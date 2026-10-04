# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Generate the committed OpenAPI contract: ``python -m interface.ui.openapi --write``."""
from __future__ import annotations

import json
import os
import sys

SPEC_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "openapi", "ui-v1.json")


def build_openapi() -> dict:
    from interface.ui import security as sec  # pylint: disable=import-outside-toplevel
    from interface.ui.app import create_app  # pylint: disable=import-outside-toplevel
    app = create_app(sec.SecurityConfig(token="spec-only", port=8731), ".", console_dir="")
    return app.openapi()


def render() -> str:
    return json.dumps(build_openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--write" in argv:
        os.makedirs(os.path.dirname(SPEC_PATH), exist_ok=True)
        with open(SPEC_PATH, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {os.path.normpath(SPEC_PATH)}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
