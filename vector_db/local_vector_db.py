"""
Local vector database module using FAISS for storing and searching semantic embeddings.
"""

import os
import json
# pylint: disable=import-error
import faiss
import numpy as np

INDEX_FILE = "vector_db/semantic.index"
META_FILE = ".cognirepo/memory/semantic_metadata.json"


class LocalVectorDB:
    """
    Local vector database using FAISS for storing and searching semantic embeddings.
    """

    def __init__(self, dim=384):
        """
        Initializes the LocalVectorDB with the specified dimensionality.
        """
        self.dim = dim
        if os.path.exists(INDEX_FILE):
            self.index = faiss.read_index(INDEX_FILE)
        else:
            self.index = faiss.IndexFlatL2(dim)

        if os.path.exists(META_FILE):
            with open(META_FILE, encoding="utf-8") as f:
                self.metadata = json.load(f)
        else:
            self.metadata = []

    def save(self):
        """
        Saves the FAISS index and metadata to disk.
        """
        faiss.write_index(self.index, INDEX_FILE)

        with open(META_FILE, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2)

    def add(self, vector, text, importance):
        """
        Adds a new vector and its associated metadata to the database.
        """
        vector = np.array([vector]).astype("float32")

        self.index.add(vector)

        self.metadata.append({
            "text": text,
            "importance": importance
        })

        self.save()

    def search(self, vector, k=5):
        """
        Searches for the k most similar vectors to the given query vector.
        """
        vector = np.array([vector]).astype("float32")

        _, indices = self.index.search(vector, k)

        results = []

        for i in indices[0]:
            if i < len(self.metadata):
                results.append(self.metadata[i])

        return results

    def search_with_scores(self, vector, k=5):
        """
        Like search() but each result also includes 'l2_distance' and 'faiss_row'.
        Used by HybridRetriever to compute vector_score = max(0, 1 - dist/2).
        """
        vector = np.array([vector]).astype("float32")
        distances, indices = self.index.search(vector, k)
        results = []
        for dist, i in zip(distances[0], indices[0]):
            if i >= 0 and i < len(self.metadata):
                record = dict(self.metadata[i])
                record["l2_distance"] = float(dist)
                record["faiss_row"] = int(i)
                results.append(record)
        return results
