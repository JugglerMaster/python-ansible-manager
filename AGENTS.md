# AnsibleCLI — AI Agent Notes

## Project Overview

Interactive CLI tool for managing and running Ansible playbooks. Discovers playbooks from the filesystem, manages a central inventory, provides a guided interactive wizard, and tracks run history.

## Architecture Decisions

### 1. Python
**Why:** Ansible is written in Python, making integration natural. Rich ecosystem for CLI tools (Typer, Rich, questionary). Zero compilation step, easy to install.

### 2. Typer over Click
**Why:** Type-hint-based CLI framework reduces boilerplate. Auto-generates help text and validation. Built on Click so it's battle-tested and extensible.

### 3. questionary for interactivity
**Why:** The core UX is a guided wizard. questionary provides select, confirm, text, and checkbox prompts out of the box. Lightweight with no heavy dependencies.

### 4. Rich for display
**Why:** Tables, panels, markup, and colors make the interactive wizard feel polished. Used for run history display, inventory listing, and playbook viewing.

### 5. SQLite for tracking (stdlib)
**Why:** Zero external dependencies. Stores run history, last-used config per project, and known hosts. Database file lives at `~/.ansiblecli/ansiblecli.db`.

### 6. Filesystem-based playbook discovery
**Why:** Drop a folder in `playbooks/` and it's auto-detected. No registration step, no database sync. Each subdirectory = one project. Convention over configuration.

### 7. playbooks/ vs playfiles/ separation
**Why:** Clear distinction between runnable Ansible YAML (playbooks/) and supporting files like templates, scripts, configs (playfiles/). Only playbooks/ is scanned and tracked. playfiles/ is documented in README as a convention.

### 8. Central inventory/hosts.yml
**Why:** Single source of truth for targets. CLI generates a YAML inventory file and passes `-i` automatically on every `ansible-playbook` invocation. Users never point at an inventory file manually.

### 9. Interactive-first UX
**Why:** Running `ansiblecli` with no arguments launches a guided wizard. CLI flags exist for automation/scripting but the default path is hand-holding: select project, choose settings, run.

### 10. Last-config memory
**Why:** Per-project recall of last host, check mode, tags, and extra vars. Repeated runs are one-click: "Run with last config."

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
├── pyproject.toml
├── AGENTS.md
├── README.md
└── LICENSE
```

## Conventions

- Each subdirectory under `playbooks/` is a **project**
- A project can have one or more `.yml`/`.yaml` files; if multiple, the user picks at run time via the wizard
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

- To add a new playbook: create `playbooks/<project>/playbook.yml`
- To add supporting files: create `playfiles/<project>/`
- To add a host: `ansiblecli inventory add <hostname> --address <ip> --group <group>`
- To initialize on a new machine: `ansiblecli init`
- For CI/automation: `ansiblecli run <project> --host <host> --check`
