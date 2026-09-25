# pylint: disable=missing-docstring, import-outside-toplevel
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_mcp_stdout_clean.py — #99: stdout of `cognirepo serve` is JSON-RPC only.

The auto-watcher's status lines ([watcher:...], [watcher] re-indexed ...) used to go
to stdout and broke MCP stdio clients.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)


def test_serve_stdout_is_only_json_rpc(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "a.py").write_text("def f():\n    return 1\n")
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), PYTHONPATH=ROOT)

    proc = subprocess.Popen(
        [sys.executable, "-m", "interface.cli.main", "serve", "--project-dir", str(repo)],
        cwd=repo, env=env, text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    out: list[str] = []
    err: list[str] = []
    threading.Thread(target=lambda: out.extend(proc.stdout), daemon=True).start()
    threading.Thread(target=lambda: err.extend(proc.stderr), daemon=True).start()
    try:
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"}}}
        proc.stdin.write(json.dumps(init) + "\n")
        proc.stdin.flush()

        deadline = time.monotonic() + 60
        # Wait on either stream: pre-fix the line lands on stdout, and the JSON
        # assertion below should be what fails, not this wait.
        while time.monotonic() < deadline and not any("[watcher:" in l for l in out + err):
            time.sleep(0.25)
        assert any("[watcher:" in l for l in out + err), "auto-watcher never started: " + "".join(err)[-500:]

        (repo / "a.py").write_text("def f():\n    return 1\n\ndef g():\n    return 2\n")  # watcher event
        time.sleep(5)
    finally:
        proc.kill()
        proc.wait(timeout=10)

    assert out, "server produced no JSON-RPC response"
    for line in out:
        json.loads(line)  # raises on any non-JSON line
