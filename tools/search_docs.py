import sys
from retrieval.docs_search import search_docs as ds


def search_docs(query):

    results = ds(query)

    print("Docs found:")

    for r in results:
        print(r)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        search_docs(sys.argv[1])
    else:
        print("Usage: python tools/search_docs.py <query>")