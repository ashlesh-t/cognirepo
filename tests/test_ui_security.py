# pylint: disable=missing-docstring, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_ui_security.py — control-API security primitives (COGNIREPO-129)."""
import pytest

from interface.ui import security as sec


class TestBind:
    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.5"])
    def test_loopback_ok(self, host):
        assert sec.validate_bind_host(host) is None

    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "10.0.0.1", "example.com", "::"])
    def test_non_loopback_refused(self, host):
        with pytest.raises(sec.UnsafeBindError):
            sec.validate_bind_host(host)

    def test_unsafe_flag_allows_with_loud_warning(self):
        warning = sec.validate_bind_host("0.0.0.0", unsafe=True)
        assert warning and "WARNING" in warning and "NON-LOOPBACK" in warning


class TestToken:
    def test_tokens_are_random_and_long(self):
        a, b = sec.new_token(), sec.new_token()
        assert a != b and len(a) >= 40

    def test_constant_time_compare(self, monkeypatch):
        calls = []
        real = sec.hmac.compare_digest
        monkeypatch.setattr(sec.hmac, "compare_digest", lambda x, y: calls.append(1) or real(x, y))
        assert sec.tokens_equal("abc", "abc") and not sec.tokens_equal("abd", "abc")
        assert len(calls) == 2  # always goes through compare_digest

    @pytest.mark.parametrize("supplied", [None, "", "x", "é\udcff"])
    def test_never_raises_on_odd_input(self, supplied):
        assert sec.tokens_equal(supplied, "expected") is False

    def test_extract_prefers_bearer_then_cookie(self):
        assert sec.extract_token({"authorization": "Bearer T1"}, {sec.COOKIE_NAME: "T2"}) == "T1"
        assert sec.extract_token({}, {sec.COOKIE_NAME: "T2"}) == "T2"
        assert sec.extract_token({"authorization": "Basic zzz"}, {}) is None


class TestHostOrigin:
    def cfg(self, **kw):
        return sec.SecurityConfig(token="t", port=8765, **kw)

    def test_host_exact_match_only(self):
        c = self.cfg()
        assert c.host_ok("127.0.0.1:8765") and c.host_ok("localhost:8765")
        for bad in (None, "", "evil.com", "evil.com:8765", "127.0.0.1", "127.0.0.1:1", "127.0.0.1:8765.evil.com"):
            assert not c.host_ok(bad)

    def test_origin_allowlist(self):
        c = self.cfg()
        assert c.origin_ok(None)  # non-browser client
        assert c.origin_ok("http://127.0.0.1:8765") and c.origin_ok("http://localhost:8765/")
        for bad in ("null", "https://evil.com", "http://127.0.0.1:9999", "http://127.0.0.1:8765.evil.com"):
            assert not c.origin_ok(bad)

    def test_extra_origin_must_be_exact_never_wildcard(self):
        assert self.cfg(extra_origins=("http://127.0.0.1:5173",)).origin_ok("http://127.0.0.1:5173")
        for bad in ("*", "evil.com", "ftp://x"):
            with pytest.raises(ValueError):
                self.cfg(extra_origins=(bad,))


class TestLimiter:
    def make(self):
        now = [1000.0]
        return sec.AttemptLimiter(max_failures=3, base_lockout=10, max_lockout=35, clock=lambda: now[0]), now

    def test_locks_after_max_failures_then_backs_off(self):
        lim, now = self.make()
        for _ in range(2):
            lim.record_failure("c")
        assert lim.retry_after("c") == 0
        lim.record_failure("c")
        assert lim.retry_after("c") == pytest.approx(10)
        now[0] += 10.1
        assert lim.retry_after("c") == 0
        for _ in range(3):
            lim.record_failure("c")
        assert lim.retry_after("c") == pytest.approx(20)  # doubled
        now[0] += 21
        for _ in range(3):
            lim.record_failure("c")
        assert lim.retry_after("c") == pytest.approx(35)  # capped (would be 40)

    def test_success_clears_and_clients_are_independent(self):
        lim, _ = self.make()
        for _ in range(3):
            lim.record_failure("a")
        assert lim.retry_after("a") > 0 and lim.retry_after("b") == 0
        lim.record_success("a")
        assert lim.retry_after("a") == 0
