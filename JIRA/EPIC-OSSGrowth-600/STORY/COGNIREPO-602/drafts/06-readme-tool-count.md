TITLE: README says "34 MCP tools" in three places; real count is 35

LABELS: good first issue, documentation

BODY:
## Context

`README.md` claims "34 MCP tools" in at least three places (lines ~18, ~56, ~260 — line numbers
may have drifted, search for "34 tools"/"34 MCP tools"). The actual, correct count is **35** —
confirmed by both `interface/server/manifest.json` (35 entries) and `docs/MCP_TOOLS.md`'s own
header ("35 tools available"). A tool was added after these three README mentions were last
updated.

## Files involved

- `README.md` (search for "34 tools"/"34 MCP tools")

## What to do

1. Verify the real count yourself before editing — don't just trust this issue text (code
   moves): `grep -c "^@mcp\.tool()$" interface/server/mcp_server.py` should match
   `interface/server/manifest.json`'s entry count and `docs/MCP_TOOLS.md`'s stated count.
2. Update all three README mentions to the verified count.
3. Grep the rest of the repo for the old count (`grep -rn "34 tools\|34 MCP tools"`) to make sure
   nothing else was missed.

## Acceptance criteria

- [ ] All README tool-count mentions match the real `@mcp.tool()` decorator count
- [ ] `manifest.json` and `docs/MCP_TOOLS.md` already agree (35) — don't change those unless
      your own count differs, in which case flag it, don't silently "fix" it

## Recipe

None needed — verify-then-edit, this repo has drifted on this exact number before
(`CHANGELOG.md` [1.1.3] entry: "server/manifest.json missing 2 tools").
