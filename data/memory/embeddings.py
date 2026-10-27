# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Utility to load and retrieve the embedding model.

Uses fastembed (ONNX runtime) — no PyTorch/CUDA required.
Model: sentence-transformers/all-MiniLM-L6-v2, dim=384.
"""
# pylint: disable=import-error
import concurrent.futures
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Shared executor for encode() calls — bounded to 2 workers to avoid thread exhaustion
_ENCODE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)
_EMBED_TIMEOUT_SEC = float(os.environ.get("COGNIREPO_EMBED_TIMEOUT_SEC", "30"))

MODEL = None


def get_model():
    global MODEL  # pylint: disable=global-statement

    if MODEL is None:
        logger.info("Loading embedding model (first use — ~2-5s)...")
        # Lazy import — keeps fastembed/ONNX out of server startup path
        try:
            from fastembed import TextEmbedding  # pylint: disable=import-outside-toplevel
        except ModuleNotFoundError as exc:
            raise ImportError(
                "fastembed is required but not installed in this Python environment.\n"
                f"  Active Python: {sys.executable}\n\n"
                "  Install options:\n"
                "    pipx (recommended — global, isolated):  pipx install 'cognirepo[languages]'\n"
                "    inside a venv:                           pip install 'cognirepo[languages]'\n"
                "    if using pipx and fastembed is missing:  pipx inject cognirepo fastembed\n\n"
                "  Do NOT pip install into system Python on Arch Linux / Debian 12+ / Ubuntu 24.04+."
            ) from exc
        MODEL = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")

    return MODEL


def encode_with_timeout(text: str, timeout: float | None = None):
    """
    Encode text using the embedding model with a timeout guard.
    Raises concurrent.futures.TimeoutError if encoding exceeds the timeout.
    Configurable via COGNIREPO_EMBED_TIMEOUT_SEC env var (default 30s).
    """
    from data.memory.circuit_breaker import get_breaker, CircuitOpenError  # pylint: disable=import-outside-toplevel
    breaker = get_breaker()
    breaker.check()
    t = timeout if timeout is not None else _EMBED_TIMEOUT_SEC
    model = get_model()
    # fastembed.embed() returns a generator; consume first (and only) result
    future = _ENCODE_EXECUTOR.submit(lambda: next(iter(model.embed([text]))))
    try:
        result = future.result(timeout=t)
        breaker.record_success()
        return result
    except concurrent.futures.TimeoutError:
        logger.error(
            "Embedding encode() timed out after %.1fs for input len=%d", t, len(text)
        )
        raise
    except CircuitOpenError:
        raise


#: Texts per ONNX call for bulk embedding. fastembed's own default (256) pads every text in a batch to the longest
#: one and keeps the attention activations of the whole batch alive; measured on 3,000 real symbol texts that is
#: 4.8 GB peak and 85 s, versus 0.5 GB and 16 s at 16 (#98, #105). Overridable, see :func:`embed_batch_size`.
EMBED_DIM = 384          # all-MiniLM-L6-v2
DEFAULT_EMBED_BATCH = 16
MAX_EMBED_BATCH = 256


def embed_batch_size() -> int:
    """Texts per ONNX call for bulk embedding: ``COGNIREPO_EMBED_BATCH``, else ``embedding.batch_size`` in the repo's
    ``config.json``, else :data:`DEFAULT_EMBED_BATCH`; clamped to ``1..MAX_EMBED_BATCH``."""
    raw: object = os.environ.get("COGNIREPO_EMBED_BATCH", "").strip()
    if not raw:
        try:
            import json  # pylint: disable=import-outside-toplevel
            from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
            with open(get_path("config.json"), encoding="utf-8") as fh:
                section = json.load(fh).get("embedding")
            raw = section.get("batch_size") if isinstance(section, dict) else None
        except (OSError, ValueError, AttributeError):
            raw = None
    try:
        return max(1, min(MAX_EMBED_BATCH, int(raw)))      # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_EMBED_BATCH


def embed_many(model, texts, batch_size: int | None = None, progress=None):
    """Embed many texts with bounded memory. Returns a ``float32`` array in the order of *texts*.

    * at most ``batch_size`` (default :func:`embed_batch_size`) texts go to the model per call, so padding and
      activations stay small however many texts there are;
    * texts are processed shortest-first so a batch is padded to a similar length, then put back in input order;
    * the circuit breaker is consulted before every batch, so a runaway RSS degrades (``CircuitOpenError``, which
      callers already handle) instead of being OOM-killed by the kernel;
    * ``progress(n)`` is called after each batch with the number of texts it held (for a progress bar).
    """
    import numpy as np  # pylint: disable=import-outside-toplevel
    from data.memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
    size = batch_size if batch_size is not None else embed_batch_size()
    size = max(1, min(MAX_EMBED_BATCH, int(size)))
    texts = list(texts)
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype="float32")
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    out = None
    breaker = get_breaker()
    for start in range(0, len(order), size):
        idx = order[start:start + size]
        breaker.check()
        vecs = np.asarray(list(model.embed([texts[i] for i in idx], batch_size=size)), dtype="float32")
        if out is None:
            out = np.empty((len(texts), vecs.shape[1]), dtype="float32")
        out[idx] = vecs
        if progress is not None:
            progress(len(idx))
    return out


def evict_model() -> None:
    """
    Release the in-memory embedding model to free RAM.

    Called by IdleManager after idle TTL expires. Next call to
    get_model() reloads from disk (~2 s warm-up).
    """
    global MODEL  # pylint: disable=global-statement
    if MODEL is not None:
        MODEL = None
        logger.info("idle: embedding model evicted from memory")
