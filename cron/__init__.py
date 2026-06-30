# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to ops.cron. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'cron' is deprecated; use 'ops.cron' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("ops.cron")
_sys.modules[__name__] = _real
for _sub in ("prune_memory", "scheduler"):
    _sys.modules[f"cron.{_sub}"] = _importlib.import_module(f"ops.cron.{_sub}")
