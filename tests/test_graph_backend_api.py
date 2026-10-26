# pylint: disable=missing-docstring, redefined-outer-name, unused-argument, import-outside-toplevel
# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""Control API for the graph backend: accurate state, a toggle that never lands on stale data, and migration jobs."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

import pytest
from starlette.testclient import TestClient

from core.config.paths import get_cognirepo_dir
from interface.ui import security as sec
from interface.ui.app import create_app
from interface.ui.audit import AuditLog

PORT = 8771
TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
_REPO = pathlib.Path(__file__).resolve().parent.parent
STATE, SWITCH, MIGRATE, JOB = ("/api/v1/graph/backend", "/api/v1/graph/backend/switch",
                               "/api/v1/graph/backend/migrate", "/api/v1/graph/backend/job")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(_REPO))
    monkeypatch.setenv("COGNIREPO_NO_WATCHER", "1")
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / ".g"))
    monkeypatch.delenv("COGNIREPO_GRAPH_BACKEND", raising=False)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (pathlib.Path(get_cognirepo_dir()) / "watchers").mkdir(parents=True, exist_ok=True)
    (pathlib.Path(get_cognirepo_dir()) / "config.json").write_text("{}")
    return tmp_path


def _index(repo):
    for i in range(4):
        (repo / f"m{i}.py").write_text(f"def f{i}():\n    return g{i}()\n\ndef g{i}():\n    return {i}\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                    "commit", "-qm", "x"], cwd=repo, check=True)
    done = subprocess.run([sys.executable, "-m", "interface.cli.main", "index-repo", ".", "--no-embed", "--no-watch"],
                          cwd=repo, capture_output=True, text=True, check=False, timeout=240)
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.fixture
def api(repo):
    cfg = sec.SecurityConfig(token=TOKEN, port=PORT, limiter=sec.AttemptLimiter(max_failures=100, base_lockout=60))
    audit = AuditLog(str(repo / "ui" / "audit.log"))
    with TestClient(create_app(cfg, str(repo), audit), base_url=f"http://127.0.0.1:{PORT}") as c:
        c.audit, c.repo = audit, repo
        yield c


def state(api, **params):
    return api.get(STATE, params=params, headers=AUTH).json()


def post(api, path, **body):
    return api.post(path, json=body, headers=AUTH)


def wait_job(api, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = api.get(JOB, headers=AUTH).json()
        if job["state"] != "running":
            return job
        time.sleep(0.2)
    pytest.fail("migration job did not finish")


def audit_lines(api):
    path = api.repo / "ui" / "audit.log"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class TestAuth:
    @pytest.mark.parametrize("method,path", [("get", STATE), ("get", JOB), ("post", SWITCH), ("post", MIGRATE)])
    def test_every_route_needs_a_token(self, api, method, path):
        assert getattr(api, method)(path).status_code == 401


class TestState:
    def test_default_repo_reports_networkx_and_why(self, api):
        _index(api.repo)
        st = state(api)
        assert (st["active"], st["configured"], st["env_override"]) == ("networkx", "networkx", None)
        assert st["files"]["networkx"]["exists"] and not st["files"]["sqlite"]["exists"]
        assert st["nodes"] > 0 and st["edges"] > 0
        assert st["recommendation"]["use"] == "networkx" and st["recommendation"]["reasons"]
        assert st["can_toggle"] is True and st["switch_to"] == "sqlite" and st["switch_needs_migration"] is True
        assert st["job"]["state"] == "idle"

    def test_env_override_is_reported_and_blocks_the_toggle(self, api, monkeypatch):
        monkeypatch.setenv("COGNIREPO_GRAPH_BACKEND", "sqlite")
        st = state(api)
        assert st["active"] == "sqlite" and st["configured"] == "networkx"
        assert st["env_override"] == "sqlite" and st["can_toggle"] is False and st["toggle_blocker"] == "env_override"
        assert post(api, SWITCH, to="networkx", confirm=True).status_code == 409

    def test_encryption_forces_networkx_and_blocks_sqlite(self, api):
        (pathlib.Path(get_cognirepo_dir()) / "config.json").write_text(
            json.dumps({"storage": {"encrypt": True, "graph_backend": "sqlite"}}))
        st = state(api)
        assert (st["active"], st["configured"], st["forced_by_encryption"]) == ("networkx", "sqlite", True)
        assert st["note"] and st["recommendation"]["use"] == "networkx"
        assert post(api, SWITCH, to="sqlite", confirm=True).status_code == 409
        assert post(api, MIGRATE, to="sqlite", confirm=True).status_code == 409

    def test_unknown_repo_selector_is_a_404(self, api):
        assert api.get(STATE, params={"repo": "/etc"}, headers=AUTH).status_code == 404

    def test_writes_are_only_for_the_served_repo(self, api):
        other = api.post(SWITCH + "?repo=/etc", json={"to": "sqlite", "confirm": True}, headers=AUTH)
        assert other.status_code in (403, 404)


class TestToggle:
    def test_needs_an_explicit_confirm_and_is_audited(self, api):
        for body in ({"to": "sqlite"}, {"to": "sqlite", "confirm": "yes"}, {"to": "sqlite", "confirm": 1}):
            assert api.post(SWITCH, json=body, headers=AUTH).status_code in (400, 422)
        assert state(api)["configured"] == "networkx"
        assert any(e.get("result") == "denied_no_confirm" for e in audit_lines(api))

    def test_rejects_an_unknown_backend(self, api):
        assert post(api, SWITCH, to="postgres", confirm=True).status_code == 422

    def test_a_repo_with_no_graph_just_flips_the_setting(self, api):
        res = post(api, SWITCH, to="sqlite", confirm=True).json()
        assert res["action"] == "switched" and res["state"]["configured"] == "sqlite"
        assert res["state"]["active"] == "sqlite"
        again = post(api, SWITCH, to="sqlite", confirm=True).json()
        assert again["action"] == "noop"
        assert any(e.get("outcome") == "switched" for e in audit_lines(api))

    def test_switching_onto_a_missing_graph_migrates_first_never_flips_blind(self, api):
        _index(api.repo)
        res = post(api, SWITCH, to="sqlite", confirm=True).json()
        assert res["action"] == "migrating"
        assert res["state"]["configured"] == "networkx", "the setting must not move until the copy is verified"
        job = wait_job(api)
        assert job["last_run"]["result"] == "ok", job
        st = state(api)
        assert st["active"] == "sqlite" and st["files"]["sqlite"]["exists"] and st["files"]["networkx"]["exists"]
        assert st["nodes"] > 0 and st["stale_note"] is None

    def test_switching_back_to_an_up_to_date_graph_only_flips(self, api):
        _index(api.repo)
        post(api, SWITCH, to="sqlite", confirm=True)
        wait_job(api)
        back = post(api, SWITCH, to="networkx", confirm=True).json()
        assert back["action"] == "switched" and back["state"]["active"] == "networkx"

    def test_a_stale_target_is_replaced_by_a_migration_not_flipped_to(self, api):
        _index(api.repo)
        post(api, SWITCH, to="sqlite", confirm=True)
        wait_job(api)
        post(api, SWITCH, to="networkx", confirm=True)
        future = time.time() + 600
        os.utime(pathlib.Path(get_cognirepo_dir()) / "graph" / "graph.pkl", (future, future))   # the pickle moved on
        st = state(api)
        assert st["switch_to"] == "sqlite" and st["switch_needs_migration"] is True
        res = post(api, SWITCH, to="sqlite", confirm=True).json()
        assert res["action"] == "migrating"
        job = wait_job(api)
        assert job["last_run"]["result"] == "ok"
        assert list((pathlib.Path(get_cognirepo_dir()) / "graph").glob("graph.sqlite.replaced-*"))


class TestMigrate:
    def test_dry_run_reports_the_plan_and_changes_nothing(self, api):
        _index(api.repo)
        before = sorted(p.name for p in (pathlib.Path(get_cognirepo_dir()) / "graph").iterdir())
        res = post(api, MIGRATE, to="sqlite", confirm=True, dry_run=True).json()
        assert res["result"] == "plan" and (res["from"], res["to"]) == ("networkx", "sqlite")
        assert res["nodes"] > 0 and res["blockers"] == []
        assert sorted(p.name for p in (pathlib.Path(get_cognirepo_dir()) / "graph").iterdir()) == before
        assert state(api)["configured"] == "networkx"

    def test_runs_both_ways_and_reports_progress_and_a_summary(self, api):
        _index(api.repo)
        started = post(api, MIGRATE, to="sqlite", confirm=True).json()
        assert started["started"] is True
        job = wait_job(api)
        assert job["last_run"]["result"] == "ok" and job["summary"]["nodes"] > 0
        assert state(api)["active"] == "sqlite"
        post(api, MIGRATE, to="networkx", confirm=True, replace=True)
        assert wait_job(api)["last_run"]["result"] == "ok"
        assert state(api)["active"] == "networkx"

    def test_a_refused_migration_is_reported_not_hidden(self, api):
        _index(api.repo)
        post(api, MIGRATE, to="sqlite", confirm=True)
        wait_job(api)
        post(api, MIGRATE, to="sqlite", confirm=True)             # target exists, replace not given
        job = wait_job(api)
        assert job["last_run"]["result"] == "failed" and job["last_run"]["reason"] == "target_exists"
        assert state(api)["active"] == "sqlite", "a refused run must not change anything"

    def test_confirm_is_required(self, api):
        assert post(api, MIGRATE, to="sqlite").status_code == 400
