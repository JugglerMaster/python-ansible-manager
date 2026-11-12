import json
import stat
import subprocess
from pathlib import Path

import pytest

from ansiblecli import config
from ansiblecli.machinesetup import (
    MACHINE_SETUP_SEQUENCE,
    ensure_executable,
    resolve_script_path,
    run_machine_setup,
    run_setup_script,
)


class FakeProcess:
    def __init__(self, output="", returncode=0):
        self.stdout = iter([output] if output else [])
        self.returncode = returncode

    def wait(self):
        return self.returncode


@pytest.fixture
def capture_popen(monkeypatch):
    calls = []

    def fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return calls


@pytest.fixture
def fake_home(monkeypatch, tmp_path):
    """Keep ssh-keyscan from appending to the real ~/.ssh/known_hosts."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: home))
    return home


def _run_sequence(capture_popen, returncodes=None):
    """Drive run_machine_setup with per-command return codes."""
    returncodes = returncodes or {}

    def fake_popen(cmd, **kwargs):
        capture_popen.append((cmd, kwargs))
        return FakeProcess(returncode=returncodes.get(cmd[0], 0))

    return fake_popen


@pytest.fixture
def full_setup_dir(isolated_env):
    for name in ["sudo.yml", "openssh_config.yml", "set_hostname.yml", "basics.yml",
                 "unattendedInstall.yml", "reboot.yml"]:
        isolated_env.write_playbook(name)
    isolated_env.write_playbook("sshsetup.sh", "#!/bin/sh\n")
    return isolated_env


def test_resolve_script_path_defaults_to_new_machine_setup(isolated_env):
    isolated_env.write_playbook("newMachineSetup.sh", "#!/bin/sh\n")
    path = resolve_script_path()
    assert path.name == "newMachineSetup.sh"


def test_resolve_script_path_prefers_override(isolated_env):
    isolated_env.write_playbook("custom.sh", "#!/bin/sh\n")
    assert resolve_script_path("custom.sh").name == "custom.sh"


def test_resolve_script_path_absolute_override(tmp_path):
    script = tmp_path / "abs.sh"
    script.write_text("#!/bin/sh\n")
    assert resolve_script_path(str(script)) == script


def test_resolve_script_path_from_config(isolated_env):
    isolated_env.write_playbook("configured.sh", "#!/bin/sh\n")
    config.set_key("machine_setup_script", "configured.sh")
    assert resolve_script_path().name == "configured.sh"


def test_resolve_script_path_returns_none_when_missing(isolated_env):
    assert resolve_script_path() is None


def test_run_setup_script_returns_none_without_script(isolated_env):
    assert run_setup_script("host1") is None


def test_run_setup_script_builds_env_and_command(isolated_env, capture_popen):
    script = isolated_env.write_playbook("newMachineSetup.sh", "#!/bin/sh\n")
    config.set_key("machine_setup_become_pass", "s3cret")

    run_setup_script("10.0.0.9", hostname="newhost")

    (cmd, kwargs), = capture_popen
    assert cmd[0] == str(script.resolve())
    assert cmd[1:] == ["--hostname", "newhost", "10.0.0.9"]
    assert kwargs["env"]["ANSIBLE_TARGET_HOST"] == "10.0.0.9"
    assert kwargs["env"]["ANSIBLE_BECOME_PASS"] == "s3cret"
    assert kwargs["cwd"] == str(script.parent)
    assert script.stat().st_mode & stat.S_IXUSR  # made executable


def test_setup_sequence_skips_set_hostname_without_hostname(
        monkeypatch, full_setup_dir, fake_home):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", _run_sequence(calls))

    run_machine_setup("10.0.0.9", None, "pw", "pw")

    invoked = [c[0] for c in calls]
    assert not any("set_hostname.yml" in c[1] for c in invoked)
    assert any("sudo.yml" in c[1] for c in invoked)


def test_setup_sequence_includes_set_hostname_when_given(
        monkeypatch, full_setup_dir, fake_home):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", _run_sequence(calls))

    run_machine_setup("10.0.0.9", "newhost", "pw", "pw")

    invoked = [c[0] for c in calls]
    sshsetup_cmd, sshsetup_kwargs = calls[1]
    assert sshsetup_cmd[:3] == ["sshpass", "-e", "ssh-copy-id"]  # password not in argv
    assert sshsetup_kwargs["env"]["SSHPASS"] == "pw"
    hostname_cmd = next(c for c in invoked if "set_hostname.yml" in c[1])
    assert "target_hostname=newhost" in hostname_cmd


def run_setup(calls, seen_secrets=None, returncodes=None):
    """Drive run_machine_setup, capturing become-password file contents live."""
    def fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if seen_secrets is not None:
            for arg in cmd:
                if arg.startswith("@"):
                    seen_secrets[arg] = Path(arg[1:]).read_text()
        return FakeProcess(returncode=(returncodes or {}).get(cmd[0], 0))

    return fake_popen


def become_arg(cmd):
    return next(a for a in cmd if a.startswith("@"))


def test_setup_sequence_uses_inline_inventory_and_become_file(
        monkeypatch, full_setup_dir, fake_home):
    calls, secrets = [], {}
    monkeypatch.setattr(subprocess, "Popen", run_setup(calls, secrets))

    run_machine_setup("10.0.0.9", "newhost", "pw", "pw")

    playbook_cmd = next(cmd for cmd, _kwargs in calls if "sudo.yml" in cmd[1])
    # Not yet in the inventory file -> inline host list
    assert playbook_cmd[playbook_cmd.index("-i") + 1] == "10.0.0.9,"
    # sudo password via a file, never inline (which would show up in `ps`)
    assert "-e" in playbook_cmd
    assert json.loads(secrets[become_arg(playbook_cmd)]) == {
        "ansible_become_password": "pw"}


def test_become_password_file_is_removed_after_the_run(
        monkeypatch, full_setup_dir, fake_home):
    calls, secrets = [], {}
    monkeypatch.setattr(subprocess, "Popen", run_setup(calls, secrets))

    run_machine_setup("10.0.0.9", None, "pw", "pw")

    assert secrets, "expected a become-password file during the run"
    for arg in secrets:
        assert not Path(arg[1:]).exists()  # temp secret cleaned up


def test_setup_sequence_scans_host_key_before_copying_id(
        monkeypatch, full_setup_dir, fake_home):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", _run_sequence(calls))

    run_machine_setup("10.0.0.9", None, "pw", "pw")

    assert [c[0][0] for c in calls[:2]] == ["ssh-keyscan", "sshpass"]


def test_setup_sequence_stops_on_first_failure(
        monkeypatch, full_setup_dir, fake_home):
    calls = []
    monkeypatch.setattr(
        subprocess, "Popen",
        _run_sequence(calls, returncodes={"sshpass": 2}))

    result = run_machine_setup("10.0.0.9", "newhost", "pw", "pw")

    assert result.returncode == 2
    assert [c[0][0] for c in calls] == ["ssh-keyscan", "sshpass"]


def test_setup_sequence_returns_none_when_playbook_missing(isolated_env):
    assert run_machine_setup("10.0.0.9", None, "pw", "pw") is None


def test_ensure_executable_adds_user_bit(isolated_env):
    script = isolated_env.write_playbook("x.sh", "#!/bin/sh\n")
    script.chmod(0o644)
    ensure_executable(script)
    assert script.stat().st_mode & stat.S_IXUSR


def test_machine_setup_sequence_defines_expected_steps():
    playbooks = [s["playbook"] for s in MACHINE_SETUP_SEQUENCE if "playbook" in s]
    assert playbooks[0] == "sudo.yml"
    assert "reboot.yml" in playbooks
