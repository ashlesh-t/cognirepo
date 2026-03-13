"""
Script to prune episodic or semantic memory to a specified maximum size.
"""
import json

FILE = ".cognirepo/memory/semantic_metadata.json"


def prune(max_size=200):
    """
    Keep only the most important memories based on their importance score.
    """
    with open(FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    data = sorted(data, key=lambda x: x["importance"], reverse=True)

    data = data[:max_size]

    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print("Memory pruned to", max_size)
