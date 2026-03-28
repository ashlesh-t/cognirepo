# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Per-file symbol tables for line-range and containment queries.

Data structure choice: bisect + sorted list (stdlib only).

Why not Fenwick / segment tree:
  - Fenwick (BIT) handles prefix-sum counts but cannot enumerate records —
    you still need the sorted list alongside it. Wins only for incremental
    single-point updates, which don't occur here (full file re-index on change).
  - Segment tree: same enumeration problem; overkill at < 1000 symbols per file.
  - bisect: O(log N) boundary search + O(k) slice for range; O(log N + depth)
    for containment where depth ≤ ~5 (Python nesting bound). Zero extra deps.
"""
import bisect
from dataclasses import dataclass, field


@dataclass
class SymbolRecord:
    """A single symbol's metadata extracted from AST parsing."""
    name: str
    symbol_type: str        # "FUNCTION" | "CLASS"
    start_line: int
    end_line: int
    docstring: str = ""
    calls: list[str] = field(default_factory=list)
    faiss_id: int = -1      # row in ast.index; -1 = not yet embedded


class SymbolTable:
    """
    Sorted-by-start_line symbol list for one file.

    symbols_in_range(l, r)  — O(log N + k) — all symbols whose start is in [l, r]
    containing_symbol(line) — O(log N + depth) — innermost symbol containing line
    """

    def __init__(self, symbols: list[SymbolRecord]) -> None:
        self._symbols = sorted(symbols, key=lambda s: s.start_line)
        self._starts = [s.start_line for s in self._symbols]

    def symbols_in_range(self, l: int, r: int) -> list[SymbolRecord]:
        """Return all symbols whose start_line falls in [l, r]."""
        lo = bisect.bisect_left(self._starts, l)
        hi = bisect.bisect_right(self._starts, r)
        return self._symbols[lo:hi]

    def containing_symbol(self, line: int) -> SymbolRecord | None:
        """
        Return the innermost symbol (function/class) that contains `line`.

        Strategy: find the rightmost symbol with start_line <= line, then
        walk backwards until we find one whose end_line >= line.
        Walking back costs at most O(nesting_depth) ≤ ~5 in real Python.
        """
        idx = bisect.bisect_right(self._starts, line) - 1
        while idx >= 0:
            sym = self._symbols[idx]
            if sym.end_line >= line:
                return sym
            idx -= 1
        return None

    def all_symbols(self) -> list[SymbolRecord]:
        """Return all symbol records in this table."""
        return list(self._symbols)

    def __len__(self) -> int:
        return len(self._symbols)


def build_symbol_table_from_index(file_path: str, index_data: dict) -> SymbolTable:
    """
    Construct a SymbolTable from the in-memory ast_index structure for one file.
    index_data is the top-level dict loaded from ast_index.json.
    """
    raw_symbols = index_data.get("files", {}).get(file_path, {}).get("symbols", [])
    records = [
        SymbolRecord(
            name=s["name"],
            symbol_type=s["type"],
            start_line=s["start_line"],
            end_line=s["end_line"],
            docstring=s.get("docstring", ""),
            calls=s.get("calls", []),
            faiss_id=s.get("faiss_id", -1),
        )
        for s in raw_symbols
    ]
    return SymbolTable(records)
