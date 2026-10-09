"""Regression test for agent_overlay.py's _ide_chat_ask() -- the direct,
in-process replacement for the old IDEChatServer socket bridge. The IDE's
embedded "Friday AI Chat" panel now calls this straight (via
agent_tools._AgentHost.ask, itself wired in by
agent_tools.set_chat_handler), with no socket, no second process, no
JSON-line protocol -- just a plain Python function call, but one that
still crosses a real thread boundary: the IDE runs its own dedicated Tk
mainloop() thread, so _ide_chat_ask() executes *there*, not on this
process's Qt GUI thread, whenever the embedded chat panel calls it. A
callback fires once the AIWorker QThread it kicks off finishes, on
AIWorker's own background thread.

AIWorker itself is stubbed out here (no real LLM calls / API quota
spent) -- this test is specifically about the *routing* (does the right
callback fire with the right payload, does it nudge the floating
circle's own state correctly) and, since a real regression was found and
fixed here, the *thread-safety* of that routing: every touch of the
floating circle (a real QWidget) from _ide_chat_ask() must land on the
Qt GUI thread no matter which thread _ide_chat_ask() itself runs on --
see _on_qt_main_thread()'s docstring in agent_overlay.py for the full
story (in short: a QTimer.singleShot() scheduled from a thread with no
Qt event dispatcher of its own silently never fires, which is how the
IDE's chat panel could appear to freeze/never resolve).

Requires PySide6 with an offscreen-capable platform plugin:
    QT_QPA_PLATFORM=offscreen python3 dev_tests/test_ide_chat_server.py
"""
import os
import sys
import threading
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QWidget

import agent_overlay as ov

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


class StubWorkerOK(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, prompt, parent=None, summarize_only=False, ide_scoped=False):
        super().__init__(parent)
        self._prompt = prompt

    def run(self):
        time.sleep(0.1)
        self.succeeded.emit(f"stub reply to: {self._prompt}")


class StubWorkerFail(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, prompt, parent=None, summarize_only=False, ide_scoped=False):
        super().__init__(parent)
        self._prompt = prompt

    def run(self):
        time.sleep(0.1)
        self.failed.emit("stub failure")


class FakeOverlay:
    """A minimal stand-in for CircleOverlay covering just what
    _ide_chat_ask actually touches (_state, _last_was_error, and the two
    state-transition methods) -- a plain duck-typed object, not a real
    QWidget, so it can't by itself catch a cross-thread Qt violation
    (see RealOverlayWidget below, which is what actually proves the
    thread-safety fix works). Still useful here for the plain
    routing/payload checks, where thread-safety isn't what's being
    tested.
    """

    def __init__(self, state):
        self._state = state
        self._last_was_error = False

    def _enter_state(self, state, show_input=True):
        self._state = state

    def _finish_responding(self):
        if self._state == ov.STATE_RESPONDING:
            self._state = ov.STATE_IDLE


class RealOverlayWidget(QWidget):
    """A real QWidget standing in for CircleOverlay, touching exactly the
    kinds of thread-sensitive Qt machinery _enter_state() actually uses
    (a QTimer, a repaint) -- unlike FakeOverlay above, calling this from
    the wrong thread can actually reproduce the real bug (Qt print a
    "Timers cannot be started from another thread" warning, or silently
    drop a QTimer.singleShot() callback forever) rather than just
    recording whatever value was written to a plain attribute."""

    def __init__(self):
        super().__init__()
        self._state = ov.STATE_IDLE
        self._last_was_error = False
        self._timer = QTimer(self)
        self._timer.setInterval(10)
        self.enter_state_threads = []
        self.finish_responding_threads = []

    def _enter_state(self, state, show_input=True):
        self.enter_state_threads.append(threading.current_thread())
        self._state = state
        self._timer.stop()
        self._timer.start()
        self.update()

    def _finish_responding(self):
        self.finish_responding_threads.append(threading.current_thread())
        if self._state == ov.STATE_RESPONDING:
            self._state = ov.STATE_IDLE


def _ask_and_wait(app, text):
    result = {}
    done = threading.Event()

    def on_done(ok, reply):
        result["ok"] = ok
        result["result"] = reply
        done.set()
        # Posted through the same main-thread invoker _settle() itself
        # uses (rather than called directly here on whatever thread
        # on_done happens to run on) so it's strictly ordered *after*
        # any already-queued _apply() from _settle() -- app.exec()
        # stopping is allowed to pre-empt already-queued work otherwise,
        # which would make this test racy rather than deterministic.
        ov._on_qt_main_thread(app.quit)

    ov._ide_chat_ask(text, on_done)
    app.exec()
    done.wait(5)
    return result


def _ask_from_background_thread_and_wait(app, text, settle_wait=2.5):
    """Mirrors how ide.py's ChatSidePanel._send() really calls this --
    from the IDE's own dedicated Tk thread, a real OS thread Qt has
    never heard of -- rather than calling _ide_chat_ask() directly from
    whatever thread is about to run app.exec(). `app.exec()` itself
    still always runs on the real Qt/main thread here, exactly like
    production."""
    result = {}
    done = threading.Event()

    def on_done(ok, reply):
        result["ok"] = ok
        result["result"] = reply
        done.set()

    def _caller_thread():
        ov._ide_chat_ask(text, on_done)
        done.wait(5)
        # Give any main-thread-marshaled follow-up work (the
        # QTimer.singleShot(2000, ...) inside _settle, in particular) a
        # chance to actually run before tearing the loop down.
        time.sleep(settle_wait)
        ov._on_qt_main_thread(app.quit)

    t = threading.Thread(target=_caller_thread)
    t.start()
    app.exec()
    t.join(5)
    return result


def main():
    app = QApplication(sys.argv)
    # Needed now that _ide_chat_ask() marshals every touch of the circle
    # through _on_qt_main_thread() rather than calling it directly --
    # without a live invoker (normally built once in agent_overlay.main())
    # those calls would just silently no-op, same as if no QApplication
    # existed at all.
    ov._main_thread_invoker = ov._MainThreadInvoker()

    with mock.patch.object(ov, "AIWorker", StubWorkerOK):
        ov._circle_overlay = None
        resp = _ask_and_wait(app, "build me a thing")
        check("ok response for a well-formed request", resp.get("ok") is True)
        check("reply text matches the stub worker's answer",
              resp.get("result") == "stub reply to: build me a thing")

    with mock.patch.object(ov, "AIWorker", StubWorkerFail):
        ov._circle_overlay = None
        resp2 = _ask_and_wait(app, "anything")
        check("failed AIWorker surfaces ok=False", resp2.get("ok") is False)
        check("failed AIWorker's error text passed through",
              resp2.get("result") == "stub failure")

    # -- a chat message also nudges an IDLE overlay's own state, so the --
    # -- circle (and the IDE glow it pushes to) visibly reacts to chats --
    # -- typed in the IDE panel, not just voice/typed ones on the circle -
    with mock.patch.object(ov, "AIWorker", StubWorkerOK):
        fake_idle = FakeOverlay(ov.STATE_IDLE)
        ov._circle_overlay = fake_idle
        _ask_and_wait(app, "hi")
        check("a successful chat leaves the overlay un-flagged as error",
              fake_idle._last_was_error is False)
        check("overlay was driven through loading -> responding",
              fake_idle._state == ov.STATE_RESPONDING)

    with mock.patch.object(ov, "AIWorker", StubWorkerFail):
        fake_idle2 = FakeOverlay(ov.STATE_IDLE)
        ov._circle_overlay = fake_idle2
        _ask_and_wait(app, "hi")
        check("a failed chat flags the overlay as error",
              fake_idle2._last_was_error is True)

    with mock.patch.object(ov, "AIWorker", StubWorkerOK):
        # A busy overlay (already mid voice/typed conversation) must be
        # left alone -- an IDE chat must never stomp that in-progress state.
        fake_busy = FakeOverlay(ov.STATE_LOADING)
        ov._circle_overlay = fake_busy
        resp8 = _ask_and_wait(app, "hi")
        check("chat still answers normally even when the overlay is busy",
              resp8.get("ok") is True)
        check("a busy overlay's state is left untouched by an IDE chat",
              fake_busy._state == ov.STATE_LOADING)

    with mock.patch.object(ov, "AIWorker", StubWorkerOK):
        # No circle at all (e.g. mid-shutdown) shouldn't crash the chat.
        ov._circle_overlay = None
        resp9 = _ask_and_wait(app, "hi")
        check("chat still answers normally with no overlay registered",
              resp9.get("ok") is True)

    # -- the actual regression: _ide_chat_ask() called from a real       --
    # -- background thread (standing in for the IDE's own Tk thread),   --
    # -- against a REAL QWidget, must not touch it anywhere but the Qt   --
    # -- main thread, and the circle must actually make it all the way  --
    # -- back to idle on its own (proving the once-dropped              --
    # -- QTimer.singleShot(2000, ...) callback now actually fires).     --
    main_thread = threading.current_thread()
    with mock.patch.object(ov, "AIWorker", StubWorkerOK):
        real_overlay = RealOverlayWidget()
        ov._circle_overlay = real_overlay
        resp10 = _ask_from_background_thread_and_wait(
            app, "hi from the IDE's chat panel")
        check("background-thread chat still answers correctly",
              resp10.get("ok") is True)
        check("_enter_state was actually invoked (not silently skipped)",
              len(real_overlay.enter_state_threads) == 2)
        check("every _enter_state call landed on the real Qt main thread, "
              "never on the calling (Tk-like) background thread",
              all(th is main_thread for th in real_overlay.enter_state_threads))
        check("_finish_responding actually fired on its own, from the "
              "2-second timer (proves the callback isn't silently dropped "
              "when _ide_chat_ask is entered from a foreign thread)",
              len(real_overlay.finish_responding_threads) == 1)
        check("_finish_responding also landed on the real Qt main thread",
              real_overlay.finish_responding_threads
              and real_overlay.finish_responding_threads[0] is main_thread)
        check("the circle made it all the way back to idle by itself",
              real_overlay._state == ov.STATE_IDLE)

    ov._circle_overlay = None  # leave the module in a clean state
    ov._main_thread_invoker = None

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()

