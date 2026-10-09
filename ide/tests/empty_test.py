"""No default untitled buffer, plus file creation and renaming."""
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)
os.environ.setdefault("DISPLAY", ":99")
import time  # noqa: E402
import traceback  # noqa: E402
import tkinter.messagebox as MB  # noqa: E402

MB.showerror = lambda *a, **k: None
MB.showinfo = lambda *a, **k: None
MB.askyesno = lambda *a, **k: True
MB.askyesnocancel = lambda *a, **k: False
import ide as V  # noqa: E402

V.messagebox = MB
V.IDEApp.open_url = lambda self, u: None
from _fixtures import make_fs_workspace  # noqa: E402

W = make_fs_workspace(tempfile.mkdtemp(prefix="ideempty"))
P, F = [], []


def chk(n, c, d=""):
    (P if c else F).append(f"{n} {d}")
    print(("  OK   " if c else "  FAIL ") + n + "  " + str(d), flush=True)


app = V.IDEApp(W)


def main():
    app.update()
    ed = app.editor

    # ---------- starts with nothing open ----------
    chk("no buffer at startup", len(app.buffers) == 0, len(app.buffers))
    chk("no untitled tab", not any("untitled" in b.get("name", "")
                                   for b in app.buffers))
    chk("empty surface shown", ed.empty_visible)
    chk("current index is -1", app.current == -1, app.current)
    chk("current_buffer() is None", app.current_buffer() is None)
    chk("title has no filename", "untitled" not in app.title().lower(),
        app.title())

    # ---------- nothing crashes with no buffer ----------
    for label, fn in (("save", app.save_file), ("save_all", app.save_all),
                      ("run_file", app.run_file),
                      ("close tab", app.close_current_tab),
                      ("update_status", app.update_status),
                      ("zoom", lambda: app.zoom(1)),
                      ("reset zoom", app.reset_zoom),
                      ("toggle minimap", app.toggle_minimap)):
        try:
            fn()
            app.update()
            chk(f"{label} safe with no buffer", True)
        except Exception as ex:  # noqa: BLE001
            chk(f"{label} safe with no buffer", False, repr(ex)[:60])

    # ---------- opening a file leaves the empty state ----------
    app.open_file(os.path.join(W, "b.txt"))
    app.update()
    chk("opening a file hides empty state", not ed.empty_visible)
    chk("one buffer open", len(app.buffers) == 1, len(app.buffers))

    # ---------- closing the last tab returns to empty, not untitled ----------
    app.close_current_tab()
    app.update()
    chk("closing last tab -> empty", len(app.buffers) == 0 and ed.empty_visible,
        f"{len(app.buffers)} buffers")
    chk("no untitled resurrected",
        not any("untitled" in b.get("name", "") for b in app.buffers))

    # ---------- Ctrl+N still works on demand ----------
    app.new_file()
    app.update()
    chk("Ctrl+N creates a scratch buffer", len(app.buffers) == 1)
    chk("scratch buffer is editable", not ed.empty_visible)
    ed.text.insert("1.0", "hello")
    app.update()
    app.buffers[0]["modified"] = False
    app.close_current_tab()
    app.update()

    # ---------- creating files ----------
    p = app.fs.create_file("brand_new.py", "print('x')\n")
    app.update()
    time.sleep(0.3)
    app.update()
    chk("fs.create_file writes", os.path.isfile(p))
    app.open_file(p)
    app.update()
    chk("new file opens", app.current_buffer()["name"] == "brand_new.py")
    chk("content correct", "print('x')" in ed.text.get("1.0", "end"))

    # ---------- renaming ----------
    app.fs.rename("brand_new.py", "renamed_now.py")
    app.update()
    time.sleep(0.3)
    app.update()
    chk("rename on disk", os.path.isfile(os.path.join(W, "renamed_now.py"))
        and not os.path.exists(os.path.join(W, "brand_new.py")))
    chk("open tab follows rename",
        app.current_buffer()["name"] == "renamed_now.py",
        app.current_buffer()["name"])

    # F2 path
    chk("rename_current exists", callable(app.rename_current))
    app.close_current_tab()
    app.update()
    chk("rename_current safe with no buffer",
        app.rename_current() is None or True)

    # ---------- explorer header actions ----------
    sb = app.sidebar
    chk("header target dir defaults to root",
        sb._target_dir() == app.root_dir, sb._target_dir())
    chk("collapse_all callable", callable(sb.collapse_all))
    sb.collapse_all()
    app.update()
    chk("collapse_all runs", True)
    for icon in ("new-file", "new-folder", "refresh", "collapse"):
        try:
            b = V.icon_button(app, icon, size=16, bg=V.C["sidebar"])
            b.destroy()
            chk(f"icon '{icon}' draws", True)
        except Exception as ex:  # noqa: BLE001
            chk(f"icon '{icon}' draws", False, repr(ex)[:50])

    # ---------- tab context menu ----------
    app.open_file(os.path.join(W, "b.txt"))
    app.update()
    import tkinter as tk
    posted = {}
    orig = tk.Menu.tk_popup
    tk.Menu.tk_popup = lambda self, *a, **k: posted.setdefault(
        "labels", [self.entrycget(i, "label")
                   for i in range(self.index("end") + 1)
                   if self.type(i) == "command"])

    class E:
        x_root = y_root = 50
    app.tab_menu(E(), 0)
    tk.Menu.tk_popup = orig
    labs = posted.get("labels", [])
    chk("tab menu opens", len(labs) >= 5, f"{len(labs)} items")
    chk("tab menu has Rename", "Rename…" in labs, labs[:3])

    # ---------- empty state survives a theme switch ----------
    app.close_all_tabs()
    app.update()
    chk("close_all -> empty", len(app.buffers) == 0)
    app.set_theme("black")
    for _ in range(8):
        app.update()
        time.sleep(0.08)
    chk("empty state after theme switch", app.editor.empty_visible)
    app.open_file(os.path.join(W, "b.txt"))
    app.update()
    chk("still opens files after theme switch", not app.editor.empty_visible)
    app.set_theme("grey")
    app.update()


try:
    main()
except Exception:  # noqa: BLE001
    traceback.print_exc()
    F.append("EXCEPTION")
print(f"\n===== PASS {len(P)}   FAIL {len(F)} =====")
for f in F:
    print("   XX", f)
app.destroy()
shutil.rmtree(W, ignore_errors=True)
