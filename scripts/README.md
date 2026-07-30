# scripts/

## cognirepo-mode.sh

Switch CogniRepo between the editable dev tree (`venv/bin/cognirepo`, live source)
and the installed pipx release (`~/.local/bin/cognirepo`, frozen).

Two independent switches — flipping one does not flip the other:

| Switch | Affects | Scope | Takes effect |
|---|---|---|---|
| `dev` / `prod` | `command` in a repo's `.mcp.json` | that repo, persists | after restarting Claude Code |
| `shellenv dev\|prod` | `$PATH` (via a symlinked shim) | current shell only | immediately |

### Commands

```bash
M=~/my_works/cognirepo/scripts/cognirepo-mode.sh

$M dev                              # bind MCP server in cwd's repo to dev build
$M prod                             # bind MCP server in cwd's repo to prod build
$M dev  --repo /path/to/other/repo  # same, targeting a different repo
$M status [--repo PATH]             # show MCP binding + shell binary + versions

eval "$($M shellenv dev)"           # put dev cognirepo on PATH for this shell
eval "$($M shellenv prod)"          # put prod cognirepo on PATH for this shell
```

### Typical use

```bash
# Test the MCP tools (context_pack, lookup_symbol, ...) against 2.0.0
cd ~/my_works/cognirepo_test_repo
~/my_works/cognirepo/scripts/cognirepo-mode.sh dev
# restart Claude Code

# Test the CLI (index-repo, doctor, benchmark, ...) against 2.0.0
eval "$(~/my_works/cognirepo/scripts/cognirepo-mode.sh shellenv dev)"
cognirepo index-repo .
```

### Notes

- `.mcp.json` is gitignored — edits stay local, nothing to commit.
- A repo with no `.mcp.json` has no CogniRepo MCP server; `status`/`dev` will tell you and
  show the command to create one.
- Each `--project-dir` gets its own `.cognirepo/` store. If you flip a repo's version after
  indexing (e.g. dev 2.0.0 → prod 1.1.0), delete and re-index `.cognirepo/` — index formats
  aren't guaranteed compatible across versions.
