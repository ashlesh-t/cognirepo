# CogniRepo — GitHub Copilot Instructions

CogniRepo MCP tools are available in this workspace. Use them before native file exploration.

## Tool routing

| Task | Use first |
|------|-----------|
| Find a function | `mcp_cognirepo_lookup_symbol` |
| Understand code / query | `mcp_cognirepo_context_pack` |
| Find callers | `mcp_cognirepo_who_calls` |
| Past decisions | `mcp_cognirepo_episodic_search` |
| Architecture | `mcp_cognirepo_architecture_overview` |

**NEVER** read files >100 lines without calling `context_pack` first.
**NEVER** assume where a symbol lives — call `lookup_symbol` first.

If `context_pack` returns `status: "no_confident_match"` or `status: "index_empty"`,
fall back to grep / file read directly.
