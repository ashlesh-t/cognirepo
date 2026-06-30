# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
tools/bg_progress.py — Background task progress tracker.

Background tasks write their state to .cognirepo/bg_tasks/<task_id>.json.
The progress UI (tools/progress_window.py) polls these files and renders
progress bars.  Closing the UI never kills tasks; the Stop button sets
stop_requested=true in the JSON and the task polls should_stop() to exit.

Usage in a background task:
    from tools.bg_progress import TaskProgress
    p = TaskProgress("embed_summaries", "Embedding summaries", total=8364)
    for i, item in enumerate(items):
        if p.should_stop():
            break
        process(item)
        p.update(i + 1)
    p.complete()
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def _tasks_dir() -> Path:
    """Return the bg_tasks directory, creating it if needed."""
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
    d = Path(get_path("bg_tasks"))
    d.mkdir(parents=True, exist_ok=True)
    return d


class TaskProgress:
    """Write-side: used by the background task process."""

    def __init__(self, task_id: str, name: str, total: int) -> None:
        self.task_id = task_id
        self.name = name
        self.total = total
        self._path = _tasks_dir() / f"{task_id}.json"
        self._pid = os.getpid()
        self._write("running", current=0)

    def update(self, current: int, message: str = "") -> None:
        self._write("running", current=current, message=message)

    def complete(self) -> None:
        self._write("done", current=self.total)
        # Leave the file for ~30 s so the UI can show the completion state,
        # then clean up.  Best-effort: if the process exits before cleanup that's fine.
        try:
            import threading  # pylint: disable=import-outside-toplevel
            def _cleanup():
                time.sleep(30)
                try:
                    self._path.unlink(missing_ok=True)
                except OSError:
                    pass
            t = threading.Thread(target=_cleanup, daemon=True)
            t.start()
        except Exception:  # pylint: disable=broad-except
            pass

    def should_stop(self) -> bool:
        """Return True if the UI requested a stop."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return bool(data.get("stop_requested", False))
        except Exception:  # pylint: disable=broad-except
            return False

    def _write(self, status: str, current: int, message: str = "") -> None:
        data = {
            "task_id": self.task_id,
            "name": self.name,
            "total": self.total,
            "current": current,
            "status": status,
            "pid": self._pid,
            "started_at": getattr(self, "_started_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stop_requested": False,
            "message": message,
        }
        if not hasattr(self, "_started_at"):
            self._started_at = data["started_at"]
        try:
            tmp = str(self._path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self._path)  # atomic write
        except OSError:
            pass


# ── Read-side helpers used by the progress window ────────────────────────────

def list_active_tasks() -> list[dict]:
    """Return all task state dicts from bg_tasks/*.json, sorted by started_at."""
    try:
        d = _tasks_dir()
    except Exception:  # pylint: disable=broad-except
        return []
    tasks = []
    for p in sorted(d.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["_path"] = str(p)
            tasks.append(data)
        except Exception:  # pylint: disable=broad-except
            pass
    return sorted(tasks, key=lambda t: t.get("started_at", ""))


def request_stop(task_id: str) -> None:
    """Set stop_requested=True for the given task."""
    try:
        d = _tasks_dir()
        path = d / f"{task_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["stop_requested"] = True
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:  # pylint: disable=broad-except
        pass


def launch_progress_ui() -> None:
    """
    Spawn the progress window as a detached subprocess.
    Safe to call from any background task launcher — the UI process is
    independent and will auto-close when all tasks complete.
    """
    import subprocess  # pylint: disable=import-outside-toplevel
    import sys  # pylint: disable=import-outside-toplevel
    script = str(Path(__file__).parent / "progress_window.py")
    try:
        subprocess.Popen(
            [sys.executable, script],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:  # pylint: disable=broad-except
        pass
