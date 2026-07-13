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

## Resolution (2026-07-13)
User's initial recollection: cryptography 48.0.1 "was giving some error, mostly some security
issue" on install, requiring the downgrade to 47.0.0. Investigation: `pip install
cryptography==48.0.1` (and PyJWT==2.13.0, starlette==1.3.1, urllib3==2.7.0) reproduced cleanly
in this environment — all four resolve to prebuilt manylinux wheels, no Rust/OpenSSL build step,
no install error. Full pytest (1203 passed, 5 skipped) green with all four at the CVE-fixed
pins. User confirmed the recollection was an install/build-type error, which did not reproduce
here — **decision: revert to the CVE-fixed pins** (`git checkout -- requirements.txt`),
restoring cryptography==48.0.1, PyJWT==2.13.0, starlette==1.3.1, urllib3==2.7.0. This
re-resolves GHSA-537c-gmf6-5ccf.

**Root cause of the original drift**: `.claude/settings.local.json` has a PostToolUse hook that
runs `pip freeze --exclude-editable > requirements.txt` after any `pip install`. An earlier
ad-hoc `pip install` (unrelated to these four packages) resolved older transitive pins into the
venv and the hook silently froze them into requirements.txt. This hook is a deliberate
project convention (auto-sync requirements.txt to the dev venv) — noted here, not changed by
this defect, but it means any manual `pip install` during future dev work can reintroduce drift
unless the venv itself is kept clean of scratch/audit-only tooling before running one.

**Additional CVEs found by the new `pip-audit -r requirements.txt` step** (AC2) that the
existing `pip install .` (pyproject-based) job never audited:
- `chromadb` 1.5.8 → CVE-2026-45829 / PYSEC-2026-311 (pre-auth code injection via
  `trust_remote_code` on chromadb's HTTP server `/collections` endpoint). No fixed version
  exists yet (last_affected 1.5.9, current latest). **Not exploitable here**: CogniRepo only
  uses `chromadb.PersistentClient` (embedded, in-process — `core/vector_db/chroma_adapter.py:60`,
  `interface/cli/main.py:410`), never chromadb's HTTP server — the vulnerable endpoint never
  runs. Bumped to 1.5.9 (latest) anyway; added as a third documented ignore in security.yml.
  **Separate pre-existing issue, out of scope here**: `chromadb` is used by real code but is not
  declared in pyproject.toml's `dependencies` — undeclared-dependency bug, worth its own ticket.
- `idna` 3.11 → PYSEC-2026-215, fixed in 3.15+. Bumped to 3.18 (latest).
- `pydantic-settings` 2.13.1 → GHSA-4xgf-cpjx-pc3j, fixed in 2.14.2. Bumped to 2.14.2.
- `python-multipart` 0.0.30 → CVE-2026-53540, fixed in 0.0.31. The original (rejected)
  working-tree diff's bump to 0.0.32 was, incidentally, a real CVE fix — kept at 0.0.32.
- `pillow` 12.2.0 → 5 CVEs (PYSEC-2026-2253/2254/2255/2256/2257, decompression-bomb-style DoS in
  font/image parsing), fixed in 12.3.0. Bumped to 12.3.0.

Final pip-audit (`-r requirements.txt`, 3 documented ignores): clean. Full pytest: 1203 passed,
5 skipped (unchanged from baseline).
