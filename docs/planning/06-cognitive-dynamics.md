# Phase 6 planning — Cognitive Dynamics (EPIC-CognitiveDynamics-700)

## Origin

This epic came out of an open-ended discussion about giving CogniRepo something like
consciousness, deliberately narrowed down over several rounds. An early direction — representing
memory as quantum qubits, reasoning from real neuron action-potential physics toward "what if we
did this with quantum bits instead of classical weights" — was researched and rejected: the only
theory proposing brain-level quantum effects (Penrose-Hameroff Orch-OR) is fringe, and even its
proponents' math doesn't survive Max Tegmark's decoherence-timescale critique (quantum coherence
in warm neural tissue lasts sub-picoseconds; neural processing runs on milliseconds — a ~9 order
of magnitude gap). Full rejection reasoning: `JIRA/EPIC-CognitiveDynamics-700/
COGNIREPO-700-Discovery.md` §0.

What survived is three mainstream, heavily-cited neuroscience mechanisms that turned out to map
directly onto real gaps found by auditing this repo's own code — not decorative analogies bolted
onto existing features, but findings that only became visible *because* we went looking for the
neuroscience parallel first. A fourth idea (grounded pushback against contradicted precedent),
from a separate strand of the same discussion, was folded in at the user's request.

## Why these four and not others

Every neuroscience concept touched during the discussion was run through the same filter epic
400 already established: "does this change what the system does, or just what it says?" This
killed several candidates before they became stories:
- Sentiment-style "mood for the system" labels — decorative unless tied to an action (this
  filter is inherited directly from epic 400's own Discovery §5).
- The amygdala fast/slow dual-pathway idea — both paths (instant substring hint, deeper
  cross-history analysis) already exist in `record_error`/`get_error_patterns`; formalizing the
  pairing with neuroscience labels would be almost entirely documentation. Deferred, not killed
  outright — see Discovery §5 for the specific future gap that would resurrect it.
- The quantum substrate — killed on physics grounds, not the behavior-change filter (see above).

What passed the filter, in order of how directly it was checked against live code:
1. **Salience decay** (701) — the codebase literally has a raw, ever-incrementing hit counter
   with a *write-only, never-read* recency field (`last_hit`) sitting right next to it. The
   neuroscience (reward-modulated STDP + eligibility traces) didn't inspire looking for this gap
   in the abstract — it explained a gap that was already sitting there unused.
2. **Episodic consolidation** (702) — the strongest citation lineage of the four: Complementary
   Learning Systems theory (1995) directly inspired DQN's experience replay (2015), which is
   explicitly documented as such in a major neuroscience-AI review (Hassabis et al. 2017). The
   existing `decision_nudge` heuristic is clear prior art that the *problem* (episodes pile up,
   decisions don't) was already recognized — just never solved beyond a text nudge.
3. **Confidence-calibrated classification** (703) — the smallest, safest story: the classifier's
   scoring function is *already* structurally an evidence-accumulation model (Gold & Shadlen
   2007's framing describes it almost exactly); this story just stops throwing away a signal
   that's already computed.
4. **Precedent-check** (704) — different research lineage (software-engineering discipline, not
   neuroscience), included because the user wanted both discussion threads to land in one epic.
   Validated by a live example found during this epic's own Discovery: the "model names only in
   classifier.py" invariant is already silently violated in four places in production code.

## Sequencing

No hard dependency on any other epic (`blocked_by: []` in `JIRA/status.yml`) — 701/702/703 touch
`behaviour_tracker.py`/`hybrid.py`/`classifier.py`/episodic memory, none of which depend on
epic 400's mood/persona work. Internal order (701 → 702 → 703 → 704) is the JIRA one-branch-at-a-
time convention, not a code dependency — 704 can query `episodic_search`/`record_decision`
directly even if 702 hasn't shipped yet, though 702's consolidation candidates are one natural
future evidence source for it.

## Version

First version bump beyond the 2.0.1 → 2.4.1 sequence already used through epic 600 — this epic
targets **v2.5.0** on sign-off.

## What's explicitly out of scope

- Fixing the model-name-invariant violations found during this epic's audit (`router.py`,
  `key_probes.py`, `model_adapters/*.py`) — real, but a separate defect, not this epic's work.
- Any README changes — the research citations live in `COGNIREPO-700-Discovery.md` only, matching
  how every prior epic keeps audit evidence out of user-facing docs.
- A 5th story for amygdala-inspired error triage — see Discovery §5 for what would need to be
  true for this to become a real story later.
