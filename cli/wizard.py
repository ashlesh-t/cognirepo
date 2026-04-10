# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Interactive terminal wizard for `cognirepo init`.

Inspired by powerlevel10k-style guided configuration prompts.
Uses ANSI escape codes + box-drawing characters.
No external dependencies required.
"""
from __future__ import annotations

import os
import subprocess
import sys

# ── ANSI color codes ──────────────────────────────────────────────────────────

_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_RESET  = "\033[0m"

_USE_COLOR: bool = bool(
    hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    and os.environ.get("TERM", "xterm") != "dumb"
    and os.environ.get("NO_COLOR") is None
)


def _c(first_code: str, *rest: str) -> str:
    """
    Apply ANSI codes to the last argument (the text).

    _c(_CYAN, "hello")              → cyan hello
    _c(_CYAN, _BOLD, "hello")       → cyan+bold hello
    When color is disabled, returns the last argument unchanged.
    """
    if not _USE_COLOR:
        return rest[-1]
    codes = first_code + "".join(rest[:-1])
    return f"{codes}{rest[-1]}{_RESET}"


def _ok(msg: str) -> None:
    print(f"    {_c(_GREEN, '✓')}  {msg}")


def _warn(msg: str) -> None:
    print(f"    {_c(_YELLOW, '!')}  {msg}")


# ── prompt primitives ─────────────────────────────────────────────────────────

def _ask_yn(prompt: str, default: bool = True) -> bool:
    """Yes/No prompt. Enter key accepts *default*."""
    hint = _c(_DIM, "(Y/n)" if default else "(y/N)")
    while True:
        try:
            raw = input(f"  {_c(_CYAN, '?')} {prompt} {hint}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        _warn("Please enter y or n.")


def _ask_text(prompt: str, default: str) -> str:
    """Free-text prompt with a default value."""
    try:
        raw = input(
            f"  {_c(_CYAN, '?')} {prompt} {_c(_DIM, f'[{default}]')}: "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return raw if raw else default


def _ask_choice(
    prompt: str,
    choices: list[str],
    descriptions: list[str] | None = None,
    default: int = 0,
) -> int:
    """
    Numbered single-select menu.  Returns 0-based index of the chosen item.
    """
    print(f"\n  {_c(_CYAN, '?')} {prompt}")
    for i, choice in enumerate(choices):
        num = _c(_GREEN, f"({i + 1})") if i == default else f"({i + 1})"
        desc = ""
        if descriptions and i < len(descriptions) and descriptions[i]:
            desc = f"  {_c(_DIM, descriptions[i])}"
        dflt_marker = "  " + _c(_DIM, "← default") if i == default else ""
        print(f"      {num} {choice}{desc}{dflt_marker}")
    while True:
        try:
            raw = input(
                f"\n  {_c(_DIM, f'Enter 1–{len(choices)} [default {default + 1}]')}: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if raw == "":
            return default
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return idx
        except ValueError:
            pass
        _warn(f"Please enter a number between 1 and {len(choices)}.")


# ── section header ────────────────────────────────────────────────────────────

def _section(step: int, total: int, title: str, subtitle: str = "") -> None:
    bar = "─" * 50
    print(f"\n  {bar}")
    print(f"  {_c(_CYAN, _BOLD, f'[{step}/{total}]')} {_c(_BOLD, title)}")
    if subtitle:
        print(f"  {_c(_DIM, subtitle)}")


# ── pip install helper ────────────────────────────────────────────────────────

def _pip_install(extra: str) -> bool:
    """Install ``cognirepo[extra]`` silently. Returns True on success."""
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", f"cognirepo[{extra}]", "-q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# ── main wizard entry point ───────────────────────────────────────────────────

def run_wizard() -> dict:
    """
    Run the interactive init wizard. Returns a configuration dict with keys:

      project_name      str   human-readable project label
      password          str   initial API password
      port              int   local REST API port
      multi_model       bool  enable multi-model routing
      lazy_grpc         bool  auto-start gRPC server on demand
      redis             bool  use Redis for session caching
      encrypt           bool  encrypt FAISS + episodic at rest
      install_languages bool  install extended tree-sitter language parsers
      mcp_targets       list  subset of ["claude", "gemini"]
    """
    STEPS = 7

    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print(f"  ║  {_c(_CYAN, _BOLD, 'CogniRepo Init Wizard')}                               ║")
    print("  ║  Cognitive infrastructure for your AI agents        ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()
    print(f"  {_c(_DIM, 'Press Enter to accept the bracketed defaults.')}")
    print(f"  {_c(_DIM, 'Settings are saved to .cognirepo/config.json.')}")

    cfg: dict = {}

    # ── 1. Project name ───────────────────────────────────────────────────────
    _section(1, STEPS, "Project name",
             "Used to namespace data in global AI tool configs (Claude, Gemini).")
    cfg["project_name"] = _ask_text(
        "Project name", default=os.path.basename(os.getcwd())
    )

    # ── 2. Multi-model routing ────────────────────────────────────────────────
    _section(2, STEPS, "Multi-model routing",
             "QUICK/FAST → Grok, BALANCED → Gemini, DEEP → Claude by default.")
    cfg["multi_model"] = _ask_yn("Enable multi-model routing?", default=True)

    cfg["lazy_grpc"] = False
    if cfg["multi_model"]:
        print(f"\n  {_c(_DIM, 'gRPC lets DEEP queries delegate fast sub-lookups to lighter models.')}")
        cfg["lazy_grpc"] = _ask_yn(
            "Auto-start gRPC server lazily (on first DEEP query)?", default=True
        )

    # ── 3. Redis caching ──────────────────────────────────────────────────────
    _section(3, STEPS, "Session caching",
             "Redis caches query context for faster repeated access (requires Redis).")
    cfg["redis"] = _ask_yn("Enable Redis session cache?", default=False)
    if cfg["redis"]:
        print(f"  {_c(_DIM, '  Verify Redis is running: redis-cli ping → PONG')}")

    # ── 4. Encryption at rest ─────────────────────────────────────────────────
    _section(4, STEPS, "Encryption at rest",
             "Fernet AES-128 for the FAISS index + episodic log. Key in OS keychain.")
    cfg["encrypt"] = _ask_yn("Enable encryption at rest?", default=False)
    if cfg["encrypt"]:
        print(f"  {_c(_DIM, '  Installing cognirepo[security] ...')}", end="", flush=True)
        if _pip_install("security"):
            _ok("cognirepo[security] installed")
        else:
            _warn("Install failed — run: pip install cognirepo[security]")

    # ── 5. Language support ───────────────────────────────────────────────────
    _section(5, STEPS, "Extended language support",
             "Adds tree-sitter parsers for JS/TS, Java, Go, Rust, C/C++ etc.")
    cfg["install_languages"] = _ask_yn(
        "Install extended language parsers?", default=False
    )
    if cfg["install_languages"]:
        print(f"  {_c(_DIM, '  Installing cognirepo[languages] ...')}", end="", flush=True)
        if _pip_install("languages"):
            _ok("cognirepo[languages] installed")
        else:
            _warn("Install failed — run: pip install cognirepo[languages]")

    # ── 6. AI tool MCP integration ────────────────────────────────────────────
    _section(6, STEPS, "AI tool MCP integration",
             "Wire CogniRepo memory + code search into Claude / Gemini / Cursor / VS Code.")
    mcp_idx = _ask_choice(
        "Set up MCP server for:",
        [
            "Claude  (Claude Code CLI + Claude Desktop)",
            "Gemini  (Gemini CLI)",
            "Cursor  (Cursor IDE)",
            "VS Code / GitHub Copilot",
            "All of the above",
            "Claude + Gemini",
            "Skip — configure later with: cognirepo mcp-setup",
        ],
        descriptions=[
            "Writes .claude/CLAUDE.md and .claude/settings.json",
            "Writes .gemini/COGNIREPO.md and .gemini/settings.json",
            "Writes .cursor/mcp.json",
            "Writes .vscode/mcp.json",
            "Configures all four AI tools",
            "Configures both Claude and Gemini",
            "",
        ],
        default=0,
    )
    _all_tools = ["claude", "gemini", "cursor", "vscode"]
    mcp_map = {
        0: ["claude"],
        1: ["gemini"],
        2: ["cursor"],
        3: ["vscode"],
        4: _all_tools,
        5: ["claude", "gemini"],
        6: [],
    }
    cfg["mcp_targets"] = mcp_map[mcp_idx]

    cfg["mcp_global"] = False
    if cfg["mcp_targets"]:
        print(
            f"\n  {_c(_DIM, 'Global: registers in ~/.claude.json / ~/.gemini/settings.json')}"
        )
        print(
            f"  {_c(_DIM, 'so the server appears in every session, not just this project.')}"
        )
        cfg["mcp_global"] = _ask_yn(
            "Register globally (available in all sessions)?", default=True
        )

    # ── 7. REST API ───────────────────────────────────────────────────────────
    _section(7, STEPS, "REST API settings",
             "Local FastAPI server — needed only for --via-api mode or REST clients.")
    cfg["port"] = int(_ask_text("API port", default="8000"))
    cfg["password"] = _ask_text("API password", default="changeme")  # nosec B106

    # ── Confirmation summary ──────────────────────────────────────────────────
    # Inner width = 2 (pad) + 14 (label) + 2 (gap) + 29 (value) + 2 (pad) = 49
    _INNER = 49
    _sep = "─" * _INNER

    def _box_title(text: str) -> str:
        """Return a box title row with correct visible-width padding."""
        colored = _c(_GREEN, _BOLD, text)
        # Pad based on visible (plain) length, not colored string length
        padding = " " * (_INNER - 2 - len(text) - 2)
        return f"  │  {colored}{padding}  │"

    print()
    print(f"  ┌{_sep}┐")
    print(_box_title("Configuration Summary"))
    print(f"  ├{_sep}┤")
    rows = [
        ("Project",      cfg["project_name"]),
        ("Multi-model",  "yes" if cfg["multi_model"] else "no"),
        ("Lazy gRPC",    "yes" if cfg["lazy_grpc"] else "no"),
        ("Redis cache",  "yes" if cfg["redis"] else "no"),
        ("Encryption",   "yes" if cfg["encrypt"] else "no"),
        ("Languages",    "extended" if cfg["install_languages"] else "Python only"),
        ("MCP targets",  ", ".join(cfg["mcp_targets"]) or "none"),
        ("MCP scope",    "global" if cfg.get("mcp_global") else "project-only"),
        ("API port",     str(cfg["port"])),
    ]
    for label, value in rows:
        print(f"  │  {label:<14}  {value:<29}  │")
    print(f"  └{_sep}┘")
    print()

    if not _ask_yn("Proceed with this configuration?", default=True):
        print(f"\n  {_c(_YELLOW, 'Init cancelled. Run cognirepo init again to retry.')}\n")
        sys.exit(0)

    return cfg
