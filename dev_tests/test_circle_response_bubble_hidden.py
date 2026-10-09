"""Regression test for: "hide the response bubble so the response text
isn't visible or readable when the agent is replying" -- the floating
circle must still visibly animate into RESPONDING exactly as before
(the outline/pulse animation, green on success / red on error), but
the reply text itself must never be rendered anywhere on screen,
whether it's a successful reply or an error message -- audio (TTS) is
the only place it ever comes out.

Kept in the persisted workspace (not /tmp) so it survives a fresh
sandbox session.

Run with:
    DISPLAY=:99 python3 dev_tests/test_circle_response_bubble_hidden.py
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import agent_overlay as ov  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def widget_texts(app):
    """Every bit of text any live widget is currently showing, so a test
    can assert a secret string never shows up in any of them."""
    out = []
    for w in app.allWidgets():
        getter = getattr(w, "text", None)
        if callable(getter):
            try:
                out.append(str(getter()))
            except Exception:  # noqa: BLE001
                pass
        getter2 = getattr(w, "toPlainText", None)
        if callable(getter2):
            try:
                out.append(str(getter2()))
            except Exception:  # noqa: BLE001
                pass
    return out


def main():
    check("ResponsePopup was removed entirely (not just hidden/unused)",
          not hasattr(ov, "ResponsePopup"))

    app = QApplication.instance() or QApplication(sys.argv)
    with mock.patch.object(ov, "ENABLE_VOICE_MODE", False), \
         mock.patch.object(ov, "ENABLE_SPEECH", False):
        overlay = ov.CircleOverlay()
    try:
        check("the circle has no response_popup attribute at all",
              not hasattr(overlay, "response_popup"))

        secret_ok = "TOP SECRET SUCCESSFUL REPLY, MUST NEVER BE SHOWN"
        overlay._last_was_error = False
        overlay._show_response(secret_ok, speak=False)
        app.processEvents()
        check("a successful reply still enters RESPONDING",
              overlay._state == ov.STATE_RESPONDING)
        check("a successful reply's text is not rendered in any widget",
              not any(secret_ok in t for t in widget_texts(app)))
        overlay._transition_timer.stop()

        secret_err = "TOP SECRET ERROR MESSAGE, MUST NEVER BE SHOWN EITHER"
        overlay._enter_state(ov.STATE_LOADING)
        overlay._last_was_error = True
        overlay._show_response(secret_err, speak=False)
        app.processEvents()
        check("an error reply still enters RESPONDING",
              overlay._state == ov.STATE_RESPONDING)
        check("an error reply still flags _last_was_error (keeps the red glow)",
              overlay._last_was_error is True)
        check("an error reply's text is not rendered in any widget either",
              not any(secret_err in t for t in widget_texts(app)))
        overlay._transition_timer.stop()

        # Returning to idle (the dismiss/cancel path a popup click used
        # to drive) must still work fine with no popup to dismiss.
        overlay._enter_state(ov.STATE_IDLE)
        app.processEvents()
        check("still returns to idle cleanly with no popup involved",
              overlay._state == ov.STATE_IDLE)
    finally:
        overlay._transition_timer.stop()
        overlay.close()
        overlay.deleteLater()
        app.processEvents()

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
