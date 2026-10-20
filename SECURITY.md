# Security Policy

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report security issues privately via **GitHub Security Advisories**:

1. Go to the repository on GitHub
2. Click the **Security** tab
3. Click **Advisories** → **Report a vulnerability**
4. Fill in the form and submit

**Response target:** 72 hours for acknowledgement.

Please include in your report:
- Affected version(s)
- Step-by-step reproduction instructions
- CWE identifier if known (e.g. CWE-89 for SQL injection)
- Impact assessment

We will coordinate disclosure and credit you in the advisory unless you prefer to remain anonymous.

---

## Supported Versions

Only the **latest release** receives security patches. Older versions are unsupported.

| Version | Supported |
|---------|-----------|
| 2.x.x   | ✓ Current |
| < 2.0.0 | ✗         |

---

## What Data is Stored and Where

All data is stored **locally in `.cognirepo/`** inside your project directory.
CogniRepo never sends data to external servers.

| Data | Location | Contains |
|------|----------|---------|
| Semantic memories | `.cognirepo/vector_db/` | FAISS embeddings + metadata |
| Episodic events | `.cognirepo/episodic/` | Plain-text event log (JSONL) |
| Knowledge graph | `.cognirepo/graph/` | NetworkX graph of code symbols |
| AST index | `.cognirepo/index/` | Symbol → file/line mapping |
| Encryption key | OS keychain | Fernet key (never written to disk) |

### What leaves the machine

Query text and the assembled context bundle are sent to whichever model API you
configure (Anthropic, Google, xAI, OpenAI). **Nothing else.**

CogniRepo has no telemetry, no analytics, and no callbacks to any CogniRepo server.
There is no CogniRepo home server. Your data stays on your machine.

---

## Encryption at Rest

When `storage.encrypt: true` in `config.json`:

- **Algorithm:** [Fernet](https://cryptography.io/en/latest/fernet/) from the `cryptography` library — authenticated symmetric encryption (AES-128-CBC with an HMAC-SHA256 tag). It is **not** AES-256-GCM; earlier versions of this document said so.
- **Key management:** the key is generated once on `cognirepo init` and stored in the OS keychain via `keyring`. It is never written to disk.

**What is encrypted** (the authoritative list is `core/security/coverage.py`; a test fails if a store path is added without being classified):

| Store | Encrypted |
|---|---|
| Knowledge graph (`graph/graph.pkl`) and its journal | ✓ |
| Behaviour model (`graph/behaviour.json`) | ✓ |
| Org graph (`~/.cognirepo/org_graph.pkl`) | ✓ |
| Episodic log (`episodic/`) | ✓ |
| Memory **text** of the local FAISS backend (`memory/semantic_metadata.json`, `vector_backend: "faiss"` only) | ✓ |
| Project learnings (`learnings/learnings.json`) — key = this repo's `project_id` | ✓ |
| Global learnings (`~/.cognirepo/learnings/`) — own keychain entry `cognirepo-global-learnings`, so every repo can read it | ✓ |
| Org project memory text (`~/.cognirepo/projects/<org>/<project>/memory/`) — own keychain entry per `<org>/<project>` | ✓ |

**What is NOT encrypted**, even with `storage.encrypt: true` (`cognirepo doctor` warns about this when encryption is on):

| Store | Contains |
|---|---|
| Chroma vector store (`vector_db/chroma/`) — **the default backend** | the text of stored semantic memories and their embeddings. Chroma has no encryption hook; use full-disk encryption or `vector_backend: "faiss"` |
| FAISS vector files (`semantic.index`, `ast.index`, `episodic_vecs.npy`) | embeddings only — no text, but vectors can leak meaning |
| AST index (`index/ast_index.json`, `ast_metadata.json`, `manifest.json`) | symbol names, paths, line numbers, docstrings. Deliberately left out: it is rebuildable from the source tree stored beside it, and it is read by ~15 call sites plus the checksummed generation pointer |
| `index/summaries.json`, `doc_ingest.json`, `endpoints.json`, `http_calls.json`, rotated `episodic_archive.json`, `sessions/`, `errors/`, `hook.log`, `last_context.json` | summaries/derived text and operational output |

If your threat model needs these protected, use full-disk encryption (or an encrypted volume) for the project directory and `~/.cognirepo/`.

**Reading and recovery rules.**
- A file that is already ciphertext is always decrypted on read, even if `storage.encrypt` was later turned off — switching the flag never strands data.
- Plaintext written before the flag was on is read as-is and encrypted on its next save.
- Ciphertext that cannot be decrypted (no keyring, wrong or lost key) is treated as *locked*, not corrupt: it is never quarantined or overwritten, and writes to that store fail loudly instead.
- **The key lives only in the OS keychain.** If it is lost (keychain reset, new machine, headless host), encrypted data is unrecoverable. Back the key up, or run `cognirepo encrypt-stores --decrypt` before you move.
- `cognirepo encrypt-stores [--decrypt] [--dry-run]` migrates learnings and project memory now instead of waiting for the next save. Each file is encrypted, decrypted again and compared before it replaces the original; a file that fails verification or is locked is left untouched.

**To enable:**
```bash
pip install 'cognirepo[security]'  # installs cryptography + keyring
# Set in .cognirepo/config.json:
# "storage": { "encrypt": true }
```

---

## Local control API (`cognirepo ui`)

See [docs/UI_API.md](docs/UI_API.md). Loopback-only bind (`--unsafe-bind` to override, with a warning), per-session
token (constant-time compare, URL fragment → `httpOnly; SameSite=Strict` cookie), exact `Host`/`Origin` allowlists,
bad-token lockout with backoff, an allowlisted + `confirm`-gated service start/stop, a local audit log, and no
endpoint that reads arbitrary files or executes commands. Remote access is out of scope.

**Console download.** `cognirepo ui` is the one place CogniRepo runs `git clone` (once, when `~/.cognirepo/console/`
is missing; opt out with `--no-console-fetch` or `COGNIREPO_CONSOLE_AUTOFETCH=0`). The URL is fixed or comes from your
own env/config, `ext::` transports are disallowed, nothing from the clone is ever executed, and the bundle is refused
unless its `console.json` matches this server's API major and every file's sha256. Only manifest-listed files are
served. The hashes catch corruption and local tampering, not a malicious source repo. See
[docs/UI_API.md](docs/UI_API.md#console-install-git-managed-215).

## Network Surface

CogniRepo has **no remote API and no user accounts**. (An earlier REST API with JWT login was removed.) The only authenticated surface is the local control API described above.

- **MCP** (`cognirepo serve`) talks to your AI tool over **stdio**: no port is opened.
- Network listeners are opt-in. The **`cognirepo ui`** control API is loopback-only and token-authenticated (see above).
- The optional **`cognirepo metrics`** exporter (Prometheus `/metrics`) binds `127.0.0.1:9090` by default, has **no authentication**, and exposes operational counters only. Do not bind it to `0.0.0.0` on an untrusted network.
- Model calls go out to the provider you configured (see "What leaves the machine").

---

## Security Scanning

CogniRepo's CI pipeline runs four automated security tools on every push:

| Tool | What it checks |
|------|---------------|
| **Bandit** | Python SAST — HIGH and CRITICAL severity only |
| **pip-audit** | Dependency vulnerabilities (pyproject install + requirements.txt pins) |
| **Trivy** | Container image and filesystem scanning |
| **TruffleHog** | Secrets accidentally committed to git history |

### Secret Scanning Patterns
The following patterns are watched by TruffleHog:
- API keys (ANTHROPIC, GEMINI, OPENAI, GROK)
- Encryption keys and tokens
- Redis connection strings containing passwords
- Any high-entropy strings in committed files

**Never commit:**
- `.env` files
- `config.json` containing API keys
- Private keys or certificates

---

## Known Non-Issues

- **Pickle deserialization** (`graph.pkl`): The graph file is loaded with `pickle.load`.
  This is intentional — the file is local, user-controlled, and protected by the
  `.cognirepo/.gitignore`. The `# nosec B301` annotation is correct.
- **Subprocess with list args** (`cognirepo seed`): Uses `subprocess.run` with a list
  argument (not a shell string), which is not injectable. The `# nosec B603` annotation
  is correct.

---

## Threat Model

CogniRepo is designed for **local developer use**. The threat model assumes:

1. **Trusted local user** — No multi-tenant isolation. `.cognirepo/` is user-owned.
2. **Network access is optional** — MCP runs over stdio; the only listeners are the optional `ui` control API and `metrics` exporter, both bound to `127.0.0.1` by default.
3. **Secrets never leave the machine** — API keys are passed via environment variables, not stored in `.cognirepo/`.
4. **Encryption defends against disk theft** — Encrypts stored embeddings and graphs; does not protect against a compromised process.

**Not in scope:**
- Protection against malicious code being indexed (CogniRepo reads but does not execute indexed code)
- Multi-user access control
- Remote deployment hardening
