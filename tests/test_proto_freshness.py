# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_proto_freshness.py — Sprint 5 / TASK-015 acceptance tests.

Covers:
  - cognirepo.proto is committed and parseable
  - cognirepo_pb2.py and cognirepo_pb2_grpc.py exist alongside the .proto
  - The pb2 files define the expected services (QueryService, ContextService)
  - Makefile target `make proto` is documented in the Makefile
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PROTO_DIR = REPO_ROOT / "rpc" / "proto"


class TestProtoCommitted:
    def test_proto_file_exists(self):
        """cognirepo.proto must be committed to rpc/proto/."""
        assert (PROTO_DIR / "cognirepo.proto").exists(), (
            "rpc/proto/cognirepo.proto is missing — commit the .proto source file"
        )

    def test_proto_is_not_empty(self):
        content = (PROTO_DIR / "cognirepo.proto").read_text()
        assert len(content.strip()) > 0

    def test_proto_defines_query_service(self):
        content = (PROTO_DIR / "cognirepo.proto").read_text()
        assert "QueryService" in content

    def test_proto_defines_context_service(self):
        content = (PROTO_DIR / "cognirepo.proto").read_text()
        assert "ContextService" in content

    def test_proto_has_syntax_declaration(self):
        content = (PROTO_DIR / "cognirepo.proto").read_text()
        assert content.startswith("syntax =") or "syntax =" in content


class TestPb2FilesExist:
    def test_pb2_file_exists(self):
        assert (PROTO_DIR / "cognirepo_pb2.py").exists(), (
            "cognirepo_pb2.py is missing — run 'make proto' to generate it"
        )

    def test_pb2_grpc_file_exists(self):
        assert (PROTO_DIR / "cognirepo_pb2_grpc.py").exists(), (
            "cognirepo_pb2_grpc.py is missing — run 'make proto' to generate it"
        )

    def test_pb2_is_importable(self):
        """The generated pb2 module must be importable (no syntax errors)."""
        from rpc.proto import cognirepo_pb2  # noqa: F401
        assert cognirepo_pb2 is not None

    def test_pb2_grpc_is_importable(self):
        from rpc.proto import cognirepo_pb2_grpc  # noqa: F401
        assert cognirepo_pb2_grpc is not None

    def test_pb2_exposes_query_request(self):
        from rpc.proto import cognirepo_pb2
        assert hasattr(cognirepo_pb2, "QueryRequest"), (
            "QueryRequest message missing from pb2 — proto may be stale"
        )

    def test_pb2_exposes_query_response(self):
        from rpc.proto import cognirepo_pb2
        assert hasattr(cognirepo_pb2, "QueryResponse")

    def test_pb2_grpc_exposes_query_servicer(self):
        from rpc.proto import cognirepo_pb2_grpc
        assert hasattr(cognirepo_pb2_grpc, "QueryServiceServicer")

    def test_pb2_grpc_exposes_context_servicer(self):
        from rpc.proto import cognirepo_pb2_grpc
        assert hasattr(cognirepo_pb2_grpc, "ContextServiceServicer")


class TestMakefile:
    def test_makefile_exists(self):
        assert (REPO_ROOT / "Makefile").exists(), (
            "Makefile is missing — add a Makefile with a 'make proto' target"
        )

    def test_makefile_has_proto_target(self):
        content = (REPO_ROOT / "Makefile").read_text()
        assert "proto" in content, "Makefile must contain a 'proto' target"

    def test_makefile_references_grpc_tools(self):
        content = (REPO_ROOT / "Makefile").read_text()
        assert "grpc_tools" in content or "grpcio-tools" in content or "grpc_tools.protoc" in content

    def test_makefile_has_proto_output_dir(self):
        """Makefile must write output to rpc/proto/."""
        content = (REPO_ROOT / "Makefile").read_text()
        assert "rpc/proto" in content
