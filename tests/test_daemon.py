# pylint: disable=missing-docstring, protected-access, redefined-outer-name, unused-argument, import-outside-toplevel
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_daemon.py — cognirepod: protocol, supervisor, repo workers, thin proxy, fallbacks (#116).

Unit tests need no processes. The integration tests start REAL supervisor and worker processes (a short run
directory under /tmp keeps AF_UNIX paths under the OS limit) and tear them down afterwards.
"""
import asyncio
import json
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the daemon uses Unix domain sockets")

from interface.daemon import client, paths, protocol  # noqa: E402
from interface.daemon.rpc_server import RpcServer, uid_allowed, peer_uid  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def wait_until(pred, timeout=20.0, step=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return False


def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


# ── unit: protocol ───────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def pair():
    a, b = socket.socketpair()
    a.settimeout(5)
    b.settimeout(5)
    yield a, b
    a.close()
    b.close()


class TestProtocol:
    def test_roundtrip_and_ordering(self, pair):
        a, b = pair
        for i in range(5):
            protocol.send(a, {"n": i, "text": "héllo ✓"})
        assert [protocol.recv(b)["n"] for _ in range(5)] == [0, 1, 2, 3, 4]

    def test_clean_close_between_frames_is_none(self, pair):
        a, b = pair
        a.close()
        assert protocol.recv(b) is None

    def test_oversize_header_refused_before_reading_the_body(self, pair):
        a, b = pair
        a.sendall(protocol.HEADER.pack(protocol.MAX_FRAME + 1))
        with pytest.raises(protocol.ProtocolError, match="exceeds"):
            protocol.recv(b)

    def test_send_refuses_an_oversize_message(self, pair):
        a, _ = pair
        with pytest.raises(protocol.ProtocolError):
            protocol.send(a, {"x": "a" * (protocol.MAX_FRAME + 10)})

    @pytest.mark.parametrize("body", [b"{not json", b"\xff\xfe\x00", b"[1, 2]", b'"text"', b"123"])
    def test_malformed_bodies(self, pair, body):
        a, b = pair
        a.sendall(protocol.HEADER.pack(len(body)) + body)
        with pytest.raises(protocol.ProtocolError):
            protocol.recv(b)

    def test_truncated_frame(self, pair):
        a, b = pair
        a.sendall(protocol.HEADER.pack(100) + b'{"a":')
        a.close()
        with pytest.raises(protocol.ProtocolError, match="mid-frame"):
            protocol.recv(b)

    def test_random_garbage_never_raises_anything_else(self):
        rng = random.Random(1234)
        for _ in range(200):
            a, b = socket.socketpair()
            b.settimeout(2)
            try:
                a.sendall(bytes(rng.getrandbits(8) for _ in range(rng.randint(0, 64))))
                a.close()
                try:
                    protocol.recv(b)
                except protocol.ProtocolError:
                    pass
            finally:
                b.close()

    @pytest.mark.parametrize("msg", [{}, {"jsonrpc": "1.0", "method": "x"}, {"jsonrpc": "2.0"},
                                     {"jsonrpc": "2.0", "method": 5}])
    def test_invalid_requests(self, msg):
        with pytest.raises(protocol.RpcError) as exc:
            protocol.parse_request(msg)
        assert exc.value.code == protocol.INVALID_REQUEST

    def test_params_must_be_an_object(self):
        with pytest.raises(protocol.RpcError) as exc:
            protocol.parse_request({"jsonrpc": "2.0", "method": "m", "params": [1]})
        assert exc.value.code == protocol.INVALID_PARAMS

    def test_call_rejects_a_reply_for_another_request(self, pair):
        a, b = pair
        protocol.send(b, protocol.result(99, "x"))
        with pytest.raises(protocol.ProtocolError, match="does not match"):
            protocol.call(a, "m", req_id=1)

    def test_call_raises_rpc_error(self, pair):
        a, b = pair
        protocol.send(b, protocol.error(1, protocol.UNKNOWN_REPO, "nope", {"k": 1}))
        with pytest.raises(protocol.RpcError) as exc:
            protocol.call(a, "m", req_id=1)
        assert (exc.value.code, exc.value.message, exc.value.data) == (protocol.UNKNOWN_REPO, "nope", {"k": 1})


# ── unit: settings and run directory ─────────────────────────────────────────────────────────────────

class TestSettings:
    def test_off_by_default(self, monkeypatch):
        for k in list(os.environ):
            if k.startswith("COGNIREPO_DAEMON"):
                monkeypatch.delenv(k)
        assert paths.setting("enabled") is False and paths.enabled() is False

    def test_env_wins_over_global_config(self, monkeypatch, tmp_path):
        from core.config.paths import get_global_dir
        os.makedirs(get_global_dir(), exist_ok=True)
        with open(os.path.join(get_global_dir(), "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"daemon": {"enabled": True, "max_workers": 9, "worker_idle_secs": "bad"}}, fh)
        monkeypatch.delenv("COGNIREPO_DAEMON", raising=False)
        monkeypatch.delenv("COGNIREPO_DAEMON_ENABLED", raising=False)
        assert paths.setting("enabled") is True
        assert paths.setting("max_workers") == 9
        assert paths.setting("worker_idle_secs") == 600            # unparsable -> default
        monkeypatch.setenv("COGNIREPO_DAEMON", "0")
        assert paths.setting("enabled") is False
        monkeypatch.setenv("COGNIREPO_DAEMON_MAX_WORKERS", "2")
        assert paths.setting("max_workers") == 2

    def test_unsupported_platform_never_enables(self, monkeypatch):
        monkeypatch.setenv("COGNIREPO_DAEMON", "1")
        monkeypatch.setattr(paths, "SUPPORTED", False)
        assert paths.enabled() is False


class TestRunDir:
    def test_created_private(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIREPO_RUN_DIR", str(tmp_path / "r"))
        d = paths.run_dir()
        assert oct(os.stat(d).st_mode & 0o777) == "0o700"

    def test_loose_permissions_are_tightened(self, tmp_path, monkeypatch):
        d = tmp_path / "r"
        d.mkdir(mode=0o777)
        os.chmod(d, 0o777)
        monkeypatch.setenv("COGNIREPO_RUN_DIR", str(d))
        paths.run_dir()
        assert oct(os.stat(d).st_mode & 0o777) == "0o700"

    def test_directory_owned_by_someone_else_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIREPO_RUN_DIR", str(tmp_path / "r"))
        paths.run_dir()
        monkeypatch.setattr(os, "getuid", lambda: os.stat(tmp_path / "r").st_uid + 1)
        with pytest.raises(paths.RunDirError, match="another user"):
            paths.run_dir()

    def test_too_long_socket_path_is_reported(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIREPO_RUN_DIR", str(tmp_path / ("x" * 120)))
        with pytest.raises(paths.RunDirError, match="too long"):
            paths.supervisor_socket()

    def test_worker_sockets_are_stable_and_distinct(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIREPO_RUN_DIR", str(tmp_path / "r"))
        a, b = str(tmp_path / "a"), str(tmp_path / "b")
        assert paths.worker_socket(a) == paths.worker_socket(a + "/") != paths.worker_socket(b)


# ── unit: the shared RPC server ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def sockdir():
    d = tempfile.mkdtemp(prefix="crt")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def rpc(sockdir):
    seen = {"disconnects": 0}

    def boom(_c, _p):
        raise RuntimeError("handler bug")

    def disc(_c):
        seen["disconnects"] += 1

    server = RpcServer(os.path.join(sockdir, "s.sock"), {
        "echo": lambda c, p: p, "boom": boom,
        "remember": lambda c, p: c.state.setdefault("n", p.get("n")),
    }, name="test", on_disconnect=disc)
    server.start()
    server.seen = seen
    yield server
    server.stop()


def connect(server):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(server.path)
    return s


class TestRpcServer:
    def test_socket_is_0600(self, rpc):
        assert oct(os.stat(rpc.path).st_mode & 0o777) == "0o600"

    def test_echo_and_unknown_method(self, rpc):
        s = connect(rpc)
        assert protocol.call(s, "echo", {"a": 1}) == {"a": 1}
        with pytest.raises(protocol.RpcError) as exc:
            protocol.call(s, "nope", req_id=2)
        assert exc.value.code == protocol.METHOD_NOT_FOUND
        s.close()

    def test_a_crashing_handler_is_an_error_not_a_dead_server(self, rpc):
        s = connect(rpc)
        with pytest.raises(protocol.RpcError) as exc:
            protocol.call(s, "boom")
        assert exc.value.code == protocol.INTERNAL and "handler bug" in exc.value.message
        assert protocol.call(s, "echo", {"still": "up"}, 2) == {"still": "up"}
        s.close()

    def test_bad_frame_gets_parse_error_and_the_connection_is_dropped(self, rpc):
        s = connect(rpc)
        s.sendall(protocol.HEADER.pack(5) + b"{oops")
        reply = protocol.recv(s)
        assert reply["error"]["code"] == protocol.PARSE_ERROR
        assert protocol.recv(s) is None
        s.close()

    def test_per_connection_state(self, rpc):
        a, b = connect(rpc), connect(rpc)
        assert protocol.call(a, "remember", {"n": 1}) == 1
        assert protocol.call(b, "remember", {"n": 2}) == 2
        assert protocol.call(a, "remember", {"n": 99}, 2) == 1       # a still has ITS state
        a.close()
        b.close()

    def test_disconnect_callback_and_count(self, rpc):
        socks = [connect(rpc) for _ in range(3)]
        for s in socks:
            protocol.call(s, "echo")
        assert rpc.connection_count() == 3
        for s in socks:
            s.close()
        assert wait_until(lambda: rpc.seen["disconnects"] == 3 and rpc.connection_count() == 0, 5)

    def test_concurrent_clients(self, rpc):
        errors = []

        def work(i):
            try:
                s = connect(rpc)
                for j in range(20):
                    assert protocol.call(s, "echo", {"i": i, "j": j}, j + 1) == {"i": i, "j": j}
                s.close()
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        assert errors == []

    def test_stale_socket_file_is_replaced(self, sockdir):
        path = os.path.join(sockdir, "stale.sock")
        dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        dead.bind(path)
        dead.close()                                                 # a file nobody listens on
        server = RpcServer(path, {"echo": lambda c, p: p})
        server.start()
        try:
            assert protocol.call(connect(server), "echo", {"ok": 1}) == {"ok": 1}
        finally:
            server.stop()

    def test_a_live_socket_is_not_stolen(self, rpc):
        other = RpcServer(rpc.path, {})
        with pytest.raises(OSError, match="already served"):
            other.start()

    def test_stop_removes_the_socket(self, sockdir):
        server = RpcServer(os.path.join(sockdir, "x.sock"), {})
        server.start()
        server.stop()
        assert not os.path.exists(server.path)

    def test_uid_policy(self):
        assert uid_allowed(1000, 1000) and uid_allowed(None, 1000)
        assert not uid_allowed(0, 1000) and not uid_allowed(1001, 1000)

    @pytest.mark.skipif(not sys.platform.startswith("linux"), reason="SO_PEERCRED")
    def test_peer_uid_is_ours_on_linux(self):
        a, b = socket.socketpair()
        try:
            assert peer_uid(a) == os.getuid()
        finally:
            a.close()
            b.close()

    def test_a_foreign_uid_is_refused_at_accept(self, sockdir, monkeypatch):
        from interface.daemon import rpc_server
        monkeypatch.setattr(rpc_server, "peer_uid", lambda _s: os.getuid() + 1)
        server = RpcServer(os.path.join(sockdir, "f.sock"), {"echo": lambda c, p: p})
        server.start()
        try:
            s = connect(server)
            with pytest.raises((protocol.ProtocolError, OSError)):
                protocol.call(s, "echo")
        finally:
            server.stop()


# ── unit: per-client session context in the shared worker ────────────────────────────────────────────

class TestClientSessionContext:
    @pytest.fixture
    def ms(self, monkeypatch):
        from interface.server import mcp_server
        sent = []
        from core import events
        monkeypatch.setattr(events, "emit", lambda type_, **kw: sent.append((type_, kw)))
        monkeypatch.setattr(events, "record_session", lambda *a, **k: None)
        monkeypatch.setattr(mcp_server, "_MCP_SESSION", {"session_id": "process"})
        monkeypatch.setattr(mcp_server, "_MCP_CLIENT", "process-client")
        monkeypatch.setattr(mcp_server, "_CALL_COUNT", 0)
        mcp_server.sent = sent
        return mcp_server

    def test_events_carry_the_clients_session_not_the_process_one(self, ms):
        from interface.server import client_session as csm
        cs = csm.ClientSession(mcp_session={"session_id": "agent-1"}, client="claude-code")
        token = csm.CURRENT.set(cs)
        try:
            ms._emit_tool_event("tool.start", "lookup_symbol", "t1")
            ms._emit_tool_event("tool.end", "lookup_symbol", "t1")
        finally:
            csm.CURRENT.reset(token)
        assert [(t, kw["session_id"], kw["client"]) for t, kw in ms.sent] == [
            ("tool.start", "agent-1", "claude-code"), ("tool.end", "agent-1", "claude-code")]
        assert cs.call_count == 1 and ms._CALL_COUNT == 0

    def test_without_a_client_session_the_process_globals_are_used(self, ms):
        ms._emit_tool_event("tool.start", "t", "x")
        assert ms.sent[0][1]["session_id"] == "process" and ms._CALL_COUNT == 1

    def test_threads_do_not_see_each_others_session(self, ms):
        from interface.server import client_session as csm
        seen = {}

        def run(name):
            cs = csm.ClientSession(mcp_session={"session_id": name}, client=name)
            token = csm.CURRENT.set(cs)
            try:
                for _ in range(50):
                    ms._emit_tool_event("tool.start", "t", name)
                seen[name] = cs.call_count
            finally:
                csm.CURRENT.reset(token)

        threads = [threading.Thread(target=run, args=(f"a{i}",)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert seen == {f"a{i}": 50 for i in range(6)}
        by_sid = {}
        for _t, kw in ms.sent:
            by_sid.setdefault(kw["session_id"], set()).add(kw["client"])
        assert all(clients == {sid} for sid, clients in by_sid.items())     # each session only ever saw its own client

    def test_session_end_is_once_per_client(self, ms):
        from interface.server import client_session as csm
        cs = csm.ClientSession(mcp_session={"session_id": "agent-2"}, client="gemini")
        token = csm.CURRENT.set(cs)
        try:
            ms._emit_session_event("session.end")
            ms._emit_session_event("session.end")
        finally:
            csm.CURRENT.reset(token)
        ends = [kw for t, kw in ms.sent if t == "session.end"]
        assert len(ends) == 1 and ends[0]["session_id"] == "agent-2" and cs.ended and ms._SESSION_ENDED is False

    def test_conversation_log_is_per_client(self, ms, monkeypatch):
        from interface.server import client_session as csm
        import intelligence.orchestrator.session as sess
        monkeypatch.setattr(sess, "append_exchange", lambda s, user_msg, assistant_msg: {**s, "last": user_msg})
        cs = csm.ClientSession(mcp_session={"session_id": "agent-3"})
        token = csm.CURRENT.set(cs)
        try:
            ms._record_mcp_tool_call("lookup_symbol", "q", "r")
        finally:
            csm.CURRENT.reset(token)
        assert cs.mcp_session["last"].startswith("[tool:lookup_symbol]") and ms._MCP_SESSION == {"session_id": "process"}


class TestEncodeResult:
    def test_three_shapes(self):
        from mcp import types
        from interface.daemon.worker import encode_result
        block = types.TextContent(type="text", text="hi")
        assert encode_result([block]) == {"content": [{"type": "text", "text": "hi"}], "structured": None}
        assert encode_result(([block], {"result": "hi"}))["structured"] == {"result": "hi"}
        assert encode_result({"a": 1}) == {"content": None, "structured": {"a": 1}}

    def test_trim_memory_is_safe(self):
        from interface.daemon.worker import trim_memory
        trim_memory()


# ── integration: real supervisor + worker processes ──────────────────────────────────────────────────

def make_repo(parent, name="repo", index=False):
    repo = os.path.join(str(parent), name)
    os.makedirs(os.path.join(repo, ".cognirepo"), exist_ok=True)
    with open(os.path.join(repo, ".cognirepo", "config.json"), "w", encoding="utf-8") as fh:
        fh.write("{}")
    with open(os.path.join(repo, "mod.py"), "w", encoding="utf-8") as fh:
        fh.write("def hello_world():\n    return 1\n\n\nclass Greeter:\n    def greet(self):\n        return hello_world()\n")
    if index:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        env = {**os.environ, "PYTHONPATH": ROOT}
        out = subprocess.run([sys.executable, "-m", "interface.cli.main", "index-repo", ".", "--no-embed", "--no-watch"],
                             cwd=repo, env=env, capture_output=True, text=True, timeout=120, check=False)
        assert out.returncode == 0, out.stderr
    return repo


@pytest.fixture
def daemon_env(monkeypatch, tmp_path):
    """A private run dir + global dir, fast timeouts, and a teardown that leaves no process behind."""
    run = tempfile.mkdtemp(prefix="crd")
    monkeypatch.setenv("COGNIREPO_RUN_DIR", run)
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "g"))
    monkeypatch.setenv("COGNIREPO_NO_WATCHER", "1")
    monkeypatch.setenv("PYTHONPATH", ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""))
    monkeypatch.setenv("COGNIREPO_DAEMON", "1")
    monkeypatch.setenv("COGNIREPO_DAEMON_SPAWN_TIMEOUT_SECS", "60")
    pids = set()
    yield {"run": run, "pids": pids, "tmp": tmp_path}
    st = client.status() or {}
    pids.update([st["pid"]] if st else [])
    pids.update(w["pid"] for w in st.get("workers", []))
    try:
        client.stop()
    except Exception:  # pylint: disable=broad-except
        pass
    for pid in pids:
        if alive(pid):
            os.kill(pid, signal.SIGKILL)
    shutil.rmtree(run, ignore_errors=True)


class TestSupervisor:
    def test_start_status_stop(self, daemon_env):
        assert client.status() is None
        info = client.ensure_supervisor()
        daemon_env["pids"].add(info["pid"])
        st = client.status()
        assert st["pid"] == info["pid"] and st["workers"] == [] and st["version"] == client._version()
        assert oct(os.stat(paths.supervisor_socket()).st_mode & 0o777) == "0o600"
        assert client.stop() is True
        assert wait_until(lambda: client.status() is None, 10) and wait_until(lambda: not alive(info["pid"]), 10)
        assert client.stop() is False

    def test_start_is_idempotent(self, daemon_env):
        a = client.ensure_supervisor()
        b = client.ensure_supervisor()
        daemon_env["pids"].add(a["pid"])
        assert a["pid"] == b["pid"]

    def test_concurrent_first_clients_start_exactly_one_supervisor(self, daemon_env):
        results, errors = [], []

        def go():
            try:
                results.append(client.ensure_supervisor()["pid"])
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(exc)

        threads = [threading.Thread(target=go) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        daemon_env["pids"].update(results)
        assert errors == [] and len(set(results)) == 1

    def test_recovers_after_the_supervisor_is_killed_9(self, daemon_env):
        first = client.ensure_supervisor()
        daemon_env["pids"].add(first["pid"])
        os.kill(first["pid"], signal.SIGKILL)
        assert wait_until(lambda: not alive(first["pid"]), 10)
        second = client.ensure_supervisor()                     # stale socket + released lock
        daemon_env["pids"].add(second["pid"])
        assert second["pid"] != first["pid"]

    def test_exits_by_itself_when_idle(self, daemon_env, monkeypatch):
        monkeypatch.setenv("COGNIREPO_DAEMON_IDLE_EXIT_SECS", "2")
        info = client.ensure_supervisor()
        daemon_env["pids"].add(info["pid"])
        assert wait_until(lambda: client.status() is None and not alive(info["pid"]), 20)

    def test_an_older_supervisor_is_replaced(self, daemon_env, monkeypatch):
        old = client.ensure_supervisor()
        daemon_env["pids"].add(old["pid"])
        monkeypatch.setattr(client, "_version", lambda: "0.0.0-newer-client")
        with pytest.raises(client.DaemonUnavailable, match="different version"):
            client.ensure_supervisor()
        assert wait_until(lambda: not alive(old["pid"]), 15)    # it WAS shut down and respawned
        st = client.status()
        daemon_env["pids"].add(st["pid"])
        assert st["pid"] != old["pid"]


class TestWorkers:
    def test_spawn_reuse_and_second_repo(self, daemon_env):
        a = make_repo(daemon_env["tmp"], "a")
        b = make_repo(daemon_env["tmp"], "b")
        w1 = client.worker_info(a)
        w2 = client.worker_info(a)
        w3 = client.worker_info(b)
        daemon_env["pids"].update([w1["pid"], w3["pid"]])
        assert w1["pid"] == w2["pid"] != w3["pid"] and w1["socket"] != w3["socket"]
        assert oct(os.stat(w1["socket"]).st_mode & 0o777) == "0o600"
        assert {w["repo"] for w in client.status()["workers"]} == {a, b}

    def test_concurrent_requests_for_one_repo_spawn_one_worker(self, daemon_env):
        repo = make_repo(daemon_env["tmp"])
        pids, errors = [], []

        def go():
            try:
                pids.append(client.worker_info(repo)["pid"])
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(exc)

        threads = [threading.Thread(target=go) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(90)
        daemon_env["pids"].update(pids)
        assert errors == [] and len(set(pids)) == 1

    @pytest.mark.parametrize("bad", ["/etc", "/", "/nonexistent/repo", "relative/../../etc", "", "a\0b", "x" * 5000])
    def test_arbitrary_or_uninitialised_paths_never_start_a_worker(self, daemon_env, bad):
        with pytest.raises(client.DaemonUnavailable):
            client.worker_info(bad)
        assert client.status()["workers"] == []

    def test_a_plain_directory_without_a_store_is_refused(self, daemon_env):
        plain = daemon_env["tmp"] / "plain"
        plain.mkdir()
        with pytest.raises(client.DaemonUnavailable, match="not an initialised"):
            client.worker_info(str(plain))

    def test_worker_exits_when_idle_and_respawns_on_demand(self, daemon_env, monkeypatch):
        monkeypatch.setenv("COGNIREPO_DAEMON_WORKER_IDLE_SECS", "2")
        repo = make_repo(daemon_env["tmp"])
        first = client.worker_info(repo)
        daemon_env["pids"].add(first["pid"])
        assert wait_until(lambda: not alive(first["pid"]), 30)
        assert wait_until(lambda: client.status()["workers"] == [], 10)
        second = client.worker_info(repo)
        daemon_env["pids"].add(second["pid"])
        assert second["pid"] != first["pid"]

    def test_worker_with_a_connected_client_is_not_reaped(self, daemon_env, monkeypatch):
        monkeypatch.setenv("COGNIREPO_DAEMON_WORKER_IDLE_SECS", "2")
        repo = make_repo(daemon_env["tmp"])
        link = client.WorkerLink(repo, "keeper").open()
        daemon_env["pids"].add(link.info["pid"])
        time.sleep(5)
        assert alive(link.info["pid"]) and link.call("tools.list", {})
        link.close()

    def test_a_killed_worker_is_replaced(self, daemon_env):
        repo = make_repo(daemon_env["tmp"])
        first = client.worker_info(repo)
        os.kill(first["pid"], signal.SIGKILL)
        assert wait_until(lambda: not alive(first["pid"]), 10)
        second = client.worker_info(repo)
        daemon_env["pids"].add(second["pid"])
        assert second["pid"] != first["pid"]

    def test_max_workers_evicts_an_idle_one_but_never_one_with_clients(self, daemon_env, monkeypatch):
        monkeypatch.setenv("COGNIREPO_DAEMON_MAX_WORKERS", "1")
        a, b = make_repo(daemon_env["tmp"], "a"), make_repo(daemon_env["tmp"], "b")
        wa = client.worker_info(a)
        daemon_env["pids"].add(wa["pid"])
        wb = client.worker_info(b)                             # `a` has no clients: it is replaced
        daemon_env["pids"].add(wb["pid"])
        assert wait_until(lambda: not alive(wa["pid"]), 15)
        assert [w["repo"] for w in client.status()["workers"]] == [b]
        link = client.WorkerLink(b, "busy").open()             # now `b` has a client
        with pytest.raises(client.DaemonUnavailable, match="already active"):
            client.worker_info(a)
        assert alive(wb["pid"])
        link.close()

    def test_version_skew_stops_the_old_worker(self, daemon_env, monkeypatch):
        repo = make_repo(daemon_env["tmp"])
        info = client.worker_info(repo)
        daemon_env["pids"].add(info["pid"])
        real = client._version
        monkeypatch.setattr(client, "_version", lambda: "9.9.9")
        # the supervisor version no longer matches either, so go straight at the worker the way a stale client would
        s = client.connect(info["socket"])
        with pytest.raises(protocol.RpcError) as exc:
            protocol.call(s, "hello", {"version": "9.9.9"})
        s.close()
        assert exc.value.code == protocol.VERSION_MISMATCH and exc.value.data["worker_version"] == real()


class TestSessions:
    def test_three_agents_share_one_worker_with_separate_sessions(self, daemon_env):
        from core import events
        repo = make_repo(daemon_env["tmp"], index=True)
        links = [client.WorkerLink(repo, name).open() for name in ("claude-code", "gemini-cli", "cursor")]
        daemon_env["pids"].add(links[0].info["pid"])
        assert len({l.info["pid"] for l in links}) == 1
        assert len({l.session_id for l in links}) == 3
        for i, link in enumerate(links):
            for _ in range(i + 1):
                try:      # search_docs goes through _traced (tool.start/end events); an error result still counts as a call
                    link.call("tools.call", {"name": "search_docs", "arguments": {"query": "hello"}})
                except protocol.RpcError:
                    pass
        assert client.status()["workers"][0]["clients"] == 3
        store = os.path.join(repo, ".cognirepo")
        rows = {r["client"]: r for r in events.list_sessions(store) if r["id"] in {l.session_id for l in links}}
        assert set(rows) == {"claude-code", "gemini-cli", "cursor"}
        assert [rows[n]["call_count"] for n in ("claude-code", "gemini-cli", "cursor")] == [1, 2, 3]
        assert {r["pid"] for r in rows.values()} == {links[0].info["pid"]}
        assert all(r["state"] == "active" for r in rows.values())
        for link in links:
            link.close()
        assert wait_until(lambda: all(r["closed_by"] == "session_end" for r in events.list_sessions(store)
                                      if r["id"] in {l.session_id for l in links}), 10)

    def test_calls_before_session_open_are_refused(self, daemon_env):
        repo = make_repo(daemon_env["tmp"])
        info = client.worker_info(repo)
        daemon_env["pids"].add(info["pid"])
        s = client.connect(info["socket"])
        with pytest.raises(protocol.RpcError, match="open a session"):
            protocol.call(s, "tools.call", {"name": "lookup_symbol", "arguments": {}})
        s.close()

    def test_bad_tool_call_params(self, daemon_env):
        repo = make_repo(daemon_env["tmp"])
        link = client.WorkerLink(repo).open()
        daemon_env["pids"].add(link.info["pid"])
        with pytest.raises(protocol.RpcError) as exc:
            link.call("tools.call", {"name": 5, "arguments": []})
        assert exc.value.code == protocol.INVALID_PARAMS
        with pytest.raises(protocol.RpcError) as exc:
            link.call("tools.call", {"name": "no_such_tool", "arguments": {}})
        assert exc.value.code == protocol.TOOL_ERROR
        link.close()

    def test_tool_list_matches_the_in_process_server(self, daemon_env):
        repo = make_repo(daemon_env["tmp"])
        link = client.WorkerLink(repo).open()
        daemon_env["pids"].add(link.info["pid"])
        remote = {t["name"] for t in link.call("tools.list", {})}
        from interface.server import mcp_server
        local = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
        assert remote == local and len(local) >= 30
        link.close()


# ── integration: the real MCP SDK against `cognirepo serve`, daemon vs in-process ────────────────────

async def _drive(repo, daemon):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    env = {**os.environ, "COGNIREPO_DAEMON": "1" if daemon else "0"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "interface.cli.main", "serve"], env=env, cwd=repo)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            out = {"server": init.serverInfo.name, "tools": sorted(t.name for t in (await s.list_tools()).tools)}
            for key, name, args in (("lookup", "lookup_symbol", {"name": "hello_world"}),
                                    ("lookup_missing", "lookup_symbol", {"name": "does_not_exist_anywhere"}),
                                    ("stats", "graph_stats", {}),
                                    ("docs", "search_docs", {"query": "hello"}),
                                    ("missing_arg", "lookup_symbol", {}),
                                    ("unknown", "no_such_tool", {})):
                res = await s.call_tool(name, args)
                texts = [c.text for c in res.content]
                if key == "stats":      # a timestamp that is "now" in each run
                    texts = [t.replace(json.loads(t)["integrity"]["swept_at"], "<swept_at>") for t in texts]
                out[key] = (res.isError, texts,
                            json.dumps(res.structuredContent, sort_keys=True) if res.structuredContent else None)
            return out


class TestThinProxyMatchesInProcess:
    def test_identical_results_through_the_real_mcp_sdk(self, daemon_env):
        repo = make_repo(daemon_env["tmp"], index=True)
        via_daemon = asyncio.run(_drive(repo, True))
        st = client.status()
        assert st is not None and len(st["workers"]) == 1, "the proxy should have used the worker"
        daemon_env["pids"].add(st["workers"][0]["pid"])
        in_process = asyncio.run(_drive(repo, False))
        assert via_daemon["server"] == in_process["server"] == "cognirepo"
        for key in via_daemon:
            assert via_daemon[key] == in_process[key], key
        assert via_daemon["lookup"][0] is False and via_daemon["unknown"][0] is True

    def test_proxy_imports_nothing_heavy(self):
        code = ("import sys; import interface.daemon.proxy; "
                "bad = [m for m in ('faiss', 'numpy', 'fastembed', 'networkx', 'interface.server.mcp_server') if m in sys.modules]; "
                "print(bad)")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ROOT},
                             check=False)
        assert out.stdout.strip() == "[]", out.stdout + out.stderr


# ── failure handling: the agent must never be left hanging ───────────────────────────────────────────

class TestFallback:
    def test_disabled_or_uninitialised_means_no_proxy(self, daemon_env, monkeypatch):
        from interface.daemon import proxy
        repo = make_repo(daemon_env["tmp"])
        monkeypatch.setenv("COGNIREPO_DAEMON", "0")
        assert proxy.run_proxy(repo) is False
        monkeypatch.setenv("COGNIREPO_DAEMON", "1")
        plain = daemon_env["tmp"] / "plain"
        plain.mkdir()
        assert proxy.run_proxy(str(plain)) is False
        assert client.status() is None                              # and nothing was started for it

    def test_an_unusable_run_dir_falls_back_quietly(self, daemon_env, monkeypatch, capsys):
        from interface.daemon import proxy
        repo = make_repo(daemon_env["tmp"])
        monkeypatch.setenv("COGNIREPO_RUN_DIR", str(daemon_env["tmp"] / ("x" * 120)))
        assert proxy.run_proxy(repo) is False
        assert capsys.readouterr().out == ""                        # stdout belongs to JSON-RPC

    def test_a_daemon_that_cannot_start_falls_back(self, daemon_env, monkeypatch):
        from interface.daemon import proxy
        repo = make_repo(daemon_env["tmp"])
        monkeypatch.setattr(client, "_spawn_supervisor", lambda: (_ for _ in ()).throw(OSError("no fork")))
        monkeypatch.setattr(client, "_wait", lambda *a, **k: False)
        assert proxy.run_proxy(repo) is False

    def test_a_wedged_supervisor_does_not_hang_the_client(self, daemon_env, monkeypatch):
        """A listener that accepts but never answers: the client must give up within its timeout."""
        monkeypatch.setenv("COGNIREPO_DAEMON_CONNECT_TIMEOUT_SECS", "1")
        sock = paths.supervisor_socket()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock)
        srv.listen(8)
        held = []
        stop = threading.Event()

        def accept_and_stay_silent():
            srv.settimeout(0.2)
            while not stop.is_set():
                try:
                    held.append(srv.accept()[0])
                except OSError:
                    continue

        t = threading.Thread(target=accept_and_stay_silent, daemon=True)
        t.start()
        try:
            started = time.time()
            assert client.supervisor_info() is None
            assert time.time() - started < 5
        finally:
            stop.set()
            t.join(2)
            for h in held:
                h.close()
            srv.close()

    def test_a_worker_that_died_between_calls_is_replaced_transparently(self, daemon_env):
        """The request never reached a dead worker, so retrying on a fresh one cannot run a tool twice."""
        from interface.daemon.proxy import Link
        repo = make_repo(daemon_env["tmp"], index=True)
        link = Link(repo)
        link.client_name = "agent"
        assert link.call("tools.list", {})
        old_pid = link._link.info["pid"]
        daemon_env["pids"].add(old_pid)
        os.kill(old_pid, signal.SIGKILL)
        assert wait_until(lambda: not alive(old_pid), 10)
        res = link.call("tools.call", {"name": "lookup_symbol", "arguments": {"name": "hello_world"}})
        assert res["content"]
        daemon_env["pids"].add(link._link.info["pid"])
        assert link._link.info["pid"] != old_pid
        link.close()

    def test_a_connection_lost_after_the_request_was_sent_is_reported_not_retried(self):
        """We cannot know whether the tool ran, so the agent is told — and the next call reconnects."""
        from interface.daemon import proxy

        a, b = socket.socketpair()
        received = []

        def worker_side():
            received.append(protocol.recv(b))          # reads the request ...
            b.close()                                  # ... and dies without answering

        t = threading.Thread(target=worker_side)
        t.start()

        class FakeLink:
            sock = a
            _next_id = 3

            def close(self):
                a.close()

        link = proxy.Link("/unused")
        link._link = FakeLink()
        link._ensure = lambda: link._link
        with pytest.raises(RuntimeError, match="may or may not"):
            link.call("tools.call", {"name": "store_memory", "arguments": {"text": "x"}})
        t.join(5)
        assert len(received) == 1 and received[0]["method"] == "tools.call"      # sent exactly once
        assert link._link is None                                                # the next call will reconnect


class TestCli:
    def run(self, daemon_env, *args):
        env = {**os.environ}
        return subprocess.run([sys.executable, "-m", "interface.cli.main", "daemon", *args], capture_output=True, text=True,
                              env=env, cwd=str(daemon_env["tmp"]), timeout=60, check=False)

    def test_status_json_when_not_running(self, daemon_env):
        out = self.run(daemon_env, "status", "--json")
        assert out.returncode == 0 and json.loads(out.stdout) == {"running": False}
        assert "not running" in self.run(daemon_env, "status").stdout

    def test_start_status_restart_stop(self, daemon_env):
        started = self.run(daemon_env, "start")
        assert started.returncode == 0 and "running (pid" in started.stdout
        st = json.loads(self.run(daemon_env, "status", "--json").stdout)
        daemon_env["pids"].add(st["pid"])
        again = self.run(daemon_env, "restart")
        assert again.returncode == 0
        st2 = json.loads(self.run(daemon_env, "status", "--json").stdout)
        daemon_env["pids"].add(st2["pid"])
        assert st2["pid"] != st["pid"]
        assert "stopped" in self.run(daemon_env, "stop").stdout
        assert "not running" in self.run(daemon_env, "stop").stdout

    def test_render_status_lists_workers(self):
        from interface.daemon.cli import render_status
        text = render_status({"version": "1", "pid": 5, "rss_bytes": 31 * 1048576, "socket": "/s", "max_workers": 4,
                              "workers": [{"repo": "/r", "pid": 7, "alive": True, "clients": 2, "calls": 9,
                                           "rss_bytes": 400 * 1048576, "idle_secs": 1.5}]})
        assert "workers: 1 of 4" in text and "/r  pid 7  up  clients 2  calls 9  400 MB" in text

    def test_doctor_reports_the_daemon(self, daemon_env):
        repo = make_repo(daemon_env["tmp"])
        info = client.ensure_supervisor()
        daemon_env["pids"].add(info["pid"])
        out = subprocess.run([sys.executable, "-m", "interface.cli.main", "doctor", "--json"], capture_output=True, text=True,
                             env={**os.environ}, cwd=repo, timeout=120, check=False)
        results = json.loads(out.stdout[out.stdout.index("["):out.stdout.rindex("]") + 1]) if "[" in out.stdout else []
        messages = " ".join(r["message"] for r in results) if results else out.stdout
        assert "Daemon — cognirepod" in messages, out.stdout[-500:]
