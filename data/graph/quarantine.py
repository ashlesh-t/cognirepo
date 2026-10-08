# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Quarantined knowledge-graph files: tell recoverable from corrupt, restore, apply retention (COGNIREPO-118).

``graph.pkl.corrupt-<unix_ts>`` files are what the loader sets aside when it cannot read ``graph.pkl``.
They are NOT all corrupt. Pre-#97 code quarantined an intact, Fernet-encrypted graph whenever
``keyring`` was missing from the interpreter, so a quarantine can be a perfectly good graph (the case
that prompted this module: three files holding 41,327 / 1,122 and 2 nodes). Each one is therefore
inspected with the *current* key and put in one of three states:

``recoverable``  decrypts (if needed) and unpickles to a graph — can be restored, must never be purged
``locked``       still ciphertext and this interpreter cannot decrypt it (no keyring / wrong key) —
                 might be fine; not judged, not purged
``corrupt``      neither — the only kind retention may remove

Nothing here runs automatically: ``restore`` and ``prune_corrupt`` are explicit, dry-run by default.
"""
from __future__ import annotations

import os
import pickle  # nosec B403 — same trust level as graph.pkl itself: the user's own store
import re
import time
from dataclasses import dataclass

from core.config.atomic import atomic_write
from core.config.lock import store_lock

_FERNET_PREFIX = b"gAAAAA"
_NAME = re.compile(r"^graph\.pkl\.corrupt-(\d+)$")
#: ``prune_corrupt`` leaves a corrupt quarantine alone for this long (days)
DEFAULT_RETENTION_DAYS = 30


@dataclass
class Quarantined:
    path: str
    ts: int                 # unix time encoded in the file name
    size: int
    status: str             # "recoverable" | "locked" | "corrupt"
    nodes: int = 0
    edges: int = 0
    reason: str = ""

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def describe(self) -> str:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.ts))
        if self.status == "recoverable":
            return f"{self.name}  {when}  {self.nodes} nodes / {self.edges} edges  [recoverable]"
        return f"{self.name}  {when}  {self.size} bytes  [{self.status}: {self.reason}]"


def _graph_dir() -> str:
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
    return os.path.dirname(get_path("graph/graph.pkl"))


def inspect(path: str) -> Quarantined:
    """Classify one quarantined file by actually trying to read it with the current key."""
    m = _NAME.match(os.path.basename(path))
    try:
        ts = int(m.group(1)) if m else int(os.path.getmtime(path))
        size = os.path.getsize(path)
    except OSError as exc:          # vanished between listing and inspecting
        return Quarantined(path, int(m.group(1)) if m else 0, 0, "corrupt", reason=f"unreadable: {exc}")
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return Quarantined(path, ts, size, "corrupt", reason=f"unreadable: {exc}")
    from core.security import get_storage_config  # pylint: disable=import-outside-toplevel
    decrypt_error = ""
    try:
        encrypt, project_id = get_storage_config()
    except Exception as exc:  # pylint: disable=broad-except
        encrypt, project_id, decrypt_error = False, "", str(exc)
    if encrypt:
        try:
            from core.security.encryption import get_or_create_key, decrypt_bytes  # pylint: disable=import-outside-toplevel
            raw = decrypt_bytes(raw, get_or_create_key(project_id))
        except Exception as exc:  # pylint: disable=broad-except
            decrypt_error = str(exc) or type(exc).__name__
    if raw.startswith(_FERNET_PREFIX):
        return Quarantined(path, ts, size, "locked",
                           reason=decrypt_error or "encrypted, but storage.encrypt is off in this repo")
    try:
        graph = pickle.loads(raw)  # nosec B301
        nodes, edges = graph.number_of_nodes(), graph.number_of_edges()   # also proves it is a graph
    except Exception as exc:  # pylint: disable=broad-except
        return Quarantined(path, ts, size, "corrupt", reason=f"{type(exc).__name__}: {exc}"[:120])
    return Quarantined(path, ts, size, "recoverable", nodes, edges)


def list_quarantined(graph_dir: str | None = None) -> "list[Quarantined]":
    """Every ``graph.pkl.corrupt-*`` file in the graph directory, newest first, each inspected."""
    d = graph_dir or _graph_dir()
    try:
        names = [n for n in os.listdir(d) if _NAME.match(n)]
    except OSError:
        return []
    items = [inspect(os.path.join(d, n)) for n in names]
    return sorted(items, key=lambda q: q.ts, reverse=True)


def best_candidate(items: "list[Quarantined]") -> "Quarantined | None":
    """The recoverable quarantine to restore: the largest graph, newest among equals.

    Largest (not newest): a later quarantine is often a tiny graph that replaced a big one
    (41,327 nodes first, then 1,122, then 2).
    """
    ok = [q for q in items if q.status == "recoverable"]
    return max(ok, key=lambda q: (q.nodes, q.ts)) if ok else None


def restore(apply: bool = False, force: bool = False) -> "tuple[str, Quarantined | None, str]":
    """Restore the best recoverable quarantine as ``graph.pkl``.

    Returns ``(outcome, chosen, message)`` where outcome is one of ``nothing`` (no quarantines),
    ``none-recoverable``, ``graph-present`` (a readable graph.pkl exists and ``force`` is not set),
    ``dry-run`` or ``restored``. The quarantined file is COPIED, never moved or deleted; a graph.pkl
    that is being replaced (``force``, or an unreadable one) is first kept as ``graph.pkl.replaced-<ts>``.
    """
    d = _graph_dir()
    graph_path = os.path.join(d, "graph.pkl")
    items = list_quarantined(d)
    if not items:
        return "nothing", None, "no quarantined graph files."
    chosen = best_candidate(items)
    if chosen is None:
        return "none-recoverable", None, (
            "none of the quarantined files can be read with the current key "
            "(see `locked` / `corrupt` above)."
        )
    live_ok = os.path.exists(graph_path) and inspect(graph_path).status == "recoverable"
    if live_ok and not force:
        return "graph-present", chosen, (
            "a readable graph.pkl is already in place; restoring would replace it. "
            "Re-run with --force if that is really what you want."
        )
    if not apply:
        return "dry-run", chosen, f"would restore {chosen.name} ({chosen.nodes} nodes) as graph.pkl."
    with store_lock():
        with open(chosen.path, "rb") as fh:
            payload = fh.read()
        if os.path.exists(graph_path):
            os.replace(graph_path, f"{graph_path}.replaced-{int(time.time())}")
        atomic_write(graph_path, payload)
    return "restored", chosen, f"restored {chosen.name} ({chosen.nodes} nodes) as graph.pkl."


def prune_corrupt(days: float = DEFAULT_RETENTION_DAYS, apply: bool = False,
                  now: float | None = None) -> "tuple[list[Quarantined], list[Quarantined]]":
    """Retention: remove quarantines that are genuinely unreadable AND older than ``days``.

    ``recoverable`` and ``locked`` files are never touched. Returns ``(eligible, removed)``;
    ``removed`` is empty unless ``apply``.
    """
    cutoff = (now if now is not None else time.time()) - days * 86400
    eligible = [q for q in list_quarantined() if q.status == "corrupt" and q.ts < cutoff]
    removed: "list[Quarantined]" = []
    if apply:
        for q in eligible:
            try:
                os.unlink(q.path)
                removed.append(q)
            except OSError:
                pass
    return eligible, removed
