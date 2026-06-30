# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to core.config. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'config' is deprecated; use 'core.config' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("core.config")
_sys.modules[__name__] = _real
for _sub in ("lock", "logging", "orgs", "paths", "version"):
    _sys.modules[f"config.{_sub}"] = _importlib.import_module(f"core.config.{_sub}")
