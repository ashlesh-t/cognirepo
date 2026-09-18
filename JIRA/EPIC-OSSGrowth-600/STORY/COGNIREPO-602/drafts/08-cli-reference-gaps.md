TITLE: docs/CLI_REFERENCE.md is missing 13 CLI subcommands

LABELS: good first issue, documentation

BODY:
## Context

`docs/CLI_REFERENCE.md` documents each top-level `cognirepo <command>` under its own `##`
heading. Comparing the real subcommands registered in `interface/cli/main.py` against the doc's
headings, these are missing entirely: `delete`, `episodic-search`, `graph`, `index-progress`,
`list`, `lookup-symbol`, `mcp-setup`, `metrics`, `setup-env`, `subgraph`, `test-connection`,
`verify-index`, `who-calls`.

This has happened before — `CHANGELOG.md`'s [1.1.3] entry lists a very similar batch of missing
commands that were added back then. New commands keep landing without a corresponding doc entry.

## Files involved

- `docs/CLI_REFERENCE.md`
- `interface/cli/main.py` (source of truth for each command's actual arguments — read the
  `add_parser`/`add_argument` calls for each, don't guess)

## What to do

1. For each of the 13 missing commands, find its `add_parser(...)` block in
   `interface/cli/main.py` and its handler in `main()` to see the real arguments/behavior.
2. Add a `## cognirepo <command>` section following the existing doc's format (see `## cognirepo
   doctor` or any other entry for the expected shape: brief description, usage, flags, example).
3. Verify each entry by actually running the command (`cognirepo <command> --help` at minimum).
4. This can be split into smaller PRs (e.g. 3-4 commands each) if you'd rather not do all 13 at
   once — comment on the issue to claim a subset.

## Acceptance criteria

- [ ] All 13 commands have a `## cognirepo <command>` section
- [ ] Each section's flags/behavior match what `--help` and the source actually show
- [ ] No regressions to existing sections

## Recipe

None needed — this is systematic doc-completeness work, model each new section on an existing
one in the same file.
