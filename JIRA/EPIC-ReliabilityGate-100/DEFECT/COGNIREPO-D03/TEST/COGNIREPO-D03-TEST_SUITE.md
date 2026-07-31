# COGNIREPO-D03 — Manual test suite

## TC-D03-1: Pins are patched and audited
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: user decision recorded; defect merged.
- What to do: fresh venv, `pip install -r requirements.txt`, run pip-audit -r requirements.txt,
  run full pytest; check security.yml contains the new audit step.
- Prompt: "Install from requirements.txt in a fresh venv, audit it with pip-audit, and run the
  test suite. Report any vulnerability findings or failures."
- Expected results: cryptography==48.0.1 (or later), PyJWT≥2.13.0, starlette≥1.3.1,
  urllib3≥2.7.0 installed; pip-audit clean apart from the two documented ignores; 1203+ tests
  pass.
- Obtained results (reproduction at HEAD pre-fix, 2026-07-11): working-tree diff present,
  reverting pins from commits 779b113/6083b15; pip-audit not runnable offline in the audit
  session. Fix verification (post-fix, defect/COGNIREPO-D03, 2026-07-13): requirements.txt
  restored to cryptography==48.0.1, PyJWT==2.13.0, starlette==1.3.1, urllib3==2.7.0 (matches
  committed CVE-fixed pins); additionally bumped chromadb==1.5.9, idna==3.18,
  pydantic-settings==2.14.2, python-multipart==0.0.32, pillow==12.3.0 to close CVEs surfaced by
  the new requirements.txt audit step. `pip-audit -r requirements.txt` with the 3 documented
  ignores (CVE-2026-4539, CVE-2026-3219, CVE-2026-45829): "No known vulnerabilities found, 1
  ignored". Full pytest: 1203 passed, 5 skipped (unchanged from baseline). security.yml now
  runs a second pip-audit step against requirements.txt pins.
- Verdict: PASS
