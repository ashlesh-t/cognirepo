# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to intelligence.retrieval. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'retrieval' is deprecated; use 'intelligence.retrieval' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("intelligence.retrieval")
_sys.modules[__name__] = _real
for _sub in (
    "cross_repo", "docs_search", "hybrid", "query_enhancer",
):
    _sys.modules[f"retrieval.{_sub}"] = _importlib.import_module(f"intelligence.retrieval.{_sub}")
