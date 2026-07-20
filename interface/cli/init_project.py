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

from core.config.paths import get_path

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


def _seed_dotenv() -> None:
    """Copy .env.example → .env on first init so users discover all env vars."""
    dotenv_dest = Path(".env")
    if dotenv_dest.exists():
        return
    # Source 1: repo root (dev install)
    here = Path(__file__).parent.parent
    example = here / ".env.example"
    # Source 2: installed package data
    if not example.exists():
        import importlib.resources as _ir  # pylint: disable=import-outside-toplevel
        try:
            example = Path(str(_ir.files("cognirepo").joinpath(".env.example")))
        except Exception:  # pylint: disable=broad-except
            example = Path("")
    if example.exists() and example.is_file():
        shutil.copy(example, dotenv_dest)
        print(".env created from .env.example — review it to tune circuit breaker limits or add API keys.")
    else:
        # Not fatal — all settings have built-in defaults (RSS limit = 80% of
        # RAM, etc.). But say so instead of silently skipping, so users know
        # why no .env appeared and what the override mechanism is.
        print(
            "Note: .env template not found in this install — skipping .env creation. "
            "All settings use built-in defaults; create a .env manually to override "
            "(see docs/USAGE.md → Configuration Reference)."
        )


def _scaffold_dirs() -> None:
    # Always create local .cognirepo/ FIRST so all subsequent get_path() calls
    # resolve to the local dir (not the global fallback). Without this, a brand-new
    # repo has no local .cognirepo/ and config.json lands at ~/.cognirepo/storage/<hash>/
    # while a later get_path() call (after some other code creates the local dir)
    # resolves locally — causing config.json missing in doctor.
    local_dir = os.path.join(os.getcwd(), ".cognirepo")
    os.makedirs(local_dir, exist_ok=True)
    os.makedirs(get_path("memory"), exist_ok=True)
    os.makedirs(get_path("docs"), exist_ok=True)
    os.makedirs(get_path("index"), exist_ok=True)
    os.makedirs(get_path("graph"), exist_ok=True)
    os.makedirs(get_path("errors"), exist_ok=True)
    os.makedirs(get_path("vector_db"), exist_ok=True)
    os.makedirs(get_path("episodic"), exist_ok=True)


def _init_empty_stores(vector_backend: str = "faiss") -> None:
    """
    Create empty ChromaDB collection and episodic log on first init so `doctor`
    shows 0 vectors immediately after `cognirepo init` instead of "not found".

    FAISS is used for AST indexing (built by `cognirepo index-repo`).
    ChromaDB is always used for semantic text memory.
    """
    # Eagerly create ChromaDB collection so doctor finds it immediately.
    try:
        from core.vector_db.chroma_adapter import ChromaDBAdapter  # pylint: disable=import-outside-toplevel
        ChromaDBAdapter()  # triggers PersistentClient → creates the on-disk directory
    except Exception:  # pylint: disable=broad-except
        pass  # chromadb not installed — doctor will surface the hint

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
    vector_backend: str = "chroma",
    autosave_context: bool = True,
    behaviour_tracking: bool = False,
) -> str:
    """
    Write config.json (new) or backfill missing keys (existing).
    Returns the project_id (new or existing).
    """
    if not os.path.exists(get_path("config.json")):
        project_id = str(uuid.uuid4())

        config: dict = {
            "schema_version": 1,
            "project_id":   project_id,
            "project_name": project_name or os.path.basename(os.getcwd()),
            "org":          org,
            "project":      project,
            "storage":      {"encrypt": encrypt, "vector_backend": vector_backend},
            "retrieval_weights": {"vector": 0.5, "graph": 0.3, "behaviour": 0.2},
            "model":        DEFAULT_MODEL,
            "autosave_context": autosave_context,
            "behaviour_tracking": behaviour_tracking,
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
        ("schema_version", 1),
        ("project_id",    str(uuid.uuid4())),
        ("project_name",  project_name or os.path.basename(os.getcwd())),
        ("retrieval_weights", {"vector": 0.5, "graph": 0.3, "behaviour": 0.2}),
        ("model",         DEFAULT_MODEL),
        ("autosave_context", True),
        ("behaviour_tracking", False),
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
        args = ["-m", "interface.cli.main", "serve", "--project-dir", project_path]

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

    # ── Behaviour hooks — wired after settings.json exists ────────────────────
    try:
        from interface.cli.main import _write_claude_hooks  # pylint: disable=import-outside-toplevel
        _write_claude_hooks(claude_dir, project_path)
    except Exception:  # pylint: disable=broad-except
        pass  # non-fatal; doctor will warn if hooks are missing

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
        args = ["-m", "interface.cli.main", "serve", "--project-dir", project_path]

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
        args = ["-m", "interface.cli.main", "serve", "--project-dir", project_path]

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
        args = ["-m", "interface.cli.main", "serve", "--project-dir", project_path]

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
    from core.config.paths import get_project_hash  # pylint: disable=import-outside-toplevel
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
    from data.memory.learning_store import ProjectLearningStore  # pylint: disable=import-outside-toplevel
    store = ProjectLearningStore()
    md_candidates = [
        "README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md",
        "docs/architecture/SPECIFICATION.md", "docs/ARCHITECTURE.md",
        "docs/USAGE.md", "docs/FEATURES.md", "docs/DEVELOPER_GUIDE.md",
        "docs",
    ]
    files: list[Path] = []
    for name in md_candidates:
        p = Path(repo_root) / name
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(p.rglob("*.md"))[:10])
    files = files[:20]  # higher cap to include moved docs

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


# ── child repo helpers ────────────────────────────────────────────────────────

def _index_with_progress(svc_path: str, svc_name: str):
    """Run ASTIndexer in a daemon thread while showing a pulsing progress bar."""
    import threading  # pylint: disable=import-outside-toplevel
    from interface.cli.wizard import _animate_indexing  # pylint: disable=import-outside-toplevel
    from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
    from intelligence.indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
    from interface.tools.bg_progress import TaskProgress  # pylint: disable=import-outside-toplevel

    done   = threading.Event()
    result = {}

    def _worker():
        try:
            _kg  = KnowledgeGraph()
            _idx = ASTIndexer(graph=_kg, progress_factory=TaskProgress)
            _sum = _idx.index_repo(svc_path)
            _idx.free_large_objects()
            _kg.save()
            result["summary"] = _sum
            result["kg"]      = _kg
        except Exception as exc:  # pylint: disable=broad-except
            result["error"] = str(exc)
        finally:
            done.set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    _animate_indexing(svc_name, done)
    t.join()
    return result.get("summary"), result.get("kg")


def _detect_service_port(svc_path: str) -> int | None:
    """Best-effort port detection from common service config files.

    Without this, agents answering "what port does X run on?" guess from
    summaries and get it wrong — the authoritative value lives in the
    service's own config (e.g. Spring `server.port`, `.env` PORT).
    """
    import re as _re  # pylint: disable=import-outside-toplevel
    candidates = [
        os.path.join(svc_path, "src", "main", "resources", "application.properties"),
        os.path.join(svc_path, "src", "main", "resources", "application.yml"),
        os.path.join(svc_path, "src", "main", "resources", "application.yaml"),
        os.path.join(svc_path, "application.properties"),
        os.path.join(svc_path, ".env"),
    ]
    patterns = [
        _re.compile(r"^\s*server\.port\s*[=:]\s*(\d{2,5})", _re.MULTILINE),  # Spring
        _re.compile(r"^\s*port\s*:\s*(\d{2,5})", _re.MULTILINE),             # YAML
        _re.compile(r"^\s*PORT\s*=\s*(\d{2,5})", _re.MULTILINE),             # .env
    ]
    for path in candidates:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue
        for pat in patterns:
            m = pat.search(content)
            if m:
                return int(m.group(1))
    return None


def _register_in_org_graph(svc, parent_path: str) -> None:
    """Add service node + CHILD_OF edge to the org graph.

    Persists service_type plus auto-detected port so org-level tools
    (get_agent_bootstrap child_services, list_org_context) report
    authoritative values instead of leaving agents to guess.
    """
    try:
        from data.graph.org_graph import get_org_graph  # pylint: disable=import-outside-toplevel
        og = get_org_graph()
        meta: dict = {"service_type": svc.service_type}
        port = getattr(svc, "port", None) or _detect_service_port(svc.path)
        if port:
            meta["port"] = port
        api_base_url = getattr(svc, "api_base_url", None)
        if api_base_url:
            meta["api_base_url"] = api_base_url
        og.add_repo(svc.path, parent_path=parent_path, metadata=meta)
        og.save()
    except Exception:  # pylint: disable=broad-except
        pass  # non-fatal


def _wire_inter_repo_edges(children: list, parent_path: str) -> None:
    """
    After all child repos are indexed, auto-detect IMPORTS edges from manifests
    and AST symbol index.  Uses existing extract_dependencies() and
    og.infer_import_edges() — no new logic, just wiring them into the setup flow.
    """
    try:
        from data.graph.org_graph import get_org_graph  # pylint: disable=import-outside-toplevel
        from intelligence.indexer.inter_repo_indexer import extract_dependencies  # pylint: disable=import-outside-toplevel
        import json as _json  # pylint: disable=import-outside-toplevel

        og = get_org_graph()
        sibling_paths = [svc.path for svc in children]
        all_paths = sibling_paths + [parent_path]
        edges_added = 0

        for svc in children:
            # Pass 1: manifest-based (pyproject.toml, package.json, go.mod, …)
            edges = extract_dependencies(svc.path, [p for p in all_paths if p != svc.path])
            for edge in edges:
                og.link(edge.src_repo, edge.dst_repo, kind=edge.kind, auto=True)
                edges_added += 1

            # Pass 2: AST-symbol-based (import statements in indexed code)
            try:
                _ctxdir = get_path("index/ast_index.json")  # child CWD must be set
                # Load child's ast_index via context switch
                from core.config.paths import _CTX_DIR, get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
                _child_cog = get_cognirepo_dir_for_repo(svc.path)
                _tok = _CTX_DIR.set(_child_cog)
                try:
                    _ast_path = get_path("index/ast_index.json")
                    if os.path.exists(_ast_path):
                        with open(_ast_path, encoding="utf-8") as _f:
                            _child_idx = _json.load(_f)
                        edges_added += og.infer_import_edges(svc.path, _child_idx)
                finally:
                    _CTX_DIR.reset(_tok)
            except Exception:  # pylint: disable=broad-except
                pass

        if edges_added:
            og.save()
            print(f"  ✓  Inter-repo edges: {edges_added} relationship(s) auto-detected (IMPORTS + CALLS_API).")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"  ⚠  Inter-repo edge detection skipped: {exc}")


def _inject_child_stubs_into_parent_kg(children: list, parent_path: str) -> None:
    """
    Populate the parent orchestrator's KnowledgeGraph with stub nodes for each
    child service so graph_stats(), subgraph(), and lookup_symbol() work from
    the parent MCP context.

    For each child:
      - Adds a REPO node for the service.
      - Adds FILE nodes for each indexed file.
      - Adds top exported symbols (functions/classes) as stubs with DEFINED_IN edges.
      - All stubs carry repo=<child_name> so they're identifiable as cross-repo entries.
    """
    try:
        import json as _json  # pylint: disable=import-outside-toplevel
        from core.config.paths import _CTX_DIR, get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
        from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel

        # Load parent KG via parent context
        _parent_cog = get_cognirepo_dir_for_repo(parent_path)
        _tok = _CTX_DIR.set(_parent_cog)
        try:
            parent_kg = KnowledgeGraph()
            total_nodes = 0

            for svc in children:
                svc_name = svc.name
                svc_abs  = os.path.abspath(svc.path)

                # REPO node for the child service
                repo_node = f"repo::{svc_name}"
                parent_kg.add_node(
                    repo_node,
                    node_type="REPO",
                    name=svc_name,
                    path=svc_abs,
                    service_type=getattr(svc, "service_type", "unknown"),
                    repo=svc_name,
                    cross_repo=True,
                )
                total_nodes += 1

                # Load child's AST index
                _child_cog = get_cognirepo_dir_for_repo(svc_abs)
                _ctok = _CTX_DIR.set(_child_cog)
                try:
                    _ast_path = get_path("index/ast_index.json")
                    if not os.path.exists(_ast_path):
                        continue
                    with open(_ast_path, encoding="utf-8") as _f:
                        child_idx = _json.load(_f)
                finally:
                    _CTX_DIR.reset(_ctok)

                # FILE + SYMBOL stubs
                for rel_file, file_data in child_idx.get("files", {}).items():
                    file_node = f"file::{svc_name}::{rel_file}"
                    parent_kg.add_node(
                        file_node,
                        node_type="FILE",
                        name=rel_file,
                        repo=svc_name,
                        path=os.path.join(svc_abs, rel_file),
                        cross_repo=True,
                    )
                    parent_kg.add_edge(file_node, repo_node, edge_type="DEFINED_IN")
                    total_nodes += 1

                    for sym in file_data.get("symbols", []):
                        sym_type = sym.get("type", "SYMBOL")
                        sym_name = sym.get("name", "")
                        # Only stub exported functions and classes (skip imports/internals)
                        if sym_type not in ("FUNCTION", "CLASS", "METHOD", "ENDPOINT"):
                            continue
                        if not sym_name or sym_name.startswith("_"):
                            continue
                        sym_node = f"symbol::{svc_name}::{sym_name}"
                        parent_kg.add_node(
                            sym_node,
                            node_type=sym_type,
                            name=sym_name,
                            file=rel_file,
                            line=sym.get("start_line", 0),
                            repo=svc_name,
                            docstring=sym.get("docstring", ""),
                            cross_repo=True,
                        )
                        parent_kg.add_edge(sym_node, file_node, edge_type="DEFINED_IN")
                        total_nodes += 1

            parent_kg.save()
            print(f"  ✓  Parent KG: injected {total_nodes} cross-repo stub nodes from {len(children)} service(s).")
        finally:
            _CTX_DIR.reset(_tok)

    except Exception as exc:  # pylint: disable=broad-except
        print(f"  ⚠  Parent KG stub injection skipped: {exc}")


def _flush_cognirepo(path: str, name: str) -> None:
    """Remove .cognirepo/ from a repo directory."""
    import shutil  # pylint: disable=import-outside-toplevel
    cr_dir = os.path.join(path, ".cognirepo")
    if os.path.isdir(cr_dir):
        shutil.rmtree(cr_dir)
        print(f"  ✓  Flushed .cognirepo/ from {name}")
    else:
        print(f"  {name}: no .cognirepo/ to flush")


def _write_parent_metadata_to_child(child_path: str, parent_path: str, parent_name: str) -> None:
    """Inject parent reference into the child's config.json."""
    cfg_path = os.path.join(child_path, ".cognirepo", "config.json")
    if not os.path.exists(cfg_path):
        return
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["parent"] = {"path": parent_path, "project_name": parent_name, "role": "child"}
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:  # pylint: disable=broad-except
        pass


def _auto_setup_child_repos(
    children: list,
    parent_path: str,
    org: str | None,
    encrypt: bool,
    mcp_targets: list[str],
    autosave_context: bool = True,
    behaviour_tracking: bool = False,
    parent_name: str = "",
    rejected: list | None = None,
) -> None:
    """Animate queue pop/process for each detected microservice."""
    from interface.cli.wizard import (  # pylint: disable=import-outside-toplevel
        _animate_enqueue, _animate_pop, _service_header, _ask_yn,
        _ok, _warn,
    )
    from interface.cli.init_project import init_project as _init_project  # pylint: disable=import-outside-toplevel
    from interface.cli.main import _write_claude_hooks  # pylint: disable=import-outside-toplevel

    _animate_enqueue(children)

    remaining_names = [svc.name for svc in children]

    for idx, svc in enumerate(children, 1):
        remaining_names = [n for n in remaining_names if n != svc.name]
        _animate_pop(svc.name, remaining_names)
        _service_header(svc.name, idx, len(children))

        old_cwd = os.getcwd()
        try:
            os.chdir(svc.path)   # stay in child dir for BOTH init AND index
            try:
                if svc.already_init:
                    _ans = _ask_yn(
                        f"  {svc.name} already has .cognirepo/ — overwrite (re-initialize)?",
                        default=False,
                    )
                    if not _ans:
                        print(f"  {svc.name}: skipping init — re-indexing and updating config")
                        # Still inject parent metadata and run index even if skipping full init
                        _write_parent_metadata_to_child(svc.path, parent_path, parent_name)
                        _index_with_progress(svc.path, svc.name)
                        _register_in_org_graph(svc, parent_path)
                        _ok(f"{svc.name} re-indexed\n")
                        continue

                _init_project(
                    non_interactive=True,
                    project_name=svc.name,
                    org=org,
                    encrypt=encrypt,
                    vector_backend="chroma",
                    mcp_targets=mcp_targets,
                    autosave_context=autosave_context,
                    behaviour_tracking=behaviour_tracking,
                    no_index=True,   # indexing done below for live progress bar
                )
                # Store parent reference in child config
                _write_parent_metadata_to_child(svc.path, parent_path, parent_name)
                # CWD is still svc.path here → KnowledgeGraph() reads child's .cognirepo/
                _index_with_progress(svc.path, svc.name)
                _register_in_org_graph(svc, parent_path)
                # Wire Claude Code / editor hooks inside child if .claude/ exists
                _child_claude_dir = os.path.join(svc.path, ".claude")
                if os.path.isdir(_child_claude_dir):
                    try:
                        _write_claude_hooks(_child_claude_dir, svc.path)
                        print(f"  ✓  Behaviour hooks wired for {svc.name}")
                    except Exception:  # pylint: disable=broad-except
                        pass
                _ok(f"{svc.name} done\n")
            finally:
                os.chdir(old_cwd)

        except Exception as exc:  # pylint: disable=broad-except
            if os.getcwd() != old_cwd:
                os.chdir(old_cwd)
            _warn(f"{svc.name} failed: {exc}")

    print(f"\n  {'─'*46}")
    print(f"  Queue empty. {chr(10004)}  All services indexed.\n")

    # ── post-setup wiring (best-effort, never blocks) ─────────────────────────
    print("  Wiring inter-repo relationships …")
    _wire_inter_repo_edges(children, parent_path)
    _inject_child_stubs_into_parent_kg(children, parent_path)

    # ── flush rejected repos that have a stale .cognirepo/ ────────────────────
    if rejected:
        stale = [svc for svc in rejected if os.path.isdir(os.path.join(svc.path, ".cognirepo"))]
        if stale:
            print(f"\n  {len(stale)} detected-but-not-selected service(s) have an existing .cognirepo/:")
            for svc in stale:
                print(f"    • {svc.name}  ({svc.path})")
            _do_flush = _ask_yn("  Remove their .cognirepo/ directories now?", default=False)
            if _do_flush:
                for svc in stale:
                    _flush_cognirepo(svc.path, svc.name)


# ── public API ────────────────────────────────────────────────────────────────

def init_project(
    no_index: bool = False,
    interactive: bool = True,
    non_interactive: bool = False,
    no_graph: bool = False,
    # wizard-supplied overrides (used when interactive=False or wizard ran)
    project_name: str = "",
    org: str | None = None,
    project: str | None = None,
    encrypt: bool = False,
    vector_backend: str = "chroma",
    mcp_targets: list[str] | None = None,
    autosave_context: bool = True,
    behaviour_tracking: bool = False,
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
    _wizard_ran = False
    if interactive  and not non_interactive:
        try:
            from interface.cli.wizard import run_wizard  # pylint: disable=import-outside-toplevel
            wizard_cfg = None
            while wizard_cfg is None:
                wizard_cfg = run_wizard()
            project_name   = wizard_cfg.get("project_name", project_name)
            org            = wizard_cfg.get("org", org)
            project        = wizard_cfg.get("project", project)
            encrypt        = wizard_cfg.get("encrypt", encrypt)
            vector_backend = wizard_cfg.get("vector_backend", vector_backend)
            mcp_targets    = wizard_cfg.get("mcp_targets", mcp_targets or [])
            autosave_context = wizard_cfg.get("autosave_context", autosave_context)
            behaviour_tracking = wizard_cfg.get("behaviour_tracking", behaviour_tracking)
            _wizard_ran = True
        except (ImportError, KeyboardInterrupt):
            # Fall back to non-interactive with defaults
            mcp_targets = mcp_targets or []

    if mcp_targets is None:
        mcp_targets = []

    # ── autosave_context prompt (non-wizard interactive, wizard already asked) ─
    if not _wizard_ran and not non_interactive and sys.stdin.isatty():
        try:
            _ans = input(
                "\nAuto-save context for inter-agent sharing? (y/n) [y]: "
            ).strip().lower()
            autosave_context = _ans not in ("n", "no")
        except (EOFError, KeyboardInterrupt):
            autosave_context = True  # default yes

    # ── scaffold directories and write config ─────────────────────────────────
    _scaffold_dirs()
    _init_empty_stores(vector_backend=vector_backend)
    _write_config(
        project_name=project_name,
        org=org,
        project=project,
        encrypt=encrypt,
        vector_backend=vector_backend,
        autosave_context=autosave_context,
        behaviour_tracking=behaviour_tracking,
    )
    _write_gitignore()
    _seed_dotenv()

    # ── link to org ───────────────────────────────────────────────────────────
    if org:
        from core.config.orgs import (  # pylint: disable=import-outside-toplevel
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
        setup_mcp(mcp_targets, project_name, project_path, global_scope=False)

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

    from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
    from intelligence.indexer.ast_indexer import ASTIndexer        # pylint: disable=import-outside-toplevel
    from interface.tools.bg_progress import TaskProgress  # pylint: disable=import-outside-toplevel

    cwd = os.getcwd()
    kg = KnowledgeGraph()
    indexer = ASTIndexer(graph=kg, progress_factory=TaskProgress)

    # Show progress if tqdm is available, otherwise fall back silently
    try:
        from tqdm import tqdm as _tqdm  # pylint: disable=import-outside-toplevel
        _ctx = _tqdm(desc="  indexing", unit="files", leave=False)
    except ImportError:
        _ctx = None

    summary = indexer.index_repo(cwd, skip_graph=True if no_graph else None)
    if _ctx is not None:
        _ctx.close()

    # Free large in-memory objects before graph serialization to reduce RSS peak.
    indexer.free_large_objects()

    try:
        kg.save()
    except Exception as _kg_exc:  # pylint: disable=broad-except
        _exc_name = type(_kg_exc).__name__
        if "CircuitOpen" in _exc_name or "CircuitBreaker" in _exc_name:
            print(
                f"  ⚠  Knowledge graph not saved (memory limit hit). "
                "AST index and embeddings are intact — cognirepo will still work. "
                "Use --no-graph to disable graph, or set "
                "COGNIREPO_CB_RSS_LIMIT_MB=4000 to raise the limit."
            )
        else:
            raise

    # ── auto-launch Tier 2 background pass if pending queue was written ──────
    try:
        from core.config.paths import pending_tier2_path  # pylint: disable=import-outside-toplevel
        import subprocess as _sp  # pylint: disable=import-outside-toplevel
        from pathlib import Path as _Path  # pylint: disable=import-outside-toplevel
        _t2_queue = pending_tier2_path()
        if os.path.exists(_t2_queue):
            import json as _json  # pylint: disable=import-outside-toplevel
            with open(_t2_queue, encoding="utf-8") as _t2f:
                _t2_data = _json.load(_t2f)
            _t2_count = len(_t2_data.get("files", []))
            _embed_pending = _t2_data.get("embed_pending", False)
            if _t2_count > 0 or _embed_pending:
                _bin_dir = _Path(sys.executable).parent
                _colocated = _bin_dir / "cognirepo"
                _cogcmd = str(_colocated) if _colocated.exists() else "cognirepo"
                _sp.Popen(
                    [_cogcmd, "index-repo", cwd, "--tier", "2", "--no-watch"],
                    stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                    start_new_session=True,
                )
                _what = []
                if _t2_count > 0:
                    _what.append(f"{_t2_count:,} files")
                if _embed_pending:
                    _what.append("FAISS embeddings")
                print(f"  Tier 2: {' + '.join(_what)} queued — background indexing started.")
                # edge: launch progress window (failure never blocks indexing)
                try:
                    from interface.tools.bg_progress import launch_progress_ui as _lpui  # pylint: disable=import-outside-toplevel
                    _lpui()
                except Exception:  # pylint: disable=broad-except
                    pass
    except Exception:  # pylint: disable=broad-except
        pass

    # seed behaviour weights from git history (fast — no embedding, just git log)
    try:
        from interface.cli.seed import seed_from_git_log  # pylint: disable=import-outside-toplevel
        _seed_result = seed_from_git_log(repo_root=cwd, indexer=indexer)
        _n_seeded = _seed_result.get("seeded", 0) if isinstance(_seed_result, dict) else 0
        if _n_seeded > 0:
            print(f"  Seeded {_n_seeded} symbols from last 100 commits.")
    except Exception:  # pylint: disable=broad-except
        pass  # seeding is best-effort

    # ── auto-summarize: generate architectural summaries if not present ───────
    _summaries_path = get_path("index/summaries.json")
    _should_summarize = not os.path.exists(_summaries_path)

    if _should_summarize and sys.stdin.isatty() and not non_interactive:
        try:
            _ans = input(
                "\nGenerate architectural summaries for this repo? "
                "(y/n) [y]: "
            ).strip().lower()
            _should_summarize = _ans not in ("n", "no")
        except (EOFError, KeyboardInterrupt):
            _should_summarize = True  # default yes

    if _should_summarize:
        print("\nGenerating architectural summaries …")
        try:
            from intelligence.indexer.summarizer import SummarizationEngine  # pylint: disable=import-outside-toplevel
            from interface.tools.bg_progress import TaskProgress, launch_progress_ui  # pylint: disable=import-outside-toplevel
            _engine = SummarizationEngine(
                progress_factory=TaskProgress, launch_progress_ui_fn=launch_progress_ui,
            )
            _sum_result = _engine.run_full_summarization()
            print("  Summaries saved to .cognirepo/index/summaries.json")
            if _sum_result.get("repo"):
                _preview = _sum_result["repo"][:200].replace("\n", " ")
                print(f"  Preview: {_preview}…")
        except Exception as _sum_exc:  # pylint: disable=broad-except
            print(f"  Summarization skipped ({_sum_exc}).")
            print("  Run 'cognirepo summarize' once an LLM API key is configured.")

    # ── doc ingestion: embed docs/README/git-log into semantic store ──────────
    # Subprocess-isolated: ingestion in a process that just finished a heavy
    # indexing pass was observed to segfault (fragmented ONNX/FAISS heaps).
    try:
        from intelligence.indexer.doc_ingester import run_ingest_subprocess  # pylint: disable=import-outside-toplevel
        _ing_result = run_ingest_subprocess(cwd)
        _n_chunks = _ing_result.get("chunks", 0)
        if _n_chunks > 0:
            print(f"  Semantic store: {_n_chunks} doc chunks embedded.")
    except Exception:  # pylint: disable=broad-except
        pass  # best-effort — never block init

    print("\n✓ Done — CogniRepo is ready.")

    return summary, kg, indexer
