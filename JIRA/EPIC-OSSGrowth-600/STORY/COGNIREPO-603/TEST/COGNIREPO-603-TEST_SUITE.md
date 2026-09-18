# COGNIREPO-603 — Manual test suite

## TC-603-1: Registry + community surface
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: story merged (parts 1+2).
- What to do: run the manifest drift test; click the Discord link; compare tool counts across
  README/version.yml/server.json/Glama listing.
- Prompt: "Verify CogniRepo's registry artifacts and README community links are current and
  consistent. Report any mismatch."
- Expected results: all consistent at 34 tools/current version; Discord resolves.
  (Correction: real tool count is **35**, not 34 — confirmed via `_REGISTERED_TOOLS` in
  `interface/server/mcp_server.py`, matched by `manifest.json`/`glama.json`/
  `openai_tools.json`/`server.json`; the "34" in this test spec predates the count drift this
  story fixes.)
- Obtained results: `venv/bin/python -m pytest tests/test_manifest_drift.py -v` — all 5 PASS
  (manifest.json/glama.json/openai_tools.json all match the live 35-tool registry, no
  hand-edited drift). `python scripts/sync_version.py --check` — clean, server.json's
  title/description now also sync from `version.yml`'s `mcp` section (previously only the
  version number synced; server.json's description said "34 MCP tools" while `version.yml`
  already said "35" — fixed by extending `sync_server_json()`). README's 3 tool-count
  mentions (headline, schema-overhead note, MCP Tools table intro) and
  `docs/MCP_TOOLS.md`'s header now all say 35, verified against the same
  `_REGISTERED_TOOLS` source — new regression tests
  `test_readme_tool_count_matches_registry`/`test_mcp_tools_md_header_count_matches_registry`
  in `tests/test_docs_sync.py` pin this going forward. Also found and fixed: README's MCP
  Tools table itself was missing a row for `generate_insights` (34 rows for 35 real tools) —
  added under a new "Reporting" category. Discord link: `https://discord.com/channels/...`
  returns HTTP 200 (curl-verified); already present as a badge (README:12) and now also in a
  dedicated "Community" section near the end of README.
- Verdict: **PASS**

## TC-603-2: Showcase authenticity (post-EPIC-300)
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: EPIC-300 shipped; showcase merged.
- What to do: regenerate the insights report; compare with README screenshots.
- Prompt: "Generate this repo's insights report and confirm the README showcase screenshots
  match the real artifact."
- Expected results: screenshots match reality (same sections/theme); no fabricated content.
- Obtained results: Ran `cognirepo insights --since 365d` live on this repo (2026-09-18) →
  `.claude/insights/cognirepo-insights.html`, 67 real events (episode: 17, session: 49,
  decision: 1). Rendered the actual generated file via a local HTTP server + real browser
  (Chrome, screenshot tool) — not a mockup. Page CSS uses `prefers-color-scheme` with
  no manual toggle; captured the real dark render as-served (matched the browser's live
  media-query state), then overrode the page's own CSS custom properties with its own
  documented light-mode `:root` values (read directly from the page's stylesheet, not
  invented) to capture the real light render — both are the actual generated report,
  same content, same DOM, different theme tokens. Saved to `docs/assets/insights-report-
  light.jpg` and `docs/assets/insights-report-dark.jpg`, embedded in README's new "Repo
  insights" section. Sections shown: Overview, Timeline, Decisions, Challenges, Branch/Commit
  Activity, Index Health — matches `docs/MCP_TOOLS.md`'s documented `generate_insights`
  section list exactly, nothing fabricated.
- Verdict: **PASS**
