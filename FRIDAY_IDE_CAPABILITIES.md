# Friday's IDE — What Friday Can and Cannot Do

A complete, explicit inventory of Friday's control over the built-in IDE
(`ide/ide.py`), written after a full pass auditing every menu item, Activity
Bar icon, and keyboard shortcut against the actual tool code in
`agent_tools.py`/`tool_schemas.py` — and closing every real gap found. This
is the authoritative answer to "what can Friday actually do in the IDE, and
what can't he."

**How it works, in one paragraph:** the IDE is one process with Friday, not
a separate app he remote-controls — `agent_mode_on` builds a real `IDEApp`
(Tk) in-process, and every `ide_*` tool below is a thin, direct call into
that same live object (file ops go through `WorkspaceFS`, which also
sandboxes every path to the one open workspace folder — a path can never
resolve outside it). All `ide_*` tools require Agent Mode to be on; they
disappear from Friday's own tool list the moment it's off, and calling one
anyway turns Agent Mode on automatically (or reports that it's off, for the
view/query-only tools). The IDE's window lifecycle itself (open/close/
minimize/maximize/restore) is handled by the *generic* panel tools
(`open_app`, `close_app`, `minimize_app`, `maximize_app`, `restore_app`),
which all accept `"ide"` as a name — not a separate `ide_*` tool, because the
IDE is just one of Friday's panels, same as Notepad or Settings.

As of this pass there are **58 `ide_*` tools**, all listed below, each
mapped to the exact menu item / icon / shortcut it mirrors.

**One important exception to all of the above:** everything in this
document describes what Friday can do to/in the IDE in general — from
voice, from a typed command to the floating circle, or from code. The
IDE's own embedded **"Friday AI Chat" side panel** (the chat box docked
next to the editor) is deliberately narrower than that, by standing
product decision: a message typed into *that specific box* can only ever
reach the IDE workspace/editor/run/git/layout tools (`agent_tools.
IDE_CHAT_TOOL_NAMES` — exactly the `ide_*` tools in §1–§8 below, nothing
more). It cannot open/close/minimize/maximize/restore the IDE or any
other panel, cannot turn Agent Mode off, and cannot reach web search,
memory, calendar, or any plain unscoped file tool either — all of that
remains the floating circle's domain only. This is enforced twice, not
just by convention: the tool list actually offered to the model is
trimmed to that set, and `agent_tools.call_tool()` independently refuses
to run anything outside it even if asked. See `ARCHITECTURE.md` §1.3 for
the full mechanism.

---

## 1. Window & lifecycle — CAN do

| Capability | Tool |
|---|---|
| Open the IDE / turn on Agent Mode | `agent_mode_on` |
| Close the IDE / turn off Agent Mode | `agent_mode_off` |
| Minimize the IDE to its pill | `minimize_app("ide")` |
| Restore it from the pill | `restore_app("ide")` |
| Maximize / un-maximize | `maximize_app("ide")` **or** `ide_toggle_maximize` |
| Bring it to the front without changing anything else | `restore_app("ide")` |
| List it among everything currently open | `list_open_apps` |
| Keep it above every other window | `ide_toggle_always_on_top` |
| Make the window more see-through / more solid | `ide_set_opacity("more_transparent" / "more_opaque")` |
| Switch the whole color theme (grey/black/white) | `ide_set_theme` |

## 2. Opening a project — CAN do

| Capability | Tool |
|---|---|
| Open an existing folder as the workspace | `ide_open_folder` |
| Clone a git repo and open it as the workspace | `ide_clone_repository` |
| Start fresh with no folder chosen yet | Automatic — a scratch workspace is created the moment Friday writes anything |

**Cannot do:** open more than one workspace/folder at once (single root,
like VS Code without multi-root workspaces) — opening a new folder replaces
the current one.

## 3. Files & folders — CAN do

| Capability | Tool |
|---|---|
| Create a new file (refuses to overwrite) | `ide_create_file` |
| Create or overwrite a file | `ide_write_file` |
| Replace one exact snippet of text in a file | `ide_edit_file` |
| Create a folder (and its parents) | `ide_create_folder` |
| Read a file's on-disk content | `ide_read_file` |
| List one folder's immediate contents | `ide_list_folder` |
| List every file in the whole workspace | `ide_workspace_tree` |
| Check whether a path exists | `ide_exists` |
| Rename a file or folder | `ide_rename` |
| Copy a file/folder into another folder | `ide_copy` — copying into its *own* parent folder reproduces the Explorer's right-click "Duplicate" (an auto " copy" suffix is added) |
| Move a file/folder into another folder | `ide_move` |
| Plain-text search across the whole workspace | `ide_search_workspace` |
| Reveal a path in the OS's native file manager | `ide_reveal_in_file_manager` |
| Copy a path (absolute or workspace-relative) to the clipboard | `ide_copy_path` |
| Delete one file — only through a mandatory two-step flow | `ide_analyze_file_for_deletion` → `ide_delete_file` — moves it to a recoverable `.friday_trash/` folder, never a hard delete |
| Delete a whole folder — only through a mandatory two-step flow | `ide_analyze_folder_for_deletion` → `ide_delete_folder` — moves the entire folder into `.friday_trash/` as a unit, never a hard delete |

Both deletion flows are gated in code, not just by prompting: the analyze
step is mandatory, must be re-run if the target has changed since (a
content/fingerprint check catches that), and refuses outright on project
infrastructure (`.git`, `node_modules`, a venv, build/cache output) or the
workspace root for folder deletion — those are never deletable by Friday,
full stop. Whether Friday then proceeds straight to deleting something the
analysis came back clean on (routine cleanup, narrated after the fact) or
stops to ask the user first (references found, or genuine ambiguity) is a
judgment call the prompt makes, not something the code gates — see
`personality.md`'s "Agent Mode" section for the exact policy.

**Cannot do:**
- Delete a file or folder without its matching analyze-then-delete flow
  immediately first — a skipped, stale, or changed-since-analysis target is
  refused outright, so this can't be bypassed by skipping step 1.
- Delete project infrastructure folders (`.git`, `node_modules`, a venv,
  build/cache output) or the workspace root itself, ever, regardless of
  what an analysis would otherwise report — these are hard-refused in code.
- Touch anything **outside** the open workspace folder from any `ide_*`
  tool — every path is resolved and boundary-checked first (`WorkspaceFS`).
  (Friday's separate, non-IDE `read_file`/`write_file`/`edit_file` tools are
  unscoped and can reach anywhere on disk — that's a deliberately different,
  non-IDE capability, not a loophole in the IDE's own sandboxing.)
- Permanently, irrecoverably destroy a file or folder via any agent tool —
  both deletion paths always land in `.friday_trash/`, recoverable by hand.

## 4. Tabs & the editor itself — CAN do

| Capability | Tool |
|---|---|
| Open (or focus, if already open) a file as a real visible tab — text, image, or PDF | `ide_open_file(path, line=...)` |
| Switch to an already-open tab without closing anything | `ide_switch_tab` |
| List every open tab, which is active, and unsaved-changes status | `ide_list_open_tabs` |
| Close one tab, several by name, "others", or "all" | `ide_close_tab` |
| Read the *live* content of the active tab, including edits never saved to disk | `ide_get_active_tab_content` |
| Save the active tab (captures live, human-typed edits — same as Ctrl+S) | `ide_save_file` |
| Save every dirty tab that has a path (File > Save All) | `ide_save_all` |
| Jump the cursor to a specific line | `ide_goto_line` (or `ide_open_file(path, line=N)` in one step) |
| Find text, and optionally replace one/all matches | `ide_find_replace` |
| Undo / redo | `ide_undo` / `ide_redo` |
| Cut / copy / paste / select all / duplicate line / move line up / move line down | `ide_editor_action` |
| Change editor font size (zoom in/out/reset) | `ide_zoom` |

**Cannot do:**
- Multi-cursor editing, column/box selection, or any multi-selection
  editing tool — one cursor, one selection, exactly what `ide_editor_action`
  exposes and nothing more granular.
- Place the cursor at an arbitrary *column* (only whole lines, via
  `ide_goto_line`).
- Split the editor into multiple side-by-side groups/panes — one editor
  area, tabs only, same as a single VS Code editor group.
- Rewind to an arbitrary point in file history — only the standard
  linear undo/redo stack, no persistent local history view.
- Code completion / IntelliSense is a real, working feature of the editor,
  but it's interactive and keystroke-triggered for a human typing — there's
  no tool for Friday to "ask for a completion list" separately; this isn't
  a gap so much as the feature having no agent-relevant shape.

## 5. Search & navigation — CAN do

| Capability | Tool |
|---|---|
| Plain-text search across the workspace, same as the Search sidebar | `ide_search_workspace` |
| List every file (for "where is X" style lookups) | `ide_workspace_tree` |
| Switch which sidebar view is showing | `ide_show_sidebar("explorer" / "search" / "git" / "run" / "extensions")` |
| Show/hide the sidebar, terminal, or minimap outright | `ide_toggle_view` |

**Cannot do:**
- Drive Quick Open (Ctrl+P) or the Command Palette (Ctrl+Shift+P) directly —
  not exposed as tools **on purpose**: everything a human would use them for
  (jumping to a file, running a command) already has a direct, more
  reliable tool (`ide_open_file`, `ide_workspace_tree`, the specific
  `ide_*` action itself) that doesn't require driving a fuzzy-finder UI.
- Regex search — `ide_search_workspace` is plain substring, case-insensitive
  text search only, same as the UI's own Search sidebar.

## 6. Running, building & tasks — CAN do

| Capability | Tool |
|---|---|
| Run the active file (F5) | `ide_run_file` |
| Run the project's detected dev-server/run task (Ctrl+F5) | `ide_run_project` |
| Build the project | `ide_build_project` |
| List *every* auto-detected task (npm scripts, pytest, cargo, make targets, Docker, Gradle, Maven, dotnet, and more, depending on what's in the folder) | `ide_list_tasks` |
| Run one *specific* named task by its exact label (e.g. "npm: test", "npm: lint", a Makefile target) | `ide_run_task(label)` |
| Stop whatever's currently running | `ide_stop_task` |
| Run any shell command directly, visible in the terminal | `ide_run_terminal_command` |
| Read back the terminal's current output | `ide_get_terminal_output` |
| Clear the terminal | `ide_clear_terminal` |
| Open the current HTML file or a running dev server in the system browser | `ide_open_in_browser` |

**Cannot do:**
- Run two tasks/commands at the same time — there is exactly one shared
  terminal/task-runner process; starting something new while one is already
  running means stopping the first one first (`ide_stop_task`).
- Real debugging — breakpoints, step-over/into/out, a call stack, a
  variables/watch pane. The "Run and Debug" sidebar view (reachable via
  `ide_show_sidebar("run")`) is real UI, but it only contains a single
  "Run Python File" shortcut — there is no actual debugger anywhere in this
  IDE, by Friday or by the human.
- Edit/create `tasks.json`/`launch.json` to define custom tasks through a
  config file the IDE reads — tasks are entirely auto-detected by scanning
  the workspace (package.json scripts, Makefile targets, etc.), not
  user-authored.

## 7. Git / source control — CAN do

| Capability | Tool |
|---|---|
| Initialize a repository | `ide_git_init` |
| Check status | `ide_git_status` |
| Stage files (specific paths, or everything) | `ide_git_add` |
| Commit | `ide_git_commit` |
| Push / pull | `ide_git_push` / `ide_git_pull` |
| List or create branches | `ide_git_branch` |
| Switch branches (optionally creating one) | `ide_git_checkout` |
| Anything else — diff, log, stash, rebase, reset, merge, tag, remotes, ... | `ide_run_terminal_command("git ...")` — there's no dedicated wrapper for these, but they are **fully usable**, same as any other shell command |

**Cannot do:**
- Stage/unstage/commit by clicking in the UI's own Source Control sidebar —
  that view (`ide_show_sidebar("git")`) is **read-only**: a changed-files
  list plus an "Initialize Repository" button, nothing more. All real git
  actions (by Friday or the human) go through the terminal/the `ide_git_*`
  tools, not extra Source Control buttons.
- Nothing is technically blocked for destructive git operations (force
  push, hard reset, etc.) — but Friday's own standing behavior always
  confirms before anything high-impact/hard-to-reverse, same as any other
  risky action.

## 8. Layout & appearance — CAN do

| Capability | Tool |
|---|---|
| Show/hide the sidebar, terminal panel, or minimap | `ide_toggle_view` |
| Switch which sidebar view is showing, and ensure it's visible | `ide_show_sidebar` |
| Change the color theme | `ide_set_theme` |
| Zoom the editor font | `ide_zoom` |
| Make the window more transparent/opaque | `ide_set_opacity` |
| Keep it always-on-top | `ide_toggle_always_on_top` |
| Maximize / restore | `ide_toggle_maximize` |

**Cannot do:**
- Rearrange panel *positions* (move the sidebar to the right, move the
  panel to the side instead of the bottom, etc.) — the layout's structure
  is fixed; only visibility/theme/zoom/opacity are adjustable.
- Rebind keyboard shortcuts, or read/change them individually — Help >
  Keyboard Shortcuts is a static reference dialog for the human only.

## 9. What exists in the UI but is a hard "cannot do," by design of the IDE itself

These aren't missing tools — the underlying feature itself doesn't really
exist, for anyone, human or Friday:

- **No real Extensions system.** The Extensions sidebar view is a static,
  cosmetic mockup of five example entries; its "Install" button is a no-op
  (does nothing at all when clicked). Nothing can actually be installed,
  searched for, or configured.
- **No real debugger.** Covered above — "Run and Debug" is a single Run
  File shortcut, not breakpoints/stepping/inspection.
- **No language server / IntelliSense.** Syntax highlighting for ~25
  languages exists (a hand-written regex lexer), but there's no real
  go-to-definition, find-references, rename-symbol, linting, or type
  checking — those require installing the real tool (e.g. a linter) and
  running it via the terminal, same as any other CLI tool.
- **No real multi-root workspaces, split editor groups, or persistent
  per-file edit history.**

## 10. Everything else Friday already has, for context

Alongside the IDE, Friday also always has (not gated behind Agent Mode):
`remember`/`recall`/`forget` and `add_task`/`list_tasks`/`complete_task`/
`delete_task` (the separate long-term memory/task system, unrelated to the
IDE's own detected run-tasks above, despite the similar name), plain
unscoped `read_file`/`write_file`/`edit_file`/`list_directory` for anywhere
on disk outside the IDE's workspace sandbox, `web_search`, calendar tools,
and the generic app-panel tools (`open_app`/`close_app`/`minimize_app`/
`maximize_app`/`restore_app`/`type_in_app`/`save_app_file`) for Chrome,
Notepad, Calculator, and Settings.

---

### Quick reference: all 58 `ide_*` tools

```
ide_open_folder            ide_create_file             ide_write_file
ide_edit_file              ide_create_folder           ide_read_file
ide_list_folder            ide_workspace_tree          ide_exists
ide_rename                 ide_copy                    ide_move
ide_search_workspace       ide_analyze_file_for_deletion
ide_delete_file            ide_analyze_folder_for_deletion
ide_delete_folder          ide_run_file                ide_run_project
ide_build_project          ide_stop_task               ide_get_terminal_output
ide_run_terminal_command   ide_clone_repository        ide_set_theme
ide_show_sidebar           ide_toggle_view             ide_open_in_browser
ide_clear_terminal         ide_list_tasks              ide_run_task
ide_zoom                   ide_set_opacity             ide_toggle_always_on_top
ide_toggle_maximize        ide_undo                    ide_redo
ide_editor_action          ide_goto_line               ide_find_replace
ide_open_file              ide_switch_tab              ide_get_active_tab_content
ide_save_file              ide_save_all                ide_list_open_tabs
ide_close_tab              ide_reveal_in_file_manager  ide_open_in_integrated_terminal
ide_copy_path              ide_git_init                ide_git_status
ide_git_add                ide_git_commit              ide_git_push
ide_git_pull               ide_git_branch              ide_git_checkout
```

Plus the generic, always-present panel tools that also control the IDE
window by name (`"ide"`): `open_app`, `close_app`, `minimize_app`,
`restore_app`, `maximize_app`, `list_open_apps`.
