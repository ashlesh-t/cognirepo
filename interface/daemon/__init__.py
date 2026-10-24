# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""``cognirepod`` — the optional per-user daemon (#116, ADR 003).

A *supervisor* owns a Unix socket and hands out per-repo *workers*; a worker is the normal server code with its
repo fixed, serving many agent sessions over its own socket. ``cognirepo serve`` becomes a thin MCP proxy to the
worker when ``daemon.enabled`` is on, and falls back to the in-process server on any failure. POSIX only for now.
"""
