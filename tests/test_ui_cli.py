# pylint: disable=missing-docstring, protected-access, redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_ui_cli.py — `cognirepo ui`: bind guard, spawn/reuse/stop, bootstrap page, real server."""
import argparse
import os
import socket
import threading
import time

import httpx
import pytest

from interface.ui import cli as ui_cli
from interface.ui import server as ui_server
from interface.ui import session as ui_session


def ns(**kw):
    base = dict(host="127.0.0.1", port=None, no_open=True, serve=False, stop=False, unsafe_bind=False, allow_origin=None)
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(ui_cli, "_spawn_server", lambda *a: calls.append(a))
    return calls


class TestBindGuard:
    def test_non_loopback_refused_before_anything_starts(self, spawned, capsys):
        assert ui_cli.run_ui(ns(host="0.0.0.0")) == 2
        assert spawned == [] and "refusing to bind" in capsys.readouterr().err

    def test_unsafe_bind_warns_loudly_and_proceeds(self, spawned, capsys, monkeypatch):
        monkeypatch.setattr(ui_cli, "_wait_for_session", lambda *a, **k: {"token": "T", "port": 1, "host": "0.0.0.0", "repo_root": "x"})
        ui_cli.run_ui(ns(host="0.0.0.0", unsafe_bind=True))
        err = capsys.readouterr().err
        assert "WARNING" in err and "NON-LOOPBACK" in err
        assert spawned and spawned[0][3] is True  # unsafe flag forwarded to the server

    def test_serve_mode_refuses_non_loopback_too(self, capsys):
        assert ui_cli.run_ui(ns(serve=True, host="0.0.0.0")) == 2


class TestSpawnReuseStop:
    def test_spawns_then_prints_tokenised_url_only_when_not_opening(self, spawned, monkeypatch, capsys):
        sess = {"token": "TOK123", "port": 9999, "host": "127.0.0.1", "repo_root": os.getcwd()}
        monkeypatch.setattr(ui_cli, "_wait_for_session", lambda *a, **k: sess)
        monkeypatch.setattr(ui_cli, "console_installed", lambda: False)
        assert ui_cli.run_ui(ns(no_open=True)) == 0
        out = capsys.readouterr().out
        assert "http://127.0.0.1:9999/#token=TOK123" in out and "pip install cognirepo-console" in out
        assert len(spawned) == 1

    def test_opens_browser_with_fragment_and_keeps_token_off_the_terminal(self, spawned, monkeypatch, capsys):
        sess = {"token": "TOK123", "port": 9999, "host": "127.0.0.1", "repo_root": os.getcwd()}
        monkeypatch.setattr(ui_cli, "_wait_for_session", lambda *a, **k: sess)
        opened = []
        monkeypatch.setattr(ui_cli.webbrowser, "open", lambda url: opened.append(url) or True)
        ui_cli.run_ui(ns(no_open=False))
        assert opened == ["http://127.0.0.1:9999/#token=TOK123"]
        assert "TOK123" not in capsys.readouterr().out

    def test_reuses_running_server_for_same_repo(self, spawned, monkeypatch):
        ui_session.write_session("T", "127.0.0.1", 9999, os.getpid(), os.getcwd())
        monkeypatch.setattr(ui_cli, "is_listening", lambda *a, **k: True)
        assert ui_cli.run_ui(ns()) == 0 and spawned == []

    def test_other_repo_running_is_refused(self, spawned, monkeypatch, capsys):
        ui_session.write_session("T", "127.0.0.1", 9999, os.getpid(), "/some/other/repo")
        monkeypatch.setattr(ui_cli, "is_listening", lambda *a, **k: True)
        assert ui_cli.run_ui(ns()) == 1 and spawned == [] and "--stop" in capsys.readouterr().err

    def test_stop_when_not_running_is_clean(self, capsys):
        assert ui_cli.run_ui(ns(stop=True)) == 0 and "not running" in capsys.readouterr().out

    def test_session_file_is_0600(self):
        ui_session.write_session("T", "127.0.0.1", 1, 1, "x")
        assert oct(os.stat(ui_session.session_path()).st_mode & 0o777) == "0o600"

    def test_spawn_uses_fixed_argv_and_detaches(self, monkeypatch, tmp_path):
        import subprocess
        import sys
        seen = {}
        monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: seen.update(argv=argv, kw=kw))
        ui_cli._spawn_server(str(tmp_path), "127.0.0.1", 8888, False, ["http://127.0.0.1:5173"])
        assert seen["argv"] == [sys.executable, "-m", "interface.cli.main", "ui", "--serve", "--no-open",
                                "--host", "127.0.0.1", "--port", "8888", "--allow-origin", "http://127.0.0.1:5173"]
        assert seen["kw"].get("shell") is not True and seen["kw"]["start_new_session"] is True


@pytest.fixture
def live(tmp_path):
    """A REAL uvicorn server on an ephemeral loopback port (no mocks between client and guard)."""
    built = ui_server.build(str(tmp_path), "127.0.0.1", 0)
    t = threading.Thread(target=built.server.run, kwargs={"sockets": [built.sock]}, daemon=True)
    t.start()
    for _ in range(100):
        if built.server.started:
            break
        time.sleep(0.05)
    assert built.server.started
    yield built
    built.server.should_exit = True
    t.join(5)
    built.sock.close()


class TestLiveServer:
    def test_real_http_roundtrip(self, live):
        base = f"http://127.0.0.1:{live.port}"
        assert httpx.get(base + "/api/v1/status").status_code == 401
        page = httpx.get(base + "/")  # bootstrap page is token-less but data-free
        assert page.status_code == 200 and "cognirepo-console" in page.text
        assert "default-src 'self'" in page.headers["content-security-policy"]
        js = httpx.get(base + "/_cognirepo/bootstrap.js")
        assert "replaceState" in js.text and js.text.index("replaceState") < js.text.index("fetch('/api/v1/session'")
        with httpx.Client(base_url=base) as c:
            r = c.post("/api/v1/session", json={"token": live.token})
            assert r.status_code == 200
            sc = r.headers["set-cookie"].lower()
            assert "httponly" in sc and "samesite=strict" in sc
            assert c.get("/api/v1/status").status_code == 200

    def test_rebinding_and_csrf_blocked_on_real_socket(self, live):
        base = f"http://127.0.0.1:{live.port}"
        h = {"Authorization": f"Bearer {live.token}"}
        assert httpx.get(base + "/api/v1/status", headers={**h, "Host": "evil.example"}).status_code == 403
        assert httpx.get(base + "/api/v1/status", headers={**h, "Origin": "https://evil.example"}).status_code == 403
        assert httpx.get(base + "/api/v1/status", headers=h).status_code == 200

    def test_only_loopback_socket(self, live):
        assert live.sock.getsockname()[0] == "127.0.0.1"

    def test_default_port_busy_falls_back_but_explicit_port_busy_errors(self, tmp_path):
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        busy = blocker.getsockname()[1]
        try:
            with pytest.raises(OSError):
                ui_server.build(str(tmp_path), "127.0.0.1", busy)
        finally:
            blocker.close()


class TestConsoleStatic:
    def test_serves_installed_console_and_blocks_traversal(self, tmp_path):
        from fastapi.testclient import TestClient

        from interface.ui import security as sec
        from interface.ui.app import create_app
        site = tmp_path / "dist"
        site.mkdir()
        (site / "index.html").write_text("<h1>engram</h1>")
        (tmp_path / "secret.txt").write_text("TOP-SECRET")
        app = create_app(sec.SecurityConfig(token="t", port=8731), str(tmp_path), console_dir=str(site))
        with TestClient(app, base_url="http://127.0.0.1:8731") as c:
            assert "engram" in c.get("/").text
            for evil in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt"):
                assert "TOP-SECRET" not in c.get(evil).text


@pytest.mark.skipif(os.name == "nt", reason="POSIX signals")
class TestGracefulShutdown:
    def test_sigterm_cleans_session_and_audits_stop(self, tmp_path):
        """uvicorn re-raises SIGTERM after shutdown; cleanup must still run (no stale token on disk)."""
        import json
        import signal
        import subprocess
        import sys
        env = {**os.environ, "COGNIREPO_GLOBAL_DIR": str(tmp_path / "g")}
        proc = subprocess.Popen([sys.executable, "-m", "interface.cli.main", "ui", "--serve", "--no-open", "--port", "0"],
                                cwd=str(tmp_path), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sess_file = tmp_path / "g" / "ui" / "session.json"
        try:
            for _ in range(200):
                if sess_file.exists() and ui_session.is_listening(json.loads(sess_file.read_text())["port"]):
                    break
                time.sleep(0.1)
            else:
                pytest.fail("server did not start")
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
        assert not sess_file.exists(), "stale session token left on disk"
        audit = (tmp_path / "g" / "ui" / "audit.log").read_text()
        assert "server_start" in audit and "server_stop" in audit


def test_run_ui_points_at_the_extra_when_deps_missing(monkeypatch, capsys):
    monkeypatch.setattr(ui_cli, "ui_extra_missing", lambda: ["fastapi", "uvicorn"])
    assert ui_cli.run_ui(argparse.Namespace()) == 1
    assert "pip install 'cognirepo[ui]'" in capsys.readouterr().err


def test_run_ui_stop_does_not_need_the_extra(monkeypatch):
    monkeypatch.setattr(ui_cli, "ui_extra_missing", lambda: ["fastapi"])
    monkeypatch.setattr(ui_cli, "_stop", lambda: 0)
    assert ui_cli.run_ui(argparse.Namespace(stop=True)) == 0
