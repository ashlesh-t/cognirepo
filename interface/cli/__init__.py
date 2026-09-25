# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

try:
    from core.config.version import __version__ as __version__  # single source: version.yml
except Exception:  # pylint: disable=broad-except
    try:
        from importlib.metadata import version as _pkg_version
        __version__: str = _pkg_version("cognirepo")
    except Exception:  # pylint: disable=broad-except
        __version__ = "0.0.0+unknown"
