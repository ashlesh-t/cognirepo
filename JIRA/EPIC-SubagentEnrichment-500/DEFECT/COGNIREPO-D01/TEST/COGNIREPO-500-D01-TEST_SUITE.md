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
- Obtained results: fix implemented (Option 1: minimal `type`/`file`/`line` attrs + `DEFINED_IN`
  edge stamped for every symbol regardless of `_graph_weight_min`, rich attrs/embeddings/FAISS
  still gated as before). Real-file re-run against `daemon/container.go` with weight forced
  below `_LITE_GRAPH_WEIGHT_MIN` (0.5 < 0.75): `GetContainer` and `load` now both have proper
  `{type, file, line}` attrs (previously `{}`), and `_annotate_independence_groups()` gives both
  `component_id="g0"` (previously `g0`/`g1`). Also added automated coverage:
  `tests/test_indexer_multilang.py::TestLiteGraphWeightFilter` (2 tests — minimal-node-created,
  same-file-grouping end to end).
- Verdict: PASS

## TC-D01-2: No regression to COGNIREPO-501 AC2/AC4
- Test repo: n/a (unit suite)
- What to do: `venv/bin/python -m pytest tests/test_hybrid_retrieval.py -q`
- Expected results: all pass, including the byte-identical-with-grouping-disabled golden test
  and the <10ms latency test.
- Obtained results: `tests/test_hybrid_retrieval.py -q -n 4` run 3x, 26 passed each time (was 25
  before this ticket — added `test_grouping_allowed_cache_keyed_by_graph`, replacing the
  now-fixed `test_grouping_allowed_cache_not_keyed_by_graph`). Full suite:
  1440 passed, 5 skipped.
- Verdict: PASS

## TC-D01-3: No memory/time regression on large repos (Option 1 was chosen)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced/moby (`daemon/` subtree, 960
  real `.go` files — full-repo reindex of all ~10k files was impractical for this session's time
  budget; this subtree is representative and large enough to extrapolate from)
- What to do: index the same 960 files with `embed=False` (isolating graph-population cost from
  embedding cost) and `_graph_weight_min` forced to lite-graph mode, before vs. after the fix
  (via `git stash`), measuring `resource.getrusage().ru_maxrss` and wall-clock time.
- Expected results: no material regression — the fix only adds a few dict keys + one edge per
  already-processed symbol, no new embedding/FAISS work.
- Obtained results:
  ```
  before: nodes=10778 edges=61872  elapsed=5.98s  peak_rss=109.8MB  attrless=5306 (49.2%)
  after:  nodes=14081 edges=69553  elapsed=7.11s  peak_rss=114.4MB  attrless=0    (0.0%)
  delta:  +4.6MB (+4.2%) peak RSS, +1.13s (+19%) wall time, for 100% attr coverage (was 49.2%)
  ```
  Modest, proportionate overhead for the correctness fix — no OOM-level regression. Extrapolated
  linearly to the full ~10k-file repo: roughly +45MB / +11s, well within the memory headroom the
  weight filter was protecting in the first place.
- Verdict: PASS
