# COGNIREPO-400 Discovery — Agentic mood / persona layer (Phase 3)

Verified against HEAD (`146627d`, v2.0.0) on 2026-07-11.

---

## 1. Existing signals to derive "mood" from (no new subsystem needed)

All inputs already persist in the behaviour store (`data/graph/behaviour_tracker.py`):
- **Error rate / recurrence**: `record_error` (`:314`) accumulates `error_patterns` with
  `count`, `last_seen`, per-error occurrences; `get_error_patterns` (`:452-481`) already computes
  frequency-sorted patterns with prevention hints. Rising counts within a session ⇒ frustration
  signal.
- **Query velocity / repetition**: `record_query` (`:159-`) appends to `query_history` (with
  timestamps via `_now()`, `:35`) and `interaction_style.query_patterns`. Burst rate and
  near-duplicate queries are computable from existing data.
- **Retry pattern**: `query_rewrites` (`:417-448`) — explicit "user said X meant Y" corrections
  with `hit_count`; a growing hit_count mid-session ⇒ misalignment signal.
- **Momentum**: `record_file_edit` (`:270`) frequency + hot-symbol churn (`get_hot_symbols`,
  `:485-494`).

`get_user_profile()` (`:347-400`) already assembles `framing_hints` (depth preference, question
type, code-focus %, vocabulary) and is consumed per CLAUDE.md's behavioral rule ("apply
framing_hints to ALL responses") — the natural extension point: add a `mood` block to this
payload (zero new tool, zero manifest tokens) and mirror it in `get_agent_bootstrap`
(`mcp_server.py:1747`, which advertises itself as the ~300-token single-call replacement for
brief+context+profile+errors). A separate `get_agent_mood` tool would cost ~100-150 manifest
tokens and one extra required call — contradicts Ground Rule 3. **Discovery verdict: extend
existing payloads; no new tool.**

## 2. Classifier / tier substrate for the economy persona

`intelligence/orchestrator/classifier.py`: rule-based scoring → tiers QUICK (≤2) / STANDARD (≤4)
/ COMPLEX (≤9) / EXPERT (`:24`, `_TIER_QUICK=2.0` at `:92`, mapping at `:301-308`); QUICK always
resolves locally (`:136,152-154`). Model names live only here (CLAUDE.md invariant — persona
layer must NOT name models). The QUICK classification is a candidate *suggestion* signal for the
economy persona, but classification runs on retrieval queries, not on Claude's response
generation — so the persona trigger cannot be fully automatic from the classifier alone.

## 3. Output-side measurement gap (confirmed)

`docs/METRICS.md` measures **input-side** reduction only: TL;DR table (tokens consumed
2,400-3,600 → ~700 packed), automated benchmark = token reduction of `context_pack` output vs
naive/targeted read baselines (`:118-152`), latency, recall. **No harness measures response
(output) tokens**, and `interface/tools/benchmark.py` compares retrieval payloads, not
generations. An output-side harness is a new story: same prompt, persona on vs off, count
response tokens (tiktoken, consistent with `context_pack`'s counter at
`interface/tools/context_pack.py:56-57`), plus an accuracy gate — README.md:91 "Honest limits"
sets the bar: never trade accuracy for compression.

## 4. Persona layer shape (user decision constraints)

Per the task brief: backend tone signal + light persona layer, small named set, opt-in only.
Existing precedent for explicit preferences: `record_user_preference` /
`explicit_preferences` in the profile (`behaviour_tracker.py:402-415`) — a persona opt-in fits
there as a reserved preference key (e.g. `persona=caveman`), meaning **zero schema changes**:
set via existing `record_user_preference`, read via existing `get_user_profile`. CLAUDE.md
gains a short "personas" section telling agents how to honor it (docs change, no code
requirement on the agent side beyond reading the profile it already reads).

## 5. Judgement filter applied to candidate signals

"Would this change what Claude does, or just what it says?"
- error-streak (≥N same-type errors this session) → DOES change behavior: check
  `get_error_patterns` before proposing fixes, prefer verification steps. KEEP.
- query-velocity burst → changes retrieval depth (shallower, faster answers). KEEP (weak, mark
  experimental).
- sentiment-y labels ("happy"/"annoyed") with no action mapping → decorative. DROP.
- momentum (sustained edits, no errors) → permits terser confirmations / batching. KEEP as the
  positive pole of the same axis.

## 6. Risks noted for planning

- Mood inference from sparse data will be noisy on fresh repos — must degrade to "neutral" and
  say so (mirror `framing_hints`'s "no profile yet" fallback at `behaviour_tracker.py:384`).
- The UserPromptSubmit hook in this very repo already injects the behaviour profile into
  prompts — doubling signals (hook + bootstrap payload) risks conflicting instructions; the
  stories must define precedence (explicit user request > persona > framing_hints).
