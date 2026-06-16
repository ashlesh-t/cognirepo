# Contributing to CogniRepo

> **This file is a redirect stub.** The canonical contributor documentation lives in two places:
>
> - **[Root CONTRIBUTING.md](../CONTRIBUTING.md)** — dev setup, PR checklist, commit format, the core `tools/` architecture rule
> - **[docs/DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)** — step-by-step walkthroughs: adding an MCP tool, adding a language, adding a model adapter, adding a CLI command

## Why two files?

The root `CONTRIBUTING.md` is the short version (setup + rules). `DEVELOPER_GUIDE.md` is the deep reference for extending CogniRepo. Both are kept in sync — if they disagree, the root file wins on process questions and `DEVELOPER_GUIDE.md` wins on implementation details.

---

> **Important — correct MCP tool path:** New tools go in `tools/your_tool.py` and are registered via `@mcp.tool()` in `server/mcp_server.py`. **Not** `mcp/tools/` or `mcp/registry.py` — those paths do not exist. See [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) for the full walkthrough.
