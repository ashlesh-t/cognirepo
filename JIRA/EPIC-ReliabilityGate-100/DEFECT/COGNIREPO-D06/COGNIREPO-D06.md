# COGNIREPO-D06 — core/vector_db/local_vector_db.py imports upward into data.memory

Epic: COGNIREPO-100 · Branch: defect/COGNIREPO-D06 · Base: development

## Backstory
Found while implementing COGNIREPO-105 (layer-invariant cleanup) after fixing
`scripts/build_import_graph.py`'s stale `INTERNAL_PACKAGES` set (it matched zero real
imports before the fix, so `check_circular_deps.py` always trivially passed). Re-running the
checker on real data surfaced two `core → data` upward imports in
`core/vector_db/local_vector_db.py` (layer 0 importing from layer 1), both lazy
(function-body) imports:

```python
# save(), line 167
def save(self):
    from data.memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
    breaker = get_breaker()
    breaker.check()
    ...
    breaker.record_success()
```

```python
# suppress_row(), line 265
from data.memory.cleanup_queue import CleanupQueue  # pylint: disable=import-outside-toplevel
CleanupQueue().push(...)
```

Both are architecture-invariant violations per `docs/ARCHITECTURE.md`'s layer stack
(`core(0) < data(1) < intelligence(2) < interface(3) < ops(4) < cli(5)`).

The mechanical-DI pattern used elsewhere in COGNIREPO-105 (optional keyword-only callback
params, default `None`, wired at construction sites) does not cleanly apply here: the
dominant, in fact near-universal, construction path for `LocalVectorDB` is
`get_vector_adapter()` in `core/vector_db/factory.py` — itself `core` layer, so it cannot
legally import `data.memory.circuit_breaker`/`cleanup_queue` to build the callbacks either.
`get_vector_adapter()` is called pervasively and transitively by `data/memory/semantic_memory.py`,
`intelligence/retrieval/hybrid.py`, `intelligence/indexer/doc_ingester.py`,
`interface/tools/prime_session.py`, and others — none of which currently pass
circuit-breaker/cleanup-queue callbacks through to construction. Defaulting the injected
factory to `None` at the one true construction path would silently disable circuit-breaker
write protection and deferred-cleanup enqueueing for nearly all real callers — a genuine
behavior regression, not a no-op refactor, and out of scope for COGNIREPO-105's "no behavior
edits" constraint.

## Description
Design and implement a fix that removes the `core → data` upward import without disabling
circuit-breaker protection or deferred cleanup for real callers. Candidate approaches to
evaluate:
1. Thread `breaker_factory`/`cleanup_queue_factory` callables through
   `get_vector_adapter()` → `LocalVectorDB.__init__`, and wire them at the actual top-level
   callers (interface/ops/cli layer) that today reach `get_vector_adapter()` transitively —
   requires auditing every call site, not just the direct ones.
2. Move `circuit_breaker`/`cleanup_queue` down into `core` (layer 0) if they have no
   `data`-layer-specific dependencies themselves — check whether this is architecturally
   sound or whether they belong in `data` for other reasons.
3. Introduce a `core`-layer protocol/interface for "write breaker" and "deferred cleanup
   sink" that `data.memory.circuit_breaker`/`cleanup_queue` implement and register into at
   startup (inversion of control), so `core` never imports `data` directly.

## Acceptance criteria
1. `core/vector_db/local_vector_db.py` has zero `data`-layer imports (toplevel or lazy),
   confirmed via `scripts/check_circular_deps.py`.
2. Circuit-breaker protection in `save()` and deferred-cleanup enqueueing in `suppress_row()`
   still function identically for all current real callers (regression tests covering both
   paths, exercised through `get_vector_adapter()` — not just direct `LocalVectorDB`
   construction).
3. No caller of `get_vector_adapter()` silently loses circuit-breaker/cleanup-queue behavior.

## Risks / notes
- This is the one COGNIREPO-105 upward-import finding that could not be resolved via the
  mechanical DI pattern used for every other site in that story; deferred here rather than
  rushed, per skill.md §G.
- Whichever approach is chosen, re-run `scripts/build_import_graph.py` +
  `scripts/check_circular_deps.py --verbose` to confirm zero remaining hard violations.
