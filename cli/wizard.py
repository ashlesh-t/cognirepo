# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

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
      encrypt           bool  encrypt FAISS + episodic at rest
      vector_backend    str   "faiss" | "chroma"
      install_languages bool  install extended tree-sitter language parsers
      mcp_targets       list  subset of ["claude", "gemini", "cursor", "vscode"]
      mcp_global        bool  register MCP server globally
      org               str | None  organization name
      project           str | None  project within org
    """
    STEPS = 5

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
             "Used to namespace data in global AI tool configs (Claude, Gemini, Cursor).")
    cfg["project_name"] = _ask_text(
        "Project name", default=os.path.basename(os.getcwd())
    )

    # ── 2. Encryption + vector backend ───────────────────────────────────────
    _section(2, STEPS, "Storage",
             "Encryption uses Fernet AES-128 (key in OS keychain). ChromaDB optional.")
    cfg["encrypt"] = _ask_yn("Enable encryption at rest?", default=False)
    if cfg["encrypt"]:
        print(f"  {_c(_DIM, '  Installing cognirepo[security] ...')}", end="", flush=True)
        if _pip_install("security"):
            _ok("cognirepo[security] installed")
        else:
            _warn("Install failed — run: pip install cognirepo[security]")

    vb_idx = _ask_choice(
        "Vector backend:",
        ["FAISS  (local, no extra install)", "ChromaDB  (persistent client, richer metadata)"],
        descriptions=[
            "Default — fast, zero config",
            "Run: pip install chromadb",
        ],
        default=0,
    )
    cfg["vector_backend"] = "faiss" if vb_idx == 0 else "chroma"
    if cfg["vector_backend"] == "chroma":
        print(f"  {_c(_DIM, '  Installing chromadb ...')}", end="", flush=True)
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "chromadb", "-q"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _ok("chromadb installed")
        except (subprocess.CalledProcessError, FileNotFoundError):
            _warn("Install failed — run: pip install chromadb")

    # ── 3. Language support ───────────────────────────────────────────────────
    _section(3, STEPS, "Extended language support",
             "Adds tree-sitter parsers for JS/TS, Java, Go, Rust, C/C++.")
    cfg["install_languages"] = _ask_yn(
        "Install extended language parsers?", default=False
    )
    if cfg["install_languages"]:
        print(f"  {_c(_DIM, '  Installing cognirepo[languages] ...')}", end="", flush=True)
        if _pip_install("languages"):
            _ok("cognirepo[languages] installed")
        else:
            _warn("Install failed — run: pip install cognirepo[languages]")

    # ── 4. AI tool MCP integration ────────────────────────────────────────────
    _section(4, STEPS, "AI tool MCP integration",
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

    # ── 5. Organization + Project ─────────────────────────────────────────────
    _section(5, STEPS, "Organisation & Project",
             "Group repos for cross-repo knowledge sharing.")
    from config.orgs import list_orgs, list_projects, create_project  # pylint: disable=import-outside-toplevel
    orgs = list_orgs()
    org_choices = ["None / Personal project"]
    org_choices.extend(list(orgs.keys()))
    org_choices.append("Create new organization...")

    org_idx = _ask_choice("Join organization:", org_choices, default=0)

    cfg["org"] = None
    cfg["project"] = None

    if org_idx == 0:
        pass  # no org
    elif org_idx == len(org_choices) - 1:
        new_org = _ask_text("New organization name", default="")
        if new_org:
            cfg["org"] = new_org
    else:
        cfg["org"] = org_choices[org_idx]

    if cfg["org"]:
        want_project = _ask_yn("Link to a project within this org?", default=True)
        if want_project:
            existing = list_projects(cfg["org"])
            proj_choices = list(existing.keys()) + ["Create new project..."]
            if len(proj_choices) > 1:
                proj_idx = _ask_choice("Select project:", proj_choices, default=0)
                if proj_idx == len(proj_choices) - 1:
                    proj_name = _ask_text("Project name", default="main")
                    proj_desc = _ask_text("Description (optional)", default="")
                    if proj_name:
                        create_project(cfg["org"], proj_name, proj_desc)
                        cfg["project"] = proj_name
                else:
                    cfg["project"] = proj_choices[proj_idx]
            else:
                proj_name = _ask_text("Project name", default="main")
                proj_desc = _ask_text("Description (optional)", default="")
                if proj_name:
                    create_project(cfg["org"], proj_name, proj_desc)
                    cfg["project"] = proj_name

    # ── Confirmation summary ──────────────────────────────────────────────────
    _INNER = 49
    _sep = "─" * _INNER

    def _box_title(text: str) -> str:
        colored = _c(_GREEN, _BOLD, text)
        padding = " " * (_INNER - 2 - len(text) - 2)
        return f"  │  {colored}{padding}  │"

    print()
    print(f"  ┌{_sep}┐")
    print(_box_title("Configuration Summary"))
    print(f"  ├{_sep}┤")
    rows = [
        ("Project",       cfg["project_name"]),
        ("Encryption",    "yes" if cfg["encrypt"] else "no"),
        ("Vector backend", cfg["vector_backend"]),
        ("Languages",     "extended" if cfg["install_languages"] else "Python only"),
        ("MCP targets",   ", ".join(cfg["mcp_targets"]) or "none"),
        ("MCP scope",     "global" if cfg.get("mcp_global") else "project-only"),
        ("Organisation",  cfg["org"] or "none"),
        ("Project",       cfg["project"] or "none"),
    ]
    for label, value in rows:
        print(f"  │  {label:<14}  {value:<29}  │")
    print(f"  └{_sep}┘")
    print()

    if not _ask_yn("Proceed with this configuration?", default=True):
        print(f"\n  {_c(_YELLOW, 'Init cancelled. Run cognirepo init again to retry.')}\n")
        sys.exit(0)

    return cfg
