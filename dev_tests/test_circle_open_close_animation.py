"""Regression test for: "separate Friday's circle from the IDE + add
open/close animations" --

  (a) the floating circle must no longer dock onto/track the IDE window
      at all -- it stays at its own fixed top-right-of-screen spot (or
      wherever the user dragged it) the entire time, regardless of the
      IDE's position or open/closed state;
  (b) agent_mode_on()/opening the IDE must visually animate the window
      as if it's emerging/growing out of the circle's current spot;
  (c) agent_mode_off()/closing the IDE must play the reverse animation,
      shrinking back down into that spot before the window disappears.

Also locks in that every bit of the old docking machinery (both the
Qt-side circle-tracking code and the Tk-side dock-rect-reporting code)
is actually gone, not just unused.

Kept in the persisted workspace (not /tmp) so it survives a fresh
sandbox session.

Run with:
    DISPLAY=:99 python3 dev_tests/test_circle_open_close_animation.py
"""
import os
import sys
import tempfile
import time
from unittest import mock

import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ide"))

from PySide6.QtWidgets import QApplication  # noqa: E402

import agent_overlay as ov  # noqa: E402
import agent_tools as at  # noqa: E402
import ide as ide_mod  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def alive(app):
    try:
        return bool(app.winfo_exists())
    except tk.TclError:
        return False


# ---------------------------------------------------------------------
# Part 1: the old docking machinery is actually gone, not just unused.
# ---------------------------------------------------------------------
def check_dead_docking_code_is_gone():
    for name in ("_dock_position_for_rect", "_dock_position_for_zone",
                 "_physical_rect_to_logical", "_find_window_rect_by_pid",
                 "_user32_functions", "_enum_visible_windows",
                 "_IDE_WINDOW_TITLE_SUFFIX", "_USER32_CACHE"):
        check(f"agent_overlay.{name} was removed", not hasattr(ov, name))

    for name in ("_track_agent_mode_window",):
        check(f"CircleOverlay.{name} was removed",
              not hasattr(ov.CircleOverlay, name))

    check("agent_tools.get_ide_dock_rect() was removed",
          not hasattr(at, "get_ide_dock_rect"))
    check("ide.IDEApp.get_dock_rect() was removed",
          not hasattr(ide_mod.IDEApp, "get_dock_rect"))

    check("CircleOverlay still has get_circle_rect()",
          hasattr(ov.CircleOverlay, "get_circle_rect"))
    check("CircleOverlay still has _position_top_right()",
          hasattr(ov.CircleOverlay, "_position_top_right"))
    check("agent_tools has set_circle_rect_provider()",
          hasattr(at, "set_circle_rect_provider"))
    check("_AgentHost has get_circle_rect()",
          hasattr(at._AgentHost, "get_circle_rect"))
    for name in ("_maybe_play_open_animation", "_play_close_animation",
                 "_animate_geometry", "_circle_pop_origin",
                 "_show_launch_curtain", "_hide_launch_curtain"):
        check(f"ide.IDEApp.{name}() exists",
              hasattr(ide_mod.IDEApp, name))


# ---------------------------------------------------------------------
# Part 2: get_circle_rect()'s DPI-conversion math, exercised directly on
# a lightweight stand-in (no real QWidget/QApplication needed for the
# pure math itself).
# ---------------------------------------------------------------------
class _FakeGeom:
    def __init__(self, x, y, w, h):
        self._x, self._y, self._w, self._h = x, y, w, h

    def x(self): return self._x
    def y(self): return self._y
    def width(self): return self._w
    def height(self): return self._h


class FakeOverlayForRect:
    def __init__(self, geom, dpr):
        self._geom = geom
        self._dpr = dpr

    def geometry(self):
        return self._geom

    def screen(self):
        return None

    def _physical_pixel_ratio(self):
        return self._dpr


def check_get_circle_rect_math():
    # 100% scaling -- a 40x40 circle at (100, 50) in logical pixels
    # should report its center/diameter unscaled.
    fake = FakeOverlayForRect(_FakeGeom(100, 50, 40, 40), 1.0)
    rect = ov.CircleOverlay.get_circle_rect(fake)
    check("get_circle_rect centers correctly at 100% scaling",
          rect == (120.0, 70.0, 40.0))

    # 150% scaling: the physical-pixel rect must come back scaled up by
    # the device pixel ratio.
    fake2 = FakeOverlayForRect(_FakeGeom(100, 50, 40, 40), 1.5)
    rect2 = ov.CircleOverlay.get_circle_rect(fake2)
    check("get_circle_rect scales up by the device pixel ratio",
          rect2 == (180.0, 105.0, 60.0))

    # A raising geometry() (or any other failure) must come back None,
    # not raise -- this is purely cosmetic plumbing.
    class Boom:
        def geometry(self):
            raise RuntimeError("no screen")

    check("get_circle_rect() swallows exceptions and returns None",
          ov.CircleOverlay.get_circle_rect(Boom()) is None)


# ---------------------------------------------------------------------
# Part 3: the real circle, on a real (offscreen-capable) QApplication --
# confirms it starts top-right and genuinely never moves on its own,
# whether or not Agent Mode is "on".
# ---------------------------------------------------------------------
def check_real_circle_stays_put():
    app = QApplication.instance() or QApplication(sys.argv)
    with mock.patch.object(ov, "ENABLE_VOICE_MODE", False):
        overlay = ov.CircleOverlay()
    try:
        app.processEvents()
        pos1 = (overlay.x(), overlay.y())

        check("circle has no docking timer at all",
              not hasattr(overlay, "_ide_dock_timer"))
        check("circle has no 'docked' flag at all",
              not hasattr(overlay, "_agent_mode_docked"))

        rect = overlay.get_circle_rect()
        check("get_circle_rect() returns a sane 3-tuple on a real circle",
              isinstance(rect, tuple) and len(rect) == 3)
        if rect:
            cx, cy, diameter = rect
            expected_diameter = max(overlay.width(), overlay.height()) * \
                overlay._physical_pixel_ratio()
            check("reported diameter matches the circle's real size",
                  abs(diameter - expected_diameter) < 2)

        # Simulate "Agent Mode is on" exactly the way the old docking
        # timer used to check it (agent_tools.get_ide_pid() returning a
        # real pid) -- with the docking code gone, this must have zero
        # effect on the circle's position.
        with mock.patch.object(at, "get_ide_pid", lambda: os.getpid()):
            for _ in range(5):
                app.processEvents()
                time.sleep(0.05)
        pos2 = (overlay.x(), overlay.y())
        check("circle does not move while 'Agent Mode' is simulated on",
              pos1 == pos2)

        # Re-asserting the top-right position (what agent_mode_on() /
        # open used to indirectly perturb via docking) must still land
        # it in the same spot it already was -- it's a fixed corner.
        overlay._position_top_right()
        app.processEvents()
        pos3 = (overlay.x(), overlay.y())
        check("_position_top_right() is idempotent / stays top-right",
              pos3 == pos1)
    finally:
        overlay.close()
        overlay.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------------
# Part 4: the Tk-side open/close pop animation.
# ---------------------------------------------------------------------
class FakeHostWithCircle:
    def __init__(self, rect):
        self._rect = rect

    def get_circle_rect(self):
        return self._rect

    def ask(self, text, on_done):
        on_done(True, "ok")

    def on_ide_closed(self):
        pass


def pump(app, ms, step=15):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        try:
            app.update()
        except tk.TclError:
            return
        time.sleep(step / 1000.0)


def check_open_animation_plays_then_settles():
    d = tempfile.mkdtemp(prefix="friday-anim-")
    # A small "circle" near the top-left -- deliberately far from where
    # the window will end up, so a real animated transition is
    # unmistakable from an instant jump.
    host = FakeHostWithCircle((40.0, 40.0, 56.0))
    app = ide_mod.IDEApp(d, agent_controlled=True, agent_host=host)
    try:
        final_x, final_y, final_w, final_h = app._final_geom

        # Immediately after construction the window should already have
        # been snapped down to a small square near the circle -- the
        # open animation's starting frame -- not already sitting at the
        # full final size.
        app.update_idletasks()
        early_w = app.winfo_width()
        check("window starts the open animation small, not full-size",
              early_w < final_w * 0.5)

        pump(app, 500)
        app.update_idletasks()
        settled_w, settled_h = app.winfo_width(), app.winfo_height()
        check("window settles at its real final width after the open animation",
              abs(settled_w - final_w) <= 2)
        check("window settles at its real final height after the open animation",
              abs(settled_h - final_h) <= 2)
        check("no geometry-animation job left pending once settled",
              getattr(app, "_geom_anim_job", None) is None)
    finally:
        if alive(app):
            app.destroy()


def check_close_animation_delays_then_destroys():
    d = tempfile.mkdtemp(prefix="friday-anim-close-")
    host = FakeHostWithCircle((40.0, 40.0, 56.0))
    app = ide_mod.IDEApp(d, agent_controlled=True, agent_host=host)
    try:
        pump(app, 400)  # let the open animation finish first

        app.close_window()
        check("window is not destroyed the instant close_window() returns",
              alive(app))

        pump(app, 500)
        check("window is actually destroyed once the close animation settles",
              not alive(app))
    finally:
        if alive(app):
            app.destroy()


def check_no_circle_means_instant_open_and_close():
    d = tempfile.mkdtemp(prefix="friday-anim-none-")
    host = FakeHostWithCircle(None)  # no circle rect available
    app = ide_mod.IDEApp(d, agent_controlled=True, agent_host=host)
    try:
        app.update_idletasks()
        final_x, final_y, final_w, final_h = app._final_geom
        check("with no circle rect, window opens straight at full size",
              abs(app.winfo_width() - final_w) <= 2)

        app.close_window()
        app.update()
        check("with no circle rect, close_window() destroys immediately",
              not alive(app))
    finally:
        if alive(app):
            app.destroy()


def check_standalone_run_is_unaffected():
    """A plain `python ide.py` run (agent_controlled=False) must never
    play this animation at all, even if an agent_host happens to be
    passed in (it normally wouldn't be)."""
    d = tempfile.mkdtemp(prefix="friday-anim-standalone-")
    app = ide_mod.IDEApp(d, agent_controlled=False)
    try:
        app.update_idletasks()
        final_x, final_y, final_w, final_h = app._final_geom
        check("standalone window opens straight at full size, no animation",
              abs(app.winfo_width() - final_w) <= 2)
        app.close_window()
        app.update()
        check("standalone close_window() destroys immediately", not alive(app))
    finally:
        if alive(app):
            app.destroy()


def main():
    check_dead_docking_code_is_gone()
    check_get_circle_rect_math()
    check_real_circle_stays_put()
    check_open_animation_plays_then_settles()
    check_close_animation_delays_then_destroys()
    check_no_circle_means_instant_open_and_close()
    check_standalone_run_is_unaffected()

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
