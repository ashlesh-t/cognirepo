┌──────────────────────────────────────────────────────────────────┐
│                        CogniRepo Core                            │
│                                                                  │
│   VectorDB (FAISS)       Knowledge Graph (NetworkX)              │
│   Semantic Memory        Dev + Query Behaviour Nodes             │
│   Episodic Log           Entity / Relationship Map               │
│   Repo AST Index         Reverse Index (file → symbol → vector)  │
│   Importance Scorer      Complexity Classifier                   │
└───────────────────────────┬──────────────────────────────────────┘
                            │
          ┌─────────────────┼──────────────────┐
          ▼                 ▼                  ▼
     FastAPI REST       MCP Server          gRPC Layer
     /login (JWT)       (Claude,            (inter-model
     /store             Gemini native)       comms channel)
     /retrieve
     /search
          │
          ▼
     Model Router / Orchestrator
     Complexity Classifier → FAST / BALANCED / DEEP
          │
     ┌────┴──────────────────────────┐
     ▼                               ▼
  OpenAI tool spec JSON          Gemini function spec
  (Cursor, Copilot, Codex)       (Gemini Pro / Flash)





  Complexity Classifier Design
Rule-based, no training data needed. Multi-signal weighted scorer.
SignalWeightLogicReasoning keywords (why, compare, refactor, design, tradeoff)+3Per keyword foundLookup keywords (what is, show, list, find, get)-2Per keyword foundVague referents (it, this, that without clear noun)+2Per unresolved referenceCross-entity count (functions, files, classes mentioned)+1.5Per entity above 2Context dependency (references episodic/graph history)+3BinaryQuery token length+0.5 per 10 tokensAfter first 20 tokensImperative + abstract combo (implement, build, architect)+4Binary
Score → Tier:

0–6 → FAST (Gemini Flash) — quick lookup, factual, single-entity
7–14 → BALANCED (Gemini Pro or Claude Haiku) — moderate reasoning
15+ → DEEP (Claude Sonnet / Opus) — cross-file, architectural, ambiguous

Override rules (hard signals that bypass score):

Query explicitly asks for "full context" or "everything related" → always DEEP
Single word / single symbol query → always FAST
Error trace in query → always BALANCED minimum


Let me build these up visually so they click properly.Let me walk through each one with a visual so it actually sticks.

---

## Knowledge Graph with NetworkX

Think of a knowledge graph as a **web of typed facts**. Not a list, not a table — a *graph* where the *relationship itself* has meaning.

In plain Python with NetworkX: nodes are things, edges are relationships between things. Both nodes and edges carry metadata.In code, this looks like:

```python
import networkx as nx

G = nx.DiGraph()

# Nodes carry metadata
G.add_node("auth.py",       type="FILE")
G.add_node("verify_token",  type="FUNCTION", file="auth.py", line=42)
G.add_node("jwt_auth",      type="CONCEPT")
G.add_node("fix auth bug",  type="QUERY",    timestamp="2024-03-01T10:22Z")

# Edges carry meaning
G.add_edge("verify_token", "auth.py",       rel="DEFINED_IN")
G.add_edge("verify_token", "jwt_auth",      rel="INVOLVES")
G.add_edge("fix auth bug", "verify_token",  rel="RETRIEVED",  weight=0.9)

# Now you can traverse: "what functions relate to JWT auth?"
jwt_neighbours = [n for n in G.neighbors("jwt_auth")]

# Or: shortest path between two things
path = nx.shortest_path(G, "fix auth bug", "auth.py")
# → ["fix auth bug", "verify_token", "auth.py"]
```

The power: FAISS tells you *"these two things are similar"*. The knowledge graph tells you *"these two things are related and here's **how** they're related"*. Combined in CogniRepo, you get both semantic nearness AND structural relationship.

---

## Episodic Log

Named after human episodic memory — you remember *events in sequence*, not just facts. "Yesterday I edited auth.py, then I asked about JWT, then I got an error."

Think of it as an **append-only event journal** with timestamps. The key property: *order matters*.The magic is in what you can *query from it later*:

- "What was I doing right before this error?" → time-range filter backward from error event
- "Which files do I always edit together?" → co-occurrence pattern across sessions
- "What queries led to useful results?" → QUERY event followed by FILE_EDIT within 5 mins = that retrieval was useful, boost those vectors

In JSON (your current `episodic.json`), each event is just:
```json
{
  "id": "e_4",
  "ts": "2024-03-01T10:23:18Z",
  "type": "ERROR",
  "session": "s_2024_03",
  "data": { "file": "auth.py", "line": 42, "error": "ImportError" },
  "prev": "e_3"
}
```

The `prev` pointer is what turns a flat list into a **linked timeline** you can traverse forward and backward.

---

## ER Map (Entity-Relationship)

An ER map answers: *"what data exists, what are its properties, and how do pieces of data relate to each other?"* It's the blueprint before you build any storage.

Here's CogniRepo's own ER map:Read the crow's foot notation like this: `SESSION ||--o{ QUERY` means *one session contains zero or more queries*. The `||` is "exactly one", `o{` is "zero or many". This is the design spec for your storage layer — before writing any Python, this tells you exactly what fields and foreign keys you need.

---

## Reverse Index

This is the trick behind every fast search engine. Normal index: *"document → words in it"*. Reverse index flips that: *"word → documents containing it"*. In CogniRepo's case, *"symbol/term → file locations that define or use it"*.In Python, the AST indexer builds this as a plain dict:

```python
reverse_index = {
    "token":        [("auth.py", 18), ("router.py", 34), ("session.py", 9)],
    "verify_token": [("auth.py", 42), ("auth.py", 67)],
    "session":      [("auth.py", 42), ("router.py", 11), ("session.py", 3)],
}

# Query is O(1) dict lookup — doesn't matter if you have 10 files or 10,000
locations = reverse_index.get("token", [])
```

The reverse index lives in `.cognirepo/index/ast_index.json`. The file watcher updates only the changed file's entries when something is edited — you don't rebuild everything, just re-scan that one file and patch the relevant keys.

---

## How all four connect in CogniRepo

When you ask "fix auth bug":

1. **Reverse index** finds all file locations for symbols in your query (`auth`, `verify_token`, `token`) — O(1) lookup
2. **FAISS** finds semantically similar past memories — vector similarity
3. **Knowledge graph** traverses from those symbols to related concepts, finds that "JWT auth" is 2 hops away — graph proximity
4. **Episodic log** retrieves: *"3 sessions ago you edited auth.py, got an ImportError, then added PyJWT"* — temporal context
5. All four signals get merged in `retrieval/hybrid.py` and handed to the model router as rich context

That's why CogniRepo is more useful than a plain RAG system — it knows *what things are*, *where they live*, *how they relate*, and *what you've done before*.