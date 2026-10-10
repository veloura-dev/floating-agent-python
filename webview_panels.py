"""webview_panels.py -- an upgraded, real HTML/CSS/JS rendering of
Friday's Chat/Profile/Image Generation/Video Generation panels, built
on pywebview (a REAL embedded web renderer: Edge WebView2 on Windows,
the production target; GTK WebKit2 on Linux dev/test machines -- both
verified end to end during development, see dev_tests/
test_webview_panels.py) instead of conversation_panels.py's hand-drawn
Tkinter Canvas icons.

Why this is its own standalone PROCESS, not just a new widget class
dropped into app_panels.py's existing _CUSTOM_PANEL_CLASSES:
pywebview hard-requires that `webview.start()` run on the real OS
process main thread -- this isn't a backend quirk, it's a flat
`threading.current_thread().name != 'MainThread'` check inside
pywebview itself, true for every backend (gtk/qt/edgechromium/cocoa)
(confirmed directly against the installed pywebview 6.2.1 source).
Friday's main process already has its main thread spoken for by
Tkinter (every CUSTOM_PANEL_APPS panel) and Qt/PySide6 (the floating
circle overlay) -- there's no in-process thread left for pywebview to
claim. Running each panel as its own small separate process sidesteps
that entirely (each process gets its own real main thread) and, more
importantly, isn't a hack: it's the exact same pattern Friday already
uses for every real, non-custom app (Chrome, Calculator) -- a real OS
process, launched and tracked by PID/window handle, not merged into
Friday's own event loop. See app_panels.py's own `launcher.launch()` /
`_discover_and_embed()` for that existing mechanism; wiring these 4
panels into it (so `open_app('chat')` launches this script the same
way it launches Chrome) is a small, separate follow-on step, not yet
done here -- this module is deliberately runnable and independently
verifiable completely on its own first via `python3 webview_panels.py
<key>`.

Deliberately NOT using the old SetParent-reparenting trick either (see
agent_tools.py's open_app docstring: that was already tried for
Notepad and abandoned as fragile) -- each panel is a real, independent
top-level window with its own HTML-drawn titlebar (draggable natively
via pywebview's own `.pywebview-drag-region` CSS class on Windows'
edgechromium backend), not reparented into anything.

Scope matches conversation_panels.py's exact same brief: an empty body
+ the bottom input bar (attach left / text entry middle / mic+speaker
right). No chat/generation backend is wired up here either -- Enter
just clears the box, attach opens a real native file picker and shows
a removable chip, mic/speaker are cosmetic toggles only.
"""
import json
import os
import sys
import threading

try:
    import webview
    WEBVIEW_AVAILABLE = True
except Exception:  # noqa: BLE001 -- pywebview (or a GUI backend it
    # needs: WebView2 Runtime on Windows, WebKitGTK on Linux) may
    # simply not be installed/available on a given machine -- every
    # caller must treat that as a normal, expected "not available"
    # condition, never crash.
    webview = None
    WEBVIEW_AVAILABLE = False


PANEL_DEFS = {
    "chat": dict(
        title="Chat",
        empty_html="No messages yet &mdash; start typing below.",
        placeholder="Type a message...",
        extra_body="",
    ),
    "profile": dict(
        title="Profile",
        empty_html="No profile info yet.",
        placeholder="Tell Friday something about yourself...",
        extra_body=(
            '<div class="avatar"><svg viewBox="0 0 24 24">'
            '<path d="M12 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0 2c-5 0-9 '
            '2.5-9 6v2h18v-2c0-3.5-4-6-9-6Z"/></svg></div>'
            '<div class="you-label">You</div>'
        ),
    ),
    "image_gen": dict(
        title="Image Generation",
        empty_html=("Describe the image you want below.<br>"
                    "(Image generation isn't wired up to a real model yet.)"),
        placeholder="Describe the image you want to generate...",
        extra_body="",
    ),
    "video_gen": dict(
        title="Video Generation",
        empty_html=("Describe the video you want below.<br>"
                    "(Video generation isn't wired up to a real model yet.)"),
        placeholder="Describe the video you want to generate...",
        extra_body="",
    ),
}


def _pick_gui_backend():
    """Edge WebView2 on Windows (the real production target -- ships
    with Windows 10/11); GTK WebKit2 on Linux, used only for dev/test
    (confirmed working under Xvfb during development)."""
    if sys.platform.startswith("win"):
        return "edgechromium"
    if sys.platform == "darwin":
        return "cocoa"
    return "gtk"


# A single shared <style> block -- the same visual language as
# conversation_panels.py's Tkinter "grey" theme (see ide.py's
# THEMES["grey"]), just rendered in real CSS instead of Tkinter
# widget colors.
_CSS = """
:root {
  --bg:#1e1e1e; --tabbar:#242424; --input:#2a2a2a; --border:#3a3a3a;
  --fg:#f0f0f0; --fg-dim:#a8a8a8; --fg-faint:#6b6b6b;
  --accent:#6ea8fe; --accent-glow:rgba(110,168,254,.45); --danger:#e5484d;
}
* { box-sizing: border-box; }
html, body {
  margin:0; height:100%; background:var(--bg); color:var(--fg);
  font-family:"Segoe UI", system-ui, sans-serif; overflow:hidden;
  border-radius:10px;
}
.shell { display:flex; flex-direction:column; height:100vh; border:1px solid var(--border); border-radius:10px; overflow:hidden; }
.titlebar {
  background:linear-gradient(180deg,#2b2b2b,#212121); padding:10px 12px;
  display:flex; align-items:center; justify-content:space-between;
  border-bottom:1px solid var(--border); flex-shrink:0; user-select:none;
}
.titlebar .name { font-size:13px; font-weight:600; display:flex; align-items:center; gap:8px; }
.titlebar .name .dot { width:7px; height:7px; border-radius:50%; background:var(--accent); box-shadow:0 0 6px var(--accent-glow); }
.titlebar .btns { display:flex; gap:6px; }
.titlebar .btns button {
  width:22px; height:22px; border:none; border-radius:6px; background:transparent;
  color:var(--fg-dim); cursor:pointer; font-size:12px; display:flex; align-items:center;
  justify-content:center; transition:background .15s,color .15s;
}
.titlebar .btns button.close:hover { background:var(--danger); color:#fff; }
.titlebar .btns button.min:hover { background:#3a3a3a; color:var(--fg); }
.body {
  flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center;
  text-align:center; color:var(--fg-faint); font-size:13px; padding:18px; gap:10px; line-height:1.6;
}
.avatar { width:64px; height:64px; border-radius:50%; background:linear-gradient(145deg,#3a3a3a,#2a2a2a);
  display:flex; align-items:center; justify-content:center; box-shadow:inset 0 0 0 1px var(--border); }
.avatar svg { width:32px; height:32px; fill:var(--fg-dim); }
.you-label { color:var(--fg); font-weight:600; font-size:14px; }
.input-bar-wrap { padding:0 14px 16px; position:relative; flex-shrink:0; }
.chip {
  position:absolute; margin-top:-40px; margin-left:4px; background:var(--input); border:1px solid var(--border);
  border-radius:7px; padding:5px 9px; font-size:12px; color:var(--fg-dim); display:none; align-items:center; gap:7px;
}
.chip.show { display:inline-flex; }
.chip button { background:none; border:none; color:var(--fg-faint); cursor:pointer; font-size:12px; }
.input-bar {
  display:flex; align-items:center; gap:6px; background:var(--input); border:1px solid var(--border);
  border-radius:12px; padding:7px 9px; transition:border-color .2s, box-shadow .2s;
}
.input-bar:focus-within { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-glow); }
.icon-btn {
  width:32px; height:32px; border-radius:8px; border:none; background:transparent; display:flex;
  align-items:center; justify-content:center; cursor:pointer; flex-shrink:0; transition:background .15s, transform .1s;
}
.icon-btn:hover { background:#3a3a3a; }
.icon-btn:active { transform:scale(.92); }
.icon-btn.active { background:var(--accent); }
.icon-btn svg { width:17px; height:17px; stroke:var(--fg-dim); fill:none; stroke-width:1.8; }
.icon-btn.active svg { stroke:#fff; }
.input-bar input {
  flex:1; min-width:0; background:transparent; border:none; outline:none; color:var(--fg);
  font-size:14px; font-family:inherit; padding:7px 4px;
}
.input-bar input::placeholder { color:var(--fg-faint); }
"""

_ICON_ATTACH = (
    '<svg viewBox="0 0 24 24"><path d="M21.44 11.05 12.25 20.24a5.5 5.5 0 0 1-7.78'
    '-7.78l9.19-9.19a3.67 3.67 0 0 1 5.19 5.19l-9.2 9.19a1.83 1.83 0 0 1-2.59-2.59'
    'l8.49-8.48"/></svg>'
)
_ICON_MIC = (
    '<svg viewBox="0 0 24 24"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 '
    '0 0 0 3 3Z"/><path d="M19 11a7 7 0 0 1-14 0"/><path d="M12 18v4"/>'
    '<path d="M8 22h8"/></svg>'
)
_ICON_SPEAKER = (
    '<svg viewBox="0 0 24 24"><path d="M4 9v6h4l5 5V4L8 9H4Z"/>'
    '<path d="M16.5 8.5a5 5 0 0 1 0 7"/><path d="M19 6a9 9 0 0 1 0 12"/></svg>'
)


def _build_html(key):
    d = PANEL_DEFS[key]
    # json.dumps for safe embedding of the placeholder string inside
    # the inline JS below (handles quotes/apostrophes correctly).
    placeholder_js = json.dumps(d["placeholder"])
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>{_CSS}</style></head>
<body>
<div class="shell">
  <div class="titlebar pywebview-drag-region">
    <div class="name"><span class="dot"></span>{d['title']}</div>
    <div class="btns">
      <button class="min" onclick="pywebview.api.minimize()">&#9472;</button>
      <button class="close" onclick="pywebview.api.close_window()">&#10005;</button>
    </div>
  </div>
  <div class="body">
    {d['extra_body']}
    <div>{d['empty_html']}</div>
  </div>
  <div class="input-bar-wrap">
    <div class="chip" id="chip"><span id="chip-name"></span>
      <button onclick="clearChip()">&#10005;</button></div>
    <div class="input-bar">
      <button class="icon-btn" title="Attach a file" onclick="doAttach()">{_ICON_ATTACH}</button>
      <input id="entry" type="text" placeholder={placeholder_js}
             onkeydown="if(event.key==='Enter'){{ this.value=''; this.blur(); }}" />
      <button class="icon-btn" id="mic" title="Voice input"
              onclick="this.classList.toggle('active')">{_ICON_MIC}</button>
      <button class="icon-btn" id="speaker" title="Read replies aloud"
              onclick="this.classList.toggle('active')">{_ICON_SPEAKER}</button>
    </div>
  </div>
</div>
<script>
  async function doAttach() {{
    const result = await pywebview.api.pick_file();
    if (result && result.name) {{
      document.getElementById('chip-name').textContent = '\\uD83D\\uDCCE ' + result.name;
      document.getElementById('chip').classList.add('show');
    }}
  }}
  function clearChip() {{
    document.getElementById('chip').classList.remove('show');
  }}
</script>
</body></html>"""


class PanelBridge:
    """The one real Python<->JS bridge each panel needs -- everything
    else (placeholder text, the Enter-key reset, mic/speaker's cosmetic
    toggle) is plain client-side JS/CSS with nothing real to call into,
    same "no fabricated backend" scope as conversation_panels.py."""

    def __init__(self):
        self.window = None  # set once create_window() returns it

    def pick_file(self):
        if self.window is None:
            return None
        try:
            result = self.window.create_file_dialog(webview.OPEN_DIALOG)
        except Exception:  # noqa: BLE001
            return None
        if not result:
            return None
        path = result[0]
        return {"path": path, "name": os.path.basename(path)}

    def minimize(self):
        if self.window is not None:
            self.window.minimize()
        return True

    def close_window(self):
        if self.window is not None:
            self.window.destroy()
        return True


def open_panel_blocking(key, width=380, height=480, x=None, y=None):
    """Builds and shows one panel, then blocks (calling webview.start())
    until it's closed -- meant to be the entire body of this script's
    __main__ block, i.e. run as its own dedicated OS process. Returns
    once the window is closed."""
    if not WEBVIEW_AVAILABLE:
        raise RuntimeError(
            "pywebview isn't installed/available -- can't open a web-"
            "rendered panel. (Falls back to conversation_panels.py's "
            "native Tkinter version in the real app.)")
    if key not in PANEL_DEFS:
        raise ValueError(f"Unknown webview panel key: {key!r}")

    bridge = PanelBridge()
    win = webview.create_window(
        PANEL_DEFS[key]["title"], html=_build_html(key), js_api=bridge,
        width=width, height=height, x=x, y=y, frameless=True, easy_drag=True,
        background_color="#1e1e1e", min_size=(300, 360))
    bridge.window = win
    webview.start(gui=_pick_gui_backend(), debug=False)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in PANEL_DEFS:
        print(f"Usage: python3 {sys.argv[0]} <{'|'.join(PANEL_DEFS)}>")
        sys.exit(1)
    open_panel_blocking(sys.argv[1])
