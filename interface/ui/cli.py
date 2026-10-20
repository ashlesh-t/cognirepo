# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""``cognirepo ui``: ensure the local control server is running and open the console."""
from __future__ import annotations

import os
import signal
import subprocess  # nosec B404 — fixed argv only
import sys
import time
import webbrowser
from typing import Any

from interface.ui import UI_INSTALL_HINT, ui_extra_missing
from interface.ui import security as sec
from interface.ui.session import clear_session, is_listening, read_session

CONSOLE_INSTALL_HINT = (
    "The Engram console is not installed, so only the API (and a minimal status page) is served.\n"
    "  Install it with:  pip install cognirepo-console\n"
    "  or let `cognirepo ui` clone it with git (needs git and network; see docs/UI_API.md)."
)


def console_installed() -> bool:
    """True when the server will find a console: the verified git-managed bundle or the pip package."""
    from interface.ui import console_install  # pylint: disable=import-outside-toplevel
    if console_install.resolve()[0] is not None:
        return True
    import importlib.util  # pylint: disable=import-outside-toplevel
    try:
        return importlib.util.find_spec("cognirepo_console") is not None
    except (ImportError, ValueError):
        return False


def _ensure_console(args: Any) -> None:
    """Install the git-managed console before the server starts (so the server finds it). Never fatal."""
    from interface.ui import console_install  # pylint: disable=import-outside-toplevel
    if console_install.resolve()[0] is not None:
        return
    off = True if getattr(args, "no_console_fetch", False) else None
    out = console_install.ensure(autofetch=False if off else None)
    if out.status == "fetched":
        print(f"cognirepo ui: {out.message} from {console_install.settings()['repo']}")
    elif out.status in ("failed", "invalid", "no-git"):
        print(f"cognirepo ui: {out.message}", file=sys.stderr)


def _spawn_server(repo_root: str, host: str, port: int | None, unsafe_bind: bool, allow_origins: list[str]) -> None:
    from core.config.paths import get_global_path  # pylint: disable=import-outside-toplevel
    argv = [sys.executable, "-m", "interface.cli.main", "ui", "--serve", "--no-open", "--host", host]
    if port is not None:
        argv += ["--port", str(port)]
    if unsafe_bind:
        argv.append("--unsafe-bind")
    for origin in allow_origins:
        argv += ["--allow-origin", origin]
    log_fd = os.open(get_global_path("ui/server.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    kwargs: dict[str, Any] = {"cwd": repo_root, "stdin": subprocess.DEVNULL, "stdout": log_fd, "stderr": log_fd}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(argv, **kwargs)  # nosec B603 — fixed argv, no shell
    finally:
        os.close(log_fd)


def _wait_for_session(timeout: float = 15.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        sess = read_session()
        if sess and is_listening(sess["port"]):
            return sess
        time.sleep(0.15)
    return None


def _url(sess: dict, with_token: bool) -> str:
    base = f"http://127.0.0.1:{sess['port']}/"
    return f"{base}#token={sess['token']}" if with_token else base


def _require_ui_extra() -> bool:
    """False (after printing the install hint) when the optional ``[ui]`` extra is absent."""
    missing = ui_extra_missing()
    if missing:
        print(f"cognirepo ui: the control API needs {', '.join(missing)}, which the core install "
              f"leaves out.\n  Install it with: {UI_INSTALL_HINT}", file=sys.stderr)
    return not missing


def run_ui(args: Any) -> int:
    """Entry point for ``cognirepo ui`` (see docs/UI_API.md). Returns an exit code."""
    repo_root = os.path.abspath(os.getcwd())
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", None)
    unsafe = bool(getattr(args, "unsafe_bind", False))
    origins = list(getattr(args, "allow_origin", None) or [])

    wants_off = getattr(args, "autostart", None) == "off"
    if not (getattr(args, "stop", False) or wants_off) and not _require_ui_extra():
        return 1

    if getattr(args, "serve", False):
        from interface.ui.server import serve  # pylint: disable=import-outside-toplevel
        return serve(repo_root, host, port, unsafe, tuple(origins))

    try:  # fail fast in the foreground command, before spawning anything
        warning = sec.validate_bind_host(host, unsafe)
    except sec.UnsafeBindError as exc:
        print(f"cognirepo ui: {exc}", file=sys.stderr)
        return 2
    if warning:
        print(warning, file=sys.stderr)

    if getattr(args, "stop", False):
        return _stop()

    autostart = getattr(args, "autostart", None)
    if autostart:
        from interface.ui import console_autostart as _auto  # pylint: disable=import-outside-toplevel
        result = _auto.enable(repo_root) if autostart == "on" else _auto.disable()
        print(("autostart: " if result.ok else "autostart FAILED: ") + result.detail,
              file=sys.stdout if result.ok else sys.stderr)
        return 0 if result.ok else 1

    sess = read_session()
    if sess and is_listening(sess["port"]):
        if os.path.abspath(sess.get("repo_root", "")) != repo_root:
            print(f"cognirepo ui: already running for {sess.get('repo_root')}.\n"
                  "  Stop it first with:  cognirepo ui --stop", file=sys.stderr)
            return 1
    else:
        clear_session()
        _ensure_console(args)
        _spawn_server(repo_root, host, port, unsafe, origins)
        sess = _wait_for_session()
        if sess is None:
            from core.config.paths import get_global_path  # pylint: disable=import-outside-toplevel
            print("cognirepo ui: the server did not start. See " + get_global_path("ui/server.log"), file=sys.stderr)
            return 1

    if not console_installed():
        print(CONSOLE_INSTALL_HINT)
    if not getattr(args, "no_open", False):  # interactive launches only; never from --serve/--no-open scripts
        from interface.ui import console_autostart as _auto  # pylint: disable=import-outside-toplevel
        prompted = _auto.maybe_prompt(repo_root)
        if prompted is not None:
            print(("autostart: " if prompted.ok else "autostart FAILED: ") + prompted.detail)
    opened = False
    if not getattr(args, "no_open", False):
        try:
            opened = bool(webbrowser.open(_url(sess, with_token=True)))
        except Exception:  # pylint: disable=broad-except
            opened = False
    if opened:
        print(f"Engram console opened at {_url(sess, with_token=False)}")
    else:
        # No browser (or --no-open): the user needs the tokenised URL. Treat it as a secret.
        print(f"Open this URL in your browser (it contains a session secret; do not share it):\n  {_url(sess, True)}")
    return 0


def _stop() -> int:
    sess = read_session()
    if not sess or not is_listening(sess["port"]):
        clear_session()
        print("cognirepo ui: not running.")
        return 0
    try:
        os.kill(int(sess["pid"]), signal.SIGTERM)
    except (OSError, ValueError) as exc:
        print(f"cognirepo ui: could not stop pid {sess.get('pid')}: {exc}", file=sys.stderr)
        return 1
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and is_listening(sess["port"]):
        time.sleep(0.1)
    clear_session()
    print("cognirepo ui: stopped.")
    return 0
