# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

try:
    from importlib.metadata import version as _pkg_version
    __version__: str = _pkg_version("cognirepo")
except Exception:  # package not installed (editable dev install edge case)
    __version__ = "0.3.0"
