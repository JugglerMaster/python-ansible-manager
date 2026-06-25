from pathlib import Path

import yaml

from ansiblecli.config import get as get_config


def discover_projects():
    playbooks_dir = Path(get_config("playbooks_dir"))
    if not playbooks_dir.exists():
        return []

    projects = []
    for child in sorted(playbooks_dir.iterdir()):
        if not child.is_dir():
            continue
        playbooks = sorted(child.glob("*.yml")) + sorted(child.glob("*.yaml"))
        if not playbooks:
            continue

        description = None
        try:
            with open(playbooks[0]) as f:
                data = yaml.safe_load(f)
            if isinstance(data, list) and len(data) > 0:
                desc = data[0].get("description") or data[0].get("name")
                if desc:
                    description = str(desc)
        except Exception:
            pass

        projects.append({
            "name": child.name,
            "path": str(child),
            "playbooks": sorted(str(p) for p in playbooks),
            "description": description or child.name,
        })

    return projects


def get_project(name):
    projects = discover_projects()
    for p in projects:
        if p["name"] == name:
            return p
    return None
