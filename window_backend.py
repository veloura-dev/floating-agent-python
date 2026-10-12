"""The real OS-process-launch and win32 window-handle primitives behind
Friday's native app panels (`app_panels.py`) -- split into their own
file purely to keep `app_panels.py` a manageable size, with zero change
in behavior. `app_panels.py` still re-exports every class below by its
original name (`RealLauncher`, `RealWindowBackend`, `RealTyper`,
`_PanelHostBridge`), and `AppPanelManager` there is still the only place
that actually constructs and uses them.

These are all deliberately small, pluggable backends (see this module's
classes' own docstrings) so AppPanelManager is testable without a real
Windows desktop or a real Chrome/Calculator to launch -- see
dev_tests/test_app_panels.py's Fake* classes, which stand in for these
by matching the same small interface rather than subclassing them.
"""

import os
import platform
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from shutil import which as _which


class RealLauncher:
    """Launches a real native application as a child process. Windows-
    first (this whole app is Windows-targeted -- see ide.py's DPI/DWM-
    specific ctypes calls elsewhere) but falls back to sensible
    equivalents on macOS/Linux so this still does something reasonable
    there instead of silently failing outright.
    """

    def launch(self, app_key, url=None, file_path=None, content=None):
        """Returns a subprocess.Popen (or raises). `url` only matters
        for "chrome" (opened as a new tab of an already-running Chrome
        if one exists -- real Chrome's own well-known single-instance
        remoting handles that distinction entirely on its own, nothing
        extra needed here). Notepad/Settings are never launched through
        here -- they're CUSTOM_PANEL_APPS (see app_panels.py's own
        module docstring), handled entirely by
        AppPanelManager._open_custom_panel instead, with no real OS
        process at all. `file_path`/`content` are unused but kept in
        this signature for backward source compatibility with anything
        still calling this directly."""
        system = platform.system()
        if app_key == "chrome":
            args = self._chrome_command(system, url)
        elif app_key == "calculator":
            args = self._calculator_command(system)
        else:
            raise ValueError(f"don't know how to open '{app_key}'")
        return subprocess.Popen(args)

    def _chrome_command(self, system, url):
        if system == "Windows":
            candidates = [
                os.path.expandvars(
                    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(
                    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(
                    r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            ]
            exe = next((c for c in candidates if os.path.isfile(c)), "chrome.exe")
            return [exe] + ([url] if url else [])
        if system == "Darwin":
            args = ["open", "-a", "Google Chrome"]
            if url:
                args.append(url)
            return args
        args = ["google-chrome"]
        if url:
            args.append(url)
        return args

    def _calculator_command(self, system):
        if system == "Windows":
            return ["calc.exe"]
        if system == "Darwin":
            return ["open", "-a", "Calculator"]
        return ["gnome-calculator"] if _which("gnome-calculator") else ["xcalc"]


class RealWindowBackend:
    """Best-effort native-window control via raw ctypes (no pywin32
    dependency -- matches how the rest of this codebase already talks to
    win32, e.g. ide.py's DPI-awareness/DWM calls), Windows-only. Every
    method is a silent, safe no-op anywhere else: there's nothing
    reliable to grab a foreign app's window handle with on macOS/Linux
    without extra OS-specific libraries this project doesn't otherwise
    depend on, so panels still open/track/close fine there, they just
    can't be truly embedded/minimized into a pill (minimize() below
    falls back to just leaving the window as-is and tells the caller as
    much; embed() below simply reports failure so the caller falls back
    to treating that app like Chrome -- a plain separate window).

    IMPORTANT ctypes correctness note (the root cause of a real, found
    bug -- see embed() below): every win32 call here that touches a
    window STYLE or HWND value is given an explicit, correctly-sized
    `argtypes`/`restype` via _user32(). Calling a raw `ctypes.windll`
    function with no declared prototype makes ctypes assume a 32-bit
    signed `c_int` for everything, which is wrong for window styles on
    64-bit Windows: an ordinary, perfectly normal top-level window's
    style value (e.g. WS_VISIBLE | WS_CLIPSIBLINGS | WS_CAPTION | ...)
    very commonly has its top bit set, which a default-prototyped
    GetWindowLongPtrW call silently turns into a *negative* Python int
    -- and once that negative value is mixed with the plain positive
    hex mask constants below, the bitwise AND/OR/NOT arithmetic that's
    supposed to strip WS_CAPTION/WS_THICKFRAME/WS_POPUP and add
    WS_CHILD can quietly produce the wrong style altogether. SetParent
    can still report success in that case (it doesn't care what the
    style value is), so the *panel frame itself* shows up fine -- it's
    only the reparented content inside it that fails to render, which
    looks exactly like "a panel with nothing in it."
    """

    GWL_STYLE = -16
    WS_CHILD = 0x40000000
    WS_POPUP = 0x80000000
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_SYSMENU = 0x00080000
    SWP_NOZORDER = 0x0004
    SWP_FRAMECHANGED = 0x0020
    SWP_SHOWWINDOW = 0x0040
    SW_SHOW = 5

    _u32 = None  # cached, fully-prototyped ctypes.WinDLL("user32"); see _user32()

    def is_supported(self):
        return sys.platform == "win32"

    def _user32(self):
        """A single, process-wide `ctypes.WinDLL("user32", use_last_error=True)`
        with every function this class calls given an explicit,
        correctly-sized prototype -- built once and cached on the class
        (not the instance, so every RealWindowBackend -- and there's
        normally only ever one -- shares it). `use_last_error=True`
        means `ctypes.get_last_error()`/`ctypes.WinError()` right after
        a call reflects that call's real GetLastError() value, which
        embed() below uses to turn a bare "didn't work" into an actual
        Win32 error message for list_open_apps's self-diagnosis.
        """
        if RealWindowBackend._u32 is not None:
            return RealWindowBackend._u32
        import ctypes
        from ctypes import wintypes

        u32 = ctypes.WinDLL("user32", use_last_error=True)

        # LONG_PTR-correct (pointer-sized) -- see this class's own
        # docstring for exactly why this matters and what silently goes
        # wrong without it.
        u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]

        u32.SetParent.restype = wintypes.HWND
        u32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        u32.GetParent.restype = wintypes.HWND
        u32.GetParent.argtypes = [wintypes.HWND]

        u32.SetWindowPos.restype = wintypes.BOOL
        u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_uint]
        u32.MoveWindow.restype = wintypes.BOOL
        u32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.BOOL]
        u32.GetWindowRect.restype = wintypes.BOOL
        u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

        u32.ShowWindow.restype = wintypes.BOOL
        u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.SetForegroundWindow.restype = wintypes.BOOL
        u32.SetForegroundWindow.argtypes = [wintypes.HWND]
        u32.PostMessageW.restype = wintypes.BOOL
        u32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                      wintypes.WPARAM, wintypes.LPARAM]

        u32.IsWindowVisible.restype = wintypes.BOOL
        u32.IsWindowVisible.argtypes = [wintypes.HWND]
        u32.GetWindowTextLengthW.restype = ctypes.c_int
        u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u32.GetWindowTextW.restype = ctypes.c_int
        u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u32.GetWindowThreadProcessId.restype = wintypes.DWORD
        u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                  ctypes.POINTER(wintypes.DWORD)]
        u32.EnumWindows.restype = wintypes.BOOL
        u32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]

        RealWindowBackend._u32 = u32
        return u32

    @staticmethod
    def _to_long_ptr_arg(value):
        """Converts an unsigned 32-bit style bitmask into whatever
        signed representation the LONG_PTR-typed `c_ssize_t` argument
        slot expects for this process's actual pointer width, so values
        with the top bit set (very common for an ordinary visible
        top-level window's style -- see this class's docstring) pass
        through correctly on a 32-bit Python/Windows build too, instead
        of ctypes raising OverflowError there (on 64-bit this is a
        no-op: the full unsigned 32-bit range fits as a small positive
        64-bit signed number with room to spare)."""
        import ctypes
        if ctypes.sizeof(ctypes.c_void_p) == 4 and value >= 0x80000000:
            return value - 0x100000000
        return value

    @staticmethod
    def _last_error_text():
        """get_last_error()/FormatError() are themselves Windows-only
        ctypes additions (absent on other platforms' ctypes builds
        entirely), on top of embed() already only ever reaching this
        after an is_supported() == True check -- but this is kept
        defensive (never raises, just returns None) rather than relying
        on that alone, since it costs nothing and it's directly
        unit-tested cross-platform below."""
        import ctypes
        try:
            code = ctypes.get_last_error()
        except AttributeError:
            return None
        if not code:
            return None
        try:
            return f"WinError {code}: {ctypes.FormatError(code)}"
        except Exception:  # noqa: BLE001
            return f"WinError {code}"

    def _enum_visible_windows(self):
        """Every currently visible top-level window with a non-empty
        title, as {hwnd: (pid, title)}. Used by find_hwnd_for_launch's
        before/after snapshot diff below -- deliberately not filtered
        by pid here, since the whole point of that method is that pid
        matching alone can't be trusted for every app (see its
        docstring)."""
        import ctypes
        from ctypes import wintypes
        user32 = self._user32()
        windows = {}

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            pid_out = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_out))
            windows[hwnd] = (pid_out.value, buf.value)
            return True

        try:
            user32.EnumWindows(_enum, 0)
        except Exception:  # noqa: BLE001
            pass
        return windows

    def snapshot_top_level_hwnds(self):
        """A snapshot of every currently visible top-level window handle,
        meant to be taken right before launching a new app so
        find_hwnd_for_launch can tell which window is actually the
        newly-opened one. Empty set (safe no-op) anywhere not Windows."""
        if not self.is_supported():
            return set()
        try:
            return set(self._enum_visible_windows().keys())
        except Exception:  # noqa: BLE001
            return set()

    def find_hwnd_for_pid(self, pid, timeout=5.0):
        """Simple, direct pid-ownership search -- kept as a building
        block / for callers that know pid-matching is reliable for
        their specific app (e.g. a plain, non-packaged win32 app).
        Prefer find_hwnd_for_launch for anything launched through
        RealLauncher, since several of the apps this project opens are
        *not* reliably pid-matchable (see its docstring)."""
        if not self.is_supported():
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            for hwnd, (wpid, _title) in self._enum_visible_windows().items():
                if wpid == pid:
                    return hwnd
            time.sleep(0.2)
        return None

    def find_hwnd_for_launch(self, pid, title_hint, before_hwnds, timeout=8.0):
        """Finds the real window of an app that was just launched,
        robust against the fact that pid-matching alone does **not**
        reliably work for every app on modern Windows.

        Concretely: Windows 11 resolves a bare "notepad.exe" through an
        App Execution Alias that launches a legacy stub, which then
        hands off to the real, separately-packaged Notepad app -- the
        process id Python's subprocess.Popen() gets back is that
        stub's, not the pid that ends up owning the actual window (this
        is well documented: e.g. Task Manager shows a different PID
        than CreateProcess returned for exactly this reason). Modern
        Calculator has the same shape of problem via
        ApplicationFrameHost.exe hosting a separate packaged process.
        Relying purely on GetWindowThreadProcessId(hwnd) == our pid (as
        an earlier version of this file did) silently finds nothing for
        apps like these -- no exception, just an empty result -- which
        is exactly the "nothing happens, no panel, no error" failure
        this method exists to fix.

        Instead: compare the live set of visible top-level windows
        against a `before_hwnds` snapshot taken right before the app was
        launched (see snapshot_top_level_hwnds). Any window that's new
        since then is a candidate. A direct pid match among the new
        windows wins outright (covers ordinary, non-packaged apps like
        Chrome exactly as before); failing that, a case-insensitive
        `title_hint` substring match among the new windows is used
        instead (covers the stub/packaged-app cases above, where the
        window's title is still recognizably the app's name even though
        its owning process isn't the one we spawned).
        """
        if not self.is_supported():
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            current = self._enum_visible_windows()
            new_hwnds = {h: t for h, t in current.items() if h not in before_hwnds}
            for hwnd, (wpid, _title) in new_hwnds.items():
                if wpid == pid:
                    return hwnd
            if title_hint:
                hint = title_hint.lower()
                for hwnd, (_wpid, title) in new_hwnds.items():
                    if hint in (title or "").lower():
                        return hwnd
            time.sleep(0.25)
        return None

    def minimize(self, hwnd):
        if not self.is_supported() or hwnd is None:
            return False
        try:
            self._user32().ShowWindow(hwnd, 6)  # SW_MINIMIZE
            return True
        except Exception:  # noqa: BLE001
            return False

    def restore(self, hwnd):
        if not self.is_supported() or hwnd is None:
            return False
        try:
            user32 = self._user32()
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return True
        except Exception:  # noqa: BLE001
            return False

    def close(self, hwnd):
        if not self.is_supported() or hwnd is None:
            return False
        try:
            WM_CLOSE = 0x0010
            self._user32().PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return True
        except Exception:  # noqa: BLE001
            return False

    def embed(self, parent_hwnd, child_hwnd, width, height):
        """Reparents `child_hwnd` (the real app's top-level window) into
        `parent_hwnd` (a slot inside one of Friday's own EmbeddedAppPanel
        frames), stripping its native title bar/border first so it
        visually fills that slot instead of looking like a window within
        a window. Returns an (ok, reason) pair: `ok` is True on success;
        on failure `reason` is either a specific Win32 error string
        (from GetLastError -- e.g. which exact step failed and why) or
        None (not on Windows at all, or a missing handle). Every
        intermediate step is explicitly verified rather than assumed
        from a non-zero return code, since SetParent in particular can
        report "success" while the reparented content still fails to
        actually render if the style bits weren't set correctly first
        (see this class's own docstring) -- better to catch that here,
        with a precise reason, than leave the caller with a silently
        empty panel and no way to tell why.
        """
        if not self.is_supported():
            return False, None
        if not parent_hwnd or not child_hwnd:
            return False, None
        try:
            import ctypes
            user32 = self._user32()

            raw_style = user32.GetWindowLongPtrW(child_hwnd, self.GWL_STYLE)
            style = raw_style & 0xFFFFFFFF  # normalize to unsigned 32-bit
            if style == 0:
                return False, (f"couldn't read its window style "
                                f"({self._last_error_text() or 'GetWindowLongPtrW returned 0'})")
            new_style = style & ~(self.WS_POPUP | self.WS_CAPTION
                                   | self.WS_THICKFRAME | self.WS_SYSMENU)
            new_style |= self.WS_CHILD
            user32.SetWindowLongPtrW(
                child_hwnd, self.GWL_STYLE, self._to_long_ptr_arg(new_style))

            if not user32.SetParent(child_hwnd, parent_hwnd):
                return False, f"SetParent failed ({self._last_error_text() or 'unknown reason'})"

            # Verify the reparent actually stuck -- SetParent returning
            # the old parent handle is not, by itself, a 100% guarantee
            # every app accepts it (seen in the wild for some apps with
            # unusual window management of their own); GetParent is the
            # ground truth.
            actual_parent = user32.GetParent(child_hwnd)
            if actual_parent != parent_hwnd:
                return False, "SetParent reported success but GetParent doesn't confirm it"

            user32.SetWindowPos(
                child_hwnd, 0, 0, 0, int(width), int(height),
                self.SWP_NOZORDER | self.SWP_FRAMECHANGED | self.SWP_SHOWWINDOW)
            # Reparenting/restyling can leave a window in a state where
            # it technically "is visible" but hasn't actually been told
            # to show/repaint itself in its new home -- force both
            # explicitly rather than hoping SWP_SHOWWINDOW above was
            # enough on its own.
            user32.ShowWindow(child_hwnd, self.SW_SHOW)
            return True, None
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def resize_embedded(self, child_hwnd, width, height):
        if not self.is_supported() or child_hwnd is None:
            return False
        try:
            self._user32().MoveWindow(child_hwnd, 0, 0, int(width), int(height), True)
            return True
        except Exception:  # noqa: BLE001
            return False

    def get_window_rect(self, hwnd):
        """(x, y, width, height) of a real top-level window in screen
        coordinates, or None on failure/not-Windows. Used for Chrome's
        own real (never-embedded) window, so AppPanelManager can
        remember its pre-maximize position/size to restore it to later
        -- an EmbeddedAppPanel can simply remember its own Tk geometry
        instead, but a plain native window has no such bookkeeping of
        its own."""
        if not self.is_supported() or hwnd is None:
            return None
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if not self._user32().GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            return (rect.left, rect.top, rect.right - rect.left,
                    rect.bottom - rect.top)
        except Exception:  # noqa: BLE001
            return None

    def move_resize(self, hwnd, x, y, width, height):
        """Moves/resizes a real top-level window (e.g. Chrome's, which
        is never embedded) to exactly (x, y, width, height). Used by
        maximize_panel/unmaximize_panel for a non-embedded panel, the
        same job EmbeddedAppPanel.maximize_to/restore_default do
        directly in Tk for embedded ones."""
        if not self.is_supported() or hwnd is None:
            return False
        try:
            SWP_NOZORDER_OFF = 0  # we *do* want z-order touched here
            self._user32().SetWindowPos(
                hwnd, 0, int(x), int(y), int(width), int(height),
                SWP_NOZORDER_OFF)
            return True
        except Exception:  # noqa: BLE001
            return False

    def bring_to_front(self, hwnd):
        """Restores (if minimized) and raises a real top-level window to
        the foreground -- used to make a just-maximized non-embedded
        panel (Chrome) visually the active/front one, same spirit as
        EmbeddedAppPanel.maximize_to's self.lift()."""
        if not self.is_supported() or hwnd is None:
            return False
        try:
            user32 = self._user32()
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return True
        except Exception:  # noqa: BLE001
            return False



class RealTyper:
    """Best-effort live keystroke injection into an already-open native
    app's window, via the optional `pywinauto` package (Windows-only;
    not a hard dependency of this project -- see requirements.txt).
    Deliberately a separate small backend (like RealLauncher/
    RealWindowBackend above) so AppPanelManager.type_text's success
    path is unit-testable with a fake, without a real Windows desktop
    or pywinauto installed.

    Currently unused in practice: Notepad -- the only app type_text
    ever drives -- moved to CustomNotepadPanel.type_text_into_active()
    (direct, 100%-reliable manipulation of Friday's own Tk widget, no
    foreign window or optional dependency needed at all). Kept around,
    still fully wired into AppPanelManager's constructor, purely as a
    ready building block for some future app that genuinely only has a
    real foreign window to drive and no Friday-native alternative.
    """

    def available(self):
        if sys.platform != "win32":
            return False
        try:
            import pywinauto  # noqa: F401
            return True
        except ImportError:
            return False

    def type_into(self, hwnd, text):
        from pywinauto import Application
        app = Application().connect(handle=hwnd)
        win = app.window(handle=hwnd)
        win.set_focus()
        win.type_keys(text, with_spaces=True)


class _PanelHostBridge:
    """Tiny analogue of agent_tools._TkThreadBridge, dedicated to this
    module's own hidden Tk root. Guards against the classic self-
    deadlock a naive version of this would hit: a pill's own click
    handler (restore) runs *on* this same Tk thread -- as a normal Tk
    event callback -- so routing that straight back through
    root.after(0, ...) + wait() would queue the callback behind the
    very call that's blocked waiting for it. Calling fn() directly
    when already on the owning thread sidesteps that entirely, exactly
    like agent_tools._run_on_main does for the IDE's own thread.
    """

    def __init__(self, root, owner_thread):
        self._root = root
        self._owner_thread = owner_thread

    def call(self, fn):
        if threading.current_thread() is self._owner_thread:
            return fn()
        box = {}
        done = threading.Event()

        def _run():
            try:
                box["result"] = fn()
            except Exception as exc:  # noqa: BLE001
                box["exc"] = exc
            finally:
                done.set()

        try:
            self._root.after(0, _run)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("the app-panel host isn't reachable anymore") from exc
        done.wait()
        if "exc" in box:
            raise box["exc"]
        return box.get("result")

    def post(self, fn):
        if threading.current_thread() is self._owner_thread:
            fn()
            return
        self._root.after(0, fn)
