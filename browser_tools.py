"""Real browser automation for Friday -- Playwright-backed, so Friday can
actually navigate pages, read real rendered content, fill in forms, click
things, and read a page's own console output, not just fetch/search text
(see web_search/agent_overlay.py's ide_open_in_browser, neither of which
does any of this). Added at the user's explicit request: a general-purpose
browsing capability to use "to its advantage later on" for research, form
filling, and similar -- the detailed behavioral skill doc governing *how*
to use it well is still to come (same two-step pattern as
FRONTEND_SKILL.md: the capability ships first, the skill doc refines it),
the same way Task 65 wired ide_get_backend_skill()/ide_get_storage_skill()
ahead of the skill content itself.

Deliberately general-purpose, not ide_* scoped: browsing the web for
research or filling out some external form has nothing to do with the
open IDE workspace, so these tools are registered the same
unrestricted way web_search already is -- available from the floating
circle and the IDE's embedded chat panel alike, not gated behind
Agent Mode.

Threading note, the one genuinely tricky part: Playwright's *sync* API
(used here, not asyncio, to match this codebase's otherwise-synchronous
tool-function style) is not safe to drive from more than one OS thread
over its lifetime -- the underlying driver connection has thread
affinity. But every tool call in this app arrives on whatever thread
happens to be running at the time (Friday's floating-circle AIWorker
QThread for one conversation, the IDE chat panel's own AIWorker QThread
for another, potentially a *different* QThread instance per message).
Constructing a fresh sync_playwright() per call would work but throws
away the whole point of a persistent browser session (the same open
page across a navigate -> fill -> click -> read-result sequence of
separate tool calls). The fix, same shape as agent_tools._TkThreadBridge
already uses for Tk: one dedicated, long-lived background thread owns
the single Playwright/browser/page instance for this process's entire
lifetime; every public function here just enqueues a job onto that one
thread and blocks for the result, so Playwright itself is always
actually driven from the one thread it started on, no matter which
caller thread asked.
"""
import os
import queue
import threading
import time

# -------------------------------------------------------------------------
# The single dedicated worker thread that actually owns Playwright.
# -------------------------------------------------------------------------

_MAX_TEXT_CHARS = 8000   # keep a single tool result from blowing out context
_MAX_CONSOLE_LOGS = 200  # ring buffer cap, oldest dropped first


class _BrowserWorker:
    """Owns one Playwright instance, one Chromium browser, one page --
    created lazily on first real use, torn down explicitly via close()
    or when the process exits. All Playwright calls happen inside run()
    on self._thread; every public browser_* function below goes through
    call() rather than touching Playwright directly."""

    def __init__(self):
        self._thread = None
        self._jobs = queue.Queue()
        self._ready = threading.Event()
        self._start_error = None
        self._playwright = None
        self._browser = None
        self._page = None
        self._console_logs = []
        self._lock = threading.Lock()

    def ensure_started(self):
        """Lazily starts the dedicated thread + launches the browser, if
        not already running. Safe to call from any thread, any number of
        times. Returns an error string, or None on success."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._start_error:
                    return self._start_error
                return None
            self._ready.clear()
            self._start_error = None
            self._thread = threading.Thread(
                target=self._run, name="FridayBrowserWorker", daemon=True)
            self._thread.start()
        self._ready.wait(timeout=60)
        return self._start_error

    def _run(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            self._start_error = (
                f"Playwright isn't installed/importable ({exc}). Run "
                "`pip install playwright && playwright install chromium`."
            )
            self._ready.set()
            return
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            self._page = self._browser.new_page()
            self._page.on("console", self._on_console)
            self._page.on("pageerror", lambda e: self._on_console(
                _FakeConsoleMsg("error", str(e))))
        except Exception as exc:  # noqa: BLE001
            self._start_error = f"Couldn't launch the browser: {exc}"
            self._ready.set()
            return
        self._ready.set()
        # Main loop: pull jobs, run them on THIS thread (the one that
        # actually owns the Playwright connection), post results back.
        while True:
            job = self._jobs.get()
            if job is None:  # shutdown sentinel
                break
            fn, result_box, done_event = job
            try:
                result_box["value"] = fn(self._page)
            except Exception as exc:  # noqa: BLE001
                result_box["error"] = exc
            done_event.set()
        try:
            if self._browser is not None:
                self._browser.close()
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:  # noqa: BLE001
            pass

    def _on_console(self, msg):
        with self._lock:
            self._console_logs.append(
                f"[{msg.type}] {msg.text}")
            if len(self._console_logs) > _MAX_CONSOLE_LOGS:
                del self._console_logs[: len(self._console_logs) - _MAX_CONSOLE_LOGS]

    def get_console_logs(self):
        with self._lock:
            return list(self._console_logs)

    def clear_console_logs(self):
        with self._lock:
            self._console_logs.clear()

    def call(self, fn, timeout=30):
        """Runs fn(page) on the dedicated browser thread and returns its
        result, raising whatever exception fn raised (callers catch and
        format a clean string -- same convention as every other tool in
        agent_tools.py)."""
        err = self.ensure_started()
        if err:
            raise RuntimeError(err)
        result_box = {}
        done_event = threading.Event()
        self._jobs.put((fn, result_box, done_event))
        if not done_event.wait(timeout=timeout):
            raise TimeoutError(
                f"Browser action timed out after {timeout}s -- the page "
                "may be hung or waiting on something that never appears.")
        if "error" in result_box:
            raise result_box["error"]
        return result_box.get("value")

    def is_running(self):
        return self._thread is not None and self._thread.is_alive() and self._page is not None

    def shutdown(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return
            self._jobs.put(None)
        self._thread.join(timeout=10)
        self._thread = None
        self._page = None
        self._browser = None
        self._playwright = None


class _FakeConsoleMsg:
    """Minimal stand-in so pageerror (uncaught JS exceptions, which
    Playwright reports differently from console.* calls) can be folded
    into the same console-log ring buffer/format as everything else --
    a Review-region-style "no console errors" check should see both."""

    def __init__(self, type_, text):
        self.type = type_
        self.text = text


_worker = None
_worker_lock = threading.Lock()


def _get_worker():
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = _BrowserWorker()
        return _worker


def _truncate(text, limit=_MAX_TEXT_CHARS):
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated, {len(text) - limit} more characters]"


def _screenshot_dir():
    """Prefer the open IDE workspace (visible in its Explorer, same as
    anything ide_create_file writes) so a screenshot taken mid-build is
    right there with the rest of the artifact; otherwise a fixed
    fallback folder under the user's home so it's still always
    reachable even with no IDE open."""
    try:
        import agent_tools
        if agent_tools.is_agent_mode_on() and agent_tools._ide_app is not None:
            root = getattr(agent_tools._ide_app, "root_dir", None)
            if root:
                d = os.path.join(root, "browser_screenshots")
                os.makedirs(d, exist_ok=True)
                return d
    except Exception:  # noqa: BLE001
        pass
    d = os.path.join(os.path.expanduser("~"), "friday_browser_screenshots")
    os.makedirs(d, exist_ok=True)
    return d


# -------------------------------------------------------------------------
# Public tool functions -- each a thin, string-returning wrapper, same
# convention as every other tool in agent_tools.py (never raises, always
# a clear message on failure).
# -------------------------------------------------------------------------

def browser_navigate(url: str) -> str:
    """Open a real browser and navigate to `url` (launches the browser on
    first use; reuses the same browser/page on every later call, so
    later browser_* calls act on whatever page this leaves open).

    Args:
        url: The address to go to. "http://"/"https://" is added
            automatically if missing.
    """
    if "://" not in url:
        url = "https://" + url
    worker = _get_worker()

    def _do(page):
        worker.clear_console_logs()
        resp = page.goto(url, timeout=20000, wait_until="domcontentloaded")
        status = resp.status if resp is not None else "?"
        return f"Navigated to {page.url} (HTTP {status}). Title: {page.title()!r}"

    try:
        return worker.call(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error navigating to {url!r}: {exc}"


def browser_click(selector: str) -> str:
    """Click the first element matching `selector` on the current page.

    Args:
        selector: A CSS selector (e.g. "#submit", ".btn-primary"), or a
            Playwright text selector (e.g. "text=Sign in").
    """
    worker = _get_worker()

    def _do(page):
        page.click(selector, timeout=10000)
        return f"Clicked {selector!r}. Current page is now {page.url!r}."

    try:
        return worker.call(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error clicking {selector!r}: {exc}"


def browser_fill(selector: str, text: str) -> str:
    """Fill a form field (input/textarea) with `text`, replacing whatever
    was already in it.

    Args:
        selector: CSS selector for the field, e.g. "#email",
            "input[name='q']".
        text: The text to put in the field.
    """
    worker = _get_worker()

    def _do(page):
        page.fill(selector, text, timeout=10000)
        return f"Filled {selector!r} with {text!r}."

    try:
        return worker.call(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error filling {selector!r}: {exc}"


def browser_select_option(selector: str, value: str) -> str:
    """Choose an option in a <select> dropdown, by value, label, or index.

    Args:
        selector: CSS selector for the <select> element.
        value: The option's value attribute or its visible label text.
    """
    worker = _get_worker()

    def _do(page):
        try:
            chosen = page.select_option(selector, value=value, timeout=8000)
        except Exception:
            chosen = page.select_option(selector, label=value, timeout=8000)
        return f"Selected {chosen!r} in {selector!r}."

    try:
        return worker.call(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error selecting an option in {selector!r}: {exc}"


def browser_press_key(selector: str, key: str) -> str:
    """Focus an element and press a keyboard key on it -- e.g. "Enter" to
    submit a search box after browser_fill.

    Args:
        selector: CSS selector of the element to focus first.
        key: Key name Playwright understands, e.g. "Enter", "Tab",
            "Escape".
    """
    worker = _get_worker()

    def _do(page):
        page.press(selector, key, timeout=8000)
        return f"Pressed {key!r} on {selector!r}. Current page is now {page.url!r}."

    try:
        return worker.call(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error pressing {key!r} on {selector!r}: {exc}"


def browser_wait_for(selector: str, timeout_ms: int = 5000) -> str:
    """Wait for an element to appear/become visible -- useful on
    JS-heavy pages that render content after the initial load.

    Args:
        selector: CSS selector to wait for.
        timeout_ms: How long to wait, in milliseconds, before giving up.
    """
    worker = _get_worker()

    def _do(page):
        page.wait_for_selector(selector, timeout=timeout_ms)
        return f"{selector!r} is now present/visible."

    try:
        return worker.call(_do, timeout=(timeout_ms / 1000) + 5)
    except Exception as exc:  # noqa: BLE001
        return f"{selector!r} never appeared within {timeout_ms}ms: {exc}"


def browser_read_text(selector: str = "") -> str:
    """Read the visible, rendered text of the current page (or one
    element on it) -- the actual text a human would see, not raw HTML.

    Args:
        selector: CSS selector to read just one element's text; leave
            empty to read the whole page body.
    """
    worker = _get_worker()

    def _do(page):
        target = selector or "body"
        return page.inner_text(target, timeout=8000)

    try:
        return _truncate(worker.call(_do))
    except Exception as exc:  # noqa: BLE001
        return f"Error reading text from {selector or 'the page'!r}: {exc}"


def browser_get_html(selector: str = "") -> str:
    """Get the raw HTML of the current page (or one element) -- use this
    over browser_read_text when you need actual markup (ids, classes,
    attributes, structure), e.g. to confirm what a page's real DOM looks
    like rather than just its visible text.

    Args:
        selector: CSS selector for one element's outerHTML; leave empty
            for the whole page's HTML.
    """
    worker = _get_worker()

    def _do(page):
        if selector:
            return page.eval_on_selector(selector, "el => el.outerHTML")
        return page.content()

    try:
        return _truncate(worker.call(_do))
    except Exception as exc:  # noqa: BLE001
        return f"Error reading HTML from {selector or 'the page'!r}: {exc}"


def browser_get_links() -> str:
    """List every link on the current page (href + visible text) --
    useful for research/crawling: see what a page links to before
    deciding where to navigate next."""
    worker = _get_worker()

    def _do(page):
        links = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({href: e.href, text: e.innerText.trim()}))"
            ".filter(l => l.text || l.href)")
        return links

    try:
        links = worker.call(_do)
        if not links:
            return "No links found on the current page."
        lines = [f"- {l['text'] or '(no text)'} -> {l['href']}" for l in links[:200]]
        extra = f"\n...and {len(links) - 200} more" if len(links) > 200 else ""
        return _truncate("\n".join(lines) + extra)
    except Exception as exc:  # noqa: BLE001
        return f"Error reading links: {exc}"


def browser_evaluate(script: str) -> str:
    """Run JavaScript in the current page and return its result --
    for anything the other browser_* tools don't cover directly (reading
    a computed style, checking an element's state, custom DOM queries).
    Runs inside the sandboxed headless browser Friday itself controls,
    not the user's own browser or OS.

    Args:
        script: A JS expression or function body to evaluate, e.g.
            "document.title" or "() => document.forms.length".
    """
    worker = _get_worker()

    def _do(page):
        return page.evaluate(script)

    try:
        result = worker.call(_do)
        return _truncate(str(result))
    except Exception as exc:  # noqa: BLE001
        return f"Error evaluating script: {exc}"


def browser_get_console_logs() -> str:
    """Return the browser's own console output (console.log/warn/error
    and uncaught JS exceptions) captured since the last browser_navigate
    call -- the mechanical way to actually check "does this page have
    console errors," not a guess."""
    worker = _get_worker()
    logs = worker.get_console_logs()
    if not logs:
        return "No console output captured since the last navigation."
    return _truncate("\n".join(logs))


def browser_screenshot(filename: str = "") -> str:
    """Save a screenshot of the current page. Saved into the open IDE
    workspace's browser_screenshots/ folder if one is open, otherwise to
    ~/friday_browser_screenshots/. Returns the saved file's path.

    Args:
        filename: Optional name for the file (".png" added if missing);
            a timestamped default is used if not given.
    """
    worker = _get_worker()
    name = filename.strip() or f"screenshot-{int(time.time())}"
    if not name.lower().endswith(".png"):
        name += ".png"
    path = os.path.join(_screenshot_dir(), name)

    def _do(page):
        page.screenshot(path=path, timeout=10000)
        return path

    try:
        saved = worker.call(_do)
        return f"Screenshot saved to {saved}"
    except Exception as exc:  # noqa: BLE001
        return f"Error taking a screenshot: {exc}"


def browser_go_back() -> str:
    """Go back to the previous page in the browser's history."""
    worker = _get_worker()

    def _do(page):
        page.go_back(timeout=10000)
        return f"Went back. Current page is now {page.url!r} ({page.title()!r})."

    try:
        return worker.call(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Error going back: {exc}"


def browser_current_state() -> str:
    """Report whether a browser session is open right now, and if so
    what page it's on -- check this before assuming browser_click/
    browser_fill/etc. have anything to act on."""
    worker = _get_worker()
    if not worker.is_running():
        return "No browser session is open yet. Call browser_navigate(url) to start one."

    def _do(page):
        return f"Open on {page.url!r}, title {page.title()!r}."

    try:
        return worker.call(_do)
    except Exception as exc:  # noqa: BLE001
        return f"Browser session exists but couldn't be queried: {exc}"


def browser_close() -> str:
    """Close the browser session and free its resources. The next
    browser_navigate call will start a fresh one."""
    worker = _get_worker()
    if not worker.is_running():
        return "No browser session was open."
    try:
        worker.shutdown()
        return "Browser session closed."
    except Exception as exc:  # noqa: BLE001
        return f"Error closing the browser: {exc}"
