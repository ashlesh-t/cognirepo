# COGNIREPO-204 — Unified timeline (get_timeline or bootstrap digest) + rollup

Epic: COGNIREPO-200 · Branch: story/COGNIREPO-204 · Base: development

## Backstory
The "what happened" record is split across three stores with no merged view: episodic.json
(log_episode + record_decision events, mcp_server.py:573-598/1463-1478), sessions/*.json
(get_session_history parses last exchanges, mcp_server.py:1697-1746), and the behaviour store
(errors/preferences). No rollup exists; rotated events (episodic_archive.json) are read by
NOTHING. This story is the data foundation for EPIC-300's insights report. Evidence:
../../COGNIREPO-200-Discovery.md §3-§4.

## Description
New data/memory/timeline.py: merge(since, include_archived, limit) reading episodic (live +
archive), the sessions dir (extract the session-file parser out of mcp_server.py:1697-1746 into
the data layer and reuse), and behaviour error patterns → chronologically sorted entries
[{ts, kind: session|episode|decision|error|index_event, summary, ref}] + a DETERMINISTIC
template rollup (counts + top items — no model-generated text). Surface (decide at
implementation, measure both): (a) new MCP tool get_timeline(since="7d",
include_archived=False, limit=100, repo_path=None) — ~140 manifest tokens, must be recorded on
the PR; or (b) PREFERRED if it fits: a 5-entry digest folded into get_agent_bootstrap's
existing output — 0 manifest tokens. Ground Rule 3 justification either way: replaces the
3-call stitch (get_session_history + episodic_search + get_error_patterns).

## Acceptance criteria
1. Fixture with 2 sessions + 3 episodes + 1 decision + 1 error → one call returns 7 ordered
   entries; rollup names the decision and error.
2. include_archived=True returns rotated events; default excludes them.
3. Deterministic: same store state ⇒ byte-identical output.
4. Requires D02 merged (stable unique refs).
5. docs/MCP_TOOLS.md + CLAUDE.md routing table updated for whichever surface ships.

## Risks / notes
- Session-parser extraction must not change get_session_history behavior (golden test).
- Timestamps are ISO strings across stores — normalize defensively (some old entries may lack
  timezone suffixes).

## Implementation notes (2026-08-08)
- AC4 (requires D02 merged): already satisfied — D02 (episodic ID collision after rotation)
  was fixed and signed off under EPIC-100's defect slot (PR #34), predating this story.
  `_next_event_id()` already produces store-lifetime-unique refs across live+archive. No new
  defect needed; verified by reading `data/memory/episodic_memory.py` before coding.
- Surface decision (per the "measure both" instruction): folded a 5-entry digest into
  `get_agent_bootstrap()`'s existing output rather than a new `get_timeline` MCP tool.
  Measured: standalone tool draft (signature + docstring, same detail level as this ticket's
  Description) = **180 manifest-equivalent tokens** (tiktoken cl100k_base) — in line with the
  ticket's own ~140 estimate. Folded approach = **0 manifest tokens** (`gen_tool_specs.py
  --check` confirms manifest.json unchanged — no new `@mcp.tool()` registered). Chose folded:
  Ground Rule 3 justification is stronger (replaces the 3-call stitch at zero manifest cost
  instead of ~180), and `get_agent_bootstrap` is the tool already documented as the
  session-start entry point.
- Full `merge()`/`rollup()` API still lives in `data/memory/timeline.py` for direct use
  (custom `since`/`include_archived`/`limit`) and as the data foundation for EPIC-300's
  `generate_insights` tool, per the story's background.
