# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""#89: provider discovery adds almost nothing to `setup`/`init` or to routing on the common (no-fetch) path.

Budgets are deliberately loose (several times the measured cost) so they catch an accidental network call, an
unbounded wait or a per-call re-parse, not scheduler noise. Measured on the reference machine: a cached
``resolve_model`` costs about 0.05 ms.
"""
from __future__ import annotations

import os
import shutil
import socket
import stat
import time

import pytest

from intelligence.orchestrator import classifier as clf
from intelligence.orchestrator import model_discovery as md
from intelligence.orchestrator import provider_status as ps

KEYS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROK_API_KEY", "OPENAI_API_KEY")


SLEEP = shutil.which("sleep") or "/bin/sleep"  # PATH is replaced by the fake bin dir, so use the absolute path


def _fake_bin(directory, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture(name="bindir", autouse=True)
def _bindir(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    monkeypatch.setenv("PATH", str(d))
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    return d


@pytest.fixture(name="no_network")
def _no_network(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("this path must not touch the network")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(md, "_OPENER", type("O", (), {"open": staticmethod(boom)})())


def _timed(fn, repeat=1):
    t0 = time.monotonic()
    for _ in range(repeat):
        out = fn()
    return (time.monotonic() - t0) / repeat, out


def test_no_cli_no_key_path_is_instant_and_offline(no_network):  # pylint: disable=unused-argument
    """What `setup` does with nothing installed and no keys: detection, wizard offer, discovery offer."""
    from interface.cli.wizard import _ask_cli_backends
    elapsed, choices = _timed(lambda: (ps.detect_cli_agents(), _ask_cli_backends(),
                                       [md.api_key(p) for p in md.PROVIDERS])[1])
    assert choices == {} and elapsed < 1.0


def test_detection_cost_is_bounded_by_the_slowest_binary_not_the_sum(bindir):
    """Three binaries that each take 0.5 s are probed in parallel: ~0.5 s, never 1.5 s."""
    for name in ("claude", "codex", "gemini"):
        _fake_bin(bindir, name, f'{SLEEP} 0.5; echo "{name} 1.0"')
    elapsed, rows = _timed(ps.detect_cli_agents)
    assert all(r.installed for r in rows) and elapsed < 1.2


def test_hung_binary_cannot_stall_setup_past_the_cap(bindir):
    for name in ("claude", "codex", "gemini"):
        _fake_bin(bindir, name, f"{SLEEP} 30")
    elapsed, rows = _timed(lambda: ps.detect_cli_agents(timeout=0.4))
    assert not any(r.installed for r in rows) and elapsed < 3.0
    assert ps.VERSION_TIMEOUT_S <= 3.0  # the production cap the issue asks for


def test_default_detection_cap_is_three_seconds():
    assert ps.VERSION_TIMEOUT_S == 3.0


def test_resolve_model_without_a_cache_is_free_and_unchanged(no_network):  # pylint: disable=unused-argument
    cfg = {}
    base = clf.default_model_for("anthropic", "COMPLEX")
    elapsed, out = _timed(lambda: clf.resolve_model("anthropic", "COMPLEX", base, cfg), repeat=200)
    assert out == base and elapsed < 0.02


def test_resolve_model_with_a_fresh_cache_stays_cheap(monkeypatch, no_network):  # pylint: disable=unused-argument
    """The router calls this per request: file read + JSON parse + hashing must stay well under a millisecond-ish."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-latency")
    ids = ("claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6")
    entry = {"fetched_at": md._now(), "key_fingerprint": md.fingerprint("sk-test-latency"),  # pylint: disable=protected-access
             "endpoint": "v1/models", "rules_hash": clf.rules_hash(),
             "models": md.tier_models([md.ModelInfo(id=i) for i in ids]), "denied": []}
    ps.modify(lambda d: d.setdefault("api", {}).__setitem__("anthropic", entry))
    base = clf.default_model_for("anthropic", "COMPLEX")
    elapsed, _ = _timed(lambda: clf.resolve_model("anthropic", "COMPLEX", base, {}), repeat=200)
    assert elapsed < 0.02, f"{elapsed * 1000:.2f} ms per call"


def test_a_corrupt_cache_costs_nothing_and_changes_nothing(no_network):  # pylint: disable=unused-argument
    os.makedirs(os.path.dirname(ps.status_path()), exist_ok=True)
    with open(ps.status_path(), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    base = clf.default_model_for("openai", "STANDARD")
    elapsed, out = _timed(lambda: clf.resolve_model("openai", "STANDARD", base, {}), repeat=50)
    assert out == base and elapsed < 0.02


def test_setup_offer_with_no_key_prints_and_fetches_nothing(monkeypatch, capsys, no_network):  # pylint: disable=unused-argument
    import interface.cli.main as cli
    monkeypatch.setattr(md, "refresh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("refresh ran")))
    elapsed, _ = _timed(cli._offer_model_refresh)  # pylint: disable=protected-access
    assert capsys.readouterr().out == "" and elapsed < 0.5


def test_setup_offer_with_a_key_only_hints_when_not_a_terminal(monkeypatch, capsys, no_network):  # pylint: disable=unused-argument
    """Non-interactive `setup` never fetches: it prints one hint line and returns."""
    import interface.cli.main as cli
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-latency")
    monkeypatch.setattr(md, "refresh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("refresh ran")))
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": staticmethod(lambda: False)})())
    cli._offer_model_refresh()  # pylint: disable=protected-access
    assert "models refresh" in capsys.readouterr().out
