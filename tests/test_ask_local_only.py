# pylint: disable=unused-argument, redefined-outer-name, protected-access, import-outside-toplevel
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_ask_local_only.py — #269 (COG-5) and the exit-code half of #275 (COG-11).

Product decision: CogniRepo supplies context to the AI agent the user already runs; it does not call a model.
``cognirepo ask`` therefore answers from the local index only. It used to be documented as routing to a model
(README, CLI_REFERENCE) while the code never did, and a piped-stdin branch that did was unreachable.

* ``ask`` never reaches the model router, whatever keys or agent CLIs exist.
* An answer exits 0; "no local answer" exits 1 with the reason on stderr; no question is a usage error (2).
* The commands that only configure or test a model call say they are deprecated, on stderr, so that
  ``--json`` and other machine-readable stdout stay intact.
"""
from __future__ import annotations

import inspect
import json
import sys

import pytest

from core.config.paths import get_path


@pytest.fixture()
def no_model(monkeypatch):
    """Make any attempt to reach a model fail the test, and give the CLI keys it could be tempted to use."""
    from intelligence.orchestrator import router

    def _boom(*_a, **_k):
        raise AssertionError("`cognirepo ask` must not call a model")

    monkeypatch.setattr(router, "route", _boom)
    monkeypatch.setattr(router, "stream_route", _boom)
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROK_API_KEY"):
        monkeypatch.setenv(var, "sk-would-be-used-before")


@pytest.fixture()
def resolver(monkeypatch):
    """Control what the local resolver answers (the real one needs a built index)."""
    from intelligence.orchestrator import router

    def _set(answer):
        monkeypatch.setattr(router, "try_local_resolve", lambda _q, _bundle: answer)
    return _set


def _initialised_repo() -> None:
    with open(get_path("config.json"), "w", encoding="utf-8") as f:  # get_path creates the parent directory
        json.dump({"schema_version": 1, "project_id": "p-269", "storage": {"encrypt": False}}, f)


def _cli(monkeypatch, *argv: str) -> int:
    """Run the real entry point in-process; returns the process exit code (a normal return is 0)."""
    from interface.cli.main import main
    monkeypatch.setattr(sys, "argv", ["cognirepo", *argv])
    try:
        main()
    except SystemExit as exit_info:
        return 0 if exit_info.code is None else exit_info.code
    return 0


# ── ask answers from the local index and never reaches a model ────────────────

def test_a_local_answer_is_printed_and_exits_zero(no_model, resolver, monkeypatch, capsys):
    _initialised_repo()
    resolver("42 files indexed")

    from interface.cli.main import _cmd_ask_local
    _cmd_ask_local("list files")  # returns; no SystemExit

    out = capsys.readouterr()
    assert out.out == "42 files indexed\n"
    assert out.err == ""


def test_ask_through_the_real_entry_point_exits_zero_and_never_calls_a_model(no_model, resolver, monkeypatch, capsys):
    _initialised_repo()
    resolver("answer from the index")

    code = _cli(monkeypatch, "ask", "where is context_pack?")

    out = capsys.readouterr()
    assert code == 0
    assert "answer from the index" in out.out
    assert "deprecated" not in out.err, "ask itself is not deprecated"


def test_no_local_answer_exits_one_and_explains_on_stderr(no_model, resolver, monkeypatch, capsys):
    """#275: this used to print a model-install hint and exit 0, so a script could not tell it from an answer."""
    _initialised_repo()
    resolver(None)

    code = _cli(monkeypatch, "ask", "why is auth slow and what should we refactor across modules")

    out = capsys.readouterr()
    assert code == 1
    assert out.out == "", "nothing on stdout: there was no answer"
    assert "No local answer" in out.err and "never calls a model" in out.err
    assert "context_pack" in out.err, "it must point at what can answer"
    for stale in ("pip install", "API_KEY", "agents enable", "cognirepo[providers]"):
        assert stale not in out.err, f"{stale!r} sends the user to configure a model that ask no longer uses"


def test_ask_without_a_question_is_a_usage_error(no_model, monkeypatch, capsys):
    _initialised_repo()

    code = _cli(monkeypatch, "ask")

    out = capsys.readouterr()
    assert code == 2
    assert out.out == "" and "Usage: cognirepo ask" in out.err


def test_verbose_shows_the_tier_and_score_but_no_model(no_model, resolver, capsys):
    _initialised_repo()
    resolver("ok")

    from interface.cli.main import _cmd_ask_local
    _cmd_ask_local("where is the thing defined", verbose=True)

    out = capsys.readouterr().out
    assert "tier=" in out and "score=" in out
    assert "model=" not in out, "a model id means nothing for a local-only command"


def test_the_dead_model_path_is_gone(no_model):
    """Re-wiring `ask` to a model is a product decision, not a refactor: this fails loudly if it comes back."""
    import interface.cli.main as cli

    assert not hasattr(cli, "_direct_ask")
    source = inspect.getsource(cli)
    assert "import route" not in source and "import stream_route" not in source, (
        "interface/cli/main.py must not import the model router; see #269")


# ── the commands that only configure a model call say they are deprecated ─────

def test_agents_list_json_stays_machine_readable_and_the_notice_goes_to_stderr(monkeypatch, capsys):
    _initialised_repo()
    from intelligence.orchestrator import provider_status
    monkeypatch.setattr(provider_status, "detect_cli_agents", lambda *a, **k: [])

    code = _cli(monkeypatch, "agents", "list", "--json")

    out = capsys.readouterr()
    assert code == 0
    assert json.loads(out.out) == [], "the notice must not corrupt --json output"
    assert "`cognirepo agents` is deprecated since 2.6.0" in out.err
    assert "cognirepo ask" in out.err, "say what replaced it"


@pytest.mark.parametrize("command", [["models", "list"], ["test-connection"]])
def test_the_other_model_commands_print_the_notice_too(monkeypatch, capsys, command):
    _initialised_repo()
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROK_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    _cli(monkeypatch, *command)  # test-connection exits 1 with no key; only the notice matters here

    assert f"`cognirepo {command[0]}` is deprecated" in capsys.readouterr().err


def test_setup_env_prints_the_notice(monkeypatch, capsys):
    from interface.cli import env_wizard

    monkeypatch.setattr(env_wizard.EnvWizard, "run", lambda self, skip_verify=False: None)

    code = _cli(monkeypatch, "setup-env", "--non-interactive")

    assert code == 0
    assert "`cognirepo setup-env` is deprecated" in capsys.readouterr().err


def test_commands_that_are_not_deprecated_stay_quiet(no_model, resolver, monkeypatch, capsys):
    _initialised_repo()
    resolver("x")

    _cli(monkeypatch, "ask", "list files")
    _cli(monkeypatch, "sessions")

    assert "deprecated" not in capsys.readouterr().err


# ── sessions: still there (the MCP server records them), but no longer say ask starts one ──

def test_sessions_empty_message_does_not_point_at_ask(capsys):
    from interface.cli.main import _cmd_sessions

    _cmd_sessions()

    out = capsys.readouterr().out
    assert "No sessions found" in out
    assert "cognirepo ask" not in out
    assert "MCP" in out


# ── setup and summarize no longer talk about model keys ──────────────────────

def test_setup_no_longer_nudges_towards_models_or_agent_cli_backends():
    import interface.cli.init_project as init_project
    import interface.cli.main as cli

    assert not hasattr(cli, "_offer_model_refresh"), "nothing uses model lists, so setup must not offer a refresh"
    for module in (cli, init_project):
        assert "apply_choices" not in inspect.getsource(module), "setup must not enable agent-CLI backends"


def test_summarize_is_described_as_local(capsys):
    from interface.cli.main import _print_help

    _print_help()

    row = next(line for line in capsys.readouterr().out.splitlines() if "summarize" in line)
    assert "local" in row and "LLM" not in row


def test_no_setup_text_says_summarize_needs_an_api_key():
    """``summarize`` is built from the AST index (`summarizer.py`: no LLM, no key); these strings said otherwise."""
    import interface.cli.init_project as init_project
    import interface.cli.main as cli

    for module in (cli, init_project):
        source = inspect.getsource(module)
        for stale in ("requires an API key", "needs API key", "LLM API key", "via LLM"):
            assert stale not in source, f"{stale!r} is stale"
