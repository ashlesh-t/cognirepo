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
- Obtained results:
- Verdict:

## TC-D06-2: Suppressed rows still enqueue for cleanup
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy/flask
- Prerequisites: fix applied.
- What to do: trigger `suppress_row()` via the normal dedup/supersede path (e.g. store a
  near-duplicate memory that triggers auto-suppression), then inspect the cleanup queue.
- Prompt: "Store a duplicate-ish memory that gets auto-suppressed — does it still show up in
  the cleanup queue for deferred deletion?"
- Expected results: suppressed row is still enqueued in `CleanupQueue` exactly as before.
- Obtained results:
- Verdict:
