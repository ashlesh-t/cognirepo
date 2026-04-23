# Contributing to CogniRepo

Thank you for contributing! This guide covers dev setup, adding languages, adding tools, and the PR checklist.

---

## Dev Setup

```bash
# Clone and install in editable mode with dev dependencies
git clone https://github.com/ashlesh-t/cognirepo
cd cognirepo
pip install -e ".[dev,security]"

# Initialize the project
cognirepo init --no-index

# Run tests
pytest tests/ -v --tb=short

# Lint
pylint $(git ls-files '*.py' | grep -v '_pb2') --disable=C,R,import-error --fail-under=8.0
```

---

## How to Add a New MCP Tool

MCP tools are implemented in `tools/` and registered in `server/mcp_server.py`.

### 1. Implement in `tools/`

Create or extend a file in `tools/`. Each tool is a plain Python function:

```python
# tools/my_tools.py
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
- All storage access goes through `tools/` — never call FAISS or the graph directly from adapters.
- Tools must not call each other (keep them composable at the caller level).
- Tools must be stateless across calls (no module-level mutable state).

### 2. Register in `server/mcp_server.py`

```python
from tools.my_tools import my_new_tool

@server.call_tool()
async def handle_my_new_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "my_new_tool":
        result = my_new_tool(**arguments)
        return [TextContent(type="text", text=json.dumps(result))]
```

Also add the tool definition to `@server.list_tools()`.

### 3. Register in `adapters/openai_spec.py`

Add a JSON schema entry for the tool so it appears in the OpenAI-compatible spec.

### 4. Write tests

```python
# tests/test_my_tools.py
def test_my_new_tool_returns_list():
    from tools.my_tools import my_new_tool
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

### 3. Register in `indexer/ast_indexer.py`

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

In `indexer/ast_indexer.py`, add a `_extract_<language>_symbols()` function that uses tree-sitter queries to extract functions, classes, and variables.

### 5. Add to `LANGUAGE_DISPLAY` in `cli/main.py`

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

### 1. Add the subparser in `cli/main.py`

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
| `SNYK_TOKEN` | Snyk dependency scanning |
| `COGNIREPO_JWT_SECRET` | JWT signing secret for API tests |
| `COGNIREPO_PASSWORD_HASH` | Bcrypt password hash for API tests |

Set these in: **GitHub repo → Settings → Secrets and variables → Actions**.

---

## License

By contributing, you agree your contributions are licensed under **MIT**.
See [LICENSE](../LICENSE).
