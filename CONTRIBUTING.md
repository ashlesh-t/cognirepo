# Contributing to CogniRepo

Thank you for contributing. This guide covers everything you need in 5 minutes.

---

## Dev setup

```bash
git clone https://github.com/ashlesh-t/cognirepo
cd cognirepo
python -m venv venv && source venv/bin/activate
pip install -e ".[dev,languages]"
pre-commit install
pytest tests/ -v   # should all be green
```

---

## Running tests

```bash
pytest tests/                                         # all tests
pytest tests/test_memory.py -v                        # one file
pytest --cov=. --cov-report=term-missing              # with coverage
```

Tests use `pytest` with fixtures in `tests/conftest.py`. The `isolated_cognirepo` fixture
creates a temporary `.cognirepo/` directory and injects test secrets via environment variables,
so tests never touch your real config or OS keychain.

---

## The one rule

**All paths to the memory engine go through `tools/`.** This is non-negotiable.

If you are adding logic in `server/mcp_server.py`, `api/routes/`, or `rpc/server.py` —
stop, move it to a function in `tools/`, and call that function from the adapter.
MCP, REST, and gRPC are thin wrappers. Nothing else.

PRs that put logic directly in adapters will not be merged.

---

## Adding a model adapter

1. Create `orchestrator/model_adapters/<name>_adapter.py`
2. Implement:
   - `call(prompt, system, tools, max_tokens) → ModelResponse`
   - `stream_call(prompt, system, tools) → Iterator[str]`
3. Add the provider to the fallback chain in `orchestrator/router.py`
   and document it in the provider table in `USAGE.md`

---

## Adding a CLI tool

1. Create `tools/<name>.py` — wraps existing `memory/` or `graph/` methods,
   no direct FAISS calls
2. Add `@mcp.tool()` decorated function in `server/mcp_server.py`
3. Add REST route in `api/routes/` — run `cognirepo export-spec` to regenerate
   `server/manifest.json`

---

## Adding language support

See [LANGUAGES.md](LANGUAGES.md) — 5 steps, ~30 minutes.

---

## PR checklist

Note: always make a PR to 'development' branch


Before opening a PR, confirm:

- [ ] `pytest tests/` passes with no new failures
- [ ] `bandit -r . -ll --exclude venv,tests` reports no new HIGH or CRITICAL findings
- [ ] Architecture rule followed — no logic added directly to adapters
- [ ] `USAGE.md` updated if any command, flag, or endpoint changed
- [ ] `CHANGELOG.md` `[Unreleased]` section updated with your change
- [ ] SPDX header present in any new `.py` files you added

---

## Commit format

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation only
- `test:` adding or fixing tests
- `chore:` build, CI, dependencies
- `refactor:` code change that is not a fix or feature

---

## License

By contributing, you agree that your contributions are licensed under
**MIT**. See [LICENSE](LICENSE).

---

## Note for maintainers

The following GitHub Actions secrets must be set in **Settings → Secrets → Actions**:

| Secret | Purpose |
|---|---|
| `SNYK_TOKEN` | Snyk dependency vulnerability scanning |
| `COGNIREPO_JWT_SECRET` | JWT signing key for the REST API (used in CI adapter tests) |
| `COGNIREPO_PASSWORD_HASH` | Bcrypt hash of the API password (used in CI integration tests) |

Without `SNYK_TOKEN`, the Snyk step will be skipped. Without `COGNIREPO_JWT_SECRET`,
adapter tests that require authentication will be skipped (they are mocked in CI).

To generate a JWT secret locally:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
