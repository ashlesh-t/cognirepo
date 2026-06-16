# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

try:
    from importlib.metadata import version as _pkg_version
    __version__: str = _pkg_version("cognirepo")
except Exception:  # package not installed — fall back to version.yml
    try:
        from config.version import __version__ as _v  # type: ignore[import-untyped]
        __version__ = _v
    except Exception:
        __version__ = "1.1.3"
