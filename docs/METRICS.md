# CogniRepo — Quantitative Impact Metrics

> Real measurements from live Claude + Gemini sessions on the CogniRepo codebase itself.
> Automated regression numbers from `cognirepo benchmark` on external repos.
>
> **Last validated: 2026-06-17** — flask (83 files), fastapi (1,122 files), celery (416 files)
> using `cognirepo benchmark --json`. Numbers in the Automated Benchmark section reflect actual
> output from this run; the External Repo Validation table is updated accordingly. The Session
> Comparison (Rounds A/B) and Gemini sections remain from the original live sessions.

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

*From `cognirepo benchmark --json` on flask, fastapi, celery (2026-06-17, no human in loop):*

| Metric | Value | Notes |
|--------|-------|-------|
| Token reduction vs naive baseline | **97.7–99.1%** | flask 97.7%, fastapi 98.6%, celery 99.1% |
| Token reduction vs targeted baseline | **~40–60%** | unchanged |
| Symbol lookup latency | **0.002–0.005 ms** | well under 1 ms target |
| grep equivalent latency | 60–1,673 ms | flask 130 ms, fastapi 60 ms, celery 1,673 ms |
| Lookup speedup vs grep | **25,960×–557,500×** | scales with repo size |
| Cache speedup (warm vs cold) | **18,000–27,000×** | |
| Memory recall@1 | **67%** (2/3 repos) | fastapi: 0% — empty vector DB; under investigation |
| Memory recall@3 | **67%** (2/3 repos) | same as @1 for this run |
| Context relevance | **21.8–39.8%** | new metric; % of context_pack sections matching query keywords |
| Symbol hit rate | **0%** ⚠️ | benchmark probe used CogniRepo symbols on external repos — fixed in v1.1.3 |
| Precision@1 | **0%** ⚠️ | golden set was CogniRepo-specific — fixed in v1.1.3 |
| Precision@3 | **0%** ⚠️ | fixed in v1.1.3; re-run benchmark after upgrade |
| Knowledge graph | 2 259 nodes · 6 073 edges | from live Claude session on CogniRepo |

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

For the cross-model test (requires Claude Desktop + Gemini CLI both pointed at same project):
1. Run Claude prompt from `TEST_SUITE.md` Section 14 (or the benchmark prompt above)
2. Run Gemini prompt — it will retrieve Claude's stored findings
3. Neither tool should need to read a file

---

## External Repo Validation

Measured on real-world Python projects. CPU-only embeddings, no GPU.
Each repo indexed with `cognirepo index-repo . --no-watch` on a fresh init.
**Re-validated 2026-06-17** using `cognirepo benchmark --json`.

| Repo | Size | Lookup latency | context_relevance | Symbol hit rate | precision@3 | Notes |
|------|------|----------------|-------------------|-----------------|-------------|-------|
| **flask** | 83 .py files | 0.005 ms | 21.8% | 0% ⚠️ | 0% ⚠️ | probe/golden-set bug (fixed v1.1.3) |
| **fastapi** | 1,122 .py files | 0.002 ms | 36.0% | 0% ⚠️ | 0% ⚠️ | probe/golden-set bug (fixed v1.1.3) |
| **celery** | 416 .py files | 0.003 ms | 39.8% | 0% ⚠️ | 0% ⚠️ | probe/golden-set bug (fixed v1.1.3) |
| **ansible** | 1,813 .py files | 0.018 ms | — | — | — | not re-run in v1.1.3 |

Prior run numbers (pre-v1.1.3 benchmark bug, from live sessions):

| Repo | precision@1 | precision@3 | Symbol hit rate |
|------|-------------|-------------|-----------------|
| flask | 87.5% | 100% | 5/5 |
| fastapi | 66.7% | 88.9% | 5/5 |
| celery | 87.5% | 100% | 5/5 |
| ansible | 80.0% | 80.0% | 5/5 |

Re-run `cognirepo benchmark` after upgrading to v1.1.3 to get updated precision and hit-rate numbers with the fixed probe.

### Quality gates (v1.1.3 re-validation)

| Gate | Threshold | Result |
|------|-----------|--------|
| Symbol lookup latency | ≤ 10 ms | ✅ max 0.005 ms |
| Token reduction vs naive | ≥ 95% | ✅ min 97.7% |
| Cache speedup | ≥ 10,000× | ✅ min 18,000× |
| Symbol hit rate | ≥ 80% | ⚠️ 0% — benchmark probe bug (fixed v1.1.3) |
| precision@3 on external repos | ≥ 0.65 | ⚠️ 0% — golden set bug (fixed v1.1.3) |

### Notes

- Symbol lookup uses AST reverse index (O(1) hash) — not FAISS. Sub-millisecond even on 1,800-file repos.
- precision@k = fraction of natural-language queries where `context_pack()` returns the correct file in the top-k sections.
- **v1.1.3 fix:** benchmark now samples symbols from the target repo's own AST index (not CogniRepo's hardcoded list) and loads repo-specific golden sets (`benchmark_golden_{repo}.json`) for precision@k.
- kubernetes and moby (Go) skipped — Python-only index by default. Go needs `cognirepo[languages]`.
