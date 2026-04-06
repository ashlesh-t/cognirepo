# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

from utils import compute_hash, verify_hash

class AuthManager:
    def login(self, username: str, password: str) -> bool:
        stored_hash = self._get_hash(username)
        return verify_hash(password, stored_hash)

    def _get_hash(self, username: str) -> str:
        return ""
