import os
import json
import faiss
import numpy as np

INDEX_FILE = "vector_db/semantic.index"
META_FILE = ".cognirepo/memory/semantic_metadata.json"


class LocalVectorDB:

    def __init__(self, dim=384):

        self.dim = dim
        if os.path.exists(INDEX_FILE):
            self.index = faiss.read_index(INDEX_FILE)
        else:
            self.index = faiss.IndexFlatL2(dim)

        if os.path.exists(META_FILE):
            with open(META_FILE) as f:
                self.metadata = json.load(f)
        else:
            self.metadata = []

    def save(self):

        faiss.write_index(self.index, INDEX_FILE)

        with open(META_FILE, "w") as f:
            json.dump(self.metadata, f, indent=2)

    def add(self, vector, text, importance):

        vector = np.array([vector]).astype("float32")

        self.index.add(vector)

        self.metadata.append({
            "text": text,
            "importance": importance
        })

        self.save()

    def search(self, vector, k=5):

        vector = np.array([vector]).astype("float32")

        distances, indices = self.index.search(vector, k)

        results = []

        for i in indices[0]:
            if i < len(self.metadata):
                results.append(self.metadata[i])

        return results