# CogniRepo Manual Test Suite

**How to use this doc**
1. Run `cognirepo setup` inside each test repo before testing
2. Use prompts below verbatim — paste them to Claude Code (or any AI using CogniRepo MCP)
3. Paste raw output under each **RESULTS** block
4. Score pass/fail in the **Status** column

## Test Repo Map

| Alias | Actual path | Language | What it is |
|---|---|---|---|
| **easy/fastapi** | `../cognirepo_test_repo/easy/fastapi` | Python | FastAPI web framework |
| **easy/flask** | `../cognirepo_test_repo/easy/flask` | Python | Flask web framework |
| **medium/celery** | `../cognirepo_test_repo/medium/celery` | Python | Async task-queue library |
| **medium/ansible** | `../cognirepo_test_repo/medium/ansible` | Python | IT-automation framework |
| **advanced/kubernetes** | `../cognirepo_test_repo/advanced/kubernetes` | Go | Kubernetes container orchestrator |
| **advanced/moby** | `../cognirepo_test_repo/advanced/moby` | Go | Docker engine (Moby project) |
| **dummy** | `../cognirepo_test_repo/dummy` | — | Empty/sparse repo for no-match tests |
| **private-org/UpiClone** | `../cognirepo_test_repo/private-org/UpiClone` | Java/Spring Boot | 3-microservice UPI payments system |

> **Interchangeable pairs:** Within a difficulty tier the two repos can be swapped unless the test specifically requires a language or feature (e.g. Go receiver methods → kubernetes; Spring Security → UpiClone). Default choices per section are listed in the **Repo:** field.

Test repos: `../cognirepo_test_repo/easy/fastapi`, `easy/flask`, `medium/celery`, `medium/ansible`, `advanced/kubernetes`, `advanced/moby`, `dummy`, `private-org/UpiClone`

---

## 0. Environment Setup

Run these once before any test. Do NOT skip.

```bash
# In cognirepo repo — use pipx for global isolated install (preferred):
pipx install -e ".[dev,languages]"
# Or inside a venv:  pip install -e ".[dev,languages]"

# Repeat cognirepo setup for EVERY sub-repo you plan to test
cd ../cognirepo_test_repo/easy/fastapi  && cognirepo setup && cognirepo doctor
cd ../cognirepo_test_repo/easy/flask    && cognirepo setup && cognirepo doctor
cd ../cognirepo_test_repo/medium/celery  && cognirepo setup && cognirepo doctor
cd ../cognirepo_test_repo/medium/ansible && cognirepo setup && cognirepo doctor
cd ../cognirepo_test_repo/advanced/kubernetes && cognirepo setup && cognirepo doctor
cd ../cognirepo_test_repo/advanced/moby       && cognirepo setup && cognirepo doctor
cd ../cognirepo_test_repo/dummy               && cognirepo setup && cognirepo doctor

# Organisation setup — parent first, then link each child
cd ../cognirepo_test_repo/private-org/UpiClone
cognirepo init   # answer YES to org/parent prompts
cognirepo index-repo .
cd client       && cognirepo init --parent-repo .. --service-type rest_api --port 8080 --api-base-url /api && cognirepo index-repo .
cd ../npci-service && cognirepo init --parent-repo .. --service-type rest_api --port 8082 --api-base-url /api && cognirepo index-repo .
cd ../bank-service && cognirepo init --parent-repo .. --service-type rest_api --port 8080 --api-base-url /ipc && cognirepo index-repo .
```

**RESULTS — easy/fastapi setup**
```
[paste here]
```

**RESULTS — easy/flask setup**
```
[paste here]
```

**RESULTS — medium/celery setup**
```
[paste here]
```

**RESULTS — medium/ansible setup**
```
[paste here]
```

**RESULTS — advanced/kubernetes setup**
```
[paste here]
```

**RESULTS — advanced/moby setup**
```
[paste here]
```

**RESULTS — organisation setup (private-org/UpiClone)**
```
[paste here]
```

---

## 1. Session Bootstrap

### 1.1 Single-call bootstrap (get_agent_bootstrap)

**Repo:** `easy/fastapi` (alt: `easy/flask`) | **Tool:** `get_agent_bootstrap`

**Prompt:**
```
Call get_agent_bootstrap() and tell me what the project is about, what the hottest symbols are, and what the index health looks like.
```

**Expected:** Single response with `repo`, `architecture`, `index_health.status = "ok"`, `hot_symbols` list (may be empty on cold start). Should NOT require 4 separate calls.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 1.2 Full 4-call sequence (baseline comparison)

**Repo:** `medium/celery` (alt: `medium/ansible`) | **Tools:** `get_session_brief` → `get_last_context` → `get_user_profile` → `get_error_patterns`

**Prompt:**
```
Run the full session start sequence: get_session_brief(), then get_last_context(), then get_user_profile(), then get_error_patterns(). Summarise what you learned.
```

**Expected:** 4 calls, combined output similar to get_agent_bootstrap. Note token count difference.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 2. Code Search

### 2.1 Symbol lookup — exact match

**Repo:** `advanced/kubernetes` (Go; alt: `advanced/moby`) | **Tool:** `lookup_symbol`

**Prompt:**
```
Look up where the main entry point function is defined. Use lookup_symbol on "main" and tell me the file and line.
```

**Expected:** Returns `{file, line, type}`. Should NOT return empty list.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 2.2 Semantic code search — concept query

**Repo:** `advanced/kubernetes` (alt: `advanced/moby`) | **Tool:** `semantic_search_code`

**Prompt:**
```
Use semantic_search_code to find where authentication or login is handled in this codebase. Top 5 results.
```

**Expected:** Returns list of `{name, file, line, type, score}`. No episodic/memory entries mixed in (type should never be "EP" or "memory").

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 2.3 Token search — word in symbol names

**Repo:** `medium/celery` (alt: `medium/ansible`) | **Tool:** `search_token`

**Prompt:**
```
Use search_token("handler") to find all symbols whose names or docs mention "handler".
```

**Expected:** Returns `{file, line}` list. Fast (< 1s), no embedding needed.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 2.4 context_pack — main workhorse

**Repo:** `advanced/kubernetes` (alt: `advanced/moby`) | **Tool:** `context_pack`

**Prompt:**
```
Use context_pack to answer: "how does the request routing work in this project?" Set max_tokens=3000.
```

**Expected:** Returns `{query, status, token_count, sections, truncated}`. Status must be "ok" or "no_confident_match" — never missing. Sections should contain file snippets, not README noise.

**Status:** [ ] pass  [x] degraded

**Note:** Previously returned low-confidence scores (0.23–0.29). BM25 boost now fires when best_score < 0.35, re-ranking in favour of keyword matches. Re-run after re-indexing.

**RESULTS**
```
[paste here]
```

---

### 2.5 context_pack — no match case

**Repo:** dummy | **Tool:** `context_pack`

**Prompt:**
```
Use context_pack("quantum entanglement in blockchain") on this project.
```

**Expected:** Returns `{status: "no_confident_match", sections: [], token_count: 0, truncated: false}`. Agent should NOT get README noise as an answer.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 2.6 Caller graph

**Repo:** `advanced/kubernetes` | **Tool:** `who_calls`

**Prompt:**
```
Use who_calls() on the most important function in this repo (pick one from lookup_symbol results). Tell me all its local callers.
```

**Expected:** Returns `{local_callers: [...], cross_repo_callers: [], truncated: false}`. Shape must always be this dict, never a plain list. When graph is sparse, fallback should include Go receiver calls (e.g. `m.syncPod(ctx,...)`) tagged with `found_via: "go_receiver_fallback"`.

**Status:** [ ] pass  [x] degraded

**Note:** Graph had no call edges for `syncPod`; grep fallback found real callers but was not tagged. Fixed: `_who_calls_dynamic_fallback()` now greps `.go` files for `\.fn_name\(` patterns and tags results `go_receiver_fallback`. Re-index to populate AST call edges.

**RESULTS**
```
[paste here]
```

---

### 2.7 Dependency graph

**Repo:** `medium/celery` (alt: `medium/ansible`) | **Tool:** `dependency_graph`

**Prompt:**
```
Use dependency_graph on the main module of this project (direction="both", depth=2). What does it import and what imports it?
```

**Expected:** Returns `{imports: [...], imported_by: [...], ...}`. No crash.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 2.8 Go receiver method caller fallback (new)

**Repo:** `advanced/kubernetes` (must be Go; `advanced/moby` also valid) | **Tool:** `who_calls`

**Prompt:**
```
Call who_calls("Run") targeting the Kubernetes scheduler package. If the call graph is empty, does the fallback find Go receiver method calls like (s *Scheduler).Run() ? Check the found_via field.
```

**Expected:** Results contain entries with `found_via: "go_receiver_fallback"` for `.Run(` matches in `.go` files. NOT an empty list.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 3. Memory

### 3.1 Store and retrieve — round trip

**Repo:** `easy/fastapi` (alt: `easy/flask`) | **Tools:** `store_memory` → `retrieve_memory`

**Prompt:**
```
Store this memory: "The authentication flow uses JWT tokens with 24h expiry. Refresh tokens stored in Redis." Then immediately retrieve memories about "authentication JWT". Did you get it back?
```

**Expected:** store returns `{stored: true}`. retrieve returns list with the stored text in top-3 results.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 3.2 Conflict detection and supersede

**Repo:** `easy/fastapi` (alt: `easy/flask`) | **Tools:** `store_memory` → `supersede_learning`

**Prompt:**
```
Store memory: "Redis cache TTL is 1 hour". Then store memory: "Redis cache TTL is 30 minutes". The second store should return a conflicts list. Use supersede_learning to replace the old entry with the corrected TTL (30 minutes).
```

**Expected:** Second `store_memory` returns `conflicts: [{id, text}]`. `supersede_learning(old_id, new_text)` returns `{found_old: true, new_id: "..."}`.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 3.3 Episodic log and search

**Repo:** `easy/fastapi` (alt: `easy/flask`) | **Tools:** `log_episode` → `episodic_search`

**Prompt:**
```
Log an episode: "Discovered that the database schema migration script is in db/migrations/". Then search episodes for "database migration". Did you find it?
```

**Expected:** `log_episode` returns `{logged: true}`. `episodic_search` returns list with the logged text. Event field must be a string, NOT a dict.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 3.4 Record decision and retrieve

**Repo:** `medium/celery` (alt: `medium/ansible`) | **Tools:** `record_decision` → `episodic_search`

**Prompt:**
```
Record this architectural decision: summary="Use async queue for email sending", rationale="Sync email causes 2s request latency". Then search episodes for "email queue decision".
```

**Expected:** `record_decision` returns `{stored: true, ...}`. `episodic_search` finds it.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 3.5 Memory store under circuit breaker pressure (new)

**Repo:** `advanced/kubernetes` (large repo — needed to inflate RSS above 2 GB) | **Tools:** `store_memory` → `retrieve_memory`

**Setup:** Trigger memory pressure by running `subgraph(entity="errnoErr", depth=3)` first to inflate RSS.

**Prompt:**
```
Store memory "circuit breaker fallback test". While the server may be under memory pressure, call retrieve_memory("circuit breaker"). Does it return gracefully or crash?
```

**Expected:** If circuit breaker is OPEN: returns `{status: "circuit_open", hint: "cognirepo server restart"}` NOT a crash or traceback. If CLOSED: returns normally.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 4. Graph

### 4.1 Graph stats

**Repo:** `advanced/kubernetes` (alt: `advanced/moby`) | **Tool:** `graph_stats`

**Prompt:**
```
Call graph_stats() and tell me: how many nodes and edges are in the knowledge graph? Is it healthy?
```

**Expected:** Returns node/edge counts > 0 after indexing. Not empty. If `index_stale: true`, the response should also include `stale_reindexing_triggered: true` when no lock file is present.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 4.2 Subgraph around a symbol

**Repo:** `advanced/kubernetes` (alt: `advanced/moby`) | **Tool:** `subgraph`

**Prompt:**
```
Use subgraph() around the most important class in this project (depth=2). List the top 5 nodes you find.
```

**Expected:** Returns `{nodes: [...], edges: [...]}` with actual content. Not empty. If symbol not found, returns `{status: "not_found", hint: "Try lookup_symbol(...) first..."}` instead of silent empty.

**Status:** [ ] pass  [x] degraded

**Note:** Previously required manually adding the `symbol::` prefix. Fixed: `subgraph()` now tries case-insensitive suffix scan before returning not-found, and returns a helpful hint with `lookup_symbol` guidance.

**RESULTS**
```
[paste here]
```

---

## 5. Architecture Overview

### 5.1 Repo-level summary

**Repo:** `advanced/kubernetes` (alt: `advanced/moby`) | **Tool:** `architecture_overview`

**Prompt:**
```
Call architecture_overview(scope="root"). What is this project's purpose and what are its key classes/functions?
```

**Note:** Run `cognirepo summarize` in the repo first if this returns "Summaries not found".

**Expected:** Returns a human-readable string with repo name, file count, key classes/functions. Test/benchmark symbols (e.g. `WideDeepModel`, `TestBoilerplate`) should NOT appear in key classes after re-summarizing.

**Status:** [ ] pass  [x] degraded

**Note:** Previously surfaced `WideDeepModel` and `TestBoilerplate` because the summarizer did not filter test paths. Fixed: `_is_test_path()` now excludes `_test.go`, `test/`, `benchmark/` etc. from class rankings. Re-run `cognirepo summarize` to pick up the fix.

**RESULTS**
```
[paste here]
```

---

### 5.2 Directory-level summary

**Repo:** `advanced/kubernetes` (must be kubernetes; pkg/kubelet and pkg/scheduler are kubernetes-specific) | **Tool:** `architecture_overview`

**Prompt:**
```
Run: cognirepo summarize --scope pkg/
Then call architecture_overview(scope="pkg/kubelet") and architecture_overview(scope="pkg/scheduler"). What's in each?
```

**Expected:** Returns real Go package summaries for `pkg/kubelet` and `pkg/scheduler`. Classes like `Kubelet`, `PodWorker`, `Scheduler`, `Framework` should appear. Build shell scripts should NOT dominate.

**Status:** [ ] pass  [x] degraded

**Note:** Previously only had shell-script summaries. Fixed: `run_full_summarization()` now accepts `--scope` flag and sorts directories by non-test source-file density. Re-run `cognirepo summarize --scope pkg/` on kubernetes.

**RESULTS**
```
[paste here]
```

---

## 6. Documentation Search

### 6.1 Semantic doc search

**Repo:** `medium/ansible` (has rich `.md` docs in `changelogs/`, `docs/`; alt: `medium/celery`) | **Tool:** `search_docs`

**Prompt:**
```
Use search_docs("how to install and configure") to find relevant documentation. What do the top 2 results say?
```

**Expected:** Returns list of `{score, snippet/text, source}`. `MANUAL_TEST_SUITE.md` must NOT appear in results. Fails gracefully if no docs indexed (empty list, no crash).

**Status:** [x] fail  [ ] pass

**Note:** Previously `MANUAL_TEST_SUITE.md` appeared as top result because the test suite contains the query verbatim. Fixed: `docs_search.py` now filters filenames matching `MANUAL_TEST_SUITE`, `TEST_SUITE`, `test_suite`, `MANUAL_TEST`. Re-run to confirm fix.

**RESULTS**
```
[paste here]
```

---

## 7. Behaviour Tracking (requires opt-in)

**Setup:** Run `cognirepo init` and answer YES to "Enable user behaviour profiling?"

### 7.1 Profile builds from queries

**Repo:** `easy/fastapi` (with behaviour=true; alt: `easy/flask`) | **Tools:** multiple calls → `get_user_profile`

**Prompt:**
```
Make 5 different code queries using context_pack and semantic_search_code. Then call get_user_profile(). What does my interaction style look like?
```

**Expected:** `get_user_profile()` returns `{interaction_style: {preferred_depth, terminology, ...}, framing_hints: "..."}`. Not `{behaviour_tracking: "disabled"}`.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 7.2 User preference recording

**Repo:** `easy/fastapi` (with behaviour=true; alt: `easy/flask`) | **Tool:** `record_user_preference` → `get_user_profile`

**Prompt:**
```
Record my preference: key="response_style", value="always show code before explanation". Then call get_user_profile() to confirm it was stored under explicit_preferences.
```

**Expected:** `record_user_preference` returns `{recorded: true}`. Profile shows it under `explicit_preferences`.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 7.3 Error pattern recording

**Repo:** `easy/fastapi` (any repo works) | **Tools:** `record_error` → `get_error_patterns`

**Prompt:**
```
Record this error: type="ImportError", message="cannot import fastembed — install via pip install fastembed inside a venv". Then call get_error_patterns(). Is the error listed with a prevention hint that includes the install command?
```

**Expected:** `get_error_patterns()` returns list with the recorded error, `count >= 1`, and `prevention_hint` that starts with `pip install fastembed` (extracted from the recorded message), not just the generic hint.

**Status:** [ ] pass  [x] degraded

**Note:** Previously the hint was generic ("Import failed — verify package is installed…"). Fixed: `get_error_patterns()` now scans `recent_context` for actionable install commands and prepends them to the generic hint.

**RESULTS**
```
[paste here]
```

---

### 7.4 Behaviour tracking disabled by default

**Repo:** `dummy` (fresh init with behaviour=false) | **Tool:** `get_user_profile`

**Prompt:**
```
On a fresh repo where behaviour tracking was NOT enabled, call get_user_profile(). What does it return?
```

**Expected:** Returns `{behaviour_tracking: "disabled", hint: "Enable in .cognirepo/config.json..."}`. Never crashes.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 8. Organisation / Cross-repo

**Setup:** UPI Clone — 3 Spring Boot microservices linked under parent UpiClone. All Java / Maven / Spring Boot.

| Service | Dir | Port | Role |
|---|---|---|---|
| client | `UpiClone/client` | 8080 | User-facing: auth, payment initiation, split bill, notifications |
| npci-service | `UpiClone/npci-service` | 8082 | NPCI intermediary: validates transactions, routes debit/credit to bank |
| bank-service | `UpiClone/bank-service` | 8080 (env: `PORT`) | Bank ledger: debit, credit, account management |

**Call chain:** `client → npci-service (/api/ipc/*) → bank-service (/ipc/*)`.
**Internal auth:** `npci-service` sets headers `X-Internal-Token` + `fonlt: present`; `bank-service` enforces via `FonltHeaderFilter` on all `/api/ipc/*` paths.

```
UpiClone/        ← .cognirepo (parent, org=MyPay-upi)
├── client/      ← .cognirepo (child, port=8080)
├── npci-service/← .cognirepo (child, port=8082)
└── bank-service/← .cognirepo (child, port=8080)
```

### 8.1 Microservice count (parent context)

**Repo:** `private-org/UpiClone` | **Tools:** `get_agent_bootstrap`, `architecture_overview`

**Prompt:**
```
How many microservices does this project have? Name them and their roles.
```

**Expected:** Returns all 3 services (client, bank-service, npci-service) with ports and roles. Uses CogniRepo, not grep.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 8.2 CogniRepo storage structure

**Repo:** `private-org/UpiClone` | **Tool:** `graph_stats`, `get_agent_bootstrap`

**Prompt:**
```
How is CogniRepo structured under this repo and its sub-services?
```

**Expected:** Describes 1 parent + 3 child `.cognirepo/` dirs with org (MyPay-upi) as the join key.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 8.3 Cross-service connection map

**Repo:** `private-org/UpiClone` | **Tools:** `context_pack`, `org_wide_search`

**Prompt:**
```
How is bank-service connected to client? Use org_wide_search if context_pack returns no_confident_match. Describe the full HTTP call chain.
```

**Expected:** Returns `client → npci-service → bank-service` chain with endpoint details. No behaviour_hook errors.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 8.4 Login/auth control flow

**Repo:** `private-org/UpiClone` (run from `client/` context) | **Tool:** `context_pack`

**Prompt:**
```
How does login and authorisation work? Trace the full control flow from client HTTP request to token validation.
```

**Expected:** Returns Spring Security filter chain, FonltHeaderFilter, internal token validation. No hook errors.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 8.5 bank-service: transaction flow (post behaviour-hook fix)

**Repo:** `private-org/UpiClone/bank-service` | **Tool:** `context_pack`, `org_wide_search`

**Prompt:**
```
How is a transaction event handled in bank-service? How does it connect to npci-service? Use organisational knowledge to answer.
```

**Expected:** CogniRepo MCP tools return results normally. NO `behaviour_hook.py` path error. Transaction debit/credit/rollback flow surfaced from bank-service index.

**Status:** [x] fail  [ ] pass

**Note:** Was failing with `No such file or directory` for `behaviour_hook.py`. Fixed: `_write_claude_hooks()` now resolves hook scripts from the installed cognirepo package path, not the child repo directory.

**RESULTS**
```
[paste here]
```

---

### 8.6 Org-wide cross-service search

**Repo:** `private-org/UpiClone` (parent) | **Tool:** `org_wide_search`

**Prompt:**
```
Call org_wide_search("debit credit transaction flow"). Do results come from bank-service AND npci-service without falling back to grep?
```

**Expected:** Results tagged `source_repo: "bank-service"` and `source_repo: "npci-service"`. No grep fallback needed.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 8.7 Cross-service endpoint traversal

**Repo:** `private-org/UpiClone` (parent) | **Tool:** `cross_repo_traverse`

**Prompt:**
```
Call cross_repo_traverse("NPCIController", direction="both"). Does it surface the bank-service endpoints that NPCI calls?
```

**Expected:** Returns a graph traversal showing `NPCIController` (in `npci-service`) → bank-service `/ipc/debit`, `/ipc/credit`, `/ipc/createAccount` endpoints as `CALLS_API` edges. Direction "both" should also surface `client → NPCIController` CALLS_API edges.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 9. Context Handoff (Cross-agent)

### 9.1 context_pack writes snapshot

**Repo:** `medium/celery` (alt: `medium/ansible`) | **Tool:** `context_pack` → `get_last_context`

**Prompt:**
```
Use context_pack("how does data validation work") then immediately call get_last_context(). Does it show the query you just ran?
```

**Expected:** `get_last_context` returns `{query: "how does data validation work", sections: [...], agent: "claude", ...}`. Status NOT "no_context".

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 9.2 Bootstrap picks up last context

**Repo:** `medium/celery` (after 9.1, same sub-repo) | **Tool:** `get_agent_bootstrap`

**Prompt:**
```
In a fresh session, call get_agent_bootstrap(). Does last_focus show the query from the previous session?
```

**Expected:** `last_focus.query` = "how does data validation work" from previous session. Cross-agent handoff working.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 10. Hooks & Integration

### 10.1 Auto-store after context_pack

**Repo:** `advanced/kubernetes` (alt: `advanced/moby`) | Internal hook test

**Prompt:**
```
Call context_pack("explain the main algorithm"). Then call retrieve_memory("main algorithm"). Does the memory store have anything from the context_pack result?
```

**Expected:** retrieve_memory returns at least one result. If circuit breaker was previously OPEN, `context_pack` should return `{status: "circuit_open", hint: "..."}` NOT a traceback.

**Status:** [x] fail  [ ] pass

**Note:** Was crashing with `CircuitOpenError` traceback when RSS ≥ 2000 MB. Fixed: `hybrid_retrieve()` now catches `CircuitOpenError` and returns `{"status": "circuit_open", "sections": [], "hint": "cognirepo server restart"}`.

**RESULTS**
```
[paste here]
```

---

### 10.2 Session history

**Repo:** `easy/fastapi` (any repo works) | **Tool:** `get_session_history`

**Prompt:**
```
Make 3 different tool calls (e.g. lookup_symbol, context_pack, who_calls). Then call get_session_history(limit=5). Does it show the current MCP session with message_count >= 3?
```

**Expected:** Returns list with at least one session. `message_count >= 3`. `last_exchange` shows the most recent tool call. NOT an empty list after MCP tool usage.

**Status:** [x] fail  [ ] pass

**Note:** Was returning empty list because sessions were only created during CLI `cognirepo ask` mode, not during MCP tool dispatch. Fixed: `run_server()` now calls `_init_mcp_session()` at startup, and `_traced()` appends each tool call as an exchange record.

**RESULTS**
```
[paste here]
```

---

### 10.3 Explain change (git-aware)

**Repo:** `advanced/kubernetes` (alt: `advanced/moby`; must be a git repo with commit history) | **Tool:** `explain_change`

**Prompt:**
```
Use explain_change on "README.md" since="30d". What changed and why?
```

**Expected:** Returns `{target, commits: [...], explanation: "..."}`. No crash if no commits. Graceful empty if no history.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 10.4 Session tracking via MCP (new)

**Repo:** `easy/fastapi` (any repo works) | **Tool:** `get_session_history`

**Prompt:**
```
Make 5 tool calls: lookup_symbol("main"), context_pack("authentication"), who_calls("validate"), graph_stats(), semantic_search_code("error handling"). Then call get_session_history(limit=3). Does it show the current session? What is message_count?
```

**Expected:** `get_session_history` returns list with the current MCP server session. `message_count >= 5`. `last_exchange.user` shows `[tool:semantic_search_code] error handling` or similar.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 11. CLI Health Check

Run locally, not via AI prompts:

```bash
# Run in each sub-repo after setup — pick at least one from each tier
cd ../cognirepo_test_repo/easy/fastapi    && cognirepo doctor && cognirepo doctor --verbose
cd ../cognirepo_test_repo/medium/celery  && cognirepo doctor && cognirepo doctor --verbose
cd ../cognirepo_test_repo/advanced/kubernetes && cognirepo doctor && cognirepo doctor --verbose
cd ../cognirepo_test_repo/private-org/UpiClone/bank-service && cognirepo doctor && cognirepo doctor --verbose
```

**Expected:** All checks green (✓) except optional language parsers. No red ✗ for core checks. Tool count shows 32/32. Check 16 (behaviour hook path) and Check 17 (org member indexes) should appear in `--verbose` output.

**RESULTS — easy/fastapi**
```
[paste here]
```

**RESULTS — medium/celery**
```
[paste here]
```

**RESULTS — advanced/kubernetes**
```
[paste here]
```

**RESULTS — private-org/UpiClone/bank-service (org child)**
```
[paste here]
```

---

## 12. Token Reduction Benchmark

```bash
# Run in either advanced repo (kubernetes is larger — more realistic):
cd ../cognirepo_test_repo/advanced/kubernetes
cognirepo benchmark

# Or for a faster run:
cd ../cognirepo_test_repo/advanced/moby
cognirepo benchmark
```

**Expected:** Token reduction ratio > 3x. If circuit breaker is OPEN: prints `⚠ Benchmark aborted: server memory pressure` with exit 0. No traceback. If some queries are skipped due to circuit breaker: reports `N queries skipped (CogniRepo under memory pressure)` and continues with remaining queries.

**Status:** [x] fail  [ ] pass

**Note:** Was crashing with `CircuitOpenError` traceback. Fixed at two levels: `measure_token_reduction()` now catches per-query `CircuitOpenError` with a `continue`, and `run_benchmark()` outer wrap prints a user-friendly message and returns `{"aborted": True}` instead of crashing.

**RESULTS**
```
[paste here]
```

---

## 13. Staleness Reindex at Session Start

**Setup:** Make a new git commit without running `cognirepo index-repo` afterward.

**Prompt:**
```
Call get_agent_bootstrap(). What is index_health.status?
```

**Expected:** `index_health.status == "reindexing"`. A background `cognirepo index-repo --changed-only` process starts. Calling `get_agent_bootstrap()` again after ~30 seconds shows `status == "ok"`. Also: `graph_stats()` should trigger the same background reindex and return `stale_reindexing_triggered: true`.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 14. Concurrent Session Shared Index

**Setup:** Terminal A has a Claude session open with the watcher running (`cognirepo index-repo .`). Open Terminal B and start a second Claude session.

**Prompt (from Terminal B):**
```
Call get_agent_bootstrap(). Does the index show data?
```

**Expected:** Terminal B's MCP server reads the same `.cognirepo/` index written by Terminal A. No second watcher is spawned (singleton enforcement). `get_agent_bootstrap()` returns populated index data.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 15. setup → init Subprocess

**Setup:** Fresh uninitialized directory (no `.cognirepo/`).

```bash
mkdir /tmp/test_setup_repo && cd /tmp/test_setup_repo
cognirepo setup
```

**Expected:** The output shows `[1/5] Running cognirepo init for 'test_setup_repo'...` followed immediately by the full 7-step `cognirepo init` wizard prompts. After the wizard completes, setup continues with `[2/5] Indexing repository...`, `[3/5] Configuring MCP integrations...`, `[4/5] Writing IDE rules...`, `[5/5] Wiring Claude Code behaviour hooks...`. Behaviour hook path should point to installed package, not the target repo's `tools/` dir.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 16. Encryption Round-Trip

**Setup:** Initialize repo with `encryption: true`.

**Prompt:**
```
Store memory: "test encryption round trip". Kill the MCP server. Restart the MCP server.
Retrieve memory "test encryption".
```

**Expected:** Memory retrieved successfully after server restart. Content matches "test encryption round trip". No decryption errors in server logs.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 17. Behaviour Framing Populated

**Setup:** `behaviour_tracking: true` in config.json. Make 5+ diverse queries via `context_pack` or `lookup_symbol`.

**Prompt:**
```
Call get_agent_bootstrap(). Is framing.depth populated? Is framing.hints non-empty?
```

**Expected:** `framing.depth != "unknown"` (e.g. "detailed" or "concise"). `framing.hints` is a non-empty descriptive string such as "prefers concise responses with code examples". `framing.vocabulary` contains relevant terms from past queries.

**Status:** [x] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 18. Circuit Breaker Recovery (new)

**Setup:** Run `subgraph(entity="errnoErr", depth=3)` on `advanced/kubernetes` to inflate RSS above the 2000 MB limit and open the circuit breaker.

### 18.1 context_pack under open circuit breaker

**Prompt:**
```
While the circuit breaker may be OPEN from heavy graph loading, call context_pack("main algorithm"). What does the response look like?
```

**Expected:** Returns `{status: "circuit_open", sections: [], hint: "CogniRepo under memory pressure. Run: cognirepo server restart"}`. NOT an exception. NOT silent empty.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 18.2 Server restart clears breaker

**Prompt:**
```
Run `cognirepo server restart` (or restart the MCP server process). Then call context_pack("main algorithm") again. Does it return normally now?
```

**Expected:** Normal result after restart. Breaker reset. Status "ok" or "no_confident_match".

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 18.3 Benchmark under open circuit breaker

```bash
# With circuit breaker OPEN:
cognirepo benchmark
```

**Expected:** Prints `⚠ Benchmark aborted: server memory pressure` OR prints partial results table with `N queries skipped (CogniRepo server under memory pressure)`. Exit 0. No traceback. No `CircuitOpenError` exception shown.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 19. UPI Clone — Extended Org Tests (new)

**Repo:** `private-org/UpiClone` (Spring Boot, Java, 3 microservices — see section 8 setup for link commands)

**Pre-condition:** All 3 services (`client`, `npci-service`, `bank-service`) linked to parent via `cognirepo init --parent-repo`. `cognirepo index-repo .` run in each. No behaviour_hook path errors. Internal-token headers `X-Internal-Token` and `fonlt` visible in index.

### 19.1 bank-service request flow

**Prompt:**
```
Use CogniRepo tools to explain the full request handling flow in bank-service, from HTTP endpoint to database write. Start with context_pack("HTTP endpoint database write flow") in the bank-service context.
```

**Expected:** `context_pack` returns Spring `@RestController` → service layer → repository flow. No hook errors. No grep fallback needed.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 19.2 Distributed transaction safety

**Prompt:**
```
Does bank-service handle partial transaction failures — e.g. debit succeeds but credit fails? Use org_wide_search("rollback credit transaction") to find rollback logic.
```

**Expected:** `org_wide_search` returns NPCI credit rollback code (re-credits sender when credit fails). Source tagged as `bank-service` or `npci-service`.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 19.3 Security — internal token validation

**Prompt:**
```
How does bank-service validate that a request comes from NPCI and not an external caller? Use semantic_search_code("authentication header validation") in the bank-service context.
```

**Expected:** Returns `FonltHeaderFilter` code from `bank-service/src/main/java/com/xai/upi/bank/filters/FonltHeaderFilter.java` with file + line. The filter checks `path.startsWith("/api/ipc/")` and rejects requests missing the `fonlt` header with 400. `NPCIController.getHeaders()` sets both `X-Internal-Token` and `fonlt: present` on outgoing calls. Both sides should appear in results.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 19.4 Cross-service dependency graph

**Prompt:**
```
Call org_dependencies() from UpiClone parent context. Does it show client → npci-service → bank-service as a call chain? Are the CALLS_API edges correctly oriented?
```

**Expected:** Returns org dependency tree with `client CALLS_API npci-service` and `npci-service CALLS_API bank-service` edges. Directionality correct — `client` never directly calls `bank-service`. `npci-service` calls bank via `${bank.base-url}/ipc/*` endpoints using the internal-token headers.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 20. Summarize Coverage (new)

**Setup:** Run `cognirepo summarize --scope pkg/` inside the advanced (kubernetes) repo.

### 20.1 pkg/kubelet architecture overview

**Prompt:**
```
After running `cognirepo summarize --scope pkg/`, call architecture_overview(scope="pkg/kubelet"). What classes and functions appear?
```

**Expected:** Real Go content — classes like `Kubelet`, `PodWorker`, `StatusManager`, `ProbeManager` should appear. Shell build scripts should NOT dominate. Symbol count should reflect Go source, not shell functions.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 20.2 pkg/scheduler architecture overview

**Prompt:**
```
Call architecture_overview(scope="pkg/scheduler"). What is the scheduler's class hierarchy?
```

**Expected:** Classes like `Scheduler`, `Framework`, `Plugin`, `QueueSortPlugin` appear. Real scheduler logic visible.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 20.3 Test symbol exclusion from root overview

**Prompt:**
```
Call architecture_overview(scope="root"). Is WideDeepModel listed in key classes? Is TestBoilerplate listed?
```

**Expected:** Both `WideDeepModel` and `TestBoilerplate` are absent from key classes. Real Kubernetes infrastructure classes (`Kubelet`, `Pod`, `Node`, `Scheduler`, or similar) should appear instead.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 21. UPI Clone — Feature-Specific Tests (new)

**Repo:** `private-org/UpiClone` (context noted per test)
**Pre-condition:** Same as section 19.

### 21.1 OTP flow — generate and verify

**Repo:** `private-org/UpiClone/npci-service` | **Tool:** `context_pack`, `lookup_symbol`

**Prompt:**
```
Use context_pack("OTP generation verification") then lookup_symbol("getOtp") and lookup_symbol("verifyOtp"). Describe the full OTP flow: how is it generated, where is it stored, how long is it valid, and how is it verified?
```

**Expected:** `NPCIController.getOtp()` generates a 4-digit OTP, stores it on the `User` entity with `otpGeneratedAt` timestamp, and prints it to stdout. `verifyOtp()` checks OTP validity within a 5-minute window. File + line returned for both methods.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 21.2 UPI PIN end-to-end

**Repo:** `private-org/UpiClone/npci-service` + `client` | **Tool:** `context_pack`, `org_wide_search`

**Prompt:**
```
Trace the full UPI PIN setup flow: client UI → npci-service endpoint → where the PIN is stored. Use context_pack("UPI PIN setup save") then org_wide_search("saveUpiPin setUpiPin"). Where is the PIN hashed and stored?
```

**Expected:** Shows `SetupController` (client) → `NPCIController.saveUpiPin()` → `user.setUpiPin(passwordEncoder.encode(upiPin))` → `userRepository.save(user)`. PIN is BCrypt-hashed in npci-service. File + line for each step.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 21.3 Transaction rollback — credit failure path

**Repo:** `private-org/UpiClone/npci-service` | **Tool:** `context_pack`, `lookup_symbol`

**Prompt:**
```
What happens if the credit step of a transaction fails? Use context_pack("transaction rollback credit failure") and lookup_symbol("makeTransaction"). Show the rollback code path.
```

**Expected:** `NPCIController.makeTransaction()` — after debit succeeds but credit fails, it calls `/ipc/credit` again on the sender's account as a rollback (re-credits the debited amount) and returns HTTP 500 with `"Transaction failed: Credit error"`. File + line clearly shown.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 21.4 Social features — friends and family members

**Repo:** `private-org/UpiClone/npci-service` | **Tool:** `semantic_search_code`, `context_pack`

**Prompt:**
```
Use semantic_search_code("friends family members list") to find the social features of this UPI app. What endpoints exist for managing friends and family members?
```

**Expected:** Returns `addFriend`, `getFriends`, `addFamilyMember`, `getFamilyMembers` endpoints in `NPCIController` with their `/api/*` paths. Each stores IDs in `User.friends` / `User.familyMembers` lists via MongoDB.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 21.5 Split bill controller

**Repo:** `private-org/UpiClone/client` | **Tool:** `lookup_symbol`, `context_pack`

**Prompt:**
```
Use lookup_symbol("SplitBillController") then context_pack("split bill shared expense flow"). What does the split bill feature do and which endpoints does it expose?
```

**Expected:** `SplitBillController` found in `client` service with file + line. `context_pack` returns relevant code. Should describe splitting a bill amount across multiple users.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 21.6 Balance inquiry — end-to-end

**Repo:** `private-org/UpiClone` (parent) | **Tool:** `context_pack`, `org_wide_search`

**Prompt:**
```
Use context_pack("check balance inquiry flow") then org_wide_search("checkBalance account balance") to trace how a balance inquiry flows from the client service to bank-service.
```

**Expected:** Shows `client → npci-service /api/ipc/checkBalance → bank-service /account/{userId}` chain. PIN verification in npci-service before forwarding. Bank endpoint returns account balance from `AccountRepository`.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 21.7 FonltHeaderFilter enforcement

**Repo:** `private-org/UpiClone/bank-service` | **Tool:** `lookup_symbol`, `context_pack`

**Prompt:**
```
Use lookup_symbol("FonltHeaderFilter") and context_pack("internal request header validation security"). What does FonltHeaderFilter do and which paths does it protect?
```

**Expected:** Returns `FonltHeaderFilter.java` with file + line. Filter protects `path.startsWith("/api/ipc/")`, rejects missing `fonlt` header with HTTP 400 and JSON error body. Non-`/api/ipc/` paths pass through without the header check.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 21.8 moby (Docker) — architecture overview

**Repo:** `advanced/moby` | **Tool:** `architecture_overview`, `lookup_symbol`

**Prompt:**
```
Call architecture_overview(scope="root") on the moby repo. What is it, and what are the key packages? Then use lookup_symbol("NewDaemon") to find where the Docker daemon is initialized.
```

**Expected:** Overview describes Docker engine (container runtime). Key packages like `daemon`, `client`, `api`, `builder` appear. `lookup_symbol("NewDaemon")` returns file + line in `daemon/` package.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 21.9 flask repo — symbol lookup and context pack

**Repo:** `easy/flask` | **Tool:** `lookup_symbol`, `context_pack`

**Prompt:**
```
Use lookup_symbol("Flask") to find the main Flask class. Then use context_pack("request routing URL dispatch") to understand how Flask routes HTTP requests.
```

**Expected:** `lookup_symbol("Flask")` returns file + line in `src/flask/app.py` or similar. `context_pack` returns relevant routing/dispatch code from Flask source, not README noise.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 21.10 ansible repo — cross-module dependency graph

**Repo:** `medium/ansible` | **Tool:** `dependency_graph`, `context_pack`

**Prompt:**
```
Use dependency_graph on "ansible" (the main package module, direction="both", depth=2). What does ansible's core module import and what imports it?
```

**Expected:** Returns `{imports: [...], imported_by: [...]}` with real Python module names. No crash. Ansible's `lib/ansible/` module tree should be reflected.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## Summary Scorecard

| Section | Tests | Pass | Fail | Degraded | Notes |
|---|---|---|---|---|---|
| 1. Session Bootstrap | 2 | 2 | 0 | 0 | |
| 2. Code Search | 8 | 5 | 0 | 2 | §2.4 low-confidence (BM25 boost fix), §2.6 Go receiver (fixed), §2.8 new |
| 3. Memory | 5 | 1 | 0 | 0 | §3.1–3.3 pending execution, §3.5 new |
| 4. Graph | 2 | 1 | 0 | 1 | §4.2 required prefix (helpful hint fix) |
| 5. Architecture | 2 | 0 | 0 | 2 | §5.1 test symbols (filter fix), §5.2 scope fix |
| 6. Docs | 1 | 0 | 1 | 0 | §6.1 test suite contamination (exclusion fix) |
| 7. Behaviour | 4 | 3 | 0 | 1 | §7.3 generic hint (enrichment fix) |
| 8. Org/Cross-repo | 7 | 4 | 1 | 0 | §8.5 hook fix, §8.6–8.7 new |
| 9. Context Handoff | 2 | 2 | 0 | 0 | |
| 10. Hooks | 4 | 1 | 2 | 0 | §10.1 circuit breaker (fix), §10.2 sessions (fix), §10.4 new |
| 11. CLI | 1 | 1 | 0 | 0 | |
| 12. Benchmark | 1 | 0 | 1 | 0 | crash fixed |
| 13. Staleness Reindex | 1 | 1 | 0 | 0 | |
| 14. Concurrent Sessions | 1 | 1 | 0 | 0 | |
| 15. setup→init | 1 | 1 | 0 | 0 | |
| 16. Encryption | 1 | 1 | 0 | 0 | |
| 17. Behaviour Framing | 1 | 1 | 0 | 0 | |
| 18. Circuit Breaker Recovery | 3 | — | — | — | new — pending |
| 19. UPI Clone Extended | 4 | — | — | — | new — pending |
| 20. Summarize Coverage | 3 | — | — | — | new — pending |
| 21. UPI Clone Feature Tests (§21.1–21.7) | 7 | — | — | — | new — OTP, PIN, rollback, social, split bill, FonltHeaderFilter |
| 21. Multi-repo Coverage (§21.8–21.10) | 3 | — | — | — | new — moby, flask, ansible |
| **Total** | **64** | **25+** | **4** | **5** | |

**Overall pass rate after fixes:** ___/64

**Readiness verdict:**
- 58–64 pass → Ship ✓
- 50–57 pass → Fix degraded before ship
- < 50 pass → Review Phase 1–4 fixes

---

## Known Pre-conditions

| Test | Repo | Requires |
|---|---|---|
| 1.1 | `easy/fastapi` | `cognirepo index-repo .` run first |
| 1.2 | `medium/celery` | `cognirepo index-repo .` run first |
| 2.1–2.4, 2.6, 2.8 | `advanced/kubernetes` | `cognirepo index-repo .` run first; 2.8 also needs Go receiver edges extracted |
| 2.5 | `dummy` | Sparse or empty index (no setup beyond `cognirepo init`) |
| 2.7 | `medium/celery` | `cognirepo index-repo .` run first |
| 3.1–3.4 | `easy/fastapi` | `cognirepo index-repo .` run first |
| 3.5 | `advanced/kubernetes` | `subgraph(depth=3)` on large hub to trigger memory pressure (RSS ≥ 2 GB) |
| 4.1–4.2 | `advanced/kubernetes` | `cognirepo index-repo .` run first |
| 5.1–5.2 | `advanced/kubernetes` | `cognirepo summarize` (or `--scope pkg/`) run first |
| 6.1 | `medium/ansible` | `cognirepo index-repo .` run first |
| 7.x | `easy/fastapi` | `behaviour_tracking: true` in config.json |
| 8.x, 19.x, 21.1–21.7 | `private-org/UpiClone` | All 3 services linked via `cognirepo init --parent-repo`; each service indexed; behaviour_hook fix applied (cognirepo reinstalled) |
| 9.x | `medium/celery` | `autosave_context: true` in config.json (default) |
| 10.1 | `advanced/kubernetes` | Populated index |
| 10.3 | `advanced/kubernetes` | git repo with at least one commit post-index |
| 12 | `advanced/kubernetes` | Populated index; `advanced/moby` also valid |
| 13 | any | git repo with at least one commit post-index |
| 14 | any | Two terminal sessions, watcher running in Terminal A |
| 15 | fresh dir | Directory without `.cognirepo/` |
| 16 | any | `encryption: true` in config.json at init time |
| 17 | any | `behaviour_tracking: true`, 5+ prior queries |
| 18 | `advanced/kubernetes` | `cognirepo server` running; `subgraph(depth=3)` to open breaker |
| 20 | `advanced/kubernetes` | `cognirepo summarize --scope pkg/` run first |
| 21.8 | `advanced/moby` | `cognirepo index-repo .` run first |
| 21.9 | `easy/flask` | `cognirepo index-repo .` run first |
| 21.10 | `medium/ansible` | `cognirepo index-repo .` run first |
| 20 | `cognirepo summarize --scope pkg/` run in kubernetes repo |
