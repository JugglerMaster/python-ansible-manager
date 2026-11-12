import yaml

from ansiblecli import database
from ansiblecli.inventory import (
    add_host,
    export_inventory,
    list_groups,
    list_hosts,
    remove_host,
)


def test_export_inventory_defaults_address_to_hostname():
    add_host("server1", None, "all")
    inv = export_inventory()
    assert inv["all"]["hosts"]["server1"] == {"ansible_host": "server1"}


def test_export_inventory_groups_become_children():
    add_host("web1", "10.0.0.1", "web")
    add_host("web2", "10.0.0.2", "web")
    add_host("db1", "10.0.0.3", "db")
    inv = export_inventory()
    assert set(inv["all"]["children"]["web"]["hosts"]) == {"web1", "web2"}
    assert set(inv["all"]["children"]["db"]["hosts"]) == {"db1"}
    assert "web1" in inv["all"]["hosts"]


def test_group_all_is_not_nested_into_children():
    add_host("plain", None, "all")
    inv = export_inventory()
    assert "all" not in inv["all"].get("children", {})


def test_add_and_remove_host_rewrite_the_inventory_file(isolated_env):
    add_host("web1", "10.0.0.1", "web")
    written = yaml.safe_load(isolated_env.hosts_file.read_text())
    assert "web1" in written["all"]["hosts"]

    remove_host("web1")
    written = yaml.safe_load(isolated_env.hosts_file.read_text())
    assert "web1" not in written["all"]["hosts"]


def test_write_inventory_file_creates_missing_directory(isolated_env):
    assert not isolated_env.inventory.exists()
    add_host("one", "10.0.0.1")
    assert isolated_env.hosts_file.exists()


def test_list_hosts_reflects_database():
    database.add_known_host("only", "10.0.0.9", "web")
    assert [h["hostname"] for h in list_hosts()] == ["only"]


def test_list_groups_after_no_hosts():
    assert list_groups() == []


def test_updating_group_moves_host_between_children():
    add_host("web1", "10.0.0.1", "web")
    add_host("web1", "10.0.0.1", "db")
    inv = export_inventory()
    assert "web1" in inv["all"]["children"]["db"]["hosts"]
    assert "web" not in inv["all"]["children"]
