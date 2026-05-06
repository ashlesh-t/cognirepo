#!/usr/bin/env bash
# Run the same checks as GitHub Actions workflows locally.
# Usage: ./scripts/check-workflows-local.sh [bandit|pip-audit|lint|ci|all]
# Default: all

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; FAILED+=("$1"); }
header() { echo -e "\n${BOLD}${YELLOW}=== $1 ===${NC}"; }

FAILED=()
TARGET="${1:-all}"

# ── Bandit (mirrors security.yml job: bandit) ──────────────────────────────
run_bandit() {
    header "Bandit — Python SAST (HIGH + MEDIUM, -ll flag)"
    if ! command -v bandit &>/dev/null; then
        echo "Installing bandit..."
        pip install "bandit[toml]>=1.8" -q
    fi
    if bandit -r adapters/ cli/ cron/ graph/ indexer/ \
                 memory/ orchestrator/ retrieval/ security/ server/ \
                 tools/ vector_db/ \
              -x tests/ \
              -ll; then
        pass "bandit"
    else
        fail "bandit"
    fi
}

# ── pip-audit (mirrors security.yml job: pip-audit) ────────────────────────
run_pip_audit() {
    header "pip-audit — dependency vulnerabilities"
    if ! command -v pip-audit &>/dev/null; then
        echo "Installing pip-audit..."
        pip install pip-audit -q
    fi

    # Point pip-audit at the active venv (or repo-local venv) so it audits
    # project deps, not the system Python environment.
    if [ -n "${VIRTUAL_ENV:-}" ]; then
        export PIPAPI_PYTHON_LOCATION="$VIRTUAL_ENV/bin/python"
        echo "Auditing venv: $VIRTUAL_ENV"
    elif [ -f "$REPO_ROOT/venv/bin/python" ]; then
        export PIPAPI_PYTHON_LOCATION="$REPO_ROOT/venv/bin/python"
        echo "Auditing venv: $REPO_ROOT/venv"
    else
        echo "Warning: no venv detected — auditing system Python (may include unrelated packages)"
    fi

    pip install --upgrade pip -q
    pip install . -q
    if pip-audit --ignore-vuln CVE-2026-4539 --ignore-vuln CVE-2026-3219; then
        pass "pip-audit"
    else
        fail "pip-audit"
    fi
}

# ── Pylint (mirrors lint.yml) ──────────────────────────────────────────────
run_lint() {
    header "Pylint — static lint (fail-under 8.0)"
    if ! command -v pylint &>/dev/null; then
        echo "Installing pylint..."
        pip install pylint -q
    fi
    PY_FILES=$(git ls-files '*.py' | grep -v 'venv/' | grep -v '_pb2' || true)
    if [ -z "$PY_FILES" ]; then
        echo "No Python files tracked by git."
    elif pylint $PY_FILES --disable=C,R,import-error --fail-under=8.0; then
        pass "pylint"
    else
        fail "pylint"
    fi
}

# ── CI tests (mirrors ci.yml: run tests step) ─────────────────────────────
run_ci() {
    header "CI — pytest (mirrors ci.yml)"
    if ! command -v pytest &>/dev/null; then
        echo "Installing dev deps..."
        pip install -e ".[dev,security]" -q
    fi
    if python -m pytest tests/ -q --tb=short --timeout=30 -x; then
        pass "pytest"
    else
        fail "pytest"
    fi
}

# ── Docker build check (mirrors docker.yml — build only, no push) ─────────
run_docker() {
    header "Docker — build check (no push)"
    if ! command -v docker &>/dev/null; then
        echo "Docker not installed — skipping."
        return
    fi
    if docker build --network=host -t cognirepo:local-check . ; then
        pass "docker build"
    else
        fail "docker build"
    fi
}

case "$TARGET" in
    bandit)    run_bandit ;;
    pip-audit) run_pip_audit ;;
    lint)      run_lint ;;
    ci)        run_ci ;;
    docker)    run_docker ;;
    all)
        run_bandit
        run_pip_audit
        run_lint
        run_ci
        run_docker
        ;;
    *)
        echo "Usage: $0 [bandit|pip-audit|lint|ci|docker|all]"
        exit 1
        ;;
esac

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
if [ ${#FAILED[@]} -eq 0 ]; then
    echo -e "${GREEN}${BOLD}All checks passed.${NC}"
    exit 0
else
    echo -e "${RED}${BOLD}Failed:${NC} ${FAILED[*]}"
    exit 1
fi
