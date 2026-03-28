# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

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
import json
import signal
import sys
import time

from cli.init_project import init_project


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


# ── command implementations (direct) ─────────────────────────────────────────

def _direct_store(text, source):
    from tools.store_memory import store_memory
    return store_memory(text, source)


def _direct_retrieve(query, top_k):
    from tools.retrieve_memory import retrieve_memory
    return retrieve_memory(query, top_k)


def _direct_search(query):
    from retrieval.docs_search import search_docs
    return search_docs(query)


def _cmd_doctor(verbose: bool = False) -> int:
    """
    Run system health checks. Returns exit code 0 (all pass) or 1 (any fail).
    """
    import importlib  # pylint: disable=import-outside-toplevel,redefined-outer-name
    import os  # pylint: disable=import-outside-toplevel,redefined-outer-name

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

    # ── Check 1: config ───────────────────────────────────────────────────────
    nonlocal_config: dict = {}
    try:
        _cfg_path = ".cognirepo/config.json"
        if not os.path.isdir(".cognirepo"):
            raise FileNotFoundError(".cognirepo/ not found")
        if not os.path.exists(_cfg_path):
            raise FileNotFoundError("config.json missing")
        with open(_cfg_path, encoding="utf-8") as _f:
            nonlocal_config = json.load(_f)
        _pname = nonlocal_config.get("project_name", "unknown")
        _ok(f".cognirepo/ — config valid · project: {_pname}")
        if verbose:
            print(f"       {os.path.abspath(_cfg_path)}")
    except Exception as exc:  # pylint: disable=broad-except
        _fail(f".cognirepo/ — {exc}", "Run: cognirepo init")
        issues += 1

    # ── Check 2: FAISS index ──────────────────────────────────────────────────
    try:
        from vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
        _vdb = LocalVectorDB()
        _count = _vdb.index.ntotal
        _ok(f"FAISS index — {_count} memories")
        if verbose:
            _idx_path = os.path.abspath(os.path.join(".cognirepo", "vector_db", "faiss.index"))
            print(f"       {_idx_path}")
    except Exception as exc:  # pylint: disable=broad-except
        _fail(f"FAISS index — {exc}", "Run: cognirepo init")
        issues += 1

    # ── Check 3: Knowledge graph ──────────────────────────────────────────────
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        _kg = KnowledgeGraph()
        _nodes = _kg.G.number_of_nodes()
        _edges = _kg.G.number_of_edges()
        _ok(f"Knowledge graph — {_nodes:,} nodes · {_edges:,} edges")
        if verbose:
            _gpath = os.path.abspath(os.path.join(".cognirepo", "graph", "graph.pkl"))
            print(f"       {_gpath}")
    except Exception as exc:  # pylint: disable=broad-except
        _fail(f"Knowledge graph — {exc}", "Run: cognirepo index-repo .")
        issues += 1

    # ── Check 4: AST index ────────────────────────────────────────────────────
    try:
        from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
        from graph.knowledge_graph import KnowledgeGraph as _KG2  # pylint: disable=import-outside-toplevel
        _idx = ASTIndexer(graph=_KG2())
        _idx.load()
        _files = _idx.index_data.get("files", {})
        _file_count = len(_files)
        _sym_count = sum(len(v.get("symbols", [])) for v in _files.values())
        _ok(f"AST index — {_sym_count} symbols across {_file_count} files")
        if verbose:
            _ipath = os.path.abspath(os.path.join(".cognirepo", "index", "ast_index.json"))
            print(f"       {_ipath}")
    except Exception as exc:  # pylint: disable=broad-except
        _fail(f"AST index — {exc}", "Run: cognirepo index-repo .")
        issues += 1

    # ── Check 5: Episodic log ─────────────────────────────────────────────────
    try:
        from memory.episodic_memory import get_history  # pylint: disable=import-outside-toplevel
        _ep_count = len(get_history(limit=100_000))
        _ok(f"Episodic log — {_ep_count} events")
        if verbose:
            _epath = os.path.abspath(os.path.join(".cognirepo", "episodic", "episodic.json"))
            print(f"       {_epath}")
    except Exception as exc:  # pylint: disable=broad-except
        _fail(f"Episodic log — {exc}", "Run: cognirepo init")
        issues += 1

    # ── Check 6: Language support ─────────────────────────────────────────────
    try:
        from indexer.language_registry import supported_extensions  # pylint: disable=import-outside-toplevel
        _exts = supported_extensions()
        _EXT_NAMES = {
            ".py": "Python", ".js": "JS", ".jsx": "JS",
            ".ts": "TS", ".tsx": "TS", ".java": "Java",
            ".go": "Go", ".rs": "Rust", ".c": "C",
            ".cpp": "C++", ".cc": "C++", ".h": "C/C++",
        }
        _seen: set[str] = set()
        _lang_list: list[str] = []
        for ext in sorted(_exts):
            name = _EXT_NAMES.get(ext, ext)
            if name not in _seen:
                _seen.add(name)
                _lang_list.append(name)
        _ok(f"Language support — {', '.join(_lang_list) if _lang_list else 'Python (built-in)'}")
    except Exception as exc:  # pylint: disable=broad-except
        _ok(f"Language support — Python (built-in) [{exc}]")

    # ── Check 7: API keys ─────────────────────────────────────────────────────
    _PROVIDERS = {
        "ANTHROPIC_API_KEY": "Anthropic",
        "GEMINI_API_KEY": "Gemini",
        "GOOGLE_API_KEY": "Gemini (alt)",
        "OPENAI_API_KEY": "OpenAI",
        "GROK_API_KEY": "Grok",
    }
    _found = [name for var, name in _PROVIDERS.items() if os.environ.get(var)]
    if _found:
        _ok(f"Model API keys — {', '.join(_found)}")
    else:
        _fail(
            "Model API keys — no keys configured",
            "Set at least one: ANTHROPIC_API_KEY · GEMINI_API_KEY · OPENAI_API_KEY · GROK_API_KEY",
        )
        issues += 1

    # ── Check 8: Circuit breaker ──────────────────────────────────────────────
    try:
        from memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
        import psutil  # pylint: disable=import-outside-toplevel
        _cb = get_breaker()
        _rss_mb = psutil.Process().memory_info().rss / 1024 / 1024
        _limit_mb = _cb._rss_limit_mb  # pylint: disable=protected-access
        _ok(f"Circuit breaker — {_cb.state} (RSS: {_rss_mb:.0f} MB / {_limit_mb:.0f} MB limit)")
    except Exception:  # pylint: disable=broad-except
        _ok("Circuit breaker — OK (psutil not available for RSS check)")

    # ── Check 9: BM25 backend (always shown) ──────────────────────────────────
    try:
        from _bm25 import BACKEND  # pylint: disable=import-outside-toplevel
        _ok(f"BM25 backend — {BACKEND}")
    except Exception as exc:  # pylint: disable=broad-except
        _fail(f"BM25 backend — {exc}")
        issues += 1

    # ── Check 10: gRPC (only if multi-agent enabled) ──────────────────────────
    if os.environ.get("COGNIREPO_MULTI_AGENT_ENABLED", "").lower() == "true":
        _grpc_port = int(nonlocal_config.get("multi_agent", {}).get("grpc_port", 50051))
        try:
            import socket  # pylint: disable=import-outside-toplevel
            with socket.create_connection(("localhost", _grpc_port), timeout=1):
                pass
            _ok(f"gRPC server — reachable on port {_grpc_port}")
        except Exception:  # pylint: disable=broad-except
            _fail(
                f"gRPC server — not reachable on port {_grpc_port}",
                f"Run: cognirepo serve-grpc --port {_grpc_port}",
            )
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

    # ── Summary ───────────────────────────────────────────────────────────────
    if issues == 0:
        print("\n  No issues found.")
    else:
        print(f"\n  {issues} issue(s) found.")
    return issues


def _maybe_tip_index_repo() -> None:
    """Print an index-repo tip when the graph is empty (cold-start hint)."""
    try:
        from graph.knowledge_graph import KnowledgeGraph
        if KnowledgeGraph().G.number_of_nodes() == 0:
            print("Tip: run 'cognirepo index-repo .' to enable graph-based retrieval.")
    except Exception:  # pylint: disable=broad-except
        pass


def _direct_log(event, metadata):
    from memory.episodic_memory import log_event
    log_event(event, metadata)
    return {"status": "logged", "event": event}


def _direct_history(limit):
    from memory.episodic_memory import get_history
    return get_history(limit)


def _direct_index(path):
    from graph.knowledge_graph import KnowledgeGraph
    from indexer.ast_indexer import ASTIndexer
    kg = KnowledgeGraph()
    indexer = ASTIndexer(graph=kg)
    summary = indexer.index_repo(path)
    kg.save()
    return {"status": "indexed", "path": path, **summary}, kg, indexer


def _start_watcher(path: str, kg, indexer) -> None:
    """Start the file watcher daemon and block until Ctrl+C."""
    import os
    from graph.behaviour_tracker import BehaviourTracker
    from indexer.file_watcher import create_watcher

    abs_path = os.path.abspath(path)
    session_id = f"watch_{int(time.time())}"
    behaviour = BehaviourTracker(graph=kg)

    observer = create_watcher(abs_path, indexer, kg, behaviour, session_id)
    print(f"Watching {abs_path} for changes. Ctrl+C to stop.")

    def _stop(signum, frame):  # pylint: disable=unused-argument
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        print("[watcher] stopped.")


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
            from orchestrator.model_adapters import openai_adapter  # pylint: disable=import-outside-toplevel
            resp = openai_adapter.call(query, system, manifest, max_tokens=10)
        else:
            return {"status": "error", "provider": provider, "error": f"Unknown provider '{provider}'"}
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
            print(f"[tier={result.classifier.tier} score={result.classifier.score} "
                  f"model={result.classifier.model} provider={result.classifier.provider}]")
            if result.classifier.signals:
                print(f"[signals={result.classifier.signals}]")
            b = result.bundle
            print(f"[context tokens={b.token_count}/{b.max_tokens}"
                  + (" TRIMMED" if b.was_trimmed else "") + "]")
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

def main():
    parser = argparse.ArgumentParser(
        prog="cognirepo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # global flags
    parser.add_argument(
        "--via-api",
        action="store_true",
        default=False,
        help="Route commands through the REST API instead of calling tools directly.",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        metavar="URL",
        help="Override REST API base URL (default: from .cognirepo/config.json or http://localhost:8000).",
    )

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Scaffold .cognirepo/ and config")
    p_init.add_argument("--password", default="changeme",  # nosec B105
                        help="Initial API password (default: changeme)")
    p_init.add_argument("--port", type=int, default=8000,
                        help="API port to record in config (default: 8000)")
    p_init.add_argument(
        "--no-index",
        action="store_true",
        default=False,
        help="Skip the index-repo prompt (useful for scripting).",
    )

    # serve
    sub.add_parser("serve", help="Start the MCP stdio server")

    # store-memory
    p_store = sub.add_parser("store-memory", help="Save a semantic memory")
    p_store.add_argument("text")
    p_store.add_argument("--source", default="", help="Origin label")

    # retrieve-memory
    p_ret = sub.add_parser("retrieve-memory", help="Semantic similarity search")
    p_ret.add_argument("query")
    p_ret.add_argument("--top-k", type=int, default=5)

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
    p_idx.add_argument("path", nargs="?", default=".", help="Repo root to index (default: current dir)")
    p_idx.add_argument(
        "--no-watch",
        action="store_true",
        default=False,
        help="Exit immediately after indexing without starting the file watcher (useful in CI).",
    )

    # serve-api
    p_api = sub.add_parser("serve-api", help="Start the FastAPI REST server")
    p_api.add_argument("--host", default="0.0.0.0")
    p_api.add_argument("--port", type=int, default=8080)
    p_api.add_argument("--reload", action="store_true")

    # serve-grpc
    p_grpc = sub.add_parser("serve-grpc", help="Start the gRPC inter-model server")
    p_grpc.add_argument("--port", type=int, default=50051)

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
    p_seed = sub.add_parser("seed", help="Seed behaviour tracker from recent git log")
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

    # chat — interactive REPL
    sub.add_parser("chat", help="Start interactive REPL (default when no args given)")

    # doctor — environment health check
    p_doctor = sub.add_parser("doctor", help="Check CogniRepo installation health")
    p_doctor.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Show all checks including optional components.",
    )

    args = parser.parse_args()

    if args.command is None:
        if sys.stdin.isatty():
            from cli.repl import run_repl  # pylint: disable=import-outside-toplevel
            run_repl()
            sys.exit(0)
        else:
            # piped input: read from stdin and route as a single query
            query = sys.stdin.read().strip()
            if query:
                _direct_ask(query, None, 5, False)
            sys.exit(0)

    # ── non-routable commands ──────────────────────────────────────────────
    if args.command == "init":
        summary, kg, indexer = init_project(
            password=args.password,
            port=args.port,
            no_index=args.no_index,
        )
        if kg is not None:
            _start_watcher(".", kg, indexer)
        return

    if args.command == "serve":
        from server.mcp_server import run_server  # pylint: disable=import-outside-toplevel
        run_server()
        return

    if args.command == "index-repo":
        summary, kg, indexer = _direct_index(args.path)
        _print_results(summary)
        if not args.no_watch:
            _start_watcher(args.path, kg, indexer)
        return

    if args.command == "serve-api":
        import uvicorn  # pylint: disable=import-outside-toplevel
        uvicorn.run("api.main:app", host=args.host, port=args.port, reload=args.reload)
        return

    if args.command == "serve-grpc":
        from rpc.server import start_server  # pylint: disable=import-outside-toplevel
        start_server(port=args.port, block=True)
        return

    if args.command == "export-spec":
        from adapters.openai_spec import export  # pylint: disable=import-outside-toplevel
        export()
        return

    if args.command == "prune":
        from cron.prune_memory import prune  # pylint: disable=import-outside-toplevel
        result = prune(
            threshold=args.threshold,
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
        result = seed_from_git_log(repo_root=args.path, dry_run=args.dry_run)
        _print_results(result)
        return

    if args.command == "test-connection":
        import os  # pylint: disable=import-outside-toplevel,redefined-outer-name
        _KEY_ENV = {
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "grok": "GROK_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        providers_to_test = (
            [args.provider] if args.provider
            else [p for p, env in _KEY_ENV.items() if os.environ.get(env)]
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

    if args.command == "chat":
        from cli.repl import run_repl  # pylint: disable=import-outside-toplevel
        run_repl()
        return

    if args.command == "doctor":
        sys.exit(_cmd_doctor(verbose=args.verbose))

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

    # ── routable commands: direct vs API ──────────────────────────────────
    if args.via_api:
        from cli.api_client import ApiClient
        client = ApiClient(api_url=args.api_url)

        if args.command == "store-memory":
            result = client.store_memory(args.text, args.source)
            _print_results(result)

        elif args.command == "retrieve-memory":
            _print_results(client.retrieve_memory(args.query, args.top_k))

        elif args.command == "search-docs":
            _print_results(client.search_docs(args.query))

        elif args.command == "log-episode":
            try:
                meta = json.loads(args.meta)
            except json.JSONDecodeError as exc:
                print(f"--meta must be valid JSON: {exc}", file=sys.stderr)
                sys.exit(1)
            _print_results(client.log_episode(args.event, meta))

        elif args.command == "history":
            _print_results(client.get_history(args.limit))

    else:
        if args.command == "store-memory":
            _print_results(_direct_store(args.text, args.source))

        elif args.command == "retrieve-memory":
            results = _direct_retrieve(args.query, args.top_k)
            _print_results(results)
            if not results:
                _maybe_tip_index_repo()

        elif args.command == "search-docs":
            results = _direct_search(args.query)
            _print_results(results)
            if not results:
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
