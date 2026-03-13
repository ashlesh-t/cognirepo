"""
Module for searching through markdown files in the repository.
"""
import os


def search_docs(query):
    """
    Search for a query string in all .md files in the current directory and subdirectories.
    """
    results = []

    for root, _, files in os.walk("."):
        for f in files:
            if f.endswith(".md"):
                path = os.path.join(root, f)
                with open(path, "r", encoding="utf-8", errors="ignore") as file:
                    text = file.read()
                    if query.lower() in text.lower():
                        results.append(path)

    return results
