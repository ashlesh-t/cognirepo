# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_coverage_extended.py — Additional 10 test cases to reach coverage goals.
"""
from __future__ import annotations

import os
import json
from unittest.mock import patch, MagicMock
import pytest
import numpy as np


# ── 1. retrieval/docs_search.py (Fast Path) ──────────────────────────────────

def test_docs_search_fast_path(tmp_path, monkeypatch):
    """Test that docs_search uses the ast_index.json fast path if available."""
    from retrieval.docs_search import search_docs
    monkeypatch.chdir(tmp_path)
    
    # Create fake index with a .md entry
    os.makedirs(".cognirepo/index", exist_ok=True)
    index_path = tmp_path / ".cognirepo/index/ast_index.json"
    index_path.write_text(json.dumps({
        "reverse_index": {
            "secret": [["doc_fast.md", 1]]
        }
    }))
    
    # Create the file mentioned in index
    (tmp_path / "doc_fast.md").write_text("This is a secret file.", encoding="utf-8")
    
    results = search_docs("secret")
    assert len(results) >= 1
    assert any(r["path"] == "doc_fast.md" for r in results)


# ── 2. retrieval/cross_repo.py (All Org Repos) ───────────────────────────────

def test_cross_repo_all_org_repos(tmp_path):
    """Test get_all_org_repos correctly merges top-level and project-level repos."""
    from retrieval.cross_repo import CrossRepoRouter
    
    with patch("retrieval.cross_repo.get_repo_org", return_value="my-org"), \
         patch("retrieval.cross_repo.purge_stale_repos"), \
         patch("retrieval.cross_repo.list_orgs") as mock_orgs:
        
        mock_orgs.return_value = {
            "my-org": {
                "repos": ["/repo/1"],
                "projects": {
                    "proj-a": {"repos": ["/repo/2"]}
                }
            }
        }
        router = CrossRepoRouter(current_repo_path="/repo/me")
        all_repos = router.get_all_org_repos()
        assert "/repo/1" in all_repos
        assert "/repo/2" in all_repos


# ── 3. memory/auto_store.py (0% coverage boost) ─────────────────────────────

def test_auto_store_basic():
    """Exercise AutoStore logic to remove 0% coverage."""
    from memory.auto_store import AutoStore
    
    # Patch dependencies globally
    with patch("vector_db.local_vector_db.LocalVectorDB"), \
         patch("memory.embeddings.encode_with_timeout") as mock_encode:
        
        mock_encode.return_value = np.zeros(384, dtype="float32")
        
        store = AutoStore()
        # Test short text ignore
        assert store.store_if_novel("too short", "context_pack") is False
        
        # Test valuable text (longer)
        # Mock _is_novel to return True
        with patch.object(store, "_is_novel", return_value=True), \
             patch.object(store, "_suppress_similar"):
            res = store.store_if_novel("This is a long and very valuable piece of information for the agent.", "context_pack")
            assert res is True


# ── 4. orchestrator/router.py (Provider Availability) ───────────────────────

def test_router_available_providers():
    """Test _available_providers logic based on env vars."""
    from orchestrator.router import _available_providers
    
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test", "GEMINI_API_KEY": ""}, clear=True):
        providers = _available_providers()
        assert "anthropic" in providers
        assert "gemini" not in providers


# ── 5. cli/env_wizard.py (Status) ──────────────────────────────────────────

def test_env_wizard_status(tmp_path):
    """Test EnvWizard status detection."""
    from cli.env_wizard import EnvWizard
    wizard = EnvWizard(project_dir=str(tmp_path))
    
    # Test all status returns a dict with expected keys
    status = wizard.detect_all_status()
    assert "ANTHROPIC_API_KEY" in status


# ── 6. indexer/ast_indexer.py (Extension Handling) ──────────────────────────

def test_ast_indexer_unsupported_ext(tmp_path):
    """Ensure indexer handles unsupported extensions gracefully."""
    from indexer.ast_indexer import ASTIndexer
    from graph.knowledge_graph import KnowledgeGraph
    
    # Create the file first to avoid FileNotFoundError
    dummy = tmp_path / "dummy.unknown"
    dummy.write_text("content")
    
    idx = ASTIndexer(KnowledgeGraph())
    # Should return empty list for unknown extension
    assert idx._parse_file(str(dummy), "unknown") == []


# ── 7. vector_db/chroma_adapter.py (Behaviour Score) ─────────────────────────

def test_chroma_update_behaviour_mocked():
    """Exercise update_behaviour_score in ChromaDBAdapter."""
    import sys
    from unittest.mock import MagicMock
    with patch.dict(sys.modules, {"chromadb": MagicMock()}):
        from vector_db.chroma_adapter import ChromaDBAdapter
        with patch("chromadb.PersistentClient") as mock_client:
            mock_col = MagicMock()
            mock_client.return_value.get_or_create_collection.return_value = mock_col
            
            adapter = ChromaDBAdapter()
            adapter.update_behaviour_score(0, 0.8)
            assert mock_col.update.called


# ── 8. server/mcp_server.py (Tools Attribute) ───────────────────────────────

def test_mcp_server_tools_attribute():
    """Ensure MCP server instance is created."""
    from server.mcp_server import mcp
    assert mcp is not None
    assert mcp.name == "cognirepo"


# ── 9. config/paths.py (Repo Dir Resolution) ────────────────────────────────

def test_paths_repo_resolution():
    """Test get_cognirepo_dir_for_repo returns a valid storage path."""
    from config.paths import get_cognirepo_dir_for_repo
    path = get_cognirepo_dir_for_repo("/work/project")
    # It should point into ~/.cognirepo/storage/
    assert ".cognirepo" in path
    assert "storage" in path


# ── 10. cli/daemon.py (Watcher Running Logic) ───────────────────────────────

def test_daemon_watcher_check_logic(tmp_path):
    """Exercise is_watcher_running_for_path logic."""
    from cli.daemon import is_watcher_running_for_path
    
    # Check for non-existent repo should return None
    assert is_watcher_running_for_path("/non/existent/path") is None
