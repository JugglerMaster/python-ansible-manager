import json
import os
import stat
from pathlib import Path

APP_DIR = Path.home() / ".ansiblecli"
CONFIG_FILE = APP_DIR / "config.json"

# The config can hold SSH/become passwords — nobody else should read it.
CONFIG_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0600

DEFAULT_CONFIG = {
    "playbooks_dir": str(Path.cwd() / "playbooks"),
    "playfiles_dir": str(Path.cwd() / "playfiles"),
    "inventory_dir": str(Path.cwd() / "inventory"),
    "inventory_file": "hosts.yml",
    "machine_setup_script": "",
    "machine_setup_become_pass": "",
    "machine_setup_default_hostname": "",
    "become_password": "",
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
    # May hold SSH/become passwords — keep it owner-only.
    lock_down_config_file()


def lock_down_config_file():
    """Create the config file with owner-only permissions if it exists."""
    if CONFIG_FILE.exists():
        os.chmod(CONFIG_FILE, CONFIG_MODE)


def config_permissions():
    """Return the config file's permission bits, or None if it doesn't exist."""
    if not CONFIG_FILE.exists():
        return None
    return stat.S_IMODE(CONFIG_FILE.stat().st_mode)


def is_config_exposed():
    """True when users other than the owner can read the config file."""
    mode = config_permissions()
    return mode is not None and bool(mode & (stat.S_IRWXG | stat.S_IRWXO))


def get(key):
    return load_config().get(key, DEFAULT_CONFIG.get(key))


def set_key(key, value):
    config = load_config()
    config[key] = value
    save_config(config)
