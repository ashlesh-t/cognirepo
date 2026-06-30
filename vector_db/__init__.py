# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to core.vector_db. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'vector_db' is deprecated; use 'core.vector_db' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("core.vector_db")
_sys.modules[__name__] = _real
for _sub in ("adapter", "chroma_adapter", "factory", "local_vector_db"):
    _sys.modules[f"vector_db.{_sub}"] = _importlib.import_module(f"core.vector_db.{_sub}")
