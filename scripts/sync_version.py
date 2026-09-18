#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Propagate version.yml → pyproject.toml, server/manifest.json, server.json.

Usage:
    python scripts/sync_version.py [--check]

    --check   Verify all targets match version.yml without writing; exit 1 if drift.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def load_version_yml() -> dict:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        print("PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)
    with (REPO_ROOT / "version.yml").open() as f:
        return yaml.safe_load(f)


def sync_pyproject(version: str, *, check: bool) -> bool:
    path = REPO_ROOT / "pyproject.toml"
    text = path.read_text()
    new_text = re.sub(r'^(version\s*=\s*")[^"]+(")', rf'\g<1>{version}\2', text, count=1, flags=re.MULTILINE)
    if text == new_text:
        print(f"  pyproject.toml — already {version}")
        return True
    if check:
        print(f"  DRIFT  pyproject.toml — expected {version}")
        return False
    path.write_text(new_text)
    print(f"  UPDATED  pyproject.toml → {version}")
    return True


def sync_manifest_json(version: str, *, check: bool) -> bool:
    path = REPO_ROOT / "interface" / "server" / "manifest.json"
    data = json.loads(path.read_text())
    if data.get("version") == version:
        print(f"  server/manifest.json — already {version}")
        return True
    if check:
        print(f"  DRIFT  server/manifest.json — expected {version}, got {data.get('version')}")
        return False
    data["version"] = version
    # ensure_ascii=True (json.dump's default) and no trailing newline, matching
    # _write_manifest() — sync_version.py previously used ensure_ascii=False + a
    # trailing newline here, so running it re-escaped every non-ASCII character
    # in every tool description into literal unicode and churned the whole file
    # on every version bump, even though nothing but the version had changed.
    path.write_text(json.dumps(data, indent=2))
    print(f"  UPDATED  server/manifest.json → {version}")
    return True


def sync_server_json(version: str, meta: dict, *, check: bool) -> bool:
    path = REPO_ROOT / "server.json"
    data = json.loads(path.read_text())
    mcp_meta = meta.get("mcp", {})
    expected_title = mcp_meta.get("title")
    expected_description = mcp_meta.get("description")

    top_ok = data.get("version") == version
    pkg_version = (data.get("packages") or [{}])[0].get("version")
    pkg_ok = pkg_version == version
    # title/description are optional in version.yml's mcp section — only enforced when present,
    # so this script doesn't require every version.yml to carry them.
    title_ok = expected_title is None or data.get("title") == expected_title
    description_ok = expected_description is None or data.get("description") == expected_description

    if top_ok and pkg_ok and title_ok and description_ok:
        print(f"  server.json — already {version}")
        return True
    if check:
        if not top_ok:
            print(f"  DRIFT  server.json version — expected {version}, got {data.get('version')}")
        if not pkg_ok:
            print(f"  DRIFT  server.json packages[0].version — expected {version}, got {pkg_version}")
        if not title_ok:
            print(f"  DRIFT  server.json title — expected {expected_title!r}, got {data.get('title')!r}")
        if not description_ok:
            print(f"  DRIFT  server.json description — expected {expected_description!r}, got {data.get('description')!r}")
        return False
    data["version"] = version
    if data.get("packages"):
        data["packages"][0]["version"] = version
    if expected_title is not None:
        data["title"] = expected_title
    if expected_description is not None:
        data["description"] = expected_description
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"  UPDATED  server.json → {version} (top-level + packages[0]"
          f"{' + title/description' if (expected_title or expected_description) else ''})")
    return True


def main() -> None:
    check = "--check" in sys.argv
    meta = load_version_yml()
    version = meta["project"]["version"]
    print(f"version.yml → {version}  ({'check' if check else 'sync'})")

    results = [
        sync_pyproject(version, check=check),
        sync_manifest_json(version, check=check),
        sync_server_json(version, meta, check=check),
    ]

    if check and not all(results):
        print("\nDrift detected — run `python scripts/sync_version.py` to fix.")
        sys.exit(1)
    elif not check:
        print("\nAll targets synced.")


if __name__ == "__main__":
    main()
