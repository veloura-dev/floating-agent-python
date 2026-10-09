"""Regression test for the tool-call iteration ceiling used by Groq's and
Mistral's shared manual tool-calling loop, AIWorker._run_tool_loop()
(Gemini doesn't use this at all -- passing it plain Python functions
turns on the SDK's own automatic function calling, which runs its whole
multi-turn loop internally, inside one network call).

Triggered by a real, reported failure: asking the IDE's embedded "Friday
AI Chat" panel (ide_scoped=True) to "build me a frontend code of an
ecommerce website" returned "Reached the tool-call limit before
finishing" -- the old hardcoded max_iterations=5 was nowhere near enough
for a genuine multi-file build (fetch a skill doc, read/list the
workspace, then a create+write pair per file), especially now that a
real frontend build is supposed to start with a call to
ide_get_frontend_skill() per development_skill.md's own Section 6,
which already spends one of the 5 before any real work begins.

Covers:
  A. TOOL_LOOP_MAX_ITERATIONS / TOOL_LOOP_MAX_ITERATIONS_IDE -- both
     exist, both comfortably higher than the old hardcoded 5, and the
     IDE-scoped ceiling is substantially higher than the general one
     (coding/build work genuinely needs far more round trips than
     ordinary chat tool use).
  B. _run_tool_loop() itself -- stops the instant the model returns a
     plain-text answer (regardless of how low iterations is), executes
     every tool call it's asked to and feeds the result back in, and
     only produces the "reached the limit" message if the cap is
     actually hit without ever getting a final answer.
  C. The real call sites in _try_groq()/_try_mistral() pass the correct
     ceiling based on self._ide_scoped -- proven by capturing the real
     max_iterations value _run_tool_loop() is actually invoked with, not
     just trusting the source reads that way.
  D. The exact reported scenario, end to end: a simulated "build an
     ecommerce site" conversation needing more than 5 but fewer than 40
     tool-call round trips fails under the old 5-iteration cap and
     succeeds under the new ide_scoped=True ceiling.

Requires PySide6 with an offscreen-capable platform plugin:
    QT_QPA_PLATFORM=offscreen python3 dev_tests/test_tool_loop_iteration_limit.py
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


class _FakeToolCall:
    def __init__(self, call_id, name, arguments="{}"):
        self.id = call_id

        class _Fn:
            pass
        self.function = _Fn()
        self.function.name = name
        self.function.arguments = arguments


class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeResponse:
    def __init__(self, message):
        class _Choice:
            pass
        choice = _Choice()
        choice.message = message
        self.choices = [choice]


def _make_scripted_create_fn(turns):
    """Returns a create_fn(messages) that, on each call, pops the next
    scripted turn and returns the matching _FakeResponse -- either
    another round of tool calls, or a final plain-text answer. Also
    records how many times it was actually invoked."""
    state = {"calls": 0}
    remaining = list(turns)

    def _create(messages):
        state["calls"] += 1
        if remaining:
            turn = remaining.pop(0)
        else:
            turn = ("answer", "fallback answer -- script ran out")
        kind, payload = turn
        if kind == "tool":
            return _FakeResponse(_FakeMessage(
                content="", tool_calls=[_FakeToolCall("c1", payload)]))
        return _FakeResponse(_FakeMessage(content=payload, tool_calls=None))

    return _create, state


# -------------------------------------------------------------------------
# Part A: the constants themselves
# -------------------------------------------------------------------------
def part_a_constants():
    print("\n--- Part A: iteration-ceiling constants ---")
    check("TOOL_LOOP_MAX_ITERATIONS exists and is comfortably higher "
          "than the old hardcoded 5", ov.TOOL_LOOP_MAX_ITERATIONS > 5)
    check("TOOL_LOOP_MAX_ITERATIONS_IDE exists and is substantially "
          "higher than the general (non-IDE) ceiling -- real coding/"
          "build work needs far more round trips than ordinary chat "
          "tool use",
          ov.TOOL_LOOP_MAX_ITERATIONS_IDE > ov.TOOL_LOOP_MAX_ITERATIONS * 2)
    check("the IDE ceiling is generous enough for a genuine multi-file "
          "build (comfortably above 20 round trips)",
          ov.TOOL_LOOP_MAX_ITERATIONS_IDE >= 20)


# -------------------------------------------------------------------------
# Part B: _run_tool_loop() itself
# -------------------------------------------------------------------------
def part_b_run_tool_loop_mechanics():
    print("\n--- Part B: _run_tool_loop() mechanics ---")

    with mock.patch.object(ov.agent_tools, "call_tool", return_value="ok"):
        # A model that answers immediately, tools available but unused.
        create_fn, state = _make_scripted_create_fn([("answer", "done already")])
        messages = []
        text = ov.AIWorker._run_tool_loop(create_fn, messages, max_iterations=5)
        check("a model that never requests a tool returns its plain-text "
              "answer immediately, using only one call",
              text == "done already" and state["calls"] == 1)

        # A model that uses a couple of tools, then answers -- well under
        # the cap, must succeed and stop as soon as it gets a real answer.
        create_fn2, state2 = _make_scripted_create_fn([
            ("tool", "ide_read_file"),
            ("tool", "ide_write_file"),
            ("answer", "built it"),
        ])
        messages2 = []
        text2 = ov.AIWorker._run_tool_loop(create_fn2, messages2, max_iterations=5)
        check("a few tool calls followed by a real answer succeeds "
              "within a generous cap, using exactly the turns it needed",
              text2 == "built it" and state2["calls"] == 3)
        check("each tool call's result is actually fed back into the "
              "conversation (not just executed and discarded)",
              any(m.get("role") == "tool" for m in messages2))

        # A model that NEVER stops requesting tools -- must terminate at
        # exactly max_iterations and say so, never loop forever.
        create_fn3, state3 = _make_scripted_create_fn(
            [("tool", "ide_write_file")] * 100)
        messages3 = []
        text3 = ov.AIWorker._run_tool_loop(create_fn3, messages3, max_iterations=5)
        check("a model that never stops requesting tools is cut off at "
              "exactly the given ceiling, not before and not after",
              state3["calls"] == 5)
        check("hitting the ceiling without a final answer returns the "
              "clear, actionable rephrase-or-split message",
              "Reached the tool-call limit" in text3)


# -------------------------------------------------------------------------
# Part C: the real call sites pass the right ceiling
# -------------------------------------------------------------------------
def part_c_call_sites_pass_correct_ceiling():
    print("\n--- Part C: _try_groq()/_try_mistral() pass the right ceiling ---")
    app = QApplication.instance() or QApplication(sys.argv)

    captured = {}

    def _fake_run_tool_loop(create_fn, messages, ide_scoped=False, max_iterations=None):
        captured["ide_scoped"] = ide_scoped
        captured["max_iterations"] = max_iterations
        return "whatever"

    # -- Groq, general (circle) chat --
    worker = ov.AIWorker("hello", ide_scoped=False)
    with mock.patch.object(ov, "GROQ_API_KEY", "fake-key"), \
         mock.patch("groq.Groq"), \
         mock.patch.object(ov.AIWorker, "_run_tool_loop",
                            staticmethod(_fake_run_tool_loop)):
        worker._try_groq()
    check("_try_groq() (general chat, ide_scoped=False) passes the "
          "general TOOL_LOOP_MAX_ITERATIONS ceiling, not the IDE one",
          captured.get("max_iterations") == ov.TOOL_LOOP_MAX_ITERATIONS)

    # -- Groq, IDE chat panel --
    captured.clear()
    worker2 = ov.AIWorker("build me a site", ide_scoped=True)
    with mock.patch.object(ov, "GROQ_API_KEY", "fake-key"), \
         mock.patch("groq.Groq"), \
         mock.patch.object(ov.AIWorker, "_run_tool_loop",
                            staticmethod(_fake_run_tool_loop)):
        worker2._try_groq()
    check("_try_groq() from the IDE chat panel (ide_scoped=True) passes "
          "the much higher TOOL_LOOP_MAX_ITERATIONS_IDE ceiling",
          captured.get("max_iterations") == ov.TOOL_LOOP_MAX_ITERATIONS_IDE)

    # -- Mistral, general chat --
    captured.clear()
    worker3 = ov.AIWorker("hello", ide_scoped=False)
    with mock.patch.object(ov, "MISTRAL_API_KEY", "fake-key"), \
         mock.patch("mistralai.client.Mistral"), \
         mock.patch.object(ov.AIWorker, "_run_tool_loop",
                            staticmethod(_fake_run_tool_loop)):
        worker3._try_mistral()
    check("_try_mistral() (general chat) passes the general ceiling too",
          captured.get("max_iterations") == ov.TOOL_LOOP_MAX_ITERATIONS)

    # -- Mistral, IDE chat panel --
    captured.clear()
    worker4 = ov.AIWorker("build me a site", ide_scoped=True)
    with mock.patch.object(ov, "MISTRAL_API_KEY", "fake-key"), \
         mock.patch("mistralai.client.Mistral"), \
         mock.patch.object(ov.AIWorker, "_run_tool_loop",
                            staticmethod(_fake_run_tool_loop)):
        worker4._try_mistral()
    check("_try_mistral() from the IDE chat panel passes the IDE "
          "ceiling too, matching Groq's own behavior",
          captured.get("max_iterations") == ov.TOOL_LOOP_MAX_ITERATIONS_IDE)


# -------------------------------------------------------------------------
# Part D: the exact reported scenario, end to end
# -------------------------------------------------------------------------
def part_d_reported_scenario_end_to_end():
    print("\n--- Part D: the real reported scenario (a multi-file build) ---")

    # A realistic simulated ecommerce-site build: fetch the skill doc,
    # look around the workspace, then create+write a handful of files --
    # 11 tool-call round trips plus a final answer (12 calls total),
    # which is more than the OLD hardcoded cap (5) but comfortably under
    # the new IDE one.
    build_turns = (
        [("tool", "ide_get_frontend_skill")]
        + [("tool", "ide_list_folder")]
        + [("tool", "ide_create_file")] * 1
        + [("tool", "ide_write_file")] * 4   # index.html, styles.css, script.js, cart.html
        + [("tool", "ide_read_file")] * 4    # a quick self-review pass
        + [("answer", "Built the ecommerce site: index.html, styles.css, "
                       "script.js, cart.html.")]
    )
    with mock.patch.object(ov.agent_tools, "call_tool", return_value="ok"):
        create_fn, state = _make_scripted_create_fn(build_turns)
        text_old_cap = ov.AIWorker._run_tool_loop(
            create_fn, [], ide_scoped=True, max_iterations=5)
        check("under the OLD hardcoded cap of 5, this exact realistic "
              "build is exactly the kind of request that used to fail "
              "(reproducing the reported bug)",
              "Reached the tool-call limit" in text_old_cap)

        create_fn2, state2 = _make_scripted_create_fn(build_turns)
        text_new_cap = ov.AIWorker._run_tool_loop(
            create_fn2, [], ide_scoped=True,
            max_iterations=ov.TOOL_LOOP_MAX_ITERATIONS_IDE)
        check("under the new IDE-scoped ceiling, the exact same build "
              "completes with a real final answer instead of hitting "
              "the limit",
              "Built the ecommerce site" in text_new_cap
              and "Reached the tool-call limit" not in text_new_cap)
        check("...using exactly the 12 round trips the script needed "
              "(11 tool calls plus the final answer), no more",
              state2["calls"] == 12)


def main():
    part_a_constants()
    part_b_run_tool_loop_mechanics()
    part_c_call_sites_pass_correct_ceiling()
    part_d_reported_scenario_end_to_end()

    passed = sum(1 for _, ok in CHECKS if ok)
    total = len(CHECKS)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
