"""Real connectivity checks for the Settings panel's green-check/red-x
status per model -- the user's own requirement for this feature was
explicit: "before it checks it make a silent call in its backend then
checks it if it connects", i.e. the green check must come from an actual
live backend call, never just "a key string is present".

Every function here takes whatever settings_store.py stored for one
model entry and returns `(ok: bool, detail: str)`. None of them ever
raise -- a missing SDK, a bad key, a timeout, or an unknown provider all
come back as a plain `(False, "<human-readable reason>")` instead of an
exception, so one bad entry can never crash the panel or block checking
everything else.

These are deliberately cheap, no-op-ish calls (list models, not a real
generation) wherever the provider's SDK offers one, specifically so that
clicking a per-model "check" button doesn't spend real API quota/cost
just to answer "is this key valid". The one unavoidable exception is
Tavily, which has no free ping endpoint -- see check_tavily's own
docstring.

All of these do real network I/O and so are meant to be called from a
background thread, never directly on the Tk main thread -- see
settings_panel.py's `_run_check` for the threading/callback wiring.
"""
import os


def check_gemini(entry):
    api_key = entry.get("api_key", "")
    if not api_key:
        return False, "No API key configured."
    try:
        from google import genai
    except Exception as exc:  # noqa: BLE001
        return False, f"google-genai isn't installed: {exc}"
    try:
        client = genai.Client(api_key=api_key)
        # Cheapest possible real call that still requires a genuinely
        # valid, authenticated key: listing models, not generating
        # anything.
        next(iter(client.models.list()), None)
        return True, "Connected."
    except Exception as exc:  # noqa: BLE001
        return False, _short(exc)


# Embeddings use the exact same client/key as chat Gemini -- see
# memory.py's _embed_via_gemini, which calls the same API with the same
# GEMINI_API_KEY, just a different model id downstream of this check.
check_gemini_embed = check_gemini


def check_groq(entry):
    api_key = entry.get("api_key", "")
    if not api_key:
        return False, "No API key configured."
    try:
        from groq import Groq
    except Exception as exc:  # noqa: BLE001
        return False, f"groq isn't installed: {exc}"
    try:
        client = Groq(api_key=api_key)
        client.models.list()
        return True, "Connected."
    except Exception as exc:  # noqa: BLE001
        return False, _short(exc)


def check_mistral(entry):
    api_key = entry.get("api_key", "")
    if not api_key:
        return False, "No API key configured."
    try:
        from mistralai import Mistral
    except Exception as exc:  # noqa: BLE001
        return False, f"mistralai isn't installed/importable: {exc}"
    try:
        client = Mistral(api_key=api_key)
        client.models.list()
        return True, "Connected."
    except Exception as exc:  # noqa: BLE001
        return False, _short(exc)


check_mistral_embed = check_mistral


def check_tavily(entry):
    """Tavily has no free "ping" endpoint, so confirming a key for real
    unavoidably means spending one real (tiny) search call against it --
    unlike the other checks here, this one is deliberately never run
    automatically; see settings_panel.py, where it's only triggered by
    an explicit user click (right after adding/editing the key, or a
    manual recheck), same as every other check, but worth calling out
    here since it's the one exception to the "check calls are free"
    design the other functions rely on."""
    api_key = entry.get("api_key", "")
    if not api_key:
        return False, "No API key configured."
    try:
        from tavily import TavilyClient
    except Exception as exc:  # noqa: BLE001
        return False, f"tavily-python isn't installed: {exc}"
    try:
        client = TavilyClient(api_key=api_key)
        client.search("connectivity check", max_results=1)
        return True, "Connected."
    except Exception as exc:  # noqa: BLE001
        return False, _short(exc)


def check_local_piper(entry):
    """Piper runs fully offline -- there's nothing remote to "connect"
    to, so this checks the one thing that can actually fail locally: the
    piper package being importable and the chosen voice model file
    actually being present on disk."""
    try:
        import piper  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"piper-tts isn't installed: {exc}"
    try:
        import overlay_speech
        model_path = getattr(overlay_speech, "PIPER_VOICE_MODEL", None)
        if model_path and not os.path.isfile(model_path):
            return False, (f"Voice model not found at {model_path} -- run "
                            "setup_piper_voice.py to download it.")
    except Exception:  # noqa: BLE001
        pass  # overlay_speech not importable here (e.g. in a test) -- not fatal
    return True, "Installed and ready (fully offline, no API key needed)."


def check_local_whisper(entry):
    """Same idea as check_local_piper: faster-whisper runs fully
    offline, so this just confirms the package itself is importable."""
    try:
        import faster_whisper  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"faster-whisper isn't installed: {exc}"
    return True, "Installed (model downloads on first use, fully offline after that)."


def check_generic_http(entry):
    """Best-effort reachability check for a custom/user-added provider
    Friday has no real call code for -- a positive result here honestly
    means "something answered at that URL", not "this exact model
    works", which is the most truthful claim possible without knowing
    that provider's actual API shape. Used for every entry added through
    the panel's "+ Add Model" button."""
    base_url = (entry.get("base_url") or "").strip()
    if not base_url:
        return False, "No API base URL configured to check."
    try:
        import requests
    except Exception as exc:  # noqa: BLE001
        return False, f"The 'requests' package isn't installed: {exc}"
    headers = {}
    api_key = entry.get("api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = requests.get(base_url, headers=headers, timeout=6)
        if resp.status_code < 500:
            return True, f"Server responded (HTTP {resp.status_code}) — reachable."
        return False, f"Server error (HTTP {resp.status_code})."
    except Exception as exc:  # noqa: BLE001
        return False, _short(exc)


def _short(exc):
    text = str(exc).strip() or exc.__class__.__name__
    return text if len(text) <= 220 else text[:217] + "..."


CHECKERS = {
    "gemini": check_gemini,
    "gemini_embed": check_gemini_embed,
    "groq": check_groq,
    "mistral": check_mistral,
    "mistral_embed": check_mistral_embed,
    "tavily": check_tavily,
    "local_piper": check_local_piper,
    "local_whisper": check_local_whisper,
    "generic_http": check_generic_http,
}


def run_check(entry):
    """Dispatches to the right checker for `entry` based on its
    check_kind, falling back to the generic HTTP reachability check for
    anything unrecognized. Never raises."""
    kind = entry.get("check_kind") or "generic_http"
    fn = CHECKERS.get(kind, check_generic_http)
    try:
        return fn(entry)
    except Exception as exc:  # noqa: BLE001
        return False, f"Check failed unexpectedly: {_short(exc)}"
