# pylint: disable=missing-docstring, import-outside-toplevel, protected-access, redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
OpenAI-compatible gateway provider: settings and URL safety, discovery, tiering, the per-tier model pick, the
adapter's wire format. No real network: a stub gateway on 127.0.0.1 answers /v1/models and /v1/chat/completions.
"""
from __future__ import annotations

import http.server
import json
import logging
import os
import threading
from types import SimpleNamespace

import pytest

from core.config.paths import get_global_dir, get_path
from intelligence.orchestrator import classifier as clf
from intelligence.orchestrator import gateway as gw
from intelligence.orchestrator import model_discovery as md
from intelligence.orchestrator import provider_status as ps
from intelligence.orchestrator import router
from intelligence.orchestrator.model_adapters import gateway_adapter
from intelligence.orchestrator.model_adapters.errors import ModelCallError

URL = "https://gw.example.test/v1"
KEY = "gw-test-SECRET-key"

#: Shaped like a real multi-vendor gateway's /v1/models (namespaced, dotted ids; some bare ids; non-chat entries).
GW_IDS = (
    "anthropic/claude-haiku-4.5", "anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-4.5",
    "anthropic/claude-opus-4.6", "google/gemini-2.5-flash", "google/gemini-2.5-pro", "openai/gpt-4o-mini",
    "x-ai/grok-4.20", "gpt-4o", "cohere/embed-v4", "mancer/weaver",
)


def _body(ids=GW_IDS):
    return {"object": "list", "data": [{"object": "model", "created": 1700000000, "owned_by": "gw", "id": i,
                                         "name": i, "input_cost_per_token": 8e-07} for i in ids]}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    gw._warned.clear()
    for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROK_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def _write_global(section):
    os.makedirs(get_global_dir(), exist_ok=True)
    with open(os.path.join(get_global_dir(), "config.json"), "w", encoding="utf-8") as fh:
        json.dump({"gateway": section}, fh)


def _configure(monkeypatch, url=URL, prefer=None):
    monkeypatch.setenv(gw.ENV_URL, url)
    monkeypatch.setenv(gw.ENV_KEY, KEY)
    if prefer:
        monkeypatch.setenv(gw.ENV_PREFER, prefer)


def _seed(monkeypatch, ids=GW_IDS):
    """Cache the gateway's models as `models refresh` would (the network call is replaced by a canned body)."""
    monkeypatch.setattr(md, "_get_json", lambda *a: _body(ids))
    assert md.refresh(["gateway"])["gateway"]["status"] == "ok"


# ── URL safety ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("https://aicredits.in/v1", "https://aicredits.in/v1"),
    ("https://aicredits.in/v1/", "https://aicredits.in/v1"),
    ("  https://gw.example.test:8443/api/v1  ", "https://gw.example.test:8443/api/v1"),
    ("http://127.0.0.1:4000/v1", "http://127.0.0.1:4000/v1"),
    ("http://localhost:4000", "http://localhost:4000"),
    ("http://[::1]:4000/v1", "http://[::1]:4000/v1"),
    # plain http to anything but this machine
    ("http://gw.example.test/v1", None),
    ("http://127.0.0.1.evil.test/v1", None),
    ("http://localhost.evil.test/v1", None),
    # credentials, query or fragment in the URL
    ("https://user:pw@gw.example.test/v1", None),
    ("https://user@gw.example.test/v1", None),
    ("https://gw.example.test/v1?key=abc", None),
    ("https://gw.example.test/v1?", None),
    ("https://gw.example.test/v1#frag", None),
    # not a URL we can use
    ("ftp://gw.example.test/v1", None), ("https://", None), ("gw.example.test/v1", None), ("", None), ("   ", None),
    (None, None), (42, None), ("https://gw.example.test/v1 x", None), ("https://gw.example.test/\nv1", None),
    ("https://gw.example.test:99999/v1", None), ("https://" + "a" * 300 + ".test/v1", None),
])
def test_normalize_url(raw, expected):
    assert gw.normalize_url(raw) == expected


def test_is_loopback_http():
    assert gw.is_loopback_http("http://127.0.0.1:4000/v1/models")
    assert not gw.is_loopback_http("http://gw.example.test/v1/models")
    assert not gw.is_loopback_http("https://127.0.0.1/v1")  # https takes the normal path
    assert not gw.is_loopback_http(None)


def test_env_beats_the_user_level_file(monkeypatch):
    _write_global({"base_url": "https://from-file.test/v1", "prefer": "gpt-"})
    assert gw.base_url() == "https://from-file.test/v1" and gw.prefer() == "gpt-"
    monkeypatch.setenv(gw.ENV_URL, URL)
    monkeypatch.setenv(gw.ENV_PREFER, "Anthropic/")
    assert gw.base_url() == URL and gw.prefer() == "anthropic/"


def test_a_repos_own_config_can_never_set_the_url(tmp_path):
    """A cloned repo can ship .cognirepo/config.json; if it chose the URL it would receive the user's key."""
    from core.config.paths import get_path
    repo_cfg = tmp_path / ".cognirepo" / "config.json"
    repo_cfg.write_text(json.dumps({"gateway": {"base_url": "https://evil.example.test/v1", "prefer": "x/"}}))
    assert get_path("config.json") == str(repo_cfg)  # this really is the file every repo-level setting is read from
    assert gw.base_url() is None and gw.prefer() is None
    _write_global({"base_url": URL})
    assert gw.base_url() == URL


def test_the_key_is_read_from_the_environment_only(monkeypatch):
    _write_global({"base_url": URL, "api_key": "from-file"})
    assert gw.api_key() is None and not gw.configured()
    monkeypatch.setenv(gw.ENV_KEY, KEY)
    assert gw.api_key() == KEY and gw.configured()


def test_a_key_without_a_valid_url_is_not_configured(monkeypatch):
    monkeypatch.setenv(gw.ENV_KEY, KEY)
    assert not gw.configured()
    monkeypatch.setenv(gw.ENV_URL, "http://gw.example.test/v1")  # remote http is refused
    assert not gw.configured()


def test_an_invalid_url_is_reported_once_and_never_logged(monkeypatch, caplog):
    monkeypatch.setenv(gw.ENV_URL, "https://user:SECRETTOKEN@gw.example.test/v1")
    with caplog.at_level("WARNING"):
        assert gw.base_url() is None
        assert gw.base_url() is None
    assert len([r for r in caplog.records if "gateway base URL ignored" in r.getMessage()]) == 1
    assert "SECRETTOKEN" not in caplog.text


def test_host_never_includes_the_path(monkeypatch):
    monkeypatch.setenv(gw.ENV_URL, "https://gw.example.test:8443/tok-123/v1")
    assert gw.host() == "gw.example.test:8443"


@pytest.mark.parametrize("raw", ["has space", "a" * 65, "a;b", "$(x)", "a\nb"])
def test_prefer_rejects_odd_values(monkeypatch, raw):
    monkeypatch.setenv(gw.ENV_PREFER, raw)
    assert gw.prefer() is None


# ── discovery ────────────────────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, _n=-1):
        return self._body


def test_get_json_allows_http_to_this_machine_only(monkeypatch):
    seen = []
    monkeypatch.setattr(md, "_OPENER", SimpleNamespace(open=lambda req, timeout: seen.append(req.full_url) or _Resp(b'{"data": []}')))
    assert md._get_json("http://127.0.0.1:4000/v1/models", {}, 1) == {"data": []}
    with pytest.raises(md.FetchError):
        md._get_json("http://gw.example.test/v1/models", {}, 1)
    assert seen == ["http://127.0.0.1:4000/v1/models"]


def test_fetch_asks_the_gateway_with_a_bearer_header(monkeypatch):
    _configure(monkeypatch, url=URL + "/")
    calls = []
    monkeypatch.setattr(md, "_get_json", lambda url, h, t: calls.append((url, h)) or _body())
    models, endpoint = md.fetch_provider_models("gateway", KEY)
    assert calls == [(URL + "/models", {"Authorization": f"Bearer {KEY}"})]
    assert endpoint == "gateway /models" and {m.id for m in models} == set(GW_IDS)
    assert KEY not in calls[0][0]


def test_fetch_without_a_url_is_malformed_not_a_request_to_a_vendor(monkeypatch):
    monkeypatch.setenv(gw.ENV_KEY, KEY)
    monkeypatch.setattr(md, "_get_json", lambda *a: (_ for _ in ()).throw(AssertionError("no request may be made")))
    with pytest.raises(md.FetchError) as ei:
        md.fetch_provider_models("gateway", KEY)
    assert ei.value.kind == "malformed" and "gateway URL" in ei.value.message


def test_refresh_reports_each_gateway_state(monkeypatch):
    assert md.refresh(["gateway"])["gateway"]["status"] == "no_key"
    monkeypatch.setenv(gw.ENV_KEY, KEY)
    r = md.refresh(["gateway"])["gateway"]
    assert r["status"] == "failed" and "gateway URL" in r["detail"]
    monkeypatch.setenv(gw.ENV_URL, URL)
    monkeypatch.setattr(md, "_get_json", lambda *a: (_ for _ in ()).throw(md.FetchError("rejected", "HTTP 401")))
    assert md.refresh(["gateway"])["gateway"] == {"status": "rejected", "count": 0, "detail": "key rejected"}
    monkeypatch.setattr(md, "_get_json", lambda *a: _body())
    assert md.refresh(["gateway"])["gateway"] == {"status": "ok", "count": len(GW_IDS), "detail": "gateway /models"}


def test_the_cache_holds_neither_the_url_nor_the_key(monkeypatch):
    _configure(monkeypatch, url="https://gw.example.test/tok-123/v1")
    _seed(monkeypatch)
    blob = json.dumps(ps.load())
    assert KEY not in blob and "gw.example.test" not in blob and "tok-123" not in blob


def test_the_cache_goes_stale_when_the_url_changes(monkeypatch):
    _configure(monkeypatch)
    _seed(monkeypatch)
    entry = md.load_entry("gateway")
    assert md.entry_is_fresh("gateway", entry)
    monkeypatch.setenv(gw.ENV_URL, "https://other.example.test/v1")
    assert not md.entry_is_fresh("gateway", entry)
    monkeypatch.setenv(gw.ENV_URL, URL)
    assert md.entry_is_fresh("gateway", entry)


# ── tiering of namespaced ids and the per-tier pick ──────────────────────────────────────────────

def test_namespaced_ids_are_tiered_and_unknowns_are_left_alone(monkeypatch):
    _configure(monkeypatch)
    _seed(monkeypatch)
    tiers = {r["id"]: r["tier"] for r in md.load_entry("gateway")["models"]}
    assert tiers["anthropic/claude-haiku-4.5"] == "STANDARD"
    assert tiers["anthropic/claude-sonnet-4.5"] == "COMPLEX"
    assert tiers["anthropic/claude-opus-4.6"] == "EXPERT"
    assert tiers["google/gemini-2.5-flash"] == "STANDARD" and tiers["google/gemini-2.5-pro"] == "COMPLEX"
    assert tiers["openai/gpt-4o-mini"] == "STANDARD" and tiers["gpt-4o"] == "COMPLEX"
    assert tiers["x-ai/grok-4.20"] == "COMPLEX"
    assert tiers["cohere/embed-v4"] is None and tiers["mancer/weaver"] is None


def _pick(tier, cfg=None):
    return clf.resolve_model("gateway", tier, "", cfg if cfg is not None else {})


def test_without_prefer_or_a_pin_the_gateway_has_no_model(monkeypatch):
    _configure(monkeypatch)
    _seed(monkeypatch)
    assert [_pick(t) for t in ("STANDARD", "COMPLEX", "EXPERT")] == ["", "", ""]


def test_prefer_picks_the_newest_per_tier_inside_that_vendor(monkeypatch):
    _configure(monkeypatch, prefer="anthropic/")
    _seed(monkeypatch)
    assert _pick("STANDARD") == "anthropic/claude-haiku-5.5"
    assert _pick("COMPLEX") == "anthropic/claude-sonnet-4.5"
    assert _pick("EXPERT") == "anthropic/claude-opus-4.6"


def test_prefer_can_be_another_vendor_or_a_bare_family(monkeypatch):
    _configure(monkeypatch, prefer="google/")
    _seed(monkeypatch)
    assert (_pick("STANDARD"), _pick("COMPLEX"), _pick("EXPERT")) == ("google/gemini-2.5-flash", "google/gemini-2.5-pro", "")
    monkeypatch.setenv(gw.ENV_PREFER, "GPT-")
    assert _pick("COMPLEX") == "gpt-4o"


def test_on_a_version_tie_the_plain_model_beats_its_variants(monkeypatch):
    """Real gateways list gpt-5, gpt-5-codex and gpt-5-search-api side by side: the tie must not go to the longest id."""
    ids = ("gpt-5", "gpt-5-codex", "gpt-5-search-api", "x-ai/grok-4.20", "x-ai/grok-4.20-multi-agent")
    _configure(monkeypatch, prefer="gpt-")
    _seed(monkeypatch, ids)
    assert _pick("COMPLEX") == "gpt-5"
    monkeypatch.setenv(gw.ENV_PREFER, "x-ai/")
    assert _pick("COMPLEX") == "x-ai/grok-4.20"
    # a genuinely newer model still wins over a plain older one, variant or not
    _seed(monkeypatch, ids + ("gpt-6-codex",))
    monkeypatch.setenv(gw.ENV_PREFER, "gpt-")
    assert _pick("COMPLEX") == "gpt-6-codex"


def test_a_pin_wins_and_needs_no_prefer(monkeypatch):
    _configure(monkeypatch)
    _seed(monkeypatch)
    cfg = {"model_overrides": {"pin": {"gateway": {"EXPERT": "vendor/pinned-model"}}}}
    assert _pick("EXPERT", cfg) == "vendor/pinned-model"
    assert _pick("STANDARD", cfg) == ""
    monkeypatch.setenv(gw.ENV_PREFER, "anthropic/")
    assert _pick("EXPERT", cfg) == "vendor/pinned-model"


def test_a_stale_catalogue_gives_no_model(monkeypatch):
    _configure(monkeypatch, prefer="anthropic/")
    _seed(monkeypatch)
    monkeypatch.setenv(gw.ENV_URL, "https://other.example.test/v1")
    assert _pick("STANDARD") == ""


def test_a_denied_model_is_not_picked_again(monkeypatch):
    _configure(monkeypatch, prefer="anthropic/")
    _seed(monkeypatch)
    md.deny("gateway", "anthropic/claude-haiku-5.5")
    assert _pick("STANDARD") == "anthropic/claude-haiku-4.5"


# ── `cognirepo models` ───────────────────────────────────────────────────────────────────────────

def test_models_list_says_why_there_is_no_model_and_never_prints_the_url(monkeypatch, capsys):
    import interface.cli.main as cli
    _configure(monkeypatch, url="https://gw.example.test/tok-123/v1")
    _seed(monkeypatch)
    args = SimpleNamespace(models_command="list", provider="gateway", stale=False, json=False)
    assert cli._cmd_models(args) == 0
    out = capsys.readouterr().out
    assert "no model (none)" in out and "COGNIREPO_GATEWAY_PREFER" in out
    assert "anthropic/claude-opus-4.6" in out and "gw.example.test" not in out and "tok-123" not in out
    monkeypatch.setenv(gw.ENV_PREFER, "anthropic/")
    assert cli._cmd_models(args) == 0
    out = capsys.readouterr().out
    assert "STANDARD -> anthropic/claude-haiku-5.5 (discovered)" in out and "COGNIREPO_GATEWAY_PREFER" not in out


# ── a real stub gateway on loopback: the wire format ─────────────────────────────────────────────

class _Stub(http.server.BaseHTTPRequestHandler):
    seen: list = []
    agents: list = []  # User-Agent of every GET
    reply_content: str | None = "pong"
    finish_reason = "stop"
    output_tokens = 1

    def log_message(self, *_a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        _Stub.seen.append(("GET", self.path, self.headers.get("Authorization"), None))
        agent = self.headers.get("User-Agent", "")
        _Stub.agents.append(agent)
        if agent.startswith("Python-urllib"):  # what Cloudflare-fronted gateways (aicredits.in) really answer
            return self._send(403, "error code: 1010")
        if self.path == "/v1/models":
            self._send(200, _body())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        _Stub.seen.append(("POST", self.path, self.headers.get("Authorization"), body))
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": "not found"})
        return self._send(200, {
            "id": "c1", "object": "chat.completion", "created": 0, "model": body.get("model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": self.reply_content},
                         "finish_reason": self.finish_reason}],
            "usage": {"prompt_tokens": 3, "completion_tokens": self.output_tokens,
                      "total_tokens": 3 + self.output_tokens},
        })


@pytest.fixture
def stub_gateway(monkeypatch):
    _Stub.seen = []
    _Stub.agents = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for var in ("NO_PROXY", "no_proxy"):  # a CI proxy must not intercept loopback
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    _configure(monkeypatch, url=url, prefer="anthropic/")
    yield url
    server.shutdown()
    server.server_close()


def test_refresh_pick_and_call_against_a_local_gateway(stub_gateway):
    import interface.cli.main as cli
    assert cli._cmd_models(SimpleNamespace(models_command="refresh", provider="gateway", timeout=5.0)) == 0
    chosen = _pick("STANDARD")
    assert chosen == "anthropic/claude-haiku-5.5"

    resp = gateway_adapter.call("ping", "be brief", [], model_id=chosen, max_tokens=7)
    assert resp.text == "pong" and resp.provider == "gateway" and resp.model == chosen

    gets = [s for s in _Stub.seen if s[0] == "GET"]
    posts = [s for s in _Stub.seen if s[0] == "POST"]
    assert gets == [("GET", "/v1/models", f"Bearer {KEY}", None)]
    assert len(posts) == 1 and posts[0][1] == "/v1/chat/completions" and posts[0][2] == f"Bearer {KEY}"
    sent = posts[0][3]
    assert sent["model"] == chosen and sent["max_tokens"] == 7
    assert sent["messages"][0] == {"role": "system", "content": "be brief"}
    assert sent["messages"][-1] == {"role": "user", "content": "ping"}


@pytest.mark.parametrize("content", [None, "The first part of the answer"])
def test_route_marks_token_limited_gateway_reply_incomplete(stub_gateway, monkeypatch, content):
    model = "openai/gpt-4o-mini"
    monkeypatch.setattr(_Stub, "reply_content", content)
    monkeypatch.setattr(_Stub, "finish_reason", "length")
    monkeypatch.setattr(_Stub, "output_tokens", 150)
    monkeypatch.setattr(router, "classify", lambda *a, **kw: SimpleNamespace(
        tier="STANDARD", provider="gateway", model=model, score=1.0))
    monkeypatch.setattr(router, "build_context", lambda *a, **kw: SimpleNamespace(
        system_prompt="", tool_manifest=[], ast_hits=[]))
    monkeypatch.setattr(router, "_post_process", lambda **kw: None)

    result = router.route("Write a long answer", force_model=model, max_tokens=150)

    assert "token limit" in result.error
    assert result.response.text == (content or "")
    assert result.response.usage["output_tokens"] == 150


def test_discovery_does_not_introduce_itself_as_python_urllib(stub_gateway):
    """aicredits.in sits behind Cloudflare, which answers urllib's default agent with 403 'error code: 1010'. Discovery
    reported that as a rejected key, so a valid key looked wrong. Found against the real gateway; the stub now behaves alike."""
    report = md.refresh(["gateway"])["gateway"]
    assert report["status"] == "ok", report
    assert _Stub.agents and all(a.startswith("cognirepo/") for a in _Stub.agents)


def test_test_connection_uses_the_chosen_model(stub_gateway):
    import interface.cli.main as cli
    assert md.refresh(["gateway"])["gateway"]["status"] == "ok"
    result = cli._test_connection("gateway")
    assert result["status"] == "ok" and result["response"] == "pong"
    assert result["model"] == "anthropic/claude-haiku-5.5"


def test_test_connection_explains_a_missing_model(monkeypatch):
    import interface.cli.main as cli
    _configure(monkeypatch)  # no prefer, nothing cached
    result = cli._test_connection("gateway")
    assert result["status"] == "error" and "no model chosen" in result["error"]


# ── adapter guards ───────────────────────────────────────────────────────────────────────────────

def test_adapter_refuses_without_a_usable_gateway(monkeypatch):
    with pytest.raises(ModelCallError) as ei:
        gateway_adapter.call("q", "s", [], model_id="vendor/m")
    assert "no usable gateway" in ei.value.message and gw.ENV_URL in ei.value.message
    monkeypatch.setenv(gw.ENV_KEY, KEY)
    monkeypatch.setenv(gw.ENV_URL, "http://gw.example.test/v1")  # remote http: never sent anything
    with pytest.raises(ModelCallError):
        gateway_adapter.call("q", "s", [], model_id="vendor/m")


def test_adapter_refuses_without_a_model(monkeypatch):
    _configure(monkeypatch)
    with pytest.raises(ModelCallError) as ei:
        gateway_adapter.call("q", "s", [], model_id="")
    assert "no model chosen" in ei.value.message


def test_a_gateway_call_does_not_log_the_url(stub_gateway, caplog):
    """The HTTP client logs 'HTTP Request: POST <full url>' at INFO. Seen on the real CLI: the whole gateway URL, which may
    hold a token in its path, reached stderr although the docs promise it is never logged."""
    names = ("httpx", "httpx2", "httpcore", "httpcore2", "openai")
    saved = {n: logging.getLogger(n).level for n in names}
    try:
        for n in names:
            logging.getLogger(n).setLevel(logging.INFO)  # what the CLI's own log setup amounts to
        with caplog.at_level(logging.INFO):
            gateway_adapter.call("ping", "s", [], model_id="vendor/m", max_tokens=7)
        assert stub_gateway not in caplog.text and "/chat/completions" not in caplog.text
    finally:
        for n, level in saved.items():
            logging.getLogger(n).setLevel(level)


def test_adapter_says_how_to_install_the_openai_package(monkeypatch):
    """Found on a pipx install, which ships without the optional openai package: the call died with a bare
    'pip install openai', which does not work inside a pipx venv."""
    import importlib.util
    _configure(monkeypatch)
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: None if name == "openai" else real(name, *a, **k))
    with pytest.raises(ModelCallError) as ei:
        gateway_adapter.call("q", "s", [], model_id="vendor/m")
    assert ei.value.provider == "gateway" and "pipx inject cognirepo openai" in ei.value.message


def test_a_gateway_http_error_is_a_model_call_error_with_its_status(stub_gateway):
    """The stub 404s unknown paths; a wrong model/URL must surface as ModelCallError so the router can fall back."""
    import intelligence.orchestrator.model_adapters.openai_adapter as oa
    with pytest.raises(ModelCallError) as ei:
        oa.call("q", "s", [], model_id="vendor/m", _api_key=KEY, _base_url=stub_gateway + "/nope", _provider="gateway")
    assert ei.value.provider == "gateway" and ei.value.status_code == 404


# ── streaming: stream_route only swaps the primary for a CLI today; the gateway joins that rule ───

def _repo_config(**cfg):
    with open(get_path("config.json"), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)


def _stream_with(monkeypatch, clf_provider, tier="COMPLEX"):
    seen = {}
    clf_result = SimpleNamespace(tier=tier, provider=clf_provider, model="primary-model", score=1.0)
    monkeypatch.setattr(router, "classify", lambda *a, **k: clf_result)
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


def test_stream_route_uses_the_gateway_when_the_primary_has_no_key(monkeypatch):
    _configure(monkeypatch)
    _repo_config(model_overrides={"pin": {"gateway": {"COMPLEX": "vendor/pinned-model"}}})
    seen = _stream_with(monkeypatch, "anthropic")
    assert (seen["provider"], seen["model_id"]) == ("gateway", "vendor/pinned-model")
    assert seen["response"].provider == "gateway"


def test_stream_route_never_swaps_in_a_gateway_that_has_no_model(monkeypatch):
    _configure(monkeypatch)  # no pin, no prefer
    seen = _stream_with(monkeypatch, "anthropic")
    assert seen["provider"] == "anthropic"  # unchanged: the primary is tried and reports its own error


def test_stream_route_keeps_the_primary_when_it_has_a_key(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _repo_config(model_overrides={"pin": {"gateway": {"COMPLEX": "vendor/pinned-model"}}})
    assert _stream_with(monkeypatch, "anthropic")["provider"] == "anthropic"
