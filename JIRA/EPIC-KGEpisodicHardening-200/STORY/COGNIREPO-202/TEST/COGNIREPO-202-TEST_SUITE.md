# COGNIREPO-202 — Manual test suite

## TC-202-1: Semantic neighbours connected
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: story merged; re-indexed with similarity_edges on.
- What to do: pick two functions known to do near-identical work in different modules; query
  subgraph on one.
- Prompt: "Show the subgraph around <function_a>. Is its semantic twin <function_b> connected,
  and by what edge?"
- Expected results: SIMILAR_TO edge present with cosine weight; unrelated functions NOT
  connected; index time delta reported by index-repo acceptable.
- Obtained results:
- Verdict:
