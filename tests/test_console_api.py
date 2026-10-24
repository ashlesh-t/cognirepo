# pylint: disable=missing-docstring, protected-access, redefined-outer-name, unused-argument, import-outside-toplevel, wrong-import-position
# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_console_api.py — what the Engram console needs for the daemon, the watcher queue and the journal (#120)."""
import json
import os
import socket
import subprocess
import threading
import time

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the daemon uses Unix domain sockets")

from core import events  # noqa: E402
from interface.daemon import client, paths  # noqa: E402
from interface.ui import security as sec  # noqa: E402
from interface.ui.app import create_app  # noqa: E402
from interface.ui.audit import AuditLog  # noqa: E402
from interface.ui.services import ServiceManager  # noqa: E402
from tests.test_daemon import alive, daemon_env, make_repo, wait_until  # noqa: E402,F401  (fixtures + helpers)

PORT = 8765
TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def app_client(tmp_path, repo, services=None):
    cfg = sec.SecurityConfig(token=TOKEN, port=PORT, limiter=sec.AttemptLimiter(max_failures=100, base_lockout=60))
    audit = AuditLog(str(tmp_path / "ui" / "audit.log"))
    c = TestClient(create_app(cfg, repo, audit, services=services), base_url=f"http://127.0.0.1:{PORT}")
    c.audit = audit
    return c


@pytest.fixture
def api(daemon_env):
    repo = make_repo(daemon_env["tmp"])
    with app_client(daemon_env["tmp"], repo, ServiceManager(repo)) as c:
        c.repo, c.env = repo, daemon_env
        yield c


def get(c, path, **params):
    return c.get(path, params=params, headers=AUTH)


class TestDaemonEndpoint:
    def test_requires_a_token(self, api):
        assert api.get("/api/v1/daemon").status_code == 401

    def test_not_running(self, api):
        body = get(api, "/api/v1/daemon").json()
        assert body["supported"] is True and body["enabled"] is True and body["running"] is False
        assert body["workers"] == [] and body["pid"] is None

    def test_unsupported_platform_makes_no_socket_calls(self, api, monkeypatch):
        with monkeypatch.context() as mp:            # scoped: the fixture teardown must still reach the real client
            mp.setattr(paths, "SUPPORTED", False)
            mp.setattr(client, "rpc", lambda *a, **k: pytest.fail("must not touch a socket"))
            body = get(api, "/api/v1/daemon").json()
        assert body["supported"] is False and body["enabled"] is False and body["running"] is False

    def test_shows_the_supervisor_workers_and_which_one_is_served(self, api):
        other = make_repo(api.env["tmp"], "other")
        mine = client.WorkerLink(api.repo, "agent-1").open()
        theirs = client.WorkerLink(other, "agent-2").open()
        api.env["pids"].update([mine.info["pid"], theirs.info["pid"]])
        body = get(api, "/api/v1/daemon").json()
        assert body["running"] is True and body["version"] and body["pid"] and body["rss_bytes"] > 0
        assert body["max_workers"] == 4 and body["socket"].endswith("daemon.sock")
        rows = {w["repo"]: w for w in body["workers"]}
        assert set(rows) == {api.repo, other}
        assert rows[api.repo]["served"] is True and rows[other]["served"] is False
        assert rows[api.repo]["clients"] == 1 and rows[api.repo]["alive"] and rows[api.repo]["rss_bytes"] > 0
        mine.close()
        theirs.close()

    def test_a_wedged_supervisor_cannot_hang_the_endpoint(self, api):
        sock = paths.supervisor_socket()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock)
        srv.listen(8)
        held, stop = [], threading.Event()

        def silent():
            srv.settimeout(0.2)
            while not stop.is_set():
                try:
                    held.append(srv.accept()[0])
                except OSError:
                    continue

        t = threading.Thread(target=silent, daemon=True)
        t.start()
        try:
            started = time.time()
            body = get(api, "/api/v1/daemon").json()
            assert body["running"] is False and time.time() - started < 6
        finally:
            stop.set()
            t.join(2)
            for h in held:
                h.close()
            srv.close()


class TestDaemonService:
    def post(self, c, action, **body):
        return c.post(f"/api/v1/services/daemon/{action}", json={"confirm": True, **body}, headers=AUTH)

    def test_listed_with_the_other_services(self, api):
        names = [s["name"] for s in get(api, "/api/v1/services").json()]
        assert "daemon" in names
        row = next(s for s in get(api, "/api/v1/services").json() if s["name"] == "daemon")
        assert row["state"] == "stopped" and "enabled" in row["detail"]

    def test_start_then_stop_the_real_supervisor(self, api):
        r = self.post(api, "start")
        assert r.status_code == 200
        started = r.json()
        api.env["pids"].add(started["pid"])
        assert started["state"] == "running" and started["changed"] is True and alive(started["pid"])
        again = self.post(api, "start").json()
        assert again["changed"] is False and again["pid"] == started["pid"]
        assert get(api, "/api/v1/daemon").json()["running"] is True
        stopped = self.post(api, "stop").json()
        assert stopped["state"] == "stopped" and stopped["changed"] is True
        assert wait_until(lambda: not alive(started["pid"]), 15)
        assert self.post(api, "stop").json()["changed"] is False

    def test_stopping_takes_the_repo_workers_with_it(self, api):
        link = client.WorkerLink(api.repo, "a").open()
        worker_pid = link.info["pid"]
        api.env["pids"].add(worker_pid)
        link.close()
        self.post(api, "stop")
        assert wait_until(lambda: not alive(worker_pid), 20)

    def test_confirm_is_required(self, api):
        r = api.post("/api/v1/services/daemon/start", json={}, headers=AUTH)
        assert r.status_code == 400 and r.json() == {"error": "confirm_required"}
        assert get(api, "/api/v1/daemon").json()["running"] is False       # nothing was started

    def test_unsupported_platform_is_reported_not_attempted(self, api, monkeypatch):
        with monkeypatch.context() as mp:
            mp.setattr(paths, "SUPPORTED", False)
            mp.setattr(client, "ensure_supervisor", lambda: pytest.fail("must not start anything"))
            r = self.post(api, "start").json()
            listed = next(s for s in get(api, "/api/v1/services").json() if s["name"] == "daemon")
        assert r["state"] == "failed" and r["reason"] == "unsupported" and listed["state"] == "unsupported"

    def test_actions_are_audited(self, api):
        self.post(api, "start")
        api.env["pids"].add(get(api, "/api/v1/daemon").json()["pid"])
        text = open(api.audit.path, encoding="utf-8").read()
        assert "service_start" in text and '"daemon"' in text


class TestReposCarryDaemonState:
    def test_repo_with_a_worker_shows_it_others_do_not(self, api):
        quiet = make_repo(api.env["tmp"], "quiet")
        from core.config import repo_registry
        repo_registry.register_repo(quiet)
        repo_registry.register_repo(api.repo)
        assert all(r["daemon"] is None for r in get(api, "/api/v1/repos").json())        # daemon not running
        link = client.WorkerLink(api.repo, "agent").open()
        api.env["pids"].add(link.info["pid"])
        rows = {r["root"]: r for r in get(api, "/api/v1/repos").json()}
        d = rows[api.repo]["daemon"]
        assert d["pid"] == link.info["pid"] and d["alive"] is True and d["clients"] == 1 and d["rss_bytes"] > 0
        assert rows[quiet]["daemon"] is None
        link.close()

    def test_a_dead_daemon_does_not_slow_or_break_the_list(self, api):
        started = time.time()
        assert get(api, "/api/v1/repos").status_code == 200 and time.time() - started < 5


class TestQueueEndpoint:
    def store(self, api):
        d = os.path.join(api.repo, ".cognirepo", "index")
        os.makedirs(d, exist_ok=True)
        return d

    def test_no_watcher(self, api):
        assert get(api, "/api/v1/queue").json() == {"running": False}

    def test_state_of_a_running_watcher(self, api):
        with open(os.path.join(self.store(api), "watch_queue.json"), "w", encoding="utf-8") as fh:
            json.dump({"depth": 12, "max": 5000, "oldest_age_s": 0.8, "overflows": 1, "dropped": 30, "batches": 4,
                       "files": 900, "last_batch": {"files": 500, "ms": 1200.0}, "pid": os.getpid(),
                       "updated_at": "2026-01-01T00:00:00Z", "batch_max": 500}, fh)
        body = get(api, "/api/v1/queue").json()
        assert body["running"] is True and body["depth"] == 12 and body["max"] == 5000 and body["overflows"] == 1
        assert body["last_batch"] == {"files": 500, "ms": 1200.0} and "coalesced" not in body

    def test_dead_watcher_is_not_running(self, api):
        dead = subprocess.Popen(["true"])
        dead.wait()
        with open(os.path.join(self.store(api), "watch_queue.json"), "w", encoding="utf-8") as fh:
            json.dump({"depth": 99, "pid": dead.pid}, fh)
        assert get(api, "/api/v1/queue").json() == {"running": False}

    def test_other_repo_via_the_selector(self, api):
        other = make_repo(api.env["tmp"], "other")
        from core.config import repo_registry
        repo_registry.register_repo(other)
        d = os.path.join(other, ".cognirepo", "index")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "watch_queue.json"), "w", encoding="utf-8") as fh:
            json.dump({"depth": 7, "max": 100, "pid": os.getpid()}, fh)
        assert get(api, "/api/v1/queue").json() == {"running": False}
        assert get(api, "/api/v1/queue", repo="other").json()["depth"] == 7
        assert get(api, "/api/v1/queue", repo="/etc").status_code == 404


class TestJournalEndpoint:
    @pytest.fixture
    def seeded(self, api):
        store = os.path.join(api.repo, ".cognirepo")
        events.emit("tool.start", store_dir=store, tool="lookup_symbol", session_id="s")
        events.emit("graph.delta", store_dir=store, graph_seq=1, ops=[{"op": "add_node", "id": "a", "kind": "FILE"}],
                    op_count=1)
        events.emit("watcher.reindex", store_dir=store, reindexed=["a.py"], removed=[], error=None)
        events.emit("prune", store_dir=store, dry_run=False, total=10, kept=8, pruned=2)
        events.emit("service", store_dir=store, service="hooks", action="start", state="installed", ok=True)
        events.emit("tool.end", store_dir=store, tool="lookup_symbol", session_id="s")
        return api

    def test_default_types_exclude_tool_calls_and_are_oldest_first(self, seeded):
        rows = get(seeded, "/api/v1/journal").json()
        assert [r["type"] for r in rows] == ["graph.delta", "watcher.reindex", "prune", "service"]
        assert [r["seq"] for r in rows] == sorted(r["seq"] for r in rows)

    def test_tail_keeps_the_newest(self, seeded):
        rows = get(seeded, "/api/v1/journal", tail=2).json()
        assert [r["type"] for r in rows] == ["prune", "service"]

    def test_types_filter_globs(self, seeded):
        assert [r["type"] for r in get(seeded, "/api/v1/journal", types="tool.*").json()] == ["tool.start", "tool.end"]
        assert [r["type"] for r in get(seeded, "/api/v1/journal", types="prune,service").json()] == ["prune", "service"]

    @pytest.mark.parametrize("tail", [0, 501, -1])
    def test_tail_is_bounded(self, seeded, tail):
        assert get(seeded, "/api/v1/journal", tail=tail).status_code == 422

    def test_metadata_only_mode_publishes_no_node_ids(self, seeded, monkeypatch):
        monkeypatch.setenv("COGNIREPO_EVENTS_METADATA_ONLY", "1")
        from data.graph.knowledge_graph import KnowledgeGraph
        from core.config.paths import set_cognirepo_dir
        set_cognirepo_dir(os.path.join(seeded.repo, ".cognirepo"))
        kg = KnowledgeGraph()
        kg.add_node("secret_symbol_name", "FILE")
        kg.save()
        text = json.dumps(get(seeded, "/api/v1/journal").json())
        assert "secret_symbol_name" not in text and '"reset": true' in text

    def test_empty_when_nothing_happened_and_selector_errors(self, api):
        assert get(api, "/api/v1/journal").json() == []
        assert get(api, "/api/v1/journal", repo="nope").status_code == 404

    def test_requires_a_token(self, api):
        assert api.get("/api/v1/journal").status_code == 401
