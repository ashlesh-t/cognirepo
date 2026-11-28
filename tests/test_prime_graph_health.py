# pylint: disable=unused-argument, redefined-outer-name, import-outside-toplevel
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_prime_graph_health.py — #278 (COG-15).

``cognirepo prime`` (and ``get_session_brief``) said "Knowledge graph file exists but loaded empty (likely
corrupted)" on a new, empty repo, where an empty graph file is the normal state and ``doctor`` reports it as
healthy. The graph is only a problem when symbols were indexed but the graph has no nodes.
"""
from __future__ import annotations

import os

import pytest

from interface.tools.prime_session import _detect_blind_spots

_EMPTY_REPO = {"symbols": 0, "files": 0, "last_indexed": "not indexed"}
_INDEXED = {"symbols": 12, "files": 3, "last_indexed": ""}


def _graph_lines(spots: list[str]) -> list[str]:
    return [s for s in spots if "Knowledge graph" in s]


@pytest.fixture()
def empty_graph_file(isolated_cognirepo):
    """A real, valid graph file with 0 nodes: what `index-repo` leaves behind on a repo with nothing to index."""
    from data.graph.backend import graph_store_path
    from data.graph.knowledge_graph import KnowledgeGraph

    KnowledgeGraph().save()
    assert os.path.exists(graph_store_path()), "the premise: an empty graph file exists"
    return graph_store_path()


def test_a_new_empty_repo_is_not_reported_as_corrupted(empty_graph_file):
    spots = _detect_blind_spots(_EMPTY_REPO)

    assert _graph_lines(spots) == [], "an empty graph on an empty repo is normal, not corruption"
    assert not any("corrupt" in s.lower() for s in spots)
    assert any("No symbols indexed" in s for s in spots), "the user is still told that nothing is indexed"


def test_a_graph_that_loads_empty_while_symbols_are_indexed_still_warns(empty_graph_file):
    spots = _detect_blind_spots(_INDEXED)

    lines = _graph_lines(spots)
    assert len(lines) == 1 and "loaded empty" in lines[0] and "index-repo" in lines[0]


def test_no_graph_file_and_symbols_indexed_says_not_built(isolated_cognirepo):
    from data.graph.backend import graph_store_path

    assert not os.path.exists(graph_store_path())

    lines = _graph_lines(_detect_blind_spots(_INDEXED))

    assert len(lines) == 1 and "not built" in lines[0]


def test_no_graph_file_and_nothing_indexed_says_nothing_about_the_graph(isolated_cognirepo):
    assert _graph_lines(_detect_blind_spots(_EMPTY_REPO)) == []


def test_a_healthy_graph_is_not_reported(isolated_cognirepo):
    from data.graph.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph()
    kg.add_node("f.py", "FILE", path="f.py")
    kg.save()

    assert _graph_lines(_detect_blind_spots(_INDEXED)) == []
