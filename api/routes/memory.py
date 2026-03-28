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

from tools.store_memory import store_memory
from tools.retrieve_memory import retrieve_memory
from retrieval.docs_search import search_docs

router = APIRouter(prefix="/memory", tags=["memory"])


class StoreRequest(BaseModel):
    text: str
    source: str = ""


class RetrieveRequest(BaseModel):
    query: str
    top_k: int = 5


@router.post("/store")
def store(req: StoreRequest):
    """Store a semantic memory entry."""
    return store_memory(req.text, req.source)


@router.post("/retrieve")
def retrieve(req: RetrieveRequest):
    """Return the top-k semantically similar memories."""
    return retrieve_memory(req.query, req.top_k)


@router.get("/search")
def search(q: str):
    """Full-text search across markdown documentation files."""
    return search_docs(q)
