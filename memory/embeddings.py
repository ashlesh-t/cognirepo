# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Utility to load and retrieve the embedding model.
"""
# pylint: disable=import-error
import concurrent.futures
import logging
import os

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Shared executor for encode() calls — bounded to 2 workers to avoid thread exhaustion
_ENCODE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)
_EMBED_TIMEOUT_SEC = float(os.environ.get("COGNIREPO_EMBED_TIMEOUT_SEC", "30"))

# Silence harmless "UNEXPECTED" weight loading reports from transformers
try:
    import transformers.utils.logging as tf_logging
    tf_logging.set_verbosity_error()
except ImportError:
    pass

MODEL = None


def get_model():
    """
    Returns the SentenceTransformer model, loading it if necessary.
    """
    global MODEL  # pylint: disable=global-statement

    if MODEL is None:
        logger.debug("Loading embedding model once...")
        import os  # pylint: disable=import-outside-toplevel
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        MODEL = SentenceTransformer("all-MiniLM-L6-v2")

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
    future = _ENCODE_EXECUTOR.submit(model.encode, text)
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

    Called by IdleManager after the idle TTL expires.  The next call to
    get_model() will reload the model from disk (~2 s warm-up).
    """
    global MODEL  # pylint: disable=global-statement
    if MODEL is not None:
        MODEL = None
        logger.info("idle: embedding model evicted from memory")
