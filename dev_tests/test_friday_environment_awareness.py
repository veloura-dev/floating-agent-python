"""Regression test for two related additions:

1. **Environment awareness** (agent_tools.get_environment_snapshot() +
   agent_overlay.AIWorker._load_environment_context()/_system_prompt()):
   Friday is told, automatically, every single turn -- with no tool call
   needed -- which panels are open, which one (if any) has the shared
   maximized/focused slot, and (if Agent Mode is on) the IDE's sidebar
   view and active editor tab. This is the ambient counterpart to the
   explicit list_open_apps()/ide_list_open_tabs() tools, which still
   exist for on-demand drill-down.

2. **Advanced thinking skills** (agent_overlay._load_thinking_skills()):
   thinking_skills.md, next to personality.md, is loaded and appended to
   SYSTEM_PROMPT the same way personality.md itself is -- a reasoning
   method Friday follows for every reply, separate from personality.md's
   "how he sounds" instructions.

Requires PySide6 with an offscreen-capable platform plugin:
    QT_QPA_PLATFORM=offscreen python3 dev_tests/test_friday_environment_awareness.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_tools as at  # noqa: E402
import agent_overlay as ov  # noqa: E402

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def _reset_agent_tools_state():
    """Agent_tools.py's panel/IDE state is module-level global -- reset
    it between sections so one test's fake panels/IDE can't leak into
    the next."""
    at._ide_app = None
    at._ide_opened_at = None
    with at._panel_manager._lock:
        at._panel_manager._panels.clear()


class _FakeSidebar:
    def __init__(self, mode):
        self.mode = mode


class _FakeIDEApp:
    """A plain stand-in for IDEApp with just the attributes
    get_environment_snapshot() actually reads -- no real Tk window
    needed, since _run_on_main() calls fn() directly when there's no
    registered IDE thread and we're on the main thread (true here)."""

    def __init__(self, buffers=None, current=None, sidebar_mode="explorer",
                 sidebar_visible=True, minimized=False):
        self.buffers = buffers or []
        self.current = current
        self.sidebar = _FakeSidebar(sidebar_mode)
        self.sidebar_visible = sidebar_visible
        self._pill = object() if minimized else None


def part_a_snapshot():
    print("\n--- Part A: get_environment_snapshot() ---")
    _reset_agent_tools_state()

    # ---- nothing open at all ----
    snap = at.get_environment_snapshot()
    check("says plainly that nothing is open, rather than returning "
          "nothing at all -- Friday should always be able to answer "
          "'what do you have open?' without a tool call",
          "Nothing else is open" in snap)
    check("always includes the same clear section header so the model "
          "can tell this apart from the memory section",
          "What's currently on screen" in snap)

    # ---- one native app panel, open, not active ----
    _reset_agent_tools_state()
    at._panel_manager._panels["notepad"] = {
        "label": "Notepad", "proc": None, "minimized": False, "maximized": False,
    }
    snap = at.get_environment_snapshot()
    check("lists an open, non-maximized panel as plain 'open', with no "
          "active/focused marker",
          "- Notepad (open)" in snap and "active" not in snap)

    # ---- one minimized, one maximized (= active) ----
    _reset_agent_tools_state()
    at._panel_manager._panels["notepad"] = {
        "label": "Notepad", "proc": None, "minimized": False, "maximized": True,
    }
    at._panel_manager._panels["calculator"] = {
        "label": "Calculator", "proc": None, "minimized": True, "maximized": False,
    }
    snap = at.get_environment_snapshot()
    check("the maximized panel is marked as currently active/focused",
          "Notepad (open, currently active/focused)" in snap)
    check("the minimized one is listed separately as minimized, not active",
          "Calculator (minimized)" in snap
          and "Calculator (minimized, currently active/focused)" not in snap)

    # ---- a dead process is dropped (same _live_panels() cleanup logic
    # list_panels() already relies on) ----
    _reset_agent_tools_state()

    class _DeadProc:
        def poll(self):
            return 0  # already exited

    at._panel_manager._panels["ghost"] = {
        "label": "Ghost App", "proc": _DeadProc(), "minimized": False, "maximized": False,
    }
    snap = at.get_environment_snapshot()
    check("a panel whose process already exited is quietly dropped, not "
          "reported as still open",
          "Ghost App" not in snap)

    # ---- IDE open, sidebar visible, an active unsaved tab ----
    _reset_agent_tools_state()
    at._ide_app = _FakeIDEApp(
        buffers=[{"path": None, "name": "untitled", "modified": False},
                 {"path": "/home/user/app.py", "name": "app.py", "modified": True}],
        current=1, sidebar_mode="git", sidebar_visible=True,
    )
    snap = at.get_environment_snapshot()
    check("reports the IDE as open when Agent Mode is on",
          "The IDE is open and active" in snap)
    check("includes which sidebar view is currently showing",
          'sidebar showing "git"' in snap)
    check("includes the active tab's path and that it has unsaved changes",
          "/home/user/app.py" in snap and "unsaved changes" in snap)

    # ---- IDE open but minimized to a pill ----
    _reset_agent_tools_state()
    at._ide_app = _FakeIDEApp(minimized=True)
    snap = at.get_environment_snapshot()
    check("a minimized IDE is reported as minimized, not as a normal "
          "active window with sidebar/tab detail",
          "minimized to a pill" in snap
          and "sidebar showing" not in snap)

    # ---- IDE open with sidebar hidden, no tabs open ----
    _reset_agent_tools_state()
    at._ide_app = _FakeIDEApp(buffers=[], current=None, sidebar_visible=False)
    snap = at.get_environment_snapshot()
    check("a hidden sidebar is reported as hidden",
          "sidebar hidden" in snap)
    check("no active tab is mentioned when no tabs are open",
          "active file" not in snap)

    # ---- both the IDE and a native panel at once ----
    _reset_agent_tools_state()
    at._ide_app = _FakeIDEApp(sidebar_mode="search")
    at._panel_manager._panels["chrome"] = {
        "label": "Google Chrome", "proc": None, "minimized": False, "maximized": False,
    }
    snap = at.get_environment_snapshot()
    check("the IDE and a separate native panel are both listed together",
          "The IDE is open" in snap and "Google Chrome (open)" in snap)

    _reset_agent_tools_state()


def part_b_wiring():
    print("\n--- Part B: AIWorker wiring ---")
    import importlib
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("MISTRAL_API_KEY", None)

    _reset_agent_tools_state()
    w = ov.AIWorker("what's open right now?", parent=None)
    check("AIWorker's environment context is empty right after "
          "construction (computed in run(), same reasoning as "
          "_memory_context -- never block __init__ on a Tk-thread call)",
          w._environment_context == "")
    w._load_environment_context()
    check("after _load_environment_context(), an empty environment still "
          "reports plainly that nothing is open",
          "Nothing else is open" in w._environment_context)
    check("the environment context is folded into the effective system "
          "prompt",
          "What's currently on screen" in w._system_prompt())

    at._panel_manager._panels["notepad"] = {
        "label": "Notepad", "proc": None, "minimized": False, "maximized": True,
    }
    w2 = ov.AIWorker("what's open right now?", parent=None)
    w2._load_environment_context()
    check("a real open panel shows up in AIWorker's environment context",
          "Notepad" in w2._environment_context)
    check("...and in the effective system prompt too",
          "Notepad" in w2._system_prompt())
    _reset_agent_tools_state()

    # summarize_only calls still get environment context (unlike memory
    # context, which they deliberately skip) -- see _load_environment_context()'s
    # own docstring for why.
    w3 = ov.AIWorker("delete the build folder", parent=None, summarize_only=True)
    check("summarize_only is True for this worker",
          w3._summarize_only is True)
    w3._load_environment_context()
    check("environment context is NOT skipped for summarize_only calls "
          "(unlike memory context) -- it's a local, instant lookup, not "
          "a network one, so there's no latency reason to withhold it",
          "Nothing else is open" in w3._environment_context)


def part_c_thinking_skills():
    print("\n--- Part C: thinking_skills.md loading ---")
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skills_path = os.path.join(repo_root, "thinking_skills.md")

    check("thinking_skills.md actually exists in the project root",
          os.path.exists(skills_path))

    loaded = ov._load_thinking_skills(skills_path)
    check("_load_thinking_skills() returns non-empty content for the "
          "real file", bool(loaded.strip()))
    check("the loaded content is clearly separated from whatever it's "
          "appended to", loaded.startswith("\n\n---\n\n"))

    missing = ov._load_thinking_skills("/no/such/file/thinking_skills.md")
    check("a missing file returns '' rather than raising -- additive "
          "guidance only, never a hard dependency",
          missing == "")

    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False) as f:
        f.write("   \n\n   ")
        blank_path = f.name
    try:
        check("a present-but-blank file also returns '' rather than a "
              "near-empty separator block",
              ov._load_thinking_skills(blank_path) == "")
    finally:
        os.remove(blank_path)

    check("the real thinking_skills.md is actually folded into the "
          "module-level SYSTEM_PROMPT the app runs with",
          "Advanced Thinking Skills" in ov.SYSTEM_PROMPT)
    check("SYSTEM_PROMPT still includes personality.md's content too -- "
          "this is additive, not a replacement",
          "Memory and tasks" in ov.SYSTEM_PROMPT
          or "composed, dry-witted" in ov.SYSTEM_PROMPT)
    check("the thinking-skills content covers both easy and hard/"
          "high-stakes tasks, as asked for",
          "Easy / routine" in ov.SYSTEM_PROMPT
          and "Hard / high-stakes" in ov.SYSTEM_PROMPT)
    check("SYSTEM_PROMPT carries the explicit rule that an Acknowledge "
          "narration beat is never a complete reply on its own -- added "
          "after a real report of the IDE chat panel replying with "
          "'setting up the project now' / 'let's get started' across two "
          "separate turns without ever actually calling a single ide_* "
          "tool, once the chat panel's own freeze bug (a separate, "
          "already-fixed issue) stopped masking it",
          "never, by itself, a complete reply" in ov.SYSTEM_PROMPT)


def part_d_development_skill():
    print("\n--- Part D: development_skill.md loading ---")
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skill_path = os.path.join(repo_root, "development_skill.md")

    check("development_skill.md actually exists in the project root",
          os.path.exists(skill_path))

    loaded = ov._load_development_skill(skill_path)
    check("_load_development_skill() returns non-empty content for the "
          "real file", bool(loaded.strip()))
    check("the loaded content is clearly separated from whatever it's "
          "appended to", loaded.startswith("\n\n---\n\n"))

    missing = ov._load_development_skill("/no/such/file/development_skill.md")
    check("a missing file returns '' rather than raising -- additive "
          "guidance only, never a hard dependency", missing == "")

    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False) as f:
        f.write("   \n\n   ")
        blank_path = f.name
    try:
        check("a present-but-blank file also returns '' rather than a "
              "near-empty separator block",
              ov._load_development_skill(blank_path) == "")
    finally:
        os.remove(blank_path)

    check("the real development_skill.md is actually folded into the "
          "module-level SYSTEM_PROMPT the app runs with",
          "Professional Software Engineering Standard" in ov.SYSTEM_PROMPT)
    check("SYSTEM_PROMPT still includes personality.md's content too -- "
          "this is additive, not a replacement",
          "composed, dry-witted" in ov.SYSTEM_PROMPT)
    check("SYSTEM_PROMPT still includes thinking_skills.md's content too",
          "Advanced Thinking Skills" in ov.SYSTEM_PROMPT)
    check("the adapted skill content documents the Definition of Done "
          "(never claim an unrun test passed / something deployed that "
          "wasn't)", "Never claim a test passed without having actually "
          "run it" in ov.SYSTEM_PROMPT)
    check("the adapted skill content explicitly reconciles 'share a "
          "plan'/'get authorization' language with this project's own "
          "autonomy policy rather than contradicting it",
          "Reconciled with rules this project already has" in ov.SYSTEM_PROMPT)
    check("the adapted skill content explicitly calls out that routine, "
          "reversible-via-trash deletions don't need authorization here",
          "does not include ordinary file/folder" in ov.SYSTEM_PROMPT)
    check("personality.md documents the {{AWAIT_DECISION}} control tag "
          "that arms the 2-minute unanswered-pause autonomy rule",
          "{{AWAIT_DECISION}}" in ov.SYSTEM_PROMPT)
    check("personality.md's own wording states the 2-minute timeout is a "
          "real timeout, not a figure of speech",
          "real timeout, not a figure of speech" in ov.SYSTEM_PROMPT)


def part_e_frontend_skill():
    print("\n--- Part E: FRONTEND_SKILL.md / design-research on-demand tools ---")
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skill_path = os.path.join(repo_root, "FRONTEND_SKILL.md")
    research_path = os.path.join(repo_root, "UI_UX_FRONTEND_DESIGN_RESEARCH.md")

    check("FRONTEND_SKILL.md exists in the project root with the clean "
          "name (no uploaded-file suffix)", os.path.exists(skill_path))
    check("UI_UX_FRONTEND_DESIGN_RESEARCH.md exists in the project root "
          "with the clean name", os.path.exists(research_path))

    _reset_agent_tools_state()
    try:
        check("ide_get_frontend_skill() refuses while Agent Mode is off",
              "isn't open" in at.ide_get_frontend_skill())
        check("ide_get_frontend_design_research() refuses while Agent "
              "Mode is off",
              "isn't open" in at.ide_get_frontend_design_research())
        check("neither on-demand tool is in the active tool list while "
              "Agent Mode is off",
              "ide_get_frontend_skill" not in
              {f.__name__ for f in at.get_active_gemini_tools()})

        at._ide_app = object()  # anything truthy flips is_agent_mode_on()
        skill_text = at.ide_get_frontend_skill()
        research_text = at.ide_get_frontend_design_research()
        check("ide_get_frontend_skill() returns the real file's content "
              "once Agent Mode is on",
              "Professional Frontend Agent Operating Standard" in skill_text
              or len(skill_text) > 1000)
        check("ide_get_frontend_design_research() returns the real "
              "file's content once Agent Mode is on", len(research_text) > 1000)
        check("both tools are in the active tool list while Agent Mode "
              "is on",
              {"ide_get_frontend_skill", "ide_get_frontend_design_research"}
              <= {f.__name__ for f in at.get_active_gemini_tools()})
        check("both tools are scoped into the IDE embedded chat panel's "
              "own tool set too (they're genuinely IDE/coding work)",
              {"ide_get_frontend_skill", "ide_get_frontend_design_research"}
              <= {f.__name__ for f in at.get_ide_chat_gemini_tools()})

        missing_msg = at._read_own_skill_file("NO_SUCH_FILE.md", "test label")
        check("a missing skill file fails gracefully with a clear "
              "message instead of raising",
              "isn't present" in missing_msg)
    finally:
        _reset_agent_tools_state()

    check("FRONTEND_SKILL.md's own content is NOT folded into the "
          "always-on SYSTEM_PROMPT -- it's deliberately fetched on "
          "demand instead, to avoid a context-budget hit on every "
          "unrelated request",
          "Professional Frontend Agent Operating Standard" not in ov.SYSTEM_PROMPT)
    check("the new development_skill.md cross-reference to the frontend "
          "skill tool IS present in SYSTEM_PROMPT (that part is always "
          "loaded, same as the rest of development_skill.md)",
          "ide_get_frontend_skill()" in ov.SYSTEM_PROMPT)
    check("development_skill.md explicitly documents why these files "
          "aren't preloaded (the context-budget rationale)",
          "wouldn't waste context" in ov.SYSTEM_PROMPT
          or "waste context for no benefit" in ov.SYSTEM_PROMPT)


def main():
    part_a_snapshot()
    part_b_wiring()
    part_c_thinking_skills()
    part_d_development_skill()
    part_e_frontend_skill()

    passed = sum(1 for _, ok in CHECKS if ok)
    total = len(CHECKS)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
