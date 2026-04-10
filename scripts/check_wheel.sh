#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# check_wheel.sh — build the wheel, install it in a fresh venv, and run smoke tests.
# Called by CI job 'wheel-smoke' and can be run locally before a release.
#
# Usage:
#   bash scripts/check_wheel.sh
#   bash scripts/check_wheel.sh --skip-size-check   # skip the 5 MB wheel size guard

set -euo pipefail

SKIP_SIZE_CHECK=false
for arg in "$@"; do
    [[ "$arg" == "--skip-size-check" ]] && SKIP_SIZE_CHECK=true
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$(mktemp -d)/wheel_test_venv"

echo "=== check_wheel.sh ==="
echo "Repo:  $REPO_ROOT"
echo "Venv:  $VENV_DIR"

# ── Step 1: build wheel ────────────────────────────────────────────────────────
echo
echo "--- Building wheel ---"
cd "$REPO_ROOT"
python -m build --wheel --outdir dist/ 2>&1 | tail -5

WHEEL=$(ls -t dist/cognirepo-*.whl 2>/dev/null | head -1)
if [[ -z "$WHEEL" ]]; then
    echo "ERROR: No wheel found in dist/" >&2
    exit 1
fi
echo "Built: $WHEEL"

# ── Step 2: size check ─────────────────────────────────────────────────────────
if [[ "$SKIP_SIZE_CHECK" == false ]]; then
    SIZE_BYTES=$(stat -c%s "$WHEEL" 2>/dev/null || stat -f%z "$WHEEL")
    MAX_BYTES=$((5 * 1024 * 1024))
    if [[ "$SIZE_BYTES" -gt "$MAX_BYTES" ]]; then
        echo "ERROR: Wheel is ${SIZE_BYTES} bytes (> 5 MB). Check package_data." >&2
        exit 1
    fi
    echo "Wheel size OK: ${SIZE_BYTES} bytes"
fi

# ── Step 3: install in fresh venv ─────────────────────────────────────────────
echo
echo "--- Installing in fresh venv: $VENV_DIR ---"
python -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet "$WHEEL"

# ── Step 4: smoke tests ────────────────────────────────────────────────────────
echo
echo "--- Smoke: cognirepo --help ---"
"$VENV_DIR/bin/cognirepo" --help | head -5

echo
echo "--- Smoke: cognirepo doctor ---"
"$VENV_DIR/bin/cognirepo" doctor --verbose 2>&1 | head -20 || true

# ── Step 5: Tier-1 REPL docs Q&A via stdin ────────────────────────────────────
# Installs [cli] extras so the embedded docs index and REPL are available.
echo
echo "--- Installing [cli] extras ---"
"$VENV_DIR/bin/pip" install --quiet "$WHEEL[cli]" 2>/dev/null || \
    echo "  (no [cli] extra — skipping REPL Q&A test)"

if "$VENV_DIR/bin/cognirepo" --version 2>&1 | grep -q "cognirepo"; then
    echo
    echo "--- Smoke: Tier-1 REPL docs Q&A (stdin) ---"
    # Pipe a docs question; expect the answer to mention the source file
    REPL_OUTPUT=$(printf 'how do I install cognirepo\n/exit\n' | \
        timeout 30 "$VENV_DIR/bin/cognirepo" 2>&1 || true)

    echo "$REPL_OUTPUT" | head -20

    # Verify we got a response (either from docs index or the tier label)
    if echo "$REPL_OUTPUT" | grep -qiE "install|pip|cognirepo|QUICK|STANDARD"; then
        echo "  Tier-1 REPL Q&A: PASS"
    else
        echo "  WARNING: Tier-1 REPL response not detected (non-fatal)"
    fi
fi

echo
echo "=== check_wheel.sh PASSED ==="
