# COGNIREPO-D04 — summarize_interaction_style() always fails (store_memory kwarg mismatch)

Epic: COGNIREPO-100 · Branch: defect/COGNIREPO-D04 · Base: development

## Backstory
Found while implementing COGNIREPO-105 (layer-invariant cleanup of
`data/graph/behaviour_tracker.py`). `BehaviourTracker.summarize_interaction_style()`
(`data/graph/behaviour_tracker.py:565` pre-105, now routed through an injected `store_fn`)
calls:

```python
store_memory(summary, source="interaction_style", importance=0.8)
```

`interface/tools/store_memory.py:19` — the real function signature is
`store_memory(text: str, source: str = "") -> dict`. There is no `importance` parameter.
Every real call raises `TypeError: store_memory() got an unexpected keyword argument
'importance'`, caught by the blanket `except Exception: return False` at the end of
`summarize_interaction_style()` (pre-105 line ~580).

Because the `store_memory(...)` call happens *before* the `style["framing_hints"]` /
`style["last_summarized"]` / buffer-clearing logic in the same `try` block, the exception
short-circuits all of it — the interaction-style semantic memory is never stored, and
`style["framing_hints"]` (the cached snapshot `get_user_profile()` falls back to once
`query_patterns` is cleared) is never written by this path.

`tests/test_behaviour_tracker.py::TestFramingHintsLifecycle::test_summarize_interaction_style_direct_call`
already works around this — it patches `interface.tools.store_memory.store_memory` with
`return_value=None` before calling `summarize_interaction_style()` — masking the real-call
failure rather than exercising it.

## Description
Fix the call site to match the real `store_memory` signature (drop `importance=0.8`, or add
an `importance` parameter to `store_memory`/`SemanticMemory.compute_importance` plumbing if
score-forcing is actually wanted — needs a product decision). Update or remove the masking
mock in `test_summarize_interaction_style_direct_call` so the test exercises the real
(unmocked) call at least once.

## Acceptance criteria
1. A 10th `record_query()` call (or a direct `summarize_interaction_style()` call) with a real
   `store_fn=store_memory` stores a semantic memory and returns `True` — no exception swallowed.
2. `style["framing_hints"]` and `style["last_summarized"]` are populated after summarization.
3. Existing test suite green; the masking mock in
   `test_summarize_interaction_style_direct_call` is replaced with a real (or realistically
   faked, matching the true signature) call.

## Risks / notes
- Pre-existing bug, not introduced by COGNIREPO-105 — 105 only relocates this exact (buggy)
  call behind an injected `store_fn` callback, preserving current behavior mechanically per its
  own ticket's "no behavior edits" constraint.
- Decide whether `importance` should be a real, honored parameter (product call) before fixing.
