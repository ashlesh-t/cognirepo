# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Agent CLIs as routing backends (#87/#88): enable/disable/probe, ordering, fallback, wizard, streaming."""
from __future__ import annotations

import json
import os
import stat
from types import SimpleNamespace

import pytest

from core.config.paths import get_path
from intelligence.orchestrator import provider_status as ps
from intelligence.orchestrator import router
from intelligence.orchestrator.model_adapters import cli_adapter
from intelligence.orchestrator.model_adapters.anthropic_adapter import ModelResponse
from intelligence.orchestrator.model_adapters.errors import ModelCallError

KEYS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROK_API_KEY", "OPENAI_API_KEY")
CODEX_OK = ('{"type":"item.completed","item":{"id":"i","type":"agent_message","text":"OK"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":4,"output_tokens":1}}')


def _fake(bindir, name: str, stdout: str = "", exit_code: int = 0, stderr: str = "") -> None:
    (bindir / f"{name}.out").write_text(stdout, encoding="utf-8")
    (bindir / f"{name}.err").write_text(stderr, encoding="utf-8")
    script = bindir / name
    script.write_text(
        f'#!/bin/sh\nd="$(dirname "$0")"\nif [ "$1" = "--version" ]; then echo "{name} 1.0"; exit 0; fi\n'
        f'cat > /dev/null\ncat "$d/{name}.out"\ncat "$d/{name}.err" >&2\nexit {exit_code}\n', encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)


def _config(**updates) -> None:
    path = get_path("config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        cfg = {}
    cfg.update(updates)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)


@pytest.fixture(name="bindir")
def _bindir(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.delenv("COGNIREPO_HEADLESS", raising=False)
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    return d


def _dispatch(**kw):
    args = dict(query="q", primary_provider="anthropic", primary_model="m", system_prompt="", tool_manifest=[],
                max_tokens=10, tier="COMPLEX")
    args.update(kw)
    return router._dispatch_with_fallback(**args)  # pylint: disable=protected-access


# ── enable / disable ─────────────────────────────────────────────────────────────────────────────

def test_codex_enables_without_the_terms_flag(bindir):
    _fake(bindir, "codex", CODEX_OK)
    ok, msg = ps.enable_agent("codex")
    assert ok and "agents probe codex" in msg
    assert ps.cli_settings()["codex"] == {"enabled": True, "terms_ack": False}


@pytest.mark.parametrize("agent", ["claude", "gemini"])
def test_gated_agent_refuses_without_the_flag_and_writes_nothing(bindir, agent):
    _fake(bindir, agent)
    ok, msg = ps.enable_agent(agent)
    assert not ok and "--accept-terms-risk" in msg
    assert ps.cli_settings() == {}
    ok, _ = ps.enable_agent(agent, accept_terms_risk=True)
    assert ok and ps.cli_settings()[agent] == {"enabled": True, "terms_ack": True}


def test_enable_requires_the_binary_and_a_known_name(bindir):  # pylint: disable=unused-argument
    assert ps.enable_agent("codex")[0] is False
    assert "unknown agent" in ps.enable_agent("nope")[1]
    assert "unknown agent" in ps.disable_agent("nope")[1]


def test_enable_outside_an_initialised_repo_is_a_clear_error(bindir):
    _fake(bindir, "codex")
    os.remove(get_path("config.json"))
    ok, msg = ps.enable_agent("codex")
    assert not ok and "init" in msg


def test_disable_keeps_the_terms_acknowledgement(bindir):
    _fake(bindir, "claude")
    ps.enable_agent("claude", accept_terms_risk=True)
    assert ps.disable_agent("claude")[0]
    assert ps.cli_settings()["claude"] == {"enabled": False, "terms_ack": True}
    ok, _ = ps.enable_agent("claude")  # no flag needed again
    assert ok


# ── which backends qualify ───────────────────────────────────────────────────────────────────────

def test_nothing_enabled_means_no_cli_backend(bindir):
    _fake(bindir, "codex")
    assert ps.enabled_cli_backends() == []


def test_gated_without_ack_and_missing_binary_do_not_qualify(bindir):
    _fake(bindir, "claude")
    _config(cli_providers={"claude": {"enabled": True, "terms_ack": False}, "codex": {"enabled": True}})
    assert ps.enabled_cli_backends() == []  # claude not acked; codex has no binary


def test_auth_failure_excludes_and_known_good_goes_first(bindir):
    for n in ("claude", "codex", "gemini"):
        _fake(bindir, n)
    _config(cli_providers={n: {"enabled": True, "terms_ack": True} for n in ("claude", "codex", "gemini")})
    assert ps.enabled_cli_backends() == ["claude", "codex", "gemini"]
    ps.record_readiness("claude", False, "claude 1.0")
    ps.record_readiness("gemini", True, "gemini 1.0")
    assert ps.enabled_cli_backends() == ["gemini", "codex"]


def test_mark_result_writes_only_on_change(bindir, monkeypatch):
    _fake(bindir, "codex")
    writes = []
    real = ps.record_readiness
    monkeypatch.setattr(ps, "record_readiness", lambda *a, **k: writes.append(a) or real(*a, **k))
    ps.mark_result("codex", True)
    ps.mark_result("codex", True)
    ps.mark_result("codex", False)
    assert [w[1] for w in writes] == [True, False]
    ps.mark_result("nope", True)  # unknown agent: ignored, never raises


# ── probe ────────────────────────────────────────────────────────────────────────────────────────

def test_probe_requires_enabled(bindir):
    _fake(bindir, "codex", CODEX_OK)
    ready, detail = ps.probe_agent("codex")
    assert ready is None and "not enabled" in detail


def test_probe_success_records_ready(bindir):
    _fake(bindir, "codex", CODEX_OK)
    ps.enable_agent("codex")
    ready, detail = ps.probe_agent("codex", timeout=20)
    assert ready is True and "tokens" in detail
    assert ps.load()["cli"]["codex"]["ready"] is True


def test_probe_auth_failure_records_not_ready(bindir):
    _fake(bindir, "codex", "", exit_code=1, stderr="Not logged in")
    ps.enable_agent("codex")
    ready, _ = ps.probe_agent("codex", timeout=20)
    assert ready is False and ps.load()["cli"]["codex"]["ready"] is False
    assert ps.enabled_cli_backends() == []


def test_probe_other_failure_is_inconclusive_and_changes_nothing(bindir):
    _fake(bindir, "codex", "", exit_code=1, stderr="segfault")
    ps.enable_agent("codex")
    ready, _ = ps.probe_agent("codex", timeout=20)
    assert ready is None and "codex" not in ps.load()["cli"]


# ── ordering and dispatch ────────────────────────────────────────────────────────────────────────

def test_available_providers_never_includes_clis(bindir):
    _fake(bindir, "codex")
    ps.enable_agent("codex")
    assert router._available_providers() == []  # pylint: disable=protected-access


def test_without_clis_ordering_is_the_previous_api_ordering(bindir, monkeypatch):  # pylint: disable=unused-argument
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert router._ordered_backends("openai") == ["openai", "gemini"]  # pylint: disable=protected-access
    assert router._ordered_backends(None) == ["gemini", "openai"]  # pylint: disable=protected-access


def test_api_first_by_default_cli_first_when_preferred(bindir, monkeypatch):
    _fake(bindir, "codex")
    ps.enable_agent("codex")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert router._ordered_backends("anthropic") == ["anthropic", "codex-cli"]  # pylint: disable=protected-access
    _config(provider_preference="cli")
    assert router._ordered_backends("anthropic") == ["codex-cli", "anthropic"]  # pylint: disable=protected-access


def test_no_keys_enabled_cli_routes(bindir):
    _fake(bindir, "codex", CODEX_OK)
    ps.enable_agent("codex")
    r = _dispatch()
    assert r.text == "OK" and r.provider == "codex-cli"


def test_model_alias_follows_the_tier(bindir, monkeypatch):
    _fake(bindir, "claude")
    ps.enable_agent("claude", accept_terms_risk=True)
    seen = []
    monkeypatch.setattr(cli_adapter, "call", lambda **kw: seen.append(kw) or ModelResponse("ok", "m", "claude-cli"))
    _dispatch(tier="EXPERT")
    _dispatch(tier="STANDARD")
    assert [k["model_id"] for k in seen] == ["opus", "haiku"] and all(k["agent"] == "claude" for k in seen)


def test_codex_gets_no_model_flag(bindir, monkeypatch):
    _fake(bindir, "codex")
    ps.enable_agent("codex")
    seen = []
    monkeypatch.setattr(cli_adapter, "call", lambda **kw: seen.append(kw) or ModelResponse("ok", "m", "codex-cli"))
    _dispatch(tier="EXPERT")
    assert seen[0]["model_id"] == ""


def test_non_retryable_api_error_falls_through_to_a_waiting_cli(bindir, monkeypatch):
    _fake(bindir, "codex", CODEX_OK)
    ps.enable_agent("codex")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    real = router._call_adapter  # pylint: disable=protected-access

    def fake(**kw):
        if kw["provider"] == "anthropic":
            raise ModelCallError("anthropic", 401, "bad key")
        return real(**kw)

    monkeypatch.setattr(router, "_call_adapter", fake)
    assert _dispatch().provider == "codex-cli"


def test_non_retryable_api_error_still_stops_the_chain_without_a_cli(bindir, monkeypatch):  # pylint: disable=unused-argument
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    calls = []

    def fake(**kw):
        calls.append(kw["provider"])
        raise ModelCallError(kw["provider"], 401, "bad key")

    monkeypatch.setattr(router, "_call_adapter", fake)
    with pytest.raises(ModelCallError):
        _dispatch()
    assert calls == ["anthropic"]


def test_failing_cli_marks_it_and_the_chain_continues(bindir, monkeypatch):
    _fake(bindir, "codex", "", exit_code=1, stderr="Not logged in")
    _fake(bindir, "gemini", "")
    ps.enable_agent("codex")
    ps.enable_agent("gemini", accept_terms_risk=True)
    monkeypatch.setattr(cli_adapter, "call", lambda **kw: (_ for _ in ()).throw(ModelCallError(kw["agent"] + "-cli", 401, "x"))
                        if kw["agent"] == "codex" else ModelResponse("g", "m", "gemini-cli"))
    assert _dispatch().provider == "gemini-cli"
    assert ps.load()["cli"]["codex"]["ready"] is False
    assert ps.load()["cli"]["gemini"]["ready"] is True


def test_all_backends_failing_raises_the_last_error(bindir, monkeypatch):
    _fake(bindir, "codex")
    ps.enable_agent("codex")
    monkeypatch.setattr(cli_adapter, "call", lambda **kw: (_ for _ in ()).throw(ModelCallError("codex-cli", 500, "boom")))
    with pytest.raises(ModelCallError) as ei:
        _dispatch()
    assert ei.value.status_code == 500


def test_promote_to_standard_uses_a_cli_when_there_are_no_keys(bindir):
    _fake(bindir, "codex", CODEX_OK)
    ps.enable_agent("codex")
    r = router._promote_to_standard("q", "", [], 10)  # pylint: disable=protected-access
    assert r is not None and r.provider == "codex-cli"


def test_promote_to_standard_still_none_with_nothing_available(bindir):  # pylint: disable=unused-argument
    assert router._promote_to_standard("q", "", [], 10) is None  # pylint: disable=protected-access


# ── streaming ────────────────────────────────────────────────────────────────────────────────────

def test_stream_dispatch_cli_yields_text_and_returns_usage(bindir):
    _fake(bindir, "codex", CODEX_OK)
    ps.enable_agent("codex")
    gen = router._stream_dispatch(  # pylint: disable=protected-access
        query="q", provider="codex-cli", model_id="", system_prompt="", tool_manifest=[], max_tokens=1)
    assert next(gen) == "OK"
    with pytest.raises(StopIteration) as stop:
        next(gen)
    assert stop.value.value == {"input_tokens": 4, "output_tokens": 1}
    assert ps.load()["cli"]["codex"]["ready"] is True


def _stream_with(monkeypatch, clf_provider, tier="COMPLEX"):
    seen = {}
    clf = SimpleNamespace(tier=tier, provider=clf_provider, model="primary-model", score=1.0)
    monkeypatch.setattr(router, "classify", lambda *a, **k: clf)
    monkeypatch.setattr(router, "build_context", lambda *a, **k: SimpleNamespace(
        system_prompt="", tool_manifest=[], ast_hits=[]))
    monkeypatch.setattr(router, "_post_process", lambda **k: seen.setdefault("response", k["response"]))

    def fake_dispatch(**kw):
        seen["provider"], seen["model_id"] = kw["provider"], kw["model_id"]
        yield "chunk"
        return {}

    monkeypatch.setattr(router, "_stream_dispatch", fake_dispatch)
    assert list(router.stream_route("q")) == ["chunk"]
    return seen


def test_stream_route_swaps_in_a_cli_when_the_primary_has_no_key(bindir, monkeypatch):
    _fake(bindir, "claude")
    ps.enable_agent("claude", accept_terms_risk=True)
    seen = _stream_with(monkeypatch, "anthropic")
    assert (seen["provider"], seen["model_id"]) == ("claude-cli", "sonnet")
    assert seen["response"].provider == "claude-cli"


def test_stream_route_keeps_the_primary_when_it_has_a_key(bindir, monkeypatch):
    _fake(bindir, "claude")
    ps.enable_agent("claude", accept_terms_risk=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    seen = _stream_with(monkeypatch, "anthropic")
    assert (seen["provider"], seen["model_id"]) == ("anthropic", "primary-model")


def test_stream_route_unchanged_without_any_cli(bindir, monkeypatch):  # pylint: disable=unused-argument
    seen = _stream_with(monkeypatch, "anthropic")
    assert (seen["provider"], seen["model_id"]) == ("anthropic", "primary-model")


# ── CLI commands ─────────────────────────────────────────────────────────────────────────────────

def _args(**kw):
    return SimpleNamespace(**{"agents_command": "list", "json": False, "name": None, "accept_terms_risk": False,
                              "timeout": 20.0, **kw})


def test_agents_enable_disable_commands(bindir, capsys):
    import interface.cli.main as cli
    _fake(bindir, "claude")
    _fake(bindir, "codex", CODEX_OK)
    assert cli._cmd_agents(_args(agents_command="enable", name="claude")) == 1  # pylint: disable=protected-access
    assert "--accept-terms-risk" in capsys.readouterr().err
    assert cli._cmd_agents(_args(agents_command="enable", name="claude", accept_terms_risk=True)) == 0  # pylint: disable=protected-access
    assert cli._cmd_agents(_args(agents_command="enable", name="codex")) == 0  # pylint: disable=protected-access
    capsys.readouterr()
    assert cli._cmd_agents(_args(json=True)) == 0  # pylint: disable=protected-access
    rows = {r["name"]: r for r in json.loads(capsys.readouterr().out)}
    assert rows["claude"]["enabled"] and rows["codex"]["enabled"] and not rows["gemini"]["enabled"]
    assert cli._cmd_agents(_args(agents_command="disable", name="claude")) == 0  # pylint: disable=protected-access


def test_agents_probe_command(bindir, capsys):
    import interface.cli.main as cli
    _fake(bindir, "codex", CODEX_OK)
    assert cli._cmd_agents(_args(agents_command="probe")) == 1  # pylint: disable=protected-access
    assert "No agent CLI is enabled" in capsys.readouterr().err
    ps.enable_agent("codex")
    assert cli._cmd_agents(_args(agents_command="probe")) == 0  # pylint: disable=protected-access
    assert "codex: ready" in capsys.readouterr().out


# ── wizard ───────────────────────────────────────────────────────────────────────────────────────

def _row(name, installed=True):
    return ps.ProviderStatus(name=name, kind="cli", installed=installed, enabled=False, ready=None, version="1",
                             path="/x", terms_gated=ps.CLI_AGENT_SPECS[name].terms_gated)


@pytest.mark.parametrize("answers,rows,expected", [
    ([], [], {}),
    ([], [_row("codex", installed=False)], {}),
    ([False], [_row("codex")], {}),
    ([True], [_row("codex")], {"codex": False}),
    ([True, True], [_row("claude")], {"claude": True}),
    ([True, False], [_row("claude")], {}),
    ([True, False, True, True], [_row("codex"), _row("gemini")], {"codex": False}),
])
def test_wizard_offers_each_installed_cli_default_no(monkeypatch, answers, rows, expected):
    from interface.cli import wizard
    monkeypatch.setattr(ps, "detect_cli_agents", lambda *a, **k: rows)
    asked = []
    it = iter(answers)

    def ask(prompt, default=True):
        asked.append((prompt, default))
        return next(it)

    monkeypatch.setattr(wizard, "_ask_yn", ask)
    assert wizard._ask_cli_backends() == expected  # pylint: disable=protected-access
    assert all(default is False for _, default in asked)  # never defaults to yes


def test_apply_choices_enables_what_the_wizard_collected(bindir):
    _fake(bindir, "codex")
    _fake(bindir, "claude")
    out = {n: (ok, msg) for n, ok, msg in ps.apply_choices({"codex": False, "claude": True})}
    assert out["codex"][0] and out["claude"][0]
    assert set(ps.cli_settings()) == {"codex", "claude"}
