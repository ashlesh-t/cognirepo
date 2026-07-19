# COGNIREPO-D07 — HybridRetriever discards real stored source, hardcodes "semantic"

Epic: COGNIREPO-100 · Branch: defect/COGNIREPO-D04_D05_D06 (bundled per user direction) · Base: story/COGNIREPO-105

## Backstory
Found while re-verifying TC-105-1 (`COGNIREPO-105` manual test suite) after fixing
`COGNIREPO-D04`. Even with D04's `store_memory()` kwarg fix applied, a real end-to-end run —
`BehaviourTracker.summarize_interaction_style()` → `store_memory(summary,
source="interaction_style")` → `retrieve_memory('interaction style')` — never returned
`source="interaction_style"`. The memory *was* stored correctly (confirmed via a fresh isolated
`.cognirepo/`, no docs ingested); `retrieve_memory` returned it, but labeled
`source: "semantic"`.

Root cause: `HybridRetriever._vector_retrieve()` (`intelligence/retrieval/hybrid.py:182`, pre-fix)
hardcoded `"source": "semantic"` on every vector-backend hit, discarding whatever the real
`source` metadata field was on the stored record (`memory`, `interaction_style`, `symbol`
(AST-embedded symbols, `ast_indexer.py:1562`/`:1855`), `init_doc` (doc chunks,
`doc_ingester.py:142`), `auto_discovery`, …) — `core/vector_db/local_vector_db.py`'s
`search_with_scores()` already returns the real field (`entry = dict(record)`), so the
information was available and simply thrown away one layer up.

`interface/tools/retrieve_memory.py::_structure_results()` (line 103, pre-fix) worked around
the missing real source with a text-shape heuristic — `source == "semantic" and " in " in text
and ":" in text` — to approximate "this vector hit looks like an AST symbol entry" for
code_hits/doc_hits bucketing, since it never had access to the real `source == "symbol"` value.

This is a pre-existing bug (not introduced by COGNIREPO-105) that happened to block TC-105-1's
verification: it makes it structurally impossible for `retrieve_memory()` to ever report a
vector hit's true storage `source`, for any caller, not just interaction-style memories.

## Description
1. `intelligence/retrieval/hybrid.py::_vector_retrieve()` — preserve the real
   `record.get("source", "memory")` instead of hardcoding `"semantic"`.
2. `interface/tools/retrieve_memory.py::_structure_results()` — replace the
   `source == "semantic" and <text-shape heuristic>` approximation with the precise
   `source in ("ast", "symbol")` check now that the real value is available. Drop the now-dead
   text-shape sub-condition (it existed only to guess at "symbol" without the real field).
3. `interface/tools/context_pack.py` was already keying its code/doc bucketing off
   `source == "ast"` specifically (not `"semantic"`), so it is unaffected by this fix — no
   changes needed there, confirmed by re-running `tests/test_context_pack.py`.

## Acceptance criteria
1. `retrieve_memory('interaction style')` returns `source="interaction_style"` for a memory
   stored via `store_memory(summary, source="interaction_style")` — this is what unblocks
   TC-105-1.
2. `retrieve_memory(structured=True)` still buckets AST/symbol hits into `code_hits` and
   everything else into `doc_hits` exactly as before (regression tests using real `source="ast"`
   and `source="symbol"` hits, plus non-code hits that happen to contain "X in Y:Z"-shaped text
   and must NOT be miscategorized as code hits).
3. `tests/test_context_pack.py`, `tests/test_retrieve_memory_extended.py`, and the full suite
   stay green.

## Risks / notes
- Widest-blast-radius fix in this bundle: `_vector_retrieve()` and `_structure_results()` are on
  the path of every `retrieve_memory`/`context_pack` call. Reviewed all current callers of
  `source` on hybrid-retrieve results (`context_pack.py`, `retrieve_memory.py`,
  `semantic_search_code.py` — the latter reads its own dedicated AST index directly, bypassing
  `HybridRetriever` entirely, so unaffected) before landing this.
- Filed and fixed in the same pass per explicit user direction (see `COGNIREPO-105`'s
  `TEST/COGNIREPO-105-TEST_SUITE.md` re-verification note) — bundled into
  `defect/COGNIREPO-D04_D05_D06` rather than its own branch/PR.
