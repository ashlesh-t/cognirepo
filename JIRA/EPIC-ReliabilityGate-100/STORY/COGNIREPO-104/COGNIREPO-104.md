# COGNIREPO-104 — verify-index working-tree staleness detection

Epic: COGNIREPO-100 · Branch: story/COGNIREPO-104 · Base: development

## Backstory
`cognirepo verify-index` (interface/cli/main.py:142-230) checks platform compatibility, index
file checksums, and git-COMMIT staleness — but uncommitted working-tree edits to indexed sources
are invisible to it (../../COGNIREPO-100-Discovery.md §3). A user editing files all day sees
"OK … commit <hash>" while the index is actually stale for every dirty file.

## Description
Extend _cmd_verify_index: run `git status --porcelain` in the repo root, filter to indexed
extensions (via language_registry.is_supported), and for each dirty tracked file compare its
mtime against the manifest's indexed_at. Emit a `DIRTY  <n> uncommitted indexed source file(s)
newer than index` line (listing up to 5 paths with -v) and exit 1. Keep exit codes: 0 OK, 1
stale/corrupted/dirty, 2 no manifest.

## Acceptance criteria
1. Clean tree at indexed commit → unchanged OK output, exit 0.
2. One uncommitted edit to an indexed .py → DIRTY line, exit 1.
3. Edit to a non-indexed extension (.md unless docs-indexed) → no DIRTY, exit 0.
4. Non-git directory degrades gracefully (current behavior preserved).

## Risks / notes
- mtime-vs-indexed_at comparison needs a small clock-skew tolerance (±2 s).
- Pure CLI change; no MCP/storage surface.
