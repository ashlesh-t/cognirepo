# COGNIREPO-D08 — store_memory()'s `source` argument is silently discarded

Epic: COGNIREPO-100 · Branch: defect/COGNIREPO-D04_D05_D06 (bundled per user direction) · Base: story/COGNIREPO-105

## Backstory
Found while re-verifying TC-105-1 after fixing `COGNIREPO-D04` (kwarg mismatch) and
`COGNIREPO-D07` (hybrid.py hardcoding `source="semantic"`). Even with both fixes applied, a
real end-to-end run still failed: `store_memory(summary, source="interaction_style")` followed
by `retrieve_memory('interaction style')` returned the memory with `source: "memory"`, not
`"interaction_style"`.

Root cause: `interface/tools/store_memory.py`'s `store_memory(text, source="")` accepts a
`source` parameter and uses it for the `log_event()` metadata and the returned status dict, but
never forwards it to the actual storage call:

```python
mem.store(text)   # <- source is dropped here
```

`data/memory/semantic_memory.py::SemanticMemory.store(self, text)` never accepted a `source`
parameter at all — it always called `self.db.add(vector, text, importance)`, which defaults to
`source="memory"` in `LocalVectorDB.add()`. So every memory ever stored through the public
`store_memory()` tool — regardless of what `source=` the caller passed — was persisted with
`source="memory"`.

This is a third, independent pre-existing bug in the same `store_memory` → `retrieve_memory`
round trip that TC-105-1 exercises (alongside D04 and D07) — not introduced by COGNIREPO-105.

## Description
1. `data/memory/semantic_memory.py::SemanticMemory.store()` — accept `source: str = "memory"`
   (matching `LocalVectorDB.add()`'s existing default) and forward it to `self.db.add(...,
   source=source)`.
2. `interface/tools/store_memory.py` — change `mem.store(text)` to
   `mem.store(text, source=source or "memory")`. The `or "memory"` preserves the existing
   behavior for every caller that passes `source=""` (the CLI default, `--source ""`) — only
   callers that pass a real, truthy source (e.g. `source="interaction_style"`,
   `source="benchmark"`, `source="session_seed"`) now actually get it persisted.

## Acceptance criteria
1. `store_memory(text, source="interaction_style")` followed by
   `retrieve_memory('interaction style')` returns a hit with `source="interaction_style"` — this
   is what fully unblocks TC-105-1 (together with D04 and D07).
2. `store_memory(text)` (no source, or `source=""`) still stores with `source="memory"` —
   no behavior change for the common case.
3. Existing `store_memory`/`SemanticMemory` tests stay green; new regression tests cover both
   the "real source forwarded" and "empty source defaults to memory" cases.

## Risks / notes
- Narrowly scoped, single call-site fix with a backward-compatible default — low blast radius
  compared to D07.
- Filed and fixed in the same pass per explicit user direction (see `COGNIREPO-105`'s
  `TEST/COGNIREPO-105-TEST_SUITE.md` re-verification note) — bundled into
  `defect/COGNIREPO-D04_D05_D06` rather than its own branch/PR.
