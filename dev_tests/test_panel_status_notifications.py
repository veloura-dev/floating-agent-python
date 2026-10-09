"""Regression test for Task 61 -- the minimized-pill status/notification
system: a minimized panel's pill outline turns orange while its work is
paused waiting on the user's permission, green once it's done, and red
on a task-stopping error; a lost-internet error specifically gets
auto-retried once connectivity returns; and the circle proactively
speaks up (naming the panel) whenever any of this happens while that
panel is tucked away as a pill, since there's nothing else on screen to
tell the user.

Covers:
  A. MinimizedPill.set_status() -- outline color per status, safe no-op
     on an unknown status or an already-destroyed pill.
  B. IDEApp.set_panel_status() -- persists across minimize/restore
     cycles; applied immediately to a freshly-built pill; recolors an
     already-shown one live.
  C. AppPanelManager.set_status() -- same two guarantees, for the
     generic app_panels.py side of the shared pill mechanism.
  (Part D -- agent_tools.report_panel_status()/is_panel_minimized()
  against a real agent_mode_on() IDE -- lives in its own file,
  test_panel_status_dispatch.py: mixing a bare main-thread IDEApp(), as
  Parts A/B below do, with agent_tools's dedicated-worker-thread IDE in
  the same process corrupts Tcl's global async-handler state and
  crashes the interpreter outright (confirmed by direct reproduction);
  the rest of this suite keeps the existing convention of one Tk access
  pattern per process, same reason test_ide_minimize_pill.py's bare-
  IDEApp style and test_agent_tools_ide.py's agent_mode_on() style are
  already two separate files rather than one.)
  E. agent_tools.has_internet_connectivity() -- tries the primary host,
     falls back to the secondary, False only if both fail.
  F. agent_overlay._looks_like_connectivity_error() -- direct exception
     types, a wrapped __cause__/__context__ chain, and the text-marker
     fallback; never a false positive on an ordinary error.
  G. The three providers' outer except-alls (_try_gemini/_try_groq/
     _try_mistral) and Groq's explicit APIConnectionError/APITimeoutError
     branch all converge on the one CONNECTIVITY_ERROR_TAG-prefixed
     message shape.
  H. AIWorker.run()'s error-combining logic collapses 2-3 all-
     connectivity failures into one clean message, but still
     concatenates normally when only some of them are connectivity-
     related.
  I. _ConnectivityRetryTracker -- arm -> polls until connectivity is
     True -> resumes exactly once; cancel() stops it; re-arming
     invalidates whatever was pending before.
  J. _ide_chat_ask end to end: a reply pauses for a decision -> "waiting"
     pill status + (when minimized) a proactive announcement naming the
     IDE; a finished reply -> "done"; a connectivity failure -> "error"
     pill status + the retry tracker gets armed + a distinct
     announcement; a non-connectivity failure -> "error" but the retry
     tracker is NOT armed.
  K. CircleOverlay.announce_panel_event/_flush_panel_announcements --
     spoken immediately when idle, queued (not dropped) while busy and
     flushed the next time Idle is reached, logged to memory, and a
     duplicate of the currently-queued text is never queued twice.
  L. The circle's own query path: a connectivity failure arms
     CircleOverlay._connectivity_retry with the original query text,
     and a new real query submission cancels a still-pending one.

Requires PySide6 with an offscreen-capable platform plugin and a real
display (Tkinter, for the ide.py/app_panels.py parts):
    DISPLAY=:99 python3 dev_tests/test_panel_status_notifications.py
"""
import os
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ide"))

import tkinter as tk  # noqa: E402

from PySide6.QtCore import QThread, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import agent_overlay as ov  # noqa: E402
import agent_tools as at  # noqa: E402
import app_panels as ap  # noqa: E402
import memory  # noqa: E402
import ide as ide_mod  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def pump_tk(app, times=40, delay=0.02):
    for _ in range(times):
        try:
            app.update()
        except tk.TclError:
            return
        time.sleep(delay)


def _pump_until(app, predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.03)
    return predicate()


class FakeIdeHost:
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


def pill_outline(pill):
    return pill.canvas.itemcget(pill._pill_shape, "outline")


# -------------------------------------------------------------------------
# Part A: MinimizedPill.set_status()
# -------------------------------------------------------------------------
def part_a_minimized_pill_set_status():
    print("\n--- Part A: MinimizedPill.set_status() ---")
    host = FakeIdeHost()
    app = ide_mod.IDEApp(start_dir=None, agent_controlled=True, agent_host=host)
    pump_tk(app, 10)
    app.minimize_to_pill()
    pump_tk(app)
    pill = app._pill
    check("got a real pill to test against", pill is not None)

    default_outline = pill_outline(pill)
    check("starts out with the plain default ('normal') outline color",
          default_outline == ide_mod.C["border"])

    pill.set_status("waiting")
    check("'waiting' paints the warn (orange) color",
          pill_outline(pill) == ide_mod.C["warn"])

    pill.set_status("done")
    check("'done' paints the success (green) color",
          pill_outline(pill) == ide_mod.C["success"])

    pill.set_status("error")
    check("'error' paints the term_err (red) color",
          pill_outline(pill) == ide_mod.C["term_err"])

    pill.set_status("normal")
    check("'normal' paints back to the plain default border color",
          pill_outline(pill) == ide_mod.C["border"])

    before = pill_outline(pill)
    pill.set_status("not-a-real-status")
    check("an unrecognized status is silently ignored, no change",
          pill_outline(pill) == before)

    pill.destroy()
    pump_tk(app, 5)
    try:
        pill.set_status("done")
        destroyed_ok = True
    except Exception:  # noqa: BLE001
        destroyed_ok = False
    check("calling set_status() after the pill is destroyed never raises",
          destroyed_ok)

    app.destroy()
    pump_tk(app, 5)


# -------------------------------------------------------------------------
# Part B: IDEApp.set_panel_status()
# -------------------------------------------------------------------------
def part_b_ideapp_set_panel_status():
    print("\n--- Part B: IDEApp.set_panel_status() ---")
    host = FakeIdeHost()
    app = ide_mod.IDEApp(start_dir=None, agent_controlled=True, agent_host=host)
    pump_tk(app, 10)

    check("starts out as 'normal' with no pill yet",
          app._panel_status == "normal" and app._pill is None)

    # Set a status while fully maximized (no pill exists at all yet) --
    # must be remembered, not just dropped because there's nothing to
    # paint right now.
    app.set_panel_status("waiting")
    check("set_panel_status() records the status even with no pill up",
          app._panel_status == "waiting")

    app.minimize_to_pill()
    pump_tk(app)
    pill = app._pill
    check("a freshly-built pill immediately reflects the status that was "
          "already set before minimizing",
          pill_outline(pill) == ide_mod.C["warn"])

    # Live recolor while already minimized.
    app.set_panel_status("done")
    check("set_panel_status() recolors an already-shown pill live",
          pill_outline(pill) == ide_mod.C["success"])
    check("the app's own recorded status is updated too",
          app._panel_status == "done")

    # Restore, then minimize again -- status must survive the round trip.
    app.restore_from_pill()
    pump_tk(app)
    check("status is still remembered after restoring (pill gone)",
          app._panel_status == "done" and app._pill is None)

    app.minimize_to_pill()
    pump_tk(app)
    check("re-minimizing shows the same status that survived the cycle",
          pill_outline(app._pill) == ide_mod.C["success"])

    app.destroy()
    pump_tk(app, 5)


# -------------------------------------------------------------------------
# Part C: AppPanelManager.set_status()
# -------------------------------------------------------------------------
class _FakeLauncher:
    def launch(self, app_key, url=None, file_path=None):
        raise AssertionError("notepad is Friday's own built-in panel -- "
                              "should never actually launch a process")


class _FakeWindowBackend:
    def is_supported(self):
        return False

    def find_hwnd_for_pid(self, pid, timeout=5.0):
        return None

    def minimize(self, hwnd):
        pass

    def restore(self, hwnd):
        pass

    def close(self, hwnd):
        return True


class _FakeAppHost:
    def __init__(self, rect=(200, 150, 64)):
        self._rect = rect
        self.spoken = []

    def get_circle_rect(self):
        return self._rect

    def speak_label(self, text):
        self.spoken.append(text)


def part_c_app_panel_manager_set_status():
    print("\n--- Part C: AppPanelManager.set_status() ---")
    mgr = ap.AppPanelManager(launcher=_FakeLauncher(),
                              window_backend=_FakeWindowBackend(),
                              agent_host=_FakeAppHost())
    try:
        mgr.open("notepad", content="hello world")
        check("set_status() on a key with no record at all never raises",
              _safe_call(lambda: mgr.set_status("not-a-real-key", "waiting")))

        mgr.set_status("notepad", "waiting")
        check("status recorded even though notepad isn't minimized yet",
              mgr._panels["notepad"].get("status") == "waiting")

        mgr.minimize("notepad")
        wait_for(lambda: mgr._panels["notepad"].get("pill") is not None)
        pill = mgr._panels["notepad"]["pill"]
        outline = mgr._bridge.call(lambda: pill_outline(pill))
        check("a freshly-built pill immediately reflects the status that "
              "was already set before minimizing",
              outline == ide_mod.C["warn"])

        mgr.set_status("notepad", "error")
        outline2 = mgr._bridge.call(lambda: pill_outline(pill))
        check("set_status() recolors an already-shown pill live",
              outline2 == ide_mod.C["term_err"])

        mgr.restore("notepad")
        wait_for(lambda: mgr._panels["notepad"].get("pill") is None)
        check("status is still remembered after restoring",
              mgr._panels["notepad"].get("status") == "error")

        mgr.minimize("notepad")
        wait_for(lambda: mgr._panels["notepad"].get("pill") is not None)
        pill2 = mgr._panels["notepad"]["pill"]
        outline3 = mgr._bridge.call(lambda: pill_outline(pill2))
        check("re-minimizing shows the same status that survived the cycle",
              outline3 == ide_mod.C["term_err"])
    finally:
        mgr.close("notepad")


def _safe_call(fn):
    try:
        fn()
        return True
    except Exception:  # noqa: BLE001
        return False


# -------------------------------------------------------------------------
# Part E: agent_tools.has_internet_connectivity()
# -------------------------------------------------------------------------
def part_e_has_internet_connectivity():
    print("\n--- Part E: agent_tools.has_internet_connectivity() ---")

    def _ok_first(host, timeout=2.0):
        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        if host[0] == "1.1.1.1":
            return _Ctx()
        raise OSError("should never reach the fallback host")

    with mock.patch.object(at.socket, "create_connection", side_effect=_ok_first):
        check("True when the primary host's connection succeeds",
              at.has_internet_connectivity() is True)

    def _fail_first_ok_second(host, timeout=2.0):
        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        if host[0] == "1.1.1.1":
            raise OSError("primary unreachable")
        return _Ctx()

    with mock.patch.object(at.socket, "create_connection",
                            side_effect=_fail_first_ok_second):
        check("falls back to the secondary host and still returns True",
              at.has_internet_connectivity() is True)

    with mock.patch.object(at.socket, "create_connection",
                            side_effect=OSError("no route")):
        check("False (never raises) when both hosts fail",
              at.has_internet_connectivity() is False)


# -------------------------------------------------------------------------
# Part F: agent_overlay._looks_like_connectivity_error()
# -------------------------------------------------------------------------
def part_f_looks_like_connectivity_error():
    print("\n--- Part F: _looks_like_connectivity_error() ---")
    import socket as _socket

    check("a raw socket.gaierror is classified as connectivity",
          ov._looks_like_connectivity_error(_socket.gaierror("name resolution failed")))
    check("a raw ConnectionError is classified as connectivity",
          ov._looks_like_connectivity_error(ConnectionError("refused")))
    check("a raw TimeoutError is classified as connectivity",
          ov._looks_like_connectivity_error(TimeoutError("timed out")))

    wrapped = RuntimeError("wrapped by an SDK")
    wrapped.__cause__ = _socket.timeout("timed out")
    check("a connectivity error hiding in __cause__ is still found",
          ov._looks_like_connectivity_error(wrapped))

    wrapped2 = RuntimeError("wrapped by an SDK")
    wrapped2.__context__ = ConnectionError("connection refused")
    check("a connectivity error hiding in __context__ is still found",
          ov._looks_like_connectivity_error(wrapped2))

    text_only = Exception("httpx.ConnectError: Failed to establish a new "
                           "connection to api.example.com")
    check("a plain exception with no special type, but connectivity "
          "wording in its text, is still classified via the text-marker "
          "fallback", ov._looks_like_connectivity_error(text_only))

    text_only2 = Exception("[Errno -2] Name or service not known")
    check("'name or service not known' text is classified too",
          ov._looks_like_connectivity_error(text_only2))

    not_connectivity = Exception("401 Unauthorized: invalid API key")
    check("an ordinary auth error is NOT classified as connectivity",
          not ov._looks_like_connectivity_error(not_connectivity))

    not_connectivity2 = ValueError("quota exceeded for this model")
    check("an ordinary quota error is NOT classified as connectivity",
          not ov._looks_like_connectivity_error(not_connectivity2))

    # All three provider SDKs sit on httpx -- a stalled connection that
    # hits AI_REQUEST_TIMEOUT_SECONDS raises one of these, and its str()
    # is often just a bare "timed out" with none of the
    # _CONNECTIVITY_ERROR_MARKERS phrases, so this has to be caught by
    # *type*, not text -- added alongside the AI_REQUEST_TIMEOUT_SECONDS
    # fix itself (a stalled request used to hang forever; now it raises
    # one of these within a bounded time, and this is what routes it to
    # the proper "no internet" message + auto-retry instead of a
    # generic, unhelpful "error: timed out").
    import httpx
    check("httpx.ConnectTimeout (a bare 'timed out' message, no marker "
          "phrase) is still classified as connectivity, by type",
          ov._looks_like_connectivity_error(httpx.ConnectTimeout("timed out")))
    check("httpx.ReadTimeout is classified as connectivity too",
          ov._looks_like_connectivity_error(httpx.ReadTimeout("timed out")))
    check("httpx.ConnectError is classified as connectivity too",
          ov._looks_like_connectivity_error(httpx.ConnectError("boom")))
    wrapped3 = RuntimeError("wrapped by google-genai")
    wrapped3.__cause__ = httpx.ReadTimeout("timed out")
    check("an httpx timeout hiding in __cause__ (how an SDK would "
          "actually surface it) is still found",
          ov._looks_like_connectivity_error(wrapped3))


# -------------------------------------------------------------------------
# Part G: the three providers converge on CONNECTIVITY_ERROR_TAG
# -------------------------------------------------------------------------
def part_g_provider_tagging():
    print("\n--- Part G: provider-level connectivity tagging ---")
    import socket as _socket

    worker = ov.AIWorker("hello", ide_scoped=False)

    with mock.patch.object(ov, "GEMINI_API_KEY", "fake-key"), \
         mock.patch("google.genai.Client",
                    side_effect=_socket.gaierror("name resolution failed")):
        ok, text, err = worker._try_gemini()
        check("_try_gemini()'s outer catch-all tags a raw connectivity "
              "failure with CONNECTIVITY_ERROR_TAG",
              ok is False and ov.CONNECTIVITY_ERROR_TAG in (err or "")
              and "Gemini" in err)

    with mock.patch.object(ov, "MISTRAL_API_KEY", "fake-key"), \
         mock.patch("mistralai.client.Mistral",
                    side_effect=ConnectionError("connection refused")):
        ok, text, err = worker._try_mistral()
        check("_try_mistral()'s outer catch-all tags a raw connectivity "
              "failure with CONNECTIVITY_ERROR_TAG",
              ok is False and ov.CONNECTIVITY_ERROR_TAG in (err or "")
              and "Mistral" in err)

    with mock.patch.object(ov, "GROQ_API_KEY", "fake-key"), \
         mock.patch("groq.Groq", side_effect=TimeoutError("timed out")):
        ok, text, err = worker._try_groq()
        check("_try_groq()'s outer catch-all tags a raw connectivity "
              "failure with CONNECTIVITY_ERROR_TAG",
              ok is False and ov.CONNECTIVITY_ERROR_TAG in (err or "")
              and "Groq" in err)

    import groq
    import httpx
    exc = groq.APIConnectionError(request=httpx.Request("GET", "http://x"))
    msg = ov.AIWorker._groq_friendly_message(exc)
    check("Groq's own explicit APIConnectionError branch now uses the "
          "shared CONNECTIVITY_ERROR_TAG too (converged with the other "
          "two providers, not its own bespoke wording any more)",
          ov.CONNECTIVITY_ERROR_TAG in msg)

    class _FakeMistralConnErr(Exception):
        status_code = None

    msg2 = ov.AIWorker._mistral_friendly_message(
        _FakeMistralConnErr("Failed to establish a new connection"))
    check("Mistral's own friendly-message classifier also recognizes a "
          "statusless connectivity failure via the shared helper",
          ov.CONNECTIVITY_ERROR_TAG in msg2)

    class _FakeMistralAuthErr(Exception):
        status_code = 401

    msg3 = ov.AIWorker._mistral_friendly_message(_FakeMistralAuthErr("bad key"))
    check("an ordinary Mistral auth error is unaffected -- still its own "
          "specific message, not the connectivity one",
          ov.CONNECTIVITY_ERROR_TAG not in msg3 and "key" in msg3.lower())

    # AI_REQUEST_TIMEOUT_SECONDS actually has to reach the real client
    # constructors, not just exist as an unused constant -- confirmed by
    # capturing the real kwargs each one is built with, rather than
    # trusting a side_effect-only mock (which would pass even if the
    # timeout kwarg were silently dropped or misspelled).
    check("AI_REQUEST_TIMEOUT_SECONDS is a sane positive, finite number "
          "of seconds (not left at the SDKs' own default of 'no timeout "
          "at all')", 0 < ov.AI_REQUEST_TIMEOUT_SECONDS < 300)


    captured = {}

    def _fake_genai_client(**kwargs):
        captured["gemini"] = kwargs
        raise RuntimeError("stop here -- only checking how it was built")

    with mock.patch.object(ov, "GEMINI_API_KEY", "fake-key"), \
         mock.patch("google.genai.Client", side_effect=_fake_genai_client):
        worker._try_gemini()
    ho = captured.get("gemini", {}).get("http_options")
    check("genai.Client() is built with an explicit http_options.timeout "
          "(milliseconds) matching AI_REQUEST_TIMEOUT_SECONDS -- not left "
          "at the SDK's own default of None (which means no timeout at "
          "all, i.e. a stalled connection hangs forever)",
          ho is not None and
          getattr(ho, "timeout", None) == int(ov.AI_REQUEST_TIMEOUT_SECONDS * 1000))

    def _fake_groq_client(**kwargs):
        captured["groq"] = kwargs
        raise RuntimeError("stop here -- only checking how it was built")

    with mock.patch.object(ov, "GROQ_API_KEY", "fake-key"), \
         mock.patch("groq.Groq", side_effect=_fake_groq_client):
        worker._try_groq()
    check("groq.Groq() is built with an explicit timeout= matching "
          "AI_REQUEST_TIMEOUT_SECONDS",
          captured.get("groq", {}).get("timeout") == ov.AI_REQUEST_TIMEOUT_SECONDS)

    def _fake_mistral_client(**kwargs):
        captured["mistral"] = kwargs
        raise RuntimeError("stop here -- only checking how it was built")

    with mock.patch.object(ov, "MISTRAL_API_KEY", "fake-key"), \
         mock.patch("mistralai.client.Mistral", side_effect=_fake_mistral_client):
        worker._try_mistral()
    check("Mistral() is built with an explicit timeout_ms matching "
          "AI_REQUEST_TIMEOUT_SECONDS",
          captured.get("mistral", {}).get("timeout_ms") ==
          int(ov.AI_REQUEST_TIMEOUT_SECONDS * 1000))


# -------------------------------------------------------------------------
# Part H: AIWorker.run()'s error-combining logic
# -------------------------------------------------------------------------
def part_h_run_error_collapsing():
    print("\n--- Part H: AIWorker.run() error-combining ---")
    app = QApplication.instance() or QApplication(sys.argv)

    def _make_worker(gemini_err, groq_err, mistral_err):
        w = ov.AIWorker("do something", ide_scoped=False)
        w._load_memory_context = lambda: None
        w._load_environment_context = lambda: None
        w._try_gemini = lambda: (False, None, gemini_err)
        w._try_groq = lambda: (False, None, groq_err)
        w._try_mistral = lambda: (False, None, mistral_err)
        return w

    # Part M's circuit breaker (shared module-level state, by design --
    # that's the whole point of it) means a connectivity failure recorded
    # by one sub-test below would otherwise make run() silently *skip*
    # re-attempting that same provider in the very next sub-test instead
    # of calling the mocked function this test just set up -- reset
    # between each one so every sub-test's provider calls are genuinely
    # exercised, the same reason _reset_agent_tools_state() exists
    # elsewhere in this test suite for other module-level state.
    def _reset_circuit():
        ov._provider_last_connectivity_failure.clear()

    with mock.patch.object(ov, "GEMINI_API_KEY", "fake"):
        tag = ov.CONNECTIVITY_ERROR_TAG
        _reset_circuit()
        w = _make_worker(f"{tag} (Gemini).", f"{tag} (Groq).", f"{tag} (Mistral).")
        failures = []
        w.succeeded.connect(lambda t: failures.append(("ok", t)))
        w.failed.connect(lambda e: failures.append(("fail", e)))
        w.run()
        check("all three failing the same connectivity way collapses "
              "into exactly one clean message",
              len(failures) == 1 and failures[0][0] == "fail"
              and failures[0][1] == tag + " — I'll keep retrying "
              "automatically once it's back.")

        _reset_circuit()
        w2 = _make_worker(f"{tag} (Gemini).", "\u26a0 Groq: all models unavailable.",
                           f"{tag} (Mistral).")
        failures2 = []
        w2.succeeded.connect(lambda t: failures2.append(("ok", t)))
        w2.failed.connect(lambda e: failures2.append(("fail", e)))
        w2.run()
        check("a mix of connectivity and non-connectivity failures is "
              "NOT collapsed -- still concatenated the normal way",
              len(failures2) == 1 and failures2[0][0] == "fail"
              and "Also tried" in failures2[0][1]
              and failures2[0][1].count(tag) == 2)

        _reset_circuit()
        w3 = _make_worker(None, None, "\u26a0 Mistral: all models unavailable.")
        failures3 = []
        w3.succeeded.connect(lambda t: failures3.append(("ok", t)))
        w3.failed.connect(lambda e: failures3.append(("fail", e)))
        w3.run()
        check("a single non-connectivity failure (the other two simply "
              "weren't configured) is surfaced as-is, untouched",
              failures3 == [("fail", "\u26a0 Mistral: all models unavailable.")])
        _reset_circuit()


# -------------------------------------------------------------------------
# Part M: per-provider circuit breaker (skip a just-failed provider
# instead of re-paying its full timeout on every single message)
# -------------------------------------------------------------------------
def part_m_provider_circuit_breaker():
    print("\n--- Part M: per-provider circuit breaker ---")
    app = QApplication.instance() or QApplication(sys.argv)
    tag = ov.CONNECTIVITY_ERROR_TAG

    # run() bails out immediately with "No API key found" before even
    # reaching the circuit-breaker logic if every provider's real
    # env-var key is unset (as it genuinely is in this sandbox) -- same
    # reason Part H's own run()-level tests patch this.
    key_patch = mock.patch.object(ov, "GEMINI_API_KEY", "fake")
    key_patch.start()

    def _reset():
        ov._provider_last_connectivity_failure.clear()

    def _make_worker(try_fns):
        w = ov.AIWorker("do something", ide_scoped=False)
        w._load_memory_context = lambda: None
        w._load_environment_context = lambda: None
        for name, fn in try_fns.items():
            setattr(w, name, fn)
        return w

    def _run(w):
        results = []
        w.succeeded.connect(lambda t: results.append(("ok", t)))
        w.failed.connect(lambda e: results.append(("fail", e)))
        w.run()
        return results

    # 1. Direct unit coverage of the three small helpers themselves.
    _reset()
    check("a provider that never failed is not considered recently "
          "unreachable", not ov._provider_recently_unreachable("Gemini"))
    ov._record_provider_connectivity_failure("Gemini")
    check("recording a connectivity failure makes it recently unreachable",
          ov._provider_recently_unreachable("Gemini"))
    ov._record_provider_recovered("Gemini")
    check("recording a recovery clears it again",
          not ov._provider_recently_unreachable("Gemini"))
    _reset()

    # 2. A provider's FIRST failure always gets a real, full attempt --
    #    the breaker must never pre-emptively skip something that
    #    hasn't actually failed yet.
    calls = {"gemini": 0}

    def _gemini_fails():
        calls["gemini"] += 1
        return False, None, f"{tag} (Gemini)."

    w1 = _make_worker({
        "_try_gemini": _gemini_fails,
        "_try_groq": lambda: (False, None, None),
        "_try_mistral": lambda: (False, None, None),
    })
    _run(w1)
    check("the first call for a provider is always actually attempted, "
          "never skipped", calls["gemini"] == 1)
    check("that real failure records a cooldown for next time",
          ov._provider_recently_unreachable("Gemini"))

    # 3. The VERY NEXT message skips straight past it instead of paying
    #    its full timeout again -- this is the actual fix for "it's slow
    #    on every single message."
    w2 = _make_worker({
        "_try_gemini": _gemini_fails,  # would raise the call count if it ran
        "_try_groq": lambda: (True, "groq answered", None),
        "_try_mistral": lambda: (False, None, None),
    })
    results2 = _run(w2)
    check("the next message does NOT re-attempt the just-failed "
          "provider (its call count stays exactly as it was)",
          calls["gemini"] == 1)
    check("...and falls straight through to the next provider, which "
          "answers normally", results2 == [("ok", "groq answered")])

    # 4. Once the cooldown window has genuinely elapsed, it's given a
    #    real attempt again (never skipped forever).
    ov._provider_last_connectivity_failure["Gemini"] = (
        time.time() - ov.PROVIDER_SKIP_COOLDOWN_SECONDS - 1)
    w3 = _make_worker({
        "_try_gemini": _gemini_fails,
        "_try_groq": lambda: (False, None, None),
        "_try_mistral": lambda: (False, None, None),
    })
    _run(w3)
    check("after the cooldown window elapses, the provider is actually "
          "retried again rather than skipped forever",
          calls["gemini"] == 2)
    _reset()

    # 5. A non-connectivity failure (bad key, quota, etc.) must NOT trip
    #    the breaker -- that's a problem retrying won't fix differently,
    #    and skipping it would just hide a real misconfiguration.
    calls2 = {"gemini": 0}

    def _gemini_bad_key():
        calls2["gemini"] += 1
        return False, None, "🔑 Gemini API key problem."

    w4 = _make_worker({
        "_try_gemini": _gemini_bad_key,
        "_try_groq": lambda: (False, None, None),
        "_try_mistral": lambda: (False, None, None),
    })
    _run(w4)
    check("a non-connectivity failure does not arm the circuit breaker",
          not ov._provider_recently_unreachable("Gemini"))
    w5 = _make_worker({
        "_try_gemini": _gemini_bad_key,
        "_try_groq": lambda: (False, None, None),
        "_try_mistral": lambda: (False, None, None),
    })
    _run(w5)
    check("...so it's attempted again normally next time, not skipped",
          calls2["gemini"] == 2)

    # 6. A real success clears a stale cooldown immediately, rather than
    #    waiting for it to simply time out.
    _reset()
    ov._record_provider_connectivity_failure("Gemini")
    w6 = _make_worker({
        "_try_gemini": lambda: (False, None, None),  # won't be called -- skipped
        "_try_groq": lambda: (True, "groq again", None),
        "_try_mistral": lambda: (False, None, None),
    })
    _run(w6)
    check("still skipped while within the cooldown (sanity check before "
          "the recovery test)", ov._provider_recently_unreachable("Gemini"))
    ov._record_provider_recovered("Gemini")
    calls3 = {"gemini": 0}

    def _gemini_ok():
        calls3["gemini"] += 1
        return True, "gemini is back", None

    w7 = _make_worker({
        "_try_gemini": _gemini_ok,
        "_try_groq": lambda: (False, None, None),
        "_try_mistral": lambda: (False, None, None),
    })
    results7 = _run(w7)
    check("once recovered, the provider is tried again immediately "
          "(not left skipped for the rest of the cooldown)",
          calls3["gemini"] == 1 and results7 == [("ok", "gemini is back")])
    _reset()
    key_patch.stop()


# -------------------------------------------------------------------------
# Part I: _ConnectivityRetryTracker
# -------------------------------------------------------------------------
def part_i_connectivity_retry_tracker():
    print("\n--- Part I: _ConnectivityRetryTracker ---")
    app = QApplication.instance() or QApplication(sys.argv)

    resumed = []
    online = {"value": False}
    tracker = ov._ConnectivityRetryTracker(
        lambda text: resumed.append(text), poll_ms=20)

    with mock.patch.object(at, "has_internet_connectivity",
                            lambda timeout=2.0: online["value"]):
        tracker.arm("fix the bug in main.py")
        check("nothing fires while still offline",
              not _pump_until(app, lambda: bool(resumed), timeout=0.15))

        online["value"] = True
        check("resumes with the original text exactly once connectivity "
              "returns",
              _pump_until(app, lambda: resumed == ["fix the bug in main.py"],
                          timeout=1.0))

        online["value"] = False
        resumed.clear()
        tracker.arm("second stalled request")
        tracker.cancel()
        time.sleep(0.1)
        app.processEvents()
        check("cancel() before connectivity returns prevents it from "
              "ever resuming", resumed == [])

        resumed.clear()
        tracker.arm("stale request")
        tracker.arm("newer request")
        online["value"] = True
        check("re-arming before the first resumes replaces it entirely "
              "-- only the newest request ever resumes",
              _pump_until(app, lambda: resumed == ["newer request"], timeout=1.0))


# -------------------------------------------------------------------------
# Part J: _ide_chat_ask end to end
# -------------------------------------------------------------------------
class StubAIWorker(QThread):
    succeeded = Signal(str)
    failed = Signal(str)
    calls = []
    instances = []
    next_reply = "ok"

    def __init__(self, prompt, parent=None, summarize_only=False,
                 ide_scoped=False):
        super().__init__(parent)
        self._prompt = prompt
        StubAIWorker.calls.append((prompt, ide_scoped))
        StubAIWorker.instances.append(self)

    def run(self):
        time.sleep(0.02)
        if isinstance(StubAIWorker.next_reply, Exception):
            self.failed.emit(str(StubAIWorker.next_reply))
        else:
            self.succeeded.emit(StubAIWorker.next_reply)


def _drain_workers(app):
    for worker in list(StubAIWorker.instances):
        try:
            worker.wait(2000)
        except RuntimeError:
            pass
    StubAIWorker.instances = []
    for _ in range(5):
        app.processEvents()


def part_j_ide_chat_ask_status_and_announcements():
    print("\n--- Part J: _ide_chat_ask panel status + announcements ---")
    app = QApplication.instance() or QApplication(sys.argv)
    memory.set_memory_dir(tempfile.mkdtemp())
    memory._clear_recent_turns()

    ov._ide_chat_decision_tracker._timeout_ms = 60
    ov._ide_chat_decision_tracker.cancel()
    ov._ide_chat_connectivity_retry._poll_ms = 30
    ov._ide_chat_connectivity_retry.cancel()
    ov._main_thread_invoker = ov._MainThreadInvoker()

    statuses = []
    announcements = []

    def _fake_report(key, status):
        statuses.append((key, status))

    def _fake_announce(text):
        announcements.append(text)

    minimized = {"value": True}

    try:
        with mock.patch.object(ov, "AIWorker", StubAIWorker), \
             mock.patch.object(at, "report_panel_status", _fake_report), \
             mock.patch.object(at, "is_panel_minimized",
                                lambda key: minimized["value"]), \
             mock.patch.object(ov, "_announce_panel_event", _fake_announce):

            # -- a reply that pauses for a decision -> "waiting" + announced.
            statuses.clear()
            announcements.clear()
            StubAIWorker.calls.clear()
            StubAIWorker.next_reply = (
                "Should I use SQLite or Postgres here?\n\n{{AWAIT_DECISION}}")
            results = []
            ov._ide_chat_ask("set up persistence",
                              lambda ok, text: results.append((ok, text)))
            check("the reply still lands normally",
                  _pump_until(app, lambda: len(results) == 1))
            check("status reported as 'waiting' when the reply pauses "
                  "for a decision", ("ide", "waiting") in statuses)
            check("a proactive announcement fires, naming the IDE and "
                  "asking permission, when the panel is minimized",
                  _pump_until(
                      app, lambda: any("permission" in a for a in announcements),
                      timeout=1.0))

            # -- a finished reply, no pause -> "done" + announced.
            statuses.clear()
            announcements.clear()
            StubAIWorker.next_reply = "All done, persistence is wired up."
            results2 = []
            ov._ide_chat_ask("that's fine, go ahead",
                              lambda ok, text: results2.append((ok, text)))
            check("reply lands", _pump_until(app, lambda: len(results2) == 1))
            check("status reported as 'done' for a finished reply",
                  ("ide", "done") in statuses)
            check("a proactive 'done' announcement fires when minimized",
                  _pump_until(
                      app, lambda: any("done" in a.lower() for a in announcements),
                      timeout=1.0))

            # -- not minimized right now -> no announcement at all, but
            # the pill status is still recorded (so it's correct the
            # instant it IS minimized later).
            minimized["value"] = False
            statuses.clear()
            announcements.clear()
            StubAIWorker.next_reply = "Finished the next bit too."
            results2b = []
            ov._ide_chat_ask("continue",
                              lambda ok, text: results2b.append((ok, text)))
            check("reply lands", _pump_until(app, lambda: len(results2b) == 1))
            time.sleep(0.1)
            app.processEvents()
            check("status is still reported even while NOT minimized",
                  ("ide", "done") in statuses)
            check("but no proactive announcement happens -- nothing to "
                  "narrate, the real window is already visible",
                  announcements == [])
            minimized["value"] = True

            # -- a connectivity failure -> "error" + retry tracker armed
            # + a distinct announcement.
            statuses.clear()
            announcements.clear()
            StubAIWorker.calls.clear()
            StubAIWorker.next_reply = Exception(
                f"{ov.CONNECTIVITY_ERROR_TAG} — I'll keep retrying "
                "automatically once it's back.")
            results3 = []
            ov._ide_chat_ask("add a new feature",
                              lambda ok, text: results3.append((ok, text)))
            check("the failure still lands via on_done",
                  _pump_until(app, lambda: len(results3) == 1))
            check("status reported as 'error' for a connectivity failure",
                  ("ide", "error") in statuses)
            check("the retry tracker actually gets armed for a "
                  "connectivity failure", _pump_until(
                      app, lambda: ov._ide_chat_connectivity_retry._generation > 0,
                      timeout=1.0))
            check("the announcement explicitly calls out the lost "
                  "connection and the automatic retry",
                  _pump_until(
                      app, lambda: any("internet" in a.lower()
                                       for a in announcements), timeout=1.0))

            # Let the armed retry actually fire and confirm it re-runs
            # the exact original request text.
            StubAIWorker.calls.clear()
            StubAIWorker.next_reply = "Added the new feature, all set."
            notified = []
            at.set_ide_chat_notify_handler(lambda text: notified.append(text))
            check("once connectivity 'returns', the stalled request is "
                  "actually retried with its original text",
                  _pump_until(app, lambda: len(StubAIWorker.calls) == 1,
                              timeout=1.0))
            if StubAIWorker.calls:
                check("the retried call carries the exact original "
                      "request text", StubAIWorker.calls[0][0] == "add a new feature")
            _drain_workers(app)
            check("the retried request's eventual success is delivered "
                  "via notify_ide_chat", _pump_until(
                      app, lambda: notified == ["Added the new feature, all set."],
                      timeout=1.0))
            at.set_ide_chat_notify_handler(None)

            # -- a genuine new message resets the pill to 'normal' and
            # cancels any still-pending connectivity retry.
            statuses.clear()
            ov._ide_chat_connectivity_retry.arm("some stale request")
            gen_before = ov._ide_chat_connectivity_retry._generation
            StubAIWorker.next_reply = "Sure, on it."
            results4 = []
            ov._ide_chat_ask("a brand new real message",
                              lambda ok, text: results4.append((ok, text)))
            check("a genuine new message resets the pill status to "
                  "'normal' up front", statuses and statuses[0] == ("ide", "normal"))
            check("a genuine new message also cancels a stale pending "
                  "connectivity retry",
                  ov._ide_chat_connectivity_retry._generation != gen_before)
            _pump_until(app, lambda: len(results4) == 1)

            # -- a non-connectivity failure -> "error" but retry tracker
            # must NOT be armed (nothing to usefully auto-retry).
            ov._ide_chat_connectivity_retry.cancel()
            statuses.clear()
            announcements.clear()
            # Every genuine new message bumps the generation once on its
            # own, via this same function's own top-of-function cancel()
            # (any new real message supersedes whatever was pending) --
            # that happens regardless of whether this particular call
            # goes on to succeed or fail. So "arm() was never additionally
            # called for this non-connectivity failure" is "only +1 from
            # that cancel(), not +2 from cancel() *and* a further arm()".
            gen_before2 = ov._ide_chat_connectivity_retry._generation
            StubAIWorker.next_reply = Exception("\U0001F511 API key problem.")
            results5 = []
            ov._ide_chat_ask("do a thing",
                              lambda ok, text: results5.append((ok, text)))
            check("a non-connectivity failure still lands",
                  _pump_until(app, lambda: len(results5) == 1))
            check("status is still 'error' for honesty",
                  ("ide", "error") in statuses)
            time.sleep(0.1)
            app.processEvents()
            check("but the connectivity retry tracker is NOT armed for a "
                  "non-connectivity failure (retrying a bad key is "
                  "pointless) -- only the one expected bump from this "
                  "call's own top-of-function cancel(), no extra arm()",
                  ov._ide_chat_connectivity_retry._generation == gen_before2 + 1)
            check("the announcement for a non-connectivity error is "
                  "generic, not the internet-specific one",
                  any("problem" in a.lower() for a in announcements)
                  and not any("internet" in a.lower() for a in announcements))
    finally:
        ov._main_thread_invoker = None
        ov._ide_chat_connectivity_retry.cancel()
        ov._ide_chat_decision_tracker.cancel()


# -------------------------------------------------------------------------
# Part K: CircleOverlay.announce_panel_event/_flush_panel_announcements
# -------------------------------------------------------------------------
def part_k_circle_announce_panel_event():
    print("\n--- Part K: CircleOverlay.announce_panel_event() ---")
    app = QApplication.instance() or QApplication(sys.argv)
    memory.set_memory_dir(tempfile.mkdtemp())
    memory._clear_recent_turns()

    patcher_voice = mock.patch.object(ov, "ENABLE_VOICE_MODE", False)
    patcher_speech = mock.patch.object(ov, "ENABLE_SPEECH", False)
    patcher_voice.start()
    patcher_speech.start()
    overlay = ov.CircleOverlay()
    try:
        overlay._enter_state(ov.STATE_IDLE)
        app.processEvents()
        overlay.announce_panel_event("Sir, the IDE is done with its task.")
        check("an announcement made while idle is spoken right away",
              _pump_until(app, lambda: overlay._state in
                          (ov.STATE_RESPONDING, ov.STATE_LISTENING, ov.STATE_IDLE)))
        check("it's logged to memory, just like any other reply",
              any("done with its task" in (t or "")
                  for _, t in memory.get_recent_turns()))

        # Busy right now -- must be queued, not dropped.
        overlay._enter_state(ov.STATE_LOADING)
        app.processEvents()
        overlay.announce_panel_event("Sir, the IDE needs your permission.")
        check("an announcement made while busy is queued, not spoken yet",
              len(overlay._pending_panel_announcements) == 1)

        overlay._enter_state(ov.STATE_RESPONDING)
        app.processEvents()
        check("still queued -- Responding is still 'busy', not idle",
              len(overlay._pending_panel_announcements) == 1)

        overlay._finish_responding()
        app.processEvents()
        time.sleep(0.05)
        app.processEvents()
        # _finish_responding lands in Listening, not Idle, by design --
        # confirm it only actually flushes once Idle is truly reached.
        if overlay._state != ov.STATE_IDLE:
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
        check("the queued announcement is flushed once Idle is actually "
              "reached", _pump_until(
                  app, lambda: overlay._pending_panel_announcements == [],
                  timeout=1.0))

        # Duplicate suppression.
        overlay._enter_state(ov.STATE_LOADING)
        app.processEvents()
        overlay.announce_panel_event("Sir, duplicate check.")
        overlay.announce_panel_event("Sir, duplicate check.")
        check("queuing the exact same text twice in a row doesn't double "
              "it up", len(overlay._pending_panel_announcements) == 1)
        overlay._pending_panel_announcements.clear()
    finally:
        overlay.close()
        patcher_voice.stop()
        patcher_speech.stop()


# -------------------------------------------------------------------------
# Part L: the circle's own connectivity retry wiring
# -------------------------------------------------------------------------
def part_l_circle_connectivity_retry():
    print("\n--- Part L: the circle's own connectivity-retry wiring ---")
    app = QApplication.instance() or QApplication(sys.argv)
    memory.set_memory_dir(tempfile.mkdtemp())
    memory._clear_recent_turns()

    patcher_voice = mock.patch.object(ov, "ENABLE_VOICE_MODE", False)
    patcher_speech = mock.patch.object(ov, "ENABLE_SPEECH", False)
    patcher_voice.start()
    patcher_speech.start()
    overlay = ov.CircleOverlay()
    overlay._connectivity_retry._poll_ms = 30
    try:
        with mock.patch.object(ov, "AIWorker", StubAIWorker):
            StubAIWorker.calls.clear()
            StubAIWorker.next_reply = Exception(ov.CONNECTIVITY_ERROR_TAG)
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            overlay._on_query_submitted("what's on my calendar today")
            _pump_until(app, lambda: overlay._last_was_error is True)
            check("a connectivity failure arms the circle's own retry "
                  "tracker", overlay._connectivity_retry._generation > 0)

            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            StubAIWorker.calls.clear()
            StubAIWorker.next_reply = "You have one meeting at 3pm."
            check("once the tracker fires, the original query is "
                  "actually retried through the normal pipeline",
                  _pump_until(app, lambda: len(StubAIWorker.calls) == 1,
                              timeout=1.0))
            if StubAIWorker.calls:
                check("the retried call carries the exact original query",
                      StubAIWorker.calls[0] == ("what's on my calendar today", False))
            _drain_workers(app)

        # A new real query cancels a still-pending retry.
        with mock.patch.object(ov, "AIWorker", StubAIWorker):
            StubAIWorker.calls.clear()
            StubAIWorker.next_reply = Exception(ov.CONNECTIVITY_ERROR_TAG)
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            overlay._on_query_submitted("find my notes on project X")
            _pump_until(app, lambda: overlay._last_was_error is True)
            gen_before = overlay._connectivity_retry._generation
            check("retry tracker armed after this second connectivity "
                  "failure", gen_before > 0)

            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            StubAIWorker.calls.clear()
            StubAIWorker.next_reply = "Sure, searching now."
            overlay._on_query_submitted("actually, search for project Y instead")
            check("a genuine new query cancels the stale pending retry",
                  overlay._connectivity_retry._generation != gen_before)
            _pump_until(app, lambda: len(StubAIWorker.calls) == 1)
            _drain_workers(app)
            time.sleep(0.1)
            app.processEvents()
            check("the cancelled retry never separately fires its own "
                  "extra call", len(StubAIWorker.calls) == 1)
    finally:
        overlay.close()
        patcher_voice.stop()
        patcher_speech.stop()


def main():
    part_a_minimized_pill_set_status()
    part_b_ideapp_set_panel_status()
    part_c_app_panel_manager_set_status()
    part_e_has_internet_connectivity()
    part_f_looks_like_connectivity_error()
    part_g_provider_tagging()
    part_h_run_error_collapsing()
    part_m_provider_circuit_breaker()
    part_i_connectivity_retry_tracker()
    part_j_ide_chat_ask_status_and_announcements()
    part_k_circle_announce_panel_event()
    part_l_circle_connectivity_retry()

    passed = sum(1 for _, ok in CHECKS if ok)
    total = len(CHECKS)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
