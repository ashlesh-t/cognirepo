"""
Module for searching the vector database.
"""
from vector_db.local_vector_db import LocalVectorDB


def vector_search(query):
    """
    Search for a query in the vector database and print results.
    """
    vector_db_obj = LocalVectorDB()
    try:
        results = vector_db_obj.search(query)
        print("Vector search results:")
        for r in results:
            print(r)
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error occurred while searching: {e}")
