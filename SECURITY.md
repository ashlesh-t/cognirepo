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
| 0.1.x   | ✓ Current |
| < 0.1.0 | ✗         |

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
| API tokens | OS keychain | JWT signing secret |
| Encryption key | OS keychain | AES-256 key (never written to disk) |

### What leaves the machine

Query text and the assembled context bundle are sent to whichever model API you
configure (Anthropic, Google, xAI, OpenAI). **Nothing else.**

CogniRepo has no telemetry, no analytics, and no callbacks to any CogniRepo server.
There is no CogniRepo home server. Your data stays on your machine.

---

## Encryption at Rest

When `storage.encrypt: true` in `config.json`:

- **Algorithm:** AES-256 GCM (authenticated encryption)
- **Key management:** Key is generated once on `cognirepo init`, stored in the OS keychain via `keyring`. Never written to disk.
- **Scope:** All files in `vector_db/`, `graph/`, `index/`
- **Episodic log:** Not encrypted (plain JSONL); contains only event text you explicitly logged

**To enable:**
```bash
pip install 'cognirepo[security]'  # installs cryptography + keyring
# Set in .cognirepo/config.json:
# "storage": { "encrypt": true }
```

---

## Authentication (REST API)

- JWT required on all routes except `GET /health`
- Default bind: `localhost:8080` — safe for local use
- **Never expose on `0.0.0.0` without a firewall rule in production**

### Login Example
```bash
curl -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password": "yourpassword"}'
# Returns: { "access_token": "eyJ...", "token_type": "bearer" }
```

### Configuration
| Environment Variable | Description |
|---------------------|-------------|
| `COGNIREPO_JWT_SECRET` | JWT signing secret (required in production) |
| `COGNIREPO_PASSWORD_HASH` | Bcrypt hash of the API password |

**Generate a JWT secret:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Generate a password hash:**
```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'mypassword', bcrypt.gensalt()).decode())"
```

---

## Security Scanning

CogniRepo's CI pipeline runs four automated security tools on every push:

| Tool | What it checks |
|------|---------------|
| **Bandit** | Python SAST — HIGH and CRITICAL severity only |
| **Snyk** | Dependency vulnerabilities |
| **Trivy** | Container image and filesystem scanning |
| **TruffleHog** | Secrets accidentally committed to git history |

### Secret Scanning Patterns
The following patterns are watched by TruffleHog:
- API keys (ANTHROPIC, GEMINI, OPENAI, GROK)
- JWT secrets
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
2. **Network access is optional** — MCP stdio and REST API bind to `localhost` by default.
3. **Secrets never leave the machine** — API keys are passed via environment variables, not stored in `.cognirepo/`.
4. **Encryption defends against disk theft** — Encrypts stored embeddings and graphs; does not protect against a compromised process.

**Not in scope:**
- Protection against malicious code being indexed (CogniRepo reads but does not execute indexed code)
- Multi-user access control
- Remote deployment hardening
