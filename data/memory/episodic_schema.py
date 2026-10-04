# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
data/memory/episodic_schema.py — named keys for the episode dict schema.

`episodic_memory.py` and `timeline.py` both accessed this schema via hardcoded
string literals (`entry.get("event", ...)`, `entry.get("metadata", ...)`, etc.),
duplicated across both files with no single source of truth. See COGNIREPO-95.

An episode dict looks like:
    {
        EVENT: str,                 # human-readable event text
        METADATA: dict,             # free-form; METADATA_TYPE ("decision", …) lives here
        TIME: str,                  # ISO-8601 UTC timestamp, e.g. "2026-01-01T00:00:00Z"
    }
"""

EVENT = "event"
METADATA = "metadata"
TIME = "time"
METADATA_TYPE = "type"  # a key *within* the metadata dict, not the top-level episode dict
