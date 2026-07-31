# COGNIREPO-502 — delegation_hints surface + TODO scan + consumer docs

Epic: COGNIREPO-500 · Branch: story/COGNIREPO-502 · Base: development

## Backstory
context_pack (interface/tools/context_pack.py; output contract :218-231 — 5 base keys incl.
status) is the flagship, token-budgeted surface (max_tokens default 2000; tiktoken counter
:56-57). The enrichment must be conditional (absent when nothing is parallelizable — zero fixed
cost) and must never displace core content. TODOs: no indexer support exists — pack-time grep
over HIT FILES ONLY keeps the index schema unchanged. Evidence:
../../COGNIREPO-500-Discovery.md §2, §4-§5.

## Description
In context_pack assembly: group hits by 501's component_id; when ≥2 groups exist, append
delegation_hints: [{group, files, reason: "no shared import/call path"}] plus ≤3 TODO/FIXME
lines per group ({file, line, text}, grepped from the hit files at pack time). Budgeting: hints
are counted LAST against max_tokens and dropped FIRST on overflow. Input schema unchanged →
0 manifest tokens (the docs/MCP_TOOLS.md context_pack section documents the new output key).
CLAUDE.md routing table gains: "context_pack may return delegation_hints — consider subagent
delegation when groups ≥ 2".

## Acceptance criteria
1. Two-group fixture ⇒ hints present with TODOs; connected fixture ⇒ key ABSENT.
2. Added output ≤ ~60 tokens for the two-group case (tiktoken in test).
3. Tight budget (max_tokens small) ⇒ hints dropped, core content intact.
4. docs/MCP_TOOLS.md + CLAUDE.md updated.

## Risks / notes
- Sparse-graph false positives are the epic's main risk — reason strings + the 501 integrity
  gate are the mitigations; do not remove them for "cleanliness".
