# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
orchestrator/model_adapters/cli_adapter.py — an installed agent CLI as a headless completion backend (#87/#88).

Runs ``claude -p`` / ``codex exec`` / ``gemini -p`` as a plain text-in/text-out model: no tools, no MCP, no hooks,
no session files. It is a *completion engine*, not an agent: ``tool_manifest`` is ignored and nothing is streamed.

Isolation (why it is built this way)
------------------------------------
A headless agent loads its own instructions, hooks and MCP servers, and CogniRepo registers itself in the user-level
config of several agents. Left alone, CogniRepo would call an agent that calls CogniRepo. Four independent layers:

1. a neutral, empty working directory (no ``CLAUDE.md`` / ``AGENTS.md`` / ``GEMINI.md`` / project MCP config);
2. per-CLI flags that turn off tools, MCP, user hooks and session persistence (see ``_RECIPES``);
3. ``COGNIREPO_HEADLESS=1`` in the child env, which makes every CogniRepo entry point a no-op (core.config.headless);
4. this adapter refuses to run when it is itself running under ``COGNIREPO_HEADLESS``.

``claude --bare`` is deliberately NOT used: it never reads OAuth/keychain credentials, which would defeat the point
of using the user's own login. Nor is any ``--dangerously-*`` / ``--yolo`` / approval-bypass flag, ever.

The child env is an allowlist with every provider API-key variable removed, so "CLI" means the CLI's own login
(a leftover ``ANTHROPIC_API_KEY`` would otherwise make ``claude`` bill the API key instead).

Errors are mapped onto :class:`ModelCallError` so the router's fallback chain works unchanged. Message matching is
best-effort; an unrecognised failure is never retried here (the router falls through to the next backend).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess  # nosec B404
import tempfile
from dataclasses import dataclass
from typing import Callable, Generator, Union

from intelligence.orchestrator.model_adapters.anthropic_adapter import ModelResponse
from intelligence.orchestrator.model_adapters.errors import ModelCallError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 120.0
_MAX_OUTPUT_CHARS = 1_000_000
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")  # first char alnum: never parsed as a flag
_AUTH_RE = re.compile(
    r"(not logged in|please (log ?in|run /login)|unauthori[sz]ed|invalid api key|authentication (page|required|failed)"
    r"|sign in|login required|opening authentication|\b401\b)", re.I)
_RATE_RE = re.compile(r"(rate.?limit|usage limit|quota|too many requests|\b429\b)", re.I)

#: Environment variables the child may inherit. Everything else, notably every provider API key, is dropped.
_ENV_ALLOW = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "LANG", "LANGUAGE", "TZ", "TMPDIR", "NO_COLOR",
    "CODEX_HOME", "CLAUDE_CONFIG_DIR", "GEMINI_CLI_HOME",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
})
_ENV_ALLOW_PREFIXES = ("LC_", "XDG_")


@dataclass(frozen=True)
class _Recipe:
    """How to run one CLI headlessly and read its answer."""

    binary: str
    base_argv: tuple[str, ...]
    model_flag: str | None
    #: Appended last (e.g. codex's ``-`` meaning "read the prompt from stdin").
    tail_argv: tuple[str, ...]
    parse: Callable[[str], tuple[str, dict, str | None]]   # stdout -> (text, usage, model)


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _parse_claude(stdout: str) -> tuple[str, dict, str | None]:
    obj = json.loads(stdout)
    if isinstance(obj, list):  # tolerate an event array: take the result event
        obj = next((e for e in reversed(obj) if isinstance(e, dict) and e.get("type") == "result"), {})
    if not isinstance(obj, dict) or obj.get("is_error") or not isinstance(obj.get("result"), str):
        raise ValueError("no result in claude output")
    u = obj.get("usage") or {}
    inp = int(u.get("input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0))
    usage = {"input_tokens": inp, "output_tokens": int(u.get("output_tokens", 0)), "estimated": False}
    model = next(iter(obj.get("modelUsage") or {}), None)
    return obj["result"], usage, model


def _parse_codex(stdout: str) -> tuple[str, dict, str | None]:
    text, usage = None, {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        item = ev.get("item") or {}
        if ev.get("type") == "item.completed" and item.get("type") == "agent_message":
            text = item.get("text")
        elif ev.get("type") == "turn.completed":
            u = ev.get("usage") or {}
            usage = {"input_tokens": int(u.get("input_tokens", 0)), "output_tokens": int(u.get("output_tokens", 0)),
                     "estimated": False}
    if not isinstance(text, str):
        raise ValueError("no agent_message in codex output")
    return text, usage, None


def _parse_gemini(stdout: str) -> tuple[str, dict, str | None]:
    obj = json.loads(stdout)
    if not isinstance(obj, dict) or not isinstance(obj.get("response"), str):
        raise ValueError("no response in gemini output")
    return obj["response"], {}, None


#: Flags come from each CLI's own ``--help``. claude and codex were exercised with a real one-word call; gemini was
#: NOT (its login needed a browser on the development machine), so its recipe is unverified end to end.
_RECIPES: dict[str, _Recipe] = {
    "claude": _Recipe(
        binary="claude",
        base_argv=("-p", "--output-format", "json", "--tools", "", "--strict-mcp-config",
                   "--disable-slash-commands", "--no-session-persistence", "--setting-sources", ""),
        model_flag="--model", tail_argv=(), parse=_parse_claude),
    "codex": _Recipe(
        binary="codex",
        base_argv=("exec", "--ephemeral", "--ignore-user-config", "--ignore-rules", "-s", "read-only",
                   "--skip-git-repo-check", "--json"),
        model_flag="-m", tail_argv=("-",), parse=_parse_codex),
    "gemini": _Recipe(
        binary="gemini",
        base_argv=("-p", "Follow the instructions given on stdin.", "--approval-mode", "plan", "-o", "json",
                   "--allowed-mcp-server-names", "cognirepo-headless-none"),
        model_flag="-m", tail_argv=(), parse=_parse_gemini),
}

#: Flags that must never appear in an argv built here (asserted by tests).
FORBIDDEN_FLAGS = ("--bare", "--yolo", "-y", "--dangerously-skip-permissions",
                   "--dangerously-bypass-approvals-and-sandbox", "--dangerously-bypass-hook-trust")


def supported_agents() -> tuple[str, ...]:
    return tuple(_RECIPES)


def provider_name(agent: str) -> str:
    return f"{agent}-cli"


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k in _ENV_ALLOW or k.startswith(_ENV_ALLOW_PREFIXES)}
    env["COGNIREPO_HEADLESS"] = "1"
    return env


def _sandbox_dir() -> str:
    """Stable empty directory used as the child's cwd (stable so an agent's per-directory state does not pile up)."""
    from core.config.paths import get_global_dir  # pylint: disable=import-outside-toplevel
    path = os.path.join(get_global_dir(), "cli-sandbox")
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        return path
    except OSError:
        return tempfile.mkdtemp(prefix="cognirepo-cli-")


def _configured_timeout() -> float:
    try:
        from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
        with open(get_path("config.json"), encoding="utf-8") as fh:
            value = float(json.load(fh).get("cli_timeout_s", DEFAULT_TIMEOUT_S))
        return value if 1.0 <= value <= 1800.0 else DEFAULT_TIMEOUT_S
    except Exception:  # pylint: disable=broad-except
        return DEFAULT_TIMEOUT_S


def build_argv(agent: str, binary_path: str, model: str | None) -> list[str]:
    """The exact argv for ``agent`` (public so tests and ``agents probe`` share one definition)."""
    recipe = _RECIPES[agent]
    argv = [binary_path, *recipe.base_argv]
    if model and recipe.model_flag:
        argv += [recipe.model_flag, model]
    return argv + list(recipe.tail_argv)


def build_prompt(query: str, system_prompt: str, messages_history: list[dict] | None) -> str:
    """One text prompt: context, earlier turns, then the question. Sent over stdin, never argv."""
    parts: list[str] = []
    if system_prompt:
        parts.append(f"<context>\n{system_prompt}\n</context>")
    for msg in messages_history or []:
        role, content = msg.get("role", "user"), msg.get("content", "")
        if isinstance(content, str) and content:
            parts.append(f"{role}: {content}")
    parts.append(query)
    return "\n\n".join(parts)


def _run(argv: list[str], prompt: str, timeout: float) -> tuple[int, str, str]:
    """Run to completion in its own process group; kill the whole group on timeout. Raises subprocess.TimeoutExpired."""
    proc = subprocess.Popen(  # nosec B603  # pylint: disable=consider-using-with
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=_sandbox_dir(), env=_child_env(), start_new_session=True,
    )
    try:
        out, err = proc.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            proc.kill()
        proc.communicate()
        raise
    return proc.returncode, out[:_MAX_OUTPUT_CHARS], err[:_MAX_OUTPUT_CHARS]


def _classify_failure(provider: str, code: int, out: str, err: str) -> ModelCallError:
    blob = f"{err}\n{out}"
    tail = " ".join(blob.split())[-300:] or f"exit code {code}"
    if _AUTH_RE.search(blob):
        return ModelCallError(provider, 401, f"not authenticated: {tail}")
    if _RATE_RE.search(blob):
        return ModelCallError(provider, 429, tail)
    return ModelCallError(provider, 500, f"exited with code {code}: {tail}")


def _stream_single(response: ModelResponse) -> Generator[str, None, dict]:
    yield response.text
    return {"input_tokens": response.usage.get("input_tokens", 0), "output_tokens": response.usage.get("output_tokens", 0)}


def call(
    query: str,
    system_prompt: str = "",
    tool_manifest: list[dict] | None = None,  # pylint: disable=unused-argument  # completion only: tools are off
    agent: str = "claude",
    model_id: str = "",
    max_tokens: int = 0,  # pylint: disable=unused-argument  # no CLI exposes an output cap
    verbose: bool = False,  # pylint: disable=unused-argument
    stream: bool = False,
    messages_history: list[dict] | None = None,
    timeout: float | None = None,
) -> Union[ModelResponse, Generator[str, None, dict]]:
    """
    Answer ``query`` with the headless ``agent`` CLI.

    ``model_id`` is an alias (claude) or a pinned id; empty means "the CLI's own default" and omits the flag.
    With ``stream=True`` the whole answer is yielded as one chunk and the generator returns the usage dict.
    """
    provider = provider_name(agent)
    if agent not in _RECIPES:
        raise ModelCallError(provider, 400, f"unsupported agent CLI: {agent}")
    from core.config.headless import is_headless  # pylint: disable=import-outside-toplevel
    if is_headless():
        raise ModelCallError(provider, 400, "refusing a nested headless agent call (COGNIREPO_HEADLESS is set)")
    if model_id and not _MODEL_RE.match(model_id):
        raise ModelCallError(provider, 400, "invalid model id")
    path = shutil.which(_RECIPES[agent].binary)
    if not path:
        raise ModelCallError(provider, 404, f"{_RECIPES[agent].binary} not found on PATH")

    prompt = build_prompt(query, system_prompt, messages_history)
    try:
        code, out, err = _run(build_argv(agent, path, model_id or None), prompt,
                              timeout if timeout is not None else _configured_timeout())
    except subprocess.TimeoutExpired as exc:
        raise ModelCallError(provider, None, f"timed out after {exc.timeout:g}s") from exc
    except OSError as exc:
        raise ModelCallError(provider, None, f"could not start {agent}: {exc}") from exc

    if code != 0:
        raise _classify_failure(provider, code, out, err)
    try:
        text, usage, model = _RECIPES[agent].parse(out)
    except (ValueError, TypeError, KeyError):
        # Output shape changed or JSON mode was ignored. A failure that exited 0 may still be an auth prompt.
        if _AUTH_RE.search(f"{err}\n{out}"):
            raise _classify_failure(provider, code, out, err) from None
        text, usage, model = out.strip(), {}, None
        if not text:
            raise ModelCallError(provider, 500, "empty answer") from None
    if not usage:
        usage = {"input_tokens": _tokens(prompt), "output_tokens": _tokens(text), "estimated": True}
    response = ModelResponse(text=text, model=model or model_id or provider, provider=provider, usage=usage)
    return _stream_single(response) if stream else response
