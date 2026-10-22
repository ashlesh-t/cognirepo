# pylint: disable=missing-docstring, protected-access, redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""An incremental index run must never lose a file's graph nodes because embedding failed.

Found by a concurrency test in an environment without ``fastembed``: ``index-repo --changed-only`` removed a
changed file's graph nodes, the inline embedding then raised, the error was swallowed at debug level, and the
run saved a graph with those nodes gone ("Re-indexed 0 changed file(s)", 6 nodes -> 0).
"""
import os
import pickle
import subprocess
import sys

import pytest

from data.graph.knowledge_graph import KnowledgeGraph
from intelligence.indexer.ast_indexer import ASTIndexer


class ExplodingModel:
    def __init__(self):
        self.calls = 0

    def embed(self, _texts):
        self.calls += 1
        raise RuntimeError("model unavailable")


@pytest.fixture
def indexed(tmp_path):
    """An indexer that already knows ``m.py`` (so a re-index removes its old graph nodes first)."""
    src = tmp_path / "m.py"
    src.write_text("def old_one():\n    return 1\n\ndef old_two():\n    return 2\n")
    idx = ASTIndexer(graph=KnowledgeGraph())
    idx._embed_enabled = False
    idx.index_file("m.py", str(src))
    return idx, src


class TestIndexFileSurvivesEmbeddingFailure:
    def test_graph_is_updated_even_though_embedding_raises(self, indexed):
        idx, src = indexed
        assert any("old_one" in n for n in idx.graph.node_ids())
        src.write_text("def new_one():\n    return 1\n\ndef new_two():\n    return 2\n")
        idx._embed_enabled = True
        idx._batch_mode = False
        idx.model = ExplodingModel()
        record = idx.index_file("m.py", str(src))           # used to raise after removing the old nodes
        names = {s["name"] for s in record["symbols"]}
        assert names == {"new_one", "new_two"}
        ids = list(idx.graph.node_ids())
        assert any("new_one" in n for n in ids) and any("new_two" in n for n in ids)
        assert not any("old_one" in n for n in ids)          # stale nodes still removed
        assert all(s["faiss_id"] == -1 for s in record["symbols"])   # no vector, as with --no-embed

    def test_a_failing_model_is_tried_once_not_per_symbol(self, indexed):
        idx, src = indexed
        src.write_text("".join(f"def f{i}():\n    return {i}\n\n" for i in range(8)))
        idx._embed_enabled, idx._batch_mode = True, False
        idx.model = ExplodingModel()
        idx.index_file("m.py", str(src))
        assert idx.model.calls == 1 and idx._embed_broken is True

    def test_later_files_skip_embedding_without_error(self, indexed, tmp_path):
        idx, src = indexed
        src.write_text("def a():\n    return 1\n")
        idx._embed_enabled, idx._batch_mode = True, False
        idx.model = ExplodingModel()
        idx.index_file("m.py", str(src))
        other = tmp_path / "n.py"
        other.write_text("def b():\n    return 2\n")
        idx.index_file("n.py", str(other))
        assert idx.model.calls == 1
        assert any("b" in n for n in idx.graph.node_ids())

    def test_working_embedding_is_unchanged(self, indexed):
        idx, src = indexed

        class Fine:
            def embed(self, _t):
                import numpy as np
                yield np.zeros(384, dtype="float32")

        src.write_text("def only():\n    return 1\n")
        idx._embed_enabled, idx._batch_mode = True, False
        idx.model = Fine()
        record = idx.index_file("m.py", str(src))
        assert record["symbols"][0]["faiss_id"] >= 0 and not getattr(idx, "_embed_broken", False)


def _write_stub_fastembed(dirpath):
    pkg = dirpath / "fastembed"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        "class TextEmbedding:\n"
        "    def __init__(self, *a, **k):\n"
        "        raise RuntimeError('no embedding model in this environment')\n")


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the checkout under test


def _cli(repo, env_extra, *args):
    env = {**os.environ, "COGNIREPO_NO_WATCHER": "1", "COGNIREPO_GLOBAL_DIR": str(repo / ".g"), **env_extra}
    env["PYTHONPATH"] = os.pathsep.join(p for p in (env_extra.get("PYTHONPATH"), ROOT, os.environ.get("PYTHONPATH")) if p)
    return subprocess.run([sys.executable, "-m", "interface.cli.main", *args], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=240, check=False)


def _git(repo, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
                   cwd=repo, check=True, capture_output=True)


class TestRealCliWithoutAnEmbeddingModel:
    def test_changed_only_keeps_and_updates_the_graph(self, tmp_path):
        repo = tmp_path / "proj"
        repo.mkdir()
        _git(repo, "init", "-q")
        (repo / ".cognirepo").mkdir(exist_ok=True)
        (repo / ".cognirepo" / "config.json").write_text("{}")
        for i in range(3):
            (repo / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "x")
        assert _cli(repo, {}, "index-repo", ".", "--no-embed", "--no-watch").returncode == 0

        def graph_nodes():
            with open(repo / ".cognirepo" / "graph" / "graph.pkl", "rb") as fh:
                return set(pickle.load(fh).nodes)

        before = graph_nodes()
        assert len(before) >= 6
        stub = tmp_path / "stub"
        stub.mkdir()
        _write_stub_fastembed(stub)
        for i in range(3):
            (repo / f"m{i}.py").write_text(f"def g{i}():\n    return {i + 100}\n")
        out = _cli(repo, {"PYTHONPATH": str(stub) + os.pathsep + os.environ.get("PYTHONPATH", "")},
                   "index-repo", "--changed-only")
        assert out.returncode == 0, out.stderr
        assert "Re-indexed 3 changed file(s)" in out.stdout
        after = graph_nodes()
        assert len(after) >= len(before)                                  # was 0 before the fix
        assert any("g0" in n for n in after) and not any("f0" in n for n in after)


class TestFailuresAreReportedNotSwallowed:
    def test_incremental_index_returns_the_failed_files_and_saves_the_rest(self, tmp_path, monkeypatch):
        from interface.cli import main as cli
        monkeypatch.chdir(tmp_path)
        (tmp_path / "good.py").write_text("def good():\n    return 1\n")
        (tmp_path / "bad.py").write_text("def bad():\n    return 1\n")
        real = ASTIndexer.index_file

        def flaky(self, rel, abs_path=None, weight=1.0):
            if rel == "bad.py":
                raise ValueError("boom")
            return real(self, rel, abs_path, weight)

        monkeypatch.setattr(ASTIndexer, "index_file", flaky)
        (tmp_path / ".cognirepo").mkdir(exist_ok=True)
        monkeypatch.setattr(cli, "_require_complete_base_graph", lambda *a, **k: None)   # no base graph in this unit test
        indexed, failed = cli._incremental_index(["good.py", "bad.py"], "--files", embed=False)
        assert indexed == 1 and failed == [("bad.py", "ValueError: boom")]

    def test_report_and_exit_code(self, capsys):
        from interface.cli import main as cli
        assert cli._report_incremental_failures([]) == 0
        assert cli._report_incremental_failures([("a.py", "ValueError: x")] * 12) == 1
        err = capsys.readouterr().err
        assert "12 file(s) could not be indexed" in err and "a.py: ValueError: x" in err and "and 2 more" in err

    def test_files_mode_exits_non_zero_and_changed_only_does_not_record_the_commit(self, monkeypatch, tmp_path):
        from interface.cli import main as cli
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".cognirepo").mkdir(exist_ok=True)
        (tmp_path / ".cognirepo" / "config.json").write_text("{}")
        monkeypatch.setattr(cli, "_incremental_index", lambda files, mode, embed: (0, [("a.py", "ValueError: x")]))
        recorded = []
        monkeypatch.setattr(cli, "_write_last_indexed_sha", lambda p: recorded.append(p))
        monkeypatch.setattr(sys, "argv", ["cognirepo", "index-repo", "--files", "a.py"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "a.py").write_text("x = 1\n")
        monkeypatch.setattr(sys, "argv", ["cognirepo", "index-repo", "--changed-only"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1 and recorded == []
