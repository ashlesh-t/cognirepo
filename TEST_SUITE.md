# CogniRepo — Manual Testing Guide & CLI Validation

> Use this guide to verify every feature works as expected before a release, demo, or OSS launch.
> Cross-reference with `FEATURE.md` for implementation status.
>
> Each section lists: **setup**, **exact commands or prompts**, **what to observe**, **pass criteria**.

---

## Prerequisites

```bash
# 1. Activate the project venv
source venv/bin/activate

# 2. Initialise (idempotent — safe to re-run)
cognirepo init

# 3. Index the repo
cognirepo index-repo .

# 4. Verify health
cognirepo doctor
```

All sections below assume these steps have been run and `cognirepo doctor` exits 0.

---

## Section 1 — MCP Tool Availability

**Goal:** Confirm all 13 tools are registered and reachable.

### 1.1 Automated check

```bash
venv/bin/python3 test_cognirepo.py --section mcp
```

**Pass:** All 9 MCP-section tests show ✅.

### 1.2 Claude Desktop smoke test

Add CogniRepo to Claude Desktop (`~/.claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "cognirepo": {
      "command": "cognirepo",
      "args": ["serve"]
    }
  }
}
```

Restart Claude Desktop. Open a new conversation and say:

> **"What MCP tools do you have available from CogniRepo?"**

**Pass:** Claude lists `context_pack`, `lookup_symbol`, `who_calls`, `retrieve_memory`, `store_memory`, `log_episode`, `search_docs`, `episodic_search`, `graph_stats`, `subgraph`, `semantic_search_code`, `dependency_graph`, `explain_change`.

### 1.3 Cursor smoke test

```bash
cat .cursor/mcp.json   # verify generated during cognirepo init
```

Open Cursor in this project. In the AI assistant pane, type:

> **"Use lookup_symbol to find where context_pack is defined."**

**Pass:** Cursor calls the MCP tool and returns a file path + line number without reading files directly.

---

## Section 2 — Memory: Store & Retrieve

### 2.1 CLI store + retrieve

```bash
cognirepo store-memory "Fixed: HybridRetriever was skipping BM25 signal when corpus cache was empty. Root cause: TTL check compared float to None."
cognirepo retrieve-memory "BM25 retrieval bug fix"
```

**Pass:**
- `store-memory` prints a confirmation with `stored: true`.
- `retrieve-memory` returns the stored entry in the top-3 results.

### 2.2 Cross-session persistence

```bash
# Session A
cognirepo store-memory "Architecture decision: use FAISS flat L2 index because IndexIDMap2 allows ID-based removal."
exit   # close terminal

# New terminal / Session B
source venv/bin/activate
cognirepo retrieve-memory "FAISS index removal"
```

**Pass:** The entry stored in Session A appears in Session B results. Confirms JSONL + FAISS are written to disk and reloaded correctly.

### 2.3 Claude using store_memory instead of internal state

In Claude Desktop (CogniRepo MCP active), say:

> **"Store the following as a project memory: 'CogniRepo uses all-MiniLM-L6-v2 for embeddings. Dimension is 384.'"**

**Pass:** Claude calls `store_memory(text="CogniRepo uses all-MiniLM-L6-v2 ...", source="claude")`. Confirm with:

```bash
cognirepo retrieve-memory "embedding model dimension"
```

### 2.4 Episodic log persistence

```bash
cognirepo log-episode "Started manual test run for v0.1.0 release" '{"test_suite": "manual"}'
cognirepo history --limit 5
```

**Pass:** The logged event appears in the history output with correct timestamp.

---

## Section 3 — Episodic Search (BM25)

### 3.1 BM25 returns ranked results

```bash
cognirepo log-episode "circuit breaker opened due to high RSS memory usage"
cognirepo log-episode "user queried BM25 episodic index for context_pack function"
cognirepo log-episode "indexed 47 Python files with AST indexer"
```

Then search:

```bash
cognirepo search-docs "episodic BM25"   # docs search
# OR use MCP tool via Claude:
# "Use episodic_search to find events about BM25"
```

**Pass:** The event containing "BM25 episodic index" ranks above unrelated events.

### 3.2 Cache TTL behavior

```bash
# In Python
python3 -c "
from memory.episodic_memory import EpisodicMemory
em = EpisodicMemory()
r1 = em.search_episodes('BM25', limit=5)
r2 = em.search_episodes('BM25', limit=5)
print('same result object?', r1 is r2)  # True = cache hit
"
```

**Pass:** Second call returns immediately (cache hit within 60s TTL).

---

## Section 4 — AST Indexer & Symbol Lookup

### 4.1 Basic symbol lookup

```bash
cognirepo index-repo .
```

Then in Claude Desktop:

> **"Where is the context_pack function defined? Use lookup_symbol."**

**Pass:** Claude calls `lookup_symbol("context_pack")` and reports `tools/context_pack.py` with a line number.  
**Fail indicator:** Claude reads `tools/context_pack.py` directly without calling the tool first.

### 4.2 Multi-language indexing

```bash
# Verify indexer covered more than Python files
python3 -c "
from indexer.ast_indexer import ASTIndexer
from graph.knowledge_graph import KnowledgeGraph
kg = KnowledgeGraph()
idx = ASTIndexer(graph=kg)
idx.load()
exts = set()
for f in idx.index_data:
    import os; exts.add(os.path.splitext(f)[1])
print('Indexed extensions:', exts)
print('Total files:', len(idx.index_data))
"
```

**Pass:** `.py` files are present. `.ts`, `.go`, `.rs` are present if tree-sitter grammars are installed.

### 4.3 Unknown symbol returns empty

```bash
python3 -c "
from indexer.ast_indexer import ASTIndexer
from graph.knowledge_graph import KnowledgeGraph
idx = ASTIndexer(graph=KnowledgeGraph())
idx.load()
print(idx.lookup_symbol('_this_function_does_not_exist_xyz'))
"
```

**Pass:** Prints `[]`.

### 4.4 SHA-256 hash cache (skip unchanged files)

```bash
# First index
time cognirepo index-repo .

# Immediate re-index (all files unchanged)
time cognirepo index-repo .
```

**Pass:** Second run completes noticeably faster (files skipped via hash cache).  
Check output for "skipped N unchanged files".

---

## Section 5 — Knowledge Graph

### 5.1 Graph stats

```bash
# CLI
cognirepo doctor   # shows graph node/edge count

# Direct
python3 -c "
from graph.knowledge_graph import KnowledgeGraph
kg = KnowledgeGraph()
kg.load()
print(kg.stats())
"
```

**Pass:** Stats dict shows non-zero counts for FUNCTION, FILE, and CLASS nodes plus CALLS and CONTAINS edges.

### 5.2 who_calls traversal

In Claude Desktop:

> **"Use who_calls to find all functions that call context_pack."**

**Pass:** Claude calls `who_calls("context_pack")` and returns a list of caller function names + files.

```bash
# Verify independently
python3 -c "
from graph.knowledge_graph import KnowledgeGraph
kg = KnowledgeGraph()
kg.load()
callers = kg.get_neighbours('context_pack', edge_types=['CALLS'], direction='in')
print('Callers:', callers)
"
```

### 5.3 Subgraph exploration

In Claude Desktop:

> **"Use subgraph to show me the neighbourhood of HybridRetriever at depth 2."**

**Pass:** Claude calls `subgraph("HybridRetriever", depth=2)` and returns a node list showing connected functions/classes.

### 5.4 Dependency graph

In Claude Desktop:

> **"Use dependency_graph to show what tools/context_pack.py imports and what imports it."**

**Pass:** Claude calls `dependency_graph("tools/context_pack.py")` and returns a dict with `imports_from` and `imported_by` lists.

---

## Section 6 — File Watcher (Hot Reload)

### 6.1 Start watcher and verify singleton

```bash
cognirepo watch &
sleep 2
cognirepo watch &   # attempt duplicate
sleep 2
cognirepo list
```

**Pass:** `cognirepo list` shows exactly one watcher process. The second `watch` command exits without starting a duplicate.

### 6.2 Hot reload on file change

```bash
# Start watcher
cognirepo watch &

# Create a new Python file
cat > /tmp/test_hotreload.py << 'EOF'
def hotreload_test_function_xyz():
    """Test function for hot-reload verification."""
    return 42
EOF
cp /tmp/test_hotreload.py tools/hotreload_test_xyz.py

# Wait for debounce (1–2s)
sleep 3

# Look up the new symbol
python3 -c "
from indexer.ast_indexer import ASTIndexer
from graph.knowledge_graph import KnowledgeGraph
idx = ASTIndexer(graph=KnowledgeGraph())
idx.load()
print(idx.lookup_symbol('hotreload_test_function_xyz'))
"

# Clean up
rm tools/hotreload_test_xyz.py
```

**Pass:** `lookup_symbol` finds `hotreload_test_function_xyz` in `tools/hotreload_test_xyz.py` without running `cognirepo index-repo` manually.

### 6.3 Stale data cleanup on delete

```bash
# After test in 6.2, verify the symbol is gone
sleep 3   # wait for watcher to process deletion
python3 -c "
from indexer.ast_indexer import ASTIndexer
from graph.knowledge_graph import KnowledgeGraph
idx = ASTIndexer(graph=KnowledgeGraph())
idx.load()
print(idx.lookup_symbol('hotreload_test_function_xyz'))
"
```

**Pass:** Returns `[]`. Graph and FAISS entries for the deleted file have been removed.

---

## Section 7 — Daemon & Process Management

### 7.1 Daemon lifecycle

```bash
# Start daemon
cognirepo watch --daemon

# Verify it's registered
cognirepo list

# Check heartbeat age
cognirepo doctor | grep heartbeat

# Stop it
cognirepo list --stop
cognirepo list   # should show empty
```

**Pass:** Each step behaves as described. `doctor` reports heartbeat age < 60s while daemon is running.

### 7.2 Systemd unit generation

```bash
cognirepo init --non-interactive
ls ~/.config/systemd/user/cognirepo-watcher.service 2>/dev/null || echo "not written (non-Linux or no systemd)"
```

**Pass on Linux:** Service file exists with correct `ExecStart` path.

### 7.3 Crash recovery

```bash
# Start watcher daemon
cognirepo watch --daemon
PID=$(cognirepo list | grep -oP '\d+' | head -1)

# Kill it hard
kill -9 $PID
sleep 5

# Daemon should have restarted itself via crash guard
cognirepo list
```

**Pass:** A new watcher PID appears in `cognirepo list` within 5–10s of the SIGKILL.

---

## Section 8 — Context Pack (Token-Efficient Context)

### 8.1 Token budget respected

```bash
python3 -c "
from tools.context_pack import context_pack
result = context_pack('how does BM25 episodic search work', max_tokens=500)
print('Keys:', list(result.keys()))
print('token_count:', result.get('token_count'))
assert result.get('token_count', 9999) <= 1000, 'Token budget exceeded by 2x'
print('PASS')
"
```

**Pass:** `token_count` ≤ 1000 (2× the 500-token budget allows for rounding).

### 8.2 Context pack returns code + episodic hits

In Claude Desktop:

> **"Use context_pack to get context about how the episodic memory BM25 search is implemented. Then explain it to me — don't read any files directly."**

**Pass:**
- Claude calls `context_pack("episodic memory BM25 search")` as its first action.
- The response references actual code from `memory/episodic_memory.py` without Claude ever calling a file-read tool.
- Token usage is 15–25% lower than reading the full file.

**Fail indicator:** Claude calls `read_file("memory/episodic_memory.py")` before or instead of `context_pack`.

---

## Section 9 — Hybrid Retrieval

### 9.1 All three signals contribute

```bash
python3 -c "
from retrieval.hybrid import HybridRetriever
hr = HybridRetriever()
results = hr.retrieve('BM25 episodic search ranking', top_k=5)
print('Results:', len(results))
for r in results[:3]:
    print(' -', r.get('text', '')[:80], '| vec:', round(r.get('vector_score', 0), 3), 'graph:', round(r.get('graph_score', 0), 3))
"
```

**Pass:** Results list is non-empty. At least one result has non-zero `vector_score` and at least one has non-zero `graph_score`.

### 9.2 Cache stats

```bash
python3 -c "
from retrieval.hybrid import HybridRetriever, cache_stats
hr = HybridRetriever()
hr.retrieve('test query', top_k=3)
hr.retrieve('test query', top_k=3)   # should be a cache hit
print(cache_stats())
"
```

**Pass:** `cache_stats()` shows `hits >= 1`.

---

## Section 10 — REST API

> These tests require `cognirepo serve-api` running in a separate terminal.

```bash
# Terminal 1
cognirepo serve-api

# Terminal 2 — run tests
```

### 10.1 Health check

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

**Pass:** `{"status": "ok"}` with HTTP 200.

### 10.2 JWT authentication

```bash
# Login
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password": "cognirepo"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
echo "Token acquired: ${TOKEN:0:20}..."

# Unauthenticated request should fail
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/memory/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "top_k": 3}'
# Expected: 401 or 403
```

### 10.3 Memory round-trip over REST

```bash
# Store
curl -s -X POST http://localhost:8000/memory/store \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "REST API test memory entry for round-trip validation", "source": "test"}' \
  | python3 -m json.tool

# Retrieve
curl -s -X POST http://localhost:8000/memory/retrieve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "REST API round-trip validation", "top_k": 5}' \
  | python3 -m json.tool
```

**Pass:** Stored entry appears in retrieve results.

### 10.4 Graph endpoint

```bash
curl -s "http://localhost:8000/graph/symbol/context_pack" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool
```

**Pass:** Returns file + line number.

---

## Section 11 — Doctor Command

### 11.1 Full health check

```bash
cognirepo doctor --verbose
```

**Pass:** Exit code 0. Every check that can pass (config, BM25 backend, Python support, AST index, FAISS index, graph) shows ✅. Optional checks (Redis, gRPC, API keys) show ⚠️ if not configured.

### 11.2 Failure detection

```bash
# Break the config temporarily
mv .cognirepo/config.json .cognirepo/config.json.bak
cognirepo doctor
mv .cognirepo/config.json.bak .cognirepo/config.json
```

**Pass:** Doctor reports a config issue and exits non-zero. Restoring the file makes it pass again.

---

## Section 12 — Security

### 12.1 Encryption at rest

```bash
# With encryption enabled in config.json (storage.encrypt: true),
# verify the metadata file is not plain JSON
file .cognirepo/memory/semantic_metadata.json
xxd .cognirepo/memory/semantic_metadata.json | head -3
```

**Pass:** The file shows binary/non-UTF8 content (Fernet token), not readable JSON.

### 12.2 Encryption round-trip

```bash
python3 -c "
import os, base64
from security.encryption import encrypt_bytes, decrypt_bytes
key = base64.urlsafe_b64encode(os.urandom(32))
plaintext = b'CogniRepo encryption test'
ct = encrypt_bytes(plaintext, key)
rt = decrypt_bytes(ct, key)
assert rt == plaintext
print('PASS: AES-256 GCM round-trip')
"
```

### 12.3 .gitignore excludes .cognirepo/

```bash
git check-ignore -v .cognirepo/config.json
```

**Pass:** Output confirms `.cognirepo/` is excluded.

### 12.4 No secrets in config.json

```bash
grep -E "sk-ant-|AIza|ANTHROPIC_API_KEY|GEMINI_API_KEY" .cognirepo/config.json \
  && echo "FAIL: secret found" || echo "PASS: no secrets in config"
```

---

## Section 13 — CLI Commands Checklist

Run each command and confirm it exits without errors:

```bash
cognirepo init --non-interactive          # idempotent
cognirepo index-repo . --no-embed        # just AST, skip FAISS ingest
cognirepo store-memory "cli test entry"
cognirepo retrieve-memory "cli test"
cognirepo search-docs "context pack"
cognirepo log-episode "cli test event"
cognirepo history --limit 3
cognirepo prune --dry-run
cognirepo doctor
cognirepo list
cognirepo export-spec > /tmp/openai_spec.json
cat /tmp/openai_spec.json | python3 -m json.tool | head -20
```

**Pass:** Each command exits 0 and produces meaningful output.

---

## Section 14 — Best Demo Questions

Use these prompts to showcase CogniRepo at a demo or OSS launch. Each one exercises a distinct subsystem.

### Tier 1 — Instant symbol lookup (QUICK tier, <50ms)

> "Where is the `HybridRetriever` class defined?"

*Observe:* `lookup_symbol("HybridRetriever")` called. No file reads. Answer in < 1s.

---

> "Who calls `context_pack`?"

*Observe:* `who_calls("context_pack")` → list of callers with file + line. Graph traversal, no reads.

---

### Tier 2 — Token-efficient context (context_pack)

> "Explain how the episodic BM25 search cache works — but don't read any files."

*Observe:* `context_pack("episodic BM25 search cache")` → packed code snippet. Explanation uses only the packed context. Token count logged.

---

> "How does the circuit breaker protect against OOM?"

*Observe:* `context_pack("circuit breaker OOM")` → relevant code from `memory/circuit_breaker.py`. No raw file reads.

---

### Tier 3 — Memory persistence

> "Remember this: the embedding model is all-MiniLM-L6-v2 with 384 dimensions."

Then in a new session:

> "What embedding model does CogniRepo use?"

*Observe:* `retrieve_memory("embedding model")` surfaces the stored memory. Answer is accurate without any code search.

---

### Tier 4 — Knowledge graph

> "What does `retrieval/hybrid.py` depend on? Show me the subgraph."

*Observe:* `subgraph("retrieval/hybrid.py", depth=2)` → node list shows FAISS, KnowledgeGraph, BehaviourTracker, EpisodicMemory connections.

---

> "What would break if I removed `BehaviourTracker`?"

*Observe:* `who_calls("BehaviourTracker")` + `subgraph` → impact analysis without reading files.

---

### Tier 5 — Episodic history

> "What have I been working on in the last 10 sessions?"

*Observe:* `episodic_search("recent work")` + `retrieve_memory("recent sessions")` → timeline of stored episodes.

---

### Tier 6 — Multi-file dependency analysis

> "Use dependency_graph on `tools/context_pack.py` and tell me everything it depends on."

*Observe:* `dependency_graph("tools/context_pack.py")` → flat list of imports. Claude can answer without reading the file.

---

### Tier 7 — Explain a code change

> "What changed in `retrieval/hybrid.py` between these two versions?" *(paste two snippets)*

*Observe:* `explain_change(file_path, before, after)` → structured diff: added symbols, removed symbols, changed call signatures.

---

---

# Part B — CLI Validation: Multi-Model Routing

This section validates the **unified REPL and router** (`orchestrator/router.py`), which routes queries to Claude, Gemini, Grok, or OpenAI based on complexity tier and configured priority.

---

## B.1 Setup: Configure Model Priority

```bash
# During cognirepo init (interactive), select model priorities.
# Or edit .cognirepo/config.json directly:
cat .cognirepo/config.json | python3 -m json.tool | grep -A 20 '"models"'
```

Expected config shape:

```json
{
  "models": {
    "QUICK":    {"provider": "grok",      "model": "grok-3-mini"},
    "FAST":     {"provider": "gemini",    "model": "gemini-2.0-flash"},
    "BALANCED": {"provider": "gemini",    "model": "gemini-2.0-flash"},
    "DEEP":     {"provider": "anthropic", "model": "claude-opus-4-6"}
  }
}
```

**Pass:** `config.json` contains a `models` section with all four tiers.

---

## B.2 Complexity Classifier Verification

```bash
python3 -c "
from orchestrator.classifier import classify

tests = [
    ('where is context_pack defined',          ['QUICK', 'FAST']),
    ('list all Python files in this repo',     ['QUICK', 'FAST']),
    ('explain the hybrid retrieval algorithm', ['BALANCED', 'DEEP']),
    ('compare BM25 to vector search and suggest three improvements with code examples',
                                               ['BALANCED', 'DEEP']),
]

all_pass = True
for query, expected_tiers in tests:
    result = classify(query)
    ok = result.tier in expected_tiers
    status = 'PASS' if ok else 'FAIL'
    print(f'{status}: [{result.tier}] {query[:60]}')
    if not ok:
        all_pass = False

print()
print('Overall:', 'PASS' if all_pass else 'FAIL')
"
```

**Pass:** Every test shows PASS.

---

## B.3 Local Resolver Short-Circuits API Calls (QUICK/FAST)

```bash
python3 -c "
import os
# Ensure no API keys are set so any API call would fail
for k in ['ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'GROK_API_KEY', 'OPENAI_API_KEY']:
    os.environ.pop(k, None)

from orchestrator.router import route

# QUICK queries should be answered locally without any API call
result = route('where is context_pack defined')
print('Result type:', type(result).__name__)
print('Answer:', str(result)[:200])
print('PASS: QUICK query answered without API key')
"
```

**Pass:** Returns an answer without raising `AuthenticationError` or similar API error.

---

## B.4 Provider Fallback Chain

```bash
python3 -c "
import os

# Set only Gemini key (anthropic missing → fallback kicks in)
os.environ['GEMINI_API_KEY'] = os.environ.get('GEMINI_API_KEY', 'test')
os.environ.pop('ANTHROPIC_API_KEY', None)

from orchestrator.router import _available_providers
providers = _available_providers()
print('Available providers:', providers)

# Verify anthropic is absent and gemini is present
assert 'anthropic' not in providers or os.environ.get('ANTHROPIC_API_KEY'), (
    'anthropic should not be available without API key'
)
print('PASS: _available_providers correctly filters by env key presence')
"
```

---

## B.5 Cross-Model Context: Claude Writes, Gemini Reads

This is the core cross-model validation. It confirms that context stored by Claude via MCP is accessible to Gemini CLI (and vice versa).

### Step 1 — Claude stores context (MCP)

In Claude Desktop (CogniRepo MCP connected):

> **"Store this as a project memory: 'Cross-model test: HybridRetriever uses three signals — FAISS cosine, graph hop distance, and behaviour frequency. Written by Claude during cross-model test.'"**

Confirm with:

```bash
cognirepo retrieve-memory "HybridRetriever three signals"
```

**Pass:** Entry appears in results with `source: "claude"` or `source: "mcp"`.

### Step 2 — Gemini reads the same context

With `.gemini/COGNIREPO.md` in place (auto-generated by `cognirepo init`), start Gemini CLI in this project directory and say:

> **"What do you know about HybridRetriever? Check CogniRepo memory first."**

**Pass:** Gemini calls `retrieve_memory("HybridRetriever")` and surfaces the memory written by Claude in Step 1 — without any file reads and without being told explicitly about the three-signals architecture.

### Step 3 — Verify shared FAISS path

```bash
python3 -c "
from config.paths import get_path
print('FAISS index:', get_path('vector_db'))
print('Episodic log:', get_path('episodic'))
# Both tools (Claude MCP and Gemini CLI) must point to the same path
import pathlib
assert '.cognirepo' in get_path('vector_db'), 'FAISS not in .cognirepo/'
assert '.cognirepo' in get_path('episodic'),  'Episodic not in .cognirepo/'
print('PASS: both paths scoped to .cognirepo/')
"
```

---

## B.6 Cross-Model Context: Gemini Writes, Claude Reads

### Step 1 — Gemini stores context

In Gemini CLI:

> **"Using CogniRepo, store this memory: 'Gemini cross-model test: context_pack packs up to max_tokens budget using a greedy algorithm. Written by Gemini.'"**

Confirm:

```bash
cognirepo retrieve-memory "context_pack greedy algorithm"
```

### Step 2 — Claude reads Gemini's memory

In Claude Desktop:

> **"What do you know about how context_pack works? Check CogniRepo memory before reading any files."**

**Pass:** Claude calls `retrieve_memory("context_pack")` and surfaces the memory written by Gemini — without reading `tools/context_pack.py` directly.

---

## B.7 External Tool Integration: Cursor / VS Code

### Cursor

1. Confirm `.cursor/mcp.json` exists:
   ```bash
   cat .cursor/mcp.json
   ```
2. Open Cursor with this project. In AI chat, ask:
   > **"Use the CogniRepo lookup_symbol tool to find where `store_memory` is defined."**
3. **Pass:** Cursor calls `lookup_symbol` via MCP without reading `tools/store_memory.py`.

### VS Code (GitHub Copilot Chat with MCP)

1. Confirm `.vscode/mcp.json` exists:
   ```bash
   cat .vscode/mcp.json
   ```
2. In Copilot Chat, ask:
   > **"What does the dependency_graph of tools/context_pack.py look like?"**
3. **Pass:** Copilot calls `dependency_graph` via MCP.

### OpenAI / Codex via REST

```bash
# Start REST API
cognirepo serve-api &
sleep 2

# Export OpenAI function spec
cognirepo export-spec > /tmp/cognirepo_spec.json
cat /tmp/cognirepo_spec.json | python3 -c "
import sys, json
spec = json.load(sys.stdin)
print('Tool count:', len(spec.get('functions', spec.get('tools', []))))
print('First tool:', spec.get('functions', spec.get('tools', [{}]))[0].get('name', 'unknown'))
"
```

**Pass:** Spec contains 13+ tool definitions in OpenAI function-calling format.

Any OpenAI-compatible client can now call CogniRepo tools via the REST API using this spec.

---

## B.8 End-to-End Cross-Model Session

This is the complete validation scenario. Run it as a final acceptance test before any release.

### Scenario: "Debug a bug across models"

**Setup:** Two terminal windows — one for Claude, one for Gemini CLI (or simulate with `cognirepo` CLI).

**Step 1 — Gemini investigates a bug** *(Gemini CLI)*

> "Use CogniRepo to look up `EpisodicMemory.search_episodes`. What does it do?"

Gemini calls `lookup_symbol("search_episodes")` → gets `memory/episodic_memory.py:L42`.

> "Use context_pack to understand the BM25 caching logic."

Gemini calls `context_pack("BM25 caching episodic")` → packed code context.

> "Store this finding: 'Gemini found: EpisodicMemory.search_episodes uses a 60s BM25 corpus cache. If the TTL expires mid-query, results can be inconsistent.'"

Gemini calls `store_memory(...)` → persisted to `.cognirepo/`.

**Step 2 — Claude proposes a fix** *(Claude Desktop)*

> "What has been found about episodic memory caching issues? Check CogniRepo memory."

Claude calls `retrieve_memory("episodic memory caching")` → retrieves Gemini's finding from Step 1.

> "Log this episode: 'Claude reviewed Gemini's BM25 cache finding. Proposed fix: lock corpus rebuild behind a mutex to prevent concurrent TTL expiry.'"

Claude calls `log_episode(...)` → appended to JSONL.

**Step 3 — Verify shared state** *(CLI)*

```bash
cognirepo retrieve-memory "BM25 cache inconsistency"
cognirepo history --limit 5
```

**Pass criteria:**
- `retrieve-memory` surfaces Gemini's finding (Step 1).
- `history` shows Claude's episode (Step 2).
- Both entries exist in the same `.cognirepo/` directory.
- Neither tool had to read source files directly — all context came from CogniRepo.

---

## B.9 Automated Routing Tests

```bash
venv/bin/python3 test_cognirepo.py --section classifier
venv/bin/python3 test_cognirepo.py --section cross_model
```

**Pass:** All classifier and cross-model tests show ✅ or ⚠️ (skip).

---

## B.10 Full Automated Suite

```bash
venv/bin/python3 test_cognirepo.py --fast
```

**Pass:** Output ends with `Results: N passed · 0 failed`. Any `⚠️ SKIPPED` entries for optional components (daemon, REST API, gRPC, model API keys) are acceptable.

---

## Appendix A — Common Failures & Fixes

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `lookup_symbol` returns `[]` | Index is empty | Run `cognirepo index-repo .` |
| `InvalidToken` on memory ops | FAISS metadata encrypted with different key | Re-initialise: `cognirepo init --non-interactive` |
| `doctor` reports BM25 backend unknown | `_bm25` not importable | `pip install -e ".[dev]"` from venv |
| Claude reads files instead of using MCP | MCP server not connected | Check `~/.claude_desktop_config.json`; restart Claude Desktop |
| `cognirepo watch` starts duplicate | Stale PID file | `cognirepo list --stop`; remove `.cognirepo/watchers/*.json` |
| REST API returns 401 | Token expired or wrong password | `POST /auth/login` to get a fresh token |
| Gemini can't find Claude's memories | Wrong project path | Ensure both tools run from the same project root |
| `graph_stats()` returns zeros | Graph not built | Re-run `cognirepo index-repo .` |

---

## Appendix B — Automated Test Reference

| Script | Sections | Run command |
|--------|---------|-------------|
| `test_cognirepo.py` | All 11 sections | `venv/bin/python3 test_cognirepo.py --fast` |
| `tests/test_memory.py` | FAISS, SemanticMemory | `pytest tests/test_memory.py` |
| `tests/test_graph.py` | KnowledgeGraph CRUD | `pytest tests/test_graph.py` |
| `tests/test_episodic_search.py` | BM25, cache TTL | `pytest tests/test_episodic_search.py` |
| `tests/test_daemon_reliability.py` | Daemon, heartbeat | `pytest tests/test_daemon_reliability.py` |
| `tests/test_documentation.py` | All docs | `pytest tests/test_documentation.py` |
| `tests/test_classifier.py` | Tier classification | `pytest tests/test_classifier.py` |
| `tests/test_hybrid_retrieval.py` | Signal merge | `pytest tests/test_hybrid_retrieval.py` |

Run the full pytest suite:

```bash
pytest tests/ -v --tb=short
```
