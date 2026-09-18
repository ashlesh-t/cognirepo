# COGNIREPO-D01 — Manual test suite

## TC-D01-1: No model-ID literals outside classifier.py
- Test repo: cognirepo (the tool's own repo — this is a source-hygiene check, not a
  target-codebase one)
- Prerequisites: defect fix merged.
- What to do: run `grep -rn '"claude-\|"gemini-\|"gpt-\|"grok-' intelligence/ interface/
  --include='*.py' | grep -v classifier.py | grep -v tests/`.
- Prompt: "Verify no model IDs are hardcoded outside classifier.py."
- Expected results: zero hits.
- Obtained results: The literal grep from the ticket returns 2 hits, both in
  `interface/tools/sync_claude_memory.py:111-112` — `"source": "claude-auto-memory"` and
  `record_action("claude-memory-sync")`. Verified these are **not model-ID literals**: the
  first is a memory-source tag, the second an action-log name; neither names an actual model.
  False positives from the ticket's grep pattern being too broad (any `"claude-"` prefix).
  Refined regression test uses
  `'"claude-[a-z]+-[0-9]|"gemini-[0-9]|"gpt-[0-9]|"grok-'` — requires a digit immediately after
  the model-family word (matches real IDs like `claude-sonnet-4-6`, `gemini-2.0-flash`,
  `gpt-4o`; `grok-` alone suffices since real grok IDs like `grok-beta` have no digit) — this
  returns **zero hits** outside `classifier.py`, including against the two sync_claude_memory.py
  lines. Pinned permanently in `tests/test_model_id_invariant.py`.
  Also found (beyond the ticket's original 4 sites) 3 more real violations of the same class:
  `openai_adapter.py:44` (`model_id: str = "gpt-4o"`), `grok_adapter.py:25`
  (`_DEFAULT_MODEL = "grok-beta"`), `router.py:253` (`"grok": "grok-beta"` inside
  `_PROVIDER_DEFAULT_MODELS`) — all fixed the same way, via a new `ADAPTER_STANDALONE_DEFAULTS`
  dict in `classifier.py` covering all 4 providers.
- Verdict: **PASS**

## TC-D01-2: Adapter/router/key_probes behavior unchanged
- Test repo: cognirepo
- Prerequisites: defect fix merged.
- What to do: run `test_key_probes.py` and the router/adapter test files; confirm the actual
  default model values returned are identical to pre-fix (e.g. `claude-haiku-4-5` for
  anthropic's fallback probe).
- Prompt: "Run the model-adapter and router tests and confirm no behavior changed."
- Expected results: all pass; default values unchanged from before the fix — only the source of
  those literals moved.
- Obtained results: `tests/test_router.py tests/test_adapters.py tests/test_key_probes.py
  tests/test_local_adapter.py tests/test_router_extended.py` — 99/99 PASS, unchanged.
  Directly inspected each adapter's `call()` signature default post-fix:
  anthropic → `claude-sonnet-4-6`, gemini → `gemini-2.0-flash`, openai → `gpt-4o`,
  grok → `grok-beta`; `key_probes._anthropic_default_model()` → `claude-haiku-4-5`. All
  identical to the pre-fix hardcoded literals — confirmed a pure source-consolidation, zero
  behavior change.
- Verdict: **PASS**
