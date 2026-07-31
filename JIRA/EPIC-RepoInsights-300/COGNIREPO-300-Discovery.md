# COGNIREPO-300 Discovery — <repoName>-insights HTML report (Phase 2)

Verified against HEAD (`146627d`, v2.0.0) on 2026-07-11.

---

## 1. Data sources available (never fabricate — all real)

- **Episodic log**: `data/memory/episodic_memory.py` — `get_history(limit)` (`:161-166`),
  `search_episodes` (`:199-229`); decisions carry `metadata.type == "decision"` with
  summary/rationale/affected_files (`interface/server/mcp_server.py:573-598`). Archive file
  `episodic_archive.json` holds rotated history (currently unread by any consumer —
  200-Discovery §3; the insights collector should read it for full history).
- **Git history**: `interface/tools/git_utils.py` — `git_log_patch()` (`:31`) with `_parse_since`
  (`:86`) and structured commit parsing (`:101`); used today by `explain_change`
  (`mcp_server.py` tool). Branch listing not yet wrapped — plain `git branch -a`/`git log` calls
  needed (extend git_utils, not shell-out from tools).
- **Knowledge graph**: `data/graph/knowledge_graph.py` — `stats()`, `subgraph_around()`; hot
  symbols via `data/graph/behaviour_tracker.py:485-494` `get_hot_symbols()`.
- **Sessions**: `.cognirepo/sessions/*.json` via the same read pattern as `get_session_history`
  (`mcp_server.py:1697-1746`).
- **Phase 1 dependency**: the merged-timeline API (COGNIREPO-204) is the preferred single entry
  point for "what happened" — the collector consumes it rather than re-stitching stores.

## 2. The extension recipe (per docs)

The task prompt cites "docs/CONTRIBUTING.md 'Adding a CLI Tool'" — **that section does not
exist**. The real recipe lives in `docs/DEVELOPER_GUIDE.md`:
- "How to Add a New MCP Tool" (`DEVELOPER_GUIDE.md:36`): implement in `interface/tools/<name>.py`
  (stateless, no cross-tool calls) → register `@mcp.tool()` wrapper in
  `interface/server/mcp_server.py` → register in `interface/adapters/openai_spec.py` flow
  (manifest) → tests → document in `docs/MCP_TOOLS.md`.
- "How to Add a New CLI Command" (`DEVELOPER_GUIDE.md:162`): subparser + handler in
  `interface/cli/main.py` → document in `docs/CLI_REFERENCE.md`.
Tickets must reference DEVELOPER_GUIDE.md sections, not the nonexistent CONTRIBUTING section.

## 3. Storage location — rule conflict to resolve explicitly

CLAUDE.md: "All storage lives under `.cognirepo/` … with one exception:
`~/.cognirepo/<repo>/last_context.json`" (+ `~/.cognirepo/org_graph.pkl`). The user wants the
HTML report under **`.claude/`**. That is a third exception → requires an explicit CLAUDE.md
amendment (Ground Rule 2), proposed in the epic. Note `.claude/` is gitignored in this repo
(`.claude/CLAUDE.md` is described as gitignored in root CLAUDE.md), which suits a generated,
per-machine artifact. Proposed convention: `.claude/insights/<repoName>-insights.html` — one
file per repo, enabling idempotent in-place update (detect by exact path; regenerate content;
preserve the file's identity/URL for bookmarks).

## 4. Making the report indexable by CogniRepo itself (dogfood)

- `search_docs` path: `intelligence/indexer/docs_index.py` ingests markdown; HTML is not a
  supported input. Two viable designs:
  a. Generator writes a **markdown twin** alongside (e.g. `.cognirepo/docs/insights.md`) that the
     existing docs index ingests — zero new index code, report content reachable via
     `search_docs`/`context_pack` doc-intent path (`interface/tools/context_pack.py:104-106`
     doc-intent detection).
  b. Teach docs_index to strip HTML — more code, no extra artifact.
  Discovery leans (a): reuses `store-memory`-adjacent flows, no parser work; the HTML stays a
  pure presentation artifact.
- Generation-time summary can also be logged as an episode (`log_event`) so future timelines note
  "insights generated".

## 5. Idempotency substrate

No existing report/update-in-place pattern in the repo to reuse; nearest analog is
`_write_manifest()` (`mcp_server.py:2580-2584`, overwrite-in-place) and `_atomic_json_dump`
(`ast_indexer.py:2051`) for atomic replace. The generator should write via tmp+`os.replace` (same
pattern) and key the report by resolved repo root name.

## 6. UI constraints

Everything in this project is offline (README.md:18 "Fully offline"); the report must be a single
self-contained HTML file — inline CSS/JS, no CDN/fonts/external requests — light/dark aware
(`prefers-color-scheme`). Claude surfaces the file path/link after generation, not raw content —
so the MCP tool's return payload must be small ({path, sections, updated_at}), keeping output
token cost low (Ground Rule 3).

## 7. Token-cost accounting for the new tool

One new MCP tool (`generate_insights`) at ~120-180 manifest tokens (comparable to
`record_decision`, 145 — 100-Discovery §2). Offset: the report replaces multi-call history
reconstruction (get_session_history + episodic_search + git log reads) for the "what's the state
of this repo" question — net input-token reduction for that workflow.
