# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to intelligence.orchestrator. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'orchestrator' is deprecated; use 'intelligence.orchestrator' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("intelligence.orchestrator")
_sys.modules[__name__] = _real
for _sub in ("classifier", "context_builder", "router", "session"):
    _sys.modules[f"orchestrator.{_sub}"] = _importlib.import_module(f"intelligence.orchestrator.{_sub}")
for _sub in (
    "anthropic_adapter", "errors", "gemini_adapter", "grok_adapter",
    "local_adapter", "openai_adapter", "retry",
):
    _sys.modules[f"orchestrator.model_adapters.{_sub}"] = _importlib.import_module(
        f"intelligence.orchestrator.model_adapters.{_sub}"
    )
