from datetime import datetime
from pathlib import Path

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ansiblecli import __version__, database
from ansiblecli.config import get as get_config, set_key
from ansiblecli.discover import discover_projects
from ansiblecli.machinesetup import resolve_script_path, run_setup_script, run_machine_setup

console = Console()


def parse_recap(output):
    if not output:
        return None
    lines = output.splitlines()
    in_recap = False
    host_summaries = []
    for line in lines:
        if "PLAY RECAP" in line:
            in_recap = True
            continue
        if in_recap:
            stripped = line.strip()
            if not stripped:
                continue
            if ":" in stripped:
                hostname, pairs = stripped.split(":", 1)
                hostname = hostname.strip()
                pairs = pairs.strip()
                kept = []
                for part in pairs.split():
                    if "=" in part:
                        k, v = part.split("=", 1)
                        if k in ("ok", "failed", "unreachable"):
                            kept.append(f"{k}={v}")
                if kept:
                    host_summaries.append(f"{hostname}: {'  '.join(kept)}")
            else:
                break
    return " | ".join(host_summaries) if host_summaries else None


def pick_main_action():
    choices = [
        questionary.Choice(title="▶  Run a playbook", value="run"),
        questionary.Choice(title="   Manage inventory", value="inventory"),
        questionary.Choice(title="   Machine Setup", value="machinesetup"),
        questionary.Choice(title="   View run history", value="history"),
        questionary.Choice(title="   Settings", value="settings"),
        questionary.Choice(title="   Quit", value="quit"),
    ]
    result = questionary.select(
        "What would you like to do?",
        choices=choices,
    ).ask()
    return result if result is not None else "quit"


def pick_project():
    projects = discover_projects()
    if not projects:
        console.print("[yellow]No projects found in playbooks/ directory.[/yellow]")
        console.print("Create a subdirectory under [bold]playbooks/[/bold] with a .yml file.")
        return None, None

    from ansiblecli.picker import ProjectPicker
    return ProjectPicker(projects).run()


def pick_playbook(project):
    if len(project["playbooks"]) == 1:
        return project["playbooks"][0]

    choices = [questionary.Choice(title=p, value=p) for p in project["playbooks"]]
    result = questionary.select(
        f"Multiple playbooks found in '{project['name']}'. Choose one:",
        choices=choices,
    ).ask()
    return result if result else project["playbooks"][0]


def get_run_settings(project, last_config=None):
    try:
        hosts = database.get_known_hosts()
        default_host = last_config.get("host") if last_config else None
        all_hosts_choice = questionary.Choice(title="All hosts", value="__all__")

        if not hosts:
            host = questionary.select(
                "Target host:",
                choices=[all_hosts_choice, questionary.Choice(title="+ Enter specific host...", value="__custom__")],
                default=all_hosts_choice,
            ).ask()
            if host is None:
                return None
            if host == "__custom__":
                host = questionary.text("Target host (hostname or IP):").ask()
                if host is None:
                    return None
        else:
            host_choices = [all_hosts_choice] + [questionary.Choice(title=h["hostname"], value=h["hostname"]) for h in hosts]
            host_choices.append(questionary.Choice(title="+ Enter custom host...", value="__custom__"))

            if default_host is None:
                default = all_hosts_choice
            else:
                found = [c for c in host_choices if c.value == default_host]
                default = found[0] if found else all_hosts_choice

            host = questionary.select(
                "Target host:",
                choices=host_choices,
                default=default,
            ).ask()
            if host is None:
                return None
            if host == "__custom__":
                host = questionary.text("Target host (hostname or IP):").ask()
                if host is None:
                    return None

        check_default = bool(last_config.get("check_mode")) if last_config else False
        check_label = "[Y/n]" if check_default else "[y/N]"
        check_mode = questionary.confirm(
            f"Dry run (--check mode)? {check_label}",
            default=check_default,
        ).ask()
        if check_mode is None:
            return None

        last_tags = last_config.get("tags") if last_config else ""
        tags = questionary.text(
            "Tags (comma-separated, optional):",
            default=last_tags or "",
        ).ask()
        if tags is None:
            return None
        tags = tags or None

        last_vars = last_config.get("extra_vars") if last_config else ""
        extra_vars = questionary.text(
            "Extra vars (key=val,key=val, optional):",
            default=last_vars or "",
        ).ask()
        if extra_vars is None:
            return None
        extra_vars = extra_vars or None

        save = questionary.confirm("Save these settings as default? [Y/n]", default=True).ask()
        if save is None:
            return None

        return {
            "host": None if host == "__all__" else (host or None),
            "check_mode": check_mode,
            "tags": tags,
            "extra_vars": extra_vars,
            "save": save,
        }
    except KeyboardInterrupt:
        return None


def show_history(project_name=None):
    rows = database.get_run_history(project_name, limit=30)
    if not rows:
        console.print("[yellow]No run history yet.[/yellow]")
        return

    table = Table(title=f"Run History{' - ' + project_name if project_name else ''}")
    table.add_column("Date", style="dim")
    table.add_column("Project")
    table.add_column("Host")
    table.add_column("Status")
    table.add_column("Host Results")
    table.add_column("Duration")

    for r in rows:
        started = r["started_at"]
        if started:
            try:
                dt = datetime.fromisoformat(started)
                started = dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass

        finished = r["finished_at"]
        duration = ""
        if r["started_at"] and r["finished_at"]:
            try:
                d1 = datetime.fromisoformat(r["started_at"])
                d2 = datetime.fromisoformat(r["finished_at"])
                secs = (d2 - d1).total_seconds()
                duration = f"{secs:.0f}s"
            except ValueError:
                pass

        status_style = {
            "success": "green",
            "failed": "red",
            "cancelled": "yellow",
        }.get(r["status"], "white")

        recap = ""
        if r.get("recap"):
            recap_str = ""
            for host_rec in r["recap"].split(" | "):
                if ":" in host_rec:
                    hname, rest = host_rec.split(":", 1)
                    hname = hname.strip()
                    rest = rest.strip()
                else:
                    hname, rest = "", host_rec.strip()
                pairs = []
                for pair in rest.split():
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        if k == "ok":
                            pairs.append(f"[green]ok={v}[/green]")
                        elif k == "failed":
                            pairs.append(f"[red]failed={v}[/red]")
                        elif k == "unreachable":
                            pairs.append(f"[yellow]unreachable={v}[/yellow]")
                if recap_str:
                    recap_str += " [dim]|[/dim] "
                if hname:
                    recap_str += f"[bold]{hname}:[/bold] "
                recap_str += "  ".join(pairs)
            recap = recap_str

        table.add_row(
            str(started or ""),
            r["project"],
            r["host"] or "all",
            Text(r["status"], style=status_style),
            recap,
            duration,
        )

    console.print(table)


def show_run_result(result, playbook_path):
    if result is None:
        console.print("[red]Playbook execution failed to start.[/red]")
        return

    status = "success" if result.returncode == 0 else "failed"

    panel = Panel(
        f"[bold]{'[OK]' if status == 'success' else '[FAIL]'} Playbook finished with exit code {result.returncode}[/bold]",
        title="Result",
        border_style="green" if status == "success" else "red",
    )
    console.print(panel)


def _do_run(project, playbook_path, settings):
    if settings.get("save"):
        database.save_last_config(
            project["name"],
            settings["host"],
            settings["check_mode"],
            settings["tags"],
            settings["extra_vars"],
        )

    if settings.get("host"):
        database.update_host_last_used(settings["host"])

    from ansiblecli.runner import run_playbook
    from ansiblecli.inventory import write_inventory_file
    write_inventory_file()

    from datetime import datetime, timezone
    started_at = datetime.now(timezone.utc).isoformat()

    result = run_playbook(
        playbook_path,
        host=settings["host"],
        check_mode=settings["check_mode"],
        tags=settings["tags"],
        extra_vars=settings["extra_vars"],
    )

    finished_at = datetime.now(timezone.utc).isoformat()

    status = "failed"
    exit_code = -1
    output = None

    recap = None
    if result is not None:
        status = "success" if result.returncode == 0 else "failed"
        exit_code = result.returncode
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()[:5000] or None
        recap = parse_recap(result.stdout)

    database.add_run(
        project["name"],
        playbook_path,
        settings["host"],
        settings["check_mode"],
        settings["tags"],
        settings["extra_vars"],
        status,
        exit_code,
        output,
        started_at=started_at,
        finished_at=finished_at,
        recap=recap,
    )

    return result


def _run_and_loop(project, playbook_path, settings):
    result = _do_run(project, playbook_path, settings)
    show_run_result(result, playbook_path)


def _run_with_last_or_settings(project, playbook_path):
    last = database.get_last_config(project["name"])
    if last:
        settings = {
            "host": last.get("host"),
            "check_mode": bool(last.get("check_mode")),
            "tags": last.get("tags"),
            "extra_vars": last.get("extra_vars"),
            "save": False,
        }
        _run_and_loop(project, playbook_path, settings)
    else:
        settings = get_run_settings(project, last)
        if settings is None:
            return
        _run_and_loop(project, playbook_path, settings)


def inventory_menu():
    while True:
        console.clear()
        console.print(Panel(f"[bold]AnsibleCLI v{__version__}[/bold] — Interactive Playbook Manager", border_style="cyan"))
        console.print()
        choices = [
            questionary.Choice(title="   List hosts", value="list"),
            questionary.Choice(title="   Add a host", value="add"),
            questionary.Choice(title="   Remove a host", value="remove"),
            questionary.Choice(title="   List groups", value="groups"),
            questionary.Choice(title="←  Back to main menu", value="back"),
        ]
        action = questionary.select("Inventory Management:", choices=choices).ask()

        if action is None or action == "back":
            break

        if action == "list":
            hosts = database.get_known_hosts()
            if not hosts:
                console.print("[yellow]No hosts in inventory.[/yellow]")
                continue
            table = Table(title="Known Hosts")
            table.add_column("Hostname")
            table.add_column("Address")
            table.add_column("Group")
            table.add_column("Last Used")
            for h in hosts:
                last = ""
                if h.get("last_used"):
                    try:
                        dt = datetime.fromisoformat(h["last_used"])
                        last = dt.strftime("%Y-%m-%d")
                    except ValueError:
                        last = h["last_used"]
                table.add_row(
                    h["hostname"],
                    h.get("address") or "-",
                    h.get("inventory_group") or "all",
                    last,
                )
            console.print(table)

        elif action == "add":
            hostname = questionary.text("Hostname:").ask()
            if not hostname:
                continue
            address = questionary.text("Address (IP, optional):").ask() or None
            group = questionary.text("Inventory group (default: all):", default="all").ask() or "all"
            from ansiblecli.inventory import add_host
            add_host(hostname, address, group)
            console.print(f"[green]Added {hostname} to inventory.[/green]")

        elif action == "remove":
            hosts = database.get_known_hosts()
            if not hosts:
                console.print("[yellow]No hosts to remove.[/yellow]")
                continue
            host_choices = [h["hostname"] for h in hosts]
            hostname = questionary.select("Select host to remove:", choices=host_choices).ask()
            if hostname and questionary.confirm(f"Remove {hostname}?").ask():
                from ansiblecli.inventory import remove_host
                remove_host(hostname)
                console.print(f"[green]Removed {hostname}.[/green]")

        elif action == "groups":
            from ansiblecli.inventory import list_groups
            groups = list_groups()
            if not groups:
                console.print("[yellow]No groups defined.[/yellow]")
            else:
                console.print("[bold]Inventory groups:[/bold]")
                for g in groups:
                    console.print(f"  - {g}")


def machine_setup_menu():
    console.clear()
    console.print(Panel(f"[bold]AnsibleCLI v{__version__}[/bold] — Machine Setup", border_style="cyan"))
    console.print()

    # Check if playbooks exist (app-driven mode)
    from ansiblecli.config import get as get_config
    playbooks_dir = Path(get_config("playbooks_dir"))
    required_playbooks = ["sudo.yml", "openssh_config.yml", "set_hostname.yml",
                          "basics.yml", "unattendedInstall.yml", "reboot.yml"]
    missing = [p for p in required_playbooks if not (playbooks_dir / p).exists()]

    if missing:
        console.print(f"[yellow]Missing playbooks: {', '.join(missing)}[/yellow]")
        console.print("Machine setup requires all playbooks to be present.")
        action = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice(title="←  Back to main menu", value="back"),
            ],
        ).ask()
        return

    # Always prompt for target host
    host = questionary.text("Target host (hostname or IP):").ask()
    if not host:
        return

    # Always prompt for hostname (no default)
    hostname = questionary.text("Machine hostname (for set_hostname.yml): ").ask()
    if not hostname:
        console.print("[yellow]Hostname is required. Aborting.[/yellow]")
        return

    # Check for sshpass (required for non-interactive ssh-copy-id)
    import shutil
    if not shutil.which("sshpass"):
        console.print("[red]sshpass is not installed.[/red]")
        console.print("  [dim]sshpass provides the SSH password to ssh-copy-id non-interactively.[/dim]")
        console.print("  [dim]Install it with: sudo apt install sshpass[/dim]")
        console.print()
        action = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice(title="←  Back to main menu", value="back"),
            ],
        ).ask()
        return

    # SSH password for ssh-copy-id (remote user's login password)
    ssh_pass = questionary.password("SSH password for remote user (dadisc01): ").ask()
    if not ssh_pass:
        console.print("[yellow]SSH password is required for ssh-copy-id. Aborting.[/yellow]")
        return

    # Become pass: show saved value as option, always confirm choice
    saved_pass = get_config("machine_setup_become_pass") or None
    if saved_pass:
        use_saved = questionary.confirm(
            f"Use saved become password? (saved)", default=True
        ).ask()
        if use_saved is False:
            console.print("[dim]Enter a new become password:[/dim]")
            become_pass = questionary.password("Become password: ").ask()
            save_new = questionary.confirm("Save this password for next time?", default=False).ask()
            if save_new:
                set_key("machine_setup_become_pass", become_pass)
        else:
            become_pass = saved_pass
    else:
        console.print("[dim]No saved become password.[/dim]")
        become_pass = questionary.password("Become password: ").ask()
        if become_pass:
            save_pass = questionary.confirm("Save this password for next time?", default=False).ask()
            if save_pass:
                set_key("machine_setup_become_pass", become_pass)

    if not become_pass:
        console.print("[yellow]No become password provided. Aborting.[/yellow]")
        return

    # Summary and confirm
    console.clear()
    console.print(Panel(f"[bold]AnsibleCLI v{__version__}[/bold] — Machine Setup", border_style="cyan"))
    console.print()
    console.print(f"Host:       [bold]{host}[/bold]")
    console.print(f"Hostname:   [bold]{hostname}[/bold]")
    console.print(f"Password:   {'[green]configured[/green]' if become_pass else '[dim]none[/dim]'}")
    console.print()

    if not questionary.confirm("Run machine setup?", default=True).ask():
        return

    # Run the playbook sequence directly (app-driven)
    console.clear()
    console.print(Panel(f"[bold]AnsibleCLI v{__version__}[/bold] — Machine Setup", border_style="cyan"))
    console.print()
    console.print(f"[cyan]Running machine setup on [bold]{host}[/bold]...[/cyan]")

    result = run_machine_setup(host, hostname, ssh_pass, become_pass)

    if result is None:
        console.print("\n[red]Failed to start machine setup.[/red]")
        console.input("[dim]Press Enter to return...[/dim]")
        return

    console.print()
    if result.returncode == 0:
        console.print(f"[green bold]✓ Machine setup completed successfully for {host}.[/green bold]")
        add_inv = questionary.confirm("Add host to inventory?", default=True).ask()
        if add_inv:
            group = questionary.text("Inventory group (default: all):", default="all").ask() or "all"
            from ansiblecli.inventory import add_host
            add_host(host, address=host, group=group)
            console.print(f"[green]+[/green] Added [bold]{host}[/bold] to inventory (group: {group}).")
    else:
        console.print(f"[red bold]✗ Machine setup failed with exit code {result.returncode}.[/red bold]")

    console.input("[dim]Press Enter to return...[/dim]")
    while True:
        console.clear()
        console.print(Panel(f"[bold]AnsibleCLI v{__version__}[/bold] — Settings", border_style="cyan"))
        console.print()
        choices = [
            questionary.Choice(title="   Clear run history", value="clear"),
            questionary.Choice(title="←  Back to main menu", value="back"),
        ]
        action = questionary.select("Settings:", choices=choices).ask()

        if action is None or action == "back":
            break

        if action == "clear":
            if questionary.confirm("Clear all run history?").ask():
                database.get_connection().execute("DELETE FROM run_history").connection.commit()
                console.print("[green]Run history cleared.[/green]")
            else:
                console.print("[dim]Cancelled.[/dim]")
            console.input("[dim]Press Enter to continue...[/dim]")


def interactive_loop():
    projects = discover_projects()

    while True:
        console.clear()
        console.print(Panel(f"[bold]AnsibleCLI v{__version__}[/bold] — Interactive Playbook Manager", border_style="cyan"))
        if projects:
            console.print(f"[green]+[/green] Found [bold]{len(projects)}[/bold] playbook project{'s' if len(projects) != 1 else ''}")
        else:
            console.print("[yellow]No playbook projects found in playbooks/ directory.[/yellow]")
            console.print("Create a subdirectory under [bold]playbooks/[/bold] with a .yml or .yaml file.")
        console.print()

        try:
            action = pick_main_action()
        except KeyboardInterrupt:
            break

        if action == "quit":
            break

        if action == "run":
            while True:
                console.clear()
                console.print(Panel(f"[bold]AnsibleCLI v{__version__}[/bold] — Interactive Playbook Manager", border_style="cyan"))
                console.print()
                project, proj_action = pick_project()
                if project is None:
                    break

                playbook_path = pick_playbook(project)
                if not playbook_path:
                    continue

                if proj_action == "history":
                    console.clear()
                    show_history(project["name"])
                    console.input("[dim]Press Enter to return...[/dim]")
                    continue

                if proj_action == "view":
                    try:
                        with open(playbook_path) as f:
                            content = f.read()
                        help_bar = Text("  ↑↓ scroll  •  / search  •  q close  ", style="white on blue")
                        syntax = Syntax(content, "yaml", line_numbers=True, theme="one-dark")
                        with console.pager():
                            console.print(help_bar)
                            console.print(Panel(syntax, title=playbook_path, border_style="blue"))
                    except OSError as e:
                        console.print(f"[red]Error reading playbook: {e}[/red]")
                        console.input("[dim]Press Enter to return...[/dim]")
                    continue

                if proj_action == "settings":
                    last = database.get_last_config(project["name"])
                    settings = get_run_settings(project, last)
                    if settings is None:
                        continue
                    _run_and_loop(project, playbook_path, settings)
                    continue

                if proj_action == "run":
                    _run_with_last_or_settings(project, playbook_path)
                    continue

        elif action == "inventory":
            inventory_menu()

        elif action == "machinesetup":
            machine_setup_menu()

        elif action == "history":
            projects = discover_projects()
            proj_choices = [p["name"] for p in projects]
            proj_choices.insert(0, "All projects")
            selected = questionary.select("Show history for:", choices=proj_choices).ask()
            console.clear()
            if selected == "All projects":
                show_history()
            else:
                show_history(selected)
            console.input("[dim]Press Enter to return...[/dim]")

        elif action == "settings":
            settings_menu()
