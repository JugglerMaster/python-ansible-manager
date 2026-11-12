from ansiblecli import database


def test_run_history_roundtrip():
    database.add_run("alpha", "alpha/playbook.yml", "web1", False, "tag1", "a=b",
                     "success", 0, "output text")
    rows = database.get_run_history()
    assert len(rows) == 1
    row = rows[0]
    assert row["project"] == "alpha"
    assert row["host"] == "web1"
    assert row["status"] == "success"
    assert row["exit_code"] == 0
    assert row["started_at"] == row["finished_at"]  # defaulted


def test_run_history_stores_recap_and_timestamps():
    database.add_run("beta", "beta.yml", None, True, None, None, "failed", 2, "err",
                     started_at="2026-01-01T00:00:00+00:00",
                     finished_at="2026-01-01T00:01:30+00:00",
                     recap="web1: ok=1 failed=0")
    row = database.get_run_history("beta")[0]
    assert row["recap"] == "web1: ok=1 failed=0"
    assert row["check_mode"] == 1
    assert row["host"] is None


def test_history_is_newest_first_and_limit_respected():
    for i in range(5):
        database.add_run("alpha", "p.yml", "h", False, None, None, "success", 0, "",
                         started_at=f"2026-01-0{i + 1}T00:00:00+00:00")
    assert len(database.get_run_history(limit=2)) == 2
    assert database.get_run_history()[0]["started_at"].startswith("2026-01-05")


def test_history_stats_counts_by_status():
    database.add_run("alpha", "p.yml", "h", False, None, None, "success", 0, "")
    database.add_run("alpha", "p.yml", "h", False, None, None, "failed", 1, "")
    database.add_run("alpha", "p.yml", "h", False, None, None, "failed", 1, "")
    database.add_run("alpha", "p.yml", "h", False, None, None, "cancelled", 130, "")
    stats = database.get_history_stats("alpha")
    assert stats["total"] == 4
    assert stats["success"] == 1
    assert stats["failed"] == 2
    assert stats["cancelled"] == 1


def test_history_stats_never_returns_none_for_empty_set():
    # SUM() over zero rows yields NULL, which would break "3 ok, None failed".
    stats = database.get_history_stats("nope")
    assert stats == {"total": 0, "success": 0, "failed": 0, "cancelled": 0}
    assert all(isinstance(v, int) for v in stats.values())


def test_clear_run_history():
    database.add_run("alpha", "p.yml", "h", False, None, None, "success", 0, "")
    database.clear_run_history()
    assert database.get_run_history() == []


def test_clear_last_config():
    database.save_last_config("alpha", "web1", True, "t1", "a=b")
    database.save_last_config("beta", None, False, None, None)
    assert database.get_last_config("alpha")["tags"] == "t1"
    database.clear_last_config("alpha")
    assert database.get_last_config("alpha") is None
    assert database.get_last_config("beta") is not None
    database.clear_last_config()
    assert database.get_last_config("beta") is None


def test_last_config_upserts_and_normalises():
    database.save_last_config("alpha", "web1", True, "t1", "a=b")
    database.save_last_config("alpha", "web2", False, None, "")
    cfg = database.get_last_config("alpha")
    assert cfg["host"] == "web2"        # updated in place, not duplicated
    assert cfg["check_mode"] == 0       # bool stored as int
    assert cfg["tags"] is None          # empty string normalised to NULL
    assert cfg["extra_vars"] is None


def test_unknown_host_crud_and_last_used():
    database.add_known_host("web1", "10.0.0.1", "web", "debian")
    database.add_known_host("web2", None, "all", None)
    hosts = database.get_known_hosts()
    assert [h["hostname"] for h in hosts] == ["web1", "web2"]  # ordered by name

    database.update_host_last_used("web1")
    assert database.get_known_hosts()[0]["last_used"]

    database.remove_known_host("web1")
    assert [h["hostname"] for h in database.get_known_hosts()] == ["web2"]


def test_add_known_host_is_idempotent():
    database.add_known_host("web1", "10.0.0.1", "web")
    database.add_known_host("web1", "10.0.0.2", "db")
    rows = database.get_known_hosts()
    assert len(rows) == 1
    assert rows[0]["address"] == "10.0.0.2"


def test_inventory_groups_are_distinct():
    database.add_known_host("a", None, "web")
    database.add_known_host("b", None, "web")
    database.add_known_host("c", None, "db")
    assert database.get_inventory_groups() == ["db", "web"]


def test_migrate_schema_normalises_legacy_all_hosts_sentinel():
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO run_history (project, playbook_path, host, status, started_at) "
        "VALUES ('a','p.yml','All hosts','success','2026-01-01T00:00:00+00:00')")
    conn.commit()
    conn.close()
    database.migrate_schema()
    assert database.get_run_history("a")[0]["host"] is None


def test_init_db_is_idempotent():
    database.init_db()
    database.init_db()
    assert database.get_run_history() == []
