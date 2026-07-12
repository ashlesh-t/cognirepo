# COGNIREPO-D03 — DEFECT: uncommitted requirements.txt diff reverts committed CVE fixes

Epic: COGNIREPO-100 · Branch: defect/COGNIREPO-D03 · Base: development · Severity: P1 (security)
**BLOCKED on a human decision — do not execute the revert without the user's explicit answer.**

## Backstory / reproduction (verified at HEAD, 2026-07-11)
`git diff requirements.txt` (uncommitted) downgrades: cryptography 48.0.1→47.0.0, PyJWT
2.13.0→2.12.1, starlette 1.3.1→1.0.0, urllib3 2.7.0→2.6.3 (and bumps python-multipart
0.0.30→0.0.32). Git history shows the committed pins were deliberate security fixes:
- 779b113 "fix(deps): bump cryptography 47.0.0 → 48.0.1 (GHSA-537c-gmf6-5ccf)"
- 6083b15 "fix(deps): bump PyJWT, python-multipart, starlette, urllib3 for CVEs"
So the working-tree diff re-introduces at least GHSA-537c-gmf6-5ccf. Additional gap: CI's
pip-audit job audits `pip install .` (pyproject), NOT requirements.txt pins
(.github/workflows/security.yml) — so even committed, this file bypasses the audit gate.
Evidence: ../../COGNIREPO-100-Discovery.md §5.

## Description / fix
1. ASK THE USER: was the downgrade intentional (compat constraint?) — record the answer here.
2. Default action on "not intentional": `git checkout -- requirements.txt` (keep the
   python-multipart 0.0.32 bump only if tests pass with it and the user wants it — otherwise
   drop the whole diff).
3. Close the CI gap: add `pip-audit -r requirements.txt` (with the two documented ignores) as a
   step in security.yml so pinned requirements are audited from now on.

## Acceptance criteria
1. requirements.txt matches (or exceeds) the CVE-fixed committed pins — or the user's written
   acceptance of the downgrade is recorded in this ticket.
2. security.yml audits requirements.txt pins; CI green.
3. `pip install -r requirements.txt` + full pytest green on the resulting pins.
