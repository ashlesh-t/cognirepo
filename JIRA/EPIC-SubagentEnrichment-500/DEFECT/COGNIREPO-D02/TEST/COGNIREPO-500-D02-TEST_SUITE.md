# COGNIREPO-500-D02 — manual test suite

## TC-D02-1: Tier prompt shown and explained on a large repo
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced/kubernetes (18,504 supported
  source files post skip_dirs — confirmed via `_count_source_files`, well over the 10k-file
  threshold. Note: moby's file count is only 2,230 after vendor/-exclusion — its 77k figure
  from COGNIREPO-500-D01 is knowledge-graph *node* count, a different metric, and does NOT
  cross this threshold — use kubernetes for these cases, not moby.)
- Prerequisites / setup steps: fresh `.cognirepo/` (rename or remove existing one first so
  `cognirepo setup` runs the full wizard, not a re-init short path); use the dev venv install
  (`/home/ashlesh/my_works/cognirepo/venv/bin/cognirepo`), not pipx/PyPI.
- What to do: run `cognirepo setup` interactively in a real TTY, walk through the wizard to the
  new indexing-tier step.
- Prompt: "Run `cognirepo setup` in kubernetes and go through the wizard. When it asks about
  indexing tier, read the explanation and tell me if Tier 1/Tier 2/All are each explained
  clearly enough to choose without reading the source."
- Expected results: a boxed/colored step (matching the existing wizard's `_section`/`_ask_choice`
  style) appears with two options — "Tier 1 now, Tier 2 in background" (default, matches current
  auto-behavior) and "Full index now (all tiers)" — each with a plain-language explanation of
  the speed/completeness tradeoff. (Tier 2 alone is not offered as a first-run choice — it's a
  resume-only concept for an already-started Tier 1 pass, not a meaningful initial decision.)
- Obtained results:
- Verdict:

## TC-D02-2: Step skipped on a small repo
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy (well under 10k files)
- Prerequisites / setup steps: fresh `.cognirepo/`.
- What to do: run `cognirepo setup` interactively.
- Prompt: "Run `cognirepo setup` in the easy test repo and tell me if it asks about indexing
  tier at all."
- Expected results: no tier step appears; setup proceeds exactly as before this change
  (full index, no tiering).
- Obtained results:
- Verdict:

## TC-D02-3: Chosen tier actually reaches the indexer
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced/kubernetes
- Prerequisites / setup steps: fresh `.cognirepo/`.
- What to do: run `cognirepo setup`, pick "All" at the tier step; after it completes, check
  `.cognirepo/index/` for whether `pending_tier2.json` was written (it shouldn't be, since
  nothing was deferred) and confirm no background `cognirepo index-repo --tier 2` process was
  spawned (`ps aux | grep cognirepo`).
- Prompt: (executed directly, not a live-agent prompt)
- Expected results: no `pending_tier2.json`, no background indexing process; symbol/embedding
  index is immediately complete.
- Obtained results:
- Verdict:

## TC-D02-4: Background Tier 2 resolves the correct install
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced/kubernetes
- Prerequisites / setup steps: fresh `.cognirepo/`; a pipx (or otherwise unrelated) `cognirepo`
  install present on PATH/at a different version than the dev venv — confirms the test can
  actually distinguish installs (e.g. `pipx list | grep cognirepo` shows a different version
  than `/home/ashlesh/my_works/cognirepo/venv/bin/cognirepo --version`). Run `cognirepo setup`
  from the dev venv binary (`/home/ashlesh/my_works/cognirepo/venv/bin/cognirepo`), pick "Tier 1"
  at the tier step.
- What to do: after setup completes and Tier 2 auto-launches in the background, inspect the
  spawned process's command line (`ps aux | grep "interface.cli.main.*index-repo.*tier.*2"`).
- Prompt: (executed directly, not a live-agent prompt)
- Expected results: the spawned process is `<dev venv python> -m interface.cli.main index-repo
  ... --tier 2 --no-watch`, where `<dev venv python>` is
  `/home/ashlesh/my_works/cognirepo/venv/bin/python3` (`sys.executable` of the process that ran
  `setup`) — confirmed via `readlink -f /proc/<pid>/exe` matching the venv interpreter, not a
  pipx or unrelated install. The fix (COGNIREPO-500-D02) invokes `sys.executable -m
  interface.cli.main` directly instead of searching for a colocated/PATH `cognirepo` binary, so
  there's no binary-resolution step left to go wrong regardless of whether a `cognirepo` console
  script happens to sit next to the running interpreter.
- Obtained results: ran `init_project(tier=None)` from the dev venv
  (`/home/ashlesh/my_works/cognirepo/venv/bin/python3`) against a fresh `.cognirepo/` on
  kubernetes (23,142 files indexed, Tier 1 pass ~61min). Console output:
  `Tier 2: FAISS embeddings queued — background indexing started
  (/home/ashlesh/my_works/cognirepo/venv/bin/python3).` `ps aux` confirmed the spawned process:
  `/home/ashlesh/my_works/cognirepo/venv/bin/python3 -m interface.cli.main index-repo
  /home/ashlesh/my_works/cognirepo_test_repo/advanced/kubernetes --tier 2 --no-watch` — matches
  `sys.executable` of the process that ran `setup`/`index-repo`, no colocated-binary or PATH
  lookup involved.
- Verdict: PASS

## TC-D02-4b: No colocated `cognirepo` binary — still resolves the correct install
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced/kubernetes
- Prerequisites / setup steps: fresh `.cognirepo/`; regression case for the original bug — run
  `setup` via a bare interpreter invocation that has *no* `cognirepo` console script next to it,
  e.g. `/home/ashlesh/my_works/cognirepo/venv/bin/python3 -m interface.cli.main setup` (confirm
  first there's no `cognirepo` file in that same `bin/`, or temporarily rename it aside). Pick
  "Tier 1" at the tier step.
- What to do: after setup completes, inspect the spawned Tier 2 process the same way as
  TC-D02-4.
- Prompt: (executed directly, not a live-agent prompt)
- Expected results: Tier 2 still launches under the dev venv interpreter (`sys.executable`),
  identical to TC-D02-4 — no PATH fallback, no warning about a missing colocated binary, no
  risk of resolving to pipx or another install. (Before the fix, this was exactly the scenario
  that fell through to a bare `shutil.which("cognirepo")` PATH lookup and could silently resolve
  to a different install — reproduced during review: with no colocated binary, the old fallback
  resolved to `/home/ashlesh/.local/bin/cognirepo` → pipx cognirepo 2.2.0, not the dev venv's
  2.0.0.)
- Obtained results: superseded by the TC-D02-4 fix — `init_project.py` no longer looks for a
  colocated or PATH `cognirepo` binary at all, it invokes `sys.executable -m interface.cli.main`
  unconditionally, so this scenario can't diverge from TC-D02-4 by construction. Confirmed no
  `Path(sys.executable).parent / "cognirepo"` pattern remains anywhere in the CLI — also fixed
  the same pattern at two other Tier-2-launch call sites in `main.py` (interactive Tier-2 prompt,
  `index-repo`'s own auto-launch) that had it independently, outside this ticket's original diff
  but the same class of bug.
- Verdict: PASS

## TC-D02-5: Non-interactive/CI setup unaffected
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced/kubernetes
- Prerequisites / setup steps: fresh `.cognirepo/`.
- What to do: `cognirepo index-repo . --no-watch` directly (non-interactive path, not through
  the wizard) — confirm no tier prompt appears and current auto-tiering behavior (Tier 1 +
  background Tier 2 for large repos) is unchanged.
- Prompt: (executed directly, not a live-agent prompt)
- Expected results: no prompt, identical output/behavior to before this change.
- Obtained results:
- Verdict:
