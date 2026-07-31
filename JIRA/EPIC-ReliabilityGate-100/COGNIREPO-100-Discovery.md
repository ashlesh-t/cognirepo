# COGNIREPO-100 Discovery — Reliability Gate (Phase 0 audit)

All findings verified against HEAD (`146627d`, branch `development`, v2.0.0) on 2026-07-11.
Nothing below is copied from stale docs — every claim carries fresh file:line evidence.

---

## 1. Ground Rule 1 re-verification

### 1a. v1.1.0 QA NO-GO P0 blockers (memory file `project_v110_release_qa.md`, 2026-06-11)

| # | P0 blocker | Verdict at HEAD | Evidence |
|---|---|---|---|
| 1 | Long-lived MCP server never reloads FAISS index | **FIXED** | `core/vector_db/local_vector_db.py:75` caches `_loaded_disk_mtime`; `_disk_mtime()` at `:80-85`; `_maybe_reload()` at `:90-108` (keeps in-memory snapshot on reload failure); called from read paths at `:282` and `:315` |
| 2 | AST index JSON corruption (73 MB k8s file, no atomic write/self-heal) | **FIXED** | `intelligence/indexer/ast_indexer.py:2051-2063` `_atomic_json_dump()` (tmp + `os.replace`); `:2066-2078` `_load_json_self_heal()` renames corrupt file to `.corrupt` and returns default; used at `:2089`, `:2092`, `:2135`, `:2156` |
| 3 | `context_pack` empty on kubernetes (staging/ skipped) | **FIXED** | `ast_indexer.py:84-87` — comment + code: "staging" deliberately NOT skipped; `:131-141` adds `indexing.skip_dirs`/`unskip_dirs` config override |
| 4 | `subgraph(depth=3)` RSS blowup past 2 GB | **FIXED** | `data/graph/knowledge_graph.py:283-354` `subgraph_around()` — bounded BFS (`max_nodes=200`, `max_edges=500`), hub skip (`hub_degree_limit=500` at `:316-317`), `truncated` flag; docstring `:294-300` explains the old `nx.ego_graph` failure mode |

Residual: k8s-scale behavior of these fixes is **cannot-determine-without-running** on a 2M-LOC
repo; the code paths are present and unit-tested (full suite green, see §6). The memory file's
2026-06-12 update also attributes the original breaker trips to `.env.example` shipping an active
`COGNIREPO_CB_RSS_LIMIT_MB=2000` — the shipped `.env.example` at HEAD has values commented.

### 1b. IMPROVEMENTS.md claims

**Claim 2 — "4 MCP tools missing from `_build_manifest()`" (IMPROVEMENTS.md:27-45): PARTIALLY STALE, and the remaining half is a REGRESSION.**

Exact reconciliation at HEAD:

- `grep -c "@mcp.tool()" interface/server/mcp_server.py` → **35**, but one hit is a comment at
  `mcp_server.py:2587` ("Set of tool names registered via @mcp.tool()"). Real decorators: **34**
  (list extracted, zero duplicates). The live MCP server exposes 34 tools.
- `interface/server/manifest.json` → **32** tools.
- Diff (in code, not in manifest): `find_symbol_path`, `get_service_endpoints`. Nothing is in the
  manifest that isn't in code.
- IMPROVEMENTS.md also lists `search_token` and `get_agent_bootstrap` as missing — **both ARE in
  the manifest at HEAD** (that half of the claim is stale).
- CHANGELOG.md:62 ([1.1.3], 2026-06-17): *"`server/manifest.json` missing 2 tools —
  `find_symbol_path` and `get_service_endpoints` … Both entries added"*. They are missing again at
  HEAD → the 2.0.0 manifest rewrite **regressed the exact [1.1.3] fix**.
- The doctor's schema-validation set `_REGISTERED_TOOLS` (`mcp_server.py:2588-2600`) correctly
  contains all 34 including the two missing ones — so doctor's source of truth and the manifest
  disagree.
- `version.yml` mcp.description claims "34 MCP tools"; README.md:18 claims "the 34 MCP tools".

**Root cause (new finding): tool schemas are maintained in THREE hand-written copies** —
(1) `@mcp.tool()` decorated signatures/docstrings, (2) `_build_manifest()` in
`interface/server/mcp_server.py` (written to `manifest.json` by `_write_manifest()` at `:2580-2584`),
(3) `glama.json` (32 tools, same two missing, plus drifted defaults — e.g. `get_session_history`
`limit` default 5 in glama.json vs 10 in code at `mcp_server.py:1697`; `link_repos` description
still says "CALLS_API … must be declared manually", stale per §4 below). A fourth artifact,
`interface/adapters/openai_tools.json`, is generated from the manifest but was last regenerated
long ago — it contains only **13 tools** — and its generator `interface/adapters/openai_spec.py:27`
still reads the pre-2.0.0 path `MANIFEST_PATH = "server/manifest.json"` (CWD-relative and wrong),
falling back to an upward import of `_write_manifest`.

**Claim 1 — `data/graph/behaviour_tracker.py` upward import: STILL TRUE.**
`behaviour_tracker.py:540` — `from interface.tools.store_memory import store_memory` inside
`summarize_interaction_style()`. Additionally, the full upward-import sweep found more
layer-invariant violations (all lazy/function-local; CHANGELOG [2.0.0] claims "hard circular-dep
violations drop … to 0" — true only for module-level imports):

- `intelligence/orchestrator/context_builder.py:270` → `interface.server.mcp_server._write_manifest`
- `intelligence/indexer/summarizer.py:395` and `:451` → `interface.tools.bg_progress`
- `intelligence/indexer/ast_indexer.py:1911` → `interface.tools.bg_progress`
- data → intelligence (skips a layer upward): `data/graph/cross_service_path.py:62` (ASTIndexer),
  `:128` (CrossRepoRouter); `data/graph/behaviour_tracker.py:26` (TYPE_CHECKING — acceptable) and
  `:513` (`create_watcher`, runtime)

### 1c. README "Future Plans" / FEATURES.md §16 spot-checks

- README.md:609-637 "Future Plans" headers still say **"Near-term (v0.3.0)" / "Medium-term
  (v0.4.0)"** at shipped version 2.0.0 — stale framing.
- **STALE**: FEATURES.md §16/§17 ("Automatic CALLS_API edge detection — ❌ No … must be declared
  manually") — contradicted by `intelligence/indexer/http_call_scanner.py` (exists),
  `cognirepo org rewire` (CLAUDE.md commands; handler in `interface/cli/main.py`), doctor's "org
  CALLS_API check" (`main.py:864`), and `data/graph/org_graph.py:216,283` (function-level
  CALLS_API annotations). `glama.json`'s `link_repos` description repeats the stale claim.
- **STILL ACCURATE**: "Similarity edges … not yet implemented" — no `SIMILAR` edge type anywhere
  in `data/graph/` or `intelligence/` (grep clean); CHANGELOG [1.1.3] removed SIMILAR_TO from docs.
- **PARTIALLY STALE**: "Go call-graph indexing … call extraction is incomplete" —
  `ast_indexer.py:415` handles `call_expression` for JS/Java/Go, and the QA memory records "Go
  `type_spec` types" landing 2026-06-11; completeness vs the claim needs a Go-repo run
  (cannot-determine-without-running; scheduled in COGNIREPO-203).
- FEATURES.md §15 test inventory lists **17** test files; `tests/` contains **85** `test_*.py`
  files — the inventory is badly stale.
- `interface/cli/docs_index.py` is a deprecation shim whose own docstring says **"Removed in
  v2.0"** yet it still ships at 2.0.0 (only importer is itself; tests and runtime use
  `intelligence.indexer.docs_index`).

---

## 2. MCP tool contract pass

- `docs/MCP_TOOLS.md` documents **34** tools (all 34 registered names, including deprecated
  `org_search` marked as replaced by `org_wide_search` at MCP_TOOLS.md:353,656). No unregistered
  or duplicate tools found; doc/tool name parity is clean.
- Signature drift found in the *derived* artifacts, not in MCP_TOOLS.md: `glama.json`
  `get_session_history.limit` default 5 vs code default 10 (`mcp_server.py:1697`);
  `openai_tools.json` has 13 of 34 tools.
- Tool-schema token footprint (Ground Rule 3 baseline): manifest.json's 32 tool entries =
  **3,380 tokens** (cl100k_base), avg ~105/tool, max `link_repos` 252. README.md:56's "~4,100
  tokens for 34 tools" is plausible once the two missing tools and MCP `tools/list` docstring
  overhead are included — treated as approximately honest. **Every proposed new tool costs
  ~100-250 manifest tokens** and must justify itself per Ground Rule 3.

---

## 3. Indexing reliability audit (the user's top pain point)

- **No debounce** (README.md:616 roadmap claim CONFIRMED): `intelligence/indexer/file_watcher.py`
  (187 lines) fires `_reindex()` synchronously per watchdog event (`:59-67`); editors emitting
  multiple events per save trigger repeated work; every single event does
  `self.indexer.save()` + `self.graph.save()` (`:153-154`) — full-index persistence per keystroke
  burst on large repos.
- **No `on_moved` handler**: `RepoFileHandler` implements only `on_modified`/`on_created`/
  `on_deleted` (`file_watcher.py:59-72`). A file rename emits `FileMovedEvent` → old path stays
  in the AST index, reverse index, and graph; the new path is not indexed until separately
  modified. This is the core "reverse indexing under renames/moves" gap.
- **Orphan graph nodes on modify**: `_reindex()` at `file_watcher.py:146-148` calls
  `graph.remove_node_edges(node_id)` (removes edges, keeps node —
  `knowledge_graph.py:189-192`) for stale nodes, then re-indexes. Symbols deleted from the file
  leave permanent orphaned nodes. The delete path (`_remove()` → `remove_file_nodes()`,
  `knowledge_graph.py:200-219`) is correct and removes nodes.
- Per-file staleness inside the indexer is sound: sha256 skip at `ast_indexer.py:1468,1493-1496`;
  reverse index rebuilt incrementally per file (`:1664-1678`) and fully (`:1754-1764`).
- `cognirepo verify-index` (`interface/cli/main.py:142-230+`): platform compat, checksum
  verification of the three index files, and git-commit staleness. Gap: staleness is
  **commit-based only** — uncommitted working-tree edits are invisible to it (checksums cover the
  index files themselves, not sources).
- `cognirepo doctor` (`main.py:342+`) includes AST validity (`:813`), doc-index (`:842`), org
  CALLS_API (`:864`), behaviour hook (`:770`) checks.

---

## 4. Knowledge-graph audit

- Corruption/recovery: `knowledge_graph.py:110-138` — on any load failure, warn + start with an
  **empty graph**, corrupt `graph.pkl` left in place to be silently overwritten by the next
  `save()`. No quarantine (contrast: AST index renames to `.corrupt`), no backup, no automatic
  rebuild trigger. Encrypted-file plaintext-fallback self-heal exists (`:119-130`).
- `save()` (`:144-163`) is safe: circuit-breaker check, cross-process `store_lock()`, encryption.
- Orphan sources: see §3 (modify-path edge-only removal). `remove_file_nodes()` matches nodes by
  `file` attr + FILE node by id (`:194-219`) — correct for deletes, unused for renames (no event).
- Subgraph memory: bounded (see §1a P0-4). `stats()` at `:358-363` returns node/edge counts only —
  no orphan/integrity metrics for doctor to consume.

---

## 5. Dependency / security posture

- CI gates at HEAD (`.github/workflows/security.yml`): **Bandit** (HIGH+CRITICAL, layer paths
  updated for 2.0.0), **pip-audit** (with 2 documented CVE ignores), **Trivy** (fs scan,
  HIGH/CRITICAL, fail on findings), **TruffleHog** (verified secrets, full history).
  `SECURITY.md:118` claims **Snyk** — not present in any workflow → doc drift.
- pip-audit runs against `pip install .` (pyproject constraints), **not** `requirements.txt`
  pins — the pinned file is not what CI audits.
- **Uncommitted `requirements.txt` diff reverts committed CVE fixes.** Working tree downgrades:
  cryptography 48.0.1→47.0.0, PyJWT 2.13.0→2.12.1, starlette 1.3.1→1.0.0, urllib3 2.7.0→2.6.3
  (python-multipart moves 0.0.30→0.0.32, an upgrade). Git history: `779b113` "fix(deps): bump
  cryptography 47.0.0 → 48.0.1 (**GHSA-537c-gmf6-5ccf**)" and `6083b15` "fix(deps): bump PyJWT,
  python-multipart, starlette, urllib3 for CVEs". The diff therefore re-introduces at least one
  named vulnerability. Local pip-audit execution unavailable (offline) — exact CVE set for the
  other pins is cannot-determine-locally. **Recommendation: `git checkout -- requirements.txt`
  unless the user states an intentional reason** (e.g. a compat pin — none found in code or docs).

---

## 6. Test coverage audit

- Full suite executed at HEAD: `venv/bin/python -m pytest tests/ -q` →
  **1203 passed, 5 skipped, 0 failed** in 100.42 s.
- The QA verdict's "~14 unexecuted tests" were sections of `MANUAL_TEST_SUITE.md` (§2.1-moby,
  §2.2, §2.4, §3.4, §6.1, §8.1, §8.6, §10.1, §14–§18.3, §19.4, §20.1-2, §21.x per the memory
  file). **Neither `MANUAL_TEST_SUITE.md` nor `RELEASE_READINESS_v1.1.0.md` exists in the repo at
  HEAD** (find returns nothing) — those manual tests are unrunnable from any in-repo artifact.
  Verdict: **superseded**; the JIRA TEST_SUITE.md files created by this epic become the manual
  suite of record.
- FEATURES.md §15 lists 17 test files vs 85 actual — inventory refresh needed (see §1c).

---

## 7. Test-repo fixture inventory (for TEST_SUITE.md files)

`ls /home/ashlesh/my_works/cognirepo_test_repo/` → directories: **`advanced`, `dummy`, `easy`,
`medium`, `private-org`** (plus `benchmark.py`, `litellm_config.yaml`, `test_repos.zip`). All
TEST_SUITE cases reference only these five.

---

## 8. Defect / story derivation

Defects (broken behavior found): D01 manifest regression (§1b), D02 episodic ID collision
(see 200-Discovery §2 — surfaced during this audit, fixed under this gate because it corrupts
existing data), D03 requirements.txt CVE-revert diff (§5).
Stories (hardening of known-incomplete behavior): single-source manifest generation (§1b root
cause), watcher debounce/on_moved/orphans (§3), verify-index working-tree staleness (§3),
graph.pkl quarantine (§4), layer-invariant cleanup (§1b), docs truth pass (§1c, §2, §5, §6).
