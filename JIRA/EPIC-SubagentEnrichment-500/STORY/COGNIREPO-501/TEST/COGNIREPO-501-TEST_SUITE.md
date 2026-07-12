# COGNIREPO-501 — Manual test suite

## TC-501-1: Grouping correctness
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced
- Prerequisites: story merged; repo indexed; identify two modules with no import/call relation
  (verify with dependency_graph) and one query hitting both.
- What to do: run the query through hybrid retrieval (via semantic_search_code/context_pack in
  debug); inspect component_ids.
- Prompt: "Search for '<spanning query>' and show which results CogniRepo considers structurally
  independent of each other."
- Expected results: two groups matching the verified dependency_graph reality; a query confined
  to one connected module yields a single group.
- Obtained results:
- Verdict:
