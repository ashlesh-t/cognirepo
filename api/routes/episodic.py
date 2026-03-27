# SPDX-FileCopyrightText: 2026 Ashlesh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/your-username/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Episodic memory routes — append events and read history.

POST /episodic/log            — log an event with optional metadata
GET  /episodic/history        — retrieve recent event history
GET  /episodic/search?q=&limit= — keyword search across the event log
"""
import json

from fastapi import APIRouter, Query
from pydantic import BaseModel

from memory.episodic_memory import log_event, get_history

router = APIRouter(prefix="/episodic", tags=["episodic"])


class LogRequest(BaseModel):
    event: str
    metadata: dict = {}


@router.post("/log")
def log(req: LogRequest):
    """Append an episodic event to the log."""
    log_event(req.event, req.metadata)
    return {"status": "logged", "event": req.event}


@router.get("/history")
def history(limit: int = Query(default=100, ge=1, le=1000)):
    """Return the last `limit` episodic events (default 100)."""
    return get_history(limit)


@router.get("/search")
def search(
    q: str = Query(..., description="Keyword to search for in the event log"),
    limit: int = Query(default=10, ge=1, le=500),
):
    """Return up to `limit` episodic events whose JSON representation contains `q`."""
    query_lower = q.lower()
    events = get_history(limit=10000)
    matches = []
    for event in events:
        if query_lower in json.dumps(event).lower():
            matches.append(event)
            if len(matches) >= limit:
                break
    return matches
