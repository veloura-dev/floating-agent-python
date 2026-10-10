"""Friday's AI model/API-key settings: one list of "model" entries per
"faculty" (Thinking, Research, Transcription, ...) -- what the new
Settings panel (settings_panel.py) reads and writes.

This is sensitive data (raw API keys), so it gets the exact same
treatment as the rest of Friday's local memory (see memory.py's own
module docstring): one small JSON blob, Fernet-encrypted at rest, in its
own folder under Friday's existing `~/.friday/` memory directory, locked
down with the same OS-level permission restrictions. Rather than
duplicating that machinery, this module just reuses memory.py's already-
built primitives (`_ensure_folder`/`_write_encrypted`/`_read_encrypted`/
`_lock_down`) directly -- this file only owns the *shape* of the data
(faculties, model entries, defaults), not how it's stored on disk.

Each faculty maps onto one real region of Friday's Brain (see
act_script.py's ROLE_FACULTY) -- Voice feeds the floating circle's own
lightweight single-call chat path (agent_overlay.AIWorker's normal,
non-ide_scoped chain), and Thinking/Planning/Review/Coding/Text
Generation each feed the matching region of Act Script's Sequential
Rotation/Fan-Out/Debate pipelines (the IDE's compulsory coding engine --
see agent_overlay.AIWorker.run()'s ide_scoped branch). A region whose own
faculty has nothing configured yet automatically falls back to whatever
Thinking has, so everything keeps working out of the box; the moment a
user adds one or more models under a *specific* faculty, that region
switches to using ONLY those -- real, dedicated capacity of its own
rather than a bigger shared list diluted with Thinking's own traffic,
which is real extra quota/rate-limit headroom exactly where they chose
to add it, not just bookkeeping.
Image Generation, Video Generation, and Embedding remain pure
scaffolding -- no real generation/embedding call wiring exists for a
user-added entry there yet (Embedding's own two pre-seeded entries are
still real; a custom addition there is reachability-checked only).
"""
import os
import uuid

import memory

# The twelve faculties the settings panel organizes models under, in the
# order they're shown. A "faculty" here is just a named bucket of model
# entries -- it doesn't imply Friday can actually act on every entry yet
# (see module docstring above).
FACULTIES = [
    "Voice",
    "Thinking",
    "Planning",
    "Review",
    "Coding",
    "Image Generation",
    "Audio Generation",
    "Video Generation",
    "Research",
    "Embedding",
    "Text Generation",
    "Transcription",
]

_SETTINGS_FILENAME = "ai_models.json.enc"


def _settings_path():
    folder = memory._ensure_folder("settings")
    return os.path.join(folder, _SETTINGS_FILENAME)


def _env(name):
    return os.environ.get(name, "") or ""


def _entry(id_, name, model, check_kind, api_key="", builtin=True, base_url=""):
    return {
        "id": id_,
        "name": name,
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "builtin": builtin,          # True = a capability Friday can genuinely call today
        "check_kind": check_kind,    # which settings_checks.py function verifies this one
        "status": "unknown",         # "unknown" | "connected" | "error"
        "detail": "",                # last check's human-readable result
        "last_checked": None,        # unix timestamp, or None if never checked
    }


def _default_data():
    """Friday's real, already-wired models/keys, seeded the very first
    time this is loaded -- mirrors the exact env-var-backed keys/models
    agent_overlay.py, memory.py, and agent_tools.py already use (see
    each one's own constants), so the panel's very first view already
    reflects whatever's actually configured instead of showing
    everything as empty/unset the first time it's opened.
    """
    return {
        # Voice is seeded with the exact same three builtin
        # providers/keys as Thinking below (same ids, so the dedup in
        # act_script.available_slots() never double-counts them) --
        # today the floating circle's plain chat chain and Act Script's
        # Thinking region really are the same three calls, so this
        # keeps that true out of the box. Add a model here specifically
        # (a second key, or a different provider entirely) to give just
        # the circle's own voice/typed chat extra fallback headroom
        # without touching the IDE/Act Script side at all.
        "Voice": [
            _entry("gemini", "Google Gemini", "gemini-3.8-flash",
                   "gemini", _env("GEMINI_API_KEY")),
            _entry("groq", "Groq", "llama-3.3-70b-versatile",
                   "groq", _env("GROQ_API_KEY")),
            _entry("mistral", "Mistral", "mistral-small-latest",
                   "mistral", _env("MISTRAL_API_KEY")),
        ],
        "Thinking": [
            _entry("gemini", "Google Gemini", "gemini-3.8-flash",
                   "gemini", _env("GEMINI_API_KEY")),
            _entry("groq", "Groq", "llama-3.3-70b-versatile",
                   "groq", _env("GROQ_API_KEY")),
            _entry("mistral", "Mistral", "mistral-small-latest",
                   "mistral", _env("MISTRAL_API_KEY")),
        ],
        "Planning": [],
        "Review": [],
        "Coding": [],
        "Image Generation": [],
        "Audio Generation": [
            _entry("piper", "Piper (local)",
                   "en_GB-northern_english_male-medium", "local_piper"),
        ],
        "Video Generation": [],
        "Research": [
            _entry("tavily", "Tavily", "search",
                   "tavily", _env("TAVILY_API_KEY")),
        ],
        "Embedding": [
            _entry("gemini_embed", "Google Gemini", "text-embedding-004",
                   "gemini_embed", _env("GEMINI_API_KEY")),
            _entry("mistral_embed", "Mistral", "mistral-embed",
                   "mistral_embed", _env("MISTRAL_API_KEY")),
        ],
        "Text Generation": [],
        "Transcription": [
            _entry("faster_whisper", "faster-whisper (local)", "small.en",
                   "local_whisper"),
        ],
    }


def load():
    """Returns the full {faculty: [entry, ...]} dict, creating (and
    saving) the default seed data on first-ever use. Also quietly backfills
    any faculty key missing from an older saved file (e.g. after an app
    update added a new faculty) so callers never need to guard against a
    KeyError here."""
    data = memory._read_encrypted(_settings_path())
    if not data:
        data = _default_data()
        save(data)
        return data
    changed = False
    if "Review" not in data and "Reasoning" in data:
        # "Reasoning" was renamed to "Review" (it was always only ever
        # used for review/critic/adjudicator/aggregator-review work --
        # see act_script.py's ROLE_FACULTY -- so the old name was just
        # a mislabel, not a different capability). Carry an existing
        # user's models straight over under the new name rather than
        # losing them or leaving an orphaned "Reasoning" section no
        # panel will ever show again.
        data["Review"] = data.pop("Reasoning")
        changed = True
    for fac in FACULTIES:
        if fac not in data:
            if fac == "Voice" and data.get("Thinking"):
                # Voice is a brand-new faculty added after Thinking's
                # own models already existed and were already doing
                # exactly this job for the floating circle's plain chat
                # chain -- backfill an existing user's save with a real
                # copy of whatever Thinking already has (same ids, same
                # keys) instead of leaving them staring at an empty
                # section that doesn't reflect what's actually been
                # happening in their circle all along. A fresh install
                # never hits this path at all (see _default_data()).
                data[fac] = [dict(e) for e in data["Thinking"]]
            else:
                data[fac] = []
            changed = True
    if changed:
        save(data)
    return data


def save(data):
    """Writes `data` back to disk, encrypted, with the same permission
    lockdown as every other file in Friday's memory folder."""
    path = _settings_path()
    memory._write_encrypted(path, data)
    memory._lock_down(path)


def add_model(data, faculty, name, model, api_key, base_url=""):
    """Adds a brand-new, user-supplied model entry to `faculty` (the
    Settings panel's "+ Add Model" button) and saves immediately. Always
    `check_kind="generic_http"` -- Friday has no real call code for a
    provider it doesn't already know about, so the best it can honestly
    do is a plain reachability check against `base_url` (see
    settings_checks.check_generic_http). Returns the new entry dict.
    """
    if faculty not in FACULTIES:
        raise ValueError(f"Unknown faculty: {faculty!r}")
    entry = _entry(f"custom-{uuid.uuid4().hex[:10]}", name, model,
                   "generic_http", api_key, builtin=False, base_url=base_url)
    data.setdefault(faculty, []).append(entry)
    save(data)
    return entry


def remove_model(data, faculty, model_id):
    """Removes one model entry by id and saves immediately. Safe no-op
    if the faculty/id doesn't exist."""
    data[faculty] = [m for m in data.get(faculty, []) if m.get("id") != model_id]
    save(data)


def update_check_result(data, faculty, model_id, ok, detail, checked_at):
    """Writes a connectivity-check result back onto the matching entry
    and saves. Safe no-op if the entry was removed in the meantime."""
    for entry in data.get(faculty, []):
        if entry.get("id") == model_id:
            entry["status"] = "connected" if ok else "error"
            entry["detail"] = detail
            entry["last_checked"] = checked_at
            save(data)
            return


def mask_key(key):
    """A fully redacted ("hashed out") display form of an API key --
    never any real characters from it, just a fixed-width bullet mask
    plus a length hint so two different keys are still visually
    distinguishable without revealing anything about either one. Even a
    short visible tail is deliberately avoided -- a handful of real
    characters still meaningfully narrows a brute-force attempt for a
    short key."""
    if not key:
        return "not set"
    return "\u2022" * 10 + f"  ({len(key)} chars)"
