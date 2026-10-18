"""#186 — every store path is classified, and the newly covered stores round-trip encrypted."""
import json
import re
from pathlib import Path

import pytest

from core.security.coverage import STORE_COVERAGE

ROOT = Path(__file__).resolve().parent.parent
_PATH_RE = re.compile(r'get_path\(\s*f?"([^"{]+)"')


def test_every_get_path_literal_is_classified():
    seen: set[str] = set()
    for py in ROOT.rglob("*.py"):
        rel = py.relative_to(ROOT).parts
        if rel[0] in ("tests", ".venv", "venv", "node_modules", "build", "dist") or ".git" in rel:
            continue
        seen.update(_PATH_RE.findall(py.read_text(encoding="utf-8", errors="ignore")))
    missing = sorted(seen - set(STORE_COVERAGE))
    assert not missing, (
        f"unclassified store path(s) {missing}: add them to core/security/coverage.py "
        "(encrypted / not_encrypted / no_content) and update SECURITY.md")


def test_security_md_lists_every_unencrypted_store():
    doc = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    for key, (status, _) in STORE_COVERAGE.items():
        if status == "not_encrypted" and key.startswith(("vector_db/chroma", "index/ast_index")):
            assert key.split("/")[-1].split(".")[0] in doc


@pytest.fixture
def enc_repo(isolated_cognirepo, monkeypatch):
    """The autouse isolated repo with ``storage.encrypt`` switched on and an in-memory keychain."""
    fernet = pytest.importorskip("cryptography.fernet")
    from core.security import encryption
    keys: dict = {}
    monkeypatch.setattr(encryption, "get_or_create_key",
                        lambda pid: keys.setdefault(pid, fernet.Fernet.generate_key()))
    cfg_path = isolated_cognirepo / ".cognirepo" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["storage"]["encrypt"] = True
    cfg_path.write_text(json.dumps(cfg))
    return isolated_cognirepo


def test_project_learnings_encrypted_and_roundtrip(enc_repo, monkeypatch):
    from data.memory.learning_store import ProjectLearningStore
    s = ProjectLearningStore(project_dir=str(enc_repo))
    rid = s.store_learning("decision", "secret learning text 186")
    raw = (enc_repo / ".cognirepo" / "learnings" / "learnings.json").read_bytes()
    assert b"secret learning text" not in raw and raw.startswith(b"gAAAAA")
    assert any(r["id"] == rid for r in s._backend._load())


def test_plaintext_learnings_migrate_on_next_save(enc_repo):
    from data.memory.learning_store import ProjectLearningStore
    d = enc_repo / ".cognirepo" / "learnings"
    d.mkdir(exist_ok=True)
    (d / "learnings.json").write_text(json.dumps([{"id": "a", "type": "decision", "scope": "project",
                                                   "text": "legacy plain", "timestamp": "x"}]))
    s = ProjectLearningStore(project_dir=str(enc_repo))
    assert s._backend._load()[0]["id"] == "a"          # plaintext still readable
    s.store_learning("decision", "new one")
    assert (d / "learnings.json").read_bytes().startswith(b"gAAAAA")
    assert {r["id"] for r in s._backend._load()} >= {"a"}


def test_locked_ciphertext_is_never_quarantined_or_overwritten(enc_repo, monkeypatch):
    from core.config.safe_read import StoreUnreadableError
    from data.memory.learning_store import ProjectLearningStore
    s = ProjectLearningStore(project_dir=str(enc_repo))
    s.store_learning("decision", "keep me")
    path = enc_repo / ".cognirepo" / "learnings" / "learnings.json"
    before = path.read_bytes()
    monkeypatch.setattr("core.security.encryption.decrypt_bytes",
                        lambda *_: (_ for _ in ()).throw(ValueError("wrong key")))
    with pytest.raises(StoreUnreadableError) as ei:
        s.store_learning("decision", "should not overwrite")
    assert ei.value.locked
    assert path.read_bytes() == before
    assert not list(path.parent.glob("learnings.json.corrupt-*"))


def test_decrypt_after_disabling_flag_still_reads(enc_repo):
    from data.memory.learning_store import ProjectLearningStore
    s = ProjectLearningStore(project_dir=str(enc_repo))
    s.store_learning("decision", "written encrypted")
    cfg_path = enc_repo / ".cognirepo" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["storage"]["encrypt"] = False
    cfg_path.write_text(json.dumps(cfg))
    assert s._backend._load()[0]["text"] == "written encrypted"


def test_project_memory_metadata_encrypted_and_roundtrip(enc_repo, tmp_path):
    from data.memory.project_memory import _ProjectLocalVectorDB
    base = tmp_path / "pm"
    (base / "vector_db").mkdir(parents=True)
    (base / "memory").mkdir(parents=True)
    db = _ProjectLocalVectorDB(base=base, key_id="cognirepo-project-memory:o/p")
    db.add([0.1] * 384, "shared secret memory 186", importance=0.5, source="repoA")
    raw = (base / "memory" / "semantic_metadata.json").read_bytes()
    assert b"shared secret memory" not in raw and raw.startswith(b"gAAAAA")
    # a fresh handle (another repo / process) reads it back through the same keychain entry
    again = _ProjectLocalVectorDB(base=base, key_id="cognirepo-project-memory:o/p")
    assert again.metadata[0]["text"] == "shared secret memory 186"


def test_global_learnings_use_shared_key_not_repo_key(enc_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "g"))
    from data.memory.learning_store import GlobalLearningStore
    g = GlobalLearningStore()
    g.store_learning("preference", "global secret 186")
    raw = (tmp_path / "g" / "learnings" / "learnings.json").read_bytes()
    assert raw.startswith(b"gAAAAA")
    assert g._backend._key_id == "cognirepo-global-learnings"


def test_migrate_encrypts_then_decrypts_with_verification(enc_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "g"))
    from core.security.migrate import migrate
    d = enc_repo / ".cognirepo" / "learnings"
    d.mkdir(exist_ok=True)
    plain = json.dumps([{"id": "a", "text": "plain before migrate"}]).encode()
    (d / "learnings.json").write_bytes(plain)

    dry = migrate(dry_run=True)
    assert any(r.action == "encrypted" for r in dry)
    assert (d / "learnings.json").read_bytes() == plain          # dry run touched nothing

    res = migrate()
    assert [r.action for r in res if r.path.endswith("learnings.json")] == ["encrypted"]
    assert (d / "learnings.json").read_bytes().startswith(b"gAAAAA")
    assert [r.action for r in migrate()] == ["unchanged"]         # idempotent

    back = migrate(decrypt=True)
    assert back[0].action == "decrypted"
    assert (d / "learnings.json").read_bytes() == plain           # byte-identical round trip


def test_migrate_leaves_file_untouched_when_key_unavailable(enc_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "g"))
    from core.security.migrate import migrate
    from data.memory.learning_store import ProjectLearningStore
    ProjectLearningStore(project_dir=str(enc_repo)).store_learning("decision", "x")
    path = enc_repo / ".cognirepo" / "learnings" / "learnings.json"
    before = path.read_bytes()
    monkeypatch.setattr("core.security.encryption.decrypt_bytes",
                        lambda *_: (_ for _ in ()).throw(ValueError("no key")))
    res = migrate(decrypt=True)
    assert res[0].action == "skipped"
    assert path.read_bytes() == before
