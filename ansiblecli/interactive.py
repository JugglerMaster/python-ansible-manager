import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ansiblecli import __version__, database
from ansiblecli import config as config_module
from ansiblecli.config import get as get_config
from ansiblecli.config import set_key
from ansiblecli.discover import discover_projects
from ansiblecli.machinesetup import run_machine_setup

console = Console()

APP_HEADER = f"[bold]AnsibleCLI v{__version__}[/bold]"
SUBTITLE_MAIN = "Interactive Playbook Manager"
BACK = "__back__"

# Select-hint + shared questionary theme so every menu looks identical.
SELECT_HINT = "  (↑↓ move · Enter select · Esc/Ctrl-C back)"
QUESTIONARY_STYLE = questionary.Style([
    ("qmark", "fg:cyan bold"),
    ("question", "bold"),
    ("answer", "fg:cyan bold"),
    ("pointer", "fg:cyan bold"),
    ("highlighted", "fg:cyan bold"),
    ("selected", "fg:cyan bold"),
    ("instruction", "fg:ansibrightblack"),
    ("text", ""),
])


def render_screen(subtitle=SUBTITLE_MAIN, lines=None):
    """Clear the screen and draw the standard menu header."""
    console.clear()
    console.print(Panel(f"{APP_HEADER} — {subtitle}", border_style="cyan"))
    for line in lines or []:
        console.print(line)
    console.print()


def pause(message="Press Enter to continue..."):
    """'Press Enter to continue' that survives non-interactive stdin / Ctrl-C."""
    prompt = f"[dim]{message}[/dim]"
    try:
        if not sys.stdin.isatty():
            # Piped/cron context: nobody can press Enter, so just show it.
            console.print(prompt)
            return
        console.input(prompt)
    except (EOFError, KeyboardInterrupt, OSError):
        console.print()


def ask_select(message, choices, default=None):
    """Consistent select prompt. Returns None on Esc/Ctrl-C."""
    try:
        return questionary.select(
            message,
            choices=choices,
            default=default,
            style=QUESTIONARY_STYLE,
            instruction=SELECT_HINT,
        ).ask()
    except KeyboardInterrupt:
        return None


def ask_text(message, default=""):
    """Consistent text prompt. Returns None on Esc/Ctrl-C."""
    try:
        return questionary.text(message, default=default, style=QUESTIONARY_STYLE).ask()
    except KeyboardInterrupt:
        return None


def ask_confirm(message, default=False):
    """Consistent confirm prompt. Returns None on Esc/Ctrl-C."""
    try:
        return questionary.confirm(message, default=default, style=QUESTIONARY_STYLE).ask()
    except KeyboardInterrupt:
        return None


def ask_password(message):
    """Consistent password prompt. Returns None on Esc/Ctrl-C."""
    try:
        return questionary.password(message, style=QUESTIONARY_STYLE).ask()
    except KeyboardInterrupt:
        return None


def back_choice(label="Back to main menu"):
    return questionary.Choice(title=f"←  {label}", value=BACK)


def dispatch_from(mapping):
    """Build a run_menu handler that calls the mapped action function."""

    def handler(action):
        fn = mapping.get(action)
        if fn is not None:
            fn()

    return handler


def run_menu(subtitle, prompt, items, handler, lines=None, back_label="Back to main menu"):
    """Render a standard menu until the user backs out.

    items: sequence of (title, value) pairs.
    handler: callable(value) invoked for every non-back selection.
    """
    while True:
        render_screen(subtitle, lines)
        choices = [questionary.Choice(title, value=value) for title, value in items]
        choices.append(back_choice(back_label))
        action = ask_select(prompt, choices)
        if action is None or action == BACK:
            return
        handler(action)


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


def pick_main_action(subtitle_lines=None):
    render_screen(SUBTITLE_MAIN, subtitle_lines)
    choices = [
        questionary.Choice(title="▶  Run a playbook", value="run"),
        questionary.Choice(title="   Manage inventory", value="inventory"),
        questionary.Choice(title="   Machine Setup", value="machinesetup"),
        questionary.Choice(title="   View run history", value="history"),
        questionary.Choice(title="   Settings", value="settings"),
        questionary.Choice(title="   Quit", value="quit"),
    ]
    result = ask_select("What would you like to do?", choices)
    return result if result is not None else "quit"


def pick_project():
    projects = discover_projects()
    if not projects:
        console.print("[yellow]No projects found in playbooks/ directory.[/yellow]")
        console.print("Create a subdirectory under [bold]playbooks/[/bold] with a .yml file.")
        pause("Press Enter to go back...")
        return None, None

    from ansiblecli.picker import ProjectPicker
    return ProjectPicker(projects).run()


def playbook_display_name(path):
    """Shorten an absolute playbook path for menus ('<project>/playbook.yml')."""
    try:
        playbooks_dir = Path(get_config("playbooks_dir"))
        return str(Path(path).resolve().relative_to(playbooks_dir.resolve()))
    except (ValueError, OSError):
        return Path(path).name


def pick_playbook(project):
    if len(project["playbooks"]) == 1:
        return project["playbooks"][0]

    choices = [
        questionary.Choice(title=playbook_display_name(p), value=p)
        for p in project["playbooks"]
    ]
    result = ask_select(
        f"Multiple playbooks found in '{project['name']}'. Choose one:",
        choices,
    )
    return result if result else project["playbooks"][0]


def get_run_settings(project, last_config=None):
    try:
        hosts = database.get_known_hosts()
        default_host = last_config.get("host") if last_config else None
        all_hosts_choice = questionary.Choice(title="All hosts", value="__all__")

        if not hosts:
            host = ask_select(
                "Target host:",
                [all_hosts_choice, questionary.Choice(title="+ Enter specific host...", value="__custom__")],
                default=all_hosts_choice,
            )
            if host is None:
                return None
            if host == "__custom__":
                host = ask_text("Target host (hostname or IP):")
                if host is None:
                    return None
        else:
            known = [questionary.Choice(title=h["hostname"], value=h["hostname"])
                     for h in hosts]
            host_choices = [all_hosts_choice, *known,
                            questionary.Choice(title="+ Enter custom host...", value="__custom__")]

            if default_host is None:
                default = all_hosts_choice
            else:
                found = [c for c in host_choices if c.value == default_host]
                default = found[0] if found else all_hosts_choice

            host = ask_select(
                "Target host:",
                host_choices,
                default=default,
            )
            if host is None:
                return None
            if host == "__custom__":
                host = ask_text("Target host (hostname or IP):")
                if host is None:
                    return None

        check_default = bool(last_config.get("check_mode")) if last_config else False
        check_label = "[Y/n]" if check_default else "[y/N]"
        check_mode = ask_confirm(
            f"Dry run (--check mode)? {check_label}",
            default=check_default,
        )
        if check_mode is None:
            return None

        last_tags = last_config.get("tags") if last_config else ""
        tags = ask_text(
            "Tags (comma-separated, optional):",
            default=last_tags or "",
        )
        if tags is None:
            return None
        tags = tags or None

        last_vars = last_config.get("extra_vars") if last_config else ""
        extra_vars = ask_text(
            "Extra vars (key=val,key=val, optional):",
            default=last_vars or "",
        )
        if extra_vars is None:
            return None
        extra_vars = extra_vars or None

        save = ask_confirm("Save these settings as default?", default=True)
        if save is None:
            return None

        return {
            "host": None if host == "__all__" else (host or None),
            "check_mode": check_mode,
            "tags": tags,
            "extra_vars": extra_vars,
            "become_password": get_config("become_password") or None,
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
    table.add_column("ID", style="dim")
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
            str(r["id"]),
            str(started or ""),
            r["project"],
            r["host"] or "all",
            Text(r["status"], style=status_style),
            recap,
            duration,
        )

    console.print(table)


def show_run_output(run_id, use_pager=True):
    """Print the stored ansible output for one run. Returns False if unknown id."""
    row = database.get_run_by_id(run_id)
    if row is None:
        return False

    header = (f"[bold]{row['project']}[/bold] — exit {row['exit_code']} "
              f"({row['status']}) — started {row['started_at']}")
    body = row.get("output") or "[dim](no output captured for this run)[/dim]"

    if use_pager:
        with console.pager():
            console.print(header)
            console.print()
            console.print(body)
    else:
        console.print(header)
        console.print()
        console.print(body)
    return True


def prompt_for_run_output(project_name=None):
    """Offer to open one run's stored output from the history screen."""
    choice = ask_text("Run ID to view output (blank to go back):")
    if not choice or not choice.strip():
        return False
    run_id = choice.strip().lstrip("#")
    if not run_id.isdigit():
        console.print("[yellow]That isn't a run ID from the table.[/yellow]")
        pause()
        return False

    if not show_run_output(int(run_id)):
        console.print(f"[yellow]No run with ID {run_id}.[/yellow]")
        pause()
        return False

    pause("Press Enter to return...")
    return True


def show_run_result(result, playbook_path):
    if result is None:
        console.print("[red]Playbook execution failed to start.[/red]")
        pause("Press Enter to return...")
        return

    status = "success" if result.returncode == 0 else "failed"
    recap = parse_recap(result.stdout)

    verdict = "[OK]" if status == "success" else "[FAIL]"
    body_lines = [f"[bold]{verdict} Playbook finished with exit code {result.returncode}[/bold]"]
    if recap:
        body_lines.append(f"\n[bold]Play Recap:[/bold]\n{recap}")

    panel = Panel(
        "\n".join(body_lines),
        title="Result",
        border_style="green" if status == "success" else "red",
    )
    console.print(panel)
    pause("Press Enter to return...")


CANCELLED = "__cancelled__"


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

    from ansiblecli.inventory import write_inventory_file
    write_inventory_file()

    started_at = datetime.now(timezone.utc).isoformat()

    from ansiblecli.runner import run_playbook
    try:
        result = run_playbook(
            playbook_path,
            host=settings["host"],
            check_mode=settings["check_mode"],
            tags=settings["tags"],
            extra_vars=settings["extra_vars"],
            become_password=settings.get("become_password"),
            verbose=settings.get("verbose", 0),
        )
    except KeyboardInterrupt:
        # Ctrl-C used to skip history entirely (the 'cancelled' status was dead
        # code) — record it so you can see what you aborted.
        database.add_run(
            project["name"], playbook_path, settings["host"], settings["check_mode"],
            settings["tags"], settings["extra_vars"], "cancelled", 130,
            "Interrupted by user (Ctrl-C)",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return CANCELLED

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
    if result is CANCELLED:
        console.print("[yellow]Run cancelled — nothing was changed by this tool.[/yellow]")
        pause("Press Enter to return...")
        return
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


def _inventory_list():
    hosts = database.get_known_hosts()
    if not hosts:
        console.print("[yellow]No hosts in inventory.[/yellow]")
        pause()
        return
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
    pause()


def _inventory_add():
    hostname = ask_text("Hostname:")
    if not hostname:
        console.print("[yellow]Cancelled — no hostname given.[/yellow]")
        pause()
        return
    address = ask_text("Address (IP, optional):") or None
    group = ask_text("Inventory group (default: all):", default="all") or "all"
    from ansiblecli.inventory import add_host
    add_host(hostname, address, group)
    console.print(f"[green]Added {hostname} to inventory.[/green]")


def _inventory_remove():
    hosts = database.get_known_hosts()
    if not hosts:
        console.print("[yellow]No hosts to remove.[/yellow]")
        pause()
        return
    host_choices = [h["hostname"] for h in hosts]
    hostname = ask_select("Select host to remove:", host_choices)
    if hostname and ask_confirm(f"Remove {hostname}?"):
        from ansiblecli.inventory import remove_host
        remove_host(hostname)
        console.print(f"[green]Removed {hostname}.[/green]")
    elif hostname:
        console.print("[dim]Cancelled.[/dim]")


def _inventory_groups():
    from ansiblecli.inventory import list_groups
    groups = list_groups()
    if not groups:
        console.print("[yellow]No groups defined.[/yellow]")
    else:
        console.print("[bold]Inventory groups:[/bold]")
        for g in groups:
            console.print(f"  - {g}")
    pause()


def inventory_menu():
    items = [
        ("   List hosts", "list"),
        ("   Add a host", "add"),
        ("   Remove a host", "remove"),
        ("   List groups", "groups"),
    ]
    handlers = {
        "list": _inventory_list,
        "add": _inventory_add,
        "remove": _inventory_remove,
        "groups": _inventory_groups,
    }
    run_menu("Inventory Management", "Inventory Management:", items,
             dispatch_from(handlers))


def machine_setup_menu():
    playbooks_dir = Path(get_config("playbooks_dir"))
    required_playbooks = ["sudo.yml", "openssh_config.yml", "set_hostname.yml",
                          "basics.yml", "unattendedInstall.yml", "reboot.yml"]
    missing = [p for p in required_playbooks if not (playbooks_dir / p).exists()]

    render_screen("Machine Setup")
    if missing:
        console.print(f"[yellow]Missing playbooks: {', '.join(missing)}[/yellow]")
        console.print("Machine setup requires all playbooks to be present.")
        pause()
        return

    # Always prompt for target host
    host = ask_text("Target host (hostname or IP):")
    if not host:
        return

    # Prompt for hostname (optional — leave blank to skip set_hostname.yml)
    hostname = ask_text("Machine hostname (leave blank to not set hostname):")
    hostname = hostname.strip() if hostname else ""

    # Check for sshpass (required for non-interactive ssh-copy-id)
    if not shutil.which("sshpass"):
        console.print("[red]sshpass is not installed.[/red]")
        console.print("  [dim]sshpass provides the SSH password to ssh-copy-id non-interactively.[/dim]")
        console.print("  [dim]Install it with: sudo apt install sshpass[/dim]")
        pause()
        return

    # SSH password for ssh-copy-id (remote user's login password)
    # Reuse the stored become password by default since sshsetup.sh uses it too.
    ssh_pass = _prompt_ssh_password()

    if not ssh_pass:
        console.print("[yellow]SSH password is required for ssh-copy-id. Aborting.[/yellow]")
        pause()
        return

    # Become pass: same password is used for ansible become
    become_pass = ssh_pass

    # Summary and confirm
    render_screen("Machine Setup", [
        f"Host:       [bold]{host}[/bold]",
        f"Hostname:   [bold]{hostname}[/bold]" if hostname else "Hostname:   [dim]not set[/dim]",
        f"Password:   {'[green]configured[/green]' if become_pass else '[dim]none[/dim]'}",
    ])

    if not ask_confirm("Run machine setup?", default=True):
        return

    render_screen("Machine Setup")
    console.print(f"[cyan]Running machine setup on [bold]{host}[/bold]...[/cyan]")

    result = run_machine_setup(host, hostname, ssh_pass, become_pass)

    if result is None:
        console.print("\n[red]Failed to start machine setup.[/red]")
        pause("Press Enter to return...")
        return

    console.print()
    if result.returncode == 0:
        console.print(f"[green bold]✓ Machine setup completed successfully for {host}.[/green bold]")
        if ask_confirm("Add host to inventory?", default=True):
            inv_name = hostname if hostname else host
            group = ask_text("Inventory group (default: all):", default="all") or "all"
            from ansiblecli.inventory import add_host
            add_host(inv_name, address=host, group=group)
            console.print(f"[green]+[/green] Added [bold]{inv_name}[/bold] ({host}) to inventory (group: {group}).")
    else:
        console.print(f"[red bold]✗ Machine setup failed with exit code {result.returncode}.[/red bold]")

    pause("Press Enter to return...")


def _prompt_ssh_password():
    """Ask for the SSH password, offering to reuse/save the stored one."""
    saved_pass = get_config("machine_setup_become_pass") or None
    if saved_pass:
        use_saved = ask_confirm("Use saved become password for ssh?", default=True)
        if use_saved is None:
            return None
        if not use_saved:
            console.print("[dim]Enter a new SSH password:[/dim]")
            ssh_pass = ask_password("SSH password:")
            if ask_confirm("Save this password for next time?", default=False):
                set_key("machine_setup_become_pass", ssh_pass)
            return ssh_pass
        return saved_pass

    console.print("[dim]No saved password. Enter your SSH password:[/dim]")
    ssh_pass = ask_password("SSH password:")
    if ssh_pass and ask_confirm("Save this password for next time?", default=False):
        set_key("machine_setup_become_pass", ssh_pass)
    return ssh_pass


def _settings_clear_history():
    if ask_confirm("Clear all run history?"):
        database.clear_run_history()
        console.print("[green]Run history cleared.[/green]")
    else:
        console.print("[dim]Cancelled.[/dim]")
    pause()


def _settings_set_become_password():
    console.print("[dim]Stored in ~/.ansiblecli/config.json (owner-only, mode 600).[/dim]")
    console.print("[dim]Leave blank to stop sending a become password.[/dim]")
    password = ask_password("Become (sudo) password:")
    if password is None:
        console.print("[dim]Cancelled.[/dim]")
        pause()
        return
    set_key("become_password", password)
    config_module.lock_down_config_file()
    if password:
        console.print("[green]Become password saved — playbooks can now use 'become' "
                      "without prompting.[/green]")
    else:
        console.print("[green]Cleared — playbooks will prompt for sudo again.[/green]")
    pause()


def _settings_clear_last_config():
    if ask_confirm("Clear saved run settings for all projects?"):
        database.clear_last_config()
        console.print("[green]Saved run settings cleared.[/green]")
    else:
        console.print("[dim]Cancelled.[/dim]")
    pause()


def settings_menu():
    items = [
        ("   Clear run history", "clear_history"),
        ("   Clear saved run settings", "clear_config"),
        ("   Set become (sudo) password", "become_pass"),
    ]
    handlers = {
        "clear_history": _settings_clear_history,
        "clear_config": _settings_clear_last_config,
        "become_pass": _settings_set_become_password,
    }
    run_menu("Settings", "Settings:", items, dispatch_from(handlers))


def interactive_loop():
    project_count = len(discover_projects())

    def status_lines():
        plural = "s" if project_count != 1 else ""
        if project_count:
            return [f"[green]+[/green] Found [bold]{project_count}[/bold] playbook project{plural}"]
        return [
            "[yellow]No playbook projects found in playbooks/ directory.[/yellow]",
            "Create a subdirectory under [bold]playbooks/[/bold] with a .yml or .yaml file.",
        ]

    while True:
        try:
            action = pick_main_action(status_lines())
        except KeyboardInterrupt:
            break

        if action == "quit":
            break

        if action == "run":
            while True:
                project, proj_action = pick_project()
                if project is None:
                    break

                # These actions don't need a specific playbook chosen first.
                if proj_action == "history":
                    while True:
                        render_screen(f"History — {project['name']}")
                        show_history(project["name"])
                        if not prompt_for_run_output():
                            break
                    continue

                playbook_path = pick_playbook(project)
                if not playbook_path:
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
                        pause("Press Enter to return...")
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
            selected = ask_select("Show history for:", proj_choices)
            if selected is None:
                continue
            while True:
                render_screen(
                    "History" if selected == "All projects" else f"History — {selected}")
                show_history(None if selected == "All projects" else selected)
                # Offer the stored output — it was captured but never viewable.
                if not prompt_for_run_output():
                    break

        elif action == "settings":
            settings_menu()
