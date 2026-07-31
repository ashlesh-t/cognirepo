# COGNIREPO-103 — Orphan-node cleanup on re-index + graph.pkl corruption quarantine

Epic: COGNIREPO-100 · Branch: story/COGNIREPO-103 · Base: development

## Backstory
Two graph-integrity gaps (../../COGNIREPO-100-Discovery.md §3-§4). (1) The watcher's modify path
(file_watcher.py:146-148) calls graph.remove_node_edges() — which removes edges but KEEPS the
node (knowledge_graph.py:189-192) — so symbols deleted from a file leave permanent orphaned
nodes; the delete path (remove_file_nodes, knowledge_graph.py:200-219) is correct. (2) On a
corrupt graph.pkl, _load() (knowledge_graph.py:110-138) warns, starts empty, and leaves the
corrupt file to be silently overwritten by the next save() — no quarantine, unlike the AST
index's .corrupt rename (ast_indexer.py:2066-2078).

## Description
(1) In _reindex(), replace the remove_node_edges loop with graph.remove_file_nodes(rel_path)
before re-indexing so stale symbol nodes vanish. (2) In KnowledgeGraph._load(), on load failure
rename the file to graph.pkl.corrupt-<unix_ts> (mirror _load_json_self_heal) before falling back
to empty; keep the existing encrypted→plaintext fallback intact. (3) Add a doctor check that
reports .corrupt-* files under .cognirepo/graph/ with the rebuild hint.

## Acceptance criteria
1. Modifying a file to remove a function leaves no node for it (fixture-verified).
2. Garbage graph.pkl → server starts, quarantine file exists, warning names it.
3. Doctor lists quarantined graph files.
4. FILE-node and CONCEPT edges recreated correctly after the modify-path change (no regression
   in tests/test_stale_cleanup.py, test_graph.py).

## Risks / notes
- remove_file_nodes on modify also drops the FILE node momentarily — ensure index_file re-adds
  it (it does for the delete+recreate flow; verify edge weights aren't semantically lost —
  CO_OCCURS/QUERIED_WITH history on symbol nodes WILL be lost for renamed symbols; acceptable,
  note in PR).
- Sequenced after COGNIREPO-102 (same file).
