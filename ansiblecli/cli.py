import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ansiblecli import __version__, database
from ansiblecli.config import (
    APP_DIR,
    CONFIG_FILE,
    is_config_exposed,
    load_config,
    save_config,
    set_key,
)
from ansiblecli.config import (
    get as get_config,
)
from ansiblecli.database import DB_FILE
from ansiblecli.discover import discover_projects, get_project
from ansiblecli.inventory import (
    add_host as inv_add_host,
)
from ansiblecli.inventory import (
    export_inventory,
    list_groups,
    list_hosts,
    write_inventory_file,
)
from ansiblecli.inventory import (
    remove_host as inv_remove_host,
)
from ansiblecli.machinesetup import run_machine_setup, run_setup_script

app = typer.Typer(
    name="ansiblecli",
    help=f"AnsibleCLI v{__version__} — Interactive Playbook Manager",
    no_args_is_help=False,
)
console = Console()


def _version_callback(value: bool):
    if value:
        console.print(f"ansiblecli {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback,
        is_eager=True, help="Show the ansiblecli version and exit.",
    ),
):
    if ctx.invoked_subcommand is None:
        # Interactive menus need a real terminal — don't hang when piped.
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            console.print(ctx.get_help())
            raise typer.Exit(1)
        from ansiblecli.interactive import interactive_loop
        database.init_db()
        interactive_loop()


@app.command()
def init():
    """Initialize ansiblecli directory and database."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    database.init_db()

    playbooks_dir = Path(get_config("playbooks_dir"))
    playfiles_dir = Path(get_config("playfiles_dir"))
    inventory_dir = Path(get_config("inventory_dir"))

    playbooks_dir.mkdir(parents=True, exist_ok=True)
    playfiles_dir.mkdir(parents=True, exist_ok=True)
    inventory_dir.mkdir(parents=True, exist_ok=True)

    # Persist resolved paths: otherwise every future run re-derives them from
    # the current working directory and finds nothing outside the repo root.
    save_config({
        **load_config(),
        "playbooks_dir": str(playbooks_dir.resolve()),
        "playfiles_dir": str(playfiles_dir.resolve()),
        "inventory_dir": str(inventory_dir.resolve()),
    })

    write_inventory_file()

    console.print(f"[green]+[/green] Initialized ansiblecli at [bold]{APP_DIR}[/bold]")
    console.print(f"[green]+[/green] Playbooks directory: [bold]{playbooks_dir}[/bold]")
    console.print(f"[green]+[/green] Playfiles directory: [bold]{playfiles_dir}[/bold]")
    console.print(f"[green]+[/green] Inventory directory: [bold]{inventory_dir}[/bold]")


@app.command()
def list():
    """List all discovered playbook projects."""
    database.init_db()
    projects = discover_projects()
    if not projects:
        console.print("[yellow]No projects found.[/yellow]")
        console.print("Create a subdirectory under [bold]playbooks/[/bold] with a .yml file.")
        raise typer.Exit()

    table = Table(title="Playbook Projects")
    table.add_column("Project")
    table.add_column("Playbooks")
    table.add_column("Last Run")
    table.add_column("Status")

    for p in projects:
        last = database.get_last_config(p["name"])
        stats = database.get_history_stats(p["name"])

        last_run = "Never"
        if last:
            last_run = f"Yes ({last.get('host') or '?'})"

        status_text = f"{stats['total']} runs"
        if stats["total"] > 0:
            status_text += f" ({stats['success']} ok, {stats['failed']} failed)"

        table.add_row(
            p["name"],
            str(len(p["playbooks"])),
            last_run,
            status_text,
        )

    console.print(table)


@app.command()
def run(
    project: str = typer.Argument(None, help="Project name from playbooks/"),
    host: str = typer.Option(None, "--host", "-l", help="Target host or hostname"),
    all_hosts: bool = typer.Option(False, "--all-hosts", "-A", help="Run against every inventory host"),
    check: bool = typer.Option(False, "--check", help="Dry-run mode"),
    tags: str = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
    extra_vars: str = typer.Option(None, "--extra-vars", "-e", help="Extra vars (key=val,key=val)"),
    become_password: str = typer.Option(
        None, "--become-password", "-K",
        help="Sudo/become password (default: config become_password)"),
    verbose: int = typer.Option(0, "--verbose", "-v", count=True,
                                help="Ansible verbosity — repeat for more (-vv, -vvv)"),
):
    """Run a playbook project."""
    database.init_db()

    if not project:
        console.print("[red]Error: project name required.[/red]")
        console.print("Usage: ansiblecli run <project> [--host HOST] [--check]")
        raise typer.Exit(1)

    proj = get_project(project)
    if not proj:
        console.print(f"[red]Error: project '{project}' not found in playbooks/[/red]")
        raise typer.Exit(1)

    if len(proj["playbooks"]) == 0:
        console.print(f"[red]Error: no playbooks found in project '{project}'[/red]")
        raise typer.Exit(1)

    playbook_path = proj["playbooks"][0]
    if len(proj["playbooks"]) > 1 and not host:
        console.print("[yellow]Multiple playbooks found. Use the interactive mode to choose.[/yellow]")
        playbook_path = proj["playbooks"][0]

    last = database.get_last_config(project) or {}

    # Flags win over saved config; missing flags fall back to the saved config.
    # --all-hosts omits `-l` entirely, matching "All hosts" in the picker.
    if all_hosts:
        resolved_host = None
    else:
        resolved_host = host or last.get("host")
        if not resolved_host:
            console.print("[yellow]No host specified. Use --host, --all-hosts, "
                          "or run interactive mode.[/yellow]")
            raise typer.Exit(1)

    resolved_check = check or bool(last.get("check_mode"))
    resolved_tags = tags or last.get("tags")
    resolved_vars = extra_vars or last.get("extra_vars")

    write_inventory_file()

    from ansiblecli.runner import run_playbook
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = run_playbook(
            playbook_path,
            host=resolved_host,
            check_mode=resolved_check,
            tags=resolved_tags,
            extra_vars=resolved_vars,
            become_password=become_password,
            verbose=verbose,
        )
    except KeyboardInterrupt:
        database.add_run(
            project, playbook_path, resolved_host, resolved_check,
            resolved_tags, resolved_vars, "cancelled", 130,
            "Interrupted by user (Ctrl-C)",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        console.print("\n[yellow]Run cancelled by user.[/yellow]")
        raise typer.Exit(130) from None

    status = "failed"
    exit_code = -1
    output = None

    if result is not None:
        status = "success" if result.returncode == 0 else "failed"
        exit_code = result.returncode
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()[:5000] or None

    database.add_run(
        project, playbook_path, resolved_host, resolved_check,
        resolved_tags, resolved_vars, status, exit_code, output,
    )

    if resolved_host:
        database.update_host_last_used(resolved_host)

    if result is not None:
        console.print(f"\n[bold]{'[OK]' if status == 'success' else '[FAIL]'} Exit code: {exit_code}[/bold]")
        if result.stdout:
            console.print(result.stdout[-1000:])
        if result.stderr:
            console.print(f"[red]{result.stderr[-500:]}[/red]")
    raise typer.Exit(0 if status == "success" else 1)


@app.command()
def history(
    project: str = typer.Argument(None, help="Filter by project name"),
    limit: int = typer.Option(30, "--limit", "-n", help="Number of entries"),
):
    """Show run history."""
    database.init_db()
    from ansiblecli.interactive import show_history
    show_history(project)


@app.command()
def machinesetup(
    host: str = typer.Argument(..., help="Hostname or IP of the new machine"),
    hostname: str = typer.Option(None, "--hostname", "-n", help="Machine hostname (for set_hostname.yml)"),
    ssh_pass: str = typer.Option(None, "--ssh-pass", "-p", help="SSH password (defaults to the stored one)"),
    script: str = typer.Option(None, "--script", "-s", help="Run a shell script instead of the built-in sequence"),
    add_to_inventory: bool = typer.Option(True, "--add-to-inventory/--no-add", help="Add host to inventory on success"),
):
    """Run machine setup against a new host."""
    database.init_db()

    # If hostname not provided via flag, try saved default
    if not hostname:
        hostname = get_config("machine_setup_default_hostname") or None

    console.print(f"[cyan]Running machine setup on [bold]{host}[/bold][/cyan]")
    if hostname:
        console.print(f"  Hostname:   [bold]{hostname}[/bold]")
    else:
        console.print("  Hostname:   [dim](not set)[/dim]")
    console.print()

    if script:
        result = run_setup_script(host, script_path=script, hostname=hostname)
    else:
        password = ssh_pass or get_config("machine_setup_become_pass") or None
        if not password and sys.stdin.isatty():
            import questionary
            password = questionary.password("SSH password:").ask()
        if not password:
            console.print("[red]Error: an SSH password is required (--ssh-pass, "
                          "config machine_setup_become_pass, or interactive prompt).[/red]")
            raise typer.Exit(1)
        result = run_machine_setup(host, hostname, password, password)

    if result is None:
        console.print("[red]Failed to start machine setup.[/red]")
        raise typer.Exit(1)

    if result.returncode == 0:
        console.print()
        console.print(f"[green bold]Machine setup completed successfully for {host}.[/green bold]")
        if add_to_inventory:
            inv_add_host(hostname or host, address=host)
            console.print(f"[green]+[/green] Added [bold]{hostname or host}[/bold] to inventory.")
    else:
        console.print(f"[red bold]Machine setup failed with exit code {result.returncode}.[/red bold]")
    raise typer.Exit(0 if result.returncode == 0 else 1)


@app.command()
def config(
    key: str = typer.Argument(None, help="Config key to show or set"),
    value: str = typer.Argument(None, help="Value to set"),
):
    """View or set configuration."""
    if key and value:
        set_key(key, value)
        write_inventory_file()
        console.print(f"[green]+[/green] Set {key} = {value}")
        return

    cfg = load_config()
    if key:
        val = cfg.get(key, "[not set]")
        console.print(f"{key} = {val}")
        return

    table = Table(title="Configuration")
    table.add_column("Key")
    table.add_column("Value")
    for k, v in cfg.items():
        table.add_row(k, str(v))
    console.print(table)


@app.command()
def show(run_id: int = typer.Argument(..., help="Run ID, see 'ansiblecli history'")):
    """Print details and the captured output of a previous run."""
    database.init_db()
    from ansiblecli.interactive import show_run_output

    if not show_run_output(run_id, use_pager=False):
        console.print(f"[red]No run with ID {run_id}.[/red]")
        raise typer.Exit(1)


@app.command()
def doctor():
    """Check the environment: binaries, config paths, inventory and database."""
    database.init_db()

    def row(name, ok, detail):
        status = "[green]OK[/green]" if ok else "[yellow]WARN[/yellow]"
        table.add_row(name, status, detail)

    table = Table(title="ansiblecli doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    for binary, needed_for in (
        ("ansible-playbook", "running playbooks"),
        ("sshpass", "machine setup"),
        ("ssh-keyscan", "machine setup"),
    ):
        path = shutil.which(binary)
        row(binary, bool(path), path or f"missing on PATH (needed for {needed_for})")

    for key in ("playbooks_dir", "playfiles_dir", "inventory_dir"):
        path = Path(get_config(key))
        row(key, path.exists(), f"{path}" + ("" if path.exists() else " (missing)"))

    inventory_file = Path(get_config("inventory_dir")) / get_config("inventory_file")
    row("inventory_file", inventory_file.exists(), str(inventory_file))

    projects = discover_projects()
    row("playbooks", bool(projects),
        f"{len(projects)} project{'s' if len(projects) != 1 else ''} discovered")

    try:
        stats = database.get_history_stats()
        row("database", True,
            f"{stats['total']} runs recorded ({stats['success']} ok, {stats['failed']} failed, "
            f"{stats['cancelled']} cancelled)")
    except Exception as exc:  # noqa: BLE001 — doctor must report, not crash
        row("database", False, f"{DB_FILE}: {exc}")

    row("config permissions", not is_config_exposed(),
        "mode 600 (private)" if not is_config_exposed()
        else f"{CONFIG_FILE} is readable by other users — run: chmod 600 {CONFIG_FILE}")

    console.print(table)

    if not shutil.which("ansible-playbook"):
        console.print("\n[yellow]Install Ansible: apt install ansible | brew install ansible "
                      "| pip install ansible[/yellow]")


inventory_app = typer.Typer(
    name="inventory",
    help="Manage inventory hosts and groups",
    no_args_is_help=True,
)
app.add_typer(inventory_app, name="inventory")


@inventory_app.command("list")
def inv_list():
    """List all known hosts."""
    hosts = list_hosts()
    if not hosts:
        console.print("[yellow]No hosts in inventory.[/yellow]")
        return

    table = Table(title="Inventory Hosts")
    table.add_column("Hostname")
    table.add_column("Address")
    table.add_column("Group")
    table.add_column("OS")
    table.add_column("Last Used")

    for h in hosts:
        table.add_row(
            h["hostname"],
            h.get("address") or "-",
            h.get("inventory_group") or "all",
            h.get("os_type") or "-",
            h.get("last_used") or "-",
        )
    console.print(table)


@inventory_app.command("add")
def inv_add(
    hostname: str = typer.Argument(..., help="Hostname to add"),
    address: str = typer.Option(None, "--address", "-a", help="IP address"),
    group: str = typer.Option("all", "--group", "-g", help="Inventory group"),
):
    """Add a host to the inventory."""
    inv_add_host(hostname, address, group)
    console.print(f"[green]+[/green] Added {hostname} to inventory (group: {group}).")


@inventory_app.command("remove")
def inv_remove(
    hostname: str = typer.Argument(..., help="Hostname to remove"),
):
    """Remove a host from the inventory."""
    inv_remove_host(hostname)
    console.print(f"[green]+[/green] Removed {hostname} from inventory.")


@inventory_app.command("show")
def inv_show():
    """Show the generated inventory YAML."""
    import yaml
    data = export_inventory()
    console.print(yaml.dump(data, default_flow_style=False, sort_keys=False))


@inventory_app.command("groups")
def inv_groups():
    """List inventory groups."""
    groups = list_groups()
    if not groups:
        console.print("[yellow]No groups defined.[/yellow]")
        return
    console.print("[bold]Groups:[/bold]")
    for g in groups:
        console.print(f"  - {g}")
