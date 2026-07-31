#!/usr/bin/env bash
# Toggle CogniRepo between the editable dev tree and the pipx release build.
#
#   cognirepo-mode.sh dev|prod [--repo PATH]   rebind that repo's MCP server
#                                              (default --repo: current directory)
#   cognirepo-mode.sh status   [--repo PATH]   show current binding
#   eval "$(cognirepo-mode.sh shellenv dev)"   put the dev binary on $PATH
#                                              for THIS shell only
#
# Two independent switches:
#   * MCP server binary  -> .mcp.json (dev|prod). Restart Claude Code to apply.
#   * shell `cognirepo`  -> $PATH     (shellenv). Affects the current shell only.
# Flipping one does NOT flip the other.
#
# .mcp.json is gitignored in the source repo, so edits stay local.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_BIN="$SRC/venv/bin/cognirepo"
SERVER_KEY="cognirepo-cognirepo"

# Resolve the release binary without the dev venv shadowing it.
PROD_BIN="$(PATH="$(printf %s "$PATH" | tr ':' '\n' | grep -vxF "$SRC/venv/bin" | paste -sd:)" \
            command -v cognirepo || true)"

cmd="${1:-status}"; shift || true
# `shellenv` takes an optional bare mode arg; consume it before option parsing.
MODE="dev"
if [ "$cmd" = "shellenv" ] && [ "${1:-}" != "" ] && [ "${1#--}" = "$1" ]; then
  MODE="$1"; shift
fi
REPO="$PWD"
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$(cd "$2" && pwd)"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
MCP="$REPO/.mcp.json"

need_dev()  { [ -x "$DEV_BIN" ]  || { echo "missing $DEV_BIN — run: python3 -m venv venv && ./venv/bin/pip install -e ." >&2; exit 1; }; }
need_prod() { [ -n "$PROD_BIN" ] || { echo "no pipx cognirepo on PATH — run: pipx install cognirepo" >&2; exit 1; }; }

# shellenv: prepend a shim dir exposing the chosen binary as plain `cognirepo`.
if [ "$cmd" = "shellenv" ]; then
  case "$MODE" in prod) need_prod; bin="$PROD_BIN" ;; *) need_dev; bin="$DEV_BIN" ;; esac
  shim="${TMPDIR:-/tmp}/cognirepo-shim-$(id -u)"
  mkdir -p "$shim"; ln -sf "$bin" "$shim/cognirepo"
  echo "export PATH=\"$shim:\$PATH\""
  exit 0
fi

set_bin() {
  MCP="$MCP" KEY="$SERVER_KEY" BIN="$1" REPO="$REPO" python3 - <<'PY'
import json, os
path, key, binary, repo = (os.environ[k] for k in ("MCP", "KEY", "BIN", "REPO"))
try:
    with open(path) as f:
        cfg = json.load(f)
except FileNotFoundError:
    cfg = {}
servers = cfg.setdefault("mcpServers", {})
entry = servers.setdefault(key, {"args": ["serve", "--project-dir", repo]})
entry["command"] = binary
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PY
}

case "$cmd" in
  dev)    need_dev;  set_bin "$DEV_BIN" ;;
  prod)   need_prod; set_bin "$PROD_BIN" ;;
  status) ;;
  *) echo "usage: $0 {dev|prod|status|shellenv} [--repo PATH]" >&2; exit 2 ;;
esac

if [ ! -f "$MCP" ]; then
  echo "repo:   $REPO"
  echo "mcp:    no .mcp.json — this repo has no CogniRepo MCP server."
  echo "        create one with: $0 dev --repo $REPO"
  exit 0
fi

bin="$(MCP="$MCP" KEY="$SERVER_KEY" python3 -c \
  'import json,os;print(json.load(open(os.environ["MCP"]))["mcpServers"][os.environ["KEY"]]["command"])')"
printf 'repo:    %s\nmode:    %s\nbinary:  %s\nversion: %s\n' \
  "$REPO" "$([ "$bin" = "$DEV_BIN" ] && echo dev || echo prod)" \
  "$bin" "$("$bin" --version 2>&1 | tail -1)"
printf 'shell:   %s (%s)\n' "$(command -v cognirepo || echo none)" \
  "$(cognirepo --version 2>&1 | tail -1)"
echo
echo "Restart Claude Code to apply the MCP change."
