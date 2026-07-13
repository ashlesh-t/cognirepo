# COGNIREPO-101 — Manual test suite

## TC-101-1: Regeneration parity
- Test repo: /home/ashlesh/my_works/cognirepo (this repo)
- Prerequisites: story branch checked out, venv active.
- What to do: run the generator (cognirepo export-spec); set-compare decorated names vs
  manifest.json vs glama.json vs openai_tools.json.
- Prompt: "Run cognirepo export-spec, then verify manifest.json, glama.json and
  openai_tools.json each contain exactly the same 34 tool names as the @mcp.tool decorators."
- Expected results: 34 = 34 = 34 = 34; diff empty; find_symbol_path + get_service_endpoints
  present everywhere.
- Obtained results (post-fix, story/COGNIREPO-101, 2026-07-13): ran `cognirepo export-spec`
  (regenerates manifest.json + openai_tools.json + cursor_mcp_config.json; glama.json is synced
  separately by the maintainer-only `python scripts/gen_tool_specs.py`, since it's a repo-root
  registry-listing file, not shipped in the installed package). manifest=34, glama=34,
  openai_tools=34, all three name-sets equal; find_symbol_path + get_service_endpoints present
  in all three. `graph_stats` schema now correctly includes its (previously undocumented)
  `repo_path` param, caught by the same introspection. Manifest token footprint: 3328 tokens
  across 34 tools (avg 97.9/tool) vs 3605 baseline — a ~8% reduction, not growth (link_repos
  max 154 tokens, well under the ~252 ceiling noted in the ticket's risk).
- Verdict: PASS

## TC-101-2: Drift detection trips
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: TC-101-1 passed.
- What to do: delete one entry from manifest.json; run pytest tests/test_manifest_drift.py;
  restore.
- Prompt: "Remove the search_token entry from manifest.json and run the drift test — it must
  fail naming the missing tool."
- Expected results: test fails, message names search_token; restore → green.
- Obtained results (post-fix, story/COGNIREPO-101, 2026-07-13): deleted `search_token` from
  manifest.json, ran `pytest tests/test_manifest_drift.py` — 2 of 5 tests failed;
  `test_manifest_json_on_disk_matches_registered_tools` reported "Extra items in the right set:
  'search_token'" (i.e. missing from the left/on-disk set); `test_no_drift_...` failed with the
  "run: python scripts/gen_tool_specs.py" message. Restored manifest.json → all 5 tests green
  again.
- Verdict: PASS
