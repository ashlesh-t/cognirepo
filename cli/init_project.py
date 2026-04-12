# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Module to initialize the cognirepo project structure.

Interactive mode (default): runs the terminal wizard (cli.wizard.run_wizard)
and asks the user about multi-model, encryption, Redis, and MCP targets.

Non-interactive mode (--no-index / scripting): skips wizard, uses CLI flags.
"""
import json
import os
import secrets
import shutil
import sys
import uuid

try:
    import keyring  # pylint: disable=import-error
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False

import bcrypt as _bcrypt


from config.paths import get_path

_KEYCHAIN_SERVICE = "cognirepo"

DEFAULT_PASSWORD = "changeme"
DEFAULT_PORT = 8000

# Blanket ignore — nothing under .cognirepo/ ever reaches git.
GITIGNORE_CONTENT = "*\n!.gitignore\n"

DEFAULT_MODELS = {
    "QUICK":    {"provider": "grok",      "model": "llama-3.1-8b-instant"},
    "STANDARD": {"provider": "gemini",    "model": "gemini-2.0-flash"},
    "COMPLEX":  {"provider": "gemini",    "model": "gemini-2.0-flash"},
    "EXPERT":   {"provider": "anthropic", "model": "claude-sonnet-4-6"},
}

# Path to the bundled MCP prompt templates (relative to this file)
_STD_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "STD_PROMPTS")


# ── internal helpers ──────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def _store_secret(key: str, value: str) -> bool:
    """Store *value* under *key* in the OS keychain. Returns True on success."""
    if not _KEYRING_AVAILABLE:
        return False
    try:
        keyring.set_password(_KEYCHAIN_SERVICE, key, value)
        return True
    except Exception:  # pylint: disable=broad-except
        return False


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
    password: str,
    port: int,
    project_name: str = "",
    encrypt: bool = False,
    multi_model: bool = True,
    lazy_grpc: bool = True,
    redis: bool = False,
) -> str:
    """
    Write config.json (new) or backfill missing keys (existing).
    Returns the project_id (new or existing).

    Secrets (password_hash, jwt_secret) are stored in the OS keychain when
    available; a fallback copy goes into config.json only when keyring is absent.
    """
    if not os.path.exists(get_path("config.json")):
        project_id = str(uuid.uuid4())
        jwt_secret = secrets.token_hex(32)
        pw_hash = _hash_password(password)

        in_keychain = _store_secret(f"{project_id}.jwt_secret", jwt_secret)
        in_keychain = _store_secret(f"{project_id}.password_hash", pw_hash) and in_keychain

        config: dict = {
            "project_id":   project_id,
            "project_name": project_name or os.path.basename(os.getcwd()),
            "api_port":     port,
            "api_url":      f"http://localhost:{port}",
            "storage":      {"encrypt": encrypt},
            "retrieval_weights": {"vector": 0.5, "graph": 0.3, "behaviour": 0.2},
            "models":       DEFAULT_MODELS,
            "multi_agent":  {
                "enabled":          multi_model,
                "auto_start_grpc":  lazy_grpc,
                "grpc_port":        50051,
            },
            "redis": {"enabled": redis, "url": "redis://localhost:6379"},
        }
        if not in_keychain:
            config["password_hash"] = pw_hash

        with open(get_path("config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"Created {get_path('config.json')}")
        print(f"  api_url  : http://localhost:{port}")
        if in_keychain:
            print("  secrets  : stored in OS keychain (never written to disk)")
        else:
            print("  secrets  : stored in config.json (install keyring for keychain storage)")
        return project_id

    # ── existing config — backfill missing keys ───────────────────────────────
    with open(get_path("config.json"), "r", encoding="utf-8") as f:
        config = json.load(f)

    changed = False
    defaults: list[tuple] = [
        ("project_id",    str(uuid.uuid4())),
        ("project_name",  project_name or os.path.basename(os.getcwd())),
        ("api_port",      port),
        ("api_url",       f"http://localhost:{config.get('api_port', port)}"),
        ("retrieval_weights", {"vector": 0.5, "graph": 0.3, "behaviour": 0.2}),
        ("models",        DEFAULT_MODELS),
    ]
    for key, val in defaults:
        if key not in config:
            config[key] = val
            changed = True

    # Always apply user-specified wizard settings (not just backfill)
    if config.setdefault("storage", {}).get("encrypt") != encrypt:
        config["storage"]["encrypt"] = encrypt
        changed = True
    _ma = config.setdefault("multi_agent", {})
    if _ma.get("enabled") != multi_model or _ma.get("auto_start_grpc") != lazy_grpc:
        _ma.update({"enabled": multi_model, "auto_start_grpc": lazy_grpc, "grpc_port": 50051})
        changed = True
    if config.setdefault("redis", {"url": "redis://localhost:6379"}).get("enabled") != redis:
        config["redis"]["enabled"] = redis
        changed = True

    # Ensure QUICK tier is in models
    if "QUICK" not in config.get("models", {}):
        config.setdefault("models", {})["QUICK"] = DEFAULT_MODELS["QUICK"]
        changed = True

    if changed:
        with open(get_path("config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"Updated {get_path("config.json")} with missing keys.")
    else:
        print(f"{get_path("config.json")} already up to date.")

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


# ── public API ────────────────────────────────────────────────────────────────

def init_project(
    password: str = DEFAULT_PASSWORD,
    port: int = DEFAULT_PORT,
    no_index: bool = False,
    interactive: bool = True,
    non_interactive: bool = False,
    # wizard-supplied overrides (used when interactive=False or wizard ran)
    project_name: str = "",
    encrypt: bool = False,
    multi_model: bool = True,
    lazy_grpc: bool = True,
    redis: bool = False,
    mcp_targets: list[str] | None = None,
    mcp_global: bool = False,
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
            password     = wizard_cfg.get("password", password)
            port         = wizard_cfg.get("port", port)
            project_name = wizard_cfg.get("project_name", project_name)
            encrypt      = wizard_cfg.get("encrypt", encrypt)
            multi_model  = wizard_cfg.get("multi_model", multi_model)
            lazy_grpc    = wizard_cfg.get("lazy_grpc", lazy_grpc)
            redis        = wizard_cfg.get("redis", redis)
            mcp_targets  = wizard_cfg.get("mcp_targets", mcp_targets or [])
            mcp_global   = wizard_cfg.get("mcp_global", mcp_global)
        except (ImportError, KeyboardInterrupt):
            # Fall back to non-interactive with defaults
            mcp_targets = mcp_targets or []

    if mcp_targets is None:
        mcp_targets = []

    # ── scaffold directories and write config ─────────────────────────────────
    _scaffold_dirs()
    _init_empty_stores()
    _write_config(
        password=password,
        port=port,
        project_name=project_name,
        encrypt=encrypt,
        multi_model=multi_model,
        lazy_grpc=lazy_grpc,
        redis=redis,
    )
    _write_gitignore()

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

    # seed behaviour from git history
    try:
        from cli.seed import seed_from_git_log  # pylint: disable=import-outside-toplevel
        seed_from_git_log(repo_root=cwd, indexer=indexer)
    except Exception:  # pylint: disable=broad-except
        pass  # seeding is best-effort

    return summary, kg, indexer
