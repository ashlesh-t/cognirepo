# COGNIREPO-106 — Manual test suite

## TC-106-1: Doc claims match code
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: story merged.
- What to do: verify each fixed claim against code.
- Prompt: "Check docs/FEATURES.md §15/§16, README Future Plans, and SECURITY.md against the
  actual code and CI workflows. List any claim that is still wrong."
- Expected results: zero wrong claims; §16 documents CALLS_API auto-detection via
  http_call_scanner/org rewire with its limits; §15 count == number of tests/test_*.py.
- Obtained results:
- Verdict:
