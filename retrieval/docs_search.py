import os


def search_docs(query):

    results = []

    for root, _, files in os.walk("."):

        for f in files:

            if f.endswith(".md"):

                path = os.path.join(root, f)

                with open(path, errors="ignore") as file:

                    text = file.read()

                    if query.lower() in text.lower():
                        results.append(path)

    return results