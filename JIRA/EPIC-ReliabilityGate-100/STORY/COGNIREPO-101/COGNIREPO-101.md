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

## Resolution (2026-07-13)
`_build_manifest()` (`interface/server/mcp_server.py`) rewritten to introspect the live FastMCP
registry via `asyncio.run(mcp.list_tools())` instead of ~530 lines of hand-written schema —
`_clean_tool_description()` takes the first paragraph of each docstring (whitespace-collapsed to
one line); `_clean_tool_schema()` normalizes FastMCP's pydantic-derived `inputSchema` (drops
`title` keys, flattens `Optional[X]` `anyOf` unions to a plain `{type, default}`, always includes
an explicit `required` list) to match the existing hand-written convention.

New `scripts/gen_tool_specs.py` (maintainer-only, matches the existing `scripts/sync_version.py`
pattern — `scripts/` is not part of the installed package per `pyproject.toml`'s
`[tool.setuptools.packages.find]`): regenerates manifest.json (via the same `_build_manifest()`),
syncs `glama.json`'s `tools` array (preserving its other top-level metadata keys), and calls
`openai_spec.export()` for `openai_tools.json` + `cursor_mcp_config.json`. `--check` mode diffs
without writing, for CI/local drift checks.

`openai_spec.py`: `MANIFEST_PATH`/`DEFAULT_OUT_DIR` now resolve from `__file__` (absolute),
not CWD-relative `"server/manifest.json"`/`"adapters"` — verified working when invoked from an
unrelated CWD (AC4). `_load_manifest()` now unconditionally calls `_write_manifest()` first
(not just when missing), so `cognirepo export-spec` alone regenerates manifest.json +
openai_tools.json + cursor_mcp_config.json from the live registry for end users too — not just
the maintainer script.

This same introspection caught a live, previously-undocumented drift: `graph_stats` gained a
`repo_path` parameter at some point after the manifest was last hand-written; the old
hand-maintained entry still showed `"properties": {}, "required": []`.

`tests/test_manifest_drift.py` (5 cases): set-equality between `_REGISTERED_TOOLS` and each of
manifest.json/glama.json/openai_tools.json, plus `test_no_drift_between_disk_artifacts_and_live_registry`
which calls `gen_tool_specs.regenerate(check=True)` — verified to fail (naming the missing tool)
when an entry is deleted from manifest.json, and pass again after restoring/regenerating.

Token measurement (AC5): manifest token delta vs HEAD (post-D01) is **-277** (3328 vs 3605
tokens across 34 tools, avg 97.9/tool vs 106.0) — a ~8% reduction, not the anticipated +210
growth, since D01 had already restored the two missing tools and the introspected descriptions
(first-docstring-paragraph) are on average shorter than the old hand-written ones. `link_repos`
(the ticket's cited max) is 154 tokens, well under the ~252 ceiling.

Full pytest: 1211 passed (1206 baseline + 5 new drift tests), 5 skipped.
