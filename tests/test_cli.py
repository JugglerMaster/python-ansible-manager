import yaml
from typer.testing import CliRunner

from ansiblecli import __version__, database
from ansiblecli.cli import app

runner = CliRunner()


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_list_shows_discovered_projects(projects):
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "alpha" in result.output
    assert "beta" in result.output


def test_list_with_no_projects(isolated_env):
    result = runner.invoke(app, ["list"])
    assert "No projects found" in result.output


def test_no_args_without_a_tty_prints_help(projects):
    result = runner.invoke(app, [])
    assert "Usage" in result.output  # guard: never hang on a piped invocation


def test_inventory_add_list_remove(projects):
    assert runner.invoke(app, ["inventory", "add", "web1",
                               "--address", "10.0.0.1", "--group", "web"]).exit_code == 0
    result = runner.invoke(app, ["inventory", "list"])
    assert "web1" in result.output
    assert "10.0.0.1" in result.output

    assert runner.invoke(app, ["inventory", "remove", "web1"]).exit_code == 0
    assert "web1" not in runner.invoke(app, ["inventory", "list"]).output


def test_inventory_show_writes_yaml(isolated_env):
    runner.invoke(app, ["inventory", "add", "web1", "--address", "10.0.0.1"])
    result = runner.invoke(app, ["inventory", "show"])
    data = yaml.safe_load(result.output)
    assert data["all"]["hosts"]["web1"]["ansible_host"] == "10.0.0.1"


def test_inventory_groups_lists_distinct_groups(isolated_env):
    runner.invoke(app, ["inventory", "add", "a", "--group", "web"])
    runner.invoke(app, ["inventory", "add", "b", "--group", "db"])
    result = runner.invoke(app, ["inventory", "groups"])
    assert "web" in result.output and "db" in result.output


def test_config_set_and_get(isolated_env):
    assert runner.invoke(app, ["config", "machine_setup_script", "custom.sh"]).exit_code == 0
    result = runner.invoke(app, ["config", "machine_setup_script"])
    assert "custom.sh" in result.output


def test_history_with_no_runs(projects):
    result = runner.invoke(app, ["history"])
    assert "No run history yet" in result.output


def test_run_requires_project(projects):
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 1
    assert "project name required" in result.output


def test_run_unknown_project(projects):
    result = runner.invoke(app, ["run", "nope"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_run_all_hosts_flag_omits_limit(projects, monkeypatch):
    database.save_last_config("alpha", "web1", False, None, None)
    projects.hosts_file.parent.mkdir(parents=True, exist_ok=True)
    projects.hosts_file.write_text("all:\n  hosts: {}\n")

    captured = {}

    def fake_run_playbook(path, host=None, check_mode=False, tags=None, extra_vars=None):
        captured["host"] = host
        from ansiblecli.runner import SubprocessResult
        return SubprocessResult(returncode=0, stdout="")

    monkeypatch.setattr("ansiblecli.runner.run_playbook", fake_run_playbook)

    result = runner.invoke(app, ["run", "alpha", "--all-hosts"])
    assert result.exit_code == 0
    assert captured["host"] is None  # no `-l` flag -> every inventory host


def test_machinesetup_requires_a_password(projects, monkeypatch):
    monkeypatch.setattr("ansiblecli.cli.sys.stdin", None)
    result = runner.invoke(app, ["machinesetup", "10.0.0.9"])
    assert result.exit_code == 1
    assert "SSH password is required" in result.output


def test_init_persists_resolved_paths(isolated_env):
    from ansiblecli.config import load_config

    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    config = load_config()
    assert config["playbooks_dir"] == str(isolated_env.playbooks.resolve())
    assert config["inventory_dir"] == str(isolated_env.inventory.resolve())
    assert isolated_env.hosts_file.exists()


def test_run_uses_last_config_and_records_history(projects, monkeypatch):
    database.save_last_config("alpha", "web1", False, None, None)
    isolated_env = projects
    isolated_env.hosts_file.parent.mkdir(parents=True, exist_ok=True)
    isolated_env.hosts_file.write_text("all:\n  hosts: {}\n")

    captured = {}

    def fake_run_playbook(path, host=None, check_mode=False, tags=None, extra_vars=None):
        captured.update(path=path, host=host)
        from ansiblecli.runner import SubprocessResult
        return SubprocessResult(returncode=0, stdout="PLAY RECAP\nweb1 : ok=1 failed=0\n")

    monkeypatch.setattr("ansiblecli.runner.run_playbook", fake_run_playbook)

    result = runner.invoke(app, ["run", "alpha"])
    assert result.exit_code == 0
    assert captured["host"] == "web1"
    rows = database.get_run_history("alpha")
    assert rows and rows[0]["status"] == "success"
