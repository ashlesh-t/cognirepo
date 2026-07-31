# COGNIREPO-303 — Manual test suite

## TC-303-1: Both entry points
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: epic branch merged; MCP reconnected (new tool visible).
- What to do: run `cognirepo insights`; then call generate_insights via Claude.
- Prompt: "Generate the repo insights report via the MCP tool and give me the link."
- Expected results: both produce/update the same file; Claude's reply contains the path and NOT
  the report body; tool output small.
- Obtained results:
- Verdict:

## TC-303-2: Dogfood retrieval
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: TC-303-1 done; a distinctive decision seeded (e.g. "adopted zanzibar cache").
- What to do: search for report content via CogniRepo.
- Prompt: "Using search_docs, what does the insights report say about the zanzibar decision?"
- Expected results: hit from the markdown twin with a relevant snippet.
- Obtained results:
- Verdict:
