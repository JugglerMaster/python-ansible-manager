# AnsibleCLI

Interactive CLI tool for managing and running Ansible playbooks.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate  # Linux/macOS

pip install -e .
```

**Requirement:** `ansible-playbook` must be on your PATH. Install Ansible either system-wide (e.g., `apt install ansible`, `brew install ansible`, `pip install ansible`) or inside the same virtual environment.

## Quick Start

```bash
ansiblecli init
ansiblecli inventory add new-pc --address 192.168.1.100 --group desktops
mkdir -p playbooks/desktop-setup
# create playbook.yml in that directory
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
ansiblecli                    # Interactive wizard
ansiblecli list               # List discovered projects
ansiblecli run desktop-setup  # Run with last config or prompts
ansiblecli history            # View run history
ansiblecli config             # Show configuration
```

### Inventory

```bash
ansiblecli inventory add new-pc --address 192.168.1.100 --group desktops
ansiblecli inventory list
ansiblecli inventory remove new-pc
ansiblecli inventory show
```

## License

MIT
