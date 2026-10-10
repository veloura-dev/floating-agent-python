"""Friday's Settings panel -- lets the user see and manage every AI
model/API key Friday knows about, grouped by "faculty" (Thinking,
Research, Transcription, ...), with a live green-check/red-x connection
status per model and an "+ Add Model" button per faculty for adding a
brand-new provider Friday didn't already know about.

Each faculty is a real region of Friday's Brain: Voice feeds the
floating circle's own lightweight chat chain, and
Thinking/Planning/Review/Coding/Text Generation each feed the
matching region of Act Script (the IDE's compulsory Sequential
Rotation/Fan-Out/Debate engine -- see act_script.py). Adding a model
under one of those gives that specific region a genuinely bigger,
independent rotation pool -- real extra quota/rate-limit headroom
exactly where it's added, not just bookkeeping.

Split out into its own file for the same reason notepad_panel.py is its
own file rather than living in app_panels.py (see that file's own
docstring): it's a fully native tk.Toplevel panel, conceptually distinct
from the real-process-embedding machinery the rest of app_panels.py is
about, and it shares the same couple of layout constants/helpers from
EmbeddedAppPanel (DEFAULT_W/H-style sizing, TITLEBAR_H, BORDER_PX,
_corner_position) that notepad_panel.py already reuses rather than
duplicates.

Data lives in settings_store.py (encrypted on disk, same mechanism as
the rest of Friday's memory) and every green-check status shown here
comes from a real, on-demand backend call in settings_checks.py -- never
just "a key string is non-empty". Voice, Thinking, Planning, Review,
Coding, and Text Generation are all real regions today (see
act_script.py's ROLE_FACULTY and agent_overlay.py's AIWorker) -- a model
added under any of them is a genuine extra one Friday can and will call
there. Image Generation and Video Generation still have no real
generation call wiring anywhere in the codebase, so entries added under
those two remain pure bookkeeping for now -- this panel is honest about
that in the small print under those two sections rather than pretending
otherwise.
"""
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

from app_panels import EmbeddedAppPanel  # noqa: E402 -- shared layout constants/helper

import settings_store
import settings_checks

# Same bootstrap notepad_panel.py and app_panels.py themselves already
# do -- ide.py's color palette and pulsing-active-border animator are
# already fully generic, reused as-is here instead of duplicated again.
_IDE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ide")
if _IDE_DIR not in sys.path:
    sys.path.insert(0, _IDE_DIR)
import ide as _ide_module  # noqa: E402
C = _ide_module.C
_ActiveGlowAnimator = _ide_module._ActiveGlowAnimator

# Faculties with no real backend integration yet (see module docstring)
# -- shown with a small honest caption under their header instead of
# silently pretending an added model there actually does something
# today. Review/Coding/Text Generation/Planning/Voice all moved out
# of this set once act_script.py/agent_overlay.py started reading their
# pools for real.
_SCAFFOLD_ONLY_FACULTIES = {
    "Image Generation", "Video Generation",
}

_STATUS_STYLE = {
    "connected": ("\u2713", C["success"], "Connected"),
    "error": ("\u2715", C["danger"], "Not connected"),
    "unknown": ("\u25cb", C["fg_dim"], "Not checked yet"),
    "checking": ("\u27f3", C["warn"], "Checking\u2026"),
}


class _FieldDialog(tk.Toplevel):
    """Small modal form for adding or editing one model entry: display
    name, model/version string, optional API base URL (used for the
    generic reachability check on anything that isn't one of Friday's
    already-known providers), and the API key itself (masked, with a
    show/hide toggle). Calls `on_submit(name, model, api_key, base_url)`
    once the user confirms with everything non-empty-enough to be
    useful; closes itself either way on Cancel.
    """

    def __init__(self, master, title, faculty, on_submit, existing=None):
        super().__init__(master)
        self.title(title)
        self.configure(bg=C["panel"])
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self._on_submit = on_submit

        pad = {"padx": 14, "pady": (10, 0)}
        tk.Label(self, text=f"{title} \u2014 {faculty}", bg=C["panel"], fg=C["fg"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", **pad)

        existing = existing or {}
        self._name_var = tk.StringVar(value=existing.get("name", ""))
        self._model_var = tk.StringVar(value=existing.get("model", ""))
        self._base_url_var = tk.StringVar(value=existing.get("base_url", ""))
        self._key_var = tk.StringVar(value=existing.get("api_key", ""))

        self._labeled_entry("Display name (e.g. \"OpenAI\")", self._name_var)
        self._labeled_entry("Model / version (e.g. \"gpt-4.1\")", self._model_var)
        self._labeled_entry(
            "API base URL (optional \u2014 used to verify a custom provider)",
            self._base_url_var)

        tk.Label(self, text="API key", bg=C["panel"], fg=C["fg_dim"],
                 font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(10, 0))
        key_row = tk.Frame(self, bg=C["panel"])
        key_row.pack(fill="x", padx=14, pady=(2, 0))
        self._key_entry = tk.Entry(key_row, textvariable=self._key_var, show="\u2022",
                                    bg=C["input"], fg=C["fg"], insertbackground=C["fg"],
                                    relief="flat", font=("Segoe UI", 10))
        self._key_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self._show_var = tk.BooleanVar(value=False)

        def _toggle_show():
            self._key_entry.configure(show="" if self._show_var.get() else "\u2022")

        tk.Checkbutton(key_row, text="show", variable=self._show_var, command=_toggle_show,
                        bg=C["panel"], fg=C["fg_dim"], selectcolor=C["panel"],
                        activebackground=C["panel"], font=("Segoe UI", 8)
                        ).pack(side="left", padx=(8, 0))

        btn_row = tk.Frame(self, bg=C["panel"])
        btn_row.pack(fill="x", padx=14, pady=14)
        tk.Button(btn_row, text="Cancel", command=self.destroy, relief="flat",
                  bg=C["hover"], fg=C["fg"], font=("Segoe UI", 9)
                  ).pack(side="right", padx=(6, 0))
        tk.Button(btn_row, text="Save", command=self._submit, relief="flat",
                  bg=C["accent_btn"], fg=C["fg"], font=("Segoe UI", 9, "bold")
                  ).pack(side="right")

        self.update_idletasks()
        w, h = 420, self.winfo_reqheight()
        try:
            px = master.winfo_rootx() + (master.winfo_width() - w) // 2
            py = master.winfo_rooty() + (master.winfo_height() - h) // 2
        except tk.TclError:
            px, py = 200, 150
        self.geometry(f"{w}x{h}+{max(0, px)}+{max(0, py)}")

    def _labeled_entry(self, label, var):
        tk.Label(self, text=label, bg=C["panel"], fg=C["fg_dim"],
                 font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(10, 0))
        tk.Entry(self, textvariable=var, bg=C["input"], fg=C["fg"],
                  insertbackground=C["fg"], relief="flat", font=("Segoe UI", 10)
                  ).pack(fill="x", padx=14, pady=(2, 0), ipady=4)

    def _submit(self):
        name = self._name_var.get().strip()
        model = self._model_var.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Give this model a display name.",
                                    parent=self)
            return
        self._on_submit(name, model, self._key_var.get().strip(),
                         self._base_url_var.get().strip())
        self.destroy()


class SettingsPanel(tk.Toplevel):
    """Friday's own native Settings panel: a titlebar matching every
    other panel's chrome (drag to move, minimize, close), then a
    scrollable list of faculty sections, each with its model rows
    (masked key, status badge, Check/Edit/Remove) and its own
    "+ Add Model" button. `initial_content` is accepted only for
    constructor-signature compatibility with the other custom panels
    (AppPanelManager._open_custom_panel calls every custom panel class
    the same way) -- Settings has no notion of "content" and ignores it.
    """

    DEFAULT_W = 760
    DEFAULT_H = 600
    TITLEBAR_H = EmbeddedAppPanel.TITLEBAR_H
    BORDER_PX = EmbeddedAppPanel.BORDER_PX

    def __init__(self, master, on_minimize, on_close, corner_index=0,
                 initial_content=None, bounds=None):
        super().__init__(master)
        self.title("Settings")
        self.overrideredirect(True)
        self.configure(bg="#ffffff")
        self.is_maximized = False
        self._is_active_panel = False
        self._active_glow = _ActiveGlowAnimator(self, lambda c: self.configure(bg=c))

        if bounds is not None:
            x, y, w, h = bounds
        else:
            w, h = self.DEFAULT_W, self.DEFAULT_H
            x, y = EmbeddedAppPanel._corner_position(master, corner_index, w, h)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self._default_geometry = (x, y, w, h)

        self._data = {}
        self._row_widgets = {}  # (faculty, id) -> {"dot":..., "status_lbl":..., ...}

        bp = self.BORDER_PX
        # Titlebar (with a real, working close button) is built first,
        # before anything below that depends on settings_store actually
        # loading cleanly -- so even if that ever fails for some reason
        # (a corrupted settings file, a missing dependency, ...), this
        # panel is never left on screen as an inert, un-closeable blank
        # window; see the try/except further down.
        titlebar = tk.Frame(self, bg=C["tabbar"], height=self.TITLEBAR_H)
        titlebar.pack(side="top", fill="x", padx=bp, pady=(bp, 0))
        titlebar.pack_propagate(False)
        tk.Label(titlebar, text="Settings \u2014 AI Models", bg=C["tabbar"], fg=C["fg"],
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=8)
        btns = tk.Frame(titlebar, bg=C["tabbar"])
        btns.pack(side="right")
        min_btn = tk.Label(btns, text="\u2500", bg=C["tabbar"], fg=C["fg_dim"],
                            font=("Segoe UI", 10), padx=8, cursor="hand2")
        min_btn.pack(side="left")
        close_btn = tk.Label(btns, text="\u2715", bg=C["tabbar"], fg=C["fg_dim"],
                              font=("Segoe UI", 10), padx=8, cursor="hand2")
        close_btn.pack(side="left")
        min_btn.bind("<Enter>", lambda _e: min_btn.configure(bg=C["hover"]))
        min_btn.bind("<Leave>", lambda _e: min_btn.configure(bg=C["tabbar"]))
        min_btn.bind("<Button-1>", lambda _e: on_minimize())
        close_btn.bind("<Enter>", lambda _e: close_btn.configure(bg=C["danger"], fg="#ffffff"))
        close_btn.bind("<Leave>", lambda _e: close_btn.configure(bg=C["tabbar"], fg=C["fg_dim"]))
        close_btn.bind("<Button-1>", lambda _e: on_close())

        self._drag = {"x": 0, "y": 0}

        def _start_drag(e):
            self._drag["x"], self._drag["y"] = e.x, e.y

        def _do_drag(e):
            nx = self.winfo_pointerx() - self._drag["x"]
            ny = self.winfo_pointery() - self._drag["y"]
            self.geometry(f"+{nx}+{ny}")

        titlebar.bind("<Button-1>", _start_drag)
        titlebar.bind("<B1-Motion>", _do_drag)

        # -- a one-line subheader + "Check all" --
        sub = tk.Frame(self, bg=C["panel"])
        sub.pack(side="top", fill="x", padx=bp)
        tk.Label(sub, text="API keys are masked below. Checking a model makes a real,"
                           " silent call to its API before it's shown as connected.",
                 bg=C["panel"], fg=C["fg_dim"], font=("Segoe UI", 8), wraplength=560,
                 justify="left").pack(side="left", padx=8, pady=6)
        tk.Button(sub, text="Check all", command=self._check_all, relief="flat",
                  bg=C["accent_btn"], fg=C["fg"], font=("Segoe UI", 8, "bold")
                  ).pack(side="right", padx=8, pady=6)

        # -- scrollable body --
        body_host = tk.Frame(self, bg=C["editor"])
        body_host.pack(side="top", fill="both", expand=True, padx=bp, pady=(0, bp))
        self._canvas = tk.Canvas(body_host, bg=C["editor"], highlightthickness=0,
                                  bd=0)
        vsb = tk.Scrollbar(body_host, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._body = tk.Frame(self._canvas, bg=C["editor"])
        self._body_window = self._canvas.create_window((0, 0), window=self._body,
                                                         anchor="nw")

        def _on_body_configure(_e):
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))

        def _on_canvas_configure(e):
            self._canvas.itemconfigure(self._body_window, width=e.width)

        self._body.bind("<Configure>", _on_body_configure)
        self._canvas.bind("<Configure>", _on_canvas_configure)

        def _on_wheel(e):
            delta = -1 if e.delta > 0 else 1
            self._canvas.yview_scroll(delta, "units")

        self._canvas.bind_all("<MouseWheel>", _on_wheel, add="+")

        try:
            self._data = settings_store.load()
            self._render_all()
        except Exception as exc:  # noqa: BLE001
            self._show_fatal_error(exc)

        # Overrideredirect windows like this one can, on real Windows,
        # become visible on screen before Tk has actually finished
        # painting every freshly-built child widget -- showing nothing
        # but this window's own plain background (a "blank white
        # panel") until some interaction (move/resize/focus) forces a
        # repaint. Re-applying this exact geometry once more right now,
        # with an update_idletasks() in between to force Tk to actually
        # process the pending layout/paint work, closes that window --
        # the same "set it, flush, set it again" trick
        # _set_geometry_firmly already uses elsewhere in this codebase
        # for the same class of problem (see its own docstring).
        self._set_geometry_firmly(x, y, w, h)
        try:
            self.lift()
            self.update()
        except tk.TclError:
            pass

    def _show_fatal_error(self, exc):
        """Shown in place of the faculty list if settings_store.load()
        or the initial render ever raises -- never leave the user
        staring at a silently blank panel with no explanation and (had
        this not been caught) possibly no way to close it either; the
        titlebar's close button above is already built and working by
        the time this can run."""
        for child in self._body.winfo_children():
            child.destroy()
        tk.Label(self._body, text="Settings couldn't fully load.", bg=C["editor"],
                  fg=C["danger"], font=("Segoe UI", 11, "bold")
                  ).pack(anchor="w", padx=14, pady=(16, 4))
        tk.Label(self._body, text=str(exc), bg=C["editor"], fg=C["fg_dim"],
                  font=("Segoe UI", 9), wraplength=640, justify="left"
                  ).pack(anchor="w", padx=14)
        tk.Label(self._body, text="Close this panel and try opening Settings again -- "
                                    "if it keeps happening, check the terminal Friday "
                                    "was started from for the full error.",
                  bg=C["editor"], fg=C["fg_faint"], font=("Segoe UI", 8),
                  wraplength=640, justify="left").pack(anchor="w", padx=14, pady=(8, 0))

    # ---------------------------------------------------------------
    # Rendering
    # ---------------------------------------------------------------
    def _render_all(self):
        for child in self._body.winfo_children():
            child.destroy()
        self._row_widgets.clear()
        for faculty in settings_store.FACULTIES:
            self._render_faculty(faculty)

    def _render_faculty(self, faculty):
        section = tk.Frame(self._body, bg=C["editor"])
        section.pack(side="top", fill="x", pady=(10, 4), padx=10)

        header = tk.Frame(section, bg=C["editor"])
        header.pack(side="top", fill="x")
        tk.Label(header, text=faculty, bg=C["editor"], fg=C["fg_bright"],
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Button(header, text="+ Add model", relief="flat", bg=C["accent_btn"],
                  fg=C["fg"], font=("Segoe UI", 8, "bold"),
                  command=lambda f=faculty: self._open_add_dialog(f)
                  ).pack(side="right")

        if faculty in _SCAFFOLD_ONLY_FACULTIES:
            tk.Label(section, bg=C["editor"], fg=C["fg_faint"], font=("Segoe UI", 8),
                      justify="left", wraplength=640, anchor="w",
                      text=("Friday doesn't call out to a real " + faculty.lower() +
                            " provider yet \u2014 entries here are saved for when that "
                            "lands, and \"Check\" still makes a real reachability call "
                            "against whatever you add.")
                      ).pack(side="top", fill="x", pady=(0, 4))

        rows_host = tk.Frame(section, bg=C["editor"])
        rows_host.pack(side="top", fill="x")

        entries = self._data.get(faculty, [])
        if not entries:
            tk.Label(rows_host, text="No models added yet.", bg=C["editor"],
                      fg=C["fg_faint"], font=("Segoe UI", 9, "italic")
                      ).pack(side="top", anchor="w", pady=4)
        for entry in entries:
            self._render_row(rows_host, faculty, entry)

        tk.Frame(section, bg=C["border_soft"], height=1).pack(side="top", fill="x",
                                                                 pady=(8, 0))

    def _render_row(self, parent, faculty, entry):
        row = tk.Frame(parent, bg=C["panel"])
        row.pack(side="top", fill="x", pady=2)

        dot = tk.Label(row, text="\u25cf", bg=C["panel"], fg=C["fg_faint"],
                        font=("Segoe UI", 10))
        dot.pack(side="left", padx=(6, 4), pady=6)

        name_col = tk.Frame(row, bg=C["panel"])
        name_col.pack(side="left", fill="x", expand=True, pady=4)
        tk.Label(name_col, text=entry["name"], bg=C["panel"], fg=C["fg"],
                  font=("Segoe UI", 9, "bold")).pack(side="top", anchor="w")
        model_txt = entry.get("model") or "\u2014"
        tk.Label(name_col, text=model_txt, bg=C["panel"], fg=C["fg_dim"],
                  font=("Segoe UI", 8)).pack(side="top", anchor="w")

        key_lbl = tk.Label(row, text=settings_store.mask_key(entry.get("api_key", "")),
                            bg=C["panel"], fg=C["fg_dim"], font=("Consolas", 9))
        key_lbl.pack(side="left", padx=10)

        status_lbl = tk.Label(row, bg=C["panel"], font=("Segoe UI", 9, "bold"))
        status_lbl.pack(side="left", padx=(0, 10))

        check_btn = tk.Button(row, text="Check", relief="flat", bg=C["hover"],
                               fg=C["fg"], font=("Segoe UI", 8),
                               command=lambda f=faculty, e=entry: self._run_check(f, e))
        check_btn.pack(side="left", padx=2)
        tk.Button(row, text="Edit", relief="flat", bg=C["hover"], fg=C["fg"],
                  font=("Segoe UI", 8),
                  command=lambda f=faculty, e=entry: self._open_edit_dialog(f, e)
                  ).pack(side="left", padx=2)
        tk.Button(row, text="Remove", relief="flat", bg=C["hover"], fg=C["danger"],
                  font=("Segoe UI", 8),
                  command=lambda f=faculty, e=entry: self._remove(f, e)
                  ).pack(side="left", padx=(2, 6))

        self._row_widgets[(faculty, entry["id"])] = {
            "dot": dot, "status_lbl": status_lbl, "key_lbl": key_lbl,
            "check_btn": check_btn,
        }
        self._apply_status(faculty, entry["id"], entry.get("status", "unknown"),
                            entry.get("detail", ""))

    def _apply_status(self, faculty, model_id, status, detail):
        widgets = self._row_widgets.get((faculty, model_id))
        if not widgets:
            return
        glyph, color, label = _STATUS_STYLE.get(status, _STATUS_STYLE["unknown"])
        widgets["dot"].configure(fg=color)
        widgets["status_lbl"].configure(text=f"{glyph} {label}", fg=color)
        tip = detail or label
        for key in ("status_lbl", "dot"):
            try:
                widgets[key].configure(text=widgets[key].cget("text"))
            except tk.TclError:
                pass
        _Tooltip.attach(widgets["status_lbl"], tip)

    # ---------------------------------------------------------------
    # Add / Edit / Remove
    # ---------------------------------------------------------------
    def _open_add_dialog(self, faculty):
        def _submit(name, model, api_key, base_url):
            entry = settings_store.add_model(self._data, faculty, name, model,
                                              api_key, base_url)
            self._render_all()
            if api_key or base_url:
                self._run_check(faculty, entry)
        _FieldDialog(self, "Add model", faculty, _submit)

    def _open_edit_dialog(self, faculty, entry):
        def _submit(name, model, api_key, base_url):
            entry["name"] = name or entry["name"]
            entry["model"] = model
            entry["api_key"] = api_key
            entry["base_url"] = base_url
            settings_store.save(self._data)
            self._render_all()
        _FieldDialog(self, "Edit model", faculty, _submit, existing=entry)

    def _remove(self, faculty, entry):
        if not messagebox.askyesno(
                "Remove model", f"Remove \"{entry['name']}\" from {faculty}?",
                parent=self):
            return
        settings_store.remove_model(self._data, faculty, entry["id"])
        self._render_all()

    # ---------------------------------------------------------------
    # Connectivity checks (threaded -- see settings_checks.py's own
    # docstring for why these can block on real network I/O)
    # ---------------------------------------------------------------
    def _run_check(self, faculty, entry):
        self._apply_status(faculty, entry["id"], "checking", "")
        widgets = self._row_widgets.get((faculty, entry["id"]))
        if widgets:
            try:
                widgets["check_btn"].configure(state="disabled")
            except tk.TclError:
                pass

        def _worker():
            ok, detail = settings_checks.run_check(entry)
            self.after(0, lambda: self._finish_check(faculty, entry["id"], ok, detail))

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_check(self, faculty, model_id, ok, detail):
        settings_store.update_check_result(self._data, faculty, model_id, ok, detail,
                                            time.time())
        self._apply_status(faculty, model_id, "connected" if ok else "error", detail)
        widgets = self._row_widgets.get((faculty, model_id))
        if widgets:
            try:
                widgets["check_btn"].configure(state="normal")
            except tk.TclError:
                pass

    def _check_all(self):
        for faculty, entries in self._data.items():
            for entry in entries:
                if entry.get("api_key") or entry.get("base_url") or \
                        entry.get("check_kind", "").startswith("local"):
                    self._run_check(faculty, entry)

    # ---------------------------------------------------------------
    # Panel-manager protocol: same methods/semantics as
    # CustomNotepadPanel's own (see its docstring) -- withdraw/deiconify/
    # destroy come for free from tk.Toplevel.
    # ---------------------------------------------------------------
    def restore_default(self):
        x, y, w, h = self._default_geometry
        self._set_geometry_firmly(x, y, w, h)
        try:
            self.lower()
        except tk.TclError:
            pass
        self.is_maximized = False
        self.set_active_panel(False)

    def set_active_panel(self, active):
        active = bool(active)
        if active == getattr(self, "_is_active_panel", False):
            return
        self._is_active_panel = active
        if active:
            self._active_glow.start()
        else:
            self._active_glow.stop()
            try:
                self.configure(bg="#ffffff")
            except tk.TclError:
                pass

    def _set_geometry_firmly(self, x, y, w, h):
        geom = f"{int(w)}x{int(h)}+{int(x)}+{int(y)}"
        try:
            self.geometry(geom)
            self.update_idletasks()
            self.geometry(geom)
        except tk.TclError:
            pass


class _Tooltip:
    """A minimal, dependency-free hover tooltip -- used only to surface
    a status row's full check detail (e.g. the real error message from
    a failed connectivity check) without permanently taking up layout
    space for it."""

    @staticmethod
    def attach(widget, text):
        # Replaces any previously-attached tooltip bindings for this
        # widget (status can be re-checked repeatedly) rather than
        # stacking duplicate handlers.
        widget._tooltip_text = text
        if getattr(widget, "_tooltip_bound", False):
            return
        widget._tooltip_bound = True
        tip = {"win": None}

        def _show(_e):
            if tip["win"] is not None:
                return
            try:
                x = widget.winfo_rootx() + 10
                y = widget.winfo_rooty() + widget.winfo_height() + 4
            except tk.TclError:
                return
            win = tk.Toplevel(widget)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            tk.Label(win, text=getattr(widget, "_tooltip_text", ""), bg="#222222",
                      fg="#ffffff", font=("Segoe UI", 8), padx=6, pady=3,
                      wraplength=320, justify="left").pack()
            win.geometry(f"+{x}+{y}")
            tip["win"] = win

        def _hide(_e):
            if tip["win"] is not None:
                try:
                    tip["win"].destroy()
                except tk.TclError:
                    pass
                tip["win"] = None

        widget.bind("<Enter>", _show, add="+")
        widget.bind("<Leave>", _hide, add="+")
