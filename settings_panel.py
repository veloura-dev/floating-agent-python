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
docstring): it's a fully native CustomTkinter panel, conceptually distinct
from the real-process-embedding machinery the rest of app_panels.py is
about. Shared panel geometry and titlebar styling live in panel_ui.py.

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
import customtkinter as ctk

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
_update_active_panel_glow = _ide_module._update_active_panel_glow
import panel_ui

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
        ctk.CTkLabel(
            self, text=f"{title} \u2014 {faculty}", text_color=C["fg"],
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

        ctk.CTkLabel(
            self, text="API key", text_color=C["fg_dim"],
            font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(10, 0))
        key_row = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        key_row.pack(fill="x", padx=14, pady=(2, 0))
        self._key_entry = ctk.CTkEntry(
            key_row, textvariable=self._key_var, show="\u2022",
            fg_color=C["input"], text_color=C["fg"],
            font=("Segoe UI", 10), corner_radius=8)
        self._key_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self._show_var = tk.BooleanVar(value=False)

        def _toggle_show():
            self._key_entry.configure(show="" if self._show_var.get() else "\u2022")

        ctk.CTkCheckBox(
            key_row, text="Show", variable=self._show_var, command=_toggle_show,
            text_color=C["fg_dim"], fg_color=C["accent"],
            hover_color=C["accent_hover"], border_color=C["border"],
            font=("Segoe UI", 8), checkbox_width=16, checkbox_height=16,
        ).pack(side="left", padx=(8, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        btn_row.pack(fill="x", padx=14, pady=14)
        panel_ui.style_button(
            ctk.CTkButton(btn_row, text="Cancel", command=self.destroy), C
        ).pack(side="right", padx=(6, 0))
        panel_ui.style_button(
            ctk.CTkButton(btn_row, text="Save", command=self._submit), C, "primary"
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
        ctk.CTkLabel(
            self, text=label, text_color=C["fg_dim"],
            font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(10, 0))
        ctk.CTkEntry(
            self, textvariable=var, fg_color=C["input"], text_color=C["fg"],
            border_width=1, border_color=C["border"],
            font=("Segoe UI", 10), corner_radius=8,
        ).pack(fill="x", padx=14, pady=(4, 0), ipady=6)

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
    TITLEBAR_H = panel_ui.TITLEBAR_H
    BORDER_PX = panel_ui.BORDER_PX

    def __init__(self, master, on_minimize, on_close, corner_index=0,
                 initial_content=None, bounds=None):
        super().__init__(master)
        self.title("Settings")
        self.overrideredirect(True)
        self.configure(bg=C["border_hi"])
        self.is_maximized = False
        self._is_active_panel = False
        self._friday_glow_state = "idle"
        self._friday_glow_is_error = False
        self._active_glow = _ActiveGlowAnimator(
            self, lambda c: self.configure(bg=c))

        if bounds is not None:
            x, y, w, h = bounds
        else:
            w, h = self.DEFAULT_W, self.DEFAULT_H
            x, y = panel_ui.corner_position(master, corner_index, w, h)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self._default_geometry = (x, y, w, h)

        self._data = {}
        self._row_widgets = {}  # (faculty, id) -> {"dot":..., "status_lbl":..., ...}
        self._wheel_widgets = set()

        bp = self.BORDER_PX
        # Titlebar (with a real, working close button) is built first,
        # before anything below that depends on settings_store actually
        # loading cleanly -- so even if that ever fails for some reason
        # (a corrupted settings file, a missing dependency, ...), this
        # panel is never left on screen as an inert, un-closeable blank
        # window; see the try/except further down.
        panel_ui.build_titlebar(
            self, C, "Settings \u2014 AI Models", on_minimize, on_close,
            self.TITLEBAR_H, bp)

        # -- a one-line subheader + "Check all" --
        sub = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=0)
        sub.pack(side="top", fill="x", padx=bp)
        ctk.CTkLabel(
            sub, text="API keys are masked below. Checking a model makes a real,"
                     " silent call to its API before it's shown as connected.",
            text_color=C["fg_dim"], font=("Segoe UI", 9), wraplength=560,
            justify="left").pack(side="left", padx=8, pady=6)
        panel_ui.style_button(
            ctk.CTkButton(sub, text="Check all", command=self._check_all),
            C, "primary"
        ).pack(side="right", padx=8, pady=6)

        # -- scrollable body --
        body_host = ctk.CTkFrame(
            self, fg_color=C["editor"], corner_radius=0)
        body_host.pack(side="top", fill="both", expand=True, padx=bp, pady=(0, bp))
        self._canvas = tk.Canvas(body_host, bg=C["editor"], highlightthickness=0,
                                  bd=0)
        vsb = tk.Scrollbar(body_host, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._body = ctk.CTkFrame(
            self._canvas, fg_color=C["editor"], corner_radius=0)
        self._body_window = self._canvas.create_window((0, 0), window=self._body,
                                                         anchor="nw")

        def _on_body_configure(_e):
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))

        def _on_canvas_configure(e):
            self._body.configure(width=e.width)

        self._body.bind("<Configure>", _on_body_configure)
        self._canvas.bind("<Configure>", _on_canvas_configure)

        self._canvas.bind("<MouseWheel>", self._on_mousewheel, add="+")
        self._canvas.bind("<Button-4>", self._on_mousewheel, add="+")
        self._canvas.bind("<Button-5>", self._on_mousewheel, add="+")

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
        ctk.CTkLabel(
            self._body, text="Settings couldn't fully load.",
            text_color=C["danger"], font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=14, pady=(16, 4))
        ctk.CTkLabel(
            self._body, text=str(exc), text_color=C["fg_dim"],
            font=("Segoe UI", 9), wraplength=640, justify="left",
        ).pack(anchor="w", padx=14)
        ctk.CTkLabel(
            self._body,
            text="Close this panel and try opening Settings again -- "
                 "if it keeps happening, check the terminal Friday "
                 "was started from for the full error.",
            text_color=C["fg_faint"], font=("Segoe UI", 8),
            wraplength=640, justify="left",
        ).pack(anchor="w", padx=14, pady=(8, 0))

    # ---------------------------------------------------------------
    # Rendering
    # ---------------------------------------------------------------
    def _on_mousewheel(self, event):
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self._canvas.yview_scroll(delta, "units")
        return "break"

    def _render_all(self):
        self._wheel_widgets.clear()
        old_sections = tuple(self._body.winfo_children())
        for section in old_sections:
            section.pack_forget()
        if old_sections:
            self.after_idle(
                lambda sections=old_sections: self._destroy_sections(sections))
        self._row_widgets.clear()
        for faculty in settings_store.FACULTIES:
            self._render_faculty(faculty)
        self._bind_mousewheel(self._body)

    @staticmethod
    def _destroy_sections(sections):
        for section in sections:
            if section.winfo_exists():
                section.destroy()

    def _bind_mousewheel(self, widget):
        surface = (widget._canvas if isinstance(widget, ctk.CTkBaseClass)
                   else widget)
        self._wheel_widgets.add(surface)
        surface.bind("<MouseWheel>", self._on_mousewheel, add="+")
        surface.bind("<Button-4>", self._on_mousewheel, add="+")
        surface.bind("<Button-5>", self._on_mousewheel, add="+")
        for child in widget.winfo_children():
            self._bind_mousewheel(child)

    def _render_faculty(self, faculty):
        section = ctk.CTkFrame(
            self._body, fg_color=C["panel"], border_width=1,
            border_color=C["border"], corner_radius=10)
        section.pack(side="top", fill="x", pady=(8, 4), padx=10)

        header = ctk.CTkFrame(
            section, fg_color="transparent", corner_radius=0)
        header.pack(side="top", fill="x", padx=12, pady=(10, 6))
        ctk.CTkLabel(
            header, text=faculty, text_color=C["fg_bright"],
            font=("Segoe UI", 11, "bold")).pack(side="left")
        panel_ui.style_button(
            ctk.CTkButton(
                header, text="+ Add model",
                command=lambda f=faculty: self._open_add_dialog(f)),
            C, "secondary"
        ).pack(side="right")

        if faculty in _SCAFFOLD_ONLY_FACULTIES:
            ctk.CTkLabel(
                section, text=("Friday doesn't call out to a real " + faculty.lower() +
                               " provider yet \u2014 entries here are saved for when that "
                               "lands, and \"Check\" still makes a real reachability call "
                               "against whatever you add."),
                text_color=C["fg_faint"], font=("Segoe UI", 9),
                justify="left", wraplength=640, anchor="w",
            ).pack(side="top", fill="x", padx=12, pady=(0, 8))

        rows_host = ctk.CTkFrame(
            section, fg_color="transparent", corner_radius=0)
        rows_host.pack(side="top", fill="x", padx=8, pady=(0, 8))

        entries = self._data.get(faculty, [])
        if not entries:
            ctk.CTkLabel(
                rows_host, text="No models added yet.",
                text_color=C["fg_faint"], font=("Segoe UI", 9, "italic"),
            ).pack(side="top", anchor="w", pady=4)
        for entry in entries:
            self._render_row(rows_host, faculty, entry)

        ctk.CTkFrame(
            section, fg_color=C["border_soft"], height=1, corner_radius=0,
        ).pack(side="top", fill="x", padx=12, pady=(0, 1))

    def _render_row(self, parent, faculty, entry):
        row = ctk.CTkFrame(
            parent, fg_color=C["chat"], corner_radius=8)
        row.pack(side="top", fill="x", pady=3)

        dot = ctk.CTkLabel(
            row, text="\u25cf", text_color=C["fg_faint"],
            font=("Segoe UI", 10))
        dot.pack(side="left", padx=(10, 6), pady=8)

        name_col = ctk.CTkFrame(
            row, fg_color="transparent", corner_radius=0)
        name_col.pack(side="left", fill="x", expand=True, pady=4)
        ctk.CTkLabel(
            name_col, text=entry["name"], text_color=C["fg"],
            font=("Segoe UI", 10, "bold")).pack(side="top", anchor="w")
        model_txt = entry.get("model") or "\u2014"
        ctk.CTkLabel(
            name_col, text=model_txt, text_color=C["fg_dim"],
            font=("Segoe UI", 9)).pack(side="top", anchor="w")

        key_lbl = ctk.CTkLabel(
            row, text=settings_store.mask_key(entry.get("api_key", "")),
            text_color=C["fg_dim"], font=("Consolas", 9))
        key_lbl.pack(side="left", padx=10)

        status_lbl = ctk.CTkLabel(
            row, text="", font=("Segoe UI", 9, "bold"))
        status_lbl.pack(side="left", padx=(0, 10))

        check_btn = panel_ui.style_button(
            ctk.CTkButton(
                row, text="Check",
                command=lambda f=faculty, e=entry: self._run_check(f, e)),
            C)
        check_btn.pack(side="left", padx=2, pady=5)
        panel_ui.style_button(
            ctk.CTkButton(
                row, text="Edit",
                command=lambda f=faculty, e=entry: self._open_edit_dialog(f, e)),
            C
        ).pack(side="left", padx=2, pady=5)
        panel_ui.style_button(
            ctk.CTkButton(
                row, text="Remove",
                command=lambda f=faculty, e=entry: self._remove(f, e)),
            C, "danger"
        ).pack(side="left", padx=(2, 8), pady=5)

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
        widgets["dot"].configure(text_color=color)
        widgets["status_lbl"].configure(text=f"{glyph} {label}", text_color=color)
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
    # destroy come from this native Tk Toplevel.
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
