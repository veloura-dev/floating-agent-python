"""Friday's fully-native CustomTkinter Notepad panel -- split out of `app_panels.py`
purely to keep that file (and the conceptually-separate "Notepad is one
of Friday's own work-surface tools" idea -- see ARCHITECTURE.md §2) in
its own clearly-named file, with zero change in behavior.
`app_panels.py` still re-exports `CustomNotepadPanel` by its original
name, and `AppPanelManager` there is still the only place that actually
constructs it.

See the class's own docstring below for why this exists at all (in
short: it replaced a fragile real-Notepad-window-embedding path that
broke multiple times on real Windows hardware -- see
IDE_CAPABILITY_AUDIT.md Parts 7/8/10). It shares layout constants and a positioning helper through `panel_ui.py`,
so this module can be imported independently without a circular import.
"""

import os
import re
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import customtkinter as ctk

# Same small bootstrap app_panels.py itself does, for the same reason:
# ide.py's MinimizedPill/_ActiveGlowAnimator/color-palette C are already
# fully generic, so they're reused as-is here instead of being
# duplicated a second time.
_IDE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ide")
if _IDE_DIR not in sys.path:
    sys.path.insert(0, _IDE_DIR)
import ide as _ide_module  # noqa: E402
C = _ide_module.C
_ActiveGlowAnimator = _ide_module._ActiveGlowAnimator
_update_active_panel_glow = _ide_module._update_active_panel_glow
import panel_ui


class CustomNotepadPanel(tk.Toplevel):
    """Friday's own, fully-native notepad: no real OS process, no
    foreign window, no SetParent reparenting of anything -- just
    Friday's own tk.Text editor widgets in a CustomTkinter surface that
    looks and behaves like a
    small Markdown-aware text editor (a tab strip, a small Bold/Italic/
    heading/list formatting toolbar, and a status bar), that writes
    real files to disk on request. This exists specifically to retire
    the fragile SetParent-based real-Notepad embedding path for good —
    see RealWindowBackend's own docstring and IDE_CAPABILITY_AUDIT.md
    Parts 7/8/10 for that whole saga of real-Windows embedding bugs.
    There is no foreign window here at all for a ctypes/SetParent bug
    to ever corrupt again, by construction — "Notepad" is just this
    class, end to end.

    Visually modeled directly on modern Windows Notepad (tabs across
    the top, a small formatting toolbar, a status bar showing line/
    column, character count, zoom, line ending and encoding). The
    toolbar's formatting buttons insert plain Markdown syntax around
    the current selection (the same approach real modern Notepad's own
    formatting toolbar actually uses) rather than any real rich-text or
    binary format, so what gets saved to disk is always an ordinary,
    fully portable, real UTF-8 .txt file with Windows CRLF line
    endings (matching the status bar's own claim) — nothing here is a
    simulation; File > Save (or the agent-facing save_active_tab/
    save_app_file path) writes a genuine file to the user's real disk.
    """

    DEFAULT_W = panel_ui.DEFAULT_PANEL_W
    DEFAULT_H = panel_ui.DEFAULT_PANEL_H
    TITLEBAR_H = panel_ui.TITLEBAR_H
    TABBAR_H = 26
    TOOLBAR_H = 30
    STATUSBAR_H = 20
    BORDER_PX = panel_ui.BORDER_PX
    ZOOM_STEPS = (50, 67, 80, 90, 100, 110, 125, 150, 175, 200, 250, 300)
    HEADING_PREFIXES = {"Body text": "", "Heading 1": "# ",
                         "Heading 2": "## ", "Heading 3": "### "}

    # Overridable per-class default base directory for save_active_tab's
    # own no-path-given fallback (normally None -- real use always falls
    # back to "~/Documents/Friday Notes", or "~/Friday Notes" if there's
    # no Documents folder). Tests point this at a scratch directory so
    # they never risk touching this sandbox's real home directory.
    DEFAULT_SAVE_BASE_DIR = None

    def __init__(self, master, on_minimize, on_close, corner_index=0,
                 initial_content=None, bounds=None):
        super().__init__(master)
        self.title("Notepad")
        self.overrideredirect(True)
        self.configure(bg=C["border_hi"])
        self.is_maximized = False
        self._zoom_pct = 100
        self._on_close_cb = on_close
        # Pulsing "this is Friday's current active panel" border --
        # same mechanism/rationale as EmbeddedAppPanel's own, see its
        # matching comment and ide.py's _ActiveGlowAnimator docstring.
        self._is_active_panel = False
        self._friday_glow_state = "idle"
        self._friday_glow_is_error = False
        self._active_glow = _ActiveGlowAnimator(
            self, lambda c: self.configure(bg=c))

        if bounds is not None:
            # See EmbeddedAppPanel.__init__'s matching comment -- the
            # unified panel-placement system already decided where this
            # should open.
            x, y, w, h = bounds
        else:
            w, h = self.DEFAULT_W, self.DEFAULT_H
            x, y = panel_ui.corner_position(master, corner_index, w, h)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self._default_geometry = (x, y, w, h)

        bp = self.BORDER_PX
        # -- titlebar: identical chrome/behavior to EmbeddedAppPanel's --
        panel_ui.build_titlebar(
            self, C, "Notepad", on_minimize, on_close, self.TITLEBAR_H, bp)

        # -- File / Edit / View menu row --
        menurow = ctk.CTkFrame(self, fg_color=C["tabbar"], corner_radius=0)
        menurow.pack(side="top", fill="x", padx=bp)
        self._build_menu(menurow, "File", self._file_menu_items())
        self._build_menu(menurow, "Edit", self._edit_menu_items())
        self._build_menu(menurow, "View", self._view_menu_items())

        # -- tab strip --
        tabbar = ctk.CTkFrame(
            self, fg_color=C["tabbar"], height=self.TABBAR_H, corner_radius=0)
        tabbar.pack(side="top", fill="x", padx=bp)
        tabbar.pack_propagate(False)
        self._tabs_area = ctk.CTkFrame(
            tabbar, fg_color="transparent", corner_radius=0)
        self._tabs_area.pack(side="left", fill="y")
        add_tab_btn = ctk.CTkButton(
            tabbar, text="+", command=self.new_tab, width=32, height=24,
            fg_color="transparent", hover_color=C["hover"],
            text_color=C["fg_dim"], font=("Segoe UI", 11, "bold"),
            corner_radius=6)
        add_tab_btn.pack(side="left", padx=4)

        # -- formatting toolbar --
        toolbar = ctk.CTkFrame(
            self, fg_color=C["panel"], height=self.TOOLBAR_H, corner_radius=0)
        toolbar.pack(side="top", fill="x", padx=bp)
        toolbar.pack_propagate(False)
        heading_menu = tk.Menu(self, tearoff=False, bg=C["panel"], fg=C["fg"])
        for lbl in ("Body text", "Heading 1", "Heading 2", "Heading 3"):
            heading_menu.add_command(label=lbl, command=lambda l=lbl: self._apply_heading(l))
        heading_btn = ctk.CTkButton(
            toolbar, text="Body text",
            fg_color=C["accent_btn"], text_color=C["fg"],
            hover_color=C["accent_hover"], font=("Segoe UI", 9),
            width=112, height=24, corner_radius=6,
            command=lambda: self._show_menu(heading_menu, heading_btn))
        self._heading_btn = heading_btn
        heading_btn.pack(side="left", padx=(6, 4), pady=3)

        def _tool_btn(text, cmd, font=("Segoe UI", 10)):
            b = ctk.CTkButton(
                toolbar, text=text, command=cmd, fg_color="transparent",
                hover_color=C["hover"], text_color=C["fg"], font=font,
                width=32, height=24, corner_radius=6)
            b.pack(side="left", padx=2)
            return b

        _tool_btn("\u2630", self.toggle_bullet_list)
        _tool_btn("B", self.apply_bold, font=("Segoe UI", 10, "bold"))
        _tool_btn("I", self.apply_italic, font=("Segoe UI", 10, "italic"))
        _tool_btn("S", self.apply_strikethrough)
        _tool_btn("\U0001F517", self.apply_link)

        # -- editor area: one Text widget per tab, stacked + raised --
        self._editor_host = ctk.CTkFrame(
            self, fg_color=C["editor"], corner_radius=0)
        self._editor_host.pack(side="top", fill="both", expand=True, padx=bp)

        # -- status bar --
        statusbar = ctk.CTkFrame(
            self, fg_color=C["statusbar"], height=self.STATUSBAR_H,
            corner_radius=0)
        statusbar.pack(side="bottom", fill="x", padx=bp, pady=(0, bp))
        statusbar.pack_propagate(False)
        self._pos_label = ctk.CTkLabel(
            statusbar, text="Ln 1, Col 1", text_color=C["status_fg"],
            font=("Segoe UI", 8))
        self._pos_label.pack(side="left", padx=8)
        self._chars_label = ctk.CTkLabel(
            statusbar, text="0 characters", text_color=C["status_fg"],
            font=("Segoe UI", 8))
        self._chars_label.pack(side="left", padx=8)
        ctk.CTkLabel(
            statusbar, text="Plain text", text_color=C["status_fg"],
            font=("Segoe UI", 8)).pack(side="left", padx=8)
        self._zoom_label = ctk.CTkLabel(
            statusbar, text="100%", text_color=C["status_fg"],
            font=("Segoe UI", 8))
        self._zoom_label.pack(side="right", padx=8)
        ctk.CTkLabel(
            statusbar, text="UTF-8", text_color=C["status_fg"],
            font=("Segoe UI", 8)).pack(side="right", padx=8)
        ctk.CTkLabel(
            statusbar, text="Windows (CRLF)", text_color=C["status_fg"],
            font=("Segoe UI", 8)).pack(side="right", padx=8)

        self._tabs = []
        self._active_tab = None

        self.bind("<Control-s>", lambda _e: self._file_save())
        self.bind("<Control-S>", lambda _e: self._file_save_as())
        self.bind("<Control-n>", lambda _e: self._file_new_tab())
        self.bind("<Control-o>", lambda _e: self._file_open())

        self.new_tab(content=initial_content or "")

        # Overrideredirect windows like this one can, on real Windows,
        # become visible on screen before Tk has actually finished
        # painting every freshly-built child widget -- showing nothing
        # but this window's own plain background (a "blank white
        # panel") until some interaction (move/resize/focus) forces a
        # repaint. Re-applying this exact geometry once more right now,
        # with a full update() in between to force Tk to actually
        # process the pending layout/paint work, closes that window.
        self._set_geometry_firmly(x, y, w, h)
        try:
            self.lift()
            self.update()
        except tk.TclError:
            pass

    # ---------------------------------------------------------------
    # Menu plumbing
    # ---------------------------------------------------------------
    def _build_menu(self, parent, label, items):
        menu = tk.Menu(self, tearoff=False, bg=C["panel"], fg=C["fg"],
                        activebackground=C["hover"], activeforeground=C["fg"])
        for item in items:
            if item is None:
                menu.add_separator()
            else:
                text, cmd = item
                menu.add_command(label=text, command=cmd)
        btn = ctk.CTkButton(
            parent, text=label,
            fg_color="transparent", hover_color=C["hover"],
            text_color=C["fg"], font=("Segoe UI", 9),
            width=54, height=26, corner_radius=6,
            command=lambda: self._show_menu(menu, btn))
        btn.pack(side="left", padx=2)
        return btn

    @staticmethod
    def _show_menu(menu, button):
        menu.tk_popup(
            button.winfo_rootx(),
            button.winfo_rooty() + button.winfo_height())
        menu.grab_release()

    def _file_menu_items(self):
        return [
            ("New Tab", self._file_new_tab),
            ("Open...", self._file_open),
            ("Save", self._file_save),
            ("Save As...", self._file_save_as),
            None,
            ("Close Tab", self._file_close_tab),
            ("Exit", self._file_exit),
        ]

    def _edit_menu_items(self):
        return [
            ("Undo", self._edit_undo),
            ("Redo", self._edit_redo),
            None,
            ("Cut", self._edit_cut),
            ("Copy", self._edit_copy),
            ("Paste", self._edit_paste),
            ("Select All", self._edit_select_all),
        ]

    def _view_menu_items(self):
        return [
            ("Toggle Word Wrap", self._toggle_word_wrap),
            None,
            ("Zoom In", self._zoom_in),
            ("Zoom Out", self._zoom_out),
            ("Reset Zoom", self._zoom_reset),
        ]

    # ---------------------------------------------------------------
    # Tabs
    # ---------------------------------------------------------------
    def new_tab(self, content="", path=None):
        """Creates a brand new tab (a real tk.Text widget of its own),
        makes it the active one, and returns its internal tab record.
        Used both for a genuinely blank new tab (File > New Tab / the
        "+" button) and for pre-filling one with real content (opening
        Notepad with content=..., or File > Open loading a real file)."""
        size = max(6, round(10 * self._zoom_pct / 100))
        text = tk.Text(self._editor_host, wrap="word", undo=True, bg=C["editor"],
                        fg=C["fg"], insertbackground=C["caret"],
                        selectbackground=C["sel"], relief="flat",
                        padx=10, pady=8, font=("Segoe UI", size))
        text.place(relx=0, rely=0, relwidth=1, relheight=1)
        if content:
            text.insert("1.0", content)
        text.edit_modified(False)

        tab = {"path": path, "dirty": False, "text": text,
               "name": os.path.basename(path) if path else "Untitled"}

        frame = ctk.CTkFrame(
            self._tabs_area, fg_color=C["tab_inactive"], corner_radius=6)
        frame.pack(side="left", fill="y")
        name_label = ctk.CTkButton(
            frame, text=tab["name"], command=lambda t=tab: self._select_tab(t),
            fg_color="transparent", hover_color=C["hover"],
            text_color=C["tab_in_fg"], font=("Segoe UI", 8),
            width=90, height=24, corner_radius=6)
        name_label.pack(side="left", padx=(3, 0), pady=2)
        close_x = ctk.CTkButton(
            frame, text="\u2715", command=lambda t=tab: self.close_tab(t),
            fg_color="transparent", hover_color=C["danger"],
            text_color=C["tab_in_fg"], font=("Segoe UI", 7),
            width=24, height=24, corner_radius=6)
        close_x.pack(side="left", padx=(0, 3), pady=2)
        tab["tab_frame"] = frame
        tab["title_label"] = name_label
        tab["close_btn"] = close_x

        def _on_modified(_e, t=tab):
            if t["text"].edit_modified():
                self._mark_dirty(t)
                t["text"].edit_modified(False)

        text.bind("<<Modified>>", _on_modified)
        text.bind("<KeyRelease>", lambda _e, t=tab: self._update_status(t))
        text.bind("<ButtonRelease-1>", lambda _e, t=tab: self._update_status(t))

        self._tabs.append(tab)
        self._select_tab(tab)
        return tab

    def _select_tab(self, tab):
        if tab not in self._tabs:
            return
        self._active_tab = tab
        tab["text"].lift()
        for t in self._tabs:
            active = t is tab
            bg = C["tab_active"] if active else C["tab_inactive"]
            fg = C["fg"] if active else C["tab_in_fg"]
            t["tab_frame"].configure(fg_color=bg)
            t["title_label"].configure(
                fg_color="transparent", text_color=fg)
            t["close_btn"].configure(
                fg_color="transparent", text_color=fg)
        try:
            tab["text"].focus_set()
        except tk.TclError:
            pass
        self._update_status(tab)

    def close_tab(self, tab):
        if tab not in self._tabs:
            return
        if len(self._tabs) == 1:
            # Always keep at least one tab alive -- reset it to a blank
            # Untitled tab instead of leaving the panel with zero tabs.
            tab["text"].delete("1.0", "end")
            tab["path"] = None
            tab["dirty"] = False
            tab["name"] = "Untitled"
            self._refresh_tab_label(tab)
            self._update_status(tab)
            return
        was_active = tab is self._active_tab
        tab["tab_frame"].destroy()
        tab["text"].destroy()
        self._tabs.remove(tab)
        if was_active:
            self._select_tab(self._tabs[-1])

    def _refresh_tab_label(self, tab):
        dot = "\u25CF " if tab["dirty"] else ""
        tab["title_label"].configure(text=f"{dot}{tab['name']}")

    def _mark_dirty(self, tab):
        if not tab["dirty"]:
            tab["dirty"] = True
            self._refresh_tab_label(tab)
        self._update_status(tab)

    def _update_status(self, tab):
        if tab is not self._active_tab:
            return
        text = tab["text"]
        try:
            line, col = text.index(tk.INSERT).split(".")
            self._pos_label.configure(text=f"Ln {line}, Col {int(col) + 1}")
        except (tk.TclError, ValueError):
            pass
        content = text.get("1.0", "end-1c")
        self._chars_label.configure(text=f"{len(content)} characters")

    # ---------------------------------------------------------------
    # Agent-facing content control (used by AppPanelManager.type_text/
    # save_file -- always via the panel-host's Tk-thread bridge)
    # ---------------------------------------------------------------
    def get_active_text(self):
        if self._active_tab is None:
            return ""
        return self._active_tab["text"].get("1.0", "end-1c")

    def type_text_into_active(self, content):
        """Inserts `content` at the current cursor position of the
        active tab -- the direct, fully-reliable replacement for the
        old pywinauto-based "type live into Notepad" path, since this
        is Friday's own real widget, not a foreign window to drive."""
        if self._active_tab is None:
            self.new_tab()
        self._active_tab["text"].insert("insert", content)
        self._mark_dirty(self._active_tab)

    def open_file_path(self, path):
        """Loads a real file's content from disk into a brand new tab
        (used by both File > Open's real file-picker dialog and,
        directly, by anything else that already knows a path)."""
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        return self.new_tab(content=content, path=path)

    def save_active_tab(self, path=None):
        """Writes the active tab's real content to a real file on disk.
        Returns (True, final_path) on success, or (False, reason) on
        failure. If `path` is omitted: reuses the active tab's own
        already-known path if it has one (a plain Save), or otherwise
        picks a sensible default location/filename on its own (under
        "Documents/Friday Notes", timestamped so nothing is ever
        silently overwritten) rather than refusing outright -- "save
        that" should just work without needing a path spelled out."""
        tab = self._active_tab
        if tab is None:
            return False, "there's no open tab to save"
        content = tab["text"].get("1.0", "end-1c")
        target = path or tab.get("path")
        if not target:
            base = type(self).DEFAULT_SAVE_BASE_DIR
            if not base:
                candidate = os.path.join(os.path.expanduser("~"), "Documents")
                base = candidate if os.path.isdir(candidate) else os.path.expanduser("~")
            notes_dir = os.path.join(base, "Friday Notes")
            stamp = time.strftime("%Y-%m-%d %H%M%S")
            target = os.path.join(notes_dir, f"Friday Note {stamp}.txt")
        try:
            final_path = self._write_to_disk(target, content)
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
        tab["path"] = final_path
        tab["dirty"] = False
        tab["name"] = os.path.basename(final_path)
        self._refresh_tab_label(tab)
        return True, final_path

    @staticmethod
    def _write_to_disk(path, content):
        path = os.path.expanduser(path)
        if not os.path.isabs(path):
            path = os.path.join(os.path.expanduser("~"), path)
        if not os.path.splitext(path)[1]:
            path += ".txt"
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(normalized)
        return path

    # ---------------------------------------------------------------
    # File menu actions (real file-picker dialogs -- UI-triggered only)
    # ---------------------------------------------------------------
    def _file_new_tab(self):
        self.new_tab()

    def _file_open(self):
        path = filedialog.askopenfilename(
            title="Open", parent=self,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.open_file_path(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open", f"Couldn't open that file:\n{exc}", parent=self)

    def _file_save(self):
        ok, result = self.save_active_tab(None)
        if not ok:
            messagebox.showerror("Save", f"Couldn't save:\n{result}", parent=self)

    def _file_save_as(self):
        tab = self._active_tab
        initial = tab["name"] if tab else "Untitled.txt"
        path = filedialog.asksaveasfilename(
            title="Save As", parent=self, defaultextension=".txt", initialfile=initial,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        ok, result = self.save_active_tab(path)
        if not ok:
            messagebox.showerror("Save As", f"Couldn't save:\n{result}", parent=self)

    def _file_close_tab(self):
        if self._active_tab is not None:
            self.close_tab(self._active_tab)

    def _file_exit(self):
        self._on_close_cb()

    # ---------------------------------------------------------------
    # Edit menu actions
    # ---------------------------------------------------------------
    def _active_text_widget(self):
        return self._active_tab["text"] if self._active_tab is not None else None

    def _edit_undo(self):
        t = self._active_text_widget()
        if t is not None:
            try:
                t.edit_undo()
            except tk.TclError:
                pass

    def _edit_redo(self):
        t = self._active_text_widget()
        if t is not None:
            try:
                t.edit_redo()
            except tk.TclError:
                pass

    def _edit_cut(self):
        t = self._active_text_widget()
        if t is not None:
            t.event_generate("<<Cut>>")

    def _edit_copy(self):
        t = self._active_text_widget()
        if t is not None:
            t.event_generate("<<Copy>>")

    def _edit_paste(self):
        t = self._active_text_widget()
        if t is not None:
            t.event_generate("<<Paste>>")

    def _edit_select_all(self):
        t = self._active_text_widget()
        if t is not None:
            t.tag_add("sel", "1.0", "end-1c")

    # ---------------------------------------------------------------
    # View menu actions
    # ---------------------------------------------------------------
    def _toggle_word_wrap(self):
        for t in self._tabs:
            current = t["text"].cget("wrap")
            t["text"].configure(wrap="none" if current == "word" else "word")

    def _set_zoom(self, pct):
        self._zoom_pct = pct
        size = max(6, round(10 * pct / 100))
        for t in self._tabs:
            t["text"].configure(font=("Segoe UI", size))
        self._zoom_label.configure(text=f"{pct}%")

    def _zoom_in(self):
        steps = self.ZOOM_STEPS
        bigger = [s for s in steps if s > self._zoom_pct]
        self._set_zoom(bigger[0] if bigger else steps[-1])

    def _zoom_out(self):
        steps = self.ZOOM_STEPS
        smaller = [s for s in steps if s < self._zoom_pct]
        self._set_zoom(smaller[-1] if smaller else steps[0])

    def _zoom_reset(self):
        self._set_zoom(100)

    # ---------------------------------------------------------------
    # Formatting toolbar actions -- plain Markdown syntax, so saved
    # files are always ordinary, fully portable real .txt files.
    # ---------------------------------------------------------------
    def _wrap_selection(self, marker_start, marker_end=None):
        marker_end = marker_start if marker_end is None else marker_end
        text = self._active_text_widget()
        if text is None:
            return
        try:
            start, end = text.index("sel.first"), text.index("sel.last")
        except tk.TclError:
            start = end = None
        if start is not None:
            content = text.get(start, end)
            text.delete(start, end)
            text.insert(start, f"{marker_start}{content}{marker_end}")
        else:
            idx = text.index("insert")
            text.insert(idx, f"{marker_start}{marker_end}")
            text.mark_set("insert", f"{idx}+{len(marker_start)}c")
        self._mark_dirty(self._active_tab)

    def apply_bold(self):
        self._wrap_selection("**")

    def apply_italic(self):
        self._wrap_selection("_")

    def apply_strikethrough(self):
        self._wrap_selection("~~")

    def apply_link(self):
        text = self._active_text_widget()
        if text is None:
            return
        try:
            start, end = text.index("sel.first"), text.index("sel.last")
            label_txt = text.get(start, end)
        except tk.TclError:
            start = end = None
            label_txt = "link text"
        url = simpledialog.askstring("Insert link", "URL:", parent=self) or ""
        if not url:
            return
        if start is not None:
            text.delete(start, end)
            text.insert(start, f"[{label_txt}]({url})")
        else:
            text.insert("insert", f"[{label_txt}]({url})")
        self._mark_dirty(self._active_tab)

    def toggle_bullet_list(self):
        text = self._active_text_widget()
        if text is None:
            return
        try:
            start_line = int(text.index("sel.first").split(".")[0])
            end_line = int(text.index("sel.last").split(".")[0])
        except tk.TclError:
            start_line = end_line = int(text.index("insert").split(".")[0])
        all_bulleted = all(
            text.get(f"{ln}.0", f"{ln}.end").lstrip().startswith("- ")
            for ln in range(start_line, end_line + 1))
        for ln in range(start_line, end_line + 1):
            line_content = text.get(f"{ln}.0", f"{ln}.end")
            if all_bulleted:
                if line_content.startswith("- "):
                    text.delete(f"{ln}.0", f"{ln}.2")
            else:
                if not line_content.lstrip().startswith("- "):
                    text.insert(f"{ln}.0", "- ")
        self._mark_dirty(self._active_tab)

    def _apply_heading(self, label):
        self._heading_btn.configure(text=label)
        prefix = self.HEADING_PREFIXES.get(label, "")
        text = self._active_text_widget()
        if text is None:
            return
        line_no = int(text.index("insert").split(".")[0])
        line_content = text.get(f"{line_no}.0", f"{line_no}.end")
        stripped = re.sub(r"^#{1,6}\s+", "", line_content)
        text.delete(f"{line_no}.0", f"{line_no}.end")
        text.insert(f"{line_no}.0", f"{prefix}{stripped}")
        self._mark_dirty(self._active_tab)

    # ---------------------------------------------------------------
    # Maximize / restore -- identical contract to EmbeddedAppPanel's,
    # so AppPanelManager.maximize_panel/_minimize_one/_restore_one work
    # against this exact same way without needing to know this isn't a
    # SetParent-embedded foreign window underneath.
    # ---------------------------------------------------------------
    def move_to(self, x, y, w, h):
        self._set_geometry_firmly(x, y, w, h)
        try:
            self.lift()
        except tk.TclError:
            pass

    def maximize_to(self, x, y, w, h):
        self.move_to(x, y, w, h)
        self.is_maximized = True
        self.set_active_panel(True)

    def move_to_slot(self, x, y, w, h):
        self.move_to(x, y, w, h)
        self.set_active_panel(False)
        self.is_maximized = False
        self._default_geometry = (x, y, w, h)

    def restore_default(self):
        x, y, w, h = self._default_geometry
        self._set_geometry_firmly(x, y, w, h)
        try:
            self.lower()
        except tk.TclError:
            pass
        self.is_maximized = False
        self.set_active_panel(False)

    def destroy(self):
        animator = getattr(self, "_active_glow", None)
        if animator is not None:
            animator.stop()
        super().destroy()

    def set_active_panel(self, active):
        """Same mechanism/rationale as EmbeddedAppPanel's own method of
        the same name -- see its docstring."""
        active = bool(active)
        if active == getattr(self, "_is_active_panel", False):
            return
        self._is_active_panel = active
        _update_active_panel_glow(self)

    def set_friday_status(self, state, is_error=False):
        self._friday_glow_state = state
        self._friday_glow_is_error = bool(is_error)
        _update_active_panel_glow(self)

    def _set_geometry_firmly(self, x, y, w, h):
        geom = f"{int(w)}x{int(h)}+{int(x)}+{int(y)}"
        try:
            self.geometry(geom)
            self.update_idletasks()
            self.geometry(geom)
        except tk.TclError:
            pass
