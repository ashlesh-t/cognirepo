# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for cli/key_probes.py — API key verification probes."""
import urllib.error
import urllib.request

import pytest

from cli.key_probes import (
    probe_anthropic,
    probe_gemini,
    probe_openai,
    probe_grok,
    PROVIDER_PROBES,
)


def _mock_urlopen_401(url_or_req, timeout=None):
    raise urllib.error.HTTPError(
        url="https://example.com", code=401,
        msg="Unauthorized", hdrs=None, fp=None,  # type: ignore[arg-type]
    )


def _mock_urlopen_ok(url_or_req, timeout=None):
    class _FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def read(self):
            return b"{}"
    return _FakeResp()


# ── probe_anthropic ───────────────────────────────────────────────────────────

def test_probe_anthropic_401_returns_not_ok(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _mock_urlopen_401)
    result = probe_anthropic("sk-ant-bad", timeout=1.0)
    assert result["ok"] is False
    assert "401" in result["error"]


def test_probe_anthropic_ok(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _mock_urlopen_ok)
    result = probe_anthropic("sk-ant-good", timeout=1.0)
    assert result["ok"] is True
    assert result["latency_ms"] >= 0


# ── probe_gemini ──────────────────────────────────────────────────────────────

def test_probe_gemini_401(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _mock_urlopen_401)
    result = probe_gemini("bad-key", timeout=1.0)
    assert result["ok"] is False


def test_probe_gemini_ok(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _mock_urlopen_ok)
    result = probe_gemini("good-key", timeout=1.0)
    assert result["ok"] is True


# ── probe_openai / probe_grok ─────────────────────────────────────────────────

def test_probe_openai_401(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _mock_urlopen_401)
    result = probe_openai("bad-key", timeout=1.0)
    assert result["ok"] is False


def test_probe_grok_401(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _mock_urlopen_401)
    result = probe_grok("bad-key", timeout=1.0)
    assert result["ok"] is False


# ── PROVIDER_PROBES registry ──────────────────────────────────────────────────

def test_provider_probes_registry_has_all_keys():
    expected = {"ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "GROK_API_KEY"}
    assert set(PROVIDER_PROBES.keys()) == expected


def test_provider_probes_all_callable():
    for key, (name, fn) in PROVIDER_PROBES.items():
        assert callable(fn), f"{key}: probe function must be callable"
        assert isinstance(name, str)
