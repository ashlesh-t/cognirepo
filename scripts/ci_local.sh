#!/usr/bin/env bash
# ci_local.sh — simulate the GitHub Actions CI pipeline locally.
#
# Runs the same steps as .github/workflows/ci.yml so you can catch
# failures before pushing. Uses a throw-away venv in /tmp so it never
# touches your dev checkout's venv or .cognirepo/.
#
# Usage:
#   bash scripts/ci_local.sh            # full run
#   bash scripts/ci_local.sh --no-index # skip index-repo (faster)
#   bash scripts/ci_local.sh --tests-only
#
# Requirements: python3.11 or python3.12 on PATH, libgomp1 installed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="/tmp/cognirepo_ci_venv"
COGNIREPO_CI_DIR="/tmp/cognirepo_ci_dir"
FASTEMBED_CACHE="$HOME/.cache/fastembed"

NO_INDEX=0
TESTS_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --no-index)   NO_INDEX=1 ;;
    --tests-only) NO_INDEX=1; TESTS_ONLY=1 ;;
  esac
done

cd "$REPO_ROOT"

step() { echo; echo "▶ $*"; }

# ── venv ──────────────────────────────────────────────────────────────────────
if [[ "$TESTS_ONLY" -eq 0 ]]; then
  step "Creating fresh venv at $VENV_DIR"
  rm -rf "$VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
export FASTEMBED_CACHE_PATH="$FASTEMBED_CACHE"

# ── install ───────────────────────────────────────────────────────────────────
if [[ "$TESTS_ONLY" -eq 0 ]]; then
  step "Installing package + dev extras"
  pip install -q -e ".[dev,languages,security]"

  step "Pre-warming embedding model (downloads to $FASTEMBED_CACHE)"
  python - <<'PYEOF'
from fastembed import TextEmbedding
m = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")
_ = list(m.embed(["warmup"]))
print("  Embedding model ready.")
PYEOF
fi

# ── bootstrap .cognirepo ──────────────────────────────────────────────────────
if [[ "$NO_INDEX" -eq 0 ]]; then
  step "Bootstrapping .cognirepo index (--no-embed, mirrors CI)"
  rm -rf "$COGNIREPO_CI_DIR"
  mkdir -p "$COGNIREPO_CI_DIR"
  python - <<PYEOF
import json, os
cfg = {
    "project_name": "cognirepo",
    "version": "0.2.1",
    "retrieval_weights": {"vector": 0.5, "graph": 0.3, "behaviour": 0.2},
    "storage": {"encrypt": False},
    "watch": {"auto_enabled": False},
    "autosave_context": True,
}
with open(os.path.join("$COGNIREPO_CI_DIR", "config.json"), "w") as f:
    json.dump(cfg, f)
PYEOF
  COGNIREPO_DIR="$COGNIREPO_CI_DIR" cognirepo index-repo . --no-watch --no-embed
fi

# ── stdout pollution guard ────────────────────────────────────────────────────
step "Checking stdout pollution (MCP framing safety)"
python scripts/check_no_stdout_pollution.py

# ── tests ─────────────────────────────────────────────────────────────────────
step "Running test suite"
COGNIREPO_DIR="$COGNIREPO_CI_DIR" \
  python -m pytest tests/ \
    -q \
    --tb=short \
    --timeout=30 \
    --cov=. \
    --cov-report=term-missing \
    --cov-fail-under=50 \
    -x

echo
echo "✓ ci_local.sh complete — all steps passed"
