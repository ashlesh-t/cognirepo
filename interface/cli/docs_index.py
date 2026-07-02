# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Backward-compat shim — moved to intelligence.indexer.docs_index. Removed in v2.0."""
import warnings as _warnings

_warnings.warn(
    "cli.docs_index is deprecated; use intelligence.indexer.docs_index instead.",
    DeprecationWarning,
    stacklevel=2,
)
from intelligence.indexer.docs_index import *  # noqa: F401,F403,E402
