# COGNIREPO-203 — Manual test suite

## TC-203-1: Go caller resolution
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced — VERIFY it contains Go
  sources first; if not, use the tests/fixtures Go fixture added by this story and note it here.
- Prerequisites: story merged; repo (re)indexed.
- What to do: hand-list the callers of one exported Go function (grep); compare who_calls.
- Prompt: "Who calls <GoFunc>? Give file:line for each caller."
- Expected results: ≥90% of the hand-verified list returned with correct locations; coverage
  note honest about the remainder.
- Obtained results:
- Verdict: (BLOCKED until Go-source presence in the test repo is confirmed)

## TC-203-2: Dynamic dispatch annotation
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced (or fixture)
- Prerequisites: as above; a celery-style task or plugin-register pattern present.
- What to do: query the symbol via lookup_symbol/subgraph.
- Prompt: "Look up <task_fn> — does CogniRepo know it's dynamically dispatched?"
- Expected results: node carries dispatch:"dynamic"; subgraph links the dynamic_dispatch
  concept.
- Obtained results:
- Verdict:
