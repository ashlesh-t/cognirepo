# ADR 002 — Knowledge graph on SQLite (WAL): scope, facade, migration

- **Status:** Accepted. Steps 1-3 are implemented as an **opt-in** backend (`storage.graph_backend: sqlite`);
  the default is still `networkx`. See "As built" below. (Tracked in #115; follows ADR 001 step 6.)
- **Related:** ADR 001 (storage consistency), #109 (graph journal), #116 (per-user daemon),
  #186 (encryption coverage), `docs/architecture/GRAPH_CONCURRENCY.md`

## Context

The knowledge graph is a `networkx.DiGraph` (`KnowledgeGraph.G`) that is **fully resident** in every
process that touches it — each `cognirepo serve`, the watcher, the CLI. It is persisted as one pickle
(`graph.pkl`) plus an append-only journal (#109) that makes long index runs resumable. The journal
and rebase-on-save (`GRAPH_CONCURRENCY.md`) made it *correct* under concurrency, but not *small*:
memory grows with graph size × number of processes, and every save rewrites the whole graph.

ADR 001 already classifies the graph as **Class 2 (derived, rebuildable)**, and lists "move the
graph onto SQLite (#115)" as step 6. This ADR fixes what that means concretely, because the
direct-access surface is wider than "swap the storage".

### What actually touches `G`

Outside `KnowledgeGraph` itself, production code reaches into `kg.G` ~65 times (the org graph,
`data/graph/org_graph.py`, is a separate class and out of scope). The operations are few and all
reads except the journalled primitives:

| Operation | Typical caller |
|---|---|
| `G.number_of_nodes()` / `number_of_edges()` | emptiness / health checks (`mcp_server`, `prime_session`, `hybrid`) |
| `G.nodes()` (iterate, filter by id prefix / attrs) | symbol and file lookups in `mcp_server`, `ast_indexer` |
| `G.successors(n)` / `G.predecessors(n)` | `who_calls`, caller/callee walks |
| `G.has_node` / `has_edge` / `get_edge_data` | existence + edge attribute reads |
| `G.degree()` / `in_degree()` | hot-symbol ranking (`prime_session`) |
| `G[n]` adjacency, `to_undirected()` | `subgraph_around`, `shortest_path` |

Writes already funnel through `KnowledgeGraph` primitives (`add_node`, `add_edge`, `remove_node`,
`remove_edge`, `set_node_attrs`, `set_edge_attrs`, `remove_file_nodes`) — the journal required that.

## Decision

1. **Introduce a read facade first, change storage second.** Add the operations above as methods
   on `KnowledgeGraph` (`node_count()`, `edge_count()`, `iter_nodes(prefix=None, node_type=None)`,
   `successors(n)`, `predecessors(n)`, `edge_data(a, b)`, `degree(n)`, `top_by_in_degree(k)`), and
   migrate the ~65 call sites to them. Behaviour is unchanged (the facade delegates to
   `self.G`); this is a mechanical, reviewable PR that removes the real blocker. After it, `.G`
   is private.
2. **A `GraphStore` backend interface** behind `KnowledgeGraph`, with two implementations:
   `NetworkXStore` (today's behaviour, default) and `SqliteStore`. Selected by
   `storage.graph_backend: "networkx" | "sqlite"`.
3. **SQLite schema** (one file, `graph/graph.sqlite`, WAL):

   ```sql
   CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT NOT NULL, file TEXT, attrs TEXT);   -- attrs: JSON
   CREATE TABLE edges (src TEXT NOT NULL, dst TEXT NOT NULL, rel TEXT NOT NULL,
                       weight REAL NOT NULL DEFAULT 1.0, attrs TEXT,
                       PRIMARY KEY (src, dst));                       -- DiGraph: one edge per ordered pair
   CREATE INDEX edges_dst ON edges(dst);                              -- predecessors / in-degree
   CREATE INDEX nodes_file ON nodes(file);                            -- remove_file_nodes, nodes_for_file
   CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);              -- schema_version, complete flag
   ```
   `PRIMARY KEY (src, dst)` mirrors `nx.DiGraph` semantics, so edge-merge behaviour does not change.
4. **Bounded memory.** Queries are SQL (`COUNT(*)`, indexed adjacency, `ORDER BY in-degree LIMIT k`).
   `subgraph_around` / `shortest_path` run a bounded BFS over neighbour queries with a small LRU of
   hot adjacency lists (default 10k entries), never materialising the graph. Nothing loads the whole
   graph, including `integrity_report`.
5. **Concurrency.** SQLite WAL gives what `GRAPH_CONCURRENCY.md` built by hand: snapshot readers that
   never block, one writer at a time. The mapping:
   - *Writer lease* (`WriterLease`) stays for index runs (it also guards FAISS/AST), but the graph no
     longer needs its own.
   - *Rebase-on-save* becomes a **transaction**: each logical operation (e.g. `remove_file_nodes` +
     re-add) is one `BEGIN IMMEDIATE … COMMIT`; there is no stale in-memory state to overwrite, so
     the whole `_rebase` / `_pending` / `_UNSYNCED_OPS_CAP` machinery disappears for this backend.
   - *Journal* is unnecessary: committed batches are durable, so a killed `index-repo` resumes from
     the committed rows. Batch size = the current flush cadence (`graph_journal_flush_files`).
   - *Conditional prune* (`remove_node_if_degree_at_most`) is a single `DELETE … WHERE degree <= ?`
     inside the transaction, so a concurrent writer's new edge cannot be lost.
   - `synchronous=NORMAL` (Class 2: a lost last commit costs a re-index of a few files, not data).
6. **Migration.** Opt-in first. `graph_backend: "sqlite"` on a repo with only `graph.pkl` runs an
   idempotent importer (stream nodes then edges in batches; write `meta.complete=1` last). The pkl
   is kept untouched as the fallback for one release; reverting the flag reads it again. A graph
   that fails an integrity check (`integrity_report`) is rebuilt by `index-repo` rather than
   repaired in place. After one release with no regressions, `sqlite` becomes the default and
   `graph.pkl` is only read by the importer.
7. **Encryption.** `storage.encrypt` currently covers `graph.pkl` and the journal. A SQLite file is
   **not** covered by Fernet. Until #186 decides the approach (SQLCipher, per-row encryption of
   `attrs`, or documenting OS-level disk encryption), `storage.encrypt: true` **forces the
   `networkx` backend** and `doctor` says so. This keeps the SECURITY.md promise true; it is the
   conservative choice and it is explicit, not silent.

## Alternatives considered

- **Keep NetworkX, load lazily per subgraph from the pickle.** A pickle cannot be partially read;
  we would reinvent a store. Rejected.
- **Embedded graph DB (Kùzu, etc.).** Adds a heavyweight native dependency for a graph that is
  nodes + typed edges with 1–3 hop queries. SQLite is already in the stdlib and already in
  ADR 001's plan for Class 1.
- **Do #115 and #116 together.** The daemon makes one *process* hold one graph, which already cuts
  memory ×N; SQLite cuts memory per process and removes whole-graph saves. They are independent
  and each pays off alone; coupling them delays both. SQLite first because it needs no new
  process model.
- **Migrate the journal format instead.** Leaves resident-memory growth untouched, which is the
  actual complaint.

## Consequences

- Positive: resident memory stops scaling with graph size; saves become O(changed rows);
  `graph.pkl.corrupt-*` quarantine and the `_rebase` code path go away on this backend; readers can
  be fully lock-free (and the control API's read-only constraint, #129, is satisfied by
  opening the DB `mode=ro`).
- Negative: two backends to test for a release; graph algorithms that relied on `nx` (`to_undirected`,
  `shortest_path`) are reimplemented as bounded queries; encrypted repos stay on the old backend until
  #186.
- Risk: query latency regression on very hot paths (`who_calls` fan-out). Mitigated by the adjacency
  LRU and measured in the benchmark PR before the default flips.

## As built (#115)

Where the implementation departs from, or settles, what is written above:

* **No separate `GraphStore` class hierarchy.** After step 1 `KnowledgeGraph` *is* the interface: a read facade,
  seven mutation primitives and a handful of persistence entry points (`save`, `load`, `reload_if_changed`,
  `begin_journal` / `end_journal` / `flush_journal` / `maybe_flush`). Moving ~700 lines of journal and rebase
  code into a `NetworkXStore` would have been churn with regression risk for no behavioural gain, so
  `SqliteGraph` **subclasses** `KnowledgeGraph` and overrides those entry points, and `KnowledgeGraph()` returns the
  configured backend (`data/graph/backend.py`, dispatch in `__new__`), so none of the ~50 construction sites
  changed. The interface is pinned by a conformance suite instead (`tests/test_graph_backends.py`): one scenario
  through the public surface on both backends, every read compared, plus a guard that no method which reads
  `self.G` is inherited by the SQLite class. If a third backend ever appears, extracting the interface is mechanical.
* **Schema.** As §3, with `type`, `rel` and `weight` nullable (networkx creates attribute-less endpoints on
  `add_edge` and allows unlabeled edges; older graphs have them), graph attributes (`complete`) in `meta` as
  `ga:<key>`, and rows read back in insertion order (`ORDER BY rowid`, edges grouped by source) so results match
  networkx's iteration order. Attribute values are JSON: tuples come back as lists, sets as sorted lists.
* **Import is one transaction** (stronger than "write `meta.complete` last"): other processes see no graph until it
  commits, a kill leaves nothing behind, and `meta.import_state` makes it idempotent. It only runs into an empty
  database, never over rows written since. `graph.pkl` and the journal are read, never modified.
* **Transactions.** A write transaction starts lazily at the first mutation and is committed by `save()`, by each
  flush of an index run (at most every 5 s, so other writers wait seconds, not for the whole run), after 5 s of
  inactivity, and after 60 s of continuous activity outside an index run. A forgotten `save()` therefore cannot hold
  the write lock against other processes (the pickle backend would have lost those changes; this one keeps them).
* **Locking.** A writer that finds the database locked retries for up to 150 s in total (30 s per attempt), longer
  than the longest transaction (60 s) another process may legitimately hold, instead of failing.
* **Switching back and forth is not synced.** The pickle is imported once and kept as a fallback, so changes made
  under one backend are not visible to the other; `doctor` warns when both files exist and the unused one is newer.
* **Searches are bounded**: `shortest_path` / `hop_distance` / the undirected view are bidirectional BFS capped at
  16 hops and 20 000 visited nodes, `subgraph_around` batches its queries. Beyond the cap the answer is "not
  connected", which retrieval already treats as "far away".
* **Open questions settled.** (1) `synchronous=NORMAL` accepted: the graph is class-2 data. (2) The adjacency LRU
  is 10 000 lists per direction, per connection (not shared; with the daemon (#116) there is one graph per repo
  worker anyway). (3) Encryption: `storage.encrypt: true` forces `networkx` and `doctor` says so; SQLite stays
  non-default until #186.
* **Unchanged on purpose:** the index-run writer lease (`JournalBusy`), the `graph.delta` / `graph_seq` change feed
  (one batch per commit, #209), `graph.stats`, the control API. `OrgGraph` is a separate class and untouched.

### Switching and migrating (follow-up)

`cognirepo graph migrate --to networkx|sqlite` (`data/graph/migrate.py`) and the console's Controls page make the backend a
product choice instead of a hand-edited config key. Order of operations: take the index writer lease; set an existing target
aside as `.replaced-<ts>` (a pickle's journal with it, or it would replay over the new file); copy (networkx -> sqlite is the
importer above, sqlite -> networkx streams into a fresh pickle); **verify** (node and edge counts, graph attributes, a sample
of attributes read back from the target); only then change `storage.graph_backend`. Any failure undoes the copy and restores
what was set aside; the source is never modified. The console's toggle goes through the same engine and never flips onto a
missing or older graph. Running agents, the watcher and cached retrievers rebuild their graph when the setting no longer
matches the backend they were built for (`backend.is_current`). Whether the unused store has changed since the two last matched is tracked with a small sync record (`graph/backend_sync.json`,
each file's mtime, written after every verified migration), not by comparing mtimes, which cannot tell "written since" from
"copied later". `backend.recommend()` encodes the rough guidance (networkx for
small graphs / one session / encryption; SQLite from about 100k nodes, or 20k+ nodes with 3+ attached processes); the
thresholds come from the single synthetic benchmark below and are advice, not rules. Migrating that benchmark graph
(105k nodes, 1.28M edges) takes about 6 s in either direction and peaks at about 1.0 GB of RSS (roughly 2.3x the resident
graph: the copy holds the graph once and the verification loads the result again), so `--dry-run` reports a memory estimate
before anything is touched. The sqlite -> networkx export interns node ids; without that the pickle was twice the size
(135 MB vs 70 MB) and the peak 1.6 GB.

### Measurements

`scripts/bench_graph_backends.py --nodes 100000 --degree 6`: a synthetic code graph (105 000 nodes, 1.28 M edges:
symbols with locality-biased calls and a few hubs), each backend measured in its own process on an otherwise idle
machine (Linux, Python 3.14). "Open" is a fresh process, which is what every `serve` and CLI call is.

| | networkx (`graph.pkl`) | sqlite (`graph.sqlite`) |
|---|---|---|
| build + save (s) | 6.4 | 11.5 |
| build peak RSS (MB) | 510 | 63 |
| disk (MB) | 63 | 255 |
| open (s) | 0.58 | 0.00 |
| RSS after open (MB) | 459 | 54 |
| RSS after 2 000 `successors` + 300 `subgraph_around` + 200 `hop_distance` (MB) | 459 | 92 |
| `successors` p50 / p95 (ms) | 0.002 / 0.003 | 0.009 / 0.013 |
| `subgraph_around(r=2)` p50 / p95 (ms) | 0.57 / 0.70 | 3.8 / 5.2 |
| `hop_distance` p50 / p95 (ms) | 0.10 / 0.25 | 1.2 / 3.3 |

Reading it: memory per process stops scaling with the graph (about 5x less here; the 10 000-symbol run below
shows a much smaller gap),
opening is free, and a query costs microseconds to a few milliseconds instead of sub-millisecond. The price is
**disk (about 4x: node ids are repeated in the edge table and its two indexes; interning ids as integers
should cut that substantially, at the cost of a join on every read — not tried)** and a slower bulk build. A 10 000-symbol graph
shows the same shape (RSS 83 vs 70 MB, `subgraph_around` 0.5 vs 3.7 ms). The graph is synthetic; real repositories
differ in degree distribution, so trust the shape, not the numbers.

**Not measured:** concurrent writers under contention, a repository with millions of edges, Windows/macOS file
locking, a cold disk cache. **Flipping the default is deliberately not part of this change**; it needs a release of
soak time and a decision on integer ids and encryption (#186).

## Delivery plan (separate PRs, each independently reviewable)

1. **Facade** — done (#205). `KnowledgeGraph` read methods + migrate call sites; `.G` is private.
2. **Interface + conformance suite** — done (#115): the facade is the interface (see "As built"); the suite both
   backends must pass is `tests/test_graph_backends.py`.
3. **`SqliteGraph`** + importer + `storage.graph_backend` flag + `doctor` checks — done (#115). Default stays `networkx`.
4. **Benchmarks and soak** — benchmark and kill-9 mid-index resume done (#115); soak and flipping the default are open.
5. **Behaviour data** (`behaviour.json`) on the same DB — open: separate, smaller PR (ADR 001 Class 1 order).

## Open questions (need a decision before PR 3)

1. Is `synchronous=NORMAL` acceptable, or does the graph share a DB (and therefore `FULL`) with
   Class 1 data later?
2. Default adjacency-LRU size, and whether it should be shared across stores in the daemon (#116).
3. #186: which encryption approach for SQLite files (blocks making `sqlite` the default for
   `storage.encrypt: true` users).
