# COGNIREPO-602 — Contribution funnel

Epic: COGNIREPO-600 · Branch: story/COGNIREPO-602 · Base: development
**Outward-facing: opening GitHub issues requires explicit user go-ahead per batch.**

## Backstory
Root CONTRIBUTING.md is nearly empty (one section, "Why two files?" :8); the real recipes live
in docs/DEVELOPER_GUIDE.md (§36 add-a-tool, §100 add-a-language, §162 add-a-CLI-command, §184 PR
checklist). No good-first-issue on-ramp exists. The audit produced ready seeds: Ruby/PHP/C#/Swift
grammar mappings (README.md:632 + DEVELOPER_GUIDE recipe), plus any COGNIREPO-106 leftovers.
Evidence: ../../COGNIREPO-600-Discovery.md §3.

## Description
(1) CONTRIBUTING.md gains a funnel section: how to pick a `good first issue`, links to the
DEVELOPER_GUIDE recipes, expectations (tests, PR checklist). (2) Issue templates
(.github/ISSUE_TEMPLATE: bug, feature, good-first-issue task). (3) Draft ≥8 good-first-issue
texts from the Discovery seed list — each with context, files, acceptance criteria, recipe link —
and open them on GitHub AFTER user approval.

## Acceptance criteria
1. CONTRIBUTING funnel section merged; no dead links.
2. Templates render on GitHub.
3. ≥8 labeled issues open (post-approval), each self-sufficient for a newcomer.

## Risks / notes
- Do NOT duplicate issues for work already ticketed in JIRA/ epics — good-first-issues are the
  small, non-roadmap items only.
