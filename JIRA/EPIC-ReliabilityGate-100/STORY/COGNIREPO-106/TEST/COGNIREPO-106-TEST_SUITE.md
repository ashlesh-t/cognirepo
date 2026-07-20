# COGNIREPO-106 — Manual test suite

## TC-106-1: Doc claims match code
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: story merged.
- What to do: verify each fixed claim against code.
- Prompt: "Check docs/FEATURES.md §15/§16, README Future Plans, and SECURITY.md against the
  actual code and CI workflows. List any claim that is still wrong."
- Expected results: zero wrong claims; §16 documents CALLS_API auto-detection via
  http_call_scanner/org rewire with its limits; §15 count == number of tests/test_*.py.
- Obtained results: Checked docs/FEATURES.md §15/§16/§17, README Future Plans, SECURITY.md,
  docs/MCP_TOOLS.md, IMPROVEMENTS.md, and interface/cli/docs_index.py against current code.
  Found and fixed: §15 listed 2 deleted test files (test_documentation.py,
  test_tool_first_workflow.py — removed in f17d467) and an 85/17 count that had drifted to
  89 real files; §16/§17 said CALLS_API/SHARES_SCHEMA are "never auto-detected" — stale,
  since `intelligence/indexer/http_call_scanner.py` + `cognirepo org rewire` + doctor's
  CALLS_API check now do this for CALLS_API (SHARES_SCHEMA is still genuinely manual-only);
  README Future Plans still had "(v0.3.0)"/"(v0.4.0)" headers at v2.0.0 and didn't note that
  Go IMPORTS edges, `cognirepo ask`, and watcher debounce had already landed (Go CALLS
  edges and BM25-as-primary-ranker are genuinely still open); SECURITY.md:118 and
  FEATURES.md:304 both listed Snyk, docs/DEVELOPER_GUIDE.md:204 listed an unused
  `SNYK_TOKEN` secret — CI actually runs Bandit/pip-audit/Trivy/TruffleHog (no Snyk
  anywhere in .github/workflows/); docs/MCP_TOOLS.md's `org_wide_search` return type said
  `list`, code says `dict`, and `retrieve_memory`'s documented signature was missing
  `include_org`/`repo_path`. IMPROVEMENTS.md item 2 was already correctly marked RESOLVED —
  no action needed. Deleted the `interface/cli/docs_index.py` shim (nothing in-repo still
  imported it) and added a CHANGELOG Removed entry. Added
  `test_features_test_count_matches_tests_dir` and
  `test_dead_test_files_not_listed_in_feature_md` to `tests/test_docs_sync.py` (not a
  recreated `test_documentation.py` — see the ticket's Correction note) to pin the §15
  count and guard against the two dead filenames reappearing. Full suite:
  `venv/bin/python -m pytest tests/ -q` — 1255 passed, 5 skipped (was 1253/5 before this
  story; +2 net from the new doc-sync tests).
- Verdict: PASS
