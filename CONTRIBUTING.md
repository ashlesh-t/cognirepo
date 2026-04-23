# Contributing to CogniRepo

Thank you for contributing! This guide covers the basics to get you started. For detailed technical guides, see the [Developer Guide](docs/DEVELOPER_GUIDE.md).

---

## Dev Setup

```bash
git clone https://github.com/ashlesh-t/cognirepo
cd cognirepo
python -m venv venv && source venv/bin/activate
pip install -e ".[dev,languages,security]"
pre-commit install
pytest tests/ -v   # should all be green
```

---

## Running Tests

```bash
pytest tests/                                         # all tests
pytest tests/test_memory.py -v                        # one file
pytest --cov=. --cov-report=term-missing              # with coverage
```

Tests use `pytest` with fixtures in `tests/conftest.py`. The `isolated_cognirepo` fixture
creates a temporary `.cognirepo/` directory and injects test secrets via environment variables,
so tests never touch your real config or OS keychain.

---

## The Core Rule: `tools/` is the Entry Point

**All paths to the memory engine MUST go through `tools/`.**

If you are adding logic in `server/mcp_server.py`, `api/routes/`, or `rpc/server.py` — stop. Move it to a function in `tools/`, and call that function from the adapter. MCP, REST, and gRPC are thin transport wrappers only.

---

## Technical Guides

For step-by-step instructions on extending CogniRepo, refer to the [Developer Guide](docs/DEVELOPER_GUIDE.md):

*   [How to Add a New MCP Tool](docs/DEVELOPER_GUIDE.md#how-to-add-a-new-mcp-tool)
*   [How to Add a New Language](docs/DEVELOPER_GUIDE.md#how-to-add-a-new-language)
*   [How to Add a New Model Adapter](docs/DEVELOPER_GUIDE.md#adding-a-model-adapter)
*   [How to Add a New CLI Command](docs/DEVELOPER_GUIDE.md#how-to-add-a-new-cli-command)

---

## PR Checklist

Before opening a PR to the `development` branch, confirm:

- [ ] `pytest tests/` passes with no new failures.
- [ ] `bandit -r . -ll --exclude venv,tests` reports no new HIGH or CRITICAL findings.
- [ ] Architecture rule followed — no logic added directly to adapters.
- [ ] Documentation updated in `docs/` if any command, flag, or endpoint changed.
- [ ] `CHANGELOG.md` `[Unreleased]` section updated.
- [ ] SPDX header present in any new `.py` files.

---

## Commit Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation only
- `test:` adding or fixing tests
- `chore:` build, CI, dependencies
- `refactor:` code change that is not a fix or feature

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `COGNIREPO_JWT_SECRET` | Signs JWT tokens for MCP auth. Set a long random string. Never commit it. |

---

## License

By contributing, you agree your contributions are licensed under **MIT**. See [LICENSE](LICENSE).
