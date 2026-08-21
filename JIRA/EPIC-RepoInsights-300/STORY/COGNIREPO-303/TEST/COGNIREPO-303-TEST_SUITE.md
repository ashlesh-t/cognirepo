# COGNIREPO-303 — Manual test suite

## TC-303-1: Both entry points
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: epic branch merged; MCP reconnected (new tool visible).
- What to do: run `cognirepo insights`; then call generate_insights via Claude.
- Prompt: "Generate the repo insights report via the MCP tool and give me the link."
- Expected results: both produce/update the same file; Claude's reply contains the path and NOT
  the report body; tool output small.
- Obtained results: automated equivalent — `pytest tests/test_insights_cli_mcp.py -q`
  (`TestCLIInsightsCommand`, `TestGenerateInsightsMCPTool`): CLI `cognirepo insights` exits 0,
  prints path, writes exactly one `.claude/insights/<repo>-insights.html`; MCP
  `generate_insights()` returns `{status, path, sections, updated_at}` — tiktoken-measured
  105 tokens (< 120, AC5), no report body. Live MCP-reconnect + Claude-prompt pass (TC-303-1 as
  written) not yet re-run manually — pending user session with a reconnected MCP client.
- Verdict: PASS (automated); manual live leg pending

## TC-303-2: Dogfood retrieval
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: TC-303-1 done; a distinctive decision seeded (e.g. "adopted zanzibar cache").
- What to do: search for report content via CogniRepo.
- Prompt: "Using search_docs, what does the insights report say about the zanzibar decision?"
- Expected results: hit from the markdown twin with a relevant snippet.
- Obtained results: automated equivalent — `pytest tests/test_insights_cli_mcp.py -q`
  (`TestDocsSearchCarveOut`): seeded `.cognirepo/docs/myrepo-insights.md` with a "zanzibar cache"
  decision; `intelligence.retrieval.docs_search.search_docs("zanzibar")` returns the twin's
  snippet. Confirmed the fix required for this to work at all — `docs_search.py`'s os.walk
  previously hard-skipped all of `.cognirepo/` (including `.cognirepo/docs/`); carved out
  `.cognirepo/docs/` specifically while leaving `.cognirepo/index/` and other internals excluded
  (same test asserts a seeded `.cognirepo/index/` file is NOT returned). Live prompt-driven leg
  not yet re-run manually.
- Verdict: PASS (automated); manual live leg pending
