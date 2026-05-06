# CogniRepo Manual Test Suite

**How to use this doc**
1. Run `cognirepo setup` inside each test repo before testing
2. Use prompts below verbatim — paste them to Claude Code (or any AI using CogniRepo MCP)
3. Paste raw output under each **RESULTS** block
4. Score pass/fail in the **Status** column

Test repos: `../cognirepo_test_repo/easy`, `medium`, `advanced`, `dummy`, `private-org`

---

## 0. Environment Setup

Run these once before any test. Do NOT skip.

```bash
# In cognirepo repo
pip install -e ".[dev,languages]"

# In each test repo (repeat for easy / medium / advanced / dummy)
cd ../cognirepo_test_repo/easy
cognirepo setup          # or: cognirepo init && cognirepo index-repo .
cognirepo doctor
```

**RESULTS — easy setup**
```
[paste doctor output here]
```

**RESULTS — medium setup**
```
[paste here]
```

**RESULTS — advanced setup**
```
[paste here]
```

**RESULTS — organisation setup-priavte**
```
[paste here]
```

---

## 1. Session Bootstrap

### 1.1 Single-call bootstrap (get_agent_bootstrap)

**Repo:** easy | **Tool:** `get_agent_bootstrap`

**Prompt:**
```
Call get_agent_bootstrap() and tell me what the project is about, what the hottest symbols are, and what the index health looks like.
```

**Expected:** Single response with `repo`, `architecture`, `index_health.status = "ok"`, `hot_symbols` list (may be empty on cold start). Should NOT require 4 separate calls.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 1.2 Full 4-call sequence (baseline comparison)

**Repo:** medium | **Tools:** `get_session_brief` → `get_last_context` → `get_user_profile` → `get_error_patterns`

**Prompt:**
```
Run the full session start sequence: get_session_brief(), then get_last_context(), then get_user_profile(), then get_error_patterns(). Summarise what you learned.
```

**Expected:** 4 calls, combined output similar to get_agent_bootstrap. Note token count difference.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 2. Code Search

### 2.1 Symbol lookup — exact match

**Repo:** advanced | **Tool:** `lookup_symbol`

**Prompt:**
```
Look up where the main entry point function is defined. Use lookup_symbol on "main" and tell me the file and line.
```

**Expected:** Returns `{file, line, type}`. Should NOT return empty list.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 2.2 Semantic code search — concept query

**Repo:** advanced | **Tool:** `semantic_search_code`

**Prompt:**
```
Use semantic_search_code to find where authentication or login is handled in this codebase. Top 5 results.
```

**Expected:** Returns list of `{name, file, line, type, score}`. No episodic/memory entries mixed in (type should never be "EP" or "memory").

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 2.3 Token search — word in symbol names

**Repo:** medium | **Tool:** `search_token`

**Prompt:**
```
Use search_token("handler") to find all symbols whose names or docs mention "handler".
```

**Expected:** Returns `{file, line}` list. Fast (< 1s), no embedding needed.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 2.4 context_pack — main workhorse

**Repo:** advanced | **Tool:** `context_pack`

**Prompt:**
```
Use context_pack to answer: "how does the request routing work in this project?" Set max_tokens=3000.
```

**Expected:** Returns `{query, status, token_count, sections, truncated}`. Status must be "ok" or "no_confident_match" — never missing. Sections should contain file snippets, not README noise.

**Status:** [ ] pass  [ ] fail

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

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 2.6 Caller graph

**Repo:** advanced | **Tool:** `who_calls`

**Prompt:**
```
Use who_calls() on the most important function in this repo (pick one from lookup_symbol results). Tell me all its local callers.
```

**Expected:** Returns `{local_callers: [...], cross_repo_callers: [], truncated: false}`. Shape must always be this dict, never a plain list.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 2.7 Dependency graph

**Repo:** medium | **Tool:** `dependency_graph`

**Prompt:**
```
Use dependency_graph on the main module of this project (direction="both", depth=2). What does it import and what imports it?
```

**Expected:** Returns `{imports: [...], imported_by: [...], ...}`. No crash.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 3. Memory

### 3.1 Store and retrieve — round trip

**Repo:** easy | **Tools:** `store_memory` → `retrieve_memory`

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

**Repo:** easy | **Tools:** `store_memory` → `supersede_learning`

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

**Repo:** easy | **Tools:** `log_episode` → `episodic_search`

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

**Repo:** medium | **Tools:** `record_decision` → `episodic_search`

**Prompt:**
```
Record this architectural decision: summary="Use async queue for email sending", rationale="Sync email causes 2s request latency". Then search episodes for "email queue decision".
```

**Expected:** `record_decision` returns `{stored: true, ...}`. `episodic_search` finds it.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 4. Graph

### 4.1 Graph stats

**Repo:** advanced | **Tool:** `graph_stats`

**Prompt:**
```
Call graph_stats() and tell me: how many nodes and edges are in the knowledge graph? Is it healthy?
```

**Expected:** Returns node/edge counts > 0 after indexing. Not empty.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 4.2 Subgraph around a symbol

**Repo:** advanced | **Tool:** `subgraph`

**Prompt:**
```
Use subgraph() around the most important class in this project (depth=2). List the top 5 nodes you find.
```

**Expected:** Returns `{nodes: [...], edges: [...]}` with actual content. Not empty.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 5. Architecture Overview

### 5.1 Repo-level summary

**Repo:** advanced | **Tool:** `architecture_overview`

**Prompt:**
```
Call architecture_overview(scope="root"). What is this project's purpose and what are its key classes/functions?
```

**Note:** Run `cognirepo summarize` in the repo first if this returns "Summaries not found".

**Expected:** Returns a human-readable string with repo name, file count, key classes/functions.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 5.2 Directory-level summary

**Repo:** advanced | **Tool:** `architecture_overview`

**Prompt:**
```
Call architecture_overview on the main source directory (e.g. "src" or the top-level package). What's in it?
```

**Expected:** Returns directory summary string. Not "No summary found".

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 6. Documentation Search

### 6.1 Semantic doc search

**Repo:** medium | **Tool:** `search_docs`

**Prompt:**
```
Use search_docs("how to install and configure") to find relevant documentation. What do the top 2 results say?
```

**Expected:** Returns list of `{score, snippet/text, source}`. Fails gracefully if no docs indexed (empty list, no crash).

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 7. Behaviour Tracking (requires opt-in)

**Setup:** Run `cognirepo init` and answer YES to "Enable user behaviour profiling?"

### 7.1 Profile builds from queries

**Repo:** easy (with behaviour=true) | **Tools:** multiple calls → `get_user_profile`

**Prompt:**
```
Make 5 different code queries using context_pack and semantic_search_code. Then call get_user_profile(). What does my interaction style look like?
```

**Expected:** `get_user_profile()` returns `{interaction_style: {preferred_depth, terminology, ...}, framing_hints: "..."}`. Not `{behaviour_tracking: "disabled"}`.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 7.2 User preference recording

**Repo:** easy (with behaviour=true) | **Tool:** `record_user_preference` → `get_user_profile`

**Prompt:**
```
Record my preference: key="response_style", value="always show code before explanation". Then call get_user_profile() to confirm it was stored under explicit_preferences.
```

**Expected:** `record_user_preference` returns `{recorded: true}`. Profile shows it under `explicit_preferences`.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 7.3 Error pattern recording

**Repo:** any | **Tools:** `record_error` → `get_error_patterns`

**Prompt:**
```
Record this error: type="ImportError", message="cannot import fastembed — run pip install fastembed". Then call get_error_patterns(). Is the error listed with a prevention hint?
```

**Expected:** `get_error_patterns()` returns list with the recorded error, `count >= 1`, and a `prevention_hint`.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 7.4 Behaviour tracking disabled by default

**Repo:** dummy (fresh init with behaviour=false) | **Tool:** `get_user_profile`

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

### 8.1 Link repos and org search

**Repos:** easy + medium | **Tools:** `link_repos` → `org_wide_search`

**Prompt:**
```
Link the easy and medium repos together: link_repos(src="/path/to/easy", dst="/path/to/medium", edge_kind="IMPORTS"). Then use org_wide_search("authentication") to search both repos at once.
```

**Expected:** `link_repos` returns success dict. `org_wide_search` returns results from both repos (or gracefully empty if no auth code exists).

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 8.2 Org dependencies

**Repos:** linked easy + medium | **Tool:** `org_dependencies`

**Prompt:**
```
Call org_dependencies(). What repos are registered? What are the edges between them?
```

**Expected:** Returns dict with keys: `current_repo`, `current_repo_name`, `organization`,
`direct_dependencies`, `direct_dependents`, `transitive_dependencies`, `transitive_dependents`.
No `graph` blob or flat `repos`/`edges` keys (removed in v1.1.0 as a bloat reduction).

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 8.3 Cross-repo search scoped to project

**Repos:** linked | **Tool:** `cross_repo_search`

**Prompt:**
```
Use cross_repo_search("database connection", scope="project") to find relevant code across all linked repos.
```

**Expected:** Returns `{results: [...], repos_searched: [...]}`. No crash if no results.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 8.4 Org search fallback (deprecated path)

**Tool:** `org_search`

**Prompt:**
```
Use org_search("config loading") as a fallback search. Does it still work even though it's marked deprecated?
```

**Expected:** Returns results (may be empty). Does NOT crash. Behaves as fallback.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 8.5 Private org structure

**Repo:** private-org | **Tool:** `list_org_context`

**Prompt:**
```
Init cognirepo in the private-org repo with --parent-repo pointing to advanced. Then call list_org_context(). What repos and relationships are visible?
```

**Expected:** Returns org context with the parent-child relationship. Child repos listed.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 9. Context Handoff (Cross-agent)

### 9.1 context_pack writes snapshot

**Repo:** medium | **Tool:** `context_pack` → `get_last_context`

**Prompt:**
```
Use context_pack("how does data validation work") then immediately call get_last_context(). Does it show the query you just ran?
```

**Expected:** `get_last_context` returns `{query: "how does data validation work", sections: [...], agent: "claude", ...}`. Status NOT "no_context".

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 9.2 Bootstrap picks up last context

**Repo:** medium (after 9.1) | **Tool:** `get_agent_bootstrap`

**Prompt:**
```
In a fresh session, call get_agent_bootstrap(). Does last_focus show the query from the previous session?
```

**Expected:** `last_focus.query` = "how does data validation work" from previous session. Cross-agent handoff working.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 10. Hooks & Integration

### 10.1 Auto-store after context_pack

**Repo:** advanced | Internal hook test

**Prompt:**
```
Call context_pack("explain the main algorithm"). Then call retrieve_memory("main algorithm"). Does the memory store have anything from the context_pack result?
```

**Expected:** retrieve_memory returns at least one result from the context_pack output (auto-store hook fired). May not match exactly — similarity search.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 10.2 Session history

**Repo:** any | **Tool:** `get_session_history`

**Prompt:**
```
Call get_session_history(limit=5). What were the last 5 sessions?
```

**Expected:** Returns list of `{session_id, created_at, message_count, last_exchange}`. Empty list is OK on fresh repo.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

### 10.3 Explain change (git-aware)

**Repo:** advanced | **Tool:** `explain_change`

**Prompt:**
```
Use explain_change on "README.md" since="30d". What changed and why?
```

**Expected:** Returns `{target, commits: [...], explanation: "..."}`. No crash if no commits. Graceful empty if no history.

**Status:** [ ] pass  [ ] fail

**RESULTS**
```
[paste here]
```

---

## 11. CLI Health Check

Run locally, not via AI prompts:

```bash
# In each test repo after setup:
cognirepo doctor
cognirepo doctor --verbose
```

**Expected:** All checks green (✓) except optional language parsers. No red ✗ for core checks. Tool count shows 32/32.

**RESULTS — easy**
```
[paste here]
```

**RESULTS — advanced**
```
[paste here]
```

---

## 12. Token Reduction Benchmark

```bash
cd ../cognirepo_test_repo/advanced
cognirepo benchmark
```

**Expected:** Token reduction ratio > 3x (CogniRepo context vs raw file reads). Baseline established.

**RESULTS**
```
[paste here]
```

---

## Summary Scorecard

| Section | Tests | Pass | Fail | Notes |
|---|---|---|---|---|
| 1. Session Bootstrap | 2 | | | |
| 2. Code Search | 7 | | | |
| 3. Memory | 4 | | | |
| 4. Graph | 2 | | | |
| 5. Architecture | 2 | | | |
| 6. Docs | 1 | | | |
| 7. Behaviour | 4 | | | |
| 8. Org/Cross-repo | 5 | | | |
| 9. Context Handoff | 2 | | | |
| 10. Hooks | 3 | | | |
| 11. CLI | 1 | | | |
| 12. Benchmark | 1 | | | |
| **Total** | **34** | | | |

**Overall pass rate:** ___/34

**Readiness verdict:**
- 32–34 pass → Ship ✓
- 28–31 pass → Fix failing before ship
- < 28 pass → Review Phase 1–4 fixes

---

## Known Pre-conditions

| Test | Requires |
|---|---|
| 1.1–1.2 | `cognirepo index-repo .` run first |
| 5.1–5.2 | `cognirepo summarize` run first |
| 7.x | `behaviour_tracking: true` in config.json |
| 8.x | At least 2 repos linked via `link_repos` |
| 9.x | `autosave_context: true` in config.json (default) |
| 12 | Populated index |
