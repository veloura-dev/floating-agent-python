"""Simulate a bare Python install: no Pillow, no ImageMagick, no poppler.

This is the stock-Windows case. Only the built-in decoders and the PDF
text fallback are available, so this suite proves the IDE is genuinely
usable with nothing installed.
"""
import builtins
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

# ---- block Pillow for the whole run ----
_real_import = builtins.__import__


def _no_pil(name, *a, **k):
    if name == "PIL" or name.startswith("PIL."):
        raise ImportError("PIL blocked for this test")
    return _real_import(name, *a, **k)


sys.modules.pop("PIL", None)
for _m in [k for k in list(sys.modules) if k.startswith("PIL")]:
    sys.modules.pop(_m, None)
builtins.__import__ = _no_pil

# ---- hide every external tool ----
_real_which = shutil.which
shutil.which = lambda *a, **k: None

import ide as V  # noqa: E402
import tkinter.messagebox as MB  # noqa: E402

MB.showerror = lambda *a, **k: None
MB.showinfo = lambda *a, **k: None
V.messagebox = MB
V.IDEApp.open_url = lambda self, u: None
V.shutil.which = lambda *a, **k: None
V._PDF_WORKING.clear()

from _fixtures import make_image_workspace, make_pdf  # noqa: E402

W = make_image_workspace(tempfile.mkdtemp(prefix="idenodeps"))
make_pdf(os.path.join(W, "doc.pdf"),
         ["ALPHA_TOKEN_PAGE1", "BETA_TOKEN_PAGE2"])

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
    chk("no external tools visible", V.shutil.which("magick") is None)
    try:
        import PIL  # noqa: F401
        chk("Pillow blocked", False, "PIL still importable")
    except ImportError:
        chk("Pillow blocked", True)
    renderer, _ = V.pdf_find_renderer()
    chk("no pdf renderer visible", renderer is None, renderer)

    # ---- must work with absolutely nothing installed ----
    for fn, why in (("a.png", "Tk native"), ("a.gif", "Tk native"),
                    ("a.ppm", "Tk native"),
                    ("a.jpg", "pure-python JPEG"),
                    ("a420.jpg", "pure-python JPEG 4:2:0"),
                    ("a.bmp", "pure-python BMP"),
                    ("a.tga", "pure-python TGA")):
        mv = open_and_settle(os.path.join(W, fn))
        ok = ed.media_visible and mv.base is not None and mv._err is None
        chk(f"{fn} with no deps ({why})", ok,
            f"{mv.base_size if ok else 'ERR=' + str(mv._err)}")

    # ---- cannot work: must explain, not crash ----
    for fn in ("a.webp", "a.tiff"):
        mv = open_and_settle(os.path.join(W, fn))
        chk(f"{fn} degrades gracefully",
            ed.media_visible and mv._err is not None,
            f"err={str(mv._err)[:45]}")

    # ---- PDF falls back to extracted text ----
    app.open_file(os.path.join(W, "doc.pdf"))
    for _ in range(10):
        app.update()
        time.sleep(0.1)
    buf = app.current_buffer()
    chk("pdf opens as text", buf.get("kind") == "file", buf.get("kind"))
    txt = ed.text.get("1.0", "end")
    chk("pdf text extracted", "ALPHA_TOKEN_PAGE1" in txt, repr(txt[-60:]))
    chk("pdf page 2 text", "BETA_TOKEN_PAGE2" in txt)
    chk("pdf explains itself", "No PDF renderer" in txt)
    chk("pdf marked read-only", buf.get("readonly") is True)
    chk("read-only save refused", app.save_file() is False)
    with open(os.path.join(W, "doc.pdf"), "rb") as fh:
        chk("original pdf untouched", fh.read(5) == b"%PDF-")

    # ---- back to code, no crash ----
    with open(os.path.join(W, "z.py"), "w") as fh:
        fh.write("y = 2\n")
    app.open_file(os.path.join(W, "z.py"))
    app.update()
    chk("returns to code view", not ed.media_visible)


try:
    main()
except Exception:  # noqa: BLE001
    traceback.print_exc()
    F.append("EXCEPTION")
finally:
    builtins.__import__ = _real_import
    shutil.which = _real_which
print(f"\n===== PASS {len(P)}   FAIL {len(F)} =====")
for f in F:
    print("   XX", f)
app.destroy()
shutil.rmtree(W, ignore_errors=True)
