"""Regression test for the right-side "Friday AI Chat" panel inside ide.py: it
should only appear when the IDE is agent-controlled (docked into
self.body next to the editor, not the bottom "Friday CHAT" tab the IDE used
to have -- that was replaced entirely by this panel), should exist
instead of (not alongside) any such bottom tab, and a message typed into
it should round-trip through app._agent_host.ask() (a fake stand-in for
Friday's real AI brain here) and land back in the panel as bubbles.

Friday and the IDE are one process now (Task 23), so there's no chat socket
left to fake out -- ChatSidePanel._send() calls self.app._agent_host.ask(
text, on_done) directly, exactly as agent_overlay.py's real _ide_chat_ask
does in production. FakeAgentHost below plays that part, replying from a
real background thread (same as a real AI call would finish on Friday's own
worker thread) so this still genuinely exercises the self.after(0, ...)
cross-thread marshaling inside ChatSidePanel._send's on_done callback.

Requires a display (Tkinter) and must drive a REAL app.mainloop() (not
manual .update() polling) for that same reason -- the Tcl interpreter
needs to actually be inside its event loop to safely marshal a
cross-thread after(0, ...) call, exactly like production.

Run with:  DISPLAY=:99 python3 dev_tests/test_ide_chat_panel.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ide"))

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def bubble_texts(chat_panel):
    """Each message is a Label embedded as a window inside the Text
    widget (so it can have its own avatar + colored background) -- plain
    Text.get() only sees literal characters/newlines, not those embedded
    widgets' text, so tests have to walk the widget tree instead."""
    out = []

    def walk(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "Label":
                out.append(child.cget("text"))
            walk(child)

    walk(chat_panel.log)
    return out


class FakeAgentHost:
    """Stands in for agent_overlay.py's real AgentHost/._ide_chat_ask in
    this test -- replies "echo: <text>" from a genuine background
    thread, same shape a real AI call finishing on Friday's own worker
    thread would have."""

    def __init__(self):
        self.asked = []
        self.notify_handler = None

    def ask(self, text, on_done):
        self.asked.append(text)

        def worker():
            time.sleep(0.05)
            on_done(True, f"echo: {text}")

        threading.Thread(target=worker, daemon=True).start()

    def register_ide_chat_notify(self, handler):
        """Stand-in for agent_tools._AgentHost.register_ide_chat_notify --
        lets this test drive the same 'Friday proactively posts a bubble'
        path the 2-minute unanswered-pause autonomy rule's follow-up
        uses (see agent_tools.notify_ide_chat/agent_overlay.py's
        _ide_chat_auto_continue), without any of agent_overlay.py's own
        machinery -- just the IDE side's half of the contract."""
        self.notify_handler = handler

    def on_ide_closed(self):
        pass


def run_agent_controlled_case():
    import ide as ide_mod
    host = FakeAgentHost()
    app = ide_mod.IDEApp(None, agent_controlled=True, agent_host=host)

    def step1():
        check("chat side panel exists when agent-controlled",
              app.chat_panel is not None)
        check("chat side panel is docked into the body PanedWindow",
              any(str(p) == str(app.chat_panel) for p in app.body.panes()))
        check("no bottom 'Friday CHAT' tab anymore (replaced by the side panel)",
              "Friday CHAT" not in app.panel._tabs)
        check("bottom panel still defaults to TERMINAL",
              app.panel.active == "TERMINAL")
        app.chat_panel.entry.focus_set()
        app.chat_panel._clear_placeholder()
        app.chat_panel.entry.insert(0, "hello there")
        app.chat_panel._send()
        app.after(2500, step2)

    def step2():
        check("the fake host actually received the message",
              host.asked == ["hello there"])
        texts = bubble_texts(app.chat_panel)
        check("your message appears in the scrollback",
              any("hello there" in t for t in texts))
        check("Friday's reply appears in the scrollback",
              any("echo: hello there" in t for t in texts))

        # 2-minute unanswered-pause autonomy rule: the panel registers a
        # proactive-notify handler with the host on construction, and
        # that handler can append a brand new 'friday' bubble that isn't
        # a reply to anything just typed here (see
        # ChatSidePanel.receive_proactive_message).
        check("the chat panel registered a proactive-notify handler with "
              "the agent host on construction",
              host.notify_handler is not None)
        host.notify_handler(
            "No reply within 2 minutes -- going with SQLite, proceeding.")
        app.after(150, step3)

    def step3():
        texts = bubble_texts(app.chat_panel)
        check("a proactively-notified message shows up as its own new "
              "'friday' bubble, unprompted by anything typed",
              any("going with SQLite, proceeding" in t for t in texts))
        app.after(50, app.destroy)

    app.after(300, step1)
    app.mainloop()

    for mod in ("ide",):
        sys.modules.pop(mod, None)


def run_no_host_case():
    """Agent-controlled but with agent_host=None (e.g. something went
    wrong wiring it up) -- the panel should still show and report a
    clear error instead of hanging forever."""
    import ide as ide_mod
    app = ide_mod.IDEApp(None, agent_controlled=True, agent_host=None)

    def step1():
        app.chat_panel.entry.focus_set()
        app.chat_panel._clear_placeholder()
        app.chat_panel.entry.insert(0, "hello")
        app.chat_panel._send()
        app.after(300, step2)

    def step2():
        texts = bubble_texts(app.chat_panel)
        check("a clear error shows when no agent_host is wired up",
              any("chat channel isn't available" in t for t in texts))
        app.after(50, app.destroy)

    app.after(200, step1)
    app.mainloop()
    sys.modules.pop("ide", None)


def run_standalone_case():
    # A plain (non-agent-controlled) run must NOT show the chat panel and
    # must keep behaving exactly as before this feature existed.
    import ide as ide_mod
    app = ide_mod.IDEApp(None, agent_controlled=False)
    check("no chat side panel in a standalone run", app.chat_panel is None)
    check("no 'Friday CHAT' tab standalone either", "Friday CHAT" not in app.panel._tabs)
    check("TERMINAL is still the default tab standalone", app.panel.active == "TERMINAL")
    check("panel stays collapsed by default standalone", not app.panel_visible)
    app.destroy()
    sys.modules.pop("ide", None)


def main():
    run_agent_controlled_case()
    run_no_host_case()
    run_standalone_case()
    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
