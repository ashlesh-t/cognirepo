"""Daemon process management for cognirepo watchers.

Handles fork-to-background, PID file storage under .cognirepo/watchers/,
singleton enforcement (flock + stale-PID detection), heartbeat writing,
crash-recovery loop, systemd unit generation, and interactive log tailing.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_cognirepo_dir() -> Path:
    """Walk up from cwd to find the nearest .cognirepo/ directory."""
    here = Path.cwd()
    for parent in [here, *here.parents]:
        candidate = parent / ".cognirepo"
        if candidate.is_dir():
            return candidate
    # Fall back to cwd/.cognirepo (will be created if needed)
    return here / ".cognirepo"


def _watchers_dir() -> Path:
    d = _find_cognirepo_dir() / "watchers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pid_file(pid: int) -> Path:
    return _watchers_dir() / f"{pid}.json"


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

_HEARTBEAT_INTERVAL = 30  # seconds between heartbeat writes
_HEARTBEAT_STALE_THRESHOLD = 120  # seconds before doctor warns


def _heartbeat_file() -> Path:
    return _watchers_dir() / "heartbeat"


def write_heartbeat(pid: int, watcher_path: str) -> None:
    """Write (overwrite) the heartbeat file with current timestamp and PID."""
    data = {
        "pid": pid,
        "path": watcher_path,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    _heartbeat_file().write_text(json.dumps(data))


def read_heartbeat() -> dict | None:
    """Return parsed heartbeat dict, or None if the file is absent/corrupt."""
    hb = _heartbeat_file()
    if not hb.exists():
        return None
    try:
        return json.loads(hb.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def heartbeat_age_seconds() -> float | None:
    """Return seconds since the last heartbeat, or None if no heartbeat file."""
    hb = read_heartbeat()
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
    """
    def _loop():
        while True:
            try:
                write_heartbeat(pid, watcher_path)
            except OSError:
                pass
            time.sleep(_HEARTBEAT_INTERVAL)

    t = threading.Thread(target=_loop, name="cognirepo-heartbeat", daemon=True)
    t.start()
    return t


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
    for f in sorted(_watchers_dir().glob("*.json")):
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
    """
    Atomically write a JSON PID file for a running watcher using flock(LOCK_EX).
    This prevents two concurrent `cognirepo watch` invocations from both
    thinking they won the race to start.
    """
    record = {
        "pid": pid,
        "name": name,
        "path": os.path.abspath(path),
        "started": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "log": log_path,
    }
    pid_path = _pid_file(pid)
    # Open with O_CREAT|O_WRONLY; flock blocks until we hold exclusive lock
    fd = os.open(str(pid_path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, json.dumps(record, indent=2).encode())
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ---------------------------------------------------------------------------
# Crash-recovery loop (TASK-008)
# ---------------------------------------------------------------------------

def run_watcher_with_crash_guard(
    create_fn,           # callable() -> observer
    stop_fn,             # callable(observer) -> None
    watcher_path: str,
    session_id: str,
    restart_delay: float = 5.0,
) -> None:
    """
    Run *create_fn()* in a while-True crash-recovery loop.

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
    start_heartbeat_thread(pid, watcher_path)

    while True:
        observer = None
        try:
            observer = create_fn()
            print(f"[watcher:{session_id}] started (pid={pid}, path={watcher_path})", flush=True)
            while observer.is_alive():
                time.sleep(1)
            print(f"[watcher:{session_id}] observer exited cleanly.", flush=True)
            break  # clean exit — don't restart
        except KeyboardInterrupt:
            print(f"[watcher:{session_id}] stopped by user.", flush=True)
            break
        except Exception as exc:  # pylint: disable=broad-except
            print(
                f"[watcher:{session_id}] CRASH: {exc} — restarting in {restart_delay}s",
                flush=True,
            )
            if observer is not None:
                try:
                    stop_fn(observer)
                except Exception:  # pylint: disable=broad-except
                    pass
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
    import shutil  # pylint: disable=import-outside-toplevel
    cognirepo_bin = shutil.which("cognirepo") or "cognirepo"
    abs_repo = os.path.abspath(repo_path)
    unit = f"""\
[Unit]
Description=CogniRepo file watcher for {abs_repo}
After=network.target

[Service]
Type=simple
ExecStart={cognirepo_bin} watch --path {abs_repo} --daemon-foreground
Restart=on-failure
RestartSec=10
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
    cognirepo_dir = _find_cognirepo_dir()
    unit_path = cognirepo_dir / "cognirepo-watcher.service"
    unit_path.write_text(generate_systemd_unit(repo_path))
    return unit_path


# ---------------------------------------------------------------------------
# Daemonize
# ---------------------------------------------------------------------------

def daemonize(log_path: str) -> int:
    """Fork the calling process into the background.

    Returns:
        In the *parent*: the child PID (> 0) — caller should print status and exit.
        In the *child*:  0 — caller should continue running the watcher.

    The grandchild (actual daemon) redirects stdout/stderr to *log_path* and
    detaches from the controlling terminal via double-fork + setsid().
    """
    # First fork
    try:
        pid = os.fork()
    except OSError as exc:
        raise RuntimeError(f"fork #1 failed: {exc}") from exc

    if pid > 0:
        # Original parent: wait briefly so the grandchild PID is stable, then return it.
        # We cannot know the grandchild PID directly, so we use a small pipe.
        # The intermediate child will write grandchild PID to a temp file and exit.
        # Simple approach: use a pipe.
        r_fd, w_fd = os.pipe()
        # Re-do: we need the pipe BEFORE forking. Use a different design:
        # Write grandchild PID to a side-channel temp file keyed on intermediate PID.
        _wait_file = Path(f"/tmp/.cognirepo_daemon_{pid}")
        # Wait up to 2 s for the grandchild to write its PID
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if _wait_file.exists():
                try:
                    grandchild_pid = int(_wait_file.read_text().strip())
                    _wait_file.unlink(missing_ok=True)
                    os.waitpid(pid, 0)  # reap intermediate child
                    return grandchild_pid
                except (ValueError, OSError):
                    pass
            time.sleep(0.05)
        # Timeout — return intermediate pid as best-effort
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        return pid

    # ── Intermediate child ──────────────────────────────────────────────────
    os.setsid()  # new session

    # Second fork (detach from session leader)
    try:
        pid2 = os.fork()
    except OSError as exc:
        sys.stderr.write(f"fork #2 failed: {exc}\n")
        os._exit(1)

    if pid2 > 0:
        # Intermediate child: write grandchild PID, then exit
        wait_file = Path(f"/tmp/.cognirepo_daemon_{os.getpid()}")
        try:
            wait_file.write_text(str(pid2))
        except OSError:
            pass
        os._exit(0)

    # ── Grandchild (actual daemon) ──────────────────────────────────────────
    # Redirect stdin to /dev/null
    with open(os.devnull, "r") as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())

    # Redirect stdout + stderr to log file
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_fd = open(log_path, "a", buffering=1)  # line-buffered  # noqa: WPS515
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())
    log_fd.close()

    return 0  # signal caller to proceed with watcher


# ---------------------------------------------------------------------------
# PID registry
# ---------------------------------------------------------------------------

def register_watcher(pid: int, name: str, path: str, log_path: str) -> None:
    """Write a JSON PID file for a running watcher daemon."""
    record = {
        "pid": pid,
        "name": name,
        "path": os.path.abspath(path),
        "started": datetime.now().isoformat(timespec="seconds"),
        "log": log_path,
    }
    _pid_file(pid).write_text(json.dumps(record, indent=2))


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


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


def stop_watcher(name_or_pid: str) -> bool:
    """Send SIGTERM to a watcher. Returns True if signal was sent."""
    w = find_watcher(name_or_pid)
    if w is None:
        return False
    try:
        os.kill(w["pid"], signal.SIGTERM)
        _pid_file(w["pid"]).unlink(missing_ok=True)
        return True
    except (ProcessLookupError, PermissionError):
        return False


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
        with open(log_path, "r") as fh:
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
        status = w["status"]
        print(f"{pid:<8} {name:<36} {path:<40} {started:<20} {status}")
