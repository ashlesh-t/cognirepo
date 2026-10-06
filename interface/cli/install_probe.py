# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Probe the interpreter behind the ``cognirepo`` on PATH (COGNIREPO-124).

Hooks, MCP clients and cron run the ``cognirepo`` found on PATH — typically a pipx venv — which
can differ from the interpreter that runs ``cognirepo doctor`` in a dev checkout. Two things go
wrong there and used to be invisible:

* ``storage.encrypt: true`` but that venv lacks ``keyring`` / ``cryptography`` (or its keyring has
  no usable backend): every save raises ImportError / NoKeyringError and nothing reports it.
* The PATH ``cognirepo`` is a *snapshot* that predates the working tree, so it doesn't know newer
  subcommands.

Everything here is side-effect free: the probe runs in a subprocess, only *reads* from keyring
(``get_password`` on a throw-away service name) and never imports the cognirepo package itself.
``diagnose`` is a pure function so the policy can be unit-tested without spawning anything.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

#: throw-away service name: the probe never touches the real cognirepo keys
PROBE_SERVICE = "cognirepo-doctor-probe"

_PROBE_CODE = r'''
import importlib.util, json
out = {}
for mod in ("cryptography", "keyring"):
    try:
        __import__(mod)
        out[mod] = True
    except Exception as exc:  # ImportError, or a broken install
        out[mod] = False
        out[mod + "_error"] = f"{type(exc).__name__}: {exc}"
if out.get("keyring"):
    import keyring
    try:
        backend = keyring.get_keyring()
        out["backend"] = f"{type(backend).__module__}.{type(backend).__name__}"
    except Exception as exc:
        out["backend"] = None
        out["backend_error"] = f"{type(exc).__name__}: {exc}"
    try:
        keyring.get_password(%(service)r, "probe")   # read-only; absent key -> None
        out["get_password"] = "ok"
    except Exception as exc:
        out["get_password"] = f"{type(exc).__name__}: {exc}"
try:
    from importlib.metadata import version
    out["version"] = version("cognirepo")
except Exception:
    out["version"] = None
try:
    spec = importlib.util.find_spec("interface.cli.main")   # locate, don't import
    path = spec.origin if spec else None
    out["main_path"] = path
    if path:
        with open(path, "rb") as fh:
            import hashlib
            out["main_sha"] = hashlib.sha256(fh.read()).hexdigest()
except Exception as exc:
    out["main_error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(out))
''' % {"service": PROBE_SERVICE}


@dataclass
class Finding:
    """One doctor line: ``level`` is ``"ok"``, ``"warn"`` or ``"fail"``."""
    level: str
    message: str
    hint: str = ""


def resolve_cli_interpreter(cli: "str | None" = None) -> "str | None":
    """Interpreter the PATH ``cognirepo`` script runs under, read from its shebang.

    Returns None when there is no ``cognirepo`` on PATH, it isn't a script (e.g. a Windows .exe
    launcher) or the shebang interpreter is missing. ``#!/usr/bin/env python3`` resolves to the
    first ``python3`` on PATH, which is what would actually run.
    """
    exe = cli or shutil.which("cognirepo")
    if not exe:
        return None
    try:
        with open(exe, "rb") as fh:
            first = fh.readline(512)
    except OSError:
        return None
    if not first.startswith(b"#!"):
        return None
    parts = first[2:].decode("utf-8", "replace").strip().split()
    if not parts:
        return None
    interp = parts[0]
    if os.path.basename(interp) == "env" and len(parts) > 1:
        interp = shutil.which(parts[-1]) or ""
    return interp if interp and os.path.exists(interp) else None


def probe_interpreter(python: str, timeout: float = 30.0) -> dict:
    """Run the read-only probe under ``python``. Returns the probe dict, or ``{"error": ...}``."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    try:
        with tempfile.TemporaryDirectory() as neutral:      # not the repo: resolve like a hook would
            res = subprocess.run(
                [python, "-c", _PROBE_CODE], cwd=neutral, env=env,
                capture_output=True, text=True, timeout=timeout, check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    if res.returncode != 0:
        return {"error": (res.stderr or res.stdout).strip()[-300:] or f"exit {res.returncode}"}
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": f"unparseable probe output: {res.stdout.strip()[-200:]!r}"}


def same_interpreter(a: str, b: str) -> bool:
    """True if two interpreter paths belong to the same environment.

    Deliberately NOT ``realpath(a) == realpath(b)``: every venv's ``bin/python`` is a symlink to
    the system interpreter, so two different venvs (a pipx venv and a dev venv) would compare
    equal and the PATH install would never be checked. Compare the environment root instead
    (``<root>/bin/python``) — different venvs differ, ``python`` vs ``python3`` in one venv don't.
    """
    def root(p: str) -> str:
        return os.path.dirname(os.path.dirname(os.path.abspath(p)))
    return os.path.abspath(a) == os.path.abspath(b) or root(a) == root(b)


def is_pipx_venv(python: str) -> bool:
    """True if ``python`` lives in a pipx venv. Checks the path as given first: a venv's python
    is usually a symlink to the system one, so ``realpath`` alone would lose the marker."""
    marker = f"{os.sep}pipx{os.sep}venvs{os.sep}"
    return marker in python or marker in os.path.realpath(python)


def install_fix(python: str) -> str:
    """Exact command that adds the encryption packages to *that* interpreter."""
    if is_pipx_venv(python):
        return "pipx inject cognirepo keyring cryptography"
    return f"{python} -m pip install keyring cryptography"


def reinstall_fix(python: str, source_root: "str | None") -> str:
    """Exact command that refreshes the PATH ``cognirepo`` from this working tree."""
    if is_pipx_venv(python):
        return f"pipx install --force {source_root}" if source_root else "pipx reinstall cognirepo"
    return f"{python} -m pip install -e {source_root}" if source_root else f"{python} -m pip install --force-reinstall cognirepo"


def is_unusable_backend(backend: "str | None") -> bool:
    """keyring's fail/null backends mean 'no keyring here': every key lookup will error or miss."""
    return bool(backend) and (".backends.fail." in backend or ".backends.null." in backend)


def diagnose(
    probe: dict, *, label: str, python: str, encrypt: bool,
    check_modules: bool = True, ours_path: "str | None" = None, ours_sha: "str | None" = None,
    ours_version: "str | None" = None, source_root: "str | None" = None,
    check_stale: bool = False,
) -> "list[Finding]":
    """Turn one interpreter's probe result into doctor findings. Pure — no I/O.

    ``label``         how the interpreter is described ("`cognirepo` on PATH").
    ``check_modules`` False for the interpreter doctor itself runs in — an existing check
                      already reports missing packages there; only the backend is checked.
    ``check_stale``   compare the package this interpreter would run with the working tree.
    """
    if "error" in probe:
        return [Finding("warn", f"{label} ({python}) could not be probed: {probe['error']}")]

    findings: "list[Finding]" = []
    if encrypt:
        missing = [m for m in ("cryptography", "keyring") if not probe.get(m)]
        if missing and check_modules:
            findings.append(Finding(
                "fail",
                f"Encryption is on but {', '.join(missing)} not importable in {label} ({python}) — "
                "every save of an encrypted store will fail",
                f"Run: {install_fix(python)}",
            ))
        elif not missing:
            backend = probe.get("backend")
            gp = probe.get("get_password", "ok")
            if is_unusable_backend(backend):
                findings.append(Finding(
                    "warn",
                    f"Encryption is on but the keyring in {label} has no usable backend ({backend}) — "
                    "the encryption key can't be read, so encrypted stores stay locked there",
                    "Run in a desktop session / install a keyring backend (e.g. gnome-keyring, "
                    "keyrings.alt), or set PYTHON_KEYRING_BACKEND",
                ))
            elif gp != "ok":
                findings.append(Finding(
                    "warn",
                    f"Encryption is on but a keyring lookup fails in {label}: {gp}",
                    "Check the OS keychain / PYTHON_KEYRING_BACKEND for that interpreter",
                ))
            else:
                findings.append(Finding("ok", f"Encryption — keyring usable in {label} ({backend})"))

    if check_stale and ours_path and probe.get("main_path"):
        same_file = os.path.realpath(probe["main_path"]) == os.path.realpath(ours_path)
        if not same_file and probe.get("main_sha") != ours_sha:
            theirs = f" (v{probe['version']})" if probe.get("version") else ""
            findings.append(Finding(
                "warn",
                f"{label} runs a different copy of cognirepo{theirs} than this working tree"
                f"{' (v' + ours_version + ')' if ours_version else ''} — it may not know newer "
                "subcommands or fixes",
                f"Run: {reinstall_fix(python, source_root)}",
            ))
    return findings


def file_sha256(path: str) -> "str | None":
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None
