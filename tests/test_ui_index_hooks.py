# pylint: disable=missing-docstring, protected-access, redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_ui_index_hooks.py — `index` / `hooks` services, auto-index setting, status flags (#211)."""
import json
import os
import subprocess
import sys

import pytest
from starlette.testclient import TestClient

from interface.ui import security as sec
from interface.ui import services as svc_mod
from interface.ui import settings as ui_settings
from interface.ui.app import create_app
from interface.ui.audit import AuditLog
from interface.ui.services import ServiceError, ServiceManager
from interface.ui.status import indexer_status

_REAL_POPEN = subprocess.Popen     # the `popen` fixture replaces subprocess.Popen
PORT = 8765
TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def repo(tmp_path):
    """A git repo with a .cognirepo/ store (the isolated_cognirepo fixture points the store here)."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    store = tmp_path / ".cognirepo"
    (store / "watchers").mkdir(parents=True, exist_ok=True)
    (store / "config.json").write_text("{}")
    return tmp_path


class FakeProc:
    _pid = 4000

    def __init__(self, rc=None, output=""):
        FakeProc._pid += 1
        self.pid, self.rc, self.output = FakeProc._pid, rc, output

    def poll(self):
        return self.rc

    def wait(self):
        return self.rc


@pytest.fixture
def popen(monkeypatch, repo):
    """Capture Popen calls; the next process is whatever the test queues."""
    state = {"calls": [], "next": FakeProc()}

    def fake(argv, **kw):
        state["calls"].append((argv, kw))
        proc = state["next"]
        kw["stdout"].write(proc.output.encode())
        return proc

    monkeypatch.setattr(svc_mod.subprocess, "Popen", fake)
    return state


class TestIndexService:
    def test_allowlisted(self):
        assert {"index", "hooks"} <= set(ServiceManager.allowed())

    def test_start_runs_fixed_incremental_argv(self, repo, popen):
        out = ServiceManager(str(repo)).start("index")
        argv, kw = popen["calls"][0]
        assert argv == [sys.executable, "-m", "interface.cli.main", "index-repo", "--changed-only"]
        assert "--force-reindex" not in argv and "shell" not in kw
        assert out["state"] == "running" and out["changed"] is True
        assert kw["env"]["COGNIREPO_PROGRESS_FILE"].endswith("ui-index-progress.json")

    def test_second_start_while_running_is_a_noop(self, repo, popen):
        mgr = ServiceManager(str(repo))
        mgr.start("index")
        again = mgr.start("index")
        assert again["changed"] is False and again["state"] == "running" and len(popen["calls"]) == 1

    def test_progress_while_running(self, repo, popen):
        mgr = ServiceManager(str(repo))
        mgr.start("index")
        (repo / ".cognirepo" / "watchers" / "ui-index-progress.json").write_text('{"done": 3, "total": 10}')
        st = mgr.status("index")
        assert st["state"] == "running" and st["progress"] == {"done": 3, "total": 10}

    def test_success_recorded(self, repo, popen):
        mgr = ServiceManager(str(repo))
        mgr.start("index")
        mgr._index_proc.rc = 0
        mgr._index_proc.output = ""
        st = mgr.status("index")
        assert st["state"] == "idle" and st["progress"] is None
        assert st["last_run"]["result"] == "ok" and st["last_run"]["exit_code"] == 0
        assert st["last_run"]["retryable"] is False

    @pytest.mark.parametrize("rc,text", [(75, "the CogniRepo store is busy"),
                                         (1, "✗ indexing is already running (pid 9) — it holds the knowledge-graph writer lease.")])
    def test_busy_is_retryable_not_an_error(self, repo, popen, rc, text):
        mgr = ServiceManager(str(repo))
        popen["next"] = FakeProc(output=text)
        mgr.start("index")
        mgr._index_proc.rc = rc
        last = mgr.status("index")["last_run"]
        assert last["result"] == "busy" and last["retryable"] is True and last["reason"] == "store_busy"

    def test_base_incomplete_flagged(self, repo, popen):
        mgr = ServiceManager(str(repo))
        popen["next"] = FakeProc(output="✗ index-repo --changed-only: not updating the graph — x.")
        mgr.start("index")
        mgr._index_proc.rc = 2
        last = mgr.status("index")["last_run"]
        assert last["result"] == "failed" and last["reason"] == "base_incomplete"
        assert "not updating the graph" in last["detail"]

    def test_other_failure(self, repo, popen):
        mgr = ServiceManager(str(repo))
        popen["next"] = FakeProc(output="Traceback...\nValueError: boom")
        mgr.start("index")
        mgr._index_proc.rc = 1
        last = mgr.status("index")["last_run"]
        assert last["reason"] == "index_failed" and "boom" in last["detail"]

    def test_new_run_clears_last_run(self, repo, popen):
        mgr = ServiceManager(str(repo))
        mgr.start("index")
        mgr._index_proc.rc = 1
        assert mgr.status("index")["last_run"]["result"] == "failed"
        popen["next"] = FakeProc()
        mgr.start("index")
        assert mgr.status("index")["last_run"] is None

    def test_not_initialised(self, tmp_path, popen):
        (tmp_path / ".cognirepo").mkdir(exist_ok=True)
        (tmp_path / ".cognirepo" / "config.json").unlink(missing_ok=True)
        out = ServiceManager(str(tmp_path)).start("index")
        assert out["state"] == "failed" and out["reason"] == "not_initialised" and popen["calls"] == []

    def test_not_stoppable(self, repo):
        with pytest.raises(ServiceError) as exc:
            ServiceManager(str(repo)).stop("index")
        assert exc.value.status == 409


class TestRealIndexRun:
    def test_incremental_run_without_base_graph_reports_base_incomplete(self, repo, monkeypatch):
        """End to end through the real CLI: no graph yet -> the refusal is classified, not a generic failure."""
        (repo / "a.py").write_text("def f():\n    return 1\n")
        subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                        "commit", "-qm", "x"], cwd=repo, check=True)
        (repo / "a.py").write_text("def f():\n    return 2\n")
        monkeypatch.setenv("COGNIREPO_NO_WATCHER", "1")
        mgr = ServiceManager(str(repo))
        mgr.start("index")
        mgr._index_proc.wait(timeout=120)
        last = mgr.status("index")["last_run"]
        assert last["result"] == "failed" and last["reason"] == "base_incomplete", last


class TestHooksService:
    def test_install_then_uninstall_for_real(self, repo):
        mgr = ServiceManager(str(repo))
        assert mgr.status("hooks")["state"] == "not_installed"
        out = mgr.start("hooks")
        assert out["state"] == "installed" and out["changed"] is True
        assert "cognirepo" in (repo / ".git" / "hooks" / "post-commit").read_text().lower()
        assert mgr.start("hooks")["changed"] is False          # idempotent
        out = mgr.stop("hooks")
        assert out["state"] == "not_installed" and out["changed"] is True
        assert mgr.stop("hooks")["changed"] is False

    def test_not_a_git_repo(self, tmp_path):
        out = ServiceManager(str(tmp_path)).start("hooks")
        assert out["state"] == "failed" and out["reason"] == "not_a_git_repo"

    def test_user_hook_content_is_preserved(self, repo):
        hook = repo / ".git" / "hooks" / "post-commit"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text("#!/bin/sh\necho mine\n")
        mgr = ServiceManager(str(repo))
        mgr.start("hooks")
        mgr.stop("hooks")
        assert "echo mine" in hook.read_text()


@pytest.fixture
def client(repo):
    cfg = sec.SecurityConfig(token=TOKEN, port=PORT, limiter=sec.AttemptLimiter(max_failures=3, base_lockout=60))
    audit = AuditLog(str(repo / "ui" / "audit.log"))
    with TestClient(create_app(cfg, str(repo), audit), base_url=f"http://127.0.0.1:{PORT}") as c:
        c.audit = audit
        yield c


class TestAutoIndexSetting:
    def post(self, client, **body):
        return client.post("/api/v1/settings/auto-index", json=body, headers=AUTH)

    def test_requires_token(self, client):
        assert client.post("/api/v1/settings/auto-index", json={"enabled": True, "confirm": True}).status_code == 401

    def test_requires_confirm(self, client, repo):
        assert self.post(client, enabled=False).status_code == 400
        assert self.post(client, enabled=False, confirm="true").status_code == 422   # strict bool
        assert json.loads((repo / ".cognirepo" / "config.json").read_text()) == {}

    def test_persists_and_preserves_other_keys(self, client, repo):
        cfg = repo / ".cognirepo" / "config.json"
        cfg.write_text(json.dumps({"storage": {"encrypt": True}, "watch": {"debounce": 2}}))
        r = self.post(client, enabled=False, confirm=True)
        assert r.status_code == 200 and r.json() == {"auto_index": False, "changed": True}
        saved = json.loads(cfg.read_text())
        assert saved["watch"] == {"debounce": 2, "auto_enabled": False} and saved["storage"] == {"encrypt": True}
        assert self.post(client, enabled=False, confirm=True).json()["changed"] is False
        assert client.get("/api/v1/status", headers=AUTH).json()["indexer"]["auto_index"] is False

    def test_missing_config_is_a_conflict(self, client, repo):
        os.remove(repo / ".cognirepo" / "config.json")
        r = self.post(client, enabled=True, confirm=True)
        assert r.status_code == 409 and r.json() == {"error": "not_initialised"}

    def test_audited(self, client):
        self.post(client, enabled=True, confirm=True)
        events = [json.loads(line) for line in open(client.audit.path, encoding="utf-8")]
        assert any(e.get("event") == "setting_auto_index" and e.get("result") == "ok" for e in events) or \
            any("setting_auto_index" in json.dumps(e) for e in events)

    def test_explicit_vs_default(self, repo):
        store = str(repo / ".cognirepo")
        assert ui_settings.explicit_auto_index(store) is False        # absent: default, not acted on
        ui_settings.set_auto_index(store, True)
        assert ui_settings.explicit_auto_index(store) is True
        ui_settings.set_auto_index(store, False)
        assert ui_settings.explicit_auto_index(store) is False


class TestWatcherStartsWithUi:
    def make(self, repo, calls):
        class Fake:
            @staticmethod
            def allowed():
                return ServiceManager.allowed()

            def start(self, name):
                calls.append(name)
                return {"name": name, "state": "running"}

            def status(self, name=None):
                return []

            def shutdown(self):
                pass

        cfg = sec.SecurityConfig(token=TOKEN, port=PORT)
        return TestClient(create_app(cfg, str(repo), None, services=Fake()), base_url=f"http://127.0.0.1:{PORT}")

    def test_explicit_true_starts_watcher(self, repo):
        import time
        ui_settings.set_auto_index(str(repo / ".cognirepo"), True)
        calls = []
        with self.make(repo, calls):
            deadline = time.monotonic() + 3
            while not calls and time.monotonic() < deadline:
                time.sleep(0.05)
        assert calls == ["watcher"]

    @pytest.mark.parametrize("value", [None, False])
    def test_default_or_false_does_not(self, repo, value):
        import time
        if value is not None:
            ui_settings.set_auto_index(str(repo / ".cognirepo"), value)
        calls = []
        with self.make(repo, calls):
            time.sleep(0.3)
        assert calls == []


class TestStatusFlags:
    def test_base_incomplete_comes_from_the_watchers_last_batch(self, repo):
        idx = repo / ".cognirepo" / "index"
        idx.mkdir(parents=True, exist_ok=True)
        assert indexer_status(str(repo))["graph_base_incomplete"] is False
        (idx / "last_watcher_reindex.json").write_text(json.dumps(
            {"reindexed": ["a.py"], "removed": [], "error": None, "graph_skipped": "there is no graph on disk"}))
        st = indexer_status(str(repo))
        assert st["graph_base_incomplete"] is True and st["last_watcher_reindex"]["reindexed"] == ["a.py"]
        (idx / "last_watcher_reindex.json").write_text(json.dumps({"reindexed": [], "graph_skipped": None}))
        assert indexer_status(str(repo))["graph_base_incomplete"] is False

    def test_watcher_records_why_the_graph_was_skipped(self, repo):
        from types import SimpleNamespace
        from intelligence.indexer.file_watcher import RepoFileHandler
        h = object.__new__(RepoFileHandler)
        h.repo_root, h.session_id = str(repo), "s"
        h.indexer = SimpleNamespace(index_data={"files": {}})
        saved = []
        h.graph = SimpleNamespace(incremental_base_status=lambda n: (False, "no graph on disk"),
                                  save=lambda: saved.append(1))
        h._save_graph()
        h._write_last_watcher_reindex(["a.py"], [])
        rec = json.loads((repo / ".cognirepo" / "index" / "last_watcher_reindex.json").read_text())
        assert saved == [] and rec["graph_skipped"] == "no graph on disk"
        h.graph = SimpleNamespace(incremental_base_status=lambda n: (True, ""), save=lambda: saved.append(1))
        h._save_graph()
        h._write_last_watcher_reindex(["a.py"], [])
        rec = json.loads((repo / ".cognirepo" / "index" / "last_watcher_reindex.json").read_text())
        assert saved == [1] and rec["graph_skipped"] is None


class TestProgressFile:
    def test_inert_without_env(self, tmp_path):
        from interface.cli.main import _ProgressFile
        before = sorted(os.listdir(tmp_path))
        pf = _ProgressFile(None, 5)
        pf.tick(1, force=True)
        assert sorted(os.listdir(tmp_path)) == before

    def test_writes_done_and_total(self, tmp_path):
        from interface.cli.main import _ProgressFile
        path = tmp_path / "p.json"
        pf = _ProgressFile(str(path), 7)
        assert json.loads(path.read_text()) == {"done": 0, "total": 7}
        pf.tick(3, force=True)
        assert json.loads(path.read_text()) == {"done": 3, "total": 7}

    def test_write_failure_never_raises(self, tmp_path):
        from interface.cli.main import _ProgressFile
        (tmp_path / "file").write_text("x")
        pf = _ProgressFile(str(tmp_path / "file" / "p.json"), 2)     # a parent that is a regular file
        pf.tick(1, force=True)
        assert pf.path is None


class TestRunStateSurvivesRestart:
    def test_last_run_outlives_the_server(self, repo, popen):
        mgr = ServiceManager(str(repo))
        popen["next"] = FakeProc(output="Re-indexed 2 changed file(s): a.py")
        mgr.start("index")
        mgr._index_proc.rc = 0
        assert mgr.status("index")["last_run"]["result"] == "ok"
        fresh = ServiceManager(str(repo))                      # UI server restarted
        st = fresh.status("index")
        assert st["state"] == "idle" and st["last_run"]["result"] == "ok"

    def test_run_started_by_a_previous_server_is_still_running(self, repo, popen):
        mgr = ServiceManager(str(repo))
        mgr.start("index")
        fresh = ServiceManager(str(repo))
        # the old server's child, which is alive: point the record at this very process
        run = repo / ".cognirepo" / "watchers" / "ui-index-run.json"
        run.write_text(json.dumps({"pid": os.getpid(), "started_epoch": __import__("time").time()}))
        assert fresh.status("index")["state"] == "running"
        assert fresh.start("index")["changed"] is False
        assert len(popen["calls"]) == 1                        # no second indexer spawned

    def test_finished_orphan_run_is_classified_from_its_log(self, repo, popen):
        ServiceManager(str(repo)).start("index")
        dead = _REAL_POPEN([sys.executable, "-c", "pass"])
        dead.wait()
        (repo / ".cognirepo" / "watchers" / "ui-index-run.json").write_text(
            json.dumps({"pid": dead.pid, "started_epoch": __import__("time").time() - 5}))
        (repo / ".cognirepo" / "watchers" / "ui-index.log").write_text("Re-indexed 2 changed file(s): a.py\n", encoding="utf-8")
        last = ServiceManager(str(repo)).status("index")["last_run"]
        assert last["result"] == "ok" and last["exit_code"] is None

    def test_orphan_with_busy_log_is_busy(self, repo, popen):
        ServiceManager(str(repo)).start("index")
        dead = _REAL_POPEN([sys.executable, "-c", "pass"])
        dead.wait()
        (repo / ".cognirepo" / "watchers" / "ui-index-run.json").write_text(
            json.dumps({"pid": dead.pid, "started_epoch": __import__("time").time()}))
        (repo / ".cognirepo" / "watchers" / "ui-index.log").write_text("✗ indexing is already running (pid 9)\n", encoding="utf-8")
        assert ServiceManager(str(repo)).status("index")["last_run"]["retryable"] is True

    def test_ancient_record_is_not_trusted_even_if_the_pid_is_alive(self, repo, popen):
        ServiceManager(str(repo)).start("index")
        (repo / ".cognirepo" / "watchers" / "ui-index-run.json").write_text(
            json.dumps({"pid": os.getpid(), "started_epoch": __import__("time").time() - 7 * 3600}))
        st = ServiceManager(str(repo)).status("index")
        assert st["state"] == "idle" and st["last_run"] is not None


class TestBaseFlagSupersededByFullIndex:
    def test_graph_written_after_the_record_clears_the_flag(self, repo):
        idx, graph = repo / ".cognirepo" / "index", repo / ".cognirepo" / "graph"
        idx.mkdir(parents=True, exist_ok=True)
        graph.mkdir(parents=True, exist_ok=True)
        rec = idx / "last_watcher_reindex.json"
        rec.write_text(json.dumps({"graph_skipped": "no graph on disk"}))
        assert indexer_status(str(repo))["graph_base_incomplete"] is True       # no graph at all
        pkl = graph / "graph.pkl"
        pkl.write_bytes(b"x")
        os.utime(rec, (1000, 1000))
        os.utime(pkl, (2000, 2000))                                             # full index ran afterwards
        assert indexer_status(str(repo))["graph_base_incomplete"] is False
        os.utime(pkl, (500, 500))                                               # graph older than the skip
        assert indexer_status(str(repo))["graph_base_incomplete"] is True


class TestWatcherAlreadyRunning:
    def test_start_with_a_live_watcher_spawns_nothing(self, repo, monkeypatch):
        mgr = ServiceManager(str(repo))
        monkeypatch.setattr(mgr, "_watcher_record", lambda: {"pid": 1234})
        monkeypatch.setattr(mgr, "_spawn_watcher", lambda: pytest.fail("a second watcher must not start"))
        out = mgr.start("watcher")
        assert out["state"] == "running" and out["changed"] is False and out["pid"] == 1234


def _cli(repo, *args, env_extra=None):
    env = {**os.environ, "COGNIREPO_NO_WATCHER": "1", "COGNIREPO_GLOBAL_DIR": str(repo / ".g")}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-m", "interface.cli.main", *args], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=240, check=False)


class TestRealRuns:
    def test_incremental_run_succeeds_with_progress(self, repo, monkeypatch):
        """Real CLI end to end: complete base graph, then the UI index service over a changed file."""
        import time
        monkeypatch.setenv("COGNIREPO_NO_WATCHER", "1")
        monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(repo / ".g"))
        (repo / "a.py").write_text("def f():\n    return 1\n")
        subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                        "commit", "-qm", "x"], cwd=repo, check=True)
        assert _cli(repo, "index-repo", ".", "--no-embed", "--no-watch").returncode == 0
        (repo / "a.py").write_text("def f():\n    return 2\n")
        mgr = ServiceManager(str(repo))
        assert mgr.start("index")["state"] == "running"
        deadline = time.monotonic() + 120
        while mgr.status("index")["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.1)
        st = mgr.status("index")
        assert st["last_run"]["result"] == "ok" and st["last_run"]["exit_code"] == 0, st
        progress = json.loads((repo / ".cognirepo" / "watchers" / "ui-index-progress.json").read_text())
        assert progress == {"done": 1, "total": 1}
        assert mgr.status("index")["last_run"]["result"] == "ok"
        assert ServiceManager(str(repo)).status("index")["last_run"]["result"] == "ok"   # after a "restart"


class TestRealIndexRace:
    """Two writers on one store (the UI service and/or the CLI) must serialise, never corrupt (#211)."""

    def _prepare(self, repo, monkeypatch, files=6):
        monkeypatch.setenv("COGNIREPO_NO_WATCHER", "1")
        monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(repo / ".g"))
        for i in range(files):
            (repo / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                        "commit", "-qm", "x"], cwd=repo, check=True)
        assert _cli(repo, "index-repo", ".", "--no-embed", "--no-watch").returncode == 0
        for i in range(files):
            (repo / f"m{i}.py").write_text(f"def f{i}():\n    return {i + 100}\n")

    @staticmethod
    def _graph_is_intact(repo):
        import pickle
        with open(repo / ".cognirepo" / "graph" / "graph.pkl", "rb") as fh:
            nodes = pickle.load(fh).number_of_nodes()
        assert nodes > 0
        return nodes

    def test_two_cli_runs_at_once_serialise_and_leave_an_intact_graph(self, repo, monkeypatch):
        self._prepare(repo, monkeypatch)
        before = self._graph_is_intact(repo)
        env = {**os.environ, "COGNIREPO_NO_WATCHER": "1", "COGNIREPO_GLOBAL_DIR": str(repo / ".g")}
        argv = [sys.executable, "-m", "interface.cli.main", "index-repo", "--changed-only"]
        procs = [subprocess.Popen(argv, cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True) for _ in range(2)]
        outs = [(p.communicate(timeout=240)[0], p.returncode) for p in procs]
        codes = [rc for _, rc in outs]
        assert 0 in codes, outs                                    # at least one finished its work
        for text, rc in outs:
            assert rc in (0, 75) or "already running" in text, (rc, text)   # the other: done, or told "busy"
        assert self._graph_is_intact(repo) >= before

    def test_service_run_alongside_a_cli_run_is_ok_or_busy_never_failed(self, repo, monkeypatch):
        import time
        self._prepare(repo, monkeypatch)
        env = {**os.environ, "COGNIREPO_NO_WATCHER": "1", "COGNIREPO_GLOBAL_DIR": str(repo / ".g")}
        cli = subprocess.Popen([sys.executable, "-m", "interface.cli.main", "index-repo", "--changed-only"],
                               cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        mgr = ServiceManager(str(repo))
        assert mgr.start("index")["state"] == "running"
        deadline = time.monotonic() + 180
        while mgr.status("index")["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.1)
        cli.communicate(timeout=240)
        last = mgr.status("index")["last_run"]
        assert last["result"] in ("ok", "busy"), last              # busy is retryable, not an error
        if last["result"] == "busy":
            assert last["retryable"] is True and last["reason"] == "store_busy"
        self._graph_is_intact(repo)


class TestRealWatcherOnUiStart:
    def test_ui_start_launches_one_real_watcher_and_not_a_second(self, repo, monkeypatch):
        import time
        monkeypatch.delenv("COGNIREPO_NO_WATCHER", raising=False)
        monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(repo / ".g"))
        (repo / "a.py").write_text("x = 1\n")
        ui_settings.set_auto_index(str(repo / ".cognirepo"), True)
        mgr = ServiceManager(str(repo))
        cfg = sec.SecurityConfig(token=TOKEN, port=PORT)
        try:
            with TestClient(create_app(cfg, str(repo), None, services=mgr), base_url=f"http://127.0.0.1:{PORT}"):
                deadline = time.monotonic() + 30
                while mgr.status("watcher")["state"] != "running" and time.monotonic() < deadline:
                    time.sleep(0.2)
                first = mgr.status("watcher")
                assert first["state"] == "running" and first["pid"]
                again = mgr.start("watcher")                       # a second start must find the first
                assert again["changed"] is False and again["pid"] == first["pid"]
        finally:
            mgr.stop("watcher")
        assert mgr.status("watcher")["state"] == "stopped"
