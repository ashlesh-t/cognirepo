# COGNIREPO-600 Discovery — OSS growth / production polish (Phase 5)

Verified against HEAD (`146627d`, v2.0.0) on 2026-07-11.

---

## 1. README / benchmark claims — internal inconsistencies to polish

- README.md:18 — "benchmarked on Flask, FastAPI, Celery, and Ansible (1,800+ files)" (4 repos).
- README.md:78 — "Benchmarked across 6 real open-source repos (FastAPI, Flask, Celery, Ansible,
  Moby/Docker, Kubernetes)".
- README.md:98 — "Indexed 4 real repos, measured with … `cognirepo benchmark --json`".
- docs/METRICS.md:118-152 — automated numbers cover **3** repos (flask, fastapi, celery,
  2026-06-17), with fastapi memory recall@1/@3 at **0% — "empty vector DB; under investigation"**
  and three metrics footnoted "fixed in v1.1.3; re-run benchmark after upgrade" — the published
  table still shows the pre-fix zeros.
  The QA memory records a moby run (97.5% reduction, recall@1 100%, 2026-06-12) that never made
  it into METRICS.md.
  → Actions: re-run `cognirepo benchmark --json` on all target repos at 2.0.0, reconcile the
  4-vs-6-vs-3 counts, resolve/pin the fastapi recall figure, expand beyond the current set.
- Local test fixtures for cheap benchmark expansion exist at
  `/home/ashlesh/my_works/cognirepo_test_repo/` (`advanced`, `dummy`, `easy`, `medium`,
  `private-org`) plus its own `benchmark.py`.

## 2. MCP registry presence — current state

- `README.md:3` — `mcp-name: io.github.ashlesh-t/cognirepo` (registry claim marker present).
- `server.json` — modelcontextprotocol schema 2025-12-11, version 2.0.0, pypi package, uvx
  runtime hint. In sync with `version.yml` (synced by `scripts/sync_version.py`).
- `glama.json` — present but hand-maintained and drifted (32 tools, stale `link_repos`
  description; see 100-Discovery §1b). COGNIREPO-101 (single-source generation) fixes the drift
  mechanically; this epic only verifies listing status after that lands.
- `interface/adapters/openai_tools.json` — 13 of 34 tools; regenerate (also downstream of 101).

## 3. Contribution funnel

- Root `CONTRIBUTING.md` is thin (one header: "Why two files?" at `:8`); the real contributor
  path is `docs/DEVELOPER_GUIDE.md` (dev setup `:7`, add-a-tool `:36`, add-a-language `:100`,
  add-a-CLI-command `:162`, PR checklist `:184`). No good-first-issue labeling guidance exists in
  either file. Concrete good-first-issue seeds discovered by this audit: FEATURES.md §15 test
  inventory refresh, README Future Plans version headers, `interface/cli/docs_index.py` shim
  removal, SECURITY.md Snyk line, Ruby/PHP/C#/Swift grammar mappings (README.md:632, recipe
  already documented in DEVELOPER_GUIDE §100).

## 4. Community / GTM assets

- Discord: official support channel exists (memory `reference_discord.md`:
  discord.com/channels/1488386981917360289/1488387271190380636). Not linked from README (grep
  for "discord" in README.md returns nothing) — lowest-effort growth action available.
- Phase 2's insights HTML is a natural showcase asset ("here's what CogniRepo generates about
  your repo") — cross-reference: README section + screenshot once COGNIREPO-302 ships. Depends on
  EPIC-300 completion; keep as a follow-on story item, not a blocker.

## 5. Version bump posture

Everything here is docs/benchmark/metadata; only the fastapi-recall investigation could touch
code (`interface/tools/benchmark.py` or vector-db seeding). Patch-level bump at most.
