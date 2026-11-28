# pylint: disable=unused-argument, redefined-outer-name  # pytest fixtures are requested by name
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_setup_keeps_existing_config.py — #280 (COG-17).

Re-running ``cognirepo setup`` (or ``cognirepo init``) on a configured repo and accepting every default used to
overwrite the saved settings with the wizard's fixed defaults: ``storage.encrypt`` true -> false,
``vector_backend`` faiss -> chroma, ``autosave_context`` false -> true. The docs promise a re-run is idempotent
("only adds missing entries"), so:

* the wizard offers the repo's current values as its defaults, and
* ``init_project`` only changes a setting the caller actually passed.

A setting the user changes on purpose must still change.
"""
from __future__ import annotations

import json
import types
from unittest.mock import patch

import pytest

from core.config.paths import get_path

_CONFIGURED = {
    "schema_version": 1,
    "project_id": "pid-1",
    "project_name": "my-service",
    "org": None,
    "project": None,
    "storage": {"encrypt": True, "vector_backend": "faiss"},
    "retrieval_weights": {"vector": 0.5, "graph": 0.3, "behaviour": 0.2},
    "model": {"provider": "auto", "model": "auto"},
    "autosave_context": False,
    "behaviour_tracking": True,
}


def _write_config(cfg: dict) -> None:
    with open(get_path("config.json"), "w", encoding="utf-8") as f:  # get_path creates the parent directory
        json.dump(cfg, f)


def _read_config() -> dict:
    with open(get_path("config.json"), encoding="utf-8") as f:
        return json.load(f)


def _answers(*scripted):
    """``input()`` that returns the scripted answers in order and then Enter for everything else."""
    it = iter(scripted)
    return lambda _prompt="": next(it, "")


@pytest.fixture()
def quiet_wizard(isolated_cognirepo, monkeypatch):
    """Run the real wizard without touching pip or the network."""
    monkeypatch.setattr("builtins.input", _answers())
    with patch("interface.cli.wizard._pip_install", return_value=True), \
         patch("interface.cli.wizard._install_package", return_value=True):
        yield


def _run_wizard():
    from interface.cli.wizard import run_wizard
    return run_wizard()


# ── the wizard offers the current values as its defaults ──────────────────────

def test_enter_at_every_prompt_keeps_the_saved_wizard_answers(quiet_wizard):
    _write_config(_CONFIGURED)

    result = _run_wizard()

    assert result["encrypt"] is True
    assert result["autosave_context"] is False
    assert result["behaviour_tracking"] is True
    assert result["project_name"] == "my-service"


def test_enter_at_every_prompt_keeps_org_and_project(quiet_wizard):
    from core.config.orgs import create_org, create_project

    create_org("acme")
    create_project("acme", "core")
    _write_config({**_CONFIGURED, "org": "acme", "project": "core"})

    result = _run_wizard()

    assert (result["org"], result["project"]) == ("acme", "core")


def test_enter_keeps_an_org_this_machine_has_no_record_of(quiet_wizard):
    """config.json can name an org the local registry does not list (a cloned repo, a wiped ~/.cognirepo)."""
    _write_config({**_CONFIGURED, "org": "ghost-org", "project": None})

    result = _run_wizard()

    assert result["org"] == "ghost-org"


def test_enter_keeps_an_org_that_has_no_project(quiet_wizard):
    from core.config.orgs import create_org

    create_org("acme")
    _write_config({**_CONFIGURED, "org": "acme", "project": None})

    result = _run_wizard()

    assert (result["org"], result["project"]) == ("acme", None)


def test_the_org_can_still_be_left(isolated_cognirepo, monkeypatch):
    from core.config.orgs import create_org

    create_org("acme")
    _write_config({**_CONFIGURED, "org": "acme", "project": None})
    # name, encryption, behaviour, languages, MCP target, handoff: Enter; org: option 1 = "None / Personal project"
    monkeypatch.setattr("builtins.input", _answers("", "", "", "", "", "", "1"))
    with patch("interface.cli.wizard._pip_install", return_value=True), \
         patch("interface.cli.wizard._install_package", return_value=True):
        result = _run_wizard()

    assert (result["org"], result["project"]) == (None, None)


def test_first_run_defaults_are_unchanged(quiet_wizard):
    """No config yet: the wizard's defaults must be exactly what they were."""
    result = _run_wizard()

    assert result["encrypt"] is False
    assert result["autosave_context"] is True
    assert result["behaviour_tracking"] is False
    assert (result["org"], result["project"]) == (None, None)


def test_an_unreadable_config_falls_back_to_the_fixed_defaults(quiet_wizard):
    with open(get_path("config.json"), "w", encoding="utf-8") as f:
        f.write("{not json")

    result = _run_wizard()

    assert result["encrypt"] is False and result["autosave_context"] is True


def _run_wizard_with(*scripted):
    """The real wizard with scripted answers (Enter for everything after them) and no pip, network or agent CLI."""
    with patch("builtins.input", _answers(*scripted)), \
         patch("interface.cli.wizard._pip_install", return_value=True), \
         patch("interface.cli.wizard._install_package", return_value=True):
        return _run_wizard()


# step 1 project name (Enter), step 2 encryption, then the confirmation that only an encrypted repo is asked
@pytest.mark.parametrize("answers", [("", "n", "y"), ("", "no", "yes")])
def test_encryption_goes_off_only_after_a_separate_confirmation(isolated_cognirepo, answers):
    _write_config(_CONFIGURED)

    assert _run_wizard_with(*answers)["encrypt"] is False


@pytest.mark.parametrize("answers", [("", "n"), ("", "n", ""), ("", "n", "n")])
def test_declining_the_confirmation_keeps_encryption_on(isolated_cognirepo, answers):
    """Enter or 'n' at the confirmation both keep it: 'n' to the first question alone never lowers it."""
    _write_config(_CONFIGURED)

    assert _run_wizard_with(*answers)["encrypt"] is True


def test_the_confirmation_is_not_asked_when_encryption_was_already_off(isolated_cognirepo):
    """Nothing is being lowered, so 'n' is final: the next Enter must go to the next prompt, not to a confirmation."""
    _write_config({**_CONFIGURED, "storage": {"encrypt": False, "vector_backend": "faiss"}})

    result = _run_wizard_with("", "n", "", "y")  # name, encryption n, behaviour: Enter (saved True), languages: y

    assert result["encrypt"] is False
    assert result["behaviour_tracking"] is True and result["install_languages"] is True


def test_turning_encryption_on_needs_no_confirmation(isolated_cognirepo):
    _write_config({**_CONFIGURED, "storage": {"encrypt": False, "vector_backend": "faiss"}})

    assert _run_wizard_with("", "y")["encrypt"] is True


# ── init_project only changes what the caller passed ──────────────────────────

def _init(**kwargs):
    from interface.cli.init_project import init_project
    return init_project(no_index=True, interactive=False, non_interactive=True, **kwargs)


def test_init_without_settings_keeps_every_saved_setting(isolated_cognirepo):
    """`cognirepo init --non-interactive` passes no settings at all."""
    _write_config(_CONFIGURED)

    _init()

    cfg = _read_config()
    assert cfg["storage"] == {"encrypt": True, "vector_backend": "faiss"}
    assert cfg["autosave_context"] is False
    assert cfg["behaviour_tracking"] is True
    assert cfg["project_id"] == "pid-1"


def test_init_with_the_wizard_answers_keeps_the_saved_vector_backend(isolated_cognirepo):
    """`setup` never asks about the vector backend, so it must not rewrite it."""
    _write_config(_CONFIGURED)

    _init(encrypt=True, autosave_context=False, behaviour_tracking=True)

    assert _read_config()["storage"]["vector_backend"] == "faiss"


def test_init_applies_a_setting_that_is_passed(isolated_cognirepo):
    _write_config({**_CONFIGURED, "storage": {"encrypt": False, "vector_backend": "faiss"},
                   "autosave_context": True, "behaviour_tracking": False})

    _init(encrypt=True, autosave_context=False, behaviour_tracking=True)

    cfg = _read_config()
    assert cfg["storage"]["encrypt"] is True
    assert cfg["autosave_context"] is False
    assert cfg["behaviour_tracking"] is True


def test_init_without_an_org_keeps_the_saved_org_and_project(isolated_cognirepo):
    """A bare `cognirepo init` must not clear the org and leave the project dangling."""
    _write_config({**_CONFIGURED, "org": "acme", "project": "core"})

    _init()

    cfg = _read_config()
    assert (cfg["org"], cfg["project"]) == ("acme", "core")


def test_init_can_clear_the_org_when_told_to(isolated_cognirepo):
    """The wizard's 'None / Personal project' passes org=None explicitly, which still means 'no organisation'."""
    _write_config({**_CONFIGURED, "org": "acme", "project": None})

    _init(org=None)

    assert _read_config()["org"] is None


def test_init_can_switch_the_org(isolated_cognirepo):
    _write_config({**_CONFIGURED, "org": "acme", "project": None})

    _init(org="globex")

    assert _read_config()["org"] == "globex"


def test_init_can_turn_encryption_off_when_asked_to(isolated_cognirepo):
    _write_config(_CONFIGURED)

    _init(encrypt=False)

    assert _read_config()["storage"]["encrypt"] is False


def test_a_new_repo_gets_the_documented_defaults(isolated_cognirepo):
    _init()

    cfg = _read_config()
    assert cfg["storage"] == {"encrypt": False, "vector_backend": "chroma"}
    assert cfg["autosave_context"] is True
    assert cfg["behaviour_tracking"] is False


# ── the whole `cognirepo setup` flow ──────────────────────────────────────────

def test_setup_with_every_default_leaves_a_configured_repo_as_it_was(quiet_wizard):
    """The reported reproduction: configure, re-run `setup`, press Enter at every prompt, compare config.json."""
    from interface.cli.main import _cmd_setup

    _write_config(_CONFIGURED)

    with patch("interface.cli.main._cmd_doctor"):  # the health check is not what is under test
        _cmd_setup(no_index=True)

    cfg = _read_config()
    assert cfg["storage"] == {"encrypt": True, "vector_backend": "faiss"}
    assert cfg["autosave_context"] is False
    assert cfg["behaviour_tracking"] is True
    assert cfg["project_id"] == "pid-1"


def test_setup_with_every_default_keeps_the_org_and_project(quiet_wizard):
    from core.config.orgs import create_org, create_project
    from interface.cli.main import _cmd_setup

    create_org("acme")
    create_project("acme", "core")
    _write_config({**_CONFIGURED, "org": "acme", "project": "core"})

    with patch("interface.cli.main._cmd_doctor"):
        _cmd_setup(no_index=True)

    cfg = _read_config()
    assert (cfg["org"], cfg["project"]) == ("acme", "core")


def test_setup_on_a_new_repo_writes_the_documented_defaults(quiet_wizard):
    from interface.cli.main import _cmd_setup

    with patch("interface.cli.main._cmd_doctor"):
        _cmd_setup(no_index=True)

    cfg = _read_config()
    assert cfg["storage"] == {"encrypt": False, "vector_backend": "chroma"}
    assert cfg["autosave_context"] is True
    assert cfg["behaviour_tracking"] is False


# ── the wizard has nothing to say about models (#269) ────────────────────────

def test_the_wizard_does_not_look_for_or_offer_agent_clis(isolated_cognirepo, monkeypatch, capsys):
    """CogniRepo does not call a model, so an agent CLI cannot be a "routing backend". The offer used to run only on
    a terminal, so simulate one."""
    from interface.cli import wizard

    monkeypatch.setattr("builtins.input", _answers())
    monkeypatch.setattr("sys.stdin", types.SimpleNamespace(isatty=lambda: True))
    with patch("interface.cli.wizard._pip_install", return_value=True), \
         patch("interface.cli.wizard._install_package", return_value=True), \
         patch("intelligence.orchestrator.provider_status.detect_cli_agents") as detect, \
         patch("intelligence.orchestrator.provider_status.prefetch_cli_agents") as prefetch:
        result = _run_wizard()

    out = capsys.readouterr().out
    detect.assert_not_called()
    prefetch.assert_not_called()
    assert "cli_backends" not in result
    assert "routing backend" not in out and "Agent CLI" not in out
    assert not hasattr(wizard, "_ask_cli_backends")
