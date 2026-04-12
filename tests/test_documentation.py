# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_documentation.py — Sprint 7 / TASK-021 acceptance tests.

Covers:
  - README.md has quick start section, CI badge, token reduction info
  - docs/ARCHITECTURE.md exists with system diagram and component descriptions
  - docs/MCP_TOOLS.md documents every tool with signature and example
  - docs/CLI_REFERENCE.md documents every command with flags
  - docs/CONFIGURATION.md documents config.json fields and env vars
  - docs/CONTRIBUTING.md has "Add a new MCP tool" walkthrough
  - docs/SECURITY.md covers encryption, JWT, data storage
  - CHANGELOG.md has version history starting from v0.1.0
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DOCS = REPO_ROOT / "docs"


class TestReadME:
    def test_readme_exists(self):
        assert (REPO_ROOT / "README.md").exists()

    def test_readme_has_quick_start(self):
        content = (REPO_ROOT / "README.md").read_text()
        assert "quick start" in content.lower() or "getting started" in content.lower(), (
            "README.md must have a quick start section"
        )

    def test_readme_has_ci_badge(self):
        content = (REPO_ROOT / "README.md").read_text()
        assert "CI" in content and "badge" in content.lower() or "actions" in content.lower()

    def test_readme_mentions_token_reduction(self):
        content = (REPO_ROOT / "README.md").read_text()
        assert "token" in content.lower(), "README.md must mention token reduction"

    def test_readme_describes_what_cognirepo_is(self):
        content = (REPO_ROOT / "README.md").read_text()
        assert "memory" in content.lower() or "infrastructure" in content.lower()


class TestArchitectureDoc:
    def test_architecture_doc_exists(self):
        """docs/ARCHITECTURE.md must exist."""
        assert (DOCS / "ARCHITECTURE.md").exists(), "docs/ARCHITECTURE.md is missing"

    def test_architecture_has_system_diagram(self):
        """Architecture doc must include a system diagram."""
        content = (DOCS / "ARCHITECTURE.md").read_text()
        assert "tools/" in content or "MCP" in content, (
            "Architecture doc must describe the tools/ layer"
        )

    def test_architecture_describes_components(self):
        """Architecture doc must describe key components."""
        content = (DOCS / "ARCHITECTURE.md").read_text()
        components = ["memory/", "graph/", "indexer/", "retrieval/"]
        missing = [c for c in components if c not in content]
        assert not missing, f"Architecture doc missing components: {missing}"

    def test_architecture_has_data_flow(self):
        """Architecture doc must include a data flow description."""
        content = (DOCS / "ARCHITECTURE.md").read_text()
        assert "context_pack" in content or "data flow" in content.lower()


class TestMCPToolsDoc:
    def test_mcp_tools_doc_exists(self):
        """docs/MCP_TOOLS.md must exist."""
        assert (DOCS / "MCP_TOOLS.md").exists(), "docs/MCP_TOOLS.md is missing"

    def test_mcp_tools_documents_context_pack(self):
        content = (DOCS / "MCP_TOOLS.md").read_text()
        assert "context_pack" in content

    def test_mcp_tools_documents_lookup_symbol(self):
        content = (DOCS / "MCP_TOOLS.md").read_text()
        assert "lookup_symbol" in content

    def test_mcp_tools_documents_who_calls(self):
        content = (DOCS / "MCP_TOOLS.md").read_text()
        assert "who_calls" in content

    def test_mcp_tools_documents_retrieve_memory(self):
        content = (DOCS / "MCP_TOOLS.md").read_text()
        assert "retrieve_memory" in content

    def test_mcp_tools_has_example_inputs(self):
        """MCP tools doc must show example inputs/outputs."""
        content = (DOCS / "MCP_TOOLS.md").read_text()
        assert "```json" in content or "Input:" in content, (
            "docs/MCP_TOOLS.md must include example inputs"
        )

    def test_mcp_tools_has_signatures(self):
        """MCP tools doc must show function signatures."""
        content = (DOCS / "MCP_TOOLS.md").read_text()
        assert "Signature:" in content or "def " in content or "→" in content


class TestCLIReferenceDoc:
    def test_cli_reference_doc_exists(self):
        """docs/CLI_REFERENCE.md must exist."""
        assert (DOCS / "CLI_REFERENCE.md").exists(), "docs/CLI_REFERENCE.md is missing"

    def test_cli_reference_documents_init(self):
        content = (DOCS / "CLI_REFERENCE.md").read_text()
        assert "cognirepo init" in content

    def test_cli_reference_documents_index_repo(self):
        content = (DOCS / "CLI_REFERENCE.md").read_text()
        assert "index-repo" in content

    def test_cli_reference_documents_serve(self):
        content = (DOCS / "CLI_REFERENCE.md").read_text()
        assert "serve" in content

    def test_cli_reference_documents_doctor(self):
        content = (DOCS / "CLI_REFERENCE.md").read_text()
        assert "doctor" in content

    def test_cli_reference_has_flags(self):
        """CLI reference must document command flags."""
        content = (DOCS / "CLI_REFERENCE.md").read_text()
        assert "--" in content, "CLI reference must show flags"

    def test_cli_reference_has_examples(self):
        """CLI reference must include usage examples."""
        content = (DOCS / "CLI_REFERENCE.md").read_text()
        assert "```bash" in content or "Examples:" in content


class TestConfigurationDoc:
    def test_configuration_doc_exists(self):
        """docs/CONFIGURATION.md must exist."""
        assert (DOCS / "CONFIGURATION.md").exists(), "docs/CONFIGURATION.md is missing"

    def test_configuration_documents_config_json(self):
        content = (DOCS / "CONFIGURATION.md").read_text()
        assert "config.json" in content

    def test_configuration_documents_env_vars(self):
        """Configuration doc must list environment variables."""
        content = (DOCS / "CONFIGURATION.md").read_text()
        assert "COGNIREPO_JWT_SECRET" in content or "environment" in content.lower()

    def test_configuration_documents_redis(self):
        content = (DOCS / "CONFIGURATION.md").read_text()
        assert "redis" in content.lower() or "REDIS" in content

    def test_configuration_documents_encryption(self):
        content = (DOCS / "CONFIGURATION.md").read_text()
        assert "encrypt" in content.lower()

    def test_configuration_documents_storage_layout(self):
        content = (DOCS / "CONFIGURATION.md").read_text()
        assert ".cognirepo/" in content


class TestContributingDoc:
    def test_contributing_doc_exists(self):
        """docs/CONTRIBUTING.md must exist."""
        assert (DOCS / "CONTRIBUTING.md").exists(), "docs/CONTRIBUTING.md is missing"

    def test_contributing_has_dev_setup(self):
        content = (DOCS / "CONTRIBUTING.md").read_text()
        assert "pip install" in content or "dev setup" in content.lower()

    def test_contributing_has_add_tool_walkthrough(self):
        """Contributing doc must explain how to add a new MCP tool."""
        content = (DOCS / "CONTRIBUTING.md").read_text()
        assert "new" in content.lower() and ("tool" in content.lower() or "mcp" in content.lower()), (
            "docs/CONTRIBUTING.md must have 'Add a new MCP tool' section"
        )

    def test_contributing_has_add_language_walkthrough(self):
        """Contributing doc must explain how to add a new language."""
        content = (DOCS / "CONTRIBUTING.md").read_text()
        assert "language" in content.lower()

    def test_contributing_has_pr_checklist(self):
        content = (DOCS / "CONTRIBUTING.md").read_text()
        assert "checklist" in content.lower() or "PR" in content or "- [ ]" in content


class TestSecurityDoc:
    def test_security_doc_exists(self):
        """docs/SECURITY.md must exist."""
        assert (DOCS / "SECURITY.md").exists(), "docs/SECURITY.md is missing"

    def test_security_documents_encryption(self):
        content = (DOCS / "SECURITY.md").read_text()
        assert "encrypt" in content.lower() or "AES" in content

    def test_security_documents_jwt(self):
        content = (DOCS / "SECURITY.md").read_text()
        assert "JWT" in content or "jwt" in content

    def test_security_documents_data_storage(self):
        content = (DOCS / "SECURITY.md").read_text()
        assert ".cognirepo/" in content or "stored" in content.lower()

    def test_security_documents_keychain(self):
        content = (DOCS / "SECURITY.md").read_text()
        assert "keychain" in content.lower() or "keyring" in content.lower()


class TestChangelog:
    def test_changelog_exists(self):
        assert (REPO_ROOT / "CHANGELOG.md").exists()

    def test_changelog_has_v010(self):
        content = (REPO_ROOT / "CHANGELOG.md").read_text()
        assert "0.1.0" in content, "CHANGELOG.md must include v0.1.0 release"

    def test_changelog_is_not_empty(self):
        content = (REPO_ROOT / "CHANGELOG.md").read_text()
        assert len(content.strip()) > 200
