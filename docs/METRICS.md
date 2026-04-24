# CogniRepo — Quantitative Impact Metrics

> Real measurements from live Claude + Gemini sessions on the CogniRepo codebase itself.
> Automated regression numbers from `cognirepo benchmark` on the same repo (~120 files, ~1 400 symbols).

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

*From `cognirepo benchmark` on the same repo (no human in loop):*

| Metric | Value |
|--------|-------|
| Token reduction vs raw reads | **98%** |
| Symbol lookup latency | **< 1 ms** |
| grep equivalent latency | 2 000–8 000 ms |
| Lookup speedup vs grep | **100 000–4 000 000×** |
| Cache speedup (warm vs cold) | **20 000–40 000×** |
| Memory recall@1 | **100%** |
| Memory recall@3 | **100%** |
| Symbol hit rate | **100%** |
| Knowledge graph | 2 259 nodes · 6 073 edges |

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
