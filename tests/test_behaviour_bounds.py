# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""behaviour.json stays bounded and is written compactly (COGNIREPO-118).

It was rewritten whole on every save and nothing but the 50-entry style buffer was capped, so one dev
checkout reached 77 MB: query_history (a uuid per query, forever), session_registry, and
file_edit_cooccurrence (a pair for every two files touched in a session — quadratic).
"""
import json
import os
import random

from data.graph import behaviour_tracker as bt_mod
from data.graph.behaviour_tracker import BehaviourTracker
from data.graph.knowledge_graph import KnowledgeGraph


def _tracker():
    return BehaviourTracker(graph=KnowledgeGraph())


def _file():
    return bt_mod._behaviour_file()  # pylint: disable=protected-access


class TestBounds:
    def test_query_history_keeps_the_newest(self, isolated_cognirepo):
        t = _tracker()
        for i in range(bt_mod.MAX_QUERY_HISTORY + 300):
            t.data["query_history"][f"q{i}"] = {"query_text": "x", "timestamp": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}",
                                                "retrieved_symbols": [], "faiss_rows": [], "useful": None}
        # timestamps above only vary within an hour; make ordering explicit and monotone
        for i, q in enumerate(t.data["query_history"].values()):
            q["timestamp"] = f"2026-01-{1 + i // 86400:02d}T{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}"
        dropped = t.prune()
        assert len(t.data["query_history"]) == bt_mod.MAX_QUERY_HISTORY
        assert dropped["query_history"] == 300
        assert "q0" not in t.data["query_history"] and f"q{bt_mod.MAX_QUERY_HISTORY + 299}" in t.data["query_history"]

    def test_entries_are_trimmed(self, isolated_cognirepo):
        t = _tracker()
        t.record_query("q", "w" * 5000, [f"s{i}" for i in range(100)], list(range(100)))
        t.prune()
        e = t.data["query_history"]["q"]
        assert len(e["query_text"]) == bt_mod.MAX_QUERY_TEXT
        assert len(e["retrieved_symbols"]) == len(e["faiss_rows"]) == bt_mod.MAX_RETRIEVED_PER_QUERY

    def test_sessions_and_files_per_session_are_capped(self, isolated_cognirepo):
        t = _tracker()
        for s in range(bt_mod.MAX_SESSIONS + 10):
            t.data["session_registry"][f"s{s}"] = {"start": f"2026-01-01T00:00:{s:02d}" if s < 60 else f"2026-01-01T00:01:{s - 60:02d}",
                                                  "queries": [], "files_touched": [f"f{i}" for i in range(300)]}
        t.prune()
        assert len(t.data["session_registry"]) == bt_mod.MAX_SESSIONS
        assert all(len(v["files_touched"]) == bt_mod.MAX_FILES_PER_SESSION for v in t.data["session_registry"].values())

    def test_cooccurrence_keeps_the_strongest_partners(self, isolated_cognirepo):
        t = _tracker()
        t.data["file_edit_cooccurrence"]["a.py"] = {f"p{i}": i + 1 for i in range(200)}
        t.prune()
        kept = t.data["file_edit_cooccurrence"]["a.py"]
        assert len(kept) == bt_mod.MAX_COOC_PARTNERS
        assert min(kept.values()) == 200 - bt_mod.MAX_COOC_PARTNERS + 1       # the heaviest survived

    def test_terminology_and_error_files_are_capped(self, isolated_cognirepo):
        t = _tracker()
        t.data["interaction_style"]["terminology"] = {f"term{i}": i for i in range(bt_mod.MAX_TERMS + 100)}
        t.data["error_patterns"]["E"] = {"count": 1, "files": [f"f{i}" for i in range(100)], "occurrences": []}
        t.prune()
        assert len(t.data["interaction_style"]["terminology"]) == bt_mod.MAX_TERMS
        assert "term0" not in t.data["interaction_style"]["terminology"]
        assert len(t.data["error_patterns"]["E"]["files"]) == bt_mod.MAX_ERROR_FILES

    def test_nothing_is_pruned_below_the_bounds(self, isolated_cognirepo):
        t = _tracker()
        t.record_query("q1", "hello world there", ["s1"], [1])
        t.record_file_edit("a.py", "sess")
        t.record_file_edit("b.py", "sess")
        assert t.prune() == {}


class TestPersistence:
    def test_file_is_compact_json(self, isolated_cognirepo):
        t = _tracker()
        t.record_query("q1", "hello world there", ["s1"], [1])
        t.save()
        raw = open(_file(), "rb").read()
        assert b"\n" not in raw and b": " not in raw
        assert json.loads(raw)["query_history"]["q1"]["query_text"] == "hello world there"

    def test_an_oversized_existing_file_shrinks_on_load_and_save(self, isolated_cognirepo):
        big = {"version": 2, "updated_at": "x", "symbol_weights": {}, "error_patterns": {},
               "session_registry": {}, "user_preferences": {}, "query_rewrites": [],
               "file_edit_cooccurrence": {}, "interaction_style": {"query_patterns": [], "terminology": {}},
               "query_history": {f"q{i}": {"query_text": "t" * 300, "timestamp": f"2026-01-01T{i // 3600 % 24:02d}:{i // 60 % 60:02d}:{i % 60:02d}",
                                           "retrieved_symbols": [f"s{j}" for j in range(40)], "faiss_rows": list(range(40)),
                                           "useful": None} for i in range(8000)}}
        os.makedirs(os.path.dirname(_file()), exist_ok=True)
        with open(_file(), "w", encoding="utf-8") as fh:
            json.dump(big, fh, indent=2)
        before = os.path.getsize(_file())
        t = _tracker()
        assert len(t.data["query_history"]) == bt_mod.MAX_QUERY_HISTORY      # bounded already in memory
        t.save()
        after = os.path.getsize(_file())
        assert after < before / 6, (before, after)

    def test_a_stale_writer_cannot_bring_pruned_entries_back(self, isolated_cognirepo):
        """save() merges the on-disk state in; the bound must be applied AFTER that merge."""
        a = _tracker()
        for i in range(bt_mod.MAX_QUERY_HISTORY):
            a.data["query_history"][f"new{i}"] = {"query_text": "n", "timestamp": f"2026-06-01T00:00:{i % 60:02d}.{i:06d}",
                                                   "retrieved_symbols": [], "faiss_rows": [], "useful": None}
        stale = _tracker()                                           # loaded before A saves
        a.save()
        for i in range(500):
            stale.data["query_history"][f"old{i}"] = {"query_text": "o", "timestamp": f"2020-01-01T00:00:00.{i:06d}",
                                                       "retrieved_symbols": [], "faiss_rows": [], "useful": None}
        stale.save()
        on_disk = json.load(open(_file(), encoding="utf-8"))["query_history"]
        assert len(on_disk) == bt_mod.MAX_QUERY_HISTORY
        assert not any(k.startswith("old") for k in on_disk)


def test_size_stays_bounded_over_a_long_run(isolated_cognirepo):
    """The simulation behind the issue: many sessions, many queries — the file must plateau."""
    random.seed(7)
    t = _tracker()
    files = [f"src/pkg{i // 20}/mod{i}.py" for i in range(400)]
    sizes = []
    for rounds in range(3):
        for s in range(30):
            for f in random.sample(files, 60):
                t.record_file_edit(f, f"w{rounds}_{s}")
        for q in range(2000):
            t.record_query(f"r{rounds}q{q}", f"how does module {q % 97} handle thing {q}", [f"sym{q % 50}"], [q % 8])
        t.save()
        sizes.append(os.path.getsize(_file()))
    assert sizes[2] < sizes[0] * 1.35, f"file keeps growing: {sizes}"
    assert sizes[2] < 3_000_000


# ── review of #173: where do the bounds come from, can they be changed, is overflow visible ──────────

def _config(**behaviour):
    import json as _json
    path = os.path.join(".cognirepo", "config.json")
    cfg = _json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    cfg["behaviour"] = behaviour
    with open(path, "w", encoding="utf-8") as fh:
        _json.dump(cfg, fh)


class TestConfigurableBounds:
    def test_defaults_without_config(self, isolated_cognirepo):
        assert bt_mod.behaviour_limits() == bt_mod.DEFAULT_LIMITS

    def test_a_user_can_raise_a_bound(self, isolated_cognirepo):
        _config(max_query_history=5000, max_sessions=200)
        lim = bt_mod.behaviour_limits()
        assert lim["max_query_history"] == 5000 and lim["max_sessions"] == 200
        assert lim["max_terms"] == bt_mod.DEFAULT_LIMITS["max_terms"]          # others untouched
        t = _tracker()
        for i in range(bt_mod.MAX_QUERY_HISTORY + 50):
            t.data["query_history"][f"q{i}"] = {"query_text": "x", "timestamp": f"2026-01-01T00:00:00.{i:07d}",
                                                "retrieved_symbols": [], "faiss_rows": [], "useful": None}
        assert t.prune() == {}                                                  # 2050 < 5000: nothing dropped

    def test_a_user_can_lower_a_bound(self, isolated_cognirepo):
        _config(max_query_history=10)
        t = _tracker()
        for i in range(25):
            t.data["query_history"][f"q{i}"] = {"query_text": "x", "timestamp": f"2026-01-01T00:00:{i:02d}",
                                                "retrieved_symbols": [], "faiss_rows": [], "useful": None}
        assert t.prune()["query_history"] == 15
        assert sorted(t.data["query_history"], key=lambda q: int(q[1:]))[0] == "q15"     # newest 10 kept

    def test_invalid_values_fall_back_to_the_default(self, isolated_cognirepo):
        """A bad config can never switch a bound off or make it nonsensical."""
        for bad in (0, -5, "lots", None, 1.5, True, [3]):
            _config(max_query_history=bad, max_terms=bad)
            lim = bt_mod.behaviour_limits()
            assert lim["max_query_history"] == bt_mod.DEFAULT_LIMITS["max_query_history"], bad
            assert lim["max_terms"] == bt_mod.DEFAULT_LIMITS["max_terms"], bad

    def test_unreadable_config_falls_back(self, isolated_cognirepo):
        with open(os.path.join(".cognirepo", "config.json"), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        assert bt_mod.behaviour_limits() == bt_mod.DEFAULT_LIMITS

    def test_files_per_session_bound_follows_the_config(self, isolated_cognirepo):
        _config(max_files_per_session=5)
        t = _tracker()
        for i in range(12):
            t.record_file_edit(f"f{i}.py", "s")
        assert len(t.data["session_registry"]["s"]["files_touched"]) == 5


class TestOverflowIsVisible:
    def test_a_big_drop_is_logged_at_info_with_the_remedy(self, isolated_cognirepo, caplog):
        import logging
        t = _tracker()
        for i in range(bt_mod.MAX_QUERY_HISTORY + 400):
            t.data["query_history"][f"q{i}"] = {"query_text": "x", "timestamp": f"2026-01-01T00:00:00.{i:07d}",
                                                "retrieved_symbols": [], "faiss_rows": [], "useful": None}
        with caplog.at_level(logging.INFO, logger=bt_mod.__name__):
            t.prune()
        msg = " ".join(r.getMessage() for r in caplog.records)
        assert "dropped 400 old entries" in msg and "config.json" in msg and "query_history" in msg

    def test_a_routine_trim_is_not_info_noise(self, isolated_cognirepo, caplog):
        import logging
        t = _tracker()
        for i in range(bt_mod.MAX_QUERY_HISTORY + 1):
            t.data["query_history"][f"q{i}"] = {"query_text": "x", "timestamp": f"2026-01-01T00:00:00.{i:07d}",
                                                "retrieved_symbols": [], "faiss_rows": [], "useful": None}
        with caplog.at_level(logging.INFO, logger=bt_mod.__name__):
            t.prune()
        assert not [r for r in caplog.records if r.levelno >= logging.INFO]


class TestWhatIsNotPruned:
    """The accumulated learning must survive pruning: only history is bounded."""

    def test_symbol_weights_preferences_and_error_counts_are_untouched(self, isolated_cognirepo):
        t = _tracker()
        t.record_query("q0", "how does the thing work", ["s1"], [1])
        t.record_feedback("q0", True)
        t.record_user_preference("tone", "terse")
        for _ in range(7):
            t.record_error("ValueError", "a.py", "boom")
        for i in range(bt_mod.MAX_QUERY_HISTORY + 500):
            t.data["query_history"][f"x{i}"] = {"query_text": "x", "timestamp": f"2030-01-01T00:00:00.{i:07d}",
                                                "retrieved_symbols": [], "faiss_rows": [], "useful": None}
        t.prune()
        assert "q0" not in t.data["query_history"]                       # the old history is gone ...
        assert t.get_behaviour_score("s1") == 1.0                       # ... what it taught retrieval is not
        assert t.get_preferences()["tone"] == "terse"
        assert t.data["error_patterns"]["ValueError"]["count"] == 7
        assert t.record_feedback("q0", True) is None                    # feedback for a pruned id: ignored, no crash
