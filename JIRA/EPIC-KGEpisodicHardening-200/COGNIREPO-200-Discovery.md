# COGNIREPO-200 Discovery — Knowledge Graph & Episodic Memory Hardening (Phase 1)

Verified against HEAD (`146627d`, v2.0.0) on 2026-07-11. Builds on
`../EPIC-ReliabilityGate-100/COGNIREPO-100-Discovery.md` (§3 watcher, §4 graph) — read that first.

---

## 1. Knowledge graph — current state

- `data/graph/knowledge_graph.py` (363 lines). Node types (`:73-84`): FILE, FUNCTION, CLASS,
  CONCEPT, QUERY, SESSION, USER_ACTION, MEMORY, ERROR, ENDPOINT. Edge types (`:87-98`):
  RELATES_TO, DEFINED_IN, CALLED_BY, CALLS, QUERIED_WITH, CO_OCCURS, IMPORTS, INHERITS, EXPOSES,
  CALLS_ENDPOINT. **No SIMILAR_TO/similarity edge exists** (grep clean across `data/` and
  `intelligence/`) — README.md:634 correctly lists it as future work.
- API surface available to build on: `add_node` (idempotent, `:167-172`), `add_edge` (`:174-187`),
  `get_neighbours` BFS (`:227-265`), `hop_distance`/`shortest_path` (`:267-281`),
  `subgraph_around` bounded BFS (`:283-354`), `stats` (`:358-363` — counts only, no integrity
  metrics).
- Integrity gaps inherited from Phase 0 discovery: orphan symbol nodes accumulate on the watcher
  modify path (100-Discovery §3); corrupt `graph.pkl` falls back to empty with no quarantine or
  rebuild trigger (100-Discovery §4). Phase 1 owns the *proactive* side: an integrity
  sweep/report (orphan count, dangling `file` attrs pointing at deleted paths, edge-without-rel
  anomalies) surfaced via `graph_stats` and doctor.
- README roadmap items still open and in scope (README.md:613-636): Go call-graph completion
  (`ast_indexer.py:415` handles `call_expression` generically; Go-specific method/selector call
  extraction unproven — needs a Go fixture run), plugin-registry/dynamic-dispatch detection
  (no `DYNAMIC_DISPATCH` anywhere in code — not implemented), similarity edges (not implemented),
  BM25 over symbol names (partially exists: `core/_bm25` used by `hybrid.py:33,150-160` as
  fallback and `search_token` tool; TF-IDF ranking over symbol names for partial-match recall not
  wired into the main path).

## 2. Episodic memory — current state

- `data/memory/episodic_memory.py` (270 lines). JSON list at `.cognirepo/memory/episodic.json`,
  BM25Plus search with in-process cache (`:64-139`), vector-similarity fallback (`:169-196`),
  rotation to `episodic_archive.json` at `episodic_max_events` (default 10,000; oldest 20%
  archived, `:22-61`), `mark_stale` on file deletion (`:248-270`).
- **DEFECT (D02): ID collision after rotation.** `log_event` assigns `"id": f"e_{len(data)}"`
  (`:150`). After `_rotate_if_needed` trims the oldest 20%, `len(data)` falls below the highest
  existing ID, so subsequent IDs duplicate surviving entries. Consequences: `id_to_entry` dict in
  `search_episodes` (`:223`) silently collapses duplicates; the `prev` linked-list (`:155-156`)
  becomes ambiguous. Archive entries also share IDs with new live entries.
- Perf risk: `_semantic_episode_search` re-embeds **every** entry per query (`:179-192`, up to
  10k `encode_with_timeout` calls) with no embedding cache — acceptable only because it's a
  zero-BM25-hit fallback.
- `mark_stale` matches by substring over event+metadata JSON (`:263-264`) — coarse but
  intentional.
- `datetime.utcnow()` (`:153`) is deprecated in Python 3.12+ (cosmetic; repo requires ≥3.11).

## 3. Timeline coherence — do the four tools form one story?

The user's goal: episodic memory as the backbone that "keeps track of everything". Today the
record is **split across three stores with no unified view**:

| Store | Written by | Read by |
|---|---|---|
| `.cognirepo/memory/episodic.json` | `log_episode` (`mcp_server.py:1463`), `record_decision` (`:573` — logs `event="decision: …"`, `metadata.type="decision"`), watcher `mark_stale` | `episodic_search`, `get_history` |
| `.cognirepo/sessions/*.json` | session listener (`interface/server/session_listener.py`) | `get_session_history` (`mcp_server.py:1697-1746` — last exchange per session file) |
| `.cognirepo/` behaviour store (`behaviour.json` via `data/graph/behaviour_tracker.py:30`) | `record_query`/`record_error`/`record_file_edit`/`record_user_preference` | `get_user_profile`, `get_error_patterns`, hot symbols |

Gaps for a coherent timeline:
- No tool merges the three stores chronologically; an agent must call
  `get_session_history` + `episodic_search` + `get_error_patterns` and stitch (3 calls, no shared
  ordering key beyond ISO timestamps).
- Decisions are only recorded when an agent remembers to call `record_decision` (CLAUDE.md
  instructs it post-session; nothing enforces or backfills). `log_episode` additionally routes
  through `intercept_after_episode` (`mcp_server.py:1478`, learning middleware) but decisions and
  errors do not cross-link to the graph SESSION/USER_ACTION nodes.
- No human-readable rollup exists (nothing produces "what happened this week" text); this is
  exactly the data foundation Phase 2's insights report needs — design them together:
  **Phase 1 delivers the merged-timeline query API; Phase 2 renders it.**
- Rotation moves old events to `episodic_archive.json`, which **no search path reads**
  (`search_episodes` loads only `_load()` = live file) — long-horizon history silently drops out
  of insights/search once a repo crosses 10k events.

## 4. Token-cost posture (Ground Rule 3)

Any new MCP tool here (e.g. a `get_timeline`) costs ~100-250 manifest tokens
(100-Discovery §2). Alternative that costs zero schema tokens: extend the *outputs* of existing
tools (`get_session_brief`, `get_agent_bootstrap`) with a compact timeline digest. Both options
carried into the stories; the epic must justify whichever it picks.

## 5. Constraints

- All graph access must stay behind `intelligence/retrieval/hybrid.py` for retrieval paths, and
  tools stay in `interface/tools/` stateless (CLAUDE.md invariants).
- Similarity-edge computation touches embeddings — model names stay out (only
  `intelligence/orchestrator/classifier.py` may name models; embedding model is configured via
  fastembed/all-MiniLM-L6-v2 per stack, dim 384).
