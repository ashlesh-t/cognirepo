# COGNIREPO-D02 — DEFECT: episodic event-ID collision after rotation

Epic: COGNIREPO-100 · Branch: defect/COGNIREPO-D02 · Base: development · Severity: P2 (data integrity)

## Backstory / reproduction (verified by code inspection at HEAD, 2026-07-11)
data/memory/episodic_memory.py:150 — log_event assigns `"id": f"e_{len(data)}"`. Rotation
(_rotate_if_needed, :43-61) archives the oldest 20% when episodic_max_events (default 10,000) is
hit, shrinking len(data); the next new event's ID duplicates a surviving entry's (e.g. after
10,000→8,000 trim, next ID e_8000 already exists). Consequences: search_episodes' id_to_entry
dict (:223) silently collapses duplicates; the prev linked-list (:155-156) becomes ambiguous;
archived entries share IDs with live ones. Repro: set episodic_max_events=20 in config.json, log
25 events, inspect IDs. Evidence: ../COGNIREPO-200-Discovery-equivalent in
../../../EPIC-KGEpisodicHardening-200/COGNIREPO-200-Discovery.md §2 and
../../COGNIREPO-100-Discovery.md §8.

## Description / fix
Make IDs unique for the store's lifetime: persist a monotonic counter (e.g. store header record
or `max(int(id[2:]) for existing)+1` computed on load, including the archive file's max).
Migration: existing IDs stay as-is; only new assignments change. Add a defensive uniqueness
check in _load (log a warning if historical dupes exist). Unit tests: fill past cap → rotate →
all live+archived IDs unique; prev chain references resolvable.

## Acceptance criteria
1. After any number of rotations, live ∪ archive IDs are unique.
2. prev chain never points at an ambiguous ID for newly written events.
3. Existing stores load unchanged (no migration rewrite of old entries).
4. Fixed BEFORE EPIC-200's 204/205 (timeline refs and embedding-cache keys use these IDs).
