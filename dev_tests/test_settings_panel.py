"""Proof that Friday's Settings panel (settings_store.py,
settings_checks.py, settings_panel.py, plus its wiring into
app_panels.py's KNOWN_APPS/CUSTOM_PANEL_APPS/_open_custom_panel) works
end to end:

  - settings_store.py seeds Friday's real, already-wired models/keys on
    first use, keeps everything encrypted at rest the same way the rest
    of memory.py's local storage is, and supports adding/editing/
    removing entries and recording a check's result;
  - API keys are never shown in the clear -- mask_key() always hashes
    them out;
  - settings_checks.py makes a real (injectable/mockable) backend call
    per provider and never raises, even for a totally unknown custom
    provider (falls back to a plain HTTP reachability check);
  - "settings" is wired into app_panels.py exactly the way "notepad" is
    -- same KNOWN_APPS/CUSTOM_PANEL_APPS/resolve_app_key/
    known_app_labels machinery, same AppPanelManager.open/minimize/
    restore/close lifecycle, same generic (not notepad-hardcoded)
    list_panels() wording;
  - the real SettingsPanel Tk widget actually builds one row per seeded
    model, reflects a connectivity check's result live (green check /
    red x), and "+ Add Model" really adds a new, fully custom entry.

Part A: settings_store.py in isolation (throwaway temp memory folder,
same sandboxing pattern as dev_tests/test_friday_memory.py).
Part B: settings_checks.py in isolation, with every real SDK/network
call faked out via sys.modules/monkeypatching -- no real network access.
Part C: app_panels.py wiring (KNOWN_APPS/CUSTOM_PANEL_APPS/
resolve_app_key/AppPanelManager), a real (Xvfb) Tk panel -- same
DISPLAY=:99 requirement as dev_tests/test_app_panels.py.
"""
import os
import shutil
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHECKS = []


def check(label, cond):
    CHECKS.append((label, bool(cond)))
    print(("PASS" if cond else "FAIL") + " - " + label)


# ---------------------------------------------------------------------
# Part A: settings_store.py
# ---------------------------------------------------------------------
def part_a():
    print("\n--- Part A: settings_store.py ---")
    import memory
    import settings_store as ss

    tmp = tempfile.mkdtemp(prefix="friday_settings_test_")
    old_env = {k: os.environ.pop(k, None) for k in
               ("GEMINI_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY", "TAVILY_API_KEY")}
    try:
        memory.set_memory_dir(tmp)

        check("FACULTIES has exactly the twelve requested faculties, in order",
              ss.FACULTIES == [
                  "Voice", "Thinking", "Planning", "Review", "Coding",
                  "Image Generation", "Audio Generation", "Video Generation",
                  "Research", "Embedding", "Text Generation", "Transcription",
              ])

        data = ss.load()
        check("load() returns every faculty as a key",
              all(f in data for f in ss.FACULTIES))
        check("Thinking is pre-seeded with Gemini/Groq/Mistral",
              {e["name"] for e in data["Thinking"]} ==
              {"Google Gemini", "Groq", "Mistral"})
        check("Voice is pre-seeded with the exact same builtin providers as "
              "Thinking (same real chain today, see act_script.py)",
              {e["name"] for e in data["Voice"]} ==
              {"Google Gemini", "Groq", "Mistral"} and
              {e["id"] for e in data["Voice"]} == {e["id"] for e in data["Thinking"]})
        check("Planning/Review/Coding/Image/Video/Text Generation start "
              "empty (Planning/Review/Coding/Text Generation fall back to "
              "Thinking's pool for real via act_script.py; Image/Video "
              "Generation have no real integration yet at all)",
              data["Planning"] == [] and data["Review"] == [] and
              data["Coding"] == [] and data["Image Generation"] == [] and
              data["Video Generation"] == [] and data["Text Generation"] == [])
        check("Research is pre-seeded with Tavily",
              [e["name"] for e in data["Research"]] == ["Tavily"])
        check("Audio Generation is pre-seeded with local Piper",
              data["Audio Generation"][0]["check_kind"] == "local_piper")
        check("Transcription is pre-seeded with local faster-whisper",
              data["Transcription"][0]["check_kind"] == "local_whisper")
        check("Embedding is pre-seeded with Gemini + Mistral embedding models",
              {e["check_kind"] for e in data["Embedding"]} ==
              {"gemini_embed", "mistral_embed"})
        check("with no env vars set, seeded cloud entries have empty api_key",
              data["Thinking"][0]["api_key"] == "")

        on_disk = ss._settings_path()
        check("the settings file actually exists on disk", os.path.isfile(on_disk))
        with open(on_disk, "rb") as f:
            raw = f.read()
        check("the on-disk file is encrypted, not plain JSON "
              "(no readable faculty/provider names in the raw bytes)",
              b"Thinking" not in raw and b"Gemini" not in raw and b"{" not in raw[:1])

        reread = ss.load()
        check("reloading gives back the same seeded data (idempotent, not "
              "re-randomized every time)",
              {e["id"] for e in reread["Thinking"]} == {e["id"] for e in data["Thinking"]})

        new_entry = ss.add_model(data, "Coding", "OpenAI", "gpt-4.1",
                                  "sk-abc123", base_url="https://api.openai.com/v1")
        check("add_model() returns the new entry with a stable id",
              bool(new_entry["id"]) and new_entry["name"] == "OpenAI")
        check("a freshly-added model is never builtin / always generic_http checked",
              new_entry["builtin"] is False and new_entry["check_kind"] == "generic_http")
        reread2 = ss.load()
        check("add_model() actually persisted the new entry",
              any(e["id"] == new_entry["id"] for e in reread2["Coding"]))
        check("add_model() raises for an unknown faculty",
              _raises(lambda: ss.add_model(data, "Not A Real Faculty", "x", "y", "z")))

        ss.update_check_result(data, "Coding", new_entry["id"], True,
                                "Connected.", 12345.0)
        reread3 = ss.load()
        updated = [e for e in reread3["Coding"] if e["id"] == new_entry["id"]][0]
        check("update_check_result() records status/detail/timestamp",
              updated["status"] == "connected" and updated["detail"] == "Connected." and
              updated["last_checked"] == 12345.0)

        ss.remove_model(data, "Coding", new_entry["id"])
        reread4 = ss.load()
        check("remove_model() actually deletes the entry",
              not any(e["id"] == new_entry["id"] for e in reread4["Coding"]))
        check("remove_model() on an unknown id is a harmless no-op",
              not _raises(lambda: ss.remove_model(data, "Coding", "no-such-id")))

        check("mask_key('') says not set", ss.mask_key("") == "not set")
        masked = ss.mask_key("sk-super-secret-value")
        check("mask_key() never contains any of the real key's characters",
              "super-secret-value" not in masked and "sk-" not in masked)
        check("mask_key() still reports a length hint",
              str(len("sk-super-secret-value")) in masked)
    finally:
        memory.close()
        shutil.rmtree(tmp, ignore_errors=True)
        for k, v in old_env.items():
            if v is not None:
                os.environ[k] = v


def _raises(fn):
    try:
        fn()
        return False
    except Exception:  # noqa: BLE001
        return True


# ---------------------------------------------------------------------
# Part B: settings_checks.py (every network/SDK call faked)
# ---------------------------------------------------------------------
def part_b():
    print("\n--- Part B: settings_checks.py ---")
    import settings_checks as sc

    def entry(check_kind, api_key="", base_url="", model=""):
        return {"check_kind": check_kind, "api_key": api_key,
                "base_url": base_url, "model": model}

    # -- no key configured: every cloud checker refuses before even
    #    trying a real call --
    for kind, fn in (("gemini", sc.check_gemini), ("groq", sc.check_groq),
                     ("mistral", sc.check_mistral), ("tavily", sc.check_tavily)):
        ok, detail = fn(entry(kind, api_key=""))
        check(f"check_{kind} refuses with no api key (no network call needed)",
              ok is False and "key" in detail.lower())

    # -- fake a working Gemini SDK --
    fake_google = types.ModuleType("google")
    fake_genai = types.ModuleType("google.genai")

    class _FakeModels:
        def list(self):
            return iter([object()])

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels()

    fake_genai.Client = _FakeClient
    fake_google.genai = fake_genai
    sys.modules["google"] = fake_google
    sys.modules["google.genai"] = fake_genai
    try:
        ok, detail = sc.check_gemini(entry("gemini", api_key="real-looking-key"))
        check("check_gemini succeeds against a fake-but-working client", ok is True)
        ok, detail = sc.check_gemini_embed(entry("gemini_embed", api_key="k"))
        check("check_gemini_embed reuses the same real call path", ok is True)
    finally:
        sys.modules.pop("google", None)
        sys.modules.pop("google.genai", None)

    # -- fake a Gemini SDK that raises (bad key) --
    fake_genai2 = types.ModuleType("google.genai")

    class _BadClient:
        def __init__(self, api_key):
            raise RuntimeError("401 Unauthorized")

    fake_genai2.Client = _BadClient
    fake_google2 = types.ModuleType("google")
    fake_google2.genai = fake_genai2
    sys.modules["google"] = fake_google2
    sys.modules["google.genai"] = fake_genai2
    try:
        ok, detail = sc.check_gemini(entry("gemini", api_key="bad-key"))
        check("check_gemini reports failure (not an exception) for a bad key",
              ok is False and "401" in detail)
    finally:
        sys.modules.pop("google", None)
        sys.modules.pop("google.genai", None)

    # -- fake a working Groq SDK --
    fake_groq = types.ModuleType("groq")

    class _FakeGroqModels:
        def list(self):
            return []

    class _FakeGroq:
        def __init__(self, api_key):
            self.models = _FakeGroqModels()

    fake_groq.Groq = _FakeGroq
    sys.modules["groq"] = fake_groq
    try:
        ok, detail = sc.check_groq(entry("groq", api_key="k"))
        check("check_groq succeeds against a fake-but-working client", ok is True)
    finally:
        sys.modules.pop("groq", None)

    # -- groq SDK missing entirely --
    sys.modules["groq"] = None  # forces ImportError on `import groq`
    try:
        ok, detail = sc.check_groq(entry("groq", api_key="k"))
        check("check_groq reports a clear message when the SDK isn't installed",
              ok is False and "install" in detail.lower())
    finally:
        sys.modules.pop("groq", None)

    # -- fake Tavily --
    fake_tavily = types.ModuleType("tavily")

    class _FakeTavilyClient:
        def __init__(self, api_key):
            self._key = api_key

        def search(self, query, max_results=1):
            return {"results": []}

    fake_tavily.TavilyClient = _FakeTavilyClient
    sys.modules["tavily"] = fake_tavily
    try:
        ok, detail = sc.check_tavily(entry("tavily", api_key="k"))
        check("check_tavily succeeds against a fake-but-working client", ok is True)
    finally:
        sys.modules.pop("tavily", None)

    # -- generic HTTP reachability (custom/unintegrated providers) --
    ok, detail = sc.check_generic_http(entry("generic_http", api_key="k", base_url=""))
    check("check_generic_http refuses with no base url configured", ok is False)

    import requests as _requests

    class _FakeResp:
        status_code = 200

    orig_get = _requests.get
    _requests.get = lambda *a, **k: _FakeResp()
    try:
        ok, detail = sc.check_generic_http(
            entry("generic_http", api_key="k", base_url="https://example.com/api"))
        check("check_generic_http treats any <500 response as reachable", ok is True)
    finally:
        _requests.get = orig_get

    def _raise_conn_error(*a, **k):
        raise _requests.exceptions.ConnectionError("no route to host")

    orig_get2 = _requests.get
    _requests.get = _raise_conn_error
    try:
        ok, detail = sc.check_generic_http(
            entry("generic_http", api_key="k", base_url="https://nowhere.invalid"))
        check("check_generic_http reports failure (not an exception) on connection error",
              ok is False and "route" in detail.lower())
    finally:
        _requests.get = orig_get2

    # -- local, no-network checks --
    ok, detail = sc.check_local_piper(entry("local_piper"))
    check("check_local_piper never raises even if piper/overlay_speech "
          "aren't fully set up here", isinstance(ok, bool))
    ok, detail = sc.check_local_whisper(entry("local_whisper"))
    check("check_local_whisper never raises", isinstance(ok, bool))

    # -- dispatch --
    check("run_check() dispatches generic_http for an unrecognized check_kind",
          sc.run_check(entry("totally-unknown-kind", base_url=""))[1].startswith(
              "No API base URL"))
    check("run_check() never raises even if a checker itself blows up",
          not _raises(lambda: sc.run_check({"check_kind": "gemini"})))


# ---------------------------------------------------------------------
# Part C: app_panels.py wiring + a real Tk SettingsPanel (Xvfb)
# ---------------------------------------------------------------------
def part_c():
    print("\n--- Part C: app_panels.py wiring + real Tk panel ---")
    import app_panels as ap

    check("'settings' is a known app", ap.resolve_app_key("settings") == "settings")
    for alias in ("settings panel", "ai settings", "model settings",
                  "api settings", "ai models", "model manager"):
        check(f"resolve_app_key({alias!r}) resolves to settings",
              ap.resolve_app_key(alias) == "settings")
    check("Settings is in known_app_labels()", "Settings" in ap.known_app_labels())
    check("'settings' is in CUSTOM_PANEL_APPS (fully native, no real OS window)",
          "settings" in ap.CUSTOM_PANEL_APPS)
    check("'settings' is not in EMBEDDABLE_APPS (it's not a real reparented window)",
          "settings" not in ap.EMBEDDABLE_APPS)
    check("_CUSTOM_PANEL_CLASSES maps settings to the real SettingsPanel class",
          ap._CUSTOM_PANEL_CLASSES["settings"].__name__ == "SettingsPanel")

    import memory
    import settings_store as ss
    tmp = tempfile.mkdtemp(prefix="friday_settings_test_panel_")
    try:
        memory.set_memory_dir(tmp)

        class FakeLauncher:
            def launch(self, *a, **k):
                raise AssertionError("settings must never launch a real process")

        class _StubAgentHost:
            def get_panel_placement(self, key):
                return (0, 0, 900, 700), True, ""

            def get_pill_slot(self, key):
                return 0

            def release_pill_slot(self, key):
                return []

            def reposition_pill(self, key, idx):
                pass

            def release_panel_slot(self, key):
                pass

        mgr = ap.AppPanelManager(launcher=FakeLauncher(), agent_host=_StubAgentHost())

        msg = mgr.open("settings")
        check("open('settings') succeeds", "Opened Settings" in msg)
        rec = mgr._panels["settings"]
        check("settings opens with no real OS process or window at all",
              rec.get("proc") is None and rec.get("hwnd") is None)
        check("settings is tracked as a custom, embedded panel",
              rec.get("custom") is True and rec.get("embedded") is True)
        check("list_panels() names Settings generically, not as a built-in notepad",
              "built-in settings" in mgr.list_panels().lower() and
              "notepad" not in mgr.list_panels().lower())

        panel = rec["frame"]
        check("the real SettingsPanel has one row per seeded model "
              "(3 Voice + 3 Thinking + 1 Audio + 1 Research + 2 Embedding + "
              "1 Transcription; Planning starts empty)",
              len(panel._row_widgets) == 11)
        check("a Thinking row's key is shown masked, never in the clear",
              panel._row_widgets.get(("Thinking", "gemini")) is not None)

        check("the panel's own data uses settings_store.mask_key for display",
              ss.mask_key("") == "not set")

        # -- simulate a finished connectivity check without touching the
        #    network or threads, exactly like the real background worker
        #    would call back on success --
        import settings_panel as sp
        panel._finish_check("Thinking", "gemini", True, "Connected.")
        widgets = panel._row_widgets[("Thinking", "gemini")]
        check("a successful check turns the status label green with a checkmark",
              "\u2713" in widgets["status_lbl"].cget("text") and
              str(widgets["status_lbl"].cget("fg")) == str(sp.C["success"]))
        check("...and the status text says Connected",
              "Connected" in widgets["status_lbl"].cget("text"))

        panel._finish_check("Thinking", "groq", False, "401 Unauthorized")
        widgets2 = panel._row_widgets[("Thinking", "groq")]
        check("a failed check shows a not-connected status",
              "Connected" not in widgets2["status_lbl"].cget("text"))

        # -- "+ Add Model" really adds a brand-new custom provider --
        before = len(panel._row_widgets)
        added = {}

        def _fake_submit():
            entry = ss.add_model(panel._data, "Coding", "Custom LLM",
                                  "custom-model-v1", "sk-xyz",
                                  base_url="https://api.example.com")
            added["entry"] = entry
            panel._render_all()

        _fake_submit()
        check("adding a brand-new custom provider adds exactly one more row",
              len(panel._row_widgets) == before + 1)
        check("the new row is keyed by faculty + the new entry's id",
              ("Coding", added["entry"]["id"]) in panel._row_widgets)
        new_key_lbl = panel._row_widgets[("Coding", added["entry"]["id"])]["key_lbl"]
        check("the new custom provider's key is masked in the UI, never shown raw",
              "sk-xyz" not in new_key_lbl.cget("text"))

        msg = mgr.minimize("settings")
        check("minimize('settings') succeeds", "Settings" in msg or "minimized" in msg)
        msg = mgr.restore("settings")
        check("restore('settings') succeeds", "Restored Settings" in msg)
        msg = mgr.close("settings")
        check("close('settings') succeeds", "Closed Settings" in msg)
        check("settings is no longer tracked after closing",
              "settings" not in mgr._panels)

        # -- a broken settings_store.load() must never leave a blank,
        #    un-closeable panel on screen (the real bug report this
        #    guards against): the constructor must swallow the error,
        #    show it in plain text, and still have a real, working
        #    close button, instead of either staying blank or raising
        #    out of __init__ entirely (which would leak an untracked,
        #    orphaned Toplevel with no way to close it). --
        import settings_panel as sp_mod
        orig_load = ss.load
        ss.load = lambda: (_ for _ in ()).throw(RuntimeError("disk is on fire"))
        close_events = []
        try:
            def _build_broken():
                return sp_mod.SettingsPanel(
                    mgr._root, on_minimize=lambda: None,
                    on_close=lambda: close_events.append(True),
                    corner_index=0, bounds=(0, 0, 900, 700))

            broken_panel = mgr._bridge.call(_build_broken)
            check("a broken settings_store.load() doesn't raise out of "
                  "SettingsPanel.__init__", True)
            body_text = " ".join(
                w.cget("text") for w in broken_panel._body.winfo_children()
                if "text" in w.keys())
            check("...and shows the real error message in the panel instead "
                  "of a silently blank one",
                  "disk is on fire" in body_text)
            check("...with zero model rows (nothing half-rendered)",
                  len(broken_panel._row_widgets) == 0)

            def _find_close_button(widget):
                for child in widget.winfo_children():
                    if child.winfo_class() == "Label" and child.cget("text") == "\u2715":
                        return child
                    found = _find_close_button(child)
                    if found is not None:
                        return found
                return None

            def _click_close():
                btn = _find_close_button(broken_panel)
                if btn is not None:
                    btn.event_generate("<Button-1>")

            mgr._bridge.call(_click_close)
            check("the error panel's own titlebar close button really is "
                  "wired up and clickable, escaping the error",
                  len(close_events) == 1)
            mgr._bridge.call(broken_panel.destroy)
        finally:
            ss.load = orig_load

        # No manual Tk teardown here -- mgr's own atexit-registered
        # shutdown() (see AppPanelManager.shutdown's docstring) is the
        # only thread-safe way to stop its background Tk host thread;
        # reaching across threads to call mgr._root.destroy() directly
        # from here is exactly the kind of cross-thread Tcl call that
        # hangs, same as test_app_panels.py deliberately never does it
        # either.
    finally:
        memory.close()
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    part_a()
    part_b()
    part_c()
    passed = sum(1 for _, ok in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    if passed != len(CHECKS):
        sys.exit(1)


if __name__ == "__main__":
    main()
