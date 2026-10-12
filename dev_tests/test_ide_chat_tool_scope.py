"""Regression test for the standing scope restriction on the IDE's
embedded "Friday AI Chat" panel: a message typed there must only ever be
able to drive strictly-coding ide_* tools (write/edit/run code in the
open workspace) -- never open/close/minimize a panel, never any other
app/window-management command, and never anything else Friday's normal
floating circle can otherwise do (web search, memory, calendar, etc.).
That's the floating circle's domain, not this embedded panel's.

Covers all three layers the restriction is actually implemented at (see
agent_tools.get_ide_chat_gemini_tools/get_ide_chat_tool_schemas/call_tool
and agent_overlay.AIWorker.__init__'s docstring):
  1. The tool *lists* handed to each provider are trimmed down to just
     the ide_* tools when a call is ide_scoped.
  2. call_tool() itself refuses to actually run anything outside that
     set even if asked to (the defense-in-depth backstop for Groq/
     Mistral, where a model could in principle hallucinate a tool name
     it was never even offered).
  3. _ide_chat_ask() (the panel's one real entry point) always
     constructs its AIWorker with ide_scoped=True -- this is the one
     standing fact that makes 1 and 2 actually apply to the panel at
     all, so it's checked directly too, not just assumed.

Requires PySide6 with an offscreen-capable platform plugin:
    QT_QPA_PLATFORM=offscreen python3 dev_tests/test_ide_chat_tool_scope.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_tools

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


# The exact panel/window-management commands the user explicitly called
# out as off-limits from this chat box ("open a tab", "minimize ide",
# "any other panel related command") -- plus a few more tools that are
# just as clearly out of scope for a "strictly coding" surface even
# though they're not panel-management per se.
OUT_OF_SCOPE_EXAMPLES = [
    "open_app", "close_app", "minimize_app", "restore_app",
    "maximize_app", "list_open_apps", "agent_mode_off", "agent_mode_on",
    "web_search", "get_current_datetime",
]

# A handful of real ide_* tool names that must stay available -- actual
# coding work (write/edit/run code), exactly what this panel is for.
IN_SCOPE_EXAMPLES = [
    "ide_write_file", "ide_edit_file", "ide_read_file", "ide_run_file",
    "ide_run_project", "ide_git_commit", "ide_create_file",
]


def main():
    # -- 1. the ide_chat tool *names* set itself ------------------------
    for name in OUT_OF_SCOPE_EXAMPLES:
        check(f"'{name}' is excluded from the IDE chat panel's tool set",
              name not in agent_tools.IDE_CHAT_TOOL_NAMES)
    for name in IN_SCOPE_EXAMPLES:
        check(f"'{name}' is included in the IDE chat panel's tool set",
              name in agent_tools.IDE_CHAT_TOOL_NAMES)
    check("every name in the ide-chat set actually starts with 'ide_' "
          "(no accidental non-coding tool slipped in)",
          all(n.startswith("ide_") for n in agent_tools.IDE_CHAT_TOOL_NAMES))

    # -- 2. the trimmed lists actually handed to each provider ----------
    gemini_names = {f.__name__ for f in agent_tools.get_ide_chat_gemini_tools()}
    check("get_ide_chat_gemini_tools() returns a non-empty set "
          "(coding tools are still usable)", len(gemini_names) > 0)
    check("get_ide_chat_gemini_tools() excludes every out-of-scope example",
          gemini_names.isdisjoint(OUT_OF_SCOPE_EXAMPLES))
    check("get_ide_chat_gemini_tools() includes every in-scope example",
          set(IN_SCOPE_EXAMPLES) <= gemini_names)
    check("get_ide_chat_gemini_tools() is a strict subset of the full "
          "GEMINI_TOOLS list (nothing new invented)",
          gemini_names < {f.__name__ for f in agent_tools.GEMINI_TOOLS})

    schema_names = {s["function"]["name"] for s in agent_tools.get_ide_chat_tool_schemas()}
    check("get_ide_chat_tool_schemas() matches get_ide_chat_gemini_tools() "
          "exactly (Groq/Mistral and Gemini agree on the same scoped set)",
          schema_names == gemini_names)

    # -- 3. call_tool()'s own defense-in-depth backstop -----------------
    blocked = agent_tools.call_tool("minimize_app", {"name": "ide"}, ide_scoped=True)
    check("call_tool() refuses a panel-management tool when ide_scoped=True",
          blocked.lower().startswith("error"))
    check("the refusal message is informative, not a silent/blank failure",
          "ide" in blocked.lower() and "panel" in blocked.lower())

    blocked2 = agent_tools.call_tool("web_search", {"query": "x"}, ide_scoped=True)
    check("call_tool() refuses a non-coding tool (web_search) when ide_scoped=True",
          blocked2.lower().startswith("error"))

    # A real ide_* tool must still actually run (not be refused) when
    # ide_scoped=True -- prove the restriction is a precise allow-list,
    # not an overzealous blanket refusal of everything.
    ran = agent_tools.call_tool(
        "ide_exists", {"path": __file__}, ide_scoped=True)
    check("a genuine ide_* tool call still actually runs when ide_scoped=True "
          "(this isn't blocking coding tasks, just non-coding ones)",
          not ran.lower().startswith("error"))

    # ide_scoped=False (the circle's own normal path, and call_tool()'s
    # default) must be completely unaffected by any of this -- a
    # panel-management tool must still work normally there.
    unblocked = agent_tools.call_tool("ide_exists", {"path": __file__})
    check("call_tool()'s default (ide_scoped=False) is untouched by the "
          "IDE-chat restriction", not unblocked.lower().startswith("error"))

    # -- 4. the panel's one real entry point actually opts into this ----
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "agent_overlay.py"),
              encoding="utf-8") as f:
        overlay_src = f.read()
    m = re.search(r"worker\s*=\s*AIWorker\(text,\s*parent=None,\s*ide_scoped=True\)",
                   overlay_src)
    check("_ide_chat_ask() constructs its AIWorker with ide_scoped=True "
          "(the one fact that makes all of the above actually apply to "
          "the embedded chat panel)", m is not None)

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
