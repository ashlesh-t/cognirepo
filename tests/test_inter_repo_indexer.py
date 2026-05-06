# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT

import pytest
import os
import json
from pathlib import Path
from indexer.inter_repo_indexer import extract_dependencies, _strip_version, _normalize

def test_strip_version():
    assert _strip_version("requests>=2.28.0") == "requests"
    assert _strip_version("fastapi[all]") == "fastapi"
    assert _strip_version("numpy") == "numpy"
    assert _strip_version("pandas<1.0; python_version < '3.8'") == "pandas"

def test_normalize():
    assert _normalize("My_Repo") == "myrepo"
    assert _normalize("my-repo") == "myrepo"
    assert _normalize("my.repo") == "myrepo"

def test_extract_dependencies_python(tmp_path):
    repo_a = tmp_path / "repo_a"
    repo_a.mkdir()
    
    # Create pyproject.toml
    pyproject = repo_a / "pyproject.toml"
    pyproject.write_text("""
[project]
dependencies = [
    "repo-b",
    "external-pkg"
]
""", encoding="utf-8")
    
    # Create requirements.txt
    requirements = repo_a / "requirements.txt"
    requirements.write_text("""repo-c>=1.0
# comment
""", encoding="utf-8")
    
    org_repos = [
        str(tmp_path / "repo_b"),
        str(tmp_path / "repo_c")
    ]
    for r in org_repos:
        os.makedirs(r, exist_ok=True)
        
    edges = extract_dependencies(str(repo_a), org_repos)
    
    # Should find repo-b and repo-c
    targets = {e.dst_repo for e in edges}
    assert any("repo_b" in t for t in targets)
    assert any("repo_c" in t for t in targets)
    assert len(edges) == 2

def test_extract_dependencies_nodejs(tmp_path):
    repo_node = tmp_path / "node_app"
    repo_node.mkdir()
    
    package_json = repo_node / "package.json"
    package_json.write_text(json.dumps({
        "dependencies": {
            "@org/service-auth": "^1.0.0"
        }
    }), encoding="utf-8")
    
    org_repos = [str(tmp_path / "service_auth")]
    os.makedirs(org_repos[0], exist_ok=True)
    
    edges = extract_dependencies(str(repo_node), org_repos)
    assert len(edges) == 1
    assert "service_auth" in edges[0].dst_repo

def test_extract_dependencies_go_rust(tmp_path):
    repo_mixed = tmp_path / "mixed"
    repo_mixed.mkdir()
    
    go_mod = repo_mixed / "go.mod"
    go_mod.write_text("""module mixed

require github.com/org/go-lib v1.0.0
""", encoding="utf-8")
    
    cargo_toml = repo_mixed / "Cargo.toml"
    cargo_toml.write_text("""
[dependencies]
rust-crate = "0.1"
""", encoding="utf-8")
    
    org_repos = [
        str(tmp_path / "go-lib"),
        str(tmp_path / "rust_crate")
    ]
    for r in org_repos:
        os.makedirs(r, exist_ok=True)
        
    edges = extract_dependencies(str(repo_mixed), org_repos)
    assert len(edges) == 2
    targets = {os.path.basename(e.dst_repo) for e in edges}
    assert "go-lib" in targets
    assert "rust_crate" in targets

def test_extract_dependencies_invalid_path():
    assert extract_dependencies("/non/existent/path", []) == []
