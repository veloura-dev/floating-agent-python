"""End-to-end proof that agent_tools.py's Agent Mode functions work
against the REAL ide/ide.py IDEApp — built in-process now (Friday and the
IDE are one process/one codebase since Task 23), not a subprocess — and
that the dynamic tool-list trimming (get_active_gemini_tools/
get_active_tool_schemas) behaves correctly across the on/off transition.
Kept in the persisted workspace (not /tmp) so it survives a fresh
sandbox session.

Requires a display (Tkinter): run with
    DISPLAY=:99 python3 dev_tests/test_agent_tools_ide.py

The IDE now gets a real, dedicated OS thread of its own running an
uninterrupted native Tk mainloop() for as long as agent_mode_on() has it
open (see agent_tools._TkThreadBridge's docstring) — this script's own
thread is never the one Tk belongs to, exactly like the real app (where
the IDE's thread and Friday's own Qt main thread are two separate GUI-
owning threads). Everything here accordingly goes through
agent_tools._run_on_main()/the normal ide_* tool functions (which
already marshal onto the IDE's thread themselves) rather than ever
touching the live `app` object directly from this thread. There's
nothing left to "pump" any more — the IDE services its own after()
callbacks continuously on its own thread regardless of what this script
is doing — so small time.sleep() calls are used wherever this needs to
give an async operation a moment to finish."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_tools as at  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def on_ide_thread(fn):
    """Run fn() on the IDE's own Tk thread and return its result —
    thin wrapper over agent_tools._run_on_main so tests that need to
    poke the live `app` object directly (reading widget options,
    switching tabs, etc) never do so from this thread."""
    return at._run_on_main(fn)


def save_tab_by_name(name, timeout=3.0):
    """Switch to the buffer called `name` and save it on the IDE's own
    thread, so a freshly agent-created tab (which the typewriter-open
    animation keeps marking modified, chunk by chunk, for a brief
    moment after it first appears in self.buffers) doesn't trip the
    real 'Save changes?' modal when a later test closes it by name.
    Retries + re-checks modified shortly after each save because a
    still-in-flight typewriter chunk can flip modified back to True
    again right after a save that looked clean."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        def _do():
            idx = next((i for i, b in enumerate(at._ide_app.buffers)
                        if b.get("name") == name), None)
            if idx is None:
                return None
            at._ide_app.switch_tab(idx)
            at._ide_app.save_file()
            return at._ide_app.buffers[idx].get("modified")
        if on_ide_thread(_do) is False:
            time.sleep(0.15)
            def _check():
                idx = next((i for i, b in enumerate(at._ide_app.buffers)
                            if b.get("name") == name), None)
                return (at._ide_app.buffers[idx].get("modified")
                        if idx is not None else None)
            if on_ide_thread(_check) is False:
                return True
        time.sleep(0.1)
    return False


def wait_until_tab_appears(name, timeout=3.0):
    """ide_create_file's new tab/buffer is only actually added once its
    (cosmetic) typewriter-open animation runs on the IDE's own thread a
    moment later, not synchronously when the tool call returns -- poll
    ide_list_open_tabs() instead of a blind sleep so this isn't flaky
    under load."""
    deadline = time.time() + timeout
    listing = ""
    while time.time() < deadline:
        listing = at.ide_list_open_tabs()
        if name in listing:
            return listing
        time.sleep(0.05)
    return listing


def main():
    # 1. Baseline: agent mode starts off, only the 17 always-on tools show up.
    check("agent mode starts off", not at.is_agent_mode_on())
    active = {f.__name__ for f in at.get_active_gemini_tools()}
    check("24 tools active while off (17 original + 7 new memory/task tools)", len(active) == 24)
    check("agent_mode_on always available", "agent_mode_on" in active)
    check("ide_create_file hidden while off", "ide_create_file" not in active)
    check("ide_analyze_file_for_deletion hidden while off",
          "ide_analyze_file_for_deletion" not in active)
    check("ide_delete_file hidden while off", "ide_delete_file" not in active)
    check("ide_analyze_folder_for_deletion hidden while off",
          "ide_analyze_folder_for_deletion" not in active)
    check("ide_delete_folder hidden while off", "ide_delete_folder" not in active)
    check("ide_list_open_tabs hidden while off", "ide_list_open_tabs" not in active)
    check("_ide_app is None while off", at._ide_app is None)

    # 2. Turn agent mode on -> a real IDEApp is built in this process.
    msg = at.agent_mode_on()
    check("agent_mode_on() succeeded", "Agent Mode is on" in msg)
    check("is_agent_mode_on() true now", at.is_agent_mode_on())
    check("_ide_app is a live IDEApp", at._ide_app is not None)
    pid = at.get_ide_pid()
    check("get_ide_pid() returns a real pid", isinstance(pid, int) and pid > 0)
    check("get_ide_pid() equals this process's own pid (one process now)",
          pid == os.getpid())
    time.sleep(0.1)

    active_on = {f.__name__ for f in at.get_active_gemini_tools()}
    check("88 tools active while on (64 original + 12 new IDE tools + 7 new "
          "memory/task tools + 2 new frontend-skill tools + 3 new Build "
          "Protocol tools -- backend/storage skill fetch + build-status)",
          len(active_on) == 88)
    check("ide_create_file visible while on", "ide_create_file" in active_on)
    check("ide_git_commit visible while on", "ide_git_commit" in active_on)
    check("ide_analyze_file_for_deletion visible while on",
          "ide_analyze_file_for_deletion" in active_on)
    check("ide_delete_file visible while on", "ide_delete_file" in active_on)
    check("ide_analyze_folder_for_deletion visible while on",
          "ide_analyze_folder_for_deletion" in active_on)
    check("ide_delete_folder visible while on", "ide_delete_folder" in active_on)

    # 2b. The circle-rect bridge the open/close pop animation reads from
    # (agent_overlay.py's circle registers a provider via
    # set_circle_rect_provider; _AgentHost.get_circle_rect() is what
    # ide.py actually calls). No provider is registered in this test
    # process (no real CircleOverlay running), so this must come back
    # None cleanly rather than raising -- exactly the "no circle, no
    # animation, window just appears normally" fallback path.
    check("get_circle_rect() is None with no provider registered",
          at._AGENT_HOST.get_circle_rect() is None)

    def _boom():
        raise RuntimeError("provider blew up")

    at.set_circle_rect_provider(_boom)
    check("get_circle_rect() swallows a raising provider",
          at._AGENT_HOST.get_circle_rect() is None)

    at.set_circle_rect_provider(lambda: (12.0, 34.0, 56.0))
    check("get_circle_rect() returns the provider's rect",
          at._AGENT_HOST.get_circle_rect() == (12.0, 34.0, 56.0))
    at.set_circle_rect_provider(None)  # leave no provider registered, as before

    # 2c. Friday can push its own state straight into the IDE's window-border
    # glow -- a plain direct method call now, no polling involved.
    def _glow_check(status, is_error, expect_attr):
        def _do():
            app = at._ide_app
            # Task 47's active-panel pulse (see ide.py's
            # _ActiveGlowAnimator) deliberately owns painting the
            # border instead of a plain static color whenever Friday's
            # status is idle *and* this panel is the current
            # active/maximized one (agent_mode_on() made it exactly
            # that, as the session's first panel) -- that new behavior
            # has its own dedicated coverage in
            # test_window_management_overhaul.py's part_c. Switched off
            # here so this check keeps testing what it's actually meant
            # to: that set_friday_status's own busy/ok/error/idle colors
            # still work right, independent of that newer feature.
            app.set_active_panel(False)
            app.set_friday_status(status, is_error)
            return app.cget("highlightbackground") == getattr(app, expect_attr)
        return on_ide_thread(_do)

    check("glow turns blue for listening",
          _glow_check("listening", False, "_GLOW_BUSY"))
    check("glow turns red for an error reply",
          _glow_check("responding", True, "_GLOW_ERR"))
    check("glow returns to idle color",
          _glow_check("idle", False, "_GLOW_IDLE"))

    # 3. Exercise the sandboxed fs tools directly against the live IDE.
    at.ide_create_file("hello.py", "print('hi')\n")
    content = at.ide_read_file("hello.py")
    check("read back what was written", "print('hi')" in content)

    at.ide_edit_file("hello.py", "print('hi')", "print('hello world')")
    content2 = at.ide_read_file("hello.py")
    check("edit applied directly, no approval step", "hello world" in content2)

    at.ide_create_folder("pkg")
    at.ide_create_file("pkg/util.py", "def f():\n    return 1\n")
    tree = at.ide_workspace_tree()
    check("workspace tree includes nested file", "pkg" in tree and "util.py" in tree)

    listing = at.ide_list_folder(".")
    check("list_folder sees top-level entries", "hello.py" in listing and "pkg" in listing)

    check("ide_exists true for a real file", "exists" in at.ide_exists("hello.py")
          and "does not" not in at.ide_exists("hello.py"))
    check("ide_exists false for a missing file", "does not exist" in at.ide_exists("nope.py"))

    rename_msg = at.ide_rename("hello.py", "greeting.py")
    time.sleep(0.1)
    check("ide_rename succeeded", "Renamed" in rename_msg)
    check("old name gone after rename", "does not exist" in at.ide_exists("hello.py"))
    check("new name present after rename", "exists" in at.ide_exists("greeting.py"))

    copy_msg = at.ide_copy("greeting.py", ".")
    time.sleep(0.1)
    check("ide_copy succeeded", "Copied" in copy_msg)

    at.ide_create_folder("archive")
    move_msg = at.ide_move("pkg/util.py", "archive")
    time.sleep(0.1)
    check("ide_move succeeded", "Moved" in move_msg)
    check("moved file no longer in pkg", "does not exist" in at.ide_exists("pkg/util.py"))
    check("moved file now in archive", "exists" in at.ide_exists("archive/util.py"))

    search_result = at.ide_search_workspace("hello world")
    check("ide_search_workspace finds the edited text",
          "greeting.py" in search_result or "hello world" in search_result)

    # 3b. Agent-driven file deletion -- the one deliberately narrow
    # exception to "no delete tool". Must refuse outright without a
    # fresh, matching analysis first, must flag a referenced file as
    # NOT clearly dead, must allow deleting an unreferenced one only
    # after analysis, and must land it in .friday_trash rather than
    # really destroying it.
    at.ide_create_file("dead_code.py", "def unused_fn():\n    return 42\n")
    at.ide_create_file(
        "uses_dead_code.py", "import dead_code\nprint(dead_code.unused_fn())\n")
    at.ide_create_file("truly_unused.py", "def nobody_calls_me():\n    pass\n")

    deny_msg = at.ide_delete_file("truly_unused.py")
    check("delete refused without prior analysis", "Refusing" in deny_msg)
    check("still exists after refused delete",
          "exists" in at.ide_exists("truly_unused.py")
          and "does not" not in at.ide_exists("truly_unused.py"))

    referenced_report = at.ide_analyze_file_for_deletion("dead_code.py")
    check("analysis finds the file content",
          "unused_fn" in referenced_report)
    check("analysis flags a referenced file as not clearly dead",
          "NOT clearly dead" in referenced_report)
    check("analysis surfaces the referencing file/line",
          "uses_dead_code.py" in referenced_report)

    unused_report = at.ide_analyze_file_for_deletion("truly_unused.py")
    check("analysis finds no references for a genuinely unused file",
          "No references" in unused_report)

    delete_msg = at.ide_delete_file("truly_unused.py")
    time.sleep(0.1)
    check("delete succeeded after analysis", "Deleted" in delete_msg)
    check("file gone from its original path",
          "does not exist" in at.ide_exists("truly_unused.py"))
    check("delete message points at the recoverable trash folder",
          ".friday_trash" in delete_msg)
    check("file physically sitting in .friday_trash on disk", any(
        "truly_unused.py" in name
        for name in os.listdir(os.path.join(at._ide_app.root_dir, ".friday_trash"))))
    check(".friday_trash hidden from the workspace tree",
          ".friday_trash" not in at.ide_workspace_tree())
    gitignore_path = os.path.join(at._ide_app.root_dir, ".gitignore")
    check(".gitignore auto-created/updated so git add -A can't sweep up trash",
          os.path.exists(gitignore_path)
          and ".friday_trash/" in open(gitignore_path).read())

    redelete_msg = at.ide_delete_file("truly_unused.py")
    check("re-deleting without a fresh analysis is refused",
          "Refusing" in redelete_msg)

    at.ide_analyze_file_for_deletion("dead_code.py")
    at.ide_edit_file("dead_code.py", "42", "43")  # content changes post-analysis
    stale_msg = at.ide_delete_file("dead_code.py")
    check("delete refused when content changed since analysis",
          "Refusing" in stale_msg and "changed" in stale_msg)
    check("edited-but-referenced file survives the refused delete",
          "exists" in at.ide_exists("dead_code.py")
          and "does not" not in at.ide_exists("dead_code.py"))

    at.ide_create_folder("not_a_file")
    folder_report = at.ide_analyze_file_for_deletion("not_a_file")
    check("analyzing a folder is rejected, not misread as a file",
          "folder" in folder_report.lower())
    folder_delete = at.ide_delete_file("not_a_file")
    check("deleting a folder path is refused (no prior file analysis)",
          "Refusing" in folder_delete)

    # 3c. Agent-driven FOLDER deletion -- the same analyze-then-delete
    # safety net as files, extended to a whole folder at once: refuse
    # outright without a fresh, matching analysis; flag a folder containing
    # a referenced file as NOT clearly dead; allow deleting an unreferenced
    # folder only after analysis; land it in .friday_trash as a unit rather
    # than really destroying it; refuse SKIP_DIRS infrastructure names and
    # the workspace root outright regardless of analysis.
    at.ide_create_folder("dead_pkg")
    at.ide_create_file("dead_pkg/helper.py", "def helper():\n    return 1\n")
    at.ide_create_file(
        "uses_dead_pkg.py", "from dead_pkg.helper import helper\nprint(helper())\n")
    at.ide_create_folder("unused_pkg")
    at.ide_create_file("unused_pkg/scratch.py", "def nobody_calls_me():\n    pass\n")

    folder_deny_msg = at.ide_delete_folder("unused_pkg")
    check("folder delete refused without prior analysis", "Refusing" in folder_deny_msg)
    check("folder still exists after refused delete",
          "exists" in at.ide_exists("unused_pkg")
          and "does not" not in at.ide_exists("unused_pkg"))

    file_as_folder_report = at.ide_analyze_folder_for_deletion("greeting.py")
    check("analyzing a file path with the folder tool is rejected, not misread as a folder",
          "folder" in file_as_folder_report.lower() and "file" in file_as_folder_report.lower())

    referenced_folder_report = at.ide_analyze_folder_for_deletion("dead_pkg")
    check("folder analysis lists the contained file",
          "helper.py" in referenced_folder_report)
    check("folder analysis flags a referenced folder as not clearly dead",
          "NOT clearly dead" in referenced_folder_report)
    check("folder analysis surfaces the referencing file/line",
          "uses_dead_pkg.py" in referenced_folder_report)

    unused_folder_report = at.ide_analyze_folder_for_deletion("unused_pkg")
    check("folder analysis finds no references for a genuinely unused folder",
          "No references" in unused_folder_report)

    folder_delete_msg = at.ide_delete_folder("unused_pkg")
    time.sleep(0.1)
    check("folder delete succeeded after analysis", "Deleted" in folder_delete_msg)
    check("folder gone from its original path",
          "does not exist" in at.ide_exists("unused_pkg"))
    check("folder delete message points at the recoverable trash folder",
          ".friday_trash" in folder_delete_msg)
    check("folder physically sitting in .friday_trash on disk", any(
        "unused_pkg" in name
        for name in os.listdir(os.path.join(at._ide_app.root_dir, ".friday_trash"))))
    check("trashed folder kept its contents", any(
        os.path.isdir(os.path.join(at._ide_app.root_dir, ".friday_trash", name))
        and "scratch.py" in os.listdir(
            os.path.join(at._ide_app.root_dir, ".friday_trash", name))
        for name in os.listdir(os.path.join(at._ide_app.root_dir, ".friday_trash"))
        if "unused_pkg" in name))

    folder_redelete_msg = at.ide_delete_folder("unused_pkg")
    check("re-deleting a folder without a fresh analysis is refused",
          "Refusing" in folder_redelete_msg)

    at.ide_analyze_folder_for_deletion("dead_pkg")
    at.ide_edit_file("dead_pkg/helper.py", "return 1", "return 2")  # content changes post-analysis
    stale_folder_msg = at.ide_delete_folder("dead_pkg")
    check("folder delete refused when contents changed since analysis",
          "Refusing" in stale_folder_msg and "changed" in stale_folder_msg)
    check("edited-but-referenced folder survives the refused delete",
          "exists" in at.ide_exists("dead_pkg")
          and "does not" not in at.ide_exists("dead_pkg"))

    at.ide_create_folder("node_modules")
    skip_dir_report = at.ide_analyze_folder_for_deletion("node_modules")
    check("analyzing a SKIP_DIRS-named folder is refused outright",
          "infrastructure" in skip_dir_report.lower())
    skip_dir_delete = at.ide_delete_folder("node_modules")
    check("deleting a SKIP_DIRS-named folder is refused (no analysis was recorded)",
          "Refusing" in skip_dir_delete)

    root_folder_report = at.ide_analyze_folder_for_deletion(".")
    check("analyzing the workspace root folder is refused outright",
          "root" in root_folder_report.lower())

    # 4. Terminal: run a real command through the IDE's integrated terminal.
    term_result = at.ide_run_terminal_command(
        "python3 -c \"print('terminal-ok-' + str(1+1))\"", timeout_seconds=15)
    check("ide_run_terminal_command captures output", "terminal-ok-2" in term_result)
    time.sleep(0.1)
    snapshot = at.ide_get_terminal_output()
    check("ide_get_terminal_output shows the same output", "terminal-ok-2" in snapshot)

    # 4b. run_file / stop_task against a real runnable file.
    at.ide_write_file("run_me.py", "print('ran-from-friday')\n")

    def _open_run_me():
        app = at._ide_app
        app.open_file(os.path.join(app.root_dir, "run_me.py"))

    on_ide_thread(_open_run_me)
    time.sleep(0.1)
    run_msg = at.ide_run_file()
    check("ide_run_file started a task", "Running" in run_msg)
    time.sleep(1.0)
    time.sleep(0.2)
    out = at.ide_get_terminal_output()
    check("ide_run_file's output appears in the terminal", "ran-from-friday" in out)

    stop_msg = at.ide_stop_task()
    check("ide_stop_task reports nothing left running",
          "Nothing was running" in stop_msg or "Stopped" in stop_msg)

    # 4c. View/window tools (theme, panel toggles, zoom, opacity, topmost,
    # maximize) — Task 36's "close every UI-toggle gap" batch.
    theme_msg = at.ide_set_theme("black")
    check("ide_set_theme succeeded", "black" in theme_msg.lower())
    check("theme actually changed on the live app",
          on_ide_thread(lambda: at._ide_app.theme_name) == "black")
    at.ide_set_theme("grey")  # back to default for the rest of the run

    sidebar_before = on_ide_thread(lambda: at._ide_app.sidebar_visible)
    at.ide_toggle_view("sidebar")
    time.sleep(0.25)
    sidebar_after = on_ide_thread(lambda: at._ide_app.sidebar_visible)
    check("ide_toggle_view('sidebar') actually flips sidebar_visible",
          sidebar_before != sidebar_after)
    at.ide_toggle_view("sidebar")  # put it back
    time.sleep(0.25)

    panel_before = on_ide_thread(lambda: at._ide_app.panel_visible)
    at.ide_toggle_view("terminal")
    panel_after = on_ide_thread(lambda: at._ide_app.panel_visible)
    check("ide_toggle_view('terminal') actually flips panel_visible",
          panel_before != panel_after)
    if not panel_after:
        at.ide_toggle_view("terminal")  # leave it open for later steps

    bad_panel_msg = at.ide_toggle_view("not_a_real_panel")
    check("ide_toggle_view rejects an unknown panel name",
          "unknown" in bad_panel_msg.lower())

    size_before = on_ide_thread(lambda: at._ide_app.font_size)
    at.ide_zoom("in")
    size_after = on_ide_thread(lambda: at._ide_app.font_size)
    check("ide_zoom('in') increases font size", size_after > size_before)
    at.ide_zoom("reset")
    size_reset = on_ide_thread(lambda: at._ide_app.font_size)
    check("ide_zoom('reset') restores the default size", size_reset < size_after)

    opacity_before = on_ide_thread(lambda: at._ide_app.opacity)
    at.ide_set_opacity("more_transparent")
    opacity_after = on_ide_thread(lambda: at._ide_app.opacity)
    check("ide_set_opacity('more_transparent') lowers opacity",
          opacity_after < opacity_before)
    at.ide_set_opacity("more_opaque")  # restore

    topmost_before = on_ide_thread(lambda: getattr(at._ide_app, "_topmost", False))
    at.ide_toggle_always_on_top()
    topmost_after = on_ide_thread(lambda: getattr(at._ide_app, "_topmost", False))
    check("ide_toggle_always_on_top flips _topmost", topmost_before != topmost_after)
    at.ide_toggle_always_on_top()  # restore

    maximize_msg = at.ide_toggle_maximize()
    check("ide_toggle_maximize runs without error", "Toggled" in maximize_msg)
    at.ide_toggle_maximize()  # restore

    # 4d. Editor-mechanics tools (undo/redo, cut/copy/paste/select-all/
    # duplicate-line/move-line, goto-line, find & replace, close-tab).
    # Written directly to disk (not via ide_write_file) so there's no
    # agent typewriter animation racing with open_file() below — that
    # animation types its content into the editor asynchronously via
    # app.after(0, ...), which would otherwise still be landing
    # keystrokes in the undo stack while this section runs its own
    # undo/redo checks right after.
    editme_path = os.path.join(at._ide_app.root_dir, "editme.py")
    with open(editme_path, "w", encoding="utf-8") as fh:
        fh.write("alpha\nbeta\ngamma\n")

    def _open_editme():
        at._ide_app.refresh_explorer()
        at._ide_app.open_file(editme_path)

    on_ide_thread(_open_editme)
    time.sleep(0.1)

    goto_msg = at.ide_goto_line(2)
    check("ide_goto_line succeeded", "line 2" in goto_msg)
    cursor_line = on_ide_thread(
        lambda: at._ide_app.editor.text.index("insert").split(".")[0])
    check("cursor actually moved to line 2", cursor_line == "2")

    dup_msg = at.ide_editor_action("duplicate_line")
    check("ide_editor_action('duplicate_line') ran", "duplicate_line" in dup_msg)
    content_after_dup = on_ide_thread(
        lambda: at._ide_app.editor.text.get("1.0", "end-1c"))
    check("duplicate_line actually duplicated the line",
          content_after_dup.count("beta") == 2)

    undo_msg = at.ide_undo()
    check("ide_undo succeeded", "Undid" in undo_msg)
    content_after_undo = on_ide_thread(
        lambda: at._ide_app.editor.text.get("1.0", "end-1c"))
    check("undo actually removed the duplicated line",
          content_after_undo.count("beta") == 1)

    redo_msg = at.ide_redo()
    check("ide_redo succeeded", "Redid" in redo_msg)
    content_after_redo = on_ide_thread(
        lambda: at._ide_app.editor.text.get("1.0", "end-1c"))
    check("redo brought the duplicated line back",
          content_after_redo.count("beta") == 2)
    at.ide_undo()  # back to the clean 3-line state for what follows

    select_msg = at.ide_editor_action("select_all")
    check("ide_editor_action('select_all') ran", "select_all" in select_msg)
    has_sel = on_ide_thread(lambda: bool(at._ide_app.editor.text.tag_ranges("sel")))
    check("select_all actually created a selection", has_sel)

    bad_action_msg = at.ide_editor_action("not_a_real_action")
    check("ide_editor_action rejects an unknown action",
          "unknown" in bad_action_msg.lower())

    find_msg = at.ide_find_replace("gamma")
    check("ide_find_replace reports a match count for an existing word",
          "Found 1" in find_msg)

    replace_msg = at.ide_find_replace("gamma", "delta", replace_all=True)
    check("ide_find_replace with replace_all reports success",
          "Replaced" in replace_msg)
    content_after_replace = on_ide_thread(
        lambda: at._ide_app.editor.text.get("1.0", "end-1c"))
    check("find & replace actually changed the live buffer",
          "delta" in content_after_replace and "gamma" not in content_after_replace)

    copy_msg = at.ide_editor_action("copy")
    check("ide_editor_action('copy') ran without error", "copy" in copy_msg)

    # ide_list_open_tabs / ide_close_tab-by-name -- the "stay inside your
    # own panels" disambiguation flow: close/minimize-type requests about
    # an unnamed/ambiguous tab must list what's actually open rather than
    # guess, and closing by name must only act when exactly one tab
    # matches.
    at.ide_create_file("alpha_note.txt", "alpha\n")
    wait_until_tab_appears("alpha_note.txt")
    save_tab_by_name("alpha_note.txt")
    at.ide_create_file("beta_note.txt", "beta\n")
    tabs_listing = wait_until_tab_appears("beta_note.txt")
    save_tab_by_name("beta_note.txt")
    check("ide_list_open_tabs lists a freshly created tab",
          "alpha_note.txt" in tabs_listing and "beta_note.txt" in tabs_listing)
    check("ide_list_open_tabs marks the active tab",
          "-> beta_note.txt" in tabs_listing)

    at.ide_create_file("dup_alpha.txt", "a\n")
    wait_until_tab_appears("dup_alpha.txt")
    save_tab_by_name("dup_alpha.txt")
    at.ide_create_file("dup_beta.txt", "b\n")
    wait_until_tab_appears("dup_beta.txt")
    save_tab_by_name("dup_beta.txt")
    ambiguous_msg = at.ide_close_tab("dup_")
    check("closing an ambiguous name matches nothing and says so",
          "More than one" in ambiguous_msg)
    check("ambiguous close didn't actually close anything",
          "dup_alpha.txt" in at.ide_list_open_tabs()
          and "dup_beta.txt" in at.ide_list_open_tabs())

    missing_msg = at.ide_close_tab("totally_nonexistent_file.xyz")
    check("closing a name that matches nothing says so plainly",
          "No open tab matches" in missing_msg)

    specific_close_msg = at.ide_close_tab("alpha_note.txt")
    check("closing one specific tab by name succeeds",
          "Closed 'alpha_note.txt'" in specific_close_msg)
    check("that specific tab is actually gone, others remain",
          "alpha_note.txt" not in at.ide_list_open_tabs()
          and "beta_note.txt" in at.ide_list_open_tabs())

    # Clean up the rest of these scratch tabs so they don't interfere with
    # the "the tab is actually gone" count check right below.
    at.ide_close_tab("beta_note.txt")
    at.ide_close_tab("dup_alpha.txt")
    at.ide_close_tab("dup_beta.txt")

    # Save first so close_tab doesn't hit the (expected, by-design) native
    # "Save changes?" modal prompt that a real unsaved-tab close would —
    # see ide_close_tab's docstring; that prompt is intentional and
    # matches the UI's own close-button behavior, just not what this
    # particular check is testing.
    on_ide_thread(at._ide_app.save_file)
    n_buffers_before_close = on_ide_thread(lambda: len(at._ide_app.buffers))
    close_msg = at.ide_close_tab("current")
    check("ide_close_tab('current') succeeded", "Closed current" in close_msg)
    n_buffers_after_close = on_ide_thread(lambda: len(at._ide_app.buffers))
    check("the tab is actually gone",
          n_buffers_after_close == n_buffers_before_close - 1)

    # 4d-2. The "fully operational IDE" follow-up round's 10 new tools:
    # ide_open_file, ide_switch_tab, ide_get_active_tab_content,
    # ide_save_file, ide_save_all, ide_show_sidebar, ide_open_in_browser,
    # ide_clear_terminal, ide_list_tasks, ide_run_task.
    at.ide_create_file("deep_dive_a.txt", "first file\nsecond line\n")
    wait_until_tab_appears("deep_dive_a.txt")
    save_tab_by_name("deep_dive_a.txt")
    at.ide_create_file("deep_dive_b.txt", "another file\n")
    wait_until_tab_appears("deep_dive_b.txt")
    save_tab_by_name("deep_dive_b.txt")
    on_ide_thread(at._ide_app.save_all)  # avoid a blocking "Save changes?" modal
    at.ide_close_tab("all")

    # ide_open_file: opening an existing, not-currently-open file must
    # actually create/focus a visible tab for it -- unlike ide_read_file,
    # which never touches the UI.
    open_msg = at.ide_open_file("deep_dive_a.txt")
    check("ide_open_file reports success", "Opened 'deep_dive_a.txt'" in open_msg)
    check("ide_open_file actually created a visible tab for it",
          "deep_dive_a.txt" in at.ide_list_open_tabs())
    check("ide_open_file's tab is the active one",
          "-> deep_dive_a.txt" in at.ide_list_open_tabs())

    # Opening it again (already open) must focus the same tab, not
    # duplicate it.
    n_before_reopen = on_ide_thread(lambda: len(at._ide_app.buffers))
    at.ide_open_file("deep_dive_a.txt")
    n_after_reopen = on_ide_thread(lambda: len(at._ide_app.buffers))
    check("re-opening an already-open file doesn't duplicate its tab",
          n_before_reopen == n_after_reopen)

    # ide_open_file with a line number actually moves the cursor there.
    at.ide_open_file("deep_dive_a.txt", line=2)
    cursor_line = on_ide_thread(
        lambda: int(at._ide_app.editor.text.index("insert").split(".")[0]))
    check("ide_open_file(line=2) moved the cursor to line 2", cursor_line == 2)

    missing_open_msg = at.ide_open_file("does_not_exist_at_all.xyz")
    check("ide_open_file on a missing path says so instead of crashing",
          "doesn't exist" in missing_open_msg)

    # ide_switch_tab: open a second file, switch back to the first one by
    # name without closing the second, then again by 1-based position.
    at.ide_open_file("deep_dive_b.txt")
    check("deep_dive_b.txt is now the active tab",
          "-> deep_dive_b.txt" in at.ide_list_open_tabs())
    switch_msg = at.ide_switch_tab("deep_dive_a.txt")
    check("ide_switch_tab by name reports success",
          "Switched to 'deep_dive_a.txt'" in switch_msg)
    check("ide_switch_tab actually focused that tab, both still open",
          "-> deep_dive_a.txt" in at.ide_list_open_tabs()
          and "deep_dive_b.txt" in at.ide_list_open_tabs())
    n_tabs_now = on_ide_thread(lambda: len(at._ide_app.buffers))
    switch_by_pos_msg = at.ide_switch_tab(str(n_tabs_now))
    check("ide_switch_tab by 1-based position reports success",
          switch_by_pos_msg.startswith("Switched to"))
    missing_switch_msg = at.ide_switch_tab("nonexistent_tab_xyz")
    check("ide_switch_tab on an unmatched name says so",
          "No open tab matches" in missing_switch_msg)

    # ide_get_active_tab_content: must reflect the LIVE widget, including
    # an edit never written to disk, not whatever's already on disk.
    at.ide_switch_tab("deep_dive_a.txt")

    def _type_unsaved_edit():
        at._ide_app.editor.text.insert("end", "UNSAVED-LIVE-EDIT\n")
        # A raw, programmatic .insert() still fires the Text widget's
        # <<Modified>> event like a real keystroke would, but only on
        # Tk's idle loop a moment later (see save_file's own comment on
        # this) -- call mark_dirty() directly too so this test doesn't
        # have to race that idle callback to see "modified" turn True.
        at._ide_app.mark_dirty()

    on_ide_thread(_type_unsaved_edit)
    on_disk = at.ide_read_file("deep_dive_a.txt")
    check("the unsaved edit is NOT yet on disk (sanity check)",
          "UNSAVED-LIVE-EDIT" not in on_disk)
    live_content_msg = at.ide_get_active_tab_content()
    check("ide_get_active_tab_content sees the live unsaved edit",
          "UNSAVED-LIVE-EDIT" in live_content_msg)
    check("ide_get_active_tab_content flags the tab as having unsaved changes",
          "unsaved changes" in live_content_msg)

    # ide_save_file: persists that exact live content (including the
    # unsaved edit above) to disk, same as Ctrl+S.
    save_one_msg = at.ide_save_file()
    check("ide_save_file reports success", "Saved 'deep_dive_a.txt'" in save_one_msg)
    on_disk_after_save = at.ide_read_file("deep_dive_a.txt")
    check("ide_save_file actually wrote the live edit to disk",
          "UNSAVED-LIVE-EDIT" in on_disk_after_save)

    # ide_save_all: dirty a second buffer (without switching the save
    # path through ide_save_file) and confirm save_all catches it too.
    at.ide_switch_tab("deep_dive_b.txt")

    def _type_second_unsaved_edit():
        at._ide_app.editor.text.insert("end", "SECOND-UNSAVED-EDIT\n")
        at._ide_app.mark_dirty()

    on_ide_thread(_type_second_unsaved_edit)
    save_all_msg = at.ide_save_all()
    check("ide_save_all reports at least one file saved",
          save_all_msg.startswith("Saved ") and "Saved 0" not in save_all_msg)
    check("ide_save_all actually wrote that edit to disk too",
          "SECOND-UNSAVED-EDIT" in at.ide_read_file("deep_dive_b.txt"))

    on_ide_thread(at._ide_app.save_all)  # avoid a blocking "Save changes?" modal
    at.ide_close_tab("all")

    # ide_show_sidebar: every documented view actually switches the
    # sidebar's live mode, and always leaves it visible.
    for view in ("explorer", "search", "git", "run", "extensions"):
        msg = at.ide_show_sidebar(view)
        check(f"ide_show_sidebar('{view}') reports success",
              f"showing {view}" in msg)
        actual_mode = on_ide_thread(lambda: at._ide_app.sidebar.mode)
        is_visible = on_ide_thread(lambda: at._ide_app.sidebar_visible)
        check(f"ide_show_sidebar('{view}') actually set the live mode",
              actual_mode == view)
        check(f"ide_show_sidebar('{view}') left the sidebar visible",
              bool(is_visible))
    bad_sidebar_msg = at.ide_show_sidebar("not_a_real_view")
    check("ide_show_sidebar rejects an unknown view",
          "Unknown view" in bad_sidebar_msg)
    at.ide_show_sidebar("explorer")  # leave it in the normal default view

    # ide_clear_terminal: must not raise even with nothing in the panel.
    clear_msg = at.ide_clear_terminal()
    check("ide_clear_terminal reports success", "Cleared" in clear_msg)

    # ide_list_tasks / ide_run_task: write a recognizable project-task
    # trigger (a main.py entrypoint) so there's a real, known task label
    # to look for and actually run, rather than trusting whatever this
    # scratch workspace happens to already contain.
    at.ide_create_file("main.py", "print('ide_run_task worked')\n")
    wait_until_tab_appears("main.py")
    save_tab_by_name("main.py")
    on_ide_thread(at._ide_app.save_all)
    at.ide_close_tab("all")

    tasks_listing = at.ide_list_tasks()
    check("ide_list_tasks finds the real detected main.py task",
          "Python: main.py" in tasks_listing and "Error" not in tasks_listing)

    no_match_msg = at.ide_run_task("definitely_not_a_real_task_xyz")
    check("ide_run_task on an unmatched label says so instead of running anything",
          "No task matches" in no_match_msg)

    run_task_msg = at.ide_run_task("Python: main.py")
    check("ide_run_task runs the real, matched task",
          "Running 'Python: main.py'" in run_task_msg)
    time.sleep(1.0)
    check("the task Friday ran actually produced its expected output",
          "ide_run_task worked" in at.ide_get_terminal_output())
    at.ide_stop_task()

    # ide_open_in_browser: with nothing running and no HTML file open,
    # must report that plainly rather than claiming success or raising.
    on_ide_thread(at._ide_app.save_all)  # avoid a blocking "Save changes?" modal
    at.ide_close_tab("all")
    browser_msg = at.ide_open_in_browser()
    check("ide_open_in_browser says plainly when there's nothing to open",
          "Nothing to open" in browser_msg)

    # ...but with an HTML file active, it must actually attempt to open
    # it (webbrowser.open is best-effort/sandboxed here, so just confirm
    # the tool recognizes it as openable rather than faking success
    # blindly beforehand).
    at.ide_create_file("page.html", "<html><body>hi</body></html>\n")
    wait_until_tab_appears("page.html")
    save_tab_by_name("page.html")
    at.ide_open_file("page.html")
    html_browser_msg = at.ide_open_in_browser()
    check("ide_open_in_browser opens a real HTML file instead of saying 'nothing to open'",
          "page.html" in html_browser_msg and "Nothing to open" not in html_browser_msg)
    on_ide_thread(at._ide_app.save_all)  # avoid a blocking "Save changes?" modal
    at.ide_close_tab("all")

    # 4e. Explorer-extra tools (reveal in file manager, open in integrated
    # terminal, copy path).
    reveal_msg = at.ide_reveal_in_file_manager("editme.py")
    check("ide_reveal_in_file_manager runs without raising",
          "Revealed" in reveal_msg)

    open_term_msg = at.ide_open_in_integrated_terminal(".")
    check("ide_open_in_integrated_terminal succeeded", "Terminal is now" in open_term_msg)
    term_cwd = on_ide_thread(lambda: at._ide_app.term_cwd)
    check("open_in_integrated_terminal actually changed term_cwd",
          os.path.abspath(term_cwd) == os.path.abspath(at._ide_app.root_dir))

    copy_path_msg = at.ide_copy_path("editme.py", relative=True)
    check("ide_copy_path (relative) reports the relative path",
          copy_path_msg.strip().endswith("editme.py")
          and at._ide_app.root_dir not in copy_path_msg)

    # 4f. First-class git tools (init, status, add, commit, branch, checkout;
    # push/pull need a real remote so they're only checked for "doesn't
    # raise and returns text", not for success).
    git_init_msg = at.ide_git_init()
    check("ide_git_init succeeded", "Initialized" in git_init_msg)

    at.ide_run_terminal_command('git config user.email "friday@example.com"')
    at.ide_run_terminal_command('git config user.name "Friday Test"')

    status_msg = at.ide_git_status()
    check("ide_git_status returns real git output",
          "branch" in status_msg.lower() or "untracked" in status_msg.lower())

    add_msg = at.ide_git_add()
    check("ide_git_add (stage all) runs without error", "error" not in add_msg.lower())

    commit_msg = at.ide_git_commit("friday test commit")
    check("ide_git_commit ran", "error" not in commit_msg.lower())

    branch_msg = at.ide_git_branch("feature-x")
    check("ide_git_branch (create) ran", "error" not in branch_msg.lower())

    list_branches_msg = at.ide_git_branch()
    check("ide_git_branch (list) shows the new branch",
          "feature-x" in list_branches_msg)

    checkout_msg = at.ide_git_checkout("feature-x")
    check("ide_git_checkout ran", "error" not in checkout_msg.lower())
    branch_after_checkout = at.ide_run_terminal_command("git branch --show-current")
    check("checkout actually switched branches",
          "feature-x" in branch_after_checkout)

    push_msg = at.ide_git_push()
    check("ide_git_push returns text instead of raising (no remote configured)",
          isinstance(push_msg, str) and len(push_msg) >= 0)
    pull_msg = at.ide_git_pull()
    check("ide_git_pull returns text instead of raising (no remote configured)",
          isinstance(pull_msg, str) and len(pull_msg) >= 0)

    # 4g. Every one of Task 36's new tools must disappear once Agent Mode
    # is off, exactly like the original ide_* tools already do.
    new_tool_names = {
        "ide_set_theme", "ide_toggle_view", "ide_zoom", "ide_set_opacity",
        "ide_toggle_always_on_top", "ide_toggle_maximize", "ide_undo",
        "ide_redo", "ide_editor_action", "ide_goto_line", "ide_find_replace",
        "ide_close_tab", "ide_reveal_in_file_manager",
        "ide_open_in_integrated_terminal", "ide_copy_path", "ide_git_init",
        "ide_git_status", "ide_git_add", "ide_git_commit", "ide_git_push",
        "ide_git_pull", "ide_git_branch", "ide_git_checkout",
    }
    check("all 23 new tools present while Agent Mode is on",
          new_tool_names <= active_on)

    # 4h. The "fully operational IDE" follow-up round's 10 new tools must
    # also be visible while Agent Mode is on, and gone once it's off
    # (checked again down in part 5) -- same contract as every other
    # ide_* tool.
    deep_dive_tool_names = {
        "ide_open_file", "ide_switch_tab", "ide_get_active_tab_content",
        "ide_save_file", "ide_save_all", "ide_show_sidebar",
        "ide_open_in_browser", "ide_clear_terminal", "ide_list_tasks",
        "ide_run_task",
    }
    check("all 10 of the IDE deep-dive round's new tools present while on",
          deep_dive_tool_names <= active_on)

    # 5. Turn it back off -> the IDEApp is destroyed, tool list shrinks back.
    off_msg = at.agent_mode_off()
    check("agent_mode_off() succeeded", "off" in off_msg.lower() or "closed" in off_msg.lower())
    check("is_agent_mode_on() false again", not at.is_agent_mode_on())
    check("_ide_app is None again", at._ide_app is None)
    check("get_ide_pid() is None again", at.get_ide_pid() is None)
    active_after = {f.__name__ for f in at.get_active_gemini_tools()}
    check("back to 24 tools after closing (17 original + 7 new memory/task tools)", len(active_after) == 24)

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
