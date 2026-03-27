# SPDX-FileCopyrightText: 2026 Ashlesh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/your-username/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Tool to search for a query in the markdown documentation.
"""
import sys
from retrieval.docs_search import search_docs as ds


def search_docs(query):
    """
    Search for a query in documentation and print the results.
    """
    results = ds(query)

    print("Docs found:")

    for r in results:
        print(r)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        search_docs(sys.argv[1])
    else:
        print("Usage: python tools/search_docs.py <query>")
