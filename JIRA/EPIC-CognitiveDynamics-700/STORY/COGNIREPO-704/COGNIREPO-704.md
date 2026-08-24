# COGNIREPO-704 — Precedent-check / grounded pushback

Epic: COGNIREPO-700 · Branch: story/COGNIREPO-704 · Base: development

## Backstory
Folded into this epic at the user's explicit request, from an earlier round of discussion — not
itself derived from the neuroscience research (701-703 are), but included here as the same
"make CogniRepo an active participant, not a blind order-taker" thread. The repo already has
every primitive this needs: `record_decision()` (`interface/server/mcp_server.py:646-670`),
`episodic_search()`/`search_episodes()` (`data/memory/episodic_memory.py:332-376`, BM25 + vector
fallback), defect tickets (`JIRA/EPIC-*/DEFECT/COGNIREPO-D*`, file:line grounded by convention),
and CLAUDE.md's own invariants (storage under `.cognirepo/`, retrieval only via `hybrid.py`,
model names only in `classifier.py`, stateless tools) — but nothing today cross-checks a request
against any of them before an agent complies. Live proof this gap is real: this epic's own audit
found the "model names only in classifier.py" invariant already violated in production code —
`interface/cli/key_probes.py:23,25`, `intelligence/orchestrator/router.py:339,691`, and both
`model_adapters/gemini_adapter.py:38` / `anthropic_adapter.py:48` hardcode model-ID literals
outside `classifier.py`, contradicting `classifier.py`'s own comment (lines 175-176) claiming
`router.py`/`key_probes.py` import from it. Evidence: `../../COGNIREPO-700-Discovery.md` §4.

## Description
Before implementing a non-trivial instruction, check whether it contradicts a recorded decision,
a known defect's root cause, or a CLAUDE.md invariant — and if so, surface the conflict with a
citation (decision/defect id, or invariant name + file:line) and a concrete alternative, instead
of silently complying. Never auto-blocks: this surfaces dissent, it does not get a veto — the
human's final call still stands, same as the existing Gate 1/Gate 2 review model in `skill.md`
§F. Must fire ONLY on an actual recorded contradiction, never a vibe or a style preference — the
same judgment filter epic 400's Discovery applied ("does this change what gets done, or just
what gets said"). Implementation shape is intentionally left open for this story's own Analyze
step (per `skill.md` §F.1) — candidate approaches include extending `episodic_search`'s existing
surface with a decision-only filter, or introducing a small structured, machine-checkable
invariants registry (today CLAUDE.md's invariants are unstructured prose that nothing can
cross-reference programmatically) — prefer the option with the smallest footprint and zero/lowest
new-tool cost, per Ground Rule 3 discipline already applied elsewhere in this repo (epics 300,
400, 500).

## Acceptance criteria
1. Given a request that contradicts a specific recorded decision (`record_decision` entry) or a
   CLAUDE.md invariant, the check surfaces the conflict with a citation and a concrete alternative
   before implementation proceeds.
2. Given an ordinary request with no relevant precedent, zero friction — no false positives, no
   "well actually" on routine asks.
3. Never auto-blocks or refuses outright — always surfaces-and-defers; a test asserts the
   mechanism's output is advisory (a structured finding), not a hard stop.
4. Seed/validation case: running the check against a request to hardcode a model default outside
   `classifier.py` flags the pre-existing live violations found in this epic's Discovery
   (`router.py`, `key_probes.py`, `model_adapters/*.py`) as the concrete proof it works — this
   does NOT mean fixing those violations is in scope for this story (separate defect).

## Risks / notes
- Highest risk of the four stories: an over-eager version that fires on trivial requests becomes
  the annoying coworker who blocks every ask with "well actually" — tune firing threshold
  conservatively; when in doubt, don't fire.
- Do not fix the model-name-invariant violations found during Discovery as part of this story —
  that's a separate candidate defect ticket; this story only needs them as a validation fixture.
- Depends conceptually on 702's consolidation candidates as one possible evidence source (a
  precedent could be "the thing 702 flagged as a repeating pattern"), but does not have a hard
  code dependency on 702 shipping first — it can query raw `episodic_search`/`record_decision`
  directly if 702 isn't done yet.
