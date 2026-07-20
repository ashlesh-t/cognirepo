# COGNIREPO-D07 — Manual test suite

## TC-D07-1: retrieve_memory preserves real stored source
- Test repo: /home/ashlesh/my_works/cognirepo (this repo, isolated .cognirepo test fixture)
- Prerequisites: fix applied (hybrid.py preserves real source; retrieve_memory.py's
  _structure_results uses source in ("ast", "symbol")).
- What to do: store a memory with a real store_memory(text, source="interaction_style") call,
  then retrieve_memory() it and inspect the returned source field.
- Prompt: n/a — automated via tests/test_hybrid_retrieval_extended.py and
  tests/test_retrieve_memory_extended.py (direct call, no mock of the source field).
- Expected results: retrieve_memory() returns the hit with source="interaction_style" (not
  "semantic"); structured=True still buckets AST/symbol hits into code_hits and everything
  else into doc_hits.
- Obtained results: Fixed `intelligence/retrieval/hybrid.py::_vector_retrieve()` to report
  `r.get("source", "memory")` instead of hardcoded `"semantic"`. Added
  `tests/test_hybrid_retrieval.py::TestVectorRetrieveSourcePreservation` — stored a vector
  directly with `source="interaction_style"` via `r.db.add(...)`, called
  `r._vector_retrieve(vec, k=5)`, confirmed `results[0]["source"] == "interaction_style"`; a
  companion test confirms a plain `SemanticMemory().store(text)` (no explicit source) still
  reports `source == "memory"`. Combined with the D08 fix, the full TC-105-1 round trip
  (`store_memory(summary, source="interaction_style")` → `retrieve_memory('interaction
  style')`) now returns `source="interaction_style"` — verified via a real isolated-`.cognirepo`
  script, not mocks. `venv/bin/python -m pytest tests/test_hybrid_retrieval.py -q` — 8 passed.
- Verdict: PASS

## TC-D07-2: code_hits/doc_hits bucketing unaffected for non-AST text shapes
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: fix applied.
- What to do: run the full pytest suite, focusing on tests/test_context_pack.py and
  tests/test_retrieve_memory_extended.py.
- Prompt: n/a — automated.
- Expected results: all existing context_pack / retrieve_memory tests stay green — no
  regression in code_hits/doc_hits classification for real "ast"/"symbol" hits or for
  doc/memory hits whose text happens to contain "X in Y:Z"-shaped substrings.
- Obtained results: Updated `interface/tools/retrieve_memory.py::_structure_results()` to
  classify via `source in ("ast", "symbol")` instead of the previous
  `source == "semantic" and <text-shape heuristic>`. Added
  `test_structure_results_symbol_source_is_code_hit` (a real `source="symbol"` AST hit lands in
  `code_hits` with correct file/line extraction) and
  `test_structure_results_non_ast_source_with_in_colon_shape_stays_doc_hit` (a real
  `source="interaction_style"` hit whose text happens to contain "X in Y:Z"-shaped substrings
  correctly stays in `doc_hits`, not miscategorized). `context_pack.py` was already keying its
  own code/doc bucketing off `source == "ast"` specifically (never `"semantic"`), confirmed
  unaffected. `venv/bin/python -m pytest tests/test_context_pack.py
  tests/test_retrieve_memory_extended.py -q` — 35 passed. Full suite:
  `venv/bin/python -m pytest tests/ -q` — 1249 passed, 5 skipped (baseline was 1227 before this
  branch).
- Verdict: PASS
