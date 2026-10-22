# pylint: disable=missing-docstring, protected-access, redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Regression tests for bugs the informational Windows CI job found. Each asserts behaviour that is also
true on POSIX, so they guard the fixes on every platform; on Windows they exercise the original failure."""
import asyncio
import os
import stat
import subprocess
import sys

import pytest

from core.config import generation
from interface.ui import console_install as ci
from interface.ui import repos


class TestConsoleServedOnWindowsPaths:
    """Starlette hands StaticFiles OS-separated paths ("assets\\app.js" on Windows); manifest keys use "/"."""

    def _files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ci.StaticFiles, "get_response", _marker_response)
        (tmp_path / "console.json").write_text("{}")
        bundle = ci.Bundle(path=str(tmp_path), version="1", files=frozenset({"index.html", "assets/app.js"}))
        sf = ci.ManifestStaticFiles(bundle)
        sf._allowed = bundle.files           # skip re-reading the (dummy) manifest
        sf._stamp = sf._stat()
        return sf

    def test_backslash_paths_match_the_manifest(self, tmp_path, monkeypatch):
        sf = self._files(tmp_path, monkeypatch)
        assert asyncio.run(sf.get_response("assets\\app.js", {})) == "served"
        assert asyncio.run(sf.get_response("assets/app.js", {})) == "served"

    @pytest.mark.parametrize("path", ["assets\\evil.js", ".git\\config", "console.json", "..\\x"])
    def test_unlisted_paths_still_404_with_backslashes(self, tmp_path, monkeypatch, path):
        sf = self._files(tmp_path, monkeypatch)
        with pytest.raises(ci.HTTPException) as exc:
            asyncio.run(sf.get_response(path, {}))
        assert exc.value.status_code == 404


async def _marker_response(self, path, scope):  # noqa: ARG001
    return "served"


class TestRmtreeOfReadOnlyTrees:
    def test_removes_read_only_files_like_a_git_checkout(self, tmp_path):
        tree = tmp_path / "co" / ".git" / "objects" / "ab"
        tree.mkdir(parents=True)
        obj = tree / "deadbeef"
        obj.write_bytes(b"x")
        os.chmod(obj, stat.S_IREAD)
        ci._rmtree(str(tmp_path / "co"))
        assert not (tmp_path / "co").exists()

    def test_missing_path_is_fine(self, tmp_path):
        ci._rmtree(str(tmp_path / "nope"))


class TestFsyncOfPublishedFiles:
    def test_fsync_file_works_on_a_normal_file(self, tmp_path):
        f = tmp_path / "ast.index"
        f.write_bytes(b"data")
        generation._fsync_file(str(f))           # raised EBADF on Windows (read-only descriptor)

    def test_fsync_file_works_on_a_read_only_file_on_posix(self, tmp_path):
        if os.name == "nt":
            pytest.skip("Windows cannot open a read-only file for writing")
        f = tmp_path / "ro"
        f.write_bytes(b"x")
        os.chmod(f, stat.S_IREAD)
        try:
            generation._fsync_file(str(f))
        except PermissionError:
            pytest.skip("running as a user that cannot open it read/write")        # root can; others cannot
        finally:
            os.chmod(f, stat.S_IREAD | stat.S_IWRITE)


class TestPidLivenessInTheReposView:
    def test_own_pid_alive_dead_pid_not(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        assert repos._alive(os.getpid()) is True
        assert repos._alive(dead.pid) is False
        assert repos._alive(None) is False and repos._alive(-3) is False and repos._alive("x") is False


class TestCliSurvivesALegacyConsoleEncoding:
    def test_non_cp1252_characters_do_not_crash_the_cli(self):
        """`init` printed an arrow and `index-repo` a cross; under cp1252 (Windows, or any piped legacy stdout) that
        raised UnicodeEncodeError and aborted the command."""
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from interface.cli import main as m\n"
            "m._main = lambda: print('  \\u2192 Enable: set storage.encrypt \\u2717 \\u2713') or None\n"
            "m.main()\n" % os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, env={**os.environ, "PYTHONIOENCODING": "cp1252"},
                             check=False)
        assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
        assert b"Enable: set storage.encrypt" in out.stdout
