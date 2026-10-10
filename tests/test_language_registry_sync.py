# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_language_registry_sync.py — enforce the CLAUDE.md invariant that
interface/cli/service_detect.py::_SERVICE_MARKERS stays in sync with
intelligence/indexer/language_registry.py::_GRAMMAR_MAP (#175), in both directions.

Every language the indexer can parse must either have a build/manifest marker
(so `cognirepo init` can detect it as a service) or be listed in
_NO_MARKER_LANGUAGES with the reason it has none. Conversely, every marker must
name a language the indexer can parse, or be listed in _MARKERS_WITHOUT_GRAMMAR.
A new language or marker therefore fails here until someone decides.

Relies on the `lang_hint` convention documented in service_detect.py:
"<Language>/<Tool>", where the first segment is the language's _LANG_LABELS label.
"""
from __future__ import annotations

from intelligence.indexer.language_registry import _GRAMMAR_MAP, _LANG_LABELS, lang_label
from interface.cli.service_detect import _SERVICE_MARKERS

# Languages served by a marker whose lang_hint doesn't name them directly.
_MARKER_ALIASES: dict[str, str] = {
    "JavaScript": "Node.js",  # package.json
    "TypeScript": "Node.js",  # package.json
}

# Languages that deliberately have no _SERVICE_MARKERS entry. Each needs a reason.
_NO_MARKER_LANGUAGES: dict[str, str] = {
    "Shell": "scripts, not a project type — no build or manifest file",
    "YAML": "config/data files, not a project type",
    "C++": "no single conventional manifest (CMakeLists.txt, Makefile, meson.build, Bazel …); "
           "adding one would change service detection, so it is a separate decision",
}

# Markers whose language the indexer can't parse yet (marker present, grammar not added).
_MARKERS_WITHOUT_GRAMMAR: dict[str, str] = {
    "Dart": "pubspec.yaml — no Dart grammar yet; candidate for a language issue",
}


def _registry_languages() -> set[str]:
    return {lang_label(ext) for ext in _GRAMMAR_MAP}


def _marker_languages() -> set[str]:
    """Language names covered by a marker, from lang_hints like "Java/Maven" or "C#/.NET"."""
    covered: set[str] = set()
    for _service_type, hint in _SERVICE_MARKERS.values():
        covered.update(part.strip() for part in hint.split("/"))
    return covered


def test_every_grammar_extension_has_a_label():
    unlabeled = sorted(ext for ext in _GRAMMAR_MAP if ext not in _LANG_LABELS)
    assert not unlabeled, (
        f"_GRAMMAR_MAP extensions missing from _LANG_LABELS: {unlabeled}. "
        "Add a label so the language can be checked against _SERVICE_MARKERS."
    )


def test_every_registry_language_has_a_service_marker():
    covered = _marker_languages()
    missing = sorted(
        lang for lang in _registry_languages()
        if lang not in _NO_MARKER_LANGUAGES
        and _MARKER_ALIASES.get(lang, lang) not in covered
    )
    assert not missing, (
        f"Languages in language_registry with no _SERVICE_MARKERS entry: {missing}. "
        "Add the language's build/manifest file to interface/cli/service_detect.py::"
        "_SERVICE_MARKERS (lang_hint naming the language, e.g. \"Kotlin/Gradle\"), or, if it "
        "has none, add it to _NO_MARKER_LANGUAGES in this test with the reason."
    )


def test_no_marker_allow_list_is_not_stale():
    """An allow-listed language that is no longer indexed, or that has since gained a
    marker, should be dropped from the list so it can't hide a future regression."""
    registry = _registry_languages()
    covered = _marker_languages()
    not_indexed = sorted(lang for lang in _NO_MARKER_LANGUAGES if lang not in registry)
    has_marker = sorted(
        lang for lang in _NO_MARKER_LANGUAGES if _MARKER_ALIASES.get(lang, lang) in covered
    )
    assert not not_indexed, f"_NO_MARKER_LANGUAGES lists languages not in _GRAMMAR_MAP: {not_indexed}"
    assert not has_marker, f"_NO_MARKER_LANGUAGES lists languages that now have a marker: {has_marker}"


def _marker_first_segments() -> set[str]:
    """The language part of each lang_hint ("Java/Maven" → "Java", "Node.js" → "Node.js")."""
    return {hint.split("/")[0].strip() for _service_type, hint in _SERVICE_MARKERS.values()}


def test_every_marker_language_is_indexed():
    indexed = _registry_languages() | set(_MARKER_ALIASES.values())
    orphans = sorted(
        lang for lang in _marker_first_segments()
        if lang not in indexed and lang not in _MARKERS_WITHOUT_GRAMMAR
    )
    assert not orphans, (
        f"_SERVICE_MARKERS names languages the indexer can't parse: {orphans}. Add the grammar to "
        "language_registry._GRAMMAR_MAP, fix the lang_hint (\"<Language>/<Tool>\", first segment = "
        "the _LANG_LABELS label), or add it to _MARKERS_WITHOUT_GRAMMAR in this test with the reason."
    )


def test_markers_without_grammar_list_is_not_stale():
    indexed = _registry_languages() | set(_MARKER_ALIASES.values())
    markers = _marker_first_segments()
    now_indexed = sorted(lang for lang in _MARKERS_WITHOUT_GRAMMAR if lang in indexed)
    no_marker = sorted(lang for lang in _MARKERS_WITHOUT_GRAMMAR if lang not in markers)
    assert not now_indexed, f"_MARKERS_WITHOUT_GRAMMAR lists languages that are now indexed: {now_indexed}"
    assert not no_marker, f"_MARKERS_WITHOUT_GRAMMAR lists languages with no marker: {no_marker}"


def test_aliases_point_at_real_markers():
    covered = _marker_languages()
    dangling = sorted(f"{lang} → {hint}" for lang, hint in _MARKER_ALIASES.items() if hint not in covered)
    assert not dangling, f"_MARKER_ALIASES targets with no _SERVICE_MARKERS entry: {dangling}"
