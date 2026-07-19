# COGNIREPO-D08 — Manual test suite

## TC-D08-1: store_memory forwards a real source to storage
- Test repo: /home/ashlesh/my_works/cognirepo (this repo, isolated .cognirepo test fixture)
- Prerequisites: fix applied (SemanticMemory.store() accepts source; store_memory() forwards it).
- What to do: call store_memory(text, source="interaction_style") directly, then
  retrieve_memory(text) and inspect the source field.
- Prompt: n/a — automated via tests/test_store_memory*.py and tests/test_memory.py.
- Expected results: retrieve_memory() returns the hit with source="interaction_style".
- Obtained results:
- Verdict:

## TC-D08-2: default/empty source still stores as "memory"
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: fix applied.
- What to do: call store_memory(text) with no source argument, then inspect the stored
  metadata's source field.
- Prompt: n/a — automated.
- Expected results: stored source is "memory" (unchanged from pre-fix behavior) — no
  regression for the common no-source-specified case.
- Obtained results:
- Verdict:
