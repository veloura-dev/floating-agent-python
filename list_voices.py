"""
Lists every text-to-speech voice installed on this machine, so you can pick
one for Friday to use instead of the system default.

Run it with:
    python list_voices.py

Then copy the "name" (or a short, unambiguous part of it) of whichever
voice you like into TTS_VOICE_NAME near the top of agent_overlay.py, e.g.:

    TTS_VOICE_NAME = "Zira"

Save agent_overlay.py and run the app again — no other changes needed.

This also looks for Windows' newer "Natural"/neural voice packs (the ones
you install from Settings -> Time & Language -> Speech, e.g. "Microsoft
Ryan (Natural)"). Those are registered in a different SAPI "category"
than the classic voices above, so plain pyttsx3 can't see them at all --
but agent_overlay.py knows to look there too if TTS_VOICE_NAME doesn't
match anything in the classic list, so you can still use them.

Two independent methods are used to find Natural voices, since different
Windows setups can behave differently: the normal SAPI COM lookup, and a
direct registry scan (via Python's built-in winreg, no extra libraries)
as a fallback/cross-check. If one finds a voice the other doesn't, that's
useful diagnostic information -- not a bug in this script.
"""

import pyttsx3

_ONECORE_CATEGORY_IDS = [
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices",
    r"HKEY_CURRENT_USER\SOFTWARE\Microsoft\Speech_OneCore\Voices",
]
_ONECORE_REGISTRY_PATHS = [
    ("HKEY_LOCAL_MACHINE",
     r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"),
    ("HKEY_CURRENT_USER",
     r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"),
]


def _onecore_voices_via_sapi():
    """Natural/neural voices found through SAPI's own COM category
    lookup (the same mechanism agent_overlay.py uses at runtime).
    Returns (names, errors) -- names is a list of display names, errors
    is a list of human-readable strings describing anything that went
    wrong (shown for diagnosis, not silently swallowed)."""
    names, errors = [], []
    try:
        import win32com.client
    except ImportError:
        errors.append("pywin32 (win32com) isn't installed -- this method "
                      "needs it. (`python -m pip install pywin32`)")
        return names, errors
    for category_id in _ONECORE_CATEGORY_IDS:
        try:
            cat = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
            cat.SetId(category_id, False)
            tokens = cat.EnumerateTokens()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{category_id}: {exc}")
            continue
        for i in range(tokens.Count):
            token = tokens.Item(i)
            name = ""
            try:
                name = token.GetAttribute("Name")
            except Exception:  # noqa: BLE001
                pass
            if not name:
                try:
                    name = token.GetDescription()
                except Exception:  # noqa: BLE001
                    name = "(unnamed voice token)"
            names.append(f"{name}  [{category_id}]")
    return names, errors


def _onecore_voices_via_registry():
    """Natural/neural voices found by reading the registry directly
    (pure Python stdlib, no pywin32 needed) -- a cross-check in case the
    SAPI COM method above misses something, e.g. due to a 32-bit vs.
    64-bit registry view mismatch."""
    names, errors = [], []
    try:
        import winreg
    except ImportError:
        errors.append("winreg isn't available (this isn't Windows).")
        return names, errors
    hives = {"HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
            "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER}
    for hive_name, subpath in _ONECORE_REGISTRY_PATHS:
        hive = hives[hive_name]
        try:
            tokens_key = winreg.OpenKey(hive, subpath)
        except OSError as exc:
            errors.append(f"{hive_name}\\{subpath}: {exc}")
            continue
        try:
            i = 0
            while True:
                try:
                    key_name = winreg.EnumKey(tokens_key, i)
                except OSError:
                    break
                i += 1
                display = key_name
                try:
                    with winreg.OpenKey(tokens_key, key_name) as tok:
                        try:
                            v = winreg.QueryValueEx(tok, "")[0]
                            if v:
                                display = v
                        except OSError:
                            pass
                        try:
                            with winreg.OpenKey(tok, "Attributes") as attrs:
                                v = winreg.QueryValueEx(attrs, "Name")[0]
                                if v:
                                    display = v
                        except OSError:
                            pass
                except OSError:
                    pass
                names.append(
                    f"{display}  [{hive_name}\\{subpath}\\{key_name}]")
        finally:
            tokens_key.Close()
    return names, errors


def main():
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    current_rate = engine.getProperty("rate")

    if not voices:
        print("No classic SAPI5 voices were found. Your OS's text-to-"
              "speech engine may not be installed or configured.")
    else:
        print(f"Found {len(voices)} classic SAPI5 voice(s) (these already "
              f"work with Friday today). Current default rate: "
              f"{current_rate} wpm.\n")

        for i, v in enumerate(voices, start=1):
            langs = v.languages if isinstance(v.languages, list) else [v.languages]
            langs = [str(l) for l in langs if l]
            print(f"{i}. {v.name}")
            print(f"   id: {v.id}")
            if langs:
                print(f"   language(s): {', '.join(langs)}")
            if getattr(v, "gender", None):
                print(f"   gender: {v.gender}")
            print()

    sapi_names, sapi_errors = _onecore_voices_via_sapi()
    reg_names, reg_errors = _onecore_voices_via_registry()
    # Merge, de-duplicating by display name (ignoring the bracketed path).
    seen, onecore = set(), []
    for n in sapi_names + reg_names:
        key = n.split("  [", 1)[0].lower()
        if key not in seen:
            seen.add(key)
            onecore.append(n)

    print("-" * 60)
    if onecore:
        print(f"Also found {len(onecore)} newer Windows \"Natural\"/neural "
              "voice pack(s) installed (e.g. voices added from Settings ->")
        print("Speech). These don't show up in the list above -- plain "
              "pyttsx3 can't see them -- but Friday can still use them; it")
        print("automatically falls back to a direct lookup for these if "
              "TTS_VOICE_NAME doesn't match anything above.\n")
        for i, n in enumerate(onecore, start=1):
            print(f"{i}. {n}")
        print()
    else:
        print("No newer Windows \"Natural\"/neural voice packs were found "
              "by either lookup method. If you've installed one (e.g. from")
        print("Settings -> Time & language -> Speech) and it's still not "
              "showing up here, something below may explain why:\n")
        for e in sapi_errors:
            print(f"  [SAPI lookup] {e}")
        for e in reg_errors:
            print(f"  [registry lookup] {e}")
        if not sapi_errors and not reg_errors:
            print("  (Both lookup methods ran without errors and simply "
                  "found nothing -- the voice pack may not have finished")
            print("  installing yet, or may need a restart to register.)")
        print()

    print("-" * 60)
    print("To use one of these, copy its name (or a short distinctive part")
    print('of it, e.g. "Zira", "David", or "Ryan") into TTS_VOICE_NAME near')
    print("the top of agent_overlay.py, then save and run the app again.")
    print()
    print("Want to hear one before deciding? Uncomment and edit the lines")
    print("at the bottom of this script, then run it again.")

    # Uncomment to preview a specific CLASSIC voice out loud before
    # committing to it:
    # engine.setProperty("voice", voices[0].id)   # <- change the index
    # engine.say("This is a preview of this voice.")
    # engine.runAndWait()

    # Uncomment to preview a specific NATURAL/neural voice out loud
    # instead (change the substring to match one printed above):
    # import win32com.client
    # cat = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
    # cat.SetId(
    #     r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices",
    #     False)
    # tokens = cat.EnumerateTokens()
    # raw_voice = win32com.client.Dispatch("SAPI.SpVoice")
    # raw_voice.Voice = tokens.Item(0)   # <- change the index
    # raw_voice.Speak("This is a preview of this natural voice.")


if __name__ == "__main__":
    main()
