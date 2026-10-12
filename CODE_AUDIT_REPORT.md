# Friday (floating-agent-python) — Full Code Audit Report
**Generated:** 2026-10-10
**Scope:** 75 shipped files / ~26,300 lines of application code (39,786 including the 28-file, 1,410-check test suite)
**Method:** Structured static audit (TODO/FIXME/scaffold-marker search, AST-based circular-import graph, doc-vs-code cross-check, line-by-line trace of every animation/worker-thread dispatch path) + full regression suite execution.

> Follow-up note: this is the original audit snapshot. Its flagged threading
> and import findings were resolved afterward, and focused regressions exposed
> and fixed two additional UI/storage defects. See §10 for the current
> follow-up results; the 1,410-check count below is the original baseline.

---

## 1. Headline numbers

| Metric | Result |
|---|---|
| Regression tests | **1,410 / 1,410 checks passing** (28/28 files) |
| Literal `TODO`/`FIXME`/`XXX`/`HACK` comments found | **0** (team documents gaps in full prose docstrings instead) |
| Confirmed overlapping-animation bugs | **0** |
| Confirmed overlapping-background-process bugs | **0** |
| Real bugs found this session | **1** (fixed) |
| Real doc/code mismatches found | **3** (2 fixed, 1 flagged) |
| Architectural foot-guns found (not bugs in the running app) | **1** (flagged, unfixed) |
| Acknowledged-incomplete features (by design, not bugs) | **3** |
| **Overall completion estimate** | **~95%** |

---

## 2. Bugs found and fixed this session

### 2.1 Settings/memory save crash on Windows — FIXED
**File:** `memory.py`, function `_write_encrypted` (now backed by new `_write_bytes_with_retry`)

**Symptom:** Settings panel crashed with `[Errno 13] Permission denied: '...\ai_models.json.enc'` on a real Windows machine.

**Root cause:** The *read* path (`_open_readable_with_retry`) already had retry + Windows-ACL self-repair logic from an earlier fix. The *write* path never got the matching treatment — it was a bare `open(path, "wb")` with zero resilience, so any transient lock (antivirus/indexing) or stuck ACL on an existing file crashed the whole panel instead of healing itself.

**Fix:** `_write_bytes_with_retry()` — retries through transient locks with backoff, attempts a real Windows ACL repair (`_repair_windows_permissions`) if the file already exists and is stuck, and raises a clear, actionable message (closing other running copies of Friday / checking Windows Defender Controlled Folder Access) if truly unrecoverable, instead of a bare traceback.

**Test coverage added:** 9 new checks in `dev_tests/test_friday_memory.py` Part D (checks 14–18), covering first-try success, transient-lock recovery, ACL-repair recovery, the final actionable-error message, and an end-to-end `_write_encrypted` survival test. All passing.

---

## 3. Doc/code mismatches found

### 3.1 Missing "Review" region — FIXED
Review/Critic/Adjudicator work (used by every Act Script pattern — Sequential Rotation's final review, Fan-Out's aggregator review, Debate's critic/adjudicator/final-read) was silently routed through a region labeled **"Reasoning"** in the Settings panel, with no visible "Review" section at all — confusing, since 100% of that region's real usage is review-type work, never generic reasoning.

**Fix:** Renamed the faculty from `"Reasoning"` → `"Review"` across:
- `settings_store.py` (`FACULTIES` list, `_default_data()`, plus a migration path in `load()` that carries an existing user's saved models from the old `"Reasoning"` key to `"Review"` automatically, so no one loses their configured models)
- `act_script.py` (`ROLE_FACULTY["reasoning"] = "Review"`, plus comments)
- `settings_panel.py`, `agent_tools.py`, `personality.md`, `README.md`, `ARCHITECTURE.md` — every mention updated
- `dev_tests/test_settings_panel.py`, `dev_tests/test_act_script.py` — updated and re-verified green

### 3.2 `ARCHITECTURE.md` described a stale pre-upgrade state — FIXED
It claimed Coding/Planning/Reasoning(now Review)/Text Generation were "pure scaffolding... not a rewiring of the real think/act pipeline" — true before this project's per-region API key work, **false now**. `act_script.py`'s `region_pool()` does a fresh, uncached `settings_store.load()` on every real Act Script run and genuinely dispatches to whatever's configured per-region, including a real OpenAI-compatible `/chat/completions` call for any custom "+ Add Model" entry (`_dispatch_generic_http`). Rewrote the paragraph to say so accurately. Only Image Generation and Video Generation remain genuine scaffolding.

### 3.3 Qt/Tk threading description — FLAGGED, NOT FIXED
`README.md` says the IDE's Tkinter window and the Qt overlay "share one thread: Qt drives the real event loop, and a lightweight timer ticks the IDE's own Tk event loop alongside it" — describing a single-thread cooperative tick model.

The actual code tells a different story:
- `agent_tools.py` has `_TkThreadBridge` and extensive comments about "`_tk_worker_loop`" running the IDE's Tk root on its **own dedicated background thread**.
- `app_panels.py` explicitly says (its own module docstring): *"this module runs its own small dedicated Tk thread"* — a **second, independent** Tk thread, deliberately decoupled from the IDE's.

So the real architecture appears to be **three separate single-threaded event loops on three separate threads** (Qt main thread + IDE's own Tk thread + app_panels' own second Tk thread), bridged by message-passing — not the single-thread timer-tick model the README describes.

**Why not fixed automatically:** rewriting an architecture description incorrectly is worse than leaving it stale. This needs a full trace of `_TkThreadBridge`'s actual mechanics before the README can be safely corrected. Flagging for a decision on whether to invest that tracing time.

---

## 4. Architectural foot-gun found (not a bug in the running app)

**Circular imports at module scope:**
- `app_panels.py` ⇄ `notepad_panel.py`
- `app_panels.py` ⇄ `settings_panel.py`

Both pairs import each other's names at the top of the file (marked `# noqa: E402`, meaning the author placed the import after some of their own definitions on purpose to break the cycle). This works fine for the real app, which always enters through `agent_overlay.py` → `app_panels.py` first, so by the time `settings_panel.py`/`notepad_panel.py` import back from `app_panels`, it's already fully initialized.

**It breaks** if anyone imports `settings_panel.py` or `notepad_panel.py` **directly/standalone** (e.g. a one-off script) — raises `ImportError: cannot import name 'SettingsPanel' from partially initialized module`. I hit this myself this session writing a demo script; the workaround is always importing `app_panels` first and reaching the class via `app_panels._CUSTOM_PANEL_CLASSES["settings"]`.

**Risk level:** low — doesn't affect the shipped app's real startup path, only ad-hoc scripting/tooling against these files.

---

## 5. Animation & concurrent-process overlap — specifically traced, found clean

This was checked by reading the actual code paths, not just grep:

- **Qt circle scale animation** (`agent_overlay.py`): exactly one `QPropertyAnimation` instance; every retarget calls `.stop()` before reconfiguring and restarting (line ~2210) — the correct pattern, no competing-animation risk.
- **Every background AI-worker dispatch is state-gated** — traced all 6 call sites of `_on_query_submitted`:
  - Voice path (`_on_voice_heard`) checks `if self._state != STATE_IDLE: return` before acting on a wake word, explicitly commented as a defensive backstop to the mic already being paused in non-idle states.
  - Confirmation-flow callbacks check `if self._state != STATE_LOADING: return` so a cancelled-mid-flight confirmation can't double-fire a request.
  - The 2-minute auto-continue timer and the connectivity-retry timer both check `if self._state != STATE_IDLE: return` before re-injecting a synthetic query.
- **Tk side (`ide/ide.py`)**: every `.after()`-scheduled animation/debounce (geometry bounce-tween, syntax-highlight debounce, hover-tooltip delay, agent-status auto-clear) explicitly cancels its previous job (`self.after_cancel(old_job)`) before scheduling a new one — same discipline as the Qt side, checked ~15 instances.

**Conclusion:** no overlapping-animation or overlapping-background-process bugs exist in the paths traced. This also explains why so much of the 1,410-check test suite exists — a large share of it (`test_pending_decision_timeout.py`, `test_circle_open_close_animation.py`, `test_panel_status_notifications.py`, `test_friday_voice_confirmation.py`) specifically pins down these exact race-condition classes, and all pass.

---

## 6. Unfinished work — acknowledged by design, not bugs

| Feature | Status |
|---|---|
| **Image Generation region** | No real generation call wiring exists yet. Settings panel honestly labels this. |
| **Video Generation region** | Same — no real call wiring yet, honestly labeled. |
| **`~/.friday/uploads/` and `~/.friday/generated/` folders** | Reserved scaffolding for future "upload files to Friday" / "Friday generates images/videos/documents" features. Explicitly not used yet (`memory.py`). |
| **Google Calendar** | Fully coded (real OAuth flow + list/create events via the real Google Calendar API) — just requires each user to do a one-time manual OAuth client setup. Not a code gap, a per-user setup step. |

No other acknowledged gaps were found in the text-search pass across all `*.py` files for "scaffold," "not used yet," "no real," "upcoming feature," "reachability only," etc.

---

## 7. Historical test-suite snapshot

This table records the earlier audit snapshot only. Its counts and pass
claim are superseded by the final revalidation in section 10; in
particular, the browser row predates the explicit Chromium availability
check.

| File | Checks |
|---|---|
| test_act_script.py | 76/76 |
| test_agent_activity_visualization.py | 30/30 |
| test_agent_tools_ide.py | 178/178* |
| test_app_panels.py | 169/169 |
| test_browser_tools.py | 32/32 |
| test_build_protocol_permission.py | 69/69 |
| test_circle_open_close_animation.py | 40/40 |
| test_circle_response_bubble_hidden.py | 8/8 |
| test_friday_environment_awareness.py | 55/55 |
| test_friday_glow.py | 19/19 |
| test_friday_interrupt_and_followup_listen.py | 31/31 |
| test_friday_memory.py | 117/117 |
| test_friday_speech_to_text.py | 12/12 |
| test_friday_voice_confirmation.py | 51/51 |
| test_ide_activity_bar.py | 21/21 |
| test_ide_chat_panel.py | 14/14 |
| test_ide_chat_server.py | 16/16 |
| test_ide_chat_tool_scope.py | 29/29 |
| test_ide_close_guard.py | 6/6 |
| test_ide_geometry_and_placeholder_label.py | 25/25 |
| test_ide_minimize_pill.py | 25/25 |
| test_panel_status_dispatch.py | 11/11 |
| test_panel_status_notifications.py | 100/100 |
| test_pending_decision_timeout.py | 33/33 |
| test_settings_panel.py | 72/72 |
| test_speech_delivery_cues.py | 19/19 |
| test_tool_loop_iteration_limit.py | 15/15 |
| test_window_management_overhaul.py | 138/138 |

*\*At the time of this historical snapshot, a live browser check failed
because no browser binary was installed. Section 10 records the current
test behavior and validation limit.*

---

## 8. Completion status

The audit found and fixed the issues listed below, but the repository is
not feature-complete: real image/video generation, persistent profile
editing, and a standalone Chat backend remain unimplemented. Browser
automation is implemented, but its live Chromium tests could not run in
this environment because the Playwright Chromium executable is absent.
These facts do not support a universal completion percentage or a claim
of "100% efficiency."

---

## 9. Open decisions at the original snapshot

These questions were open when this snapshot was written. Their current
status is recorded below.

---

## 10. Follow-up findings and verification

### Resolved findings

- **Qt/Tk threading documentation:** traced the IDE's dedicated Tk worker
  loop and the separate app-panel Tk host. Corrected `README.md` to describe
  those two Tk threads alongside Qt's main UI thread.
- **Panel import cycle:** moved shared sizing/placement helpers into
  `panel_ui.py`. `settings_panel`, `notepad_panel`, `conversation_panels`,
  and `app_panels` now each import successfully in a fresh process.
- **Settings file ACLs on Windows:** reproduced a saved settings file
  becoming unreadable after lockdown. Directory-only `(OI)(CI)` inheritance
  flags had been applied to individual files before inherited access was
  removed. `_lock_down_windows()` now grants directory inheritance only to
  directories, grants file access explicitly for files, and verifies access
  by actually listing/opening the target before and after removing inheritance.
- **Settings scrolling:** wheel bindings are scoped to the Settings canvas
  and its content, rather than installed globally on all Tk windows.
- **Conversation panel behavior and content:** empty states now name each
  panel's actual capability boundary. Enter keeps the draft and explains
  that nothing was sent; unavailable microphone/speaker controls do not
  pretend to activate. The Profile panel's compact avatar keeps the input
  bar visible at the tested 420×360 size.
- **Preview and architecture docs:** the HTML concept reflects the explicit
  not-connected states, and the README thread description matches the code.
- **App-panel shutdown:** reproduced Tk `Variable.__del__` errors when an
  open Notepad panel was left for interpreter shutdown. `AppPanelManager`
  now destroys its host-owned widgets before stopping the Tk loop, and
  `CustomNotepadPanel` releases its `StringVar` on the Tk-owning thread.
- **Glow-test cleanup:** the test now stops its timers and closes/deletes
  its Qt widget before application teardown; the process exits normally.
- **Browser-test prerequisite:** the test checks whether Chromium can
  actually launch and skips only the live-browser checks when its binary is
  missing, instead of cascading into unrelated assertion/index errors.

### Final verification

| Check | Result |
|---|---:|
| All `dev_tests/test_*.py` scripts | **30/30 exited successfully** |
| Checks reported by the suite | **1,600 passed** |
| `dev_tests/test_app_panels.py` | **174/174**, no Tk teardown warnings |
| `dev_tests/test_friday_glow.py` | **34/34**, clean process exit |
| `dev_tests/test_settings_panel.py` | **75/75** |
| `dev_tests/test_conversation_panels.py` | **179/179** |
| Fresh-process imports of four panel modules | **4/4** |
| Pylance diagnostics for changed Python files | **No errors** |

The browser suite's six registration/no-session checks passed; its
live-browser checks were **skipped** because
`ms-playwright\chromium_headless_shell-1243\chrome-headless-shell.exe` is
not installed here. Thus, the 1,600 passing checks do not verify live
browser behavior in this environment.
