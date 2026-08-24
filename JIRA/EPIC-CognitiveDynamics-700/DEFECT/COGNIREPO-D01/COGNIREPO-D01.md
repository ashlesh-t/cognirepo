# COGNIREPO-D01 — model-ID literals hardcoded outside classifier.py

Epic: COGNIREPO-700 · Branch: defect/COGNIREPO-D01 · Base: development

## Backstory
CLAUDE.md's invariant "model names only in `intelligence/orchestrator/classifier.py`. No
hardcoding elsewhere" is already violated in current production code — found during
COGNIREPO-700's Discovery audit (`COGNIREPO-700-Discovery.md` §4), not during any story's
testing. Two distinct severities, both verified at HEAD (`f31ae81`):

**Clean violations** — no import from `classifier.py` at all:
- `intelligence/orchestrator/model_adapters/gemini_adapter.py:38` — `def call(..., model_id:
  str = "gemini-2.0-flash", ...)`.
- `intelligence/orchestrator/model_adapters/anthropic_adapter.py:48` — `def call(..., model_id:
  str = "claude-sonnet-4-6", ...)`.

**Subtler violations** — the primary path correctly imports/spreads `classifier.py`'s
`DEFAULT_MODELS_BY_PROVIDER` (confirming `classifier.py:175-176`'s own comment is honored there),
but a *duplicate* literal fallback sits alongside it, divergeable if `classifier.py`'s value ever
changes and this code path is ever hit:
- `interface/cli/key_probes.py:20-24` — `_anthropic_default_model()` correctly does
  `from intelligence.orchestrator.classifier import DEFAULT_MODELS_BY_PROVIDER` (line 20) and
  `.get("anthropic", "claude-haiku-4-5")` (line 22), but the `except ImportError: return
  "claude-haiku-4-5"` (lines 23-24) duplicates the literal instead of, e.g., failing loudly or
  referencing a single constant.
- `intelligence/orchestrator/router.py:251-253` — `_PROVIDER_DEFAULT_MODELS = {
  **DEFAULT_MODELS_BY_PROVIDER, "grok": "grok-beta"}` correctly spreads from `classifier.py`, but
  lines 339 and 691 both call `.get(provider, "claude-haiku-4-5")` — the same duplicate-literal
  pattern as above.

## Description / fix
Two separate fixes, matching the two severities:
1. `gemini_adapter.py:38` / `anthropic_adapter.py:48`: import each provider's default from
   `classifier.py`'s `DEFAULT_MODELS_BY_PROVIDER` instead of hardcoding a literal default
   parameter value (mirror the pattern `key_probes.py` already uses correctly for its primary
   path).
2. `key_probes.py:24` / `router.py:339,691`: remove the duplicate literal fallback — either let
   the lookup fail loudly (a missing provider key is itself a bug worth surfacing, not silently
   papering over with a possibly-stale literal), or reference a single named constant instead of
   repeating the string, so there is exactly one place `"claude-haiku-4-5"` can ever be spelled.

Verify at implementation time whether `classifier.py`'s own comment (lines 175-176: "router.py
and key_probes.py import from here — do NOT hardcode elsewhere") needs updating to explicitly
also cover `model_adapters/*.py`, since that's the file class most impacted by this defect.

## Acceptance criteria
1. `grep -rn '"claude-\|"gemini-\|"gpt-\|"grok-' intelligence/ interface/ --include='*.py' |
   grep -v classifier.py | grep -v tests/` returns zero hits for model-ID literals (excluding
   `classifier.py` itself and test fixtures) — this exact grep becomes a permanent regression
   test.
2. `gemini_adapter.py`/`anthropic_adapter.py` default `model_id` from `classifier.py`'s
   `DEFAULT_MODELS_BY_PROVIDER`, not a literal.
3. `key_probes.py`/`router.py` no longer duplicate a literal fallback — single source of truth
   enforced even on the fallback path.
4. Existing tests (`test_key_probes.py`, router/adapter tests) still pass unchanged — this is a
   source-consolidation fix, not a behavior change (the actual default values ship identical).

## Risks / notes
- Low risk: this is a pure refactor (import instead of hardcode), not new logic — the shipped
  default values themselves don't change.
- Blocks COGNIREPO-700 sign-off per `skill.md` §G.4 ("the parent story/epic cannot be signed off
  while its defects are open") — fix before or alongside 701-704, order not otherwise mandated.
