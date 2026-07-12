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
- Obtained results:
- Verdict:

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
