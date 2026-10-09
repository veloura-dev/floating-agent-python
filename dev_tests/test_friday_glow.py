"""Regression test for Task 22's "Friday state glow", now on Task 23's
push-based (not polled) architecture:

1. CircleOverlay (agent_overlay.py) must distinguish a successful reply
   from a failed one -- STATE_RESPONDING used to be painted green
   (BORDER_COLOR_RESPONDING) regardless of whether the reply was an
   error, which is misleading. _last_was_error now tracks that, and
   paintEvent's border-color choice (exercised indirectly here through
   the same attribute it reads) must pick red for errors.

2. The IDE's own window-border "glow" (ide.py's IDEApp.set_friday_status)
   must map (state, error) -> the right color, and the window's real
   highlightbackground/highlightcolor must change to match -- that's
   what makes the IDE's whole border visibly react to Friday's live state
   (white/grey=idle, blue=listening-or-thinking, green=answered
   successfully, red=error), per the user's mockup. Friday and the IDE are
   one process/thread now (Task 23), so this is a single direct method
   call agent_overlay.py's CircleOverlay._push_ide_status() makes every
   time its own state changes -- there's no poll loop or socket left to
   fake out here at all.

Run with:
    DISPLAY=:99 QT_QPA_PLATFORM=offscreen python3 dev_tests/test_friday_glow.py
"""
import os
import sys
import threading
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ide"))

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def run_circle_overlay_checks():
    from PySide6.QtWidgets import QApplication
    import agent_overlay as ov

    app = QApplication.instance() or QApplication(sys.argv)
    circle = ov.CircleOverlay()

    check("starts with no error flagged", circle._last_was_error is False)

    # Speech now stays in Loading (the spinner) until the speech worker
    # actually signals it's about to produce audio (see
    # agent_overlay.py's _show_response/_on_speech_started) -- a fake,
    # manually-driven worker keeps this deterministic and avoids
    # depending on whether real TTS is available on this machine.
    circle._state = ov.STATE_LOADING
    with mock.patch.object(ov, "SpeechWorker",
                            mock.Mock(return_value=mock.Mock())), \
         mock.patch.object(ov, "ENABLE_SPEECH", True):
        circle._on_reply_ok("all good")
        check("a successful reply clears the error flag",
              circle._last_was_error is False)
        check("a successful reply stays in Loading until speech actually "
              "starts (the animation must not get ahead of the audio)",
              circle._state == ov.STATE_LOADING)
        circle._on_speech_started()
        check("...then lands in RESPONDING the instant speech starts",
              circle._state == ov.STATE_RESPONDING)
        circle._on_speech_finished()
        circle._command_timeout_timer.stop()
        circle._capturing_voice_command = False

    circle._state = ov.STATE_LOADING
    circle._on_reply_err("quota exceeded")
    check("a failed reply sets the error flag",
          circle._last_was_error is True)
    check("a failed reply still lands in RESPONDING (just colored red, not green)",
          circle._state == ov.STATE_RESPONDING)

    # cancelled-while-loading must not update the flag (same guard as the
    # existing _on_reply_ok/_on_reply_err early-return behavior).
    circle._last_was_error = False
    circle._state = ov.STATE_IDLE  # i.e. the user already cancelled
    circle._on_reply_err("too late")
    check("a stale/cancelled reply is ignored, not flagged as an error",
          circle._last_was_error is False)

    # -- _push_ide_status: a single direct method call onto a live IDE,
    # no polling/socket involved at all anymore.
    import agent_tools

    class FakeIDE:
        def __init__(self):
            self.calls = []

        def set_friday_status(self, state, is_error):
            self.calls.append((state, is_error))

    fake_ide = FakeIDE()
    agent_tools._ide_app = fake_ide
    try:
        circle._last_was_error = True
        circle._state = ov.STATE_RESPONDING
        circle._push_ide_status()
        check("_push_ide_status calls the live IDE directly with the current state",
              fake_ide.calls[-1] == (ov.STATE_RESPONDING, True))

        circle._state = ov.STATE_IDLE
        circle._last_was_error = False
        circle._push_ide_status()
        check("_push_ide_status reflects a later state change too",
              fake_ide.calls[-1] == (ov.STATE_IDLE, False))
    finally:
        agent_tools._ide_app = None

    # No IDE open -> nothing to call, no crash.
    circle._push_ide_status()
    check("_push_ide_status is a safe no-op with no IDE open", True)


def run_ide_glow_checks():
    import ide as ide_mod
    app = ide_mod.IDEApp(None, agent_controlled=True)

    check("agent-controlled window gets a thicker glow ring",
          app._glow_thickness > 1)
    check("the window starts life colored idle (pushed once at startup)",
          app.cget("highlightbackground") == app._GLOW_IDLE)

    app.set_friday_status("idle", False)
    check("idle maps to the idle (white/grey) color",
          app.cget("highlightbackground") == app._GLOW_IDLE)

    app.set_friday_status("listening", False)
    check("listening maps to blue",
          app.cget("highlightbackground") == app._GLOW_BUSY)

    app.set_friday_status("loading", False)
    check("loading (thinking) also maps to blue",
          app.cget("highlightbackground") == app._GLOW_BUSY)

    app.set_friday_status("responding", False)
    check("a successful answer maps to green",
          app.cget("highlightbackground") == app._GLOW_OK)

    app.set_friday_status("responding", True)
    check("an error maps to red",
          app.cget("highlightbackground") == app._GLOW_ERR)

    app.update()

    app.destroy()
    sys.modules.pop("ide", None)


def run_standalone_has_no_glow_ring():
    import ide as ide_mod
    app = ide_mod.IDEApp(None, agent_controlled=False)
    check("a plain (non-agent) run keeps the old thin 1px outline",
          app._glow_thickness == 1)
    check("a plain (non-agent) run never touches the glow color at startup",
          app.cget("highlightbackground") != app._GLOW_BUSY
          and app.cget("highlightbackground") != app._GLOW_OK
          and app.cget("highlightbackground") != app._GLOW_ERR)
    app.destroy()
    sys.modules.pop("ide", None)


def main():
    run_circle_overlay_checks()
    run_ide_glow_checks()
    run_standalone_has_no_glow_ring()
    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
