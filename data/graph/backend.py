# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Which store backs ``KnowledgeGraph()`` for this repo (#115, ADR 002).

``storage.graph_backend`` in ``.cognirepo/config.json`` is ``"networkx"`` (default: the graph is a
pickle loaded whole into every process) or ``"sqlite"`` (a WAL database read on demand, see
``sqlite_graph.py``). Opt-in: nothing changes unless a repo asks for it.

``storage.encrypt: true`` always selects networkx. A SQLite file is not covered by the Fernet
encryption that protects ``graph.pkl`` and its journal (ADR 002 §7, #186), so honouring ``sqlite``
there would silently drop a security promise; :func:`resolve` says so instead.

``COGNIREPO_GRAPH_BACKEND`` overrides the config file (tests, CI, a one-off benchmark); the
encryption rule still wins over it.
"""
from __future__ import annotations

import json
import os
import warnings
from typing import NamedTuple

NETWORKX = "networkx"
SQLITE = "sqlite"
BACKENDS = (NETWORKX, SQLITE)
ENV_VAR = "COGNIREPO_GRAPH_BACKEND"


class Resolution(NamedTuple):
    """The backend in force and, when it differs from what was asked for, why."""
    backend: str
    requested: str
    note: str = ""


def _requested() -> str:
    env = os.environ.get(ENV_VAR, "").strip().lower()
    if env:
        return env
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
    try:
        with open(get_path("config.json"), encoding="utf-8") as fh:
            value = json.load(fh).get("storage", {}).get("graph_backend", NETWORKX)
    except (OSError, ValueError, AttributeError):
        return NETWORKX
    return str(value).strip().lower() or NETWORKX


def resolve() -> Resolution:
    """Backend for the repo the current context points at. Cheap enough to call per construction."""
    requested = _requested()
    if requested not in BACKENDS:
        warnings.warn(
            f"storage.graph_backend {requested!r} is not one of {BACKENDS}; using {NETWORKX}.",
            stacklevel=2,
        )
        return Resolution(NETWORKX, requested, f"unknown backend {requested!r}")
    if requested == SQLITE:
        from core.security import get_storage_config  # pylint: disable=import-outside-toplevel
        if get_storage_config()[0]:
            return Resolution(
                NETWORKX, SQLITE,
                "storage.encrypt is on: the SQLite graph file is not encrypted yet (#186), "
                "so the encrypted pickle graph stays in use",
            )
    return Resolution(requested, requested)


def graph_store_path() -> str:
    """The on-disk file that holds the graph under the backend in force (for "is there a graph?" checks)."""
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
    return get_path("graph/graph.sqlite" if resolve().backend == SQLITE else "graph/graph.pkl")


def graph_class() -> type:
    """The ``KnowledgeGraph`` subclass to instantiate (the base class itself for networkx)."""
    if resolve().backend == SQLITE:
        from data.graph.sqlite_graph import SqliteGraph  # pylint: disable=import-outside-toplevel
        return SqliteGraph
    from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
    return KnowledgeGraph
