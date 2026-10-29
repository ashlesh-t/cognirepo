# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Opt-in model discovery (#87/#88, phase 2): parsing, tiering, cache, ladder, router wiring, CLI. No network."""
from __future__ import annotations

import io
import json
import os
import stat
import urllib.error
from types import SimpleNamespace

import pytest

from core.config.paths import get_path
from intelligence.orchestrator import classifier as clf
from intelligence.orchestrator import model_discovery as md
from intelligence.orchestrator import provider_status as ps
from intelligence.orchestrator import router

SECRET = "sk-test-SECRET-key-value"
KEYS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROK_API_KEY", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


def _info(*ids, **kw):
    return [md.ModelInfo(id=i, **kw) for i in ids]


def _seed(provider="anthropic", ids=("claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6"), key=SECRET,
          fetched_at=None, rules=None, denied=()):
    rows = md.tier_models(_info(*ids))
    entry = {"fetched_at": fetched_at or md._now(), "key_fingerprint": md.fingerprint(key),  # pylint: disable=protected-access
             "endpoint": "v1/models", "rules_hash": rules or clf.rules_hash(), "models": rows, "denied": list(denied)}
    ps.modify(lambda d: d.setdefault("api", {}).__setitem__(provider, entry))


# ── tier assignment ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model_id,tier", [
    ("claude-opus-4-6", "EXPERT"), ("claude-sonnet-4-6", "COMPLEX"), ("claude-haiku-4-5", "STANDARD"),
    ("claude-3-5-sonnet-20241022", "COMPLEX"), ("claude-3-opus-20240229", "EXPERT"), ("gpt-4o", "COMPLEX"),
    ("gpt-4o-mini", "STANDARD"), ("o3", "EXPERT"), ("o3-mini", "STANDARD"), ("gpt-5", "COMPLEX"),
    ("gpt-5-nano", "STANDARD"), ("gemini-2.5-pro", "COMPLEX"), ("gemini-2.5-flash", "STANDARD"),
    ("gemini-2.0-flash-lite", "STANDARD"), ("gemini-3-ultra", "EXPERT"), ("grok-4", "COMPLEX"),
    ("grok-3-mini", "STANDARD"), ("grok-4-heavy", "EXPERT"), ("claude-3-5-haiku-latest", "STANDARD"),
    # not routable chat models, or an unknown family: never assigned
    ("text-embedding-3-small", None), ("whisper-1", None), ("dall-e-3", None), ("gemini-embedding-001", None),
    ("some-new-thing", None), ("ft:gpt-4o:org", None), ("gpt-4o-realtime-preview", None), ("gpt-image-1", None),
    ("omni-moderation-latest", None), ("", None), ("bad id with spaces", None), ("-leading-dash", None),
])
def test_assign_tier(model_id, tier):
    assert clf.assign_tier(model_id) == tier


def test_gemini_is_not_mistaken_for_a_mini_model():
    assert clf.assign_tier("gemini-2.5-pro") == "COMPLEX"  # "gemini" contains "mini"


def test_small_context_demotes_upper_tiers_one_step():
    assert clf.assign_tier("claude-opus-4-6", ctx=8000) == "COMPLEX"
    assert clf.assign_tier("claude-sonnet-4-6", ctx=8000) == "STANDARD"
    assert clf.assign_tier("claude-haiku-4-5", ctx=8000) == "STANDARD"
    assert clf.assign_tier("claude-opus-4-6", ctx=200_000) == "EXPERT"


def test_gemini_needs_generate_content():
    assert clf.assign_tier("gemini-2.5-pro", methods=["embedContent"]) is None
    assert clf.assign_tier("gemini-2.5-pro", methods=["generateContent"]) == "COMPLEX"


def test_version_and_family():
    assert clf.model_version("claude-opus-4-6") == (4, 6) and clf.model_version("x-3-5-sonnet-20241022") == (3, 5)
    assert clf.model_version("nothing") == ()
    assert clf.model_family("claude-opus-4-6") == clf.model_family("claude-opus-5") == "claude-opus"
    assert clf.model_family("claude-opus-4-6") != clf.model_family("claude-sonnet-4-6")


def test_dated_snapshot_loses_to_its_alias():
    ids = ("claude-3-5-sonnet", "claude-3-5-sonnet-20241022", "claude-3-opus-20240229")
    rows = {r["id"]: r["tier"] for r in md.tier_models(_info(*ids))}
    assert rows["claude-3-5-sonnet"] == "COMPLEX" and rows["claude-3-5-sonnet-20241022"] is None
    assert rows["claude-3-opus-20240229"] == "EXPERT"  # no undated alias listed: kept


def test_user_tier_override_wins():
    rows = {r["id"]: r["tier"] for r in md.tier_models(_info("some-new-thing"), {"some-new-thing": "EXPERT"})}
    assert rows["some-new-thing"] == "EXPERT"


# ── parsing canned provider responses ────────────────────────────────────────────────────────────

def test_parse_anthropic_paginates_and_skips_bad_rows():
    page = {"data": [{"id": "claude-a-1", "created_at": "2026-01-01"}, {"id": "bad id"}, {"nope": 1}],
            "has_more": True, "last_id": "claude-a-1"}
    models, more = md.parse_anthropic(page)
    assert [m.id for m in models] == ["claude-a-1"] and more == "claude-a-1"
    assert md.parse_anthropic({"data": [], "has_more": False})[1] is None


def test_parse_openai():
    models, more = md.parse_openai({"data": [{"id": "gpt-x", "created": 1700000000, "owned_by": "o"}]})
    assert models[0].id == "gpt-x" and models[0].created == "1700000000" and more is None


def test_parse_gemini_strips_prefix_and_keeps_limits():
    page = {"models": [{"name": "models/gemini-9-pro", "inputTokenLimit": 1000000,
                        "supportedGenerationMethods": ["generateContent"]}], "nextPageToken": "t2"}
    models, token = md.parse_gemini(page)
    assert models[0].id == "gemini-9-pro" and models[0].ctx == 1000000 and models[0].methods == ("generateContent",)
    assert token == "t2"


@pytest.mark.parametrize("body", [{"models": [{"id": "grok-9"}]}, {"data": [{"id": "grok-9"}]}])
def test_parse_grok_accepts_both_shapes(body):
    assert md.parse_grok(body)[0][0].id == "grok-9"


@pytest.mark.parametrize("fn", [md.parse_anthropic, md.parse_openai, md.parse_gemini, md.parse_grok])
@pytest.mark.parametrize("body", [None, [], "x", {}, {"data": "no"}])
def test_malformed_bodies_raise_fetch_error(fn, body):
    with pytest.raises(md.FetchError) as ei:
        fn(body)
    assert ei.value.kind == "malformed"


def test_fetch_follows_pages_and_stops(monkeypatch):
    pages = iter([{"data": [{"id": "claude-a-1"}], "has_more": True, "last_id": "claude-a-1"},
                  {"data": [{"id": "claude-b-2"}], "has_more": False}])
    urls = []
    monkeypatch.setattr(md, "_get_json", lambda url, h, t: urls.append(url) or next(pages))
    models, endpoint = md.fetch_provider_models("anthropic", SECRET)
    assert [m.id for m in models] == ["claude-a-1", "claude-b-2"] and endpoint == "v1/models"
    assert "after_id=claude-a-1" in urls[1]


def test_fetch_caps_runaway_pagination(monkeypatch):
    monkeypatch.setattr(md, "_get_json", lambda *a: {"data": [{"id": "claude-a-1"}], "has_more": True, "last_id": "claude-a-1"})
    models, _ = md.fetch_provider_models("anthropic", SECRET)
    assert len(models) == md._MAX_PAGES  # pylint: disable=protected-access


def test_grok_falls_back_to_the_openai_compatible_list(monkeypatch):
    def fake(url, headers, timeout):  # pylint: disable=unused-argument
        if "language-models" in url:
            raise md.FetchError("transient", "HTTP 404")
        return {"data": [{"id": "grok-9"}]}
    monkeypatch.setattr(md, "_get_json", fake)
    models, endpoint = md.fetch_provider_models("grok", SECRET)
    assert models[0].id == "grok-9" and endpoint == "v1/models"


def test_grok_does_not_retry_a_rejected_key(monkeypatch):
    calls = []
    monkeypatch.setattr(md, "_get_json", lambda url, h, t: calls.append(url) or (_ for _ in ()).throw(md.FetchError("rejected", "HTTP 401")))
    with pytest.raises(md.FetchError):
        md.fetch_provider_models("grok", SECRET)
    assert len(calls) == 1


def test_empty_model_list_is_a_failure(monkeypatch):
    monkeypatch.setattr(md, "_get_json", lambda *a: {"data": []})
    with pytest.raises(md.FetchError):
        md.fetch_provider_models("openai", SECRET)


# ── HTTP layer: key in a header, never in the URL ────────────────────────────────────────────────

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_key_travels_in_a_header_not_the_url(monkeypatch):
    seen = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: seen.append(req) or _Resp(b'{"data": [{"id": "claude-a-1"}]}'))
    for provider in ("anthropic", "openai", "gemini", "grok"):
        seen.clear()
        try:
            md.fetch_provider_models(provider, SECRET)
        except md.FetchError:
            pass  # gemini/grok bodies differ; only the request matters here
        assert seen and all(SECRET not in r.full_url for r in seen)
        assert any(SECRET in v for r in seen for v in r.headers.values())


def test_non_https_is_refused():
    with pytest.raises(md.FetchError):
        md._get_json("http://api.example.com/v1/models", {}, 1)  # pylint: disable=protected-access


@pytest.mark.parametrize("code,kind", [(401, "rejected"), (403, "rejected"), (429, "transient"), (500, "transient")])
def test_http_status_classes(monkeypatch, code, kind):
    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(md.FetchError) as ei:
        md._get_json("https://x.example/v1", {}, 1)  # pylint: disable=protected-access
    assert ei.value.kind == kind


def test_network_error_and_bad_json_are_classified(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(md.FetchError) as ei:
        md._get_json("https://x.example/v1", {}, 1)  # pylint: disable=protected-access
    assert ei.value.kind == "transient"
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: _Resp(b"<html>"))
    with pytest.raises(md.FetchError) as ei:
        md._get_json("https://x.example/v1", {}, 1)  # pylint: disable=protected-access
    assert ei.value.kind == "malformed"


# ── refresh + cache ──────────────────────────────────────────────────────────────────────────────

def _fetch_returns(monkeypatch, ids=("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-6")):
    monkeypatch.setattr(md, "fetch_provider_models", lambda p, k, t=5.0: (_info(*ids), "v1/models"))


def test_refresh_without_keys_does_no_network(monkeypatch):
    monkeypatch.setattr(md, "_get_json", lambda *a: (_ for _ in ()).throw(AssertionError("network used")))
    report = md.refresh()
    assert {r["status"] for r in report.values()} == {"no_key"}
    assert not ps.load().get("api")


def test_refresh_caches_and_never_stores_the_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _fetch_returns(monkeypatch)
    report = md.refresh(["anthropic"])
    assert report["anthropic"] == {"status": "ok", "count": 3, "detail": "v1/models"}
    text = open(ps.status_path(), encoding="utf-8").read()
    assert SECRET not in text and md.fingerprint(SECRET) in text
    assert stat.S_IMODE(os.stat(ps.status_path()).st_mode) == 0o600
    entry = md.load_entry("anthropic")
    assert md.entry_is_fresh("anthropic", entry)
    assert {r["id"]: r["tier"] for r in entry["models"]}["claude-sonnet-5"] == "COMPLEX"


def test_refresh_keeps_the_cli_section(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    ps.record_readiness("codex", True, "v1")
    _fetch_returns(monkeypatch)
    md.refresh(["anthropic"])
    assert ps.load()["cli"]["codex"]["ready"] is True and md.load_entry("anthropic")


@pytest.mark.parametrize("error,status", [(md.FetchError("rejected", "HTTP 401"), "rejected"),
                                         (md.FetchError("transient", "HTTP 429"), "failed"),
                                         (md.FetchError("malformed", "no data"), "failed"),
                                         (RuntimeError("boom"), "failed")])
def test_failed_refresh_keeps_the_previous_cache(monkeypatch, error, status):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _seed()
    before = md.load_entry("anthropic")

    def boom(*a, **k):
        raise error
    monkeypatch.setattr(md, "fetch_provider_models", boom)
    assert md.refresh(["anthropic"])["anthropic"]["status"] == status
    assert md.load_entry("anthropic") == before


def test_refresh_total_timeout_is_bounded(monkeypatch):
    import time
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr(md, "fetch_provider_models", lambda *a, **k: time.sleep(5))
    t0 = time.monotonic()
    report = md.refresh(["anthropic"], total_timeout=0.3)
    assert time.monotonic() - t0 < 4 and report["anthropic"]["status"] == "failed"


def test_freshness_rules(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _seed()
    entry = md.load_entry("anthropic")
    assert md.entry_is_fresh("anthropic", entry)
    assert not md.entry_is_fresh("anthropic", {**entry, "fetched_at": "2020-01-01T00:00:00Z"})  # TTL
    assert not md.entry_is_fresh("anthropic", {**entry, "rules_hash": "other"})                 # rules changed
    assert not md.entry_is_fresh("anthropic", {**entry, "fetched_at": "garbage"})
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET + "-rotated")
    assert not md.entry_is_fresh("anthropic", entry)                                            # key rotated
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert not md.entry_is_fresh("anthropic", entry)                                            # no key


def test_clear_cache_one_or_all():
    _seed("anthropic")
    _seed("openai", ids=("gpt-5",))
    md.clear_cache("anthropic")
    assert md.load_entry("anthropic") is None and md.load_entry("openai")
    md.clear_cache()
    assert md.load_entry("openai") is None


def test_deny_never_blocks_a_shipped_default():
    _seed(denied=())
    md.deny("anthropic", clf.default_model_for("anthropic", "COMPLEX"))
    md.deny("anthropic", "claude-sonnet-5")
    md.deny("anthropic", "bad id")
    assert md.load_entry("anthropic")["denied"] == ["claude-sonnet-5"]


# ── the ladder ───────────────────────────────────────────────────────────────────────────────────

def test_newer_same_family_replaces_the_default(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _seed(ids=("claude-sonnet-4-6", "claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5"))
    assert md.pick_for_tier("anthropic", "COMPLEX", "claude-sonnet-4-6") == "claude-sonnet-5"
    assert md.pick_for_tier("anthropic", "STANDARD", "claude-haiku-4-5") is None  # nothing newer
    assert md.pick_for_tier("anthropic", "COMPLEX", "claude-sonnet-5") is None    # already the newest


def test_same_tier_but_other_family_is_not_an_upgrade(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _seed(ids=("claude-sonnet-4-6", "claude-pro-9"))  # both COMPLEX, higher version, different family
    rows = {r["id"]: r["tier"] for r in md.load_entry("anthropic")["models"]}
    assert rows["claude-sonnet-4-6"] == rows["claude-pro-9"] == "COMPLEX"
    assert md.pick_for_tier("anthropic", "COMPLEX", "claude-sonnet-4-6") is None


def test_retired_default_is_replaced_by_the_newest_of_the_tier(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _seed(ids=("claude-sonnet-4-9", "claude-sonnet-5", "claude-haiku-4-5"))
    assert md.pick_for_tier("anthropic", "COMPLEX", "claude-sonnet-4-6") == "claude-sonnet-5"
    assert md.pick_for_tier("anthropic", "EXPERT", "claude-opus-4-6") is None  # no EXPERT model at all: keep default


def test_denied_and_overrides(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _seed(ids=("claude-sonnet-4-6", "claude-sonnet-5"), denied=["claude-sonnet-5"])
    assert md.pick_for_tier("anthropic", "COMPLEX", "claude-sonnet-4-6") is None
    _seed(ids=("claude-sonnet-4-6", "claude-sonnet-5"))
    assert md.pick_for_tier("anthropic", "COMPLEX", "claude-sonnet-4-6", {"deny": ["claude-sonnet-5"]}) is None
    _seed(ids=("claude-haiku-4-5", "mystery-model-9"))
    assert md.pick_for_tier("anthropic", "EXPERT", "gone", {"tiers": {"mystery-model-9": "EXPERT"}}) == "mystery-model-9"


def test_unassigned_models_are_never_auto_selected(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _seed(ids=("mystery-model-9", "claude-haiku-4-5"))
    for tier in ("STANDARD", "COMPLEX", "EXPERT"):
        assert md.pick_for_tier("anthropic", tier, "gone") != "mystery-model-9"


def test_no_or_stale_cache_changes_nothing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    assert md.pick_for_tier("anthropic", "COMPLEX", "claude-sonnet-4-6") is None
    _seed(ids=("claude-sonnet-5",), fetched_at="2020-01-01T00:00:00Z")
    assert md.pick_for_tier("anthropic", "COMPLEX", "claude-sonnet-4-6") is None


def test_resolve_model_is_exactly_configured_without_a_cache(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    for tier in ("STANDARD", "COMPLEX", "EXPERT"):
        base = clf.default_model_for("anthropic", tier)
        assert clf.resolve_model("anthropic", tier, base) == base
    assert clf.resolve_model("anthropic", None, "") == ""


def test_resolve_model_precedence(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _seed(ids=("claude-sonnet-4-6", "claude-sonnet-5"))
    base = clf.default_model_for("anthropic", "COMPLEX")
    assert clf.resolve_model("anthropic", "COMPLEX", base) == "claude-sonnet-5"                 # discovered upgrade
    assert clf.resolve_model("anthropic", "COMPLEX", "my-own-model") == "my-own-model"          # user's choice kept
    cfg = {"model_overrides": {"pin": {"anthropic": {"COMPLEX": "pinned-model-1"}}}}
    assert clf.resolve_model("anthropic", "COMPLEX", "my-own-model", cfg) == "pinned-model-1"   # pin beats all
    bad = {"model_overrides": {"pin": {"anthropic": {"COMPLEX": "bad id; rm -rf"}}}}
    assert clf.resolve_model("anthropic", "COMPLEX", base, bad) == "claude-sonnet-5"             # invalid pin ignored


def test_resolve_model_never_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr(md, "pick_for_tier", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert clf.resolve_model("anthropic", "COMPLEX", "claude-sonnet-4-6", {}) == "claude-sonnet-4-6"
    assert clf.resolve_model("anthropic", "COMPLEX", "x", {"model_overrides": "not a dict"}) == "x"


# ── router wiring ────────────────────────────────────────────────────────────────────────────────

def test_router_upgrades_primary_and_fallback_models(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _seed(ids=("claude-haiku-4-5", "claude-haiku-5", "claude-sonnet-4-6", "claude-sonnet-5"))
    primary = clf.default_model_for("anthropic", "COMPLEX")
    assert router._model_for("anthropic", "COMPLEX", "anthropic", primary) == "claude-sonnet-5"  # pylint: disable=protected-access
    # a fallback provider gets its own default, upgraded within the family
    assert router._model_for("anthropic", "COMPLEX", "openai", "gpt-x") == "claude-haiku-5"  # pylint: disable=protected-access
    assert router._model_for("anthropic", "COMPLEX", "anthropic", "my-own-model") == "my-own-model"  # pylint: disable=protected-access


def test_router_is_unchanged_without_a_cache():
    primary = clf.default_model_for("anthropic", "COMPLEX")
    assert router._model_for("anthropic", "COMPLEX", "anthropic", primary) == primary  # pylint: disable=protected-access
    assert router._model_for("gemini", "COMPLEX", "anthropic", primary) == router._PROVIDER_DEFAULT_MODELS["gemini"]  # pylint: disable=protected-access


def test_model_not_found_marks_it_denied(monkeypatch):
    from intelligence.orchestrator.model_adapters.errors import ModelCallError
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _seed(ids=("claude-sonnet-4-6", "claude-sonnet-5"))

    def fake(**kw):
        raise ModelCallError(kw["provider"], 404, "model not found")
    monkeypatch.setattr(router, "_call_adapter", fake)
    default = clf.default_model_for("anthropic", "COMPLEX")
    with pytest.raises(ModelCallError):
        router._dispatch_with_fallback(  # pylint: disable=protected-access
            query="q", primary_provider="anthropic", primary_model=default,
            system_prompt="", tool_manifest=[], max_tokens=1, tier="COMPLEX")
    assert md.load_entry("anthropic")["denied"] == ["claude-sonnet-5"]
    # next call: the denied model is no longer picked, the default is used
    assert router._model_for("anthropic", "COMPLEX", "anthropic", default) == default  # pylint: disable=protected-access


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────

def _args(cmd, **kw):
    return SimpleNamespace(**{"models_command": cmd, "provider": None, "timeout": 5.0, "stale": False, "json": False, **kw})


def test_models_commands(monkeypatch, capsys):
    import interface.cli.main as cli
    monkeypatch.setattr(md, "_get_json", lambda *a: (_ for _ in ()).throw(AssertionError("list/clear must not use the network")))
    assert cli._cmd_models(_args("list")) == 0  # pylint: disable=protected-access
    assert "No cached models" in capsys.readouterr().out
    assert cli._cmd_models(_args("refresh")) == 1  # pylint: disable=protected-access
    assert "nothing to refresh" in capsys.readouterr().err

    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _fetch_returns(monkeypatch, ("claude-haiku-4-5", "claude-sonnet-4-6", "claude-sonnet-5", "claude-opus-4-6", "mystery-9"))
    assert cli._cmd_models(_args("refresh", provider="anthropic")) == 0  # pylint: disable=protected-access
    assert "ok" in capsys.readouterr().out
    assert cli._cmd_models(_args("list")) == 0  # pylint: disable=protected-access
    out = capsys.readouterr().out
    assert "unassigned" in out and "COMPLEX -> claude-sonnet-5 (discovered)" in out and "EXPERT -> claude-opus-4-6 (default)" in out
    assert cli._cmd_models(_args("list", json=True)) == 0  # pylint: disable=protected-access
    data = json.loads(capsys.readouterr().out)
    assert data["anthropic"]["fresh"] and data["anthropic"]["effective"]["COMPLEX"]["source"] == "discovered"
    assert cli._cmd_models(_args("clear")) == 0  # pylint: disable=protected-access
    assert md.load_entry("anthropic") is None


def test_refresh_exit_code_reflects_a_failure(monkeypatch, capsys):
    import interface.cli.main as cli
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr(md, "fetch_provider_models", lambda *a, **k: (_ for _ in ()).throw(md.FetchError("rejected", "HTTP 401")))
    assert cli._cmd_models(_args("refresh")) == 1  # pylint: disable=protected-access
    assert "rejected" in capsys.readouterr().out


def test_stale_entries_are_hidden_unless_asked(monkeypatch, capsys):
    import interface.cli.main as cli
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    _seed(fetched_at="2020-01-01T00:00:00Z")
    cli._cmd_models(_args("list"))  # pylint: disable=protected-access
    assert "No cached models" in capsys.readouterr().out
    cli._cmd_models(_args("list", stale=True))  # pylint: disable=protected-access
    assert "STALE" in capsys.readouterr().out


def test_discovery_module_holds_no_model_id_literals():
    import re
    src = open(md.__file__, encoding="utf-8").read()
    assert not re.search(r'"claude-[a-z]+-[0-9]|"gemini-[0-9]|"gpt-[0-9]|"grok-', src)
