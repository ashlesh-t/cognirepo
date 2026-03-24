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
import sys

from cli.init_project import init_project
from server.mcp_server import run_server


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
    return {"status": "indexed", "path": path, **summary}


def _direct_ask(query, force_model, top_k, verbose):
    from orchestrator.router import route
    result = route(query, force_model=force_model, top_k=top_k)
    if verbose:
        print(f"[tier={result.classifier.tier} score={result.classifier.score} "
              f"model={result.classifier.model} provider={result.classifier.provider}]")
        if result.classifier.signals:
            print(f"[signals={result.classifier.signals}]")
    if result.error:
        print(f"ERROR: {result.error}", file=__import__('sys').stderr)
    if result.response.tool_calls:
        import json
        print("\n[tool calls]")
        for tc in result.response.tool_calls:
            print(" ", json.dumps(tc))
    return result.response.text


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
    p_init.add_argument("--password", default="changeme",
                        help="Initial API password (default: changeme)")
    p_init.add_argument("--port", type=int, default=8000,
                        help="API port to record in config (default: 8000)")

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

    # ask
    p_ask = sub.add_parser("ask", help="Route a query through the multi-model orchestrator")
    p_ask.add_argument("query", help="Natural language query")
    p_ask.add_argument("--model", default=None, metavar="MODEL_ID",
                       help="Force a specific model ID (e.g. claude-opus-4-6)")
    p_ask.add_argument("--top-k", type=int, default=5,
                       help="Memories to retrieve for context (default: 5)")
    p_ask.add_argument("--verbose", action="store_true",
                       help="Print classifier tier/score/signals before response")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # ── non-routable commands ──────────────────────────────────────────────
    if args.command == "init":
        init_project(password=args.password, port=args.port)
        return

    if args.command == "serve":
        run_server()
        return

    if args.command == "index-repo":
        _print_results(_direct_index(args.path))
        return

    if args.command == "ask":
        text = _direct_ask(args.query, args.model, args.top_k, args.verbose)
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
            _print_results(_direct_retrieve(args.query, args.top_k))

        elif args.command == "search-docs":
            _print_results(_direct_search(args.query))

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
