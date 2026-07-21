# COGNIREPO-D11 — verify-index/doctor blind to uncommitted working-tree changes under a live watcher

Epic: COGNIREPO-100 · Branch: defect/COGNIREPO-D10_D11_D12 · Base: development

## Backstory
Found running `E2E-100-1` live: with 3 uncommitted mutations present (`git status` showing
R/M/M) and `cognirepo watch` running, `cognirepo verify-index` exited 0 with
`OK 17343 symbols · 4114 files · commit bd7fa60c2413 · indexed ...` — no `DIRTY` line at all.
`cognirepo doctor` showed only 2 unrelated pre-existing warnings (missing API keys,
`graph.pkl.corrupt-<ts>` quarantine) — zero mention of the dirty tree. Both were expected to
catch this: COGNIREPO-104 ("verify-index working-tree staleness detection") added exactly this
check.

Root cause, traced to `interface/cli/main.py`:
- The dirty check (`:258-297`) runs `git status --porcelain` (`:271`) and correctly resolves
  renames (`:277-278`), but only adds a path to `dirty` if
  `os.path.getmtime(path) > indexed_at_ts + 2` (`:281`).
- `indexed_at` is stamped to "now" by *every* `save()` call (`ast_indexer.py`'s manifest
  write), **including the watcher's own incremental saves** — the very save that just indexed
  the uncommitted mutation. So by the time `verify-index` runs, every mutated file's mtime is
  already older than the just-bumped `indexed_at`; the mtime-vs-indexed_at heuristic is
  fundamentally defeated by the exact live-watcher scenario it's supposed to catch.
- `tests/test_verify_index_dirty.py`'s 5 existing scenarios all `time.sleep(2.5)` *before*
  mutating, which simulates "watcher never ran / offline edit" — not "watcher ran and
  refreshed indexed_at." This is an untested gap, not a regression.
- `doctor()` (`:397-678`) has zero `git status`/porcelain calls anywhere and never calls
  `verify-index`'s logic — entirely independent checks (version, FAISS/graph corruption,
  API keys, daemon heartbeat). That's why it showed nothing.

## Description
1. Extract the dirty-check block into a module-level
   `_check_working_tree_dirty(manifest: dict) -> list[str]` in `interface/cli/main.py`.
2. Change the authoritative signal: any supported, existing path present in
   `git status --porcelain` output is dirty unconditionally (after the existing rename
   resolution) — drop the mtime gate as the primary condition, since porcelain is git's own
   ground truth for "differs from HEAD/index" and doesn't race with reindex timing. Keep a
   repo-wide mtime-vs-`indexed_at` scan only as a fallback inside the existing non-git
   `except` branch (porcelain isn't available there).
3. `verify-index`'s call site becomes `dirty = _check_working_tree_dirty(manifest)`, feeding
   the existing print/issue-count logic unchanged.
4. Wire `doctor()` to call the same function and print a non-fatal `WARN` line pointing at
   `cognirepo verify-index` for detail — dirty tree stays a warning in doctor, not a hard
   failure (doctor's exit code semantics are unaffected).

## Acceptance criteria
1. With a live watcher running and 3 uncommitted mutations present (rename, edit, delete),
   `verify-index` exits 1 with a `DIRTY` line naming the affected paths.
2. `doctor` prints a `WARN` line for the same condition, referencing `verify-index`; exit code
   stays 0 apart from genuinely unrelated issues.
3. The 5 existing `test_verify_index_dirty.py` scenarios pass without the `time.sleep(2.5)`
   workaround (now correct for the right reason — porcelain, not mtime timing).
4. New test: mutate then immediately call `save()` (simulating a live watcher, no sleep) —
   dirty check still fires. This is the direct regression test for the bug.
5. Existing test suite green.

## Risks / notes
- Fix second among D10/D11/D12 — independent of D10 (disjoint files: `main.py` vs
  `ast_indexer.py`/`file_watcher.py`), lower severity than D10 (reporting-only, no data
  corruption).
