# CogniRepo Security Guide

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

---

## Encryption at Rest

When `storage.encrypt: true` in `config.json`:

- **Algorithm:** AES-256 GCM (authenticated encryption)
- **Key management:** Key is generated once on `cognirepo init`, stored in the OS keychain via `keyring`. Never written to disk.
- **Scope:** All files in `vector_db/`, `graph/`, `index/`
- **Episodic log:** Not encrypted (plain JSONL); contains only event text you explicitly logged

**To enable:**
```bash
pip install cognirepo[security]  # installs cryptography + keyring
# Set in .cognirepo/config.json:
# "storage": { "encrypt": true }
```

---

## Authentication (REST API)

The FastAPI REST API uses **JWT Bearer token** authentication.

### Login
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password": "yourpassword"}'
# Returns: { "access_token": "eyJ...", "token_type": "bearer" }
```

### Authenticated Request
```bash
curl http://localhost:8000/memory/retrieve \
  -H "Authorization: Bearer eyJ..." \
  -d '{"query": "cache bug fix"}'
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

Tokens expire after **24 hours**.

---

## Secret Scanning

CogniRepo CI runs **TruffleHog** with `--only-verified` to detect committed secrets.

The following patterns are watched:
- API keys (ANTHROPIC, GEMINI, OPENAI, GROK)
- JWT secrets
- Redis connection strings containing passwords
- Any high-entropy strings in committed files

**Never commit:**
- `.env` files
- `config.json` containing API keys
- Private keys or certificates

---

## GitHub Secrets Required for CI

| Secret | Description |
|--------|-------------|
| `SNYK_TOKEN` | Snyk vulnerability scanning |
| `COGNIREPO_JWT_SECRET` | API auth token for integration tests |
| `COGNIREPO_PASSWORD_HASH` | API password for integration tests |

See [CONTRIBUTING.md](../CONTRIBUTING.md) for setup instructions.

---

## Dependency Vulnerabilities

CI runs:
- **Bandit:** Python static analysis (fails on HIGH severity)
- **Snyk:** Dependency vulnerability scan (fails on CRITICAL CVEs)
- **Trivy:** Filesystem scan (fails on CRITICAL/HIGH unpatched CVEs)

To scan locally:
```bash
pip install bandit
bandit -r . --exclude ./.venv --severity-level high

pip install snyk
snyk test --severity-threshold=critical
```

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
