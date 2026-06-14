# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from memory.project_memory import ProjectMemory

@pytest.fixture
def mock_local_vector_db():
    with patch("vector_db.local_vector_db.LocalVectorDB") as mock:
        yield mock

@pytest.fixture
def mock_encode():
    with patch("memory.project_memory.encode_with_timeout") as mock:
        mock.return_value = [0.1] * 384
        yield mock

def test_project_memory_init(tmp_path):
    with patch("memory.project_memory.get_shared_memory_path") as mock_path:
        mock_path.return_value = tmp_path
        pm = ProjectMemory("test-org", "test-project")
        assert pm._org == "test-org"
        assert pm._project == "test-project"
        assert pm._base == tmp_path
        assert (tmp_path / "vector_db").exists()
        assert (tmp_path / "memory").exists()

def test_project_memory_store(tmp_path, mock_encode):
    with patch("memory.project_memory.get_shared_memory_path") as mock_path:
        mock_path.return_value = tmp_path
        pm = ProjectMemory("test-org", "test-project")
        
        # Test successful store
        pm.store("hello world", "repo-a")
        assert len(pm._db.metadata) == 1
        assert pm._db.metadata[0]["text"] == "hello world"
        assert pm._db.metadata[0]["source"] == "repo-a"

def test_project_memory_search(tmp_path, mock_encode):
    with patch("memory.project_memory.get_shared_memory_path") as mock_path:
        mock_path.return_value = tmp_path
        pm = ProjectMemory("test-org", "test-project")
        pm.store("hello world", "repo-a")
        
        results = pm.search("hello")
        assert len(results) == 1
        assert results[0]["text"] == "hello world"

def test_project_memory_store_failure(tmp_path, mock_encode):
    with patch("memory.project_memory.get_shared_memory_path") as mock_path:
        mock_path.return_value = tmp_path
        pm = ProjectMemory("test-org", "test-project")
        
        mock_encode.side_effect = Exception("encode failed")
        pm.store("hello", "repo-a")  # Should not raise

def test_project_memory_search_failure(tmp_path, mock_encode):
    with patch("memory.project_memory.get_shared_memory_path") as mock_path:
        mock_path.return_value = tmp_path
        pm = ProjectMemory("test-org", "test-project")
        
        mock_encode.side_effect = Exception("search failed")
        results = pm.search("hello")
        assert results == []
