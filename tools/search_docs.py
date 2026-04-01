# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Tool to search for a query in the markdown documentation.
Returns file paths with context snippets (grep -C 2 style).
"""
import sys
from retrieval.docs_search import search_docs as ds


def search_docs(query: str) -> list[dict]:
    """
    Search for *query* in all .md files recursively and print context snippets.
    Returns the raw list of match dicts for programmatic use.
    """
    results = ds(query)

    if not results:
        print(f"No docs found matching: {query!r}")
        return results

    # Group by file for cleaner display
    current_path = None
    for r in results:
        if r["path"] != current_path:
            current_path = r["path"]
            print(f"\n{r['path']}")
            print("─" * len(r["path"]))
        print(f"  Line {r['line']}:")
        for line in r["context"].splitlines():
            print(f"    {line}")

    return results


if __name__ == "__main__":
    if len(sys.argv) > 1:
        search_docs(sys.argv[1])
    else:
        print("Usage: python tools/search_docs.py <query>")
