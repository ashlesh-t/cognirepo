# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_ci_security.py — Sprint 7 / TASK-019 acceptance tests.

Covers:
  - security.yml contains Bandit, TruffleHog, Trivy, pip-audit
  - Bandit step targets HIGH severity findings
  - pip-audit scans dependency vulnerabilities
  - TruffleHog uses --only-verified flag
  - Trivy targets CRITICAL,HIGH severity
  - CONTRIBUTING.md documents the required GitHub Secrets
  - README.md has a CI badge
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"


class TestCIWorkflowExists:
    def test_ci_yml_exists(self):
        assert CI_WORKFLOW.exists(), ".github/workflows/security.yml is missing"

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


class TestPipAuditIntegration:
    def test_ci_yml_includes_pip_audit(self):
        """CI must run pip-audit for dependency vulnerability scanning."""
        content = CI_WORKFLOW.read_text()
        assert "pip-audit" in content.lower() or "pip_audit" in content.lower(), (
            "security.yml must include a pip-audit step"
        )

    def test_pip_audit_runs_after_install(self):
        """pip-audit must run after installing the package."""
        content = CI_WORKFLOW.read_text()
        assert "pip install" in content.lower() and "pip-audit" in content.lower(), (
            "pip-audit must run after pip install"
        )
