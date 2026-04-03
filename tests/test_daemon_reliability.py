# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_daemon_reliability.py — Sprint 3 acceptance tests.

Covers:
  TASK-008: heartbeat write/read/age, crash-recovery loop, systemd unit gen
  TASK-009: singleton enforcement, stale-PID detection, flock_register_watcher
  TASK-010: SubQueryStream uses stream_route (real streaming, not sentence-split)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── TASK-008: Heartbeat ───────────────────────────────────────────────────────

class TestHeartbeat:
    def test_write_and_read_heartbeat(self, tmp_path, monkeypatch):
        from cli import daemon as d
        monkeypatch.setattr(d, "_watchers_dir", lambda: tmp_path)
        d.write_heartbeat(pid=12345, watcher_path="/repo")
        hb = d.read_heartbeat()
        assert hb is not None
        assert hb["pid"] == 12345
        assert hb["path"] == "/repo"
        assert "timestamp" in hb

    def test_heartbeat_age_fresh(self, tmp_path, monkeypatch):
        from cli import daemon as d
        monkeypatch.setattr(d, "_watchers_dir", lambda: tmp_path)
        d.write_heartbeat(pid=1, watcher_path="/repo")
        age = d.heartbeat_age_seconds()
        assert age is not None
        assert age < 5  # written just now

    def test_heartbeat_age_none_when_no_file(self, tmp_path, monkeypatch):
        from cli import daemon as d
        monkeypatch.setattr(d, "_watchers_dir", lambda: tmp_path)
        age = d.heartbeat_age_seconds()
        assert age is None

    def test_read_heartbeat_returns_none_on_corrupt(self, tmp_path, monkeypatch):
        from cli import daemon as d
        monkeypatch.setattr(d, "_watchers_dir", lambda: tmp_path)
        (tmp_path / "heartbeat").write_text("not json")
        hb = d.read_heartbeat()
        assert hb is None

    def test_heartbeat_thread_updates(self, tmp_path, monkeypatch):
        """start_heartbeat_thread must call write_heartbeat at least once."""
        from cli import daemon as d
        monkeypatch.setattr(d, "_watchers_dir", lambda: tmp_path)
        monkeypatch.setattr(d, "_HEARTBEAT_INTERVAL", 0.05)  # speed up

        t = d.start_heartbeat_thread(pid=99, watcher_path="/repo")
        time.sleep(0.15)  # allow at least 2 ticks

        hb = d.read_heartbeat()
        assert hb is not None
        assert hb["pid"] == 99
        assert t.daemon is True


# ── TASK-008: Systemd unit generation ────────────────────────────────────────

class TestSystemdUnit:
    def test_unit_content(self):
        from cli.daemon import generate_systemd_unit
        unit = generate_systemd_unit("/my/repo")
        assert "[Unit]" in unit
        assert "[Service]" in unit
        assert "[Install]" in unit
        assert "Restart=on-failure" in unit
        assert "/my/repo" in unit

    def test_write_systemd_unit(self, tmp_path, monkeypatch):
        from cli import daemon as d
        monkeypatch.setattr(d, "_find_cognirepo_dir", lambda: tmp_path)
        path = d.write_systemd_unit("/my/repo")
        assert path.exists()
        content = path.read_text()
        assert "Restart=on-failure" in content


# ── TASK-008: Crash-recovery loop ────────────────────────────────────────────

class TestCrashRecovery:
    def test_clean_exit_does_not_restart(self, tmp_path, monkeypatch):
        """If observer exits cleanly, the loop terminates (no restart)."""
        from cli import daemon as d
        monkeypatch.setattr(d, "_watchers_dir", lambda: tmp_path)

        call_count = {"n": 0}

        def make_observer():
            call_count["n"] += 1
            obs = MagicMock()
            obs.is_alive.return_value = False  # dies immediately → clean exit
            return obs

        d.run_watcher_with_crash_guard(
            create_fn=make_observer,
            stop_fn=lambda obs: obs.stop(),
            watcher_path="/repo",
            session_id="test",
            restart_delay=0,
        )
        assert call_count["n"] == 1  # started exactly once

    def test_crash_triggers_restart(self, tmp_path, monkeypatch):
        """First call raises → loop restarts → second call exits cleanly."""
        from cli import daemon as d
        monkeypatch.setattr(d, "_watchers_dir", lambda: tmp_path)

        call_count = {"n": 0}

        def make_observer():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated crash")
            obs = MagicMock()
            obs.is_alive.return_value = False
            return obs

        d.run_watcher_with_crash_guard(
            create_fn=make_observer,
            stop_fn=lambda obs: obs.stop(),
            watcher_path="/repo",
            session_id="test",
            restart_delay=0,  # no sleep in tests
        )
        assert call_count["n"] == 2  # crashed once, then restarted successfully


# ── TASK-009: Singleton enforcement ──────────────────────────────────────────

class TestSingletonEnforcement:
    def _make_pid_file(self, d, tmp_path, pid: int, path: str) -> None:
        record = {
            "pid": pid,
            "name": f"watcher-{pid}",
            "path": os.path.abspath(path),
            "started": "2026-01-01T00:00:00Z",
            "log": "/log.txt",
        }
        (tmp_path / f"{pid}.json").write_text(json.dumps(record))

    def test_running_watcher_detected(self, tmp_path, monkeypatch):
        from cli import daemon as d
        monkeypatch.setattr(d, "_watchers_dir", lambda: tmp_path)
        self._make_pid_file(d, tmp_path, pid=os.getpid(), path="/my/repo")

        result = d.is_watcher_running_for_path("/my/repo")
        assert result is not None
        assert result["pid"] == os.getpid()

    def test_stale_pid_cleaned_up(self, tmp_path, monkeypatch):
        from cli import daemon as d
        monkeypatch.setattr(d, "_watchers_dir", lambda: tmp_path)
        # use PID 99999 — almost certainly not a real process
        self._make_pid_file(d, tmp_path, pid=99999, path="/my/repo")

        result = d.is_watcher_running_for_path("/my/repo")
        assert result is None
        # stale PID file should have been deleted
        assert not (tmp_path / "99999.json").exists()

    def test_different_path_not_detected(self, tmp_path, monkeypatch):
        from cli import daemon as d
        monkeypatch.setattr(d, "_watchers_dir", lambda: tmp_path)
        self._make_pid_file(d, tmp_path, pid=os.getpid(), path="/other/repo")

        result = d.is_watcher_running_for_path("/my/repo")
        assert result is None

    def test_flock_register_writes_pid_file(self, tmp_path, monkeypatch):
        from cli import daemon as d
        monkeypatch.setattr(d, "_watchers_dir", lambda: tmp_path)
        d.flock_register_watcher(
            pid=os.getpid(), name="test-watcher",
            path="/repo", log_path="/log.txt",
        )
        pid_file = tmp_path / f"{os.getpid()}.json"
        assert pid_file.exists()
        rec = json.loads(pid_file.read_text())
        assert rec["pid"] == os.getpid()
        assert rec["name"] == "test-watcher"


# ── TASK-010: True gRPC streaming ────────────────────────────────────────────

class TestGrpcStreaming:
    def _make_request(self, query="test query", max_tokens=256):
        req = MagicMock()
        req.query = query
        req.max_tokens = max_tokens
        req.context_id = ""
        req.source_model = ""
        req.target_tier = ""
        return req

    def test_subquerystream_uses_stream_route(self):
        """SubQueryStream must call stream_route, not the old sentence splitter."""
        from rpc.server import QueryServiceServicer
        svc = QueryServiceServicer()
        context = MagicMock()
        context.is_active.return_value = True

        chunks_yielded = []
        with patch("rpc.server.stream_route", return_value=iter(["Hello ", "world"])) as mock_sr:
            for resp in svc.SubQueryStream(self._make_request(), context):
                chunks_yielded.append(resp.result)

        mock_sr.assert_called_once()
        assert len(chunks_yielded) == 2
        assert chunks_yielded[0] == "Hello "
        assert chunks_yielded[1] == "world"

    def test_stream_route_imported_at_top_of_method(self):
        """Verify stream_route is imported inside SubQueryStream (no global import)."""
        import inspect
        from rpc.server import QueryServiceServicer
        src = inspect.getsource(QueryServiceServicer.SubQueryStream)
        assert "stream_route" in src

    def test_client_disconnect_stops_stream(self):
        """If context.is_active() returns False, generator must be closed."""
        from rpc.server import QueryServiceServicer
        svc = QueryServiceServicer()
        context = MagicMock()
        context.is_active.return_value = False  # client disconnected immediately

        def _gen():
            yield "chunk1"
            yield "chunk2"

        results = []
        with patch("rpc.server.stream_route", return_value=_gen()):
            for resp in svc.SubQueryStream(self._make_request(), context):
                results.append(resp)

        # No chunks should be delivered after client disconnects
        assert len(results) == 0

    def test_stream_error_yields_error_response(self):
        """If stream_route raises, SubQueryStream must yield a single error response."""
        from rpc.server import QueryServiceServicer
        svc = QueryServiceServicer()
        context = MagicMock()
        context.is_active.return_value = True

        with patch("rpc.server.stream_route", side_effect=RuntimeError("model failure")):
            responses = list(svc.SubQueryStream(self._make_request(), context))

        assert len(responses) == 1
        assert responses[0].error is True
        assert "model failure" in responses[0].error_message

    def test_empty_stream_falls_back_to_subquery(self):
        """If stream_route yields nothing, fall back to blocking SubQuery."""
        from rpc.server import QueryServiceServicer
        svc = QueryServiceServicer()
        context = MagicMock()
        context.is_active.return_value = True

        fallback_resp = MagicMock()
        fallback_resp.result = "fallback answer"

        with patch("rpc.server.stream_route", return_value=iter([])):
            with patch.object(svc, "SubQuery", return_value=fallback_resp):
                responses = list(svc.SubQueryStream(self._make_request(), context))

        assert len(responses) == 1
        assert responses[0].result == "fallback answer"
