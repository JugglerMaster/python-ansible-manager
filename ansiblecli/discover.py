import os
from pathlib import Path

import yaml

from ansiblecli.config import get as get_config


def _parse_project_description(playbook_path):
    try:
        with open(playbook_path) as f:
            data = yaml.safe_load(f)
        if isinstance(data, list) and len(data) > 0:
            desc = data[0].get("description") or data[0].get("name")
            if desc:
                return str(desc)
    except Exception:
        pass
    return None


def discover_projects():
    playbooks_dir = Path(get_config("playbooks_dir"))
    if not playbooks_dir.exists():
        return []

    projects = []

    for child in sorted(playbooks_dir.iterdir()):
        if child.is_dir():
            playbooks = sorted(child.rglob("*.yml")) + sorted(child.rglob("*.yaml"))
            if not playbooks:
                continue
            description = _parse_project_description(playbooks[0])
            projects.append({
                "name": child.name,
                "path": str(child),
                "playbooks": sorted(str(p) for p in playbooks),
                "description": description or child.name,
                "mtime": max(os.path.getmtime(p) for p in playbooks),
            })
        elif child.suffix.lower() in (".yml", ".yaml"):
            name = child.stem
            description = _parse_project_description(child)
            projects.append({
                "name": name,
                "path": str(child.parent),
                "playbooks": [str(child)],
                "description": description or name,
                "mtime": os.path.getmtime(child),
            })

    return projects


def get_project(name):
    projects = discover_projects()
    for p in projects:
        if p["name"] == name:
            return p
    return None
