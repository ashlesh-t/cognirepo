TITLE: Add PHP language support (tree-sitter grammar mapping)

LABELS: good first issue, enhancement

BODY:
## Context

Same gap as Ruby/C#/Swift (see README.md Longer-term section): PHP's tree-sitter grammar
exists but isn't wired into CogniRepo's indexer.

## Files involved

- `intelligence/indexer/language_registry.py` (`_GRAMMAR_MAP`, line ~27)
- `intelligence/indexer/ast_indexer.py` (`_TS_FUNCTION_TYPES`, `_TS_CLASS_TYPES`, line ~188)
- `interface/cli/service_detect.py` (`_SERVICE_MARKERS` — update in the same PR; PHP's marker
  is `composer.json`)
- `README.md` (remove PHP from the "Longer-term" gap list once done)

## What to do

1. `pip install tree-sitter-php`, add `.php` → the correct package/function to `_GRAMMAR_MAP`
   (tree-sitter-php exposes `language_php()`, not the default `language()` — check
   `_GRAMMAR_FUNC_OVERRIDE` in `language_registry.py` for the existing override pattern used by
   other multi-language packages, and add an entry there too).
2. Add PHP's tree-sitter node types for functions/classes/methods to `_TS_FUNCTION_TYPES`
   (`function_definition`, `method_declaration` — likely already covered) and `_TS_CLASS_TYPES`
   (`class_declaration` — likely already covered, verify against a real parse tree) in
   `ast_indexer.py`.
3. Add `"composer.json": ("rest_api", "PHP/Composer")` (or the appropriate service type) to
   `_SERVICE_MARKERS` in `service_detect.py`.
4. Add `tree-sitter-php>=0.23` to `pyproject.toml`'s `[project.optional-dependencies].languages`.
5. Write `tests/test_indexer_php.py`.
6. Remove PHP from README's "Longer-term" grammar-support gap list.

## Acceptance criteria

- [ ] `cognirepo index-repo` on a `.php` file extracts function/class/method symbols correctly
- [ ] `cognirepo doctor` reports PHP under "Language support — indexable"
- [ ] New test passes; full suite stays green
- [ ] `_SERVICE_MARKERS` updated in the same PR
- [ ] README's gap-list mention removed

## Recipe

`docs/DEVELOPER_GUIDE.md` §How to Add a New Language.
