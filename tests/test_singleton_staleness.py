# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_singleton_staleness.py — COGNIREPO-D-A/D-B/D-C/D-D/D-E/D-F regressions.

Found by the second run of E2E-100-1 (epic ReliabilityGate-100). The watcher
pipeline was verified correct *on disk* — a renamed file resolved only to its
new path, a deleted function was gone from reverse_index, zero orphan graph
nodes — yet the same queries through the long-lived MCP server returned the
pre-edit answers for the whole session, while graph_stats reported
index_age_minutes: 0 and index_stale: false in the same payload.

The cause is process boundaries. The watcher reindexes in its own process, so
ASTIndexer.lookup_symbol.cache_clear() there never reaches the server, and the
server's module-level _INDEXER/_GRAPH were .load()ed exactly once at startup
with no revalidation. Nothing in tests/test_index_write_concurrency.py could
catch it: those tests exercise a single process, where the writer and the
reader are the same object.
"""
from __future__ import annotations

import json
import os
import time

import pytest


def _fresh_indexer():
    """Build an ASTIndexer over the isolated store, as a reader would."""
    from data.graph.knowledge_graph import KnowledgeGraph
    from intelligence.indexer.ast_indexer import ASTIndexer

    idx = ASTIndexer(KnowledgeGraph())
    idx.load()
    return idx


def _seed(indexer, symbol: str, path: str, line: int = 1):
    indexer.index_data["reverse_index"] = {symbol: [[path, line]]}
    indexer.index_data["files"] = {
        path: {"symbols": [{"name": symbol, "start_line": line, "type": "function"}]}
    }
    indexer.save()


# ── D-A: long-lived readers must revalidate against disk ─────────────────────

class TestIndexerReloadIfChanged:
    """ASTIndexer must notice a rewrite performed by another process."""

    def test_reader_sees_rename_after_external_write(self):
        """The exact E2E-100-1 failure: renamed symbol still resolves to the old path."""
        writer = _fresh_indexer()
        _seed(writer, "secure_hash_s", "utils/hashing.py", 34)

        reader = _fresh_indexer()
        assert reader.lookup_symbol("secure_hash_s") == [
            {"file": "utils/hashing.py", "line": 34}
        ]

        time.sleep(0.01)  # ensure a distinct mtime_ns
        _seed(writer, "secure_hash_s", "utils/hashing_renamed.py", 34)

        assert reader.reload_if_changed() is True
        assert reader.lookup_symbol("secure_hash_s") == [
            {"file": "utils/hashing_renamed.py", "line": 34}
        ]

    def test_reader_sees_deletion_after_external_write(self):
        """A function deleted from a file must stop resolving, not linger."""
        writer = _fresh_indexer()
        _seed(writer, "deduplicate_list", "utils/helpers.py", 44)

        reader = _fresh_indexer()
        assert reader.lookup_symbol("deduplicate_list")  # warms the lru_cache

        time.sleep(0.01)
        writer.index_data["reverse_index"] = {}
        writer.index_data["files"] = {"utils/helpers.py": {"symbols": []}}
        writer.save()

        assert reader.reload_if_changed() is True
        assert reader.lookup_symbol("deduplicate_list") == []

    def test_lru_cache_alone_would_serve_stale_results(self):
        """Guard the invalidation, not just the reload.

        lookup_symbol is @lru_cache'd on the class, so a reload that forgets
        cache_clear() still answers from the pre-reload reverse_index. Reloading
        by hand without clearing must reproduce the stale answer — otherwise
        this suite would pass even if reload_if_changed() dropped the clear.
        """
        writer = _fresh_indexer()
        _seed(writer, "foo", "a.py")

        reader = _fresh_indexer()
        assert reader.lookup_symbol("foo") == [{"file": "a.py", "line": 1}]

        time.sleep(0.01)
        _seed(writer, "foo", "b.py")

        reader.load()  # reload WITHOUT clearing the cache
        assert reader.index_data["reverse_index"]["foo"] == [["b.py", 1]]
        assert reader.lookup_symbol("foo") == [{"file": "a.py", "line": 1}], (
            "expected the un-cleared lru_cache to serve the stale path"
        )

        # load() adopted the new stamp, so force one more comparison to prove
        # reload_if_changed() is what clears the cache.
        reader._disk_stamp = None
        assert reader.reload_if_changed() is True
        assert reader.lookup_symbol("foo") == [{"file": "b.py", "line": 1}]

    def test_writer_does_not_reload_its_own_write(self):
        """save() must adopt its own stamp, or every writer bounces off disk."""
        writer = _fresh_indexer()
        _seed(writer, "foo", "a.py")
        assert writer.reload_if_changed() is False

    def test_unchanged_index_does_not_reload(self):
        writer = _fresh_indexer()
        _seed(writer, "foo", "a.py")
        reader = _fresh_indexer()
        assert reader.reload_if_changed() is False
        assert reader.reload_if_changed() is False

    def test_reload_refuses_when_path_context_changed(self, tmp_path):
        """A _repo_ctx() switch must not swap this instance's repo underneath it.

        get_path() is ContextVar-scoped, so calling reload_if_changed() inside a
        block scoped to another repository would otherwise load that repo's
        ast_index.json into the default singleton.
        """
        from core.config.paths import _CTX_DIR

        writer = _fresh_indexer()
        _seed(writer, "foo", "a.py")
        reader = _fresh_indexer()

        other = tmp_path / "other" / ".cognirepo"
        (other / "index").mkdir(parents=True)
        (other / "index" / "ast_index.json").write_text(
            json.dumps({"reverse_index": {"foo": [["ELSEWHERE.py", 9]]}, "files": {}})
        )

        token = _CTX_DIR.set(str(other))
        try:
            assert reader.reload_if_changed() is False
        finally:
            _CTX_DIR.reset(token)

        assert reader.lookup_symbol("foo") == [{"file": "a.py", "line": 1}]

    def test_unloaded_indexer_is_not_reloaded(self):
        """An instance that never load()ed has no baseline to compare against."""
        from data.graph.knowledge_graph import KnowledgeGraph
        from intelligence.indexer.ast_indexer import ASTIndexer

        assert ASTIndexer(KnowledgeGraph()).reload_if_changed() is False


class TestGraphReloadIfChanged:
    """KnowledgeGraph is the same singleton shape and needs the same guarantee."""

    def test_reader_sees_external_node_addition(self):
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType

        writer = KnowledgeGraph()
        writer.add_node("a.py::foo", NodeType.FUNCTION)
        writer.save()

        reader = KnowledgeGraph()
        assert reader.G.number_of_nodes() == 1

        time.sleep(0.01)
        writer.add_node("b.py::bar", NodeType.FUNCTION)
        writer.save()

        assert reader.reload_if_changed() is True
        assert reader.G.number_of_nodes() == 2

    def test_writer_does_not_reload_its_own_write(self):
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType

        writer = KnowledgeGraph()
        writer.add_node("a.py::foo", NodeType.FUNCTION)
        writer.save()
        assert writer.reload_if_changed() is False

    def test_save_is_atomic(self):
        """graph.pkl must be promoted by rename, never truncated in place.

        Readers take no lock, so an in-place write exposes a short pickle that
        _load() treats as corruption and quarantines as .corrupt-<ts> — the
        fix would otherwise turn every revalidation into a corruption risk.
        """
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, _graph_file

        g = KnowledgeGraph()
        g.add_node("a.py::foo", NodeType.FUNCTION)
        g.save()

        seen_modes: list[str] = []
        real_open = open

        def _spy(path, mode="r", *args, **kwargs):
            if str(path).startswith(_graph_file()):
                seen_modes.append(mode)
            return real_open(path, mode, *args, **kwargs)

        import builtins

        builtins.open = _spy
        try:
            g.add_node("b.py::bar", NodeType.FUNCTION)
            g.save()
        finally:
            builtins.open = real_open

        # os.replace() does the promotion; nothing may open graph.pkl itself "wb".
        assert seen_modes == [] or all(
            not m.startswith("w") for m in seen_modes
        ), f"graph.pkl opened for truncating write: {seen_modes}"

    def test_no_corrupt_quarantine_after_reload_cycle(self):
        """A reload right after a save must not quarantine the graph."""
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, _graph_file

        writer = KnowledgeGraph()
        reader = KnowledgeGraph()
        for i in range(10):
            writer.add_node(f"f{i}.py::sym", NodeType.FUNCTION)
            writer.save()
            reader.reload_if_changed()

        quarantined = [
            n for n in os.listdir(os.path.dirname(_graph_file()))
            if ".corrupt-" in n
        ]
        assert quarantined == []
        assert reader.G.number_of_nodes() == 10


class TestMcpServerRevalidation:
    """The MCP singleton accessors are where the staleness actually surfaced."""

    @pytest.fixture(autouse=True)
    def _reset_singletons(self):
        from interface.server import mcp_server as srv

        srv._evict_singletons()
        yield
        srv._evict_singletons()

    def test_get_indexer_serves_fresh_data_after_external_write(self):
        from interface.server import mcp_server as srv

        writer = _fresh_indexer()
        _seed(writer, "foo", "a.py")

        assert srv._get_indexer().lookup_symbol("foo") == [{"file": "a.py", "line": 1}]

        time.sleep(0.01)
        _seed(writer, "foo", "b.py")

        assert srv._get_indexer().lookup_symbol("foo") == [{"file": "b.py", "line": 1}]

    def test_get_graph_serves_fresh_data_after_external_write(self):
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType
        from interface.server import mcp_server as srv

        writer = KnowledgeGraph()
        writer.add_node("a.py::foo", NodeType.FUNCTION)
        writer.save()
        assert srv._get_graph().G.number_of_nodes() == 1

        time.sleep(0.01)
        writer.add_node("b.py::bar", NodeType.FUNCTION)
        writer.save()
        assert srv._get_graph().G.number_of_nodes() == 2

    def test_revalidation_failure_does_not_break_the_call(self):
        """A stat error must degrade to serving cached state, not raise."""
        from interface.server import mcp_server as srv

        writer = _fresh_indexer()
        _seed(writer, "foo", "a.py")
        idx = srv._get_indexer()

        def _boom():
            raise OSError("stat failed")

        idx.reload_if_changed = _boom
        assert srv._get_indexer().lookup_symbol("foo") == [{"file": "a.py", "line": 1}]

    def test_eviction_clears_lookup_caches(self):
        """lru_cache entries hold a strong ref to the indexer.

        Without cache_clear() the eviction drops the module global but frees
        nothing — the whole index stays reachable from the cache.
        """
        from intelligence.indexer.ast_indexer import ASTIndexer
        from interface.server import mcp_server as srv

        writer = _fresh_indexer()
        _seed(writer, "foo", "a.py")
        srv._get_indexer().lookup_symbol("foo")
        assert ASTIndexer.lookup_symbol.cache_info().currsize > 0

        srv._evict_singletons()
        assert ASTIndexer.lookup_symbol.cache_info().currsize == 0


# ── D-B: FAISS metadata compaction ───────────────────────────────────────────

class TestFaissCompaction:
    """faiss_meta is positional and append-only; dead records must be reclaimable."""

    def _indexer_with(self, symbols):
        """Build an indexer with *symbols* = [(name, file, vector_seed), ...]."""
        import numpy as np

        idx = _fresh_indexer()
        idx._ensure_faiss()
        files: dict = {}
        for i, (name, path) in enumerate(symbols):
            vec = np.full((1, 384), float(i + 1), dtype="float32")
            idx.faiss_index.add_with_ids(vec, np.array([i], dtype=np.int64))
            idx.faiss_meta.append({"name": name, "file": path, "source": "symbol"})
            files.setdefault(path, {"symbols": []})["symbols"].append(
                {"name": name, "start_line": 1, "faiss_id": i}
            )
        idx.index_data["files"] = files
        return idx

    def test_stats_report_dead_records(self):
        import numpy as np

        idx = self._indexer_with([("a", "x.py"), ("b", "y.py")])
        # y.py deleted: vector removed, metadata record necessarily retained
        idx.faiss_index.remove_ids(np.array([1], dtype=np.int64))
        idx.index_data["files"].pop("y.py")

        stats = idx.faiss_meta_stats()
        assert stats["live"] == 1
        assert stats["retained"] == 2
        assert stats["dead"] == 1

    def test_compaction_drops_dead_and_renumbers(self):
        import numpy as np

        idx = self._indexer_with([("a", "x.py"), ("b", "y.py"), ("c", "z.py")])
        idx.faiss_index.remove_ids(np.array([1], dtype=np.int64))
        idx.index_data["files"].pop("y.py")

        result = idx.compact_faiss()
        assert result["compacted"] is True
        assert idx.faiss_meta_stats()["dead"] == 0
        assert [m["name"] for m in idx.faiss_meta] == ["a", "c"]

        # The positional invariant semantic_search_code relies on must hold:
        # faiss_meta[fid] is the record for the symbol carrying that faiss_id.
        for file_data in idx.index_data["files"].values():
            for sym in file_data["symbols"]:
                assert idx.faiss_meta[sym["faiss_id"]]["name"] == sym["name"]

    def test_compacted_vectors_still_resolve_to_the_right_record(self):
        """Compaction must move vectors with their metadata, not just relabel."""
        import numpy as np

        idx = self._indexer_with([("a", "x.py"), ("b", "y.py"), ("c", "z.py")])
        idx.faiss_index.remove_ids(np.array([1], dtype=np.int64))
        idx.index_data["files"].pop("y.py")
        idx.compact_faiss()

        # Query with c's exact vector (seed 3) — it must come back as "c".
        probe = np.full((1, 384), 3.0, dtype="float32")
        _dist, ids = idx.faiss_index.search(probe, 1)
        assert idx.faiss_meta[ids[0][0]]["name"] == "c"

    def test_compaction_is_a_noop_when_nothing_is_dead(self):
        idx = self._indexer_with([("a", "x.py")])
        assert idx.compact_faiss()["compacted"] is False

    def test_dangling_faiss_id_is_cleared_not_carried(self):
        """A symbol whose faiss_id addresses nothing must lose the reference.

        Left in place, semantic_search_code's `fid < len(faiss_meta)` guard is
        the only thing between it and an IndexError or a wrong record.
        """
        idx = self._indexer_with([("a", "x.py")])
        idx.index_data["files"]["z.py"] = {
            "symbols": [{"name": "ghost", "start_line": 1, "faiss_id": 99}]
        }

        assert idx.faiss_meta_stats()["dangling"] == 1
        assert idx.compact_faiss()["compacted"] is True

        assert idx.index_data["files"]["z.py"]["symbols"][0]["faiss_id"] == -1
        assert idx.faiss_meta_stats()["dangling"] == 0
        assert [m["name"] for m in idx.faiss_meta] == ["a"]


# ── D-C: heartbeat must identify which repo it belongs to ────────────────────

class TestHeartbeatIdentity:
    def test_foreign_heartbeat_is_not_credited_to_this_repo(self, tmp_path):
        from interface.cli import daemon

        this_repo = tmp_path / "this_repo"
        other_repo = tmp_path / "some" / "other" / "repo"
        (this_repo / ".cognirepo").mkdir(parents=True)
        (other_repo / ".cognirepo").mkdir(parents=True)

        daemon.write_heartbeat(os.getpid(), str(other_repo))

        # The foreign repo's own heartbeat slot is occupied...
        assert daemon.read_heartbeat(str(other_repo)) is not None
        # ...but a repo-scoped heartbeat file (post COGNIREPO-D-C-follow-up)
        # means it never lands in this repo's slot in the first place.
        assert daemon.read_heartbeat(str(this_repo)) is None
        assert daemon.read_heartbeat_for_path(str(this_repo)) is None
        assert daemon.heartbeat_age_seconds_for_path(str(this_repo)) is None

    def test_own_heartbeat_is_credited(self, tmp_path):
        from interface.cli import daemon

        daemon.write_heartbeat(os.getpid(), str(tmp_path))
        assert daemon.read_heartbeat_for_path(str(tmp_path)) is not None
        age = daemon.heartbeat_age_seconds_for_path(str(tmp_path))
        assert age is not None and age < 60

    def test_path_match_is_normalised(self, tmp_path):
        from interface.cli import daemon

        daemon.write_heartbeat(os.getpid(), str(tmp_path) + "/./")
        assert daemon.read_heartbeat_for_path(str(tmp_path)) is not None

    def test_identityless_heartbeat_is_rejected(self):
        from interface.cli import daemon

        daemon._heartbeat_file().write_text(json.dumps({"pid": os.getpid()}))
        assert daemon.read_heartbeat_for_path(os.getcwd()) is None

    def test_watcher_alive_ignores_foreign_heartbeat(self, tmp_path):
        """graph_stats' liveness probe is the consumer that mattered."""
        from interface.cli import daemon
        from interface.server import mcp_server as srv

        daemon.write_heartbeat(os.getpid(), str(tmp_path / "elsewhere"))
        assert srv._watcher_alive() is False

    def test_clear_heartbeat_only_removes_our_own(self):
        from interface.cli import daemon

        daemon.write_heartbeat(os.getpid(), os.getcwd())
        daemon.clear_heartbeat_if_owned(os.getpid() + 1)
        assert daemon.read_heartbeat() is not None
        daemon.clear_heartbeat_if_owned(os.getpid())
        assert daemon.read_heartbeat() is None


# ── D-E: the daemon must not leave its PID file behind ───────────────────────

class TestWatcherShutdownCleanup:
    def test_pid_file_and_heartbeat_removed_on_clean_exit(self):
        from interface.cli import daemon

        pid = os.getpid()
        daemon.flock_register_watcher(pid, "test", os.getcwd(), "/dev/null")
        assert daemon._pid_file(pid).exists()

        class _Observer:
            def is_alive(self):
                return False

        daemon.run_watcher_with_crash_guard(
            create_fn=_Observer, stop_fn=lambda _o: None,
            watcher_path=os.getcwd(), session_id="test",
        )

        assert not daemon._pid_file(pid).exists()
        assert daemon.read_heartbeat() is None

    def test_pid_file_removed_even_when_the_loop_raises(self):
        from interface.cli import daemon

        pid = os.getpid()
        daemon.flock_register_watcher(pid, "test", os.getcwd(), "/dev/null")

        def _explode():
            raise KeyboardInterrupt

        daemon.run_watcher_with_crash_guard(
            create_fn=_explode, stop_fn=lambda _o: None,
            watcher_path=os.getcwd(), session_id="test",
        )
        assert not daemon._pid_file(pid).exists()


# ── D-D: every advertised command must actually be dispatchable ──────────────

def _dispatch_exit_code(command: str) -> int:
    """Run `cognirepo <command> --help` in-process; return its exit status.

    argparse exits 0 for a registered subcommand's own help and 2 for
    "invalid choice", which is exactly the distinction under test — no
    command implementation runs either way.
    """
    import sys as _sys

    from interface.cli.main import _main

    argv = _sys.argv
    _sys.argv = ["cognirepo", command, "--help"]
    try:
        _main()
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        _sys.argv = argv
    return 0


class TestBannerCommandsAreRegistered:
    ADVERTISED = [
        "mcp-setup", "episodic-search", "lookup-symbol",
        "who-calls", "subgraph", "graph-stats",
    ]

    @pytest.mark.parametrize("command", ADVERTISED)
    def test_command_is_dispatchable(self, command, capsys):
        """These six were printed by --help but rejected by argparse with exit 2."""
        code = _dispatch_exit_code(command)
        capsys.readouterr()
        assert code == 0, f"`cognirepo {command}` is advertised but not registered"

    def test_banner_advertises_nothing_unregistered(self, capsys):
        """Keeps the banner honest as commands are added or removed."""
        import io
        import re
        from contextlib import redirect_stdout

        from interface.cli.main import _print_help

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_help()
        text = re.sub(r"\x1b\[[0-9;]*m", "", buf.getvalue())

        # _row() prints six leading spaces, then the command token.
        advertised = {
            m.group(1)
            for m in (re.match(r"^ {6}([a-z][a-z0-9-]{2,})(?:\s|$)", ln)
                      for ln in text.splitlines())
            if m
        }
        assert advertised, "banner scrape found no commands — did _row() change?"

        unregistered = sorted(c for c in advertised if _dispatch_exit_code(c) == 2)
        capsys.readouterr()
        assert not unregistered, (
            f"banner advertises unregistered command(s): {unregistered}"
        )


# ── D-F: doc-chunk health must not be backend-specific ───────────────────────

class TestDocIngestReceipt:
    def test_ingest_receipt_is_written(self):
        from core.config.paths import get_path
        from intelligence.indexer.doc_ingester import DocIngester

        DocIngester._write_receipt(145, 51)
        with open(get_path("index/doc_ingest.json"), encoding="utf-8") as f:
            receipt = json.load(f)
        assert receipt["chunks"] == 145
        assert receipt["files"] == 51
        assert receipt["ingested_at"]

    def test_doctor_counts_chunks_from_receipt_not_faiss_metadata(self, capsys):
        """With vector_backend=chroma, semantic_metadata.json stays '[]'.

        Doctor used to read only that file, so it warned "repo has docs but no
        doc chunks are indexed" on every chroma-backed project forever, even
        with the docs fully ingested and searchable.
        """
        from core.config.paths import get_path
        from intelligence.indexer.doc_ingester import DocIngester
        from interface.cli.main import _cmd_doctor

        with open("README.md", "w", encoding="utf-8") as f:
            f.write("# docs exist\n")
        with open(get_path("memory/semantic_metadata.json"), "w", encoding="utf-8") as f:
            f.write("[]")  # what the chroma backend leaves behind

        DocIngester._write_receipt(145, 51)
        _cmd_doctor()
        assert "no doc chunks are indexed" not in capsys.readouterr().out

    def test_doctor_still_warns_when_nothing_was_ingested(self, capsys):
        from core.config.paths import get_path
        from intelligence.indexer.doc_ingester import DocIngester
        from interface.cli.main import _cmd_doctor

        with open("README.md", "w", encoding="utf-8") as f:
            f.write("# docs exist\n")
        with open(get_path("memory/semantic_metadata.json"), "w", encoding="utf-8") as f:
            f.write("[]")

        DocIngester._write_receipt(0, 0)
        _cmd_doctor()
        assert "no doc chunks are indexed" in capsys.readouterr().out
