# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for config/logging.py — structured logging + correlation IDs."""
import importlib
import json
import logging
import sys

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _reload_logging_module():
    """Force a fresh import of config.logging (resets _SETUP_DONE)."""
    import config.logging as mod  # pylint: disable=import-outside-toplevel
    mod._SETUP_DONE = False  # type: ignore[attr-defined]
    return mod


# ── trace ID helpers ──────────────────────────────────────────────────────────

def test_new_trace_id_returns_hex_string():
    from config.logging import new_trace_id
    tid = new_trace_id()
    assert isinstance(tid, str)
    assert len(tid) == 32          # uuid4.hex is 32 hex chars
    int(tid, 16)                   # must be valid hex


def test_get_trace_id_returns_set_value():
    from config.logging import new_trace_id, get_trace_id
    tid = new_trace_id()
    assert get_trace_id() == tid


def test_get_trace_id_none_when_unset():
    from config.logging import cogni_trace_id, get_trace_id
    cogni_trace_id.set(None)
    assert get_trace_id() is None


# ── JSON formatter ────────────────────────────────────────────────────────────

def test_json_formatter_produces_valid_ndjson(capfd):
    from config.logging import JSONFormatter, TraceFilter, cogni_trace_id

    cogni_trace_id.set("abc123")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(TraceFilter())

    lgr = logging.getLogger("test.json_fmt")
    lgr.propagate = False
    lgr.addHandler(handler)
    lgr.setLevel(logging.DEBUG)

    lgr.info("hello world")
    lgr.removeHandler(handler)

    captured = capfd.readouterr().err
    last_line = [l for l in captured.splitlines() if l.strip()][-1]
    payload = json.loads(last_line)

    assert payload["msg"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["trace_id"] == "abc123"
    assert "ts" in payload


def test_json_formatter_trace_id_null_when_unset(capfd):
    from config.logging import JSONFormatter, TraceFilter, cogni_trace_id

    cogni_trace_id.set(None)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(TraceFilter())

    lgr = logging.getLogger("test.json_null")
    lgr.propagate = False
    lgr.addHandler(handler)
    lgr.setLevel(logging.DEBUG)

    lgr.warning("no trace here")
    lgr.removeHandler(handler)

    captured = capfd.readouterr().err
    last_line = [l for l in captured.splitlines() if l.strip()][-1]
    payload = json.loads(last_line)
    assert payload["trace_id"] is None


# ── setup_logging idempotency ─────────────────────────────────────────────────

def test_setup_logging_idempotent():
    """Calling setup_logging twice must not add duplicate handlers."""
    mod = _reload_logging_module()
    root = logging.getLogger()
    handlers_before = len(root.handlers)

    mod.setup_logging()
    handlers_after_first = len(root.handlers)
    mod.setup_logging()  # second call
    handlers_after_second = len(root.handlers)

    assert handlers_after_second == handlers_after_first


# ── stderr-only (stdout safety) ───────────────────────────────────────────────

def test_setup_logging_does_not_write_to_stdout(capfd):
    mod = _reload_logging_module()
    mod.setup_logging()

    lgr = logging.getLogger("test.stdout_safety")
    lgr.info("this must not appear on stdout")

    captured = capfd.readouterr()
    assert captured.out == "", "Log output leaked to stdout!"
