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
- Obtained results:
- Verdict:

## TC-101-2: Drift detection trips
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: TC-101-1 passed.
- What to do: delete one entry from manifest.json; run pytest tests/test_manifest_drift.py;
  restore.
- Prompt: "Remove the search_token entry from manifest.json and run the drift test — it must
  fail naming the missing tool."
- Expected results: test fails, message names search_token; restore → green.
- Obtained results:
- Verdict:
