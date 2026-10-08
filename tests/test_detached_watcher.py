# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""`index-repo --daemon` / `watch --ensure-running` start a FRESH watcher process (COGNIREPO-127).

Before: the daemon was a double-fork of the calling process, so it inherited that process's whole heap
(after `index-repo`: embedder + FAISS + every parsed AST) — measured 3.3-3.5 GB RSS against ~100 MB for
a fresh watcher on the same index — and, being a fork of a threaded process, was seen ignoring SIGTERM
for 30 s. Its argv was also its parent's (`init`, `index-repo`), which is what #119's "leaked init
processes" were: watchers nobody could recognise.
"""
import os
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="daemon management is Linux-only")


def _rss_mb(pid):
    with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    raise AssertionError("no VmRSS")


def _wait_registered(repo, pid, timeout=60.0):
    from interface.cli import daemon
    end = time.time() + timeout
    while time.time() < end:
        rec = daemon.is_watcher_running_for_path(str(repo))
        if rec and rec["pid"] == pid:
            return rec
        time.sleep(0.1)
    raise AssertionError("detached watcher never registered")


def _stop(repo, pid):
    from interface.cli import daemon
    out = daemon.stop_watcher_and_wait(str(pid))
    assert out == "stopped", out


@pytest.mark.timeout(180)
def test_detached_watcher_does_not_inherit_the_callers_heap(isolated_cognirepo, tmp_path):
    from interface.cli import daemon
    (tmp_path / "a.py").write_text("def f():\n    pass\n")
    heap = bytearray(600 * 1024 * 1024)            # stands in for the embedder/FAISS/AST heap
    for i in range(0, len(heap), 4096):
        heap[i] = 1                                 # touch every page so it is resident
    parent_rss = _rss_mb(os.getpid())
    assert parent_rss > 600

    pid = daemon.spawn_detached_watcher(str(tmp_path), str(tmp_path / ".cognirepo" / "w.log")).pid
    try:
        _wait_registered(tmp_path, pid)
        child_rss = _rss_mb(pid)
        assert child_rss < 300, f"detached watcher is {child_rss:.0f} MB; the caller holds {parent_rss:.0f} MB"
    finally:
        _stop(tmp_path, pid)
        del heap


@pytest.mark.timeout(120)
def test_detached_watcher_is_recognisable_and_stops_promptly(isolated_cognirepo, tmp_path):
    from interface.cli import daemon
    pid = daemon.spawn_detached_watcher(str(tmp_path), str(tmp_path / ".cognirepo" / "w.log")).pid
    try:
        rec = _wait_registered(tmp_path, pid)
        assert rec["log"] == str(tmp_path / ".cognirepo" / "w.log")        # `list --view` can find it
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode()
        assert "watch --foreground" in cmd and "init" not in cmd.split("main")[-1]
        assert os.getsid(pid) == pid                                        # own session: survives the terminal
    finally:
        t0 = time.time()
        _stop(tmp_path, pid)
        assert time.time() - t0 < 15, "a fresh watcher must stop on SIGTERM, not need SIGKILL"


@pytest.mark.timeout(120)
def test_a_repo_with_its_own_interface_package_does_not_shadow_cognirepo(isolated_cognirepo, tmp_path):
    """The watcher runs with cwd = the repo; without `-P` its `interface/` would be imported instead."""
    from interface.cli import daemon
    (tmp_path / "interface").mkdir()
    (tmp_path / "interface" / "__init__.py").write_text("raise RuntimeError('the repo shadowed cognirepo')\n")
    pid = daemon.spawn_detached_watcher(str(tmp_path), str(tmp_path / ".cognirepo" / "w.log")).pid
    try:
        _wait_registered(tmp_path, pid)
    finally:
        _stop(tmp_path, pid)


def test_ensure_running_does_not_load_the_graph_or_index(real_watcher_spawn, isolated_cognirepo, tmp_path, monkeypatch):
    """`watch --ensure-running` used to build a KnowledgeGraph + ASTIndexer only to discard them."""
    import interface.cli.main as cli
    from interface.cli import daemon
    from data.graph import knowledge_graph
    from intelligence.indexer import ast_indexer
    spawned = []

    class _Exited:                                  # a child that exited at once, exit code 0
        pid = 999999

        def poll(self):
            return 0

    monkeypatch.setattr(daemon, "spawn_detached_watcher", lambda repo, log: spawned.append(repo) or _Exited())
    monkeypatch.setattr(knowledge_graph.KnowledgeGraph, "__init__",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("graph loaded")))
    monkeypatch.setattr(ast_indexer.ASTIndexer, "__init__",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("index loaded")))
    monkeypatch.setattr(sys, "argv", ["cognirepo", "watch", "--ensure-running", "--path", str(tmp_path)])
    cli.main()
    assert spawned == [str(tmp_path)]


# ── review of #171 ────────────────────────────────────────────────────────────

class TestSpawnRobustness:
    def test_unstartable_process_is_a_clean_error_not_a_traceback(self, isolated_cognirepo, tmp_path, monkeypatch):
        from interface.cli import daemon
        monkeypatch.setattr(daemon.sys, "executable", str(tmp_path / "no-such-python"))
        with pytest.raises(daemon.WatcherSpawnError, match="could not start the watcher process"):
            daemon.spawn_detached_watcher(str(tmp_path), str(tmp_path / ".cognirepo" / "w.log"))

    def test_missing_cwd_is_a_clean_error(self, isolated_cognirepo, tmp_path):
        from interface.cli import daemon
        with pytest.raises(daemon.WatcherSpawnError):
            daemon.spawn_detached_watcher(str(tmp_path / "gone"), str(tmp_path / ".cognirepo" / "w.log"))

    def test_returns_the_popen_so_the_exit_code_is_observable(self, isolated_cognirepo, tmp_path):
        import subprocess
        from interface.cli import daemon
        proc = daemon.spawn_detached_watcher(str(tmp_path), str(tmp_path / ".cognirepo" / "w.log"))
        try:
            assert isinstance(proc, subprocess.Popen) and proc.pid > 0
        finally:
            _wait_registered(tmp_path, proc.pid)
            daemon.stop_watcher_and_wait(str(proc.pid))
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=30)


class TestWatcherEnv:
    def test_package_root_is_appended_after_existing_entries(self, isolated_cognirepo, tmp_path, monkeypatch):
        from interface.cli import daemon
        monkeypatch.setenv("PYTHONPATH", os.pathsep.join(["/a/first", "/b/second"]))
        parts = daemon._watcher_env(str(tmp_path / "w.log"))["PYTHONPATH"].split(os.pathsep)  # pylint: disable=protected-access
        assert parts[:2] == ["/a/first", "/b/second"] and parts[-1] == daemon._PACKAGE_ROOT  # pylint: disable=protected-access
        assert str(tmp_path) not in parts, "the user's repo must never be on the path (shadowing)"

    def test_package_root_is_not_duplicated_and_works_without_pythonpath(self, isolated_cognirepo, monkeypatch):
        from interface.cli import daemon
        monkeypatch.delenv("PYTHONPATH", raising=False)
        assert daemon._watcher_env("x")["PYTHONPATH"] == daemon._PACKAGE_ROOT  # pylint: disable=protected-access
        monkeypatch.setenv("PYTHONPATH", daemon._PACKAGE_ROOT)  # pylint: disable=protected-access
        assert daemon._watcher_env("x")["PYTHONPATH"] == daemon._PACKAGE_ROOT  # pylint: disable=protected-access

    def test_package_root_contains_the_interface_package(self):
        from interface.cli import daemon
        assert os.path.isfile(os.path.join(daemon._PACKAGE_ROOT, "interface", "cli", "daemon.py"))  # pylint: disable=protected-access


class _FakeChild:
    def __init__(self, code):
        self.pid, self._code = 987654, code

    def poll(self):
        return self._code


class TestStartupReporting:
    """`_start_watcher(daemon=True)` says what really happened to the child."""

    def _run(self, monkeypatch, tmp_path, child, log_text=""):
        import interface.cli.main as cli
        from interface.cli import daemon
        monkeypatch.delenv("COGNIREPO_NO_WATCHER", raising=False)

        def _spawn(_repo, log):
            os.makedirs(os.path.dirname(log), exist_ok=True)
            with open(log, "w", encoding="utf-8") as fh:
                fh.write(log_text)
            return child

        monkeypatch.setattr(daemon, "spawn_detached_watcher", _spawn)
        monkeypatch.setattr(daemon, "is_watcher_running_for_path", lambda _p: None)
        cli._start_watcher(str(tmp_path), None, None, daemon=True)  # pylint: disable=protected-access

    def test_a_child_that_crashes_on_startup_is_reported_with_its_exit_code_and_log(
            self, real_watcher_spawn, isolated_cognirepo, tmp_path, monkeypatch, capsys):
        self._run(monkeypatch, tmp_path, _FakeChild(3), "Traceback...\nImportError: no module named x\n")
        io = capsys.readouterr()
        assert "exited with code 3" in io.err and "ImportError: no module named x" in io.err
        assert "did not register" not in io.err and "still starting" not in io.err

    def test_a_slow_child_is_reported_as_still_starting(self, real_watcher_spawn, isolated_cognirepo,
                                                        tmp_path, monkeypatch, capsys):
        import interface.cli.main as cli
        ticks = iter([0.0, 0.0, 31.0, 31.0, 31.0])
        monkeypatch.setattr(cli.time, "monotonic", lambda: next(ticks, 99.0))
        self._run(monkeypatch, tmp_path, _FakeChild(None))
        io = capsys.readouterr()
        assert "still starting after 30s" in io.err and "exited with code" not in io.err

    def test_the_wait_is_announced_up_front(self, real_watcher_spawn, isolated_cognirepo, tmp_path, monkeypatch, capsys):
        self._run(monkeypatch, tmp_path, _FakeChild(0))
        assert "Starting the background watcher" in capsys.readouterr().out

    def test_spawn_failure_is_a_message_not_a_traceback(self, real_watcher_spawn, isolated_cognirepo,
                                                       tmp_path, monkeypatch, capsys):
        import interface.cli.main as cli
        from interface.cli import daemon
        monkeypatch.delenv("COGNIREPO_NO_WATCHER", raising=False)

        def _boom(*_a):
            raise daemon.WatcherSpawnError("could not start the watcher process (x): nope")

        monkeypatch.setattr(daemon, "spawn_detached_watcher", _boom)
        monkeypatch.setattr(daemon, "is_watcher_running_for_path", lambda _p: None)
        cli._start_watcher(str(tmp_path), None, None, daemon=True)  # pylint: disable=protected-access
        assert "Error: could not start the watcher process" in capsys.readouterr().err


class TestStateIsPersistedBeforeTheWatcherStarts:
    """The new process reads from disk; the old fork shared our memory. A full index must be complete
    on disk by the time `_start_watcher` runs, or the watcher starts on a stale/partial index."""

    @pytest.mark.timeout(180)
    def test_a_fresh_process_sees_exactly_what_index_repo_produced(self, isolated_cognirepo, tmp_path, monkeypatch):
        import json
        import subprocess
        import interface.cli.main as cli
        for n in range(5):
            (tmp_path / f"m{n}.py").write_text(f"def f{n}():\n    return {n}\n\ndef g{n}():\n    return f{n}()\n")
        monkeypatch.setenv("COGNIREPO_NO_WATCHER", "1")
        _summary, kg, indexer = cli._direct_index(str(tmp_path), embed=False)  # pylint: disable=protected-access
        in_proc_nodes = kg.G.number_of_nodes()
        # NB: index_repo() frees the in-memory index afterwards (free_large_objects), so the old
        # forked watcher inherited an EMPTY index; only what is on disk is the truth.
        assert indexer.index_data.get("files") == {}
        expected_files = sorted(f"m{n}.py" for n in range(5))
        code = ("import json,sys\n"
                "sys.path.insert(0, %r)\n"
                "from data.graph.knowledge_graph import KnowledgeGraph\n"
                "from intelligence.indexer.ast_indexer import ASTIndexer\n"
                "kg = KnowledgeGraph(); ix = ASTIndexer(graph=kg); ix.load()\n"
                "print(json.dumps([kg.G.number_of_nodes(), sorted(ix.index_data['files'])]))\n"
                % os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        env = dict(os.environ, COGNIREPO_DIR=str(tmp_path / ".cognirepo"))
        out = subprocess.run([sys.executable, "-c", code], env=env, cwd=str(tmp_path),
                             capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
        nodes, files = json.loads(out)
        assert [os.path.basename(f) for f in files] == expected_files
        assert nodes == in_proc_nodes, "graph on disk differs from the one in memory when the watcher would start"
