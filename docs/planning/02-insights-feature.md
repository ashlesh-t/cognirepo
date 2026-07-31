# Phase 2 — `<repoName>`-insights HTML report → v2.2.0

**Epic:** COGNIREPO-300 (`JIRA/EPIC-RepoInsights-300/`). Evidence:
`JIRA/EPIC-RepoInsights-300/COGNIREPO-300-Discovery.md` (*D300 §n*).
**Depends on:** Phase 1 (consumes COGNIREPO-204's timeline API).

## Context / Why

Users (and the project's own GTM, see Phase 5) need a human-readable answer to "what happened in
this repo" — what was done, how, challenges, branches — sourced from real data: the episodic
log + decisions (D300 §1), git history via the existing `git_utils.git_log_patch`
(`interface/tools/git_utils.py:31`), and graph/hot-symbol stats. Today that story exists only as
raw tool outputs. The report is also the first consumer proving Phase 1's timeline API.

## Scope

**In:** data collector; single-file HTML generator (offline, light/dark); idempotent in-place
update; `cognirepo insights` CLI + `generate_insights` MCP tool; markdown twin ingested by the
docs index (dogfood); CLAUDE.md storage-exception amendment.
**Out:** any model-generated prose (all content templated from real records — no fabrication);
scheduling/watch-mode; multi-repo/org-level reports (future).

## Acceptance criteria (epic)

1. `cognirepo insights` produces `.claude/insights/<repoName>-insights.html` — self-contained
   (zero external requests verified by grep for `http` in the artifact), light/dark via
   `prefers-color-scheme`, sections: overview, timeline, decisions, challenges (recurring
   errors), branch/commit activity, index health.
2. Re-running updates that same file in place (same path, updated content, `generated_at` +
   `updated_at` both shown); no second file is created.
3. Every fact in the report traces to a record (episode id, commit hash, graph stat) — a
   `data-ref` attribute per rendered item; empty sources render "no data recorded", never
   invented content.
4. `search_docs("insights <topic>")` returns hits from the report's markdown twin after
   generation.
5. The MCP tool returns `{path, sections, updated_at}` (< ~80 output tokens), not report content;
   Claude surfaces the link.
6. CLAUDE.md carries the approved storage-exception amendment.

## Stories

### COGNIREPO-301 — Insights data collector
- **Files:** new `intelligence/orchestrator/insights_collector.py` (aggregation is
  intelligence-layer work; reads via data-layer APIs), reusing `timeline.merge()`
  (COGNIREPO-204), `git_utils.git_log_patch` + new `git_utils.list_branches()`,
  `behaviour_tracker.get_hot_symbols`, `KnowledgeGraph.stats()`/`integrity_report()`.
- **Interface contract:** internal API `collect(repo_root, since="90d") -> InsightsModel`
  (typed dict: meta, timeline, decisions, errors, branches, commits_by_week, hot_symbols,
  index_health). No MCP surface.
- **Data flow:** collector → data-layer reads only (episodic/timeline, behaviour, graph) + git
  subprocess via git_utils. Never calls FAISS directly (no retrieval involved — aggregation, not
  search; consistent with hybrid.py's ownership being about *retrieval*).
- **State/schema:** none; read-only.
- **Dependencies:** COGNIREPO-204.
- **Test oracle:** unit test on a fixture `.cognirepo/` + git repo → model contains the seeded
  decision, the seeded error pattern, and real commit hashes; empty fixture → all-empty model
  with `status: "no_data"` per section (AC3).

### COGNIREPO-302 — HTML generator, idempotent writer
- **Files:** new `interface/tools/insights.py` (render + write; stateless), an inline-assets
  HTML template (string template or `string.Template` — no new dependency), writer using
  tmp+`os.replace` (pattern: `ast_indexer.py:2051` — D300 §5).
- **Interface contract:** internal `render(model) -> str`, `write(html, repo_root) -> path`
  with fixed path `.claude/insights/<repoName>-insights.html`; markdown twin written to
  `.cognirepo/docs/<repoName>-insights.md` for indexing (D300 §4a).
- **Data flow:** model → deterministic template → single HTML file + md twin →
  `docs_index` ingestion hook (existing `intelligence/indexer/docs_index.py` picks up
  `.cognirepo/docs/`? verify ingestion root; if it only scans repo docs, register the twin
  explicitly at generation time).
- **State/schema:** the `.claude/insights/` artifact (see amendment below) + md twin under
  `.cognirepo/docs/`. Idempotency: fixed filename per repo; overwrite in place (AC2).
- **Dependencies:** 301.
- **Test oracle:** AC1 (grep artifact for `https?://` → only `data-ref` free of external URLs;
  both color schemes present), AC2 (two runs → one file, mtime advanced, `updated_at` changed),
  AC3 (every `<li>` carries `data-ref`).

### COGNIREPO-303 — CLI command + MCP tool + indexing + CLAUDE.md amendment
- **Files:** `interface/cli/main.py` (subparser `insights`, handler — DEVELOPER_GUIDE.md:162
  recipe), `interface/server/mcp_server.py` (tool registration — DEVELOPER_GUIDE.md:36 recipe),
  `docs/MCP_TOOLS.md`, `docs/CLI_REFERENCE.md`, `CLAUDE.md`, regenerate manifests via
  COGNIREPO-101 generator.
- **Interface contract (new MCP tool):**
  `generate_insights(since: str = "90d", repo_path: str | None = None) -> dict` →
  `{status, path, sections: [str], updated_at}`. Manifest cost ~130 tokens (D300 §7).
  Justification: replaces multi-call "repo status" reconstruction; output is a path, not
  content (AC5).
- **Data flow:** MCP tool → `interface/tools/insights.py` → collector (301) → writer (302) →
  `log_event("insights generated", {...})` so the timeline records it (D300 §4).
- **State/schema:** as 302.
- **Dependencies:** 301, 302; COGNIREPO-101 (generated manifests).
- **Test oracle:** AC4 (`search_docs` returns twin content), AC5 (tool output token count <
  120 via tiktoken in test), CLI exit 0 + path printed.

## Architecture-rule compliance — explicit CLAUDE.md amendment required

Storing the HTML under `.claude/` violates the current storage rule (all storage under
`.cognirepo/` with two `~/.cognirepo` exceptions). **Proposed amendment** (must merge with this
epic, wording final at PR):

> - Exception 3: generated human-facing reports (currently `cognirepo insights`) are written to
>   `.claude/insights/<repoName>-insights.html` in the project root. Rationale: these are
>   presentation artifacts for the human + their agent tooling, not machine state; keeping them
>   out of `.cognirepo/` avoids polluting index/memory storage, and `.claude/` is already the
>   agent-facing, gitignored surface. The machine-readable twin remains under `.cognirepo/docs/`.

All other rules respected: tool is stateless in `interface/tools/`, no cross-tool calls
(collector is a library, not a tool), no model names introduced, retrieval untouched.

## Version bump

**2.2.0** (from 2.1.0) — additive feature: one CLI command, one MCP tool, no breaking changes.

## Risks / open questions

- Verify `docs_index` ingestion covers `.cognirepo/docs/` (D300 §4 — flagged for 302's
  implementer; fallback: explicit ingest call at generation).
- "Exceptionally good UI" is subjective — the ticket pins it to: keyboard-free reading flow,
  section nav, dark/light parity, < 200 KB file; a design review round with the user is built
  into the story's Gate 1.
- `.claude/` may not exist in arbitrary user repos — generator creates it; confirm no conflict
  with Claude Code's own usage of that directory (it tolerates unknown files).
- If the user rejects the CLAUDE.md amendment, fallback path is
  `.cognirepo/insights/` (no amendment needed) — decision recorded at epic sign-off.
