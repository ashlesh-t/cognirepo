# COGNIREPO-502 — Manual test suite

## TC-502-1: Hints appear only when real
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced
- Prerequisites: epic merged; two unrelated modules each with a TODO comment.
- What to do: spanning context_pack query; then a single-module query; then the spanning query
  with max_tokens=300.
- Prompt: "Use context_pack for '<spanning query>'. Is any of this work parallelizable?"
- Expected results: call 1: 2 groups + TODOs, ≤60 extra tokens; call 2: no delegation_hints key;
  call 3: hints dropped, code context preserved.
- Obtained results:
- Verdict:
