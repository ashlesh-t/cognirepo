import json

FILE = ".cognirepo/memory/semantic_metadata.json"


def prune(max_size=200):

    with open(FILE) as f:
        data = json.load(f)

    data = sorted(data, key=lambda x: x["importance"], reverse=True)

    data = data[:max_size]

    with open(FILE, "w") as f:
        json.dump(data, f, indent=2)

    print("Memory pruned to", max_size)