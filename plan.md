# CogniRepo 100% Execution Plan

**Goal:** Bridge CogniRepo from 92% to 100% completeness by introducing local cross-repository reasoning via "Orgs", implementing advanced hierarchical RAG (RAPTOR-like summarization), and drastically simplifying the architecture by removing legacy REST and gRPC transports in favor of a pure MCP (Model Context Protocol) approach. Focus is strictly on local-first workflows.

---

## Phase 1: Transport Simplification (Pure MCP)
**Objective:** Reduce architectural complexity and maintenance burden by completely removing REST and gRPC. MCP becomes the sole communication layer.

### Tasks
- [ ] **Remove REST API:**
  - Delete the `server/api/` (or similar) directories containing FastAPI app, routes, JWT auth, and Redis cache.
  - Remove REST-specific dependencies from `requirements.txt` and `pyproject.toml`.
  - Remove `cognirepo wait-api` command.
- [ ] **Remove gRPC:**
  - Delete `.proto` files and generated Python stubs.
  - Remove gRPC server implementation and client stubs.
  - Remove `make proto` from `Makefile` and CI checks.
- [ ] **Cleanup CLI & Doctor:**
  - Update `cli/main.py` and `cli/daemon.py` to remove HTTP/gRPC server startup logic.
  - Update `cognirepo doctor` to remove REST and gRPC health checks.
- [ ] **Documentation Updates:**
  - Update `ARCHITECTURE.md` to reflect the pure MCP architecture.
  - Remove REST/gRPC endpoint documentation from `docs/`.

### Acceptance Criteria
- Codebase contains zero references to FastAPI, uvicorn, or gRPC.
- `cognirepo serve` starts only the stdio MCP server.
- Tests pass without API/gRPC fixtures.

---

## Phase 2: Local Organization (Cross-Repo) Architecture
**Objective:** Enable AI agents to discover findings and context across multiple repositories on the same local machine.

### Tasks
- [ ] **Global Configuration Registry:**
  - Establish a global registry at `~/.cognirepo/orgs.json` to track local organizations and their member repository paths.
- [ ] **Org CLI Commands:**
  - `cognirepo org create <name>`: Create a new local organization.
  - `cognirepo org list`: List all orgs and their associated repos.
  - `cognirepo org link <path>`: Manually link a repo to an org.
- [ ] **Update `cognirepo init` Wizard:**
  - Add a prompt during initialization: "Do you want to add this repository to a local organization?"
  - If yes, display a list of available orgs (from the global registry) or allow creating a new one inline.
  - Save the org association in the local project's `.cognirepo/config.json`.
- [ ] **Cross-Repo Routing Logic:**
  - Create a `CrossRepoRouter` utility that, when invoked within an org-linked repo, can fan-out read requests (e.g., vector search, BM25 search) to the `.cognirepo` directories of sibling repositories.

### Acceptance Criteria
- Developers can create orgs and link multiple local repositories to them.
- `cognirepo init` seamlessly handles org selection.
- Global and local config files accurately reflect org memberships.

---

## Phase 3: Cross-Repo MCP Tools
**Objective:** Expose the cross-repo capabilities to AI agents via MCP.

### Tasks
- [ ] **Enhance `retrieve_memory`:**
  - Update the semantic search to optionally query across all repos in the current org if a global flag/parameter is set, aggregating and ranking the results.
- [ ] **New Tool: `org_search(query)`:**
  - A dedicated tool to perform semantic and AST searches across all repositories within the current organization. Returns results annotated with their source repository name.
- [ ] **New Tool: `org_dependencies()`:**
  - Analyzes Cross-Repo links (e.g., matching imports in Repo A to exports in Repo B) and returns a high-level dependency graph of the organization.
- [ ] **Update `lookup_symbol` & `who_calls`:**
  - Allow these tools to resolve symbols that are imported from sibling repositories within the same org.

### Acceptance Criteria
- AI models can successfully query and retrieve context from Repo B while working inside Repo A (if both are in the same org).
- MCP tools return correctly scoped and attributed cross-repo results.

---

## Phase 4: Advanced RAG (Hierarchical Summarization)
**Objective:** Implement RAPTOR-like summarization to answer broad, repository-wide architectural questions.

### Tasks
- [ ] **Summarization Engine:**
  - Create `indexer/summarizer.py` to generate rolling summaries:
    - *Level 1:* File summaries (generated from AST/code).
    - *Level 2:* Directory summaries (rolled up from file summaries).
    - *Level 3:* Repository summary (rolled up from directory summaries).
- [ ] **Storage & Indexing:**
  - Store hierarchical summaries in a dedicated structure within `.cognirepo/graph/` (as high-level concept nodes) or `.cognirepo/vector_db/` with specific metadata tags (`type: summary`, `level: 2`).
- [ ] **CLI Summarize Command:**
  - `cognirepo summarize`: A command to build/update the summarization tree (can be hooked into the file watcher for background updates with debouncing).
- [ ] **New Tool: `architecture_overview(scope)`:**
  - An MCP tool that retrieves these high-level summaries. `scope` can be a directory path or `root` for the entire repo.
- [ ] **Cross-Repo Summaries:**
  - Extend the engine to generate an Org-level summary by rolling up the Level 3 summaries of all member repos.

### Acceptance Criteria
- Broad questions like "What does this system do?" leverage pre-computed summaries instead of hallucinating or pulling scattered low-level snippets.
- Summaries automatically invalidate or update when underlying files change significantly.

---

## Phase 5: Testing, Polish & Validation
**Objective:** Ensure the new features are robust, secure, and performant.

### Tasks
- [ ] **Cross-Repo Security Checks:**
  - Ensure path traversal vulnerabilities are mitigated when accessing sibling repos.
- [ ] **Performance Tuning:**
  - Ensure cross-repo fan-out queries do not block the MCP server for longer than 2 seconds. Implement parallel retrieval for sibling repos.
- [ ] **Documentation:**
  - Write a new `docs/ORGS.md` explaining the local cross-repo feature.
  - Update `docs/MCP_TOOLS.md` with the new summarization and org tools.
- [ ] **Benchmarking:**
  - Update the `cognirepo benchmark` suite to measure cross-repo retrieval latency and summarization accuracy.

### Acceptance Criteria
- All tests pass, including new integration tests for orgs and summarization.
- Documentation accurately reflects the 100% complete state of CogniRepo.
