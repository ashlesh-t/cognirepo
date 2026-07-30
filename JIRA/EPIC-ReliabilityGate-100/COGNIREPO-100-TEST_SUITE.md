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

Working repo: .../medium/ansible (the git+.cognirepo root; the MCP server cognirepo-ansible is scoped here). Watcher PID 330459 live. Choices: burst=color.py, rename=deduplicate_list (helpers.py→helpers_moved.py), delete=md5s (hashing.py).

#: 1
Check: Burst-save color.py 5× (0.002s)
Expected: one reindex
Obtained: Watcher reindexed color.py; no crash/partial. Only a single-slot marker
exists (last_watcher_reindex.json), so I can't prove exactly-one event from logs —
but no duplicate/burst multiplication at the query layer.
Verdict: ⚠︎ Pass (weak evidence)
────────────────────────────────────────
#: 2
Check: git mv → renamed symbol
Expected: new path only
Obtained: lookup_symbol(deduplicate_list) → helpers_moved.py:44 only.
Verdict: ✅ Pass
────────────────────────────────────────
#: 3
Check: Delete md5s
Expected: absent + no orphan node
Obtained: lookup_symbol(md5s) → no output. who_calls(md5s) → no definition,
local_callers=[], no orphan graph node. (The "called in some files" note is a false
substring match on md5sum/module.md5 — grep confirms zero real md5s( callers.)
Verdict: ✅ Pass
────────────────────────────────────────
#: 4
Check: verify-index w/ dirty edit
Expected: exit 1 + DIRTY
Obtained: EXIT 1; DIRTY 3 uncommitted… listing color.py, hashing.py, helpers_moved.py.
Verdict: ✅ Pass
────────────────────────────────────────
#: 5
Check: doctor
Expected: green except dirty warning
Obtained: EXIT 1, 3 warnings — see below.
Verdict: ❌ Deviation

graph_stats: 17592→17598 nodes, 96434→96444 edges, watcher_alive:true, index_stale:false.

Two real deviations (verified against files, not just tool text)

1. doctor is not "green apart from dirty". Besides the intentional ⚠ Working tree (dirty) warning, it emits ⚠ Daemon heartbeat — held by PID 438467 watching …/cognirepo_test_repo, not this repo — i.e. a cross-repo heartbeat collision: the parent-dir serve process owns the heartbeat file, so doctor cannot see this repo's live watcher (330459). Plus a benign ⚠ Model API keys — none (environmental).
2. ast_metadata.json is not pruned on incremental reindex. The plaintext side-file holds 19,111 rows with duplicates and 2 orphan file paths (helpers.py from this run's rename + hashing_renamed.py from a prior test) — md5s and old-path deduplicate_list still listed there. The query layer hides all of it: lookup_symbol, who_calls, verify-index, doctor, and graph_stats all consistently report the clean 17,514 sym / 17,596 nodes. So it's a stale-cache/orphan artifact in the raw metadata, not a query-correctness failure.

Verdict

PASS with caveats. All core index-consistency behaviors hold at the query/graph layer: rename resolves to the new path only, the deleted function is absent with no orphan graph node, and verify-index correctly flags DIRTY (exit 1). Two genuine issues fall short of the spec: (a) doctor shows an extra heartbeat-ownership collision warning (cross-repo watcher bug), so it's not green-except-dirty; and (b) the incremental watcher does not prune ast_metadata.json, leaving stale duplicate/orphan rows (masked from queries but real on disk). Repo restored to clean state afterward.

---

### RESOLUTION — both caveats fixed (2026-07-31, on `development`, targets v2.0.1)

**(a) Heartbeat collision — root cause was one level deeper than D-C's fix reached.**
D-C's `read_heartbeat_for_path()` correctly rejects a heartbeat once read if its recorded
`path` doesn't match the caller's repo — but *which file* gets read was still decided by
`daemon._find_cognirepo_dir()`, which walked up from the current process's cwd to the
nearest ancestor `.cognirepo/`, ignoring the actual repo path being watched entirely. A
`serve --project-dir <parent>` process could walk past a child repo's own `.cognirepo/`
and stamp its heartbeat there, physically colliding with that child's own watcher heartbeat
— which is exactly what the retest above caught. Fix: all PID/heartbeat resolution in
`interface/cli/daemon.py` (`_watchers_dir`, `_pid_file`, `_heartbeat_file`, and every
reader/writer that touches them) now resolves directly against
`core.config.paths.get_cognirepo_dir_for_repo(repo_path)` — the same resolution
FAISS/AST/graph storage already uses — instead of walking cwd's ancestors. No collision
is possible now: two repos' watcher state can no longer share a file.

**(b) ast_metadata.json pruning — the watcher never called compact_faiss().**
Confirmed via a direct trace: a single in-file symbol rename left `faiss_meta`
2 records heavier for 1 live symbol (dead=2), because `compact_faiss()` (the D-B fix) only
ever ran at the end of a full `index-repo` pass — the watcher's debounced incremental
reindexes only ever appended. `RepoFileHandler._flush_locked()` (and the `debounce_ms=0`
synchronous `_reindex`/`_remove` paths) now call a new `_maybe_compact_faiss()` before every
persist, threshold-gated at 25 dead+dangling records so a full index rebuild (which
reconstructs every live vector) isn't paid on every keystroke-triggered save. Verified: after
compaction, `faiss_meta_stats()["dead"] == 0` and `ntotal == live == len(faiss_meta)`.

**Also investigated, found to be by design, not a defect:** the E2E-100-3 gap ("`watch
--ensure-running` doesn't restart a killed `serve`") — `serve` is a foreground subprocess
owned by the MCP client (`.mcp.json` spawns and is responsible for restarting it); a
cognirepo-side supervisor bolted onto the watcher's `--ensure-running` path would be a
second, conflicting layer with no PID/heartbeat hook into `serve` today. No code change.

**Also found (pre-existing, not introduced by this fix, not fixed):** `run_watcher_with_crash_guard`'s
shutdown path has a low-probability race — `start_heartbeat_thread` writes immediately on
start, which can land after `clear_heartbeat_if_owned()` in the `finally` block on a very
fast clean exit, leaving a stale heartbeat behind. Reproduced once under full-suite load
(`tests/test_singleton_staleness.py::TestWatcherShutdownCleanup::test_pid_file_and_heartbeat_removed_on_clean_exit`),
not reproducible standalone. Pre-existing on the merged D-E fix; out of scope for this pass.

**Tests:** 1312 passed, 5 skipped (full suite). New coverage:
`tests/test_stale_cleanup.py::TestWatcherFaissReclaim` (2 tests — rename reclaim, threshold-triggered
compaction). `tests/test_daemon_extended2.py`, `tests/test_index_write_concurrency.py`,
`tests/test_singleton_staleness.py` updated for the new path-scoped `daemon.py` signatures.

**Retest:** E2E-100-1 full retest recommended to confirm no doctor warning remains and
`ast_metadata.json` stays bounded under a live watch session; left for the user per skill.md
step 4 (live MCP verification).

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
