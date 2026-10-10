"""
Tools available to the AI agent: web search, file access, and clock/calendar.

Each tool below is a plain Python function with type hints and a docstring.
Gemini's automatic function calling (google-genai) introspects these
directly — see GEMINI_TOOLS. Groq and Mistral need an explicit JSON schema
plus a manual tool-call loop instead, so the same functions are also
described as OpenAI-style schemas in TOOL_SCHEMAS, with call_tool() used to
dispatch a (name, arguments) pair from either of those two providers.

Deliberately NOT included: any destructive/irreversible action on files
outside the IDE's own workspace. Inside the IDE's own workspace, Friday
may delete files and folders that are clearly dead/leftover and not part
of its active work — mirroring the kind of routine cleanup a competent
collaborator does without a permission round-trip for every item — but
only through the required two-step analyze-then-delete flow (see
ide_analyze_file_for_deletion/ide_delete_file and
ide_analyze_folder_for_deletion/ide_delete_folder below), never
permanently (everything is moved to a recoverable trash folder), and
never on project infrastructure (.git, node_modules, a venv, build/cache
output) or the workspace root itself, which are always refused outright.
When the analysis step finds outside references or genuine ambiguity, or
the user would obviously want a say, Friday stops and asks rather than
guessing. Outside the IDE's own workspace, the agent can read, create,
and edit files/events, but never remove them — ask the user to do that
themselves.
"""

import datetime
import gc
import hashlib
import inspect
import json
import os
import socket
import queue
import sys
import tempfile
import threading
import time


# ---------------------------------------------------------------------------
# File access (read / create / edit / list) — full filesystem access, scoped
# only by whatever the OS user account running this app can already reach.
# ---------------------------------------------------------------------------

_MAX_READ_CHARS = 20_000  # keep replies (and TTS) from choking on huge files


def read_file(path: str) -> str:
    """Read and return the text content of a file on disk.

    Args:
        path: Absolute or relative filesystem path to the file to read.
    """
    path = os.path.expanduser(path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except IsADirectoryError:
        return f"Error: {path} is a directory, not a file."
    except Exception as exc:  # noqa: BLE001
        return f"Error reading {path}: {exc}"

    if len(content) > _MAX_READ_CHARS:
        remaining = len(content) - _MAX_READ_CHARS
        return content[:_MAX_READ_CHARS] + f"\n\n...[truncated, {remaining} more characters]"
    return content


def write_file(path: str, content: str) -> str:
    """Create a new file or overwrite an existing one with the given text content.

    Args:
        path: Absolute or relative filesystem path to write to. Parent
            directories are created automatically if they don't exist.
        content: The full text content to write to the file.
    """
    path = os.path.expanduser(path)
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} characters to {path}."
    except Exception as exc:  # noqa: BLE001
        return f"Error writing {path}: {exc}"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Edit an existing file by replacing the first occurrence of some exact text with new text.

    Args:
        path: Absolute or relative filesystem path to the file to edit.
        old_text: The exact text to search for in the file (only the
            first occurrence is replaced).
        new_text: The text to replace it with.
    """
    path = os.path.expanduser(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:  # noqa: BLE001
        return f"Error reading {path}: {exc}"

    if old_text not in content:
        return f"Error: the given old_text was not found in {path}. No changes made."

    content = content.replace(old_text, new_text, 1)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Edited {path} successfully."
    except Exception as exc:  # noqa: BLE001
        return f"Error writing {path}: {exc}"


def list_directory(path: str = ".") -> str:
    """List the files and subfolders inside a directory.

    Args:
        path: Absolute or relative filesystem path to the directory to
            list. Defaults to the current working directory.
    """
    path = os.path.expanduser(path)
    try:
        entries = sorted(os.listdir(path))
    except Exception as exc:  # noqa: BLE001
        return f"Error listing {path}: {exc}"

    if not entries:
        return f"{path} is empty."

    lines = []
    for name in entries:
        full = os.path.join(path, name)
        prefix = "[dir]  " if os.path.isdir(full) else "       "
        lines.append(prefix + name)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent Mode — Friday's own bundled IDE (ide/ide.py), hard-coded into Friday as
# one of its own windows rather than a separate app: opens, opens/creates
# folders, creates/writes/edits/renames/copies/moves files, searches the
# workspace, and runs/builds/stops tasks or arbitrary shell commands in its
# integrated terminal — all of it live, visible in its own Explorer/editor/
# terminal, the same as if a person were doing it by hand. Use the ide_*
# tools below when Agent Mode is (or should be) on; use read_file/
# write_file/edit_file above for everyday file tasks unrelated to a coding
# session.
#
# This is one process, one codebase: the IDE is literally a second Tk
# window built directly here, not a subprocess Friday happens to talk to over
# a socket (see IDEApp(agent_host=...) in ide/ide.py). agent_overlay.py
# pumps that window's Tk event loop from its own Qt main-thread timer, so
# quitting Friday (however it quits) takes the IDE down with it automatically
# — there is no second process left behind to orphan.
#
# Most of what's below calls straight into ide.py's WorkspaceFS (already
# thread-safe to call from any thread — its own UI refreshes marshal
# themselves onto Tk) with no extra plumbing. A handful of operations that
# construct/destroy Tk widgets or start a managed run (building the IDE
# itself, opening/closing it, run/build/stop) are routed through
# _run_on_main so they always land on the one thread Tk owns, whether
# they were called from Friday's own background tool-calling thread or not.
#
# Deleting individual files and whole folders inside the open workspace is
# exposed — see ide_analyze_file_for_deletion/ide_delete_file and
# ide_analyze_folder_for_deletion/ide_delete_folder further down — but only
# through their required analyze-then-delete flow, scoped to dead/unrelated
# content, and even then into a recoverable trash folder, never a permanent
# unlink. Project infrastructure (.git, node_modules, a venv, build/cache
# output) and the workspace root itself are always refused outright.
# ---------------------------------------------------------------------------

_IDE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ide")
if _IDE_DIR not in sys.path:
    sys.path.insert(0, _IDE_DIR)
import ide as _ide_module  # noqa: E402  (path must be set up first)
IDEApp = _ide_module.IDEApp

import app_panels as _app_panels_module  # noqa: E402

_IDE_HOME_DIR = os.path.join(os.path.expanduser("~"), "Friday-Agent-Workspace")

_ide_app = None             # the live IDEApp instance, or None when closed —
                            # cleared by IDEApp.destroy() itself calling
                            # into _AgentHost.on_ide_closed() below, so this
                            # is correct no matter how the window closed
                            # (agent_mode_off, the window's own close
                            # button, or Friday force-closing it on its own
                            # way out).
_ide_thread = None          # the one dedicated OS thread that ever runs a Tk
                            # mainloop() for this process, for its whole
                            # lifetime -- see _ensure_tk_worker()/
                            # _tk_worker_loop(). Stays set (and the thread
                            # stays alive, parked waiting for the next
                            # session) across repeated agent_mode_on()/
                            # agent_mode_off() cycles; only ever None before
                            # the first agent_mode_on() call. Deliberately
                            # NOT spawned fresh per session (as an earlier
                            # version of this did): a brand new OS thread
                            # building a brand new Tk() right after a
                            # previous one had been built-and-destroyed on a
                            # *different* thread reproduced a permanent
                            # hang in testing (a known, long-standing
                            # CPython/Tcl limitation -- see
                            # https://bugs.python.org/issue33412 -- where a
                            # cross-thread Tcl call can only be serviced by
                            # an interpreter whose event loop is actively
                            # running, and something about that hand-off
                            # breaks down across repeated thread churn even
                            # when each new mainloop() genuinely is up and
                            # running by the time the call is made). A
                            # single long-lived worker thread that just
                            # builds/tears down a new IDEApp per session,
                            # looping back to wait for the next one instead
                            # of exiting, sidesteps that entirely.
_tk_worker_queue = None      # queue.Queue() of (start_dir, ready_event, box)
                            # session requests for the worker thread above;
                            # created lazily by _ensure_tk_worker().
_main_thread_bridge = None  # set once the IDE is open; see _run_on_main.
_chat_handler = None        # set once by agent_overlay.py; see set_chat_handler
_circle_rect_provider = None  # set once by agent_overlay.py; see
                            # set_circle_rect_provider
_speak_label_handler = None  # set once by agent_overlay.py; see
                            # set_speak_label_handler
_ide_chat_notify_handler = None  # set once by ide.py's ChatSidePanel; see
                            # set_ide_chat_notify_handler/notify_ide_chat
_ide_build_status_handler = None  # set once by ide.py's ChatSidePanel; see
                            # set_ide_build_status_handler/report_ide_build_status


class _TkThreadBridge:
    """Marshals a call onto the dedicated thread running the IDE's Tk
    mainloop() and blocks the caller for the result. Built on Tk's own
    `.after(0, ...)` scheduling, which is safe to call from any thread —
    the same thread-safe hand-off ide.py's own chat panel already relies
    on (see ChatSidePanel._send's on_done) — so no extra locking of our
    own is needed beyond a plain threading.Event per call.

    Why the IDE gets a real dedicated thread (running an uninterrupted
    native Tk mainloop(), the same way any standalone Tkinter app runs)
    rather than being ticked via periodic .update() calls from a Qt
    timer on Friday's own main thread (the original Task 23 design): on
    real Windows, re-entering Tcl's native event dispatch from *inside*
    another toolkit's own already-running native event loop, on the
    very same OS thread, turned out to fatally corrupt CPython's thread
    state the moment any *other* Python thread was doing essentially
    anything at all — observed both with pyttsx3's SAPI5 driver pumping
    COM on its own thread, and completely independently with an AIWorker
    thread simply blocked in a plain SSL socket read. Giving Tk a fully
    separate thread, with its own native mainloop() as the only native
    loop that thread ever runs, removes that nested-native-loop pattern
    entirely -- the well-established, widely-used way Tkinter apps mix
    with background worker threads elsewhere, which is exactly what
    this now is: one GUI-owning thread per toolkit (Qt's main thread,
    Tk's dedicated thread), with plain thread-safe hand-offs between
    them instead of sharing one thread's native event dispatch.
    """

    def __init__(self, root):
        self._root = root

    def call(self, fn):
        box = {}
        done = threading.Event()

        def _run():
            try:
                box["result"] = fn()
            except Exception as exc:  # noqa: BLE001
                box["exc"] = exc
            finally:
                done.set()

        try:
            self._root.after(0, _run)
        except Exception as exc:  # noqa: BLE001
            # The Tk root is already torn down/tearing down.
            raise RuntimeError("the IDE isn't reachable anymore") from exc
        done.wait()
        if "exc" in box:
            raise box["exc"]
        return box.get("result")

    def post(self, fn):
        """Fire-and-forget sibling of call(): schedules fn() to run on
        the Tk thread and returns immediately, without waiting for it
        and without holding any reference to this bridge (or the
        IDEApp/root it wraps) beyond this one call.

        Used specifically for the close()/destroy() request itself (see
        agent_mode_off()), never for anything that needs a return
        value. call()'s done.wait() necessarily keeps this bridge --
        and so its self._root, the IDEApp instance -- referenced on the
        *calling* thread for the whole round trip, including however
        long destroy() itself takes to run on the Tk thread. In testing
        that window was occasionally just long enough for the calling
        thread to still be the one holding the last Python-level
        reference once the Tk thread's own post-mainloop cleanup (see
        _tk_main's finally block) had already freed everything else --
        and the resulting final deallocation of the IDEApp's Tcl
        interpreter happened on the wrong thread, which Tcl escalates
        to an unrecoverable process abort, not a catchable exception.
        Returning immediately here, instead of blocking, keeps that
        window down to this single, synchronous .after() registration
        call -- callers observe completion some other way instead (see
        agent_mode_off()'s own polling loop).
        """
        root = self._root
        try:
            root.after(0, fn)
        except Exception:  # noqa: BLE001
            pass  # the Tk root is already torn down/tearing down


def _post_on_main(fn):
    """Fire-and-forget sibling of _run_on_main(): see
    _TkThreadBridge.post()'s docstring for why this exists separately
    from _run_on_main instead of just not waiting for its result."""
    if _ide_thread is not None and threading.current_thread() is _ide_thread:
        fn()
        return
    bridge = _main_thread_bridge
    if bridge is not None:
        bridge.post(fn)
    elif threading.current_thread() is threading.main_thread():
        fn()


def set_chat_handler(handler):
    """Called once by agent_overlay.py: `handler(text, on_done)` runs
    `text` through Friday's normal AI brain — the exact same Gemini/Groq/
    Mistral pipeline a spoken command goes through — and calls
    on_done(ok, result_text) once finished, from whatever thread that
    happens on. Lets the IDE's embedded "Friday AI Chat" panel ask Friday
    anything without the IDE needing to know how Friday's brain works."""
    global _chat_handler
    _chat_handler = handler


def set_ide_chat_notify_handler(handler):
    """Called once by ide.py's ChatSidePanel, the opposite direction of
    set_chat_handler above: `handler(text, options=None)` appends `text`
    as a new, unprompted "friday" bubble in the IDE's embedded chat
    panel -- for a message that isn't a reply to anything the user just
    typed here, e.g. the 2-minute unanswered-pause autonomy rule's
    follow-up once Friday decides to proceed without a reply (see
    agent_overlay.py's _ide_chat_auto_continue/notify_ide_chat below).
    `options`, when not None, is a short list of option labels to render
    as clickable buttons under that bubble (Task 65's Permission
    mechanism). `handler` is responsible for its own thread marshaling
    onto Tk's thread -- see ChatSidePanel.register for the actual
    implementation.
    """
    global _ide_chat_notify_handler
    _ide_chat_notify_handler = handler


def notify_ide_chat(text, options=None):
    """Best-effort: posts `text` as a new Friday-initiated bubble in the
    IDE's embedded chat panel, if one is open and has registered a
    handler (see set_ide_chat_notify_handler) -- e.g. the 2-minute
    unanswered-pause autonomy rule's follow-up, which isn't triggered by
    anything the user just typed. `options`, when given, is a short list
    of option labels (Task 65's Permission mechanism) rendered as
    clickable buttons under this bubble, same as a normal in-turn
    decision pause -- lets a decision posed *after* an auto-continue
    still offer concrete choices, not just a bare question. Silently
    does nothing if no panel is listening right now. Never raises --
    same graceful-degradation spirit as speak_label above."""
    if _ide_chat_notify_handler is None:
        return
    try:
        if _accepts_options_arg(_ide_chat_notify_handler):
            _ide_chat_notify_handler(text, options)
        else:
            # Backward-compatible with any handler registered before the
            # `options` parameter existed (single-arg signature) --
            # checked up front by inspecting the signature, not a bare
            # try/except TypeError around the call itself, which would
            # risk silently double-invoking (and double-acting on) a
            # handler whose *body* happens to raise its own unrelated
            # TypeError rather than one that just doesn't accept a 2nd
            # argument.
            _ide_chat_notify_handler(text)
    except Exception:  # noqa: BLE001
        pass


def _accepts_options_arg(fn):
    """True if `fn` can be called with a 2nd positional argument -- see
    agent_overlay._accepts_options_arg for the identical reasoning
    (duplicated rather than imported across the two modules to avoid a
    circular import between them)."""
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
    return len(positional) >= 2


def set_ide_build_status_handler(handler):
    """Called once by ide.py's ChatSidePanel, the build-status sibling of
    set_ide_chat_notify_handler above: `handler(phase, status, detail)`
    upserts one row of the chat panel's persistent build-status
    checklist (see ChatSidePanel.update_build_status) -- phase is
    "frontend"/"backend"/"storage", status is "in_progress"/"done"/
    "blocked", detail is a short free-text note. `handler` is
    responsible for its own thread marshaling onto Tk's thread, same as
    the chat-notify handler."""
    global _ide_build_status_handler
    _ide_build_status_handler = handler


def report_ide_build_status(phase, status, detail=""):
    """Best-effort: tells the IDE's embedded chat panel's build-status
    checklist to update `phase` to `status` (with optional `detail`), if
    a panel is open and has registered a handler (see
    set_ide_build_status_handler). Silently does nothing if no panel is
    listening right now -- same graceful-degradation spirit as
    notify_ide_chat. Never raises."""
    if _ide_build_status_handler is None:
        return
    try:
        _ide_build_status_handler(phase, status, detail)
    except Exception:  # noqa: BLE001
        pass


def set_circle_rect_provider(fn):
    """Called once by agent_overlay.py: `fn()` returns the floating
    circle's current on-screen (center_x, center_y, diameter), in
    physical screen pixels, or None. Lets the IDE's open/close "pop"
    animation (ide.py's _play_open_animation/_play_close_animation) know
    where to visually grow out of / shrink back into, without the IDE
    needing to import agent_overlay.py (which would be a circular
    import) or know anything about Qt."""
    global _circle_rect_provider
    _circle_rect_provider = fn


def set_speak_label_handler(fn):
    """Called once by agent_overlay.py: `fn(text)` speaks `text` aloud
    through Friday's own configured voice, best-effort (silently skipped
    if Friday is already mid-conversation or speech is unavailable).
    Lets the IDE's minimized-panel "pill" near the circle announce which
    panel it represents by name when hovered, without the IDE needing to
    import agent_overlay.py or know anything about Qt/TTS."""
    global _speak_label_handler
    _speak_label_handler = fn



def _run_on_main(fn):
    """Run fn() on the thread that owns the IDE's Tk root and block for
    the result. A plain direct call when already on that thread, or
    when no IDE thread has been started yet and we're on the process's
    own main thread (true for simple scripts/tests that construct an
    IDEApp directly without going through agent_mode_on() at all, e.g.
    ide/tests/*); otherwise marshaled through the per-session
    _TkThreadBridge agent_mode_on() set up."""
    if _ide_thread is not None and threading.current_thread() is _ide_thread:
        return fn()
    if _main_thread_bridge is None:
        if threading.current_thread() is threading.main_thread():
            return fn()
        raise RuntimeError(
            "the IDE can't be reached from this thread yet — no IDE "
            "thread has been registered")
    return _main_thread_bridge.call(fn)



class _AgentHost:
    """The small adapter object IDEApp(agent_host=...) gets. Everything
    the IDE needs from "Friday at large" — without importing agent_overlay.py
    and creating a circular import — goes through this."""

    def ask(self, text, on_done):
        if _chat_handler is None:
            on_done(False, "Friday's chat handler isn't wired up this run.")
            return
        _chat_handler(text, on_done)

    def on_ide_closed(self):
        global _ide_app, _ide_opened_at
        _ide_app = None
        _ide_opened_at = None
        _release_panel_slot("ide")
        # If the IDE was minimized (a pill showing under the circle)
        # at the moment it got closed, its slot in the *other* shared
        # ledger -- the minimized-pill stack -- also needs releasing,
        # with everything below it reflowed up a slot. Without this, an
        # IDE closed straight from its pill (rather than restored
        # first) left a stale "ide" entry in the shared pill stack
        # forever, the same bug _close_one had for app_panels.py's own
        # panels -- see its comment for the full story.
        try:
            reflow = _stack_remove_and_reflow("ide")
            for key, idx in reflow:
                _AGENT_HOST.reposition_pill(key, idx)
        except Exception:  # noqa: BLE001
            pass

    def get_circle_rect(self):
        """Best-effort (center_x, center_y, diameter) of Friday's floating
        circle right now, in physical screen pixels, or None if no
        provider is registered (e.g. ide.py was constructed directly by
        a test/script, with no agent_overlay.py circle running at all)
        or the query fails for any reason. Purely cosmetic -- see
        set_circle_rect_provider's docstring."""
        if _circle_rect_provider is None:
            return None
        try:
            return _circle_rect_provider()
        except Exception:  # noqa: BLE001
            return None

    def speak_label(self, text):
        """Best-effort: speaks `text` aloud through Friday's own voice, if
        a handler is registered and Friday isn't already busy with
        something else. Silently does nothing otherwise -- see
        set_speak_label_handler's docstring. Never raises."""
        if _speak_label_handler is None:
            return
        try:
            _speak_label_handler(text)
        except Exception:  # noqa: BLE001
            pass

    def register_ide_chat_notify(self, handler):
        """Called once by ide.py's ChatSidePanel (the IDE never imports
        agent_tools directly -- everything it needs from "Friday at
        large" goes through this host object, same as every other
        method here). Forwards straight to
        agent_tools.set_ide_chat_notify_handler -- see that function's
        docstring for what `handler` is used for."""
        set_ide_chat_notify_handler(handler)

    def register_ide_build_status(self, handler):
        """Called once by ide.py's ChatSidePanel, the build-status
        sibling of register_ide_chat_notify above. Forwards straight to
        agent_tools.set_ide_build_status_handler -- see that function's
        docstring for what `handler` is used for."""
        set_ide_build_status_handler(handler)

    # ---- unified minimized-pill stacking, shared by the IDE (ide.py)
    # and every app_panels.py panel (Chrome/Notepad/Calculator/Settings) ----
    # Both subsystems get this exact same _AgentHost instance already
    # (see _panel_manager/IDEApp construction below), so it's the one
    # place both sides can coordinate a single shared vertical stack of
    # pills under the circle without either module importing the other.
    def get_pill_slot(self, key):
        """0-based slot index `key` ("ide", or an app_panels.py panel
        key) should use in the shared minimized-pill stack, adding it to
        the stack if it isn't tracked yet. Slot 0 is the pill directly
        under the circle; each following slot stacks one pill further
        down, in the order panels were minimized."""
        return _stack_add_and_index(key)

    def release_pill_slot(self, key):
        """Removes `key` from the shared minimized stack (call this once
        its pill is actually gone, e.g. right after destroying it in
        restore_from_pill/_restore_one) and returns
        [(key, new_slot_index), ...] for every other still-minimized
        panel that needs to shift up a slot as a result, so the stack
        never has a gap in the middle of it."""
        return _stack_remove_and_reflow(key)

    def reposition_pill(self, key, slot_index):
        """Dispatches a live reposition of `key`'s already-shown pill to
        whichever subsystem actually owns it -- "ide" is handled
        directly against the live IDEApp instance; anything else is
        routed through the shared AppPanelManager. Used to carry out the
        reflow release_pill_slot() reports. Best-effort, never raises."""
        if key == "ide":
            app = _ide_app
            if app is not None:
                try:
                    _run_on_main(lambda: app.reposition_pill_to_slot(slot_index))
                except Exception:  # noqa: BLE001
                    pass
        else:
            try:
                _panel_manager.reposition_pill(key, slot_index)
            except Exception:  # noqa: BLE001
                pass

    # ---- unified single-active-panel placement, shared the same way
    # the pill stack above is -- see the module-level comment just
    # below _AGENT_HOST for the full design ----
    def get_panel_placement(self, key):
        """Decides (and, for whichever other panel was previously
        active, actually carries out minimizing it) exactly where `key`
        should land for its very first on-screen appearance -- a fresh
        open, or a restore from minimized. Returns (bounds, is_maximized,
        note); see _place_new_or_restored_panel's own docstring for the
        full contract."""
        return _place_new_or_restored_panel(key)

    def release_panel_slot(self, key):
        """Releases `key`'s claim on being the one single active/
        maximized panel (call once it's no longer visible, minimized or
        closed) -- a no-op unless `key` actually was the active panel
        right now."""
        _release_panel_slot(key)


_AGENT_HOST = _AgentHost()

# Friday's tracked real-app panels (Chrome/Notepad/Calculator/Settings, so far) —
# see app_panels.py's module docstring for why this deliberately runs on
# its own dedicated Tk thread instead of reusing the coding IDE's one.
# Reuses the exact same _AGENT_HOST the IDE's own pill already does for
# the circle's position and hover-to-speak, since neither of those is
# actually IDE-specific.
_panel_manager = _app_panels_module.AppPanelManager(agent_host=_AGENT_HOST)

# ---------------------------------------------------------------------
# Unified panel organization: every panel Friday owns -- the IDE and
# every app_panels.py panel -- is treated the same way (per explicit
# user direction), sharing one single on-screen rule: exactly ONE panel
# is ever visible on screen at a time -- "the active panel" -- full
# screen, sized/positioned to Friday's own IDE-style reference bounds
# (see _ide_reference_bounds -- "the IDE's panel size" means this
# fixed, nameable concept, whether or not the IDE itself actually
# happens to be open right now). Every other panel Friday has open is
# minimized, stacked in a single ordered pill under the circle.
#
#   - Opening a brand new panel, or restoring an already-open but
#     currently-minimized one, always makes it the new active panel --
#     full screen, front and center -- and minimizes whatever was
#     previously the active one (if anything) to a pill, automatically,
#     to make room. There's no cap to worry about any more (there used
#     to be one, back when several smaller panels could share the
#     screen at once side by side) -- there's only ever at most one
#     panel visible regardless of how many are open in total.
#   - Explicitly maximizing a panel that's currently minimized does the
#     exact same thing restoring it would: promotes it to active,
#     minimizing whatever was active before. maximize_app and
#     restore_app are deliberately two names for the same single
#     underlying action now, kept as separate tools only because
#     they're both already part of Friday's existing conversational
#     vocabulary ("restore notepad" / "maximize notepad" should both
#     just work).
#
# All of this lives here, rather than inside ide.py or app_panels.py
# themselves, since this is the one module that already knows about
# both subsystems; neither of them needs to know the other exists.
# ---------------------------------------------------------------------
_ide_opened_at = None        # time.time() of the IDE's current open, or None
_maximized_panel_key = None  # "ide", an app_panels.py key, or None -- the one
                              # single panel currently visible on screen, if any
_MINIMIZED_STACK = []        # ordered keys, closest-to-circle (earliest minimized) first


def is_panel_minimized(key):
    """True if `key` ("ide", or an app_panels.py panel key) is currently
    showing as a pill under the circle rather than its real window.
    Used by agent_overlay.py to decide whether a status change (paused
    for a decision, finished, hit an error) is worth proactively calling
    out through the circle's own voice at all -- if the panel's real
    window is already on screen, there's no point narrating something
    the user can already just look at."""
    return key in _MINIMIZED_STACK


def report_panel_status(key, status):
    """Best-effort: recolors `key`'s minimized-pill outline, if it's
    currently minimized, to reflect what it's doing right now --
    "waiting" (paused, needs a decision -- orange), "done" (finished a
    task while minimized -- green), "error" (hit a problem it can't get
    past on its own -- red), or "normal" (nothing to report, the plain
    default outline). The underlying status is remembered on the owning
    panel itself even when nothing is currently minimized to show it on
    (see IDEApp._panel_status / AppPanelManager's own per-panel record),
    so a panel minimized *after* the status already changed still shows
    the right color immediately, instead of starting blank.

    "ide" is handled directly against the live IDEApp instance, the same
    dispatch pattern _AgentHost.reposition_pill already uses; anything
    else is routed through the shared AppPanelManager (no app_panels.py-
    managed panel actually drives this yet -- Notepad/Calculator/Chrome
    have no "paused/working/erroring" concept of their own today -- but
    the plumbing is generic and ready for a future one, e.g. a
    long-running video-generation panel, built the same way the IDE's
    own chat-driven tasks already are). Never raises.
    """
    if key == "ide":
        app = _ide_app
        if app is not None:
            try:
                _run_on_main(lambda: app.set_panel_status(status))
            except Exception:  # noqa: BLE001
                pass
    else:
        try:
            _panel_manager.set_status(key, status)
        except Exception:  # noqa: BLE001
            pass


def has_internet_connectivity(timeout=2.0):
    """True if a plain TCP connection to a well-known, highly-available
    public DNS resolver (Cloudflare's 1.1.1.1:53, falling back to
    Google's 8.8.8.8:53) succeeds within `timeout` seconds. Deliberately
    not an HTTP/HTTPS request to any AI provider's own domain -- this is
    meant to answer "is there a working internet connection at all right
    now", not "is Gemini/Groq/Mistral specifically reachable", so a
    provider-specific outage never gets mistaken for a local
    connectivity problem (see agent_overlay.py's
    _looks_like_connectivity_error/_ConnectivityRetryTracker, which use
    this exact function to decide when to retry a connectivity-failed
    request automatically). A bare TCP handshake on the DNS port is used
    rather than an actual DNS query -- cheap, fast, and needs no extra
    dependency -- since merely completing the handshake already proves a
    real route to the open internet exists. Never raises -- False on any
    failure (DNS resolution itself failing, connection refused, timeout,
    or anything else).
    """
    for host in (("1.1.1.1", 53), ("8.8.8.8", 53)):
        try:
            with socket.create_connection(host, timeout=timeout):
                return True
        except OSError:
            continue
    return False


def _stack_add_and_index(key):
    if key not in _MINIMIZED_STACK:
        _MINIMIZED_STACK.append(key)
    return _MINIMIZED_STACK.index(key)


def _stack_remove_and_reflow(key):
    if key in _MINIMIZED_STACK:
        _MINIMIZED_STACK.remove(key)
    return [(k, i) for i, k in enumerate(_MINIMIZED_STACK)]


def _label_for(key):
    if key == "ide":
        return "the IDE"
    rec = _panel_manager._panels.get(key)
    return rec["label"] if rec else key


def _ide_reference_bounds():
    """(x, y, w, h) -- Friday's own agent-controlled IDE geometry
    formula: the one shared "maximized/full screen" reference size and
    position every panel (the IDE included) fills while it's the
    single active one on screen. Computed fresh against the current
    screen size every single time, independent of whatever size the
    IDE's own window happens to be sitting at right this moment (it
    might currently be minimized to a pill, if something else is the
    active panel) and independent of whether the IDE is even open at
    all right now."""
    sw, sh = _panel_manager.screen_size()
    return _ide_module.compute_agent_controlled_bounds(sw, sh)


def _minimize_key_to_pill(key):
    """Minimizes `key` (the IDE or an app_panels.py panel) down to its
    pill under the circle -- used whenever some other panel is about to
    become the new single active/visible one, same mechanics
    minimize_app's own single-panel path uses."""
    if key == "ide":
        _minimize_ide_panel()
    else:
        _panel_manager.minimize(key)


def _place_new_or_restored_panel(key):
    """Call right before `key` (the IDE, or an app_panels.py key) is
    about to become visible -- a fresh open(), or a restore() from
    minimized. Friday only ever shows one single panel on screen at a
    time: `key` always becomes that one panel, full screen, at Friday's
    own IDE-style reference bounds -- and whatever panel was
    previously the active one (if any, and if it isn't `key` itself) is
    minimized to a pill under the circle first, automatically, to make
    room.

    Returns (bounds, is_maximized, note) -- `is_maximized` is always
    True (there's no other state left to land in any more -- a panel is
    either the one active/maximized one, or it's minimized); `note`
    explains which other panel, if any, just got minimized to make room
    for this one. `bounds` is _ide_reference_bounds() in every case
    except one: the IDE being opened fresh (not restored -- `_ide_app`
    doesn't exist yet). That one case deliberately returns None instead
    -- see the comment inline below for why skipping the call actually
    matters there, not just style.
    """
    global _maximized_panel_key
    prev = _maximized_panel_key
    note = ""
    if prev is not None and prev != key:
        note = f" ({_label_for(prev)} was minimized to make room for it.)"
        _minimize_key_to_pill(prev)
    _maximized_panel_key = key
    _apply_active_panel_flag(key, True)
    if key == "ide" and _ide_app is None:
        # The IDE doesn't exist yet (a fresh open, not a restore of an
        # already-running one) -- deliberately skip calling
        # _ide_reference_bounds() here. That call goes through
        # _panel_manager.screen_size(), which lazily spins up the panel
        # manager's own hidden background Tk host the very first time
        # anything needs it -- and whichever Tk root gets created
        # *first* in the whole process silently claims tkinter's global
        # default-root slot. ide.py's own icon-drawing helpers
        # (build_icon/build_badge_icon) are called with the bare
        # tkinter module rather than an explicit master, so they
        # implicitly rely on that slot pointing at *this* IDE's own
        # interpreter once it exists. If the panel manager's host won
        # that race instead -- which it would, racing against the IDE's
        # own not-yet-created Tk root -- every icon the IDE ever drew
        # would silently get built in the wrong interpreter, surfacing
        # later as a confusing `image "pyimageN" doesn't exist` TclError
        # the moment one was actually used (e.g. the first time the
        # Explorer tree populates). Returning None instead costs
        # nothing: ide.py computes this exact same formula itself,
        # just safely after its own Tk root already exists and has
        # already claimed the default-root slot for real.
        return None, True, note
    return _ide_reference_bounds(), True, note


def _apply_active_panel_flag(key, active):
    """Best-effort: tells `key`'s own panel object (the IDE, or an
    app_panels.py panel's frame) whether it's currently Friday's single
    active/maximized panel right now -- the one in the unified
    placement system's one center/maximized slot -- so it can show
    (active) or stop showing (not active) the pulsing violet
    active-panel border (see ide.py's _ActiveGlowAnimator, and
    IDEApp/EmbeddedAppPanel/CustomNotepadPanel's own set_active_panel
    methods). Purely cosmetic, never raises. A no-op if `key` is None
    or isn't actually open right now (e.g. it was just closed outright
    rather than minimized)."""
    if key is None:
        return
    try:
        if key == "ide":
            if _ide_app is not None:
                _run_on_main(lambda: _ide_app.set_active_panel(active))
        else:
            rec = _panel_manager._panels.get(key)
            frame = rec.get("frame") if rec is not None else None
            if frame is not None:
                _panel_manager._bridge.call(lambda: frame.set_active_panel(active))
    except Exception:  # noqa: BLE001
        pass


def _release_panel_slot(key):
    """Reverse of _place_new_or_restored_panel's bookkeeping -- call
    whenever `key` stops being visible (minimized or closed). A no-op
    unless `key` was actually the one single active/maximized panel
    right now (there's nothing else to release -- anything that isn't
    the active panel is already minimized). The maximized/center slot,
    once vacated, is simply left empty -- nothing auto-promotes into
    it; that only ever happens via an explicit later open()/restore()/
    maximize_app() call."""
    global _maximized_panel_key
    if _maximized_panel_key == key:
        _maximized_panel_key = None
        _apply_active_panel_flag(key, False)


def is_agent_mode_on() -> bool:
    """True if Friday's IDE is currently open."""
    return _ide_app is not None


def get_ide_pid():
    """The running IDE's process id, or None if it isn't open. The IDE is
    one of Friday's own windows now (not a separate process), so while it's
    open this is simply Friday's own pid -- kept for anything that still
    wants a liveness-by-pid signal."""
    return os.getpid() if is_agent_mode_on() else None


def _resolve_folder_hint(hint: str) -> str:
    """Turn a spoken/typed folder reference into a real absolute path.

    Tries the hint as a literal path first (expanding ~ and resolving
    relative paths), then falls back to a shallow, exact-name search of a
    handful of common top-level locations (home, Desktop, Documents,
    Downloads, and the Friday agent workspace) — not a full-disk crawl.
    """
    hint = hint.strip().strip('"').strip("'")
    literal = os.path.abspath(os.path.expanduser(hint))
    if os.path.isdir(literal):
        return literal

    home = os.path.expanduser("~")
    search_roots = [
        home,
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
        _IDE_HOME_DIR,
    ]
    target_name = os.path.basename(hint.rstrip("/\\")).lower()
    matches = []
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        try:
            for entry in os.scandir(root):
                if entry.is_dir() and entry.name.lower() == target_name:
                    matches.append(os.path.abspath(entry.path))
        except OSError:
            continue

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise LookupError(
            "found more than one folder named '%s': %s — please give the "
            "full path instead." % (target_name, "; ".join(matches)))
    raise FileNotFoundError(
        f"couldn't find a folder named '{hint}' in your home, Desktop, "
        f"Documents, Downloads, or Friday-Agent-Workspace folders. Try giving "
        f"the full path instead.")


def _tk_worker_loop():
    """Runs for the rest of the process's life on its own dedicated OS
    thread (see the long comment on _ide_thread above for why this is
    one persistent thread rather than a fresh one per session): waits
    for the next (start_dir, ready, box) session request, builds an
    IDEApp and runs its mainloop() to completion, cleans up, then loops
    back to wait for the next one.
    """
    global _ide_app, _main_thread_bridge
    while True:
        start_dir, initial_bounds, ready, box = _tk_worker_queue.get()
        try:
            app = IDEApp(start_dir, agent_controlled=True, agent_host=_AGENT_HOST,
                          initial_bounds=initial_bounds)
        except Exception as exc:  # noqa: BLE001
            box["exc"] = exc
            ready.set()
            continue
        _ide_app = app
        _main_thread_bridge = _TkThreadBridge(app)
        # _place_new_or_restored_panel("ide") (called by agent_mode_on()
        # a moment ago, back on the *caller's* thread) already decided
        # whether this IDE session is the one Friday's active/maximized
        # panel right now (_maximized_panel_key) and tried to flag it
        # as such then and there -- but `app` (and so _ide_app) didn't
        # exist yet at that exact moment, so that attempt was
        # necessarily a no-op. This is the first point `app` actually
        # exists, already on its own Tk thread, so apply it now instead.
        if _maximized_panel_key == "ide":
            try:
                app.set_active_panel(True)
            except Exception:  # noqa: BLE001
                pass
        # Signal "ready" from *inside* the event loop itself (via
        # .after(0, ...), fired on mainloop()'s very first pass) rather
        # than right before calling mainloop() below -- so whichever
        # thread called agent_mode_on() can't possibly race ahead and
        # try to post a cross-thread call (e.g. an immediate
        # agent_mode_off()) at a moment when this thread has a live Tk
        # interpreter but isn't actually pumping its event queue yet.
        app.after(0, ready.set)
        try:
            app.mainloop()
        finally:
            # mainloop() only returns once the root's been destroyed
            # (agent_mode_off(), the window's own close button, or Friday
            # force-closing it on its way out). _AgentHost.on_ide_closed()
            # normally already cleared _ide_app by then; this is just a
            # belt-and-braces backstop, same spirit as the old code's.
            if _ide_app is app:
                _ide_app = None
            _main_thread_bridge = None

            # A destroyed Tkinter widget tree is riddled with reference
            # cycles (parent<->child back-references, bound methods
            # stashed as menu/button commands, etc) that plain
            # refcounting can never free on its own -- only a cyclic gc
            # pass can. If one of those PhotoImage/widget objects is
            # instead left to whenever Python's cyclic collector
            # *happens* to run next (e.g. during full interpreter
            # shutdown, triggered from Friday's own main thread), its
            # finalizer tries to call back into Tcl from the wrong
            # thread -- which doesn't raise a catchable Python
            # exception, it's a hard Tcl-level panic that aborts the
            # whole process. Dropping our own last reference and
            # sweeping for cycles right here, still on this thread,
            # while it's still around to safely finalize anything Tcl-
            # owned, avoids that entirely. (IDEApp.destroy() itself
            # also explicitly empties its own PhotoImage caches before
            # any of this, for the same reason -- see ide.py's
            # _drop_image_caches(); this is the backstop for anything
            # not covered by that.)
            del app
            gc.collect()


_tk_worker_start_lock = threading.Lock()


def _ensure_tk_worker():
    """Starts the one persistent Tk worker thread, the first time it's
    needed. Safe to call on every agent_mode_on() -- a no-op once it's
    already running."""
    global _ide_thread, _tk_worker_queue
    with _tk_worker_start_lock:
        if _ide_thread is not None:
            return
        _tk_worker_queue = queue.Queue()
        thread = threading.Thread(
            target=_tk_worker_loop, name="Friday-IDE-Tk", daemon=True)
        thread.start()
        _ide_thread = thread


def agent_mode_on(folder: str = "") -> str:
    """Turn on Agent Mode: opens the bundled IDE so you can see code being written live, ready for real coding work.

    Call this when the user asks to start coding, write a program, build
    a project, or explicitly says something like "turn on agent mode" or
    "open the IDE". If a folder isn't given, the IDE opens empty — you can
    still create files immediately (a fresh workspace folder is set up
    automatically the first time you write something), or the user can ask
    to open a specific existing folder afterwards.

    Args:
        folder: Optional name or path of an existing folder to open right
            away instead of starting empty (e.g. "my-project" or
            "C:/Users/me/Documents/my-project").
    """
    if is_agent_mode_on():
        if folder:
            return ide_open_folder(folder)
        return "Agent Mode is already on — the IDE is already open."

    start_dir = None
    if folder:
        try:
            start_dir = _resolve_folder_hint(folder)
        except (FileNotFoundError, LookupError) as exc:
            return f"Couldn't turn on Agent Mode: {exc}"
    if start_dir is None:
        start_dir = tempfile.mkdtemp(prefix="friday-empty-")

    # Decide (and, for whatever panel was previously active, actually
    # carry out minimizing it to make room) exactly where the IDE
    # should land *before* it actually opens -- always Friday's one
    # single active/maximized slot, full screen -- see
    # _place_new_or_restored_panel's own docstring.
    initial_bounds, _is_maximized, cap_note = _place_new_or_restored_panel("ide")

    _ensure_tk_worker()
    ready = threading.Event()
    box = {}
    _tk_worker_queue.put((start_dir, initial_bounds, ready, box))
    ready.wait()

    if "exc" in box:
        return f"Couldn't turn on Agent Mode: {box['exc']}"

    global _ide_opened_at
    _ide_opened_at = time.time()

    if folder:
        return f"Agent Mode is on. Opened '{os.path.basename(start_dir)}' in the IDE.{cap_note}"
    return f"Agent Mode is on. The IDE is open and empty — tell me what to build.{cap_note}"


_PANEL_NAMES_FOR_IDE = ("ide", "the ide", "code editor", "coding", "code")


def _minimize_ide_panel():
    if not is_agent_mode_on():
        return "The IDE isn't open right now."
    try:
        already = _run_on_main(lambda: getattr(_ide_app, "_pill", None) is not None)
    except Exception:  # noqa: BLE001
        already = False
    if already:
        return "The IDE is already minimized."
    _release_panel_slot("ide")
    # Claim "ide"'s spot in the shared pill stack synchronously, right
    # now, rather than letting _show_pill() claim it later once the
    # IDE's shrink-to-circle animation finishes. The IDE's own minimize
    # is animated (hundreds of ms), while app_panels.py's panels
    # minimize instantly with no animation at all -- so on a combined
    # "minimize everything" pass that asks for the IDE first and then
    # the app panels, the app panels' synchronous _stack_add_and_index()
    # calls would otherwise race ahead and claim slots 0/1 before the
    # IDE's own (correctly first-requested) slot claim lands, leaving
    # the IDE's pill stacked *last* instead of closest to the circle.
    # _stack_add_and_index() is idempotent on an already-claimed key, so
    # _show_pill()'s own later call just reuses this same reserved slot.
    try:
        _AGENT_HOST.get_pill_slot("ide")
    except Exception:  # noqa: BLE001
        pass
    _run_on_main(lambda: _ide_app.minimize_to_pill())
    # minimize_to_pill() only *starts* its ~260ms shrink-to-circle
    # animation and returns immediately -- the actual pill widget (and
    # self._pill being set) only shows up once that animation's final
    # .after() tick runs, well after this call already returned. Wait
    # (briefly, bounded) for that to actually happen before reporting
    # success, so by the time this returns the IDE is genuinely,
    # verifiably minimized rather than merely "about to be" -- without
    # this, a restore_app("ide")/("all") landing in that gap would see
    # self._pill still None, conclude "the IDE isn't minimized" and
    # skip releasing the slot reserved just above, leaking a stale
    # entry into the shared pill stack forever (the same class of bug
    # _close_one/on_ide_closed had, see their own comments).
    deadline = time.time() + 1.0
    while time.time() < deadline:
        try:
            if _run_on_main(lambda: getattr(_ide_app, "_pill", None) is not None):
                break
        except Exception:  # noqa: BLE001
            break
        time.sleep(0.02)
    return "Minimized the IDE under the circle."


def _restore_ide_panel(assign_slot=True):
    if not is_agent_mode_on():
        return "The IDE isn't open right now."
    try:
        minimized = _run_on_main(lambda: getattr(_ide_app, "_pill", None) is not None)
    except Exception:  # noqa: BLE001
        minimized = False
    if not minimized:
        return "The IDE isn't minimized."
    note = ""
    if assign_slot:
        # Decides where the IDE lands this time (always the one single
        # active/maximized slot now, minimizing whoever else was active
        # to make room -- see _place_new_or_restored_panel) and
        # overrides the pop-out animation's own remembered pre-minimize
        # geometry with it, so the IDE eases straight to its *new* slot
        # in one motion instead of animating to its old spot and then
        # snapping again.
        bounds, _is_maximized, note = _place_new_or_restored_panel("ide")
        if bounds is not None:
            try:
                _run_on_main(lambda: setattr(_ide_app, "_pre_minimize_geom", bounds))
            except Exception:  # noqa: BLE001
                pass
    _run_on_main(lambda: _ide_app.restore_from_pill())
    return f"Restored the IDE.{note}"


def open_app(name: str, url: str = "", content: str = "") -> str:
    """Opens a real native desktop application — Chrome, Notepad,
    Calculator, or Settings so far — as one of Friday's own tracked
    panels, exactly the way opening the IDE already is: Friday launches
    it and remembers it as his (ide_list_open_tabs/ide_close_tab are a
    different, narrower thing — those are for tabs *inside* the IDE's
    own code editor, not top-level apps like this).

    Notepad is Friday's own fully built-in text editor — not a real
    notepad.exe at all. After the old approach (reparenting the real
    Windows Notepad's own window into a Friday panel via SetParent)
    turned out to be fragile across several real-Windows bugs, it was
    replaced outright with a small native editor Friday draws himself:
    tabs, a Bold/Italic/heading/bullet-list formatting toolbar (plain
    Markdown syntax, so it always saves as an ordinary portable .txt
    file), and a status bar. It opens instantly (no external process to
    launch or wait on), full screen, as Friday's single active panel
    (see below). New content isn't auto-saved — say where to save it afterwards
    (e.g. "save that as notes.txt on my Desktop" → save_app_file), or
    the user can use File > Save in the panel themselves. type_in_app
    and save_app_file both work directly against this same panel.

    Settings is also Friday's own fully built-in panel (same mechanism
    as Notepad, no real OS process at all) — it lists every AI model/API
    key Friday knows about, grouped by faculty (Thinking, Review,
    Coding, Image Generation, Audio Generation, Video Generation,
    Research, Embedding, Text Generation, Transcription), with keys
    shown masked and a real, live connectivity check (green check / red
    x) per model, plus a way to add a brand-new custom provider. Call
    this for "open settings"/"open the settings panel"/"show me the AI
    model settings"/"I want to check my API keys" or anything else about
    managing Friday's AI providers or their keys — there is nothing to
    configure about this one beyond opening it; it has its own in-panel
    Add/Edit/Remove/Check controls once it's open.

    Calculator is actually embedded inside a small, Friday-drawn panel
    frame — the real app's window gets reparented into it (Windows
    only), so it visually lives inside Friday's own panel rather than
    floating around as an independent window. Minimizing an embedded
    panel hides that whole frame (and the app inside it) and shows the
    usual pill under the circle. Finding the just-launched app's real window is robust
    against modern Windows launching Calculator through a stub/App-
    Execution-Alias whose own process id doesn't match the real
    window's (a documented Windows 11 quirk) — it's found by comparing
    against a before-launch window snapshot and matching by title
    instead of assuming the pid lines up. If embedding still isn't
    possible for some reason (not on Windows, the window can't be found
    at all, or the embed call itself fails — the newer UWP-hosted
    Calculator on some Windows 10/11 builds is a known case that can
    refuse classic reparenting), it quietly falls back to treating that
    app like a normal separate window instead, same as Chrome — and
    list_open_apps says plainly why, instead of failing silently.

    Chrome is deliberately never embedded, by design — real window
    reparenting is a well-known rough edge for apps doing their own
    GPU-accelerated compositing, so it opens as its own real, separate
    window instead, still trackable/minimizable/closeable (hybrid real
    OS-minimize + custom pill), just not drawn inside a Friday panel.

    Chat, Profile, Image Generation, and Video Generation are four more
    fully built-in panels (same no-real-process mechanism as Notepad/
    Settings) -- each one is an empty surface with a bottom input bar
    (an attach-file button, a text box, and mic/speaker buttons).
    They're deliberately just the UI shell for now: typing and pressing
    Enter clears the box rather than faking a reply, and Image/Video
    Generation say plainly in-panel that there's no real generation
    model wired up yet (matching Settings' own honest labeling for
    those two faculties) — don't claim to have generated or replied
    with anything through these yet.

    Call this for "open chrome"/"open notepad"/"open the calculator"/
    "open settings"/"open chat"/"open my profile"/"open image
    generation"/"open video generation" — this really opens the real
    thing (or, for Notepad/Settings/Chat/Profile/Image Generation/Video
    Generation, Friday's own real built-in panel), it does not simulate
    it inside the IDE. Use ide_open_folder/ide_create_file etc. instead
    for anything that's actually about writing/running code in the IDE.

    Friday only ever shows one single panel on screen at a time. A
    freshly-opened panel always takes that one slot — full screen,
    front and center — and whatever was active before (the IDE or
    another app panel, if anything) is automatically minimized to a
    pill under the circle to make room, same as restore_app/
    maximize_app do. (If the app you're opening is already open and
    already visible, this is a no-op; if it's already open but
    minimized, it's simply restored/promoted to active instead of
    opening a second copy.)

    Args:
        name: which app to open — "chrome", "notepad", "calculator", or
            "settings".
        url: Chrome only. A URL to open — a new tab of the same Chrome
            window if Chrome is already open, a fresh window otherwise.
        content: Notepad only. Text to pre-fill a brand new tab with in
            Friday's own built-in Notepad panel. If Notepad is already
            open, this adds it as a new tab instead of replacing what's
            there. Leave blank for a blank tab.
    """

    # Where this app lands -- always the one single active/maximized
    # slot, minimizing whatever was previously active to make room, or
    # nothing extra at all if it's already open and visible, or already
    # open and gets a new tab added instead -- is all decided internally
    # by _panel_manager.open() itself now (via
    # AppPanelManager._decide_placement(), which calls back into this
    # module's own _place_new_or_restored_panel()), the same shared
    # system agent_mode_on() uses for the IDE.
    return _panel_manager.open(name, url=url or None, content=content or None)


def list_open_apps() -> str:
    """Lists every top-level panel Friday currently has open — the IDE
    (if it's open) plus any native apps he's launched on command
    (Chrome, Notepad, Calculator, Settings, ...) — and whether each is minimized.

    Call this before acting on an ambiguous "minimize that"/"close that
    tab"/"what do you have open" so you check what's actually open
    instead of guessing which one the user means. (For tabs *inside*
    the IDE's own code editor specifically, use ide_list_open_tabs
    instead — that's a different, narrower listing.) If Notepad or
    Calculator was supposed to be embedded inside its own panel but
    couldn't be (window never found, embedding failed, not on
    Windows, ...), this says so plainly right next to that app instead
    of leaving you to guess why it's just a plain window — read that
    note back to the user if they ask why something didn't embed.
    """
    lines = []
    if is_agent_mode_on():
        try:
            minimized = _run_on_main(lambda: getattr(_ide_app, "_pill", None) is not None)
        except Exception:  # noqa: BLE001
            minimized = False
        lines.append(f"- IDE ({'minimized' if minimized else 'open'})")
    external = _panel_manager.list_panels()
    if not external.startswith("No app panels"):
        lines.extend(external.splitlines())
    if not lines:
        return "No panels are open right now — nothing to list."
    return "\n".join(lines)


def get_environment_snapshot() -> str:
    """Short, always-current summary of what's actually on screen right
    now: which panels are open, and which one (if any) currently has the
    shared maximized/focused slot, plus -- if Agent Mode is on -- the
    IDE's own sidebar view and active editor tab. This is the "ambient
    awareness" counterpart to list_open_apps()/ide_list_open_tabs(): it's
    not a tool the model calls on demand, it's folded straight into every
    reply's context automatically by agent_overlay.py's AIWorker (see
    _load_environment_context() there), so Friday never has to guess or
    ask "what do you have open?" before answering a question about it.

    Never raises and never blocks on a dead/unreachable UI thread for
    long -- worst case this quietly says a bit less than it could,
    rather than ever delaying a reply.
    """
    lines = []

    if is_agent_mode_on():
        def _snapshot_ide():
            buffers = getattr(_ide_app, "buffers", None) or []
            current = getattr(_ide_app, "current", None)
            active_tab = None
            active_tab_modified = False
            if buffers and isinstance(current, int) and 0 <= current < len(buffers):
                b = buffers[current]
                active_tab = b.get("path") or b.get("name")
                active_tab_modified = bool(b.get("modified"))
            sidebar = getattr(_ide_app, "sidebar", None)
            return {
                "minimized": getattr(_ide_app, "_pill", None) is not None,
                "sidebar_visible": getattr(_ide_app, "sidebar_visible", None),
                "sidebar_mode": getattr(sidebar, "mode", None),
                "active_tab": active_tab,
                "active_tab_modified": active_tab_modified,
            }

        try:
            info = _run_on_main(_snapshot_ide)
        except Exception:  # noqa: BLE001
            info = None

        if info is None:
            lines.append("- The IDE is open (couldn't check its current state just now).")
        elif info["minimized"]:
            lines.append("- The IDE is open but minimized to a pill.")
        else:
            detail = []
            if info["sidebar_visible"] and info["sidebar_mode"]:
                detail.append(f'sidebar showing "{info["sidebar_mode"]}"')
            elif info["sidebar_visible"] is False:
                detail.append("sidebar hidden")
            if info["active_tab"]:
                dirty = " (unsaved changes)" if info["active_tab_modified"] else ""
                detail.append(f'active file: {info["active_tab"]}{dirty}')
            suffix = f" — {', '.join(detail)}" if detail else ""
            lines.append(f"- The IDE is open and active{suffix}.")

    # Native app panels (Notepad, Calculator, embedded browser, ...) --
    # _live_panels() is a plain lock-protected dict read, no Tk-thread
    # marshaling needed, same as list_panels()/list_open_apps() above.
    try:
        panels = _panel_manager._live_panels()
    except Exception:  # noqa: BLE001
        panels = {}
    if panels:
        for rec in panels.values():
            state = "minimized" if rec.get("minimized") else "open"
            if rec.get("maximized"):
                state += ", currently active/focused"
            lines.append(f"- {rec['label']} ({state})")

    if not lines:
        return (
            "\n\n--- What's currently on screen (always current, not "
            "from memory) ---\nNothing else is open right now — no IDE, "
            "no other app panels."
        )
    return (
        "\n\n--- What's currently on screen (always current, not from "
        "memory) ---\n" + "\n".join(lines)
    )


def minimize_app(which: str) -> str:
    """Minimizes one of Friday's open top-level panels — the IDE, or a
    native app he opened (Chrome, Notepad, Calculator, Settings) — down into a
    small pill tucked under his floating circle. Pass "all" to minimize
    everything currently open at once.

    For a panel that's actually embedded (Notepad/Calculator, when
    embedding succeeded — see open_app), this hides Friday's own panel
    frame that the real app is living inside, rather than minimizing
    the real app's window directly (it's a child window now, it has no
    independent taskbar presence of its own to minimize). For anything
    not embedded — Chrome always, or an embeddable app that happened to
    fall back to a plain window — this does a real OS-level minimize to
    the taskbar, same as before, with the pill as a visible handle on it.

    If the name is ambiguous (matches more than one open panel) or
    matches none, this says so instead of guessing — call
    list_open_apps first and ask the user which one they mean whenever
    that happens, rather than acting on a guess.
    """
    # Minimizing any panel releases its claim on being the one single
    # active/maximized panel, if it held one -- handled internally now
    # (AppPanelManager._minimize_one and _minimize_ide_panel both call
    # _release_panel_slot themselves), so nothing extra is needed here
    # beyond picking which panel(s) to actually minimize.
    w = (which or "").strip().lower()
    if w == "all":
        results = []
        if is_agent_mode_on():
            results.append(_minimize_ide_panel())
        results.append(_panel_manager.minimize("all"))
        return " ".join(r for r in results if r)
    if w in _PANEL_NAMES_FOR_IDE:
        return _minimize_ide_panel()
    return _panel_manager.minimize(which)


def restore_app(which: str) -> str:
    """Restores one of Friday's minimized top-level panels (the IDE or
    a native app he opened) back to being Friday's single active/
    visible panel — full screen, front and center (restoring and
    maximizing are deliberately the same action now: there's no other,
    smaller on-screen state left to restore into, since Friday only
    ever shows one single panel at a time — see maximize_app). Whatever
    else was previously the active panel (if anything) is automatically
    minimized to a pill under the circle to make room.

    Pass "all" to restore the single most-recently-minimized panel —
    since at most one panel can ever be visible at once, "restore
    everything" isn't literally possible any more; this picks up where
    a user would most likely mean to continue from.
    """
    w = (which or "").strip().lower()
    if w == "all":
        if not _MINIMIZED_STACK:
            return "Nothing is minimized right now."
        return restore_app(_MINIMIZED_STACK[-1])
    if w in _PANEL_NAMES_FOR_IDE:
        return _restore_ide_panel()
    return _panel_manager.restore(which)


def maximize_app(which: str) -> str:
    """Makes one of Friday's open panels the single active/visible one
    on screen -- full screen, at Friday's own IDE-style reference
    size/position ("the IDE's panel size", the same one every panel
    uses the instant it's opened -- see open_app). Only one panel is
    ever visible at a time: whatever else was previously the active
    one (if anything) is minimized to a pill under the circle to make
    room, exactly like opening or restoring a new panel already does.
    If the target is currently minimized, it's restored and promoted
    straight to active in one step -- maximize_app and restore_app are
    deliberately the same underlying action now (see the module-level
    comment above _ide_opened_at for why), kept as two separate tools
    only because they're both already part of Friday's conversational
    vocabulary. Works whether or not the IDE happens to be open right
    now -- "the IDE's panel size" is a fixed, nameable reference, not
    something that needs a live IDE window to measure.

    Pass "ide" to make the IDE itself the active/front panel again.
    """
    global _maximized_panel_key
    w = (which or "").strip().lower()

    if w in _PANEL_NAMES_FOR_IDE:
        if not is_agent_mode_on():
            return "The IDE isn't open right now."
        target_key, label, rec = "ide", "The IDE", None
    else:
        matches = _panel_manager._match(which)
        if not matches:
            return (f"No open app panel matches '{which}'. Here's what's "
                     f"open:\n{list_open_apps()}")
        if len(matches) > 1:
            names = ", ".join(r["label"] for _, r in matches)
            return (f"More than one open panel matches '{which}': {names}. "
                     "Ask the user which one they mean before maximizing anything.")
        target_key, rec = matches[0]
        label = rec["label"]

    if _maximized_panel_key == target_key:
        return f"{label} is already the maximized, active panel."

    prev = _maximized_panel_key

    # Bring it into view first if it's currently minimized -- skip the
    # normal placement decision (assign_slot=False), since it's about
    # to be promoted straight to the one active slot below anyway.
    if target_key == "ide":
        try:
            minimized = _run_on_main(lambda: getattr(_ide_app, "_pill", None) is not None)
        except Exception:  # noqa: BLE001
            minimized = False
        if minimized:
            _restore_ide_panel(assign_slot=False)
    elif rec.get("minimized"):
        _panel_manager._restore_one(target_key, rec, assign_slot=False)

    bounds = _ide_reference_bounds()
    if target_key == "ide":
        try:
            _run_on_main(lambda: (_ide_app.resize_to_bounds(*bounds),
                                   _ide_app.deiconify(), _ide_app.lift(),
                                   _ide_app.focus_force()))
        except Exception:  # noqa: BLE001
            pass
    else:
        ok, reason = _panel_manager.maximize_panel(target_key, bounds)
        if not ok:
            return f"Couldn't maximize {label}: {reason or 'unknown error'}"

    # Only one panel is ever shown on screen at a time now -- whatever
    # was active before (if anything, and if it isn't this same panel)
    # gets minimized to make room, through the exact same
    # _release_panel_slot flow that clears its own active flag, the
    # same thing opening/restoring a new panel already triggers.
    # Deliberately done *before* reassigning _maximized_panel_key below
    # -- _release_panel_slot's own "is this the active one?" check
    # needs `prev` to still actually be the recorded active key when it
    # runs, or it would silently skip clearing its active-panel flag.
    note = ""
    if prev is not None and prev != target_key:
        note = f" ({_label_for(prev)} was minimized to make room for it.)"
        _minimize_key_to_pill(prev)

    _maximized_panel_key = target_key
    # target_key's own mover call above (resize_to_bounds for the IDE,
    # or AppPanelManager.maximize_panel -> frame.maximize_to for
    # anything else) already flagged it active in the app_panels.py
    # case; this call is what actually does it for the IDE (which has
    # no such mover-based hook) and is a harmless no-op repeat
    # otherwise (set_active_panel is idempotent).
    _apply_active_panel_flag(target_key, True)

    return f"{label} is now the maximized, active panel.{note}"


def close_app(which: str) -> str:
    """Closes one of Friday's open top-level panels — the IDE (same as
    agent_mode_off) or a native app he opened (Chrome, Notepad,
    Calculator, Settings). Pass "all" to close everything currently open.

    Same ambiguity rule as minimize_app/restore_app: if the name
    matches more than one open panel (or none), this says so instead
    of guessing — check with the user first."""
    # Closing any panel releases its claim on being the one single
    # active/maximized panel, if it held one -- handled internally now
    # (AppPanelManager._close_one and on_ide_closed() both call
    # _release_panel_slot themselves).
    w = (which or "").strip().lower()
    if w in _PANEL_NAMES_FOR_IDE:
        return agent_mode_off()
    if w == "all":
        results = []
        if is_agent_mode_on():
            results.append(agent_mode_off())
        results.append(_panel_manager.close("all"))
        return " ".join(r for r in results if r)
    return _panel_manager.close(which)


def type_in_app(which: str, text: str) -> str:
    """Types `text` into the active tab of an already-open Notepad
    panel Friday opened earlier, right at the current cursor position
    — direct and fully reliable, since Notepad is Friday's own built-in
    editor widget now, not a foreign window that needs driving (no
    optional dependency needed for this any more).

    Args:
        which: which open panel to type into (currently only Notepad
            supports this).
        text: the text to type.
    """
    return _panel_manager.type_text(which, text)


def save_app_file(which: str, path: str = "") -> str:
    """Saves an open Notepad panel's real, current content to a real
    file on the user's PC — currently the only way any panel's content
    gets written to disk, since Notepad is Friday's own built-in editor
    (not a real notepad.exe with its own Save dialog Friday could drive
    instead).

    Call this whenever the user asks to save/export what's in Notepad,
    e.g. "save that to my Desktop as notes.txt" or just "save that".

    Args:
        which: which open panel to save (currently only "notepad"
            supports this).
        path: where to save it, e.g. "notes.txt", "Desktop/notes.txt",
            or a full path. A relative path is resolved against the
            user's own home directory, not wherever Friday's process
            happens to be running from. ".txt" is added automatically
            if you don't give an extension. Leave this blank to just
            reuse whatever path this tab was already saved to before
            (a plain re-save), or — if it's never been saved at all —
            Friday picks a sensible default location/filename on his
            own (under "Documents/Friday Notes") rather than failing;
            prefer giving an explicit path whenever the user mentions
            one, so it ends up exactly where they expect.
    """
    return _panel_manager.save_file(which, path or None)


def agent_mode_off() -> str:
    """Turn off Agent Mode: closes the IDE.

    Call this when the user says something like "close agent mode" or
    "close the IDE". If there's unsaved work open in it, the IDE will ask
    to save before it actually closes, same as clicking its own close
    button.
    """
    global _ide_app

    if not is_agent_mode_on():
        return "Agent Mode is already off."

    # Deliberately using _post_on_main (fire-and-forget) rather than
    # _run_on_main (which blocks for a result) for both calls below,
    # and deliberately NOT "app = _ide_app" (a bare local this function
    # would otherwise hold for the next several seconds, across the
    # polling wait below): the IDEApp instance's own interpreter
    # (self.tk) is only safe to tear down from the IDE's dedicated Tk
    # thread, and whichever Python-level reference-count decrement
    # happens to be the *last* one triggers that teardown -- on
    # whatever thread performs that specific decrement. Blocking here
    # for close_window()/destroy() to finish (as _run_on_main would)
    # keeps a reference to the bridge -- and so to the IDEApp instance
    # itself -- alive on *this* thread for the whole round trip; in
    # testing that was occasionally just long enough for this thread to
    # still be holding it once the Tk thread's own post-mainloop
    # cleanup (see _tk_main's finally block) had already freed
    # everything else, and the resulting final deallocation happened on
    # the wrong thread -- a hard, unrecoverable Tcl-level process
    # abort, not a catchable exception. Posting instead and polling
    # _ide_app the same way the loop below already did keeps this
    # thread from ever holding that last reference.
    try:
        _post_on_main(lambda: _ide_app.close_window() if _ide_app is not None else None)
    except Exception:  # noqa: BLE001
        pass  # fall through to the hard-stop fallback below

    deadline = time.time() + 5.0
    while time.time() < deadline and _ide_app is not None:
        time.sleep(0.1)

    if _ide_app is not None:
        try:
            _post_on_main(lambda: _ide_app.destroy() if _ide_app is not None else None)
        except Exception:  # noqa: BLE001
            pass
        # Give that destroy() a brief moment to actually run on the Tk
        # thread before this function returns (and "Agent Mode is off"
        # gets spoken/printed) -- same spirit as the deadline above,
        # just shorter since this is already the last-resort path.
        fallback_deadline = time.time() + 2.0
        while time.time() < fallback_deadline and _ide_app is not None:
            time.sleep(0.1)
        _ide_app = None  # belt-and-braces in case destroy()'s own
                          # on_ide_closed() hand-off didn't land

    return "Agent Mode is off. The IDE is closed."


def ide_open_folder(folder: str) -> str:
    """Open an existing folder in the IDE (Agent Mode must already be on).

    Args:
        folder: Name or path of the folder to open, e.g. "my-project" or
            a full path. A bare name is searched for in common locations
            (home, Desktop, Documents, Downloads, Friday-Agent-Workspace).
    """
    if not is_agent_mode_on():
        return agent_mode_on(folder=folder)
    try:
        path = _resolve_folder_hint(folder)

        # See agent_mode_off()'s comment on why this looks _ide_app up
        # fresh inside the Tk-thread closure rather than binding it to
        # a bare local on this (possibly different) calling thread.
        def _do():
            app = _ide_app
            app.set_root(path)
            app.refresh_explorer()
            app._index_workspace()

        _run_on_main(_do)
        return f"Opened '{os.path.basename(path)}' in the IDE."
    except Exception as exc:  # noqa: BLE001
        return f"Error opening that folder in the IDE: {exc}"


def ide_create_file(path: str, content: str = "") -> str:
    """Create a new file inside the IDE's open workspace, visible live in its Explorer (Agent Mode must be on).

    Args:
        path: Path relative to the folder currently open in the IDE (or
            absolute, as long as it's inside that folder). Refuses to
            overwrite an existing file — use ide_write_file for that.
        content: Text content for the new file.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        result = _ide_app.fs.create_file(path, content, agent=True)
        return f"Created {result} in the IDE."
    except Exception as exc:  # noqa: BLE001
        return f"Error creating that file in the IDE: {exc}"


def ide_write_file(path: str, content: str) -> str:
    """Create or overwrite a file inside the IDE's open workspace, visible live in its editor (Agent Mode must be on).

    Args:
        path: Path relative to the folder currently open in the IDE (or
            absolute, as long as it's inside that folder).
        content: The full text content to write.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        result = _ide_app.fs.write(path, content, agent=True)
        return f"Wrote {len(content)} characters to {result} in the IDE."
    except Exception as exc:  # noqa: BLE001
        return f"Error writing that file in the IDE: {exc}"


def ide_edit_file(path: str, old_text: str, new_text: str) -> str:
    """Edit a file already inside the IDE's open workspace by replacing the first occurrence of some exact text (Agent Mode must be on).

    Args:
        path: Path relative to the folder currently open in the IDE.
        old_text: The exact text to search for (only the first occurrence
            is replaced).
        new_text: The text to replace it with.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        result = _ide_app.fs.edit(path, old_text, new_text, agent=True)
        return f"Edited {result} in the IDE."
    except Exception as exc:  # noqa: BLE001
        return f"Error editing that file in the IDE: {exc}"


def ide_create_folder(path: str) -> str:
    """Create a new folder inside the IDE's open workspace, visible live in its Explorer (Agent Mode must be on).

    Args:
        path: Path relative to the folder currently open in the IDE, e.g.
            "src/utils". Parent folders are created automatically.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        result = _ide_app.fs.create_folder(path, agent=True)
        return f"Created folder {result} in the IDE."
    except Exception as exc:  # noqa: BLE001
        return f"Error creating that folder in the IDE: {exc}"


def ide_read_file(path: str) -> str:
    """Read a file's content from inside the IDE's open workspace (Agent Mode must be on).

    Args:
        path: Path relative to the folder currently open in the IDE.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        return _ide_app.fs.read(path)
    except Exception as exc:  # noqa: BLE001
        return f"Error reading that file in the IDE: {exc}"


def ide_list_folder(path: str = ".") -> str:
    """List files and subfolders inside a folder in the IDE's open workspace (Agent Mode must be on).

    Args:
        path: Path relative to the folder currently open in the IDE.
            Defaults to the workspace root.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        names = _ide_app.fs.list(path)
        return "\n".join(names) if names else "(empty folder)"
    except Exception as exc:  # noqa: BLE001
        return f"Error listing that folder in the IDE: {exc}"


def ide_workspace_tree() -> str:
    """List every file in the IDE's currently open workspace, as workspace-relative paths (Agent Mode must be on)."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        paths = _ide_app.fs.tree()
        return "\n".join(paths) if paths else "(empty workspace)"
    except Exception as exc:  # noqa: BLE001
        return f"Error reading the IDE's workspace tree: {exc}"


def ide_exists(path: str) -> str:
    """Check whether a file or folder exists inside the IDE's open workspace (Agent Mode must be on).

    Args:
        path: Path relative to the folder currently open in the IDE.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        found = _ide_app.fs.exists(path)
        return f"'{path}' {'exists' if found else 'does not exist'} in the workspace."
    except Exception as exc:  # noqa: BLE001
        return f"Error checking that path in the IDE: {exc}"


def ide_rename(path: str, new_name: str) -> str:
    """Rename a file or folder inside the IDE's open workspace, visible live in its Explorer (Agent Mode must be on).

    Args:
        path: Path, relative to the open folder, of the file/folder to rename.
        new_name: The new name (just the filename, not a full path, unless
            you're also moving it into a different folder).
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        result = _ide_app.fs.rename(path, new_name)
        return f"Renamed to {result} in the IDE."
    except Exception as exc:  # noqa: BLE001
        return f"Error renaming that in the IDE: {exc}"


def ide_copy(path: str, destination_folder: str) -> str:
    """Copy a file or folder inside the IDE's open workspace, visible live in its Explorer (Agent Mode must be on).

    Args:
        path: Path, relative to the open folder, of the file/folder to copy.
        destination_folder: Folder (relative to the open folder) to copy it into.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        result = _ide_app.fs.copy(path, dst_dir=destination_folder)
        return f"Copied to {result} in the IDE."
    except Exception as exc:  # noqa: BLE001
        return f"Error copying that in the IDE: {exc}"


def ide_move(path: str, destination_folder: str) -> str:
    """Move a file or folder inside the IDE's open workspace, visible live in its Explorer (Agent Mode must be on).

    Args:
        path: Path, relative to the open folder, of the file/folder to move.
        destination_folder: Folder (relative to the open folder) to move it into.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        result = _ide_app.fs.move(path, destination_folder)
        return f"Moved to {result} in the IDE."
    except Exception as exc:  # noqa: BLE001
        return f"Error moving that in the IDE: {exc}"


def ide_search_workspace(query: str, scope: str = ".") -> str:
    """Search for a plain-text string across every file in the IDE's open workspace (or a subfolder of it), same as using the IDE's own Search sidebar (Agent Mode must be on).

    Args:
        query: The text to search for (case-insensitive, no regex).
        scope: Folder to search within, relative to the open workspace.
            Defaults to the whole workspace.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        hits = _ide_app.fs.search(query, scope=scope)
        if not hits:
            return f"No matches for '{query}'."
        lines = [f"{path}:{ln}: {snippet}" for path, ln, snippet in hits[:80]]
        more = f"\n…and {len(hits) - 80} more matches" if len(hits) > 80 else ""
        return "\n".join(lines) + more
    except Exception as exc:  # noqa: BLE001
        return f"Error searching the IDE's workspace: {exc}"


# ---------------------------------------------------------------------------
# Agent-driven file/folder deletion — the deliberately narrow exception to
# the "no delete tool" policy stated at the top of this file, scoped to
# cleaning up dead/leftover content inside the open workspace that isn't
# part of Friday's active work. Two parallel two-step flows, one for single
# files and one for whole folders, each enforced in code here, not just by
# prompting:
#
#   1. ide_analyze_file_for_deletion(path) / ide_analyze_folder_for_deletion(path)
#      — read-only. Reads the file (or inventories every file under the
#      folder) and searches the rest of the workspace for anything that
#      still references it (imports, bare filename/path mentions, etc.),
#      then returns a report and records a fingerprint (content hash for a
#      file, a hash over every contained file's path+size+mtime for a
#      folder) for the next step to check freshness against. Friday must
#      relay that report to the user and use its own judgment: proceed
#      straight to deletion and narrate it for routine, clearly-dead
#      content with nothing depending on it — no permission round-trip
#      needed — but stop and get the user's explicit go-ahead first if
#      references were found, something is ambiguous, or the user would
#      obviously want a say.
#
#   2. ide_delete_file(path) / ide_delete_folder(path) — each only succeeds
#      if its matching analyze step was just called for this exact
#      file/folder and nothing inside it has changed since (a skipped,
#      stale, or fingerprint-mismatched analysis is rejected outright, so
#      this can't be bypassed just by not calling step 1, and a race where
#      the content changes between the two calls is caught too). Even
#      then, nothing is ever permanently removed — it's moved into a
#      hidden .friday_trash folder inside the workspace (see
#      WorkspaceFS.trash()), timestamped, so a wrong call can always be
#      recovered by moving it back out by hand. Project infrastructure
#      (.git, node_modules, a venv, build/cache output — see SKIP_DIRS in
#      ide/ide.py) and the workspace root itself are always refused
#      outright for folder deletion, regardless of what the analysis says.
#
# Neither flow touches the human-driven right-click Delete in the IDE's own
# Explorer, which stays a separate, permanent, human-only action with its
# own confirm dialog — completely unrelated to this flow.
# ---------------------------------------------------------------------------

_pending_deletion_analysis = {}  # resolved path -> (sha256 of content, analyzed_at)
_DELETION_ANALYSIS_TTL_SECONDS = 30 * 60  # re-analyze if older than this


def _deletion_reference_terms(rel_path: str) -> set:
    """Plausible terms another file might use to reference this one — its
    bare filename, its stem, and (for Python files) the dotted import
    path you'd reach it by."""
    terms = set()
    base = os.path.basename(rel_path)
    terms.add(base)
    stem, ext = os.path.splitext(base)
    if stem:
        terms.add(stem)
    if ext == ".py":
        mod_path = rel_path[:-3].replace(os.sep, ".").replace("/", ".")
        if mod_path:
            terms.add(mod_path)
            terms.add(mod_path.split(".")[-1])
    return {t for t in terms if t and t != "."}


def ide_analyze_file_for_deletion(path: str) -> str:
    """Read a file and check the rest of the IDE's open workspace for anything that still references it — required before Friday may delete it (Agent Mode must be on).

    This is step 1 of Friday's file-deletion flow. Always call this before
    ide_delete_file, every time, even if the file was looked at earlier in
    the conversation. Relay what it reports to the user in your own
    words, then use your own judgment: if it's clearly dead/leftover
    content (generated output, a scratch file, replaced-by-refactor code,
    nothing else references it) go ahead and call ide_delete_file without
    waiting for a reply — routine workspace cleanup doesn't need a
    permission round-trip. If anything is ambiguous, or references were
    found, or this is something the user obviously cares about keeping,
    stop and get their explicit go-ahead first instead of guessing. Never
    call ide_delete_file first.

    Args:
        path: Path, relative to the open workspace folder, of the file to
            consider deleting.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        resolved = _ide_app.fs.resolve(path)
    except Exception as exc:  # noqa: BLE001
        return f"Error resolving that path in the IDE: {exc}"
    if not os.path.exists(resolved):
        return f"'{path}' does not exist in the workspace — nothing to analyze."
    if os.path.isdir(resolved):
        return (f"'{path}' is a folder, not a file — call "
                f"ide_analyze_folder_for_deletion instead.")
    try:
        with open(resolved, "rb") as fh:
            raw = fh.read()
    except Exception as exc:  # noqa: BLE001
        return f"Error reading that file in the IDE: {exc}"

    content_hash = hashlib.sha256(raw).hexdigest()
    _pending_deletion_analysis[resolved] = (content_hash, time.time())
    size = len(raw)
    try:
        text = raw.decode("utf-8")
        line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        preview = text if len(text) <= 4000 else (
            text[:2000] + "\n...(truncated)...\n" + text[-1500:])
        content_section = f"Content ({line_count} lines, {size} bytes):\n{preview}"
    except UnicodeDecodeError:
        content_section = f"(binary file, {size} bytes — content not shown)"

    rel_path = os.path.relpath(resolved, _ide_app.fs.root)
    references = []
    seen = set()
    try:
        for term in _deletion_reference_terms(rel_path):
            for hit_path, ln, snippet in _ide_app.fs.search(term, scope="."):
                if os.path.normpath(
                        os.path.join(_ide_app.fs.root, hit_path)) == resolved:
                    continue  # the file mentioning itself doesn't count
                key = (hit_path, ln)
                if key in seen:
                    continue
                seen.add(key)
                references.append(f"{hit_path}:{ln}: {snippet}")
    except Exception:  # noqa: BLE001
        pass

    if references:
        refs_section = (
            f"References found elsewhere in the workspace "
            f"({len(references)} match(es) — read these before deciding, "
            f"this file may still be in use):\n" + "\n".join(references[:40]))
        if len(references) > 40:
            refs_section += f"\n...and {len(references) - 40} more matches"
        verdict = "NOT clearly dead — other files appear to reference it."
    else:
        refs_section = ("No references to this file's name found anywhere "
                         "else in the workspace.")
        verdict = ("Looks unused based on a name search, but that search "
                   "can miss dynamic references (reflection, string-built "
                   "paths, config files, etc.) — weigh the content above "
                   "too, not just this search.")

    return (
        f"Analysis of '{rel_path}' (do not call this again for the same "
        f"unchanged file):\n\n{content_section}\n\n{refs_section}\n\n"
        f"Verdict: {verdict}\n\nRelay this to the user in your own words, "
        f"then use your own judgment: if this is clearly dead/leftover "
        f"content with nothing depending on it, routine cleanup doesn't "
        f"need to wait on a reply — just call ide_delete_file('{path}') "
        f"and say what you removed. If anything above is ambiguous or "
        f"references were found, stop and get the user's explicit "
        f"go-ahead first."
    )


def ide_delete_file(path: str) -> str:
    """Delete a single file from the IDE's open workspace — only after ide_analyze_file_for_deletion was just called for this exact, unchanged file (Agent Mode must be on).

    The file is never permanently destroyed: it is moved into a hidden
    .friday_trash folder inside the workspace, timestamped, so it can be
    recovered by hand if this turns out to be wrong. Calling this without
    having just analyzed this exact, unmodified file fails on purpose —
    always call ide_analyze_file_for_deletion first, even if you already
    looked at the file earlier in the conversation.

    This is for keeping the open workspace clean during normal coding
    work — leftover scaffolding, confirmed-dead code, generated/duplicate
    content nothing depends on — not for anything the analysis flagged as
    referenced or ambiguous; use your own judgment on those and check with
    the user first rather than guessing.

    Args:
        path: Path, relative to the open workspace folder, of the file to
            delete. Must be a single file, never a folder (use
            ide_delete_folder for that).
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        resolved = _ide_app.fs.resolve(path)
    except Exception as exc:  # noqa: BLE001
        return f"Error resolving that path in the IDE: {exc}"

    pending = _pending_deletion_analysis.get(resolved)
    if pending is None:
        return (
            "Refusing to delete — ide_analyze_file_for_deletion hasn't "
            "been called for this file yet. Call that first, relay its "
            "findings (or use your own judgment if it's clearly routine "
            "cleanup), and only call this afterward."
        )
    content_hash, analyzed_at = pending
    if time.time() - analyzed_at > _DELETION_ANALYSIS_TTL_SECONDS:
        _pending_deletion_analysis.pop(resolved, None)
        return (
            "Refusing to delete — that analysis is more than 30 minutes "
            "old. Call ide_analyze_file_for_deletion again to refresh it "
            "before retrying."
        )
    if not os.path.exists(resolved):
        _pending_deletion_analysis.pop(resolved, None)
        return f"'{path}' no longer exists — nothing to delete."
    try:
        with open(resolved, "rb") as fh:
            current_hash = hashlib.sha256(fh.read()).hexdigest()
    except Exception as exc:  # noqa: BLE001
        return f"Error re-reading that file before deletion: {exc}"
    if current_hash != content_hash:
        _pending_deletion_analysis.pop(resolved, None)
        return (
            "Refusing to delete — this file's content changed since it "
            "was last analyzed. Call ide_analyze_file_for_deletion again "
            "on the current version before retrying."
        )

    try:
        trashed_to = _ide_app.fs.trash(path)
    except Exception as exc:  # noqa: BLE001
        return f"Error deleting that file in the IDE: {exc}"
    finally:
        _pending_deletion_analysis.pop(resolved, None)

    rel_trash = os.path.relpath(trashed_to, _ide_app.fs.root)
    return (
        f"Deleted '{path}'. It wasn't permanently destroyed — it's sitting "
        f"in the workspace's hidden trash folder at '{rel_trash}' and can "
        f"be recovered by moving it back if this turns out to be wrong."
    )


_pending_folder_deletion_analysis = {}  # resolved dir -> (fingerprint, analyzed_at)


def _folder_deletion_fingerprint(resolved_dir):
    """The same staleness guard ide_delete_file uses (a content sha256),
    extended to a whole folder: every contained file's relative path and
    own content hash, chained together into one digest. Reads file
    content rather than trusting size/mtime on purpose -- a same-second
    edit that doesn't change a file's size would otherwise slip past a
    metadata-only check undetected."""
    rel_root = os.path.relpath(resolved_dir, _ide_app.fs.root)
    rel_root = "." if rel_root == "." else rel_root
    entries = []
    for rel in sorted(_ide_app.fs.tree(rel_root)):
        full = os.path.join(_ide_app.fs.root, rel)
        try:
            with open(full, "rb") as fh:
                content_hash = hashlib.sha256(fh.read()).hexdigest()
            entries.append(f"{rel}:{content_hash}")
        except OSError:
            entries.append(f"{rel}:missing")
    digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()
    return digest, entries


def ide_analyze_folder_for_deletion(path: str) -> str:
    """Inventory a folder and check the rest of the IDE's open workspace for anything that still references files inside it — required before Friday may delete it (Agent Mode must be on).

    This is step 1 of the only folder-deletion flow Friday has, mirroring
    ide_analyze_file_for_deletion/ide_delete_file exactly, just scoped to
    every file inside a folder at once instead of a single file. Always
    call this before ide_delete_folder, every time, even if the folder
    was looked at earlier in the conversation. Relay what it reports —
    the folder's contents and whether anything elsewhere in the workspace
    appears to reference something inside it — to the user in your own
    words, and use your own judgment about whether it's routine cleanup
    (generated/dead/leftover content with nothing depending on it) you
    can just go ahead with, or something uncertain enough to ask the user
    about first. Never call ide_delete_folder first.

    Refuses outright on the workspace root itself and on project
    infrastructure folders (.git, node_modules, a venv, build/cache
    output) — those are never "dead code to clean up", even if nothing
    else references them by name.

    Args:
        path: Path, relative to the open workspace folder, of the folder
            to consider deleting.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        resolved = _ide_app.fs.resolve(path)
    except Exception as exc:  # noqa: BLE001
        return f"Error resolving that path in the IDE: {exc}"
    if not os.path.exists(resolved):
        return f"'{path}' does not exist in the workspace — nothing to analyze."
    if not os.path.isdir(resolved):
        return (f"'{path}' is a file, not a folder — call "
                f"ide_analyze_file_for_deletion instead.")
    if os.path.abspath(resolved) == os.path.abspath(_ide_app.fs.root):
        return "Refusing to analyze the open workspace's root folder for deletion."
    base_name = os.path.basename(resolved.rstrip(os.sep))
    if base_name in _ide_module.SKIP_DIRS:
        return (f"'{path}' is project infrastructure (version control, "
                f"dependencies, or build output), not dead code — Friday "
                f"never deletes folders like this regardless of what the "
                f"analysis would say.")

    fingerprint, entries = _folder_deletion_fingerprint(resolved)
    _pending_folder_deletion_analysis[resolved] = (fingerprint, time.time())
    rel_root = os.path.relpath(resolved, _ide_app.fs.root)

    if not entries:
        contents_section = "This folder is empty."
    else:
        shown = entries[:60]
        contents_section = (
            f"Contains {len(entries)} file(s):\n" +
            "\n".join(e.split(":", 1)[0] for e in shown))
        if len(entries) > 60:
            contents_section += f"\n...and {len(entries) - 60} more"

    references = []
    seen = set()
    try:
        for rel in entries:
            rel_file = rel.split(":", 1)[0]
            for term in _deletion_reference_terms(rel_file):
                for hit_path, ln, snippet in _ide_app.fs.search(term, scope="."):
                    hit_full = os.path.normpath(
                        os.path.join(_ide_app.fs.root, hit_path))
                    if hit_full == resolved or hit_full.startswith(
                            resolved + os.sep):
                        continue  # a reference from inside the folder itself doesn't count
                    key = (hit_path, ln)
                    if key in seen:
                        continue
                    seen.add(key)
                    references.append(f"{hit_path}:{ln}: {snippet}")
    except Exception:  # noqa: BLE001
        pass

    if references:
        refs_section = (
            f"References found elsewhere in the workspace, outside this "
            f"folder ({len(references)} match(es) — read these before "
            f"deciding, something in here may still be in use):\n" +
            "\n".join(references[:40]))
        if len(references) > 40:
            refs_section += f"\n...and {len(references) - 40} more matches"
        verdict = ("NOT clearly dead — other files outside this folder "
                   "appear to reference something inside it. Treat this "
                   "as needing the user's explicit go-ahead, not routine "
                   "cleanup.")
    else:
        refs_section = ("No references to anything in this folder found "
                        "anywhere else in the workspace.")
        verdict = ("Looks unused based on a name search, but that search "
                   "can miss dynamic references (reflection, string-built "
                   "paths, config files, etc.) — weigh the contents above "
                   "too, not just this search, before treating it as safe, "
                   "routine cleanup.")

    return (
        f"Analysis of folder '{rel_root}' (do not call this again for the "
        f"same unchanged folder):\n\n{contents_section}\n\n{refs_section}"
        f"\n\nVerdict: {verdict}\n\nRelay this to the user in your own "
        f"words, then use your own judgment: if this is clearly dead/"
        f"leftover content with nothing depending on it, routine cleanup "
        f"doesn't need to wait on a reply — just call "
        f"ide_delete_folder('{path}') and say what you removed. If "
        f"anything above is ambiguous or references were found, stop and "
        f"get the user's explicit go-ahead first."
    )


def ide_delete_folder(path: str) -> str:
    """Delete a whole folder from the IDE's open workspace — only after ide_analyze_folder_for_deletion was just called for this exact, unchanged folder (Agent Mode must be on).

    The folder is never permanently destroyed: it is moved, as a whole,
    into the hidden .friday_trash folder inside the workspace, timestamped,
    so it can be recovered by hand if this turns out to be wrong. Calling
    this without having just analyzed this exact, unchanged folder fails
    on purpose — always call ide_analyze_folder_for_deletion first, even
    if you already looked at the folder earlier in the conversation.

    This is for keeping the open workspace clean during normal coding
    work — leftover scaffolding, confirmed-dead code, generated/duplicate
    content nothing depends on — not for anything the analysis flagged as
    referenced or ambiguous; use your own judgment on those and check with
    the user first rather than guessing.

    Args:
        path: Path, relative to the open workspace folder, of the folder
            to delete. Must be a folder, never a single file (use
            ide_delete_file for that).
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        resolved = _ide_app.fs.resolve(path)
    except Exception as exc:  # noqa: BLE001
        return f"Error resolving that path in the IDE: {exc}"

    pending = _pending_folder_deletion_analysis.get(resolved)
    if pending is None:
        return (
            "Refusing to delete — ide_analyze_folder_for_deletion hasn't "
            "been called for this folder yet. Call that first, relay its "
            "findings (or use your own judgment if it's clearly routine "
            "cleanup), and only call this afterward."
        )
    fingerprint, analyzed_at = pending
    if time.time() - analyzed_at > _DELETION_ANALYSIS_TTL_SECONDS:
        _pending_folder_deletion_analysis.pop(resolved, None)
        return (
            "Refusing to delete — that analysis is more than 30 minutes "
            "old. Call ide_analyze_folder_for_deletion again to refresh "
            "it before retrying."
        )
    if not os.path.exists(resolved):
        _pending_folder_deletion_analysis.pop(resolved, None)
        return f"'{path}' no longer exists — nothing to delete."
    if not os.path.isdir(resolved):
        _pending_folder_deletion_analysis.pop(resolved, None)
        return f"'{path}' is a file now, not a folder — call ide_delete_file instead."
    current_fingerprint, _entries = _folder_deletion_fingerprint(resolved)
    if current_fingerprint != fingerprint:
        _pending_folder_deletion_analysis.pop(resolved, None)
        return (
            "Refusing to delete — this folder's contents changed since it "
            "was last analyzed. Call ide_analyze_folder_for_deletion "
            "again on the current version before retrying."
        )

    try:
        trashed_to = _ide_app.fs.trash(path, allow_folder=True)
    except Exception as exc:  # noqa: BLE001
        return f"Error deleting that folder in the IDE: {exc}"
    finally:
        _pending_folder_deletion_analysis.pop(resolved, None)

    rel_trash = os.path.relpath(trashed_to, _ide_app.fs.root)
    return (
        f"Deleted the folder '{path}'. It wasn't permanently destroyed — "
        f"it's sitting in the workspace's hidden trash folder at "
        f"'{rel_trash}' and can be recovered by moving it back if this "
        f"turns out to be wrong."
    )


def ide_run_file() -> str:
    """Run the file open in the IDE's active editor tab, same as pressing F5 in the IDE (Agent Mode must be on). Use ide_get_terminal_output afterwards to see what it printed."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    result = {}

    def _do():
        result["task"] = _ide_app.run_file()

    try:
        _run_on_main(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error running the file: {exc}"
    task = result.get("task")
    if task:
        return (f"Running: {task['label']} — check ide_get_terminal_output "
                 "shortly for its output.")
    return ("Couldn't run that file — check ide_get_terminal_output for "
            "the exact reason.")


def ide_run_project() -> str:
    """Start the IDE's detected project run/dev-server task (e.g. npm dev, cargo run, go run), same as Ctrl+F5 in the IDE (Agent Mode must be on). Falls back to running the active file if no project task is detected."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    result = {}

    def _do():
        result["task"] = _ide_app.run_project()

    try:
        _run_on_main(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error running the project: {exc}"
    task = result.get("task")
    if task:
        return (f"Running: {task['label']} — check ide_get_terminal_output "
                 "shortly for its output.")
    return ("Couldn't start the project — check ide_get_terminal_output "
            "for the exact reason.")


def ide_build_project() -> str:
    """Run the IDE's detected project build task (Agent Mode must be on)."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    result = {}

    def _do():
        result["task"] = _ide_app.build_project()

    try:
        _run_on_main(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error building the project: {exc}"
    task = result.get("task")
    if task:
        return (f"Running: {task['label']} — check ide_get_terminal_output "
                 "shortly for its output.")
    return "No build task detected in this workspace."


def ide_stop_task() -> str:
    """Stop whatever build/run task is currently running in the IDE (Agent Mode must be on)."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    def _do():
        app = _ide_app
        was_running = app.task_proc is not None
        app.stop_task()
        return was_running

    try:
        was_running = _run_on_main(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error stopping the task: {exc}"
    return "Stopped the running task." if was_running else "Nothing was running."


def ide_get_terminal_output() -> str:
    """Read everything currently shown in the IDE's integrated terminal panel (Agent Mode must be on). Use this after ide_run_file/ide_run_project/ide_build_project/ide_run_terminal_command to see what happened."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        text = _run_on_main(_ide_app.get_terminal_output)
        return text if text.strip() else "(terminal is empty)"
    except Exception as exc:  # noqa: BLE001
        return f"Error reading the IDE's terminal: {exc}"


def ide_run_terminal_command(command: str, timeout_seconds: float = 60.0) -> str:
    """Run a shell command in the IDE's own integrated terminal, visibly, and wait for it to finish (Agent Mode must be on). Use this for installs, test runs, git commands, or anything else you'd normally type into a terminal.

    Do NOT use this to launch a native desktop application like Chrome,
    Notepad, or the Calculator just because the user asked you to "open"
    something -- use the open_app tool for that instead. open_app
    launches the real application too, but tracks it as one of your own
    panels (list_open_apps/minimize_app/restore_app/close_app), the same
    way the IDE itself already is -- a plain terminal launch wouldn't be
    tracked that way, and background-launching a GUI app from a terminal
    command can also leave this call hanging/timing out waiting for a
    process that never exits. This tool is for real command-line work:
    installs, builds, git, running the project, anything you'd actually
    type into a terminal.

    Args:
        command: The shell command to run, e.g. "python -m pip install requests".
        timeout_seconds: How long to wait before returning partial output.
            The command keeps running in the terminal regardless — check
            back with ide_get_terminal_output. Defaults to 60 seconds.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        return _ide_app.run_terminal_command(command, timeout=timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        return f"Error running that command in the IDE: {exc}"


def ide_clone_repository(url: str, destination_folder: str = "") -> str:
    """Clone a Git repository and open it as the IDE's workspace (Agent Mode must be on).

    Runs `git clone` visibly in the IDE's integrated terminal and waits
    for it to finish, then opens the newly-cloned folder in the Explorer.

    Args:
        url: The repository's clone URL, e.g.
            "https://github.com/someuser/somerepo.git".
        destination_folder: Optional existing folder to clone into (the
            repo gets its own new folder inside it, named after the
            repo). Defaults to the user's home folder.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    name = name or "repository"
    try:
        parent = os.path.abspath(os.path.expanduser(
            destination_folder) if destination_folder
            else os.path.expanduser("~"))
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        return f"Couldn't use '{destination_folder}' as a destination: {exc}"
    dest = os.path.join(parent, name)
    if os.path.exists(dest):
        return (f"'{name}' already exists in {parent} -- choose a "
                f"different destination folder or ask to open it instead.")
    try:
        output = _ide_app.run_terminal_command(
            f'git clone "{url}" "{dest}"', timeout=600)
    except Exception as exc:  # noqa: BLE001
        return f"Error cloning that repository: {exc}"
    if not os.path.isdir(os.path.join(dest, ".git")):
        return f"Clone did not complete successfully:\n{output}"

    def _do():
        app = _ide_app
        app.set_root(dest)
        app.refresh_explorer()
        app._index_workspace()

    _run_on_main(_do)
    return f"Cloned '{name}' and opened it in the IDE."


# ---------------------------------------------------------------------------
# IDE view / window controls (theme, zoom, opacity, panels)
# ---------------------------------------------------------------------------

def ide_set_theme(name: str) -> str:
    """Switch the IDE's whole color theme (Agent Mode must be on).

    Args:
        name: One of "grey", "black", or "white".
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        result = _run_on_main(lambda: _ide_app.set_theme(name))
        return f"Theme switched to {result}."
    except Exception as exc:  # noqa: BLE001
        return f"Error switching theme: {exc}"


def ide_toggle_view(panel: str) -> str:
    """Show/hide a part of the IDE's layout, same as the View menu or the sidebar/panel toggle icons (Agent Mode must be on).

    Args:
        panel: One of "sidebar" (the Explorer/Search/Source Control rail),
            "terminal" (the bottom panel), or "minimap".
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    panel = panel.strip().lower()
    actions = {
        "sidebar": _ide_app.toggle_sidebar if _ide_app else None,
        "side bar": _ide_app.toggle_sidebar if _ide_app else None,
        "terminal": _ide_app.toggle_panel if _ide_app else None,
        "panel": _ide_app.toggle_panel if _ide_app else None,
        "minimap": _ide_app.toggle_minimap if _ide_app else None,
    }
    fn = actions.get(panel)
    if fn is None:
        return "Unknown panel — use 'sidebar', 'terminal', or 'minimap'."
    try:
        _run_on_main(fn)
        return f"Toggled the {panel}."
    except Exception as exc:  # noqa: BLE001
        return f"Error toggling that panel: {exc}"


def ide_show_sidebar(view: str) -> str:
    """Switch which view the IDE's side bar is showing, same as clicking an Activity Bar icon on the left edge, and makes sure the side bar is actually visible (unlike ide_toggle_view, this never hides it even if that view happens to already be showing) (Agent Mode must be on).

    Args:
        view: One of "explorer" (file tree), "search" (search-in-files),
            "git" (Source Control -- a read-only changed-files list plus
            "Initialize Repository"; actual staging/committing is done
            with the ide_git_* tools or ide_run_terminal_command, not
            buttons here), "run" (Run and Debug -- just a "Run Python
            File" shortcut, there is no real breakpoint debugger), or
            "extensions" (a static, non-functional display of example
            extensions -- nothing can actually be installed from it).
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    view = view.strip().lower()
    aliases = {"source control": "git", "scm": "git",
               "run and debug": "run", "debug": "run"}
    view = aliases.get(view, view)
    if view not in ("explorer", "search", "git", "run", "extensions"):
        return ("Unknown view — use 'explorer', 'search', 'git', 'run', "
                "or 'extensions'.")
    try:
        def _do():
            if not _ide_app.sidebar_visible:
                _ide_app.toggle_sidebar()
            _ide_app.sidebar.show(view)
        _run_on_main(_do)
        return f"Side bar is now showing {view}."
    except Exception as exc:  # noqa: BLE001
        return f"Error switching the side bar view: {exc}"


def ide_open_in_browser() -> str:
    """Open the current HTML file, or the IDE's currently running dev server, in the system's default web browser -- same as Run > Open in Browser (Agent Mode must be on)."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        def _what():
            server_url = getattr(_ide_app, "server_url", None)
            path = _ide_app._current_path()
            html = path and path.lower().endswith((".html", ".htm", ".svg"))
            return server_url, (path if html else None)

        server_url, html_path = _run_on_main(_what)
        if not server_url and not html_path:
            return ("Nothing to open -- there's no running dev server and "
                    "the active tab isn't an HTML/SVG file.")
        _run_on_main(_ide_app.open_in_browser)
        return f"Opened {server_url or html_path} in the browser."
    except Exception as exc:  # noqa: BLE001
        return f"Error opening the browser: {exc}"


def ide_clear_terminal() -> str:
    """Clear the IDE's terminal/output panel, same as Terminal > Clear Terminal (Agent Mode must be on)."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        _run_on_main(_ide_app.panel.clear)
        return "Cleared the terminal."
    except Exception as exc:  # noqa: BLE001
        return f"Error clearing the terminal: {exc}"


def ide_list_tasks() -> str:
    """List every run/build/test task the IDE has auto-detected for the open workspace -- the same list Run > Tasks… shows (npm scripts, pytest, cargo, make targets, Docker, and more, depending on what's in the folder) (Agent Mode must be on). Use ide_run_task with one of these exact labels to run a specific one."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        tasks = _run_on_main(_ide_app.all_tasks)
    except Exception as exc:  # noqa: BLE001
        return f"Error listing tasks: {exc}"
    if not tasks:
        return ("No tasks detected for this workspace. ide_run_file still "
                "works for running whatever's in the active tab directly.")
    return "\n".join(f"- {t['label']}  [{t['kind']}]  ({t['cmd']})"
                     for t in tasks)


def ide_run_task(label: str) -> str:
    """Run one specific auto-detected task by name (e.g. an npm script like "test" or "lint", a Makefile target, pytest, cargo build, ...), streaming its output into the IDE's terminal panel exactly like Run > Tasks… would (Agent Mode must be on). Call ide_list_tasks first to see the exact labels available in this workspace -- ide_run_file/ide_run_project/ide_build_project only cover the single most obvious run/build task, not every task a project can have.

    Args:
        label: The task's label as shown by ide_list_tasks (e.g.
            "npm: test"), or just a distinctive fragment of it (e.g.
            "test") if that matches exactly one task.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    needle = (label or "").strip().lower()
    if not needle:
        return "Give a task label — call ide_list_tasks to see them."
    try:
        tasks = _run_on_main(_ide_app.all_tasks)
    except Exception as exc:  # noqa: BLE001
        return f"Error listing tasks: {exc}"
    if not tasks:
        return "No tasks detected for this workspace."
    exact = [t for t in tasks if t["label"].lower() == needle]
    matches = exact or [t for t in tasks if needle in t["label"].lower()]
    if not matches:
        return (f"No task matches '{label}'. Call ide_list_tasks to see "
                f"the exact labels available.")
    if len(matches) > 1:
        names = ", ".join(t["label"] for t in matches)
        return (f"More than one task matches '{label}': {names}. Ask the "
                f"user which one they mean before running anything.")
    task = matches[0]
    try:
        _run_on_main(lambda: _ide_app.run_task(task))
        return f"Running '{task['label']}' — check the terminal for output."
    except Exception as exc:  # noqa: BLE001
        return f"Error running that task: {exc}"


def ide_zoom(action: str) -> str:
    """Change the editor's font size, same as Ctrl+=/Ctrl+-/Ctrl+0 (Agent Mode must be on).

    Args:
        action: One of "in" (bigger text), "out" (smaller text), or
            "reset" (back to default size).
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    action = action.strip().lower()
    try:
        if action in ("in", "zoom in", "increase"):
            _run_on_main(lambda: _ide_app.zoom(1))
        elif action in ("out", "zoom out", "decrease"):
            _run_on_main(lambda: _ide_app.zoom(-1))
        elif action in ("reset", "default"):
            _run_on_main(_ide_app.reset_zoom)
        else:
            return "Unknown zoom action — use 'in', 'out', or 'reset'."
        return f"Zoomed {action}."
    except Exception as exc:  # noqa: BLE001
        return f"Error zooming: {exc}"


def ide_set_opacity(action: str) -> str:
    """Make the IDE window more see-through or more solid, same as Ctrl+Shift+-/Ctrl+Shift+= (Agent Mode must be on).

    Args:
        action: One of "more_transparent" or "more_opaque".
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    action = action.strip().lower()
    try:
        if action in ("more_transparent", "more transparent", "transparent"):
            _run_on_main(lambda: _ide_app.fade(-0.04))
        elif action in ("more_opaque", "more opaque", "opaque", "solid"):
            _run_on_main(lambda: _ide_app.fade(0.04))
        else:
            return "Unknown action — use 'more_transparent' or 'more_opaque'."
        pct = round(_ide_app.opacity * 100)
        return f"Opacity is now {pct}%."
    except Exception as exc:  # noqa: BLE001
        return f"Error changing opacity: {exc}"


def ide_toggle_always_on_top() -> str:
    """Toggle whether the IDE window stays above every other window (Agent Mode must be on)."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        _run_on_main(_ide_app.toggle_topmost)
        return "Toggled always-on-top."
    except Exception as exc:  # noqa: BLE001
        return f"Error toggling always-on-top: {exc}"


def ide_toggle_maximize() -> str:
    """Maximize the IDE window, or restore it if it's already maximized (Agent Mode must be on)."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        _run_on_main(_ide_app.toggle_maximize)
        return "Toggled maximize."
    except Exception as exc:  # noqa: BLE001
        return f"Error toggling maximize: {exc}"


# ---------------------------------------------------------------------------
# IDE editor mechanics (undo/redo, cut/copy/paste, find & replace, tabs)
# ---------------------------------------------------------------------------

def ide_undo() -> str:
    """Undo the last edit in the IDE's active editor tab, same as Ctrl+Z (Agent Mode must be on)."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        _run_on_main(_ide_app._undo)
        return "Undid the last edit."
    except Exception as exc:  # noqa: BLE001
        return f"Error undoing: {exc}"


def ide_redo() -> str:
    """Redo the last undone edit in the IDE's active editor tab, same as Ctrl+Y (Agent Mode must be on)."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        _run_on_main(_ide_app._redo)
        return "Redid the last edit."
    except Exception as exc:  # noqa: BLE001
        return f"Error redoing: {exc}"


def ide_editor_action(action: str) -> str:
    """Perform a basic editing action in the IDE's active editor tab, same as the Edit/Selection menu (Agent Mode must be on).

    Args:
        action: One of "cut", "copy", "paste", "select_all",
            "duplicate_line", "move_line_up", or "move_line_down".
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    action = action.strip().lower()
    try:
        if action == "cut":
            _run_on_main(lambda: _ide_app.editor.text.event_generate("<<Cut>>"))
        elif action == "copy":
            _run_on_main(lambda: _ide_app.editor.text.event_generate("<<Copy>>"))
        elif action == "paste":
            _run_on_main(lambda: _ide_app.editor.text.event_generate("<<Paste>>"))
        elif action == "select_all":
            _run_on_main(_ide_app._select_all)
        elif action == "duplicate_line":
            _run_on_main(_ide_app._duplicate_line)
        elif action == "move_line_up":
            _run_on_main(lambda: _ide_app._move_line(-1))
        elif action == "move_line_down":
            _run_on_main(lambda: _ide_app._move_line(1))
        else:
            return ("Unknown action — use 'cut', 'copy', 'paste', "
                    "'select_all', 'duplicate_line', 'move_line_up', or "
                    "'move_line_down'.")
        return f"Did: {action}."
    except Exception as exc:  # noqa: BLE001
        return f"Error performing that editor action: {exc}"


def ide_goto_line(line: int) -> str:
    """Move the cursor to a specific line number in the IDE's active editor tab, same as Ctrl+G (Agent Mode must be on).

    Args:
        line: The 1-based line number to jump to.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        _run_on_main(lambda: _ide_app.goto_line(int(line)))
        return f"Jumped to line {line}."
    except Exception as exc:  # noqa: BLE001
        return f"Error going to that line: {exc}"


def ide_find_replace(find_text: str, replace_text: str = "",
                     replace_all: bool = False) -> str:
    """Find (and optionally replace) text in the IDE's active editor tab, same as Ctrl+F / Ctrl+H (Agent Mode must be on). Works on the live, possibly-unsaved buffer — use ide_edit_file instead for edits that should also be saved straight to disk.

    Args:
        find_text: The text to search for in the currently open file.
        replace_text: If given (even an empty string), replaces matches
            with this text.
        replace_all: If true (and replace_text was given), replaces every
            match; otherwise just reports how many matches were found.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."

    def _do():
        buf = _ide_app.current_buffer()
        if not buf or buf.get("kind") != "file":
            return "no_file"
        ed = _ide_app.editor
        ed.show_find(replace=bool(replace_text) or replace_all)
        ed.fe.delete(0, "end")
        ed.fe.insert(0, find_text)
        if ed.re is not None:
            ed.re.delete(0, "end")
            ed.re.insert(0, replace_text)
        ed.do_find()
        count = len(getattr(ed, "_matches", []) or [])
        if replace_all and find_text:
            ed.replace_all()
            ed._after_edit()
        return count

    try:
        result = _run_on_main(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error searching/replacing: {exc}"
    if result == "no_file":
        return "No file is open in the editor to search."
    if replace_all and find_text:
        return f"Replaced every occurrence of '{find_text}' ({result} found)."
    return f"Found {result} occurrence(s) of '{find_text}'."


def ide_open_file(path: str, line: int = 0) -> str:
    """Open (or just bring to the front, if already open) a file as a real, visible tab in the IDE's editor -- same as double-clicking it in the Explorer (Agent Mode must be on).

    This is the one to use whenever a human would expect to actually
    *see* the file appear on screen (e.g. "open main.py", "show me that
    image", "pull up the PDF") -- ide_read_file only returns text into
    the conversation and never touches the UI at all. Handles plain text
    files, images (opened in the built-in image viewer), and PDFs
    (rendered if a renderer is available, text extracted either way) the
    same way the UI's own Explorer double-click does. Binary files of
    any other kind open as a withheld-content placeholder tab rather
    than raw garbage, exactly like clicking them manually would.

    Args:
        path: Path, relative to the open workspace folder (or absolute),
            of the file to open.
        line: If given (and the file is text), moves the cursor to this
            1-based line number once it's open, same as ide_goto_line.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        full = _ide_app.fs.resolve(path)
        if not os.path.exists(full):
            return f"'{path}' doesn't exist in the workspace."
        _run_on_main(lambda: _ide_app.open_file(full, line or None))
        where = f" and jumped to line {line}" if line else ""
        return f"Opened '{path}' in the editor{where}."
    except Exception as exc:  # noqa: BLE001
        return f"Error opening that file in the IDE: {exc}"


def ide_switch_tab(which: str) -> str:
    """Switch focus to an already-open tab without closing anything else (Agent Mode must be on).

    Args:
        which: The name/path of the open tab to switch to (e.g.
            "notes.txt"), or its 1-based position among currently open
            tabs (e.g. "2"). Call ide_list_open_tabs first if you're not
            sure what's open or which one the user means. If the name
            you pass matches more than one open tab, nothing switches
            and the matches are listed back instead of guessing.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    which_raw = which.strip()
    which_l = which_raw.lower()
    try:
        if which_raw.isdigit():
            idx = int(which_raw) - 1

            def _by_pos():
                if not (0 <= idx < len(_ide_app.buffers)):
                    return None
                _ide_app.switch_tab(idx)
                return _ide_app.buffers[idx].get("name")

            name = _run_on_main(_by_pos)
            if name is None:
                return (f"There's no tab #{which_raw} -- call "
                        f"ide_list_open_tabs to see what's actually open.")
            return f"Switched to '{name}'."

        def _find_matches():
            return [
                i for i, b in enumerate(_ide_app.buffers)
                if which_l in (b.get("name") or "").lower()
                or which_l in (b.get("path") or "").lower()
            ]

        matches = _run_on_main(_find_matches)
        if not matches:
            return (f"No open tab matches '{which_raw}'. Call "
                    f"ide_list_open_tabs to see what's actually open.")
        if len(matches) > 1:
            def _names():
                return [_ide_app.buffers[i].get("name") for i in matches]
            names = _run_on_main(_names)
            return (f"More than one open tab matches '{which_raw}': "
                    f"{', '.join(names)}. Ask the user which one they "
                    f"mean before switching.")
        idx = matches[0]
        _run_on_main(lambda: _ide_app.switch_tab(idx))
        return f"Switched to '{which_raw}'."
    except Exception as exc:  # noqa: BLE001
        return f"Error switching tab: {exc}"


def ide_get_active_tab_content() -> str:
    """Read the currently active editor tab's content exactly as it looks on screen right now, including any unsaved edits the human has typed but not saved yet (Agent Mode must be on).

    Use this instead of ide_read_file when you need to see what's
    actually on screen this instant -- ide_read_file only ever reads
    what's already on disk, so it would miss live, unsaved changes.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."

    def _do():
        buf = _ide_app.current_buffer()
        if not buf:
            return None
        if buf.get("kind") == "file" and _ide_app.editor.text.winfo_ismapped():
            content = _ide_app.editor.text.get("1.0", "end-1c")
        else:
            content = buf.get("content", "")
        return {
            "name": buf.get("name"), "path": buf.get("path"),
            "modified": bool(buf.get("modified")), "content": content,
        }

    try:
        info = _run_on_main(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error reading the active tab: {exc}"
    if info is None:
        return "No tab is open right now."
    loc = info["path"] or "(not yet saved to disk)"
    dirty = " (unsaved changes)" if info["modified"] else ""
    return f"{info['name']} — {loc}{dirty}\n\n{info['content']}"


def ide_save_file() -> str:
    """Save the currently active editor tab to disk, same as Ctrl+S -- captures the human's live, unsaved typing exactly as it appears on screen (Agent Mode must be on). Use ide_write_file instead if you already know the exact content you want on disk and there's no in-progress human edit to preserve.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        def _do():
            buf = _ide_app.current_buffer()
            name = buf.get("name") if buf else None
            ok = _ide_app.save_file()
            return ok, name
        ok, name = _run_on_main(_do)
        if ok:
            return f"Saved '{name}'."
        return ("Couldn't save -- either no file tab is open, it's a "
                "read-only extracted-text view, or it needs a Save As "
                "location (ask the user where to save it).")
    except Exception as exc:  # noqa: BLE001
        return f"Error saving: {exc}"


def ide_save_all() -> str:
    """Save every open tab that has unsaved changes and a known file path, same as File > Save All (Agent Mode must be on)."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        n = _run_on_main(_ide_app.save_all)
        return f"Saved {n} file(s)." if n else "Nothing needed saving."
    except Exception as exc:  # noqa: BLE001
        return f"Error saving all: {exc}"


def ide_list_open_tabs() -> str:
    """List every tab currently open in the IDE's editor -- name, path (or "not yet saved" for an untitled buffer), whether it has unsaved changes, and which one is active right now (Agent Mode must be on).

    Call this before closing/acting on "a tab" or "the file" whenever the
    user didn't clearly say which one they mean and more than one is
    open -- list them out and ask the user to pick before doing anything,
    rather than guessing which tab they meant.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."

    def _do():
        return [
            {
                "name": b.get("name"),
                "path": b.get("path"),
                "modified": bool(b.get("modified")),
                "active": i == _ide_app.current,
            }
            for i, b in enumerate(_ide_app.buffers)
        ]

    try:
        tabs = _run_on_main(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error listing open tabs: {exc}"
    if not tabs:
        return "No tabs are open right now."
    lines = []
    for t in tabs:
        marker = "-> " if t["active"] else "   "
        dirty = " (unsaved changes)" if t["modified"] else ""
        loc = t["path"] or "(not yet saved to disk)"
        lines.append(f"{marker}{t['name']} — {loc}{dirty}")
    return "\n".join(lines)


def _read_own_skill_file(filename, label):
    """Shared helper for the two tools below: reads a named .md file next
    to this script (Friday's own repo root -- the same place
    personality.md/development_skill.md/etc. already live), not from the
    currently open IDE workspace (which is some unrelated project's
    folder the vast majority of the time a frontend build is actually
    happening). Returns a clear, non-crashing message instead of raising
    if the file is ever missing, matching the same spirit as
    agent_overlay.py's own _load_development_skill()/_load_thinking_skills()
    (additive, never a hard dependency) -- the one difference being that
    here a missing file really is worth telling the model about, since
    it was asked for by name on purpose rather than loaded silently.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    if not os.path.exists(path):
        return (f"{label} ('{filename}') isn't present in this install -- "
                "nothing to load. Proceed using development_skill.md's "
                "general engineering standard and your own best judgment.")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except Exception as exc:  # noqa: BLE001
        return f"Error reading {label} ('{filename}'): {exc}"
    return content or f"{label} ('{filename}') exists but is currently empty."


def ide_get_frontend_skill() -> str:
    """Load FRONTEND_SKILL.md -- Friday's full professional frontend
    operating standard (UX strategy, information architecture, visual
    direction, responsive/accessible implementation, component states,
    performance, and a validation protocol) for websites, web apps,
    PWAs, and mobile UI (Agent Mode must be on).

    Call this once, near the start of any task that is actually a
    frontend build or a meaningful frontend change -- a new page,
    component, layout, or visual redesign -- before writing code, the
    same way a professional engineer would pull up the team's frontend
    standards doc before starting that kind of work. Not needed for
    small copy/content tweaks, pure backend/logic work, or tasks with no
    user-facing UI at all. This is deliberately NOT preloaded into your
    standing instructions the way development_skill.md is: it's sizeable
    (tens of thousands of tokens), and loading it for every single
    request -- including ones with nothing to do with frontend work --
    would waste context for no benefit the rest of the time. Fetch it
    yourself, on demand, exactly when a task actually calls for it. Its
    own guidance on validating things you may not have the tooling for
    in this sandbox (no real screen reader, no real device lab) still
    applies: build to the standard regardless, then report plainly which
    checks you could and couldn't actually run here -- never claim a
    check passed that didn't happen.

    See also ide_get_frontend_design_research() for the evidentiary
    research/citations this standard is built on, useful when you need
    to justify a specific design decision rather than just follow the
    rule.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    return _read_own_skill_file("FRONTEND_SKILL.md", "Friday's frontend skill")


def ide_get_backend_skill() -> str:
    """Load BACKEND_SKILL.md -- Friday's professional backend operating
    standard (API design, data flow, auth, error handling, validation
    protocol), the backend sibling of ide_get_frontend_skill() (Agent
    Mode must be on).

    Call this once, near the start of any task that is actually a
    backend build or a meaningful backend change -- an API, a server,
    business logic, auth, a service layer -- before writing code, same
    reasoning as ide_get_frontend_skill(): it's sizeable and only
    sometimes relevant, so it's fetched on demand rather than preloaded.

    BACKEND_SKILL.md may not exist in this install yet (it's supplied by
    the user the same way FRONTEND_SKILL.md was) -- if so this returns a
    plain, non-crashing message saying so. That is not an error: proceed
    using development_skill.md's general engineering standard and your
    own best professional judgment for backend work until the real
    document is supplied, same as any other optional skill file.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    return _read_own_skill_file("BACKEND_SKILL.md", "Friday's backend skill")


def ide_get_storage_skill() -> str:
    """Load STORAGE_SKILL.md -- Friday's professional storage/database
    operating standard (schema design, migrations, query/indexing
    discipline, data integrity, validation protocol), the storage/
    database sibling of ide_get_frontend_skill() (Agent Mode must be
    on).

    Call this once, near the start of any task that is actually a
    storage/database build or a meaningful schema change -- designing
    tables/collections, writing migrations, wiring an ORM, persistence
    logic -- before writing code, same reasoning as
    ide_get_frontend_skill(): sizeable and only sometimes relevant, so
    it's fetched on demand rather than preloaded.

    STORAGE_SKILL.md may not exist in this install yet (it's supplied by
    the user the same way FRONTEND_SKILL.md was) -- if so this returns a
    plain, non-crashing message saying so. That is not an error: proceed
    using development_skill.md's general engineering standard and your
    own best professional judgment for storage/database work until the
    real document is supplied, same as any other optional skill file.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    return _read_own_skill_file("STORAGE_SKILL.md", "Friday's storage/database skill")


def ide_get_frontend_design_research() -> str:
    """Load UI_UX_FRONTEND_DESIGN_RESEARCH.md -- the companion research
    document behind FRONTEND_SKILL.md: durable UX/accessibility/
    performance standards versus 2026 trend signals, sourced from W3C/
    MDN/web.dev/Nielsen Norman Group and similar, with the reasoning and
    citations FRONTEND_SKILL.md's rules are distilled from (Agent Mode
    must be on).

    Call this when you need the underlying evidence or a citation to
    justify a specific design decision (for example, deciding whether a
    glass/neumorphic treatment is appropriate here, or what a WCAG
    criterion actually requires) -- not as a routine first step the way
    ide_get_frontend_skill() is. Same reasoning for why this isn't
    preloaded into your standing instructions: it's large, and only
    occasionally relevant.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    return _read_own_skill_file(
        "UI_UX_FRONTEND_DESIGN_RESEARCH.md", "Friday's frontend design research")


_BUILD_STATUS_PHASES = ("frontend", "backend", "storage")
_BUILD_STATUS_STATES = ("in_progress", "done", "blocked")


def ide_report_build_status(phase: str, status: str, detail: str = "") -> str:
    """Update the IDE chat panel's persistent build-status checklist for
    one phase of a multi-layer development task (Agent Mode must be
    on). This is how the user keeps track of where a build actually is
    without having to read back through the whole conversation -- the
    checklist is a small, always-visible block in the chat panel, not
    another bubble added to the scrolling log.

    `phase` must be one of "frontend", "backend", "storage" -- the three
    layers development_skill.md's Build Protocol separates every real
    development task into (storage covers the database/persistence
    layer). `status` must be one of "in_progress", "done", "blocked" --
    there's no need to report "not_started" explicitly, every phase
    starts in that state automatically. `detail` is an optional short
    note shown next to the phase (a one-line plan when starting, a
    one-line summary of what was actually built when finishing, or the
    reason when blocked) -- keep it to a few words, it renders inline
    next to the phase row, not as its own paragraph.

    Call this at the start of each phase ("in_progress"), the moment it
    actually finishes ("done"), and immediately if something stops a
    phase from proceeding ("blocked") -- not after every single file,
    which would be noisy without adding real information. This is in
    addition to, never a replacement for, narrating the work normally;
    see development_skill.md's Build Protocol section for the full
    contract.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    phase_norm = (phase or "").strip().lower()
    status_norm = (status or "").strip().lower()
    if phase_norm not in _BUILD_STATUS_PHASES:
        return (
            f"Error: phase must be one of {_BUILD_STATUS_PHASES!r}, "
            f"got {phase!r}."
        )
    if status_norm not in _BUILD_STATUS_STATES:
        return (
            f"Error: status must be one of {_BUILD_STATUS_STATES!r}, "
            f"got {status!r}."
        )
    report_ide_build_status(phase_norm, status_norm, (detail or "").strip())
    return f"Build status updated: {phase_norm} -> {status_norm}."


def ide_close_tab(which: str = "current") -> str:
    """Close one or more open editor tabs (Agent Mode must be on).

    If a tab being closed has unsaved changes, this shows the exact same
    "Save changes before closing?" prompt the UI's own close button
    would — so the call blocks until a human answers it. Save first
    (ide_write_file) if you want a guaranteed silent close.

    Args:
        which: One of "current" (just the active tab), "all" (every open
            tab), "others" (every tab except the active one), or the
            name/path of one specific open tab to close (e.g.
            "notes.txt") -- call ide_list_open_tabs first if you're not
            sure what's open or which one the user means. If the name
            you pass matches more than one open tab, nothing is closed
            and the matches are listed back so you can ask the user to
            be more specific instead of guessing.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    which_raw = which.strip()
    which = which_raw.lower()
    try:
        if which == "current":
            _run_on_main(_ide_app.close_current_tab)
            return "Closed current tab(s)."
        if which == "all":
            _run_on_main(_ide_app.close_all_tabs)
            return "Closed all tab(s)."
        if which == "others":
            _run_on_main(lambda: _ide_app.close_others(_ide_app.current))
            return "Closed others tab(s)."

        def _find_matches():
            return [
                i for i, b in enumerate(_ide_app.buffers)
                if which in (b.get("name") or "").lower()
                or which in (b.get("path") or "").lower()
            ]

        matches = _run_on_main(_find_matches)
        if not matches:
            return (f"No open tab matches '{which_raw}'. Call "
                     f"ide_list_open_tabs to see what's actually open "
                     f"before trying again.")
        if len(matches) > 1:
            def _names():
                return [_ide_app.buffers[i].get("name") for i in matches]
            names = _run_on_main(_names)
            return (f"More than one open tab matches '{which_raw}': "
                     f"{', '.join(names)}. Ask the user which one they "
                     f"mean before closing anything.")
        idx = matches[0]
        _run_on_main(lambda: _ide_app.close_tab(idx))
        return f"Closed '{which_raw}'."
    except Exception as exc:  # noqa: BLE001
        return f"Error closing tab(s): {exc}"


# ---------------------------------------------------------------------------
# IDE explorer extras
# ---------------------------------------------------------------------------

def ide_reveal_in_file_manager(path: str) -> str:
    """Open the OS's native file explorer/finder with a file or folder selected, same as the Explorer's 'Reveal in File Explorer' (Agent Mode must be on).

    Args:
        path: Path, relative to the open workspace folder (or absolute),
            of the file/folder to reveal.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        full = _ide_app.fs.resolve(path)
        _run_on_main(lambda: _ide_app.reveal_in_file_manager(full))
        return f"Revealed '{path}' in the OS file explorer."
    except Exception as exc:  # noqa: BLE001
        return f"Error revealing that path: {exc}"


def ide_open_in_integrated_terminal(path: str) -> str:
    """Open the IDE's terminal panel with its working directory set to a given folder, same as the Explorer's 'Open in Integrated Terminal' (Agent Mode must be on). Use ide_run_terminal_command afterwards to actually run something there.

    Args:
        path: Folder, relative to the open workspace (or absolute), to
            set as the terminal's working directory.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        full = _ide_app.fs.resolve(path)
        _run_on_main(lambda: _ide_app.open_in_terminal(full))
        return f"Terminal is now at '{path}'."
    except Exception as exc:  # noqa: BLE001
        return f"Error opening that in the terminal: {exc}"


def ide_copy_path(path: str, relative: bool = False) -> str:
    """Copy a file or folder's filesystem path to the clipboard, same as the Explorer's 'Copy Path' / 'Copy Relative Path' (Agent Mode must be on).

    Args:
        path: Path, relative to the open workspace folder (or absolute),
            of the file/folder whose path should be copied.
        relative: If true, copies the path relative to the workspace root
            instead of the full absolute path.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        full = _ide_app.fs.resolve(path)
        _run_on_main(lambda: _ide_app.copy_path(full, bool(relative)))
        value = (os.path.relpath(full, _ide_app.root_dir) if relative
                 else full)
        return f"Copied to the clipboard: {value}"
    except Exception as exc:  # noqa: BLE001
        return f"Error copying that path: {exc}"


# ---------------------------------------------------------------------------
# IDE source control (git) — first-class tools, all run visibly in the
# IDE's own integrated terminal via run_terminal_command so the user sees
# exactly what ran, same as the clone tool above.
# ---------------------------------------------------------------------------

def _ide_git(cmd: str, timeout: float = 60.0) -> str:
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        return _ide_app.run_terminal_command(cmd, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return f"Error running that git command: {exc}"


def ide_git_init() -> str:
    """Initialize a new Git repository in the IDE's open workspace, same as the Source Control panel's 'Initialize Repository' button (Agent Mode must be on)."""
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        _run_on_main(_ide_app.git_init_repository)
        return "Initialized a Git repository in the workspace."
    except Exception as exc:  # noqa: BLE001
        return f"Error initializing the repository: {exc}"


def ide_git_status() -> str:
    """Show which files are changed/staged/untracked in the IDE's open workspace, same as the Source Control panel (Agent Mode must be on)."""
    return _ide_git("git status")


def ide_git_add(paths: str = "") -> str:
    """Stage file(s) for commit (Agent Mode must be on).

    Args:
        paths: Space-separated paths to stage, relative to the workspace.
            Leave empty to stage every changed file ("git add -A").
    """
    paths = (paths or "").strip()
    return _ide_git(f"git add {paths}" if paths else "git add -A")


def ide_git_commit(message: str) -> str:
    """Commit every currently staged change (Agent Mode must be on).

    Args:
        message: The commit message.
    """
    safe = (message or "").replace('"', "'")
    return _ide_git(f'git commit -m "{safe}"')


def ide_git_push(remote: str = "origin", branch: str = "") -> str:
    """Push commits to a remote (Agent Mode must be on).

    Args:
        remote: The remote name. Defaults to "origin".
        branch: The branch to push. Defaults to the current branch.
    """
    cmd = f"git push {remote} {branch}".strip()
    return _ide_git(cmd, timeout=120.0)


def ide_git_pull(remote: str = "origin", branch: str = "") -> str:
    """Pull and merge changes from a remote (Agent Mode must be on).

    Args:
        remote: The remote name. Defaults to "origin".
        branch: The branch to pull. Defaults to the current branch.
    """
    cmd = f"git pull {remote} {branch}".strip()
    return _ide_git(cmd, timeout=120.0)


def ide_git_branch(name: str = "") -> str:
    """List branches, or create a new one (Agent Mode must be on).

    Args:
        name: Leave empty to list every branch. Give a name to create a
            new branch with that name (without switching to it — use
            ide_git_checkout with create=true to create and switch).
    """
    name = (name or "").strip()
    return _ide_git(f"git branch {name}" if name else "git branch -a")


def ide_git_checkout(branch: str, create: bool = False) -> str:
    """Switch to a branch, optionally creating it first (Agent Mode must be on).

    Args:
        branch: The branch name to switch to.
        create: If true, creates the branch before switching to it
            ("git checkout -b").
    """
    flag = "-b " if create else ""
    return _ide_git(f"git checkout {flag}{branch}")


# ---------------------------------------------------------------------------
# Act Script -- Friday's heavier multi-model orchestration system
# ---------------------------------------------------------------------------

def ide_run_act_script(task_description: str, mode: str = "auto") -> str:
    """Runs Friday's ACT Script system on a task that's too deep for a single model call (Agent Mode must be on).

    Use this for: dependent multi-step builds/refactors/migrations where
    each step's real output must exist before the next can safely start
    (routes to Sequential Rotation); breadth/research questions or
    debugging hypotheses that benefit from several independent takes
    merged into one (routes to Fan-Out); or whole-artifact writing
    (reports, strategy docs) that benefits from drafting, cold critique,
    and revision before it ships (routes to Debate). It rotates Friday's
    real providers (Gemini/Groq/Mistral) against each other so whichever
    model reviews/critiques/judges a piece of work always differs from
    whichever model produced it. This can take a while -- several real
    model calls happen underneath -- so only reach for it when a task
    actually warrants that, not for simple questions or one-line edits.

    Args:
        task_description: The task, in full -- the same level of detail
            you'd want a careful coworker to have before starting.
        mode: "auto" (default -- classifies the task itself and picks
            the right pipeline), or force one of "sequential", "fan_out",
            "debate" directly.
    """
    if not is_agent_mode_on():
        return "Agent Mode / the IDE isn't open right now."
    try:
        import act_script
        return act_script.run_act_script(task_description, mode=mode)
    except Exception as exc:  # noqa: BLE001
        return f"Act Script error: {exc}"


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def get_current_datetime() -> str:
    """Get the current local date, time, and day of the week."""
    now = datetime.datetime.now().astimezone()
    return now.strftime("%A, %B %d, %Y, %I:%M %p (UTC%z)")


# ---------------------------------------------------------------------------
# Web search (Tavily — search API built for AI agents)
# ---------------------------------------------------------------------------

def web_search(query: str) -> str:
    """Search the web for current information and return results with source links.

    Use this for anything time-sensitive, recent, or outside your training
    data — news, current events, prices, current versions of software,
    or any fact you're not confident is still accurate.

    Args:
        query: The search query.
    """
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return (
            "Web search is unavailable: no TAVILY_API_KEY configured in "
            "the .env file. Let the user know they'd need to add a free "
            "Tavily API key (https://app.tavily.com) to enable it."
        )

    try:
        from tavily import TavilyClient
    except Exception as exc:  # noqa: BLE001
        return f"Web search is unavailable: tavily-python not installed ({exc})."

    try:
        client = TavilyClient(api_key=api_key)
        result = client.search(query=query, max_results=5, include_answer=True)
    except Exception as exc:  # noqa: BLE001
        return f"Web search failed: {exc}"

    lines = []
    answer = result.get("answer")
    if answer:
        lines.append(f"Quick answer: {answer}")

    for item in result.get("results", [])[:5]:
        title = item.get("title", "").strip()
        url = item.get("url", "").strip()
        snippet = (item.get("content") or "").strip()
        if len(snippet) > 300:
            snippet = snippet[:300].rstrip() + "..."
        lines.append(f"- {title}: {snippet} (source: {url})")

    if not lines:
        return "No results found."
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Real browser automation (Playwright) -- navigate, click, fill forms,
# read rendered content/console output. See browser_tools.py's own module
# docstring for the full design (especially the dedicated-thread Playwright
# bridge, same shape as _TkThreadBridge above). General-purpose, not
# ide_* scoped -- registered the same unrestricted way web_search already
# is, available from both the floating circle and the IDE's embedded chat
# panel.
# ---------------------------------------------------------------------------
from browser_tools import (  # noqa: E402
    browser_navigate,
    browser_click,
    browser_fill,
    browser_select_option,
    browser_press_key,
    browser_wait_for,
    browser_read_text,
    browser_get_html,
    browser_get_links,
    browser_evaluate,
    browser_get_console_logs,
    browser_screenshot,
    browser_go_back,
    browser_current_state,
    browser_close,
)


# ---------------------------------------------------------------------------
# Calendar (Google Calendar, OAuth — read + create events)
# ---------------------------------------------------------------------------

_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _calendar_paths():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return (
        os.path.join(base_dir, "credentials.json"),
        os.path.join(base_dir, "token.json"),
    )


def _get_calendar_service():
    """Returns (service, None) on success, or (None, friendly_error) on failure."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except Exception as exc:  # noqa: BLE001
        return None, (
            f"Calendar is unavailable: required packages not installed ({exc}). "
            "Run: python -m pip install -r requirements.txt"
        )

    creds_path, token_path = _calendar_paths()

    if not os.path.exists(creds_path):
        return None, (
            "Calendar isn't set up yet. To enable it, create an OAuth "
            "client (type: Desktop app) with the Google Calendar API "
            "enabled in Google Cloud Console, download it, and save it as "
            "credentials.json next to agent_overlay.py. See the README's "
            "Calendar setup section for the exact steps."
        )

    creds = None
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, _CALENDAR_SCOPES)
        except Exception:  # noqa: BLE001
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:  # noqa: BLE001
                creds = None

        if not creds or not creds.valid:
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    creds_path, _CALENDAR_SCOPES
                )
                # Opens the user's browser for a one-time consent screen.
                creds = flow.run_local_server(port=0)
            except Exception as exc:  # noqa: BLE001
                return None, f"Calendar sign-in failed or was cancelled: {exc}"

        try:
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        except Exception:  # noqa: BLE001
            pass  # non-fatal — it'll just prompt again next time

    try:
        service = build("calendar", "v3", credentials=creds)
    except Exception as exc:  # noqa: BLE001
        return None, f"Calendar is unavailable: {exc}"
    return service, None


def list_calendar_events(max_results: int = 10, days_ahead: int = 30) -> str:
    """List upcoming events from the user's Google Calendar.

    Args:
        max_results: Maximum number of events to return. Defaults to 10.
        days_ahead: Only include events starting within this many days
            from now. Defaults to 30.
    """
    service, err = _get_calendar_service()
    if err:
        return err

    now = datetime.datetime.now(datetime.timezone.utc)
    time_min = now.isoformat()
    time_max = (now + datetime.timedelta(days=days_ahead)).isoformat()

    try:
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        return f"Error listing calendar events: {exc}"

    events = events_result.get("items", [])
    if not events:
        return "No upcoming events found in that window."

    lines = []
    for ev in events:
        start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date"))
        summary = ev.get("summary", "(no title)")
        lines.append(f"- {start}: {summary}")
    return "\n".join(lines)


def create_calendar_event(
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    timezone_name: str = "",
) -> str:
    """Create a new event on the user's Google Calendar.

    Args:
        summary: Short title of the event.
        start_iso: Start date/time in ISO 8601 format, e.g. 2026-10-01T15:00:00.
        end_iso: End date/time in ISO 8601 format, e.g. 2026-10-01T16:00:00.
        description: Optional longer description of the event.
        timezone_name: Optional IANA timezone name, e.g. Africa/Lagos. If
            you know the user's timezone from context, pass it here;
            otherwise this defaults to UTC.
    """
    service, err = _get_calendar_service()
    if err:
        return err

    tz_name = timezone_name or "UTC"
    event_body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": tz_name},
        "end": {"dateTime": end_iso, "timeZone": tz_name},
    }
    try:
        created = service.events().insert(calendarId="primary", body=event_body).execute()
    except Exception as exc:  # noqa: BLE001
        return f"Error creating calendar event: {exc}"
    return f"Created event '{summary}'. Link: {created.get('htmlLink', '(none)')}"


# ---------------------------------------------------------------------------
# Memory — long-term facts/preferences, semantically searchable, and
# simple structured tasks. See memory.py's own module docstring for the
# full storage design (a folder of individually-encrypted files acting
# as the vector DB, the structured task store, and the "localStorage"-
# style key/value cache all at once). These are the agent-facing tool
# wrappers around it, same shape as every other tool in this file: plain
# functions, type hints, docstrings Gemini introspects directly, schemas
# below for Groq/Mistral.
# ---------------------------------------------------------------------------

import memory as _memory


def remember(text: str, category: str = "fact") -> str:
    """Saves something worth remembering long-term about the user — a
    fact, a stated preference, a one-off note — so it can be recalled
    automatically in later conversations, even in ones that never
    explicitly ask to look it up. Use this whenever the user shares
    something that sounds like it should stick (a preference, a detail
    about their life/work, a standing instruction), not for things only
    relevant to the current exchange.

    Args:
        text: the thing to remember, written as a clear, self-contained
            statement (e.g. "The user's work folder is ~/projects/acme",
            not just "that folder").
        category: a short label for what kind of memory this is, e.g.
            "fact", "preference". Defaults to "fact".
    """
    try:
        memory_id = _memory.remember(text, category=category)
    except ValueError as exc:
        return f"Couldn't save that: {exc}"
    return f"Remembered (#{memory_id}): {text}"


def recall(query: str) -> str:
    """Searches Friday's long-term memory for anything relevant to
    `query`, by meaning rather than exact wording — use this when the
    user asks something that might depend on a fact/preference they
    mentioned before (e.g. "what's my usual order" after once mentioning
    it weeks ago). Returns the most relevant saved memories, or says
    plainly that nothing relevant was found.

    Args:
        query: what to search memory for.
    """
    results = _memory.recall(query)
    if not results:
        return "Nothing relevant found in memory."
    lines = [f"#{r['id']}: {r['text']}" for r in results]
    return "Found in memory:\n" + "\n".join(lines)


def forget(which: str) -> str:
    """Deletes a saved memory. Pass either the exact memory number shown
    by remember()/recall() (e.g. "7"), or a word/phrase to search for —
    if that search matches more than one memory, this lists them and
    asks which one instead of guessing.

    Args:
        which: a memory id (as a number or numeric string), or text to
            search for among saved memories.
    """
    which = (which or "").strip()
    if which.isdigit():
        return ("Deleted that memory." if _memory.forget(int(which))
                else f"No memory #{which} found.")
    matches = _memory.recall(which, max_results=5)
    if not matches:
        return f"No memory matching '{which}' found."
    if len(matches) > 1:
        lines = [f"#{m['id']}: {m['text']}" for m in matches]
        return ("More than one memory matches — tell me the exact number:\n"
                 + "\n".join(lines))
    _memory.forget(matches[0]["id"])
    return f"Deleted: {matches[0]['text']}"


def add_task(text: str, due: str = "") -> str:
    """Adds a task/reminder for the user to Friday's task list.

    Args:
        text: what the task is.
        due: an optional due date/time, in whatever form the user gave
            it (e.g. "tomorrow", "Oct 10", "2026-10-10") — stored as
            plain text, not parsed into a strict date.
    """
    try:
        task_id = _memory.add_task(text, due_date=due)
    except ValueError as exc:
        return f"Couldn't add that task: {exc}"
    due_note = f" (due {due})" if due else ""
    return f"Added task #{task_id}: {text}{due_note}"


def list_tasks(status: str = "pending") -> str:
    """Lists the user's tasks.

    Args:
        status: "pending" (default, not yet done), "done", or "all".
    """
    tasks = _memory.list_tasks(status=status)
    if not tasks:
        label = "pending " if status == "pending" else ("done " if status == "done" else "")
        return f"No {label}tasks."
    lines = []
    for t in tasks:
        due_note = f" (due {t['due_date']})" if t["due_date"] else ""
        mark = "✓ " if t["status"] == "done" else ""
        lines.append(f"{mark}#{t['id']}: {t['text']}{due_note}")
    return "\n".join(lines)


def complete_task(which: str) -> str:
    """Marks a task done. Pass either the exact task number, or a
    word/phrase from its text — if that matches more than one pending
    task, this lists them and asks which one instead of guessing.

    Args:
        which: a task id (as a number or numeric string), or text to
            search for among pending tasks.
    """
    which = (which or "").strip()
    if which.isdigit():
        return (f"Marked task #{which} done." if _memory.complete_task(int(which))
                else f"No pending task #{which} found.")
    matches = _memory.find_tasks(which, status="pending")
    if not matches:
        return f"No pending task matching '{which}' found."
    if len(matches) > 1:
        lines = [f"#{m['id']}: {m['text']}" for m in matches]
        return ("More than one pending task matches — tell me the exact number:\n"
                 + "\n".join(lines))
    _memory.complete_task(matches[0]["id"])
    return f"Marked task #{matches[0]['id']} done: {matches[0]['text']}"


def delete_task(which: str) -> str:
    """Deletes a task outright (as opposed to marking it done). Pass
    either the exact task number, or a word/phrase from its text — same
    ambiguity rule as complete_task().

    Args:
        which: a task id (as a number or numeric string), or text to
            search for among all tasks (pending or done).
    """
    which = (which or "").strip()
    if which.isdigit():
        return (f"Deleted task #{which}." if _memory.delete_task(int(which))
                else f"No task #{which} found.")
    matches = _memory.find_tasks(which, status="all")
    if not matches:
        return f"No task matching '{which}' found."
    if len(matches) > 1:
        lines = [f"#{m['id']}: {m['text']}" for m in matches]
        return ("More than one task matches — tell me the exact number:\n"
                 + "\n".join(lines))
    _memory.delete_task(matches[0]["id"])
    return f"Deleted task #{matches[0]['id']}: {matches[0]['text']}"


# ---------------------------------------------------------------------------
# Gemini (automatic function calling — pass the plain callables directly)
# ---------------------------------------------------------------------------

GEMINI_TOOLS = [
    web_search,
    browser_navigate,
    browser_click,
    browser_fill,
    browser_select_option,
    browser_press_key,
    browser_wait_for,
    browser_read_text,
    browser_get_html,
    browser_get_links,
    browser_evaluate,
    browser_get_console_logs,
    browser_screenshot,
    browser_go_back,
    browser_current_state,
    browser_close,
    get_current_datetime,
    read_file,
    write_file,
    edit_file,
    list_directory,
    list_calendar_events,
    create_calendar_event,
    remember,
    recall,
    forget,
    add_task,
    list_tasks,
    complete_task,
    delete_task,
    agent_mode_on,
    open_app,
    list_open_apps,
    minimize_app,
    restore_app,
    maximize_app,
    close_app,
    type_in_app,
    save_app_file,
    agent_mode_off,
    ide_open_folder,
    ide_create_file,
    ide_write_file,
    ide_edit_file,
    ide_create_folder,
    ide_read_file,
    ide_list_folder,
    ide_workspace_tree,
    ide_exists,
    ide_rename,
    ide_copy,
    ide_move,
    ide_search_workspace,
    ide_analyze_file_for_deletion,
    ide_delete_file,
    ide_analyze_folder_for_deletion,
    ide_delete_folder,
    ide_run_file,
    ide_run_project,
    ide_build_project,
    ide_stop_task,
    ide_get_terminal_output,
    ide_run_terminal_command,
    ide_clone_repository,
    ide_set_theme,
    ide_show_sidebar,
    ide_toggle_view,
    ide_open_in_browser,
    ide_clear_terminal,
    ide_list_tasks,
    ide_run_task,
    ide_zoom,
    ide_set_opacity,
    ide_toggle_always_on_top,
    ide_toggle_maximize,
    ide_undo,
    ide_redo,
    ide_editor_action,
    ide_goto_line,
    ide_find_replace,
    ide_open_file,
    ide_switch_tab,
    ide_get_active_tab_content,
    ide_save_file,
    ide_save_all,
    ide_list_open_tabs,
    ide_get_frontend_skill,
    ide_get_frontend_design_research,
    ide_get_backend_skill,
    ide_get_storage_skill,
    ide_report_build_status,
    ide_close_tab,
    ide_reveal_in_file_manager,
    ide_open_in_integrated_terminal,
    ide_copy_path,
    ide_git_init,
    ide_git_status,
    ide_git_add,
    ide_git_commit,
    ide_git_push,
    ide_git_pull,
    ide_git_branch,
    ide_git_checkout,
    ide_run_act_script,
]


# ---------------------------------------------------------------------------
# Groq / Mistral (manual tool-call loop — OpenAI-style JSON schema)
# ---------------------------------------------------------------------------

# The actual schema list -- pure declarative data, no logic, no
# dependency on anything else here -- lives in tool_schemas.py now,
# split out purely to keep this file a manageable size. Imported under
# its exact original name so everything below (and anything reaching
# for `agent_tools.TOOL_SCHEMAS`) keeps working unchanged.
from tool_schemas import TOOL_SCHEMAS  # noqa: E402


TOOL_FUNCTIONS = {
    "web_search": web_search,
    "browser_navigate": browser_navigate,
    "browser_click": browser_click,
    "browser_fill": browser_fill,
    "browser_select_option": browser_select_option,
    "browser_press_key": browser_press_key,
    "browser_wait_for": browser_wait_for,
    "browser_read_text": browser_read_text,
    "browser_get_html": browser_get_html,
    "browser_get_links": browser_get_links,
    "browser_evaluate": browser_evaluate,
    "browser_get_console_logs": browser_get_console_logs,
    "browser_screenshot": browser_screenshot,
    "browser_go_back": browser_go_back,
    "browser_current_state": browser_current_state,
    "browser_close": browser_close,
    "get_current_datetime": get_current_datetime,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_directory": list_directory,
    "list_calendar_events": list_calendar_events,
    "create_calendar_event": create_calendar_event,
    "remember": remember,
    "recall": recall,
    "forget": forget,
    "add_task": add_task,
    "list_tasks": list_tasks,
    "complete_task": complete_task,
    "delete_task": delete_task,
    "agent_mode_on": agent_mode_on,
    "open_app": open_app,
    "list_open_apps": list_open_apps,
    "minimize_app": minimize_app,
    "restore_app": restore_app,
    "maximize_app": maximize_app,
    "close_app": close_app,
    "type_in_app": type_in_app,
    "save_app_file": save_app_file,
    "agent_mode_off": agent_mode_off,
    "ide_open_folder": ide_open_folder,
    "ide_create_file": ide_create_file,
    "ide_write_file": ide_write_file,
    "ide_edit_file": ide_edit_file,
    "ide_create_folder": ide_create_folder,
    "ide_read_file": ide_read_file,
    "ide_list_folder": ide_list_folder,
    "ide_workspace_tree": ide_workspace_tree,
    "ide_exists": ide_exists,
    "ide_rename": ide_rename,
    "ide_copy": ide_copy,
    "ide_move": ide_move,
    "ide_search_workspace": ide_search_workspace,
    "ide_analyze_file_for_deletion": ide_analyze_file_for_deletion,
    "ide_delete_file": ide_delete_file,
    "ide_analyze_folder_for_deletion": ide_analyze_folder_for_deletion,
    "ide_delete_folder": ide_delete_folder,
    "ide_run_file": ide_run_file,
    "ide_run_project": ide_run_project,
    "ide_build_project": ide_build_project,
    "ide_stop_task": ide_stop_task,
    "ide_get_terminal_output": ide_get_terminal_output,
    "ide_run_terminal_command": ide_run_terminal_command,
    "ide_clone_repository": ide_clone_repository,
    "ide_set_theme": ide_set_theme,
    "ide_show_sidebar": ide_show_sidebar,
    "ide_toggle_view": ide_toggle_view,
    "ide_open_in_browser": ide_open_in_browser,
    "ide_clear_terminal": ide_clear_terminal,
    "ide_list_tasks": ide_list_tasks,
    "ide_run_task": ide_run_task,
    "ide_zoom": ide_zoom,
    "ide_set_opacity": ide_set_opacity,
    "ide_toggle_always_on_top": ide_toggle_always_on_top,
    "ide_toggle_maximize": ide_toggle_maximize,
    "ide_undo": ide_undo,
    "ide_redo": ide_redo,
    "ide_editor_action": ide_editor_action,
    "ide_goto_line": ide_goto_line,
    "ide_find_replace": ide_find_replace,
    "ide_open_file": ide_open_file,
    "ide_switch_tab": ide_switch_tab,
    "ide_get_active_tab_content": ide_get_active_tab_content,
    "ide_save_file": ide_save_file,
    "ide_save_all": ide_save_all,
    "ide_list_open_tabs": ide_list_open_tabs,
    "ide_get_frontend_skill": ide_get_frontend_skill,
    "ide_get_frontend_design_research": ide_get_frontend_design_research,
    "ide_get_backend_skill": ide_get_backend_skill,
    "ide_get_storage_skill": ide_get_storage_skill,
    "ide_report_build_status": ide_report_build_status,
    "ide_close_tab": ide_close_tab,
    "ide_reveal_in_file_manager": ide_reveal_in_file_manager,
    "ide_open_in_integrated_terminal": ide_open_in_integrated_terminal,
    "ide_copy_path": ide_copy_path,
    "ide_git_init": ide_git_init,
    "ide_git_status": ide_git_status,
    "ide_git_add": ide_git_add,
    "ide_git_commit": ide_git_commit,
    "ide_git_push": ide_git_push,
    "ide_git_pull": ide_git_pull,
    "ide_git_branch": ide_git_branch,
    "ide_git_checkout": ide_git_checkout,
    "ide_run_act_script": ide_run_act_script,
}

# The IDE-specific tools only make sense — and are only worth the extra
# tokens — while Agent Mode is actually on. Sending every tool schema on
# every single request (even a plain "what time is it") bloats the
# tool-calling payload for no benefit the rest of the time, so
# get_active_gemini_tools()/get_active_tool_schemas() below trim the list
# back down whenever the IDE isn't open. `agent_mode_on` itself always
# stays available so the model can turn it on in the first place.
_AGENT_MODE_ONLY_TOOLS = {
    "agent_mode_off",
    "ide_open_folder",
    "ide_create_file",
    "ide_write_file",
    "ide_edit_file",
    "ide_create_folder",
    "ide_read_file",
    "ide_list_folder",
    "ide_workspace_tree",
    "ide_exists",
    "ide_rename",
    "ide_copy",
    "ide_move",
    "ide_search_workspace",
    "ide_analyze_file_for_deletion",
    "ide_delete_file",
    "ide_analyze_folder_for_deletion",
    "ide_delete_folder",
    "ide_run_file",
    "ide_run_project",
    "ide_build_project",
    "ide_stop_task",
    "ide_get_terminal_output",
    "ide_run_terminal_command",
    "ide_clone_repository",
    "ide_set_theme",
    "ide_show_sidebar",
    "ide_toggle_view",
    "ide_open_in_browser",
    "ide_clear_terminal",
    "ide_list_tasks",
    "ide_run_task",
    "ide_zoom",
    "ide_set_opacity",
    "ide_toggle_always_on_top",
    "ide_toggle_maximize",
    "ide_undo",
    "ide_redo",
    "ide_editor_action",
    "ide_goto_line",
    "ide_find_replace",
    "ide_open_file",
    "ide_switch_tab",
    "ide_get_active_tab_content",
    "ide_save_file",
    "ide_save_all",
    "ide_list_open_tabs",
    "ide_get_frontend_skill",
    "ide_get_frontend_design_research",
    "ide_get_backend_skill",
    "ide_get_storage_skill",
    "ide_report_build_status",
    "ide_close_tab",
    "ide_reveal_in_file_manager",
    "ide_open_in_integrated_terminal",
    "ide_copy_path",
    "ide_git_init",
    "ide_git_status",
    "ide_git_add",
    "ide_git_commit",
    "ide_git_push",
    "ide_git_pull",
    "ide_git_branch",
    "ide_git_checkout",
    "ide_run_act_script",
}


def get_active_gemini_tools():
    """GEMINI_TOOLS, trimmed to exclude the ide_*/agent_mode_off tools
    unless Agent Mode is currently on."""
    if is_agent_mode_on():
        return GEMINI_TOOLS
    return [f for f in GEMINI_TOOLS if f.__name__ not in _AGENT_MODE_ONLY_TOOLS]


def get_active_tool_schemas():
    """TOOL_SCHEMAS, trimmed the same way, for the Groq/Mistral manual
    tool-calling loop."""
    if is_agent_mode_on():
        return TOOL_SCHEMAS
    return [s for s in TOOL_SCHEMAS
            if s["function"]["name"] not in _AGENT_MODE_ONLY_TOOLS]


# Just the ide_* tools -- code writing/editing/running/git/layout work
# scoped to the currently open workspace. Deliberately excludes
# agent_mode_off (closing the IDE out from under the very chat panel
# that's running inside it would be self-destructive) and every
# non-ide_* tool (open_app/close_app/minimize_app/restore_app/
# maximize_app/list_open_apps, web_search, memory, calendar, clock,
# agent_mode_on, etc.) -- see IDE_CHAT_TOOL_NAMES below for exactly what
# that leaves in.
IDE_CHAT_TOOL_NAMES = frozenset(
    name for name in _AGENT_MODE_ONLY_TOOLS if name.startswith("ide_")
)


def get_ide_chat_gemini_tools():
    """GEMINI_TOOLS, trimmed down to just IDE_CHAT_TOOL_NAMES -- used only
    for AI calls that came in through the IDE's own embedded "Friday AI
    Chat" panel (see agent_overlay._ide_chat_ask), which is a standing
    requirement: that panel is strictly for coding tasks (writing,
    editing, and running code in the open workspace), never for
    general app/window control or anything else Friday can otherwise do
    from its normal floating circle. Not gated on is_agent_mode_on() the
    way get_active_gemini_tools() is -- the embedded panel only exists
    at all while Agent Mode (and so the IDE) is already on, by
    construction."""
    return [f for f in GEMINI_TOOLS if f.__name__ in IDE_CHAT_TOOL_NAMES]


def get_ide_chat_tool_schemas():
    """TOOL_SCHEMAS equivalent of get_ide_chat_gemini_tools(), for the
    Groq/Mistral manual tool-calling loop."""
    return [s for s in TOOL_SCHEMAS if s["function"]["name"] in IDE_CHAT_TOOL_NAMES]


def call_tool(name, arguments, ide_scoped=False):
    """Dispatches a (name, arguments) tool call from Groq/Mistral's manual
    tool-calling loop to the matching local function above. `arguments`
    may be a JSON string (as providers send it) or an already-parsed dict.
    Always returns a string, even on error, so it can be fed straight
    back to the model as a tool result message.

    `ide_scoped=True` is a defense-in-depth backstop for the IDE's
    embedded chat panel restriction described in
    get_ide_chat_gemini_tools() above: Groq/Mistral are only ever handed
    IDE_CHAT_TOOL_NAMES' schemas for that panel's calls, so a model
    playing by the rules can't even see a non-ide_* tool to request one
    -- but a model can still hallucinate a tool name that was never
    offered, so this is checked again right here, at the one place every
    actual call is dispatched from, rather than trusting the schema list
    alone.
    """
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except Exception:  # noqa: BLE001
            arguments = {}
    elif arguments is None:
        arguments = {}

    if ide_scoped and name not in IDE_CHAT_TOOL_NAMES:
        return (
            f"Error: '{name}' isn't available from the IDE's embedded chat "
            "panel. That panel is scoped strictly to coding tasks -- "
            "writing, editing, and running code in the open workspace -- "
            "not app or window control (opening/closing/minimizing panels, "
            "etc.). Ask Friday directly (the floating circle) for anything "
            "outside of that."
        )

    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return f"Error: unknown tool '{name}'."

    try:
        return str(func(**arguments))
    except TypeError as exc:
        return f"Error calling {name}: invalid arguments ({exc})"
    except Exception as exc:  # noqa: BLE001
        return f"Error calling {name}: {exc}"
