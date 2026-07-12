# COGNIREPO-104 — Manual test suite

## TC-104-1: Dirty detection
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: story merged; cognirepo index-repo . completed on a clean tree.
- What to do: run verify-index (expect OK); append a comment to an indexed .py; run again.
- Prompt: "Run cognirepo verify-index before and after I touch a source file, and report both
  exit codes and outputs."
- Expected results: first run OK/exit 0; second run DIRTY line naming 1 file, exit 1; after
  `git checkout` of the file, OK again.
- Obtained results:
- Verdict:
