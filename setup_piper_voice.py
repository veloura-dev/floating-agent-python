"""
One-time setup for Friday's local neural voice (Piper).

This downloads the actual voice model Friday speaks with. It's a genuinely
offline, open-source TTS engine (https://github.com/OHF-Voice/piper1-gpl)
-- not Windows SAPI, and not Narrator's locked-down "Natural" voices, so
there's no registry hacking or compatibility-breaking Windows updates to
worry about. You only need an internet connection for this one download;
Friday's actual speech afterward never calls out anywhere.

Run it with:
    python -m pip install piper-tts
    python setup_piper_voice.py

That downloads the default voice below (~60 MB) into a `voices` folder
next to this script, which is exactly where agent_overlay.py expects it
(see PIPER_VOICE_MODEL near the top of that file).

Want a different voice? Browse samples at
    https://rhasspy.github.io/piper-samples/
then run this script with that name, e.g.:
    python setup_piper_voice.py en_GB-northern_english_male-medium
and update PIPER_VOICE_MODEL in agent_overlay.py to match (same folder,
just a different filename).
"""

import os
import subprocess
import sys

DEFAULT_VOICE = "en_GB-northern_english_male-medium"


def main():
    voice_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VOICE
    voices_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "voices")
    os.makedirs(voices_dir, exist_ok=True)

    print(f"Downloading Piper voice '{voice_name}' into:\n  {voices_dir}\n")
    print("This is a one-time download (roughly 20-70 MB depending on "
          "quality level) and needs internet access just for this step "
          "-- Friday's speech itself stays fully offline afterward.\n")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "piper.download_voices",
             "--data-dir", voices_dir, voice_name])
    except FileNotFoundError:
        print("Couldn't run the piper downloader. Make sure you've "
              "already installed it with:")
        print("    python -m pip install piper-tts")
        sys.exit(1)

    if result.returncode != 0:
        print("\nSomething went wrong downloading that voice. Double-"
              "check the name (browse options at "
              "https://rhasspy.github.io/piper-samples/) and that "
              "piper-tts is installed:")
        print("    python -m pip install piper-tts")
        sys.exit(result.returncode)

    model_path = os.path.join(voices_dir, f"{voice_name}.onnx")
    print(f"\nDone. Voice model saved to:\n  {model_path}")
    if voice_name != DEFAULT_VOICE:
        print("\nSince this isn't the default voice name, update "
              "PIPER_VOICE_MODEL near the top of agent_overlay.py to "
              f'point at "{voice_name}.onnx" instead, then save.')
    print("\nRun the app again -- Friday should now speak with this voice.")


if __name__ == "__main__":
    main()
