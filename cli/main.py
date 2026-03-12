import argparse

from cli.init_project import init_project
from server.mcp_server import run_server
from tools.search_docs import search_docs
from tools.store_memory import store_memory
from tools.retrieve_memory import retrieve_memory


def main():
    vector_db = None

    parser = argparse.ArgumentParser(prog="cognirepo")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init")
    sub.add_parser("serve")

    search_cmd = sub.add_parser("search-docs")
    search_cmd.add_argument("query")

    store_cmd = sub.add_parser("store-memory")
    store_cmd.add_argument("text")

    retrieve_cmd = sub.add_parser("retrieve-memory")
    retrieve_cmd.add_argument("query")

    args = parser.parse_args()

    def initialize_vector_db():
        nonlocal vector_db
        if vector_db is None:
            from vector_db.local_vector_db import LocalVectorDB
            vector_db = LocalVectorDB()
        

    if args.command == "init":
        init_project()

    elif args.command == "serve":
        run_server()

    elif args.command == "search-docs":
        search_docs(args.query)

    elif args.command == "store-memory":
        store_memory(args.text)

    elif args.command == "retrieve-memory":
        retrieve_memory(args.query)
    elif args.command is "store-vector":
        initialize_vector_db()
        vector_db.add_documents([args.text])
    elif args.command is "search-vector":
        initialize_vector_db()
        vector_db.search(args.query)


if __name__ == "__main__":
    main()