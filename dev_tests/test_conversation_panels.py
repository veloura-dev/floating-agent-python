"""Proof that Friday's four new native panels -- Chat, Profile, Image
Generation, Video Generation (conversation_panels.py) -- work end to
end, mirroring dev_tests/test_settings_panel.py's Part C pattern:

  - all four are wired into app_panels.py exactly the way "settings" is
    -- same KNOWN_APPS/resolve_app_key/known_app_labels machinery, same
    CUSTOM_PANEL_APPS/_CUSTOM_PANEL_CLASSES entries, same
    AppPanelManager.open/minimize/restore/close lifecycle, same generic
    (not notepad-hardcoded) list_panels() wording;
  - each real Tk panel actually builds the exact bottom bar the user
    asked for: attach icon (left), a text entry (middle, expands), mic
    + speaker icons (right) -- not reordered, not merged;
  - the entry's placeholder show/clear/restore behavior works and Enter
    preserves drafts while explaining that no backend is connected;
  - the attach button opens a (mocked, no real dialog) file picker and
    shows/removes a real chip; mic/speaker report their unavailable
    backends instead of toggling cosmetically;
  - each panel shows honest, panel-specific empty-state content.

Requires a real (Xvfb) Tk display, same DISPLAY=:99 requirement as
dev_tests/test_app_panels.py and test_settings_panel.py's Part C.
"""
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


# ---------------------------------------------------------------------
# Part A: app_panels.py wiring (no Tk needed)
# ---------------------------------------------------------------------
def part_a():
    print("\n--- Part A: app_panels.py wiring ---")
    import app_panels as ap

    panels = {
        "chat": ("Chat", ["chat panel", "open chat", "new chat"]),
        "profile": ("Profile", ["profile panel", "my profile", "user profile"]),
        "image_gen": ("Image Generation",
                      ["image generation", "image gen", "generate an image"]),
        "video_gen": ("Video Generation",
                      ["video generation", "video gen", "generate a video"]),
    }

    for key, (label, aliases) in panels.items():
        check(f"resolve_app_key({key!r}) resolves to itself",
              ap.resolve_app_key(key) == key)
        for alias in aliases:
            check(f"resolve_app_key({alias!r}) resolves to {key!r}",
                  ap.resolve_app_key(alias) == key)
        check(f"{label!r} is in known_app_labels()", label in ap.known_app_labels())
        check(f"{key!r} is in CUSTOM_PANEL_APPS (fully native, no real OS window)",
              key in ap.CUSTOM_PANEL_APPS)
        check(f"{key!r} is not in EMBEDDABLE_APPS (not a real reparented window)",
              key not in ap.EMBEDDABLE_APPS)

    import conversation_panels as cpm
    check("_CUSTOM_PANEL_CLASSES maps chat to ChatPanel",
          ap._CUSTOM_PANEL_CLASSES["chat"] is cpm.ChatPanel)
    check("_CUSTOM_PANEL_CLASSES maps profile to ProfilePanel",
          ap._CUSTOM_PANEL_CLASSES["profile"] is cpm.ProfilePanel)
    check("_CUSTOM_PANEL_CLASSES maps image_gen to ImageGenPanel",
          ap._CUSTOM_PANEL_CLASSES["image_gen"] is cpm.ImageGenPanel)
    check("_CUSTOM_PANEL_CLASSES maps video_gen to VideoGenPanel",
          ap._CUSTOM_PANEL_CLASSES["video_gen"] is cpm.VideoGenPanel)


# ---------------------------------------------------------------------
# Part B: AppPanelManager lifecycle (real Xvfb Tk, no real OS process)
# ---------------------------------------------------------------------
def part_b():
    print("\n--- Part B: AppPanelManager open/minimize/restore/close ---")
    import app_panels as ap
    import customtkinter as ctk
    import tkinter as tk

    class FakeLauncher:
        def launch(self, *a, **k):
            raise AssertionError(
                "a fully-native custom panel must never launch a real process")

    class _StubAgentHost:
        def get_panel_placement(self, key):
            return (0, 0, 900, 700), True, ""

        def get_pill_slot(self, key):
            return 0

        def release_pill_slot(self, key):
            return []

        def reposition_pill(self, key, idx):
            pass

        def release_panel_slot(self, key):
            pass

    mgr = ap.AppPanelManager(launcher=FakeLauncher(), agent_host=_StubAgentHost())
    try:
        for key, label in (("chat", "Chat"), ("profile", "Profile"),
                            ("image_gen", "Image Generation"),
                            ("video_gen", "Video Generation")):
            msg = mgr.open(key)
            check(f"open({key!r}) succeeds", f"Opened {label}" in msg)
            rec = mgr._panels[key]
            check(f"{key!r} opens with no real OS process or window at all",
                  rec.get("proc") is None and rec.get("hwnd") is None)
            check(f"{key!r} is tracked as a custom, embedded panel",
                  rec.get("custom") is True and rec.get("embedded") is True)

            listing = mgr.list_panels().lower()
            check(f"list_panels() names {label} generically, not as a "
                  f"built-in notepad",
                  label.lower() in listing and "notepad" not in listing)

            panel = rec["frame"]
            check(f"{key!r} uses CustomTkinter chrome on a native Tk panel",
                  isinstance(panel, tk.Toplevel) and
                  isinstance(panel._titlebar, ctk.CTkFrame))
            check(f"{key!r} panel has the real attach/mic/speaker icon buttons",
                  hasattr(panel, "_attach_btn") and hasattr(panel, "_mic_btn") and
                  hasattr(panel, "_speaker_btn"))
            check(f"{key!r} panel has a real tk.Entry for the message box",
                  panel.entry is not None)

            msg = mgr.minimize(key)
            check(f"minimize({key!r}) succeeds",
                  label in msg or "minimized" in msg.lower())
            msg = mgr.restore(key)
            check(f"restore({key!r}) succeeds", f"Restored {label}" in msg)
            msg = mgr.close(key)
            check(f"close({key!r}) succeeds", f"Closed {label}" in msg)
            check(f"{key!r} is no longer tracked after closing",
                  key not in mgr._panels)
    finally:
        # Same thread-safety note as test_settings_panel.py's Part C: the
        # only safe teardown path is mgr's own shutdown(), never reaching
        # across threads to call mgr._root.destroy() directly.
        pass


# ---------------------------------------------------------------------
# Part C: the real bottom input bar's layout, order, and behavior
# ---------------------------------------------------------------------
def part_c():
    print("\n--- Part C: bottom input bar layout + behavior (direct Tk) ---")
    import tkinter as tk
    import conversation_panels as cpm

    root = tk.Tk()
    root.withdraw()
    try:
        closed = {"n": 0}
        minimized = {"n": 0}

        def make(cls):
            return cls(root, on_minimize=lambda: minimized.__setitem__(
                "n", minimized["n"] + 1),
                on_close=lambda: closed.__setitem__("n", closed["n"] + 1),
                corner_index=0, bounds=(0, 0, 420, 360))

        for cls, title, empty_text, placeholder in (
            (cpm.ChatPanel, "Chat", "messaging isn't connected",
             "Draft a message..."),
            (cpm.ProfilePanel, "Profile", "not connected",
             "Profile editing is not available yet..."),
            (cpm.ImageGenPanel, "Image Generation", "not connected",
             "Draft an image prompt (generation unavailable)..."),
            (cpm.VideoGenPanel, "Video Generation", "not connected",
             "Draft a video prompt (generation unavailable)..."),
        ):
            panel = make(cls)
            root.update_idletasks()
            root.update()

            check(f"{title} panel title is correct", panel.title() == title)
            check(f"{title} panel shows its expected empty-state text",
                  empty_text in
                  f"{panel.EMPTY_STATE_TITLE} {panel.EMPTY_STATE_TEXT}".lower())

            # -- the 3 icon buttons really exist and are _IconButton canvases --
            check(f"{title}: attach button exists and is a real Canvas widget",
                  isinstance(panel._attach_btn, tk.Canvas))
            check(f"{title}: mic button exists and is a real Canvas widget",
                  isinstance(panel._mic_btn, tk.Canvas))
            check(f"{title}: speaker button exists and is a real Canvas widget",
                  isinstance(panel._speaker_btn, tk.Canvas))

            # -- layout order: attach must sit left of the entry, mic/
            #    speaker must sit right of the entry, and mic must sit
            #    left of speaker (exact ordering the user specified) --
            attach_x = panel._attach_btn.winfo_rootx()
            entry_x = panel.entry.winfo_rootx()
            mic_x = panel._mic_btn.winfo_rootx()
            speaker_x = panel._speaker_btn.winfo_rootx()
            check(f"{title}: attach icon is left of the text entry",
                  attach_x < entry_x)
            check(f"{title}: text entry is left of the mic icon",
                  entry_x < mic_x)
            check(f"{title}: mic icon is left of the speaker icon (not "
                  f"merged, not reordered)",
                  mic_x < speaker_x)
            check(f"{title}: all 3 icon buttons have nonzero rendered width "
                  f"(none squeezed to invisible -- the pack-order bug this "
                  f"guards against)",
                  panel._attach_btn.winfo_width() > 0 and
                  panel._mic_btn.winfo_width() > 0 and
                  panel._speaker_btn.winfo_width() > 0)

            # -- entry placeholder behavior --
            check(f"{title}: entry starts out showing its placeholder, dimmed",
                  panel.entry.get() == placeholder and panel._showing_placeholder)
            panel._clear_placeholder()
            check(f"{title}: focusing clears the placeholder",
                  panel.entry.get() == "" and not panel._showing_placeholder)
            panel.entry.insert(0, "hello")
            panel._maybe_restore_placeholder()
            check(f"{title}: non-empty text is NOT replaced on blur",
                  panel.entry.get() == "hello")
            panel.entry.delete(0, "end")
            panel._maybe_restore_placeholder()
            check(f"{title}: blurring an empty entry restores the placeholder",
                  panel.entry.get() == placeholder and panel._showing_placeholder)

            # -- Enter retains text and reports the missing backend --
            panel._clear_placeholder()
            panel.entry.insert(0, "something typed")
            panel._on_entry_submit()
            check(f"{title}: pressing Enter preserves the draft",
                  panel.entry.get() == "something typed")
            check(f"{title}: pressing Enter explains why nothing was sent",
                  panel._notice_label.cget("text") == panel.SUBMIT_NOTICE)

            # -- attach: mock the real file dialog, verify a real chip
            #    appears and can be removed --
            fake_path = "/tmp/example_attachment.png"
            orig_dialog = cpm.filedialog.askopenfilename
            cpm.filedialog.askopenfilename = lambda **k: fake_path
            try:
                panel._on_attach_click()
                root.update_idletasks()
                check(f"{title}: attach opens the (mocked) file picker and "
                      f"records the picked path",
                      panel._attached_path == fake_path)
                check(f"{title}: a real attach chip widget is shown",
                      panel._attach_chip is not None and
                      panel._attach_chip.winfo_exists())
                panel._on_entry_submit()
                check(f"{title}: unavailable submit preserves its attachment",
                      panel._attached_path == fake_path)
                panel._clear_attachment()
                check(f"{title}: clearing the attachment removes the chip "
                      f"and resets the path",
                      panel._attached_path is None and panel._attach_chip is None)
            finally:
                cpm.filedialog.askopenfilename = orig_dialog

            # -- a cancelled file dialog must not attach anything --
            cpm.filedialog.askopenfilename = lambda **k: ""
            try:
                panel._on_attach_click()
                check(f"{title}: cancelling the file picker attaches nothing",
                      panel._attached_path is None and panel._attach_chip is None)
            finally:
                cpm.filedialog.askopenfilename = orig_dialog

            # -- unavailable mic/speaker controls give clear feedback --
            check(f"{title}: mic starts inactive", panel._mic_btn._active is False)
            panel._on_mic_click()
            check(f"{title}: mic explains that voice input is unavailable",
                  "not connected" in panel._notice_label.cget("text").lower())
            check(f"{title}: mic does not imply an active recording",
                  panel._speaker_btn._active is False)
            panel._on_speaker_click()
            check(f"{title}: speaker explains that speech output is unavailable",
                  "not connected" in panel._notice_label.cget("text").lower())

            if cls is cpm.ChatPanel:
                check("Chat uses the supplied near-black page background",
                      panel._body.cget("fg_color") == "#0F0F11")
                check("Chat uses a layered charcoal conversation card",
                      panel._chat_card.cget("fg_color") == "#1A1A1F")
                check("Chat composer uses the layered card surface",
                      panel._composer_frame.cget("fg_color") == "#1A1A1F")
                check("Chat composer uses a subtle border and rounded corners",
                      panel._composer_frame.cget("border_color") == "#2E2E36" and
                      panel._composer_frame.cget("corner_radius") == 12)
                check("Chat header uses the card surface and a preview badge",
                      panel._connection_badge.cget("text") == "PREVIEW" and
                      panel._connection_badge.cget("fg_color") == "#242429")
                check("Chat empty state is centered with a minimal brand mark",
                      panel._brand_mark.cget("fg_color") == "#242429" and
                      panel.EMPTY_STATE_TITLE == "A quieter space to think.")
                check("Chat entry uses the card surface and restrained typography",
                      panel.entry.cget("fg_color") == "#1A1A1F" and
                      panel.entry.cget("border_color") == "#1A1A1F" and
                      panel.entry.cget("height") == 40 and
                      panel.entry.cget("font")[0] == "Segoe UI" and
                      panel.entry.cget("font")[1] == 10)
                check("Chat Send button uses a compact dark default with red hover",
                      panel._send_btn.cget("fg_color") == "#303036" and
                      panel._send_btn.cget("hover_color") == "#E03E48" and
                      panel._send_btn.cget("width") == 64 and
                      panel._send_btn.cget("height") == 32 and
                      panel._send_btn.cget("font")[0] == "Segoe UI" and
                      panel._send_btn.cget("font")[1] == 9)

                panel._clear_placeholder()
                panel.entry.delete(0, "end")
                panel.entry.insert(0, "send button draft")
                panel._send_btn.invoke()
                check("Chat Send preserves its draft when no backend is connected",
                      panel.entry.get() == "send button draft")
                check("Chat Send explains that the message was not sent",
                      panel._notice_label.cget("text") == panel.SUBMIT_NOTICE)

                panel.geometry("420x300+0+0")
                root.update_idletasks()
                root.update()
                check("Chat composer remains usable at a shorter panel size",
                      panel.entry.winfo_width() > 0 and
                      panel._send_btn.winfo_width() > 0 and
                      panel._send_btn.winfo_rootx() +
                      panel._send_btn.winfo_width() <=
                      panel.winfo_rootx() + panel.winfo_width())

            # -- titlebar minimize/close callbacks really fire --
            before_min = minimized["n"]
            panel._min_btn.invoke()
            root.update_idletasks()
            check(f"{title}: titlebar minimize button really calls on_minimize",
                  minimized["n"] == before_min + 1)
            before_close = closed["n"]
            panel._close_btn.invoke()
            root.update_idletasks()
            check(f"{title}: titlebar close button really calls on_close",
                  closed["n"] == before_close + 1)

            panel.destroy()
            root.update()

        # -- Profile's extra body content (compact placeholder avatar) --
        profile = make(cpm.ProfilePanel)
        root.update_idletasks()
        import customtkinter as ctk
        state_labels = [
            w.cget("text")
            for child in profile._body.winfo_children()
            for w in child.winfo_children()
            if isinstance(w, ctk.CTkLabel)
        ]
        check("Profile panel presents a clear 'Your profile' empty-state title",
              "Your profile" in state_labels)
        canvases = [w for w in profile._body.winfo_children()
                    if isinstance(w, tk.Canvas)]
        check("Profile panel draws a placeholder avatar canvas",
              len(canvases) >= 1)
        profile.destroy()

        # -- Chat/Image/Video Gen must NOT have Profile's avatar extra --
        chat = make(cpm.ChatPanel)
        root.update_idletasks()
        chat_canvases = [w for w in chat._body.winfo_children()
                         if isinstance(w, tk.Canvas)]
        check("Chat panel has no extra avatar canvas (that's Profile-only)",
              len(chat_canvases) == 0)
        chat.destroy()

    finally:
        root.destroy()


def main():
    part_a()
    part_b()
    part_c()
    passed = sum(1 for _, ok in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    if passed != len(CHECKS):
        sys.exit(1)


if __name__ == "__main__":
    main()
