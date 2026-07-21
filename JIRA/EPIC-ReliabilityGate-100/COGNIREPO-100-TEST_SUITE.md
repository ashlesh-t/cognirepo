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
Actions performed:
1. Burst-saved lib/ansible/utils/version.py 5× in <1s (appended marker comments)
2. git mv lib/ansible/utils/shlex.py → shlex_renamed.py
3. Deleted colorize() from lib/ansible/utils/color.py
4. Ran cognirepo verify-index with all 3 edits uncommitted
5. Ran cognirepo doctor

Obtained results (filesystem/log-verified, not just tool text)

Check: lookup_symbol("colorize")
Result: Empty — no output. Confirmed at raw-file level too: grep -c '"name":
*"colorize"' on .cognirepo/index/ast_index.json → 0. Correctly removed.
────────────────────────────────────────
Check: lookup_symbol("shlex_split")
Result: Found at lib/ansible/utils/shlex_renamed.py:24 — correctly resolved to new path
only.
────────────────────────────────────────
Check: graph_stats
Result: 17,592 nodes / 96,42 but last_indexed field stuck

at 2026-07-21T16:31:07, whic recorded in manifest.json
(18:20:10). Timestamp is stapdated.
────────────────────────────
Check: cognirepo verify-inde
Result: Exit code 1, DIRTY les (color.py,
shlex_renamed.py, version.py
────────────────────────────
Check: cognirepo doctor
Result: Exit code 1, 3 warning-tree warning, plus "no API

keys configured" and "doc chexisting environment
conditions, not caused by th was not "green apart from
the intentional dirty warnin
────────────────────────────
Check: Watcher log (watch_17
Result: Two threads crashed replace(ast_index.json.tmp →
ast_index.json) — a race whetriggered by the

- **ROOT CAUSE (analysed 2026-07-22) — 4 defects, fixed on
  `defect/COGNIREPO-D13_D14_D15_D16`.**

  - **D13 (P0, silent corruption).** `ASTIndexer._atomic_json_dump()` derived its scratch
    filename from the target path, so all concurrent writers shared one `ast_index.json.tmp`.
    Two failure modes: the loser of the rename race raises `FileNotFoundError` (the crash
    logged above — the *benign* variant), and an interleaved `open(tmp,"w")` truncates a file
    another writer is mid-`json.dump()` into, promoting partial JSON into place. The latter is
    the "parse error at char 73M" the atomic-write commit was written to fix; it narrowed the
    window without closing it. Fix: `tempfile.mkstemp()` per writer + `store_lock()` across the
    whole four-file group in `save()`, matching what `KnowledgeGraph.save()` already did.
  - **D14 (P1) — the 16:31:07 vs 18:20:10 gap is real.** `indexed_at` is stamped only at
    `ast_indexer.py::index_repo`, never by `save()`, so the watcher's incremental path left it
    frozen while `_write_manifest()` stamped `_now()` on every save. Worse, `graph_stats`
    returned `last_indexed` (last *full* index) and `index_age_minutes` (file mtime) in the
    same dict — two clocks. Fix: stamp on every `save()`; add `full_indexed_at` for the last
    complete sweep.
  - **D15 (P0).** `flush()` held `self._lock` only while draining `_pending`, releasing it
    before the seconds-long index+save section; `Timer.cancel()` is a no-op once fired, so a
    burst outlasting the debounce window ran two flush bodies concurrently. Also
    `indexer.save()` sat outside any handler, so its failure skipped `graph.save()`, the D12
    audit trail, `mark_stale()` and `invalidate_hybrid_cache()` — producing exactly the
    cross-store divergence this test exists to detect, with no trace in
    `last_watcher_reindex.json`. Fix: `_flush_lock` + per-step guards + an `error` field in
    the audit record.
  - **D16 (P1, latent).** `_watcher_alive()` read `.cognirepo/watcher.pid`, which nothing
    writes, so it always returned `False` and `graph_stats` could spawn a competing
    `index-repo --changed-only` against a live watcher — a third concurrent writer feeding
    D13. Did not fire in this run only because `index_age_minutes ≈ 0`.

  **Test-suite defect:** the expected result "doctor green apart from the intentional dirty
  warning" is unachievable in an environment with no API keys and incomplete doc coverage, and
  cannot distinguish a regression from ambient noise. Restate as a delta assertion: capture
  `doctor` output before the mutations and assert the only *new* warnings after are the
  dirty-tree ones.

  **Coverage gap that let this ship:** `tests/test_watcher_debounce.py` mocks `indexer.save`,
  so no watcher test ever reached the real writer, and every case asserts the debounce
  *collapse* property rather than constructing overlapping flushes. New regression suite
  `tests/test_index_write_concurrency.py` (11 tests) drives the real writer; 10 of the 11 fail
  against the pre-fix code, reproducing the logged `FileNotFoundError` verbatim.



## E2E-100-2: Tool discovery parity across all artifacts (crosses D01+101+106)
- Test repo: /home/ashlesh/my_works/cognirepo (this repo)
- Prerequisites: epic merged; `cognirepo export-spec` run.
- What to do: set-compare decorated tool names vs manifest.json vs glama.json vs
  openai_tools.json vs docs/MCP_TOOLS.md headers; then reconnect the MCP client.
- Prompt: "List every CogniRepo MCP tool you can see, alphabetically."
- Expected results: all five sources agree on the same 34 names (incl. find_symbol_path,
  get_service_endpoints); client lists 34.
- Obtained results:
  Ran `cognirepo export-spec` first. Source of truth = 34 `@mcp.tool()`-decorated functions
  in `interface/server/mcp_server.py` (arch_overview, context_pack, cross_repo_search,
  cross_repo_traverse, dependency_graph, episodic_search, explain_change, find_symbol_path,
  get_agent_bootstrap, get_error_patterns, get_last_context, get_service_endpoints,
  get_session_brief, get_session_history, get_user_profile, graph_stats, link_repos,
  list_org_context, log_episode, lookup_symbol, org_dependencies, org_search, org_wide_search,
  record_decision, record_error, record_user_preference, retrieve_memory, search_docs,
  search_token, semantic_search_code, store_memory, subgraph, supersede_learning, who_calls).

  Set-compared each artifact against source:
  | Source | Count | Diff |
  |---|---|---|
  | interface/server/manifest.json | 34 | none |
  | glama.json | 34 | none |
  | interface/adapters/openai_tools.json | 34 | none |
  | docs/MCP_TOOLS.md headers | 34 | none |
  | Raw MCP `tools/list` (fresh `cognirepo serve` spawned, JSON-RPC `initialize`+`tools/list`
    sent directly over stdio) | 34 | none |
  | This session's live client (`claude mcp list` / `claude mcp get cognirepo-cognirepo` →
    `✔ Connected`; `ToolSearch` for any cognirepo tool name, incl. `select:context_pack,
    lookup_symbol,get_session_brief,store_memory,who_calls`) | **0** | **34 missing** |

  find_symbol_path and get_service_endpoints present in all five static artifacts and in the
  raw server handshake — no drift there. The server process itself is healthy: a clean stdio
  handshake against a freshly spawned `cognirepo serve` returns the correct 34/34 names,
  identical to the decorated-function set.

- Verdict: FAIL — not a spec/manifest drift issue (4/4 static artifacts + raw server response
  agree exactly, 34/34). Failure is on the "reconnect the MCP client" step: this session's
  transport reports the server as Connected but exposes zero CogniRepo tools — a client-side
  staleness bug where "Connected" status does not guarantee the tool list was (re)loaded into
  the active session. Could not fully confirm whether a true session restart resolves it, since
  no in-session mechanism exists to force a client-side MCP reconnect/tool-cache eviction —
  flag as a retest item requiring a fresh session process.

- **ROOT CAUSE (corrected 2026-07-22) — environment/config, NOT a product defect and NOT a
  client staleness bug.** `.mcp.json` registers `cognirepo-cognirepo` at *project* scope.
  Claude Code gates project-scoped servers behind a one-time per-project approval recorded in
  `~/.claude.json → projects["/home/ashlesh/my_works/cognirepo"].enabledMcpjsonServers`.
  Both that list and `disabledMcpjsonServers` are **empty** — the approval was never granted,
  so the server is never loaded into any session. `claude mcp list` bypasses that gate
  entirely: it reads the config file and spawns the process itself for a health check, which
  is why it prints `✔ Connected` next to a session exposing zero tools. The two signals come
  from different code paths and only one consults the approval state.

  Timed raw stdio handshake against a freshly spawned `cognirepo serve`: `initialize` reply at
  0.55 s, `tools/list` reply at 0.55 s, 34 tools — so a startup/timeout explanation is also
  ruled out. The failure is deterministic, not session-specific; it reproduces in every new
  session until approval is granted.

  Fix (either): `claude mcp reset-project-choices`, restart, and answer the approval prompt;
  or move the server to user scope —
  `claude mcp add -s user cognirepo-cognirepo /home/ashlesh/.local/bin/cognirepo serve
  --project-dir /home/ashlesh/my_works/cognirepo`.

  **Retest required under a corrected premise.** The assertion this test actually owns —
  artifact/spec parity — *passed* (5/5 sources at 34/34, including the raw server response).
  Only the client-reconnect step failed, for an environment reason unrelated to the epic.
  Test-suite defect: the prerequisites must assert `enabledMcpjsonServers` contains the server,
  so an unapproved config fails as a setup error instead of masquerading as tool-discovery drift.

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
