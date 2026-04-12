# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Task 1.3 — Honor --project-dir in orchestrator/session.py.

Verifies that session files are written under the configured project dir,
and that two distinct project dirs do not cross-contaminate each other.
"""
import json


def test_project_dir_isolates_sessions(tmp_path):
    """Sessions must land under the configured project dir, not CWD or ~/.cognirepo."""
    dir_a = tmp_path / "project_a" / ".cognirepo"
    dir_b = tmp_path / "project_b" / ".cognirepo"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    from config.paths import set_cognirepo_dir

    # ── project A ────────────────────────────────────────────────────────────
    set_cognirepo_dir(str(dir_a))
    from orchestrator import session as sess_mod
    # Reload so module-level state picks up the new dir override
    import importlib
    importlib.reload(sess_mod)

    sess_a = sess_mod.create_session(model="test")
    sid_a = sess_a["session_id"]

    # Session file must live under dir_a/sessions/
    expected_a = dir_a / "sessions" / f"{sid_a}.json"
    assert expected_a.exists(), f"Session not written to project_a: {expected_a}"

    # ── project B ────────────────────────────────────────────────────────────
    set_cognirepo_dir(str(dir_b))
    importlib.reload(sess_mod)

    sess_b = sess_mod.create_session(model="test")
    sid_b = sess_b["session_id"]

    expected_b = dir_b / "sessions" / f"{sid_b}.json"
    assert expected_b.exists(), f"Session not written to project_b: {expected_b}"

    # ── no cross-contamination ────────────────────────────────────────────────
    wrong_a_in_b = dir_b / "sessions" / f"{sid_a}.json"
    wrong_b_in_a = dir_a / "sessions" / f"{sid_b}.json"
    assert not wrong_a_in_b.exists(), "Project A session leaked into project B"
    assert not wrong_b_in_a.exists(), "Project B session leaked into project A"
