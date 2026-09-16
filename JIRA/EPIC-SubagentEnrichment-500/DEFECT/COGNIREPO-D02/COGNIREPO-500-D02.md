# COGNIREPO-500-D02 — setup wizard never surfaces tiered-indexing choice

Epic: COGNIREPO-500 · Branch: defect/COGNIREPO-500-D02 · Base: development
Found while re-testing E2E-500-1 for COGNIREPO-500-D01: diagnosing why a moby MCP server
returned no `delegation_hints` led to a stale pipx-served process that had silently
auto-launched a background Tier 2 indexing pass with no user visibility into what "tier"
means or that it was even running.

## Backstory

`intelligence/indexer/ast_indexer.py:141-146,1543-1556` implements tiered indexing for large
repos (≥`_LARGE_REPO_TIER_THRESHOLD` = 10,000 source files): Tier 1 indexes BFS-reachable,
weight≥0.5 files only (fast bootstrap, symbols/AST, embeddings deferred); Tier 2 processes the
rest (`pending_tier2.json` queue) plus deferred FAISS embeddings, in the background.

`interface/cli/init_project.py:1252-1286` auto-launches Tier 2 as a detached `subprocess.Popen`
immediately after Tier 1 completes, with **zero prompt and no explanation of what a tier is or
what tradeoff was just made** — the only visible signal is a one-line
`"Tier 2: N files + FAISS embeddings queued — background indexing started."` after the fact.
Users have no way to choose `--tier all` (full index now, slower but complete) up front, and no
idea their symbol index is partial for however long Tier 2 takes.

Compounding this: the background process is launched via
`_bin_dir = Path(sys.executable).parent` (`init_project.py:1265`) — whichever Python happened
to run `setup`/`index-repo`. If a user later runs `cognirepo setup` under a different install
(pipx vs. editable dev venv vs. global pip), the launched Tier 2 process, and any *future*
implicit re-triggers, resolve against whatever `sys.executable` was that time — not necessarily
the install the user is currently working from. `interface/cli/wizard.py:155-158` already has
an `_is_pipx()` helper for exactly this class of install-detection problem, so the ambiguity is
a known concern in this codebase, just not applied here.

`interface/cli/main.py::_cmd_setup` (the `cognirepo setup` entry point) calls
`init_project(interactive=False, non_interactive=True, ...)` unconditionally
(`main.py:1466-1479`) — so even on a fully interactive terminal, the indexing step inside
`init_project` never prompts for anything, tier included. `interface/cli/wizard.py::run_wizard`
(the actual interactive step sequence, 8 steps) has no tier-related question at all.

## Description

Add an explicit, explained tier-choice step to the setup wizard, shown only when it's a real
decision (repo file count is large enough that tiering would actually kick in — no point asking
on a 200-file repo where the answer is always "all" already). Reuse the wizard's existing
`_ask_choice`/`_section`/`_c` color-box styling (`wizard.py:91-131`) rather than introducing a
new UI dependency — the wizard already renders boxed headers, colored prompts, and animated
enqueue/dequeue sequences (`wizard.py:399-459`), so "astonishing" here means matching and
extending that existing visual language, not bolting on `rich`/`questionary`.

## Acceptance criteria

1. `cognirepo setup` on a repo with ≥10,000 supported source files shows a new wizard step that
   explains, in plain language, the speed-vs-completeness tradeoff and lets the user choose
   between "Tier 1 now + Tier 2 in background" (default, current auto-behavior) and "Full index
   now" — Tier 2 alone isn't offered as a first-run choice since it's a resume-only concept, not
   a meaningful initial decision. Non-interactive/CI runs are unaffected.
2. On a repo below the threshold, the step is skipped entirely (matches current "all" auto
   behavior) — no extra prompt for the common case.
3. The chosen tier flows through to `init_project()`'s `indexer.index_repo(..., tier=...)` call
   and, when the user chose Tier 1, the existing background-launch messaging
   (`init_project.py:1278`) is unchanged; when the user chose "All", no background Tier 2
   process is spawned (nothing left to queue).
4. The background Tier 2 launch resolves the `cognirepo` binary using the same install the
   current process is running from (not a bare `sys.executable`-adjacent guess) — reuse or
   extend `_is_pipx()`-style detection so a background pass launched from one install doesn't
   silently run stale code from a different one.
5. No regression to non-interactive/CI setup (`--no-index`, `non_interactive=True` paths) —
   tier defaults to current auto behavior when no prompt is possible.

## Risks / notes

- AC4 only fixes the *install-resolution* ambiguity for the process this wizard spawns; it does
  not audit every other place `cognirepo serve`/reindex might be manually invoked under the
  wrong install (that's an environment-hygiene issue outside this ticket's scope).
- Not a design tradeoff like D01 — this is a straightforward UX/visibility gap fix, safe to
  implement directly.
