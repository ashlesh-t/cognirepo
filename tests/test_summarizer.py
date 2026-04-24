# pylint: disable=redefined-outer-name
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

import os
import pytest
import json
from unittest.mock import MagicMock, patch
from indexer.summarizer import SummarizationEngine

def test_summarize_file_logic(isolated_cognirepo):  # pylint: disable=unused-argument
    engine = SummarizationEngine()
    
    # Mock ASTIndexer to return some dummy data
    with patch("indexer.ast_indexer.ASTIndexer") as mock_indexer_cls:
        mock_indexer = mock_indexer_cls.return_value
        mock_indexer.index_data = {
            "files": {
                "test.py": {
                    "symbols": [
                        {"name": "TestClass", "type": "CLASS", "docstring": "This is a test class."},
                        {"name": "test_func", "type": "FUNCTION", "docstring": "This is a test function."}
                    ],
                    "language": "python"
                }
            }
        }
        mock_indexer.load = MagicMock()
        
        summary = engine.summarize_file("test.py")
        assert summary["path"] == "test.py"
        assert "TestClass" in summary["classes"]
        assert "test_func" in summary["functions"]
        assert "test class" in summary["purpose"].lower()

def test_run_full_summarization(isolated_cognirepo, tmp_path):  # pylint: disable=unused-argument
    engine = SummarizationEngine(project_root=str(tmp_path))
    
    # Mock ASTIndexer
    with patch("indexer.ast_indexer.ASTIndexer") as mock_indexer_cls:
        mock_indexer = mock_indexer_cls.return_value
        mock_indexer.index_data = {
            "files": {
                "src/main.py": {
                    "symbols": [{"name": "main", "type": "FUNCTION", "docstring": "Main entry point."}],
                    "language": "python"
                },
                "src/utils.py": {
                    "symbols": [{"name": "helper", "type": "FUNCTION", "docstring": "Helper function."}],
                    "language": "python"
                }
            }
        }
        mock_indexer.load = MagicMock()
        mock_indexer.save = MagicMock()
        mock_indexer.faiss_meta = []
        mock_indexer._ensure_faiss = MagicMock()
        
        # Mock embeddings to avoid real model load
        with patch("memory.embeddings.get_model") as mock_get_model:
            mock_model = mock_get_model.return_value
            mock_model.encode.return_value = MagicMock(astype=lambda x: MagicMock())
            
            # We need to make sure directories are created
            os.makedirs(tmp_path / ".cognirepo" / "index", exist_ok=True)
            
            result = engine.run_full_summarization()
            
            assert "repo" in result
            assert "directories" in result
            assert "files" in result
            assert "src/main.py" in result["files"]
            
            save_path = tmp_path / ".cognirepo" / "index" / "summaries.json"
            assert os.path.exists(save_path)
            with open(save_path, "r") as f:
                saved_data = json.load(f)
                assert "repo" in saved_data
