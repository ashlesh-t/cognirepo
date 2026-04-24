# Language Support

CogniRepo's AST indexer maps functions, classes, and call relationships from your codebase.
"Language support" means CogniRepo can parse source files of that language, extract symbols,
build the knowledge graph, and enable O(1) symbol lookup via hybrid retrieval.

---

## Install

```bash
pip install cognirepo                # Python only (built-in, no extras needed)
pip install cognirepo[languages]     # all supported languages
```

---

## Current support

| Language | Extensions | Status | Grammar package |
|----------|------------|--------|-----------------|
| Python | `.py` | Stable — built-in | tree-sitter-python (optional, stdlib fallback) |
| JavaScript | `.js` `.jsx` | Stable | tree-sitter-javascript |
| TypeScript | `.ts` `.tsx` | Stable | tree-sitter-javascript |
| Java | `.java` | Stable | tree-sitter-java |
| Go | `.go` | Stable | tree-sitter-go |
| Rust | `.rs` | Stable | tree-sitter-rust |
| C / C++ | `.c` `.cpp` `.cc` `.h` | Stable | tree-sitter-cpp |

**Python is always available.** Even without `tree-sitter-python` installed, CogniRepo
falls back to the stdlib `ast` module for Python files. All other languages require the
grammar package from `cognirepo[languages]`.

---

## Planned

| Language | Issue |
|----------|-------|
| Ruby | #TBD |
| Swift | #TBD |
| Kotlin | #TBD |
| PHP | #TBD |

---

## What gets extracted

For each supported file, the indexer extracts:

- **Functions** — name, line number, docstring (Python), call relationships
- **Classes** — name, line number, docstring (Python)
- **Call edges** — which functions call which (used to build the knowledge graph)

These become nodes and edges in the NetworkX knowledge graph, and entries in the
`ast_index.json` reverse index (symbol name → list of `(file, line)` locations).

---

## Adding a new language

tree-sitter has grammars for 100+ languages. Adding support to CogniRepo takes ~30 minutes:

1. Find the grammar — search PyPI for `tree-sitter-<language>`
2. Add the extension mapping in `indexer/language_registry.py` `_GRAMMAR_MAP` dict:
   ```python
   ".ext": "tree_sitter_<language>",
   ```
3. Add the package to `pyproject.toml` under `[project.optional-dependencies] languages`:
   ```toml
   "tree-sitter-<language>>=0.23",
   ```
4. Add a fixture source file and tests in `tests/test_indexer_multilang.py`
5. Open a PR — reviewer verifies `cognirepo index-repo .` works on a real project
   in that language with correct symbol extraction

No other changes needed. The indexer, graph, retrieval, and all tools are language-agnostic
once symbols are extracted.

---

## Check what's installed

```bash
cognirepo doctor --verbose
# Shows: Language support — Python, JS, TS, Java, Go, Rust, C++
# (or only "Python (built-in)" if cognirepo[languages] not installed)
```
