#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Generate architecture diagrams from Mermaid source files.
# Requires: mmdc (Mermaid CLI) — install with: npm install -g @mermaid-js/mermaid-cli
#
# Usage:
#   bash scripts/build_diagrams.sh
#
# Output: docs/architecture/diagrams/*.png (overwritten)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DIAGRAM_DIR="$REPO_ROOT/docs/architecture/diagrams"

cd "$REPO_ROOT"

if ! command -v mmdc &>/dev/null; then
    echo "ERROR: mmdc not found. Install with: npm install -g @mermaid-js/mermaid-cli" >&2
    exit 1
fi

for mmd in "$DIAGRAM_DIR"/*.mmd; do
    base="$(basename "$mmd" .mmd)"
    out="$DIAGRAM_DIR/$base.png"
    echo "  Generating $base.png from $base.mmd ..."
    mmdc -i "$mmd" -o "$out" -t neutral -b white --width 1200
done

echo "Done. Diagrams written to $DIAGRAM_DIR/"
