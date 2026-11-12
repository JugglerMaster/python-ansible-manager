import os

from prompt_toolkit import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import FormattedTextControl, Layout, Window
from prompt_toolkit.styles import Style

from ansiblecli import database

SORT_MODES = ["name", "last_run", "modified"]
SORT_LABELS = {"name": "name", "last_run": "last run", "modified": "modified"}


class ProjectPicker:
    """Keyboard-driven, paginated project picker (search + sort + hotkeys).

    All key handling lives on small methods so behaviour can be unit tested
    without starting a prompt_toolkit Application.
    """

    def __init__(self, projects, page_size=None):
        self.projects = list(projects)
        self.sort_mode = "name"
        self.search_text = ""
        self.search_active = False
        self.page = 0
        self.page_size = page_size or self._auto_page_size()
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

    @staticmethod
    def _auto_page_size():
        try:
            return max(5, min(15, os.get_terminal_size().lines - 8))
        except OSError:
            return 10

    # ------------------------------------------------------------------ data

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

    def _current_project(self):
        fl = self._filtered
        if not fl or self.selected_abs >= len(fl):
            return None
        return fl[self.selected_abs]

    # ------------------------------------------------------------- mutations

    def _clamp_selection(self):
        total = len(self._filtered)
        if total == 0:
            self.selected_abs = 0
            self.page = 0
            return
        self.selected_abs = max(0, min(self.selected_abs, total - 1))
        self.page = self.selected_abs // self.page_size

    def move(self, delta):
        self.search_active = False
        self.selected_abs += delta
        self._clamp_selection()

    def page_next(self):
        if self._total_pages <= 1:
            return
        self.page = min(self.page + 1, self._total_pages - 1)
        rel = self.selected_abs % self.page_size
        self.selected_abs = self.page * self.page_size + rel
        self._clamp_selection()

    def page_prev(self):
        if self.page <= 0:
            return
        self.page -= 1
        rel = self.selected_abs % self.page_size
        self.selected_abs = self.page * self.page_size + rel
        self._clamp_selection()

    def jump_to_start(self):
        self.selected_abs = 0
        self.page = 0

    def jump_to_end(self):
        total = len(self._filtered)
        self.selected_abs = max(0, total - 1)
        self._clamp_selection()

    def cycle_sort(self):
        self.search_active = False
        idx = SORT_MODES.index(self.sort_mode)
        self.sort_mode = SORT_MODES[(idx + 1) % len(SORT_MODES)]
        self.jump_to_start()

    def toggle_search(self):
        self.search_active = not self.search_active
        self.jump_to_start()

    def accept_search(self):
        """Leave search input mode but keep the filter applied."""
        self.search_active = False
        self.jump_to_start()

    def cancel_search(self):
        self.search_active = False
        self.search_text = ""
        self.jump_to_start()

    def type_char(self, char):
        """Append one printable character to the active search."""
        self.search_text += char
        self.jump_to_start()

    def erase_char(self):
        self.search_text = self.search_text[:-1]
        self.jump_to_start()

    def select(self, action="run"):
        """Return (project, action) for the highlighted row (or (None, None))."""
        proj = self._current_project()
        if proj is None:
            return None, None
        return proj, action

    # ------------------------------------------------------------- rendering

    def _host_info(self, proj):
        lc = self.last_configs.get(proj["name"])
        if lc and lc.get("host"):
            return f"last: {lc['host']}"
        if lc:
            return "last: all hosts"
        return "(never run)"

    def _build_fragments(self):
        fragments = []
        total_items = len(self._filtered)

        fragments.append(("class:header", "  Select a playbook project\n"))

        parts = [f"[s] Sort: {SORT_LABELS[self.sort_mode]}"]
        if self.page_size and total_items:
            first = self.page * self.page_size + 1
            last = min(total_items, (self.page + 1) * self.page_size)
            parts.append(f"{first}-{last} of {total_items}")
        if self._total_pages > 1:
            parts.append(f"Page {self.page + 1}/{self._total_pages}")
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
            # Width comes from *every* project (clamped), so the column never
            # shifts while typing a search or changing pages.
            all_names = [p["name"] for p in self.projects] or [p["name"] for p in visible]
            name_width = min(max(max(len(n) for n in all_names), 20), 40)
            for i, proj in enumerate(visible):
                abs_idx = self.page * self.page_size + i
                selected = abs_idx == self.selected_abs

                prefix = "\u25b6 " if selected else "  "
                line = f"{prefix}{proj['name']}"
                line += " " * max(2, name_width - len(proj["name"]) + 2)
                line += f"{self._host_info(proj)}\n"
                style = "class:selected" if selected else "class:item"
                fragments.append((style, line))

        fragments.append(("", "\n"))
        if self.search_active:
            fragments.append(("class:footer", "  type to filter  \u2191\u2193 navigate  Enter accept  Esc clear\n"))
        else:
            edit = "edit search" if self.search_text else "search"
            hint = (f"  \u2191\u2193 nav  \u2190\u2192 page  s sort  / {edit}  "
                    "Enter run  c settings  h history  v view  Esc back\n")
            fragments.append(("class:footer", hint))

        return fragments

    # ------------------------------------------------------------- app wiring

    def build_app(self, input=None, output=None):
        kb = KeyBindings()
        is_searching = Condition(lambda: self.search_active)

        @kb.add("up")
        def _up(event):
            self.move(-1)
            event.app.invalidate()

        @kb.add("down")
        def _down(event):
            self.move(1)
            event.app.invalidate()

        for page_key in ("left", "pageup"):
            @kb.add(page_key, filter=~is_searching)
            def _prev(event):
                self.page_prev()
                event.app.invalidate()

        for page_key in ("right", "pagedown"):
            @kb.add(page_key, filter=~is_searching)
            def _next(event):
                self.page_next()
                event.app.invalidate()

        @kb.add("home", filter=~is_searching)
        def _home(event):
            self.jump_to_start()
            event.app.invalidate()

        @kb.add("end", filter=~is_searching)
        def _end(event):
            self.jump_to_end()
            event.app.invalidate()

        @kb.add("s", filter=~is_searching)
        def _sort(event):
            self.cycle_sort()
            event.app.invalidate()

        @kb.add("/", filter=~is_searching)
        def _search(event):
            self.toggle_search()
            event.app.invalidate()

        # Enter while typing a search accepts the filter (instead of doing
        # nothing) and then runs the highlighted project.
        @kb.add("enter", filter=is_searching)
        def _accept(event):
            self.accept_search()
            project, action = self.select("run")
            if project is not None:
                event.app.exit((project, action))
            event.app.invalidate()

        @kb.add(Keys.Any, filter=is_searching)
        def _type(event):
            key = event.key_sequence[0].key
            if isinstance(key, str) and len(key) == 1:
                self.type_char(key)
            elif key == Keys.Backspace:
                self.erase_char()
            event.app.invalidate()

        @kb.add("enter")
        def _run(event):
            project, action = self.select("run")
            if project is not None:
                event.app.exit((project, action))
            event.app.invalidate()

        @kb.add("escape")
        def _escape(event):
            if self.search_active:
                self.cancel_search()
            else:
                event.app.exit((None, None))
            event.app.invalidate()

        for hotkey, action in (("c", "settings"), ("h", "history"), ("v", "view")):
            @kb.add(hotkey, filter=~is_searching)
            def _hotkey(event, action=action):
                project, picked = self.select(action)
                if project is not None:
                    event.app.exit((project, picked))

        @kb.add("c-c")
        @kb.add("c-d")
        def _abort(event):
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
        return Application(
            layout=Layout(window),
            key_bindings=kb,
            style=style,
            mouse_support=False,
            full_screen=False,
            input=input,
            output=output,
        )

    def run(self):
        try:
            return self.build_app().run()
        except (KeyboardInterrupt, EOFError):
            return None, None
