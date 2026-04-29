# CogniRepo Troubleshooting

Run `cognirepo doctor` first — it catches most issues automatically.

---

## Index Problems

### lookup_symbol / semantic_search_code return empty results

**Symptom:** Queries return `[]` even though the function clearly exists in the codebase.

**Cause:** AST index is empty or stale.

**Fix:**
```bash
cognirepo index-repo .
```

Run this whenever you add new files, rename modules, or after a large git pull.

---

### cognirepo doctor shows "AST index — 0 symbols"

**Cause:** Index was never built, or `.cognirepo/index/ast_index.json` is corrupt/empty.

**Fix:**
```bash
cognirepo index-repo .
```

---

### context_pack always returns `status: "no_confident_match"`

**Cause 1:** Index empty — fix above.

**Cause 2:** FAISS vector index empty (symbols indexed but not embedded).

**Fix:**
```bash
cognirepo index-repo .          # rebuilds AST + FAISS
```

Check FAISS state:
```bash
cognirepo doctor                # shows "FAISS index — N vectors"
```
N should be > 0.

---

### architecture_overview returns "Summaries not found"

**Cause:** `summaries.json` not generated yet.

**Fix:**
```bash
cognirepo summarize
```

---

### Index has data but wrong/old symbols (stale index)

**Symptom:** `doctor` shows symbols > 0 but recently added functions aren't found.

**Fix:** Force full reindex:
```bash
cognirepo index-repo . --force
```

---

## Installation Problems

### pip install cognirepo pulls NVIDIA/CUDA packages (~1.5 GB)

**Cause:** Old version (≤ 1.0.0) used `sentence-transformers` which depends on PyTorch + CUDA.

**Fix:** Upgrade to 1.1.0+:
```bash
pip install --upgrade cognirepo
```

Version 1.1.0+ uses `fastembed` (ONNX, ~50 MB, no GPU required).

---

### ModuleNotFoundError: No module named 'fastembed'

**Cause:** Installed into wrong Python environment (system vs venv).

**Diagnosis:**
```bash
which pip
which python
which pytest
```
All three should point to the same environment.

**Fix (venv):**
```bash
source venv/bin/activate
pip install fastembed
```

**Fix (no venv):**
```bash
pip install --upgrade cognirepo
```

---

### ModuleNotFoundError: No module named 'fastembed' during pytest

**Cause:** `ASTIndexer` imports `get_model` at module level — collection fails if fastembed not installed.

**Fix:** Install fastembed in the same environment as pytest:
```bash
pip install fastembed
pytest tests/
```

---

### ImportError: cannot import 'encode' from 'TextEmbedding'

**Cause:** Code using old `sentence-transformers` API (`model.encode(text)`) after migration to fastembed.

**Fix:** Replace all `model.encode(text)` with:
```python
next(iter(model.embed([text])))          # single text → ndarray
np.array(list(model.embed(texts)))       # batch → ndarray shape (N, 384)
```

---

## pytest Failures

### Tests fail with "lookup_symbol missed known symbols"

**Cause:** AST index stale or empty.

**Fix:**
```bash
cognirepo index-repo .
pytest tests/
```

---

### Tests fail with "precision@3 = 0%"

**Cause:** FAISS vector index empty — embeddings not built.

**Fix:**
```bash
cognirepo index-repo .
pytest tests/
```

---

### Tests fail with "StopIteration" in embed calls

**Cause:** Mock for fastembed not returning an iterable. Pattern `MagicMock()` returns a non-iterable on `.embed()`.

**Fix:** Use this mock pattern:
```python
fake_model = MagicMock()
fake_model.embed.side_effect = lambda texts: iter([np.zeros(384, dtype="float32") for _ in texts])
with patch("indexer.ast_indexer.get_model", return_value=fake_model):
    ...
```

---

### 5 tests skip with "AST index empty — run cognirepo index-repo ."

This is expected behaviour on a fresh clone. Not a bug.

**Fix:**
```bash
cognirepo index-repo .
pytest tests/
```

---

## MCP / AI Tool Problems

### Claude / Gemini / Cursor can't see CogniRepo tools

**Cause 1:** MCP not configured for that tool.

**Fix:**
```bash
cognirepo mcp-setup           # re-run MCP setup wizard
```

Or run full setup again:
```bash
cognirepo setup
```

**Cause 2:** Server not running.

**Fix:** CogniRepo uses stdio MCP — no persistent server needed. The AI tool starts it on demand. If it still fails, check the MCP config file:

- Claude Code: `~/.claude/settings.json` → should have a `cognirepo` entry under `mcpServers`
- Gemini CLI: `~/.config/gemini/settings.json`
- Cursor: `.cursor/mcp.json`
- VS Code: `.vscode/mcp.json`

---

### cognirepo doctor shows "MCP tools — N expected tool(s) not registered"

**Cause:** Server module import failed (usually a missing dependency).

**Fix:**
```bash
pip install -e ".[dev]"
cognirepo doctor --verbose
```

---

### get_user_profile returns `{"behaviour_tracking": "disabled"}`

This is correct if you didn't enable behaviour tracking during setup.

**Enable it:**
```bash
# Edit .cognirepo/config.json
{"behaviour_tracking": true}
```

Or re-run setup:
```bash
cognirepo setup
```

---

## Cross-repo / Org Problems

### org_wide_search returns empty

**Cause:** No repos linked yet.

**Fix:**
```bash
# In each repo you want to link:
cognirepo init --parent-repo /path/to/main-repo
```

Or link manually:
```python
# via MCP tool
link_repos("/path/to/repo-a", "/path/to/repo-b", "IMPORTS")
```

---

### get_children() always returns empty list

**Fixed in v1.1.0.** Upgrade:
```bash
pip install --upgrade cognirepo
```

---

## General Fixes

### Full reset (nuclear option)

Wipes all CogniRepo state and starts fresh:
```bash
rm -rf .cognirepo/
cognirepo setup
```

### Partial reset (index only)

Keeps memory and graph, rebuilds index:
```bash
rm -rf .cognirepo/index/
cognirepo index-repo .
```

### Check everything

```bash
cognirepo doctor --verbose
```

All lines should be ✓. Warnings (⚠) on optional API keys and language parsers are fine.
