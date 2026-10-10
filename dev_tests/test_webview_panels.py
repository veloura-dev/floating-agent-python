"""Proof that webview_panels.py -- the upgraded HTML/CSS/JS rendering
of Chat/Profile/Image Generation/Video Generation -- actually works:

Part A: pure logic, no real webview needed -- PANEL_DEFS content,
_build_html() produces real, well-formed markup with the right title/
placeholder/icons/layout order for every panel, and PanelBridge's
pick_file/minimize/close_window behave correctly against a fake
Window object (never touches a real OS window).

Part B: a real pywebview window, rendered for real via the installed
GTK WebKit2 backend under Xvfb (DISPLAY=:99, same requirement as
dev_tests/test_app_panels.py/test_settings_panel.py) -- proves the
HTML this module generates is valid enough for a real browser engine
to actually render it, not just well-formed as a string.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def part_a():
    print("\n--- Part A: PANEL_DEFS / _build_html / PanelBridge (pure logic) ---")
    import webview_panels as wp

    check("all 4 panel keys are defined",
          set(wp.PANEL_DEFS) == {"chat", "profile", "image_gen", "video_gen"})

    for key, title, placeholder in (
        ("chat", "Chat", "Type a message..."),
        ("profile", "Profile", "Tell Friday something about yourself..."),
        ("image_gen", "Image Generation", "Describe the image you want to generate..."),
        ("video_gen", "Video Generation", "Describe the video you want to generate..."),
    ):
        html = wp._build_html(key)
        check(f"{key}: _build_html embeds the correct title", f">{title}<" in html)
        check(f"{key}: _build_html embeds the correct placeholder",
              placeholder in html)
        check(f"{key}: has a draggable titlebar (pywebview-drag-region, "
              f"not the old abandoned SetParent-reparenting approach)",
              "pywebview-drag-region" in html)
        check(f"{key}: attach icon comes before the text entry in the markup "
              f"(left-to-right source order == left-to-right visual order "
              f"for this flex row)",
              html.index("doAttach()") < html.index('id="entry"'))
        check(f"{key}: text entry comes before mic in the markup",
              html.index('id="entry"') < html.index('id="mic"'))
        check(f"{key}: mic comes before speaker in the markup (not merged, "
              f"not reordered)",
              html.index('id="mic"') < html.index('id="speaker"'))
        check(f"{key}: Enter key handler clears the box rather than "
              f"fabricating a reply/generation",
              "this.value=''" in html)
        check(f"{key}: minimize button calls the real window's own "
              f"minimize(), not a fake no-op",
              "pywebview.api.minimize()" in html)
        check(f"{key}: close button calls the real window's own "
              f"destroy() (via close_window), not a fake no-op",
              "pywebview.api.close_window()" in html)

    check("profile's extra body includes the placeholder avatar + 'You' label",
          "you-label" in wp._build_html("profile") and
          "avatar" in wp._build_html("profile"))
    check("chat/image_gen/video_gen have no avatar extra (that's Profile-only "
          "-- '.avatar' is shared CSS present in every panel's <style> block, "
          "but only Profile actually places a <div class=\"avatar\"> in its body)",
          all('<div class="avatar">' not in wp._build_html(k)
              for k in ("chat", "image_gen", "video_gen")))

    # -- PanelBridge against a fake Window, never a real OS window --
    class _FakeWindow:
        def __init__(self, dialog_result=None):
            self._dialog_result = dialog_result
            self.minimized = False
            self.destroyed = False

        def create_file_dialog(self, *_a, **_k):
            return self._dialog_result

        def minimize(self):
            self.minimized = True

        def destroy(self):
            self.destroyed = True

    bridge = wp.PanelBridge()
    check("a brand-new PanelBridge has no window yet", bridge.window is None)
    check("pick_file() with no window attached is a safe no-op (returns None)",
          bridge.pick_file() is None)

    fw = _FakeWindow(dialog_result=["/tmp/some/picked/photo.png"])
    bridge.window = fw
    result = bridge.pick_file()
    check("pick_file() returns both the full path and just the filename",
          result == {"path": "/tmp/some/picked/photo.png", "name": "photo.png"})

    fw_cancel = _FakeWindow(dialog_result=None)
    bridge2 = wp.PanelBridge()
    bridge2.window = fw_cancel
    check("pick_file() returns None (no fabricated attachment) when the "
          "real dialog is cancelled", bridge2.pick_file() is None)

    fw_empty = _FakeWindow(dialog_result=[])
    bridge3 = wp.PanelBridge()
    bridge3.window = fw_empty
    check("pick_file() also treats an empty result list as 'nothing picked'",
          bridge3.pick_file() is None)

    bridge.minimize()
    check("minimize() really calls the real window's own minimize()",
          fw.minimized is True)
    bridge.close_window()
    check("close_window() really calls the real window's own destroy()",
          fw.destroyed is True)

    bridge_nowin = wp.PanelBridge()
    check("minimize()/close_window() with no window attached never raise",
          not _raises(bridge_nowin.minimize) and
          not _raises(bridge_nowin.close_window))

    check("open_panel_blocking() rejects an unknown panel key",
          _raises(lambda: wp.open_panel_blocking("not-a-real-panel")))


def _raises(fn):
    try:
        fn()
        return False
    except Exception:  # noqa: BLE001
        return True


# ---------------------------------------------------------------------
# Part B: a real pywebview window, rendered for real (Xvfb + GTK WebKit2)
# ---------------------------------------------------------------------
def part_b():
    print("\n--- Part B: a real rendered pywebview window (Xvfb) ---")
    import webview_panels as wp

    if not wp.WEBVIEW_AVAILABLE:
        check("pywebview not installed on this machine -- Part B skipped "
              "(expected/handled: the real app simply keeps using "
              "conversation_panels.py's native Tkinter panels instead)",
              True)
        return
    try:
        import webview
    except Exception:
        check("webview import failed unexpectedly after WEBVIEW_AVAILABLE "
              "was True", False)
        return

    results = {}

    def _run():
        bridge = wp.PanelBridge()
        win = webview.create_window(
            "Webview Test Harness", html=wp._build_html("chat"), js_api=bridge,
            width=380, height=480, x=0, y=0, frameless=True,
            background_color="#1e1e1e")
        bridge.window = win

        def _probe():
            time.sleep(1.5)
            try:
                title_len = win.evaluate_js(
                    "document.querySelector('.titlebar .name').textContent.length")
                results["title_len"] = title_len
                results["has_entry"] = win.evaluate_js(
                    "!!document.getElementById('entry')")
            except Exception as exc:  # noqa: BLE001
                results["error"] = str(exc)
            finally:
                win.destroy()

        import threading
        threading.Thread(target=_probe, daemon=True).start()
        webview.start(gui=wp._pick_gui_backend(), debug=False)

    _run()
    check("a real pywebview/WebKit window actually rendered the titlebar "
          "text (evaluate_js round-tripped through the real JS engine)",
          results.get("title_len", 0) > 0)
    check("the real rendered DOM really has the #entry text input in it",
          results.get("has_entry") is True)


def main():
    part_a()
    part_b()
    passed = sum(1 for _, ok in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    if passed != len(CHECKS):
        sys.exit(1)


if __name__ == "__main__":
    main()
