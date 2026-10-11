# ADR 001 — Storage consistency model: ACID tiers per data class

- **Status:** Proposed (to ratify; tracked in #143, part of the data-integrity epic #130)
- **Unblocks:** SQLite store (#115)
- **Related:** #109 (graph journal), #116 (per-user daemon), #134–#139 (integrity fixes), #140 (generation pointer)

## Context

Several processes share one `.cognirepo/` directory: the file watcher, one `cognirepo serve`
per agent (Claude, Gemini, Cursor), the CLI and `index-repo`. Until the integrity epic, stores
were rewritten in place or by read-modify-write on JSON/pickle files, which produced torn files
(#134), lost updates and duplicate ids (#136), journal sequence collisions (#137), and mixed
reads across the files of one logical store (#140).

"Do we need ACID with transactions?" has no single answer, because the data falls in two
classes with different value and different recovery options.

## Decision

Consistency is chosen **per data class**, not blanket.

### Class 1 — Primary data: full ACID

*Memories, episodic events, learnings, decisions, behaviour/profile, project memory.*
This data is the only copy; losing or corrupting it is unrecoverable.

- Store: **SQLite in WAL mode** — serialisable writers (one at a time, enforced by SQLite),
  snapshot readers that never block writers. Replaces the JSON/pickle read-modify-write stores.
- Atomicity: every logical operation (e.g. "store memory" = vector row + metadata row + dedup
  check) is one transaction. No operation spans files.
- Durability: `synchronous=FULL` for the primary DB; fsync is not optional here.
- Until it lands: the existing `store_lock()` + locked RMW + `core.config.atomic` writes remain
  in force (they are correct, just coarse).

### Class 2 — Derived, rebuildable data: atomic publish + snapshot isolation

*AST index (`ast_index.json`, `ast.index`, `ast_metadata.json`, `manifest.json`), the semantic
FAISS index + metadata, the code graph.* All of it can be regenerated from source with
`cognirepo index-repo`.

- A group of files that must be read together is **published as a generation**
  (`core/config/generation.py`): written to a scratch directory, fsynced, renamed to `gen-N/`,
  then made current by atomically replacing a `CURRENT` pointer.
- Readers pin the generation named by `CURRENT` and read only inside it — **snapshot isolation
  without reader locks**: no torn reads (half-written file) and no mixed reads (new json with
  old FAISS).
- A crash at any step leaves the previous generation intact and current; orphaned scratch
  directories are swept.
- Old generations are removed by the next writer after a grace period, always keeping the
  newest few, so a slow reader is never pulled out from under.
- Durability is *optional*: a lost generation costs a re-index, not data. (fsync is still done —
  it is cheap relative to indexing — but it is not a correctness requirement.)
- Writers still serialise on `store_lock()`; this is "single writer, many snapshot readers".

### Journal (#109)

The graph journal is the crash-recovery mechanism for **long index runs** (resume instead of
restart) until Class 1 moves to SQLite. It is not a transaction log for primary data.

### Reader/writer rules (normative)

These come from the integrity epic and are now binding on new code:

1. **Writers** replace files only through `core.config.atomic` (never `open(path, "w")` on a
   live store) and hold `store_lock()` for any read-modify-write or multi-file group. Enforced
   by `tests/test_atomic_writes.py`.
2. **Readers never modify.** Loading must not rename, quarantine or rewrite a file that fails to
   parse — the failure may be a concurrent writer (#135). Only a writer, under the lock, after
   the file stays unreadable *and* unchanged, quarantines it.
3. **Never overwrite a store you failed to load** with an empty in-memory fallback.
4. **Multi-file stores are read from one generation** (or one DB snapshot), never file by file.
5. **Sample the freshness stamp before reading**, so a write that lands mid-load is picked up on
   the next check rather than recorded as current.
6. **One journal writer** at a time (`WriterLease`); sequence numbers come from the on-disk tail
   under the lock.

### Explicitly rejected

- **ElasticMQ / LocalStack / external brokers** and **a general-purpose scheduler**: they add
  a service to install and operate for a local, single-user tool. A single writer plus an
  in-process FIFO inside the per-user daemon (#116) provides all the ordering we need.
- **Blanket ACID for derived data**: transactional machinery around data that is rebuilt from
  source buys nothing the generation pointer does not already give.
- **Reader locks**: they make a slow or crashed MCP server able to block indexing.

## Consequences

- AST index and semantic store: implemented (#140). On disk, `index/ast.gen/gen-N/` and
  `vector_db/semantic.gen/gen-N/` hold the groups and a `CURRENT` file beside them names the live
  one. The flat `index/ast_index.json`, `ast.index`, `ast_metadata.json`, `manifest.json`,
  `vector_db/semantic.index` and `memory/semantic_metadata.json` are **hard links** to the current generation's files,
  so `verify-index`, `doctor` and other tools that open them directly keep working with no extra
  disk. A flat file that is *not* a link into any generation (hand-edited, or a pre-#140 index)
  is read as-is until the next save. Where hard links are unavailable the flat files are copies
  and in-process readers still use the generation.
- Disk usage is up to `keep` (3) generations of the AST group while old ones are inside the
  grace period.
- Quarantined AST files now land inside the generation directory they were found in.

## Migration plan (ordered)

1. **Done** — atomic single-file writes (#134), side-effect-free readers (#135), locked RMW
   (#136), journal writer lease (#137), watcher singleton (#138), AST rebase (#139).
2. **Done** — generation pointer for the AST group (#140).
3. **Done** — same generation pointer for `semantic.index` + `semantic_metadata.json`
   (`core/vector_db/local_vector_db.py`, `ops/cron/prune_memory.py`), reusing `GenerationStore`.
   Metadata-only changes (behaviour score, soft-delete, suppress) hard-link the unchanged index
   into the new generation instead of rewriting it.
4. Ratify this ADR; unblocks #115.
5. SQLite WAL schema + one-shot importer for each Class 1 store, in this order (smallest blast
   radius first): learnings → decisions → episodic → project memory → behaviour/profile →
   memories. Each step ships behind a feature flag with the old store as the fallback reader for
   one release, and the importer is idempotent.
6. Move the knowledge graph onto SQLite (#115); retire the graph journal's role beyond index-run
   resume.
7. Per-user daemon (#116) owns the single writer + in-process FIFO; CLI/MCP become clients.
   Remove `store_lock()` from Class 1 paths once nothing else writes them.
