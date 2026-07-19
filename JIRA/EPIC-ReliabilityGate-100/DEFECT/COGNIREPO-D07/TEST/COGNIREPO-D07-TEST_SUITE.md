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
- Obtained results:
- Verdict:

## TC-D07-2: code_hits/doc_hits bucketing unaffected for non-AST text shapes
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: fix applied.
- What to do: run the full pytest suite, focusing on tests/test_context_pack.py and
  tests/test_retrieve_memory_extended.py.
- Prompt: n/a — automated.
- Expected results: all existing context_pack / retrieve_memory tests stay green — no
  regression in code_hits/doc_hits classification for real "ast"/"symbol" hits or for
  doc/memory hits whose text happens to contain "X in Y:Z"-shaped substrings.
- Obtained results:
- Verdict:
