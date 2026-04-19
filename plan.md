# CogniRepo Improvement Plan — Implementation Reference

> Execute tasks in order. Each task is independent within its phase but phases are sequential.
> Do not start Phase N+1 until all tasks in Phase N pass acceptance criteria.

---

## PHASE 1 — Remove Dead Code & Phantom REST API

---

### TASK 1.1 — Delete orphaned files and directories

**Description:**
Remove files that are either explicitly deprecated, unused, or dev artifacts that leaked into
the repo. These create confusion for contributors and signal immaturity to OSS readers.

**Key Directions:**
- Delete entire `myapp/` directory (`auth.py`, `utils.py`, `__init__.py`)
- Delete `vector_db/faiss_adapter.py` — thin wrapper nobody imports; `LocalVectorDB` is used directly everywhere
- Delete `cli/plan_helper.md` — dev artifact in a Python package folder
- Delete `cli/root_cause_analysis.md` — same
- Check `pyproject.toml` `[project] packages` list — remove `myapp` if listed there

**Acceptance Criteria:**
```bash
[ ! -d myapp ] && echo PASS || echo FAIL
python -c "import vector_db.faiss_adapter" 2>&1 | grep -q "No module" && echo PASS || echo FAIL
[ ! -f cli/plan_helper.md ] && echo PASS || echo FAIL
[ ! -f cli/root_cause_analysis.md ] && echo PASS || echo FAIL
grep -r "myapp" pyproject.toml && echo FAIL || echo PASS
```

---

### TASK 1.2 — Strip REST API from documentation

**Description:**
The REST API (Flask/FastAPI endpoints, JWT auth, curl examples) is documented in README,
USAGE, ARCHITECTURE but has zero implementation. Shipping this to OSS is a credibility killer.

**Key Directions:**

`README.md`:
- Remove section titled "REST API" or "API Usage" or similar
- Remove any `curl` code blocks calling `/api/v1/...`
- Remove Docker REST API usage examples
- Keep: MCP usage, CLI usage, install instructions

`USAGE.md`:
- Remove REST API section entirely
- Remove `--via-api` flag documentation (or mark as "not yet implemented")
- Keep: all CLI commands, MCP tool examples

`ARCHITECTURE.md`:
- Remove `api/` from component table
- Remove JWT auth / REST adapter description
- Add one-liner: "HTTP transport not yet implemented; MCP stdio is the active transport"

`docker-compose.yml`:
- Remove services: `api`, `redis`, `postgres`
- If nothing remains useful, delete the file entirely
- If keeping for dev purposes, keep only a minimal `cognirepo-dev` service running `cognirepo serve`

**Acceptance Criteria:**
```bash
grep -r "curl" README.md && echo FAIL || echo PASS
grep -r "/api/v1" README.md USAGE.md && echo FAIL || echo PASS
grep -r "JWT" ARCHITECTURE.md && echo FAIL || echo PASS
grep -r "postgres\|FastAPI\|Flask" docker-compose.yml 2>/dev/null && echo FAIL || echo PASS
```

---

### TASK 1.3 — Strip phantom config keys, simplify config schema

**Description:**
`config.json` contains `api_port` and `api_url` keys that power a non-existent REST server.
`_write_config()` in `cli/init_project.py` writes these on every init.
Also replace the 4-tier `models` dict with a single `model` key (provider auto-detected from env).

**Key Directions:**

`.cognirepo/config.json` (edit directly):
- Remove `"api_port": 9090`
- Remove `"api_url": "http://localhost:9090"`
- Add `"vector_backend": "faiss"` under `"storage"` key
- Add `"project": null` at top level (sibling of `"org"`)
- Replace `"models": {QUICK: ..., STANDARD: ..., COMPLEX: ..., EXPERT: ...}` with `"model": {"provider": "auto", "model": "auto"}`
- Remove `"multi_model": true`
- Keep everything else unchanged

`cli/init_project.py` → `_write_config()`:
- Remove `api_port` and `api_url` from the config dict
- Add `storage.vector_backend` defaulting to `"faiss"`
- Add top-level `project` field defaulting to `null`
- Replace `DEFAULT_MODELS` constant (4-tier dict) with `DEFAULT_MODEL = {"provider": "auto", "model": "auto"}`
- Update schema written to config.json accordingly

`orchestrator/classifier.py`:
- Update `_load_model_registry()` or equivalent to read `config["model"]` single key
- Tier routing (QUICK/STANDARD/COMPLEX/EXPERT) can still exist internally
  but all tiers default to the single configured provider unless explicitly overridden
- Add auto-detect logic: if `provider == "auto"`, check env vars in order:
  `ANTHROPIC_API_KEY` → `GEMINI_API_KEY` → `OPENAI_API_KEY`; first found wins

`orchestrator/router.py`:
- Update `_dispatch_with_fallback()` to read `config["model"]["provider"]` as primary
- Graceful fallback: accept both `config["model"]` (new) and `config["models"]["EXPERT"]` (old)
  so existing installs don't break

**Acceptance Criteria:**
```bash
python -c "
import json
c = json.load(open('.cognirepo/config.json'))
assert 'api_port' not in c, 'api_port still present'
assert 'api_url' not in c, 'api_url still present'
assert 'vector_backend' in c['storage'], 'vector_backend missing'
assert 'model' in c, 'model key missing'
assert 'models' not in c, 'old models key still present'
print('PASS')
"
grep -n "api_port\|api_url" cli/init_project.py && echo FAIL || echo PASS
```

---

### TASK 1.4 — Simplify init wizard (7 steps → 5 steps)

**Description:**
`cli/wizard.py` `run_wizard()` asks about multi-model routing and Redis — both add friction
for zero gain for the 90% of users who have a single API key and no Redis.
Remove them. Add vector backend selection instead (faiss vs chroma).

**Key Directions:**

`cli/wizard.py` → `run_wizard()`:
- **REMOVE** step: "Enable multi-model routing?" (entire `_ask_yn` block + related)
- **REMOVE** step: "Enable Redis cache?" (entire block)
- **KEEP** step 1: Project name
- **KEEP** step 2: Encryption at rest
- **KEEP** step 3: Language parsers
- **KEEP** step 4: MCP targets — Claude / Gemini / Cursor / VS Code (this is the core value, must stay)
- **KEEP** step 5: Org + Project (extended in Task 3.4)
- **ADD** inside step 2 or as new step: "Vector backend?" — `faiss` (default) or `chroma`
  - If chroma: run `_pip_install("chroma")` silently; set `vector_backend: "chroma"` in return dict

Return dict must include: `project_name`, `encrypt`, `install_languages`, `mcp_targets`, `mcp_global`, `org`, `project`, `vector_backend`

`cli/init_project.py`:
- Remove `multi_model` and `redis` from `init_project()` signature (or hide as `**kwargs` with deprecation)
- Add `vector_backend: str = "faiss"` param flowing through to `_write_config()`

**Acceptance Criteria:**
```bash
# Verify run_wizard() return dict has correct keys when run non-interactively
python -c "
import unittest.mock as mock
# Patch all prompts to return defaults
with mock.patch('builtins.input', return_value=''):
    with mock.patch('cli.wizard._ask_yn', return_value=False):
        with mock.patch('cli.wizard._ask_text', return_value='testproject'):
            with mock.patch('cli.wizard._ask_choice', return_value=0):
                try:
                    from cli.wizard import run_wizard
                    cfg = run_wizard()
                    assert 'multi_model' not in cfg or cfg.get('multi_model') is None
                    assert 'redis' not in cfg or cfg.get('redis') is None
                    assert 'vector_backend' in cfg
                    print('PASS')
                except Exception as e:
                    print(f'Manual verify needed: {e}')
" 2>/dev/null || echo "Manual verify needed (TTY required)"
```

---

## PHASE 2 — ChromaDB Properly Wired with Behaviour Scoring

---

### TASK 2.1 — Create `vector_db/factory.py`

**Description:**
Nothing currently selects ChromaDB — `memory/semantic_memory.py` hardcodes `LocalVectorDB`.
The factory reads `config.json → storage.vector_backend` and returns the correct adapter.
Defaults to `"faiss"` if config is unreadable or key is missing.

**Key Directions:**

Create `vector_db/factory.py`:

```python
"""
vector_db/factory.py
Reads storage.vector_backend from .cognirepo/config.json and returns
the appropriate VectorStorageAdapter implementation.
Defaults to "faiss" if config unreadable or key missing.
"""
from __future__ import annotations
import json, logging
from pathlib import Path
from vector_db.adapter import VectorStorageAdapter

_log = logging.getLogger(__name__)

def get_vector_adapter(dim: int = 384) -> VectorStorageAdapter:
    backend = _read_backend()
    if backend == "chroma":
        try:
            from vector_db.chroma_adapter import ChromaDBAdapter
            path = _get_vector_db_path()
            _log.debug("vector backend: chroma at %s", path)
            return ChromaDBAdapter(path=str(path))
        except ImportError:
            _log.warning("chromadb not installed, falling back to faiss. Run: pip install chromadb")
    _log.debug("vector backend: faiss")
    from vector_db.local_vector_db import LocalVectorDB
    return LocalVectorDB(dim=dim)

def _read_backend() -> str:
    try:
        config_path = _find_config()
        if config_path and config_path.exists():
            return json.loads(config_path.read_text()).get("storage", {}).get("vector_backend", "faiss")
    except Exception:
        pass
    return "faiss"

def _find_config() -> Path | None:
    """Walk up from cwd to find .cognirepo/config.json"""
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / ".cognirepo" / "config.json"
        if candidate.exists():
            return candidate
    return None

def _get_vector_db_path() -> Path:
    config = _find_config()
    return (config.parent / "vector_db") if config else (Path.home() / ".cognirepo" / "vector_db")
```

**Acceptance Criteria:**
```bash
python -c "
from vector_db.factory import get_vector_adapter
from vector_db.local_vector_db import LocalVectorDB
db = get_vector_adapter()
assert isinstance(db, LocalVectorDB), f'Expected LocalVectorDB, got {type(db)}'
print('PASS: default is faiss')
"
```

---

### TASK 2.2 — Wire factory into `memory/semantic_memory.py`

**Description:**
One-line change: replace hardcoded `LocalVectorDB()` construction with `get_vector_adapter()`.
All existing `self._db.*` call sites are unchanged — same `VectorStorageAdapter` interface.

**Key Directions:**

`memory/semantic_memory.py`:
- Find the import: `from vector_db.local_vector_db import LocalVectorDB`
- Replace with: `from vector_db.factory import get_vector_adapter`
- Find construction: `self._db = LocalVectorDB(...)` (in `__init__`)
- Replace with: `self._db = get_vector_adapter(dim=384)`
- All `self._db.add/search/search_with_scores/save/deprecate_row` calls unchanged

If any other `memory/` files directly instantiate `LocalVectorDB` for semantic storage
(e.g. `ast_semantic_memory.py`), apply the same one-line change there too.

**Acceptance Criteria:**
```bash
cognirepo store-memory "factory wiring test"
cognirepo retrieve-memory "factory wiring" | grep -q "factory wiring test" && echo PASS || echo FAIL
```

---

### TASK 2.3 — Extend ChromaDB adapter and LocalVectorDB with behaviour scoring

**Description:**
Both adapters need `behaviour_score` in stored metadata and `update_behaviour_score()` method.
ChromaDB natively supports metadata updates; FAISS uses the metadata JSON file.
Both apply a `combined_score` formula in `search_with_scores()`.

**Key Directions:**

`vector_db/adapter.py` (ABC) — add abstract method:
```python
@abstractmethod
def update_behaviour_score(self, item_id, delta: float = 0.1) -> None:
    """Increment stored behaviour_score for an item. Best-effort — no exception if unsupported."""
```

`vector_db/chroma_adapter.py`:

In `add()` — add `behaviour_score: float = 0.0` param and include in metadata:
```python
metadata = {"text": text, "importance": float(importance),
            "source": source, "behaviour_score": float(behaviour_score)}
```

New method:
```python
def update_behaviour_score(self, chroma_id: str, delta: float = 0.1) -> None:
    try:
        existing = self._collection.get(ids=[chroma_id], include=["metadatas"])
        if not existing["metadatas"]:
            return
        meta = existing["metadatas"][0]
        new_score = min(1.0, float(meta.get("behaviour_score", 0.0)) + delta)
        self._collection.update(ids=[chroma_id], metadatas=[{**meta, "behaviour_score": new_score}])
    except Exception as e:
        logging.getLogger(__name__).warning("update_behaviour_score: %s", e)
```

In `search_with_scores()` — add combined_score after fetching results:
```python
for r in results:
    b = float(r.get("behaviour_score", 0.0))
    l2 = max(0.0, 1.0 - float(r.get("l2_distance", 0.0)) / 2.0)
    r["combined_score"] = round(l2 * 0.8 + b * 0.2, 4)
return sorted(results, key=lambda r: r["combined_score"], reverse=True)
```

`vector_db/local_vector_db.py`:

In `add()` — add `behaviour_score: float = 0.0` to metadata dict:
```python
self._meta.append({..., "behaviour_score": float(behaviour_score)})
```

New method:
```python
def update_behaviour_score(self, faiss_row: int, delta: float = 0.1) -> None:
    if 0 <= faiss_row < len(self._meta):
        old = float(self._meta[faiss_row].get("behaviour_score", 0.0))
        self._meta[faiss_row]["behaviour_score"] = round(min(1.0, old + delta), 4)
        self._save_meta()
```

In `search_with_scores()` — add `combined_score` using same formula.

**Acceptance Criteria:**
```bash
python -c "
import numpy as np, tempfile
from vector_db.local_vector_db import LocalVectorDB
import unittest.mock as mock

with tempfile.TemporaryDirectory() as tmp:
    with mock.patch('config.paths.get_cognirepo_path', return_value=__import__('pathlib').Path(tmp)):
        db = LocalVectorDB(dim=4)
        vec = np.array([1.0, 0.0, 0.0, 0.0], dtype='float32')
        db.add(vec, 'test', importance=0.5, behaviour_score=0.0)
        db.update_behaviour_score(0, delta=0.3)
        results = db.search_with_scores(vec, k=1)
        assert results[0]['behaviour_score'] >= 0.3, f'score={results[0][\"behaviour_score\"]}'
        assert 'combined_score' in results[0]
        print('PASS')
" 2>/dev/null || echo "Manual verify needed — check LocalVectorDB path handling"
```

---

### TASK 2.4 — Wire behaviour feedback into vector store

**Description:**
`BehaviourTracker.record_feedback(query_id, useful)` updates `symbol_weights` in `behaviour.json`
but not the vector store. When a user accepts a result (useful=True), the vector's `behaviour_score`
should increment so it ranks higher in future searches. Close this feedback loop.

**Key Directions:**

`graph/behaviour_tracker.py` → `__init__()`:
- Add optional param: `db_adapter=None`
- Store: `self._db_adapter = db_adapter`

`graph/behaviour_tracker.py` → `record_query()`:
- When building `retrieved_symbols` list, include `faiss_row` from each result dict
  (`search_with_scores()` already returns `faiss_row` — just store it in `query_history`)
- Schema: `{"symbol_id": ..., "faiss_row": <int>, "text": ...}`

`graph/behaviour_tracker.py` → `record_feedback()`:
```python
def record_feedback(self, query_id: str, useful: bool) -> None:
    # existing symbol_weights logic here...

    # ADD: update vector store behaviour scores
    if useful and self._db_adapter is not None:
        entry = self.data["query_history"].get(query_id, {})
        for sym in entry.get("retrieved_symbols", []):
            faiss_row = sym.get("faiss_row")
            if faiss_row is not None:
                try:
                    self._db_adapter.update_behaviour_score(faiss_row, delta=0.1)
                except Exception:
                    pass  # best-effort, never block
```

Caller site (wherever `BehaviourTracker` is constructed — likely `tools/retrieve_memory.py`
or `server/mcp_server.py`):
- Pass `db_adapter=get_vector_adapter()` to the constructor
- Or lazily set `tracker._db_adapter = get_vector_adapter()` after construction if refactoring
  the constructor is too invasive

**Acceptance Criteria:**
```bash
python -c "
from graph.behaviour_tracker import BehaviourTracker
import inspect
sig = inspect.signature(BehaviourTracker.__init__)
assert 'db_adapter' in sig.parameters, 'db_adapter param missing from __init__'
assert 'record_feedback' in dir(BehaviourTracker)
print('PASS: signature correct')
"
```

---

## PHASE 3 — Org → Project Hierarchy

---

### TASK 3.1 — Migrate `config/orgs.py` to project-aware schema

**Description:**
Current schema: `{org_name: {repos: [paths]}}` — flat, no project concept.
New schema: `{org_name: {projects: {proj_name: {repos, description, shared_memory_path, created_at}}}}`.
Old schema auto-migrates on load into a `_legacy` project. All existing callers still work.

**Key Directions:**

`config/orgs.py` — add migration on `_load_orgs()`:
```python
def _migrate_schema(raw: dict) -> dict:
    migrated = {}
    for org, data in raw.items():
        if "projects" in data:
            migrated[org] = data  # already new schema
        elif "repos" in data:
            # old flat schema → move into _legacy project
            migrated[org] = {"projects": {"_legacy": {
                "description": "Migrated from flat org",
                "repos": data["repos"],
                "created_at": _now(),
                "shared_memory_path": str(_shared_mem_path(org, "_legacy")),
            }}}
        else:
            migrated[org] = {"projects": {}}
    return migrated
```

New functions to add:
```python
def create_project(org_name: str, project_name: str, description: str = "") -> bool
def list_projects(org_name: str) -> dict[str, dict]
def link_repo_to_project(repo_path: str, org_name: str, project_name: str) -> bool
def unlink_repo_from_project(repo_path: str, org_name: str, project_name: str) -> bool
def get_repo_project(repo_path: str) -> tuple[str, str] | None   # (org_name, project_name)
def get_project_repos(org_name: str, project_name: str) -> list[str]
def get_shared_memory_path(org_name: str, project_name: str) -> Path
    # returns: Path.home() / ".cognirepo" / "projects" / org_name / project_name
```

Backward-compat wrappers (existing callers unchanged):
```python
def link_repo_to_org(repo_path, org_name):
    """Backward compat: links to _legacy project."""
    create_org(org_name)
    return link_repo_to_project(repo_path, org_name, "_legacy")

def get_repo_org(repo_path) -> str | None:
    """Backward compat: returns org name regardless of project."""
    r = get_repo_project(repo_path)
    return r[0] if r else None
```

**Acceptance Criteria:**
```bash
python -c "
import os, json, tempfile
os.environ['COGNIREPO_ORGS_FILE'] = '/tmp/_test_orgs.json'  # if env-override supported
# OR patch directly in test

from config.orgs import create_org, create_project, link_repo_to_project, get_repo_project, list_projects
# These calls should not raise
create_org('testco')
create_project('testco', 'backend', description='API services')
link_repo_to_project('/tmp/repo1', 'testco', 'backend')
result = get_repo_project('/tmp/repo1')
assert result == ('testco', 'backend'), f'got {result}'
projects = list_projects('testco')
assert 'backend' in projects, f'projects: {projects}'
print('PASS')
" && rm -f /tmp/_test_orgs.json
```

---

### TASK 3.2 — Create `memory/project_memory.py`

**Description:**
Shared FAISS index at `~/.cognirepo/projects/<org>/<project>/` that all repos in a project
contribute to. Provides the data layer for cross-repo knowledge sharing within a project.

**Key Directions:**

Create `memory/project_memory.py`:

```python
"""
memory/project_memory.py
Shared semantic memory index for all repos within a CogniRepo project.
Storage: ~/.cognirepo/projects/<org>/<project>/
"""
from __future__ import annotations
import os
from pathlib import Path

class ProjectMemory:
    def __init__(self, org: str, project: str):
        from config.orgs import get_shared_memory_path
        self._root: Path = get_shared_memory_path(org, project)
        self._root.mkdir(parents=True, exist_ok=True)
        from vector_db.local_vector_db import LocalVectorDB
        self._db = LocalVectorDB(dim=384, path=self._root)

    def store(self, text: str, source_repo: str, importance: float = 0.7) -> None:
        from memory.embeddings import get_embedding_model
        vec = get_embedding_model().encode([text])[0]
        self._db.add(vec, text, importance=importance, source=source_repo)
        self._db.save()

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        from memory.embeddings import get_embedding_model
        vec = get_embedding_model().encode([query])[0]
        results = self._db.search(vec, k=top_k)
        for r in results:
            r.setdefault("scope", "project")
        return results

    @classmethod
    def for_current_repo(cls, repo_path: str = ".") -> "ProjectMemory | None":
        from config.orgs import get_repo_project
        result = get_repo_project(os.path.abspath(repo_path))
        if result is None:
            return None
        org, project = result
        return cls(org, project)
```

Note: `LocalVectorDB` may need an optional `path: Path = None` param added to `__init__`
to override the default `.cognirepo/vector_db/` path. If it currently reads path from a
global `config/paths.py` singleton, add `path` override param and use it when provided.

**Acceptance Criteria:**
```bash
python -c "
import tempfile
from pathlib import Path
import unittest.mock as mock

with tempfile.TemporaryDirectory() as tmp:
    with mock.patch('config.orgs.get_shared_memory_path', return_value=Path(tmp) / 'shared'):
        from memory.project_memory import ProjectMemory
        pm = ProjectMemory('testorg', 'testproj')
        pm.store('hello from repo_a', source_repo='repo_a')
        results = pm.search('hello')
        assert len(results) > 0, 'no results'
        assert 'repo_a' in str(results[0]), f'source missing: {results[0]}'
        assert results[0].get('scope') == 'project'
        print('PASS')
" 2>/dev/null || echo "Check LocalVectorDB path param support"
```

---

### TASK 3.3 — Hook `store_memory` into ProjectMemory

**Description:**
When `autosave_context=True` and the current repo belongs to a project, every `store_memory`
call should also write to the project shared index. Entirely best-effort — project store failure
must never break local store.

**Key Directions:**

`tools/store_memory.py` — after successful local FAISS store:
```python
# Existing: local store
result = semantic_memory.store(text)  # or equivalent local store call

# ADD: propagate to project shared memory (best-effort)
try:
    from cli.init_project import autosave_context_enabled
    from memory.project_memory import ProjectMemory
    if autosave_context_enabled():
        pm = ProjectMemory.for_current_repo()
        if pm is not None:
            import os
            pm.store(text, source_repo=os.path.basename(os.getcwd()), importance=0.7)
except Exception:
    pass  # never break local store
```

**Acceptance Criteria:**
```bash
# Setup
cognirepo org create testco 2>/dev/null || true
cognirepo org project create testco backend 2>/dev/null || true
cognirepo org project link testco backend . 2>/dev/null || true

# Store
cognirepo store-memory "project propagation acceptance test"

# Verify in project index
python -c "
from memory.project_memory import ProjectMemory
pm = ProjectMemory('testco', 'backend')
results = pm.search('project propagation acceptance test')
assert len(results) > 0, 'not in project store'
print('PASS')
" 2>/dev/null || echo "Requires org/project setup"
```

---

### TASK 3.4 — Update init wizard with org/project step

**Description:**
The org step in `run_wizard()` currently only asks for org name.
Extend it to also ask which project the repo belongs to within that org,
or to create a new project with a description.

**Key Directions:**

`cli/wizard.py` → org/project section (step 5):
```
_section(5, 5, "Organisation & Project", "Group repos for cross-service knowledge")

Q: "Join an organisation?" Y/N
  → if Y:
    [list existing orgs from list_orgs()]
    choice: existing | create new
    → if existing: select from numbered list
    → if new: _ask_text("Org name?")

Q: "Link to a project within this org?" Y/N
  → if Y:
    [list projects from list_projects(org)]
    choice: existing | create new
    → if existing: select from list
    → if new:
      project_name = _ask_text("Project name?")
      desc = _ask_text("Description? (optional, Enter to skip)")
      [call create_project(org, project_name, desc) immediately in wizard]
    return project_name
  → if N: project = None

wizard return dict: {..., "org": org_name_or_None, "project": project_name_or_None}
```

`cli/init_project.py` → `init_project()`:
- Accept `project: str | None = None` param
- After org linking: if project provided, call `link_repo_to_project(cwd, org, project)`
- Write `"project": project` to config.json via `_write_config()`

**Acceptance Criteria:**
- `cognirepo init --non-interactive` completes without error (project=None path)
- After interactive init with project selection: `config.json` contains `"project": "<name>"`
```bash
python -c "import json; c=json.load(open('.cognirepo/config.json')); assert 'project' in c; print('PASS')"
```

---

### TASK 3.5 — Add `org project` CLI subcommands

**Description:**
Expose project management as CLI commands. Users need `cognirepo org project create/list/link/unlink`.
Also enhance `cognirepo org list` to show the tree: org → projects → repos.

**Key Directions:**

`cli/main.py` — add under existing `org` subcommand group:
```
cognirepo org project create <org> <project> [--description "..."]
cognirepo org project list <org>
cognirepo org project link <org> <project> [path]     # default path = "."
cognirepo org project unlink <org> <project> [path]
```

Each dispatches to the corresponding function in `config/orgs.py`.

Enhance `cognirepo org list` output:
```
myco
  └─ backend          (2 repos)
  │    /path/to/api
  │    /path/to/auth
  └─ frontend         (1 repo)
       /path/to/webapp
```

Use `rich` if already imported; fallback to plain text with `└─` box-drawing chars.

**Acceptance Criteria:**
```bash
cognirepo org project create testco myproj --description "Test"
cognirepo org project list testco | grep -q "myproj" && echo PASS || echo FAIL
cognirepo org project link testco myproj .
cognirepo org list | grep -q "myproj" && echo PASS || echo FAIL
cognirepo org project unlink testco myproj .
```

---

## PHASE 4 — Cross-Repo Knowledge via MCP

---

### TASK 4.1 — Extend `retrieval/cross_repo.py` with project-scoped search

**Description:**
`CrossRepoRouter.query_org_memories()` queries ALL org repos — too broad.
Add `query_project_memories()` for project-scoped sibling search.
Add `get_context_summary()` so Claude can check available context before searching.

**Key Directions:**

`retrieval/cross_repo.py` → `CrossRepoRouter.__init__()`:
```python
def __init__(self, current_repo_path: str = "."):
    self._current = os.path.abspath(current_repo_path)
    self._org = get_repo_org(self._current)           # existing
    proj_result = get_repo_project(self._current)     # new import
    self._project = proj_result[1] if proj_result else None
```

New method `get_project_sibling_repos()`:
```python
def get_project_sibling_repos(self) -> list[str]:
    if not self._org or not self._project:
        return []
    all_repos = get_project_repos(self._org, self._project)
    return [r for r in all_repos if os.path.abspath(r) != self._current]
```

New method `query_project_memories()` — same pattern as existing `query_org_memories()`
but uses `get_project_sibling_repos()` and tags results with `"scope": "project"`:
```python
def query_project_memories(self, query: str, top_k: int = 5) -> list[dict]:
    siblings = self.get_project_sibling_repos()
    if not siblings:
        return []
    results = []
    original = get_cognirepo_dir()
    try:
        for repo_path in siblings:
            sibling_dir = os.path.join(repo_path, ".cognirepo")
            if not os.path.isdir(sibling_dir):
                continue
            set_cognirepo_dir(sibling_dir)
            try:
                from memory.semantic_memory import SemanticMemory
                hits = SemanticMemory().retrieve(query, top_k=top_k)
                for h in hits:
                    h["source_repo"] = os.path.basename(repo_path)
                    h["repo_path"] = repo_path
                    h["scope"] = "project"
                results.extend(hits)
            except Exception:
                continue
    finally:
        set_cognirepo_dir(original)
    results.sort(key=lambda r: r.get("similarity", 0), reverse=True)
    return results[:top_k]
```

New method `get_context_summary()`:
```python
def get_context_summary(self) -> dict:
    return {
        "org": self._org,
        "project": self._project,
        "current_repo": os.path.basename(self._current),
        "has_project_siblings": len(self.get_project_sibling_repos()) > 0,
        "project_sibling_repos": [os.path.basename(r) for r in self.get_project_sibling_repos()],
        "org_sibling_repos": [os.path.basename(r) for r in self.get_sibling_repos()],
    }
```

**Acceptance Criteria:**
```bash
python -c "
from retrieval.cross_repo import CrossRepoRouter
router = CrossRepoRouter('.')
summary = router.get_context_summary()
assert 'org' in summary
assert 'project' in summary
assert 'has_project_siblings' in summary
assert 'current_repo' in summary
print('PASS')
print(summary)
"
```

---

### TASK 4.2 — Add `cross_repo_search` and `list_org_context` MCP tools

**Description:**
Two new MCP tools that expose cross-repo knowledge to Claude.
Tool docstrings serve as routing hints — Claude reads them and decides when to call.
No hardcoded routing. Pure Claude judgment via well-written tool descriptions.

**Key Directions:**

`server/mcp_server.py` — add two tools using same `_tool_gate` pattern as existing tools:

```python
@mcp.tool()
def cross_repo_search(query: str, scope: str = "project") -> dict:
    """
    Search knowledge from sibling repositories in the same org/project.

    scope="project" — repos in same PROJECT only (recommended, high relevance).
                      Call when: symbol not found locally, question spans services,
                      user asks how X works across the system, need context from
                      a related service you're importing from.

    scope="org"     — ALL repos in organization (broad). Call when: project search
                      returned empty, or question is org-wide / shared infrastructure.

    Call list_org_context() FIRST to verify siblings exist before calling this.
    Returns empty results list (not an error) if repo has no org/project.
    """
    with _tool_gate("cross_repo_search"):
        from retrieval.cross_repo import CrossRepoRouter
        router = CrossRepoRouter(current_repo_path=str(get_cognirepo_dir().parent))
        if scope == "project":
            results = router.query_project_memories(query, top_k=5)
            searched = router.get_project_sibling_repos()
        else:
            results = router.query_org_memories(query, top_k=5)
            searched = router.get_sibling_repos()
        return {
            "scope": scope,
            "query": query,
            "results": results,
            "result_count": len(results),
            "repos_searched": [os.path.basename(r) for r in searched],
        }


@mcp.tool()
def list_org_context() -> dict:
    """
    Returns org/project membership and sibling repos for the current repository.

    Call this FIRST when user asks about:
    - Other services, related repos, or cross-service behavior
    - How something works across the system
    - Architecture spanning multiple codebases

    Use the result to decide whether cross_repo_search() is worthwhile.
    If has_project_siblings=false and org_sibling_repos=[], no cross-repo context exists.
    """
    with _tool_gate("list_org_context"):
        from retrieval.cross_repo import CrossRepoRouter
        router = CrossRepoRouter(current_repo_path=str(get_cognirepo_dir().parent))
        return router.get_context_summary()
```

Also rename `org_search` → `org_wide_search` with backward-compat alias:
```python
@mcp.tool()
def org_wide_search(query: str, top_k: int = 5) -> dict:
    """Org-wide search (all repos in org). Prefer cross_repo_search with scope='org'."""
    ...

org_search = org_wide_search  # backward compat
```

**Acceptance Criteria:**
```bash
# Regenerate manifest after adding tools
python -c "
from server.mcp_server import mcp
# Check tools registered
tool_names = [t.name for t in mcp._tool_manager.list_tools()]
assert 'cross_repo_search' in tool_names, f'missing, got: {tool_names}'
assert 'list_org_context' in tool_names
print('PASS: both MCP tools registered')
" 2>/dev/null || echo "Check FastMCP tool introspection API"

# Functional (no siblings needed — should return valid empty structure)
cognirepo serve &
sleep 1
python -c "
import asyncio
async def test():
    # Direct function call (bypasses MCP transport for unit test)
    from server.mcp_server import list_org_context, cross_repo_search
    ctx = await list_org_context()
    assert 'org' in ctx and 'has_project_siblings' in ctx
    res = await cross_repo_search('test', scope='project')
    assert 'results' in res and 'scope' in res
    print('PASS')
asyncio.run(test())
" && kill %1 2>/dev/null
```

---

## PHASE 5 — Final Wiring & Validation

---

### TASK 5.1 — Update docs to reflect all changes

**Description:**
Update `docs/MCP_TOOLS.md` with new tools. Update `ARCHITECTURE.md` with new components.

**Key Directions:**

`docs/MCP_TOOLS.md`:
- Add entries for `cross_repo_search` and `list_org_context` (description, params, when to use, example return)
- Mark `org_search` as deprecated alias for `org_wide_search`
- Update tool count in header (was 14–15, now 17)

`ARCHITECTURE.md`:
- Add to component table: `vector_db/factory.py` → "Selects FAISS or ChromaDB via config"
- Add to component table: `memory/project_memory.py` → "Shared FAISS index per org/project"
- Update org section: show org → project → repos hierarchy
- Remove `api/` component row
- Add data flow: `store_memory → [local FAISS] + [ProjectMemory if autosave_context]`

**Acceptance Criteria:**
```bash
grep -q "cross_repo_search" docs/MCP_TOOLS.md && echo PASS || echo FAIL
grep -q "list_org_context" docs/MCP_TOOLS.md && echo PASS || echo FAIL
grep -q "project_memory" ARCHITECTURE.md && echo PASS || echo FAIL
grep -q "api/" ARCHITECTURE.md && echo FAIL || echo PASS
```

---

### TASK 5.2 — Run full test suite, fix regressions

**Description:**
Run all 63 tests. Fix failures caused by: LocalVectorDB path param, orgs schema migration,
BehaviourTracker signature change, config schema change (`models` → `model`).

**Key Directions:**
```bash
pytest tests/ -x -q 2>&1 | head -40
```

Expected failures to fix:
- `ImportError: cannot import vector_db.faiss_adapter` → update test imports to `local_vector_db`
- `KeyError: models` in classifier/router tests → update to use `config["model"]`; add compat shim
- `TypeError: BehaviourTracker.__init__() got unexpected keyword` → add `db_adapter=None` default
- `AssertionError` in orgs tests → update for new schema, old flat schema auto-migrates

Do NOT lower `fail_under` coverage threshold. Fix tests, don't delete them.

**Acceptance Criteria:**
```bash
pytest tests/ -q --tb=no 2>&1 | tail -5
# Must show: "X passed" with 0 errors
# Skips are acceptable
# No ImportError for deleted modules
```

---

### TASK 5.3 — `cognirepo doctor` passes on updated config

**Description:**
`cognirepo doctor` validates config schema. Update it to accept the new simplified schema
without false-positive failures on removed keys or the new `model` key.

**Key Directions:**
- Find all `config["models"]` or `config.get("models")` references in doctor checks
- Update to: `config.get("model") or config.get("models")` (graceful both-schema)
- Find checks for `api_port` → remove or make optional
- Ensure `storage.vector_backend` is accepted as a valid config key

**Acceptance Criteria:**
```bash
cognirepo doctor
echo "Exit: $?"  # must be 0
cognirepo doctor | grep -i "fail\|error\|missing" | grep -iv "optional" && echo WARN || echo PASS
```

---

## EXECUTION CHECKLIST

```
Phase 1 — Dead Code & Phantom REST
  [x] 1.1  Delete orphaned files (myapp/, faiss_adapter.py, cli/*.md)
  [x] 1.2  Strip REST API from docs (README, USAGE, ARCHITECTURE, docker-compose)
  [x] 1.3  Strip phantom config keys; simplify to single model + vector_backend
  [x] 1.4  Simplify init wizard: 7 steps → 5 steps

Phase 2 — ChromaDB Properly Wired
  [ ] 2.1  Create vector_db/factory.py
  [ ] 2.2  Wire factory into memory/semantic_memory.py
  [ ] 2.3  Extend chroma_adapter + local_vector_db with behaviour scoring
  [ ] 2.4  Wire behaviour feedback into vector store

Phase 3 — Org → Project Hierarchy
  [ ] 3.1  Migrate config/orgs.py to project-aware schema (backward compat)
  [ ] 3.2  Create memory/project_memory.py (shared project FAISS index)
  [ ] 3.3  Hook store_memory into ProjectMemory (best-effort propagation)
  [ ] 3.4  Update init wizard with org/project step
  [ ] 3.5  Add org project CLI subcommands

Phase 4 — Cross-Repo MCP
  [ ] 4.1  Extend cross_repo.py: query_project_memories + get_context_summary
  [ ] 4.2  Add cross_repo_search + list_org_context MCP tools

Phase 5 — Final Wiring
  [ ] 5.1  Update docs (MCP_TOOLS.md + ARCHITECTURE.md)
  [ ] 5.2  Run full test suite, fix regressions
  [ ] 5.3  cognirepo doctor passes with exit code 0
```
