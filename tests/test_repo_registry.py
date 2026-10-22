# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""#210 — the global repo registry and GET /api/v1/repos."""
import json
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from core.config import repo_registry
from interface.ui import repos as repos_view
from interface.ui import security as sec
from interface.ui.app import create_app
from interface.ui.audit import AuditLog

PORT = 8767
TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _repo(tmp_path, name, *, indexed=True):
    root = tmp_path / name
    (root / ".cognirepo" / "index").mkdir(parents=True)
    if indexed:
        (root / ".cognirepo" / "index" / "manifest.json").write_text(
            json.dumps({"indexed_at": "2026-10-01T00:00:00Z", "git_commit": "abc123"}))
    return str(root)


class TestRegistry:
    def test_register_and_load_roundtrip_private_file(self, tmp_path):
        a = _repo(tmp_path, "a")
        assert repo_registry.register_repo(a) is True
        rows = repo_registry.load()
        assert [r["path"] for r in rows] == [a] and rows[0]["store"].endswith(".cognirepo")
        if os.name != "nt":   # Windows has no POSIX permission bits
            assert oct(os.stat(repo_registry.registry_path()).st_mode & 0o777) == "0o600"

    def test_touch_is_throttled_but_new_store_updates(self, tmp_path):
        a = _repo(tmp_path, "a")
        assert repo_registry.register_repo(a) is True
        assert repo_registry.register_repo(a) is False                    # seen <60 s ago: no rewrite
        assert repo_registry.register_repo(a, store_dir="/elsewhere") is True   # store changed: update
        assert repo_registry.load()[0]["store"] == "/elsewhere"

    def test_first_seen_is_kept_and_order_is_most_recent_first(self, tmp_path, monkeypatch):
        a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
        repo_registry.register_repo(a)
        first = repo_registry.load()[0]["first_seen"]
        monkeypatch.setattr(repo_registry, "_TOUCH_SECS", 0)
        time.sleep(1.1)
        repo_registry.register_repo(b)
        time.sleep(1.1)
        repo_registry.register_repo(a)
        rows = repo_registry.load()
        assert [r["path"] for r in rows] == [a, b] and rows[0]["first_seen"] == first

    def test_never_raises_and_can_be_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(repo_registry, "registry_path", lambda: (_ for _ in ()).throw(OSError("boom")))
        assert repo_registry.register_repo(str(tmp_path)) is False
        monkeypatch.undo()
        monkeypatch.setenv("COGNIREPO_REPO_REGISTRY", "0")
        assert repo_registry.register_repo(str(tmp_path)) is False
        assert repo_registry.load() == []

    def test_corrupt_file_loads_empty_and_is_replaced(self, tmp_path):
        a = _repo(tmp_path, "a")
        os.makedirs(os.path.dirname(repo_registry.registry_path()), exist_ok=True)
        open(repo_registry.registry_path(), "w").write("{not json")
        assert repo_registry.load() == []
        assert repo_registry.register_repo(a) is True and len(repo_registry.load()) == 1

    def test_register_watcher_registers_the_repo(self, tmp_path):
        from interface.cli.daemon import register_watcher
        a = _repo(tmp_path, "a")
        register_watcher(os.getpid(), "w", a, str(tmp_path / "w.log"))
        assert [r["path"] for r in repo_registry.load()] == [a]


class TestRepoView:
    def test_indexed_repo_fields(self, tmp_path):
        a = _repo(tmp_path, "a")
        (tmp_path / "a" / ".git" / "hooks").mkdir(parents=True)
        (tmp_path / "a" / ".git" / "hooks" / "post-commit").write_text("#!/bin/sh\n# cognirepo\n")
        repo_registry.register_repo(a)
        r = repos_view.list_repos()[0]
        assert (r["name"], r["root"], r["exists"], r["indexed"]) == ("a", a, True, True)
        assert r["indexed_at"] == "2026-10-01T00:00:00Z" and r["git_commit"] == "abc123"
        assert r["hooks_installed"] is True and r["auto_index"] is True
        assert r["watcher"]["state"] == "stopped"

    def test_missing_repo_dir_and_unindexed(self, tmp_path):
        gone = str(tmp_path / "gone")
        repo_registry.register_repo(gone, store_dir=str(tmp_path / "gone" / ".cognirepo"))
        bare = _repo(tmp_path, "bare", indexed=False)
        repo_registry.register_repo(bare)
        by = {r["name"]: r for r in repos_view.list_repos()}
        assert by["gone"]["exists"] is False and by["gone"]["indexed"] is False
        assert by["bare"]["exists"] is True and by["bare"]["indexed"] is False

    def test_watcher_running_stale_and_listing_is_read_only(self, tmp_path):
        a = _repo(tmp_path, "a")
        repo_registry.register_repo(a)
        wdir = tmp_path / "a" / ".cognirepo" / "watchers"
        wdir.mkdir()
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        (wdir / f"{dead.pid}.json").write_text(json.dumps({"pid": dead.pid, "path": a}))
        assert repos_view.list_repos()[0]["watcher"]["state"] == "stopped"
        assert (wdir / f"{dead.pid}.json").exists()           # a stale pid file is NOT deleted by a listing

        (wdir / f"{os.getpid()}.json").write_text(json.dumps({"pid": os.getpid(), "path": a}))
        from datetime import datetime
        (wdir / "heartbeat").write_text(json.dumps(
            {"pid": os.getpid(), "path": a, "timestamp": datetime.utcnow().isoformat() + "Z"}))
        w = repos_view.list_repos()[0]["watcher"]
        assert w["state"] == "running" and w["pid"] == os.getpid() and w["heartbeat_age_s"] < 5
        (wdir / "heartbeat").write_text(json.dumps(
            {"pid": os.getpid(), "path": a, "timestamp": "2020-01-01T00:00:00Z"}))
        assert repos_view.list_repos()[0]["watcher"]["state"] == "stale"

    def test_does_not_create_dirs_in_listed_repos(self, tmp_path):
        a = _repo(tmp_path, "a")
        repo_registry.register_repo(a)
        before = sorted(p.relative_to(a).as_posix() for p in (tmp_path / "a").rglob("*"))
        repos_view.list_repos()
        assert sorted(p.relative_to(a).as_posix() for p in (tmp_path / "a").rglob("*")) == before

    def test_auto_index_off_from_config(self, tmp_path):
        a = _repo(tmp_path, "a")
        (tmp_path / "a" / ".cognirepo" / "config.json").write_text(json.dumps({"watch": {"auto_enabled": False}}))
        repo_registry.register_repo(a)
        assert repos_view.list_repos()[0]["auto_index"] is False

    def test_current_repo_included_even_if_unregistered(self, tmp_path):
        a = _repo(tmp_path, "a")
        assert [r["root"] for r in repos_view.list_repos(current_root=a)] == [a]
        assert repos_view.list_repos(current_root=str(tmp_path / "nostore")) == []


@pytest.fixture
def client(tmp_path):
    cfg = sec.SecurityConfig(token=TOKEN, port=PORT, limiter=sec.AttemptLimiter(max_failures=3, base_lockout=60))
    app = create_app(cfg, _repo(tmp_path, "served"), AuditLog(str(tmp_path / "ui" / "audit.log")))
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        yield c


class TestApi:
    def test_requires_token(self, client):
        assert client.get("/api/v1/repos").status_code == 401

    def test_lists_registered_and_current(self, client, tmp_path):
        repo_registry.register_repo(_repo(tmp_path, "other"))
        rows = client.get("/api/v1/repos", headers=AUTH).json()
        assert {r["name"] for r in rows} == {"other", "served"}
        assert set(rows[0]) >= {"name", "root", "store", "indexed", "indexed_at", "git_commit", "watcher",
                                "hooks_installed", "auto_index"}
        assert set(rows[0]["watcher"]) == {"state", "pid", "heartbeat_age_s", "last_reindex"}
