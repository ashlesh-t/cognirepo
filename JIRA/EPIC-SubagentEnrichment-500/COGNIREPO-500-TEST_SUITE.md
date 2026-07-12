# COGNIREPO-500 — Epic e2e test suite (cross-story flows only)

## E2E-500-1: Delegable work surfaces end-to-end (crosses 501+502)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced
- Prerequisites: epic merged; repo indexed; identify (or add) two modules with no import/call
  relationship, each containing a TODO comment.
- What to do: issue a context_pack query whose hits span both modules; then one whose hits are
  all within one connected module.
- Prompt: "Use context_pack for '<query spanning both modules>'. If it suggests parallelizable
  work, explain how you would split it between subagents."
- Expected results: first call returns 2 delegation groups with the TODOs and Claude proposes a
  sensible split; second call's output has no delegation_hints key at all; token overhead ≤ 60.
- Obtained results:
- Verdict:

## E2E-500-2: No false hints on a degraded graph (crosses 501 gate + EPIC-200's 201)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: epic merged; artificially create orphans (delete a source file bypassing the
  watcher, don't reindex).
- What to do: run the same spanning query.
- Prompt: "Use context_pack for '<query>' and tell me if it flagged parallelizable work."
- Expected results: grouping suppressed (high-orphan gate), no delegation_hints emitted; core
  retrieval unaffected.
- Obtained results:
- Verdict:
