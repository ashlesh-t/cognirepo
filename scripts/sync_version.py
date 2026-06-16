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
    path = REPO_ROOT / "server" / "manifest.json"
    data = json.loads(path.read_text())
    if data.get("version") == version:
        print(f"  server/manifest.json — already {version}")
        return True
    if check:
        print(f"  DRIFT  server/manifest.json — expected {version}, got {data.get('version')}")
        return False
    data["version"] = version
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"  UPDATED  server/manifest.json → {version}")
    return True


def sync_server_json(version: str, *, check: bool) -> bool:
    path = REPO_ROOT / "server.json"
    data = json.loads(path.read_text())
    top_ok = data.get("version") == version
    pkg_version = (data.get("packages") or [{}])[0].get("version")
    pkg_ok = pkg_version == version
    if top_ok and pkg_ok:
        print(f"  server.json — already {version}")
        return True
    if check:
        if not top_ok:
            print(f"  DRIFT  server.json version — expected {version}, got {data.get('version')}")
        if not pkg_ok:
            print(f"  DRIFT  server.json packages[0].version — expected {version}, got {pkg_version}")
        return False
    data["version"] = version
    if data.get("packages"):
        data["packages"][0]["version"] = version
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"  UPDATED  server.json → {version} (top-level + packages[0])")
    return True


def main() -> None:
    check = "--check" in sys.argv
    meta = load_version_yml()
    version = meta["project"]["version"]
    print(f"version.yml → {version}  ({'check' if check else 'sync'})")

    results = [
        sync_pyproject(version, check=check),
        sync_manifest_json(version, check=check),
        sync_server_json(version, check=check),
    ]

    if check and not all(results):
        print("\nDrift detected — run `python scripts/sync_version.py` to fix.")
        sys.exit(1)
    elif not check:
        print("\nAll targets synced.")


if __name__ == "__main__":
    main()
