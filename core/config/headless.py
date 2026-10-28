# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Recursion guard for headless agent calls (#87/#88).

When CogniRepo's router uses an installed agent CLI as a completion backend, it runs the CLI with
``COGNIREPO_HEADLESS=1`` in the child's environment. That agent may still find a CogniRepo MCP server or a
CogniRepo hook in its *user-level* config (CogniRepo registers itself there), which would make CogniRepo call an
agent that calls CogniRepo. Every CogniRepo entry point an agent can reach (``serve``, the MCP server, the
prompt-submit hook) checks :func:`is_headless` first and does nothing, whatever isolation flags the CLI honoured.
"""
from __future__ import annotations

import os

ENV_VAR = "COGNIREPO_HEADLESS"
_FALSE = ("", "0", "false", "off", "no")


def is_headless() -> bool:
    """True when this process was started by CogniRepo's own headless agent adapter."""
    return os.environ.get(ENV_VAR, "").strip().lower() not in _FALSE
