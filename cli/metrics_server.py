# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Standalone Prometheus metrics HTTP server for pure-MCP deployments.

Usage:
    cognirepo metrics --host 127.0.0.1 --port 9090

Serves the same prometheus_client registry that the REST API exposes at
/metrics, but on a separate HTTP port so MCP-only users can scrape it
without running the full FastAPI stack.
"""
from __future__ import annotations

import http.server
import logging
import threading

logger = logging.getLogger(__name__)


class _MetricsHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler that serves /metrics."""

    def do_GET(self):  # pylint: disable=invalid-name
        if self.path not in ("/metrics", "/metrics/"):
            self.send_response(404)
            self.end_headers()
            return

        from server.metrics import metrics_available, get_metrics_output  # pylint: disable=import-outside-toplevel
        if not metrics_available():
            body = b"prometheus_client not installed\n"
            self.send_response(501)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body, content_type = get_metrics_output()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # pylint: disable=arguments-differ
        logger.debug("metrics_server: " + fmt, *args)


def run_metrics_server(host: str = "127.0.0.1", port: int = 9090) -> None:
    """Block serving /metrics on host:port until KeyboardInterrupt."""
    server = http.server.HTTPServer((host, port), _MetricsHandler)
    logger.info("CogniRepo metrics server listening on %s:%d", host, port)
    print(f"Metrics available at http://{host}:{port}/metrics")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def start_metrics_server_thread(host: str = "127.0.0.1", port: int = 9090) -> threading.Thread:
    """Start the metrics server in a daemon thread and return it."""
    t = threading.Thread(
        target=run_metrics_server,
        args=(host, port),
        daemon=True,
        name="cognirepo-metrics-server",
    )
    t.start()
    return t
