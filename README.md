# AnsibleCLI

Interactive CLI tool for managing and running Ansible playbooks.

## Quick Start

```bash
# First run: creates .venv, installs, launches wizard
./acli.sh

# Or use make (recommended for development)
make install
make run

# Initialize config and database
ansiblecli init

# Add a host
ansiblecli inventory add new-pc --address 192.168.1.100 --group desktops

# Run the interactive wizard
ansiblecli
```

**Requirement:** `ansible-playbook` must be on your PATH — install Ansible via `apt`/`brew`/`pip` or inside the same venv.

> The launcher is `acli.sh` (not `ansiblecli.sh`) so it doesn't collide with the
> `ansiblecli/` package directory on tab-completion.

## Features

- **Keyboard-driven project picker** — pagination, live search (`/`), sort modes (`s`), hotkeys for run/settings/history/view
- **Live streaming output** — ansible-playbook output streams in real time while still being captured for history
- **Run history** — per-project or global, with host-level recap (ok/failed/unreachable counts from PLAY RECAP)
- **Playbook viewer** — full-screen YAML via `less` with syntax highlighting, line numbers, scroll, and search
- **Settings menu** — clear run history, clear saved per-project run settings, store the sudo/become password
- **Become (sudo) support** — set once and playbooks using `become` no longer hang on a sudo prompt; the password travels in a 0600 temp file, never on the command line
- **Stored run output** — every run's output is captured; open it again from history or with `ansiblecli show <id>`
- **`ansiblecli doctor`** — checks ansible/sshpass/ssh-keyscan, config paths, inventory, DB and config permissions
- **Inventory management** — CRUD hosts, group listing, auto-generated YAML inventory

## Development

```bash
make help          # list all targets
make install       # .venv + editable install + dev deps (pytest, ruff, build)
make test          # run the test suite
make lint          # ruff check
make fmt           # auto-fix import order / simple lint issues
make check         # lint + test — run before every commit
make bump          # 1.2.0 -> 1.2.1  (PART=minor|major to override)
make release       # check + bump + commit + tag + push (CI publishes the release)
```

- Tests live in `tests/` and run fully isolated: every test gets a throwaway
  `~/.ansiblecli`, `config.json`, SQLite DB and `playbooks/` tree, so your real
  history and inventory are never touched.
- No `ansible-playbook` binary is needed for tests — subprocesses are faked.

### Versioning & releases

The version lives in **one** place: `ansiblecli/__init__.py` (`__version__`).
`pyproject.toml` reads it dynamically, so `make bump` is the only step needed.

`make release` bumps, commits, tags `vX.Y.Z` and pushes; the GitHub Actions
`Release` workflow then builds the sdist/wheel and publishes a GitHub release.

CI (`.github/workflows/ci.yml`) runs `ruff` + `pytest` on Python 3.10–3.12 for
every push and PR.

## Directory Structure

```
playbooks/          # Ansible playbooks — subdirs or standalone .yml files
  <project>/        #   One or more .yml files, auto-discovered recursively
    playbook.yml

playfiles/          # Supporting files for playbooks (NOT managed by this tool)
  <project>/        #   Same project name as playbooks/
    files/
    templates/
    scripts/

inventory/          # Managed inventory — auto-generated, do not edit
  hosts.yml         #   Passed to ansible-playbook with -i automatically

tests/              # pytest suite (isolated fixtures in tests/conftest.py)
scripts/            # bump_version.py
```

## Usage

```bash
ansiblecli                    # Interactive wizard
ansiblecli --version          # Print version
ansiblecli list               # List discovered projects
ansiblecli run desktop-setup  # Run with last config or prompts
ansiblecli run basics --all-hosts -vv   # Every host, verbose
ansiblecli run basics -K      # Prompt-free sudo (uses stored become password)
ansiblecli history            # View run history (IDs shown)
ansiblecli show 42            # Re-open the captured output of run 42
ansiblecli doctor             # Environment sanity check
ansiblecli config             # Show configuration
ansiblecli inventory list     # List hosts
ansiblecli inventory add <hostname> --address <ip> --group <group>
ansiblecli --install-completion      # Shell completion for commands/flags
```

### Become (sudo) password

`become` tasks otherwise block on an interactive sudo prompt you can't answer:

```bash
ansiblecli                    # Settings -> "Set become (sudo) password"
ansiblecli config set become_password '<sudo password>'   # same thing, non-interactive
```

It's written to `~/.ansiblecli/config.json`, which is forced to mode `600`, and
handed to ansible via a temporary `--extra-vars` file — never on the command
line where `ps` could see it. Runs interrupted with Ctrl-C are recorded as
`cancelled` instead of disappearing.

Interactive picker hotkeys:

| Key | Action |
|---|---|
| `↑` / `↓` | Move selection |
| `←` / `→` (or PgUp/PgDn) | Previous / next page |
| `Home` / `End` | First / last project |
| `s` | Cycle sort (name → last run → modified) |
| `/` | Search (type to filter, `Enter` accepts and runs, `Esc` clears) |
| `Enter` | Run highlighted project |
| `c` / `h` / `v` | Settings / history / view playbook |
| `Esc` (or `Ctrl-C`) | Back |

## License

MIT
