"""Regression test for three behavior changes:

1. Clicking the circle while it's RESPONDING (Friday is talking) must
   immediately interrupt whatever is being spoken and drop straight into
   actively listening for the next request (STATE_LISTENING, capturing a
   voice command) -- not cancel all the way back to idle, and not keep
   talking.

2. Every time a response finishes on its own (speech completes, or the
   safety-net timer fires) it must land in that same actively-listening
   state first, not jump straight back to Idle -- only falling back to
   Idle after a few seconds of silence (the existing command-capture
   timeout), so a quick follow-up never needs the wake word repeated.

3. The circle must not flip to its "talking" (RESPONDING) animation
   until speech actually starts producing audio -- Piper's one-time
   voice-model load and its synthesis both take a visible beat, so the
   circle stays in Loading (the spinner) until then instead of visibly
   getting ahead of the sound.

Also covers the underlying SpeechWorker.request_stop() dispatch logic
(which backend gets told to stop, and how), and _speak_with_piper's
asynchronous-playback-plus-poll design -- which exists specifically so
interruption actually works: a blocking PlaySound() call can't reliably
be interrupted from another thread, but an asynchronous one can.

Kept in the persisted workspace (not /tmp) so it survives a fresh
sandbox session.

Run with:
    DISPLAY=:99 python3 dev_tests/test_friday_interrupt_and_followup_listen.py
"""
import os
import sys
import types
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import agent_overlay as ov  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def _fake_winsound(**extra):
    base = dict(PlaySound=mock.Mock(), SND_PURGE=8,
                SND_FILENAME=1, SND_ASYNC=2)
    base.update(extra)
    return types.SimpleNamespace(**base)


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    # -- Part A: SpeechWorker.request_stop() backend dispatch ----------
    worker = ov.SpeechWorker("hello there", parent=None)
    check("a fresh SpeechWorker starts with _stop_requested False",
          worker._stop_requested is False)

    fake_engine = mock.Mock()
    worker._active_backend = "pyttsx3"
    worker._active_handle = fake_engine
    worker.request_stop()
    check("request_stop() sets _stop_requested",
          worker._stop_requested is True)
    check("request_stop() calls engine.stop() for the pyttsx3 backend",
          fake_engine.stop.called)

    fake_winsound = _fake_winsound()
    worker2 = ov.SpeechWorker("hello again", parent=None)
    worker2._active_backend = "winsound"
    with mock.patch.dict(sys.modules, {"winsound": fake_winsound}):
        worker2.request_stop()
    check("request_stop() calls winsound.PlaySound(None, SND_PURGE) "
          "for the winsound backend",
          fake_winsound.PlaySound.called and
          fake_winsound.PlaySound.call_args[0] == (None, fake_winsound.SND_PURGE))

    worker3 = ov.SpeechWorker("hello once more", parent=None)
    worker3._active_backend = None  # e.g. the raw OneCore/SAPI path
    try:
        worker3.request_stop()
        no_raise = True
    except Exception:  # noqa: BLE001
        no_raise = False
    check("request_stop() is a safe no-op (never raises) when there's "
          "no interruptible backend tagged yet (e.g. the OneCore/SAPI "
          "path, which stops itself cooperatively instead)", no_raise)
    check("...but still sets _stop_requested so that cooperative path "
          "notices on its own next poll", worker3._stop_requested is True)

    # -- Part B: _speak_with_piper's interruptible async playback ------
    fake_voice = mock.Mock()

    def fake_synthesize_wav(text, wav_file, syn_config=None):
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        # A handful of frames of silence -- enough that the computed
        # clip duration is a small positive number, not zero, so the
        # poll loop below actually has something to wait through.
        wav_file.writeframes(b"\x00\x00" * 2205)  # ~0.1s at 22050 Hz

    fake_voice.synthesize_wav.side_effect = fake_synthesize_wav
    fake_piper_module = types.SimpleNamespace(
        PiperVoice=types.SimpleNamespace(load=lambda path: fake_voice))

    tmp_model = tempfile.NamedTemporaryFile(suffix=".onnx", delete=False)
    tmp_model.close()
    model_path = tmp_model.name

    try:
        # B1: already-interrupted before synthesis finished -> no
        # playback, no started_speaking signal either.
        ov._piper_voice_cache.clear()
        stub_worker = types.SimpleNamespace(
            _stop_requested=True, _active_backend=None,
            started_speaking=mock.Mock())
        fake_winsound2 = _fake_winsound()
        with mock.patch.dict(
                sys.modules,
                {"piper": fake_piper_module, "winsound": fake_winsound2}), \
             mock.patch.object(ov.sys, "platform", "win32"):
            ov._speak_with_piper(
                "this should not actually play", model_path,
                worker=stub_worker)
        check("_speak_with_piper skips playback entirely if the worker "
              "was already told to stop before synthesis finished",
              not fake_winsound2.PlaySound.called)
        check("...and never emits started_speaking in that case either "
              "(nothing is actually about to be heard)",
              not stub_worker.started_speaking.emit.called)

        # B2: normal playback -- plays asynchronously (so it CAN be
        # interrupted), emits started_speaking, and tags the backend.
        ov._piper_voice_cache.clear()
        stub_worker2 = types.SimpleNamespace(
            _stop_requested=False, _active_backend=None,
            started_speaking=mock.Mock())
        fake_winsound3 = _fake_winsound()
        with mock.patch.dict(
                sys.modules,
                {"piper": fake_piper_module, "winsound": fake_winsound3}), \
             mock.patch.object(ov.sys, "platform", "win32"):
            ov._speak_with_piper(
                "this should play normally", model_path,
                worker=stub_worker2)
        check("_speak_with_piper plays (winsound.PlaySound called) when "
              "no stop was requested",
              fake_winsound3.PlaySound.called)
        check("...using SND_ASYNC (not a blocking call) specifically so "
              "a later request_stop() can actually interrupt it -- a "
              "blocking PlaySound() can't reliably be purged cross-thread",
              bool(fake_winsound3.PlaySound.call_args[0][1] & fake_winsound3.SND_ASYNC))
        check("...and tags the worker's _active_backend as 'winsound' "
              "so request_stop() knows how to interrupt it",
              stub_worker2._active_backend == "winsound")
        check("...and emits started_speaking right before playback, "
              "which is what flips the circle's animation to Responding "
              "in sync with the actual audio",
              stub_worker2.started_speaking.emit.called)

        # B3: interruption mid-wait actually cuts the wait short, rather
        # than always running the full clip duration regardless.
        ov._piper_voice_cache.clear()
        stub_worker3 = types.SimpleNamespace(
            _stop_requested=False, _active_backend=None,
            started_speaking=mock.Mock())
        fake_winsound4 = _fake_winsound()

        def fake_long_synthesize_wav(text, wav_file, syn_config=None):
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            # ~5 seconds of silence -- long enough that if interruption
            # didn't work, this check would need a 5s sleep to prove it.
            wav_file.writeframes(b"\x00\x00" * 22050 * 5)

        fake_voice.synthesize_wav.side_effect = fake_long_synthesize_wav

        def flip_stop_after_delay():
            time.sleep(0.1)
            stub_worker3._stop_requested = True

        import threading
        flipper = threading.Thread(target=flip_stop_after_delay)
        with mock.patch.dict(
                sys.modules,
                {"piper": fake_piper_module, "winsound": fake_winsound4}), \
             mock.patch.object(ov.sys, "platform", "win32"):
            started = time.time()
            flipper.start()
            ov._speak_with_piper(
                "this is a long clip that should be cut short",
                model_path, worker=stub_worker3)
            elapsed = time.time() - started
        flipper.join()
        check("interrupting mid-playback actually cuts the wait short "
              "instead of always running out the full ~5s clip duration",
              elapsed < 2.0)
    finally:
        fake_voice.synthesize_wav.side_effect = fake_synthesize_wav
        os.unlink(model_path)
        ov._piper_voice_cache.clear()

    # -- Part C & D: overlay state-machine behavior ---------------------
    with mock.patch.object(ov, "ENABLE_VOICE_MODE", False), \
         mock.patch.object(ov, "ENABLE_SPEECH", False):
        overlay = ov.CircleOverlay()
    try:
        # Part C: clicking mid-RESPONDING interrupts and moves to
        # actively listening for a follow-up, not back to Idle.
        mock_worker = mock.Mock()
        overlay._enter_state(ov.STATE_RESPONDING)
        overlay._speech_worker = mock_worker
        app.processEvents()

        overlay.toggle()
        app.processEvents()

        check("clicking mid-RESPONDING calls request_stop() on the "
              "active speech worker", mock_worker.request_stop.called)
        check("clicking mid-RESPONDING clears the overlay's own "
              "reference to that worker",
              overlay._speech_worker is None)
        check("clicking mid-RESPONDING moves to LISTENING (not Idle)",
              overlay._state == ov.STATE_LISTENING)
        check("clicking mid-RESPONDING starts capturing a follow-up "
              "voice command immediately (no wake word needed)",
              overlay._capturing_voice_command is True)
        check("...and the input text box stays hidden (voice-style "
              "listening, same as right after a wake-word ack)",
              not overlay.input_popup.isVisible())
        overlay._command_timeout_timer.stop()
        overlay._enter_state(ov.STATE_IDLE)
        app.processEvents()

        # Part D: a response finishing on its own also lands in that
        # same actively-listening state first, not straight to Idle.
        overlay._enter_state(ov.STATE_RESPONDING)
        app.processEvents()
        overlay._finish_responding()
        app.processEvents()
        check("a response finishing naturally moves to LISTENING "
              "first, not directly to Idle",
              overlay._state == ov.STATE_LISTENING)
        check("...and is actively capturing a follow-up command",
              overlay._capturing_voice_command is True)
        check("...with the command-capture timeout timer running",
              overlay._command_timeout_timer.isActive())

        # And after that follow-up window times out with nothing heard,
        # it still falls back to idle exactly as before.
        overlay._on_command_capture_timeout()
        app.processEvents()
        check("after the follow-up listening window times out with "
              "nothing heard, it falls back to Idle",
              overlay._state == ov.STATE_IDLE)
        check("...and is no longer marked as capturing a command",
              overlay._capturing_voice_command is False)

        # Sanity: clicking while actually Idle still opens the typed box
        # as before (unaffected by any of the above changes).
        overlay.toggle()
        app.processEvents()
        check("clicking while Idle still opens the typed box as before",
              overlay._state == ov.STATE_LISTENING and
              overlay.input_popup.isVisible())
        overlay._enter_state(ov.STATE_IDLE)

        # -- Part E: Loading stays up until speech actually starts -----
        with mock.patch.object(ov, "SpeechWorker",
                                mock.Mock(return_value=mock.Mock())), \
             mock.patch.object(ov, "ENABLE_SPEECH", True):
            overlay._enter_state(ov.STATE_LOADING)  # as if the AI reply just arrived
            overlay._last_was_error = False
            overlay._show_response("hello, this is the reply", speak=True)
            app.processEvents()
            check("while speech is still starting up (model load / "
                  "synthesis), the circle stays in Loading rather than "
                  "jumping to Responding ahead of any actual audio",
                  overlay._state == ov.STATE_LOADING)
            check("a speech worker was created and started",
                  overlay._speech_worker is not None)

            overlay._on_speech_started()
            app.processEvents()
            check("flips to Responding the instant speech actually "
                  "starts (SpeechWorker.started_speaking)",
                  overlay._state == ov.STATE_RESPONDING)

            overlay._on_speech_finished()
            app.processEvents()
            check("finishing speech still lands in the active-listening "
                  "follow-up state as before, unaffected by the "
                  "Loading-first change",
                  overlay._state == ov.STATE_LISTENING and
                  overlay._capturing_voice_command is True)
            overlay._on_command_capture_timeout()
            app.processEvents()

        # Clicking while still in that Loading-but-about-to-speak window
        # must also interrupt the (already-started) speech worker.
        mock_worker2 = mock.Mock()
        with mock.patch.object(ov, "SpeechWorker",
                                mock.Mock(return_value=mock_worker2)), \
             mock.patch.object(ov, "ENABLE_SPEECH", True):
            overlay._enter_state(ov.STATE_LOADING)
            overlay._show_response("another reply", speak=True)
            app.processEvents()
            check("speech worker is created/started while still in "
                  "Loading, waiting on the started_speaking signal",
                  overlay._speech_worker is mock_worker2 and
                  overlay._state == ov.STATE_LOADING)

            overlay.toggle()
            app.processEvents()
            check("clicking while speech is still only starting up (not "
                  "yet audibly speaking) still interrupts it",
                  mock_worker2.request_stop.called)
            check("...and returns to Idle (nothing is audible yet to "
                  "hand off to an active-listening follow-up for)",
                  overlay._state == ov.STATE_IDLE)
    finally:
        overlay._transition_timer.stop()
        overlay._command_timeout_timer.stop()
        overlay._inactivity_timer.stop()
        overlay.close()
        overlay.deleteLater()
        app.processEvents()

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
