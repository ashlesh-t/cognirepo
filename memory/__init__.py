# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to data.memory. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'memory' is deprecated; use 'data.memory' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("data.memory")
_sys.modules[__name__] = _real
for _sub in (
    "auto_store", "circuit_breaker", "cleanup_queue", "embeddings",
    "episodic_memory", "learning_store", "project_memory",
    "semantic_memory", "user_memory",
):
    _sys.modules[f"memory.{_sub}"] = _importlib.import_module(f"data.memory.{_sub}")
