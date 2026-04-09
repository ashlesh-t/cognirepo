# CogniRepo — Production Hardening Sprint

> **Mission:** Take CogniRepo from ~82% OSS-ready to **100% production-reliable**. Fix every critical bug, close every documentation gap, harden DX, and ship a release that a stranger can `pip install` and use without hitting a single foot-gun.

---

## 📌 Note for Claude CLI (READ FIRST)

**Use the CogniRepo MCP server wherever possible to minimize token usage.**

Before reading raw files for any task below, prefer these CogniRepo MCP tools:

- `context_pack` — pull only the relevant slice of code/context for a task instead of `cat`-ing whole files
- `semantic_search_code` — locate symbols/functions without scanning directories
- `dependency_graph` — understand call sites and impact radius before editing
- `explain_change` — summarize diffs without re-reading the whole file
- `episodic_memory` — recall prior decisions/discussions about the file you're touching

**Rule of thumb:** If a task references a file path, route through `context_pack` first. Only fall back to direct file reads when the MCP tool is unavailable or returns insufficient context. Every avoided raw read = saved tokens + faster iteration.

If a CogniRepo MCP tool fails or is missing, log it as a sprint blocker in /temp/blocker.md — that itself is a reliability signal.But u dont stop , resolve the issue by using normal claude cli tools and resolve that issue and go , alwas sequentially, when an issue got log that issue and resolve , while logging also log at what point ogf time this issue was notified

---

## Sprint Goals

1. **Zero-crash fresh install** — `pip install cognirepo && cognirepo init && cognirepo daemon start` works on a clean machine, every time, on Linux/macOS/Windows.
2. **Documentation = Code** — every claim in docs is verifiable against the implementation.
3. **Honest CI** — no silently swallowed failures. Red means red.
4. **Test isolation** — pytest never touches `~/.cognirepo`.
5. **Friendly first run** — `cognirepo init` leaves the user with a working, indexed repo.

---

# SPRINT 1 — Critical Bug Fixes (Ship-Blockers)

> These four bugs make fresh installs unusable. Fix first, release patch version immediately after.

---

## Task 1.1 — Declare `rank_bm25` as a hard dependency

**Context**
`memory/episodic_memory.py` imports `rank_bm25` for keyword retrieval, but it is missing from `pyproject.toml`. On a fresh install the first call to `episodic_search` raises `ModuleNotFoundError`. Either it's a real dependency (declare it) or it's optional (gate it behind a try/except with a Python fallback).

**Decision required:** Hard dep is simpler and matches the C++/BM25 design intent. Go with hard dep unless there's a packaging reason not to.

**Acceptance Criteria**
- `rank_bm25` listed under `[project.dependencies]` in `pyproject.toml` with a pinned minor version
- Fresh `pip install .` in a clean venv installs it automatically
- New test `tests/test_fresh_install.py::test_episodic_search_no_import_error` passes
- `cognirepo init` followed by an `episodic_search` call succeeds end-to-end

**Definition of Done**
- [ ] Dependency declared and pinned
- [ ] Lockfile / `requirements.txt` regenerated
- [ ] Test added and green in CI
- [ ] Manually verified in a fresh Docker container (`python:3.11-slim`)
- [ ] CHANGELOG entry under `Fixed`

---

## Task 1.2 — Remove `print()` from `memory/semantic_memory.py:51`

**Context**
MCP servers communicate over stdio using JSON-RPC framing. **Any** stray write to stdout corrupts the framing and breaks the client. Line 51 of `semantic_memory.py` has a `print()` (likely a debug leftover) that breaks every `store_memory` call routed through MCP.

**Acceptance Criteria**
- The `print()` at `memory/semantic_memory.py:51` is removed or replaced with `logger.debug(...)` writing to stderr
- A repo-wide grep `rg "^\s*print\(" cognirepo/` returns zero hits in non-CLI modules
- New CI guard: `scripts/check_no_stdout_pollution.py` runs in CI and fails on any `print(` outside `cognirepo/cli/`
- Integration test `tests/test_mcp_stdio.py::test_store_memory_via_stdio` passes (spawns the MCP server, sends a `store_memory` request, asserts valid JSON-RPC response)

**Definition of Done**
- [ ] Offending `print()` removed
- [ ] Logger configured to stderr at module level
- [ ] CI guard script added and wired into the pipeline
- [ ] Stdio integration test added and green
- [ ] CHANGELOG entry under `Fixed`

---

## Task 1.3 — Honor `--project-dir` in `orchestrator/session.py`

**Context**
`orchestrator/session.py:46` hardcodes `.cognirepo/sessions` at **module load time**, which means the path is captured before any CLI flag is parsed. Result: `--project-dir /tmp/foo` correctly isolates everything *except* sessions, which still leak into the global `~/.cognirepo`.

**Fix shape:** Move the path resolution into a function/property that reads from the active `Config` object at call time, not at import time.

**Acceptance Criteria**
- Sessions directory is resolved lazily from `Config.project_dir`, not at import
- New test `tests/test_session_isolation.py::test_project_dir_isolates_sessions` creates two distinct project dirs, opens a session in each, and asserts the session files land under the correct path with no cross-contamination
- Removing `~/.cognirepo` between test runs does not break the test (no hidden global writes)

**Definition of Done**
- [ ] Module-level constant removed
- [ ] Lazy resolver in place
- [ ] Isolation test added and green
- [ ] Verified manually with two parallel `--project-dir` invocations
- [ ] CHANGELOG entry under `Fixed`

---

## Task 1.4 — Fix FAISS rebuild path in `cron/prune_memory.py`

**Context**
`cron/prune_memory.py:44` writes the rebuilt FAISS index to a relative `./vector_db/` path, which resolves to wherever the cron job happened to be invoked from — usually **not** `.cognirepo/vector_db/`. The pruner runs, succeeds, and the result is silently discarded. The next query still hits the unpruned index.

**Acceptance Criteria**
- Path resolved via `Config.vector_db_path` (or equivalent), never relative
- Pruner refuses to write outside the configured project root (raise + log)
- New test `tests/test_prune_memory.py::test_rebuild_writes_to_configured_path` runs the pruner against a temp project dir and asserts the rebuilt index file exists at the expected absolute path
- Old stray `./vector_db/` directories created by previous bad runs are detected and warned about on startup

**Definition of Done**
- [ ] Path resolution fixed
- [ ] Safety guard added (no writes outside project root)
- [ ] Test added and green
- [ ] Startup warning for stray directories implemented
- [ ] CHANGELOG entry under `Fixed`

---

# SPRINT 2 — Documentation Truthfulness

> Docs currently lie about the system. Fix until every claim is verifiable.

---

## Task 2.1 — Reconcile retrieval signal count (3-signal vs 4-signal)

**Context**
Docs (README, ARCHITECTURE.md, FEATURE.md) repeatedly claim "4-signal retrieval." The actual implementation is a **3-signal weighted merge**: vector + graph + behaviour. AST is a pre-scorer (not a merge input), and episodic memory is a separate pipeline. Either the docs are wrong or the code is incomplete.

**Decision required:** Confirm with implementation. If code is correct → fix docs. If a 4th signal was intended → file a follow-up task and fix docs to "3-signal" in the meantime.

**Acceptance Criteria**
- Every doc reference to signal count matches the code
- A single canonical diagram in `docs/architecture/retrieval.md` shows the actual pipeline: AST pre-scorer → 3-signal merge → episodic side-channel
- `grep -r "4-signal" docs/` returns zero hits (or all hits are in a clearly marked "Future Work" section)

**Definition of Done**
- [ ] All docs updated
- [ ] Canonical diagram added (real PNG/SVG, not 0-byte placeholder — see Task 2.5)
- [ ] PR description explains the discrepancy and the resolution
- [ ] Follow-up issue filed if a 4th signal is genuinely planned

---

## Task 2.2 — Refresh classifier tier thresholds in ARCHITECTURE.md

**Context**
The complexity classifier thresholds in `ARCHITECTURE.md` are stale — code has been updated, docs have not. Anyone reading the architecture doc gets a wrong mental model of routing behavior.

**Acceptance Criteria**
- Thresholds in `ARCHITECTURE.md` match the constants in the classifier module exactly
- A test `tests/test_docs_sync.py::test_classifier_thresholds_match_docs` parses the doc and asserts value parity with the code constants (single source of truth check)

**Definition of Done**
- [ ] Doc updated
- [ ] Sync test added and green
- [ ] Comment in classifier module pointing to the doc section it mirrors

---

## Task 2.3 — Align edge type names between docs and code

**Context**
Docs use edge names `CONTAINS`, `CALLS`, `USES`. Code uses `DEFINED_IN`, `CALLED_BY`, `RELATES_TO`. Users following the docs will write graph queries that return empty results.

**Decision required:** Code names are more precise (`CALLED_BY` vs `CALLS` makes direction explicit). Keep code names, fix docs.

**Acceptance Criteria**
- All edge type references in `docs/` match `cognirepo/graph/schema.py` (or wherever they're defined)
- A glossary table added to `docs/architecture/graph.md` listing each edge type, its direction, and an example query
- `tests/test_docs_sync.py::test_edge_types_match_docs` scrapes the glossary and asserts coverage of all enum values

**Definition of Done**
- [ ] Docs updated
- [ ] Glossary added
- [ ] Sync test green
- [ ] At least one example graph query per edge type in the docs

---

## Task 2.4 — Fix non-existent package versions in `requirements.txt`

**Context**
`requirements.txt` pins `faiss-cpu==1.13.2` and `starlette==1.0.0` — neither version exists on PyPI. `pip install -r requirements.txt` fails immediately. These look like typos or hallucinated versions.

**Acceptance Criteria**
- Pin to the latest stable versions that actually exist on PyPI as of the sprint date
- `pip install -r requirements.txt` succeeds in a clean Python 3.11 venv
- CI job `verify-requirements` added: spins up a clean container and runs `pip install -r requirements.txt` on every PR
- Dependabot or equivalent configured to flag future drift

**Definition of Done**
- [ ] Versions corrected
- [ ] Clean install verified in Docker
- [ ] CI job added and green
- [ ] Dependency update automation enabled

---

## Task 2.5 — Generate real architecture diagrams (replace 0-byte placeholders)

**Context**
Every PNG in `docs/architecture/` is a 0-byte placeholder. The docs reference them, the rendered site shows broken images, and contributors have no visual mental model of the system.

**Acceptance Criteria**
- Diagrams generated from a versioned source (Mermaid, PlantUML, or Excalidraw `.excalidraw` JSON checked into the repo)
- Minimum diagrams: (1) high-level component map, (2) retrieval pipeline, (3) MCP request lifecycle, (4) graph schema
- All PNGs are non-zero bytes and render correctly in the GitHub-rendered docs
- A `make diagrams` (or `scripts/build_diagrams.sh`) target regenerates them from source

**Definition of Done**
- [ ] Source files committed
- [ ] PNGs regenerated and committed
- [ ] Build script added
- [ ] CI check: `find docs -name "*.png" -size 0` fails the build

---

# SPRINT 3 — DX & Reliability

> Fix the foot-guns that don't crash the build but ruin the user experience.

---

## Task 3.1 — Stop swallowing REST API test failures

**Context**
`test_api.py` runs with `|| true` in the CI workflow, meaning REST adapter failures are silently green. We have no idea if the REST surface actually works.

**Acceptance Criteria**
- `|| true` removed from the CI step running `test_api.py`
- All currently-failing tests in `test_api.py` either fixed or explicitly marked `@pytest.mark.xfail(reason="...", strict=True)` with a tracking issue link
- CI fails on any new REST regression

**Definition of Done**
- [ ] CI workflow updated
- [ ] All tests passing or explicitly xfailed
- [ ] Tracking issues filed for any xfails
- [ ] One full CI run shows the REST tests actually executing and reporting

---

## Task 3.2 — Isolate `memory/user_memory.py` from real `~/.cognirepo` during tests

**Context**
`memory/user_memory.py` writes to the actual `~/.cognirepo/user/` directory during pytest runs. This pollutes the developer's machine, leaks state between test runs, and makes CI flaky depending on runner state.

**Acceptance Criteria**
- A pytest fixture `isolated_cognirepo_home` (autouse in the relevant test module, or session-scoped) redirects `~/.cognirepo` to a `tmp_path` for the duration of the test
- `monkeypatch.setenv("HOME", ...)` or equivalent — depending on how the path is resolved
- New regression test: `tests/test_isolation.py::test_no_writes_to_real_home` runs the suite and asserts the real `~/.cognirepo` is unchanged (mtime check)

**Definition of Done**
- [ ] Fixture added and applied
- [ ] Regression test green
- [ ] Documented in `CONTRIBUTING.md` under "Test isolation"

---

## Task 3.3 — Friendly OS check on `cognirepo daemon start`

**Context**
`cognirepo daemon start` throws a raw `ImportError` on macOS and Windows because the daemon module imports Linux-only primitives (`fcntl`, etc.) at the top of the file. Users get a stack trace instead of a useful message.

**Acceptance Criteria**
- `cognirepo daemon start` checks `sys.platform` before importing Linux-only modules
- On macOS/Windows, prints a clear message: e.g. `"The CogniRepo daemon currently supports Linux only. On macOS/Windows, run 'cognirepo serve' for foreground mode."` and exits with code 2
- Linux-specific imports moved inside the function/class that needs them (lazy import)
- Test `tests/test_cli_daemon.py::test_daemon_start_friendly_error_on_unsupported_os` mocks `sys.platform` and asserts the friendly message

**Definition of Done**
- [ ] OS check added
- [ ] Lazy imports in place
- [ ] Test added and green on Linux runner (with platform mocking)
- [ ] `cognirepo serve` foreground mode verified to work on macOS

---

## Task 3.4 — Make `cognirepo init` actually initialize

**Context**
`cognirepo init` creates the directory structure but does **not** run `index-repo`. Result: every graph/AST tool returns empty until the user runs a second, undocumented command. First-run experience is broken.

**Acceptance Criteria**
- `cognirepo init` runs `index-repo` automatically by default
- A `--no-index` flag is available for users who want to skip (e.g., huge monorepos)
- Progress is shown during indexing (tqdm or similar)
- After `cognirepo init`, an immediate `cognirepo query "..."` returns non-empty results on a sample repo
- E2E test `tests/test_e2e_init.py::test_init_then_query` clones a tiny fixture repo, runs init, and asserts a query returns results

**Definition of Done**
- [ ] `init` command updated
- [ ] `--no-index` flag added and documented
- [ ] Progress indicator working
- [ ] E2E test added and green
- [ ] README "Quickstart" updated to reflect the new one-command flow

---

# SPRINT 4 — Release Readiness

> Final polish before tagging a release.

---

## Task 4.1 — Full smoke test on all supported platforms

**Context**
Run the full quickstart flow (`pip install` → `cognirepo init` → query → daemon start → MCP call) on Linux, macOS, and Windows in CI. Any failure blocks the release.

**Acceptance Criteria**
- GitHub Actions matrix job: `{ubuntu-latest, macos-latest, windows-latest} × {python 3.10, 3.11, 3.12}`
- Each cell runs the smoke test script `scripts/smoke_test.sh` (or `.ps1` for Windows)
- All cells green before tagging

**Definition of Done**
- [ ] Matrix job added
- [ ] Smoke test scripts written for each OS
- [ ] All cells green on a release-candidate branch
- [ ] Release notes mention tested platforms

---

## Task 4.2 — CHANGELOG and version bump

**Context**
Aggregate all fixes from Sprints 1–3 into a single CHANGELOG entry. Bump version following semver (likely a minor bump given the bug fixes + DX improvements).

**Acceptance Criteria**
- `CHANGELOG.md` updated with sections: `Fixed`, `Changed`, `Added`, `Documentation`
- Version bumped in `pyproject.toml` and any `__version__` constant
- Git tag created
- GitHub release drafted with copy-pasted CHANGELOG section

**Definition of Done**
- [ ] CHANGELOG complete
- [ ] Version bumped consistently across the repo
- [ ] Tag pushed
- [ ] Release published

---

## Task 4.3 — Post-release verification

**Context**
After publishing to PyPI, verify the published artifact actually works — not just the local checkout.

**Acceptance Criteria**
- In a fresh Docker container, `pip install cognirepo==<new_version>` succeeds
- Quickstart flow runs end-to-end against the published package
- No imports of dev-only paths (e.g., editable-install artifacts)

**Definition of Done**
- [ ] Verified in Docker
- [ ] Verified on a real macOS machine if available
- [ ] Issue closed: "v<X.Y.Z> released and verified"

---

# Summary Checklist

**Sprint 1 — Critical Bugs**
- [ ] 1.1 Declare `rank_bm25`
- [ ] 1.2 Remove stdout `print()` from semantic_memory
- [ ] 1.3 Honor `--project-dir` in sessions
- [ ] 1.4 Fix FAISS rebuild path

**Sprint 2 — Documentation Truthfulness**
- [ ] 2.1 Reconcile signal count
- [ ] 2.2 Refresh classifier thresholds
- [ ] 2.3 Align edge type names
- [ ] 2.4 Fix non-existent package versions
- [ ] 2.5 Generate real architecture diagrams

**Sprint 3 — DX & Reliability**
- [ ] 3.1 Stop swallowing REST test failures
- [ ] 3.2 Isolate user_memory tests
- [ ] 3.3 Friendly daemon OS check
- [ ] 3.4 Make `init` actually initialize

**Sprint 4 — Release Readiness**
- [ ] 4.1 Multi-platform smoke tests
- [ ] 4.2 CHANGELOG + version bump
- [ ] 4.3 Post-release verification

---

## Reminder

**Use `cognirepo` MCP tools (`context_pack`, `semantic_search_code`, `dependency_graph`, `explain_change`) instead of raw file reads wherever possible. This sprint is also a dogfooding exercise — if a CogniRepo tool can't help you fix CogniRepo, that's a bug worth filing.**