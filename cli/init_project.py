# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Module to initialize the cognirepo project structure.

Interactive mode (default): runs the terminal wizard (cli.wizard.run_wizard)
and asks the user about multi-model, encryption, Redis, and MCP targets.

Non-interactive mode (--no-index / scripting): skips wizard, uses CLI flags.
"""
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

try:
    import keyring  # pylint: disable=import-error
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False

from config.paths import get_path

_KEYCHAIN_SERVICE = "cognirepo"

# Blanket ignore — nothing under .cognirepo/ ever reaches git.
GITIGNORE_CONTENT = "*\n!.gitignore\n"

DEFAULT_MODEL = {"provider": "auto", "model": "auto"}

# Path to the bundled MCP prompt templates (relative to this file)
_STD_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "STD_PROMPTS")


# ── internal helpers ──────────────────────────────────────────────────────────

def _write_gitignore() -> None:
    """Write (or overwrite) .cognirepo/.gitignore with the blanket pattern."""
    with open(get_path(".gitignore"), "w", encoding="utf-8") as f:
        f.write(GITIGNORE_CONTENT)


def _scaffold_dirs() -> None:
    os.makedirs(get_path("memory"), exist_ok=True)
    os.makedirs(get_path("docs"), exist_ok=True)
    os.makedirs(get_path("index"), exist_ok=True)
    os.makedirs(get_path("graph"), exist_ok=True)
    os.makedirs(get_path("errors"), exist_ok=True)
    os.makedirs(get_path("vector_db"), exist_ok=True)
    os.makedirs(get_path("episodic"), exist_ok=True)


def _init_empty_stores() -> None:
    """
    Create empty FAISS index and episodic log on first init so `doctor`
    does not report false failures immediately after `cognirepo init`.
    """
    # Empty FAISS index
    idx_file = get_path("vector_db/semantic.index")
    if not os.path.exists(idx_file):
        try:
            import faiss  # pylint: disable=import-outside-toplevel
            _idx = faiss.IndexFlatL2(384)
            faiss.write_index(_idx, idx_file)
        except Exception:  # pylint: disable=broad-except
            pass  # faiss not installed — skip; doctor will show clear hint

    # Empty episodic log
    ep_file = get_path("memory/episodic.json")
    if not os.path.exists(ep_file):
        try:
            with open(ep_file, "w", encoding="utf-8") as f:
                f.write("[]")
        except Exception:  # pylint: disable=broad-except
            pass


def _write_config(
    project_name: str = "",
    org: str | None = None,
    project: str | None = None,
    encrypt: bool = False,
    vector_backend: str = "faiss",
    autosave_context: bool = True,
) -> str:
    """
    Write config.json (new) or backfill missing keys (existing).
    Returns the project_id (new or existing).
    """
    if not os.path.exists(get_path("config.json")):
        project_id = str(uuid.uuid4())

        config: dict = {
            "project_id":   project_id,
            "project_name": project_name or os.path.basename(os.getcwd()),
            "org":          org,
            "project":      project,
            "storage":      {"encrypt": encrypt, "vector_backend": vector_backend},
            "retrieval_weights": {"vector": 0.5, "graph": 0.3, "behaviour": 0.2},
            "model":        DEFAULT_MODEL,
            "autosave_context": autosave_context,
        }

        with open(get_path("config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"Created {get_path('config.json')}")
        return project_id

    # ── existing config — backfill missing keys ───────────────────────────────
    with open(get_path("config.json"), "r", encoding="utf-8") as f:
        config = json.load(f)

    changed = False
    defaults: list[tuple] = [
        ("project_id",    str(uuid.uuid4())),
        ("project_name",  project_name or os.path.basename(os.getcwd())),
        ("retrieval_weights", {"vector": 0.5, "graph": 0.3, "behaviour": 0.2}),
        ("model",         DEFAULT_MODEL),
        ("autosave_context", True),
        ("project",       None),
    ]
    for key, val in defaults:
        if key not in config:
            config[key] = val
            changed = True

    # Remove phantom keys from old installs
    for old_key in ("api_port", "api_url", "multi_model", "models"):
        if old_key in config:
            del config[old_key]
            changed = True

    # Always apply user-specified wizard settings
    storage = config.setdefault("storage", {})
    if storage.get("encrypt") != encrypt:
        storage["encrypt"] = encrypt
        changed = True
    if storage.get("vector_backend") != vector_backend:
        storage["vector_backend"] = vector_backend
        changed = True

    if config.get("autosave_context") != autosave_context:
        config["autosave_context"] = autosave_context
        changed = True
    if config.get("org") != org:
        config["org"] = org
        changed = True
    if project is not None and config.get("project") != project:
        config["project"] = project
        changed = True

    if changed:
        with open(get_path("config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"Updated {get_path('config.json')} with missing keys.")
    else:
        print(f"{get_path('config.json')} already up to date.")

    return config["project_id"]


# ── MCP configuration generator ───────────────────────────────────────────────

def _load_template(template_name: str) -> str:
    """Load a template from STD_PROMPTS/. Returns empty string if not found."""
    path = os.path.join(_STD_PROMPTS_DIR, template_name)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, FileNotFoundError):
        return ""


def _render_template(template: str, project_name: str, project_path: str) -> str:
    """Substitute {project_name} and {project_path} placeholders."""
    return template.replace("{project_name}", project_name).replace(
        "{project_path}", project_path
    )


def setup_mcp(
    targets: list[str],
    project_name: str,
    project_path: str,
    global_scope: bool = False,
) -> None:
    """
    Generate MCP config files for the requested AI tools.

    targets      : list containing any of "claude", "gemini", "cursor", "vscode"
    project_name : human-readable project label
    project_path : absolute path to the project root
    global_scope : also register in the user-level global config so the server
                   is available in every session, not just this project
    """
    if not targets:
        return

    if "claude" in targets:
        _setup_claude_mcp(project_name, project_path, global_scope=global_scope)

    if "gemini" in targets:
        _setup_gemini_mcp(project_name, project_path, global_scope=global_scope)

    if "cursor" in targets:
        _setup_cursor_mcp(project_name, project_path)

    if "vscode" in targets:
        _setup_vscode_mcp(project_name, project_path)

    if "copilot" in targets:
        _setup_copilot(project_name, project_path)


def _setup_claude_mcp(
    project_name: str, project_path: str, global_scope: bool = False
) -> None:
    """
    Write .claude/CLAUDE.md, .mcp.json, and update .claude/settings.json for Claude Code.

    .claude/CLAUDE.md   — project-level instructions (read by Claude Code)
    .mcp.json           — project MCP server list (shown in /mcp dialog)
    .claude/settings.json — legacy project settings entry (kept for compatibility)
    ~/.claude.json      — global MCP registration (when global_scope=True)
    """
    claude_dir = ".claude"
    os.makedirs(claude_dir, exist_ok=True)

    # ── CLAUDE.md ─────────────────────────────────────────────────────────────
    template = _load_template("claude_mcp.md")
    if template:
        content = _render_template(template, project_name, project_path)
    else:
        content = _minimal_claude_md(project_name, project_path)

    claude_md_path = os.path.join(claude_dir, "CLAUDE.md")
    with open(claude_md_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Wrote {claude_md_path}")

    # Name the server "cognirepo-<project>" so multiple projects can coexist.
    server_name = f"cognirepo-{project_name}" if project_name else "cognirepo"

    # Resolve cognirepo binary — prefer the absolute venv path so Claude Code
    # can start the server regardless of what PATH it inherits.
    cognirepo_bin = shutil.which("cognirepo")
    if cognirepo_bin:
        cmd, args = cognirepo_bin, ["serve", "--project-dir", project_path]
    else:
        cmd = sys.executable
        args = ["-m", "cli.main", "serve", "--project-dir", project_path]

    server_entry = {"command": cmd, "args": args}

    # ── .mcp.json — project-level MCP server list (shown in /mcp dialog) ─────
    mcp_json_path = ".mcp.json"
    if os.path.exists(mcp_json_path):
        try:
            with open(mcp_json_path, encoding="utf-8") as f:
                mcp_json = json.load(f)
        except (json.JSONDecodeError, OSError):
            mcp_json = {}
    else:
        mcp_json = {}

    mcp_json.setdefault("mcpServers", {})[server_name] = server_entry
    with open(mcp_json_path, "w", encoding="utf-8") as f:
        json.dump(mcp_json, f, indent=2)
    print(f"  Wrote {mcp_json_path}  (MCP server: {server_name})")

    # ── .claude/settings.json — kept for compatibility ────────────────────────
    settings_path = os.path.join(claude_dir, "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            settings = {}
    else:
        settings = {}

    settings.setdefault("mcpServers", {})[server_name] = {**server_entry, "env": {}}
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    print(f"  Wrote {settings_path}")

    # ── ~/.claude.json — global registration (optional) ───────────────────────
    if global_scope:
        _register_claude_global(server_name, server_entry)
    else:
        print(f"  Command: {cmd}")


def _register_claude_global(server_name: str, server_entry: dict) -> None:
    """Merge the MCP server entry into ~/.claude.json (global Claude Code config)."""
    global_cfg_path = os.path.expanduser("~/.claude.json")
    if os.path.exists(global_cfg_path):
        try:
            with open(global_cfg_path, encoding="utf-8") as f:
                global_cfg = json.load(f)
        except (json.JSONDecodeError, OSError):
            global_cfg = {}
    else:
        global_cfg = {}

    global_cfg.setdefault("mcpServers", {})[server_name] = {
        **server_entry,
        "env": {},
    }
    with open(global_cfg_path, "w", encoding="utf-8") as f:
        json.dump(global_cfg, f, indent=2)
    print(f"  Registered globally in ~/.claude.json  (server: {server_name})")


def _setup_gemini_mcp(
    project_name: str, project_path: str, global_scope: bool = False
) -> None:
    """
    Write .gemini/COGNIREPO.md and update .gemini/settings.json for Gemini CLI.

    .gemini/COGNIREPO.md  — project-level instructions
    .gemini/settings.json — project MCP server entry
    ~/.gemini/settings.json — global MCP registration (when global_scope=True)
    """
    gemini_dir = ".gemini"
    os.makedirs(gemini_dir, exist_ok=True)

    # ── COGNIREPO.md ──────────────────────────────────────────────────────────
    template = _load_template("gemini_mcp.md")
    if template:
        content = _render_template(template, project_name, project_path)
    else:
        content = _minimal_gemini_md(project_name, project_path)

    md_path = os.path.join(gemini_dir, "COGNIREPO.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Wrote {md_path}")

    server_name = f"cognirepo-{project_name}" if project_name else "cognirepo"

    cognirepo_bin = shutil.which("cognirepo")
    if cognirepo_bin:
        cmd, args = cognirepo_bin, ["serve", "--project-dir", project_path]
    else:
        cmd = sys.executable
        args = ["-m", "cli.main", "serve", "--project-dir", project_path]

    server_entry = {"command": cmd, "args": args}

    # ── .gemini/settings.json — project-level entry ───────────────────────────
    settings_path = os.path.join(gemini_dir, "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            settings = {}
    else:
        settings = {}

    settings.setdefault("mcpServers", {})[server_name] = server_entry
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    print(f"  Wrote {settings_path}  (MCP server: {server_name} → {project_path})")

    # ── ~/.gemini/settings.json — global registration (optional) ─────────────
    if global_scope:
        _register_gemini_global(server_name, server_entry)


def _register_gemini_global(server_name: str, server_entry: dict) -> None:
    """Merge the MCP server entry into ~/.gemini/settings.json (global Gemini CLI config)."""
    global_gemini_dir = os.path.expanduser("~/.gemini")
    os.makedirs(global_gemini_dir, exist_ok=True)
    global_settings_path = os.path.join(global_gemini_dir, "settings.json")

    if os.path.exists(global_settings_path):
        try:
            with open(global_settings_path, encoding="utf-8") as f:
                global_settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            global_settings = {}
    else:
        global_settings = {}

    global_settings.setdefault("mcpServers", {})[server_name] = server_entry
    with open(global_settings_path, "w", encoding="utf-8") as f:
        json.dump(global_settings, f, indent=2)
    print(f"  Registered globally in ~/.gemini/settings.json  (server: {server_name})")


def _setup_cursor_mcp(project_name: str, project_path: str) -> None:
    """
    Write .cursor/mcp.json for Cursor IDE MCP integration.

    Cursor reads mcpServers from .cursor/mcp.json in the workspace root.
    Config generation is idempotent — re-running updates the server entry.
    """
    cursor_dir = ".cursor"
    os.makedirs(cursor_dir, exist_ok=True)

    server_name = f"cognirepo-{project_name}" if project_name else "cognirepo"
    cognirepo_bin = shutil.which("cognirepo")
    if cognirepo_bin:
        cmd, args = cognirepo_bin, ["serve", "--project-dir", project_path]
    else:
        cmd = sys.executable
        args = ["-m", "cli.main", "serve", "--project-dir", project_path]

    mcp_json_path = os.path.join(cursor_dir, "mcp.json")
    if os.path.exists(mcp_json_path):
        try:
            with open(mcp_json_path, encoding="utf-8") as f:
                mcp_cfg = json.load(f)
        except (json.JSONDecodeError, OSError):
            mcp_cfg = {}
    else:
        mcp_cfg = {}

    mcp_cfg.setdefault("mcpServers", {})[server_name] = {
        "command": cmd,
        "args": args,
    }
    with open(mcp_json_path, "w", encoding="utf-8") as f:
        json.dump(mcp_cfg, f, indent=2)
    print(f"  Wrote {mcp_json_path}  (Cursor MCP server: {server_name})")

    # ── .cursor/rules/cognirepo.mdc — routing rules for Cursor AI ────────────
    rules_dir = os.path.join(cursor_dir, "rules")
    os.makedirs(rules_dir, exist_ok=True)
    rules_path = os.path.join(rules_dir, "cognirepo.mdc")
    template = _load_template("cursor_rules.mdc")
    if template:
        content = _render_template(template, project_name, project_path)
    else:
        content = _minimal_cursor_rules(project_name, project_path)
    with open(rules_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Wrote {rules_path}")


def _setup_vscode_mcp(project_name: str, project_path: str) -> None:
    """
    Write .vscode/mcp.json for VS Code MCP extension integration.

    VS Code uses a "servers" top-level key with type="stdio" entries,
    unlike the Claude/Cursor "mcpServers" key format.
    Config generation is idempotent — re-running updates the server entry.
    """
    vscode_dir = ".vscode"
    os.makedirs(vscode_dir, exist_ok=True)

    server_name = f"cognirepo-{project_name}" if project_name else "cognirepo"
    cognirepo_bin = shutil.which("cognirepo")
    if cognirepo_bin:
        cmd, args = cognirepo_bin, ["serve", "--project-dir", project_path]
    else:
        cmd = sys.executable
        args = ["-m", "cli.main", "serve", "--project-dir", project_path]

    mcp_json_path = os.path.join(vscode_dir, "mcp.json")
    if os.path.exists(mcp_json_path):
        try:
            with open(mcp_json_path, encoding="utf-8") as f:
                mcp_cfg = json.load(f)
        except (json.JSONDecodeError, OSError):
            mcp_cfg = {}
    else:
        mcp_cfg = {}

    # VS Code MCP extension format uses "servers" with "type": "stdio"
    mcp_cfg.setdefault("servers", {})[server_name] = {
        "type": "stdio",
        "command": cmd,
        "args": args,
    }
    with open(mcp_json_path, "w", encoding="utf-8") as f:
        json.dump(mcp_cfg, f, indent=2)
    print(f"  Wrote {mcp_json_path}  (VS Code MCP server: {server_name})")

    # ── .vscode/tasks.json — run cognirepo prime on folder open ─────────────
    tasks_path = os.path.join(vscode_dir, "tasks.json")
    tasks_cfg = {}
    if os.path.exists(tasks_path):
        try:
            with open(tasks_path, encoding="utf-8") as f:
                tasks_cfg = json.load(f)
        except (json.JSONDecodeError, OSError):
            tasks_cfg = {}
    tasks_cfg.setdefault("version", "2.0.0")
    existing_tasks = [t for t in tasks_cfg.get("tasks", []) if t.get("label") != "CogniRepo: Refresh Context"]
    from config.paths import get_project_hash  # pylint: disable=import-outside-toplevel
    _cwd = os.path.abspath(os.getcwd())
    _pname = project_name or os.path.basename(_cwd)
    _storage_subdir = f"{_pname}_{get_project_hash(_cwd)}"
    _last_ctx_path = f"~/.cognirepo/storage/{_storage_subdir}/last_context.json"
    existing_tasks.append({
        "label": "CogniRepo: Refresh Context",
        "type": "shell",
        "command": f"cognirepo prime > {_last_ctx_path}",
        "runOptions": {"runOn": "folderOpen"},
        "presentation": {"reveal": "silent"},
    })
    tasks_cfg["tasks"] = existing_tasks
    with open(tasks_path, "w", encoding="utf-8") as f:
        json.dump(tasks_cfg, f, indent=2)
    print(f"  Wrote {tasks_path}  (auto-refresh context on folder open)")


def _minimal_cursor_rules(project_name: str, project_path: str) -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", project_name or "cognirepo")
    return f"""---
description: CogniRepo tool routing rules for {project_name}
globs: ["**/*.py", "**/*.ts", "**/*.js", "**/*.go", "**/*.rs"]
alwaysApply: true
---

## CogniRepo Tool Routing

Project: {project_name}
Data: {project_path}/.cognirepo/

BEFORE reading any file >100 lines:   use mcp_{safe_name}_context_pack first.
BEFORE searching for a function:      use mcp_{safe_name}_lookup_symbol first.
BEFORE tracing callers:               use mcp_{safe_name}_who_calls first.
AFTER a non-trivial decision:         use mcp_{safe_name}_store_memory to record it.

If context_pack returns no_confident_match → fall back to file read.
"""


def _setup_copilot(project_name: str, project_path: str) -> None:
    """
    Write .github/copilot-instructions.md for GitHub Copilot.
    Copilot reads this file for project-level instructions.
    """
    github_dir = ".github"
    os.makedirs(github_dir, exist_ok=True)

    template = _load_template("copilot_instructions.md")
    if template:
        content = _render_template(template, project_name, project_path)
    else:
        content = _minimal_copilot_instructions(project_name, project_path)

    path = os.path.join(github_dir, "copilot-instructions.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Wrote {path}")


def _minimal_copilot_instructions(project_name: str, project_path: str) -> str:
    return f"""# CogniRepo Context for {project_name}

This repo uses CogniRepo for indexed symbol lookup and semantic memory.
Before suggesting changes, check: ~/.cognirepo/{project_name}/last_context.json

Key decisions stored via: `cognirepo retrieve-learnings "<topic>"`
Dynamic dispatch patterns: use `cognirepo who-calls <fn>` for scheduler/signal hooks.
"""


def _detect_agents() -> list[str]:
    """
    Detect which AI agents are present on this system.
    Returns list of detected agent names.
    """
    agents = []
    if shutil.which("claude"):
        agents.append("claude")
    if shutil.which("gemini"):
        agents.append("gemini")
    if Path(".cursor").exists() or shutil.which("cursor"):
        agents.append("cursor")
    if Path(".github").exists() or shutil.which("gh"):
        agents.append("copilot")
    if Path(".vscode").exists() or shutil.which("code"):
        agents.append("vscode")
    return agents


def _minimal_claude_md(project_name: str, project_path: str) -> str:
    return f"""# CogniRepo — {project_name}

Project path: `{project_path}`

Use CogniRepo MCP tools before answering complex questions:
- `retrieve_memory(query)` — semantic search over stored memories
- `lookup_symbol(name)` — find symbol definitions (file + line)
- `search_docs(query)` — search documentation with context snippets
- `store_memory(text)` — save important decisions or bug fixes
- `who_calls(function)` — trace callers in the call graph

All data is in `.cognirepo/` — scoped to this project only.
"""


def _minimal_gemini_md(project_name: str, project_path: str) -> str:
    return f"""# CogniRepo — {project_name}

Project path: `{project_path}`

CogniRepo MCP tools: retrieve_memory, search_docs, lookup_symbol, store_memory.
Data stored in `.cognirepo/` — project-scoped.
"""


# ── doc seeding ───────────────────────────────────────────────────────────────

def autosave_context_enabled() -> bool:
    """Return True if autosave_context is enabled in .cognirepo/config.json."""
    try:
        with open(get_path("config.json"), encoding="utf-8") as _f:
            return bool(json.load(_f).get("autosave_context", True))
    except Exception:  # pylint: disable=broad-except
        return True  # default on


def _seed_learnings_from_docs(repo_root: str) -> int:
    """
    Seed the LearningStore with sections from README/ARCHITECTURE/docs markdown files.
    Called during init so retrieve_learnings() has data immediately.
    Returns the number of sections stored.
    """
    from memory.learning_store import ProjectLearningStore  # pylint: disable=import-outside-toplevel
    store = ProjectLearningStore()
    md_candidates = [
        "README.md", "ARCHITECTURE.md", "CONTRIBUTING.md",
        "DESIGN.md", "OVERVIEW.md", "docs",
    ]
    files: list[Path] = []
    for name in md_candidates:
        p = Path(repo_root) / name
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(p.rglob("*.md"))[:5])
    files = files[:10]  # hard cap

    stored = 0
    for md_file in files:
        try:
            text = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sections = re.split(r'\n(?=#{1,3} )', text)
        for section in sections:
            section = section.strip()
            if len(section) < 150:
                continue
            try:
                store.store_learning(
                    learning_type="documentation",
                    text=section[:2000],
                    context_summary=f"from {md_file.name}",
                    tags=["auto-seeded", md_file.stem.lower()],
                )
                stored += 1
            except Exception:  # pylint: disable=broad-except
                continue
    return stored


# ── public API ────────────────────────────────────────────────────────────────

def init_project(
    no_index: bool = False,
    interactive: bool = True,
    non_interactive: bool = False,
    # wizard-supplied overrides (used when interactive=False or wizard ran)
    project_name: str = "",
    org: str | None = None,
    project: str | None = None,
    encrypt: bool = False,
    vector_backend: str = "faiss",
    mcp_targets: list[str] | None = None,
    mcp_global: bool = False,
    autosave_context: bool = True,
    # deprecated — accepted but ignored for backward compat
    multi_model: bool = True,
    redis: bool = False,
):
    """
    Scaffold .cognirepo/ directories, write config.json, write .gitignore.
    Safe to re-run — existing config is preserved (idempotent).

    When *interactive* is True (default), the powerlevel10k-style wizard runs
    and all parameters are sourced from user answers.

    When *non_interactive* is True, all prompts use defaults (for CI/scripting).

    Returns (summary_dict, kg, indexer) if indexing was performed,
    otherwise (None, None, None).
    """
    # ── idempotency check: detect re-run ─────────────────────────────────────
    _config_path = get_path("config.json")
    _already_init = os.path.exists(_config_path)
    if _already_init:
        print("Already initialized — updating config without losing existing index.")

    # ── run wizard (interactive mode) ─────────────────────────────────────────
    if interactive and not no_index and not non_interactive:
        try:
            from cli.wizard import run_wizard  # pylint: disable=import-outside-toplevel
            wizard_cfg = run_wizard()
            project_name   = wizard_cfg.get("project_name", project_name)
            org            = wizard_cfg.get("org", org)
            project        = wizard_cfg.get("project", project)
            encrypt        = wizard_cfg.get("encrypt", encrypt)
            vector_backend = wizard_cfg.get("vector_backend", vector_backend)
            mcp_targets    = wizard_cfg.get("mcp_targets", mcp_targets or [])
            mcp_global     = wizard_cfg.get("mcp_global", mcp_global)
            autosave_context = wizard_cfg.get("autosave_context", autosave_context)
        except (ImportError, KeyboardInterrupt):
            # Fall back to non-interactive with defaults
            mcp_targets = mcp_targets or []

    if mcp_targets is None:
        mcp_targets = []

    # ── autosave_context prompt (non-wizard interactive) ─────────────────────
    if not non_interactive and sys.stdin.isatty():
        try:
            _ans = input(
                "\nAuto-save context for inter-agent sharing? (y/n) [y]: "
            ).strip().lower()
            autosave_context = _ans not in ("n", "no")
        except (EOFError, KeyboardInterrupt):
            autosave_context = True  # default yes

    # ── scaffold directories and write config ─────────────────────────────────
    _scaffold_dirs()
    _init_empty_stores()
    _write_config(
        project_name=project_name,
        org=org,
        project=project,
        encrypt=encrypt,
        vector_backend=vector_backend,
        autosave_context=autosave_context,
    )
    _write_gitignore()

    # ── link to org ───────────────────────────────────────────────────────────
    if org:
        from config.orgs import (  # pylint: disable=import-outside-toplevel
            create_org, link_repo_to_org, create_project, link_repo_to_project,
        )
        create_org(org)  # Ensure it exists
        link_repo_to_org(os.getcwd(), org)
        print(f"Linked repository to local organization: {org}")
        if project:
            create_project(org, project)
            link_repo_to_project(os.getcwd(), org, project)
            print(f"Linked repository to project: {org}/{project}")

    # ── set up MCP configs ────────────────────────────────────────────────────
    if mcp_targets:
        print("\nConfiguring MCP integration:")
        project_path = os.path.abspath(os.getcwd())
        setup_mcp(mcp_targets, project_name, project_path, global_scope=mcp_global)

    # Read back encrypt flag for status display
    try:
        with open(get_path("config.json"), encoding="utf-8") as f:
            _cfg = json.load(f)
        encrypt_enabled = _cfg.get("storage", {}).get("encrypt", False)
    except (OSError, json.JSONDecodeError):
        encrypt_enabled = False

    # ── dependency check: tiktoken (required for context_pack) ───────────────
    try:
        import tiktoken as _tk  # pylint: disable=import-outside-toplevel
        _tk.get_encoding("cl100k_base")
    except ImportError:
        print(
            "\n[WARNING] tiktoken not installed — context_pack will use "
            "approximate token counts.\n"
            "  Fix: pip install tiktoken"
        )

    print("\nCogniRepo initialised.\n")
    if encrypt_enabled:
        print("Storage encryption: enabled")
        print("  → Key stored in your OS keychain (never written to disk)")
    else:
        print("Storage encryption: disabled")
        print("  → Enable: set storage.encrypt: true in .cognirepo/config.json")

    if no_index:
        print("Skipping index (--no-index). Run 'cognirepo index-repo .' when ready.")
        return None, None, None

    # ── repo indexing (automatic — use --no-index to skip) ───────────────────
    _verb = "Re-indexing" if _already_init else "Indexing"
    print(f"\n{_verb} repo …  (use --no-index to skip)")

    from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
    from indexer.ast_indexer import ASTIndexer        # pylint: disable=import-outside-toplevel

    cwd = os.getcwd()
    kg = KnowledgeGraph()
    indexer = ASTIndexer(graph=kg)

    # Show progress if tqdm is available, otherwise fall back silently
    try:
        from tqdm import tqdm as _tqdm  # pylint: disable=import-outside-toplevel
        _ctx = _tqdm(desc="  indexing", unit="files", leave=False)
    except ImportError:
        _ctx = None

    summary = indexer.index_repo(cwd)
    if _ctx is not None:
        _ctx.close()

    kg.save()

    # seed behaviour weights from git history (fast — no embedding, just git log)
    try:
        from cli.seed import seed_from_git_log  # pylint: disable=import-outside-toplevel
        _seed_result = seed_from_git_log(repo_root=cwd, indexer=indexer)
        _n_seeded = _seed_result.get("seeded", 0) if isinstance(_seed_result, dict) else 0
        if _n_seeded > 0:
            print(f"  Seeded {_n_seeded} symbols from last 100 commits.")
    except Exception:  # pylint: disable=broad-except
        pass  # seeding is best-effort

    return summary, kg, indexer
