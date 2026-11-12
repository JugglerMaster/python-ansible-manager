"""Shared fixtures.

Every test runs against a throwaway home/config/DB so real ~/.ansiblecli data
is never touched.
"""

import pytest

from ansiblecli import config, database


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Point APP_DIR, config.json, the SQLite DB and the project dirs at tmp_path."""
    app_dir = tmp_path / ".ansiblecli"
    app_dir.mkdir()
    playbooks_dir = tmp_path / "playbooks"
    playbooks_dir.mkdir()
    playfiles_dir = tmp_path / "playfiles"
    playfiles_dir.mkdir()
    inventory_dir = tmp_path / "inventory"

    monkeypatch.setattr(config, "APP_DIR", app_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", app_dir / "config.json")
    monkeypatch.setattr(config, "DEFAULT_CONFIG", {
        **config.DEFAULT_CONFIG,
        "playbooks_dir": str(playbooks_dir),
        "playfiles_dir": str(playfiles_dir),
        "inventory_dir": str(inventory_dir),
    })
    monkeypatch.setattr(database, "DB_FILE", app_dir / "ansiblecli.db")

    # cli.py binds these at import time, so patch the module attribute too.
    import ansiblecli.cli as cli_module
    monkeypatch.setattr(cli_module, "APP_DIR", app_dir)

    database.init_db()

    class Env:
        def __init__(self):
            self.app_dir = app_dir
            self.playbooks = playbooks_dir
            self.playfiles = playfiles_dir
            self.inventory = inventory_dir
            self.hosts_file = inventory_dir / config.DEFAULT_CONFIG["inventory_file"]

        def write_playbook(self, name, body="- hosts: all\n  tasks: []\n"):
            """Create a playbook; 'sub/project/x.yml' becomes a project dir."""
            path = playbooks_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
            return path

    return Env()


@pytest.fixture
def projects(isolated_env):
    """Three projects: one directory project, two standalone playbooks."""
    isolated_env.write_playbook("alpha/playbook.yml")
    isolated_env.write_playbook("beta.yml")
    isolated_env.write_playbook("gamma/main.yaml")
    return isolated_env
