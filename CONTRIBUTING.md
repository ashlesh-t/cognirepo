# Contributing to CogniRepo

## Adding a new model adapter

Three steps:

**Step 1 — Create `orchestrator/model_adapters/<name>_adapter.py`**

```python
from orchestrator.model_adapters.anthropic_adapter import ModelResponse

def call(
    query: str,
    system_prompt: str,
    tool_manifest: list[dict],
    model_id: str = "your-default-model",
    max_tokens: int = 2048,
) -> ModelResponse:
    # 1. import your SDK
    # 2. convert tool_manifest → SDK tool format (see _manifest_to_* helpers)
    # 3. call the API
    # 4. return ModelResponse(text=..., model=model_id, provider="yourprovider", ...)
    ...
```

**Step 2 — Register in `orchestrator/router.py` `_dispatch()`**

```python
if provider == "yourprovider":
    from orchestrator.model_adapters import your_adapter
    return your_adapter.call(...)
```

**Step 3 — Add to `.cognirepo/config.json` models registry**

```json
"FAST": { "provider": "yourprovider", "model": "your-fast-model" }
```

Or set via environment: export the model in `_load_model_registry()` default dict in `orchestrator/classifier.py`.

---

## Adding a new tool

1. Create `tools/your_tool.py` with a single function matching the signature expected by MCP/REST.
2. Add `@mcp.tool()` decorator in `server/mcp_server.py`.
3. Add a FastAPI route in `api/routes/`.
4. Re-run `cognirepo export-spec` to regenerate `adapters/openai_tools.json`.

---

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

Lint: `pylint $(git ls-files '*.py' | grep -v _pb2 | grep -v venv) --disable=C,R`
