# COGNIREPO-300 — EPIC: <repoName>-insights HTML report (Phase 2) → v2.2.0

## Backstory
Users need a human-readable, real-data answer to "what was done in this repo, how, what were the
challenges, what branches" — today that exists only as raw tool outputs across three stores.
Phase 1 built the merged timeline (COGNIREPO-204); this epic renders it (plus git history via
interface/tools/git_utils.py and graph/hot-symbol stats) into a single self-contained HTML
report, updated idempotently in place, indexed by CogniRepo itself. Evidence:
`COGNIREPO-300-Discovery.md` (this folder). Plan: `docs/planning/02-insights-feature.md`.
IMPORTANT: content is templated from real records ONLY — no model-generated/fabricated prose.

## Description
Stories: 301 (insights data collector — intelligence-layer aggregation over timeline + git +
graph), 302 (HTML generator + idempotent tmp/os.replace writer to
`.claude/insights/<repoName>-insights.html`, markdown twin to `.cognirepo/docs/`), 303
(CLI `cognirepo insights` + MCP tool `generate_insights` + docs-index ingestion + the explicit
CLAUDE.md storage-exception amendment — see plan doc for approved wording; fallback path
`.cognirepo/insights/` if the user rejects the amendment).
Order: 301 → 302 → 303. Requires EPIC-200 signed off (consumes get_timeline).

## Acceptance criteria
1. `cognirepo insights` writes the self-contained HTML (zero external requests, light/dark),
   sections: overview, timeline, decisions, challenges (recurring errors), branch/commit
   activity, index health.
2. Re-run updates the same file in place — never a duplicate.
3. Every rendered fact carries a data-ref (episode id / commit hash / stat); empty sources say
   "no data recorded".
4. search_docs finds the report content after generation (markdown twin).
5. MCP tool returns {status, path, sections, updated_at} — a link surface, not content.
6. CLAUDE.md amendment merged (or fallback path adopted and recorded).

## Notes
Version 2.2.0. New-tool manifest cost ~130 tokens (record on the 303 PR). UI bar pinned in the
plan doc: section nav, dark/light parity, < 200 KB, design-review round with the user at Gate 1.
