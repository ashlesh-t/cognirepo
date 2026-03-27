# SPDX-FileCopyrightText: 2026 Ashlesh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/your-username/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
orchestrator/model_adapters/retry.py — exponential backoff retry wrapper.

Policy
------
Max retries  : 3  (4 total attempts including the initial call)
Backoff      : 1s → 2s → 4s between consecutive attempts
Retryable    : HTTP 429, 500, 503, and connection/timeout errors (status_code=None)
Non-retryable: HTTP 400, 401, 404 — raised immediately without retry
"""
from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

from orchestrator.model_adapters.errors import ModelCallError

logger = logging.getLogger(__name__)

T = TypeVar("T")

_BACKOFF_DELAYS: list[int] = [1, 2, 4]  # seconds before each retry


def with_retry(fn: Callable[[], T], provider: str, verbose: bool = False) -> T:
    """
    Call *fn* with exponential backoff on retryable :class:`ModelCallError`.

    Parameters
    ----------
    fn       : zero-argument callable that may raise :class:`ModelCallError`
    provider : provider name used in log messages
    verbose  : if True, print retry messages to stdout (for CLI ``--verbose``)

    Returns
    -------
    Whatever *fn* returns on success.

    Raises
    ------
    :class:`ModelCallError`
        After all retries are exhausted or if the error is non-retryable.
    """
    last_exc: ModelCallError | None = None

    for attempt in range(len(_BACKOFF_DELAYS) + 1):  # 0, 1, 2, 3 → 4 total attempts
        try:
            return fn()
        except ModelCallError as exc:
            last_exc = exc
            if exc.status_code in ModelCallError.NON_RETRYABLE_CODES:
                raise
            if attempt == len(_BACKOFF_DELAYS):
                raise  # last attempt exhausted
            delay = _BACKOFF_DELAYS[attempt]
            logger.debug(
                "[%s] attempt %d failed (HTTP %s), retrying in %ds",
                provider, attempt + 1, exc.status_code, delay,
            )
            if verbose:
                print(f"  [retry] {provider} attempt {attempt + 1} failed "
                      f"(HTTP {exc.status_code}), waiting {delay}s…")
            time.sleep(delay)

    raise last_exc  # type: ignore[misc]  # unreachable but satisfies type checker
