import os

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout, Window, FormattedTextControl
from prompt_toolkit.filters import Condition
from prompt_toolkit.styles import Style

from ansiblecli import database


class ProjectPicker:
    def __init__(self, projects):
        self.projects = list(projects)
        self.sort_mode = "name"
        self.search_text = ""
        self.search_active = False
        self.page = 0
        try:
            self.page_size = max(5, min(15, os.get_terminal_size().lines - 8))
        except OSError:
            self.page_size = 10
        self.selected_abs = 0

        self.last_configs = {}
        self.last_run_times = {}
        for p in self.projects:
            lc = database.get_last_config(p["name"])
            if lc:
                self.last_configs[p["name"]] = lc
            rows = database.get_run_history(p["name"], limit=1)
            if rows:
                self.last_run_times[p["name"]] = rows[0]["started_at"]

    @property
    def _filtered(self):
        items = self.projects
        if self.search_text:
            st = self.search_text.strip().lower()
            items = [p for p in items if st in p["name"].lower()]

        key_funcs = {
            "name": lambda p: p["name"].lower(),
            "last_run": lambda p: self.last_run_times.get(p["name"]) or "",
            "modified": lambda p: p.get("mtime", 0),
        }
        reverse = self.sort_mode != "name"
        return sorted(items, key=key_funcs[self.sort_mode], reverse=reverse)

    @property
    def _total_pages(self):
        return max(1, -(-len(self._filtered) // self.page_size))

    def _visible_items(self):
        fl = self._filtered
        start = self.page * self.page_size
        return fl[start:start + self.page_size]

    def _build_fragments(self):
        fragments = []

        fragments.append(("class:header", "  Select a playbook project\n"))

        sort_labels = {"name": "name", "last_run": "last run", "modified": "modified"}
        total = self._total_pages
        parts = [
            f"[s] Sort: {sort_labels[self.sort_mode]}",
        ]
        if total > 1:
            parts.append(f"Page {self.page + 1}/{total}")
        if self.search_active:
            parts.append(f"Search: {self.search_text}\u2588")
        elif self.search_text:
            parts.append(f"Search: {self.search_text}")
        else:
            parts.append("/ Search")
        fragments.append(("class:info", "  " + "  |  ".join(parts) + "\n\n"))

        visible = self._visible_items()
        if not visible:
            msg = "  No projects match your search." if self.search_text else "  No projects found."
            fragments.append(("class:empty", msg + "\n"))
        else:
            for i, proj in enumerate(visible):
                abs_idx = self.page * self.page_size + i
                selected = abs_idx == self.selected_abs

                prefix = "\u25b6 " if selected else "  "
                lc = self.last_configs.get(proj["name"])
                if lc and lc.get("host"):
                    host_info = f"last: {lc['host']}"
                else:
                    host_info = "(never run)"

                name_part = f"{prefix}{proj['name']}"
                pad = " " * max(2, 28 - len(proj['name']))
                line = f"{name_part}{pad}{host_info}\n"
                style = "class:selected" if selected else "class:item"
                fragments.append((style, line))

        fragments.append(("", "\n"))
        if self.search_active:
            fragments.append(("class:footer", "  \u2191\u2193 navigate  Enter confirm  Esc cancel\n"))
        else:
            fragments.append(("class:footer",
                "  \u2191\u2193 nav  \u2190\u2192 page  s sort  / search  Enter run  c settings  h history  v view  Esc back\n"))

        return fragments

    def _clamp_selection(self):
        total = len(self._filtered)
        if total == 0:
            self.selected_abs = 0
            self.page = 0
            return
        self.selected_abs = max(0, min(self.selected_abs, total - 1))
        self.page = self.selected_abs // self.page_size

    def _move(self, delta):
        self.selected_abs += delta
        self._clamp_selection()

    def _page_next(self):
        if self._total_pages <= 1:
            return
        self.page = min(self.page + 1, self._total_pages - 1)
        rel = self.selected_abs % self.page_size
        self.selected_abs = self.page * self.page_size + rel
        self._clamp_selection()

    def _page_prev(self):
        if self.page <= 0:
            return
        self.page -= 1
        rel = self.selected_abs % self.page_size
        self.selected_abs = self.page * self.page_size + rel
        self._clamp_selection()

    def _cycle_sort(self):
        order = ["name", "last_run", "modified"]
        idx = order.index(self.sort_mode)
        self.sort_mode = order[(idx + 1) % len(order)]
        self.selected_abs = 0
        self.page = 0

    def _toggle_search(self):
        self.search_active = not self.search_active
        if not self.search_active:
            self.search_text = ""
        self.selected_abs = 0
        self.page = 0

    def _current_project(self):
        fl = self._filtered
        if not fl or self.selected_abs >= len(fl):
            return None
        return fl[self.selected_abs]

    def run(self):
        kb = KeyBindings()
        is_searching = Condition(lambda: self.search_active)

        @kb.add("up", filter=~is_searching)
        def _(event):
            self._move(-1)
            event.app.invalidate()

        @kb.add("down", filter=~is_searching)
        def _(event):
            self._move(1)
            event.app.invalidate()

        @kb.add("left", filter=~is_searching)
        def _(event):
            self._page_prev()
            event.app.invalidate()

        @kb.add("right", filter=~is_searching)
        def _(event):
            self._page_next()
            event.app.invalidate()

        @kb.add("s", filter=~is_searching)
        def _(event):
            self._cycle_sort()
            event.app.invalidate()

        @kb.add("/", filter=~is_searching)
        def _(event):
            self._toggle_search()
            event.app.invalidate()

        @kb.add(Keys.Any, filter=is_searching)
        def _(event):
            key = event.key
            if len(key) == 1 and key.isprintable():
                self.search_text += key
            elif key == "backspace":
                self.search_text = self.search_text[:-1]
            self.selected_abs = 0
            self.page = 0
            event.app.invalidate()

        @kb.add("enter", filter=is_searching)
        def _(event):
            self._toggle_search()
            event.app.invalidate()

        @kb.add("escape", filter=is_searching)
        def _(event):
            self._toggle_search()
            event.app.invalidate()

        @kb.add("escape", filter=~is_searching)
        def _(event):
            event.app.exit((None, None))

        @kb.add("enter", filter=~is_searching)
        def _(event):
            proj = self._current_project()
            if proj:
                event.app.exit((proj, "run"))

        @kb.add("c", filter=~is_searching)
        def _(event):
            proj = self._current_project()
            if proj:
                event.app.exit((proj, "settings"))

        @kb.add("h", filter=~is_searching)
        def _(event):
            proj = self._current_project()
            if proj:
                event.app.exit((proj, "history"))

        @kb.add("v", filter=~is_searching)
        def _(event):
            proj = self._current_project()
            if proj:
                event.app.exit((proj, "view"))

        @kb.add("c-c")
        @kb.add("c-d")
        def _(event):
            event.app.exit((None, None))

        style = Style([
            ("header", "bold fg:cyan"),
            ("info", "fg:ansibrightyellow"),
            ("selected", "reverse bold"),
            ("item", ""),
            ("empty", "fg:yellow"),
            ("footer", "fg:ansibrightblack"),
        ])

        control = FormattedTextControl(self._build_fragments, show_cursor=False)
        window = Window(content=control, dont_extend_height=True, wrap_lines=False)
        app = Application(
            layout=Layout(window),
            key_bindings=kb,
            style=style,
            mouse_support=False,
            full_screen=False,
        )

        try:
            return app.run()
        except (KeyboardInterrupt, EOFError):
            return (None, None)
