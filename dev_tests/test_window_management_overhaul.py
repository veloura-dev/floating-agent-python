"""Proof that Friday's unified window-management system works: his IDE
and every app_panels.py panel (Chrome/Notepad/Calculator) are treated
as one single pool for pill-stacking, and share one single on-screen
rule -- exactly ONE panel is ever visible at a time (Task 48's full
removal of the old 3-side-slot layout).

  - minimized pills (IDE's own + every app_panels.py panel's) share one
    single vertical stack under the circle, coordinated centrally
    through agent_tools._AgentHost (get_pill_slot/release_pill_slot/
    reposition_pill) -- no two pills ever land on the same slot, and
    releasing one in the middle of the stack reflows everything below
    it up to close the resulting gap;
  - every panel, the instant it opens (or is restored from minimized),
    becomes Friday's one single active/visible panel -- full screen, at
    a fixed, nameable reference size/position (_ide_reference_bounds)
    -- and whatever panel was active immediately before it (if any) is
    automatically minimized to a pill to make room. This is true every
    time, not just for the session's first-ever panel -- there's no
    side-slot system or 4-panel-visible cap left to reach any more;
  - maximize_app(which) and restore_app(which) are deliberately the
    same underlying action now: both promote the target straight to
    being the one active panel, minimizing whatever was previously
    active (if anything) in its place. Neither requires the IDE to be
    open to do this (the reference bounds are a fixed formula, not a
    live measurement of the IDE's own window);
  - every panel (including the IDE's own window) gets the same white
    border styling, and the one currently-active panel (and only it)
    shows a pulsing violet "active panel" border.

Part A exercises app_panels.py's maximize/unmaximize/pill-slot-dispatch
mechanics directly with fakes, no IDE involved at all (mirrors
dev_tests/test_app_panels.py's Part A) -- these are generic, policy-
independent Tk mechanics Task 48's placement-policy rewrite didn't
touch. Part B exercises the full unified placement system through
agent_tools.py's tools, against a real (Xvfb) IDE -- same DISPLAY=:99
requirement as dev_tests/test_agent_tools_ide.py. Part C covers Task
47's side-slot-size and active-panel-border follow-ups, updated for
Task 48's single-active-panel model.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_panels as ap  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.03)
    return predicate()


# --------------------------------------------------------------------
# Fakes (same spirit as dev_tests/test_app_panels.py's)
# --------------------------------------------------------------------
class FakeProc:
    def __init__(self, pid):
        self.pid = pid
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self._alive = False


class FakeLauncher:
    def __init__(self):
        self.calls = []
        self._next_pid = 2000

    def launch(self, app_key, url=None, file_path=None, content=None):
        self.calls.append((app_key, url, file_path))
        self._next_pid += 1
        return FakeProc(self._next_pid)


class FakeWindowBackend:
    """Adds get_window_rect/move_resize/bring_to_front on top of the
    usual fake surface, so maximize_panel's non-embedded (hwnd) path is
    exercisable without a real OS window."""

    def __init__(self, embed_supported=False, embed_succeeds=True):
        self.minimized, self.restored, self.closed = [], [], []
        self.embeds, self.resizes = [], []
        self.moved = []
        self.fronted = []
        self._embed_supported = embed_supported
        self._embed_succeeds = embed_succeeds
        self._rects = {}  # hwnd -> (x, y, w, h)

    def is_supported(self):
        return self._embed_supported

    def snapshot_top_level_hwnds(self):
        return set()

    def find_hwnd_for_launch(self, pid, title_hint, before_hwnds, timeout=8.0):
        hwnd = 9000 + pid
        self._rects[hwnd] = (10, 10, 300, 200)  # arbitrary starting rect
        return hwnd

    def minimize(self, hwnd):
        self.minimized.append(hwnd)
        return True

    def restore(self, hwnd):
        self.restored.append(hwnd)
        return True

    def close(self, hwnd):
        self.closed.append(hwnd)
        return True

    def embed(self, parent_hwnd, child_hwnd, width, height):
        self.embeds.append((parent_hwnd, child_hwnd, width, height))
        return (self._embed_succeeds, None if self._embed_succeeds else "fake embed failure")

    def resize_embedded(self, child_hwnd, width, height):
        self.resizes.append((child_hwnd, width, height))
        return True

    def get_window_rect(self, hwnd):
        return self._rects.get(hwnd)

    def move_resize(self, hwnd, x, y, w, h):
        self.moved.append((hwnd, x, y, w, h))
        self._rects[hwnd] = (x, y, w, h)
        return True

    def bring_to_front(self, hwnd):
        self.fronted.append(hwnd)
        return True


class FakeAgentHostWithStack:
    """A minimal stand-in for agent_tools._AgentHost exposing exactly
    the pill-stack methods AppPanelManager dispatches to, so Part A can
    prove app_panels.py actually *calls* them (rather than falling back
    to its own local count-based scheme) without needing the real
    agent_tools module at all. Deliberately does NOT implement
    get_panel_placement/release_panel_slot -- AppPanelManager's
    _decide_placement/_release_panel_slot_for must tolerate an
    agent_host that doesn't have the newer Task 46 methods (the plain
    hasattr-guarded no-op fallback), same as it must tolerate no
    agent_host at all."""

    def __init__(self, rect=(200, 150, 64)):
        self._rect = rect
        self.get_slot_calls = []
        self.release_calls = []
        self.reposition_calls = []
        self._stack = []

    def get_circle_rect(self):
        return self._rect

    def speak_label(self, text):
        pass

    def get_pill_slot(self, key):
        self.get_slot_calls.append(key)
        if key not in self._stack:
            self._stack.append(key)
        return self._stack.index(key)

    def release_pill_slot(self, key):
        self.release_calls.append(key)
        if key in self._stack:
            self._stack.remove(key)
        return [(k, i) for i, k in enumerate(self._stack)]

    def reposition_pill(self, key, slot_index):
        self.reposition_calls.append((key, slot_index))


def part_a():
    # Everything in this process that touches real Tk widgets goes
    # through AppPanelManager's own dedicated panel-host thread (same
    # as app_panels.py's production code always does) -- never a bare
    # tk.Tk() constructed directly on this test's own main thread.
    # Mixing a main-thread Tcl interpreter with the separate
    # dedicated-thread interpreters agent_tools.py's IDE and
    # AppPanelManager's panel host each spin up on their own is exactly
    # the kind of cross-thread Tcl/Tk state mixing this project's whole
    # multi-Tk-root architecture is built to avoid.
    launcher = FakeLauncher()
    backend = FakeWindowBackend(embed_supported=True, embed_succeeds=True)
    host = FakeAgentHostWithStack()
    mgr = ap.AppPanelManager(launcher=launcher, window_backend=backend, agent_host=host)
    mgr._ensure_host()

    # ---- white border + maximize_to/restore_default: a scratch panel ----
    scratch = mgr._bridge.call(lambda: ap.EmbeddedAppPanel(
        mgr._root, label="Scratch", on_minimize=lambda: None,
        on_close=lambda: None, corner_index=3))
    check("EmbeddedAppPanel's own background is white (the border color)",
          mgr._bridge.call(lambda: scratch.cget("bg")) == "#ffffff")
    check("EmbeddedAppPanel remembers its own default geometry",
          scratch._default_geometry[2:] == (ap.EmbeddedAppPanel.DEFAULT_W,
                                             ap.EmbeddedAppPanel.DEFAULT_H))
    check("EmbeddedAppPanel starts not maximized", scratch.is_maximized is False)

    mgr._bridge.call(lambda: scratch.maximize_to(50, 60, 800, 600))
    geom = mgr._bridge.call(lambda: (scratch.winfo_x(), scratch.winfo_y(),
                                      scratch.winfo_width(), scratch.winfo_height()))
    check("maximize_to() resizes the panel to the requested bounds",
          geom[2:] == (800, 600))
    check("maximize_to() moves the panel to the requested position",
          geom[:2] == (50, 60))
    check("maximize_to() flags the panel as maximized", scratch.is_maximized is True)

    mgr._bridge.call(scratch.restore_default)
    geom = mgr._bridge.call(lambda: (scratch.winfo_x(), scratch.winfo_y(),
                                      scratch.winfo_width(), scratch.winfo_height()))
    dx, dy, dw, dh = scratch._default_geometry
    check("restore_default() shrinks the panel back to its own default size",
          geom[2:] == (dw, dh))
    check("restore_default() moves it back to its own default position",
          geom[:2] == (dx, dy))
    check("restore_default() clears the maximized flag", scratch.is_maximized is False)
    mgr._bridge.call(scratch.destroy)

    # ---- maximize_panel/unmaximize_panel: embedded path ----
    mgr.open("notepad")
    wait_for(lambda: mgr._panels.get("notepad", {}).get("embedded"))
    check("notepad embedded successfully for this test's setup",
          mgr._panels["notepad"].get("embedded"))

    ok, reason = mgr.maximize_panel("notepad", (11, 22, 777, 555))
    check("maximize_panel() succeeds for an embedded panel", ok and reason is None)
    frame = mgr._panels["notepad"]["frame"]
    check("the embedded frame is marked maximized",
          mgr._panels["notepad"]["maximized"] is True)
    geom = mgr._bridge.call(lambda: (frame.winfo_x(), frame.winfo_y(),
                                      frame.winfo_width(), frame.winfo_height()))
    check("the embedded frame's real geometry matches the requested bounds",
          geom == (11, 22, 777, 555))

    mgr.unmaximize_panel("notepad")
    dgeom = mgr._bridge.call(lambda: (frame.winfo_x(), frame.winfo_y(),
                                       frame.winfo_width(), frame.winfo_height()))
    default_xywh = mgr._bridge.call(lambda: frame._default_geometry)
    check("unmaximize_panel() shrinks the embedded frame back to its own default",
          dgeom == default_xywh)
    check("unmaximize_panel() clears the maximized flag",
          mgr._panels["notepad"]["maximized"] is False)

    # ---- maximize_panel/unmaximize_panel: non-embedded (hwnd) path ----
    msg = mgr.open("chrome")
    check("chrome opened for the hwnd-path test", "Opened Chrome" in msg)
    chrome_hwnd = mgr._panels["chrome"]["hwnd"]
    ok, reason = mgr.maximize_panel("chrome", (1, 2, 333, 444))
    check("maximize_panel() succeeds for a non-embedded (hwnd) panel", ok and reason is None)
    check("maximize_panel() snapshotted chrome's pre-maximize bounds first",
          mgr._panels["chrome"]["pre_maximize_bounds"] == (10, 10, 300, 200))
    check("maximize_panel() actually moved/resized chrome's real window",
          backend.moved[-1] == (chrome_hwnd, 1, 2, 333, 444))
    check("maximize_panel() brought chrome's real window to the front",
          backend.fronted[-1] == chrome_hwnd)
    check("chrome is marked maximized", mgr._panels["chrome"]["maximized"] is True)

    mgr.unmaximize_panel("chrome")
    check("unmaximize_panel() restores chrome's pre-maximize bounds",
          backend.moved[-1] == (chrome_hwnd, 10, 10, 300, 200))
    check("unmaximize_panel() clears chrome's pre_maximize_bounds snapshot",
          mgr._panels["chrome"]["pre_maximize_bounds"] is None)
    check("chrome is no longer marked maximized", mgr._panels["chrome"]["maximized"] is False)

    # ---- minimizing a maximized panel implicitly un-maximizes it ----
    mgr.maximize_panel("chrome", (5, 5, 200, 200))
    check("chrome is maximized again, ready for the minimize-unmaximizes check",
          mgr._panels["chrome"]["maximized"])
    mgr.minimize("chrome")
    check("minimizing a maximized panel clears its maximized flag",
          mgr._panels["chrome"]["maximized"] is False)
    mgr.restore("chrome")
    check("...so restoring it afterwards shows it at its pre-maximize size, not maximized",
          mgr._panels["chrome"].get("hwnd") == chrome_hwnd and
          not mgr._panels["chrome"]["maximized"])

    # ---- shared pill-slot stack actually dispatches through agent_host ----
    mgr.minimize("chrome")
    check("minimize() asked the shared agent_host for a pill slot (not the local fallback)",
          "chrome" in host.get_slot_calls)
    mgr.open("calculator")
    wait_for(lambda: mgr._panels.get("calculator", {}).get("hwnd") is not None)
    mgr.minimize("calculator")
    check("a second minimize also goes through the shared agent_host",
          "calculator" in host.get_slot_calls)
    mgr.restore("chrome")
    check("restoring releases the slot through the shared agent_host",
          "chrome" in host.release_calls)
    check("...and reflows whatever's left still minimized (calculator shifts to slot 0)",
          ("calculator", 0) in host.reposition_calls)

    # ---- fallback still works with no agent_host at all ----
    no_host_mgr = ap.AppPanelManager(launcher=FakeLauncher(),
                                      window_backend=FakeWindowBackend(),
                                      agent_host=None)
    no_host_mgr.open("notepad")
    msg = no_host_mgr.minimize("notepad")
    check("minimize() with no agent_host at all still works (local fallback)",
          "tucked under the circle" in msg or "minimized normally" in msg)
    msg = no_host_mgr.restore("notepad")
    check("...and restore() still works too", "Restored" in msg)

    mgr.close("all")
    no_host_mgr.close("all")


def part_b():
    import agent_tools as at  # noqa: E402

    at.set_circle_rect_provider(lambda: (200, 150, 64))

    # Defensive reset in case an earlier test file in the same run left
    # module-level state behind (each dev_tests/*.py is normally run as
    # its own fresh process, but this keeps part_b() self-contained
    # either way).
    at._MINIMIZED_STACK.clear()
    at._maximized_panel_key = None
    at._ide_opened_at = None

    launcher = FakeLauncher()
    backend = FakeWindowBackend(embed_supported=True, embed_succeeds=True)
    at._panel_manager = ap.AppPanelManager(
        launcher=launcher, window_backend=backend, agent_host=at._AGENT_HOST)

    def ide_pill():
        return at._run_on_main(lambda: getattr(at._ide_app, "_pill", None))

    def ide_pill_y():
        pill = ide_pill()
        return at._run_on_main(pill.winfo_y) if pill is not None else None

    def panel_pill_y(key):
        pill = at._panel_manager._panels[key].get("pill")
        return at._panel_manager._bridge.call(pill.winfo_y) if pill is not None else None

    def ide_bounds():
        return at._run_on_main(lambda: (at._ide_app.winfo_x(), at._ide_app.winfo_y(),
                                         at._ide_app.winfo_width(), at._ide_app.winfo_height()))

    def panel_bounds(key):
        if key == "ide":
            return ide_bounds()
        rec = at._panel_manager._panels[key]
        if rec.get("embedded") and rec.get("frame") is not None:
            frame = rec["frame"]
            return at._panel_manager._bridge.call(
                lambda: (frame.winfo_x(), frame.winfo_y(),
                         frame.winfo_width(), frame.winfo_height()))
        hwnd = rec.get("hwnd")
        return backend.get_window_rect(hwnd) if hwnd is not None else None

    def is_minimized(key):
        if key == "ide":
            return at._run_on_main(lambda: getattr(at._ide_app, "_pill", None) is not None)
        return at._panel_manager._panels[key].get("minimized") is True

    # ================================================================
    # Phase 1 -- the core single-active-panel rule: Friday only ever
    # shows ONE panel on screen at a time. Every panel, the instant it
    # opens, becomes that one panel -- full screen, at the shared
    # reference bounds -- and whatever was active immediately before it
    # (if anything) is automatically minimized to a pill under the
    # circle to make room. There's no side-slot system or 4-panel cap
    # left to reach any more -- opening a 2nd, 3rd, 4th... panel always
    # behaves exactly the same way, regardless of how many are already
    # open.
    # ================================================================
    msg = at.agent_mode_on()
    check("agent_mode_on() opens the IDE (the session's first panel)", "Agent Mode is on" in msg)
    check("opening the IDE stamped an opened_at timestamp", at._ide_opened_at is not None)
    check("the IDE is automatically the maximized/active panel, being first",
          at._maximized_panel_key == "ide")
    check("the IDE's real bounds match the shared reference bounds",
          wait_for(lambda: ide_bounds() == at._ide_reference_bounds(), timeout=8.0))

    msg = at.open_app("chrome")
    check("open_app('chrome') (panel #2) reports minimizing the IDE to make room",
          "Opened Chrome" in msg and "IDE was minimized" in msg)
    check("chrome is now the maximized/active panel", at._maximized_panel_key == "chrome")
    check("chrome's real window was actually moved to the shared reference bounds",
          panel_bounds("chrome") == at._ide_reference_bounds())
    check("the IDE, previously active, is now minimized", wait_for(lambda: is_minimized("ide")))

    msg = at.open_app("notepad")
    check("open_app('notepad') (panel #3) reports minimizing chrome to make room",
          "Opened Notepad" in msg and "Chrome was minimized" in msg)
    check("notepad is now the maximized/active panel", at._maximized_panel_key == "notepad")
    check("notepad's panel was actually placed at the shared reference bounds",
          wait_for(lambda: panel_bounds("notepad") == at._ide_reference_bounds(), timeout=8.0))
    check("chrome, previously active, is now minimized", is_minimized("chrome"))
    check("the IDE is still minimized too -- only one panel is ever visible at once",
          is_minimized("ide"))

    msg = at.open_app("calculator")
    check("open_app('calculator') (panel #4) reports minimizing notepad to make room",
          "Opened Calculator" in msg and "Notepad was minimized" in msg)
    check("calculator is now the maximized/active panel", at._maximized_panel_key == "calculator")
    check("calculator's panel was actually placed at the shared reference bounds",
          wait_for(lambda: panel_bounds("calculator") == at._ide_reference_bounds(), timeout=8.0))

    listing = at.list_open_apps()
    check("only calculator shows as open -- everything else is minimized",
          "Calculator (open" in listing and "Chrome (minimized)" in listing
          and "Notepad (minimized)" in listing and "IDE (minimized)" in listing)

    at.close_app("all")
    time.sleep(0.3)  # let the previous IDE/panel Tk threads fully tear down
    check("everything closed cleanly at the end of phase 1",
          "No panels are open" in at.list_open_apps()
          or "No app panels are open" in at.list_open_apps())
    check("closing everything released the one active-panel slot",
          at._maximized_panel_key is None)

    # ================================================================
    # Phase 2 -- _place_new_or_restored_panel() exercised directly with
    # synthetic panel keys, chained across more panels in a row than
    # Friday's 3 real app types alone could reach through open_app().
    # Confirms the exact same promote-and-minimize-the-previous-one
    # mechanics Phase 1 already exercised indirectly, plus that it
    # always reports the *specific* panel it minimized to make room.
    # ================================================================
    for k in ("fakeA", "fakeB", "fakeC", "fakeD"):
        at._panel_manager._panels[k] = {
            "label": k, "proc": None, "hwnd": None, "frame": None,
            "embedded": False, "custom": False, "minimized": False, "pill": None,
            "opened_at": time.time(), "maximized": False, "pre_maximize_bounds": None,
            "placement_bounds": None}

    bounds, is_max, note = at._place_new_or_restored_panel("fakeA")
    check("the very first synthetic panel becomes active with no eviction note",
          is_max is True and note == "" and at._maximized_panel_key == "fakeA")
    check("...landing at the shared reference bounds", bounds == at._ide_reference_bounds())

    chain = [("fakeA", "fakeB"), ("fakeB", "fakeC"), ("fakeC", "fakeD")]
    for prev, cur in chain:
        bounds, is_max, note = at._place_new_or_restored_panel(cur)
        check(f"'{cur}' becomes the new active panel, still never auto-side-slotted",
              is_max is True and at._maximized_panel_key == cur)
        check(f"...and its own note says '{prev}' specifically was minimized to make room",
              prev.lower() in note.lower() and "minimized" in note.lower())
        check(f"'{prev}' itself is actually flagged minimized now",
              at._panel_manager._panels[prev].get("minimized") is True)
        check(f"'{cur}' lands at the shared reference bounds",
              bounds == at._ide_reference_bounds())

    # cleanup
    for k in ("fakeA", "fakeB", "fakeC", "fakeD"):
        at._release_panel_slot(k)
        at._panel_manager._panels.pop(k, None)
    check("phase 2's synthetic panels left no trace as the active panel",
          at._maximized_panel_key is None)

    # ================================================================
    # Phase 3 -- the unified pill stack: the IDE's own pill and an app
    # panel's pill share one single ordered stack, exactly as before --
    # unaffected by the fact that placement itself no longer has a
    # separate side-slot concept to coordinate with.
    # ================================================================
    # Defensive reset: phase 2's synthetic fakeA/fakeB/fakeC panels
    # above got minimized (not just released from the active slot) on
    # their way to being evicted by the next one in the chain, each
    # claiming a real slot in the shared pill stack that popping them
    # from _panel_manager._panels afterwards never released (that only
    # ever happens for real through restore()/close(), neither of
    # which phase 2 calls -- it's only testing placement, not pill-
    # stack bookkeeping). Clear it before phase 3's own real pill-stack
    # assertions so their leftover entries can't contaminate it.
    at._MINIMIZED_STACK.clear()

    at.agent_mode_on()
    at.open_app("chrome")
    check("opening chrome minimized the IDE into the shared stack, slot 0",
          wait_for(lambda: at._MINIMIZED_STACK == ["ide"]))
    check("the IDE's pill widget actually appears once its minimize animation finishes",
          wait_for(lambda: ide_pill() is not None))
    ide_y0 = ide_pill_y()

    at.open_app("notepad")
    check("opening notepad minimized chrome into the shared stack too, slot 1",
          wait_for(lambda: at._MINIMIZED_STACK == ["ide", "chrome"]))
    chrome_y1 = wait_for(lambda: panel_pill_y("chrome") is not None and ide_y0 is not None and
                          abs((panel_pill_y("chrome") - ide_y0) - ap.MinimizedPill.STACK_STEP) <= 1)
    check("chrome's pill sits below the IDE's, by exactly one STACK_STEP",
          chrome_y1 and panel_pill_y("chrome") is not None)

    msg = at.restore_app("chrome")
    check("restore_app('chrome') restores it and promotes it to active", "Restored Chrome" in msg)
    check("...minimizing notepad (the panel that *was* active) to make room for it",
          "Notepad was minimized" in msg)
    check("chrome is gone from the shared pill stack after being restored",
          "chrome" not in at._MINIMIZED_STACK)
    check("the IDE's pill stayed right where it was -- restoring chrome never touched it",
          at._MINIMIZED_STACK[0] == "ide" and
          wait_for(lambda: ide_pill_y() == ide_y0))
    check("notepad joined the end of the shared stack instead",
          at._MINIMIZED_STACK == ["ide", "notepad"])
    check("restoring a panel now always promotes it straight to active/maximized -- "
          "there's no smaller, separate 'just restored, not maximized' state left any more",
          at._maximized_panel_key == "chrome"
          and at._panel_manager._panels["chrome"]["maximized"] is True)

    # ----------------------------------------------------------------
    # Regression: minimize_app("all") used to stack the IDE's pill
    # *last* instead of first, even though it's always asked to
    # minimize first -- its minimize is animated (takes a moment to
    # actually land), while app_panels.py's panels minimize instantly,
    # so their synchronous stack-slot claims used to race ahead of the
    # IDE's own (correctly first-requested) one. _minimize_ide_panel()
    # still reserves the IDE's slot synchronously up front specifically
    # to prevent this, unaffected by the placement-policy rewrite.
    # ----------------------------------------------------------------
    at.minimize_app("all")
    check("minimize_app('all') leaves the IDE and notepad right where they already were "
          "(both already minimized) and minimizes chrome (the one active panel) last",
          wait_for(lambda: at._MINIMIZED_STACK == ["ide", "notepad", "chrome"]))
    check("minimizing everything cleared the one active-panel slot",
          at._maximized_panel_key is None)

    # ---- restore_app("all"): restores the single most-recently-
    # minimized panel (chrome, just minimized above) ----
    msg = at.restore_app("all")
    check("restore_app('all') restores the single most-recently-minimized panel",
          "Restored Chrome" in msg)
    check("...making it active again, leaving the IDE and notepad minimized",
          at._maximized_panel_key == "chrome" and at._MINIMIZED_STACK == ["ide", "notepad"])

    # ----------------------------------------------------------------
    # Regression: closing a panel while it's minimized (pill showing)
    # used to leave a stale/ghost entry behind in the shared pill
    # stack forever -- _close_one() released the side-slot ledger but
    # never the separate pill-stack one, and on_ide_closed() had the
    # exact same gap for the IDE's own pill. Still a live regression
    # risk in the new model (nothing about the pill-stack bookkeeping
    # itself changed), so still covered here.
    # ----------------------------------------------------------------
    at.minimize_app("chrome")
    check("chrome is minimized, joining the stack", at._MINIMIZED_STACK == ["ide", "notepad", "chrome"])
    at.close_app("chrome")
    check("closing chrome *while minimized* also releases its pill-stack "
          "slot -- no stale entry left behind", at._MINIMIZED_STACK == ["ide", "notepad"])

    at.restore_app("notepad")
    check("restoring notepad promotes it and minimizes the IDE in turn",
          at._maximized_panel_key == "notepad" and at._MINIMIZED_STACK == ["ide"])
    at.minimize_app("notepad")
    check("notepad minimized too -- nothing active, both in the stack",
          at._maximized_panel_key is None and at._MINIMIZED_STACK == ["ide", "notepad"])
    at.close_app("notepad")
    check("closing notepad *while minimized* also releases its slot cleanly",
          at._MINIMIZED_STACK == ["ide"])

    at.agent_mode_off()
    check("closing the IDE *while minimized* also releases its pill-stack "
          "slot -- no stale entry left behind", at._MINIMIZED_STACK == [])
    at.agent_mode_on()
    at.open_app("chrome")
    at.minimize_app("chrome")
    check("a fresh minimize after those closes claims a clean stack "
          "(no leftover gap from the stale entries above)",
          wait_for(lambda: at._MINIMIZED_STACK == ["ide", "chrome"]))

    at.close_app("all")
    time.sleep(0.3)  # let the previous IDE/panel Tk threads fully tear down

    # ================================================================
    # Phase 4 -- maximize_app(): promotes the target straight to being
    # the one active/visible panel, minimizing whatever was previously
    # active (if anything) in its place -- no more full position
    # *swap* into the promoted panel's old side-slot spot, because
    # there's no side slot left for anything to swap into any more.
    # Still doesn't need the IDE to even be open to do this.
    # ================================================================
    at.open_app("notepad")
    at.open_app("calculator")
    check("Agent Mode is off for this check", not at.is_agent_mode_on())
    msg = at.maximize_app("notepad")
    check("maximize_app works on an app panel with the IDE not open at all",
          "maximized" in msg.lower() or "active" in msg.lower())
    check("...and says calculator (the one that was active) was minimized to make room",
          "Calculator was minimized" in msg)
    check("notepad is now the maximized/active panel", at._maximized_panel_key == "notepad")
    check("notepad's real bounds now match the shared reference 'maximized' bounds",
          wait_for(lambda: panel_bounds("notepad") == at._ide_reference_bounds(), timeout=8.0))
    at.close_app("all")
    time.sleep(0.3)  # let the previous IDE/panel Tk threads fully tear down

    # Now the full promote-and-demote chain, with the IDE back in the mix.
    at.agent_mode_on()           # panel #1 -- active
    at.open_app("notepad")       # panel #2 -- active, IDE minimized
    at.open_app("calculator")    # panel #3 -- active, notepad minimized

    def check_promote(target):
        """maximize_app(target): verifies the promotion itself, and (if
        something else was previously active) that maximize_app's own
        result message names it specifically as the one minimized to
        make room."""
        prev = at._maximized_panel_key
        msg = at.maximize_app(target)
        check(f"maximize_app('{target}') succeeds", "maximized" in msg.lower()
              or "active" in msg.lower())
        check(f"{target} is now the maximized/active panel", at._maximized_panel_key == target)
        check(f"{target}'s real bounds now match the shared reference 'maximized' bounds",
              wait_for(lambda: panel_bounds(target) == at._ide_reference_bounds(), timeout=8.0))
        if prev is not None and prev != target:
            check(f"the previously-active panel ({prev}) is named as minimized to make room",
                  at._label_for(prev).lower() in msg.lower() and "minimized" in msg.lower())
            check(f"...and {prev} is genuinely minimized now", is_minimized(prev))
        return msg

    check_promote("notepad")      # calculator was active -- plain promotion, demotes calculator
    check_promote("calculator")   # demotes notepad
    check_promote("ide")          # demotes calculator

    # ---- restoring a panel always promotes it straight back to active now ----
    at.maximize_app("notepad")
    check("notepad is maximized again for this check", at._maximized_panel_key == "notepad")
    at.minimize_app("notepad")
    check("minimizing the active panel clears the active-panel bookkeeping",
          at._maximized_panel_key is None)
    at.restore_app("notepad")
    check("restoring it afterwards promotes it straight back to active/maximized -- "
          "restore and maximize are the same action now",
          at._maximized_panel_key == "notepad")
    check("...and it's genuinely flagged maximized, not some smaller in-between state",
          at._panel_manager._panels["notepad"]["maximized"] is True)

    # ---- maximize_app refusal/ambiguity/already-maximized cases ----
    msg = at.maximize_app("nonexistent_panel_xyz")
    check("maximize_app on an unknown name says so plainly", "No open app panel matches" in msg)

    at.maximize_app("notepad")
    msg = at.maximize_app("notepad")
    check("maximize_app on the panel that's already maximized says so instead of re-doing work",
          "already" in msg.lower())

    msg = at.close_app("ide")
    check("close_app('ide') turns Agent Mode off for the next check", "Agent Mode is off" in msg)
    msg = at.maximize_app("ide")
    check("maximize_app('ide') refuses cleanly when the IDE isn't open", "isn't open" in msg)

    # ---- white border: the IDE's own window matches every other panel
    # -- checked while it's NOT the active panel (every panel Friday
    # opens becomes active immediately now, so a second panel has to be
    # opened afterwards to demote the IDE back to idle/non-active first,
    # for a meaningful "idle" border reading) ----
    at.agent_mode_on()
    at.open_app("notepad")
    wait_for(lambda: at._run_on_main(lambda: getattr(at._ide_app, "_pill", None) is not None))
    ide_bg = at._run_on_main(lambda: at._ide_app.cget("bg"))
    ide_hl = at._run_on_main(lambda: at._ide_app.cget("highlightbackground"))
    check("the IDE's own window background is the same white border color",
          ide_bg.lower() == "#ffffff")
    check("the IDE's own window outline is white now that it's idle (minimized, not active), "
          "matching every app panel",
          ide_hl.lower() == "#ffffff")

    # ---- cleanup ----
    at.close_app("ide")
    at.close_app("all")
    check("everything is closed at the end of this test",
          "No panels are open" in at.list_open_apps()
          or "No app panels are open" in at.list_open_apps())


def part_c():
    """Task 47's two follow-up asks, updated for Task 48's removal of
    the side-slot system:

      - the default small-panel size shrunk to ~258x124 (the exact
        pixel size of the user's own reference screenshot), down from
        the original 480x360 -- still used verbatim today by the
        standalone/no-agent-host fallback path (EmbeddedAppPanel's own
        corner-rotation default, exercised with no agent_host at all
        below), even though the real agent-hosted system no longer has
        a "side slot" of that size for a panel to land in -- every
        panel that's actually open (agent_host wired up) now opens
        straight to full screen instead, per Task 48;
      - every panel type (not just the IDE) supports a pulsing "this is
        Friday's current active panel" violet border animation, shown
        on whichever single panel is Friday's one active panel right
        now, and nowhere else -- see ide.py's _ActiveGlowAnimator and
        IDEApp/EmbeddedAppPanel/CustomNotepadPanel's own
        set_active_panel() methods, all coordinated centrally through
        agent_tools._apply_active_panel_flag every time
        _maximized_panel_key changes (every open/restore/maximize now,
        not just the session's first panel or an explicit swap).
    """
    import agent_tools as at  # noqa: E402

    at.set_circle_rect_provider(lambda: (200, 150, 64))
    at._MINIMIZED_STACK.clear()
    at._maximized_panel_key = None
    at._ide_opened_at = None

    launcher = FakeLauncher()
    backend = FakeWindowBackend(embed_supported=True, embed_succeeds=True)
    at._panel_manager = ap.AppPanelManager(
        launcher=launcher, window_backend=backend, agent_host=at._AGENT_HOST)

    def is_active(key):
        if key == "ide":
            return at._run_on_main(lambda: at._ide_app._is_active_panel)
        frame = at._panel_manager._panels[key]["frame"]
        return at._panel_manager._bridge.call(lambda: frame._is_active_panel)

    def glow_running(key):
        if key == "ide":
            return at._run_on_main(lambda: at._ide_app._active_glow.running)
        frame = at._panel_manager._panels[key]["frame"]
        return at._panel_manager._bridge.call(lambda: frame._active_glow.running)

    def border_bg(key):
        if key == "ide":
            return at._run_on_main(lambda: at._ide_app.cget("bg"))
        frame = at._panel_manager._panels[key]["frame"]
        return at._panel_manager._bridge.call(lambda: frame.cget("bg"))

    # ---- issue #2: default small-panel size (still a real, tested
    # mechanism -- just no longer reachable through a normal, agent-
    # hosted open_app() now that every panel opens full screen instead;
    # exercised here the same way it's actually still reached in
    # practice, the standalone/no-agent-host fallback path) ----
    check("EmbeddedAppPanel's default size still matches the reference "
          "screenshot (258x124), down from 480x360",
          ap.EmbeddedAppPanel.DEFAULT_W == 258 and ap.EmbeddedAppPanel.DEFAULT_H == 124)
    check("CustomNotepadPanel's default size follows the same shrink "
          "(it reuses EmbeddedAppPanel's own constants)",
          ap.CustomNotepadPanel.DEFAULT_W == 258 and ap.CustomNotepadPanel.DEFAULT_H == 124)

    no_host_mgr = ap.AppPanelManager(
        launcher=FakeLauncher(),
        window_backend=FakeWindowBackend(embed_supported=True, embed_succeeds=True),
        agent_host=None)
    no_host_mgr.open("notepad")

    def _standalone_notepad_size():
        frame = no_host_mgr._panels["notepad"]["frame"]
        def _sz():
            frame.update_idletasks()
            return (frame.winfo_width(), frame.winfo_height())
        return no_host_mgr._bridge.call(_sz)
    check("with no agent_host wired up at all (the standalone fallback), "
          "a fresh panel still opens at the small 258x124 default size",
          wait_for(lambda: _standalone_notepad_size() == (258, 124)))
    no_host_mgr.close("all")

    # ---- issue #3: active-panel border, now driven by the single-
    # active-panel model instead of the old maximized/side-slot one ----
    at.agent_mode_on()
    at.open_app("notepad")   # panel #2 -- becomes active, minimizes the IDE
    check("notepad (the just-opened panel) is flagged active", wait_for(lambda: is_active("notepad")))
    check("...with its pulse animation actually running", wait_for(lambda: glow_running("notepad")))
    check("the IDE (minimized to make room for it) is NOT flagged active",
          wait_for(lambda: not is_active("ide")))
    check("...and has no pulse animation running", not glow_running("ide"))

    msg = at.maximize_app("ide")
    check("maximize_app('ide') succeeds", "now the maximized" in msg)
    check("the IDE is now flagged active", wait_for(lambda: is_active("ide")))
    check("...with its pulse animation running", wait_for(lambda: glow_running("ide")))
    check("notepad is no longer flagged active (minimized in its place)",
          wait_for(lambda: not is_active("notepad")))
    check("...and its pulse animation stopped", not glow_running("notepad"))
    check("notepad's border is back to plain white now that it's not active",
          wait_for(lambda: border_bg("notepad").lower() == "#ffffff"))

    at.maximize_app("notepad")
    check("swapping back: notepad is active again", wait_for(lambda: is_active("notepad")))
    check("...and the IDE is not", wait_for(lambda: not is_active("ide")))
    check("the IDE's pulse animation stopped and its border is white again",
          not glow_running("ide") and
          at._run_on_main(lambda: at._ide_app.cget("bg")).lower() == "#ffffff")

    at.minimize_app("notepad")
    check("minimizing the active panel clears its active flag too",
          wait_for(lambda: not is_active("notepad")))
    check("...and stops its pulse animation", not glow_running("notepad"))

    at.close_app("all")
    time.sleep(0.3)
    check("everything is closed at the end of part C",
          "No panels are open" in at.list_open_apps()
          or "No app panels are open" in at.list_open_apps())


def main():
    part_a()
    part_b()
    part_c()

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
