# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""GET /api/v1/insights[/report] and the `insights` service action (#147): fixed path, no file read."""
import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from interface.tools.insights import report_path
from interface.ui import security as sec
from interface.ui.app import create_app
from interface.ui.audit import AuditLog

PORT = 8766
TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
HTML = ('<!doctype html><html><head><meta name="cognirepo:generated-at" content="2026-10-12T10:00:00Z">'
        "<title>r</title></head><body>report</body></html>")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "myrepo"
    r.mkdir()
    return r


@pytest.fixture
def client(repo, tmp_path):
    cfg = sec.SecurityConfig(token=TOKEN, port=PORT, limiter=sec.AttemptLimiter(max_failures=3, base_lockout=60))
    app = create_app(cfg, str(repo), AuditLog(str(tmp_path / "audit.log")))
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        yield c


def _write_report(repo, text=HTML):
    path = report_path(str(repo))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class TestInfo:
    def test_missing_report(self, client):
        r = client.get("/api/v1/insights", headers=AUTH)
        assert r.status_code == 200 and r.json() == {"exists": False, "generated_at": None, "bytes": 0}

    def test_existing_report_uses_its_own_stamp(self, client, repo):
        _write_report(repo)
        body = client.get("/api/v1/insights", headers=AUTH).json()
        assert body == {"exists": True, "generated_at": "2026-10-12T10:00:00Z", "bytes": len(HTML)}

    def test_falls_back_to_mtime_without_a_stamp(self, client, repo):
        _write_report(repo, "<html>no meta</html>")
        assert client.get("/api/v1/insights", headers=AUTH).json()["generated_at"].startswith("20")

    def test_requires_a_token(self, client):
        assert client.get("/api/v1/insights").status_code == 401
        assert client.get("/api/v1/insights/report").status_code == 401


class TestReport:
    def test_served_sandboxed_and_read_only(self, client, repo):
        _write_report(repo)
        r = client.get("/api/v1/insights/report", headers=AUTH)
        assert r.status_code == 200 and "report" in r.text
        csp = r.headers["content-security-policy"]
        assert csp.startswith("sandbox") and "default-src 'none'" in csp and "script-src" not in csp
        assert r.headers["x-content-type-options"] == "nosniff"

    def test_download_flag_sends_an_attachment(self, client, repo):
        _write_report(repo)
        r = client.get("/api/v1/insights/report?download=1", headers=AUTH)
        assert "attachment" in r.headers["content-disposition"]

    def test_404_when_absent(self, client):
        r = client.get("/api/v1/insights/report", headers=AUTH)
        assert r.status_code == 404 and r.json() == {"error": "no_report"}

    def test_other_endpoints_keep_the_strict_default_csp(self, client):
        r = client.get("/api/v1/status", headers=AUTH)
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert r.headers["x-frame-options"] == "DENY"


class TestNoArbitraryFileRead:
    def test_client_supplied_paths_are_ignored(self, client, repo, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP SECRET")
        _write_report(repo)
        for q in ("?path=../secret.txt", f"?path={secret}", "?file=/etc/passwd", "?name=../../x"):
            r = client.get("/api/v1/insights/report" + q, headers=AUTH)
            assert "TOP SECRET" not in r.text and "root:" not in r.text
        assert client.get("/api/v1/insights/..%2f..%2fsecret.txt", headers=AUTH).status_code == 404

    def test_symlinked_report_is_refused(self, client, repo, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP SECRET")
        path = report_path(str(repo))
        os.makedirs(os.path.dirname(path))
        os.symlink(secret, path)
        r = client.get("/api/v1/insights/report", headers=AUTH)
        assert r.status_code == 404 and "TOP SECRET" not in r.text
        assert client.get("/api/v1/insights", headers=AUTH).json()["exists"] is False

    def test_symlinked_directory_is_refused(self, client, repo, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / os.path.basename(report_path(str(repo)))).write_text("TOP SECRET")
        os.makedirs(repo / ".claude")
        os.symlink(elsewhere, repo / ".claude" / "insights")
        r = client.get("/api/v1/insights/report", headers=AUTH)
        assert r.status_code == 404 and "TOP SECRET" not in r.text

    def test_oversized_file_is_refused(self, client, repo):
        _write_report(repo)
        with mock.patch("interface.ui.insights_view.MAX_REPORT_BYTES", 10):
            assert client.get("/api/v1/insights/report", headers=AUTH).status_code == 404


class TestRegenerate:
    def test_start_runs_the_fixed_insights_command_after_confirm(self, client, repo):
        with mock.patch("interface.ui.services.subprocess.Popen") as popen:
            popen.return_value.poll.return_value = None
            r = client.post("/api/v1/services/insights/start", headers=AUTH, json={"confirm": True})
        assert r.status_code == 200 and r.json()["state"] == "running" and r.json()["changed"] is True
        argv = popen.call_args.args[0]
        assert argv[1:] == ["-m", "interface.cli.main", "insights"]

    def test_second_start_while_running_is_a_noop(self, client):
        with mock.patch("interface.ui.services.subprocess.Popen") as popen:
            popen.return_value.poll.return_value = None
            client.post("/api/v1/services/insights/start", headers=AUTH, json={"confirm": True})
            r = client.post("/api/v1/services/insights/start", headers=AUTH, json={"confirm": True})
        assert r.json()["changed"] is False and popen.call_count == 1

    def test_needs_confirm(self, client):
        with mock.patch("interface.ui.services.subprocess.Popen") as popen:
            r = client.post("/api/v1/services/insights/start", headers=AUTH, json={})
        assert r.status_code == 400 and not popen.called

    def test_stop_is_not_supported(self, client):
        r = client.post("/api/v1/services/insights/stop", headers=AUTH, json={"confirm": True})
        assert r.status_code == 409 and r.json()["error"] == "not_stoppable"

    def test_listed_with_the_other_services(self, client):
        names = [s["name"] for s in client.get("/api/v1/services", headers=AUTH).json()]
        assert names == ["watcher", "metrics", "insights"]
