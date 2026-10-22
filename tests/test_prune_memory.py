# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Task 1.4 — Fix FAISS rebuild path in cron/prune_memory.py.

Verifies that the pruner writes the rebuilt FAISS index to the configured
project path, not a hard-coded relative ./vector_db/ path.
"""
import json
import os


def test_rebuild_writes_to_configured_path(tmp_path, monkeypatch):
    """
    Run the pruner against a temp project dir and assert the rebuilt FAISS
    index exists at the expected absolute path (under .cognirepo/vector_db/).

    Setup includes one high-importance entry (kept) and one zero-importance
    entry (pruned) so that the FAISS rebuild actually executes.
    """
    from core.config.paths import set_cognirepo_dir
    set_cognirepo_dir(str(tmp_path / ".cognirepo"))

    # ── seed a real semantic store: one kept, one pruned (prune copies the vectors out of the index) ──
    import numpy as np
    from core.vector_db.local_vector_db import LocalVectorDB
    db = LocalVectorDB(dim=8)
    db.add(np.ones(8, dtype="float32"), "important memory that should be kept", 1.0)
    db.add(np.zeros(8, dtype="float32"), "stale memory that should be pruned", 0.0)

    import importlib
    from ops.cron import prune_memory
    importlib.reload(prune_memory)

    result = prune_memory.prune(threshold=0.10, dry_run=False)

    # Prune must not crash, keep 1, prune 1
    assert result.get("pruned", 0) >= 1, f"Expected at least 1 pruned, got: {result}"
    assert result.get("kept", 0) >= 1, f"Expected at least 1 kept, got: {result}"

    # The rebuilt FAISS index must exist under the configured project dir
    expected_index = str(tmp_path / ".cognirepo" / "vector_db" / "semantic.index")
    assert os.path.exists(expected_index), (
        f"FAISS index not found at configured path: {expected_index}\n"
        f"Prune result: {result}"
    )

    # Must NOT have been written to a stray ./vector_db/ relative to cwd
    stray = str(tmp_path / "vector_db" / "semantic.index")
    assert not os.path.exists(stray), (
        f"FAISS index written to stray path: {stray} instead of configured location"
    )
