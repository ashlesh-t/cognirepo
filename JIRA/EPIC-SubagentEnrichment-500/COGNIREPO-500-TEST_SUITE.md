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
- Obtained results: Modules used: `pkg/util/oom/oom.go:21` (`TODO: make this an interface, and
  inject a mock ioutil struct for testing`) and `pkg/util/labels/labels.go:79`
  (`TODO(madhusudancs): Check if you can use deepCopy_extensions_LabelSelector here`) — confirmed
  no import/call relationship (`oom_linux.go` imports only `pkg/kubelet/cm/util` + klog;
  `labels.go` imports only `apimachinery/pkg/apis/meta/v1`).

  Ran `mcp__cognirepo-kubernetes__context_pack` (backed by the `cognirepo-kubernetes` MCP
  server, `.mcp.json` → `/home/ashlesh/.local/bin/cognirepo` → pipx venv) with several phrasings
  of a query spanning both TODOs. Every call returned `status: "ok"` with generic semantic
  hits (mostly file-header license-comment chunks) and **no `delegation_hints` key at all** —
  not even a single-group result. File-scoped calls (`file: "pkg/util/oom/oom.go"`) do
  correctly retrieve the actual TODO line, so symbol-level retrieval itself works; the
  delegation-grouping layer never activates regardless of query.

  Root cause traced, not a context_pack query problem: the pipx install serving this project
  (`/home/ashlesh/.local/share/pipx/venvs/cognirepo`, reports `2.2.0`) has
  `intelligence/indexer/ast_indexer.py` last modified 2026-08-24 22:31 — predating the
  COGNIREPO-500-D01 fix (commit `5d79748`, committed 2026-08-30 17:27, merged via PR #65 at
  21:17) that stamps minimal graph attrs for weight-filtered symbols so
  `_reachable_files`/grouping works on large repos. Without that fix, weight-filtered symbol
  nodes (this repo: ~80% of nodes per D01's own measurement) get zero attrs and never
  connect to their FILE node, so `_annotate_independence_groups` / `delegation_hints` can't
  form groups at all on a repo this size — this is the exact "stale pipx-served process"
  scenario D02 was filed from. The sibling `cognirepo-cognirepo` MCP server (dev venv, editable
  install of the current branch, correctly includes the D01 fix) was not the one under test
  here since `.mcp.json` pins this project to the pipx binary.

  Did not attempt a corrected re-run: reinstalling/upgrading the pipx package and restarting the
  MCP server mid-session risks disrupting the active tool connection and wasn't authorized for
  this pass.
- Re-run 2026-09-16 (after pipx reinstall to 2.3.0 + fresh session): `context_pack` returned only
  low-relevance license-header boilerplate (~0.35–0.39 score), no TODO-line hits, no
  `delegation_hints` key — feature still doesn't fire. User read both files directly and did the
  parallelization split manually (sound reasoning, but not evidence of the tool feature working).
  **Second root cause identified**: the D01 fix lives in `ast_indexer.py`'s lite-graph mode,
  which only runs at *index-build* time — reinstalling the binary doesn't retroactively repair a
  graph.pkl already built by the old (pre-D01) indexer. This repo's `.cognirepo/graph` was last
  built 2026-09-03, while the pipx binary was still 2.2.0 — so the on-disk graph still lacks the
  minimal `{type, file, line}` attrs D01 added. Needs `cognirepo index-repo` re-run against the
  now-2.3.0 binary to rebuild the graph, then a fresh MCP session, before this AC can be
  meaningfully re-tested.
- Verdict: **BLOCKED (environment, retry)** — stale on-disk graph, not a binary issue this time.
  Next: reindex `advanced/kubernetes` with the 2.3.0 binary and re-run the prompt above.

## E2E-500-2: No false hints on a degraded graph (crosses 501 gate + EPIC-200's 201)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: epic merged; artificially create orphans (delete a source file bypassing the
  watcher, don't reindex).
- What to do: run the same spanning query.
- Prompt: "Use context_pack for '<query>' and tell me if it flagged parallelizable work."
- Expected results: grouping suppressed (high-orphan gate), no delegation_hints emitted; core
  retrieval unaffected.
- Obtained results: Ran `context_pack(query="password hashing utility functions")` against the
  `easy/fastapi` repo after deleting `fastapi/security/utils.py` (tracked file, had incoming
  edges, removed via `rm`, not reindexed). `status: "ok"`, `token_count: 2000`,
  `truncated: false`, 20 `bucket: "code"` sections from `docs_src/security/tutorial00{3,4,5}*.py`
  and `docs_src/extra_models/*.py`. `fastapi/security/utils.py` did not appear anywhere in the
  output — not as a hit, not as a broken/orphan reference. No `delegation_hints` field, no
  parallelization signal. Core retrieval stayed functional (returned relevant sections from the
  remaining live files); the stale orphan reference produced no visible error, warning, or
  degraded-mode signal.
- Verdict: **PASS** — grouping suppressed (no `delegation_hints` on the degraded graph), core
  retrieval unaffected. Note: no staleness/orphan warning surfaced in the response, but that's
  outside this AC's scope (AC only requires suppression + unaffected retrieval).
