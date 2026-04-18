# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Tool to store a text memory into semantic memory.
"""
import sys
from memory.semantic_memory import SemanticMemory
from memory.episodic_memory import log_event
from server.metrics import MEMORY_OPS_TOTAL


def store_memory(text: str, source: str = "") -> dict:
    """
    Store a text memory in semantic memory and return status.
    """
    mem = SemanticMemory()
    importance = mem.compute_importance(text)
    try:
        mem.store(text)
        MEMORY_OPS_TOTAL.labels(op="store", result="ok").inc()
    except Exception:
        MEMORY_OPS_TOTAL.labels(op="store", result="error").inc()
        raise

    # Log the event in episodic memory
    log_event(
        event=f"store-memory: {text[:50]}...",
        metadata={"source": source, "importance": importance, "type": "semantic_storage"}
    )

    # Mirror to shared project memory when autosave_context enabled
    try:
        from config.orgs import get_repo_project  # pylint: disable=import-outside-toplevel
        import os  # pylint: disable=import-outside-toplevel
        result = get_repo_project(os.getcwd())
        if result:
            from memory.project_memory import ProjectMemory  # pylint: disable=import-outside-toplevel
            org, project = result
            ProjectMemory(org, project).store(
                text,
                source_repo=os.path.basename(os.getcwd()),
                importance=importance,
            )
    except Exception:  # pylint: disable=broad-except
        pass  # project memory mirror is best-effort

    return {"status": "stored", "text": text, "source": source, "importance": importance}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = store_memory(sys.argv[1])
        print(result)
    else:
        print("Usage: python tools/store_memory.py <text>")
