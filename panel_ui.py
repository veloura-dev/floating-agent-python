"""Shared visual helpers for Friday's native CustomTkinter panels."""
import tkinter as tk
import customtkinter as ctk


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


DEFAULT_PANEL_W = 258
DEFAULT_PANEL_H = 124
TITLEBAR_H = 30
PANEL_MARGIN = 24
BORDER_PX = 2


def corner_position(master, index, width, height):
    """Place a standalone panel in a predictable screen corner."""
    try:
        screen_width = master.winfo_screenwidth()
        screen_height = master.winfo_screenheight()
    except tk.TclError:
        screen_width, screen_height = 1920, 1080
    margin = PANEL_MARGIN
    corners = (
        (margin, margin),
        (max(0, screen_width - width - margin), margin),
        (margin, max(0, screen_height - height - margin)),
        (max(0, screen_width - width - margin),
         max(0, screen_height - height - margin)),
    )
    return corners[index % len(corners)]


def build_titlebar(panel, colors, title, on_minimize, on_close,
                   height, border_px):
    titlebar = ctk.CTkFrame(
        panel, fg_color=colors["tabbar"], corner_radius=0, height=height)
    titlebar.pack(side="top", fill="x", padx=border_px, pady=(border_px, 0))
    titlebar.pack_propagate(False)

    accent = ctk.CTkFrame(
        titlebar, fg_color=colors["accent"], corner_radius=0, width=3)
    accent.pack(side="left", fill="y")
    ctk.CTkLabel(
        titlebar, text=title, text_color=colors["fg"],
        font=("Segoe UI", 9, "bold"),
    ).pack(side="left", padx=(9, 8))

    buttons = ctk.CTkFrame(
        titlebar, fg_color=colors["tabbar"], corner_radius=0)
    buttons.pack(side="right", fill="y")
    min_btn = ctk.CTkButton(
        buttons, text="\u2500", command=on_minimize, width=38, height=height,
        fg_color="transparent", hover_color=colors["hover"],
        text_color=colors["fg_dim"], font=("Segoe UI", 10),
        corner_radius=0, border_spacing=0)
    min_btn.pack(side="left", fill="y")
    close_btn = ctk.CTkButton(
        buttons, text="\u2715", command=on_close, width=38, height=height,
        fg_color="transparent", hover_color=colors["danger"],
        text_color=colors["fg_dim"], font=("Segoe UI", 10),
        corner_radius=0, border_spacing=0)
    close_btn.pack(side="left", fill="y")

    panel._drag = {"x": 0, "y": 0}

    def _start_drag(event):
        panel._drag["x"], panel._drag["y"] = event.x, event.y

    def _do_drag(event):
        x = panel.winfo_pointerx() - panel._drag["x"]
        y = panel.winfo_pointery() - panel._drag["y"]
        panel.geometry(f"+{x}+{y}")

    titlebar.bind("<Button-1>", _start_drag)
    titlebar.bind("<B1-Motion>", _do_drag)
    panel._titlebar = titlebar
    panel._min_btn = min_btn
    panel._close_btn = close_btn
    return titlebar


def style_button(button, colors, kind="secondary"):
    """Apply consistent flat button styling while preserving its command."""
    if kind == "primary":
        background, foreground = colors["accent"], "#ffffff"
    elif kind == "danger":
        background, foreground = colors["hover"], colors["danger"]
    else:
        background, foreground = colors["hover"], colors["fg"]

    button.configure(
        fg_color=background,
        text_color=foreground,
        hover_color=colors["accent_hover"] if kind == "secondary" else background,
        border_color=colors["border"],
        border_width=1,
        corner_radius=8,
        font=("Segoe UI", 9, "bold" if kind == "primary" else "normal"),
    )
    return button
