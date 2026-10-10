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
  - the entry's placeholder show/clear/restore behavior works;
  - the attach button opens a (mocked, no real dialog) file picker and
    shows/removes a real chip; mic/speaker are cosmetic toggles only;
  - Profile's extra placeholder-avatar body content renders; Image/
    Video Generation show their honest "not wired up to a real model
    yet" empty-state text.

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
            (cpm.ChatPanel, "Chat", "No messages yet", "Type a message..."),
            (cpm.ProfilePanel, "Profile", "No profile info yet.",
             "Tell Friday something about yourself..."),
            (cpm.ImageGenPanel, "Image Generation",
             "isn't wired up to a real model yet",
             "Describe the image you want to generate..."),
            (cpm.VideoGenPanel, "Video Generation",
             "isn't wired up to a real model yet",
             "Describe the video you want to generate..."),
        ):
            panel = make(cls)
            root.update_idletasks()
            root.update()

            check(f"{title} panel title is correct", panel.title() == title)
            check(f"{title} panel shows its expected empty-state text",
                  empty_text in panel.EMPTY_STATE_TEXT)

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

            # -- Enter just resets, never fabricates a reply/generation --
            panel._clear_placeholder()
            panel.entry.insert(0, "something typed")
            panel._on_entry_submit()
            check(f"{title}: pressing Enter resets the box back to its "
                  f"placeholder (no fake reply/generation is fabricated)",
                  panel.entry.get() == placeholder)

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

            # -- mic/speaker: cosmetic toggle only, independent of each other --
            check(f"{title}: mic starts inactive", panel._mic_btn._active is False)
            panel._on_mic_click()
            check(f"{title}: clicking mic toggles it active",
                  panel._mic_btn._active is True)
            check(f"{title}: speaker is unaffected by the mic toggle",
                  panel._speaker_btn._active is False)
            panel._on_speaker_click()
            check(f"{title}: clicking speaker toggles it active independently",
                  panel._speaker_btn._active is True)

            # -- titlebar minimize/close callbacks really fire --
            before_min = minimized["n"]
            panel._min_btn.event_generate("<Button-1>")
            root.update_idletasks()
            check(f"{title}: titlebar minimize button really calls on_minimize",
                  minimized["n"] == before_min + 1)
            before_close = closed["n"]
            panel._close_btn.event_generate("<Button-1>")
            root.update_idletasks()
            check(f"{title}: titlebar close button really calls on_close",
                  closed["n"] == before_close + 1)

            panel.destroy()

        # -- Profile's extra body content (placeholder avatar + "You" label) --
        profile = make(cpm.ProfilePanel)
        root.update_idletasks()
        labels = [w.cget("text") for w in profile._body.winfo_children()
                  if w.winfo_class() == "Label"]
        check("Profile panel shows a 'You' label above the empty-state message",
              "You" in labels)
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
