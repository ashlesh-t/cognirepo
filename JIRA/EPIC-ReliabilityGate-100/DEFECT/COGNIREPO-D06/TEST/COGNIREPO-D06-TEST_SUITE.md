# COGNIREPO-D06 — Manual test suite

## TC-D06-1: Circuit breaker still trips after fix
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy/flask
- Prerequisites: fix applied (core→data upward import removed from local_vector_db.py).
- What to do: force the circuit breaker into an open/tripped state (per existing
  `data/memory/circuit_breaker.py` test fixtures), then attempt `store_memory` via the normal
  `get_vector_adapter()` path.
- Prompt: "Trip the circuit breaker, then try to store a memory — does it still block the
  write the way it did before the refactor?"
- Expected results: write is still blocked/raises exactly as before the fix — no silent
  behavior change.
- Obtained results: Ran a real end-to-end script (isolated `.cognirepo` fixture, faiss backend)
  using `SemanticMemory()` (the actual production wiring, which now passes
  `breaker_factory=get_breaker, cleanup_queue_factory=CleanupQueue` into `get_vector_adapter()`
  per the D06 fix). Tripped the breaker via `get_breaker().record_failure()`, then called
  `db.save()`: raised `CircuitOpenError("[CircuitBreaker:cognirepo] OPEN — retry in 30s")` —
  identical to pre-refactor behavior. `venv/bin/python -m pytest tests/test_storage_adapter.py -q`
  — 19/20 passed (1 pre-existing unrelated failure,
  `test_default_returns_local_vector_db`, confirmed present on HEAD before this branch too —
  caused by a real `~/.cognirepo` chroma store on this machine interfering with the
  `_find_config` monkeypatch, unrelated to D06).
- Verdict: PASS

## TC-D06-2: Suppressed rows still enqueue for cleanup
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy/flask
- Prerequisites: fix applied.
- What to do: trigger `suppress_row()` via the normal dedup/supersede path (e.g. store a
  near-duplicate memory that triggers auto-suppression), then inspect the cleanup queue.
- Prompt: "Store a duplicate-ish memory that gets auto-suppressed — does it still show up in
  the cleanup queue for deferred deletion?"
- Expected results: suppressed row is still enqueued in `CleanupQueue` exactly as before.
- Obtained results: Same script/session as TC-D06-1. Stored a memory via `db.add(vec,
  "duplicate-ish memory text", importance=0.6, source="memory")`, recorded `len(CleanupQueue())`
  before (0), then called `db.suppress_row(0, reason="auto_superseded", similarity=0.93)` and
  re-checked the queue length (1) — the suppressed row was enqueued via the injected
  `cleanup_queue_factory=CleanupQueue`, exactly matching pre-refactor behavior.
- Verdict: PASS
