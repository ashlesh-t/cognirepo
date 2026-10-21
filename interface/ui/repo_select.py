# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""``?repo=`` for the control API's read-only routes (#210 follow-up).

A client names a repo by exact path or unique directory name, and it is resolved **only** against the
global registry, org links and the repo this server was started for (``core.config.repo_registry.resolve``).
It is never turned into a filesystem path by the request, so ``?repo=/etc`` or ``?repo=../x`` is simply
``unknown_repo``. Writes (services, settings) stay bound to the served repo.
"""
from __future__ import annotations

import os

from core.config import repo_registry

REPO_DESC = ("Repo to read: an exact path or unique directory name from `GET /api/v1/repos`. "
             "Omitted = the repo this server was started for. Unknown names are `404 unknown_repo`.")


class RepoSelectError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def select(repo: str | None, served_root: str) -> tuple[str, str]:
    """``(root, store)`` for the requested repo (the served one when ``repo`` is empty)."""
    from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
    served = os.path.abspath(served_root)
    if not repo:
        return served, str(get_cognirepo_dir_for_repo(served))
    row, err = repo_registry.resolve(repo, served)
    if row is None:
        raise RepoSelectError(409 if err == "ambiguous_repo" else 404, err or "unknown_repo")
    root = row["path"]
    if not os.path.isdir(root):
        raise RepoSelectError(404, "repo_missing")
    store = str(get_cognirepo_dir_for_repo(root))
    if root != served and not os.path.isdir(store):
        raise RepoSelectError(404, "repo_not_initialised")
    return root, store


def require_served(repo: str | None, served_root: str) -> None:
    """Writes and per-process state only exist for the served repo: naming another one is a conflict."""
    if not repo:
        return
    root, _ = select(repo, served_root)
    if root != os.path.abspath(served_root):
        raise RepoSelectError(409, "not_served_repo")
