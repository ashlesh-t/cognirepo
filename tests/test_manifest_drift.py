# pylint: disable=missing-docstring, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_manifest_drift.py — CI gate for COGNIREPO-101 (single-source manifest generation).

Asserts set-equality between the @mcp.tool()-decorated function names (the same
extraction _REGISTERED_TOOLS uses, mcp_server.py) and every derived artifact —
manifest.json, glama.json, openai_tools.json — plus a hard check that none of
those artifacts have been hand-edited out of sync with the live registry.
"""
from __future__ import annotations

import importlib.util
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_gen_tool_specs():
    spec = importlib.util.spec_from_file_location(
        "gen_tool_specs", os.path.join(REPO_ROOT, "scripts", "gen_tool_specs.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestManifestDrift:
    def test_manifest_names_match_registered_tools(self):
        from interface.server.mcp_server import _build_manifest, _REGISTERED_TOOLS
        manifest = _build_manifest()
        names = {t["name"] for t in manifest["tools"]}
        assert names == _REGISTERED_TOOLS

    def test_manifest_json_on_disk_matches_registered_tools(self):
        from interface.server.mcp_server import _REGISTERED_TOOLS
        manifest_path = os.path.join(REPO_ROOT, "interface", "server", "manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        names = {t["name"] for t in manifest["tools"]}
        assert names == _REGISTERED_TOOLS

    def test_glama_json_matches_registered_tools(self):
        from interface.server.mcp_server import _REGISTERED_TOOLS
        glama_path = os.path.join(REPO_ROOT, "glama.json")
        with open(glama_path, encoding="utf-8") as f:
            glama = json.load(f)
        names = {t["name"] for t in glama["tools"]}
        assert names == _REGISTERED_TOOLS

    def test_openai_tools_json_matches_registered_tools(self):
        from interface.server.mcp_server import _REGISTERED_TOOLS
        openai_path = os.path.join(REPO_ROOT, "interface", "adapters", "openai_tools.json")
        with open(openai_path, encoding="utf-8") as f:
            openai_tools = json.load(f)
        names = {t["function"]["name"] for t in openai_tools}
        assert names == _REGISTERED_TOOLS

    def test_no_drift_between_disk_artifacts_and_live_registry(self):
        """
        Fails if manifest.json/glama.json were hand-edited (or a tool was added
        without running scripts/gen_tool_specs.py) since they'd no longer match
        what regenerating from the live @mcp.tool() registry produces.
        """
        mod = _load_gen_tool_specs()
        assert mod.regenerate(check=True) is False, (
            "manifest.json/glama.json are out of sync with the @mcp.tool() registry — "
            "run: python scripts/gen_tool_specs.py"
        )
