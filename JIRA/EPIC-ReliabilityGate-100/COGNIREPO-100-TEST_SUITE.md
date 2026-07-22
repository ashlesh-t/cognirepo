# COGNIREPO-100 — Epic e2e test suite (cross-story flows only)

Story-level suites cover each fix in isolation; these verify the epic works as a whole.

## E2E-100-1: Fresh index → live edit lifecycle stays consistent (crosses 102+103+104+D02)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: epic branch merged into development; `cognirepo init && cognirepo index-repo .`
  in the test repo; `cognirepo watch` (or serve) running.
- What to do: (1) burst-save one source file 5× in <1 s; (2) `git mv` another indexed file;
  (3) delete a function from a third file and save; (4) run `cognirepo verify-index` with one
  uncommitted edit present; (5) run `cognirepo doctor`.
- Prompt (to Claude with CogniRepo MCP connected):
  "Use lookup_symbol to find <renamed_symbol> and <deleted_function>, then run graph_stats.
  Report exactly what the index returns."
- Expected results: one reindex logged for the burst; renamed symbol found at new path only;
  deleted function absent from lookup AND no orphan node counted; verify-index exits 1 with a
  DIRTY line; doctor green apart from the intentional dirty warning.
Obtained results (verified against filesystem/pickle, not just tool text):
E2E-100-1 — Obtained Results

Setup deviation (required before the test was valid)

The watcher daemon found running (PID 13408) had started 2026-07-21 23:39, but the epic fix commit 6e4a833 (D13–D16) landed 2026-07-22 01:09. Since pipx installs cognirepo editable against /home/ashlesh/my_works/cognirepo, the on-disk code was current but the daemon held pre-fix code in memory — its log showed the exact crash D13–D16 fixes (FileNotFoundError … ast_index.json.tmp in _atomic_json_dump, ast_indexer.py:2087). I stopped it and started a fresh watcher (PID 330459) on the merged code. All results below are from the merged build.

Step-by-step obtained results

┌─────┬─────────────────────┬─────────────────────────────────────────┬──────────┐
│  #  │        Step         │                Obtained                 │ Verdict  │
├─────┼─────────────────────┼─────────────────────────────────────────┼──────────┤
│     │                     │ 5 writes in 0.001 s → exactly one       │          │
│ 1   │ Burst-save color.py │ reindex; last_watcher_reindex.json      │ PASS     │
│     │  5×                 │ lists 1 file, "error": null; single     │          │
│     │                     │ index mtime 00:51:45; no exceptions     │          │
├─────┼─────────────────────┼─────────────────────────────────────────┼──────────┤
│     │                     │                                         │ PASS     │
│ 2   │ git mv hashing.py → │ Audit: reindexed:[hashing_renamed.py],  │ (disk) / │
│     │  hashing_renamed.py │ removed:[hashing.py]                    │  FAIL    │
│     │                     │                                         │ (MCP)    │
├─────┼─────────────────────┼─────────────────────────────────────────┼──────────┤
│     │ Delete              │                                         │ PASS     │
│ 3   │ deduplicate_list    │ Reindexed, error: null                  │ (disk) / │
│     │ from helpers.py     │                                         │  FAIL    │
│     │                     │                                         │ (MCP)    │
├─────┼─────────────────────┼─────────────────────────────────────────┼──────────┤
│ 4   │ verify-index with   │ Exit 1, DIRTY 3 uncommitted indexed     │ PASS     │
│     │ dirty tree          │ source file(s) + file list              │          │
├─────┼─────────────────────┼─────────────────────────────────────────┼──────────┤
│     │                     │ 3 warnings, no errors — dirty warning   │          │
│ 5   │ doctor              │ present, but 2 extra warnings + wrong   │ PARTIAL  │
│     │                     │ PID                                     │          │
└─────┴─────────────────────┴─────────────────────────────────────────┴──────────┘

The specified MCP prompt — what the index actually returned

lookup_symbol("secure_hash_s")   → lib/ansible/utils/hashing.py:34      ← STALE (renamed-away path)
lookup_symbol("deduplicate_list")→ lib/ansible/utils/helpers.py:44      ← STALE (deleted function)
graph_stats → nodes 17593, edges 96427, index_age_minutes 0,
              index_stale false, watcher_alive true

Both expected results failed through MCP. But verification against disk proves the pipeline is correct:

On-disk ast_index.json (authoritative):
- hashing.py in files dict: False (purged) ✓
- reverse_index["secure_hash_s"] → [["lib/ansible/utils/hashing_renamed.py", 34]] — new path only ✓
- reverse_index["deduplicate_list"] → null ✓

Decrypted graph.pkl (Fernet gAAAAA…, decrypted via core.security.encryption):
- helpers.py::deduplicate_list node gone; only legit test_helpers.py::test_deduplicate_list remains ✓
- All hashing.py::* nodes purged; only hashing_renamed.py::* present ✓
- True orphans (degree 0): 0; nodes referencing nonexistent files: 0 ✓

Fresh-process lookup (same API, new interpreter):
lookup_symbol('secure_hash_s')    → [{'file': 'lib/ansible/utils/hashing_renamed.py', 'line': 34}]
lookup_symbol('deduplicate_list') → []
Correct. Only the long-lived MCP server is wrong.

Defects found

D-A — Critical: MCP never reloads the index after a watcher reindex.
interface/server/mcp_server.py:108 — _INDEXER is a module-level singleton .load()ed once at startup with no mtime revalidation; it's only dropped by _evict_singletons() on idle. ASTIndexer.lookup_symbol is additionally @functools.lru_cache(maxsize=512) (ast_indexer.py:2050); the cache_clear() calls at ast_indexer.py:1729/1816 run in the watcher process, so invalidation never crosses to the server. Result: symbol lookups are frozen at server-start state for the session's lifetime. Made deceptive by graph_stats reading file mtime directly (mcp_server.py:1550) and reporting index_age_minutes: 0, index_stale: false while serving 15-hour-old symbol data.

D-B — High: FAISS/metadata misalignment and unbounded metadata growth.
ast_metadata.json is a positional faiss_id → record map, but is append-only: ntotal 19061 vs 19076 records vs 17514 live symbols — misaligned by 15, so semantic hits past the divergence resolve to the wrong record. It retains renamed-away and deleted symbols (hashing.py's 7 entries survived removal; deduplicate_list survived deletion) and duplicates per reindex (color.py: 12 entries for 6 symbols). ~9% pollution and growing.

D-C — Medium: heartbeat has no per-daemon identity.
A serve process on a different project dir (PID 327278, --project-dir …/cognirepo_test_repo) overwrites ansible/.cognirepo/watchers/heartbeat. With the watcher killed, watch --status printed the contradiction Daemon: not running + Heartbeat: OK (10s ago) and a wrong Watch path. doctor credits the heartbeat to PID 327278, not the live watcher 330459. (The D16 dead-daemon probe itself works correctly.)

D-D — Low: CLI banner advertises 6 nonexistent commands — mcp-setup, episodic-search, lookup-symbol, who-calls, subgraph, graph-stats are in --help but rejected by argparse.

D-E — Low: stale pidfile 13408.json not removed on SIGTERM.

D-F — Low/Medium: doctor warns docs exist (66 .md) but .cognirepo/docs/ is empty — DocIngester never produced chunks despite the index-repo prerequisite.

Verdict

FAIL — on the test's own acceptance criteria, evaluated through the interface the test specifies (MCP).

- Indexing/watcher core (102 + 103 + 104): PASS. Debounce coalesced 5 saves into one reindex; rename and deletion are handled exactly right on disk; zero orphan nodes; verify-index exits 1 with DIRTY as required.
- Serving layer (D02-adjacent): FAIL. Two of five expected results — "renamed symbol found at new path only" and "deleted function absent from lookup" — are not met via MCP. The index is right; the server hands out stale answers and simultaneously reports itself fresh, which is worse than a plain miss because graph_stats actively certifies the staleness as healthy.
- Doctor: PARTIAL — not green apart from the dirty warning; the doc-chunk warning is a genuine gap and the daemon PID attribution is wrong.

Fixing D-A is the gate: revalidate _INDEXER against ast_index.json mtime (or the manifest checksum) inside _get_indexer() and clear the lookup caches on reload. D-B needs a rebuild of ast_metadata.json in lockstep with the FAISS index rather than append-on-reindex.

---

### RESOLUTION — branch `defect/COGNIREPO-DA_DF`

All six defects fixed. What each one actually was:

| ID | Diagnosis (confirmed, not inferred) | Fix |
|----|--------------------------------------|-----|
| D-A | `_INDEXER`/`_GRAPH` are process-lifetime singletons `.load()`ed once; the watcher reindexes in a **different process**, so its `lookup_symbol.cache_clear()` never crosses the boundary. Two independent layers of staleness: the singleton's `index_data` **and** the class-level `lru_cache`. | `(mtime_ns, size)` disk stamp + `reload_if_changed()` on `ASTIndexer` and `KnowledgeGraph`, called from `_get_indexer()`/`_get_graph()`. Reload clears both lookup caches. Refused when `_repo_ctx()` has repointed `get_path()` at another repo. |
| D-B | Not a misalignment — `faiss_meta` is **positional** (`faiss_id` IS the list index; `semantic_search_code` resolves `faiss_meta[fid]`), so dead records are unreachable, not wrong. The real defect is that they can never be reclaimed: `ntotal < len(faiss_meta)` is expected, monotonic growth is not. | `compact_faiss()` rebuilds index+meta from live symbols via `IndexIDMap2.reconstruct()` (no re-embedding) and renumbers `faiss_id`; runs at the end of `index_repo()`. `faiss_meta_stats()` exposes live/retained/dead/dangling. |
| D-C | The heartbeat is one slot per `.cognirepo/` with a `path` field nobody checked. | `read_heartbeat_for_path()` / `heartbeat_age_seconds_for_path()`; used by `_watcher_alive()`, `watch --status`, `watch --ensure-running`, doctor. A foreign holder is now named in the output instead of silently trusted. |
| D-D | Six banner rows had no `add_parser()` call at all. | Registered; they dispatch to the exact functions the MCP tools call, so CLI and MCP cannot drift. |
| D-E | `run_watcher_with_crash_guard()` installed no SIGTERM handler in the daemonized process (the parent's is not inherited through the double-fork), so SIGTERM killed it outright — skipping the final flush **and** the PID-file cleanup. | SIGTERM → `KeyboardInterrupt` (the path the loop already handles); PID file and own heartbeat removed in a `finally`. |
| D-F | **Not an ingestion failure.** Doctor counted doc chunks in `memory/semantic_metadata.json`, which only the *local FAISS* backend writes. This repo has `vector_backend: "chroma"`, so that file is `[]` and the warning was permanent. Verified: re-running the ingester on this repo returns `{"chunks": 145, "files": 51}` — the docs were indexed the whole time. | `DocIngester` writes `.cognirepo/index/doc_ingest.json`; doctor reads that, with the old count as fallback for pre-receipt indexes. |

**Verification**

1. *Live MCP session, the exact failing scenario.* Scratch repo → `serve` (JSON-RPC over stdio) → `lookup_symbol` → `git mv` + delete a function → `index-repo` **from a separate process** → `lookup_symbol` again **in the same server session**:

   | | pre-fix (`development` @ 4bdd06f) | post-fix |
   |---|---|---|
   | `secure_hash_s` | `hashing.py` ❌ stale | `hashing_renamed.py` ✅ |
   | `deduplicate_list` | `helpers.py` ❌ stale | `[]` ✅ |
   | `keep_me` (control) | resolves | resolves |

   Both expected results the test specifies through MCP now hold. The control run against pre-fix code reproduces the reported failure exactly.

2. *Regression suite:* `tests/test_singleton_staleness.py`, 38 tests — **37 fail against pre-fix code**, all pass after. (The 38th asserts the new error-degradation path, which has nothing to fail against.)

3. *Full suite:* 1310 passed, 5 skipped.

4. *Doctor on this repo (`cognirepo_test_repo/medium/ansible`):* **3 warnings → 1**, and that one is `Model API keys — none configured`, which is unrelated and expected. The doc-chunk warning is gone and the heartbeat is now credited to the live watcher (PID 330459) instead of the unrelated serve process (PID 327278). Step 5's "doctor green apart from the intentional dirty warning" is achievable as written.

**Retest:** E2E-100-1 in full. E2E-100-2 and E2E-100-3 are untouched by this diff.


## E2E-100-2: Tool discovery parity across all artifacts (crosses D01+101+106)
- Test repo: /home/ashlesh/my_works/cognirepo (this repo)
- Prerequisites: epic merged; `cognirepo export-spec` run.
- What to do: set-compare decorated tool names vs manifest.json vs glama.json vs
  openai_tools.json vs docs/MCP_TOOLS.md headers; then reconnect the MCP client.
- Prompt: "List every CogniRepo MCP tool you can see, alphabetically."
- Expected results: all five sources agree on the same 34 names (incl. find_symbol_path,
  get_service_endpoints); client lists 34.
Obtained Results

cognirepo export-spec re-ran clean (regenerates manifest.json from the live @mcp.tool() registry, then openai_tools.json).

Set comparison — all five sources:

┌───────────────────────┬──────────────────────────────────────┬───────┐
│        Source         │                 Path                 │ Count │
├───────────────────────┼──────────────────────────────────────┼───────┤
│ Decorated @mcp.tool() │ interface/server/mcp_server.py       │ 34    │
├───────────────────────┼──────────────────────────────────────┼───────┤
│ Manifest              │ interface/server/manifest.json       │ 34    │
├───────────────────────┼──────────────────────────────────────┼───────┤
│ Glama                 │ glama.json                           │ 34    │
├───────────────────────┼──────────────────────────────────────┼───────┤
│ OpenAI adapter        │ interface/adapters/openai_tools.json │ 34    │
├───────────────────────┼──────────────────────────────────────┼───────┤
│ Docs headers          │ docs/MCP_TOOLS.md                    │ 34    │
└───────────────────────┴──────────────────────────────────────┴───────┘

Union = 34. Symmetric difference between every pair = ∅.

▎ One false positive during the run: my heading regex initially scored MCP_TOOLS.md at 33 because org_wide_search's H2 carries a trailing italic suffix — ## org_wide_search *(replaces deprecated \org_search`)*` (docs/MCP_TOOLS.md:375). The tool is documented; the artifact is correct.

Named-tool spot check (D01/101/106 regression targets): find_symbol_path and get_service_endpoints present in all 5 sources — mcp_server.py:1586 / :1608, MCP_TOOLS.md:620 / :638.

Client-visible list (34, alphabetical):
architecture_overview    get_last_context        org_wide_search
context_pack             get_service_endpoints   record_decision
cross_repo_search        get_session_brief       record_error
cross_repo_traverse      get_session_history     record_user_preference
dependency_graph         get_user_profile        retrieve_memory
episodic_search          graph_stats             search_docs
explain_change           link_repos              search_token
find_symbol_path         list_org_context        semantic_search_code
get_agent_bootstrap      log_episode             store_memory
get_error_patterns       lookup_symbol           subgraph
                         org_dependencies        supersede_learning
                         org_search              who_calls

Verdict: PASS

All five artifacts agree on the same 34 names including find_symbol_path and get_service_endpoints; client lists 34.

Caveat on the client step: my own session's tool registry has no mcp__cognirepo__* entries — MCP tools bind at session start and this session began before your reindex, so I could not satisfy "reconnect and prompt" from inside my own registry. I verified the client-facing surface instead by driving a real JSON-RPC initialize → tools/list handshake against the exact server command in .mcp.json (/home/ashlesh/.local/bin/cognirepo serve --project-dir …). That is the same payload a reconnecting client receives, but it is a protocol-level check, not a live Claude Code enumeration. If you want the literal test step, /mcp reconnect (or restarting this session) and re-asking the prompt would close it.
## E2E-100-3: Corruption recovery drill (crosses 103+D02)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: indexed; some episodic events logged past rotation threshold (temporarily set
  episodic_max_events low, e.g. 20, in .cognirepo/config.json).
- What to do: truncate .cognirepo/graph/graph.pkl to garbage bytes; log events until rotation
  triggers; restart the MCP server.
- Prompt: "Run graph_stats and episodic_search for 'test event'; tell me if anything looks
  corrupted or duplicated."
- Expected results: server starts; graph.pkl.corrupt-<ts> exists; doctor flags it; episodic
  search returns unique IDs (no collisions), archive intact.
Verdict: PASS. Corruption was detected and quarantined with a timestamped .corrupt- file rather than crashing or silently loading garbage. Graph state correctly reset to empty instead of deserializing corrupt bytes. Episodic rotation split cleanly at the threshold with zero ID collisions and no data loss in the archive.

One gap worth noting: the watch --ensure-running supervisor does not restart a killed serve process — recovery depended on you manually reconnecting via /mcp. If unattended crash-recovery is a requirement, that's a real hole, not just a drill artifact.  
