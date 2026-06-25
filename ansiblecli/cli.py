from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ansiblecli import database
from ansiblecli.config import get as get_config
from ansiblecli.config import APP_DIR, load_config, set_key
from ansiblecli.discover import discover_projects, get_project
from ansiblecli.inventory import (
    add_host as inv_add_host,
    export_inventory,
    list_groups,
    list_hosts,
    remove_host as inv_remove_host,
    write_inventory_file,
)

app = typer.Typer(
    name="ansiblecli",
    help="Interactive CLI for managing and running Ansible playbooks",
    no_args_is_help=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
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
    check: bool = typer.Option(False, "--check", help="Dry-run mode"),
    tags: str = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
    extra_vars: str = typer.Option(None, "--extra-vars", "-e", help="Extra vars (key=val,key=val)"),
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
        console.print(f"[yellow]Multiple playbooks found. Use the interactive mode to choose.[/yellow]")
        playbook_path = proj["playbooks"][0]

    last = database.get_last_config(project)

    resolved_host = host or (last.get("host") if last else None)
    resolved_check = check or (bool(last.get("check_mode")) if last and not check else False)
    resolved_tags = tags or (last.get("tags") if last else None)
    resolved_vars = extra_vars or (last.get("extra_vars") if last else None)

    if not resolved_host:
        console.print("[yellow]No host specified. Use --host or run interactive mode.[/yellow]")
        raise typer.Exit(1)

    write_inventory_file()

    from ansiblecli.runner import run_playbook
    result = run_playbook(
        playbook_path,
        host=resolved_host,
        check_mode=resolved_check,
        tags=resolved_tags,
        extra_vars=resolved_vars,
    )

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
