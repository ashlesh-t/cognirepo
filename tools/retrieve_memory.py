"""
Tool to retrieve semantic memory based on a query.
"""
import sys
from memory.semantic_memory import SemanticMemory


def retrieve_memory(query):
    """
    Search for a query in semantic memory and print the results.
    """
    mem = SemanticMemory()

    results = mem.retrieve(query)

    print("Results:")

    for r in results:
        print(r["text"], "| importance:", r["importance"])


if __name__ == "__main__":
    if len(sys.argv) > 1:
        retrieve_memory(sys.argv[1])
    else:
        print("Usage: python tools/retrieve_memory.py <query>")
