# COGNIREPO-702 — Episodic-to-semantic consolidation pass

Epic: COGNIREPO-700 · Branch: story/COGNIREPO-702 · Base: development

## Backstory
No code path today promotes recurring episodic events into decisions or semantic memory.
`record_decision()` (`interface/server/mcp_server.py:646-670`) writes into the same flat
`episodic.json` list as ordinary episodes, distinguished only by `metadata["type"]=="decision"`,
and its docstring gates promotion on manual agent judgment — nothing calls it programmatically.
`BehaviourTracker.summarize_interaction_style()` (`data/graph/behaviour_tracker.py:675-723`) is
the only auto-triggered summarization in the repo, but it only touches its own transient
query-pattern buffer, never `episodic.json`, and prunes its source after summarizing.
`decision_nudge` (`interface/server/mcp_server.py:1953-1964`) is the closest prior art — it
detects the accumulation-without-promotion gap (0 decisions, ≥5 episodes/30d) but only emits a
static text nudge, with no inspection of episode content and no automatic remediation. Search
infrastructure to build on already exists: `search_episodes()`
(`data/memory/episodic_memory.py:332-376`, BM25 + vector-similarity fallback). Neuroscience
parallel: Complementary Learning Systems theory (McClelland/McNaughton/O'Reilly 1995) —
hippocampal one-shot encoding gradually consolidated into neocortex via replay — the same theory
that directly inspired DQN's experience replay (Mnih et al. 2015; Hassabis et al. 2017 makes the
link explicit). Evidence: `../../COGNIREPO-700-Discovery.md` §2.

## Description
Add a `consolidate_episodic()`-style pass that reuses `search_episodes()`'s existing
similarity machinery to cluster near-duplicate/recurring recent episodic events (same symbol,
file, or topic appearing repeatedly without ever being promoted to a decision), and surfaces the
result as `consolidation_candidates`: `[{group_summary, episode_ids, suggested_decision_draft}]`.
This is NOT a new background daemon or subsystem — trigger it on-demand (a tool call) or piggyback
on an existing lifecycle event (e.g. alongside `index-repo` or `generate_insights`, whichever
Analyze finds cheapest) rather than adding new state/process. Never auto-calls `record_decision`
— it only proposes; a human or agent still makes the call, respecting `record_decision`'s existing
"non-obvious, agent judgment" contract. Extends, rather than replaces, `decision_nudge`'s existing
threshold-based gap detection with actual content-aware evidence.

## Acceptance criteria
1. ≥3 near-duplicate episodic events about the same symbol/file/topic within a window (e.g. 30d,
   matching `decision_nudge`'s existing window) produce one `consolidation_candidates` entry
   citing the specific episode ids as evidence.
2. Never calls `record_decision` automatically under any circumstance — verified by a test that
   asserts no `record_decision`/`log_event(metadata.type="decision")` call happens during the
   consolidation pass itself.
3. Sparse/fresh episodic store (or no repeated topics) ⇒ empty `consolidation_candidates`, nothing
   fabricated — same honesty bar `generate_insights` (COGNIREPO-303) already holds.
4. Zero new MCP tool if foldable into an existing one (e.g. extend `get_agent_bootstrap` or
   `generate_insights`'s existing output) — if a new tool proves necessary, measure and report
   the manifest-token cost in the PR, matching COGNIREPO-500's "zero manifest growth" discipline
   as the target, not an absolute requirement.

## Risks / notes
- Clustering "near-duplicate" episodes needs a similarity threshold — reuse `search_episodes`'s
  existing BM25/vector scoring rather than inventing a new similarity metric; tune the threshold
  during Analyze against real seeded data, not guesswork.
- Must not touch `summarize_interaction_style()`'s existing pruning behavior — this story adds a
  new consolidation path, it does not modify the existing query-pattern summarization.
