# AnsibleCLI — AI Agent Notes

## Architecture

- **Python + Typer** — type-hint CLI, auto-help, Rich for output, questionary for prompts
- **SQLite (stdlib)** — run history, last-config per project, known hosts
- **prompt_toolkit** — custom project picker with pagination, search, sort (via questionary dep)

## Project Structure

```
ansiblecli/package/          # Python package
  cli.py                     # Typer app, commands, entry point
  interactive.py             # Main menu, picker orchestration, settings/inventory menus
  picker.py                  # ProjectPicker (prompt_toolkit based, paginated, searchable)
  database.py                # SQLite schema, queries, migration
  runner.py                  # subprocess.Popen wrapper for ansible-playbook (live streaming)
  discover.py                # Filesystem scan for playbook projects
  config.py                  # ~/.ansiblecli/config.json
  inventory.py               # inventory/hosts.yml generation + host CRUD
playbooks/                   # Auto-discovered: subdirs or standalone .yml files
playfiles/<project>/         # Supporting files (templates, scripts, etc.)
inventory/hosts.yml          # Auto-generated, passed as -i
```

## Conventions

- `playbooks/` subdir or standalone `.yml` = project. Uses `rglob` for nested playbooks.
- `playfiles/<project>/` = supporting files (not scanned, not managed)
- `inventory/hosts.yml` is auto-generated — do not edit manually
- DB at `~/.ansiblecli/ansiblecli.db`

## Database

| Table | Key Columns |
|---|---|
| `run_history` | id, project, playbook_path, host, check_mode, tags, extra_vars, status, exit_code, output, started_at, finished_at, recap |
| `last_config` | project (PK), host, check_mode, tags, extra_vars |
| `known_hosts` | hostname (PK), address, inventory_group, os_type |

`init_db()` + `migrate_schema()` run on startup — handles schema drift (e.g. `recap` column added via ALTER TABLE).

## CLI Commands

| Command | Purpose |
|---|---|
| `ansiblecli` | Interactive wizard |
| `ansiblecli init` | Create config + DB + directories |
| `ansiblecli list` | List discovered projects |
| `ansiblecli run <project>` | Run with last config or prompts |
| `ansiblecli history [project]` | Show run history |
| `ansiblecli config [key] [val]` | View/set config |
| `ansiblecli inventory list\|add\|remove\|show\|groups` | Host management |

## Interactive Flow

```
ansiblecli → Main menu (Run / Inventory / History / Settings / Quit)
  Run → pick_project() → pick_playbook()
    Picker hotkeys: ↑↓ nav, ←→ page, s sort, / search, Enter run, c settings, h history, v view, Esc back
    Run → live ansible-playbook stream → result panel → back to picker
    View → YAML in pager (less) with syntax highlighting + help bar
    History → table with host results recap column
    Settings → run settings prompts (host, check, tags, extra vars)
  Inventory → CRUD hosts + list groups
  History → pick project filter → table with recap + duration
  Settings → Clear run history (with confirmation)
```

- `show_history()` displays table with Date, Project, Host, Status, Host Results (parsed PLAY RECAP), Duration
- `parse_recap()` extracts `ok=N failed=N unreachable=N` from ansible output, stored in `recap` column
- Duration calculated from `started_at`/`finished_at` timestamps (captured before/after run)

## Key Implementation Details

- `runner.run_playbook()` uses `subprocess.Popen` with line-by-line stdout streaming + capture
- `_do_run()` captures `started_at` before, `finished_at` after playbook execution
- `add_run()` accepts optional `started_at`, `finished_at`, `recap` params
- Picker actions return `(project_dict, action_string)` — actions: `run`, `settings`, `history`, `view`
- `host=None` means run against all hosts (no `-l` flag); stored as `"__all__"` sentinel in prompts
- Settings menu items: Clear run history

## Launcher

`./ansiblecli.sh` auto-creates `.venv`, `pip install -e .`, delegates to entry point.

## Ansible Dependency

`ansible-playbook` must be on PATH at runtime (independent of venv). Options: `apt install ansible`, `brew install ansible`, or `pip install ansible` in/outside venv.
