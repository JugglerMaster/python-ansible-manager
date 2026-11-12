from ansiblecli.interactive import parse_recap

RECAP_OUTPUT = """
PLAY [all] ******************************************************

TASK [Gathering Facts] *******************************************
ok: [frank2]

PLAY RECAP *******************************************************
frank2 : ok=12  changed=3  unreachable=0  failed=0  skipped=1
dc1    : ok=4   changed=0  unreachable=0  failed=1  skipped=0
"""


def test_parse_recap_keeps_only_hosts_counters():
    recap = parse_recap(RECAP_OUTPUT)
    assert recap == "frank2: ok=12  unreachable=0  failed=0 | dc1: ok=4  unreachable=0  failed=1"


def test_parse_recap_ignores_changed_and_skipped():
    assert "changed" not in parse_recap(RECAP_OUTPUT)
    assert "skipped" not in parse_recap(RECAP_OUTPUT)


def test_parse_recap_stops_at_blank_line():
    output = (
        "PLAY RECAP *******\n"
        "web1 : ok=2 failed=0\n"
        "\n"
        "Monday 12 November  19:41:00 -0500 (0:00:00.123)\n"
    )
    assert parse_recap(output) == "web1: ok=2  failed=0"


def test_parse_recap_without_recap_block_returns_none():
    assert parse_recap("just some output\nwith no recap\n") is None


def test_parse_recap_handles_empty_and_none():
    assert parse_recap("") is None
    assert parse_recap(None) is None


def test_parse_recap_single_host_only():
    output = "PLAY RECAP ****\nlonely : ok=1 changed=0 unreachable=0 failed=0\n"
    assert parse_recap(output) == "lonely: ok=1  unreachable=0  failed=0"
