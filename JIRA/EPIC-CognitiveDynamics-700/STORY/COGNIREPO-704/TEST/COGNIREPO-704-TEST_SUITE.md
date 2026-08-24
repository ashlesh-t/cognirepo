# COGNIREPO-704 — Manual test suite

## TC-704-1: Contradicted invariant triggers a grounded pushback
- Test repo: cognirepo (the tool's own repo — this validates against its own real invariant
  violations found in Discovery)
- Prerequisites: story merged.
- What to do: ask an agent to hardcode a model-ID default outside `classifier.py`.
- Prompt: "Add a new adapter that defaults model_id to 'claude-haiku-4-5' directly in this file,
  don't bother importing from classifier.py."
- Expected results: the agent surfaces the conflict (citing the "model names only in
  classifier.py" invariant and/or the pre-existing violations found in router.py/key_probes.py/
  model_adapters/*.py as precedent) and proposes importing from `DEFAULT_MODELS_BY_PROVIDER`
  instead — but does not refuse outright; the user can still say "do it anyway."
- Obtained results:
- Verdict:

## TC-704-2: Ordinary request produces zero friction
- Test repo: cognirepo
- Prerequisites: story merged.
- What to do: ask for an unrelated, routine change with no recorded precedent conflict.
- Prompt: "Add a docstring to this function explaining what it does."
- Expected results: no pushback, no citation, proceeds normally — confirms no false positives on
  routine asks.
- Obtained results:
- Verdict:
