# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Explicit encrypt / decrypt pass over the JSON stores that #186 added to ``storage.encrypt``.

Stores migrate lazily on their next save anyway; this makes the switch complete and
reversible on demand. Every file is verified before it is replaced:
    plaintext -> encode -> decode == plaintext     (the bytes on disk are only swapped after that)
so a missing keyring or a bad key aborts that file untouched instead of destroying it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.config.atomic import atomic_write
from core.config.lock import store_lock
from core.config.safe_read import StoreUnreadableError, looks_encrypted
from core.security.store_crypto import decode_store, encode_store


@dataclass
class Result:
    path: str
    action: str  # "encrypted" | "decrypted" | "unchanged" | "skipped" | "failed"
    detail: str = ""


def _targets() -> list[tuple[str, str | None]]:
    """(path, key_id) of every migratable store: project + global learnings, org project memory."""
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
    out: list[tuple[str, str | None]] = [(os.path.join(get_path("learnings"), "learnings.json"), None)]
    home = Path(os.environ.get("COGNIREPO_GLOBAL_DIR", str(Path.home() / ".cognirepo")))
    out.append((str(home / "learnings" / "learnings.json"), "cognirepo-global-learnings"))
    projects = home / "projects"
    if projects.is_dir():
        for meta in sorted(projects.glob("*/*/memory/semantic_metadata.json")):
            org, proj = meta.parts[-4], meta.parts[-3]
            out.append((str(meta), f"cognirepo-project-memory:{org}/{proj}"))
    return out


def migrate(*, decrypt: bool = False, dry_run: bool = False) -> list[Result]:
    results: list[Result] = []
    for path, key_id in _targets():
        if not os.path.exists(path):
            continue
        try:
            with store_lock():
                with open(path, "rb") as f:
                    raw = f.read()
                if decrypt:
                    if not looks_encrypted(raw):
                        results.append(Result(path, "unchanged", "already plaintext"))
                        continue
                    plain = decode_store(raw, path, key_id=key_id)
                    new = plain
                    action = "decrypted"
                else:
                    if looks_encrypted(raw):
                        decode_store(raw, path, key_id=key_id)  # prove we hold the key
                        results.append(Result(path, "unchanged", "already encrypted"))
                        continue
                    plain = raw
                    new = encode_store(plain, key_id=key_id, enabled=True)
                    if decode_store(new, path, key_id=key_id) != plain:
                        raise ValueError("round-trip verification failed")
                    action = "encrypted"
                if not dry_run:
                    atomic_write(path, new)
                results.append(Result(path, action, "dry run" if dry_run else ""))
        except StoreUnreadableError as exc:
            results.append(Result(path, "skipped", f"locked — {exc.reason}"))
        except Exception as exc:  # pylint: disable=broad-except
            results.append(Result(path, "failed", f"{type(exc).__name__}: {exc}"))
    return results
