# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Main entry point for the cognirepo CLI.

Global flags
------------
--via-api          Route commands through the REST API instead of calling
                   tools directly.  Useful for remote / daemon mode.
--api-url URL      Override the API base URL (default: from config or
                   http://localhost:8000).

When --via-api is NOT set (default), tools are called in-process — no
server required.
"""
import argparse
import datetime
import json
import os
import signal
import sys
import time
import traceback

from config.logging import setup_logging
setup_logging()

from cli.init_project import init_project


from config.paths import get_path


# ── helpers ──────────────────────────────────────────────────────────────────


def _print_results(results):
    if isinstance(results, list):
        for r in results:
            if isinstance(r, dict):
                print(r.get("text", r))
                if "importance" in r:
                    print("  importance:", r["importance"])
            else:
                print(r)
    else:
        print(json.dumps(results, indent=2))


def _print_search_results(results: list) -> None:
    """Display search-docs results with file path + context snippet."""
    if not results:
        return
    current_path = None
    for r in results:
        if isinstance(r, dict):
            path = r.get("path", "")
            line = r.get("line", "")
            context = r.get("context", "")
            if path != current_path:
                current_path = path
                print(f"\n{path}")
                print("─" * max(len(path), 4))
            print(f"  Line {line}:")
            for ln in context.splitlines():
                print(f"    {ln}")
        else:
            print(r)


def _log_error_to_file(exc: Exception, context: str = "") -> str:
    """
    Write a timestamped exception traceback to ``.cognirepo/errors/<date>.log``.
    Returns the log file path for display to the user. Never raises.
    """
    try:
        error_dir = get_path("errors")
        os.makedirs(error_dir, exist_ok=True)
        date_str = datetime.date.today().isoformat()
        log_path = os.path.join(error_dir, f"{date_str}.log")
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"\n[{ts}]")
            if context:
                fh.write(f" {context}")
            fh.write(f"\n{traceback.format_exc()}\n{'─' * 60}\n")
        return log_path
    except Exception:  # pylint: disable=broad-except
        return error_dir


# ── command implementations (direct) ─────────────────────────────────────────

def _direct_store(text, source, global_scope=False):
    """Call store_memory tool directly."""
    from memory.user_memory import record_action  # pylint: disable=import-outside-toplevel
    if global_scope:
        from memory.user_memory import set_preference  # pylint: disable=import-outside-toplevel
        set_preference(f"memory:{hash(text) & 0xFFFFFF}", {"text": text, "source": source})
        record_action("store-global")
        return {"status": "stored", "text": text, "source": source, "scope": "global"}
    from tools.store_memory import store_memory  # pylint: disable=import-outside-toplevel
    record_action("store")
    return store_memory(text, source)


def _direct_retrieve(query, top_k, global_scope=False):
    """Call retrieve_memory tool directly."""
    from memory.user_memory import record_action  # pylint: disable=import-outside-toplevel
    if global_scope:
        from memory.user_memory import list_preferences  # pylint: disable=import-outside-toplevel
        record_action("retrieve-global")
        prefs = list_preferences()
        # Simple keyword match over global preferences
        q = query.lower()
        results = []
        for key, val in prefs.items():
            if key.startswith("memory:") and isinstance(val, dict):
                text = val.get("text", "")
                if any(w in text.lower() for w in q.split()):
                    results.append({"text": text, "source": val.get("source", ""), "scope": "global"})
        return results[:top_k]
    from tools.retrieve_memory import retrieve_memory  # pylint: disable=import-outside-toplevel
    record_action("retrieve")
    return retrieve_memory(query, top_k)


def _direct_search(query):
    """Call search_docs tool directly."""
    from retrieval.docs_search import search_docs  # pylint: disable=import-outside-toplevel
    return search_docs(query)


def _cmd_verify_index() -> int:
    """
    Verify AST index integrity against manifest.json.

    Exit codes:
      0 — index is OK and matches the current git HEAD
      1 — index is STALE (source changed since last index) or CORRUPTED
      2 — manifest not found (run `cognirepo index-repo .` first)
    """
    # pylint: disable=import-outside-toplevel
    from indexer.ast_indexer import (
        _manifest_file, _ast_index_file, _ast_faiss_file, _ast_meta_file,
        _sha256_file, _check_platform_compat,
    )

    manifest_path = _manifest_file()
    if not os.path.exists(manifest_path):
        print("verify-index: manifest.json not found.")
        print("  Run `cognirepo index-repo .` to build the index and manifest.")
        return 2

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"verify-index: could not read manifest.json — {exc}")
        return 1

    issues = 0

    # ── Platform compatibility ─────────────────────────────────────────────
    if not _check_platform_compat(manifest):
        recorded = manifest.get("platform", {})
        import platform as _platform  # pylint: disable=import-outside-toplevel
        import faiss as _faiss  # pylint: disable=import-outside-toplevel
        print(
            f"  PLATFORM MISMATCH  index built on arch={recorded.get('arch')} "
            f"faiss={recorded.get('faiss')} but running on "
            f"arch={_platform.machine()} faiss={_faiss.__version__}"
        )
        print("  → Re-run `cognirepo index-repo .` to rebuild for this platform.")
        issues += 1

    # ── Checksum verification ──────────────────────────────────────────────
    stored_checksums = manifest.get("index_checksums", {})
    file_map = {
        "ast_index.json":    _ast_index_file(),
        "ast.index":         _ast_faiss_file(),
        "ast_metadata.json": _ast_meta_file(),
    }
    corrupted = []
    for fname, fpath in file_map.items():
        expected = stored_checksums.get(fname, "")
        actual = _sha256_file(fpath)
        if not actual:
            corrupted.append(f"  MISSING        {fname}")
        elif actual != expected:
            corrupted.append(f"  CORRUPTED      {fname}  (checksum mismatch)")

    for msg in corrupted:
        print(msg)
    if corrupted:
        print("  → Re-run `cognirepo index-repo .` to rebuild.")
        issues += len(corrupted)

    # ── Git staleness check ────────────────────────────────────────────────
    if not corrupted:
        manifest_commit = manifest.get("git_commit", "unknown")
        try:
            import subprocess as _sp  # pylint: disable=import-outside-toplevel
            current_commit = _sp.check_output(
                ["git", "rev-parse", "HEAD"], stderr=_sp.DEVNULL
            ).decode().strip()
            if manifest_commit == "unknown" or current_commit == "unknown":
                print(f"  OK             index at commit {manifest_commit[:12]} (git unavailable for comparison)")
            elif current_commit == manifest_commit:
                sym_count = manifest.get("symbol_count", "?")
                file_count = manifest.get("source_file_count", "?")
                indexed_at = manifest.get("indexed_at", "?")
                print(
                    f"  OK             {sym_count} symbols · {file_count} files · "
                    f"commit {manifest_commit[:12]} · indexed {indexed_at}"
                )
            else:
                # count how many commits behind
                try:
                    behind = _sp.check_output(
                        ["git", "rev-list", "--count", f"{manifest_commit}..HEAD"],
                        stderr=_sp.DEVNULL,
                    ).decode().strip()
                    behind_str = f"{behind} commit(s) behind"
                except Exception:  # pylint: disable=broad-except
                    behind_str = "HEAD has moved"
                print(
                    f"  STALE          index at commit {manifest_commit[:12]}, "
                    f"current HEAD is {current_commit[:12]} ({behind_str})"
                )
                print("  → Re-run `cognirepo index-repo .` to update.")
                issues += 1
        except Exception:  # pylint: disable=broad-except
            print(f"  OK             index at commit {manifest_commit[:12]} (no git to compare)")

    return 1 if issues else 0


def _cmd_coverage() -> int:
    """
    Show per-directory symbol counts from the AST index.

    Useful for spotting directories that were silently skipped during indexing
    (e.g. backend/, routes/, data/).  Prints a table and warns on zero-symbol dirs.

    Language-agnostic: detects source directories by the presence of any supported
    language file (.py, .js, .ts, .go, .java, .rs, .cpp, etc.), not just Python
    __init__.py files.

    Exit codes:
      0 — all top-level source directories have at least one symbol
      1 — one or more source directories have 0 symbols (likely missed)
    """
    from config.paths import get_path  # pylint: disable=import-outside-toplevel

    ast_index_path = get_path("index/ast_index.json")
    if not os.path.exists(ast_index_path):
        print("coverage: no AST index found — run `cognirepo index-repo .` first.")
        return 1

    try:
        with open(ast_index_path, encoding="utf-8") as f:
            index_data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"coverage: could not read ast_index.json — {exc}")
        return 1

    files: dict = index_data.get("files", {})

    # Aggregate symbol counts per top-level directory
    dir_counts: dict[str, int] = {}
    for rel_path, file_info in files.items():
        parts = rel_path.replace("\\", "/").split("/")
        top = parts[0] if len(parts) > 1 else "."
        sym_count = len(file_info.get("symbols", []))
        dir_counts[top] = dir_counts.get(top, 0) + sym_count

    if not dir_counts:
        print("coverage: index is empty — run `cognirepo index-repo .`")
        return 1

    # Language-agnostic scan: find top-level dirs with source files not yet in index
    from pathlib import Path as _Path  # pylint: disable=import-outside-toplevel
    from indexer.language_registry import supported_extensions as _supported_exts  # pylint: disable=import-outside-toplevel
    _src_exts = set(_supported_exts())
    _skip = {"venv", ".venv", "env", "node_modules", "dist", "build", "target",
             "bin", ".gradle", "vendor", ".tox", ".eggs", "__pycache__", "coverage"}
    cwd = os.getcwd()
    for entry in sorted(os.listdir(cwd)):
        full = os.path.join(cwd, entry)
        if (
            not os.path.isdir(full)
            or entry.startswith((".", "_"))
            or entry in _skip
            or entry in dir_counts
        ):
            continue
        # Shallow walk: check if any supported source file exists anywhere under this dir
        _has_sources = False
        for _dp, _dns, _fns in os.walk(full):
            _dns[:] = [d for d in _dns if d not in _skip and not d.startswith(".")]
            if any(_Path(f).suffix in _src_exts for f in _fns):
                _has_sources = True
                break
        if _has_sources:
            dir_counts[entry] = 0  # real gap: has code but 0 indexed symbols

    col_w = max(len(d) for d in dir_counts) + 2
    print(f"\n  {'Directory':<{col_w}} {'Symbols':>8}  Status")
    print("  " + "─" * (col_w + 18))

    missing = 0
    for directory in sorted(dir_counts):
        count = dir_counts[directory]
        if count == 0:
            status = "⚠  no symbols — re-run cognirepo index-repo ."
            missing += 1
        else:
            status = "✓"
        print(f"  {directory + '/':<{col_w}} {count:>8}  {status}")

    total = sum(dir_counts.values())
    print(f"\n  Total: {total} symbols across {len(files)} files\n")

    if missing:
        print(
            f"  {missing} director{'y' if missing == 1 else 'ies'} with 0 symbols. "
            "Re-index with: cognirepo index-repo .\n"
        )
        return 1
    return 0


def _cmd_doctor(verbose: bool = False, release_check: bool = False) -> int:
    """
    Run system health checks. Returns exit code 0 (all pass) or 1 (any fail).
    """
    # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    # pylint: disable=too-many-return-statements
    # pylint: disable=import-outside-toplevel
    import importlib  # pylint: disable=import-outside-toplevel

    # ── version ───────────────────────────────────────────────────────────────
    try:
        from importlib.metadata import version as _pkg_version  # pylint: disable=import-outside-toplevel
        _ver = _pkg_version("cognirepo")
    except Exception:  # pylint: disable=broad-except
        _ver = "dev"

    print(f"CogniRepo doctor — v{_ver}\n")

    issues = 0

    def _ok(msg: str) -> None:
        print(f"  \u2713  {msg}")

    def _fail(msg: str, hint: str = "") -> None:
        print(f"  \u2717  {msg}")
        if hint:
            print(f"       {hint}")
    def _warn(msg: str, hint: str = "") -> None:
        print(f"  \u26a0  {msg}")
        if hint:
            print(f"       {hint}")

    # ── Check 1: config ───────────────────────────────────────────────────────
    nonlocal_config: dict = {}
    try:
        _cfg_path = get_path("config.json")
        _cognirepo_dir = get_path("")
        if not os.path.isdir(_cognirepo_dir):
            raise FileNotFoundError(f"{_cognirepo_dir} not found")
        if not os.path.exists(_cfg_path):
            raise FileNotFoundError("config.json missing")
        with open(_cfg_path, encoding="utf-8") as _f:
            nonlocal_config = json.load(_f)
        _pname = nonlocal_config.get("project_name", "unknown")
        _ok(f"Storage — valid · project: {_pname}")
        if verbose:
            print(f"       {os.path.abspath(_cfg_path)}")
    except Exception as exc:  # pylint: disable=broad-except
        _fail(f"Storage — {exc}", "Run: cognirepo init")
        issues += 1

    # ── Check 2: FAISS index (lightweight — no model loading) ────────────────
    _faiss_path = get_path("vector_db/semantic.index")
    if os.path.exists(_faiss_path):
        try:
            import faiss as _faiss  # pylint: disable=import-outside-toplevel
            _fidx = _faiss.read_index(_faiss_path)
            _ok(f"FAISS index — {_fidx.ntotal} vectors")
            if verbose:
                print(f"       {os.path.abspath(_faiss_path)}")
        except Exception as exc:  # pylint: disable=broad-except
            _fail(f"FAISS index — {exc}", "Run: cognirepo init")
            issues += 1
    else:
        _fail("FAISS index — not found", "Run: cognirepo init")
        issues += 1

    # ── Check 3: Knowledge graph ──────────────────────────────────────────────
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        _kg = KnowledgeGraph()
        _nodes = _kg.G.number_of_nodes()
        _edges = _kg.G.number_of_edges()
        _ok(f"Knowledge graph — {_nodes:,} nodes · {_edges:,} edges")
        if verbose:
            _gpath = get_path("graph/graph.pkl")
            print(f"       {os.path.abspath(_gpath)}")
    except Exception as exc:  # pylint: disable=broad-except
        _fail(f"Knowledge graph — {exc}", "Run: cognirepo index-repo .")
        issues += 1

    # ── Check 4: AST index (lightweight — parse JSON directly, no model load) ─
    _ast_path = get_path("index/ast_index.json")
    if os.path.exists(_ast_path):
        try:
            with open(_ast_path, encoding="utf-8") as _af:
                _ast_data = json.load(_af)
            _ast_files = _ast_data.get("files", {})
            _sym_count = sum(len(v.get("symbols", [])) for v in _ast_files.values())
            if _sym_count == 0 and len(_ast_files) > 0:
                _warn(
                    f"AST index — {len(_ast_files)} files indexed but 0 symbols parsed."
                    " Queries will return empty results.",
                    "Run: cognirepo index-repo . (check language support with --verbose)",
                )
                issues += 1
            elif _sym_count == 0:
                _warn("AST index — file exists but contains no symbols.",
                      "Run: cognirepo index-repo .")
                issues += 1
            else:
                _ok(f"AST index — {_sym_count:,} symbols across {len(_ast_files)} files")
            if verbose:
                print(f"       {os.path.abspath(_ast_path)}")
        except Exception as exc:  # pylint: disable=broad-except
            _fail(f"AST index — {exc}", "Run: cognirepo index-repo .")
            issues += 1
    else:
        _fail("AST index — not found", "Run: cognirepo index-repo .")
        issues += 1

    # ── Check 4b: Index integrity manifest ───────────────────────────────────
    try:
        import platform as _plat  # pylint: disable=import-outside-toplevel
        _mf = get_path("index/manifest.json")
        if os.path.exists(_mf):
            with open(_mf, encoding="utf-8") as _mfh:
                _mdata = json.load(_mfh)
            _mcommit = _mdata.get("git_commit", "unknown")[:12]
            _mindexed = _mdata.get("indexed_at", "?")
            _mplatform = _mdata.get("platform", {})
            # Inline platform compat check — no private-function import needed
            _arch_ok = _mplatform.get("arch", "") == _plat.machine()
            try:
                import faiss as _faiss  # pylint: disable=import-outside-toplevel
                _faiss_ok = _mplatform.get("faiss", "") == _faiss.__version__
            except ImportError:
                _faiss_ok = True  # can't check without faiss
            if not (_arch_ok and _faiss_ok):
                _fail(
                    f"Index manifest — platform mismatch "
                    f"(built on {_mplatform.get('arch')}/{_mplatform.get('faiss')})",
                    "Re-run: cognirepo index-repo .",
                )
                issues += 1
            else:
                _sym = _mdata.get("symbol_count", "?")
                _ok(f"Index manifest — commit {_mcommit} · {_sym} symbols · {_mindexed}")
                if verbose:
                    print(f"       {os.path.abspath(_mf)}")
        else:
            # Not a hard failure — manifest is generated by index-repo, not init
            if verbose:
                print("  ○  Index manifest — not found (run: cognirepo index-repo .)")
    except Exception as exc:  # pylint: disable=broad-except
        if verbose:
            print(f"  ○  Index manifest — skipped ({exc})")

    # ── Check 5: Episodic log (lightweight — no decrypt attempt) ─────────────
    _ep_path = get_path("memory/episodic.json")
    if os.path.exists(_ep_path):
        try:
            with open(_ep_path, "rb") as _ef:
                _ep_raw = _ef.read()
            try:
                _ep_data = json.loads(_ep_raw)
                _ok(f"Episodic log — {len(_ep_data)} events")
            except json.JSONDecodeError:
                # File may be encrypted — that's fine, report as healthy
                _ok("Episodic log — encrypted (use retrieve-memory to query)")
            if verbose:
                print(f"       {os.path.abspath(_ep_path)}")
        except Exception as exc:  # pylint: disable=broad-except
            _fail(f"Episodic log — {exc}", "Run: cognirepo init")
            issues += 1
    else:
        _fail("Episodic log — not found", "Run: cognirepo init")
        issues += 1

    # ── Check 6: Language support matrix ─────────────────────────────────────
    try:
        from indexer.language_registry import _GRAMMAR_MAP, _get_language, clear_cache  # pylint: disable=import-outside-toplevel
        clear_cache()
        # canonical per-language check: one representative ext per language
        _lang_checks = [
            ("Python",     ".py"),
            ("TypeScript", ".ts"),
            ("JavaScript", ".js"),
            ("Go",         ".go"),
            ("Rust",       ".rs"),
            ("Java",       ".java"),
            ("C++",        ".cpp"),
        ]
        _supported_langs: list[str] = []
        _missing_langs: list[tuple[str, str]] = []  # (lang, install_hint)
        _pkg_hints = {
            ".ts":   "tree-sitter-typescript",
            ".js":   "tree-sitter-javascript",
            ".go":   "tree-sitter-go",
            ".rs":   "tree-sitter-rust",
            ".java": "tree-sitter-java",
            ".cpp":  "tree-sitter-cpp",
        }
        for _lang_name, _ext in _lang_checks:
            if _ext == ".py":
                _supported_langs.append(_lang_name)  # always available via stdlib
            elif _get_language(_ext) is not None:
                _supported_langs.append(_lang_name)
            else:
                _missing_langs.append((_lang_name, _pkg_hints.get(_ext, "")))

        _ok(f"Language support — indexable: {', '.join(_supported_langs)}")
        for _mlang, _mpkg in _missing_langs:
            _fail(
                f"Language support — {_mlang}: grammar not installed",
                f"Run: pip install {_mpkg}" if _mpkg else "",
            )
            # optional grammars are warnings, not hard failures
    except Exception as exc:  # pylint: disable=broad-except
        _ok(f"Language support — Python (built-in) [{exc}]")

    # ── Check 7: API keys ─────────────────────────────────────────────────────
    _providers = {
        "ANTHROPIC_API_KEY": "Anthropic",
        "GEMINI_API_KEY": "Gemini",
        "GOOGLE_API_KEY": "Gemini (alt)",
        "OPENAI_API_KEY": "OpenAI",
        "GROK_API_KEY": "Grok",
    }
    _found = [name for var, name in _providers.items() if os.environ.get(var)]
    if _found:
        _ok(f"Model API keys — {', '.join(_found)}")
    else:
        _fail(
            "Model API keys — no keys configured",
            "Set at least one: ANTHROPIC_API_KEY · GEMINI_API_KEY · OPENAI_API_KEY · GROK_API_KEY",
        )
        issues += 1

    # ── Check 8: Daemon heartbeat ─────────────────────────────────────────────
    try:
        from cli.daemon import heartbeat_age_seconds, read_heartbeat  # pylint: disable=import-outside-toplevel
        _hb_age = heartbeat_age_seconds()
        _hb = read_heartbeat()
        if _hb_age is None:
            _ok("Daemon heartbeat — no watcher running (start with: cognirepo watch --ensure-running .)")
        elif _hb_age < 60:
            _ok(f"Daemon heartbeat — OK (last beat: {_hb_age:.0f}s ago, PID {_hb.get('pid', '?')})")
        elif _hb_age < 120:
            _ok(f"Daemon heartbeat — slow ({_hb_age:.0f}s since last beat)")
        else:
            _fail(
                f"Daemon heartbeat — STALE ({_hb_age:.0f}s since last beat)",
                "Daemon may be dead. Run: cognirepo watch --ensure-running .",
            )
            # stale daemon is a warning — file watcher is optional for MCP operation
    except Exception as exc:  # pylint: disable=broad-except
        _ok(f"Daemon heartbeat — skipped ({exc})")

    # ── Check 9 (was 8): Circuit breaker ─────────────────────────────────────
    try:
        from memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
        import psutil  # pylint: disable=import-outside-toplevel
        _cb = get_breaker()
        _rss_mb = psutil.Process().memory_info().rss / 1024 / 1024
        _limit_mb = _cb._rss_limit_mb  # pylint: disable=protected-access
        _ok(f"Circuit breaker — {_cb.state} (RSS: {_rss_mb:.0f} MB / {_limit_mb:.0f} MB limit)")
    except Exception:  # pylint: disable=broad-except
        _ok("Circuit breaker — OK (psutil not available for RSS check)")

    # ── Check 10: BM25 backend (always shown) ────────────────────────────────
    try:
        from _bm25 import BACKEND  # pylint: disable=import-outside-toplevel
        _ok(f"BM25 backend — {BACKEND}")
    except Exception as exc:  # pylint: disable=broad-except
        _fail(f"BM25 backend — {exc}")
        issues += 1

    # ── Check N: AI tool MCP configs (informational, not failures) ───────────
    _tool_checks = [
        ("Claude Code", ".claude/settings.json", "mcpServers"),
        ("Gemini CLI",  ".gemini/settings.json", "mcpServers"),
        ("Cursor",      ".cursor/mcp.json",       "mcpServers"),
        ("VS Code",     ".vscode/mcp.json",        "servers"),
    ]
    _any_tool_configured = False
    for _tool_name, _tool_path, _tool_key in _tool_checks:
        if os.path.exists(_tool_path):
            try:
                with open(_tool_path, encoding="utf-8") as _tf:
                    _tool_cfg = json.load(_tf)
                _entries = _tool_cfg.get(_tool_key, {})
                _cognirepo_entries = [k for k in _entries if "cognirepo" in k.lower()]
                if _cognirepo_entries:
                    _ok(f"{_tool_name} — configured ({', '.join(_cognirepo_entries)})")
                    _any_tool_configured = True
                else:
                    _ok(f"{_tool_name} — {_tool_path} exists but no cognirepo entry")
            except (json.JSONDecodeError, OSError):
                _ok(f"{_tool_name} — {_tool_path} exists (unreadable)")
        elif verbose:
            print(f"  ○  {_tool_name} — not configured (run: cognirepo init)")

    if not _any_tool_configured:
        _fail("AI tools — no MCP configs found", "Run: cognirepo init (select your AI tools)")
        issues += 1

    # ── Optional verbose extras ───────────────────────────────────────────────
    if verbose:
        print("\n  Optional components:")
        for _pkg, _label in [
            ("cryptography", "cryptography (encryption at rest)"),
            ("keyring", "keyring (OS keychain)"),
        ]:
            try:
                importlib.import_module(_pkg)
                print(f"  \u25cb  {_label}: installed")
            except ImportError:
                print(f"  \u25cb  {_label}: not installed (pip install cognirepo[security])")

    # ── Release-readiness checks (opt-in) ────────────────────────────────────
    if release_check:
        print("\n  Release checks:")
        try:
            from cli.release_check import run_release_checks  # pylint: disable=import-outside-toplevel
            _rc_violations = run_release_checks()
            if not _rc_violations:
                _ok("Docs — no legacy version refs or old tier names found")
            else:
                for _v in _rc_violations:
                    _fail(f"Release: {_v}")
                issues += len(_rc_violations)
        except Exception as _exc:  # pylint: disable=broad-except
            _fail(f"Release check failed to run: {_exc}")
            issues += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    if issues == 0:
        print("\n  No issues found.")
    else:
        print(f"\n  {issues} issue(s) found.")
    return issues


def _cmd_status() -> None:
    """
    Show live retrieval signal weights, warm-up progress, and index age.
    P1-A: Cold-start transparency — users know immediately what is/isn't working.
    """
    print("\n  CogniRepo Status\n  " + "─" * 40)
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        from graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
        from retrieval.hybrid import _load_weights  # pylint: disable=import-outside-toplevel

        weights = _load_weights()
        kg = KnowledgeGraph()
        bt = BehaviourTracker(kg)

        g_nodes = kg.G.number_of_nodes()
        g_edges = kg.G.number_of_edges()
        b_count = len(bt.data.get("symbol_weights", {}))

        # Index age
        try:
            with open(get_path("index/ast_index.json"), encoding="utf-8") as f:
                idx = json.load(f)
            indexed_at = idx.get("indexed_at", "unknown")
            symbol_count = idx.get("total_symbols", 0)
            file_count = len(idx.get("files", {}))
        except (OSError, json.JSONDecodeError):
            indexed_at = "not indexed"
            symbol_count = 0
            file_count = 0

        # Signal weights
        print(f"  Retrieval weights:")
        print(f"    vector     : {weights.get('vector', 0.5):.2f}  (always active)")
        g_label = f"{weights.get('graph', 0.3):.2f}  ({'warm' if g_nodes > 10 else 'COLD — run cognirepo index-repo .'})"
        b_label = f"{weights.get('behaviour', 0.2):.2f}  ({'warm' if b_count > 50 else f'calibrating ({b_count}/50 queries)'})"
        print(f"    graph      : {g_label}")
        print(f"    behaviour  : {b_label}")

        # Index health
        print(f"\n  Index health:")
        print(f"    symbols    : {symbol_count} across {file_count} files")
        print(f"    graph      : {g_nodes:,} nodes · {g_edges:,} edges")
        print(f"    last indexed: {indexed_at}")

        # Cold-start guidance
        if g_nodes <= 10:
            print("\n  Currently running: pure vector search (graph cold)")
            print("  Fix: cognirepo index-repo . && cognirepo seed --from-git")
        elif b_count < 50:
            print(f"\n  Behaviour warm-up: {b_count}/50 queries needed")
        else:
            print("\n  Status: fully warm (all signals active)")

        # ── memory health ─────────────────────────────────────────────────────
        print("\n  Memory health:")
        try:
            from memory.episodic_memory import _load as _ep_load, _get_max_events  # pylint: disable=import-outside-toplevel
            ep_data    = _ep_load()
            ep_count   = len(ep_data)
            ep_cap     = _get_max_events()
            cap_pct    = ep_count / ep_cap * 100 if ep_cap > 0 else 0
            cap_label  = ""
            if cap_pct >= 80:
                cap_label = f"  ⚠  {cap_pct:.0f}% of cap ({ep_cap:,}) — rotation imminent"
            elif cap_pct >= 50:
                cap_label = f"  ({cap_pct:.0f}% of cap)"
            print(f"    episodic events : {ep_count:,}{cap_label}")
            archive_path = get_path("memory/episodic_archive.json")
            if os.path.exists(archive_path):
                arch_kb = os.path.getsize(archive_path) / 1024
                print(f"    episodic archive: {arch_kb:.1f} KB")
        except Exception:  # pylint: disable=broad-except
            print("    episodic events : (unavailable)")

        try:
            sem_meta = get_path("memory/semantic_metadata.json")
            if os.path.exists(sem_meta):
                with open(sem_meta, encoding="utf-8") as _smf:
                    _sm_data = json.load(_smf)
                sm_count = len(_sm_data)
                sm_kb    = os.path.getsize(sem_meta) / 1024
                print(f"    semantic memories: {sm_count:,} entries ({sm_kb:.1f} KB)")
            else:
                print("    semantic memories: 0 (not yet stored)")
        except Exception:  # pylint: disable=broad-except
            print("    semantic memories: (unavailable)")

    except Exception as exc:  # pylint: disable=broad-except
        print(f"  Error reading status: {exc}")
    print()


def _cmd_prime(as_json: bool = False) -> None:
    """
    I2: Generate a session brief for agent bootstrap.
    Outputs architecture summary, entry points, recent decisions, hot symbols.
    """
    import datetime  # pylint: disable=import-outside-toplevel
    brief: dict = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "repo": os.path.basename(os.getcwd()),
        "architecture": [],
        "entry_points": [],
        "recent_decisions": [],
        "hot_symbols": [],
        "known_blind_spots": [],
        "index_health": {},
    }

    # ── architecture from learning store ─────────────────────────────────────
    try:
        from memory.learning_store import get_learning_store  # pylint: disable=import-outside-toplevel
        store = get_learning_store()
        arch_learnings = store.retrieve_learnings("architecture overview design", top_k=3)
        brief["architecture"] = [
            {"text": lr.get("text", "")[:200], "type": lr.get("type", "")}
            for lr in arch_learnings
        ]
        recent = store.retrieve_learnings("decision bug fix", top_k=3)
        brief["recent_decisions"] = [
            {"text": lr.get("text", "")[:200], "type": lr.get("type", "")}
            for lr in recent
        ]
    except Exception:  # pylint: disable=broad-except
        pass

    # ── entry points from knowledge graph (top symbols by call frequency) ────
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        # Top nodes by in-degree (most-called symbols)
        if kg.G.number_of_nodes() > 0:
            top = sorted(
                [(n, d) for n, d in kg.G.in_degree() if not n.startswith("concept::")],
                key=lambda x: x[1],
                reverse=True,
            )[:5]
            brief["entry_points"] = [
                {"symbol": n.replace("symbol::", ""), "call_count": deg}
                for n, deg in top
            ]
    except Exception:  # pylint: disable=broad-except
        pass

    # ── hot symbols from behaviour tracker ────────────────────────────────────
    try:
        from graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
        bt = BehaviourTracker(KnowledgeGraph())  # type: ignore[arg-type]
        weights = bt.data.get("symbol_weights", {})
        # Sort by hit_count
        hot = sorted(
            [(k, v.get("hit_count", 0)) for k, v in weights.items()],
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        brief["hot_symbols"] = [
            {"symbol": k.split("::")[-1], "path": k, "score": round(v, 2)}
            for k, v in hot
        ]
    except Exception:  # pylint: disable=broad-except
        pass

    # ── index health ──────────────────────────────────────────────────────────
    try:
        with open(get_path("index/ast_index.json"), encoding="utf-8") as f:
            idx = json.load(f)
        brief["index_health"] = {
            "symbols": idx.get("total_symbols", 0),
            "files": len(idx.get("files", {})),
            "last_indexed": idx.get("indexed_at", "unknown"),
        }
    except (OSError, json.JSONDecodeError):
        brief["index_health"] = {"symbols": 0, "files": 0, "last_indexed": "not indexed"}

    # ── known blind spots ─────────────────────────────────────────────────────
    brief["known_blind_spots"] = [
        "scheduler-registered functions (add_job) require string-literal fallback in who_calls",
        "decorators-only registration (@app.route) may not appear in AST call graph",
    ]

    if as_json:
        print(json.dumps(brief, indent=2))
        return

    # ── human-readable output ─────────────────────────────────────────────────
    print(f"\n  CogniRepo Session Brief — {brief['repo']} — {brief['generated_at'][:10]}\n")

    if brief["architecture"]:
        print("  Architecture (top concepts):")
        for a in brief["architecture"]:
            print(f"    • {a['text'][:100]}")

    if brief["entry_points"]:
        print("\n  Entry points (top by call frequency):")
        for ep in brief["entry_points"]:
            print(f"    • {ep['symbol']} (called {ep['call_count']}x)")

    if brief["recent_decisions"]:
        print("\n  Recent decisions:")
        for d in brief["recent_decisions"]:
            print(f"    [{d['type']}] {d['text'][:100]}")

    if brief["hot_symbols"]:
        print("\n  Hot symbols (7 days):")
        for s in brief["hot_symbols"]:
            print(f"    • {s['symbol']} ({s['score']:.1f})")

    h = brief["index_health"]
    print(f"\n  Index health: {h.get('symbols', 0)} symbols · {h.get('files', 0)} files")
    print(f"  Last indexed: {h.get('last_indexed', 'unknown')}")

    print("\n  Known blind spots:")
    for bs in brief["known_blind_spots"]:
        print(f"    ⚠  {bs}")
    print()

    # Also save to last_context.json for inter-agent sharing
    try:
        repo_name = os.path.basename(os.getcwd())
        save_dir = os.path.join(os.path.expanduser("~"), ".cognirepo", repo_name)
        os.makedirs(save_dir, exist_ok=True)
        brief["session_brief"] = True
        with open(os.path.join(save_dir, "last_context.json"), "w", encoding="utf-8") as f:
            json.dump(brief, f, indent=2)
    except Exception:  # pylint: disable=broad-except
        pass


def _cmd_doctor_fix() -> int:
    """
    P2-B: Auto-fix top 2 failure modes:
    1. FAISS index corruption → delete and rebuild
    2. Embedding dimension mismatch → detect from metadata, reindex
    Returns exit code.
    """
    print("CogniRepo doctor --fix\n")
    fixes_applied = 0

    # ── Fix 1: FAISS semantic index ──────────────────────────────────────────
    faiss_path = get_path("vector_db/semantic.index")
    if os.path.exists(faiss_path):
        try:
            import faiss  # pylint: disable=import-outside-toplevel
            _idx = faiss.read_index(faiss_path)
            print(f"  ✓  FAISS semantic index — OK ({_idx.ntotal} vectors)")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  ✗  FAISS semantic index — CORRUPT ({exc})")
            print("     Deleting stale index and rebuilding...")
            try:
                stale = faiss_path + ".stale"
                os.rename(faiss_path, stale)
                import faiss  # pylint: disable=import-outside-toplevel,reimported
                _new = faiss.IndexFlatL2(384)
                faiss.write_index(_new, faiss_path)
                print(f"     Fixed — empty index created at {faiss_path}")
                print(f"     Run `cognirepo index-repo .` to rebuild embeddings")
                fixes_applied += 1
            except Exception as fix_exc:  # pylint: disable=broad-except
                print(f"     Auto-fix failed: {fix_exc}")

    # ── Fix 2: AST FAISS index corruption / dimension mismatch ───────────────
    ast_faiss_path = get_path("index/ast.index")
    ast_meta_path = get_path("index/ast_metadata.json")
    if os.path.exists(ast_faiss_path):
        try:
            import faiss  # pylint: disable=import-outside-toplevel,reimported
            _ast_idx = faiss.read_index(ast_faiss_path)
            # Check dimension matches expected (384 for all-MiniLM-L6-v2)
            expected_dim = 384
            actual_dim = getattr(_ast_idx, "d", expected_dim)
            if actual_dim != expected_dim:
                print(f"  ✗  AST FAISS index — DIMENSION MISMATCH ({actual_dim} != {expected_dim})")
                print(f"     Renaming stale index and scheduling reindex...")
                os.rename(ast_faiss_path, ast_faiss_path + ".stale")
                if os.path.exists(ast_meta_path):
                    os.rename(ast_meta_path, ast_meta_path + ".stale")
                print("     Fixed — run `cognirepo index-repo .` to rebuild")
                fixes_applied += 1
            else:
                print(f"  ✓  AST FAISS index — OK ({_ast_idx.ntotal} vectors, dim={actual_dim})")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  ✗  AST FAISS index — CORRUPT ({exc})")
            try:
                os.rename(ast_faiss_path, ast_faiss_path + ".stale")
                print("     Renamed stale index — run `cognirepo index-repo .` to rebuild")
                fixes_applied += 1
            except OSError:
                pass

    if fixes_applied == 0:
        print("\n  No fixable issues found. Run `cognirepo doctor` for full health check.")
    else:
        print(f"\n  Applied {fixes_applied} fix(es). Run `cognirepo index-repo .` to rebuild index.")

    return 0


def _print_ready_summary(summary: dict | None = None) -> None:
    """Print the 'You're ready!' end-of-init summary."""
    print("\n" + "─" * 60)
    print("  You're ready! CogniRepo is set up.\n")

    print("  MCP tools Claude can now call:")
    tools = [
        ("context_pack",     "Token-efficient code context (saves 15–25% tokens)"),
        ("lookup_symbol",    "O(1) symbol lookup across the whole codebase"),
        ("who_calls",        "Impact analysis — find all callers of a function"),
        ("subgraph",         "Knowledge graph neighbourhood for any module"),
        ("retrieve_memory",  "Semantic search over stored decisions and notes"),
        ("search_docs",      "Full-text search across all .md documentation"),
        ("store_memory",     "Persist insights for future sessions"),
        ("log_episode",      "Record milestones and decisions to the event log"),
    ]
    for name, desc in tools:
        print(f"    • {name:<20} {desc}")

    if summary:
        files  = summary.get("files_indexed", summary.get("files", 0))
        syms   = summary.get("symbols", 0)
        print(f"\n  Index stats: {files} files · {syms} symbols")
        # rough token reduction estimate: ~200 tokens saved per retrieval vs raw read
        est_reduction = min(int(syms * 0.15), 5000)
        if est_reduction > 0:
            print(f"  Estimated token reduction: ~{est_reduction} tokens/query")

    print("\n  Next steps:")
    print("    cognirepo doctor          — check system health")
    print("    cognirepo retrieve-memory — search your stored context")
    print("    cognirepo store-memory    — save a new insight")
    print("─" * 60 + "\n")


def _maybe_tip_index_repo() -> None:
    """Print an index-repo tip when the graph is empty (cold-start hint)."""
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        if KnowledgeGraph().G.number_of_nodes() == 0:
            print("Tip: run 'cognirepo index-repo .' to enable graph-based retrieval.")
    except Exception:  # pylint: disable=broad-except
        pass


def _direct_log(event, metadata):
    """Log an episodic event directly."""
    from memory.episodic_memory import log_event  # pylint: disable=import-outside-toplevel
    log_event(event, metadata)
    return {"status": "logged", "event": event}


def _direct_history(limit):
    """Fetch episodic history directly."""
    from memory.episodic_memory import get_history  # pylint: disable=import-outside-toplevel
    return get_history(limit)


def _direct_index(path, embed: bool = True):
    """Index a repository directly. Exits with code 1 if *path* does not exist."""
    abs_path = os.path.abspath(path)
    if not os.path.isdir(abs_path):
        print(
            f"Error: Directory does not exist: {abs_path}",
            file=sys.stderr,
        )
        sys.exit(1)
    from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
    from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
    kg = KnowledgeGraph()
    indexer = ASTIndexer(graph=kg)
    summary = indexer.index_repo(abs_path, embed=embed)
    kg.save()
    return {"status": "indexed", "path": abs_path, **summary}, kg, indexer


def _start_watcher(path: str, kg, indexer, daemon: bool = False) -> None:
    """Start the file watcher, optionally forking into the background."""
    import os  # pylint: disable=import-outside-toplevel
    from graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
    from indexer.file_watcher import create_watcher  # pylint: disable=import-outside-toplevel

    abs_path = os.path.abspath(path)

    # ── TASK-009: Singleton enforcement ──────────────────────────────────────
    from cli.daemon import is_watcher_running_for_path  # pylint: disable=import-outside-toplevel
    existing = is_watcher_running_for_path(abs_path)
    if existing:
        print(
            f"[cognirepo] Daemon already running for this path "
            f"(PID {existing['pid']}, name: {existing['name']}). "
            f"Use 'cognirepo list' to inspect or 'cognirepo list -n {existing['pid']} --stop' to stop."
        )
        return

    ts = int(time.time())
    session_id = f"watch_{ts}"

    if daemon:
        from cli.daemon import daemonize, flock_register_watcher  # pylint: disable=import-outside-toplevel
        from pathlib import Path  # pylint: disable=import-outside-toplevel

        cognirepo_dir = Path(get_path(""))
        cognirepo_dir.mkdir(parents=True, exist_ok=True)
        log_path = str(cognirepo_dir / "watchers" / f"{session_id}.log")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)

        name = f"watcher-{Path(abs_path).name}-{ts}"
        child_pid = daemonize(log_path)
        if child_pid > 0:
            # We are the parent — register PID file atomically and return
            flock_register_watcher(child_pid, name, abs_path, log_path)
            print(f"[cognirepo] Watcher started in background (PID {child_pid})")
            print(f"[cognirepo] Name : {name}")
            print(f"[cognirepo] Log  : {log_path}")
            print(f"[cognirepo] View : cognirepo list -n {child_pid} --view")
            return
        # child (grandchild) continues below

    behaviour = BehaviourTracker(graph=kg)

    # ── TASK-008: Crash-recovery loop ─────────────────────────────────────────
    from cli.daemon import run_watcher_with_crash_guard  # pylint: disable=import-outside-toplevel

    if not daemon:
        print(f"Watching {abs_path} for changes. Ctrl+C to stop.")

    def _make_observer():
        return create_watcher(abs_path, indexer, kg, behaviour, session_id)

    def _stop_observer(obs):
        obs.stop()
        obs.join()

    def _stop(signum, frame):  # pylint: disable=unused-argument
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)

    run_watcher_with_crash_guard(
        create_fn=_make_observer,
        stop_fn=_stop_observer,
        watcher_path=abs_path,
        session_id=session_id,
    )
    if not daemon:
        print("[watcher] stopped.")


def _start_watcher_bg(path: str) -> None:
    """
    Start the file watcher as a daemon thread — no kg/indexer required upfront.
    Loads them lazily inside the thread. Safe to call from REPL/MCP server startup.
    Silently skips if a watcher is already running for this path.
    """
    abs_path = os.path.abspath(path)
    try:
        from cli.daemon import is_watcher_running_for_path  # pylint: disable=import-outside-toplevel
        if is_watcher_running_for_path(abs_path):
            return  # already watching — skip silently
    except Exception:  # pylint: disable=broad-except
        pass

    def _run():
        try:
            from graph.knowledge_graph import KnowledgeGraph as _KG    # pylint: disable=import-outside-toplevel
            from indexer.ast_indexer import ASTIndexer as _AI          # pylint: disable=import-outside-toplevel
            from graph.behaviour_tracker import BehaviourTracker as _BT # pylint: disable=import-outside-toplevel
            from indexer.file_watcher import create_watcher             # pylint: disable=import-outside-toplevel
            from cli.daemon import run_watcher_with_crash_guard         # pylint: disable=import-outside-toplevel
            import time as _time                                         # pylint: disable=import-outside-toplevel
            _kg = _KG()
            _indexer = _AI(graph=_kg)
            _indexer.load()
            _bt = _BT(graph=_kg)
            _session_id = f"watch_auto_{int(_time.time())}"

            def _make():
                return create_watcher(abs_path, _indexer, _kg, _bt, _session_id)

            def _stop(obs):
                obs.stop()
                obs.join()

            run_watcher_with_crash_guard(
                create_fn=_make,
                stop_fn=_stop,
                watcher_path=abs_path,
                session_id=_session_id,
            )
        except Exception:  # pylint: disable=broad-except
            pass  # watcher is best-effort

    import threading as _threading  # pylint: disable=import-outside-toplevel
    _t = _threading.Thread(target=_run, daemon=True, name="cognirepo-auto-watcher")
    _t.start()


def _test_connection(provider: str) -> dict:
    """Make a minimal API call to verify connectivity and credentials."""
    from orchestrator.model_adapters.errors import ModelCallError  # pylint: disable=import-outside-toplevel
    query = "ping"
    system = "Reply with one word."
    manifest: list = []

    try:
        if provider == "anthropic":
            from orchestrator.model_adapters import anthropic_adapter  # pylint: disable=import-outside-toplevel
            resp = anthropic_adapter.call(query, system, manifest, max_tokens=10)
        elif provider == "gemini":
            from orchestrator.model_adapters import gemini_adapter  # pylint: disable=import-outside-toplevel
            resp = gemini_adapter.call(query, system, manifest, max_tokens=10)
        elif provider == "grok":
            from orchestrator.model_adapters import grok_adapter  # pylint: disable=import-outside-toplevel
            resp = grok_adapter.call(query, system, manifest, max_tokens=10)
        elif provider == "openai":
            from orchestrator.model_adapters import openai_adapter as oa  # pylint: disable=import-outside-toplevel
            resp = oa.call(query, system, manifest, max_tokens=10)
        else:
            return {
                "status": "error", "provider": provider,
                "error": f"Unknown provider '{provider}'"
            }
        return {
            "status": "ok",
            "provider": provider,
            "model": resp.model,
            "response": resp.text[:120],
        }
    except ModelCallError as exc:
        return {
            "status": "error",
            "provider": provider,
            "http_status": exc.status_code,
            "error": exc.message,
        }
    except Exception as exc:  # pylint: disable=broad-except
        return {"status": "error", "provider": provider, "error": str(exc)}


def _resolve_session(continue_session: bool, session_id: str | None) -> dict | None:
    """Return the session to continue, or None if starting fresh."""
    from orchestrator.session import load_current_session, find_session  # pylint: disable=import-outside-toplevel
    if session_id:
        sess = find_session(session_id)
        if sess is None:
            print(f"Session {session_id!r} not found.", file=sys.stderr)
            sys.exit(1)
        return sess
    if continue_session:
        sess = load_current_session()
        if sess is None:
            print("No current session found. Starting a new one.", file=sys.stderr)
        return sess
    return None


def _save_exchange(session, query: str, response_text: str, model: str = "") -> None:
    """Create or append to the session file, enforcing the history cap."""
    from orchestrator.session import (  # pylint: disable=import-outside-toplevel
        create_session, append_exchange, load_max_exchanges,
    )
    if session is None:
        session = create_session(model=model)
    append_exchange(session, query, response_text, max_exchanges=load_max_exchanges())


def _direct_ask(
    query,
    force_model,
    top_k,
    verbose,
    no_stream=False,
    continue_session=False,
    session_id=None,
    no_history=False,
):
    # ── resolve session ───────────────────────────────────────────────────────
    session = None if no_history else _resolve_session(continue_session, session_id)
    messages_history = session["messages"] if session else None

    resolved_model = force_model or ""

    if no_stream:
        # Blocking mode: collect full response, then print
        from orchestrator.router import route  # pylint: disable=import-outside-toplevel
        result = route(
            query, force_model=force_model, top_k=top_k,
            messages_history=messages_history,
        )
        if verbose:
            clf = result.classifier
            b = result.bundle
            W = 60
            print(f"\n\u250c\u2500 Classifier {'─' * (W - 13)}")
            print(f"\u2502  tier     : {clf.tier}")
            print(f"\u2502  score    : {clf.score:.1f}")
            print(f"\u2502  model    : {clf.model}  ({clf.provider})")
            if clf.signals:
                print("\u2502  signals  :")
                for sig, val in sorted(clf.signals.items(),
                                       key=lambda x: abs(x[1]), reverse=True):
                    bar = f"+{val:.1f}" if val >= 0 else f"{val:.1f}"
                    print(f"\u2502    {sig:<28} {bar}")
            if getattr(clf, "overrides", None):
                print(f"\u2502  overrides: {', '.join(clf.overrides)}")
            print(f"\u251c\u2500 Context bundle {'─' * (W - 17)}")
            trimmed_flag = "  [TRIMMED]" if b.was_trimmed else ""
            print(f"\u2502  tokens   : {b.token_count:,}/{b.max_tokens:,}{trimmed_flag}")
            mem_count = len(b.memories) + len(b.ast_hits)
            ep_count  = len(b.recent_episodes)
            print(f"\u2502  memories : {mem_count} retrieved  ·  episodes: {ep_count}")
            top_hits = (b.memories + b.ast_hits)[:5]
            for hit in top_hits:
                score = hit.get("final_score", hit.get("importance", 0.0))
                src   = hit.get("text", "")[:50].replace("\n", " ")
                print(f"\u2502    [{score:.2f}] {src}")
            print(f"\u2514{'─' * W}")
            print()
        if result.error:
            print(f"ERROR: {result.error}", file=sys.stderr)
        if result.response.tool_calls:
            print("\n[tool calls]")
            for tc in result.response.tool_calls:
                print(" ", json.dumps(tc))
        response_text = result.response.text
        resolved_model = result.classifier.model
    else:
        # Streaming mode (default): print each chunk as it arrives
        from orchestrator.router import stream_route  # pylint: disable=import-outside-toplevel
        full_text: list[str] = []
        try:
            for chunk in stream_route(
                query, force_model=force_model, top_k=top_k,
                messages_history=messages_history,
            ):
                print(chunk, end="", flush=True)
                full_text.append(chunk)
        except KeyboardInterrupt:
            print()
            sys.exit(0)
        print()  # trailing newline
        response_text = "".join(full_text)

    # ── persist exchange ──────────────────────────────────────────────────────
    if not no_history and response_text:
        _save_exchange(session, query, response_text, model=resolved_model)

    return response_text


def _cmd_sessions(limit: int = 20) -> None:
    """Print a table of recent sessions."""
    from orchestrator.session import list_sessions, current_session_id  # pylint: disable=import-outside-toplevel
    sessions = list_sessions(limit=limit)
    if not sessions:
        print("No sessions found. Run 'cognirepo ask' to start one.")
        return
    cur = current_session_id()
    print(f"{'ID':8}  {'CREATED':19}  {'EX':>2}  FIRST QUERY")
    print("-" * 72)
    for s in sessions:
        sid = s["session_id"]
        short_id = sid[:8]
        created = s.get("created_at", "")[:19].replace("T", " ")
        msgs = s.get("messages", [])
        exchanges = len(msgs) // 2
        first_q = next((m["content"] for m in msgs if m["role"] == "user"), "(empty)")
        first_q = first_q[:42] + "…" if len(first_q) > 43 else first_q
        marker = " ← current" if sid == cur else ""
        print(f"{short_id}  {created}  {exchanges:>2}x  \"{first_q}\"{marker}")


# ── main ──────────────────────────────────────────────────────────────────────

def _print_help() -> None:
    """Print a rich, formatted help screen for cognirepo."""
    try:
        from importlib.metadata import version as _pkg_ver  # pylint: disable=import-outside-toplevel
        _ver = _pkg_ver("cognirepo")
    except Exception:  # pylint: disable=broad-except
        _ver = "dev"

    _C  = "\033[36m"    # cyan
    _G  = "\033[32m"    # green
    _Y  = "\033[33m"    # yellow
    _D  = "\033[2m"     # dim
    _B  = "\033[1m"     # bold
    _R  = "\033[0m"     # reset

    use_color = (
        hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
        and os.environ.get("TERM", "xterm") != "dumb"
        and os.environ.get("NO_COLOR") is None
    )

    def c(*codes_then_text):
        text = codes_then_text[-1]
        if not use_color:
            return text
        codes = "".join(codes_then_text[:-1])
        return f"{codes}{text}{_R}"

    W = 62  # inner box width

    def _hdr(title):
        print(f"\n  {c(_C, _B, title)}")
        print(f"  {'─' * W}")

    def _row(cmd, desc, indent=4):
        col = 22
        pad = " " * indent
        cmd_s = c(_G, cmd)
        # Visible-width padding (cmd has ANSI codes that don't count toward width)
        spaces = " " * max(1, col - len(cmd))
        print(f"  {pad}{cmd_s}{spaces}{c(_D, desc)}")

    def _flag(flag, desc):
        col = 22
        spaces = " " * max(1, col - len(flag))
        print(f"    {c(_Y, flag)}{spaces}{c(_D, desc)}")

    # ── header ────────────────────────────────────────────────────────────────
    print()
    print(f"  ┌{'─' * (W + 2)}┐")
    _title = f"CogniRepo  v{_ver}"
    _sub   = "Local Cognitive Infrastructure for AI Agents"
    print(f"  │ {c(_C, _B, _title)}{' ' * (W - len(_title) + 1)}│")
    print(f"  │ {c(_D, _sub)}{' ' * (W - len(_sub) + 1)}│")
    print(f"  └{'─' * (W + 2)}┘")

    # ── usage ─────────────────────────────────────────────────────────────────
    print(f"\n  {c(_B, 'USAGE')}")
    print(f"  {'─' * W}")
    print(f"    {c(_G, 'cognirepo')} {c(_Y, '<command>')} {c(_D, '[options]')}")

    # ── Setup & Index ─────────────────────────────────────────────────────────
    _hdr("SETUP & INDEX")
    _row("init",               "Interactive wizard — scaffold .cognirepo/ + MCP config")
    _row("index-repo [path]",  "AST-index a codebase for symbol lookup & graph")
    _row("seed",               "Seed behaviour graph from recent git log")
    _row("mcp-setup",          "Re-run MCP integration (Claude / Gemini)")

    # ── Memory ────────────────────────────────────────────────────────────────
    _hdr("MEMORY")
    _row("store-memory <txt>",      "Save semantic memory to FAISS index")
    _row("store-memory --global",   "Save to ~/.cognirepo/ user store (cross-project)")
    _row("retrieve-memory <q>",     "Similarity search over stored memories")
    _row("retrieve-memory --global","Search ~/.cognirepo/ user store")
    _row("user-prefs",              "View/set global user preferences and behaviour")
    _row("log-episode <event>",     "Append an event to the episodic log")
    _row("history",                 "Print recent episodic events")
    _row("episodic-search <q>",     "Keyword search in episodic event history")
    _row("prune",                   "Remove low-score / stale memories")

    # ── Search & Code ─────────────────────────────────────────────────────────
    _hdr("SEARCH & CODE")
    _row("search-docs <q>",   "Full-text search in all .md files with snippets")
    _row("lookup-symbol <n>", "Find where a function/class is defined (file:line)")
    _row("who-calls <fn>",    "Trace callers of a function in the call graph")
    _row("subgraph <entity>", "Show knowledge-graph neighbourhood for an entity")
    _row("graph-stats",       "Node/edge count and health of the knowledge graph")

    # ── AI Query ──────────────────────────────────────────────────────────────
    _hdr("AI QUERY")
    _row("ask <query>",       "Route query through multi-model orchestrator")
    _row("sessions",          "List recent conversation sessions")
    _row("test-connection",   "Verify API key & connectivity per provider")

    # ── Servers ───────────────────────────────────────────────────────────────
    _hdr("SERVERS")
    _row("serve",             "Start MCP stdio server (used by Claude Code)")
    _row("export-spec",       "Export OpenAI/Cursor tool specs to adapters/")

    # ── System ────────────────────────────────────────────────────────────────
    _hdr("SYSTEM")
    _row("doctor",            "Full installation health check")
    _row("list",              "List / inspect / stop running watcher daemons")
    _row("install-hooks",      "Install git post-commit hook for incremental reindex")
    _row("uninstall-hooks",    "Remove cognirepo git hook block from post-commit")
    _row("update-directives",  "Regenerate agent directive files from latest templates")

    # ── Global flags ──────────────────────────────────────────────────────────
    print(f"\n  {c(_B, 'GLOBAL FLAGS')}")
    print(f"  {'─' * W}")
    _flag("--verbose, -v",    "Verbose output (where supported)")
    _flag("-h, --help",       "Show this help screen")

    # ── footer ────────────────────────────────────────────────────────────────
    print(f"\n  {c(_D, 'Run')} {c(_G, 'cognirepo <command> --help')} {c(_D, 'for command-specific options.')}")
    print(f"  {c(_D, 'Docs:')} {c(_C, 'github.com/ashlesh-t/cognirepo')}")
    print()


def _find_git_dir() -> "Path | None":
    """Walk up from cwd to find .git/ directory. Returns its Path or None."""
    from pathlib import Path  # pylint: disable=import-outside-toplevel
    here = Path.cwd()
    for parent in [here, *here.parents]:
        if (parent / ".git").is_dir():
            return parent / ".git"
    return None


_HOOK_SENTINEL_START = "# >>> cognirepo-hook-start <<<"
_HOOK_SENTINEL_END   = "# >>> cognirepo-hook-end <<<"
_HOOK_BLOCK = (
    _HOOK_SENTINEL_START + "\n"
    "changed=$(git diff-tree --no-commit-id -r --name-only HEAD \\\n"
    "  | grep -E '\\.(py|js|ts|java|go|rs|cpp|c|h)$')\n"
    "if [ -n \"$changed\" ]; then\n"
    "  cognirepo index-repo --files $changed --no-watch 2>/dev/null &\n"
    "fi\n"
    + _HOOK_SENTINEL_END + "\n"
)


def _cmd_install_hooks() -> int:
    """Write a post-commit git hook that incrementally reindexes changed files."""
    from pathlib import Path  # pylint: disable=import-outside-toplevel
    git_dir = _find_git_dir()
    if git_dir is None:
        print("install-hooks: not a git repository (no .git/ found).")
        return 1
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_file = hooks_dir / "post-commit"
    if hook_file.exists():
        content = hook_file.read_text(encoding="utf-8")
        if _HOOK_SENTINEL_START in content:
            print("install-hooks: cognirepo block already present.")
            return 0
        hook_file.write_text(content.rstrip("\n") + "\n\n" + _HOOK_BLOCK, encoding="utf-8")
    else:
        hook_file.write_text("#!/bin/sh\n" + _HOOK_BLOCK, encoding="utf-8")
    hook_file.chmod(0o755)
    print(f"install-hooks: wrote post-commit hook → {hook_file}")
    return 0


def _cmd_uninstall_hooks() -> int:
    """Remove the cognirepo block from .git/hooks/post-commit."""
    from pathlib import Path  # pylint: disable=import-outside-toplevel
    import re as _re  # pylint: disable=import-outside-toplevel
    git_dir = _find_git_dir()
    if git_dir is None:
        print("uninstall-hooks: not a git repository.")
        return 1
    hook_file = git_dir / "hooks" / "post-commit"
    if not hook_file.exists():
        print("uninstall-hooks: cognirepo block not found (no post-commit hook).")
        return 0
    content = hook_file.read_text(encoding="utf-8")
    if _HOOK_SENTINEL_START not in content:
        print("uninstall-hooks: cognirepo block not found.")
        return 0
    # Remove block between sentinels (inclusive)
    cleaned = _re.sub(
        r"\n*" + _re.escape(_HOOK_SENTINEL_START) + r".*?" + _re.escape(_HOOK_SENTINEL_END) + r"\n?",
        "",
        content,
        flags=_re.DOTALL,
    ).rstrip("\n") + "\n"
    stripped = cleaned.strip()
    if stripped in ("", "#!/bin/sh"):
        hook_file.unlink()
        print(f"uninstall-hooks: removed post-commit hook entirely ({hook_file})")
    else:
        hook_file.write_text(cleaned, encoding="utf-8")
        print(f"uninstall-hooks: removed cognirepo block from {hook_file}")
    return 0


def _cmd_update_directives() -> int:
    """Regenerate all agent directive files from the current STD_PROMPTS templates.

    Detects which agents are present in the project and re-runs setup_mcp for each,
    overwriting CLAUDE.md, GEMINI.md, .cursor/rules/cognirepo.mdc, and
    .github/copilot-instructions.md with the latest template content.
    """
    import shutil  # pylint: disable=import-outside-toplevel
    from pathlib import Path  # pylint: disable=import-outside-toplevel
    from cli.init_project import setup_mcp  # pylint: disable=import-outside-toplevel
    from config.paths import get_cognirepo_dir  # pylint: disable=import-outside-toplevel

    cwd = os.getcwd()

    # Load project name from config if available
    project_name = os.path.basename(cwd)
    try:
        cfg_path = os.path.join(get_cognirepo_dir(), "config.json")
        with open(cfg_path, encoding="utf-8") as _f:
            _cfg = json.load(_f)
        project_name = _cfg.get("project_name", project_name)
    except Exception:  # pylint: disable=broad-except
        pass

    # Detect which agents are present
    agents: list[str] = []
    if shutil.which("claude") or Path(cwd).joinpath(".claude").exists():
        agents.append("claude")
    if shutil.which("gemini") or Path(cwd).joinpath(".gemini").exists():
        agents.append("gemini")
    if Path(cwd).joinpath(".cursor").exists():
        agents.append("cursor")
    if Path(cwd).joinpath(".github").exists():
        agents.append("copilot")
    if Path(cwd).joinpath(".vscode").exists():
        agents.append("vscode")

    if not agents:
        # Default: regenerate claude (always useful) and any that have existing dirs
        agents = ["claude"]

    print(f"update-directives: regenerating for agents: {', '.join(agents)}")
    setup_mcp(agents, project_name=project_name, project_path=cwd)
    print("update-directives: done.")
    return 0


def main():
    """CLI entry point — parse args and route to commands."""
    # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    # pylint: disable=too-many-return-statements
    # pylint: disable=import-outside-toplevel
    from dotenv import load_dotenv
    load_dotenv()  # load .env from cwd (and parent dirs) before anything else

    # Show custom help if -h/--help is the first argument (before argparse runs)
    if len(sys.argv) == 1 or (len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help")):
        _print_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        prog="cognirepo",
        add_help=False,             # we handle -h ourselves via _print_help()
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # global flags
    parser.add_argument(
        "-h", "--help",
        action="store_true",
        default=False,
        help="Show help and exit.",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Scaffold .cognirepo/ and config")
    p_init.add_argument(
        "--no-index",
        action="store_true",
        default=False,
        help="Skip the index-repo prompt (useful for scripting).",
    )
    p_init.add_argument(
        "--daemon", "-d",
        action="store_true",
        default=False,
        help="Run the file watcher in the background as a daemon.",
    )
    p_init.add_argument(
        "--non-interactive",
        action="store_true",
        default=False,
        help="Use all defaults without prompting (for CI/scripted setup).",
    )

    # serve
    p_serve = sub.add_parser("serve", help="Start the MCP stdio server")
    p_serve.add_argument(
        "--project-dir",
        nargs="?",
        const=".",
        default=None,
        metavar="DIR",
        help=(
            "Lock this MCP server instance to a specific project directory. "
            "All tools read/write storage inside DIR. "
            "Omit to use current directory (or global storage if not found). "
            "Required when Claude has multiple projects open simultaneously "
            "so each connector sees only its own data."
        ),
    )

    # store-memory
    p_store = sub.add_parser("store-memory", help="Save a semantic memory")
    p_store.add_argument("text")
    p_store.add_argument("--source", default="", help="Origin label")
    p_store.add_argument("--global", dest="global_scope", action="store_true",
                         help="Save to ~/.cognirepo/ user store (cross-project)")

    # retrieve-memory
    p_ret = sub.add_parser("retrieve-memory", help="Semantic similarity search")
    p_ret.add_argument("query")
    p_ret.add_argument("--top-k", type=int, default=5)
    p_ret.add_argument("--global", dest="global_scope", action="store_true",
                       help="Search ~/.cognirepo/ user store instead of project store")

    # user-prefs
    p_prefs = sub.add_parser("user-prefs", help="View/set global user preferences (~/.cognirepo/)")
    p_prefs.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"),
                         help="Set a preference: --set key value")
    p_prefs.add_argument("--behaviour", action="store_true",
                         help="Show auto-tracked behaviour pattern counts")

    # search-docs
    p_search = sub.add_parser("search-docs", help="Full-text search in .md docs")
    p_search.add_argument("query")

    # log-episode
    p_log = sub.add_parser("log-episode", help="Append an episodic event")
    p_log.add_argument("event")
    p_log.add_argument("--meta", default="{}", metavar="JSON",
                       help="JSON metadata object (default: {})")

    # history
    p_hist = sub.add_parser("history", help="Print recent episodic events")
    p_hist.add_argument("--limit", type=int, default=20)

    # index-repo
    p_idx = sub.add_parser("index-repo", help="AST-index a codebase for hybrid retrieval")
    p_idx.add_argument(
        "path", nargs="?", default=".",
        help="Repo root to index (default: current dir)"
    )
    p_idx.add_argument(
        "--no-embed",
        action="store_true",
        default=False,
        help="Skip FAISS embedding (AST/symbol index only). Faster; useful in CI or first-pass indexing.",
    )
    p_idx.add_argument(
        "--no-watch",
        action="store_true",
        default=False,
        help="Exit immediately after indexing without starting the file watcher (useful in CI).",
    )
    p_idx.add_argument(
        "--daemon", "-d",
        action="store_true",
        default=False,
        help="Run the file watcher in the background as a daemon.",
    )
    p_idx.add_argument(
        "--files",
        nargs="+",
        metavar="FILE",
        default=None,
        help=(
            "Re-index specific files only (relative or absolute paths). "
            "Skips full repo walk — useful for git hooks and CI incremental runs."
        ),
    )
    p_idx.add_argument(
        "--changed-only",
        action="store_true",
        default=False,
        help=(
            "Auto-detect changed files via git (git diff --name-only HEAD + "
            "untracked files) and reindex only those. Ideal for post-commit hooks."
        ),
    )

    # benchmark
    p_bench = sub.add_parser("benchmark", help="Run quantitative value benchmarks")
    p_bench.add_argument("--json", action="store_true", help="Output raw JSON instead of report")
    p_bench.add_argument("--compare", action="store_true", help="Compare with previous run")

    # migrate-config
    p_migrate = sub.add_parser(
        "migrate-config",
        help="Rename deprecated tier names in .cognirepo/config.json (FAST→STANDARD etc.)",
    )
    p_migrate.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without writing anything",
    )

    # export-spec
    sub.add_parser("export-spec", help="Export OpenAI/Cursor tool specs to adapters/")

    # prune
    p_prune = sub.add_parser("prune", help="Prune low-score memories")
    p_prune.add_argument("--dry-run", action="store_true")
    p_prune.add_argument("--aggressive", action="store_true")
    p_prune.add_argument("--archive", action="store_true")
    p_prune.add_argument("--threshold", type=float, default=None)
    p_prune.add_argument("--verbose", action="store_true")

    # seed
    p_seed = sub.add_parser("seed", help="Seed behaviour tracker and learning store from git log")
    p_seed.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show which files/symbols would be seeded without writing anything.",
    )
    p_seed.add_argument(
        "--path",
        default=".",
        metavar="DIR",
        help="Repo root to read git history from (default: current dir).",
    )
    p_seed.add_argument(
        "--from-git",
        action="store_true",
        default=False,
        help="Also parse commit messages (fix:/decision:/breaking:) and ADR files into learning store.",
    )
    p_seed.add_argument(
        "--comments",
        action="store_true",
        default=False,
        help="Also scan source files for FIXME/HACK/NOTE comments (slow on large repos).",
    )

    # test-connection
    p_tc = sub.add_parser("test-connection", help="Verify API key and connectivity for a provider")
    p_tc.add_argument(
        "--provider",
        default=None,
        choices=["anthropic", "gemini", "grok", "openai"],
        metavar="PROVIDER",
        help="Provider to test: anthropic | gemini | grok | openai. "
             "Omit to test all configured providers.",
    )

    # ask
    p_ask = sub.add_parser("ask", help="Route a query through the multi-model orchestrator")
    p_ask.add_argument("query", help="Natural language query")
    p_ask.add_argument("--model", default=None, metavar="MODEL_ID",
                       help="Force a specific model ID (e.g. claude-opus-4-6)")
    p_ask.add_argument("--top-k", type=int, default=5,
                       help="Memories to retrieve for context (default: 5)")
    p_ask.add_argument("--verbose", action="store_true",
                       help="Print classifier tier/score/signals before response")
    p_ask.add_argument(
        "--no-stream",
        action="store_true",
        default=False,
        help="Collect full response before printing (useful for piping to other commands).",
    )
    p_ask.add_argument(
        "--continue", dest="continue_session",
        action="store_true", default=False,
        help="Continue the most recent conversation session.",
    )
    p_ask.add_argument(
        "--session",
        default=None,
        metavar="ID",
        help="Resume a specific session by ID or ID prefix.",
    )
    p_ask.add_argument(
        "--no-history",
        action="store_true", default=False,
        help="Disable session tracking for this query (one-shot / privacy mode).",
    )

    # sessions — list recent conversations
    p_sess = sub.add_parser("sessions", help="List recent conversation sessions")
    p_sess.add_argument("--limit", type=int, default=20, help="Max sessions to show (default: 20)")

    # watch — standalone watcher management (--status, --ensure-running)
    p_watch_cmd = sub.add_parser("watch", help="Manage the background file-watcher daemon")
    p_watch_cmd.add_argument(
        "--status",
        action="store_true",
        default=False,
        help="Print daemon status: PID, heartbeat age, last reindex.",
    )
    p_watch_cmd.add_argument(
        "--ensure-running",
        action="store_true",
        default=False,
        help="Start the watcher if it is not running or its heartbeat is stale (> 60s).",
    )
    p_watch_cmd.add_argument(
        "--path",
        default=".",
        metavar="DIR",
        help="Repo root to watch (default: current dir).",
    )

    # verify-index — check index integrity against manifest
    sub.add_parser(
        "verify-index",
        help="Verify that the AST index is fresh and untampered (checks manifest.json)",
    )

    # coverage — show per-directory symbol counts
    sub.add_parser(
        "coverage",
        help="Show per-directory symbol counts; warn on unindexed Python packages",
    )

    # summarize — generate hierarchical architectural summaries (Level 1-3)
    sub.add_parser(
        "summarize",
        help="Generate hierarchical architectural summaries (Level 1-3) via LLM",
    )

    # doctor — environment health check
    p_doctor = sub.add_parser("doctor", help="Check CogniRepo installation health")
    p_doctor.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Show all checks including optional components.",
    )
    p_doctor.add_argument(
        "--release-check",
        action="store_true",
        default=False,
        help="Also run release-readiness checks (v0.x refs, old tier names in docs).",
    )
    p_doctor.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help="Auto-fix top 2 failure modes: FAISS corruption → rebuild, dimension mismatch → reindex.",
    )

    # prime — session bootstrap command (I2)
    p_prime = sub.add_parser("prime", help="Generate a session brief for agent bootstrap")
    p_prime.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output raw JSON instead of human-readable brief.",
    )

    # status — show live signal weights and cold-start progress (P1-A)
    sub.add_parser("status", help="Show live retrieval signal weights and index health")

    # org — local organization management (cross-repo context)
    p_org = sub.add_parser("org", help="Manage local repository organizations (cross-repo context)")
    org_sub = p_org.add_subparsers(dest="org_command")

    p_org_create = org_sub.add_parser("create", help="Create a new local organization")
    p_org_create.add_argument("name", help="Name of the organization")

    p_org_list = org_sub.add_parser("list", help="List all local organizations and member repos")

    p_org_link = org_sub.add_parser("link", help="Link a repository to an organization")
    p_org_link.add_argument("org_name", help="Organization name")
    p_org_link.add_argument("path", nargs="?", default=".", help="Repo path (default: current)")

    p_org_unlink = org_sub.add_parser("unlink", help="Unlink a repository from an organization")
    p_org_unlink.add_argument("org_name", help="Organization name")
    p_org_unlink.add_argument("path", nargs="?", default=".", help="Repo path (default: current)")

    # org project subcommands
    p_org_proj = org_sub.add_parser("project", help="Manage projects within an organization")
    proj_sub = p_org_proj.add_subparsers(dest="project_command")

    p_proj_create = proj_sub.add_parser("create", help="Create a project in an org")
    p_proj_create.add_argument("org", help="Organization name")
    p_proj_create.add_argument("project", help="Project name")
    p_proj_create.add_argument("--description", default="", help="Project description")

    p_proj_list = proj_sub.add_parser("list", help="List projects in an org")
    p_proj_list.add_argument("org", help="Organization name")

    p_proj_link = proj_sub.add_parser("link", help="Link a repo to a project")
    p_proj_link.add_argument("org", help="Organization name")
    p_proj_link.add_argument("project", help="Project name")
    p_proj_link.add_argument("path", nargs="?", default=".", help="Repo path (default: current)")

    p_proj_unlink = proj_sub.add_parser("unlink", help="Unlink a repo from a project")
    p_proj_unlink.add_argument("org", help="Organization name")
    p_proj_unlink.add_argument("project", help="Project name")
    p_proj_unlink.add_argument("path", nargs="?", default=".", help="Repo path (default: current)")

    # setup-env — interactive API key wizard
    p_setup_env = sub.add_parser(
        "setup-env",
        help="Interactive wizard to set and verify API keys",
    )
    p_setup_env.add_argument(
        "--skip-verify", action="store_true", default=False,
        help="Write keys but skip API verification calls (useful in CI with real keys)",
    )
    p_setup_env.add_argument(
        "--non-interactive", action="store_true", default=False,
        help="Skip wizard entirely (for scripted environments)",
    )

    # metrics — standalone Prometheus metrics HTTP server
    p_metrics = sub.add_parser(
        "metrics",
        help="Serve Prometheus /metrics on a standalone HTTP port (for MCP-only deployments)",
    )
    p_metrics.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_metrics.add_argument("--port", type=int, default=9090, help="Port to listen on (default: 9090)")

    # list — process / daemon management
    p_list = sub.add_parser("list", help="List or inspect running cognirepo daemons")
    p_list.add_argument(
        "-p", "--processes",
        action="store_true",
        default=False,
        help="List all running watcher daemon processes.",
    )
    p_list.add_argument(
        "-n", "--name",
        default=None,
        metavar="PID_OR_NAME",
        help="Select a daemon by PID or name (use with --view or --stop).",
    )
    p_list.add_argument(
        "--view",
        action="store_true",
        default=False,
        help="Interactively tail the log of the daemon selected with -n.",
    )
    p_list.add_argument(
        "--stop",
        action="store_true",
        default=False,
        help="Send SIGTERM to the daemon selected with -n.",
    )

    # install-hooks / uninstall-hooks / update-directives
    sub.add_parser("install-hooks", help="Install git post-commit hook for incremental reindex")
    sub.add_parser("uninstall-hooks", help="Remove cognirepo git hook block from post-commit")
    sub.add_parser(
        "update-directives",
        help="Regenerate CLAUDE.md / GEMINI.md / .cursor/rules from latest templates",
    )

    args = parser.parse_args()

    if getattr(args, "help", False):
        _print_help()
        sys.exit(0)

    if args.command is None:
        if sys.stdin.isatty():
            _print_help()
            sys.exit(0)
        else:
            # piped input: read from stdin and route as a single query
            query = sys.stdin.read().strip()
            if query:
                _direct_ask(query, None, 5, False)
            sys.exit(0)

    # ── non-routable commands ──────────────────────────────────────────────
    if args.command == "setup-env":
        from cli.env_wizard import EnvWizard  # pylint: disable=import-outside-toplevel
        wizard = EnvWizard(
            non_interactive=getattr(args, "non_interactive", False),
        )
        wizard.run(skip_verify=getattr(args, "skip_verify", False))
        sys.exit(0)

    if args.command == "metrics":
        from cli.metrics_server import run_metrics_server  # pylint: disable=import-outside-toplevel
        run_metrics_server(host=args.host, port=args.port)
        sys.exit(0)

    if args.command == "init":
        # interactive=True runs the wizard; --no-index or --non-interactive skips it
        non_interactive = getattr(args, "non_interactive", False)
        interactive = not args.no_index and not non_interactive and sys.stdin.isatty()
        summary, kg, indexer = init_project(
            no_index=args.no_index,
            interactive=interactive,
            non_interactive=non_interactive,
        )
        if kg is not None:
            # prompt to start background watcher (skip in non-interactive mode — default yes)
            _start_daemon = False
            if args.daemon or non_interactive:
                _start_daemon = True
            elif sys.stdin.isatty():
                print(
                    "\nStart background watcher? It monitors file changes and keeps the\n"
                    "index and graph up to date automatically. (Y/n): ",
                    end="", flush=True,
                )
                try:
                    _wa = input().strip().lower()
                    _start_daemon = _wa not in ("n", "no")
                except EOFError:
                    _start_daemon = True

            if _start_daemon:
                _start_watcher(".", kg, indexer, daemon=True)

        # prompt for systemd auto-restart (only on Linux, skip in non-interactive)
        if sys.platform == "linux":
            _systemd = False
            if non_interactive:
                _systemd = False  # don't auto-enable systemd in scripted mode
            elif sys.stdin.isatty():
                print(
                    "\nEnable systemd auto-restart? CogniRepo will restart automatically\n"
                    "if the watcher crashes or the machine reboots. (y/N): ",
                    end="", flush=True,
                )
                try:
                    _sa = input().strip().lower()
                    _systemd = _sa in ("y", "yes")
                except EOFError:
                    _systemd = False

            if _systemd:
                try:
                    from cli.daemon import write_systemd_unit  # pylint: disable=import-outside-toplevel
                    _unit_path = write_systemd_unit(".")
                    print(
                        f"\n[cognirepo] systemd unit written to {_unit_path}\n"
                        f"  To enable:\n"
                        f"    systemctl --user enable {_unit_path}\n"
                        f"    systemctl --user start cognirepo-watcher"
                    )
                except Exception:  # pylint: disable=broad-except
                    pass

        _print_ready_summary(summary)
        # Best-effort: install git hook so future commits trigger incremental reindex
        try:
            _cmd_install_hooks()
        except Exception:  # pylint: disable=broad-except
            pass
        return

    if args.command == "serve":
        from server.mcp_server import run_server  # pylint: disable=import-outside-toplevel
        run_server(project_dir=getattr(args, "project_dir", None))
        return

    if args.command == "index-repo":
        # ── git-aware changed-only reindex ───────────────────────────────────
        if getattr(args, "changed_only", False):
            import subprocess as _sp  # pylint: disable=import-outside-toplevel
            from graph.knowledge_graph import KnowledgeGraph as _KG  # pylint: disable=import-outside-toplevel
            from indexer.ast_indexer import ASTIndexer as _AI       # pylint: disable=import-outside-toplevel
            _supported_exts = {
                ".py", ".js", ".ts", ".tsx", ".jsx", ".java",
                ".cpp", ".c", ".h", ".go", ".rs", ".rb",
            }
            _changed: list[str] = []
            try:
                # staged + unstaged changes relative to HEAD
                _diff = _sp.check_output(
                    ["git", "diff", "--name-only", "HEAD"],
                    stderr=_sp.DEVNULL,
                    text=True,
                ).splitlines()
                # untracked files (new files not yet committed)
                _untracked = _sp.check_output(
                    ["git", "ls-files", "--others", "--exclude-standard"],
                    stderr=_sp.DEVNULL,
                    text=True,
                ).splitlines()
                _changed = [
                    f for f in _diff + _untracked
                    if os.path.splitext(f)[1] in _supported_exts and os.path.isfile(f)
                ]
            except (_sp.CalledProcessError, FileNotFoundError):
                print("Warning: git not available — falling back to full reindex.", file=sys.stderr)
            if _changed:
                _kg = _KG()
                _indexer = _AI(graph=_kg)
                _indexed = 0
                for _rel in _changed:
                    _abs = os.path.abspath(_rel)
                    try:
                        _indexer.index_file(_rel, _abs)
                        _indexed += 1
                    except Exception as _exc:  # pylint: disable=broad-except
                        log.debug("index-repo --changed-only: skip %s: %s", _rel, _exc)
                _kg.save()
                print(f"Re-indexed {_indexed} changed file(s): {', '.join(_changed[:5])}"
                      + (" …" if len(_changed) > 5 else ""))
            else:
                print("No changed files detected.")
            return

        # ── selective reindex (--files) ──────────────────────────────────────
        if getattr(args, "files", None):
            from graph.knowledge_graph import KnowledgeGraph as _KG  # pylint: disable=import-outside-toplevel
            from indexer.ast_indexer import ASTIndexer as _AI       # pylint: disable=import-outside-toplevel
            _kg = _KG()
            _indexer = _AI(graph=_kg)
            _indexed = 0
            for _rel in args.files:
                _abs = os.path.abspath(_rel)
                if os.path.isfile(_abs):
                    try:
                        _indexer.index_file(_rel, _abs)
                        _indexed += 1
                    except Exception as _exc:  # pylint: disable=broad-except
                        log.debug("index-repo --files: skip %s: %s", _rel, _exc)
            _kg.save()
            print(f"Re-indexed {_indexed} file(s).")
            return
        # ── full repo walk ────────────────────────────────────────────────────
        try:
            summary, kg, indexer = _direct_index(args.path, embed=not args.no_embed)
        except Exception as exc:  # pylint: disable=broad-except
            log_path = _log_error_to_file(exc, context=f"index-repo {args.path}")
            print(
                f"Error: indexing failed — {exc}\n"
                f"Details logged to {log_path}",
                file=sys.stderr,
            )
            sys.exit(1)
        _print_results(summary)
        _cmd_coverage()
        if not args.no_watch:
            _start_watcher(args.path, kg, indexer, daemon=args.daemon)
        return

    if args.command == "benchmark":
        from tools.benchmark import run_benchmark, print_report, load_last_run  # pylint: disable=import-outside-toplevel
        metrics = run_benchmark()
        if args.json:
            print(json.dumps({k: v for k, v in metrics.items() if k != "_details"}, indent=2))
        else:
            prev = load_last_run() if args.compare else None
            print_report(metrics, compare=prev)
        return

    if args.command == "migrate-config":
        from cli.migrate_config import run_migrate_config  # pylint: disable=import-outside-toplevel
        sys.exit(run_migrate_config(dry_run=getattr(args, "dry_run", False)))

    if args.command == "export-spec":
        from adapters.openai_spec import export  # pylint: disable=import-outside-toplevel
        paths = export()
        # Also write openai_tools.json to stdout so `cognirepo export-spec > /tmp/spec.json` works
        if paths.get("openai_tools"):
            with open(paths["openai_tools"], encoding="utf-8") as _f:
                json.dump(json.load(_f), sys.stdout, indent=2)
            sys.stdout.write("\n")
        return

    if args.command == "prune":
        from cron.prune_memory import prune  # pylint: disable=import-outside-toplevel
        from cron.prune_memory import DEFAULT_THRESHOLD  # pylint: disable=import-outside-toplevel
        threshold = args.threshold if args.threshold is not None else DEFAULT_THRESHOLD
        result = prune(
            threshold=threshold,
            dry_run=args.dry_run,
            archive=args.archive,
            verbose=args.verbose or args.dry_run,
        )
        if args.aggressive and args.threshold is None:
            from cron.prune_memory import AGGRESSIVE_THRESHOLD  # pylint: disable=import-outside-toplevel
            result = prune(threshold=AGGRESSIVE_THRESHOLD, dry_run=args.dry_run,
                           archive=args.archive, verbose=args.verbose or args.dry_run)
        _print_results(result)
        return

    if args.command == "seed":
        from cli.seed import seed_from_git_log  # pylint: disable=import-outside-toplevel
        from_git = getattr(args, "from_git", False)
        seed_comments = getattr(args, "comments", False)
        result = seed_from_git_log(
            repo_root=args.path,
            dry_run=args.dry_run,
            seed_learnings=from_git,
            seed_adrs=from_git,
            seed_comments=seed_comments,
        )
        _print_results(result)
        return

    if args.command == "test-connection":
        _key_env = {
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "grok": "GROK_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        providers_to_test = (
            [args.provider] if args.provider
            else [p for p, env in _key_env.items() if os.environ.get(env)]
        )
        if not providers_to_test:
            print("No API keys found. Set ANTHROPIC_API_KEY, GEMINI_API_KEY, "
                  "GROK_API_KEY, or OPENAI_API_KEY and try again.")
            sys.exit(1)
        exit_code = 0
        for prov in providers_to_test:
            result = _test_connection(prov)
            if result["status"] == "ok":
                print(f"  [{prov}] OK — model={result['model']} response={result['response']!r}")
            else:
                http = result.get("http_status")
                print(f"  [{prov}] FAIL — {result['error']}"
                      + (f" (HTTP {http})" if http else ""))
                exit_code = 1
        sys.exit(exit_code)

    if args.command == "sessions":
        _cmd_sessions(limit=args.limit)
        return

    if args.command == "verify-index":
        sys.exit(_cmd_verify_index())

    if args.command == "summarize":
        from indexer.summarizer import SummarizationEngine
        engine = SummarizationEngine()
        result = engine.run_full_summarization()
        print("\n--- Repository Summary ---")
        print(result["repo"])
        print("\nSummaries saved to .cognirepo/index/summaries.json")
        return

    if args.command == "coverage":
        sys.exit(_cmd_coverage())

    if args.command == "doctor":
        fix_mode = getattr(args, "fix", False)
        if fix_mode:
            sys.exit(_cmd_doctor_fix())
        sys.exit(_cmd_doctor(verbose=args.verbose, release_check=getattr(args, "release_check", False)))

    if args.command == "prime":
        _cmd_prime(as_json=getattr(args, "json", False))
        return

    if args.command == "status":
        _cmd_status()
        return

    if args.command == "org":
        from config.orgs import (  # pylint: disable=import-outside-toplevel
            create_org, list_orgs, link_repo_to_org, unlink_repo_from_org,
            create_project, list_projects, link_repo_to_project, unlink_repo_from_project,
        )
        if args.org_command == "create":
            if create_org(args.name):
                print(f"Created organization: {args.name}")
            else:
                print(f"Organization '{args.name}' already exists.")
        elif args.org_command == "list":
            orgs = list_orgs()
            if not orgs:
                print("No organizations found. Create one with: cognirepo org create <name>")
            else:
                print("Local Organizations:")
                for name, data in orgs.items():
                    print(f"  {name}:")
                    for repo in data.get("repos", []):
                        print(f"    - {repo} (org-level)")
                    for proj_name, proj in data.get("projects", {}).items():
                        desc = f"  [{proj.get('description', '')}]" if proj.get("description") else ""
                        print(f"    project: {proj_name}{desc}")
                        for repo in proj.get("repos", []):
                            print(f"      - {repo}")
        elif args.org_command == "link":
            if link_repo_to_org(args.path, args.org_name):
                print(f"Linked {os.path.abspath(args.path)} to org '{args.org_name}'")
            else:
                print(f"Org '{args.org_name}' not found.")
        elif args.org_command == "unlink":
            if unlink_repo_from_org(args.path, args.org_name):
                print(f"Unlinked {os.path.abspath(args.path)} from org '{args.org_name}'")
            else:
                print(f"Failed to unlink. Org '{args.org_name}' or repo path not found.")
        elif args.org_command == "project":
            if args.project_command == "create":
                if create_project(args.org, args.project, args.description):
                    print(f"Created project '{args.project}' in org '{args.org}'")
                else:
                    print(f"Project '{args.project}' already exists in org '{args.org}'.")
            elif args.project_command == "list":
                projects = list_projects(args.org)
                if not projects:
                    print(f"No projects in org '{args.org}'.")
                else:
                    print(f"Projects in '{args.org}':")
                    for pname, pdata in projects.items():
                        desc = pdata.get("description", "")
                        print(f"  {pname}" + (f"  — {desc}" if desc else ""))
                        for repo in pdata.get("repos", []):
                            print(f"    - {repo}")
            elif args.project_command == "link":
                if link_repo_to_project(args.path, args.org, args.project):
                    print(f"Linked {os.path.abspath(args.path)} to project '{args.org}/{args.project}'")
                else:
                    print(f"Project '{args.project}' not found in org '{args.org}'.")
            elif args.project_command == "unlink":
                if unlink_repo_from_project(args.path, args.org, args.project):
                    print(f"Unlinked {os.path.abspath(args.path)} from '{args.org}/{args.project}'")
                else:
                    print(f"Repo not linked to '{args.org}/{args.project}'.")
            else:
                print("Usage: cognirepo org project <create|list|link|unlink> ...")
        return

    if args.command == "watch":
        if sys.platform not in ("linux", "linux2"):
            print(
                "ERROR: The CogniRepo background daemon currently supports Linux only.\n"
                "On macOS/Windows, run 'cognirepo serve' for foreground MCP server mode,\n"
                "or use 'cognirepo index-repo --no-watch' to index without a watcher.",
                file=sys.stderr,
            )
            sys.exit(2)
        from cli.daemon import (  # pylint: disable=import-outside-toplevel
            heartbeat_age_seconds,
            read_heartbeat,
            is_watcher_running_for_path,
        )
        abs_watch_path = os.path.abspath(args.path)

        if args.status:
            hb = read_heartbeat()
            running = is_watcher_running_for_path(abs_watch_path)
            if running:
                print(f"  Daemon     : running (PID {running['pid']}, name: {running['name']})")
                print(f"  Started    : {running.get('started', 'unknown')}")
            else:
                print("  Daemon     : not running")
            age = heartbeat_age_seconds()
            if age is None:
                print("  Heartbeat  : no heartbeat file")
            elif age < 60:
                print(f"  Heartbeat  : OK ({age:.0f}s ago)")
            else:
                print(f"  Heartbeat  : STALE ({age:.0f}s ago — daemon may be stuck)")
            if hb:
                print(f"  Watch path : {hb.get('path', '?')}")
            return

        if args.ensure_running:
            age = heartbeat_age_seconds()
            running = is_watcher_running_for_path(abs_watch_path)
            if running and (age is None or age < 60):
                print(f"[cognirepo] Watcher already running (PID {running['pid']}).")
                return
            print("[cognirepo] Starting watcher (--ensure-running)...")
            from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
            from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
            kg = KnowledgeGraph()
            indexer = ASTIndexer(graph=kg)
            indexer.load()
            _start_watcher(abs_watch_path, kg, indexer, daemon=True)
            return

        print("Use --status or --ensure-running. See: cognirepo watch --help")
        return

    if args.command == "install-hooks":
        sys.exit(_cmd_install_hooks())

    if args.command == "uninstall-hooks":
        sys.exit(_cmd_uninstall_hooks())

    if args.command == "update-directives":
        sys.exit(_cmd_update_directives())

    if args.command == "list":
        from cli.daemon import print_watcher_list, view_watcher_logs, stop_watcher  # pylint: disable=import-outside-toplevel
        if args.view or args.stop:
            if not args.name:
                print("--view and --stop require -n <PID_OR_NAME>.", file=sys.stderr)
                sys.exit(1)
            if args.view:
                view_watcher_logs(args.name)
            elif args.stop:
                ok = stop_watcher(args.name)
                if ok:
                    print(f"[cognirepo] Sent SIGTERM to watcher '{args.name}'.")
                else:
                    print(f"[cognirepo] No running watcher found matching '{args.name}'.",
                          file=sys.stderr)
                    sys.exit(1)
        else:
            # Default: -p or bare `cognirepo list` both show process table
            print_watcher_list()
        return

    if args.command == "ask":
        text = _direct_ask(
            args.query, args.model, args.top_k, args.verbose,
            no_stream=args.no_stream,
            continue_session=args.continue_session,
            session_id=args.session,
            no_history=args.no_history,
        )
        if args.no_stream:
            print(text)
        return

    # ── routable commands ─────────────────────────────────────────────────
    if True:
        if args.command == "store-memory":
            _print_results(_direct_store(args.text, args.source, getattr(args, "global_scope", False)))

        elif args.command == "retrieve-memory":
            results = _direct_retrieve(args.query, args.top_k, getattr(args, "global_scope", False))
            _print_results(results)
            if not results:
                _maybe_tip_index_repo()

        elif args.command == "user-prefs":
            from memory.user_memory import (  # pylint: disable=import-outside-toplevel
                set_preference, list_preferences, get_behaviour_summary,
            )
            if args.set:
                key, value = args.set
                set_preference(key, value)
                print(f"Set {key} = {value!r}  (stored in ~/.cognirepo/user/behaviour.json)")
            elif args.behaviour:
                summary = get_behaviour_summary()
                if not summary:
                    print("No behaviour patterns recorded yet.")
                else:
                    print("User behaviour patterns (global):")
                    for action, info in sorted(summary.items()):
                        print(f"  {action:<25} count={info['count']}  last={info.get('last_seen','?')[:10]}")
            else:
                prefs = list_preferences()
                if not prefs:
                    print("No preferences set. Use: cognirepo user-prefs --set <key> <value>")
                else:
                    print("User preferences (global ~/.cognirepo/):")
                    for k, v in prefs.items():
                        if not k.startswith("memory:"):
                            print(f"  {k}: {v}")

        elif args.command == "search-docs":
            results = _direct_search(args.query)
            if results:
                _print_search_results(results)
            else:
                print(f"No docs found matching: {args.query!r}")
                _maybe_tip_index_repo()

        elif args.command == "log-episode":
            try:
                meta = json.loads(args.meta)
            except json.JSONDecodeError as exc:
                print(f"--meta must be valid JSON: {exc}", file=sys.stderr)
                sys.exit(1)
            _print_results(_direct_log(args.event, meta))

        elif args.command == "history":
            _print_results(_direct_history(args.limit))


if __name__ == "__main__":
    main()
