"""File-type icons: mapping, drawing, and use in the Explorer tree."""
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)
os.environ.setdefault("DISPLAY", ":99")
import tkinter as tk  # noqa: E402
import traceback  # noqa: E402
import tkinter.messagebox as MB  # noqa: E402

MB.showerror = lambda *a, **k: None
import ide as V  # noqa: E402

V.messagebox = MB

P, F = [], []


def chk(n, c, d=""):
    (P if c else F).append(f"{n} {d}")
    print(("  OK   " if c else "  FAIL ") + n + "  " + str(d), flush=True)


W = tempfile.mkdtemp(prefix="ideicons")
os.makedirs(os.path.join(W, "sub"), exist_ok=True)
SAMPLES = ["main.py", "app.js", "a.ts", "b.tsx", "i.html", "s.css", "d.json",
           "r.md", "sh.sh", "y.yaml", "J.java", "l.rs", "g.go", "c.cpp",
           "q.sql", "rb.rb", "p.php", "Dockerfile", "Makefile", ".gitignore",
           "pic.png", "ph.jpg", "doc.pdf", "z.zip", "s.mp3", "v.mp4",
           "f.ttf", "e.exe", "u.xyz", "t.txt", "cs.cs", "k.kt", "sw.swift"]
for _n in SAMPLES:
    with open(os.path.join(W, _n), "w") as _fh:
        _fh.write("x\n")

app = V.IDEApp(W)


def main():
    app.update()

    # ---- extension resolution ----
    cases = [("main.py", "py"), ("App.TSX", "tsx"), ("Dockerfile", "dockerfile"),
             ("makefile", "makefile"), (".gitignore", "gitignore"),
             ("archive.tar.gz", "gz"), ("README.md", "md"),
             ("noext", ""), (".env", "env")]
    bad = [(n, V.key_for(n), e) for n, e in cases if V.key_for(n) != e]
    chk("filename -> icon key", not bad, bad or f"{len(cases)} cases")

    # ---- category classification ----
    cats = [("pic.png", "image"), ("doc.pdf", "pdf"), ("z.zip", "archive"),
            ("s.mp3", "audio"), ("v.mp4", "video"), ("f.ttf", "font"),
            ("e.exe", "binary"), ("main.py", "code"), ("u.xyz", "default")]
    bad = [(n, V.category(V.key_for(n)), c) for n, c in cats
           if V.category(V.key_for(n)) != c]
    chk("category classification", not bad, bad or f"{len(cats)} cases")

    # ---- every sample draws without raising, at the right size ----
    sizes = {}
    errs = []
    for n in SAMPLES:
        try:
            img = V.build_icon(tk, n, 18)
            sizes[n] = (img.width(), img.height())
        except Exception as ex:  # noqa: BLE001
            errs.append((n, repr(ex)[:40]))
    chk("all samples draw", not errs, errs or f"{len(sizes)} icons")
    chk("icons are square and correct size",
        all(v == (18, 18) for v in sizes.values()),
        set(sizes.values()))

    # ---- icons are actually distinct per type ----
    def sig(name, size=18):
        img = V.build_icon(tk, name, size)
        out = []
        for y in range(0, size, 3):
            for x in range(0, size, 3):
                try:
                    out.append(img.get(x, y))
                except Exception:  # noqa: BLE001
                    out.append(None)
        return tuple(str(v) for v in out)

    distinct = {n: sig(n) for n in
                ("main.py", "app.js", "a.ts", "pic.png", "doc.pdf",
                 "z.zip", "s.mp3", "v.mp4", "u.xyz")}
    chk("icons differ per type", len(set(distinct.values())) == len(distinct),
        f"{len(set(distinct.values()))}/{len(distinct)} unique")

    # ---- folder icons, open vs closed ----
    closed = V.build_icon(tk, "src", 18, is_dir=True, is_open=False)
    opened = V.build_icon(tk, "src", 18, is_dir=True, is_open=True)
    cs = [closed.get(x, y) for y in range(0, 18, 2) for x in range(0, 18, 2)]
    os_ = [opened.get(x, y) for y in range(0, 18, 2) for x in range(0, 18, 2)]
    chk("folder open/closed differ", cs != os_)

    # ---- sizes scale ----
    big = V.build_icon(tk, "main.py", 28)
    chk("icon scales up", (big.width(), big.height()) == (28, 28))

    # ---- the tree really uses them ----
    sb = app.sidebar
    kids = sb.tree.get_children(sb.root_node)
    with_img = [k for k in kids if sb.tree.item(k, "image")]
    chk("tree rows carry an image", len(with_img) == len(kids),
        f"{len(with_img)}/{len(kids)}")
    chk("no colour-chip fallback left", not hasattr(sb, "_chip"))

    # a folder row swaps icon when expanded
    folder = None
    for k in kids:
        v = sb.tree.item(k, "values")
        if v and os.path.isdir(v[0]):
            folder = (k, v[0])
            break
    if folder:
        k, pth = folder
        before = sb.tree.item(k, "image")
        sb._set_dir_icon(k, pth, True)
        after = sb.tree.item(k, "image")
        chk("folder icon swaps on expand", before != after,
            f"{before} -> {after}")
    else:
        chk("folder icon swaps on expand", False, "no folder row found")

    # ---- icons survive a theme switch ----
    app.set_theme("black")
    app.update()
    sb = app.sidebar
    kids = sb.tree.get_children(sb.root_node)
    chk("icons present after theme switch",
        bool(kids) and all(sb.tree.item(k, "image") for k in kids),
        f"{len(kids)} rows")
    app.set_theme("grey")
    app.update()

    # ---- cache: same request returns the same object ----
    a = app.sidebar._icon("main.py")
    b = app.sidebar._icon("main.py")
    chk("icons are cached", a is b)


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
