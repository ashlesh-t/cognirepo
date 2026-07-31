# COGNIREPO-400 — Epic e2e test suite (cross-story flows only)

## E2E-400-1: Mood + persona end-to-end behavior shift (crosses 401+402+403)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: epic merged; repo indexed; MCP connected.
- What to do: (1) baseline session: ask a question, note response style; (2) record_error 3× same
  type within minutes, ask again; (3) record_user_preference("persona","caveman"), ask again;
  (4) clear preference, confirm reversion.
- Prompt (step 3): "Why does the retrieval cache invalidate on file edits? Answer normally."
- Expected results: step 2 profile shows mood frustrated with the error streak as evidence and
  Claude's answer visibly adapts (verification-first); step 3 answer is telegraphic but retains
  file:line refs and caveats; step 4 identical to baseline.
- Obtained results:
- Verdict:

## E2E-400-2: Economy persona measurement gate (crosses 403+404)
- Test repo: /home/ashlesh/my_works/cognirepo (this repo, richest golden set)
- Prerequisites: scripts/persona_bench.py merged; prompt set + goldens committed.
- What to do: run the harness persona-on vs persona-off across the full prompt set.
- Prompt: (harness-driven — the ~20 fixed repo questions in the prompt set)
- Expected results: JSON+markdown report; median reduction ≥40%; accuracy Δ ≤ 2 pp; results
  pasted into docs/METRICS.md.
- Obtained results:
- Verdict:
