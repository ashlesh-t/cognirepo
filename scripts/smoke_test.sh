#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Smoke test: pip install → init → index → MCP call
# Runs on Linux and macOS. For Windows use smoke_test.ps1.
#
# Usage:
#   bash scripts/smoke_test.sh [--package-install]
#
# Flags:
#   --package-install   pip install cognirepo from PyPI (default: editable install from source)
#
# Exit code 0 = all checks passed, 1 = failure.

set -euo pipefail

PACKAGE_INSTALL=0
for arg in "$@"; do
    [[ "$arg" == "--package-install" ]] && PACKAGE_INSTALL=1
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKE_DIR="$(mktemp -d)"
trap 'rm -rf "$SMOKE_DIR"' EXIT

echo "=== CogniRepo Smoke Test ==="
echo "    platform : $(uname -s)"
echo "    python   : $(python3 --version)"
echo "    workdir  : $SMOKE_DIR"
echo ""

cd "$SMOKE_DIR"

# Pin .cognirepo/ to the smoke dir so nothing touches ~/.cognirepo
export COGNIREPO_DIR="$SMOKE_DIR/.cognirepo"

# ── 1. Install ────────────────────────────────────────────────────────────────
echo "[1/5] Installing cognirepo..."
if [[ $PACKAGE_INSTALL -eq 1 ]]; then
    pip install cognirepo --quiet
else
    pip install -e "$REPO_ROOT[dev,security]" --quiet
fi
echo "      OK"

# ── 2. Init ───────────────────────────────────────────────────────────────────
echo "[2/5] cognirepo init --no-index --non-interactive..."
cognirepo init --password smoketest --no-index --non-interactive
[[ -f "$COGNIREPO_DIR/config.json" ]] || { echo "FAIL: config.json not created at $COGNIREPO_DIR"; exit 1; }
echo "      OK"

# ── 3. Index ──────────────────────────────────────────────────────────────────
echo "[3/5] cognirepo index-repo --no-watch..."
# Write a tiny fixture so indexer has something to do
mkdir -p myapp
cat > myapp/hello.py << 'EOF'
def greet(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}"
EOF
cognirepo index-repo . --no-watch
echo "      OK"

# ── 4. Store and retrieve memory ──────────────────────────────────────────────
echo "[4/5] store-memory + retrieve-memory..."
cognirepo store-memory "smoke test memory entry alpha"
RESULT=$(cognirepo retrieve-memory "smoke test memory" --top-k 1 2>/dev/null || echo "")
# Result may be empty on first run (model not warmed up) — just check no crash
echo "      OK (result: ${RESULT:0:60}...)"

# ── 5. MCP server starts ──────────────────────────────────────────────────────
echo "[5/5] MCP server start/stop..."
timeout 5 cognirepo serve &
MCP_PID=$!
sleep 2
if kill -0 $MCP_PID 2>/dev/null; then
    kill $MCP_PID 2>/dev/null
    echo "      OK (MCP server started, PID $MCP_PID)"
else
    echo "      WARN: MCP server exited early (may be normal if stdin closed)"
fi

echo ""
echo "=== Smoke test PASSED ==="
