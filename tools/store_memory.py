"""
Tool to store a text memory into semantic memory.
"""
import sys
from memory.semantic_memory import SemanticMemory


def store_memory(text: str, source: str = "") -> dict:
    """
    Store a text memory in semantic memory and return status.
    """
    mem = SemanticMemory()
    importance = mem.compute_importance(text)
    mem.store(text)
    return {"status": "stored", "text": text, "source": source, "importance": importance}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = store_memory(sys.argv[1])
        print(result)
    else:
        print("Usage: python tools/store_memory.py <text>")
