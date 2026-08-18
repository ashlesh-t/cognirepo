# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
interface/tools/insights.py — COGNIREPO-302 HTML generator + idempotent writer.

Renders an intelligence.orchestrator.insights_collector InsightsModel into one
self-contained, offline, light/dark-aware HTML report plus a markdown twin for
docs_index ingestion (COGNIREPO-303). Stateless: render()/write()/generate()
take everything they need as arguments, no cross-tool calls.

Storage target `.claude/insights/<repoName>-insights.html` is the proposed
CLAUDE.md storage-exception (docs/planning/02-insights-feature.md
§Architecture-rule-compliance) — the amendment itself lands in COGNIREPO-303;
this module only implements the write path.
"""
from __future__ import annotations

import html as html_lib
import os
import re
import tempfile

_GENERATED_AT_RE = re.compile(r'<meta name="cognirepo:generated-at" content="([^"]*)">')


def _slugify(name: str) -> str:
    """ASCII-safe filename slug for a repo's display name (spaces/unicode-safe)."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-").lower()
    return slug or "repo"


def _esc(value) -> str:
    return html_lib.escape(str(value), quote=True)


def _atomic_write(path: str, content: str) -> None:
    """tmp + os.replace — same pattern as ast_indexer.py::_atomic_json_dump."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _fact_list(items: list, empty_label: str, row_fn) -> str:
    """Render a <ul> of data-ref-carrying facts, or a "no data recorded" note."""
    if not items:
        return f'<p class="no-data">{_esc(empty_label)}</p>'
    rows = "\n".join(f"    <li data-ref=\"{_esc(ref)}\">{text}</li>" for ref, text in (row_fn(i) for i in items))
    return f"  <ul>\n{rows}\n  </ul>"


def _render_timeline(section: dict) -> str:
    if section["status"] != "ok":
        return '<p class="no-data">no data recorded</p>'

    def row(e):
        return e["ref"], f'<span class="ts">{_esc(e["ts"])}</span> <span class="kind">{_esc(e["kind"])}</span> — {_esc(e["summary"])}'

    rollup = section["rollup"]
    counts = ", ".join(f"{_esc(k)}: {v}" for k, v in rollup["counts"].items()) or "none"
    return (
        f'<p class="rollup">total: {rollup["total"]} ({counts})</p>\n'
        + _fact_list(section["entries"], "no data recorded", row)
    )


def _render_decisions(section: dict) -> str:
    return _fact_list(
        section["items"], "no data recorded",
        lambda e: (e["ref"], f'<span class="ts">{_esc(e["ts"])}</span> — {_esc(e["summary"])}'),
    )


def _render_challenges(section: dict) -> str:
    return _fact_list(
        section["items"], "no data recorded",
        lambda e: (e["ref"], f'<span class="ts">{_esc(e["ts"])}</span> — {_esc(e["summary"])}'),
    )


def _render_branches(section: dict) -> str:
    def row(b):
        lc = b["last_commit"]
        ab = "default branch" if b["is_default"] else f'{b["ahead"]} ahead / {b["behind"]} behind'
        return lc["hash"], (
            f'<strong>{_esc(b["name"])}</strong> ({ab}) — '
            f'<code>{_esc(lc["hash"][:8])}</code> {_esc(lc["date"])} {_esc(lc["message"])}'
        )
    return _fact_list(section["items"], "no data recorded", row)


def _render_commits_by_week(section: dict) -> str:
    def row(w):
        return w["week"], f'{_esc(w["week"])} — {w["commits"]} commits (+{w["added"]}/-{w["removed"]})'
    return _fact_list(section["weeks"], "no data recorded", row)


def _render_hot_symbols(section: dict) -> str:
    def row(s):
        return s["symbol_id"], f'{_esc(s["name"])} — {s["hit_count"]} hits'
    return _fact_list(section["items"], "no data recorded", row)


def _render_index_health(section: dict) -> str:
    if section["status"] != "ok":
        return '<p class="no-data">no data recorded</p>'
    facts = [
        ("index_health.symbols", f'symbols indexed: {section["symbols"]}'),
        ("index_health.files", f'files indexed: {section["files"]}'),
        ("index_health.last_indexed", f'last indexed: {_esc(section["last_indexed"])}'),
    ]
    if "graph_stats" in section:
        gs = section["graph_stats"]
        facts.append(("index_health.graph_stats.nodes", f'graph nodes: {gs["nodes"]}'))
        facts.append(("index_health.graph_stats.edges", f'graph edges: {gs["edges"]}'))
    if "integrity" in section:
        integ = section["integrity"]
        facts.append(("index_health.integrity.orphans", f'orphan nodes: {len(integ["orphans"])}'))
        facts.append(("index_health.integrity.dangling_files", f'dangling files: {len(integ["dangling_files"])}'))
    rows = "\n".join(f'    <li data-ref="{_esc(ref)}">{text}</li>' for ref, text in facts)
    return f"  <ul>\n{rows}\n  </ul>"


_CSS = """
:root {
  --bg: #ffffff; --fg: #1a1a1a; --muted: #6b6b6b; --border: #e2e2e2;
  --accent: #3457d5; --card-bg: #f7f7f8; --code-bg: #eef0f4;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14161a; --fg: #e8e8e8; --muted: #9a9a9a; --border: #2c2f36;
    --accent: #7f9cff; --card-bg: #1c1f26; --code-bg: #22262e;
  }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
nav {
  position: sticky; top: 0; background: var(--bg); border-bottom: 1px solid var(--border);
  padding: 0.75rem 1.5rem; display: flex; gap: 1.25rem; flex-wrap: wrap; z-index: 1;
}
nav a { color: var(--muted); text-decoration: none; font-size: 0.9rem; }
nav a:hover { color: var(--accent); }
main { max-width: 860px; margin: 0 auto; padding: 1.5rem; }
header.overview { margin-bottom: 2rem; }
header.overview h1 { margin: 0 0 0.25rem; font-size: 1.5rem; }
header.overview p { margin: 0.15rem 0; color: var(--muted); font-size: 0.9rem; }
section { margin-bottom: 2.5rem; }
section h2 {
  font-size: 1.1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4rem;
}
ul { list-style: none; margin: 0; padding: 0; }
li {
  padding: 0.5rem 0.75rem; border-radius: 6px; margin-bottom: 0.35rem;
  background: var(--card-bg);
}
.ts { color: var(--muted); font-size: 0.85em; }
.kind {
  text-transform: uppercase; font-size: 0.72em; letter-spacing: 0.04em;
  color: var(--accent);
}
code { background: var(--code-bg); padding: 0.1rem 0.3rem; border-radius: 4px; }
.no-data { color: var(--muted); font-style: italic; }
.rollup { color: var(--muted); font-size: 0.85rem; }
"""

_SECTIONS = [
    ("overview", "Overview", None),
    ("timeline", "Timeline", _render_timeline),
    ("decisions", "Decisions", _render_decisions),
    ("challenges", "Challenges", _render_challenges),
    ("activity", "Branch / Commit Activity", None),
    ("index-health", "Index Health", _render_index_health),
]


def render(model: dict, generated_at: str, updated_at: str) -> str:
    """Render model (InsightsModel from insights_collector.collect()) into a
    single self-contained HTML string. Pure function — deterministic given the
    same model + timestamps, no I/O.
    """
    meta = model["meta"]
    repo_name = os.path.basename(meta["repo_root"].rstrip(os.sep)) or meta["repo_root"]
    title = f"{repo_name} — Insights"

    nav_links = "\n".join(f'    <a href="#{sid}">{label}</a>' for sid, label, _ in _SECTIONS)

    branches_html = _render_branches(model["branches"])
    commits_html = _render_commits_by_week(model["commits_by_week"])
    hot_html = _render_hot_symbols(model["hot_symbols"])

    body_sections = f"""
  <section id="overview">
    <h2>Overview</h2>
  </section>

  <section id="timeline">
    <h2>Timeline</h2>
{_render_timeline(model["timeline"])}
  </section>

  <section id="decisions">
    <h2>Decisions</h2>
{_render_decisions(model["decisions"])}
  </section>

  <section id="challenges">
    <h2>Challenges (recurring errors)</h2>
{_render_challenges(model["errors"])}
  </section>

  <section id="activity">
    <h2>Branch / Commit Activity</h2>
    <h3>Branches</h3>
{branches_html}
    <h3>Commits by week</h3>
{commits_html}
    <h3>Hot symbols</h3>
{hot_html}
  </section>

  <section id="index-health">
    <h2>Index Health</h2>
{_render_index_health(model["index_health"])}
  </section>
"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="cognirepo:generated-at" content="{_esc(generated_at)}">
  <meta name="cognirepo:updated-at" content="{_esc(updated_at)}">
  <title>{_esc(title)}</title>
  <style>{_CSS}</style>
</head>
<body>
  <nav>
{nav_links}
  </nav>
  <main>
    <header class="overview">
      <h1>{_esc(repo_name)}</h1>
      <p>repo: <code>{_esc(meta["repo_root"])}</code></p>
      <p>window: last {_esc(meta["since"])}</p>
      <p>generated: {_esc(generated_at)} &middot; updated: {_esc(updated_at)}</p>
    </header>
{body_sections}
  </main>
</body>
</html>
"""


def _render_markdown(model: dict, generated_at: str, updated_at: str) -> str:
    """Plain-text twin for docs_index ingestion (COGNIREPO-303 wires the ingest call)."""
    meta = model["meta"]
    repo_name = os.path.basename(meta["repo_root"].rstrip(os.sep)) or meta["repo_root"]
    lines = [
        f"# {repo_name} — Insights",
        "",
        f"repo: {meta['repo_root']}",
        f"window: last {meta['since']}",
        f"generated: {generated_at} · updated: {updated_at}",
        "",
        "## Timeline",
    ]
    timeline = model["timeline"]
    if timeline["status"] == "ok":
        for e in timeline["entries"]:
            lines.append(f"- [{e['kind']}] {e['ts']} — {e['summary']} (ref: {e['ref']})")
    else:
        lines.append("no data recorded")

    lines += ["", "## Decisions"]
    if model["decisions"]["status"] == "ok":
        for e in model["decisions"]["items"]:
            lines.append(f"- {e['ts']} — {e['summary']} (ref: {e['ref']})")
    else:
        lines.append("no data recorded")

    lines += ["", "## Challenges (recurring errors)"]
    if model["errors"]["status"] == "ok":
        for e in model["errors"]["items"]:
            lines.append(f"- {e['ts']} — {e['summary']} (ref: {e['ref']})")
    else:
        lines.append("no data recorded")

    lines += ["", "## Branches"]
    if model["branches"]["status"] == "ok":
        for b in model["branches"]["items"]:
            lines.append(f"- {b['name']} — {b['last_commit']['hash'][:8]} {b['last_commit']['message']}")
    else:
        lines.append("no data recorded")

    lines += ["", "## Index health"]
    ih = model["index_health"]
    if ih["status"] == "ok":
        lines.append(f"- symbols: {ih['symbols']}, files: {ih['files']}, last indexed: {ih['last_indexed']}")
    else:
        lines.append("no data recorded")

    return "\n".join(lines) + "\n"


def write(html_str: str, repo_root: str) -> str:
    """Write html_str to .claude/insights/<repoName>-insights.html, creating the
    directory if absent. Atomic (tmp + os.replace). Returns the written path.
    """
    repo_name = os.path.basename(os.path.abspath(repo_root).rstrip(os.sep))
    slug = _slugify(repo_name)
    path = os.path.join(repo_root, ".claude", "insights", f"{slug}-insights.html")
    _atomic_write(path, html_str)
    return path


def _write_markdown_twin(md_str: str, repo_root: str) -> str:
    from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel

    repo_name = os.path.basename(os.path.abspath(repo_root).rstrip(os.sep))
    slug = _slugify(repo_name)
    cognirepo_dir = get_cognirepo_dir_for_repo(repo_root)
    path = os.path.join(cognirepo_dir, "docs", f"{slug}-insights.md")
    _atomic_write(path, md_str)
    return path


def _previous_generated_at(path: str) -> "str | None":
    """Read a prior report's generated_at so regeneration preserves it while
    updated_at always advances. Returns None if no prior report / unparseable.
    """
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(4096)
    except OSError:
        return None
    m = _GENERATED_AT_RE.search(head)
    return m.group(1) if m else None


def generate(model: dict, repo_root: str, now: str) -> dict:
    """Render + write the HTML report and its markdown twin, idempotently:
    same path every call, generated_at preserved from the prior file (if any),
    updated_at always set to `now`.

    `now` is caller-supplied (ISO timestamp) rather than computed here, so
    render() stays a pure function of its arguments and callers control the
    clock (tests, and any future scheduler).

    Returns {path, md_path, sections, generated_at, updated_at}.
    """
    repo_name = os.path.basename(os.path.abspath(repo_root).rstrip(os.sep))
    slug = _slugify(repo_name)
    target_path = os.path.join(repo_root, ".claude", "insights", f"{slug}-insights.html")

    generated_at = _previous_generated_at(target_path) or now
    updated_at = now

    html_str = render(model, generated_at=generated_at, updated_at=updated_at)
    md_str = _render_markdown(model, generated_at=generated_at, updated_at=updated_at)

    path = write(html_str, repo_root)
    md_path = _write_markdown_twin(md_str, repo_root)

    sections = [sid for sid, _, _ in _SECTIONS]
    return {
        "path": path,
        "md_path": md_path,
        "sections": sections,
        "generated_at": generated_at,
        "updated_at": updated_at,
    }
