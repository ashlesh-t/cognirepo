# Retrieval Pipeline

> **Source of truth:** `retrieval/hybrid.py` — `HybridRetriever.retrieve()`.

CogniRepo uses a **3-signal weighted merge** for retrieval. AST lookup is a
candidate-expansion pre-scorer (not a merge signal), and episodic search is
a separate BM25 side-channel.

---

## Pipeline Overview

```
Query string
    │
    ▼
1. AST pre-scorer — extract_entities_from_text(query)
   │   O(1) reverse-index lookup per entity → ast_candidates[]
    │
    ▼
2. Vector search — FAISS flat index
   │   query_vector = model.encode(query)
   │   wider net: top_k × 3 candidates
   │
    ▼
3. Merge + dedup — _merge_candidates(vector, ast)
   │   deduplicate by _id; AST candidates inherit vector_score when matched
   │
    ▼
4. 3-signal scoring — _score_candidates()
   │
   │   final_score = w_vector × vector_score
   │               + w_graph  × graph_score
   │               + w_behav  × behaviour_score
   │
   │   Default weights (config.json → retrieval_weights):
   │     vector    = 0.5
   │     graph     = 0.3
   │     behaviour = 0.2
   │
   │   Score normalization:
   │     vector_score    = max(0, 1 − l2_distance / 2.0)      → [0, 1]
   │     graph_score     = 1 / (1 + hop_distance)              → [0, 1]
   │     behaviour_score = log(1+count) / log(1+max_count)     → [0, 1]
   │
    ▼
5. Sort + truncate → top_k results
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  Episodic side-channel (separate pipeline)           │
│  episodic_bm25_filter(query) → BM25-ranked events   │
│  NOT merged into final_score — returned separately  │
└──────────────────────────────────────────────────────┘
```

---

## Signal Detail

### Vector signal (weight 0.5)
- Embedding model: `all-MiniLM-L6-v2` (384-dim, sentence-transformers)
- Index: FAISS `IndexFlatL2`
- Distance converted to similarity: `max(0, 1 − l2_dist / 2.0)`

### Graph signal (weight 0.3)
- Hop distance from query entities to candidate node in `KnowledgeGraph`
- Tries directed path first, falls back to undirected BFS
- Cold start (empty graph): `graph_score = 0` — degrades gracefully to pure vector

### Behaviour signal (weight 0.2)
- Access frequency per symbol from `BehaviourTracker`
- Log-normalized: `log(1 + count) / log(1 + max_count)`
- Cold start (no interactions): `behaviour_score = 0`

---

## Why AST is a Pre-scorer, Not a Merge Signal

AST lookup expands the **candidate pool** before scoring — it uses `ASTIndexer.lookup_symbol()`
to add code symbols that the vector search might have missed. These candidates then flow through
the same 3-signal merge as vector candidates. The "4-signal" label that appeared in earlier docs
was a mischaracterization — AST does not have its own weight in the final scoring formula.

## Why Episodic is a Side-channel

Episodic events are narrative entries (`"fixed bug in auth"`, `"explored graph schema"`).
They live in a separate BM25 corpus and are retrieved by `episodic_bm25_filter()`. They
are surfaced to the context builder as a separate source, not blended into the semantic
similarity score.
