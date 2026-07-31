# Phase 0 — Verification & Reliability Audit (gate) → v2.0.1

**Epic:** COGNIREPO-100 (`JIRA/EPIC-ReliabilityGate-100/`). Evidence:
`JIRA/EPIC-ReliabilityGate-100/COGNIREPO-100-Discovery.md` (cited below as *D100 §n*).
**Gate rule:** no later phase starts before this epic is signed off.

## Context / Why

The repo shipped a breaking 2.0.0 restructure (commits `146627d`, `6b0c83d`, `45b0b41`) and the
audit found: a regression of the [1.1.3] manifest fix (D100 §1b — `find_symbol_path` +
`get_service_endpoints` absent from `manifest.json`/`glama.json` while 34 tools are live), an
uncommitted `requirements.txt` diff that reverts committed CVE fixes `779b113`/`6083b15`
(D100 §5), a file watcher with no debounce, no rename handling, and orphan-node leakage
(D100 §3), an episodic-memory ID collision after rotation (D100 §8 / D200 §2), a
fall-back-to-empty graph.pkl recovery story (D100 §4), and widespread doc drift (D100 §1c, §2,
§5). The four v1.1.0 P0 blockers are **verified fixed at HEAD** (D100 §1a) and the full pytest
suite is green (1203 passed / 5 skipped, D100 §6) — so this phase is a focused fix list, not a
rescue.

## Scope

**In:** manifest single-sourcing + immediate regression fix; watcher debounce/on_moved/orphan
cleanup; verify-index working-tree staleness; graph.pkl corruption quarantine; layer-invariant
upward-import cleanup; requirements.txt revert decision; docs truth pass.
**Out:** any new MCP tool or feature (Phases 1-4); k8s-scale re-validation runs (tracked as a
risk, not a blocker); manual-suite re-execution of the deleted MANUAL_TEST_SUITE.md (superseded
by this epic's TEST_SUITE files, D100 §6).

## Acceptance criteria (epic)

1. `manifest.json`, `glama.json`, `openai_tools.json` each list exactly the 34 decorated tools,
   generated (not hand-edited), with a CI test failing on drift.
2. On a watched repo: a burst of ≥5 writes to one file within 1 s triggers exactly one reindex;
   `git mv a.py b.py` results in `lookup_symbol` resolving to `b.py` and zero hits on `a.py`;
   modifying a file to delete a symbol leaves no orphan node for it.
3. `cognirepo verify-index` reports STALE when a tracked source file has uncommitted
   modifications.
4. A corrupt `graph.pkl` is quarantined to `graph.pkl.corrupt-<ts>` (not silently overwritten)
   and doctor reports it.
5. `grep -rn "from interface" data/ intelligence/ core/` (excluding TYPE_CHECKING) returns zero
   runtime imports.
6. requirements.txt matches the CVE-fixed committed pins (or the user has explicitly accepted the
   downgrade in writing on the ticket).
7. Docs truth pass merged: FEATURES §15/§16, README Future Plans headers, SECURITY.md gate list,
   IMPROVEMENTS.md, shim removal noted for next major.

## Stories

### COGNIREPO-101 — Single-source MCP tool manifest generation
- **Context/Why:** three hand-maintained schema copies caused two drift incidents ([1.1.3] fix,
  then 2.0.0 regression) — D100 §1b.
- **Files:** `interface/server/mcp_server.py` (`_build_manifest`, `_write_manifest` :2580-2584),
  new `scripts/gen_tool_specs.py` (or extend `scripts/sync_version.py`), `glama.json`,
  `interface/adapters/openai_spec.py` (fix stale `MANIFEST_PATH = "server/manifest.json"` :27),
  `interface/adapters/openai_tools.json`, new `tests/test_manifest_drift.py`.
- **Interface contract:** no MCP tool changes. Build-time contract: generator introspects the
  FastMCP registry (decorated functions' signatures + docstrings) → emits manifest.json entries;
  glama.json `tools` array and openai_tools.json derive from that same output.
  Manifest token delta: +~210 tokens (the two restored tools, ~105 avg each — D100 §2); no other
  growth.
- **Data flow:** `cognirepo export-spec` (existing CLI) → `_write_manifest()` → generator reads
  `mcp._tool_manager` registry → writes all three artifacts. CI test loads decorated names
  (same extraction as doctor's `_REGISTERED_TOOLS` :2588) and asserts set-equality with each
  artifact.
- **State/schema:** none under `.cognirepo/`; repo artifacts regenerated. Back-compat: manifest
  gains 2 entries (additive).
- **Dependencies:** none (D01 lands first as the hotfix; this story prevents recurrence).
- **Test oracle:** AC1 — `python -c` set-diff of decorators vs each artifact prints empty;
  `pytest tests/test_manifest_drift.py` passes; deleting a manifest entry makes it fail.

### COGNIREPO-102 — File-watcher hardening: debounce, rename handling, batched saves
- **Context/Why:** D100 §3 — no debounce (README:616 confirmed), no `on_moved`
  (`file_watcher.py:59-72`), full `indexer.save()`+`graph.save()` per event (`:153-154`).
- **Files:** `intelligence/indexer/file_watcher.py`, `tests/test_stale_cleanup.py` (extend),
  new `tests/test_watcher_debounce.py`.
- **Interface contract:** no MCP change. Internal: `RepoFileHandler` gains an event queue with a
  configurable debounce window (default 500 ms, `config.json → indexing.debounce_ms`), a
  `on_moved(FileMovedEvent)` = `_remove(src)` + `_reindex(dest)`, and one save per flushed batch.
- **Data flow:** watchdog event → queue (per-path dedupe) → timer flush → existing
  `_reindex`/`_remove` per unique path → single `indexer.save()`/`graph.save()` →
  `invalidate_hybrid_cache()` once.
- **State/schema:** new optional `indexing.debounce_ms` config key (documented in
  CONFIGURATION.md); default preserves behavior semantics. Back-compat: yes.
- **Dependencies:** none.
- **Test oracle:** AC2 items 1-2 — unit test: 5 synthetic events in <500 ms → one `index_file`
  call; moved-event test: reverse index has dest, not src.

### COGNIREPO-103 — Orphan-node cleanup on re-index + graph.pkl quarantine
- **Context/Why:** D100 §3 (modify path removes edges only — `file_watcher.py:146-148`,
  `knowledge_graph.py:189-192`), D100 §4 (corrupt pkl silently replaced).
- **Files:** `intelligence/indexer/file_watcher.py` (`_reindex` uses `remove_file_nodes` before
  reindex), `data/graph/knowledge_graph.py` (`_load` quarantine: rename to
  `graph.pkl.corrupt-<ts>` mirroring `ast_indexer.py:2066-2078`), doctor check in
  `interface/cli/main.py`, tests.
- **Interface contract:** no MCP change; `graph_stats` output unchanged here (integrity metrics
  are Phase 1 / COGNIREPO-201).
- **Data flow:** modify event → `remove_file_nodes(rel_path)` (already correct for deletes) →
  `index_file` re-adds current symbols → save. Load path: pickle failure → quarantine file →
  warn → empty graph → doctor surfaces the `.corrupt-*` artifact.
- **State/schema:** possible `graph.pkl.corrupt-<ts>` files under `.cognirepo/graph/`;
  back-compat unaffected.
- **Dependencies:** sequenced with 102 (same file); implement after 102 merges.
- **Test oracle:** AC2 item 3 — reindex a fixture file with a removed function → node absent;
  AC4 — write garbage to graph.pkl → load → quarantine file exists, doctor flags it.

### COGNIREPO-104 — verify-index working-tree staleness
- **Context/Why:** D100 §3 — `_cmd_verify_index` (`main.py:142-230`) is commit-based; dirty
  files never flag stale.
- **Files:** `interface/cli/main.py` (`_cmd_verify_index`), `tests/test_doctor_expanded.py` or
  new test.
- **Interface contract:** CLI-only. Adds `git status --porcelain` check over indexed extensions;
  output gains a `DIRTY` line and exit code 1 when indexed sources have uncommitted changes newer
  than `indexed_at`.
- **Data flow:** verify-index → existing manifest read → new: `git status --porcelain` +
  per-file mtime vs manifest `indexed_at`.
- **State/schema:** none.
- **Dependencies:** none.
- **Test oracle:** AC3 — modify a tracked file in a fixture repo, run verify-index, exit code 1
  with DIRTY line.

### COGNIREPO-105 — Layer-invariant cleanup (upward imports)
- **Context/Why:** D100 §1b — 5 runtime upward imports into `interface.*` from data/intelligence
  plus data→intelligence skips; CHANGELOG 2.0.0's "0 violations" holds only for module level.
- **Files:** `data/graph/behaviour_tracker.py:540` (inject `store_fn` callable per
  IMPROVEMENTS.md:19-23 suggestion), `intelligence/orchestrator/context_builder.py:270`,
  `intelligence/indexer/summarizer.py:395,451`, `intelligence/indexer/ast_indexer.py:1911`
  (progress-UI callback injection), `data/graph/cross_service_path.py:62,128`,
  `data/graph/behaviour_tracker.py:513`, `scripts/check_circular_deps.py` (teach it to catch
  function-local imports), IMPROVEMENTS.md (refresh).
- **Interface contract:** none (internal refactor; injection parameters default to None →
  behavior unchanged).
- **Data flow:** callers at the interface layer supply the callback (e.g. `mcp_server`/CLI pass
  `store_memory` into `BehaviourTracker(...)`); library layers never import upward.
- **State/schema:** none. Back-compat: constructor kwargs additive with defaults.
- **Dependencies:** none; independent of 101-104.
- **Test oracle:** AC5 — the grep in AC5 returns empty (runtime imports);
  `python scripts/check_circular_deps.py` passes with lazy-import detection enabled; full pytest
  stays green.

### COGNIREPO-106 — Docs truth pass
- **Context/Why:** D100 §1c/§2/§5/§6 — FEATURES §15 (17 vs 85 test files), §16/§17 stale
  CALLS_API claim, README Future Plans "v0.3.0/v0.4.0" headers, SECURITY.md:118 Snyk vs actual
  pip-audit, IMPROVEMENTS.md stale counts, `interface/cli/docs_index.py` shim past its
  removal date, METRICS.md pre-fix zeros footnoted but not re-run (re-run itself is
  COGNIREPO-601).
- **Files:** `docs/FEATURES.md`, `README.md`, `SECURITY.md`, `IMPROVEMENTS.md`,
  `docs/MCP_TOOLS.md` (spot-fix drifted defaults), `interface/cli/docs_index.py` (delete —
  in-repo importers already use the new path; flag in CHANGELOG under Unreleased/Removed).
- **Interface contract / data flow / state:** docs only, plus one dead-shim deletion (grep shows
  no runtime importer — D100 §1c).
- **Dependencies:** after 101 (so tool counts written into docs are the generated truth).
- **Test oracle:** AC7 — `tests/test_documentation.py` (exists, D100 §6 inventory) extended to
  assert FEATURES §15 count matches `len(glob tests/test_*.py)`; grep for "v0.3.0" under Future
  Plans returns nothing; shim file absent; suite green.

## Defects

- **COGNIREPO-D01 — manifest.json/glama.json missing `find_symbol_path` + `get_service_endpoints`
  (regression of [1.1.3]).** Hotfix: re-add both entries by running the [1.1.3] procedure
  (add to `_build_manifest()`, regenerate). Evidence D100 §1b. Test oracle: AC1 set-equality.
  Superseded structurally by 101 but shipped first as the minimal patch.
- **COGNIREPO-D02 — episodic event-ID collision after rotation.** `episodic_memory.py:150`
  `e_{len(data)}` vs rotation trim `:43-61`. Fix: monotonic counter persisted in the store (e.g.
  `"next_id"` header record or max-existing+1 scan on load); migration: leave old IDs, ensure new
  ones unique; dedupe `id_to_entry` guard. Oracle: unit test — fill past cap, rotate, assert all
  live+archived IDs unique and `prev` chain consistent.
- **COGNIREPO-D03 — requirements.txt reverts CVE fixes (uncommitted).** Evidence D100 §5
  (commits `779b113`, `6083b15`; GHSA-537c-gmf6-5ccf named). Action: `git checkout --
  requirements.txt` after user confirms no intentional pin; add a CI job step auditing
  `requirements.txt` pins explicitly (pip-audit `-r requirements.txt`) so the gap where CI audits
  only pyproject (D100 §5) is closed. **Needs human decision before execution.**

## Architecture-rule compliance

All stories operate inside existing layers; 105 *restores* the layer invariant. No CLAUDE.md
amendments required in this phase. No new MCP tools; manifest grows only by restoring the two
already-live tools (+~210 tokens that agents were already paying via `tools/list`).

## Version bump

**2.0.1** — pure fixes/regressions/doc corrections; the only schema-visible change restores
already-registered tools. Escalation rule: if D03's CI addition or 102's config key is judged
user-visible-additive, this may ship as 2.1.0 — default is patch.

## Risks / open questions

- D03 requires the user's intent (why was the file downgraded locally?) — blocked on human.
- k8s/moby-scale behavior of the P0 fixes is verified by code+unit tests only
  (cannot-determine-without-running at that scale); a scale re-run is deferred to Phase 5
  benchmark work.
- Debounce default (500 ms) is a guess; needs tuning on the `advanced` test repo.
- Deleting the `cli/docs_index` shim is technically breaking for out-of-tree importers; justified
  because its docstring already declared removal at v2.0 (D100 §1c) — call it out in CHANGELOG.
