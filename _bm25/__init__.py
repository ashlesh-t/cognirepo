# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
CogniRepo BM25 package — transparent C++/Python backend selection.

Import this package instead of importing either backend directly::

    from _bm25 import BM25, Document, BACKEND

At import time the package tries to load the compiled C++ extension
(_bm25_ext).  If it is absent (no cmake build performed), it silently
falls back to the pure-Python implementation — same interface, slightly
slower on very large corpora (10k+ documents).

Build the C++ extension::

    pip install 'cognirepo[cpp]'
    # or manually:
    cmake -S cognirepo/_bm25 -B build/bm25 -DBUILD_EXT=ON
    cmake --build build/bm25 --target _bm25_ext
    cp build/bm25/_bm25_ext*.so .   # place .so on Python path
"""

try:
    from _bm25_ext import BM25, Document  # type: ignore[import]  # nosec
    BACKEND: str = "cpp"
except ImportError:
    from _bm25._fallback import BM25, Document  # noqa: F401
    BACKEND = "python"

__all__ = ["BM25", "Document", "BACKEND"]
