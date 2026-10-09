# Friday — Architecture Map

This document is a map of the codebase: what every file is, how the pieces
fit together, and — in particular — how Friday's "brain" actually works.
It's a companion to `README.md` (which is written for an end user setting
the project up) and `IDE_CAPABILITY_AUDIT.md` (which is a chronological
engineering log of every capability added to the IDE across many rounds of
work). This file is neither of those: it's a snapshot, organized by what
things *are*, meant to make the project legible at a glance.

---

## 1. The Brain: Listen → Think → Act → Speak (+ Remember, + Aware)

Friday is a loop with four stages, plus two that run quietly alongside
all of them. Every one of those stages lives in a specific, dedicated
place in the code:

```
            ┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐
   you ───► │  LISTEN  │ ───► │  THINK   │ ───► │   ACT    │ ───► │  SPEAK   │ ───► you
    speak   └──────────┘      └────┬─────┘      └──────────┘      └──────────┘
  or type    agent_overlay.py      │              agent_tools.py   agent_overlay.py
             (wake word +          │ recalls       (tools the       (TTS, spoken
              faster-whisper       │ relevant       LLM can call —   aloud; reply
              speech-to-text)      │ memories       see §1.3)        text is never
                                   │ + what's                        shown on screen)
                                   │ on screen
                                   ▼ into context
                      ┌──────────┐   ┌──────────┐
                      │ REMEMBER │   │  AWARE   │ ← queried fresh every turn, not stored
                      └──────────┘   └──────────┘
                       memory.py      agent_tools.py
                      (encrypted      (live panel/IDE
                       files; see      state; see §1.5)
                       §1.4) — every
                       exchange
                       logged here
                       too, after
                       Speak
```

Think is still Gemini → Groq → Mistral, each guided by `personality.md`
and `thinking_skills.md` (see §1.2) — Remember and Aware sit alongside it
rather than replacing anything: Remember quietly supplies relevant *past*
context into Think and logs the result once Speak is done; Aware supplies
what's *currently* true on screen, freshly checked every single turn
rather than stored anywhere.

### 1.1 Listen — `agent_overlay.py` + `overlay_speech.py`
A frameless, always-on-top circle pinned to the screen's top-right corner.
It idles in the background listening for the wake word ("Friday"), then
transcribes whatever follows using `faster-whisper` running **entirely
locally** (no internet, no API key). If `faster-whisper` isn't installed or
its one-time model download fails, it falls back to the free Google Web
Speech API instead, so talking to Friday still works either way. You can
also just click the circle (or say "bring up text chat") to type instead —
typed requests skip the voice-specific confirmation step below entirely.
Because speech-to-text can mishear things, any long or action-sounding
spoken request gets summarized back as a yes/no confirmation first (see
`_needs_confirmation()` near the top of `agent_overlay.py`) — and that
cross-check exchange itself is logged to memory just like any other turn,
not just whatever request it eventually triggers.

### 1.2 Think — `agent_overlay.py` + `personality.md` + `thinking_skills.md` + `speech_delivery.md`
Whatever you asked gets answered by one of three LLM providers, tried in
order, each one only kicking in if every provider before it has no key
configured, is out of quota, or errors out:

1. **Google Gemini** (free tier)
2. **Groq** (Llama 3.3 70B, free, very fast — backup)
3. **Mistral** (Mistral Small, free — third fallback)

Every call is guided by three Markdown files, concatenated into one
`SYSTEM_PROMPT` (`_load_system_prompt()` + `_load_thinking_skills()` +
`_load_speech_delivery()`) — none of them are hardcoded in Python, so
editing any of them changes Friday's behavior with no code changes needed:

- **`personality.md`** — Friday's voice and tone (composed/dry-witted/
  "gentleman's AI" style, directness rules, how it handles emotional
  topics, and — since the memory system shipped — when to proactively
  call `remember`/`add_task` rather than only when explicitly asked to).
- **`thinking_skills.md`** — Friday's reasoning *method*, separate from
  how he sounds: classifying a task as easy/moderate/hard before acting
  on it, decomposing and sequencing hard problems, deliberately slowing
  down and naming risk for high-stakes/"nerve-wracking" requests instead
  of rushing them, verifying a result against the original ask before
  calling it done, and diagnosing (not blindly retrying) when something
  fails. Applies to every reply regardless of which provider answers.
- **`speech_delivery.md`** — Friday's human-like speech *delivery*:
  natural pacing, hesitation, varied emphasis, and a small set of bracket
  cues (`[pause]`, `[sighs]`, `[whispers]`, ...) the LLM may write into a
  reply. These aren't just decorative text — `overlay_speech.py`'s
  `_parse_speech_cues()` gives every recognized one a real mechanical
  effect when the reply is actually spoken (see §1.2.1 below), and
  strips them out entirely (never reading a cue's bracket text aloud as
  literal words) anywhere a reply is only ever shown, not spoken.

#### 1.2.1 Speech-delivery cues: honest limits of an offline voice
Piper and classic SAPI/pyttsx3 (§1.6's TTS backends) are a single fixed
voice each — neither can literally sigh, chuckle, clear its throat, or
change its own prosody mid-sentence the way a human (or an expensive
cloud "expressive" TTS model) can. Rather than either ignoring
speech_delivery.md's cues entirely or letting them leak through as
spoken-aloud bracket text ("bracket pause bracket"), `overlay_speech.py`
converts every recognized cue into the nearest *honest* mechanical
equivalent before any backend ever sees the text:

- `[pause]` / `[brief pause]` / `[long pause]` — a real, interruptible
  beat of silence between the two halves of the reply, sized to the tag.
- `[inhales]`, `[deep breath]`, `[exhales]`, `[sighs]`, `[soft sigh]`,
  `[clears throat]`, `[chuckles]`, `[laughs softly]`, `[hmm]` — also
  become a short timed pause (can't be sounded out), rather than being
  spoken as literal words.
- `[whispers]` / `[voice softens]` — the words immediately after really
  are spoken at reduced volume, lasting until the next cue (or the end
  of the reply).
- `[voice trembles]` — becomes a brief hesitant pause; a true vocal
  tremor isn't something either backend can produce.
- Any other/unrecognized bracket tag still becomes a short generic pause
  rather than ever being read aloud literally, and a markdown-style
  `[text](url)` link is specifically excluded from ever matching as a cue.

`SpeechWorker` (in `overlay_speech.py`) plays a cue-segmented reply as a
sequence of real TTS calls interleaved with real `time.sleep`-based
pauses, but still only emits its `started_speaking` signal once per
reply — not once per segment — so the circle's "talking" animation
behaves exactly as it did before this feature existed. A reply is only
ever displayed as readable text in one place, the IDE's "Friday AI
Chat" side panel (`ide.py`'s `ChatSidePanel`, reached via
`agent_overlay._ide_chat_ask()`) — since that text is never spoken,
`_strip_cues_for_display()` is used there (and for memory logging, both
there and in the circle's own chat path) instead: pause-family cues
become a plain ellipsis, everything else is simply dropped, so the panel
and Friday's own conversation history never show literal bracket "stage
direction" text.

### 1.3 Act — `agent_tools.py` (+ `app_panels.py`, `ide/ide.py`)
This is where an LLM reply can reach for a tool instead of (or in addition
to) just answering in words. Every tool is a plain, type-hinted, docstring-
documented Python function in `agent_tools.py` — Gemini introspects these
directly (`GEMINI_TOOLS`), while Groq/Mistral get an explicit JSON schema
version of the same functions (`TOOL_SCHEMAS`) plus a manual dispatch loop
(`call_tool()`). The ~82 tools fall into clear groups:

| Category | Examples | What it touches |
|---|---|---|
| **Plain file access** | `read_file`, `write_file`, `edit_file`, `list_directory` | Anywhere on disk the OS user can reach — unscoped, for general assistant use outside the IDE |
| **App/window management** | `agent_mode_on/off`, `open_app`, `close_app`, `minimize_app`, `restore_app`, `maximize_app`, `list_open_apps`, `type_in_app`, `save_app_file` | The IDE panel + native app panels (Chrome/Notepad/Calculator/Settings) — see §2, the single-active-panel model |
| **IDE workspace files** | `ide_create_file`, `ide_write_file`, `ide_edit_file`, `ide_read_file`, `ide_rename`, `ide_copy`, `ide_move`, `ide_search_workspace`, `ide_workspace_tree`, `ide_analyze_file_for_deletion` → `ide_delete_file`, `ide_analyze_folder_for_deletion` → `ide_delete_folder` | Scoped **only** to the IDE's currently-open workspace folder (`WorkspaceFS` in `ide.py`) — a path can never resolve outside it |
| **IDE tabs/editor UI** | `ide_open_file` (opens/focuses a *visible* tab — text, image, or PDF — unlike `ide_read_file`, which never touches the UI), `ide_switch_tab`, `ide_list_open_tabs`, `ide_close_tab`, `ide_get_active_tab_content` (reads the live, possibly-unsaved buffer), `ide_save_file`/`ide_save_all` (native Ctrl+S/Save All, capturing live human edits `ide_write_file` can't see), `ide_goto_line`, `ide_find_replace`, `ide_undo/redo`, `ide_editor_action` | The open editor/tab UI itself |
| **IDE run/build/terminal** | `ide_run_file`, `ide_run_project`, `ide_build_project`, `ide_list_tasks`/`ide_run_task` (every auto-detected npm/pytest/cargo/make/... task by name, not just the one obvious run/build task), `ide_stop_task`, `ide_run_terminal_command`, `ide_get_terminal_output`, `ide_clear_terminal`, `ide_clone_repository`, `ide_open_in_browser` | The IDE's integrated terminal/task runner |
| **IDE layout/view control** | `ide_set_theme`, `ide_toggle_view` (show/hide sidebar/terminal/minimap), `ide_show_sidebar` (switch *which* sidebar view — explorer/search/git/run/extensions — and ensure it's visible), `ide_zoom`, `ide_set_opacity`, `ide_toggle_always_on_top`, `ide_toggle_maximize` | The IDE window's own chrome |
| **IDE git** | `ide_git_init/status/add/commit/push/pull/branch/checkout` | A workspace's `.git`, via subprocess (any other git operation — diff, log, stash, rebase, reset, ... — is reachable too, just via `ide_run_terminal_command` rather than a dedicated wrapper) |
| **Time / web / calendar** | `get_current_datetime`, `web_search`, `list_calendar_events`, `create_calendar_event` | Tavily (web search), Google Calendar |
| **Memory & tasks** | `remember`, `recall`, `forget`, `add_task`, `list_tasks`, `complete_task`, `delete_task` | `memory.py`'s encrypted on-disk folder store — see §1.4. Always available, unlike the IDE-gated tools above |

Deliberately **not** included anywhere: any destructive/irreversible action
on files outside the IDE's own workspace. Inside the IDE's own workspace,
Friday may delete a single file (`ide_analyze_file_for_deletion` →
`ide_delete_file`) or a whole folder (`ide_analyze_folder_for_deletion` →
`ide_delete_folder`), each gated by its own mandatory two-step
analyze-then-delete flow (a fresh, matching analysis is required
immediately before the delete call, re-checked for staleness via a content
fingerprint) and each moving its target to a recoverable trash folder
(`.friday_trash`) rather than deleting it outright. Project infrastructure
(`.git`, `node_modules`, a venv, build/cache output — `SKIP_DIRS` in
`ide.py`) and the workspace root itself are always refused for folder
deletion regardless of what the analysis finds. Whether Friday proceeds
straight to deleting something that analysis comes back clean on, or stops
and asks the user first, is a prompt-level judgment call (see
`personality.md`'s "Agent Mode" section) — the code only enforces that
*nothing* can be deleted without a fresh matching analysis immediately
first, not whether the user was asked. Also deliberately not exposed as tools:
Quick Open/Command Palette and the Keyboard Shortcuts/About dialogs — every
task a human would reach for those for already has a direct, more reliable
tool equivalent (`ide_search_workspace`/`ide_workspace_tree`/`ide_open_file`),
so there's no reason to make the model drive a human fuzzy-finder UI instead.
Two sidebar views reachable via `ide_show_sidebar` are UI-only and have no
matching tool capability behind them, by design of the UI itself, not a gap:
"run" is just a Run File shortcut (no real breakpoint debugger exists in this
IDE at all), and "extensions" is a static, non-functional mockup (its
"Install" button is a no-op) — see `FRIDAY_IDE_CAPABILITIES.md` for the full,
explicit can/can't-do inventory.

**The IDE's embedded "Friday AI Chat" side panel is scoped to a strict
subset of all this** — `ChatSidePanel` → `agent_overlay._ide_chat_ask()`
always builds its `AIWorker` with `ide_scoped=True`, which trims every
provider's tool list down to just the IDE workspace/editor/run/git/layout
tools (`agent_tools.IDE_CHAT_TOOL_NAMES`/`get_ide_chat_gemini_tools()`/
`get_ide_chat_tool_schemas()`), with `agent_tools.call_tool()` itself
refusing anything outside that set as a second, independent backstop
(in case a model ever requests a tool name it was never even offered).
This chat box is strictly for coding tasks — writing, editing, running
code in the open workspace — never app/window/panel management
(`open_app`/`close_app`/`minimize_app`/`restore_app`/`maximize_app`/
`list_open_apps`, turning Agent Mode off, or anything else Friday's
normal floating circle can otherwise do). A standing product decision,
not a technical limitation: the floating circle remains the only
surface that can act on panels/windows at all.

Three real OS threads are involved every time this panel sends a
message, and every hop between them is a known, specific failure mode
if skipped — this bit the panel for real once (see
`dev_tests/test_ide_chat_server.py`'s module docstring for the full
postmortem) and is worth keeping in mind for any future change here:
1. **The IDE's own dedicated Tk thread** (`agent_tools._tk_worker_loop`,
   running a genuine, uninterrupted `app.mainloop()`) is what
   `ChatSidePanel._send()` — and so `_ide_chat_ask()`'s own body —
   actually executes on. Only this thread may ever touch a Tk widget.
2. **Qt's main thread** (`agent_overlay.main()`, running `app.exec()`)
   is what `CircleOverlay` and every other Qt widget/timer live on.
   `_ide_chat_ask()` marshals every touch of the circle onto it via
   `_on_qt_main_thread()` (a persistent `QObject` + `Signal(object)` +
   `Qt.QueuedConnection` invoker, built once in `main()`) rather than
   calling it directly — including, critically, building, wiring up, and
   starting the `AIWorker` itself: a `QThread` subclass's own signals,
   connected to a plain Python callback (not a bound `QObject` slot),
   get delivered via a queued call targeting wherever the `QThread`
   *object* was constructed, not wherever its `run()` actually executes
   — build it on the Tk thread (which pumps no Qt events at all) and
   that delivery is silently dropped forever, which is what made
   messages typed into this panel appear to freeze/never go through.
3. **`AIWorker`'s own background thread** (its `run()`), where the
   actual Gemini/Groq/Mistral call happens, is not safe to touch either
   Qt or Tk widgets from directly either — same reasoning as above,
   confirmed directly by reproduction: a `QTimer.singleShot()` scheduled
   from a thread with no Qt event dispatcher of its own silently never
   fires its callback.

Pushing Friday's live state into the IDE's own window-border glow
(`CircleOverlay._push_ide_status()` → `ide.py`'s `set_friday_status()`)
makes the same Qt-main → Tk hop, the other direction: it goes through
`agent_tools._post_on_main()` (the same `_TkThreadBridge`-backed,
fire-and-forget primitive `agent_tools.py`'s own app-panel code already
used for this) rather than calling into the Tk widget directly.

### 1.4 Remember — `memory.py`
As discussed directly with the user, this is deliberately **not** one
opaque database file — it's a folder of real, individually-encrypted
files and folders on disk (default `~/.friday/`, overridable via
`FRIDAY_MEMORY_PATH` or `set_memory_dir()` for tests), organized so any
one fact, task, or conversation has its own addressable home. Full
design rationale (including every edge case and the exact file layout)
lives in `memory.py`'s own module docstring, so it isn't duplicated here
— the summary:

| Folder | Role |
|---|---|
| `facts/` | Deliberately-saved facts/preferences (`remember`/`recall`/`forget` tools below), one encrypted file per fact, each with an embedding — semantic ("vector DB") search |
| `conversations/<session-id>/` | Every exchange, logged automatically (no tool call needed) after each reply, also embedded — one folder per run of the app, one file per turn — the same semantic search, over the raw transcript, across every session |
| `tasks/<id>/` | Structured to-dos (`add_task`/`list_tasks`/`complete_task`/`delete_task`) — one folder per task, plain exact fields, no embedding involved |
| `kv/` | Small key→value session state, one encrypted file per key — the "localStorage" role, given there's no browser here to provide a literal one |
| `uploads/`, `generated/{images,videos,documents}/` | Empty scaffolding reserved for upcoming features (uploading files to Friday; Friday-generated media) — not wired to anything yet, just given a stable, organized, individually-addressable home in advance |

Every `*.json.enc` file is a whole JSON object encrypted with
[Fernet](https://cryptography.io/) (AES128-CBC + HMAC, via the
`cryptography` package), using one local key generated on first use and
stored in `key.bin` right next to the data — by design, not a prompted
passphrase, since memory here is meant to be read only by the user and
by Friday itself on this same machine, with no separate login step. This
protects the data at rest (copy the folder elsewhere, or read it with
some other program, and it's unreadable without `key.bin`). On top of
that, the whole folder is locked down at the OS level the moment it's
first touched (`chmod 700` on POSIX; best-effort `icacls` on Windows) so
*other* user accounts/processes on a shared machine can't read or write
into it at all. **Being explicit about a real limit here rather than
overclaiming it:** this does not, and cannot, stop the owning OS user
(or Friday's own process, running as that user) from deleting the
folder — no plain-filesystem permission scheme can fully prevent that.
`key.bin`'s loss is equally unrecoverable: it is not backed up or
escrowed anywhere, so losing it means every encrypted file becomes
permanently unreadable. A plain-text `README.txt` at the folder root
(and in each reserved subfolder) spells this out for a human who
stumbles onto the folder directly.

**Self-protecting lockdown, not self-locking.** The Windows `icacls`
step used to be one combined call,
`icacls path /inheritance:r /grant:r "user:perm"` — strip inherited
permissions and grant the current user full control, in one shot. In
practice, on at least one real machine, the grant half silently failed
(swallowed on purpose — locking down permissions must never be allowed
to block memory from working) while the inheritance-stripping half
still went through, leaving `key.bin` with *no* effective permissions
at all, including for its own owner: every subsequent read of it —
Settings included — failed with `PermissionError`. `_lock_down`'s
Windows path (`_lock_down_windows` in `memory.py`) is now ordered
grant-then-verify-then-strip instead: it grants access first, confirms
the file is actually still readable, only then strips inherited
permissions, and immediately re-enables inheritance
(`icacls path /inheritance:e`) if that last step somehow still broke
access anyway. A failure anywhere in that sequence now leaves a file at
least as accessible as it already was, never less. Reading `key.bin`
itself goes through `_open_readable_with_retry`, which retries a
transient `PermissionError` with a short backoff first (the realistic
Windows case of antivirus/indexing briefly locking a file moments after
it's written), then attempts an active ACL repair
(`_repair_windows_permissions`: `icacls /reset`, re-grant, `takeown`,
re-grant again — self-healing a file already broken by the old logic,
since a future code fix can't retroactively repair bytes already on
disk) before finally raising a clear, actionable error naming the exact
file and an `icacls /reset` command to run by hand, rather than a bare
`[Errno 13]`. `_read_encrypted` uses the same retry (without the repair
step) but treats a still-unrecoverable error as "skip this one item"
like any other corrupt file, since losing one fact/task/turn is
recoverable in a way that losing `key.bin` itself is not.

Because there's no SQL index behind any of this, search means
decrypting and scanning every file in the relevant folder(s) rather than
one indexed query — an accepted tradeoff at the scale of one person's
local assistant, chosen deliberately over a faster single opaque file
because a real folder of individually-encrypted files is what was
actually wanted here. (Note: this folder-based design is new — an
existing older `~/.friday/memory.db` SQLite file, if one exists from
before this change, is not auto-migrated into it.)

Turning text into a vector for the semantic folders reuses the same
tried-in-order provider philosophy as Think itself: Gemini's embedding
model, then Mistral's, then a local, dependency-free hashed-bag-of-words
vector if neither is reachable — see `embed_text()`. Embeddings from
different providers are never compared against each other (each file
remembers exactly which one produced it); recall transparently falls
back to a plain substring match if nothing in the *current* provider's
space has been saved yet.

Every reply is one single, stateless request to the model — there is no
running chat-history object anywhere in this file. Memory is the *only*
thing that carries anything from one message to the next:

At the start of `AIWorker.run()` (`agent_overlay.py`) — deliberately in
`run()`, on the background thread, not in `__init__` on the UI thread,
so a real embedding-provider network call never blocks the UI before the
worker thread even starts — `memory.build_context_block()` is called once
and folded into that call's system prompt. It combines two different
kinds of recall:

- **Recent turns** — the last ~6 exchanges of *this running session*,
  kept in a tiny in-process ring buffer (`remember_recent_turn()` /
  `get_recent_turns()`), always included regardless of relevance, with
  zero embedding/disk/network involved. This exists specifically to
  close a real gap: `log_turn_async()` (below) is fire-and-forget on a
  background thread so a slow embedding call never delays a reply, but
  that means a turn can take a visible moment before it's actually
  searchable — if the user asks something back immediately, a pure
  embedding-search could lose the race and look like it "forgot." The
  recent-turns buffer has no such delay. It resets on restart; long-term,
  cross-session recall is still entirely the embedded tables below.
- **Semantic search** — `memories` + `conversation_log`, by meaning,
  across all history including past sessions.

After each successful reply, both `remember_recent_turn()` (synchronous,
instant) and `log_turn_async()` (fire-and-forget, embedded, permanent)
are called together — the automatic-logging half. The
`remember`/`recall`/`forget`/`add_task`/`list_tasks`/`complete_task`/
`delete_task` tools (§1.3's table) are the explicit, LLM-initiated half of
the same system.

### 1.5 Aware — `agent_tools.get_environment_snapshot()`
A second, deliberately separate kind of context, folded into the same
system prompt as Remember but never stored anywhere: what's actually on
screen *right now*. `AIWorker._load_environment_context()` calls this
once per reply (on the background thread, same reasoning as the memory
lookup) and gets back a short, always-current block covering:

- Every open panel — the IDE itself, plus native apps Friday opened
  (Notepad, Calculator, a browser, ...) — and whether each is open or
  minimized.
- Which *one* of those, if any, currently holds the shared maximized/
  focused slot (§2's single-active-panel model) — marked as "currently
  active/focused."
- If Agent Mode is on: the IDE's sidebar view (Explorer/Search/Source
  Control/...) and whether it's visible, plus the active editor tab's
  path and whether it has unsaved changes.

This runs even for the voice-confirmation `summarize_only` calls (unlike
the memory lookup, which skips them) — it's a local, instant introspection
call, not a network one, so there's no latency reason to withhold it, and
knowing what's open can matter even for phrasing a yes/no cross-check
sensibly. `list_open_apps()` and `ide_list_open_tabs()` (§1.3's table)
remain as explicit, on-demand tools for deeper detail than the ambient
summary carries — the two are complementary, not a replacement for each
other.

### 1.6 Speak — `agent_overlay.py` + `overlay_speech.py`
Whatever text comes back is spoken aloud with the OS's default voice (or a
configured Piper voice — see `setup_piper_voice.py`). This is deliberately
audio-only: the reply is never rendered as readable text on screen, only
the circle's outline/pulse animation (green = success, red = error)
indicates Friday is replying.

---

## 2. The panel model: one active panel, everything else a pill

Friday owns two kinds of on-screen panel, unified under one shared rule:

- **The IDE** (`ide/ide.py`) — Friday's own built-from-scratch code editor.
- **App panels** (`app_panels.py`) — three flavors: real separate OS
  windows Friday can't embed (Chrome — see that file's module docstring
  for why), a real OS window reparented into a Friday-drawn frame
  (Calculator, `EMBEDDABLE_APPS`), and fully-native panels with no real
  OS process behind them at all (Notepad, Settings — `CUSTOM_PANEL_APPS`,
  each one's own `tk.Toplevel` subclass in its own file — see
  `notepad_panel.py`/`settings_panel.py`).

Conceptually, the IDE, Notepad, and Settings are all **Friday's own
custom work surfaces** — tools Friday itself reaches for to get things
done (writing and running code in the IDE; drafting or reading plain text
in Notepad; reviewing/adding AI model API keys in Settings) — rather than
just app shortcuts being launched for the user's sake. They happen to
live in different files (`ide/ide.py`'s editor, `notepad_panel.py`,
`settings_panel.py` — each importing a couple of shared layout
constants/helpers back from `app_panels.py`'s `EmbeddedAppPanel`), but
all three are governed by the exact same single-active-panel rule below,
and all show up identically in `get_environment_snapshot()` (§1.5) as
"panels," not as different kinds of thing. Settings specifically is
opened the same way as any other app — `open_app("settings")`, or
aliases like "AI settings"/"model settings" (see `KNOWN_APPS["settings"]`
in `app_panels.py`) — there's no separate UI entry point for it.

**The rule (current design, as of the most recent window-management
overhaul): exactly one panel is ever visible on screen at a time.** It's
shown fully maximized, full screen, at Friday's own reference bounds.
Opening or restoring *any* panel immediately makes it the one active
panel and minimizes whatever was active before it to a small pill stacked
under the circle (in order — most recently minimized pill closest to the
circle). There is no smaller "docked to the side" state left — a panel is
always either the one maximized/active panel, or fully minimized to a
pill. `maximize_app()` and `restore_app()` are therefore the same action
under the hood; `restore_app("all")` restores only the single
most-recently-minimized panel, since "restore everything" isn't
meaningful any more when at most one panel can ever be on screen.

This logic is centralized in `agent_tools.py` (`_MINIMIZED_STACK`,
`_maximized_panel_key`, `_place_new_or_restored_panel`, `_AgentHost`) and
shared identically by the IDE and every app panel, rather than duplicated
per panel type.

### 2.1 The Settings panel — `settings_panel.py` + `settings_store.py` + `settings_checks.py`
Lets the user see and manage every AI model/API key Friday knows about,
grouped into ten fixed **faculties** (Thinking, Reasoning, Coding, Image
Generation, Audio Generation, Video Generation, Research, Embedding, Text
Generation, Transcription), each its own section with its own model list
and its own "+ Add Model" button. Split across three files by concern,
the same split memory.py's own docs/code follow:

- **`settings_store.py`** — the data: one list of model entries per
  faculty, persisted as a single encrypted blob (reusing memory.py's own
  `_ensure_folder`/`_write_encrypted`/`_read_encrypted`/`_lock_down`
  primitives directly rather than duplicating them) at
  `<memory dir>/settings/ai_models.json.enc`. Seeded once, on first use,
  with Friday's actual already-wired providers and their current env-var
  keys (Gemini/Groq/Mistral under Thinking, Tavily under Research,
  Gemini+Mistral's embedding models under Embedding, local Piper under
  Audio Generation, local faster-whisper under Transcription) — per the
  user's own explicit framing for this feature, this is deliberately
  *just a UI* over that roster for now, not a rewiring of the real think/
  act pipeline to call arbitrary added providers, so the other five
  faculties (Reasoning, Coding, Image Generation, Video Generation, Text
  Generation) start completely empty: real scaffolding for a capability
  that isn't built yet, same spirit as memory.py's reserved-but-unused
  `uploads/`/`generated/` folders. `mask_key()` is the only thing ever
  shown for a stored key — a fixed-width bullet mask plus a length hint,
  never any real characters, not even a short trailing fragment.
- **`settings_checks.py`** — one function per provider (`check_gemini`,
  `check_groq`, `check_mistral`, `check_tavily`, `check_local_piper`,
  `check_local_whisper`) that makes a real, cheap backend call (listing
  models rather than spending a real generation, wherever the SDK offers
  that) and returns `(ok, detail)` — never raises, so one bad/misconfigured
  entry can't break checking everything else. This is what the user
  explicitly asked for: the green check must come from "a silent call in
  its backend," never just "a key string is non-empty." Any provider
  Friday has no real call code for (every custom entry added through
  "+ Add Model") falls back to `check_generic_http` — a plain reachability
  GET against the entry's API base URL, honestly labeled in the panel as
  "reachable," not "verified," since that's the most truthful claim
  possible without knowing that provider's actual API shape. Tavily has
  no free ping endpoint, so (unlike the others) its check unavoidably
  spends one real search call — checks are therefore only ever run
  on-demand (a per-row "Check" button, a per-faculty-group "Check all,"
  or automatically once right after a model is added), never silently
  in the background on every panel open, to avoid burning API quota
  nobody asked to spend.
- **`settings_panel.py`** — the `SettingsPanel(tk.Toplevel)` widget
  itself, built the same way `notepad_panel.py`'s `CustomNotepadPanel`
  is (same titlebar chrome, same `EmbeddedAppPanel`-shared layout
  constants/`_corner_position` helper, same `ide.py` color palette/
  `_ActiveGlowAnimator`): a scrollable list of faculty sections, each
  listing its models with a masked key, a colored status badge (green
  check = connected, red x = not connected, a hollow circle = never
  checked), and Check/Edit/Remove buttons, plus the faculty's own
  "+ Add Model" button opening a small modal form (display name, model/
  version string, optional API base URL, API key with a show/hide
  toggle). Every check runs on a background thread (real network I/O)
  and marshals its result back via `self.after(...)`, never blocking the
  panel.

Wired into `app_panels.py` exactly the way Notepad is: `"settings"` is a
`KNOWN_APPS` entry (aliases: "settings", "settings panel", "ai settings",
"model settings", "api settings", "ai models", "model manager") and a
`CUSTOM_PANEL_APPS` member, with `_CUSTOM_PANEL_CLASSES` mapping each
custom-panel key to its real class so `_open_custom_panel` can construct
either one through one shared dispatch instead of two near-duplicate
code paths.

**Fail-safe construction.** `SettingsPanel.__init__` builds its titlebar
(with a real, working close button) *before* anything that depends on
`settings_store.load()` actually succeeding, and wraps that load +
initial render in a `try/except` that shows the real error message in
place of the faculty list on failure rather than letting the exception
propagate — so a corrupted settings file or a missing dependency can
never leave an inert, un-closeable blank window on screen; the user can
always close it and see why. Both `SettingsPanel` and `CustomNotepadPanel`
also re-apply their own initial geometry once more (with a full
`update()` in between) right after building all of their content, to
force Tk to actually paint every freshly-built child widget immediately
— `overrideredirect(True)` windows (used by both, since neither has a
real window-manager-drawn frame) can otherwise become visible on real
Windows before painting their content, showing nothing but a blank
background until some interaction forces a repaint.

---

## 3. File-by-file map

### Core brain / UI
| File | Role |
|---|---|
| `agent_overlay.py` | Entry point. The floating circle widget (`CircleOverlay`), the Think worker (`AIWorker`), voice confirmation logic, state machine (Idle/Listening/Loading/Responding). Run this to start Friday. |
| `overlay_speech.py` | Split out of `agent_overlay.py` to keep that file a manageable size: every Listen/Speak implementation detail — Piper/SAPI5/OneCore text-to-speech (`SpeechWorker`), and wake-word + microphone speech-to-text (`VoiceListenWorker`, faster-whisper, the Google Web Speech API fallback). `agent_overlay.py` re-exports everything here by its original name, so nothing outside this pair of files needed to change. |
| `personality.md` | Friday's entire tone/voice/behavior definition, read by the Think stage. Edit this, not code, to change how Friday talks. |
| `agent_tools.py` | The Act layer: every tool the LLM can call, the unified single-active-panel placement system shared by the IDE and app panels, and the Tk-thread bridge that lets a background thread safely drive IDE/app-panel Tk widgets living on their own dedicated UI threads. |
| `tool_schemas.py` | Split out of `agent_tools.py` to keep that file a manageable size: `TOOL_SCHEMAS`, the OpenAI-style JSON schema list Groq/Mistral need for every tool (pure declarative data, matched to each real function by name in `agent_tools.TOOL_FUNCTIONS`). Gemini never touches this — it introspects the plain functions in `agent_tools.py` directly. |
| `app_panels.py` | Manages Friday's native "owned" app panels (Chrome/Notepad/Calculator): launching, embedding, minimizing to a pill, closing, in-panel typing. |
| `window_backend.py` | Split out of `app_panels.py` to keep that file a manageable size: the real OS-process-launch and win32 window-handle primitives (`RealLauncher`, `RealWindowBackend`, `RealTyper`, `_PanelHostBridge`) behind `AppPanelManager`'s pluggable backends. `app_panels.py` re-exports these by their original names. |
| `notepad_panel.py` | Split out of `app_panels.py`, and given its own clearly-named file: `CustomNotepadPanel`, Friday's fully-native Notepad tab (see §2's "IDE + Notepad are both Friday's own work-surface tools" note). `app_panels.py` re-exports it by its original name. |
| `settings_panel.py` | `SettingsPanel`, Friday's fully-native Settings panel for managing AI models/API keys by faculty — see §2.1. Built the same way `notepad_panel.py` is (its own file, importing a couple of shared layout constants back from `app_panels.py`). |
| `settings_store.py` | The Settings panel's persisted data: faculty → model-entry list, encrypted at rest via `memory.py`'s own primitives, plus the seed defaults, add/remove/update helpers, and `mask_key()` — see §2.1. |
| `settings_checks.py` | The Settings panel's real, per-provider connectivity checks (`check_gemini`/`check_groq`/`check_mistral`/`check_tavily`/`check_local_piper`/`check_local_whisper`/`check_generic_http`) — see §2.1. |
| `memory.py` | The Remember layer: an encrypted folder of individual files (`~/.friday/` by default) serving as the vector-DB-style semantic memory, the structured task list, and the "localStorage"-style key/value cache, plus an in-process recent-turns buffer — see §1.4. |
| `thinking_skills.md` | Friday's reasoning method — task classification, decomposing hard problems, slowing down for high-stakes ones, verifying before declaring done — see §1.2. Loaded and appended to `SYSTEM_PROMPT` the same way `personality.md` is. |
| `speech_delivery.md` | Friday's human-like speech *delivery* — natural pacing/hesitation, and the bracket cues (`[pause]`, `[sighs]`, `[whispers]`, ...) `overlay_speech.py` gives a real mechanical effect to when a reply is spoken — see §1.2.1. Loaded and appended to `SYSTEM_PROMPT` the same way `personality.md`/`thinking_skills.md` are. |

### The IDE
| File | Role |
|---|---|
| `ide/ide.py` | Friday's own code editor, built entirely on Python's standard-library Tkinter (no third-party UI deps). File explorer, tabbed editor, integrated terminal, git panel, themes, minimize-to-pill, activity bar, chat overlay. ~7,850 lines — still the single largest file in the project even after splitting out `media_codecs.py` below. |
| `ide/media_codecs.py` | Split out of `ide.py` to keep that file a manageable size: the pure-Python BMP/TGA/JPEG decoders and the PDF page-render/metadata/text-extraction helpers the Explorer's file-preview pane uses when Tk's native PNG/GIF/PPM decoding and any optionally-installed Pillow/external converter both fall short. Fully self-contained (stdlib only); `ide.py` re-exports every name (`decode_bmp`, `decode_jpeg`, `load_image`, `pdf_render_page`, `IMAGE_EXTS`, ...) under its original spelling. |
| `ide/WALKTHROUGH.md` | A guided tour of the IDE's own UI/features, written for a human reading the code or using the app. |
| `ide/tests/` | The IDE's own internal regression suite (`run_all.py` plus feature-specific test modules) — 213 checks, independent of `dev_tests/` below. |

### Tests
| File | Role |
|---|---|
| `dev_tests/` | The project-wide regression suite — 20 files, ~1001 checks total (plus `ide/tests/`'s own 213 — 1214 combined), covering the overlay's state machine, voice confirmation, speech-to-text, app panels, the IDE↔agent_tools bridge (`test_agent_tools_ide.py`, including the full deep-dive round of tab/task/sidebar/browser tools and the file/folder deletion safety net), the window-management model in `test_window_management_overhaul.py`, the memory system (including the recent-turns buffer and the Windows permission-lockdown self-healing logic) in `test_friday_memory.py`, environment awareness + thinking-skills loading in `test_friday_environment_awareness.py`, the speech-delivery cue system in `test_speech_delivery_cues.py`, and the Settings panel (store/checks/UI) in `test_settings_panel.py`. Run any file directly with `python3 dev_tests/<file>.py`. |
| `test_embedding_standalone.py` (top level) | A small, separate smoke test for the native-window-embedding mechanism in isolation, outside the main `dev_tests/` harness. |

### Utilities / one-off scripts
| File | Role |
|---|---|
| `diagnose_mic.py` | Standalone CLI tool to debug microphone/speech-to-text setup issues, independent of the main app. |
| `list_voices.py` | Standalone CLI tool to list text-to-speech voices available on the current OS. |
| `setup_piper_voice.py` | One-time setup helper to download/configure a Piper neural TTS voice as an alternative to the OS default voice. |

### Docs / config / assets
| File | Role |
|---|---|
| `README.md` | User-facing setup and feature overview. |
| `ARCHITECTURE.md` | This file — a map of the codebase by category, for anyone (including a future agent) orienting themselves in the project. |
| `IDE_CAPABILITY_AUDIT.md` | A chronological engineering log/audit of IDE capabilities added over many rounds of work — a history, not a snapshot. |
| `requirements.txt` | Python dependencies. |
| `.env` | Local API keys (Gemini/Groq/Mistral/Tavily/Google Calendar). Never committed or shared. |
| `preview.png` | Screenshot used in `README.md`. |

---

## 4. Documented-intentional code that looks unused but isn't

A few things in the codebase will flag as "dead code" under a naive static
scan but are deliberate, and were confirmed during this cleanup pass to be
either actively exercised by tests or explicitly kept as forward-looking
scaffolding — **do not remove these**:

- **`app_panels.py`: `RealTyper`/`FakeTyper`, `AppPanelManager._typer`** —
  live keystroke injection into a *foreign* OS window via `pywinauto`.
  Currently unused in practice (Notepad moved to driving Friday's own Tk
  widget directly instead), but kept, fully wired into the constructor, as
  a ready building block for a future app that has no Friday-native
  alternative. Documented as such directly in `RealTyper`'s own docstring.
- **`app_panels.py`: `move_to_slot`, `place_in_side_slot`, `restore_default`,
  `unmaximize_panel`** — lower-level panel-geometry mechanics that predate
  the current single-active-panel model (§2). Not reachable through
  `agent_tools.py`'s unified placement system any more (a panel there is
  always either fully maximized or fully minimized, nothing smaller), but
  kept as the standalone/no-`agent_host` fallback path (e.g. a bare
  `AppPanelManager(agent_host=None)`, or `test_embedding_standalone.py`)
  and are directly exercised by `dev_tests/test_app_panels.py`.
- **`RealLauncher.launch`'s unused `file_path` parameter** — kept for
  backward source-compatibility with any caller still passing it, per its
  own docstring; Notepad no longer routes through this launcher at all.
- **Various Tkinter/Qt event-handler overrides** (`paintEvent`,
  `mousePressEvent`, `_key_return`, etc. in `ide.py`/`agent_overlay.py`) —
  invoked by the GUI framework itself via polymorphism/dynamic dispatch,
  not by any direct call site in this codebase, so a plain text search for
  callers won't find one. This is normal and expected for GUI code.

## 5. Dead code actually removed in this cleanup pass

These had zero callers anywhere (production code or tests) and no
documented reason to keep them, so they were deleted outright, confirmed
by a full rerun of all ~920+213 regression checks afterward:

- `app_panels.py`: an orphaned `PILL_GAP = 8` class constant — superseded
  long ago by `MinimizedPill.STACK_STEP`, never actually read anywhere.
- `ide/ide.py`: an orphaned `FILE_COLORS` dict (GitHub-style per-extension
  hex colors) — the real file-icon system (`build_icon`/`draw_icon`) uses
  a completely different, name-based mechanism; this dict was never wired
  into it.
- `ide/ide.py`: a dead `X if False else Y` ternary left over from a
  debugging session in the Makefile-target-detection code — simplified to
  just the live `Y` branch (`list(dict.fromkeys(targets))[:8]`), no
  behavior change.
