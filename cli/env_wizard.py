# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
EnvWizard — interactive .env setup wizard for first-run experience.

Flow
----
1. detect_missing()    — which keys are absent from .env + os.environ?
2. prompt_mode()       — manual / guided / skip
3. manual_flow()       — open $EDITOR, wait, loop
   guided_flow()       — hidden-input prompts per key, write to .env
4. verify_keys()       — minimal API call per provider
5. repair_loop()       — re-prompt for any key that failed verification
6. summary()           — print final status

Security
--------
- Keys are read via getpass (never echoed)
- Keys are masked in all print/log output  (sk-ant-***...***)
- .env file is NOT committed — wizard warns if .env is not in .gitignore
"""
from __future__ import annotations

import getpass
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

_ALL_KEYS = ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "GROK_API_KEY"]


def _mask(value: str) -> str:
    """Return a masked version of an API key for display."""
    if len(value) <= 8:
        return "****"
    return value[:4] + "***...***" + value[-4:]


def _dotenv_path(project_dir: str = ".") -> Path:
    return Path(project_dir) / ".env"


def _read_dotenv(project_dir: str = ".") -> dict[str, str]:
    """Parse .env file into a dict (key=value, no shell expansion)."""
    env: dict[str, str] = {}
    path = _dotenv_path(project_dir)
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def _set_dotenv_key(key: str, value: str, project_dir: str = ".") -> None:
    """Write or update a key in .env (preserving other entries)."""
    try:
        from dotenv import set_key  # pylint: disable=import-outside-toplevel
        dotenv_path = str(_dotenv_path(project_dir))
        set_key(dotenv_path, key, value)
    except ImportError:
        # Fallback: append to .env manually
        path = _dotenv_path(project_dir)
        existing = _read_dotenv(project_dir)
        existing[key] = value
        with open(path, "w", encoding="utf-8") as f:
            for k, v in existing.items():
                f.write(f'{k}="{v}"\n')


def _gitignore_has_dotenv(project_dir: str = ".") -> bool:
    gi = Path(project_dir) / ".gitignore"
    if not gi.exists():
        return False
    return any(".env" in line for line in gi.read_text().splitlines())


class EnvWizard:
    """Interactive .env setup wizard."""

    def __init__(self, project_dir: str = ".", non_interactive: bool = False) -> None:
        self._dir = project_dir
        self._non_interactive = non_interactive

    def detect_missing(self, keys: list[str] | None = None) -> list[str]:
        """Return keys that are absent from both .env and os.environ."""
        keys = keys or _ALL_KEYS
        dotenv = _read_dotenv(self._dir)
        missing = []
        for key in keys:
            if not os.environ.get(key) and not dotenv.get(key):
                missing.append(key)
        return missing

    def detect_all_status(self, keys: list[str] | None = None) -> dict[str, bool]:
        """Return {key: is_set} for display."""
        keys = keys or _ALL_KEYS
        dotenv = _read_dotenv(self._dir)
        return {k: bool(os.environ.get(k) or dotenv.get(k)) for k in keys}

    def prompt_mode(self) -> Literal["manual", "guided", "skip"]:
        """Ask the user how they want to set missing keys."""
        if self._non_interactive or not sys.stdin.isatty():
            return "skip"
        print("\nHow would you like to set the missing keys?")
        print("  [1] Update .env manually (I'll open the file)")
        print("  [2] Enter keys here now (guided prompts)")
        print("  [3] Skip for now (some features will be unavailable)")
        while True:
            choice = input("Choice [1/2/3]: ").strip()
            if choice == "1":
                return "manual"
            if choice == "2":
                return "guided"
            if choice == "3":
                return "skip"

    def manual_flow(self, keys: list[str]) -> None:
        """Open $EDITOR, wait for user, loop until keys are set or user skips."""
        dotenv_path = str(_dotenv_path(self._dir))
        editor = os.environ.get("EDITOR", "")
        if editor:
            try:
                subprocess.run([editor, dotenv_path], check=False)  # nosec B603
            except Exception:  # pylint: disable=broad-except
                pass
        else:
            print(f"\nPlease edit: {dotenv_path}")

        while True:
            input("Press Enter when done (or Ctrl+C to skip) ▶ ")
            still_missing = self.detect_missing(keys)
            if not still_missing:
                break
            print(f"Still missing: {', '.join(still_missing)}")
            again = input("Edit again? [Y/n]: ").strip().lower()
            if again in ("n", "no"):
                break

    def guided_flow(self, keys: list[str]) -> None:
        """Hidden-input prompt per key, write to .env."""
        for key in keys:
            while True:
                try:
                    value = getpass.getpass(f"Enter {key}: ")
                except (EOFError, KeyboardInterrupt):
                    print(f"\nSkipping {key}.")
                    break
                if not value.strip():
                    print("  Value cannot be empty. Try again.")
                    continue
                _set_dotenv_key(key, value.strip(), self._dir)
                print(f"  ✓ {key} saved ({_mask(value)})")
                break

    def verify_keys(
        self,
        keys: list[str] | None = None,
        skip_verify: bool = False,
    ) -> dict[str, dict]:
        """
        Verify each key by making the minimal API call.
        Returns {key: ProbeResult}.
        """
        from cli.key_probes import PROVIDER_PROBES  # pylint: disable=import-outside-toplevel

        if skip_verify:
            return {}

        keys = keys or _ALL_KEYS
        dotenv = _read_dotenv(self._dir)
        results: dict[str, dict] = {}

        for key in keys:
            value = os.environ.get(key) or dotenv.get(key)
            if not value:
                continue
            if key not in PROVIDER_PROBES:
                continue
            provider_name, probe_fn = PROVIDER_PROBES[key]
            print(f"  Verifying {key}...", end=" ", flush=True)
            result = probe_fn(value)  # type: ignore[call-arg]
            results[key] = result
            if result["ok"]:
                print(f"✓ {provider_name} verified ({result['latency_ms']:.0f} ms)")
            else:
                print(f"✗ {provider_name} FAILED: {result['error']}")

        return results

    def repair_loop(
        self,
        failed_keys: list[str],
        skip_verify: bool = False,
    ) -> dict[str, dict]:
        """Re-prompt for each failed key and re-verify."""
        if self._non_interactive or not sys.stdin.isatty():
            return {}

        from cli.key_probes import PROVIDER_PROBES  # pylint: disable=import-outside-toplevel

        results: dict[str, dict] = {}
        for key in failed_keys:
            print(f"\n{key} failed verification.")
            print("  [1] Re-enter key now")
            print("  [2] Update .env manually and press Enter")
            print("  [3] Skip this key")
            choice = input("Choice [1/2/3]: ").strip()

            if choice == "3":
                results[key] = {"ok": False, "latency_ms": 0, "error": "skipped by user"}
                continue
            if choice == "2":
                input("Update .env and press Enter ▶ ")
            elif choice == "1":
                try:
                    value = getpass.getpass(f"Enter {key}: ")
                    _set_dotenv_key(key, value.strip(), self._dir)
                except (EOFError, KeyboardInterrupt):
                    continue

            if key in PROVIDER_PROBES and not skip_verify:
                dotenv = _read_dotenv(self._dir)
                value = os.environ.get(key) or dotenv.get(key, "")
                _, probe_fn = PROVIDER_PROBES[key]
                result = probe_fn(value)  # type: ignore[call-arg]
                results[key] = result
                status = "✓ verified" if result["ok"] else f"✗ FAILED: {result['error']}"
                print(f"  {key}: {status}")

        return results

    def print_summary(
        self,
        verify_results: dict[str, dict],
        skipped_keys: list[str],
    ) -> None:
        """Print final status to stdout."""
        print("\n✓ Setup complete.")
        dotenv = _read_dotenv(self._dir)
        for key in _ALL_KEYS:
            value = os.environ.get(key) or dotenv.get(key)
            if not value:
                print(f"  ✗  {key} not set (features requiring this key will be unavailable)")
                continue
            if key in verify_results:
                r = verify_results[key]
                if r["ok"]:
                    print(f"  ✓  {key} verified")
                elif r.get("error") == "skipped by user":
                    print(f"  ✗  {key} skipped")
                else:
                    print(f"  ✗  {key} verification failed: {r['error']}")
            elif key in skipped_keys:
                print(f"  ?  {key} set but not verified (--skip-verify)")
            else:
                print(f"  ✓  {key} set")

    def _check_gitignore(self) -> None:
        if not _gitignore_has_dotenv(self._dir):
            print(
                "\n⚠  .env is NOT in .gitignore — your API keys could be committed!"
            )
            if sys.stdin.isatty():
                add = input("  Add .env to .gitignore now? [Y/n]: ").strip().lower()
                if add not in ("n", "no"):
                    gi = Path(self._dir) / ".gitignore"
                    with open(gi, "a", encoding="utf-8") as f:
                        f.write("\n.env\n")
                    print("  ✓ Added .env to .gitignore")

    def run(
        self,
        skip_verify: bool = False,
        force: bool = False,
    ) -> None:
        """
        Full wizard flow.

        Parameters
        ----------
        skip_verify : don't make API calls (useful in CI)
        force       : run wizard even if all keys are already set
        """
        all_status = self.detect_all_status()
        missing = [k for k, v in all_status.items() if not v]

        if not missing and not force:
            print("✓ All API keys already configured.")
            return

        # Display current status
        print("\nSome environment variables are not set:")
        for key, is_set in all_status.items():
            status = "✓" if is_set else "✗"
            print(f"  {status}  {key}")

        if missing:
            mode = self.prompt_mode()
            if mode == "manual":
                self.manual_flow(missing)
            elif mode == "guided":
                self.guided_flow(missing)
            # mode == "skip" — fall through

        # Check .gitignore
        self._check_gitignore()

        verify_results: dict[str, dict] = {}
        skipped_verify: list[str] = []

        # Offer verification
        if not self._non_interactive and sys.stdin.isatty() and not skip_verify:
            do_verify = input("\nVerify your API keys now? [Y/n]: ").strip().lower()
            if do_verify not in ("n", "no"):
                verify_results = self.verify_keys(skip_verify=False)
            else:
                skipped_verify = list(all_status.keys())
        elif skip_verify:
            skipped_verify = list(all_status.keys())
        else:
            verify_results = self.verify_keys(skip_verify=False)

        # Repair failed keys
        failed = [k for k, r in verify_results.items() if not r["ok"]]
        if failed and sys.stdin.isatty():
            repair_results = self.repair_loop(failed, skip_verify=skip_verify)
            verify_results.update(repair_results)

        self.print_summary(verify_results, skipped_verify)
        print("\n→ CogniRepo is ready. Run: cognirepo index-repo .\n")
