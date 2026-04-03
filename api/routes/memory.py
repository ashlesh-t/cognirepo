# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Memory routes — thin wrappers around the tools/ layer.

POST /memory/store    — store a semantic memory
POST /memory/retrieve — semantic similarity search
GET  /memory/search   — full-text search across .md docs
"""
from fastapi import APIRouter
from pydantic import BaseModel

from api.cache import cache_get, cache_set
from tools.store_memory import store_memory
from tools.retrieve_memory import retrieve_memory
from retrieval.docs_search import search_docs

router = APIRouter(prefix="/memory", tags=["memory"])


class StoreRequest(BaseModel):  # pylint: disable=too-few-public-methods
    """Request body for storing a semantic memory."""
    text: str
    source: str = ""


class RetrieveRequest(BaseModel):  # pylint: disable=too-few-public-methods
    """Request body for semantic similarity search."""
    query: str
    top_k: int = 5


@router.post("/store")
def store(req: StoreRequest):
    """Store a semantic memory entry."""
    return store_memory(req.text, req.source)


@router.post("/retrieve")
def retrieve(req: RetrieveRequest):
    """Return the top-k semantically similar memories (Redis-cached for 5 min)."""
    cache_key = f"retrieve:{hash((req.query, req.top_k))}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    result = retrieve_memory(req.query, req.top_k)
    cache_set(cache_key, result)
    return result


@router.get("/search")
def search(q: str):
    """Full-text search across markdown documentation files."""
    return search_docs(q)
