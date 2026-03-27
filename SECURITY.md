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

## What CogniRepo Stores and Where

All data is local. Nothing is written outside `.cognirepo/` in your project root.

```
Semantic memories      → .cognirepo/vector_db/      local disk only
Episodic event log     → .cognirepo/episodic/        local disk only
Knowledge graph        → .cognirepo/graph/           local disk only
Session history        → .cognirepo/sessions/        local disk only
Encryption key         → OS keychain                 never written to disk
JWT secret             → OS keychain or env var      never in config.json
Password hash          → OS keychain or env var      never in config.json
```

### What leaves the machine

Query text and the assembled context bundle are sent to whichever model API you
configure (Anthropic, Google, xAI, OpenAI). **Nothing else.**

CogniRepo has no telemetry, no analytics, and no callbacks to any CogniRepo server.
There is no CogniRepo home server. Your data stays on your machine.

---

## Trust Boundaries

### REST API
- JWT required on all routes except `GET /health`
- Default bind: `localhost:8080` — safe for local use
- **Never expose on `0.0.0.0` without a firewall rule in production**
- Set a strong password on `cognirepo init --password <strong-password>`

### gRPC
- Unauthenticated by default — suitable for localhost multi-agent use only
- Enable mTLS for any multi-machine or networked deployment

### `.cognirepo/` storage
- Protected by `.gitignore` emitted automatically on `cognirepo init`
- Enable Fernet encryption at rest with `storage.encrypt: true` in `config.json`
- Requires `pip install cognirepo[security]`
- The encryption key is stored in the OS keychain — never on disk

### Secrets in CI / Docker
Use environment variables instead of the OS keychain in containerised environments:

```bash
COGNIREPO_JWT_SECRET=<32+ char random string>
COGNIREPO_PASSWORD_HASH=<bcrypt hash>
COGNIREPO_ENCRYPTION_KEY=<base64 Fernet key>  # if encrypt: true
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

Pre-commit hooks run Bandit and detect-private-key locally before every commit.

---

## Known Non-Issues

- **Pickle deserialization** (`graph.pkl`): The graph file is loaded with `pickle.load`.
  This is intentional — the file is local, user-controlled, and protected by the
  `.cognirepo/.gitignore`. The `# nosec B301` annotation is correct.
- **Subprocess with list args** (`cognirepo seed`): Uses `subprocess.run` with a list
  argument (not a shell string), which is not injectable. The `# nosec B603` annotation
  is correct.
