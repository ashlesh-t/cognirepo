"""
Utility to load and retrieve the embedding model.
"""
# pylint: disable=import-error
from sentence_transformers import SentenceTransformer

MODEL = None


def get_model():
    """
    Returns the SentenceTransformer model, loading it if necessary.
    """
    global MODEL  # pylint: disable=global-statement

    if MODEL is None:
        print("Loading embedding model once...")
        MODEL = SentenceTransformer("all-MiniLM-L6-v2")

    return MODEL
