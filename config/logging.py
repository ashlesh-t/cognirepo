# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Structured logging for CogniRepo.

Provides:
- JSONFormatter   — NDJSON single-line log records
- TextFormatter   — human-readable colored-ish text records
- setup_logging() — idempotent setup; call once at startup

Environment controls:
    COGNIREPO_LOG_LEVEL    — DEBUG|INFO|WARNING|ERROR|CRITICAL (default INFO)
    COGNIREPO_LOG_FORMAT   — json|text (default: json in non-TTY, text in TTY)

Trace context:
    cogni_trace_id  — ContextVar; set per request/tool call
    new_trace_id()  — generate a fresh UUID4 trace ID
    get_trace_id()  — read current trace ID (or None)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from typing import Optional

# ── trace context ─────────────────────────────────────────────────────────────

cogni_trace_id: ContextVar[Optional[str]] = ContextVar("cogni_trace_id", default=None)


def new_trace_id() -> str:
    """Generate and set a fresh UUID4 trace ID in the current context."""
    tid = uuid.uuid4().hex
    cogni_trace_id.set(tid)
    return tid


def get_trace_id() -> Optional[str]:
    """Return the current trace ID, or None if not set."""
    return cogni_trace_id.get(None)


# ── filters ───────────────────────────────────────────────────────────────────

class TraceFilter(logging.Filter):
    """Inject trace_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = cogni_trace_id.get(None)
        return True


# ── formatters ────────────────────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """Emit a single-line NDJSON record per log message."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": getattr(record, "trace_id", None),
        }
        # include any extra fields passed via logger.xxx(msg, extra={...})
        _SKIP = {
            "name", "msg", "args", "levelname", "levelno", "pathname",
            "filename", "module", "exc_info", "exc_text", "stack_info",
            "lineno", "funcName", "created", "msecs", "relativeCreated",
            "thread", "threadName", "processName", "process", "message",
            "taskName", "trace_id",
        }
        for key, val in record.__dict__.items():
            if key not in _SKIP:
                payload[key] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable log line: [LEVEL] logger — msg  (trace_id)"""

    LEVEL_COLORS = {
        "DEBUG":    "\033[36m",   # cyan
        "INFO":     "\033[32m",   # green
        "WARNING":  "\033[33m",   # yellow
        "ERROR":    "\033[31m",   # red
        "CRITICAL": "\033[35m",   # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelname, "")
        reset = self.RESET if color else ""
        tid = getattr(record, "trace_id", None)
        tid_str = f"  [{tid}]" if tid else ""
        ts = self.formatTime(record, datefmt="%H:%M:%S")
        line = (
            f"{ts} {color}{record.levelname:8s}{reset} "
            f"{record.name} — {record.getMessage()}{tid_str}"
        )
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


# ── setup ─────────────────────────────────────────────────────────────────────

_SETUP_DONE = False  # guard for idempotency


def setup_logging(
    level: Optional[str] = None,
    fmt: Optional[str] = None,
) -> None:
    """
    Configure the root logger for CogniRepo (idempotent).

    Parameters
    ----------
    level:
        Log level string.  Falls back to $COGNIREPO_LOG_LEVEL then INFO.
    fmt:
        "json" or "text".  Falls back to $COGNIREPO_LOG_FORMAT then
        auto-detected: "text" if stderr is a TTY, otherwise "json".
    """
    global _SETUP_DONE  # pylint: disable=global-statement

    if _SETUP_DONE:
        return

    # ── level ─────────────────────────────────────────────────────────────
    log_level_str = (
        level
        or os.environ.get("COGNIREPO_LOG_LEVEL", "INFO")
    ).upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    # ── format ────────────────────────────────────────────────────────────
    if fmt is None:
        env_fmt = os.environ.get("COGNIREPO_LOG_FORMAT", "").lower()
        if env_fmt in ("json", "text"):
            fmt = env_fmt
        else:
            fmt = "text" if sys.stderr.isatty() else "json"

    formatter: logging.Formatter
    if fmt == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()

    # ── handler (stderr only — never stdout, protects MCP framing) ────────
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    handler.addFilter(TraceFilter())

    root = logging.getLogger()

    # Skip if already configured (e.g. by test harness)
    if root.handlers:
        _SETUP_DONE = True
        return

    root.setLevel(log_level)
    root.addHandler(handler)

    # Quieten noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers",
                  "faiss", "grpc"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _SETUP_DONE = True
