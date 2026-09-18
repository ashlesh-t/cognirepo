# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_sync_version.py — Regression coverage for scripts/sync_version.py.

COGNIREPO-600-603: server.json's title/description drifted from version.yml's mcp section
(server.json said "34 MCP tools" while version.yml already said "35") because sync_version.py
only ever propagated the version number, never title/description. Covers the fix.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_sync_version_module():
    spec = importlib.util.spec_from_file_location(
        "sync_version", Path(__file__).parent.parent / "scripts" / "sync_version.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sync_version(tmp_path, monkeypatch):
    module = _load_sync_version_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    return module


def _write_server_json(tmp_path: Path, **overrides) -> Path:
    data = {
        "version": "1.0.0",
        "title": "OldTitle",
        "description": "old description",
        "packages": [{"version": "1.0.0"}],
    }
    data.update(overrides)
    path = tmp_path / "server.json"
    path.write_text(json.dumps(data))
    return path


class TestSyncServerJsonTitleDescription:
    def test_syncs_title_and_description_from_mcp_meta(self, sync_version, tmp_path):
        path = _write_server_json(tmp_path)
        meta = {"mcp": {"title": "CogniRepo", "description": "35 MCP tools for AI agents."}}

        ok = sync_version.sync_server_json("2.0.0", meta, check=False)

        assert ok
        data = json.loads(path.read_text())
        assert data["title"] == "CogniRepo"
        assert data["description"] == "35 MCP tools for AI agents."
        assert data["version"] == "2.0.0"
        assert data["packages"][0]["version"] == "2.0.0"

    def test_check_mode_detects_description_drift_without_writing(self, sync_version, tmp_path):
        path = _write_server_json(
            tmp_path, version="2.0.0", title="CogniRepo",
            description="34 MCP tools for AI agents.", packages=[{"version": "2.0.0"}],
        )
        meta = {"mcp": {"title": "CogniRepo", "description": "35 MCP tools for AI agents."}}

        ok = sync_version.sync_server_json("2.0.0", meta, check=True)

        assert ok is False
        # --check must never write
        assert json.loads(path.read_text())["description"] == "34 MCP tools for AI agents."

    def test_leaves_title_description_untouched_when_mcp_meta_has_neither(self, sync_version, tmp_path):
        """version.yml's mcp section is optional — a caller without title/description shouldn't
        have this script clobber whatever server.json already has."""
        path = _write_server_json(tmp_path, version="2.0.0", packages=[{"version": "2.0.0"}])
        meta = {"mcp": {}}

        ok = sync_version.sync_server_json("2.0.0", meta, check=False)

        assert ok
        data = json.loads(path.read_text())
        assert data["title"] == "OldTitle"
        assert data["description"] == "old description"

    def test_already_in_sync_returns_true_without_writing(self, sync_version, tmp_path):
        path = _write_server_json(
            tmp_path, version="2.0.0", title="CogniRepo",
            description="35 MCP tools for AI agents.", packages=[{"version": "2.0.0"}],
        )
        meta = {"mcp": {"title": "CogniRepo", "description": "35 MCP tools for AI agents."}}
        before = path.read_text()

        ok = sync_version.sync_server_json("2.0.0", meta, check=True)

        assert ok
        assert path.read_text() == before
