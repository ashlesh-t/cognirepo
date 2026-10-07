# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Daemon process management for cognirepo watchers.

Handles fork-to-background, PID file storage under .cognirepo/watchers/,
singleton enforcement (flock + stale-PID detection), heartbeat writing,
crash-recovery loop, systemd unit generation, and interactive log tailing.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import tempfile
import time
from datetime import datetime
from pathlib import Path

from core.config.atomic import atomic_write
from core.config.paths import get_cognirepo_dir, get_cognirepo_dir_for_repo

# fcntl is Linux/macOS only — imported lazily inside functions that need it
# so that importing this module on Windows does not raise ImportError.

# ── stop timing (COGNIREPO-126) ───────────────────────────────────────────────
#: how long a watcher that received SIGTERM may spend on its final flush before it forces exit
GRACEFUL_STOP_SECS = 20.0
#: how long `list --stop` waits for the process to be gone before escalating to SIGKILL
#: (deliberately longer than GRACEFUL_STOP_SECS so the watcher normally exits by itself)
CLI_STOP_WAIT_SECS = 30.0
#: how long to wait after SIGKILL
KILL_WAIT_SECS = 5.0

#: set by the SIGTERM handler. The KeyboardInterrupt the handler raises can be swallowed by any
#: `except`/`finally` it lands in; the flag cannot, so the loop checks it as well.
_STOP_REQUESTED = threading.Event()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_cognirepo_dir(repo_path: str | None = None) -> Path:
    """Resolve the .cognirepo/ directory for *repo_path*, or for cwd if None.

    Previously this walked up from cwd looking for the nearest ancestor
    .cognirepo/, ignoring any explicit repo path the caller already had (e.g.
    the watcher's own watch_path, or --project-dir). A `serve --project-dir
    <parent>` process whose cwd sat inside a child repo would walk up past
    the child's own .cognirepo/ into an unrelated tree — or, worse, land on
    the child's .cognirepo/ while believing it belonged to the parent it was
    told to watch — so its PID/heartbeat file was written into the wrong
    repo's watchers/ dir, colliding with and overwriting that repo's own
    watcher heartbeat. Resolving directly against get_cognirepo_dir_for_repo()
    (or get_cognirepo_dir() for the no-path/cwd case) matches the storage
    resolution already used for FAISS/AST/graph, and never walks ancestors.
    See COGNIREPO-D-C follow-up.
    """
    if repo_path is not None:
        return Path(get_cognirepo_dir_for_repo(repo_path))
    return Path(get_cognirepo_dir())


def _watchers_dir(repo_path: str | None = None) -> Path:
    d = _find_cognirepo_dir(repo_path) / "watchers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pid_file(pid: int, repo_path: str | None = None) -> Path:
    return _watchers_dir(repo_path) / f"{pid}.json"


# ---------------------------------------------------------------------------
# Per-repo watcher lease (COGNIREPO-138)
# ---------------------------------------------------------------------------
# One observer per repo. The right to run it is an OS advisory lock held by the process that
# actually runs the observer — `watch --daemon`, `watch --foreground`, or the thread `serve`
# starts. It is taken in run_watcher_with_crash_guard(), the one place every kind of watcher
# passes through, so there is no check-then-act window: of N processes that start at once,
# exactly one gets it. The kernel drops the lock when the holder exits or is killed, so a crashed
# watcher never leaves a stale lease and another process can take over.
#
# Only the holder writes the registry record (<pid>.json) and the heartbeat, so both identify
# the one live watcher instead of whichever process wrote last. Reuses the graph's WriterLease
# (data/graph/journal.py): lock file `watchers/watcher.writer`, owner pid in `.writer.pid`.

#: how often a `serve` session that lost the lease re-checks whether it can take over
_STANDBY_POLL_SECS = 15.0


class WatcherBusy(RuntimeError):
    """Another process holds this repo's watcher lease."""

    def __init__(self, owner: int | None) -> None:
        self.owner = owner
        super().__init__(f"a watcher already holds the lease{f' (pid {owner})' if owner else ''}")


def acquire_watcher_lease(repo_path: str | None = None, wait: float = 0.0):
    """Take this repo's watcher lease or raise WatcherBusy. Returns the lease; ``release()`` it."""
    from data.graph.journal import JournalBusy, WriterLease  # pylint: disable=import-outside-toplevel
    lease = WriterLease(str(_watchers_dir(repo_path) / "watcher"))
    try:
        lease.acquire(wait=wait)
    except JournalBusy as exc:
        raise WatcherBusy(exc.pid) from exc
    return lease


def wait_for_watcher_lease(repo_path: str | None = None, poll: float | None = None,
                           stop: "threading.Event | None" = None):
    """Stand by until this process can hold the lease (takeover after the holder died).

    Returns the lease, or None if ``stop`` was set first. Cheap while waiting: nothing is loaded.
    """
    poll = _STANDBY_POLL_SECS if poll is None else poll
    while True:
        try:
            return acquire_watcher_lease(repo_path)
        except WatcherBusy:
            pass
        if stop is not None:
            if stop.wait(poll):
                return None
        else:
            time.sleep(poll)


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

_HEARTBEAT_INTERVAL = 30  # seconds between heartbeat writes
_HEARTBEAT_STALE_THRESHOLD = 120  # seconds before doctor warns


def _heartbeat_file(repo_path: str | None = None) -> Path:
    return _watchers_dir(repo_path) / "heartbeat"


def write_heartbeat(pid: int, watcher_path: str) -> None:
    """Write (overwrite) the heartbeat file with current timestamp and PID."""
    data = {
        "pid": pid,
        "path": watcher_path,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    atomic_write(str(_heartbeat_file(watcher_path)), json.dumps(data), fsync=False)  # status file


def read_heartbeat(repo_path: str | None = None) -> dict | None:
    """Return parsed heartbeat dict, or None if the file is absent/corrupt."""
    hb = _heartbeat_file(repo_path)
    if not hb.exists():
        return None
    try:
        return json.loads(hb.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def read_heartbeat_for_path(repo_path: str) -> dict | None:
    """Return the heartbeat only if it was written by a watcher for *repo_path*.

    The heartbeat file now lives under that repo's own resolved storage dir
    (get_cognirepo_dir_for_repo(repo_path)/watchers/heartbeat), so a foreign
    process watching a different tree can no longer land in the same slot in
    the first place. The recorded-`path` match is kept as a defense-in-depth
    check against stale/pre-fix heartbeat files. See COGNIREPO-D-C.
    """
    hb = read_heartbeat(repo_path)
    if hb is None:
        return None
    recorded = hb.get("path")
    if not recorded:
        return None  # pre-D-C heartbeat with no identity — cannot be trusted
    try:
        if os.path.abspath(recorded) != os.path.abspath(repo_path):
            return None
    except (TypeError, ValueError):
        return None
    return hb


def clear_heartbeat_if_owned(pid: int, repo_path: str | None = None) -> None:
    """Remove the heartbeat file if *pid* is the process that last wrote it.

    Leaving our own heartbeat behind on shutdown is what let a dead watcher
    keep reporting "Heartbeat: OK" for the next two minutes.
    """
    hb = read_heartbeat(repo_path)
    if hb is not None and hb.get("pid") == pid:
        try:
            _heartbeat_file(repo_path).unlink(missing_ok=True)
        except OSError:
            pass


def heartbeat_age_seconds_for_path(repo_path: str) -> float | None:
    """Seconds since the last heartbeat *for repo_path*, else None.

    Path-scoped counterpart to heartbeat_age_seconds(). See COGNIREPO-D-C.
    """
    return _heartbeat_age(read_heartbeat_for_path(repo_path))


def heartbeat_age_seconds(repo_path: str | None = None) -> float | None:
    """Return seconds since the last heartbeat, or None if no heartbeat file."""
    return _heartbeat_age(read_heartbeat(repo_path))


def _heartbeat_age(hb: dict | None) -> float | None:
    """Seconds since *hb* was stamped, or None if absent/unparseable."""
    if hb is None:
        return None
    try:
        ts_str = hb.get("timestamp", "")
        from datetime import timezone  # pylint: disable=import-outside-toplevel
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(tz=timezone.utc)
        return (now - ts).total_seconds()
    except (ValueError, TypeError):
        return None


def start_heartbeat_thread(pid: int, watcher_path: str) -> threading.Thread:
    """
    Start a daemon thread that updates the heartbeat file every
    _HEARTBEAT_INTERVAL seconds.  Thread is automatically killed when the
    process exits (daemon=True).

    The thread has a stop event (``thread.stop_event``): shutdown MUST stop and join it
    (``stop_heartbeat_thread``) BEFORE clearing the heartbeat file. Otherwise a write that is
    still in flight — or the very first write, if the watcher exits straight away — lands after
    the cleanup and leaves a heartbeat for a dead watcher, which then keeps reporting
    "Heartbeat: OK" (the race behind the intermittent CI failure of
    test_pid_file_and_heartbeat_removed_on_clean_exit).
    """
    stop = threading.Event()

    def _loop():
        while not stop.is_set():
            try:
                write_heartbeat(pid, watcher_path)
            except OSError:
                pass
            if stop.wait(_HEARTBEAT_INTERVAL):   # wakes immediately when asked to stop
                break

    t = threading.Thread(target=_loop, name="cognirepo-heartbeat", daemon=True)
    t.stop_event = stop  # type: ignore[attr-defined]
    t.start()
    return t


def stop_heartbeat_thread(thread: threading.Thread, timeout: float = 5.0) -> None:
    """Stop the heartbeat thread and wait until no write can still be in flight."""
    stop = getattr(thread, "stop_event", None)
    if stop is not None:
        stop.set()
    thread.join(timeout)


# ---------------------------------------------------------------------------
# Singleton enforcement (TASK-009)
# ---------------------------------------------------------------------------

def is_watcher_running_for_path(repo_path: str) -> dict | None:
    """
    Return the watcher record if a live daemon is already watching *repo_path*,
    or None if the path is unwatched (or the PID file is stale).

    Stale PID files (process dead after reboot) are deleted automatically.
    """
    abs_path = os.path.abspath(repo_path)
    for f in sorted(_watchers_dir(repo_path).glob("*.json")):
        try:
            rec = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            f.unlink(missing_ok=True)
            continue

        if os.path.abspath(rec.get("path", "")) != abs_path:
            continue

        pid = rec.get("pid", -1)
        if _is_alive(pid):
            return rec

        # Stale PID file — clean up
        f.unlink(missing_ok=True)
    return None


def flock_register_watcher(pid: int, name: str, path: str, log_path: str) -> None:
    """Write the registry record for a watcher (kept for callers/tests; same as register_watcher).

    This used to flock a *per-pid* file, which excluded nothing — the mutual exclusion is the
    per-repo lease (see above), taken by the process that runs the observer.
    """
    register_watcher(pid, name, path, log_path)


# ---------------------------------------------------------------------------
# Crash-recovery loop (TASK-008)
# ---------------------------------------------------------------------------

def run_watcher_with_crash_guard(
    create_fn,           # callable() -> observer
    stop_fn,             # callable(observer) -> None
    watcher_path: str,
    session_id: str,
    restart_delay: float = 5.0,
    lease=None,          # an already-held watcher lease (see wait_for_watcher_lease); else taken here
    registration: dict | None = None,   # {"name", "log", "kind"?} — recorded once the lease is held
) -> bool:
    """
    Run *create_fn()* in a while-True crash-recovery loop — as THE watcher for *watcher_path*.

    COGNIREPO-138: takes the repo's watcher lease first. If another process holds it, nothing is
    started and False is returned; otherwise the registry record (if ``registration`` is given) and
    the heartbeat are written by this process only, and the lease is released on the way out.

    If the observer raises an unhandled exception it is logged and the watcher
    is restarted after *restart_delay* seconds.  This prevents silent death
    after OOM or unexpected errors.

    Parameters
    ----------
    create_fn       : zero-argument callable that starts and returns an observer
    stop_fn         : callable(observer) called to cleanly stop before restart
    watcher_path    : repo root (for log messages)
    session_id      : watcher session ID (for log messages)
    restart_delay   : seconds to wait before restarting after a crash
    """
    pid = os.getpid()
    if lease is None:
        try:
            lease = acquire_watcher_lease(watcher_path)
        except WatcherBusy as busy:
            print(f"[watcher:{session_id}] another watcher already holds the lease for {watcher_path}"
                  f"{f' (pid {busy.owner})' if busy.owner else ''} — not starting a second one.",
                  file=sys.stderr, flush=True)
            return False
    try:
        if registration:
            register_watcher(pid, registration["name"], watcher_path,
                             registration.get("log", ""), registration.get("kind"))
        _guarded_run(create_fn, stop_fn, watcher_path, session_id, restart_delay, lease)
    finally:
        lease.release()
    return True


def _guarded_run(create_fn, stop_fn, watcher_path, session_id, restart_delay, lease) -> None:
    """Body of run_watcher_with_crash_guard() once the lease is held."""
    pid = os.getpid()
    heartbeat = start_heartbeat_thread(pid, watcher_path)
    _STOP_REQUESTED.clear()
    watchdog: list[threading.Timer] = []

    def _cleanup_registration() -> None:
        # First: stop and join the heartbeat thread, so no write can land after the cleanup below
        # and recreate a heartbeat for a dead watcher. Used by the normal exit AND the forced exit.
        stop_heartbeat_thread(heartbeat)
        try:
            _pid_file(pid, watcher_path).unlink(missing_ok=True)
        except OSError:
            pass
        clear_heartbeat_if_owned(pid, watcher_path)
        lease.release()   # idempotent; also covers the forced-exit path

    def _force_exit(reason: str) -> None:
        print(f"[watcher:{session_id}] {reason} — forcing exit.", file=sys.stderr, flush=True)
        _cleanup_registration()
        os._exit(1)  # pylint: disable=protected-access

    # Translate SIGTERM into the KeyboardInterrupt this loop already handles.
    # `watch --stop` sends SIGTERM; without a handler Python's default killed
    # the process outright, so neither stop_fn()'s final flush nor the cleanup
    # below ever ran and .cognirepo/watchers/<pid>.json survived the daemon.
    # Installed here (in the daemonized process itself) rather than in the
    # parent, which a double-fork does not propagate. See COGNIREPO-D-E.
    #
    # COGNIREPO-126: shutdown must be bounded and must not be swallowable.
    #  * the first SIGTERM sets _STOP_REQUESTED (checked by the loop even if the
    #    KeyboardInterrupt is swallowed), arms a watchdog that forces exit if the final
    #    flush hangs, then raises KeyboardInterrupt;
    #  * a second SIGTERM means "now": exit immediately (registration cleaned up).
    def _on_sigterm(_signum, _frame):
        if _STOP_REQUESTED.is_set():
            _force_exit("second stop signal")
        _STOP_REQUESTED.set()
        timer = threading.Timer(GRACEFUL_STOP_SECS,
                                lambda: _force_exit(f"graceful stop exceeded {GRACEFUL_STOP_SECS:.0f}s"))
        timer.daemon = True
        timer.start()
        watchdog.append(timer)
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except (ValueError, OSError):
        pass  # not on the main thread — the parent's handler still applies

    try:
        _run_watcher_loop(create_fn, stop_fn, watcher_path, session_id, restart_delay, pid)
    finally:
        for timer in watchdog:
            timer.cancel()
        _cleanup_registration()


def _run_watcher_loop(create_fn, stop_fn, watcher_path, session_id, restart_delay, pid) -> None:
    """Crash-recovery loop body — see run_watcher_with_crash_guard()."""
    while not _STOP_REQUESTED.is_set():
        observer = None
        try:
            observer = create_fn()
            print(f"[watcher:{session_id}] started (pid={pid}, path={watcher_path})", file=sys.stderr, flush=True)
            while observer.is_alive() and not _STOP_REQUESTED.is_set():
                time.sleep(1)
            if _STOP_REQUESTED.is_set():
                # the KeyboardInterrupt may have been swallowed on the way here: stop cleanly anyway
                print(f"[watcher:{session_id}] stop requested.", file=sys.stderr, flush=True)
                if observer is not None:
                    try:
                        stop_fn(observer)
                    except Exception:  # pylint: disable=broad-except
                        pass
                break
            print(f"[watcher:{session_id}] observer exited cleanly.", file=sys.stderr, flush=True)
            break  # clean exit — don't restart
        except KeyboardInterrupt:
            print(f"[watcher:{session_id}] stopped by user.", file=sys.stderr, flush=True)
            # COGNIREPO-D05: this is the primary real-world shutdown path
            # (Ctrl+C / SIGTERM both raise KeyboardInterrupt here) — without
            # calling stop_fn(), _flush_and_stop_observer()'s flush() never
            # runs and any debounced-but-unflushed edit is silently dropped.
            if observer is not None:
                try:
                    stop_fn(observer)
                except Exception:  # pylint: disable=broad-except
                    pass
            break
        except Exception as exc:  # pylint: disable=broad-except
            print(
                f"[watcher:{session_id}] CRASH: {exc} — restarting in {restart_delay}s",
                file=sys.stderr, flush=True,
            )
            if observer is not None:
                try:
                    stop_fn(observer)
                except Exception:  # pylint: disable=broad-except
                    pass
            if _STOP_REQUESTED.is_set():
                break  # a stop arrived while we were crashing: don't restart
            time.sleep(restart_delay)


# ---------------------------------------------------------------------------
# Systemd unit generation (TASK-008 Layer 2)
# ---------------------------------------------------------------------------

def generate_systemd_unit(repo_path: str) -> str:
    """
    Generate a systemd user service unit file content for the watcher daemon.

    Returns the unit file content as a string.  The caller should write it to
    ``.cognirepo/cognirepo-watcher.service``.
    """
    import shlex  # pylint: disable=import-outside-toplevel
    import shutil  # pylint: disable=import-outside-toplevel
    cognirepo_bin = shutil.which("cognirepo") or "cognirepo"
    abs_repo = os.path.abspath(repo_path)
    # `watch --foreground` is a real foreground mode (COGNIREPO-125): it registers itself, runs
    # under the crash guard and logs to stderr, which systemd sends to the journal. Quoting keeps
    # a repo path with spaces as ONE argument (systemd honours shell-style quotes in ExecStart).
    exec_start = " ".join(shlex.quote(a) for a in (cognirepo_bin, "watch", "--path", abs_repo, "--foreground"))
    unit = f"""\
[Unit]
Description=CogniRepo file watcher for {abs_repo}
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=10
# SIGTERM triggers the watcher's final flush (bounded by GRACEFUL_STOP_SECS = {GRACEFUL_STOP_SECS:.0f}s)
TimeoutStopSec=60
WorkingDirectory={abs_repo}

[Install]
WantedBy=default.target
"""
    return unit


def write_systemd_unit(repo_path: str) -> Path:
    """
    Write the systemd unit file to ``.cognirepo/cognirepo-watcher.service``.
    Returns the path to the written file.
    """
    cognirepo_dir = _find_cognirepo_dir(repo_path)
    unit_path = cognirepo_dir / "cognirepo-watcher.service"
    unit_path.write_text(generate_systemd_unit(repo_path))
    return unit_path


# ---------------------------------------------------------------------------
# Daemonize
# ---------------------------------------------------------------------------

#: environment variable a detached watcher reads to record its log file in the registry
WATCHER_LOG_ENV = "COGNIREPO_WATCHER_LOG"


def spawn_detached_watcher(repo_path: str, log_path: str) -> int:
    """Start ``cognirepo watch --foreground`` as a new, detached process and return its pid.

    COGNIREPO-127: this replaces the old double-fork ``daemonize()``. Forking the calling process
    copied its whole heap into the daemon — after ``index-repo`` that is the embedding model, the
    FAISS index and every parsed AST (3.3 GB RSS, against ~100 MB for a fresh watcher on the same
    index) — and forking a process that already runs threads and native libraries (ONNX, FAISS) is
    unsafe: the forked daemon was seen ignoring SIGTERM for 30 s. A fresh interpreter inherits
    nothing, loads only what a watcher needs, and registers itself under the per-repo lease (#138).

    stdin is /dev/null, stdout/stderr append to ``log_path``, and the child is a session leader
    (``start_new_session``) so it survives the terminal that started it. Requires Python >= 3.11
    (``-P``), which the project already does.
    """
    env = dict(os.environ)
    env["COGNIREPO_DIR"] = str(get_cognirepo_dir())      # same store as the caller, even if cwd differs
    env[WATCHER_LOG_ENV] = log_path
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(os.devnull, "rb") as devnull, open(log_path, "ab") as log:
        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            # -P: do not put the cwd (= the user's repo) on sys.path. Without it a repo that has its
            # own `interface/` package would shadow cognirepo's and the watcher could not start.
            [sys.executable, "-P", "-m", "interface.cli.main", "watch", "--foreground", "--path", repo_path],
            stdin=devnull, stdout=log, stderr=log, cwd=repo_path, env=env,
            start_new_session=True, close_fds=True,
        )
    return proc.pid


# ---------------------------------------------------------------------------
# PID registry
# ---------------------------------------------------------------------------

def register_watcher(pid: int, name: str, path: str, log_path: str, kind: str | None = None) -> None:
    """Write a JSON PID file for a running watcher daemon.

    ``kind="embedded"`` marks a watcher that is a thread inside another process (the MCP server):
    ``list --stop`` must not signal that pid — it would kill the agent's server, not the watcher.
    """
    record = {
        "pid": pid,
        "name": name,
        "path": os.path.abspath(path),
        "started": datetime.now().isoformat(timespec="seconds"),
        "log": log_path,
    }
    if kind:
        record["kind"] = kind
    atomic_write(str(_pid_file(pid, path)), json.dumps(record, indent=2), fsync=False)  # status file


def _is_alive(pid: int) -> bool:
    """True if ``pid`` is a running process. A zombie (exited, not yet reaped by its parent) is
    NOT alive: ``kill(pid, 0)`` still succeeds on one, which made a watcher that had really
    stopped look "running" forever and made ``list --stop`` time out (COGNIREPO-126)."""
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            # "<pid> (<comm>) <state> ..." — comm may contain spaces/parens, so split after the LAST ')'
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True  # no /proc (macOS) or unreadable: fall back to "kill succeeded"


def list_watchers() -> list[dict]:
    """Return all registered watcher daemons with a live 'status' field."""
    watchers = []
    for f in sorted(_watchers_dir().glob("*.json")):
        try:
            rec = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        rec["status"] = "running" if _is_alive(rec["pid"]) else "stopped"
        # Clean up stale PID files automatically
        if rec["status"] == "stopped":
            f.unlink(missing_ok=True)
            continue
        watchers.append(rec)
    return watchers


def find_watcher(name_or_pid: str) -> dict | None:
    """Find a watcher by PID (numeric string) or name (partial match)."""
    all_w = list_watchers()
    # exact PID match
    if name_or_pid.isdigit():
        pid = int(name_or_pid)
        for w in all_w:
            if w["pid"] == pid:
                return w
    # name substring match
    for w in all_w:
        if name_or_pid in w["name"]:
            return w
    return None


def _wait_until_dead(pid: int, timeout: float, interval: float = 0.1) -> bool:
    """Poll until ``pid`` is gone. True if it exited within ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    while True:
        if not _is_alive(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def _looks_like_cognirepo(pid: int) -> bool:
    """Guard before SIGKILL: is ``pid`` still a cognirepo process, not a recycled pid?

    Reads /proc/<pid>/cmdline. Where /proc is unavailable (macOS) we can't tell, so we allow it.
    """
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return not Path("/proc").exists()
    return b"cognirepo" in cmdline or b"interface.cli" in cmdline


def stop_watcher_and_wait(
    name_or_pid: str, timeout: float = CLI_STOP_WAIT_SECS, kill_wait: float = KILL_WAIT_SECS,
) -> str:
    """Stop a watcher and report what actually happened (COGNIREPO-126).

    Returns ``"not_found"``, ``"stopped"`` (exited after SIGTERM), ``"killed"`` (needed SIGKILL),
    ``"embedded"`` (it is a thread in an MCP server — nothing was signalled) or ``"failed"``
    (still alive — the registration is deliberately left in place).

    Previously this sent SIGTERM, deleted the PID file straight away and reported success while
    the process was still flushing (or ignoring the signal). The registry then said "not
    running", so ``watch --ensure-running`` started a SECOND watcher on the same repo — two
    writers on one graph. The registration is now removed only once the process is really gone.
    """
    w = find_watcher(name_or_pid)
    if w is None:
        return "not_found"
    if w.get("kind") == "embedded":
        return "embedded"   # a thread inside `cognirepo serve`: signalling the pid would kill the server
    pid, path = int(w["pid"]), w.get("path")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # raced with a normal exit
    except PermissionError:
        return "failed"

    outcome = "stopped"
    if not _wait_until_dead(pid, timeout):
        if not _looks_like_cognirepo(pid):
            return "failed"  # the pid now belongs to something else — never SIGKILL a stranger
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            return "failed"
        if not _wait_until_dead(pid, kill_wait):
            return "failed"
        outcome = "killed"

    # The process is gone: only now clear what it may have left behind (a SIGKILLed watcher can't).
    try:
        _pid_file(pid, path).unlink(missing_ok=True)
    except OSError:
        pass
    clear_heartbeat_if_owned(pid, path)
    return outcome


def stop_watcher(name_or_pid: str) -> bool:
    """Stop a watcher. Returns True only if the process is really gone (see stop_watcher_and_wait)."""
    return stop_watcher_and_wait(name_or_pid) in ("stopped", "killed")


# ---------------------------------------------------------------------------
# Interactive log view (tail -f equivalent)
# ---------------------------------------------------------------------------

def view_watcher_logs(name_or_pid: str) -> None:
    """Interactively tail the log of a watcher daemon (blocks until Ctrl+C)."""
    w = find_watcher(name_or_pid)
    if w is None:
        print(f"No running watcher found matching {name_or_pid!r}.", file=sys.stderr)
        sys.exit(1)

    log_path = w.get("log", "")
    if not log_path or not os.path.exists(log_path):
        print(f"Log file not found: {log_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[cognirepo] Viewing logs for watcher '{w['name']}' (PID {w['pid']})")
    print(f"[cognirepo] Log: {log_path}  |  Ctrl+C to stop viewing\n")

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            # Print existing content first
            existing = fh.read()
            if existing:
                print(existing, end="")

            # Follow new output
            while True:
                line = fh.readline()
                if line:
                    print(line, end="", flush=True)
                else:
                    if not _is_alive(w["pid"]):
                        print("\n[cognirepo] Watcher process has exited.")
                        break
                    time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[cognirepo] Stopped viewing.")


# ---------------------------------------------------------------------------
# Pretty-print process list
# ---------------------------------------------------------------------------

def print_watcher_list() -> None:
    """Print a formatted table of all running watcher daemons."""
    watchers = list_watchers()
    if not watchers:
        print("No running watcher daemons found.")
        return

    header = f"{'PID':<8} {'NAME':<36} {'PATH':<40} {'STARTED':<20} STATUS"
    print(header)
    print("-" * len(header))
    for w in watchers:
        pid = str(w["pid"])
        name = w["name"][:35]
        path = w["path"][:39]
        started = w["started"][:19]
        status = w["status"] + (" (in serve)" if w.get("kind") == "embedded" else "")
        print(f"{pid:<8} {name:<36} {path:<40} {started:<20} {status}")
