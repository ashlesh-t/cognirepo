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
        result["storage_path"] = get_cognirepo_dir()
    except Exception:  # pylint: disable=broad-except
        pass

    try:
        from vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
        db = LocalVectorDB()
        result["memory"]["faiss_vectors"] = db.index.ntotal
    except Exception:  # pylint: disable=broad-except
        pass

    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        result["graph"]["nodes"] = kg.G.number_of_nodes()
        result["graph"]["edges"] = kg.G.number_of_edges()
    except Exception:  # pylint: disable=broad-except
        pass

    try:
        from memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
        result["circuit_breaker"]["state"] = get_breaker().state.value
    except Exception:  # pylint: disable=broad-except
        pass

    return JSONResponse(result)
