import os
import signal
import stat
from pathlib import Path

from ansiblecli.config import get as get_config, set_key
from ansiblecli.runner import SubprocessResult, run_subprocess


def resolve_script_path(override=None):
    if override:
        path = Path(override)
        if path.is_absolute():
            return path
        playbooks_dir = Path(get_config("playbooks_dir"))
        return playbooks_dir / path

    configured = get_config("machine_setup_script")
    if configured:
        path = Path(configured)
        if path.is_absolute():
            return path
        return Path(get_config("playbooks_dir")) / path

    playbooks_dir = Path(get_config("playbooks_dir"))
    candidate = playbooks_dir / "newMachineSetup.sh"
    if candidate.exists():
        return candidate

    return None


def ensure_executable(path):
    st = path.stat()
    if not st.st_mode & stat.S_IXUSR:
        path.chmod(st.st_mode | stat.S_IXUSR)


def run_setup_script(host, script_path=None, hostname=None):
    script = resolve_script_path(script_path)
    if script is None:
        return None

    script = script.resolve()
    if not script.exists():
        return None

    ensure_executable(script)

    become_pass = get_config("machine_setup_become_pass") or None

    env = {
        "ANSIBLE_TARGET_HOST": host,
    }
    if become_pass:
        env["ANSIBLE_BECOME_PASS"] = become_pass

    cwd = str(script.parent)

    cmd = [str(script)]
    if hostname:
        cmd.extend(["--hostname", hostname])
    cmd.append(host)

    result = run_subprocess(cmd, cwd=cwd, env=env)
    return result


# Machine setup playbook sequence (app-driven, not shell script)
MACHINE_SETUP_SEQUENCE = [
    {"type": "ssh_key_setup", "script": "sshsetup.sh"},
    {"playbook": "sudo.yml",         "extra_vars": []},
    {"playbook": "openssh_config.yml", "extra_vars": []},
    {"playbook": "set_hostname.yml",  "extra_vars": ["target_hostname"]},
    {"playbook": "basics.yml",        "extra_vars": []},
    {"playbook": "unattendedInstall.yml", "extra_vars": []},
    {"playbook": "reboot.yml",        "extra_vars": ["reboot_timeout"]},
]


def run_machine_setup(host, hostname, ssh_pass, become_pass):
    """Run the machine setup playbook sequence directly (not via shell script).

    Args:
        host: Target host (hostname or IP)
        hostname: Machine hostname for set_hostname.yml
        ssh_pass: SSH password for the remote user (used by ssh-copy-id)
        become_pass: Sudo/become password for ansible

    Returns a SubprocessResult with cumulative output.
    """
    playbooks_dir = Path(get_config("playbooks_dir"))
    all_output_lines = []

    # Skip set_hostname step if no hostname provided
    steps = MACHINE_SETUP_SEQUENCE
    if not hostname:
        steps = [s for s in steps if s.get("playbook") != "set_hostname.yml"]

    for step in steps:
        # Handle SSH key setup step (runs sshsetup.sh before any playbooks)
        if step.get("type") == "ssh_key_setup":
            script_path = playbooks_dir / step["script"]
            if not script_path.exists():
                print(f"Error: {step['script']} not found in playbooks/", file=__import__('sys').stderr)
                return None
            ensure_executable(script_path)
            print(f"\n[MACHINE_SETUP] Running {step['script']}...")
            # Pre-populate known_hosts so the first SSH connection doesn't
            # hang on an interactive host-key verification prompt. sshpass
            # cannot handle that prompt, so this is required.
            print(f"[MACHINE_SETUP] Scanning remote host key...")
            scan_cmd = ["ssh-keyscan", "-T", "10", host]
            scan_result = run_subprocess(scan_cmd)
            if scan_result and scan_result.stdout:
                known_hosts = Path.home() / ".ssh" / "known_hosts"
                known_hosts.parent.mkdir(parents=True, exist_ok=True)
                with open(known_hosts, "a") as f:
                    f.write(scan_result.stdout)
            print(f"[MACHINE_SETUP] Copying SSH key...")
            ssh_cmd = ["sshpass", "-p", ssh_pass, "ssh-copy-id", host]
            result = run_subprocess(ssh_cmd, cwd=str(script_path.parent))
            if result is None:
                return None
            all_output_lines.append(result.stdout)
            if result.returncode != 0:
                print(f"\n[MACHINE_SETUP] {step['script']} failed with exit code {result.returncode}")
                return SubprocessResult(returncode=result.returncode, stdout="\n".join(all_output_lines))
            continue

        playbook_path = playbooks_dir / step["playbook"]
        if not playbook_path.exists():
            print(f"Error: {step['playbook']} not found in playbooks/", file=__import__('sys').stderr)
            return None

        # Use inline inventory (host as a string) so we can target a host
        # that isn't yet in the inventory file. Trailing comma tells Ansible
        # it's a host list, not a file path.
        cmd = ["ansible-playbook", str(playbook_path), "-i", f"{host},"]

        # Build extra vars
        ev_list = []
        for var_name in step["extra_vars"]:
            if var_name == "target_hostname":
                ev_list.append(f"target_hostname={hostname}")
            elif var_name == "reboot_timeout":
                ev_list.append("reboot_timeout=360")
        for ev in ev_list:
            cmd.extend(["-e", ev])

        # Set ANSIBLE_BECOME_PASSWORD via env (passing ansible_become_pass via -e
        # doesn't work reliably — Ansible ignores it and prompts interactively).
        step_env = {"ANSIBLE_BECOME_PASSWORD": become_pass, "ANSIBLE_BECOME_PASS": become_pass} if become_pass else {}

        print(f"\n[MACHINE_SETUP] Running {step['playbook']}...")
        result = run_subprocess(cmd, env=step_env)

        if result is None:
            return None

        all_output_lines.append(result.stdout)

        if result.returncode != 0:
            print(f"\n[{'MACHINE_SETUP'}] {step['playbook']} failed with exit code {result.returncode}")
            return SubprocessResult(returncode=result.returncode, stdout="\n".join(all_output_lines))

    return SubprocessResult(returncode=0, stdout="\n".join(all_output_lines))
