# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Model Router — the top-level orchestration entry point.

NOTE: `cognirepo ask` uses this module only for the classifier and
try_local_resolve() — both are zero-API. The model dispatch path (STANDARD+
tier) requires the [providers] extra and an API key. MCP tools never touch
this module.
Install providers: pip install 'cognirepo[providers]'

route(query) pipeline
─────────────────────
1. Classify query          → tier (FAST/BALANCED/DEEP), model ID, provider
2. Build context bundle    → memories + graph + episodic + AST hits + manifest
3. Dispatch to adapter     → anthropic | gemini | openai
4. Post-process            → log episode, update behaviour graph

Usage
-----
    from orchestrator.router import route
    resp = route("why is verify_token slow?")
    print(resp.text)
"""
from __future__ import annotations

import json
import logging
import os
import traceback
from dataclasses import dataclass
from typing import Generator

from orchestrator.classifier import ClassifierResult, classify, DEFAULT_MODELS_BY_PROVIDER
from orchestrator.context_builder import ContextBundle, build as build_context
from orchestrator.model_adapters.anthropic_adapter import ModelResponse
from orchestrator.model_adapters.errors import ModelCallError

logger = logging.getLogger(__name__)

from config.paths import get_path

def _config_file() -> str:
    return get_path("config.json")

def _error_log_dir() -> str:
    return get_path("errors")


def _write_error_log(error_msg: str, query: str = "") -> str:
    """
    Append a timestamped error entry to ``.cognirepo/errors/<date>.log``.
    Returns the log file path (for display to the user).
    Never raises.
    """
    import datetime  # pylint: disable=import-outside-toplevel
    try:
        os.makedirs(_error_log_dir(), exist_ok=True)
        date_str = datetime.date.today().isoformat()
        log_path = os.path.join(_error_log_dir(), f"{date_str}.log")
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"\n[{ts}]")
            if query:
                fh.write(f" query={query[:80]!r}")
            fh.write(f"\n{error_msg}\n{'─' * 60}\n")
        return log_path
    except Exception:  # pylint: disable=broad-except
        return _error_log_dir()


def _tier_retrieval_params(tier: str, caller_top_k: int, caller_episodes: int) -> tuple[int, int]:
    """
    Return (top_k, episode_limit) for the given tier.
    Overrides caller-supplied values to match the tier's retrieval depth:

      QUICK:    semantic_search_code only — skip graph, no episodes
      STANDARD: semantic + learnings — light episodes
      COMPLEX:  full hybrid + learnings — moderate episodes
      EXPERT:   full hybrid + graph + session prime — maximum depth
    """
    TIER_PARAMS = {
        "QUICK":    (3,  0),
        "STANDARD": (5,  3),
        "COMPLEX":  (10, 5),
        "EXPERT":   (20, 10),
    }
    defaults = TIER_PARAMS.get(tier, (caller_top_k, caller_episodes))
    # If the caller explicitly passed higher values, respect them
    return (max(defaults[0], caller_top_k), max(defaults[1], caller_episodes))


def _load_config() -> dict:
    try:
        with open(_config_file(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


# ── public dataclass ──────────────────────────────────────────────────────────

@dataclass
class RouteResult:
    """Container for the primary model response and all orchestration metadata."""
    response: ModelResponse
    classifier: ClassifierResult
    bundle: ContextBundle
    error: str = ""


# ── main entry point ──────────────────────────────────────────────────────────

def route(
    query: str,
    context: dict | None = None,
    force_model: str | None = None,
    top_k: int = 5,
    episode_limit: int = 10,
    max_tokens: int = 2048,
    messages_history: list[dict] | None = None,
) -> RouteResult:
    """
    Classify, hydrate context, (optionally) run sub-queries, dispatch, post-process.

    Parameters
    ----------
    query         : raw user query
    context       : optional hints for classifier (e.g. has_episodic_ref)
    force_model   : override resolved model ID (tier still computed normally)
    top_k         : memories to retrieve for context
    episode_limit : recent episodes to include in context
    max_tokens    : max response tokens
    """
    # ── 1. classify ──────────────────────────────────────────────────────────
    clf = classify(query, context=context, force_model=force_model)
    logger.info(
        "route.classify",
        extra={"tier": clf.tier, "model": clf.model, "provider": clf.provider, "score": clf.score},
    )

    # ── 1.5 local resolver (QUICK/FAST, no force_model) ─────────────────────
    if clf.tier in ("QUICK", "STANDARD") and not force_model:
        _fast_bundle = build_context(query, top_k=0, episode_limit=0, tier="STANDARD")
        local_answer = try_local_resolve(query, _fast_bundle)
        if local_answer is not None:
            local_clf = ClassifierResult(
                tier="STANDARD", score=clf.score, model="local",
                provider="local", signals=clf.signals, overrides=clf.overrides,
            )
            local_resp = ModelResponse(text=local_answer, model="local", provider="local")
            return RouteResult(
                response=local_resp, classifier=local_clf, bundle=_fast_bundle,
            )

    # ── 2. build context (tier controls token budget AND retrieval depth) ──────
    # Tier-aware retrieval depth: QUICK uses fast-path only, EXPERT uses full stack
    tier_top_k, tier_episodes = _tier_retrieval_params(clf.tier, top_k, episode_limit)
    bundle = build_context(query, top_k=tier_top_k, episode_limit=tier_episodes, tier=clf.tier)

    # ── 3. inject relevant past learnings (corrections/prod_issues) ─────────
    try:
        from memory.learning_store import get_learning_store  # pylint: disable=import-outside-toplevel
        learnings = get_learning_store().retrieve_learnings(
            query, top_k=3, types=["correction", "prod_issue"],
        )
        if learnings:
            _MAX_LEARNING_CHARS = 1800  # stay under ~500 tokens
            learning_lines = []
            chars = 0
            for lr in learnings:
                line = f"- [{lr.get('type','learning')}] {lr.get('text','')[:200]}"
                if chars + len(line) > _MAX_LEARNING_CHARS:
                    break
                learning_lines.append(line)
                chars += len(line)
            if learning_lines:
                bundle.system_prompt += (
                    "\n\n## Relevant past learnings from prior sessions\n"
                    + "\n".join(learning_lines)
                )
                logger.debug("route.learnings_injected", extra={"count": len(learning_lines)})
    except Exception:  # pylint: disable=broad-except
        pass  # never let learning injection break routing

    # ── 4. dispatch to adapter (with provider fallback chain) ────────────────
    logger.info(
        "route.dispatch",
        extra={"tier": clf.tier, "model": clf.model, "provider": clf.provider},
    )
    try:
        response = _dispatch_with_fallback(
            query=query,
            primary_provider=clf.provider,
            primary_model=clf.model,
            system_prompt=bundle.system_prompt,
            tool_manifest=bundle.tool_manifest,
            max_tokens=max_tokens,
            messages_history=messages_history,
        )
    except ModelCallError as exc:
        error_msg = f"ModelCallError [{clf.provider}/{clf.model}]: {exc.message}"
        log_path = _write_error_log(error_msg, query=query)
        response = ModelResponse(
            text=(
                f"[!] API error with {clf.provider}. "
                f"Details logged to {log_path}\n{exc.message}"
            ),
            model=clf.model,
            provider=clf.provider,
        )
        return RouteResult(
            response=response, classifier=clf, bundle=bundle,
            error=error_msg,
        )
    except Exception as exc:  # pylint: disable=broad-except
        full_tb = traceback.format_exc()
        error_msg = f"[{clf.provider}/{clf.model}] {exc}\n{full_tb}"
        log_path = _write_error_log(error_msg, query=query)
        response = ModelResponse(
            text=(
                f"[!] Unexpected error. "
                f"Details logged to {log_path}"
            ),
            model=clf.model,
            provider=clf.provider,
        )
        return RouteResult(
            response=response, classifier=clf, bundle=bundle,
            error=error_msg,
        )

    # ── 5. post-process ───────────────────────────────────────────────────────
    _post_process(query=query, clf=clf, bundle=bundle, response=response)

    return RouteResult(
        response=response, classifier=clf, bundle=bundle,
    )


# ── provider availability + fallback chain ────────────────────────────────────

#: Priority order for provider fallback (most capable first)
_PROVIDER_PRIORITY = ["anthropic", "gemini", "grok", "openai"]

#: Default model IDs per provider — sourced from orchestrator/classifier.py (single source of truth)
_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    **DEFAULT_MODELS_BY_PROVIDER,
    "grok": "grok-beta",  # grok not in base classifier; extend here
}


def _available_providers() -> list[str]:
    """Return providers that have a valid API key configured, in priority order."""
    available = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        available.append("anthropic")
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        available.append("gemini")
    if os.environ.get("GROK_API_KEY"):
        available.append("grok")
    if os.environ.get("OPENAI_API_KEY"):
        available.append("openai")
    return available


def _dispatch_with_fallback(
    query: str,
    primary_provider: str,
    primary_model: str,
    system_prompt: str,
    tool_manifest: list[dict],
    max_tokens: int,
    messages_history: list[dict] | None = None,
) -> ModelResponse:
    """
    Try the primary provider first, then fall back through available providers.

    Raises :class:`ModelCallError` only after all providers have been exhausted.
    """
    available = _available_providers()

    # Build ordered provider list: primary first, then remaining available providers
    ordered: list[str] = []
    if primary_provider in available:
        ordered.append(primary_provider)
    for p in _PROVIDER_PRIORITY:
        if p in available and p not in ordered:
            ordered.append(p)

    if not ordered:
        # No keys configured — try the primary anyway (let it fail with a clear error)
        ordered = [primary_provider]

    last_exc: Exception | None = None
    for i, provider in enumerate(ordered):
        model_id = (
            primary_model if provider == primary_provider
            else _PROVIDER_DEFAULT_MODELS.get(provider, primary_model)
        )
        is_fallback = i > 0
        if is_fallback:
            logger.debug("Falling back from %s to %s/%s", ordered[i - 1], provider, model_id)
        try:
            return _call_adapter(
                query=query, provider=provider, model_id=model_id,
                system_prompt=system_prompt, tool_manifest=tool_manifest,
                max_tokens=max_tokens, messages_history=messages_history,
            )
        except ModelCallError as exc:
            last_exc = exc
            if exc.status_code in ModelCallError.NON_RETRYABLE_CODES or i == len(ordered) - 1:
                raise
            continue

    raise last_exc  # type: ignore[misc]


def _promote_to_standard(
    query: str,
    system_prompt: str,
    tool_manifest: list[dict],
    max_tokens: int,
    messages_history: list[dict] | None = None,
) -> "ModelResponse | None":
    """
    When the local adapter has no answer, promote the query to STANDARD tier
    by re-classifying and dispatching to the best available provider.
    Returns None if no provider is available.
    """
    available = _available_providers()
    if not available:
        return None
    provider = available[0]
    model_id = _PROVIDER_DEFAULT_MODELS.get(provider, "claude-haiku-4-5")
    try:
        return _call_adapter(
            query=query, provider=provider, model_id=model_id,
            system_prompt=system_prompt, tool_manifest=tool_manifest,
            max_tokens=max_tokens, messages_history=messages_history,
        )
    except Exception:  # pylint: disable=broad-except
        return None


def _call_adapter(
    query: str,
    provider: str,
    model_id: str,
    system_prompt: str,
    tool_manifest: list[dict],
    max_tokens: int,
    messages_history: list[dict] | None = None,
) -> ModelResponse:
    """Dispatch to the correct adapter module."""
    kwargs = {
        "query": query,
        "system_prompt": system_prompt,
        "tool_manifest": tool_manifest,
        "model_id": model_id,
        "max_tokens": max_tokens,
        "messages_history": messages_history,
    }
    if provider == "local":
        from orchestrator.model_adapters import local_adapter  # pylint: disable=import-outside-toplevel
        from orchestrator.model_adapters.local_adapter import NoLocalAnswer  # pylint: disable=import-outside-toplevel
        try:
            return local_adapter.call(**kwargs)
        except NoLocalAnswer:
            # Promote to STANDARD — pick the first available non-local provider
            logger.info("local_adapter: no answer, promoting to STANDARD")
            _promoted = _promote_to_standard(
                query=query,
                system_prompt=system_prompt,
                tool_manifest=tool_manifest,
                max_tokens=max_tokens,
                messages_history=messages_history,
            )
            if _promoted is not None:
                return _promoted
            raise  # re-raise if no providers available
    if provider == "anthropic":
        from orchestrator.model_adapters import anthropic_adapter  # pylint: disable=import-outside-toplevel
        return anthropic_adapter.call(**kwargs)
    if provider == "gemini":
        from orchestrator.model_adapters import gemini_adapter  # pylint: disable=import-outside-toplevel
        return gemini_adapter.call(**kwargs)
    if provider == "grok":
        from orchestrator.model_adapters import grok_adapter  # pylint: disable=import-outside-toplevel
        return grok_adapter.call(**kwargs)
    if provider in ("openai", "azure", "ollama", "lmstudio"):
        from orchestrator.model_adapters import openai_adapter  # pylint: disable=import-outside-toplevel
        return openai_adapter.call(**kwargs)
    raise ValueError(f"Unknown provider: {provider!r}")


# ── local resolver (FAST queries only) ───────────────────────────────────────

def try_local_resolve(query: str, context_bundle) -> str | None:
    """
    Attempt to answer a FAST-tier query directly from the local index,
    with no model API call.

    Returns a string answer if the query matches a known pattern and the
    index has data.  Returns None to signal fall-through to a model call.

    Patterns handled
    ----------------
    - CogniRepo usage questions    → docs FAISS index (Tier-1, score ≥ 0.6)
    - "where is <symbol>"         → reverse-index lookup
    - "who calls <function>"      → call-graph predecessors in knowledge graph
    - "list files" / "what files" → AST index file list
    - "graph stats" / "how many nodes" → graph node/edge count
    - "recent history" / "what did I do" → last 5 episodic events
    """
    import re  # pylint: disable=import-outside-toplevel

    # ── Tier-1: embedded docs index (CogniRepo usage questions) ─────────────
    try:
        from cli.docs_index import ensure_docs_index, _CONFIDENCE_THRESHOLD  # pylint: disable=import-outside-toplevel
        _docs_idx = ensure_docs_index()
        if _docs_idx is not None and _docs_idx.is_docs_query(query):
            results = _docs_idx.answer(query, top_k=3)
            if results and results[0]["score"] >= _CONFIDENCE_THRESHOLD:
                top = results[0]
                answer = top["text"]
                footer = f"\n\n→ see: {top['file']} § {top['section']}"
                return answer + footer
    except Exception:  # pylint: disable=broad-except
        pass  # never break routing on docs-index errors

    q = query.strip().lower()

    # "where is <symbol>" / "where can i find <symbol>"
    m = re.match(r"where (?:is|can i find)\s+(.+?)[\?\.]*$", q)
    if m:
        return _lookup_symbol(m.group(1).strip(), context_bundle)

    # "who calls <function>"
    m = re.match(r"who calls?\s+(.+?)[\?\.]*$", q)
    if m:
        return _who_calls(m.group(1).strip(), context_bundle)

    # "list files" / "what files" / "show files"
    if re.search(r"\b(list files?|what files?|show files?)\b", q):
        return _list_files()

    # "graph stats" / "how many nodes" / "graph size"
    if re.search(r"\b(graph stats?|how many nodes?|graph size)\b", q):
        return _graph_stats()

    # "recent history" / "what did i do" / "show history"
    if re.search(r"\b(recent history|what did i do|show history)\b", q):
        return _recent_history()

    return None


def _lookup_symbol(symbol: str, _bundle) -> str | None:
    """Reverse-index lookup for a symbol name."""
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel

        if not os.path.exists(".cognirepo/index/ast_index.json"):
            return None

        kg = KnowledgeGraph()
        indexer = ASTIndexer(graph=kg)
        indexer.load()
        hits = indexer.lookup_symbol(symbol)

        if not hits:
            # case-insensitive fallback
            lower_s = symbol.lower()
            for key in indexer.index_data.get("reverse_index", {}):
                if key.lower() == lower_s:
                    hits = indexer.lookup_symbol(key)
                    symbol = key
                    break

        if hits:
            lines = [f"`{symbol}` found at:"]
            for h in hits:
                lines.append(f"  {h['file']}:{h['line']}")
            return "\n".join(lines)
        return f"`{symbol}` not found in index."
    except Exception:  # pylint: disable=broad-except
        return None


def _who_calls(func_name: str, _bundle) -> str | None:
    """Return callers of a function from the call graph."""
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel

        if not os.path.exists(".cognirepo/graph/graph.pkl"):
            return None

        kg = KnowledgeGraph()
        graph = kg.G
        target = f"symbol::{func_name}"

        if not graph.has_node(target):
            lower_f = func_name.lower()
            for n in graph.nodes():
                if n.startswith("symbol::") and n[8:].lower() == lower_f:
                    target = n
                    func_name = n[8:]
                    break
            else:
                return f"No call graph data for `{func_name}`."

        callers = list(graph.predecessors(target))
        if not callers:
            return f"No recorded callers for `{func_name}`."
        lines = [f"Callers of `{func_name}`:"]
        for c in callers[:10]:
            display = c.replace("symbol::", "").replace("function::", "")
            lines.append(f"  • {display}")
        return "\n".join(lines)
    except Exception:  # pylint: disable=broad-except
        return None


def _list_files() -> str | None:
    """Return indexed file list from the AST index."""
    try:
        if not os.path.exists(".cognirepo/index/ast_index.json"):
            return None

        with open(".cognirepo/index/ast_index.json", encoding="utf-8") as f:
            data = json.load(f)
        files = sorted(data.get("files", {}).keys())
        if not files:
            return "No files indexed. Run `cognirepo index-repo .` first."
        lines = [f"Indexed files ({len(files)}):"]
        for fp in files:
            lines.append(f"  {fp}")
        return "\n".join(lines)
    except Exception:  # pylint: disable=broad-except
        return None


def _graph_stats() -> str | None:
    """Return a one-line summary of the knowledge graph."""
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        graph = kg.G
        return f"Knowledge graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges."
    except Exception:  # pylint: disable=broad-except
        return None


def _recent_history() -> str | None:
    """Return last 5 episodic events."""
    try:
        from memory.episodic_memory import get_history  # pylint: disable=import-outside-toplevel
        events = get_history(5)
        if not events:
            return "No episodic history found."
        lines = ["Recent history (last 5 events):"]
        for ev in events:
            t = ev.get("time", "?")
            e = ev.get("event", "")
            lines.append(f"  [{t}] {e}")
        return "\n".join(lines)
    except Exception:  # pylint: disable=broad-except
        return None


# ── streaming route ───────────────────────────────────────────────────────────

def stream_route(
    query: str,
    context: dict | None = None,
    force_model: str | None = None,
    top_k: int = 5,
    episode_limit: int = 10,
    max_tokens: int = 2048,
    messages_history: list[dict] | None = None,
) -> Generator[str, None, None]:
    """
    Streaming version of :func:`route`.  Yields text chunks as they arrive
    from the model, then logs the episodic event after the stream completes.

    Usage
    -----
    ::

        for chunk in stream_route("why is verify_token slow?"):
            print(chunk, end="", flush=True)

    Ctrl+C raises ``KeyboardInterrupt`` in the caller — the generator is
    closed cleanly by Python's GC.

    Parameters
    ----------
    Same as :func:`route` except ``stream`` is always True.
    """
    clf = classify(query, context=context, force_model=force_model)

    # local resolver (QUICK/FAST, no force_model) — yield answer directly
    if clf.tier in ("QUICK", "STANDARD") and not force_model:
        _fast_bundle = build_context(query, top_k=0, episode_limit=0, tier="STANDARD")
        local_answer = try_local_resolve(query, _fast_bundle)
        if local_answer is not None:
            yield local_answer
            return

    tier_top_k, tier_episodes = _tier_retrieval_params(clf.tier, top_k, episode_limit)
    bundle = build_context(query, top_k=tier_top_k, episode_limit=tier_episodes, tier=clf.tier)

    full_text: list[str] = []
    usage: dict = {}

    gen = _stream_dispatch(
        query=query,
        provider=clf.provider,
        model_id=clf.model,
        system_prompt=bundle.system_prompt,
        tool_manifest=bundle.tool_manifest,
        max_tokens=max_tokens,
        messages_history=messages_history,
    )

    try:
        while True:
            try:
                chunk = next(gen)
            except StopIteration as exc:
                usage = exc.value or {}
                break
            full_text.append(chunk)
            yield chunk
    except GeneratorExit:
        gen.close()
        return
    except Exception:  # pylint: disable=broad-except
        gen.close()
        raise

    # Post-process after stream completes (runs before caller's StopIteration)
    response = ModelResponse(
        text="".join(full_text),
        model=clf.model,
        provider=clf.provider,
        usage=usage,
    )
    _post_process(query=query, clf=clf, bundle=bundle, response=response)


def _stream_dispatch(
    query: str,
    provider: str,
    model_id: str,
    system_prompt: str,
    tool_manifest: list[dict],
    max_tokens: int,
    messages_history: list[dict] | None = None,
) -> Generator[str, None, dict]:
    """Route to the correct adapter in streaming mode."""
    kwargs = {
        "query": query,
        "system_prompt": system_prompt,
        "tool_manifest": tool_manifest,
        "model_id": model_id,
        "max_tokens": max_tokens,
        "stream": True,
        "messages_history": messages_history,
    }
    if provider == "local":
        from orchestrator.model_adapters import local_adapter  # pylint: disable=import-outside-toplevel
        from orchestrator.model_adapters.local_adapter import NoLocalAnswer  # pylint: disable=import-outside-toplevel
        try:
            return (yield from local_adapter.call(**kwargs))
        except NoLocalAnswer:
            # Promote to STANDARD — fall back to first available provider
            logger.info("local_adapter (stream): no answer, promoting to STANDARD")
            available = _available_providers()
            if available:
                promoted_provider = available[0]
                promoted_model = _PROVIDER_DEFAULT_MODELS.get(promoted_provider, "claude-haiku-4-5")
                kwargs["model_id"] = promoted_model
                del kwargs["stream"]
                kwargs["stream"] = True
                # Recurse once with a real provider
                return (yield from _stream_dispatch(
                    query=query, provider=promoted_provider,
                    model_id=promoted_model, system_prompt=system_prompt,
                    tool_manifest=tool_manifest, max_tokens=max_tokens,
                    messages_history=messages_history,
                ))
            return {}
    if provider == "anthropic":
        from orchestrator.model_adapters import anthropic_adapter  # pylint: disable=import-outside-toplevel
        return (yield from anthropic_adapter.call(**kwargs))
    if provider == "gemini":
        from orchestrator.model_adapters import gemini_adapter  # pylint: disable=import-outside-toplevel
        return (yield from gemini_adapter.call(**kwargs))
    if provider == "grok":
        from orchestrator.model_adapters import grok_adapter  # pylint: disable=import-outside-toplevel
        return (yield from grok_adapter.call(**kwargs))
    if provider in ("openai", "azure", "ollama", "lmstudio"):
        from orchestrator.model_adapters import openai_adapter  # pylint: disable=import-outside-toplevel
        return (yield from openai_adapter.call(**kwargs))
    raise ValueError(f"Unknown provider: {provider!r}")


# ── post-process ──────────────────────────────────────────────────────────────

def _post_process(
    query: str,
    clf: ClassifierResult,
    bundle: ContextBundle,
    response: ModelResponse,
) -> None:
    """Log episodic event and update behaviour graph after a successful route."""
    try:
        from memory.episodic_memory import log_event  # pylint: disable=import-outside-toplevel
        log_event(
            event=f"ask: {query[:120]}",
            metadata={
                "tier": clf.tier,
                "model": clf.model,
                "provider": clf.provider,
                "score": clf.score,
                "tokens_out": response.usage.get("output_tokens", 0),
            },
        )
    except Exception:  # pylint: disable=broad-except
        pass

    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        from graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
        import uuid  # pylint: disable=import-outside-toplevel

        kg = KnowledgeGraph()
        bt = BehaviourTracker(graph=kg)
        query_id = "q_" + uuid.uuid4().hex[:8]
        retrieved_symbols = [f"{h['file']}::{h['name']}" for h in bundle.ast_hits[:5]]
        bt.record_query(query_id, query, retrieved_symbols)
        bt.save()
    except Exception:  # pylint: disable=broad-except
        pass
