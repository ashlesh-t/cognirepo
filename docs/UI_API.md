# Local control API (`cognirepo ui`)

A small HTTP API plus launcher for a local console. **Local-only by design**: it binds to loopback,
needs a per-session secret, and exposes no endpoint that reads arbitrary files or runs arbitrary
commands. The machine-readable contract is [`docs/openapi/ui-v1.json`](openapi/ui-v1.json)
(regenerate with `python -m interface.ui.openapi --write`; a test fails if it drifts).

## Quick start
```bash
cognirepo ui                  # start the server if needed, open http://127.0.0.1:8731/#token=…
cognirepo ui --no-open        # print the tokenised URL instead of opening a browser
cognirepo ui --stop           # stop the server
cognirepo ui --autostart on   # opt in to starting at login (off by default); `--autostart off` removes it
```
Default port is `8731` (a free port is used if it is busy; an explicit `--port` that is busy is an error).
The server serves **the repo you launched it from**; a second repo needs `cognirepo ui --stop` first.

The optional **`cognirepo-console`** package provides the web UI. If it is not installed, `cognirepo ui`
prints how to install it (`pip install cognirepo-console`) and serves the API plus a minimal status page.
CogniRepo never clones or downloads console code at runtime.

## Authentication
1. `cognirepo ui` opens `http://127.0.0.1:PORT/#token=<secret>`. The fragment is never sent to a server.
2. The page script (`/_cognirepo/bootstrap.js`, or the console's own) **strips the fragment first**, then
   `POST /api/v1/session {"token": …}`; the server answers with an `httpOnly; SameSite=Strict` cookie `cr_session`.
3. Every `/api/v1/*` request needs that cookie **or** `Authorization: Bearer <token>`. Comparison is constant-time.
4. The token lives for the server's lifetime in `<global dir>/ui/session.json` (mode 0600, removed on shutdown).

The only token-less responses are the data-free landing page / static console assets and the
`/_cognirepo/bootstrap.js` script. `POST /api/v1/session` takes the token in its body instead of a header.

## Endpoints (`/api/v1`)
| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/session` | Swap `{token}` for the session cookie |
| `GET` | `/api/v1/status` | Version, repo, watcher daemon health, MCP tool inventory, indexer status |
| `GET` | `/api/v1/graph?node=&depth=&limit=` | Read-only knowledge-graph slice. `depth` 0–3 (default 1), `limit` 1–2000 (default 200). Without `node`: the highest-degree nodes. Only whitelisted attributes are returned |
| `GET` | `/api/v1/harness` | Which agent clients (Claude Code, Cursor, VS Code, Gemini CLI) have the CogniRepo MCP server configured — names only, never args/env — plus a fixed-field summary of the shared last context (no query text) |
| `GET` | `/api/v1/insights` | `{exists, generated_at, bytes}` for the repo's insights report (`.claude/insights/<repo>-insights.html`) |
| `GET` | `/api/v1/insights/report` | The report HTML, read-only, from that one fixed path (no path/name parameter exists). Sent with `Content-Security-Policy: sandbox; default-src 'none'` so it can sit in an `<iframe sandbox>` (`frame-ancestors 'self'`); `?download=1` sends it as an attachment. `404 no_report` if absent, if the path is a symlink (or under one), or if it exceeds 8 MiB |
| `GET` | `/api/v1/services` | State of the allowlisted services |
| `POST` | `/api/v1/services/{name}/start` | Start a service. Body must be `{"confirm": true}` (strict boolean) |
| `POST` | `/api/v1/services/{name}/stop` | Stop a service. Body must be `{"confirm": true}` |

**Service allowlist:** `watcher` (the repo's file-watcher daemon), `insights` (`start` regenerates the report by running `cognirepo insights`; one run at a time, `stop` is `409 not_stoppable`) and `metrics` (in-process Prometheus
`/metrics` on `127.0.0.1:9090`). Any other name is a `404` before anything else is evaluated. Each service
maps to fixed code with a fixed argv — nothing from a request reaches a command line.

### Status codes
`200` ok · `400` `confirm_required` · `401` missing/invalid token · `403` bad `Host`/`Origin` · `404` unknown service/path ·
`409` `port_in_use` · `422` invalid parameters · `429` locked out (`Retry-After` seconds) · `501` unsupported platform.

### Stability
`/api/v1` is additive-only: fields may be added, never removed or retyped. A breaking change ships as `/api/v2`.

## Security model
| Threat | Mitigation |
|--------|------------|
| A web page calls `127.0.0.1` (CSRF) | Exact `Origin` allowlist (own origin only; extra origins only via explicit `--allow-origin`, never `*`), `SameSite=Strict` cookie, token required |
| DNS rebinding | Exact `Host` allowlist (`127.0.0.1:PORT`, `localhost:PORT`, `[::1]:PORT`) |
| Token guessing | 5 bad tokens ⇒ lockout with exponential backoff (5 s … 5 min); a locked client is refused even with the right token |
| Exposure on the network | Binds loopback only. A non-loopback `--host` (incl. `0.0.0.0`) is refused unless `--unsafe-bind` is given, with a loud warning. Autostart can never contain `--unsafe-bind` |
| XSS in the page | `Content-Security-Policy: default-src 'self'`, `nosniff`, `X-Frame-Options: DENY`, `no-store` |
| Control abuse | Allowlist, strict `confirm`, local audit log of every attempt (including denials) at `<global dir>/ui/audit.log` (0600, rotated, never contains the token) |
| Arbitrary file read / exec | No such endpoint exists; the graph/harness/status handlers read fixed files only |

The UI process is **read-only** with respect to the index: it never imports `ASTIndexer` or `LocalVectorDB`
(their load paths can rename live index files under a concurrent writer) and never calls `KnowledgeGraph.save()`.

**Remote viewing is out of scope** (no relay, no hosted component, no password login). A Tailscale recipe will be
documented separately; until then keep the server on loopback.

## Autostart (opt-in)
First interactive run asks `Start the console automatically at login? (y/N)` (default **No**, asked once, never in
scripts). `cognirepo ui --autostart on|off` does it explicitly; both are idempotent.
| OS | Mechanism |
|----|-----------|
| Linux | `~/.config/systemd/user/cognirepo-ui.service` (`systemctl --user enable --now`) |
| macOS | `~/Library/LaunchAgents/com.cognirepo.ui.plist` (`launchctl bootstrap gui/<uid>`) |
| Windows | Task Scheduler task `CogniRepoUI` (logon trigger, current user, least privilege) |

The installed command is `<this python> -m interface.cli.main ui --serve --no-open --host 127.0.0.1` — loopback by
construction, and independent of whatever `cognirepo` happens to be first on `PATH`.

## Console package contract (`cognirepo-console`)
`import cognirepo_console` must expose `STATIC_DIR` (a directory containing `index.html`); the server mounts it at `/`.
The console must perform the fragment→cookie swap itself (or include `/_cognirepo/bootstrap.js`) and call only the
endpoints above.

## Files (under `<global dir>/ui/`, default `~/.cognirepo/ui/`)
`session.json` (token/port/pid, 0600) · `audit.log` (+ `.1`) · `server.log` · `config.json` (autostart choice).
