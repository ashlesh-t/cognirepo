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

    pid = daemon.spawn_detached_watcher(str(tmp_path), str(tmp_path / ".cognirepo" / "w.log"))
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
    pid = daemon.spawn_detached_watcher(str(tmp_path), str(tmp_path / ".cognirepo" / "w.log"))
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
    pid = daemon.spawn_detached_watcher(str(tmp_path), str(tmp_path / ".cognirepo" / "w.log"))
    try:
        _wait_registered(tmp_path, pid)
    finally:
        _stop(tmp_path, pid)


def test_ensure_running_does_not_load_the_graph_or_index(isolated_cognirepo, tmp_path, monkeypatch):
    """`watch --ensure-running` used to build a KnowledgeGraph + ASTIndexer only to discard them."""
    import interface.cli.main as cli
    from interface.cli import daemon
    from data.graph import knowledge_graph
    from intelligence.indexer import ast_indexer
    spawned = []
    monkeypatch.setattr(daemon, "spawn_detached_watcher", lambda repo, log: spawned.append(repo) or 999999)
    monkeypatch.setattr(knowledge_graph.KnowledgeGraph, "__init__",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("graph loaded")))
    monkeypatch.setattr(ast_indexer.ASTIndexer, "__init__",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("index loaded")))
    monkeypatch.setattr(sys, "argv", ["cognirepo", "watch", "--ensure-running", "--path", str(tmp_path)])
    cli.main()
    assert spawned == [str(tmp_path)]
