# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""A small threaded Unix-socket JSON-RPC server shared by the supervisor and the workers.

Security properties (ADR 003 §1): the socket is created ``0600`` inside a ``0700`` run directory, only the owning
uid may talk to it (``SO_PEERCRED`` / ``LOCAL_PEERCRED`` where the OS has them), there is no TCP, frames are
size-capped by ``protocol``, and a handler can only be reached through the explicit table it is constructed with.
"""
from __future__ import annotations

import logging
import os
import socket
import struct
import sys
import threading
from typing import Any, Callable

from interface.daemon import protocol

logger = logging.getLogger(__name__)

Handler = Callable[["Connection", dict[str, Any]], Any]


def peer_uid(conn: socket.socket) -> int | None:
    """The uid of the process on the other end, or ``None`` if the OS cannot say."""
    try:
        if sys.platform.startswith("linux"):
            _pid, uid, _gid = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                                 struct.calcsize("3i")))
            return uid
        if sys.platform == "darwin":
            # xucred { u_int cr_version; uid_t cr_uid; ... } from LOCAL_PEERCRED (level 0, option 1)
            raw = conn.getsockopt(0, 1, 76)
            return struct.unpack_from("II", raw)[1]
    except (OSError, AttributeError, struct.error):
        pass
    return None


def uid_allowed(uid: int | None, own_uid: int | None = None) -> bool:
    """Unknown peers (``None``) are allowed because the 0700 run directory already excludes other users;
    a known foreign uid is refused."""
    own = os.getuid() if own_uid is None else own_uid
    return uid is None or uid == own


class Connection:
    """One client connection; ``state`` is free for the handlers to keep per-connection data in."""

    def __init__(self, sock: socket.socket, server: "RpcServer") -> None:
        self.sock = sock
        self.server = server
        self.state: dict[str, Any] = {}


class RpcServer:
    def __init__(self, path: str, handlers: dict[str, Handler], *, name: str = "rpc",
                 on_disconnect: Callable[[Connection], None] | None = None) -> None:
        self.path = path
        self.handlers = handlers
        self.name = name
        self.on_disconnect = on_disconnect
        self._listener: socket.socket | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.connections: set[Connection] = set()

    # -- lifecycle ----------------------------------------------------------------------------
    def start(self) -> None:
        self._remove_stale()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)                     # the socket file is created 0600
        try:
            listener.bind(self.path)
        finally:
            os.umask(old)
        os.chmod(self.path, 0o600)
        listener.listen(32)
        listener.settimeout(0.5)
        self._listener = listener
        self._thread = threading.Thread(target=self._accept_loop, name=f"{self.name}-accept", daemon=True)
        self._thread.start()

    def _remove_stale(self) -> None:
        if not os.path.exists(self.path):
            return
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(1.0)
        try:
            probe.connect(self.path)
        except (ConnectionRefusedError, FileNotFoundError, socket.timeout, OSError):
            os.unlink(self.path)                  # nobody is listening: a leftover from a crashed process
        else:
            raise OSError(f"{self.path} is already served by a live process")
        finally:
            probe.close()

    def stop(self) -> None:
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        with self._lock:
            conns = list(self.connections)
        for conn in conns:
            try:
                conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def wait(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(0.5)

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def connection_count(self) -> int:
        with self._lock:
            return len(self.connections)

    # -- serving ------------------------------------------------------------------------------
    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                sock, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not uid_allowed(peer_uid(sock)):
                logger.warning("%s: refused a connection from uid %s", self.name, peer_uid(sock))
                sock.close()
                continue
            conn = Connection(sock, self)
            with self._lock:
                self.connections.add(conn)
            threading.Thread(target=self._serve, args=(conn,), name=f"{self.name}-conn", daemon=True).start()

    def _serve(self, conn: Connection) -> None:
        try:
            while not self._stop.is_set():
                try:
                    msg = protocol.recv(conn.sock)
                except protocol.ProtocolError as exc:
                    self._reply(conn, protocol.error(None, protocol.PARSE_ERROR, str(exc)))
                    return                       # framing is lost: drop the connection
                except OSError:
                    return
                if msg is None:
                    return
                self._dispatch(conn, msg)
        finally:
            with self._lock:
                self.connections.discard(conn)
            if self.on_disconnect is not None:
                try:
                    self.on_disconnect(conn)
                except Exception:  # pylint: disable=broad-except
                    logger.exception("%s: on_disconnect failed", self.name)
            try:
                conn.sock.close()
            except OSError:
                pass

    def _dispatch(self, conn: Connection, msg: dict[str, Any]) -> None:
        req_id = msg.get("id")
        try:
            req_id, method, params = protocol.parse_request(msg)
            handler = self.handlers.get(method)
            if handler is None:
                raise protocol.RpcError(protocol.METHOD_NOT_FOUND, f"unknown method {method!r}")
            reply = protocol.result(req_id, handler(conn, params))
        except protocol.RpcError as exc:
            reply = protocol.error(req_id, exc.code, exc.message, exc.data)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("%s: handler failed", self.name)
            reply = protocol.error(req_id, protocol.INTERNAL, f"{type(exc).__name__}: {str(exc)[:200]}")
        self._reply(conn, reply)

    @staticmethod
    def _reply(conn: Connection, reply: dict[str, Any]) -> None:
        try:
            protocol.send(conn.sock, reply)
        except (OSError, protocol.ProtocolError):
            pass
