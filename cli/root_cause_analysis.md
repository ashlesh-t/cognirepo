  Hit ratio: ~40% CogniRepo / ~60% file-read fallback
  context_pack was dead (tiktoken missing) — that's the main coverage gap.

  ---

  mainly it suffers from cold start problem 

  Token Count Comparison

  ┌───────────────────────────────┬─────────────────────────┐
  │            Source             │ Approx tokens consumed  │
  ├───────────────────────────────┼─────────────────────────┤
  │ CogniRepo responses (3 tools) │ ~600 tokens             │
  ├───────────────────────────────┼─────────────────────────┤
  │ File reads (7 files, partial) │ ~2,400 tokens           │
  ├───────────────────────────────┼─────────────────────────┤
  │ If full files read raw        │ ~8,000–12,000 tokens    │
  ├───────────────────────────────┼─────────────────────────┤
  │ Savings from CogniRepo        │ ~70% vs naive full-read │
  └───────────────────────────────┴─────────────────────────┘

  ---
  Index Coverage Gaps

  ┌────────────────────────────────┬────────────────────────────────────────────────┐
  │              Gap               │                     Reason                     │
  ├────────────────────────────────┼────────────────────────────────────────────────┤
  │ context_pack fully dead        │ tiktoken not installed — install it: pip       │
  │                                │ install tiktoken                               │
  ├────────────────────────────────┼────────────────────────────────────────────────┤
  │ backend/routes/,               │ Explicitly noted in memory: "Backend layer NOT │
  │ background_tasks.py,           │  in semantic_search_code index — always needs  │
  │ scheduled_tasks.py             │ file read"                                     │
  ├────────────────────────────────┼────────────────────────────────────────────────┤
  │ update_database.py internals   │ Not surfaced by any CogniRepo tool — pure      │
  │                                │ file-read fallback                             │
  ├────────────────────────────────┼────────────────────────────────────────────────┤
  │ data/update.py internals       │ Not indexed at symbol level for this query     │
  ├────────────────────────────────┼────────────────────────────────────────────────┤
  │ Dynamic model loading path     │ GFIModelLoader._models cache hit logic —       │
  │                                │ needed direct read                             │
  └────────────────────────────────┴────────────────────────────────────────────────┘

  ---
  Would I Use CogniRepo Without Being Told?

  Yes, per CLAUDE.md — it mandates calling context_pack before any file >100 lines,
  lookup_symbol before grep, who_calls before impact analysis. Those are hard rules in
  this project's config.

  But honest assessment:

  ┌────────────────────┬─────────────────────────────┬─────────────────────────────┐
  │     Dimension      │          CogniRepo          │        My own tools         │
  │                    │                             │      (Grep/Read/Glob)       │
  ├────────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ Cold start (no     │ Useless                     │ Always works                │
  │ index)             │                             │                             │
  ├────────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ Pinpoint symbol    │ Fast when indexed           │ Grep is just as fast        │
  │ lookup             │                             │                             │
  ├────────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ Pipeline-level     │ retrieve_learnings was gold │ Would've missed the stub    │
  │ explanation        │  (stub correction!)         │ without reading carefully   │
  ├────────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ Architecture       │ Good when memories are      │ read + grep is more         │
  │ overview           │ seeded                      │ reliable                    │
  ├────────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ Dead tools         │ Silent failure, wastes a    │ Never silently fails        │
  │ (context_pack)     │ turn                        │                             │
  ├────────────────────┼─────────────────────────────┼─────────────────────────────┤
  │ Staleness risk     │ Memories lag behind code    │ File reads always current   │
  └────────────────────┴─────────────────────────────┴─────────────────────────────┘

  Verdict: CogniRepo's retrieve_learnings was the highest-value tool here — it surfaced
  the stub correction immediately without any file read. That's genuinely hard to
  replicate with grep alone. But semantic_search_code at 0.39–0.51 similarity scores
  mostly duplicated what Grep would've found instantly. Without context_pack (broken)
  the value drops significantly.

  Preference: Use CogniRepo for retrieve_learnings / retrieve_memory (past decisions,
  corrections, quirks) — that's irreplaceable institutional memory. Fall back to
  Grep/Read for live code — faster, always current, never broken.

    What it gave: 7 sections — all memory/doc hits, no raw code snippets. Content is
  recycled from retrieve_memory entries (same pipeline map, same function locations). No
   new code context — context_pack here purely reassembles stored memories, doesn't
  inject actual source lines.

  Verdict: Useful as single-call bootstrap (saves multiple retrieve_memory +
  semantic_search_code calls), but only as good as what's in the memory index. No code
  it hasn't seen before. For this repo, retrieve_learnings still higher signal — has the
   corrections/decisions that context_pack doesn't surface.