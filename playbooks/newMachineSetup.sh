#!/usr/bin/env bash
set -euo pipefail

playbooks_dir="$(cd "$(dirname "$0")" && pwd)"

# Parse arguments
hostname=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hostname) hostname="$2"; shift 2 ;;
        *) break ;;
    esac
done

if [[ -z "$hostname" ]]; then
    read -p "Machine hostname: " hostname
fi

if [[ -z "$hostname" ]]; then
    echo "Error: hostname is required."
    exit 1
fi

if [[ $# -lt 1 ]]; then
    read -p "Machine to setup: " machine
fi

if [[ -z "$machine" ]]; then
    echo "Error: target host is required."
    exit 1
fi

cd "$playbooks_dir"

echo "=== Machine Setup ==="
echo "  Hostname: $hostname"
echo "  Target:   $machine"
echo ""

read -p "Continue? [Y/n] " confirm
confirm=${confirm:-Y}
if [[ "${confirm,,}" == "n" ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "[1/8] SSH setup..."
./sshsetup.sh "$machine"
ssh "$machine" 'ssh-keygen -q -t rsa -N "" -f ~/.ssh/id_rsa <<<y >/dev/null 2>&1'

echo "[2/8] Sudoers setup..."
ansible-playbook sudo.yml -i "$machine," -e "ansible_become_pass=godisreal"

echo "[3/8] OpenSSH config..."
ansible-playbook openssh_config.yml -i "$machine,"

echo "[4/8] Setting hostname to '$hostname' (rebooting)..."
ansible-playbook set_hostname.yml -i "$machine," -e "target_hostname=$hostname" -e "ansible_become_pass=godisreal"

echo "[5/8] Basics..."
ansible-playbook basics.yml -i "$machine," -e "ansible_become_pass=godisreal"

echo "[6/8] Unattended install..."
ansible-playbook unattendedInstall.yml -i "$machine,"

echo "[7/8] Reboot..."
ansible-playbook reboot.yml -i "$machine," -e "reboot_timeout=360" -e "ansible_become_pass=godisreal"

echo ""
echo "=== Machine setup complete! ==="
echo "  Hostname: $hostname"
echo "  Target:   $machine"
