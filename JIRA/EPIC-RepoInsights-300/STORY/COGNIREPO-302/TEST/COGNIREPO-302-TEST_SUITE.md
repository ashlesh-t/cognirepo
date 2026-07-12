# COGNIREPO-302 — Manual test suite

## TC-302-1: Visual + offline check (USER-FACING — user fills results)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: 301+302 merged; seeded history.
- What to do: generate; open in a browser with devtools network tab; toggle OS light/dark;
  disconnect network and reload.
- Prompt: "Generate the insights HTML for this repo and give me the file path to open."
- Expected results: zero network requests; both themes legible and intentional; nav works;
  file < 200 KB; every fact hoverable/traceable to its data-ref.
- Obtained results:
- Verdict:

## TC-302-2: Idempotent update
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: TC-302-1 done.
- What to do: log one new episode; regenerate; ls .claude/insights/.
- Prompt: "Regenerate the insights report and confirm it updated the existing file rather than
  creating a new one."
- Expected results: exactly one HTML file; updated_at changed; new episode visible in timeline.
- Obtained results:
- Verdict:
