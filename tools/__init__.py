# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to interface.tools. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'tools' is deprecated; use 'interface.tools' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("interface.tools")
_sys.modules[__name__] = _real
for _sub in (
    "behaviour_hook", "benchmark", "bg_progress", "context_pack",
    "dependency_graph", "explain_change", "git_utils", "prime_session",
    "progress_window", "retrieve_memory", "search_docs", "semantic_search_code",
    "store_memory", "sync_claude_memory",
):
    _sys.modules[f"tools.{_sub}"] = _importlib.import_module(f"interface.tools.{_sub}")
