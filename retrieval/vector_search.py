# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Module for searching the vector database.
"""
import logging

from vector_db.local_vector_db import LocalVectorDB

logger = logging.getLogger(__name__)


def vector_search(query):
    """
    Search for a query in the vector database and return results.
    """
    vector_db_obj = LocalVectorDB()
    try:
        results = vector_db_obj.search(query)
        logger.debug("Vector search results: %s", results)
        return results
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error occurred while searching: %s", e)
        return []
