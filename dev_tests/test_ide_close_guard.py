"""Regression test for: "the IDE should stay open until I tell Friday to
close it" -- while Friday is driving the IDE (agent_controlled), a human
trying to close the window directly (Alt+F4 / the window manager's own
close request, or the File > Exit menu item) must NOT close it. Only
Friday's own agent_mode_off() tool (which calls close_window() straight,
not through either of those two paths) is allowed to. Standalone
(not agent-controlled) runs must behave exactly as before: either path
closes the window normally, unsaved-changes prompt and all.

Kept in the persisted workspace (not /tmp) so it survives a fresh
sandbox session.

Run with:
    DISPLAY=:99 python3 dev_tests/test_ide_close_guard.py
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


def alive(app):
    try:
        return bool(app.winfo_exists())
    except tk.TclError:
        return False


def main():
    # 1. Agent-controlled: neither the WM_DELETE_WINDOW protocol handler
    # nor the File > Exit menu item (both wired to the same
    # _human_requested_close) may actually close the window.
    d = tempfile.mkdtemp(prefix="friday-close-guard-")
    app = ide_mod.IDEApp(d, agent_controlled=True)
    app.update()

    app._human_requested_close()
    app.update()
    check("agent-controlled: Alt+F4/WM_DELETE_WINDOW does not close it",
          alive(app))
    check("agent-controlled: a nudge message is shown instead",
          "Friday" in app.status.pos.cget("text"))

    # File > Exit is wired to the exact same guarded handler -- the menu
    # itself is built from a plain local dict inside _build_menubar()
    # with nothing kept on self to introspect at runtime, so check the
    # wiring the simple, direct way: the source line itself.
    ide_src_path = os.path.join(
        os.path.dirname(os.path.abspath(ide_mod.__file__)), "ide.py")
    with open(ide_src_path, encoding="utf-8") as f:
        ide_src = f.read()
    check('File > Exit is wired to the close guard, not close_window directly',
          '"Exit", "", self._human_requested_close' in ide_src)

    # 2. Friday's own close path (agent_mode_off() -> close_window(), never
    # _human_requested_close()) must still work, unaffected by the guard.
    app.close_window()
    app.update()
    check("Friday's own close_window() still actually closes it", not alive(app))

    # 3. Standalone (not agent-controlled): both paths behave exactly as
    # before -- the window closes normally.
    d2 = tempfile.mkdtemp(prefix="friday-close-guard-standalone-")
    app2 = ide_mod.IDEApp(d2, agent_controlled=False)
    app2.update()
    app2._human_requested_close()
    app2.update()
    check("standalone: Alt+F4/WM_DELETE_WINDOW closes normally",
          not alive(app2))

    d3 = tempfile.mkdtemp(prefix="friday-close-guard-standalone2-")
    app3 = ide_mod.IDEApp(d3, agent_controlled=False)
    app3.update()
    app3._human_requested_close()  # what File > Exit is wired to too
    app3.update()
    check("standalone: File > Exit (same handler) closes normally too",
          not alive(app3))

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
