# COGNIREPO-201 — Manual test suite

## TC-201-1: Integrity visibility + repair
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: story merged; indexed; MCP server stopped.
- What to do: `rm` one indexed source file while the watcher is NOT running; restart server.
- Prompt: "Run graph_stats — how healthy is the graph? If it reports dangling nodes, run the
  repair and re-check."
- Expected results: integrity shows dangling ≥ 1 naming pattern; doctor flags it;
  `cognirepo graph repair --apply` prunes; re-run shows 0; other nodes untouched.
- Obtained results: Automated-equivalent coverage added and passing (unit-level, real
  KnowledgeGraph, no mocks): `tests/test_graph.py::TestKnowledgeGraphIntegrity` (clean graph →
  0/0; orphan restricted to FILE/FUNCTION/CLASS; dangling file detected + deduped across its
  symbols; `--apply`-equivalent prune removes danglers only, orphan CONCEPT untouched, re-sweep
  shows 0), `tests/test_doctor.py::TestDoctorGraphIntegrity` (seeded dangling node → doctor WARN
  with repair hint + exit ≥1; clean graph → "0 orphans · 0 dangling files"),
  `tests/test_graph_repair.py::TestGraphRepair` (dry-run reports without mutating; `--apply`
  removes exactly the dangling nodes and prints the count; clean graph reports "no dangling
  file nodes found"). Full suite: 1322 passed, 5 skipped.
  Live retest against `cognirepo_test_repo/easy/fastapi` (indexed, watcher confirmed not
  running — `cognirepo list` showed no running watcher daemons) — executed 2026-08-06 via CLI
  equivalents of the MCP tools (`graph-stats`/`doctor`/`graph repair`, same
  `KnowledgeGraph.integrity_report()` code path graph_stats calls): baseline
  `graph-stats`/`doctor` on the indexed repo showed 0 orphans/0 dangling (7153 nodes, 28614
  edges). Removed `fastapi/security/utils.py` (1 indexed FUNCTION,
  `get_authorization_scheme_param`). Re-ran `graph-stats` →
  `integrity.dangling_files: ["fastapi/security/utils.py"]`, orphans still `[]`. `doctor` → WARN
  "0 orphan node(s), 1 dangling file(s)" with the `cognirepo graph repair --apply` hint, exit
  code 1. `cognirepo graph repair` (dry-run) reported the same path without mutating. `cognirepo
  graph repair --apply` removed 2 nodes (the FILE node + its FUNCTION) across the 1 dangling
  path. Re-ran `graph-stats`/`doctor` → 0 orphans/0 dangling, 7152 nodes/28611 edges (net -1
  node/-3 edges — consistent with live call edges redirecting onto an unresolved CONCEPT stub
  per COGNIREPO-D10 rather than being dropped; no other symbols touched). Restored the file via
  `git checkout -- fastapi/security/utils.py`; working tree clean.
- Verdict: PASS (automated + live retest).
