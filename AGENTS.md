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
tests/                       # pytest suite (isolated fixtures in tests/conftest.py)
scripts/bump_version.py      # Version bump helper (only place versions change)
Makefile                     # install / test / lint / check / bump / release
acli.sh                      # Dev launcher (NOT ansiblecli.sh — avoids tab-completion clash)
.github/workflows/           # CI (ruff+pytest) + release (build/publish on v* tags)
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
ansiblecli → Main menu (Run / Inventory / Machine Setup / History / Settings / Quit)
  Run → pick_project() → pick_playbook()
    Picker hotkeys: ↑↓ nav, ←→ page, s sort, / search, Enter run, c settings, h history, v view, Esc back
    Run → live ansible-playbook stream → result panel → back to picker
    View → YAML in pager (less) with syntax highlighting + help bar
    History → table with host results recap column
    Settings → run settings prompts (host, check, tags, extra vars)
  Inventory → CRUD hosts + list groups
  Machine Setup → enter host → live stream (built-in sequence) → add to inventory
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
- Settings menu items: Clear run history, Clear saved run settings, Set become (sudo) password
- **Become (sudo) password**: config key `become_password`; delivered via a 0600 temp
  JSON file + `--extra-vars @file` (`runner.become_password_args`). Never put it in argv
  (`ps`) — env vars alone are ignored by ansible, so `become` tasks would hang.
  `run_machine_setup()` uses the same helper so machine setup stays identical to normal runs.
- **Cancelled runs**: Ctrl-C is caught in `_do_run()` and in `cli.run`, recorded with
  `status="cancelled"`, `exit_code=130` (previously Ctrl-C lost the history entry).
- **Stored output**: every run's stdout is kept in `run_history.output`; re-open it with
  `ansiblecli show <id>` or from the history screen (`show_run_output`,
  `prompt_for_run_output`). The history table shows the `ID` column.
- `ansiblecli doctor` checks `ansible-playbook`/`sshpass`/`ssh-keyscan`, config paths,
  inventory file, project count, DB stats and config file permissions
- `config.json` may hold passwords — `save_config()`/`lock_down_config_file()` force mode
  0600; `is_config_exposed()` drives the doctor warning
- `run_subprocess()` in `runner.py` is the shared streaming subprocess utility used by `run_playbook()` and `run_machine_setup()`
- `run_subprocess()` uses `preexec_fn=os.setsid` so `KeyboardInterrupt` propagates to the child process tree
- Machine setup runs the built-in `MACHINE_SETUP_SEQUENCE` (ssh-key scan + ssh-copy-id, then
  sudo.yml / openssh_config.yml / set_hostname.yml / basics.yml / unattendedInstall.yml /
  reboot.yml) against `<host>` via the same `become_password_args()` helper as normal runs
- `machine_setup_menu()` in interactive menu: config check → host prompt → password prompt → live execution → add-to-inventory prompt
- No run_history tracking for machine setup (per user preference)
- Menus clear + re-render through `render_screen()` each loop; `Esc`/Ctrl-C and
  the `← Back` entry always return to the previous menu
- `ansiblecli` with no TTY prints help instead of hanging (see `cli.main`)

## Versioning

`ansiblecli/__init__.py` (`__version__`) is the **single source of truth** —
`pyproject.toml` reads it via `[tool.setuptools.dynamic]`, so never set a
version in `pyproject.toml`. Use `make bump` (`PART=patch|minor|major`) after
major changes or new features; bump minor/major rather than patch when adding
functionality.

## Build / test / release workflow

```bash
make check      # lint + tests — ALWAYS run before finishing work
make test       # pytest only
make lint       # ruff only
make run        # launch the interactive wizard
make bump       # bump __version__ (single source of truth)
make release    # check + bump + commit + tag + push
```

- Tests must be added/updated for every behaviour change; they live in `tests/`.
- `tests/conftest.py` isolates `APP_DIR`, `config.json`, `DB_FILE` and the
  playbooks/inventory dirs into `tmp_path` — never write to the real
  `~/.ansiblecli` in tests, and never shell out to real `ansible-playbook`.
- Every interactive menu is driven through `render_screen()` / `run_menu()` in
  `interactive.py` so all menus look identical. New menus should use those
  helpers (and `ask_select` / `ask_text` / `ask_confirm` / `ask_password`, which
  return `None` on Esc/Ctrl-C) instead of calling questionary directly.
- `ProjectPicker` keeps all behaviour in methods (`move`, `page_next`,
  `cycle_sort`, `type_char`, `select`, ...) so tests exercise them without a
  terminal; `build_app(input=..., output=...)` allows driving it with a pipe.

## Launcher

`./acli.sh` auto-creates `.venv`, `pip install -e .`, delegates to the entry
point. Renamed from `ansiblecli.sh` so it doesn't collide with the `ansiblecli/`
package directory on tab-completion.

## Machine Setup Feature

- [x] `ansiblecli machinesetup <host>` — CLI command to run the built-in machine setup sequence against a new host
- [x] Interactive menu item: Machine Setup (between Inventory and History)
- [x] Config: `machine_setup_become_pass` (single stored SSH/become password, reused by the built-in sequence)
- [x] Subprocess execution with env var injection (SSH password via `SSHPASS`, become password via `--extra-vars @file`) via shared `run_subprocess()` utility
- [x] Post-run host import to inventory (known_hosts)
- [x] KeyboardInterrupt propagates to child process tree via process group

Config keys for Machine Setup:

| Key | Purpose |
|---|---|
| `machine_setup_become_pass` | Default password stored once and reused for SSH login (via `sshpass`) and for ansible become (via `--extra-vars @file`) |
| `machine_setup_default_hostname` | Default hostname passed to `set_hostname.yml` (overridable with `--hostname`) |

The built-in sequence targets the host with an inline inventory (`-i <host>,`) so it works even before the host is added to inventory. The SSH password is never put in argv (only in the `SSHPASS` environment), and ansible's become password is never put in argv (it goes through a 0600 temp JSON file).

## Potential Future Features

- Multi-playbook batch runs (run a sequence of playbooks as a single operation)
- Playbook templates / scaffolding (`ansiblecli new <project>`)
- Per-host variable store (host_vars/)
- SSH key generation and management from within the tool

## Ansible Dependency

`ansible-playbook` must be on PATH at runtime (independent of venv). Options: `apt install ansible`, `brew install ansible`, or `pip install ansible` in/outside venv.
