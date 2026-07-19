# COGNIREPO-105 — Manual test suite

## TC-105-1: Behaviour summarize still stores memory (injection wiring)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: story merged; MCP server running; style-summarize threshold reachable
  (issue ≥ _STYLE_SUMMARIZE_EVERY queries or lower it in a scratch config).
- What to do: drive enough queries to trigger summarize_interaction_style(); then retrieve.
- Prompt: "Run retrieve_memory('interaction style') and show me the stored profile summary."
- Expected results: a source="interaction_style" memory exists — proving the injected store_fn
  path works end-to-end (previously the lazy upward import).
- Obtained results:
- Verdict:

## TC-105-2: Guard self-test
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: story branch.
- What to do: add `from interface.tools.store_memory import store_memory` inside any data/
  function; run scripts/check_circular_deps.py; revert.
- Prompt: "Add a lazy upward import to data/graph/knowledge_graph.py and confirm the checker
  fails naming the file, then revert."
- Expected results: checker exits nonzero naming the violation; clean tree passes.
- Obtained results: added a lazy `from interface.tools.store_memory import store_memory`
  inside `_graph_file()` in `data/graph/knowledge_graph.py`; ran
  `scripts/build_import_graph.py .` then `scripts/check_circular_deps.py
  restructure/import-graph.json --verbose` — exited 1, correctly named
  `data/graph/knowledge_graph.py:73 [data] → interface.tools.store_memory [interface]` among
  3 violations. Reverted the file, rebuilt the graph — back down to exactly the 2 known,
  already-registered `COGNIREPO-D06` violations (`core/vector_db/local_vector_db.py:167,265`).
  Note: "clean tree passes" is not literally true — HEAD currently has the two D06-deferred
  violations open (tracked separately, epic cannot sign off until D06 is resolved per
  skill.md §G.4) — but the checker's detection behavior itself is confirmed correct, which is
  what this case tests. Also covered as an automated self-test:
  `tests/test_check_circular_deps.py::test_fails_on_deliberately_added_lazy_upward_import`.
- Verdict: PASS (detection behavior confirmed; see note on the pre-existing D06 exception)
