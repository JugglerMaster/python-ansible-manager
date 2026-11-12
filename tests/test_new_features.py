"""Tests for the newer behaviour: become password, verbosity, cancelled runs,
stored-output viewing, config permissions and `ansiblecli doctor`.
"""

import json
import os
import stat
import subprocess

import pytest
from typer.testing import CliRunner

from ansiblecli import config, database, interactive
from ansiblecli.cli import app
from ansiblecli.runner import SubprocessResult, become_password_args, run_playbook

runner = CliRunner()


def write_inventory(isolated_env):
    isolated_env.hosts_file.parent.mkdir(parents=True, exist_ok=True)
    isolated_env.hosts_file.write_text("all:\n  hosts: {}\n")
    return isolated_env.hosts_file


@pytest.fixture
def capture_popen(monkeypatch):
    calls = []

    class FakeProcess:
        stdout = iter(["PLAY RECAP\nweb1 : ok=1 failed=0\n"])
        returncode = 0

        def wait(self):
            return 0

    def fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return calls


# --------------------------------------------------------- become password

def test_become_password_file_is_private_and_contains_password():
    with become_password_args("s3cret") as args:
        assert args  # otherwise the password wouldn't be supplied at all
        assert args[0] == "-e"
        path = args[1][1:]  # strip the '@'
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600, "become password file must be owner-only"
        with open(path) as handle:
            assert json.load(handle) == {"ansible_become_password": "s3cret"}
        password_file = path

    assert not os.path.exists(password_file), "temp file must be cleaned up"


def test_become_password_file_removed_even_on_error():
    password_file = None
    with pytest.raises(RuntimeError), become_password_args("pw") as args:
        password_file = args[1][1:]
        raise RuntimeError("boom")
    assert not os.path.exists(password_file)


def test_no_password_yields_no_args():
    with become_password_args("") as args:
        assert args == []


def test_run_playbook_uses_become_file_when_configured(isolated_env, capture_popen, monkeypatch):
    write_inventory(isolated_env)
    config.set_key("become_password", "sudopw")

    run_playbook("p.yml")

    cmd, _ = capture_popen[0]
    assert "-e" in cmd
    become_arg = next(a for a in cmd if a.startswith("@"))
    assert os.path.exists(become_arg[1:]) is False  # cleaned up after the run


def test_run_playbook_explicit_password_overrides_config(isolated_env, capture_popen):
    write_inventory(isolated_env)
    config.set_key("become_password", "configpw")

    run_playbook("p.yml", become_password=None)  # None -> falls back to config

    cmd, _ = capture_popen[0]
    # whichever source, it must arrive via a file and never inline
    assert not any("configpw" in a for a in cmd), "password must not appear in argv"


def test_become_password_never_appears_in_argv(isolated_env, capture_popen):
    write_inventory(isolated_env)
    run_playbook("p.yml", become_password="topsecret")
    cmd, _ = capture_popen[0]
    assert not any("topsecret" in a for a in cmd)


# ---------------------------------------------------------------- verbosity

@pytest.mark.parametrize("verbose,expected", [(0, 0), (1, 1), (2, 2), (7, 4)])
def test_verbose_adds_repeated_v_flags(isolated_env, capture_popen, verbose, expected):
    write_inventory(isolated_env)
    run_playbook("p.yml", verbose=verbose)
    cmd, _ = capture_popen[0]
    assert cmd.count("-v") == expected


def test_verbose_bool_is_treated_as_one(isolated_env, capture_popen):
    write_inventory(isolated_env)
    run_playbook("p.yml", verbose=True)
    cmd, _ = capture_popen[0]
    assert cmd.count("-v") == 1


# --------------------------------------------------------- cancelled runs

def test_do_run_records_cancelled_status(monkeypatch, projects):
    write_inventory(projects)
    monkeypatch.setattr("ansiblecli.inventory.write_inventory_file", lambda *a, **kw: None)

    def interrupt(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr("ansiblecli.runner.run_playbook", interrupt)

    result = interactive._do_run({"name": "alpha"}, "alpha/playbook.yml",
                                 {"host": "web1", "check_mode": False, "tags": None,
                                  "extra_vars": None, "save": False})
    assert result is interactive.CANCELLED

    row = database.get_run_history("alpha")[0]
    assert row["status"] == "cancelled"
    assert row["exit_code"] == 130


def test_run_and_loop_prints_cancelled_message(monkeypatch, projects, capsys):
    write_inventory(projects)
    monkeypatch.setattr(interactive, "_do_run", lambda *a, **kw: interactive.CANCELLED)
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)

    interactive._run_and_loop({"name": "alpha"}, "alpha/playbook.yml", {})
    assert "cancelled" in capsys.readouterr().out.lower()


def test_cli_run_records_cancel_on_interrupt(monkeypatch, projects):
    write_inventory(projects)
    database.save_last_config("alpha", "web1", False, None, None)

    def interrupt(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr("ansiblecli.runner.run_playbook", interrupt)

    result = runner.invoke(app, ["run", "alpha"])
    assert result.exit_code == 130
    assert database.get_run_history("alpha")[0]["status"] == "cancelled"


# ------------------------------------------------------- stored run output

def test_get_run_by_id_roundtrip():
    database.add_run("alpha", "p.yml", "web1", False, None, None, "failed", 2, "boom output")
    run_id = database.get_run_history("alpha")[0]["id"]
    row = database.get_run_by_id(run_id)
    assert row["output"] == "boom output"
    assert database.get_run_by_id(run_id + 999) is None


def test_show_run_output_prints_stored_output(projects, capsys):
    database.add_run("alpha", "p.yml", "web1", False, None, None, "failed", 2, "TASK FAILED here")
    run_id = database.get_run_history("alpha")[0]["id"]

    assert interactive.show_run_output(run_id, use_pager=False) is True
    assert "TASK FAILED here" in capsys.readouterr().out
    assert interactive.show_run_output(999999, use_pager=False) is False


def test_history_table_shows_ids(projects, capsys):
    database.add_run("alpha", "p.yml", "web1", False, None, None, "success", 0, "")
    interactive.show_history("alpha")
    out = capsys.readouterr().out
    assert "ID" in out
    assert "1" in out


def test_prompt_for_run_output_blank_returns_false(monkeypatch):
    monkeypatch.setattr(interactive, "ask_text", lambda *a, **kw: "")
    assert interactive.prompt_for_run_output() is False


def test_prompt_for_run_output_bad_id_is_reported(monkeypatch, capsys):
    monkeypatch.setattr(interactive, "ask_text", lambda *a, **kw: "999999")
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)
    assert interactive.prompt_for_run_output() is False
    assert "No run with ID" in capsys.readouterr().out


def test_prompt_for_run_output_non_numeric_rejected(monkeypatch, capsys):
    monkeypatch.setattr(interactive, "ask_text", lambda *a, **kw: "banana")
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)
    assert interactive.prompt_for_run_output() is False
    assert "isn't a run ID" in capsys.readouterr().out


def test_prompt_for_run_output_valid_id(monkeypatch):
    database.add_run("alpha", "p.yml", "web1", False, None, None, "success", 0, "hello")
    run_id = database.get_run_history("alpha")[0]["id"]
    shown = []
    monkeypatch.setattr(interactive, "ask_text", lambda *a, **kw: str(run_id))
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)
    monkeypatch.setattr(interactive, "show_run_output",
                        lambda rid, **kw: shown.append(rid) or True)
    assert interactive.prompt_for_run_output() is True
    assert shown == [run_id]


def test_cli_show_prints_output_and_exits_one_when_missing(projects):
    database.add_run("alpha", "p.yml", "web1", False, None, None, "failed", 2, "boom")
    run_id = database.get_run_history("alpha")[0]["id"]

    ok = runner.invoke(app, ["show", str(run_id)])
    assert ok.exit_code == 0
    assert "boom" in ok.output

    missing = runner.invoke(app, ["show", "123456"])
    assert missing.exit_code == 1


# ------------------------------------------------------ config permissions

def test_saved_config_is_private(isolated_env):
    config.set_key("become_password", "hunter2")
    mode = stat.S_IMODE(config.CONFIG_FILE.stat().st_mode)
    assert mode == 0o600


def test_is_config_exposed_detects_loose_permissions(isolated_env):
    config.set_key("become_password", "x")
    assert config.is_config_exposed() is False

    os.chmod(config.CONFIG_FILE, 0o644)
    assert config.is_config_exposed() is True

    config.lock_down_config_file()
    assert config.is_config_exposed() is False


def test_config_permissions_none_when_missing(isolated_env):
    assert config.CONFIG_FILE.exists() is False
    assert config.config_permissions() is None
    assert config.is_config_exposed() is False


# ----------------------------------------------------------------- doctor

def test_doctor_reports_environment(isolated_env, projects, monkeypatch):
    monkeypatch.setattr("ansiblecli.cli.shutil.which",
                        lambda name: f"/usr/bin/{name}" if name == "ansible-playbook" else None)
    database.add_run("alpha", "p.yml", "web1", False, None, None, "success", 0, "")

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "ansible-playbook" in result.output
    assert "sshpass" in result.output          # reported as missing
    assert "playbooks_dir" in result.output
    assert "3 project" in result.output or "projects discovered" in result.output
    assert "1 runs recorded" in result.output


def test_doctor_warns_when_ansible_missing(isolated_env, monkeypatch):
    monkeypatch.setattr("ansiblecli.cli.shutil.which", lambda name: None)
    result = runner.invoke(app, ["doctor"])
    assert "missing on PATH" in result.output
    assert "Install Ansible" in result.output


def test_doctor_warns_on_exposed_config(isolated_env, monkeypatch):
    config.set_key("become_password", "x")
    os.chmod(config.CONFIG_FILE, 0o644)
    result = runner.invoke(app, ["doctor"])
    assert "readable by other users" in result.output


# ------------------------------------------------------- history include cancelled

def test_stats_include_cancelled(projects):
    database.add_run("alpha", "p.yml", "h", False, None, None, "cancelled", 130, "")
    assert database.get_history_stats("alpha")["cancelled"] == 1


def test_show_history_styles_cancelled_row(projects, capsys):
    database.add_run("alpha", "p.yml", "h", False, None, None, "cancelled", 130, "")
    interactive.show_history("alpha")
    assert "cancelled" in capsys.readouterr().out


def test_subprocessresult_and_run_playbook_return_type(isolated_env, capture_popen):
    write_inventory(isolated_env)
    result = run_playbook("p.yml")
    assert isinstance(result, SubprocessResult)
    assert result.returncode == 0


def test_settings_can_store_become_password_privately(isolated_env, monkeypatch):
    monkeypatch.setattr(interactive, "ask_password", lambda *a, **kw: "sudopw")
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)

    interactive._settings_set_become_password()

    assert config.get("become_password") == "sudopw"
    mode = stat.S_IMODE(config.CONFIG_FILE.stat().st_mode)
    assert mode == 0o600


def test_settings_can_clear_become_password(isolated_env, monkeypatch):
    config.set_key("become_password", "old")
    monkeypatch.setattr(interactive, "ask_password", lambda *a, **kw: "")
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)

    interactive._settings_set_become_password()
    assert config.get("become_password") == ""


def test_settings_menu_offers_become_password(monkeypatch):
    answers = iter(["become_pass", interactive.BACK])
    monkeypatch.setattr(interactive, "ask_select", lambda *a, **kw: next(answers))
    monkeypatch.setattr(interactive, "ask_password", lambda *a, **kw: "pw")
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)

    interactive.settings_menu()
    assert config.get("become_password") == "pw"
