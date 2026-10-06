# pylint: disable=missing-docstring, import-outside-toplevel, too-few-public-methods, protected-access
# pylint: disable=redefined-outer-name, unused-argument, duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_doctor_path_install.py — COGNIREPO-124.

`cognirepo doctor` must inspect the interpreter behind the `cognirepo` on PATH (hooks and MCP
clients run that one), not just the one running doctor: missing keyring/cryptography, a keyring
with no usable backend, and a stale snapshot of an older working tree.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from interface.cli import install_probe as ip


def _make_executable(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _fake_python(root: Path, *, block=(), env=None, pipx=False) -> str:
    """A python wrapper that behaves like an interpreter with some packages missing.

    ``block`` modules are made un-importable (like a pipx venv without keyring); ``env`` extra
    environment variables are set (e.g. a fail keyring backend). ``pipx`` puts it under a
    ``pipx/venvs/cognirepo/bin`` path so the pipx-specific hints apply.
    """
    where = root / ("pipx/venvs/cognirepo/bin" if pipx else "venv/bin") / "python"
    blocks = "\n".join(f"sys.modules[{m!r}] = None" for m in block)
    exports = "".join(f'export {k}="{v}"\n' for k, v in (env or {}).items())
    script = (
        "#!/bin/sh\n" + exports +
        f'exec "{sys.executable}" -c "import sys\n{blocks}\nexec(sys.argv[1])" "$2"\n'
    )
    return str(_make_executable(where, script))


def _fake_cli(root: Path, interpreter: str) -> str:
    """A `cognirepo` script on PATH whose shebang names ``interpreter`` (like pipx)."""
    return str(_make_executable(root / "bin" / "cognirepo", f"#!{interpreter}\nprint('cognirepo')\n"))


@pytest.fixture(autouse=True)
def _use_real_resolver(real_path_install):
    """These tests exercise the real resolver (conftest stubs it for everything else)."""


class TestResolveCliInterpreter:
    def test_reads_the_shebang(self, tmp_path):
        py = _fake_python(tmp_path)
        assert ip.resolve_cli_interpreter(_fake_cli(tmp_path, py)) == py

    def test_env_shebang_resolves_to_the_first_python_on_path(self, tmp_path, monkeypatch):
        py = _fake_python(tmp_path)
        monkeypatch.setenv("PATH", f"{os.path.dirname(py)}{os.pathsep}{os.environ['PATH']}")
        cli = _make_executable(tmp_path / "bin" / "cognirepo", "#!/usr/bin/env python\n")
        assert ip.resolve_cli_interpreter(str(cli)) == py

    def test_not_a_script_or_missing_returns_none(self, tmp_path):
        binary = tmp_path / "cognirepo"
        binary.write_bytes(b"\x7fELF....")
        assert ip.resolve_cli_interpreter(str(binary)) is None
        assert ip.resolve_cli_interpreter(str(tmp_path / "nope")) is None

    def test_dead_interpreter_returns_none(self, tmp_path):
        cli = _fake_cli(tmp_path, str(tmp_path / "gone" / "python"))
        assert ip.resolve_cli_interpreter(cli) is None


class TestSameInterpreter:
    def test_two_venvs_sharing_a_system_python_are_different_environments(self, tmp_path):
        """The real-world case: both venvs' bin/python are symlinks to the same system python."""
        system = _make_executable(tmp_path / "usr" / "bin" / "python3.14", "#!/bin/sh\n")
        a, b = tmp_path / "pipx" / "venvs" / "cognirepo" / "bin", tmp_path / "dev" / "venv" / "bin"
        for d in (a, b):
            d.mkdir(parents=True)
            (d / "python").symlink_to(system)
        assert os.path.realpath(a / "python") == os.path.realpath(b / "python")   # why realpath fails
        assert not ip.same_interpreter(str(a / "python"), str(b / "python"))

    def test_the_same_venv_under_two_names_is_one_environment(self, tmp_path):
        bindir = tmp_path / "venv" / "bin"
        bindir.mkdir(parents=True)
        assert ip.same_interpreter(str(bindir / "python"), str(bindir / "python3"))
        assert ip.same_interpreter(str(bindir / "python"), str(bindir / "python"))


class TestProbe:
    def test_probe_of_a_healthy_interpreter(self):
        pytest.importorskip("keyring")
        probe = ip.probe_interpreter(sys.executable)
        assert "error" not in probe
        assert probe["keyring"] is True and probe["cryptography"] is True
        assert probe["get_password"] in ("ok",) or "Error" in probe["get_password"]
        assert probe["main_path"] and probe["main_sha"]

    def test_probe_of_a_keyring_less_interpreter(self, tmp_path):
        probe = ip.probe_interpreter(_fake_python(tmp_path, block=("keyring", "cryptography")))
        assert probe["keyring"] is False and probe["cryptography"] is False
        assert "backend" not in probe

    def test_probe_error_is_reported_not_raised(self, tmp_path):
        probe = ip.probe_interpreter(str(tmp_path / "does-not-exist"))
        assert "error" in probe

    def test_probe_never_touches_the_real_keys(self):
        """The probe reads a throw-away service name; it must not create or read cognirepo keys."""
        assert ip.PROBE_SERVICE == "cognirepo-doctor-probe"
        assert "cognirepo-doctor-probe" in ip._PROBE_CODE and "set_password" not in ip._PROBE_CODE


class TestDiagnoseEncryption:
    def _probe(self, **kw):
        base = {"cryptography": True, "keyring": True, "backend": "keyring.backends.SecretService.Keyring",
                "get_password": "ok", "version": "1.2.3", "main_path": "/x/main.py", "main_sha": "a"}
        base.update(kw)
        return base

    def test_missing_packages_fail_with_the_exact_pipx_fix(self, tmp_path):
        py = _fake_python(tmp_path, block=("keyring",), pipx=True)
        probe = ip.probe_interpreter(py)
        findings = ip.diagnose(probe, label="`cognirepo` on PATH", python=py, encrypt=True)
        assert [f.level for f in findings] == ["fail"]
        assert "keyring not importable" in findings[0].message
        assert findings[0].hint == "Run: pipx inject cognirepo keyring cryptography"

    def test_missing_packages_outside_pipx_get_a_pip_fix_for_that_interpreter(self, tmp_path):
        py = _fake_python(tmp_path, block=("cryptography",))
        findings = ip.diagnose(ip.probe_interpreter(py), label="L", python=py, encrypt=True)
        assert findings[0].level == "fail"
        assert findings[0].hint == f"Run: {py} -m pip install keyring cryptography"

    def test_modules_check_is_skipped_for_the_doctor_interpreter(self):
        findings = ip.diagnose(self._probe(keyring=False), label="this interpreter",
                               python=sys.executable, encrypt=True, check_modules=False)
        assert findings == []         # an existing check already reports this one

    def test_encryption_off_means_no_encryption_findings(self, tmp_path):
        py = _fake_python(tmp_path, block=("keyring", "cryptography"))
        assert ip.diagnose(ip.probe_interpreter(py), label="L", python=py, encrypt=False) == []

    def test_fail_backend_warns_even_though_the_packages_import(self, tmp_path):
        pytest.importorskip("keyring")
        py = _fake_python(tmp_path, env={"PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring"})
        probe = ip.probe_interpreter(py)
        assert probe["backend"].endswith("backends.fail.Keyring")
        findings = ip.diagnose(probe, label="`cognirepo` on PATH", python=py, encrypt=True)
        assert [f.level for f in findings] == ["warn"]
        assert "no usable backend" in findings[0].message

    def test_null_backend_is_unusable_too(self):
        assert ip.is_unusable_backend("keyring.backends.null.Keyring")
        assert ip.is_unusable_backend("keyring.backends.fail.Keyring")
        assert not ip.is_unusable_backend("keyring.backends.SecretService.Keyring")
        assert not ip.is_unusable_backend(None)

    def test_failing_lookup_warns(self):
        findings = ip.diagnose(self._probe(get_password="KeyringLocked: locked"), label="L",
                               python="/p/python", encrypt=True)
        assert [f.level for f in findings] == ["warn"] and "lookup fails" in findings[0].message

    def test_healthy_keyring_is_ok(self):
        findings = ip.diagnose(self._probe(), label="L", python="/p/python", encrypt=True)
        assert [f.level for f in findings] == ["ok"]

    def test_unprobeable_interpreter_warns(self):
        findings = ip.diagnose({"error": "boom"}, label="L", python="/p/python", encrypt=True)
        assert [f.level for f in findings] == ["warn"] and "boom" in findings[0].message


class TestDiagnoseStaleInstall:
    def _probe(self, **kw):
        base = {"cryptography": True, "keyring": True, "backend": "b", "get_password": "ok",
                "version": "1.0.0", "main_path": "/site-packages/interface/cli/main.py", "main_sha": "OLD"}
        base.update(kw)
        return base

    def _diag(self, probe, **kw):
        args = dict(label="`cognirepo` on PATH", python="/home/u/.local/pipx/venvs/cognirepo/bin/python",
                    encrypt=False, ours_path="/work/cognirepo/interface/cli/main.py", ours_sha="NEW",
                    ours_version="1.1.0", source_root="/work/cognirepo", check_stale=True)
        args.update(kw)
        return ip.diagnose(probe, **args)

    def test_a_different_copy_with_different_content_is_stale(self):
        (f,) = self._diag(self._probe())
        assert f.level == "warn" and "different copy of cognirepo (v1.0.0)" in f.message
        assert "v1.1.0" in f.message
        assert f.hint == "Run: pipx install --force /work/cognirepo"

    def test_non_pipx_stale_install_gets_a_pip_editable_hint(self):
        (f,) = self._diag(self._probe(), python="/venv/bin/python")
        assert f.hint == "Run: /venv/bin/python -m pip install -e /work/cognirepo"

    def test_the_same_file_is_never_stale(self):
        assert self._diag(self._probe(main_path="/work/cognirepo/interface/cli/main.py")) == []

    def test_same_content_in_a_different_place_is_not_stale(self):
        assert self._diag(self._probe(main_sha="NEW")) == []

    def test_staleness_is_only_checked_when_asked(self):
        assert self._diag(self._probe(), check_stale=False) == []

    def test_no_source_tree_falls_back_to_a_generic_reinstall(self):
        (f,) = self._diag(self._probe(), source_root=None)
        assert f.hint == "Run: pipx reinstall cognirepo"


class TestDoctorIntegration:
    def _enable_encryption(self):
        Path(".cognirepo/config.json").write_text(
            json.dumps({"project_id": "p", "storage": {"encrypt": True}}))

    def test_doctor_flags_a_keyring_less_path_install_with_the_exact_fix(
            self, real_path_install, isolated_cognirepo, tmp_path, monkeypatch, capsys):
        from interface.cli.main import _cmd_doctor
        self._enable_encryption()
        py = _fake_python(tmp_path / "fake", block=("keyring", "cryptography"), pipx=True)
        cli = _fake_cli(tmp_path / "fake", py)
        monkeypatch.setenv("PATH", f"{os.path.dirname(cli)}{os.pathsep}{os.environ['PATH']}")
        code = _cmd_doctor(verbose=False)
        out = capsys.readouterr().out
        assert "`cognirepo` on PATH" in out and "not importable" in out
        assert "pipx inject cognirepo keyring cryptography" in out
        assert code >= 1

    def test_doctor_checks_a_path_install_that_shares_a_system_python(
            self, isolated_cognirepo, tmp_path, monkeypatch, capsys):
        """Regression: a pipx venv whose python symlinks to the same system python as the dev venv
        was treated as 'the same interpreter' and never probed."""
        from interface.cli import install_probe
        from interface.cli.main import _cmd_doctor
        self._enable_encryption()
        probed = []
        monkeypatch.setattr(install_probe, "resolve_cli_interpreter",
                            lambda *_a, **_k: str(tmp_path / "pipx" / "venvs" / "cognirepo" / "bin" / "python"))
        monkeypatch.setattr(install_probe, "probe_interpreter",
                            lambda py, **_k: probed.append(py) or {"cryptography": True, "keyring": False,
                                                                   "version": "0"})
        _cmd_doctor(verbose=False)
        assert any("pipx" in p for p in probed), probed
        assert "keyring not importable in `cognirepo` on PATH" in capsys.readouterr().out

    def test_doctor_stays_quiet_when_nothing_is_wrong(
            self, real_path_install, isolated_cognirepo, tmp_path, monkeypatch, capsys):
        """Encryption off and no cognirepo on PATH → no new output, no new failures."""
        from interface.cli.main import _cmd_doctor
        monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
        _cmd_doctor(verbose=False)
        out = capsys.readouterr().out
        assert "on PATH" not in out
