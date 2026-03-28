# pylint: disable=duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
orchestrator/model_adapters/errors.py — shared error types for all model adapters.
"""
from __future__ import annotations


class ModelCallError(Exception):
    """Raised by any adapter when a model API call fails.

    Parameters
    ----------
    provider    : "anthropic" | "gemini" | "openai" | "grok"
    status_code : HTTP status code, or None for connection/timeout errors
    message     : human-readable error description
    """

    #: HTTP codes that are safe to retry
    RETRYABLE_CODES: frozenset[int] = frozenset({429, 500, 503})
    #: HTTP codes that should never be retried
    NON_RETRYABLE_CODES: frozenset[int] = frozenset({400, 401, 404})

    def __init__(self, provider: str, status_code: int | None, message: str) -> None:
        self.provider = provider
        self.status_code = status_code
        self.message = message
        code_str = str(status_code) if status_code is not None else "connection error"
        super().__init__(f"[{provider}] HTTP {code_str}: {message}")

    @property
    def is_retryable(self) -> bool:
        """True if this error warrants a retry."""
        if self.status_code is None:
            return True  # connection/timeout errors are retryable
        return self.status_code in self.RETRYABLE_CODES
