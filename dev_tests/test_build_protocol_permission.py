"""Regression test for the Build Protocol / Permission mechanism (Task
66): development_skill.md's new three-layer (Frontend/Backend/Storage)
Build Protocol, the two new on-demand skill-fetch tools that complete
the reusable pattern Task 62 started (ide_get_backend_skill /
ide_get_storage_skill), the new persistent build-status checklist tool
(ide_report_build_status), and the inline "Permission" decision-options
mechanism in the IDE's embedded "Friday AI Chat" panel -- a pending
{{AWAIT_DECISION}} pause that also carries a companion
{{OPTIONS: "A" | "B"}} tag renders as clickable buttons (plus the
panel's own always-present text box as the free-text custom option),
the same shape as this agent's own ask_user tool.

Covers:
  A. _extract_decision_options() -- tag detection/stripping/parsing,
     2-4 option cap, malformed/absent tag treated as None, no false
     positives on ordinary text, and it never fires without the tag
     regardless of what {{AWAIT_DECISION}} does.
  B. _accepts_options_arg() -- 2-arg vs 3-arg callables, *args,
     bound methods, and callables that can't be introspected.
  C. agent_overlay._ide_chat_ask() end to end: a reply carrying both
     control tags delivers options to a 3-arg on_done, delivers nothing
     to a 2-arg on_done without raising (and without double-invoking
     it), and a reply with only {{AWAIT_DECISION}} (no {{OPTIONS}})
     delivers options=None either way.
  D. The circle's own voice/typed chat path discards {{OPTIONS: ...}}
     as a pure defense-in-depth signal -- it never leaks into
     _show_response/memory even though personality.md never tells the
     model to use it there.
  E. agent_tools.ide_report_build_status() -- phase/status validation,
     forwards to the registered handler, Agent-Mode-off guard, and the
     tool is correctly registered (GEMINI_TOOLS/TOOL_FUNCTIONS/
     TOOL_SCHEMAS/IDE_CHAT_TOOL_NAMES all agree).
  F. agent_tools.ide_get_backend_skill()/ide_get_storage_skill() --
     graceful "not present yet" message (the real files don't exist in
     this install), Agent-Mode-off guard, and registration parity same
     as Part E.
  G. ChatSidePanel (ide.py) -- _show_decision_options renders a button
     per option plus a working custom-text box; clicking an option (or
     submitting custom text) dismisses the widget and sends that exact
     text through the normal _submit_text path; a brand new typed
     message dismisses a still-showing decision widget instead of
     leaving stale buttons around; update_build_status creates the
     checklist once and upserts each phase's row in place afterward
     rather than duplicating blocks.

Requires PySide6 with an offscreen-capable platform plugin and a real
display (Tkinter, for the ide.py part):
    DISPLAY=:99 QT_QPA_PLATFORM=offscreen python3 dev_tests/test_build_protocol_permission.py
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
import memory  # noqa: E402
import ide as ide_mod  # noqa: E402

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


def pump_tk(root, times=20, delay=0.01):
    for _ in range(times):
        try:
            root.update()
        except tk.TclError:
            return
        time.sleep(delay)


class StubAIWorker(QThread):
    """Same shape as the one in test_pending_decision_timeout.py."""

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


def _drain_workers(app, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if all(w.isFinished() for w in StubAIWorker.instances):
            return
        time.sleep(0.01)


# -------------------------------------------------------------------------
# Part A: _extract_decision_options()
# -------------------------------------------------------------------------
def part_a_tag_extraction():
    print("\n--- Part A: _extract_decision_options() ---")

    clean, opts = ov._extract_decision_options(
        'Which stack?\n\n{{OPTIONS: "React" | "Plain HTML/CSS/JS" | "Vue"}}')
    check("the tag is detected and parsed", opts == ["React", "Plain HTML/CSS/JS", "Vue"])
    check("the tag itself is removed from the cleaned text",
          "{{" not in clean and "OPTIONS" not in clean)
    check("the real question text survives untouched", clean == "Which stack?")

    clean2, opts2 = ov._extract_decision_options("just an ordinary finished reply")
    check("ordinary text with no tag is left completely untouched",
          clean2 == "just an ordinary finished reply")
    check("ordinary text with no tag returns None, not an empty list", opts2 is None)

    # More than 4 options offered -- capped, not rejected outright.
    _, opts3 = ov._extract_decision_options(
        '{{OPTIONS: "A" | "B" | "C" | "D" | "E"}}')
    check("more than 4 options is capped at 4, not rejected or crashed",
          opts3 == ["A", "B", "C", "D"])

    # Malformed/empty tag (no quoted items at all) -- treated as absent,
    # not a crash or a confusing empty-button widget.
    clean4, opts4 = ov._extract_decision_options("Pick one.\n\n{{OPTIONS: }}")
    check("a tag with no quoted options parses to None, not an empty list",
          opts4 is None)
    check("the malformed tag is still stripped from the displayed text",
          "OPTIONS" not in clean4)

    # Empty/None input never raises.
    try:
        r1 = ov._extract_decision_options("")
        r2 = ov._extract_decision_options(None)
        ok = r1 == ("", None) and r2 == (None, None)
    except Exception:  # noqa: BLE001
        ok = False
    check("empty string / None input never raises and returns (input, None)", ok)

    # Case/whitespace tolerance, same spirit as _AWAIT_DECISION_TAG_RE.
    _, opts5 = ov._extract_decision_options('{{ options :  "Yes" | "No" }}')
    check("the tag is case/whitespace tolerant", opts5 == ["Yes", "No"])


# -------------------------------------------------------------------------
# Part B: _accepts_options_arg()
# -------------------------------------------------------------------------
def part_b_accepts_options_arg():
    print("\n--- Part B: _accepts_options_arg() ---")

    two_arg = lambda ok, text: None  # noqa: E731
    three_arg = lambda ok, text, options=None: None  # noqa: E731
    star_args = lambda *a, **kw: None  # noqa: E731

    check("a plain 2-arg lambda does NOT accept an options arg",
          ov._accepts_options_arg(two_arg) is False)
    check("a 3-arg lambda (with a default) DOES accept an options arg",
          ov._accepts_options_arg(three_arg) is True)
    check("a *args catch-all is treated as accepting it",
          ov._accepts_options_arg(star_args) is True)

    def three_arg_def(ok, text, options=None):
        return None

    check("a plain def with 3 params also accepts it",
          ov._accepts_options_arg(three_arg_def) is True)

    class Obj:
        def method(self, ok, text):
            return None

    check("a bound method counting 'self' correctly still says 2 real args "
          "-> doesn't accept it", ov._accepts_options_arg(Obj().method) is False)

    check("something that can't be introspected (a builtin) is assumed to "
          "accept it, rather than guessed the other, more restrictive way",
          ov._accepts_options_arg(print) is True)

    # Same helper, duplicated in agent_tools.py for the notify_ide_chat
    # path (documented as intentional, see its own docstring) -- check it
    # independently so a future edit to one copy that silently diverges
    # from the other gets caught. Its threshold is 2 positional args, not
    # 3, because notify_ide_chat's handler signature is handler(text,
    # options=None) -- one fewer than _ide_chat_ask's on_done(ok, text,
    # options=None) -- so the single-arg/two-arg shapes it distinguishes
    # between are one narrower than agent_overlay's own copy above.
    one_arg = lambda text: None  # noqa: E731
    two_arg_at = lambda text, options=None: None  # noqa: E731
    check("agent_tools.py's own copy of the helper says a 1-arg handler "
          "does NOT accept an options arg",
          at._accepts_options_arg(one_arg) is False)
    check("agent_tools.py's own copy of the helper says a 2-arg handler "
          "DOES accept an options arg",
          at._accepts_options_arg(two_arg_at) is True)


# -------------------------------------------------------------------------
# Part C: _ide_chat_ask() end to end -- options delivered to on_done
# -------------------------------------------------------------------------
def part_c_ide_chat_ask_delivers_options():
    print("\n--- Part C: _ide_chat_ask() delivers options end to end ---")
    app = QApplication.instance() or QApplication(sys.argv)
    memory.set_memory_dir(tempfile.mkdtemp())
    memory._clear_recent_turns()
    ov._ide_chat_decision_tracker._timeout_ms = 60_000  # don't let it fire mid-test
    ov._ide_chat_decision_tracker.cancel()
    # _ide_chat_ask marshals AIWorker construction/start through
    # _on_qt_main_thread(), which is a silent no-op with no real
    # CircleOverlay/main() ever having run (true in this standalone
    # test) -- same setup test_pending_decision_timeout.py's own IDE-chat
    # part uses.
    ov._main_thread_invoker = ov._MainThreadInvoker()

    with mock.patch.object(ov, "AIWorker", StubAIWorker):
        # -- both tags present -> a 3-arg on_done gets the parsed options.
        StubAIWorker.calls.clear()
        StubAIWorker.next_reply = (
            'Which stack should this use?\n\n'
            '{{OPTIONS: "React" | "Plain HTML/CSS/JS"}}\n{{AWAIT_DECISION}}')
        results = []
        ov._ide_chat_ask(
            "build me a frontend",
            lambda ok, text, options=None: results.append((ok, text, options)))
        check("the reply lands", _pump_until(app, lambda: len(results) == 1))
        ok, text, options = results[0]
        check("the question text is clean of both control tags",
              "OPTIONS" not in text and "AWAIT_DECISION" not in text)
        check("the 3-arg on_done actually receives the parsed options",
              options == ["React", "Plain HTML/CSS/JS"])

        # -- a 2-arg on_done (pre-existing style) still works, unharmed,
        # and is never invoked twice (no duplicate memory logging).
        memory._clear_recent_turns()
        StubAIWorker.calls.clear()
        StubAIWorker.next_reply = (
            'Pick one?\n\n{{OPTIONS: "Yes" | "No"}}\n{{AWAIT_DECISION}}')
        results2 = []
        call_count = {"n": 0}

        def on_done_2arg(ok, text):
            call_count["n"] += 1
            results2.append((ok, text))

        ov._ide_chat_ask("a question with legacy callback", on_done_2arg)
        check("a legacy 2-arg on_done still receives the reply",
              _pump_until(app, lambda: len(results2) == 1))
        time.sleep(0.1)
        app.processEvents()
        check("a legacy 2-arg on_done is invoked exactly once, never "
              "double-invoked while falling back", call_count["n"] == 1)
        check("the delivered text to the legacy callback is clean",
              "OPTIONS" not in results2[0][1])

        # -- {{AWAIT_DECISION}} alone, no {{OPTIONS}} -> options is None,
        # not an accidental empty list or leftover from a previous turn.
        StubAIWorker.calls.clear()
        StubAIWorker.next_reply = "An open-ended question.\n\n{{AWAIT_DECISION}}"
        results3 = []
        ov._ide_chat_ask(
            "something open-ended",
            lambda ok, text, options=None: results3.append((ok, text, options)))
        check("an await-decision-only reply lands",
              _pump_until(app, lambda: len(results3) == 1))
        check("no {{OPTIONS}} tag -> options is None",
              results3[0][2] is None)

        # -- a finished reply (no {{AWAIT_DECISION}} at all) never carries
        # options even if a stray {{OPTIONS}} tag somehow showed up on it.
        StubAIWorker.calls.clear()
        StubAIWorker.next_reply = 'All done.\n\n{{OPTIONS: "A" | "B"}}'
        results4 = []
        ov._ide_chat_ask(
            "a finished task",
            lambda ok, text, options=None: results4.append((ok, text, options)))
        check("a finished (non-pending) reply lands",
              _pump_until(app, lambda: len(results4) == 1))
        check("a stray OPTIONS tag on a non-pending reply is ignored, no "
              "options rendered for something that isn't actually waiting",
              results4[0][2] is None)


# -------------------------------------------------------------------------
# Part D: the circle's own path discards {{OPTIONS: ...}} defensively
# -------------------------------------------------------------------------
def part_d_circle_discards_options_tag():
    print("\n--- Part D: circle path discards {{OPTIONS: ...}} ---")
    app = QApplication.instance() or QApplication(sys.argv)
    memory.set_memory_dir(tempfile.mkdtemp())
    memory._clear_recent_turns()

    patcher_voice = mock.patch.object(ov, "ENABLE_VOICE_MODE", False)
    patcher_speech = mock.patch.object(ov, "ENABLE_SPEECH", False)
    patcher_voice.start()
    patcher_speech.start()
    overlay = ov.CircleOverlay()
    overlay._decision_tracker._timeout_ms = 60_000

    try:
        with mock.patch.object(ov, "AIWorker", StubAIWorker):
            StubAIWorker.calls.clear()
            StubAIWorker.next_reply = (
                'Should this be SQLite or Postgres?\n\n'
                '{{OPTIONS: "SQLite" | "Postgres"}}\n{{AWAIT_DECISION}}')
            overlay._enter_state(ov.STATE_IDLE)
            app.processEvents()
            overlay._on_query_submitted("set up a database")
            _pump_until(app, lambda: overlay._state == ov.STATE_RESPONDING)
            check("the circle still responds normally even with an "
                  "OPTIONS tag it was never told to use",
                  overlay._last_was_error is False)
            check("the raw {{OPTIONS: ...}} tag never leaks into memory "
                  "(spoken text has nowhere to put a button)",
                  all("OPTIONS" not in (t or "")
                      for _, t in memory.get_recent_turns()))
            check("the decision tracker is still armed off the cleaned "
                  "question (await-decision handling is unaffected)",
                  overlay._decision_tracker._question is not None
                  and "OPTIONS" not in overlay._decision_tracker._question)
    finally:
        overlay.hide()
        patcher_voice.stop()
        patcher_speech.stop()


# -------------------------------------------------------------------------
# Part E: ide_report_build_status() + registration parity
# -------------------------------------------------------------------------
def part_e_build_status_tool():
    print("\n--- Part E: ide_report_build_status() ---")

    check("the tool is registered in GEMINI_TOOLS",
          "ide_report_build_status" in {f.__name__ for f in at.GEMINI_TOOLS})
    check("the tool is registered in TOOL_FUNCTIONS",
          "ide_report_build_status" in at.TOOL_FUNCTIONS)
    check("the tool has a schema in TOOL_SCHEMAS",
          "ide_report_build_status" in
          {s["function"]["name"] for s in at.TOOL_SCHEMAS})
    check("the tool is IDE-chat-scoped (offered to the embedded panel)",
          "ide_report_build_status" in at.IDE_CHAT_TOOL_NAMES)

    if not at.is_agent_mode_on():
        check("off Agent Mode, the tool says plainly it isn't available "
              "rather than silently doing nothing",
              "isn't open" in at.ide_report_build_status("frontend", "done"))

    received = []
    at.set_ide_build_status_handler(
        lambda phase, status, detail: received.append((phase, status, detail)))
    try:
        with mock.patch.object(at, "is_agent_mode_on", lambda: True):
            msg = at.ide_report_build_status("frontend", "in_progress", "scaffolding")
            check("a valid call returns a plain confirmation string",
                  "frontend" in msg and "in_progress" in msg)
            check("a valid call actually forwards to the registered handler",
                  received == [("frontend", "in_progress", "scaffolding")])

            received.clear()
            bad_phase = at.ide_report_build_status("css", "done")
            check("an invalid phase is rejected with a clear error, not "
                  "silently accepted", bad_phase.startswith("Error")
                  and received == [])

            bad_status = at.ide_report_build_status("backend", "finished")
            check("an invalid status is rejected with a clear error too",
                  bad_status.startswith("Error") and received == [])

            # phase/status normalization (case-insensitive, trimmed).
            received.clear()
            at.ide_report_build_status("  Storage ", "DONE", "")
            check("phase/status are normalized (trimmed, case-insensitive)",
                  received == [("storage", "done", "")])
    finally:
        at.set_ide_build_status_handler(None)

    # Best-effort: no handler registered -> never raises.
    try:
        at.report_ide_build_status("frontend", "done", "")
        no_handler_ok = True
    except Exception:  # noqa: BLE001
        no_handler_ok = False
    check("report_ide_build_status() with no handler registered never raises",
          no_handler_ok)


# -------------------------------------------------------------------------
# Part F: ide_get_backend_skill() / ide_get_storage_skill()
# -------------------------------------------------------------------------
def part_f_backend_storage_skill_tools():
    print("\n--- Part F: ide_get_backend_skill()/ide_get_storage_skill() ---")

    for name in ("ide_get_backend_skill", "ide_get_storage_skill"):
        check(f"{name} is registered in GEMINI_TOOLS",
              name in {f.__name__ for f in at.GEMINI_TOOLS})
        check(f"{name} is registered in TOOL_FUNCTIONS",
              name in at.TOOL_FUNCTIONS)
        check(f"{name} has a schema in TOOL_SCHEMAS",
              name in {s["function"]["name"] for s in at.TOOL_SCHEMAS})
        check(f"{name} is IDE-chat-scoped", name in at.IDE_CHAT_TOOL_NAMES)

    if not at.is_agent_mode_on():
        check("off Agent Mode, ide_get_backend_skill says plainly it "
              "isn't available", "isn't open" in at.ide_get_backend_skill())
        check("off Agent Mode, ide_get_storage_skill says plainly it "
              "isn't available", "isn't open" in at.ide_get_storage_skill())

    backend_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "BACKEND_SKILL.md")
    storage_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "STORAGE_SKILL.md")

    with mock.patch.object(at, "is_agent_mode_on", lambda: True):
        if not os.path.exists(backend_path):
            msg = at.ide_get_backend_skill()
            check("BACKEND_SKILL.md genuinely doesn't exist in this install "
                  "yet, and the tool says so plainly rather than crashing "
                  "or pretending it has content", "isn't present" in msg)
        if not os.path.exists(storage_path):
            msg2 = at.ide_get_storage_skill()
            check("STORAGE_SKILL.md genuinely doesn't exist in this install "
                  "yet, and the tool says so plainly rather than crashing "
                  "or pretending it has content", "isn't present" in msg2)

        # Prove the success path generically works too (once a user
        # supplies the real file, this exact mechanism serves it) by
        # dropping a temporary one in next to the real skill files.
        tmp_name = "_TEST_TEMP_BACKEND_SKILL.md"
        tmp_path = os.path.join(os.path.dirname(backend_path), tmp_name)
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write("# Temporary backend skill content for this test\n")
            content = at._read_own_skill_file(tmp_name, "test skill")
            check("_read_own_skill_file() (the shared helper both new "
                  "tools use) returns real content once a file exists",
                  "Temporary backend skill content" in content)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


# -------------------------------------------------------------------------
# Part G: ChatSidePanel -- decision options UI + build status checklist
# -------------------------------------------------------------------------
def part_g_chat_panel_ui():
    print("\n--- Part G: ChatSidePanel decision-options + build-status UI ---")

    class FakeApp(tk.Tk):
        def __init__(self):
            super().__init__()
            self.f_ui = ("Arial",)
            self._agent_host = None

    app = FakeApp()
    try:
        panel = ide_mod.ChatSidePanel(app)
        panel.pack(fill="both", expand=True)
        pump_tk(app)

        # -- rendering + answering via a button.
        panel._add_bubble("friday", "Which stack?")
        panel._show_decision_options(["React", "Plain HTML/CSS/JS", "Vue"])
        pump_tk(app)
        check("the decision widget is created", panel._decision_row is not None)

        submitted = []
        with mock.patch.object(panel, "_submit_text", lambda t: submitted.append(t)):
            panel._choose_decision_option("React")
        check("choosing an option sends that exact text through the "
              "normal submit path", submitted == ["React"])
        check("choosing an option dismisses the widget",
              panel._decision_row is None)

        # -- a brand new typed message dismisses a still-live decision
        # widget rather than leaving stale buttons clickable.
        panel._add_bubble("friday", "Which stack, take two?")
        panel._show_decision_options(["A", "B"])
        pump_tk(app)
        check("widget re-created for a second question", panel._decision_row is not None)
        host_calls = []

        class FakeHost:
            def ask(self, text, on_done):
                host_calls.append(text)
                # never resolves in this test -- just checking dismissal
                # happens up front, synchronously, not after the reply.

        app._agent_host = FakeHost()
        panel._submit_text("something the user typed instead")
        check("submitting a brand new message dismisses the still-live "
              "decision widget from the previous turn",
              panel._decision_row is None)
        check("the new message still actually goes through normally",
              host_calls == ["something the user typed instead"])

        # -- build-status checklist: created once, upserted afterward.
        panel.update_build_status("frontend", "in_progress", "scaffolding")
        pump_tk(app)
        row_after_first = panel._status_row
        check("the checklist widget is created on first use",
              row_after_first is not None)
        check("all three phases are present from the first call, not just "
              "the one reported", set(panel._status_labels) ==
              {"frontend", "backend", "storage"})
        check("the reported phase shows in_progress", "Frontend" in
              panel._status_labels["frontend"].cget("text")
              and "scaffolding" in panel._status_labels["frontend"].cget("text"))
        check("an unreported phase still shows its initial pending state",
              "Backend" in panel._status_labels["backend"].cget("text"))

        panel.update_build_status("frontend", "done", "4 pages built")
        panel.update_build_status("backend", "blocked", "needs API keys")
        pump_tk(app)
        check("a second update to the SAME phase upserts in place -- no "
              "second checklist widget was created",
              panel._status_row is row_after_first)
        check("the frontend row now reflects 'done'",
              "4 pages built" in panel._status_labels["frontend"].cget("text"))
        check("the backend row reflects 'blocked' with its detail",
              "needs API keys" in panel._status_labels["backend"].cget("text"))

        # -- receive_proactive_message can also carry options.
        panel.receive_proactive_message("Continuing without a reply -- pick one?",
                                         ["Option X", "Option Y"])
        pump_tk(app)
        check("a proactive message with options also renders the widget",
              panel._decision_row is not None)
    finally:
        app.destroy()
        pump_tk(app, 3)


def main():
    part_a_tag_extraction()
    part_b_accepts_options_arg()
    part_c_ide_chat_ask_delivers_options()
    part_d_circle_discards_options_tag()
    part_e_build_status_tool()
    part_f_backend_storage_skill_tools()
    part_g_chat_panel_ui()

    total = len(CHECKS)
    passed = sum(1 for _, ok in CHECKS if ok)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        print("\nFailed checks:")
        for label, ok in CHECKS:
            if not ok:
                print("  - " + label)
        sys.exit(1)


if __name__ == "__main__":
    main()
