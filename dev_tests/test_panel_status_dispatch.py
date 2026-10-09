"""Regression test for Task 61's agent_tools.py dispatcher --
report_panel_status()/is_panel_minimized() -- exercised end to end
against a REAL ide/ide.py IDEApp, the same way test_agent_tools_ide.py
exercises the rest of agent_tools.py's IDE-facing surface.

Kept in its own file/process on purpose: agent_tools.agent_mode_on()
builds its IDEApp on a dedicated background Tcl/Tk worker thread (see
agent_tools._tk_worker_loop), and mixing that with a bare, main-thread
`ide_mod.IDEApp(...)` construction (as dev_tests/test_ide_minimize_pill.py
and dev_tests/test_panel_status_notifications.py's Parts A/B do) in the
same process corrupts Tcl's global async-handler state and crashes the
interpreter outright (confirmed by direct reproduction -- "Tcl_AsyncDelete:
async handler deleted by the wrong thread"). Same reason those two Tk
access patterns are already split across separate files elsewhere in
this suite.

Requires a display (Tkinter): run with
    DISPLAY=:99 python3 dev_tests/test_panel_status_dispatch.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ide"))

import agent_tools as at  # noqa: E402
import ide as ide_mod  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def on_ide_thread(fn):
    return at._run_on_main(fn)


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.03)
    return predicate()


def pill_outline(pill):
    return pill.canvas.itemcget(pill._pill_shape, "outline")


def _safe_call(fn):
    try:
        fn()
        return True
    except Exception:  # noqa: BLE001
        return False


def main():
    at.set_circle_rect_provider(lambda: (960, 60, 48))
    try:
        msg = at.agent_mode_on()
        check("agent_mode_on() succeeded", "Agent Mode is on" in msg)
        time.sleep(0.1)

        check("is_panel_minimized('ide') is False before minimizing",
              at.is_panel_minimized("ide") is False)

        on_ide_thread(lambda: at._ide_app.minimize_to_pill())
        wait_for(lambda: on_ide_thread(lambda: at._ide_app._pill) is not None)
        check("is_panel_minimized('ide') is True once minimized",
              at.is_panel_minimized("ide") is True)

        at.report_panel_status("ide", "waiting")
        outline = on_ide_thread(lambda: pill_outline(at._ide_app._pill))
        check("report_panel_status('ide', 'waiting') paints the real pill "
              "orange through the full dispatcher", outline == ide_mod.C["warn"])

        at.report_panel_status("ide", "done")
        outline2 = on_ide_thread(lambda: pill_outline(at._ide_app._pill))
        check("report_panel_status('ide', 'done') paints it green",
              outline2 == ide_mod.C["success"])

        at.report_panel_status("ide", "error")
        outline3 = on_ide_thread(lambda: pill_outline(at._ide_app._pill))
        check("report_panel_status('ide', 'error') paints it red",
              outline3 == ide_mod.C["term_err"])

        on_ide_thread(lambda: at._ide_app.restore_from_pill())
        wait_for(lambda: on_ide_thread(lambda: at._ide_app._pill) is None)
        check("is_panel_minimized('ide') is False again after restoring",
              at.is_panel_minimized("ide") is False)
        check("the status set while minimized survives the restore (same "
              "guarantee IDEApp.set_panel_status() gives directly)",
              on_ide_thread(lambda: at._ide_app._panel_status) == "error")

        on_ide_thread(lambda: at._ide_app.minimize_to_pill())
        wait_for(lambda: on_ide_thread(lambda: at._ide_app._pill) is not None)
        outline4 = on_ide_thread(lambda: pill_outline(at._ide_app._pill))
        check("re-minimizing through the dispatcher's own real IDE shows "
              "the same status that survived the cycle",
              outline4 == ide_mod.C["term_err"])

        check("report_panel_status() for an unknown app-panel key never "
              "raises (no record to update -- safe no-op)",
              _safe_call(lambda: at.report_panel_status("nonexistent-panel", "error")))
        check("is_panel_minimized() for an unknown key is simply False, "
              "never raises",
              _safe_call(lambda: at.is_panel_minimized("nonexistent-panel"))
              and at.is_panel_minimized("nonexistent-panel") is False)
    finally:
        at.agent_mode_off()
        at.set_circle_rect_provider(None)
        time.sleep(0.1)

    passed = sum(1 for _, ok in CHECKS if ok)
    total = len(CHECKS)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
