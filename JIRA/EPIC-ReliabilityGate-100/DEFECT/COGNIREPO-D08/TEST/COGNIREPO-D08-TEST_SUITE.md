# COGNIREPO-D08 — Manual test suite

## TC-D08-1: store_memory forwards a real source to storage
- Test repo: /home/ashlesh/my_works/cognirepo (this repo, isolated .cognirepo test fixture)
- Prerequisites: fix applied (SemanticMemory.store() accepts source; store_memory() forwards it).
- What to do: call store_memory(text, source="interaction_style") directly, then
  retrieve_memory(text) and inspect the source field.
- Prompt: n/a — automated via tests/test_store_memory*.py and tests/test_memory.py.
- Expected results: retrieve_memory() returns the hit with source="interaction_style".
- Obtained results: `SemanticMemory.store()` now accepts `source: str = "memory"` and forwards
  it to `self.db.add(..., source=source)`; `store_memory()` now calls `mem.store(text, source=source
  or "memory")`. Added `TestSemanticMemory.test_store_forwards_real_source` (direct
  `SemanticMemory` layer) and `TestStoreMemoryToolSourceForwarding.test_real_source_is_persisted`
  (full `store_memory()` tool call, unmocked) in `tests/test_memory.py` — both confirm
  `sm.retrieve(text, top_k=1)[0]["source"]` matches the real source passed in. Also
  end-to-end confirmed via the same isolated-`.cognirepo` script used for TC-D07-1: the full
  `BehaviourTracker.summarize_interaction_style()` → `store_memory(..., source=
  "interaction_style")` → `retrieve_memory('interaction style')` round trip now returns
  `source="interaction_style"` (previously "memory" even after D04/D07). `venv/bin/python -m
  pytest tests/test_memory.py -q` — 16 passed.
- Verdict: PASS

## TC-D08-2: default/empty source still stores as "memory"
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: fix applied.
- What to do: call store_memory(text) with no source argument, then inspect the stored
  metadata's source field.
- Prompt: n/a — automated.
- Expected results: stored source is "memory" (unchanged from pre-fix behavior) — no
  regression for the common no-source-specified case.
- Obtained results: `test_store_default_source_is_memory` (SemanticMemory layer) and
  `test_empty_source_still_defaults_to_memory` (store_memory() tool layer) in
  `tests/test_memory.py` both confirm `source == "memory"` when no source (or `source=""`) is
  passed — the `source or "memory"` forwarding in `store_memory.py` preserves the pre-fix
  default for the common case.
- Verdict: PASS
