# CogniRepo Release Checklist

Follow this checklist for every stable release. Complete each step in order.

---

## 1. Pre-release validation

- [ ] All tests pass: `pytest tests/ -q --cov=. --cov-fail-under=50`
- [ ] `cognirepo doctor` exits 0 on a clean install
- [ ] `bash scripts/smoke_test.sh` passes on the release branch
- [ ] No v0.x tier names in non-CHANGELOG docs: `grep -r "FAST\|BALANCED\|DEEP" --include="*.md" . | grep -v CHANGELOG`
- [ ] CHANGELOG.md has an entry for the new version with a date

## 2. Version bump

- [ ] Update `version` in `pyproject.toml`
- [ ] Update `VERSION` in `cli/repl/shell.py`
- [ ] Confirm `pyproject.toml` and git tag will match (e.g. `1.0.0`)

## 3. CHANGELOG

- [ ] Add a `## [x.y.z] — YYYY-MM-DD` section
- [ ] Fill in `### Added`, `### Changed`, `### Fixed`, `### Breaking` subsections
- [ ] Close the `[Unreleased]` link at the bottom

## 4. RC dry-run on TestPyPI

```bash
# Tag an RC and push — publish.yml uploads to TestPyPI automatically
git tag -a v1.0.0-rc1 -m "Release candidate 1" --no-sign
git push origin v1.0.0-rc1
```

- [ ] `publish.yml` "Publish to TestPyPI" job turns green
- [ ] Install from TestPyPI in a fresh venv and run smoke test:

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple cognirepo[cli]
cognirepo --help
cognirepo doctor
echo "how do I install cognirepo" | cognirepo   # should answer from docs index
```

- [ ] No secrets visible in CI logs (`grep -i "api.key\|password\|secret" ci.log` → empty)

## 5. OIDC trusted publisher setup (one-time, per project)

Required before the first PyPI publish:

1. Go to https://pypi.org/manage/project/cognirepo/settings/publishing/
2. Add a trusted publisher:
   - Owner: `ashlesh-t`
   - Repository: `cognirepo`
   - Workflow filename: `publish.yml`
   - Environment name: `pypi`
3. Do the same for TestPyPI at https://test.pypi.org/manage/project/cognirepo/settings/publishing/
   - Environment name: `testpypi`

No `PYPI_API_TOKEN` secret is needed after this is set up.

## 6. Stable release

- [ ] Delete RC tags: `git tag -d v1.0.0-rc1 && git push origin :v1.0.0-rc1`
- [ ] Cut the stable tag:

```bash
git tag -a v1.0.0 -m "CogniRepo v1.0.0" --no-sign
git push origin v1.0.0
```

- [ ] Create a GitHub Release from the tag (paste CHANGELOG section as body)
- [ ] `publish.yml` "Publish to PyPI" job turns green
- [ ] Verify on PyPI: `pip install cognirepo==1.0.0`

## 7. Post-release

- [ ] Announce on Discord: discord.com/channels/1488386981917360289/1488387271190380636
- [ ] Merge `development` → `main`
- [ ] Open a new `[Unreleased]` section in CHANGELOG.md
