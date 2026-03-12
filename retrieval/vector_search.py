from vector_db.local_vector_db import LocalVectorDB


def vector_search(query):
    vector_db_obj = LocalVectorDB()
    results = None
    try:
        results = vector_db_obj.search(query)
        print("Vector search results:")
        for r in results:
            print(r)
    except Exception as e:
        print(f"Error occurred while searching: {e}")
