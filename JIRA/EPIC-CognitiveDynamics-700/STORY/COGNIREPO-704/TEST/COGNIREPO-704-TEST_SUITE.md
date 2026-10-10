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
- Obtained results: Ran the exact prompt text above through the real `check_precedent()`
  function. First pass with the initially-implemented `intent_pattern` **did not fire** —
  the natural phrasing "defaults model_id to 'claude-haiku-4-5'" didn't match the narrower
  regex (which only recognized `hardcode`/`default =` literal phrasings). Broadened the
  pattern to also recognize `defaults? \S+ to '<model>-...'` and `don't...import from
  classifier` phrasing. Re-ran: now correctly flags `model_names_only_in_classifier`, citing
  `CLAUDE.md — "Model names only in intelligence/orchestrator/classifier.py..."`,
  `related_defect: COGNIREPO-700-D01`, and `suggested_alternative:` "Import the model ID from
  classifier.py's DEFAULT_MODELS_BY_PROVIDER or ADAPTER_STANDALONE_DEFAULTS instead of
  hardcoding it." `advisory: true` throughout — never a hard stop.
- Verdict: **PASS** (after fixing a real gap found during this test itself — see above)

## TC-704-2: Ordinary request produces zero friction
- Test repo: cognirepo
- Prerequisites: story merged.
- What to do: ask for an unrelated, routine change with no recorded precedent conflict.
- Prompt: "Add a docstring to this function explaining what it does."
- Expected results: no pushback, no citation, proceeds normally — confirms no false positives on
  routine asks.
- Obtained results: Ran the exact prompt "Add a docstring to this function explaining what it
  does." through `check_precedent()` — `conflicts: []`. Also verified against 6 additional
  ordinary requests (CLI commands, test fixes, informational questions, generic storage/
  pagination asks) — all zero conflicts. No false positives found across the full set.
- Verdict: **PASS**
