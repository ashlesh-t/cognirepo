"""
Tool to store a text memory into semantic memory.
"""
import sys
from memory.semantic_memory import SemanticMemory


def store_memory(text):
    """
    Store a text memory in semantic memory.
    """
    mem = SemanticMemory()

    mem.store(text)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        store_memory(sys.argv[1])
    else:
        print("Usage: python tools/store_memory.py <text>")
