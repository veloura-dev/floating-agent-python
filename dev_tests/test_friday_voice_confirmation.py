"""Regression test for the voice cross-check confirmation feature:

Any spoken request that's either long (>= CONFIRMATION_WORD_THRESHOLD
words) or sounds like it wants Friday to DO something (matches
CONFIRMATION_ACTION_VERBS) gets summarized back as a short yes/no
question first, instead of being acted on immediately -- speech-to-text
can mishear words, and an acted-on mistake is costlier than an
answered-wrong one. Confirming runs the *original, verbatim* request for
real; anything else asks the user to just restate it, no wake word
needed either way. Typed input and short/simple spoken questions are
unaffected.

Covers:
  1. _needs_confirmation() heuristic (word-count trigger, action-verb
     trigger, short questions skip it).
  2. _is_affirmative() matching.
  3. AIWorker(summarize_only=True) wraps the prompt in
     CONFIRMATION_SUMMARY_INSTRUCTION and physically cannot call tools
     (no tools/tool_choice kwargs reach the provider SDK at all).
  4. The full CircleOverlay state-machine flow end to end: a long/action
     voice command triggers the summary call instead of running
     immediately; confirming it runs the original text for real;
     rejecting it asks the user to restate and does NOT get stuck
     re-interpreting the restated command as another confirmation reply
     (the bug this test specifically guards against); a technical
     failure generating the summary falls back to just running the
     request anyway rather than losing it; typed input never goes
     through any of this.

Requires PySide6 with an offscreen-capable platform plugin:
    QT_QPA_PLATFORM=offscreen python3 dev_tests/test_friday_voice_confirmation.py
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
    """Blocks until every StubAIWorker thread started so far has actually
    finished running (not just been constructed), then flushes the Qt
    event loop so any signals they emitted are delivered. Needed between
    test sections: otherwise a still-running thread from one section can
    emit its (queued-connection) signal while the *next* section happens
    to be sitting in STATE_LOADING for an unrelated call, and get
    misread as that call's reply -- a test-harness race, not a real
    agent_overlay.py bug, but it has to be ruled out for the checks below
    to mean anything."""
    for worker in list(StubAIWorker.instances):
        try:
            worker.wait(2000)
        except RuntimeError:
            pass  # already finished and cleaned up (deleteLater already ran)
    StubAIWorker.instances = []
    for _ in range(5):
        app.processEvents()


class StubAIWorker(QThread):
    """Captures every AIWorker(...) construction (prompt + summarize_only)
    so tests can see exactly what was asked for, and replies according to
    `behavior` -- a dict mapping summarize_only (True/False) to either a
    reply string (-> succeeded) or an Exception instance (-> failed)."""

    succeeded = Signal(str)
    failed = Signal(str)
    calls = []  # class-level, reset per test via StubAIWorker.calls.clear()
    instances = []  # every instance constructed since the last drain

    behavior = {True: "Pardon me, sir -- am I to do the thing?", False: "Done."}

    def __init__(self, prompt, parent=None, summarize_only=False):
        super().__init__(parent)
        self._prompt = prompt
        self._summarize_only = summarize_only
        StubAIWorker.calls.append((prompt, summarize_only))
        StubAIWorker.instances.append(self)

    def run(self):
        time.sleep(0.03)
        outcome = StubAIWorker.behavior.get(self._summarize_only, "ok")
        if isinstance(outcome, Exception):
            self.failed.emit(str(outcome))
        else:
            self.succeeded.emit(outcome)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    memory.set_memory_dir(tempfile.mkdtemp())
    memory._clear_recent_turns()

    # ---------------- _needs_confirmation() ------------------------------
    check("a short plain question skips confirmation",
          not ov._needs_confirmation("what's the weather today"))
    check("a short action-ish question still skips confirmation "
          "if it has no action verb and isn't long",
          not ov._needs_confirmation("what time is it"))
    check("a short request with an action verb triggers confirmation "
          "even though it's short",
          ov._needs_confirmation("create a new file"))
    check("a long request triggers confirmation purely on length, even "
          "with no action verb in it",
          ov._needs_confirmation(
              "tell me a very long and detailed story about a dog who "
              "went on an adventure across several different countries"))
    check("the example from the feature request triggers confirmation "
          "(contains 'create')",
          ov._needs_confirmation(
              "let's create an interactive header that responds to "
              "multiple screen sizes and upscales for larger displays"))
    check("empty text never triggers confirmation", not ov._needs_confirmation("  "))

    # ---------------- _is_affirmative() -----------------------------------
    for phrase in ["yes", "Yes!", "yeah", "yep", "that's right", "correct",
                   "go ahead", "do it", "okay", "sure, go ahead"]:
        check(f"_is_affirmative() recognizes {phrase!r}",
              ov._is_affirmative(phrase))
    for phrase in ["no", "nope", "not quite", "that's not it",
                   "actually make it blue instead", ""]:
        check(f"_is_affirmative() correctly rejects {phrase!r}",
              not ov._is_affirmative(phrase))

    # ---------------- AIWorker(summarize_only=True) ------------------------
    worker = ov.AIWorker("create a login page", summarize_only=True)
    check("summarize_only wraps the original command into the "
          "confirmation meta-instruction",
          "create a login page" in worker._prompt
          and "Do NOT perform this request" in worker._prompt)
    check("a normal (summarize_only=False) worker keeps the prompt verbatim",
          ov.AIWorker("create a login page")._prompt == "create a login page")

    # Tools must be physically impossible to reach for a summarize_only
    # call -- not just discouraged by the prompt wording. Patch Gemini's
    # SDK to inspect exactly what GenerateContentConfig(...) was built
    # with.
    fake_types = mock.Mock()
    fake_errors = mock.Mock()
    fake_response = mock.Mock(text="Am I to create a login page?")
    fake_client = mock.Mock()
    fake_client.models.generate_content.return_value = fake_response
    fake_genai = mock.Mock()
    fake_genai.Client.return_value = fake_client
    # `from google.genai import types, errors` resolves via attribute
    # access on the already-imported `google.genai` module object when
    # it's found in sys.modules -- not a second sys.modules lookup for
    # "google.genai.types" -- so these must be wired up explicitly for
    # the fakes below to actually be what agent_overlay.py's code sees.
    fake_genai.types = fake_types
    fake_genai.errors = fake_errors
    captured_config_kwargs = {}

    def _fake_config(**kwargs):
        captured_config_kwargs.update(kwargs)
        return mock.Mock(**kwargs)

    fake_types.GenerateContentConfig.side_effect = _fake_config
    fake_google_pkg = mock.Mock(genai=fake_genai)

    with mock.patch.object(ov, "GEMINI_API_KEY", "fake-key"), \
         mock.patch.dict(sys.modules, {
             "google": fake_google_pkg,
             "google.genai": fake_genai,
             "google.genai.types": fake_types,
             "google.genai.errors": fake_errors,
         }):
        summarize_worker = ov.AIWorker("create a login page", summarize_only=True)
        ok, text, err = summarize_worker._try_gemini()
        check("a summarize_only Gemini call succeeds",
              ok and text == "Am I to create a login page?")
        check("a summarize_only Gemini call never passes 'tools' to "
              "GenerateContentConfig at all -- not even an empty list",
              "tools" not in captured_config_kwargs)

        captured_config_kwargs.clear()
        normal_worker = ov.AIWorker("create a login page")
        normal_worker._try_gemini()
        check("a normal (non-summarize) Gemini call does pass 'tools'",
              "tools" in captured_config_kwargs)

    # ---------------- full state-machine flow -------------------------------
    # Patched for the whole flow below (not just construction) -- several
    # steps exercise _show_response(), which reads ENABLE_SPEECH itself at
    # call time, so the patch has to still be active when that runs.
    patcher_voice = mock.patch.object(ov, "ENABLE_VOICE_MODE", False)
    patcher_speech = mock.patch.object(ov, "ENABLE_SPEECH", False)
    patcher_voice.start()
    patcher_speech.start()
    overlay = ov.CircleOverlay()

    try:
        # -- A: a long/action voice command triggers the cross-check,
        # not an immediate reply.
        StubAIWorker.calls.clear()
        StubAIWorker.behavior = {True: "Am I to create a login page?"}
        with mock.patch.object(ov, "AIWorker", StubAIWorker):
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            overlay._handle_voice_command("create a login page for my app")
            check("a long/action voice command enters Loading for the "
                  "summary call, not Responding with an immediate answer",
                  _pump_until(app, lambda: overlay._state == ov.STATE_LOADING))
            check("exactly one AIWorker was constructed, with "
                  "summarize_only=True and the verbatim original text",
                  StubAIWorker.calls == [("create a login page for my app", True)])

            # Let the summary call land and flow through to the
            # actively-listening-for-yes/no window.
            check("the summary gets spoken/shown and settles into "
                  "Responding", _pump_until(
                      app, lambda: overlay._state == ov.STATE_RESPONDING))
            check("_awaiting_confirmation is now True",
                  overlay._awaiting_confirmation is True)
            check("the original (unparaphrased) text is preserved for "
                  "later, not overwritten by the summary",
                  overlay._pending_confirmation_text ==
                  "create a login page for my app")
            check("the cross-check question itself is logged to memory "
                  "(so the whole conversation is captured, not just the "
                  "eventual acted-on request)",
                  ("friday", "Am I to create a login page?")
                  in memory.get_recent_turns())

            # ENABLE_SPEECH is False, so there's no real audio to wait on --
            # fire the same completion path a finished/safety-netted
            # response always goes through (same technique the existing
            # interrupt/follow-up test uses).
            overlay._finish_responding()
            app.processEvents()
            check("after the question is 'spoken', Friday is actively "
                  "listening for the yes/no with no wake word needed",
                  overlay._state == ov.STATE_LISTENING
                  and overlay._capturing_voice_command is True)

            # -- B: confirming it runs the ORIGINAL verbatim text for
            # real (not the paraphrased summary).
            _drain_workers(app)
            StubAIWorker.calls.clear()
            StubAIWorker.behavior = {False: "Login page created."}
            overlay._on_voice_heard("yes, that's right")
            check("confirming clears _awaiting_confirmation",
                  overlay._awaiting_confirmation is False)
            check("confirming runs a brand new AIWorker with "
                  "summarize_only=False and the untouched original text",
                  _pump_until(app, lambda: StubAIWorker.calls == [
                      ("create a login page for my app", False)]))
            check("the user's spoken 'yes' confirming it is also logged "
                  "to memory, not just the request it triggered",
                  ("user", "yes, that's right") in memory.get_recent_turns())

            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()

        # -- C: rejecting asks the user to restate, and does NOT get
        # stuck forever treating the restated command as another
        # confirmation reply (the exact bug caught and fixed this turn).
        _drain_workers(app)
        StubAIWorker.calls.clear()
        StubAIWorker.behavior = {True: "Am I to delete the build folder?"}
        with mock.patch.object(ov, "AIWorker", StubAIWorker):
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            overlay._handle_voice_command("delete the build folder")
            _pump_until(app, lambda: overlay._state == ov.STATE_RESPONDING)
            check("_awaiting_confirmation set for the rejection scenario too",
                  overlay._awaiting_confirmation is True)
            overlay._finish_responding()
            app.processEvents()

            _drain_workers(app)
            StubAIWorker.calls.clear()
            overlay._on_voice_heard("no, don't do that")
            check("rejecting clears _awaiting_confirmation",
                  overlay._awaiting_confirmation is False)
            check("rejecting clears the pending original text",
                  overlay._pending_confirmation_text is None)
            check("the user's spoken rejection is logged to memory too",
                  ("user", "no, don't do that") in memory.get_recent_turns())
            check("rejecting speaks/shows the restate-it message instead "
                  "of running anything",
                  _pump_until(
                      app, lambda: overlay._state == ov.STATE_RESPONDING)
                  and len(StubAIWorker.calls) == 0)
            overlay._finish_responding()
            app.processEvents()
            check("after being asked to restate, Friday is listening again",
                  overlay._state == ov.STATE_LISTENING
                  and overlay._capturing_voice_command is True)
            check("the 'go ahead and say that again' reply is logged too "
                  "-- the whole rejected-confirmation exchange is captured",
                  ("friday", "My mistake — go ahead and say that again.")
                  in memory.get_recent_turns())

            # The critical regression check: the restated (short, plain)
            # command must be treated as a brand new command, not
            # mistaken for a second confirmation reply.
            _drain_workers(app)
            StubAIWorker.calls.clear()
            overlay._on_voice_heard("what time is it")
            check("the restated command is handled as a fresh request "
                  "(answered directly, short question, no action verb) "
                  "-- not swallowed as another rejected confirmation",
                  _pump_until(app, lambda: StubAIWorker.calls == [
                      ("what time is it", False)]))
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()

        # -- D: a technical failure generating the summary falls back to
        # just running the request for real, rather than losing it.
        _drain_workers(app)
        StubAIWorker.calls.clear()
        StubAIWorker.behavior = {True: RuntimeError("provider hiccup")}
        with mock.patch.object(ov, "AIWorker", StubAIWorker):
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            overlay._handle_voice_command("install the dependencies")
            check("a failed summary call still runs the original request "
                  "for real instead of silently dropping it",
                  _pump_until(app, lambda: any(
                      call == ("install the dependencies", False)
                      for call in StubAIWorker.calls)))
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()

        # -- E: an empty/blank summary also falls back to running for real.
        _drain_workers(app)
        StubAIWorker.calls.clear()
        StubAIWorker.behavior = {True: "   "}
        with mock.patch.object(ov, "AIWorker", StubAIWorker):
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            overlay._handle_voice_command("set up the database")
            check("a blank summary also falls back to running the "
                  "original request for real",
                  _pump_until(app, lambda: any(
                      call == ("set up the database", False)
                      for call in StubAIWorker.calls)))
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()

        # -- F: short, simple voice questions are entirely unaffected --
        # answered immediately, no confirmation step at all.
        _drain_workers(app)
        StubAIWorker.calls.clear()
        StubAIWorker.behavior = {False: "It's sunny."}
        with mock.patch.object(ov, "AIWorker", StubAIWorker):
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            overlay._handle_voice_command("what's the weather")
            check("a short plain question runs immediately with no "
                  "confirmation summary call in between",
                  _pump_until(app, lambda: StubAIWorker.calls == [
                      ("what's the weather", False)]))
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()

        # -- G: typed input never goes through any of this, even when
        # it's long/action-flavored -- only spoken input does.
        _drain_workers(app)
        StubAIWorker.calls.clear()
        StubAIWorker.behavior = {False: "Done."}
        with mock.patch.object(ov, "AIWorker", StubAIWorker):
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            overlay._on_query_submitted(
                "create a very long interactive header component that "
                "adapts across every screen size imaginable")
            check("typed input runs immediately even though it would "
                  "have triggered confirmation if spoken",
                  _pump_until(app, lambda: len(StubAIWorker.calls) == 1
                              and StubAIWorker.calls[0][1] is False))
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()

        # -- H: landing back in Idle for any reason always clears any
        # stale confirmation state (defensive reset).
        overlay._awaiting_confirmation = True
        overlay._pending_confirmation_text = "leftover"
        overlay._enter_state(ov.STATE_IDLE)
        check("entering Idle always clears _awaiting_confirmation",
              overlay._awaiting_confirmation is False)
        check("entering Idle always clears _pending_confirmation_text",
              overlay._pending_confirmation_text is None)

    finally:
        overlay.close()
        overlay.deleteLater()
        patcher_speech.stop()
        patcher_voice.stop()

    total = len(CHECKS)
    passed = sum(1 for _, ok in CHECKS if ok)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
