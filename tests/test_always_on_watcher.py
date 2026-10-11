# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""Always-on watcher (#146): catch-up reindex on start, `watch --serve`, `watch --autostart`."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from intelligence.indexer import file_watcher
from interface.ui import autostart
from interface.ui.autostart import launchd, schtasks, systemd


def _ts(delta_secs: float) -> str:
    return (datetime.now(tz=timezone.utc) + timedelta(seconds=delta_secs)).isoformat()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *cmd], cwd=r, check=True)
    (r / ".gitignore").write_text("ignored.py\n")
    return r


def _touch(path, content="x = 1\n", age=0.0):
    path.write_text(content)
    t = path.stat().st_mtime - age
    os.utime(path, (t, t))


class TestFindStalePaths:
    def test_new_modified_deleted_and_unchanged(self, repo):
        _touch(repo / "fresh.py", age=3600)               # indexed after its last edit
        _touch(repo / "edited.py")                        # edited after it was indexed
        _touch(repo / "brand_new.py")                     # never indexed
        _touch(repo / "ignored.py")                       # gitignored: never a candidate
        _touch(repo / "notes.txt")                        # unsupported extension
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        indexed = {
            "fresh.py": {"indexed_at": _ts(-10)},
            "edited.py": {"indexed_at": _ts(-3600)},
            "gone.py": {"indexed_at": _ts(-10)},          # indexed, deleted while we were down
        }
        changed, removed = file_watcher.find_stale_paths(str(repo), indexed)
        assert sorted(os.path.basename(p) for p in changed) == ["brand_new.py", "edited.py"]
        assert [os.path.basename(p) for p in removed] == ["gone.py"]

    def test_tracked_file_deleted_from_the_working_tree_is_removed(self, repo):
        """`git ls-files --cached` still lists it until the deletion is staged."""
        _touch(repo / "doomed.py")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "c"], cwd=repo, check=True)
        (repo / "doomed.py").unlink()
        changed, removed = file_watcher.find_stale_paths(str(repo), {"doomed.py": {"indexed_at": _ts(-5)}})
        assert changed == [] and [os.path.basename(p) for p in removed] == ["doomed.py"]

    def test_untracked_but_not_ignored_file_is_picked_up(self, repo):
        _touch(repo / "untracked.py")                     # never `git add`ed
        changed, _ = file_watcher.find_stale_paths(str(repo), {})
        assert [os.path.basename(p) for p in changed] == ["untracked.py"]

    def test_unparseable_indexed_at_is_treated_as_stale(self, repo):
        _touch(repo / "a.py", age=3600)
        changed, _ = file_watcher.find_stale_paths(str(repo), {"a.py": {"indexed_at": "garbage"}})
        assert len(changed) == 1

    def test_not_a_git_repo_returns_nothing(self, tmp_path):
        _touch(tmp_path / "a.py")
        assert file_watcher.find_stale_paths(str(tmp_path), {}) == ([], [])


class TestCatchUp:
    def test_stale_paths_go_through_the_debounced_queue(self, repo):
        _touch(repo / "new.py")
        handler = mock.MagicMock(repo_root=str(repo))
        handler.indexer.index_data = {"files": {"gone.py": {"indexed_at": _ts(-5)}}}
        assert file_watcher.catch_up(handler) == 2
        calls = sorted((c.args[0], os.path.basename(c.args[1])) for c in handler._queue.call_args_list)
        assert calls == [("reindex", "new.py"), ("remove", "gone.py")]

    def test_a_scan_failure_never_blocks_the_watcher(self, repo):
        handler = mock.MagicMock(repo_root=str(repo))
        with mock.patch.object(file_watcher, "find_stale_paths", side_effect=RuntimeError("boom")):
            assert file_watcher.catch_up(handler) == 0
        handler._queue.assert_not_called()

    def test_create_watcher_catches_up_only_when_asked(self, repo):
        indexer = mock.MagicMock()
        for flag in (False, True):
            with mock.patch.object(file_watcher, "Observer"), \
                 mock.patch.object(file_watcher, "catch_up") as cu:
                file_watcher.create_watcher(str(repo), indexer, mock.MagicMock(), mock.MagicMock(), "s",
                                            catch_up_on_start=flag)
            assert cu.called is flag


class TestUnitName:
    def test_stable_per_repo_and_distinct_across_repos(self, tmp_path):
        a, b = tmp_path / "x" / "app", tmp_path / "y" / "app"
        assert autostart.unit_name_for_repo(str(a)) == autostart.unit_name_for_repo(str(a))
        assert autostart.unit_name_for_repo(str(a)) != autostart.unit_name_for_repo(str(b))

    def test_is_filesystem_and_launchd_safe(self):
        name = autostart.unit_name_for_repo("/home/u/my repo (v2)/ü")
        assert name.startswith("cognirepo-watcher-")
        assert all(c.isalnum() or c in "-_." for c in name)


class _FakeSystemctl:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, *args):
        self.calls.append(args)
        rc = 1 if self.fail_on and self.fail_on in args else 0
        return subprocess.CompletedProcess(args, rc, "", "denied" if rc else "")


class TestSystemd:
    @pytest.fixture(autouse=True)
    def _xdg(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    def test_unit_runs_serve_in_the_foreground_and_revives_crashes(self):
        text = systemd.render("n", ["/bin/cognirepo", "watch", "--path", "/my repo", "--serve"], "/my repo")
        assert "ExecStart=/bin/cognirepo watch --path '/my repo' --serve" in text
        assert "Restart=on-failure" in text
        assert "WorkingDirectory=/my repo" in text

    def test_install_enables_now_and_is_idempotent(self):
        fake = _FakeSystemctl()
        with mock.patch.object(systemd, "_systemctl", fake):
            p1 = systemd.install("n", ["x", "watch"], "/r")
            p2 = systemd.install("n", ["x", "watch"], "/r")
        assert p1 == p2 and p1.read_text().count("[Service]") == 1
        assert ("enable", "--now", "n.service") in fake.calls
        assert systemd.is_installed("n")

    def test_uninstall_removes_unit_and_reports_absence(self):
        fake = _FakeSystemctl()
        with mock.patch.object(systemd, "_systemctl", fake):
            assert systemd.uninstall("n") is False        # nothing there
            systemd.install("n", ["x"], "/r")
            assert systemd.uninstall("n") is True
        assert not systemd.is_installed("n")
        assert ("disable", "--now", "n.service") in fake.calls

    def test_systemctl_refusal_surfaces_as_autostart_error(self):
        with mock.patch.object(systemd, "_systemctl", _FakeSystemctl(fail_on="enable")):
            with pytest.raises(autostart.AutostartError, match="denied"):
                systemd.install("n", ["x"], "/r")

    def test_old_generator_still_produces_the_same_shape(self, tmp_path):
        from interface.cli.daemon import generate_systemd_unit
        text = generate_systemd_unit(str(tmp_path))
        assert "--foreground" in text and "Restart=on-failure" in text


class TestLaunchdAndSchtasks:
    def test_plist_is_valid_and_keeps_alive_after_failure_only(self):
        data = plistlib.loads(launchd.render("n", ["/bin/cognirepo", "watch", "--serve"], "/r"))
        assert data["Label"] == "io.cognirepo.n"
        assert data["ProgramArguments"] == ["/bin/cognirepo", "watch", "--serve"]
        assert data["KeepAlive"] == {"SuccessfulExit": False} and data["RunAtLoad"] is True

    def test_schtasks_install_and_uninstall(self):
        calls = []

        def fake(*args):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(schtasks, "_schtasks", fake):
            schtasks.install("n", ["C:\\cr.exe", "watch", "--path", "C:\\my repo", "--serve"], "C:\\my repo")
            assert schtasks.uninstall("n") is True
        create = next(c for c in calls if c[0] == "/Create")
        assert "ONLOGON" in create and "CogniRepo\\n" in create
        assert any(c[0] == "/Delete" for c in calls)

    def test_backend_selection(self, monkeypatch):
        for plat, mod in (("linux", systemd), ("darwin", launchd), ("win32", schtasks)):
            monkeypatch.setattr(sys, "platform", plat)
            assert autostart.backend() is mod
        monkeypatch.setattr(sys, "platform", "plan9")
        with pytest.raises(autostart.AutostartError):
            autostart.backend()


class TestWatchCommand:
    def test_serve_runs_the_watcher_in_the_foreground_in_this_process(self, tmp_path):
        from interface.cli import main as cli
        with mock.patch.object(sys, "argv", ["cognirepo", "watch", "--serve", "--path", str(tmp_path)]), \
             mock.patch("interface.cli.daemon.is_watcher_running_for_path", return_value=None), \
             mock.patch("data.graph.knowledge_graph.KnowledgeGraph"), \
             mock.patch("intelligence.indexer.ast_indexer.ASTIndexer"), \
             mock.patch.object(cli, "_start_watcher") as start:
            cli.main()
        assert start.call_args.kwargs["daemon"] is False          # no fork, no detach
        assert start.call_args.args[0] == str(tmp_path)

    def test_autostart_flag_dispatches(self, tmp_path):
        from interface.cli import main as cli
        with mock.patch.object(sys, "argv", ["cognirepo", "watch", "--autostart", "off", "--path", str(tmp_path)]), \
             mock.patch.object(cli, "_cmd_watch_autostart", return_value=0) as cmd:
            with pytest.raises(SystemExit) as exc:
                cli.main()
        assert exc.value.code == 0
        cmd.assert_called_once_with(str(tmp_path), "off")

    def test_autostart_on_hands_over_a_manual_watcher_then_installs(self, tmp_path, capsys):
        from interface.cli import main as cli
        backend = mock.MagicMock()
        backend.install.return_value = "/u/n.service"
        with mock.patch.object(autostart, "backend", return_value=backend), \
             mock.patch("interface.cli.daemon.is_watcher_running_for_path",
                        return_value={"pid": 4242, "kind": "detached"}), \
             mock.patch("interface.cli.daemon.stop_watcher_and_wait", return_value="stopped") as stop:
            assert cli._cmd_watch_autostart(str(tmp_path), "on") == 0
        stop.assert_called_once_with("4242")
        argv = backend.install.call_args.args[1]
        assert argv[-3:] == ["--path", str(tmp_path), "--serve"]
        assert "Autostart enabled" in capsys.readouterr().out

    def test_autostart_on_leaves_an_embedded_watcher_alone(self, tmp_path):
        from interface.cli import main as cli
        backend = mock.MagicMock()
        with mock.patch.object(autostart, "backend", return_value=backend), \
             mock.patch("interface.cli.daemon.is_watcher_running_for_path",
                        return_value={"pid": 1, "kind": "embedded"}), \
             mock.patch("interface.cli.daemon.stop_watcher_and_wait") as stop:
            cli._cmd_watch_autostart(str(tmp_path), "on")
        stop.assert_not_called()

    def test_autostart_off_removes_and_is_idempotent(self, tmp_path, capsys):
        from interface.cli import main as cli
        backend = mock.MagicMock()
        backend.uninstall.side_effect = [True, False]
        with mock.patch.object(autostart, "backend", return_value=backend):
            assert cli._cmd_watch_autostart(str(tmp_path), "off") == 0
            assert cli._cmd_watch_autostart(str(tmp_path), "off") == 0
        out = capsys.readouterr().out
        assert "Autostart removed" in out and "nothing to remove" in out

    def test_unsupported_platform_is_a_clean_error(self, tmp_path, capsys):
        from interface.cli import main as cli
        with mock.patch.object(autostart, "backend", side_effect=autostart.AutostartError("nope")):
            assert cli._cmd_watch_autostart(str(tmp_path), "on") == 1
        assert "nope" in capsys.readouterr().err
