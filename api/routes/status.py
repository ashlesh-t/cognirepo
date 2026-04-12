# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
GET /status/detailed

Returns the same diagnostics as `cognirepo doctor` as JSON, suitable for
Grafana dashboards and automated health monitors.

No auth required (read-only, no sensitive data).
"""
from __future__ import annotations

import os
import platform
import sys
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

_SERVER_START = time.time()


@router.get("/status/detailed")
async def status_detailed() -> JSONResponse:
    """
    Return a detailed status snapshot mirroring ``cognirepo doctor``.

    Response schema
    ---------------
    {
      "uptime_s": float,
      "python": str,
      "platform": str,
      "memory": {"faiss_vectors": int | null},
      "graph":  {"nodes": int | null, "edges": int | null},
      "circuit_breaker": {"state": str},
      "multi_agent": bool,
      "grpc_port": int,
      "storage_path": str,
      "ok": bool
    }
    """
    result: dict = {
        "uptime_s": round(time.time() - _SERVER_START, 1),
        "python": sys.version,
        "platform": platform.platform(),
        "memory": {"faiss_vectors": None},
        "graph": {"nodes": None, "edges": None},
        "circuit_breaker": {"state": "unknown"},
        "multi_agent": os.environ.get("COGNIREPO_MULTI_AGENT_ENABLED", "false").lower() == "true",
        "grpc_port": int(os.environ.get("COGNIREPO_GRPC_PORT", "50051")),
        "storage_path": "",
        "ok": True,
    }

    try:
        from config.paths import get_cognirepo_dir  # pylint: disable=import-outside-toplevel
        _path = get_cognirepo_dir()
        result["storage_path"] = str(_path) if _path is not None else ""
    except Exception:  # pylint: disable=broad-except
        pass

    try:
        from vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
        db = LocalVectorDB()
        _ntotal = db.index.ntotal
        result["memory"]["faiss_vectors"] = int(_ntotal) if isinstance(_ntotal, (int, float)) else None
    except Exception:  # pylint: disable=broad-except
        pass

    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        _nodes = kg.G.number_of_nodes()
        _edges = kg.G.number_of_edges()
        result["graph"]["nodes"] = int(_nodes) if isinstance(_nodes, (int, float)) else None
        result["graph"]["edges"] = int(_edges) if isinstance(_edges, (int, float)) else None
    except Exception:  # pylint: disable=broad-except
        pass

    try:
        from memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
        _state = get_breaker().state.value
        result["circuit_breaker"]["state"] = str(_state) if _state is not None else "unknown"
    except Exception:  # pylint: disable=broad-except
        pass

    return JSONResponse(result)
