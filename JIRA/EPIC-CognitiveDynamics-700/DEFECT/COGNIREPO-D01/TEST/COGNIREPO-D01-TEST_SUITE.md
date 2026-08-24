# COGNIREPO-D01 — Manual test suite

## TC-D01-1: No model-ID literals outside classifier.py
- Test repo: cognirepo (the tool's own repo — this is a source-hygiene check, not a
  target-codebase one)
- Prerequisites: defect fix merged.
- What to do: run `grep -rn '"claude-\|"gemini-\|"gpt-\|"grok-' intelligence/ interface/
  --include='*.py' | grep -v classifier.py | grep -v tests/`.
- Prompt: "Verify no model IDs are hardcoded outside classifier.py."
- Expected results: zero hits.
- Obtained results:
- Verdict:

## TC-D01-2: Adapter/router/key_probes behavior unchanged
- Test repo: cognirepo
- Prerequisites: defect fix merged.
- What to do: run `test_key_probes.py` and the router/adapter test files; confirm the actual
  default model values returned are identical to pre-fix (e.g. `claude-haiku-4-5` for
  anthropic's fallback probe).
- Prompt: "Run the model-adapter and router tests and confirm no behavior changed."
- Expected results: all pass; default values unchanged from before the fix — only the source of
  those literals moved.
- Obtained results:
- Verdict:
