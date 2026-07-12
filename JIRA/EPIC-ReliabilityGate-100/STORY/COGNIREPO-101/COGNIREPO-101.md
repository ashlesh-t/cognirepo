# COGNIREPO-101 — Single-source MCP tool manifest generation

Epic: COGNIREPO-100 · Branch: story/COGNIREPO-101 · Base: development

## Backstory
Tool schemas are hand-maintained in three copies — @mcp.tool() decorators (34 tools),
_build_manifest() in interface/server/mcp_server.py (32), glama.json (32) — plus a derived
openai_tools.json stuck at 13 tools whose generator (interface/adapters/openai_spec.py:27) still
reads the pre-2.0.0 path "server/manifest.json". This caused two drift incidents: [1.1.3] added
find_symbol_path + get_service_endpoints to the manifest (CHANGELOG.md:62), then the 2.0.0
rewrite dropped them again (fixed immediately by defect COGNIREPO-D01). Evidence:
../../COGNIREPO-100-Discovery.md §1b, §2.

## Description
Make the decorated functions the single source of truth. Build a generator (new
scripts/gen_tool_specs.py, or wired into `cognirepo export-spec`/_write_manifest) that
introspects the FastMCP tool registry (signatures + docstrings) and emits: manifest.json,
glama.json's tools array, openai_tools.json. Fix openai_spec.py's MANIFEST_PATH. Add
tests/test_manifest_drift.py asserting set-equality between decorated names (same extraction as
_REGISTERED_TOOLS, mcp_server.py:2588-2600) and every artifact — CI fails on drift.

## Acceptance criteria
1. All three artifacts regenerate from one command and list exactly the 34 decorated tools.
2. Hand-editing any artifact (or adding a tool without regenerating) fails CI.
3. glama.json defaults match code defaults (e.g. get_session_history limit=10, not 5).
4. openai_spec.py resolves the manifest at interface/server/manifest.json regardless of CWD.
5. Manifest token delta vs HEAD ≈ +210 (the two restored tools only) — record measured value in
   the PR description.

## Risks / notes
- Descriptions in generated manifest come from docstrings — review that the generated text stays
  ≤ current per-tool token size (~105 avg; link_repos max 252); trim docstrings if needed.
- Depends on: D01 merged first (hotfix); 106 documents the result.
