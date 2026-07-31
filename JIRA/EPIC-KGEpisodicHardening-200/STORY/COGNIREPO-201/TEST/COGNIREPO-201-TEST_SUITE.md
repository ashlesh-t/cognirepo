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
  Live MCP verification against `cognirepo_test_repo/easy` (per skill.md step 4) — left for
  the user: restart server after `rm`-ing an indexed file with the watcher stopped, run
  `graph_stats`/doctor/`graph repair --apply` through the MCP client itself.
- Verdict: PASS (automated). Live retest pending.
