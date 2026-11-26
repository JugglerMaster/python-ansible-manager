import json
import stat
import subprocess
from pathlib import Path

import pytest

from ansiblecli.machinesetup import (
    MACHINE_SETUP_SEQUENCE,
    ensure_executable,
    run_machine_setup,
)


class FakeProcess:
    def __init__(self, output="", returncode=0):
        self.stdout = iter([output] if output else [])
        self.returncode = returncode

    def wait(self):
        return self.returncode


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
