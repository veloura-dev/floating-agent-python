"""Four of Friday's own fully-native CustomTkinter panels -- Chat,
Profile, Image Generation, Video Generation -- with native Tk canvas
icons and file dialogs retained where they provide platform features.

These panels are deliberately *just the UI shell* for now -- an empty
content area plus the bottom
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
import customtkinter as ctk

_IDE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ide")
if _IDE_DIR not in sys.path:
    sys.path.insert(0, _IDE_DIR)
import ide as _ide_module  # noqa: E402
C = _ide_module.C
_ActiveGlowAnimator = _ide_module._ActiveGlowAnimator
_update_active_panel_glow = _ide_module._update_active_panel_glow
import panel_ui


# ---------------------------------------------------------------------------
# Hand-drawn icons -- small Canvas widgets, not font glyphs (see module
# docstring). Each one is a thin clickable button: hover highlight, a
# bound <Button-1>, and a `set_active(bool)` toggle used by the mic/
# speaker buttons' own pressed/active cosmetic state.
# ---------------------------------------------------------------------------

class _IconButton(tk.Canvas):
    SIZE = 28

    def __init__(self, parent, draw_fn, on_click=None, tooltip="", colors=None):
        self._colors = colors or C
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                          bg=self._colors["input"], highlightthickness=0, cursor="hand2")
        self._draw_fn = draw_fn
        self._on_click = on_click
        self._active = False
        self._tooltip = tooltip
        self._redraw()
        self.bind("<Enter>", lambda _e: self._set_bg(self._colors["hover"]))
        self.bind(
            "<Leave>",
            lambda _e: self._set_bg(
                self._colors["list_sel"] if self._active else self._colors["input"]))
        self.bind("<Button-1>", self._handle_click)

    def _set_bg(self, color):
        self.configure(bg=color)
        self._redraw(bg=color)

    def _redraw(self, bg=None):
        self.delete("all")
        self._draw_fn(self, self.SIZE, self._colors["fg"], bg or self.cget("bg"))

    def _handle_click(self, _event):
        if self._on_click:
            self._on_click()

    def set_active(self, active):
        """Cosmetic pressed/active toggle -- used by mic (listening) and
        speaker (unmuted) so clicking them gives real visual feedback
        even with no backend wired yet."""
        self._active = active
        self._set_bg(
            self._colors["list_sel"] if active else self._colors["input"])


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
    EMPTY_STATE_TITLE = "Nothing here yet"
    EMPTY_STATE_TEXT = ""
    EMPTY_STATE_HINT = ""
    ENTRY_PLACEHOLDER = "Type a message..."
    SUBMIT_NOTICE = "This panel is not connected yet. Your draft has not been sent."

    DEFAULT_W = panel_ui.DEFAULT_PANEL_W
    DEFAULT_H = panel_ui.DEFAULT_PANEL_H
    TITLEBAR_H = panel_ui.TITLEBAR_H
    BORDER_PX = panel_ui.BORDER_PX
    INPUT_BAR_H = 56

    def __init__(self, master, on_minimize, on_close, corner_index=0,
                 initial_content=None, bounds=None):
        super().__init__(master)
        self._colors = getattr(self, "COLORS", C)
        self.title(self.PANEL_TITLE)
        self.overrideredirect(True)
        self.configure(bg=self._colors["border_hi"])
        self.is_maximized = False
        self._on_close_cb = on_close
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

        bp = self.BORDER_PX
        self._build_titlebar(bp, on_minimize, on_close)
        self._build_input_bar(bp)
        self._build_body(bp)

    # -- titlebar: identical chrome/behavior to every other custom panel --
    def _build_titlebar(self, bp, on_minimize, on_close):
        panel_ui.build_titlebar(
            self, self._colors, self.PANEL_TITLE, on_minimize, on_close,
            self.TITLEBAR_H, bp)

    # -- empty body area, with room for a subclass to add its own extra
    #    content (e.g. Profile's placeholder avatar) above the message --
    def _build_body(self, bp):
        body = ctk.CTkFrame(self, fg_color=self._colors["panel"], corner_radius=0)
        body.pack(side="top", fill="both", expand=True, padx=bp)
        self._body = body
        self._build_body_extra(body)
        empty_state = ctk.CTkFrame(body, fg_color="transparent", corner_radius=0)
        empty_state.pack(expand=True, padx=28, pady=10)
        ctk.CTkLabel(
            empty_state, text="PREVIEW  ·  NOT CONNECTED",
            text_color=self._colors["warn"], font=("Segoe UI", 8, "bold"),
        ).pack(pady=(0, 8))
        ctk.CTkLabel(
            empty_state, text=self.EMPTY_STATE_TITLE,
            text_color=self._colors["fg"], font=("Segoe UI", 12, "bold"),
            wraplength=420, justify="center",
        ).pack(pady=(0, 6))
        ctk.CTkLabel(
            empty_state, text=self.EMPTY_STATE_TEXT,
            text_color=self._colors["fg_dim"], font=("Segoe UI", 9),
            wraplength=420, justify="center",
        ).pack()
        if self.EMPTY_STATE_HINT:
            ctk.CTkLabel(
                empty_state, text=self.EMPTY_STATE_HINT,
                text_color=self._colors["fg_faint"], font=("Segoe UI", 8),
                wraplength=420, justify="center",
            ).pack(pady=(8, 0))
        self._notice_label = ctk.CTkLabel(
            body, text="", text_color=self._colors["warn"],
            font=("Segoe UI", 8), wraplength=520, justify="center")

    def _build_body_extra(self, body):
        """Hook for a subclass to add panel-specific content above the
        empty-state message. No-op by default."""
        pass

    # -- the bottom input bar: attach (left) / text entry (middle,
    #    expands) / mic + speaker (right) -- exactly as requested --
    def _build_input_bar(self, bp):
        bar = ctk.CTkFrame(
            self, fg_color=self._colors.get("bg_main", self._colors["panel"]),
            height=self.INPUT_BAR_H, corner_radius=0)
        bar.pack(side="bottom", fill="x", padx=bp + 10, pady=(0, 10))
        bar.pack_propagate(False)

        inner = ctk.CTkFrame(
            bar, fg_color=self._colors["input"], border_width=1,
            border_color=self._colors["border"], corner_radius=10)
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
            tooltip="Attach a file", colors=self._colors)
        self._attach_btn.pack(side="left", padx=(8, 4), pady=8)

        right = ctk.CTkFrame(
            inner, fg_color=self._colors["input"], corner_radius=0)
        right.pack(side="right", padx=(4, 8), pady=8)
        self._mic_btn = _IconButton(right, _draw_mic, on_click=self._on_mic_click,
                                     tooltip="Voice input", colors=self._colors)
        self._mic_btn.pack(side="left", padx=(0, 6))
        self._speaker_btn = _IconButton(right, _draw_speaker, on_click=self._on_speaker_click,
                                         tooltip="Read replies aloud",
                                         colors=self._colors)
        self._speaker_btn.pack(side="left")

        self.entry = ctk.CTkEntry(
            inner, fg_color=self._colors["input"],
            text_color=self._colors["fg"],
            placeholder_text=None, border_width=0,
            font=("Segoe UI", 11), corner_radius=6)
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
        self.entry.configure(text_color=self._colors["fg_faint"])
        self.entry.delete(0, "end")
        self.entry.insert(0, self._placeholder)
        self._showing_placeholder = True

    def _clear_placeholder(self, _event=None):
        if getattr(self, "_showing_placeholder", False):
            self.entry.delete(0, "end")
            self.entry.configure(text_color=self._colors["fg"])
            self._showing_placeholder = False

    def _maybe_restore_placeholder(self, _event=None):
        if not self.entry.get().strip():
            self._show_placeholder()

    def _on_entry_submit(self, _event=None):
        """Keep the user's draft and state plainly that no backend ran."""
        if getattr(self, "_showing_placeholder", False):
            return "break"
        self._show_notice(self.SUBMIT_NOTICE)
        return "break"

    def _show_notice(self, message):
        self._notice_label.configure(text=message)
        if not self._notice_label.winfo_manager():
            self._notice_label.pack(side="bottom", fill="x", padx=18, pady=(0, 10))

    # -- attach: a real OS file picker, shown as a small chip once chosen --
    def _on_attach_click(self):
        path = filedialog.askopenfilename(parent=self, title="Attach a file")
        if not path:
            return
        self._attached_path = path
        self._show_attach_chip(os.path.basename(path))

    def _show_attach_chip(self, filename):
        self._hide_attach_chip()
        chip = ctk.CTkFrame(
            self._body, fg_color=self._colors["list_sel"], corner_radius=8)
        ctk.CTkLabel(
            chip, text=filename, text_color=self._colors["fg"],
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(8, 4), pady=4)
        remove = ctk.CTkButton(
            chip, text="\u2715", command=self._clear_attachment,
            fg_color="transparent", hover_color=self._colors["hover"],
            text_color=self._colors["fg_dim"], font=("Segoe UI", 8),
            width=24, height=24, corner_radius=6)
        remove.pack(side="left", padx=(0, 3), pady=2)
        chip.place(relx=0.0, rely=1.0, anchor="sw", x=4, y=-4)
        self._attach_chip = chip

    def _hide_attach_chip(self):
        if self._attach_chip is not None:
            self._attach_chip.destroy()
            self._attach_chip = None

    def _clear_attachment(self):
        self._attached_path = None
        self._hide_attach_chip()

    # -- keep controls honest until this panel has voice backends --
    def _on_mic_click(self):
        self._show_notice("Voice input is not connected to this panel.")

    def _on_speaker_click(self):
        self._show_notice("Spoken replies are not connected to this panel.")

    # -- active-panel glow + maximize/restore, same contract every other
    #    custom panel already implements (AppPanelManager calls these) --
    def set_active_panel(self, is_active):
        self._is_active_panel = bool(is_active)
        _update_active_panel_glow(self)

    def set_friday_status(self, state, is_error=False):
        self._friday_glow_state = state
        self._friday_glow_is_error = bool(is_error)
        _update_active_panel_glow(self)

    def restore_default_geometry(self):
        x, y, w, h = self._default_geometry
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.is_maximized = False


class ChatPanel(_TextBoxPanel):
    """Friday's chat panel styled to the Quiet CustomTkinter demo while keeping
    the native Friday panel chrome and panel-manager contract intact."""
    PANEL_TITLE = "Chat"
    COLORS = dict(
        C,
        outside="#101012",
        background="#151517",
        sidebar="#1B1B1E",
        surface="#222225",
        input="#1E1E21",
        bubble="#28282D",
        selected="#2A2A2F",
        hover="#303035",
        border="#35353B",
        border_soft="#29292E",
        focus="#626169",
        text="#E7E6E3",
        body="#CCCBCF",
        secondary="#B2B1B8",
        muted="#909098",
        accent="#C7C3BC",
        accent_hover="#DAD6D0",
        accent_text="#29282B",
        bg_main="#0F0F11",
        panel="#1A1A1F",
        border_hi="#2E2E36",
        tabbar="#1A1A1F",
        fg="#F2F2F3",
        fg_dim="#8B8B99",
        fg_faint="#777783",
        accent_btn="#303036",
        danger="#F0525C",
    )
    EMPTY_STATE_TITLE = "A calmer workday"
    EMPTY_STATE_TEXT = "Your space, without the noise."
    EMPTY_STATE_HINT = ""
    ENTRY_PLACEHOLDER = "Write a message..."
    SUBMIT_NOTICE = (
        "Chat is not connected here. Your message stays here as a local draft; "
        "nothing was sent.")

    INPUT_BAR_H = 120

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.conversations = [
            {
                "id": "quiet-1",
                "title": "A calmer workday",
                "messages": [
                    {"role": "assistant", "content": "Hey. What’s on your mind?"},
                    {"role": "user", "content": "Help me make my day feel a little less busy."},
                    {"role": "assistant", "content": "## Let’s keep it simple.\n\n"
                                                    "1. Choose one thing that really matters.\n"
                                                    "2. Make space for a proper break.\n"
                                                    "3. Leave a little room for the unexpected.\n\n"
                                                    "You don’t have to do everything to have a good day."},
                ],
            },
            {
                "id": "quiet-2",
                "title": "A few words, made simpler",
                "messages": [
                    {"role": "user", "content": "Help me write a clearer introduction."},
                    {"role": "assistant", "content": "Start with what you mean.\n\n"
                                                    "One honest sentence is often better than a complicated paragraph. "
                                                    "What’s the main thing you want your reader to know?"},
                ],
            },
            {
                "id": "quiet-3",
                "title": "Something worth making",
                "messages": [
                    {"role": "assistant", "content": "Big ideas can start small.\n\n"
                                                    "What’s something you’d enjoy making, even just for yourself?"},
                ],
            },
        ]
        self.active_id = "quiet-1"
        self._drafts = {}
        self._draft_attachments = []
        self._render_sidebar()
        self._render_chat()

    @property
    def current(self):
        return next((conv for conv in self.conversations if conv["id"] == self.active_id), self.conversations[0])

    def _build_body(self, bp):
        body = ctk.CTkFrame(self, fg_color=self.COLORS["bg_main"], corner_radius=0)
        body.pack(side="top", fill="both", expand=True, padx=bp, pady=(0, 4))
        self._body = body

        shell = ctk.CTkFrame(
            body, fg_color=self.COLORS["background"],
            border_width=1, border_color=self.COLORS["border_soft"],
            corner_radius=22)
        shell.pack(fill="both", expand=True, padx=10, pady=10)
        shell.grid_columnconfigure(1, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(shell, width=250, fg_color=self.COLORS["sidebar"], corner_radius=15)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(12, 0), pady=10)
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent", corner_radius=0)
        brand.grid(row=0, column=0, sticky="w", padx=18, pady=(18, 8))
        brand.grid_columnconfigure(1, weight=1)
        mark = ctk.CTkFrame(brand, width=36, height=36, fg_color=self.COLORS["surface"], corner_radius=10)
        mark.grid(row=0, column=0, sticky="w")
        mark.grid_propagate(False)
        ctk.CTkLabel(mark, text="✦", text_color=self.COLORS["fg"], font=("Segoe UI", 16, "bold")).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(brand, text="quiet", text_color=self.COLORS["fg"], font=("Segoe UI", 32, "bold")).grid(row=0, column=1, sticky="w", padx=(10, 0))
        ctk.CTkLabel(sidebar, text="A little room to think.", text_color=self.COLORS["fg_dim"], font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 14))

        add_btn = ctk.CTkButton(
            sidebar, text="＋ New conversation",
            fg_color="transparent", text_color=self.COLORS["fg"], hover_color=self.COLORS["hover"],
            border_width=1, border_color=self.COLORS["border"], corner_radius=10,
            height=42, width=180, font=("Segoe UI", 11), command=self._new_conversation)
        add_btn.grid(row=2, column=0, padx=14, pady=(0, 12), sticky="ew")

        ctk.CTkLabel(sidebar, text="CONVERSATIONS", text_color=self.COLORS["fg_faint"], font=("Segoe UI", 9, "bold")).grid(row=3, column=0, sticky="w", padx=18, pady=(4, 10))

        self._sidebar_list = ctk.CTkFrame(sidebar, fg_color="transparent")
        self._sidebar_list.grid(row=4, column=0, sticky="nsew", padx=(10, 10), pady=(0, 12))
        self._sidebar_list.grid_columnconfigure(0, weight=1)

        main = ctk.CTkFrame(shell, fg_color="transparent", corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew", padx=(18, 18), pady=(10, 0))
        main.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(10, 8))
        header.grid_columnconfigure(0, weight=1)

        self._title_label = ctk.CTkLabel(
            header, text="A calmer workday", text_color=self.COLORS["fg"],
            font=("Segoe UI", 28, "bold"), anchor="w")
        self._title_label.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header, text="Your space, without the noise.",
            text_color=self.COLORS["fg_dim"], font=("Segoe UI", 15), anchor="w"
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self._status_badge = ctk.CTkLabel(
            header, text="•  Local demo", text_color=self.COLORS["secondary"],
            fg_color=self.COLORS["surface"], corner_radius=11, height=26,
            font=("Segoe UI", 10))
        self._status_badge.grid(row=0, column=1, sticky="e", padx=(10, 0))

        ctk.CTkFrame(main, fg_color=self.COLORS["border_soft"], height=1).grid(
            row=1, column=0, sticky="ew", pady=(12, 0))

        self.chat = ctk.CTkScrollableFrame(
            main, fg_color="transparent", corner_radius=0,
            scrollbar_fg_color=self.COLORS["background"],
            scrollbar_button_color=self.COLORS["border_soft"],
            scrollbar_button_hover_color=self.COLORS["border"])
        self.chat.grid(row=2, column=0, sticky="nsew", pady=(12, 4))
        self.chat.grid_columnconfigure(0, weight=1)

        self._notice_label = ctk.CTkLabel(
            body, text="", text_color=self.COLORS["fg_dim"],
            font=("Segoe UI", 9), wraplength=420, justify="center")

    def _render_sidebar(self):
        for child in self._sidebar_list.winfo_children():
            child.destroy()
        for idx, conversation in enumerate(self.conversations):
            selected = conversation["id"] == self.active_id
            row = ctk.CTkButton(
                self._sidebar_list, text=conversation["title"],
                fg_color=self.COLORS["selected"] if selected else "transparent",
                hover_color=self.COLORS["hover"],
                text_color=self.COLORS["fg"] if selected else self.COLORS["secondary"],
                corner_radius=10, height=34, anchor="w",
                border_width=0, font=("Segoe UI", 11),
                command=lambda cid=conversation["id"]: self._switch_conversation(cid))
            row.grid(row=idx, column=0, sticky="ew", pady=(0, 8))

    def _render_chat(self):
        for child in self.chat.winfo_children():
            child.destroy()

        conversation = next((conv for conv in self.conversations if conv["id"] == self.active_id), self.conversations[0])
        self._title_label.configure(text=conversation["title"])

        if not conversation["messages"]:
            empty = ctk.CTkFrame(self.chat, fg_color="transparent")
            empty.grid(row=0, column=0, sticky="nsew", padx=40, pady=18)
            mark = ctk.CTkFrame(empty, width=54, height=54, fg_color=self.COLORS["surface"], corner_radius=18)
            mark.pack(pady=(0, 10))
            mark.pack_propagate(False)
            ctk.CTkLabel(mark, text="✦", text_color=self.COLORS["fg"], font=("Segoe UI", 20, "bold")).place(relx=0.5, rely=0.5, anchor="center")
            ctk.CTkLabel(empty, text="A little room to think.", text_color=self.COLORS["fg"], font=("Segoe UI", 38, "bold"), justify="center").pack()
            ctk.CTkLabel(empty, text="A quiet place for questions, ideas, and everything in between.", text_color=self.COLORS["fg_dim"], font=("Segoe UI", 14), justify="center").pack(pady=(8, 20))

            row = ctk.CTkFrame(empty, fg_color="transparent")
            row.pack(pady=(10, 0))
            prompts = [("Plan my day", "Plan my day"), ("Draft something", "Draft something"), ("Explore an idea", "Explore an idea")]
            for idx, (label, prompt) in enumerate(prompts):
                btn = ctk.CTkButton(row, text=label, width=150, height=36, corner_radius=18,
                                    fg_color="transparent", hover_color=self.COLORS["hover"],
                                    border_width=1, border_color=self.COLORS["border"],
                                    text_color=self.COLORS["secondary"],
                                    font=("Segoe UI", 11), command=lambda p=prompt: self._apply_prompt(p))
                btn.grid(row=0, column=idx, padx=(0, 8 if idx < 2 else 0))
            return

        for index, message in enumerate(conversation["messages"]):
            bubble = ctk.CTkFrame(self.chat, fg_color=self.COLORS["bubble"], corner_radius=16)
            bubble.grid(row=index, column=0, padx=(12 if message["role"] == "assistant" else 50), pady=(0, 10), sticky="ew")
            label = ctk.CTkLabel(bubble, text=message["content"], text_color=self.COLORS["fg"], font=("Segoe UI", 12), justify="left", wraplength=350)
            label.grid(row=0, column=0, padx=14, pady=12, sticky="ew")
            if message["role"] == "user":
                bubble.configure(fg_color="#2A2B30")

        self.chat._parent_canvas.yview_moveto(1.0)

    def _apply_prompt(self, prompt):
        if hasattr(self, "entry") and self.entry is not None:
            if isinstance(self.entry, ctk.CTkTextbox):
                self.entry.delete("1.0", "end")
                self.entry.insert("1.0", prompt)
            else:
                self.entry.delete(0, "end")
                self.entry.insert(0, prompt)
            self.entry.focus_set()

    def _switch_conversation(self, conversation_id):
        self.active_id = conversation_id
        self._render_sidebar()
        self._render_chat()

    def _new_conversation(self):
        new_conversation = {
            "id": f"quiet-{len(self.conversations) + 1}",
            "title": "New conversation",
            "messages": [],
        }
        self.conversations.insert(0, new_conversation)
        self.active_id = new_conversation["id"]
        self._render_sidebar()
        self._render_chat()

    def _show_notice(self, message):
        self._notice_label.configure(text=message)
        self._notice_label.place(relx=0.5, rely=1.0, anchor="s", y=-3)

    def _on_entry_submit(self, _event=None):
        if getattr(self, "_showing_placeholder", False):
            return "break"

        text = self.entry.get("1.0", "end-1c").strip() if isinstance(self.entry, ctk.CTkTextbox) else self.entry.get().strip()
        if not text:
            return "break"

        conversation = next((conv for conv in self.conversations if conv["id"] == self.active_id), self.conversations[0])
        conversation["messages"].append({"role": "user", "content": text})
        if isinstance(self.entry, ctk.CTkTextbox):
            self.entry.delete("1.0", "end")
        else:
            self.entry.delete(0, "end")
        self._render_chat()
        reply = self._demo_reply(text, conversation["messages"])
        conversation["messages"].append({"role": "assistant", "content": reply})
        self._render_chat()
        self._show_notice("Reply loaded locally.")
        return "break"

    def _demo_reply(self, text, history):
        lower = text.lower()
        if any(word in lower for word in ("plan", "day", "busy", "focus")):
            return ("## A little less, done well.\n\n"
                    "Choose one priority. Give it a small, realistic block of time. "
                    "Then leave some breathing room.\n\n"
                    "What’s the one thing you’d feel good about finishing today?")
        if any(word in lower for word in ("write", "draft", "words", "introduction")):
            return ("## Start with one clear sentence.\n\n"
                    "Write what you mean, as if you were explaining it to a friend. "
                    "We can make it shorter and smoother from there.\n\n"
                    "Who are you writing for?")
        if any(word in lower for word in ("idea", "create", "make", "explore")):
            return ("## Give the idea a little room.\n\n"
                    "What would it help someone do? Start with the smallest version "
                    "that could be useful, and build from there.")
        if lower.strip() in {"hi", "hello", "hey"} or lower.startswith("hi ") or lower.startswith("hello ") or lower.startswith("hey "):
            return "Hey. Good to have you here.\n\nWhat would you like to work on?"
        return ("Your message is here in your space.\n\n"
                "These are sample replies, not a live AI model. Connect a real responder "
                "if you want this panel to send beyond the local demo.")

    def _build_input_bar(self, bp):
        bar = ctk.CTkFrame(self, fg_color=self.COLORS["bg_main"], height=self.INPUT_BAR_H, corner_radius=0)
        bar.pack(side="bottom", fill="x", padx=bp + 8, pady=(0, 10))
        bar.pack_propagate(False)

        composer = ctk.CTkFrame(bar, fg_color=self.COLORS["input"], border_width=1, border_color=self.COLORS["border"], corner_radius=16)
        composer.pack(fill="both", expand=True)
        self._composer_frame = composer

        toolbar = ctk.CTkFrame(composer, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        toolbar.grid_columnconfigure(0, weight=1)

        self.entry = ctk.CTkTextbox(toolbar, height=48, fg_color="transparent", corner_radius=0,
                                   border_width=0, border_spacing=0, activate_scrollbars=False,
                                   font=("Segoe UI", 14), text_color=self.COLORS["text"], wrap="word")
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 0), pady=(8, 0))
        self.entry._textbox.configure(insertbackground=self.COLORS["text"], insertwidth=1,
                                     selectbackground=self.COLORS["border"], selectforeground=self.COLORS["text"])

        self.placeholder = ctk.CTkLabel(toolbar, text="Write a message...", font=("Segoe UI", 14),
                                        text_color=self.COLORS["muted"], fg_color=self.COLORS["input"], height=23)
        self.placeholder.place(x=4, y=16)
        self.placeholder.bind("<Button-1>", lambda _event: self.entry.focus_set())

        self.entry.bind("<Return>", self._on_entry_submit, add="+")
        self.entry.bind("<KP_Enter>", self._on_entry_submit, add="+")
        self.entry.bind("<<Modified>>", self._on_modified, add="+")
        self.entry.bind("<FocusIn>", lambda _event: composer.configure(border_color=self.COLORS["focus"]), add="+")
        self.entry.bind("<FocusOut>", lambda _event: composer.configure(border_color=self.COLORS["border"]), add="+")

        footer = ctk.CTkFrame(composer, fg_color="transparent")
        footer.grid(row=1, column=0, sticky="ew", padx=(12, 12), pady=(4, 12))
        footer.grid_columnconfigure(1, weight=1)

        self._attach_btn = ctk.CTkButton(footer, text="Attach file", text_color=self.COLORS["secondary"],
                                         fg_color="transparent", hover_color=self.COLORS["hover"],
                                         anchor="w", height=30, corner_radius=8, font=("Segoe UI", 11),
                                         command=self._on_attach_click)
        self._attach_btn.grid(row=0, column=0, sticky="w")

        self._mic_btn = _IconButton(footer, _draw_mic, on_click=self._on_mic_click, tooltip="Voice input", colors=self.COLORS)
        self._mic_btn.grid(row=0, column=2, padx=(0, 6), sticky="e")
        self._speaker_btn = _IconButton(footer, _draw_speaker, on_click=self._on_speaker_click, tooltip="Read replies aloud", colors=self.COLORS)
        self._speaker_btn.grid(row=0, column=3, sticky="e")

        self._send_btn = ctk.CTkButton(footer, text="", width=35, height=35, corner_radius=11,
                                       image=None, fg_color=self.COLORS["accent"], hover_color=self.COLORS["accent_hover"],
                                       command=self._on_entry_submit)
        self._send_btn.grid(row=0, column=4, sticky="e", padx=(8, 0))
        self._send_btn.configure(text="↑")

        self._attached_path = None
        self._attach_chip = None
        self._showing_placeholder = True
        self.entry.bind("<FocusIn>", self._clear_placeholder, add="+")
        self.entry.bind("<FocusOut>", self._maybe_restore_placeholder, add="+")

    def _on_modified(self, _event=None):
        value = self.entry.get("1.0", "end-1c")
        if value.strip():
            self.placeholder.place_forget()
            self._showing_placeholder = False
        else:
            self.placeholder.place(x=4, y=16)
            self._showing_placeholder = True

    def _clear_placeholder(self, _event=None):
        if getattr(self, "_showing_placeholder", False):
            self.entry.delete("1.0", "end")
            self._showing_placeholder = False
            self.placeholder.place_forget()

    def _maybe_restore_placeholder(self, _event=None):
        if not self.entry.get("1.0", "end-1c").strip():
            self._showing_placeholder = True
            self.placeholder.place(x=4, y=16)

    def _show_attach_chip(self, filename):
        self._hide_attach_chip()
        chip = ctk.CTkFrame(self._body, fg_color=self.COLORS["surface"], corner_radius=8)
        chip.place(relx=0.0, rely=1.0, anchor="sw", x=16, y=-90)
        ctk.CTkLabel(chip, text=filename, text_color=self.COLORS["fg"], font=("Segoe UI", 10)).pack(side="left", padx=(8, 4), pady=4)
        remove = ctk.CTkButton(chip, text="×", command=self._clear_attachment, fg_color="transparent",
                              hover_color=self.COLORS["hover"], text_color=self.COLORS["fg_dim"],
                              font=("Segoe UI", 9), width=24, height=24, corner_radius=6)
        remove.pack(side="left", padx=(0, 3), pady=2)
        self._attach_chip = chip

    def _hide_attach_chip(self):
        if self._attach_chip is not None:
            self._attach_chip.destroy()
            self._attach_chip = None

    def _clear_attachment(self):
        self._attached_path = None
        self._hide_attach_chip()

    def _on_attach_click(self):
        path = filedialog.askopenfilename(parent=self, title="Attach a file")
        if not path:
            return
        self._attached_path = path
        self._show_attach_chip(os.path.basename(path))

    def _on_mic_click(self):
        self._show_notice("Voice input is not connected to this panel.")

    def _on_speaker_click(self):
        self._show_notice("Spoken replies are not connected to this panel.")


class ProfilePanel(_TextBoxPanel):
    """A profile panel with a placeholder avatar and the same bottom
    input bar as the others (e.g. for asking Friday to update profile
    info by typing/voice later) -- no real profile data wired up yet."""
    PANEL_TITLE = "Profile"
    EMPTY_STATE_TITLE = "Your profile"
    EMPTY_STATE_TEXT = (
        "Profile editing is not connected to Friday's saved memory yet.")
    EMPTY_STATE_HINT = "Nothing entered here will be stored."
    ENTRY_PLACEHOLDER = "Profile editing is not available yet..."
    SUBMIT_NOTICE = (
        "Profile storage is not connected. Your text remains here and was "
        "not saved.")

    def _build_body_extra(self, body):
        avatar = tk.Canvas(body, width=48, height=48, bg=C["panel"],
                            highlightthickness=0)
        avatar.pack(pady=(8, 0))
        avatar.create_oval(2, 2, 46, 46, fill=C["list_sel"], outline="")
        avatar.create_oval(17, 10, 31, 24, fill=C["fg_bright"], outline="")
        avatar.create_arc(9, 27, 39, 57, start=0, extent=180,
                           fill=C["fg_bright"], outline="", style="chord")


class ImageGenPanel(_TextBoxPanel):
    """Image Generation panel -- UI shell only. Matches
    settings_store.py's own honest labeling: Image Generation has no
    real generation call wiring in Friday yet, so this is deliberately
    just the surface, not a fake generated image."""
    PANEL_TITLE = "Image Generation"
    EMPTY_STATE_TITLE = "Image generation is not connected"
    EMPTY_STATE_TEXT = (
        "No image provider is available in Friday yet, so prompts cannot be "
        "submitted and no image will be generated.")
    EMPTY_STATE_HINT = (
        "Connect a supported image-generation provider to enable this panel.")
    ENTRY_PLACEHOLDER = "Draft an image prompt (generation unavailable)..."
    SUBMIT_NOTICE = (
        "Image generation is not connected. Your prompt remains as a draft; "
        "nothing was generated.")


class VideoGenPanel(_TextBoxPanel):
    """Video Generation panel -- UI shell only, same honest-scaffolding
    status as ImageGenPanel above."""
    PANEL_TITLE = "Video Generation"
    EMPTY_STATE_TITLE = "Video generation is not connected"
    EMPTY_STATE_TEXT = (
        "No video provider is available in Friday yet, so prompts cannot be "
        "submitted and no video will be generated.")
    EMPTY_STATE_HINT = (
        "Connect a supported video-generation provider to enable this panel.")
    ENTRY_PLACEHOLDER = "Draft a video prompt (generation unavailable)..."
    SUBMIT_NOTICE = (
        "Video generation is not connected. Your prompt remains as a draft; "
        "nothing was generated.")
