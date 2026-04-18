# Knowledge Graph Schema

> **Source of truth:** `graph/knowledge_graph.py` — `NodeType` and `EdgeType` classes.
> This document mirrors those constants and must be updated whenever the code changes.
> A sync test (`tests/test_docs_sync.py::test_edge_types_match_docs`) enforces parity.

---

## Node Types

| Constant | Value | Description |
|----------|-------|-------------|
| `NodeType.FILE` | `"FILE"` | A source file tracked in the repository |
| `NodeType.FUNCTION` | `"FUNCTION"` | A function or method defined in a file |
| `NodeType.CLASS` | `"CLASS"` | A class definition |
| `NodeType.CONCEPT` | `"CONCEPT"` | An abstract concept or keyword extracted from queries |
| `NodeType.QUERY` | `"QUERY"` | A user query issued via CLI or MCP |
| `NodeType.SESSION` | `"SESSION"` | A conversation session |
| `NodeType.USER_ACTION` | `"USER_ACTION"` | A recorded user interaction |
| `NodeType.MEMORY` | `"MEMORY"` | Cross-agent memory node (synced from Claude/Gemini/etc.) |

---

## Edge Type Glossary

| Constant | Value | Direction | Description | Example query |
|----------|-------|-----------|-------------|---------------|
| `EdgeType.RELATES_TO` | `"RELATES_TO"` | A → B | Generic semantic relationship between two nodes | `subgraph("HybridRetriever")` |
| `EdgeType.DEFINED_IN` | `"DEFINED_IN"` | FUNCTION/CLASS → FILE | A symbol is defined in a specific file | `who_calls("classify")` |
| `EdgeType.CALLED_BY` | `"CALLED_BY"` | FUNCTION → FUNCTION | A function is called by another function | `who_calls("hybrid_retrieve")` |
| `EdgeType.QUERIED_WITH` | `"QUERIED_WITH"` | CONCEPT → QUERY | A concept was mentioned in a query | `subgraph("circuit_breaker", depth=2)` |
| `EdgeType.CO_OCCURS` | `"CO_OCCURS"` | FILE ↔ FILE | Two files are frequently edited together (behaviour tracker) | `subgraph("memory/semantic_memory.py")` |

### Direction notes

- `CALLED_BY` edges go from callee → caller (i.e. "this function is called by that one").
  This makes `who_calls(fn)` a simple outbound traversal from fn's node.
- `DEFINED_IN` edges go from symbol → file, not file → symbol.
  This lets you find all symbols in a file via inbound traversal on the FILE node.

---

## Example Graph Queries

```python
from graph.knowledge_graph import KnowledgeGraph, EdgeType

kg = KnowledgeGraph()

# All callers of hybrid_retrieve
callers = kg.get_neighbours("hybrid_retrieve", edge_types=[EdgeType.CALLED_BY], direction="out")

# All symbols defined in retrieval/hybrid.py
syms = kg.get_neighbours("FILE:retrieval/hybrid.py", edge_types=[EdgeType.DEFINED_IN], direction="in")

# Files that co-occur with memory/semantic_memory.py
coedits = kg.get_neighbours("memory/semantic_memory.py", edge_types=[EdgeType.CO_OCCURS], direction="out")
```
CALLS
