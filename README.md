# AnsibleCLI

Interactive CLI tool for managing and running Ansible playbooks.

## Quick Start

```bash
# First run: creates .venv, installs, launches wizard
./ansiblecli.sh

# Initialize config and database
ansiblecli init

# Add a host
ansiblecli inventory add new-pc --address 192.168.1.100 --group desktops

# Run the interactive wizard
ansiblecli
```

**Requirement:** `ansible-playbook` must be on your PATH — install Ansible via `apt`/`brew`/`pip` or inside the same venv.

## Features

- **Keyboard-driven project picker** — pagination, live search (`/`), sort modes (`s`), hotkeys for run/settings/history/view
- **Live streaming output** — ansible-playbook output streams in real time while still being captured for history
- **Run history** — per-project or global, with host-level recap (ok/failed/unreachable counts from PLAY RECAP)
- **Playbook viewer** — full-screen YAML via `less` with syntax highlighting, line numbers, scroll, and search
- **Settings menu** — configurable run options (host, check mode, tags, extra vars), clear run history
- **Inventory management** — CRUD hosts, group listing, auto-generated YAML inventory

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
```

## Usage

```bash
ansiblecli                    # Interactive wizard
ansiblecli list               # List discovered projects
ansiblecli run desktop-setup  # Run with last config or prompts
ansiblecli history            # View run history
ansiblecli config             # Show configuration
ansiblecli inventory list     # List hosts
ansiblecli inventory add <hostname> --address <ip> --group <group>
```

## License

MIT
