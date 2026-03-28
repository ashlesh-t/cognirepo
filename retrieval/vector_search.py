# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

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
