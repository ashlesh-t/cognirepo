"""
Module to initialize the cognirepo project structure.
"""
import json
import os
import bcrypt


DEFAULT_PASSWORD = "changeme"
DEFAULT_PORT = 8000
CONFIG_FILE = ".cognirepo/config.json"

DEFAULT_MODELS = {
    "FAST":     {"provider": "gemini",    "model": "gemini-2.0-flash"},
    "BALANCED": {"provider": "gemini",    "model": "gemini-2.0-flash"},
    "DEEP":     {"provider": "anthropic", "model": "claude-sonnet-4-6"},
}


def init_project(password: str = DEFAULT_PASSWORD, port: int = DEFAULT_PORT) -> None:
    """
    Scaffold .cognirepo/ directories and write config.json with a bcrypt-hashed
    password, api_port, and api_url.  Safe to re-run — existing config is preserved.
    """
    os.makedirs(".cognirepo/memory", exist_ok=True)
    os.makedirs(".cognirepo/docs", exist_ok=True)
    os.makedirs(".cognirepo/index", exist_ok=True)
    os.makedirs(".cognirepo/graph", exist_ok=True)
    os.makedirs("vector_db", exist_ok=True)

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
        # Config exists — backfill any missing keys without touching password_hash.
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

        changed = False
        if "api_port" not in config:
            config["api_port"] = port
            changed = True
        if "api_url" not in config:
            config["api_url"] = f"http://localhost:{config['api_port']}"
            changed = True
        if "retrieval_weights" not in config:
            config["retrieval_weights"] = {"vector": 0.5, "graph": 0.3, "behaviour": 0.2}
            changed = True
        if "models" not in config:
            config["models"] = DEFAULT_MODELS
            changed = True

        if changed:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            print(f"Updated {CONFIG_FILE} with api_port / api_url.")
        else:
            print(f"{CONFIG_FILE} already up to date.")

    print("Cognirepo initialised.")
