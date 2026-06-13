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

import difflib
import os
import subprocess
import sys
import threading
import time

# ── ANSI color codes ──────────────────────────────────────────────────────────

_CYAN    = "\033[36m"
_GREEN   = "\033[32m"
_YELLOW  = "\033[33m"
_MAGENTA = "\033[35m"
_WHITE   = "\033[97m"
_RED     = "\033[31m"
_BOLD    = "\033[1m"
_DIM     = "\033[2m"
_RESET   = "\033[0m"

_CLR_LINE = "\r\033[K"      # carriage return + erase line
_CUR_HIDE = "\033[?25l"     # hide cursor
_CUR_SHOW = "\033[?25h"     # show cursor

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


# ── pip/pipx install helpers ──────────────────────────────────────────────────

# Maps extra names to the actual packages they contain. Using real package names
# ensures install works regardless of whether the local editable or PyPI version
# of cognirepo is resolved (self-referential 'cognirepo[extra]' can install wrong version).
_EXTRA_PACKAGES: dict[str, list[str]] = {
    "security": ["keyring>=25.0", "cryptography>=46.0.7"],
    "languages": [
        "tree-sitter-python>=0.23",
        "tree-sitter-javascript>=0.23",
        "tree-sitter-typescript>=0.23",
        "tree-sitter-java>=0.23",
        "tree-sitter-cpp>=0.23",
        "tree-sitter-go>=0.23",
        "tree-sitter-rust>=0.23",
        "tree-sitter-bash>=0.23",
        "tree-sitter-yaml>=0.6",
    ],
}


def _is_pipx() -> bool:
    """Return True if cognirepo is running inside a pipx-managed venv."""
    exe = sys.executable.replace("\\", "/")
    return "pipx/venvs" in exe or "pipx\\venvs" in sys.executable


def _is_externally_managed() -> bool:
    """Return True if system Python is PEP 668 externally managed (Arch, Debian 12+, Ubuntu 24.04+)."""
    import sysconfig  # pylint: disable=import-outside-toplevel
    stdlib = sysconfig.get_path("stdlib")
    if stdlib and os.path.exists(os.path.join(stdlib, "EXTERNALLY-MANAGED")):
        return True
    base = sysconfig.get_config_var("installed_base") or ""
    base_lib = os.path.join(base, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}")
    return os.path.exists(os.path.join(base_lib, "EXTERNALLY-MANAGED"))


def _pipx_inject(*packages: str) -> bool:
    """Try `pipx inject cognirepo <packages>`. Returns True on success."""
    try:
        subprocess.check_call(
            ["pipx", "inject", "cognirepo", *packages, "-q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _pip_install(extra: str) -> bool:
    """Install a cognirepo extra. Prefers pipx inject, falls back to pip."""
    packages = _EXTRA_PACKAGES.get(extra, [f"cognirepo[{extra}]"])

    # pipx-managed env or externally-managed system Python → use pipx inject
    if _is_pipx() or _is_externally_managed():
        if _pipx_inject(*packages):
            return True
        pkg_str = " ".join(packages)
        _warn(f"Auto-install failed. Run manually: pipx inject cognirepo {pkg_str}")
        return False

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", *packages, "-q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _install_package(package: str) -> bool:
    """Install an arbitrary package. Prefers pipx inject, falls back to pip."""
    # pipx-managed env or externally-managed system Python → use pipx inject
    if _is_pipx() or _is_externally_managed():
        if _pipx_inject(package):
            return True
        _warn(f"Auto-install failed. Run manually: pipx inject cognirepo {package}")
        return False

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", package, "-q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# ── multiselect UI ────────────────────────────────────────────────────────────

def _ask_multiselect_fallback(prompt: str, candidates: list) -> list:
    """Numbered fallback for non-TTY environments (CI, pipes)."""
    print(f"\n  {_c(_CYAN, '?')} {prompt}")
    for i, svc in enumerate(candidates, 1):
        star = f"  {_c(_YELLOW, '★ already init')}" if svc.already_init else ""
        print(f"    {_c(_DIM, str(i)+'.')} {_c(_BOLD, svc.name):<22} "
              f"{_c(_CYAN, svc.service_type):<12} {_c(_DIM, svc.lang_hint):<18}{star}")
    print(f"\n  {_c(_DIM, 'Enter numbers separated by commas (e.g. 1,2,3), or Enter for all:')}")
    try:
        raw = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return list(candidates)
    if not raw:
        return list(candidates)
    selected = []
    for token in raw.split(","):
        token = token.strip()
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(candidates):
                selected.append(candidates[idx])
    return selected or list(candidates)


def _ask_multiselect(prompt: str, candidates: list) -> list:
    """
    Arrow-key + space checkbox UI.
    Uses cbreak mode (keeps OPOST on) so \\n stays as \\r\\n — avoids the
    'duplicate lines' bug that tty.setraw() causes by disabling OPOST.
    Falls back to numbered list when stdin/stdout are not a TTY.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return _ask_multiselect_fallback(prompt, candidates)

    try:
        import termios  # pylint: disable=import-outside-toplevel
    except ImportError:
        return _ask_multiselect_fallback(prompt, candidates)

    checked = [True] * len(candidates)
    cursor  = 0
    n       = len(candidates)
    # header + blank + n items + blank + status bar = n + 4
    MENU_LINES = n + 4

    def _row(text: str = "") -> None:
        sys.stdout.write(f"\033[2K\r{text}\n")

    def _render() -> None:
        sys.stdout.write(f"\033[{MENU_LINES}A")
        sel_count = sum(checked)
        _row(f"  {_c(_CYAN, '?')} {_c(_BOLD, prompt)}")
        _row(f"  {_c(_DIM, '↑/↓  move   ·   SPACE toggle   ·   a select-all   ·   d deselect-all   ·   ENTER confirm')}")
        _row()
        for i, svc in enumerate(candidates):
            box   = _c(_GREEN, "✓") if checked[i] else _c(_RED, "✗")
            arrow = _c(_CYAN, _BOLD, "▶") if i == cursor else " "
            star  = f" {_c(_YELLOW, '★ init')}" if svc.already_init else ""
            name  = _c(_BOLD, _WHITE, svc.name) if i == cursor else svc.name
            stype = _c(_MAGENTA, svc.service_type)
            hint  = _c(_DIM, svc.lang_hint)
            bg    = "\033[48;5;235m" if i == cursor else ""
            rst   = _RESET if i == cursor else ""
            _row(f"{bg}  {arrow} [{box}] {name:<22} {stype:<22} {hint:<16}{star}{rst}")
        _row()
        _row(f"  {_c(_DIM, f'{sel_count}/{n} selected')}  "
             f"{_c(_GREEN, '(ENTER to confirm)')}")
        sys.stdout.flush()

    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    # Cbreak-like: raw input (no echo, no canonical), but OPOST kept ON
    # so that \n still does CR+LF and print() works correctly during re-renders.
    new = termios.tcgetattr(fd)
    new[0] = new[0] & ~(termios.BRKINT | termios.ICRNL | termios.INPCK
                        | termios.ISTRIP | termios.IXON)
    # new[1] (OFLAG) intentionally unchanged — OPOST stays enabled
    new[2] = (new[2] & ~termios.CSIZE) | termios.CS8
    new[3] = new[3] & ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG)
    new[6][termios.VMIN]  = 1
    new[6][termios.VTIME] = 0

    sys.stdout.write(_CUR_HIDE)
    sys.stdout.write("\n" * MENU_LINES)
    sys.stdout.flush()

    def _read_key() -> str:
        """Read one logical key (handles multi-byte escape sequences)."""
        ch = sys.stdin.read(1)
        if ch != "\x1b":
            return ch
        ch2 = sys.stdin.read(1)
        if ch2 == "[":
            ch3 = sys.stdin.read(1)
            return f"\x1b[{ch3}"
        return f"\x1b{ch2}"

    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, new)
        _render()
        while True:
            key = _read_key()
            if key in ("\r", "\n"):
                break
            elif key == " ":
                checked[cursor] = not checked[cursor]
            elif key in ("a", "A"):
                checked = [True] * n
            elif key in ("d", "D", "n", "N"):
                checked = [False] * n
            elif key == "\x1b[A":      # up arrow
                cursor = (cursor - 1) % n
            elif key == "\x1b[B":      # down arrow
                cursor = (cursor + 1) % n
            elif key in ("\x03", "\x04"):  # Ctrl-C / Ctrl-D
                raise KeyboardInterrupt
            _render()
    except KeyboardInterrupt:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write(_CUR_SHOW + "\n")
        sys.stdout.flush()
        raise
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write(_CUR_SHOW)
        sys.stdout.flush()

    print()
    result = [svc for svc, sel in zip(candidates, checked) if sel]
    _ok(f"{len(result)} service(s) selected.")
    return result


def _ask_fuzzy_add(root: str, already_shown: list) -> list:
    """Prompt for extra services not in the detected list (fuzzy name match)."""
    from cli.service_detect import detect_sub_repos  # pylint: disable=import-outside-toplevel
    print(f"\n  {_c(_DIM, '+ Add unlisted services (comma-separated names, fuzzy match) or Enter to skip:')}")
    try:
        raw = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return []
    if not raw:
        return []

    shown_names = {s.name for s in already_shown}
    # Re-scan to get all candidates (including those not in shown list)
    all_candidates = {svc.name: svc for svc in detect_sub_repos(root)}
    extras: list = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        matches = difflib.get_close_matches(token, all_candidates.keys(), n=1, cutoff=0.6)
        if matches:
            name = matches[0]
            if name not in shown_names:
                extras.append(all_candidates[name])
                shown_names.add(name)
                _ok(f"Matched '{token}' → {name}")
        else:
            _warn(f"No match for '{token}' — skipped")
    return extras


# ── queue animation ───────────────────────────────────────────────────────────

def _print_queue_bar(names: list[str]) -> None:
    if not names:
        sys.stdout.write(f"  {_c(_DIM, 'Queue: (empty)')}\n")
    else:
        parts = "  ▶  ".join(_c(_CYAN, n) for n in names)
        sys.stdout.write(f"  Queue  ▶  {parts}\n")
    sys.stdout.flush()


def _animate_enqueue(services: list) -> None:
    """Animate pushing each service into the queue with a dot-trail effect."""
    print()
    print(f"  {_c(_CYAN, _BOLD, '╔══════════════════════════════════════════════╗')}")
    print(f"  {_c(_CYAN, _BOLD, '║')}  {_c(_BOLD, 'Microservice Setup Queue')}                   {_c(_CYAN, _BOLD, '║')}")
    print(f"  {_c(_CYAN, _BOLD, '╚══════════════════════════════════════════════╝')}")
    print()
    print(f"  {_c(_DIM, 'Enqueueing services...')}")

    queued: list[str] = []
    sys.stdout.write(_CUR_HIDE)
    try:
        for svc in services:
            label = f"  {_c(_MAGENTA, '↪')}  {_c(_BOLD, svc.name):<20} "
            sys.stdout.write(label)
            sys.stdout.flush()
            dots = "·" * 12
            for i in range(len(dots) + 1):
                sys.stdout.write(f"\r{label}{_c(_DIM, dots[:i])}")
                sys.stdout.flush()
                time.sleep(0.04)
            sys.stdout.write(f"\r{label}{_c(_GREEN, '►')} {_c(_GREEN, '[QUEUED]')}\n")
            sys.stdout.flush()
            queued.append(svc.name)
    finally:
        sys.stdout.write(_CUR_SHOW)
        sys.stdout.flush()

    print()
    _print_queue_bar(queued)
    print()


def _animate_pop(name: str, remaining_names: list[str]) -> None:
    """Show dequeue animation and updated queue bar."""
    sys.stdout.write(_CUR_HIDE)
    try:
        print(f"  {_c(_YELLOW, '◀')} {_c(_BOLD, 'Dequeuing:')} {_c(_CYAN, name)}")
        _print_queue_bar(remaining_names)
        print()
        time.sleep(0.3)
    finally:
        sys.stdout.write(_CUR_SHOW)
        sys.stdout.flush()


def _service_header(name: str, idx: int, total: int) -> None:
    bar = "━" * 50
    print(f"\n  {_c(_DIM, bar)}")
    print(f"  {_c(_CYAN, _BOLD, f'[{idx}/{total}]')} {_c(_BOLD, 'Setting up:')} {_c(_MAGENTA, _BOLD, name)}")
    print(f"  {_c(_DIM, bar)}\n")


def _animate_indexing(name: str, done_event: threading.Event) -> None:
    """
    Pulsing bouncing-block progress bar shown while indexing runs in a thread.
    Exits when done_event is set.
    """
    width   = 30
    pos     = 0
    forward = True
    sys.stdout.write(_CUR_HIDE)
    try:
        while not done_event.is_set():
            bar = [_c(_DIM, "░")] * width
            for j in range(3):
                p = pos + j
                if 0 <= p < width:
                    bar[p] = _c(_CYAN, "█")
            bar_str = "".join(bar)
            sys.stdout.write(f"{_CLR_LINE}  [{bar_str}]  {_c(_DIM, f'Indexing {name}...')}")
            sys.stdout.flush()
            time.sleep(0.06)
            if forward:
                pos += 1
                if pos + 3 >= width:
                    forward = False
            else:
                pos -= 1
                if pos <= 0:
                    forward = True
        sys.stdout.write(f"{_CLR_LINE}  [{_c(_GREEN, '█' * width)}]  {_c(_GREEN, f'✓ {name} indexed')}\n")
        sys.stdout.flush()
    finally:
        sys.stdout.write(_CUR_SHOW)
        sys.stdout.flush()


# ── main wizard entry point ───────────────────────────────────────────────────

def run_wizard() -> dict:
    """
    Run the interactive init wizard. Returns a configuration dict with keys:

      project_name      str   human-readable project label
      encrypt           bool  encrypt episodic at rest
      install_languages bool  install extended tree-sitter language parsers
      mcp_targets       list  subset of ["claude", "gemini", "cursor", "vscode"]
      org               str | None  organization name
      project           str | None  project within org
      child_repos       list[ServiceCandidate]  detected microservices to set up
      orchestrator_mode bool  True if child_repos is non-empty

    Vector storage is fixed: FAISS for AST indexing, ChromaDB for semantic text.
    """
    # Microservice detection deferred until user opts in (step 8).
    _candidates: list = []
    STEPS = 8

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

    # ── 2. Encryption ─────────────────────────────────────────────────────────
    _section(2, STEPS, "Storage",
             "Encryption uses Fernet AES-128 (key in OS keychain).\n"
             "  Vector storage is fixed: FAISS for AST indexing, ChromaDB for semantic text.")
    cfg["encrypt"] = _ask_yn("Enable encryption at rest?", default=False)
    if cfg["encrypt"]:
        print(f"  {_c(_DIM, '  Installing cognirepo[security] ...')}", end="", flush=True)
        if _pip_install("security"):
            _ok("cognirepo[security] installed")
        else:
            _warn("Install failed — run: pip install cognirepo[security]")

    # Install chromadb automatically (always needed for semantic store)
    print(f"  {_c(_DIM, '  Installing chromadb (semantic text store) ...')}", end="", flush=True)
    if _install_package("chromadb"):
        _ok("chromadb installed")
    else:
        _warn("chromadb install failed — run: pip install chromadb")

    # ── 3. Behaviour tracking opt-in ─────────────────────────────────────────
    _section(3, STEPS, "Behaviour profiling",
             "Tracks query patterns to personalise AI agent responses over time.")
    cfg["behaviour_tracking"] = _ask_yn(
        "Enable user behaviour profiling? (opt-in)",
        default=False,
    )
    if cfg["behaviour_tracking"]:
        print(f"  {_c(_DIM, '  Stored in .cognirepo/graph/behaviour.json')}")
        if cfg.get("encrypt"):
            print(f"  {_c(_DIM, '  Will be encrypted (encryption is on).')}")
        print(f"  {_c(_DIM, '  Disable anytime: set behaviour_tracking=false in .cognirepo/config.json')}")

    # ── 4. Language support ───────────────────────────────────────────────────
    _section(4, STEPS, "Extended language support",  # noqa: E501
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

    # ── 5. AI tool MCP integration ────────────────────────────────────────────
    _section(5, STEPS, "AI tool MCP integration",
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

    cfg["mcp_global"] = False  # always project-scoped; global registration removed

    # ── 6. Cross-agent context handoff ───────────────────────────────────────
    _section(6, STEPS, "Cross-agent context handoff",
             "Share last session context between Claude, Gemini, and Cursor automatically.")
    cfg["autosave_context"] = _ask_yn(
        "Enable cross-agent context handoff? (saves last query context to ~/.cognirepo/<repo>/)",
        default=True,
    )
    if cfg["autosave_context"]:
        print(f"  {_c(_DIM, '  Each context_pack call writes a snapshot other agents can read.')}")
    else:
        print(f"  {_c(_DIM, '  Sessions stay isolated. Enable later: set autosave_context=true in config.json')}")

    # ── 7. Organization + Project ─────────────────────────────────────────────
    _section(7, STEPS, "Organisation & Project",
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

    # ── 8. Microservice detection (opt-in) ───────────────────────────────────
    _section(8, STEPS, "Microservice architecture",
             "Does this repo contain or orchestrate multiple microservices?")
    _is_microservice_repo = _ask_yn(
        "Is this repo part of a microservice architecture?", default=False
    )
    if _is_microservice_repo:
        from cli.service_detect import detect_sub_repos  # pylint: disable=import-outside-toplevel
        _candidates = detect_sub_repos(os.getcwd())
        if _candidates:
            print(f"\n  {_c(_GREEN, '✓')}  Found {len(_candidates)} sub-repo(s) that look like services.\n")
            selected = _ask_multiselect("Select microservices to set up:", _candidates)
            extra    = _ask_fuzzy_add(os.getcwd(), already_shown=_candidates)
            selected += [s for s in extra if s not in selected]
            selected_paths = {svc.path for svc in selected}
            cfg["child_repos"]       = selected
            cfg["rejected_repos"]    = [svc for svc in _candidates if svc.path not in selected_paths]
            cfg["orchestrator_mode"] = bool(selected)
        else:
            _warn("No microservice sub-repos detected automatically.")
            print(f"  {_c(_DIM, 'You can register them later with: cognirepo init --parent-repo <path>')}")
            cfg["child_repos"]       = []
            cfg["rejected_repos"]    = []
            cfg["orchestrator_mode"] = False
    else:
        cfg["child_repos"]       = []
        cfg["rejected_repos"]    = []
        cfg["orchestrator_mode"] = False

    # ── Confirmation summary ──────────────────────────────────────────────────
    _child_names = [s.name for s in cfg.get("child_repos", [])]
    _summary_rows = [
        ("Project",         cfg["project_name"]),
        ("Encryption",      "yes" if cfg["encrypt"] else "no"),
        ("Behaviour",       "enabled" if cfg.get("behaviour_tracking") else "disabled"),
        ("Context handoff", "yes" if cfg.get("autosave_context", True) else "no"),
        ("AST indexing",    "FAISS"),
        ("Semantic text",   "ChromaDB"),
        ("Languages",       "extended" if cfg["install_languages"] else "Python only"),
        ("MCP targets",     ", ".join(cfg["mcp_targets"]) or "none"),
        ("MCP scope",       "project-only"),
        ("Organisation",    cfg["org"] or "none"),
        ("Project",         cfg["project"] or "none"),
        ("Sub-repos",       f"{len(_child_names)} service(s)" if _child_names else "none detected"),
        ("Services",        ", ".join(_child_names) if _child_names else "—"),
        ("Parent mode",     "orchestrator (docs only)" if cfg.get("orchestrator_mode") else "standard"),
    ]

    print()
    try:
        from rich.console import Console   # pylint: disable=import-outside-toplevel
        from rich.table import Table       # pylint: disable=import-outside-toplevel
        from rich import box as rbox       # pylint: disable=import-outside-toplevel
        _con = Console()
        _tbl = Table(
            title="Configuration Summary",
            box=rbox.ROUNDED,
            show_header=False,
            padding=(0, 1),
            title_style="bold cyan",
            border_style="cyan",
        )
        _tbl.add_column("Setting", style="dim", min_width=18)
        _tbl.add_column("Value",   style="white")
        for label, value in _summary_rows:
            _tbl.add_row(label, value)
        _con.print(_tbl)
    except ImportError:
        # Fallback: plain ASCII box with truncated values
        _W_LABEL = 16
        _W_VALUE = 34
        _INNER   = _W_LABEL + _W_VALUE + 6
        _sep     = "─" * _INNER
        print(f"  ┌{_sep}┐")
        print(f"  │  {_c(_GREEN, _BOLD, 'Configuration Summary'):<{_INNER - 2}}  │")
        print(f"  ├{_sep}┤")
        for label, value in _summary_rows:
            val_trunc = value[:_W_VALUE] if len(value) > _W_VALUE else value
            print(f"  │  {label:<{_W_LABEL}}  {val_trunc:<{_W_VALUE}}  │")
        print(f"  └{_sep}┘")
    print()

    if not _ask_yn("Proceed with this configuration?", default=True):
        print(f"\n  {_c(_YELLOW, 'Restarting wizard...')}\n")
        import time  # pylint: disable=import-outside-toplevel
        time.sleep(0.8)
        os.system("clear")
        return None  # caller loops

    return cfg
