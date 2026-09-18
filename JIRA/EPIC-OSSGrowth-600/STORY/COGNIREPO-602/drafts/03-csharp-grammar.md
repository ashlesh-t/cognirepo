TITLE: Add C# language support (tree-sitter grammar mapping)

LABELS: good first issue, enhancement

BODY:
## Context

Same gap as Ruby/PHP/Swift (see README.md Longer-term section): C#'s tree-sitter grammar exists
but isn't wired into CogniRepo's indexer. Note: `ast_indexer.py`'s `_TS_FUNCTION_TYPES` already
includes `method_declaration` labeled "Java, C#" and `_TS_CLASS_TYPES` already includes
`class_declaration`/`interface_declaration` — the node-type mappings may already be correct;
this issue is primarily about wiring the grammar itself.

## Files involved

- `intelligence/indexer/language_registry.py` (`_GRAMMAR_MAP`, line ~27; also `_LANG_LABELS`)
- `intelligence/indexer/ast_indexer.py` (verify `_TS_FUNCTION_TYPES`/`_TS_CLASS_TYPES` against a
  real C# parse tree — likely no changes needed, confirm rather than assume)
- `interface/cli/service_detect.py` (`_SERVICE_MARKERS` — update in the same PR; C#'s marker is
  `*.csproj` or `*.sln` — check how `_SERVICE_MARKERS` handles glob-style markers vs. exact
  filenames, since most existing entries are exact filenames like `pom.xml`)
- `README.md` (remove C# from the "Longer-term" gap list once done)

## What to do

1. `pip install tree-sitter-c-sharp` (verify exact PyPI package name — it may not follow the
   `tree-sitter-<lang>` convention exactly), add `.cs` → the correct package to `_GRAMMAR_MAP`
   and a human-readable label to `_LANG_LABELS`.
2. Verify function/class extraction against a real `.cs` file — `method_declaration` and
   `class_declaration` are likely already in `_TS_FUNCTION_TYPES`/`_TS_CLASS_TYPES` from the
   Java mapping, but confirm the actual tree-sitter-c-sharp node type names match (they may
   differ from Java's despite similar syntax).
3. Add a C# project-file marker to `_SERVICE_MARKERS` in `service_detect.py`.
4. Add the grammar package to `pyproject.toml`'s `[project.optional-dependencies].languages`.
5. Write `tests/test_indexer_csharp.py`.
6. Remove C# from README's "Longer-term" grammar-support gap list.

## Acceptance criteria

- [ ] `cognirepo index-repo` on a `.cs` file extracts function/class/method symbols correctly
- [ ] `cognirepo doctor` reports C# under "Language support — indexable"
- [ ] New test passes; full suite stays green
- [ ] `_SERVICE_MARKERS` updated in the same PR
- [ ] README's gap-list mention removed

## Recipe

`docs/DEVELOPER_GUIDE.md` §How to Add a New Language.
