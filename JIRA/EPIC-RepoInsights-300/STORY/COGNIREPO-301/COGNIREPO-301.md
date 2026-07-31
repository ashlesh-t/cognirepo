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
