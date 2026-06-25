from pathlib import Path

import yaml

from ansiblecli import database
from ansiblecli.config import get as get_config


def export_inventory():
    hosts = database.get_known_hosts()
    inv = {"all": {"hosts": {}, "children": {}}}

    groups = {}
    for h in hosts:
        hostname = h["hostname"]
        address = h.get("address") or hostname
        inv["all"]["hosts"][hostname] = {"ansible_host": address}

        group = h.get("inventory_group", "all")
        if group and group != "all":
            if group not in groups:
                groups[group] = []
            groups[group].append(hostname)

    if groups:
        inv["all"]["children"] = {}
        for gname, ghosts in groups.items():
            inv["all"]["children"][gname] = {"hosts": {h: {} for h in ghosts}}

    return inv


def write_inventory_file():
    inv_dir = Path(get_config("inventory_dir"))
    inv_dir.mkdir(parents=True, exist_ok=True)
    inv_file = inv_dir / get_config("inventory_file")

    data = export_inventory()
    with open(inv_file, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return inv_file


def list_hosts():
    return database.get_known_hosts()


def add_host(hostname, address=None, group="all", os_type=None):
    database.add_known_host(hostname, address, group, os_type)
    write_inventory_file()


def remove_host(hostname):
    database.remove_known_host(hostname)
    write_inventory_file()


def list_groups():
    return database.get_inventory_groups()


def create_group(name):
    if name == "all":
        return
    existing = database.get_known_hosts()
    database.add_known_host(f"__group_anchor_{name}__", address=None, inventory_group=name, os_type=None)
    for h in existing:
        if h["inventory_group"] == name:
            return
    write_inventory_file()


def add_host_to_group(hostname, group):
    hosts = database.get_known_hosts()
    for h in hosts:
        if h["hostname"] == hostname:
            database.add_known_host(hostname, h.get("address"), group, h.get("os_type"))
            write_inventory_file()
            return


def remove_host_from_group(hostname):
    hosts = database.get_known_hosts()
    for h in hosts:
        if h["hostname"] == hostname and h["inventory_group"] != "all":
            database.add_known_host(hostname, h.get("address"), "all", h.get("os_type"))
            write_inventory_file()
            return
