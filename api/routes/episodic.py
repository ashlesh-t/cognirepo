"""
Episodic memory routes — append events and read history.

POST /episodic/log     — log an event with optional metadata
GET  /episodic/history — retrieve recent event history
"""
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
