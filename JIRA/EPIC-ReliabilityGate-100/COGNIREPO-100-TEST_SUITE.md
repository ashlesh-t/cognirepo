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

#: 1
Expected: One reindex logged for the burst
Obtained: last_indexed.json unchanged (2026-07-20T19:57:03, pre-dates burst).
.cognirepo/bg_tasks/ empty. No watcher log file exists. Yet ast_index.json content
was silently patched in place (network_renamed.py present, count_terms gone) with
zero log trail.
Result: FAIL — mutation happened, no log entry anywhere
────────────────────────────────────────
#: 2
Expected: Renamed symbol found at new path only
Obtained: lookup_symbol("to_netmask") → {"file":
"lib/ansible/module_utils/common/network_renamed.py", "line": 40, "type":
"FUNCTION"}. Confirmed old path network.py absent from ast_index.json["files"]
entirely (checked directly).
Result: PASS
────────────────────────────────────────
#: 3
Expected: Deleted function absent from lookup AND no orphan node
Obtained: lookup_symbol("count_terms") → empty (absent, half-pass). But
subgraph("count_terms") → symbol::count_terms CONCEPT node still live with 4 CALLS +
4 CALLED_BY edges to
check_mutually_exclusive/check_required_one_of/check_required_together/check_required_if.
Result: FAIL — orphan node confirmed present in graph
────────────────────────────────────────
#: 4
Expected: verify-index exits 1 with a DIRTY line
Obtained: EXIT_CODE=0, output OK 17343 symbols · 4114 files · commit bd7fa60c2413 ·
indexed ... — no DIRTY line, no nonzero exit, despite 3 uncommitted mutations (git
status confirms R/M/M present at call time).
Result: FAIL
────────────────────────────────────────
#: 5
Expected: doctor green apart from intentional dirty warning
Obtained: 2 warnings shown, neither is the dirty-tree warning: (a) missing API keys —
pre-existing/unrelated, (b) graph.pkl.corrupt-1784570101 quarantined — pre-existing
corruption, unrelated to this test. Bonus defect not in scope: FAISS 17,342 vs
manifest 17343 symbol-count mismatch. Zero mention of the rename/edit/delete.
Result: FAIL — wrong warnings surfaced, correct one never fired

Verdict: FAIL (1/5 pass).

The only behavior that matched spec was symbol resolution following the rename. Everything gating "did the tool notice the dirty state" failed: no reindex log, verify-index blind to 3 live mutations (exit 0, no DIRTY), doctor blind to the same mutations (its 2 warnings are unrelated pre-existing issues), and the deleted function left a live orphan node in the graph despite disappearing from lookup_symbol.

## E2E-100-2: Tool discovery parity across all artifacts (crosses D01+101+106)
- Test repo: /home/ashlesh/my_works/cognirepo (this repo)
- Prerequisites: epic merged; `cognirepo export-spec` run.
- What to do: set-compare decorated tool names vs manifest.json vs glama.json vs
  openai_tools.json vs docs/MCP_TOOLS.md headers; then reconnect the MCP client.
- Prompt: "List every CogniRepo MCP tool you can see, alphabetically."
- Expected results: all five sources agree on the same 34 names (incl. find_symbol_path,
  get_service_endpoints); client lists 34.
- Obtained results:
- Verdict:

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
- Obtained results:
- Verdict:
