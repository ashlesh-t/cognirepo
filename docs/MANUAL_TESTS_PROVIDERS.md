# Manual test suite — agent CLIs and model discovery (setup/init UX)

Covers the parts of #86/#88/#89 that automated tests cannot: real logins, real keys, real terminals.
Automated coverage lives in `tests/test_provider_status.py`, `tests/test_cli_adapter.py`,
`tests/test_model_discovery.py` and `tests/test_setup_latency.py`.

Run in a scratch repo (`mkdir t && cd t && git init`). Record result, date and OS per row.
Rows marked **spends quota** make one tiny real model call.

| ID | Setup | Steps | Expected |
|----|-------|-------|----------|
| P-1 | No agent CLI on `PATH`, no API keys | `cognirepo setup` | No agent or model prompts; finishes as before; no network traffic (`strace -f -e trace=connect` shows no connection from discovery) |
| P-2 | `codex` installed and logged in | `cognirepo setup`, answer **No** to the codex prompt | Nothing enabled; `cognirepo agents list` shows codex `installed`, not `enabled` |
| P-3 | As P-2 | `cognirepo setup`, answer **Yes** | codex enabled with no extra warning; `agents list` shows `enabled` |
| P-4 | `claude` installed | `cognirepo setup`, answer **Yes** | Terms warning printed and a second confirmation required; **No** at the second prompt leaves it disabled |
| P-5 | `claude` or `gemini` installed | `cognirepo agents enable claude` (no flag) | Refused with the terms message; exit non-zero |
| P-6 | codex enabled, no API keys | `cognirepo ask "say OK"` (**spends quota**) | Answer returned through codex; `cognirepo agents probe codex` reports ready |
| P-7 | As P-6 plus a bogus `ANTHROPIC_API_KEY=x` | `cognirepo ask "say OK"` | Anthropic fails (401) and the call falls back to the CLI; no crash |
| P-8 | Agent CLI logged out | `cognirepo agents probe <name>` | Reports not ready with a login hint; no hang past `--timeout` |
| P-9 | Any | Run `cognirepo ask` from inside a Claude Code session | No recursive spawn (`COGNIREPO_HEADLESS` guard); returns or refuses promptly |
| P-10 | One real API key | `cognirepo setup` in a terminal | One hint line and a **No**-default question; **No** makes zero requests |
| P-11 | As P-10 | `cognirepo models refresh` | Per-provider status line; `models list` shows tiers; `doctor` shows the cached count |
| P-12 | As P-11, then unplug the network | `cognirepo ask "hi"` | Works from defaults/cache; no hang |
| P-13 | Key set, cache present | Change the key, `cognirepo models list` | Entry shown as stale (key fingerprint changed); defaults apply |
| P-14 | Any | `cognirepo setup` timed with and without agent CLIs installed | Difference under about 1 s (detection is one parallel `--version`, 3 s cap) |
| P-15 | Windows and macOS | P-1, P-2, P-11 | Same as Linux. **Not yet verified on either.** |
