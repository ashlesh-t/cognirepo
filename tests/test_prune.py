# pylint: disable=missing-docstring, protected-access, redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_prune.py — prune correctness (encryption, lost updates), the safe scheduler and the console service (#213)."""
import json
import os
import subprocess
import sys
import time

import faiss
import numpy as np
import pytest
from starlette.testclient import TestClient

from core import events
from core.config.paths import get_path
from core.vector_db import local_vector_db as lvdb
from core.vector_db.local_vector_db import LocalVectorDB, read_semantic_metadata
from interface.ui import security as sec
from interface.ui import services as svc_mod
from interface.ui.app import create_app
from interface.ui.audit import AuditLog
from interface.ui.services import ServiceError, ServiceManager
from ops.cron import prune_memory, scheduler

DIM = 8
PORT = 8765
TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
KEEP = "important bug fix: the parser must reject unterminated strings before indexing a file"   # high importance
DROP = "tmp note"                                                                                  # 8 chars -> 0.08


def vec(i):
    v = np.zeros(DIM, dtype="float32")
    v[i % DIM] = 1.0 + i
    return v


def build_store(texts):
    db = LocalVectorDB(dim=DIM)
    for i, t in enumerate(texts):
        db.add(vec(i), t, prune_memory_importance(t))
    return db


def prune_memory_importance(text):
    from data.memory.semantic_memory import SemanticMemory
    return SemanticMemory.compute_importance(None, text)


def on_disk_text():
    out = ""
    for root, _d, files in os.walk(get_path("")):
        for f in files:
            with open(os.path.join(root, f), "rb") as fh:
                out += fh.read().decode("utf-8", "ignore")
    return out


class TestPruneCorrectness:
    def test_dry_run_reports_and_changes_nothing(self, isolated_cognirepo):
        build_store([KEEP, DROP, KEEP + " 2", "scrap"])
        before = read_semantic_metadata()
        r = prune_memory.prune(dry_run=True)
        assert (r["total"], r["kept"], r["pruned"], r["dry_run"]) == (4, 2, 2, True)
        assert [p["text"] for p in r["preview"]] == ["scrap", "tmp note"]           # lowest scores first, clipped
        assert read_semantic_metadata() == before
        assert prune_memory.read_state()["last_dry_run"]["pruned"] == 2 and prune_memory.dry_run_is_fresh()

    def test_real_run_keeps_the_right_vectors_in_order(self, isolated_cognirepo):
        build_store([KEEP, DROP, KEEP + " 2", "scrap", KEEP + " 3"])
        index_path = lvdb._read_paths()[0]
        old = faiss.read_index(index_path).reconstruct_n(0, 5)
        r = prune_memory.prune(archive=True)
        assert (r["total"], r["kept"], r["pruned"]) == (5, 3, 2)
        meta = read_semantic_metadata()
        assert [m["text"] for m in meta] == [KEEP, KEEP + " 2", KEEP + " 3"]
        assert [m["faiss_row"] for m in meta] == [0, 1, 2]
        new = faiss.read_index(lvdb._read_paths()[0])
        assert new.ntotal == 3
        np.testing.assert_array_equal(new.reconstruct_n(0, 3), old[[0, 2, 4]])      # copied, not re-embedded
        arch = json.load(open(r["archive_path"], encoding="utf-8"))
        assert [e["text"] for e in arch] == [DROP, "scrap"]

    def test_store_still_searchable_after_a_prune(self, isolated_cognirepo):
        build_store([KEEP, DROP, KEEP + " 2"])
        prune_memory.prune()
        hits = LocalVectorDB(dim=DIM).search(vec(2), top_k=1)
        assert hits and hits[0]["text"] == KEEP + " 2"

    def test_nothing_to_prune_rewrites_nothing(self, isolated_cognirepo):
        build_store([KEEP, KEEP + " 2"])
        gen = os.listdir(os.path.dirname(lvdb._read_paths()[0]))
        r = prune_memory.prune()
        assert r["pruned"] == 0 and r["archive_path"] == ""
        assert os.listdir(os.path.dirname(lvdb._read_paths()[0])) == gen

    def test_index_and_metadata_mismatch_is_reported_not_applied(self, isolated_cognirepo):
        build_store([KEEP, DROP, KEEP + " 2"])
        faiss.write_index(faiss.IndexFlatL2(DIM), lvdb._read_paths()[0])            # corrupt: empty index
        before = read_semantic_metadata()
        r = prune_memory.prune()
        assert r["status"] == "error" and "nothing was changed" in r["message"] and r["pruned"] == 0
        assert read_semantic_metadata() == before

    def test_all_entries_pruned(self, isolated_cognirepo):
        build_store([DROP, "scrap"])
        r = prune_memory.prune()
        assert r["kept"] == 0 and read_semantic_metadata() == []
        assert faiss.read_index(lvdb._read_paths()[0]).ntotal == 0

    def test_read_publish_happen_under_the_store_lock(self, isolated_cognirepo, monkeypatch):
        """A memory stored between read and publish used to be dropped; now both happen under one lock hold."""
        build_store([KEEP, DROP])
        order = []
        from core.config import lock as lockmod
        real = lockmod.store_lock

        class Recording:
            def __init__(self, *a, **k):
                self.cm = real(*a, **k)

            def __enter__(self):
                order.append("lock")
                return self.cm.__enter__()

            def __exit__(self, *a):
                order.append("unlock")
                return self.cm.__exit__(*a)

        monkeypatch.setattr(lockmod, "store_lock", Recording)
        real_pub, real_read = lvdb.publish_semantic, lvdb.read_semantic_metadata
        monkeypatch.setattr(lvdb, "publish_semantic", lambda *a, **k: (order.append("publish"), real_pub(*a, **k))[1])
        monkeypatch.setattr(lvdb, "read_semantic_metadata", lambda *a, **k: (order.append("read"), real_read(*a, **k))[1])
        prune_memory.prune()
        assert order.index("lock") < order.index("read") < order.index("publish") < order.index("unlock")

    def test_event_and_state_carry_counts_not_text(self, isolated_cognirepo):
        build_store([KEEP, DROP])
        prune_memory.prune(archive=True)
        ev = [e for e in events.read_since(str(get_path("")), 0) if e["type"] == "prune"]
        assert len(ev) == 1 and ev[0]["pruned"] == 1 and ev[0]["dry_run"] is False and ev[0]["archived"] is True
        state = json.dumps(prune_memory.read_state())
        assert DROP not in state and KEEP not in state and DROP not in json.dumps(ev)


class TestPruneWithEncryption:
    @pytest.fixture
    def enc_repo(self, isolated_cognirepo, monkeypatch):
        fernet = pytest.importorskip("cryptography.fernet")
        from core.security import encryption
        keys: dict = {}
        monkeypatch.setattr(encryption, "get_or_create_key", lambda pid: keys.setdefault(pid, fernet.Fernet.generate_key()))
        cfg_path = isolated_cognirepo / ".cognirepo" / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg.setdefault("storage", {})["encrypt"] = True
        cfg_path.write_text(json.dumps(cfg))
        return isolated_cognirepo

    def test_prune_reads_and_writes_ciphertext_and_encrypts_the_archive(self, enc_repo):
        build_store([KEEP, DROP, KEEP + " 2"])
        assert KEEP not in on_disk_text()                          # precondition: the store is encrypted
        r = prune_memory.prune(archive=True)                       # used to crash on json.load(ciphertext)
        assert (r["kept"], r["pruned"]) == (2, 1)
        text = on_disk_text()
        assert KEEP not in text and DROP not in text               # metadata and archive stay ciphertext
        assert [m["text"] for m in read_semantic_metadata()] == [KEEP, KEEP + " 2"]
        from core.security.store_crypto import decode_store
        with open(r["archive_path"], "rb") as fh:
            assert json.loads(decode_store(fh.read(), r["archive_path"]))[0]["text"] == DROP

    def test_dry_run_reads_ciphertext(self, enc_repo):
        build_store([KEEP, DROP])
        assert prune_memory.prune(dry_run=True)["pruned"] == 1

    def test_cleanup_rebuild_no_longer_writes_plaintext(self, enc_repo, monkeypatch):
        """`cleanup_suppressed` shares the rebuild helper, which published plaintext metadata."""
        build_store([KEEP, DROP])
        entries = read_semantic_metadata()

        class FakeModel:
            def embed(self, texts, batch_size=256, **_kw):
                return iter([np.zeros(DIM, dtype="float32") for _ in texts])

        import data.memory.embeddings as emb
        monkeypatch.setattr(emb, "get_model", lambda: FakeModel())
        assert prune_memory._rebuild_faiss(entries[:1], dry_run=False) == 1
        assert KEEP not in on_disk_text()


class TestGraphPrune:
    def _graph(self):
        from data.graph.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.add_node("file::a.py", "FILE")
        kg.add_node("function::a.py::f", "FUNCTION")
        kg.add_edge("function::a.py::f", "file::a.py", "DEFINED_IN")
        kg.add_node("symbol::print", "CONCEPT")                      # a call-graph stub with ONE caller
        kg.add_edge("function::a.py::f", "symbol::print", "CALLED_BY")
        kg.add_edge("symbol::print", "function::a.py::f", "CALLS")
        kg.add_node("function::gone::orphan", "FUNCTION")            # degree 0
        kg.add_node("symbol::lonely", "CONCEPT")                     # degree 0
        kg.save()

    def test_orphans_removed_and_single_caller_stubs_survive(self, isolated_cognirepo):
        from data.graph.knowledge_graph import KnowledgeGraph
        self._graph()
        r = prune_memory._prune_graph(dry_run=False)
        assert r["orphans_removed"] == 2
        ids = set(KnowledgeGraph().node_ids())
        assert "symbol::print" in ids                                # who_calls needs it
        assert "function::gone::orphan" not in ids and "symbol::lonely" not in ids

    def test_dry_run_counts_without_removing(self, isolated_cognirepo):
        from data.graph.knowledge_graph import KnowledgeGraph
        self._graph()
        assert prune_memory._prune_graph(dry_run=True)["orphans_removed"] == 2
        assert "function::gone::orphan" in set(KnowledgeGraph().node_ids())


class TestAggressiveRunsOnce:
    def test_one_prune_at_the_chosen_threshold(self, isolated_cognirepo, monkeypatch):
        from interface.cli import main as cli
        calls = []
        monkeypatch.setattr(prune_memory, "prune", lambda **kw: calls.append(kw) or {"total": 0, "kept": 0, "pruned": 0})
        monkeypatch.setattr(sys, "argv", ["cognirepo", "prune", "--aggressive", "--dry-run"])
        cli.main()
        assert len(calls) == 1 and calls[0]["threshold"] == prune_memory.AGGRESSIVE_THRESHOLD

    def test_json_flag_prints_one_json_line_last(self, isolated_cognirepo, monkeypatch, capsys):
        from interface.cli import main as cli
        monkeypatch.setattr(prune_memory, "prune", lambda **kw: {"total": 3, "kept": 2, "pruned": 1})
        monkeypatch.setattr(sys, "argv", ["cognirepo", "prune", "--json"])
        cli.main()
        assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"total": 3, "kept": 2, "pruned": 1}


@pytest.fixture
def fresh_scheduler():
    scheduler._AUTO_PRUNE_SCHEDULER = scheduler._CLEANUP_SCHEDULER = None
    yield
    for s in (scheduler._AUTO_PRUNE_SCHEDULER, scheduler._CLEANUP_SCHEDULER):
        if s is not None:
            s.stop()
    scheduler._AUTO_PRUNE_SCHEDULER = scheduler._CLEANUP_SCHEDULER = None


def set_prune_cfg(**prune_cfg):
    path = get_path("config.json")
    cfg = json.load(open(path, encoding="utf-8"))
    cfg["prune"] = prune_cfg
    json.dump(cfg, open(path, "w", encoding="utf-8"))


def stamp_last_run(seconds_ago):
    when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))
    json.dump({"last_run": {"at": when, "status": "ok"}}, open(get_path("prune_state.json"), "w", encoding="utf-8"))


class TestSafeScheduler:
    def test_off_by_default(self, isolated_cognirepo, fresh_scheduler):
        assert scheduler.start_auto_prune_scheduler() is None

    def test_due_at_once_when_it_never_ran_but_not_in_the_first_minute(self, isolated_cognirepo, fresh_scheduler):
        set_prune_cfg(auto_enabled=True, every_hours=24)
        assert scheduler._seconds_until_due(86400) == 0
        sched = scheduler.start_auto_prune_scheduler()
        assert 55 <= sched._next_run - time.monotonic() <= 61         # 60 s after start, not 24 h

    def test_waits_for_the_remaining_interval_after_a_recent_run(self, isolated_cognirepo, fresh_scheduler):
        set_prune_cfg(auto_enabled=True, every_hours=24)
        stamp_last_run(20 * 3600)                                      # 4 h left
        sched = scheduler.start_auto_prune_scheduler()
        assert 3.9 * 3600 < sched._next_run - time.monotonic() < 4.1 * 3600

    def test_overdue_runs_soon_even_after_a_restart(self, isolated_cognirepo, fresh_scheduler):
        set_prune_cfg(auto_enabled=True, every_hours=24)
        stamp_last_run(3 * 86400)
        assert 55 <= scheduler.start_auto_prune_scheduler()._next_run - time.monotonic() <= 61

    def test_run_skips_when_another_process_pruned_recently(self, isolated_cognirepo, monkeypatch):
        set_prune_cfg(auto_enabled=True, every_hours=24)
        stamp_last_run(3600)
        monkeypatch.setattr(prune_memory, "prune", lambda **k: pytest.fail("pruned twice in one interval"))
        scheduler._run_auto_prune()

    def test_run_skips_when_another_process_holds_the_lock(self, isolated_cognirepo, monkeypatch):
        from filelock import FileLock
        set_prune_cfg(auto_enabled=True, every_hours=24)
        monkeypatch.setattr(prune_memory, "prune", lambda **k: pytest.fail("ran while another process was pruning"))
        with FileLock(get_path("prune.lock")):
            scheduler._run_auto_prune()

    def test_scheduled_runs_archive_by_default_and_respect_config(self, isolated_cognirepo, monkeypatch):
        seen = []
        monkeypatch.setattr(prune_memory, "prune", lambda **k: seen.append(k) or {"total": 0, "kept": 0, "pruned": 0})
        set_prune_cfg(auto_enabled=True)
        scheduler._run_auto_prune()
        set_prune_cfg(auto_enabled=True, archive=False, threshold=0.3)
        scheduler._run_auto_prune()
        assert seen[0]["archive"] is True and seen[0]["dry_run"] is False
        assert seen[1]["archive"] is False and seen[1]["threshold"] == 0.3

    def test_a_real_scheduled_run_records_state_so_the_next_one_waits(self, isolated_cognirepo):
        set_prune_cfg(auto_enabled=True, every_hours=24)
        build_store([KEEP, DROP])
        scheduler._run_auto_prune()
        assert [m["text"] for m in read_semantic_metadata()] == [KEEP]
        assert len(os.listdir(get_path("archive"))) == 1                # archived, not deleted
        assert 23 * 3600 < scheduler._seconds_until_due(86400) <= 86400


class TestClassify:
    c = staticmethod(ServiceManager._classify_prune)

    def test_ok_busy_memory_pressure_failed(self):
        ok = '{"total":4,"kept":3,"pruned":1,"archive_path":"a","preview":[{"text":"secret"}]}'
        result, reason, summary = self.c(0, "[prune] done\n" + ok)
        assert result == "ok" and summary["pruned"] == 1 and "preview" not in summary     # text never persisted
        assert self.c(75, "cognirepo: the CogniRepo store is busy")[:2] == ("busy", "store_busy")
        assert self.c(0, '{"skipped":true,"reason":"circuit_breaker_open"}')[:2] == ("busy", "memory_pressure")
        assert self.c(1, '{"status":"error","message":"mismatch"}')[:2] == ("failed", "prune_failed")
        assert self.c(1, "Traceback ...")[:2] == ("failed", "prune_failed")


@pytest.fixture
def served(isolated_cognirepo):
    """The served repo is the isolated tmp dir (its .cognirepo/config.json exists)."""
    return str(isolated_cognirepo)


def run_cli_env(monkeypatch, served):
    monkeypatch.setenv("COGNIREPO_NO_WATCHER", "1")
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", os.path.join(served, ".g"))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(
        p for p in (os.path.dirname(os.path.dirname(os.path.abspath(__file__))), os.environ.get("PYTHONPATH")) if p))


class TestConsoleService:
    def test_allowlisted_and_not_stoppable(self, served):
        assert "prune" in ServiceManager.allowed()
        with pytest.raises(ServiceError) as exc:
            ServiceManager(served).stop("prune")
        assert exc.value.status == 409

    def test_a_real_run_needs_a_fresh_dry_run(self, served):
        build_store([KEEP, DROP])
        with pytest.raises(ServiceError) as exc:
            ServiceManager(served).start("prune")
        assert exc.value.status == 409 and exc.value.code == "dry_run_required"
        assert len(read_semantic_metadata()) == 2                     # nothing happened

    def test_dry_run_returns_the_preview_and_persists_no_memory_text(self, served, monkeypatch):
        run_cli_env(monkeypatch, served)
        build_store([KEEP, DROP, "scrap"])
        out = ServiceManager(served).start("prune", dry_run=True)
        assert out["dry_run"] is True and out["summary"]["pruned"] == 2
        assert {p["text"] for p in out["summary"]["preview"]} == {DROP, "scrap"}
        assert out["dry_run_fresh"] is True and out["changed"] is False
        assert len(read_semantic_metadata()) == 3                     # a dry run changes nothing
        watchers = os.path.join(get_path(""), "watchers")
        blob = prune_memory.read_state().__repr__() + (on_disk_text_under(watchers) if os.path.isdir(watchers) else "")
        assert DROP not in blob and "scrap" not in blob

    def test_dry_run_then_confirmed_run_archives_and_reports(self, served, monkeypatch):
        run_cli_env(monkeypatch, served)
        build_store([KEEP, DROP, "scrap", KEEP + " 2"])
        mgr = ServiceManager(served)
        mgr.start("prune", dry_run=True)
        started = mgr.start("prune")
        assert started["state"] == "running" and started["changed"] is True
        deadline = time.monotonic() + 120
        while mgr.status("prune")["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.1)
        st = mgr.status("prune")
        assert st["last_run"]["result"] == "ok" and st["summary"]["pruned"] == 2, st
        assert [m["text"] for m in read_semantic_metadata()] == [KEEP, KEEP + " 2"]
        archive = os.path.join(get_path(""), "archive")
        assert len(os.listdir(archive)) == 1                          # the console always archives
        assert ServiceManager(served).status("prune")["last_run"]["result"] == "ok"      # survives a restart

    def test_status_shape(self, served):
        st = ServiceManager(served).status("prune")
        assert st["name"] == "prune" and st["state"] == "idle" and st["dry_run_fresh"] is False
        assert set(st["auto"]) == {"enabled", "every_hours", "archive", "next_due_in_s"} and st["auto"]["enabled"] is False

    def test_status_reflects_the_schedule(self, served):
        set_prune_cfg(auto_enabled=True, every_hours=6)
        auto = ServiceManager(served).status("prune")["auto"]
        assert auto["enabled"] is True and auto["every_hours"] == 6 and auto["archive"] is True
        assert auto["next_due_in_s"] == 0


def on_disk_text_under(path):
    out = ""
    for root, _d, files in os.walk(path):
        for f in files:
            with open(os.path.join(root, f), "rb") as fh:
                out += fh.read().decode("utf-8", "ignore")
    return out


class FakeSvc:
    def __init__(self):
        self.calls = []

    @staticmethod
    def allowed():
        return ServiceManager.allowed()

    def start(self, name, dry_run=False):
        self.calls.append((name, dry_run))
        return {"name": name, "state": "idle", "changed": False}

    def status(self, name=None):
        return []

    def shutdown(self):
        pass


class TestRoute:
    @pytest.fixture
    def client(self, served):
        cfg = sec.SecurityConfig(token=TOKEN, port=PORT, limiter=sec.AttemptLimiter(max_failures=50, base_lockout=60))
        audit = AuditLog(os.path.join(served, "ui", "audit.log"))
        svc = FakeSvc()
        with TestClient(create_app(cfg, served, audit, services=svc), base_url=f"http://127.0.0.1:{PORT}") as c:
            c.svc, c.audit = svc, audit
            yield c

    def post(self, client, name, **body):
        return client.post(f"/api/v1/services/{name}/start", json=body, headers=AUTH)

    def test_dry_run_is_forwarded_only_for_prune(self, client):
        assert self.post(client, "prune", confirm=True, dry_run=True).status_code == 200
        assert client.svc.calls == [("prune", True)]
        r = self.post(client, "hooks", confirm=True, dry_run=True)
        assert r.status_code == 400 and r.json() == {"error": "dry_run_unsupported"}
        assert client.svc.calls == [("prune", True)]                   # the unsupported call never reached the service

    def test_confirm_is_still_required_for_a_dry_run(self, client):
        assert self.post(client, "prune", dry_run=True).status_code == 400
        assert self.post(client, "prune", confirm="true", dry_run=True).status_code == 422
        assert client.svc.calls == []

    def test_plain_start_is_not_a_dry_run(self, client):
        self.post(client, "prune", confirm=True)
        assert client.svc.calls == [("prune", False)]

    def test_dry_run_required_is_a_409(self, served):
        cfg = sec.SecurityConfig(token=TOKEN, port=PORT, limiter=sec.AttemptLimiter(max_failures=50, base_lockout=60))
        with TestClient(create_app(cfg, served, None, services=ServiceManager(served)),
                        base_url=f"http://127.0.0.1:{PORT}") as c:
            r = c.post("/api/v1/services/prune/start", json={"confirm": True}, headers=AUTH)
        assert r.status_code == 409 and r.json() == {"error": "dry_run_required"}
