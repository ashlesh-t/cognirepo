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
| Swift | `.swift` | Stable | tree-sitter-swift |
| Kotlin | `.kt` `.kts` | Stable | tree-sitter-kotlin |
| JavaScript | `.js` `.jsx` | Stable | tree-sitter-javascript |
| TypeScript | `.ts` `.tsx` | Stable | tree-sitter-typescript |
| Java | `.java` | Stable | tree-sitter-java |
| C# | `.cs` | Stable | tree-sitter-c-sharp |
| Go | `.go` | Stable | tree-sitter-go |
| Rust | `.rs` | Stable | tree-sitter-rust |
| Ruby | `.rb` | Stable | tree-sitter-ruby |
| C / C++ | `.c` `.cpp` `.cc` `.h` | Stable | tree-sitter-cpp |
| PHP | `.php` | Stable | tree-sitter-php |

**Python is always available.** Even without `tree-sitter-python` installed, CogniRepo
falls back to the stdlib `ast` module for Python files. All other languages require the
grammar package from `cognirepo[languages]`.

---

## Planned

No further languages are planned yet — open an issue to request one.

---

## What gets extracted

For each supported file, the indexer extracts:

- **Functions** — name, line number, docstring (Python), call relationships
- **Classes** — name, line number, docstring (Python)
- **Call edges** — which functions call which (used to build the knowledge graph)

These become nodes and edges in the NetworkX knowledge graph, and entries in the
`ast_index.json` reverse index (symbol name → list of `(file, line)` locations).

### Language-specific notes

- **C#** — calls made inside constructors, property accessors (`get`/`set`/expression-bodied
  properties) and finalizers are not attributed to any symbol (constructors are not indexed as
  FUNCTION symbols, same as Java). Since constructors are where DI wiring usually lives, those
  call edges will be missing from `who_calls`. Null-conditional calls (`a?.Foo()`) are recorded.
  MSBuild output (`obj/`, `bin/`) and `.vs/` are skipped during indexing.

- **Swift** — an `extension Foo { … }` is indexed as a CLASS symbol named `Foo` at the extension
  site (its methods need a parent in the graph), so `lookup_symbol("Foo")` returns the type and
  each of its extensions. `init` and `deinit` are FUNCTION symbols. Calls inside computed-property
  bodies (`var x: Int { calc() }`) and property observers are not attributed to any symbol.
  Vendored/build dirs (`Pods/`, `.build/`, `Carthage/`, `DerivedData/`) are skipped.

- **Kotlin** — `object` declarations and companion objects are CLASS symbols. Secondary
  constructors and `init { … }` blocks are FUNCTION symbols, so calls made in them are attributed.
  These members have the same name in every class, and graph nodes are keyed `file::name`, so
  they are qualified with their class: `Service.constructor`, `Service.init`, and
  `Service.Companion` for an unnamed companion object (a named one keeps its own name).
  Supertypes are recorded by simple name, including `Iface by impl` delegation. `build/` and
  `.gradle/` are skipped; `.kts` scripts, including `build.gradle.kts` / `settings.gradle.kts`,
  are indexed deliberately — they are Kotlin code and their helper functions are real symbols,
  though they count towards the Kotlin file total.
  Known limits (tree-sitter-kotlin 1.1.0):
  - **Enum classes whose entries have bodies** (`ADD { override fun f() … }`) make the grammar
    fail to parse that region: the enum **and every declaration after it in the same file** are
    not indexed. Plain enums, enums with constructor arguments, and enums with members after `;`
    are fine. (A one-line `enum class E { A, B; fun d() = x() }` directly followed by another
    declaration does the same, but that form is rare.) Files with parse errors are reported at
    debug level as `[parse-errors] <path>`.
  - Explicit type-argument calls (`foo<Int>(1)`) are parsed as comparisons, so those calls are
    missed.
  - Calls inside property getters/setters and property initialisers are not attributed to any
    symbol.

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
4. Add the language's build/manifest file to `interface/cli/service_detect.py` `_SERVICE_MARKERS`,
   with a `lang_hint` that names the language (e.g. `"Kotlin/Gradle"`). If it has no such file,
   add it to `_NO_MARKER_LANGUAGES` in `tests/test_language_registry_sync.py` with the reason —
   that test fails until one of the two is done.
5. Add a fixture source file and tests in `tests/test_indexer_multilang.py`
6. Open a PR — reviewer verifies `cognirepo index-repo .` works on a real project
   in that language with correct symbol extraction

No other registration is needed. The indexer, graph, retrieval, and all tools are language-agnostic
once symbols are extracted.

---

## Check what's installed

```bash
cognirepo doctor --verbose
# Shows: Language support — Python, JS, TS, Java, C#, Go, Rust, Ruby, C++, Swift, Kotlin, PHP
# (or only "Python (built-in)" if cognirepo[languages] not installed)
```
