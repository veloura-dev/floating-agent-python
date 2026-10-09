"""
Diagnoses why Friday's wake word isn't responding, step by step, using the
exact same microphone/recognizer setup agent_overlay.py uses internally.

Run it with:
    python diagnose_mic.py

It walks through, in order, printing a clear PASS/FAIL for each:
  1. Can "pyaudio" (real or the PyAudioWPatch fallback) be imported at all?
  2. Does SpeechRecognition see any input devices, and which one is default?
  3. Can a Microphone + ambient-noise calibration be opened (same call
     agent_overlay.py makes at startup)?
  4. Does recognizer.listen() actually pick up sound when you speak during
     a 6-second window (this is the step that silently times out forever
     if the wrong device is selected, or the energy threshold calibrated
     too high in a noisy room)?
  5. Does local faster-whisper transcription (or, if unavailable, the
     Google fallback) turn that captured clip into text?

Say something out loud when it says "Listening now..." in step 4 -- the
wake word "Friday" is not required here, just talk normally so there's
something to capture and transcribe.
"""

import sys


def _ok(msg):
    print(f"[PASS] {msg}")


def _fail(msg):
    print(f"[FAIL] {msg}")


def main():
    print("=" * 70)
    print("Friday microphone diagnostic")
    print("=" * 70)

    # Step 1: same PyAudio/PyAudioWPatch shim agent_overlay.py uses.
    if "pyaudio" not in sys.modules:
        try:
            import pyaudio  # noqa: F401
            _ok("real PyAudio is importable")
        except ImportError:
            try:
                import pyaudiowpatch
                sys.modules["pyaudio"] = pyaudiowpatch
                _ok("PyAudioWPatch is importable and registered as 'pyaudio'")
            except ImportError:
                _fail(
                    "neither PyAudio nor PyAudioWPatch is importable -- "
                    "run: python -m pip install PyAudioWPatch"
                )
                return

    try:
        import speech_recognition as sr
    except ImportError:
        _fail("SpeechRecognition isn't installed -- run: python -m pip install -r requirements.txt")
        return
    _ok("SpeechRecognition imported")

    # Step 2: list devices, show which one SpeechRecognition will default to.
    try:
        names = sr.Microphone.list_microphone_names()
    except Exception as exc:
        _fail(f"couldn't list microphone devices at all ({exc})")
        return

    if not names:
        _fail("zero input devices found by PyAudio/PyAudioWPatch -- Windows isn't exposing any microphone to Python")
        return
    _ok(f"{len(names)} input device(s) visible to Python:")
    for i, n in enumerate(names):
        print(f"       [{i}] {n}")

    try:
        import pyaudio as _pa
        pa = _pa.PyAudio()
        default_index = pa.get_default_input_device_info()["index"]
        pa.terminate()
        print(f"       --> default input device index: {default_index} "
              f"({names[default_index] if default_index < len(names) else '?'})")
    except Exception as exc:
        print(f"       --> couldn't determine the default device index ({exc}) "
              "-- not necessarily fatal, but worth noting")

    # Step 3: open + calibrate, exactly like agent_overlay.py's startup.
    try:
        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True
        mic = sr.Microphone()
        print("\nCalibrating for ambient noise (stay quiet for 1 second)...")
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
        _ok(f"microphone opened and calibrated (energy_threshold={recognizer.energy_threshold:.1f})")
    except Exception as exc:
        _fail(f"couldn't open/calibrate the microphone ({exc})")
        print(
            "\nMost likely cause: Windows microphone privacy permissions.\n"
            "Check Settings -> Privacy & security -> Microphone -> make sure\n"
            "'Let apps access your microphone' and the per-app toggle for your\n"
            "terminal/Python are both ON."
        )
        return

    # Step 4: does listen() actually hear anything?
    print("\nListening now for up to 6 seconds -- say something out loud...")
    try:
        with mic as source:
            audio = recognizer.listen(source, timeout=6, phrase_time_limit=6)
        _ok("captured an audio clip (recognizer.listen() returned without timing out)")
    except sr.WaitTimeoutError:
        _fail(
            "timed out -- no speech was detected above the energy threshold "
            "in 6 seconds."
        )
        print(
            "\nThis is the step that fails silently inside the running app too\n"
            "(it just keeps looping forever with no error). Likely causes:\n"
            "  - the wrong device is selected as 'default' (see the device list\n"
            "    above -- if your real mic isn't the default, pick it in Windows\n"
            "    Sound settings: Settings -> System -> Sound -> Input -> set your\n"
            "    microphone as the default device)\n"
            "  - the mic is muted or its input volume is near zero in Windows\n"
            "  - you spoke too quietly / mic gain is very low\n"
            "Try again, speak clearly and a bit louder, right after this script\n"
            "prints 'Listening now...'."
        )
        return
    except Exception as exc:
        _fail(f"unexpected error while listening ({exc})")
        return

    # Step 5: transcribe it, local first then cloud fallback, same as the app.
    try:
        from agent_overlay import _load_whisper_model, _transcribe_locally
        print("\nLoading faster-whisper model (first run downloads it, be patient)...")
        model = _load_whisper_model()
        if model is None:
            print("       faster-whisper unavailable/failed to load -- will use Google fallback only")
        text = _transcribe_locally(model, audio)
        if text is None:
            print("       local transcription unavailable for this clip -- falling back to Google...")
            try:
                text = recognizer.recognize_google(audio)
            except (sr.UnknownValueError, sr.RequestError) as exc:
                _fail(f"Google fallback also couldn't transcribe this clip ({exc})")
                return
        if text and text.strip():
            _ok(f"transcribed: \"{text.strip()}\"")
            print(
                "\nEverything in the mic/transcription pipeline works. If Friday\n"
                "still doesn't respond to the wake word while the app is running,\n"
                "the issue is specifically in wake-word phrase matching or timing,\n"
                "not microphone access -- say so and share what you actually said."
            )
        else:
            _fail("transcription came back empty -- the clip may have been just silence/noise")
    except Exception as exc:
        _fail(f"unexpected error during transcription ({exc})")


if __name__ == "__main__":
    main()
