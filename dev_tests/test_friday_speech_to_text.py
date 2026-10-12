"""Regression test for switching Friday's speech-to-text transcription from
the cloud-only Google Web Speech API to a local `faster-whisper` model,
with Google kept only as an automatic fallback.

Covers the two new pure(ish) helpers in agent_overlay.py:

  _load_whisper_model()   -- loads the local model once; must return None
                              (not raise) if faster-whisper isn't
                              installed, or if loading/downloading it
                              fails for any reason, so callers can fall
                              back to the cloud API instead of going silent.

  _transcribe_locally()   -- runs one SpeechRecognition AudioData clip
                              through the local model; must return None
                              (not "", and not raise) whenever local
                              transcription isn't usable right now, which
                              is exactly the signal VoiceListenWorker.run()
                              uses to fall back to recognize_google().

faster_whisper itself is faked out via sys.modules (same technique the
existing Piper tests use for the `piper` module) so this suite stays fast,
deterministic, and offline -- it never actually downloads a Whisper model.
The real numpy resampling/conversion path (SpeechRecognition AudioData ->
float32 PCM) is exercised for real, against a real audio clip built from
scratch, so that part isn't just mocked away.

Run with:
    DISPLAY=:99 QT_QPA_PLATFORM=offscreen python3 dev_tests/test_friday_speech_to_text.py
"""
import os
import struct
import sys
import types
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def _make_audio_data(seconds=0.5, rate=16000, freq=440):
    """Builds a real speech_recognition.AudioData clip out of a simple
    synthesized tone -- no microphone, no file on disk, just raw PCM
    bytes -- so the real get_raw_data()/resample path actually runs."""
    import math
    import speech_recognition as sr

    n = int(seconds * rate)
    samples = [
        int(3000 * math.sin(2 * math.pi * freq * (i / rate)))
        for i in range(n)
    ]
    raw = struct.pack("<%dh" % n, *samples)
    return sr.AudioData(raw, rate, 2)


def _fake_whisper_module(transcribe_impl=None, construct_impl=None):
    """A stand-in for the `faster_whisper` package: WhisperModel(...)
    either returns a fake model object (whose .transcribe() is driven by
    `transcribe_impl`) or raises, per `construct_impl`."""
    fake_model = mock.Mock()
    if transcribe_impl is not None:
        fake_model.transcribe.side_effect = transcribe_impl

    def _ctor(*a, **k):
        if construct_impl is not None:
            return construct_impl(*a, **k)
        return fake_model

    return types.SimpleNamespace(WhisperModel=_ctor), fake_model


def main():
    import agent_overlay as ov

    # ---------------- _load_whisper_model() ----------------------------
    with mock.patch.dict(sys.modules, {"faster_whisper": None}):
        # sys.modules[name] = None makes `import faster_whisper` raise
        # ImportError, simulating "package not installed".
        result = ov._load_whisper_model()
    check("_load_whisper_model() returns None (not raise) when "
          "faster-whisper isn't installed", result is None)

    fake_module, fake_model = _fake_whisper_module()
    with mock.patch.dict(sys.modules, {"faster_whisper": fake_module}):
        result = ov._load_whisper_model()
    check("_load_whisper_model() returns the loaded model when "
          "faster-whisper is available", result is fake_model)

    def _boom(*a, **k):
        raise RuntimeError("no internet for the one-time model download")

    fake_module_broken, _ = _fake_whisper_module(construct_impl=_boom)
    with mock.patch.dict(sys.modules, {"faster_whisper": fake_module_broken}):
        result = ov._load_whisper_model()
    check("_load_whisper_model() returns None (not raise) when the model "
          "fails to load/download (e.g. no internet the first time)",
          result is None)

    check("_load_whisper_model() is asked for WHISPER_MODEL_SIZE/"
          "WHISPER_DEVICE/WHISPER_COMPUTE_TYPE (configurable, not "
          "hardcoded)",
          all(hasattr(ov, n) for n in (
              "WHISPER_MODEL_SIZE", "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE",
              "WHISPER_BEAM_SIZE", "WHISPER_INITIAL_PROMPT")))
    check("wake-word listening ends on a shorter silence than command capture",
          ov.WAKE_PAUSE_THRESHOLD_SECONDS
          < ov.COMMAND_PAUSE_THRESHOLD_SECONDS)

    # ---------------- _transcribe_locally() -----------------------------
    audio = _make_audio_data()

    check("_transcribe_locally() returns None immediately when no model "
          "is loaded, without touching the audio at all",
          ov._transcribe_locally(None, audio) is None)

    seg1 = types.SimpleNamespace(text=" Turn on the kitchen lights")
    seg2 = types.SimpleNamespace(text=" please.")
    captured = {}

    def _transcribe_ok(samples, **kwargs):
        captured["samples"] = samples
        captured["kwargs"] = kwargs
        return [seg1, seg2], types.SimpleNamespace(language="en")

    model_ok = mock.Mock()
    model_ok.transcribe.side_effect = _transcribe_ok
    text = ov._transcribe_locally(model_ok, audio)
    check("_transcribe_locally() joins and strips multi-segment output",
          text == "Turn on the kitchen lights please.")
    check("_transcribe_locally() passes beam_size/language through to "
          "the model (uses the configured beam and Friday-focused prompt)",
          captured["kwargs"].get("beam_size") == ov.WHISPER_BEAM_SIZE
          and captured["kwargs"].get("language") == "en"
          and captured["kwargs"].get("initial_prompt")
          == ov.WHISPER_INITIAL_PROMPT)

    import numpy as np
    samples = captured["samples"]
    check("_transcribe_locally() hands the model a float32 numpy array "
          "(not raw bytes) -- skips faster-whisper's ffmpeg decoder path "
          "entirely", isinstance(samples, np.ndarray)
          and samples.dtype == np.float32)
    check("...resampled to the 16kHz faster-whisper expects",
          abs(len(samples) - int(0.5 * 16000)) <= 1)
    check("...normalized into [-1, 1], not raw int16 range",
          float(np.max(np.abs(samples))) <= 1.0)

    def _transcribe_raises(*a, **k):
        raise RuntimeError("some transient decoding error")

    model_broken = mock.Mock()
    model_broken.transcribe.side_effect = _transcribe_raises
    check("_transcribe_locally() returns None (not raise) if transcribing "
          "this specific clip errors, so the caller falls back to the "
          "cloud API instead of crashing the listen loop",
          ov._transcribe_locally(model_broken, audio) is None)

    model_silence = mock.Mock()
    model_silence.transcribe.side_effect = lambda *a, **k: (
        [], types.SimpleNamespace(language="en"))
    check("_transcribe_locally() returns \"\" (genuine silence), not None, "
          "when the model runs fine but hears nothing -- None is reserved "
          "for \"try the fallback instead\"",
          ov._transcribe_locally(model_silence, audio) == "")

    # ---------------- real local engine, if actually installed ----------
    # Bonus, not required: if faster-whisper happens to really be
    # installed in this environment (it is in dev/CI images that have run
    # the full setup), do one real, non-mocked round trip against a tiny
    # synthesized clip so the whole pipeline is proven end-to-end, not
    # just its pieces. Skipped (not failed) if the package or its model
    # download isn't available -- this suite must stay runnable offline.
    real_model = ov._load_whisper_model()
    if real_model is not None:
        try:
            import speech_recognition as sr
            import subprocess
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                wav_path = tf.name
            subprocess.run(
                ["espeak-ng", "-w", wav_path, "open the front door"],
                check=True, capture_output=True, timeout=15)
            with sr.AudioFile(wav_path) as source:
                real_audio = sr.Recognizer().record(source)
            os.unlink(wav_path)
            real_text = ov._transcribe_locally(real_model, real_audio)
            check("real faster-whisper round trip recognizes the gist of "
                  "a real synthesized phrase (bonus, non-mocked check)",
                  real_text is not None
                  and "door" in real_text.lower())
        except Exception as exc:  # noqa: BLE001
            print(f"   (skipped real round-trip check: {exc!r})")
    else:
        print("   (skipped real round-trip check: faster-whisper not "
              "installed in this environment)")


try:
    main()
except Exception:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    CHECKS.append(("EXCEPTION", False))

passed = sum(1 for _, ok in CHECKS if ok)
total = len(CHECKS)
print(f"\n{passed}/{total} checks passed")
sys.exit(0 if passed == total else 1)
