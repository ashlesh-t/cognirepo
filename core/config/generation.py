# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Generation pointer for multi-file stores (COGNIREPO-140, ADR 001).

A store made of several files that must be read as a unit (``ast_index.json`` + ``ast.index`` +
``ast_metadata.json`` + ``manifest.json``) cannot be kept consistent by per-file atomic renames:
a reader that loads between two of the renames pairs new files with old ones. This module
publishes the whole group at once instead::

    <root>/
      gen-000007/            complete, immutable once published
      gen-000008/
      CURRENT                "8\\n" — the only mutable name, replaced atomically

Writer (caller holds ``store_lock()``): build ``gen-N+1`` in a hidden scratch directory, fsync
every file, rename the directory into place, then atomically replace ``CURRENT``. A crash at
any step leaves ``CURRENT`` pointing at the previous, intact generation; orphaned scratch
directories are swept later.

Reader (no lock): read ``CURRENT``, open files only under that generation. Generations are
immutable, so the reader sees one snapshot — never a torn or mixed one. Old generations are
garbage-collected by the writer after a grace period (and the newest ``keep`` are always kept);
a reader that loses that race re-reads ``CURRENT`` and retries.

``mirror`` publishes hard links to the current generation's files at legacy flat paths, so code
that still opens ``index/ast_index.json`` directly keeps working with no extra disk use.
"""
import contextlib
import logging
import os
import shutil
import tempfile
import time
import uuid
from typing import Callable, Mapping

from core.config.atomic import atomic_write, _fsync_dir

__all__ = ["GenerationStore", "same_file", "link_or_copy"]

_log = logging.getLogger(__name__)

_CURRENT = "CURRENT"
_PREFIX = "gen-"
_SCRATCH_PREFIX = ".incoming-"


def same_file(a: str, b: str) -> bool:
    """True if both paths exist and are the same inode (hard links of each other)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _fsync_file(path: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def link_or_copy(src: str, dst: str) -> None:
    """Make ``dst`` (not yet existing) a hard link to ``src``; copy where links are unsupported."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _link_over(src: str, dst: str) -> None:
    """Atomically make ``dst`` a hard link to ``src`` (copy where links are unsupported)."""
    tmp = f"{dst}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        link_or_copy(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class GenerationStore:
    """Atomically published generations of a multi-file store rooted at ``root``."""

    def __init__(self, root: str, *, keep: int = 3, grace_secs: float = 60.0):
        self.root = root
        self.keep = max(1, keep)
        self.grace_secs = grace_secs

    # ── reading (lock-free) ──────────────────────────────────────────────────

    def gen_dir(self, n: int) -> str:
        return os.path.join(self.root, f"{_PREFIX}{n:06d}")

    def current(self) -> "int | None":
        """The published generation number, or None if nothing was published / pointer unreadable."""
        try:
            with open(os.path.join(self.root, _CURRENT), encoding="ascii") as f:
                n = int(f.read().strip())
        except (OSError, ValueError):
            return None
        return n if os.path.isdir(self.gen_dir(n)) else None

    def generations(self) -> list[int]:
        """Every complete generation on disk, oldest first."""
        try:
            names = os.listdir(self.root)
        except OSError:
            return []
        out = []
        for name in names:
            if name.startswith(_PREFIX):
                with contextlib.suppress(ValueError):
                    out.append(int(name[len(_PREFIX):]))
        return sorted(out)

    def resolve(self, flat: Mapping[str, str]) -> dict[str, str]:
        """Paths to read ONE consistent group from: ``{name: path}`` for every name in ``flat``.

        ``flat`` maps file name -> its legacy flat path; the first entry is the probe. Files are
        taken from the generation ``CURRENT`` names when the flat probe is a hard link into some
        generation (i.e. the flat layout is managed by us). Otherwise — no generation yet, the
        flat file is missing, or it was edited/replaced by something else — the flat paths are
        returned unchanged, so an out-of-band edit wins exactly as it did before generations.
        Any generation counts for "managed", not just the current one: between the pointer flip
        and the flat re-link a reader must still follow ``CURRENT``, not fall back to flat files
        that are being replaced one by one.
        """
        names = list(flat)
        probe = flat[names[0]]
        for _ in range(3):
            n = self.current()
            if n is None or not os.path.exists(probe):
                break
            d = self.gen_dir(n)
            managed = same_file(probe, os.path.join(d, names[0])) or any(
                same_file(probe, os.path.join(self.gen_dir(g), names[0])) for g in self.generations()
            )
            if not managed:
                break
            if os.path.exists(os.path.join(d, names[0])):
                return {name: os.path.join(d, name) for name in names}
        return dict(flat)

    # ── writing (caller holds store_lock) ────────────────────────────────────

    def publish(
        self,
        writers: Mapping[str, Callable[[str], None]],
        *,
        finalize: "Callable[[str], None] | None" = None,
        mirror: "Mapping[str, str] | None" = None,
    ) -> int:
        """Write a new generation, make it current, return its number.

        ``writers`` maps file name -> ``fn(path)`` that writes that file. ``finalize(dir)`` runs
        after them (e.g. to write a manifest that checksums what was just written) and may add
        more files. ``mirror`` maps file name -> legacy flat path to hard-link to the new file.
        Must be called under the cross-process store lock: it assigns the next number and
        garbage-collects.
        """
        os.makedirs(self.root, exist_ok=True)
        cur = self.current()
        n = max([cur or 0, *self.generations()]) + 1
        scratch = tempfile.mkdtemp(dir=self.root, prefix=_SCRATCH_PREFIX)
        try:
            for name, write in writers.items():
                write(os.path.join(scratch, name))
            if finalize is not None:
                finalize(scratch)
            for name in os.listdir(scratch):
                _fsync_file(os.path.join(scratch, name))
            _fsync_dir(scratch)
            os.chmod(scratch, 0o755)   # mkdtemp is 0700; readers may be other users' agents
            os.rename(scratch, self.gen_dir(n))      # the group appears all at once...
            _fsync_dir(self.root)
        except BaseException:
            shutil.rmtree(scratch, ignore_errors=True)
            raise
        atomic_write(os.path.join(self.root, _CURRENT), f"{n}\n")   # ...and is published here
        if mirror:
            self._mirror(n, mirror)
        self._gc(n)
        return n

    def _mirror(self, n: int, mirror: Mapping[str, str]) -> None:
        d = self.gen_dir(n)
        for name, flat in mirror.items():
            src = os.path.join(d, name)
            if not os.path.exists(src):
                continue
            os.makedirs(os.path.dirname(flat) or ".", exist_ok=True)
            try:
                _link_over(src, flat)
            except OSError as exc:       # the generation is already published; flat is a courtesy
                _log.warning("could not mirror %s to %s: %s", name, flat, exc)

    def _gc(self, current: int) -> None:
        """Drop generations beyond ``keep`` once older than the grace period, plus stale scratch dirs."""
        now = time.time()
        gens = self.generations()
        protected = set(gens[-self.keep:]) | {current}
        for n in gens:
            if n in protected:
                continue
            d = self.gen_dir(n)
            try:
                if now - os.stat(d).st_mtime < self.grace_secs:
                    continue
            except OSError:
                continue
            shutil.rmtree(d, ignore_errors=True)
        try:
            names = os.listdir(self.root)
        except OSError:
            return
        for name in names:
            if not name.startswith(_SCRATCH_PREFIX):
                continue
            d = os.path.join(self.root, name)
            with contextlib.suppress(OSError):
                if now - os.stat(d).st_mtime >= max(self.grace_secs, 600):
                    shutil.rmtree(d, ignore_errors=True)
