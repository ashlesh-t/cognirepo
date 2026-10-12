# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""Process helpers that behave on POSIX *and* Windows (#148).

The pitfalls this hides: on Windows ``os.kill(pid, 0)`` does not probe — any signal other than
CTRL_C/CTRL_BREAK calls ``TerminateProcess`` — so a liveness check would kill the watcher it was
asking about; ``signal.SIGKILL`` does not exist; ``start_new_session`` is POSIX-only.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys

IS_WINDOWS = sys.platform in ("win32", "cygwin")

_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _windows_alive(pid: int) -> bool:
    import ctypes  # pylint: disable=import-outside-toplevel
    from ctypes import wintypes  # pylint: disable=import-outside-toplevel
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # access denied -> it exists but is not ours; anything else -> no such process
        return ctypes.get_last_error() == 5
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def pid_alive(pid: int) -> bool:
    """True if ``pid`` is a running process. Safe to call on Windows (never signals anything)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if IS_WINDOWS:
        return _windows_alive(pid)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True      # exists, owned by someone else
    except (ProcessLookupError, OSError, ValueError):
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            # "<pid> (<comm>) <state> ..." — comm may contain spaces/parens, so split after the LAST ')'
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"   # a zombie is not alive
    except (OSError, IndexError):
        return True      # no /proc (macOS) or unreadable: fall back to "kill succeeded"


def request_stop(pid: int) -> None:
    """Ask ``pid`` to stop. POSIX: SIGTERM (the watcher flushes first). Windows has no catchable
    signal for a detached console-less process, so this is ``TerminateProcess`` — no final flush;
    the catch-up scan on the next start recovers the unflushed edits (#146)."""
    os.kill(pid, signal.SIGTERM)


def force_kill(pid: int) -> None:
    """Last resort. ``signal.SIGKILL`` where it exists, else the same hard terminate."""
    os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))


def detach_kwargs() -> dict:
    """``Popen`` kwargs that detach a child from this terminal/session, fork-free."""
    if IS_WINDOWS:
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        return {"creationflags": flags, "close_fds": True}
    return {"start_new_session": True, "close_fds": True}
