# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to intelligence.indexer. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'indexer' is deprecated; use 'intelligence.indexer' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("intelligence.indexer")
_sys.modules[__name__] = _real
for _sub in (
    "ast_indexer", "doc_ingester", "docs_index", "endpoint_scanner",
    "file_watcher", "http_call_scanner", "index_utils", "inter_repo_indexer",
    "language_registry", "on_demand", "summarizer",
):
    _sys.modules[f"indexer.{_sub}"] = _importlib.import_module(f"intelligence.indexer.{_sub}")
