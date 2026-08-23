# COGNIREPO-302 — Manual test suite

## TC-302-1: Real report renders correctly, both themes, offline
- Test repo: `/home/ashlesh/my_works/cognirepo` (this repo's own real data, via
  `insights_collector.collect()` from COGNIREPO-301).
- Prerequisites / setup steps: none — read-only collect + render against live data.
- What to do: `collect()` → `insights.generate(model, repo_root, now)`; open the resulting
  HTML in a browser; toggle OS light/dark; grep the file for external URLs.
- Prompt: "Show me an HTML report of what's happened in this repo."
- Expected results: single self-contained file, section nav (overview/timeline/decisions/
  challenges/activity/index-health), correct rendering in both color schemes, zero external
  requests, < 200 KB.
- Obtained results: generated `insights_preview-insights.html` (22,538 bytes, well under the
  200 KB budget) from this repo's real timeline/decisions/branches/index-health; published as
  an Artifact for design review — user confirmed the UI ("Thats crazy good"). `grep -E
  '(src|href)="https?://'` on the output: zero matches. `prefers-color-scheme: dark` block and
  a `:root` light-token block both present.
- Verdict: PASS

## TC-302-2: Idempotent regeneration — same path, one file, updated_at advances
- Test repo: `/tmp/insights_idempotency_check` (scratch dir, deleted after the run).
- Prerequisites / setup steps: none.
- What to do: call `generate(model, repo_root, now=t1)` then `generate(model, repo_root,
  now=t2)` with the real repo's collected model; inspect the output directory.
- Prompt: "Regenerate the insights report — it should update in place, not create a second
  file."
- Expected results: both calls return the same `path`; exactly one `.html` file on disk;
  `generated_at` unchanged across calls (preserved from the first write); `updated_at` equals
  the second call's timestamp.
- Obtained results: `r1['path'] == r2['path']` → True. `os.listdir(.claude/insights/)` →
  `['insights_idempotency_check-insights.html']` (one file). `generated_at` identical between
  runs; `updated_at` advanced from `2026-08-18T19:41:31...` to `2026-08-19T00:00:00+00:00`.
- Verdict: PASS

## TC-302-3: data-ref coverage and no_data placeholders (unit-level, automated)
- Test repo: synthetic (in-memory `InsightsModel` fixtures — see
  `tests/test_insights_render_write.py`).
- Prerequisites / setup steps: none — covered by the automated suite; listed here per §F.4
  for traceability against AC3.
- What to do: `pytest tests/test_insights_render_write.py -q`.
- Prompt: n/a (automated).
- Expected results: every `<li>` in a seeded-model render carries `data-ref`; every empty
  section in an empty-model render shows "no data recorded"; injected `<script>` content in a
  summary is HTML-escaped, not executed.
- Obtained results: PASS — `venv/bin/python -m pytest tests/test_insights_render_write.py -q`
  → 15 passed (data-ref coverage, no_data placeholders, HTML escaping, balanced-tag parse,
  size budget, unicode-repo-name slugify, idempotency, markdown twin).
- Verdict: PASS
