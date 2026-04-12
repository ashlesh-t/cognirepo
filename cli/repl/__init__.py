# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""CogniRepo interactive REPL package."""
# Expose submodules so 'from cli.repl.X import Y' resolves cleanly under pylint.
from cli.repl import ui as ui  # noqa: F401
from cli.repl import commands as commands  # noqa: F401
from cli.repl import agents_panel as agents_panel  # noqa: F401
from cli.repl.shell import run_repl

__all__ = ["run_repl", "ui", "commands", "agents_panel"]
