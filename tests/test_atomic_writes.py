# pylint: disable=missing-docstring, import-outside-toplevel, too-few-public-methods, protected-access
# pylint: disable=redefined-outer-name, unused-argument, duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_atomic_writes.py — COGNIREPO-134: every store is written atomically.

Fault injection (a writer that dies mid-write leaves the previous complete file), a
concurrent reader that must never see a partial file, store-level failure cases, and an
AST lint that fails on any new bare in-place write of a store file.
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import subprocess
import sys
import threading
from unittest import mock

import pytest

from core.config.atomic import atomic_json_dump, atomic_path, atomic_write, atomic_write_with


def _tmp_leftovers(directory) -> list[str]:
    return [n for n in os.listdir(directory) if n.endswith(".tmp")]


class TestHelper:
    def test_writes_bytes_and_str(self, tmp_path):
        atomic_write(str(tmp_path / "b.bin"), b"\x00\x01")
        atomic_write(str(tmp_path / "s.txt"), "héllo")
        assert (tmp_path / "b.bin").read_bytes() == b"\x00\x01"
        assert (tmp_path / "s.txt").read_text(encoding="utf-8") == "héllo"

    def test_creates_missing_parent_directories(self, tmp_path):
        atomic_json_dump(str(tmp_path / "a" / "b" / "c.json"), {"x": 1})
        assert json.loads((tmp_path / "a" / "b" / "c.json").read_text()) == {"x": 1}

    def test_failing_writer_leaves_the_previous_file_and_no_scratch(self, tmp_path):
        target = tmp_path / "store.json"
        target.write_text('{"v": "old"}')

        def boom(f):
            f.write('{"v": "ne')          # half a document …
            raise RuntimeError("disk full")  # … then the writer dies

        with pytest.raises(RuntimeError):
            atomic_write_with(str(target), boom)
        assert target.read_text() == '{"v": "old"}'
        assert _tmp_leftovers(tmp_path) == []

    def test_atomic_path_cleans_up_and_keeps_old_file_on_error(self, tmp_path):
        target = tmp_path / "idx.bin"
        target.write_bytes(b"OLD")
        with pytest.raises(ValueError):
            with atomic_path(str(target)) as tmp:
                pathlib.Path(tmp).write_bytes(b"PARTIAL")
                raise ValueError("boom")
        assert target.read_bytes() == b"OLD" and _tmp_leftovers(tmp_path) == []

    def test_existing_file_mode_is_preserved(self, tmp_path):
        target = tmp_path / "secret.json"
        target.write_text("{}")
        os.chmod(target, 0o600)
        atomic_write(str(target), "{}")
        assert os.stat(target).st_mode & 0o777 == 0o600

    def test_new_file_gets_the_conventional_mode(self, tmp_path):
        atomic_write(str(tmp_path / "new.json"), "{}")
        assert os.stat(tmp_path / "new.json").st_mode & 0o777 == 0o644

    def test_writer_killed_mid_write_leaves_the_previous_complete_file(self, tmp_path):
        """SIGKILL-equivalent: the process dies (os._exit) after writing half the new content."""
        target = tmp_path / "store.json"
        target.write_text(json.dumps({"gen": "old", "pad": "x" * 1000}))
        code = (
            "import os, sys\n"
            f"sys.path.insert(0, {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))!r})\n"
            "from core.config.atomic import atomic_write_with\n"
            "def w(f):\n"
            "    f.write('{\"gen\": \"new\", \"pad\": \"' + 'y' * 500)\n"
            "    f.flush(); os._exit(9)\n"
            f"atomic_write_with({str(target)!r}, w)\n"
        )
        assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 9
        assert json.loads(target.read_text())["gen"] == "old"   # complete, parseable, old

    def test_concurrent_reader_never_sees_a_partial_file(self, tmp_path):
        target = tmp_path / "hot.json"
        atomic_json_dump(str(target), {"n": 0, "pad": "p" * 50_000})
        stop = threading.Event()
        errors: list[str] = []

        def writer():
            i = 1
            while not stop.is_set():
                atomic_json_dump(str(target), {"n": i, "pad": "p" * 50_000}, fsync=False)
                i += 1

        def reader():
            for _ in range(400):
                try:
                    doc = json.loads(target.read_text())
                    assert len(doc["pad"]) == 50_000
                except Exception as exc:  # pylint: disable=broad-except
                    errors.append(repr(exc))

        wt = threading.Thread(target=writer)
        wt.start()
        try:
            reader()
        finally:
            stop.set()
            wt.join()
        assert not errors, errors[:3]

    def test_concurrent_writers_use_distinct_scratch_files(self, tmp_path):
        target = tmp_path / "shared.json"
        errors: list[str] = []

        def spam(tag):
            for i in range(60):
                try:
                    atomic_json_dump(str(target), {"tag": tag, "i": i}, fsync=False)
                except Exception as exc:  # pylint: disable=broad-except
                    errors.append(repr(exc))

        threads = [threading.Thread(target=spam, args=(t,)) for t in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert not errors and "tag" in json.loads(target.read_text())
        assert _tmp_leftovers(tmp_path) == []


class TestStoresFailSafe:
    def test_faiss_write_failure_keeps_the_previous_index(self, isolated_cognirepo):
        import faiss
        from core.vector_db.local_vector_db import LocalVectorDB, _index_file
        db = LocalVectorDB()
        db.save()
        good = open(_index_file(), "rb").read()
        with mock.patch("faiss.write_index", side_effect=lambda idx, path: (open(path, "wb").write(b"junk"), (_ for _ in ()).throw(OSError("disk full")))):
            with pytest.raises(OSError):
                db.save()
        assert open(_index_file(), "rb").read() == good
        assert faiss.read_index(_index_file()).ntotal == 0

    def test_episodic_save_failure_keeps_the_history(self, isolated_cognirepo):
        from data.memory import episodic_memory as ep
        ep.log_event("first event", {})
        path = ep._file_path()
        before = open(path, "rb").read()
        with mock.patch("os.replace", side_effect=OSError("rename failed")):
            with pytest.raises(OSError):
                ep.log_event("second event", {})
        assert open(path, "rb").read() == before

    def test_prune_metadata_is_not_truncated_when_encryption_fails(self, isolated_cognirepo):
        """Old code opened the metadata file 'wb' BEFORE encrypting: a keyring failure
        left it empty. Content is now computed first and swapped in atomically."""
        pytest.importorskip("cryptography")
        from ops.cron import prune_memory
        from core.vector_db.local_vector_db import _meta_file, LocalVectorDB
        from data.memory.cleanup_queue import CleanupQueue
        db = LocalVectorDB()
        db.metadata = [{"text": "keep me", "faiss_row": 0}]
        db._save_meta()
        before = open(_meta_file(), "rb").read()
        assert b"keep me" in before
        CleanupQueue().push(entry_id=0, store="semantic", importance=0.1,
                            suppressed_at="2026-01-01T00:00:00+00:00", similarity_score=0.99)
        pathlib.Path(".cognirepo/config.json").write_text(
            json.dumps({"project_id": "p", "storage": {"encrypt": True}}))
        with mock.patch("core.security.encryption.get_or_create_key", side_effect=RuntimeError("no keyring")), \
             mock.patch.object(prune_memory, "_check_memory_pressure", return_value=True):
            with pytest.raises(RuntimeError):
                prune_memory.cleanup_suppressed()
        assert open(_meta_file(), "rb").read() == before, "metadata must survive an encryption failure"


# ── lint: no bare in-place write of a store file ─────────────────────────────────────────

_ROOTS = ("core", "data", "intelligence", "interface", "ops")
_REPO = pathlib.Path(__file__).resolve().parent.parent

# (file, enclosing function) -> why a bare write is acceptable here. Anything else that
# truncates a file in place must go through core/config/atomic.py (COGNIREPO-134).
_ALLOWED: dict[tuple[str, str], str] = {
    ("data/graph/journal.py", "acquire"): "pid sidecar for the writer lease; advisory",
    ("data/graph/journal.py", "append_segment"): "append-only fsynced log, not a rewrite",
    ("intelligence/orchestrator/router.py", "_write_error_log"): "append-only log",
    ("interface/cli/main.py", "_log_error_to_file"): "append-only error log",
    ("interface/tools/benchmark.py", "_save_to_history"): "append-only jsonl history",
    ("interface/cli/daemon.py", "spawn_detached_watcher"): "append-mode log handed to the child as its stdout/stderr",
    ("interface/cli/daemon.py", "write_systemd_unit"): "generated user unit file, not a store",
    ("interface/server/mcp_server.py", "_spawn_background_reindex"): "O_EXCL lock-file creation is itself atomic",
    ("interface/server/mcp_server.py", "_write_manifest"): "dev-time package manifest, not .cognirepo data",
    ("intelligence/indexer/ast_indexer.py", "save"): "writes into the scratch dir of a GenerationStore.publish(), "
                                                      "which fsyncs and renames the whole group into place (#140)",
    ("core/vector_db/local_vector_db.py", "_index"): "writes into the scratch dir of a GenerationStore.publish(), "
                                                          "which fsyncs and renames the group into place (#140)",
    ("interface/tools/bg_progress.py", "_write"): "already tmp + os.replace",
    ("interface/tools/bg_progress.py", "request_stop"): "already tmp + os.replace",
    ("interface/tools/progress_window.py", "_request_stop"): "already tmp + os.replace",
    ("interface/adapters/openai_spec.py", "export"): "generated adapter specs the user asked for",
    ("interface/cli/env_wizard.py", "_set_dotenv_key"): "user's .env, not a store",
    ("interface/cli/env_wizard.py", "_check_gitignore"): "user's .gitignore append",
    ("interface/cli/init_project.py", "_write_gitignore"): "user's .gitignore",
    ("interface/cli/init_project.py", "_setup_claude_mcp"): "other tools' config files (agent setup)",
    ("interface/cli/init_project.py", "_register_claude_global"): "other tools' config files (agent setup)",
    ("interface/cli/init_project.py", "_setup_gemini_mcp"): "other tools' config files (agent setup)",
    ("interface/cli/init_project.py", "_register_gemini_global"): "other tools' config files (agent setup)",
    ("interface/cli/init_project.py", "_setup_cursor_mcp"): "other tools' config files (agent setup)",
    ("interface/cli/init_project.py", "_setup_vscode_mcp"): "other tools' config files (agent setup)",
    ("interface/cli/init_project.py", "_setup_copilot"): "other tools' config files (agent setup)",
    ("interface/cli/main.py", "_write_claude_hooks"): "other tools' config files (hook install)",
    ("interface/cli/main.py", "_write_cursor_rules"): "other tools' config files (hook install)",
    ("interface/cli/main.py", "_cmd_install_hooks"): "git hook scripts the user asked for",
    ("interface/cli/main.py", "_cmd_uninstall_hooks"): "git hook scripts the user asked for",
    ("interface/cli/main.py", "_strip_cognirepo_from_json"): "other tools' config files (uninstall)",
}


def _name(func) -> "str | None":
    return func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)


def _is_in_place_write(call: ast.Call) -> "str | None":
    f = call.func
    if isinstance(f, ast.Attribute):
        if f.attr in ("write_text", "write_bytes"):
            return f.attr
        if f.attr == "write_index":
            return "faiss.write_index"
        if f.attr == "save" and isinstance(f.value, ast.Name) and f.value.id in ("np", "numpy"):
            return "np.save"
    if _name(f) == "open":
        mode = call.args[1].value if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant) else None
        for kw in call.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value
        if isinstance(mode, str) and any(c in mode for c in "wax"):
            return "open(write)"
    return None


class _Finder(ast.NodeVisitor):
    def __init__(self):
        self.stack: list[ast.AST] = []
        self.funcs: list[str] = []
        self.found: list[tuple[int, str, str]] = []

    def generic_visit(self, node):
        self.stack.append(node)
        super().generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node):
        self.funcs.append(node.name)
        self.generic_visit(node)
        self.funcs.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        kind = _is_in_place_write(node)
        if kind:
            safe = False
            for anc in self.stack:
                if isinstance(anc, ast.With):
                    safe |= any(isinstance(i.context_expr, ast.Call) and _name(i.context_expr.func) == "atomic_path"
                                for i in anc.items)
                if isinstance(anc, ast.Call) and _name(anc.func) == "atomic_write_with":
                    safe = True
            if not safe:
                self.found.append((node.lineno, kind, self.funcs[-1] if self.funcs else "<module>"))
        self.generic_visit(node)


def _scan() -> list[tuple[str, int, str, str]]:
    out = []
    for root in _ROOTS:
        for path in sorted((_REPO / root).rglob("*.py")):
            rel = path.relative_to(_REPO).as_posix()
            if rel == "core/config/atomic.py":
                continue
            finder = _Finder()
            finder.visit(ast.parse(path.read_text(encoding="utf-8")))
            out += [(rel, line, kind, fn) for line, kind, fn in finder.found]
    return out


class TestNoBareStoreWrites:
    def test_every_in_place_write_goes_through_the_atomic_helper_or_is_allowlisted(self):
        offenders = [f"{rel}:{line} {kind} in {fn}()" for rel, line, kind, fn in _scan()
                     if (rel, fn) not in _ALLOWED]
        assert not offenders, (
            "Bare in-place write(s) — use core.config.atomic (atomic_write / atomic_json_dump / "
            "atomic_path) so readers never see a torn file (COGNIREPO-134), or add the function "
            "to _ALLOWED with a reason:\n  " + "\n  ".join(offenders)
        )

    def test_allowlist_has_no_stale_entries(self):
        live = {(rel, fn) for rel, _l, _k, fn in _scan()}
        stale = sorted(set(_ALLOWED) - live)
        assert not stale, f"remove from _ALLOWED (no bare write there any more): {stale}"
