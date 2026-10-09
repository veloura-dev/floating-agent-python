"""Regression test for the 2-minute unanswered-pause autonomy rule (Task
59): when Friday pauses to ask about a major decision/external action
(personality.md's existing two-pause-reasons policy) and ends that reply
with the literal control tag {{AWAIT_DECISION}}, a real timer is armed;
if nothing cancels it (a new message on the same surface) before it
elapses, Friday is nudged to proceed on its own and the result is
delivered the normal way for that surface.

Covers:
  1. _extract_await_decision() -- tag detection/stripping, case and
     whitespace tolerance, no false positives on ordinary text.
  2. _PendingDecisionTracker -- arm -> fire after the timeout; cancel
     prevents a fire; re-arming invalidates whatever was pending before
     (generation counter).
  3. The circle's own voice/typed chat path end to end: a reply carrying
     the tag arms CircleOverlay._decision_tracker and the tag itself
     never reaches _show_response/memory; letting the (shortened, for
     this test) timeout elapse with the circle back in STATE_IDLE and no
     new message re-runs the query pipeline with a synthetic
     continuation prompt and speaks/logs whatever comes back; a new real
     query before the timeout cancels it (no synthetic follow-up fires).
  4. The IDE's embedded "Friday AI Chat" panel end to end: the same tag
     arms the shared module-level _ide_chat_decision_tracker, and
     letting it elapse delivers the follow-up via
     agent_tools.notify_ide_chat() rather than an on_done a caller is
     still holding onto.

Requires PySide6 with an offscreen-capable platform plugin:
    QT_QPA_PLATFORM=offscreen python3 dev_tests/test_pending_decision_timeout.py
"""
import os
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QThread, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import agent_overlay as ov  # noqa: E402
import agent_tools as at  # noqa: E402
import memory  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def _pump_until(app, predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _drain_workers(app):
    for worker in list(StubAIWorker.instances):
        try:
            worker.wait(2000)
        except RuntimeError:
            pass
    StubAIWorker.instances = []
    for _ in range(5):
        app.processEvents()


class StubAIWorker(QThread):
    """Same shape as the one in test_friday_voice_confirmation.py --
    captures every AIWorker(...) construction and replies with
    `next_reply` (or raises `next_error`)."""

    succeeded = Signal(str)
    failed = Signal(str)
    calls = []       # [(prompt, ide_scoped), ...]
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


def part_a_tag_extraction():
    print("\n--- Part A: _extract_await_decision() ---")
    clean, pending = ov._extract_await_decision(
        "Should I use SQLite or Postgres for this?\n\n{{AWAIT_DECISION}}")
    check("the tag is detected", pending is True)
    check("the tag itself is removed from the cleaned text",
          "{{" not in clean and "AWAIT_DECISION" not in clean)
    check("the real question text survives untouched",
          clean == "Should I use SQLite or Postgres for this?")

    clean2, pending2 = ov._extract_await_decision(
        "just a normal finished reply, nothing pending")
    check("ordinary text with no tag is left completely untouched",
          clean2 == "just a normal finished reply, nothing pending")
    check("ordinary text with no tag never sets the pending flag",
          pending2 is False)

    _, pending3 = ov._extract_await_decision(
        "weird casing and spacing  {{ await_decision }}  ")
    check("the tag is matched case-insensitively and tolerates internal "
          "whitespace", pending3 is True)

    empty_clean, empty_pending = ov._extract_await_decision("")
    check("empty text is handled without raising and never pending",
          empty_clean == "" and empty_pending is False)

    none_clean, none_pending = ov._extract_await_decision(None)
    check("None is handled without raising and never pending",
          none_clean is None and none_pending is False)


def part_b_tracker():
    print("\n--- Part B: _PendingDecisionTracker ---")
    app = QApplication.instance() or QApplication(sys.argv)

    fired = []
    tracker = ov._PendingDecisionTracker(
        lambda q: fired.append(q), timeout_ms=60)

    tracker.arm("pick a database")
    check("nothing fires before the timeout elapses",
          not _pump_until(app, lambda: bool(fired), timeout=0.02))
    check("it fires with the armed question once the timeout elapses",
          _pump_until(app, lambda: fired == ["pick a database"], timeout=1.0))

    fired.clear()
    tracker.arm("pick a cache layer")
    tracker.cancel()
    time.sleep(0.12)
    app.processEvents()
    check("cancel() before the timeout prevents it from ever firing",
          fired == [])

    fired.clear()
    tracker.arm("first question")
    tracker.arm("second question")
    check("re-arming before the first fires replaces it entirely -- only "
          "the newest question ever fires",
          _pump_until(app, lambda: fired == ["second question"], timeout=1.0))


def part_c_circle_end_to_end():
    print("\n--- Part C: the circle's own voice/typed chat path ---")
    app = QApplication.instance() or QApplication(sys.argv)
    memory.set_memory_dir(tempfile.mkdtemp())
    memory._clear_recent_turns()

    patcher_voice = mock.patch.object(ov, "ENABLE_VOICE_MODE", False)
    patcher_speech = mock.patch.object(ov, "ENABLE_SPEECH", False)
    patcher_voice.start()
    patcher_speech.start()
    overlay = ov.CircleOverlay()
    overlay._decision_tracker._timeout_ms = 60  # real 120s is too slow for a test

    try:
        with mock.patch.object(ov, "AIWorker", StubAIWorker):
            StubAIWorker.calls.clear()
            StubAIWorker.next_reply = (
                "Should I use SQLite or a full Postgres setup here?\n\n"
                "{{AWAIT_DECISION}}")
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            overlay._on_query_submitted("set up a database for this app")
            _pump_until(app, lambda: overlay._state == ov.STATE_RESPONDING)
            check("the pausing reply still gets shown/spoken normally",
                  overlay._last_was_error is False)
            check("the {{AWAIT_DECISION}} tag never leaks into memory",
                  all("AWAIT_DECISION" not in (t or "")
                      for _, t in memory.get_recent_turns()))
            check("the tracker is armed with the cleaned question text",
                  overlay._decision_tracker._question is not None
                  and "AWAIT_DECISION" not in overlay._decision_tracker._question)

            # Finish responding and go back to idle, same as a real
            # pause would once Friday is done "speaking" the question.
            overlay._finish_responding()
            app.processEvents()
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()

            # -- no reply arrives: let the (shortened) timeout elapse.
            StubAIWorker.calls.clear()
            StubAIWorker.next_reply = "Went with SQLite -- simplest fit here."
            check("after the timeout elapses with nobody replying, a "
                  "synthetic continuation query actually runs",
                  _pump_until(app, lambda: len(StubAIWorker.calls) == 1,
                              timeout=1.0))
            prompt, _ = StubAIWorker.calls[0]
            check("the synthetic continuation prompt references the "
                  "original pending question and is clearly labeled as "
                  "a system note, not something the user said",
                  "System note" in prompt and "SQLite" in prompt)
            _drain_workers(app)
            _pump_until(app, lambda: overlay._state in (
                ov.STATE_RESPONDING, ov.STATE_IDLE))
            check("the auto-continuation's own result still gets spoken "
                  "normally like any other reply",
                  overlay._last_was_error is False)

        # -- a new real message before the timeout cancels it: no
        # synthetic follow-up should ever fire.
        with mock.patch.object(ov, "AIWorker", StubAIWorker):
            StubAIWorker.calls.clear()
            StubAIWorker.next_reply = (
                "Pick REST or GraphQL for the API layer?\n\n"
                "{{AWAIT_DECISION}}")
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            overlay._on_query_submitted("build the API layer")
            _pump_until(app, lambda: overlay._state == ov.STATE_RESPONDING)
            overlay._finish_responding()
            app.processEvents()
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            check("the tracker is armed after this second pause too",
                  overlay._decision_tracker._question is not None)

            StubAIWorker.calls.clear()
            StubAIWorker.next_reply = "Went with REST, thanks for confirming."
            overlay._on_query_submitted("let's go with REST")
            check("a real new message cancels the pending pause timer "
                  "immediately", overlay._decision_tracker._question is None)
            _pump_until(app, lambda: len(StubAIWorker.calls) == 1)
            check("that real message is the only AIWorker call that "
                  "ever runs for it -- not also overwritten/duplicated "
                  "by a stale auto-continuation",
                  StubAIWorker.calls == [("let's go with REST", False)])
            _drain_workers(app)
            # Wait past the original (already-cancelled) timeout window
            # to confirm it really never fires a second, unwanted call.
            time.sleep(0.15)
            app.processEvents()
            check("no extra synthetic continuation ever fires after a "
                  "real reply already cancelled it",
                  len(StubAIWorker.calls) == 1)
    finally:
        overlay.close()
        patcher_voice.stop()
        patcher_speech.stop()


def part_d_ide_chat_end_to_end():
    print("\n--- Part D: the IDE's embedded chat panel ---")
    app = QApplication.instance() or QApplication(sys.argv)
    memory.set_memory_dir(tempfile.mkdtemp())
    memory._clear_recent_turns()

    ov._ide_chat_decision_tracker._timeout_ms = 60
    ov._ide_chat_decision_tracker.cancel()  # clean slate between test runs

    notified = []
    at.set_ide_chat_notify_handler(lambda text: notified.append(text))

    # _ide_chat_ask marshals AIWorker construction/start through
    # _on_qt_main_thread(), which is a silent no-op with no real
    # CircleOverlay/main() ever having run (true in this standalone
    # test) -- same setup test_ide_chat_server.py uses to actually
    # exercise that path here.
    ov._main_thread_invoker = ov._MainThreadInvoker()

    with mock.patch.object(ov, "AIWorker", StubAIWorker):
        results = []
        StubAIWorker.calls.clear()
        StubAIWorker.next_reply = (
            "Should this use a JSON file or a tiny SQLite db for "
            "storage?\n\n{{AWAIT_DECISION}}")
        ov._ide_chat_ask("add persistence to this project",
                         lambda ok, text: results.append((ok, text)))
        check("the chat panel's own reply still lands normally",
              _pump_until(app, lambda: len(results) == 1))
        check("the {{AWAIT_DECISION}} tag never reaches the chat bubble "
              "text handed back to the panel",
              "AWAIT_DECISION" not in results[0][1])
        # arm() itself is posted via _on_qt_main_thread() (a queued
        # cross-thread call) from on_ok -- it can land a beat after
        # results/on_done above, which run synchronously on the worker
        # thread that emitted succeeded, so this waits for it rather
        # than checking the instant results appears.
        check("the IDE chat's own tracker is armed with the cleaned "
              "question", _pump_until(
                  app, lambda: ov._ide_chat_decision_tracker._question
                  is not None, timeout=1.0)
              and "AWAIT_DECISION" not in ov._ide_chat_decision_tracker._question)

        # -- let it elapse with no reply typed in the panel.
        StubAIWorker.calls.clear()
        StubAIWorker.next_reply = "Went with SQLite for persistence."
        check("letting the timeout elapse runs a synthetic continuation "
              "through the exact same _ide_chat_ask pipeline",
              _pump_until(app, lambda: len(StubAIWorker.calls) == 1,
                          timeout=1.0))
        prompt, ide_scoped = StubAIWorker.calls[0]
        check("that continuation call is still ide_scoped (never gains "
              "broader tool access just because it's automatic)",
              ide_scoped is True)
        check("it references the original pending question and is "
              "clearly a system note", "System note" in prompt
              and "SQLite" in prompt)
        _drain_workers(app)
        check("the result of the auto-continuation is delivered through "
              "notify_ide_chat (a new, unprompted bubble) rather than "
              "silently vanishing",
              _pump_until(app, lambda: len(notified) == 1))
        check("the delivered text is the clean reply, no leftover tag "
              "or error prefix", notified[0] == "Went with SQLite for persistence.")

    # -- a real message typed into the panel cancels a pending timer.
    with mock.patch.object(ov, "AIWorker", StubAIWorker):
        StubAIWorker.calls.clear()
        StubAIWorker.next_reply = (
            "Light theme or dark theme by default?\n\n{{AWAIT_DECISION}}")
        results2 = []
        ov._ide_chat_ask("add a theme toggle",
                         lambda ok, text: results2.append((ok, text)))
        _pump_until(app, lambda: len(results2) == 1)
        check("tracker armed for this second pause", _pump_until(
            app, lambda: ov._ide_chat_decision_tracker._question is not None,
            timeout=1.0))

        StubAIWorker.calls.clear()
        notified.clear()
        StubAIWorker.next_reply = "Going with dark by default, thanks."
        results3 = []
        ov._ide_chat_ask("let's do dark by default",
                         lambda ok, text: results3.append((ok, text)))
        check("the new real message cancels the pending timer right away",
              ov._ide_chat_decision_tracker._question is None)
        _pump_until(app, lambda: len(results3) == 1)
        _drain_workers(app)
        time.sleep(0.15)
        app.processEvents()
        check("no stray auto-continuation / proactive bubble shows up "
              "after a real reply already cancelled the timer",
              notified == [])

    at.set_ide_chat_notify_handler(None)
    ov._main_thread_invoker = None


def main():
    part_a_tag_extraction()
    part_b_tracker()
    part_c_circle_end_to_end()
    part_d_ide_chat_end_to_end()

    passed = sum(1 for _, ok in CHECKS if ok)
    total = len(CHECKS)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
