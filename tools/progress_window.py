# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
tools/progress_window.py — Tkinter popup showing all active background tasks.

Launched as a detached subprocess by launch_progress_ui().
- Closing the window does NOT stop any task.
- Each task row has its own Stop button that sets stop_requested=True.
- Window auto-closes 5 s after the last task finishes.
- Falls back to a no-op if tkinter / display is unavailable.

Run standalone:  python tools/progress_window.py [--cognirepo-dir <path>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


# ── path bootstrap (works when run as subprocess from any cwd) ────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ── task directory resolution ─────────────────────────────────────────────────

def _resolve_tasks_dir(cognirepo_dir: str | None) -> Path | None:
    """Return the bg_tasks directory, or None if unresolvable."""
    if cognirepo_dir:
        d = Path(cognirepo_dir) / "bg_tasks"
        d.mkdir(parents=True, exist_ok=True)
        return d
    # Auto-detect: walk up from cwd looking for .cognirepo/
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / ".cognirepo" / "bg_tasks"
        if candidate.exists():
            return candidate
    # Try via config.paths (works when cognirepo is on sys.path)
    try:
        from config.paths import get_path  # pylint: disable=import-outside-toplevel
        d = Path(get_path("bg_tasks"))
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:  # pylint: disable=broad-except
        return None


def _read_tasks(tasks_dir: Path) -> list[dict]:
    tasks = []
    for p in sorted(tasks_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["_path"] = str(p)
            tasks.append(data)
        except Exception:  # pylint: disable=broad-except
            pass
    return sorted(tasks, key=lambda t: t.get("started_at", ""))


def _request_stop(task_path: str) -> None:
    try:
        path = Path(task_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["stop_requested"] = True
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:  # pylint: disable=broad-except
        pass


# ── tkinter UI ────────────────────────────────────────────────────────────────

_POLL_MS   = 500    # how often to refresh task state
_DONE_WAIT = 5000  # ms to keep window open after all tasks finish


def _run_ui(tasks_dir: Path) -> None:
    import tkinter as tk                    # noqa: PLC0415
    from tkinter import ttk, font as tkfont  # noqa: PLC0415

    root = tk.Tk()
    root.title("CogniRepo — Background Tasks")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    # ── header ────────────────────────────────────────────────────────────────
    hdr_font = tkfont.Font(family="Helvetica", size=12, weight="bold")
    tk.Label(root, text="⚙  CogniRepo Background Tasks", font=hdr_font,
             pady=8).pack(fill="x", padx=16)
    ttk.Separator(root, orient="horizontal").pack(fill="x", padx=8)

    # ── scrollable task frame ─────────────────────────────────────────────────
    canvas   = tk.Canvas(root, borderwidth=0, highlightthickness=0)
    v_scroll = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=v_scroll.set)
    v_scroll.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True, padx=8, pady=4)

    task_frame = tk.Frame(canvas)
    canvas_win = canvas.create_window((0, 0), window=task_frame, anchor="nw")

    def _on_frame_configure(event):  # noqa: ANN001
        canvas.configure(scrollregion=canvas.bbox("all"))
    task_frame.bind("<Configure>", _on_frame_configure)

    def _on_canvas_configure(event):  # noqa: ANN001
        canvas.itemconfig(canvas_win, width=event.width)
    canvas.bind("<Configure>", _on_canvas_configure)

    # ── footer: "Closing this window does not stop tasks" ─────────────────────
    ttk.Separator(root, orient="horizontal").pack(fill="x", padx=8, pady=(4, 0))
    tk.Label(root, text="Closing this window does not stop any task.",
             fg="gray", font=("Helvetica", 9), pady=6).pack()

    # ── per-task row widgets (rebuilt on each poll) ───────────────────────────
    _row_widgets: dict[str, dict] = {}   # task_id → {bar, pct_label, msg_label, stop_btn}
    _all_done_since: list[float] = [0.0]  # mutable container for closure

    def _pct(current: int, total: int) -> float:
        return (current / total * 100) if total > 0 else 0.0

    def _eta(current: int, total: int, started_at: str) -> str:
        try:
            elapsed = time.time() - time.mktime(time.strptime(started_at, "%Y-%m-%dT%H:%M:%SZ"))
            if current <= 0 or elapsed <= 0:
                return ""
            rate = current / elapsed
            remaining = (total - current) / rate
            m, s = divmod(int(remaining), 60)
            return f"~{m}m {s:02d}s left" if m else f"~{s}s left"
        except Exception:  # pylint: disable=broad-except
            return ""

    def _refresh() -> None:
        tasks = _read_tasks(tasks_dir)
        active_ids = {t["task_id"] for t in tasks}

        # Remove rows for tasks that have been cleaned up
        for tid in list(_row_widgets):
            if tid not in active_ids:
                for w in _row_widgets[tid].values():
                    try:
                        w.destroy()
                    except Exception:  # pylint: disable=broad-except
                        pass
                del _row_widgets[tid]

        for task in tasks:
            tid      = task["task_id"]
            name     = task.get("name", tid)
            total    = task.get("total", 1)
            current  = task.get("current", 0)
            status   = task.get("status", "running")
            started  = task.get("started_at", "")
            stop_req = task.get("stop_requested", False)
            tpath    = task.get("_path", "")
            pct      = _pct(current, total)

            if tid not in _row_widgets:
                # Build a new row
                row = tk.Frame(task_frame, pady=6)
                row.pack(fill="x", padx=12, pady=(4, 0))

                tk.Label(row, text=name, font=("Helvetica", 10, "bold"),
                         anchor="w").pack(anchor="w")

                bar_frame = tk.Frame(row)
                bar_frame.pack(fill="x", pady=(2, 0))

                bar = ttk.Progressbar(bar_frame, length=380, mode="determinate",
                                      maximum=100)
                bar.pack(side="left", padx=(0, 8))

                pct_lbl = tk.Label(bar_frame, text="0%", width=6, anchor="w")
                pct_lbl.pack(side="left")

                stop_btn = tk.Button(
                    bar_frame, text="Stop",
                    bg="#e74c3c", fg="white", relief="flat",
                    padx=8, pady=2,
                    command=lambda p=tpath: _request_stop(p),
                )
                stop_btn.pack(side="left", padx=(4, 0))

                msg_lbl = tk.Label(row, text="", fg="gray",
                                   font=("Helvetica", 9), anchor="w")
                msg_lbl.pack(anchor="w")

                ttk.Separator(row, orient="horizontal").pack(fill="x", pady=(6, 0))

                _row_widgets[tid] = {
                    "bar": bar, "pct_lbl": pct_lbl,
                    "msg_lbl": msg_lbl, "stop_btn": stop_btn,
                    "row": row,
                }

            w = _row_widgets[tid]
            w["bar"]["value"] = pct
            w["pct_lbl"].config(text=f"{pct:.0f}%")

            if status == "done":
                w["pct_lbl"].config(text="✓ Done", fg="#27ae60")
                w["stop_btn"].config(state="disabled", bg="gray")
                w["msg_lbl"].config(text="")
            elif stop_req:
                w["stop_btn"].config(text="Stopping…", state="disabled", bg="gray")
                w["msg_lbl"].config(text="Stop requested — finishing current item…")
            else:
                eta = _eta(current, total, started)
                extra = task.get("message", "")
                parts = [f"{current:,} / {total:,}"]
                if eta:
                    parts.append(eta)
                if extra:
                    parts.append(extra)
                w["msg_lbl"].config(text="  ".join(parts))

        # ── auto-close logic ──────────────────────────────────────────────────
        all_done = all(t.get("status") == "done" for t in tasks) and tasks
        if all_done:
            if _all_done_since[0] == 0.0:
                _all_done_since[0] = time.monotonic()
            elif time.monotonic() - _all_done_since[0] > _DONE_WAIT / 1000:
                root.destroy()
                return
        else:
            _all_done_since[0] = 0.0

        # Resize window to fit content
        root.update_idletasks()
        root.minsize(460, max(120, task_frame.winfo_reqheight() + 100))

        root.after(_POLL_MS, _refresh)

    # Kick off first poll after a short delay to let the first task file appear
    root.after(300, _refresh)
    root.mainloop()


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="CogniRepo background task progress UI")
    ap.add_argument("--cognirepo-dir", default=None,
                    help="Path to .cognirepo directory for the project")
    args = ap.parse_args()

    tasks_dir = _resolve_tasks_dir(args.cognirepo_dir)
    if tasks_dir is None:
        print("progress_window: could not locate .cognirepo/bg_tasks — exiting.", file=sys.stderr)
        sys.exit(1)

    try:
        _run_ui(tasks_dir)
    except Exception as exc:  # pylint: disable=broad-except
        # Display not available or tkinter error — exit silently so the
        # missing UI never breaks any background task.
        print(f"progress_window: UI unavailable ({exc})", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
