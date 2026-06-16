# CogniRepo — Metrics Revalidation Workbook

Use this doc to revalidate `docs/METRICS.md`. Run each section, paste raw output into the
**RESULT** block, then hand the filled doc back to Claude Code to regenerate METRICS.md.

**Agents covered:** Claude · Gemini · Cursor · VS Code · Grok/OpenAI  
**Test repos:** `../cognirepo_test_repo/easy/flask` · `easy/fastapi` · `medium/celery` · `advanced/kubernetes` · `private-org/UpiClone`

---

## Setup (run once)

```bash
# Index every repo you plan to test — skip any you won't use
cd ../cognirepo_test_repo/easy/flask      && cognirepo setup && cognirepo doctor
cd ../cognirepo_test_repo/easy/fastapi    && cognirepo setup && cognirepo doctor
cd ../cognirepo_test_repo/medium/celery   && cognirepo setup && cognirepo doctor
cd ../cognirepo_test_repo/advanced/kubernetes && cognirepo setup && cognirepo doctor
cd ../cognirepo_test_repo/private-org/UpiClone && cognirepo setup && cognirepo doctor
```

---

## A — Automated Benchmark (no AI in loop)

**Repo:** `easy/flask` (run from inside the repo dir)

```bash
cd ../cognirepo_test_repo/easy/flask
cognirepo benchmark --json
```

**What to capture:** copy the full JSON output.

**RESULT — flask benchmark JSON**
```json

```

---

**Repo:** `easy/fastapi`

```bash
cd ../cognirepo_test_repo/easy/fastapi
cognirepo benchmark --json
```

**RESULT — fastapi benchmark JSON**
```json

```

---

**Repo:** `medium/celery`

```bash
cd ../cognirepo_test_repo/medium/celery
cognirepo benchmark --json
```

**RESULT — celery benchmark JSON**
```json

```

---

**Repo:** `advanced/kubernetes` *(requires `cognirepo[languages]` for Go)*

```bash
cd ../cognirepo_test_repo/advanced/kubernetes
cognirepo benchmark --json
```

**RESULT — kubernetes benchmark JSON**
```json

```

---

## B — Claude (Anthropic) — without vs with CogniRepo

**Repo:** `easy/flask`  
**Setup:** Point Claude Code at this repo (it should NOT have CogniRepo MCP active for Round 1).

### B1 — Without CogniRepo

Paste this prompt to Claude with **no MCP tools** (disable cognirepo MCP in `.claude/settings.json` temporarily, or use a fresh project):

```
Answer these three questions about the Flask codebase using only your training knowledge.
Do not read any files. Do not use tools.

Q1: Where is the `full_dispatch_request` method defined? Give file and line number.
Q2: What signals does Flask's request context push to the app context? Name them.
Q3: What is the default value of MAX_CONTENT_LENGTH in Flask config?
```

**RESULT — Claude without CogniRepo**
```

```

### B2 — With CogniRepo

Re-enable CogniRepo MCP. Same repo, same questions:

```
Answer these three questions about the Flask codebase.
Use CogniRepo tools — call lookup_symbol, context_pack, or retrieve_memory as needed.

Q1: Where is `full_dispatch_request` defined? Give exact file and line number.
Q2: What signals does Flask's request context push to the app context? Name them.
Q3: What is the default value of MAX_CONTENT_LENGTH in Flask config?

After answering, report: which tools you called, and roughly how many tokens context_pack returned.
```

**RESULT — Claude with CogniRepo**
```

```

---

## C — Gemini — cross-model memory retrieval

**Repo:** `easy/flask` (same session as B2 above — Claude must have run first and stored memories)

Open Gemini CLI in the same project directory. CogniRepo MCP must be active.

```
Call retrieve_memory("Flask request context signals") and get_last_context().
Report: what facts did you find, which agent stored them, and did you need to read any files?
```

**RESULT — Gemini cross-model retrieval**
```

```

---

## D — Cursor (IDE MCP)

**Repo:** `medium/celery`  
Open Cursor with the celery repo as project root. CogniRepo MCP must be configured in `.cursor/mcp.json`.

Paste in Cursor chat:

```
Use CogniRepo to answer:
1. Where is the `apply_async` method defined? File + line.
2. What retry strategy does Celery use by default?
Call lookup_symbol and context_pack. Report token count from context_pack.
```

**RESULT — Cursor**
```

```

---

## E — VS Code (MCP extension)

**Repo:** `medium/celery`  
Open VS Code with MCP extension active. CogniRepo configured in `.vscode/mcp.json`.

Same prompt as D above.

**RESULT — VS Code**
```

```

---

## F — Grok / OpenAI-compatible client

**Repo:** `easy/fastapi`  
Use any OpenAI-compatible client (Grok, LM Studio, Ollama) with CogniRepo MCP wired via `openai_adapter`.  
Set `GROK_API_KEY` or `OPENAI_API_KEY` in `.cognirepo/config.json` provider field.

```
cognirepo ask "Where is the APIRouter class defined and what methods does it expose?" --tier STANDARD
```

Paste the CLI output.

**RESULT — Grok/OpenAI adapter**
```

```

---

## G — Cross-repo retrieval (UpiClone org)

**Repo:** `private-org/UpiClone` (org with 3 microservices)  
**Agent:** Claude or Gemini (whichever is easier)

```
Call org_wide_search("payment initiation flow") then cross_repo_traverse("initiatePayment", "UpiClone").
Report: how many repos were searched, what files were found, and which service owns the entry point.
```

**RESULT — cross-repo org search**
```

```

---

## H — Index build times (fill from `cognirepo doctor` or `index-repo` output)

Run for each repo and note the wall-clock time printed at the end of `cognirepo index-repo .`:

| Repo | Files | Index time (s) | Symbol count |
|------|-------|---------------|--------------|
| easy/flask | | | |
| easy/fastapi | | | |
| medium/celery | | | |
| advanced/kubernetes | | | |
| private-org/UpiClone | | | |

**RESULT — paste the table above filled in**

---

## I — Token reduction spot-check (fill manually)

From section B2, note:

| Item | Value |
|------|-------|
| Tokens returned by `context_pack` | |
| Estimated tokens if reading the 2-3 relevant files directly | |
| Reduction % | |
| Tools called (list) | |
| Correct answers / 3 | |

**RESULT — paste the table above filled in**

---

## How to use this doc to update METRICS.md

Once all RESULT blocks are filled:

1. Hand this file to Claude Code:
   ```
   Read docs/BENCHMARK_VALIDATION.md and update docs/METRICS.md with the new numbers.
   Replace any "(unverified — carried forward)" notes with the real values.
   Keep the existing structure; only update numbers.
   Date: <today>
   ```
2. Claude Code will diff the old vs new numbers and update every table in METRICS.md.
3. Commit: `docs: revalidate METRICS.md against v1.1.3 benchmark run`.
