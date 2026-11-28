# pylint: disable=unused-argument, redefined-outer-name, import-outside-toplevel, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_setup_ctrl_c.py — #276 (COG-13).

Ctrl-C at a setup-wizard prompt used to be answered with that prompt's default. At "Proceed with this
configuration?" (default yes) it confirmed the setup, so a user trying to get out of ``cognirepo setup`` got
``.cognirepo/``, ``.mcp.json``, ``.claude/`` and ``.env`` and exit 0.

* Ctrl-C at any wizard prompt cancels: a short message, exit 130, nothing written to the repo.
* EOF (closed stdin) still takes the prompt's default, so a scripted run finishes.
* An interrupted command no longer exits 0 (a shell and CI read that as success).
"""
from __future__ import annotations

import os
import re
import select
import subprocess
import sys
import time
import types
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parents[1])


# ── helpers ───────────────────────────────────────────────────────────────────

class _Prompts:
    """``input()`` that records every prompt, answers Enter, and can raise at the Nth one."""

    def __init__(self, raise_at: int | None = None, exc: type[BaseException] = KeyboardInterrupt):
        self.raise_at, self.exc, self.seen = raise_at, exc, []

    def __call__(self, prompt: str = "") -> str:
        self.seen.append(prompt)
        if self.raise_at is not None and len(self.seen) == self.raise_at:
            raise self.exc()
        return ""


@pytest.fixture()
def wizard_env(isolated_cognirepo):
    """The real wizard without touching pip or the network."""
    with patch("interface.cli.wizard._pip_install", return_value=True), \
         patch("interface.cli.wizard._install_package", return_value=True):
        yield


def _count_prompts(monkeypatch) -> _Prompts:
    """Run the wizard once, answering Enter everywhere, to learn how many prompts it asks."""
    from interface.cli.wizard import run_wizard

    dry = _Prompts()
    monkeypatch.setattr("builtins.input", dry)
    assert run_wizard() is not None
    return dry


def _cli(monkeypatch, *argv: str) -> int:
    from interface.cli.main import main

    monkeypatch.setattr(sys, "argv", ["cognirepo", *argv])
    try:
        main()
    except SystemExit as exit_info:
        return 0 if exit_info.code is None else exit_info.code
    return 0


def _service(name: str):
    return types.SimpleNamespace(name=name, service_type="rest_api", lang_hint="Python/pip", already_init=False)


def _files(root: Path) -> set[str]:
    """Every file under *root*. Empty directories do not count: reading the saved config creates the (empty)
    per-repo data directory, which is not a write."""
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# ── the prompt helpers ────────────────────────────────────────────────────────

@pytest.mark.parametrize("call", [
    lambda w: w._ask_yn("Proceed?", default=True),
    lambda w: w._ask_text("Name", "x"),
    lambda w: w._ask_choice("Pick", ["a", "b"], default=1),
    lambda w: w._ask_multiselect_fallback("Select", [_service("a"), _service("b")]),
    lambda w: w._ask_fuzzy_add(".", already_shown=[]),
], ids=["yn", "text", "choice", "multiselect-fallback", "fuzzy-add"])
def test_ctrl_c_at_a_prompt_is_not_an_answer(monkeypatch, call):
    from interface.cli import wizard

    monkeypatch.setattr("builtins.input", _Prompts(raise_at=1, exc=KeyboardInterrupt))

    with pytest.raises(KeyboardInterrupt):
        call(wizard)


def test_eof_still_takes_the_default(monkeypatch):
    """A closed stdin is not a person pressing a key: scripted and piped runs keep finishing."""
    from interface.cli import wizard

    monkeypatch.setattr("builtins.input", _Prompts(raise_at=1, exc=EOFError))
    assert wizard._ask_yn("Proceed?", default=True) is True
    monkeypatch.setattr("builtins.input", _Prompts(raise_at=1, exc=EOFError))
    assert wizard._ask_yn("Proceed?", default=False) is False
    monkeypatch.setattr("builtins.input", _Prompts(raise_at=1, exc=EOFError))
    assert wizard._ask_text("Name", "dflt") == "dflt"
    monkeypatch.setattr("builtins.input", _Prompts(raise_at=1, exc=EOFError))
    assert wizard._ask_choice("Pick", ["a", "b"], default=1) == 1


# ── the whole wizard ──────────────────────────────────────────────────────────

def test_the_last_prompt_is_the_one_that_defaults_to_yes(wizard_env, monkeypatch):
    """The premise of the bug: the final confirmation defaults to yes, so a swallowed Ctrl-C confirmed it."""
    dry = _count_prompts(monkeypatch)

    assert len(dry.seen) >= 5
    assert "Proceed with this configuration?" in dry.seen[-1] and "(Y/n)" in dry.seen[-1]


def test_ctrl_c_at_every_wizard_prompt_cancels_the_wizard(wizard_env, monkeypatch):
    from interface.cli.wizard import run_wizard

    total = len(_count_prompts(monkeypatch).seen)

    for position in range(1, total + 1):
        monkeypatch.setattr("builtins.input", _Prompts(raise_at=position))
        with pytest.raises(KeyboardInterrupt):
            run_wizard()


def test_a_closed_stdin_at_every_wizard_prompt_still_finishes_with_defaults(wizard_env, monkeypatch):
    from interface.cli.wizard import run_wizard

    monkeypatch.setattr("builtins.input", _Prompts(raise_at=1, exc=EOFError))
    first_prompt_eof = run_wizard()  # only the first prompt hits EOF, the rest answer Enter
    assert first_prompt_eof is not None and first_prompt_eof["project_name"]

    def _always_eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _always_eof)
    assert run_wizard() is not None


# ── `cognirepo setup` and `cognirepo init` ───────────────────────────────────

def test_setup_cancelled_at_the_first_and_the_last_prompt_exits_130_and_writes_nothing(
        wizard_env, monkeypatch, capsys, tmp_path):
    total = len(_count_prompts(monkeypatch).seen)
    capsys.readouterr()

    def _must_not_run(*_a, **_k):
        raise AssertionError("init_project() writes the repo: it must not run after a cancel")

    for position in (1, total):
        before = _files(tmp_path)
        monkeypatch.setattr("builtins.input", _Prompts(raise_at=position))
        with patch("interface.cli.init_project.init_project", _must_not_run):
            code = _cli(monkeypatch, "setup")

        out = capsys.readouterr().out
        assert code == 130, f"prompt {position} of {total}"
        assert "Setup cancelled" in out
        assert _files(tmp_path) == before, "a file was written after Ctrl-C"
        for name in (".mcp.json", ".claude", ".env"):
            assert not (tmp_path / name).exists(), name


def test_setup_interrupted_while_writing_also_exits_130(wizard_env, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", _Prompts())

    def _interrupted(*_a, **_k):
        raise KeyboardInterrupt

    with patch("interface.cli.init_project.init_project", _interrupted):
        code = _cli(monkeypatch, "setup")

    assert code == 130 and "Setup cancelled" in capsys.readouterr().out


def test_init_does_not_fall_back_to_default_answers_after_ctrl_c(isolated_cognirepo, monkeypatch):
    """`init` used to catch the interrupt, carry on with defaults and write a config."""
    from interface.cli.init_project import init_project

    def _cancel():
        raise KeyboardInterrupt

    def _must_not_write():
        raise AssertionError("init wrote the repo after Ctrl-C")

    with patch("interface.cli.wizard.run_wizard", _cancel), \
         patch("interface.cli.init_project._scaffold_dirs", _must_not_write):
        with pytest.raises(KeyboardInterrupt):
            init_project(interactive=True, non_interactive=False, no_index=True)


def test_an_interrupted_command_does_not_exit_zero(monkeypatch, capsys):
    """A shell and CI read exit 0 as success, so `cognirepo index-repo . && next` carried on after Ctrl-C."""
    def _interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr("interface.cli.main._main", _interrupted)
    monkeypatch.setattr(sys, "argv", ["cognirepo", "doctor"])
    from interface.cli.main import main

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 130
    assert "Interrupted" in capsys.readouterr().out


# ── a real terminal: the realistic way to send Ctrl-C ────────────────────────

_DRIVER = (
    "import fcntl, signal, sys, termios\n"
    "fcntl.ioctl(0, termios.TIOCSCTTY, 0)\n"        # the pty becomes our controlling terminal, so ^C is SIGINT
    # A person at a terminal has the default SIGINT handler. A test run started as a background job (`cmd &`,
    # nohup, some CI wrappers) inherits SIGINT as *ignored*, and so would this child: ^C would then do nothing.
    "signal.signal(signal.SIGINT, signal.default_int_handler)\n"
    "import sys\n"
    "import interface.cli.wizard as w\n"
    "w._pip_install = lambda *a, **k: True\n"       # nothing is installed by a test
    "w._install_package = lambda *a, **k: True\n"
    "sys.argv = ['cognirepo', 'setup', '--no-index']\n"
    "from interface.cli.main import main\n"
    "main()\n"
)
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _run_setup_in_a_pty(repo: Path, home: Path, ctrl_c_at: str, timeout: float = 90.0):
    """Drive the real `cognirepo setup` in a pseudo-terminal: Enter at every prompt, Ctrl-C at the chosen one."""
    pty = pytest.importorskip("pty", reason="needs a POSIX pseudo-terminal")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COGNIREPO_", "ANTHROPIC_", "OPENAI_"))}
    env.update(HOME=str(home), COGNIREPO_GLOBAL_DIR=str(home / ".cognirepo"), PYTHONPATH=_REPO_ROOT,
               PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring", TERM="dumb", NO_COLOR="1",
               PYTHONDONTWRITEBYTECODE="1")
    master, slave = pty.openpty()
    proc = subprocess.Popen([sys.executable, "-c", _DRIVER], cwd=repo, env=env, stdin=slave, stdout=slave,
                            stderr=slave, close_fds=True, start_new_session=True)
    os.close(slave)
    out, pending, last_data, sent, start, sent_at = b"", b"", time.time(), False, time.time(), 0.0
    try:
        while time.time() - start < timeout and proc.poll() is None:
            if sent and time.time() - sent_at > 20:                # Ctrl-C was sent and the process is still there
                break
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                out, pending, last_data = out + chunk, pending + chunk, time.time()
            elif pending and time.time() - last_data > 0.3:        # output stopped: is it waiting at a prompt?
                shown = _ANSI.sub("", out.decode(errors="replace")).replace("\r", "")[-400:]
                if not shown.endswith(": "):                       # every wizard prompt ends in ": "; a slow
                    continue                                       # machine pausing mid-output must not get an Enter
                if not sent and (ctrl_c_at == "first" or "Proceed with this configuration" in shown):
                    os.write(master, b"\x03")
                    sent, sent_at = True, time.time()
                else:
                    os.write(master, b"\n")
                pending = b""
        try:
            code = proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = None
    finally:
        os.close(master)
    return code, _ANSI.sub("", out.decode(errors="replace")).replace("\r", ""), sent


@pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX pseudo-terminal")
@pytest.mark.parametrize("ctrl_c_at", ["first", "last"])
def test_real_terminal_ctrl_c_cancels_setup_and_writes_nothing(tmp_path, ctrl_c_at):
    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir()
    home.mkdir()
    (repo / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    code, transcript, sent = _run_setup_in_a_pty(repo, home, ctrl_c_at)

    assert sent, f"never reached the {ctrl_c_at} prompt:\n{transcript[-600:]}"
    assert code == 130, transcript[-600:]
    assert "Setup cancelled" in transcript
    assert sorted(os.listdir(repo)) == ["a.py"], "setup wrote into the repo after Ctrl-C"
    assert "Traceback" not in transcript
