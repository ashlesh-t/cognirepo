# COGNIREPO-D12 — No persistent trail of watcher-driven reindex activity

Epic: COGNIREPO-100 · Branch: defect/COGNIREPO-D10_D11_D12 · Base: development

## Backstory
Found running `E2E-100-1` live: after burst-saving a file 5x in under 1 second with
`cognirepo watch` running, `.cognirepo/index/last_indexed.json` was unchanged (its timestamp
pre-dated the burst), `.cognirepo/bg_tasks/` was empty, and no watcher log file existed
anywhere — yet `ast_index.json` *was* correctly, silently updated in place. The mutation
happened; there is no durable trail that it happened.

Root cause: this is partly a test-expectation mismatch, not a missing feature —
`last_indexed.json` (`interface/cli/main.py:2097-2109`, `_write_last_indexed_sha`) is a
git-HEAD-SHA marker written only by the CLI `index-repo` command; it was never wired to the
watcher. `.cognirepo/bg_tasks/` (`interface/tools/bg_progress.py`) is the unrelated Tier-2
background-embedding progress queue. Both are structurally the wrong artifacts to check for
watcher activity. However, the underlying gap is real: `flush()`
(`intelligence/indexer/file_watcher.py:133-186`) only does bare `print()` (`:161`, `:186`) for
its own activity — invisible unless `cognirepo watch` was started in daemon mode (which
redirects stdout to `.cognirepo/watchers/<session>.log` via `interface/cli/daemon.py:288-359`).
In foreground mode, there is no log by design, so debugging "did the watcher actually process
my save" has no artifact to check regardless of mode.

## Description
In `flush()`, after `self.graph.save()`, write (overwrite) a small
`.cognirepo/index/last_watcher_reindex.json` containing
`{"timestamp": <iso>, "session_id": <str>, "reindexed": [rel_paths...], "removed": [rel_paths...]}`.
Last-write-wins — no unbounded log growth, negligible cost added to a call that already does a
full `indexer.save()` + `graph.save()`.

## Acceptance criteria
1. After any watcher-triggered `flush()` (foreground or daemon mode),
   `.cognirepo/index/last_watcher_reindex.json` exists and reflects the most recent batch
   (timestamp, session id, reindexed/removed paths).
2. File is overwritten (not appended) on each flush — file size stays bounded regardless of
   watcher uptime.
3. Existing test suite green; new test asserts the file is written/updated after `flush()`.

## Risks / notes
- Fix last among D10/D11/D12 — smallest, no dependency on the other two.
- Does not attempt to also wire `last_indexed.json` or `bg_tasks/` into the watcher path —
  those remain correctly scoped to CLI `index-repo` and Tier-2 embedding respectively; this
  ticket only adds a new, watcher-specific artifact rather than repurposing the wrong ones.
