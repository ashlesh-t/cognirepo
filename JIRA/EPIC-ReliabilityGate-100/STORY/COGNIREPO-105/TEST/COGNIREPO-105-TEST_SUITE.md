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
Setup: Ran 10 diverse retrieve_memory queries against cognirepo-ansible (module_utils imports, executor internals, deprecation API, changelog conventions, inventory parsing, integration test targets, architecture overview, sanity config, TaskExecutor callers, AnsibleModule validation) to push past the _STYLE_SUMMARIZE_EVERY threshold.

Prompt executed: retrieve_memory('interaction style')

Obtained results:
5 hits returned, ALL source="semantic":
1. "get_user_profile() ... Call at session start" (docs)
2. "get_user_profile() ... calibrate response style" (docs)
3. "User behavior profiling ... CogniRepo tracks how you interact..." (docs)
4. "Claude Code Behaviour Hooks ... behaviour_hook.py ... sync_claude_memory.py" (docs)
5. "Code of Conduct scope..." (unrelated doc noise)
No result carried source="interaction_style".

Cross-check via get_user_profile():
total_queries_tracked: 35   (well above any reasonable threshold)
sample_queries includes "interaction style" (the query itself, tracked)
depth_preference: "detailed", code_focus_percent: 100, etc. — profile IS being computed
- Verdict: FAIL :

The behavior-tracking side works — get_user_profile() correctly aggregates 35 tracked queries into a live profile (depth preference, terminology, question-type distribution). But summarize_interaction_style() is not persisting that profile into the memory/vector store: retrieve_memory('interaction style') returns zero hits with source="interaction_style", only pre-existing documentation chunks that happen to mention the term.

This means the injected store_fn path is not confirmed end-to-end. Two possible root causes, given the framing of your test ("previously the lazy upward import"):
1. summarize_interaction_style() never actually calls store_fn(...) (threshold logic not firing despite 35 tracked queries).
2. It calls store_fn but the memory is stored with a different source label or into a different repo scope/index than the one retrieve_memory searches.

Suggested next step: grep the CogniRepo source for summarize_interaction_style and _STYLE_SUMMARIZE_EVERY in .cognirepo/ or the installed package to check (a) whether the threshold is actually being evaluated on this counter, and (b) what source= string it passes to store_fn/store_memory.

### Re-verification (defect/COGNIREPO-D04_D05_D06 branch)

Root-caused to three independent bugs, each filed and fixed:
- **COGNIREPO-D04** — `summarize_interaction_style()` called `store_fn(summary,
  source="interaction_style", importance=0.8)`, but `store_memory()` has no `importance`
  kwarg → `TypeError`, swallowed by a blanket `except Exception`. Fixed by dropping the kwarg.
- **COGNIREPO-D07** — even with D04 fixed, `HybridRetriever._vector_retrieve()` hardcoded
  `"source": "semantic"` on every vector hit, discarding the real stored source. Fixed to
  preserve the real value.
- **COGNIREPO-D08** — even with D04+D07 fixed, `store_memory()`'s `source` argument was never
  forwarded to `SemanticMemory.store()`, which always persisted with the default `source=
  "memory"`. Fixed by threading `source` through both.

Re-ran the exact scenario (isolated `.cognirepo` fixture, real `BehaviourTracker(store_fn=
store_memory)`, 10 diverse queries to cross `_STYLE_SUMMARIZE_EVERY`, then
`retrieve_memory('interaction style')`):

```
Total hits: 1
interaction_style-sourced hits: 1
 - User interaction style: prefers concise answers. Most common question type: how.
   Common terminology: does, work, what, explain, module_utils. Recent query examples:
   explain sanity config | who calls TaskExecutor | how does AnsibleModule validation
   work. | source= interaction_style
TC-105-1: PASS
```

Full suite green throughout: `venv/bin/python -m pytest tests/ -q` — 1249 passed, 5 skipped
(baseline before this branch: 1227 passed, 5 skipped).

### Live re-verification against the running cognirepo-ansible MCP server — parallel-call race found (COGNIREPO-D09)

Pulled `story/COGNIREPO-105` (post D04–D08) into the venv actually backing the live
`cognirepo-ansible` MCP server and reran TC-105-1 for real, not just against an isolated
pytest fixture. First attempt fired the 10 warm-up `retrieve_memory` queries in a single
**parallel** tool-call batch (the natural pattern for an agentic client) — `retrieve_memory
('interaction style')` still came back empty of any `source="interaction_style"` hit, and
`.cognirepo/graph/behaviour.json` showed `interaction_style.last_summarized: null` with
`query_patterns` stuck at its 50-entry cap, even though `query_history` kept growing normally.

Isolated the cause to `BehaviourTracker.save()` being a plain last-write-wins
read-modify-write: `_behaviour_record_query()` constructs a fresh `BehaviourTracker` per MCP
call, so concurrent calls each load the same on-disk snapshot and whichever `save()` runs last
overwrites the others' updates outright — including a concurrent request's own successful
`summarize_interaction_style()` reset. Filed and fixed as **COGNIREPO-D09** (see
`JIRA/EPIC-ReliabilityGate-100/DEFECT/COGNIREPO-D09/`): `save()` now acquires a dedicated
`behaviour.json`-scoped file lock and re-reads + additively merges concurrent on-disk state
(`query_history` union, `symbol_weights` keep-max, `interaction_style` adopt-newer-summary)
before writing — mirroring the existing `OrgGraph.save()` compose-on-save pattern.

Re-ran the same 10-query batch **sequentially** post-fix (and added a unit-level equivalent —
two independently-loaded `BehaviourTracker` instances racing on `save()`, see
`tests/test_behaviour_tracker.py::TestBehaviourTrackerConcurrentSave`) — a genuine
auto-generated `source="interaction_style"` memory was retrievable, `last_summarized` was set,
and `query_patterns` reset correctly. Full suite: `venv/bin/python -m pytest tests/ -q` — 1253
passed, 5 skipped.

TC-105-1: **PASS** (parallel-call path was previously unverified and in fact broken —
COGNIREPO-D09 closes that gap; the injected `store_fn` path itself, D04/D07/D08's target, was
already correct).

- Verdict (re-verified): **PASS**

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

**Update:** `COGNIREPO-D06` (the `core/vector_db/local_vector_db.py:167,265` core→data
violations referenced above) is now resolved on `defect/COGNIREPO-D04_D05_D06` — HEAD reports
zero layer violations (`scripts/check_circular_deps.py restructure/import-graph.json
--verbose`), not the two deferred ones.
