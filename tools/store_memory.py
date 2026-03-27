# SPDX-FileCopyrightText: 2026 Ashlesh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/your-username/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Tool to store a text memory into semantic memory.
"""
import sys
from memory.semantic_memory import SemanticMemory


def store_memory(text: str, source: str = "") -> dict:
    """
    Store a text memory in semantic memory and return status.
    """
    mem = SemanticMemory()
    importance = mem.compute_importance(text)
    mem.store(text)
    return {"status": "stored", "text": text, "source": source, "importance": importance}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = store_memory(sys.argv[1])
        print(result)
    else:
        print("Usage: python tools/store_memory.py <text>")
