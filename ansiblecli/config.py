import json
from pathlib import Path

APP_DIR = Path.home() / ".ansiblecli"
CONFIG_FILE = APP_DIR / "config.json"


DEFAULT_CONFIG = {
    "playbooks_dir": str(Path.cwd() / "playbooks"),
    "playfiles_dir": str(Path.cwd() / "playfiles"),
    "inventory_dir": str(Path.cwd() / "inventory"),
    "inventory_file": "hosts.yml",
}


def load_config():
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(config):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get(key):
    return load_config().get(key, DEFAULT_CONFIG.get(key))


def set_key(key, value):
    config = load_config()
    config[key] = value
    save_config(config)
