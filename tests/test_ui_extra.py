# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""The control API's dependencies live in the optional ``[ui]`` extra, not the core install."""
import tomllib
from pathlib import Path

from interface import ui

_PYPROJECT = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text("utf-8"))


def _names(reqs):
    return {r.split(">")[0].split("=")[0].split("[")[0].strip() for r in reqs}


def test_ui_deps_are_an_extra_not_core():
    core = _names(_PYPROJECT["project"]["dependencies"])
    extra = _names(_PYPROJECT["project"]["optional-dependencies"]["ui"])
    assert {"fastapi", "uvicorn"} <= extra
    assert not ({"fastapi", "uvicorn", "python-multipart"} & core)


def test_ui_extra_missing_reports_absent_modules(monkeypatch):
    monkeypatch.setattr(ui.importlib.util, "find_spec", lambda name: None)
    assert ui.ui_extra_missing() == ["fastapi", "uvicorn"]
    assert "cognirepo[ui]" in ui.UI_INSTALL_HINT
