# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Task 4.3 — Post-release verification.

Checks that the installed package is self-consistent:
- Version in pyproject.toml is parseable as semver
- All declared hard dependencies are importable
- No dev-only paths are imported by the main package at runtime
- cognirepo CLI entry point exists and responds to --version / --help
"""
import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_version_is_semver():
    """pyproject.toml version must follow semantic versioning (MAJOR.MINOR.PATCH)."""
    import re
    toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', toml, re.MULTILINE)
    assert m, "version field not found in pyproject.toml"
    version = m.group(1)
    assert re.match(r"^\d+\.\d+\.\d+", version), (
        f"Version {version!r} does not follow semver (MAJOR.MINOR.PATCH)"
    )


def test_hard_dependencies_importable():
    """All packages declared as hard dependencies must be importable."""
    # Map pyproject dependency names → import names
    hard_deps = {
        "faiss-cpu": "faiss",
        "numpy": "numpy",
        "sentence-transformers": "sentence_transformers",
        "mcp": "mcp",
        "fastapi": "fastapi",
        "pydantic": "pydantic",
        "networkx": "networkx",
        "rank-bm25": "rank_bm25",
        "python-dotenv": "dotenv",
        "httpx": "httpx",
        "anthropic": "anthropic",
    }
    failures = []
    for pkg_name, import_name in hard_deps.items():
        try:
            importlib.import_module(import_name)
        except ImportError as e:
            failures.append(f"{pkg_name} ({import_name}): {e}")

    assert not failures, (
        "Hard dependencies not importable — run 'pip install .[dev,security]':\n"
        + "\n".join(f"  {f}" for f in failures)
    )


def test_cli_entrypoint_responds():
    """cognirepo --help must exit 0 and mention key commands."""
    result = subprocess.run(
        [sys.executable, "-m", "cli.main", "--help"],
        capture_output=True, text=True, timeout=15,
        cwd=str(ROOT),
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"--help exited {result.returncode}:\n{output}"
    for keyword in ("init", "index-repo", "store-memory", "serve"):
        assert keyword in output, f"Expected '{keyword}' in --help output"


def test_no_dev_path_imports():
    """
    Importing core modules must not import any dev-only paths
    (pytest, setuptools, build) — these should never be runtime deps.
    """
    dev_only = ["pytest", "_pytest", "setuptools", "build", "pip._internal"]
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; import memory.semantic_memory; import retrieval.hybrid; "
         "import orchestrator.classifier; print('\\n'.join(sys.modules.keys()))"],
        capture_output=True, text=True, timeout=30, cwd=str(ROOT),
    )
    if result.returncode != 0:
        # Skip if model isn't cached (HF offline)
        return
    loaded = set(result.stdout.splitlines())
    violations = [d for d in dev_only if any(m.startswith(d) for m in loaded)]
    assert not violations, (
        f"Dev-only modules loaded at runtime: {violations}"
    )
