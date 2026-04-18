# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Tests for cli/env_wizard.py — .env setup wizard."""
from cli.env_wizard import EnvWizard, _mask, _read_dotenv, _set_dotenv_key


# ── _mask helper ──────────────────────────────────────────────────────────────

def test_mask_short_value():
    assert _mask("abc") == "****"


def test_mask_long_value():
    masked = _mask("sk-ant-abcdefghij1234567890")
    assert "***" in masked
    assert "sk-a" in masked
    assert "7890" in masked


# ── detect_missing ────────────────────────────────────────────────────────────

def test_detect_missing_when_all_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Clear env
    for key in ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "GROK_API_KEY"]:
        monkeypatch.delenv(key, raising=False)

    wizard = EnvWizard(project_dir=str(tmp_path), non_interactive=True)
    missing = wizard.detect_missing(["ANTHROPIC_API_KEY", "GEMINI_API_KEY"])
    assert "ANTHROPIC_API_KEY" in missing
    assert "GEMINI_API_KEY" in missing


def test_detect_missing_respects_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Write a .env file
    (tmp_path / ".env").write_text('ANTHROPIC_API_KEY="sk-ant-test"\n')
    wizard = EnvWizard(project_dir=str(tmp_path), non_interactive=True)
    missing = wizard.detect_missing(["ANTHROPIC_API_KEY"])
    assert "ANTHROPIC_API_KEY" not in missing


def test_detect_missing_respects_os_environ(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    wizard = EnvWizard(project_dir=str(tmp_path), non_interactive=True)
    missing = wizard.detect_missing(["ANTHROPIC_API_KEY"])
    assert "ANTHROPIC_API_KEY" not in missing


# ── _set_dotenv_key / _read_dotenv ────────────────────────────────────────────

def test_set_and_read_dotenv_key(tmp_path):
    _set_dotenv_key("MY_KEY", "my_value", project_dir=str(tmp_path))
    env = _read_dotenv(str(tmp_path))
    assert env["MY_KEY"] == "my_value"


def test_set_dotenv_key_overwrites_existing(tmp_path):
    _set_dotenv_key("MY_KEY", "first", project_dir=str(tmp_path))
    _set_dotenv_key("MY_KEY", "second", project_dir=str(tmp_path))
    env = _read_dotenv(str(tmp_path))
    assert env["MY_KEY"] == "second"


# ── guided_flow writes key ────────────────────────────────────────────────────

def test_guided_flow_writes_key(tmp_path, monkeypatch):
    inputs = iter(["sk-ant-fakefakefake"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(inputs))

    wizard = EnvWizard(project_dir=str(tmp_path), non_interactive=False)
    wizard.guided_flow(["ANTHROPIC_API_KEY"])

    env = _read_dotenv(str(tmp_path))
    assert env.get("ANTHROPIC_API_KEY") == "sk-ant-fakefakefake"


# ── non-interactive mode skips wizard ─────────────────────────────────────────

def test_non_interactive_skips(tmp_path, monkeypatch, capsys):
    for key in ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "GROK_API_KEY"]:
        monkeypatch.delenv(key, raising=False)

    wizard = EnvWizard(project_dir=str(tmp_path), non_interactive=True)
    # run() must not call input() — would raise StopIteration if it did
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(AssertionError("input() called in non-interactive mode")))
    wizard.run(skip_verify=True)
    out = capsys.readouterr().out
    # Should have printed at least the status header
    assert "API keys" in out or "Setup complete" in out or "configured" in out


# ── verify_keys mocking ───────────────────────────────────────────────────────

def test_verify_keys_calls_probe(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('ANTHROPIC_API_KEY="sk-ant-test"\n')
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    called_with = []

    def mock_probe(api_key, timeout=10.0):
        called_with.append(api_key)
        return {"ok": True, "latency_ms": 100.0, "error": ""}

    import cli.key_probes as kp
    monkeypatch.setattr(kp, "PROVIDER_PROBES", {
        "ANTHROPIC_API_KEY": ("anthropic", mock_probe),
    })

    wizard = EnvWizard(project_dir=str(tmp_path), non_interactive=True)
    results = wizard.verify_keys(["ANTHROPIC_API_KEY"], skip_verify=False)

    assert "ANTHROPIC_API_KEY" in results
    assert results["ANTHROPIC_API_KEY"]["ok"] is True
    assert called_with == ["sk-ant-test"]


def test_verify_keys_skipped_with_flag(tmp_path):
    wizard = EnvWizard(project_dir=str(tmp_path), non_interactive=True)
    results = wizard.verify_keys(["ANTHROPIC_API_KEY"], skip_verify=True)
    assert results == {}


# ── keys never appear in log output ──────────────────────────────────────────

def test_key_masked_in_guided_flow(tmp_path, monkeypatch, capfd):
    """API key value must not appear literally in stdout/stderr."""
    secret = "sk-ant-supersecretkey1234"
    monkeypatch.setattr("getpass.getpass", lambda _: secret)

    wizard = EnvWizard(project_dir=str(tmp_path), non_interactive=False)
    wizard.guided_flow(["ANTHROPIC_API_KEY"])

    captured = capfd.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
