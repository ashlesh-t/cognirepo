# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""`cognirepo doctor --resources` — processes, store sizes, set-aside files (COGNIREPO-121)."""
import json
import os

from interface.cli import resources
from interface.cli.proc_scan import CogniProc


def _write(root, rel, n):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(b"x" * n)
    return p


class TestStoreSizes:
    def test_sums_each_subdirectory_biggest_first_with_largest_files(self, tmp_path):
        r = str(tmp_path / "store")
        _write(r, "graph/graph.pkl", 4000)
        _write(r, "graph/behaviour.json", 9000)
        _write(r, "index/ast.index", 2000)
        _write(r, "config.json", 50)
        stores = resources.store_sizes(r)
        assert [s.name for s in stores] == ["graph", "index", "(top-level files)"]
        g = stores[0]
        assert g.bytes == 13000 and g.files == 2
        assert g.largest[0] == (os.path.join("graph", "behaviour.json"), 9000)

    def test_missing_root_is_empty_not_an_error(self, tmp_path):
        assert resources.store_sizes(str(tmp_path / "nope")) == []

    def test_symlinks_are_not_followed(self, tmp_path):
        r = str(tmp_path / "root")
        outside = str(tmp_path / "outside")
        _write(outside, "big.bin", 100_000)
        os.makedirs(r)
        os.symlink(outside, os.path.join(r, "link"))
        total = sum(s.bytes for s in resources.store_sizes(r))
        assert total < 100_000


class TestSetAside:
    def test_finds_quarantines_stale_indexes_and_scratch(self, tmp_path):
        r = str(tmp_path / "store")
        _write(r, "graph/graph.pkl.corrupt-1700000000", 500)
        _write(r, "graph/graph.pkl.replaced-1700000001", 300)
        _write(r, "index/ast.index.stale", 200)
        _write(r, "index/ast_index.json.abc123.tmp", 100)
        _write(r, "graph/graph.pkl", 9999)                       # live files are not set-aside
        _write(r, "vector_db/chroma.corrupt-1700000002/chroma.sqlite3", 4000)   # a directory
        found = {a.path: a for a in resources.set_aside_files(r)}
        assert set(found) == {
            os.path.join("graph", "graph.pkl.corrupt-1700000000"),
            os.path.join("graph", "graph.pkl.replaced-1700000001"),
            os.path.join("index", "ast.index.stale"),
            os.path.join("index", "ast_index.json.abc123.tmp"),
            os.path.join("vector_db", "chroma.corrupt-1700000002"),
        }
        assert found[os.path.join("vector_db", "chroma.corrupt-1700000002")].bytes == 4000
        assert found[os.path.join("graph", "graph.pkl.corrupt-1700000000")].kind == "quarantine"
        assert found[os.path.join("index", "ast.index.stale")].kind == "stale-index"
        assert resources.set_aside_files(r)[0].bytes == 4000               # biggest first


def _proc(pid, cmd, rss, deleted=False, age=3600.0):
    return CogniProc(pid=pid, ppid=1, age_secs=age, rss_mb=rss, command=cmd, cwd="/r", cwd_deleted=deleted)


class TestProcesses:
    def test_sorted_by_memory_with_stale_and_totals(self, monkeypatch):
        from interface.cli import proc_scan
        monkeypatch.setattr(proc_scan, "scan", lambda *_a, **_k: [
            _proc(1, "watch", 110.0), _proc(2, "init", 128.0, deleted=True), _proc(3, "serve", 220.0)])
        rep = resources.process_report()
        assert [p["pid"] for p in rep["processes"]] == [3, 2, 1]
        assert rep["total_rss_mb"] == 458.0 and rep["stale_rss_mb"] == 128.0
        assert [p["pid"] for p in rep["processes"] if p["stale"]] == [2]

    def test_empty(self, monkeypatch):
        from interface.cli import proc_scan
        monkeypatch.setattr(proc_scan, "scan", lambda *_a, **_k: [])
        assert resources.process_report()["processes"] == []


class TestReport:
    def _report(self, tmp_path, monkeypatch):
        from interface.cli import proc_scan
        monkeypatch.setattr(proc_scan, "scan", lambda *_a, **_k: [_proc(7, "init", 128.0, deleted=True)])
        r = str(tmp_path / "store")
        _write(r, "graph/behaviour.json", 3 * 1024 * 1024)
        _write(r, "graph/graph.pkl.corrupt-1700000000", 2 * 1024 * 1024)
        return resources.collect(r)

    def test_render_has_the_three_sections_and_the_numbers(self, tmp_path, monkeypatch):
        text = resources.render(self._report(tmp_path, monkeypatch))
        assert "Processes" in text and "Stores under .cognirepo/" in text and "Set-aside and left-over files" in text
        assert "STALE" in text and "128.0 MB" in text
        assert "behaviour.json  3.0 MB" in text
        assert "graph.pkl.corrupt-1700000000" in text and "cognirepo graph restore" in text

    def test_report_is_json_serialisable(self, tmp_path, monkeypatch):
        rep = self._report(tmp_path, monkeypatch)
        assert json.loads(json.dumps(rep))["set_aside_bytes"] == 2 * 1024 * 1024


class TestCli:
    def test_doctor_resources_runs_read_only_and_exits_zero(self, isolated_cognirepo, capsys, monkeypatch):
        from interface.cli.main import _cmd_doctor_resources
        _write(os.path.abspath(".cognirepo"), "graph/graph.pkl", 1234)
        before = sorted(os.listdir(".cognirepo"))
        assert _cmd_doctor_resources() == 0
        out = capsys.readouterr().out
        assert "CogniRepo resource report" in out and "graph" in out
        assert sorted(os.listdir(".cognirepo")) == before

    def test_json_mode(self, isolated_cognirepo, capsys):
        from interface.cli.main import _cmd_doctor_resources
        assert _cmd_doctor_resources(as_json=True) == 0
        data = json.loads(capsys.readouterr().out)
        assert {"root", "processes", "stores", "set_aside"} <= set(data)

    def test_flag_is_wired_through_main(self, isolated_cognirepo, capsys, monkeypatch):
        import sys
        import pytest
        import interface.cli.main as cli
        monkeypatch.setattr(sys, "argv", ["cognirepo", "doctor", "--resources", "--json"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0
        assert "processes" in json.loads(capsys.readouterr().out)
