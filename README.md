# AnsibleCLI

Interactive CLI tool for managing and running Ansible playbooks.

## Install

```bash
pip install -e .
```

## Quick Start

```bash
# Initialize config and database
ansiblecli init

# Add a host to inventory
ansiblecli inventory add new-pc --address 192.168.1.100 --group desktops

# Add a playbook project
mkdir -p playbooks/desktop-setup
# ... create playbook.yml in that directory

# Run the interactive wizard
ansiblecli
```

## Directory Structure

```
playbooks/          # Ansible playbooks — each subdirectory is a project
  <project>/        #   One or more .yml files, auto-discovered
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
# Interactive wizard (no args)
ansiblecli

# List discovered projects
ansiblecli list

# Run a project (uses last settings or prompts)
ansiblecli run desktop-setup

# Run with specific flags (no prompts)
ansiblecli run desktop-setup --host new-pc --check
ansiblecli run desktop-setup --host new-pc --tags "desktop,apps" --extra-vars "user=chris"

# Manage inventory
ansiblecli inventory add new-pc --address 192.168.1.100 --group desktops
ansiblecli inventory list
ansiblecli inventory remove new-pc
ansiblecli inventory show

# History
ansiblecli history
ansiblecli history desktop-setup

# Configuration
ansiblecli config
ansiblecli config set playbooks_dir /path/to/playbooks

# Initialize
ansiblecli init
```

## License

MIT
