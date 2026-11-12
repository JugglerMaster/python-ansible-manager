import contextlib
import sqlite3
from datetime import datetime, timezone

from ansiblecli.config import APP_DIR

DB_FILE = APP_DIR / "ansiblecli.db"


def get_connection():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # Don't fail immediately if another process holds the write lock.
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextlib.contextmanager
def connect():
    """Connection that is always closed, even on error."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS run_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            playbook_path TEXT NOT NULL,
            host TEXT,
            check_mode INTEGER DEFAULT 0,
            tags TEXT,
            extra_vars TEXT,
            status TEXT NOT NULL,
            exit_code INTEGER,
            output TEXT,
            started_at TIMESTAMP NOT NULL,
            finished_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS last_config (
            project TEXT PRIMARY KEY,
            host TEXT,
            check_mode INTEGER DEFAULT 0,
            tags TEXT,
            extra_vars TEXT,
            updated_at TIMESTAMP NOT NULL
        );

        CREATE TABLE IF NOT EXISTS known_hosts (
            hostname TEXT PRIMARY KEY,
            address TEXT,
            inventory_group TEXT DEFAULT 'all',
            os_type TEXT,
            last_used TIMESTAMP
        );
    """)
        conn.commit()
    migrate_schema()


_RUN_HISTORY_COLUMNS = (
    "project, playbook_path, host, check_mode, tags, extra_vars, status, "
    "exit_code, output, started_at, finished_at, recap"
)


def add_run(project, playbook_path, host, check_mode, tags, extra_vars, status, exit_code, output,
            started_at=None, finished_at=None, recap=None):
    if started_at is None:
        started_at = datetime.now(timezone.utc).isoformat()
    if finished_at is None:
        finished_at = started_at
    with connect() as conn:
        conn.execute(
            f"""INSERT INTO run_history ({_RUN_HISTORY_COLUMNS})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (project, playbook_path, host, int(check_mode), tags or None, extra_vars or None,
             status, exit_code, output, started_at, finished_at, recap),
        )
        conn.commit()


_LEGACY_ALL_HOSTS = ("All hosts", "all", "*")


def migrate_schema():
    with connect() as conn:
        conn.execute(
            "UPDATE run_history SET host = NULL WHERE host IN ('All hosts', 'all', '*')")
        conn.execute(
            "UPDATE last_config SET host = NULL WHERE host IN ('All hosts', 'all', '*')")
        # 'recap' was added after the first release — ignore if already present.
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("ALTER TABLE run_history ADD COLUMN recap TEXT")
        conn.commit()


def get_run_history(project=None, limit=50):
    with connect() as conn:
        if project:
            rows = conn.execute(
                "SELECT * FROM run_history WHERE project = ? ORDER BY started_at DESC LIMIT ?",
                (project, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM run_history ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_run_by_id(run_id):
    """Fetch a single run (used by the output viewer)."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM run_history WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


def get_history_stats(project=None):
    summary = (
        "SELECT COUNT(*) as total, "
        "COALESCE(SUM(CASE WHEN status='success' THEN 1 ELSE 0 END), 0) as success, "
        "COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END), 0) as failed, "
        "COALESCE(SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END), 0) as cancelled "
        "FROM run_history"
    )
    with connect() as conn:
        if project:
            row = conn.execute(f"{summary} WHERE project = ?", (project,)).fetchone()
        else:
            row = conn.execute(summary).fetchone()
        stats = dict(row) if row else {}
        return {key: stats.get(key, 0) for key in ("total", "success", "failed", "cancelled")}


def save_last_config(project, host, check_mode, tags, extra_vars):
    with connect() as conn:
        conn.execute(
            """INSERT INTO last_config (project, host, check_mode, tags, extra_vars, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(project) DO UPDATE SET
                   host = excluded.host,
                   check_mode = excluded.check_mode,
                   tags = excluded.tags,
                   extra_vars = excluded.extra_vars,
                   updated_at = excluded.updated_at""",
            (project, host, int(check_mode), tags or None, extra_vars or None,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def get_last_config(project):
    with connect() as conn:
        row = conn.execute("SELECT * FROM last_config WHERE project = ?", (project,)).fetchone()
        return dict(row) if row else None


def get_known_hosts():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM known_hosts ORDER BY hostname").fetchall()
        return [dict(r) for r in rows]


def add_known_host(hostname, address=None, inventory_group="all", os_type=None):
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO known_hosts "
            "(hostname, address, inventory_group, os_type) VALUES (?, ?, ?, ?)",
            (hostname, address, inventory_group, os_type),
        )
        conn.commit()


def remove_known_host(hostname):
    with connect() as conn:
        conn.execute("DELETE FROM known_hosts WHERE hostname = ?", (hostname,))
        conn.commit()


def update_host_last_used(hostname):
    with connect() as conn:
        conn.execute(
            "UPDATE known_hosts SET last_used = ? WHERE hostname = ?",
            (datetime.now(timezone.utc).isoformat(), hostname),
        )
        conn.commit()


def clear_run_history():
    """Delete every row in run_history."""
    with connect() as conn:
        conn.execute("DELETE FROM run_history")
        conn.commit()


def clear_last_config(project=None):
    """Delete saved run settings — one project, or all of them."""
    with connect() as conn:
        if project:
            conn.execute("DELETE FROM last_config WHERE project = ?", (project,))
        else:
            conn.execute("DELETE FROM last_config")
        conn.commit()


def get_inventory_groups():
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT inventory_group FROM known_hosts ORDER BY inventory_group"
        ).fetchall()
        return [r["inventory_group"] for r in rows]
