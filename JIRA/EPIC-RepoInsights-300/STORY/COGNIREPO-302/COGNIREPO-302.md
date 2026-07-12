# COGNIREPO-302 — HTML generator + idempotent writer

Epic: COGNIREPO-300 · Branch: story/COGNIREPO-302 · Base: development

## Backstory
Render 301's model into ONE self-contained HTML file — offline like everything in this project
(no CDN/fonts/external requests), light/dark via prefers-color-scheme, "exceptionally good" UI
pinned to: section nav, dark/light parity, keyboard-free reading flow, < 200 KB. Idempotent:
fixed path per repo, update in place (tmp + os.replace — the ast_indexer.py:2051 pattern).
Storage target .claude/insights/<repoName>-insights.html is a CLAUDE.md exception handled in
303. Evidence: ../../COGNIREPO-300-Discovery.md §3, §5, §6.

## Description
New interface/tools/insights.py (stateless): render(model) -> str using stdlib templating (no
new deps), write(html, repo_root) -> path creating .claude/insights/ if absent. Sections:
overview, timeline, decisions, challenges (recurring errors), branch/commit activity, index
health. Every rendered fact carries data-ref="<episode id|commit hash|stat key>". Also emit a
markdown twin to .cognirepo/docs/<repoName>-insights.md (for 303's indexing). Show
generated_at + updated_at.

## Acceptance criteria
1. Artifact passes: no external URL fetches (grep + devtools check), renders in both themes,
   < 200 KB, valid HTML (tidy/nu-check or python html.parser round-trip).
2. Two consecutive runs → same path, one file, updated_at advanced.
3. Every fact node carries data-ref; no_data sections render "no data recorded".
4. Unit tests: idempotency, data-ref coverage, empty-model rendering.

## Risks / notes
- Design-review round with the user at Gate 1 (UI bar is subjective — expect one iteration).
- Repo names with spaces/unicode → slugify the filename, keep display name verbatim.
