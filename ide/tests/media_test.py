"""Image and PDF viewing.

Uses only the dependency-free fixtures, so it behaves the same on a bare
Windows Python as it does on a machine with Pillow and ImageMagick.
Formats that need an optional backend are allowed to either display *or*
degrade with a clear message - both are correct behaviour.
"""
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
import ide as V  # noqa: E402

V.messagebox = MB
V.IDEApp.open_url = lambda self, u: None
from _fixtures import make_image_workspace, make_pdf  # noqa: E402

W = make_image_workspace(tempfile.mkdtemp(prefix="idemedia"))
make_pdf(os.path.join(W, "doc.pdf"),
         ["PAGE ONE TOKEN", "PAGE TWO TOKEN", "PAGE THREE TOKEN"])
with open(os.path.join(W, "notes.py"), "w") as _fh:
    _fh.write("x = 1\n")

P, F = [], []


def chk(n, c, d=""):
    (P if c else F).append(f"{n} {d}")
    print(("  OK   " if c else "  FAIL ") + n + "  " + str(d), flush=True)


app = V.IDEApp(W)


def open_and_settle(path, tries=8):
    app.open_file(path)
    for _ in range(tries):
        app.update()
        time.sleep(0.08)
    return app.editor.media


def main():
    app.update()
    ed = app.editor

    # ---- formats guaranteed to work with no dependencies at all ----
    for fn, why in (("a.png", "Tk native"), ("a.gif", "Tk native"),
                    ("a.ppm", "Tk native"),
                    ("a.jpg", "built-in JPEG decoder"),
                    ("a420.jpg", "built-in JPEG 4:2:0"),
                    ("a.bmp", "built-in BMP decoder"),
                    ("a.tga", "built-in TGA decoder")):
        mv = open_and_settle(os.path.join(W, fn))
        ok = ed.media_visible and mv.base is not None and mv._err is None
        chk(f"{fn} ({why})", ok,
            f"{mv.base_size if ok else 'ERR=' + str(mv._err)}")

    # ---- optional-backend formats: display OR explain, never crash ----
    for fn in ("a.webp", "a.tiff"):
        mv = open_and_settle(os.path.join(W, fn))
        shown = mv.base is not None and mv._err is None
        chk(f"{fn} handled", ed.media_visible and (shown or mv._err),
            "displayed" if shown else f"explained: {str(mv._err)[:40]}")

    # ---- the 1/8 DC-only path, tested at the decoder ----
    with open(os.path.join(W, "a.jpg"), "rb") as fh:
        jpg = fh.read()
    full_w, full_h, _ = V.decode_jpeg(jpg)
    prev_w, prev_h, _ = V.decode_jpeg(jpg, dc_only_above=100)
    chk("big-image 1/8 preview path", prev_w * 8 >= full_w > prev_w,
        f"full {full_w}x{full_h} -> preview {prev_w}x{prev_h}")

    # ---- zoom controls ----
    mv = open_and_settle(os.path.join(W, "a.png"))
    z0 = mv.zoom_level
    mv.zoom_in()
    app.update()
    chk("zoom in", mv.zoom_level > z0, f"{z0} -> {mv.zoom_level}")
    mv.zoom_out()
    app.update()
    chk("zoom out", abs(mv.zoom_level - z0) < 0.001, mv.zoom_level)
    mv.zoom_actual()
    app.update()
    chk("1:1", abs(mv.zoom_level - 1.0) < 0.01)
    mv.zoom_fit()
    app.update()
    chk("fit", mv.fit_mode)
    chk("photo rendered", mv.photo is not None)

    # ---- PDF: rendered pages or the text fallback, both valid ----
    app.open_file(os.path.join(W, "doc.pdf"))
    for _ in range(12):
        app.update()
        time.sleep(0.1)
    buf = app.current_buffer()
    renderer, _ = V.pdf_find_renderer()
    if buf.get("kind") == "media":
        mv = ed.media
        chk("pdf renders", mv.base is not None and mv._err is None,
            f"via {renderer}: {mv.base_size if mv.base else mv._err}")
        chk("pdf page count", mv.pages == 3, mv.pages)
        mv.next_page()
        for _ in range(8):
            app.update()
            time.sleep(0.1)
        chk("pdf next page", mv.page == 2, f"page {mv.page}")
        mv.prev_page()
        app.update()
        chk("pdf prev page", mv.page == 1)
    else:
        txt = ed.text.get("1.0", "end")
        chk("pdf text fallback", "PAGE ONE TOKEN" in txt, repr(txt[-60:]))
        chk("pdf fallback read-only", buf.get("readonly") is True)
        chk("pdf explains itself", "No PDF renderer" in txt)

    # ---- switching between media and code ----
    app.open_file(os.path.join(W, "notes.py"))
    app.update()
    chk("code view restored", not ed.media_visible)
    chk("text still editable", ed.text.get("1.0", "1.5").startswith("x = 1"))
    open_and_settle(os.path.join(W, "a.png"), 3)
    chk("media view again", ed.media_visible)
    app.open_file(os.path.join(W, "notes.py"))
    app.update()
    chk("toggles cleanly", not ed.media_visible)

    # ---- safety / status / theme ----
    open_and_settle(os.path.join(W, "a.png"), 3)
    chk("save refuses media", app.save_file() is False)
    app.update_status()
    chk("status shows dimensions", "x" in app.status.pos.cget("text"),
        app.status.pos.cget("text"))
    app.set_theme("black")
    for _ in range(8):
        app.update()
        time.sleep(0.1)
    open_and_settle(os.path.join(W, "a.png"), 4)
    chk("survives theme switch",
        ed.media_visible and app.editor.media.base is not None)
    app.set_theme("grey")
    app.update()

    # ---- missing media must error, not open a blank tab ----
    before = len(app.buffers)
    app.open_file(os.path.join(W, "does_not_exist.png"))
    app.update()
    chk("missing image rejected", len(app.buffers) == before,
        f"{before} -> {len(app.buffers)}")

    # ---- explorer lists images ----
    names = []

    def walk(n=""):
        for k in app.sidebar.tree.get_children(n):
            names.append(app.sidebar.tree.item(k, "text").strip())
            walk(k)
    walk()
    chk("images listed in explorer", any(x.startswith("a.") for x in names),
        [x for x in names if x.startswith("a.")][:4])


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
