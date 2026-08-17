# COGNIREPO-301 — Insights data collector

Epic: COGNIREPO-300 · Branch: story/COGNIREPO-301 · Base: development

## Backstory
The insights report must be sourced from real records only: the merged timeline
(EPIC-200/COGNIREPO-204), git history via interface/tools/git_utils.py (git_log_patch :31,
_parse_since :86, structured parse :101 — branch listing NOT yet wrapped), behaviour hot symbols
(data/graph/behaviour_tracker.py:485-494), graph stats/integrity
(data/graph/knowledge_graph.py:358 + 201's integrity_report). Evidence:
../../COGNIREPO-300-Discovery.md §1.

## Description
New intelligence/orchestrator/insights_collector.py: collect(repo_root, since="90d") →
InsightsModel dict {meta, timeline, decisions, errors, branches, commits_by_week, hot_symbols,
index_health}. Add git_utils.list_branches() (name, last_commit, ahead/behind vs default) rather
than shelling out ad hoc. Every list empty ⇒ section {status:"no_data"} — never invented
content. Pure read-only aggregation; no MCP surface in this story.

## Acceptance criteria
1. On a fixture with seeded decision/error/branches: model contains them with real refs
   (episode id, commit hash).
2. Empty .cognirepo ⇒ all sections status:"no_data", git sections still real.
3. No FAISS/embedding calls anywhere in the collector (aggregation, not retrieval).
4. Unit tests for both fixtures.

## Risks / notes
- since-window parsing reuses _parse_since — don't reimplement.
- Depends on EPIC-200 signed off (get_timeline/merge available).

## Implementation notes (added during coding)
- Discovery's cited line numbers drifted at HEAD: `get_hot_symbols()` is now
  `data/graph/behaviour_tracker.py:577` (was 485-494); `KnowledgeGraph.stats()`/
  `integrity_report()` are now `data/graph/knowledge_graph.py:481`/`:492` (was 358). Logic
  unchanged, only line numbers moved.
- `intelligence/orchestrator/insights_collector.py` imports `interface/tools/git_utils.py`
  directly, per this ticket's explicit design — `git_utils.py` has no `@mcp.tool()` wrapper
  and is a plain subprocess helper, not an MCP entry point, so this doesn't violate CLAUDE.md's
  "tools are the single entry point" rule; it is the first `intelligence/` → `interface/`
  import in the repo, worth flagging if a future story wants to relocate `git_utils.py` to a
  lower layer.
- `collect()` scopes `.cognirepo` storage lookups (KnowledgeGraph/BehaviourTracker/get_path)
  to `repo_root` via a local `_scoped_to_repo()` context manager (ContextVar `_CTX_DIR` +
  `get_cognirepo_dir_for_repo`), mirroring `mcp_server.py::_repo_ctx` — reimplemented locally
  rather than imported, to avoid depending on `interface/server`.
- Added `git_utils.list_branches(repo_root)` — local branches via `git for-each-ref`, default
  branch resolved from `origin/HEAD` → local `main`/`master` → current `HEAD`, ahead/behind via
  `git rev-list --left-right --count`.
- `commits_by_week` reuses `git_log_patch(target=".", since=since, ...)` rather than adding a
  new git_utils helper — `--follow` is a no-op (not an error) against a directory target,
  confirmed against this repo's own history.
