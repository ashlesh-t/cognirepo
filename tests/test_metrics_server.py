# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for cli/metrics_server.py — standalone metrics HTTP server."""
import socket
import time
import urllib.request

import pytest

from api.metrics import metrics_available
from cli.metrics_server import start_metrics_server_thread


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(not metrics_available(), reason="prometheus_client not installed")
def test_standalone_metrics_server_serves_metrics():
    """start_metrics_server_thread should respond to GET /metrics."""
    port = _find_free_port()
    start_metrics_server_thread(host="127.0.0.1", port=port)

    # Give the server thread a moment to bind
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=1) as resp:
                if resp.status == 200:
                    body = resp.read()
                    assert b"cognirepo_" in body or b"# HELP" in body
                    return
        except Exception:
            time.sleep(0.1)
    pytest.fail("Metrics server did not respond within 3s")


@pytest.mark.skipif(not metrics_available(), reason="prometheus_client not installed")
def test_standalone_metrics_server_404_on_unknown_path():
    """Paths other than /metrics should return 404."""
    port = _find_free_port()
    start_metrics_server_thread(host="127.0.0.1", port=port)

    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/notfound", timeout=1
            ):
                pass
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
            return
        except Exception:
            time.sleep(0.1)
    pytest.fail("Server did not respond within 3s")
