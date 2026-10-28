# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""cli_adapter (#87/#88): isolation recipe, env hygiene, error mapping, recursion guard. Fake binaries only."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.config import headless
from intelligence.orchestrator.model_adapters import cli_adapter as ca
from intelligence.orchestrator.model_adapters.errors import ModelCallError

REPO = Path(__file__).resolve().parents[1]

CLAUDE_OK = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "hello",
                        "usage": {"input_tokens": 2, "cache_creation_input_tokens": 3, "cache_read_input_tokens": 5,
                                  "output_tokens": 7}, "modelUsage": {"claude-haiku-x": {}}})
CODEX_OK = "\n".join([
    '{"type":"thread.started","thread_id":"t"}',
    '{"type":"item.completed","item":{"id":"i","type":"agent_message","text":"hello"}}',
    '{"type":"turn.completed","usage":{"input_tokens":11,"output_tokens":3}}'])
GEMINI_OK = json.dumps({"response": "hello", "stats": {}})
OK_BODY = {"claude": CLAUDE_OK, "codex": CODEX_OK, "gemini": GEMINI_OK}


def _fake(bindir: Path, name: str, stdout: str = "", exit_code: int = 0, stderr: str = "", extra: str = "") -> Path:
    """A stand-in CLI that logs argv / env / cwd / stdin next to itself, then prints canned output."""
    (bindir / f"{name}.out").write_text(stdout, encoding="utf-8")
    (bindir / f"{name}.err").write_text(stderr, encoding="utf-8")
    script = bindir / name
    script.write_text(
        '#!/bin/sh\nd="$(dirname "$0")"\n'
        f'printf "%s\\n" "$@" > "$d/{name}.argv"\nenv > "$d/{name}.env"\npwd > "$d/{name}.pwd"\n'
        f'cat > "$d/{name}.stdin"\n{extra}\ncat "$d/{name}.out"\ncat "$d/{name}.err" >&2\nexit {exit_code}\n',
        encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


@pytest.fixture(name="bindir")
def _bindir(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.delenv("COGNIREPO_HEADLESS", raising=False)
    return d


def _argv(bindir: Path, name: str) -> list[str]:
    return (bindir / f"{name}.argv").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("agent", ["claude", "codex", "gemini"])
def test_success_per_agent(bindir, agent):
    _fake(bindir, agent, OK_BODY[agent])
    r = ca.call("q?", agent=agent)
    assert r.text == "hello" and r.provider == f"{agent}-cli"
    assert r.usage["output_tokens"] >= 1


def test_claude_usage_and_model_from_output(bindir):
    _fake(bindir, "claude", CLAUDE_OK)
    r = ca.call("q?", agent="claude", model_id="haiku")
    assert r.model == "claude-haiku-x"
    assert r.usage == {"input_tokens": 10, "output_tokens": 7, "estimated": False}


def test_codex_usage(bindir):
    _fake(bindir, "codex", CODEX_OK)
    assert ca.call("q?", agent="codex").usage == {"input_tokens": 11, "output_tokens": 3, "estimated": False}


def test_unstructured_output_falls_back_to_text_and_estimates_tokens(bindir):
    _fake(bindir, "claude", "plain text answer")
    r = ca.call("q?", agent="claude")
    assert r.text == "plain text answer" and r.usage["estimated"] is True


@pytest.mark.parametrize("agent", ["claude", "codex", "gemini"])
def test_argv_has_isolation_flags_and_no_forbidden_flags(bindir, agent):
    _fake(bindir, agent, OK_BODY[agent])
    ca.call("q?", agent=agent)
    argv = _argv(bindir, agent)
    for forbidden in ca.FORBIDDEN_FLAGS:
        assert forbidden not in argv
    assert not any(a.startswith("--dangerously") for a in argv)
    if agent == "claude":
        assert {"-p", "--tools", "--strict-mcp-config", "--disable-slash-commands",
                "--no-session-persistence", "--setting-sources"} <= set(argv)
        assert argv[argv.index("--tools") + 1] == ""
    if agent == "codex":
        assert {"exec", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check"} <= set(argv)
        assert argv[argv.index("-s") + 1] == "read-only" and argv[-1] == "-"
    if agent == "gemini":
        assert argv[argv.index("--approval-mode") + 1] == "plan"
        assert "--allowed-mcp-server-names" in argv


def test_model_flag_only_when_given(bindir):
    _fake(bindir, "claude", CLAUDE_OK)
    ca.call("q?", agent="claude")
    assert "--model" not in _argv(bindir, "claude")
    ca.call("q?", agent="claude", model_id="sonnet")
    argv = _argv(bindir, "claude")
    assert argv[argv.index("--model") + 1] == "sonnet"


@pytest.mark.parametrize("bad", ["--yolo", "-x", "a b", "a;b", "$(id)", " "])
def test_model_id_cannot_inject_flags(bindir, bad):
    _fake(bindir, "claude", CLAUDE_OK)
    with pytest.raises(ModelCallError) as ei:
        ca.call("q?", agent="claude", model_id=bad)
    assert ei.value.status_code == 400
    assert not (bindir / "claude.argv").exists()  # rejected before the CLI was started


def test_empty_model_id_means_cli_default(bindir):
    _fake(bindir, "claude", CLAUDE_OK)
    assert ca.call("q?", agent="claude", model_id="").text == "hello"
    assert "--model" not in _argv(bindir, "claude")


def test_prompt_goes_over_stdin_not_argv(bindir):
    _fake(bindir, "codex", CODEX_OK)
    ca.call("the question", system_prompt="ctx-block", agent="codex",
            messages_history=[{"role": "user", "content": "earlier"}])
    stdin = (bindir / "codex.stdin").read_text(encoding="utf-8")
    assert "ctx-block" in stdin and "earlier" in stdin and stdin.rstrip().endswith("the question")
    assert not any("the question" in a or "ctx-block" in a for a in _argv(bindir, "codex"))


def test_child_env_is_allowlisted_and_has_no_api_keys(bindir, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROK_API_KEY",
                "SOME_SECRET_TOKEN"):
        monkeypatch.setenv(var, "sk-secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy:1")
    monkeypatch.setenv("CODEX_HOME", "/somewhere")
    _fake(bindir, "claude", CLAUDE_OK)
    ca.call("q?", agent="claude")
    env = dict(line.split("=", 1) for line in (bindir / "claude.env").read_text(encoding="utf-8").splitlines() if "=" in line)
    assert "sk-secret" not in "".join(env.values())
    assert not {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROK_API_KEY",
                "SOME_SECRET_TOKEN"} & set(env)
    assert env["COGNIREPO_HEADLESS"] == "1"
    assert env["HTTPS_PROXY"] == "http://proxy:1" and env["CODEX_HOME"] == "/somewhere"


def test_runs_in_neutral_empty_cwd_not_the_repo(bindir, monkeypatch):
    monkeypatch.chdir(REPO)
    _fake(bindir, "claude", CLAUDE_OK)
    ca.call("q?", agent="claude")
    cwd = Path((bindir / "claude.pwd").read_text(encoding="utf-8").strip())
    assert cwd.name == "cli-sandbox" and cwd != REPO and not any(cwd.iterdir())


def test_timeout_kills_process_group_and_is_retryable(bindir):
    _fake(bindir, "claude", CLAUDE_OK, extra="sleep 30 &\nsleep 30")
    t0 = time.monotonic()
    with pytest.raises(ModelCallError) as ei:
        ca.call("q?", agent="claude", timeout=0.5)
    assert time.monotonic() - t0 < 10
    assert ei.value.status_code is None and ei.value.is_retryable


@pytest.mark.parametrize("stderr,code", [("Error: Not logged in. Please run /login", 401),
                                         ("Unauthorized", 401),
                                         ("Opening authentication page in your browser", 401),
                                         ("429 rate limit exceeded", 429),
                                         ("You have hit your usage limit", 429),
                                         ("segfault", 500)])
def test_nonzero_exit_is_mapped(bindir, stderr, code):
    _fake(bindir, "codex", "", exit_code=1, stderr=stderr)
    with pytest.raises(ModelCallError) as ei:
        ca.call("q?", agent="codex")
    assert ei.value.status_code == code and ei.value.provider == "codex-cli"


def test_auth_prompt_with_exit_zero_and_unparseable_output_is_401(bindir):
    _fake(bindir, "gemini", "Opening authentication page in your browser. Do you want to continue? [Y/n]")
    with pytest.raises(ModelCallError) as ei:
        ca.call("q?", agent="gemini")
    assert ei.value.status_code == 401


def test_empty_output_is_an_error(bindir):
    _fake(bindir, "claude", "")
    with pytest.raises(ModelCallError) as ei:
        ca.call("q?", agent="claude")
    assert ei.value.status_code == 500


def test_missing_binary_is_404(bindir):  # pylint: disable=unused-argument
    with pytest.raises(ModelCallError) as ei:
        ca.call("q?", agent="codex")
    assert ei.value.status_code == 404 and not ei.value.is_retryable


def test_unsupported_agent(bindir):  # pylint: disable=unused-argument
    with pytest.raises(ModelCallError) as ei:
        ca.call("q?", agent="nope")
    assert ei.value.status_code == 400


def test_refuses_nested_headless_call(bindir, monkeypatch):
    _fake(bindir, "claude", CLAUDE_OK)
    monkeypatch.setenv("COGNIREPO_HEADLESS", "1")
    with pytest.raises(ModelCallError) as ei:
        ca.call("q?", agent="claude")
    assert ei.value.status_code == 400
    assert not (bindir / "claude.argv").exists()  # the CLI was never started


def test_stream_yields_one_chunk_and_returns_usage(bindir):
    _fake(bindir, "claude", CLAUDE_OK)
    gen = ca.call("q?", agent="claude", stream=True)
    assert next(gen) == "hello"
    with pytest.raises(StopIteration) as stop:
        next(gen)
    assert stop.value.value == {"input_tokens": 10, "output_tokens": 7}


def test_tool_manifest_is_ignored(bindir):
    _fake(bindir, "claude", CLAUDE_OK)
    ca.call("q?", tool_manifest=[{"name": "t"}], agent="claude")
    assert "t" not in _argv(bindir, "claude")


def test_timeout_comes_from_config():
    from core.config.paths import get_path
    with open(get_path("config.json"), "w", encoding="utf-8") as fh:
        json.dump({"cli_timeout_s": 7}, fh)
    assert ca._configured_timeout() == 7.0  # pylint: disable=protected-access
    with open(get_path("config.json"), "w", encoding="utf-8") as fh:
        json.dump({"cli_timeout_s": -3}, fh)
    assert ca._configured_timeout() == ca.DEFAULT_TIMEOUT_S  # pylint: disable=protected-access


# ── recursion guard ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [("1", True), ("true", True), ("yes", True), ("", False),
                                            ("0", False), ("false", False), ("off", False)])
def test_is_headless(monkeypatch, value, expected):
    monkeypatch.setenv("COGNIREPO_HEADLESS", value)
    assert headless.is_headless() is expected


def test_is_headless_unset(monkeypatch):
    monkeypatch.delenv("COGNIREPO_HEADLESS", raising=False)
    assert headless.is_headless() is False


def test_behaviour_hook_is_a_noop_when_headless(monkeypatch):
    import io
    from interface.tools import behaviour_hook
    monkeypatch.setenv("COGNIREPO_HEADLESS", "1")
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"prompt": "hi"}'))
    called = []
    monkeypatch.setattr(behaviour_hook, "_record_query", lambda *a, **k: called.append(a))
    assert behaviour_hook.main() == 0 and not called


def test_run_server_returns_without_starting_when_headless(monkeypatch):
    from interface.server import mcp_server
    monkeypatch.setenv("COGNIREPO_HEADLESS", "1")

    def boom(*_a, **_k):
        raise AssertionError("must not start")

    monkeypatch.setattr(mcp_server, "_prepare_runtime", boom)
    assert mcp_server.run_server() is None


def test_cli_serve_exits_zero_without_serving_when_headless():
    proc = subprocess.run(
        [sys.executable, "-m", "interface.cli.main", "serve"], cwd=REPO, capture_output=True, text=True, timeout=60,
        env={**os.environ, "COGNIREPO_HEADLESS": "1"}, check=False)
    assert proc.returncode == 0 and "COGNIREPO_HEADLESS" in proc.stderr


def test_aliases_live_in_classifier_and_cover_three_tiers():
    from intelligence.orchestrator.classifier import CLI_TIER_ALIASES
    assert set(CLI_TIER_ALIASES["claude"]) == {"STANDARD", "COMPLEX", "EXPERT"}


# ── real binaries: opt-in only (spends a few tokens of the developer's own subscription) ───────────

@pytest.mark.skipif(os.environ.get("COGNIREPO_REAL_CLI_TESTS") != "1", reason="set COGNIREPO_REAL_CLI_TESTS=1")
@pytest.mark.parametrize("agent,model", [("claude", "haiku"), ("codex", "")])
def test_real_cli_round_trip(agent, model):
    if not shutil.which(agent):
        pytest.skip(f"{agent} not installed")
    r = ca.call("Reply with the single word OK.", agent=agent, model_id=model, timeout=120)
    assert "ok" in r.text.lower()
