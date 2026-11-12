import subprocess

import pytest

from ansiblecli.runner import SubprocessResult, run_playbook, run_subprocess


class FakeProcess:
    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self.returncode = returncode

    def wait(self):
        return self.returncode


@pytest.fixture
def capture_popen(monkeypatch):
    """Replace subprocess.Popen so no real ansible-playbook is required."""
    calls = []

    def fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return FakeProcess(["line one\n", "PLAY RECAP\n"], returncode=0)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return calls


def test_run_playbook_builds_expected_command(isolated_env, capture_popen):
    isolated_env.hosts_file.parent.mkdir(parents=True, exist_ok=True)
    isolated_env.hosts_file.write_text("all:\n  hosts: {}\n")

    run_playbook("playbooks/alpha/playbook.yml")

    cmd, _ = capture_popen[0]
    assert cmd[:4] == ["ansible-playbook", "playbooks/alpha/playbook.yml", "-i", str(isolated_env.hosts_file)]


def test_run_playbook_appends_flags_in_order(isolated_env, capture_popen):
    isolated_env.hosts_file.parent.mkdir(parents=True, exist_ok=True)
    isolated_env.hosts_file.write_text("all:\n  hosts: {}\n")

    run_playbook("p.yml", host="web1", check_mode=True, tags="install", extra_vars="a=1, b=2")

    cmd, _ = capture_popen[0]
    assert cmd[cmd.index("-l"):cmd.index("-l") + 2] == ["-l", "web1"]
    assert "--check" in cmd
    assert cmd[cmd.index("-t"):cmd.index("-t") + 2] == ["-t", "install"]
    assert cmd.count("-e") == 2
    assert "a=1" in cmd and "b=2" in cmd


def test_run_playbook_ignores_malformed_extra_vars(isolated_env, capture_popen):
    isolated_env.hosts_file.parent.mkdir(parents=True, exist_ok=True)
    isolated_env.hosts_file.write_text("all:\n  hosts: {}\n")

    run_playbook("p.yml", extra_vars="good=1, notakeyvalue")

    cmd, _ = capture_popen[0]
    assert cmd.count("-e") == 1
    assert "good=1" in cmd
    assert "notakeyvalue" not in cmd


def test_run_playbook_without_inventory_file_returns_none(isolated_env, capture_popen):
    assert run_playbook("p.yml") is None
    assert capture_popen == []  # never launched


def test_run_playbook_missing_binary_returns_none(isolated_env, monkeypatch, capsys):
    isolated_env.hosts_file.parent.mkdir(parents=True, exist_ok=True)
    isolated_env.hosts_file.write_text("all:\n  hosts: {}\n")

    def raise_not_found(*a, **kw):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "Popen", raise_not_found)
    assert run_playbook("p.yml") is None
    assert "command not found" in capsys.readouterr().err


def test_run_subprocess_captures_and_streams_output(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen",
                        lambda cmd, **kw: FakeProcess(["hello\n", "world\n"], returncode=3))
    result = run_subprocess(["echo"])
    assert isinstance(result, SubprocessResult)
    assert result.stdout == "hello\nworld\n"
    assert result.returncode == 3


def test_run_subprocess_sets_child_process_group(isolated_env, monkeypatch):
    import os
    from unittest import mock

    with mock.patch.object(subprocess, "Popen", return_value=FakeProcess([])) as popen:
        run_subprocess(["x"])
    assert popen.call_args.kwargs["preexec_fn"] is os.setsid


def test_keyboard_interrupt_terminates_child_process_group(isolated_env, monkeypatch):
    """Ctrl-C must be forwarded to the whole ansible process group."""
    import signal

    killed = {}

    class InterruptingProcess:
        pid = 4242
        stdout = iter(["one line\n"])

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: InterruptingProcess())
    monkeypatch.setattr("os.getpgid", lambda pid: 999)
    monkeypatch.setattr("os.killpg", lambda pgid, sig: killed.update(pgid=pgid, sig=sig))

    def raise_interrupt(*a, **kw):
        raise KeyboardInterrupt

    # print() is called for each streamed line — use it to inject the interrupt.
    monkeypatch.setattr("builtins.print", raise_interrupt)

    with pytest.raises(KeyboardInterrupt):
        run_subprocess(["boom"])

    assert killed == {"pgid": 999, "sig": signal.SIGTERM}
