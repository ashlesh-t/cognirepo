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
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "tag.gpgsign=false",
                    "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True)


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


def release(src, version, *, api_major=None, orphan=False, extra=None, msg="build"):
    """Publish a new build on the source repo's `release` branch (CI-style orphan rebuild if asked)."""
    if orphan:
        git(src, "checkout", "-q", "--orphan", "tmp")
        git(src, "rm", "-rqf", "--ignore-unmatch", ".")
    write_bundle(str(src), api_major=api_major, version=version, extra=extra)
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", msg)
    if orphan:
        git(src, "branch", "-M", "release")


def served(tmp_path, path="/"):
    return make_client(tmp_path).get(path)


def index_text():
    with open(os.path.join(ci.console_dir(), "index.html"), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def installed(source_repo):
    assert ci.ensure().status == "fetched"
    return source_repo


class TestUpdate:
    def test_not_managed(self):
        assert ci.update().status == "not-managed"

    def test_already_current_is_a_noop(self, installed):
        out = ci.update()
        assert out.status == "current" and "already current" in out.message
        assert not os.path.exists(ci.prev_dir())

    def test_check_reports_without_changing_anything(self, installed):
        release(installed, "1.1.0", extra={"index.html": b"<html>v2</html>"})
        before = index_text()
        out = ci.update(check_only=True)
        assert out.status == "available" and out.old == "1.0.1" and out.new == "1.1.0"
        assert index_text() == before and not os.path.exists(ci.prev_dir())

    def test_update_swaps_and_keeps_previous(self, installed):
        release(installed, "1.1.0", extra={"index.html": b"<html>v2</html>"})
        out = ci.update()
        assert out.status == "updated" and (out.old, out.new) == ("1.0.1", "1.1.0")
        assert "1.0.1 -> 1.1.0" in out.message
        assert index_text() == "<html>v2</html>"
        assert ci.validate(ci.prev_dir())[0].version == "1.0.1"
        assert ci.validate(ci.console_dir())[0].version == "1.1.0"
        assert not [d for d in os.listdir(ci.get_global_dir()) if ".new-" in d]

    def test_update_survives_orphan_rebuild(self, installed):
        release(installed, "2.0.0", orphan=True, extra={"index.html": b"<html>orphan</html>"})
        assert ci.update().status == "updated"
        assert index_text() == "<html>orphan</html>"

    def test_files_dropped_by_the_new_build_are_gone(self, installed):
        git(installed, "rm", "-q", "assets/app.js")
        man = json.loads((installed / ci.MANIFEST).read_text())
        del man["files"]["assets/app.js"]
        man["version"] = "1.1.0"
        (installed / ci.MANIFEST).write_text(json.dumps(man))
        git(installed, "commit", "-qam", "drop")
        assert ci.update().status == "updated"
        assert not os.path.exists(os.path.join(ci.console_dir(), "assets", "app.js"))

    def test_incompatible_api_major_refused_and_untouched(self, installed):
        release(installed, "3.0.0", api_major=2, extra={"index.html": b"<html>v3</html>"})
        out = ci.update()
        assert out.status == "incompatible" and "API major 2" in out.message and "serves API major '1'" in out.message
        assert index_text() == "<html>engram</html>" and not os.path.exists(ci.prev_dir())
        assert ci.update(check_only=True).status == "incompatible"

    def test_tampered_remote_refused_and_untouched(self, installed):
        (installed / "assets" / "app.js").write_text("evil()")
        git(installed, "commit", "-qam", "tamper")
        out = ci.update()
        assert out.status == "failed" and "sha256" in out.message
        assert ci.validate(ci.console_dir())[0].version == "1.0.1" and not os.path.exists(ci.prev_dir())

    def test_failed_fetch_leaves_current_build_untouched(self, installed):
        ci._rmtree(str(installed))      # a git checkout's read-only objects defeat plain shutil.rmtree on Windows
        out = ci.update()
        assert out.status == "failed" and "could not fetch" in out.message
        assert ci.validate(ci.console_dir())[0].version == "1.0.1"
        assert not [d for d in os.listdir(ci.get_global_dir()) if ".new-" in d]

    def test_ref_pin_to_a_tag(self, installed, monkeypatch):
        git(installed, "tag", "v1")
        release(installed, "1.1.0", extra={"index.html": b"<html>v2</html>"})
        monkeypatch.setenv("COGNIREPO_CONSOLE_REF", "v1")
        assert ci.update().status == "current"
        monkeypatch.setenv("COGNIREPO_CONSOLE_REF", "release")
        assert ci.update().status == "updated"

    def test_option_like_ref_refused(self, installed, monkeypatch):
        monkeypatch.setenv("COGNIREPO_CONSOLE_REF", "--upload-pack=x")
        assert ci.update().status == "failed"

    def test_no_git(self, installed, monkeypatch):
        monkeypatch.setattr(ci.shutil, "which", lambda *_: None)
        assert ci.update().status == "failed"

    def test_running_server_picks_up_update_without_restart(self, installed, tmp_path):
        client = make_client(tmp_path)
        assert client.get("/").text == "<html>engram</html>"
        assert client.get("/new.js").status_code == 404
        release(installed, "1.1.0", extra={"index.html": b"<html>v2</html>", "new.js": b"1"})
        assert ci.update().status == "updated"
        assert client.get("/").text == "<html>v2</html>"
        assert client.get("/new.js").text == "1"
        assert ci.rollback().status == "rolled-back"
        assert client.get("/").text == "<html>engram</html>"
        assert client.get("/new.js").status_code == 404


class TestRollback:
    def test_no_previous(self, installed):
        assert ci.rollback().status == "no-previous"

    def test_restores_previous_build(self, installed):
        release(installed, "1.1.0", extra={"index.html": b"<html>v2</html>"})
        ci.update()
        out = ci.rollback()
        assert out.status == "rolled-back" and "1.1.0 -> 1.0.1" in out.message
        assert index_text() == "<html>engram</html>"

    def test_twice_toggles(self, installed):
        release(installed, "1.1.0", extra={"index.html": b"<html>v2</html>"})
        ci.update()
        ci.rollback()
        ci.rollback()
        assert index_text() == "<html>v2</html>"
        assert not [d for d in os.listdir(ci.get_global_dir()) if ".rollback-" in d]

    def test_corrupt_previous_refused_and_current_kept(self, installed):
        release(installed, "1.1.0", extra={"index.html": b"<html>v2</html>"})
        ci.update()
        with open(os.path.join(ci.prev_dir(), "index.html"), "w", encoding="utf-8") as f:
            f.write("bad")
        out = ci.rollback()
        assert out.status == "failed" and "sha256" in out.message
        assert index_text() == "<html>v2</html>"


class TestUpdateCli:
    def args(self, **kw):
        base = dict(update=True, check=False, rollback=False)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_update_prints_versions_and_undo_hint(self, installed, capsys, monkeypatch):
        monkeypatch.setattr(ui_cli, "read_session", lambda: None)
        release(installed, "1.1.0", extra={"index.html": b"<html>v2</html>"})
        assert ui_cli._update_console(self.args()) == 0
        out = capsys.readouterr().out
        assert "1.0.1 -> 1.1.0" in out and "--rollback" in out

    def test_running_server_gets_refresh_hint(self, installed, capsys, monkeypatch):
        monkeypatch.setattr(ui_cli, "read_session", lambda: {"port": 1})
        monkeypatch.setattr(ui_cli, "is_listening", lambda p: True)
        release(installed, "1.1.0", extra={"index.html": b"<html>v2</html>"})
        ui_cli._update_console(self.args())
        assert "refresh the page" in capsys.readouterr().out

    def test_check_does_not_change(self, installed, capsys):
        release(installed, "1.1.0", extra={"index.html": b"<html>v2</html>"})
        assert ui_cli._update_console(self.args(check=True)) == 0
        assert "1.0.1 -> 1.1.0" in capsys.readouterr().out and index_text() == "<html>engram</html>"

    def test_failure_exit_code(self, capsys):
        assert ui_cli._update_console(self.args()) == 1
        assert "not a git-managed install" in capsys.readouterr().err

    def test_check_and_rollback_together_refused(self, capsys):
        assert ui_cli._update_console(self.args(check=True, rollback=True)) == 2

    def test_check_without_update_refused(self, capsys, monkeypatch):
        monkeypatch.setattr(ui_cli, "_require_ui_extra", lambda: True)
        ns = argparse.Namespace(host="127.0.0.1", port=None, no_open=True, serve=False, stop=False,
                                unsafe_bind=False, allow_origin=None, update=False, check=True, rollback=False)
        assert ui_cli.run_ui(ns) == 2
        assert "only valid together with --update" in capsys.readouterr().err

    def test_rollback_via_cli(self, installed, capsys, monkeypatch):
        monkeypatch.setattr(ui_cli, "read_session", lambda: None)
        release(installed, "1.1.0", extra={"index.html": b"<html>v2</html>"})
        ui_cli._update_console(self.args())
        capsys.readouterr()
        assert ui_cli._update_console(self.args(rollback=True)) == 0
        assert "1.1.0 -> 1.0.1" in capsys.readouterr().out
