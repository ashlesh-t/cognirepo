# Contributing to CogniRepo

## Dev Setup

```bash
git clone https://github.com/ashlesh-t/cognirepo
cd cognirepo
pip install -e ".[dev]"
pre-commit install
```

## Add a New MCP Tool

1. Create handler in `mcp/tools/your_tool.py` implementing `async def run(params) -> dict`.
2. Register it in `mcp/registry.py` under a unique tool name.
3. Add schema entry in `mcp/schemas/your_tool.json`.
4. Write tests in `tests/test_your_tool.py`.
5. Document in `docs/MCP_TOOLS.md`.

## Add a New Language

1. Add a tree-sitter grammar or parser in `indexing/languages/`.
2. Register the file extension → parser mapping in `indexing/language_registry.py`.
3. Add sample fixtures under `tests/fixtures/<language>/`.
4. Update `docs/LANGUAGES.md` with support status.

## Environment Variables

| Variable | Purpose |
|---|---|
| `COGNIREPO_JWT_SECRET` | Signs JWT tokens for MCP auth. Set a long random string. Never commit it. |

## PR Checklist

- [ ] Tests pass: `python -m pytest tests/ -q`
- [ ] SPDX header present in any new `.py` files
- [ ] `docs/` updated if behaviour changes
- [ ] Conventional Commits format used (`feat:`, `fix:`, `docs:`, etc.)
