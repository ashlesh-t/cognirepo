# COGNIREPO-303 — CLI command + MCP tool + self-indexing + CLAUDE.md amendment

Epic: COGNIREPO-300 · Branch: story/COGNIREPO-303 · Base: development

## Backstory
Wire 301+302 into the product following docs/DEVELOPER_GUIDE.md §162 (CLI command) and §36 (MCP
tool) — note: the recipe is in DEVELOPER_GUIDE.md, NOT CONTRIBUTING.md. The report must be
retrievable through CogniRepo's own search (dogfood), and the .claude/ storage location needs an
explicit CLAUDE.md rule amendment (Ground Rule: all storage under .cognirepo/ + two ~/.cognirepo
exceptions). Approved amendment wording: docs/planning/02-insights-feature.md
§Architecture-rule-compliance; fallback if the user rejects it: .cognirepo/insights/. Evidence:
../../COGNIREPO-300-Discovery.md §2-§4, §7.

## Description
(1) CLI: `cognirepo insights [--since 90d]` subparser + handler in interface/cli/main.py; docs
in CLI_REFERENCE.md. (2) MCP tool: generate_insights(since="90d", repo_path=None) →
{status, path, sections, updated_at} — registered in mcp_server.py; manifest regenerated via
COGNIREPO-101 generator; measured manifest token cost recorded on the PR (~130 expected);
docs/MCP_TOOLS.md entry. (3) Indexing: after write, ingest the markdown twin into the docs index
— FIRST verify whether intelligence/indexer/docs_index.py's ingestion root covers
.cognirepo/docs/; if not, call its ingest explicitly at generation time. (4) log_event("insights
generated", {path, sections}) so the timeline records it. (5) CLAUDE.md amendment PR section +
routing-table row ("Repo history report → generate_insights").

## Acceptance criteria
1. CLI exit 0, prints path; MCP tool returns the small payload (< 120 output tokens,
   tiktoken-tested).
2. search_docs("insights <seeded topic>") returns twin content post-generation.
3. Manifest/glama/openai artifacts include the tool (generated, drift test green).
4. CLAUDE.md amendment merged (or fallback path adopted — record the user's decision HERE).

## Risks / notes
- Amendment needs explicit user approval at review — outward-facing rule change.
- Claude must surface the link, not the content — the tool description should say so.
