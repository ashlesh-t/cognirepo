# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Standalone Prometheus metrics HTTP server for pure-MCP deployments.

Usage:
    cognirepo metrics --host 127.0.0.1 --port 9090

Serves /metrics for ONE repo's store on its own HTTP port. The numbers are derived from what every
process leaves on disk (the event log, graph/index/watcher files, directory sizes) rather than from
in-process counters, which the MCP server, the watcher and this server cannot share (#212). See
``interface/ui/store_metrics.py``.
"""
from __future__ import annotations

import http.server
import logging
import threading

logger = logging.getLogger(__name__)


class _MetricsHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler that serves /metrics."""

    registry = None   # set per server in create_metrics_server

    def do_GET(self):  # pylint: disable=invalid-name
        if self.path not in ("/metrics", "/metrics/"):
            self.send_response(404)
            self.end_headers()
            return

        from core.metrics import metrics_available  # pylint: disable=import-outside-toplevel
        if not metrics_available():
            body = b"prometheus_client not installed\n"
            self.send_response(501)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # pylint: disable=import-outside-toplevel
        body, content_type = generate_latest(self.registry), CONTENT_TYPE_LATEST
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # pylint: disable=arguments-differ
        logger.debug("metrics_server: " + fmt, *args)


def create_metrics_server(host: str = "127.0.0.1", port: int = 9090,
                          repo_root: str | None = None) -> http.server.HTTPServer:
    """Bind (but do not start) the /metrics server for ``repo_root`` (default: the current directory).
    ``port=0`` picks a free port."""
    import os  # pylint: disable=import-outside-toplevel
    from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
    handler = type("_BoundMetricsHandler", (_MetricsHandler,), {"registry": None})
    from core.metrics import metrics_available  # pylint: disable=import-outside-toplevel
    if metrics_available():
        from prometheus_client import CollectorRegistry  # pylint: disable=import-outside-toplevel
        from interface.ui.store_metrics import StoreCollector  # pylint: disable=import-outside-toplevel
        root = os.path.abspath(repo_root or os.getcwd())
        registry = CollectorRegistry()
        registry.register(StoreCollector(str(get_cognirepo_dir_for_repo(root)),
                                         os.path.basename(root.rstrip(os.sep)) or root, root))
        handler.registry = registry
    return http.server.HTTPServer((host, port), handler)


def run_metrics_server(host: str = "127.0.0.1", port: int = 9090, repo_root: str | None = None) -> None:
    """Block serving /metrics on host:port until KeyboardInterrupt."""
    server = create_metrics_server(host, port, repo_root)
    logger.info("CogniRepo metrics server listening on %s:%d", host, port)
    print(f"Metrics available at http://{host}:{port}/metrics")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def start_metrics_server_thread(host: str = "127.0.0.1", port: int = 9090,
                                repo_root: str | None = None) -> threading.Thread:
    """Start the metrics server in a daemon thread and return it."""
    t = threading.Thread(
        target=run_metrics_server,
        args=(host, port, repo_root),
        daemon=True,
        name="cognirepo-metrics-server",
    )
    t.start()
    return t
