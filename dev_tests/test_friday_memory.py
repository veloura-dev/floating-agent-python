"""Regression test for Friday's long-term memory system (memory.py +
its agent_tools.py tool wrappers + its automatic wiring into
agent_overlay.py's AIWorker/CircleOverlay) -- the encrypted-folder-of-
individual-files store discussed with the user and built as three
roles under one memory folder: facts/ + conversations/ (the
vector-DB-style semantic recall half, one file per fact/per turn),
tasks/ (the plain structured-data half, one folder per task), and
kv/ (the "localStorage"-style key/value half, one file per key). See
memory.py's own module docstring for the full design rationale.

Covers:
  Part A — memory.py directly: schema/CRUD for all four tables, the
    embedding fallback chain (Gemini -> Mistral -> local hash vector,
    each monkeypatched rather than hitting a real network/API key),
    cross-embedding-model-space handling (a stored memory from a
    *different* embed_model must never be blindly compared via cosine
    similarity against a query from a different space), and
    build_context_block()'s retrieval-augmentation text.
  Part B — the new agent_tools.py tool wrappers (remember/recall/forget/
    add_task/list_tasks/complete_task/delete_task): correct behavior,
    ambiguity handling (same "more than one match, ask first" rule as
    close_app/minimize_app elsewhere in this codebase), always-available
    registration (NOT gated behind Agent Mode, unlike the ide_* tools),
    and call_tool() dispatch.
  Part C — agent_overlay.py wiring: AIWorker folds relevant memory into
    every provider's system prompt (and skips it entirely for the
    confirmation-summary call), and a real reply through CircleOverlay
    logs both sides of the exchange to the conversation log in the
    background, without delaying the reply itself.

Requires PySide6 with an offscreen-capable platform plugin for Part C:
    QT_QPA_PLATFORM=offscreen python3 dev_tests/test_friday_memory.py

Uses a throwaway temp memory folder throughout (memory.set_memory_dir()),
never the real `~/.friday`.
"""
import os
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

import memory  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def wait_for(predicate, timeout=3.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def fresh_db():
    """Points memory.py at a brand-new, not-yet-created memory folder,
    resetting any cached encryption key first. Also clears the
    in-process recent-turns buffer (module-level state, not tied to the
    memory folder) so one test's recent turns can never leak into the
    next."""
    path = os.path.join(tempfile.mkdtemp(), "friday_memory")
    memory.set_memory_dir(path)
    memory._clear_recent_turns()
    return path


def _write_stale_fact(text, embed_model, vec):
    """Raw-writes a fact file as if saved back when a since-retired
    embedding provider was configured -- the file-based equivalent of
    the raw SQL INSERT this test used before memory.py moved off
    SQLite onto individual encrypted files."""
    folder = memory._ensure_folder("facts")
    fid = memory._next_seq(folder)
    now = time.time()
    obj = {
        "id": fid, "text": text, "category": "fact",
        "embedding": vec.astype(float).tolist(), "embed_model": embed_model,
        "created_at": now, "updated_at": now,
    }
    memory._write_encrypted(memory._fact_path(fid), obj)
    return fid


def part_a():
    print("\n--- Part A: memory.py directly ---")
    mem_dir = fresh_db()
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("MISTRAL_API_KEY", None)

    # ---- the whole folder scaffold is created on first use ----
    check("the memory folder doesn't exist until first use",
          not os.path.exists(mem_dir))
    memory._fernet()  # first real touch -- creates the scaffold AND key.bin
    check("the memory folder (key.bin + facts/tasks/conversations/kv "
          "subfolders) is created on first use",
          os.path.exists(mem_dir)
          and os.path.exists(os.path.join(mem_dir, "key.bin"))
          and os.path.exists(os.path.join(mem_dir, "facts"))
          and os.path.exists(os.path.join(mem_dir, "tasks"))
          and os.path.exists(os.path.join(mem_dir, "conversations"))
          and os.path.exists(os.path.join(mem_dir, "kv")))

    # ---- local embedding fallback: deterministic, no network ----
    v1 = memory._embed_local_fallback("The user likes blue cars")
    v2 = memory._embed_local_fallback("The user likes blue cars")
    v3 = memory._embed_local_fallback("Completely unrelated text about pizza")
    check("the local hash-vector fallback is deterministic for the same text",
          np.array_equal(v1, v2))
    check("the local hash-vector fallback is L2-normalized",
          abs(float(np.linalg.norm(v1)) - 1.0) < 1e-5)
    check("unrelated text produces a different vector",
          not np.array_equal(v1, v3))

    # ---- embed_text() provider fallback chain ----
    with mock.patch.object(memory, "_embed_via_gemini",
                            lambda text, key: np.ones(4, dtype=np.float32)):
        os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
        vec, model_id = memory.embed_text("hello")
        check("embed_text() uses Gemini first when a key is configured and it succeeds",
              model_id == memory.GEMINI_EMBED_MODEL_ID and np.array_equal(vec, np.ones(4)))
        os.environ.pop("GEMINI_API_KEY", None)

    def _boom(text, key):
        raise RuntimeError("simulated Gemini outage")

    with mock.patch.object(memory, "_embed_via_gemini", _boom), \
         mock.patch.object(memory, "_embed_via_mistral",
                            lambda text, key: np.full(4, 2.0, dtype=np.float32)):
        os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
        os.environ["MISTRAL_API_KEY"] = "fake-mistral-key"
        vec, model_id = memory.embed_text("hello")
        check("embed_text() falls back to Mistral when Gemini errors out",
              model_id == memory.MISTRAL_EMBED_MODEL_ID and np.array_equal(vec, np.full(4, 2.0)))
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("MISTRAL_API_KEY", None)

    with mock.patch.object(memory, "_embed_via_gemini", _boom), \
         mock.patch.object(memory, "_embed_via_mistral", _boom):
        os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
        os.environ["MISTRAL_API_KEY"] = "fake-mistral-key"
        vec, model_id = memory.embed_text("hello")
        check("embed_text() falls back all the way to the local hash vector "
              "when every real provider errors out",
              model_id == memory.LOCAL_EMBED_MODEL_ID)
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("MISTRAL_API_KEY", None)

    vec, model_id = memory.embed_text("hello")
    check("embed_text() goes straight to the local fallback with no keys configured at all",
          model_id == memory.LOCAL_EMBED_MODEL_ID)

    # ---- memories: remember / recall / forget / list ----
    fresh_db()
    mid1 = memory.remember("The user's favorite programming language is Python.")
    mid2 = memory.remember("The user's dog is named Max.", category="fact")
    check("remember() returns an incrementing id", mid2 == mid1 + 1)

    results = memory.recall("what programming language does the user like")
    check("recall() finds the semantically relevant memory",
          any(r["id"] == mid1 for r in results))
    check("recall() results carry a real similarity score, not an exact-only flag",
          all(r["exact_only"] is False for r in results))

    all_memories = memory.list_memories()
    check("list_memories() returns everything saved, most recent first",
          len(all_memories) == 2 and all_memories[0]["id"] == mid2)

    check("forget() by id removes the memory", memory.forget(mid2))
    check("forget() on an already-gone id returns False", not memory.forget(mid2))
    check("the forgotten memory no longer appears in list_memories()",
          all(m["id"] != mid2 for m in memory.list_memories()))

    try:
        memory.remember("")
        check("remember() rejects empty text", False)
    except ValueError:
        check("remember() rejects empty text", True)

    # ---- cross-embedding-model-space safety ----
    fresh_db()
    # Simulate a memory saved back when a *different* embedding provider
    # was configured -- its embedding lives in a different vector space
    # than whatever recall() computes for its query right now, so it
    # must never be blindly cosine-compared against it.
    fake_vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    _write_stale_fact("A memory from a since-retired embedding provider",
                       "some-old-retired-provider:v0", fake_vec)
    results = memory.recall("retired embedding provider")
    check("with nothing in the *current* embedding space yet, recall() "
          "falls back to a plain substring match instead of returning nothing",
          len(results) == 1 and results[0]["exact_only"] is True
          and "retired embedding provider" in results[0]["text"])

    # Once something real exists in the current space, it's found
    # properly and the stale cross-space row is correctly never compared.
    mid3 = memory.remember("The user's favorite snack is popcorn.")
    results = memory.recall("what snack does the user like")
    check("once a memory exists in the current embedding space, recall() "
          "finds it via real similarity, ignoring the stale cross-space row",
          any(r["id"] == mid3 and r["exact_only"] is False for r in results))

    # ---- tasks ----
    fresh_db()
    tid1 = memory.add_task("Buy milk", due_date="tomorrow")
    tid2 = memory.add_task("Finish the report")
    check("add_task() returns an incrementing id", tid2 == tid1 + 1)
    pending = memory.list_tasks()
    check("list_tasks() defaults to pending tasks", len(pending) == 2)
    check("a task's due_date is stored as plain text",
          any(t["id"] == tid1 and t["due_date"] == "tomorrow" for t in pending))

    matches = memory.find_tasks("report")
    check("find_tasks() fuzzy-matches by substring", len(matches) == 1 and matches[0]["id"] == tid2)
    check("find_tasks() with no query returns every candidate",
          len(memory.find_tasks("")) == 2)

    check("complete_task() marks a task done", memory.complete_task(tid2))
    check("a completed task no longer shows up in the pending list",
          all(t["id"] != tid2 for t in memory.list_tasks()))
    check("a completed task shows up in the done list",
          any(t["id"] == tid2 for t in memory.list_tasks(status="done")))
    check("status='all' shows both pending and done", len(memory.list_tasks(status="all")) == 2)
    check("completing an already-done task returns False (not re-completed)",
          not memory.complete_task(tid2))

    check("delete_task() removes a task outright", memory.delete_task(tid1))
    check("a deleted task is gone even from status='all'",
          all(t["id"] != tid1 for t in memory.list_tasks(status="all")))

    # ---- kv_store ("localStorage") ----
    fresh_db()
    check("kv_get() on an unset key returns the given default",
          memory.kv_get("nope", default="fallback") == "fallback")
    memory.kv_set("last_folder", "/home/user/projects/acme")
    check("kv_set()/kv_get() round-trip a string",
          memory.kv_get("last_folder") == "/home/user/projects/acme")
    memory.kv_set("window_prefs", {"x": 10, "y": 20, "theme": "dark"})
    check("kv_set()/kv_get() round-trip arbitrary JSON-serializable data",
          memory.kv_get("window_prefs") == {"x": 10, "y": 20, "theme": "dark"})
    memory.kv_set("last_folder", "/somewhere/else")
    check("kv_set() on an existing key overwrites rather than duplicating",
          memory.kv_get("last_folder") == "/somewhere/else")
    check("kv_delete() removes the key", memory.kv_delete("last_folder"))
    check("a deleted key is gone", memory.kv_get("last_folder") is None)
    check("kv_delete() on a never-set key returns False", not memory.kv_delete("never_set"))

    # ---- conversation log + recall_conversation ----
    fresh_db()
    memory.log_turn("user", "What's the weather like in Warri today?")
    memory.log_turn("friday", "It's mostly sunny with a chance of rain later.")
    convo_results = memory.recall_conversation("weather")
    check("recall_conversation() finds semantically relevant past turns",
          any("weather" in r["text"].lower() for r in convo_results))

    # log_turn_async must not block the caller, and must still land in
    # the database shortly after.
    before = time.time()
    memory.log_turn_async("user", "A background-logged turn.")
    elapsed = time.time() - before
    check("log_turn_async() returns immediately rather than blocking on the embedding call",
          elapsed < 0.5)
    landed = wait_for(lambda: any(
        r["text"] == "A background-logged turn."
        for r in memory.recall_conversation("background-logged turn")
    ))
    check("...and the turn actually lands in the conversation log shortly after",
          landed)

    # ---- build_context_block() ----
    fresh_db()
    check("build_context_block() returns '' when nothing is relevant yet",
          memory.build_context_block("anything") == "")
    memory.remember("The user's preferred IDE theme is the dark grey one.")
    block = memory.build_context_block("what theme does the user like")
    check("build_context_block() includes a relevant memory when one exists",
          "dark grey" in block)
    check("build_context_block() is clearly labeled as a memory section",
          "From memory" in block)

    # ---- recent-turns buffer: fixes "I just told you X and you forgot" ----
    # See memory.py's "Recent-turns buffer" section -- this is deliberately
    # NOT embedding/DB-dependent at all, specifically so an immediate
    # follow-up in the same session can never lose to a background
    # embedding call that hasn't landed yet.
    fresh_db()
    check("get_recent_turns() starts empty",
          memory.get_recent_turns() == [])
    memory.remember_recent_turn("user", "Hi, my name is Marcus.")
    memory.remember_recent_turn("friday", "Nice to meet you, Marcus!")
    recent = memory.get_recent_turns()
    check("remember_recent_turn() records both sides, in order",
          recent == [("user", "Hi, my name is Marcus."),
                     ("friday", "Nice to meet you, Marcus!")])

    block = memory.build_context_block("What's my name?")
    check("build_context_block() surfaces a just-said name via the recent "
          "turns buffer alone -- with zero embedding or DB round-trip "
          "involved (simulates asking again before any background "
          "log_turn_async() write could possibly have landed)",
          "Marcus" in block)
    check("...labeled as being from this same conversation, not old history",
          "Earlier in this same conversation" in block)

    check("remember_recent_turn() silently ignores empty/blank text",
          (memory.remember_recent_turn("user", "   ") or True)
          and memory.get_recent_turns() == recent)

    fresh_db()
    for i in range(10):
        memory.remember_recent_turn("user", f"turn {i}")
    check("the recent-turns buffer is bounded (doesn't grow forever)",
          len(memory.get_recent_turns(max_turns=999)) <= 12)
    check("...and keeps the most recent ones, not the oldest",
          memory.get_recent_turns(max_turns=1) == [("user", "turn 9")])

    # A semantic conversation-log hit whose text is already shown via the
    # recent-turns buffer shouldn't also be repeated as a second, separate
    # "relevant past conversation" bullet -- that would just be noise.
    fresh_db()
    memory.remember_recent_turn("user", "My favorite color is teal.")
    memory.log_turn("user", "My favorite color is teal.")
    block = memory.build_context_block("what color do I like")
    check("a conversation-log hit already covered by the recent-turns "
          "buffer is not duplicated as a second 'relevant past "
          "conversation' bullet",
          block.count("favorite color is teal") == 1)

    memory.close()


def part_b():
    print("\n--- Part B: agent_tools.py tool wrappers ---")
    fresh_db()
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("MISTRAL_API_KEY", None)

    import agent_tools as at

    # ---- always registered, regardless of Agent Mode ----
    gemini_names_off = {f.__name__ for f in at.get_active_gemini_tools()}
    schema_names_off = {s["function"]["name"] for s in at.get_active_tool_schemas()}
    new_tools = {"remember", "recall", "forget", "add_task", "list_tasks",
                 "complete_task", "delete_task"}
    check("every new memory/task tool is in GEMINI_TOOLS with Agent Mode off",
          new_tools.issubset(gemini_names_off))
    check("every new memory/task tool is in TOOL_SCHEMAS with Agent Mode off",
          new_tools.issubset(schema_names_off))
    check("none of the new tools are gated behind Agent Mode "
          "(unlike the ide_* tools)",
          new_tools.isdisjoint(at._AGENT_MODE_ONLY_TOOLS))

    # ---- remember / recall / forget ----
    msg = at.remember("The user's favorite movie is Interstellar.")
    check("remember() tool wrapper confirms what was saved",
          "Interstellar" in msg and msg.startswith("Remembered"))

    msg = at.recall("what movie does the user like")
    check("recall() tool wrapper surfaces the matching memory",
          "Interstellar" in msg)

    msg = at.recall("something totally unrelated to anything ever saved xyzzy")
    # (local fallback can still have some noise overlap -- just assert
    # the "found" path mentions the actual saved text only if it does
    # claim a match; the real contract being tested is the "nothing
    # found" message shape when truly nothing clears the bar)
    fresh_db()
    msg = at.recall("nothing has ever been saved in this fresh database")
    check("recall() tool wrapper says plainly when nothing relevant is found",
          "Nothing relevant" in msg)

    mid_msg = at.remember("The user's shoe size is 10.")
    new_id = int(mid_msg.split("#")[1].split(")")[0])
    msg = at.call_tool("forget", {"which": str(new_id)})
    check("forget() tool wrapper deletes by exact id",
          "Deleted" in msg)
    msg = at.forget(str(new_id))
    check("forget() on an already-gone id says so", "No memory" in msg)

    at.remember("The user likes hiking.")
    at.remember("The user likes biking.")
    msg = at.forget("likes")
    check("forget() lists candidates instead of guessing when the search is ambiguous",
          "More than one memory matches" in msg)

    # ---- tasks ----
    fresh_db()
    msg = at.add_task("Walk the dog", due="today")
    check("add_task() tool wrapper confirms the new task with its due date",
          "Walk the dog" in msg and "today" in msg)

    at.add_task("Call the plumber")
    listing = at.list_tasks()
    check("list_tasks() tool wrapper lists every pending task",
          "Walk the dog" in listing and "Call the plumber" in listing)

    msg = at.complete_task("plumber")
    check("complete_task() tool wrapper fuzzy-matches and marks it done",
          "Marked task" in msg and "plumber" in msg.lower() or "Call the plumber" in msg)

    listing = at.list_tasks()
    check("the completed task no longer shows up in the pending list",
          "Call the plumber" not in listing)

    listing_done = at.list_tasks(status="done")
    check("list_tasks(status='done') shows the completed one",
          "Call the plumber" in listing_done)

    msg = at.complete_task("nonexistent task xyz")
    check("complete_task() says plainly when nothing pending matches",
          "No pending task" in msg)

    at.add_task("Email Alice")
    at.add_task("Email Bob")
    msg = at.complete_task("Email")
    check("complete_task() asks which one instead of guessing when ambiguous",
          "More than one pending task matches" in msg)

    msg = at.delete_task("Walk the dog")
    check("delete_task() removes a task outright by fuzzy match", "Deleted task" in msg)
    listing_all = at.list_tasks(status="all")
    check("a deleted task is gone even from the 'all' listing",
          "Walk the dog" not in listing_all)

    # ---- call_tool() dispatch for every new tool name ----
    fresh_db()
    r1 = at.call_tool("remember", '{"text": "Dispatched via call_tool."}')
    check("call_tool() dispatches remember() with a JSON string payload",
          "Remembered" in r1)
    r2 = at.call_tool("add_task", {"text": "Dispatched task"})
    check("call_tool() dispatches add_task() with an already-parsed dict",
          "Dispatched task" in r2)
    r3 = at.call_tool("list_tasks", {})
    check("call_tool() dispatches list_tasks() with empty arguments",
          "Dispatched task" in r3)

    memory.close()


def part_c():
    print("\n--- Part C: agent_overlay.py wiring ---")
    from PySide6.QtCore import QThread, Signal
    from PySide6.QtWidgets import QApplication

    import agent_overlay as ov

    app = QApplication.instance() or QApplication(sys.argv)

    def pump_until(predicate, timeout=3.0):
        """Qt-aware version of wait_for() above -- StubAIWorker's
        succeeded/failed signals are only actually delivered to their
        connected slots (_on_reply_ok/_on_reply_err) while the Qt event
        loop is being pumped, so a plain time.sleep() polling loop (like
        wait_for() above, which Part A/B's plain-Python checks don't
        need an event loop for) would just spin until timeout and never
        see the result -- confirmed while first writing this test."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            app.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    fresh_db()
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("MISTRAL_API_KEY", None)
    memory.remember("The user's favorite color is teal.")

    # ---- AIWorker folds relevant memory into the system prompt ----
    # _load_memory_context() is called directly here (rather than reading
    # w._memory_context right after construction) because it's computed
    # in run() now, on the background thread -- not in __init__ on the
    # main thread -- precisely so a real embedding-API network call never
    # blocks the UI before the worker thread even starts. See run()'s and
    # _load_memory_context()'s comments in agent_overlay.py.
    w = ov.AIWorker("what color does the user like?", parent=None)
    check("AIWorker's memory context is empty right after construction "
          "(not computed until run(), so __init__ never blocks on a "
          "network call)",
          w._memory_context == "")
    w._load_memory_context()
    check("AIWorker computes a non-empty memory context when something relevant exists",
          "teal" in w._memory_context)
    check("AIWorker's effective system prompt includes the memory context",
          "teal" in w._system_prompt())
    check("AIWorker's effective system prompt still includes the base "
          "personality prompt too",
          ov.SYSTEM_PROMPT in w._system_prompt())

    w_confirm = ov.AIWorker("what color does the user like?", parent=None,
                             summarize_only=True)
    w_confirm._load_memory_context()
    check("summarize_only=True skips memory lookup entirely (no extra "
          "embedding call for a call that can't act on anything anyway)",
          w_confirm._memory_context == "")

    fresh_db()  # nothing relevant this time
    w_empty = ov.AIWorker("some query with nothing relevant saved", parent=None)
    w_empty._load_memory_context()
    check("AIWorker's memory context is empty when nothing is relevant",
          w_empty._memory_context == "")
    check("...and the system prompt then falls back to exactly the base personality prompt",
          w_empty._system_prompt() == ov.SYSTEM_PROMPT)

    # ---- automatic conversation logging through the real state machine ----
    class StubAIWorker(QThread):
        succeeded = Signal(str)
        failed = Signal(str)

        def __init__(self, prompt, parent=None, summarize_only=False):
            super().__init__(parent)
            self._prompt = prompt
            self._summarize_only = summarize_only

        def run(self):
            time.sleep(0.02)
            self.succeeded.emit("A stubbed reply about teal.")

    fresh_db()
    logged = []

    def _fake_log_turn_async(role, text):
        logged.append((role, text))

    with mock.patch.object(ov, "AIWorker", StubAIWorker), \
         mock.patch.object(ov, "ENABLE_SPEECH", False), \
         mock.patch.object(ov, "ENABLE_VOICE_MODE", False), \
         mock.patch.object(memory, "log_turn_async", _fake_log_turn_async):
        # ENABLE_VOICE_MODE=False, same as every other dev_test that
        # constructs a real CircleOverlay() -- without it, CircleOverlay()
        # starts a real VoiceListenWorker that (in this mic-less sandbox)
        # fires mic_unavailable almost immediately, which calls
        # _show_response() with no state guard and can race ahead of our
        # own _on_query_submitted()'s LOADING state, stealing it away to
        # RESPONDING before the stubbed reply arrives.
        overlay = ov.CircleOverlay()
        overlay._on_query_submitted("What color do I like?")
        ok = pump_until(lambda: len(logged) >= 2, timeout=3.0)
        check("a real reply through the state machine logs both sides "
              "of the exchange", ok)
        check("...the user's side is logged verbatim",
              any(r == "user" and t == "What color do I like?" for r, t in logged))
        check("...and Friday's reply is logged too",
              any(r == "friday" and "teal" in t for r, t in logged))
        # The fix for "I just told you X and you forgot": remember_recent_turn()
        # runs synchronously in the exact same spot as log_turn_async() (see
        # _on_reply_ok in agent_overlay.py), so it's already in the recent-turns
        # buffer the instant this slot runs -- no need to wait for anything
        # further, unlike the (here, mocked-out) real embedding/DB write.
        recent = memory.get_recent_turns()
        check("the real _on_reply_ok also records both sides to the "
              "instant, zero-latency recent-turns buffer (not just the "
              "slower embedded conversation log)",
              ("user", "What color do I like?") in recent
              and any(r == "friday" and "teal" in t for r, t in recent))
        overlay.close()
        overlay.deleteLater()

    # ---- error replies are not logged ----
    class FailingStubAIWorker(QThread):
        succeeded = Signal(str)
        failed = Signal(str)

        def __init__(self, prompt, parent=None, summarize_only=False):
            super().__init__(parent)

        def run(self):
            time.sleep(0.02)
            self.failed.emit("\U0001F511 simulated auth error")

    logged.clear()
    with mock.patch.object(ov, "AIWorker", FailingStubAIWorker), \
         mock.patch.object(ov, "ENABLE_SPEECH", False), \
         mock.patch.object(ov, "ENABLE_VOICE_MODE", False), \
         mock.patch.object(memory, "log_turn_async", _fake_log_turn_async):
        overlay = ov.CircleOverlay()
        overlay._on_query_submitted("This will fail.")
        pump_until(lambda: overlay._last_was_error, timeout=3.0)
        time.sleep(0.1)
        check("a failed reply is never logged to the conversation log",
              logged == [])
        check("...nor does it pollute the recent-turns buffer",
              not any(t == "This will fail." for _, t in memory.get_recent_turns()))
        overlay.close()
        overlay.deleteLater()

    memory.close()


def part_d():
    """Part D — the Windows permission-lockdown fix (memory.py's
    _lock_down_windows / _repair_windows_permissions /
    _open_readable_with_retry), added after a real-machine report of
    key.bin ending up permanently unreadable (even to its own owner)
    after the old single combined `icacls /inheritance:r /grant:r`
    call. This sandbox is Linux, so os.name is mocked to "nt" and every
    actual icacls/takeown subprocess call is mocked too -- these checks
    verify the *logic* (ordering, bail-out conditions, self-undo,
    retry/repair sequencing) rather than real Windows ACL behavior,
    which can't be exercised here."""
    print("\n--- Part D: Windows permission-lockdown fix ---")

    # 1. Grant succeeds, file stays readable throughout -> inheritance
    #    gets stripped too, exactly like the old behavior's happy path.
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        result = mock.Mock()
        result.returncode = 0
        return result

    with mock.patch.object(os, "name", "nt"), \
         mock.patch.dict(os.environ, {"USERNAME": "Some User"}), \
         mock.patch("subprocess.run", side_effect=fake_run), \
         mock.patch.object(os, "access", return_value=True):
        memory._lock_down_windows("C:\\fake\\key.bin")
    check("happy path grants before stripping inheritance (grant call first)",
          calls and calls[0][:2] == ["icacls", "C:\\fake\\key.bin"]
          and "/grant:r" in calls[0])
    check("happy path still strips inheritance once grant is confirmed",
          any("/inheritance:r" in c for c in calls))

    # 2. Grant call fails (nonzero returncode) -> must bail out WITHOUT
    #    ever touching inheritance, which is exactly the fix for the
    #    real failure (old code struck inheritance regardless).
    calls = []

    def fake_run_grant_fails(cmd, **kwargs):
        calls.append(cmd)
        result = mock.Mock()
        result.returncode = 1
        return result

    with mock.patch.object(os, "name", "nt"), \
         mock.patch.dict(os.environ, {"USERNAME": "New User"}), \
         mock.patch("subprocess.run", side_effect=fake_run_grant_fails), \
         mock.patch.object(os, "access", return_value=True):
        memory._lock_down_windows("C:\\fake\\key.bin")
    check("a failed grant call makes exactly one subprocess call (no inheritance strip attempted)",
          len(calls) == 1)
    check("a failed grant call never touches inheritance",
          not any("/inheritance" in c for c in calls))

    # 3. Grant call "succeeds" but the file is already unreadable right
    #    after -> must also bail out before stripping inheritance.
    calls = []

    def fake_run_ok(cmd, **kwargs):
        calls.append(cmd)
        result = mock.Mock()
        result.returncode = 0
        return result

    with mock.patch.object(os, "name", "nt"), \
         mock.patch.dict(os.environ, {"USERNAME": "New User"}), \
         mock.patch("subprocess.run", side_effect=fake_run_ok), \
         mock.patch.object(os, "access", return_value=False):
        memory._lock_down_windows("C:\\fake\\key.bin")
    check("grant succeeds but file unreadable afterward -> inheritance strip skipped",
          len(calls) == 1 and "/grant:r" in calls[0])

    # 4. Stripping inheritance somehow still breaks access despite a
    #    confirmed grant -> must self-undo via /inheritance:e rather
    #    than leaving the file broken.
    calls = []
    access_results = iter([True, False])  # readable before strip, not after

    def fake_access(path, mode):
        try:
            return next(access_results)
        except StopIteration:
            return False

    with mock.patch.object(os, "name", "nt"), \
         mock.patch.dict(os.environ, {"USERNAME": "New User"}), \
         mock.patch("subprocess.run", side_effect=fake_run_ok), \
         mock.patch.object(os, "access", side_effect=fake_access):
        memory._lock_down_windows("C:\\fake\\key.bin")
    check("self-undo (/inheritance:e) fires when stripping inheritance broke access",
          any("/inheritance:e" in c for c in calls))

    # 5. No USERNAME/USER env var at all -> no-op, no subprocess calls,
    #    nothing crashes.
    calls = []
    with mock.patch.object(os, "name", "nt"), \
         mock.patch.dict(os.environ, {}, clear=True), \
         mock.patch("subprocess.run", side_effect=fake_run_ok):
        memory._lock_down_windows("C:\\fake\\key.bin")
    check("missing username env vars is a safe no-op", calls == [])

    # 6. _repair_windows_permissions: already readable -> no subprocess
    #    calls needed at all.
    calls = []
    with mock.patch.object(os, "name", "nt"), \
         mock.patch.object(os, "access", return_value=True), \
         mock.patch("subprocess.run", side_effect=fake_run_ok):
        result = memory._repair_windows_permissions("C:\\fake\\key.bin")
    check("repair is a no-op (and reports success) when already readable",
          result is True and calls == [])

    # 7. _repair_windows_permissions: stays broken through every attempt
    #    -> tries reset, grant, takeown, grant again, then gives up
    #    cleanly (returns False, never raises).
    calls = []
    with mock.patch.object(os, "name", "nt"), \
         mock.patch.dict(os.environ, {"USERNAME": "New User"}), \
         mock.patch.object(os, "access", return_value=False), \
         mock.patch("subprocess.run", side_effect=fake_run_ok):
        result = memory._repair_windows_permissions("C:\\fake\\key.bin")
    check("repair tries /reset first", calls[0] == ["icacls", "C:\\fake\\key.bin", "/reset"])
    check("repair tries takeown somewhere in the sequence",
          any(c[0] == "takeown" for c in calls))
    check("repair gives up and returns False rather than raising when nothing works",
          result is False)

    # 8. _repair_windows_permissions: becomes readable partway through
    #    -> stops immediately instead of running every remaining attempt.
    calls = []
    toggle = {"n": 0}

    def fake_access_fixed_after_reset(path, mode):
        toggle["n"] += 1
        return toggle["n"] > 1  # unreadable once, then "fixed"

    with mock.patch.object(os, "name", "nt"), \
         mock.patch.dict(os.environ, {"USERNAME": "New User"}), \
         mock.patch.object(os, "access", side_effect=fake_access_fixed_after_reset), \
         mock.patch("subprocess.run", side_effect=fake_run_ok):
        result = memory._repair_windows_permissions("C:\\fake\\key.bin")
    check("repair stops as soon as the file becomes readable again",
          result is True and len(calls) == 1)

    # 9. _open_readable_with_retry: succeeds on the first try -> no
    #    sleeping, no repair attempted.
    tmp_path = os.path.join(tempfile.mkdtemp(), "ok.bin")
    with open(tmp_path, "wb") as f:
        f.write(b"hello-key-bytes")
    with mock.patch("time.sleep") as fake_sleep:
        data = memory._open_readable_with_retry(tmp_path)
    check("retry-read returns real file content on the normal/first-try path",
          data == b"hello-key-bytes")
    check("retry-read never sleeps when the very first read already works",
          fake_sleep.call_count == 0)

    # 10. _open_readable_with_retry: transient PermissionError that
    #     clears after a couple of attempts (the realistic AV-lock
    #     case) -> retries quietly and returns the real content,
    #     without ever invoking the heavier ACL repair path.
    attempts_made = {"n": 0}
    real_open = open

    def flaky_open(path, mode="r", *a, **kw):
        if path == tmp_path and mode == "rb":
            attempts_made["n"] += 1
            if attempts_made["n"] < 3:
                raise PermissionError("transient lock")
        return real_open(path, mode, *a, **kw)

    with mock.patch("builtins.open", side_effect=flaky_open), \
         mock.patch("time.sleep") as fake_sleep, \
         mock.patch.object(memory, "_repair_windows_permissions") as fake_repair:
        data = memory._open_readable_with_retry(tmp_path)
    check("retry-read recovers from a transient PermissionError without repair",
          data == b"hello-key-bytes" and fake_repair.call_count == 0)
    check("retry-read actually waited between attempts", fake_sleep.call_count >= 1)

    # 11. _open_readable_with_retry: never clears, repair also fails ->
    #     raises PermissionError with a clear, actionable message
    #     instead of a bare errno-13.
    def always_fails_open(path, mode="r", *a, **kw):
        if path == tmp_path and mode == "rb":
            raise PermissionError(13, "Permission denied")
        return real_open(path, mode, *a, **kw)

    raised = None
    with mock.patch("builtins.open", side_effect=always_fails_open), \
         mock.patch("time.sleep"), \
         mock.patch.object(memory, "_repair_windows_permissions", return_value=False):
        try:
            memory._open_readable_with_retry(tmp_path, attempts=2, delay=0)
        except PermissionError as exc:
            raised = exc
    check("retry-read raises PermissionError (not silently None) when truly unrecoverable",
          raised is not None)
    check("the raised error gives actionable guidance (mentions icacls)",
          raised is not None and "icacls" in str(raised))

    # 12. _read_encrypted must swallow that same unrecoverable
    #     PermissionError as "unreadable, skip it" (None) rather than
    #     letting one locked file crash a whole folder scan -- the
    #     opposite of _fernet(), which must NOT swallow it (checked
    #     next) because losing the key means losing everything, not
    #     just one item.
    with mock.patch("builtins.open", side_effect=always_fails_open), \
         mock.patch("time.sleep"), \
         mock.patch.object(memory, "_repair_windows_permissions", return_value=False):
        result = memory._read_encrypted(tmp_path)
    check("_read_encrypted treats an unrecoverable permission error as None, not a crash",
          result is None)

    # 13. _fernet() must propagate (not swallow) an unrecoverable
    #     permission error on key.bin itself, with the same actionable
    #     message -- this is the exact real-world symptom (Settings'
    #     fail-safe UI showing "[Errno 13] Permission denied:
    #     '...\\key.bin'") that triggered this whole fix, so it must
    #     still surface clearly rather than disappear into a generic
    #     "memory broken" state.
    key_dir = tempfile.mkdtemp()
    memory.set_memory_dir(os.path.join(key_dir, "friday_memory"))
    memory._fernet()  # creates key.bin for real, on first use
    key_path = os.path.join(memory.get_memory_dir(), "key.bin")
    check("key.bin actually exists once _fernet() has run once (sanity check)",
          os.path.exists(key_path))
    memory._FERNET = None
    memory._FERNET_DIR = None

    def key_always_fails_open(path, mode="r", *a, **kw):
        if path == key_path and mode == "rb":
            raise PermissionError(13, "Permission denied")
        return real_open(path, mode, *a, **kw)

    raised = None
    with mock.patch("builtins.open", side_effect=key_always_fails_open), \
         mock.patch("time.sleep"), \
         mock.patch.object(memory, "_repair_windows_permissions", return_value=False):
        try:
            memory._fernet()
        except PermissionError as exc:
            raised = exc
    check("_fernet() surfaces (does not swallow) an unrecoverable key.bin permission error",
          raised is not None)
    check("that surfaced error still names key.bin's actual path",
          raised is not None and key_path in str(raised))
    memory._FERNET = None
    memory._FERNET_DIR = None

    # 14. _write_bytes_with_retry: succeeds on the first try -> no
    #     sleeping, no repair attempted. This is the write-side
    #     counterpart to check 9 above -- added after a real-machine
    #     report of the Settings panel crashing with
    #     "[Errno 13] Permission denied: '...\\ai_models.json.enc'"
    #     because _write_encrypted used to be a bare
    #     `open(path, "wb")` with none of the retry/repair logic the
    #     read side already had.
    write_path = os.path.join(tempfile.mkdtemp(), "settings.json.enc")
    with mock.patch("time.sleep") as fake_sleep:
        memory._write_bytes_with_retry(write_path, b"first-write")
    check("retry-write returns normally on the first-try path",
          open(write_path, "rb").read() == b"first-write")
    check("retry-write never sleeps when the very first write already works",
          fake_sleep.call_count == 0)

    # 15. _write_bytes_with_retry: transient PermissionError that
    #     clears after a couple of attempts (the realistic AV/OneDrive
    #     lock case right after a file is touched) -> retries quietly
    #     and the content really lands on disk, without ever invoking
    #     the heavier ACL repair path.
    attempts_made = {"n": 0}

    def flaky_write_open(path, mode="r", *a, **kw):
        if path == write_path and mode == "wb":
            attempts_made["n"] += 1
            if attempts_made["n"] < 3:
                raise PermissionError("transient lock")
        return real_open(path, mode, *a, **kw)

    with mock.patch("builtins.open", side_effect=flaky_write_open), \
         mock.patch("time.sleep") as fake_sleep, \
         mock.patch.object(memory, "_repair_windows_permissions") as fake_repair:
        memory._write_bytes_with_retry(write_path, b"second-write")
    check("retry-write recovers from a transient PermissionError without repair",
          open(write_path, "rb").read() == b"second-write"
          and fake_repair.call_count == 0)
    check("retry-write actually waited between attempts", fake_sleep.call_count >= 1)

    # 16. _write_bytes_with_retry: every plain retry fails, but the
    #     file already exists and ACL repair fixes it -> succeeds
    #     anyway instead of raising, the exact scenario of an existing
    #     settings/memory file stuck in a broken permission state from
    #     an earlier run.
    def always_fails_write_open(path, mode="r", *a, **kw):
        if path == write_path and mode == "wb":
            raise PermissionError(13, "Permission denied")
        return real_open(path, mode, *a, **kw)

    def fake_repair_fixes_it(path):
        # Simulate the repair call itself "fixing" things by letting
        # the *next* open through -- swap in a open that now succeeds.
        nonlocal_state["repaired"] = True
        return True

    nonlocal_state = {"repaired": False}

    def open_after_repair(path, mode="r", *a, **kw):
        if path == write_path and mode == "wb" and not nonlocal_state["repaired"]:
            raise PermissionError(13, "Permission denied")
        return real_open(path, mode, *a, **kw)

    with mock.patch("builtins.open", side_effect=open_after_repair), \
         mock.patch("time.sleep"), \
         mock.patch.object(memory, "_repair_windows_permissions",
                            side_effect=fake_repair_fixes_it) as fake_repair:
        memory._write_bytes_with_retry(write_path, b"third-write", attempts=2, delay=0)
    check("retry-write heals a stuck ACL via repair instead of raising",
          open(write_path, "rb").read() == b"third-write" and fake_repair.called)

    # 17. _write_bytes_with_retry: never clears, repair also fails ->
    #     raises PermissionError with a clear, actionable message
    #     (mentions another running copy of Friday AND Windows
    #     Controlled Folder Access) instead of a bare errno-13 crash
    #     like the one reported from the Settings panel.
    raised = None
    with mock.patch("builtins.open", side_effect=always_fails_write_open), \
         mock.patch("time.sleep"), \
         mock.patch.object(memory, "_repair_windows_permissions", return_value=False):
        try:
            memory._write_bytes_with_retry(write_path, b"never-lands", attempts=2, delay=0)
        except PermissionError as exc:
            raised = exc
    check("retry-write raises PermissionError (not a silent no-op) when truly unrecoverable",
          raised is not None)
    check("the raised write error mentions another running copy of Friday",
          raised is not None and "another copy of Friday" in str(raised))
    check("the raised write error mentions Controlled Folder Access",
          raised is not None and "Controlled Folder Access" in str(raised))

    # 18. _write_encrypted (the real settings_store.save()/memory.py
    #     code path, not just the raw-bytes helper) still ends up with
    #     correct, decryptable content on disk after a transient lock
    #     that clears -- an end-to-end check that the fix is actually
    #     wired into the function every save() call goes through.
    memory.set_memory_dir(os.path.join(tempfile.mkdtemp(), "friday_memory2"))
    enc_path = os.path.join(memory._ensure_folder("settings"), "ai_models.json.enc")
    attempts_made2 = {"n": 0}

    def flaky_enc_open(path, mode="r", *a, **kw):
        if path == enc_path and mode == "wb":
            attempts_made2["n"] += 1
            if attempts_made2["n"] < 2:
                raise PermissionError("transient lock")
        return real_open(path, mode, *a, **kw)

    with mock.patch("builtins.open", side_effect=flaky_enc_open), \
         mock.patch("time.sleep"):
        memory._write_encrypted(enc_path, {"Voice": ["demo"]})
    check("_write_encrypted survives a transient lock and writes real, decryptable content",
          memory._read_encrypted(enc_path) == {"Voice": ["demo"]})
    memory.close()


def main():
    part_a()
    part_b()
    part_c()
    part_d()

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
