"""The OpenAI-style JSON tool schemas Groq and Mistral need (Gemini
introspects the plain Python functions in agent_tools.py directly, via
automatic function calling, and never touches this file at all).

Split out of agent_tools.py purely to keep that file a manageable size:
this is pure declarative data (name/description/parameters dicts, one
per tool, matched up with the real function by *name* in
agent_tools.TOOL_FUNCTIONS, not by direct reference) with zero logic and
zero dependency on anything else in the project -- about a third of
agent_tools.py's own line count before this split. Every entry's
"name" must exactly match both an agent_tools.py function's real name
and its key in TOOL_FUNCTIONS -- agent_tools.py's own tests
(dev_tests/test_friday_memory.py and others) verify that stays true.

agent_tools.py imports this list as `TOOL_SCHEMAS`, unchanged from
before this split -- nothing importing agent_tools.TOOL_SCHEMAS needed
to change.
"""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information and return results "
                "with source links. Use for anything time-sensitive, "
                "recent, or possibly outside your training data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": (
                "Open a real browser and navigate to a URL (launches on "
                "first use; reuses the same browser/page on later calls). "
                "Use for research/form-filling that needs a real rendered "
                "page, not just web_search's text snippets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The address to go to."}
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click the first element matching a CSS or text selector on the current page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector (e.g. '#submit') or Playwright text selector (e.g. 'text=Sign in').",
                    }
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": "Fill a form field (input/textarea) with text, replacing whatever was already in it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector for the field."},
                    "text": {"type": "string", "description": "The text to put in the field."},
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_select_option",
            "description": "Choose an option in a <select> dropdown, by value or visible label.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector for the <select> element."},
                    "value": {"type": "string", "description": "The option's value or visible label text."},
                },
                "required": ["selector", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_press_key",
            "description": "Focus an element and press a keyboard key on it, e.g. 'Enter' to submit a search box after browser_fill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the element to focus first."},
                    "key": {"type": "string", "description": "Key name, e.g. 'Enter', 'Tab', 'Escape'."},
                },
                "required": ["selector", "key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait_for",
            "description": "Wait for an element to appear/become visible -- useful on JS-heavy pages that render content after the initial load.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector to wait for."},
                    "timeout_ms": {"type": "integer", "description": "How long to wait, in milliseconds (default 5000)."},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_read_text",
            "description": "Read the visible, rendered text of the current page (or one element) -- the actual text a human would see, not raw HTML.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector to read just one element; leave empty for the whole page."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_html",
            "description": "Get the raw HTML of the current page (or one element) -- use over browser_read_text when you need actual markup (ids, classes, structure).",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector for one element's outerHTML; leave empty for the whole page."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_links",
            "description": "List every link on the current page (href + visible text) -- useful for research/crawling.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_evaluate",
            "description": "Run JavaScript in the current page and return its result -- for anything the other browser_* tools don't cover directly (computed styles, element state, custom DOM queries).",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "A JS expression or function body to evaluate."}
                },
                "required": ["script"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_console_logs",
            "description": "Return the browser's own console output (console.log/warn/error and uncaught JS exceptions) captured since the last browser_navigate call -- the mechanical way to check for real console errors.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "Save a screenshot of the current page (into the open IDE workspace if one is open, otherwise a fallback folder). Returns the saved file's path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Optional file name; a timestamped default is used if omitted."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_go_back",
            "description": "Go back to the previous page in the browser's history.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_current_state",
            "description": "Report whether a browser session is open right now, and if so what page it's on -- check before assuming browser_click/browser_fill/etc. have anything to act on.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_close",
            "description": "Close the browser session and free its resources. The next browser_navigate call starts a fresh one.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_datetime",
            "description": "Get the current local date, time, and day of the week.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read and return the text content of a file on disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative filesystem path to the file to read.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file or overwrite an existing one with the given text content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative filesystem path to write to.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full text content to write to the file.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit an existing file by replacing the first occurrence of some exact text with new text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative filesystem path to the file to edit.",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "The exact text to search for (first occurrence is replaced).",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "The text to replace it with.",
                    },
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the files and subfolders inside a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative filesystem path to the directory to list. Defaults to the current directory.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_calendar_events",
            "description": "List upcoming events from the user's Google Calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of events to return (default 10).",
                    },
                    "days_ahead": {
                        "type": "integer",
                        "description": "Only include events starting within this many days from now (default 30).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Create a new event on the user's Google Calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Short title of the event."},
                    "start_iso": {
                        "type": "string",
                        "description": "Start date/time in ISO 8601 format, e.g. 2026-10-01T15:00:00.",
                    },
                    "end_iso": {
                        "type": "string",
                        "description": "End date/time in ISO 8601 format, e.g. 2026-10-01T16:00:00.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional longer description of the event.",
                    },
                    "timezone_name": {
                        "type": "string",
                        "description": "Optional IANA timezone name, e.g. Africa/Lagos. Defaults to UTC if omitted.",
                    },
                },
                "required": ["summary", "start_iso", "end_iso"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Save something worth remembering long-term about the "
                "user -- a fact, a stated preference, a one-off note -- "
                "so it can be recalled automatically in later "
                "conversations, even ones that never explicitly ask to "
                "look it up."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "The thing to remember, written as a clear, "
                            "self-contained statement."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "description": "A short label, e.g. 'fact' or 'preference'. Defaults to 'fact'.",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": (
                "Search Friday's long-term memory for anything relevant "
                "to a query, by meaning rather than exact wording."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search memory for."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": (
                "Delete a saved memory, by its exact number or by "
                "searching its text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "which": {
                        "type": "string",
                        "description": "A memory id, or text to search for among saved memories.",
                    }
                },
                "required": ["which"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add a task/reminder for the user to Friday's task list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What the task is."},
                    "due": {
                        "type": "string",
                        "description": "Optional due date/time, in whatever form the user gave it.",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List the user's tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "'pending' (default), 'done', or 'all'.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": (
                "Mark a task done, by its exact number or by searching "
                "its text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "which": {
                        "type": "string",
                        "description": "A task id, or text to search for among pending tasks.",
                    }
                },
                "required": ["which"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": (
                "Delete a task outright (as opposed to marking it done), "
                "by its exact number or by searching its text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "which": {
                        "type": "string",
                        "description": "A task id, or text to search for among all tasks.",
                    }
                },
                "required": ["which"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agent_mode_on",
            "description": (
                "Turn on Agent Mode: opens the bundled IDE so code can be "
                "written live. Call this when the user asks to start "
                "coding, build a project, or says something like 'turn on "
                "agent mode' / 'open the IDE'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Optional name or path of an existing folder to open right away instead of starting empty.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": (
                "Opens a real native desktop application -- Chrome, "
                "Notepad, Calculator, Settings, Chat, Profile, Image "
                "Generation, or Video Generation so far -- as one of "
                "Friday's own tracked panels, the same way opening the IDE "
                "already is: Friday launches it, remembers it as his, and "
                "it can later be minimized into a small pill under his "
                "floating circle. This really launches the real "
                "application (or, for the fully built-in panels, Friday's "
                "own real panel); it does not simulate it inside the IDE. "
                "Settings lists every AI model/API key Friday knows about "
                "by faculty, with masked keys and a live connectivity "
                "check -- open it for anything about managing Friday's AI "
                "providers or API keys, e.g. 'open settings', 'show me the "
                "AI model settings', 'check my API keys'. Chat/Profile/"
                "Image Generation/Video Generation are each an empty "
                "panel with an attach/text/mic/speaker input bar at the "
                "bottom -- UI shells only, not yet wired to a real chat, "
                "profile, image, or video backend."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Which app to open -- 'chrome', 'notepad', "
                            "'calculator', 'settings', 'chat', 'profile', "
                            "'image_gen', or 'video_gen'."
                        ),
                    },
                    "url": {
                        "type": "string",
                        "description": "Chrome only -- a URL to open (a new tab if Chrome is already open).",
                    },
                    "content": {
                        "type": "string",
                        "description": "Notepad only -- text to pre-fill a brand new Notepad window with.",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_open_apps",
            "description": (
                "Lists every top-level panel Friday currently has open -- "
                "the IDE (if open) plus any native apps he's launched on "
                "command -- and whether each is minimized. Call this "
                "before acting on an ambiguous 'minimize that'/'close that' "
                "so you check what's actually open instead of guessing."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "minimize_app",
            "description": (
                "Minimizes one of Friday's open top-level panels (the IDE "
                "or a native app he opened) into a small pill under his "
                "floating circle, while the real window quietly minimizes "
                "to the taskbar. Pass 'all' to minimize everything open. "
                "If the name is ambiguous or matches nothing, this says so "
                "instead of guessing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "which": {
                        "type": "string",
                        "description": "Which panel to minimize, or 'all'.",
                    }
                },
                "required": ["which"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restore_app",
            "description": (
                "Restores one of Friday's minimized top-level panels back "
                "to its normal small/default size (not maximized). Pass "
                "'all' to restore everything minimized."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "which": {
                        "type": "string",
                        "description": "Which panel to restore, or 'all'.",
                    }
                },
                "required": ["which"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "maximize_app",
            "description": (
                "Maximizes one of Friday's open panels so it fills exactly "
                "the IDE's own window size/position (the IDE's current "
                "size is the reference every panel maximizes to fit). Only "
                "one panel can be maximized/active at a time -- maximizing "
                "one shrinks whichever other panel was previously "
                "maximized back to its normal size and brings the new one "
                "to the front. Pass 'ide' to make the IDE the active panel "
                "again. Needs the IDE open (there's nothing to size-match "
                "otherwise)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "which": {
                        "type": "string",
                        "description": "Which panel to maximize, or 'ide'.",
                    }
                },
                "required": ["which"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_app",
            "description": (
                "Closes one of Friday's open top-level panels (the IDE or "
                "a native app he opened). Pass 'all' to close everything "
                "open. Ambiguous or no-match names are refused with an "
                "explanation instead of guessing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "which": {
                        "type": "string",
                        "description": "Which panel to close, or 'all'.",
                    }
                },
                "required": ["which"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_in_app",
            "description": (
                "Types text into the active tab of an already-open "
                "Notepad panel at the current cursor position -- direct "
                "and fully reliable, since Notepad is Friday's own "
                "built-in editor widget now."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "which": {
                        "type": "string",
                        "description": "Which open panel to type into.",
                    },
                    "text": {
                        "type": "string",
                        "description": "The text to type.",
                    },
                },
                "required": ["which", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_app_file",
            "description": (
                "Saves an open Notepad panel's real, current content to "
                "a real file on the user's PC. Call this whenever the "
                "user asks to save/export what's in Notepad."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "which": {
                        "type": "string",
                        "description": "Which open panel to save (currently only 'notepad').",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Where to save it, e.g. 'notes.txt' or "
                            "'Desktop/notes.txt' (resolved against the "
                            "user's home directory if relative). Leave "
                            "blank to reuse the tab's existing save path, "
                            "or let Friday pick a sensible default."
                        ),
                    },
                },
                "required": ["which"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agent_mode_off",
            "description": "Turn off Agent Mode: closes the IDE. Call this when the user says something like 'close agent mode' / 'close the IDE'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_open_folder",
            "description": "Open an existing folder in the IDE (turns Agent Mode on first if it isn't already).",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Name or path of the folder to open, e.g. 'my-project' or a full path.",
                    }
                },
                "required": ["folder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_create_file",
            "description": "Create a new file inside the IDE's open workspace, visible live in its Explorer (Agent Mode must be on). Refuses to overwrite an existing file -- use ide_write_file for that.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the folder currently open in the IDE.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Text content for the new file.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_write_file",
            "description": "Create or overwrite a file inside the IDE's open workspace, visible live in its editor (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the folder currently open in the IDE.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full text content to write.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_edit_file",
            "description": "Edit a file already inside the IDE's open workspace by replacing the first occurrence of some exact text (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the folder currently open in the IDE.",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "The exact text to search for (first occurrence is replaced).",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "The text to replace it with.",
                    },
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_create_folder",
            "description": "Create a new folder inside the IDE's open workspace, visible live in its Explorer (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the folder currently open in the IDE, e.g. 'src/utils'.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_read_file",
            "description": "Read a file's content from inside the IDE's open workspace (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the folder currently open in the IDE.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_list_folder",
            "description": "List files and subfolders inside a folder in the IDE's open workspace (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the folder currently open in the IDE. Defaults to the workspace root.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_workspace_tree",
            "description": "List every file in the IDE's currently open workspace, as workspace-relative paths (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_exists",
            "description": "Check whether a file or folder exists inside the IDE's open workspace (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the folder currently open in the IDE.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_rename",
            "description": "Rename a file or folder inside the IDE's open workspace, visible live in its Explorer (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path, relative to the open folder, of the file/folder to rename.",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "The new name.",
                    },
                },
                "required": ["path", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_copy",
            "description": "Copy a file or folder inside the IDE's open workspace, visible live in its Explorer (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path, relative to the open folder, of the file/folder to copy.",
                    },
                    "destination_folder": {
                        "type": "string",
                        "description": "Folder (relative to the open folder) to copy it into.",
                    },
                },
                "required": ["path", "destination_folder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_move",
            "description": "Move a file or folder inside the IDE's open workspace, visible live in its Explorer (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path, relative to the open folder, of the file/folder to move.",
                    },
                    "destination_folder": {
                        "type": "string",
                        "description": "Folder (relative to the open folder) to move it into.",
                    },
                },
                "required": ["path", "destination_folder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_search_workspace",
            "description": "Search for a plain-text string across every file in the IDE's open workspace (or a subfolder of it), same as the IDE's own Search sidebar (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The text to search for (case-insensitive, no regex).",
                    },
                    "scope": {
                        "type": "string",
                        "description": "Folder to search within, relative to the open workspace. Defaults to the whole workspace.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_analyze_file_for_deletion",
            "description": (
                "Read a file and check the rest of the IDE's open workspace for anything "
                "that still references it — required before Friday may delete it (Agent "
                "Mode must be on). Always call this before ide_delete_file. If it comes "
                "back clean (no references, clearly dead/leftover content), proceed with "
                "ide_delete_file and narrate what was removed — no need to wait for a "
                "reply for routine cleanup. If references are found or it's ambiguous, "
                "stop and get the user's explicit go-ahead first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path, relative to the open workspace folder, of the file to consider deleting.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_delete_file",
            "description": (
                "Delete a single file from the IDE's open workspace — only after "
                "ide_analyze_file_for_deletion was just called for this exact, unchanged "
                "file (Agent Mode must be on). Moves the file to a recoverable trash "
                "folder, never a permanent delete. For routine cleanup of dead/leftover "
                "files with no outside references, go ahead without asking first; stop "
                "and ask if the analysis found references or ambiguity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path, relative to the open workspace folder, of the file to delete. Must be a single file, never a folder (use ide_delete_folder for that).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_analyze_folder_for_deletion",
            "description": (
                "Inventory a folder and check the rest of the IDE's open workspace for "
                "anything that still references files inside it — required before Friday "
                "may delete it (Agent Mode must be on). Always call this before "
                "ide_delete_folder. Refuses on the workspace root and on project "
                "infrastructure folders (.git, node_modules, a venv, build/cache output) "
                "regardless of what the reference search finds. If it comes back clean, "
                "proceed with ide_delete_folder and narrate what was removed — no need to "
                "wait for a reply for routine cleanup. If references are found or it's "
                "ambiguous, stop and get the user's explicit go-ahead first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path, relative to the open workspace folder, of the folder to consider deleting.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_delete_folder",
            "description": (
                "Delete a whole folder from the IDE's open workspace — only after "
                "ide_analyze_folder_for_deletion was just called for this exact, "
                "unchanged folder (Agent Mode must be on). Moves the entire folder to a "
                "recoverable trash folder, never a permanent delete. For routine cleanup "
                "of dead/leftover folders with no outside references, go ahead without "
                "asking first; stop and ask if the analysis found references or "
                "ambiguity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path, relative to the open workspace folder, of the folder to delete. Must be a folder, never a single file (use ide_delete_file for that).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_run_file",
            "description": "Run the file open in the IDE's active editor tab, same as pressing F5 in the IDE (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_run_project",
            "description": "Start the IDE's detected project run/dev-server task, same as Ctrl+F5 in the IDE (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_build_project",
            "description": "Run the IDE's detected project build task (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_stop_task",
            "description": "Stop whatever build/run task is currently running in the IDE (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_get_terminal_output",
            "description": "Read everything currently shown in the IDE's integrated terminal panel (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_run_terminal_command",
            "description": "Run a shell command in the IDE's own integrated terminal, visibly, and wait for it to finish (Agent Mode must be on). Use this for installs, test runs, git commands, or anything else you'd normally type into a terminal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run, e.g. 'python -m pip install requests'.",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "How long to wait before returning partial output. Defaults to 60 seconds.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_clone_repository",
            "description": "Clone a Git repository and open it as the IDE's workspace (Agent Mode must be on). Runs git clone visibly in the integrated terminal, waits for it to finish, then opens the cloned folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The repository's clone URL, e.g. 'https://github.com/someuser/somerepo.git'.",
                    },
                    "destination_folder": {
                        "type": "string",
                        "description": "Optional existing folder to clone into (the repo gets its own new folder inside it). Defaults to the user's home folder.",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_set_theme",
            "description": "Switch the IDE's whole color theme (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": ["grey", "black", "white"],
                             "description": "The theme to switch to."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_toggle_view",
            "description": "Show/hide a part of the IDE's layout, same as the View menu or the sidebar/panel toggle icons (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "panel": {"type": "string", "enum": ["sidebar", "terminal", "minimap"],
                              "description": "Which part of the layout to toggle."},
                },
                "required": ["panel"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_show_sidebar",
            "description": (
                "Switch which view the IDE's side bar is showing, same as clicking an Activity Bar "
                "icon (Agent Mode must be on). Unlike ide_toggle_view this always makes the side bar "
                "visible and showing that view, never hides it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "view": {"type": "string", "enum": ["explorer", "search", "git", "run", "extensions"],
                             "description": (
                                 "\"explorer\" (file tree), \"search\" (search-in-files), \"git\" "
                                 "(Source Control -- read-only status list + Initialize Repository), "
                                 "\"run\" (Run and Debug -- just a Run File shortcut, no real debugger), "
                                 "or \"extensions\" (a static, non-functional example list)."
                             )},
                },
                "required": ["view"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_open_in_browser",
            "description": "Open the current HTML file, or the IDE's currently running dev server, in the system's default web browser, same as Run > Open in Browser (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_clear_terminal",
            "description": "Clear the IDE's terminal/output panel, same as Terminal > Clear Terminal (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_list_tasks",
            "description": (
                "List every run/build/test task auto-detected for the open workspace (npm scripts, "
                "pytest, cargo, make targets, Docker, and more depending on the folder), the same "
                "list Run > Tasks... shows (Agent Mode must be on). Use ide_run_task with one of "
                "these exact labels to run a specific one."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_run_task",
            "description": (
                "Run one specific auto-detected task by name (an npm script, a Makefile target, "
                "pytest, cargo build, ...), streaming its output into the IDE's terminal panel "
                "(Agent Mode must be on). Call ide_list_tasks first to see the exact labels -- "
                "ide_run_file/ide_run_project/ide_build_project only cover the single most obvious "
                "run/build task, not every task a project can have."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string",
                              "description": "The task's exact label from ide_list_tasks, or a distinctive fragment of it."},
                },
                "required": ["label"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_zoom",
            "description": "Change the editor's font size, same as Ctrl+=/Ctrl+-/Ctrl+0 (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["in", "out", "reset"],
                               "description": "Zoom in, zoom out, or reset to default."},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_set_opacity",
            "description": "Make the IDE window more see-through or more solid, same as Ctrl+Shift+-/Ctrl+Shift+= (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["more_transparent", "more_opaque"],
                               "description": "Which direction to adjust opacity."},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_toggle_always_on_top",
            "description": "Toggle whether the IDE window stays above every other window (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_toggle_maximize",
            "description": "Maximize the IDE window, or restore it if already maximized (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_undo",
            "description": "Undo the last edit in the IDE's active editor tab, same as Ctrl+Z (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_redo",
            "description": "Redo the last undone edit in the IDE's active editor tab, same as Ctrl+Y (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_editor_action",
            "description": "Perform a basic editing action in the IDE's active editor tab, same as the Edit/Selection menu (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string",
                               "enum": ["cut", "copy", "paste", "select_all",
                                        "duplicate_line", "move_line_up",
                                        "move_line_down"],
                               "description": "Which editing action to perform."},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_goto_line",
            "description": "Move the cursor to a specific line number in the IDE's active editor tab, same as Ctrl+G (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer", "description": "The 1-based line number to jump to."},
                },
                "required": ["line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_find_replace",
            "description": "Find (and optionally replace) text in the IDE's active editor tab, same as Ctrl+F / Ctrl+H (Agent Mode must be on). Works on the live, possibly-unsaved buffer — use ide_edit_file instead for edits that should also be saved straight to disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "find_text": {"type": "string", "description": "The text to search for in the currently open file."},
                    "replace_text": {"type": "string", "description": "If given, replaces matches with this text."},
                    "replace_all": {"type": "boolean", "description": "If true (and replace_text was given), replace every match."},
                },
                "required": ["find_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_open_file",
            "description": (
                "Open (or bring to the front, if already open) a file as a real, visible tab in "
                "the IDE's editor, same as double-clicking it in the Explorer (Agent Mode must be "
                "on). Use this whenever a human would expect to actually see the file appear on "
                "screen -- ide_read_file only returns text into the conversation and never touches "
                "the UI. Handles text files, images, and PDFs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path, relative to the open workspace (or absolute), of the file to open."},
                    "line": {"type": "integer", "description": "If given (and the file is text), jump to this 1-based line number once open."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_switch_tab",
            "description": (
                "Switch focus to an already-open tab without closing anything else (Agent Mode "
                "must be on). Call ide_list_open_tabs first if unsure what's open."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "which": {"type": "string",
                              "description": "The name/path of the open tab, or its 1-based position among currently open tabs."},
                },
                "required": ["which"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_get_active_tab_content",
            "description": (
                "Read the currently active editor tab's content exactly as it looks on screen "
                "right now, including any unsaved edits the human has typed but not saved yet "
                "(Agent Mode must be on). Use instead of ide_read_file to see live, unsaved changes."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_save_file",
            "description": (
                "Save the currently active editor tab to disk, same as Ctrl+S -- captures the "
                "human's live, unsaved typing exactly as it appears on screen (Agent Mode must be "
                "on). Use ide_write_file instead if you already know the exact content you want on "
                "disk and there's no in-progress human edit to preserve."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_save_all",
            "description": "Save every open tab that has unsaved changes and a known file path, same as File > Save All (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_list_open_tabs",
            "description": (
                "List every tab currently open in the IDE's editor, with its name, path, "
                "unsaved-changes status, and which one is active (Agent Mode must be on). "
                "Call this before closing/acting on \"a tab\"/\"the file\" whenever the user "
                "didn't say which one and more than one is open."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_get_frontend_skill",
            "description": (
                "Load Friday's full professional frontend operating standard "
                "(FRONTEND_SKILL.md) -- UX strategy, information architecture, "
                "visual direction, responsive/accessible implementation, "
                "component states, performance, and validation -- for "
                "websites, web apps, PWAs, and mobile UI. Call this once near "
                "the start of any real frontend build or meaningful "
                "frontend change, before writing code. Not preloaded into "
                "standing instructions since it's large and only sometimes "
                "relevant -- fetch it yourself when a task actually calls "
                "for it."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_get_frontend_design_research",
            "description": (
                "Load the companion research document behind the frontend "
                "skill (UI_UX_FRONTEND_DESIGN_RESEARCH.md) -- the evidence "
                "and citations (W3C/MDN/web.dev/NN-G and similar) the "
                "frontend skill's rules are distilled from. Call this when "
                "you need to justify a specific design decision with real "
                "evidence, not as a routine first step."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_get_backend_skill",
            "description": (
                "Load Friday's professional backend operating standard "
                "(BACKEND_SKILL.md) -- API design, data flow, auth, error "
                "handling, validation -- the backend sibling of "
                "ide_get_frontend_skill. Call this once near the start of "
                "any real backend build or meaningful backend change, "
                "before writing code. May not exist in this install yet "
                "(returns a plain message saying so, not an error) if the "
                "user hasn't supplied it -- proceed with "
                "development_skill.md's general standard until it is."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_get_storage_skill",
            "description": (
                "Load Friday's professional storage/database operating "
                "standard (STORAGE_SKILL.md) -- schema design, migrations, "
                "query/indexing discipline, data integrity, validation -- "
                "the storage/database sibling of ide_get_frontend_skill. "
                "Call this once near the start of any real storage/database "
                "build or schema change, before writing code. May not "
                "exist in this install yet (returns a plain message saying "
                "so, not an error) if the user hasn't supplied it -- "
                "proceed with development_skill.md's general standard "
                "until it is."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_report_build_status",
            "description": (
                "Update the IDE chat panel's persistent build-status "
                "checklist for one phase of a multi-layer development "
                "task -- a small always-visible block in the chat panel "
                "the user can glance at to see where a build actually is, "
                "not another scrolling bubble. Call at the start of each "
                "phase (status='in_progress'), the moment it actually "
                "finishes (status='done'), and immediately if something "
                "stops it (status='blocked') -- not after every file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phase": {
                        "type": "string",
                        "enum": ["frontend", "backend", "storage"],
                        "description": "Which layer this update is about.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["in_progress", "done", "blocked"],
                        "description": "The phase's new status.",
                    },
                    "detail": {
                        "type": "string",
                        "description": (
                            "Optional short note shown next to the phase "
                            "(a one-line plan, summary, or blocker reason)."
                        ),
                    },
                },
                "required": ["phase", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_close_tab",
            "description": (
                "Close one or more open editor tabs (Agent Mode must be on). `which` can be "
                "\"current\", \"all\", \"others\", or the name/path of one specific open tab "
                "(call ide_list_open_tabs first if unsure what's open)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "which": {"type": "string",
                              "description": "\"current\", \"all\", \"others\", or a specific open tab's name/path."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_reveal_in_file_manager",
            "description": "Open the OS's native file explorer/finder with a file or folder selected, same as the Explorer's 'Reveal in File Explorer' (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path (relative to the open workspace, or absolute) of the file/folder to reveal."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_open_in_integrated_terminal",
            "description": "Open the IDE's terminal panel with its working directory set to a given folder, same as the Explorer's 'Open in Integrated Terminal' (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Folder (relative to the open workspace, or absolute) to set as the terminal's working directory."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_copy_path",
            "description": "Copy a file or folder's filesystem path to the clipboard, same as the Explorer's 'Copy Path' / 'Copy Relative Path' (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path (relative to the open workspace, or absolute) whose path should be copied."},
                    "relative": {"type": "boolean", "description": "If true, copy the path relative to the workspace root instead of the absolute path."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_git_init",
            "description": "Initialize a new Git repository in the IDE's open workspace, same as the Source Control panel's 'Initialize Repository' button (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_git_status",
            "description": "Show which files are changed/staged/untracked in the IDE's open workspace, same as the Source Control panel (Agent Mode must be on).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_git_add",
            "description": "Stage file(s) for commit (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {"type": "string", "description": "Space-separated paths to stage, relative to the workspace. Leave empty to stage every changed file."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_git_commit",
            "description": "Commit every currently staged change (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "The commit message."},
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_git_push",
            "description": "Push commits to a remote (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "remote": {"type": "string", "description": "The remote name. Defaults to 'origin'."},
                    "branch": {"type": "string", "description": "The branch to push. Defaults to the current branch."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_git_pull",
            "description": "Pull and merge changes from a remote (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "remote": {"type": "string", "description": "The remote name. Defaults to 'origin'."},
                    "branch": {"type": "string", "description": "The branch to pull. Defaults to the current branch."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_git_branch",
            "description": "List branches, or create a new one (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Leave empty to list every branch. Give a name to create a new branch (without switching to it)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_git_checkout",
            "description": "Switch to a branch, optionally creating it first (Agent Mode must be on).",
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {"type": "string", "description": "The branch name to switch to."},
                    "create": {"type": "boolean", "description": "If true, create the branch before switching to it."},
                },
                "required": ["branch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ide_run_act_script",
            "description": (
                "Runs Friday's ACT Script system on a task that's too deep for a single "
                "model call (Agent Mode must be on). Use for dependent multi-step "
                "builds/refactors/migrations (Sequential Rotation), breadth/research "
                "questions or debugging hypotheses needing independent takes merged "
                "into one (Fan-Out), or whole-artifact writing benefiting from "
                "drafting + cold critique + revision (Debate). Rotates Friday's real "
                "providers (Gemini/Groq/Mistral) so review/critique never comes from "
                "the same model that produced the work. Can take a while -- only use "
                "for tasks that actually warrant it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "The task, in full -- the same level of detail you'd want a careful coworker to have before starting.",
                    },
                    "mode": {
                        "type": "string",
                        "description": "\"auto\" (default, classifies the task itself) or force one of \"sequential\", \"fan_out\", \"debate\".",
                    },
                },
                "required": ["task_description"],
            },
        },
    },
]
