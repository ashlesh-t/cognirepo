# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""docs/CLI_REFERENCE.md must describe the CLI that actually exists (#144).

It documented ``cognirepo watch start|stop|status`` for releases while the parser only has
``--status`` / ``--ensure-running`` / ``--foreground`` / ``--path``, and six real commands had no
section at all. The check is made against the REAL argparse parser (captured by intercepting
``parse_args``), not against a hand-kept list, so it cannot drift again:

* every top-level subcommand has a ``## cognirepo <cmd>`` section, and every section is a real command;
* every long flag of a command (including those of its nested subcommands) appears in its section;
* every flag in the first column of a section's tables exists on that command;
* a usage line may not advertise subcommands that the parser does not have (``watch start|stop|status``).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parents[1] / "docs" / "CLI_REFERENCE.md"
_FLAG = re.compile(r"(?<![\w-])(--[A-Za-z][\w-]*)")


def _capture_parser(monkeypatch) -> argparse.ArgumentParser:
    """Run the real CLI entry point up to ``parser.parse_args()`` and hand back that parser."""
    import interface.cli.main as cli
    captured: dict = {}

    def fake_parse_args(self, *_a, **_k):
        captured["parser"] = self
        raise SystemExit(0)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", fake_parse_args)
    monkeypatch.setattr(sys, "argv", ["cognirepo", "doctor"])
    with pytest.raises(SystemExit):
        cli._main()  # pylint: disable=protected-access
    return captured["parser"]


def _subparsers(parser: argparse.ArgumentParser) -> dict:
    for action in parser._actions:  # pylint: disable=protected-access
        if isinstance(action, argparse._SubParsersAction):  # pylint: disable=protected-access
            return dict(action.choices)
    return {}


def _own_flags(parser: argparse.ArgumentParser) -> set:
    flags = set()
    for action in parser._actions:  # pylint: disable=protected-access
        flags.update(o for o in action.option_strings if o.startswith("--"))
    return flags - {"--help"}


def _all_flags(parser: argparse.ArgumentParser) -> set:
    """Long flags of ``parser`` and of every nested subcommand."""
    flags = _own_flags(parser)
    for sub in _subparsers(parser).values():
        flags |= _all_flags(sub)
    return flags


def _nested_names(parser: argparse.ArgumentParser) -> set:
    names = set()
    for name, sub in _subparsers(parser).items():
        names.add(name)
        names |= _nested_names(sub)
    return names


def _has_choice_positionals(parser: argparse.ArgumentParser) -> bool:
    return any(not a.option_strings and a.choices for a in parser._actions  # pylint: disable=protected-access
               if not isinstance(a, argparse._SubParsersAction))  # pylint: disable=protected-access


def _sections() -> dict:
    text = DOC.read_text(encoding="utf-8")
    return {m.group(1): m.group(2)
            for m in re.finditer(r"^## cognirepo ([\w-]+)\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)}


def _table_first_cell_flags(section: str) -> set:
    flags = set()
    for line in section.splitlines():
        if line.startswith("|"):
            cells = line.split("|")
            if len(cells) > 2:
                flags.update(_FLAG.findall(cells[1]))
    return flags


@pytest.fixture()
def cli_tree(monkeypatch):
    top = _subparsers(_capture_parser(monkeypatch))
    assert len(top) > 30, "the CLI parser could not be captured"
    return top


def test_every_command_has_a_section_and_every_section_is_a_command(cli_tree):
    sections = _sections()
    undocumented = sorted(set(cli_tree) - set(sections))
    ghosts = sorted(set(sections) - set(cli_tree))
    assert not undocumented, (
        f"commands with no `## cognirepo <cmd>` section in docs/CLI_REFERENCE.md: {undocumented}")
    assert not ghosts, f"CLI_REFERENCE.md documents commands that do not exist: {ghosts}"


def test_every_flag_is_documented(cli_tree):
    sections = _sections()
    problems = []
    for name, parser in sorted(cli_tree.items()):
        section = sections.get(name, "")
        missing = sorted(f for f in _all_flags(parser) if f not in _FLAG.findall(section))
        if missing:
            problems.append(f"cognirepo {name}: flags missing from its section: {missing}")
    assert not problems, "\n" + "\n".join(problems)


def test_no_documented_flag_is_made_up(cli_tree):
    sections = _sections()
    problems = []
    for name, parser in sorted(cli_tree.items()):
        ghosts = sorted(_table_first_cell_flags(sections.get(name, "")) - _all_flags(parser))
        if ghosts:
            problems.append(f"cognirepo {name}: documented flags that do not exist: {ghosts}")
    assert not problems, "\n" + "\n".join(problems)


def test_nested_subcommands_are_documented(cli_tree):
    sections = _sections()
    problems = []
    for name, parser in sorted(cli_tree.items()):
        for nested in sorted(_subparsers(parser)):
            if not re.search(rf"(?<![\w-]){re.escape(nested)}(?![\w-])", sections.get(name, "")):
                problems.append(f"cognirepo {name} {nested}: not mentioned in its section")
    assert not problems, "\n" + "\n".join(problems)


def test_usage_lines_do_not_advertise_subcommands_that_do_not_exist(cli_tree):
    """`cognirepo watch start|stop|status` was documented for releases; none of those exist."""
    sections = _sections()
    alt = re.compile(r"^[a-z][\w-]*(?:\|[a-z][\w-]*)+$")
    problems = []
    for name, parser in sorted(cli_tree.items()):
        if _has_choice_positionals(parser):
            continue                                   # lowercase alternatives may be legitimate choices
        real_nested = _nested_names(parser)
        for line in re.findall(r"^```[^\n]*\n(.*?)^```", sections.get(name, ""), re.M | re.S):
            for usage in line.splitlines():
                m = re.match(rf"\s*cognirepo {re.escape(name)}\s+(\S+)", usage)
                if m and alt.match(m.group(1)):
                    bogus = [w for w in m.group(1).split("|") if w not in real_nested]
                    if bogus:
                        problems.append(f"cognirepo {name}: usage advertises {bogus} (real subcommands: "
                                        f"{sorted(real_nested) or 'none'})")
    assert not problems, "\n" + "\n".join(problems)


def test_usage_examples_only_use_flags_that_exist(cli_tree):
    """Fenced `cognirepo <cmd> …` lines (usage and examples) may not use flags the command lacks.

    The tables are checked separately; this is what caught `seed [--days N]` (no such flag) and
    `ask … --model/--tier` (removed) hiding in code blocks.
    """
    sections = _sections()
    problems = []
    for name, parser in sorted(cli_tree.items()):
        real = _all_flags(parser) | {"--help", "--version"}
        for block in re.findall(r"^```[^\n]*\n(.*?)^```", sections.get(name, ""), re.M | re.S):
            for line in block.splitlines():
                code = line.split("#", 1)[0]
                if not re.match(rf"\s*cognirepo {re.escape(name)}(\s|$)", code):
                    continue
                bogus = sorted(set(_FLAG.findall(code)) - real)
                if bogus:
                    problems.append(f"cognirepo {name}: `{line.strip()}` uses {bogus}")
    assert not problems, "\n" + "\n".join(problems)
