# COGNIREPO-205 — Episodic robustness: archive search, embedding cache, decision coverage

Epic: COGNIREPO-200 · Branch: story/COGNIREPO-205 · Base: development

## Backstory
Three episodic gaps (../../COGNIREPO-200-Discovery.md §2-§3): (1) search_episodes reads only the
live file — rotated history is unsearchable; (2) the vector fallback _semantic_episode_search
(episodic_memory.py:169-196) re-embeds EVERY entry per query (up to 10k encode calls, no cache);
(3) system events (index-repo completion, org rewire) are never logged, so timelines miss
infrastructure activity, and decision logging relies entirely on agents remembering
record_decision.

## Description
(1) search_episodes(query, limit, include_archived=False) — when True, extend the corpus with
episodic_archive.json; expose the param on the episodic_search MCP tool (additive, ~15 manifest
tokens — record measured). (2) Persistent embedding cache keyed by event ID (requires D02) at
.cognirepo/memory/episodic_vecs.npy + id list sidecar; regenerable, safe to delete; document in
CONFIGURATION.md storage layout. (3) index-repo and org rewire completion call log_event with
kind metadata ({"type":"index_event", ...}); CLAUDE.md already instructs record_decision — add a
gentle nudge to the get_agent_bootstrap payload when 0 decisions exist but ≥N episodes do
("no decisions recorded yet — use record_decision for architectural choices").

## Acceptance criteria
1. Archived event found only with the flag; default behavior unchanged.
2. Second identical fallback search performs 0 encode calls (monkeypatched counter test).
3. index-repo on a fixture adds exactly one index_event episode.
4. datetime.utcnow() deprecation in episodic_memory.py:153 fixed (datetime.now(timezone.utc)).

## Risks / notes
- Cache invalidation: entry text is immutable once logged (only stale flag mutates) — cache by
  ID is safe; drop cache rows whose IDs disappear after rotation? No — archive keeps IDs valid.
