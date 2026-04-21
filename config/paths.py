# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Centralized path management for CogniRepo storage.

Two storage scopes:
  - Project scope : .cognirepo/ in the project root (FAISS, graph, AST, project config)
  - Global scope  : ~/.cognirepo/ (user behaviour, preferences, cross-project settings)
"""
import contextvars
import hashlib
import os
from pathlib import Path

def get_project_hash(project_path: str) -> str:
    """Generate a stable 8-character hash for a project path."""
    abs_path = os.path.abspath(project_path)
    return hashlib.sha256(abs_path.encode()).hexdigest()[:8]

_OVERRIDE_DIR = None
_OVERRIDE_GLOBAL_DIR = None

# Per-task/thread context override — used by CrossRepoRouter to safely switch
# directory context without mutating the process-wide _OVERRIDE_DIR global.
_CTX_DIR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cognirepo_ctx_dir", default=None
)


def set_cognirepo_dir(path: str):
    """Explicitly override the .cognirepo directory (e.g. from CLI flag)."""
    global _OVERRIDE_DIR
    _OVERRIDE_DIR = os.path.abspath(path)


def set_global_dir(path: str):
    """
    Override the global ~/.cognirepo directory.

    Use in tests to redirect user_memory writes away from the real home directory:
        from config.paths import set_global_dir
        set_global_dir(str(tmp_path / ".cognirepo-global"))
    """
    global _OVERRIDE_GLOBAL_DIR  # pylint: disable=global-statement
    _OVERRIDE_GLOBAL_DIR = os.path.abspath(path)

def get_global_dir() -> str:
    """
    Return the global user-level CogniRepo directory.

    Priority:
    1. Explicit override via set_global_dir() (used in tests)
    2. COGNIREPO_GLOBAL_DIR environment variable
    3. Default: ~/.cognirepo/
    """
    if _OVERRIDE_GLOBAL_DIR:
        return _OVERRIDE_GLOBAL_DIR
    env_dir = os.environ.get("COGNIREPO_GLOBAL_DIR")
    if env_dir:
        return os.path.abspath(env_dir)
    return os.path.join(str(Path.home()), ".cognirepo")

def get_global_path(subpath: str) -> str:
    """
    Get an absolute path under the global ~/.cognirepo/ directory.
    Creates the parent directory if needed.
    """
    full_path = os.path.join(get_global_dir(), subpath)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    return full_path

def get_orgs_path() -> str:
    """Return the absolute path to the global organizations registry."""
    return get_global_path("orgs.json")

def get_cognirepo_dir() -> str:
    """
    Determine the base directory for .cognirepo storage.

    Priority:
    1. Per-task context override via _CTX_DIR (used by CrossRepoRouter for thread safety)
    2. Explicit process-wide override via set_cognirepo_dir()
    3. COGNIREPO_DIR environment variable
    4. Local .cognirepo/ directory in CWD (if it exists)
    5. Global ~/.cognirepo/storage/<hash_of_cwd>/
    """
    ctx = _CTX_DIR.get()
    if ctx is not None:
        return ctx

    if _OVERRIDE_DIR:
        return _OVERRIDE_DIR

    # 1. Environment variable override
    env_dir = os.environ.get("COGNIREPO_DIR")
    if env_dir:
        return os.path.abspath(env_dir)

    # 2. Local directory (backward compatibility / explicit local)
    local_dir = os.path.join(os.getcwd(), ".cognirepo")
    if os.path.isdir(local_dir):
        return local_dir

    # 3. Global directory (Issue 2)
    home_dir = str(Path.home())
    project_path = os.getcwd()
    project_hash = get_project_hash(project_path)
    project_name = os.path.basename(project_path)
    
    global_base = os.path.join(home_dir, ".cognirepo", "storage")
    project_storage = os.path.join(global_base, f"{project_name}_{project_hash}")
    return project_storage

def get_cognirepo_dir_for_repo(repo_path: str) -> str:
    """
    Resolve the .cognirepo storage directory for an arbitrary repo path.
    Mirrors get_cognirepo_dir() priority but accepts an explicit path instead
    of using CWD.  Used by CrossRepoRouter and run_server().

    Priority:
    1. Local .cognirepo/ inside repo_path (if it exists)
    2. Global ~/.cognirepo/storage/<name>_<hash>/  (fallback)
    """
    abs_path = os.path.abspath(repo_path)
    local_dir = os.path.join(abs_path, ".cognirepo")
    if os.path.isdir(local_dir):
        return local_dir
    project_name = os.path.basename(abs_path)
    project_hash = get_project_hash(abs_path)
    global_base = os.path.join(str(Path.home()), ".cognirepo", "storage")
    return os.path.join(global_base, f"{project_name}_{project_hash}")


def get_path(subpath: str) -> str:
    """
    Get the absolute path for a file or directory under .cognirepo.
    Automatically ensures the parent directory exists.
    """
    base = get_cognirepo_dir()
    # If subpath is absolute, it might be a mistake or intended. 
    # Usually subpaths are relative like 'graph/graph.pkl'.
    if os.path.isabs(subpath):
        full_path = subpath
    else:
        full_path = os.path.join(base, subpath)
    # Ensure directory exists for files
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    return full_path
