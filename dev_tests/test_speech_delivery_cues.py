"""Regression test for speech_delivery.md's bracket "stage direction" cues
([pause]/[sighs]/[whispers]/...) and how overlay_speech.py/agent_overlay.py
actually act on them:

  - overlay_speech._parse_speech_cues() turns raw reply text into an
    ordered list of real "speak"/"pause" ops for SpeechWorker, with
    [whispers]/[voice softens] carrying a volume_scale onto the text right
    after them -- never speaking a cue's bracket text as literal words.
  - overlay_speech._strip_cues_for_display() is what any place that
    actually *shows* a reply as text (not speech) uses instead -- pause
    cues become a plain ellipsis, everything else is dropped, and a
    markdown-style `[text](url)` link is left completely alone.
  - SpeechWorker.run(), when segmented this way, still only ever emits
    started_speaking once per reply (not once per segment), regardless of
    how many cue-pauses sit inside it.
  - agent_overlay._ide_chat_ask() -- the IDE's "Friday AI Chat" panel
    backend -- hands the *cleaned* (cue-stripped) text to both its
    on_done callback and to memory logging, since that reply is only ever
    displayed as text, never spoken.

Run with:
    QT_QPA_PLATFORM=offscreen python3 dev_tests/test_speech_delivery_cues.py
"""
import os
import sys
import threading
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

import overlay_speech as osp
import agent_overlay as ov

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


# -- _parse_speech_cues ---------------------------------------------------

def part_a_parse_cues():
    print("\n--- Part A: _parse_speech_cues ---")

    ops = osp._parse_speech_cues("Hmm, [pause] I think that could work.")
    check("a [pause] tag produces a real pause op between the two spoken "
          "chunks, not literal bracket text",
          ops == [
              {"type": "speak", "text": "Hmm,", "volume_scale": 1.0},
              {"type": "pause", "seconds": 0.35},
              {"type": "speak", "text": "I think that could work.",
               "volume_scale": 1.0},
          ])

    ops2 = osp._parse_speech_cues("[long pause] Let me think.")
    check("a cue at the very start of the reply still works (no leading "
          "empty 'speak' op)",
          ops2 == [{"type": "pause", "seconds": 0.75},
                   {"type": "speak", "text": "Let me think.",
                    "volume_scale": 1.0}])

    ops3 = osp._parse_speech_cues("[whispers] this is just between us.")
    check("[whispers] attaches a volume_scale < 1.0 to the text right "
          "after it",
          ops3[-1]["type"] == "speak" and ops3[-1]["volume_scale"] < 1.0)

    ops3b = osp._parse_speech_cues(
        "[whispers] quiet bit. [pause] Then back to normal.")
    speak_ops3b = [op for op in ops3b if op["type"] == "speak"]
    check("[whispers]'s volume ducking lasts until the *next* cue, not "
          "forever -- the segment after the following [pause] is back to "
          "full volume",
          speak_ops3b[0]["volume_scale"] < 1.0
          and speak_ops3b[-1]["volume_scale"] == 1.0)

    ops4 = osp._parse_speech_cues("No cues here at all.")
    check("plain text with no cues at all round-trips as a single speak op",
          ops4 == [{"type": "speak", "text": "No cues here at all.",
                    "volume_scale": 1.0}])

    ops5 = osp._parse_speech_cues(
        "Something with a markdown link [click here](http://example.com) "
        "should not break.")
    check("a markdown-style [text](url) link is never mistaken for a "
          "speech cue (no pause op, link text stays intact)",
          len(ops5) == 1 and "[click here](http://example.com)" in ops5[0]["text"])

    ops6 = osp._parse_speech_cues("Wait—[totally made up tag] really?")
    check("an unrecognized bracket tag still becomes a short pause "
          "(never spoken literally) rather than being ignored or crashing",
          any(op["type"] == "pause" for op in ops6)
          and all("made up tag" not in op.get("text", "") for op in ops6))

    check("an empty string parses to no ops at all",
          osp._parse_speech_cues("") == [])


# -- _strip_cues_for_display ------------------------------------------------

def part_b_strip_for_display():
    print("\n--- Part B: _strip_cues_for_display ---")

    check("a [pause] cue becomes a plain ellipsis when displayed as text",
          osp._strip_cues_for_display("Hmm, [pause] okay.") ==
          "Hmm, \u2026 okay.")

    check("a non-pause cue like [sighs] is simply dropped from displayed "
          "text, not shown as literal brackets",
          "[" not in osp._strip_cues_for_display(
              "[sighs] That was a long day."))

    check("plain text with no cues is returned unchanged",
          osp._strip_cues_for_display("Nothing special here.") ==
          "Nothing special here.")

    check("a markdown link is left completely untouched by display "
          "stripping too",
          "[click here](http://example.com)" in osp._strip_cues_for_display(
              "See [click here](http://example.com) for more."))


# -- SpeechWorker: segmented playback still behaves like one reply ---------

def part_c_speech_worker_segments():
    print("\n--- Part C: SpeechWorker plays cue-segmented text as one reply ---")

    spoken = []

    def fake_speak_with_piper(text, model_path, rate=None, volume=None, worker=None):
        spoken.append((text, volume))
        if worker is not None and not getattr(worker, "_started_emitted", False):
            worker._started_emitted = True
            worker.started_speaking.emit()

    sleeps = []

    def fake_interruptible_sleep(worker, seconds):
        sleeps.append(seconds)

    worker = osp.SpeechWorker(
        "Honestly, [pause] that one surprised me. [whispers] Don't tell "
        "anyone.")
    started_count = {"n": 0}
    worker.started_speaking.connect(lambda: started_count.__setitem__(
        "n", started_count["n"] + 1))

    with mock.patch.object(osp, "_get_piper_voice", lambda model_path: object()), \
         mock.patch.object(osp, "_speak_with_piper", fake_speak_with_piper), \
         mock.patch.object(osp, "_interruptible_sleep", fake_interruptible_sleep), \
         mock.patch.object(osp, "USE_PIPER_VOICE", True):
        worker.run()  # calling run() directly -- no real QThread needed here

    check("the reply was split into the right number of spoken chunks "
          "around its cues",
          len(spoken) == 3)
    check("cue text itself was never handed to the TTS backend as words "
          "to speak",
          all("pause" not in t and "whispers" not in t for t, _ in spoken))
    check("the segment right after [whispers] was spoken with a reduced "
          "volume",
          spoken[-1][1] is not None and spoken[-1][1] < 1.0)
    check("at least one real pause was inserted for the [pause] cue",
          len(sleeps) >= 1)
    check("started_speaking fired exactly once for the whole reply, not "
          "once per cue-separated segment",
          started_count["n"] == 1)


# -- _ide_chat_ask: the IDE's text-only chat panel never sees raw cues -----

class StubWorkerCues(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, prompt, parent=None, summarize_only=False, ide_scoped=False):
        super().__init__(parent)
        self._prompt = prompt

    def run(self):
        time.sleep(0.05)
        self.succeeded.emit(
            "[pause] Sure, [sighs] here's that function you asked for.")


def _ask_and_wait(app, text):
    result = {}
    done = threading.Event()

    def on_done(ok, reply):
        result["ok"] = ok
        result["result"] = reply
        done.set()
        # Posted through the same main-thread invoker _ide_chat_ask()
        # itself uses (see agent_overlay._on_qt_main_thread), rather than
        # called directly here on whatever thread on_done happens to run
        # on, so it's strictly ordered after any already-queued
        # main-thread work -- app.exec() stopping is allowed to pre-empt
        # already-queued work otherwise, which would make this racy.
        ov._on_qt_main_thread(app.quit)

    ov._ide_chat_ask(text, on_done)
    app.exec()
    done.wait(5)
    return result


def part_d_ide_chat_panel_never_sees_cues(app):
    print("\n--- Part D: _ide_chat_ask strips cues before the visible chat panel ---")

    with mock.patch.object(ov, "AIWorker", StubWorkerCues):
        ov._circle_overlay = None
        resp = _ask_and_wait(app, "write me a function")
        reply = resp.get("result", "")
        check("the IDE chat panel's callback never receives a literal "
              "bracket cue (it's a plain text bubble, never spoken)",
              "[" not in reply and "]" not in reply)
        check("the actual words of the reply still made it through "
              "untouched",
              "here's that function you asked for" in reply)

    ov._circle_overlay = None  # leave the module in a clean state


def main():
    part_a_parse_cues()
    part_b_strip_for_display()
    part_c_speech_worker_segments()

    app = QApplication(sys.argv)
    # Needed now that _ide_chat_ask() builds/wires/starts its AIWorker
    # via _on_qt_main_thread() rather than directly -- see
    # agent_overlay.main() for where this is normally built for real.
    ov._main_thread_invoker = ov._MainThreadInvoker()
    part_d_ide_chat_panel_never_sees_cues(app)
    ov._main_thread_invoker = None

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
