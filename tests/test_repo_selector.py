# pylint: disable=missing-docstring, protected-access, redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_repo_selector.py — registry discovery, `cognirepo repos`, and `?repo=` on the read-only routes (#210)."""
import json
import os
import sys

import pytest
from starlette.testclient import TestClient

from core import events
from core.config import repo_registry
from core.config.paths import _CTX_DIR
from data.graph.knowledge_graph import KnowledgeGraph
from interface.tools import graph_view
from interface.ui import repo_select
from interface.ui import security as sec
from interface.ui.app import create_app
from interface.ui.audit import AuditLog

PORT = 8765
TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def make_repo(root, node):
    """An initialised repo with its own graph, events and sessions."""
    root.mkdir(parents=True, exist_ok=True)
    store = root / ".cognirepo"
    (store / "index").mkdir(parents=True, exist_ok=True)
    (store / "config.json").write_text("{}")
    token = _CTX_DIR.set(str(store))
    try:
        kg = KnowledgeGraph()
        kg.add_node(node, "FILE")
        kg.save()
    finally:
        _CTX_DIR.reset(token)
    events.emit("session.start", store_dir=str(store), session_id=f"sess-{node}", client=f"client-{node}",
                pid=os.getpid())
    return str(root)


@pytest.fixture
def world(tmp_path):
    from core.config.paths import set_cognirepo_dir
    graph_view.reset_cache()
    a = make_repo(tmp_path / "alpha", "a_only")
    b = make_repo(tmp_path / "beta", "b_only")
    set_cognirepo_dir(str(tmp_path / "alpha" / ".cognirepo"))     # the served repo's store is the process default
    repo_registry.register_repo(b)
    yield {"a": a, "b": b, "tmp": tmp_path}
    graph_view.reset_cache()


@pytest.fixture
def client(world):
    cfg = sec.SecurityConfig(token=TOKEN, port=PORT, limiter=sec.AttemptLimiter(max_failures=50, base_lockout=60))
    audit = AuditLog(str(world["tmp"] / "ui" / "audit.log"))
    with TestClient(create_app(cfg, world["a"], audit), base_url=f"http://127.0.0.1:{PORT}") as c:
        c.audit = audit
        c.world = world
        yield c


def get(client, path, **params):
    return client.get(path, params=params, headers=AUTH)


class TestRegistryDiscovery:
    def test_org_linked_repos_are_listed_read_only(self, world):
        orgs = os.path.join(repo_registry.registry_path().rsplit(os.sep, 1)[0], "orgs.json")
        gamma = make_repo(world["tmp"] / "gamma", "g")
        open(orgs, "w", encoding="utf-8").write(json.dumps(
            {"acme": {"repos": [gamma], "projects": {"p": {"repos": [world["a"], "/nonexistent/x"]}}}}))
        before = open(orgs, encoding="utf-8").read()
        paths = {r["path"]: r for r in repo_registry.known_repos()}
        assert gamma in paths and paths[gamma]["source"] == "org" and world["a"] in paths
        assert "/nonexistent/x" not in paths                          # not on disk
        assert open(orgs, encoding="utf-8").read() == before          # no id backfill, no rewrite

    def test_org_repo_paths_does_not_create_the_global_dir(self, tmp_path, monkeypatch):
        from core.config.paths import set_global_dir
        fresh = tmp_path / "never-created"
        set_global_dir(str(fresh))
        assert repo_registry.org_repo_paths() == [] and not fresh.exists()

    def test_register_if_initialised_ignores_plain_directories(self, world):
        plain = world["tmp"] / "plain"
        plain.mkdir()
        assert repo_registry.register_if_initialised(str(plain)) is False
        assert str(plain) not in {r["path"] for r in repo_registry.load()}
        assert repo_registry.register_if_initialised(world["a"]) is True

    def test_scan_depth_skips_and_symlinks(self, world):
        tmp = world["tmp"]
        deep = make_repo(tmp / "ws" / "x" / "y" / "deep", "d")
        shallow = make_repo(tmp / "ws" / "shallow", "s")
        make_repo(tmp / "ws" / "node_modules" / "pkg", "n")
        make_repo(tmp / "ws" / ".hidden" / "h", "h")
        os.symlink(world["b"], tmp / "ws" / "link")
        found = repo_registry.scan(str(tmp / "ws"), depth=2)
        assert found == [shallow]
        assert deep in repo_registry.scan(str(tmp / "ws"), depth=4)

    def test_scan_is_bounded(self, world, monkeypatch):
        monkeypatch.setattr(repo_registry, "SCAN_MAX_DIRS", 3)
        for i in range(10):
            (world["tmp"] / "many" / f"d{i}").mkdir(parents=True)
        assert repo_registry.scan(str(world["tmp"] / "many"), depth=2) == []      # stopped early, no error

    def test_listing_endpoint_includes_org_and_registered(self, client):
        names = {r["name"] for r in get(client, "/api/v1/repos").json()}
        assert {"alpha", "beta"} <= names


class TestResolve:
    def test_path_and_name(self, world):
        assert repo_registry.resolve(world["b"], world["a"])[0]["path"] == world["b"]
        assert repo_registry.resolve("beta", world["a"])[0]["path"] == world["b"]
        assert repo_registry.resolve("alpha", world["a"])[0]["path"] == world["a"]    # the served repo

    @pytest.mark.parametrize("ident", ["/etc", "../beta", "/", "nope", "..", "beta/../../etc", "~", "x" * 500])
    def test_arbitrary_paths_never_resolve(self, world, ident):
        row, err = repo_registry.resolve(ident, world["a"])
        assert row is None and err == "unknown_repo"

    def test_non_normalised_form_of_a_known_path_resolves_only_to_that_repo(self, world):
        weird = world["b"] + "/./"
        row, _ = repo_registry.resolve(weird, world["a"])
        assert row is not None and row["path"] == world["b"]

    def test_ambiguous_name(self, world):
        other = make_repo(world["tmp"] / "elsewhere" / "beta", "b2")
        repo_registry.register_repo(other)
        row, err = repo_registry.resolve("beta", world["a"])
        assert row is None and err == "ambiguous_repo"
        assert repo_registry.resolve(other, world["a"])[0]["path"] == other        # a path still works


class TestReposCli:
    def run(self, capsys, *argv):
        import argparse
        from interface.cli.main import _cmd_repos
        ns = argparse.Namespace(repos_command=argv[0], path=None, root=None, depth=3, dry_run=False)
        for k, v in zip(("path", "root", "depth", "dry_run"), argv[1:]):
            setattr(ns, k, v)
        rc = _cmd_repos(ns)
        return rc, capsys.readouterr()

    def test_add_requires_an_initialised_repo(self, world, capsys):
        plain = world["tmp"] / "plain"
        plain.mkdir()
        rc, out = self.run(capsys, "add", str(plain))
        assert rc == 1 and "no CogniRepo store" in out.err
        rc, out = self.run(capsys, "add", str(world["tmp"] / "missing"))
        assert rc == 1 and "not a directory" in out.err
        gamma = make_repo(world["tmp"] / "gamma", "g")
        rc, out = self.run(capsys, "add", gamma)
        assert rc == 0 and gamma in {r["path"] for r in repo_registry.load()}

    def test_scan_registers_unless_dry_run(self, world, capsys):
        make_repo(world["tmp"] / "ws" / "one", "o")
        rc, out = self.run(capsys, "scan", None, str(world["tmp"] / "ws"), 3, True)
        assert rc == 0 and "would register" in out.out
        assert str(world["tmp"] / "ws" / "one") not in {r["path"] for r in repo_registry.load()}
        rc, out = self.run(capsys, "scan", None, str(world["tmp"] / "ws"), 3, False)
        assert "registered " in out.out and "1 repo(s) found" in out.out
        assert str(world["tmp"] / "ws" / "one") in {r["path"] for r in repo_registry.load()}

    def test_list_shows_sources(self, world, capsys):
        rc, out = self.run(capsys, "list")
        assert rc == 0 and world["b"] in out.out and "registered" in out.out

    def test_used_commands_register_the_repo(self, world, monkeypatch):
        gamma = make_repo(world["tmp"] / "gamma", "g")
        monkeypatch.chdir(gamma)
        import interface.ui.cli as ui_cli
        from interface.cli import main as cli_main
        monkeypatch.setattr(ui_cli, "run_ui", lambda args: 0)
        monkeypatch.setattr(sys, "argv", ["cognirepo", "ui", "--stop"])
        with pytest.raises(SystemExit):
            cli_main.main()
        assert gamma in {r["path"] for r in repo_registry.load()}


class TestSelectorOnReadRoutes:
    def test_default_is_the_served_repo(self, client):
        assert get(client, "/api/v1/status").json()["repo"]["name"] == "alpha"

    def test_status_of_another_repo(self, client):
        body = get(client, "/api/v1/status", repo=client.world["b"]).json()
        assert body["repo"]["root"] == client.world["b"] and body["daemon"]["state"] == "stopped"
        assert get(client, "/api/v1/status", repo="beta").json()["repo"]["name"] == "beta"

    def test_graph_is_the_other_repos_graph(self, client):
        a = {n["id"] for n in get(client, "/api/v1/graph").json()["nodes"]}
        b = {n["id"] for n in get(client, "/api/v1/graph", repo="beta").json()["nodes"]}
        assert "a_only" in a and "b_only" not in a
        assert "b_only" in b and "a_only" not in b
        # asking again for the served repo is unaffected by the other one being cached
        assert "a_only" in {n["id"] for n in get(client, "/api/v1/graph", repo="alpha").json()["nodes"]}

    def test_graph_cache_holds_at_most_two_repos(self, client):
        c = make_repo(client.world["tmp"] / "gamma", "g_only")
        repo_registry.register_repo(c)
        for repo in (None, "beta", "gamma"):
            get(client, "/api/v1/graph", **({"repo": repo} if repo else {}))
        assert len(graph_view._cache) <= 2
        assert "g_only" in {n["id"] for n in get(client, "/api/v1/graph", repo="gamma").json()["nodes"]}

    def test_graph_changes_use_the_other_repos_counter(self, client):
        a = get(client, "/api/v1/graph/changes", since=0).json()
        b = get(client, "/api/v1/graph/changes", since=0, repo="beta").json()
        assert a["seq"] >= 1 and b["seq"] >= 1
        assert {o["id"] for o in a["ops"] if o["op"] == "add_node"} == {"a_only"}
        assert {o["id"] for o in b["ops"] if o["op"] == "add_node"} == {"b_only"}

    def test_sessions_are_per_repo(self, client):
        assert [s["id"] for s in get(client, "/api/v1/sessions").json()] == ["sess-a_only"]
        assert [s["id"] for s in get(client, "/api/v1/sessions", repo="beta").json()] == ["sess-b_only"]
        assert get(client, "/api/v1/sessions/sess-b_only", repo="beta").status_code == 200
        assert get(client, "/api/v1/sessions/sess-b_only").status_code == 404      # not in the served repo

    def test_processes_omit_the_ui_row_for_another_repo(self, client):
        served = {r["role"] for r in get(client, "/api/v1/processes").json()}
        other = {r["role"] for r in get(client, "/api/v1/processes", repo="beta").json()}
        assert "ui" in served and "ui" not in other

    def test_harness_insights_accept_repo(self, client):
        assert get(client, "/api/v1/harness", repo="beta").status_code == 200
        assert get(client, "/api/v1/insights", repo="beta").status_code == 200
        assert get(client, "/api/v1/insights/report", repo="beta").status_code == 404     # no report yet

    def test_event_stream_unknown_repo_is_refused_before_streaming(self, client):
        assert get(client, "/api/v1/events", repo="nope").status_code == 404

    @pytest.mark.parametrize("ident,code,status", [
        ("/etc", "unknown_repo", 404), ("../beta", "unknown_repo", 404), ("nope", "unknown_repo", 404)])
    def test_unknown_repos_are_404_with_a_code(self, client, ident, code, status):
        r = get(client, "/api/v1/status", repo=ident)
        assert r.status_code == status and r.json() == {"error": code}

    def test_overlong_repo_is_a_validation_error(self, client):
        assert get(client, "/api/v1/status", repo="x" * 2000).status_code == 422

    def test_ambiguous_name_is_a_conflict(self, client):
        other = make_repo(client.world["tmp"] / "elsewhere" / "beta", "b2")
        repo_registry.register_repo(other)
        r = get(client, "/api/v1/status", repo="beta")
        assert r.status_code == 409 and r.json() == {"error": "ambiguous_repo"}
        assert get(client, "/api/v1/status", repo=other).status_code == 200

    def test_deleted_and_uninitialised_repos(self, client):
        import shutil
        shutil.rmtree(client.world["b"] + "/.cognirepo")
        assert get(client, "/api/v1/status", repo="beta").json() == {"error": "repo_not_initialised"}
        shutil.rmtree(client.world["b"])
        assert get(client, "/api/v1/status", repo="beta").json() == {"error": "repo_missing"}

    def test_token_is_still_required(self, client):
        assert client.get("/api/v1/status", params={"repo": "beta"}).status_code == 401


class TestWritesStayOnTheServedRepo:
    def test_services_refuse_another_repo(self, client):
        assert get(client, "/api/v1/services", repo="beta").json() == {"error": "not_served_repo"}
        r = client.post("/api/v1/services/hooks/start", params={"repo": "beta"}, json={"confirm": True}, headers=AUTH)
        assert r.status_code == 409 and r.json() == {"error": "not_served_repo"}
        r = client.post("/api/v1/services/hooks/stop", params={"repo": "beta"}, json={"confirm": True}, headers=AUTH)
        assert r.status_code == 409

    def test_auto_index_refuses_another_repo_and_writes_nothing(self, client):
        cfg = client.world["b"] + "/.cognirepo/config.json"
        r = client.post("/api/v1/settings/auto-index", params={"repo": "beta"},
                        json={"enabled": False, "confirm": True}, headers=AUTH)
        assert r.status_code == 409 and json.loads(open(cfg, encoding="utf-8").read()) == {}

    def test_naming_the_served_repo_explicitly_is_fine(self, client):
        assert get(client, "/api/v1/services", repo="alpha").status_code == 200

    def test_denials_are_audited(self, client):
        client.post("/api/v1/services/hooks/start", params={"repo": "beta"}, json={"confirm": True}, headers=AUTH)
        client.post("/api/v1/services/hooks/start", params={"repo": "/etc"}, json={"confirm": True}, headers=AUTH)
        text = open(client.audit.path, encoding="utf-8").read()
        assert "service_start_denied_repo" in text and "not_served_repo" in text and "unknown_repo" in text

    def test_unknown_repo_on_a_write_never_reaches_the_service(self, client):
        r = client.post("/api/v1/services/hooks/start", params={"repo": "nope"}, json={"confirm": True}, headers=AUTH)
        assert r.status_code == 404


class TestSelectUnit:
    def test_require_served(self, world):
        repo_select.require_served(None, world["a"])
        repo_select.require_served("alpha", world["a"])
        with pytest.raises(repo_select.RepoSelectError) as exc:
            repo_select.require_served("beta", world["a"])
        assert exc.value.code == "not_served_repo"
