from sentence_transformers import SentenceTransformer
from vector_db.local_vector_db import LocalVectorDB
from memory.embeddings import get_model
import time


class SemanticMemory:

    def __init__(self):
        self.model = get_model()
        self.db = LocalVectorDB()

    def compute_importance(self, text):

        length_score = min(len(text) / 100, 1)

        keywords = ["bug", "fix", "error", "important"]

        keyword_score = 0

        for k in keywords:
            if k in text.lower():
                keyword_score += 0.2

        return min(length_score + keyword_score, 1)

    def store(self, text):

        vector = self.model.encode(text)

        importance = self.compute_importance(text)

        self.db.add(vector, text, importance)

        print("Stored semantic memory with importance:", importance)

    def retrieve(self, query):

        vector = self.model.encode(query)

        results = self.db.search(vector)

        return results