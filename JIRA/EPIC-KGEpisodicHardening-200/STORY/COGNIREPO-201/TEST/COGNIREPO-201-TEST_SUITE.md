# COGNIREPO-201 — Manual test suite

## TC-201-1: Integrity visibility + repair
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: story merged; indexed; MCP server stopped.
- What to do: `rm` one indexed source file while the watcher is NOT running; restart server.
- Prompt: "Run graph_stats — how healthy is the graph? If it reports dangling nodes, run the
  repair and re-check."
- Expected results: integrity shows dangling ≥ 1 naming pattern; doctor flags it;
  `cognirepo graph repair --apply` prunes; re-run shows 0; other nodes untouched.
- Obtained results:
- Verdict:
