# COGNIREPO-600 — Epic e2e test suite (cross-story flows only)

## E2E-600-1: Claims audit passes cold (crosses 601+603)
- Test repo: /home/ashlesh/my_works/cognirepo (this repo)
- Prerequisites: epic merged and published to the README on GitHub.
- What to do: as a skeptical newcomer, read README top-to-bottom against METRICS.md and the
  registry files; click every link.
- Prompt: "Read README.md and docs/METRICS.md. List every quantitative claim and check each one
  is internally consistent and sourced to a dated run. Flag anything that contradicts."
- Expected results: zero contradictions flagged; Discord link resolves; benchmark repo counts
  identical everywhere; fastapi row explained.
- Obtained results:
- Verdict:

## E2E-600-2: Contributor cold-start (crosses 602)
- Test repo: /home/ashlesh/my_works/cognirepo (fresh clone)
- Prerequisites: 602 merged; issues opened.
- What to do: follow CONTRIBUTING.md from a fresh clone to a first PR on a good-first-issue.
- Prompt: "I want to contribute to CogniRepo. Using only CONTRIBUTING.md and what it links,
  pick a good first issue and tell me the exact steps to a mergeable PR."
- Expected results: a coherent path exists (label → issue → DEVELOPER_GUIDE recipe → PR
  checklist) with no dead links or missing sections.
- Obtained results:
- Verdict:
