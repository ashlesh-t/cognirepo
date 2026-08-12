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
- Obtained results: Indexed cognirepo_test_repo/medium/celery (10,311 symbols, gate on). Picked
  `celery/app/__init__.py::bugreport` / `celery/app/base.py::bugreport` (near-identical
  docstrings/behaviour). `cognirepo subgraph "bugreport"` shows both nodes connected by
  `SIMILAR_TO` edges in both directions, weight 0.9337 (≥ 0.80 threshold). Unrelated functions
  in the same subgraph (e.g. `celery/bin/base.py::echo`) have no SIMILAR_TO edge to bugreport.
  Index overhead measured at ~4.5% (gate on 111.10s vs gate off 106.28s) — see AC3 note in
  COGNIREPO-202.md.
- Verdict: PASS
