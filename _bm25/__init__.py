# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to core._bm25. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from '_bm25' is deprecated; use 'core._bm25' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("core._bm25")
_sys.modules[__name__] = _real
for _sub in ("_fallback",):
    _sys.modules[f"_bm25.{_sub}"] = _importlib.import_module(f"core._bm25.{_sub}")
