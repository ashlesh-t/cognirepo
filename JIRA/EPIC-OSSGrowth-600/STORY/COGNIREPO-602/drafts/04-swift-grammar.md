TITLE: Add Swift language support (tree-sitter grammar mapping)

LABELS: good first issue, enhancement

BODY:
## Context

Same gap as Ruby/PHP/C# (see README.md Longer-term section): Swift's tree-sitter grammar exists
but isn't wired into CogniRepo's indexer.

## Files involved

- `intelligence/indexer/language_registry.py` (`_GRAMMAR_MAP`, line ~27; also `_LANG_LABELS`)
- `intelligence/indexer/ast_indexer.py` (`_TS_FUNCTION_TYPES`, `_TS_CLASS_TYPES`, line ~188)
- `interface/cli/service_detect.py` (`_SERVICE_MARKERS` — update in the same PR; Swift's marker
  is `Package.swift`)
- `README.md` (remove Swift from the "Longer-term" gap list once done)

## What to do

1. `pip install tree-sitter-swift`, add `.swift` → the correct package to `_GRAMMAR_MAP` and a
   label to `_LANG_LABELS`.
2. Add Swift's tree-sitter node types for functions/classes/structs to `_TS_FUNCTION_TYPES`
   and `_TS_CLASS_TYPES` in `ast_indexer.py` (Swift uses `function_declaration`, `class_declaration`,
   `struct_declaration`, `protocol_declaration` — verify exact node type strings against a real
   parse tree rather than assuming).
3. Add `"Package.swift": ("rest_api", "Swift/SPM")` (or the appropriate service type) to
   `_SERVICE_MARKERS` in `service_detect.py`.
4. Add `tree-sitter-swift>=0.23` to `pyproject.toml`'s `[project.optional-dependencies].languages`.
5. Write `tests/test_indexer_swift.py`.
6. Remove Swift from README's "Longer-term" grammar-support gap list.

## Acceptance criteria

- [ ] `cognirepo index-repo` on a `.swift` file extracts function/class/struct symbols correctly
- [ ] `cognirepo doctor` reports Swift under "Language support — indexable"
- [ ] New test passes; full suite stays green
- [ ] `_SERVICE_MARKERS` updated in the same PR
- [ ] README's gap-list mention removed

## Recipe

`docs/DEVELOPER_GUIDE.md` §How to Add a New Language.
