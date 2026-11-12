"""Tests for the interactive menus — especially the ones that used to break."""

import pytest

from ansiblecli import database, interactive
from ansiblecli.runner import SubprocessResult

REQUIRED_SETUP_PLAYBOOKS = [
    "sudo.yml", "openssh_config.yml", "set_hostname.yml",
    "basics.yml", "unattendedInstall.yml", "reboot.yml",
]


@pytest.fixture
def setup_playbooks(isolated_env):
    for name in REQUIRED_SETUP_PLAYBOOKS:
        isolated_env.write_playbook(name)
    isolated_env.write_playbook("sshsetup.sh", "#!/bin/sh\n")
    return isolated_env


class Selector:
    """Feeds canned answers to ask_select and records every call."""

    def __init__(self, monkeypatch, answers):
        self.answers = list(answers)
        self.calls = []

        def fake_select(message, choices, default=None):
            self.calls.append(message)
            if isinstance(self.answers[0], dict):
                return self.answers.pop(0).get(message)
            return self.answers.pop(0)

        monkeypatch.setattr(interactive, "ask_select", fake_select)
        monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)


# --------------------------------------------------------------- main menu

def test_main_action_defaults_to_quit_on_escape(monkeypatch):
    monkeypatch.setattr(interactive, "ask_select", lambda *a, **kw: None)
    assert interactive.pick_main_action() == "quit"


def test_interactive_loop_exits_on_quit(monkeypatch):
    monkeypatch.setattr(interactive, "ask_select", lambda *a, **kw: "quit")
    interactive.interactive_loop()  # returns instead of looping forever


def test_interactive_loop_dispatches_to_settings(monkeypatch):
    """Regression: Settings used to raise NameError — there was no function."""
    answers = iter(["settings", "quit"])
    entered = []

    def fake_select(message, choices, default=None):
        choice = next(answers)
        if choice == "settings":
            # prove the handler attribute actually resolves
            entered.append(interactive.settings_menu)
        return choice

    monkeypatch.setattr(interactive, "ask_select", fake_select)
    monkeypatch.setattr(interactive, "settings_menu", lambda: entered.append("called"))
    interactive.interactive_loop()
    assert entered[-1] == "called"  # Settings resolved and ran (used to be NameError)


def test_interactive_loop_history_escape_does_not_show_history(monkeypatch, projects):
    shown = []
    monkeypatch.setattr(interactive, "ask_select", lambda *a, **kw: None)
    monkeypatch.setattr(interactive, "show_history", lambda *a, **kw: shown.append(a))
    interactive.interactive_loop()
    assert shown == []


def test_interactive_loop_run_with_no_projects_breaks(monkeypatch, isolated_env):
    answers = iter(["run", "quit"])
    monkeypatch.setattr(interactive, "ask_select", lambda *a, **kw: next(answers))
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)
    interactive.interactive_loop()  # pick_project returns None -> back to main menu


# ----------------------------------------------------------------- menus

def test_settings_menu_clears_history(monkeypatch):
    database.add_run("alpha", "p.yml", "h", False, None, None, "success", 0, "")
    answers = iter(["clear_history", interactive.BACK])
    monkeypatch.setattr(interactive, "ask_select", lambda *a, **kw: next(answers))
    monkeypatch.setattr(interactive, "ask_confirm", lambda *a, **kw: True)
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)

    interactive.settings_menu()
    assert database.get_run_history() == []


def test_settings_menu_back_exits(monkeypatch):
    monkeypatch.setattr(interactive, "ask_select", lambda *a, **kw: interactive.BACK)
    interactive.settings_menu()  # must return


def test_inventory_menu_lists_hosts(monkeypatch, capsys):
    database.add_known_host("web1", "10.0.0.1", "web")
    answers = iter(["list", interactive.BACK])
    monkeypatch.setattr(interactive, "ask_select", lambda *a, **kw: next(answers))
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)

    interactive.inventory_menu()
    assert "web1" in capsys.readouterr().out


def test_inventory_menu_add_host(monkeypatch, isolated_env):
    answers = iter(["add", interactive.BACK])
    monkeypatch.setattr(interactive, "ask_select", lambda *a, **kw: next(answers))
    texts = iter(["web2", "10.0.0.2", "web"])
    monkeypatch.setattr(interactive, "ask_text", lambda *a, **kw: next(texts))
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)

    interactive.inventory_menu()
    hosts = database.get_known_hosts()
    assert hosts[0]["hostname"] == "web2"
    assert hosts[0]["address"] == "10.0.0.2"
    assert hosts[0]["inventory_group"] == "web"


def test_inventory_menu_remove_host(monkeypatch):
    database.add_known_host("web1", None, "all")
    answers = iter(["remove", "web1", interactive.BACK])
    monkeypatch.setattr(interactive, "ask_select", lambda *a, **kw: next(answers))
    monkeypatch.setattr(interactive, "ask_confirm", lambda *a, **kw: True)
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)

    interactive.inventory_menu()
    assert database.get_known_hosts() == []


# --------------------------------------------------------- machine setup

def test_machine_setup_returns_to_main_menu(monkeypatch, setup_playbooks):
    """Regression: finishing machine setup fell through into the Settings menu."""
    texts = iter(["10.0.0.5", "newhost", "all"])
    monkeypatch.setattr(interactive, "ask_text", lambda *a, **kw: next(texts))
    monkeypatch.setattr(interactive, "ask_password", lambda *a, **kw: "pw")
    monkeypatch.setattr(interactive, "ask_confirm", lambda *a, **kw: True)
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)
    monkeypatch.setattr(interactive, "run_machine_setup",
                        lambda *a, **kw: SubprocessResult(returncode=0, stdout="done"))
    monkeypatch.setattr(interactive.shutil, "which", lambda name: "/usr/bin/sshpass")

    def boom(*a, **kw):
        raise AssertionError("no menu should open after machine setup finishes")

    monkeypatch.setattr(interactive, "ask_select", boom)

    interactive.machine_setup_menu()  # must return without opening another menu


def test_machine_setup_adds_host_to_inventory(monkeypatch, setup_playbooks):
    texts = iter(["10.0.0.5", "newhost", "all"])
    monkeypatch.setattr(interactive, "ask_text", lambda *a, **kw: next(texts))
    monkeypatch.setattr(interactive, "ask_password", lambda *a, **kw: "pw")
    monkeypatch.setattr(interactive, "ask_confirm", lambda *a, **kw: True)
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)
    monkeypatch.setattr(interactive, "run_machine_setup",
                        lambda *a, **kw: SubprocessResult(returncode=0, stdout="done"))
    monkeypatch.setattr(interactive.shutil, "which", lambda name: "/usr/bin/sshpass")

    interactive.machine_setup_menu()

    hosts = database.get_known_hosts()
    assert hosts[0]["hostname"] == "newhost"
    assert hosts[0]["address"] == "10.0.0.5"


def test_machine_setup_aborts_without_host(monkeypatch, setup_playbooks):
    ran = []
    monkeypatch.setattr(interactive, "ask_text", lambda *a, **kw: "")
    monkeypatch.setattr(interactive, "run_machine_setup", lambda *a, **kw: ran.append(True))
    monkeypatch.setattr(interactive.shutil, "which", lambda name: "/usr/bin/sshpass")

    interactive.machine_setup_menu()
    assert ran == []


def test_machine_setup_warns_when_playbooks_missing(monkeypatch, isolated_env, capsys):
    monkeypatch.setattr(interactive.shutil, "which", lambda name: "/usr/bin/sshpass")
    interactive.machine_setup_menu()
    assert "Missing playbooks" in capsys.readouterr().out


def test_machine_setup_warns_without_sshpass(monkeypatch, setup_playbooks, capsys):
    texts = iter(["10.0.0.5", "newhost"])
    monkeypatch.setattr(interactive, "ask_text", lambda *a, **kw: next(texts))
    monkeypatch.setattr(interactive.shutil, "which", lambda name: None)
    monkeypatch.setattr(interactive, "pause", lambda *a, **kw: None)

    interactive.machine_setup_menu()
    assert "sshpass is not installed" in capsys.readouterr().out


# ------------------------------------------------------------ run settings

def test_get_run_settings_uses_all_hosts_sentinel(monkeypatch):
    monkeypatch.setattr(interactive, "ask_select", lambda *a, **kw: "__all__")
    monkeypatch.setattr(interactive, "ask_confirm", lambda *a, **kw: False)
    monkeypatch.setattr(interactive, "ask_text", lambda *a, **kw: "")

    settings = interactive.get_run_settings({"name": "alpha"})
    assert settings["host"] is None      # "__all__" -> None (no -l flag)
    assert settings["check_mode"] is False
    assert settings["tags"] is None
    assert settings["extra_vars"] is None


def test_get_run_settings_returns_none_when_cancelled(monkeypatch):
    monkeypatch.setattr(interactive, "ask_select", lambda *a, **kw: None)
    assert interactive.get_run_settings({"name": "alpha"}) is None


def test_run_settings_prefer_saved_host_as_default(monkeypatch):
    database.add_known_host("web1", "10.0.0.1")
    seen = {}

    def fake_select(message, choices, default=None):
        seen["default"] = default
        return "web1"

    monkeypatch.setattr(interactive, "ask_select", fake_select)
    monkeypatch.setattr(interactive, "ask_confirm", lambda *a, **kw: True)
    monkeypatch.setattr(interactive, "ask_text", lambda *a, **kw: "")

    settings = interactive.get_run_settings({"name": "alpha"},
                                            last_config={"host": "web1"})
    assert settings["host"] == "web1"
    assert seen["default"].value == "web1"


def test_pick_playbook_shows_relative_names(monkeypatch, projects):
    project = {"name": "multi", "playbooks": [str(projects.playbooks / "multi/a.yml"),
                                              str(projects.playbooks / "multi/b.yml")]}
    seen = {}

    def fake_select(message, choices, default=None):
        seen["titles"] = [c.title for c in choices]
        return choices[1].value

    monkeypatch.setattr(interactive, "ask_select", fake_select)
    chosen = interactive.pick_playbook(project)
    assert chosen.endswith("multi/b.yml")
    assert seen["titles"] == ["multi/a.yml", "multi/b.yml"]


def test_pick_playbook_skips_prompt_for_single_playbook():
    project = {"name": "one", "playbooks": ["one.yml"]}
    assert interactive.pick_playbook(project) == "one.yml"


def test_do_run_records_history_and_recap(monkeypatch, projects, isolated_env):
    import ansiblecli.interactive as mod

    isolated_env.hosts_file.parent.mkdir(parents=True, exist_ok=True)
    isolated_env.hosts_file.write_text("all:\n  hosts: {}\n")

    monkeypatch.setattr("ansiblecli.runner.run_playbook",
                        lambda *a, **kw: SubprocessResult(
                            returncode=0,
                            stdout="PLAY RECAP *****\nweb1 : ok=3 failed=0\n"))
    monkeypatch.setattr("ansiblecli.inventory.write_inventory_file", lambda *a: None)

    result = mod._do_run(
        {"name": "alpha"}, "alpha/playbook.yml",
        {"host": "web1", "check_mode": False, "tags": None, "extra_vars": None, "save": True},
    )

    assert result.returncode == 0
    rows = database.get_run_history("alpha")
    assert rows[0]["status"] == "success"
    assert rows[0]["recap"] == "web1: ok=3  failed=0"
    assert rows[0]["finished_at"] >= rows[0]["started_at"]
    assert database.get_last_config("alpha")["host"] == "web1"


def test_show_run_result_handles_missing_result(capsys):
    interactive.show_run_result(None, "missing.yml")
    assert "failed to start" in capsys.readouterr().out
