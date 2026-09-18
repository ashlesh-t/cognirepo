# Contributing to CogniRepo

Thanks for considering a contribution. This is the short version (setup + rules); the deep
reference — step-by-step walkthroughs for adding an MCP tool, a language, a model adapter, or a
CLI command — lives in **[docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)**. If the two ever
disagree, this file wins on process questions and `DEVELOPER_GUIDE.md` wins on implementation
details.

## Quick start

```bash
git clone https://github.com/ashlesh-t/cognirepo
cd cognirepo
pip install -e ".[dev,security,languages]"   # or: pipx install -e ".[dev,security,languages]"
cognirepo init
pytest tests/ -v --tb=short
```

Full dev-setup details (pipx vs venv, PEP 668 notes): `docs/DEVELOPER_GUIDE.md` §Dev Setup.

## The one architecture rule that matters most

New MCP tools go in `interface/tools/your_tool.py` and are registered via `@mcp.tool()` in
`interface/server/mcp_server.py`. **Not** `mcp/tools/` or `mcp/registry.py` — those paths don't
exist. Tools are stateless and never call each other directly; all retrieval routes through
`intelligence/retrieval/hybrid.py`. Full walkthrough: `docs/DEVELOPER_GUIDE.md` §How to Add a
New MCP Tool.

## Looking for a place to start?

Issues labeled [`good first issue`](https://github.com/ashlesh-t/cognirepo/labels/good%20first%20issue)
are scoped for a first contribution — each one names the exact files involved, the acceptance
criteria, and links the relevant `DEVELOPER_GUIDE.md` recipe. Common categories:

- **Adding a language** — `docs/DEVELOPER_GUIDE.md` §How to Add a New Language
- **Adding an MCP tool** — `docs/DEVELOPER_GUIDE.md` §How to Add a New MCP Tool
- **Adding a CLI command** — `docs/DEVELOPER_GUIDE.md` §How to Add a New CLI Command
- **Doc/README accuracy fixes** — no recipe needed, just verify the current state against the
  live code before editing (`grep`/`lookup_symbol` the claim, don't take the issue text on
  faith — code moves)

## Before opening a PR

- [ ] Tests pass: `pytest tests/ -v --tb=short`
- [ ] Lint passes: `pylint ... --fail-under=8.0`
- [ ] New code has SPDX license headers (see any existing file for the exact header)
- [ ] New tools documented in `docs/MCP_TOOLS.md`; new CLI commands in `docs/CLI_REFERENCE.md`;
      new config fields in `docs/CONFIGURATION.md`
- [ ] No new HIGH severity Bandit findings: `bandit -r . --severity-level high`
- [ ] No secrets committed

Full checklist: `docs/DEVELOPER_GUIDE.md` §PR Checklist.

## Commit format

```
<short imperative summary>

<optional body: what/why, notable tradeoffs>
```

## Questions?

Ask in the [Discord](https://discord.com/channels/1488386981917360289/1488387271190380636), or
open a [GitHub issue](https://github.com/ashlesh-t/cognirepo/issues/new/choose).
