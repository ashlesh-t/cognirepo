# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to interface.adapters. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'adapters' is deprecated; use 'interface.adapters' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("interface.adapters")
_sys.modules[__name__] = _real
for _sub in ("openai_spec",):
    _sys.modules[f"adapters.{_sub}"] = _importlib.import_module(f"interface.adapters.{_sub}")
