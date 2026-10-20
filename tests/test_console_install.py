# pylint: disable=missing-docstring, protected-access, redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_console_install.py — git-managed console under <global>/console (#215)."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess

import pytest
from starlette.testclient import TestClient

from interface.ui import cli as ui_cli
from interface.ui import console_install as ci
from interface.ui import security as sec
from interface.ui.app import create_app
from interface.ui.audit import AuditLog
from interface.ui.status import API_VERSION

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_bundle(root, *, api_major=None, version="1.0.1", extra=None):
    files = {"index.html": b"<html>engram</html>", "assets/app.js": b"console.log(1)"}
    files.update(extra or {})
    for rel, data in files.items():
        p = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
    man = {"name": "cognirepo-console", "version": version,
           "api_major": int(API_VERSION) if api_major is None else api_major,
           "files": {rel: _sha(d) for rel, d in files.items()}}
    with open(os.path.join(root, ci.MANIFEST), "w", encoding="utf-8") as f:
        json.dump(man, f)


PORT = 8765


def make_client(tmp_path):
    cfg = sec.SecurityConfig(token="t" * 40, port=PORT, limiter=sec.AttemptLimiter(max_failures=3, base_lockout=60))
    app = create_app(cfg, str(tmp_path), AuditLog(str(tmp_path / "ui" / "audit.log")))
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.fixture
def source_repo(tmp_path, monkeypatch):
    """A local repo with a `release` branch standing in for the console repo."""
    src = tmp_path / "console-src"
    src.mkdir()
    git(src, "init", "-q", "-b", "release")
    write_bundle(str(src))
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "build")
    monkeypatch.setenv("COGNIREPO_CONSOLE_REPO", str(src))
    return src


class TestValidate:
    def test_good_bundle(self, tmp_path):
        write_bundle(str(tmp_path))
        bundle, reason = ci.validate(str(tmp_path))
        assert reason == "" and bundle.version == "1.0.1"
        assert bundle.files == {"index.html", "assets/app.js"}

    def test_tampered_file_refused(self, tmp_path):
        write_bundle(str(tmp_path))
        (tmp_path / "assets" / "app.js").write_text("evil()")
        bundle, reason = ci.validate(str(tmp_path))
        assert bundle is None and "assets/app.js" in reason and "sha256" in reason

    def test_missing_listed_file_refused(self, tmp_path):
        write_bundle(str(tmp_path))
        (tmp_path / "assets" / "app.js").unlink()
        assert "missing" in ci.validate(str(tmp_path))[1]

    def test_api_major_mismatch_refused(self, tmp_path):
        write_bundle(str(tmp_path), api_major=99)
        bundle, reason = ci.validate(str(tmp_path))
        assert bundle is None and "99" in reason

    @pytest.mark.parametrize("rel", ["../escape.js", "/abs.js", "a//b.js", ".git/config", "a\\b.js"])
    def test_unsafe_manifest_paths_refused(self, tmp_path, rel):
        write_bundle(str(tmp_path))
        man = json.loads((tmp_path / ci.MANIFEST).read_text())
        man["files"][rel] = "0" * 64
        (tmp_path / ci.MANIFEST).write_text(json.dumps(man))
        bundle, reason = ci.validate(str(tmp_path))
        assert bundle is None and "unsafe" in reason

    def test_symlink_refused(self, tmp_path):
        outside = tmp_path / "outside.js"
        outside.write_bytes(b"console.log(1)")
        write_bundle(str(tmp_path / "c"))
        target = tmp_path / "c" / "assets" / "app.js"
        target.unlink()
        os.symlink(outside, target)
        assert "symlink" in ci.validate(str(tmp_path / "c"))[1]

    def test_missing_or_garbage_manifest(self, tmp_path):
        assert "missing" in ci.validate(str(tmp_path))[1]
        (tmp_path / ci.MANIFEST).write_text("{nope")
        assert "not valid JSON" in ci.validate(str(tmp_path))[1]


class TestEnsure:
    def test_clones_validates_and_installs(self, source_repo):
        out = ci.ensure()
        assert out.status == "fetched" and out.bundle.version == "1.0.1"
        assert os.path.isfile(os.path.join(ci.console_dir(), "index.html"))
        assert not [d for d in os.listdir(os.path.dirname(ci.console_dir())) if ".tmp-" in d]

    def test_second_call_is_offline(self, source_repo, monkeypatch):
        ci.ensure()
        monkeypatch.setattr(ci, "_clone", lambda *a: pytest.fail("must not touch the network"))
        assert ci.ensure().status == "ready"

    def test_autofetch_off_installs_nothing(self, source_repo):
        assert ci.ensure(autofetch=False).status == "disabled"
        assert not os.path.exists(ci.console_dir())

    def test_env_switch_disables_autofetch(self, source_repo, monkeypatch):
        monkeypatch.setenv("COGNIREPO_CONSOLE_AUTOFETCH", "0")
        assert ci.ensure().status == "disabled"

    def test_global_config_switch(self, source_repo):
        os.makedirs(ci.get_global_dir(), exist_ok=True)
        with open(os.path.join(ci.get_global_dir(), "config.json"), "w", encoding="utf-8") as f:
            json.dump({"ui": {"console_autofetch": False}}, f)
        assert ci.ensure().status == "disabled"

    def test_no_git_reported(self, source_repo, monkeypatch):
        monkeypatch.setattr(ci.shutil, "which", lambda *_: None)
        assert ci.ensure().status == "no-git"

    def test_unreachable_repo_leaves_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNIREPO_CONSOLE_REPO", str(tmp_path / "does-not-exist"))
        out = ci.ensure()
        assert out.status == "failed" and out.bundle is None
        assert not os.path.exists(ci.console_dir())
        assert not [d for d in os.listdir(ci.get_global_dir()) if d.startswith("console")]

    def test_tampered_remote_is_refused_and_not_installed(self, source_repo):
        (source_repo / "assets" / "app.js").write_text("evil()")
        git(source_repo, "commit", "-qam", "tamper")
        out = ci.ensure()
        assert out.status == "invalid" and "sha256" in out.message
        assert not os.path.exists(ci.console_dir())

    def test_incompatible_api_major_not_installed(self, source_repo):
        write_bundle(str(source_repo), api_major=7)
        git(source_repo, "commit", "-qam", "v7")
        assert ci.ensure().status == "invalid"
        assert not os.path.exists(ci.console_dir())

    def test_broken_install_is_not_overwritten(self, source_repo):
        ci.ensure()
        with open(os.path.join(ci.console_dir(), "index.html"), "w", encoding="utf-8") as f:
            f.write("local edit")
        out = ci.ensure()
        assert out.status == "invalid"
        assert open(os.path.join(ci.console_dir(), "index.html"), encoding="utf-8").read() == "local edit"

    @pytest.mark.parametrize("bad", ["--upload-pack=touch /tmp/pwned", "-c"])
    def test_option_like_repo_refused(self, bad, monkeypatch):
        monkeypatch.setenv("COGNIREPO_CONSOLE_REPO", bad)
        out = ci.ensure()
        assert out.status == "failed" and "'-'" in out.message

    def test_ext_transport_is_not_allowed(self, monkeypatch):
        monkeypatch.setenv("COGNIREPO_CONSOLE_REPO", "ext::sh -c 'touch /tmp/cognirepo-ext-pwned'")
        assert ci.ensure().status == "failed"
        assert not os.path.exists("/tmp/cognirepo-ext-pwned")


class TestServing:
    def test_serves_manifest_files_only(self, source_repo, tmp_path):
        ci.ensure()
        # something in the tree that the manifest does not list, and git metadata
        with open(os.path.join(ci.console_dir(), "notes.txt"), "w", encoding="utf-8") as f:
            f.write("secret")
        client = make_client(tmp_path)
        assert client.get("/").text == "<html>engram</html>"
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/notes.txt").status_code == 404
        assert client.get("/.git/config").status_code == 404
        assert client.get("/%2e%2e/notes.txt").status_code == 404

    def test_invalid_install_falls_back_to_landing_page(self, source_repo, tmp_path):
        ci.ensure()
        with open(os.path.join(ci.console_dir(), "index.html"), "w", encoding="utf-8") as f:
            f.write("tampered")
        client = make_client(tmp_path)
        assert "tampered" not in client.get("/").text

    def test_api_still_served_next_to_console(self, source_repo, tmp_path):
        ci.ensure()
        client = make_client(tmp_path)
        assert client.get("/api/v1/status").status_code in (200, 401)


class TestCli:
    def args(self, **kw):
        base = dict(no_console_fetch=False)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_ui_installs_before_spawning(self, source_repo, capsys):
        ui_cli._ensure_console(self.args())
        assert "installed console 1.0.1" in capsys.readouterr().out
        assert ci.resolve()[0] is not None

    def test_no_console_fetch_flag(self, source_repo, capsys):
        ui_cli._ensure_console(self.args(no_console_fetch=True))
        assert ci.resolve()[0] is None and capsys.readouterr().out == ""

    def test_failure_is_reported_not_raised(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("COGNIREPO_CONSOLE_REPO", str(tmp_path / "nope"))
        ui_cli._ensure_console(self.args())
        assert "could not fetch the console" in capsys.readouterr().err

    def test_console_installed_sees_git_bundle(self, source_repo, monkeypatch):
        monkeypatch.setattr("importlib.util.find_spec", lambda *_: None)
        assert ui_cli.console_installed() is False
        ci.ensure()
        assert ui_cli.console_installed() is True
