# SPDX-FileCopyrightText: 2026 Ashlesh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/your-username/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Module to initialize the cognirepo project structure.
"""
import json
import os
import secrets
import uuid

try:
    import keyring  # pylint: disable=import-error
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False

try:
    from passlib.context import CryptContext  # pylint: disable=import-error
    _pwd_ctx = CryptContext(schemes=["bcrypt"])
    _PASSLIB_AVAILABLE = True
except ImportError:
    import bcrypt as _bcrypt  # type: ignore
    _PASSLIB_AVAILABLE = False


_KEYCHAIN_SERVICE = "cognirepo"

DEFAULT_PASSWORD = "changeme"
DEFAULT_PORT = 8000
CONFIG_FILE = ".cognirepo/config.json"
GITIGNORE_FILE = ".cognirepo/.gitignore"

# Blanket ignore — nothing under .cognirepo/ ever reaches git.
# The .gitignore itself is the only exception.
GITIGNORE_CONTENT = "*\n!.gitignore\n"

DEFAULT_MODELS = {
    "FAST":     {"provider": "gemini",    "model": "gemini-2.0-flash"},
    "BALANCED": {"provider": "gemini",    "model": "gemini-2.0-flash"},
    "DEEP":     {"provider": "anthropic", "model": "claude-sonnet-4-6"},
}


# ── internal helpers ──────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    if _PASSLIB_AVAILABLE:
        return _pwd_ctx.hash(password)
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
    with open(GITIGNORE_FILE, "w", encoding="utf-8") as f:
        f.write(GITIGNORE_CONTENT)


def _scaffold_dirs() -> None:
    os.makedirs(".cognirepo/memory", exist_ok=True)
    os.makedirs(".cognirepo/docs", exist_ok=True)
    os.makedirs(".cognirepo/index", exist_ok=True)
    os.makedirs(".cognirepo/graph", exist_ok=True)
    os.makedirs("vector_db", exist_ok=True)


def _write_config(password: str, port: int) -> str:
    """
    Write config.json (new) or backfill missing keys (existing).
    Returns the project_id (new or existing).

    Secrets (password_hash, jwt_secret) are stored in the OS keychain when
    available; a fallback copy goes into config.json only when keyring is absent.
    """
    if not os.path.exists(CONFIG_FILE):
        project_id = str(uuid.uuid4())
        jwt_secret = secrets.token_hex(32)
        pw_hash = _hash_password(password)

        # Try keychain first; fall back to config.json when unavailable.
        in_keychain = _store_secret(f"{project_id}.jwt_secret", jwt_secret)
        in_keychain = _store_secret(f"{project_id}.password_hash", pw_hash) and in_keychain

        config: dict = {
            "project_id": project_id,
            "api_port": port,
            "api_url": f"http://localhost:{port}",
            "storage": {"encrypt": False},
            "retrieval_weights": {"vector": 0.5, "graph": 0.3, "behaviour": 0.2},
            "models": DEFAULT_MODELS,
        }
        # Fallback: keep hashes in config when keyring is unavailable.
        if not in_keychain:
            config["password_hash"] = pw_hash

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"Created {CONFIG_FILE}")
        print(f"  api_url  : http://localhost:{port}")
        if in_keychain:
            print("  secrets  : stored in OS keychain (never written to disk)")
        else:
            print("  secrets  : stored in config.json (install keyring for keychain storage)")
        return project_id

    # ── existing config — backfill missing keys ───────────────────────────────
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    changed = False
    for key, val in [
        ("project_id", str(uuid.uuid4())),
        ("api_port", port),
        ("api_url", f"http://localhost:{config.get('api_port', port)}"),
        ("storage", {"encrypt": False}),
        ("retrieval_weights", {"vector": 0.5, "graph": 0.3, "behaviour": 0.2}),
        ("models", DEFAULT_MODELS),
    ]:
        if key not in config:
            config[key] = val
            changed = True

    if changed:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"Updated {CONFIG_FILE} with missing keys.")
    else:
        print(f"{CONFIG_FILE} already up to date.")

    return config["project_id"]


def init_project(
    password: str = DEFAULT_PASSWORD,
    port: int = DEFAULT_PORT,
    no_index: bool = False,
):
    """
    Scaffold .cognirepo/ directories, write config.json, write .gitignore.
    Safe to re-run — existing config is preserved.

    If no_index is False (default), prompt the user to index the repo now.
    Returns (summary_dict, kg, indexer) if indexing was performed,
    otherwise (None, None, None).
    """
    _scaffold_dirs()
    _write_config(password, port)
    _write_gitignore()

    # Read back encrypt flag for status display
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
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
        print("  → Key stored in your OS keychain (never written to disk)")

    if no_index:
        return None, None, None

    print(
        "\nIndex this repo now? It maps every function and class so AI tools\n"
        "can look up symbols and understand code structure.\n"
        "This takes ~5 seconds for most projects. (Y/n): ",
        end="",
        flush=True,
    )

    try:
        answer = input().strip().lower()
    except EOFError:
        answer = ""  # non-interactive environment → default yes

    if answer in ("n", "no"):
        print("Run 'cognirepo index-repo .' when ready.")
        return None, None, None

    from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
    from indexer.ast_indexer import ASTIndexer        # pylint: disable=import-outside-toplevel

    cwd = os.getcwd()
    kg = KnowledgeGraph()
    indexer = ASTIndexer(graph=kg)
    summary = indexer.index_repo(cwd)
    kg.save()

    # seed behaviour from git history
    try:
        from cli.seed import seed_from_git_log  # pylint: disable=import-outside-toplevel
        seed_from_git_log(repo_root=cwd, indexer=indexer)
    except Exception:  # pylint: disable=broad-except
        pass  # seeding is best-effort

    return summary, kg, indexer
