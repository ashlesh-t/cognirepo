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
        from fastembed import TextEmbedding  # pylint: disable=import-outside-toplevel
        MODEL = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")

    return MODEL


def encode_with_timeout(text: str, timeout: float | None = None):
    """
    Encode text using the embedding model with a timeout guard.
    Raises concurrent.futures.TimeoutError if encoding exceeds the timeout.
    Configurable via COGNIREPO_EMBED_TIMEOUT_SEC env var (default 30s).
    """
    from memory.circuit_breaker import get_breaker, CircuitOpenError  # pylint: disable=import-outside-toplevel
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
