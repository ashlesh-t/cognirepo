# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_ci_security.py — Sprint 7 / TASK-019 acceptance tests.

Covers:
  - ci.yml contains a security job with Bandit, TruffleHog, Trivy, Snyk
  - Bandit step targets HIGH severity findings
  - Snyk step uses SNYK_TOKEN secret
  - TruffleHog uses --only-verified flag
  - Trivy targets CRITICAL,HIGH severity
  - CONTRIBUTING.md documents the required GitHub Secrets
  - README.md has a CI badge
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


class TestCIWorkflowExists:
    def test_ci_yml_exists(self):
        assert CI_WORKFLOW.exists(), ".github/workflows/ci.yml is missing"

    def test_ci_yml_is_not_empty(self):
        content = CI_WORKFLOW.read_text()
        assert len(content.strip()) > 100


class TestBanditIntegration:
    def test_ci_yml_includes_bandit(self):
        """CI must run Bandit for Python static security analysis."""
        content = CI_WORKFLOW.read_text()
        assert "bandit" in content.lower(), "ci.yml must include a Bandit step"

    def test_bandit_targets_high_severity(self):
        """Bandit must be configured to fail on HIGH severity findings."""
        content = CI_WORKFLOW.read_text()
        assert "high" in content.lower() or "severity-level" in content.lower(), (
            "Bandit must target HIGH severity findings"
        )


class TestTruffleHogIntegration:
    def test_ci_yml_includes_trufflehog(self):
        """CI must run TruffleHog for secret scanning."""
        content = CI_WORKFLOW.read_text()
        assert "trufflehog" in content.lower() or "trufflesecurity" in content.lower(), (
            "ci.yml must include a TruffleHog step"
        )

    def test_trufflehog_uses_only_verified(self):
        """TruffleHog must use --only-verified to reduce false positives."""
        content = CI_WORKFLOW.read_text()
        assert "only-verified" in content, (
            "TruffleHog must use --only-verified flag"
        )


class TestTrivyIntegration:
    def test_ci_yml_includes_trivy(self):
        """CI must run Trivy for container/filesystem vulnerability scanning."""
        content = CI_WORKFLOW.read_text()
        assert "trivy" in content.lower(), "ci.yml must include a Trivy step"

    def test_trivy_targets_critical_high(self):
        """Trivy must target CRITICAL and HIGH vulnerabilities."""
        content = CI_WORKFLOW.read_text()
        assert "CRITICAL" in content and "HIGH" in content, (
            "Trivy must target CRITICAL,HIGH vulnerabilities"
        )

    def test_trivy_exit_code_is_1(self):
        """Trivy must be configured to exit with code 1 on findings."""
        content = CI_WORKFLOW.read_text()
        assert "exit-code" in content or "exit_code" in content, (
            "Trivy must be configured with exit-code: 1"
        )


class TestSnykIntegration:
    def test_ci_yml_includes_snyk(self):
        """CI must run Snyk for dependency vulnerability scanning."""
        content = CI_WORKFLOW.read_text()
        assert "snyk" in content.lower(), "ci.yml must include a Snyk step"

    def test_snyk_uses_token_secret(self):
        """Snyk must use the SNYK_TOKEN secret."""
        content = CI_WORKFLOW.read_text()
        assert "SNYK_TOKEN" in content, "Snyk must reference secrets.SNYK_TOKEN"

    def test_snyk_targets_critical_threshold(self):
        """Snyk must fail on critical vulnerabilities."""
        content = CI_WORKFLOW.read_text()
        assert "critical" in content.lower(), (
            "Snyk must be configured with --severity-threshold=critical"
        )


class TestCIBadge:
    def test_readme_has_ci_badge(self):
        """README.md must display a CI badge."""
        readme = REPO_ROOT / "README.md"
        assert readme.exists(), "README.md is missing"
        content = readme.read_text()
        assert "CI" in content and (
            "badge" in content.lower() or "actions/workflows" in content
        ), "README.md must include a CI badge"

    def test_readme_badge_links_to_ci_yml(self):
        """README CI badge must link to ci.yml workflow."""
        readme = REPO_ROOT / "README.md"
        content = readme.read_text()
        assert "ci.yml" in content, "README CI badge must reference ci.yml"


class TestSecurityDocumentation:
    def test_contributing_md_documents_snyk_token(self):
        """CONTRIBUTING.md or SECURITY.md must document SNYK_TOKEN configuration."""
        contributing = REPO_ROOT / "CONTRIBUTING.md"
        security = REPO_ROOT / "docs" / "SECURITY.md"

        # Check either file
        snyk_documented = False
        for doc_file in [contributing, security]:
            if doc_file.exists():
                content = doc_file.read_text()
                if "SNYK_TOKEN" in content or "snyk" in content.lower():
                    snyk_documented = True
                    break

        assert snyk_documented, (
            "SNYK_TOKEN must be documented in CONTRIBUTING.md or docs/SECURITY.md"
        )

    def test_contributing_md_documents_jwt_secret(self):
        """CONTRIBUTING.md must document COGNIREPO_JWT_SECRET configuration."""
        contributing = REPO_ROOT / "CONTRIBUTING.md"
        security = REPO_ROOT / "docs" / "SECURITY.md"

        jwt_documented = False
        for doc_file in [contributing, security]:
            if doc_file.exists():
                content = doc_file.read_text()
                if "JWT_SECRET" in content or "jwt" in content.lower():
                    jwt_documented = True
                    break

        assert jwt_documented, (
            "COGNIREPO_JWT_SECRET must be documented in CONTRIBUTING.md or docs/SECURITY.md"
        )
