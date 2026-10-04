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
- Not covered: `ast_index.json` / FAISS still save last-writer-wins (remainder of #139).
- Phantom reads across a reload mid-query would need per-request snapshots — a #115 (SQLite WAL) concern.
