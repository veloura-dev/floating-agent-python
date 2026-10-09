# IDE — Walkthrough & Evaluation

A single-file code editor in pure Python (Tkinter). No third-party packages.

- **File:** `ide.py` (~2,900 lines)
- **Requires:** Python 3.8+ with Tkinter
- **Recommended:** JetBrains Mono font (falls back gracefully)

---

## 1. Running it

```bash
python3 ide.py                  # opens the current folder
python3 ide.py ~/my-project     # opens a specific folder
```

Windows: use `python` instead of `python3`.

If you get `ModuleNotFoundError: No module named 'tkinter'`:

| OS | Command |
|---|---|
| Debian / Ubuntu | `sudo apt install python3-tk` |
| Fedora | `sudo dnf install python3-tkinter` |
| macOS (Homebrew) | `brew install python-tk` |
| Windows | Included with python.org installers |

Optional font:

| OS | Command |
|---|---|
| Debian / Ubuntu | `sudo apt install fonts-jetbrains-mono` |
| macOS | `brew install --cask font-jetbrains-mono` |
| Windows | [jetbrains.com/lp/mono](https://www.jetbrains.com/lp/mono/) |

---

## 2. First 60 seconds

1. The window opens frameless and floating, with an empty `untitled-1` tab.
2. **Left** — the EXPLORER file tree. **Click a folder** to expand it, **click a
   file once** to open it (single click, like VS Code).
3. **Ctrl+`** opens the integrated terminal at the bottom. It runs real shell
   commands in your workspace folder.
4. Open a `.py` file and press **F5** to run it; output streams into the terminal.
5. Click **Theme: Grey** in the status bar to cycle grey → black → white.
6. Drag the **menu bar** to move the window; drag the **right/bottom edge** to
   resize; **double-click the menu bar** to maximize.

---

## 3. Layout

```
┌──────────────────────────────────────────────────────────────┐
│ </>  File Edit Selection View Go Run Terminal Help   ─ □ ✕    │  menu bar / drag handle
├──────────────┬───────────────────────────────────────────────┤
│ EXPLORER     │  untitled-1 │ main.py ×                        │  tab strip
│              ├───────────────────────────────────────────────┤
│ MY_PROJECT   │  src › main.py                                 │  breadcrumb
│   src        ├──┬─────────────────────────────────────┬──────┤
│              │ 1│ """Demo module."""                  │▓▒░   │  gutter │ code │ minimap
│ MY_PROJECT   │ 2│ import math                         │      │
│   src        │ 3│                                     │      │
│   README.md  │  │                                     │      │
│              ├──┴─────────────────────────────────────┴──────┤
│              │ PROBLEMS OUTPUT DEBUG CONSOLE TERMINAL   + ^ ✕ │  panel
│              │ my-project $ █                                 │
├──────────────┴───────────────────────────────────────────────┤
│ ⎇ main ✖0 ⚠0        Theme: Grey  Opacity 97%  75%  UTF-8 ... │  status bar
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Keyboard reference

### Files
| Shortcut | Action |
|---|---|
| `Ctrl+N` | New buffer (in memory until saved) |
| `Ctrl+O` | Open file… |
| `Ctrl+S` | Save |
| `Ctrl+Shift+S` | Save As… |
| `Ctrl+Alt+S` | **Save All** |
| `Ctrl+W` | Close editor (prompts if unsaved) |

### Navigation
| Shortcut | Action |
|---|---|
| `Ctrl+P` | Quick Open (fuzzy file finder) |
| `Ctrl+Shift+P` | Command Palette (every menu action) |
| `Ctrl+G` | Go to line |
| `Ctrl+Shift+E` | Explorer view |
| `Ctrl+Shift+F` | Search across the workspace |

### Editing
| Shortcut | Action |
|---|---|
| `Ctrl+F` / `Ctrl+H` | Find / Replace (smart case) |
| `Ctrl+Space` | Trigger suggestions |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo |
| `Tab` / `Shift+Tab` | Indent / outdent selection |
| `Alt+↑` / `Alt+↓` | Move line |
| `Shift+Alt+↓` | Duplicate line |

### View & window
| Shortcut | Action |
|---|---|
| `Ctrl+B` | Toggle sidebar |
| `Ctrl+`` ` | Toggle terminal |
| `Ctrl+=` / `Ctrl+-` / `Ctrl+0` | Zoom in / out / reset to 75% |
| `Ctrl+Shift+T` | Cycle theme |
| `Ctrl+Shift+=` / `Ctrl+Shift+-` | More / less opaque |
| `F5` | Run the current Python file |

---

## 5. Features in detail

**Editor** — syntax highlighting for 25+ languages, line numbers, current-line highlight,
auto-indent (after `:`), auto-closing brackets/quotes, bracket skip-over,
undo/redo, word-based autocomplete with Python keywords and builtins.

**Explorer** — lazy-loaded tree, **a real icon per file type** (see 5g),
single-click to open, full right-click menu (below). Skips `.git`,
`node_modules`, `__pycache__`, `.venv`, `dist`, `build` and similar.

**Tabs** — dirty dot for unsaved changes, close button, middle-click to close,
prompts before discarding changes.

**Terminal** — real subprocess execution with streaming output, `cd` tracking,
command history (↑/↓), `Ctrl+C` to interrupt, `clear`.

**Search** — in-file find/replace with smart case (lowercase query =
case-insensitive), plus workspace-wide search and replace-across-files.

**Themes** — three hard-coded palettes, switchable at runtime without losing
open files, cursor position, or terminal history.

**Media** — images and PDFs open in a zoomable viewer tab (see 5f), with
built-in JPEG/BMP/TGA decoders so no extra packages are required.

**Window** — frameless floating panel, translucent (97%), drag to move, edge
resize, custom minimize/maximize/close, optional always-on-top, rounded corners
on Windows.

**External change detection** — a 1.5s watcher reloads files edited outside the
IDE. If you have unsaved edits in that file, it will **not** clobber them; it
flags a conflict instead.

---

## 5b. Languages

Syntax highlighting is driven by a per-language lexer, picked from the file
extension (or filename, for `Makefile`, `Dockerfile`, `Gemfile`, …):

| Group | Languages |
|---|---|
| Web | JavaScript, TypeScript, JSX/TSX, HTML, Vue, Svelte, CSS/SCSS/Less |
| Systems | C, C++, Rust, Go, Swift |
| JVM / .NET | Java, Kotlin, C# |
| Scripting | Python, Ruby, PHP, Lua, Shell (bash/zsh), Perl, R |
| Data / config | JSON, YAML, TOML, INI, XML, SVG, SQL, Markdown |
| Build | Dockerfile, Makefile, CMake |

Anything else opens as plain text — every file is readable, nothing is refused
except true binaries, which show a guard message instead of garbage.

## 5c. Building and running

The IDE inspects the workspace and offers the right commands automatically.

| Detected | Tasks offered |
|---|---|
| `package.json` | every npm script (`dev`, `build`, `start`, `test`, …) using the right package manager — npm / pnpm / yarn / bun, chosen from the lockfile |
| `manage.py` | Django runserver, migrate |
| `requirements.txt` / `pyproject.toml` | run entry point, pip install, build, pytest |
| `go.mod` | go run / build / test |
| `Cargo.toml` | cargo run / build --release / test |
| `pom.xml`, `build.gradle` | Maven, Gradle (uses `./gradlew` when present) |
| `*.csproj`, `*.sln` | dotnet run / build |
| `Gemfile`, `composer.json` | bundler, composer, PHP dev server |
| `Makefile` | `make` plus each discovered target |
| `CMakeLists.txt` | configure + build |
| `Dockerfile`, `docker-compose.yml` | docker build, compose up |
| `index.html` (no package.json) | static server on :5500 |

**Single files** run directly with `F5`, whatever the language — `.py`, `.js`,
`.ts` (via `tsx`), `.sh`, `.rb`, `.php`, `.lua`, `.go`, `.rs`, `.c`, `.cpp`,
`.java`, `.swift`, `.kt`, `.R`. HTML opens in your browser.

**Web development** — when a dev server starts, the IDE sniffs the URL out of
the output (`http://localhost:5173`, `listening on port 3000`, …), shows it in
the status bar, and opens your browser. Set `app.auto_open_browser = False` to
disable.

| Shortcut | Action |
|---|---|
| `F5` | Run the current file |
| `Ctrl+F5` | Run the project (npm dev / cargo run / …) |
| `Ctrl+Shift+B` | Build the project |
| `Ctrl+Shift+R` | Tasks… (pick from everything detected) |
| `Ctrl+.` | Stop the running process |
| `Ctrl+Shift+V` | Open in browser |

Processes start in their own process group, so **Stop** kills the whole tree —
a dev server and its children die together.

## 5d. Managing files

Right-click anywhere in the Explorer:

| Item | Shortcut | Notes |
|---|---|---|
| New File… | | created next to the clicked item, then opened |
| New Folder… | | nested paths like `src/utils` work |
| Open / Run File | `F5` | files only |
| Reveal in File Explorer | `Shift+Alt+R` | Explorer / Finder / `xdg-open` |
| Open in Integrated Terminal | | points the terminal at that folder |
| Find in Folder… | `Shift+Alt+F` | narrows workspace search to that subtree |
| Cut / Copy / Paste | `Ctrl+X/C/V` | real file moves and copies |
| Duplicate | | auto-names `file copy.py` |
| Copy Path / Copy Relative Path | `Shift+Alt+C` | |
| Rename… | `F2` | |
| Delete | `Del` | confirms first; folders delete recursively |
| Refresh Explorer | | |

`Ctrl+X/C/V` are bound to the tree only, so they never shadow the editor's own
cut/copy/paste.

Open tabs stay correct through all of this: **renaming a file retargets its
tab**, renaming a folder retargets every file open beneath it, and deleting
something closes its tab instead of leaving a phantom buffer.

The **OPEN EDITORS** section has been removed — open files are in the tab strip.

## 5e. Agent file API

Every operation above runs through one sandboxed object, `app.fs`, which is
also the interface an AI agent will use:

```python
app.fs.create_file("src/utils.py", "def helper():\n    pass\n")
app.fs.create_folder("tests")
app.fs.write("README.md", text)      # overwrites
app.fs.read("src/main.py")
app.fs.rename("old.py", "new.py")
app.fs.move("a.py", "src")
app.fs.copy("a.py", dst_dir="backup")
app.fs.delete("scratch")             # recursive for folders
app.fs.list("src")                   # names in one folder
app.fs.tree()                        # all files, workspace-relative
app.fs.exists(p) / app.fs.is_dir(p)
```

Two guarantees:

- **Sandboxed.** Paths resolve against the workspace root and are rejected if
  they escape it — `../`, absolute paths and symlink tricks all raise
  `PermissionError`. Deleting the workspace root is refused.
- **Thread-safe to call.** Disk work happens on the calling thread; the tree
  refresh, quick-open re-index and tab updates are marshalled onto the Tk main
  thread. A background agent thread can call these directly without crashing
  Tk.

## 5f. Viewing images and PDFs

Click any image or PDF in the Explorer and it opens in a viewer tab instead of
as garbled text. The toolbar gives zoom out / percentage / zoom in, **Fit**,
**1:1**, the pixel dimensions, and **Open externally**. Drag to pan,
`Ctrl`+wheel to zoom, wheel to scroll. PDFs also get `◀ page n/N ▶`.

### Images

Tk itself can only decode PNG, GIF and PPM, so the IDE ships its own decoders.
Support is layered, best available wins:

| Tier | Needs | Formats |
|---|---|---|
| Tk built-in | nothing | PNG, GIF, PPM/PGM/PBM/PNM |
| **Bundled pure-python decoders** | nothing | **JPEG** (baseline, all subsampling modes, restart markers, grayscale), **BMP** (1/4/8/16/24/32-bit, RLE-free, top-down and bottom-up), **TGA** (raw + RLE) |
| Pillow, if installed | `pip install pillow` | WebP, TIFF, ICO, AVIF, HEIC, JPEG 2000, PSD… |
| External converter | ImageMagick / `sips` | anything those can read |

So **JPEG, PNG, GIF and BMP work on a bare Python install with no extra
packages** — verified by a test that blocks Pillow and hides every external
tool. Formats that genuinely cannot be decoded show a clear message naming
what to install, rather than failing silently.

Very large JPEGs (over ~2.5 megapixels) decode DC-only, producing a 1/8-scale
preview almost instantly instead of freezing for minutes in pure python; the
toolbar says so, e.g. `1/8 preview of 2200x1400`.

### PDFs

| Situation | Behaviour |
|---|---|
| A renderer is installed (`pdftoppm`, `mutool`, Ghostscript, ImageMagick, `sips`) | pages render as images with page navigation; re-rendered at higher DPI as you zoom, so text stays sharp |
| No renderer | the PDF opens as **extracted text** (pure python: object parsing, Flate decompression, `Tj`/`TJ` operators) with a header explaining what to install |
| Scanned/image-only PDF and no renderer | says so explicitly instead of showing an empty page |

Candidate renderers are **probed by actually running them** — ImageMagick is
installed on many systems but cannot render PDFs without Ghostscript, and that
case is detected and skipped rather than producing a blank page.

Extracted-text PDFs are opened **read-only**; saving is refused so the original
file can never be overwritten with its own text dump.

## 5g. File-type icons

Every row in the Explorer carries an icon drawn to the left of the name.
They are generated at runtime as `PhotoImage` pixels - **no image files, no
icon font, no dependency** - so nothing can go missing on another machine.

| Kind | Icon |
|---|---|
| Source code | document in the language's brand colour with a monogram: `PY`, `JS`, `TS`, `TSX`, `HTM`, `CSS`, `GO`, `RS`, `CPP`, `JAV`, `PHP`, `SQL`… |
| Images | teal document with a mountains-and-sun glyph |
| PDF | red `PDF` document |
| Archives | amber document with a zipper |
| Audio / video | quaver / play triangle |
| Fonts, binaries | `F` / `BIN` |
| Folders | folder with a tab, switching to an open variant when expanded |
| Unknown | grey document with the extension, e.g. `XYZ` |

Around 90 extensions are mapped, plus extension-less names such as
`Dockerfile`, `Makefile`, `Gemfile`, `.gitignore`, `.env` and `LICENSE`.
Anything unmapped still gets a readable icon from its own extension, so the
list never has to be exhaustive.

Monograms use a small built-in pixel font. Letters are variable width -
`N`, `M` and `W` are wider than the rest, because at three pixels they are
indistinguishable from `K`, `H` and `H`. Icons scale with `UI_SCALE` and are
cached per (type, size), so each one is drawn once.

## 6. Evaluation results

Automated audit, 29 checks, all passing:

| Area | Checks | Result |
|---|---|---|
| File I/O | open, unicode, binary guard, 4k-line file, missing file | 5/5 |
| Editing | dirty flag, save to disk, clean after save, undo | 4/4 |
| Tabs | new, close | 2/2 |
| Search | find, find-next, replace-all, workspace search | 4/4 |
| Navigation | go-to-line, workspace index, autocomplete | 3/3 |
| Terminal | command, `cd`, failing command | 3/3 |
| Run | F5 produces correct program output | 1/1 |
| Languages | 18 languages highlight correctly | 18/18 |
| Build/run | JS, shell, Python files; web server start/serve/stop | 5/5 |
| Filesystem | create/rename/move/copy/delete, tab retargeting | 20/20 |
| Sandbox | `../`, absolute paths, root deletion all blocked | 5/5 |
| Context menu | menu builds and contains every required item | 4/4 |
| Binary sniffing | 13 formats + 300 random samples | 14/14 |
| Image viewing | 8 formats, zoom, fit, 1:1, big-JPEG preview | 26/26 |
| No-dependency mode | Pillow blocked + all external tools hidden | 17/17 |
| Decoder accuracy | JPEG/BMP/TGA compared against libjpeg/Pillow | exact for BMP+TGA, mean error 0.89/255 for JPEG |
| PDF | page count, metadata, text extraction, rendering | 15/15 |
| File icons | mapping, categories, drawing, caching, tree use | 12/12 |
| View | zoom reset, minimap, themes, opacity, maximize, sidebar | 6/6 |
| Safety | external reload, conflict guard, save-all, close protocol | 10/10 |

### Bugs found and fixed during this audit

1. **Quadratic syntax highlighting.** `highlight()` addressed tags with
   character offsets (`"1.0+12345c"`), which Tk resolves by walking the buffer
   — O(n) per tag. A 4,000-line file took **10.3 seconds** to open and froze
   the UI. Now precomputes line starts and emits `line.col` indices, batching
   one `tag_add` per tag type: **0.10s** (~100× faster).
2. **Minimap tag copying.** Duplicated every syntax tag range into the 2px
   preview. Now renders as plain text.
3. **`File ▸ Exit` discarded unsaved work** — it called `destroy()` directly,
   bypassing the save prompt.
4. **No `WM_DELETE_WINDOW` handler** — Alt+F4 / window-manager close silently
   lost unsaved changes.
5. **No external-change detection** — a file edited by an agent or `git
   checkout` would be silently overwritten by the stale buffer on next save.
6. **Weak binary detection** — it required a NUL in the first 256 bytes, so a
   JPEG (and ~37% of random data) opened as garbage text. Now sniffs 8 KB,
   checks magic numbers, and falls back on a control-byte ratio.
7. **Context menu crashed on a missing palette key** (`menu_bg`). The
   functional test only asserted the handler was callable — a screenshot
   caught it. The test now builds and posts the menu and asserts its items.

---

## 7. Known limitations

- **Terminal is not a PTY.** Programs that wait for interactive input
  (`input()`, `sudo` password, `vim`) will hang. Run those in a real terminal.
- **Toolchains must be installed.** The IDE detects and invokes `node`, `go`,
  `cargo`, `mvn`, `docker` and friends, but does not install them; a missing
  tool surfaces as "command not found" in the terminal.
- **Progressive JPEGs are rejected** by the built-in decoder (baseline only).
  They fall through to Pillow or an external converter if available.
- **Animated GIFs show the first frame**; there is no playback.
- **The built-in JPEG decoder is pure python**, so a full-resolution decode of
  a multi-megapixel photo takes a second or two. Install Pillow if you work
  with large images constantly.
- **PDF text extraction is best-effort.** It handles ordinary text PDFs but
  not unusual encodings or scanned pages; install a renderer for fidelity.
- **Highlighting is regex-based, not a parser.** It is fast and good enough
  for reading and writing code, but it will not catch every edge case (e.g.
  JS regex literals vs division, HTML embedded in template strings).
- **Highlighting/minimap disable above 400,000 characters** to stay responsive.
- **Rounded corners are Windows-only** (DWM). X11 has no equivalent without
  XShape masking; the window stays square on Linux.
- **Translucency needs a compositor.** Standard on Windows/macOS; on a bare X
  session without picom/xcompmgr the window renders opaque.
- **Problems / Output / Debug Console panel tabs are decorative** — only
  TERMINAL is wired up.
- **No Git integration.** The Source Control view is a placeholder and the
  `⎇ main` status item is static text.
- **Minimize flickers** — an `overrideredirect` window can't iconify directly,
  so it briefly restores the native frame.

---

## 8. Not yet built

1. **The agent connection itself** — transport to a model, and a chat/diff
   surface in the IDE. The file and theme APIs it needs are now in place.
2. **Not carried over from the reference menu:** "Open in Images Preview"
   (no image viewer), "Add/Remove Folder from Workspace" (single-root
   workspace), "Open Folder Settings" (no settings store) and "Add Folder to
   Chat" (no chat yet).

The theme API is already agent-ready:

```python
app.list_themes()        # ['grey', 'black', 'white']
app.set_theme("black")
app.cycle_theme()
```

---

## 9. Regression suite

```
tests/
  core_test.py           25  file I/O, editing, search, nav, view, safety,
                             18 languages, the runner
  fs_test.py             35  create/rename/move/copy/delete, sandbox escapes,
                             context menu, tab retargeting
  media_test.py          28  9 image formats, zoom/fit/1:1, PDF pages or
                             text fallback, missing-file handling
  media_nodeps_test.py   20  same, with Pillow blocked and every external
                             tool hidden - the bare-python path
  icons_test.py          12  file-type icon mapping, drawing, folder
                             open/close, caching, theme survival
  _fixtures.py               workspace, image and PDF builders
  run_all.py                 runs all four, prints one table
```

Each suite builds its own throwaway workspace under the system temp
directory and deletes it afterwards, so the suites are order-independent and
repeatable. Paths are derived from `__file__`, so the project can live
anywhere, and **the fixtures themselves need no third-party packages** -
PNG/BMP/TGA/PPM are written by pure-python encoders in `_fixtures.py` and
JPEG/GIF/WebP/TIFF are stored as small base64 blobs. The suite therefore runs
identically on a stock Windows Python and on a fully equipped Linux box.

```bash
python3 tests/run_all.py            # 103 checks

# headless:
Xvfb :99 -screen 0 1600x1000x24 &
DISPLAY=:99 python3 tests/run_all.py
```

```
suite                             pass  fail   status
core, languages, runner             25     0   ok
filesystem, sandbox, menu           35     0   ok
images and PDFs                     28     0   ok
bare-python fallbacks               20     0   ok
file-type icons                     12     0   ok
TOTAL                              120     0
```

One media check is conditional on a PDF renderer being installed, so the
total is 119 without one. Verified both ways, and on Windows.

The table prints a short hash of each test file. If two machines disagree on
the number of checks, compare those hashes first - it is almost always a
stale copy rather than a real difference.

`run_all.py` exits non-zero on any failure, so it drops straight into CI.

## 10. Tunable constants

At the top of `ide.py`:

```python
EDITOR_FONT_SIZE = 12        # 100% baseline, points
UI_FONT_SIZE = 10            # menus, tabs, sidebar
DEFAULT_ZOOM = 0.75          # editor opens at 75%
DEFAULT_OPACITY = 0.97       # window translucency
DEFAULT_THEME = "grey"       # grey | black | white
MAX_HIGHLIGHT_CHARS = 400_000
MAX_MINIMAP_CHARS = 400_000
```
