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
- Verdict: (previously **BLOCKED (environment)** on stale pipx install 2.2.0 pre-dating D01/D02.
  2026-09-16: `pipx install .` from `development` @ `1910897` reinstalled `cognirepo` at
  **2.3.0** — `ast_indexer.py` mtime now 2026-09-16 19:37, confirming both the D01 minimal-attrs
  fix and D02 are in the served binary. Needs the `cognirepo-kubernetes` MCP server (and this
  session) restarted before re-running the prompt above — leaving blank for the user to re-run
  and fill in per skill.md §F.4.)

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
