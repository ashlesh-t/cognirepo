# Contributing to CogniRepo

Thank you for contributing! This guide covers dev setup, adding languages, adding tools, and the PR checklist.

---

## Dev Setup

```bash
# Clone the repo
git clone https://github.com/ashlesh-t/cognirepo
cd cognirepo

# Option A — pipx (recommended: global binary, isolated venv, no PEP 668 issues)
pipx install -e ".[dev,security,languages]"

# Option B — local venv
python -m venv venv && source venv/bin/activate
pip install -e ".[dev,security,languages]"

# Initialize the project
cognirepo init

# Run tests
pytest tests/ -v --tb=short

# Lint
pylint $(git ls-files '*.py' | grep -v '_pb2') --disable=C,R,import-error --fail-under=8.0
```

> **Arch Linux / Debian 12+ / Ubuntu 24.04+:** Do not `pip install` into system Python (PEP 668).
> Use pipx (Option A) or activate a venv first (Option B).

---

## How to Add a New MCP Tool

MCP tools are implemented in `interface/tools/` and registered in `interface/server/mcp_server.py`.

### 1. Implement in `interface/tools/`

Create or extend a file in `interface/tools/`. Each tool is a plain Python function:

```python
# interface/tools/my_tools.py
def my_new_tool(query: str, top_k: int = 5) -> list[dict]:
    """
    Brief description of what this tool does.

    Args:
        query: Natural language query.
        top_k: Number of results.

    Returns:
        List of result dicts.
    """
    # implement here — use FAISS, graph, or episodic as needed
    ...
```

**Rules:**
- All storage access goes through `interface/tools/` — never call FAISS or the graph directly from adapters.
- Tools must not call each other (keep them composable at the caller level).
- Tools must be stateless across calls (no module-level mutable state).

### 2. Register in `interface/server/mcp_server.py`

```python
from interface.tools.my_tools import my_new_tool

@server.call_tool()
async def handle_my_new_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "my_new_tool":
        result = my_new_tool(**arguments)
        return [TextContent(type="text", text=json.dumps(result))]
```

Also add the tool definition to `@server.list_tools()`.

### 3. Register in `interface/adapters/openai_spec.py`

Add a JSON schema entry for the tool so it appears in the OpenAI-compatible spec.

### 4. Write tests

```python
# tests/test_my_tools.py
def test_my_new_tool_returns_list():
    from interface.tools.my_tools import my_new_tool
    result = my_new_tool("test query")
    assert isinstance(result, list)
```

### 5. Document in `docs/MCP_TOOLS.md`

Add a section with: signature, description, example input, example output.

---

## How to Add a New Language

Languages are indexed via tree-sitter grammars in `language_grammars/`.

### 1. Install the grammar package

```bash
pip install tree-sitter-<language>
# e.g. pip install tree-sitter-kotlin
```

### 2. Create `language_grammars/<language>.py`

```python
# language_grammars/kotlin.py
from tree_sitter import Language
import tree_sitter_kotlin

KOTLIN_LANGUAGE = Language(tree_sitter_kotlin.language())
```

### 3. Register in `intelligence/indexer/ast_indexer.py`

Add to the `LANGUAGE_MAP` dict:
```python
LANGUAGE_MAP = {
    ...
    ".kt": ("kotlin", _load_kotlin),
    ".kts": ("kotlin", _load_kotlin),
}
```

Add a loader function:
```python
def _load_kotlin():
    from language_grammars.kotlin import KOTLIN_LANGUAGE  # noqa: F401
    return KOTLIN_LANGUAGE
```

### 4. Add extraction logic

In `intelligence/indexer/ast_indexer.py`, add a `_extract_<language>_symbols()` function that uses tree-sitter queries to extract functions, classes, and variables.

### 5. Add to `LANGUAGE_DISPLAY` in `interface/cli/main.py`

```python
LANGUAGE_DISPLAY = {
    ...
    "kotlin": ("tree-sitter-kotlin", "pip install tree-sitter-kotlin"),
}
```

### 6. Write tests

```python
# tests/test_indexer_kotlin.py
def test_kotlin_function_extracted(tmp_path):
    ...
```

---

## How to Add a New CLI Command

### 1. Add the subparser in `interface/cli/main.py`

```python
p_mycommand = sub.add_parser("mycommand", help="What it does")
p_mycommand.add_argument("--option", default="default", help="...")
```

### 2. Add the handler in `main()`

```python
if args.command == "mycommand":
    from cli.mycommand import run_mycommand
    run_mycommand(args.option)
    return
```

### 3. Document in `docs/CLI_REFERENCE.md`

---

## How to Write a Store File (atomic writes)

Several processes (watcher, one `serve` per agent, the CLI) share `.cognirepo/`. A bare
`open(path, "w")` truncates the live file first, so a concurrent reader or a crash sees an empty
or half-written store — and code that treats "unreadable" as "corrupt" then acts on it
(COGNIREPO-134/#135). Never write a store in place; use `core/config/atomic.py`:

| Need | Call |
|------|------|
| bytes / text (encrypt *before* calling) | `atomic_write(path, data)` |
| JSON | `atomic_json_dump(path, obj, indent=2)` |
| writer takes a file object (`np.save`, pickle) | `atomic_write_with(path, lambda f: ..., binary=True)` |
| writer takes a *filename* (`faiss.write_index`) | `with atomic_path(path) as tmp: faiss.write_index(idx, tmp)` |

The helper writes a unique scratch file in the same directory, fsyncs, `os.replace`s it over the
target and fsyncs the directory; on any error the old file is untouched. It keeps an existing file's
mode (new files get 0644) and creates missing parent directories. It does **not** lock — a
read-modify-write cycle still needs `core.config.lock.store_lock()` (#136).

`tests/test_atomic_writes.py` has an AST lint that fails on any new `open(..., "w"/"a"/"x")`,
`write_text`, `write_bytes`, `faiss.write_index` or `np.save` outside the helper. Genuine exceptions
(append-only logs, files owned by other tools) go in its `_ALLOWED` table with a reason.

## How to Read a Store File (never mutate from a reader)

A read failure is not proof of corruption: it can be a concurrent writer, or ciphertext you simply
cannot decrypt (no keyring). Acting on that belief — renaming the file, sweeping scratch files, or
returning `[]` that the next write persists — destroys good data (COGNIREPO-135). Use
`core/config/safe_read.py`:

| Situation | Rule |
|-----------|------|
| any reader | `read_retry(path, load)` (short backoff). It raises `StoreUnreadableError`; it **never** renames, deletes or writes. Serve an empty value *in memory* if you must, but never persist it. |
| ciphertext that fails to decrypt (`looks_encrypted(raw)`) | `StoreUnreadableError(..., locked=True)` — never quarantined, never overwritten. |
| a writer meets an unreadable store | refuse to save (raise), or `quarantine_if_stably_corrupt(path, is_readable)` under `store_lock()`: moves it to `<file>.corrupt-<ts>` only if it stayed unreadable **and unchanged** across two checks; bytes are kept, nothing is deleted. |
| scratch-file cleanup | only under `store_lock`, only files older than 10 minutes. |

`tests/test_side_effect_free_readers.py` shows the pattern for episodic, learnings, the vector store
and the AST index.

## How to Read-Modify-Write a Shared Store (locking)

Load → change → save is only safe if nobody else saves in between. Without the lock, two
processes both load N events, both mint `e_N`, and the later save drops the other's event
(COGNIREPO-136). Rules:

1. Do the **whole cycle** inside `core.config.lock.store_lock()` and **reload inside it** — never
   mutate a snapshot loaded before the lock. Allocate ids inside the lock.
2. `store_lock()` is **re-entrant for the same thread** (a nested `with store_lock():` only bumps a
   depth counter), so helpers may lock defensively. Other threads/processes still exclude each other.
3. Stores that live outside the repo (global learnings in `~/.cognirepo`) lock their own file:
   `store_lock(lock_path=...)`. Never nest two *different* locks; if you must, keep the order
   graph → ast → vector → episodic → behaviour.
4. Hold the lock only for the cycle — no network, subprocess or embedding calls inside it.
5. For in-memory structures that outlive one call (`LocalVectorDB`): remember unsaved changes and,
   on save, merge them into whatever is on disk (`_sync_locked`) instead of overwriting it.

`tests/test_locked_rmw.py` has the multi-process stress pattern (`_run_workers`) to copy.

## PR Checklist

Before submitting a pull request:

- [ ] Tests pass: `pytest tests/ -v --tb=short`
- [ ] Lint passes: `pylint ... --fail-under=8.0`
- [ ] New code has SPDX license headers
- [ ] New tools are documented in `docs/MCP_TOOLS.md`
- [ ] New CLI commands are documented in `docs/CLI_REFERENCE.md`
- [ ] New config fields are documented in `docs/CONFIGURATION.md`
- [ ] Proto files regenerated if `.proto` changed: `make proto`
- [ ] No new HIGH severity Bandit findings: `bandit -r . --severity-level high`
- [ ] No secrets committed (TruffleHog check passes)

---

## GitHub Secrets for CI

| Secret | Description |
|--------|-------------|

Set these in: **GitHub repo → Settings → Secrets and variables → Actions**.

---

## License

By contributing, you agree your contributions are licensed under **MIT**.
See [LICENSE](../LICENSE).
