"""Explorer indent guides: the vertical lines marking folder contents."""
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
import ide as V  # noqa: E402

V.messagebox = MB

W = tempfile.mkdtemp(prefix="ideguides")
for rel in ("src/components/Button.tsx", "src/components/Card.tsx",
            "src/utils/format.ts", "assets/icons/logo.png",
            "assets/style.css", "docs/README.md", "main.py"):
    p = os.path.join(W, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write("x\n")

P, F = [], []


def chk(n, c, d=""):
    (P if c else F).append(f"{n} {d}")
    print(("  OK   " if c else "  FAIL ") + n + "  " + str(d), flush=True)


app = V.IDEApp(W)


def SB():
    """Always re-fetch: set_theme rebuilds the whole sidebar."""
    return app.sidebar


def settle(n=12):
    for _ in range(n):
        app.update()
        time.sleep(0.03)


def expand_all():
    for _ in range(4):
        def walk(node=""):
            for k in SB().tree.get_children(node):
                v = SB().tree.item(k, "values")
                if v and os.path.isdir(v[0]) and not SB().tree.item(k, "open"):
                    SB().tree.item(k, open=True)
                    SB()._fill_dir(k, v[0])
                walk(k)
        walk()
        settle(3)
    SB()._draw_guides()
    settle(3)


def visible_bars():
    return [b for b in SB()._guide_bars if b.winfo_ismapped()]


def find(name, node=""):
    for k in SB().tree.get_children(node):
        if SB().tree.item(k, "text").strip() == name:
            return k
        r = find(name, k)
        if r:
            return r
    return None


def main():
    settle()
    chk("guide pool exists", hasattr(SB(), "_guide_bars"))

    # collapsed tree: only the root's children, so at most the level-1 guide
    settle()
    flat = len(visible_bars())

    expand_all()
    deep = len(visible_bars())
    chk("expanding draws more guides", deep > flat, f"{flat} -> {deep}")
    chk("guides are thin", all(b.winfo_width() <= 3 for b in visible_bars()),
        sorted({b.winfo_width() for b in visible_bars()}))

    # guides must sit in the indent gutter, never over the labels
    ind = SB()._indent_px()
    xs = sorted({b.winfo_x() for b in visible_bars()})
    chk("guides sit on indent columns",
        all((x - ind // 2) % ind == 0 for x in xs), xs)
    chk("guides stay left of the deepest icon",
        max(xs) < ind * 4, f"max x={max(xs)}, indent={ind}")

    # vertical extent should cover real rows
    tall = [b for b in visible_bars() if b.winfo_height() > 10]
    chk("guides span rows", len(tall) == len(visible_bars()),
        f"{len(tall)}/{len(visible_bars())}")

    # ---- the selected file's folder chain is highlighted ----
    card = find("Card.tsx")
    chk("nested file found", card is not None)
    SB().tree.selection_set(card)
    SB().tree.focus(card)
    SB()._draw_guides()
    settle()
    accents = [b for b in visible_bars()
               if str(b.cget("bg")).lower() == V.C["accent"].lower()]
    chk("selection highlights its folder chain", len(accents) >= 1,
        f"{len(accents)} highlighted")
    plain = [b for b in visible_bars()
             if str(b.cget("bg")).lower() != V.C["accent"].lower()]
    chk("unrelated folders stay neutral", len(plain) >= 1,
        f"{len(plain)} neutral")

    # selecting a top-level file should clear the highlight
    top = find("main.py")
    if top:
        SB().tree.selection_set(top)
        SB().tree.focus(top)
        SB()._draw_guides()
        settle()
        acc2 = [b for b in visible_bars()
                if str(b.cget("bg")).lower() == V.C["accent"].lower()]
        chk("top-level selection highlights nothing", not acc2,
            f"{len(acc2)} highlighted")

    # ---- collapsing removes the inner guides ----
    comp = find("components")
    SB().tree.item(comp, open=False)
    SB()._draw_guides()
    settle()
    after = len(visible_bars())
    chk("collapsing removes guides", after < deep, f"{deep} -> {after}")
    SB().tree.item(comp, open=True)
    SB()._draw_guides()
    settle()

    # ---- guides follow the theme ----
    before_col = GUIDE = V.GUIDE_COLOR
    app.set_theme("white")
    settle(14)
    SB()._draw_guides()
    settle()
    chk("guide colour follows the theme", V.GUIDE_COLOR != before_col,
        f"{before_col} -> {V.GUIDE_COLOR}")
    chk("guides survive a theme rebuild",
        hasattr(SB(), "_guide_bars"), type(SB()).__name__)
    app.set_theme("grey")
    settle(14)

    # ---- switching away from the explorer hides them ----
    app.show_sidebar_mode("search")
    settle()
    hidden = [b for b in getattr(SB(), "_guide_bars", []) if b.winfo_ismapped()]
    chk("guides hidden outside the explorer", not hidden, len(hidden))
    app.show_sidebar_mode("explorer")
    settle()

    # ---- clicking a guide still selects the row underneath ----
    expand_all()
    bars = visible_bars()
    if bars:
        bar = bars[-1]

        class E:
            pass
        e = E()
        e.x, e.y = 0, 2
        e.x_root = bar.winfo_rootx()
        e.y_root = bar.winfo_rooty() + 2
        before_sel = SB().tree.focus()
        SB()._fwd_from(bar, SB()._on_single, e)
        settle()
        chk("clicking a guide reaches the tree",
            SB().tree.focus() != "" or before_sel != "", SB().tree.focus())
    else:
        chk("clicking a guide reaches the tree", False, "no bars")

    # ---- no crash on rapid rebuilds ----
    ok = True
    try:
        for _ in range(5):
            app.refresh_explorer()
            app.sidebar._draw_guides()
            settle(2)
    except Exception as ex:  # noqa: BLE001
        ok = False
        print("   ", repr(ex)[:70])
    chk("repeated refresh is stable", ok)


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
