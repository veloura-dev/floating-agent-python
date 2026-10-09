"""Regression test for two follow-up requests, both from the same
reference screenshot of the user's own screen:

  (a) the agent-controlled IDE window must open at the *exact* on-screen
      position/size measured from that screenshot -- expressed as
      fractions of the real screen size (not a fixed pixel size scaled
      by DPI), so it lands in the same relative spot on any monitor:
      left margin ~5.4% of screen width, top margin ~7.4% of screen
      height, width ~89.7% of screen width, height ~89.4% of screen
      height. Standalone (non agent-controlled) runs must be completely
      unaffected -- still centered on screen as before.

  (b) when Agent Mode starts with no real folder open, agent_tools.py
      auto-creates a throwaway temp directory (prefixed "friday-empty-") so
      there's somewhere real on disk to write to right away. That raw,
      meaningless temp-folder name must never be shown to the user:
      while it's still genuinely empty, the Explorer shows a rich
      VS-Code-style "no folder open" empty state (Open Folder / Clone
      Repository) instead of a one-node tree; once it's no longer empty
      (or once set_root() points elsewhere), the window title and the
      Explorer's root label fall back to a friendly "Open Folder or
      Create New Workspace" prompt instead of the raw name. A real,
      explicitly-opened folder's own name must still be shown normally.

Kept in the persisted workspace (not /tmp) so it survives a fresh
sandbox session.

Run with:
    DISPLAY=:99 python3 dev_tests/test_ide_geometry_and_placeholder_label.py
"""
import os
import sys
import tempfile

import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ide"))

import ide as ide_mod  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def close(app):
    try:
        app.destroy()
    except tk.TclError:
        pass


def collect_texts(widget):
    """All tk.Label text and Canvas create_text strings under a widget,
    recursively -- used to inspect the empty-state UI's rendered copy
    (including rounded_button(), which draws its label on a Canvas)."""
    texts = []
    try:
        if isinstance(widget, tk.Label):
            texts.append(widget.cget("text"))
        if isinstance(widget, tk.Canvas):
            for item in widget.find_all():
                if widget.type(item) == "text":
                    texts.append(widget.itemcget(item, "text"))
    except tk.TclError:
        pass
    try:
        children = widget.winfo_children()
    except tk.TclError:
        children = []
    for child in children:
        texts.extend(collect_texts(child))
    return texts


def main():
    real_dir = tempfile.mkdtemp(prefix="geomtest-real-")
    placeholder_dir = tempfile.mkdtemp(prefix="friday-empty-")

    # ---------------- (a) exact agent-controlled geometry ----------------
    agent_app = ide_mod.IDEApp(start_dir=placeholder_dir, agent_controlled=True)
    try:
        agent_app.update_idletasks()
        sw = agent_app.winfo_screenwidth()
        sh = agent_app.winfo_screenheight()
        x, y, w, h = agent_app._final_geom

        exp_w, exp_h = int(sw * 0.897), int(sh * 0.894)
        exp_x, exp_y = int(sw * 0.054), int(sh * 0.074)

        check("agent-controlled width matches the measured layout exactly",
              w == exp_w)
        check("agent-controlled height matches the measured layout exactly",
              h == exp_h)
        check("agent-controlled x position matches the measured layout exactly",
              x == exp_x)
        check("agent-controlled y position matches the measured layout exactly",
              y == exp_y)
        # Sanity: a clear, deliberate gap on every edge, consistent with
        # the reference screenshot (not edge-to-edge/maximized).
        check("a real margin is left on the left edge", x > 0)
        check("a real margin is left on the top edge", y > 0)
        check("a real margin is left on the right edge", x + w < sw)
        check("a real margin is left on the bottom edge", y + h < sh)
    finally:
        close(agent_app)

    # ---------------- (a) standalone geometry is unaffected ----------------
    standalone_app = ide_mod.IDEApp(start_dir=real_dir, agent_controlled=False)
    try:
        standalone_app.update_idletasks()
        sw = standalone_app.winfo_screenwidth()
        sh = standalone_app.winfo_screenheight()
        x, y, w, h = standalone_app._final_geom
        check("standalone window is still centered horizontally",
              abs((x + w / 2) - sw / 2) <= 1)
        check("standalone window is not pinned to the agent-mode exact spot",
              not (x == int(sw * 0.054) and y == int(sh * 0.074)))
    finally:
        close(standalone_app)

    # ---------------- (b) placeholder workspace label ----------------
    ph_app = ide_mod.IDEApp(start_dir=placeholder_dir, agent_controlled=True)
    try:
        ph_app.update_idletasks()
        check("workspace_display_name() hides the raw friday-empty-* temp name",
              ph_app.workspace_display_name() == "Open Folder or Create New Workspace")

        ph_app._refresh_title()
        check("window title shows the friendly prompt, not the raw temp name",
              "Open Folder or Create New Workspace" in ph_app.title()
              and os.path.basename(placeholder_dir) not in ph_app.title())

        ph_app.sidebar.show("explorer")
        ph_app.update_idletasks()
        check("a genuinely empty placeholder shows the rich empty state, "
              "not a one-node tree",
              ph_app.sidebar.tree is None)
        texts = collect_texts(ph_app.sidebar._no_folder_frame)
        check("empty state shows the 'NO FOLDER OPENED' header",
              "NO FOLDER OPENED" in texts)
        check("empty state shows the 'not yet opened a folder' message",
              "You have not yet opened a folder." in texts)
        check("empty state has an 'Open Folder' button", "Open Folder" in texts)
        check("empty state shows the clone-locally message",
              "You can clone a repository locally." in texts)
        check("empty state has a 'Clone Repository' button",
              "Clone Repository" in texts)
        check("empty state never leaks the raw temp folder name",
              not any(os.path.basename(placeholder_dir) in t for t in texts))

        # Once Friday actually writes a real file into the placeholder, the
        # rich empty state must give way to a normal tree (still with the
        # friendly root label, since the folder's real name is still ugly).
        with open(os.path.join(placeholder_dir, "hello.py"), "w") as fh:
            fh.write("print('hi')\n")
        ph_app.refresh_explorer()
        ph_app.update_idletasks()
        check("writing a file switches out of the empty state",
              ph_app.sidebar.tree is not None)
        root_text = ph_app.sidebar.tree.item(
            ph_app.sidebar.root_node, "text").strip()
        check("Explorer root label still hides the raw name once populated",
              root_text == "OPEN FOLDER OR CREATE NEW WORKSPACE")
    finally:
        close(ph_app)

    # ---------------- (b) a real, explicitly-opened folder is unaffected ----------------
    real_app = ide_mod.IDEApp(start_dir=real_dir, agent_controlled=True)
    try:
        real_app.update_idletasks()
        real_name = os.path.basename(real_dir)
        check("workspace_display_name() returns the real folder's own name",
              real_app.workspace_display_name() == real_name)

        real_app.sidebar.show("explorer")
        root_text = real_app.sidebar.tree.item(real_app.sidebar.root_node, "text").strip()
        check("Explorer root label shows the real folder's own name",
              root_text == real_name.upper())

        # set_root() to the placeholder-prefixed dir mid-session must also
        # flip the label -- and back again when a real folder follows.
        real_app.set_root(placeholder_dir)
        check("set_root() to a friday-empty-* dir also shows the friendly prompt",
              real_app.workspace_display_name() == "Open Folder or Create New Workspace")
        real_app.set_root(real_dir)
        check("set_root() back to a real folder restores its own name",
              real_app.workspace_display_name() == real_name)
    finally:
        close(real_app)

    total = len(CHECKS)
    passed = sum(1 for _, ok in CHECKS if ok)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
