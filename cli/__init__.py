# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — package moved to interface.cli. Removed in v2.0."""
import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "Importing from 'cli' is deprecated; use 'interface.cli' instead.",
    DeprecationWarning,
    stacklevel=2,
)
_real = _importlib.import_module("interface.cli")
_sys.modules[__name__] = _real
for _sub in (
    "cli_config", "daemon", "docs_index", "env_wizard", "init_project",
    "key_probes", "main", "metrics_server", "migrate_config",
    "seed", "service_detect", "wizard",
):
    _sys.modules[f"cli.{_sub}"] = _importlib.import_module(f"interface.cli.{_sub}")
