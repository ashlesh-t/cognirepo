# COGNIREPO-500-D01 — Manual test suite (written before the fix, per skill.md §G.1)

## TC-D01-1: Same-file symbols group together on a large repo
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced/moby
- Prerequisites: repo indexed (already is); fix direction chosen (see ticket options 1-3).
- What to do: pick two functions confirmed in the same large Go file (e.g.
  `daemon/container.go::GetContainer` and `daemon/container.go::load`); run them through
  `HybridRetriever._annotate_independence_groups()` directly (unmocked, real graph).
- Prompt: n/a — reproduced via direct Python, not a chat prompt (see ticket's Repro section for
  the exact snippet).
- Expected results: both symbols get the SAME `component_id` (post-fix). Currently (pre-fix)
  they get different ids (`g0`/`g1`) — this is the defect.
- Obtained results:
- Verdict:

## TC-D01-2: No regression to COGNIREPO-501 AC2/AC4
- Test repo: n/a (unit suite)
- What to do: `venv/bin/python -m pytest tests/test_hybrid_retrieval.py -q`
- Expected results: all pass, including the byte-identical-with-grouping-disabled golden test
  and the <10ms latency test.
- Obtained results:
- Verdict:

## TC-D01-3: No memory/time regression on large repos (only if fix option 1 chosen)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced/moby and /advanced/kubernetes
- What to do: full reindex (`cognirepo index-repo .`) before and after the fix; compare peak RSS
  and wall-clock time.
- Expected results: no material regression (the fix should only add a few dict keys per
  already-created edge-endpoint node, not new embedding/FAISS work).
- Obtained results:
- Verdict:
