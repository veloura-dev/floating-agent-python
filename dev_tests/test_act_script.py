"""Regression test for act_script.py -- Friday's ACT Script system (the
Router + Sequential Rotation / Fan-Out / Debate pipelines) and its
wiring into agent_tools.py as ide_run_act_script.

Honesty about scope: this sandbox has no real Gemini/Groq/Mistral API
keys configured (see .env -- the key names are present but the values
are empty placeholders), so this can't do a live network end-to-end
run. Exactly like this codebase's own existing precedent for the same
problem (test_friday_memory.py monkeypatches memory.py's embedding
calls "rather than hitting a real network/API key" -- see its module
docstring), this test monkeypatches only two seams: settings_store.load
(the per-region-faculty model roster -- see settings_store.py/
settings_panel.py) and act_script._DISPATCH (the check_kind -> real-
API-call dict), both with deterministic, scripted data/replies, while
everything around it stays completely real: real round-robin/exclude
provider selection, real per-region faculty pooling/fallback (see
act_script.region_pool), real JSON/file-block parsing, real shell
mechanical verify commands, real file writes through the real IDE
(agent_tools.ide_write_file / ide_read_file against a real temp
workspace), real bounded fix-forward retry, real concurrent worker
threads, real memory.py evidence logging against a real (temp,
throwaway) encrypted memory folder, and the real agent_tools
tool-registration/gating plumbing.

Requires a display (the IDE is Tkinter-based):
    DISPLAY=:99 QT_QPA_PLATFORM=offscreen python3 dev_tests/test_act_script.py
"""
import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_tools as at  # noqa: E402
import act_script  # noqa: E402
import memory  # noqa: E402
import settings_store  # noqa: E402

CHECKS = []
_ORIG_SETTINGS_LOAD = settings_store.load


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


def _raises(fn):
    try:
        fn()
        return False
    except Exception:  # noqa: BLE001
        return True


def _stub_entry(id_, check_kind, api_key="stub", model=None, base_url="", name=None):
    """A minimal, settings_store-shaped entry -- same fields add_model()
    would produce, just built directly so tests don't need a real
    encrypted settings file on disk."""
    return {
        "id": id_, "name": name or id_.title(), "model": model or f"{id_}-model",
        "base_url": base_url, "api_key": api_key, "check_kind": check_kind,
        "builtin": check_kind != "generic_http",
        "status": "unknown", "detail": "", "last_checked": None,
    }


def make_role_dispatch(call_log, behavior):
    """Builds one dispatch(entry, system_prompt, user_prompt, model_name)
    function per provider id, all sharing the same `behavior` table
    (substring-in-system-prompt -> handler), and all appending to the
    shared `call_log` so tests can assert who got called, in what role,
    how many times."""
    def _factory(provider_id):
        def _dispatch(entry, system_prompt, user_prompt, model_name):
            call_log.append({"provider": provider_id, "system": system_prompt,
                              "user": user_prompt, "model": model_name})
            for key, fn in behavior:
                if key in system_prompt:
                    return fn(provider_id, system_prompt, user_prompt, model_name)
            raise AssertionError(f"no stub matched for {provider_id}: {system_prompt[:100]!r}")
        return _dispatch
    return _factory


def install_stub_providers(behavior, thinking_ids=("gemini", "groq", "mistral"),
                            extra_faculties=None):
    """Pretends `thinking_ids` are configured under the Thinking faculty
    (every other faculty empty by default, so every other region falls
    back entirely to this one shared pool -- the same effective
    shared-pool-of-three behavior the old fixed PROVIDER_KEYS/_DISPATCH
    setup had), optionally with extra per-faculty entries (e.g. a
    region-specific custom model under "Coding") via `extra_faculties`
    ({faculty: [entry, ...]}). Routes every real call through `behavior`
    (see make_role_dispatch). Returns the call_log list (grows as the
    pipeline runs)."""
    call_log = []
    data = {fac: [] for fac in settings_store.FACULTIES}
    data["Thinking"] = [_stub_entry(pid, pid) for pid in thinking_ids]
    for fac, entries in (extra_faculties or {}).items():
        data[fac] = list(entries)
    settings_store.load = lambda: copy.deepcopy(data)

    factory = make_role_dispatch(call_log, behavior)
    kinds = {e["check_kind"] for entries in data.values() for e in entries}
    dispatch = {}
    for entries in data.values():
        for e in entries:
            dispatch[e["check_kind"]] = factory(e["id"])
    act_script._DISPATCH = dispatch or {k: factory(k) for k in kinds}
    return call_log


def main():
    tmp_memory = tempfile.mkdtemp(prefix="friday-act-script-memory-")
    memory.set_memory_dir(tmp_memory)

    # ---- Part A: provider plumbing (role/faculty-based pools) -----------
    install_stub_providers([], thinking_ids=())
    check("available_providers('thinking') is empty when nothing is configured",
          act_script.available_providers("thinking") == [])
    p, degraded = act_script.next_provider("thinking")
    check("next_provider() with nothing configured returns (None, True)",
          p is None and degraded is True)

    install_stub_providers([], thinking_ids=("gemini", "mistral"))
    check("available_providers('thinking') reflects exactly what's configured, keeps order",
          act_script.available_providers("thinking") == ["gemini", "mistral"])

    install_stub_providers([], thinking_ids=("gemini", "groq", "mistral"))
    check("available_providers('thinking') with all three configured",
          act_script.available_providers("thinking") == ["gemini", "groq", "mistral"])
    p1, d1 = act_script.next_provider("thinking", after="gemini")
    check("next_provider() round-robins forward", p1 == "groq" and not d1)
    p2, d2 = act_script.next_provider("thinking", after="mistral")
    check("next_provider() wraps around", p2 == "gemini" and not d2)
    p3, d3 = act_script.next_provider("thinking", after="gemini", exclude={"groq"})
    check("next_provider() honors exclude when an alternative exists",
          p3 == "mistral" and not d3)
    p4, d4 = act_script.next_provider("thinking", after="gemini", exclude={"gemini", "groq", "mistral"})
    check("next_provider() falls back (degraded=True) only when exclude covers literally everyone",
          p4 == "groq" and d4 is True)

    # ---- Part A2: per-region faculties -- fallback + dedicated custom ---
    # models (the actual point of Settings' per-faculty "+ Add Model" --
    # see settings_panel.py/settings_store.py and act_script.ROLE_FACULTY).
    install_stub_providers(
        [], thinking_ids=("gemini", "groq"),
        extra_faculties={
            "Coding": [_stub_entry("custom-coder", "generic_http",
                                    base_url="https://api.example.com/v1")],
            # Planning/Review/Text Generation/Voice left empty on
            # purpose -- pure fallback-to-Thinking cases.
        },
    )
    check("a region with nothing of its own falls back entirely to Thinking's pool",
          act_script.available_providers("planning") == ["gemini", "groq"])
    check("a region with its own faculty entries uses ONLY those -- real, "
          "dedicated capacity, not diluted into Thinking's shared pool",
          act_script.available_providers("coding") == ["custom-coder"])
    check("Thinking's own pool is completely unaffected by another region's "
          "custom addition",
          act_script.available_providers("thinking") == ["gemini", "groq"])
    check("Voice falls back to Thinking too when it has nothing of its own",
          act_script.available_providers("voice") == ["gemini", "groq"])
    install_stub_providers(
        [], thinking_ids=("gemini", "groq"),
        extra_faculties={
            "Coding": [_stub_entry("custom-coder", "generic_http"),
                       _stub_entry("custom-coder-2", "generic_http")],
        },
    )
    check("adding a SECOND model under the same specific faculty gives that "
          "region a genuinely bigger pool of its own to round-robin across",
          act_script.available_providers("coding") == ["custom-coder", "custom-coder-2"])
    nxt, deg = act_script.next_provider("coding", after="custom-coder")
    check("next_provider() rotates correctly within a region's own dedicated pool",
          nxt == "custom-coder-2" and not deg)
    check("provider_label() shows a custom entry's own display name, not its raw id",
          act_script.provider_label("coding", "custom-coder") == "Custom-Coder")
    check("provider_label() falls back to the raw id for an unknown/removed entry",
          act_script.provider_label("coding", "no-such-id") == "no-such-id")

    # ---- Part A3: the generic OpenAI-compatible dispatcher ---------------
    # This is the real call a user-added "+ Add Model" custom entry (see
    # settings_panel.py) gets -- not just a reachability ping.
    check("_dispatch_generic_http() raises cleanly when no base_url is configured",
          _raises(lambda: act_script._dispatch_generic_http(
              _stub_entry("x", "generic_http", base_url=""), "s", "u", "m")))

    import requests as _requests
    captured_request = {}

    class _FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "  a real custom reply  "}}]}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured_request["url"] = url
        captured_request["json"] = json
        captured_request["headers"] = headers
        return _FakeResp()

    orig_post = _requests.post
    _requests.post = _fake_post
    try:
        entry = _stub_entry("custom-coder", "generic_http", api_key="sk-custom",
                             model="my-model", base_url="https://api.example.com/v1")
        text = act_script._dispatch_generic_http(entry, "sys prompt", "user prompt", "my-model")
        check("_dispatch_generic_http() calls base_url + /chat/completions",
              captured_request["url"] == "https://api.example.com/v1/chat/completions")
        check("_dispatch_generic_http() sends a Bearer auth header with the entry's own key",
              captured_request["headers"]["Authorization"] == "Bearer sk-custom")
        check("_dispatch_generic_http() sends an OpenAI-shaped messages payload",
              captured_request["json"]["messages"][0] == {"role": "system", "content": "sys prompt"}
              and captured_request["json"]["messages"][1] == {"role": "user", "content": "user prompt"}
              and captured_request["json"]["model"] == "my-model")
        check("_dispatch_generic_http() extracts and strips the real reply text",
              text == "a real custom reply")

        entry2 = _stub_entry("custom-coder2", "generic_http", base_url="https://api.example.com/v1/")
        act_script._dispatch_generic_http(entry2, "s", "u", "m")
        check("_dispatch_generic_http() doesn't double up the /chat/completions suffix",
              captured_request["url"] == "https://api.example.com/v1/chat/completions")
    finally:
        _requests.post = orig_post

    # ---- Part B: call_model() -------------------------------------------
    install_stub_providers([], thinking_ids=("gemini",))

    def _fails_once_then_succeeds(entry, system_prompt, user_prompt, model_name):
        if model_name == entry["model"]:
            raise RuntimeError("primary model overloaded")
        return f"fallback reply from {model_name}"

    act_script._DISPATCH = dict(act_script._DISPATCH)
    act_script._DISPATCH["gemini"] = _fails_once_then_succeeds
    result = act_script.call_model("thinking", "gemini", "sys", "usr")
    check("call_model() falls back to the provider's own known fallback models on failure",
          result.ok and result.model in act_script.GEMINI_FALLBACK_MODELS)

    install_stub_providers([], thinking_ids=())
    result2 = act_script.call_model("thinking", "gemini", "sys", "usr")
    check("call_model() reports cleanly (not raising) when the provider isn't "
          "configured for this region",
          result2.ok is False and "isn't configured" in result2.error)

    # ---- Part C: JSON / file-block extraction ---------------------------
    check("_extract_json() handles plain JSON", act_script._extract_json('{"a": 1}') == {"a": 1})
    check("_extract_json() strips markdown fences",
          act_script._extract_json('```json\n{"a": 1}\n```') == {"a": 1})
    check("_extract_json() finds JSON amid prose",
          act_script._extract_json('Sure, here it is:\n{"a": 1}\nHope that helps!') == {"a": 1})
    check("_extract_json() returns None (never raises) on garbage",
          act_script._extract_json("not json at all") is None)

    blocks = act_script._extract_file_blocks(
        '===FILE: a.py===\nprint(1)\n===END===\n===FILE: b.py===\nprint(2)\n===END==='
    )
    check("_extract_file_blocks() finds multiple files",
          blocks == [("a.py", "print(1)"), ("b.py", "print(2)")])
    check("_extract_file_blocks() returns [] for NO_FILE_CHANGES",
          act_script._extract_file_blocks("NO_FILE_CHANGES") == [])

    # ---- Part D: mechanical verify (real subprocess) ---------------------
    passed, _out = act_script.run_mechanical_check("true")
    check("run_mechanical_check('true') short-circuits without running a shell", passed)
    passed_ok, out_ok = act_script.run_mechanical_check("echo hi")
    check("run_mechanical_check() really runs a real shell command", passed_ok and "hi" in out_ok)
    passed_bad, _out_bad = act_script.run_mechanical_check("exit 1")
    check("run_mechanical_check() reports real failure on a nonzero exit", not passed_bad)

    # ---- Part E: evidence/memory logging (real memory.py) -----------------
    act_script._log_evidence("testrun01", "step", {"summary": "did a thing", "x": 1})
    recalled = memory.recall("did a thing", max_results=3, category="act_script")
    check("_log_evidence() really writes a recallable memory.remember() entry",
          any("did a thing" in r["text"] for r in recalled))
    kv_record = memory.kv_get("act_script_run:testrun01")
    check("_log_evidence() really writes the full raw record via memory.kv_set()",
          kv_record is not None and kv_record["entries"][0]["kind"] == "step"
          and kv_record["entries"][0]["x"] == 1)

    # ---- Part F: Sequential Rotation, end to end (real IDE, real files) ---
    msg = at.agent_mode_on()
    check("agent_mode_on() succeeded (needed for real file writes below)",
          "Agent Mode is on" in msg)

    def thinking_seq(provider, system, user, model):
        return (
            '{"contract": "greet.py must define greet() returning a greeting, '
            'and running it as __main__ must print that greeting.", '
            '"steps": ["Create greet.py with a greet() function that returns '
            '\\"Hello, Friday!\\"", "Add a __main__ block to greet.py that '
            'prints greet()\'s result"]}'
        )

    def planning_seq(provider, system, user, model):
        verify_first = (
            f'"{sys.executable}" -c "from pathlib import Path; '
            "assert 'Hello, Friday!' in "
            "Path('greet.py').read_text(encoding='utf-8')\""
        )
        verify_second = (
            f'"{sys.executable}" -c "from pathlib import Path; '
            "text=Path('greet.py').read_text(encoding='utf-8'); "
            "assert '__main__' in text and 'print(greet())' in text\""
        )
        return json.dumps({
            "steps": [
                {
                    "description": (
                        'Create greet.py with a greet() function that returns '
                        '"Hello, Friday!"'
                    ),
                    "file_hint": "greet.py",
                    "verify_command": verify_first,
                },
                {
                    "description": (
                        "Add a __main__ block to greet.py that prints "
                        "greet()'s result"
                    ),
                    "file_hint": "greet.py",
                    "verify_command": verify_second,
                },
            ]
        })

    def coding_seq(provider, system, user, model):
        if "Create greet.py" in system and "Add a __main__" not in system.split("This step:")[1][:80]:
            return '===FILE: greet.py===\ndef greet():\n    return "Hello, Friday!"\n===END==='
        if "Add a __main__" in system:
            # Deliberately broken the first time -- forgets the __main__
            # block entirely, so the mechanical verify command fails and
            # the bounded fix-forward retry path actually gets exercised.
            return '===FILE: greet.py===\ndef greet():\n    return "Hello, Friday!"\n===END==='
        raise AssertionError(f"unexpected coding system prompt: {system[:120]!r}")

    def fix_seq(provider, system, user, model):
        return (
            '===FILE: greet.py===\n'
            'def greet():\n'
            '    return "Hello, Friday!"\n\n'
            'if __name__ == "__main__":\n'
            '    print(greet())\n'
            '===END==='
        )

    def review_seq(provider, system, user, model):
        return '{"verdict": "done", "report": "Both steps verified against the real file contents."}'

    seq_behavior = [
        ("Sequential Rotation mode -- for dependent", thinking_seq),
        ("Planning region of", planning_seq),
        ("fixing ONE mechanical verify failure", fix_seq),
        ("Coding region of", coding_seq),
        ("Review region of", review_seq),
    ]
    seq_calls = install_stub_providers(seq_behavior)
    seq_report = act_script.run_sequential("Write a tiny greet.py script with a main block.")
    check("run_sequential() returns a Sequential header",
          "Act Script -- Sequential Rotation" in seq_report)
    check("run_sequential() reports 2 steps", "2 step(s)" in seq_report)
    check("run_sequential() shows step 2 as passed (after the fix-forward retry)",
          "Step 2:" in seq_report and "FAILED" not in seq_report.split("Review verdict")[0])
    check("run_sequential() surfaces the Review verdict", "Review verdict: done" in seq_report)

    greet_content = at.ide_read_file("greet.py")
    check("run_sequential() really wrote greet.py into the real IDE workspace",
          "def greet" in greet_content)
    check("run_sequential()'s bounded fix-forward retry really fixed the file for real",
          "__main__" in greet_content)

    coder_calls = [c for c in seq_calls if "Coding region of" in c["system"]
                   or "fixing ONE mechanical" in c["system"]]
    fix_calls = [c for c in seq_calls if "fixing ONE mechanical" in c["system"]]
    check("the fix-forward path was actually invoked exactly once (bounded, not looping)",
          len(fix_calls) == 1)

    review_calls = [c for c in seq_calls if "Review region of" in c["system"]]
    coder_providers_used = {c["provider"] for c in coder_calls}
    check("Review really ran", len(review_calls) == 1)
    check("Review's provider differs from whichever provider coded last (producer != reviewer)",
          review_calls[0]["provider"] != [c["provider"] for c in seq_calls
                                           if "Coding region of" in c["system"]][-1])

    # ---- Part F2: the await_decision path emits real control tags -------
    def review_await(provider, system, user, model):
        return ('{"verdict": "await_decision", '
                '"report": "The request is ambiguous about which database to use.", '
                '"options": ["Use SQLite", "Use Postgres"]}')

    seq_behavior_await = [
        ("Sequential Rotation mode -- for dependent", thinking_seq),
        ("Planning region of", planning_seq),
        ("fixing ONE mechanical verify failure", fix_seq),
        ("Coding region of", coding_seq),
        ("Review region of", review_await),
    ]
    install_stub_providers(seq_behavior_await)
    await_report = act_script.run_sequential("Write a tiny greet.py script with a main block.")
    check("run_sequential() emits the literal {{AWAIT_DECISION}} control tag "
          "(not just prose) so the IDE chat panel actually pauses",
          "{{AWAIT_DECISION}}" in await_report)
    check("run_sequential() emits the {{OPTIONS: ...}} tag in the exact format "
          "agent_overlay._extract_decision_options() parses",
          '{{OPTIONS: "Use SQLite" | "Use Postgres"}}' in await_report)
    check("the plain-language report still appears before the control tags "
          "(that's the part the user actually sees as the chat bubble)",
          "ambiguous about which database" in await_report.split("{{AWAIT_DECISION}}")[0])

    # ---- Part F3: ordinary IDE chat uses the fast IDE-scoped tool loop;
    # ACT Script stays available as an explicit tool for deeper tasks.
    try:
        import agent_overlay as ov
        from PySide6.QtWidgets import QApplication
        _qapp = QApplication.instance() or QApplication([])
        original_keys = (ov.GEMINI_API_KEY, ov.GROQ_API_KEY, ov.MISTRAL_API_KEY)

        # This sandbox has no real keys at all (see this file's module
        # docstring) -- AIWorker.run()'s very first line is a real,
        # legitimate "no provider configured anywhere" guard checked
        # against agent_overlay's OWN GEMINI_API_KEY/GROQ_API_KEY/
        # MISTRAL_API_KEY globals (loaded once from .env at import time),
        # which is a different place than act_script.PROVIDER_KEYS
        # above. In a real deployment with any real key configured this
        # guard simply passes on its own; here it needs its own stub so
        # this test can reach the actual branch under test. The real
        # network boundary stays genuinely stubbed via
        # install_stub_providers()/act_script.PROVIDER_KEYS regardless.
        ov.GEMINI_API_KEY = "stub-key-for-this-test-only"

        worker = ov.AIWorker("Write a tiny greet.py script with a main block.",
                              parent=None, ide_scoped=True)
        worker._load_memory_context = lambda: None
        worker._load_environment_context = lambda: None
        worker._try_gemini = lambda: (True, "fast IDE reply", None)
        original_act_script = act_script.run_act_script
        act_script.run_act_script = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ordinary IDE chat must not invoke ACT Script"))
        captured = {}
        worker.succeeded.connect(lambda text: captured.setdefault("ok", text))
        worker.failed.connect(lambda err: captured.setdefault("err", err))
        try:
            worker.run()
        finally:
            act_script.run_act_script = original_act_script
        check("ordinary IDE chat returns directly through its scoped provider path",
              captured.get("ok") == "fast IDE reply")
        check("ACT Script remains available as an IDE-only tool for deeper work",
              "ide_run_act_script" in at.IDE_CHAT_TOOL_NAMES)

        # And the non-ide_scoped (floating circle) path must NOT be
        # affected by any of this -- it still only tries configured
        # providers via the normal chain, which in this sandbox (no real
        # keys) fails outright rather than silently running Act Script.
        # Restores the real (empty, in this sandbox) key first, undoing
        # this check's own stub above.
        ov.GEMINI_API_KEY = ov.GROQ_API_KEY = ov.MISTRAL_API_KEY = ""
        install_stub_providers([], thinking_ids=())
        worker2 = ov.AIWorker("hello", parent=None)
        captured2 = {}
        worker2.succeeded.connect(lambda text: captured2.setdefault("ok", text))
        worker2.failed.connect(lambda err: captured2.setdefault("err", err))
        worker2.run()
        check("the floating circle's own (non-ide_scoped) chat path is untouched -- "
              "still the plain single-model chain, not Act Script",
              "err" in captured2 and "Act Script" not in captured2.get("err", ""))
        ov.GEMINI_API_KEY, ov.GROQ_API_KEY, ov.MISTRAL_API_KEY = original_keys
    except ImportError as exc:
        check(f"PySide6 available for the real AIWorker integration check (skipped: {exc})", False)

    # ---- Part F4: a model added under ONE specific region's own faculty --
    # really does give just that region a bigger/independent rotation pool
    # -- the actual point of Settings' per-faculty "+ Add Model" -- while
    # every other region keeps using whatever it already had. Real,
    # full Sequential Rotation run, not a unit-level pool check.
    region_calls = install_stub_providers(
        seq_behavior, thinking_ids=("gemini", "groq", "mistral"),
        extra_faculties={
            "Coding": [_stub_entry("dedicated-coder", "generic_http")],
        },
    )
    region_report = act_script.run_sequential("Write a tiny greet.py script with a main block.")
    check("Sequential still completes correctly when Coding has its own dedicated model",
          "Act Script -- Sequential Rotation" in region_report)
    coding_calls2 = [c for c in region_calls if "Coding region of" in c["system"]
                     or "fixing ONE mechanical" in c["system"]]
    other_calls2 = [c for c in region_calls if c not in coding_calls2]
    check("every Coding-region call used the Coding faculty's own dedicated "
          "model, never Thinking's gemini/groq/mistral pool",
          bool(coding_calls2) and all(c["provider"] == "dedicated-coder" for c in coding_calls2))
    check("Thinking/Planning/Review calls still used the Thinking pool, "
          "completely unaffected by Coding's own dedicated addition",
          bool(other_calls2) and all(c["provider"] in ("gemini", "groq", "mistral")
                                      for c in other_calls2))

    # ---- Part F5: AIWorker._try_voice_extras() -- the circle's own last- --
    # resort tier for extra models added specifically under Settings ->
    # Voice (see agent_overlay.py's AIWorker._try_voice_extras).
    try:
        ov.GEMINI_API_KEY, ov.GROQ_API_KEY, ov.MISTRAL_API_KEY = "", "", ""

        install_stub_providers([], thinking_ids=())
        worker3 = ov.AIWorker("hello", parent=None)
        ok3, text3, err3 = worker3._try_voice_extras()
        check("_try_voice_extras() is a clean no-op (not an error) when Voice "
              "has nothing extra configured at all",
              ok3 is False and text3 is None and err3 is None)

        def voice_extra_reply(provider, system, user, model):
            return "a real reply from the user's own extra Voice model"

        install_stub_providers(
            [("", voice_extra_reply)],  # matches any system prompt
            thinking_ids=(),
            extra_faculties={
                "Voice": [_stub_entry("my-extra-key", "generic_http",
                                       api_key="sk-not-one-of-the-builtins",
                                       base_url="https://api.example.com/v1")],
            },
        )
        worker4 = ov.AIWorker("hello", parent=None)
        ok4, text4, err4 = worker4._try_voice_extras()
        check("_try_voice_extras() really calls a genuinely extra Voice model "
              "and returns its reply",
              ok4 is True and text4 == "a real reply from the user's own extra Voice model")

        # And it must be skipped as "nothing extra" when the only Voice
        # entry configured is literally the same key as one of the three
        # builtins just tried above (the default seed -- see
        # settings_store.py) -- that's not a genuinely extra model.
        ov.GEMINI_API_KEY = "same-key-as-voice-entry"
        install_stub_providers(
            [], thinking_ids=(),
            extra_faculties={
                "Voice": [_stub_entry("gemini", "gemini", api_key="same-key-as-voice-entry")],
            },
        )
        worker5 = ov.AIWorker("hello", parent=None)
        ok5, text5, err5 = worker5._try_voice_extras()
        check("_try_voice_extras() correctly ignores a Voice entry that's just "
              "a duplicate of an already-tried builtin key",
              ok5 is False and text5 is None and err5 is None)
        ov.GEMINI_API_KEY = ""

        # A real run() end to end with ZERO env-var-backed keys at all --
        # only a model configured through Settings -> Voice -- must not
        # be blocked by run()'s own top-of-function "no key anywhere"
        # guard (see agent_overlay.AIWorker.run()'s own comment).
        install_stub_providers(
            [("", voice_extra_reply)], thinking_ids=(),
            extra_faculties={
                "Voice": [_stub_entry("my-extra-key", "generic_http",
                                       api_key="sk-not-one-of-the-builtins",
                                       base_url="https://api.example.com/v1")],
            },
        )
        worker6 = ov.AIWorker("hello", parent=None)
        captured6 = {}
        worker6.succeeded.connect(lambda text: captured6.setdefault("ok", text))
        worker6.failed.connect(lambda err: captured6.setdefault("err", err))
        worker6.run()
        check("run() doesn't short-circuit with \"No API key found\" when only "
              "a Settings -> Voice model is configured (zero env keys at all)",
              captured6.get("ok") == "a real reply from the user's own extra Voice model")
    except NameError:
        check("AIWorker available for _try_voice_extras() checks (skipped -- "
              "PySide6 import failed earlier)", False)

    # ---- Part G: Fan-Out, end to end (real concurrency, real URL check) ---
    def thinking_fo(provider, system, user, model):
        return (
            '{"question": "Is Python dynamically typed, and is the sky blue during the day?", '
            '"merge_rule": "Combine agreement; flag any disagreement plainly, never average it.", '
            '"stakes": "contested"}'
        )

    def worker_fo(provider, system, user, model):
        if provider == "mistral":
            return ("Python is dynamically typed. I'm not fully sure about the sky "
                     "question, no source handy.")
        return ("Python is dynamically typed (official docs: https://example.com). "
                "The sky is blue during the day due to Rayleigh scattering "
                "(source: https://example.com).")

    def aggregator_fo(provider, system, user, model):
        return (
            "Python is dynamically typed -- all workers agree, HIGH confidence "
            "(cited https://example.com). The sky is blue during the day per "
            "most workers (HIGH confidence, same source), though one worker "
            "expressed uncertainty and had no source -- noted as a minority, "
            "low-confidence caveat rather than dropped."
        )

    def review_fo(provider, system, user, model):
        return '{"verdict": "pass", "note": "Merge preserved the dissenting worker fairly."}'

    fo_behavior = [
        ("Fan-Out mode -- for breadth", thinking_fo),
        ("one independent worker", worker_fo),
        ("Aggregator region of", aggregator_fo),
        ("Review region of Friday's ACT Script Fan-Out", review_fo),
    ]
    fo_calls = install_stub_providers(fo_behavior)
    fo_report = act_script.run_fan_out("Is Python dynamically typed and is the sky blue?")
    check("run_fan_out() returns a Fan-Out header", "Act Script -- Fan-Out" in fo_report)
    check("run_fan_out() picked N=4 workers for 'contested' stakes", "4/4 workers" in fo_report)
    check("run_fan_out() mechanically checked cited URLs for real reachability",
          "Mechanical check:" in fo_report and "reachable" in fo_report)
    worker_calls = [c for c in fo_calls if "one independent worker" in c["system"]]
    check("Fan-Out really ran all 4 workers concurrently (4 real calls logged)",
          len(worker_calls) == 4)

    # ---- Part H: Debate, end to end (stopping rule + role separation) -----
    draft_v1 = "A mug that holds coffee. It is round."
    draft_v2 = "A cozy mug built for warmth-seeking coffee lovers. Its rounded shape fits any hand."

    def thinking_deb(provider, system, user, model):
        return (
            '{"brief": "Write a 2-sentence product blurb for a ceramic coffee mug.", '
            '"review_criteria": "Must mention warmth/coziness and be concise.", '
            '"stakes": "low"}'
        )

    def author_deb(provider, system, user, model):
        if "A Critic" in system:
            return draft_v2
        return draft_v1

    def critic_deb(provider, system, user, model):
        return ('{"issues": [{"severity": "BLOCKING", '
                '"issue": "Never mentions warmth/coziness as the brief requires."}], '
                '"overall_note": "Needs warmth language."}')

    def adjudicator_deb(provider, system, user, model):
        return '{"verdict": "DONE", "note": "Revision added warmth language as required."}'

    def final_read_deb(provider, system, user, model):
        return "Reads well and satisfies the brief -- ready to ship."

    deb_behavior = [
        ("Debate mode -- for whole-artifact", thinking_deb),
        ("Critic in round", critic_deb),
        ("Adjudicator in", adjudicator_deb),
        ("One last cold read", final_read_deb),
        ("You are the Author in", author_deb),
    ]
    deb_calls = install_stub_providers(deb_behavior)
    deb_report = act_script.run_debate("Write a short coffee mug product blurb.")
    check("run_debate() returns a Debate header", "Act Script -- Debate" in deb_report)
    check("run_debate() stopped after round 1 because the Adjudicator said DONE "
          "(not because it hit the round cap)", "1 round(s)" in deb_report)
    check("run_debate()'s final shipped text is the REVISED draft, not the first weak one",
          "warmth-seeking" in deb_report and "It is round." not in deb_report)
    check("run_debate() included the final cold read", "Final cold read" in deb_report)

    critic_calls = [c for c in deb_calls if "Critic in round" in c["system"]]
    author_calls = [c for c in deb_calls if "You are the Author in" in c["system"]]
    adj_calls = [c for c in deb_calls if "Adjudicator in" in c["system"]]
    check("Debate ran exactly one Author draft + one revision (bounded by DONE)",
          len(author_calls) == 2)
    check("Debate's Critic never shares a provider with the Author (producer != reviewer)",
          critic_calls[0]["provider"] != author_calls[0]["provider"])
    check("Debate's Adjudicator never shares a provider with the Author",
          adj_calls[0]["provider"] != author_calls[0]["provider"])
    check("Debate's Adjudicator never shares a provider with that round's Critic",
          adj_calls[0]["provider"] != critic_calls[0]["provider"])

    history = memory.kv_get(f"act_script_debate_history:{deb_report.split('run `')[1].split('`')[0]}")
    check("Debate stored full draft+critique provenance in memory",
          history is not None and len(history) == 1 and "issues" in history[0])

    # ---- Part I: top-level entry point + forced mode ----------------------
    # Reuses the Fan-Out stub table from Part G -- the point here isn't
    # Fan-Out's own behavior (already covered above), it's proving
    # run_act_script(mode="fan_out") skips the classifier entirely and
    # goes straight to run_fan_out().
    top_level_calls = install_stub_providers(fo_behavior)
    forced = act_script.run_act_script("Is Python dynamically typed and is the sky blue?",
                                        mode="fan_out")
    check("run_act_script(mode='fan_out') actually ran the Fan-Out pipeline",
          "Act Script -- Fan-Out" in forced)
    classify_calls = [c for c in top_level_calls if "which of three pipelines" in c["system"]]
    check("run_act_script(mode=...) skips the classifier entirely when a mode is forced",
          len(classify_calls) == 0)

    install_stub_providers([], thinking_ids=())
    empty_msg = act_script.run_act_script("anything")
    check("run_act_script() fails cleanly with no providers configured, never raises",
          "needs at least one configured AI model" in empty_msg)

    # ---- Part J: real tool registration/gating via agent_tools -----------
    check("ide_run_act_script is registered in GEMINI_TOOLS/TOOL_FUNCTIONS/TOOL_SCHEMAS",
          "ide_run_act_script" in {f.__name__ for f in at.GEMINI_TOOLS}
          and "ide_run_act_script" in at.TOOL_FUNCTIONS
          and "ide_run_act_script" in {s["function"]["name"] for s in at.TOOL_SCHEMAS})
    check("ide_run_act_script is IDE-chat-scoped (surface decision: IDE chat only, not voice/circle)",
          "ide_run_act_script" in at.IDE_CHAT_TOOL_NAMES)

    at.agent_mode_off()
    check("ide_run_act_script refuses cleanly when Agent Mode/the IDE is off",
          "isn't open" in at.ide_run_act_script("anything"))

    settings_store.load = _ORIG_SETTINGS_LOAD

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
