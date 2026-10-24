# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Length-prefixed JSON-RPC 2.0 between a client and the supervisor/worker (ADR 003 §2).

Frame = 4-byte big-endian length + UTF-8 JSON. Frames above ``MAX_FRAME`` are refused *before* allocating, so a
confused or hostile peer cannot make us read gigabytes. Anything that is not a well-formed request object is
answered with a JSON-RPC error instead of an exception.
"""
from __future__ import annotations

import json
import socket
import struct
from typing import Any

MAX_FRAME = 8 * 1024 * 1024
HEADER = struct.Struct(">I")

# JSON-RPC error codes (the standard ones, plus a small server range of ours)
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = -32700, -32600, -32601, -32602, -32603
UNKNOWN_REPO, TOO_MANY_WORKERS, TOOL_ERROR, VERSION_MISMATCH, SHUTTING_DOWN = -32001, -32002, -32003, -32004, -32005


class ProtocolError(Exception):
    """The peer sent something that is not a valid frame; the connection should be dropped."""


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            if not buf:
                return None                       # clean EOF between frames
            raise ProtocolError("connection closed mid-frame")
        buf.extend(chunk)
    return bytes(buf)


def send(sock: socket.socket, message: dict[str, Any]) -> None:
    body = json.dumps(message, separators=(",", ":"), default=str).encode("utf-8")
    if len(body) > MAX_FRAME:
        raise ProtocolError(f"message of {len(body)} bytes exceeds the {MAX_FRAME}-byte frame limit")
    sock.sendall(HEADER.pack(len(body)) + body)


def recv(sock: socket.socket) -> dict[str, Any] | None:
    """The next message, or ``None`` on a clean close. Raises ``ProtocolError`` for anything malformed."""
    head = _recv_exact(sock, HEADER.size)
    if head is None:
        return None
    (length,) = HEADER.unpack(head)
    if length > MAX_FRAME:
        raise ProtocolError(f"frame of {length} bytes exceeds the {MAX_FRAME}-byte limit")
    body = _recv_exact(sock, length) if length else b""
    if body is None:
        raise ProtocolError("connection closed mid-frame")
    try:
        msg = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError(f"frame is not valid JSON: {exc}") from exc
    if not isinstance(msg, dict):
        raise ProtocolError("frame is not a JSON object")
    return msg


def request(method: str, params: dict[str, Any] | None = None, req_id: int = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}


def result(req_id: Any, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": value}


def error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def parse_request(msg: dict[str, Any]) -> tuple[Any, str, dict[str, Any]]:
    """``(id, method, params)`` of a valid request; raises ``RpcError(INVALID_REQUEST)`` otherwise."""
    if msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        raise RpcError(INVALID_REQUEST, "not a JSON-RPC 2.0 request")
    params = msg.get("params", {})
    if not isinstance(params, dict):
        raise RpcError(INVALID_PARAMS, "params must be an object")
    return msg.get("id"), msg["method"], params


def call(sock: socket.socket, method: str, params: dict[str, Any] | None = None, req_id: int = 1) -> Any:
    """One request/response on an open socket. Raises ``RpcError`` for an error reply, ``ProtocolError`` otherwise."""
    send(sock, request(method, params, req_id))
    reply = recv(sock)
    if reply is None:
        raise ProtocolError("connection closed before a reply")
    if reply.get("id") != req_id:
        raise ProtocolError("reply does not match the request")
    if "error" in reply:
        err = reply["error"] if isinstance(reply["error"], dict) else {}
        raise RpcError(int(err.get("code", INTERNAL)), str(err.get("message", "error")), err.get("data"))
    return reply.get("result")
