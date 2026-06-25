import subprocess
import sys
from pathlib import Path

from ansiblecli.config import get


def run_playbook(playbook_path, host=None, check_mode=False, tags=None, extra_vars=None):
    inventory_dir = Path(get("inventory_dir"))
    inventory_file = inventory_dir / get("inventory_file")

    if not inventory_file.exists():
        print(f"Error: inventory file not found at {inventory_file}", file=sys.stderr)
        print("Run 'ansiblecli inventory list' or 'ansiblecli init' first.", file=sys.stderr)
        return None

    cmd = ["ansible-playbook", str(playbook_path), "-i", str(inventory_file)]

    if host:
        cmd.extend(["-l", host])

    if check_mode:
        cmd.append("--check")

    if tags:
        cmd.extend(["-t", tags])

    if extra_vars:
        for ev in extra_vars.split(","):
            ev = ev.strip()
            if "=" in ev:
                cmd.extend(["-e", ev])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result
    except FileNotFoundError:
        print("Error: 'ansible-playbook' not found. Is Ansible installed?", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error running ansible-playbook: {e}", file=sys.stderr)
        return None
