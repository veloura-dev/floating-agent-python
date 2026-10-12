"""Friday's long-term memory: an encrypted folder of individual files,
organized by kind, living at MEMORY_DIR below (default `~/.friday`,
overridable via the FRIDAY_MEMORY_PATH environment variable or
`set_memory_dir()` for tests) -- deliberately outside the project folder
so Friday's memory survives a code update/reinstall untouched.

Chosen deliberately as real separate files/folders rather than one opaque
database file, as discussed with the user before building this:

    ~/.friday/
        key.bin                    the local encryption key (see below)
        README.txt                 plain-text explainer, not encrypted
        facts/                     deliberately-saved facts/preferences
            000001.json.enc        one file per fact
            ...
        tasks/
            000001/                one FOLDER per task
                task.json.enc
            ...
        conversations/
            <session-id>/          one folder per run of the app
                000001.json.enc    one file per turn, in order
                ...
        kv/                        small "localStorage"-style session state
            <key>.json.enc
        uploads/                   reserved for an upcoming feature (files
                                    you upload to Friday) -- not used yet
        generated/                 reserved for an upcoming feature
            images/                (images/videos/documents Friday
            videos/                 generates) -- not used yet
            documents/

Every *.json.enc file is a whole JSON object, Fernet-encrypted (AES128-CBC
+ HMAC, via the `cryptography` package) with one local key generated on
first use and stored in `key.bin` next to the data. This protects the
data at rest -- if the `.friday` folder is copied elsewhere, or read by
some other program without the key, its contents are unreadable. It does
**not** protect against someone with access to this same user account on
this same machine (the key lives right next to the data, deliberately,
so Friday can read his own memory without ever prompting for a password)
-- see `_lock_down()` below for the complementary, OS-level half of this:
restricting the whole folder to the current OS user only, so at least
*other* accounts/processes on a shared machine can't read or touch it.

  - `facts/` + `conversations/` are the **vector DB** half — free text
    (deliberately-saved facts/preferences, and the automatic turn-by-turn
    conversation transcript) each stored alongside an embedding, searched
    by cosine similarity for "remember by meaning, not exact words" recall.
  - `tasks/` is the **structured data** half in the classic database
    sense — exact fields (text/due date/status), queried precisely (e.g.
    "list pending tasks"), no embedding involved at all. Each task gets
    its own folder so it (and anything later attached to it) has one
    clear, individually-addressable home.
  - `kv/` is the **localStorage** half — there's no browser here to give
    Friday a literal localStorage API, so this gives small, schema-less
    key/value session state (last-opened folder, UI prefs, ...) the same
    fast get/set *shape* localStorage has, as its own small encrypted
    file per key.

Embeddings: turning text into a vector requires calling *some* model.
This reuses the same tried-in-order fallback philosophy already used for
chat (Gemini, then Groq, then Mistral) — here, Gemini's embedding model
first, then Mistral's (Groq has no embedding endpoint as of this
writing), and finally a pure-numpy local fallback (a deterministic
hashed-bag-of-words vector — no network, no API key, always available,
just lower semantic quality than a real neural embedding) so recall
never goes completely dark just because no key is configured or a
provider is temporarily down.

Important subtlety, handled explicitly rather than ignored: embeddings
from different providers/models are **not comparable** to each other via
cosine similarity, even when their dimensions happen to line up. Every
stored embedding is tagged with exactly which `embed_model` produced it
(see EMBED_MODEL_* constants below), and a similarity search only ever
compares a freshly-computed query embedding against items from that same
model space. If a provider becomes unavailable partway through Friday's
life (a key removed, a model retired) and literally nothing in the
current model space is stored yet, recall falls back to a plain
substring match over the saved text as a last resort rather than
returning nothing — lower precision, but still useful, and clearly
distinguishable from a real semantic hit (see `recall()`'s `exact_only`
field on each result).

A known, accepted tradeoff of this layout versus a single indexed
database: searching means decrypting and scanning every file in the
relevant folder(s), rather than one indexed query. Fine at the scale of
one person's local assistant (hundreds to low thousands of items);
deliberately chosen anyway over a faster opaque single file, because a
real folder of individually-addressable, individually-encrypted files is
what was actually asked for here.
"""

import base64
import hashlib
import json
import os
import re
import threading
import time
import uuid
from collections import deque

import numpy as np
from cryptography.fernet import Fernet, InvalidToken

# ---------------------------------------------------------------------------
# Where the memory folder lives
# ---------------------------------------------------------------------------

DEFAULT_MEMORY_DIR = os.path.join(os.path.expanduser("~"), ".friday")

# Resolved lazily (not at import time) so set_memory_dir()/the environment
# variable can still override it before the first real use.
_memory_dir = None
_LOCK = threading.RLock()


def set_memory_dir(path):
    """Overrides where Friday's whole memory folder lives -- used by
    tests to point at a throwaway temp directory instead of the real
    `~/.friday`. Resets the cached encryption key and scaffold-created
    flag so the next read/write re-derives/re-creates everything fresh
    at the new location."""
    global _memory_dir, _FERNET, _FERNET_DIR, _SCAFFOLD_DONE_FOR, _SESSION_ID
    with _LOCK:
        _memory_dir = path
        _FERNET = None
        _FERNET_DIR = None
        _SCAFFOLD_DONE_FOR = None
        _SESSION_ID = None


def get_memory_dir():
    """The memory folder path actually in effect: set_memory_dir()'s
    value if one was given, else the FRIDAY_MEMORY_PATH environment
    variable, else DEFAULT_MEMORY_DIR."""
    if _memory_dir is not None:
        return _memory_dir
    return os.environ.get("FRIDAY_MEMORY_PATH") or DEFAULT_MEMORY_DIR


def close():
    """Resets cached in-memory state (the encryption key, the
    scaffold-done flag) -- there's no persistent connection to literally
    close with a file-per-item store, this is kept mainly so tests can
    cleanly force a fresh reload between runs."""
    global _FERNET, _FERNET_DIR, _SCAFFOLD_DONE_FOR
    with _LOCK:
        _FERNET = None
        _FERNET_DIR = None
        _SCAFFOLD_DONE_FOR = None


# ---------------------------------------------------------------------------
# OS-level permission lockdown
# ---------------------------------------------------------------------------

def _lock_down(path):
    """Best-effort OS-level permission lockdown so this file/folder is
    reachable only by the current user. This is NOT literal
    delete-proofing -- no userland mechanism can fully stop an owner
    from deleting their own files, and this deliberately doesn't try to
    claim otherwise -- but it does stop *other* users/processes on a
    shared machine from reading, modifying, or deleting Friday's memory
    at all. On POSIX, chmod 700 on the root folder alone is enough: it
    blocks every other user from even traversing into it, which
    transitively protects everything underneath without needing to
    chmod each file individually. On Windows, `icacls` with
    (OI)(CI) (object-inherit/container-inherit) flags on the root
    achieves the same thing for new files created under it afterward.
    Failures here are swallowed on purpose -- restricting permissions is
    a safety layer, never something allowed to block memory from
    working at all (e.g. on an unusual filesystem where chmod isn't
    meaningful).

    The Windows path is deliberately ordered grant-then-restrict, not
    the single combined `/inheritance:r /grant:r user:perm` call this
    used to be: that one-shot version, if the grant half silently failed
    for any reason (an account name icacls couldn't resolve, a locale
    quirk, antivirus/indexing holding a transient lock right after the
    file was created, ...) while the inheritance-stripping half still
    went through, could leave a file with *no* effective permissions at
    all -- not even for its own owner. That exact failure mode is what
    actually happened in practice (a brand-new key.bin immediately
    unreadable by the very process that just created it). Granting
    first, verifying the file is still readable, and only then
    stripping inherited permissions (undoing that step immediately if
    it somehow still broke access) means a failure anywhere in this
    sequence leaves the file at least as accessible as it already was,
    never less.
    """
    try:
        if os.name == "posix":
            os.chmod(path, 0o700 if os.path.isdir(path) else 0o600)
        elif os.name == "nt":
            _lock_down_windows(path)
    except Exception:  # noqa: BLE001
        pass  # best-effort only -- never let this block memory from working


def _lock_down_windows(path):
    import subprocess
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if not user:
        return
    is_dir = os.path.isdir(path)
    grant = f"{user}:(OI)(CI)F" if is_dir else f"{user}:F"

    def _is_accessible():
        try:
            if is_dir:
                with os.scandir(path):
                    return True
            with open(path, "rb"):
                return True
        except OSError:
            return False

    try:
        grant_result = subprocess.run(
            ["icacls", path, "/grant:r", grant],
            capture_output=True, timeout=5, check=False,
        )
        if grant_result.returncode != 0:
            return  # couldn't even confirm the grant -- leave inheritance alone
        if not _is_accessible():
            return  # already can't read it -- don't make things worse
        subprocess.run(
            ["icacls", path, "/inheritance:r"],
            capture_output=True, timeout=5, check=False,
        )
        if not _is_accessible():
            # Stripping inheritance somehow still broke access despite
            # the confirmed grant above -- immediately undo it rather
            # than leaving this file locked out of its own owner.
            subprocess.run(
                ["icacls", path, "/inheritance:e"],
                capture_output=True, timeout=5, check=False,
            )
    except Exception:  # noqa: BLE001
        pass


def _repair_windows_permissions(path):
    """Self-heal for a file that's already ended up in the exact broken
    state _lock_down_windows above is now written to avoid -- e.g. one
    created before this fix shipped. Tries, in rough order of how
    invasive they are: resetting to inherited permissions, re-granting
    the current user full control, and finally taking ownership
    outright (the one that can recover a file even the OS no longer
    considers "owned" by anyone reachable). Returns True once `path`
    is readable again, False if every attempt failed -- never raises.
    POSIX is a no-op (chmod failures here are a different, much rarer
    situation not worth the same treatment).
    """
    if os.name != "nt" or os.access(path, os.R_OK):
        return os.access(path, os.R_OK)
    import subprocess
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    attempts = [["icacls", path, "/reset"]]
    if user:
        attempts.append(["icacls", path, "/grant:r", f"{user}:F"])
    attempts.append(["takeown", "/F", path])
    if user:
        attempts.append(["icacls", path, "/grant:r", f"{user}:F"])
    for cmd in attempts:
        try:
            subprocess.run(cmd, capture_output=True, timeout=5, check=False)
        except Exception:  # noqa: BLE001
            pass
        if os.access(path, os.R_OK):
            return True
    return False


def _open_readable_with_retry(path, attempts=5, delay=0.2):
    """Opens `path` for binary reading, retrying through a brief,
    growing backoff if it's transiently unreadable -- most commonly
    real-time antivirus/indexing on Windows holding a short-lived lock
    on a file that was just created moments before (key.bin right after
    _fernet() writes it, for instance), which typically clears within a
    few hundred milliseconds. If every retry still fails with a
    permissions error specifically, makes one last attempt at an actual
    ACL repair (_repair_windows_permissions) before giving up for good.
    Raises the original PermissionError (with a clearer, actionable
    message attached) if nothing works -- this one failure is too
    important to silently swallow the way _read_encrypted's per-item
    scanning does, since it means the *entire* memory system is
    unreadable, not just one fact/task/conversation.
    """
    last_exc = None
    for i in range(attempts):
        try:
            with open(path, "rb") as f:
                return f.read()
        except PermissionError as exc:
            last_exc = exc
            if i < attempts - 1:
                time.sleep(delay * (i + 1))
    if _repair_windows_permissions(path):
        try:
            with open(path, "rb") as f:
                return f.read()
        except PermissionError as exc:
            last_exc = exc
    raise PermissionError(
        f"{last_exc}. Friday's encryption key at {path} is locked by Windows "
        "file permissions and couldn't be repaired automatically. Close "
        "Friday completely, then in an elevated (Run as administrator) "
        f'Command Prompt run: icacls "{path}" /reset -- then start Friday '
        "again.") from last_exc



_MEMORY_ROOT_README = (
    "This folder is Friday's long-term memory: saved facts and "
    "preferences, your task list, and the conversation history, all "
    "individually encrypted on disk.\n\n"
    "- key.bin is the encryption key. If it's lost or replaced, "
    "everything else in here becomes permanently unreadable -- it is "
    "NOT optional, back it up if you back up this folder.\n"
    "- This folder's permissions are locked down to your user account "
    "only on this machine, automatically.\n"
    "- Don't move, rename, or delete this folder while Friday is "
    "running, and don't delete it at all unless you actually want to "
    "erase everything Friday remembers.\n"
    "- uploads/ and generated/ are reserved for upcoming features and "
    "aren't used yet.\n"
)

_SCAFFOLD_DONE_FOR = None


def _ensure_scaffold():
    """Creates the whole folder layout (idempotent, cached per memory
    dir so this is a cheap no-op after the first call for a given
    directory) and locks down the root. Called from _ensure_folder()
    below, so it transparently runs before anything ever touches disk."""
    global _SCAFFOLD_DONE_FOR
    mem_dir = get_memory_dir()
    if _SCAFFOLD_DONE_FOR == mem_dir:
        return
    os.makedirs(mem_dir, exist_ok=True)
    _lock_down(mem_dir)
    for sub in ("facts", "tasks", "conversations", "kv"):
        os.makedirs(os.path.join(mem_dir, sub), exist_ok=True)

    # Reserved scaffolding for upcoming features (uploading files to
    # Friday, and Friday-generated images/videos/documents) -- each
    # given a stable, organized, individual folder in advance so that
    # when those features ship, reaching their content (by Friday or by
    # hand) is immediate rather than needing another migration later.
    uploads = os.path.join(mem_dir, "uploads")
    os.makedirs(uploads, exist_ok=True)
    _write_readme_once(uploads,
        "Reserved for files you upload to Friday (upcoming feature). "
        "Not used yet.\n")

    generated = os.path.join(mem_dir, "generated")
    for kind in ("images", "videos", "documents"):
        os.makedirs(os.path.join(generated, kind), exist_ok=True)
    _write_readme_once(generated,
        "Reserved for images/videos/documents Friday generates "
        "(upcoming feature). Not used yet.\n")

    _write_readme_once(mem_dir, _MEMORY_ROOT_README)
    _SCAFFOLD_DONE_FOR = mem_dir


def _write_readme_once(folder, text):
    path = os.path.join(folder, "README.txt")
    if os.path.exists(path):
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:  # noqa: BLE001
        pass


def _ensure_folder(*parts):
    """Joins `parts` onto the current memory dir, creates it (and the
    whole surrounding scaffold, the first time) and returns the path."""
    _ensure_scaffold()
    path = os.path.join(get_memory_dir(), *parts)
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------

_FERNET = None
_FERNET_DIR = None  # which memory dir the cached Fernet instance belongs to


def _fernet():
    """The shared Fernet instance for the current memory dir, creating
    (and locking down) key.bin on first use. Re-derived automatically
    whenever the memory dir changes (set_memory_dir()/close() reset the
    cache) so tests pointed at a fresh temp dir never reuse a stale key.
    """
    global _FERNET, _FERNET_DIR
    mem_dir = get_memory_dir()
    if _FERNET is None or _FERNET_DIR != mem_dir:
        _ensure_scaffold()
        key_path = os.path.join(mem_dir, "key.bin")
        if os.path.exists(key_path):
            key = _open_readable_with_retry(key_path).strip()
        else:
            key = Fernet.generate_key()
            with open(key_path, "wb") as f:
                f.write(key)
            _lock_down(key_path)
        _FERNET = Fernet(key)
        _FERNET_DIR = mem_dir
    return _FERNET


def _encrypt_obj(obj):
    return _fernet().encrypt(json.dumps(obj).encode("utf-8"))


def _decrypt_obj(blob):
    return json.loads(_fernet().decrypt(blob).decode("utf-8"))


def _write_encrypted(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _write_bytes_with_retry(path, _encrypt_obj(obj))


def _write_bytes_with_retry(path, blob, attempts=5, delay=0.2):
    """Writes `blob` to `path`, retrying through a brief, growing backoff
    if the file is transiently unwritable -- the write-side counterpart
    to `_open_readable_with_retry` above, for the same real-world cause
    (Windows antivirus/indexing/cloud-sync briefly holding a lock on a
    file right after it's touched). If every retry still fails with a
    permissions error specifically, makes one last attempt at an actual
    ACL repair (_repair_windows_permissions) -- relevant when `path`
    already exists from a previous run and ended up in a broken ACL
    state -- before giving up for good. Raises the original
    PermissionError, with a clearer and actionable message appended, if
    nothing works -- a save failure here is too important to silently
    swallow (previously this used a bare `open(path, "wb")`, so any
    transient lock or stuck ACL on an *existing* settings/memory file
    surfaced as a raw, unexplained traceback instead of either healing
    itself or telling the user what to actually do about it).
    """
    last_exc = None
    for i in range(attempts):
        try:
            with open(path, "wb") as f:
                f.write(blob)
            return
        except PermissionError as exc:
            last_exc = exc
            if i < attempts - 1:
                time.sleep(delay * (i + 1))
    if os.path.exists(path) and _repair_windows_permissions(path):
        try:
            with open(path, "wb") as f:
                f.write(blob)
            return
        except PermissionError as exc:
            last_exc = exc
    raise PermissionError(
        f"{last_exc}. Friday couldn't save {path} because Windows denied "
        "write access. This is usually either (a) another copy of Friday "
        "already running and holding this file open -- close every other "
        "Friday window/terminal, then try again, or (b) Windows Defender's "
        "Controlled Folder Access blocking Python from writing under your "
        "user folder -- allow python.exe in Windows Security > Virus & "
        "threat protection > Manage ransomware protection > Controlled "
        "folder access, or turn it off there temporarily."
    ) from last_exc


def _read_encrypted(path):
    """Returns the decrypted dict, or None if the file is missing,
    corrupted, or was encrypted with a different/unreadable key (e.g.
    key.bin was lost or replaced). Callers treat None as "skip this one"
    during a folder scan rather than letting one bad file crash the
    whole operation.

    A transient PermissionError specifically (e.g. Windows antivirus/
    indexing holding a brief lock on a file moments after it was
    written -- see _open_readable_with_retry's own docstring) gets a
    short retry before being treated as "unreadable, skip it" the same
    as any other failure here -- cheap insurance against a freshly
    saved fact/task/conversation briefly looking like it never saved at
    all."""
    try:
        try:
            blob = _open_readable_with_retry(path, attempts=3, delay=0.1)
        except PermissionError:
            return None
        return _decrypt_obj(blob)
    except (InvalidToken, FileNotFoundError, ValueError, OSError,
            json.JSONDecodeError, UnicodeDecodeError):
        return None
    except Exception:  # noqa: BLE001
        return None


def _next_seq(folder):
    """Atomically returns the next integer id for items under `folder`,
    persisted in a plain-text `_seq.txt` counter so ids keep climbing
    across restarts instead of colliding. Guarded by the same module
    lock every other write already goes through."""
    seq_path = os.path.join(folder, "_seq.txt")
    with _LOCK:
        current = 0
        if os.path.exists(seq_path):
            try:
                with open(seq_path, "r", encoding="utf-8") as f:
                    current = int((f.read() or "0").strip() or "0")
            except Exception:  # noqa: BLE001
                current = 0
        nxt = current + 1
        with open(seq_path, "w", encoding="utf-8") as f:
            f.write(str(nxt))
        return nxt


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

GEMINI_EMBED_MODEL_ID = "gemini:text-embedding-004"
MISTRAL_EMBED_MODEL_ID = "mistral:mistral-embed"
LOCAL_EMBED_MODEL_ID = "local:hashvec-v1:256"
LOCAL_EMBED_DIM = 256

# How similar (cosine) a result has to be to count as a real semantic
# hit at all, as opposed to noise -- tuned loosely rather than precisely,
# since "relevant enough to mention" is inherently fuzzy. Applies equally
# to real neural embeddings and the local hashed fallback.
_MIN_SIMILARITY = 0.2

# Common English filler words excluded from the local hash-vector
# fallback (not from real neural embeddings, which already handle this
# correctly on their own) -- without this, two otherwise-unrelated
# sentences that both happen to contain "the"/"is"/"a" register as
# falsely similar, since every word (common or not) gets equal weight in
# a plain hashed bag-of-words. Short and blunt on purpose: this only
# needs to catch the highest-frequency words that would otherwise
# dominate the vector, not be a complete/linguistically rigorous list.
_STOPWORDS = frozenset("""
a an the is are was were be been being am i you he she it we they
this that these those of in on at to for with as by from up down
and or but if then so than too very just do does did have has had
my your his her its our their me him them us not no yes can will
would should could what who whom which when where why how
""".split())


def _embed_via_gemini(text, api_key):
    """Returns a float32 numpy vector via Gemini's embedding model, or
    raises. Broken out as its own module-level function (rather than
    inlined in embed_text()) specifically so tests can monkeypatch it to
    simulate success/failure without a real API key or network access —
    the same dependency-injection spirit as app_panels.py's
    RealLauncher/FakeLauncher pair."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    result = client.models.embed_content(
        model="text-embedding-004",
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=768),
    )
    values = result.embeddings[0].values
    return np.array(values, dtype=np.float32)


def _embed_via_mistral(text, api_key):
    """Same idea as _embed_via_gemini, via Mistral's embedding model."""
    from mistralai import Mistral

    client = Mistral(api_key=api_key)
    response = client.embeddings.create(model="mistral-embed", inputs=[text])
    values = response.data[0].embedding
    return np.array(values, dtype=np.float32)


def _embed_local_fallback(text, dim=LOCAL_EMBED_DIM):
    """A deterministic, dependency-free stand-in for a real embedding:
    feature-hashing (the "hashing trick") bag-of-words -- every word
    hashes to one of `dim` buckets with a deterministic +1/-1 sign, the
    resulting vector is L2-normalized. Two texts sharing a lot of the
    same words land close together under cosine similarity; texts
    sharing no words are roughly orthogonal. This is keyword-overlap
    similarity, not true semantic understanding (it won't connect "a big
    car" with "an SUV" the way a real neural embedding would) -- but it
    never needs a network, an API key, or a heavy ML dependency, so
    recall degrades gracefully instead of breaking outright when no
    embedding provider is configured or reachable."""
    vec = np.zeros(dim, dtype=np.float32)
    words = [w for w in re.findall(r"[a-z0-9']+", (text or "").lower())
             if w not in _STOPWORDS]
    for w in words:
        digest = hashlib.md5(w.encode("utf-8")).hexdigest()
        h = int(digest, 16)
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return vec


def embed_text(text):
    """Turns `text` into (vector, embed_model_id), trying Gemini then
    Mistral (whichever has a key configured and actually succeeds) before
    falling back to the always-available local hash vector. Never
    raises -- the local fallback has no external dependency to fail on."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            return _embed_via_gemini(text, gemini_key), GEMINI_EMBED_MODEL_ID
        except Exception:  # noqa: BLE001
            pass

    mistral_key = os.environ.get("MISTRAL_API_KEY", "")
    if mistral_key:
        try:
            return _embed_via_mistral(text, mistral_key), MISTRAL_EMBED_MODEL_ID
        except Exception:  # noqa: BLE001
            pass

    return _embed_local_fallback(text), LOCAL_EMBED_MODEL_ID


def _cosine_similarity(a, b):
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


# ---------------------------------------------------------------------------
# Shared semantic-search mechanics (facts/ + conversations/)
# ---------------------------------------------------------------------------

def _list_fact_files():
    folder = _ensure_folder("facts")
    return sorted(
        os.path.join(folder, fn) for fn in os.listdir(folder)
        if fn.endswith(".json.enc")
    )


def _list_conversation_files():
    folder = _ensure_folder("conversations")
    paths = []
    for session in sorted(os.listdir(folder)):
        sdir = os.path.join(folder, session)
        if not os.path.isdir(sdir):
            continue
        for fn in sorted(os.listdir(sdir)):
            if fn.endswith(".json.enc"):
                paths.append(os.path.join(sdir, fn))
    return paths


def _search_items(list_fn, query, max_results=5, category=None,
                   query_embedding=None):
    """Shared semantic-search mechanics behind recall()/recall_conversation():
    embeds `query` fresh, compares it against every item from `list_fn()`
    whose embed_model matches the *current* embedding space (see this
    module's docstring for why cross-model comparison isn't valid), and
    returns the top `max_results` scoring above `_MIN_SIMILARITY`. If the
    current model space has no items at all yet (e.g. the embedding
    provider changed since everything currently stored was saved), falls
    back to a plain case-insensitive substring match over `text` instead
    of returning nothing -- each result dict's `exact_only` flag says
    which path produced it.

    `query_embedding`, if given, is a pre-computed (vector, model_id)
    pair -- lets a caller searching more than one source for the *same*
    query (e.g. build_context_block() searching both facts and
    conversation history) embed it exactly once instead of once per
    source, since embedding is the one step here that can mean a real
    network call.
    """
    query_vec, model_id = query_embedding if query_embedding else embed_text(query)
    paths = list_fn()

    same_space = []
    for p in paths:
        obj = _read_encrypted(p)
        if obj is None:
            continue
        if category and obj.get("category") != category:
            continue
        if obj.get("embed_model") == model_id:
            same_space.append(obj)

    if not same_space:
        # Nothing in the current embedding space -- fall back to a plain
        # substring match rather than reporting zero results.
        ql = (query or "").lower()
        fallback = []
        for p in paths:
            obj = _read_encrypted(p)
            if obj is None:
                continue
            if category and obj.get("category") != category:
                continue
            if ql in (obj.get("text") or "").lower():
                fallback.append(obj)
        fallback.sort(key=lambda o: o.get("created_at", 0), reverse=True)
        results = []
        for obj in fallback[:max_results]:
            d = {k: v for k, v in obj.items() if k != "embedding"}
            d["score"] = None
            d["exact_only"] = True
            results.append(d)
        return results

    scored = []
    for obj in same_space:
        vec = np.array(obj.get("embedding") or [], dtype=np.float32)
        score = _cosine_similarity(query_vec, vec)
        if score >= _MIN_SIMILARITY:
            d = {k: v for k, v in obj.items() if k != "embedding"}
            d["score"] = score
            d["exact_only"] = False
            scored.append(d)
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:max_results]


# ---------------------------------------------------------------------------
# Facts (deliberately-saved memories/preferences/notes)
# ---------------------------------------------------------------------------

def _fact_path(fact_id):
    return os.path.join(_ensure_folder("facts"), f"{int(fact_id):06d}.json.enc")


def remember(text, category="fact"):
    """Saves `text` as a new fact, embedding it immediately and writing
    it to its own file under facts/. Returns the new fact's id."""
    text = (text or "").strip()
    if not text:
        raise ValueError("remember() needs non-empty text")
    vector, model_id = embed_text(text)
    now = time.time()
    with _LOCK:
        folder = _ensure_folder("facts")
        fid = _next_seq(folder)
        obj = {
            "id": fid, "text": text, "category": category or "fact",
            "embedding": vector.astype(float).tolist(), "embed_model": model_id,
            "created_at": now, "updated_at": now,
        }
        _write_encrypted(_fact_path(fid), obj)
        return fid


def recall(query, max_results=5, category=None):
    """Semantic search over saved facts. Returns a list of dicts:
    id/text/category/embed_model/created_at/updated_at/score/exact_only,
    highest score first."""
    return _search_items(_list_fact_files, query, max_results, category)


def forget(memory_id):
    """Deletes a fact by id (removes its file under facts/). Returns
    True if it actually existed, False if that id didn't."""
    try:
        path = _fact_path(memory_id)
    except (TypeError, ValueError):
        return False
    with _LOCK:
        if os.path.exists(path):
            os.remove(path)
            return True
        return False


def list_memories(category=None, limit=50):
    """Plain, non-semantic listing of saved facts, most recent first --
    used when a caller wants "what do you remember" rather than a
    similarity search against a specific query."""
    items = []
    for p in _list_fact_files():
        obj = _read_encrypted(p)
        if obj is None:
            continue
        if category and obj.get("category") != category:
            continue
        items.append({k: v for k, v in obj.items()
                      if k not in ("embedding", "embed_model")})
    items.sort(key=lambda o: o.get("created_at", 0), reverse=True)
    return items[:limit]


# ---------------------------------------------------------------------------
# Conversation log (automatic, every turn) -- one folder per session
# ---------------------------------------------------------------------------

_SESSION_ID = None


def _session_id():
    """One id per process run, generated once and reused for every turn
    logged during this run -- the "individual folder for conversation
    history" the session's turns live under. A fresh run (restarting the
    app) gets a fresh folder; cross-session recall still searches every
    session folder that exists (see _list_conversation_files())."""
    global _SESSION_ID
    if _SESSION_ID is None:
        _SESSION_ID = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    return _SESSION_ID


def log_turn(role, text):
    """Saves one turn (role is "user" or "friday") to this session's
    conversation folder, embedding it immediately. Blocking -- see
    log_turn_async() for the fire-and-forget version used from the UI
    thread so a slow embedding call never delays anything user-facing."""
    text = (text or "").strip()
    if not text:
        return None
    vector, model_id = embed_text(text)
    now = time.time()
    with _LOCK:
        folder = _ensure_folder("conversations", _session_id())
        seq = _next_seq(folder)
        obj = {
            "id": seq, "role": role, "text": text,
            "embedding": vector.astype(float).tolist(), "embed_model": model_id,
            "created_at": now,
        }
        _write_encrypted(os.path.join(folder, f"{seq:06d}.json.enc"), obj)
        return seq


def log_turn_async(role, text):
    """Fire-and-forget version of log_turn(), run on a daemon background
    thread -- the same "plain threading.Thread, no result waited on"
    shape app_panels.py's own _discover_and_embed already uses for its
    background work. Intended to be called only *after* Friday's reply
    has already been shown/spoken, so a slow embedding call never adds
    latency to anything the user is waiting on. Any failure is swallowed
    (memory logging is a courtesy, not something that should ever surface
    as a user-facing error)."""
    def _run():
        try:
            log_turn(role, text)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_run, daemon=True).start()


def recall_conversation(query, max_results=5):
    """Semantic search over the automatic conversation transcript,
    across every session folder that exists."""
    return _search_items(_list_conversation_files, query, max_results)


# ---------------------------------------------------------------------------
# Tasks (plain structured data -- no embedding involved; one folder each)
# ---------------------------------------------------------------------------

def _task_dir(task_id):
    return os.path.join(_ensure_folder("tasks"), f"{int(task_id):06d}")


def _task_path(task_id):
    return os.path.join(_task_dir(task_id), "task.json.enc")


def _list_task_files():
    folder = _ensure_folder("tasks")
    paths = []
    for name in sorted(os.listdir(folder)):
        sub = os.path.join(folder, name)
        if not os.path.isdir(sub):
            continue
        p = os.path.join(sub, "task.json.enc")
        if os.path.exists(p):
            paths.append(p)
    return paths


def add_task(text, due_date=""):
    """Adds a new pending task, each one living in its own folder under
    tasks/. Returns its id."""
    text = (text or "").strip()
    if not text:
        raise ValueError("add_task() needs non-empty text")
    now = time.time()
    with _LOCK:
        folder = _ensure_folder("tasks")
        tid = _next_seq(folder)
        obj = {
            "id": tid, "text": text, "due_date": due_date or "",
            "status": "pending", "created_at": now, "completed_at": None,
        }
        _write_encrypted(_task_path(tid), obj)
        return tid


def list_tasks(status="pending"):
    """Lists tasks. `status` is "pending", "done", or "all"."""
    items = []
    for p in _list_task_files():
        obj = _read_encrypted(p)
        if obj is None:
            continue
        if status != "all" and obj.get("status") != status:
            continue
        items.append(obj)
    items.sort(key=lambda o: o.get("created_at", 0), reverse=True)
    return items


def find_tasks(which, status="pending"):
    """Fuzzy-matches `which` against open tasks' text, the same
    substring-matching spirit app_panels.py's AppPanelManager._match uses
    for "which panel did they mean" -- returns a list of matching task
    dicts (0, 1, or many; the caller decides what to do with ambiguity,
    same pattern as complete_task()/delete_task() below)."""
    which_lower = (which or "").strip().lower()
    candidates = list_tasks(status=status)
    if not which_lower:
        return candidates
    exact = [t for t in candidates if t["text"].strip().lower() == which_lower]
    if exact:
        return exact
    return [t for t in candidates if which_lower in t["text"].lower()]


def complete_task(task_id):
    """Marks a task done by id. Returns True if it existed and wasn't
    already done."""
    with _LOCK:
        try:
            path = _task_path(task_id)
        except (TypeError, ValueError):
            return False
        obj = _read_encrypted(path)
        if obj is None or obj.get("status") == "done":
            return False
        obj["status"] = "done"
        obj["completed_at"] = time.time()
        _write_encrypted(path, obj)
        return True


def delete_task(task_id):
    """Deletes a task outright (as opposed to marking it done) --
    removes its whole folder under tasks/."""
    with _LOCK:
        try:
            task_dir = _task_dir(task_id)
        except (TypeError, ValueError):
            return False
        path = os.path.join(task_dir, "task.json.enc")
        if not os.path.exists(path):
            return False
        os.remove(path)
        try:
            os.rmdir(task_dir)  # only succeeds if now empty; harmless otherwise
        except OSError:
            pass
        return True


# ---------------------------------------------------------------------------
# kv_store ("localStorage")
# ---------------------------------------------------------------------------

def _kv_path(key):
    safe = base64.urlsafe_b64encode((key or "").encode("utf-8")).decode("ascii")
    safe = safe.rstrip("=") or "_empty_"
    return os.path.join(_ensure_folder("kv"), f"{safe}.json.enc")


def kv_set(key, value):
    """Stores `value` (anything JSON-serializable) under `key`,
    overwriting any existing value."""
    now = time.time()
    obj = {"key": key, "value": value, "updated_at": now}
    with _LOCK:
        _write_encrypted(_kv_path(key), obj)


def kv_get(key, default=None):
    """Returns the value stored under `key`, or `default` if unset."""
    obj = _read_encrypted(_kv_path(key))
    if obj is None:
        return default
    return obj.get("value", default)


def kv_delete(key):
    """Removes `key` entirely. Returns True if it existed."""
    with _LOCK:
        path = _kv_path(key)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False


# ---------------------------------------------------------------------------
# Recent-turns buffer -- fixes the "I just told you X and you forgot"
# failure mode
# ---------------------------------------------------------------------------
#
# Every reply Friday gives is one single, stateless request to the LLM
# (see agent_overlay.py's AIWorker -- there's no running chat-history
# object at all). The *only* thing that carries anything from one message
# to the next is this module's retrieval: build_context_block() searching
# whatever's already been embedded and written to disk.
#
# log_turn_async() is deliberately fire-and-forget on a background thread
# so a slow embedding call never delays a reply the user is waiting on --
# but that means a turn can take a real, visible moment (an actual network
# round-trip to the embedding provider, plus a disk write) before it's
# actually searchable. If the user asks something back immediately
# afterward, the search can run *before* that background write has
# landed, and the fact looks "forgotten" even though nothing is actually
# wrong with the embedding or the recall logic itself.
#
# This buffer is the fix: a tiny, in-process, zero-I/O ring of the last
# few raw turns from *this running session*, always available the instant
# they happen, with no embedding/network/disk step in the way at all. It
# is intentionally NOT persisted (it resets on restart) -- long-term,
# cross-session recall is still exactly what build_context_block()'s
# semantic search above already does. This is purely about closing the
# gap for "a moment ago, this same conversation."
_RECENT_TURNS = deque(maxlen=12)  # last 12 raw turns (~6 exchanges)
_RECENT_LOCK = threading.Lock()


def remember_recent_turn(role, text):
    """Appends one raw turn to the in-process recent-turns buffer. Cheap
    and synchronous (no disk, no embedding) -- meant to be called right
    alongside log_turn_async(), not instead of it, so the very next
    prompt can see it with zero delay while the slower, permanent,
    embedded copy is written in the background."""
    text = (text or "").strip()
    if not text:
        return
    with _RECENT_LOCK:
        _RECENT_TURNS.append((role, text))


def get_recent_turns(max_turns=6):
    """Returns up to the last `max_turns` (role, text) tuples from this
    running session, oldest first."""
    with _RECENT_LOCK:
        return list(_RECENT_TURNS)[-max_turns:]


def _clear_recent_turns():
    """Test-only helper -- real usage never needs to clear this."""
    with _RECENT_LOCK:
        _RECENT_TURNS.clear()


# ---------------------------------------------------------------------------
# Retrieval augmentation -- the "automatic" half of memory
# ---------------------------------------------------------------------------

def build_context_block(query, max_memories=3, max_turns=2, max_recent=6):
    """Builds a short text block to append to the system prompt before
    asking the LLM to reply, so Friday can recall things the user never
    explicitly asked it to look up. Two different kinds of recall, both
    folded in here:

    - Recent turns (see the module docstring above): the last few raw
      exchanges from *this running session*, always included regardless
      of relevance to `query` -- instant, no embedding involved, exists
      specifically so an immediate follow-up never looks "forgotten."
    - Semantic search (facts/ + conversations/): anything relevant *by
      meaning*, from any point in history including past sessions, via
      embeddings -- this is the part that can lag a beat behind a turn
      that only just happened (see remember_recent_turn()).

    Returns "" if there's nothing at all to add (deliberately silent
    rather than padding the prompt with noise on every single turn).
    """
    recent = get_recent_turns(max_recent)

    # Embedded once and shared below -- recall() and recall_conversation()
    # would otherwise each embed this same query text independently,
    # turning one network round-trip to the embedding provider into two
    # for every single command. Falls back to letting each call embed
    # for itself if this fails for any reason.
    try:
        query_embedding = embed_text(query)
    except Exception:  # noqa: BLE001
        query_embedding = None

    try:
        memories = _search_items(
            _list_fact_files, query, max_memories, query_embedding=query_embedding
        )
    except Exception:  # noqa: BLE001
        memories = []
    try:
        turns = _search_items(
            _list_conversation_files, query, max_turns,
            query_embedding=query_embedding,
        )
    except Exception:  # noqa: BLE001
        turns = []

    # A plain substring-fallback hit (exact_only) is weaker evidence than
    # a real semantic match -- still worth surfacing, just not presented
    # as confidently relevant.
    lines = []
    if memories:
        lines.append("Relevant things you remember about the user:")
        for m in memories:
            lines.append(f"- {m['text']}")
    if recent:
        lines.append("Earlier in this same conversation, most recent last:")
        for role, text in recent:
            who = "User" if role == "user" else "You"
            lines.append(f"- {who}: {text}")
    # Semantic conversation-history hits that are ALSO already covered by
    # the recent-turns buffer above would just be noisy repetition -- only
    # show one if its text isn't already present verbatim in `recent`.
    recent_texts = {t for _, t in recent}
    turns = [t for t in turns if t["text"] not in recent_texts]
    if turns:
        lines.append("Relevant past conversation (from before, or an earlier session):")
        for t in turns:
            who = "User" if t["role"] == "user" else "You"
            lines.append(f"- {who}: {t['text']}")

    if not lines:
        return ""
    return (
        "\n\n--- From memory (use only if actually relevant; don't "
        "mention checking memory unless it matters) ---\n"
        + "\n".join(lines)
    )
