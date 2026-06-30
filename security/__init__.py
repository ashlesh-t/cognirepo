# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to core.security. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'security' is deprecated; use 'core.security' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("core.security")
_sys.modules[__name__] = _real
for _sub in ("encryption",):
    _sys.modules[f"security.{_sub}"] = _importlib.import_module(f"core.security.{_sub}")
