"""Friday's ACT Script system -- real implementation.

ACT Script is Friday's heavier, multi-model orchestration layer for work
that's too deep for one single-model reply (see agent_overlay.AIWorker
for that normal, lightweight path). It is NOT a replacement for AIWorker
-- it's something the IDE chat's own model can reach for, one task at a
time, via the ide_run_act_script tool (see agent_tools.py), when a task
genuinely needs it.

Three pipelines, one shared principle: **the control loop lives only in
a coordinator function** (run_sequential / run_fan_out / run_debate,
picked by run_act_script's classification step). Every region below
(thinking/planning/coding/review/workers/aggregator/author/critic/
adjudicator/etc.) is a narrow function: it's handed exactly the state it
needs, does its one job, and hands back a result -- it never decides
what runs next, and never reaches into another region's private state.
That's deliberate, not incidental: it's what keeps each region
independently testable and swappable later.

  1. Sequential Rotation -- dependent, multi-step builds/refactors/
     migrations. One real model per step (round-robin), strict
     read-before-write, a shared Contract, mechanical (non-LLM) verify
     after every step, one bounded fix-forward retry on verify failure,
     a Review pass by a model that did not write the work it's judging.
  2. Fan-Out -- breadth/independent-perspective work (research, weighing
     options, debugging hypotheses). N models answer in parallel with
     zero cross-visibility, a different model aggregates (never
     averaging a contradiction, never dropping a claim, never just
     concatenating), mechanical verify where that's possible (URL
     reachability), then a Review pass by yet another different model.
  3. Debate -- whole-artifact quality (reports, strategy, writing that
     needs real scrutiny). One Author (constant across rounds) drafts,
     a different Critic reads it cold each round, the Author revises,
     a constant Adjudicator (never the Author, never that round's
     Critic) decides PROCEED or DONE, bounded by a hard round cap. One
     final cold read by yet another different model before it ships.

Standing rule enforced in all three: whichever model reviews/critiques/
judges a piece of work always differs from whichever model produced it
-- see next_provider()'s `exclude` argument, used at every single one of
those handoffs below.

### Model diversity, honestly
Each Act Script region (Thinking/Planning/Coding/Review/Text
Generation -- see ROLE_FACULTY) draws its real, callable rotation pool
from settings_store.py's matching faculty, surfaced in the Settings
panel (settings_panel.py). A region whose own faculty is empty falls
back to whatever's configured under Thinking (pre-seeded with Friday's
three original builtin providers: Gemini, Groq, Mistral), so every
region keeps working out of the box; anything a user adds under a
*specific* faculty becomes a genuinely bigger, independent pool for just
that region -- real extra quota/rate-limit headroom exactly where it was
added, not an exhaustive roster of hypothetical vendors. If only one
real model is configured for a region at all, the "reviewer differs from
producer" rule literally cannot be satisfied there -- next_provider()
says so plainly (via its `degraded` return value) rather than silently
pretending the review is independent when it isn't.

### Where the real API calls live
The three builtin dispatchers (_dispatch_gemini/_dispatch_groq/
_dispatch_mistral) call each settings_store entry's own api_key/model --
never a single hardcoded global key -- so two different entries of the
same provider kind (e.g. two separate Gemini keys, added under two
different faculties) are genuinely independent rotation slots.
_dispatch_generic_http is the one broadly-applicable call Friday can
make for a user-added custom provider it has no dedicated integration
for (OpenAI-compatible POST .../chat/completions -- see its own
docstring). GEMINI_MODEL/GROQ_MODEL/MISTRAL_MODEL/API key constants
below are still sourced from agent_overlay.py when importable (same
reasoning as before: agent_overlay.py pulls in PySide6, so the import is
best-effort, with a hand-copied env-var fallback for when it truly can't
be imported) -- they only matter now as settings_store.py's own
first-run default seed values and call_model()'s per-kind fallback-model
lists, not as the dispatchers' key source anymore.
"""
import json
import os
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field


def _load_env_file(path=None):
    """Same tiny KEY=VALUE loader as agent_overlay.py's own
    _load_env_file -- duplicated here (not imported) for exactly the
    reason explained in this module's docstring: importing
    agent_overlay.py at all drags in PySide6."""
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


try:
    import agent_overlay as _overlay  # noqa: E402  (see module docstring)
    GEMINI_API_KEY = _overlay.GEMINI_API_KEY
    GEMINI_MODEL = _overlay.GEMINI_MODEL
    GEMINI_FALLBACK_MODELS = _overlay.FALLBACK_MODELS
    GROQ_API_KEY = _overlay.GROQ_API_KEY
    GROQ_MODEL = _overlay.GROQ_MODEL
    GROQ_FALLBACK_MODELS = _overlay.GROQ_FALLBACK_MODELS
    MISTRAL_API_KEY = _overlay.MISTRAL_API_KEY
    MISTRAL_MODEL = _overlay.MISTRAL_MODEL
    MISTRAL_FALLBACK_MODELS = _overlay.MISTRAL_FALLBACK_MODELS
    REQUEST_TIMEOUT_SECONDS = _overlay.AI_REQUEST_TIMEOUT_SECONDS
except Exception:  # noqa: BLE001 -- PySide6 missing, or any other import snag
    _load_env_file()
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = "gemini-3.8-flash"
    GEMINI_FALLBACK_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    GROQ_MODEL = "llama-3.3-70b-versatile"
    GROQ_FALLBACK_MODELS = ["llama-3.1-8b-instant"]
    MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
    MISTRAL_MODEL = "mistral-small-latest"
    MISTRAL_FALLBACK_MODELS = ["ministral-8b-latest"]
    REQUEST_TIMEOUT_SECONDS = 30

import memory  # noqa: E402 -- plain stdlib-ish module, no Qt, safe to import eagerly
import settings_store  # noqa: E402 -- plain module, no Qt; single source of truth for region pools


# ---------------------------------------------------------------------------
# Provider plumbing
#
# Every Act Script region pulls its real, callable model pool from
# settings_store.py's per-faculty roster (surfaced to the user in
# settings_panel.py's Settings UI) rather than a fixed 3-item list --
# see ROLE_FACULTY below. A region whose own faculty has nothing
# configured yet automatically falls back to the Thinking faculty (kept
# pre-seeded with Friday's three original builtin providers), so
# everything keeps working exactly as before out of the box; the moment
# a user adds one or more models under a *specific* faculty, that
# region switches to using ONLY those -- real, dedicated capacity of
# its own, taken entirely off the shared Thinking pool rather than
# diluted into one bigger shared list, which is real extra quota/
# rate-limit headroom exactly where it was added, not just bookkeeping.
# ---------------------------------------------------------------------------

ROLE_FACULTY = {
    "thinking": "Thinking",
    "planning": "Planning",
    "coding": "Coding",
    "reasoning": "Review",      # review / critic / adjudicator / aggregator / fan-out review
    "writing": "Text Generation",  # debate's Author
    "voice": "Voice",           # not used internally here -- agent_overlay.AIWorker's own chain
}
FALLBACK_FACULTY = "Thinking"


def _dispatch_gemini(entry, system_prompt, user_prompt, model_name):
    """Real call against one settings_store entry. Raises on failure --
    call_model() is what turns that into a clean (ok, error) result."""
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=entry.get("api_key", ""),
        http_options=types.HttpOptions(timeout=int(REQUEST_TIMEOUT_SECONDS * 1000)),
    )
    config = types.GenerateContentConfig(system_instruction=system_prompt)
    response = client.models.generate_content(
        model=model_name, contents=user_prompt, config=config,
    )
    return (getattr(response, "text", None) or "").strip()


def _dispatch_groq(entry, system_prompt, user_prompt, model_name):
    import groq

    client = groq.Groq(api_key=entry.get("api_key", ""), timeout=REQUEST_TIMEOUT_SECONDS)
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return (response.choices[0].message.content or "").strip()


def _dispatch_mistral(entry, system_prompt, user_prompt, model_name):
    from mistralai.client import Mistral

    client = Mistral(
        api_key=entry.get("api_key", ""),
        timeout_ms=int(REQUEST_TIMEOUT_SECONDS * 1000),
    )
    response = client.chat.complete(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return (response.choices[0].message.content or "").strip()


def _dispatch_generic_http(entry, system_prompt, user_prompt, model_name):
    """OpenAI-compatible POST .../chat/completions -- the one broadly-
    applicable real call Friday can make for a user-added "+ Add Model"
    entry (see settings_panel.py) whose exact provider it has no
    dedicated integration for. Covers OpenAI itself, OpenRouter,
    Together, and self-hosted OpenAI-compatible servers (Ollama, LM
    Studio, vLLM, ...) -- the overwhelming majority of real "bring your
    own provider" cases. `entry["base_url"]` is the provider's base API
    URL; `/chat/completions` is appended unless already present."""
    import requests

    base = (entry.get("base_url") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("no API base URL configured for this custom model.")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = entry.get("api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


# check_kind -> callable(entry, system_prompt, user_prompt, model_name) ->
# text. Deliberately a plain module-level dict (not a hardcoded if/elif
# chain) so dev_tests/test_act_script.py can monkeypatch individual
# entries -- same seam this codebase already uses for memory.py's
# embedding calls (see test_friday_memory.py) -- to exercise the real
# Router/region control flow, tool execution, mechanical verify, and
# memory logging without needing live network credentials.
_DISPATCH = {
    "gemini": _dispatch_gemini,
    "groq": _dispatch_groq,
    "mistral": _dispatch_mistral,
    "generic_http": _dispatch_generic_http,
}

# The known fallback-model lists for Friday's three original builtin
# kinds -- tried, in order, after an entry's own configured "model"
# string, same resilience behavior this had before per-region pools
# existed. Custom (generic_http) entries have no such list -- Friday
# can't know a truly arbitrary provider's alternate model names.
_BUILTIN_FALLBACK_MODELS = {
    "gemini": GEMINI_FALLBACK_MODELS,
    "groq": GROQ_FALLBACK_MODELS,
    "mistral": MISTRAL_FALLBACK_MODELS,
}


@dataclass
class CallResult:
    ok: bool
    text: str = ""
    provider: str = ""
    model: str = ""
    error: str = ""


_NO_PROVIDER_MSG = (
    "Act Script needs at least one configured AI model for its Thinking "
    "region -- open Settings and add an API key under Thinking (every "
    "other region falls back to Thinking's pool when its own has nothing "
    "configured, so that's the one that must have something) before "
    "trying again."
)


def _settings_data():
    """Fresh read of settings_store on every call (no caching) so a
    model added/edited/removed in the Settings panel takes effect on
    the very next Act Script run, no restart needed. Never raises --
    a settings-store hiccup degrades to \"nothing configured\" rather
    than crashing a run that may not even touch the broken faculty."""
    try:
        return settings_store.load()
    except Exception:  # noqa: BLE001
        return {}


def _chat_capable_entries(data, faculty):
    """Entries under `faculty` that are actually real, callable chat
    models right now: a recognized check_kind, a non-empty API key, and
    a model name to call. Filters out embedding/local-audio/search
    entries and anything not yet configured."""
    return [
        e for e in data.get(faculty, [])
        if e.get("check_kind") in _DISPATCH and e.get("api_key") and e.get("model")
    ]


def region_pool(role):
    """Every real, callable settings_store entry currently configured
    for Act Script role `role` (see ROLE_FACULTY). If that role's own
    faculty has anything configured at all, those entries are used
    exclusively -- a user adding one (or several) models under a
    specific faculty gives that region real, dedicated capacity of its
    own, taking that region's traffic entirely off the shared Thinking
    pool rather than just diluting a bigger shared list with it (the
    more literal reading of "give this region more quota"). Only when
    the role's own faculty is completely empty does it fall back to the
    Thinking faculty's pool, so every region still works out of the box
    before a user configures anything region-specific. Returns a list
    of plain settings_store entry dicts
    (id/name/model/api_key/base_url/check_kind/...)."""
    data = _settings_data()
    faculty = ROLE_FACULTY.get(role, FALLBACK_FACULTY)
    own = _chat_capable_entries(data, faculty)
    if own or faculty == FALLBACK_FACULTY:
        return own
    return _chat_capable_entries(data, FALLBACK_FACULTY)


def provider_label(role, provider_id):
    """Human-friendly display name for a provider id within `role`'s
    pool -- a user-added custom entry's own name (e.g. "My OpenRouter
    key") rather than its opaque internal id. Falls back to the raw id
    if the entry can't be found (e.g. removed from Settings mid-run).
    Display only -- callers must keep comparing/rotating on the raw id."""
    if not provider_id:
        return "(none)"
    for e in region_pool(role):
        if e["id"] == provider_id:
            return e.get("name") or provider_id
    return provider_id


def available_providers(role):
    """Ids of every real, callable model currently configured for
    region `role`, in a fixed order (see region_pool)."""
    return [e["id"] for e in region_pool(role)]


def next_provider(role, after=None, exclude=None):
    """Round-robins over region `role`'s own pool, starting just after
    `after` (if present in this pool -- otherwise starts from the top,
    which is the expected, harmless outcome when `after` belongs to a
    different role's pool entirely). `exclude` is the "must differ from
    the producer" set -- skipped if at all possible. Returns
    (provider_id_or_None, degraded): degraded is True only when there
    was truly no way to honor `exclude` (e.g. a single model configured
    for this role at all) and a repeat had to be returned anyway --
    callers should surface that plainly rather than silently pretending
    the review was independent."""
    pool = region_pool(role)
    ids = [e["id"] for e in pool]
    if not ids:
        return None, True
    exclude = exclude or set()
    start_idx = (ids.index(after) + 1) % len(ids) if after in ids else 0
    ordered = ids[start_idx:] + ids[:start_idx]
    for pid in ordered:
        if pid not in exclude:
            return pid, False
    return ordered[0], True


def call_model(role, provider_id, system_prompt, user_prompt):
    """One real call to region `role`'s `provider_id` entry, falling
    back once to each of its own known fallback models (builtin kinds
    only) on failure. Never raises -- always returns a CallResult, so
    every coordinator below can apply its own documented failure route
    (skip/retry/degrade/escalate) instead of crashing the whole run over
    one bad call."""
    entry = next((e for e in region_pool(role) if e["id"] == provider_id), None)
    if entry is None:
        return CallResult(ok=False, provider=provider_id,
                           error=f"{provider_id} isn't configured for the {role} region.")
    dispatch = _DISPATCH.get(entry.get("check_kind"))
    if dispatch is None:
        return CallResult(ok=False, provider=provider_id,
                           error=f"{entry.get('name', provider_id)} has no runnable chat integration.")

    primary_model = entry.get("model") or ""
    extra_models = [m for m in _BUILTIN_FALLBACK_MODELS.get(entry.get("check_kind"), [])
                    if m and m != primary_model]
    models_to_try = ([primary_model] if primary_model else []) + extra_models
    last_err = None
    for model_name in models_to_try:
        try:
            text = dispatch(entry, system_prompt, user_prompt, model_name)
            return CallResult(ok=True, text=text or "(empty response)",
                               provider=provider_id, model=model_name)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
    name = entry.get("name", provider_id)
    return CallResult(ok=False, provider=provider_id, error=f"{name} error: {last_err}")


# ---------------------------------------------------------------------------
# Shared helpers: JSON extraction, mechanical verify, evidence/memory log
# ---------------------------------------------------------------------------

def _extract_json(text):
    """Models don't always obey "respond with ONLY JSON" -- strips
    markdown fences and pulls out the first {...}/[...] block before
    trying json.loads, so a stray "Sure, here you go:" preamble doesn't
    break parsing. Returns None (never raises) if nothing usable is
    found, so every call site can apply its own documented degrade
    path."""
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    candidate = match.group(1) if match else text
    try:
        return json.loads(candidate)
    except Exception:  # noqa: BLE001
        return None


_FILE_BLOCK_RE = re.compile(
    r"===FILE:\s*(?P<path>.+?)\s*===\n(?P<content>.*?)(?:\n===END===|\Z)",
    re.DOTALL,
)


def _extract_file_blocks(text):
    """Pulls (path, content) pairs out of Coding's ===FILE: ...=== /
    ===END=== format. Returns [] for a plain NO_FILE_CHANGES reply (or
    anything else that doesn't contain a single file block)."""
    if not text:
        return []
    return [(m.group("path").strip(), m.group("content"))
            for m in _FILE_BLOCK_RE.finditer(text)]


def _workspace_root():
    """The IDE's real open workspace folder, if Agent Mode/the IDE is
    currently on -- None otherwise (callers fall back to os.getcwd())."""
    try:
        import agent_tools
        if agent_tools.is_agent_mode_on() and agent_tools._ide_app is not None:
            return agent_tools._ide_app.fs.root
    except Exception:  # noqa: BLE001
        pass
    return None


def run_mechanical_check(command, timeout=30):
    """Runs `command` as a real shell command, in the IDE's real open
    workspace if there is one. Mechanical means mechanical: no model is
    involved in deciding pass/fail here, only the command's own exit
    code. Returns (passed, output)."""
    if not command or not command.strip() or command.strip() == "true":
        return True, "(no mechanical check specified for this step)"
    cwd = _workspace_root() or os.getcwd()
    try:
        proc = subprocess.run(
            command, shell=True, cwd=cwd, capture_output=True, text=True,
            timeout=timeout,
        )
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return proc.returncode == 0, output
    except Exception as exc:  # noqa: BLE001
        return False, f"error running mechanical check: {exc}"


def _log_evidence(run_id, kind, payload):
    """Evidence/provenance trail for a run -- a short searchable summary
    via memory.remember() plus the full raw record via memory.kv_set(),
    matching the spec's "every step/round/worker answer is provenance"
    requirement. Best-effort: a memory hiccup must never abort an
    in-flight Act Script run."""
    payload = dict(payload or {})
    summary = payload.get("summary") or json.dumps(payload, default=str)[:300]
    try:
        memory.remember(f"[act_script:{run_id}] {kind}: {summary}", category="act_script")
    except Exception:  # noqa: BLE001
        pass
    try:
        key = f"act_script_run:{run_id}"
        record = memory.kv_get(key, default={"run_id": run_id, "entries": []})
        record["entries"].append({"kind": kind, "ts": time.time(), **payload})
        memory.kv_set(key, record)
    except Exception:  # noqa: BLE001
        pass


def _read_file_or_note(path):
    """Fresh read-before-write -- used by Coding/Review so they're
    always working from the file's real current content, never from
    anything a previous step merely claimed."""
    try:
        import agent_tools
        content = agent_tools.ide_read_file(path)
        if content.startswith("Error reading"):
            return f"(doesn't exist yet: {path})"
        return content
    except Exception as exc:  # noqa: BLE001
        return f"(couldn't read {path}: {exc})"


def _write_files(file_blocks):
    """Writes every (path, content) pair for real via agent_tools'
    actual ide_write_file -- the same function a normal IDE-chat tool
    call would use, so these edits show up live in the IDE exactly like
    any other agent edit. Returns the list of paths actually written."""
    import agent_tools
    written = []
    for path, content in file_blocks:
        result = agent_tools.ide_write_file(path, content)
        if not result.startswith("Error"):
            written.append(path)
    return written


# ---------------------------------------------------------------------------
# Thinking (top-level classification -- which pipeline actually fits)
# ---------------------------------------------------------------------------

CLASSIFY_SYSTEM = """You are the Thinking region of Friday's ACT Script \
system -- the first thing that sees any task routed here. Decide which \
of three pipelines actually fits this task, or whether it's too small \
to need any of them.

- sequential: a dependent, multi-step build/refactor/migration, where \
each step's real output must exist before the next step can safely \
start (e.g. "add a field to the model, migrate the DB, update the API, \
update the UI").
- fan_out: breadth / independent perspectives -- research questions, \
weighing options, debugging hypotheses, wanting several independent \
takes merged into one.
- debate: a single whole artifact where quality matters more than speed \
-- a report, a strategy document, a piece of writing -- worth drafting, \
critiquing cold, and revising before it ships.
- single: everything else -- a plain question or small task not worth \
the overhead of any of the above.

Respond with ONLY a JSON object, no prose before or after:
{"route": "sequential"|"fan_out"|"debate"|"single", "reason": "<one sentence>"}
"""

_VALID_ROUTES = {"sequential", "fan_out", "debate", "single"}


def thinking_classify(user_request, provider):
    result = call_model("thinking", provider, CLASSIFY_SYSTEM, user_request)
    if not result.ok:
        return "single", result
    data = _extract_json(result.text)
    route = (data or {}).get("route", "single")
    if route not in _VALID_ROUTES:
        route = "single"
    return route, result


# ---------------------------------------------------------------------------
# Sequential Rotation
# ---------------------------------------------------------------------------

SEQUENTIAL_THINKING_SYSTEM = """You are the Thinking region of Friday's \
ACT Script system, in Sequential Rotation mode -- for dependent, \
multi-step build/refactor/migration work where each step builds on the \
last. Your ONLY job: read the user's request and produce a short \
Contract (the non-negotiable constraints/acceptance criteria this work \
must satisfy) plus a rough ordered list of steps. You never write any \
actual code or file content yourself -- that's the Coding region's job, \
later, one step at a time, each with only its own narrow slice visible.

Respond with ONLY a JSON object, no prose before or after:
{"contract": "<2-5 sentences: what must be true when this is done>",
 "steps": ["<step 1 description>", "<step 2 description>", "..."]}
Keep steps to the minimum needed -- split only where one step's real, \
verified output must exist before the next step can safely start."""


def _sequential_thinking(user_request, provider):
    result = call_model("thinking", provider, SEQUENTIAL_THINKING_SYSTEM, user_request)
    if not result.ok:
        return None, result
    data = _extract_json(result.text)
    if not data or not data.get("steps"):
        return None, result
    return data, result


SEQUENTIAL_PLANNING_SYSTEM_TMPL = """You are the Planning region of \
Friday's ACT Script system, in Sequential Rotation mode. The Thinking \
region already produced a Contract and a rough step list -- your job is \
to turn that into a literal, executable step table. You add no new \
scope and write no code yourself.

Contract:
{contract}

Rough steps:
{steps}

For EACH step, write a literal shell command that mechanically proves \
that step's real work actually happened -- e.g. `python -c "from pathlib \
import Path; assert Path('file.py').is_file()"` or `python -m py_compile \
file.py`. \
The verifier runs through the host shell (Windows cmd.exe on Windows, \
POSIX shell elsewhere). Prefer Python-based file checks for portability; \
do not use POSIX-only commands such as grep or test on Windows. A command \
that passes on a no-op is not acceptable. If you truly cannot construct \
a meaningful check, use exactly: true

Respond with ONLY a JSON object, no prose before or after:
{{"steps": [{{"description": "...", "file_hint": "relative/path.ext", \
"verify_command": "..."}}, "..."]}}
(file_hint may be a comma-separated list, or empty if no particular \
file is implicated yet.)"""


def _sequential_planning(user_request, contract, rough_steps, provider):
    system = SEQUENTIAL_PLANNING_SYSTEM_TMPL.format(
        contract=contract, steps="\n".join(f"- {s}" for s in rough_steps),
    )
    result = call_model("planning", provider, system, user_request)
    if not result.ok:
        return None, result
    data = _extract_json(result.text)
    if not data or not data.get("steps"):
        return None, result
    return data, result


SEQUENTIAL_CODING_SYSTEM_TMPL = """You are the Coding region of \
Friday's ACT Script system, in Sequential Rotation mode, executing ONE \
step of a larger plan. You only ever see this one step's narrow slice \
-- not the whole plan, not any other step's internal reasoning -- just \
this step's description, the shared Contract, and the REAL current \
content of whatever file(s) are relevant (read fresh, just now -- trust \
this, not any assumption about what they "should" already contain).

Contract: {contract}

This step: {description}

Current real content of the relevant file(s):
{file_contents}

Make the real, concrete change(s) this step needs. Output ONLY file \
blocks, one per file touched, FULL file content each time (never a \
diff), in exactly this format:

===FILE: relative/path.ext===
<entire file content>
===END===

If this step genuinely needs no file changes, output exactly: \
NO_FILE_CHANGES"""


def _sequential_read_hinted_files(file_hint):
    paths = [p.strip() for p in (file_hint or "").split(",") if p.strip()]
    if not paths:
        return "(no specific file hinted for this step yet -- use your judgment)"
    return "\n\n".join(f"--- {p} ---\n{_read_file_or_note(p)}" for p in paths)


def _sequential_do_step(contract, step, provider):
    file_contents = _sequential_read_hinted_files(step.get("file_hint", ""))
    system = SEQUENTIAL_CODING_SYSTEM_TMPL.format(
        contract=contract, description=step.get("description", ""),
        file_contents=file_contents,
    )
    result = call_model("coding", provider, system, step.get("description", ""))
    if not result.ok:
        return {"written": [], "model": None, "error": result.error}
    if result.text.strip() == "NO_FILE_CHANGES":
        return {"written": [], "model": result.model, "error": None}
    blocks = _extract_file_blocks(result.text)
    written = _write_files(blocks)
    return {"written": written, "model": result.model, "error": None}


SEQUENTIAL_FIX_SYSTEM_TMPL = """You are still the Coding region of \
Friday's ACT Script system, fixing ONE mechanical verify failure for \
the step you just wrote -- not re-touching anything else. Same step, \
same Contract, one bounded fix attempt.

Contract: {contract}
Step: {description}
Mechanical verify command: {verify_command}
Its real output (why it failed): {verify_output}

Current real content of the file(s) you touched (fresh read, after your \
last attempt):
{file_contents}

Fix exactly what the verify command is complaining about. Output ONLY \
file blocks, full content, same format as before:
===FILE: relative/path.ext===
<entire file content>
===END==="""


def _sequential_fix_step(contract, step, written_paths, verify_command, verify_output, provider):
    file_contents = (
        "\n\n".join(f"--- {p} ---\n{_read_file_or_note(p)}" for p in written_paths)
        if written_paths else _sequential_read_hinted_files(step.get("file_hint", ""))
    )
    system = SEQUENTIAL_FIX_SYSTEM_TMPL.format(
        contract=contract, description=step.get("description", ""),
        verify_command=verify_command, verify_output=verify_output[:1000],
        file_contents=file_contents,
    )
    result = call_model("coding", provider, system, "")
    if not result.ok:
        return []
    blocks = _extract_file_blocks(result.text)
    return _write_files(blocks)


SEQUENTIAL_REVIEW_SYSTEM_TMPL = """You are the Review region of \
Friday's ACT Script system, in Sequential Rotation mode -- the final \
check before this multi-step build is reported done. CRITICAL: a \
different model wrote the work you're judging. Verify skeptically from \
the real current files, never from anything a prior step merely \
claimed.

Original user request: {user_request}
Contract: {contract}

Step-by-step evidence:
{evidence}

Current real content of every file touched:
{all_file_contents}

Judge against the Contract AND the original request. Respond with ONLY \
a JSON object, no prose before or after:
{{"verdict": "done"|"local_bug"|"spec_issue"|"cosmetic"|"await_decision", \
"report": "<3-6 plain-language sentences: what you checked, what you found>", \
"options": ["<short option label>", "..."]}}
Only include "options" when verdict is "await_decision" AND there are \
2-4 genuinely distinct, concrete paths forward worth offering as quick \
choices (e.g. "Use SQLite" / "Use Postgres") -- omit it (empty list) \
otherwise."""


def _sequential_review(user_request, contract, evidence_log, provider):
    all_paths = sorted({p for e in evidence_log for p in e.get("written", [])})
    all_file_contents = (
        "\n\n".join(f"--- {p} ---\n{_read_file_or_note(p)}" for p in all_paths)
        or "(no files were written)"
    )
    evidence_text = "\n".join(
        f"- {e['step']} -- provider {e['provider']}, files {e['written'] or '(none)'}, "
        f"verify {'PASSED' if e['verify_passed'] else 'FAILED'}"
        f"{' (fixed on retry)' if e['fixed'] else ''}: {e['verify_output'][:200]}"
        for e in evidence_log
    )
    system = SEQUENTIAL_REVIEW_SYSTEM_TMPL.format(
        user_request=user_request, contract=contract, evidence=evidence_text,
        all_file_contents=all_file_contents,
    )
    result = call_model("reasoning", provider, system, "")
    data = _extract_json(result.text) if result.ok else None
    if not data:
        return {"verdict": "done" if result.ok else "spec_issue",
                "report": result.text if result.ok else (result.error or "Review failed.")}
    return data


def run_sequential(user_request):
    run_id = uuid.uuid4().hex[:8]
    providers = available_providers("thinking")
    if not providers:
        return _NO_PROVIDER_MSG

    thinking_provider = providers[0]
    thinking_data, think_result = _sequential_thinking(user_request, thinking_provider)
    if thinking_data is None:
        return (f"Act Script (Sequential): couldn't produce a plan -- "
                f"{think_result.error or 'the model reply was not valid JSON.'}")
    contract = thinking_data.get("contract", "")
    rough_steps = thinking_data.get("steps", [])
    _log_evidence(run_id, "thinking",
                  {"summary": contract, "provider": thinking_provider, "rough_steps": rough_steps})

    planning_provider, _ = next_provider("planning", after=thinking_provider)
    plan_data, _plan_result = _sequential_planning(user_request, contract, rough_steps, planning_provider)
    if plan_data and plan_data.get("steps"):
        steps = plan_data["steps"]
    else:
        # Degrade gracefully: run the rough steps as-is with no mechanical check,
        # rather than failing the whole run over a planning parse miss.
        steps = [{"description": s, "file_hint": "", "verify_command": "true"} for s in rough_steps]
    _log_evidence(run_id, "planning",
                  {"summary": f"{len(steps)} step(s) planned", "provider": planning_provider, "steps": steps})

    evidence_log = []
    coder_provider = planning_provider
    for i, step in enumerate(steps):
        coder_provider, _ = next_provider("coding", after=coder_provider)
        step_result = _sequential_do_step(contract, step, coder_provider)
        verify_command = step.get("verify_command") or "true"
        passed, output = run_mechanical_check(verify_command)
        fixed = False
        if not passed and verify_command.strip() != "true":
            fixed_paths = _sequential_fix_step(
                contract, step, step_result["written"], verify_command, output, coder_provider,
            )
            if fixed_paths:
                passed2, output2 = run_mechanical_check(verify_command)
                if passed2:
                    passed, output, fixed = True, output2, True
                    step_result["written"] = sorted(set(step_result["written"]) | set(fixed_paths))
        evidence_log.append({
            "step": step.get("description", ""),
            "provider": coder_provider,
            "written": step_result["written"],
            "verify_command": verify_command,
            "verify_passed": passed,
            "verify_output": output,
            "fixed": fixed,
        })
        _log_evidence(run_id, "step", {
            "summary": f"step {i + 1}: {step.get('description', '')} -> "
                       f"verify {'OK' if passed else 'FAILED'}",
            "provider": coder_provider, "written": step_result["written"],
            "verify_passed": passed,
        })

    review_provider, review_degraded = next_provider("reasoning", after=coder_provider, exclude={coder_provider})
    review = _sequential_review(user_request, contract, evidence_log, review_provider)
    _log_evidence(run_id, "review", {
        "summary": review.get("report", "")[:300], "provider": review_provider,
        "verdict": review.get("verdict"),
    })

    verdict = review.get("verdict", "done")
    report = review.get("report", "(no report produced)")
    failed_steps = [e for e in evidence_log if not e["verify_passed"]]

    header = (
        f"**Act Script -- Sequential Rotation** (run `{run_id}`, {len(steps)} step(s); "
        f"reviewed by {provider_label('reasoning', review_provider)}"
        + (" -- only one model configured, so review could not be independent"
           if review_degraded else f" after {provider_label('coding', coder_provider)} coded the last step")
        + ")\n\n"
    )
    body = "\n".join(
        f"- Step {i + 1}: {e['step']} -- {provider_label('coding', e['provider'])} -- "
        f"verify {'passed' if e['verify_passed'] else 'FAILED'}"
        f"{' (fixed on retry)' if e['fixed'] else ''}"
        for i, e in enumerate(evidence_log)
    )
    if verdict == "await_decision":
        # Literal control tags, not prose -- this is what actually makes
        # the IDE chat panel pause, arm its 2-minute no-reply timer, and
        # (when options are present) render them as clickable choices.
        # See agent_overlay.py's _extract_await_decision/
        # _extract_decision_options -- they strip these tags before the
        # user ever sees them; everything before the tags is the
        # visible chat bubble text.
        options = [o for o in (review.get("options") or []) if o][:4]
        tags = "\n\n{{AWAIT_DECISION}}"
        if len(options) >= 2:
            tags += " {{OPTIONS: " + " | ".join(f'"{o}"' for o in options) + "}}"
        return header + body + f"\n\n\u26a0\ufe0f {report}" + tags
    tail = f"\n\nReview verdict: {verdict}. {report}"
    if failed_steps and verdict == "done":
        tail += (f"\n\n(Note: {len(failed_steps)} step(s) never passed mechanical "
                 f"verify even after a retry -- flagged above.)")
    return header + body + tail


# ---------------------------------------------------------------------------
# Fan-Out
# ---------------------------------------------------------------------------

FAN_OUT_THINKING_SYSTEM = """You are the Thinking region of Friday's \
ACT Script system, in Fan-Out mode -- for breadth/independent-\
perspective work: research questions, weighing options, debugging \
hypotheses, multi-reviewer checks. Frame the question precisely \
(standalone, self-contained -- a worker will see only this) and decide \
the merge rule the Aggregator must follow.

Respond with ONLY a JSON object, no prose before or after:
{"question": "<the precise, standalone question each worker answers>",
 "merge_rule": "<1-2 sentences: what counts as agreement vs. contradiction for THIS question>",
 "stakes": "simple"|"contested"|"high"}"""

_FAN_OUT_N_BY_STAKES = {"simple": 2, "contested": 4, "high": 6}

FAN_OUT_WORKER_SYSTEM_TMPL = """You are one independent worker in \
Friday's ACT Script Fan-Out system. Answer the question below \
completely on your own -- you have no visibility into any other \
worker's answer and never will. Be concrete, cite sources/evidence for \
claims where you can, and say plainly when you're not sure.

Question: {question}"""

FAN_OUT_AGGREGATOR_SYSTEM_TMPL = """You are the Aggregator region of \
Friday's ACT Script Fan-Out system. {n} independent workers answered \
the same question with zero visibility into each other. Merge rule: \
{merge_rule}

Rules you must follow, no exceptions:
- Never average a contradiction -- if workers disagree, state BOTH \
positions plainly and flag it as contested.
- Preserve per-claim attribution for anything contested or uncertain.
- Confidence must be evidence-based: HIGH only if at least 2 workers \
independently agree AND at least one cited a real source; MEDIUM if \
only one worker had a source; LOW/appendix-only if no source at all.
- Never silently drop a worker's claim, even a minority-of-one -- if \
you're not folding it into the main answer, say so and why.
- This must be a genuine rewrite/synthesis, never a concatenation of \
the workers' answers back to back.

Independent worker answers:
{worker_answers}

Produce the merged answer now."""

FAN_OUT_REVIEW_SYSTEM_TMPL = """You are the Review region of Friday's \
ACT Script Fan-Out system -- a different model than the Aggregator. \
Check: did the merge lose or mislabel anything a worker said with real \
confidence? Is the merge actually better than just picking the single \
best worker answer? Respond with ONLY a JSON object, no prose before or \
after:
{{"verdict": "pass"|"bad_merge", "note": "<1-3 sentences>"}}

Independent worker answers:
{worker_answers}

Merged answer under review:
{merged}"""

_URL_RE = re.compile(r"https?://[^\s)\]\"'<>]+")


def _fan_out_verify_urls(text, timeout=5, limit=5):
    """Mechanical (non-LLM) check: any URL the merge cites is at least
    reachable. Best-effort and silent on failure to reach the network at
    all -- this is a courtesy sanity check, not a hard gate."""
    urls = list(dict.fromkeys(_URL_RE.findall(text)))[:limit]
    if not urls:
        return ""
    try:
        import requests
    except Exception:  # noqa: BLE001
        return ""
    ok_count = 0
    for url in urls:
        try:
            resp = requests.head(url, timeout=timeout, allow_redirects=True)
            if resp.status_code < 400:
                ok_count += 1
        except Exception:  # noqa: BLE001
            try:
                resp = requests.get(url, timeout=timeout)
                if resp.status_code < 400:
                    ok_count += 1
            except Exception:  # noqa: BLE001
                continue
    return f"Mechanical check: {ok_count}/{len(urls)} cited URL(s) reachable."


def run_fan_out(user_request):
    run_id = uuid.uuid4().hex[:8]
    providers = available_providers("thinking")
    if not providers:
        return _NO_PROVIDER_MSG

    thinking_provider = providers[0]
    think_result = call_model("thinking", thinking_provider, FAN_OUT_THINKING_SYSTEM, user_request)
    data = _extract_json(think_result.text) if think_result.ok else None
    if not data or not data.get("question"):
        data = {"question": user_request,
                 "merge_rule": "State both sides plainly if workers disagree; never average.",
                 "stakes": "simple"}
    question = data["question"]
    merge_rule = data.get("merge_rule", "")
    stakes = data.get("stakes", "simple")
    n = _FAN_OUT_N_BY_STAKES.get(stakes, 2)
    _log_evidence(run_id, "thinking",
                  {"summary": question, "provider": thinking_provider, "stakes": stakes, "n": n})

    worker_providers = [providers[i % len(providers)] for i in range(n)]
    _log_evidence(run_id, "planning",
                  {"summary": f"N={n} workers: {worker_providers}", "stakes": stakes})

    worker_system = FAN_OUT_WORKER_SYSTEM_TMPL.format(question=question)
    worker_results = [None] * n
    with ThreadPoolExecutor(max_workers=max(n, 1)) as pool:
        futures = {
            pool.submit(call_model, "thinking", worker_providers[i], worker_system, question): i
            for i in range(n)
        }
        for future in futures:
            i = futures[future]
            try:
                worker_results[i] = future.result(timeout=120)
            except Exception as exc:  # noqa: BLE001
                worker_results[i] = CallResult(ok=False, provider=worker_providers[i], error=str(exc))

    good_workers = [
        (i, worker_providers[i], worker_results[i]) for i in range(n)
        if worker_results[i] and worker_results[i].ok and worker_results[i].text.strip()
    ]
    if not good_workers:
        first_err = next((r.error for r in worker_results if r), "no responses")
        return f"Act Script (Fan-Out): every worker failed or timed out -- {first_err}"
    _log_evidence(run_id, "workers", {
        "summary": f"{len(good_workers)}/{n} workers answered",
        "answers": [{"provider": p, "text": r.text} for _, p, r in good_workers],
    })

    worker_answers_text = "\n\n".join(
        f"--- Worker {i + 1} ({p}) ---\n{r.text}" for i, p, r in good_workers
    )
    last_worker_provider = good_workers[-1][1]
    aggregator_provider, _ = next_provider(
        "reasoning", after=last_worker_provider, exclude=set(p for _, p, _ in good_workers),
    )
    agg_system = FAN_OUT_AGGREGATOR_SYSTEM_TMPL.format(
        n=len(good_workers), merge_rule=merge_rule, worker_answers=worker_answers_text,
    )
    agg_result = call_model("reasoning", aggregator_provider, agg_system, question)
    if not agg_result.ok:
        best = max(good_workers, key=lambda t: len(t[2].text))
        return (f"Act Script (Fan-Out): aggregator ({provider_label('reasoning', aggregator_provider)}) failed -- "
                f"{agg_result.error} -- falling back to the strongest single worker "
                f"answer ({provider_label('thinking', best[1])}):\n\n{best[2].text}")
    merged = agg_result.text
    _log_evidence(run_id, "aggregate", {"summary": merged[:300], "provider": aggregator_provider})

    verify_note = _fan_out_verify_urls(merged)

    review_provider, review_degraded = next_provider("reasoning", after=aggregator_provider, exclude={aggregator_provider})
    review_system = FAN_OUT_REVIEW_SYSTEM_TMPL.format(
        worker_answers=worker_answers_text, merged=merged,
    )
    review_result = call_model("reasoning", review_provider, review_system, "")
    review_data = _extract_json(review_result.text) if review_result.ok else None
    review_note = (review_data or {}).get("note", "")
    _log_evidence(run_id, "review", {"summary": review_note, "provider": review_provider})

    header = (
        f"**Act Script -- Fan-Out** (run `{run_id}`, {len(good_workers)}/{n} workers: "
        f"{', '.join(provider_label('thinking', p) for _, p, _ in good_workers)}; "
        f"aggregated by {provider_label('reasoning', aggregator_provider)}, "
        f"reviewed by {provider_label('reasoning', review_provider)}"
        + (" -- not fully independent, limited models configured" if review_degraded else "")
        + ")\n\n"
    )
    tail = f"\n\n{verify_note}" if verify_note else ""
    if review_data and review_data.get("verdict") == "bad_merge":
        tail += f"\n\n(Review flagged the merge: {review_note})"
    return header + merged + tail


# ---------------------------------------------------------------------------
# Debate
# ---------------------------------------------------------------------------

DEBATE_THINKING_SYSTEM = """You are the Thinking region of Friday's ACT \
Script system, in Debate mode -- for whole-artifact quality work: \
reports, strategy documents, writing that needs real scrutiny. Produce \
a Brief the Author will follow and separate Review Criteria the \
Critic/Adjudicator will judge against.

Respond with ONLY a JSON object, no prose before or after:
{"brief": "<type, length, audience, thesis, structure, tone, citation/anti-fabrication rules -- everything the Author needs, 4-8 sentences>",
 "review_criteria": "<what counts as BLOCKING vs MAJOR vs MINOR for this specific artifact, 3-5 sentences>",
 "stakes": "low"|"medium"|"high"}"""

_DEBATE_ROUNDS_BY_STAKES = {"low": 2, "medium": 3, "high": 4}

DEBATE_AUTHOR_SYSTEM_TMPL = """You are the Author in Friday's ACT \
Script Debate system -- the same model every round, owning this \
artifact end to end.

Brief: {brief}

{revision_note}
Write the full artifact now -- not a summary, not an outline, the real \
complete thing."""

DEBATE_CRITIC_SYSTEM_TMPL = """You are the Critic in round {round_num} \
of Friday's ACT Script Debate system -- reading this artifact cold, \
with NO access to any earlier round's critique, by design. A different \
model wrote it than you.

Review Criteria: {review_criteria}

Artifact under review:
{draft}

List every real issue you find, tagged BLOCKING, MAJOR, or MINOR. \
Respond with ONLY a JSON object, no prose before or after:
{{"issues": [{{"severity": "BLOCKING"|"MAJOR"|"MINOR", "issue": "..."}}], "overall_note": "..."}}
If there are truly no issues, use an empty issues list."""

DEBATE_ADJUDICATOR_SYSTEM_TMPL = """You are the Adjudicator in \
Friday's ACT Script Debate system -- the same model every round, never \
the Author, never that round's Critic. Judge whether the Author \
substantively addressed round {round_num}'s critique (every BLOCKING \
addressed, every MAJOR addressed-or-declined-with-a-stated-reason, \
nothing silently ignored), whether the critique itself was valid, and \
whether the revision introduced any new problems.

Round {round_num} critique:
{critique}

Author's revision after that critique:
{revision}

Respond with ONLY a JSON object, no prose before or after:
{{"verdict": "PROCEED"|"DONE", "note": "<1-3 sentences>"}}
PROCEED means another round is worth it; DONE means this is good enough to ship."""

DEBATE_FINAL_READ_SYSTEM_TMPL = """One last cold read before this \
ships -- you are yet another different model, seeing this for the \
first time. Review Criteria: {review_criteria}
Flag anything serious; otherwise say plainly that it's ready.

Artifact:
{draft}"""


def run_debate(user_request):
    run_id = uuid.uuid4().hex[:8]
    providers = available_providers("thinking")
    if not providers:
        return _NO_PROVIDER_MSG

    thinking_provider = providers[0]
    think_result = call_model("thinking", thinking_provider, DEBATE_THINKING_SYSTEM, user_request)
    data = _extract_json(think_result.text) if think_result.ok else None
    if not data or not data.get("brief"):
        data = {"brief": user_request,
                 "review_criteria": "Must be accurate, complete, well-organized, and free of fabrication.",
                 "stakes": "low"}
    brief = data["brief"]
    review_criteria = data.get("review_criteria", "")
    stakes = data.get("stakes", "low")
    max_rounds = _DEBATE_ROUNDS_BY_STAKES.get(stakes, 2)
    _log_evidence(run_id, "thinking", {"summary": brief, "provider": thinking_provider, "stakes": stakes})

    # Author draws from the Text Generation region (whole-artifact
    # writing); Adjudicator/Critic/final read draw from Review
    # (judgment work) -- see ROLE_FACULTY.
    author_provider, _ = next_provider("writing", after=thinking_provider)
    adjudicator_provider, _ = next_provider("reasoning", after=author_provider, exclude={author_provider})
    _log_evidence(run_id, "planning", {
        "summary": f"{max_rounds} round(s) max, author={author_provider}, adjudicator={adjudicator_provider}",
    })

    draft_result = call_model("writing", author_provider, DEBATE_AUTHOR_SYSTEM_TMPL.format(brief=brief, revision_note=""), user_request)
    if not draft_result.ok:
        return f"Act Script (Debate): the Author ({provider_label('writing', author_provider)}) failed to draft -- {draft_result.error}"
    draft = draft_result.text

    history = []
    last_critic_provider = author_provider  # seed so round 1's critic can't equal the author
    round_num = 0
    note = "No rounds ran."
    while round_num < max_rounds:
        round_num += 1
        # Excludes the Author (critic must never judge its own producer's
        # work), the previous round's Critic (so it actually rotates),
        # AND the Adjudicator (the Adjudicator's own prompt above
        # promises "never that round's Critic" -- this is what keeps
        # that promise true rather than just asserting it in text).
        critic_provider, _ = next_provider(
            "reasoning", after=last_critic_provider,
            exclude={author_provider, last_critic_provider, adjudicator_provider},
        )
        last_critic_provider = critic_provider
        critic_result = call_model(
            "reasoning", critic_provider,
            DEBATE_CRITIC_SYSTEM_TMPL.format(round_num=round_num, review_criteria=review_criteria, draft=draft),
            "",
        )
        critic_data = _extract_json(critic_result.text) if critic_result.ok else None
        issues = (critic_data or {}).get("issues", [])
        _log_evidence(run_id, "critique", {
            "summary": f"round {round_num}: {len(issues)} issue(s)",
            "provider": critic_provider, "issues": issues,
        })

        if not issues:
            note = "No issues raised this round."
            history.append({"round": round_num, "critic": critic_provider, "issues": issues, "draft": draft})
            break

        revision_note = (
            "A Critic (a different model, reading cold) raised these issues last round "
            "-- address every BLOCKING and either fix or explicitly explain-and-decline "
            "every MAJOR; never silently ignore anything:\n"
            + "\n".join(f"- [{it.get('severity')}] {it.get('issue')}" for it in issues)
        )
        revised_result = call_model(
            "writing", author_provider, DEBATE_AUTHOR_SYSTEM_TMPL.format(brief=brief, revision_note=revision_note), user_request,
        )
        revised = revised_result.text if revised_result.ok else draft

        adjudication = call_model(
            "reasoning", adjudicator_provider,
            DEBATE_ADJUDICATOR_SYSTEM_TMPL.format(
                round_num=round_num, critique=json.dumps(issues), revision=revised,
            ),
            "",
        )
        adj_data = _extract_json(adjudication.text) if adjudication.ok else None
        verdict = (adj_data or {}).get("verdict", "PROCEED" if round_num < max_rounds else "DONE")
        note = (adj_data or {}).get("note", "")
        _log_evidence(run_id, "adjudication", {
            "summary": f"round {round_num}: {verdict} -- {note}", "provider": adjudicator_provider,
        })
        history.append({
            "round": round_num, "critic": critic_provider, "issues": issues,
            "draft_before": draft, "draft_after": revised,
        })
        draft = revised
        if verdict == "DONE":
            break
    else:
        note = note or "Reached the round cap without the Adjudicator saying DONE -- declaring done-at-best."

    final_reader, _ = next_provider(
        "reasoning", after=last_critic_provider, exclude={author_provider, last_critic_provider, adjudicator_provider},
    )
    final_check = call_model(
        "reasoning", final_reader, DEBATE_FINAL_READ_SYSTEM_TMPL.format(review_criteria=review_criteria, draft=draft), "",
    )
    _log_evidence(run_id, "final_read", {
        "summary": (final_check.text[:300] if final_check.ok else final_check.error),
        "provider": final_reader,
    })

    try:
        memory.kv_set(f"act_script_debate_history:{run_id}", history)
    except Exception:  # noqa: BLE001
        pass
    _log_evidence(run_id, "memory", {"summary": "full draft+critique provenance stored", "rounds": len(history)})

    header = (
        f"**Act Script -- Debate** (run `{run_id}`, {round_num} round(s); "
        f"author={provider_label('writing', author_provider)}, "
        f"adjudicator={provider_label('reasoning', adjudicator_provider)}, "
        f"final read by {provider_label('reasoning', final_reader)})\n\n"
    )
    tail = (
        f"\n\n---\nFinal cold read ({provider_label('reasoning', final_reader)}): "
        f"{final_check.text if final_check.ok else '(skipped -- ' + final_check.error + ')'}"
    )
    return header + draft + tail


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_act_script(user_request, mode="auto"):
    """Friday's ACT Script entry point. `mode` is "auto" (Thinking
    classifies it) or one of "sequential"/"fan_out"/"debate" to force a
    pipeline directly. Returns the final report/answer/artifact as plain
    text -- ready to hand straight back to whichever lightweight model
    asked for this (see agent_tools.ide_run_act_script)."""
    providers = available_providers("thinking")
    if not providers:
        return _NO_PROVIDER_MSG

    route = mode if mode in ("sequential", "fan_out", "debate") else None
    if route is None:
        route, _ = thinking_classify(user_request, providers[0])

    if route == "sequential":
        return run_sequential(user_request)
    if route == "fan_out":
        return run_fan_out(user_request)
    if route == "debate":
        return run_debate(user_request)

    result = call_model("thinking", providers[0], "Answer directly and concisely.", user_request)
    if result.ok:
        return result.text
    return f"Couldn't get an answer: {result.error}"
