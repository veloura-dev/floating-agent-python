"""Four of Friday's own fully-native panels -- Chat, Profile, Image
Generation, Video Generation -- built the exact same way Notepad/
Settings are (see notepad_panel.py's own docstring for the full
rationale: no real OS process, no foreign window, nothing for a
ctypes/SetParent bug to ever touch, just Friday's own Tkinter widgets
dressed up to look and behave like a real panel).

Per the user's explicit framing for this task: these are deliberately
*just the UI shell* for now -- an empty content area plus the bottom
input bar -- not yet wired to any real chat/profile/image/video
backend. Same honest-scaffolding spirit as Image/Video Generation's
empty faculties in settings_store.py: the surface is real, genuinely
interactive (hover/click feedback, a real file picker on Attach), but
nothing here fabricates a reply or a generation that doesn't exist.

All four share one base class, _TextBoxPanel, since the only thing
that actually differs between them is a title, an accent-free empty-
state message, and (optionally) a little extra body content (Profile's
placeholder avatar). Icons (attach/mic/speaker) are hand-drawn on a
small Canvas rather than relying on color-emoji glyphs -- the exact
same lesson ide.py's ChatSidePanel._you_avatar_badge already documents
("some systems/fonts have no color-emoji glyph installed and silently
draw an empty box instead") -- so they render identically everywhere,
with no font-dependent guesswork.
"""

import os
import sys
import tkinter as tk
from tkinter import filedialog

from app_panels import EmbeddedAppPanel  # noqa: E402 -- see notepad_panel.py's
# own matching comment for why this resolves fine despite the circular
# import: app_panels.py only imports *this* file after EmbeddedAppPanel
# is already fully defined.

_IDE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ide")
if _IDE_DIR not in sys.path:
    sys.path.insert(0, _IDE_DIR)
import ide as _ide_module  # noqa: E402
C = _ide_module.C
_ActiveGlowAnimator = _ide_module._ActiveGlowAnimator


# ---------------------------------------------------------------------------
# Hand-drawn icons -- small Canvas widgets, not font glyphs (see module
# docstring). Each one is a thin clickable button: hover highlight, a
# bound <Button-1>, and a `set_active(bool)` toggle used by the mic/
# speaker buttons' own pressed/active cosmetic state.
# ---------------------------------------------------------------------------

class _IconButton(tk.Canvas):
    SIZE = 28

    def __init__(self, parent, draw_fn, on_click=None, tooltip=""):
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                          bg=C["input"], highlightthickness=0, cursor="hand2")
        self._draw_fn = draw_fn
        self._on_click = on_click
        self._active = False
        self._tooltip = tooltip
        self._redraw()
        self.bind("<Enter>", lambda _e: self._set_bg(C["hover"]))
        self.bind("<Leave>", lambda _e: self._set_bg(C["list_sel"] if self._active else C["input"]))
        self.bind("<Button-1>", self._handle_click)

    def _set_bg(self, color):
        self.configure(bg=color)
        self._redraw(bg=color)

    def _redraw(self, bg=None):
        self.delete("all")
        self._draw_fn(self, self.SIZE, C["fg"], bg or self.cget("bg"))

    def _handle_click(self, _event):
        if self._on_click:
            self._on_click()

    def set_active(self, active):
        """Cosmetic pressed/active toggle -- used by mic (listening) and
        speaker (unmuted) so clicking them gives real visual feedback
        even with no backend wired yet."""
        self._active = active
        self._set_bg(C["list_sel"] if active else C["input"])


def _draw_attach(cv, size, fg, bg):
    """A simple paperclip silhouette: one smoothed zig-zag line, thick
    enough to read clearly at icon size."""
    pts = [size * 0.64, size * 0.18,
           size * 0.32, size * 0.18,
           size * 0.22, size * 0.32,
           size * 0.30, size * 0.46,
           size * 0.62, size * 0.46,
           size * 0.70, size * 0.60,
           size * 0.60, size * 0.76,
           size * 0.36, size * 0.76]
    cv.create_line(*pts, smooth=True, width=max(2, size // 10), fill=fg,
                    capstyle="round", joinstyle="round")


def _draw_mic(cv, size, fg, bg):
    """A microphone glyph built from solid filled shapes (a capsule
    "stadium" head, a cradle arc, a stem and base) rather than thin
    multi-arc outlines -- at icon sizes this small (28px), a handful of
    sub-3px-radius arcs blur into an unrecognizable blob (confirmed by
    screenshot during development: the original outline version read
    as a plain "0"), while a solid filled silhouette stays legible."""
    w = max(2, size // 9)
    cx = size * 0.5
    top_y, bot_y, r = size * 0.16, size * 0.52, size * 0.13
    cv.create_oval(cx - r, top_y - r, cx + r, top_y + r, fill=fg, outline=fg)
    cv.create_oval(cx - r, bot_y - r, cx + r, bot_y + r, fill=fg, outline=fg)
    cv.create_rectangle(cx - r, top_y, cx + r, bot_y, fill=fg, outline=fg)
    cv.create_arc(cx - r * 2.3, bot_y - r * 0.5, cx + r * 2.3, bot_y + r * 2.3,
                  start=200, extent=140, style="arc", outline=fg, width=w)
    stem_top = bot_y + r * 1.8
    cv.create_line(cx, stem_top, cx, size * 0.86, fill=fg, width=w)
    cv.create_line(cx - size * 0.15, size * 0.86, cx + size * 0.15, size * 0.86,
                    fill=fg, width=w)


def _draw_speaker(cv, size, fg, bg):
    """A speaker cone plus two volume arcs."""
    w = max(2, size // 11)
    cv.create_rectangle(size * 0.16, size * 0.38, size * 0.32, size * 0.62,
                         outline=fg, fill=fg)
    cv.create_polygon(size * 0.32, size * 0.38, size * 0.50, size * 0.22,
                       size * 0.50, size * 0.78, size * 0.32, size * 0.62,
                       outline=fg, fill=fg)
    cv.create_arc(size * 0.54, size * 0.32, size * 0.72, size * 0.68,
                  start=-55, extent=110, style="arc", outline=fg, width=w)
    cv.create_arc(size * 0.60, size * 0.20, size * 0.84, size * 0.80,
                  start=-55, extent=110, style="arc", outline=fg, width=w)


class _TextBoxPanel(tk.Toplevel):
    """Shared base for Chat/Profile/Image Generation/Video Generation:
    identical titlebar/drag/minimize/close chrome as CustomNotepadPanel/
    SettingsPanel, an empty body area with a short placeholder message,
    and the bottom input bar the user asked for -- attach icon (left),
    a text entry (middle, expands), mic + speaker icons (right).

    Every subclass just sets PANEL_TITLE/EMPTY_STATE_TEXT/ENTRY_PLACEHOLDER
    and, if it wants one, overrides `_build_body_extra` for a little
    panel-specific content above the empty-state message (see
    ProfilePanel below). The constructor signature matches every other
    _CUSTOM_PANEL_CLASSES entry exactly, so app_panels.py's
    _open_custom_panel dispatches to all of them identically.
    """

    PANEL_TITLE = "Panel"
    EMPTY_STATE_TEXT = "Nothing here yet."
    ENTRY_PLACEHOLDER = "Type a message..."

    DEFAULT_W = EmbeddedAppPanel.DEFAULT_W
    DEFAULT_H = EmbeddedAppPanel.DEFAULT_H
    TITLEBAR_H = EmbeddedAppPanel.TITLEBAR_H
    BORDER_PX = EmbeddedAppPanel.BORDER_PX
    INPUT_BAR_H = 56

    def __init__(self, master, on_minimize, on_close, corner_index=0,
                 initial_content=None, bounds=None):
        super().__init__(master)
        self.title(self.PANEL_TITLE)
        self.overrideredirect(True)
        self.configure(bg=C["panel"])
        self.is_maximized = False
        self._on_close_cb = on_close
        self._is_active_panel = False
        self._active_glow = _ActiveGlowAnimator(self, lambda c: self.configure(bg=c))

        if bounds is not None:
            x, y, w, h = bounds
        else:
            w, h = self.DEFAULT_W, self.DEFAULT_H
            x, y = EmbeddedAppPanel._corner_position(master, corner_index, w, h)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self._default_geometry = (x, y, w, h)

        bp = self.BORDER_PX
        self._build_titlebar(bp, on_minimize, on_close)
        self._build_body(bp)
        self._build_input_bar(bp)

    # -- titlebar: identical chrome/behavior to every other custom panel --
    def _build_titlebar(self, bp, on_minimize, on_close):
        titlebar = tk.Frame(self, bg=C["tabbar"], height=self.TITLEBAR_H)
        titlebar.pack(side="top", fill="x", padx=bp, pady=(bp, 0))
        titlebar.pack_propagate(False)
        tk.Label(titlebar, text=self.PANEL_TITLE, bg=C["tabbar"], fg=C["fg"],
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
        close_btn.bind(
            "<Enter>", lambda _e: close_btn.configure(bg=C["danger"], fg="#ffffff"))
        close_btn.bind(
            "<Leave>", lambda _e: close_btn.configure(bg=C["tabbar"], fg=C["fg_dim"]))
        close_btn.bind("<Button-1>", lambda _e: on_close())
        self._min_btn, self._close_btn = min_btn, close_btn

        self._drag = {"x": 0, "y": 0}

        def _start_drag(e):
            self._drag["x"], self._drag["y"] = e.x, e.y

        def _do_drag(e):
            nx = self.winfo_pointerx() - self._drag["x"]
            ny = self.winfo_pointery() - self._drag["y"]
            self.geometry(f"+{nx}+{ny}")

        titlebar.bind("<Button-1>", _start_drag)
        titlebar.bind("<B1-Motion>", _do_drag)
        self._titlebar = titlebar

    # -- empty body area, with room for a subclass to add its own extra
    #    content (e.g. Profile's placeholder avatar) above the message --
    def _build_body(self, bp):
        body = tk.Frame(self, bg=C["panel"])
        body.pack(side="top", fill="both", expand=True, padx=bp)
        self._body = body
        self._build_body_extra(body)
        tk.Label(body, text=self.EMPTY_STATE_TEXT, bg=C["panel"],
                 fg=C["fg_dim"], font=("Segoe UI", 10), wraplength=360,
                 justify="center").pack(expand=True)

    def _build_body_extra(self, body):
        """Hook for a subclass to add panel-specific content above the
        empty-state message. No-op by default."""
        pass

    # -- the bottom input bar: attach (left) / text entry (middle,
    #    expands) / mic + speaker (right) -- exactly as requested --
    def _build_input_bar(self, bp):
        bar = tk.Frame(self, bg=C["panel"], height=self.INPUT_BAR_H)
        bar.pack(side="bottom", fill="x", padx=bp + 10, pady=(0, 10))
        bar.pack_propagate(False)

        inner = tk.Frame(bar, bg=C["input"], highlightthickness=1,
                          highlightbackground=C["border"])
        inner.pack(fill="x", expand=True, pady=10)

        # Packing order matters here, not just visual side= -- Tk's
        # packer hands each widget whatever's left of the cavity *at
        # the moment it's packed*, so every fixed-size widget (attach,
        # and the whole mic+speaker cluster) has to be packed before
        # the expanding entry, regardless of attach being visually
        # leftmost -- otherwise the entry's expand=True greedily claims
        # the entire remaining cavity immediately, leaving nothing for
        # whatever's packed after it (this is exactly what happened the
        # first time: mic/speaker were being packed last and silently
        # squeezed out to zero width).
        self._attach_btn = _IconButton(
            inner, _draw_attach, on_click=self._on_attach_click,
            tooltip="Attach a file")
        self._attach_btn.pack(side="left", padx=(8, 4), pady=8)

        right = tk.Frame(inner, bg=C["input"])
        right.pack(side="right", padx=(4, 8), pady=8)
        self._mic_btn = _IconButton(right, _draw_mic, on_click=self._on_mic_click,
                                     tooltip="Voice input")
        self._mic_btn.pack(side="left", padx=(0, 6))
        self._speaker_btn = _IconButton(right, _draw_speaker, on_click=self._on_speaker_click,
                                         tooltip="Read replies aloud")
        self._speaker_btn.pack(side="left")

        self.entry = tk.Entry(inner, bg=C["input"], fg=C["fg"], relief="flat",
                               insertbackground=C["fg"], highlightthickness=0,
                               font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True, padx=6, ipady=6)
        self._placeholder = self.ENTRY_PLACEHOLDER
        self._show_placeholder()
        self.entry.bind("<FocusIn>", self._clear_placeholder)
        self.entry.bind("<FocusOut>", self._maybe_restore_placeholder)
        self.entry.bind("<Return>", self._on_entry_submit)

        self._attached_path = None
        self._attach_chip = None  # small "filename.png \u2715" label, shown
        # above the input bar once a file is actually picked -- built
        # lazily in _on_attach_click so a panel that never uses Attach
        # never pays for it.

    # -- entry placeholder handling (same pattern as ide.py's ChatSidePanel) --
    def _show_placeholder(self):
        self.entry.configure(fg=C["fg_faint"])
        self.entry.delete(0, "end")
        self.entry.insert(0, self._placeholder)
        self._showing_placeholder = True

    def _clear_placeholder(self, _event=None):
        if getattr(self, "_showing_placeholder", False):
            self.entry.delete(0, "end")
            self.entry.configure(fg=C["fg"])
            self._showing_placeholder = False

    def _maybe_restore_placeholder(self, _event=None):
        if not self.entry.get().strip():
            self._show_placeholder()

    def _on_entry_submit(self, _event=None):
        """No backend is wired up yet (see module docstring) -- typing
        and pressing Enter just clears the box back to its placeholder
        rather than pretending to send/generate something that doesn't
        exist. Real wiring plugs in here once there's somewhere for
        this text to actually go."""
        if getattr(self, "_showing_placeholder", False):
            return
        self.entry.delete(0, "end")
        self._show_placeholder()
        self._attached_path = None
        self._hide_attach_chip()

    # -- attach: a real OS file picker, shown as a small chip once chosen --
    def _on_attach_click(self):
        path = filedialog.askopenfilename(parent=self, title="Attach a file")
        if not path:
            return
        self._attached_path = path
        self._show_attach_chip(os.path.basename(path))

    def _show_attach_chip(self, filename):
        self._hide_attach_chip()
        chip = tk.Frame(self._body, bg=C["list_sel"])
        tk.Label(chip, text=f"\U0001F4CE {filename}", bg=C["list_sel"], fg=C["fg"],
                 font=("Segoe UI", 8), padx=6, pady=2).pack(side="left")
        remove = tk.Label(chip, text="\u2715", bg=C["list_sel"], fg=C["fg_dim"],
                           font=("Segoe UI", 8), padx=4, cursor="hand2")
        remove.pack(side="left")
        remove.bind("<Button-1>", lambda _e: self._clear_attachment())
        chip.place(relx=0.0, rely=1.0, anchor="sw", x=4, y=-4)
        self._attach_chip = chip

    def _hide_attach_chip(self):
        if self._attach_chip is not None:
            self._attach_chip.destroy()
            self._attach_chip = None

    def _clear_attachment(self):
        self._attached_path = None
        self._hide_attach_chip()

    # -- mic/speaker: cosmetic pressed-state toggles, no STT/TTS wired yet --
    def _on_mic_click(self):
        self._mic_btn.set_active(not self._mic_btn._active)

    def _on_speaker_click(self):
        self._speaker_btn.set_active(not self._speaker_btn._active)

    # -- active-panel glow + maximize/restore, same contract every other
    #    custom panel already implements (AppPanelManager calls these) --
    def set_active_panel(self, is_active):
        self._is_active_panel = is_active
        if is_active:
            self._active_glow.start()
        else:
            self._active_glow.stop()
            self.configure(bg=C["panel"])

    def restore_default_geometry(self):
        x, y, w, h = self._default_geometry
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.is_maximized = False


class ChatPanel(_TextBoxPanel):
    """Friday's standalone Chat panel -- a plain conversational surface
    distinct from the IDE's own embedded 'Friday AI Chat' side panel
    (ide.py's ChatSidePanel) and from the floating circle's own voice/
    typed chat. Just the empty shell + input bar for now (see module
    docstring) -- no message log wired up yet."""
    PANEL_TITLE = "Chat"
    EMPTY_STATE_TEXT = "No messages yet \u2014 start typing below."
    ENTRY_PLACEHOLDER = "Type a message..."


class ProfilePanel(_TextBoxPanel):
    """A profile panel with a placeholder avatar and the same bottom
    input bar as the others (e.g. for asking Friday to update profile
    info by typing/voice later) -- no real profile data wired up yet."""
    PANEL_TITLE = "Profile"
    EMPTY_STATE_TEXT = "No profile info yet."
    ENTRY_PLACEHOLDER = "Tell Friday something about yourself..."

    def _build_body_extra(self, body):
        avatar = tk.Canvas(body, width=64, height=64, bg=C["panel"],
                            highlightthickness=0)
        avatar.pack(pady=(24, 4))
        avatar.create_oval(2, 2, 62, 62, fill=C["list_sel"], outline="")
        avatar.create_oval(22, 14, 42, 34, fill=C["fg_bright"], outline="")
        avatar.create_arc(10, 36, 54, 80, start=0, extent=180,
                           fill=C["fg_bright"], outline="", style="chord")
        tk.Label(body, text="You", bg=C["panel"], fg=C["fg"],
                 font=("Segoe UI", 11, "bold")).pack(pady=(0, 16))


class ImageGenPanel(_TextBoxPanel):
    """Image Generation panel -- UI shell only. Matches
    settings_store.py's own honest labeling: Image Generation has no
    real generation call wiring in Friday yet, so this is deliberately
    just the surface, not a fake generated image."""
    PANEL_TITLE = "Image Generation"
    EMPTY_STATE_TEXT = (
        "Describe the image you want below.\n"
        "(Image generation isn't wired up to a real model yet.)")
    ENTRY_PLACEHOLDER = "Describe the image you want to generate..."


class VideoGenPanel(_TextBoxPanel):
    """Video Generation panel -- UI shell only, same honest-scaffolding
    status as ImageGenPanel above."""
    PANEL_TITLE = "Video Generation"
    EMPTY_STATE_TEXT = (
        "Describe the video you want below.\n"
        "(Video generation isn't wired up to a real model yet.)")
    ENTRY_PLACEHOLDER = "Describe the video you want to generate..."
