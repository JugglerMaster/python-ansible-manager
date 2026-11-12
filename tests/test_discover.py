from ansiblecli.discover import discover_projects, get_project


def test_standalone_playbooks_become_projects(projects):
    names = {p["name"] for p in discover_projects()}
    assert names == {"alpha", "beta", "gamma"}


def test_directory_project_uses_dir_name_and_recurses(projects):
    alpha = get_project("alpha")
    assert alpha["name"] == "alpha"
    assert len(alpha["playbooks"]) == 1
    assert alpha["playbooks"][0].endswith("alpha/playbook.yml")


def test_description_comes_from_playbook_head(projects):
    projects.write_playbook("described/site.yml",
                            "- name: Set up the thing\n  description: A described project\n"
                            "  hosts: all\n  tasks: []\n")
    described = get_project("described")
    assert described["description"] == "A described project"


def test_description_falls_back_to_name(projects):
    assert get_project("beta")["description"] == "beta"


def test_missing_playbooks_dir_returns_empty(isolated_env, monkeypatch):
    monkeypatch.setattr("ansiblecli.discover.get_config",
                        lambda key: str(isolated_env.app_dir / "nope"))
    assert discover_projects() == []


def test_dirs_without_playbooks_are_skipped(projects):
    projects.playbooks.mkdir(exist_ok=True)
    (projects.playbooks / "empty-project").mkdir()
    assert "empty-project" not in {p["name"] for p in discover_projects()}


def test_broken_yaml_still_discovers(projects):
    projects.write_playbook("broken.yml", "- hosts: all\n  tasks: [ unclosed\n")
    assert get_project("broken") is not None


def test_get_project_returns_none_for_unknown(projects):
    assert get_project("does-not-exist") is None


def test_mtime_reflects_newest_playbook(projects):
    import os
    import time
    older = projects.write_playbook("timed/first.yml")
    time.sleep(0.01)
    newer = projects.write_playbook("timed/second.yml")
    os.utime(older, (0, 0))
    project = get_project("timed")
    assert project["mtime"] == max(
        os.path.getmtime(p) for p in [str(older), str(newer)]
    )
