import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ansiblecli.config import APP_DIR

DB_FILE = APP_DIR / "ansiblecli.db"


def get_connection():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
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
    conn.close()


def add_run(project, playbook_path, host, check_mode, tags, extra_vars, status, exit_code, output):
    conn = get_connection()
    conn.execute(
        """INSERT INTO run_history
           (project, playbook_path, host, check_mode, tags, extra_vars, status, exit_code, output, started_at, finished_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (project, playbook_path, host, int(check_mode), tags or None, extra_vars or None,
         status, exit_code, output, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_run_history(project=None, limit=50):
    conn = get_connection()
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
    conn.close()
    return [dict(r) for r in rows]


def get_history_stats(project=None):
    conn = get_connection()
    if project:
        row = conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success, "
            "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed FROM run_history WHERE project = ?",
            (project,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success, "
            "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed FROM run_history",
        ).fetchone()
    conn.close()
    return dict(row) if row else {"total": 0, "success": 0, "failed": 0}


def save_last_config(project, host, check_mode, tags, extra_vars):
    conn = get_connection()
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
    conn.close()


def get_last_config(project):
    conn = get_connection()
    row = conn.execute("SELECT * FROM last_config WHERE project = ?", (project,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_known_hosts():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM known_hosts ORDER BY hostname").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_known_host(hostname, address=None, inventory_group="all", os_type=None):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO known_hosts (hostname, address, inventory_group, os_type) VALUES (?, ?, ?, ?)",
        (hostname, address, inventory_group, os_type),
    )
    conn.commit()
    conn.close()


def remove_known_host(hostname):
    conn = get_connection()
    conn.execute("DELETE FROM known_hosts WHERE hostname = ?", (hostname,))
    conn.commit()
    conn.close()


def update_host_last_used(hostname):
    conn = get_connection()
    conn.execute(
        "UPDATE known_hosts SET last_used = ? WHERE hostname = ?",
        (datetime.now(timezone.utc).isoformat(), hostname),
    )
    conn.commit()
    conn.close()


def get_inventory_groups():
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT inventory_group FROM known_hosts ORDER BY inventory_group").fetchall()
    conn.close()
    return [r["inventory_group"] for r in rows]
