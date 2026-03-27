"""
Module to initialize the cognirepo project structure.
"""
import json
import os
import bcrypt


DEFAULT_PASSWORD = "changeme"
DEFAULT_PORT = 8000
CONFIG_FILE = ".cognirepo/config.json"
GITIGNORE_FILE = ".cognirepo/.gitignore"

GITIGNORE_CONTENT = """\
# CogniRepo — auto-generated, do not commit data files
*.index
*.pkl
episodic.json
config.json
sessions/
archive/
"""

DEFAULT_MODELS = {
    "FAST":     {"provider": "gemini",    "model": "gemini-2.0-flash"},
    "BALANCED": {"provider": "gemini",    "model": "gemini-2.0-flash"},
    "DEEP":     {"provider": "anthropic", "model": "claude-sonnet-4-6"},
}


def _write_gitignore() -> None:
    """Write .cognirepo/.gitignore if it doesn't already exist."""
    if not os.path.exists(GITIGNORE_FILE):
        with open(GITIGNORE_FILE, "w", encoding="utf-8") as f:
            f.write(GITIGNORE_CONTENT)


def _scaffold_dirs() -> None:
    os.makedirs(".cognirepo/memory", exist_ok=True)
    os.makedirs(".cognirepo/docs", exist_ok=True)
    os.makedirs(".cognirepo/index", exist_ok=True)
    os.makedirs(".cognirepo/graph", exist_ok=True)
    os.makedirs("vector_db", exist_ok=True)


def _write_config(password: str, port: int) -> None:
    """Write config.json (new) or backfill missing keys (existing)."""
    if not os.path.exists(CONFIG_FILE):
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        config = {
            "password_hash": pw_hash,
            "api_port": port,
            "api_url": f"http://localhost:{port}",
            "retrieval_weights": {"vector": 0.5, "graph": 0.3, "behaviour": 0.2},
            "models": DEFAULT_MODELS,
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"Created {CONFIG_FILE}")
        print(f"  api_url  : http://localhost:{port}")
        print(f"  password : {password}  ← change before production use")
    else:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

        changed = False
        for key, val in [
            ("api_port", port),
            ("api_url", f"http://localhost:{config.get('api_port', port)}"),
            ("retrieval_weights", {"vector": 0.5, "graph": 0.3, "behaviour": 0.2}),
            ("models", DEFAULT_MODELS),
        ]:
            if key not in config:
                config[key] = val
                changed = True

        if changed:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            print(f"Updated {CONFIG_FILE} with missing keys.")
        else:
            print(f"{CONFIG_FILE} already up to date.")


def init_project(
    password: str = DEFAULT_PASSWORD,
    port: int = DEFAULT_PORT,
    no_index: bool = False,
):
    """
    Scaffold .cognirepo/ directories, write config.json, write .gitignore.
    Safe to re-run — existing config is preserved.

    If no_index is False (default), prompt the user to index the repo now.
    Returns (summary_dict, kg, indexer) if indexing was performed,
    otherwise (None, None, None).
    """
    _scaffold_dirs()
    _write_config(password, port)
    _write_gitignore()

    print(
        "\nCogniRepo initialised.\n"
    )

    if no_index:
        return None, None, None

    print(
        "Index this repo now? It maps every function and class so AI tools\n"
        "can look up symbols and understand code structure.\n"
        "This takes ~5 seconds for most projects. (Y/n): ",
        end="",
        flush=True,
    )

    try:
        answer = input().strip().lower()
    except EOFError:
        answer = ""  # non-interactive environment → default yes

    if answer in ("n", "no"):
        print("Run 'cognirepo index-repo .' when ready.")
        return None, None, None

    from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
    from indexer.ast_indexer import ASTIndexer        # pylint: disable=import-outside-toplevel

    cwd = os.getcwd()
    kg = KnowledgeGraph()
    indexer = ASTIndexer(graph=kg)
    summary = indexer.index_repo(cwd)
    kg.save()

    # seed behaviour from git history
    try:
        from cli.seed import seed_from_git_log  # pylint: disable=import-outside-toplevel
        seed_from_git_log(repo_root=cwd, indexer=indexer)
    except Exception:  # pylint: disable=broad-except
        pass  # seeding is best-effort

    return summary, kg, indexer
