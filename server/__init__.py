# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to interface.server. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'server' is deprecated; use 'interface.server' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("interface.server")
_sys.modules[__name__] = _real
for _sub in ("idle_manager", "learning_middleware", "mcp_server", "session_listener"):
    _sys.modules[f"server.{_sub}"] = _importlib.import_module(f"interface.server.{_sub}")
