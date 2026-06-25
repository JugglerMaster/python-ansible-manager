# AnsibleCLI — AI Agent Notes

## Architecture Decisions

1. **Python** — Ansible is Python, integration natural. Rich CLI ecosystem.
2. **Typer over Click** — Type-hint CLI, less boilerplate, auto-help.
3. **questionary** — select/confirm/text prompts for guided wizard UX.
4. **Rich** — Tables, panels, colors for polished terminal output.
5. **SQLite (stdlib)** — Zero deps, tracks history + last-config + hosts.
6. **Filesystem discovery** — Drop a folder in `playbooks/`, auto-detected.
7. **playbooks/ vs playfiles/** — Runnable YAML vs supporting files. Only playbooks/ is scanned.
8. **Central inventory/hosts.yml** — CLI generates YAML inventory, auto-injects `-i` on every run.
9. **Interactive-first UX** — `ansiblecli` with no args = guided wizard.
10. **Last-config memory** — Per-project recall of last host, check mode, tags, extra vars.

## Project Structure

```
ansiblecli/
├── ansiblecli/                     # Python package
│   ├── __init__.py
│   ├── __main__.py                 # python -m ansiblecli
│   ├── cli.py                      # Typer app, all commands, interactive entry point
│   ├── config.py                   # ~/.ansiblecli/config.json read/write
│   ├── database.py                 # SQLite schema and query functions
│   ├── discover.py                 # Scan playbooks/ for projects
│   ├── interactive.py              # questionary prompts + Rich display
│   ├── inventory.py                # Host/group CRUD + inventory YAML generation
│   └── runner.py                   # subprocess wrapper for ansible-playbook
├── playbooks/                      # Auto-discovered playbook projects
│   └── <project-name>/
│       └── playbook.yml
├── playfiles/                      # Supporting files (templates, scripts, configs)
│   └── <project-name>/
│       ├── files/
│       └── templates/
├── inventory/                      # Managed inventory (auto-generated)
│   └── hosts.yml
├── ansiblecli.sh                    # Unix launcher — auto-creates .venv, installs, runs
├── pyproject.toml
├── AGENTS.md
├── README.md
└── LICENSE
```

## Conventions

- Each subdirectory under `playbooks/` is a **project**
- Standalone `.yml`/`.yaml` files at `playbooks/` root are also treated as projects (name = filename without extension)
- Projects can have playbooks in subdirectories — uses `rglob` so `tasks/main.yml`, `handlers/` etc. are found
- Supporting files go in `playfiles/<project>/` (not managed by the tool)
- The inventory file at `inventory/hosts.yml` is auto-generated — do not edit manually
- Known hosts are managed via `ansiblecli inventory` commands or the interactive wizard
- Run history and last-config are stored in `~/.ansiblecli/ansiblecli.db`

## Database Schema (`~/.ansiblecli/ansiblecli.db`)

### run_history
Logs every execution. Columns: id, project, playbook_path, host, check_mode, tags, extra_vars, status (success/failed/cancelled), exit_code, output (truncated to 5000 chars), started_at, finished_at.

### last_config
Per-project last-used settings. Columns: project (PK), host, check_mode, tags, extra_vars, updated_at. Used for "Run with last config" shortcut.

### known_hosts
Inventory hosts. Columns: hostname (PK), address, inventory_group, os_type, last_used. Managed through inventory commands.

## CLI Commands

| Command | Purpose |
|---|---|
| `ansiblecli` | Launch interactive wizard |
| `ansiblecli init` | Create ~/.ansiblecli/ + DB + directories |
| `ansiblecli list` | List discovered projects |
| `ansiblecli run <project>` | Run with last config or specified flags |
| `ansiblecli history [project]` | Show run history |
| `ansiblecli config [key] [val]` | View/set configuration |
| `ansiblecli inventory list` | List known hosts |
| `ansiblecli inventory add <hostname>` | Add a host |
| `ansiblecli inventory remove <hostname>` | Remove a host |
| `ansiblecli inventory show` | Display generated inventory YAML |
| `ansiblecli inventory groups` | List inventory groups |

## Interactive Wizard Flow

```
ansiblecli
  → Main menu: Run / Manage Inventory / History / Quit
  → Select project (from playbooks/ scan)
  → If multiple playbooks: pick one
  → Project menu: Run with last config / Change settings / History / View / Back
  → Settings: host, check mode, tags, extra vars, save-as-default
  → Execute ansible-playbook -i inventory/hosts.yml
  → Show result (exit code, output)
  → Prompt: run again?

  Inventory sub-menu: List / Add / Remove / Groups / Back
```

## Inventory Format

Generated YAML at `inventory/hosts.yml`:

```yaml
all:
  hosts:
    new-pc:
      ansible_host: 192.168.1.100
  children:
    webservers:
      hosts:
        web-01: {}
```

Auto-passed to ansible-playbook via `-i inventory/hosts.yml`.

## Common Patterns

- To add a new playbook: create `playbooks/<project>/playbook.yml` or just drop a `.yml` file in `playbooks/`
- To add supporting files: create `playfiles/<project>/`
- To add a host: `ansiblecli inventory add <hostname> --address <ip> --group <group>`
- To initialize on a new machine: `ansiblecli init`
- For CI/automation: `ansiblecli run <project> --host <host> --check`

## Launcher Script

`ansiblecli.sh` at the repo root auto-bootstraps the virtual environment:

1. Checks if `.venv/` exists; if not, creates it and runs `pip install -e .`
2. Delegates to the venv's `ansiblecli` entry point with all arguments forwarded

Usage: `./ansiblecli.sh` (first run creates venv, subsequent runs are instant)

This avoids manual venv activation. On Windows, use WSL with this script or manually activate `.venv\Scripts\activate` then `ansiblecli`.

## Important Note: Ansible Dependency

`ansiblecli` calls `ansible-playbook` via subprocess. The `ansible-playbook` binary must be on the system PATH at runtime. This is independent of whether ansiblecli itself is installed in a virtual environment. Options:

- Install Ansible system-wide: `apt install ansible` (Linux), `brew install ansible` (macOS), or `pip install ansible` (anywhere on PATH)
- Install Ansible inside the same venv: `pip install ansible` after activating the venv
- If deploying via CI/CD, ensure `ansible-playbook` is available in the runner environment

Without `ansible-playbook` on PATH, `ansiblecli run` will fail with a clear error message.
