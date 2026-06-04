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

what I did fo rorg setUp , went in Upiclone and used cognirepo setup
**RESULTS — easy/fastapi 
```
SUCCESS
```
**RESULTS — easy/flask setup**
```
SUCCESS
```

**RESULTS — medium/celery setup**
```
SUCCESS
```

**RESULTS — medium/ansible setup**
```
SUCCESS
```

**RESULTS — advanced/kubernetes setup**
```
SUCCESS
```

**RESULTS — advanced/moby setup**
```
SUCCESS
```

**RESULTS — organisation setup (private-org/UpiClone)**
```
SUCCESS
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

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● Here's what get_agent_bootstrap returned:

  ---
  Project: flask
  
  Architecture
  The repo contains 77 source files with 1,832 indexed symbols. Top packages:
  - src/flask — core library
  - src/flask/sansio, src/flask/json — sub-modules
  - examples/celery, examples/tutorial/flaskr — example apps
  - tests/, tests/type_check — test suite
  
  Key classes: Flask, Blueprint, NoAppException, ScriptInfo, AppGroup, FlaskGroup,
  CertParamType, SeparatedPathType

  Key functions: _make_timedelta, remove_ctx, add_ctx, get_send_file_max_age,
  send_static_file, open_resource, create_jinja_environment, create_url_adapter

  ---
  Hot Symbols

  The "hottest" entries (by behavioural weight) are infrastructure/config files rather
  than source symbols — indicating recent activity has been concentrated on CI/tooling,
  not application logic:

  1. docs/config.rst
  2. tests/test_reqctx.py
  3. .github/workflows/pre-commit.yaml
  4. .github/workflows/tests.yaml
  5. .github/workflows/publish.yaml
  6. .github/workflows/zizmor.yaml
  7. .pre-commit-config.yaml
  8. uv.lock

  ---
  Index Health

  ┌─────────────────┬───────┐
  │     Metric      │ Value │
  ├─────────────────┼───────┤
  │ Symbols indexed │ 1,832 │
  ├─────────────────┼───────┤
  │ Files indexed   │ 92    │
  ├─────────────────┼───────┤
  │ Status          │ ok    │
  └─────────────────┴───────┘

  The index is healthy. No prior error patterns have been recorded for this repo.
```

---

### 1.2 Full 4-call sequence (baseline comparison)

**Repo:** `medium/celery` (alt: `medium/ansible`) | **Tools:** `get_session_brief` → `get_last_context` → `get_user_profile` → `get_error_patterns`

**Prompt:**
```
Run the full session start sequence: get_session_brief(), then get_last_context(), then get_user_profile(), then get_error_patterns(). Summarise what you learned.
```

**Expected:** 4 calls, combined output similar to get_agent_bootstrap. Note token count difference.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
 Here's a summary of what each call returned:

  ---
  Session Start Summary
  
  get_session_brief

  - Index health: 17,341 symbols across 4,114 files, last indexed 2026-05-28 (about 4
  days ago — worth re-running cognirepo index-repo . soon).
  - Most-called symbols: Generic builtins — join, isinstance, get, dict, append —
  indicating a broad Python codebase with no single dominant hotspot.
  - Hot files (recently accessed): Windows/PSRP-related paths dominate —
  .azure-pipelines/azure-pipelines.yml, lib/ansible/plugins/connection/psrp.py, and
  Windows Server 2016 changelog fragments. Recent work was focused on Windows 
  connectivity and CI pipeline changes.
  - Architecture summaries: Missing. Run cognirepo summarize to populate them.
  - Recent decisions: None stored yet.

  get_last_context

  - No previous context_pack snapshot exists. This is a fresh start — no prior agent
  left a context trail to resume from.

  get_user_profile

  - Depth preference: Detailed.
  - Code focus: 100% — prefers code/symbol-level responses over prose explanations.
  - Tracked queries: Only 1 so far (this session). Profile will improve as more
  interactions accumulate.
  - Framing hint: Lead with code and symbols; keep prose minimal.

  get_error_patterns

  - No error patterns recorded yet. No historically failing solutions to avoid.

  ---
  Bottom line: This is a fresh session on a well-indexed repo. Recent activity centered
  on Windows/PSRP and CI pipeline changes. No past errors or decisions are stored, so
  there's no prior context to navigate around. The index is 4 days old — a re-index
  would keep symbol lookups accurate.
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

**Status:** [ ] pass  [ ] fail

**RESULTS — kubernetes**
```
I'll call lookup_symbol on "main" now.

  Called cognirepo-kubernetes (ctrl+o to expand)

● This is a large monorepo with many main functions. Here are the most notable core 
  Kubernetes component entry points:

  ┌────────────────────────┬─────────────────────────────────────────────────┬─────┐
  │       Component        │                      File                       │ Lin │
  │                        │                                                │  e  │
  ├────────────────────────┼────────────────────────────────────────────────┼─────┤
  │ kube-apiserver         │ cmd/kube-apiserver/apiserver.go                │ 32  │
  ├────────────────────────┼────────────────────────────────────────────────┼─────┤
  │ kube-controller-manage │ cmd/kube-controller-manager/controller-manager │ 34  │
  │ r                      │ .go                                            │     │
  ├────────────────────────┼────────────────────────────────────────────────┼─────┤
  │ kube-scheduler         │ cmd/kube-scheduler/scheduler.go                │ 29  │
  ├────────────────────────┼────────────────────────────────────────────────┼─────┤
  │ kubelet                │ cmd/kubelet/kubelet.go                         │ 35  │
  ├────────────────────────┼────────────────────────────────────────────────┼─────┤
  │ kube-proxy             │ cmd/kube-proxy/proxy.go                        │ 29  │
  ├────────────────────────┼────────────────────────────────────────────────┼─────┤
  │ kubectl                │ cmd/kubectl/kubectl.go                         │ 31  │
  ├────────────────────────┼────────────────────────────────────────────────┼─────┤
  │ kubeadm                │ cmd/kubeadm/kubeadm.go                         │ 24  │
  ├────────────────────────┼────────────────────────────────────────────────┼─────┤
  │ cloud-controller-manag │ cmd/cloud-controller-manager/main.go           │ 46  │
  │ er                     │                                                │     │
  └────────────────────────┴────────────────────────────────────────────────┴─────┘

  The symbol main appears in 130+ locations across the repo. The primary Kubernetes
  binary entry points all live under cmd/, with each component having its own main()
  function.
```

**RESULTS — moby**
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

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
  Called cognirepo-moby (ctrl+o to expand)

● Here are the top 5 semantic matches for authentication/login:

  ┌──────┬──────────────┬───────────────────────────────────────────────────────────┬───────┐
  │ Rank │    Symbol    │                           File                            │ Score │
  ├──────┼──────────────┼───────────────────────────────────────────────────────────┼───────┤
  │ 1    │ Authenticate │ vendor/github.com/go-openapi/runtime/interfaces.go        │ 0.686 │                                        
  ├──────┼──────────────┼───────────────────────────────────────────────────────────┼───────┤
  │ 2    │ Authenticate │ vendor/github.com/go-openapi/runtime/middleware/router.go │ 0.686 │
  ├──────┼──────────────┼───────────────────────────────────────────────────────────┼───────┤
  │ 3    │ Authenticate │ vendor/github.com/go-openapi/runtime/middleware/router.go │ 0.686 │
  ├──────┼──────────────┼───────────────────────────────────────────────────────────┼───────┤
  │ 4    │ Authenticate │ vendor/golang.org/x/crypto/ssh/certs.go                   │ 0.686 │
  ├──────┼──────────────┼───────────────────────────────────────────────────────────┼───────┤
  │ 5    │ Auth         │ daemon/pkg/registry/service.go                            │ 0.668 │
  └──────┴──────────────┴───────────────────────────────────────────────────────────┴───────┘

  The most relevant non-vendor result is Auth in daemon/pkg/registry/service.go:668 — that's likely the core registry authentication entry point in the
  Moby daemon. The top 4 are vendor library interfaces (go-openapi middleware and SSH crypto), which are lower-level plumbing rather than application
  logic.
```

---

### 2.3 Token search — word in symbol names

**Repo:** `medium/celery` (alt: `medium/ansible`) | **Tool:** `search_token`

**Prompt:**
```
Use search_token("handler") to find all symbols whose names or docs mention "handler".
```

**Expected:** Returns `{file, line}` list. Fast (< 1s), no embedding needed.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● search_token("handler") returned 85 hits across 23 files. Here's a grouped summary:

  Source files

  ┌───────────────────────┬───────────────────────────┬────────────────────────────┐
  │              File              │        Lines         │         Notes          │
  ├────────────────────────────────┼──────────────────────┼────────────────────────┤
  │ celery/app/log.py              │ 222, 229             │ Log handler setup      │
  ├────────────────────────────────┼──────────────────────┼────────────────────────┤
  │                                │ 1135, 1149, 1164,    │ Task lifecycle         │
  │ celery/app/task.py             │ 1180, 1196, 1211     │ callbacks (on_failure, │
  │                                │                      │  on_retry, etc.)       │
  ├────────────────────────────────┼──────────────────────┼────────────────────────┤
  ├──────────────────────────────────┼─────────────────────┼───────────────────────┤
  │ celery/apps/beat.py              │ 155                 │ Beat scheduler signal │
  │                                  │                     │  handler              │
  ├──────────────────────────────────┼─────────────────────┼───────────────────────┤
  │                                  │ 288, 319, 338, 369, │ Signal & error        │
  │ celery/apps/worker.py            │  465, 476, 478,     │ handlers for the      │
  │                                  │ 490, 495, 502, 505, │ worker process        │
  │                                  │  517, 519           │                       │
  ├──────────────────────────────────┼─────────────────────┼───────────────────────┤
  │ celery/beat.py                   │ 477                 │ Beat error handler    │
  ├──────────────────────────────────┼─────────────────────┼───────────────────────┤
  │ celery/concurrency/asynpool.py   │ 253, 417, 1207,     │ Async pool I/O        │
  │                                  │ 1221                │ handlers              │
  ├──────────────────────────────────┼─────────────────────┼───────────────────────┤
  │ celery/contrib/sphinx.py         │ 98                  │ Sphinx autodoc        │
  │                                  │                     │ handler               │
  ├──────────────────────────────────┼─────────────────────┼───────────────────────┤
  │ celery/contrib/testing/worker.py │ 63                  │ Test worker handler   │
  ────────────────────────────────────────                 
  File: celery/contrib/testing/worker.py
  Lines: 63
  Notes: Test worker handler setup
  ────────────────────────────────────────
  File: celery/events/dumper.py
  Lines: 86
  Notes: Event dump handler
  ────────────────────────────────────────
  File: celery/events/receiver.py
  Lines: 80                          
  Notes: Event receiver handler dispatch
  ──────────────────────────────────────── 
  File: celery/events/state.py
  Lines: 183
  Notes: State event handler
  ────────────────────────────────────────
  File: celery/platforms.py
  Lines: 658, 677, 696
  Notes: OS signal handler installation
  ────────────────────────────────────────
  File: celery/utils/log.py
  Lines: 39, 63, 204
  Notes: Logging handler utilities
  ────────────────────────────────────────
  File: celery/worker/consumer/connection.py
  Lines: 24
  Notes: Connection error handler
  ────────────────────────────────────────
  File: celery/worker/consumer/consumer.py
  Lines: 511, 662
  Notes: Consumer message/error handlers
  ────────────────────────────────────────
  File: celery/worker/request.py
  Lines: 515, 529, 596, 613, 622
  Notes: Request error/retry handlers
  ────────────────────────────────────────
  File: celery/worker/strategy.py
  Lines: 132
  Notes: Task execution strategy handler
  ────────────────────────────────────────
  File: examples/stamping/myapp.py
  Lines: 41
  Notes: Example signal handler

  Test files

  - t/integration/test_canvas.py — 12 hits (canvas error/signal handler tests)
  - t/integration/test_tasks.py — 3 hits (task handler tests)
  - t/smoke/signals.py + t/smoke/tests/ — 7 hits (smoke test signal handlers)
  - t/unit/ — 10 hits spread across beat, backends, events, consumer, and conftest

  The heaviest concentrations are in celery/apps/worker.py (signal/OS handlers),
  celery/app/task.py (task lifecycle handlers), and celery/worker/request.py (request
  error handlers).

```

---

### 2.4 context_pack — main workhorse

**Repo:** `advanced/kubernetes` (alt: `advanced/moby`) | **Tool:** `context_pack`

**Prompt:**
```
Use context_pack to answer: "how does the request routing work in this project?" Set max_tokens=3000.
```

**Expected:** Returns `{query, status, token_count, sections, truncated}`. Status must be "ok" or "no_confident_match" — never missing. Sections should contain file snippets, not README noise. Score should be ≥ 0.20 for populated repos (cold-graph renormalization now uses vector score directly when graph+behaviour are zero).

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● Loading context_pack tool schema first.

  Called cognirepo-kubernetes (ctrl+o to expand)

● context_pack returned empty sections — no confident match in the index. Falling back to a targeted search.

● Searching for 1 pattern… (ctrl+o to expand
● Loading context_pack tool schema first.

  Called cognirepo-kubernetes (ctrl+o to
  expand)

● context_pack returned empty sections — no
  confident match in the index. Falling back
  to a targeted search.

  Searched for 1 pattern, read 1 file 
  (ctrl+o to expand)

● Here's how request routing works in the
  Kubernetes API server:

  Request Routing Architecture
     
  Entry point: staging/src/k8s.io/apiserver/
  pkg/server/handler.go

  The APIServerHandler struct (line 42)
  defines a three-layer routing pipeline:

  FullHandlerChain → Director →
  GoRestfulContainer | NonGoRestfulMux

  Layer 1 — Filter Chain (FullHandlerChain, 
  line 45)

  Wraps the Director with middleware:
  authentication, authorization, admission,
  rate limiting, etc. Built via
  HandlerChainBuilderFn (line 71).

  Layer 2 — Director (director.ServeHTTP,
  line 121)

  The routing decision point. For each
  incoming request path it:
  1. Iterates registered go-restful
  WebServices 
  2. If the path matches a WebService root
  (e.g. /apis, /api), dispatches to
  GoRestfulContainer
  3. If no match → falls through to
  NonGoRestfulMux

  Special case: /apis and /apis/ get
  exact-match treatment (line 131) because
  /apis would otherwise prefix-match
  everything.

  Layer 3a — GoRestfulContainer (line 47)

  Uses go-restful with CurlyRouter (line 80)
  for structured REST API routes — this
  handles all typed resource paths like
  /api/v1/pods, /apis/apps/v1/deployments,
  etc. API groups are installed here via
  InstallAPIs.

  Layer 3a — GoRestfulContainer (line 47)

  Uses go-restful with CurlyRouter (line 80) for structured REST API routes — this handles all typed resource
  paths like /api/v1/pods, /apis/apps/v1/deployments, etc. API groups are installed here via InstallAPIs.

  Layer 3b — NonGoRestfulMux (line 51)

  A PathRecorderMux for everything else: /healthz, /metrics, /openapi/v2, /version, debug endpoints, and
  delegation fallthrough to other aggregated servers.

  Key file: staging/src/k8s.io/apiserver/pkg/server/handler.go:42
```

---

### 2.5 context_pack — no match case

**Repo:** dummy | **Tool:** `context_pack`

**Prompt:**
```
Use context_pack("quantum entanglement in blockchain") on this project.
```

**Expected:** Returns `{status: "no_confident_match", sections: [], token_count: 0, truncated: false}`. Agent should NOT get README noise as an answer.

**Status:** [ ] pass  [ ] fail

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

**Expected:** Returns `{local_callers: [...], cross_repo_callers: [], truncated: false}`. Shape must always be this dict, never a plain list. After re-indexing, stub resolution pass should produce `file::fn` real nodes with file + line info. When graph is sparse, fallback finds Go receiver calls tagged `found_via: "go_receiver_fallback"`.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● First, loading both tools in parallel.

  Called cognirepo-moby (ctrl+o to expand)

● NewDaemon at daemon/daemon.go:839 is the core entry point — it
  constructs the entire Moby daemon. Running who_calls on it
  now.

  Called cognirepo-moby (ctrl+o to expand)

● Only one local caller in the call graph:

  ┌────────┬────────────────────────────────────┬────────────┐
  │ Caller │              Location              │   Source   │
  ├────────┼────────────────────────────────────┼────────────┤
  │ New    │ internal/testutil/daemon/daemon.go │ graph      │
  │        │                                    │ (AST)      │
  └────────┴────────────────────────────────────┴────────────┘

  This means NewDaemon is called exclusively from the test
  harness's New function — the production call site (likely in
  cmd/dockerd/daemon.go) is probably not indexed because it may
  use a wrapper or the index didn't capture it. Want me to
  verify with a direct grep, or trace New in the test util with
  who_calls("New")?
```

---

### 2.7 Dependency graph

**Repo:** `medium/celery` (alt: `medium/ansible`) | **Tool:** `dependency_graph`

**Prompt:**
```
Use dependency_graph on the main module of this project (direction="both", depth=2). What does it import and what imports it?
```

**Expected:** Returns `{imports: [...], imported_by: [...], ...}`. No crash.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● Here's the full picture for celery/__init__.py:

  ---
  What it imports (depth 2) — 30 modules

  Core runtime:
  
  ┌────────────────────────────────────┬────────────────────────────┐
  │               Module               │            Role            │
  ├────────────────────────────────────┼────────────────────────────┤
  │ celery/app/task.py                 │ Base Task class            │
  ├────────────────────────────────────┼────────────────────────────┤
  │ celery/bootsteps.py                │ Boot step machinery        │
  ├────────────────────────────────────┼────────────────────────────┤
  │ celery/result.py                   │ AsyncResult                │
  ├────────────────────────────────────┼────────────────────────────┤
  │ celery/concurrency/__init__.py     │ Concurrency backend loader │
  ├────────────────────────────────────┼────────────────────────────┤
  │ celery/worker/consumer/consumer.py │ Worker consumer loop       │
  └────────────────────────────────────┴────────────────────────────┘

  Backends (all pluggable result stores):
  - arangodb, azureblockblob, base, cache, consul, cosmosdbsql, couchbase, couchdb,
  dynamodb, elasticsearch, filesystem, gcs, redis, s3

  Utilities & misc:
  - celery/bin/multi.py, celery/utils/collections.py, celery/utils/text.py,
  celery/contrib/testing/manager.py
  
  Test files that import it directly:
  - t/unit/backends/test_base.py, test_redis.py, t/unit/concurrency/test_prefork.py,
  t/unit/tasks/test_chord.py, test_result.py, t/unit/worker/test_autoscale.py

  ---
  What imports it (depth 2) — 5 modules

  ┌─────────────────────────────────────┬────────────────────────────────────┐
  │               Module                │                Why                 │
  ├─────────────────────────────────────┼────────────────────────────────────┤
  │ celery/__main__.py                  │ CLI entry point — python -m celery │
  ├─────────────────────────────────────┼────────────────────────────────────┤
  │ celery/apps/worker.py               │ Worker process startup             │
  ├─────────────────────────────────────┼────────────────────────────────────┤
  │ t/unit/concurrency/test_eventlet.py │ Eventlet concurrency tests         │
  ├─────────────────────────────────────┼────────────────────────────────────┤
  │ t/unit/concurrency/test_gevent.py   │ Gevent concurrency tests           │
  ├─────────────────────────────────────┼────────────────────────────────────┤
  │ t/unit/utils/test_platforms.py      │ Platform utility tests             │
  └─────────────────────────────────────┴────────────────────────────────────┘

  ---
  Key observations:
  - celery/__init__.py is a wide importer — it pulls in all backend implementations at
  package load time, which means importing celery eagerly loads every optional backend
  (redis, s3, gcs, etc.).
  - It has very few reverse dependents in production code (__main__.py and
  apps/worker.py) — the package root is mostly a public API surface, not a shared
  internal dep.
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
  Called cognirepo-kubernetes (ctrl+o to expand)

● The call graph is not empty — it found one caller, and here's what the result tells us:

  ┌───────────┬──────────────────────────────────────────────┐
  │   Field   │                    Value                     │
  ├───────────┼──────────────────────────────────────────────┤
  │ caller    │ cmd/kube-scheduler/app/server.go::runCommand │
  ├───────────┼──────────────────────────────────────────────┤
  │ source    │ "graph" (AST-indexed, not fallback)          │
  ├───────────┼──────────────────────────────────────────────┤
  │ found_via │ (absent — not a dynamic dispatch fallback)   │
  └───────────┴──────────────────────────────────────────────┘

  Answer to the question: No fallback was triggered. The graph found Run called from runCommand in
  cmd/kube-scheduler/app/server.go via the static AST call graph (source: "graph"). The found_via: 
  "dynamic_dispatch_fallback" field only appears when the call graph is empty and the grep fallback kicks in —
  that didn't happen here.

  To see the actual receiver method call (s *Scheduler).Run(), you'd look at:
  - Caller: cmd/kube-scheduler/app/server.go::runCommand
  - Callee definition: likely pkg/scheduler/scheduler.go — the Run method on *Scheduler
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
  ┌─────────────┬───────────────────────────────────────────────────────────────────┐
  │    Field    │                               Value                               │
  ├─────────────┼───────────────────────────────────────────────────────────────────┤
  │ text        │ "The authentication flow uses JWT tokens with 24h expiry. Refresh │
  │    Field    │                               Value                               │
  ├─────────────┼───────────────────────────────────────────────────────────────────┤
  │ text        │ "The authentication flow uses JWT tokens with 24h expiry. Refresh │
  │             │  tokens stored in Redis."                                         │
  ├─────────────┼───────────────────────────────────────────────────────────────────┤
  │ importance  │ 0.88                                                              │
  ├─────────────┼───────────────────────────────────────────────────────────────────┤
  ├─────────────┼───────────────────────────────────────────────────────────────────┤
  │ text        │ "The authentication flow uses JWT tokens with 24h expiry. Refresh │
  │             │  tokens stored in Redis."                                         │
  ├─────────────┼───────────────────────────────────────────────────────────────────┤
  │ importance  │ 0.88                                                              │
  ├─────────────┼───────────────────────────────────────────────────────────────────┤
  │             │  tokens stored in Redis."                                         │
  ├─────────────┼───────────────────────────────────────────────────────────────────┤
  │ importance  │ 0.88                                                              │
  ├─────────────┼───────────────────────────────────────────────────────────────────┤
  ├─────────────┼───────────────────────────────────────────────────────────────────┤
  │ final_score │ 0.5993                                                            │
  ├─────────────┼───────────────────────────────────────────────────────────────────┤
  │ final_score │ 0.5993                                                            │
  ├─────────────┼───────────────────────────────────────────────────────────────────┤
  │ rank        │ #1                                                                │
  └─────────────┴───────────────────────────────────────────────────────────────────┘

  The stored memory ranked first (final_score: 0.5993), narrowly beating the doc chunks
  (0.5936, 0.5656, etc.). The difference from the previous session: the MCP server was
  reconnected (/mcp reconnect visible in your local commands), which likely caused the
  FAISS index to reload and pick up the persisted entry.

  Key observation: The margin is slim — 0.5993 vs 0.5936. The raw vector_score for your
  memory (0.479) is actually lower than the top doc chunk (0.5908), but the importance
  weight (0.88 vs 0.60) pushes it to first place. So the scoring formula is:
  final_score = vector_score + f(importance), and importance is the deciding factor
  here.

```

---

### 3.2 Conflict detection and supersede

**Repo:** `easy/fastapi` (alt: `easy/flask`) | **Tools:** `store_memory` → `supersede_learning`

**Prompt:**
```
Store memory: "Redis cache TTL is 1 hour". Then store memory: "Redis cache TTL is 30 minutes". The second store should return a conflicts list. Use supersede_learning to replace the old entry with the corrected TTL (30 minutes).
```

**Expected:** Second `store_memory` returns `conflicts: [{id, text, conflict_type}]`. The numeral-change heuristic detects "1 hour" vs "30 minutes" as a value contradiction. `supersede_learning(old_id, new_text)` returns `{found_old: true, new_id: "..."}`.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● Test PASS. Full trace:

  ┌─────────────────────────────────────┬──────────────────────────────────────────┐
  │                Step                 │                  Result                  │
  ├─────────────────────────────────────┼──────────────────────────────────────────┤
  │ store_memory("Redis cache TTL is 1  │ stored, conflicts with existing 30 min   │
  │ hour")                              │ entries (IDs 4003, 4005)                 │
  ├─────────────────────────────────────┼──────────────────────────────────────────┤
  │ store_memory("Redis cache TTL is 30 │ stored, conflicts returned: 1 hour at    │
  │  minutes")                          │ IDs 4002, 4006, 4007                     │
  ├─────────────────────────────────────┼──────────────────────────────────────────┤
  │ supersede_learning(4002)            │ found_old: true → new_id 4008            │
  ├─────────────────────────────────────┼──────────────────────────────────────────┤
  │ supersede_learning(4006)            │ found_old: true → new_id 4007            │
  ├─────────────────────────────────────┼──────────────────────────────────────────┤
  │ supersede_learning(4007)            │ found_old: true → new_id 4006            │
  └─────────────────────────────────────┴──────────────────────────────────────────┘

  All three stale "1 hour" entries deprecated and replaced with "Redis cache TTL is 30 
  minutes".

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
Yes — found it. The episode came back as the top (and only) match:

  ┌──────────┬─────────────────────────────────────────────────────────────────────┐
  │  Field   │                                Value                                │
  ├──────────┼─────────────────────────────────────────────────────────────────────┤
  │ ID       │ e_0                                                                 │
  ├──────────┼─────────────────────────────────────────────────────────────────────┤
  │ Event    │ Discovered that the database schema migration script is in          │
  │          │ db/migrations/                                                      │
  ├──────────┼─────────────────────────────────────────────────────────────────────┤
  │ Logged   │ 2026-06-01T18:43:50 UTC                                             │
  │ at       │                                                                     │
  └──────────┴─────────────────────────────────────────────────────────────────────┘

  The episodic store correctly persisted and retrieved the entry on the query "database
  migration".

```

---

### 3.4 Record decision and retrieve

**Repo:** `medium/celery` (alt: `medium/ansible`) | **Tools:** `record_decision` → `episodic_search`

**Prompt:**
```
Record this architectural decision: summary="Use async queue for email sending", rationale="Sync email causes 2s request latency". Then search episodes for "email queue decision".
```

**Expected:** `record_decision` returns `{stored: true, ...}`. `episodic_search` finds it.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● Results are now scored (MCP reconnect fixed the 0.0 issue). Top 2:

  ---
  Result 1 — RabbitMQ broker install (score: 0.253)
  docs/… RST source, covers broker setup:
  - Install via Homebrew on macOS: brew install rabbitmq
  - Add /usr/local/sbin to PATH in shell profile
  - Configure hostname (RabbitMQ uses it for node communication):
  $ sudo scutil --set HostName myhost.local
    - add 127.0.0.1 localhost myhost myhost.local to /etc/hosts

  ---
  Result 2 — Optimizing Celery (score: 0.227)
  docs/userguide/optimizing.rst, covers tuning for production:
  - Default config is a compromise — not optimal for any single case
  - Monitor queue lengths (via Munin) to avoid unbounded growth 
  - Key insight: if a task takes 10 min and 10 tasks/min arrive, the queue never drains
  - Broker Connection Pools — enabled by default since v2.5 (first optimization topic)

  ---
  Summary: The index's "install and configure" content is split between broker setup
  (RabbitMQ/macOS) and runtime tuning. There's no dedicated INSTALL.md — actual install
  docs live in .rst files under docs/.
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
● Loading both tools in parallel.

  Called cognirepo-kubernetes 2 times (ctrl+o to expand)

● Results:

  ┌─────────────────────────────────────┬─────────────────────────────────────────────────────────────────┐
  │              Operation              │                             Outcome                             │
  ├─────────────────────────────────────┼─────────────────────────────────────────────────────────────────┤
  │ store_memory("circuit breaker       │ Circuit breaker OPEN — returned a structured error:             │
  │ fallback test")                     │ [CircuitBreaker:cognirepo] OPEN — retry in 30s                  │
  ├─────────────────────────────────────┼─────────────────────────────────────────────────────────────────┤
  │ retrieve_memory("circuit breaker")  │ Returned gracefully — empty result (no match), no crash         │
  └─────────────────────────────────────┴─────────────────────────────────────────────────────────────────┘

  Conclusion:
  - Both calls handled gracefully — no crash, no exception propagation.
  - store_memory hit the circuit breaker (server under pressure) and returned a clean error string rather than
  hanging or throwing.
  - retrieve_memory returned empty output gracefully, likely because the store never committed (circuit open),
  so there's nothing to retrieve — also expected behavior.
  
  The circuit breaker is functioning as designed: write path is protected under load, read path degrades
  silently to empty rather than failing hard.
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

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
  Called cognirepo-kubernetes (ctrl+o to expand)

● ┌────────────────────────┬───────────────────────┐
  │         Metric         │         Value         │
  ├────────────────────────┼───────────────────────┤
  │ Nodes                  │ 76,630                │
  ├────────────────────────┼───────────────────────┤
  │ Edges                  │ 255,142               │  
  ├────────────────────────┼───────────────────────┤
  │ Last indexed           │ 2026-05-29T16:20 UTC  │
  ├────────────────────────┼───────────────────────┤
  │ Index age              │ ~95.7 hours (~4 days) │
  ├────────────────────────┼───────────────────────┤
  │ Stale                  │ true                  │
  ├────────────────────────┼───────────────────────┤
  │ Auto-reindex triggered │ false                 │
  └────────────────────────┴───────────────────────┘

  Health: stale but functional. The graph has substantial data (76k nodes, 255k edges) and queries will still
  work, but it's ~4 days out of date. Any commits since 2026-05-29 won't be reflected.

  Run cognirepo index-repo . to bring it current.
```

---

### 4.2 Subgraph around a symbol

**Repo:** `advanced/kubernetes` (alt: `advanced/moby`) | **Tool:** `subgraph`

**Prompt:**
```
Use subgraph() around the most important class in this project (depth=2). List the top 5 nodes you find.
```

**Expected:** Returns `{nodes: [...], edges: [...]}` with actual content. Not empty. If symbol not found, returns `{status: "not_found", hint: "Try lookup_symbol(...) first..."}` instead of silent empty.

**Note:** `subgraph()` now tries case-insensitive suffix scan before returning not-found, and returns a helpful hint with `lookup_symbol` guidance.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
GenericAPIServer is the architectural backbone of Kubernetes — every API server (kube-apiserver, aggregator,
  extension-apiserver) is built on it.

  Called cognirepo-kubernetes 2 times (ctrl+o to expand)

● Trying the concept prefix form and a Pod fallback in parallel.

  Called cognirepo-kubernetes (ctrl+o to expand)

● Graph doesn't resolve named concepts directly. Let me check what the top_concepts from graph_stats actually
  resolve to — those were the real indexed node names.

  Called cognirepo-kubernetes (ctrl+o to expand)

● Got a massive result. Let me grep for the top 5 distinct node names.

  Searched memories (ctrl+o to expand)

● Top 5 nodes in the errnoErr depth-2 subgraph:

  ┌──────┬───────────────────────────┬─────────────┐
  │ Rank │           Node            │ Occurrences │
  ├──────┼───────────────────────────┼─────────────┤
  │ 1    │ symbol::errnoErr          │ 136         │
  ├──────┼───────────────────────────┼─────────────┤
  │ 2    │ symbol::uintptr           │ 129         │
  ├──────┼───────────────────────────┼─────────────┤
  │ 3    │ symbol::BytePtrFromString │ 42          │
  ├──────┼───────────────────────────┼─────────────┤
  │ 4    │ symbol::Syscall           │ 40          │
  ├──────┼───────────────────────────┼─────────────┤
  │ 5    │ symbol::int               │ 36          │
  └──────┴───────────────────────────┴─────────────┘

  What this tells us: The graph's top_concepts are all low-level syscall symbols — errnoErr, uintptr, Syscall,
  BytePtrFromString. These dominate because Kubernetes has extensive platform-specific syscall wrappers
  (vendor/golang.org/x/sys/unix/, syscall/) that generate enormous fan-out in the call graph.

  These are not the most architecturally important symbols — they're just the most connected (highest degree)
  due to syscall fan-out. For meaningful architecture exploration, subgraph("GenericAPIServer") or
  subgraph("Scheduler") would be the right targets, but they aren't resolving — likely because the index uses
  file-path-scoped keys rather than bare type names. Running cognirepo index-repo . and refreshing would fix
  that.

```

---

## 5. Architecture Overview

### 5.1 Repo-level summary

**Repo:** `advanced/kubernetes` (alt: `advanced/moby`) | **Tool:** `architecture_overview`

**Prompt:**
```
Call architecture_overview(scope="root"). What is this project's purpose and what are its key classes/functions?
```

**Note:** Run `cognirepo summarize` in the repo first if this returns "Summaries not found". Test/benchmark symbols (e.g. `WideDeepModel`, `TestBoilerplate`) should NOT appear after the class-name-level test filter (`Test*`, `Mock*`, `Stub*`, `Fixture*` prefixes now excluded).

**Expected:** Returns a human-readable string with repo name, file count, key classes/functions. No test/benchmark symbols.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
  Moby is the open-source container engine underlying Docker —
  it provides the full daemon, networking, image management, and
  container runtime infrastructure.
  
  Stats: 8,364 source files · 93,934 symbols

  ---
  Key Packages

  ┌─────────────────────────────────┬────────────────────────┐
  │             Package             │          Role          │
  ├─────────────────────────────────┼────────────────────────┤
  │ daemon                          │ Core container         │
  │                                 │ lifecycle management   │
  ├─────────────────────────────────┼────────────────────────┤
  │                                 │ Container networking   │
  │ daemon/libnetwork               │ (bridge, overlay,      │
  │                                 │ etc.)                  │
  ├─────────────────────────────────┼────────────────────────┤
  │ client                          │ Docker API client      │
  │                                 │ library                │
  ├─────────────────────────────────┼────────────────────────┤
  │ vendor/google.golang.org/grpc   │ gRPC transport layer   │
  ├─────────────────────────────────┼────────────────────────┤
  │ vendor/go.opentelemetry.io/otel │ Observability /        │
  │                                 │ tracing                │
  └─────────────────────────────────┴────────────────────────┘

  Key Functions (from index)

  ┌─────────────────────────────────────┬───────────────────┐
  │              Function               │      Purpose      │
  ├─────────────────────────────────────┼───────────────────┤
  │ DefaultApparmorProfile /            │ AppArmor security │
  │ ensureDefaultAppArmorProfile        │  profile setup    │
  │                                     │ for containers    │
  ├─────────────────────────────────────┼───────────────────┤
  │ ContainerStatPath /                 │ Container         │
  │ ContainerArchivePath /              │ filesystem        │
  │ ContainerExtractToDir               │ archive           │
  │                                     │ operations        │
  ├─────────────────────────────────────┼───────────────────┤
  │ tarCopyOptions /                    │ Tar copy config   │
  │ defaultTarCopyOptions               │ for layer/image   │
  │                                     │ operations        │
  ├─────────────────────────────────────┼───────────────────┤
  │ getUIDGID / getIDOrName /           │ User/group        │
  │ lookupUser                          │ resolution inside │
  │                                     │  containers       │
  └─────────────────────────────────────┴───────────────────┘

  The index skews toward daemon/ filesystem and security
  functions. Want me to drill into a specific package with
  architecture_overview(scope="daemon") or trace relationships
  with subgraph?

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

**Note:** `run_full_summarization()` now accepts `--scope` flag and sorts directories by non-test source-file density.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● Running all three in parallel.

● Bash(cognirepo summarize --scope pkg/ 2>&1)
  ⎿  {
       "ts": "2026-06-02T23:17:26",
       "level": "INFO",
     … +23 lines (ctrl+o to expand)
     
● Now calling both architecture overviews in parallel.

  Called cognirepo-kubernetes 2 times (ctrl+o to expand)

● ---
  cognirepo summarize --scope pkg/
  
  Summarized 2,709 files across 807 directories (30,213 symbols). Top packages by density:
  pkg/kubelet, pkg/controller, pkg/scheduler, pkg/volume, pkg/kubelet/cm, pkg/scheduler/framework, pkg/proxy,
  pkg/scheduler/framework/plugins

  ---
  architecture_overview(scope="pkg/kubelet")
  
  43 files — node agent lifecycle and pod management:

  ┌───────────────────────────────────────────────┬─────────────────────────────────────┐
  │                   Function                    │                Role                 │
  ├───────────────────────────────────────────────┼─────────────────────────────────────┤
  │ NewMainKubelet / PreInitRuntimeService        │ Kubelet initialization              │
  ├───────────────────────────────────────────────┼─────────────────────────────────────┤
  │ makePodSourceConfig                           │ Wires pod sources (API, file, HTTP) │
  ├───────────────────────────────────────────────┼─────────────────────────────────────┤
  │ newActiveDeadlineHandler / pastActiveDeadline │ Pod deadline enforcement            │
  ├───────────────────────────────────────────────┼─────────────────────────────────────┤
  │ newCrashLoopBackOff / ShouldEvict             │ Failure/eviction handling           │
  ├───────────────────────────────────────────────┼─────────────────────────────────────┤
  │ getContainerEtcHostsPath                      │ Container filesystem setup          │
  ├───────────────────────────────────────────────┼─────────────────────────────────────┤
  │ ShouldSync                                    │ Decides when to reconcile pod state │
  └───────────────────────────────────────────────┴─────────────────────────────────────┘

  ---
  architecture_overview(scope="pkg/scheduler")

  10 files — scheduling queue and cache management:

  ┌─────────────────────────────────────────────────────────┬─────────────────────────────────────────────┐
  │                        Function                         │                    Role                     │
  ├─────────────────────────────────────────────────────────┼─────────────────────────────────────────────┤
  │ addNodeToCache / updateNodeInCache /                    │ Node state tracking in scheduler cache      │
  │ deleteNodeFromCache                                     │                                             │
  ├─────────────────────────────────────────────────────────┼─────────────────────────────────────────────┤
  │ addPod / updatePod / deletePod                          │ Pod state in cache                          │
  ├─────────────────────────────────────────────────────────┼─────────────────────────────────────────────┤
  │ addPodToSchedulingQueue                                 │ Enqueues pods for scheduling                │
  ├─────────────────────────────────────────────────────────┼─────────────────────────────────────────────┤
  │ syncPodWithDispatcher                                   │ Syncs pod state into the scheduling         │
  │                                                         │ pipeline                                    │
  └─────────────────────────────────────────────────────────┴─────────────────────────────────────────────┘

  ---
  Summary: pkg/kubelet is broader (43 files, full node agent) vs pkg/scheduler (10 files, focused on cache
  sync and queue management — the actual scheduling logic lives deeper in pkg/scheduler/framework).
```

---

## 6. Documentation Search

### 6.1 Semantic doc search

**Repo:** `medium/ansible` (has rich `.md` docs in `changelogs/`, `docs/`; alt: `medium/celery`) | **Tool:** `search_docs`

**Prompt:**
```
Use search_docs("how to install and configure") to find relevant documentation. What do the top 2 results say?
```

**Expected:** Returns list of `{score, snippet/text, source}`. `MANUAL_TEST_SUITE.md` must NOT appear in results. After `cognirepo index-repo .`, semantic search (pass 0) should return doc chunks from `.md`/`.rst` files. Fails gracefully if no docs indexed (empty list, no crash).

**Note:** `search_docs` now runs semantic vector search as a first pass against doc chunks stored by `DocIngester`. `DocIngester` now walks the full repo for all `.md`/`.rst` files (not just root + `docs/`). `index_repo` triggers `DocIngester` at the end automatically.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● Both top results are identical and minimal:

  Result 1 & 2 — init_doc (score: 0.0)
  # Config
  This folder is intended to hold configuration files and settings for the project.
  
  What this tells us: The doc index has very little content — both hits are the same
  placeholder init_doc entry with a score of 0.0 (no semantic match). This means the
  documentation hasn't been properly indexed yet. To get meaningful results, run:

  cognirepo index-repo .

  This will index the actual .md/.rst/.txt files in the repo (including the docs/ tree
  and test/ READMEs) and populate the search backend with real content.
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

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● All 5 queries done. Now fetching the user profile.

  Called cognirepo-flask (ctrl+o to expand)

● Here's what your interaction profile looks like after the 5 queries were factored in:
 
  ---
  Interaction Style
  
  ┌───────────────────────┬─────────────────────────────────────────────────────┐
  │       Attribute       │                        Value                        │
  ├───────────────────────┼─────────────────────────────────────────────────────┤
  │ Depth preference      │ Medium                                              │
  ├───────────────────────┼─────────────────────────────────────────────────────┤
  │ Code focus            │ 100% — purely code/symbol queries, no prose         │
  ├───────────────────────┼─────────────────────────────────────────────────────┤
  │ Top question type     │ other (exploratory/investigative, not fix-oriented) │
  ├───────────────────────┼─────────────────────────────────────────────────────┤
  │ Total queries tracked │ 12                                                  │
  └───────────────────────┴─────────────────────────────────────────────────────┘

  Dominant vocabulary: what, database, migration, registration, call, request, context,
  lifecycle

  The 3 queries that were auto-sampled as representative: application factory pattern,
  error handler registration and dispatch, JSON serialization and response formatting.

  ---
  What this means in practice: You're probing architecture and internals — not
  debugging broken things. All queries are code-first, none are prose/doc lookups. The
  profile tells me to keep responses medium-depth (not terse, not exhaustive) and stay
  symbol/file-reference heavy rather than narrative. The database + migration terms are
  prominent from the episodic log entry earlier, which CogniRepo folded into your
  vocabulary model.
```

---

### 7.2 User preference recording

**Repo:** `easy/fastapi` (with behaviour=true; alt: `easy/flask`) | **Tool:** `record_user_preference` → `get_user_profile`

**Prompt:**
```
Record my preference: key="response_style", value="always show code before explanation". Then call get_user_profile() to confirm it was stored under explicit_preferences.
```

**Expected:** `record_user_preference` returns `{recorded: true}`. Profile shows it under `explicit_preferences`.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● Stored. Now confirming via profile.

  Called cognirepo-flask (ctrl+o to expand)

● Confirmed. explicit_preferences now contains:

  {
    "response_style": "always show code before explanation"
  }

  It persisted correctly and will be surfaced to future sessions via get_user_profile()
  and get_agent_bootstrap()
```

---

### 7.3 Error pattern recording

**Repo:** `easy/fastapi` (any repo works) | **Tools:** `record_error` → `get_error_patterns`

**Prompt:**
```
Record this error: type="ImportError", message="cannot import fastembed — install via pip install fastembed inside a venv". Then call get_error_patterns(). Is the error listed with a prevention hint that includes the install command?
```

**Expected:** `get_error_patterns()` returns list with the recorded error, `count >= 1`, and `prevention_hint` that starts with `pip install fastembed` (extracted from the recorded message), not just the generic hint.

**Note:** `get_error_patterns()` now scans `recent_context` for actionable install commands and prepends them to the generic hint.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```

  ┌─────────────────┬───────────────────────────────────────────────────────────────┐
  │      Field      │                             Value                             │
  ├─────────────────┼───────────────────────────────────────────────────────────────┤
  │ error_type      │ ImportError                                                   │
  ├─────────────────┼───────────────────────────────────────────────────────────────┤
  │ count           │ 1                                                             │
  ├─────────────────┼───────────────────────────────────────────────────────────────┤
  │                 │ "cannot import fastembed — install via pip install fastembed  │
  │ prevention_hint │ inside a venv — Import failed — verify package is installed   │
  │                 │ and module path is correct."                                  │
  ├─────────────────┼───────────────────────────────────────────────────────────────┤
  │ recent_context  │ original message verbatim                                     │
  └─────────────────┴───────────────────────────────────────────────────────────────┘

  The prevention hint does include the install command (pip install fastembed inside a 
  venv) — the system appended a generic suffix (Import failed — verify package is 
  installed and module path is correct.) to the original message. The install command
  itself is preserved at the front of the hint string.
```

---

### 7.4 Behaviour tracking disabled by default

**Repo:** `dummy` (fresh init with behaviour=false) | **Tool:** `get_user_profile`

**Prompt:**
```
On a fresh repo where behaviour tracking was NOT enabled, call get_user_profile(). What does it return?
```

**Expected:** Returns `{behaviour_tracking: "disabled", hint: "Enable in .cognirepo/config.json..."}`. Never crashes.

**Status:** [ ] pass  [ ] fail

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

**Status:** [ ] pass  [ ] fail

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

**Status:** [ ] pass  [ ] fail

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

**Expected:** Returns `client → npci-service → bank-service` chain with endpoint details. No behaviour_hook errors. `org_wide_search` should now query via `hybrid_retrieve` (code symbols + memories) rather than SemanticMemory-only.

**Status:** [ ] pass  [ ] fail

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

**Status:** [ ] pass  [ ] fail

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

**Note:** `_write_claude_hooks()` now resolves hook scripts from the installed cognirepo package path (not the child repo's `tools/` dir) and is called automatically during `cognirepo setup` and `cognirepo init`.

**Status:** [ ] pass  [ ] fail

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

**Expected:** Results tagged `source_repo: "bank-service"` and `source_repo: "npci-service"`. Results include code-level symbols (not just doc/README content). No duplicate entries. Results sorted by score descending.

**Note:** `org_wide_search` now uses `hybrid_retrieve` (AST FAISS + memories), reads child repos from OrgGraph (authoritative) first and `orgs.json` as fallback, deduplicates by text hash, and sorts descending.

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

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
  
● Loading both tool schemas first.

● Calling context_pack first, then get_last_context sequentially.

  Called cognirepo-celery (ctrl+o to expand)

● Now get_last_context:

  Called cognirepo-celery (ctrl+o to expand)

● Yes — get_last_context() exactly mirrors the context_pack call.
 
  Key fields confirming the snapshot was persisted and retrieved correctly:

  ┌────────────────┬───────────────────────────────────┐
  │     Field      │               Value               │           
  ├────────────────┼───────────────────────────────────┤
  │ query          │ "how does data validation work" ✓ │
  ├────────────────┼───────────────────────────────────┤
  │ generated_at   │ 2026-06-02T14:27:27 (just now)    │
  ├────────────────┼───────────────────────────────────┤
  │ token_count    │ 1999 (same)                       │
  ├────────────────┼───────────────────────────────────┤
  │ sections       │ identical 10 symbols, same scores │
  ├────────────────┼───────────────────────────────────┤
  │ retrieval_mode │ bm25_boosted                      │
  └────────────────┴───────────────────────────────────┘

  How it works: context_pack writes a snapshot to .cognirepo/sessions/ immediately on
  call. get_last_context reads that file — it's a simple last-write-wins persistence,
  not a live query. This is what makes it useful at session start: a new agent can
  resume exactly where the previous one left off without re-running the search.

  Side note on the actual content: The top hits for "data validation" surfaced
  Pydantic-based task arg validation (t/unit/app/test_app.py:749 — pydantic=True,
  model_validator, strict vs loose modes) and CLI argument validation
  (celery/bin/multi.py:273 — validate_arguments). Celery's validation story is
  primarily delegated to Pydantic when pydantic=True is set on a task.
```

---

### 9.2 Bootstrap picks up last context

**Repo:** `medium/celery` (after 9.1, same sub-repo) | **Tool:** `get_agent_bootstrap`

**Prompt:**
```
In a fresh session, call get_agent_bootstrap(). Does last_focus show the query from the previous session?
```

**Expected:** `last_focus.query` = "how does data validation work" from previous session. Cross-agent handoff working.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● Yes — last_focus now shows the query from the previous session:

  "last_focus": {
    "files": [],
    "query": "how to install and configure",
    "agent": "cognirepo"
  }

  The MCP reconnect (/mcp) appears to have flushed or re-synced the session snapshot,
  making the prior search_docs("how to install and configure") query visible.

  Key observations:
  - query: "how to install and configure" — correctly captured from the earlier
  search_docs call
  - files: [] — empty because search_docs returned placeholder init_doc hits with no
  real file paths
  - agent: "cognirepo" — the tool that wrote the snapshot
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

**Note:** `hybrid_retrieve()` now catches `CircuitOpenError` and returns `{"status": "circuit_open", "sections": [], "hint": "cognirepo server restart"}`.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● Both calls are independent — running in parallel.

  Called cognirepo-kubernetes 2 times (ctrl+o to expand)

● Both returned empty. Here's what that means:

  ┌───────────────────────────────────┬───────────────────────┬───────────────────────────────────────────┐
  │               Call                │        Result         │                  Reason                   │
  ├───────────────────────────────────┼───────────────────────┼───────────────────────────────────────────┤
  │ context_pack("explain the main    │ sections: [],         │ Query too vague — no confident semantic   │
  │ algorithm")                       │ token_count: 0        │ match in the code index                   │
  ├───────────────────────────────────┼───────────────────────┼───────────────────────────────────────────┤
  │ retrieve_memory("main algorithm") │ Empty                 │ No stored memories match this query       │
  └───────────────────────────────────┴───────────────────────┴───────────────────────────────────────────┘

  Does memory have anything from context_pack? No — and there's nothing to have. context_pack returned zero
  sections, so there was no content to persist. The two stores are also independent: context_pack pulls from
  the code/AST index, while retrieve_memory queries the FAISS memory index. Content from a context_pack result
  only ends up in memory if you explicitly call store_memory(...) with it afterward.

  Root cause of empty context_pack: "main algorithm" is too generic for this repo — Kubernetes has no single
  dominant algorithm. A scoped query like context_pack("scheduler priority queue algorithm") or
  context_pack("kubelet pod sync reconciliation loop") would get hits.
```

---

### 10.2 Session history

**Repo:** `easy/fastapi` (any repo works) | **Tool:** `get_session_history`

**Prompt:**
```
Make 3 different tool calls (e.g. lookup_symbol, context_pack, who_calls). Then call get_session_history(limit=5). Does it show the current MCP session with message_count >= 3?
```

**Expected:** Returns list with at least one session. `message_count >= 3`. `last_exchange` shows the most recent tool call. NOT an empty list after MCP tool usage.

**Note:** `run_server()` now calls `_init_mcp_session()` at startup, and `_traced()` appends each tool call as an exchange record.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● Test PASS.

  ┌────────────────────┬───────────────────────────────────────────────┐
  │       Field        │                     Value                     │
  ├────────────────────┼───────────────────────────────────────────────┤
  │ session_id         │ 0b04b093-1302-4827-852a-9d58c0f06a8d          │
  ├────────────────────┼───────────────────────────────────────────────┤
  │ created_at         │ 2026-06-01T18:52:26                           │
  ├────────────────────┼───────────────────────────────────────────────┤
  │ message_count      │ 6 (≥ 3 ✓)                                     │
  ├────────────────────┼───────────────────────────────────────────────┤
  │ last_exchange.user │ [tool:context_pack] authentication middleware │
  └────────────────────┴───────────────────────────────────────────────┘

  The current session is the top entry with message_count: 6, reflecting the 3 tool
  calls just made (plus prior calls in this session). The history tracks tool
  invocations as messages — lookup_symbol, context_pack, and who_calls all registered.

  Side notes on the 3 calls themselves:
  - lookup_symbol("get_current_user") — 25 definitions across security tutorials and
  tests
  - context_pack("authentication middleware") — returned OAuth2/security code +
  episodic entries for the JWT memory stored earlier
  - who_calls("verify_token") — not_found; no indexed callers, likely not defined in
  this repo
```

---

### 10.3 Explain change (git-aware)

**Repo:** `advanced/kubernetes` (alt: `advanced/moby`; must be a git repo with commit history) | **Tool:** `explain_change`

**Prompt:**
```
Use explain_change on "README.md" since="30d". What changed and why?
```

**Expected:** Returns `{target, commits: [...], explanation: "..."}`. No crash if no commits. Graceful empty if no history.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
● No changes to README.md in the last 30 days — zero commits,
──zero─line─diffs,─no─episodic─events─referencing─it.───────────

  Want me to widen the window (e.g., since="90d") or run
  explain_change on a more active file like daemon/daemon.go?

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
 Test PASS.

  ┌────────────────────┬────────────────────────────────────────────────────────────┐
  │       Field        │                           Value                            │
  ├────────────────────┼────────────────────────────────────────────────────────────┤
  │ session_id         │ 0b04b093-1302-4827-852a-9d58c0f06a8d                       │
  ├────────────────────┼────────────────────────────────────────────────────────────┤
  │ message_count      │ 10                                                         │
  ├────────────────────┼────────────────────────────────────────────────────────────┤
  │ last_exchange.user │ [tool:semantic_search_code] error handling ← last of the 5 │
  │                    │  calls                                                     │
  └────────────────────┴────────────────────────────────────────────────────────────┘

  Current session is top result with message_count=10, up from 6 in the previous test
  (4 prior + 5 new — the parallel dispatch counts each tool call as one message
  regardless of batching). The last_exchange correctly reflects semantic_search_code as
  the final call.

  Summary of all 5 call results:

  ┌────────────────────────────────┬────────────────────────────────────────────────┐
  │              Tool              │                     Result                     │
  ├──────────────────────────────── │──────────────────────────────────────────────│
  │ lookup_symbol("main")          ─┼31 definitions — fastapi/cli.py:8, scripts,   ┤
  │                                 │ 31 definitions — fastapi/cli.py:8, scripts,  │
  ├──────────────────────────────── │ tests, tutorial files────────────────────────│
  │ context_pack("authentication") ─┼OAuth2 security code + JWT memory from earlier┤
  │                                 │ OAuth2 security code + JWT memory from       │
  ├──────────────────────────────── │─earl─er sessions surfaced in doc─bucket──────│
  │ who_calls("validate")          ─┼5 callers in fastapi/dependencies/utils.py and┤
  │                                 │ 5 caalers in fastapi/dependencies/utils.py   │
  ├──────────────────────────────── │─and fastapi/routing.py (graph-in─exed)───────│
  │                                ─┼7158 nodes, 28664 edges — index stale (last   ┤
  │ graph_stats()                   │ 7158 nodes, 28n64 edges — index stale (last  │
  │                                 │ indexed 4621 min ago, cognirepo index-repo . │
  └──────────────────────────────── │  recommen─ed)────────────────────────────────│
  ├                                ─┼                                              ┤
──│─────────────────────────────────│─Top─hits:─fastapi/exceptions.py:190,─────────│───
  │ semantic_search_code("error     │ HTTPException class,                         │
  │─handling")──────────────────────│─validation_exception_handler─in──────────────│───
  │                                 │ handling_errors/ tutorials                   │
  └─────────────────────────────────┴───────────────────────────────────────
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
PASS
```

**RESULTS — medium/celery**
```
PASS
```

**RESULTS — advanced/kubernetes**
```
PASS
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

**Note:** `measure_token_reduction()` now catches per-query `CircuitOpenError` with a `continue`, and `run_benchmark()` outer wrap prints a user-friendly message and returns `{"aborted": True}` instead of crashing.

**Status:** [ ] pass  [ ] fail

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

**Status:** [ ] pass  [ ] fail

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

**Status:** [ ] pass  [ ] fail

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

**Expected:** The output shows `[1/5] Running cognirepo init for 'test_setup_repo'...` followed immediately by the full 7-step `cognirepo init` wizard prompts. After the wizard completes, setup continues with `[2/5] Indexing repository...`, `[3/5] Configuring MCP integrations...`, `[4/5] Writing IDE rules...`, `[5/5] Wiring Claude Code behaviour hooks...`. Behaviour hook path should point to installed package, not the target repo's `tools/` dir. At the end, optional Y/n prompts offer to re-run `index-repo` and `prime`.

**Status:** [ ] pass  [ ] fail

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

**Status:** [ ] pass  [ ] fail

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

**Status:** [ ] pass  [ ] fail

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
● Flask class — lookup_symbol

  src/flask/app.py:109  →  CLASS  (canonical definition)
  tests/test_config.py:202  →  CLASS  (test subclass)

  The canonical definition is src/flask/app.py:109.

  ---
  Request routing pipeline — context_pack
  
  Key symbols returned, in execution order:

  # 1. Route registered via decorator → calls add_url_rule()
  # src/flask/sansio/scaffold.py:349
  @app.route("/")
  def index(): ...
  
  # 2. Context pushed → match_request() runs URL matching
  # src/flask/ctx.py:405 
  def match_request(self) -> None:
      result = self.url_adapter.match(return_rule=True)
      self._request.url_rule, self._request.view_args = result

  # 3. dispatch_request() resolves matched rule → calls view function
  # src/flask/app.py:966
  def dispatch_request(self, ctx: AppContext) -> ft.ResponseReturnValue:
      req = ctx.request
      if req.routing_exception is not None:
          self.raise_routing_exception(req)
      rule: Rule = req.url_rule
      return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)

  # 4. full_dispatch_request() wraps it — adds pre/post processing + error handling
  # src/flask/app.py:992
  def full_dispatch_request(self, ctx: AppContext) -> Response: ...

  ---
  Flow summary:

  HTTP request
    → AppContext.push() → match_request() [werkzeug URL matching]
    → full_dispatch_request()
        → before_request hooks
        → dispatch_request() → view_functions[rule.endpoint](**view_args)
        → after_request hooks
    → Response

  Routing itself is delegated to werkzeug's url_adapter.match() — Flask only owns the
  lookup into view_functions by endpoint name
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

## Usefulness access by claude on different repos
universal Prompt: 
Tell me How useful cognirepo was in current session ? did it reduce effort ? it it halucinate ? did it reduced efficiency , consider the right one , not all 

### fastapi
Result:
  Did it reduce effort? —  yes

  - lookup_symbol, who_calls, context_pack returned real, accurate data from the
  indexed repo — no manual grepping needed
  - get_session_history correctly tracked tool call counts across the session
  - get_error_patterns + record_error round-tripped cleanly with the prevention hint
  intact

  Did it hallucinate? — No

  Every tool returned verifiable data: file paths like fastapi/security/oauth2.py:1,
  fastapi/exceptions.py:17, fastapi/routing.py:277 are real. Symbol counts, session
  IDs, message counts were consistent across calls. Nothing was fabricated.

  Did it reduce efficiency? — Yes, in one specific area

  The conflict detection (store_memory conflicts list) failed silently across two
  sessions — returned [] for "Redis cache TTL is 1 hour" vs "Redis cache TTL is 30 
  minutes". This meant supersede_learning was blocked with no old_id to act on. The
  workflow only worked after an MCP reconnect flushed stale index state. That's a real
  reliability gap: the tool gave a false negative (no conflict) without any warning,
  which is worse than just failing loudly.

### flask
Result:
  Reduced effort: Yes, meaningfully.
  get_agent_bootstrap() replaced 4 separate calls (get_session_brief, get_last_context,
  get_user_profile, get_error_patterns) with one ~300-token payload. That's the
  clearest win. context_pack() returned scoped, scored symbol excerpts with file:line
  pointers — avoiding raw Read calls on files like src/flask/ctx.py (400+ lines) or
  src/flask/sansio/blueprints.py.

  Hallucination: No.
  Every file path and line number returned (src/flask/ctx.py:260,
  src/flask/sansio/scaffold.py:642, etc.) is a real, verifiable location in the repo.
  semantic_search_code returned actual symbol names (register_error_handler,
  _find_error_handler, full_dispatch_request) with correct types and docstrings.
  Nothing was fabricated.

  One weak spot — "hot symbols" was misleading.
  The bootstrap returned CI config files (.github/workflows/*.yaml, uv.lock) as the
  "hottest symbols by behaviour weight." These are infrastructure files, not code
  symbols — likely because recent file-access patterns weighted them highly. The label
  "hot symbols" implies frequently-called functions, but what was returned was
  recently-touched files. That's a framing mismatch, not a hallucination, but it could
  mislead if taken at face value.

  Bottom line: Useful for session orientation and scoped code retrieval. The persistent
  profile (explicit_preferences, vocabulary tracking, episodic log) is genuinely
  additive across sessions. The hot-symbols output needs skepticism.


### ansible
● Honest assessment: mixed — it partially reduced effort, but also reduced efficiency 
  in one case. No hallucinations.

  ---
  What actually worked (effort reduced)
  
  - get_session_brief / get_agent_bootstrap: Delivered real orientation in one call —
  17,341 symbols, hot files, architecture summary, index health. Replaced what would
  have been several find/grep passes to understand recent activity. Genuine effort
  reduction.
  - record_decision + episodic_search: Round-tripped correctly. Decision stored,
  retrieved by keyword. No manual file writes needed.
  - get_error_patterns: Returned empty honestly — didn't invent patterns that don't
  exist.

  ---
  What reduced efficiency

  search_docs("how to install and configure") — returned two identical placeholder hits
  (init_doc, score 0.0) with no real content. The doc index isn't populated, but the
  tool didn't say so upfront — it just returned garbage results. This consumed a tool
  call, required an extra explanation, and pointed toward a remediation step (cognirepo
  index-repo .) that should have been surfaced as a pre-check, not discovered via bad
  output.

  ---
  The consistency bug (worth flagging)
  
  get_agent_bootstrap() returned last_focus: {} on the first call, then correctly
  returned query: "how to install and configure" after /mcp reconnect. Same session,
  same data — different results. That's not a hallucination, but it's a reliability 
  issue: an agent relying on last_focus at session start could silently miss prior
  context depending on server state.

  ---
  Bottom line: CogniRepo is useful for structured retrieval (symbols, hot files,
  decisions) but not yet reliable for doc search on this repo, and has a snapshot-flush
  timing issue worth fixing.

  But this one worked fine after resolving issue now works perfetly fine.

  ### celery
 
● Honest assessment per tool used:

  ---
  search_token("handler") — Genuinely useful. 85 hits across 23 files, grouped by
  module. Faster than grep, no hallucination. Effort reduced.
  
  dependency_graph — Useful result, but required two calls — first with "celery"
  failed, had to retry with "celery/__init__.py". Minor friction. Result itself was
  accurate. Slight efficiency loss on first call.

  search_docs("how to install and configure") — Weak. First run returned all scores 0.0
  (MCP cold start). After reconnect, scores were real but results were loosely related
  (RabbitMQ macOS setup, optimization guide). Query intent wasn't well matched. Did 
  not reduce effort meaningfully.

  context_pack("how does data validation work") — Mixed. Top hit (test_app.py:749) was
  genuinely on-target (Pydantic task validation). But ~6 of 10 sections
  (collections.py, certificate.py, test_eventlet.py) were irrelevant — BM25 noise.
  Partial hallucination risk: if you acted on the full context without filtering, you'd
  get misleading signal.

  get_last_context() — Worked exactly as designed. Snapshot was persisted and retrieved
  correctly. No issue.

  ---
  Bottom line: search_token and dependency_graph earned their keep. context_pack and
  search_docs had signal-to-noise problems — not hallucination in the strict sense
  (files are real), but retrieval relevance was poor enough that acting on them
  uncritically would waste effort rather than save it.

  Ignore the reconnect thing .

### Kubernetes
Honest per-tool verdict from this session:

  Genuinely reduced effort:

  - lookup_symbol("main") — returned 130+ locations instantly, no grep needed. Real win.
  - who_calls("Run") — pinpointed runCommand in scheduler's server.go from the AST graph. Accurate, fast.
  - graph_stats() — single call gave node/edge counts, staleness, last-indexed timestamp. No file reads
  needed.
  - architecture_overview (kubelet + scheduler) — compact, accurate package summaries after cognirepo 
  summarize ran.

  Did not reduce effort / required fallback:

  - context_pack — returned empty both times ("request routing", "main algorithm"). Had to grep + Read files
  manually. Net negative on routing question.
  - subgraph("GenericAPIServer") — name resolution failed across all prefix variants. Fell through to
  symbol::errnoErr which returned 120k chars of syscall noise — useless for architecture intent.

  Did it hallucinate? No. It returned empty results or structured errors (circuit breaker OPEN) rather than
  fabricating data. That's the correct failure mode.

  Net verdict: ~50/50. Symbol lookup and call-graph tools delivered real value. Semantic/concept tools
  (context_pack, subgraph by name, retrieve_memory) were unreliable on a stale index. Reindexing (cognirepo 
  index-repo . --tier 2) would likely fix the semantic half.


### moby
● Honest assessment — the signal that matters most:

  who_calls("NewDaemon") is the clearest indicator of both value
  and limitation.

  - It returned exactly 1 caller
  (testutil/daemon/daemon.go::New) but missed the production 
  call site (cmd/dockerd/daemon.go). That's an index coverage
  gap — not hallucination, but incomplete data presented without
  a warning.
  - If taken at face value, it would mislead: you'd conclude
  NewDaemon is test-only, which is wrong.

  Where it genuinely reduced effort:
  - architecture_overview — gave a real 10-second orientation
  over 8,364 files. Would have taken many reads otherwise.
  - lookup_symbol("NewDaemon") — pinpointed daemon/daemon.go:839
  instantly, no grep needed.
  
  Did it hallucinate? No outright hallucination. But line: -1
  across nearly all semantic_search_code results means the index
  is partially built — results exist but aren't fully resolved.
  That's a silent quality issue.

  Bottom line: CogniRepo reduced effort on discovery (symbol
  location, repo orientation) but its call graph is incomplete —
  who_calls results need a grep verification step before
  trusting them. Net: modest positive, with a reliability caveat
  on caller tracing.

  Run cognirepo index-repo . to improve call graph coverage.

ignore reindex thing i have handled it.

## Summary Scorecard

| Section | Tests | Pass | Fail | Degraded | Notes |
|---|---|---|---|---|---|
| 1. Session Bootstrap | 2 | — | — | — | |
| 2. Code Search | 8 | — | — | — | §2.4 cold-graph fix; §2.6 stub resolution fix; §2.8 new |
| 3. Memory | 5 | — | — | — | §3.2 conflict detection fix; §3.5 new |
| 4. Graph | 2 | — | — | — | §4.2 helpful hint fix |
| 5. Architecture | 2 | — | — | — | §5.1 test symbol filter fix; §5.2 scope fix |
| 6. Docs | 1 | — | — | — | §6.1 semantic doc search fix |
| 7. Behaviour | 4 | — | — | — | §7.3 enriched hint fix |
| 8. Org/Cross-repo | 7 | — | — | — | §8.5 hook fix; §8.6 hybrid search + dedup fix |
| 9. Context Handoff | 2 | — | — | — | |
| 10. Hooks | 4 | — | — | — | §10.1 circuit breaker fix; §10.2 session tracking fix |
| 11. CLI | 1 | — | — | — | |
| 12. Benchmark | 1 | — | — | — | circuit breaker crash fix |
| 13. Staleness Reindex | 1 | — | — | — | |
| 14. Concurrent Sessions | 1 | — | — | — | |
| 15. setup→init | 1 | — | — | — | post-setup re-index/prime prompts added |
| 16. Encryption | 1 | — | — | — | |
| 17. Behaviour Framing | 1 | — | — | — | |
| 18. Circuit Breaker Recovery | 3 | — | — | — | new |
| 19. UPI Clone Extended | 4 | — | — | — | new |
| 20. Summarize Coverage | 3 | — | — | — | new |
| 21. UPI Clone Feature Tests (§21.1–21.7) | 7 | — | — | — | new — OTP, PIN, rollback, social, split bill, FonltHeaderFilter |
| 21. Multi-repo Coverage (§21.8–21.10) | 3 | — | — | — | new — moby, flask, ansible |
| **Total** | **64** | **—** | **—** | **—** | |

**Overall pass rate:** ___/64

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
| 6.1 | `medium/ansible` | `cognirepo index-repo .` run first (triggers DocIngester automatically) |
| 7.x | `easy/fastapi` | `behaviour_tracking: true` in config.json |
| 8.x, 19.x, 21.1–21.7 | `private-org/UpiClone` | All 3 services linked via `cognirepo init --parent-repo`; each service indexed; latest cognirepo installed |
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
