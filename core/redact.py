# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Secret scrubbing shared by the UI audit log and the live event stream."""
from __future__ import annotations

from typing import Any

#: field names whose values are never recorded (compared lower-cased, exact match)
SECRET_KEYS = frozenset({
    "token", "authorization", "cookie", "set-cookie", "password", "passwd", "secret",
    "api_key", "apikey", "access_token", "refresh_token", "private_key",
})


def drop_secrets(fields: dict[str, Any]) -> dict[str, Any]:
    """``fields`` without any secret-named key."""
    return {k: v for k, v in fields.items() if str(k).lower() not in SECRET_KEYS}
