"""Quick, standalone sanity check for the Notepad/Calculator panel-
embedding feature — run this directly on your real Windows PC to see
exactly what happens, with NO API keys and without running the full
Friday app at all. It opens Notepad then Calculator through the same
app_panels.py code Friday itself uses, prints what's tracked after
each one, and leaves them open for a bit so you can actually look at
the screen corners for the small embedded panels.

Run it from inside the extracted zip's folder:
    python test_embedding_standalone.py

What "working" looks like: within a couple seconds of each "Opening
<app>..." line, a small bordered window (styled like the IDE — dark
background, a thin titlebar with the app's name and — / X buttons)
should appear in a screen corner, with the real Notepad/Calculator
content visibly inside it — not a second, separate, normal-looking
Notepad/Calculator window floating on its own.

If it's NOT working, the text this script prints (the list_panels()
output after each open) will now say plainly why, e.g.:
    - Notepad (open) — couldn't find its window to embed it into a
      panel, so it's running as its own separate window
Please copy/paste that exact text back — it tells us precisely which
part failed instead of us having to guess blind again.
"""
import sys
import time

import app_panels as ap


def main():
    print(f"Python: {sys.version}")
    print(f"Platform: {sys.platform}")
    backend = ap.RealWindowBackend()
    print(f"RealWindowBackend.is_supported(): {backend.is_supported()}  "
          "(must be True on Windows for embedding to even be attempted)")
    print()

    mgr = ap.AppPanelManager()

    print("Opening Notepad...")
    print(mgr.open("notepad", content="Hello from Friday's embedding test!"))
    print("Waiting up to 10s for discovery/embedding to finish...")
    for _ in range(20):
        time.sleep(0.5)
        rec = mgr._panels.get("notepad")
        if rec and (rec.get("embedded") or rec.get("embed_note")):
            break
    print(mgr.list_panels())
    print()

    print("Opening Calculator...")
    print(mgr.open("calculator"))
    print("Waiting up to 10s for discovery/embedding to finish...")
    for _ in range(20):
        time.sleep(0.5)
        rec = mgr._panels.get("calculator")
        if rec and (rec.get("embedded") or rec.get("embed_note")):
            break
    print(mgr.list_panels())
    print()

    print("Leaving both open for 20 seconds so you can look at the screen")
    print("corners for the embedded panels (or two separate normal windows,")
    print("if embedding fell back) — final status below once that's up.")
    time.sleep(20)
    print()
    print("Final status:")
    print(mgr.list_panels())

    input("\nPress Enter to close everything and exit...")
    print(mgr.close("all"))


if __name__ == "__main__":
    main()
