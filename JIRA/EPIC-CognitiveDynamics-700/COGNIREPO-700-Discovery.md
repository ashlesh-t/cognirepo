# COGNIREPO-700 Discovery — Cognitive Dynamics (neuroscience-inspired memory + judgment)

Verified against HEAD (`a79905f`, v2.2.0, `development`) on 2026-08-24, via two parallel
codebase audits plus targeted web research. This epic descends from a discussion that started
as "give CogniRepo consciousness" and was deliberately narrowed to what's actually buildable —
see §0 for what got rejected and why, before the four real findings in §1-§4.

---

## 0. Rejected: quantum/qubit substrate

The originating idea proposed representing CogniRepo's information as qubits, reasoning from
real neuron action-potential physics (resting -70mV, threshold -55mV, spike to +30mV, all-or-
none, rate coding) toward "what if we did this with quantum bits instead of classical weights."
Checked and rejected on two independent grounds:

1. **The neuroscience doesn't support a quantum substrate for cognition.** The only real theory
   proposing brain-level quantum effects — Penrose & Hameroff's Orchestrated Objective Reduction
   (Orch-OR), which claims microtubule quantum coherence underlies consciousness — is fringe, not
   consensus. MIT's Max Tegmark computed the actual decoherence timescale for warm, wet neural
   tissue at sub-picoseconds, roughly 9 orders of magnitude shorter than the millisecond
   timescale neural processing actually operates on. This is treated as the theory's fatal flaw
   by most of the field (Reimers et al. critique; see also PMC5681944 "Revisiting the Quantum
   Brain Hypothesis").
2. **Even if true, it wouldn't transfer.** No proposed mechanism connects spike-rate coding to
   qubit-state representation — "the brain might use quantum effects" and "quantum computing as
   a classical-computation alternative" are two unrelated ideas bridged only by both containing
   the word "quantum."
3. **Practical wall specific to this repo:** CogniRepo's identity is local-first, offline,
   zero-cost (FAISS + ONNX on-device, per README). Quantum hardware today is cloud-only,
   NISQ-era, accelerates narrow algorithms (factoring, some simulation/optimization), and is not
   general-purpose — there is no offline-compatible version of "represent memory as qubits."

Also checked and found mismatched: the user's original PMC citation for the spike-physiology
facts (PMC6608126) is not actually about electrophysiology — it's an fMRI study of moral
judgment (amygdala vs. ventromedial prefrontal cortex). The spike-physiology facts themselves are
accurate textbook neuroscience; they just weren't sourced from that particular paper. Flagging
so it doesn't get miscited downstream.

**What survived the cut**: three genuinely mainstream, well-cited neuroscience mechanisms that
map cleanly onto real code gaps found in this repo (§1-§3), plus a separate software-discipline
idea from an earlier discussion, folded into this epic at the user's request (§4).

---

## 1. Reward-modulated salience has no decay (→ story 701)

`data/graph/behaviour_tracker.py`: `symbol_weights[sym]["hit_count"]` is a raw, monotonically
incrementing counter — incremented at `record_feedback()` line 354 (`sw[sym]["hit_count"] += 1`)
with **zero decay applied anywhere in the file**. `get_hot_symbols()` (lines 654-663) sorts purely
by this raw count (line 662). `get_all_scores()` (lines 669-671) returns `{symbol_id: hit_count}`
verbatim. The only decay-like mechanism in the file is unrelated: `record_feedback()` line 357
(`new_score = min(1.0, old_score * 0.95 + 0.1)`) is an event-triggered EMA update on the
*separate* `relevance_feedback` field — not time-based, and not read by any scoring path.
`last_hit` (line 355, `sw[sym]["last_hit"] = _now()`) is written but **never read back anywhere**
— pure write-only telemetry today.

Consumer: `intelligence/retrieval/hybrid.py::HybridRetriever._behaviour_score` (a `@staticmethod`,
lines 424-436) takes this same raw `hit_count` (via `all_counts = self.behaviour.get_all_scores()`
at line 134) and log-normalizes it against the corpus max: `math.log(1+raw) / math.log(1+max_count)`
(line 436) — **no recency weighting anywhere in the retrieval path**. This score then feeds the
overall blended formula in `_score_candidates` (lines 316-353): cold-start path uses
`vector*0.7 + importance*0.3` when graph and behaviour scores are both 0 (lines 333-334); warm
path blends `vector*0.5 + graph*0.3 + behaviour*0.2` (weights from `_load_weights()`, lines
55-67, default `DEFAULT_WEIGHTS` line 47) scaled to 0.85 of the total plus `importance*0.15`
(lines 335-342). A symbol hit heavily once, long ago, permanently outranks one hit consistently
every week since — there is no mechanism to prefer current relevance over historical volume.

**Neuroscience parallel**: reward-modulated spike-timing-dependent plasticity (STDP) with
eligibility traces solves exactly this class of problem in biological learning — a synaptic
eligibility trace decays over seconds after coincident pre/post-synaptic firing, and is only
consolidated into a lasting change if a delayed reward signal (dopamine) arrives while the trace
is still positive (the "distal reward problem"). Citations:
- Izhikevich, E.M. (2007). "Solving the Distal Reward Problem through Linkage of STDP and
  Dopamine Signaling." *Cerebral Cortex* (PubMed 17444757).
- Frontiers in Neural Circuits (2015). "Neuromodulated Spike-Timing-Dependent Plasticity, and
  Theory of Three-Factor Learning Rules." doi:10.3389/fncir.2015.00085 — formalizes the
  pre-synaptic + post-synaptic + modulatory-signal "three-factor" structure that maps onto
  `hit_count` (activity) + recency (trace decay) + usefulness feedback (modulatory signal).

**Verdict**: KEEP as story 701 — real gap, concrete file:line hook, directly serves the
project's own retrieval-quality mission.

---

## 2. Episodic accumulation never gets consolidated (→ story 702)

Three independent memory surfaces exist and none of them promote raw episodes into durable
knowledge automatically:

- **Episodic log** — `data/memory/episodic_memory.py`, persisted at `.cognirepo/memory/
  episodic.json`. `log_event()` (lines 213-229) appends flat `{id, event, metadata, time, prev}`
  dicts, no schema enforcement, no clustering. `record_decision()`
  (`interface/server/mcp_server.py:646-670`) is a thin wrapper writing into this *same* flat
  list with `metadata["type"]="decision"` (lines 661-669) — decisions and ordinary episodes are
  structurally identical, distinguished only by that one metadata flag, and its docstring
  explicitly gates promotion on manual agent judgment ("Call when a non-obvious architectural
  decision is made... Do NOT call for routine changes", lines 655-657). No code path anywhere
  calls `record_decision` programmatically.
- **Semantic memory** — `data/memory/semantic_memory.py`, a FAISS-backed vector store (`store()`
  lines 50-60, `retrieve()` lines 62-67) — structurally separate storage, addressed by similarity
  not by event schema.
- **`BehaviourTracker.summarize_interaction_style()`** (`data/graph/behaviour_tracker.py:
  675-723`) is the one auto-triggered summarization in the codebase (every 10 queries, line 109
  `_STYLE_SUMMARIZE_EVERY`, invoked at line 325-326) — but it only reads its own transient
  `interaction_style.query_patterns` ring buffer (never touches `episodic.json`), writes one
  generic natural-language blob to semantic memory via the injected `store_fn` (line 706), and
  **prunes its own source buffer afterward** (lines 718-719) — it consolidates query *style*, not
  episodic *content*.
- **`decision_nudge`** (`interface/server/mcp_server.py:1953-1964`, surfaced in
  `get_agent_bootstrap` at lines 2005-2006) is the closest existing prior art for "the system
  notices the accumulation-without-promotion gap": it calls `timeline.merge(since="30d",
  limit=200)` + `rollup()` and fires a static text nudge purely on `counts["decision"]==0 AND
  counts["episode"]>=5` — no inspection of *which* episodes are repeating, no clustering, no
  automatic remediation, just a threshold-triggered string.

Search infrastructure already exists to build on: `search_episodes()`
(`data/memory/episodic_memory.py:332-376`) does BM25Plus keyword search with a vector-similarity
fallback (lines 350-369) — the similarity primitive a clustering pass would need already lives
here, just isn't used for consolidation.

**Neuroscience parallel**: Complementary Learning Systems theory — the hippocampus rapidly
encodes novel experience (one-shot), which is then gradually consolidated into neocortex during
rest/sleep via replay, producing generalized, structured knowledge from repeated raw experience.
This is not a decorative analogy — it directly inspired DeepMind's experience-replay mechanism in
DQN, explicitly cited as such. Citations:
- McClelland, J.L., McNaughton, B.L., O'Reilly, R.C. (1995). "Why there are complementary
  learning systems in the hippocampus and neocortex: insights from the successes and failures of
  connectionist models of learning and memory." *Psychological Review* 102(3):419-457 (PubMed
  7624455).
- Mnih, V. et al. (2015). "Human-level control through deep reinforcement learning." *Nature*
  518:529-533 — the experience-replay mechanism.
- Hassabis, D., Kumaran, D., Summerfield, C., Botvinick, M. (2017). "Neuroscience-Inspired
  Artificial Intelligence." *Neuron* 95:245-258 — states directly: "experience replay was
  directly inspired by theories that seek to understand how the multiple memory systems in the
  mammalian brain might interact," citing the hippocampus/neocortex complementary-systems account
  above.
- HMS News, "How Does the Brain Make Decisions?" (hms.harvard.edu/news/how-does-brain-make-
  decisions) — the mouse-maze reinforcement-learning study the user originally found; corroborates
  the reward-prediction framing (Uchida lab dopamine work) motivating this whole research thread.
  (Direct fetch was blocked by the site's bot-detection; content verified via independent search
  results, including Harvard Gazette and ScienceDaily coverage of the same underlying research.)

**Verdict**: KEEP as story 702 — genuine gap with the clearest, most citable neuroscience-to-AI
lineage of the four findings (this is literally the same theory that produced DQN's experience
replay).

---

## 3. Tier classification discards its own confidence (→ story 703)

`intelligence/orchestrator/classifier.py::_compute_score()` (lines 244-297) additively
accumulates a scalar score from independent signals — reasoning keywords (+3.0/hit, lines
252-256), lookup keywords (-2.0/hit, lines 258-262), vague referents (+2.0/hit, lines 264-268),
cross-entity count (+1.5 per entity beyond 2, lines 270-275), context-dependency (+3.0 binary,
lines 277-283), token-length excess (+0.5 per 10 tokens beyond 20, lines 285-290), and
imperative+abstract combination (+5.0 binary, lines 292-295) — each contribution recorded into a
`signals` dict for audit. `_score_to_tier()` (lines 300-307) then maps the final scalar onto four
fixed decision boundaries: `_TIER_QUICK=2.0`, `_TIER_STANDARD=4.0`, `_TIER_COMPLEX=9.0` (lines
92-94), everything above → EXPERT. Hard overrides bypass or floor this for single-token queries,
docs-pattern matches, "full context" phrasing, and error-trace regex matches (lines 207-224).

This is, structurally, already a **bounded evidence-accumulation model** — independent evidence
sources summed until a threshold is crossed, exactly the computational shape of classic
perceptual decision-making models. But only the final tier label survives to the caller; how
close the accumulated score was to a boundary (e.g., 3.9 vs. the 4.0 STANDARD/COMPLEX boundary —
a coin-flip classification) is discarded. There's no way for a downstream consumer to know a
classification was decisive vs. a near-miss.

**Neuroscience parallel**: evidence-accumulation / bounded decision models, most rigorously
characterized in the posterior parietal cortex (specifically area LIP) — neurons ramp firing rate
in proportion to accumulated sensory evidence until reaching a fixed threshold that triggers a
decision, with the margin at threshold-crossing correlating with confidence/reaction time.
Citation:
- Gold, J.I., Shadlen, M.N. (2007). "The Neural Basis of Decision Making." *Annual Review of
  Neuroscience* 30:535-574 — the canonical review of this evidence-accumulation literature.
- Supporting general PPC context (non-decision-specific, but establishes the region holds
  multiple action/evidence options in parallel and its engagement scales down with familiarity/
  proficiency — relevant to why "margin" rather than raw score is the right output signal):
  Wikipedia, "Posterior parietal cortex" (consulted directly, not a primary citation but useful
  orientation — the PPC "plays an important role in planned movements, spatial reasoning, and
  attention," with activation decreasing as proficiency increases).

**Verdict**: KEEP as story 703 — smallest, lowest-risk story (purely additive output field, zero
change to existing tier-assignment behavior), but a real, currently-thrown-away signal.

---

## 4. No grounded pushback against contradicted precedent (→ story 704)

Folded into this epic at the user's request from an earlier round of this discussion (not itself
a neuroscience finding — a software-discipline gap, included here because the user asked for both
threads in one epic). The repo has every primitive needed to check "does this request contradict
something we already decided, already broke, or explicitly ruled out" — and nothing currently
runs that check before an agent complies with an instruction:

- `record_decision()` (`interface/server/mcp_server.py:646-670`) — every non-trivial
  architectural choice is queryable.
- `episodic_search()`/`search_episodes()` (`data/memory/episodic_memory.py:332-376`) — BM25 +
  vector-fallback search over the full decision/episode/error history.
- Defect tickets (`JIRA/EPIC-*/DEFECT/COGNIREPO-D*`) — every past root-caused mistake, on disk,
  file:line grounded by convention.
- CLAUDE.md's own invariants (storage under `.cognirepo/`, retrieval only via `hybrid.py`, model
  names only in `classifier.py`, tools stateless) — hard rules a request can silently violate
  today unless an agent happens to remember them.

**Live proof this gap is real, found during this epic's own audit**: the "model names live only
in `classifier.py`" invariant is *already violated* in current production code —
`interface/cli/key_probes.py:23,25` hardcodes `"claude-haiku-4-5"` as a fallback default (twice);
`intelligence/orchestrator/router.py:339,691` both hardcode the same literal inside
`_PROVIDER_DEFAULT_MODELS.get(provider, "claude-haiku-4-5")`; `intelligence/orchestrator/
model_adapters/gemini_adapter.py:38` defaults `model_id: str = "gemini-2.0-flash"`;
`intelligence/orchestrator/model_adapters/anthropic_adapter.py:48` defaults `model_id: str =
"claude-sonnet-4-6"` — none of these import from `classifier.py`'s `DEFAULT_MODELS_BY_PROVIDER`,
despite `classifier.py`'s own comment (lines 175-176) asserting `router.py` and `key_probes.py`
do. This drifted in unnoticed; a precedent-check that cross-references invariants before a
"let's just hardcode this here" change would have caught it. (Not fixed as part of this epic —
flagged to the user separately as a candidate defect for its own ticket.)

**Verdict**: KEEP as story 704, per explicit user instruction to fold this thread in. Weakest
neuroscience grounding of the four (this is a software-engineering-discipline idea, not derived
from the brain research), strongest concrete motivating evidence (the live invariant violation
above). Implementation shape intentionally left open for the story's own Analyze step — likely a
combination of (a) a documented CLAUDE.md protocol step instructing agents to check
`episodic_search`/decisions before complying with instructions that touch a known invariant or
prior mistake, and (b) a minimal, structured, machine-checkable invariants registry, since
CLAUDE.md's invariants are currently unstructured English prose that nothing can cross-reference
programmatically. The exact minimal-footprint design (extend `episodic_search`, or a small new
`invariants.yml` + lookup helper, or a new tool if neither suffices) is a call for the story's
Analyze step, not this Discovery doc.

---

## 5. Considered, deferred: amygdala dual-pathway error triage

LeDoux's dual amygdala pathway model (fast, crude thalamus→amygdala "low road," ~12ms, bypassing
conscious processing; slower, detailed thalamus→cortex→amygdala "high road" enabling nuanced
response) was considered as a 5th story: formalize `record_error`'s existing substring-matched
`_ERROR_HINTS` lookup (`data/graph/behaviour_tracker.py`, instant prevention-hint lookup by
error-type substring) as the "low road," paired with `get_error_patterns`'s cross-history
frequency analysis as the "high road."

**Dropped**: both paths already exist today in essentially this shape — the fast substring
lookup and the slower cross-history analysis are both already implemented and already used
together (a fresh error gets an instant hint; a recurring one surfaces via `get_error_patterns`).
Formalizing the pairing with neuroscience labels would be almost entirely documentation, not new
capability — it fails the same judgment filter epic 400 already applied to its own dropped
sentiment-label idea ("does this change what Claude does, or just what it says?"). Diluting a
four-story epic with a fifth, mostly-decorative story was judged not worth it. Revisit only if a
genuine behavioral gap between the two paths turns up later (e.g., the fast path currently never
escalates to the slow path automatically — that specific gap, if it matters in practice, would be
a real future story, not this one).

---

## 6. Citations summary (full list, for convenience)

1. Izhikevich, E.M. (2007). "Solving the Distal Reward Problem through Linkage of STDP and
   Dopamine Signaling." *Cerebral Cortex*. PubMed 17444757.
2. Frontiers in Neural Circuits (2015). "Neuromodulated Spike-Timing-Dependent Plasticity, and
   Theory of Three-Factor Learning Rules." doi:10.3389/fncir.2015.00085.
3. McClelland, J.L., McNaughton, B.L., O'Reilly, R.C. (1995). "Why there are complementary
   learning systems in the hippocampus and neocortex..." *Psychological Review* 102(3):419-457.
   PubMed 7624455.
4. Mnih, V. et al. (2015). "Human-level control through deep reinforcement learning." *Nature*
   518:529-533.
5. Hassabis, D., Kumaran, D., Summerfield, C., Botvinick, M. (2017). "Neuroscience-Inspired
   Artificial Intelligence." *Neuron* 95:245-258.
6. Gold, J.I., Shadlen, M.N. (2007). "The Neural Basis of Decision Making." *Annual Review of
   Neuroscience* 30:535-574.
7. HMS News. "How Does the Brain Make Decisions?" hms.harvard.edu/news/how-does-brain-make-
   decisions.
8. Rejected-substrate citation: Tegmark, M. — decoherence-timescale critique of Penrose-Hameroff
   Orch-OR (see §0); Wikipedia "Posterior parietal cortex" consulted for orientation only, not a
   primary source (§3).
