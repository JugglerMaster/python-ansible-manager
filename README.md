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

## Manual Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

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
