"""Proof that Friday's "real app panels" feature (app_panels.py, plus
its wiring into agent_tools.py's open_app/list_open_apps/minimize_app/
restore_app/close_app/type_in_app) works end to end:

  - opening a real app launches it (via an injectable launcher, so this
    never actually spawns a real Chrome/Notepad/Calculator) and tracks
    it as one of Friday's own panels;
  - minimizing one shows a real pill under a fake circle (a real Tk
    Toplevel, on this module's own dedicated panel-host thread) and
    (best-effort) asks an injectable window backend to minimize the
    real window too;
  - restoring/closing reverse that correctly;
  - ambiguous/no-match names refuse to guess;
  - the IDE itself merges into the very same "panel" vocabulary
    (list_open_apps/minimize_app("all")/close_app("ide")) without the
    two subsystems' lifetimes getting tangled together (closing the IDE
    must not touch a separately-tracked Chrome/Notepad, and vice versa).

Part A exercises app_panels.AppPanelManager directly with fakes, no IDE
involved at all. Part B exercises it through agent_tools.py's thin
wrapper tools, with a real (Xvfb) IDE for the merge-with-the-IDE checks
— same DISPLAY=:99 requirement as dev_tests/test_agent_tools_ide.py.
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_panels as ap  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


# --------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------
class FakeProc:
    def __init__(self, pid):
        self.pid = pid
        self.terminated = False
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill_externally(self):
        """Simulate the user closing the real app window by hand."""
        self._alive = False


class FakeLauncher:
    def __init__(self):
        self.calls = []
        self._next_pid = 1000
        self._last_proc = None

    def launch(self, app_key, url=None, file_path=None, content=None):
        self.calls.append((app_key, url, file_path))
        self._next_pid += 1
        self._last_proc = FakeProc(self._next_pid)
        return self._last_proc


class FailingLauncher:
    def launch(self, app_key, url=None, file_path=None, content=None):
        raise OSError("no such executable")


class FakeWindowBackend:
    def __init__(self, close_succeeds=True, embed_supported=False,
                 embed_succeeds=True, hwnd_delay=0.0):
        self.minimized = []
        self.restored = []
        self.closed = []
        self.embeds = []
        self.resizes = []
        self._close_succeeds = close_succeeds
        self._embed_supported = embed_supported
        self._embed_succeeds = embed_succeeds
        self._hwnd_delay = hwnd_delay

    def is_supported(self):
        return self._embed_supported

    def find_hwnd_for_pid(self, pid, timeout=5.0):
        if self._hwnd_delay:
            time.sleep(self._hwnd_delay)
        return 5000 + pid

    def snapshot_top_level_hwnds(self):
        return set()

    def find_hwnd_for_launch(self, pid, title_hint, before_hwnds, timeout=8.0):
        # Fakes a real backend's "find the window that was just
        # launched" job without needing any real windows -- the manager
        # only cares about getting *a* hwnd back (or None), not about
        # how it was found; the real snapshot/title-match logic lives in
        # RealWindowBackend and isn't exercised by these fakes.
        if self._hwnd_delay:
            time.sleep(self._hwnd_delay)
        return 5000 + pid

    def minimize(self, hwnd):
        self.minimized.append(hwnd)
        return True

    def restore(self, hwnd):
        self.restored.append(hwnd)
        return True

    def close(self, hwnd):
        self.closed.append(hwnd)
        return self._close_succeeds

    def embed(self, parent_hwnd, child_hwnd, width, height):
        self.embeds.append((parent_hwnd, child_hwnd, width, height))
        return (self._embed_succeeds, None if self._embed_succeeds else "fake embed failure")

    def resize_embedded(self, child_hwnd, width, height):
        self.resizes.append((child_hwnd, width, height))
        return True


class FakeTyper:
    def __init__(self, avail=True, raise_exc=None):
        self._avail = avail
        self._raise = raise_exc
        self.typed = []

    def available(self):
        return self._avail

    def type_into(self, hwnd, text):
        if self._raise:
            raise self._raise
        self.typed.append((hwnd, text))


class FakeAgentHost:
    def __init__(self, rect=(200, 150, 64)):
        self._rect = rect
        self.spoken = []

    def get_circle_rect(self):
        return self._rect

    def speak_label(self, text):
        self.spoken.append(text)


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.03)
    return predicate()


def part_a():
    # ---- resolve_app_key / known_app_labels ----
    check("resolve_app_key: exact key", ap.resolve_app_key("chrome") == "chrome")
    check("resolve_app_key: alias", ap.resolve_app_key("google chrome") == "chrome")
    check("resolve_app_key: case/whitespace insensitive",
          ap.resolve_app_key("  NOTEPAD  ") == "notepad")
    check("resolve_app_key: calc alias", ap.resolve_app_key("calc") == "calculator")
    check("resolve_app_key: unknown -> None", ap.resolve_app_key("photoshop") is None)
    check("known_app_labels lists all three",
          all(x in ap.known_app_labels() for x in ("Chrome", "Notepad", "Calculator")))

    launcher = FakeLauncher()
    backend = FakeWindowBackend()
    host = FakeAgentHost()
    mgr = ap.AppPanelManager(launcher=launcher, window_backend=backend, agent_host=host)

    # ---- open() unknown app ----
    msg = mgr.open("photoshop")
    check("open() refuses an unknown app", "don't know how to open" in msg)
    check("unknown app isn't tracked", mgr.list_panels() == "No app panels are open right now.")

    # ---- open() chrome ----
    msg = mgr.open("chrome", url="https://example.com")
    check("open() chrome succeeds", "Opened" in msg and "example.com" in msg)
    check("chrome is now tracked", "Chrome (open)" in mgr.list_panels())
    check("launcher actually got called with the url",
          launcher.calls[-1] == ("chrome", "https://example.com", None))

    # ---- re-opening chrome with a url doesn't duplicate the panel ----
    msg2 = mgr.open("chrome", url="https://second.example")
    check("re-opening chrome relaunches with the new url (new tab semantics)",
          "second.example" in msg2)
    check("still only one tracked Chrome panel", mgr.list_panels().count("Chrome") == 1)
    check("launcher was actually called a second time", len(launcher.calls) == 2)

    # ---- open() notepad with content builds Friday's own custom panel
    # immediately -- no external process, no launcher call, no hwnd at
    # all (see CustomNotepadPanel's own docstring for why Notepad moved
    # off the old SetParent-embedding path entirely) ----
    launcher_calls_before = len(launcher.calls)
    msg = mgr.open("notepad", content="hello world")
    check("open() notepad with content succeeds", "Opened Notepad" in msg)
    check("opening notepad never launches any real external process",
          len(launcher.calls) == launcher_calls_before)
    notepad_rec = mgr._panels["notepad"]
    check("notepad has no real OS process or window at all -- it's Friday's own panel",
          notepad_rec.get("proc") is None and notepad_rec.get("hwnd") is None)
    check("the panel manager marks it embedded/custom (reuses the same "
          "minimize/restore/maximize machinery as a real embedded panel)",
          notepad_rec.get("embedded") is True and notepad_rec.get("custom") is True)
    active_text = mgr._bridge.call(lambda: notepad_rec["frame"].get_active_text())
    check("the requested content is actually sitting in the new tab's text widget",
          active_text == "hello world")
    check("new content isn't auto-saved to disk -- stays unsaved until Save/"
          "save_app_file is used",
          mgr._bridge.call(lambda: notepad_rec["frame"]._active_tab["path"]) is None)

    # ---- minimize with no circle available at all ----
    no_circle_mgr = ap.AppPanelManager(launcher=FakeLauncher(),
                                        window_backend=FakeWindowBackend(),
                                        agent_host=None)
    no_circle_mgr.open("calculator")
    msg = no_circle_mgr.minimize("calculator")
    check("minimize without a circle falls back gracefully, doesn't crash",
          "minimized normally" in msg)
    check("it's still marked minimized even without a pill",
          "Calculator (minimized)" in no_circle_mgr.list_panels())

    # ---- minimize with a real circle: a real pill gets created ----
    msg = mgr.minimize("chrome")
    check("minimize() with a circle available succeeds",
          "tucked under the circle" in msg)
    check("chrome shows minimized in the listing", "Chrome (minimized)" in mgr.list_panels())
    check("backend.minimize was actually called", len(backend.minimized) == 1)
    rec = mgr._panels["chrome"]
    pill_exists = wait_for(lambda: rec.get("pill") is not None)
    check("a real pill object was created", pill_exists)
    alive = mgr._bridge.call(rec["pill"].winfo_exists)
    check("that pill is a real, live Tk window", bool(alive))

    # ---- self-deadlock guard: a pill's own click handler runs ON the
    # panel-host's own Tk thread (exactly like a real mouse click would)
    # -- restore() must not try to block-wait for itself. ----
    done = {}

    def _click_on_tk_thread():
        try:
            rec["pill"]._on_click()
            done["ok"] = True
        except Exception as exc:  # noqa: BLE001
            done["exc"] = exc

    mgr._bridge._root.after(0, _click_on_tk_thread)
    finished = wait_for(lambda: bool(done), timeout=3.0)
    check("clicking a pill from its own hosting thread doesn't deadlock", finished)
    check("...and it completed without raising", done.get("ok") is True)
    check("chrome is restored (open again) after that click",
          "Chrome (open)" in mgr.list_panels())
    check("backend.restore was actually called", len(backend.restored) == 1)

    # ---- ambiguous / no-match matching ----
    mgr.open("calculator")
    no_match = mgr.minimize("nonexistent_app_xyz")
    check("minimizing a name matching nothing says so, closes nothing",
          "No open app panel matches" in no_match)
    ambiguous = mgr.minimize("c")  # matches both "chrome" and "calculator"
    check("an ambiguous minimize names the candidates instead of guessing",
          "More than one" in ambiguous and "Chrome" in ambiguous and "Calculator" in ambiguous)
    check("ambiguous minimize actually minimized nothing",
          "Chrome (open)" in mgr.list_panels() and "Calculator (open)" in mgr.list_panels())

    # ---- minimize_all / restore_all across multiple simultaneous panels ----
    msg = mgr.minimize("all")
    check("minimize('all') reports every panel", "Chrome" in msg and "Calculator" in msg
          and "Notepad" in msg)
    check("everything is actually minimized", mgr.list_panels().count("(minimized)") == 3)
    msg = mgr.minimize("all")
    check("minimizing again when already all-minimized is a clean no-op message",
          "already minimized" in msg)
    msg = mgr.restore("all")
    check("restore('all') brings everything back", mgr.list_panels().count("(open)") == 3)

    # ---- close ----
    closed_count_before = len(backend.closed)
    notepad_frame_ref = mgr._panels["notepad"]["frame"]
    msg = mgr.close("notepad")
    check("close() reports success", "Closed Notepad" in msg)
    check("notepad is no longer tracked", "Notepad" not in mgr.list_panels())
    check("closing Friday's own built-in notepad needs no backend window-close "
          "call at all -- there's no foreign window to ask",
          len(backend.closed) == closed_count_before)
    check("its custom panel frame was actually destroyed",
          not mgr._bridge.call(notepad_frame_ref.winfo_exists))

    # ---- close() falls back to terminate() if the graceful close fails
    # (still exercised against Calculator -- the one remaining app that
    # actually has a real subprocess/hwnd to fall back on) ----
    stubborn_backend = FakeWindowBackend(close_succeeds=False)
    stubborn_launcher = FakeLauncher()
    stubborn_mgr = ap.AppPanelManager(launcher=stubborn_launcher,
                                       window_backend=stubborn_backend,
                                       agent_host=host)
    stubborn_mgr.open("calculator")
    wait_for(lambda: stubborn_mgr._panels["calculator"].get("hwnd") is not None)
    proc = stubborn_launcher._last_proc
    stubborn_mgr.close("calculator")
    check("close() falls back to terminate() when the window won't close nicely",
          proc.terminated)

    # ---- dead-process auto cleanup ----
    cleanup_launcher = FakeLauncher()
    cleanup_mgr = ap.AppPanelManager(launcher=cleanup_launcher,
                                      window_backend=FakeWindowBackend(),
                                      agent_host=host)
    cleanup_mgr.open("calculator")
    cleanup_launcher._last_proc.kill_externally()
    check("a panel whose real process died on its own quietly disappears",
          cleanup_mgr.list_panels() == "No app panels are open right now.")

    # ---- open() failing to launch at all ----
    broken_mgr = ap.AppPanelManager(launcher=FailingLauncher(),
                                     window_backend=FakeWindowBackend(),
                                     agent_host=host)
    msg = broken_mgr.open("chrome")
    check("a launch failure is reported, not raised", "Couldn't open" in msg)
    check("a failed launch isn't tracked as a panel",
          broken_mgr.list_panels() == "No app panels are open right now.")

    # ---- type_text: now routes directly into Friday's own custom
    # Notepad panel -- synchronous, no hwnd/pywinauto involved at all
    # any more (see CustomNotepadPanel.type_text_into_active) ----
    typer_mgr = ap.AppPanelManager(launcher=FakeLauncher(),
                                    window_backend=FakeWindowBackend(),
                                    agent_host=host)
    typer_mgr.open("calculator")
    msg = typer_mgr.type_text("calculator", "2+2")
    check("typing into a non-Notepad app is refused with an explanation",
          "only Notepad supports that" in msg)

    typer_mgr.open("notepad")
    msg = typer_mgr.type_text("notepad", "typed live")
    check("typing into notepad succeeds immediately -- no hwnd/pywinauto "
          "wait needed any more", "Typed that into Notepad" in msg)
    notepad_rec2 = typer_mgr._panels["notepad"]
    check("...and the text actually landed in the active tab",
          typer_mgr._bridge.call(lambda: notepad_rec2["frame"].get_active_text())
          == "typed live")

    msg = typer_mgr.type_text("notepad", " and more")
    check("typing again appends at the cursor rather than overwriting",
          "Typed that into Notepad" in msg)
    check("...confirmed by the tab's actual content",
          typer_mgr._bridge.call(lambda: notepad_rec2["frame"].get_active_text())
          == "typed live and more")

    msg = typer_mgr.type_text("nope_nothing_like_this", "x")
    check("typing into a name matching nothing says so", "No open app panel matches" in msg)

    # ---- embedding: successful embed wraps Calculator in a real frame
    # (Calculator is now the one remaining app that actually uses the
    # real SetParent-based EmbeddedAppPanel path -- Notepad moved to
    # CustomNotepadPanel entirely, see above) ----
    embed_backend = FakeWindowBackend(embed_supported=True, embed_succeeds=True)
    embed_mgr = ap.AppPanelManager(launcher=FakeLauncher(), window_backend=embed_backend,
                                    agent_host=host)
    embed_mgr.open("calculator")
    rec = embed_mgr._panels["calculator"]
    got_frame = wait_for(lambda: rec.get("frame") is not None, timeout=4.0)
    check("a successful embed actually builds a real EmbeddedAppPanel frame", got_frame)
    check("the panel manager marks it embedded", rec.get("embedded") is True)
    check("backend.embed() was actually called", len(embed_backend.embeds) == 1)
    frame_alive = embed_mgr._bridge.call(rec["frame"].winfo_exists)
    check("that frame is a real, live Tk window", bool(frame_alive))
    check("list_panels calls out the embedded panel",
          "embedded in its own panel" in embed_mgr.list_panels())

    # minimizing an embedded panel hides the frame itself, not the backend
    msg = embed_mgr.minimize("calculator")
    check("minimizing an embedded panel succeeds", "Minimized Calculator" in msg)
    check("backend.minimize() is NOT called for an embedded panel",
          len(embed_backend.minimized) == 0)
    frame_state = embed_mgr._bridge.call(rec["frame"].state)
    check("the embedding frame itself is withdrawn on minimize",
          frame_state == "withdrawn")

    msg = embed_mgr.restore("calculator")
    check("restoring an embedded panel succeeds", "Restored Calculator" in msg)
    check("backend.restore() is NOT called for an embedded panel",
          len(embed_backend.restored) == 0)
    frame_state = embed_mgr._bridge.call(rec["frame"].state)
    check("the embedding frame is shown again on restore", frame_state != "withdrawn")

    frame_ref = rec["frame"]
    msg = embed_mgr.close("calculator")
    check("closing an embedded panel reports success", "Closed Calculator" in msg)
    check("embedded panel's frame was actually destroyed on close",
          not embed_mgr._bridge.call(frame_ref.winfo_exists))

    # ---- embedding: Chrome never attempts it, even if embedding would work ----
    chrome_backend = FakeWindowBackend(embed_supported=True, embed_succeeds=True)
    chrome_mgr = ap.AppPanelManager(launcher=FakeLauncher(), window_backend=chrome_backend,
                                     agent_host=host)
    chrome_mgr.open("chrome", url="https://example.com")
    wait_for(lambda: chrome_mgr._panels["chrome"].get("hwnd") is not None)
    time.sleep(0.2)  # give any (wrongful) embed attempt a chance to happen
    check("Chrome is never embedded, by explicit design",
          chrome_mgr._panels["chrome"].get("embedded") is not True)
    check("backend.embed() was never called for Chrome", len(chrome_backend.embeds) == 0)
    check("Chrome has no embedding frame", chrome_mgr._panels["chrome"].get("frame") is None)

    # ---- embedding: a failed embed() falls back to plain (non-embedded) behavior ----
    fail_backend = FakeWindowBackend(embed_supported=True, embed_succeeds=False)
    fail_mgr = ap.AppPanelManager(launcher=FakeLauncher(), window_backend=fail_backend,
                                   agent_host=host)
    fail_mgr.open("calculator")
    wait_for(lambda: fail_mgr._panels["calculator"].get("hwnd") is not None)
    time.sleep(0.2)  # let the (failing) embed attempt finish
    check("backend.embed() was attempted for an embeddable app", len(fail_backend.embeds) == 1)
    check("a failed embed leaves the panel not embedded", not fail_mgr._panels["calculator"].get("embedded"))
    check("a failed embed leaves no stray frame behind", fail_mgr._panels["calculator"].get("frame") is None)
    msg = fail_mgr.minimize("calculator")
    check("after a failed embed, minimize falls back to the plain OS-backend path",
          len(fail_backend.minimized) == 1 and "tucked under the circle" in msg)
    check("a failed embed leaves a human-readable reason visible in list_open_apps",
          "running as its own separate window" in fail_mgr.list_panels())

    # ---- embedding: the window simply can't be found at all (e.g. the
    # real-world bug this was built to fix -- a modern Windows app
    # launched through a stub/App-Execution-Alias whose pid never
    # matches the real window) is reported, not silently dropped ----
    class NoWindowBackend(FakeWindowBackend):
        def find_hwnd_for_launch(self, pid, title_hint, before_hwnds, timeout=8.0):
            return None

    nowin_backend = NoWindowBackend(embed_supported=True, embed_succeeds=True)
    nowin_mgr = ap.AppPanelManager(launcher=FakeLauncher(), window_backend=nowin_backend,
                                    agent_host=host)
    nowin_mgr.open("calculator")
    hwnd_resolved = wait_for(
        lambda: nowin_mgr._panels["calculator"].get("embed_note") is not None, timeout=3.0)
    check("when the real window can never be found, that's recorded instead of "
          "silently doing nothing", hwnd_resolved)
    check("...and it's visible in list_open_apps, not just in internal state",
          "couldn't find its window" in nowin_mgr.list_panels())
    check("backend.embed() was never even attempted without a real hwnd",
          len(nowin_backend.embeds) == 0)
    check("the panel is still otherwise perfectly usable (not embedded, just tracked)",
          "Calculator (open)" in nowin_mgr.list_panels())
    msg = nowin_mgr.close("calculator")
    check("closing a never-found-window panel still works", "Closed Calculator" in msg)

    # ---- embedding: minimize-before-embed-completes race is handled ----
    slow_backend = FakeWindowBackend(embed_supported=True, embed_succeeds=True, hwnd_delay=0.4)
    race_mgr = ap.AppPanelManager(launcher=FakeLauncher(), window_backend=slow_backend,
                                   agent_host=host)
    race_mgr.open("calculator")
    # hwnd discovery (and therefore embedding) is still pending -- minimize
    # right away, before any of that async work has had a chance to land.
    msg = race_mgr.minimize("calculator")
    check("minimizing while embedding is still pending doesn't crash",
          "Minimized Calculator" in msg or "minimized normally" in msg)
    race_rec = race_mgr._panels["calculator"]
    check("the panel is marked minimized immediately, ahead of the embed finishing",
          race_rec.get("minimized") is True)
    got_frame = wait_for(lambda: race_rec.get("frame") is not None, timeout=4.0)
    check("the embed still completes once the real hwnd shows up", got_frame)
    frame_state = race_mgr._bridge.call(race_rec["frame"].state)
    check("...and the newly-built frame respects the already-minimized state "
          "(withdrawn, not shown then hidden)", frame_state == "withdrawn")


def part_b():
    import agent_tools as at  # noqa: E402 (after sys.path insert above)

    # A real circle must be "on screen" for either the IDE's own
    # minimize-to-pill (Task 40) or this feature's external-app pills to
    # do anything beyond a bare OS-level minimize fallback -- register a
    # fake one, same as agent_overlay.py does for real, so the IDE-merge
    # checks below actually exercise the pill path instead of silently
    # falling back.
    at.set_circle_rect_provider(lambda: (200, 150, 64))

    # ---- baseline tool counts: 7 new always-on app-panel tools ----
    check("agent mode starts off", not at.is_agent_mode_on())
    active_off = {f.__name__ for f in at.get_active_gemini_tools()}
    for name in ("open_app", "list_open_apps", "minimize_app", "restore_app",
                 "close_app", "type_in_app"):
        check(f"{name} is active even while Agent Mode is off", name in active_off)
    check("ide_create_file still hidden while off", "ide_create_file" not in active_off)
    check("39 tools active while off (17 original + 7 new memory/task tools + 15 new general-purpose browser_* tools)", len(active_off) == 39)

    # Swap in fakes for the shared singleton -- same spirit as every other
    # dev_tests file reaching into at._ide_app directly; reuses the real
    # _AGENT_HOST so the circle-rect/speak-label plumbing is exercised for
    # real, just the OS process/window parts are faked.
    launcher = FakeLauncher()
    backend = FakeWindowBackend()
    at._panel_manager = ap.AppPanelManager(
        launcher=launcher, window_backend=backend, agent_host=at._AGENT_HOST)

    # ---- before the IDE is open: list_open_apps doesn't mention it ----
    check("open_app('chrome') works through agent_tools",
          "Opened Chrome" in at.open_app("chrome"))
    listing = at.list_open_apps()
    check("list_open_apps shows chrome but no IDE entry before Agent Mode is on",
          "Chrome" in listing and "IDE" not in listing)
    check("chrome, the only panel open so far, is the active one",
          "Chrome (open" in listing)

    # ---- Friday only ever shows one single panel at a time: opening a
    # second one promotes it to active and minimizes whichever one was
    # active before, automatically, to make room (replaces the old
    # "several small side-slot panels share the screen at once" model)
    # ----
    msg = at.open_app("notepad", content="note!")
    check("open_app('notepad', content=...) works", "Opened Notepad" in msg)
    check("...and says chrome was minimized to make room for it",
          "Chrome was minimized" in msg)
    listing = at.list_open_apps()
    check("notepad is now the one active/visible panel, chrome got minimized",
          "Notepad (open" in listing and "Chrome (minimized)" in listing)

    # ---- turn Agent Mode on: the IDE merges into the same listing, and
    # (same single-active-panel rule) becomes the new active one,
    # minimizing notepad in turn ----
    msg = at.agent_mode_on()
    check("agent_mode_on() still works normally", "Agent Mode is on" in msg)
    check("...and says notepad was minimized to make room for it",
          "Notepad was minimized" in msg)
    listing = at.list_open_apps()
    check("list_open_apps now also shows the IDE, as the active panel",
          "IDE (open)" in listing)
    check("...with chrome and notepad both minimized (only one panel is ever visible)",
          "Chrome (minimized)" in listing and "Notepad (minimized)" in listing)

    active_on = {f.__name__ for f in at.get_active_gemini_tools()}
    check("104 tools active while Agent Mode is on (64 original + 12 new IDE "
          "tools + 7 new memory/task tools + 2 new frontend-skill tools + "
          "3 new Build Protocol tools + 15 new general-purpose browser_* tools + "
          "1 new ide_run_act_script tool)",
          len(active_on) == 104)
    for name in ("open_app", "list_open_apps", "minimize_app", "restore_app",
                 "close_app", "type_in_app"):
        check(f"{name} still active while on", name in active_on)

    # ---- minimize_app('all') covers the IDE AND the external apps ----
    # The IDE's own minimize_to_pill() is a short, genuinely-animated
    # shrink-into-the-circle sequence (ide.py's _play_close_animation,
    # ~260ms of .after() ticks on the IDE's own thread) -- it returns
    # from _run_on_main as soon as it's *kicked off*, not once the pill
    # actually exists, so give it a moment the same way
    # dev_tests/test_agent_tools_ide.py's wait_until_tab_appears has to
    # for the create-file typewriter animation.
    def ide_is_minimized():
        try:
            return at._run_on_main(lambda: getattr(at._ide_app, "_pill", None) is not None)
        except Exception:  # noqa: BLE001
            return False

    msg = at.minimize_app("all")
    check("minimize_app('all') mentions the IDE", "IDE" in msg or "Minimized the IDE" in msg)
    wait_for(ide_is_minimized)
    listing = at.list_open_apps()
    check("everything is minimized after minimize_app('all')",
          listing.count("(minimized)") == 3)

    # ---- restore just one named external app: it becomes the new
    # active panel; nothing else needs to move since nothing else was
    # active to begin with (everything was already minimized) ----
    msg = at.restore_app("chrome")
    check("restore_app('chrome') restores just chrome", "Restored Chrome" in msg)
    listing = at.list_open_apps()
    check("chrome is open/active again, notepad and the IDE are still minimized",
          "Chrome (open)" in listing and "Notepad (minimized)" in listing
          and "IDE (minimized)" in listing)

    # ---- restore_app('ide') promotes the IDE to active, minimizing
    # chrome (the previously-active panel) right back down in turn ----
    msg = at.restore_app("ide")
    check("restore_app('ide') targets the IDE specifically", "Restored the IDE" in msg)
    check("...and chrome, previously active, is minimized to make room",
          "Chrome was minimized" in msg)
    wait_for(lambda: not ide_is_minimized())
    listing = at.list_open_apps()
    check("IDE is the active panel again, chrome and notepad are minimized",
          "IDE (open)" in listing and "Chrome (minimized)" in listing
          and "Notepad (minimized)" in listing)

    # ---- restore_app('all'): since at most one panel can ever be
    # visible at once, "restore everything" is reinterpreted as
    # "restore the single most-recently-minimized panel" -- here,
    # that's chrome (it was the one just minimized, immediately above,
    # to make room for the IDE) ----
    msg = at.restore_app("all")
    check("restore_app('all') restores the most-recently-minimized panel (chrome)",
          "Restored Chrome" in msg)
    listing = at.list_open_apps()
    check("...making it the new active panel, minimizing the IDE back down",
          "Chrome (open)" in listing and "IDE (minimized)" in listing
          and "Notepad (minimized)" in listing)

    # ---- type_in_app routes through to the panel manager, straight into
    # Friday's own custom Notepad panel -- no pywinauto/hwnd involved ----
    msg = at.type_in_app("notepad", "more")
    check("type_in_app routes through agent_tools and succeeds immediately",
          "Typed that into Notepad" in msg)

    # ---- save_app_file routes through to the panel manager and writes
    # a real file to disk ----
    scratch_dir = tempfile.mkdtemp(prefix="friday-agent-tools-notepad-")
    try:
        target = os.path.join(scratch_dir, "agent-saved.txt")
        msg = at.save_app_file("notepad", target)
        check("save_app_file routes through agent_tools and reports success",
              "Saved Notepad" in msg and target in msg)
        check("...and the file genuinely exists with the real content in it",
              os.path.isfile(target))
        with open(target, encoding="utf-8") as fh:
            check("...matching exactly what was typed/opened into it",
                  "more" in fh.read())
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    # ---- close_app('ide') only closes the IDE, external apps untouched
    # (the IDE was minimized, not active, going into this -- closing a
    # minimized panel must not disturb whichever one actually is active
    # right now) ----
    msg = at.close_app("ide")
    check("close_app('ide') turns Agent Mode off", "Agent Mode is off" in msg)
    check("is_agent_mode_on() is false again", not at.is_agent_mode_on())
    listing = at.list_open_apps()
    check("chrome/notepad are untouched by closing the IDE",
          "Chrome (open)" in listing and "Notepad (minimized)" in listing
          and "IDE" not in listing)

    # ---- close_app on a specific external app / ambiguous / no-match ----
    msg = at.close_app("notepad")
    check("close_app('notepad') closes just notepad", "Closed Notepad" in msg)
    check("chrome survives", "Chrome (open)" in at.list_open_apps())

    at.open_app("calculator")
    msg = at.minimize_app("nonexistent_panel_xyz")
    check("minimize_app on an unknown name says so plainly, acts on nothing",
          "No open app panel matches" in msg)

    # ---- final cleanup: close everything left open ----
    msg = at.close_app("all")
    check("close_app('all') closes every remaining external app",
          "No app panels are open right now" in at.list_open_apps()
          or at.list_open_apps() == "No panels are open right now — nothing to list.")

    active_after = {f.__name__ for f in at.get_active_gemini_tools()}
    check("back to 39 tools after closing everything (17 original + 7 new memory/task tools + 15 new general-purpose browser_* tools)", len(active_after) == 39)


def part_c():
    """RealWindowBackend's platform-independent pieces: the ctypes
    prototype-correctness fix from Task 44 (see app_panels.py's own
    docstring on that class). These run on every OS -- not just
    Windows -- since they're plain bit-twiddling/string helpers with
    no actual win32 calls in them, so they're exercised here even
    though the rest of RealWindowBackend only does anything real on
    Windows itself."""
    backend = ap.RealWindowBackend()

    # embed()/minimize()/etc. all stay safe, silent no-ops off Windows
    # -- and embed() specifically now returns an (ok, reason) *pair*,
    # not a bare bool (the breaking-but-necessary signature change this
    # fix made every caller above account for).
    result = backend.embed(123, 456, 480, 360)
    check("embed() returns a 2-tuple even when unsupported (not a bare bool)",
          isinstance(result, tuple) and len(result) == 2)
    ok, reason = result
    check("embed() reports ok=False when not on this (non-Windows) platform",
          ok is False)
    if backend.is_supported():
        check("embed() reports a failure for invalid native window handles",
              ok is False)
        check("a supported platform provides a reason for the failed embed",
              bool(reason))
    else:
        check("embed()'s reason is None (not a fabricated error string) when "
              "it's simply unsupported here",
              reason is None)

    # _to_long_ptr_arg: the actual root-cause fix. On a 64-bit process
    # (every realistic target here) it must be a pure no-op -- the bug
    # was ctypes silently mis-sizing/mis-signing these values with no
    # declared prototype, not that the raw unsigned value was ever
    # itself wrong to pass through on 64-bit.
    import ctypes
    is_64bit = ctypes.sizeof(ctypes.c_void_p) == 8
    ordinary_style = 0x96CA0000  # WS_VISIBLE|WS_CLIPSIBLINGS|WS_CAPTION|... --
    # top bit (0x80000000, WS_POPUP) is set, same as a real top-level
    # window's style commonly is; this is exactly the value class a
    # default-prototyped GetWindowLongPtrW call used to corrupt.
    converted = ap.RealWindowBackend._to_long_ptr_arg(ordinary_style)
    if is_64bit:
        check("_to_long_ptr_arg() is a no-op for a top-bit-set style on 64-bit",
              converted == ordinary_style)
    else:
        check("_to_long_ptr_arg() converts a top-bit-set style to its signed "
              "32-bit form on 32-bit", converted == ordinary_style - 0x100000000)
    small_style = 0x00000010
    check("_to_long_ptr_arg() leaves an ordinary small positive value untouched",
          ap.RealWindowBackend._to_long_ptr_arg(small_style) == small_style)

    # _last_error_text: purely a get_last_error()/FormatError() wrapper,
    # safe to call on any OS (ctypes.get_last_error() always exists;
    # it just won't correspond to a real Win32 error off Windows).
    text = ap.RealWindowBackend._last_error_text()
    check("_last_error_text() returns None or a string, never raises",
          text is None or isinstance(text, str))


def part_d():
    """CustomNotepadPanel: Friday's own fully-native CustomTkinter notepad --
    tabs, a small Markdown-style formatting toolbar, and real save-to-
    disk -- built to retire the fragile SetParent-based real-Notepad
    embedding path for good (see IDE_CAPABILITY_AUDIT.md Part 11).
    There is no foreign window here at all, so none of the ctypes-
    prototype bugs documented in Parts 7/8/10 can recur for Notepad
    specifically ever again, by construction."""
    host = FakeAgentHost()
    import tkinter as tk
    import customtkinter as ctk

    mgr = ap.AppPanelManager(launcher=FakeLauncher(), window_backend=FakeWindowBackend(),
                              agent_host=host)
    tmp_home = tempfile.mkdtemp(prefix="friday-notepad-home-")
    real_base_dir = ap.CustomNotepadPanel.DEFAULT_SAVE_BASE_DIR
    ap.CustomNotepadPanel.DEFAULT_SAVE_BASE_DIR = tmp_home
    try:
        mgr.open("notepad", content="first tab content")
        rec = mgr._panels["notepad"]
        frame = rec["frame"]
        bridge = mgr._bridge
        check("Notepad uses CustomTkinter chrome on a native Tk panel",
              bridge.call(lambda: isinstance(frame, tk.Toplevel) and
                          isinstance(frame._titlebar, ctk.CTkFrame)))
        check("Notepad keeps its native Tk Text editor for editing semantics",
              bridge.call(lambda: isinstance(frame._active_tab["text"], tk.Text)))

        check("a freshly-opened notepad starts with exactly one tab",
              bridge.call(lambda: len(frame._tabs)) == 1)

        # ---- new_tab() actually adds a real second tab and switches to it ----
        bridge.call(lambda: frame.new_tab(content="second tab"))
        check("new_tab() actually adds another tab", bridge.call(lambda: len(frame._tabs)) == 2)
        check("the newly-created tab becomes the active one",
              bridge.call(frame.get_active_text) == "second tab")

        # ---- switching tabs actually swaps the active content ----
        bridge.call(lambda: frame._select_tab(frame._tabs[0]))
        check("selecting the first tab makes it active again",
              bridge.call(frame.get_active_text) == "first tab content")

        # ---- formatting toolbar: Bold/Italic/Strikethrough wrap the selection ----
        def _select_all():
            t = frame._active_tab["text"]
            t.tag_add("sel", "1.0", "end-1c")

        bridge.call(lambda: (_select_all(), frame.apply_bold()))
        check("Bold wraps the selected text in ** markers (plain Markdown, "
              "stays a real .txt)", bridge.call(frame.get_active_text) == "**first tab content**")

        bridge.call(lambda: frame.new_tab(content="plain line"))
        bridge.call(lambda: (_select_all(), frame.apply_italic()))
        check("Italic wraps the selection in _ markers",
              bridge.call(frame.get_active_text) == "_plain line_")

        bridge.call(lambda: frame.new_tab(content="plain line"))
        bridge.call(lambda: (_select_all(), frame.apply_strikethrough()))
        check("Strikethrough wraps the selection in ~~ markers",
              bridge.call(frame.get_active_text) == "~~plain line~~")

        bridge.call(lambda: frame.new_tab(content="a line of text"))
        bridge.call(lambda: frame.toggle_bullet_list())
        check("the bullet-list button prefixes the current line with '- '",
              bridge.call(frame.get_active_text) == "- a line of text")
        bridge.call(lambda: frame.toggle_bullet_list())
        check("toggling it again removes the prefix instead of doubling it",
              bridge.call(frame.get_active_text) == "a line of text")

        bridge.call(lambda: frame.new_tab(content="a heading"))
        bridge.call(lambda: frame._apply_heading("Heading 1"))
        check("the H1 dropdown adds a leading '# ' Markdown heading",
              bridge.call(frame.get_active_text) == "# a heading")
        bridge.call(lambda: frame._apply_heading("Heading 2"))
        check("switching heading level replaces, rather than stacks, the prefix",
              bridge.call(frame.get_active_text) == "## a heading")
        bridge.call(lambda: frame._apply_heading("Body text"))
        check("'Body text' strips the heading prefix back off entirely",
              bridge.call(frame.get_active_text) == "a heading")

        # ---- type_text_into_active: the new type_in_app path ----
        bridge.call(lambda: frame.new_tab(content="hello"))
        bridge.call(lambda: frame.type_text_into_active(" world"))
        check("typing into the active tab appends at the cursor (no pywinauto "
              "needed any more)", bridge.call(frame.get_active_text) == "hello world")

        # ---- dirty tracking ----
        bridge.call(lambda: frame.new_tab(content="untouched"))
        check("a brand new tab isn't marked dirty until actually edited further",
              bridge.call(lambda: frame._active_tab["dirty"]) is False)
        bridge.call(lambda: frame.type_text_into_active("!"))
        check("editing a tab marks it dirty",
              bridge.call(lambda: frame._active_tab["dirty"]) is True)

        # ---- save_app_file: an explicit path is honored exactly ----
        target = os.path.join(tmp_home, "my notes.txt")
        msg = mgr.save_file("notepad", target)
        check("save_app_file saves the active tab's real content to the exact "
              "path given", "Saved Notepad" in msg and target in msg)
        with open(target, encoding="utf-8") as fh:
            saved = fh.read()
        check("the saved file is a real file with the actual tab content in it",
              saved == "untouched!")
        check("the tab is no longer dirty after a successful save",
              bridge.call(lambda: frame._active_tab["dirty"]) is False)
        check("the tab now remembers the path it was saved to (so a later "
              "plain Save reuses it)",
              bridge.call(lambda: frame._active_tab["path"]) == target)

        # ---- save_app_file: no path given yet at all -> a sensible default
        # location is used automatically, not an error ----
        bridge.call(lambda: frame.new_tab(content="auto-saved note"))
        msg = mgr.save_file("notepad", None)
        check("save_app_file with no path still actually saves somewhere "
              "sensible by default", "Saved Notepad" in msg)
        default_path = bridge.call(lambda: frame._active_tab["path"])
        check("...and remembers exactly where it put it",
              bool(default_path) and os.path.isfile(default_path))
        check("...inside the expected default base directory",
              default_path.startswith(os.path.join(tmp_home, "Friday Notes")))
        with open(default_path, encoding="utf-8") as fh:
            check("...with the real content actually in it", fh.read() == "auto-saved note")

        # ---- save_app_file: re-saving with no path reuses the known path ----
        bridge.call(lambda: frame.type_text_into_active(" (edited)"))
        msg = mgr.save_file("notepad", None)
        check("a plain re-save (no path) overwrites the same remembered file, "
              "not a new one", default_path in msg)
        with open(default_path, encoding="utf-8") as fh:
            check("the overwrite actually landed on disk",
                  fh.read() == "auto-saved note (edited)")

        # ---- File > Open equivalent: loading a real file from disk ----
        opened_path = os.path.join(tmp_home, "preexisting.txt")
        with open(opened_path, "w", encoding="utf-8") as fh:
            fh.write("already on disk")
        bridge.call(lambda: frame.open_file_path(opened_path))
        check("opening an existing real file loads its real content into a new tab",
              bridge.call(frame.get_active_text) == "already on disk")
        check("...and remembers that file's path (so Save reuses it, not Save As)",
              bridge.call(lambda: frame._active_tab["path"]) == opened_path)

        # ---- save_app_file against a non-notepad panel is refused plainly ----
        mgr.open("calculator")
        msg = mgr.save_file("calculator", None)
        check("save_app_file on a non-notepad panel is refused with a clear "
              "explanation", "only Notepad supports" in msg)

        # ---- closing the very last tab resets it to blank instead of
        # leaving the panel with zero tabs ----
        while bridge.call(lambda: len(frame._tabs)) > 1:
            bridge.call(lambda: frame.close_tab(frame._tabs[-1]))
        check("exactly one tab is left", bridge.call(lambda: len(frame._tabs)) == 1)
        bridge.call(lambda: frame.close_tab(frame._tabs[0]))
        check("closing the very last tab clears it back to a blank Untitled "
              "tab instead of leaving zero tabs",
              bridge.call(lambda: len(frame._tabs)) == 1
              and bridge.call(frame.get_active_text) == "")

        # ---- maximize/restore use the exact same contract as a real
        # SetParent-embedded panel, with no changes needed anywhere else ----
        check("CustomNotepadPanel starts not maximized", frame.is_maximized is False)
        bridge.call(lambda: frame.maximize_to(5, 6, 700, 500))
        geom = bridge.call(lambda: (frame.winfo_x(), frame.winfo_y(),
                                     frame.winfo_width(), frame.winfo_height()))
        check("maximize_to() resizes/repositions the real Tk window",
              geom == (5, 6, 700, 500))
        check("maximize_to() flags it maximized", frame.is_maximized is True)
        bridge.call(frame.restore_default)
        check("restore_default() clears the maximized flag", frame.is_maximized is False)

        mgr.close("notepad")
        mgr.close("calculator")
    finally:
        ap.CustomNotepadPanel.DEFAULT_SAVE_BASE_DIR = real_base_dir
        shutil.rmtree(tmp_home, ignore_errors=True)


def part_e_shutdown_cleanup():
    manager = ap.AppPanelManager(
        launcher=FakeLauncher(),
        window_backend=FakeWindowBackend(),
        agent_host=None,
    )
    manager.open("notepad")
    host_thread = manager._thread
    check("shutdown test opened a live Tk-hosted panel",
          host_thread is not None and host_thread.is_alive())

    manager.shutdown()
    check("shutdown clears the manager's Tk-backed panel records",
          manager._panels == {})
    check("shutdown stops the dedicated Tk host thread",
          host_thread is not None and not host_thread.is_alive())
    check("shutdown releases its Tk host references",
          manager._root is None and manager._bridge is None and manager._thread is None)


def main():
    part_a()
    part_b()
    part_c()
    part_d()
    part_e_shutdown_cleanup()

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
