# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Local-only control API + console host (`cognirepo ui`). See docs/UI_API.md."""

import importlib.util

UI_INSTALL_HINT = ("pip install 'cognirepo[ui]'"
                   "\n  (installed with pipx? run: pipx inject cognirepo 'cognirepo[ui]')")
_UI_MODULES = ("fastapi", "uvicorn")


def ui_extra_missing() -> list[str]:
    """Names of the ``[ui]`` extra's modules that are not installed (empty when ready)."""
    return [m for m in _UI_MODULES if importlib.util.find_spec(m) is None]
