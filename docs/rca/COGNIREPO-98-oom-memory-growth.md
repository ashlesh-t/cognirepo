# RCA — `cognirepo` OOM-killed at ~5.2 GB RSS (issue #98)

**Status: OPEN — root cause not found.** This document records what is confirmed, what has
been ruled out, the mitigation already shipped, a repro attempt run today, and what's left.
Tracking follow-up: #105. Mitigation PR: #102 (`fix/COGNIREPO-98-memory-guard`).

## 1. Incident (from #98)

A `cognirepo` process was OOM-killed twice (~23:48 and ~23:55) at ~5.2 GB / ~5.1 GB anon-RSS
while running a manual e2e session against `cognirepo_test_repo/medium/celery` (vector_db 47 MB,
index 27 MB, graph 6 MB — store is far too small to explain 5 GB). Host: 15 GB RAM, already
swapping (IntelliJ + Chrome). `oom_score_adj:200`. At kill time the celery graph was already
quarantined/empty (issue #97's bug, unrelated as a cause — confirmed below). A watcher/heartbeat
was alive until the kill.

## 2. Ruled out

| Hypothesis | Status | Evidence |
|---|---|---|
| Graph load (encrypted/quarantined) is the cause | **Ruled out** | Graph was already empty at kill time (#97); loading the real decrypted graph measured 90 MB. |
| A heavier fallback embedder (torch / sentence-transformers) loads instead of fastembed | **Ruled out** | Audited `data/memory/embeddings.py` and every caller (`ast_indexer.py`, `docs_index.py`, `summarizer.py`, `doc_ingester.py`, `ops/cron/prune_memory.py`): fastembed/ONNX is the only embedding path in the codebase. No torch/sentence-transformers import exists anywhere outside `venv/`. |
| Individual subsystems (context_pack, MCP tool set, index-repo, background reindex, decrypted graph load, hook) | **Ruled out individually** | All measured ≤ 405 MB peak in the original issue's own RLIMIT_AS-capped tests. |
| `subgraph_around` hub-node blowup (earlier v1.1.0 QA P0) | **Not the cause here** | A cap already exists; issue notes hub nodes exist (`Mock` degree 1652) but this session's graph was empty at kill time. |
| Circuit breaker should have caught this before the kernel did | **Confirmed real bug, now fixed** | Default RSS limit was `80% of total RAM` (~12 GB on this 15 GB host) — mathematically could never trip before a 5.2 GB death. Fixed in #102: `min(80%, 3072 MB)` + a server-side watchdog that evicts resources and trips the breaker at 75%/100% of the (now sane) limit. This is a safety net, not the root cause fix. |

## 3. Repro attempt (2026-09-29)

**Method:** real `cognirepo serve --project-dir <copy of cognirepo_test_repo/medium/celery>`,
launched under `systemd-run --user --scope -p MemoryMax=3G --property=MemorySwapMax=0` (protects
the host if a real leak reproduces), driven over real MCP stdio with the exact tool sequence the
original e2e names: `get_session_brief → get_last_context → get_user_profile →
get_error_patterns → get_agent_bootstrap → context_pack → lookup_symbol → who_calls →
episodic_search → check_precedent`, 3 s between calls, then 90 s idle watch. RSS sampled every 1 s
via `/proc/<pid>/status`. Branch under test: `fix/COGNIREPO-98-memory-guard` (mitigation applied
but not yet triggered at this scale).

**Result:** peak RSS **457 MB**, plateaued after the sequence finished, no growth during the 90 s
idle watch, clean shutdown (SIGTERM). Did **not** reproduce the reported 5.2 GB.

**Side finding (not the OOM cause, noted for hygiene):** the copied fixture's
`.cognirepo/memory/semantic_metadata.json` was invalid JSON — a leftover from whatever crashed
the original session — and `core/vector_db/local_vector_db.py::_load_meta()` correctly detected
it, backed it up to `.corrupt`, and started fresh with `[]`. This file is tiny (hundreds of bytes,
FAISS-local-backend-only per `project_memory.py`'s own comment; this project's config uses the
`chroma` backend) and unrelated to the reported chroma/FAISS store recreation the issue flags as
a lead — that lead (§"Not yet tested / leads" in #98) is still open.

**Why this likely didn't reproduce:** the fixture is a partial checkout (127 MB on disk, 444
files) vs. whatever the reporter's actual celery checkout was at incident time; the sequence was
a single short session (~35 s of activity + 90 s idle) rather than a real multi-hour Claude Code
session with file edits flowing through the watcher; and the reported kills happened around
"MCP reconnect" and "first e2e prompt" specifically — timing this repro didn't attempt to match
(process restart / reconnect churn, concurrent `serve` instances from Claude + Gemini per
`org_graph.pkl`'s multi-agent design, or a leak that needs sustained watcher-driven reindex
churn rather than a handful of read-only tool calls).

## 4. What's left (next steps, from #98's own plan, not yet done)

1. Reproduce under the *real* Claude Code session shape, not just direct tool calls: multiple
   concurrent `serve` processes (Claude + Gemini, per the org-graph multi-agent design in
   CLAUDE.md), an MCP reconnect mid-session, and a longer watcher-driven edit stream, still
   under `systemd-run ... -p MemoryMax=3G` with `py-spy`/`tracemalloc` attached (not available
   in this environment — `py-spy` needs to be installed first).
2. If reproduced, get an allocation profile (`tracemalloc` snapshot diff, or `py-spy dump`) at
   the point RSS crosses ~1 GB, not just a peak number.
3. Confirm behavior on a genuinely clean install (stale editable install was fixed mid-incident
   per the original issue — #100 now makes `doctor` catch that class of problem, but it's worth
   re-confirming a clean install doesn't itself contribute, e.g. via duplicate module instances).
4. Watch whether the mitigation in #102 (watchdog + 3 GB cap) is sufficient in practice even
   without knowing the root cause — if it now always evicts/trips before 3 GB, the user-visible
   symptom (host OOM-kill) is gone even if the underlying allocation pattern remains uninvestigated.

## 5. Artifacts

Repro harness and raw RSS samples from this run: kept in the session scratchpad, not committed
(temporary, machine-specific paths) — rerun via the method in §3 against any fixture repo to
regenerate.
