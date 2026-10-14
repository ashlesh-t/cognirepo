# ADR 002 — Knowledge graph on SQLite (WAL): scope, facade, migration

- **Status:** Proposed (tracked in #115; follows ADR 001 step 6)
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

## Delivery plan (separate PRs, each independently reviewable)

1. **Facade** — `KnowledgeGraph` read methods + migrate call sites; `.G` becomes private. No behaviour
   change. *(Unblocks everything; can merge alone.)*
2. **`GraphStore` interface** + `NetworkXStore` extraction; conformance test suite that both backends
   must pass (same fixtures, same expected results).
3. **`SqliteStore`** + importer + `storage.graph_backend` flag + `doctor` checks. Default stays `networkx`.
4. **Benchmarks and soak**: RSS vs graph size, `who_calls` / `context_pack` latency, kill-9 mid-index
   resume. Flip the default only if no regression.
5. **Behaviour data** (`behaviour.json`) on the same DB — separate, smaller PR (ADR 001 Class 1 order).

## Open questions (need a decision before PR 3)

1. Is `synchronous=NORMAL` acceptable, or does the graph share a DB (and therefore `FULL`) with
   Class 1 data later?
2. Default adjacency-LRU size, and whether it should be shared across stores in the daemon (#116).
3. #186: which encryption approach for SQLite files (blocks making `sqlite` the default for
   `storage.encrypt: true` users).
