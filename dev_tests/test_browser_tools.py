"""Regression test for browser_tools.py / the browser_* tool suite --
real Playwright-backed browser automation added at the user's request so
Friday can navigate real pages, read actual rendered content and console
output, and fill in/click/submit forms (not just web_search's text
snippets or ide_open_in_browser's "open it for a human to look at").

Deliberately uses a local file:// fixture page, not a live network
request -- a test that depends on a real website's exact markup/content
staying the same forever is fragile and flaky; everything genuinely
Playwright-specific (navigation, DOM reads, form interaction, console
capture, JS evaluation, waiting, history) is fully exercised against a
page this test controls completely.

Covers:
  A. Tool registration -- all 15 browser_* tools agree across
     GEMINI_TOOLS/TOOL_FUNCTIONS/TOOL_SCHEMAS, and are NOT Agent-Mode-
     gated (general-purpose, like web_search, not an ide_* tool).
  B. browser_current_state() before any session exists.
  C. Navigation, rendered-text read, raw-HTML read, and link listing
     against the fixture page.
  D. Form interaction: fill -> select_option -> click actually runs the
     page's own JS and the result is readable afterward.
  E. Console log capture: a deliberate console.error from the fixture
     page is captured, and a fresh browser_navigate() clears the ring
     buffer rather than accumulating forever across pages.
  F. browser_evaluate() -- arbitrary JS executes and its return value
     comes back correctly.
  G. browser_wait_for() -- succeeds for an element that appears after a
     real delay, and returns a clear (non-hanging, non-crashing) message
     for one that never appears.
  H. browser_go_back() -- real browser history navigation.
  I. browser_screenshot() -- an actual non-empty PNG file lands on disk.
  J. browser_close() then browser_navigate() again -- a closed session
     cleanly starts a fresh one, not left broken.
  K. Thread-affinity: every call above is made from a background thread
     (not the test's main thread) -- the exact shape a real AIWorker
     QThread tool call takes -- proving the dedicated single-thread
     Playwright bridge actually works under that constraint, not just
     when convenient.
  L. Error handling: acting on a selector that doesn't exist on the page
     returns a clean, readable error string -- it never raises out of
     the tool function itself.

Requires Playwright with the chromium browser installed:
    pip install playwright && playwright install chromium
    python3 dev_tests/test_browser_tools.py
"""
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_tools as at  # noqa: E402
import browser_tools as bt  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


FIXTURE_HTML = """<!DOCTYPE html>
<html><head><title>Fixture Page</title></head>
<body>
<p id="greeting">Hello, nobody yet.</p>
<form>
  <input id="name" type="text">
  <select id="color"><option value="r">Red</option><option value="b">Blue</option></select>
  <button id="go" type="button"
    onclick="document.getElementById('out').innerText = document.getElementById('name').value + ':' + document.getElementById('color').value; console.error('deliberate test error');">
    Go
  </button>
  <input id="searchish" type="text" onkeydown="if(event.key==='Enter'){document.getElementById('out').innerText='enter-pressed';}">
</form>
<div id="out"></div>
<a href="page2.html">Next page</a>
<a href="https://example.com">External</a>
<script>
setTimeout(function() {
    var d = document.createElement('div');
    d.id = 'late';
    d.innerText = 'I appeared late';
    document.body.appendChild(d);
}, 300);
</script>
</body></html>
"""

FIXTURE_PAGE2 = """<!DOCTYPE html>
<html><head><title>Page Two</title></head>
<body><p>This is page two.</p></body></html>
"""


def _run_in_thread(fn, timeout=60):
    """Runs fn() on a brand new background thread and returns its result
    -- the same shape a real AIWorker QThread tool call takes, so this
    test actually proves the dedicated-thread Playwright bridge works
    under the real constraint, not just when conveniently called from
    the test's own main thread."""
    box = {}

    def _wrapped():
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=_wrapped)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        raise TimeoutError("background thread call never finished")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def part_a_tool_registration():
    print("\n--- Part A: tool registration ---")
    expected = {
        "browser_navigate", "browser_click", "browser_fill",
        "browser_select_option", "browser_press_key", "browser_wait_for",
        "browser_read_text", "browser_get_html", "browser_get_links",
        "browser_evaluate", "browser_get_console_logs", "browser_screenshot",
        "browser_go_back", "browser_current_state", "browser_close",
    }
    schema_names = {s["function"]["name"] for s in at.TOOL_SCHEMAS}
    gemini_names = {f.__name__ for f in at.GEMINI_TOOLS}
    func_names = set(at.TOOL_FUNCTIONS.keys())

    check("all 15 browser_* tools are in TOOL_SCHEMAS",
          expected.issubset(schema_names))
    check("all 15 browser_* tools are in GEMINI_TOOLS",
          expected.issubset(gemini_names))
    check("all 15 browser_* tools are in TOOL_FUNCTIONS",
          expected.issubset(func_names))
    check("the three registries agree exactly (no orphan tool anywhere)",
          schema_names == gemini_names == func_names)
    check("browser_* tools are general-purpose, NOT Agent-Mode-gated "
          "(same as web_search, unlike the ide_* tools)",
          expected.isdisjoint(at._AGENT_MODE_ONLY_TOOLS))


def part_b_initial_state():
    print("\n--- Part B: initial state, no session yet ---")
    # Fresh worker so this doesn't depend on test ordering/leftover state.
    bt._worker = bt._BrowserWorker()
    state = _run_in_thread(at.browser_current_state)
    check("before any navigation, current_state says plainly there's no session",
          "No browser session" in state)


def part_c_to_l_everything_else(fixture_dir):
    print("\n--- Parts C-L: real navigation/interaction/evaluation ---")
    page1 = "file://" + os.path.join(fixture_dir, "page1.html")
    page2 = "file://" + os.path.join(fixture_dir, "page2.html")

    # -- C: navigation + reads.
    nav_result = _run_in_thread(lambda: at.browser_navigate(page1))
    check("navigate reports success with the real title",
          "Fixture Page" in nav_result)
    state = _run_in_thread(at.browser_current_state)
    check("current_state now reflects the open page",
          "Fixture Page" in state and "page1.html" in state)
    text = _run_in_thread(lambda: at.browser_read_text("#greeting"))
    check("read_text on a specific selector returns exactly that element's text",
          text.strip() == "Hello, nobody yet.")
    html = _run_in_thread(lambda: at.browser_get_html("#greeting"))
    check("get_html on a selector returns real markup, not just text",
          "<p" in html and "id=\"greeting\"" in html)
    links = _run_in_thread(at.browser_get_links)
    check("get_links finds both real links on the page",
          "page2.html" in links and "example.com" in links)

    # -- D: form interaction actually runs the page's own JS.
    fill_result = _run_in_thread(lambda: at.browser_fill("#name", "Ada Lovelace"))
    check("fill reports success", "Ada Lovelace" in fill_result)
    select_result = _run_in_thread(lambda: at.browser_select_option("#color", "b"))
    check("select_option reports the chosen value", "'b'" in select_result or "b" in select_result)
    click_result = _run_in_thread(lambda: at.browser_click("#go"))
    check("click reports success", "Clicked" in click_result)
    out_text = _run_in_thread(lambda: at.browser_read_text("#out"))
    check("the click handler's actual JS ran -- the filled values show up "
          "in the page's own output element", out_text.strip() == "Ada Lovelace:b")

    # -- E: console capture + reset on navigate.
    console_after_click = _run_in_thread(at.browser_get_console_logs)
    check("the deliberate console.error from the click handler was captured",
          "deliberate test error" in console_after_click)
    _run_in_thread(lambda: at.browser_navigate(page2))
    console_after_nav = _run_in_thread(at.browser_get_console_logs)
    check("navigating to a new page clears the console ring buffer "
          "rather than accumulating across pages forever",
          "deliberate test error" not in console_after_nav)

    # -- F: evaluate.
    eval_result = _run_in_thread(lambda: at.browser_evaluate("1 + 41"))
    check("evaluate runs real JS and returns the actual result", eval_result.strip() == "42")
    title_result = _run_in_thread(lambda: at.browser_evaluate("document.title"))
    check("evaluate can read real page state (document.title)",
          "Page Two" in title_result)

    # -- back to page1 for the remaining checks that need its fixtures.
    _run_in_thread(lambda: at.browser_navigate(page1))

    # -- G: wait_for, success and failure paths.
    wait_ok = _run_in_thread(lambda: at.browser_wait_for("#late", timeout_ms=2000))
    check("wait_for succeeds once a delayed element actually appears",
          "now present" in wait_ok)
    wait_fail = _run_in_thread(
        lambda: at.browser_wait_for("#this-selector-does-not-exist", timeout_ms=500))
    check("wait_for on something that never appears returns a clear "
          "message instead of hanging or raising",
          "never appeared" in wait_fail)

    # -- press_key.
    press_result = _run_in_thread(lambda: at.browser_press_key("#searchish", "Enter"))
    check("press_key reports success", "Pressed" in press_result)
    out_after_enter = _run_in_thread(lambda: at.browser_read_text("#out"))
    check("the keydown handler actually fired from the pressed key",
          out_after_enter.strip() == "enter-pressed")

    # -- H: go_back (currently on page1, but we navigated 1->2->1, so
    # history has page2 right before this page1).
    back_result = _run_in_thread(at.browser_go_back)
    check("go_back reports success and lands on the expected prior page",
          "page2.html" in back_result or "Page Two" in back_result)

    # -- I: screenshot actually produces a real file.
    with tempfile.TemporaryDirectory() as shot_dir:
        shot_path_holder = {}

        def _shot():
            return at.browser_screenshot(os.path.join(shot_dir, "shot.png"))

        # screenshot() only takes a filename, not a full path, by design
        # (it decides the directory itself) -- so just take one with a
        # plain name and locate it via _screenshot_dir().
        shot_result = _run_in_thread(lambda: at.browser_screenshot("test-shot-regress"))
        check("screenshot reports a saved path", "Screenshot saved to" in shot_result)
        saved_path = shot_result.split("Screenshot saved to", 1)[1].strip()
        check("the screenshot file actually exists on disk",
              os.path.exists(saved_path))
        check("the screenshot file is a real, non-trivial PNG, not an "
              "empty/stub file", os.path.getsize(saved_path) > 1000)
        try:
            os.remove(saved_path)
        except OSError:
            pass

    # -- L: error handling -- acting on a selector that isn't there.
    bad_click = _run_in_thread(lambda: at.browser_click("#this-does-not-exist-at-all"))
    check("clicking a nonexistent selector returns a clean error string, "
          "not a raised exception escaping the tool function",
          bad_click.startswith("Error"))
    bad_fill = _run_in_thread(lambda: at.browser_fill("#also-missing", "x"))
    check("filling a nonexistent selector also fails cleanly",
          bad_fill.startswith("Error"))

    # -- J: close, then a fresh navigate still works.
    close_result = _run_in_thread(at.browser_close)
    check("close reports success", "closed" in close_result.lower())
    state_after_close = _run_in_thread(at.browser_current_state)
    check("current_state reflects no session right after closing",
          "No browser session" in state_after_close)
    renav_result = _run_in_thread(lambda: at.browser_navigate(page1))
    check("a fresh navigate after close starts a brand new session cleanly",
          "Fixture Page" in renav_result)
    _run_in_thread(at.browser_close)


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright isn't installed in this environment -- skipping "
              "(pip install playwright && playwright install chromium).")
        return

    part_a_tool_registration()
    part_b_initial_state()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            browser.close()
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).splitlines()[0].encode("ascii", "replace").decode("ascii")
        print(f"Chromium isn't available in this environment -- skipping "
              f"live browser checks: {reason}")
        passed = sum(1 for _, ok in CHECKS if ok)
        print(f"\n{passed}/{len(CHECKS)} non-browser checks passed")
        if passed != len(CHECKS):
            sys.exit(1)
        return

    with tempfile.TemporaryDirectory() as fixture_dir:
        with open(os.path.join(fixture_dir, "page1.html"), "w", encoding="utf-8") as f:
            f.write(FIXTURE_HTML)
        with open(os.path.join(fixture_dir, "page2.html"), "w", encoding="utf-8") as f:
            f.write(FIXTURE_PAGE2)
        part_c_to_l_everything_else(fixture_dir)

    total = len(CHECKS)
    passed = sum(1 for _, ok in CHECKS if ok)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        print("\nFailed checks:")
        for label, ok in CHECKS:
            if not ok:
                print("  - " + label)
        sys.exit(1)


if __name__ == "__main__":
    main()
