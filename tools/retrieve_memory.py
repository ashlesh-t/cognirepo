"""
Tool to retrieve memory using hybrid retrieval
(FAISS vector similarity + knowledge graph proximity + behaviour weights).

Architecture rule (CLAUDE.md): tools/ must NOT call FAISS directly.
All retrieval goes through retrieval/hybrid.py.
"""
import sys

from retrieval.hybrid import hybrid_retrieve


def retrieve_memory(query: str, top_k: int = 5) -> list:
    """
    Search for memories using hybrid retrieval.
    Returns a list of result dicts, each containing:
      text, importance, source, final_score,
      vector_score, graph_score, behaviour_score

    Degrades gracefully: if the graph/index are empty (cold start),
    returns pure vector results with graph_score=0, behaviour_score=0.
    """
    return hybrid_retrieve(query, top_k)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        results = retrieve_memory(sys.argv[1])
        for r in results:
            score = r.get("final_score", r.get("importance", "?"))
            print(f"[{score}] {r.get('text', '')}")
    else:
        print("Usage: python tools/retrieve_memory.py <query>")
