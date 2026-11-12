import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from ansiblecli.config import get


class SubprocessResult:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


@contextlib.contextmanager
def become_password_args(password):
    """Yield the extra args that give ansible a non-interactive become password.

    The password goes through a 0600 temp file with `--extra-vars @file`:
    - inline (`-e ansible_become_password=...`) would leak it via `ps`
    - env alone isn't honoured by ansible, so sudo prompts and the run hangs
    """
    if not password:
        yield []
        return

    fd, path = tempfile.mkstemp(prefix="ansiblecli-become-", suffix=".json")
    try:
        os.chmod(path, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"ansible_become_password": password}, f)
        yield ["-e", f"@{path}"]
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


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
            # Sets a new process group so Ctrl-C reaches the whole ansible tree.
            preexec_fn=os.setsid,  # noqa: PLW1509
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
    except OSError as e:
        print(f"Error running command: {e}", file=sys.stderr)
        return None


def run_playbook(playbook_path, host=None, check_mode=False, tags=None, extra_vars=None,
                 become_password=None, verbose=0):
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

    # -v ... -vvvv (capped); ansible accepts repeated short flags.
    if isinstance(verbose, bool):
        verbose = 1 if verbose else 0
    cmd.extend(["-v"] * max(0, min(int(verbose or 0), 4)))

    # Fall back to the stored sudo password so `become` tasks don't hang.
    if not become_password:
        become_password = get("become_password") or None

    with become_password_args(become_password) as become_args:
        cmd.extend(become_args)
        result = run_subprocess(cmd)

    if result is not None:
        return SubprocessResult(returncode=result.returncode, stdout=result.stdout)
    return None
