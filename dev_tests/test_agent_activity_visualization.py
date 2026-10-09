"""Task 28 regression coverage: the "agent activity" visualization layer
added on top of the real ide/ide.py IDEApp --

  * git-status badges (amber "M" checkbox for modified paths, green "C"
    checkbox for new/untracked paths, composited onto the existing
    hand-drawn file/folder icons)
  * the status-bar "agent status" chip
  * the Explorer-row highlight + filename typewriter used when Friday
    creates a file/folder
  * the editor-content typewriter used when Friday writes code, including
    the critical correctness guarantee that a half-typed on-screen
    animation can never be saved/run in place of the file's real,
    already-on-disk content (ide_write_file/create_file are instant on
    disk; only the on-screen "typing" catches up afterwards)

Built the same way as dev_tests/test_agent_tools_ide.py: a real IDEApp,
in-process, on its own Tk thread via agent_tools.agent_mode_on() --
nothing here is mocked.

Requires a display (Tkinter):
    DISPLAY=:99 python3 dev_tests/test_agent_activity_visualization.py
"""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_tools as at  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def on_ide_thread(fn):
    return at._run_on_main(fn)


def wait_until(pred, timeout=5.0, interval=0.03):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if on_ide_thread(pred):
            return True
        time.sleep(interval)
    return bool(on_ide_thread(pred))


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def make_git_repo():
    repo = tempfile.mkdtemp(prefix="friday-gitrepo-")
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "friday@example.com")
    git(repo, "config", "user.name", "Friday Test")
    os.makedirs(os.path.join(repo, "pkg"), exist_ok=True)
    os.makedirs(os.path.join(repo, "untouched_dir"), exist_ok=True)
    with open(os.path.join(repo, "pkg", "unchanged.py"), "w") as fh:
        fh.write("x = 1\n")
    with open(os.path.join(repo, "pkg", "to_modify.py"), "w") as fh:
        fh.write("x = 1\n")
    with open(os.path.join(repo, "untouched_dir", "also_unchanged.py"),
             "w") as fh:
        fh.write("z = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "baseline")
    return repo


def main():
    # ---- 1. build_badge_icon / build_icon compositing (no IDE needed) ----
    import tkinter as tk
    ide_mod = at._ide_module
    probe_root = tk.Tk()
    probe_root.withdraw()
    base = ide_mod.build_icon(tk, "app.py", 18)
    m_badge = ide_mod.build_badge_icon(tk, base, "M", 18)
    c_badge = ide_mod.build_badge_icon(tk, base, "C", 18)
    check("badge composite is wider than the plain icon",
          m_badge.width() > base.width())
    check("badge composite keeps the icon's full height",
          m_badge.height() == base.height())
    check("'M' and 'C' badges are the same size as each other",
          m_badge.width() == c_badge.width())
    check("badge glyph tables define exactly M and C",
          set(ide_mod.BADGE_GLYPHS.keys()) == {"M", "C"})
    probe_root.destroy()

    # ---- boot the real IDE ----
    msg = at.agent_mode_on()
    check("agent_mode_on() succeeded", "Agent Mode is on" in msg)
    app = at._ide_app
    check("_ide_app is live", app is not None)

    # ---- 2. git status map against a REAL git repo ----
    repo = make_git_repo()
    # modify a tracked file -> "M"
    with open(os.path.join(repo, "pkg", "to_modify.py"), "w") as fh:
        fh.write("x = 2\n")
    # new, never-committed file in a brand new nested folder -> "C",
    # and that status must propagate up to the new folder too
    os.makedirs(os.path.join(repo, "new_feature"), exist_ok=True)
    with open(os.path.join(repo, "new_feature", "brand_new.py"), "w") as fh:
        fh.write("y = 1\n")

    def _set_root_and_scan():
        app.set_root(repo)
        return app.git_status_map()

    status = on_ide_thread(_set_root_and_scan)
    mod_path = os.path.normpath(os.path.join(repo, "pkg", "to_modify.py"))
    unchanged_path = os.path.normpath(
        os.path.join(repo, "pkg", "unchanged.py"))
    new_file_path = os.path.normpath(
        os.path.join(repo, "new_feature", "brand_new.py"))
    new_dir_path = os.path.normpath(os.path.join(repo, "new_feature"))
    pkg_dir_path = os.path.normpath(os.path.join(repo, "pkg"))

    check("modified tracked file is flagged M", status.get(mod_path) == "M")
    check("unrelated tracked file has no badge",
          unchanged_path not in status)
    check("brand new untracked file is flagged C",
          status.get(new_file_path) == "C")
    check("new file's containing folder inherits the C badge",
          status.get(new_dir_path) == "C")
    check("modified file's containing folder inherits the M badge",
          status.get(pkg_dir_path) == "M")

    # Explorer actually renders the badges: after a root rebuild, the
    # SideBar._icon() cache should hold a wider, badge-composited image
    # for the modified folder's row (visible at the root level without
    # needing to expand anything -- lazily-loaded children of collapsed
    # folders, like pkg/to_modify.py itself, aren't materialized as tree
    # rows until opened, so this checks the ancestor folder instead,
    # exactly the row a user actually sees first), distinct from an
    # unrelated, unchanged folder's plain icon.
    untouched_dir_path = os.path.normpath(
        os.path.join(repo, "untouched_dir"))

    def _icons_for_rebuilt_tree():
        app.refresh_explorer()
        app.update_idletasks()
        sb = app.sidebar

        def find(path):
            for k in sb.tree.get_children(sb.root_node):
                vals = sb.tree.item(k, "values")
                if vals and os.path.normpath(vals[0]) == path:
                    return sb.tree.item(k, "image")
            return None
        return find(pkg_dir_path), find(untouched_dir_path)

    modified_img, plain_img = on_ide_thread(_icons_for_rebuilt_tree)
    check("Explorer draws a distinct (badged) icon for the modified folder",
          bool(modified_img) and modified_img != plain_img)

    # ---- 3. status bar "agent status" chip ----
    def _status_chip_checks():
        app.status.set_agent_status("Creating demo.py…", "create")
        text1 = app.status.agent.cget("text")
        app.status.set_agent_status("Writing demo.py…", "write")
        text2 = app.status.agent.cget("text")
        app.status.clear_agent_status()
        text3 = app.status.agent.cget("text")
        return text1, text2, text3

    t1, t2, t3 = on_ide_thread(_status_chip_checks)
    check("agent status chip shows the 'create' message", "Creating" in t1)
    check("agent status chip updates to the 'write' message", "Writing" in t2)
    check("clear_agent_status() empties the chip", t3 == "")

    # ---- 4. Explorer filename typewriter ----
    def _typewriter_label_setup():
        node = app.sidebar.tree.insert(
            app.sidebar.root_node, "end", text="", values=("/tmp/x",))
        app._typewriter_tree_label(node, "newly_created.py", interval_ms=5)
        return node

    node = on_ide_thread(_typewriter_label_setup)
    check("typewriter starts from an empty label",
          on_ide_thread(lambda: app.sidebar.tree.item(node, "text")) == "")
    wait_until(lambda: app.sidebar.tree.item(node, "text") ==
               "newly_created.py", timeout=3)
    check("typewriter eventually types out the full filename",
          on_ide_thread(lambda: app.sidebar.tree.item(node, "text"))
          == "newly_created.py")

    # ---- 5. editor content typewriter: normal completion ----
    target = os.path.join(repo, "typed_by_friday.py")
    full_code = "def greet():\n    return 'hello from friday'\n" * 4

    def _start_write_anim():
        app.animate_agent_write(target, full_code)
        buf = app.current_buffer()
        return buf is not None, buf.get("content", "") if buf else ""

    has_buf, early_content = on_ide_thread(_start_write_anim)
    check("animate_agent_write opens a live buffer for the target file",
          has_buf)
    check("the editor text is still mid-typing just after starting "
          "(not instantly pasted)", early_content != full_code)

    def _final_state():
        buf = app.current_buffer()
        return (buf.get("content", ""),
               app.editor.text.get("1.0", "end-1c"))

    wait_until(lambda: _final_state()[0] == full_code, timeout=5)
    final_content, final_widget_text = on_ide_thread(_final_state)
    check("typewriter eventually lands the exact full content in the buffer",
          final_content == full_code)
    check("typewriter eventually lands the exact full content on screen",
          final_widget_text == full_code)

    # ---- 6. CRITICAL: the disk file is correct the instant it's written,
    # regardless of how far the on-screen typewriter has gotten, and an
    # impatient save/run can never truncate it to a half-typed state. ----
    final_code = "print('this must survive a mid-animation save')\n" * 3
    rel_name = "critical_write.py"
    at.ide_write_file(rel_name, final_code)
    disk_text_immediately = open(
        os.path.join(repo, rel_name), encoding="utf-8").read()
    check("agent-written file is fully correct on disk immediately, "
          "before the on-screen typing animation has even started",
          disk_text_immediately == final_code)

    def _save_mid_animation():
        # The write above already opened+started animating this exact
        # buffer (ide_write_file -> WorkspaceFS.write(agent=True) ->
        # animate_agent_write_file -> animate_agent_write). Grab it while
        # it's still mid-typing and force a save right now, the way a
        # real Ctrl+S could race it.
        buf = app.current_buffer()
        still_typing = buf.get("content", "") != final_code
        app.save_file()
        with open(buf["path"], encoding="utf-8") as fh:
            saved_now = fh.read()
        return still_typing, saved_now

    still_typing, saved_now = on_ide_thread(_save_mid_animation)
    check("the animation really was still in flight when save_file() ran "
          "(otherwise this check proves nothing)", still_typing)
    check("save_file() mid-animation flushes to the full content instead "
          "of writing a half-typed truncation to disk",
          saved_now == final_code)

    # ---- 7. tab-switch mid-animation doesn't lose or corrupt content ----
    other_path = os.path.join(repo, "other_tab.py")
    with open(other_path, "w") as fh:
        fh.write("# pre-existing\n")

    def _switch_away_mid_animation():
        app.animate_agent_write(
            os.path.join(repo, "switch_target.py"),
            "line\n" * 300)
        animated_buf = app.current_buffer()
        app.open_file(other_path)
        return animated_buf

    animated_buf = on_ide_thread(_switch_away_mid_animation)
    check("switching tabs away mid-animation moves focus to the new tab",
          on_ide_thread(lambda: app.current_buffer() is not animated_buf))
    wait_until(lambda: animated_buf["content"] == "line\n" * 300, timeout=5)
    check("a buffer animated in the background still ends up with its "
          "exact full content after the user switches away",
          on_ide_thread(lambda: animated_buf["content"]) == "line\n" * 300)

    # ---- 8. Explorer highlight for agent activity ----
    def _highlight_roundtrip():
        node_a = app.sidebar.tree.insert(
            app.sidebar.root_node, "end", text="a", values=("/tmp/a",))
        app._highlight_tree_node(node_a)
        tagged = "agent-active" in app.sidebar.tree.item(node_a, "tags")
        app._unhighlight_tree_node(node_a)
        untagged = "agent-active" not in app.sidebar.tree.item(node_a,
                                                                "tags")
        return tagged, untagged, app._agent_highlight_node

    tagged, untagged, leftover = on_ide_thread(_highlight_roundtrip)
    check("_highlight_tree_node() tags the row", tagged)
    check("_unhighlight_tree_node() removes the tag again", untagged)
    check("no stray highlight node left tracked after unhighlighting",
          leftover is None)

    # Sections 5/7 exercised animate_agent_write() directly (bypassing
    # WorkspaceFS, which is what actually persists to disk) purely to
    # probe the animation/typewriter mechanics in isolation -- clear any
    # buffers that are left looking "dirty" as a result so the shutdown
    # below doesn't pop an (irrelevant, here) unsaved-changes prompt.
    on_ide_thread(lambda: [b.update(modified=False) for b in app.buffers])

    off_msg = at.agent_mode_off()
    check("agent_mode_off() succeeded",
          "off" in off_msg.lower() or "closed" in off_msg.lower())

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
