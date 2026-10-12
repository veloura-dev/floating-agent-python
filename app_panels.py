"""Friday's own tracked "real app" panels: native desktop applications
(Chrome, Notepad, Calculator, ...) that Friday opens on command and now
considers one of *his* panels, the same way the coding IDE already is
(see ide.py's MinimizedPill / IDEApp.minimize_to_pill).

Two different "owned panel" treatments live here, chosen per app:

  - Embeddable apps (Notepad, Calculator) open **inside** a small
    Friday-drawn frame (EmbeddedAppPanel below) at a default size in a
    corner of the screen: the real app's own window is reparented into
    that frame (Windows' SetParent, no pywin32 dependency needed), with
    its OS-native title bar/border stripped off, so the running app
    visually lives inside Friday's own panel rather than floating
    around as an independent native window. Minimizing that panel just
    hides the whole frame (which hides the embedded app along with it)
    and shows a small pill under the circle, the same way the IDE's
    own minimize-to-pill already works.
  - Chrome is deliberately *not* embedded this way, by explicit user
    choice: real window embedding via SetParent is a well-known rough
    edge for apps that do their own GPU-accelerated compositing
    (blank/black rendering, lost input, flicker) and Chrome is the
    textbook example. It opens as a real, independent window instead,
    still tracked/minimizable/closeable by Friday -- minimizing it
    triggers a real OS-level minimize (to the taskbar) plus the same
    kind of pill as a visible handle on it.

Deliberately decoupled from agent_tools.py/ide.py's own Tk-threading
machinery for the coding IDE itself (see agent_tools.py's long comments
on _tk_worker_loop/_TkThreadBridge for just how much hard-won care that
needs) — opening Chrome or Notepad has nothing to do with coding, so
this module runs its own small dedicated Tk thread purely to host pill
and panel-frame widgets, started lazily the first time it's actually
needed, entirely independent of whether Agent Mode (the code IDE) is on
at all. Treating the IDE itself as one more of these same top-level
"panels" (so "minimize all" covers it too) is agent_tools.py's job, not
this module's — it composes this manager with the IDE's own existing
minimize_to_pill()/restore_from_pill(), since those already work and
this module has no business reaching into the IDE's Tk thread itself.

The real OS process launch and the win32 window-handle work (find /
embed / minimize / restore / close a foreign window) are all behind
small pluggable backends so this whole thing is testable without a real
Windows desktop or a real Chrome/Calculator to launch — see
dev_tests/test_app_panels.py's Fake* classes.

Notepad is a deliberate third category, as of this project's Task 44
follow-up: not a real OS process at all. After the SetParent-based real-
Notepad embedding path broke on a real Windows PC three separate times
(see IDE_CAPABILITY_AUDIT.md Parts 7/8/10 for the whole saga, each one
root-causing and fixing a *different* real bug in that path), it was
retired outright in favor of CustomNotepadPanel below: a small, fully
Friday-native Markdown-ish text editor with no foreign window in it at
all. There is nothing left for a ctypes/SetParent bug to ever corrupt
for Notepad again, by construction, since there's no real notepad.exe
involved anywhere in the picture any more.
"""
import atexit
import os
import platform
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from shutil import which as _which
from tkinter import filedialog, messagebox, simpledialog
import customtkinter as ctk


# ide.py's MinimizedPill is already a fully generic small pill-shaped
# Toplevel (master, label, agent_host, circle_bottom, on_restore) with no
# IDE-specific assumptions baked in anywhere -- reused as-is here instead
# of duplicating the same canvas-drawing code a second time. Its color
# palette (C) is reused for EmbeddedAppPanel below too, so a panel looks
# visually consistent with the rest of Friday's own UI.
_IDE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ide")
if _IDE_DIR not in sys.path:
    sys.path.insert(0, _IDE_DIR)
import ide as _ide_module  # noqa: E402
MinimizedPill = _ide_module.MinimizedPill
C = _ide_module.C
import panel_ui
# Same spirit as MinimizedPill above -- ide.py's _ActiveGlowAnimator is
# already a fully generic pulsing-border-animation driver with no
# IDE-specific assumptions baked in (it just needs a widget with
# .after()/.winfo_exists() and a set_color(hex) callback), reused as-is
# by both EmbeddedAppPanel and CustomNotepadPanel below for their own
# "I'm Friday's current active/maximized panel" border pulse.
_ActiveGlowAnimator = _ide_module._ActiveGlowAnimator
_update_active_panel_glow = _ide_module._update_active_panel_glow


KNOWN_APPS = {
    "chrome": {
        "label": "Chrome",
        "aliases": ("chrome", "google chrome", "browser", "web browser"),
        # Used as a last-resort title-match fallback when a launched
        # app's real window isn't owned by the process we actually
        # spawned -- see the long comment on find_hwnd_for_launch below
        # for why that happens on modern Windows for Calculator
        # specifically. Chrome's own window process is reliable, so this
        # mostly never gets used for it, but it's harmless to have.
        "title_hint": "chrome",
    },
    "notepad": {
        "label": "Notepad",
        "aliases": ("notepad", "note pad", "text editor", "notes"),
    },
    "calculator": {
        "label": "Calculator",
        "aliases": ("calculator", "calc"),
        "title_hint": "calculator",
    },
    "settings": {
        "label": "Settings",
        "aliases": ("settings", "settings panel", "ai settings", "model settings",
                    "api settings", "ai models", "model manager"),
    },
    "chat": {
        "label": "Chat",
        "aliases": ("chat", "chat panel", "open chat", "new chat"),
    },
    "profile": {
        "label": "Profile",
        "aliases": ("profile", "profile panel", "my profile", "user profile"),
    },
    "image_gen": {
        "label": "Image Generation",
        "aliases": ("image generation", "image gen", "image gen panel",
                    "generate an image", "image generator"),
    },
    "video_gen": {
        "label": "Video Generation",
        "aliases": ("video generation", "video gen", "video gen panel",
                    "generate a video", "video generator"),
    },
}

# Apps Friday actually embeds a *real OS window* for, inside his own
# small panel frame (SetParent-based reparenting; see RealWindowBackend
# below). Chrome is excluded by explicit user decision -- see this
# module's docstring. Notepad is excluded too, as of Task 44's follow-up
# -- it's CUSTOM_PANEL_APPS instead (see below), not a real window at
# all any more.
EMBEDDABLE_APPS = {"calculator"}

# Apps that are entirely Friday's own native UI -- no real OS process,
# no window handle, no SetParent reparenting, nothing for a win32/ctypes
# bug to ever touch. See CustomNotepadPanel's own docstring for why
# Notepad specifically moved here, and SettingsPanel's own (in
# settings_panel.py) for why Settings is built the same way.
CUSTOM_PANEL_APPS = {"notepad", "settings", "chat", "profile", "image_gen", "video_gen"}

# Which fully-native panel class CUSTOM_PANEL_APPS maps each key to --
# see _open_custom_panel below, which constructs whichever one `key`
# resolves to with an identical call signature for all of them.
_CUSTOM_PANEL_CLASSES = {
    "notepad": None,    # filled in below, once CustomNotepadPanel is importable
    "settings": None,   # filled in below, once SettingsPanel is importable
    "chat": None,        # filled in below, once ChatPanel is importable
    "profile": None,     # filled in below, once ProfilePanel is importable
    "image_gen": None,   # filled in below, once ImageGenPanel is importable
    "video_gen": None,   # filled in below, once VideoGenPanel is importable
}



def resolve_app_key(name):
    """Turns a spoken/typed app name into one of KNOWN_APPS's keys, or
    None if it isn't one Friday knows how to open yet."""
    n = (name or "").strip().lower()
    if n in KNOWN_APPS:
        return n
    for key, meta in KNOWN_APPS.items():
        if n in meta["aliases"]:
            return key
    return None


def known_app_labels():
    return ", ".join(meta["label"] for meta in KNOWN_APPS.values())


# RealLauncher/RealWindowBackend/RealTyper/_PanelHostBridge -- the real
# OS-process-launch and win32 window-handle primitives -- live in
# window_backend.py now (split out purely to keep this file a readable
# size; see that module's own docstring). Imported with their exact
# original names so AppPanelManager below (and anything that reaches for
# `app_panels.RealWindowBackend` etc.) keeps working unchanged.
from window_backend import (  # noqa: E402
    RealLauncher, RealWindowBackend, RealTyper, _PanelHostBridge,
)


class EmbeddedAppPanel(tk.Toplevel):
    """A small, Friday-drawn window frame (no OS title bar of its own —
    this is entirely Friday's own chrome) that a real embeddable app's
    window gets reparented into, so the app visually lives *inside* one
    of Friday's own panels instead of floating around as an independent
    native window. Opens at a default small size in a rotating screen
    corner so several of these (plus the IDE, wherever it is) don't
    automatically stack on top of each other. Draggable by its own
    title strip since an undecorated window has no OS-provided way to
    move itself.

    This class only knows how to be a frame with a slot to embed into —
    it has no idea *why* a given app was or wasn't embedded into it
    (that's AppPanelManager's job, including the graceful give-up-and-
    fall-back-to-a-plain-window path when real embedding isn't possible
    at all, e.g. not on Windows, or the embed() call itself fails).
    """

    # Default small-panel size -- only actually used by the plain
    # corner-rotation fallback below, for a panel built with no
    # agent_host/placement system wired up at all (e.g. a standalone
    # AppPanelManager, or a direct test of this class). Every real,
    # agent-hosted panel open always gets full-screen bounds from
    # agent_tools.py's unified single-active-panel placement system
    # instead (there's no smaller/side-slot size in that system any
    # more -- a panel is either this maximized or minimized to a pill,
    # nothing in between). Matches the size of the reference screenshot
    # the user asked for explicitly (down from the original 480x360).
    DEFAULT_W = panel_ui.DEFAULT_PANEL_W
    DEFAULT_H = panel_ui.DEFAULT_PANEL_H
    TITLEBAR_H = panel_ui.TITLEBAR_H
    MARGIN = panel_ui.PANEL_MARGIN
    BORDER_PX = panel_ui.BORDER_PX

    def __init__(self, master, label, on_minimize, on_close, corner_index=0,
                 bounds=None):
        super().__init__(master)
        self.title(label)
        self.overrideredirect(True)
        self.configure(bg=C["border_hi"])
        self.is_maximized = False

        if bounds is not None:
            # Friday's unified panel-placement system (agent_tools.py)
            # has already decided exactly where this panel should open
            # -- always the one shared full-screen maximized slot now,
            # since opening/restoring any panel immediately makes it
            # the single active one -- so use that directly instead of
            # the plain corner rotation below (still kept as the
            # standalone/no-agent_host fallback, e.g.
            # test_embedding_standalone.py or an isolated
            # AppPanelManager built with agent_host=None).
            x, y, w, h = bounds
        else:
            w, h = self.DEFAULT_W, self.DEFAULT_H
            x, y = self._corner_position(master, corner_index, w, h)
        self.geometry(f"{w}x{h}+{x}+{y}")
        # Remembered so restore_default() can always get back to exactly
        # this panel's own normal size/corner, regardless of how many
        # times it's since been maximized/un-maximized.
        self._default_geometry = (x, y, w, h)

        bp = self.BORDER_PX
        panel_ui.build_titlebar(
            self, C, label, on_minimize, on_close, self.TITLEBAR_H, bp)

        # Pulsing "this is Friday's current active panel" border --
        # see ide.py's _ActiveGlowAnimator docstring. Starts/stops from
        # maximize_to()/move_to_slot() below (maximize_to() is the only
        # one of the two actually driven by agent_tools.py's unified
        # placement system now -- move_to_slot()/restore_default() are
        # lower-level mechanics kept for the standalone/no-agent_host
        # fallback and direct unit tests, since real panel opens are
        # always either fully maximized or fully minimized to a pill),
        # and from AppPanelManager whenever this panel is minimized or
        # closed while it happened to be the active one.
        self._is_active_panel = False
        self._friday_glow_state = "idle"
        self._friday_glow_is_error = False
        self._active_glow = _ActiveGlowAnimator(
            self, lambda c: self.configure(bg=c))

        # The slot the real app's window gets reparented into (its own
        # native HWND is what embed()/resize_embedded() actually use).
        self.slot = tk.Frame(self, bg=C["editor"])
        self.slot.pack(side="top", fill="both", expand=True, padx=bp, pady=(0, bp))

        self._on_resize_cb = None
        self.slot.bind("<Configure>", self._on_slot_configure)

    def move_to(self, x, y, w, h):
        """The bare geometry-change mechanics shared by maximize_to()
        (the one shared full-screen maximized slot) and move_to_slot()
        (a smaller, specific rectangle -- not driven by
        agent_tools.py's unified placement system any more, kept as
        lower-level plumbing for the standalone/no-agent_host fallback
        and direct unit tests) alike -- resizes/repositions this panel
        to exactly (x, y, w, h) and raises it to the front. The
        embedded real app's window is kept in sync automatically via
        the existing slot <Configure> -> resize_embedded callback, no
        extra work needed here for that part. Doesn't touch
        is_maximized -- see the two callers below for that."""
        self._set_geometry_firmly(x, y, w, h)
        try:
            self.lift()
        except tk.TclError:
            pass

    def maximize_to(self, x, y, w, h):
        """Resizes/repositions this panel to exactly (x, y, w, h) --
        the one shared full-screen maximized slot every panel
        maximizes to fill, the only state a real agent-hosted panel is
        ever actually placed in besides fully minimized -- and flags it
        as the active/maximized panel."""
        self.move_to(x, y, w, h)
        self.is_maximized = True
        self.set_active_panel(True)

    def move_to_slot(self, x, y, w, h):
        """Moves this panel to a smaller, specific rectangle -- same
        physical mechanics as maximize_to(), just without flagging it
        as the maximized/active panel. Not called by agent_tools.py's
        unified placement system any more (a panel there is always
        either fully maximized or fully minimized to a pill, nothing
        smaller in between) -- kept as lower-level plumbing for the
        standalone/no-agent_host fallback and direct unit tests. Also
        updates this panel's own remembered "default" position to the
        new spot, so a later plain restore_default() (that same
        no-agent_host fallback path) lands here too, not back at
        wherever it happened to first open."""
        self.move_to(x, y, w, h)
        self.set_active_panel(False)
        self.is_maximized = False
        self._default_geometry = (x, y, w, h)

    def restore_default(self):
        """Reverses maximize_to(): shrinks this panel back down to its
        own normal small default size/corner position (or wherever
        move_to_slot() last placed it, for callers that use that
        lower-level method directly), and lowers it back out of the way
        (it's no longer the active/maximized one)."""
        x, y, w, h = self._default_geometry
        self._set_geometry_firmly(x, y, w, h)
        try:
            self.lower()
        except tk.TclError:
            pass
        self.is_maximized = False
        self.set_active_panel(False)

    def set_active_panel(self, active):
        """Tells this panel whether it's currently Friday's single
        active/maximized panel right now, so it can show (active) or
        stop showing (not active) the pulsing accent active-panel
        border -- see ide.py's _ActiveGlowAnimator. Called from
        maximize_to()/move_to_slot()/restore_default() above (the
        places this panel becomes/stops being the maximized one), and
        from AppPanelManager when this panel is minimized or closed
        while it happened to be the active one. Safe to call repeatedly
        with the same value."""
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
        """Sets this Toplevel's geometry and makes sure the *position*
        actually sticks -- Tk's own pack-propagate machinery can react
        to the resize (titlebar/slot frames re-laying-out to the new
        size) by reasserting just a size-only `wm geometry` update of
        its own right afterwards, using whatever position it had
        internally tracked *before* our move was confirmed by a real
        Configure round-trip -- which silently undoes the position half
        of our own change while leaving the size half intact. Forcing
        an idletasks pass and then reapplying the exact same geometry
        string a second time reliably wins that race."""
        geom = f"{int(w)}x{int(h)}+{int(x)}+{int(y)}"
        try:
            self.geometry(geom)
            self.update_idletasks()
            self.geometry(geom)
        except tk.TclError:
            pass

    def _on_slot_configure(self, event):
        if self._on_resize_cb is not None:
            try:
                self._on_resize_cb(event.width, event.height)
            except Exception:  # noqa: BLE001
                pass

    def set_resize_callback(self, cb):
        self._on_resize_cb = cb

    def slot_size(self):
        return (self.slot.winfo_width(), self.slot.winfo_height())

    def slot_hwnd(self):
        """The real native window handle of the embedding slot (its own
        winfo_id() is a real HWND on Windows -- that's what embed()
        reparents the app's window into), or None if this Tk build
        can't resolve one for any reason."""
        try:
            return self.slot.winfo_id()
        except tk.TclError:
            return None

    @staticmethod
    def _corner_position(master, index, w, h):
        return panel_ui.corner_position(master, index, w, h)


# Custom panel implementations live in focused modules and are
# re-exported here to preserve the public app_panels API.
from notepad_panel import CustomNotepadPanel  # noqa: E402

from settings_panel import SettingsPanel  # noqa: E402

from conversation_panels import (  # noqa: E402
    ChatPanel, ProfilePanel, ImageGenPanel, VideoGenPanel,
)

_CUSTOM_PANEL_CLASSES["notepad"] = CustomNotepadPanel
_CUSTOM_PANEL_CLASSES["settings"] = SettingsPanel
_CUSTOM_PANEL_CLASSES["chat"] = ChatPanel
_CUSTOM_PANEL_CLASSES["profile"] = ProfilePanel
_CUSTOM_PANEL_CLASSES["image_gen"] = ImageGenPanel
_CUSTOM_PANEL_CLASSES["video_gen"] = VideoGenPanel


class AppPanelManager:
    """Tracks every real native app Friday has opened on command (keyed
    by app type -- "common few" apps for now, one tracked instance of
    each at a time, matching how a real single-instance app like Chrome
    actually behaves) and lets them be minimized to a pill under the
    circle, restored, closed, listed, or (for a couple of apps) driven
    a little from the inside. Everything here is safe to call from any
    thread -- the Tk pill/panel host is marshaled onto internally, same
    spirit as agent_tools.py's own _run_on_main for the IDE.
    """

    def __init__(self, launcher=None, window_backend=None, typer=None,
                 agent_host=None):
        self._launcher = launcher or RealLauncher()
        self._backend = window_backend or RealWindowBackend()
        self._typer = typer or RealTyper()
        self._agent_host = agent_host
        self._panels = {}
        self._lock = threading.RLock()
        self._root = None
        self._bridge = None
        self._thread = None
        # Registered once per instance so this manager's own background
        # Tk host thread (if _ensure_host() ever actually spins one up
        # for a Calculator/Notepad panel) always gets a clean chance to
        # stop before the process truly exits -- see shutdown()'s
        # docstring for exactly why this matters and can't just be left
        # to the daemon=True flag alone.
        atexit.register(self.shutdown)

    # ---------------------------------------------------------------
    # Tk pill/panel-host lifecycle
    # ---------------------------------------------------------------
    def shutdown(self):
        """Stops this manager's own background Tk host thread, if one
        was ever actually created (by opening Calculator/Notepad --
        see _ensure_host()). Harmless, idempotent no-op otherwise, and
        safe to call more than once.

        Why this is needed at all: that host thread's whole body is
        `tk.Tk(); root.mainloop()`, i.e. it spends its *entire* life
        (not just while a panel happens to be open) blocked inside a
        single native Tcl call. `daemon=True` alone does NOT make a
        thread like that harmless to just leave running -- it only
        stops it from keeping the interpreter alive *indefinitely*; it
        does nothing to stop CPython's normal shutdown sequence (the
        one `sys.exit()` triggers, which is exactly how this project's
        real entry point in agent_overlay.py quits) from hanging while
        it tries to finalize a thread that's still mid-call inside a C
        extension's event loop. Observed directly in testing: a plain
        script that opened a Notepad panel and returned normally hung
        forever instead of exiting, until this method started being
        called. Telling the Tcl side itself to stop (root.quit(), which
        makes mainloop() return and lets the thread fall off the end of
        its target function normally) *before* interpreter shutdown
        begins -- which is exactly what an atexit hook runs early
        enough to do -- sidesteps the whole problem.
        """
        with self._lock:
            root, thread = self._root, self._thread
        if root is None or thread is None:
            return

        def _stop_host():
            with self._lock:
                panels = list(self._panels.values())
                self._panels.clear()
            try:
                for rec in panels:
                    self._destroy_widgets(rec)
            finally:
                root.quit()

        try:
            root.after(0, _stop_host)
        except Exception:  # noqa: BLE001
            try:
                root.quit()
            except Exception:  # noqa: BLE001
                pass
        thread.join(timeout=2.0)
        with self._lock:
            if self._root is root:
                self._root = None
                self._bridge = None
                self._thread = None

    def _ensure_host(self):
        with self._lock:
            if self._thread is not None:
                return
            ready = threading.Event()
            box = {}

            def _run():
                root = tk.Tk()
                root.withdraw()
                box["root"] = root
                ready.set()
                root.mainloop()

            t = threading.Thread(
                target=_run, name="Friday-AppPanels-Tk", daemon=True)
            t.start()
            ready.wait()
            self._root = box["root"]
            self._thread = t
            self._bridge = _PanelHostBridge(self._root, t)

    def _circle_bottom(self):
        if self._agent_host is None:
            return None
        try:
            rect = self._agent_host.get_circle_rect()
        except Exception:  # noqa: BLE001
            return None
        if not rect:
            return None
        cx, cy, diameter = rect
        return (cx, cy + diameter / 2)

    # ---------------------------------------------------------------
    # Bookkeeping
    # ---------------------------------------------------------------
    def _live_panels(self):
        """Returns {key: record} for everything still actually running,
        quietly dropping (and tidying up the pill/frame for) anything
        whose process has exited on its own since the last check -- the
        user closing an app by hand, for instance."""
        with self._lock:
            dead = [k for k, r in self._panels.items()
                    if r.get("proc") is not None and r["proc"].poll() is not None]
            for k in dead:
                rec = self._panels.pop(k)
                self._destroy_widgets(rec)
            return dict(self._panels)

    def _destroy_widgets(self, rec):
        if self._bridge is None:
            return
        for widget_key in ("pill", "frame"):
            widget = rec.get(widget_key)
            if widget is not None:
                try:
                    def _destroy():
                        animator = getattr(widget, "_active_glow", None)
                        if animator is not None:
                            animator.stop()
                        widget.destroy()

                    self._bridge.call(_destroy)
                except Exception:  # noqa: BLE001
                    pass

    def _match(self, which):
        """Same spirit as ide_close_tab's name matching: an exact key/
        label match wins outright; otherwise a case-insensitive
        substring match against every open panel's key/label. Returns
        a list of (key, record) pairs -- empty, one, or more than one."""
        panels = self._live_panels()
        w = (which or "").strip().lower()
        for key, rec in panels.items():
            if w == key or w == rec["label"].lower():
                return [(key, rec)]
        return [(key, rec) for key, rec in panels.items()
                if w in key or w in rec["label"].lower()]

    def list_panels(self):
        panels = self._live_panels()
        if not panels:
            return "No app panels are open right now."
        lines = []
        for rec in panels.values():
            state = "minimized" if rec.get("minimized") else "open"
            if rec.get("maximized"):
                state += ", maximized"
            extra = ""
            if rec.get("custom"):
                extra = (f" — Friday's own built-in {rec['label'].lower()} "
                         "(not a separate real window)")
            elif rec.get("embedded"):
                extra = " — embedded in its own panel"
            elif rec.get("embed_note"):
                extra = f" — {rec['embed_note']}"
            lines.append(f"- {rec['label']} ({state}){extra}")
        return "\n".join(lines)

    def reposition_pill(self, key, slot_index):
        """Live-repositions `key`'s already-shown pill to `slot_index`'s
        slot in the shared stack -- called when some other panel's pill
        above it was removed (restored/closed) and everything below it
        needs to shift up to close the gap. Best-effort/no-op if `key`
        isn't actually minimized right now (e.g. it raced ahead and was
        itself just restored)."""
        rec = self._panels.get(key)
        if rec is None:
            return
        pill = rec.get("pill")
        if pill is None or self._bridge is None:
            return
        origin = self._circle_bottom()
        if origin is None:
            return
        cx, bottom_y = origin
        offset = slot_index * MinimizedPill.STACK_STEP
        try:
            self._bridge.call(lambda: pill.reposition((cx, bottom_y + offset)))
        except Exception:  # noqa: BLE001
            pass

    def set_status(self, key, status):
        """Records `key`'s current status ("normal"/"waiting"/"done"/
        "error" -- see MinimizedPill._STATUS_COLORS) and, if its pill is
        showing right now, recolors it live. Called via
        agent_tools.report_panel_status(key, status). The status itself
        is remembered on the panel's own record regardless of whether
        it's actually minimized at the moment it's set, so a panel
        minimized *after* its status already changed still shows the
        right color immediately rather than starting blank (see the
        pill-creation site in minimize() that applies rec["status"] to
        a freshly-built pill). No app_panels.py-managed panel
        (Chrome/Notepad/Calculator) actually drives this today -- none
        of them have a "paused/working/erroring" concept of their own
        yet -- this exists so a future one can use the same mechanism
        the IDE's own chat-driven tasks already do. Best-effort, never
        raises.
        """
        rec = self._panels.get(key)
        if rec is None:
            return
        rec["status"] = status
        pill = rec.get("pill")
        if pill is None or self._bridge is None:
            return
        try:
            self._bridge.call(lambda: pill.set_status(status))
        except Exception:  # noqa: BLE001
            pass

    def _current_friday_status(self):
        getter = getattr(self._agent_host, "get_friday_status", None)
        if getter is None:
            return "idle", False
        try:
            return getter()
        except Exception:  # noqa: BLE001
            return "idle", False

    def report_friday_status(self, key, state, is_error=False):
        rec = self._panels.get(key)
        frame = rec.get("frame") if rec is not None else None
        bridge = self._bridge
        if frame is None or bridge is None or rec.get("minimized"):
            return

        def update():
            if self._panels.get(key) is rec and not rec.get("minimized"):
                frame.set_friday_status(state, is_error)

        try:
            bridge.post(update)
        except Exception:  # noqa: BLE001
            pass

    def screen_size(self):
        """(screen_width, screen_height) in real pixels, via this
        manager's own hidden Tk host (created on first use if it isn't
        already up). Falls back to a plain 1920x1080 guess if querying
        it ever fails for any reason -- used by agent_tools.py's shared
        panel-placement system to compute where the one shared
        full-screen maximized slot actually lands on screen, without
        needing the IDE to be open just to ask it."""
        self._ensure_host()
        try:
            return self._bridge.call(
                lambda: (self._root.winfo_screenwidth(), self._root.winfo_screenheight()))
        except Exception:  # noqa: BLE001
            return (1920, 1080)

    # ---------------------------------------------------------------
    # Maximize / unmaximize / lower-level slot placement
    # ---------------------------------------------------------------
    def _move_panel(self, key, bounds, mover_attr):
        """The bare physical move shared by maximize_panel() (the one
        shared full-screen maximized slot -- the only placement
        agent_tools.py's unified system actually drives any more) and
        place_in_side_slot() (a smaller, specific rectangle -- no
        longer called by that unified system, kept as lower-level
        plumbing for the standalone/no-agent_host fallback and direct
        unit tests) -- the two differ only in which bounds they pass
        in, which Friday-drawn-frame method they call (`mover_attr`:
        "maximize_to" or "move_to_slot"), and whether the panel ends up
        flagged "maximized" afterward (handled by the two callers, not
        here). Returns (True, None) on success or (False,
        reason) on failure. Dispatches to the named frame method for
        anything with its own Friday-drawn frame (Notepad's
        CustomNotepadPanel always; Calculator's EmbeddedAppPanel when
        real SetParent embedding succeeded), or
        RealWindowBackend.move_resize/bring_to_front directly against
        the real OS window for anything not framed that way (Chrome,
        always, or Calculator if it fell back to a plain window) -- the
        two cases need different mechanics but the net visible effect
        is identical either way.
        """
        rec = self._panels.get(key)
        if rec is None:
            return False, "that panel isn't open any more"
        x, y, w, h = bounds
        if rec.get("embedded") and rec.get("frame") is not None:
            try:
                self._bridge.call(lambda: getattr(rec["frame"], mover_attr)(x, y, w, h))
            except Exception as exc:  # noqa: BLE001
                return False, str(exc)
        elif rec.get("hwnd") is not None:
            if not self._backend.is_supported():
                return False, "native window control isn't available here"
            if rec.get("pre_maximize_bounds") is None:
                rec["pre_maximize_bounds"] = self._backend.get_window_rect(rec["hwnd"])
            if not self._backend.move_resize(rec["hwnd"], x, y, w, h):
                return False, "couldn't move/resize its window"
            self._backend.bring_to_front(rec["hwnd"])
        else:
            return False, "that panel has no window to resize yet"
        return True, None

    def maximize_panel(self, key, bounds):
        """Resizes/repositions the panel at `key` to exactly `bounds`
        (x, y, w, h) -- the one shared full-screen maximized slot every
        panel maximizes to fill -- and raises it to the front, flagging
        it as the active/maximized panel. Also updates `rec`'s own
        remembered placement_bounds/placement_is_maximized to match --
        critical for a real-process panel (Calculator) whose actual
        SetParent embedding hasn't finished yet (it runs on a
        background discovery thread -- see _discover_and_embed/
        _try_embed): without this, a maximize_app() call that lands
        *before* that embed finishes would be silently clobbered a
        moment later when the embed completes and builds the panel's
        real frame at its stale, already-superseded open-time bounds
        instead of here. Returns (True, None) on success or (False,
        reason) on failure."""
        ok, reason = self._move_panel(key, bounds, "maximize_to")
        if ok:
            rec = self._panels[key]
            rec["maximized"] = True
            rec["placement_bounds"] = bounds
            rec["placement_is_maximized"] = True
        return ok, reason

    def place_in_side_slot(self, key, bounds):
        """Moves the panel at `key` to a smaller, specific rectangle --
        same physical mechanics as maximize_panel(), just without
        flagging it as the maximized/active panel (and clearing any
        stale pre_maximize_bounds left over from a previous maximize --
        this fresh position is this panel's new "normal" spot now, not
        something layered on top of an old unmaximize). Not reachable
        through agent_tools.py's unified single-active-panel placement
        system any more -- _decide_placement() above always reports
        `is_maximized=True` whenever an agent_host is wired up, so this
        is now only ever exercised via the public unmaximize_panel()
        API directly (the standalone/no-agent_host fallback, or a
        direct unit test). Also updates
        `rec`'s own remembered placement_bounds/placement_is_maximized
        to match, for the same not-yet-embedded-real-process reason
        documented on maximize_panel() above. Returns (True, None) on
        success or (False, reason) on failure."""
        ok, reason = self._move_panel(key, bounds, "move_to_slot")
        if ok:
            rec = self._panels[key]
            rec["maximized"] = False
            rec["pre_maximize_bounds"] = None
            rec["placement_bounds"] = bounds
            rec["placement_is_maximized"] = False
        return ok, reason

    def unmaximize_panel(self, key, bounds=None):
        """Reverses maximize_panel(key), moving the panel back to a
        smaller, non-maximized size/position. If `bounds` is given,
        moves it there via place_in_side_slot (the mechanics are
        generic -- "side slot" here just means "some smaller, specific
        rectangle", not a slot in agent_tools.py's own placement
        policy, which no longer uses this method at all -- it now only
        ever shows a panel either fully maximized or fully minimized to
        a pill, nothing in between). With no `bounds` (the standalone/
        no-agent_host fallback, e.g. test_embedding_standalone.py),
        falls back to each panel's own remembered default position
        instead. Safe no-op if `key` isn't open or wasn't maximized."""
        rec = self._panels.get(key)
        if rec is None or not rec.get("maximized"):
            return
        if bounds is not None:
            self.place_in_side_slot(key, bounds)
            return
        if rec.get("embedded") and rec.get("frame") is not None:
            try:
                self._bridge.call(rec["frame"].restore_default)
            except Exception:  # noqa: BLE001
                pass
        elif rec.get("hwnd") is not None:
            pre_bounds = rec.get("pre_maximize_bounds")
            if pre_bounds is not None:
                self._backend.move_resize(rec["hwnd"], *pre_bounds)
            rec["pre_maximize_bounds"] = None
        rec["maximized"] = False

    # ---------------------------------------------------------------
    # Open
    # ---------------------------------------------------------------
    def _decide_placement(self, key):
        """Decides where panel `key` should land for its very first
        on-screen appearance (a fresh open, or coming back from being
        minimized) -- delegates to the agent_host's shared single-
        active-panel placement system when one is wired up (the normal
        case, shared with the IDE -- see agent_tools.py's module-level
        comment on that system), falling back to (None, False, "")
        otherwise (e.g. a standalone AppPanelManager built with
        agent_host=None, like test_embedding_standalone.py -- panels
        just fall back to each frame class's own simple corner-rotation
        default in that case). Returns (bounds_or_None, is_maximized,
        note): bounds is an explicit (x, y, w, h) to use instead of the
        panel's own default placement, or None to leave that default
        alone; is_maximized says whether `bounds` is the one shared
        maximized/center slot -- true any time an agent_host is wired
        up, since that system only ever shows a single panel on screen
        at once, full screen, with nothing else sharing it; note is a
        short string (possibly empty) to append to the caller's result
        message, e.g. noting that another panel had to be minimized to
        make room.
        """
        if self._agent_host is not None and hasattr(self._agent_host, "get_panel_placement"):
            try:
                return self._agent_host.get_panel_placement(key)
            except Exception:  # noqa: BLE001
                pass
        return None, False, ""

    def _release_panel_slot_for(self, key):
        """Releases `key`'s claim on being the one single active/
        maximized panel (a different ledger than the minimized-pill
        stack -- see _release_pill_slot_for for that one). Call this
        whenever `key` stops being visible, whether by minimizing or
        closing. No-op without an agent_host wired up, or if `key`
        wasn't the active panel to begin with."""
        if self._agent_host is not None and hasattr(self._agent_host, "release_panel_slot"):
            try:
                self._agent_host.release_panel_slot(key)
            except Exception:  # noqa: BLE001
                pass

    def open(self, name, url=None, content=None):
        key = resolve_app_key(name)
        if key is None:
            return (f"I don't know how to open '{name}' yet — I can open "
                     f"{known_app_labels()} right now.")

        with self._lock:
            existing = self._live_panels().get(key)
            if existing is not None:
                if key == "chrome" and url:
                    try:
                        self._launcher.launch(key, url=url)
                    except Exception as exc:  # noqa: BLE001
                        return f"Couldn't open that in Chrome: {exc}"
                    return f"Opened {url} in Chrome."
                if key == "notepad" and content is not None:
                    try:
                        self._bridge.call(lambda: existing["frame"].new_tab(content=content))
                    except Exception as exc:  # noqa: BLE001
                        return f"Notepad is already open, but couldn't add a new tab: {exc}"
                    return f"{existing['label']} is already open — added your text as a new tab."
                if existing.get("minimized"):
                    msg = self._restore_one(key, existing)
                    return f"{existing['label']} was already open (minimized) — {msg.lower()}"
                return f"{existing['label']} is already open."

            bounds, is_maximized, note = self._decide_placement(key)

            if key in CUSTOM_PANEL_APPS:
                return self._open_custom_panel(
                    key, content, bounds=bounds, is_maximized=is_maximized) + note

            # Snapshotted *before* launching -- find_hwnd_for_launch
            # below needs to know which visible windows already existed
            # so it can recognize the newly-opened one, since (see its
            # docstring) the process id we're about to get back from
            # launching isn't reliably the one that ends up owning the
            # real window for every app.
            before_hwnds = self._backend.snapshot_top_level_hwnds()
            try:
                proc = self._launcher.launch(key, url=url or None, file_path=None,
                                              content=content)
            except Exception as exc:  # noqa: BLE001
                return f"Couldn't open {KNOWN_APPS[key]['label']}: {exc}"

            label = KNOWN_APPS[key]["label"]
            record = {"label": label, "proc": proc, "hwnd": None,
                      "minimized": False, "pill": None, "frame": None,
                      "embedded": False, "embed_note": None, "custom": False,
                      "file_path": None, "opened_at": time.time(),
                      "maximized": False, "pre_maximize_bounds": None,
                      "placement_bounds": bounds,
                      "placement_is_maximized": is_maximized}
            self._panels[key] = record

        threading.Thread(target=self._discover_and_embed,
                          args=(key, proc, before_hwnds), daemon=True).start()

        if key == "chrome" and url:
            return f"Opened Chrome to {url}.{note}"
        if key in EMBEDDABLE_APPS:
            return f"Opened {label} — it'll appear in its own small panel in a moment.{note}"
        return f"Opened {label} — it's now one of your open panels.{note}"

    def _open_custom_panel(self, key, content, bounds=None, is_maximized=False):
        """Opens one of Friday's fully-native panels (Notepad, Settings)
        -- no real OS process, no window handle, nothing to discover
        asynchronously, so this builds the whole thing synchronously and
        returns once it's actually on screen, unlike the real-process
        path above which has to launch-then-wait. Every class in
        _CUSTOM_PANEL_CLASSES is built with the exact same call
        signature (see CustomNotepadPanel/SettingsPanel's own
        __init__), so this one dispatch works for all of them --
        `content` is notepad-specific and simply ignored by any panel
        class that doesn't use it.
        """
        self._ensure_host()
        corner = sum(1 for r in self._panels.values() if r.get("frame") is not None)
        label = KNOWN_APPS[key]["label"]
        panel_cls = _CUSTOM_PANEL_CLASSES[key]
        try:
            def create_panel():
                panel = panel_cls(
                    self._root, on_minimize=lambda: self.minimize(key),
                    on_close=lambda: self.close(key), corner_index=corner,
                    initial_content=content, bounds=bounds)
                if bounds is not None:
                    panel.is_maximized = is_maximized
                    panel.set_active_panel(is_maximized)
                    if is_maximized:
                        panel.set_friday_status(*self._current_friday_status())
                return panel

            panel = self._bridge.call(create_panel)
        except Exception as exc:  # noqa: BLE001
            return f"Couldn't open {label}: {exc}"
        record = {"label": label, "proc": None, "hwnd": None,
                  "minimized": False, "pill": None, "frame": panel,
                  "embedded": True, "embed_note": None, "custom": True,
                  "file_path": None, "opened_at": time.time(),
                  "maximized": is_maximized, "pre_maximize_bounds": None,
                  "placement_bounds": bounds}
        with self._lock:
            self._panels[key] = record
        if content:
            return (f"Opened {label} with your text in it — it's not saved to disk "
                     "yet, just say where to save it (e.g. \"save that as notes.txt "
                     "on my Desktop\") whenever you're ready, or use File > Save in "
                     "the panel yourself.")
        return f"Opened {label} — it's now one of your open panels."

    def _discover_and_embed(self, key, proc, before_hwnds):
        title_hint = KNOWN_APPS[key].get("title_hint")
        hwnd = self._backend.find_hwnd_for_launch(proc.pid, title_hint, before_hwnds)
        with self._lock:
            rec = self._panels.get(key)
            if rec is None or rec.get("proc") is not proc:
                return  # closed, or replaced by a newer open() call already
            rec["hwnd"] = hwnd
            bounds = rec.get("placement_bounds")
            is_maximized = rec.get("placement_is_maximized", False)
            if hwnd is None and key in EMBEDDABLE_APPS:
                # Self-diagnosing fallback: rather than failing
                # completely silently (the exact "nothing happened, no
                # panel, no error" symptom this was built to fix), say
                # plainly, right in list_open_apps, that embedding
                # couldn't even find the window to embed, so the app is
                # simply running as its own separate window instead.
                rec["embed_note"] = (
                    "couldn't find its window to embed it into a panel, "
                    "so it's running as its own separate window")
        embedded = False
        if hwnd is not None and key in EMBEDDABLE_APPS:
            embedded = self._try_embed(key, rec, bounds, is_maximized)
        if hwnd is not None and not embedded and bounds is not None:
            # Chrome (never embeddable), or an embeddable app that fell
            # back to a plain separate window -- still honor the
            # *current* decided placement (re-read fresh here rather
            # than reusing the possibly-now-stale `bounds`/`is_maximized`
            # read at the very top of this method -- an explicit
            # maximize_app()/restore_app() call may have landed on
            # this same panel while the embed attempt above was still in
            # flight) by moving/resizing its real OS window directly,
            # the same mechanism maximize_panel already uses for this
            # exact case.
            with self._lock:
                live_bounds = rec.get("placement_bounds", bounds)
                live_is_maximized = rec.get("placement_is_maximized", is_maximized)
            if self._backend.is_supported():
                self._backend.move_resize(hwnd, *live_bounds)
                self._backend.bring_to_front(hwnd)
                rec["maximized"] = live_is_maximized

    def _try_embed(self, key, rec, bounds=None, is_maximized=False):
        """Attempts to build an EmbeddedAppPanel frame and reparent the
        real app's window into it. On any failure along the way (not
        Windows, the frame couldn't be built, SetParent itself failed,
        ...) tears down whatever was half-built and leaves `rec` as a
        normal, un-embedded panel instead -- open()/minimize()/etc.
        still work for it, it just behaves like Chrome from then on (a
        plain separate real window). Every failure path records *why*
        in rec["embed_note"] so it shows up in list_open_apps instead of
        failing in total silence -- the exact complaint that led here.
        `bounds`, if given, is where the unified panel-placement system
        (agent_tools.py) already decided this panel should open --
        passed straight into the frame's own constructor so it's right
        the first time, no separate move needed afterward.
        """
        if not self._backend.is_supported():
            rec["embed_note"] = ("isn't being embedded (panel embedding "
                                  "is Windows-only), so it's running as "
                                  "its own separate window")
            return False
        self._ensure_host()
        corner = sum(1 for r in self._panels.values() if r.get("frame") is not None)
        # Re-read the live decided placement one more time right before
        # actually building the frame, rather than trusting the
        # `bounds`/`is_maximized` this method was called with -- SetParent
        # reparenting below isn't instant, and an explicit maximize_app()
        # or restore_app() call may have landed on this very panel while
        # this whole embed attempt was still in flight. The frame must
        # open at wherever this panel is *currently* supposed to be, not
        # wherever it was when this background discovery thread started.
        with self._lock:
            bounds = rec.get("placement_bounds", bounds)
            is_maximized = rec.get("placement_is_maximized", is_maximized)
        try:
            frame = self._bridge.call(lambda: EmbeddedAppPanel(
                self._root, label=rec["label"],
                on_minimize=lambda k=key: self.minimize(k),
                on_close=lambda k=key: self.close(k),
                corner_index=corner, bounds=bounds))
        except Exception as exc:  # noqa: BLE001
            rec["embed_note"] = (f"couldn't build its panel frame ({exc}), "
                                  "so it's running as its own separate window")
            return False

        slot_hwnd = self._bridge.call(frame.slot_hwnd)
        width, height = self._bridge.call(frame.slot_size)
        try:
            if not slot_hwnd:
                ok, embed_reason = False, "its panel frame has no real window handle yet"
            else:
                ok, embed_reason = self._backend.embed(
                    slot_hwnd, rec["hwnd"], width or EmbeddedAppPanel.DEFAULT_W,
                    height or EmbeddedAppPanel.DEFAULT_H)
        except Exception as exc:  # noqa: BLE001
            ok, embed_reason = False, str(exc)
        if not ok:
            try:
                self._bridge.call(frame.destroy)
            except Exception:  # noqa: BLE001
                pass
            reason = f" ({embed_reason})" if embed_reason else ""
            rec["embed_note"] = (f"couldn't be embedded into its panel{reason}, "
                                  "so it's running as its own separate window")
            return False

        def _resize_cb(nw, nh, hwnd=rec["hwnd"]):
            self._backend.resize_embedded(hwnd, nw, nh)

        if bounds is not None:
            frame.is_maximized = is_maximized
        self._bridge.call(lambda: frame.set_resize_callback(_resize_cb))
        with self._lock:
            rec["frame"] = frame
            rec["embedded"] = True
            # One last re-read, right at the moment this commits, of
            # whatever this panel's placement currently actually is --
            # maximize_panel() (via an explicit maximize_app()/
            # restore_app() call) could have run (and won the race) at
            # literally any point during the possibly-slow embed() call
            # above, including after this method's own
            # earlier re-read but before this very line. If so, `bounds`/
            # `is_maximized` (and the frame, already built/positioned
            # with them) are stale -- physically correct it to the
            # latest decision instead of silently reverting it.
            live_bounds = rec.get("placement_bounds", bounds)
            live_is_maximized = rec.get("placement_is_maximized", is_maximized)
            if bounds is not None:
                rec["maximized"] = live_is_maximized
            already_minimized = rec.get("minimized")
        if live_bounds is not None and live_bounds != bounds:
            try:
                mover = frame.maximize_to if live_is_maximized else frame.move_to_slot
                self._bridge.call(lambda: mover(*live_bounds))
            except Exception:  # noqa: BLE001
                pass
        # Same retroactive fix as _open_custom_panel's: this frame
        # didn't exist yet when _decide_placement() first ran (and
        # possibly flagged it active), so apply that decision now.
        def activate_frame():
            frame.set_active_panel(live_is_maximized)
            if live_is_maximized:
                frame.set_friday_status(*self._current_friday_status())

        self._bridge.call(activate_frame)
        # A minimize() could have raced ahead and already happened on the
        # (until-now un-embedded) panel while embedding was still in
        # flight -- keep the freshly-built frame in sync with that
        # instead of popping it visibly open regardless.
        if already_minimized:
            self._bridge.call(frame.withdraw)
        else:
            self._bridge.call(frame.deiconify)
        return True

    # ---------------------------------------------------------------
    # Minimize / restore / close
    # ---------------------------------------------------------------
    def minimize(self, which):
        panels = self._live_panels()
        if (which or "").strip().lower() == "all":
            if not panels:
                return "No app panels are open to minimize."
            msgs = [self._minimize_one(k, r) for k, r in panels.items()
                    if not r.get("minimized")]
            return " ".join(msgs) if msgs else "Everything's already minimized."
        matches = self._match(which)
        if not matches:
            return (f"No open app panel matches '{which}'. Here's what's "
                     f"open:\n{self.list_panels()}")
        if len(matches) > 1:
            names = ", ".join(r["label"] for _, r in matches)
            return (f"More than one open panel matches '{which}': {names}. "
                     "Ask the user which one they mean before minimizing anything.")
        key, rec = matches[0]
        if rec.get("minimized"):
            return f"{rec['label']} is already minimized."
        return self._minimize_one(key, rec)

    def _minimize_one(self, key, rec):
        self._ensure_host()
        # Minimizing always implicitly clears the maximized flag, so a
        # later restore() -- which now always promotes straight back to
        # the one single active/maximized panel anyway, under the
        # current single-active-panel model -- doesn't have to special-
        # case coming back from an already-maximized state. No physical
        # move needed for this -- the panel is about to be
        # withdrawn/hidden entirely anyway.
        if rec.get("maximized"):
            rec["maximized"] = False
            rec["pre_maximize_bounds"] = None
        # Releases this panel's claim on being the one single active/
        # maximized panel (a different ledger than the pill-slot one
        # just below) -- a no-op unless it actually held that claim.
        self._release_panel_slot_for(key)
        if rec.get("embedded") and rec.get("frame") is not None:
            try:
                self._bridge.call(rec["frame"].withdraw)
            except Exception:  # noqa: BLE001
                pass
        elif rec.get("hwnd") is not None:
            self._backend.minimize(rec["hwnd"])
        origin = self._circle_bottom()
        if origin is None:
            rec["minimized"] = True
            return (f"{rec['label']} doesn't have Friday's circle to tuck "
                     "under right now, so it was just minimized normally.")
        cx, bottom_y = origin
        slot = self._pill_slot_for(key)
        slot_offset = slot * MinimizedPill.STACK_STEP
        pill = self._bridge.call(lambda: MinimizedPill(
            self._root, label=rec["label"], agent_host=self._agent_host,
            circle_bottom=(cx, bottom_y + slot_offset),
            on_restore=lambda k=key: self.restore(k)))
        rec["pill"] = pill
        rec["minimized"] = True
        # Apply whatever status was already recorded for this panel
        # (set_status() can be called whether or not it's minimized at
        # the time) rather than letting a freshly-built pill start out
        # looking like nothing is going on -- see set_status().
        status = rec.get("status", "normal")
        if status != "normal":
            try:
                self._bridge.call(lambda: pill.set_status(status))
            except Exception:  # noqa: BLE001
                pass
        return (f"Minimized {rec['label']} — it's tucked under the circle "
                "now, still running in the taskbar.")

    def _pill_slot_for(self, key):
        """0-based slot index for `key`'s pill in the single shared
        stack under the circle (IDE pill included) -- delegates to the
        agent_host when one is wired up (the normal case, shared with
        ide.py's own pills), falling back to a purely local
        count-of-already-minimized-panels scheme otherwise (e.g. a test
        harness with agent_host=None), same spirit as _circle_bottom's
        own agent_host-or-nothing fallback."""
        if self._agent_host is not None:
            try:
                return self._agent_host.get_pill_slot(key)
            except Exception:  # noqa: BLE001
                pass
        return sum(1 for r in self._panels.values() if r.get("pill") is not None)

    def _release_pill_slot_for(self, key):
        """Reverse of _pill_slot_for: releases `key`'s slot and reflows
        every other currently-minimized panel (and the IDE's own pill,
        when agent_host is wired up) up to close the resulting gap."""
        if self._agent_host is not None:
            try:
                reflow = self._agent_host.release_pill_slot(key)
            except Exception:  # noqa: BLE001
                return
            for other_key, idx in reflow:
                self._agent_host.reposition_pill(other_key, idx)
            return
        # No agent_host -- nothing to reflow against beyond this
        # manager's own panels, and without a shared slot ledger there's
        # no cheap way to know their indices changed, so just leave them
        # be (matches the pre-Task-43 behavior for this fallback path).

    def restore(self, which):
        panels = self._live_panels()
        if (which or "").strip().lower() == "all":
            # Not actually reachable through agent_tools.py's
            # restore_app("all") any more -- that's handled a level up
            # now, restoring only the single most-recently-minimized
            # panel (there's no "bring everything back" left to do once
            # at most one panel can ever be on screen at once -- see
            # restore_app's own docstring). Kept here, unmodified, as
            # the standalone/no-agent_host fallback and for direct unit
            # tests: a bulk restore in that case isn't subject to any
            # cap/eviction the way a single restore is -- everything
            # just comes back wherever it last was.
            msgs = [self._restore_one(k, r, assign_slot=False) for k, r in panels.items()
                    if r.get("minimized")]
            return " ".join(msgs) if msgs else "Nothing is minimized right now."
        matches = self._match(which)
        if not matches:
            return (f"No open app panel matches '{which}'. Here's what's "
                     f"open:\n{self.list_panels()}")
        if len(matches) > 1:
            names = ", ".join(r["label"] for _, r in matches)
            return (f"More than one open panel matches '{which}': {names}. "
                     "Ask the user which one they mean before restoring anything.")
        key, rec = matches[0]
        if not rec.get("minimized"):
            return f"{rec['label']} isn't minimized."
        return self._restore_one(key, rec)

    def _restore_one(self, key, rec, assign_slot=True):
        pill = rec.get("pill")
        if pill is not None and self._bridge is not None:
            try:
                self._bridge.call(pill.destroy)
            except Exception:  # noqa: BLE001
                pass
        rec["pill"] = None
        rec["minimized"] = False
        # Restoring now always promotes straight back to being Friday's
        # one single active/maximized panel (restore and maximize are
        # deliberately the same underlying action under the current
        # single-active-panel model -- see agent_tools.py's
        # maximize_app/restore_app), deciding exactly where that is
        # (and minimizing whoever else was active to make room) through
        # the same shared placement system a fresh open() uses --
        # unless assign_slot is False (a restore that's about to be
        # immediately promoted straight to maximized by maximize_app's
        # own next step anyway, so this step shouldn't also apply a
        # placement), in which case it just comes back wherever it last
        # physically was, untouched, and stays non-maximized.
        bounds, is_maximized, note = (
            self._decide_placement(key) if assign_slot else (None, False, ""))
        if rec.get("embedded") and rec.get("frame") is not None:
            try:
                self._bridge.call(rec["frame"].deiconify)
            except Exception:  # noqa: BLE001
                pass
            if bounds is not None:
                if is_maximized:
                    self.maximize_panel(key, bounds)
                else:
                    self.place_in_side_slot(key, bounds)
        elif rec.get("hwnd") is not None:
            self._backend.restore(rec["hwnd"])
            if bounds is not None and self._backend.is_supported():
                self._backend.move_resize(rec["hwnd"], *bounds)
                self._backend.bring_to_front(rec["hwnd"])
                rec["maximized"] = is_maximized
        self._release_pill_slot_for(key)
        return f"Restored {rec['label']}.{note}"

    def close(self, which):
        panels = self._live_panels()
        if (which or "").strip().lower() == "all":
            if not panels:
                return "No app panels are open to close."
            msgs = [self._close_one(k, r) for k, r in list(panels.items())]
            return " ".join(msgs)
        matches = self._match(which)
        if not matches:
            return (f"No open app panel matches '{which}'. Here's what's "
                     f"open:\n{self.list_panels()}")
        if len(matches) > 1:
            names = ", ".join(r["label"] for _, r in matches)
            return (f"More than one open panel matches '{which}': {names}. "
                     "Ask the user which one they mean before closing anything.")
        key, rec = matches[0]
        return self._close_one(key, rec)

    def _close_one(self, key, rec):
        # Releases this panel's claim on being the one single active/
        # maximized panel (safe no-op if it was already minimized --
        # minimizing already released it), same as minimizing does.
        self._release_panel_slot_for(key)
        # If this panel was minimized (a pill showing) when it got
        # closed, its slot in the *other* shared ledger -- the
        # minimized-pill stack -- also needs releasing, with everything
        # below it reflowed up a slot, exactly like a normal restore
        # would do. Without this, closing a minimized panel instead of
        # restoring it first left a permanent stale/ghost entry behind
        # in the shared pill stack forever (the key was never a live
        # panel again unless the same app got reopened later), which
        # could leave a visible gap in the pill stack under the circle
        # and threw off every other still-minimized panel's reported
        # slot index from then on.
        if rec.get("minimized"):
            self._release_pill_slot_for(key)
        self._destroy_widgets(rec)
        closed_gracefully = False
        if rec.get("hwnd") is not None:
            closed_gracefully = self._backend.close(rec["hwnd"])
        proc = rec.get("proc")
        if proc is not None and not closed_gracefully:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._panels.pop(key, None)
        return f"Closed {rec['label']}."

    # ---------------------------------------------------------------
    # Basic content control
    # ---------------------------------------------------------------
    def type_text(self, which, text):
        if (which or "").strip().lower() == "all":
            return "Say which app you want me to type into."
        matches = self._match(which)
        if not matches:
            return (f"No open app panel matches '{which}'. Here's what's "
                     f"open:\n{self.list_panels()}")
        if len(matches) > 1:
            names = ", ".join(r["label"] for _, r in matches)
            return (f"More than one open panel matches '{which}': {names}. "
                     "Ask the user which one they mean.")
        key, rec = matches[0]
        if key != "notepad" or not rec.get("custom") or rec.get("frame") is None:
            return (f"I can't type live into {rec['label']} yet — only "
                     "Notepad supports that right now.")
        try:
            self._bridge.call(lambda: rec["frame"].type_text_into_active(text))
            return f"Typed that into {rec['label']}."
        except Exception as exc:  # noqa: BLE001
            return f"Couldn't type into {rec['label']}: {exc}"

    def save_file(self, which, path=None):
        """Saves one of Friday's panels' real content to a real file on
        disk -- only Notepad supports this right now (it's Friday's own
        CustomNotepadPanel, writing a genuine file, not simulating
        anything). If `path` is omitted, the active tab's own
        already-known save path is reused (a plain Save), or otherwise
        a sensible default location/filename is chosen automatically --
        see CustomNotepadPanel.save_active_tab's own docstring.
        """
        matches = self._match(which)
        if not matches:
            return (f"No open app panel matches '{which}'. Here's what's "
                     f"open:\n{self.list_panels()}")
        if len(matches) > 1:
            names = ", ".join(r["label"] for _, r in matches)
            return (f"More than one open panel matches '{which}': {names}. "
                     "Ask the user which one they mean before saving anything.")
        key, rec = matches[0]
        if not rec.get("custom") or rec.get("frame") is None:
            return (f"{rec['label']} isn't something I can save to disk "
                     "directly yet — only Notepad supports that right now.")
        try:
            ok, result = self._bridge.call(lambda: rec["frame"].save_active_tab(path))
        except Exception as exc:  # noqa: BLE001
            return f"Couldn't save {rec['label']}: {exc}"
        if not ok:
            return f"Couldn't save {rec['label']}: {result}"
        return f"Saved {rec['label']}'s content to {result}."
