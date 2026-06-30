# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to data.graph. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'graph' is deprecated; use 'data.graph' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("data.graph")
_sys.modules[__name__] = _real
for _sub in (
    "behaviour_tracker", "cross_service_path", "graph_utils",
    "knowledge_graph", "org_graph",
):
    _sys.modules[f"graph.{_sub}"] = _importlib.import_module(f"data.graph.{_sub}")
