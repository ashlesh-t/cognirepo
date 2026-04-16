# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

import os
import json
import pytest
from unittest.mock import MagicMock, patch
from indexer.summarizer import SummarizationEngine

@pytest.fixture
def mock_route():
    with patch("indexer.summarizer.route") as mock:
        # Return a mock response that has a .text attribute
        mock.return_value = MagicMock(text="This is a test summary.")
        yield mock

def test_summarize_file_logic(isolated_cognirepo, mock_route):
    engine = SummarizationEngine()
    
    # Mock ASTIndexer to return some dummy data
    with patch("indexer.ast_indexer.ASTIndexer") as mock_indexer_cls:
        mock_indexer = mock_indexer_cls.return_value
        mock_indexer.index_data = {
            "files": {
                "test.py": {
                    "symbols": [{"name": "func1"}]
                }
            }
        }
        
        summary = engine.summarize_file("test.py")
        assert summary == "This is a test summary."
        assert mock_route.called

def test_run_full_summarization(isolated_cognirepo, mock_route, tmp_path):
    engine = SummarizationEngine(project_root=str(tmp_path))
    
    # Mock ASTIndexer
    with patch("indexer.ast_indexer.ASTIndexer") as mock_indexer_cls:
        mock_indexer = mock_indexer_cls.return_value
        mock_indexer.index_data = {
            "files": {
                "src/main.py": {"symbols": []},
                "src/utils.py": {"symbols": []}
            }
        }
        
        # We need to make sure directories are created
        os.makedirs(tmp_path / ".cognirepo" / "index", exist_ok=True)
        
        result = engine.run_full_summarization()
        
        assert "repo" in result
        assert "directories" in result
        assert "files" in result
        assert "src/main.py" in result["files"]
        
        save_path = tmp_path / ".cognirepo" / "index" / "summaries.json"
        assert os.path.exists(save_path)
