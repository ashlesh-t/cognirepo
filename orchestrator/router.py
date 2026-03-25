"""
Model Router — the top-level orchestration entry point.

route(query) pipeline
─────────────────────
1. Classify query          → tier (FAST/BALANCED/DEEP), model ID, provider
2. Build context bundle    → memories + graph + episodic + AST hits + manifest
3. [Optional] Multi-agent  → DEEP queries may spawn gRPC sub-queries (off by default)
4. Dispatch to adapter     → anthropic | gemini | openai
5. Post-process            → log episode, update behaviour graph

Multi-Agent Mode
----------------
Controlled by environment variable (OFF by default):

    COGNIREPO_MULTI_AGENT_ENABLED=true   # enable agent-to-agent delegation

When enabled and tier == DEEP, the router may call rpc.client.sub_query() to
delegate fast sub-lookups to a lighter model before calling the primary model.

Agent topology: 1 orchestrator + N sub-agents (each = one model API call).
Interaction depth: one level (orchestrator → sub-agent, no sub-agent chains).

Usage
-----
    from orchestrator.router import route
    resp = route("why is verify_token slow?")
    print(resp.text)
"""
from __future__ import annotations

import os
import traceback
from dataclasses import dataclass

from orchestrator.classifier import ClassifierResult, classify
from orchestrator.context_builder import ContextBundle, build as build_context
from orchestrator.model_adapters.anthropic_adapter import ModelResponse


# ── multi-agent feature flag ──────────────────────────────────────────────────

def _multi_agent_enabled() -> bool:
    return os.environ.get("COGNIREPO_MULTI_AGENT_ENABLED", "false").lower() in ("1", "true", "yes")


# ── public dataclass ──────────────────────────────────────────────────────────

@dataclass
class RouteResult:
    response: ModelResponse
    classifier: ClassifierResult
    bundle: ContextBundle
    error: str = ""
    sub_queries: list[dict] = None  # populated when multi-agent is active

    def __post_init__(self):
        if self.sub_queries is None:
            self.sub_queries = []


# ── main entry point ──────────────────────────────────────────────────────────

def route(
    query: str,
    context: dict | None = None,
    force_model: str | None = None,
    top_k: int = 5,
    episode_limit: int = 10,
    max_tokens: int = 2048,
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

    # ── 2. build context ─────────────────────────────────────────────────────
    bundle = build_context(query, top_k=top_k, episode_limit=episode_limit)

    # ── 3. multi-agent sub-queries (DEEP only, off by default) ───────────────
    sub_queries: list[dict] = []
    if _multi_agent_enabled() and clf.tier == "DEEP":
        sub_queries = _run_sub_queries(query, bundle)
        if sub_queries:
            # Inject sub-query results into system prompt
            sub_text = "\n".join(
                f"  [{sq['target_tier']}] {sq['query'][:60]}: {sq['result'][:200]}"
                for sq in sub_queries
            )
            bundle.system_prompt += f"\n\n## Sub-Query Results (from fast models)\n{sub_text}"

    # ── 4. dispatch to adapter ───────────────────────────────────────────────
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
        return RouteResult(
            response=response, classifier=clf, bundle=bundle,
            error=error_msg, sub_queries=sub_queries,
        )

    # ── 5. post-process ───────────────────────────────────────────────────────
    _post_process(query=query, clf=clf, bundle=bundle, response=response)

    return RouteResult(
        response=response, classifier=clf, bundle=bundle, sub_queries=sub_queries,
    )


# ── multi-agent sub-query delegation ─────────────────────────────────────────

def _run_sub_queries(query: str, bundle: ContextBundle) -> list[dict]:
    """
    For DEEP queries, extract entity lookups and delegate them to FAST tier
    via gRPC sub-query.  Returns list of {query, result, target_tier} dicts.

    This is a best-effort step — failures are silently dropped.
    """
    results: list[dict] = []
    try:
        from graph.graph_utils import extract_entities_from_text  # pylint: disable=import-outside-toplevel
        from rpc.client import CogniRepoClient  # pylint: disable=import-outside-toplevel

        entities = extract_entities_from_text(query)[:2]  # max 2 sub-queries
        if not entities:
            return results

        grpc_host = os.environ.get("COGNIREPO_GRPC_HOST", "localhost")
        grpc_port = int(os.environ.get("COGNIREPO_GRPC_PORT", "50051"))

        import uuid  # pylint: disable=import-outside-toplevel
        context_id = "q_" + uuid.uuid4().hex[:8]

        with CogniRepoClient(host=grpc_host, port=grpc_port) as client:
            for entity in entities:
                sub_q = f"Where is {entity} defined and what does it do?"
                resp = client.sub_query(
                    query=sub_q,
                    context_id=context_id,
                    source_model="orchestrator",
                    target_tier="FAST",
                    max_tokens=256,
                    timeout=10.0,
                )
                if not resp.error:
                    results.append({
                        "query": sub_q,
                        "result": resp.result,
                        "target_tier": "FAST",
                        "model_used": resp.model_used,
                    })
    except Exception:  # pylint: disable=broad-except
        pass  # multi-agent is best-effort
    return results


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
            query=query, system_prompt=system_prompt, tool_manifest=tool_manifest,
            model_id=model_id, max_tokens=max_tokens,
        )
    if provider == "gemini":
        from orchestrator.model_adapters import gemini_adapter  # pylint: disable=import-outside-toplevel
        return gemini_adapter.call(
            query=query, system_prompt=system_prompt, tool_manifest=tool_manifest,
            model_id=model_id, max_tokens=max_tokens,
        )
    if provider in ("openai", "azure", "ollama", "lmstudio"):
        from orchestrator.model_adapters import openai_adapter  # pylint: disable=import-outside-toplevel
        return openai_adapter.call(
            query=query, system_prompt=system_prompt, tool_manifest=tool_manifest,
            model_id=model_id, max_tokens=max_tokens,
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
                "multi_agent": _multi_agent_enabled(),
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
