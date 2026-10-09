"""Regression test for the minimize-to-pill feature: the titlebar's
minimize button, under Agent Mode, must tuck the IDE window away into a
small pill-shaped indicator just under Friday's floating circle (instead
of a normal OS-level minimize), connected to the circle by a thin line,
speaking its name aloud on hover and restoring the window exactly as it
was on click. Must gracefully fall back to a plain OS-level minimize
whenever the circle's on-screen spot isn't available at all (standalone
`python ide.py` runs, or any run where the circle-rect provider fails).

Kept in the persisted workspace (not /tmp) so it survives a fresh
sandbox session.

Run with:
    DISPLAY=:99 python3 dev_tests/test_ide_minimize_pill.py
"""
import os
import sys
import time

import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ide"))

import ide as ide_mod  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def pump(app, times=40, delay=0.02):
    for _ in range(times):
        try:
            app.update()
        except tk.TclError:
            return
        time.sleep(delay)


class FakeHost:
    """Stand-in for agent_tools._AgentHost: a fixed circle rect (unless
    told otherwise) and a speak_label() that just records what it was
    asked to say, instead of touching real TTS."""

    def __init__(self, rect=(960, 60, 48)):
        self._rect = rect
        self.spoken = []

    def ask(self, text, on_done):
        on_done(True, "ok")

    def on_ide_closed(self):
        pass

    def get_circle_rect(self):
        return self._rect

    def speak_label(self, text):
        self.spoken.append(text)


def alive(widget):
    try:
        return bool(widget.winfo_exists())
    except tk.TclError:
        return False


def main():
    host = FakeHost()
    app = ide_mod.IDEApp(start_dir=None, agent_controlled=True, agent_host=host)
    pump(app, 10)

    # 1. Baseline: not minimized yet, window fully visible, no pill.
    check("no pill before minimizing", getattr(app, "_pill", None) is None)
    check("window viewable before minimizing", app.winfo_viewable())

    original_geom = (app.winfo_x(), app.winfo_y(),
                      app.winfo_width(), app.winfo_height())

    # 2. Minimize -> pill appears, main window hides.
    app.minimize_to_pill()
    pump(app)
    pill = getattr(app, "_pill", None)
    check("minimize_to_pill() creates a pill", pill is not None)
    check("main window no longer viewable once minimized",
          not app.winfo_viewable())
    check("pill is a real, alive Toplevel", pill is not None and alive(pill))

    # 3. Position: pill should be horizontally centered under the circle,
    # with its top edge at (or very near) the circle's bottom edge.
    if pill is not None:
        cx, circle_center_y, diameter = host._rect
        bottom_y = circle_center_y + diameter / 2  # get_circle_rect() is
                                                    # (center_x, center_y,
                                                    # diameter), not a
                                                    # top-left/bottom edge
        pill_x = pill.winfo_x()
        pill_y = pill.winfo_y()
        pill_w = pill.winfo_width()
        pill_center_x = pill_x + pill_w / 2
        check("pill horizontally centered under the circle",
              abs(pill_center_x - cx) <= 3)
        check("pill's top edge sits at the circle's bottom edge",
              abs(pill_y - bottom_y) <= 3)
        check("pill shape is a real polygon item on its own canvas",
              pill._pill_shape in pill.canvas.find_all())

    # 4. Calling minimize again while already minimized is a safe no-op
    # (never two pills at once).
    app.minimize_to_pill()
    pump(app, 5)
    check("minimizing twice in a row doesn't create a second pill",
          getattr(app, "_pill", None) is pill)

    # 5. Hover -> after the debounce delay, Friday's voice is asked to
    # say the panel's name ("IDE" -- APP_NAME).
    if pill is not None:
        pill._on_hover_enter()
        pump(app, 5)
        check("nothing spoken yet before the hover delay elapses",
              host.spoken == [])
        time.sleep(pill.HOVER_SPEAK_DELAY_MS / 1000 + 0.15)
        pump(app, 5)
        check("hovering speaks the panel's name after the delay",
              host.spoken == ["IDE"])
        check("the spoken name matches the IDE's own APP_NAME constant",
              host.spoken and host.spoken[0] == ide_mod.APP_NAME)

        # Leaving before the delay elapses must cancel the pending speech.
        host.spoken.clear()
        pill._on_hover_enter()
        pump(app, 2)
        pill._on_hover_leave()
        time.sleep(pill.HOVER_SPEAK_DELAY_MS / 1000 + 0.15)
        pump(app, 5)
        check("leaving early cancels the pending hover announcement",
              host.spoken == [])

    # 6. Click -> restores the window to exactly its pre-minimize geometry.
    if pill is not None:
        pill._on_click()
        pump(app)
        check("pill is gone after clicking it", getattr(app, "_pill", None) is None)
        check("clicked pill window itself was destroyed", not alive(pill))
        check("main window viewable again after restoring",
              app.winfo_viewable())
        restored_geom = (app.winfo_x(), app.winfo_y(),
                          app.winfo_width(), app.winfo_height())
        check("restored geometry matches what it was before minimizing",
              restored_geom == original_geom)

    # 7. Minimizing again after a restore must work the same way (not a
    # one-shot feature).
    app.minimize_to_pill()
    pump(app)
    second_pill = getattr(app, "_pill", None)
    check("can minimize again after restoring", second_pill is not None)
    if second_pill is not None:
        second_pill._on_click()
        pump(app)
        check("restores cleanly a second time", getattr(app, "_pill", None) is None)

    # 8. Minimizing while already minimized-then-closed shouldn't leak a
    # pill window: destroying the main window must take the pill with it.
    app.minimize_to_pill()
    pump(app)
    leaked_pill = getattr(app, "_pill", None)
    check("have a pill to test the destroy-cascade with",
          leaked_pill is not None)
    app.destroy()
    pump_fake = None
    time.sleep(0.1)
    check("destroying the main window also destroys its pill",
          leaked_pill is not None and not alive(leaked_pill))

    # 9. Fallback: no circle rect available at all (e.g. the provider
    # fails or there's genuinely no circle) -> falls back to a plain
    # OS-level minimize, never crashes, never fabricates a pill.
    class NoCircleHost(FakeHost):
        def get_circle_rect(self):
            return None

    app2 = ide_mod.IDEApp(start_dir=None, agent_controlled=True,
                           agent_host=NoCircleHost())
    pump(app2, 10)
    try:
        app2.minimize_to_pill()
        pump(app2, 10)
        fallback_ok = True
    except Exception:  # noqa: BLE001
        fallback_ok = False
    check("falls back without crashing when no circle rect is available",
          fallback_ok)
    check("no pill fabricated when there's nothing to tuck it under",
          getattr(app2, "_pill", None) is None)
    app2.destroy()

    # 10. Standalone (non-agent-controlled) run: minimize_to_pill is still
    # the button's handler, but with no circle at all it must fall back
    # to the original OS-level minimize_window(), not attempt a pill.
    app3 = ide_mod.IDEApp(start_dir=None, agent_controlled=False, agent_host=None)
    pump(app3, 10)
    try:
        app3.minimize_to_pill()
        pump(app3, 10)
        standalone_ok = True
    except Exception:  # noqa: BLE001
        standalone_ok = False
    check("standalone run's minimize button doesn't crash either",
          standalone_ok)
    check("standalone run never creates a pill (no circle to anchor to)",
          getattr(app3, "_pill", None) is None)
    app3.destroy()

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
