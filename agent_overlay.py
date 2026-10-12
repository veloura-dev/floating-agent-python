"""
Floating Agent Overlay — now with a real "brain": Gemini (primary) with
Groq and Mistral as fast backup providers, spoken replies, and voice input
with a "Friday" wake word (typing is still available on request).

A frameless, transparent, always-on-top circle that pins itself to the
top-right corner of your screen and floats above every application window
(not just a browser tab).

States:

  IDLE       - small plain circle outline. This is also the default,
               background "always listening for the wake word" state — say
               "Friday" to get its attention. Click to open the
               typed text box instead.
  LISTENING  - circle enlarges and turns blue. Two ways to get here:
                 - you said the wake word with nothing after it — it speaks
                   a short acknowledgment ("Sir?", "Yes?", etc.) and then
                   actively listens for your actual request; or
                 - you clicked the circle, or said something like "bring up
                   text chat" — a small text box pops up so you can type
                   instead (press Enter to send, Esc/click the circle again
                   to cancel).
  LOADING    - circle shrinks back to idle size; the same ring animates as
               a rotating spinner while the AI call is in flight -- and,
               once the reply is back, for as long as speech synthesis
               itself needs to actually start producing audio (so the
               "talking" animation never visibly gets ahead of the sound).
  RESPONDING - circle enlarges again and turns green, shows the animated
               sound-wave/equalizer, and a text bubble shows the reply
               (also spoken aloud). Clicking the circle at any point during
               this state immediately interrupts the speech (cuts it off
               mid-sentence) and drops straight into actively listening for
               your next request, same as finishing normally. Once the
               reply finishes on its own (or is interrupted this way), it
               moves to a brief LISTENING window — ready for a follow-up
               with no need to repeat the wake word — and only falls back
               to Idle (background wake-word listening) after a few
               seconds of silence.

Voice input is heard with `faster-whisper` — a fast, local speech-to-text
engine that runs entirely on your own machine (no internet, no API key,
nothing ever leaves your computer). It downloads its model once, the same
one-time-download shape as Friday's Piper voice. If it isn't installed or its
one-time model download can't complete, voice input quietly falls back to
the free Google Web Speech API (needs internet) so talking to Friday still
works either way — see requirements.txt. The typed box is still there any
time voice isn't convenient: click the circle, or say something like
"bring up text chat".

Voice cross-check confirmation: because speech-to-text can mishear words,
any spoken request that's either long or sounds like it wants Friday to DO
something (as opposed to just answer a question) gets summarized back as
a short yes/no question first — e.g. "...am I to create a header that
adapts to different screen sizes and scales up for larger displays?" —
instead of being acted on immediately. Confirm it (say "yes"/"correct"/
etc.) and it runs for real; say anything else and Friday just asks you to
restate it, no need to repeat the wake word either way. Typed requests
skip this entirely — see _needs_confirmation() near the top of this file
for exactly what triggers it, and CONFIRMATION_WORD_THRESHOLD /
CONFIRMATION_ACTION_VERBS if you want to tune the trigger.

Setup:
    pip install -r requirements.txt
    Add your key(s) to the .env file next to this script:
        GEMINI_API_KEY=...   (free at https://aistudio.google.com/apikey)
        GROQ_API_KEY=...     (free at https://console.groq.com/keys)
        MISTRAL_API_KEY=... (free at https://console.mistral.ai/api-keys)
    python agent_overlay.py

You only need one of the three keys. Together, Gemini, Groq, and Mistral
make up the "think" part of the brain (the LLM step) — Gemini is tried
first, then Groq, then Mistral, each one kicking in automatically only if
every provider before it has no key, is out of quota, or errors out (in
whatever order you've actually configured keys for).
"""


import math
import inspect
import os
import random
import re
import socket
import sys
import threading
import time

# google-genai (the Gemini SDK) logs a one-time, purely informational
# WARNING the first time it sees automatic function calling used via
# generate_content() (it suggests Chat.send_message instead) -- harmless
# either way, this script never accumulates chat history across turns so
# there's no "chat" object to hand the tool loop to. Nothing here
# configures Python's logging module otherwise, so that one log line
# would reach the default "no handler configured" fallback and print
# straight to stderr -- confusing on Windows specifically, where
# PowerShell renders *any* stderr line from a native command as a red
# "NativeCommandError", making a harmless log line look like a crash.
# Capping this one logger at ERROR keeps real failures (which this file
# already surfaces itself, as friendly chat replies) visible while
# dropping that specific noise.
import logging
logging.getLogger("google_genai").setLevel(logging.ERROR)

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property, QRectF, QPointF, QTimer, QThread, QObject, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QGuiApplication, QAction, QPainterPath
from PySide6.QtWidgets import (
    QApplication, QWidget, QMenu, QLineEdit, QHBoxLayout
)

import agent_tools
import memory

# ---- Tunables ----------------------------------------------------------
WINDOW_SIZE = 52          # overall (invisible) window size, gives room to scale
BASE_DIAMETER = 19        # circle diameter at rest / idle / loading
ACTIVE_SCALE = 2.0        # how much bigger it gets while listening / responding
MARGIN_TOP = 16
MARGIN_RIGHT = 16
BORDER_WIDTH = 2.2

FILL_COLOR = QColor(20, 20, 24, 140)          # translucent dark fill
BORDER_COLOR = QColor(255, 255, 255, 210)      # circle outline (idle)
BORDER_COLOR_HOVER = QColor(255, 255, 255, 255)
BORDER_COLOR_LISTENING = QColor(59, 130, 246)   # blue, only while listening
BORDER_COLOR_LOADING = QColor(255, 255, 255, 210)  # spinner-ring color while loading
BORDER_COLOR_RESPONDING = QColor(46, 204, 113)  # green, only while responding
BORDER_COLOR_ERROR = QColor(231, 76, 60)        # red, responding-with-error

ICON_COLOR = QColor(255, 255, 255, 235)        # waveform / spinner / equalizer color

# Equalizer (RESPONDING) bars
WAVE_BAR_COUNT = 7
WAVE_ENVELOPE = [0.40, 0.65, 0.85, 1.00, 0.85, 0.65, 0.40]

LISTEN_RAMP_MS = 700          # time for the flat line to grow into a full waveform

# How long the response bubble stays up before auto-returning to idle
# (rough "reading time" based on reply length), unless dismissed sooner.
# This path only applies when nothing is being spoken aloud (TTS off,
# unavailable, or an empty reply) — when speech IS playing, the real
# trigger is _on_speech_finished (see MAX_SPEECH_SAFETY_MS below), not
# this reading-time estimate.
MIN_RESPONSE_MS = 4000
MAX_RESPONSE_MS = 20000
MS_PER_CHAR = 60

# Safety-net ceiling used ONLY while a spoken reply is actually playing.
# The equalizer/response bubble is meant to stay up for the entire spoken
# reply, however long — that's driven by the finished_speaking signal
# firing exactly when the OS voice engine stops talking, not by this
# timer. This value just guards against a hung/crashed TTS engine that
# never emits that signal, so it's set high enough to comfortably outlast
# any real reply instead of cutting the animation off early.
MAX_SPEECH_SAFETY_MS = 180000  # 3 minutes

# How long the Listening text box waits with no typing before it gives up
# and falls back to idle (covers both a fresh click and the automatic
# re-open after a response finishes speaking).
LISTEN_INACTIVITY_MS = 4000  # ~3-5s

STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_LOADING = "loading"
STATE_RESPONDING = "responding"


def _load_env_file(path=None):
    """Reads KEY=VALUE pairs from a local .env file into os.environ.

    Values already set in the real environment take priority (so you can
    still override via a real env var if you want), but for most people
    the .env file next to this script is the single place to put keys.
    """
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


_load_env_file()

GEMINI_MODEL = "gemini-3.8-flash"
# If the primary model is overloaded/unavailable/retired, try these next,
# in order, before giving up. "gemini-flash-latest" is a Google-maintained
# alias that always points at their current recommended Flash model, so
# it's the most future-proof fallback as models get retired over time.
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]
RETRIES_PER_MODEL = 2          # extra attempts on the *same* model before moving on
RETRY_BACKOFF_SECONDS = 1.5    # multiplied by attempt number between retries

# Hard ceiling on a single network request to any provider. Without this,
# a stalled connection (TCP connects fine but the server/a proxy/a VPN
# silently never sends a reply -- a real, observed failure mode, not a
# hypothetical one) hangs the underlying SDK call forever: no exception,
# no retry, no fallback to the next provider, nothing -- Friday just sits
# there looking unresponsive with no way to tell the difference between
# "thinking" and "stuck." Every provider client below is now built with
# this explicit timeout so a stall surfaces as a real, catchable error
# (classified as connectivity-related by _looks_like_connectivity_error
# below, which arms the same automatic-retry-once-back-online machinery
# a hard connection failure already does) within a bounded, known time
# instead of an indefinite hang.
AI_REQUEST_TIMEOUT_SECONDS = 30

# How many local tool-call round trips Groq/Mistral's own manual
# tool-calling loop (_run_tool_loop below) allows within a single reply,
# before giving up and telling the user to rephrase/split the request.
# (Gemini doesn't use this at all -- passing it plain Python functions
# turns on the SDK's *own* automatic function calling, which runs its
# whole multi-turn loop internally, inside one network call, with its
# own internal cap.) A real multi-file build easily needs far more than
# a handful of these: fetching a skill doc, reading/listing the
# workspace, then a create+write pair per file -- a modest multi-page
# site (HTML/CSS/JS, maybe a couple of extra pages) can genuinely need
# 15-25+ round trips on its own. An ordinary chat reply only needs a
# couple at most and returns as soon as the model stops requesting
# tools either way, so a generous ceiling here costs nothing for small
# asks and only matters for the substantial ones it was too low for.
# Deliberately higher for genuine coding work (the IDE's own embedded
# chat panel, `ide_scoped=True` -- see AIWorker.__init__) than for the
# circle's general-purpose chat, which rarely needs this many.
TOOL_LOOP_MAX_ITERATIONS = 10
TOOL_LOOP_MAX_ITERATIONS_IDE = 40


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def _load_system_prompt(path=None):
    """Loads the assistant's personality/behavior instructions from
    personality.md next to this script, if present, falling back to a
    short built-in default otherwise.

    Edit personality.md to change how the assistant talks, introduces
    itself, banters, and handles emotional topics — no code changes
    needed. This is sent to whichever provider (Gemini/Groq/Mistral)
    actually answers, so the personality is consistent across all three.
    """
    path = path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "personality.md"
    )
    default = (
        "You are a concise voice-style assistant shown in a tiny floating popup. "
        "Keep replies short and conversational (1-4 sentences) unless the user "
        "explicitly asks for more detail."
    )
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                # The personality file defines *how* to talk; this app-specific
                # note makes sure that still fits a tiny popup + spoken reply.
                return (
                    content
                    + "\n\n---\n\n"
                    "Formatting note for this interface: your reply is shown in "
                    "a small floating text popup and read aloud with "
                    "text-to-speech. Keep replies conversational and reasonably "
                    "brief (a sentence or a few) unless the user explicitly asks "
                    "for more detail or a longer explanation. Avoid markdown "
                    "formatting like headers, bold, or bullet-heavy lists — "
                    "plain spoken-style sentences read better here."
                )
        except Exception:
            pass  # fall through to the built-in default below
    return default


def _load_thinking_skills(path=None):
    """Loads the assistant's reasoning/problem-solving method from
    thinking_skills.md next to this script, if present. This is
    deliberately separate from personality.md: that file governs how
    Friday *sounds*, this one governs how he *reasons* -- classifying
    task difficulty, breaking down hard problems, slowing down for
    high-stakes ones, verifying before declaring done, and so on. Edit
    thinking_skills.md to change the reasoning method; no code changes
    needed. Returns "" (not a hard failure) if the file is missing or
    unreadable -- this is additive guidance on top of personality.md's
    SYSTEM_PROMPT, not something the assistant can't function without.
    """
    path = path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "thinking_skills.md"
    )
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                return "\n\n---\n\n" + content
        except Exception:
            pass  # additive guidance only -- never block startup on this
    return ""


def _load_development_skill(path=None):
    """Loads Friday's software-development operating standard from
    development_skill.md next to this script, if present. Separate from
    personality.md (how Friday talks), thinking_skills.md (how Friday
    reasons generally), and speech_delivery.md (how replies sound) --
    this one is specifically the professional engineering discipline for
    IDE/coding work: Definition of Done, the plan -> implement -> validate
    -> review workflow, risk classification, and the anti-patterns list
    (never claim an unrun test passed, never claim something was
    deployed/committed when it wasn't, etc.). It's an adapted version of
    a user-supplied "Professional Software Development Agent Operating
    Standard" -- trimmed of the enterprise CI/CD/production-infra
    content that doesn't apply to this local, no-deploy-pipeline project,
    and reconciled with this project's own already-established autonomy
    rules (finish tasks without checking in after every step; the
    2-minute unanswered-pause rule above governs the cases where a pause
    really is warranted; routine/reversible-via-trash deletions don't
    need authorization). Edit development_skill.md to change the
    engineering standard; no code changes needed. Additive guidance only,
    same as thinking_skills.md: returns "" (not a hard failure) if the
    file is missing or unreadable.
    """
    path = path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "development_skill.md"
    )
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                return "\n\n---\n\n" + content
        except Exception:
            pass  # additive guidance only -- never block startup on this
    return ""


def _load_speech_delivery(path=None):
    """Loads Friday's human-like speech/delivery guidance from
    speech_delivery.md next to this script, if present. Separate from
    personality.md (how Friday talks/banters) and thinking_skills.md
    (how Friday reasons) -- this one is specifically about *delivery*:
    natural pacing, hesitation, emphasis, and the small set of bracket
    cues (`[pause]`, `[sighs]`, `[whispers]`, ...) that overlay_speech.py
    actually gives a real mechanical effect to when the reply is spoken
    aloud (see _parse_speech_cues there) -- not just decorative text.
    Additive guidance only, same as thinking_skills.md: returns "" (not a
    hard failure) if the file is missing or unreadable.
    """
    path = path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "speech_delivery.md"
    )
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                return "\n\n---\n\n" + content
        except Exception:
            pass  # additive guidance only -- never block startup on this
    return ""


SYSTEM_PROMPT = (
    _load_system_prompt() + _load_thinking_skills()
    + _load_development_skill() + _load_speech_delivery()
)


# Groq: a second, very fast LLM provider used as backup. If Gemini has no
# key, is out of quota, or errors out, this kicks in automatically (and
# vice versa if only Groq is configured). Get a free key at
# https://console.groq.com/keys — no credit card required.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_FALLBACK_MODELS = ["llama-3.1-8b-instant"]

# Mistral: a third LLM provider, tried last if both Gemini and Groq are
# unavailable/unconfigured/exhausted. French-made, generous free "Experiment"
# tier. Get a free key (no credit card, phone verification) at
# https://console.mistral.ai/api-keys. Gemini, Groq, and Mistral together
# make up the "think" stage of the brain — whichever one actually answers,
# the rest of the app (display + speech) doesn't care which provider it was.
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_MODEL = "mistral-small-latest"
MISTRAL_FALLBACK_MODELS = ["ministral-8b-latest"]

# Text-to-speech: speaks the reply out loud using the OS's default voice
# (SAPI5 on Windows via pyttsx3 — fully offline, no API, no cost).
ENABLE_SPEECH = True

# Everything else involved in actually speaking text aloud and actually
# listening via the microphone -- the TTS tunables/helpers/SpeechWorker,
# and the wake-word/voice-confirmation helpers/VoiceListenWorker -- lives
# in overlay_speech.py now (split out purely to keep this file a readable
# size; see that module's own docstring for the full rationale and for
# why this stays a plain star-free, explicit re-export rather than a
# `from overlay_speech import *`). Imported with their exact original
# names so every reference below (and every `agent_overlay.NAME` a test
# or another file reaches for) keeps working unchanged.
from overlay_speech import (  # noqa: E402
    ENABLE_VOICE_MODE, USE_PIPER_VOICE, PIPER_VOICE_MODEL,
    TTS_RATE, TTS_VOLUME, TTS_VOICE_NAME,
    WHISPER_MODEL_SIZE, WHISPER_COMPUTE_TYPE, WHISPER_DEVICE,
    WHISPER_BEAM_SIZE, WHISPER_INITIAL_PROMPT,
    WAKE_PAUSE_THRESHOLD_SECONDS, COMMAND_PAUSE_THRESHOLD_SECONDS,
    WAKE_WORDS, WAKE_ACK_PHRASES,
    TEXT_CHAT_TRIGGER_PHRASES, COMMAND_CAPTURE_TIMEOUT_MS,
    PAUSE_THRESHOLD_SECONDS, PHRASE_TIME_LIMIT_SECONDS,
    CONFIRMATION_WORD_THRESHOLD, CONFIRMATION_ACTION_VERBS,
    CONFIRMATION_AFFIRMATIVE_PHRASES, CONFIRMATION_SUMMARY_INSTRUCTION,
    SpeechWorker, VoiceListenWorker,
    _normalize_for_wake_check, _extract_wake_command,
    _needs_confirmation, _is_affirmative,
    _piper_voice_cache, _speak_with_piper, _speak_with_onecore_voice,
    _get_piper_voice, _find_onecore_voice_token,
    _load_whisper_model, _transcribe_locally,
    _strip_cues_for_display,
)


# -------------------------------------------------------------------------
# Connectivity-error classification, shared by all three providers'
# outer catch-alls in AIWorker (_try_gemini/_try_groq/_try_mistral) and
# by AIWorker.run()'s own error-combining logic below. The one goal: any
# time a provider call failed because *the internet itself* isn't
# reachable right now -- not because of a bad API key, a quota limit, or
# the provider's own servers being down -- that failure is tagged with
# this one unmistakable, greppable marker string instead of each
# provider inventing its own wording for the same underlying situation.
# That lets two things happen further down the pipeline that otherwise
# couldn't: (1) AIWorker.run() can collapse 2-3 near-duplicate
# per-provider "can't reach X" messages into one clean sentence when
# *every* provider failed the same way, and (2) whoever submitted the
# request (CircleOverlay / _ide_chat_ask) can recognize "this specific
# kind of failure is worth automatically retrying once the connection
# comes back" (see _ConnectivityRetryTracker) instead of surfacing a
# dead-end error the user would otherwise have to manually retry.
# -------------------------------------------------------------------------
CONNECTIVITY_ERROR_TAG = "🔌 No internet connection detected"

# -------------------------------------------------------------------------
# Per-provider short-term circuit breaker.
#
# AI_REQUEST_TIMEOUT_SECONDS (see its own comment further below) fixed a
# real indefinite-hang bug, but on its own it created a *new*, milder
# but still real problem: if one specific configured provider is
# reliably unreachable for this user (a firewall/VPN/ISP route that
# blocks just that one vendor's domain while everything else on the
# internet works completely fine, for example) — run() still tries it
# FIRST, in the same fixed Gemini -> Groq -> Mistral order, on *every
# single message*, each time paying that provider's full timeout before
# falling through to whichever one actually works. That's exactly what
# "it does eventually answer, but it's slow every single time" looks
# like from the user's side — a real, reported symptom, not a
# hypothetical one.
#
# The fix: the *first* failure for a given provider always gets its
# full, honest timeout and attempt -- this is never used to avoid ever
# trying a provider. Only once it has just failed for a connectivity
# reason does a short cooldown kick in, during which *subsequent*
# messages skip straight past it to the next configured provider
# instead of re-discovering the same "still down" fact the slow way
# every time. A success immediately clears the cooldown, so a
# provider that recovers is tried again right away rather than waiting
# out whatever was left of it.
# -------------------------------------------------------------------------
PROVIDER_SKIP_COOLDOWN_SECONDS = 90
_provider_circuit_lock = threading.Lock()
_provider_last_connectivity_failure = {}  # provider name -> time.time() of last failure


def _provider_recently_unreachable(name):
    """True if `name` (\"Gemini\"/\"Groq\"/\"Mistral\") failed for a
    connectivity reason within the last PROVIDER_SKIP_COOLDOWN_SECONDS."""
    with _provider_circuit_lock:
        last_fail = _provider_last_connectivity_failure.get(name)
    return last_fail is not None and (
        time.time() - last_fail < PROVIDER_SKIP_COOLDOWN_SECONDS)


def _record_provider_connectivity_failure(name):
    with _provider_circuit_lock:
        _provider_last_connectivity_failure[name] = time.time()


def _record_provider_recovered(name):
    """Clears a provider's cooldown -- called the moment it succeeds, so
    a transient blip doesn't keep being skipped after it's actually
    back, rather than waiting for the cooldown to simply expire."""
    with _provider_circuit_lock:
        _provider_last_connectivity_failure.pop(name, None)


def _skipped_provider_message(name):
    """What a provider's error slot is filled with when it's skipped via
    the circuit breaker above rather than actually attempted this round
    -- still carries CONNECTIVITY_ERROR_TAG so run()'s own "every
    provider failed the exact same way" collapsing logic still treats
    it identically to a provider that was actually retried and failed
    again, which is the honest outcome anyway."""
    return (f"{CONNECTIVITY_ERROR_TAG} ({name}, skipped -- it failed for "
            "the same reason very recently; retrying it again shortly).")

# Lowercase substrings matched against an exception's own str() as a
# fallback net, since httpx/requests/urllib3 (whatever each provider's
# SDK happens to wrap under the hood) don't all raise the same plain
# socket/connection exception types for the same real-world failure —
# some wrap it in their own HTTP-client-specific error class with no
# direct inheritance from anything socket-related.
_CONNECTIVITY_ERROR_MARKERS = (
    "name or service not known",
    "name resolution",
    "nodename nor servname",
    "getaddrinfo failed",
    "connection refused",
    "failed to establish a new connection",
    "max retries exceeded",
    "read timed out",
    "connection timed out",
    "network is unreachable",
    "temporary failure in name resolution",
    "connection aborted",
    "connection reset",
    "remote end closed connection",
)


def _looks_like_connectivity_error(exc):
    """True if `exc` (any exception raised while trying to reach an AI
    provider) looks like it was actually caused by *no internet
    connection being available at all*, rather than anything specific
    to that provider (a bad key, a quota limit, the provider's own
    servers being down, a malformed request, etc). Checks the exception
    itself and walks its __cause__/__context__ chain (SDKs commonly
    wrap a raw socket/urllib3 error inside their own exception class via
    `raise ... from exc`, so the connectivity signal is often one or two
    levels down rather than on the exception actually caught), then
    falls back to matching known connectivity-failure phrases in the
    text of the whole chain as a safety net for SDKs/HTTP clients that
    don't chain exceptions the normal way.
    """
    connectivity_types = [
        socket.gaierror, socket.timeout, ConnectionError, TimeoutError, OSError,
    ]
    try:
        # All three provider SDKs (google-genai/groq/mistralai) use httpx
        # under the hood, so a request that hits AI_REQUEST_TIMEOUT_SECONDS
        # above raises one of these -- not a plain TimeoutError/OSError,
        # and its str() is often just a bare "timed out" with none of the
        # phrases in _CONNECTIVITY_ERROR_MARKERS, so without this it would
        # wrongly fall through to a generic, unhelpful "error: timed out"
        # message instead of the proper connectivity message (and the
        # automatic once-back-online retry that message arms). Best
        # effort: if httpx somehow isn't importable, the type/text checks
        # below still catch most real-world cases on their own.
        import httpx
        connectivity_types.append(httpx.TransportError)  # covers Timeout/Connect/etc.
    except Exception:  # noqa: BLE001
        pass
    connectivity_types = tuple(connectivity_types)
    seen = set()
    node = exc
    chain = []
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        chain.append(node)
        if isinstance(node, connectivity_types):
            return True
        node = getattr(node, "__cause__", None) or getattr(node, "__context__", None)
    text = " | ".join(str(n) for n in chain).lower()
    return any(marker in text for marker in _CONNECTIVITY_ERROR_MARKERS)


# -------------------------------------------------------------------------
# Agent Mode: the circle's own position is now completely independent of
# the IDE (it stays pinned to its usual top-right-of-screen spot, or
# wherever the user has dragged it, the whole time) — the only thing
# that still relates the two is the open/close "pop" animation (see
# get_circle_rect() below and ide.py's _play_open_animation/
# _play_close_animation), which uses the circle's *current* on-screen
# spot as the point the IDE visually grows out of / shrinks back into.
# -------------------------------------------------------------------------


class AIWorker(QThread):
    """The "think" part of the brain: runs one prompt through Gemini, then
    Groq, then Mistral as backups, off the UI thread. Tries whichever
    provider(s) have an API key configured, in that order — each one only
    kicks in if every provider before it fails outright (no key, out of
    quota, erroring, etc.). Whichever one actually answers, the rest of
    the app (text display + speech) doesn't need to know or care which."""

    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, prompt, parent=None, summarize_only=False, ide_scoped=False):
        """`summarize_only=True` is used for the voice cross-check
        confirmation step (see _needs_confirmation near the top of this
        file): wraps `prompt` in CONFIRMATION_SUMMARY_INSTRUCTION and
        disables tool-calling for this call entirely, so it can only ever
        produce a short confirmation question back, never actually act on
        the request -- that still happens as a normal, separate, full
        AIWorker(original_text) call once the user confirms.

        `ide_scoped=True` is for prompts that came in through the IDE's
        own embedded "Friday AI Chat" panel (see _ide_chat_ask below): a
        standing requirement that this specific chat surface only ever
        writes/edits/runs code in the open workspace, never
        opens/closes/minimizes panels or anything else Friday's normal
        floating circle can otherwise do. Trims which tools the model is
        even offered (agent_tools.get_ide_chat_gemini_tools/
        get_ide_chat_tool_schemas) and, as a backstop, which ones
        agent_tools.call_tool() will actually run -- see its docstring.
        """
        super().__init__(parent)
        self._summarize_only = summarize_only
        self._ide_scoped = ide_scoped
        self._prompt = (
            CONFIRMATION_SUMMARY_INSTRUCTION.format(command=prompt)
            if summarize_only else prompt
        )
        # The "automatic recall" half of memory (see memory.py's module
        # docstring): whatever's semantically relevant to this prompt,
        # folded into every provider's system prompt below. Deliberately
        # NOT computed here in __init__ -- __init__ runs synchronously on
        # whatever thread constructs this AIWorker (the main/UI thread,
        # for both call sites), so doing a real embedding-API network
        # call here would block the UI before the background thread even
        # starts. It's computed once, up front, in run() instead (see
        # below) -- still a single lookup shared across the
        # Gemini/Groq/Mistral fallback chain, just on the right thread.
        # Skipped entirely for the confirmation-summary call: that call
        # already can't act on anything (no tools), and burning an extra
        # embedding call just to phrase a yes/no question back isn't
        # worth the latency.
        self._memory_context = ""
        # "What's on screen right now" -- which panels are open, which
        # one's active, the IDE's sidebar/active-tab state. Same
        # deliberately-deferred-to-run() reasoning as _memory_context
        # above (a Tk-thread round-trip belongs on the background
        # thread, not __init__ on the UI thread). See
        # agent_tools.get_environment_snapshot().
        self._environment_context = ""

    def _system_prompt(self):
        """SYSTEM_PROMPT (personality.md + thinking_skills.md +
        speech_delivery.md), plus
        whatever's relevant from memory and whatever's currently on
        screen, for this specific prompt -- see __init__'s
        _memory_context/_environment_context above."""
        return SYSTEM_PROMPT + self._memory_context + self._environment_context

    def _load_memory_context(self):
        """Does the actual automatic-recall lookup and stores it in
        self._memory_context. Broken out of run() as its own method so
        it's exactly one call either way: run() calls it for real (on
        the background thread, before trying any provider), and tests
        can call it directly to check the memory-folding logic without
        needing a real/mocked AI provider to exercise all of run().
        No-op for summarize_only calls (see __init__)."""
        if self._summarize_only:
            return
        try:
            self._memory_context = memory.build_context_block(self._prompt)
        except Exception:  # noqa: BLE001
            pass  # memory is a courtesy -- never block a reply on it

    def _load_environment_context(self):
        """Does the actual screen/panel-state lookup and stores it in
        self._environment_context. Broken out of run() for the same
        testability reason as _load_memory_context() above. NOT skipped
        for summarize_only -- the confirmation-summary call still
        benefits from knowing what's open (e.g. phrasing "close that"
        sensibly), and it's a local introspection call, not a network
        one, so there's no extra latency reason to skip it."""
        try:
            self._environment_context = agent_tools.get_environment_snapshot()
        except Exception:  # noqa: BLE001
            pass  # same courtesy-only spirit as memory above


    # -- Gemini ------------------------------------------------------------
    @staticmethod
    def _classify_gemini_quota_error(exc):
        """Google's 429s always say status RESOURCE_EXHAUSTED, for both
        per-minute rate limits *and* per-day quota exhaustion — but the
        error details embed a quotaId that says which one, plus sometimes
        a suggested retryDelay. Returns (is_daily, retry_after_seconds).
        """
        text = str(getattr(exc, "details", "") or exc)
        is_daily = "perday" in text.lower().replace(" ", "")
        match = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', text)
        retry_after = float(match.group(1)) if match else None
        return is_daily, retry_after

    @classmethod
    def _gemini_friendly_message(cls, exc):
        code = getattr(exc, "code", None)
        if code == 429:
            is_daily, retry_after = cls._classify_gemini_quota_error(exc)
            if is_daily:
                return (
                    "⏳ Gemini's free daily quota is used up. It resets at "
                    "midnight Pacific time — try again later, or check "
                    "usage at aistudio.google.com/usage."
                )
            wait_note = f" (~{int(retry_after)}s)" if retry_after else ""
            return f"⏳ Gemini rate limit hit{wait_note}."
        if code in (401, 403):
            return "🔑 Gemini API key problem — check GEMINI_API_KEY in your .env file."
        if code == 404:
            return "🔍 Gemini model not found/retired. Update GEMINI_MODEL in agent_overlay.py."
        return f"⚠️ Gemini error: {exc}"

    def _try_gemini(self):
        """Returns (ok, text_or_none, friendly_error_or_none)."""
        if not GEMINI_API_KEY:
            return False, None, None  # simply not configured — not an error

        try:
            from google import genai
            from google.genai import types, errors
        except Exception as exc:
            return False, None, f"⚠️ google-genai not installed: {exc}"

        try:
            # HttpOptions.timeout is milliseconds, not seconds -- see
            # AI_REQUEST_TIMEOUT_SECONDS's own comment above for why this
            # is set explicitly at all (the SDK's own default is no
            # timeout whatsoever, i.e. an indefinite hang on a stalled
            # connection).
            client = genai.Client(
                api_key=GEMINI_API_KEY,
                http_options=types.HttpOptions(
                    timeout=int(AI_REQUEST_TIMEOUT_SECONDS * 1000)),
            )
            config_kwargs = {"system_instruction": self._system_prompt()}
            if not self._summarize_only:
                # Passing plain Python functions here turns on Gemini's
                # automatic function calling: the SDK introspects each
                # function's type hints/docstring, calls it locally
                # whenever the model requests it, and feeds the result
                # back in — response.text is already the final answer.
                # Omitted entirely for the cross-check summary call (see
                # AIWorker.__init__) so it's physically unable to act.
                config_kwargs["tools"] = (
                    agent_tools.get_ide_chat_gemini_tools() if self._ide_scoped
                    else agent_tools.get_active_gemini_tools()
                )
            config = types.GenerateContentConfig(**config_kwargs)

            # Try the primary model first, then each fallback in turn.
            # Within each model, retry a couple of times on 5xx/overload
            # errors (these are usually transient) before moving on.
            models_to_try = [GEMINI_MODEL] + [
                m for m in FALLBACK_MODELS if m != GEMINI_MODEL
            ]
            last_error = None

            for model_name in models_to_try:
                for attempt in range(RETRIES_PER_MODEL + 1):
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=self._prompt,
                            config=config,
                        )
                        text = (getattr(response, "text", None) or "").strip()
                        return True, (text or "(empty response)"), None
                    except errors.ServerError as exc:
                        last_error = exc
                        if attempt < RETRIES_PER_MODEL:
                            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                        continue
                    except errors.ClientError as exc:
                        last_error = exc
                        code = getattr(exc, "code", None)
                        if code in (401, 403):
                            return False, None, self._gemini_friendly_message(exc)
                        if code == 429:
                            is_daily, retry_after = self._classify_gemini_quota_error(exc)
                            if is_daily:
                                break
                            if attempt < RETRIES_PER_MODEL:
                                wait_s = retry_after or (
                                    RETRY_BACKOFF_SECONDS * (attempt + 1)
                                )
                                time.sleep(min(wait_s, 10))
                                continue
                        break

            return False, None, (
                self._gemini_friendly_message(last_error)
                if last_error is not None
                else "⚠️ Gemini: all models unavailable."
            )
        except Exception as exc:  # noqa: BLE001
            if _looks_like_connectivity_error(exc):
                return False, None, f"{CONNECTIVITY_ERROR_TAG} (Gemini)."
            return False, None, f"⚠️ Gemini error: {exc}"

    # -- shared tool-call loop (Groq + Mistral) -------------------------------
    @staticmethod
    def _run_tool_loop(create_fn, messages, ide_scoped=False,
                        max_iterations=TOOL_LOOP_MAX_ITERATIONS):
        """Multi-turn tool-calling loop shared by Groq and Mistral — both
        expose the same OpenAI-style response shape (response.choices[0]
        .message, with .tool_calls entries exposing .id/.function.name/
        .function.arguments). Executes any requested tool call locally via
        agent_tools.call_tool and feeds the result back in, repeating until
        the model returns a final plain-text answer (or the iteration cap
        is hit, to guarantee this always terminates).

        `create_fn(messages)` should perform exactly one API call and
        return the raw response object. `messages` is mutated in place as
        the conversation grows. `ide_scoped` is forwarded straight to
        agent_tools.call_tool() -- see AIWorker.__init__'s docstring.
        """
        for _ in range(max_iterations):
            response = create_fn(messages)
            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                return (message.content or "").strip()

            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                result = agent_tools.call_tool(
                    tc.function.name, tc.function.arguments, ide_scoped=ide_scoped
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.function.name,
                    "content": result,
                })

        return (
            "Reached the tool-call limit before finishing — try rephrasing "
            "or breaking the request into smaller steps."
        )

    # -- Groq ----------------------------------------------------------------
    @staticmethod
    def _groq_friendly_message(exc):
        import groq

        if isinstance(exc, groq.RateLimitError):
            return "⏳ Groq rate limit hit."
        if isinstance(exc, (groq.AuthenticationError, groq.PermissionDeniedError)):
            return "🔑 Groq API key problem — check GROQ_API_KEY in your .env file."
        if isinstance(exc, groq.NotFoundError):
            return "🔍 Groq model not found. Update GROQ_MODEL in agent_overlay.py."
        if isinstance(exc, groq.InternalServerError):
            return "⚠️ Groq's servers are having issues. Try again shortly."
        if isinstance(exc, (groq.APIConnectionError, groq.APITimeoutError)):
            return f"{CONNECTIVITY_ERROR_TAG} (Groq)."
        if _looks_like_connectivity_error(exc):
            return f"{CONNECTIVITY_ERROR_TAG} (Groq)."
        return f"⚠️ Groq error: {exc}"

    def _try_groq(self):
        """Returns (ok, text_or_none, friendly_error_or_none)."""
        if not GROQ_API_KEY:
            return False, None, None  # simply not configured — not an error

        try:
            import groq
        except Exception as exc:
            return False, None, f"⚠️ groq package not installed: {exc}"

        try:
            # See AI_REQUEST_TIMEOUT_SECONDS's comment above -- explicit
            # here for the same reason, even though Groq's own SDK
            # default (60s) is already bounded rather than infinite.
            client = groq.Groq(api_key=GROQ_API_KEY, timeout=AI_REQUEST_TIMEOUT_SECONDS)
            models_to_try = [GROQ_MODEL] + [
                m for m in GROQ_FALLBACK_MODELS if m != GROQ_MODEL
            ]
            last_error = None

            for model_name in models_to_try:
                for attempt in range(RETRIES_PER_MODEL + 1):
                    try:
                        messages = [
                            {"role": "system", "content": self._system_prompt()},
                            {"role": "user", "content": self._prompt},
                        ]

                        def _create(msgs, _model=model_name):
                            kwargs = {}
                            if not self._summarize_only:
                                # Omitted entirely for the cross-check
                                # summary call (see AIWorker.__init__) so
                                # it's physically unable to act.
                                kwargs["tools"] = (
                                    agent_tools.get_ide_chat_tool_schemas()
                                    if self._ide_scoped
                                    else agent_tools.get_active_tool_schemas()
                                )
                                kwargs["tool_choice"] = "auto"
                            return client.chat.completions.create(
                                model=_model, messages=msgs, **kwargs
                            )

                        text = self._run_tool_loop(
                            _create, messages, ide_scoped=self._ide_scoped,
                            max_iterations=(TOOL_LOOP_MAX_ITERATIONS_IDE
                                            if self._ide_scoped
                                            else TOOL_LOOP_MAX_ITERATIONS),
                        )
                        return True, (text or "(empty response)"), None
                    except (groq.RateLimitError, groq.InternalServerError,
                            groq.APIConnectionError, groq.APITimeoutError) as exc:
                        # Transient — worth a short retry, then fall back.
                        last_error = exc
                        if attempt < RETRIES_PER_MODEL:
                            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                        continue
                    except (groq.AuthenticationError, groq.PermissionDeniedError) as exc:
                        return False, None, self._groq_friendly_message(exc)
                    except groq.APIStatusError as exc:
                        # Model-specific problem — move to next fallback.
                        last_error = exc
                        break

            return False, None, (
                self._groq_friendly_message(last_error)
                if last_error is not None
                else "⚠️ Groq: all models unavailable."
            )
        except Exception as exc:  # noqa: BLE001
            if _looks_like_connectivity_error(exc):
                return False, None, f"{CONNECTIVITY_ERROR_TAG} (Groq)."
            return False, None, f"⚠️ Groq error: {exc}"

    # -- Mistral -----------------------------------------------------------
    @staticmethod
    def _mistral_friendly_message(exc):
        # The mistralai SDK doesn't use one exception class per status code
        # (unlike Groq) — everything raises the same error type with a
        # `.status_code` attribute, so classify off of that instead.
        status = getattr(exc, "status_code", None)
        if status == 429:
            return "⏳ Mistral rate limit hit."
        if status in (401, 403):
            return "🔑 Mistral API key problem — check MISTRAL_API_KEY in your .env file."
        if status == 404:
            return "🔍 Mistral model not found. Update MISTRAL_MODEL in agent_overlay.py."
        if status is not None and status >= 500:
            return "⚠️ Mistral's servers are having issues. Try again shortly."
        if _looks_like_connectivity_error(exc):
            return f"{CONNECTIVITY_ERROR_TAG} (Mistral)."
        return f"⚠️ Mistral error: {exc}"

    def _try_mistral(self):
        """Returns (ok, text_or_none, friendly_error_or_none)."""
        if not MISTRAL_API_KEY:
            return False, None, None  # simply not configured — not an error

        try:
            from mistralai.client import Mistral
            from mistralai.client.errors import MistralError
        except Exception as exc:
            return False, None, f"⚠️ mistralai not installed: {exc}"

        try:
            # See AI_REQUEST_TIMEOUT_SECONDS's comment above.
            client = Mistral(
                api_key=MISTRAL_API_KEY,
                timeout_ms=int(AI_REQUEST_TIMEOUT_SECONDS * 1000),
            )
            models_to_try = [MISTRAL_MODEL] + [
                m for m in MISTRAL_FALLBACK_MODELS if m != MISTRAL_MODEL
            ]
            last_error = None

            for model_name in models_to_try:
                for attempt in range(RETRIES_PER_MODEL + 1):
                    try:
                        messages = [
                            {"role": "system", "content": self._system_prompt()},
                            {"role": "user", "content": self._prompt},
                        ]

                        def _create(msgs, _model=model_name):
                            kwargs = {}
                            if not self._summarize_only:
                                # Omitted entirely for the cross-check
                                # summary call (see AIWorker.__init__) so
                                # it's physically unable to act.
                                kwargs["tools"] = (
                                    agent_tools.get_ide_chat_tool_schemas()
                                    if self._ide_scoped
                                    else agent_tools.get_active_tool_schemas()
                                )
                                kwargs["tool_choice"] = "auto"
                            return client.chat.complete(
                                model=_model, messages=msgs, **kwargs
                            )

                        text = self._run_tool_loop(
                            _create, messages, ide_scoped=self._ide_scoped,
                            max_iterations=(TOOL_LOOP_MAX_ITERATIONS_IDE
                                            if self._ide_scoped
                                            else TOOL_LOOP_MAX_ITERATIONS),
                        )
                        return True, (text or "(empty response)"), None
                    except MistralError as exc:
                        last_error = exc
                        status = getattr(exc, "status_code", None)
                        if status in (401, 403):
                            return False, None, self._mistral_friendly_message(exc)
                        if status == 429 or (status is not None and status >= 500):
                            # Transient — worth a short retry, then fall back.
                            if attempt < RETRIES_PER_MODEL:
                                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                                continue
                        # Any other status (400/404/422/etc.), or retries
                        # exhausted — move on to the next fallback model.
                        break

            return False, None, (
                self._mistral_friendly_message(last_error)
                if last_error is not None
                else "⚠️ Mistral: all models unavailable."
            )
        except Exception as exc:  # noqa: BLE001
            if _looks_like_connectivity_error(exc):
                return False, None, f"{CONNECTIVITY_ERROR_TAG} (Mistral)."
            return False, None, f"⚠️ Mistral error: {exc}"

    def _try_voice_extras(self):
        """Returns (ok, text_or_none, friendly_error_or_none). Last-
        resort tier, tried only after Gemini/Groq/Mistral above have
        all already failed or aren't configured: any REAL EXTRA model
        the user has specifically added under the Settings panel's
        "Voice" faculty (see settings_panel.py/settings_store.py)
        beyond Friday's three original builtin providers -- a second
        key for a provider already in use (more quota), or an entirely
        different OpenAI-compatible endpoint. Routes through
        act_script.py's own region/dispatch plumbing (region_pool/
        call_model) so this never duplicates that logic, but note the
        real trade-off: act_script's dispatch is plain text generation
        only, no tool-calling -- unlike _try_gemini/_try_groq/
        _try_mistral above, a reply from here can't open apps, read
        files, etc. That's acceptable for a last-resort tier (answering
        in plain text beats returning nothing), but it's why this only
        ever runs after every tool-capable builtin option has already
        been exhausted, never before.
        """
        try:
            import act_script
        except Exception:  # noqa: BLE001
            return False, None, None  # Act Script unavailable -- silently skip, not an error

        try:
            entries = act_script.region_pool("voice")
        except Exception:  # noqa: BLE001
            return False, None, None

        # Skip whichever entries are literally the same key(s) already
        # tried above as Gemini/Groq/Mistral (Voice is pre-seeded with
        # those exact three by default -- see settings_store.py) --
        # only a key/entry genuinely beyond that default is worth a
        # fresh attempt here.
        already_tried_keys = {k for k in (GEMINI_API_KEY, GROQ_API_KEY, MISTRAL_API_KEY) if k}
        extras = [e for e in entries if e.get("api_key") not in already_tried_keys]
        if not extras:
            return False, None, None

        last_err = None
        for entry in extras:
            result = act_script.call_model("voice", entry["id"], self._system_prompt(), self._prompt)
            if result.ok:
                return True, result.text, None
            last_err = result.error
        return False, None, (f"⚠️ Voice (extra models): {last_err}" if last_err else None)

    # -- entry point ---------------------------------------------------------
    def run(self):
        if not GEMINI_API_KEY and not GROQ_API_KEY and not MISTRAL_API_KEY:
            # Still worth a real look before giving up entirely: a user
            # may have configured a model only through the Settings
            # panel (see settings_panel.py) -- under Voice for the
            # circle's own plain chat, or under Thinking (or anything
            # that falls back to it) for Act Script's IDE path -- with
            # none of the three original env-var-backed keys set at all.
            has_any_configured_model = False
            try:
                import act_script
                has_any_configured_model = (
                    bool(act_script.region_pool("voice"))
                    or bool(act_script.region_pool("thinking"))
                )
            except Exception:  # noqa: BLE001
                pass
            if not has_any_configured_model:
                self.failed.emit(
                    "No API key found. Add GEMINI_API_KEY, GROQ_API_KEY, and/or "
                    "MISTRAL_API_KEY to the .env file next to agent_overlay.py, "
                    "or add a model under Settings (any region), then try again."
                )
                return

        # Keep IDE chat responsive: use its normal provider tool loop
        # with the strict IDE-only allow-list. The deeper multi-model
        # ACT Script pipeline remains available explicitly through
        # ide_run_act_script for work that warrants its extra planning,
        # verification, and review calls.
        if not self._ide_scoped:
            # Automatic recall and screen-state lookup run here, on the
            # worker thread, never while the UI is constructing it.
            self._load_memory_context()
            self._load_environment_context()

        def _attempt(name, try_fn):
            """Runs one provider's _try_X(), wired into the circuit
            breaker above: skips the call entirely (near-zero cost)
            if this provider just failed for a connectivity reason very
            recently, clears its cooldown the moment it actually
            succeeds, and starts its cooldown the moment it fails for a
            connectivity reason -- see PROVIDER_SKIP_COOLDOWN_SECONDS's
            own comment for why this exists at all."""
            if _provider_recently_unreachable(name):
                return False, None, _skipped_provider_message(name)
            ok, text, err = try_fn()
            if ok:
                _record_provider_recovered(name)
            elif err and CONNECTIVITY_ERROR_TAG in err:
                _record_provider_connectivity_failure(name)
            return ok, text, err

        gemini_ok, gemini_text, gemini_err = _attempt("Gemini", self._try_gemini)
        if gemini_ok:
            self.succeeded.emit(gemini_text)
            return

        groq_ok, groq_text, groq_err = _attempt("Groq", self._try_groq)
        if groq_ok:
            self.succeeded.emit(groq_text)
            return

        mistral_ok, mistral_text, mistral_err = _attempt("Mistral", self._try_mistral)
        if mistral_ok:
            self.succeeded.emit(mistral_text)
            return

        # Last-resort tier: any extra model the user specifically added
        # under Settings -> Voice beyond the three builtins just tried
        # above (see _try_voice_extras' own docstring for the tool-
        # calling trade-off). Not wired into the circuit breaker above --
        # it's already a last resort only reached when everything else
        # just failed, so there's no meaningful "skip it, it's probably
        # still down" cost to save here.
        extra_ok, extra_text, extra_err = self._try_voice_extras()
        if extra_ok:
            self.succeeded.emit(extra_text)
            return

        # All three (plus any configured Voice extras) failed (or
        # weren't configured) — surface the most useful combination of
        # messages we have.
        tried_errors = [
            ("Gemini", gemini_err),
            ("Groq", groq_err),
            ("Mistral", mistral_err),
            ("Voice (extra models)", extra_err),
        ]
        tried_errors = [(name, err) for name, err in tried_errors if err]

        if not tried_errors:
            final_error = "All providers failed."
        elif len(tried_errors) == 1:
            final_error = tried_errors[0][1]
        elif all(CONNECTIVITY_ERROR_TAG in err for _, err in tried_errors):
            # Every provider failed the exact same underlying way — there's
            # no internet, full stop — so 2-3 near-identical "can't reach
            # X" lines would just be noise. One clean message instead,
            # plus a nod to the fact this gets retried automatically (see
            # _ConnectivityRetryTracker) rather than needing the user to
            # ask again once the connection is back.
            final_error = (
                f"{CONNECTIVITY_ERROR_TAG} — I'll keep retrying "
                "automatically once it's back."
            )
        else:
            first_name, first_err = tried_errors[0]
            rest = "\n\n".join(
                f"Also tried {name}: {err}" for name, err in tried_errors[1:]
            )
            final_error = f"{first_err}\n\n{rest}"
        self.failed.emit(final_error)


def _translucent_panel(widget):
    """Give a frameless QWidget a rounded, semi-opaque dark panel look."""
    widget.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    widget.setAttribute(Qt.WA_TranslucentBackground)
    widget.setAttribute(Qt.WA_StyledBackground, True)
    widget.setAttribute(Qt.WA_ShowWithoutActivating, False)
    widget.setStyleSheet(
        "QWidget { background-color: rgba(24, 24, 28, 235); border-radius: 14px; }"
        "QLineEdit { background: transparent; color: white; border: none; "
        "font-size: 13px; }"
        "QLabel { background: transparent; color: white; font-size: 13px; }"
    )


class InputPopup(QWidget):
    """Small text box that appears while LISTENING, replacing mic input."""

    submitted = Signal(str)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        _translucent_panel(self)
        self.setFixedSize(230, 42)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("Type your question…")
        self.edit.returnPressed.connect(self._on_return)
        layout.addWidget(self.edit)

    def _on_return(self):
        text = self.edit.text().strip()
        if text:
            self.submitted.emit(text)
        else:
            self.cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)

    def show_near(self, circle_geo):
        x = circle_geo.x() + circle_geo.width() - self.width()
        y = circle_geo.y() + circle_geo.height() + 8
        self.move(x, y)
        self.edit.clear()
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()


_circle_overlay = None  # the one live CircleOverlay instance, set by its
                        # own __init__ -- used by _ide_chat_ask() below


class _MainThreadInvoker(QObject):
    """A persistent QObject constructed on, and living on, the real Qt
    GUI thread -- its only job is running an arbitrary callable there on
    request, no matter which thread asked. See _on_qt_main_thread()'s
    docstring for why this exists: _ide_chat_ask() can be entered from a
    thread Qt doesn't own at all (the IDE's own dedicated Tk thread, when
    a message comes from its embedded chat panel), and even the AIWorker
    callbacks it sets up for itself run on AIWorker's own background
    QThread rather than this one (see that docstring too). A signal
    connected with Qt.QueuedConnection is the standard, supported way to
    post a call onto a specific QObject's own thread regardless of which
    thread emits it -- unlike connecting straight to a plain Python
    closure (what this file used to do here), which Qt can't detect any
    thread affinity for and so always just runs directly, synchronously,
    on whichever thread emitted the signal.
    """
    _invoke = Signal(object)

    def __init__(self):
        super().__init__()
        self._invoke.connect(self._run, Qt.QueuedConnection)

    def _run(self, fn):
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass


_main_thread_invoker = None  # built in main() below, on the real Qt
                             # thread, once a QApplication exists


def _on_qt_main_thread(fn):
    """Runs fn() on the Qt GUI thread -- safe to call from any thread,
    including ones Qt has never heard of (e.g. the IDE's own dedicated
    Tk thread).

    This matters because CircleOverlay (`ov`, below) is a QWidget: its
    timers, animations, and repaints are only safe to touch from the one
    thread that owns it. Before this existed, _ide_chat_ask() called
    straight into `ov._enter_state(...)` from whatever thread invoked it
    -- the IDE's Tk thread, for a message typed into its embedded chat
    panel -- and `_settle()` below did the same thing again from
    AIWorker's own background QThread once the AI call finished. Both
    are genuine Qt threading violations, not just theoretical: calling
    QTimer.singleShot() from a thread with no Qt event dispatcher of its
    own (confirmed by direct reproduction, not guessed) silently
    schedules a callback that never fires -- which is exactly how the
    IDE's chat panel could look "frozen" (an exchange that never
    resolves, or a reply bubble that lands but leaves the circle stuck
    mid-response) depending on exactly when the dropped callback would
    otherwise have run.

    A silent no-op if there's no QApplication/invoker yet (e.g. a unit
    test exercising _ide_chat_ask in isolation without calling main()) --
    there's then no main thread worth marshaling onto anyway.
    """
    if _main_thread_invoker is None:
        return
    _main_thread_invoker._invoke.emit(fn)


# -------------------------------------------------------------------------
# 2-minute unanswered-pause autonomy rule (personality.md's Agent Mode
# section): when Friday pauses mid-task to ask about a major decision --
# sharing a plan, flagging a risk, asking which of several reasonable
# options to take -- that pause must not block forever. If 120 seconds
# pass with no reply on the same conversation surface, Friday is expected
# to stop waiting, pick the most professional option itself, say so out
# loud, and actually carry the work out.
#
# The one piece of this a model reply alone can never supply is real
# wall-clock awareness -- a single request/response turn has no sense of
# how much time elapses afterward. So the contract is split in two:
#   - the model signals "this reply is a pause I'm waiting on an answer
#     for" by ending it with the literal control tag {{AWAIT_DECISION}}
#     (see personality.md) -- never shown or spoken, stripped by
#     _extract_await_decision below before the reply ever reaches the
#     user, same spirit as speech_delivery.md's bracket cues but a
#     deliberately different bracket style so the two can never collide
#     or be mistaken for one another (see _CUE_TAG_RE in
#     overlay_speech.py);
#   - this file supplies the actual clock: _PendingDecisionTracker arms a
#     real QTimer the moment that tag is seen, and -- if nothing
#     cancels it first, which any new message on that same surface does
#     -- fires a synthetic continuation prompt once the timeout elapses,
#     telling Friday no one answered and to decide and proceed, then
#     delivers whatever it comes back with the normal way (spoken for
#     the circle, a new chat bubble for the IDE's embedded "Friday AI
#     Chat" panel).
#
# Two independent trackers exist -- one per conversation surface (see
# CircleOverlay._decision_tracker and _ide_chat_decision_tracker below) --
# so a pause on one surface never auto-resolves just because the *other*
# surface happens to see activity.
_AWAIT_DECISION_TAG_RE = re.compile(
    r"\{\{\s*AWAIT[_ -]DECISION\s*\}\}\s*", re.IGNORECASE)
AWAIT_DECISION_TIMEOUT_MS = 120_000  # 2 minutes, per the user's standing rule


def _extract_await_decision(text):
    """Returns (clean_text, is_pending_decision). `clean_text` has the
    {{AWAIT_DECISION}} control tag removed -- it's a pure signal to this
    code, never literal content a user should see or hear.
    `is_pending_decision` is True only when the tag was actually present.
    """
    if not text:
        return text, False
    if not _AWAIT_DECISION_TAG_RE.search(text):
        return text, False
    cleaned = _AWAIT_DECISION_TAG_RE.sub("", text).rstrip()
    return cleaned, True


# -------------------------------------------------------------------------
# Inline decision options (Task 65's Permission mechanism): the IDE's own
# embedded "Friday AI Chat" panel renders a pending {{AWAIT_DECISION}}
# pause as clickable option buttons -- plus the chat box's own always-
# present text entry as the free-text "custom option" -- instead of
# leaving the user to retype an answer from scratch, the same spirit as
# this agent's own ask_user tool presenting predefined options alongside
# a custom-response field. A reply signals this by also including
# {{OPTIONS: "Option A" | "Option B" | "Option C"}} right alongside
# {{AWAIT_DECISION}} (see personality.md) -- 2 to 4 short option labels,
# pipe-separated, double-quoted.
#
# IDE-chat-only, deliberately: the floating circle's conversation is
# voice/spoken, where clickable buttons have no meaning -- its own
# decision path (CircleOverlay._decision_tracker) never looks for this
# tag and is never offered it in personality.md's instructions, but as a
# defense-in-depth backstop against a model emitting it somewhere it was
# never asked to, the circle path still runs text through
# _extract_decision_options() and discards the parsed options, purely
# so the raw tag text itself is never spoken aloud or shown (see
# AIWorker._on_reply_ok below).
_OPTIONS_TAG_RE = re.compile(
    r"\{\{\s*OPTIONS\s*:\s*(.*?)\s*\}\}\s*", re.IGNORECASE | re.DOTALL)
_OPTIONS_ITEM_RE = re.compile(r'"([^"]*)"')


def _extract_decision_options(text):
    """Returns (clean_text, options_or_None). `clean_text` has the
    {{OPTIONS: ...}} control tag removed -- same pure-signal spirit as
    _extract_await_decision. `options` is a list of 2-4 short strings
    when the tag was present and parsed at least one quoted option,
    otherwise None (a malformed/empty tag is treated as absent rather
    than raising or showing the user a broken tag).
    """
    if not text:
        return text, None
    m = _OPTIONS_TAG_RE.search(text)
    if not m:
        return text, None
    cleaned = _OPTIONS_TAG_RE.sub("", text).rstrip()
    items = [s.strip() for s in _OPTIONS_ITEM_RE.findall(m.group(1))]
    items = [s for s in items if s][:4]
    return cleaned, (items if items else None)


def _accepts_options_arg(fn):
    """True if `fn` can be called with a 3rd positional argument --
    used to decide whether an on_done-shaped callback gets the new
    `options` parameter or the original 2-arg (ok, text) call, without
    ever actually attempting (and possibly double-performing) the call
    itself to find out. Any callable this can't introspect (some C
    builtins, bound methods wrapping them, etc.) is assumed to accept
    it -- genuinely bare 2-arg callbacks are always plain Python
    functions/lambdas in this codebase, so that case is the one this
    needs to actually detect; the fallback only ever broadens, it never
    narrows, what already worked before this parameter existed.
    """
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return True
    if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
        return True
    positional = [
        p for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                      inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional) >= 3


class _PendingDecisionTracker:
    """One per conversation surface -- see module comment above. Owns at
    most one in-flight 2-minute timer at a time; arming a new one (a
    fresh pause) or cancelling (a new real user message arrived)
    invalidates whatever was pending before via a generation counter,
    rather than holding an actual QTimer handle to stop -- simpler, and
    safe even though arm()/cancel() happen from different call sites
    over the tracker's lifetime.
    """

    def __init__(self, resume, timeout_ms=AWAIT_DECISION_TIMEOUT_MS):
        self._generation = 0
        self._question = None
        self._resume = resume  # resume(question_text) -- called once the timeout fires
        self._timeout_ms = timeout_ms

    def arm(self, question_text):
        """Call only from the Qt main thread (QTimer requirement -- see
        _on_qt_main_thread's docstring for exactly what goes wrong
        otherwise). Starts, or restarts, the clock on `question_text` --
        the cleaned reply Friday just gave, kept only as context for the
        eventual auto-continuation prompt."""
        self._generation += 1
        gen = self._generation
        self._question = question_text
        QTimer.singleShot(self._timeout_ms, lambda: self._fire(gen))

    def cancel(self):
        """Call whenever a new real user message arrives on this
        surface -- the user came back, so whatever was pending no longer
        needs an automatic decision; Friday's ordinary reply to that new
        message handles it instead."""
        self._generation += 1
        self._question = None

    def _fire(self, gen):
        if gen != self._generation:
            return  # answered, or superseded by a newer pause -- stale
        question = self._question
        self._generation += 1
        self._question = None
        if question:
            self._resume(question)


CONNECTIVITY_POLL_MS = 5000  # how often to re-check for a working connection


class _ConnectivityRetryTracker:
    """One per conversation surface (circle / IDE chat panel) -- same
    reasoning as _PendingDecisionTracker's own module comment: a stalled
    request on one surface should never auto-resolve just because
    activity happens on the *other* one. Armed exactly once a request
    fails with CONNECTIVITY_ERROR_TAG in its error message (see
    AIWorker.run() and the three _try_* providers above) -- polls
    agent_tools.has_internet_connectivity() every CONNECTIVITY_POLL_MS
    and, the instant it comes back True, resubmits the *original*
    request text through the normal pipeline exactly once.

    Deliberately re-runs the original request rather than sending a
    synthetic "you're back online, continue" nudge the way the 2-minute
    unanswered-pause rule's auto-continue does: that request never
    actually ran at all (the call failed before the model ever saw it),
    so there's nothing to "continue" -- just retry it for real, with the
    exact text the user (or whatever system event) originally asked for.

    Same generation-counter cancellation pattern as
    _PendingDecisionTracker, but polling on a fixed interval rather than
    firing once after a fixed delay -- "is the internet back yet" is
    inherently a thing that has to be kept checking, not something with
    a single deadline to time out into.
    """

    def __init__(self, resume, poll_ms=CONNECTIVITY_POLL_MS):
        self._generation = 0
        self._resume = resume  # resume(original_text) -- called once connectivity returns
        self._poll_ms = poll_ms

    def arm(self, original_text):
        """Call only from the Qt main thread (QTimer requirement -- see
        _PendingDecisionTracker.arm's docstring). Starts, or restarts,
        polling for connectivity on `original_text`'s behalf."""
        self._generation += 1
        gen = self._generation
        self._schedule_poll(gen, original_text)

    def cancel(self):
        """Call whenever a new real request supersedes the stalled one
        (same trigger point _PendingDecisionTracker.cancel() uses) --
        once the user has moved on, the old stalled request is abandoned
        rather than retried behind their back."""
        self._generation += 1

    def _schedule_poll(self, gen, original_text):
        QTimer.singleShot(self._poll_ms, lambda: self._poll(gen, original_text))

    def _poll(self, gen, original_text):
        if gen != self._generation:
            return  # cancelled, or superseded by a newer arm() -- stale
        if agent_tools.has_internet_connectivity():
            self._generation += 1
            self._resume(original_text)
        else:
            self._schedule_poll(gen, original_text)


_pending_chat_workers = set()  # keeps each _ide_chat_ask() AIWorker alive
                               # until it finishes -- it has no QObject
                               # parent to rely on for that when no
                               # circle is on screen to own it (parent=
                               # the circle would otherwise do this, the
                               # same way the circle's own chat path
                               # keeps its worker alive via self._worker)


def _ide_chat_ask(text, on_done, is_auto_continue=False):
    """Registered with agent_tools.set_chat_handler() in main() below.
    Runs `text` through Friday's normal AI brain -- the exact same AIWorker
    a spoken/typed command goes through -- and calls on_done(ok, result)

    once finished. This is called directly, in-process, by the IDE's own
    embedded 'Friday AI Chat' panel (ide.py's ChatSidePanel) -- no socket,
    no separate process, just a plain function call. Note that this
    still crosses a real thread boundary, though: the IDE runs its own
    dedicated Tk mainloop() thread (see agent_tools._TkThreadBridge), so
    this function's own body executes *there*, not on this process's Qt
    GUI thread -- any touch of `ov` (CircleOverlay, a QWidget) below goes
    through _on_qt_main_thread() rather than calling it directly, for
    exactly that reason. The AIWorker itself is built (and its signals
    connected, and started) entirely on the Qt main thread too, for a
    more subtle reason than ov -- see _start_worker()'s own docstring
    below, this is what was actually silently swallowing every reply
    that came in through this panel.

    Also drives the floating circle's own state (loading -> responding),
    exactly as a chat message typed inside the IDE should visibly
    register on the circle too -- but only when the circle is otherwise
    idle, so it never interrupts an unrelated live voice/typed
    conversation already in progress.

    Standing scope restriction: this AIWorker is constructed with
    ide_scoped=True, so it's only ever offered (and will only ever run)
    the ide_* coding tools -- never the app/window/panel-management
    tools (open_app/minimize_app/etc.) or anything else Friday's normal
    floating circle can do. This chat box is strictly for coding tasks
    in the open workspace; see AIWorker.__init__ and
    agent_tools.get_ide_chat_gemini_tools/call_tool for where that's
    actually enforced.

    `is_auto_continue=True` only for the 2-minute unanswered-pause
    autonomy rule's own synthetic follow-up call (see
    _ide_chat_auto_continue below) -- a real message typed by the user
    into the chat box never sets this. It skips re-cancelling the pause
    timer (the timer firing is *why* this call is happening) and tells
    on_ok/on_fail below not to misattribute the synthetic nudge text to
    the user in memory.
    """
    if not is_auto_continue:
        # A real message just arrived in this chat panel -- any
        # previously-armed 2-minute pause timer for it no longer needs
        # to fire; this message (whether or not it actually answers the
        # pending question) is handled the normal way below instead.
        _ide_chat_decision_tracker.cancel()
        # Same for a stalled connectivity retry -- the user re-engaging
        # with this chat panel (whether or not their new message is
        # actually related to whatever previously failed) supersedes it.
        _ide_chat_connectivity_retry.cancel()
        # A genuine new message clears any stale waiting/done/error pill
        # color from a previous turn immediately -- see
        # agent_tools.report_panel_status's own docstring. Auto-continue/
        # retry calls skip this so *their* own eventual outcome (not a
        # premature reset back to "normal" the instant they start) is
        # what the user sees reflected on the pill.
        agent_tools.report_panel_status("ide", "normal")
    ov = _circle_overlay
    drive_state = (ov is not None and ov._state == STATE_IDLE)
    if drive_state:
        _on_qt_main_thread(lambda: ov._enter_state(STATE_LOADING))

    def _settle(ok):
        if not drive_state:
            return

        def _apply():
            ov._last_was_error = not ok
            if ov._state == STATE_LOADING:
                ov._enter_state(STATE_RESPONDING)
                # Scheduled from right here, inside the main-thread
                # invoker's own callback, so this QTimer is created on
                # the thread that actually runs a Qt event dispatcher --
                # scheduling it from AIWorker's own background thread
                # (as this used to, before _on_qt_main_thread existed)
                # silently drops the callback forever instead of firing
                # it, since that thread has no Qt event loop of its own.
                QTimer.singleShot(2000, ov._finish_responding)

        _on_qt_main_thread(_apply)


    def on_ok(reply):
        _settle(True)
        # 2-minute unanswered-pause autonomy rule: strip the control tag
        # before the reply ever reaches memory or the chat bubble (it's
        # a pure signal, never literal content -- see
        # _extract_await_decision's docstring), and arm this panel's own
        # pause timer when it was present. Done up front, before any of
        # the cue-stripping/memory/display steps below, same as the
        # circle's own _on_reply_ok.
        reply, is_pending_decision = _extract_await_decision(reply)
        # Task 65's Permission mechanism: a companion {{OPTIONS: ...}}
        # tag, only ever meaningful alongside {{AWAIT_DECISION}} on this
        # IDE-chat surface (see _extract_decision_options's module
        # comment) -- parsed here, before display/memory, same reasoning
        # as the await-decision tag just above. `decision_options` is
        # None unless the model actually offered concrete choices.
        reply, decision_options = _extract_decision_options(reply)
        # Unlike the circle's own voice/typed chat path, this reply is
        # never spoken -- the IDE's "Friday AI Chat" panel is a plain
        # text bubble (ide.py's ChatSidePanel._add_bubble) -- so
        # speech_delivery.md's bracket cues ([pause]/[sighs]/[whispers]/
        # ...) would just show up as literal bracket noise here instead
        # of doing anything useful. Clean them out once, up front, and
        # use that same cleaned text for both the visible bubble and
        # memory, so conversation history never carries them either.
        clean_reply = _strip_cues_for_display(reply) if reply else reply
        # Same automatic memory logging the circle's own chat path does
        # (_on_reply_ok above) -- the IDE's chat panel is a second front
        # door onto the exact same AIWorker/"think" stage, so it should
        # feed the same memory rather than being a silent blind spot.
        # remember_recent_turn() is synchronous/instant (no embedding, no
        # disk) so the very next message -- even one typed a second later
        # -- already sees this exchange; log_turn_async() is the slower,
        # permanent, embedded copy for long-term/cross-session recall.
        if text:
            memory.remember_recent_turn("user", text)
            memory.log_turn_async("user", text)
        if clean_reply:
            memory.remember_recent_turn("friday", clean_reply)
            memory.log_turn_async("friday", clean_reply)
        if is_pending_decision:
            # arm() creates a QTimer -- must happen on the Qt main
            # thread (see _on_qt_main_thread's docstring); on_ok itself
            # runs on AIWorker's own background QThread (a plain Python
            # closure connected to a QThread signal runs synchronously
            # on whichever thread emitted it, same reason _settle above
            # marshals its own ov-touching work).
            _on_qt_main_thread(
                lambda: _ide_chat_decision_tracker.arm(clean_reply or reply))
        # Minimized-panel pill color + proactive voice cue (see
        # agent_tools.report_panel_status/CircleOverlay.announce_panel_event):
        # "waiting" (orange) when this reply paused for the user's
        # permission to proceed, "done" (green) otherwise. Scoped
        # deliberately to this chat panel's own worker completions, not
        # the circle's general conversation touching ide_* tools --
        # same per-surface boundary the 2-minute pause rule above
        # already draws.
        agent_tools.report_panel_status("ide", "waiting" if is_pending_decision else "done")
        if agent_tools.is_panel_minimized("ide"):
            announcement = (
                "Sir, the IDE needs your permission before proceeding."
                if is_pending_decision else
                "The IDE is done with its task, sir."
            )
            _on_qt_main_thread(lambda: _announce_panel_event(announcement))
        # Options only ever make sense alongside an actual pending
        # decision -- a stray {{OPTIONS: ...}} tag on an otherwise
        # finished reply (no {{AWAIT_DECISION}}) is ignored rather than
        # rendered, since there would be nothing live to resolve by
        # clicking it.
        _opts = decision_options if is_pending_decision else None
        if _accepts_options_arg(on_done):
            on_done(True, clean_reply, _opts)
        else:
            # Backward-compatible with any `on_done` written before the
            # `options` parameter existed (2-arg signature) -- ide.py's
            # real callback always accepts it, but tests/other callers
            # that only ever cared about (ok, text) shouldn't have to be
            # rewritten just because a feature they don't exercise grew
            # an extra, optional piece of information. Checked by
            # inspecting the signature up front, deliberately not a
            # bare try/except TypeError around the call itself -- that
            # would risk silently double-invoking (and so double-acting
            # on) a callback whose *body* happens to raise its own
            # unrelated TypeError, rather than one that just doesn't
            # accept a 3rd argument.
            on_done(True, clean_reply)

    def on_fail(err):
        _settle(False)
        # Same pill-color treatment for a failure -- red either way, but
        # only a *connectivity* failure also arms the automatic retry
        # (see _ide_chat_connectivity_retry/_ConnectivityRetryTracker):
        # retrying a bad API key or a quota error on its own would just
        # fail again the exact same way, so that's left for the user to
        # actually address.
        agent_tools.report_panel_status("ide", "error")
        is_connectivity = err and CONNECTIVITY_ERROR_TAG in err
        if is_connectivity:
            _on_qt_main_thread(
                lambda: _ide_chat_connectivity_retry.arm(text))
        if agent_tools.is_panel_minimized("ide"):
            announcement = (
                "Sir, the IDE's work has stalled — no internet "
                "connection. I'll resume it automatically once it's "
                "back."
                if is_connectivity else
                "Sir, the IDE ran into a problem and couldn't continue."
            )
            _on_qt_main_thread(lambda: _announce_panel_event(announcement))
        on_done(False, err)

    def _start_worker():
        """Builds, wires up, and starts the AIWorker -- run entirely on
        the Qt main thread via _on_qt_main_thread() below, same as every
        other Qt-touching step in this function, but for a sharper
        reason here: a QThread subclass's OWN signals (succeeded/failed)
        auto-connected to a plain Python callable (on_ok/on_fail below,
        not a bound QObject slot) get delivered via a queued call
        targeting the QThread *object's* own thread affinity -- i.e.
        wherever it was constructed -- not wherever run() itself
        actually executes, and not wherever .connect() happened to be
        called from either. Build it on a thread with no Qt event
        dispatcher of its own (the IDE's Tk thread, in particular) and
        that queued delivery is silently never pumped: on_ok/on_fail
        then never fire at all, which is the actual, complete
        explanation for messages typed into the IDE's chat panel
        appearing to freeze/never go through -- confirmed by direct
        reproduction (a QThread built on a plain background thread,
        emitting a signal connected to a plain function, simply never
        calls it, no error, no warning).

        No QObject parent passed to AIWorker() on purpose -- the circle
        (when there is one) isn't a meaningful "owner" of a chat-panel
        request, and in tests it may not even be a real QObject.
        _pending_chat_workers is what actually keeps this alive until it
        finishes.
        """
        # ide_scoped=True: standing requirement -- the IDE's embedded
        # chat panel is strictly for coding tasks (writing/editing/
        # running code in the open workspace). It must never be able to
        # open/close/minimize panels or do anything else Friday's normal
        # floating circle can otherwise do -- see AIWorker.__init__'s
        # docstring.
        worker = AIWorker(text, parent=None, ide_scoped=True)
        _pending_chat_workers.add(worker)

        def _cleanup():
            _pending_chat_workers.discard(worker)
            worker.deleteLater()

        worker.succeeded.connect(on_ok)
        worker.failed.connect(on_fail)
        worker.finished.connect(_cleanup)
        worker.start()

    _on_qt_main_thread(_start_worker)


def _ide_chat_auto_continue(question):
    """Fires when _ide_chat_decision_tracker's 2-minute no-reply timeout
    elapses -- the user never replied to Friday's last pause-for-a-
    major-decision question in the IDE's embedded chat panel. Per
    personality.md's Agent Mode section, re-runs _ide_chat_ask with a
    synthetic system-level nudge standing in for the user's own next
    message, so the usual AIWorker -> on_ok -> memory flow handles the
    follow-through -- the only difference is where the eventual reply
    lands: nobody is sitting on a `host.ask(...)` call waiting for this
    one (the timer fired on its own, not in response to anything typed
    just now), so it's delivered with agent_tools.notify_ide_chat
    instead of an on_done callback a caller is already holding.
    """
    synthetic = (
        "(System note, not from the user: about two minutes have passed "
        "with no reply to your last question in this chat panel — \"%s\". "
        "No one is coming back to answer it right now. Per the 2-minute "
        "unanswered-pause rule, decide the most professional, reasonable "
        "option yourself, say plainly that you're proceeding without a "
        "reply and why, and then actually carry out the pending work.)"
        % question
    )

    def _deliver(ok, result, options=None):
        agent_tools.notify_ide_chat(
            result if ok else "\u26a0 %s" % result, options if ok else None)

    _ide_chat_ask(synthetic, _deliver, is_auto_continue=True)


def _ide_chat_retry_after_connectivity(original_text):
    """Fires when _ide_chat_connectivity_retry detects the internet is
    back after a request in the IDE's embedded chat panel failed with
    CONNECTIVITY_ERROR_TAG (see _ide_chat_ask's on_fail below). Simply
    re-runs the exact original request -- it never actually went through
    the first time, so this is a real retry, not a continuation -- and
    delivers the eventual result via agent_tools.notify_ide_chat, same
    as _ide_chat_auto_continue above, since nobody is sitting on an
    on_done callback waiting for it any more (the original caller's
    on_done already fired once, with the failure).
    """
    def _deliver(ok, result, options=None):
        agent_tools.notify_ide_chat(
            result if ok else "\u26a0 %s" % result, options if ok else None)

    _ide_chat_ask(original_text, _deliver, is_auto_continue=True)


# One shared tracker for the IDE's embedded chat panel -- see the
# _PendingDecisionTracker/_extract_await_decision block near
# _on_qt_main_thread above for the full story. The circle's own
# voice/typed chat gets its own separate instance per CircleOverlay (see
# CircleOverlay.__init__'s self._decision_tracker) so a pause on one
# surface never auto-resolves just because the other sees activity.
_ide_chat_decision_tracker = _PendingDecisionTracker(_ide_chat_auto_continue)

# Same one-per-surface reasoning, for the "lost internet mid-task, retry
# once it's back" behavior (see _ConnectivityRetryTracker above). The
# circle's own voice/typed chat gets its own separate instance too (see
# CircleOverlay.__init__'s self._connectivity_retry).
_ide_chat_connectivity_retry = _ConnectivityRetryTracker(
    _ide_chat_retry_after_connectivity)


_pending_label_workers = set()  # keeps each _ide_speak_label() SpeechWorker
                               # alive until it finishes, same reason as
                               # _pending_chat_workers above.


def _ide_speak_label(text):
    """Registered with agent_tools.set_speak_label_handler() in main()
    below. Speaks `text` aloud through Friday's own configured voice --
    called directly, in-process, from the Tk side of this shared main
    thread, by ide.py's minimized-panel "pill" (see MinimizedPill) when
    it's hovered, to announce which panel it represents (e.g. "IDE").

    Deliberately silent (not an error, just a no-op) if speech is off,
    if there's no circle at all (e.g. ide.py running standalone), or if
    Friday is already mid-conversation (not idle) -- this is a minor
    cosmetic cue and must never interrupt, queue behind, or compete with
    a real voice/typed exchange already in progress. Also silently
    ignores a new request while a previous label announcement is still
    playing, rather than piling them up.
    """
    if not (ENABLE_SPEECH and text and text.strip()):
        return
    ov = _circle_overlay
    if ov is None or ov._state != STATE_IDLE:
        return
    if _pending_label_workers:
        return  # already announcing a label -- don't stack another on top

    worker = SpeechWorker(text, parent=None)
    _pending_label_workers.add(worker)

    def _cleanup():
        _pending_label_workers.discard(worker)
        worker.deleteLater()

    worker.finished.connect(_cleanup)
    worker.start()


def _announce_panel_event(text):
    """Best-effort: hands `text` to the circle's own proactive
    panel-status announcement queue (see CircleOverlay.announce_panel_event)
    if a circle is actually on screen right now. No-ops otherwise (e.g.
    a standalone `python ide.py` run with no Friday circle at all).
    Always call this via _on_qt_main_thread(...) from a non-Qt thread --
    announce_panel_event can start a QTimer.
    """
    ov = _circle_overlay
    if ov is not None:
        ov.announce_panel_event(text)


class CircleOverlay(QWidget):
    def __init__(self):
        super().__init__()
        global _circle_overlay
        _circle_overlay = self  # lets _ide_chat_ask() reach the one live
        # circle instance without a constructor-injected reference —
        # there's only ever one of these per process.

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.resize(WINDOW_SIZE, WINDOW_SIZE)

        self._scale = 1.0
        self._hover = False
        self._state = STATE_IDLE
        self._drag_offset = None
        self._press_global_pos = None
        self._dragged = False
        self._worker = None
        self._speech_worker = None
        # True whenever the most recent reply (from either the circle's own
        # voice/typed flow, or a chat message relayed in from the IDE's
        # right-side panel) ended in an error, so STATE_RESPONDING can be
        # painted red instead of green -- and so _push_ide_status() can
        # tell the IDE which color its own border glow should be.
        self._last_was_error = False

        self._anim = QPropertyAnimation(self, b"scale")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutBack)

        self._pulse_phase = 0.0
        self._listen_elapsed_ms = 0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)
        self._anim_timer.timeout.connect(self._tick_animation)

        # Safety-net: guarantees we move on from Responding even if speech
        # fails/hangs/is disabled (normally _on_speech_finished beats it).
        self._transition_timer = QTimer(self)
        self._transition_timer.setSingleShot(True)
        self._transition_timer.timeout.connect(self._finish_responding)

        # While the typed text box is open, closes it back to idle if the
        # user doesn't type anything for a few seconds. Restarted on every
        # keystroke, and every time the text box is (re-)opened.
        self._inactivity_timer = QTimer(self)
        self._inactivity_timer.setSingleShot(True)
        self._inactivity_timer.timeout.connect(self._on_listen_inactivity)

        self.input_popup = InputPopup()
        self.input_popup.submitted.connect(self._on_query_submitted)
        self.input_popup.cancelled.connect(lambda: self._enter_state(STATE_IDLE))
        self.input_popup.edit.textChanged.connect(self._on_listen_activity)

        # -- voice input: wake word + speech-to-text --------------------
        self._voice_worker = None
        self._voice_worker_ok = False   # True once the mic has been confirmed usable
        self._capturing_voice_command = False  # True only during the post-ack listen window
        self._voice_ack_worker = None

        # -- voice cross-check confirmation (see _needs_confirmation) ----
        # Long or action-sounding spoken requests get summarized back for
        # a quick yes/no before Friday actually acts on them, to catch
        # speech-to-text mistakes before they become the wrong file edit
        # or command. _awaiting_confirmation is True only during the
        # follow-up listen window right after Friday asks "...is that right?";
        # _pending_confirmation_text holds the original (verbatim, not
        # summarized) request that runs for real once confirmed.
        self._awaiting_confirmation = False
        self._pending_confirmation_text = None
        # 2-minute unanswered-pause autonomy rule -- see the
        # _PendingDecisionTracker/_extract_await_decision block above.
        self._decision_tracker = _PendingDecisionTracker(
            self._auto_continue_pending_decision)
        # "Lost internet mid-task, retry once it's back" -- see
        # _ConnectivityRetryTracker above. Independent of the IDE chat
        # panel's own instance (_ide_chat_connectivity_retry) -- each
        # conversation surface tracks its own stalled request.
        self._connectivity_retry = _ConnectivityRetryTracker(
            self._retry_after_connectivity)
        # Queued proactive notifications about some OTHER minimized
        # panel's status changing (paused for a decision / done / hit an
        # error) -- see announce_panel_event/_flush_panel_announcements.
        self._pending_panel_announcements = []
        self._confirm_worker = None

        self._command_timeout_timer = QTimer(self)
        self._command_timeout_timer.setSingleShot(True)
        self._command_timeout_timer.timeout.connect(self._on_command_capture_timeout)

        if ENABLE_VOICE_MODE:
            self._voice_worker = VoiceListenWorker(self)
            self._voice_worker.heard.connect(self._on_voice_heard)
            self._voice_worker.mic_unavailable.connect(self._on_mic_unavailable)
            self._voice_worker.start()
            self._voice_worker_ok = True
            self._voice_worker.resume()  # app starts idle == background wake-word listening
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._shutdown_voice_worker)

        self._position_top_right()
        self.setMouseTracking(True)

    def _shutdown_voice_worker(self):
        # Stops the background mic thread cleanly on quit instead of
        # letting Qt tear it down mid-listen.
        if self._voice_worker is not None:
            self._voice_worker.stop()
            self._voice_worker.resume()  # in case it was paused, so the loop can see _stop_requested
            self._voice_worker.wait(2000)

    # -- positioning -------------------------------------------------
    def _position_top_right(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.width() - MARGIN_RIGHT
        y = screen.top() + MARGIN_TOP
        self.move(x, y)

    def _physical_pixel_ratio(self):
        """Best-effort devicePixelRatio for whichever screen this circle
        is currently on — used by get_circle_rect() below to convert its
        own logical-pixel geometry into the physical-pixel space ide.py's
        Tk window geometry calls use (see _declare_dpi_awareness).
        Returns 1.0 (a no-op) on anything that fails, which is also
        simply the correct value on Linux/macOS."""
        try:
            screen = self.screen() if hasattr(self, "screen") else None
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is not None:
                dpr = screen.devicePixelRatio()
                if dpr and dpr > 0:
                    return dpr
        except Exception:  # noqa: BLE001
            pass
        return 1.0

    def get_circle_rect(self):
        """(center_x, center_y, diameter) of this circle on screen right
        now, in *physical* screen pixels — the space ide.py's own Tk
        window geometry calls use, not Qt's own logical pixels (see
        _physical_pixel_ratio). Used purely cosmetically by
        agent_tools._AgentHost.get_circle_rect() to give the IDE's
        open/close "pop" animation (ide.py's _play_open_animation/
        _play_close_animation) a point to grow out of / shrink back
        into. None if, for any reason, a sane rect can't be worked out —
        the animation just plays as a plain fade instead, Agent Mode
        itself is entirely unaffected either way."""
        try:
            dpr = self._physical_pixel_ratio()
            g = self.geometry()
            cx = (g.x() + g.width() / 2.0) * dpr
            cy = (g.y() + g.height() / 2.0) * dpr
            diameter = max(g.width(), g.height()) * dpr
            return (cx, cy, diameter)
        except Exception:  # noqa: BLE001
            return None

    # -- animated "scale" property ------------------------------------
    def getScale(self):
        return self._scale

    def setScale(self, value):
        self._scale = value
        self.update()

    scale = Property(float, getScale, setScale)

    # -- animation tick (waveform / spinner / equalizer) -----------------
    def _tick_animation(self):
        self._pulse_phase += 0.18
        if self._pulse_phase > 2 * math.pi:
            self._pulse_phase -= 2 * math.pi
        if self._state == STATE_LISTENING:
            self._listen_elapsed_ms = min(
                self._listen_elapsed_ms + self._anim_timer.interval(), LISTEN_RAMP_MS
            )
        self.update()

    # -- state machine -----------------------------------------------------
    def _enter_state(self, state, show_input=True):
        self._state = state
        self._transition_timer.stop()
        self._inactivity_timer.stop()
        self._command_timeout_timer.stop()

        if state == STATE_IDLE:
            target_scale = 1.0
            self._anim_timer.stop()
            self.input_popup.hide()
            self._capturing_voice_command = False
            if self._voice_worker is not None:
                self._voice_worker.set_command_capture(False)
            # Any pending cross-check confirmation is abandoned the moment
            # we land back in Idle for any reason (cancel click, timeout,
            # inactivity) — never let a stale "yes/no" expectation survive
            # into an unrelated future interaction.
            self._awaiting_confirmation = False
            self._pending_confirmation_text = None
            # Idle is the default "ready" state now — the mic is quietly
            # listening in the background for the wake word the whole time.
            if self._voice_worker is not None and self._voice_worker_ok:
                self._voice_worker.resume()
            # Flush any proactive panel-status announcement that was
            # queued while Friday was busy (see announce_panel_event) --
            # deferred to right after this method returns (QTimer(0))
            # rather than called straight from inside _enter_state
            # itself, since _flush_panel_announcements ultimately calls
            # _show_response, which calls _enter_state again -- calling
            # back into this same method while it's still running would
            # re-enter it instead of starting a clean new call.
            if self._pending_panel_announcements:
                QTimer.singleShot(0, self._flush_panel_announcements)

        elif state == STATE_LISTENING:
            target_scale = ACTIVE_SCALE
            self._pulse_phase = 0.0
            self._listen_elapsed_ms = 0
            self._anim_timer.start()
            if show_input:
                # Typed text box (manual click, or the "bring up text chat"
                # voice command) — mic stays paused while you type.
                self.input_popup.show_near(self.geometry())
                self._inactivity_timer.start(LISTEN_INACTIVITY_MS)
                if self._voice_worker is not None:
                    self._voice_worker.pause()
            else:
                # Waiting for a spoken command right after the wake-word
                # acknowledgment — same waveform visual, no text box.
                self.input_popup.hide()

        elif state == STATE_LOADING:
            target_scale = 1.0
            self._anim_timer.start()
            self.input_popup.hide()
            if self._voice_worker is not None:
                self._voice_worker.pause()

        elif state == STATE_RESPONDING:
            target_scale = ACTIVE_SCALE
            self._anim_timer.start()
            # Mic stays paused through the whole reply so it never hears
            # (and reacts to) Friday's own voice coming out of the speakers.
            if self._voice_worker is not None:
                self._voice_worker.pause()

        self._anim.stop()
        self._anim.setStartValue(self._scale)
        self._anim.setEndValue(target_scale)
        self._anim.start()
        self.update()
        self._push_ide_status()

    def _push_ide_status(self):
        """Push this state into the IDE and active app-panel borders.
        self._state/_last_was_error are already current by the time
        _enter_state calls this.

        App-panel updates are posted to their Tk host without waiting;
        the IDE update is separately marshaled to its Tk thread. This
        method can run on Qt's main thread or another thread, so neither
        path touches a Tk widget directly."""
        state, is_error = self._state, bool(self._last_was_error)
        agent_tools.report_friday_status(state, is_error)
        app = agent_tools._ide_app
        if app is None:
            return

        def _push():
            try:
                app.set_friday_status(state, is_error)
            except Exception:  # noqa: BLE001
                pass

        try:
            agent_tools._post_on_main(_push)
        except Exception:  # noqa: BLE001
            pass

    def toggle(self):
        if self._state == STATE_IDLE:
            self._enter_state(STATE_LISTENING)  # manual click always opens the typed box
        elif self._state == STATE_RESPONDING:
            # Interrupt whatever Friday is saying right now and drop
            # straight into actively listening for the next request --
            # no need to repeat the wake word right after cutting it off.
            self._stop_speaking()
            self._enter_state(STATE_LISTENING, show_input=False)
            self._begin_command_capture()
        else:
            # Clicking again at any point cancels back to idle -- this
            # also covers the brief Loading window where a reply has
            # arrived and speech is already being synthesized/started but
            # hasn't audibly begun yet (see _show_response), so it can't
            # keep talking a moment later after being "cancelled".
            if self._worker is not None:
                self._worker = None  # let any in-flight call finish silently
            self._stop_speaking()
            self._enter_state(STATE_IDLE)

    def _stop_speaking(self):
        """Immediately cuts off whatever Friday is currently saying (or about
        to say). Best-effort: whichever TTS backend is actually active
        gets asked to stop right away -- see SpeechWorker.request_stop().
        Never blocks: the state machine moves on the instant this
        returns, regardless of whether the underlying audio actually
        managed to stop immediately. Safe to call even when nothing is
        speaking (e.g. plain cancel-to-idle clicks) -- it's just a no-op
        then."""
        worker = self._speech_worker
        self._speech_worker = None
        if worker is not None:
            try:
                worker.request_stop()
            except Exception:  # noqa: BLE001
                pass

    def _on_listen_activity(self, _text=None):
        # Any keystroke in the text box resets the inactivity countdown.
        if self._state == STATE_LISTENING:
            self._inactivity_timer.start(LISTEN_INACTIVITY_MS)

    def _on_listen_inactivity(self):
        if self._state == STATE_LISTENING:
            self._enter_state(STATE_IDLE)

    # -- voice input: wake word + speech-to-text ---------------------------
    def _on_voice_heard(self, text):
        """Fires for every phrase VoiceListenWorker understands, any time
        it isn't paused. Only acts on it if we're idle/background-listening
        (the wake word) or specifically waiting for the command right after
        a wake-word acknowledgment — otherwise (mid-reply, typing, etc.) it
        shouldn't be possible to get here since the mic is paused, but the
        state check is kept as a defensive no-op just in case."""
        if self._capturing_voice_command:
            self._capturing_voice_command = False
            self._command_timeout_timer.stop()
            if self._voice_worker is not None:
                self._voice_worker.set_command_capture(False)
            if self._awaiting_confirmation:
                self._on_confirmation_reply(text)
            else:
                self._handle_voice_command(text)
            return

        if self._state != STATE_IDLE:
            return  # busy with something else — ignore stray mic input

        hit, trailing = _extract_wake_command(text)
        if not hit:
            return  # not the wake word — keep quietly listening in the background

        if self._voice_worker is not None:
            self._voice_worker.pause()

        if trailing:
            # Said the whole request in one breath, e.g. "Friday, what's the
            # weather?" — skip the acknowledgment and act immediately.
            self._handle_voice_command(trailing)
        else:
            self._speak_wake_ack_then_capture()

    def _speak_wake_ack_then_capture(self):
        self._enter_state(STATE_LISTENING, show_input=False)
        ack = random.choice(WAKE_ACK_PHRASES)
        self._voice_ack_worker = SpeechWorker(ack, parent=self)
        self._voice_ack_worker.finished_speaking.connect(self._begin_command_capture)
        self._voice_ack_worker.finished.connect(self._voice_ack_worker.deleteLater)
        self._voice_ack_worker.start()

    def _begin_command_capture(self):
        if self._state != STATE_LISTENING:
            return  # cancelled (e.g. clicked away) while the ack was playing
        self._capturing_voice_command = True
        self._command_timeout_timer.start(COMMAND_CAPTURE_TIMEOUT_MS)
        if self._voice_worker is not None:
            self._voice_worker.set_command_capture(True)
            self._voice_worker.resume()

    def _on_command_capture_timeout(self):
        # Waited long enough after the acknowledgment and heard nothing
        # usable — quietly go back to background wake-word listening rather
        # than leaving the waveform up indefinitely.
        if self._capturing_voice_command:
            self._capturing_voice_command = False
            if self._voice_worker is not None:
                self._voice_worker.set_command_capture(False)
            self._enter_state(STATE_IDLE)

    def _handle_voice_command(self, text):
        normalized = _normalize_for_wake_check(text)
        if any(phrase in normalized for phrase in TEXT_CHAT_TRIGGER_PHRASES):
            self._enter_state(STATE_LISTENING)  # typed box (show_input defaults True)
            return
        if not text.strip():
            self._enter_state(STATE_IDLE)
            return
        if _needs_confirmation(text):
            self._start_confirmation(text)
            return
        self._on_query_submitted(text)

    # -- voice cross-check confirmation -------------------------------------
    def _start_confirmation(self, text):
        """Kicks off the summary call for a long/action-sounding spoken
        request (see _needs_confirmation) instead of acting on it right
        away. `text` is kept verbatim in _pending_confirmation_text and is
        what actually runs, unmodified, once the user confirms -- the
        summary is only ever used for the spoken question back to them."""
        self._pending_confirmation_text = text
        self._enter_state(STATE_LOADING)
        self._confirm_worker = AIWorker(text, parent=self, summarize_only=True)
        self._confirm_worker.succeeded.connect(self._on_confirmation_summary_ok)
        self._confirm_worker.failed.connect(self._on_confirmation_summary_err)
        self._confirm_worker.finished.connect(self._confirm_worker.deleteLater)
        self._confirm_worker.start()

    def _on_confirmation_summary_ok(self, summary_text):
        if self._state != STATE_LOADING:
            return  # cancelled while the summary call was in flight
        if not summary_text or not summary_text.strip():
            # Nothing usable came back for the question itself -- don't
            # leave the user waiting on a confirmation that was never
            # actually asked; just run the request for real instead.
            pending = self._pending_confirmation_text
            self._pending_confirmation_text = None
            if pending:
                self._on_query_submitted(pending)
            else:
                self._enter_state(STATE_IDLE)
            return
        self._awaiting_confirmation = True
        self._last_was_error = False
        # Logged as its own real exchange -- a genuine question Friday
        # asked out loud -- even though the pending action itself (the
        # original verbatim request) gets logged separately, as its own
        # normal turn, once it actually runs for real (see
        # _on_confirmation_reply below / _on_reply_ok above). Without
        # this, the cross-check question-and-answer dance would be a
        # silent gap in "every conversation."
        memory.remember_recent_turn("friday", summary_text)
        memory.log_turn_async("friday", summary_text)
        # Reuses the normal speak-then-listen-for-a-follow-up machinery
        # (_show_response -> ... -> _finish_responding -> LISTENING +
        # _begin_command_capture) unchanged -- the only difference is what
        # happens to whatever gets captured next, handled by the
        # _awaiting_confirmation check in _on_voice_heard above.
        self._show_response(summary_text, speak=True)

    def _on_confirmation_summary_err(self, _message):
        # The summary call itself failed for a technical reason (provider
        # hiccup, no key, etc.) -- rather than making the user repeat their
        # whole request, just run it for real without the cross-check this
        # one time, same graceful-degradation spirit as every other
        # fallback in this file.
        if self._state != STATE_LOADING:
            return
        pending = self._pending_confirmation_text
        self._pending_confirmation_text = None
        if pending:
            self._on_query_submitted(pending)
        else:
            self._enter_state(STATE_IDLE)

    def _on_confirmation_reply(self, text):
        """Fires once for whatever's captured right after Friday asks its
        cross-check question. Confirmed -> the original verbatim request
        runs for real (full tool access, same as any other command);
        anything else (plain "no", a correction, an unrelated reply) ->
        asked to just restate it fresh, no need to repeat the wake word."""
        self._awaiting_confirmation = False
        original = self._pending_confirmation_text
        self._pending_confirmation_text = None
        # The user's actual spoken reply to the cross-check question --
        # logged here regardless of which branch runs next, same
        # "complete the dialogue" reasoning as the question itself above.
        if text:
            memory.remember_recent_turn("user", text)
            memory.log_turn_async("user", text)
        if original and _is_affirmative(text):
            self._on_query_submitted(original)
        else:
            self._last_was_error = False
            reply = "My mistake — go ahead and say that again."
            memory.remember_recent_turn("friday", reply)
            memory.log_turn_async("friday", reply)
            self._show_response(reply, speak=True)

    def _on_mic_unavailable(self, reason):
        # `reason` is already a complete, friendly sentence from
        # VoiceListenWorker (e.g. "...voice mode is disabled; click the
        # circle to type instead."), so it's shown/spoken as-is.
        self._voice_worker_ok = False
        self._show_response(reason, speak=True)

    def _auto_continue_pending_decision(self, question):
        """Fires when self._decision_tracker's 2-minute no-reply timeout
        elapses (see the _PendingDecisionTracker block near
        _on_qt_main_thread) -- nobody answered Friday's last
        pause-for-a-major-decision question. Per personality.md's Agent
        Mode section, re-enters the normal query pipeline with a
        synthetic system-level nudge standing in for the user's own next
        message, so the usual AIWorker -> _show_response -> memory flow
        handles the follow-through -- spoken aloud exactly like any
        other reply.
        """
        if self._state != STATE_IDLE:
            # Something else is already happening on this surface (a new
            # real command, mid-reply, etc.) -- don't barge in; whatever
            # that is already superseded the stale pause.
            return
        synthetic = (
            "(System note, not from the user: about two minutes have "
            "passed with no reply to your last question — \"%s\". No one "
            "is coming back to answer it right now. Per the 2-minute "
            "unanswered-pause rule, decide the most professional, "
            "reasonable option yourself, say plainly that you're "
            "proceeding without a reply and why, and then actually carry "
            "out the pending work.)" % question
        )
        self._on_query_submitted(synthetic, is_auto_continue=True)

    def _retry_after_connectivity(self, original_text):
        """Fires when self._connectivity_retry detects the internet is
        back after the circle's own query failed with
        CONNECTIVITY_ERROR_TAG (see _on_reply_err below). Re-submits the
        exact original query -- it never actually ran the first time, so
        this is a genuine retry, not a continuation -- through the
        normal pipeline, so it ends up spoken/remembered exactly like
        any other reply once it succeeds.
        """
        if self._state != STATE_IDLE:
            return  # something else already superseded the stalled request
        self._on_query_submitted(original_text, is_auto_continue=True)

    def announce_panel_event(self, text):
        """Best-effort proactive notification that some OTHER minimized
        panel's status just changed -- e.g. "Sir, the IDE needs your
        permission before proceeding." or "The IDE is done with its
        task, sir." Only ever worth calling for a panel that's actually
        minimized right now (see agent_tools.is_panel_minimized): the
        whole premise is that its real window isn't on screen, so there
        is nothing else to cue the user that something happened.

        Unlike _ide_speak_label's purely cosmetic hover announcement
        (silently dropped whenever Friday isn't idle, never queued),
        these are substantive enough to be worth not losing: queued in
        self._pending_panel_announcements and spoken either right away
        (if idle right now) or the next time _enter_state naturally
        lands back in Idle (see there), oldest first.
        """
        if not text:
            return
        if (self._pending_panel_announcements
                and self._pending_panel_announcements[-1] == text):
            return  # the exact same announcement is already queued
        self._pending_panel_announcements.append(text)
        if self._state == STATE_IDLE:
            self._flush_panel_announcements()

    def _flush_panel_announcements(self):
        """Speaks the oldest still-pending panel-status announcement, if
        Friday is actually idle right now (never interrupts a live
        voice/typed exchange or a reply already in flight) and there is
        one -- see announce_panel_event. More than one queued
        announcement drains naturally over time: _finish_responding's
        own path back through _enter_state(STATE_IDLE) calls this again
        once each one finishes.
        """
        if self._state != STATE_IDLE or not self._pending_panel_announcements:
            return
        text = self._pending_panel_announcements.pop(0)
        self._last_was_error = False
        self._show_response(text, speak=True)
        memory.remember_recent_turn("friday", text)
        memory.log_turn_async("friday", text)

    # -- talking to Gemini ---------------------------------------------------
    def _on_query_submitted(self, text, is_auto_continue=False):
        if not is_auto_continue:
            # A real message just arrived on this surface -- any
            # previously-armed 2-minute pause timer no longer needs to
            # fire; this message (whether or not it actually answers the
            # pending question) is handled the normal way below instead.
            self._decision_tracker.cancel()
            # Same for a stalled connectivity retry -- the user sending
            # a new request supersedes whatever previously failed.
            self._connectivity_retry.cancel()
        self.input_popup.hide()
        self._enter_state(STATE_LOADING)

        # Remembered so _on_reply_ok below can log *both* sides of this
        # exchange to the conversation log once the reply actually comes
        # back -- AIWorker's own succeeded signal only carries the reply
        # text, not the original query.
        self._last_query_text = text

        self._worker = AIWorker(text, parent=self)
        self._worker.succeeded.connect(self._on_reply_ok)
        self._worker.failed.connect(self._on_reply_err)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_reply_ok(self, text):
        if self._state != STATE_LOADING:
            return  # user cancelled while we were waiting
        self._last_was_error = False
        # 2-minute unanswered-pause autonomy rule: strip the control tag
        # before anything below ever speaks it, shows it, or feeds it
        # back into memory -- it's a pure signal, never literal content
        # (see _extract_await_decision's docstring) -- and remember
        # whether to arm this surface's own pause timer once the reply
        # has actually gone out.
        text, is_pending_decision = _extract_await_decision(text)
        # Defense-in-depth only -- the circle is voice/spoken, where
        # {{OPTIONS: ...}} (Task 65's IDE-chat-only Permission tag) has
        # no meaning; personality.md never tells the model to use it
        # here. Still run it and discard the parsed list so the raw tag
        # itself is stripped and never spoken aloud if a model ever
        # emits it on this surface anyway (see _extract_decision_options's
        # module comment).
        text, _unused_decision_options = _extract_decision_options(text)
        self._show_response(text, speak=True)
        # Memory logging below uses the cue-stripped text (speech_delivery.md's
        # bracket "stage directions" like [pause]/[sighs] removed), not the
        # raw reply handed to _show_response/SpeechWorker above -- those cues
        # only mean something as timing/volume instructions for speech, and
        # would otherwise sit as literal bracket noise in conversation
        # history that gets fed back to the model as future context.
        clean_text = _strip_cues_for_display(text) if text else text
        # Automatic half of memory (see memory.py's module docstring):
        # every successful exchange is logged + embedded in the
        # background, with no tool call needed, so Friday can recall it
        # later even if nothing in it was ever explicitly "remembered".
        # Fire-and-forget and started only *after* _show_response above
        # -- logging must never add latency to a reply the user is
        # already waiting on. Error replies are deliberately not logged
        # here (see _on_reply_err) -- nothing about a quota/auth error
        # message is worth recalling later.
        #
        # remember_recent_turn() runs first and synchronously (no
        # embedding, no disk I/O) -- it's what makes the *very next*
        # message, even one typed a second later, already able to see
        # this exchange, without waiting on log_turn_async()'s slower
        # background embedding call to actually land. See memory.py's
        # "Recent-turns buffer" section for the full story -- this is
        # what closes the "I just told you X and you forgot" gap.
        query = getattr(self, "_last_query_text", "")
        if query:
            memory.remember_recent_turn("user", query)
            memory.log_turn_async("user", query)
        if clean_text:
            memory.remember_recent_turn("friday", clean_text)
            memory.log_turn_async("friday", clean_text)
        if is_pending_decision:
            # Already on the Qt main thread here (see _on_reply_ok's own
            # callers -- AIWorker.succeeded is connected to this bound
            # method, which Qt auto-delivers via a queued connection
            # onto CircleOverlay's own thread), so arm() -- which starts
            # a real QTimer -- can be called directly, no
            # _on_qt_main_thread marshaling needed (unlike the IDE
            # chat's own on_ok, which runs on a plain background thread).
            self._decision_tracker.arm(clean_text or text)

    def _on_reply_err(self, message):
        if self._state != STATE_LOADING:
            return
        # `message` already comes with a friendly emoji/context prefix
        # from AIWorker (e.g. quota/auth/model errors from either provider).
        self._last_was_error = True
        self._show_response(message, speak=False)
        # "Lost internet mid-task, retry once it's back" -- only for a
        # genuine connectivity failure (see CONNECTIVITY_ERROR_TAG); a
        # bad API key or quota limit would just fail the same way again,
        # so those are left for the user to actually address instead of
        # being silently retried forever.
        if message and CONNECTIVITY_ERROR_TAG in message:
            query = getattr(self, "_last_query_text", "")
            if query:
                # Already on the Qt main thread here (see _on_reply_ok's
                # own comment just above for why) -- arm() can be called
                # directly, no _on_qt_main_thread marshaling needed.
                self._connectivity_retry.arm(query)

    def _show_response(self, text, speak):
        """Deliberately never displays `text` anywhere on screen: the
        reply is audible only (via the TTS call below), never shown as
        a readable bubble, by design -- nothing in this method renders
        `text` itself, it's only used to size the speech-safety timer
        below.

        When speech is going to play, this stays in Loading (the
        spinner) rather than jumping straight to Responding: Piper's
        one-time voice-model warm-up and its actual synthesis both take
        a visible beat, and switching to the "talking" animation before
        there's any sound to go with it looks like it's lying. Instead,
        _on_speech_started -- fired the instant the speech worker is
        actually about to produce audio -- is what flips it to
        Responding, keeping the animation in sync with the sound.
        """
        will_speak = speak and ENABLE_SPEECH and bool(text.strip())

        if not will_speak:
            # Nothing will be spoken (TTS off/unavailable/empty reply) —
            # no speech signals are coming, so just show Responding right
            # away, timed as a rough "reading time" instead.
            self._enter_state(STATE_RESPONDING)
            duration = max(MIN_RESPONSE_MS, min(
                MAX_RESPONSE_MS,
                len(_strip_cues_for_display(text)) * MS_PER_CHAR))
            self._transition_timer.start(duration)
            return

        # Speech is coming -- stay in Loading until it actually starts.
        # This timer is a generous fallback covering both "waiting for
        # speech to start" and (once it has) "waiting for it to finish",
        # in case TTS hangs or crashes without ever emitting its signals.
        self._enter_state(STATE_LOADING)
        self._transition_timer.start(MAX_SPEECH_SAFETY_MS)

        self._speech_worker = SpeechWorker(text, parent=self)
        self._speech_worker.started_speaking.connect(self._on_speech_started)
        self._speech_worker.finished_speaking.connect(self._on_speech_finished)
        self._speech_worker.finished.connect(self._speech_worker.deleteLater)
        self._speech_worker.start()

    def _on_speech_started(self):
        # The active speech worker is actually about to produce audio --
        # this is what flips the circle into its "talking" animation, in
        # sync with the sound instead of ahead of it.
        if self._state == STATE_LOADING and self._speech_worker is not None:
            self._enter_state(STATE_RESPONDING)
            # Restart the safety net now that real speaking has begun, in
            # case finished_speaking never arrives for some reason.
            self._transition_timer.start(MAX_SPEECH_SAFETY_MS)

    def _on_speech_finished(self):
        # As soon as speaking wraps up, move on right away instead of
        # waiting out the full safety-net timer.
        self._finish_responding()

    def _finish_responding(self):
        # The response bubble/equalizer stays up for as long as it's
        # speaking (or, before that, the spinner stays up while speech is
        # still starting -- see _show_response/_on_speech_started). Once
        # done (or the safety-net timer fires either way), move into a
        # brief actively-listening window instead of dropping straight
        # back to idle — same place clicking mid-response jumps to, and
        # the same mechanism the wake-word ack uses: no need to repeat the
        # wake word for a quick follow-up. If nothing comes in within
        # COMMAND_CAPTURE_TIMEOUT_MS, _on_command_capture_timeout() falls
        # back to Idle (background wake-word listening) on its own.
        if self._state in (STATE_RESPONDING, STATE_LOADING):
            self._enter_state(STATE_LISTENING, show_input=False)
            self._begin_command_capture()

    # -- painting ------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        diameter = BASE_DIAMETER * self._scale
        rect = QRectF(0, 0, diameter, diameter)
        rect.moveCenter(QRectF(0, 0, self.width(), self.height()).center())

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(FILL_COLOR))
        painter.drawEllipse(rect)

        if self._state == STATE_LOADING:
            self._draw_loading_ring(painter, rect)
        else:
            if self._state == STATE_RESPONDING:
                border = BORDER_COLOR_ERROR if self._last_was_error \
                    else BORDER_COLOR_RESPONDING
            elif self._state == STATE_LISTENING:
                border = BORDER_COLOR_LISTENING
            elif self._hover:
                border = BORDER_COLOR_HOVER
            else:
                border = BORDER_COLOR
            painter.setPen(QPen(border, BORDER_WIDTH))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect)

        if self._state == STATE_LISTENING:
            self._draw_listening_wave(painter, rect)
        elif self._state == STATE_RESPONDING:
            self._draw_equalizer(painter, rect)

    def _draw_listening_wave(self, painter, circle_rect):
        diameter = circle_rect.width()
        cx = circle_rect.center().x()
        cy = circle_rect.center().y()

        amplitude_ratio = self._listen_elapsed_ms / LISTEN_RAMP_MS
        line_width = diameter * 0.62
        max_amp = diameter * 0.17 * amplitude_ratio
        stroke_width = max(1.6, diameter * 0.045)

        num_points = 28
        path = QPainterPath()
        for i in range(num_points + 1):
            t = i / num_points
            x = cx - line_width / 2 + t * line_width
            envelope = math.sin(math.pi * t)
            y = cy + max_amp * envelope * math.sin(6.0 * t + self._pulse_phase * 2.2)
            point = QPointF(x, y)
            if i == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)

        pen = QPen(ICON_COLOR, stroke_width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def _draw_loading_ring(self, painter, circle_rect):
        pen = QPen(BORDER_COLOR_LOADING, BORDER_WIDTH)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        rotation_deg = (self._pulse_phase * (180.0 / math.pi) * 3.0) % 360.0
        start_angle = int(-rotation_deg * 16)
        span_angle = 270 * 16
        painter.drawArc(circle_rect, start_angle, span_angle)

    def _draw_equalizer(self, painter, circle_rect):
        diameter = circle_rect.width()
        cx = circle_rect.center().x()
        cy = circle_rect.center().y()

        bar_width = diameter * 0.09
        gap = diameter * 0.035
        max_height = diameter * 0.60

        total_width = WAVE_BAR_COUNT * bar_width + (WAVE_BAR_COUNT - 1) * gap
        start_x = cx - total_width / 2

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(ICON_COLOR))

        for i, env in enumerate(WAVE_ENVELOPE):
            wobble = (abs(math.sin(self._pulse_phase * 1.6 + i * 0.9)) * 0.5) + 0.5
            bar_h = max(bar_width, env * max_height * wobble)

            bar_rect = QRectF(
                start_x + i * (bar_width + gap),
                cy - bar_h / 2,
                bar_width,
                bar_h,
            )
            painter.drawRoundedRect(bar_rect, bar_width / 2, bar_width / 2)

    # -- hover state -----------------------------------------------------
    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    # -- click to toggle state / drag to move -----------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_global_pos = event.globalPosition().toPoint()
            self._dragged = False

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            current = event.globalPosition().toPoint()
            if (current - self._press_global_pos).manhattanLength() > 4:
                self._dragged = True
            self.move(current - self._drag_offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not self._dragged:
                self.toggle()
            self._drag_offset = None

    # -- right-click quit menu --------------------------------------------
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)
        menu.exec(event.globalPos())


def _declare_dpi_awareness():
    """Windows only: explicitly request Per-Monitor-V2 DPI awareness for
    this process, the same way ide/ide.py does, and for the same reason —
    Win32 APIs return coordinates *virtualized* (i.e. silently rescaled)
    to whatever DPI the *calling* process claims to be aware of, not the
    real physical pixels, unless the caller has actually opted in.
    Without this, on any display with Windows scaling other than 100%
    CircleOverlay.get_circle_rect() (which converts its own logical
    on-screen position into the physical-pixel space ide.py's Tk window
    geometry calls use, for the open/close pop animation's origin point)
    would drift or land in the wrong place entirely — this must run
    before QApplication() so Qt doesn't get to decide DPI awareness for
    us first."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        except (AttributeError, OSError):
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
            except (AttributeError, OSError):
                ctypes.windll.user32.SetProcessDPIAware()  # Vista+ fallback
    except Exception:  # noqa: BLE001
        pass  # never let a platform quirk here block startup


def _force_close_ide():
    """Wired to QApplication.aboutToQuit: whatever is quitting Friday --
    the right-click Quit action, Ctrl+C, a hard process kill via the
    task manager, anything -- takes the IDE down with it too, since it's
    one of Friday's own windows now and not a separate process that could
    be left orphaned behind. No panel Friday ever creates should be able to
    outlive Friday itself.

    The IDE's Tk root now lives on its own dedicated thread (see
    agent_tools._TkThreadBridge) rather than sharing this one, so it
    can't be destroyed directly from here -- that has to be marshaled
    onto its own thread via Tk's thread-safe .after(0, ...) scheduling,
    same as every other cross-thread call into the IDE. Bounded wait so
    a wedged IDE thread can never hang Friday's own shutdown.
    """
    if agent_tools._ide_app is None:
        return
    try:
        # Deliberately fire-and-forget (agent_tools._post_on_main, not
        # a blocking wait on a local "app ="/done.wait() pair): holding
        # a reference to the IDEApp instance on *this* thread for
        # however long destroy() takes to run on the IDE's own Tk
        # thread reproduced a hard, unrecoverable Tcl-level process
        # abort in testing -- see agent_mode_off()'s matching comment
        # in agent_tools.py for the full explanation. Polling for the
        # IDE to actually be gone, same as agent_mode_off() does, gives
        # the bounded wait this still needs without ever holding that
        # reference here.
        agent_tools._post_on_main(
            lambda: agent_tools._ide_app.destroy()
            if agent_tools._ide_app is not None else None)
        deadline = time.time() + 2.0
        while time.time() < deadline and agent_tools._ide_app is not None:
            time.sleep(0.05)
    except Exception:  # noqa: BLE001
        pass


def main():
    _declare_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    # Built here, on the real Qt GUI thread, before anything else can
    # possibly need it -- see _on_qt_main_thread()'s docstring. Must be
    # constructed on this thread specifically (a QObject's thread
    # affinity is whichever thread creates it); it then lives for the
    # rest of the process.
    global _main_thread_invoker
    _main_thread_invoker = _MainThreadInvoker()

    overlay = CircleOverlay()

    # Lets the IDE's embedded "Friday AI Chat" panel (shown only while
    # agent-controlled) talk to the exact same AI brain this circle
    # uses. agent_tools' own IDE-lifecycle tools reach across onto
    # whichever thread the IDE's Tk mainloop is running on by
    # themselves now (see agent_mode_on()/_TkThreadBridge) -- nothing
    # to wire up here for that any more.
    agent_tools.set_chat_handler(_ide_chat_ask)

    # Lets the IDE's open/close "pop" animation (ide.py's
    # _play_open_animation/_play_close_animation) know where this circle
    # currently is on screen, so the window can visibly grow out of it /
    # shrink back into it -- purely cosmetic, see get_circle_rect()'s
    # docstring for the None-is-fine fallback.
    agent_tools.set_circle_rect_provider(overlay.get_circle_rect)

    # Lets the IDE's minimized-panel "pill" (shown near the circle while
    # the IDE is minimized) speak its own name aloud on hover, through
    # Friday's own voice -- purely cosmetic, see set_speak_label_handler's
    # docstring for the silent-no-op fallback.
    agent_tools.set_speak_label_handler(_ide_speak_label)

    app.aboutToQuit.connect(_force_close_ide)

    overlay.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
