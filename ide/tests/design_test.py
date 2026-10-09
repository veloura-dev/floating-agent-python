"""Design system: tokens, palette integrity, contrast, and motion."""
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
import tkinter as tk  # noqa: E402
import tkinter.messagebox as MB  # noqa: E402

MB.showerror = lambda *a, **k: None
import ide as V  # noqa: E402

V.messagebox = MB
from _fixtures import make_fs_workspace  # noqa: E402

W = make_fs_workspace(tempfile.mkdtemp(prefix="idedesign"))
P, F = [], []


def chk(n, c, d=""):
    (P if c else F).append(f"{n} {d}")
    print(("  OK   " if c else "  FAIL ") + n + "  " + str(d), flush=True)


def lum(hexcol):
    r, g, b = V._rgb(hexcol)

    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


app = V.IDEApp(W)


def main():
    app.update()

    # ---------------- tokens ----------------
    chk("spacing scale is monotonic",
        V.sp("xs") <= V.sp("sm") <= V.sp("md") <= V.sp("lg") <= V.sp("xl"),
        [V.sp(k) for k in ("xs", "sm", "md", "lg", "xl")])
    chk("type scale is ordered",
        V.ts(-1)[0] < V.ts(0)[0] < V.ts(1)[0],
        [V.ts(i)[0] for i in (-1, 0, 1)])
    chk("heading weight is bold", V.ts(1, bold=True)[1] == "bold")

    # ---------------- palette integrity ----------------
    keys = {name: set(pal) for name, pal in V.THEMES.items()}
    base = keys["grey"]
    missing = {n: sorted(base - k) for n, k in keys.items() if base - k}
    chk("all themes define the same keys", not missing, missing)
    bad = []
    for name, pal in V.THEMES.items():
        for k, val in pal.items():
            if not (isinstance(val, str) and val.startswith("#")
                    and len(val) in (4, 7, 9)):
                bad.append((name, k, val))
    chk("every colour is a valid hex", not bad, bad[:3])

    # ---------------- readability ----------------
    poor = []
    for name, pal in V.THEMES.items():
        pairs = [("body text", pal["fg"], pal["editor"]),
                 ("dim text", pal["fg_dim"], pal["sidebar"]),
                 ("editor text", pal["text_fg"], pal["editor"]),
                 ("status text", pal["status_fg"], pal["statusbar"]),
                 ("active tab", pal["fg_bright"], pal["tab_active"])]
        for label, fg, bg in pairs:
            r = contrast(fg, bg)
            if r < 4.5:
                poor.append(f"{name}/{label}={r:.1f}")
    chk("text meets 4.5:1 contrast everywhere", not poor, poor)

    faint = []
    for name, pal in V.THEMES.items():
        r = contrast(pal["fg_faint"], pal["editor"])
        if r < 2.5:
            faint.append(f"{name}={r:.1f}")
    chk("faint text still visible (>=2.5:1)", not faint, faint)

    # borders must be subtle, not harsh
    harsh = []
    for name, pal in V.THEMES.items():
        r = contrast(pal["border_soft"], pal["sidebar"])
        if r > 2.2:
            harsh.append(f"{name}={r:.1f}")
    chk("separators are subtle (<=2.2:1)", not harsh, harsh)

    # accent must stand out against chrome
    weak = []
    for name, pal in V.THEMES.items():
        r = contrast(pal["accent"], pal["tabbar"])
        if r < 2.5:
            weak.append(f"{name}={r:.1f}")
    chk("accent reads against the tab bar", not weak, weak)

    # ---------------- colour maths ----------------
    chk("mix endpoints exact",
        V.mix("#000000", "#ffffff", 0) == "#000000"
        and V.mix("#000000", "#ffffff", 1) == "#ffffff")
    chk("mix midpoint blends",
        V.mix("#000000", "#ffffff", 0.5) in ("#7f7f7f", "#808080"),
        V.mix("#000000", "#ffffff", 0.5))
    chk("mix tolerates junk", V.mix("nonsense", "#123456", 0.5) == "#123456")

    # ---------------- motion ----------------
    probe = tk.Label(app, bg="#000000", fg="#000000")
    probe.pack()
    app.update()
    V.animate_color(probe, "bg", "#ffffff", ms=90, steps=6)
    mids = set()
    for _ in range(14):
        app.update()
        time.sleep(0.02)
        mids.add(str(probe.cget("bg")))
    chk("animation produces intermediate frames", len(mids) >= 3,
        f"{len(mids)} distinct values")
    for _ in range(40):
        app.update()
        time.sleep(0.01)
        if str(probe.cget("bg")) == "#ffffff":
            break
    chk("animation reaches its target", str(probe.cget("bg")) == "#ffffff",
        probe.cget("bg"))

    # destroyed widgets must not raise
    doomed = tk.Label(app, bg="#000000")
    doomed.pack()
    app.update()
    V.animate_color(doomed, "bg", "#ffffff", ms=120, steps=8)
    doomed.destroy()
    ok = True
    try:
        for _ in range(20):
            app.update()
            time.sleep(0.01)
    except Exception as ex:  # noqa: BLE001
        ok = False
        print("   ", repr(ex)[:70])
    chk("animating a destroyed widget is safe", ok)
    probe.destroy()

    # steps=0 disables animation but still applies the value
    probe2 = tk.Label(app, bg="#000000")
    probe2.pack()
    app.update()
    V.animate_color(probe2, "bg", "#123456", steps=0)
    chk("steps=0 applies instantly", str(probe2.cget("bg")) == "#123456",
        probe2.cget("bg"))
    probe2.destroy()

    # ---------------- smooth sidebar toggle ----------------
    chk("sidebar starts visible", app.sidebar_visible)
    app.toggle_sidebar()
    for _ in range(30):
        app.update()
        time.sleep(0.02)
    chk("sidebar hides", not app.sidebar_visible)
    app.toggle_sidebar()
    for _ in range(30):
        app.update()
        time.sleep(0.02)
    width = app.sidebar.winfo_width()
    chk("sidebar returns to full width", app.sidebar_visible and width > 100,
        f"{width}px")

    # ---------------- every theme still builds ----------------
    for th in ("black", "white", "grey"):
        app.set_theme(th)
        for _ in range(10):
            app.update()
            time.sleep(0.03)
        chk(f"theme '{th}' rebuilds cleanly",
            app.theme_name == th and app.editor.winfo_exists())
    app.open_file(os.path.join(W, "b.txt"))
    app.update()
    chk("editor usable after all switches",
        app.editor.text.get("1.0", "end").startswith("b"))


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
