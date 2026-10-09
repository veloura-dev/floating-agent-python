"""Friday's Listen + Speak infrastructure: everything involved in turning
text into spoken audio, and turning your spoken voice into text, lives
here -- split out of agent_overlay.py (which was growing hard to navigate
at 2500+ lines) purely to make the workspace more manageable, with zero
change in behavior. agent_overlay.py still re-exports every name below
that anything else (including dev_tests/) refers to by name, and
agent_overlay.CircleOverlay is still the one place that actually
constructs and wires these classes together -- this file just holds their
definitions.

Contents:
  - Text-to-speech: a local Piper neural voice (preferred, fully offline)
    with classic Windows SAPI5/OneCore as the fallback -- see
    _speak_with_piper/_speak_with_onecore_voice and SpeechWorker, the
    QThread wrapper CircleOverlay actually uses.
  - Speech-to-text: wake-word detection, the voice cross-check
    confirmation heuristics, and VoiceListenWorker -- the QThread that
    continuously listens via the microphone (SpeechRecognition for
    capture, faster-whisper for local transcription, Google's free Web
    Speech API as an automatic fallback).

None of the module-level tunables defined here (USE_PIPER_VOICE,
WHISPER_*, WAKE_WORDS, CONFIRMATION_*, ...) are ever monkeypatched
directly by name in tests -- only agent_overlay.ENABLE_SPEECH,
agent_overlay.ENABLE_VOICE_MODE, agent_overlay.SpeechWorker, and
agent_overlay.AIWorker are (see dev_tests/). Those four stay resolvable
as live attributes of agent_overlay precisely because: ENABLE_SPEECH/
ENABLE_VOICE_MODE are still defined directly in agent_overlay.py (they
gate *whether* to construct these workers, which only ever happens in
agent_overlay.CircleOverlay, so they never needed to move here at all);
and SpeechWorker (this file) is re-exported into agent_overlay.py via a
plain `from overlay_speech import SpeechWorker`, so patching
`agent_overlay.SpeechWorker` still works exactly as before -- CircleOverlay
constructs it by the bare name `SpeechWorker`, which Python resolves
against agent_overlay's own module namespace at call time, regardless of
which file originally defined the class.
"""

import os
import re
import sys
import threading
import time

from PySide6.QtCore import QThread, Signal

TTS_RATE = None    # words per minute, e.g. 175; None = system default
TTS_VOLUME = None  # 0.0-1.0; None = system default
TTS_VOICE_NAME = "Ryan"  # e.g. "Zira", "David", "Hazel", "Microsoft Ava"
# ^ Case-insensitive substring match against the installed voice's name.
# None = whatever your OS uses as its default voice. Run list_voices.py
# (in this folder) to see the exact names installed on your machine, then
# paste one in here — you don't need the full name, just enough to be
# unambiguous (e.g. "Zira" matches "Microsoft Zira Desktop").
# Only used when USE_PIPER_VOICE (below) is False, or if the Piper voice
# fails to load for any reason (missing model file, package not
# installed, etc.) — in that case this is the fallback.
# -------------------------------------------------------------------------

# -------------------------------------------------------------------------
# Optional (recommended): a local neural voice via Piper, instead of
# Windows SAPI. Piper (https://github.com/OHF-Voice/piper1-gpl) is a
# free, open-source, fully offline TTS engine -- no Windows voice
# restrictions (unlike Narrator's "Natural" voices, which third-party
# apps can't use at all), no cloud calls once the one-time voice
# download is done, and no API key.
#
# One-time setup:
#   python -m pip install piper-tts
#   python setup_piper_voice.py
# (see that script for picking a different voice than the default)
#
# If the model file below isn't found, or the piper-tts package isn't
# installed, Friday automatically falls back to the classic SAPI5/OneCore
# settings above instead -- speech always still works either way.
USE_PIPER_VOICE = True
PIPER_VOICE_MODEL = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "voices", "en_GB-northern_english_male-medium.onnx")
# -------------------------------------------------------------------------


_piper_voice_cache = {}


def _get_piper_voice(model_path):
    """Lazily load (and cache) a Piper neural voice model. Raises if the
    piper-tts package isn't installed or the model file is missing --
    callers should catch and fall back to the classic SAPI path."""
    voice = _piper_voice_cache.get(model_path)
    if voice is not None:
        return voice
    if not os.path.isfile(model_path):
        raise FileNotFoundError(
            f"Piper voice model not found at {model_path!r}. Run "
            f"'python setup_piper_voice.py' once to download it, or set "
            f"USE_PIPER_VOICE = False to use a classic Windows voice "
            f"instead.")
    from piper import PiperVoice
    voice = PiperVoice.load(model_path)
    _piper_voice_cache[model_path] = voice
    return voice


def _speak_with_piper(text, model_path, rate=None, volume=None, worker=None):
    """Synthesize `text` with a local Piper neural voice and play it back
    -- fully offline, bypassing Windows SAPI/Narrator entirely (so it
    isn't subject to the restrictions that keep "Natural" voices locked
    to Narrator). Raises on any failure; caller is expected to catch and
    fall back to the classic voice path.

    Playback is started *asynchronously* and then waited out in a
    pollable loop (rather than one blocking call) specifically so it can
    actually be interrupted: a cross-thread winsound.PlaySound(None,
    SND_PURGE) call reliably stops asynchronous playback, but does not
    reliably stop a synchronous/blocking PlaySound() call made on another
    thread -- so a blocking call here would make
    SpeechWorker.request_stop() a no-op in practice.

    If `worker` (the owning SpeechWorker) is given, its `started_speaking`
    signal is emitted right before audio playback actually begins (after
    the voice model has loaded and the text has been synthesized, which
    can take a noticeable beat) -- this is what the circle's "talking"
    animation is synced to, instead of starting the instant the reply
    text arrives. Its `_stop_requested` flag is also checked, both before
    playback starts (skips it entirely if already cancelled) and while
    waiting for it to finish (cuts it short).
    """
    import tempfile
    import wave

    voice = _get_piper_voice(model_path)

    syn_config = None
    try:
        from piper import SynthesisConfig
        if volume is not None or rate is not None:
            kwargs = {}
            if volume is not None:
                kwargs["volume"] = max(0.0, min(1.0, volume))
            if rate is not None:
                # Piper's length_scale is inverse-speed (>1 slower, <1
                # faster), unlike SAPI's words-per-minute -- this is a
                # rough mapping around a ~175 wpm baseline at scale 1.0.
                kwargs["length_scale"] = max(
                    0.3, min(3.0, 175.0 / max(rate, 1)))
            syn_config = SynthesisConfig(**kwargs)
    except ImportError:
        syn_config = None

    out_path = os.path.join(tempfile.gettempdir(), "friday_piper_tts.wav")
    with wave.open(out_path, "wb") as wav_file:
        if syn_config is not None:
            voice.synthesize_wav(text, wav_file, syn_config=syn_config)
        else:
            voice.synthesize_wav(text, wav_file)

    if worker is not None and worker._stop_requested:
        return  # interrupted before playback even started -- nothing to play

    # Read the clip's own duration back from the file we just wrote, so
    # async playback (below) can be waited out for the right amount of
    # time instead of guessing.
    clip_seconds = None
    try:
        with wave.open(out_path, "rb") as rf:
            clip_seconds = rf.getnframes() / float(rf.getframerate() or 22050)
    except Exception:  # noqa: BLE001
        clip_seconds = None

    # Guarded so a reply split into several cue-separated segments (see
    # _parse_speech_cues) still only ever fires this once, on whichever
    # segment actually starts producing audio first -- not once per
    # segment.
    if worker is not None and not getattr(worker, "_started_emitted", False):
        worker._started_emitted = True
        worker.started_speaking.emit()

    if sys.platform == "win32":
        import winsound
        if worker is not None:
            # Tags this worker as currently playing through winsound, so
            # SpeechWorker.request_stop() (called from the UI thread when
            # the circle is clicked) knows winsound.PlaySound(None,
            # SND_PURGE) is the right way to cut this specific playback
            # short -- that call is safe cross-thread (plain Win32 API,
            # not raw COM), unlike the SAPI backends below.
            worker._active_backend = "winsound"
        if clip_seconds is not None:
            winsound.PlaySound(
                out_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            elapsed = 0.0
            step = 0.05
            target = clip_seconds + 0.2  # small buffer for the tail end
            while elapsed < target:
                if worker is not None and worker._stop_requested:
                    break
                time.sleep(step)
                elapsed += step
        else:
            # Couldn't read the clip's own duration back for some reason
            # -- fall back to a plain blocking call rather than guessing
            # (not interruptible in this fallback case, but still speaks).
            winsound.PlaySound(out_path, winsound.SND_FILENAME)
    # On non-Windows dev/test environments there's no stdlib blocking
    # playback API to rely on -- the WAV is still written successfully,
    # which is enough for tests to verify the synthesis path works.



def _find_onecore_voice_token(name_substring):
    """Look up a Windows 10/11 "Natural"/neural voice (e.g. a voice pack
    like "Microsoft Ryan (Natural)") by a case-insensitive substring of
    its name.

    These newer voices live under a different registry category
    (Speech_OneCore) than the classic "Desktop" SAPI5 voices (plain
    Speech) that pyttsx3's getProperty("voices") looks at -- so they're
    completely invisible to pyttsx3 (and to list_voices.py's classic
    listing) even though Narrator/Windows' own voice picker sees them
    fine. Returns a raw SAPI token object if a match is found (which can
    be assigned straight to an SpVoice.Voice property), or None if it's
    missing, this isn't Windows, or pywin32 isn't installed.
    """
    import win32com.client
    wanted = name_substring.lower()
    # Per-machine voices are the common case; per-user is checked too in
    # case a voice pack installed itself there instead (observed with
    # some Store-delivered voice packages).
    for category_id in (
        r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices",
        r"HKEY_CURRENT_USER\SOFTWARE\Microsoft\Speech_OneCore\Voices",
    ):
        try:
            cat = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
            cat.SetId(category_id, False)
            tokens = cat.EnumerateTokens()
        except Exception:  # noqa: BLE001
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
                    continue
            if wanted in (name or "").lower():
                return token
    return None



def _speak_with_onecore_voice(text, token, rate=None, volume=None, worker=None):
    """Speak `text` through a raw SAPI SpVoice pointed at a OneCore
    voice `token` (see _find_onecore_voice_token) -- bypassing pyttsx3
    entirely, since its own voice picker can't address these tokens.

    Speaks asynchronously and polls for completion, instead of one
    blocking Speak() call, so an interruption request (`worker`'s
    `_stop_requested` flag, set from the UI thread when the circle is
    clicked mid-reply) can be noticed and acted on from right here, on
    this same thread -- the SAPI COM voice object this function creates
    isn't safe to reach into from a different thread, so the actual stop
    deliberately happens in this polling loop rather than in
    SpeechWorker.request_stop() itself. Still effectively synchronous
    from the caller's point of view: this call doesn't return until
    speech finishes naturally or is cut short.
    """
    import win32com.client
    raw_voice = win32com.client.Dispatch("SAPI.SpVoice")
    raw_voice.Voice = token
    if rate is not None:
        # SAPI's native Rate is -10 (slowest) .. 10 (fastest), not words
        # per minute -- this is a rough linear approximation around a
        # ~200 wpm baseline at Rate 0, good enough for "a bit faster/
        # slower", not an exact wpm match.
        raw_voice.Rate = max(-10, min(10, round((rate - 200) / 15)))
    if volume is not None:
        raw_voice.Volume = max(0, min(100, round(volume * 100)))

    SVSF_ASYNC = 1
    SVSF_PURGE_BEFORE_SPEAK = 2
    SPRS_IS_SPEAKING = 2

    raw_voice.Speak(text, SVSF_ASYNC)
    # Guarded the same way as _speak_with_piper's equivalent emit above --
    # see that comment.
    if worker is not None and not getattr(worker, "_started_emitted", False):
        worker._started_emitted = True
        worker.started_speaking.emit()
    while True:
        if worker is not None and worker._stop_requested:
            try:
                raw_voice.Speak("", SVSF_PURGE_BEFORE_SPEAK)
            except Exception:  # noqa: BLE001
                pass
            break
        try:
            running = raw_voice.Status.RunningState
        except Exception:  # noqa: BLE001
            break  # can't check anymore -- assume it's done rather than loop forever
        if running != SPRS_IS_SPEAKING:
            break
        time.sleep(0.05)


# -------------------------------------------------------------------------
# Speech-delivery cues: speech_delivery.md tells the LLM it may write a
# small set of bracket "stage direction" cues (`[pause]`, `[sighs]`,
# `[whispers]`, ...) to make replies sound more human. Neither Piper nor
# classic SAPI/pyttsx3 can actually perform a sigh, a chuckle, or a true
# mid-sentence prosody change -- there's no feature for that, and reading
# the bracket text aloud as literal words would sound broken -- so every
# recognized cue is converted here into the nearest honest mechanical
# equivalent instead: a real timed beat of silence (sized to the cue),
# and, for `[whispers]`/`[voice softens]` specifically, a temporary volume
# drop on the words that immediately follow it. The cue text itself is
# never spoken and never shown anywhere (see _strip_cues_for_display for
# anywhere the reply is actually displayed, e.g. the IDE's chat panel).
#
# (seconds, volume_scale_for_the_text_right_after | None)
_KNOWN_SPEECH_CUES = {
    "pause": (0.35, None),
    "brief pause": (0.2, None),
    "long pause": (0.75, None),
    "inhales": (0.25, None),
    "deep breath": (0.5, None),
    "exhales": (0.25, None),
    "sighs": (0.4, None),
    "soft sigh": (0.3, None),
    "hmm": (0.15, None),
    "chuckles": (0.3, None),
    "laughs softly": (0.35, None),
    "clears throat": (0.3, None),
    "whispers": (0.1, 0.55),
    "voice softens": (0.1, 0.7),
    "voice trembles": (0.15, None),
}
_DEFAULT_UNKNOWN_CUE = (0.2, None)  # any other short bracket "[...]" tag

# A short, word-like bracket tag not immediately followed by "(" -- the
# lookahead avoids ever matching a markdown link like "[text](url)".
_CUE_TAG_RE = re.compile(r"\[([a-zA-Z][a-zA-Z '\-]{0,40})\](?!\()")

# Pause-family cues are the only ones that still imply something useful
# when a reply is *displayed* as text rather than spoken (see
# _strip_cues_for_display) -- an ellipsis reads naturally in their place;
# every other cue is simply dropped from displayed text.
_PAUSE_DISPLAY_TAGS = {"pause", "brief pause", "long pause"}


def _parse_speech_cues(text):
    """Splits raw reply text (which may contain the bracket cues
    speech_delivery.md tells the LLM it can use) into an ordered list of
    ops for SpeechWorker to actually perform:
      {"type": "speak", "text": str, "volume_scale": float}
      {"type": "pause", "seconds": float}
    Empty/whitespace-only spoken chunks are dropped. Unrecognized cues
    still produce a short generic pause rather than being read aloud --
    better to under-react to an unexpected tag than to ever speak one
    literally.
    """
    ops = []
    pos = 0
    pending_volume_scale = 1.0
    for m in _CUE_TAG_RE.finditer(text):
        chunk = text[pos:m.start()]
        if chunk.strip():
            ops.append({"type": "speak", "text": chunk.strip(),
                        "volume_scale": pending_volume_scale})
            pending_volume_scale = 1.0  # only carries into the next chunk
        tag = re.sub(r"\s+", " ", m.group(1).strip().lower())
        pause_s, vol_scale = _KNOWN_SPEECH_CUES.get(tag, _DEFAULT_UNKNOWN_CUE)
        if pause_s:
            ops.append({"type": "pause", "seconds": pause_s})
        if vol_scale is not None:
            pending_volume_scale = vol_scale
        pos = m.end()
    tail = text[pos:]
    if tail.strip():
        ops.append({"type": "speak", "text": tail.strip(),
                    "volume_scale": pending_volume_scale})
    return ops


def _strip_cues_for_display(text):
    """Returns `text` with every bracket speech-delivery cue removed --
    for anywhere a reply is actually shown as readable text (the IDE's
    "Friday AI Chat" panel, or the floating circle's own fallback
    "how long would this take to read" estimate) rather than spoken.
    Pause-family cues become a plain ellipsis, so a beat is still implied
    visually; everything else is simply dropped. The exact same cue text
    is parsed again, separately, for real timed pauses + volume ducking
    when a reply is spoken aloud instead -- see _parse_speech_cues.
    """
    def _sub(m):
        tag = re.sub(r"\s+", " ", m.group(1).strip().lower())
        return "\u2026" if tag in _PAUSE_DISPLAY_TAGS else ""

    cleaned = _CUE_TAG_RE.sub(_sub, text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([.,!?;:])", r"\1", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _interruptible_sleep(worker, seconds):
    """time.sleep(seconds), but checked in small steps against
    `worker._stop_requested` so a mid-reply interruption (clicking the
    circle while Friday is talking) can actually cut a cue-pause short
    instead of silently finishing it out."""
    step = 0.05
    elapsed = 0.0
    while elapsed < seconds:
        if worker is not None and worker._stop_requested:
            return
        time.sleep(min(step, seconds - elapsed))
        elapsed += step


class SpeechWorker(QThread):
    """Speaks text aloud with the OS's default voice, off the UI thread.

    The text may contain speech_delivery.md's bracket cues (`[pause]`,
    `[sighs]`, `[whispers]`, ...) -- see _parse_speech_cues, which this
    splits the reply into before any backend below ever sees it, so cue
    tags are never themselves spoken as literal words.
    """

    finished_speaking = Signal()
    started_speaking = Signal()

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._text = text
        self._stop_requested = False
        # Set the instant the first segment of this reply actually starts
        # producing audio, so a reply split into several cue-separated
        # segments still only ever fires started_speaking once (the UI's
        # "talking" animation cares about the reply as a whole, not about
        # each individual segment between pauses).
        self._started_emitted = False
        # Which backend is actively playing audio right now, if any --
        # set just before playback starts in whichever branch below ends
        # up speaking, and read by request_stop() (called from the UI
        # thread) to decide how to interrupt it. "sapi_onecore" doesn't
        # use this -- it stops itself cooperatively from its own polling
        # loop instead, since its COM object isn't safe to touch here.
        self._active_backend = None  # "winsound" | "pyttsx3" | None
        self._active_handle = None   # the pyttsx3 engine, when applicable

    def request_stop(self):
        """Ask whatever this worker is currently speaking through to stop
        immediately. Called from the UI thread (clicking the circle
        mid-RESPONDING) -- never blocks, never raises. If the active
        backend can't be stopped for some reason, the worker thread is
        simply left to keep running in the background and finish (or
        fail) on its own; the UI has already moved on regardless, since
        nothing waits on this thread.
        """
        self._stop_requested = True
        backend = self._active_backend
        handle = self._active_handle
        try:
            if backend == "winsound":
                import winsound
                # Plain Win32 API, not raw COM -- safe to call cross-thread.
                # Stops whatever winsound is currently playing right now.
                winsound.PlaySound(None, winsound.SND_PURGE)
            elif backend == "pyttsx3" and handle is not None:
                handle.stop()
            # "sapi_onecore": nothing to do here -- see
            # _speak_with_onecore_voice, which polls _stop_requested on
            # its own thread instead.
        except Exception:  # noqa: BLE001
            pass

    def _effective_volume(self, base_volume, segment):
        """Combines the configured TTS_VOLUME (or a backend's own default
        of effectively 1.0 when that's None) with a segment's
        volume_scale (see _parse_speech_cues -- only [whispers]/
        [voice softens] ever set this to anything but 1.0). Returns None
        -- meaning "leave the backend's own default alone" -- only when
        there's truly nothing to apply, so a normal reply with no
        whisper cues behaves exactly as before this feature existed.
        """
        scale = segment.get("volume_scale", 1.0)
        if scale == 1.0 and base_volume is None:
            return None
        return max(0.0, min(1.0, (base_volume if base_volume is not None else 1.0) * scale))

    def _speak_segments_piper(self, segments):
        """Speaks every "speak" op through Piper, honoring "pause" ops as
        real timed silence in between. Raises only if the very first
        spoken segment fails -- at that point nothing has been said yet,
        so it's still safe for the caller to fall back to the classic
        Windows voice for the whole reply. A failure on a *later* segment
        (after Piper has already spoken something) instead just stops
        here rather than risking the reply being spoken twice via a
        fallback.
        """
        said_something = False
        for seg in segments:
            if self._stop_requested:
                return
            if seg["type"] == "pause":
                _interruptible_sleep(self, seg["seconds"])
                continue
            text = seg["text"]
            if not text:
                continue
            volume = self._effective_volume(TTS_VOLUME, seg)
            try:
                _speak_with_piper(
                    text, PIPER_VOICE_MODEL,
                    rate=TTS_RATE, volume=volume, worker=self)
                said_something = True
            except Exception:
                if not said_something:
                    raise  # nothing played yet -- safe to fall back entirely
                return  # already spoke part of this reply -- stop, don't duplicate

    def run(self):
        com_initialized = False
        try:
            if self._stop_requested:
                return

            segments = _parse_speech_cues(self._text)
            if not segments:
                return

            if USE_PIPER_VOICE:
                piper_ready = False
                try:
                    _get_piper_voice(PIPER_VOICE_MODEL)  # pre-flight only
                    piper_ready = True
                except Exception:
                    piper_ready = False
                if piper_ready:
                    try:
                        self._speak_segments_piper(segments)
                    except Exception:
                        # Already said something via Piper when this was
                        # raised -- see _speak_segments_piper's own
                        # docstring on why that means "stop", not "fall
                        # back and risk saying it twice".
                        pass
                    return

            if self._stop_requested:
                return

            # SAPI5 (Windows TTS) relies on COM, which needs to be
            # initialized on whichever thread uses it. pywin32 (pulled in
            # automatically by pyttsx3 on Windows) provides this.
            try:
                import pythoncom
                pythoncom.CoInitialize()
                com_initialized = True
            except ImportError:
                pass  # not on Windows / pywin32 not available — fine elsewhere

            import pyttsx3

            engine = pyttsx3.init()
            if TTS_RATE is not None:
                engine.setProperty("rate", TTS_RATE)
            if TTS_VOLUME is not None:
                engine.setProperty("volume", TTS_VOLUME)
            onecore_token = None
            if TTS_VOICE_NAME:
                wanted = TTS_VOICE_NAME.lower()
                matched_classic = False
                for voice in engine.getProperty("voices"):
                    if wanted in (voice.name or "").lower():
                        engine.setProperty("voice", voice.id)
                        matched_classic = True
                        break
                if not matched_classic:
                    # Not one of the classic "Desktop" voices pyttsx3 can
                    # see -- it might still be a newer Windows "Natural"
                    # voice pack (e.g. "Microsoft Ryan (Natural)"), which
                    # lives in a registry spot pyttsx3 never looks at.
                    try:
                        onecore_token = _find_onecore_voice_token(
                            TTS_VOICE_NAME)
                    except Exception:  # noqa: BLE001
                        onecore_token = None
                # If neither matches, silently keep the system default
                # rather than erroring out — speech still works either way.

            if self._stop_requested:
                return

            base_volume = TTS_VOLUME

            if onecore_token is not None:
                said_something = False
                fell_back = False
                try:
                    for seg in segments:
                        if self._stop_requested:
                            return
                        if seg["type"] == "pause":
                            _interruptible_sleep(self, seg["seconds"])
                            continue
                        text = seg["text"]
                        if not text:
                            continue
                        volume = self._effective_volume(base_volume, seg)
                        _speak_with_onecore_voice(
                            text, onecore_token,
                            rate=TTS_RATE, volume=volume, worker=self)
                        said_something = True
                except Exception:  # noqa: BLE001
                    fell_back = True
                if fell_back and not said_something and not self._stop_requested:
                    # Nothing was said yet via the OneCore voice -- safe to
                    # fall back to whatever pyttsx3 already has configured,
                    # for the whole reply, same as before this feature.
                    self._active_backend = "pyttsx3"
                    self._active_handle = engine
                    for seg in segments:
                        if self._stop_requested:
                            break
                        if seg["type"] == "pause":
                            _interruptible_sleep(self, seg["seconds"])
                            continue
                        text = seg["text"]
                        if not text:
                            continue
                        if not self._started_emitted:
                            self._started_emitted = True
                            self.started_speaking.emit()
                        engine.say(text)
                        engine.runAndWait()
            else:
                self._active_backend = "pyttsx3"
                self._active_handle = engine
                default_volume = engine.getProperty("volume")
                for seg in segments:
                    if self._stop_requested:
                        break
                    if seg["type"] == "pause":
                        _interruptible_sleep(self, seg["seconds"])
                        continue
                    text = seg["text"]
                    if not text:
                        continue
                    scale = seg.get("volume_scale", 1.0)
                    if scale != 1.0:
                        try:
                            engine.setProperty(
                                "volume",
                                max(0.0, min(1.0, (default_volume or 1.0) * scale)))
                        except Exception:  # noqa: BLE001
                            pass
                    if not self._started_emitted:
                        self._started_emitted = True
                        self.started_speaking.emit()
                    engine.say(text)
                    engine.runAndWait()
                    if scale != 1.0:
                        try:
                            engine.setProperty("volume", default_volume)
                        except Exception:  # noqa: BLE001
                            pass
            engine.stop()
        except Exception:
            # If TTS isn't available for any reason, fail silently — the
            # text reply is already shown, speech is just a bonus.
            pass
        finally:
            if com_initialized:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
            self.finished_speaking.emit()


# -------------------------------------------------------------------------
# Voice input: wake word + speech-to-text ("listen" stage, replaces typing
# as the default way in). Microphone capture (recording when you start/stop
# talking, ambient-noise calibration) is still handled by the
# SpeechRecognition package — it's good at that part and needs no changes.
# The actual transcription step runs locally through `faster-whisper` (a
# fast CTranslate2 build of OpenAI's Whisper model) so hearing you doesn't
# depend on an internet connection or a cloud service. If faster-whisper
# isn't installed, or its one-time model download never completed (no
# internet the first time Friday ran), transcription quietly falls back to
# the free, keyless Google Web Speech API instead — voice input still
# works, just back to needing a connection. Say the wake word, then either
# the whole request in one breath ("Friday, what's the weather?") or pause
# after it and answer once Friday acknowledges you.
# -------------------------------------------------------------------------
ENABLE_VOICE_MODE = True  # set False to go back to click-to-type-only, no mic used at all

# faster-whisper model settings. "small.en" trades a little speed for
# meaningfully better accuracy than "base.en" on real conversational
# speech (names, longer sentences, accents) -- still comfortably fast on
# a plain CPU for short spoken commands. Every size downloads once (to
# the standard Hugging Face cache folder) the first time Friday starts
# listening, then loads from disk after that. If replies ever feel
# sluggish to start on an older machine, drop back to "base.en" or
# "tiny.en"; if you want even higher accuracy and don't mind a slower
# first-token latency, "medium.en" is the next step up.
WHISPER_MODEL_SIZE = "small.en"
WHISPER_COMPUTE_TYPE = "int8"   # fast on CPU; use "float16"/"int8_float16" if you have a GPU
WHISPER_DEVICE = "cpu"
WHISPER_BEAM_SIZE = 5           # proper beam search (faster-whisper's own default) -- more
                                 # accurate than greedy decoding at a small speed cost

# Common ways speech recognition mishears "Friday" — add more here if
# you notice it missing yours. Matched as a substring against the
# lowercased, punctuation-stripped transcript.
WAKE_WORDS = [
    "friday", "fry day", "fri day", "fridays",
    "hey friday", "hey fry day",
]

# Played (spoken) once the wake word is heard with nothing said after it,
# while the circle shows it's actively listening for the actual request.
WAKE_ACK_PHRASES = [
    "Sir?", "Yes, sir?", "I'm listening.", "Go ahead.", "At your service.",
    "Yes?", "Right here.",
]

# Say something containing one of these (after the wake word) to bring the
# typed text box back up instead of speaking your request.
TEXT_CHAT_TRIGGER_PHRASES = [
    "bring up text chat", "bring up the text chat", "show text chat",
    "open text chat", "open the text box", "open text box",
    "switch to typing", "switch to text", "text mode", "let me type",
    "bring up the keyboard",
]

COMMAND_CAPTURE_TIMEOUT_MS = 8000  # how long to wait for the actual request after the wake-word ack

# How long a silence has to last before SpeechRecognition decides you've
# finished talking and stops recording. SpeechRecognition's own default
# (0.8s) is tuned for short commands and cuts people off mid-sentence on
# any normal thinking/breathing pause -- raised here so a pause doesn't
# get mistaken for the end of what you're saying.
PAUSE_THRESHOLD_SECONDS = 1.5

# Hard ceiling on how long a single utterance can be recorded, regardless
# of pauses -- generous enough for a full sentence or two without letting
# a stuck/open mic record forever.
PHRASE_TIME_LIMIT_SECONDS = 20


def _normalize_for_wake_check(text):
    """Lowercases and strips punctuation, collapsing whitespace, so wake
    word / trigger-phrase matching is forgiving about exact wording."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_wake_command(text):
    """Checks normalized `text` for the wake word. Returns (True, trailing)
    if found, where `trailing` is whatever was said right after it in the
    same breath (may be ""); returns (False, "") if the wake word wasn't
    said at all."""
    normalized = _normalize_for_wake_check(text)
    # Longest phrases first, so e.g. "friday" matches fully instead of "friday"
    # matching its first two characters and leaving "01 ..." as "trailing".
    for phrase in sorted(WAKE_WORDS, key=len, reverse=True):
        idx = normalized.find(phrase)
        if idx != -1:
            return True, normalized[idx + len(phrase):].strip()
    return False, ""


# -------------------------------------------------------------------------
# Voice cross-check confirmation: speech-to-text is never perfect, and a
# misheard word in a long or consequential request (vs. a quick question)
# is a lot more costly to act on by mistake. Any spoken request that trips
# either trigger below gets summarized back as a short yes/no question
# first ("...is that right?") instead of being acted on immediately —
# typed input skips this entirely, since there's no transcription risk to
# guard against there. See AIWorker(summarize_only=True) for how the
# summary itself gets generated, and _handle_voice_command/
# _on_confirmation_reply in CircleOverlay for the actual flow.
# -------------------------------------------------------------------------

# Any spoken request at least this many words long triggers the
# cross-check, regardless of what it's asking for.
CONFIRMATION_WORD_THRESHOLD = 14

# Any of these appearing (as a whole word) triggers the cross-check too,
# even in a short request — these usually mean "go DO something" rather
# than "tell me something", and an acted-on mistake is costlier than an
# answered-wrong one.
CONFIRMATION_ACTION_VERBS = [
    "create", "build", "make", "write", "generate", "implement", "add",
    "install", "run", "execute", "open", "edit", "modify", "update",
    "refactor", "fix", "rename", "move", "delete", "remove", "change",
    "setup", "set up", "configure", "save", "replace", "convert", "deploy",
]

# Phrases that count as confirming Friday's summary was correct, checked as
# whole words/phrases against the normalized reply.
CONFIRMATION_AFFIRMATIVE_PHRASES = [
    "yes", "yeah", "yep", "yup", "correct", "thats right", "thats it",
    "right", "sure", "go ahead", "do it", "confirmed", "affirmative",
    "exactly", "ok", "okay", "please do", "sounds right", "thats correct",
]


def _needs_confirmation(text):
    """True if a spoken request should be summarized back for a yes/no
    before Friday acts on it -- see the constants above for the two
    triggers (long, or action-sounding). Never called for typed input."""
    normalized = _normalize_for_wake_check(text)
    if not normalized:
        return False
    if len(normalized.split()) >= CONFIRMATION_WORD_THRESHOLD:
        return True
    return any(
        re.search(rf"\b{re.escape(verb)}\b", normalized)
        for verb in CONFIRMATION_ACTION_VERBS
    )


def _is_affirmative(text):
    """True if a short spoken reply counts as confirming Friday's summary
    was correct. Anything else (a plain "no", a correction, silence,
    an unrelated new request) is treated as "not confirmed" -- see
    _on_confirmation_reply, which asks the user to just restate it."""
    normalized = _normalize_for_wake_check(text)
    if not normalized:
        return False
    return any(
        re.search(rf"\b{re.escape(phrase)}\b", normalized)
        for phrase in CONFIRMATION_AFFIRMATIVE_PHRASES
    )


# The user-turn prompt swapped in for AIWorker(summarize_only=True) calls
# -- deliberately phrased as a meta-instruction so the model paraphrases
# the request back as a question instead of acting on it. SYSTEM_PROMPT
# (personality.md) is still used as the system instruction underneath
# this, so the confirmation question still sounds like Friday.
CONFIRMATION_SUMMARY_INSTRUCTION = (
    "The user just said this to you by voice, transcribed by "
    "speech-to-text (so it may contain mistranscribed words): "
    "\"{command}\"\n\n"
    "Do NOT perform this request and do NOT call any tools. Instead, "
    "reply with ONLY a single short, natural, spoken-style confirmation "
    "question that restates in your own words what you understood the "
    "request to be, so the user can confirm you heard it correctly "
    "before you act on it. One sentence. No preamble, no tool calls, no "
    "extra commentary -- just the confirmation question itself."
)


def _load_whisper_model():
    """Loads the local faster-whisper model once, up front. Returns the
    model, or None if faster-whisper isn't installed, or its one-time
    download/load fails for any reason (e.g. no internet the very first
    time Friday ever listens) -- callers treat None as "fall back to the
    cloud API", not as a fatal error, so voice input still works either
    way."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    try:
        return WhisperModel(WHISPER_MODEL_SIZE, device=WHISPER_DEVICE,
                            compute_type=WHISPER_COMPUTE_TYPE)
    except Exception:
        return None


def _transcribe_locally(whisper_model, audio):
    """Runs one SpeechRecognition AudioData clip through the local
    faster-whisper model and returns the transcribed text (which may
    legitimately be "" for a clip with no real speech in it). Returns
    None -- not "" -- if local transcription itself isn't usable right
    now (model never loaded, or this specific clip errored), which
    callers use as the signal to fall back to the cloud API instead.
    A plain float32 PCM array is handed to faster-whisper directly
    (skipping its optional ffmpeg-based decoder entirely), so no extra
    system dependency beyond faster-whisper itself is needed."""
    if whisper_model is None:
        return None
    try:
        import numpy as np
        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = whisper_model.transcribe(
            samples, language="en", beam_size=WHISPER_BEAM_SIZE,
            condition_on_previous_text=False)
        return "".join(segment.text for segment in segments).strip()
    except Exception:
        return None


class VoiceListenWorker(QThread):
    """Continuously captures one spoken phrase at a time from the default
    microphone and reports back whatever it understood, off the UI thread,
    until stopped. Deliberately knows nothing about wake words or
    commands -- CircleOverlay decides what any given phrase means; this is
    just a "listen once, report the text" loop that keeps going forever
    (staying quiet whenever paused, e.g. while Friday itself is talking, so it
    never picks up its own voice). Transcription itself runs locally via
    faster-whisper, loaded once up front here, with the free Google Web
    Speech API as an automatic fallback if that's ever unavailable."""

    heard = Signal(str)            # non-empty recognized text
    mic_unavailable = Signal(str)  # friendly reason; the loop exits after this

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False
        self._paused = True  # CircleOverlay calls resume() once it's ready

    def stop(self):
        self._stop_requested = True

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def run(self):
        # PyAudio (needed internally by SpeechRecognition's Microphone) has
        # no prebuilt wheel for brand-new CPython versions for a while
        # after each release (e.g. none exist for 3.14 as of this writing —
        # pip tries to compile it from source and fails without Visual C++
        # build tools). PyAudioWPatch is a maintained fork that does publish
        # wheels for newer Pythons sooner; if the real "pyaudio" isn't
        # importable but the fork is, register it under the "pyaudio" name
        # *before* importing speech_recognition, so speech_recognition's own
        # `import pyaudio` (it doesn't know about the fork) transparently
        # picks it up instead. Harmless no-op if real PyAudio is present.
        if "pyaudio" not in sys.modules:
            try:
                import pyaudio  # noqa: F401
            except ImportError:
                try:
                    import pyaudiowpatch
                    sys.modules["pyaudio"] = pyaudiowpatch
                except ImportError:
                    pass  # neither available — the except below reports it

        try:
            import speech_recognition as sr
        except ImportError:
            self.mic_unavailable.emit(
                "Voice mode needs the SpeechRecognition package (and "
                "PyAudio, or PyAudioWPatch on very new Python versions "
                "where PyAudio has no installable wheel yet) — run: "
                "python -m pip install -r requirements.txt"
            )
            return

        try:
            recognizer = sr.Recognizer()
            recognizer.dynamic_energy_threshold = True
            recognizer.pause_threshold = PAUSE_THRESHOLD_SECONDS
            mic = sr.Microphone()
            with mic as source:
                recognizer.adjust_for_ambient_noise(source, duration=1)
        except Exception as exc:
            self.mic_unavailable.emit(
                f"Couldn't access a microphone ({exc}) — voice mode is "
                "disabled; click the circle to type instead."
            )
            return

        # Loaded in the background, off this thread, so wake-word listening
        # (below) starts responding immediately instead of sitting blocked
        # for however long the first-time model download/load takes (can be
        # a noticeable delay the very first time a given model size is used,
        # or whenever it changes -- faster-whisper has to fetch a brand new
        # file from scratch). `whisper_holder["model"]` starts as None, so
        # every utterance transparently uses the cloud fallback below until
        # loading finishes, then switches over to local transcription with
        # no restart and no interruption to the listen loop.
        whisper_holder = {"model": None}

        def _load_whisper_in_background():
            whisper_holder["model"] = _load_whisper_model()

        threading.Thread(target=_load_whisper_in_background, daemon=True).start()

        while not self._stop_requested:
            if self._paused:
                self.msleep(120)
                continue
            try:
                with mic as source:
                    audio = recognizer.listen(
                        source, timeout=3, phrase_time_limit=PHRASE_TIME_LIMIT_SECONDS
                    )
            except sr.WaitTimeoutError:
                continue  # nobody spoke in the last few seconds — keep looping
            except Exception:
                self.msleep(200)
                continue  # transient mic hiccup — keep trying

            if self._paused or self._stop_requested:
                continue  # dropped while we were capturing (e.g. Friday started talking)

            text = _transcribe_locally(whisper_holder["model"], audio)
            if text is None:
                # Local transcription unavailable/failed for this clip —
                # fall back to the free cloud API so voice input still
                # works (just needs a connection this time).
                try:
                    text = recognizer.recognize_google(audio)
                except (sr.UnknownValueError, sr.RequestError):
                    continue  # couldn't transcribe / network hiccup — ignore and keep listening

            if text and text.strip():
                self.heard.emit(text.strip())
