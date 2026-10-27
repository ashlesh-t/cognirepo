# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""The regression test the OOM in #98/#105 never had: bulk-embedding real text must stay within a memory budget.

fastembed's default batch of 256 padded every text to the longest in the batch and peaked at ~4.8 GB for 3,000
symbol-sized texts (a kernel OOM-kill on a 10k-symbol repo). With the bounded batches `embed_many` uses it stays
well under 1 GB. Runs the real ONNX model in a subprocess so the peak is that of the embedding alone.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("fastembed")

BUDGET_MB = 1200

SCRIPT = textwrap.dedent("""
    import json, resource, sys
    sys.path.insert(0, sys.argv[1])
    from data.memory.embeddings import embed_many, get_model
    texts = []
    for i in range(1200):
        body = "def handler(request, *args, **kwargs):  " + ("process the incoming message and retry on failure " * (1 + (i % 40) * 4 if i % 37 == 0 else 1))
        texts.append(f"function handler_{i} {body}")
    out = embed_many(get_model(), texts)
    print(json.dumps({"n": int(out.shape[0]), "peak_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024}))
""")


def _run(env_extra: dict[str, str]) -> dict:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        proc = subprocess.run([sys.executable, "-c", SCRIPT, root], capture_output=True, text=True, timeout=420,
                              env={**os.environ, **env_extra}, check=False)
    except subprocess.TimeoutExpired:
        pytest.skip("the embedding model could not be loaded in time (first use downloads it)")
    if proc.returncode != 0 and ("fastembed is required" in proc.stderr or "No such file" in proc.stderr
                                 or "Connection" in proc.stderr or "huggingface" in proc.stderr.lower()):
        pytest.skip("embedding model is not available in this environment")
    assert proc.returncode == 0, proc.stderr[-1500:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_bulk_embedding_stays_within_the_memory_budget():
    result = _run({"COGNIREPO_EMBED_BATCH": ""})
    assert result["n"] == 1200
    assert result["peak_mb"] < BUDGET_MB, f"bulk embedding peaked at {result['peak_mb']} MB (budget {BUDGET_MB} MB)"
