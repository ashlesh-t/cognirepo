TITLE: Add Ruby language support (tree-sitter grammar mapping)

LABELS: good first issue, enhancement

BODY:
## Context

CogniRepo indexes source code via tree-sitter grammars registered in
`intelligence/indexer/language_registry.py::_GRAMMAR_MAP`. Ruby isn't mapped yet — README.md
(Longer-term section) lists it as a known gap: "tree-sitter grammars exist; need
`_TS_FUNCTION_TYPES`/`_TS_CLASS_TYPES` mappings and call-extraction rules per language."

## Files involved

- `intelligence/indexer/language_registry.py` (`_GRAMMAR_MAP`, line ~27)
- `intelligence/indexer/ast_indexer.py` (`_TS_FUNCTION_TYPES`, `_TS_CLASS_TYPES`, line ~188)
- `interface/cli/service_detect.py` (`_SERVICE_MARKERS` — **must** be updated in the same PR,
  per the module's own docstring: "When a new language is added to language_registry, add its
  build file marker here too." Ruby's marker is `Gemfile`.)
- `README.md` (remove Ruby from the "Longer-term" gap list once done)

## What to do

1. `pip install tree-sitter-ruby`, add `.rb` → `tree_sitter_ruby` to `_GRAMMAR_MAP`.
2. Add Ruby's tree-sitter node types for functions/classes/methods to `_TS_FUNCTION_TYPES`
   (`method`, `singleton_method`) and `_TS_CLASS_TYPES` (`class`, `module`) in `ast_indexer.py`.
3. Add `"Gemfile": ("rest_api", "Ruby/Bundler")` (or the appropriate service type) to
   `_SERVICE_MARKERS` in `service_detect.py`.
4. Add `tree-sitter-ruby>=0.23` to `pyproject.toml`'s `[project.optional-dependencies].languages`.
5. Write `tests/test_indexer_ruby.py` (model it on `tests/test_indexer_kotlin.py`-style tests
   referenced in `docs/DEVELOPER_GUIDE.md` §How to Add a New Language, if one exists — otherwise
   on any existing `test_indexer_<lang>.py`).
6. Remove Ruby from README's "Longer-term" grammar-support gap list.

## Acceptance criteria

- [ ] `cognirepo index-repo` on a `.rb` file extracts function/class/method symbols correctly
      (verify against a small real Ruby file, e.g. from a public gem)
- [ ] `cognirepo doctor` reports Ruby under "Language support — indexable"
- [ ] New test passes; full suite stays green
- [ ] `_SERVICE_MARKERS` updated in the same PR
- [ ] README's gap-list mention removed

## Recipe

`docs/DEVELOPER_GUIDE.md` §How to Add a New Language has the full step-by-step walkthrough.
