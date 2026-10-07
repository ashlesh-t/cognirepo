# Knowledge-graph concurrency (COGNIREPO-137 / COGNIREPO-139)

Several processes share one `.cognirepo/`: an `index-repo` run, the file watcher, one MCP server
per agent (Claude, Gemini, Cursor). This note records how the graph store stays consistent between
them and why.

## Prior art we borrowed from

| System | Mechanism | Used here as |
|---|---|---|
| LevelDB / RocksDB (`LOCK`), Lucene (`write.lock`) | One writer per store, enforced by an OS advisory lock held for the writer's lifetime | **Writer lease** — `journal.WriterLease` (`graph/graph.journal.writer`). The kernel releases it when the holder exits or is killed, so there is no stale-lease cleanup. |
| PostgreSQL WAL, SQLite WAL | The next log position is allocated from the **on-disk tail inside the lock**, never from process memory | `flush_journal()` derives seq from the file tail under `store_lock`; seq is in the frame header so the scan needs no decrypt/unpickle. |
| Git (`index.lock`, ref updates) | Compare-and-swap: if the value changed since you read it, redo your change on the new value rather than overwrite | **Rebase-on-save** — `KnowledgeGraph._rebase()`. |
| SQLite / Postgres MVCC | Readers see a consistent snapshot; writers don't block them | Readers replay only whole, crc-verified segments; they never take the lock. |

## Rules

1. **One journal writer.** `ASTIndexer.index_repo()` → `begin_journal()` acquires the lease. A second
   indexer raises `JournalBusy` (CLI: `indexing is already running (pid N)`, exit 1) or waits
   `indexing.writer_wait_secs`. Journaling off (`indexing.graph_journal: false`) takes no lease; rule 3
   still protects the data.
2. **Sequence numbers are allocated from the disk tail.** Even if the lease were bypassed, seqs cannot
   collide. `graph.pkl` carries `G.graph["journal_seq"]`; replay skips records `<=` it.
3. **No writer overwrites newer disk state.** Every mutation goes through `KnowledgeGraph._do()` and is
   kept in `_pending` until it is on disk (journal flush or `save()`). `save()` holds `store_lock`,
   compares `(graph.pkl, graph.journal)` stamps with what this instance last synced, and if they differ
   reloads the fresh state and re-applies `_pending` (`_rebase`). `reload_if_changed()` does the same for
   readers that have unsaved local ops.

## Collision semantics

| Case | Outcome |
|---|---|
| Write–write, different nodes/edges | Union — both survive. |
| Write–write, same node attribute | Last op applied wins, **per attribute** (other attributes merge). |
| Write–read | A reader sees a prefix of whole segments; never a torn record. |
| Watcher `save()` while an indexer is journaling | Watcher rebases (folds the journal in), compacts it, indexer keeps appending with continuing seqs. |
| Two `index-repo` | Second refused (or queued). |
| Holder killed | Lease auto-released; torn tail truncated by the next writer; flushed segments survive. |

## Limits (deliberate)

- Mutations that bypass the primitives (`kg.G.add_node(...)`) are not in `_pending`, so a rebase will not
  re-apply them. All production code now uses the primitives.
- If more than `_UNSYNCED_OPS_CAP` (200k) ops are pending with no journal, a stale `save()` degrades to
  last-writer-wins with a warning.
- The AST index has its own, per-file rebase — see below.
- Phantom reads across a reload mid-query would need per-request snapshots — a #115 (SQLite WAL) concern.

## AST index and FAISS (`ast_index.json`, `ast.index`, `ast_metadata.json`) — rebase per file

The graph is op-based; the AST index is keyed by file, so it rebases per file instead.

- `ASTIndexer` tracks `_dirty_files` (`"set"` from `index_file()`, `"del"` from `note_file_removed()`).
- `save()` (under `store_lock`) checks whether `ast_index.json` was rewritten since this instance last
  loaded/saved. If so it loads the newer disk state and re-applies only the dirty files onto it, then
  writes. Files only the other writer touched are kept; a file both changed takes the local version.
- `reload_if_changed()` with unsaved local edits rebases them instead of discarding them via `load()`.
- **FAISS ids are positional** (`faiss_id` is the `faiss_meta` index) but the store is an `IndexIDMap2`
  that never reuses an id. A dirty file's vectors are read out of the local index with `reconstruct()`
  (no re-embedding) and appended to the disk index with the next free ids (`len(meta)`); the file's
  symbol records are renumbered. The replaced file's old symbol and file-summary vectors are removed.
- The reverse indexes and `total_symbols` are rebuilt from the merged files.

Limits: a never-synced instance (a from-scratch build that never called `load()`) is not "stale" and
still overwrites, as before; a `compact_faiss()` run on a stale copy is discarded by the rebase (the next
run redoes it); if either FAISS binary is unusable the dirty files' vectors are dropped (`faiss_id = -1`)
rather than mixed; `kg.save()` and `indexer.save()` are still two separate saves.
