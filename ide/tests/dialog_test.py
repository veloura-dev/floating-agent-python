"""Drive the create / rename dialogs with real key events.

Earlier suites called app.fs.* directly, so a dialog that never accepted
keyboard input still passed every check. This one types into the actual
modal.

Two layers:
  * Tk-level - works on every platform. Key events are sent to the dialog
    window, so Tk must have routed focus to the entry for them to land.
  * OS-level - if xdotool is present (X11) the same flows are repeated
    through the real input stack. Skipped, not failed, when unavailable.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)
os.environ.setdefault("DISPLAY", ":99")
import tkinter as tk  # noqa: E402
import tkinter.messagebox as MB  # noqa: E402

MB.showerror = lambda *a, **k: None
MB.showinfo = lambda *a, **k: None
MB.askyesno = lambda *a, **k: True
import ide as V  # noqa: E402

V.messagebox = MB
from _fixtures import make_fs_workspace  # noqa: E402

W = make_fs_workspace(tempfile.mkdtemp(prefix="idedlg"))
P, F = [], []


def chk(n, c, d=""):
    (P if c else F).append(f"{n} {d}")
    print(("  OK   " if c else "  FAIL ") + n + "  " + str(d), flush=True)


KEYSYM = {"_": "underscore", ".": "period", "-": "minus", " ": "space",
          "/": "slash", "*": "asterisk", "?": "question", ":": "colon",
          '"': "quotedbl", "|": "bar", "<": "less", ">": "greater",
          "\\": "backslash", "'": "apostrophe", ",": "comma",
          ";": "semicolon", "(": "parenleft", ")": "parenright"}

app = V.IDEApp(W)


def find_dialog():
    for w in app.winfo_children():
        if isinstance(w, tk.Toplevel) and w.winfo_exists() \
                and w.winfo_viewable():
            return w
    return None


def type_keys(win, text):
    """Send key events to the window; Tk routes them to the focus widget."""
    for ch in text:
        win.event_generate("<KeyPress-%s>" % KEYSYM.get(ch, ch), when="now")


def run_dialog(trigger, text, finish="Return", pre=None):
    """Open a modal via `trigger`, type into it, and return what we saw."""
    seen = {}

    def act():
        try:
            _act()
        except Exception as ex:  # noqa: BLE001
            seen["error"] = repr(ex)[:80]
            top = find_dialog()
            if top is not None:
                top.destroy()          # never leave the suite hanging

    def _act():
        top = find_dialog()
        seen["found"] = top is not None
        if top is None:
            return
        focus = top.focus_get()
        seen["focus_cls"] = focus.winfo_class() if focus else None
        seen["entry_value_before"] = None
        if focus is not None and focus.winfo_class() == "Entry":
            seen["entry_value_before"] = focus.get()
        if pre:
            pre(top)
        type_keys(top, text)
        app.update()
        f2 = top.focus_get()
        if f2 is not None and f2.winfo_class() == "Entry":
            seen["entry_value_after"] = f2.get()
        top.event_generate("<%s>" % finish, when="now")
        app.update()
        # a refused name keeps the modal open on purpose - record that and
        # then close it, so the suite can never wedge on wait_window
        seen["stayed_open"] = bool(top.winfo_exists())
        if top.winfo_exists():
            top.event_generate("<Escape>", when="now")
            app.update()
            if top.winfo_exists():
                top.destroy()

    def watchdog():
        top = find_dialog()
        if top is not None:
            seen["watchdog"] = True
            top.destroy()

    app.after(500, act)
    app.after(5000, watchdog)      # belt and braces: never hang
    trigger()               # blocks in wait_window until the modal closes
    app.update()
    return seen


def main():
    app.update()

    # ---------------- Tk-level: the dialog must own the keyboard ----------
    captured = {}
    real_prompt = V.IDEApp._prompt_text

    def spy(self, title, label, initial="", select_stem=True):
        val = real_prompt(self, title, label, initial, select_stem)
        captured[title] = val
        return val
    V.IDEApp._prompt_text = spy

    seen = run_dialog(lambda: app.fs_new_file(W), "typed_file.py")
    chk("dialog appears", seen.get("found") is True)
    chk("focus lands on the text entry", seen.get("focus_cls") == "Entry",
        seen.get("focus_cls"))
    chk("typed characters reach the entry",
        seen.get("entry_value_after") == "typed_file.py",
        seen.get("entry_value_after"))
    chk("Return commits the name",
        captured.get("New File") == "typed_file.py", captured.get("New File"))
    chk("file created on disk",
        os.path.isfile(os.path.join(W, "typed_file.py")), sorted(os.listdir(W)))
    chk("file opened in a tab",
        any(b.get("name") == "typed_file.py" for b in app.buffers),
        [b.get("name") for b in app.buffers])

    # ---------------- folders ----------------
    seen = run_dialog(lambda: app.fs_new_folder(W), "typed_folder")
    chk("folder dialog takes input",
        captured.get("New Folder") == "typed_folder",
        captured.get("New Folder"))
    chk("folder created", os.path.isdir(os.path.join(W, "typed_folder")))

    # ---------------- rename: stem preselected, typing replaces it --------
    seen = run_dialog(lambda: app.fs_rename(os.path.join(W, "typed_file.py")),
                      "renamed_now")
    chk("rename dialog prefills the old name",
        seen.get("entry_value_before") == "typed_file.py",
        seen.get("entry_value_before"))
    chk("typing replaces the stem, keeps the extension",
        seen.get("entry_value_after") == "renamed_now.py",
        seen.get("entry_value_after"))
    chk("rename applied on disk",
        os.path.isfile(os.path.join(W, "renamed_now.py"))
        and not os.path.exists(os.path.join(W, "typed_file.py")))
    chk("open tab followed the rename",
        any(b.get("name") == "renamed_now.py" for b in app.buffers),
        [b.get("name") for b in app.buffers])

    # ---------------- Escape cancels ----------------
    before = set(os.listdir(W))
    run_dialog(lambda: app.fs_new_file(W), "should_not_exist",
               finish="Escape")
    chk("Escape creates nothing", set(os.listdir(W)) == before,
        set(os.listdir(W)) ^ before)

    # ---------------- validation ----------------
    seen = run_dialog(lambda: app.fs_new_file(W), "bad:name?.py")
    chk("invalid characters rejected",
        not any(":" in f or "?" in f for f in os.listdir(W)),
        sorted(os.listdir(W)))
    chk("dialog stays open on an invalid name",
        seen.get("stayed_open") is True and not seen.get("watchdog"),
        seen)

    before = set(os.listdir(W))

    def empty_then_real(top):
        top.event_generate("<Return>", when="now")     # empty -> refused
    seen = run_dialog(lambda: app.fs_new_file(W), "after_retry.py",
                      pre=empty_then_real)
    chk("empty name refused, dialog stays open",
        os.path.isfile(os.path.join(W, "after_retry.py")),
        sorted(os.listdir(W)))

    V.IDEApp._prompt_text = real_prompt

    # ---------------- OS-level pass, only where xdotool exists ------------
    if not shutil.which("xdotool"):
        print("  skip  OS-level keystroke pass (xdotool not installed; "
              "Tk-level checks above already cover the dialog)", flush=True)
        return

    def worker(text):
        time.sleep(0.9)
        subprocess.run(["xdotool", "type", "--delay", "40", text], check=False)
        time.sleep(0.15)
        subprocess.run(["xdotool", "key", "Return"], check=False)

    threading.Thread(target=worker, args=("os_level.py",), daemon=True).start()
    app.fs_new_file(W)
    app.update()
    time.sleep(0.3)
    chk("real OS keystrokes reach the dialog",
        os.path.isfile(os.path.join(W, "os_level.py")), sorted(os.listdir(W)))


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
