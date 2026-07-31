# COGNIREPO-D01 — Manual test suite

## TC-D01-1: Tool parity restored
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: defect branch merged.
- What to do: count and set-compare tools in code vs manifest.json vs glama.json.
- Prompt: "Compare the @mcp.tool functions in mcp_server.py against manifest.json and
  glama.json. Report counts and any missing names."
- Expected results: 34/34/34, no missing names; find_symbol_path + get_service_endpoints present
  with correct schemas; get_session_history default limit is 10 everywhere.
- Obtained results (reproduction at HEAD pre-fix, 2026-07-11): 34 decorators vs 32/32 —
  find_symbol_path, get_service_endpoints missing from both artifacts. Fix verification
  (post-fix, defect/COGNIREPO-D01, 2026-07-12): `_REGISTERED_TOOLS` (34) == manifest.json tool
  names (34) == glama.json tool names (34); diff is empty set. find_symbol_path and
  get_service_endpoints present in both artifacts with schemas matching the Python signatures
  (from_symbol/to_symbol required, from_repo/to_repo default ""; repo_path default "" resp.).
  get_session_history limit default is 10 in manifest.json, glama.json, and code
  (mcp_server.py:1697). Full pytest: 1203 passed, 5 skipped (unchanged from baseline).
- Verdict: PASS
