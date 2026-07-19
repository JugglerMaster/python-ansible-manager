import os
import signal
import subprocess
import sys
from pathlib import Path

from ansiblecli.config import get


class SubprocessResult:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def run_subprocess(cmd, cwd=None, env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    try:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            preexec_fn=os.setsid,
        )
        output_lines = []
        try:
            for line in process.stdout:
                print(line, end="", flush=True)
                output_lines.append(line)
            process.wait()
        except KeyboardInterrupt:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait()
            raise
        full_output = "".join(output_lines)
        return SubprocessResult(returncode=process.returncode, stdout=full_output)
    except FileNotFoundError:
        print(f"Error: command not found — {cmd[0]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error running command: {e}", file=sys.stderr)
        return None


def run_playbook(playbook_path, host=None, check_mode=False, tags=None, extra_vars=None):
    inventory_dir = Path(get("inventory_dir"))
    inventory_file = inventory_dir / get("inventory_file")

    if not inventory_file.exists():
        print(f"Error: inventory file not found at {inventory_file}", file=sys.stderr)
        print("Run 'ansiblecli inventory list' or 'ansiblecli init' first.", file=sys.stderr)
        return None

    cmd = ["ansible-playbook", str(playbook_path), "-i", str(inventory_file)]

    if host:
        cmd.extend(["-l", host])

    if check_mode:
        cmd.append("--check")

    if tags:
        cmd.extend(["-t", tags])

    if extra_vars:
        for ev in extra_vars.split(","):
            ev = ev.strip()
            if "=" in ev:
                cmd.extend(["-e", ev])

    result = run_subprocess(cmd)
    if result is not None:
        return SubprocessResult(returncode=result.returncode, stdout=result.stdout)
    return None
