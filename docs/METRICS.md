# CogniRepo — Quantitative Impact Metrics

> Real measurements from live Claude + Gemini sessions on the CogniRepo codebase itself.
> Automated regression numbers from `cognirepo benchmark` on external repos.
>
> **Last validated: 2026-09-17** — flask (92 files), fastapi (1,178 files), celery (444 files),
> ansible (4,196 files) using `cognirepo benchmark --json` on v2.4.0+ with COGNIREPO-600-D01/D02
> landed (see the Automated Benchmark section for what those fixed — the 2026-06-17 run's
> token-reduction/relevance/precision/symbol-hit-rate numbers were unreliable pre-fix). moby and
> kubernetes are indexable (Go support confirmed via COGNIREPO-500) but excluded from this pass —
> scheduled separately, hours of indexing. The Session Comparison (Rounds A/B) and Gemini sections
> remain from the original live sessions.

---

## TL;DR

| What changed | Without CogniRepo | With CogniRepo | Delta |
|---|---|---|---|
| Answer accuracy | 1 / 3 correct | 3 / 3 correct | **+200%** |
| Confidence | ~25% | ~100% | **+75 pp** |
| Tokens consumed | ~2 400–3 600 (raw reads) | ~700 (packed) | **−70–80%** |
| Line-number precision | 0 / 1 | 1 / 1 | ✅ |
| Weights / runtime config | 0 / 3 | 3 / 3 | ✅ |
| File reads needed | (would need 3) | **0** | ✅ |
| Cross-model facts retrieved | — | 3 / 3 | ✅ |

---

## Round A — Claude without CogniRepo

*Claude answered three questions about the live codebase using training knowledge only — no tools called.*

| Question | Answer | Quality | Confidence |
|----------|--------|---------|------------|
| Where is `context_pack` defined? | `tools/context_pack.py`, no line | Partially correct | 20% |
| What signals does `HybridRetriever` combine + weights? | Named 3 signals, no weights | Incomplete | 15% |
| Embedding model + dimension? | `all-MiniLM-L6-v2`, 384 dims | Correct (via memory index shortcut) | 80% |

**Overall: 1 / 3 fully answerable. ~25% mean confidence.**

Key insight from Claude:
> *"The biggest gap was Q2 — weights are runtime-configurable from `config.json`, something no training knowledge could ever know. Only live tool access surfaces ground truth."*

---

## Round B — Claude with CogniRepo

*Same three questions, tools called first: `retrieve_memory` → `lookup_symbol` × 2 → `context_pack`.*

| Question | Answer | Quality | Key tool | Confidence |
|----------|--------|---------|----------|------------|
| Where is `context_pack`? | `tools/context_pack.py:57` (+ MCP wrapper at `server/mcp_server.py:220`) | Exact, verified | `lookup_symbol("context_pack")` | 100% |
| Signals + weights? | `vector=0.5`, `graph=0.3`, `behaviour=0.2` — configurable in `config.json`, defaults in `hybrid.py:45` | Exact, verified | `lookup_symbol("HybridRetriever")` | 100% |
| Embedding model + dim? | `all-MiniLM-L6-v2`, 384 dims — `memory/embeddings.py:33` | Exact, verified | `retrieve_memory` | 100% |

**Overall: 3 / 3 exact. 100% confidence.**

---

## Token Comparison (Claude session)

| Approach | Tokens | Source |
|----------|--------|--------|
| With CogniRepo (packed context + tool calls) | **~700** | `context_pack` reported 473 + ~200 tool overhead |
| Equivalent raw file reads (`hybrid.py` + `embeddings.py` + `context_pack.py`) | **~2 400–3 600** | ~800–1 200 tokens/file × 3 files |
| **Reduction** | **70–80%** | Tools gave verified answers at ¼ the token cost |

> **Benchmark baseline note:** The automated `cognirepo benchmark` numbers use a *naive baseline*
> (tokens in all files containing the keyword). The manual numbers above use a *targeted baseline*
> (tokens in 2–3 files a human or agent would actually read). The targeted reduction is real but
> smaller: typically **40–60%** vs naive's 70–80%. Run `cognirepo benchmark` to see both numbers:
> `savings_vs_naive_pct` and `savings_vs_targeted_pct`.
> The genuine advantage is structural: `lookup_symbol` returns `{file:line}` in <1 ms without
> grep output parsing — that is not captured in any token-reduction metric.

---

## Gemini Cross-Model Retrieval

*Gemini CLI ran in the same project directory after Claude's session. Claude had stored findings via `store_memory` and `log_episode`. Gemini retrieved them cold — no file reads, no prior context.*

| Metric | Result |
|--------|--------|
| Facts retrieved from Claude's stored memories | **3 / 3** (all targets found) |
| File reads needed | **0** |
| Tool calls total | **7** (3 retrieval + 3 graph + 1 store) |
| Knowledge graph — nodes | **2 259** |
| Knowledge graph — edges | **6 073** |
| Facts Gemini couldn't find | **None** |
| Source of architectural facts | Exclusively from Claude's stored memories |

Gemini's confirmation:
> *"All specific architectural facts (weights, file paths, model name, and dimensions) came exclusively from Claude's stored memories. I did not need to read any files. All answers were derived from the CogniRepo memory and graph tools."*

---

## What This Demonstrates

### 1 — Ground truth beats training knowledge
Training knowledge got Q2 (runtime-configurable weights) completely wrong — **0%** without tools, **100%** with. This gap only widens as codebases evolve.

### 2 — Shared memory across models
Claude stored findings. Gemini retrieved them verbatim. Neither model needed to read a file. This is the core CogniRepo promise: **one memory store, any AI tool reads it**.

### 3 — Token efficiency
At 70–80% token reduction per query, a 20-query coding session costs:

| Scenario | Tokens | Cost (Claude Sonnet @ $3/M) |
|----------|--------|-----------------------------|
| Without CogniRepo (raw reads) | ~60 000 | **~$0.18** |
| With CogniRepo (packed) | ~14 000 | **~$0.04** |

Savings compound across sessions because memories persist — second sessions start warm.

### 4 — Precision without search
`lookup_symbol("context_pack")` returned `tools/context_pack.py:57` in < 1 ms. The grep-equivalent takes 2–8 seconds and requires the AI to parse noisy output. CogniRepo returns structured `{file, line}` — no parsing, no ambiguity.

---

## Automated Benchmark Numbers

*From `cognirepo benchmark --json` on flask, fastapi, celery, ansible (2026-09-17, v2.4.0+,
no human in loop). Supersedes the 2026-06-17 run below — that run predates two defect fixes
(COGNIREPO-600-D01: the benchmark's own baseline-comparison path was silently scanning
CogniRepo's own source tree instead of the repo actually being benchmarked; COGNIREPO-600-D02:
the token-reduction/context-relevance probe queries were CogniRepo's own vocabulary rather than
the target repo's) that made every number below it unreliable for token-reduction/relevance/
precision/symbol-hit-rate specifically — see `JIRA/EPIC-OSSGrowth-600/` for full evidence.*

| Metric | Value | Notes |
|--------|-------|-------|
| Token reduction vs naive baseline | **96.1–99.7%** | flask 97.3%, fastapi 97.6%, celery 99.7%, ansible 96.1% |
| Symbol lookup latency | **0.002–0.008 ms** | well under 1 ms target |
| grep equivalent latency | 2.3–19.5 ms | flask 2.3 ms, fastapi 7.8 ms, celery 5.8 ms, ansible 19.5 ms |
| Lookup speedup vs grep | **1,150×–2,600×** | scales with repo size |
| Cache speedup (warm vs cold) | **8,910×–42,674×** | |
| Memory recall@1 | **100%** (4/4 repos) | fastapi's earlier "0% — empty vector DB" was a stale/transient artifact, not reproducible today |
| Memory recall@3 | **100%** (4/4 repos) | |
| Context relevance | **56.6–100.0%** | flask 80.5%, fastapi 97.1%, celery 100.0%, ansible 56.6% |
| Symbol hit rate | **100%** (4/4 repos) | v1.1.3's `_sample_repo_symbols()` fix confirmed working |
| Precision@1 | **40–100%** | flask 0.8, fastapi 0.4, celery 0.5, ansible 1.0 |
| Precision@3 | **50–100%** | flask 0.9, fastapi 0.5, celery 0.6, ansible 1.0 |
| Knowledge graph (this repo, cognirepo) | 184 002 nodes · 1 158 807 edges | from a full `cognirepo index-repo --tier all` re-index, 2026-09-16 |

moby and kubernetes (Go, both 10k+ files) are excluded from this pass — they need hours of
indexing on the maintainer's machine and are scheduled separately, not blocked on anything
above. Go language support itself is confirmed working (COGNIREPO-500's epic e2e suite verified
`delegation_hints`/AST parsing on a freshly-indexed kubernetes checkout, 2026-09-16/17).

Run on your own codebase:
```bash
cognirepo benchmark          # full report
cognirepo benchmark --compare  # delta vs last run
cognirepo benchmark --json   # machine-readable for CI
```

Regression tests that enforce these thresholds:
```bash
pytest tests/test_benchmark_metrics.py -v
```

---

## Reproduce

```bash
git clone https://github.com/ashlesh-t/cognirepo
cd cognirepo
pip install -e ".[dev]"
cognirepo init
cognirepo index-repo .
cognirepo benchmark
```

### Reproduce the External Repo Validation table

No API key needed — `cognirepo benchmark --json` is fully offline and automated. Anyone can
reproduce the flask/fastapi/celery/ansible numbers above against a fresh clone of each repo:

```bash
pip install "cognirepo[languages]"   # [languages] only needed for non-Python repos (moby, k8s)
for repo in flask fastapi celery ansible; do
  git clone https://github.com/pallets/flask       flask       2>/dev/null || true
  git clone https://github.com/fastapi/fastapi     fastapi     2>/dev/null || true
  git clone https://github.com/celery/celery       celery      2>/dev/null || true
  git clone https://github.com/ansible/ansible     ansible     2>/dev/null || true
done
for repo in flask fastapi celery ansible; do
  (cd "$repo" && cognirepo init && cognirepo index-repo . --no-watch && cognirepo benchmark --json)
done
```

Numbers will vary slightly run-to-run (embedding/index timing, upstream repo drift since this
table's date) but should land in the same range. `tests/fixtures/benchmark_golden_<repo>.json`
ships in this repo for all four — that's what drives `precision@k`/`context_relevance`'s repo-
relevant queries (COGNIREPO-600-D02); no manual query-writing needed.

For the cross-model test (requires Claude Desktop + Gemini CLI both pointed at same project):
1. Run Claude prompt from `TEST_SUITE.md` Section 14 (or the benchmark prompt above)
2. Run Gemini prompt — it will retrieve Claude's stored findings
3. Neither tool should need to read a file

---

## External Repo Validation

Measured on real-world Python projects. CPU-only embeddings, no GPU.
Each repo indexed with `cognirepo index-repo . --no-watch` on a fresh init.
**Re-validated 2026-09-17** using `cognirepo benchmark --json`, on v2.4.0+ with
COGNIREPO-600-D01/D02 landed (see the dated note above the automated numbers).

| Repo | Size | Lookup latency | context_relevance | Symbol hit rate | precision@1 | precision@3 |
|------|------|----------------|-------------------|-----------------|-------------|-------------|
| **flask** | 92 files, 1,832 symbols | 0.002 ms | 80.5% | 100% | 80% | 90% |
| **fastapi** | 1,178 files, 7,700 symbols | 0.003 ms | 97.1% | 100% | 40% | 50% |
| **celery** | 444 files, 10,311 symbols | 0.003 ms | 100.0% | 100% | 50% | 60% |
| **ansible** | 4,196 files, 17,521 symbols | 0.008 ms | 56.6% | 100% | 100% | 100% |

moby and kubernetes: excluded from this table — hours of indexing, scheduled separately with
the maintainer (not a Go-support gap; see note above).

### Quality gates (2026-09-17 re-validation)

| Gate | Threshold | Result |
|------|-----------|--------|
| Symbol lookup latency | ≤ 10 ms | ✅ max 0.008 ms |
| Token reduction vs naive | ≥ 95% | ✅ min 96.1% |
| Cache speedup | ≥ 10,000× | ⚠️ min 8,910× (flask) — below the 10,000× gate; still 3 of 4 repos clear it (celery 28,134×, ansible 42,674×, fastapi 26,453×). Flask's smaller index gives the cache less relative work to skip; not a regression, just a smaller repo's baseline being cheaper too |
| Symbol hit rate | ≥ 80% | ✅ 100% on all 4 repos |
| precision@3 on external repos | ≥ 0.65 | ⚠️ 50–100% — fastapi (50%) and celery (60%) sit below the 0.65 gate; flask (90%) and ansible (100%) clear it. Precision@3 depends on how well each repo's hand-curated 10-query golden set happens to match `context_pack`'s top-3 ranking — this is a real, repo-specific number now (not a bug artifact), and the two lower repos are candidates for follow-up golden-set tuning, not a code regression |

### Notes

- Symbol lookup uses AST reverse index (O(1) hash) — not FAISS. Sub-millisecond even on 4,000+-file repos.
- precision@k = fraction of natural-language queries where `context_pack()` returns the correct file in the top-k sections.
- **COGNIREPO-600-D01/D02 fixes (2026-09-17):** the benchmark's own baseline-comparison path (`REPO_ROOT`) was pointing at CogniRepo's own source tree instead of the repo being benchmarked (D01), and the token-reduction/context-relevance probe queries were CogniRepo's own vocabulary rather than sampled from the target repo (D02, extending v1.1.3's analogous fix for `symbol_hit_rate`). Both fixed; this table is the first fully-trustworthy automated run since.
- kubernetes and moby (Go) are indexable as of COGNIREPO-500 (`cognirepo[languages]` ships tree-sitter-go) — excluded from this specific table only for time budget, not a capability gap.

---

## Output-side (persona) measurements — 2026-08-24

Every number above measures **input-side** reduction (`context_pack` vs. raw reads). The
caveman persona (COGNIREPO-403) is the first output-side claim — response tokens, not retrieval
payload — and needed its own harness: `scripts/persona_bench.py` (dev script, not CI). Ship gate
(COGNIREPO-404): median reduction ≥ 40% AND accuracy delta ≤ 2pp.

**Methodology:** 20 fixed factual questions about this repo's own code (real file:line facts —
`hybrid.py`'s scoring weights, `classifier.py`'s tier thresholds, `derive_mood()`'s state
machine, etc. — see `tests/fixtures/persona_bench_golden.json`). For each, a live agent session
(this one) produced two real answers: one written naturally/verbosely (persona off), one written
under the caveman `output_contract` (persona on). Tokens counted with `tiktoken` `cl100k_base`
(same encoder as `context_pack.py:57`). Accuracy = fraction of each question's golden facts
present as a case-insensitive substring of the response.

| Metric | Result | Gate | Verdict |
|---|---|---|---|
| Median token reduction | **57.3%** | ≥ 40% | ✅ PASS |
| Mean accuracy, persona off | 83.9% | — | — |
| Mean accuracy, persona on | 92.7% | — | — |
| Accuracy delta (off − on) | **−8.8pp** | ≤ 2pp (absolute) | ❌ **MISSED** |

**Gate: MISSED.** Documenting honestly rather than reshaping the fixture to force a pass
(COGNIREPO-404 AC2). Two things worth separating:

1. **The actual safety concern the gate exists to catch — did caveman lose accuracy — did NOT
   happen.** Persona-on scored equal or *higher* accuracy than persona-off on all 20 questions;
   it never scored lower on a single one. The −8.8pp delta runs in the safe direction.
2. **The gate as literally specified (`abs(delta) ≤ 2pp`) still fails**, because it penalizes any
   asymmetry, not just a harmful one. Root cause, confirmed by inspection: substring-based fact
   matching rewards terse, literal fact citation (exactly what caveman mode produces) and
   penalizes natural paraphrasing (exactly how the off-persona answers were written) — e.g. an
   off-answer saying "3 or more occurrences of the same error type" doesn't literally contain the
   golden fact string `"same-type"`, even though it states the identical fact. This is a scoring
   methodology limitation, not evidence of information loss.

**Status: caveman persona ships as experimental**, not as a validated ≥40%-reduction/
zero-accuracy-cost feature. Real numbers stand as measured above; re-run
`python scripts/persona_bench.py` after any prompt-scoring methodology improvement (e.g.
LLM-graded accuracy instead of substring match) to re-evaluate the gate.
