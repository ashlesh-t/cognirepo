# COGNIREPO-201 — Graph integrity sweep + metrics

Epic: COGNIREPO-200 · Branch: story/COGNIREPO-201 · Base: development

## Backstory
KnowledgeGraph.stats() (data/graph/knowledge_graph.py:358-363) returns only node/edge counts —
no integrity visibility. Known orphan sources: the pre-EPIC-100 watcher modify path, and any
historical index runs. Doctor has no graph-integrity check. Evidence:
../../COGNIREPO-200-Discovery.md §1; ../../../EPIC-ReliabilityGate-100/COGNIREPO-100-Discovery.md §3-§4.

## Description
Add KnowledgeGraph.integrity_report() → {orphans (non-CONCEPT nodes with degree 0), dangling
(nodes whose 'file' attr no longer exists on disk), swept_at}. Surface it: graph_stats MCP tool
output gains an `integrity` block (output-only — input schema untouched, 0 manifest tokens);
doctor gains a check flagging nonzero orphans/danglers with the repair hint; new CLI
`cognirepo graph repair` prunes danglers via remove_file_nodes (dry-run by default, --apply to
prune). Dangling detection needs the repo root — pass it in from the caller (tools already
resolve repo context via _repo_ctx).

## Acceptance criteria
1. graph_stats returns integrity {orphans, dangling_files, swept_at}.
2. Doctor flags a seeded dangling node; clean fresh index reports 0/0.
3. `graph repair --apply` removes danglers only (orphan CONCEPTs untouched); prints counts.
4. Sweep cost on the medium test repo < 1 s (it's O(nodes)).

## Risks / notes
- Orphan definition must exclude legitimately isolated node types (MEMORY, SESSION, ERROR may
  have no edges early) — restrict to FILE/FUNCTION/CLASS.
