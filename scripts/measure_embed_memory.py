#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Peak RSS and time of bulk embedding at different batch sizes, on real symbol-sized texts (#98, #105).

    python scripts/measure_embed_memory.py /path/to/repo [--texts 3000] [--batches 256,64,32,16]

Each configuration runs in its OWN process (a shared interpreter would carry the previous run's ONNX arena), so the
peak is honest. Texts are built from the repo's Python functions/classes (name + docstring), like the indexer's
own embed text. Run it under a memory cap if you are unsure what your batch size will do::

    systemd-run --user --scope -p MemoryMax=6G -p MemorySwapMax=0 python scripts/measure_embed_memory.py .

This is how the OOM in #98 was root-caused: fastembed's default batch of 256 padded every text to the longest in the
batch and peaked at ~4.8 GB for 3,000 texts (and took 85 s), versus ~0.5 GB and 16 s at a batch of 16.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHILD = r"""
import ast, glob, json, os, resource, sys, time
repo, batch, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
texts = []
for f in sorted(glob.glob(os.path.join(repo, "**", "*.py"), recursive=True)):
    try:
        tree = ast.parse(open(f, encoding="utf-8", errors="replace").read())
    except Exception:
        continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            texts.append(" ".join(["function", node.name, ast.get_docstring(node) or "", "calls: a, b, c"])[:1500])
if not texts:
    print(json.dumps({"error": "no Python symbols found"})); sys.exit(0)
texts = (texts * (n // len(texts) + 1))[:n]
from fastembed import TextEmbedding
model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")
base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
start = time.time()
count = sum(1 for _ in model.embed(texts, batch_size=batch))
print(json.dumps({"batch": batch, "texts": count, "avg_chars": sum(map(len, texts)) // len(texts), "base_mb": base,
                  "peak_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024, "secs": round(time.time() - start, 1)}))
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("repo", help="a repository with Python sources")
    ap.add_argument("--texts", type=int, default=3000)
    ap.add_argument("--batches", default="256,64,32,16")
    args = ap.parse_args()
    print(f"{'batch':>6} {'texts':>6} {'avg chars':>10} {'peak MB':>8} {'secs':>6}")
    for batch in (int(b) for b in args.batches.split(",")):
        proc = subprocess.run([sys.executable, "-c", CHILD, args.repo, str(batch), str(args.texts)],
                              capture_output=True, text=True, check=False, env={**os.environ, "PYTHONPATH": ROOT})
        try:
            row = json.loads(proc.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            print(f"{batch:>6}  failed (exit {proc.returncode}): {proc.stderr.strip()[-200:]}")
            continue
        if "error" in row:
            sys.exit(row["error"])
        print(f"{row['batch']:>6} {row['texts']:>6} {row['avg_chars']:>10} {row['peak_mb']:>8} {row['secs']:>6}")


if __name__ == "__main__":
    main()
