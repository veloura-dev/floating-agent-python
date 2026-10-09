"""Task 28 sub-requirement (a) coverage: the Activity Bar (the narrow
icon rail along the window's left edge) and the Source Control sidebar
view it exposes.

Every view the Activity Bar switches to (Explorer, Search, Source
Control, Run and Debug, Extensions) already existed in SideBar before
this; this only gives them a visible way in, matching the reference
screenshot's layout, using nothing invented for the occasion. Also
covers the Source Control view actually listing real git changes (with
the same M/C badges Explorer shows) and the "Initialize Repository"
button, which used to be inert dead code and now really runs `git init`.

Requires a display (Tkinter):
    DISPLAY=:99 python3 dev_tests/test_ide_activity_bar.py
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


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _all_texts(widget):
    """Every non-empty `text` option in this widget's whole subtree --
    used to find labels/buttons in the sidebar without caring exactly
    how they're nested."""
    out = []
    try:
        t = widget.cget("text")
    except Exception:  # noqa: BLE001
        t = None
    if t:
        out.append(t)
    for child in widget.winfo_children():
        out.extend(_all_texts(child))
    return out


def main():
    msg = at.agent_mode_on()
    check("agent_mode_on() succeeded", "Agent Mode is on" in msg)
    app = at._ide_app
    C = at._ide_module.C
    # Give the window manager a moment to actually map/realize the
    # just-opened window before the first simulated click -- the IDE's
    # own native mainloop keeps running on its dedicated thread the
    # whole time this test sleeps, so this is purely waiting for Xvfb's
    # side of the geometry negotiation, not polling anything ourselves.
    time.sleep(0.3)

    # ---- 1. the rail itself: all five existing views get a button ----
    def _rail_basics():
        bar = app.activity_bar
        names = set(bar._buttons.keys())
        return (bar.winfo_exists(),
               names == {"explorer", "search", "git", "run", "extensions"})
    exists, names_ok = on_ide_thread(_rail_basics)
    check("activity bar is a real, live widget", exists)
    check("activity bar has one button per existing sidebar view",
          names_ok)

    # ---- 2. clicking each icon switches the sidebar view, and the rail
    # highlights whichever one is active (and only that one) ----
    for mode in ("search", "git", "run", "extensions", "explorer"):
        def _click_and_check(m=mode):
            app.activity_bar._buttons[m].event_generate(
                "<Button-1>", x=5, y=5)
            app.update()
            bars = app.activity_bar._bars
            active_bg = bars[m].cget("bg")
            others_bg = [b.cget("bg") for n, b in bars.items() if n != m]
            return (app.sidebar.mode, active_bg, others_bg)

        got_mode, active_bg, others_bg = on_ide_thread(_click_and_check)
        check(f"clicking the {mode} icon switches SideBar to {mode}",
              got_mode == mode)
        check(f"the {mode} icon's accent bar lights up (and only it)",
              active_bg == C["accent"] and
              all(b == C["activity"] for b in others_bg))

    # ---- 3. Source Control view: no repo yet -> shows the (now really
    # working) "Initialize Repository" button ----
    plain_dir = tempfile.mkdtemp(prefix="friday-actbar-")

    def _show_git_on(d):
        app.set_root(d)
        app.show_sidebar_mode("explorer")  # force a real mode change
        app.show_sidebar_mode("git")
        app.update_idletasks()
        return _all_texts(app.sidebar)

    texts_before_init = on_ide_thread(lambda: _show_git_on(plain_dir))
    check("fresh folder has no .git yet",
          not os.path.isdir(os.path.join(plain_dir, ".git")))
    check("Source Control view offers to Initialize Repository",
          any("Initialize Repository" in t for t in texts_before_init))

    on_ide_thread(lambda: app.git_init_repository())
    time.sleep(0.3)
    check("git_init_repository() really runs `git init`",
          os.path.isdir(os.path.join(plain_dir, ".git")))

    # ---- 4. Source Control view: real repo with real changes, listing
    # exactly what Explorer's git-status badges would also flag ----
    repo = tempfile.mkdtemp(prefix="friday-actbar-repo-")
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "friday@example.com")
    git(repo, "config", "user.name", "Friday Test")
    os.makedirs(os.path.join(repo, "src"))
    with open(os.path.join(repo, "src", "main.py"), "w") as fh:
        fh.write("print('hi')\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "baseline")
    with open(os.path.join(repo, "src", "main.py"), "w") as fh:
        fh.write("print('hi there')\n")
    with open(os.path.join(repo, "src", "new_feature.py"), "w") as fh:
        fh.write("x = 1\n")

    texts = on_ide_thread(lambda: _show_git_on(repo))
    joined = " | ".join(texts)
    check("Source Control view lists the modified file",
          "src/main.py" in joined)
    check("Source Control view lists the newly created file",
          "src/new_feature.py" in joined)
    check("Source Control view shows a change count heading",
          any("CHANGES" in t for t in texts))

    # Give the freshly (re)built Source Control rows a moment to actually
    # get laid out/mapped by the window manager before clicking one --
    # same reasoning as the settle delay after agent_mode_on() above.
    time.sleep(0.3)

    # Clicking a changed row opens it in the editor, same as Explorer.
    def _click_row_and_check():
        def find(widget):
            try:
                t = widget.cget("text")
            except Exception:  # noqa: BLE001
                t = None
            if t and "src/main.py" in t:
                return widget
            for c in widget.winfo_children():
                found = find(c)
                if found is not None:
                    return found
            return None
        lbl = find(app.sidebar)
        if lbl is None:
            return False
        lbl.event_generate("<Button-1>", x=2, y=2)
        app.update()
        buf = app.current_buffer()
        return bool(buf and buf.get("path", "").endswith(
            os.path.join("src", "main.py")))

    check("clicking a Source Control row opens that file in the editor",
          on_ide_thread(_click_row_and_check))

    off_msg = at.agent_mode_off()
    check("agent_mode_off() succeeded",
          "off" in off_msg.lower() or "closed" in off_msg.lower())

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
