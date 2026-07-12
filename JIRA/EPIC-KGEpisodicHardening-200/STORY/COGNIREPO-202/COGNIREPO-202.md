# COGNIREPO-202 — Similarity edges (SIMILAR_TO)

Epic: COGNIREPO-200 · Branch: story/COGNIREPO-202 · Base: development

## Backstory
README.md:634 roadmap item ("Similarity edges in knowledge graph — embedding-distance
clustering… not yet implemented") — verified absent (no SIMILAR anywhere in data/ or
intelligence/; CHANGELOG [1.1.3] even removed SIMILAR_TO from docs as not-in-code). Symbol
vectors already exist in the AST FAISS index. Evidence: ../../COGNIREPO-200-Discovery.md §1.

## Description
Post-index pass in intelligence/indexer/ast_indexer.py: for each symbol vector, FAISS k-NN over
the AST index; add graph edge (sym_a, sym_b, SIMILAR_TO, weight=cosine) when cosine ≥ 0.80,
max 5 per node, skip same-file pairs (DEFINED_IN already relates those). Add
EdgeType.SIMILAR_TO to data/graph/knowledge_graph.py. Config gate
`indexing.similarity_edges` (default true when symbol count < 20k, else false). Weight
SIMILAR_TO in hybrid.py's _graph_score (small factor, tune on fixtures) — retrieval logic stays
inside intelligence/retrieval/hybrid.py per CLAUDE.md. Re-add the edge type to
docs/architecture/graph.md.

## Acceptance criteria
1. Two near-duplicate functions in different fixture files get a SIMILAR_TO edge with weight ≥
   0.80; subgraph(entity) shows the counterpart.
2. Gate off ⇒ zero SIMILAR_TO edges; existing graphs load fine either way (unknown rel values
   are already tolerated).
3. Index-time overhead on the medium repo measured and recorded in the PR (< 20% target).
4. tests: edge creation, cap enforcement, gate, hybrid weight non-regression.

## Risks / notes
- Threshold/cap (0.80/5) are initial guesses — tune; risk of CONCEPT-like noise (cf.
  PYTHON_BUILTINS filtering, knowledge_graph.py:31-66).
