import pytest

from ansiblecli import database
from ansiblecli.picker import ProjectPicker


def make_projects(count, prefix="proj"):
    return [
        {"name": f"{prefix}{i:02d}", "playbooks": [f"{prefix}{i:02d}/p.yml"],
         "description": f"{prefix}{i:02d}", "mtime": float(i)}
        for i in range(count)
    ]


def test_default_sort_is_name_ascending():
    database.save_last_config("proj00", "web1", False, None, None)
    picker = ProjectPicker(make_projects(3), page_size=5)
    assert [p["name"] for p in picker._filtered] == ["proj00", "proj01", "proj02"]


def test_cycle_sort_moves_through_modes_and_resets_selection():
    picker = ProjectPicker(make_projects(3), page_size=5)
    picker.move(2)
    picker.cycle_sort()
    assert picker.sort_mode == "last_run"
    assert picker.selected_abs == 0
    picker.cycle_sort()
    assert picker.sort_mode == "modified"
    picker.cycle_sort()
    assert picker.sort_mode == "name"


def test_sort_by_modified_is_descending():
    picker = ProjectPicker(make_projects(3), page_size=5)
    picker.sort_mode = "modified"
    assert [p["name"] for p in picker._filtered] == ["proj02", "proj01", "proj00"]


def test_sort_by_last_run_puts_never_run_last():
    database.add_run("proj01", "p.yml", "h", False, None, None, "success", 0, "",
                     started_at="2026-01-01T00:00:00+00:00")
    database.add_run("proj02", "p.yml", "h", False, None, None, "success", 0, "",
                     started_at="2026-01-02T00:00:00+00:00")

    picker = ProjectPicker(make_projects(3), page_size=5)
    picker.sort_mode = "last_run"
    assert [p["name"] for p in picker._filtered] == ["proj02", "proj01", "proj00"]


def test_search_filters_case_insensitively():
    picker = ProjectPicker(make_projects(3), page_size=5)
    picker.type_char("P")  # uppercase should still match "proj.."
    assert len(picker._filtered) == 3
    picker = ProjectPicker(make_projects(3), page_size=5)
    picker.type_char("1")
    assert [p["name"] for p in picker._filtered] == ["proj01"]


def test_backspace_and_cancel_search():
    picker = ProjectPicker(make_projects(12), page_size=5)
    picker.type_char("p")
    picker.type_char("r")
    picker.erase_char()
    assert picker.search_text == "pr"[:-1] == "p"
    picker.cancel_search()
    assert picker.search_text == ""
    assert picker.search_active is False
    assert len(picker._filtered) == 12


def test_accept_search_keeps_filter_but_leaves_input_mode():
    picker = ProjectPicker(make_projects(12), page_size=5)
    picker.search_active = True
    picker.type_char("1")
    picker.accept_search()
    assert picker.search_active is False
    assert picker.search_text == "1"
    assert [p["name"] for p in picker._filtered] == ["proj01", "proj10", "proj11"]


def test_paging_moves_by_page_and_clamps():
    picker = ProjectPicker(make_projects(12), page_size=5)
    assert picker._total_pages == 3
    picker.page_next()
    assert picker.page == 1
    assert next(p["name"] for p in picker._visible_items()) == "proj05"
    picker.page_next()
    picker.page_next()  # clamped at last page
    assert picker.page == 2
    picker.page_prev()
    assert picker.page == 1


def test_moving_past_last_item_clamps():
    picker = ProjectPicker(make_projects(3), page_size=5)
    picker.move(10)
    assert picker.selected_abs == 2
    picker.move(-10)
    assert picker.selected_abs == 0


def test_selection_follows_page_boundaries():
    picker = ProjectPicker(make_projects(12), page_size=5)
    picker.selected_abs = 4
    picker.page_next()
    assert picker.selected_abs == 9
    assert picker.page == 1


def test_select_returns_current_project_and_action():
    picker = ProjectPicker(make_projects(3), page_size=5)
    picker.move(1)
    project, action = picker.select("history")
    assert project["name"] == "proj01"
    assert action == "history"


def test_select_with_no_results_returns_none_pair():
    picker = ProjectPicker(make_projects(3), page_size=5)
    picker.type_char("zzzz")
    assert picker.select("run") == (None, None)


def test_column_width_stays_stable_while_searching():
    picker = ProjectPicker([{"name": "basics", "playbooks": ["p.yml"], "mtime": 0.0},
                            {"name": "windows_basics", "playbooks": ["p.yml"], "mtime": 0.0},
                            {"name": "a_very_long_project_name_here", "playbooks": ["p.yml"],
                             "mtime": 0.0}], page_size=5)

    def width():
        rows = [text for style, text in picker._build_fragments()]
        return [text.rstrip("\n") for text in rows if "basics" in text][0].index("(")

    unfiltered = width()
    picker.type_char("bas")
    assert width() == unfiltered  # column must not shift while filtering


def test_jump_to_end_and_start():
    picker = ProjectPicker(make_projects(12), page_size=5)
    picker.jump_to_end()
    assert picker.selected_abs == 11
    assert picker.page == 2
    picker.jump_to_start()
    assert picker.selected_abs == 0
    assert picker.page == 0


def test_fragments_show_no_match_message_and_counts():
    picker = ProjectPicker(make_projects(12), page_size=5)
    text = "".join(frag for _, frag in picker._build_fragments())
    assert "1-5 of 12" in text
    assert "Page 1/3" in text

    picker2 = ProjectPicker(make_projects(12), page_size=5)
    picker2.type_char("nope")
    text2 = "".join(frag for _, frag in picker2._build_fragments())
    assert "No projects match your search." in text2


def test_fragments_mark_selected_row_and_last_host():
    database.save_last_config("proj01", "web1", False, None, None)
    picker = ProjectPicker(make_projects(3), page_size=5)
    rows = picker._build_fragments()
    selected = [(style, text) for style, text in rows if style == "class:selected"]
    assert len(selected) == 1
    assert selected[0][1].startswith("\u25b6 proj00")
    assert "(never run)" in selected[0][1]
    host_lines = [text for style, text in rows if "last: web1" in text]
    assert host_lines


def test_app_exits_with_run_action_on_enter(tmp_path):
    pytest.importorskip("prompt_toolkit")
    from threading import Thread

    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    picker = ProjectPicker(make_projects(3), page_size=5)
    with create_pipe_input() as pipe:
        Thread(target=pipe.send_text, args=("\r",), daemon=True).start()  # Enter
        result = picker.build_app(input=pipe, output=DummyOutput()).run()

    assert result is not None
    project, action = result
    assert project["name"] == "proj00"
    assert action == "run"


def test_app_search_then_enter_runs_filtered_project():
    """Regression: Enter used to be swallowed while typing a search."""
    from threading import Thread

    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    picker = ProjectPicker(make_projects(12), page_size=5)
    with create_pipe_input() as pipe:
        Thread(target=pipe.send_text, args=("/proj1\r",), daemon=True).start()  # '/'=search
        result = picker.build_app(input=pipe, output=DummyOutput()).run()

    assert result is not None
    project, action = result
    assert action == "run"
    assert project["name"] in {"proj01", "proj10", "proj11"}


def test_app_hotkey_returns_view_action():
    from threading import Thread

    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    picker = ProjectPicker(make_projects(3), page_size=5)
    with create_pipe_input() as pipe:
        Thread(target=pipe.send_text, args=("v",), daemon=True).start()
        result = picker.build_app(input=pipe, output=DummyOutput()).run()

    assert result is not None
    project, action = result
    assert action == "view"
    assert project["name"] == "proj00"


def test_app_escape_returns_empty_selection():
    from threading import Thread

    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    picker = ProjectPicker(make_projects(3), page_size=5)
    with create_pipe_input() as pipe:
        Thread(target=pipe.send_text, args=("\x1b",), daemon=True).start()  # Escape
        result = picker.build_app(input=pipe, output=DummyOutput()).run()

    assert result == (None, None)
