from datetime import datetime

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ansiblecli import database
from ansiblecli.discover import discover_projects

console = Console()


def pick_main_action():
    choices = [
        questionary.Choice(title="▶  Run a playbook", value="run"),
        questionary.Choice(title="   Manage inventory", value="inventory"),
        questionary.Choice(title="   View run history", value="history"),
        questionary.Choice(title="   Quit", value="quit"),
    ]
    return questionary.select(
        "What would you like to do?",
        choices=choices,
    ).ask()


def pick_project():
    projects = discover_projects()
    if not projects:
        console.print("[yellow]No projects found in playbooks/ directory.[/yellow]")
        console.print("Create a subdirectory under [bold]playbooks/[/bold] with a .yml file.")
        return None

    choices = []
    for p in projects:
        last = database.get_last_config(p["name"])
        suffix = ""
        if last:
            host_info = f" (last: {last['host']})" if last.get("host") else ""
            suffix = f"[dim]Last run: yes{host_info}[/dim]"
        else:
            suffix = "[dim]Never run[/dim]"
        choices.append(questionary.Choice(
            title=f"{p['name']}  {suffix}",
            value=p["name"],
        ))

    choices.append(questionary.Choice(title="←  Back", value="__back__"))

    result = questionary.select("Select a playbook project:", choices=choices).ask()
    if result == "__back__":
        return None
    for p in projects:
        if p["name"] == result:
            return p
    return None


def pick_playbook(project):
    if len(project["playbooks"]) == 1:
        return project["playbooks"][0]

    choices = [questionary.Choice(title=p, value=p) for p in project["playbooks"]]
    result = questionary.select(
        f"Multiple playbooks found in '{project['name']}'. Choose one:",
        choices=choices,
    ).ask()
    return result


def project_menu(project):
    last = database.get_last_config(project["name"])

    choices = []
    if last:
        host_display = last.get("host") or "(no host)"
        choices.append(questionary.Choice(
            title=f"▶  Run with last config (host: {host_display})",
            value="run_last",
        ))
    choices.append(questionary.Choice(title="   Change settings", value="run_settings"))
    choices.append(questionary.Choice(title="   View run history", value="history"))
    choices.append(questionary.Choice(title="   View playbook", value="view"))
    choices.append(questionary.Choice(title="←  Back to projects", value="back"))

    return questionary.select(
        f"Project: {project['name']}",
        choices=choices,
    ).ask()


def get_run_settings(project, last_config=None):
    hosts = database.get_known_hosts()
    host_choices = [h["hostname"] for h in hosts] if hosts else []
    default_host = last_config.get("host") if last_config else None

    if not host_choices:
        host = questionary.text("Target host (hostname or IP):", default=default_host or "").ask()
    else:
        host = questionary.select(
            "Target host:",
            choices=host_choices + [questionary.Choice(title="+ Enter custom host...", value="__custom__")],
            default=default_host or host_choices[0],
        ).ask()
        if host == "__custom__":
            host = questionary.text("Target host (hostname or IP):", default=default_host or "").ask()

    check_mode = questionary.confirm(
        "Dry run (--check mode)?",
        default=bool(last_config.get("check_mode")) if last_config else False,
    ).ask()

    last_tags = last_config.get("tags") if last_config else ""
    tags = questionary.text(
        "Tags (comma-separated, optional):",
        default=last_tags or "",
    ).ask() or None

    last_vars = last_config.get("extra_vars") if last_config else ""
    extra_vars = questionary.text(
        "Extra vars (key=val,key=val, optional):",
        default=last_vars or "",
    ).ask() or None

    save = questionary.confirm("Save these settings as default?").ask()

    return {
        "host": host or None,
        "check_mode": check_mode,
        "tags": tags,
        "extra_vars": extra_vars,
        "save": save,
    }


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
        if started and finished:
            try:
                d1 = datetime.fromisoformat(r["started_at"])
                d2 = datetime.fromisoformat(finished)
                secs = (d2 - d1).total_seconds()
                duration = f"{secs:.0f}s"
            except ValueError:
                pass

        status_style = {
            "success": "green",
            "failed": "red",
            "cancelled": "yellow",
        }.get(r["status"], "white")

        table.add_row(
            str(started or ""),
            r["project"],
            r["host"] or "-",
            Text(r["status"], style=status_style),
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

    if result.stdout:
        console.print("[bold]Output:[/bold]")
        console.print(result.stdout[:2000])

    if result.stderr:
        console.print("[bold]Errors:[/bold]")
        console.print(result.stderr[:1000])


def inventory_menu():
    while True:
        choices = [
            questionary.Choice(title="   List hosts", value="list"),
            questionary.Choice(title="   Add a host", value="add"),
            questionary.Choice(title="   Remove a host", value="remove"),
            questionary.Choice(title="   List groups", value="groups"),
            questionary.Choice(title="←  Back to main menu", value="back"),
        ]
        action = questionary.select("Inventory Management:", choices=choices).ask()

        if action == "back":
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


def interactive_loop():
    console.print(Panel("[bold]AnsibleCLI[/bold] - Interactive Playbook Manager", border_style="cyan"))
    console.print()

    while True:
        action = pick_main_action()

        if action == "quit":
            break

        if action == "run":
            project = pick_project()
            if not project:
                continue

            playbook_path = pick_playbook(project)
            if not playbook_path:
                continue

            while True:
                menu_action = project_menu(project)
                if menu_action == "back":
                    break

                if menu_action == "history":
                    show_history(project["name"])
                    continue

                if menu_action == "view":
                    try:
                        with open(playbook_path) as f:
                            content = f.read()
                        console.print(Panel(content, title=playbook_path, border_style="blue"))
                    except OSError as e:
                        console.print(f"[red]Error reading playbook: {e}[/red]")
                    continue

                last = database.get_last_config(project["name"])
                if menu_action == "run_last":
                    settings = {
                        "host": last.get("host") if last else None,
                        "check_mode": bool(last.get("check_mode")) if last else False,
                        "tags": last.get("tags") if last else None,
                        "extra_vars": last.get("extra_vars") if last else None,
                        "save": False,
                    }
                else:
                    settings = get_run_settings(project, last)

                if settings["save"]:
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

                result = run_playbook(
                    playbook_path,
                    host=settings["host"],
                    check_mode=settings["check_mode"],
                    tags=settings["tags"],
                    extra_vars=settings["extra_vars"],
                )

                status = "failed"
                exit_code = -1
                output = None

                if result is not None:
                    status = "success" if result.returncode == 0 else "failed"
                    exit_code = result.returncode
                    output = (result.stdout or "") + "\n" + (result.stderr or "")
                    output = output.strip()[:5000] or None

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
                )

                show_run_result(result, playbook_path)

                cont = questionary.confirm("Run again?", default=False).ask()
                if not cont:
                    break

        elif action == "inventory":
            inventory_menu()

        elif action == "history":
            projects = discover_projects()
            proj_choices = [p["name"] for p in projects]
            proj_choices.insert(0, "All projects")
            selected = questionary.select("Show history for:", choices=proj_choices).ask()
            if selected == "All projects":
                show_history()
            else:
                show_history(selected)
