"""Proof that "Option B" -- wiring webview_panels.py's upgraded HTML/
CSS/JS panels into the real open_app()/AppPanelManager path -- actually
works, end to end, through the exact same machinery Chrome/Calculator
already use (RealLauncher.launch() + AppPanelManager.open()/minimize()/
close()), not a side mechanism:

  - app_panels.set_panel_ui_mode() defaults to "native" (zero behavior
    change for anyone not explicitly opting in) and only mutates
    CUSTOM_PANEL_APPS when actually switching;
  - it refuses (raises, doesn't silently no-op) to switch to "web" if
    pywebview/a working backend genuinely isn't available;
  - window_backend.RealLauncher knows how to build the real subprocess
    command for all 4 keys once in "web" mode;
  - a real AppPanelManager.open() call in "web" mode really launches
    webview_panels.py as a real OS process (not a Tkinter custom
    panel), tracks it exactly like Chrome, and close() really tears
    the process down.

Requires a real (Xvfb) display + a working pywebview backend for Part
C -- same DISPLAY=:99 requirement as dev_tests/test_webview_panels.py;
Part C is skipped (not failed) if either isn't available on this
machine, exactly how set_panel_ui_mode itself is designed to behave.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def _raises(fn):
    try:
        fn()
        return False
    except Exception:  # noqa: BLE001
        return True


def part_a():
    print("\n--- Part A: set_panel_ui_mode() ---")
    import app_panels as ap

    # Always restore to native afterwards, whatever happens, so this
    # test file never leaves global state behind for any test that
    # runs after it in the same process.
    try:
        check("PANEL_UI_MODE starts out 'native'", ap.PANEL_UI_MODE == "native")
        check("all 4 panel keys are in CUSTOM_PANEL_APPS by default "
              "(zero behavior change out of the box)",
              {"chat", "profile", "image_gen", "video_gen"} <= ap.CUSTOM_PANEL_APPS)
        check("set_panel_ui_mode() rejects a garbage mode",
              _raises(lambda: ap.set_panel_ui_mode("blorp")))
        check("...and a rejected call doesn't change PANEL_UI_MODE",
              ap.PANEL_UI_MODE == "native")

        import webview_panels as wp
        if wp.WEBVIEW_AVAILABLE:
            ap.set_panel_ui_mode("web")
            check("set_panel_ui_mode('web') succeeds when pywebview is "
                  "really available", ap.PANEL_UI_MODE == "web")
            check("...and removes all 4 keys from CUSTOM_PANEL_APPS (so "
                  "they fall through to the real-process launch path)",
                  not ({"chat", "profile", "image_gen", "video_gen"} &
                       ap.CUSTOM_PANEL_APPS))
            ap.set_panel_ui_mode("native")
            check("switching back to 'native' restores all 4 keys to "
                  "CUSTOM_PANEL_APPS", {"chat", "profile", "image_gen",
                  "video_gen"} <= ap.CUSTOM_PANEL_APPS)

            # -- simulate pywebview genuinely not being available (a
            #    machine with no WebView2 Runtime / no WebKitGTK) --
            orig = wp.WEBVIEW_AVAILABLE
            wp.WEBVIEW_AVAILABLE = False
            try:
                check("set_panel_ui_mode('web') refuses (raises) rather "
                      "than silently no-op-ing when no working backend "
                      "is actually available",
                      _raises(lambda: ap.set_panel_ui_mode("web")))
                check("...and PANEL_UI_MODE stays 'native' after the "
                      "refused switch", ap.PANEL_UI_MODE == "native")
            finally:
                wp.WEBVIEW_AVAILABLE = orig
        else:
            check("pywebview isn't available on this machine -- "
                  "set_panel_ui_mode('web') correctly refuses instead of "
                  "silently pretending to switch",
                  _raises(lambda: ap.set_panel_ui_mode("web")))
            check("...and PANEL_UI_MODE stays 'native'",
                  ap.PANEL_UI_MODE == "native")
    finally:
        ap.set_panel_ui_mode("native")


def part_b():
    print("\n--- Part B: RealLauncher's real subprocess command ---")
    import window_backend as wb

    launcher = wb.RealLauncher()
    script_path = os.path.join(
        os.path.dirname(os.path.abspath(wb.__file__)), "webview_panels.py")
    check("webview_panels.py really exists on disk right next to "
          "window_backend.py", os.path.isfile(script_path))

    for key in ("chat", "profile", "image_gen", "video_gen"):
        args = launcher._webview_panel_command(key)
        check(f"{key}: the real launch command runs this same Python "
              f"interpreter", args[0] == sys.executable)
        check(f"{key}: ...against the real webview_panels.py script",
              args[1] == script_path)
        check(f"{key}: ...with the panel key as its one argument",
              args[2:] == [key])

    check("launch() for an unknown app key still raises cleanly "
          "(unrelated to this change -- guards against a future typo "
          "silently matching nothing)",
          _raises(lambda: launcher.launch("not-a-real-app")))


def part_c():
    print("\n--- Part C: a real AppPanelManager.open() in 'web' mode (Xvfb) ---")
    import app_panels as ap
    import webview_panels as wp

    if not wp.WEBVIEW_AVAILABLE:
        check("pywebview isn't available here -- Part C skipped (expected: "
              "the real app simply keeps PANEL_UI_MODE='native' instead)",
              True)
        return

    class _StubAgentHost:
        def get_panel_placement(self, key):
            return (0, 0, 420, 520), True, ""

        def get_pill_slot(self, key):
            return 0

        def release_pill_slot(self, key):
            return []

        def reposition_pill(self, key, idx):
            pass

        def release_panel_slot(self, key):
            pass

    try:
        ap.set_panel_ui_mode("web")
        mgr = ap.AppPanelManager(launcher=ap.RealLauncher(),
                                  agent_host=_StubAgentHost())
        try:
            msg = mgr.open("chat")
            check("open('chat') in web mode succeeds through the exact "
                  "same open() every other app uses",
                  "Opened Chat" in msg)
            rec = mgr._panels.get("chat")
            check("...and it's tracked as a REAL process this time "
                  "(unlike native mode's custom in-process panel)",
                  rec is not None and rec.get("proc") is not None)
            check("...not as a custom in-process panel",
                  rec.get("custom") is False and rec.get("frame") is None)
            check("list_panels() reports it open",
                  "chat" in mgr.list_panels().lower())

            time.sleep(2)  # let the real subprocess actually start up

            msg = mgr.minimize("chat")
            check("minimize('chat') in web mode succeeds (falls back to "
                  "just showing a pill -- no hwnd to tell the OS to "
                  "minimize on this non-Windows dev machine, exactly the "
                  "same graceful fallback Chrome already gets here)",
                  "Chat" in msg or "minimized" in msg.lower())
            msg = mgr.restore("chat")
            check("restore('chat') succeeds", "Restored Chat" in msg)

            msg = mgr.close("chat")
            check("close('chat') succeeds", "Closed Chat" in msg)
            check("the real subprocess is actually gone from tracking",
                  "chat" not in mgr._panels)
            time.sleep(0.5)
            poll = rec["proc"].poll()
            check("...and the real OS process was actually terminated "
                  "(not leaked running in the background)",
                  poll is not None)
        finally:
            # best-effort cleanup if any assertion above failed midway
            leftover = mgr._panels.get("chat")
            if leftover is not None and leftover.get("proc") is not None:
                try:
                    leftover["proc"].terminate()
                except Exception:  # noqa: BLE001
                    pass
    finally:
        ap.set_panel_ui_mode("native")


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
