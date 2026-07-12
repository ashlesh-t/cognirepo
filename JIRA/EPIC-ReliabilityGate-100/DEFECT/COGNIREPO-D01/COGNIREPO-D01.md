# COGNIREPO-D01 — DEFECT: manifest.json + glama.json missing find_symbol_path & get_service_endpoints (regression)

Epic: COGNIREPO-100 · Branch: defect/COGNIREPO-D01 · Base: development · Severity: P1

## Backstory / reproduction (verified at HEAD 146627d, 2026-07-11)
34 tools carry @mcp.tool() in interface/server/mcp_server.py (a 35th grep hit is a comment at
:2587); interface/server/manifest.json and glama.json each list 32. Set-diff: find_symbol_path
(decorator ~:1317) and get_service_endpoints (~:1348) are absent from both. CHANGELOG.md:62
([1.1.3], 2026-06-17) fixed EXACTLY these two entries; the 2.0.0 manifest rewrite dropped the
fix — a regression. Impact: agents discovering tools via the manifest (and the Glama registry
listing) never learn these tools exist; version.yml/README both advertise "34 MCP tools".
Doctor's _REGISTERED_TOOLS set (mcp_server.py:2588-2600) correctly has all 34. Evidence:
../../COGNIREPO-100-Discovery.md §1b.

## Description / fix
Minimal hotfix (structural fix is story COGNIREPO-101): add both entries with full parameter
schemas to _build_manifest() (copy the [1.1.3] entries — signatures unchanged since), regenerate
manifest.json (cognirepo export-spec), and add the same two entries to glama.json. While there,
fix glama.json's get_session_history limit default (5 → 10, code truth at mcp_server.py:1697).

## Acceptance criteria
1. manifest.json and glama.json list 34 tools; set-equal with decorators.
2. `cognirepo verify-index`-adjacent doctor schema check passes (all _REGISTERED_TOOLS present).
3. Entries' parameter schemas match the Python signatures (name/type/default).
