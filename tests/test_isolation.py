# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in recovery root.

"""
Task 3.2 — Isolate memory/user_memory.py from real ~/.cognirepo during tests.

Verifies that:
- user_memory writes go to the tmp directory, NOT the real ~/.cognirepo
- The real ~/.cognirepo is untouched after running user_memory operations
"""
from pathlib import Path


def test_no_writes_to_real_home(tmp_path):
    """
    Run user_memory operations and assert the real ~/.cognirepo/user/ is NOT modified.
    """
    real_home_dir = Path.home() / ".cognirepo" / "user"

    # Record mtime of real user dir before (if it exists)
    real_mtime_before = real_home_dir.stat().st_mtime if real_home_dir.exists() else None

    # Override dirs — conftest's autouse fixture already does this, but be explicit
    from config.paths import set_global_dir, get_global_dir
    isolated_global = tmp_path / ".cognirepo-global"
    set_global_dir(str(isolated_global))

    # Run user_memory operations
    from memory.user_memory import set_preference, get_preference, record_action

    set_preference("test_key", "test_value")
    result = get_preference("test_key")
    assert result == "test_value"

    record_action("test_action")

    # Verify writes went to the isolated dir
    isolated_user = isolated_global / "user"
    assert isolated_user.exists(), f"Expected writes under {isolated_user}, found nothing"

    # Verify the real ~/.cognirepo/user was NOT modified
    if real_home_dir.exists() and real_mtime_before is not None:
        real_mtime_after = real_home_dir.stat().st_mtime
        assert real_mtime_after == real_mtime_before, (
            f"Real ~/.cognirepo/user/ was modified during test! "
            f"mtime before={real_mtime_before}, after={real_mtime_after}"
        )


def test_global_dir_override_respected():
    """get_global_dir() must return the overridden path, not ~/.cognirepo."""
    from config.paths import set_global_dir, get_global_dir

    fake_dir = "/tmp/fake_cognirepo_global_test"
    set_global_dir(fake_dir)
    assert get_global_dir() == fake_dir
    assert get_global_dir() != str(Path.home() / ".cognirepo")
