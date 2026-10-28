# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Detection of installed agent CLIs (#87/#88): local only, bounded, never raises."""
from __future__ import annotations

import json
import os
import stat

import pytest

from intelligence.orchestrator import provider_status as ps


def _fake_bin(directory, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture(name="bindir")
def _bindir(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    monkeypatch.setenv("PATH", str(d))
    return d


def _by_name(rows):
    return {r.name: r for r in rows}


def test_nothing_installed(bindir):  # pylint: disable=unused-argument
    rows = _by_name(ps.detect_cli_agents())
    assert set(rows) == {"claude", "codex", "gemini"}
    assert not any(r.installed for r in rows.values())
    assert all(r.ready is None and r.version is None and r.path is None for r in rows.values())


def test_installed_reports_first_version_line(bindir):
    _fake_bin(bindir, "codex", 'echo "codex-cli 9.9.9"; echo "extra"')
    row = _by_name(ps.detect_cli_agents())["codex"]
    assert row.installed and row.version == "codex-cli 9.9.9" and row.kind == "cli"
    assert row.path == str(bindir / "codex")
    assert row.ready is None and row.enabled is False


def test_hung_binary_is_not_installed_and_is_bounded(bindir):
    _fake_bin(bindir, "gemini", "sleep 30")
    import time
    t0 = time.monotonic()
    row = _by_name(ps.detect_cli_agents(timeout=0.3))["gemini"]
    assert time.monotonic() - t0 < 5
    assert not row.installed and row.version is None


def test_failing_version_is_not_installed(bindir):
    _fake_bin(bindir, "claude", "exit 3")
    assert not _by_name(ps.detect_cli_agents())["claude"].installed


def test_terms_gate_flags():
    assert ps.CLI_AGENT_SPECS["claude"].terms_gated
    assert ps.CLI_AGENT_SPECS["gemini"].terms_gated
    assert not ps.CLI_AGENT_SPECS["codex"].terms_gated


def test_readiness_roundtrip_and_version_change_resets(bindir):
    _fake_bin(bindir, "codex", 'echo "codex-cli 1.0"')
    assert ps.record_readiness("codex", True, "codex-cli 1.0")
    assert _by_name(ps.detect_cli_agents())["codex"].ready is True
    _fake_bin(bindir, "codex", 'echo "codex-cli 2.0"')
    assert _by_name(ps.detect_cli_agents())["codex"].ready is None


def test_auth_failure_is_recorded_as_not_ready(bindir):
    _fake_bin(bindir, "codex", 'echo "codex-cli 1.0"')
    ps.record_readiness("codex", False, "codex-cli 1.0")
    assert _by_name(ps.detect_cli_agents())["codex"].ready is False


def test_record_readiness_rejects_unknown_agent():
    assert ps.record_readiness("not-an-agent", True) is False


def test_status_file_is_0600_and_holds_no_secrets(bindir):  # pylint: disable=unused-argument
    assert ps.record_readiness("claude", True, "1.0")
    path = ps.status_path()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    doc = json.loads(open(path, encoding="utf-8").read())
    assert set(doc["cli"]["claude"]) == {"ready", "version", "checked_at"}


@pytest.mark.parametrize("garbage", ["", "not json", "[]", '{"cli": 5}'])
def test_corrupt_status_file_is_ignored(bindir, garbage):  # pylint: disable=unused-argument
    os.makedirs(os.path.dirname(ps.status_path()), exist_ok=True)
    with open(ps.status_path(), "w", encoding="utf-8") as fh:
        fh.write(garbage)
    assert ps.load()["cli"] == {}
    assert not any(r.installed for r in ps.detect_cli_agents())


def test_enabled_flag_comes_from_config(bindir):
    from core.config.paths import get_path
    _fake_bin(bindir, "codex", 'echo "codex-cli 1.0"')
    with open(get_path("config.json"), "w", encoding="utf-8") as fh:
        json.dump({"cli_providers": {"codex": {"enabled": True}, "claude": {"enabled": False}}}, fh)
    rows = _by_name(ps.detect_cli_agents())
    assert rows["codex"].enabled is True and rows["claude"].enabled is False


def test_detection_makes_no_network_call(bindir, monkeypatch):
    import socket

    def boom(*_a, **_k):
        raise AssertionError("detection must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", boom)
    _fake_bin(bindir, "codex", 'echo "codex-cli 1.0"')
    assert _by_name(ps.detect_cli_agents())["codex"].installed


def test_agents_list_json_cli(bindir, capsys):
    import interface.cli.main as cli
    _fake_bin(bindir, "codex", 'echo "codex-cli 1.0"')

    class _Args:  # pylint: disable=too-few-public-methods
        agents_command = "list"
        json = True

    assert cli._cmd_agents(_Args()) == 0  # pylint: disable=protected-access
    rows = {r["name"]: r for r in json.loads(capsys.readouterr().out)}
    assert rows["codex"]["installed"] is True and rows["claude"]["installed"] is False


def test_agents_list_text_cli(bindir, capsys):  # pylint: disable=unused-argument
    import interface.cli.main as cli

    class _Args:  # pylint: disable=too-few-public-methods
        agents_command = None
        json = False

    assert cli._cmd_agents(_Args()) == 0  # pylint: disable=protected-access
    out = capsys.readouterr().out
    assert "AGENT" in out and "No agent CLI found on PATH." in out
