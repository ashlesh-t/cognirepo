"""
Model Router — the top-level orchestration entry point.

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

import traceback
from dataclasses import dataclass

from orchestrator.classifier import ClassifierResult, classify
from orchestrator.context_builder import ContextBundle, build as build_context
from orchestrator.model_adapters.anthropic_adapter import ModelResponse


# ── public dataclass (re-exports ModelResponse for callers) ──────────────────

@dataclass
class RouteResult:
    response: ModelResponse
    classifier: ClassifierResult
    bundle: ContextBundle
    error: str = ""


# ── main entry point ─────────────────────────────────────────────────────────

def route(
    query: str,
    context: dict | None = None,
    force_model: str | None = None,
    top_k: int = 5,
    episode_limit: int = 10,
    max_tokens: int = 2048,
) -> RouteResult:
    """
    Classify, hydrate context, dispatch to model adapter, post-process.

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

    # ── 2. build context ─────────────────────────────────────────────────────
    bundle = build_context(query, top_k=top_k, episode_limit=episode_limit)

    # ── 3. dispatch to adapter ───────────────────────────────────────────────
    try:
        response = _dispatch(
            query=query,
            provider=clf.provider,
            model_id=clf.model,
            system_prompt=bundle.system_prompt,
            tool_manifest=bundle.tool_manifest,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # pylint: disable=broad-except
        error_msg = f"[{clf.provider}/{clf.model}] {exc}\n{traceback.format_exc()}"
        response = ModelResponse(
            text=f"Error: {exc}",
            model=clf.model,
            provider=clf.provider,
        )
        return RouteResult(response=response, classifier=clf, bundle=bundle, error=error_msg)

    # ── 4. post-process ───────────────────────────────────────────────────────
    _post_process(query=query, clf=clf, bundle=bundle, response=response)

    return RouteResult(response=response, classifier=clf, bundle=bundle)


# ── dispatch ──────────────────────────────────────────────────────────────────

def _dispatch(
    query: str,
    provider: str,
    model_id: str,
    system_prompt: str,
    tool_manifest: list[dict],
    max_tokens: int,
) -> ModelResponse:
    if provider == "anthropic":
        from orchestrator.model_adapters import anthropic_adapter  # pylint: disable=import-outside-toplevel
        return anthropic_adapter.call(
            query=query,
            system_prompt=system_prompt,
            tool_manifest=tool_manifest,
            model_id=model_id,
            max_tokens=max_tokens,
        )
    if provider == "gemini":
        from orchestrator.model_adapters import gemini_adapter  # pylint: disable=import-outside-toplevel
        return gemini_adapter.call(
            query=query,
            system_prompt=system_prompt,
            tool_manifest=tool_manifest,
            model_id=model_id,
            max_tokens=max_tokens,
        )
    if provider in ("openai", "azure", "ollama", "lmstudio"):
        from orchestrator.model_adapters import openai_adapter  # pylint: disable=import-outside-toplevel
        return openai_adapter.call(
            query=query,
            system_prompt=system_prompt,
            tool_manifest=tool_manifest,
            model_id=model_id,
            max_tokens=max_tokens,
        )
    raise ValueError(f"Unknown provider: {provider!r}")


# ── post-process ──────────────────────────────────────────────────────────────

def _post_process(
    query: str,
    clf: ClassifierResult,
    bundle: ContextBundle,
    response: ModelResponse,
) -> None:
    """Log episodic event and update behaviour graph after a successful route."""
    # Log episodic event
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

    # Record query in behaviour tracker
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        from graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
        import uuid  # pylint: disable=import-outside-toplevel

        kg = KnowledgeGraph()
        bt = BehaviourTracker(graph=kg)
        query_id = "q_" + uuid.uuid4().hex[:8]
        retrieved_symbols = [
            f"{h['file']}::{h['name']}" for h in bundle.ast_hits[:5]
        ]
        bt.record_query(query_id, query, retrieved_symbols)
        bt.save()
    except Exception:  # pylint: disable=broad-except
        pass
