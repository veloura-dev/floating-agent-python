#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  IDE - a lightweight code editor built entirely with Python's standard
  library (Tkinter). Intended to be wired up to an AI agent that can read
  and edit the open source files (agent integration not implemented yet).

      python3 ide.py [optional_folder]

  Dark grey theme, grey outlines, frameless translucent floating window.
  No third-party packages required.
================================================================================
"""

import atexit
import json
import math
import os
import re
import sys
import queue
import shutil
import struct
import signal
import zlib
import threading
import subprocess
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont

# ------------------------------------------------------------------ #
#  Themes                                                             #
#  Three hard-coded palettes an agent (or the user) can switch        #
#  between at runtime:  "grey" | "black" | "white"                    #
#  -> app.set_theme("black"), app.cycle_theme(), app.list_themes()    #
# ------------------------------------------------------------------ #
THEMES = {
    # ---------------- 1. GREY (default) ----------------
    "grey": {
        "text_fg":       "#d8d8de",
        "caret":         "#6ea8fe",
        "sel_inactive":  "#2b3344",
        "term_cwd":      "#7fcbbd",
        "term_err":      "#f14c4c",
        "term_info":     "#6fa8dc",
        "editor":        "#232326",
        "sidebar":       "#1c1c1f",
        "activity":      "#141416",
        "menubar":       "#19191c",
        "menubar_hover": "#2a2a2f",
        "panel":         "#1a1a1e",
        "chat":          "#1e1e23",
        "terminal":      "#18181b",
        "statusbar":     "#17171a",
        "status_fg":     "#a8a8b2",
        "success":       "#49b870",
        "warn":          "#d7a23c",
        "danger":        "#f14c4c",
        "fg":            "#e6e6ea",
        "fg_dim":        "#9d9da7",
        "fg_faint":      "#6b6b75",
        "fg_bright":     "#ffffff",
        "border":        "#2f2f35",
        "border_soft":   "#26262a",
        "border_hi":     "#3c3c44",
        "tabbar":        "#1c1c1f",
        "tab_active":    "#232326",
        "tab_inactive":  "#1c1c1f",
        "tab_in_fg":     "#8d8d97",
        "hover":         "#2a2a2f",
        "list_sel":      "#2f2f37",
        "input":         "#232327",
        "accent":        "#6ea8fe",
        "accent_btn":    "#2f2f37",
        "accent_hover":  "#3a3a44",
        "link":          "#8ab4f8",
        "scroll":        "#35353d",
        "scroll_hover":  "#484852",
        "cur_line":      "#28282c",
        "sel":           "#2f4a6d",
        "gutter":        "#5c5c66",
        "gutter_cur":    "#d8d8de",
        "kw":     "#7cb7f0",
        "str":    "#d8a07a",
        "com":    "#7fa87f",
        "num":    "#bcd4a8",
        "fn":     "#e3e3a8",
        "cls":    "#7fcbbd",
        "dec":    "#dcc58c",
        "findall": "#5a5a5a",
        "findcur": "#7a7a7a",
    },
    # ---------------- 2. BLACK (high contrast dark) ----------------
    "black": {
        "text_fg":       "#dcdce2",
        "caret":         "#7aa2f7",
        "sel_inactive":  "#1a1f2b",
        "term_cwd":      "#6fd0bd",
        "term_err":      "#ff5f5f",
        "term_info":     "#6fa8dc",
        "editor":        "#000000",
        "sidebar":       "#07070a",
        "activity":      "#000000",
        "menubar":       "#030305",
        "menubar_hover": "#141418",
        "panel":         "#09090c",
        "chat":          "#0c0c10",
        "terminal":      "#000000",
        "statusbar":     "#030305",
        "status_fg":     "#9a9aa4",
        "success":       "#49d88a",
        "warn":          "#e0b35a",
        "danger":        "#ff5f5f",
        "fg":            "#e8e8ec",
        "fg_dim":        "#9a9aa4",
        "fg_faint":      "#63636c",
        "fg_bright":     "#ffffff",
        "border":        "#222228",
        "border_soft":   "#151519",
        "border_hi":     "#33333c",
        "tabbar":        "#000000",
        "tab_active":    "#0d0d10",
        "tab_inactive":  "#000000",
        "tab_in_fg":     "#84848e",
        "hover":         "#141418",
        "list_sel":      "#1c1c23",
        "input":         "#0d0d10",
        "accent":        "#7aa2f7",
        "accent_btn":    "#1c1c23",
        "accent_hover":  "#26262f",
        "link":          "#7aa2f7",
        "scroll":        "#26262e",
        "scroll_hover":  "#3a3a45",
        "cur_line":      "#0e0e11",
        "sel":           "#1f3050",
        "gutter":        "#55555f",
        "gutter_cur":    "#e8e8ec",
        "kw":     "#6fb0ee",
        "str":    "#e0956b",
        "com":    "#6f9e6f",
        "num":    "#b5d49a",
        "fn":     "#ece9a0",
        "cls":    "#6fd0bd",
        "dec":    "#e0c37f",
        "findall": "#3a3a1f",
        "findcur": "#6b5a1f",
    },
    # ---------------- 3. WHITE (light) ----------------
    "white": {
        "text_fg":       "#1f2328",
        "caret":         "#2563eb",
        "sel_inactive":  "#e4e9f0",
        "term_cwd":      "#0f6f5c",
        "term_err":      "#b31a1a",
        "term_info":     "#0066b8",
        "editor":        "#ffffff",
        "sidebar":       "#f7f8fa",
        "activity":      "#eef0f4",
        "menubar":       "#f2f4f7",
        "menubar_hover": "#e9ecf1",
        "panel":         "#f1f3f6",
        "chat":          "#f5f6f9",
        "terminal":      "#ffffff",
        "statusbar":     "#eef0f4",
        "status_fg":     "#5a626d",
        "success":       "#0f6f3c",
        "warn":          "#8a5a0c",
        "danger":        "#b31a1a",
        "fg":            "#1f2328",
        "fg_dim":        "#5a626d",
        "fg_faint":      "#8b939e",
        "fg_bright":     "#0b0d0f",
        "border":        "#e3e5ea",
        "border_soft":   "#edeff3",
        "border_hi":     "#ced3da",
        "tabbar":        "#f0f2f5",
        "tab_active":    "#ffffff",
        "tab_inactive":  "#f0f2f5",
        "tab_in_fg":     "#5a626d",
        "hover":         "#e9ecf1",
        "list_sel":      "#e2e9f5",
        "input":         "#ffffff",
        "accent":        "#2563eb",
        "accent_btn":    "#e6eaf1",
        "accent_hover":  "#d8dee9",
        "link":          "#1d4ed8",
        "scroll":        "#d4d8de",
        "scroll_hover":  "#b8bec8",
        "cur_line":      "#f4f6f9",
        "sel":           "#cfe0fb",
        "gutter":        "#a7aeb9",
        "gutter_cur":    "#1f2328",
        "kw":     "#0000ff",
        "str":    "#a31515",
        "com":    "#008000",
        "num":    "#098658",
        "fn":     "#795e26",
        "cls":    "#267f99",
        "dec":    "#8a6d1c",
        "findall": "#ffe08a",
        "findcur": "#ffb700",
    },
}

DEFAULT_THEME = "grey"

# Live palette. Widgets read from this dict, so a theme switch mutates it
# in place and then rebuilds the widget tree.
C = dict(THEMES[DEFAULT_THEME])

LANG_NAMES = {
    "py": "Python", "js": "JavaScript", "ts": "TypeScript", "html": "HTML",
    "css": "CSS", "json": "JSON", "md": "Markdown", "sh": "Shell Script",
    "c": "C", "cpp": "C++", "java": "Java", "go": "Go", "rs": "Rust",
    "rb": "Ruby", "php": "PHP", "sql": "SQL", "yml": "YAML", "yaml": "YAML",
    "xml": "XML", "toml": "TOML", "txt": "Plain Text", "csv": "CSV",
}

# ------------------------------------------------------------------ #
#  Language definitions                                               #
# ------------------------------------------------------------------ #
KW = {
 "python": "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return self cls try while with yield match case",
 "javascript": "abstract arguments await async break case catch class const continue debugger default delete do else enum export extends false finally for from function get if implements import in instanceof interface let new null of package private protected public return set static super switch this throw true try typeof var void while with yield",
 "typescript": "abstract any as asserts async await bigint boolean break case catch class const constructor continue declare default delete do else enum export extends false finally for from function get if implements import in infer instanceof interface is keyof let module namespace never new null number object of package private protected public readonly return satisfies set static string super switch symbol this throw true try type typeof undefined unique unknown var void while yield",
 "java": "abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public record return short static strictfp super switch synchronized this throw throws transient try var void volatile while true false null",
 "c": "auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while NULL true false",
 "cpp": "alignas alignof and asm auto bool break case catch char class co_await co_return co_yield concept const consteval constexpr const_cast continue decltype default delete do double dynamic_cast else enum explicit export extern false float for friend goto if inline int long mutable namespace new noexcept nullptr operator or private protected public register reinterpret_cast requires return short signed sizeof static static_assert static_cast struct switch template this thread_local throw true try typedef typeid typename union unsigned using virtual void volatile while",
 "go": "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var nil true false iota",
 "rust": "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
 "ruby": "BEGIN END alias and begin break case class def defined? do else elsif end ensure false for if in module next nil not or redo rescue retry return self super then true undef unless until when while yield require require_relative attr_accessor attr_reader puts",
 "php": "abstract and array as break callable case catch class clone const continue declare default do echo else elseif empty enddeclare endfor endforeach endif endswitch endwhile enum extends final finally fn for foreach function global goto if implements include include_once instanceof insteadof interface isset list match namespace new or print private protected public readonly require require_once return static switch throw trait try unset use var while xor yield true false null",
 "shell": "if then else elif fi case esac for while until do done in function select time coproc return break continue local export readonly declare typeset unset shift eval exec exit trap source alias echo cd set",
 "sql": "SELECT FROM WHERE INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE ALTER DROP INDEX VIEW JOIN INNER LEFT RIGHT FULL OUTER ON GROUP BY ORDER HAVING LIMIT OFFSET UNION ALL DISTINCT AS AND OR NOT NULL IS IN BETWEEN LIKE EXISTS CASE WHEN THEN ELSE END PRIMARY KEY FOREIGN REFERENCES DEFAULT CONSTRAINT UNIQUE CHECK CASCADE WITH RETURNING",
 "yaml": "true false null yes no on off",
 "json": "true false null",
 "toml": "true false",
 "lua": "and break do else elseif end false for function goto if in local nil not or repeat return then true until while",
 "kotlin": "as break class continue do else false for fun if in interface is null object package return super this throw true try typealias val var when while by get set import data sealed suspend override private public internal",
 "swift": "associatedtype class deinit enum extension fileprivate func import init inout internal let open operator private protocol public rethrows static struct subscript typealias var break case continue default defer do else fallthrough for guard if in repeat return switch where while as catch false is nil super self throw throws true try",
 "csharp": "abstract as base bool break byte case catch char checked class const continue decimal default delegate do double else enum event explicit extern false finally fixed float for foreach goto if implicit in int interface internal is lock long namespace new null object operator out override params private protected public readonly ref return sbyte sealed short sizeof stackalloc static string struct switch this throw true try typeof uint ulong unchecked unsafe ushort using var virtual void volatile while async await record",
}
BUILTINS = {
 "python": "print len range type isinstance issubclass str int float bool list dict set tuple frozenset bytes bytearray open enumerate zip map filter sorted reversed sum min max abs round super getattr setattr hasattr callable iter next input vars dir repr format chr ord hex id object Exception ValueError TypeError KeyError IndexError RuntimeError AttributeError OSError FileNotFoundError StopIteration",
 "javascript": "console window document Object Array String Number Boolean Math JSON Promise Map Set WeakMap Symbol Date RegExp Error TypeError fetch setTimeout setInterval require module exports process Buffer __dirname __filename globalThis localStorage alert",
 "typescript": "console window document Object Array String Number Boolean Math JSON Promise Map Set Symbol Date RegExp Error fetch setTimeout setInterval require module exports process Record Partial Pick Omit Readonly Array Promise",
 "go": "append cap close complex copy delete imag len make new panic print println real recover string int int8 int16 int32 int64 uint uintptr float32 float64 byte rune bool error fmt",
 "rust": "Vec String Option Result Some None Ok Err Box Rc Arc HashMap HashSet println print format vec panic assert write writeln Default Clone Copy Debug",
 "java": "System String Integer Double Boolean Long Object List Map Set ArrayList HashMap HashSet Exception RuntimeException Math Arrays Collections Optional Stream",
 "shell": "echo printf read test cat ls cd pwd grep sed awk find xargs curl wget git npm node python pip make docker chmod mkdir rm cp mv touch kill ps sudo apt tar",
}

SPECS = {
 "python":     dict(exts=("py","pyw","pyi"), line="#", triple=True, decorator=True),
 "javascript": dict(exts=("js","mjs","cjs","jsx"), line="//", block=("/*","*/"), template=True, regex_lit=True),
 "typescript": dict(exts=("ts","tsx","mts","cts"), line="//", block=("/*","*/"), template=True, regex_lit=True),
 "java":       dict(exts=("java",), line="//", block=("/*","*/"), annot=True),
 "c":          dict(exts=("c","h"), line="//", block=("/*","*/"), preproc=True),
 "cpp":        dict(exts=("cpp","cc","cxx","hpp","hh","hxx","ino"), line="//", block=("/*","*/"), preproc=True),
 "csharp":     dict(exts=("cs",), line="//", block=("/*","*/"), annot=True),
 "go":         dict(exts=("go",), line="//", block=("/*","*/"), template=True),
 "rust":       dict(exts=("rs",), line="//", block=("/*","*/"), annot=True),
 "ruby":       dict(exts=("rb","rake","gemspec"), line="#", symbol=True),
 "php":        dict(exts=("php","phtml"), line="//", block=("/*","*/"), variable=True),
 "shell":      dict(exts=("sh","bash","zsh","ksh","bashrc","zshrc"), line="#", variable=True),
 "sql":        dict(exts=("sql",), line="--", block=("/*","*/"), ci_keywords=True),
 "lua":        dict(exts=("lua",), line="--"),
 "kotlin":     dict(exts=("kt","kts"), line="//", block=("/*","*/"), annot=True),
 "swift":      dict(exts=("swift",), line="//", block=("/*","*/"), annot=True),
 "json":       dict(exts=("json","jsonc","webmanifest"), block=("/*","*/"), keys=True),
 "yaml":       dict(exts=("yml","yaml"), line="#", keys=True),
 "toml":       dict(exts=("toml","ini","cfg","conf","properties"), line="#", keys=True, section=True),
 "html":       dict(exts=("html","htm","xhtml","vue","svelte"), markup=True),
 "xml":        dict(exts=("xml","svg","xsl","plist","storyboard"), markup=True),
 "css":        dict(exts=("css","scss","sass","less"), block=("/*","*/"), css=True),
 "markdown":   dict(exts=("md","markdown","mdx"), md=True),
 "dockerfile": dict(exts=("dockerfile",), line="#", dockerfile=True),
 "make":       dict(exts=("mk","makefile"), line="#", make=True),
}

GROUP_TAG = {
    "cblock": "comment", "cline": "comment", "string": "string",
    "number": "number", "keyword": "keyword", "builtin": "builtin",
    "funcall": "funcall", "decorator": "decorator", "clsname": "clsname",
    "tagname": "tagname", "attrname": "attrname", "key": "key",
    "heading": "keyword", "mdcode": "string", "mdlink": "funcall",
    "preproc": "decorator", "variable": "builtin", "symbol": "number",
}

LANG_BY_EXT = {}
for _n, _s in SPECS.items():
    for _e in _s["exts"]:
        LANG_BY_EXT[_e] = _n
FILENAME_LANG = {"makefile": "make", "dockerfile": "dockerfile",
                 "gemfile": "ruby", "rakefile": "ruby", "vagrantfile": "ruby",
                 "cmakelists.txt": "make", ".gitignore": "shell",
                 ".env": "shell", ".bashrc": "shell", ".zshrc": "shell"}

_CACHE = {}

def _words(s):
    return "|".join(sorted((re.escape(w) for w in s.split()), key=len, reverse=True))

def get_lexer(lang):
    if lang in _CACHE:
        return _CACHE[lang]
    sp = SPECS.get(lang)
    if not sp:
        _CACHE[lang] = None
        return None
    p = []
    # ---- comments first ----
    if sp.get("md"):
        p.append(r"(?P<cblock>^\s*>.*$)")
    if sp.get("markup"):
        p.append(r"(?P<cblock><!--(?:.|\n)*?-->)")
    if sp.get("block"):
        o, c = sp["block"]
        p.append(r"(?P<cblock>%s(?:.|\n)*?%s)" % (re.escape(o), re.escape(c)))
    if sp.get("line"):
        p.append(r"(?P<cline>%s[^\n]*)" % re.escape(sp["line"]))
    # ---- markdown specials ----
    if sp.get("md"):
        p.append(r"(?P<heading>^\#{1,6}[^\n]*)")
        p.append(r"(?P<mdcode>```(?:.|\n)*?```|`[^`\n]+`)")
        p.append(r"(?P<mdlink>\[[^\]\n]*\]\([^)\n]*\))")
        p.append(r"(?P<keyword>\*\*[^*\n]+\*\*|__[^_\n]+__)")
    # ---- keys before strings: a quoted key must not be eaten as a string ----
    if sp.get("keys"):
        p.append(r'(?P<key>(?<=^)[ \t]*[\"\']?[\w.\-/]+[\"\']?(?=[ \t]*:)|(?<=[{,\n])[ \t]*\"[^\"\n]+\"(?=[ \t]*:))')
    if sp.get("section"):
        p.append(r"(?P<tagname>^\s*\[[^\]\n]+\])")
    if sp.get("make"):
        p.append(r"(?P<key>^[A-Za-z_][\w.-]*(?=\s*:))")
    # ---- strings ----
    st = []
    if sp.get("triple"):
        st += [r'"""(?:\\.|[^\\])*?"""', r"'''(?:\\.|[^\\])*?'''"]
    if sp.get("template"):
        st += [r"`(?:\\.|[^`\\])*`"]
    st += [r'"(?:\\.|[^"\\\n])*"', r"'(?:\\.|[^'\\\n])*'"]
    p.append(r"(?P<string>%s)" % "|".join(st))
    # ---- markup ----
    if sp.get("markup"):
        p.append(r"(?P<tagname></?[A-Za-z][\w:.-]*)")
        p.append(r"(?P<attrname>[A-Za-z_:@#\[\(][\w:.\-\)\]]*)(?=\s*=)")
    if sp.get("css"):
        p.append(r"(?P<attrname>[-A-Za-z]+)(?=\s*:)")
        p.append(r"(?P<tagname>[.#][A-Za-z_][\w-]*|@[a-z-]+|:{1,2}[a-z-]+)")
        p.append(r"(?P<number>-?\d*\.?\d+(?:px|em|rem|%|vh|vw|s|ms|pt|fr|deg)?|\#[0-9a-fA-F]{3,8})")
    if sp.get("preproc"):
        p.append(r"(?P<preproc>^[ \t]*\#[a-z_]+)")
    if sp.get("annot") or sp.get("decorator"):
        p.append(r"(?P<decorator>@[\w.]+)")
    if sp.get("variable"):
        p.append(r"(?P<variable>\$\{?[A-Za-z_]\w*\}?)")
    if sp.get("symbol"):
        p.append(r"(?P<symbol>:[A-Za-z_]\w*)")
    if sp.get("dockerfile"):
        p.append(r"(?P<keyword>^\s*(?:FROM|RUN|CMD|LABEL|EXPOSE|ENV|ADD|COPY|ENTRYPOINT|VOLUME|USER|WORKDIR|ARG|ONBUILD|STOPSIGNAL|HEALTHCHECK|SHELL|AS)\b)")
    # ---- numbers ----
    if not sp.get("css"):
        p.append(r"(?P<number>\b0[xXbBoO][0-9a-fA-F_]+\b|\b\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?\b)")
    # ---- keywords / builtins ----
    kw = KW.get(lang)
    if kw:
        if sp.get("ci_keywords"):      # scoped flag: (?i) must not be mid-pattern
            p.append(r"(?P<keyword>\b(?i:%s)\b)" % _words(kw))
        else:
            p.append(r"(?P<keyword>\b(?:%s)\b)" % _words(kw))
    bi = BUILTINS.get(lang)
    if bi:
        p.append(r"(?P<builtin>\b(?:%s)\b)" % _words(bi))
    # ---- declarations & calls ----
    p.append(r"(?P<clsname>(?<=\bclass\s)[A-Za-z_]\w*|(?<=\bstruct\s)[A-Za-z_]\w*|(?<=\binterface\s)[A-Za-z_]\w*)")
    if not sp.get("md") and not sp.get("markup"):
        p.append(r"(?P<funcall>\b[A-Za-z_]\w*(?=\s*\())")
    rx = re.compile("|".join(p), re.M)
    _CACHE[lang] = rx
    return rx

def lang_for(filename):
    base = filename.lower()
    if base in FILENAME_LANG:
        return FILENAME_LANG[base]
    if "." in base:
        return LANG_BY_EXT.get(base.rsplit(".", 1)[-1])
    return None


GUIDE_COLOR = "#3a3a42"          # recomputed on every theme change


def _tag_colors():
    """Editor tag -> colour, rebuilt whenever the theme changes."""
    return {"keyword": C["kw"], "builtin": C["cls"], "string": C["str"],
            "comment": C["com"], "number": C["num"], "funcall": C["fn"],
            "decorator": C["dec"], "clsname": C["cls"],
            # markup / config token kinds
            "tagname": C["kw"], "attrname": C["fn"], "key": C["cls"]}


TAG_COLOR = _tag_colors()


def _refresh_guide_color():
    """Subtle guide colour derived from the active theme."""
    global GUIDE_COLOR
    try:
        GUIDE_COLOR = mix(C["fg_faint"], C["sidebar"], 0.62)
    except NameError:          # called before the motion helpers exist
        GUIDE_COLOR = C.get("border_hi", "#3a3a42")


# Python word lists reused by the autocomplete engine
PY_KEYWORDS = KW["python"].split()
PY_BUILTINS = BUILTINS["python"].split()


def _human_size(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n / 1:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


# bytes that legitimately appear in text files
_TEXT_BYTES = bytes({7, 8, 9, 10, 12, 13, 27}
                    | set(range(0x20, 0x7F)) | set(range(0x80, 0x100)))


def _looks_binary(raw, sniff=8192):
    """True if the data should not be shown in a text editor.

    A NUL anywhere in the sample is decisive; otherwise fall back on the
    proportion of control bytes, which catches formats such as JPEG that
    can begin without a NUL.
    """
    if not raw:
        return False
    chunk = raw[:sniff]
    if b"\x00" in chunk:
        return True
    if chunk.startswith((b"\x89PNG", b"GIF8", b"\xff\xd8\xff", b"%PDF",
                         b"PK\x03\x04", b"\x7fELF", b"MZ", b"RIFF",
                         b"\x1f\x8b", b"BM", b"OggS", b"fLaC")):
        return True
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        nontext = sum(1 for b in chunk if b not in _TEXT_BYTES)
        return nontext / len(chunk) > 0.10
    return False


# ------------------------------------------------------------------ #
#  File-type icons (drawn at runtime; no image assets needed)         #
# ------------------------------------------------------------------ #
# ------------------------------------------------------------------ #
#  3x5 pixel font                                                     #
# ------------------------------------------------------------------ #
GLYPHS = {
    "A": "###|#.#|###|#.#|#.#", "B": "##.|#.#|##.|#.#|##.",
    "C": "###|#..|#..|#..|###", "D": "##.|#.#|#.#|#.#|##.",
    "E": "###|#..|##.|#..|###", "F": "###|#..|##.|#..|#..",
    "G": "###|#..|#.#|#.#|###", "H": "#.#|#.#|###|#.#|#.#",
    "I": "###|.#.|.#.|.#.|###", "J": "..#|..#|..#|#.#|###",
    "K": "#.#|#.#|##.|#.#|#.#", "L": "#..|#..|#..|#..|###",
    "M": "#...#|##.##|#.#.#|#...#|#...#", "N": "#..#|##.#|#.##|#..#|#..#",
    "O": "###|#.#|#.#|#.#|###", "P": "###|#.#|###|#..|#..",
    "Q": "###|#.#|#.#|###|..#", "R": "###|#.#|##.|#.#|#.#",
    "S": "###|#..|###|..#|###", "T": "###|.#.|.#.|.#.|.#.",
    "U": "#.#|#.#|#.#|#.#|###", "V": "#.#|#.#|#.#|#.#|.#.",
    "W": "#...#|#...#|#.#.#|##.##|#...#", "X": "#.#|#.#|.#.|#.#|#.#",
    "Y": "#.#|#.#|.#.|.#.|.#.", "Z": "###|..#|.#.|#..|###",
    "0": "###|#.#|#.#|#.#|###", "1": ".#.|##.|.#.|.#.|###",
    "2": "###|..#|###|#..|###", "3": "###|..#|###|..#|###",
    "4": "#.#|#.#|###|..#|..#", "5": "###|#..|###|..#|###",
    "6": "###|#..|###|#.#|###", "7": "###|..#|..#|..#|..#",
    "8": "###|#.#|###|#.#|###", "9": "###|#.#|###|..#|###",
    "+": "...|.#.|###|.#.|...", "#": "#.#|###|#.#|###|#.#",
    "-": "...|...|###|...|...", ".": "...|...|...|...|.#.",
}

# ------------------------------------------------------------------ #
#  Per-extension colour + monogram                                    #
# ------------------------------------------------------------------ #
# (colour, monogram)
SPEC = {
    # web
    "js": ("#f1e05a", "JS"), "mjs": ("#f1e05a", "JS"),
    "cjs": ("#f1e05a", "JS"), "jsx": ("#61dafb", "JSX"),
    "ts": ("#3178c6", "TS"), "tsx": ("#3178c6", "TSX"),
    "mts": ("#3178c6", "TS"), "cts": ("#3178c6", "TS"),
    "html": ("#e34c26", "HTM"), "htm": ("#e34c26", "HTM"),
    "xhtml": ("#e34c26", "HTM"),
    "css": ("#563d7c", "CSS"), "scss": ("#c6538c", "SCS"),
    "sass": ("#c6538c", "SAS"), "less": ("#1d365d", "LES"),
    "vue": ("#41b883", "VUE"), "svelte": ("#ff3e00", "SVT"),
    "astro": ("#ff5d01", "AST"),
    # python & friends
    "py": ("#3572A5", "PY"), "pyi": ("#3572A5", "PY"),
    "pyw": ("#3572A5", "PY"), "ipynb": ("#f37726", "IPY"),
    # systems
    "c": ("#649ad2", "C"), "h": ("#649ad2", "H"),
    "cpp": ("#f34b7d", "CPP"), "cc": ("#f34b7d", "CPP"),
    "cxx": ("#f34b7d", "CPP"), "hpp": ("#f34b7d", "HPP"),
    "rs": ("#dea584", "RS"), "go": ("#00add8", "GO"),
    "swift": ("#f05138", "SFT"), "zig": ("#f7a41d", "ZIG"),
    # jvm / .net
    "java": ("#b07219", "JAV"), "kt": ("#a97bff", "KT"),
    "kts": ("#a97bff", "KT"), "cs": ("#68217a", "CS"),
    "scala": ("#c22d40", "SCL"), "groovy": ("#4298b8", "GRV"),
    # scripting
    "rb": ("#cc342d", "RB"), "php": ("#4f5d95", "PHP"),
    "lua": ("#000080", "LUA"), "pl": ("#0298c3", "PL"),
    "r": ("#198ce7", "R"), "dart": ("#00b4ab", "DRT"),
    "sh": ("#89e051", "SH"), "bash": ("#89e051", "SH"),
    "zsh": ("#89e051", "SH"), "fish": ("#89e051", "SH"),
    "ps1": ("#012456", "PS"), "bat": ("#c1f12e", "BAT"),
    "cmd": ("#c1f12e", "CMD"),
    # data / config
    "json": ("#cbcb41", "JSN"), "jsonc": ("#cbcb41", "JSN"),
    "yml": ("#cb171e", "YML"), "yaml": ("#cb171e", "YML"),
    "toml": ("#9c4221", "TML"), "ini": ("#6b8e23", "INI"),
    "cfg": ("#6b8e23", "CFG"), "conf": ("#6b8e23", "CNF"),
    "env": ("#edd812", "ENV"), "properties": ("#6b8e23", "PRP"),
    "xml": ("#e37933", "XML"), "csv": ("#237346", "CSV"),
    "tsv": ("#237346", "TSV"), "sql": ("#e38c00", "SQL"),
    "db": ("#e38c00", "DB"), "sqlite": ("#e38c00", "DB"),
    "graphql": ("#e10098", "GQL"), "proto": ("#4285f4", "PRT"),
    # docs
    "md": ("#519aba", "MD"), "markdown": ("#519aba", "MD"),
    "mdx": ("#519aba", "MDX"), "rst": ("#519aba", "RST"),
    "txt": ("#9aa0a6", "TXT"), "log": ("#8d8d8d", "LOG"),
    "tex": ("#3d6117", "TEX"),
    # build / tooling
    "dockerfile": ("#2496ed", "DK"), "mk": ("#6d8086", "MK"),
    "makefile": ("#6d8086", "MK"), "cmake": ("#064f8c", "CMK"),
    "gradle": ("#02303a", "GRD"), "lock": ("#6b6b6b", "LCK"),
    "gitignore": ("#f14e32", "GIT"), "gitattributes": ("#f14e32", "GIT"),
    "editorconfig": ("#6b6b6b", "EC"),
}

# categories that get a bespoke glyph instead of a monogram
IMAGE_EXT = {"png", "jpg", "jpeg", "jpe", "jfif", "gif", "bmp", "dib",
             "tga", "webp", "tif", "tiff", "ico", "avif", "heic", "heif",
             "ppm", "pgm", "pbm", "pnm", "jp2", "psd", "xcf", "svg", "svgz"}
ARCHIVE_EXT = {"zip", "tar", "gz", "tgz", "bz2", "xz", "7z", "rar", "jar",
               "war", "whl", "deb", "rpm", "dmg", "iso"}
AUDIO_EXT = {"mp3", "wav", "ogg", "flac", "aac", "m4a", "opus", "aiff", "mid"}
VIDEO_EXT = {"mp4", "mkv", "mov", "avi", "webm", "wmv", "flv", "m4v"}
FONT_EXT = {"ttf", "otf", "woff", "woff2", "eot"}
BINARY_EXT = {"exe", "dll", "so", "dylib", "bin", "o", "a", "class", "pyc",
              "wasm"}

CAT_COLOR = {
    "image": "#26a69a", "archive": "#c9a227", "audio": "#8e6bd6",
    "video": "#d16ba5", "font": "#7e8ba3", "binary": "#7a7a7a",
    "pdf": "#e5252a", "folder": "#7aa2d2", "default": "#9aa0a6",
}

# filenames without a useful extension
BY_NAME = {
    "dockerfile": "dockerfile", "makefile": "makefile",
    "cmakelists.txt": "cmake", "gemfile": "rb", "rakefile": "rb",
    "vagrantfile": "rb", "procfile": "txt", "license": "txt",
    "licence": "txt", "readme": "md", "changelog": "md",
    ".gitignore": "gitignore", ".gitattributes": "gitattributes",
    ".env": "env", ".editorconfig": "editorconfig",
    ".bashrc": "sh", ".zshrc": "sh", ".profile": "sh",
    "package.json": "json", "tsconfig.json": "json",
}


def category(ext):
    if ext == "pdf":
        return "pdf"
    if ext in IMAGE_EXT:
        return "image"
    if ext in ARCHIVE_EXT:
        return "archive"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in VIDEO_EXT:
        return "video"
    if ext in FONT_EXT:
        return "font"
    if ext in BINARY_EXT:
        return "binary"
    return "code" if ext in SPEC else "default"


def key_for(filename):
    """Extension (or pseudo-extension) used to pick an icon."""
    low = filename.lower()
    if low in BY_NAME:
        return BY_NAME[low]
    stem = low.rsplit(".", 1)
    if low.startswith(".") and len(stem) == 1:
        return "cfg"
    if len(stem) == 2:
        ext = stem[1]
        if stem[0] in ("readme", "changelog", "license") and ext in ("md", "txt"):
            return ext
        return ext
    return ""


def _shade(color, factor):
    """Lighten (factor>1) or darken (factor<1) a #rrggbb colour."""
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    f = lambda v: max(0, min(255, int(v * factor)))  # noqa: E731
    return "#%02x%02x%02x" % (f(r), f(g), f(b))


def _lum(color):
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def _text(img, s, x, y, scale, color):
    """Draw a monogram. Glyphs are variable width, so N/M/W stay legible."""
    for ch in s:
        rows = GLYPHS.get(ch)
        if not rows:
            x += 4 * scale
            continue
        cells = rows.split("|")
        gw = len(cells[0])
        for ry, row in enumerate(cells):
            run = 0
            for rx, cell in enumerate(row):
                if cell == "#":
                    run += 1
                    continue
                if run:
                    img.put(color, to=(x + (rx - run) * scale,
                                       y + ry * scale,
                                       x + rx * scale,
                                       y + (ry + 1) * scale))
                    run = 0
            if run:
                img.put(color, to=(x + (gw - run) * scale, y + ry * scale,
                                   x + gw * scale, y + (ry + 1) * scale))
        x += (gw + 1) * scale


def _glyph_w(ch):
    rows = GLYPHS.get(ch)
    return len(rows.split("|")[0]) if rows else 3


def _text_width(s, scale):
    if not s:
        return 0
    return (sum(_glyph_w(c) for c in s) + len(s) - 1) * scale


def _page(img, w, h, color):
    """Document silhouette with a folded top-right corner."""
    fold = max(3, w // 4)
    left, right = max(1, w // 8), w - max(1, w // 8)
    top, bottom = 0, h
    body = color
    # main body below the fold line
    img.put(body, to=(left, top + fold, right, bottom))
    # top band, narrower where the fold is cut away
    img.put(body, to=(left, top, right - fold, top + fold))
    # diagonal of the fold
    for i in range(fold):
        img.put(body, to=(right - fold, top + fold - 1 - i,
                          right - fold + i + 1, top + fold - i))
    # the folded triangle itself, lighter
    hi = _shade(color, 1.45)
    for i in range(fold - 1):
        img.put(hi, to=(right - fold + i + 1, top + i + 1,
                        right, top + i + 2))
    return left, top + fold, right, bottom


def _mountain(img, x0, y0, x1, y1, ink, s):
    """Two peaks and a sun - the universal 'picture' glyph."""
    pad = max(1, int(round(1.5 * s)))
    left, right = x0 + pad, x1 - pad
    base = y1 - max(1, int(round(2 * s)))
    # big peak, right of centre
    h1 = max(3, int(round(5 * s)))
    apex = left + int((right - left) * 0.58)
    for i in range(h1):
        img.put(ink, to=(max(left, apex - i), base - h1 + i,
                         min(right, apex + i + 1), base - h1 + i + 1))
    # smaller peak on the left
    h2 = max(2, int(round(3 * s)))
    apex2 = left + int((right - left) * 0.22)
    for i in range(h2):
        img.put(ink, to=(max(left, apex2 - i), base - h2 + i,
                         min(right, apex2 + i + 1), base - h2 + i + 1))
    # ground line
    img.put(ink, to=(left, base, right, base + max(1, int(round(s)))))
    # sun
    r = max(1, int(round(1.4 * s)))
    img.put(ink, to=(right - 2 * r, y0 + max(1, int(round(1.2 * s))),
                     right, y0 + max(1, int(round(1.2 * s))) + 2 * r))


def _play(img, x0, y0, x1, y1, ink, s):
    """Right-pointing play triangle."""
    h = max(5, int(round(8 * s)))
    if h % 2 == 0:
        h += 1
    w = max(3, int(round(5 * s)))
    cx = (x0 + x1) // 2 - w // 2
    cy = (y0 + y1) // 2 - h // 2
    half = (h - 1) // 2
    for i in range(h):
        run = half - abs(i - half)
        width = max(1, int(round(w * (run + 1) / (half + 1))))
        img.put(ink, to=(cx, cy + i, cx + width, cy + i + 1))


def _note(img, x0, y0, x1, y1, ink, s):
    """Quaver: stem, flag and note head."""
    stem_w = max(1, int(round(1.4 * s)))
    top = y0 + max(1, int(round(1.5 * s)))
    bottom = y1 - max(2, int(round(3 * s)))
    cx = (x0 + x1) // 2 + max(1, int(round(s)))
    img.put(ink, to=(cx, top, cx + stem_w, bottom))
    # flag
    fw = max(2, int(round(3 * s)))
    img.put(ink, to=(cx + stem_w, top, cx + stem_w + fw,
                     top + max(1, int(round(1.6 * s)))))
    # head
    r = max(2, int(round(2.6 * s)))
    img.put(ink, to=(cx - r, bottom - max(1, int(round(s))),
                     cx + stem_w, bottom - max(1, int(round(s))) + r))


# ------------------------------------------------------------------ #
#  Git-status badges (amber "M" / green "C"), composited to the left  #
#  of a file/folder's normal icon in the Explorer tree.               #
# ------------------------------------------------------------------ #
# Tiny hand-drawn 5x7 bitmap glyphs, in the same pixel-primitive spirit
# as the rest of this module's icon drawing (no font rendering needed
# for just two letters).
BADGE_GLYPHS = {
    "M": ("1...1",
         "11.11",
         "1.1.1",
         "1...1",
         "1...1",
         "1...1",
         "1...1"),
    "C": (".111.",
         "1...1",
         "1....",
         "1....",
         "1....",
         "1...1",
         ".111."),
}
# (badge background, glyph ink)
BADGE_COLORS = {
    "M": ("#d7a23c", "#241a00"),   # amber -- modified
    "C": ("#49b870", "#04190c"),   # green  -- created
}


def build_badge_icon(tk, base_img, code, size):
    """A composite PhotoImage: a small colored "checkbox" with `code`'s
    letter (M/C) drawn in it, a gap, then `base_img` (the file/folder's
    normal icon) -- i.e. exactly `base_img` with a status badge stuck on
    its left, as one single image (ttk.Treeview items only take one)."""
    bg, ink = BADGE_COLORS.get(code, ("#888888", "#000000"))
    badge = max(10, int(round(size * 0.74)))
    gap = max(2, int(round(size * 0.16)))
    total_w = badge + gap + size
    out = tk.PhotoImage(width=total_w, height=size)
    top = max(0, (size - badge) // 2)
    out.put(bg, to=(0, top, badge, top + badge))
    glyph = BADGE_GLYPHS.get(code)
    if glyph:
        rows, cols = len(glyph), len(glyph[0])
        cell = max(1, badge // (cols + 2))
        gw, gh = cell * cols, cell * rows
        ox = (badge - gw) // 2
        oy = top + (badge - gh) // 2
        for r, row in enumerate(glyph):
            for c, ch in enumerate(row):
                if ch == "1":
                    x0, y0 = ox + c * cell, oy + r * cell
                    out.put(ink, to=(x0, y0, x0 + cell, y0 + cell))
    try:
        out.tk.call(out.name, "copy", base_img.name, "-to", badge + gap, 0)
    except Exception:  # noqa: BLE001
        pass
    return out


def build_icon(tk, filename, size=16, is_dir=False, is_open=False):
    """Return a PhotoImage for this file or folder."""
    img = tk.PhotoImage(width=size, height=size)   # starts transparent
    s = size / 16.0

    if is_dir:
        col = CAT_COLOR["folder"]
        top = max(2, int(round(3 * s)))
        tab_h = max(2, int(round(3.5 * s)))
        bot = size - max(2, int(round(2.5 * s)))
        # tab
        img.put(_shade(col, 0.78), to=(1, top, int(size * 0.5), top + tab_h))
        if is_open:
            # back panel, then a lighter front flap sitting proud of it
            img.put(_shade(col, 0.78),
                    to=(1, top + tab_h - 1, size - 1, bot))
            img.put(_shade(col, 1.15),
                    to=(max(2, int(round(2 * s))), top + tab_h + max(1, int(s)),
                        size - 1, bot))
        else:
            img.put(col, to=(1, top + tab_h - 1, size - 1, bot))
            img.put(_shade(col, 1.12),
                    to=(1, top + tab_h - 1, size - 1,
                        top + tab_h + max(1, int(round(s)))))
        return img

    ext = key_for(filename)
    cat = category(ext)
    if cat == "code" or cat == "default":
        color = SPEC.get(ext, (CAT_COLOR["default"], ""))[0]
    else:
        color = CAT_COLOR[cat]

    x0, y0, x1, y1 = _page(img, size, size, color)
    ink = "#ffffff" if _lum(color) < 0.62 else "#1d1d1d"

    if cat == "image":
        _mountain(img, x0, y0, x1, y1, ink, s)
        return img

    if cat == "archive":
        cx = (x0 + x1) // 2
        wdt = max(1, int(round(1.2 * s)))
        step = max(3, int(round(4 * s)))
        yy = y0 + max(1, int(s))
        while yy < y1 - max(2, int(2 * s)):
            img.put(ink, to=(cx - wdt, yy, cx + wdt,
                             yy + max(1, int(round(1.6 * s)))))
            yy += step
        return img

    if cat == "audio":
        _note(img, x0, y0, x1, y1, ink, s)
        return img

    if cat == "video":
        _play(img, x0, y0, x1, y1, ink, s)
        return img

    if cat == "font":
        lab, sc = "F", max(1, int(round(2 * s)))
        _text(img, lab, (x0 + x1) // 2 - _text_width(lab, sc) // 2,
              (y0 + y1) // 2 - (5 * sc) // 2, sc, ink)
        return img

    if cat == "pdf":
        lab = "PDF"
    elif cat == "binary":
        lab = "BIN"
    else:
        lab = SPEC.get(ext, ("", ext[:3].upper()))[1] or ext[:3].upper()

    lab = "".join(c for c in lab if c in GLYPHS)[:3]
    if not lab:
        return img
    sc = 1
    while _text_width(lab, sc + 1) <= (x1 - x0) - 2 and (5 * (sc + 1)) <= (y1 - y0) - 2:
        sc += 1
    tx = x0 + ((x1 - x0) - _text_width(lab, sc)) // 2
    ty = y0 + ((y1 - y0) - 5 * sc) // 2
    _text(img, lab, tx, ty, sc, ink)
    return img


# Pure-Python BMP/TGA/JPEG/PDF decoding -- split out into its own file
# (media_codecs.py) purely to keep this one a manageable size; see that
# module's own docstring. Imported with every name's exact original
# spelling so everything below (and anything reaching for
# `ide.decode_jpeg`, `ide.pdf_render_page`, etc.) keeps working
# unchanged.
from media_codecs import (  # noqa: E402
    DecodeError, decode_bmp, decode_tga, decode_jpeg, to_ppm,
    pdf_find_renderer, pdf_render_page, pdf_page_count, pdf_version,
    pdf_is_encrypted, pdf_metadata, pdf_extract_text, pdf_summary,
    IMAGE_EXTS, load_image, _jpeg_size, _image_converter,
    _tk_photo_from_rgb, _cleanup_temp_dirs, _TEMP_DIRS, _PDF_WORKING,
)


# ------------------------------------------------------------------ #
#  Workspace filesystem (sandboxed; also the agent-facing API)        #
# ------------------------------------------------------------------ #
class WorkspaceFS:
    """File operations confined to the open workspace folder.

    Every path is resolved and checked against the workspace root, so a
    caller - including an AI agent - cannot touch anything outside it.
    Disk work happens on the calling thread; UI refreshes are marshalled
    onto the Tk main thread, so these methods are safe to call from a
    background thread.
    """

    def __init__(self, app):
        self.app = app

    # ---- internals ----
    @property
    def root(self):
        return os.path.abspath(self.app.root_dir)

    def resolve(self, path):
        p = path if os.path.isabs(path) else os.path.join(self.root, path)
        p = os.path.abspath(p)
        root = self.root
        if p != root and not p.startswith(root + os.sep):
            raise PermissionError(
                f"path escapes the workspace: {path}")
        return p

    def _sync(self):
        """Refresh tree + quick-open index on the main thread."""
        def do():
            try:
                self.app.refresh_explorer()
                self.app._index_workspace()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.app.after(0, do)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _unique(path):
        if not os.path.exists(path):
            return path
        stem, ext = os.path.splitext(path)
        i = 1
        while os.path.exists(f"{stem} copy{'' if i == 1 else ' ' + str(i)}{ext}"):
            i += 1
        return f"{stem} copy{'' if i == 1 else ' ' + str(i)}{ext}"

    # ---- queries ----
    def exists(self, path):
        return os.path.exists(self.resolve(path))

    def is_dir(self, path):
        return os.path.isdir(self.resolve(path))

    def list(self, path="."):
        p = self.resolve(path)
        return sorted(os.listdir(p)) if os.path.isdir(p) else []

    def tree(self, path=".", max_entries=2000):
        """Recursive listing of workspace-relative file paths."""
        base = self.resolve(path)
        out = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                out.append(os.path.relpath(os.path.join(dirpath, f), self.root))
                if len(out) >= max_entries:
                    return out
        return out

    def read(self, path):
        with open(self.resolve(path), encoding="utf-8", errors="replace") as fh:
            return fh.read()

    # ---- mutations ----
    def write(self, path, content, create_dirs=True, agent=False):
        p = self.resolve(path)
        if create_dirs:
            os.makedirs(os.path.dirname(p) or self.root, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        if agent:
            # Registered synchronously, right here, on whatever thread
            # called write() -- the disk write above already finished,
            # so this must be visible immediately, before the Tk-thread
            # animation has even been scheduled, let alone started.
            self.app._pending_agent_writes[os.path.normpath(p)] = content
            self.app.after(0, lambda: self.app.animate_agent_write_file(
                p, content))
        else:
            self._sync()
        return p

    def create_file(self, path, content="", overwrite=False, agent=False):
        p = self.resolve(path)
        if os.path.exists(p) and not overwrite:
            raise FileExistsError(p)
        os.makedirs(os.path.dirname(p) or self.root, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        if agent:
            self.app._pending_agent_writes[os.path.normpath(p)] = content
            self.app.after(0, lambda: self.app.animate_agent_create(
                p, content))
        else:
            self._sync()
        return p

    def create_folder(self, path, agent=False):
        p = self.resolve(path)
        os.makedirs(p, exist_ok=True)
        if agent:
            self.app.after(0, lambda: self.app.animate_agent_create(
                p, is_folder=True))
        else:
            self._sync()
        return p

    def delete(self, path):
        p = self.resolve(path)
        if p == self.root:
            raise PermissionError("refusing to delete the workspace root")
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
        try:
            self.app.after(0, lambda: self.app._forget_paths(p))
        except Exception:  # noqa: BLE001
            pass
        self._sync()
        return p

    def _ensure_trash_gitignored(self):
        """Make sure `.friday_trash/` is listed in the workspace's root
        .gitignore, so ide_git_add's default "git add -A" never sweeps a
        deleted file's content back into a commit -- that would silently
        defeat the entire point of a recoverable trash folder. Creates
        .gitignore if it doesn't exist yet; appends the line only if it
        isn't already present (idempotent, safe to call on every trash()).
        Best-effort: a failure here must never block the actual deletion.
        """
        try:
            gi_path = os.path.join(self.root, ".gitignore")
            existing = ""
            if os.path.exists(gi_path):
                with open(gi_path, encoding="utf-8", errors="replace") as fh:
                    existing = fh.read()
            if FRIDAY_TRASH_DIR in existing:
                return
            with open(gi_path, "a", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(f"{FRIDAY_TRASH_DIR}/\n")
        except Exception:  # noqa: BLE001
            pass

    def trash(self, path, allow_folder=False):
        """Move a file (or, with allow_folder=True, a whole folder) into
        the recoverable `.friday_trash` folder instead of permanently
        deleting it.

        This is the only deletion path ever exposed to the agent (see
        agent_tools.py: ide_analyze_file_for_deletion/ide_delete_file and
        ide_analyze_folder_for_deletion/ide_delete_folder). The human-
        driven right-click "Delete" in the UI still calls delete() above
        and removes the file for real after its own confirm dialog --
        that is unchanged and stays human-only. This method is
        deliberately non-destructive: the file/folder is moved,
        timestamped, under <workspace_root>/.friday_trash/ with its
        relative path folded into the name, so a wrong agent deletion can
        always be undone by moving it back out by hand. `.friday_trash`
        is skipped everywhere else (explorer, search, workspace tree, git
        tools) via SKIP_DIRS, so it never clutters the project.

        allow_folder defaults to False -- a plain trash(path) call still
        refuses a directory exactly like before, so nothing outside the
        one new, deliberate agent folder-deletion tool can ever trash a
        whole folder by accident. Infrastructure folders (.git,
        node_modules, venvs, build/cache output -- anything already in
        SKIP_DIRS) are refused even with allow_folder=True: those are
        regenerable/critical project plumbing, never the kind of "dead
        code left lying around" cleanup this is for.
        """
        p = self.resolve(path)
        if p == self.root:
            raise PermissionError("refusing to delete the workspace root")
        if not os.path.exists(p):
            raise FileNotFoundError(p)
        is_dir = os.path.isdir(p)
        if is_dir and not allow_folder:
            raise IsADirectoryError(
                "Friday can only delete individual files, not whole "
                "folders, through this call")
        if is_dir and os.path.basename(p.rstrip(os.sep)) in SKIP_DIRS:
            raise PermissionError(
                f"refusing to delete '{os.path.basename(p)}' -- that's "
                f"project infrastructure (version control/dependencies/"
                f"build output), not dead code to clean up")
        trash_root = os.path.join(self.root, FRIDAY_TRASH_DIR)
        os.makedirs(trash_root, exist_ok=True)
        self._ensure_trash_gitignored()
        rel = os.path.relpath(p, self.root)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe_name = rel.replace(os.sep, "__").replace("/", "__")
        dest = os.path.join(trash_root, f"{stamp}__{safe_name}")
        # Extremely unlikely collision (same file trashed twice inside the
        # same second) -- disambiguate rather than overwrite a previous
        # trash entry.
        n = 1
        base_dest = dest
        while os.path.exists(dest):
            dest = f"{base_dest}.{n}"
            n += 1
        shutil.move(p, dest)
        try:
            self.app.after(0, lambda: self.app._forget_paths(p))
        except Exception:  # noqa: BLE001
            pass
        self._sync()
        return dest


    def rename(self, path, new_name):
        p = self.resolve(path)
        if os.sep in new_name or (os.altsep and os.altsep in new_name):
            dst = self.resolve(new_name)
        else:
            dst = os.path.join(os.path.dirname(p), new_name)
            dst = self.resolve(dst)
        if os.path.exists(dst):
            raise FileExistsError(dst)
        os.rename(p, dst)
        try:
            self.app.after(0, lambda: self.app._repath(p, dst))
        except Exception:  # noqa: BLE001
            pass
        self._sync()
        return dst

    def copy(self, src, dst_dir=None, dst=None):
        s_ = self.resolve(src)
        target = (self.resolve(dst) if dst else
                  os.path.join(self.resolve(dst_dir or "."),
                               os.path.basename(s_)))
        target = self._unique(self.resolve(target))
        if os.path.isdir(s_):
            shutil.copytree(s_, target)
        else:
            shutil.copy2(s_, target)
        self._sync()
        return target

    def move(self, src, dst_dir):
        s_ = self.resolve(src)
        target = os.path.join(self.resolve(dst_dir), os.path.basename(s_))
        target = self.resolve(target)
        if os.path.exists(target):
            raise FileExistsError(target)
        shutil.move(s_, target)
        try:
            self.app.after(0, lambda: self.app._repath(s_, target))
        except Exception:  # noqa: BLE001
            pass
        self._sync()
        return target

    def edit(self, path, old_text, new_text, agent=False):
        """Replace the first occurrence of `old_text` with `new_text` in
        an existing file. Raises ValueError if `old_text` isn't found."""
        current = self.read(path)
        if old_text not in current:
            raise ValueError("old_text not found in file")
        updated = current.replace(old_text, new_text, 1)
        self.write(path, updated, agent=agent)
        return self.resolve(path)

    def search(self, query, scope=".", max_hits=200):
        """Plain-text, case-insensitive search across every file under
        `scope` (workspace-relative, defaults to the whole workspace).
        Returns a list of (workspace-relative path, 1-based line number,
        stripped line text) tuples -- the same logic the Search sidebar
        view uses, factored out here so it's also usable headlessly (no
        Tk widgets touched), e.g. from a background thread or an agent
        tool, with no risk of the two ever drifting apart."""
        base = self.resolve(scope)
        ql = query.lower()
        hits = []
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                p = os.path.join(dirpath, fn)
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                        for ln, line in enumerate(fh, 1):
                            if ql in line.lower():
                                hits.append((os.path.relpath(p, self.root),
                                            ln, line.strip()))
                                if len(hits) >= max_hits:
                                    return hits
                except OSError:
                    continue
        return hits


# ------------------------------------------------------------------ #
#  Friday drives this IDE directly, in-process -- no socket/subprocess   #
#  layer anymore (see agent_tools.py's ide_* tools and agent_host     #
#  below). Every file operation Friday can call is just a thin pass-     #
#  through to WorkspaceFS above, so it inherits the exact same        #
#  sandboxing (a path can never resolve outside the open workspace)   #
#  and the same "no delete" posture -- deletion is deliberately not   #
#  exposed to the agent anywhere.                                     #
# ------------------------------------------------------------------ #
# ------------------------------------------------------------------ #
#  Build / run task detection (all project types)                     #
# ------------------------------------------------------------------ #

RUN_BY_EXT = {
    "py":   '"{py}" -u "{file}"',
    "pyw":  '"{py}" -u "{file}"',
    "js":   'node "{file}"',
    "mjs":  'node "{file}"',
    "cjs":  'node "{file}"',
    "ts":   'npx --yes tsx "{file}"',
    "tsx":  'npx --yes tsx "{file}"',
    "sh":   'bash "{file}"',
    "bash": 'bash "{file}"',
    "zsh":  'zsh "{file}"',
    "rb":   'ruby "{file}"',
    "php":  'php "{file}"',
    "pl":   'perl "{file}"',
    "lua":  'lua "{file}"',
    "r":    'Rscript "{file}"',
    "go":   'go run "{file}"',
    "rs":   'rustc "{file}" -o "{tmp}" && "{tmp}"',
    "java": 'java "{file}"',
    "kt":   'kotlinc "{file}" -include-runtime -d "{tmp}.jar" && java -jar "{tmp}.jar"',
    "swift": 'swift "{file}"',
    "c":    'cc "{file}" -o "{tmp}" && "{tmp}"',
    "cpp":  'c++ "{file}" -o "{tmp}" && "{tmp}"',
    "cc":   'c++ "{file}" -o "{tmp}" && "{tmp}"',
    "cs":   'dotnet run',
    "html": '__OPEN_BROWSER__',
    "htm":  '__OPEN_BROWSER__',
}

def _pm(root):
    """Which node package manager this project uses."""
    if os.path.exists(os.path.join(root, "pnpm-lock.yaml")):
        return "pnpm"
    if os.path.exists(os.path.join(root, "yarn.lock")):
        return "yarn"
    if os.path.exists(os.path.join(root, "bun.lockb")):
        return "bun"
    return "npm"

def _has(root, *names):
    return any(os.path.exists(os.path.join(root, n)) for n in names)

def detect_project_tasks(root):
    """Every build/run task we can infer from the workspace root."""
    T = []
    def add(label, cmd, kind="run"):
        T.append({"label": label, "cmd": cmd, "cwd": root, "kind": kind})

    # ---------------- Node / web ----------------
    pj = os.path.join(root, "package.json")
    if os.path.exists(pj):
        pm = _pm(root)
        runner = f"{pm} run" if pm != "bun" else "bun run"
        try:
            data = json.load(open(pj, encoding="utf-8"))
        except Exception:
            data = {}
        scripts = data.get("scripts", {}) or {}
        order = ["dev", "start", "serve", "build", "preview", "test", "lint"]
        seen = []
        for name in order:
            if name in scripts:
                seen.append(name)
        for name in scripts:
            if name not in seen:
                seen.append(name)
        for name in seen:
            kind = ("build" if name in ("build", "compile", "dist")
                    else "test" if name in ("test", "lint") else "run")
            add(f"{pm}: {name}", f"{runner} {name}", kind)
        if not scripts:
            add(f"{pm}: install", f"{pm} install", "build")
        if not _has(root, "node_modules"):
            add(f"{pm}: install deps", f"{pm} install", "build")

    # ---------------- Python ----------------
    if _has(root, "manage.py"):
        add("Django: runserver", '"{py}" manage.py runserver', "run")
        add("Django: migrate", '"{py}" manage.py migrate', "build")
    for entry in ("main.py", "app.py", "run.py", "__main__.py", "server.py"):
        if os.path.exists(os.path.join(root, entry)):
            add(f"Python: {entry}", f'"{{py}}" -u {entry}', "run")
            break
    if _has(root, "pyproject.toml"):
        add("Python: build package", '"{py}" -m build', "build")
    if _has(root, "requirements.txt"):
        add("pip: install requirements",
            '"{py}" -m pip install -r requirements.txt', "build")
    if _has(root, "pytest.ini", "tox.ini") or _has(root, "tests"):
        add("pytest", '"{py}" -m pytest', "test")

    # ---------------- Go / Rust / Java / .NET ----------------
    if _has(root, "go.mod"):
        add("Go: run", "go run .", "run")
        add("Go: build", "go build ./...", "build")
        add("Go: test", "go test ./...", "test")
    if _has(root, "Cargo.toml"):
        add("Cargo: run", "cargo run", "run")
        add("Cargo: build", "cargo build --release", "build")
        add("Cargo: test", "cargo test", "test")
    if _has(root, "pom.xml"):
        add("Maven: compile", "mvn -q compile", "build")
        add("Maven: exec", "mvn -q exec:java", "run")
        add("Maven: package", "mvn -q package", "build")
    if _has(root, "build.gradle", "build.gradle.kts"):
        g = "./gradlew" if _has(root, "gradlew") else "gradle"
        add("Gradle: run", f"{g} run", "run")
        add("Gradle: build", f"{g} build", "build")
    for f in os.listdir(root) if os.path.isdir(root) else []:
        if f.endswith((".csproj", ".sln")):
            add("dotnet: run", "dotnet run", "run")
            add("dotnet: build", "dotnet build", "build")
            break

    # ---------------- Ruby / PHP ----------------
    if _has(root, "Gemfile"):
        add("Bundler: install", "bundle install", "build")
        if _has(root, "config.ru"):
            add("Rack: server", "bundle exec rackup", "run")
    if _has(root, "composer.json"):
        add("Composer: install", "composer install", "build")
        add("PHP: dev server", "php -S localhost:8000", "run")

    # ---------------- Make / CMake / Docker ----------------
    mk = os.path.join(root, "Makefile")
    if os.path.exists(mk):
        add("make", "make", "build")
        try:
            targets = re.findall(r"(?m)^([A-Za-z_][\w.-]*)\s*:(?!=)",
                                 open(mk, encoding="utf-8", errors="ignore").read())
            for t in list(dict.fromkeys(targets))[:8]:
                if t not in ("PHONY",):
                    add(f"make {t}", f"make {t}",
                        "run" if t in ("run", "start", "dev", "serve") else "build")
        except OSError:
            pass
    if _has(root, "CMakeLists.txt"):
        add("CMake: configure", "cmake -B build", "build")
        add("CMake: build", "cmake --build build", "build")
    if _has(root, "docker-compose.yml", "docker-compose.yaml", "compose.yaml"):
        add("Docker Compose: up", "docker compose up", "run")
    if _has(root, "Dockerfile"):
        add("Docker: build image",
            f"docker build -t {os.path.basename(root).lower()} .", "build")

    # ---------------- static site ----------------
    if _has(root, "index.html") and not os.path.exists(pj):
        add("Serve static site (:5500)",
            '"{py}" -m http.server 5500', "serve")
    return T

def detect_file_task(path, py=None):
    """How to run this one file."""
    if not path:
        return None
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    tpl = RUN_BY_EXT.get(ext)
    if not tpl:
        return None
    if tpl == "__OPEN_BROWSER__":
        return {"label": f"Open {os.path.basename(path)} in browser",
                "cmd": "__OPEN_BROWSER__", "cwd": os.path.dirname(path),
                "kind": "browser"}
    tmp = os.path.splitext(path)[0] + "_build"
    cmd = tpl.format(py=py or sys.executable, file=path, tmp=tmp)
    return {"label": f"Run {os.path.basename(path)}", "cmd": cmd,
            "cwd": os.path.dirname(path) or ".", "kind": "run"}

URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?[^\s\"'<>]*")
PORT_RE = re.compile(r"(?:port|listening on|running at|Local:)\D{0,20}(\d{4,5})", re.I)

def find_url(text):
    m = URL_RE.search(text)
    if m:
        return m.group(0).rstrip(".,)")
    m = PORT_RE.search(text)
    if m:
        return f"http://localhost:{m.group(1)}"
    return None


SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             ".idea", ".vscode", "dist", "build", ".mypy_cache",
             ".friday_trash"}

# Name of the recoverable-trash folder Friday moves agent-deleted files into
# (see WorkspaceFS.trash()) instead of ever permanently unlinking something
# itself. Kept as a constant so agent_tools.py and WorkspaceFS always agree
# on the same folder name.
FRIDAY_TRASH_DIR = ".friday_trash"

APP_NAME = "IDE"

# Global UI scale factor, set once the root window knows its DPI.
UI_SCALE = 1.0
DPI_AWARE = False


def _enable_dpi_awareness():
    """Tell Windows we paint our own pixels.

    Without this a Tk window on a scaled display (125%/150%/200%) is
    rendered at 96dpi and then bitmap-stretched by the OS, which is what
    makes text and icons look soft. Must run BEFORE the root window exists.
    """
    global DPI_AWARE
    if sys.platform != "win32":
        DPI_AWARE = True          # X11/Quartz hand us real pixels already
        return
    try:
        import ctypes
        # Per-Monitor-V2 (Win10 1703+) is the sharpest option
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(-4))
            DPI_AWARE = True
            return
        except Exception:  # noqa: BLE001
            pass
        try:                       # Win8.1+
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            DPI_AWARE = True
            return
        except Exception:  # noqa: BLE001
            pass
        ctypes.windll.user32.SetProcessDPIAware()   # Vista+
        DPI_AWARE = True
    except Exception:  # noqa: BLE001
        DPI_AWARE = False


_enable_dpi_awareness()

# ---- typography -----------------------------------------------------
EDITOR_FONT_SIZE = 12       # code editor 100% baseline, in points
UI_FONT_SIZE = 10           # menus / tabs / sidebar chrome

# Chrome font. The editor/terminal are always monospace (JetBrains Mono or
# a fallback); the surrounding chrome -- menus, tabs, sidebar, status bar,
# chat prose, dialogs -- uses a clean proportional UI face instead, which
# reads much more like a native desktop app and is easier to scan than an
# all-monospace interface. Set to False to go back to one face everywhere.
UI_FONT_PROPORTIONAL = True

# ------------------------------------------------------------------ #
#  Design tokens                                                      #
# ------------------------------------------------------------------ #
# One spacing scale, so padding is never ad hoc.
_SPACE = {"xs": 4, "sm": 6, "md": 10, "lg": 14, "xl": 20}


def sp(name):
    """Spacing step in device pixels."""
    return max(1, int(round(_SPACE.get(name, name) * UI_SCALE)))


def ts(step=0, bold=False):
    """Type scale: -1 small, 0 body, +1 heading."""
    size = max(7, UI_FONT_SIZE + step)
    return size, ("bold" if bold else "normal")


# Heights of the chrome bands, all derived from the same rhythm.
def band(units):
    return int(round(units * UI_SCALE))


MOTION_MS = 110             # hover / state transition duration
MOTION_STEPS = 6            # frames per transition; 0 disables animation


# ------------------------------------------------------------------ #
#  Motion helpers (Tk has no animation API, so interpolate by hand)   #
# ------------------------------------------------------------------ #
def _rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(t):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in t)


def mix(a, b, t):
    """Blend two colours; t=0 -> a, t=1 -> b."""
    try:
        ra, ga, ba = _rgb(a)
        rb, gb, bb = _rgb(b)
    except Exception:  # noqa: BLE001
        return b
    return _hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


_ANIM = {}


def animate_color(widget, option, to, ms=MOTION_MS, steps=MOTION_STEPS):
    """Ease a colour option toward `to`. Safe on destroyed widgets."""
    try:
        if not widget.winfo_exists():
            return
        start = str(widget.cget(option))
    except Exception:  # noqa: BLE001
        return
    key = (str(widget), option)
    job = _ANIM.pop(key, None)
    if job:
        try:
            widget.after_cancel(job)
        except Exception:  # noqa: BLE001
            pass
    if not steps or start == to:
        try:
            widget.configure(**{option: to})
        except Exception:  # noqa: BLE001
            pass
        return

    def frame(i=1):
        if not widget.winfo_exists():
            _ANIM.pop(key, None)
            return
        t = i / steps
        t = t * t * (3 - 2 * t)          # smoothstep
        try:
            widget.configure(**{option: mix(start, to, t)})
        except Exception:  # noqa: BLE001
            _ANIM.pop(key, None)
            return
        if i < steps:
            _ANIM[key] = widget.after(max(1, ms // steps), frame, i + 1)
        else:
            _ANIM.pop(key, None)
    frame()


# ------------------------------------------------------------------ #
#  Easing curves -- used by IDEApp._animate_geometry (the open/close   #
#  "pop" animation below). Each maps t in [0, 1] -> t' in roughly      #
#  [0, 1] (ease_out_back deliberately overshoots past 1 briefly,       #
#  that's the point of it) and always returns exactly 0 at t=0 and     #
#  exactly 1 at t=1, so whatever's being interpolated always lands     #
#  exactly on its target at the end no matter which curve is used.     #
# ------------------------------------------------------------------ #
def ease_in_out_cubic(t):
    """Smooth, symmetric accelerate-then-decelerate -- noticeably
    softer through the middle of the motion than a plain quadratic
    smoothstep, which tends to read as slightly flat/mechanical."""
    if t < 0.5:
        return 4 * t * t * t
    p = -2 * t + 2
    return 1 - (p ** 3) / 2


def ease_out_back(t, overshoot=1.3):
    """Decelerates past the target, then springs back to it -- the
    classic "something popping into existence" curve. Used for the
    IDE's open animation so growing out of the circle reads as a
    lively little emergence rather than a mechanical slide into
    place."""
    c3 = overshoot + 1
    t -= 1
    return 1 + c3 * t ** 3 + overshoot * t ** 2


def ease_in_cubic(t):
    """Accelerates smoothly from a standstill -- the natural reverse of
    ease_out_back: used for the IDE's close animation so it reads as
    gently, then increasingly, being drawn back into the circle."""
    return t * t * t


def hover_fx(widget, bg_from=None, bg_to=None, fg_from=None, fg_to=None,
             targets=None, enter_extra=None, leave_extra=None):
    """Animated hover state for a label/frame acting as a button."""
    group = list(targets) if targets else [widget]

    def enter(_e=None):
        for w in group:
            if bg_to is not None:
                animate_color(w, "bg", bg_to)
            if fg_to is not None and "fg" in w.keys():
                animate_color(w, "fg", fg_to)
        if enter_extra:
            enter_extra()

    def leave(_e=None):
        for w in group:
            if bg_from is not None:
                animate_color(w, "bg", bg_from)
            if fg_from is not None and "fg" in w.keys():
                animate_color(w, "fg", fg_from)
        if leave_extra:
            leave_extra()

    for w in group:
        w.bind("<Enter>", enter, add="+")
        w.bind("<Leave>", leave, add="+")
    return enter, leave


def animate_pane(paned, child, key, to, ms=150, steps=10, done=None):
    """Smoothly resize a PanedWindow child (sidebar / bottom panel)."""
    try:
        start = int(paned.paneconfigure(child)[key][-1])
    except Exception:  # noqa: BLE001
        start = 0

    def frame(i=1):
        try:
            if not paned.winfo_exists():
                return
            t = i / steps
            t = t * t * (3 - 2 * t)
            paned.paneconfigure(child, **{key: int(start + (to - start) * t)})
        except Exception:  # noqa: BLE001
            return
        if i < steps:
            paned.after(max(1, ms // steps), frame, i + 1)
        elif done:
            done()
    frame()


DEFAULT_ZOOM = 0.75         # editor opens at 75% (= 9pt), Ctrl+0 returns here
# Fully opaque by default so the IDE is readable over any desktop
# background/wallpaper. Opacity remains a live, user-adjustable setting
# (status bar "Opacity" chip / fade()) -- this only changes what it starts
# at on launch; it can still be lowered down to 45% afterwards.
DEFAULT_OPACITY = 1.0

# shown on the blank editor surface; set to "" for nothing at all
EMPTY_HINT = ("Ctrl+N  new file        "
              "Ctrl+P  go to file\n"
              "Ctrl+O  open file       "
              "Ctrl+Shift+P  commands")

# performance ceilings (large files stay responsive)
MAX_HIGHLIGHT_CHARS = 400_000   # skip syntax colouring above this
MAX_MINIMAP_CHARS = 400_000     # skip the minimap preview above this


def zoomed_pt(zoom=DEFAULT_ZOOM):
    """Point size for a zoom factor against the 12pt baseline."""
    return max(6, round(EDITOR_FONT_SIZE * zoom))

# ------------------------------------------------------------------ #
#  Icon drawing on canvases (vector-ish, always renders)              #
# ------------------------------------------------------------------ #
def draw_icon(cv, name, color=None, bg=None):
    """Draw a flat line icon and centre it inside its canvas.

    Shapes are authored in a 20x20 unit grid, then uniformly scaled to the
    canvas and centred on its true bounding box -- so an icon looks right
    on a large sidebar button and an 18px panel button alike, instead
    of being pinned to the top-left corner of a fixed 20px grid.
    """
    if color is None:
        color = C["fg"]          # follows the active theme
    cv.delete("icon")
    w = cv.winfo_reqwidth() or 20
    # shape outlines (rect/oval/arc/polygon) — no cap/join options allowed
    t = dict(tags="icon", outline=color, width=1.6)
    # line strokes accept cap/join styling
    ln = dict(tags="icon", fill=color, width=1.6,
              capstyle=tk.ROUND, joinstyle=tk.ROUND)
    fl = dict(tags="icon", fill=color, outline="")
    if name == "explorer":      # two overlapping documents
        cv.create_rectangle(3, 4, 11, 14, **t)
        cv.create_rectangle(5, 7, 15, 17, fill=bg or "", outline="")
        cv.create_rectangle(5, 7, 15, 17, **t)
    elif name == "search":      # magnifier
        cv.create_oval(3, 3, 13, 13, **t)
        cv.create_line(12, 12, 17.5, 17.5, **ln)
    elif name == "git":         # source control branch
        cv.create_oval(4.5, 2.5, 9.5, 7.5, **t)
        cv.create_oval(4.5, 12.5, 9.5, 17.5, **t)
        cv.create_oval(12.5, 6.5, 17.5, 11.5, **t)
        cv.create_line(7, 7.5, 7, 12.5, **ln)
        cv.create_line(7, 12.5, 15, 11.5, smooth=True, **ln)
    elif name == "run":         # play
        cv.create_polygon(6, 4, 6, 16, 16.5, 10, fill="", **t)
    elif name == "extensions":  # 3 squares + detached outline
        cv.create_rectangle(2.5, 2.5, 8.5, 8.5, **fl)
        cv.create_rectangle(2.5, 11.5, 8.5, 17.5, **fl)
        cv.create_rectangle(11.5, 11.5, 17.5, 17.5, **fl)
        cv.create_rectangle(13, 2, 19, 8, **t)
    elif name == "gear":
        cx, cy, r1, r2 = 10, 10, 4.6, 6.6
        import math
        pts = []
        for i in range(16):
            ang = math.pi * i / 8
            r = r2 if i % 2 == 0 else r1
            pts += [cx + r * math.cos(ang), cy + r * math.sin(ang)]
        cv.create_polygon(pts, fill="", **t)
        cv.create_oval(cx - 1.8, cy - 1.8, cx + 1.8, cy + 1.8, **t)
    elif name == "account":
        cv.create_oval(6.5, 2.5, 13.5, 9.5, **t)
        cv.create_arc(3, 9, 17, 23, start=10, extent=160, style="arc", **t)
    elif name == "close":
        cv.create_line(5.5, 5.5, 14.5, 14.5, **ln)
        cv.create_line(14.5, 5.5, 5.5, 14.5, **ln)
    elif name == "plus":
        cv.create_line(10, 4, 10, 16, **ln)
        cv.create_line(4, 10, 16, 10, **ln)
    elif name == "chevron-down":
        cv.create_line(4.5, 7.5, 10, 13, 15.5, 7.5, **ln)
    elif name == "chevron-up":
        cv.create_line(4.5, 12.5, 10, 7, 15.5, 12.5, **ln)
    elif name == "new-file":     # page with a plus
        cv.create_polygon(4, 2, 11.5, 2, 15.5, 6, 15.5, 18, 4, 18,
                          fill=bg or "", **t)
        cv.create_line(11.5, 2, 11.5, 6, **ln)
        cv.create_line(11.5, 6, 15.5, 6, **ln)
        cv.create_line(7, 13, 12.5, 13, **ln)
        cv.create_line(9.75, 10.25, 9.75, 15.75, **ln)
    elif name == "new-folder":   # folder with a plus
        cv.create_polygon(2.5, 5, 8, 5, 10, 7.5, 17.5, 7.5, 17.5, 16,
                          2.5, 16, fill=bg or "", **t)
        cv.create_line(7.5, 11.75, 12.5, 11.75, **ln)
        cv.create_line(10, 9.25, 10, 14.25, **ln)
    elif name == "refresh":      # circular arrow
        cv.create_arc(3.5, 3.5, 16.5, 16.5, start=55, extent=265,
                      style="arc", **t)
        cv.create_polygon(12.5, 1.5, 17, 5, 12, 7.5,
                          fill=color, outline="", tags="icon")
    elif name == "collapse":     # chevron folding up onto a line
        cv.create_line(5, 11, 10, 6, **ln)
        cv.create_line(10, 6, 15, 11, **ln)
        cv.create_line(4.5, 15.5, 15.5, 15.5, **ln)
    elif name == "ellipsis":
        for x in (4.5, 10, 15.5):
            cv.create_oval(x - 1.4, 8.6, x + 1.4, 11.4, **fl)
    elif name == "panel-side":   # toggle sidebar
        cv.create_rectangle(2.5, 3, 17.5, 17, **t)
        cv.create_line(9, 3, 9, 17, **ln)
    elif name == "panel-bottom":  # toggle panel
        cv.create_rectangle(2.5, 3, 17.5, 17, **t)
        cv.create_line(2.5, 12, 17.5, 12, **ln)
    elif name == "logo":          # neutral </> mark
        cv.create_line(7.5, 4.5, 2.5, 10, 7.5, 15.5, **ln)
        cv.create_line(12.5, 4.5, 17.5, 10, 12.5, 15.5, **ln)
        cv.create_line(11.2, 3.5, 8.8, 16.5, **ln)

    _fit_icon(cv)


def _fit_icon(cv):
    """Scale the 20-unit artwork to the canvas and centre it exactly."""
    try:
        w = int(cv.cget("width"))
        h = int(cv.cget("height"))
    except (tk.TclError, ValueError):
        return
    if w <= 0 or h <= 0:
        return
    scale = min(w, h) / 20.0
    if abs(scale - 1.0) > 0.01:
        cv.scale("icon", 0, 0, scale, scale)
    box = cv.bbox("icon")
    if not box:
        return
    # centre on the artwork's real extents, rounded to whole pixels so
    # strokes land on the pixel grid instead of straddling it
    dx = round((w - (box[2] - box[0])) / 2.0 - box[0])
    dy = round((h - (box[3] - box[1])) / 2.0 - box[1])
    if dx or dy:
        cv.move("icon", dx, dy)


def icon_button(parent, name, size=20, bg=C["activity"], cmd=None, pad=0,
                color=None):
    size = max(12, round(size * UI_SCALE))
    cv = tk.Canvas(parent, width=size, height=size, bg=bg,
                   highlightthickness=0, cursor="hand2")
    cv._icon_name = name
    draw_icon(cv, name, color=color, bg=bg)
    if cmd:
        def _click(_e, c=cmd):
            c()
        cv.bind("<Button-1>", _click)
    return cv


def rounded_button(parent, text, cmd, bg, fg, hover_bg, font,
                   height=32, radius=7):
    """A pill/rounded-corner button drawn on a Canvas (ttk/tk have no
    native rounded-rect widget), used for the Explorer's "no folder
    open" empty state so it visually matches the rest of the app's
    rounded, card-like chrome instead of a flat square tk.Button.

    Stretches to fill whatever width its parent gives it (pack with
    fill="x") -- the shape is redrawn on every resize.
    """
    height = max(20, round(height * UI_SCALE))
    radius = max(3, round(radius * UI_SCALE))
    cv = tk.Canvas(parent, height=height, bg=parent["bg"],
                   highlightthickness=0, cursor="hand2")
    state = {"color": bg}

    def redraw(_e=None):
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 4 or h < 4:
            return
        r = min(radius, w / 2.0, h / 2.0)
        cv.delete("all")
        pts = [r, 0, w - r, 0, w, 0, w, r,
               w, h - r, w, h, w - r, h,
               r, h, 0, h, 0, h - r, 0, r, 0, 0]
        color = state["color"]
        cv.create_polygon(pts, smooth=True, fill=color, outline=color)
        cv.create_text(w / 2.0, h / 2.0, text=text, fill=fg, font=font)

    def enter(_e):
        state["color"] = hover_bg
        redraw()

    def leave(_e):
        state["color"] = bg
        redraw()

    cv.bind("<Configure>", redraw)
    cv.bind("<Button-1>", lambda e: cmd())
    cv.bind("<Enter>", enter)
    cv.bind("<Leave>", leave)
    return cv


# ------------------------------------------------------------------ #
#  Activity bar (far left icon strip)                                 #
# ------------------------------------------------------------------ #
class ActivityBar(tk.Frame):
    """The narrow, fixed-width icon rail along the window's left edge
    that switches which SideBar view is showing. Every one of these
    views (Explorer, Search, Source Control, Run and Debug, Extensions)
    already existed in SideBar -- Explorer/Search were only reachable
    through the View menu or a keyboard shortcut, and Source Control /
    Run and Debug / Extensions had no way in at all. This just gives all
    five a single, visible, VS-Code-shaped home, using nothing but icons
    and views this app already draws and already builds."""

    _ITEMS = (
        ("explorer", "Explorer  (Ctrl+Shift+E)"),
        ("search", "Search  (Ctrl+Shift+F)"),
        ("git", "Source Control"),
        ("run", "Run and Debug"),
        ("extensions", "Extensions"),
    )

    def __init__(self, app):
        super().__init__(app, bg=C["activity"], width=band(48),
                         highlightthickness=1,
                         highlightbackground=C["border"])
        self.app = app
        self.pack_propagate(False)
        self._buttons = {}
        self._bars = {}
        top = tk.Frame(self, bg=C["activity"])
        top.pack(side="top", fill="x")
        for name, tip in self._ITEMS:
            holder = tk.Frame(top, bg=C["activity"])
            holder.pack(side="top", fill="x")
            bar = tk.Frame(holder, bg=C["activity"], width=max(2, band(2)))
            bar.pack(side="left", fill="y")
            btn = icon_button(holder, name, size=band(24), bg=C["activity"],
                              cmd=lambda n=name: self.app.show_sidebar_mode(n),
                              color=C["fg_dim"])
            btn.pack(side="left", padx=band(11), pady=band(11))
            self.app.tooltip(btn, tip)

            def _enter(_e, n=name):
                if self.app.sidebar.mode != n:
                    draw_icon(self._buttons[n], n, color=C["fg_bright"],
                             bg=C["activity"])

            def _leave(_e, n=name):
                if self.app.sidebar.mode != n:
                    draw_icon(self._buttons[n], n, color=C["fg_dim"],
                             bg=C["activity"])

            btn.bind("<Enter>", _enter)
            btn.bind("<Leave>", _leave)
            self._buttons[name] = btn
            self._bars[name] = bar

    def set_active(self, mode):
        """Tint the icon for `mode` and show its left accent bar -- the
        only on-screen indicator, besides the sidebar's own title, of
        which view is currently open."""
        for name, btn in self._buttons.items():
            active = (name == mode)
            try:
                draw_icon(btn, name,
                         color=C["fg_bright"] if active else C["fg_dim"],
                         bg=C["activity"])
                self._bars[name].configure(
                    bg=C["accent"] if active else C["activity"])
            except tk.TclError:
                pass


# ------------------------------------------------------------------ #
#  Side bar (explorer / search / run / extensions views)              #
# ------------------------------------------------------------------ #
class SideBar(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=C["sidebar"], highlightthickness=1,
                         highlightbackground=C["border"])
        self.app = app
        self.mode = None   # nothing shown yet
        app.style_tree(self)
        self.tree = None
        self._guide_bars = []
        self.body = tk.Frame(self, bg=C["sidebar"])
        self._imgs = {}
        self._git_status = {}

    # ---------------- shared chrome ----------------
    def _title(self, text, actions=()):
        bar = tk.Frame(self, bg=C["sidebar"], height=band(36))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text=text, bg=C["sidebar"], fg=C["fg_dim"],
                 font=(self.app.f_ui[0], *ts(-1, bold=True))
                 ).pack(side="left", padx=sp("lg"))
        # actions are packed right-to-left, so reverse for visual order
        for icon, tip, cmd in reversed(actions):
            b = icon_button(bar, icon, size=15, bg=C["sidebar"], cmd=cmd,
                            color=C["fg_dim"])
            b.pack(side="right", padx=sp("xs"), pady=sp("sm"))
            b.bind("<Enter>", lambda e, w=b: draw_icon(
                w, w._icon_name, color=C["fg_bright"], bg=C["sidebar"]),
                add="+")
            b.bind("<Leave>", lambda e, w=b: draw_icon(
                w, w._icon_name, color=C["fg_dim"], bg=C["sidebar"]),
                add="+")
            self.app.tooltip(b, tip)

    def show(self, mode):
        self.mode = mode
        bar = getattr(self.app, "activity_bar", None)
        if bar is not None:
            bar.set_active(mode)
        for w in self.winfo_children():
            w.pack_forget()
        if mode == "explorer":
            root = self.app.root_dir
            self._title("EXPLORER", actions=(
                ("new-file", "New File  (right-click for more)",
                 lambda: self.app.fs_new_file(self._target_dir())),
                ("new-folder", "New Folder",
                 lambda: self.app.fs_new_folder(self._target_dir())),
                ("refresh", "Refresh Explorer", self.app.refresh_explorer),
                ("collapse", "Collapse Folders", self.collapse_all),
            ))
            self._build_explorer()
        elif mode == "search":
            self._title("SEARCH")
            self._build_search()
        elif mode == "run":
            self._title("RUN AND DEBUG")
            self._build_run()
        elif mode == "extensions":
            self._title("EXTENSIONS")
            self._build_extensions()
        elif mode == "git":
            self._title("SOURCE CONTROL")
            self._build_git()

    # ---------------- explorer ----------------
    def icon_size(self):
        return max(16, min(30, int(round(18 * UI_SCALE))))

    def _icon(self, name, is_dir=False, is_open=False, badge=None):
        """Cached file-type icon. Keyed so each variant is drawn once.

        `badge`, when given ("M" or "C"), composites a small git-status
        checkbox onto the icon's left -- see build_badge_icon().
        """
        size = self.icon_size()
        if is_dir:
            key = ("dir-open" if is_open else "dir", size)
        else:
            key = (key_for(name) or "?", size)
        img = self._imgs.get(key)
        if img is None:
            try:
                img = build_icon(tk, name, size, is_dir=is_dir,
                                 is_open=is_open)
            except Exception:  # noqa: BLE001
                img = tk.PhotoImage(width=size, height=size)
            self._imgs[key] = img
        if not badge:
            return img
        bkey = key + (badge,)
        bimg = self._imgs.get(bkey)
        if bimg is None:
            try:
                bimg = build_badge_icon(tk, img, badge, size)
            except Exception:  # noqa: BLE001
                bimg = img
            self._imgs[bkey] = bimg
        return bimg

    def _build_explorer(self):
        self.body.pack(fill="both", expand=True)

        if self.app._placeholder_workspace_is_empty():
            if self.tree is not None:
                self.tree.pack_forget()
            self._build_no_folder_state()
            return
        if getattr(self, "_no_folder_frame", None) is not None:
            self._no_folder_frame.pack_forget()

        if self.tree is None:
            self.tree = ttk.Treeview(self.body, show="tree", selectmode="browse")
            self.tree.bind("<<TreeviewOpen>>", self._on_open_node)
            self.tree.bind("<<TreeviewClose>>", self._on_close_node)
            self.tree.bind("<Double-1>", self._on_dbl)
            # single click opens a file / toggles a folder
            self.tree.bind("<ButtonRelease-1>", self._on_single, add="+")
            # right click (Button-2 / Ctrl+click are the macOS equivalents)
            for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
                self.tree.bind(seq, self._ctx_menu)
            self.tree.bind("<F2>", lambda e: self._key_op("rename"))
            self.tree.bind("<Delete>", lambda e: self._key_op("delete"))
            self.tree.bind("<Control-x>", lambda e: self._key_op("cut"))
            self.tree.bind("<Control-c>", lambda e: self._key_op("copy"))
            self.tree.bind("<Control-v>", lambda e: self._key_op("paste"))

            # ttk.Treeview cannot draw indent guides. An overlay canvas
            # would be opaque and cover the icons, so each guide is a 1px
            # strip placed in the indent whitespace instead.
            self._guide_bars = []
            self.tree.bind("<<TreeviewSelect>>",
                           lambda e: self._queue_guides(), add="+")
            self.tree.bind("<Configure>",
                           lambda e: self._queue_guides(), add="+")
            self.tree.configure(
                yscrollcommand=lambda *a: self._queue_guides())
        self.tree.pack(fill="both", expand=True)
        self.tree.delete(*self.tree.get_children(""))
        self._git_status = self.app.git_status_map()
        root = self.app.root_dir
        self.root_node = self.tree.insert(
            "", "end", text=" " + self.app.workspace_display_name().upper(),
            open=True, tags=("section",), values=(root,),
            image=self._icon(os.path.basename(root), is_dir=True,
                             is_open=True,
                             badge=self._git_badge_for(root)))
        self._fill_dir(self.root_node, root)
        self._queue_guides()

    def _git_badge_for(self, path):
        """'M'/'C'/None for a path, from the git status snapshot taken at
        the start of the current Explorer build (see _build_explorer())."""
        status = getattr(self, "_git_status", None)
        return status.get(os.path.normpath(path)) if status else None

    def _build_no_folder_state(self):
        """VS-Code-style "no folder open" empty state, shown instead of a
        file tree while the IDE's workspace is still just agent_tools.py's
        own auto-created, empty friday-empty-* scratch directory -- i.e.
        nobody has opened or cloned a real project yet."""
        if getattr(self, "_no_folder_frame", None) is None:
            self._no_folder_frame = self._make_no_folder_frame()
        self._no_folder_frame.pack(fill="both", expand=True)

    def _make_no_folder_frame(self):
        app = self.app
        outer = tk.Frame(self.body, bg=C["sidebar"])

        head = tk.Frame(outer, bg=C["sidebar"], cursor="hand2")
        head.pack(fill="x")
        chevron = tk.Label(head, text="\u2304", bg=C["sidebar"],
                           fg=C["fg_dim"], font=(app.f_ui[0], *ts(2)))
        chevron.pack(side="left", padx=(sp("lg"), 4), pady=6)
        tk.Label(head, text="NO FOLDER OPENED", bg=C["sidebar"],
                 fg=C["fg_dim"], font=(app.f_ui[0], *ts(-1, bold=True))
                 ).pack(side="left", pady=6)

        content = tk.Frame(outer, bg=C["sidebar"])
        content.pack(fill="both", expand=True)

        def toggle(_e=None):
            if content.winfo_ismapped():
                content.pack_forget()
                chevron.configure(text="\u203a")
            else:
                content.pack(fill="both", expand=True)
                chevron.configure(text="\u2304")
        head.bind("<Button-1>", toggle)
        chevron.bind("<Button-1>", toggle)

        pad = sp("lg")
        wrap = max(180, int(220 * UI_SCALE))

        tk.Label(content, text="You have not yet opened a folder.",
                 bg=C["sidebar"], fg=C["fg"], font=app.f_ui, anchor="w",
                 justify="left", wraplength=wrap
                 ).pack(fill="x", padx=pad, pady=(12, 10))

        rounded_button(
            content, "Open Folder", app.open_folder_dialog,
            bg=C["accent"], fg="#ffffff",
            hover_bg=mix(C["accent"], "#ffffff", 0.18), font=app.f_ui
            ).pack(fill="x", padx=pad, pady=(0, 18))

        tk.Label(content, text="You can clone a repository locally.",
                 bg=C["sidebar"], fg=C["fg"], font=app.f_ui, anchor="w",
                 justify="left", wraplength=wrap
                 ).pack(fill="x", padx=pad, pady=(0, 10))

        rounded_button(
            content, "Clone Repository", app.clone_repository_dialog,
            bg=C["accent_btn"], fg=C["fg_bright"], hover_bg=C["accent_hover"],
            font=app.f_ui
            ).pack(fill="x", padx=pad, pady=(0, 18))

        tk.Label(content, text="Once a folder is open, use Source Control "
                 "to work with Git.",
                 bg=C["sidebar"], fg=C["fg_faint"],
                 font=(app.f_ui[0], *ts(-1)), anchor="w", justify="left",
                 wraplength=wrap).pack(fill="x", padx=pad, pady=(0, 10))
        return outer

    def refresh_open_editors(self):
        """The OPEN EDITORS section was removed; open files live in the tab
        strip. Kept as a no-op so existing call sites stay valid."""
        return

    def _fill_dir(self, node, path):
        self._queue_guides()
        self.tree.delete(*self.tree.get_children(node))
        try:
            entries = sorted(os.scandir(path),
                             key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return
        for e in entries:
            if e.name in SKIP_DIRS:
                continue
            if e.is_dir():
                n = self.tree.insert(node, "end", text=" " + e.name,
                                     values=(e.path,), tags=("dir",),
                                     image=self._icon(
                                         e.name, is_dir=True,
                                         badge=self._git_badge_for(e.path)))
                self.tree.insert(n, "end", text="dummy")  # lazy marker
            else:
                self.tree.insert(node, "end", text=" " + e.name,
                                 values=(e.path,),
                                 image=self._icon(
                                     e.name,
                                     badge=self._git_badge_for(e.path)))

    # ---------------- indent guides ----------------
    def _indent_px(self):
        try:
            v = ttk.Style(self).lookup("Treeview", "indent")
            return max(8, int(float(v)))
        except Exception:  # noqa: BLE001
            return max(14, int(round(16 * UI_SCALE)))

    def _fwd(self, handler, e):
        """Replay a click from the overlay onto the tree underneath."""
        item = self.tree.identify_row(e.y)
        if item:
            self.tree.selection_set(item)
            self.tree.focus(item)

        class _E:
            pass
        ev = _E()
        ev.x, ev.y = e.x, e.y
        ev.x_root, ev.y_root = e.x_root, e.y_root
        ev.num = getattr(e, "num", 1)
        ev.state = getattr(e, "state", 0)
        ev.delta = getattr(e, "delta", 0)
        try:
            handler(ev)
        except Exception:  # noqa: BLE001
            pass
        self._queue_guides()
        return "break"

    def _fwd_wheel(self, e):
        step = -1 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) \
            else 1
        self.tree.yview_scroll(step * 2, "units")
        self._queue_guides()
        return "break"

    def _queue_guides(self):
        if getattr(self, "_guide_job", None):
            try:
                self.after_cancel(self._guide_job)
            except Exception:  # noqa: BLE001
                pass
        try:
            self._guide_job = self.after_idle(self._draw_guides)
        except Exception:  # noqa: BLE001
            pass

    def _visible_rows(self):
        """(item, depth, ancestors) for every row currently on screen."""
        out = []

        def walk(node, depth, chain):
            for k in self.tree.get_children(node):
                out.append((k, depth, chain))
                if self.tree.item(k, "open"):
                    walk(k, depth + 1, chain + [k])
        walk("", 0, [])
        return out

    def _guide_bar(self, idx):
        """Reuse a strip from the pool, creating it on first use."""
        while len(self._guide_bars) <= idx:
            f = tk.Frame(self.tree, bg=GUIDE_COLOR,
                         highlightthickness=0, bd=0)
            # a click that lands exactly on a 1px line should still work
            f.bind("<ButtonRelease-1>",
                   lambda e, w=f: self._fwd_from(w, self._on_single, e))
            f.bind("<Double-1>",
                   lambda e, w=f: self._fwd_from(w, self._on_dbl, e))
            for seq in ("<Button-3>", "<Button-2>"):
                f.bind(seq, lambda e, w=f: self._fwd_from(w, self._ctx_menu, e))
            self._guide_bars.append(f)
        return self._guide_bars[idx]

    def _fwd_from(self, widget, handler, e):
        """Translate an event on a strip into tree coordinates."""
        class _E:
            pass
        ev = _E()
        ev.x = e.x + widget.winfo_x()
        ev.y = e.y + widget.winfo_y()
        ev.x_root, ev.y_root = e.x_root, e.y_root
        ev.num = getattr(e, "num", 1)
        ev.state = getattr(e, "state", 0)
        ev.delta = getattr(e, "delta", 0)
        return self._fwd(handler, ev)

    def _draw_guides(self):
        self._guide_job = None
        if self.tree is None or not hasattr(self, "_guide_bars"):
            return
        try:
            if not self.tree.winfo_exists():
                return
        except tk.TclError:
            return
        if self.mode != "explorer":
            for f in self._guide_bars:
                f.place_forget()
            return

        ind = self._indent_px()
        rows = []
        for item, depth, chain in self._visible_rows():
            try:
                bb = self.tree.bbox(item)
            except tk.TclError:
                bb = None
            if bb:
                rows.append((depth, chain, bb[1], bb[3]))

        # the folder chain leading to the selected row is highlighted, which
        # is what makes "these files live in that folder" obvious at a glance
        active = set()
        node = self.tree.focus()
        while node:
            active.add(node)
            node = self.tree.parent(node)
        root = getattr(self, "root_node", None)

        # group consecutive rows sharing a guide into one strip
        runs = []                      # (level, parent, y0, y1)
        open_runs = {}                 # level -> [parent, y0, y1]
        for depth, chain, y, h in rows:
            for lvl in range(1, depth + 1):
                parent = chain[lvl - 1] if lvl - 1 < len(chain) else None
                if parent is None:
                    continue
                cur = open_runs.get(lvl)
                if cur and cur[0] == parent and abs(cur[2] - y) <= h + 2:
                    cur[2] = y + h
                else:
                    if cur:
                        runs.append((lvl, cur[0], cur[1], cur[2]))
                    open_runs[lvl] = [parent, y, y + h]
            for lvl in list(open_runs):
                if lvl > depth:
                    cur = open_runs.pop(lvl)
                    runs.append((lvl, cur[0], cur[1], cur[2]))
        for lvl, cur in open_runs.items():
            runs.append((lvl, cur[0], cur[1], cur[2]))

        i = 0
        for lvl, parent, y0, y1 in runs:
            if y1 <= y0:
                continue
            on = parent in active and parent != root
            bar = self._guide_bar(i)
            i += 1
            bar.configure(bg=C["accent"] if on else GUIDE_COLOR)
            bar.place(x=ind * lvl + ind // 2, y=y0,
                      width=max(1, band(1) if on else 1),
                      height=y1 - y0)
            bar.lift()
        for f in self._guide_bars[i:]:
            f.place_forget()

    def _key_op(self, what):
        p = self.selected_path()
        if not p:
            return None
        app = self.app
        if what == "rename":
            app.fs_rename(p)
        elif what == "delete":
            app.fs_delete(p)
        elif what in ("cut", "copy"):
            app.fs_clip_set(p, what)
        elif what == "paste":
            app.fs_paste(p if os.path.isdir(p) else os.path.dirname(p))
        return "break"

    def _on_open_node(self, _e):
        self._queue_guides()
        node = self.tree.focus()
        vals = self.tree.item(node, "values")
        if vals and os.path.isdir(vals[0]):
            self._fill_dir(node, vals[0])
            self._set_dir_icon(node, vals[0], True)

    def _on_close_node(self, _e):
        self._queue_guides()
        node = self.tree.focus()
        vals = self.tree.item(node, "values")
        if vals and os.path.isdir(vals[0]):
            self._set_dir_icon(node, vals[0], False)

    def _set_dir_icon(self, node, path, is_open):
        if node == getattr(self, "root_node", None):
            return
        try:
            self.tree.item(node, image=self._icon(
                os.path.basename(path), is_dir=True, is_open=is_open,
                badge=self._git_badge_for(path)))
        except tk.TclError:
            pass

    def _on_single(self, e):
        """Single left click: open the file, or expand/collapse the folder."""
        if self.tree.identify_region(e.x, e.y) == "separator":
            return
        item = self.tree.identify_row(e.y)
        if not item:
            return
        vals = self.tree.item(item, "values")
        if not vals:
            return
        v = vals[0]
        self._queue_guides()
        if os.path.isdir(v):
            is_open = bool(self.tree.item(item, "open"))
            self.tree.item(item, open=not is_open)
            if not is_open:
                self._fill_dir(item, v)
            self._set_dir_icon(item, v, not is_open)
        elif os.path.isfile(v):
            self.app.open_file(v)

    def _on_dbl(self, _e):
        node = self.tree.focus()
        vals = self.tree.item(node, "values")
        if not vals:
            return
        v = vals[0]
        if os.path.isfile(v):
            self.app.open_file(v)

    # ---------------- explorer context menu ----------------
    def _ctx_target(self, e):
        """(path, is_dir) for the row under the pointer, root as fallback."""
        item = self.tree.identify_row(e.y)
        if item:
            self.tree.selection_set(item)
            self.tree.focus(item)
            vals = self.tree.item(item, "values")
            if vals:
                return vals[0], os.path.isdir(vals[0])
        return self.app.root_dir, True

    def _ctx_menu(self, e):
        path, is_dir = self._ctx_target(e)
        app = self.app
        base = path if is_dir else os.path.dirname(path)
        m = tk.Menu(self, tearoff=0, bg=C["sidebar"], fg=C["fg"],
                    activebackground=C["list_sel"],
                    activeforeground=C["fg_bright"],
                    bd=1, relief="flat", font=app.f_ui)

        def item(label, cmd, accel="", state="normal"):
            m.add_command(label=label, command=cmd, accelerator=accel,
                          state=state)

        item("New File…", lambda: app.fs_new_file(base))
        item("New Folder…", lambda: app.fs_new_folder(base))
        m.add_separator()
        if not is_dir:
            item("Open", lambda: app.open_file(path))
            item("Run File", lambda: (app.open_file(path), app.run_file()))
            m.add_separator()
        item("Reveal in File Explorer", lambda: app.reveal_in_file_manager(path),
             "Shift+Alt+R")
        item("Open in Integrated Terminal",
             lambda: app.open_in_terminal(base))
        item("Find in Folder…", lambda: app.find_in_folder(base),
             "Shift+Alt+F")
        m.add_separator()
        item("Cut", lambda: app.fs_clip_set(path, "cut"), "Ctrl+X")
        item("Copy", lambda: app.fs_clip_set(path, "copy"), "Ctrl+C")
        item("Paste", lambda: app.fs_paste(base), "Ctrl+V",
             "normal" if app.fs_clip else "disabled")
        item("Duplicate", lambda: app.fs_duplicate(path))
        m.add_separator()
        item("Copy Path", lambda: app.copy_path(path, False), "Shift+Alt+C")
        item("Copy Relative Path", lambda: app.copy_path(path, True))
        m.add_separator()
        item("Rename…", lambda: app.fs_rename(path), "F2")
        item("Delete", lambda: app.fs_delete(path), "Del")
        m.add_separator()
        item("Refresh Explorer", app.refresh_explorer)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()
        return "break"

    def _target_dir(self):
        """Where a new file should go: the selected folder, else the root."""
        p = self.selected_path()
        if p and os.path.isdir(p):
            return p
        if p:
            return os.path.dirname(p)
        return self.app.root_dir

    def collapse_all(self):
        if self.tree is None:
            return

        def walk(node):
            for k in self.tree.get_children(node):
                vals = self.tree.item(k, "values")
                if vals and os.path.isdir(vals[0]) and k != self.root_node:
                    self.tree.item(k, open=False)
                    self._set_dir_icon(k, vals[0], False)
                walk(k)
        walk("")

    def selected_path(self):
        node = self.tree.focus() if self.tree else None
        if not node:
            return None
        vals = self.tree.item(node, "values")
        return vals[0] if vals else None

    # ---------------- search ----------------
    def _build_search(self):
        f = tk.Frame(self, bg=C["sidebar"])
        f.pack(fill="both", expand=True, padx=10, pady=6)

        def entry(parent):
            e = tk.Entry(parent, bg=C["input"], fg=C["fg"], relief="flat",
                         insertbackground=C["fg"], font=self.app.f_ui,
                         highlightthickness=1, highlightcolor=C["accent"],
                         highlightbackground=C["border"])
            e.pack(fill="x", ipady=4)
            return e

        self.search_scope = getattr(self, "search_scope", None)
        self.s_query = entry(f)
        self.s_query.insert(0, "Search")
        self.s_query.bind("<FocusIn>",
                          lambda e: self.s_query.get() == "Search"
                          and self.s_query.delete(0, "end"))
        self.s_query.bind("<Return>", lambda e: self._run_search())
        tk.Frame(f, bg=C["sidebar"], height=6).pack()
        self.s_repl = entry(f)
        self.s_repl.insert(0, "Replace")
        self.s_repl.bind("<FocusIn>",
                         lambda e: self.s_repl.get() == "Replace"
                         and self.s_repl.delete(0, "end"))
        tk.Frame(f, bg=C["sidebar"], height=8).pack()
        btns = tk.Frame(f, bg=C["sidebar"])
        btns.pack(fill="x")
        mk = self.app.flat_button
        mk(btns, "Replace All", self._replace_all, secondary=True)\
            .pack(side="right")
        self.s_results = tk.Frame(f, bg=C["sidebar"])
        self.s_results.pack(fill="both", expand=True, pady=(8, 0))
        self.s_count = tk.Label(f, bg=C["sidebar"], fg=C["fg_dim"],
                                font=(self.app.f_ui[0], 9), anchor="w")
        self.s_count.pack(fill="x", side="bottom")

    def _run_search(self):
        scope = getattr(self, "search_scope", None)
        if scope and scope != self.app.root_dir:
            self.app.panel_error  # no-op guard
        q = self.s_query.get()
        if not q or q == "Search":
            return
        for w in self.s_results.winfo_children():
            w.destroy()
        scope = getattr(self, "search_scope", None) or self.app.root_dir
        # Same WorkspaceFS.search() an ide_search_workspace agent tool
        # call uses -- one implementation, so the UI and Friday can never
        # see different results for the same query.
        hits = self.app.fs.search(q, scope=scope)
        self._search_hits = [(self.app.fs.resolve(rel), ln, snip)
                             for rel, ln, snip in hits]
        self.s_count.configure(
            text=f"{len(self._search_hits)} results in workspace")
        for p, ln, snip in self._search_hits[:80]:
            rel = os.path.relpath(p, self.app.root_dir)
            txt = f"{rel}:{ln}"
            b = tk.Label(self.s_results, text=txt, bg=C["sidebar"],
                         fg=C["link"], anchor="w", cursor="hand2",
                         font=(self.app.f_ui[0], 9))
            b.pack(fill="x")
            b.bind("<Button-1>",
                   lambda e, pp=p, ll=ln: self.app.open_file(pp, line=ll))
            tk.Label(self.s_results, text="   " + snip[:60], bg=C["sidebar"],
                     fg=C["fg_dim"], anchor="w",
                     font=(self.app.f_ui[0], 9)).pack(fill="x")

    def _replace_all(self):
        q, r = self.s_query.get(), self.s_repl.get()
        if not q or q == "Search" or r == "Replace":
            return
        n = 0
        scope = getattr(self, "search_scope", None) or self.app.root_dir
        for dirpath, dirs, files in os.walk(scope):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                p = os.path.join(dirpath, fn)
                try:
                    txt = open(p, encoding="utf-8").read()
                except (OSError, UnicodeError):
                    continue
                if q in txt:
                    open(p, "w", encoding="utf-8").write(txt.replace(q, r))
                    n += 1
        self.s_count.configure(text=f"Replaced in {n} file(s). Reload tabs.")
        self.app.reload_current()


    # ---------------- run view ----------------
    def _build_run(self):
        f = tk.Frame(self, bg=C["sidebar"])
        f.pack(fill="both", expand=True, padx=14, pady=10)
        tk.Label(f, text="Run and debug the active file using the\n"
                         "built-in Python launcher.",
                 bg=C["sidebar"], fg=C["fg_dim"], font=self.app.f_ui,
                 justify="left").pack(anchor="w")
        tk.Frame(f, bg=C["sidebar"], height=12).pack()
        self.app.flat_button(f, "▶  Run Python File   (F5)",
                             self.app.run_file).pack(fill="x")
        tk.Frame(f, bg=C["sidebar"], height=18).pack()
        tk.Label(f, text="To customize Run and Debug create a "
                         "launch.json file.", bg=C["sidebar"], fg=C["fg_dim"],
                 font=(self.app.f_ui[0], 9), justify="left",
                 wraplength=190).pack(anchor="w")

    # ---------------- extensions view ----------------
    def _build_extensions(self):
        f = tk.Frame(self, bg=C["sidebar"])
        f.pack(fill="both", expand=True, padx=10, pady=6)
        tk.Label(f, text="INSTALLED / RECOMMENDED", bg=C["sidebar"],
                 fg=C["fg_dim"], font=(self.app.f_ui[0], 9)).pack(anchor="w")
        exts = [("Python", "Microsoft", "IntelliSense, linting, debugging"),
                ("Pylance", "Microsoft", "Fast, feature-rich language support"),
                ("Jupyter", "Microsoft", "Notebook support"),
                ("Prettier", "Prettier", "Code formatter"),
                ("GitLens", "GitKraken", "Git supercharged")]
        for name, pub, desc in exts:
            card = tk.Frame(f, bg=C["sidebar"])
            card.pack(fill="x", pady=6)
            tk.Label(card, text=name, bg=C["sidebar"], fg=C["fg_bright"],
                     font=(self.app.f_ui[0], 10, "bold")).pack(anchor="w")
            tk.Label(card, text=desc, bg=C["sidebar"], fg=C["fg_dim"],
                     font=(self.app.f_ui[0], 9), wraplength=190,
                     justify="left").pack(anchor="w")
            row = tk.Frame(card, bg=C["sidebar"])
            row.pack(fill="x")
            tk.Label(row, text=pub, bg=C["sidebar"], fg=C["fg_dim"],
                     font=(self.app.f_ui[0], 8)).pack(side="left")
            self.app.flat_button(row, "Install", lambda: None,
                                 secondary=True).pack(side="right")

    # ---------------- git view ----------------
    def _build_git(self):
        f = tk.Frame(self, bg=C["sidebar"])
        f.pack(fill="both", expand=True, padx=14, pady=10)
        if not os.path.isdir(os.path.join(self.app.root_dir, ".git")):
            tk.Label(f, text="No source control providers registered.",
                     bg=C["sidebar"], fg=C["fg_dim"], font=self.app.f_ui,
                     justify="left").pack(anchor="w")
            tk.Frame(f, bg=C["sidebar"], height=12).pack()
            self.app.flat_button(
                f, "Initialize Repository",
                lambda: self.app.git_init_repository()).pack(fill="x")
            return

        changes = self.app._raw_git_status()
        if not changes:
            tk.Label(f, text="No changes.", bg=C["sidebar"],
                     fg=C["fg_dim"], font=self.app.f_ui,
                     justify="left").pack(anchor="w")
            return

        tk.Label(f, text=f"CHANGES ({len(changes)})", bg=C["sidebar"],
                 fg=C["fg_dim"], font=(self.app.f_ui[0], 9)
                 ).pack(anchor="w", pady=(0, 6))
        size = self.icon_size()
        for path, code in sorted(changes.items(),
                                 key=lambda kv: os.path.basename(kv[0])):
            row = tk.Frame(f, bg=C["sidebar"], cursor="hand2")
            row.pack(fill="x", pady=1)
            img = self._icon(os.path.basename(path), badge=code)
            lbl_icon = tk.Label(row, image=img, bg=C["sidebar"])
            lbl_icon.image = img
            lbl_icon.pack(side="left")
            rel = os.path.relpath(path, self.app.root_dir)
            lbl = tk.Label(row, text=" " + rel, bg=C["sidebar"],
                           fg=C["fg"], font=self.app.f_ui, anchor="w")
            lbl.pack(side="left", fill="x", expand=True)
            widgets = (row, lbl_icon, lbl)
            hover_fx(row, bg_from=C["sidebar"], bg_to=C["hover"],
                    targets=widgets)
            for w in widgets:
                w.bind("<Button-1>", lambda e, p=path: self.app.open_file(p)
                      if os.path.isfile(p) else None)


# ------------------------------------------------------------------ #
#  Terminal / output panel                                            #
# ------------------------------------------------------------------ #
class Panel(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=C["panel"], highlightthickness=1,
                         highlightbackground=C["border"])
        self.app = app
        self.proc = None
        self.history, self.hidx = [], 0

        tabbar = tk.Frame(self, bg=C["panel"], height=30)
        tabbar.pack(fill="x")
        tabbar.pack_propagate(False)
        self._tabs = {}
        self._tab_rules = {}
        for name in ("PROBLEMS", "OUTPUT", "DEBUG CONSOLE", "TERMINAL"):
            holder = tk.Frame(tabbar, bg=C["panel"])
            holder.pack(side="left", pady=(sp("sm"), 0))
            lab = tk.Label(holder, text=name, bg=C["panel"],
                           fg=C["fg_dim"], font=(app.f_ui[0], *ts(-1)),
                           padx=sp("md"), cursor="hand2")
            lab.pack(side="top")
            rule = tk.Frame(holder, bg=C["panel"], height=max(2, band(2)))
            rule.pack(side="top", fill="x")
            for wdg in (holder, lab, rule):
                wdg.bind("<Button-1>", lambda e, n=name: self._sel(n))
            hover_fx(lab, fg_from=None, fg_to=C["fg"])
            self._tabs[name] = lab
            self._tab_rules[name] = rule
        right = tk.Frame(tabbar, bg=C["panel"])
        right.pack(side="right", padx=8)
        _clear_btn = icon_button(right, "plus", 18, C["panel"], cmd=self.clear)
        _clear_btn.pack(side="left", padx=3)
        app.tooltip(_clear_btn, "Clear")
        _max_btn = icon_button(right, "chevron-up", 18, C["panel"], cmd=self.clear)
        _max_btn.pack(side="left", padx=3)
        app.tooltip(_max_btn, "Maximize panel")
        _close_btn = icon_button(right, "close", 18, C["panel"],
                                 cmd=app.toggle_panel)
        _close_btn.pack(side="left", padx=3)
        app.tooltip(_close_btn, "Close panel")

        self.term = tk.Text(self, bg=C["terminal"], fg=C["fg"],
                            insertbackground=C["fg"], relief="flat", bd=0,
                            font=(app.f_mono[0], 11), wrap="none",
                            state="normal", undo=False, highlightthickness=0)
        self.term.pack(fill="both", expand=True)
        self.term.tag_configure("cwd", foreground=C["term_cwd"])
        self.term.tag_configure("err", foreground=C["term_err"])
        self.term.tag_configure("info", foreground=C["term_info"])
        self.term.tag_configure("cursor", underline=True)
        self.term.mark_set("input", "end-1c")
        self.term.mark_gravity("input", "left")
        for ev in ("<Return>", "<BackSpace>", "<Up>", "<Down>", "<Key>",
                   "<Button-1>", "<Control-c>"):
            self.term.bind(ev, getattr(self, "_key_" +
                           ev.strip("<>").replace("-", "_")
                           .replace("Return", "return")
                           .replace("BackSpace", "backspace")
                           .replace("Up", "up").replace("Down", "down")
                           .replace("Key", "key")
                           .replace("Button_1", "click")
                           .replace("Control_c", "ctrlc")))
        self._sel("TERMINAL")
        self.q = queue.Queue()
        self._poll()

    def _sel(self, name):   # active panel tab gets the accent
        self.active = name
        for n, lab in self._tabs.items():
            on = (n == name)
            animate_color(lab, "fg", C["fg_bright"] if on else C["fg_dim"])
            rule = getattr(self, "_tab_rules", {}).get(n)
            if rule is not None and rule.winfo_exists():
                animate_color(rule, "bg",
                              C["accent"] if on else C["panel"])

    def _prompt(self):
        d = os.path.basename(self.app.term_cwd) or self.app.term_cwd
        self.term.insert("end", f"{d}", "cwd")
        self.term.insert("end", " $ ")
        self.term.mark_set("input", "end-1c")
        self.term.see("end")

    def write(self, s, tag=None):
        try:
            if not self.term.winfo_exists():
                return
        except tk.TclError:
            return
        self.term.configure(state="normal")
        self.term.insert("end", s, tag)
        self.term.see("end")

    def _poll(self):
        # a theme rebuild destroys this panel; the pending after() callback
        # still fires, so bail out if our widgets are gone
        try:
            if not self.winfo_exists() or not self.term.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            while True:
                s, tag = self.q.get_nowait()
                if s == "\x00PROMPT":
                    self._prompt()
                else:
                    self.write(s, tag)
        except queue.Empty:
            pass
        try:
            self.after(80, self._poll)
        except tk.TclError:
            pass

    def start(self):
        self.write("Integrated terminal\n\n")
        self._prompt()

    def _run_cmd(self, cmd):
        self.history.append(cmd)
        self.hidx = len(self.history)
        if cmd.strip() == "clear":
            self.term.delete("1.0", "end")
            self._prompt()
            return
        if cmd.strip().startswith("cd "):
            tgt = os.path.expanduser(cmd.strip()[3:] or "~")
            tgt = tgt if os.path.isabs(tgt) else os.path.join(
                self.app.term_cwd, tgt)
            if os.path.isdir(tgt):
                self.app.term_cwd = os.path.abspath(tgt)
            else:
                self.write(f"cd: no such directory: {tgt}\n", "err")
            self._prompt()
            return
        if self.proc:
            self.write("…a process is still running (Ctrl+C to stop)\n",
                       "info")
            self._prompt()
            return

        def worker():
            try:
                self.proc = subprocess.Popen(
                    cmd, shell=True, cwd=self.app.term_cwd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, env={**os.environ, "TERM": "dumb"})
                for line in self.proc.stdout:
                    self.q.put((line, None))
                rc = self.proc.wait()
                if rc:
                    self.q.put((f"(exit code {rc})\n", "err"))
            except Exception as ex:  # noqa: BLE001
                self.q.put((f"{ex}\n", "err"))
            finally:
                self.proc = None
                self.q.put(("\x00PROMPT", None))

        threading.Thread(target=worker, daemon=True).start()

    # ---- key handlers ----
    def _key_return(self, _e):
        cmd = self.term.get("input", "end-1c")
        self.term.insert("end", "\n")
        self.term.mark_set("input", "end-1c")
        self._run_cmd(cmd)
        return "break"

    def _key_backspace(self, _e):
        if self.term.compare("insert", "<=", "input"):
            return "break"

    def _key_up(self, _e):
        if self.history and self.hidx > 0:
            self.hidx -= 1
            self.term.delete("input", "end")
            self.term.insert("input", self.history[self.hidx])
        return "break"

    def _key_down(self, _e):
        if self.hidx < len(self.history) - 1:
            self.hidx += 1
            self.term.delete("input", "end")
            self.term.insert("input", self.history[self.hidx])
        else:
            self.hidx = len(self.history)
            self.term.delete("input", "end")
        return "break"

    def _key_key(self, e):
        if len(e.char) and self.term.compare("insert", "<", "input"):
            self.term.mark_set("insert", "end")

    def _key_click(self, e):
        self.after(1, lambda: self.term.mark_set("insert", "end")
                   if self.term.compare("insert", "<", "input") else None)

    def _key_ctrlc(self, _e):
        if self.term.tag_ranges("sel"):
            return  # normal copy
        if self.proc:
            try:
                self.proc.send_signal(signal.SIGINT)
            except Exception:  # noqa: BLE001
                pass
            self.write("^C\n")
        else:
            self.term.insert("end", "^C\n")
            self._prompt()
        return "break"

    def clear(self):
        self.term.delete("1.0", "end")
        self._prompt()


# ------------------------------------------------------------------ #
#  Status bar                                                         #
# ------------------------------------------------------------------ #
class StatusBar(tk.Frame):
    H = 22

    def __init__(self, app):
        super().__init__(app, bg=C["statusbar"], height=self.H,
                         highlightthickness=1,
                         highlightbackground=C["border"])
        self.pack_propagate(False)
        self.app = app
        f = (app.f_ui[0], 9)
        self.branch = self._item("⎇ main", side="left")
        self.sync = self._item("⟳", side="left")
        self.errors = self._item("✖ 0   ⚠ 0", side="left")
        self.task = self._item("", side="left")
        self.agent = self._item("", side="left")
        self._agent_clear_job = None
        self.pos = self._item("Ln 1, Col 1", side="right")
        self._pad("right")
        self.lang = self._item("Plain Text", side="right")
        self.spaces = self._item("Spaces: 4", side="right")
        self.enc = self._item("UTF-8", side="right")
        self.zoom = self._item(
            f"{round(getattr(app, 'font_size', EDITOR_FONT_SIZE) / EDITOR_FONT_SIZE * 100)}%",
            side="right")
        self.opacity = self._item(
            f"Opacity {round(getattr(app, 'opacity', DEFAULT_OPACITY) * 100)}%",
            side="right")
        self.theme = self._item(
            f"Theme: {getattr(app, 'theme_name', DEFAULT_THEME).title()}",
            side="right")
        for w in (self.pos, self.lang, self.spaces, self.enc, self.zoom,
                  self.theme, self.opacity):
            w.configure(cursor="hand2")
        self.lang.bind("<Button-1>", lambda e: app.quick_open(">"))
        self.zoom.bind("<Button-1>", lambda e: app.reset_zoom())
        # click the chip to cycle grey -> black -> white
        self.theme.bind("<Button-1>", lambda e: app.cycle_theme())
        self.opacity.bind("<Button-1>", lambda e: app.fade(0.04))

    def _item(self, text, side):   # noqa: D401
        l = tk.Label(self, text=text, bg=C["statusbar"], fg=C["status_fg"],
                     font=(self.app.f_ui[0], 9))
        l.pack(side=side, padx=8)
        return l

    def _pad(self, side):
        tk.Label(self, text=" ", bg=C["statusbar"]).pack(side=side)

    def update(self, buf_name, line, col, modified):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self.pos.configure(text=f"Ln {line}, Col {col}")
        lang = "Plain Text"
        if buf_name and "." in buf_name:
            ext = buf_name.rsplit(".", 1)[-1].lower()
            lang = LANG_NAMES.get(ext, ext.upper())
        self.lang.configure(text=lang)

    # Friday's own live-activity chip: "Creating app.py…" / "Writing app.py…",
    # a highlighted status-bar entry so it's clear, at a glance, that an
    # edit appearing in the Explorer/editor is Friday working, not something
    # else, and what it's actually doing.
    _AGENT_KIND_COLORS = {
        "create": ("#2e7d46", "#eafff1"),
        "write":  ("#9a6a16", "#fff6e6"),
    }

    def set_agent_status(self, text, kind="write"):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        bg, fg = self._AGENT_KIND_COLORS.get(kind, self._AGENT_KIND_COLORS["write"])
        self.agent.configure(text=f" {text} ", bg=bg, fg=fg)
        if self._agent_clear_job:
            try:
                self.after_cancel(self._agent_clear_job)
            except Exception:  # noqa: BLE001
                pass
        self._agent_clear_job = self.after(6000, self.clear_agent_status)

    def clear_agent_status(self):
        self._agent_clear_job = None
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self.agent.configure(text="", bg=C["statusbar"])


# ------------------------------------------------------------------ #
#  Overlay input dialog (Quick Open / Command Palette / Go to Line)   #
# ------------------------------------------------------------------ #
class QuickOpen(tk.Toplevel):
    def __init__(self, app, initial=""):
        super().__init__(app)
        self.app = app
        app.quickopen_open = True
        self.overrideredirect(True)
        self.configure(bg=C["border"])
        self.initial = initial
        self.transient(app)
        w, h = 560, 300
        x = app.winfo_rootx() + max(20, (app.winfo_width() - w) // 2)
        y = app.winfo_rooty() + 34
        self.geometry(f"{w}x{h}+{x}+{y}")

        wrap = tk.Frame(self, bg=C["input"], highlightthickness=1,
                        highlightbackground=C["accent"])
        wrap.pack(fill="x", padx=1, pady=1)
        self.entry = tk.Entry(wrap, bg=C["input"], fg=C["fg_bright"],
                              insertbackground=C["fg_bright"], relief="flat",
                              font=(app.f_ui[0], 12))
        self.entry.pack(fill="x", ipady=8, ipadx=8)
        self.entry.insert(0, initial)
        self.entry.selection_range(0, "end")
        self.listbox = tk.Listbox(self, bg=C["sidebar"], fg=C["fg"],
                                  relief="flat", highlightthickness=0,
                                  selectbackground=C["list_sel"],
                                  selectforeground=C["fg_bright"],
                                  font=app.f_ui, activestyle="none", bd=0)
        self.listbox.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        self.entry.bind("<KeyRelease>", self._filter)
        self.entry.bind("<Down>", lambda e: self._move(1))
        self.entry.bind("<Up>", lambda e: self._move(-1))
        self.entry.bind("<Return>", self._accept)
        self.entry.bind("<Escape>", lambda e: self._close())
        self.listbox.bind("<Double-1>", self._accept)
        self.listbox.bind("<Escape>", lambda e: self._close())
        self.bind("<FocusOut>", lambda e: self.after(150, self._maybe_close))
        self._refresh()
        self.entry.focus_set()
        self.entry.icursor("end")

    def _maybe_close(self):
        try:
            if self.focus_get() is None:
                self._close()
        except tk.TclError:
            pass

    def _items(self):
        q = self.entry.get()
        if q.startswith(">"):
            needle = q[1:].strip().lower()
            return [("cmd", label, fn) for label, fn in self.app.COMMANDS
                    if needle in label.lower()]
        if q.startswith(":"):
            return []
        needle = q.lower()
        out = []
        for p in self.app.workspace_files:
            rel = os.path.relpath(p, self.app.root_dir)
            if needle in rel.lower() or needle in os.path.basename(p).lower():
                out.append(("file", rel, p))
            if len(out) >= 60:
                break
        return out

    def _refresh(self):
        self.items = self._items()
        self.listbox.delete(0, "end")
        q = self.entry.get()
        if q.startswith(":"):
            self.listbox.insert("end", f"  Go to line {q[1:] or '…'}")
            return
        if not self.items:
            self.listbox.insert("end", "  No matching results")
            return
        for kind, label, _ in self.items:
            pre = "  ⌘  " if kind == "cmd" else "  📄 "
            self.listbox.insert("end", pre + label)
        self.listbox.selection_set(0)
        self.listbox.activate(0)

    def _filter(self, _e):
        self._refresh()

    def _move(self, d):
        sel = self.listbox.curselection()
        i = (sel[0] if sel else 0) + d
        i = max(0, min(self.listbox.size() - 1, i))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(i)
        self.listbox.see(i)
        return "break"

    def _accept(self, _e=None):
        q = self.entry.get()
        if q.startswith(":"):
            try:
                self.app.goto_line(int(q[1:]))
            except ValueError:
                pass
            self._close()
            return
        sel = self.listbox.curselection()
        if not sel or not self.items or sel[0] >= len(self.items):
            self._close()
            return
        kind, _label, payload = self.items[sel[0]]
        self._close()
        if kind == "cmd":
            self.after(1, payload)
        else:
            self.app.open_file(payload)

    def _close(self):
        self.app.quickopen_open = False
        self.destroy()
        self.app.focus_editor()


# ------------------------------------------------------------------ #
#  Editor area (tabs + code + minimap + welcome + find bar)           #
# ------------------------------------------------------------------ #
class MediaView(tk.Frame):
    """Canvas viewer for images and rendered PDF pages."""

    LEVELS = (0.125, 0.25, 0.33, 0.5, 0.67, 1.0, 1.5, 2.0, 3.0, 4.0, 8.0)

    def __init__(self, parent, app):
        super().__init__(parent, bg=C["editor"])
        self.app = app
        self.buf = None
        self.photo = None
        self.zoom_level = 1.0
        self.fit_mode = True
        self.page = 1
        self.pages = 1
        self._err = None

        bar = tk.Frame(self, bg=C["tabbar"], height=30)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.bar = bar

        def btn(parent, text, cmd):
            b = tk.Label(parent, text=text, bg=C["tabbar"], fg=C["fg_dim"],
                         font=app.f_ui, padx=7, pady=4, cursor="hand2")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", lambda e: b.configure(fg=C["fg_bright"]))
            b.bind("<Leave>", lambda e: b.configure(fg=C["fg_dim"]))
            return b

        # page navigation lives in its own box so hiding it for images does
        # not disturb the packing order of everything after it
        self.pagebox = tk.Frame(bar, bg=C["tabbar"])
        btn(self.pagebox, "\u25c0", self.prev_page)
        self.lbl_page = tk.Label(self.pagebox, text="", bg=C["tabbar"],
                                 fg=C["fg"], font=app.f_ui, padx=2, width=7)
        self.lbl_page.pack(side="left")
        btn(self.pagebox, "\u25b6", self.next_page)
        tk.Frame(self.pagebox, bg=C["border"], width=1).pack(
            side="left", fill="y", padx=8, pady=6)

        self.zoombox = tk.Frame(bar, bg=C["tabbar"])
        self.zoombox.pack(side="left")
        btn(self.zoombox, "\u2212", self.zoom_out)
        self.lbl_zoom = tk.Label(self.zoombox, text="100%", bg=C["tabbar"],
                                 fg=C["fg"], font=app.f_ui, width=6)
        self.lbl_zoom.pack(side="left")
        btn(self.zoombox, "+", self.zoom_in)
        btn(self.zoombox, "Fit", self.zoom_fit)
        btn(self.zoombox, "1:1", self.zoom_actual)
        self.lbl_info = tk.Label(self.zoombox, text="", bg=C["tabbar"],
                                 fg=C["fg_dim"], font=app.f_ui, padx=10)
        self.lbl_info.pack(side="left")

        self.b_ext = tk.Label(bar, text="Open externally \u2197",
                              bg=C["tabbar"], fg=C["fg_dim"], font=app.f_ui,
                              padx=10, cursor="hand2")
        self.b_ext.pack(side="right")
        self.b_ext.bind("<Button-1>", lambda e: self.open_external())

        wrap = tk.Frame(self, bg=C["editor"])
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=C["panel"], highlightthickness=0, bd=0)
        self.vbar = ttk.Scrollbar(wrap, orient="vertical",
                                  command=self.canvas.yview)
        self.hbar = ttk.Scrollbar(self, orient="horizontal",
                                  command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vbar.set,
                              xscrollcommand=self.hbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="left", fill="y")
        self.hbar.pack(fill="x")

        self.canvas.bind("<ButtonPress-1>", self._pan_start)
        self.canvas.bind("<B1-Motion>", self._pan_move)
        self.canvas.bind("<Configure>", lambda e: self._refit())
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind(seq, self._wheel)

    # ---------------- loading ----------------
    def open(self, buf):
        self.buf = buf
        self.page = 1
        self.fit_mode = True
        self._err = None
        if buf.get("media") == "pdf":
            try:
                with open(buf["path"], "rb") as fh:
                    self.pages = pdf_page_count(fh.read())
            except OSError:
                self.pages = 1
        else:
            self.pages = 1
        self._show_page_controls(buf.get("media") == "pdf")
        self.load()

    def _show_page_controls(self, on):
        if on:
            self.pagebox.pack(side="left", before=self.zoombox)
        else:
            self.pagebox.pack_forget()

    def load(self):
        buf = self.buf
        if not buf:
            return
        self.canvas.delete("all")
        try:
            if buf.get("media") == "pdf":
                self._load_pdf_page()
            else:
                img, w, h, note = load_image(buf["path"])
                self.base = img
                self.base_size = (w, h)
                self.note = note
        except Exception as ex:  # noqa: BLE001
            self.base = None
            self._err = str(ex)
            self._draw_error()
            return
        self._refit(force=True)

    def _load_pdf_page(self):
        dpi = int(max(60, min(300, 110 * (self.zoom_level or 1))))
        png = pdf_render_page(self.buf["path"], self.page,
                              self.app.pdf_tmpdir(), dpi)
        if not png:
            raise DecodeError("no PDF renderer available")
        img = tk.PhotoImage(file=png)
        self.base = img
        self.base_size = (img.width(), img.height())
        self.note = ""

    # ---------------- drawing ----------------
    def _draw_error(self):
        self.canvas.delete("all")
        name = os.path.basename(self.buf["path"]) if self.buf else ""
        msg = self._err or "cannot display"
        lines = [f"Cannot display {name}", "", msg, ""]
        if self.buf and self.buf.get("media") == "pdf":
            lines += ["No PDF renderer was found on this system.",
                      "Install one of: poppler-utils (pdftoppm), mupdf-tools",
                      "(mutool), Ghostscript, or ImageMagick.", "",
                      "The text of this PDF was extracted instead - see the",
                      "tab opened alongside this one."]
        else:
            lines += ["This format needs a decoder that is not available.",
                      "Install Pillow (pip install pillow) or ImageMagick",
                      "to view it."]
        lines += ["", "Use 'Open externally' to view it in another app."]
        self.canvas.create_text(
            24, 24, anchor="nw", width=760, fill=C["fg_dim"],
            font=self.app.f_ui, text="\n".join(lines))
        self.lbl_info.configure(text="unsupported")
        self.lbl_zoom.configure(text="--")

    def _scaled(self):
        """PhotoImage at the current zoom, using integer zoom/subsample."""
        z = self.zoom_level
        img = self.base
        if abs(z - 1.0) < 0.01:
            return img
        num, den = self._ratio(z)
        if num > 1:
            img = img.zoom(num)
        if den > 1:
            img = img.subsample(den)
        return img

    @staticmethod
    def _ratio(z):
        best = (1, 1)
        err = 9e9
        for den in range(1, 9):
            for num in range(1, 9):
                e = abs(num / den - z)
                if e < err:
                    err, best = e, (num, den)
        return best

    def _refit(self, force=False):
        if getattr(self, "base", None) is None:
            return
        if self.fit_mode or force:
            cw = max(1, self.canvas.winfo_width())
            ch = max(1, self.canvas.winfo_height())
            bw, bh = self.base_size
            if self.fit_mode and bw and bh:
                scale = min(cw / bw, ch / bh, 1.0)
                self.zoom_level = min(self.LEVELS,
                                      key=lambda L: abs(L - scale))
        self._render()

    def _render(self):
        if getattr(self, "base", None) is None:
            return
        self.photo = self._scaled()
        self.canvas.delete("all")
        w, h = self.photo.width(), self.photo.height()
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        x = max(0, (cw - w) // 2)
        y = max(0, (ch - h) // 2)
        self.canvas.create_image(x, y, anchor="nw", image=self.photo)
        self.canvas.configure(scrollregion=(0, 0, max(w, cw), max(h, ch)))
        bw, bh = self.base_size
        self.lbl_zoom.configure(text=f"{int(self.zoom_level * 100)}%")
        note = getattr(self, "note", "")
        self.lbl_info.configure(
            text=f"{bw} x {bh}" + (f"   \u00b7   {note}" if note else ""))
        self.lbl_page.configure(text=f"{self.page} / {self.pages}")

    # ---------------- interaction ----------------
    def zoom_in(self):
        self.fit_mode = False
        nxt = [L for L in self.LEVELS if L > self.zoom_level + 0.001]
        if nxt:
            self.zoom_level = nxt[0]
            self._reload_if_pdf()

    def zoom_out(self):
        self.fit_mode = False
        prev = [L for L in self.LEVELS if L < self.zoom_level - 0.001]
        if prev:
            self.zoom_level = prev[-1]
            self._reload_if_pdf()

    def zoom_fit(self):
        self.fit_mode = True
        self._refit(force=True)

    def zoom_actual(self):
        self.fit_mode = False
        self.zoom_level = 1.0
        self._reload_if_pdf()

    def _reload_if_pdf(self):
        # re-render PDFs at the new dpi so text stays sharp
        if self.buf and self.buf.get("media") == "pdf" and not self._err:
            try:
                self._load_pdf_page()
            except Exception:  # noqa: BLE001
                pass
            self.zoom_level = 1.0 if self.fit_mode else self.zoom_level
            self._render()
        else:
            self._render()

    def next_page(self):
        if self.page < self.pages:
            self.page += 1
            self.load()

    def prev_page(self):
        if self.page > 1:
            self.page -= 1
            self.load()

    def _wheel(self, e):
        if e.state & 0x4:            # Ctrl+wheel = zoom
            if getattr(e, "delta", 0) > 0 or e.num == 4:
                self.zoom_in()
            else:
                self.zoom_out()
            return "break"
        d = -1 if (getattr(e, "delta", 0) > 0 or e.num == 4) else 1
        self.canvas.yview_scroll(d, "units")
        return "break"

    def _pan_start(self, e):
        self.canvas.scan_mark(e.x, e.y)

    def _pan_move(self, e):
        self.canvas.scan_dragto(e.x, e.y, gain=1)

    def open_external(self):
        if self.buf and self.buf.get("path"):
            self.app.open_url("file://" + os.path.abspath(self.buf["path"]))


# ------------------------------------------------------------------ #
#  Friday AI Chat -- a real docked chat panel, only built while this IDE  #
#  is agent-controlled. Talks to the exact same AI brain (Gemini/     #
#  Groq/Mistral + full tool access) the floating circle uses, via a   #
#  direct in-process call (app._agent_host.ask) -- Friday and this IDE   #
#  are one process now, so there's no socket in between anymore.      #
# ------------------------------------------------------------------ #
class ChatSidePanel(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=C["chat"], highlightthickness=1,
                         highlightbackground=C["border"])
        self.app = app
        self._pending_bubble = None  # the "Friday is thinking..." bubble Frame,
        # swapped out once the real reply lands.
        self._decision_row = None   # the live options/custom-text widget
        # row embedded after the current pending decision's bubble, if
        # any -- see _show_decision_options/_dismiss_decision_options.
        self._status_row = None     # the persistent build-status
        # checklist widget, created lazily on first use -- see
        # update_build_status.
        self._status_labels = {}    # phase name -> its Label widget,
        # inside _status_row, so later updates recolor in place instead
        # of appending a new block every time.

        header = tk.Frame(self, bg=C["chat"], height=38)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        self._avatar_badge(header, size=22).pack(side="left", padx=(12, 8))
        tk.Label(header, text="FRIDAY AI CHAT", bg=C["chat"],
                 fg=C["fg_bright"], font=(app.f_ui[0], 10, "bold")
                 ).pack(side="left")
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x", side="top")

        # Scrollable message list: a Text widget with each message
        # embedded as a real widget ("window_create") so every bubble can
        # have its own avatar + wrapped, padded, colored background --
        # plain inserted text can't do per-message styling like this.
        body = tk.Frame(self, bg=C["chat"])
        body.pack(fill="both", expand=True, side="top")
        self.log = tk.Text(body, bg=C["chat"], relief="flat", bd=0,
                           wrap="word", state="disabled", undo=False,
                           highlightthickness=0, cursor="arrow",
                           padx=0, pady=8)
        vsb = tk.Scrollbar(body, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        entry_row = tk.Frame(self, bg=C["chat"])
        entry_row.pack(fill="x", side="bottom", padx=10, pady=10)
        self.entry = tk.Entry(entry_row, bg=C["input"], fg=C["fg"],
                              relief="flat", insertbackground=C["fg"],
                              highlightthickness=1,
                              highlightbackground=C["border"],
                              highlightcolor=C["accent"],
                              font=(app.f_ui[0], 11))
        self.entry.insert(0, "")
        self.entry.pack(fill="x", expand=True, side="top", ipady=7)
        self._placeholder = "Ask Friday to build, edit, or explain something..."
        self._show_placeholder()
        self.entry.bind("<FocusIn>", self._clear_placeholder)
        self.entry.bind("<FocusOut>", self._maybe_restore_placeholder)
        self.entry.bind("<Return>", self._send)

        self._add_bubble(
            "friday", "Ask me to build, edit, or explain something in this "
            "workspace \u2014 I have the same file tools here as in our "
            "normal conversation.", pending=True)

    # -- tiny diamond "Friday" avatar, reused for the header + every bubble --
    def _avatar_badge(self, parent, size=20):
        cv = tk.Canvas(parent, width=size, height=size, bg=C["chat"],
                       highlightthickness=0)
        pad = 2
        cv.create_polygon(
            size / 2, pad, size - pad, size / 2, size / 2, size - pad,
            pad, size / 2, fill=C["accent"], outline="")
        cv.create_text(size / 2, size / 2, text="F", fill=C["fg_bright"],
                       font=(self.app.f_ui[0], max(7, int(size * 0.4)), "bold"))
        return cv

    # -- "you" avatar: a plain vector person glyph, not an emoji -- some
    # systems/fonts have no color-emoji glyph installed and silently draw
    # an empty box instead, so this is drawn with plain Canvas shapes
    # (same technique as the Friday diamond above) for guaranteed rendering.
    def _you_avatar_badge(self, parent, size=20):
        cv = tk.Canvas(parent, width=size, height=size, bg=C["chat"],
                       highlightthickness=0)
        cv.create_oval(1, 1, size - 1, size - 1, fill=C["list_sel"], outline="")
        head_r = size * 0.16
        cx, cy = size / 2, size * 0.36
        cv.create_oval(cx - head_r, cy - head_r, cx + head_r, cy + head_r,
                       fill=C["fg_bright"], outline="")
        cv.create_arc(size * 0.16, size * 0.42, size * 0.84, size * 1.05,
                     start=0, extent=180, fill=C["fg_bright"], outline="",
                     style="chord")
        return cv

    def _show_placeholder(self):
        self.entry.configure(fg=C["fg_faint"])
        self.entry.delete(0, "end")
        self.entry.insert(0, self._placeholder)
        self._showing_placeholder = True

    def _clear_placeholder(self, event=None):
        if getattr(self, "_showing_placeholder", False):
            self.entry.delete(0, "end")
            self.entry.configure(fg=C["fg"])
            self._showing_placeholder = False

    def _maybe_restore_placeholder(self, event=None):
        if not self.entry.get().strip():
            self._show_placeholder()

    # -- message bubbles ----------------------------------------------
    def _add_bubble(self, role, text, pending=False):
        """role is 'you' or 'friday'. Returns the Frame so a pending bubble
        can be located and swapped out later."""
        row = tk.Frame(self.log, bg=C["chat"])
        is_you = (role == "you")

        # (No fixed-size wrapper Frame here -- an empty Frame with only a
        # width set and no height, under pack_propagate(False), collapses
        # to near-zero height and hides whatever's inside it. The avatar
        # widget's own natural size is used instead.)
        if is_you:
            self._you_avatar_badge(row, size=22).pack(
                side="left", anchor="n", padx=(12, 8), pady=(2, 0))
        else:
            self._avatar_badge(row, size=22).pack(
                side="left", anchor="n", padx=(12, 8), pady=(2, 0))

        bubble_bg = C["list_sel"] if is_you else C["panel"]
        text_fg = C["fg_faint"] if pending else C["fg"]
        bubble = tk.Label(row, text=text, bg=bubble_bg, fg=text_fg,
                          font=(self.app.f_ui[0], 10), justify="left",
                          wraplength=230, padx=10, pady=8, anchor="w")
        bubble.pack(side="left", fill="x", expand=True, padx=(0, 12))

        self.log.configure(state="normal")
        self.log.window_create("end", window=row, stretch=True)
        self.log.insert("end", "\n")
        self.log.configure(state="disabled")
        self.log.see("end")
        return row, bubble

    def _send(self, event=None):
        text = self.entry.get().strip()
        if not text or getattr(self, "_showing_placeholder", False):
            return
        self.entry.delete(0, "end")
        self._submit_text(text)

    def _submit_text(self, text):
        """Shared by the normal typed-and-Enter path (_send above) and
        every "answer" to a pending decision -- clicking one of
        _show_decision_options' option buttons, or typing something into
        its own custom-text box and submitting that instead. Either way
        it's handled completely indistinguishably from a message the
        user typed into the main entry box: same "you" bubble, same
        AIWorker round trip, same memory logging on the other end (see
        agent_overlay._ide_chat_ask) -- a clicked option is just a
        shortcut for typing that exact text.

        A new real message always supersedes whatever decision widget
        was still showing from the turn before -- the user is moving on,
        answered or not, the same reasoning _ide_chat_decision_tracker's
        own cancel() already uses on the backend side.
        """
        self._dismiss_decision_options()
        self._add_bubble("you", text)
        self._pending_bubble = self._add_bubble(
            "friday", "Friday is thinking\u2026", pending=True)

        host = getattr(self.app, "_agent_host", None)
        if host is None:
            self._resolve_pending(
                "Friday's chat channel isn't available this run \u2014 talk to "
                "Friday in its normal window instead.", ok=False)
            return

        def on_done(ok, result, options=None):
            # `on_done` can be invoked from whatever thread finishes the
            # AI call (Friday's own background worker thread, normally) --
            # marshal back onto Tk's thread before touching any widget.
            try:
                self.after(0, lambda: self._resolve_pending(result, ok, options))
            except (RuntimeError, tk.TclError):
                pass

        try:
            host.ask(text, on_done)
        except Exception as exc:  # noqa: BLE001
            self._resolve_pending(str(exc), ok=False)

    def receive_proactive_message(self, text, options=None):
        """Appends a new 'friday' bubble that wasn't triggered by
        anything the user just typed here -- e.g. the 2-minute
        unanswered-pause autonomy rule's follow-up once Friday decides
        to proceed on its own (see agent_tools.notify_ide_chat /
        _AgentHost.register_ide_chat_notify). `options`, when given,
        renders the same clickable-option widget a normal in-turn
        decision pause would (see _show_decision_options). Safe to call
        even while an unrelated reply is already pending in this same
        panel."""
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if not text:
            return
        self._dismiss_decision_options()
        self._add_bubble("friday", text)
        if options:
            self._show_decision_options(options)
        self.log.see("end")

    # -- Task 65's Permission mechanism: inline decision options -------
    # Mirrors this agent's own ask_user tool -- a handful of concrete,
    # clickable options plus a free-text box for anything else -- rather
    # than leaving the user to retype a whole answer by hand. Lives
    # right in the chat log as its own small embedded widget (same
    # window_create technique _add_bubble uses), directly under whatever
    # bubble posed the question, never a separate tab/panel -- it's part
    # of the same conversation, not a different surface.
    def _show_decision_options(self, options):
        self._dismiss_decision_options()
        row = tk.Frame(self.log, bg=C["chat"])
        inner = tk.Frame(row, bg=C["panel"])
        inner.pack(side="left", fill="x", expand=True, padx=(34, 12), pady=(0, 6))

        for opt in options:
            btn = tk.Button(
                inner, text=opt, anchor="w", justify="left", wraplength=190,
                bg=C["list_sel"], fg=C["fg_bright"], activebackground=C["accent"],
                activeforeground=C["fg_bright"], relief="flat", bd=0,
                font=(self.app.f_ui[0], 10), padx=10, pady=6, cursor="hand2",
                command=lambda o=opt: self._choose_decision_option(o))
            btn.pack(fill="x", padx=8, pady=(8, 0))

        custom_row = tk.Frame(inner, bg=C["panel"])
        custom_row.pack(fill="x", padx=8, pady=8)
        custom_entry = tk.Entry(
            custom_row, bg=C["input"], fg=C["fg"], relief="flat",
            insertbackground=C["fg"], highlightthickness=1,
            highlightbackground=C["border"], highlightcolor=C["accent"],
            font=(self.app.f_ui[0], 10))
        custom_entry.pack(side="left", fill="x", expand=True, ipady=5)

        def _submit_custom(event=None):
            val = custom_entry.get().strip()
            if val:
                self._choose_decision_option(val)

        custom_entry.bind("<Return>", _submit_custom)
        send_btn = tk.Button(
            custom_row, text="Send", bg=C["accent"], fg=C["fg_bright"],
            activebackground=C["accent"], activeforeground=C["fg_bright"],
            relief="flat", bd=0, font=(self.app.f_ui[0], 10, "bold"),
            padx=10, cursor="hand2", command=_submit_custom)
        send_btn.pack(side="left", padx=(6, 0))

        self.log.configure(state="normal")
        self.log.window_create("end", window=row, stretch=True)
        self.log.insert("end", "\n")
        self.log.configure(state="disabled")
        self.log.see("end")
        self._decision_row = row

    def _dismiss_decision_options(self):
        """Removes the live decision widget, if any -- called whenever a
        new real message supersedes it (answered via a button, via its
        own custom-text box, or the user just typed something new into
        the main entry instead of using either)."""
        if self._decision_row is not None:
            try:
                self._decision_row.destroy()
            except tk.TclError:
                pass
            self._decision_row = None

    def _choose_decision_option(self, text):
        """An option button (or the custom-text box's Send/Return) was
        used to answer a pending decision -- dismiss the widget and send
        `text` through exactly the same path a typed message would take
        (_submit_text itself dismisses it again, redundantly but
        harmlessly, since _submit_text's own supersede-the-old-decision
        step runs first regardless of how this got triggered)."""
        self._dismiss_decision_options()
        self._submit_text(text)

    # -- Build Protocol status checklist --------------------------------
    # A small, persistent, in-place-updated block (never a new one added
    # per update) showing exactly where a multi-layer build actually is
    # -- Frontend/Backend/Storage -- so the user can tell at a glance
    # without reading back through the whole scrolling conversation. See
    # development_skill.md's Build Protocol section and
    # agent_tools.ide_report_build_status, which is what actually drives
    # this.
    _STATUS_PHASE_LABELS = (
        ("frontend", "Frontend"), ("backend", "Backend"), ("storage", "Storage/Database"))
    _STATUS_GLYPHS = {
        "not_started": ("\u2b1c", "fg_faint"), "in_progress": ("\U0001f504", "fg"),
        "done": ("\u2705", "fg_bright"), "blocked": ("\u26a0", "term_err"),
    }

    def update_build_status(self, phase, status, detail=""):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if self._status_row is None:
            row = tk.Frame(self.log, bg=C["chat"])
            inner = tk.Frame(row, bg=C["panel"])
            inner.pack(side="left", fill="x", expand=True, padx=(34, 12), pady=(0, 6))
            tk.Label(inner, text="BUILD STATUS", bg=C["panel"], fg=C["fg_dim"],
                     font=(self.app.f_ui[0], 9, "bold"), anchor="w"
                     ).pack(fill="x", padx=10, pady=(8, 2))
            for key, label in self._STATUS_PHASE_LABELS:
                lab = tk.Label(
                    inner, text=f"\u2b1c  {label}", bg=C["panel"], fg=C["fg_faint"],
                    font=(self.app.f_ui[0], 10), justify="left", wraplength=210,
                    anchor="w")
                lab.pack(fill="x", padx=10, pady=(0, 6))
                self._status_labels[key] = lab
            self.log.configure(state="normal")
            self.log.window_create("end", window=row, stretch=True)
            self.log.insert("end", "\n")
            self.log.configure(state="disabled")
            self._status_row = row
        lab = self._status_labels.get(phase)
        if lab is None:
            return
        glyph, color_key = self._STATUS_GLYPHS.get(status, ("\u2b1c", "fg_faint"))
        name = dict(self._STATUS_PHASE_LABELS)[phase]
        text = f"{glyph}  {name}"
        if detail:
            text += f" \u2014 {detail}"
        try:
            lab.configure(text=text, fg=C[color_key])
        except tk.TclError:
            pass
        self.log.see("end")

    def _resolve_pending(self, text, ok, options=None):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if self._pending_bubble is not None:
            row, bubble = self._pending_bubble
            try:
                if ok:
                    bubble.configure(text=text, fg=C["fg"])
                else:
                    bubble.configure(text=f"\u26a0 {text}", fg=C["term_err"])
            except tk.TclError:
                pass
            self._pending_bubble = None
        if ok and options:
            self._show_decision_options(options)
        self.log.see("end")


class EditorArea(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=C["editor"], highlightthickness=0)
        self.app = app
        self._hl_job = None
        self._gutter_job = None
        self._loading = False

        # tab strip
        self.tabbar = tk.Frame(self, bg=C["tabbar"], height=34)
        self.tabbar.pack(fill="x")
        self.tabbar.pack_propagate(False)
        self.tabs_row = tk.Frame(self.tabbar, bg=C["tabbar"])
        self.tabs_row.pack(side="left", fill="y")
        self.tabs_row.bind("<Double-1>", lambda e: app.new_file())

        # breadcrumb
        self.crumb = tk.Label(self, text="", bg=C["editor"],
                              fg=C["fg_faint"],
                              font=(app.f_ui[0], *ts(-1)), anchor="w",
                              padx=sp("lg"), pady=sp("xs"))
        self.crumb.pack(fill="x")

        # code row: gutter | text | vbar | minimap
        self.code_row = tk.Frame(self, bg=C["editor"])
        self.code_row.pack(fill="both", expand=True)
        self.gutter = tk.Canvas(self.code_row, width=52, bg=C["editor"],
                                highlightthickness=0, bd=0)
        self.gutter.pack(side="left", fill="y")
        self.text = tk.Text(self.code_row, bg=C["editor"], fg=C["text_fg"],
                            insertbackground=C["caret"], relief="flat", bd=0,
                            font=app.f_mono, undo=True, wrap="none",
                            selectbackground=C["sel"],
                            selectforeground=C["fg_bright"],
                            inactiveselectbackground=C["sel_inactive"],
                            padx=4, pady=2, insertwidth=2, maxundo=200, highlightthickness=0)
        mono = app.f_mono
        for tag, color in TAG_COLOR.items():
            self.text.tag_configure(tag, foreground=color)
        self.text.tag_configure("current_line", background=C["cur_line"])
        self.text.tag_configure("findall", background=C["findall"])
        self.text.tag_configure("findcur", background=C["findcur"])

        self.vbar = ttk.Scrollbar(self.code_row, orient="vertical",
                                  command=self._yview)
        self.text.configure(yscrollcommand=self._on_scroll,
                            xscrollcommand=self._on_xscroll)
        self.text.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="left", fill="y")

        self.minimap = tk.Text(self.code_row, width=max(12, round(14 * UI_SCALE)),
                               font=(mono[0], max(2, round(2 * UI_SCALE))), bg=C["editor"],
                               fg=C["fg_dim"], relief="flat", bd=0,
                               state="disabled", cursor="arrow",
                               padx=0, pady=0, highlightthickness=0)
        for tag, color in TAG_COLOR.items():
            self.minimap.tag_configure(tag, foreground=color)
        self.minimap_visible = True
        self.minimap.pack(side="left", fill="y")

        # image / PDF viewer, shown instead of the code row when needed
        self.media = MediaView(self, app)
        self.media_visible = False

        # shown when no file is open at all
        self.empty = tk.Frame(self, bg=C["editor"])
        self.empty_label = tk.Label(
            self.empty, text=EMPTY_HINT, bg=C["editor"], fg=C["fg_faint"],
            font=(app.f_ui[0], max(9, UI_FONT_SIZE)), justify="center")
        self.empty_label.place(relx=0.5, rely=0.45, anchor="center")
        self.empty_visible = False
        self.minimap.bind("<Button-1>", self._mm_jump)
        self.minimap.bind("<B1-Motion>", self._mm_jump)

        self.hbar = ttk.Scrollbar(self, orient="horizontal",
                                  command=self.text.xview)
        self.hbar.pack(fill="x")

        # find bar (floating)
        self.findbar = tk.Frame(self.code_row, bg=C["sidebar"],
                                highlightthickness=1,
                                highlightbackground=C["border"])
        self._build_findbar()

        # events
        t = self.text
        t.bind("<KeyRelease>", self._on_release)
        t.bind("<KeyPress>", self._on_press)
        t.bind("<ButtonRelease>", lambda e: self.app.update_status())
        t.bind("<Motion>", lambda e: None)
        t.bind("<Configure>", lambda e: self._queue_gutter())
        t.bind("<<Modified>>", self._on_modified)
        t.bind("<Button-3>", self._context_menu)
        t.bind("<Control-space>", lambda e: self.app.autocomplete(trigger=True))
        t.bind("<MouseWheel>", lambda e: self._queue_gutter())
        t.bind("<Button-4>", lambda e: self._queue_gutter())
        t.bind("<Button-5>", lambda e: self._queue_gutter())

    # ---------------- scrolling / gutter ----------------
    def _yview(self, *args):
        self.text.yview(*args)
        if getattr(self, "minimap", None) is not None:
            self.minimap.yview(*args)
        self._queue_gutter()

    def _on_xscroll(self, *a):
        # Tk can fire this while the widget tree is still being built
        bar = getattr(self, "hbar", None)
        if bar is not None:
            bar.set(*a)

    def _on_scroll(self, first, last):
        if getattr(self, "vbar", None) is None:
            return
        self.vbar.set(first, last)
        try:
            if getattr(self, "minimap", None) is not None:
                self.minimap.yview_moveto(float(first))
        except tk.TclError:
            pass
        self._queue_gutter()

    def _queue_gutter(self):
        if self._gutter_job:
            return
        self._gutter_job = self.after_idle(self._draw_gutter)

    def _draw_gutter(self):
        self._gutter_job = None
        try:
            if not self.gutter.winfo_exists() or not self.text.winfo_exists():
                return
        except tk.TclError:
            return
        g, t = self.gutter, self.text
        g.delete("all")
        try:
            total = int(t.index("end-1c").split(".")[0])
        except tk.TclError:
            return
        width = max(46, 14 + 8 * len(str(total)))
        if g.winfo_reqwidth() != width:
            g.configure(width=width)
        cur = t.index("insert").split(".")[0]
        f = (self.app.f_mono[0], max(6, self.app.font_size - 1))
        i = t.index("@0,0")
        while True:
            d = t.dlineinfo(i)
            if d is None:
                break
            y = d[1]
            ln = str(i).split(".")[0]
            g.create_text(width - 8, y + 1, anchor="ne", text=ln,
                          fill=C["gutter_cur"] if ln == cur else C["gutter"],
                          font=f)
            i = t.index(f"{i}+1line")

    # ---------------- minimap ----------------
    def _mm_jump(self, e):
        h = max(1, self.minimap.winfo_height())
        frac = max(0.0, min(1.0, e.y / h))
        self.text.yview_moveto(frac)
        self._queue_gutter()

    def _mm_sync(self):
        if not self.minimap_visible:
            return
        mm, t = self.minimap, self.text
        content = t.get("1.0", "end-1c")
        first = t.yview()[0]
        mm.configure(state="normal")
        mm.delete("1.0", "end")
        if len(content) <= MAX_MINIMAP_CHARS:
            # copying every syntax tag across is far more expensive than the
            # 2px preview is worth, so the minimap renders as plain text
            mm.insert("1.0", content)
        mm.configure(state="disabled")
        try:
            mm.yview_moveto(first)
        except tk.TclError:
            pass

    def toggle_minimap(self):
        self.minimap_visible = not self.minimap_visible
        if self.minimap_visible:
            self.minimap.pack(side="left", fill="y", after=self.vbar)
            self._mm_sync()
        else:
            self.minimap.pack_forget()

    # ---------------- editing events ----------------
    PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}

    def _on_press(self, e):
        app = self.app
        if app.completion_active:
            if e.keysym in ("Up", "Down", "Return", "Tab", "Escape"):
                return app.completion_key(e)
        if e.state & 0x4:  # Ctrl held — let shortcuts pass
            return
        t = self.text
        ch = e.char
        if e.keysym == "Return":
            line_start = t.index("insert linestart")
            before = t.get(line_start, "insert")
            indent = re.match(r"[ \t]*", before).group(0)
            extra = "    " if before.rstrip().endswith(":") else ""
            t.insert("insert", "\n" + indent + extra)
            self._after_edit()
            return "break"
        if e.keysym == "Tab":
            try:
                first = t.index("sel.first linestart")
                last = t.index("sel.last lineend")
                lines = int(last.split(".")[0]) - int(first.split(".")[0])
                if lines > 0:
                    for n in range(int(first.split(".")[0]),
                                   int(last.split(".")[0]) + 1):
                        t.insert(f"{n}.0", "    ")
                    return "break"
            except tk.TclError:
                pass
            t.insert("insert", "    ")
            self._after_edit()
            return "break"
        if e.keysym == "ISO_Left_Tab" or (e.keysym == "Tab" and e.state & 0x1):
            return "break"
        if ch in self.PAIRS:
            close = self.PAIRS[ch]
            try:
                sel0, sel1 = t.index("sel.first"), t.index("sel.last")
                selected = t.get(sel0, sel1)
                t.delete(sel0, sel1)
                t.insert("insert", ch + selected + close)
                t.mark_set("insert", f"insert-{1 + len(selected)}c")
            except tk.TclError:
                t.insert("insert", ch + close)
                t.mark_set("insert", "insert-1c")
            self._after_edit()
            return "break"
        if ch in (")", "]", "}"):
            if t.get("insert", "insert+1c") == ch:
                t.mark_set("insert", "insert+1c")
                return "break"
        if e.keysym == "BackSpace":
            prev = t.get("insert-1c", "insert")
            nxt = t.get("insert", "insert+1c")
            if prev in self.PAIRS and self.PAIRS[prev] == nxt:
                t.delete("insert-1c", "insert+1c")
                self._after_edit()
                return "break"

    def _on_release(self, e):
        if e.keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R",
                        "Alt_L", "Alt_R"):
            return
        self.app.update_status()
        self._mark_current_line()
        if e.keysym in ("Up", "Down", "Left", "Right", "Prior", "Next",
                        "Home", "End"):
            self._queue_gutter()
            return
        self._after_edit()
        if len(e.char) and (e.char.isalnum() or e.char in "_."):
            self.app.autocomplete()

    def _after_edit(self):
        self._queue_gutter()
        if self._hl_job:
            self.after_cancel(self._hl_job)
        self._hl_job = self.after(180, self.highlight)

    def _on_modified(self, _e):
        if self._loading:
            self.text.edit_modified(False)
            return
        self.app.mark_dirty()
        self.text.edit_modified(False)

    def _mark_current_line(self):
        t = self.text
        t.tag_remove("current_line", "1.0", "end")
        t.tag_add("current_line", "insert linestart", "insert lineend+1c")
        t.tag_lower("current_line", "sel")

    # ---------------- syntax highlighting ----------------
    def highlight(self):
        self._hl_job = None
        try:
            if not self.text.winfo_exists():
                return
        except tk.TclError:
            return
        t = self.text
        buf = self.app.current_buffer()
        if not buf or buf["kind"] != "file":
            self._mm_sync()
            return
        code = t.get("1.0", "end-1c")
        for tag in TAG_COLOR:
            t.tag_remove(tag, "1.0", "end")
        lang = lang_for(buf["name"])
        rx = get_lexer(lang) if lang else None
        if rx is not None and len(code) < MAX_HIGHLIGHT_CHARS:
            # Tk resolves a "1.0+Nc" index by walking N characters, so using
            # character offsets here is O(n) per tag and quadratic overall.
            # Precompute line starts once and emit cheap "line.col" indices.
            starts = [0]
            for line in code.split("\n"):
                starts.append(starts[-1] + len(line) + 1)
            import bisect as _bisect

            def idx(off):
                ln = _bisect.bisect_right(starts, off) - 1
                return f"{ln + 1}.{off - starts[ln]}"

            spans = {}
            for m in rx.finditer(code):
                tag = GROUP_TAG.get(m.lastgroup)
                if tag:
                    spans.setdefault(tag, []).extend(
                        (idx(m.start()), idx(m.end())))
            for kind, rng in spans.items():
                if rng:
                    t.tag_add(kind, *rng)
        t.tag_raise("sel")
        self._mark_current_line()
        self._mm_sync()

    # ---------------- find bar ----------------
    def _build_findbar(self):
        f = self.findbar
        self.fe = tk.Entry(f, bg=C["input"], fg=C["fg"], relief="flat",
                           insertbackground=C["fg"], width=24,
                           font=self.app.f_ui, highlightthickness=1,
                           highlightcolor=C["accent"],
                           highlightbackground=C["border"])
        self.fcount = tk.Label(f, text="", bg=C["sidebar"], fg=C["fg_dim"],
                               font=(self.app.f_ui[0], 9), width=8)
        self.re = None

        def btn(txt, cmd, w=2):
            b = tk.Label(f, text=txt, bg=C["sidebar"], fg=C["fg_dim"],
                         font=(self.app.f_ui[0], 10), width=w, cursor="hand2")
            b.pack(side="left", padx=1, pady=2)
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", lambda e, bb=b: bb.configure(bg=C["hover"]))
            b.bind("<Leave>", lambda e, bb=b: bb.configure(bg=C["sidebar"]))
            return b

        self.fe.pack(side="left", padx=(6, 2), ipady=3)
        self.fcount.pack(side="left")
        btn("▲", lambda: self.find_next(-1))
        btn("▼", lambda: self.find_next(1))
        btn("×", self.hide_find)
        self.fe.bind("<KeyRelease>", lambda e: self.do_find())
        self.fe.bind("<Return>", lambda e: self.find_next(1))
        self.fe.bind("<Shift-Return>", lambda e: self.find_next(-1))
        self.fe.bind("<Escape>", lambda e: self.hide_find())

        # replace row
        f2 = tk.Frame(self.findbar, bg=C["sidebar"])
        self.re_bar = f2
        self.re = tk.Entry(f2, bg=C["input"], fg=C["fg"], relief="flat",
                           insertbackground=C["fg"], width=24,
                           font=self.app.f_ui, highlightthickness=1,
                           highlightcolor=C["accent"],
                           highlightbackground=C["border"])
        self.re.pack(side="left", padx=(6, 2), ipady=3)

        def rbtn(txt, cmd):
            b = tk.Label(f2, text=txt, bg=C["sidebar"], fg=C["fg_dim"],
                         font=(self.app.f_ui[0], 9), cursor="hand2", padx=4)
            b.pack(side="left", padx=1, pady=2)
            b.bind("<Button-1>", lambda e: cmd())
            return b
        rbtn("Replace", self.replace_one)
        rbtn("Replace All", self.replace_all)
        self.fe.bind("<Escape>", lambda e: self.hide_find(), add="+")
        if self.re:
            self.re.bind("<Escape>", lambda e: self.hide_find())

    def show_find(self, replace=False):
        self.findbar.place(relx=1.0, x=-14, y=6, anchor="ne")
        if replace:
            self.re_bar.pack(fill="x")
        try:
            sel = self.text.get("sel.first", "sel.last")
            self.fe.delete(0, "end")
            self.fe.insert(0, sel)
        except tk.TclError:
            pass
        self.fe.focus_set()
        self.fe.selection_range(0, "end")
        self.do_find()

    def hide_find(self):
        self.findbar.place_forget()
        self.re_bar.pack_forget()
        self.text.tag_remove("findall", "1.0", "end")
        self.text.tag_remove("findcur", "1.0", "end")
        self.text.focus_set()

    def do_find(self):
        t, q = self.text, self.fe.get()
        t.tag_remove("findall", "1.0", "end")
        t.tag_remove("findcur", "1.0", "end")
        if not q:
            self.fcount.configure(text="")
            return
        nocase = not any(ch.isupper() for ch in q)  # smart case
        self._matches = []
        pos = "1.0"
        while True:
            i = t.search(q, pos, stopindex="end", nocase=nocase)
            if not i:
                break
            j = f"{i}+{len(q)}c"
            t.tag_add("findall", i, j)
            self._matches.append(i)
            pos = j
        self._find_idx = -1
        self.fcount.configure(text=f"{len(self._matches)} found"
                              if self._matches else "No results")
        t.tag_raise("sel")

    def find_next(self, d=1):
        if not getattr(self, "_matches", None):
            return
        self._find_idx = (self._find_idx + d) % len(self._matches)
        i = self._matches[self._find_idx]
        t = self.text
        t.tag_remove("findcur", "1.0", "end")
        t.tag_add("findcur", i, f"{i}+{len(self.fe.get())}c")
        t.mark_set("insert", i)
        t.see(i)
        self.fcount.configure(
            text=f"{self._find_idx + 1} of {len(self._matches)}")

    def replace_one(self):
        self.find_next(1)
        if self._matches:
            i = self._matches[self._find_idx]
            q = self.fe.get()
            self.text.delete(i, f"{i}+{len(q)}c")
            self.text.insert(i, self.re.get())
            self.do_find()

    def replace_all(self):
        q = self.fe.get()
        if not q:
            return
        content = self.text.get("1.0", "end-1c")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content.replace(q, self.re.get()))
        self.do_find()
        self.highlight()

    # ---------------- context menu ----------------
    def _context_menu(self, e):
        app = self.app
        m = tk.Menu(self, tearoff=0, bg=C["sidebar"], fg=C["fg"],
                    activebackground=C["list_sel"],
                    activeforeground=C["fg_bright"], bd=1, font=app.f_ui)
        m.add_command(label="Cut", command=lambda: self.text.event_generate("<<Cut>>"))
        m.add_command(label="Copy", command=lambda: self.text.event_generate("<<Copy>>"))
        m.add_command(label="Paste", command=lambda: self.text.event_generate("<<Paste>>"))
        m.add_separator()
        m.add_command(label="Find", command=lambda: app.show_find(False))
        m.add_command(label="Replace", command=lambda: app.show_find(True))
        m.add_separator()
        m.add_command(label="Run File", command=app.run_file)
        m.add_separator()
        m.add_command(label="Command Palette…   Ctrl+Shift+P",
                      command=lambda: app.quick_open(">"))
        m.tk_popup(e.x_root, e.y_root)

    # ---------------- tabs ----------------
    def show_empty(self):
        """No file open: blank surface, no phantom untitled buffer."""
        self.hide_media()
        if not self.empty_visible:
            self.code_row.pack_forget()
            self.hbar_row_forget()
            self.empty.pack(fill="both", expand=True)
            self.empty_visible = True
        self.redraw_tabs()
        self.crumb.configure(text="")

    def hide_empty(self):
        if self.empty_visible:
            self.empty.pack_forget()
            self.code_row.pack(fill="both", expand=True)
            self.hbar_row_restore()
            self.empty_visible = False

    def show_media(self, buf):
        """Swap the code row out for the image/PDF viewer."""
        if not self.media_visible:
            self.code_row.pack_forget()
            self.hbar_row_forget()
            self.media.pack(fill="both", expand=True)
            self.media_visible = True
        self.media.open(buf)

    def hide_media(self):
        if self.media_visible:
            self.media.pack_forget()
            self.code_row.pack(fill="both", expand=True)
            self.hbar_row_restore()
            self.media_visible = False

    def hbar_row_forget(self):
        try:
            self.hbar.pack_forget()
        except Exception:  # noqa: BLE001
            pass

    def hbar_row_restore(self):
        try:
            self.hbar.pack(fill="x")
        except Exception:  # noqa: BLE001
            pass

    def redraw_tabs(self):
        for w in self.tabs_row.winfo_children():
            w.destroy()
        for i, buf in enumerate(self.app.buffers):
            self._make_tab(i, buf)

    def _make_tab(self, i, buf):
        app = self.app
        active = (i == app.current)
        bg = C["tab_active"] if active else C["tab_inactive"]
        fg = C["fg_bright"] if active else C["tab_in_fg"]
        tab = tk.Frame(self.tabs_row, bg=bg)
        tab.pack(side="left", fill="y")
        accent = tk.Frame(tab, bg=C["accent"] if active else bg,
                          height=max(2, band(2)))
        accent.pack(fill="x")
        row = tk.Frame(tab, bg=bg)
        row.pack(fill="both", expand=True)
        dots = tk.Label(row, text="\u25cf" if buf.get("modified") else " ",
                        bg=bg, fg=C["warn"] if buf.get("modified") else C["fg_dim"],
                        font=(app.f_ui[0], 7))
        dots.pack(side="left", padx=(sp("md"), 0))
        name = tk.Label(row, text=buf["name"], bg=bg, fg=fg,
                        font=(app.f_ui[0], *ts(0)), padx=sp("sm"))
        name.pack(side="left")
        close = tk.Label(row, text="\u00d7", bg=bg, fg=C["fg_faint"],
                         font=(app.f_ui[0], 11), padx=sp("sm"),
                         cursor="hand2")
        close.pack(side="left", pady=sp("xs"))
        if not active:
            hover_fx(tab, bg_from=bg, bg_to=C["hover"],
                     targets=[tab, row, name, dots, close])
        for wdg in (tab, row, name, dots):
            wdg.bind("<Button-1>", lambda e, n=i: app.switch_tab(n))
            wdg.bind("<Button-2>", lambda e, n=i: app.close_tab(n))
            wdg.bind("<Button-3>", lambda e, n=i: app.tab_menu(e, n))
        close.bind("<Button-1>", lambda e, n=i: app.close_tab(n))
        close.bind("<Enter>", lambda e: close.configure(bg=C["hover"],
                                                        fg=C["fg_bright"]))
        close.bind("<Leave>", lambda e: close.configure(
            bg=C["tab_active"] if i == app.current else C["tab_inactive"],
            fg=C["tab_in_fg"]))
        sep = tk.Frame(self.tabs_row, bg=C["border_soft"], width=1)
        sep.pack(side="left", fill="y")


def _rounded_rect_points(x1, y1, x2, y2, r):
    """Point list for a canvas create_polygon(..., smooth=True) that
    renders as a rounded rectangle -- a pill shape when `r` is half the
    height. Standard Tk canvas trick: smooth=True turns the sharp corner
    pairs below into quadratic curves."""
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


class MinimizedPill(tk.Toplevel):
    """Small pill-shaped indicator shown just under Friday's floating
    circle while an IDEApp window is minimized (see
    IDEApp.minimize_to_pill/_show_pill). Connected to the circle by a
    thin vertical line drawn in the same small window, so it never needs
    to track the circle moving (the circle is fixed in place anyway).
    Hovering the pill speaks its label aloud through Friday's own voice
    (best-effort, silently does nothing if that's not available); a
    plain click restores the real window via `on_restore`.

    Every panel Friday tracks -- this IDE and any app_panels.py-managed
    app (Chrome/Notepad/Calculator) -- shares one single vertical stack
    of pills under the circle instead of each subsystem positioning its
    own independently (which could overlap): STACK_STEP is the fixed
    vertical spacing between consecutive slots in that shared stack, and
    reposition() lets an already-shown pill be shifted to a new slot
    without rebuilding it, used when a pill in the middle of the stack
    is restored and everything below it needs to shift up to close the
    gap. The actual slot-index bookkeeping lives centrally in
    agent_tools.py's _AgentHost (get_pill_slot/release_pill_slot),
    shared by both this module and app_panels.py.
    """

    LINE_LEN = 26     # vertical gap between the circle's bottom edge and the pill
    PILL_W = 112
    PILL_H = 34
    STACK_GAP = 8     # vertical gap between consecutive stacked pills
    STACK_STEP = LINE_LEN + PILL_H + STACK_GAP
    HOVER_SPEAK_DELAY_MS = 220  # avoids speaking on a quick mouse pass-through

    def __init__(self, master, label, agent_host, circle_bottom, on_restore):
        super().__init__(master)
        self._label = label
        self._agent_host = agent_host
        self._on_restore = on_restore
        self._hover_job = None
        self._restoring = False  # one-shot guard, see _on_click

        self.withdraw()  # positioned before first shown, no flash at (0, 0)
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass

        win_w = self.PILL_W + 4
        win_h = self.LINE_LEN + self.PILL_H + 2
        cx, bottom_y = circle_bottom
        x = int(cx - win_w / 2)
        y = int(bottom_y)

        # True per-pixel window shaping (so only the line + pill are ever
        # visible, nothing rectangular around them) is a Windows-only Tk
        # feature (-transparentcolor); gracefully falls back to a plain
        # small opaque panel, matching the IDE's own theme, everywhere
        # else (Linux/macOS Tk can't punch a hole in a window's shape
        # without extra non-standard libraries this app doesn't depend
        # on elsewhere).
        magic = "#010203"
        self._shaped = False
        try:
            self.wm_attributes("-transparentcolor", magic)
            self._shaped = True
        except tk.TclError:
            pass
        bg = magic if self._shaped else C["panel"]
        self.configure(bg=bg)

        self.canvas = tk.Canvas(self, width=win_w, height=win_h, bg=bg,
                                 highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        line_x = win_w / 2
        self.canvas.create_line(line_x, 0, line_x, self.LINE_LEN,
                                 fill=C["border"], width=2)

        px1, py1 = 2, self.LINE_LEN
        px2, py2 = win_w - 2, win_h - 2
        radius = (py2 - py1) / 2  # fully rounded ends -- a true pill
        self._pill_fill = C["panel"]
        self._pill_hover_fill = C["tab_active"]
        self._pill_shape = self.canvas.create_polygon(
            _rounded_rect_points(px1, py1, px2, py2, radius),
            smooth=True, fill=self._pill_fill, outline=C["border"])
        self._pill_text = self.canvas.create_text(
            (px1 + px2) / 2, (py1 + py2) / 2, text=label,
            fill=C["fg"], font=("Segoe UI", 9, "bold"))

        self.geometry(f"{win_w}x{win_h}+{max(0, x)}+{max(0, y)}")
        self.deiconify()

        for item in (self._pill_shape, self._pill_text):
            self.canvas.tag_bind(item, "<Enter>", self._on_hover_enter)
            self.canvas.tag_bind(item, "<Leave>", self._on_hover_leave)
            self.canvas.tag_bind(item, "<Button-1>", self._on_click)

    def reposition(self, circle_bottom):
        """Moves this already-shown pill to a different slot under the
        circle without rebuilding it -- used to keep the shared
        IDE+app-panels pill stack gap-free: when a pill in the middle of
        the stack is restored, everything below it shifts up by one
        slot via this, rather than leaving a visible gap where it used
        to be."""
        cx, bottom_y = circle_bottom
        win_w = self.PILL_W + 4
        x = int(cx - win_w / 2)
        y = int(bottom_y)
        try:
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            pass

    # Maps a panel-status name to the pill outline color used to show it
    # at a glance without needing to restore the real window -- reuses
    # the theme's existing semantic colors rather than inventing new
    # ones, so pill status stays visually consistent with everything
    # else the IDE already paints those colors for (the terminal's own
    # error/success text, warning banners, etc).
    _STATUS_COLORS = {
        "normal": "border",    # nothing to report -- today's plain default
        "waiting": "warn",     # paused, needs the user's permission to continue
        "done": "success",     # finished a task while minimized
        "error": "term_err",   # hit a problem it can't get past on its own
    }

    def set_status(self, status):
        """Recolors this pill's outline to reflect what the panel it
        represents is doing right now -- see _STATUS_COLORS. Safe to
        call at any point in the pill's life, including right after
        construction (IDEApp._show_pill does this immediately, so a
        freshly-shown pill reflects whatever status was already active
        rather than resetting to "normal" every time it's re-minimized).
        Best-effort: silently does nothing on an unrecognized status or
        if the underlying Tk widget is already gone.
        """
        color_key = self._STATUS_COLORS.get(status)
        if color_key is None:
            return
        try:
            self.canvas.itemconfig(self._pill_shape, outline=C[color_key])
        except tk.TclError:
            pass

    def _on_hover_enter(self, _event=None):
        self.canvas.itemconfig(self._pill_shape, fill=self._pill_hover_fill)
        if self._hover_job is not None:
            self.after_cancel(self._hover_job)
        self._hover_job = self.after(self.HOVER_SPEAK_DELAY_MS, self._announce)

    def _on_hover_leave(self, _event=None):
        self.canvas.itemconfig(self._pill_shape, fill=self._pill_fill)
        if self._hover_job is not None:
            self.after_cancel(self._hover_job)
            self._hover_job = None

    def _announce(self):
        self._hover_job = None
        if self._agent_host is not None:
            try:
                self._agent_host.speak_label(self._label)
            except Exception:  # noqa: BLE001
                pass

    def _on_click(self, _event=None):
        # One-shot guard: this pill is about to be destroyed by its own
        # on_restore() callback, but that destruction isn't necessarily
        # instantaneous (it can hop across the IDE/app_panels bridge
        # first) -- without this, any stray extra <Button-1> delivered
        # to this exact widget before that teardown lands (e.g. a fast
        # double click, or any other source of a repeat event) would
        # call on_restore() a second time for the same pill. Restoring
        # is only ever supposed to happen once per pill, no matter how
        # many click events it happens to receive.
        if self._restoring:
            return
        self._restoring = True
        if self._hover_job is not None:
            self.after_cancel(self._hover_job)
            self._hover_job = None
        self._on_restore()


class _ActiveGlowAnimator:
    """Drives a slow, smooth pulsing-brightness border animation for
    whichever single panel is currently Friday's active one -- the one
    sitting in the unified placement system's one center/maximized
    slot (agent_tools.py's _maximized_panel_key), the panel Friday is
    "currently working on" per the user's own request. Every panel
    type gets this the same way: the IDE itself (see IDEApp's own
    set_active_panel) and every app_panels.py panel (EmbeddedAppPanel/
    CustomNotepadPanel's own set_active_panel) -- each just owns one of
    these and hands it a `set_color(hex)` callback that paints its own
    particular flavor of border (the IDE recolors its native Tk
    highlightbackground/-color; app_panels.py panels recolor the thin
    white margin around their titlebar/slot, both already tracked
    elsewhere -- this class doesn't need to know or care which).

    Deliberately plain composition, not a mixin/base class, since the
    panel types it serves don't otherwise share a common ancestor
    (IDEApp vs. tk.Toplevel-based app panels) and forcing one just for
    this one animation would be more invasive than it's worth.
    """

    PERIOD_S = 1.6             # one full dim-to-bright-to-dim pulse cycle
    TICK_MS = 40               # ~25fps -- smooth without being wasteful
    BASE_COLOR = (168, 85, 247)  # "#a855f7", violet -- used nowhere else
    #  in the app, so it reads unambiguously as "this is the active
    #  panel" and never gets confused with Friday's own busy/ok/error
    #  status colors (blue/green/red) or a plain idle white border.
    MIN_BRIGHTNESS = 0.55
    MAX_BRIGHTNESS = 1.0

    def __init__(self, owner, set_color):
        self._owner = owner          # any widget with .after()/.winfo_exists()
        self._set_color = set_color  # hex string -> None, paints the border
        self._job = None
        self._t0 = None

    def start(self):
        """No-op if already running -- safe to call repeatedly."""
        if self._job is not None:
            return
        self._t0 = time.time()
        self._tick()

    def stop(self):
        """Cancels the pulse. Does NOT repaint anything itself -- the
        caller is responsible for restoring whatever static border
        color should show once the pulse stops (e.g. plain white, or
        Friday's own current busy/ok/error status color), since that's
        something only the caller actually knows."""
        if self._job is not None:
            try:
                self._owner.after_cancel(self._job)
            except Exception:  # noqa: BLE001
                pass
            self._job = None

    @property
    def running(self):
        return self._job is not None

    def _tick(self):
        self._job = None
        try:
            if not self._owner.winfo_exists():
                return
        except tk.TclError:
            return
        phase = (time.time() - self._t0) % self.PERIOD_S / self.PERIOD_S
        span = self.MAX_BRIGHTNESS - self.MIN_BRIGHTNESS
        brightness = self.MIN_BRIGHTNESS + span * (0.5 - 0.5 * math.cos(phase * 2 * math.pi))
        r, g, b = self.BASE_COLOR
        hexcolor = "#%02x%02x%02x" % (int(r * brightness), int(g * brightness), int(b * brightness))
        try:
            self._set_color(hexcolor)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._job = self._owner.after(self.TICK_MS, self._tick)
        except tk.TclError:
            pass


def compute_agent_controlled_bounds(sw, sh):
    """(x, y, w, h) for Friday's own agent-controlled IDE layout --
    pinned to the exact on-screen layout measured from the user's own
    reference screenshot: nearly fills the screen, but leaves a clear,
    deliberate margin on every edge -- a bit more at the top (where
    Friday's floating circle lives, fixed in the top-right corner) and
    on the left than at the bottom/right -- so the window never looks
    like it's touching or crowding the circle. Expressed as fractions
    of the actual screen size, not a fixed pixel size scaled by DPI, so
    it lands in exactly the same relative spot on any monitor.

    Pulled out of IDEApp.__init__ into its own free function so
    agent_tools.py's unified panel-placement system can compute "the
    IDE's own natural/default size" -- the shared reference every panel
    maximizes to fill -- as a fixed, nameable concept, without needing
    a live IDEApp instance to measure (the IDE might not even be open
    right now, or might currently be shrunk down into one of the
    smaller side slots because something else is the active/maximized
    panel instead).
    """
    w = int(sw * 0.897)
    h = int(sh * 0.894)
    x = int(sw * 0.054)
    y = int(sh * 0.074)
    return (x, y, w, h)


# ------------------------------------------------------------------ #
#  The application                                                    #
# ------------------------------------------------------------------ #
class IDEApp(tk.Tk):
    _BORDER_WHITE = "#ffffff"  # the IDE's own window border -- see __init__

    def __init__(self, start_dir=None, agent_controlled=False, agent_host=None,
                 initial_bounds=None):
        super().__init__()
        self.title(APP_NAME)
        # When True (only set when Friday launched this via Agent Mode), the
        # titlebar's minimize/maximize/close buttons are replaced with an
        # inert placeholder instead -- see _winctrl_zone below (this
        # window is opened/closed by Friday itself, "turn on/close agent
        # mode", never by clicking a titlebar button). A plain
        # `python ide.py` run (or the value defaulting to False) keeps
        # the normal buttons.
        self._agent_controlled = agent_controlled
        # Friday itself, in-process -- this IDE is one of Friday's own windows,
        # not a separate app it merely happens to talk to. `agent_host`
        # is whatever object agent_overlay.py hands in when it builds
        # this IDEApp (see AgentHost there): `.ask(text, on_done)` routes
        # a chat-panel message through the exact same AI brain the
        # floating circle uses, and `.on_ide_closed()` tells Friday this
        # window is gone the instant it is, however that happens. None
        # for a plain standalone `python ide.py` run -- the chat panel
        # still shows while agent-controlled, it just reports a clear
        # error instead of hanging.
        self._agent_host = agent_host

        # Persists independently of whether a pill is actually showing
        # right now, so a status set while this window is maximized (or
        # between one minimize and the next) is still there, correctly
        # colored, the moment _show_pill() next builds a fresh pill --
        # see set_panel_status()/_show_pill().
        self._pill = None
        self._panel_status = "normal"

        # ---- HiDPI / resolution -------------------------------------
        # Scale every Tk dimension to the real pixel density so the UI is
        # crisp (and physically the same size) on high-DPI panels.

        global UI_SCALE
        try:
            dpi = self.winfo_fpixels("1i")           # px per inch
            self.ui_scale = max(1.0, min(3.0, dpi / 96.0))
        except tk.TclError:
            self.ui_scale = 1.0
        # Now that the process is DPI aware the OS no longer stretches our
        # bitmap, so we must scale the type ourselves to keep it physically
        # the right size -- and it renders natively sharp. If awareness
        # could not be enabled the OS is still scaling for us, so we pin the
        # ratio to 96dpi instead to avoid scaling twice (blurry AND huge).
        if DPI_AWARE:
            self.tk.call("tk", "scaling", self.ui_scale * 1.3333)
        else:
            self.ui_scale = 1.0
            self.tk.call("tk", "scaling", 1.3333)
        UI_SCALE = self.ui_scale

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if initial_bounds is not None:
            # Friday's unified panel-placement system (agent_tools.py)
            # has already decided exactly where this window should land
            # -- e.g. this IDE isn't the first panel of the session, so
            # it's opening straight into one of the smaller side slots
            # instead of its own normal near-fullscreen spot. Bypasses
            # both formulas below entirely so there's no flash of the
            # "wrong" size before a later resize corrects it.
            final_x, final_y, w, h = initial_bounds
        elif self._agent_controlled:
            final_x, final_y, w, h = compute_agent_controlled_bounds(sw, sh)
        else:
            base_w, base_h = 1680, 1050
            w = min(int(base_w * self.ui_scale), int(sw * 0.94))
            h = min(int(base_h * self.ui_scale), int(sh * 0.94))
            final_x, final_y = (sw - w) // 2, max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{final_x}+{final_y}")
        # Remembered so the open/close pop animation below can relax this
        # back to effectively none while the window is deliberately
        # smaller than this floor (snapped down near the circle), then
        # restore it exactly once the window is back at a real usable
        # size -- window managers (and Tk itself) clamp any geometry()
        # request below the current minsize() right back up to it, which
        # would otherwise make the window jump straight to this floor
        # size instead of visibly starting tiny, over by the circle.
        self._real_minsize = (int(900 * self.ui_scale), int(560 * self.ui_scale))
        self.minsize(*self._real_minsize)
        # Remembered for _maybe_play_open_animation() below: the window's
        # real, final size/position, laid out here before any open-pop
        # animation might temporarily shrink it back down near Friday's
        # floating circle.
        self._final_geom = (final_x, final_y, w, h)

        # ---- floating frameless panel + translucency ----------------
        self.theme_name = DEFAULT_THEME
        self.opacity = DEFAULT_OPACITY
        self._anim_active = False  # True only mid open/close pop animation
        self._maximized = False
        self._normal_geom = None
        # White border around the whole IDE window, same as every
        # app_panels.py panel (Chrome/Notepad/Calculator) -- per explicit
        # user request that the IDE's own window get the same white
        # border styling, not just Friday-drawn app panels.
        self.configure(bg=self._BORDER_WHITE)
        try:
            self.overrideredirect(True)               # no OS title bar
            self.attributes("-alpha", self.opacity)   # translucent
        except tk.TclError:
            pass
        # -alpha set before the window is mapped is dropped by some window
        # managers, so assert it again once the panel is actually on screen.
        self.after(60, self._apply_opacity)
        self.after(400, self._apply_opacity)
        # Outline around the whole floating panel. Agent-controlled runs
        # get a thicker ring so it reads as a real "glow" once _apply_glow
        # starts recoloring it to reflect Friday's state; a plain
        # `python ide.py` run keeps the old thin static outline. White by
        # default/idle (see _GLOW_IDLE below), same white border every
        # other panel gets -- set_friday_status still recolors it to
        # blue/green/red while actually busy/succeeding/failing, that
        # functional feedback is unrelated to and unaffected by the
        # white-border styling change.
        self._glow_thickness = 4 if self._agent_controlled else 1
        try:
            self.configure(highlightthickness=self._glow_thickness,
                           highlightbackground=self._BORDER_WHITE,
                           highlightcolor=self._BORDER_WHITE)
        except tk.TclError:
            pass
        # Pulsing "this is Friday's current active panel" border, shown
        # whenever this IDE is the one sitting in the unified placement
        # system's center/maximized slot *and* Friday's own live status
        # (see set_friday_status below) is idle -- a busy/responding/
        # error status color always takes priority over the pulse,
        # exactly like it already took priority over the old plain
        # static white border. See _ActiveGlowAnimator's own docstring.
        self._is_active_panel = False
        self._friday_glow_state = "idle"
        self._friday_glow_is_error = False
        self._active_glow = _ActiveGlowAnimator(self, self._paint_active_glow_color)

        # ---- fonts: JetBrains Mono for code, a clean sans for chrome ----
        fams = set(tkfont.families())
        pick = lambda *names: next((n for n in names if n in fams), names[-1])
        # "JetBrains Mono NL" is the no-ligature cut shipped by some distros.
        mono = pick("JetBrains Mono", "JetBrainsMono Nerd Font",
                    "JetBrains Mono NL", "Cascadia Code", "Fira Code",
                    "Source Code Pro", "Consolas", "Menlo",
                    "DejaVu Sans Mono", "Liberation Mono", "Courier New")
        self.font_family = mono
        self.jetbrains = mono.startswith("JetBrains")
        # Chrome face: menus, tabs, sidebar, status bar, dialogs, and chat
        # prose. "Segoe UI" is the native Windows 10/11 UI font; the rest
        # are cross-platform fallbacks so this still looks right in dev.
        ui_sans = pick("Segoe UI", "Segoe UI Variable Text", "Segoe UI Semibold",
                       "Helvetica Neue", "Arial", "Noto Sans",
                       "DejaVu Sans", "Liberation Sans", "Tahoma", mono)
        self.ui_font_family = ui_sans if UI_FONT_PROPORTIONAL else mono
        self.f_ui = (self.ui_font_family, UI_FONT_SIZE)
        self.font_size = zoomed_pt()               # 12pt baseline @ 75%
        self.f_mono = (mono, self.font_size)

        self.root_dir = os.path.abspath(start_dir or os.getcwd())
        self.term_cwd = self.root_dir
        self.buffers = []           # dicts: name, path, kind, content, modified
        self.current = -1
        # ---- agent activity visualization (see "agent activity" below) ----
        self._type_jobs = {}        # tree node id -> scheduled .after() job
        self._write_anim_jobs = {}  # id(buf) -> scheduled .after() job
        self._agent_highlight_node = None
        # normalized abs path -> full final content, for a disk write
        # WorkspaceFS already made for Friday whose on-screen typewriter
        # animation either hasn't started yet or is still mid-flight.
        # Registered synchronously the instant the real disk write
        # happens (see WorkspaceFS.write/create_file), independent of
        # whatever Tk-thread marshalling/animation scheduling follows --
        # see _flush_agent_write()'s docstring for why this exists.
        self._pending_agent_writes = {}
        self.untitled_n = 0
        self.quickopen_open = False
        self.completion = None
        self.workspace_files = []
        self._watch_job = None
        _refresh_guide_color()
        self.fs = WorkspaceFS(self)    # sandboxed file ops -- Friday's own API
        self.fs_clip = None            # (path, "copy"|"cut")
        self.task_proc = None          # running build/run process
        self.server_url = None         # detected dev-server URL
        self.auto_open_browser = True
        self._task_url_opened = False

        self._mc = None  # context menu ref
        self._style_scrollbars()
        self._build_menubar()
        self._build_statusbar()
        self._build_body()
        self._bind_shortcuts()

        self._add_resize_grips()
        self.show_sidebar_mode("explorer")
        self._load_current(force=True)      # start with no buffer open
        self.after(120, self._round_corners)
        # Alt+F4 / window manager close must go through the unsaved check
        # (standalone) or be refused outright in favor of Friday's own
        # agent_mode_off() tool (agent-controlled) -- see
        # _human_requested_close()'s docstring.
        self.protocol("WM_DELETE_WINDOW", self._human_requested_close)
        self._start_watcher()
        if self._agent_controlled:
            self.set_friday_status("idle", False)  # starting color, before the
            # first real push from Friday (see set_friday_status below)

        if os.environ.get("IDE_DEMO"):
            self.after(500, self._plant_demo)

        # The whole chrome above (menubar, sidebar, editor, chat panel,
        # statusbar) is already fully built and sized at this point --
        # exactly what the open-pop animation below needs before it can
        # briefly shrink the window down near the circle and ease it
        # back out, without the editor/sidebar/chat widget tree itself
        # reflowing at animation frequency (see _show_launch_curtain).
        self._maybe_play_open_animation()

    # ---------------- styling helpers ----------------
    def _style_scrollbars(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("Vertical.TScrollbar", background=C["scroll"],
                    troughcolor=C["editor"], bordercolor=C["editor"],
                    arrowcolor=C["scroll"], relief="flat", borderwidth=0,
                    lightcolor=C["editor"], darkcolor=C["editor"],
                    gripcount=0)
        s.configure("Horizontal.TScrollbar", background=C["scroll"],
                    troughcolor=C["editor"], bordercolor=C["editor"],
                    arrowcolor=C["scroll"], relief="flat", borderwidth=0,
                    lightcolor=C["editor"], darkcolor=C["editor"],
                    gripcount=0)
        s.map("Vertical.TScrollbar",
              background=[("active", C["scroll_hover"]),
                          ("pressed", C["scroll_hover"])])
        s.map("Horizontal.TScrollbar",
              background=[("active", C["scroll_hover"]),
                          ("pressed", C["scroll_hover"])])

    def style_tree(self, parent=None):
        s = ttk.Style(self)
        s.configure("Treeview", background=C["sidebar"],
                    fieldbackground=C["sidebar"], foreground=C["fg"],
                    borderwidth=0, font=self.f_ui,
                    rowheight=max(24, round(27 * self.ui_scale)),
                    indent=max(14, round(16 * self.ui_scale)))
        try:
            s.configure("Treeview", arrowcolor=C["fg_dim"])
        except tk.TclError:
            pass
        s.map("Treeview", background=[("selected", C["list_sel"])],
              foreground=[("selected", C["fg_bright"])])
        s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    def flat_button(self, parent, text, cmd, secondary=False):
        bg = C["sidebar"] if secondary else C["accent_btn"]
        hb = C["accent_btn"] if secondary else C["accent_hover"]
        b = tk.Label(parent, text=text, bg=bg, fg=C["fg_bright"],
                     font=self.f_ui, padx=12, pady=5, cursor="hand2",
                     highlightthickness=1 if secondary else 0,
                     highlightbackground=C["border"])
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(bg=hb))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        return b

    # ---------------- menu bar ----------------
    def _build_menubar(self):
        bar = tk.Frame(self, bg=C["menubar"], height=band(34))
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        logo = tk.Canvas(bar, width=band(22), height=band(22),
                         bg=C["menubar"], highlightthickness=0)
        logo.pack(side="left", padx=(sp("md"), sp("xs")), pady=sp("xs"))
        draw_icon(logo, "logo")

        menus = {
            "File": [("New Text File", "Ctrl+N", self.new_file),
                     ("Open File…", "Ctrl+O", self.open_file_dialog),
                     ("Open Folder…", "Ctrl+K Ctrl+O",
                      self.open_folder_dialog), None,
                     ("Save", "Ctrl+S", self.save_file),
                     ("Save As…", "Ctrl+Shift+S", self.save_file_as),
                     ("Save All", "Ctrl+Alt+S", self.save_all), None,
                     ("New File in Workspace…",
                      "", lambda: self.fs_new_file(self.root_dir)),
                     ("New Folder…",
                      "", lambda: self.fs_new_folder(self.root_dir)), None,
                     ("Close Editor", "Ctrl+W", self.close_current_tab), None,
                     ("Exit", "", self._human_requested_close)],
            "Edit": [("Undo", "Ctrl+Z", self._undo),
                     ("Redo", "Ctrl+Y", self._redo), None,
                     ("Cut", "Ctrl+X", lambda: self.editor.text.event_generate("<<Cut>>")),
                     ("Copy", "Ctrl+C", lambda: self.editor.text.event_generate("<<Copy>>")),
                     ("Paste", "Ctrl+V", lambda: self.editor.text.event_generate("<<Paste>>")), None,
                     ("Find", "Ctrl+F", lambda: self.show_find(False)),
                     ("Replace", "Ctrl+H", lambda: self.show_find(True)),
                     ("Select All", "Ctrl+A", self._select_all)],
            "Selection": [("Select All", "Ctrl+A", self._select_all),
                          ("Copy Line Down", "Shift+Alt+Down",
                           self._duplicate_line),
                          ("Move Line Up", "Alt+Up",
                           lambda: self._move_line(-1)),
                          ("Move Line Down", "Alt+Down",
                           lambda: self._move_line(1))],
            "View": [("Command Palette…", "Ctrl+Shift+P",
                      lambda: self.quick_open(">")),
                     ("Quick Open…", "Ctrl+P",
                      lambda: self.quick_open("")), None,
                     ("Explorer", "Ctrl+Shift+E",
                      lambda: self.show_sidebar_mode("explorer")),
                     ("Search in Files", "Ctrl+Shift+F",
                      lambda: self.show_sidebar_mode("search")),
                     ("Refresh Explorer", "F5 (tree)", self.refresh_explorer),
                     ("Toggle Side Bar", "Ctrl+B", self.toggle_sidebar),
                     ("Toggle Panel", "Ctrl+`", self.toggle_panel),
                     ("Toggle Minimap", "", self.toggle_minimap), None,
                     ("Zoom In", "Ctrl+=", lambda: self.zoom(1)),
                     ("Zoom Out", "Ctrl+-", lambda: self.zoom(-1)),
                     ("Reset Zoom", "Ctrl+0", self.reset_zoom), None,
                     ("More Transparent", "Ctrl+Shift+-",
                      lambda: self.fade(-0.04)),
                     ("More Opaque", "Ctrl+Shift+=",
                      lambda: self.fade(0.04)),
                     ("Toggle Always On Top", "", self.toggle_topmost),
                     ("Toggle Maximize", "", self.toggle_maximize), None,
                     ("Cycle Theme", "Ctrl+Shift+T", self.cycle_theme),
                     ("Theme: Grey", "", lambda: self.set_theme("grey")),
                     ("Theme: Black", "", lambda: self.set_theme("black")),
                     ("Theme: White", "", lambda: self.set_theme("white"))],
            "Go": [("Go to Line…", "Ctrl+G", self.goto_line_dialog),
                   ("Back to Editor", "Esc", self.focus_editor), None,
                   ("Open Editors View", "",
                    lambda: self.show_sidebar_mode("explorer"))],
            "Run": [("Run File", "F5", self.run_file),
                    ("Run Project", "Ctrl+F5", self.run_project),
                    ("Build Project", "Ctrl+Shift+B", self.build_project),
                    ("Tasks…", "Ctrl+Shift+R", self.show_tasks), None,
                    ("Stop", "Ctrl+.", self.stop_task),
                    ("Open in Browser", "Ctrl+Shift+V",
                     self.open_in_browser), None,
                    ("Toggle Terminal", "Ctrl+`", self.toggle_panel)],
            "Terminal": [("New Terminal", "Ctrl+`", self.toggle_panel),
                         ("Clear Terminal", "",
                          lambda: self.panel.clear()), None,
                         ("Run File", "F5", self.run_file),
                         ("Stop", "Ctrl+.", self.stop_task)],
            "Help": [("Keyboard Shortcuts", "", self.show_shortcuts), None,
                     ("About", "", self.show_about)],
        }
        for label, items in menus.items():
            mb = tk.Menubutton(bar, text=label, bg=C["menubar"], fg=C["fg"],
                               activebackground=C["menubar_hover"],
                               activeforeground=C["fg_bright"], bd=0,
                               padx=10, pady=5, font=self.f_ui,
                               highlightthickness=0)
            m = tk.Menu(mb, tearoff=0, bg=C["sidebar"], fg=C["fg"],
                        activebackground=C["list_sel"],
                        activeforeground=C["fg_bright"], bd=1,
                        relief="flat", font=self.f_ui,
                        disabledforeground=C["fg_faint"])
            for it in items:
                if it is None:
                    m.add_separator(background="#454545")
                else:
                    text, accel, cmd = it
                    m.add_command(label=text, accelerator=accel,
                                  command=cmd)
            mb.configure(menu=m)
            mb.pack(side="left")

        # center command bar
        center = tk.Frame(bar, bg=C["menubar"])
        center.place(relx=0.58, rely=0.5, anchor="center")
        self.cmdcenter = tk.Entry(center, width=30, justify="center",
                                  bg=C["input"], fg=C["fg_dim"], relief="flat",
                                  readonlybackground=C["input"],
                                  insertbackground=C["fg_dim"],
                                  highlightthickness=1,
                                  highlightbackground=C["border"],
                                  highlightcolor=C["border"],
                                  font=(self.f_ui[0], 9), state="readonly")
        self.cmdcenter.pack(ipady=3)
        self.cmdcenter.configure(state="readonly")
        self.cmdcenter.bind("<Button-1>", lambda e: self.quick_open(""))

        right = tk.Frame(bar, bg=C["menubar"])
        right.pack(side="right", padx=6)

        # --- window controls (we are frameless, so we draw our own) ---
        # Under agent control (Agent Mode), this window is opened/closed
        # by Friday ("turn on/close agent mode"), not by clicking a titlebar
        # button, so the three buttons are replaced with an identically
        # sized, inert zone (self._winctrl_zone) instead -- same font/
        # width/packing as the real buttons, so the reserved footprint
        # lines up pixel-for-pixel with where they'd otherwise be.
        self._winctrl_zone = tk.Frame(right, bg=C["menubar"])
        self._winctrl_zone.pack(side="right", fill="y")

        def wbtn(glyph, cmd, hover="#4a4a4a", fg=C["fg"]):
            b = tk.Label(self._winctrl_zone, text=glyph, bg=C["menubar"],
                         fg=fg, font=(self.f_ui[0], 10), width=3,
                         cursor="hand2")
            b.pack(side="right", fill="y")
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", lambda e: b.configure(bg=hover,
                                                    fg=C["fg_bright"]))
            b.bind("<Leave>", lambda e: b.configure(bg=C["menubar"], fg=fg))
            return b

        if self._agent_controlled:
            # Close and maximize stay inert placeholders under Agent Mode
            # (see the big comment above self._winctrl_zone) -- this
            # window is opened/closed/resized by Friday itself, not by a
            # human clicking those two. Minimize is the one deliberate
            # exception: it doesn't destroy or resize anything, it just
            # tucks the window away into a small pill near Friday's
            # circle, so it's always safe to leave enabled.
            for _ in range(2):
                tk.Label(self._winctrl_zone, text="", bg=C["menubar"],
                         font=(self.f_ui[0], 10), width=3
                         ).pack(side="right", fill="y")
            wbtn("\u2500", self.minimize_to_pill)                 # —
        else:
            wbtn("\u2715", self.close_window, hover="#c4383f")   # ×
            self._max_btn = wbtn("\u25a1", self.toggle_maximize)  # □
            wbtn("\u2500", self.minimize_to_pill)                 # —
        tk.Frame(right, bg=C["border_soft"], width=1).pack(side="right",
                                                           fill="y", padx=6)
        _side_btn = icon_button(right, "panel-side", 18, C["menubar"],
                                cmd=self.toggle_sidebar)
        _side_btn.pack(side="right", padx=4)
        self.tooltip(_side_btn, "Toggle sidebar")
        _bottom_btn = icon_button(right, "panel-bottom", 18, C["menubar"],
                                  cmd=self.toggle_panel)
        _bottom_btn.pack(side="right", padx=4)
        self.tooltip(_bottom_btn, "Toggle panel")

        # --- drag the panel around by its title bar ---
        for drag_target in (bar, logo):
            drag_target.bind("<Button-1>", self._drag_start)
            drag_target.bind("<B1-Motion>", self._drag_move)
            drag_target.bind("<Double-Button-1>",
                             lambda e: self.toggle_maximize())

        self._menu_commands = []
        for section, items in menus.items():
            for it in items:
                if it:
                    self._menu_commands.append((f"{section}: {it[0]}", it[2]))
        self.COMMANDS = self._menu_commands

    # ---------------- themes (agent-facing API) ----------------
    def list_themes(self):
        """Names of every available theme."""
        return list(THEMES)

    def set_theme(self, name):
        """Switch the whole IDE to a hard-coded theme: grey | black | white.

        Safe to call from an AI agent at any time; the open buffers, the
        cursor, the terminal history and the window geometry all survive.
        """
        name = str(name).strip().lower()
        if name not in THEMES:
            raise ValueError(f"unknown theme {name!r}; "
                             f"expected one of {list(THEMES)}")
        if name == getattr(self, "theme_name", None):
            return name
        self.theme_name = name
        C.clear()
        C.update(THEMES[name])
        TAG_COLOR.clear()
        TAG_COLOR.update(_tag_colors())
        _refresh_guide_color()
        self._rebuild_ui()
        return name

    def cycle_theme(self):
        names = self.list_themes()
        nxt = names[(names.index(self.theme_name) + 1) % len(names)]
        self.set_theme(nxt)

    def _rebuild_ui(self):
        """Tear down and re-create the widget tree under the new palette."""
        self._stash()
        bufs, cur = list(self.buffers), self.current
        mode = getattr(self.sidebar, "mode", None) or "explorer"
        want_panel = self.panel_visible
        want_sidebar = self.sidebar_visible
        hist = list(getattr(self.panel, "history", []))
        term_text = ""
        try:
            term_text = self.panel.term.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001
            pass
        started = getattr(self.panel, "_started", False)

        self._grips = None          # stale grip frames die with the tree
        for w in self.winfo_children():
            w.destroy()
        self.configure(bg=self._BORDER_WHITE)

        self.buffers, self.current = bufs, cur
        self._style_scrollbars()
        self._build_menubar()
        self._build_statusbar()
        self._build_body()
        self._bind_shortcuts()
        self._add_resize_grips()

        self.sidebar.show(mode)
        if not want_sidebar:
            self.toggle_sidebar()
        if want_panel:
            self.toggle_panel()
            self.panel._started = started
            if term_text:
                self.panel.term.delete("1.0", "end")
                self.panel.term.insert("1.0", term_text)
                self.panel.term.mark_set("input", "end-1c")
                self.panel.term.see("end")
            self.panel.history = hist
            self.panel.hidx = len(hist)
        self._load_current()
        self.status.theme.configure(text=f"Theme: {self.theme_name.title()}")
        self.status.opacity.configure(
            text=f"Opacity {round(self.opacity * 100)}%")
        pct = round(self.font_size / EDITOR_FONT_SIZE * 100)
        self.status.zoom.configure(text=f"{pct}%")

    # ---------------- rounded window corners ----------------
    def _round_corners(self, radius=16):
        """Give the frameless panel slightly curved edges.

        Windows: real rounded corners via DWM (11) or a window region (10).
        macOS/Linux: handled by the compositor where supported.
        """
        self.corner_radius = radius
        try:
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes
                self.update_idletasks()
                hwnd = ctypes.windll.user32.GetAncestor(
                    wintypes.HWND(self.winfo_id()), 2)   # GA_ROOT
                # --- Windows 11: ask DWM for rounded corners ---
                DWMWA_WINDOW_CORNER_PREFERENCE = 33
                DWMWCP_ROUND = 2
                pref = ctypes.c_int(DWMWCP_ROUND)
                rc = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(pref), ctypes.sizeof(pref))
                if rc != 0:
                    # --- Windows 10 fallback: clip to a round-rect region ---
                    w, h = self.winfo_width(), self.winfo_height()
                    rgn = ctypes.windll.gdi32.CreateRoundRectRgn(
                        0, 0, w + 1, h + 1, radius * 2, radius * 2)
                    ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
                    self._win_rgn = True
        except Exception:  # noqa: BLE001
            pass   # never let cosmetics break startup

    def _reround(self):
        """Re-clip after a resize (only needed for the Win10 region path)."""
        if getattr(self, "_win_rgn", False):
            self._round_corners(getattr(self, "corner_radius", 16))

    # ---------------- floating window management ----------------
    def _drag_start(self, e):
        self._drag_off = (e.x_root - self.winfo_x(),
                          e.y_root - self.winfo_y())

    def _drag_move(self, e):
        if self._maximized or not hasattr(self, "_drag_off"):
            return
        dx, dy = self._drag_off
        self.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

    def toggle_maximize(self):
        # self._max_btn only exists when the real window-control buttons
        # were drawn (i.e. not agent-controlled) -- double-click-to-
        # maximize on the titlebar still works either way, there's just
        # no glyph to flip when there's no button.
        if self._maximized:
            if self._normal_geom:
                self.geometry(self._normal_geom)
            self._maximized = False
            if hasattr(self, "_max_btn"):
                self._max_btn.configure(text="\u25a1")
        else:
            self._normal_geom = self.geometry()
            self.geometry(f"{self.winfo_screenwidth()}x"
                          f"{self.winfo_screenheight()}+0+0")
            self._maximized = True
            if hasattr(self, "_max_btn"):
                self._max_btn.configure(text="\u2750")
        self.after(30, self._reround)

    def minimize_window(self):
        # iconify() is ignored on an overrideredirect window, so drop the
        # flag, minimise, and restore the frameless look when remapped.
        try:
            self.overrideredirect(False)
            self.iconify()
            self.bind("<Map>", self._remap, add="+")
        except tk.TclError:
            pass

    def _remap(self, _e=None):
        try:
            if self.state() == "normal":
                self.overrideredirect(True)
                self.attributes("-alpha", self.opacity)
        except tk.TclError:
            pass

    def _human_requested_close(self):
        """Wired to Alt+F4/the window manager's own close request and
        the File > Exit menu item -- the two ways a human could try to
        close this window directly from inside the IDE itself, bypassing
        Friday entirely. While Friday is driving this window
        (agent_controlled), it belongs to Friday -- "the IDE should not be
        a different panel separate from Friday" -- so only Friday's own
        agent_mode_off() tool (which calls close_window() directly, not
        this) should ever be able to close it. This just nudges instead
        of closing. Standalone (not agent-controlled) runs are
        unaffected: this just forwards straight to close_window(),
        exactly as before -- unsaved-changes prompt and all."""
        if self._agent_controlled:
            self.status.pos.configure(
                text="This window is controlled by Friday — tell Friday to "
                     "close Agent Mode to close it.")
            return
        self.close_window()

    def close_window(self):
        self._stash()
        dirty = [b["name"] for b in self.buffers if b.get("modified")]
        if dirty:
            names = ", ".join(dirty[:5]) + ("…" if len(dirty) > 5 else "")
            ans = messagebox.askyesnocancel(
                "Unsaved Changes",
                f"{len(dirty)} file(s) have unsaved changes:\n\n{names}\n\n"
                f"Save before closing?")
            if ans is None:
                return
            if ans:
                self.save_all()
        if self._agent_controlled:
            self._play_close_animation(self.destroy)
        else:
            self.destroy()

    # ---------------- open/close "pop" animation ----------------
    # Cosmetic only, agent-controlled runs only: makes this window look
    # like it emerges out of Friday's floating circle when Friday opens it,
    # and shrinks back into that same spot when Friday closes it. Every
    # entry point below is best-effort -- if the circle's current
    # on-screen rect can't be worked out for any reason (standalone
    # `python ide.py` run with no circle at all, no provider registered,
    # a query failing), the window just appears/disappears instantly,
    # exactly as it did before this feature existed. Agent Mode itself
    # never depends on any of this succeeding.

    def _show_launch_curtain(self):
        """A plain solid-color frame placed over the whole (already
        fully built) window for the duration of the open/close
        animation. Without it, every resize tick would force the real
        editor/sidebar/chat widget tree to reflow at animation
        frequency -- visibly janky and needlessly slow. Resizing a
        single trivial Frame underneath it is instant regardless of how
        complex the real layout is."""
        curtain = tk.Frame(self, bg=C["editor"], highlightthickness=0)
        curtain.place(x=0, y=0, relwidth=1, relheight=1)
        curtain.lift()
        return curtain

    def _hide_launch_curtain(self, curtain):
        try:
            curtain.destroy()
        except tk.TclError:
            pass

    def _animate_geometry(self, from_rect, to_rect, duration_ms=240,
                           on_done=None, easing=None,
                           from_alpha=None, to_alpha=None):
        """Eases this window's x/y/width/height (and, optionally, its
        own -alpha, in lockstep) from `from_rect`/`from_alpha` to
        `to_rect`/`to_alpha` over `duration_ms`. Tk has no real
        animation API of its own, so this drives it by hand with
        repeated .after() ticks -- but, unlike a naive fixed-step
        version (counting off N equal steps regardless of how long they
        actually took to fire), it times itself off the wall clock
        (time.monotonic()): each tick computes how far through
        `duration_ms` it actually, truly is and jumps straight to the
        matching point on the curve. A tick that fires a little late
        under system load just makes the *next* one advance further
        along the same curve instead of the whole animation visibly
        stuttering, slowing down, or running jerkily -- the standard
        "delta/elapsed-time" technique real animation frameworks use
        instead of a plain step counter, and the main fix for the
        choppy/"breaking" feel the previous fixed-step version had.

        `easing`, if given, is a t -> t' function (t and t' both
        conceptually in [0, 1], though an overshoot curve like
        ease_out_back briefly exceeds that range on purpose) applied to
        the geometry interpolation; defaults to ease_in_out_cubic.
        `from_alpha`/`to_alpha`, if both given, fade -alpha in step
        with the *raw* (un-eased) progress -- deliberately linear, so a
        bouncy geometry curve doesn't also make the window flicker.

        Safe on a window that gets destroyed mid-flight -- each tick
        checks winfo_exists() first and simply stops without calling
        on_done(). `on_done`, if given, is called exactly once, right
        after the exact final (t=1, un-eased, alpha included) frame has
        been applied."""
        if easing is None:
            easing = ease_in_out_cubic
        fx, fy, fw, fh = from_rect
        tx, ty, tw, th = to_rect
        fade = from_alpha is not None and to_alpha is not None
        old_job = getattr(self, "_geom_anim_job", None)
        if old_job:
            try:
                self.after_cancel(old_job)
            except Exception:  # noqa: BLE001
                pass
            self._geom_anim_job = None

        start_time = time.monotonic()
        # ~90fps target -- the OS timer / Tk's own event loop will
        # coarsen this somewhat in practice, but aiming high keeps
        # whichever frame rate IS actually achievable as smooth as
        # possible instead of deliberately throttling it further.
        tick_ms = 11

        def frame():
            if not self.winfo_exists():
                self._geom_anim_job = None
                return
            elapsed_ms = (time.monotonic() - start_time) * 1000.0
            raw_t = 1.0 if duration_ms <= 0 else min(1.0, elapsed_ms / duration_ms)
            t = easing(raw_t)
            x = int(fx + (tx - fx) * t)
            y = int(fy + (ty - fy) * t)
            w = max(1, int(fw + (tw - fw) * t))
            h = max(1, int(fh + (th - fh) * t))
            try:
                self.geometry(f"{w}x{h}+{x}+{y}")
                if fade:
                    a = from_alpha + (to_alpha - from_alpha) * raw_t
                    self.attributes("-alpha", max(0.0, min(1.0, a)))
            except tk.TclError:
                self._geom_anim_job = None
                return
            if raw_t < 1.0:
                self._geom_anim_job = self.after(tick_ms, frame)
            else:
                self._geom_anim_job = None
                if on_done:
                    on_done()

        frame()

    def _circle_pop_origin(self):
        """Best-effort (x, y, size) square, in this window's own
        geometry()-compatible coordinate space, centered on Friday's
        floating circle's current on-screen spot -- or None if that
        spot isn't available for any reason. Shared by the open and
        close animations below."""
        if not self._agent_controlled or self._agent_host is None:
            return None
        try:
            rect = self._agent_host.get_circle_rect()
        except Exception:  # noqa: BLE001
            rect = None
        if not rect:
            return None
        try:
            cx, cy, diameter = rect
            size = max(24, int(diameter))
            return (int(cx - size / 2), int(cy - size / 2), size)
        except Exception:  # noqa: BLE001
            return None

    def _maybe_play_open_animation(self):
        """Called once, right at the end of __init__ (the whole chrome
        is already fully built and sized by then): if this is an
        agent-controlled window and the circle's spot is available,
        snap down to a small square there, then ease up to the real
        final size/position computed earlier (see self._final_geom)."""
        origin = self._circle_pop_origin()
        if origin is None:
            return
        start_x, start_y, size = origin
        end_x, end_y, end_w, end_h = self._final_geom
        try:
            curtain = self._show_launch_curtain()
            # See self._real_minsize's comment: a toplevel can never be
            # resized below its current minsize(), window-manager or not
            # -- relax it to let the window actually shrink down to the
            # tiny circle-sized square for the start of this animation.
            self.minsize(1, 1)
            self.geometry(f"{size}x{size}+{max(0, start_x)}+{max(0, start_y)}")
            # Starts fully transparent and fades in alongside the
            # growth (see _animate_geometry's from_alpha/to_alpha), so
            # the necessarily-instant jump down to this tiny starting
            # square is invisible -- the window only ever becomes
            # visible already mid-emergence, not as a visible "snap".
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            return
        # Tells _apply_opacity's own watchdog calls (scheduled earlier
        # in __init__) to leave -alpha alone for now -- otherwise one of
        # them firing mid-fade would yank it straight back to the full,
        # final opacity, exactly the kind of jarring mid-animation jump
        # this whole feature is trying to avoid.
        self._anim_active = True

        def _done():
            self._anim_active = False
            self._hide_launch_curtain(curtain)
            try:
                self.minsize(*self._real_minsize)
                self.attributes("-alpha", self.opacity)
            except tk.TclError:
                pass

        self._animate_geometry(
            (start_x, start_y, size, size), (end_x, end_y, end_w, end_h),
            duration_ms=340, on_done=_done, easing=ease_out_back,
            from_alpha=0.0, to_alpha=self.opacity)

    def _play_close_animation(self, on_done):
        """Reverse of _maybe_play_open_animation(): eases this window
        down from its current size/position into a small square over
        Friday's floating circle's current on-screen spot, then calls
        `on_done` (always self.destroy in practice). Falls back to
        calling `on_done` immediately, with no animation, if the
        circle's spot isn't available."""
        origin = self._circle_pop_origin()
        if origin is None or not self.winfo_exists():
            on_done()
            return
        end_x, end_y, size = origin
        try:
            cur_w, cur_h = self.winfo_width(), self.winfo_height()
            cur_x, cur_y = self.winfo_rootx(), self.winfo_rooty()
            start_alpha = float(self.attributes("-alpha"))
            curtain = self._show_launch_curtain()
            # See self._real_minsize's comment on _maybe_play_open_animation
            # -- relax it here too, so the window can actually shrink all
            # the way down to the circle-sized square instead of getting
            # clamped at the normal usable-size floor partway through.
            self.minsize(1, 1)
        except tk.TclError:
            on_done()
            return
        self._anim_active = True  # see _maybe_play_open_animation's comment

        def _finish():
            self._anim_active = False
            self._hide_launch_curtain(curtain)
            on_done()

        self._animate_geometry(
            (cur_x, cur_y, cur_w, cur_h), (end_x, end_y, size, size),
            duration_ms=260, on_done=_finish, easing=ease_in_cubic,
            from_alpha=start_alpha, to_alpha=0.0)

    # ---------------- unified panel placement (agent_tools.py's shared
    # maximized-center / 3-side-slot system -- see its module-level
    # comment) -- resizing the IDE's own window into/out of a side slot
    # or the maximized/center spot, exactly the same contract
    # app_panels.py's EmbeddedAppPanel/CustomNotepadPanel.maximize_to()/
    # move_to_slot() already give every other panel, so agent_tools.py
    # can treat "ide" as just another key in that system ----------------
    def resize_to_bounds(self, x, y, w, h):
        """Resizes/repositions this window to exactly (x, y, w, h) --
        used when agent_tools.py's panel-placement system demotes this
        IDE into one of the three smaller side slots (because some
        other panel is now the maximized/active one) or promotes it
        back out to the maximized/full size. A side slot is normally
        smaller than this window's own comfortable minimum size (see
        self._real_minsize), so this relaxes minsize() first exactly
        like the existing open/close pop animations already do, and
        restores the real minsize right away once the target size is
        big enough not to need that relaxation any more. Uses the same
        set-twice-after-an-idletasks-pass trick as
        EmbeddedAppPanel._set_geometry_firmly to reliably win the same
        Tk pack-propagate position-reassertion race documented there.

        Also explicitly cancels any still-in-flight open/close pop
        animation (_animate_geometry's own scheduled .after() ticks --
        see _maybe_play_open_animation/_play_close_animation) first:
        Agent Mode's open animation alone takes 340ms, and
        agent_mode_on() returns well before that finishes (it only
        waits for the window to exist, not for it to finish animating
        in) -- so a maximize_app('ide')/panel-placement call landing
        shortly after turning Agent Mode on could otherwise race with
        the animation's own leftover scheduled ticks still easing
        toward its original target and silently overwrite whatever
        this method just set, moments later.
        """
        old_job = getattr(self, "_geom_anim_job", None)
        if old_job:
            try:
                self.after_cancel(old_job)
            except Exception:  # noqa: BLE001
                pass
            self._geom_anim_job = None
        self._anim_active = False
        try:
            if w < self._real_minsize[0] or h < self._real_minsize[1]:
                self.minsize(1, 1)
            else:
                self.minsize(*self._real_minsize)
            geom = f"{int(w)}x{int(h)}+{int(x)}+{int(y)}"
            self.geometry(geom)
            self.update_idletasks()
            self.geometry(geom)
            self.deiconify()
            self.lift()
        except tk.TclError:
            pass

    # ---------------- minimize-to-pill (hide into a small tab near the
    # circle, instead of a normal OS-level minimize) ----------------
    def minimize_to_pill(self):
        """The titlebar's minimize button. If Friday's circle is on
        screen (Agent Mode), eases this window down into Friday's circle
        (reusing the same shrink animation as closing) and then, instead
        of destroying it, replaces it with a small pill-shaped indicator
        just under the circle, connected to it by a thin line -- hover
        the pill to hear its name spoken aloud, click it to bring this
        window straight back exactly where/how big it was. Falls back to
        a plain OS-level minimize if the circle isn't available at all
        (e.g. a standalone `python ide.py` run with no Friday circle on
        screen) -- there's nothing to tuck this under in that case.
        """
        if getattr(self, "_pill", None) is not None:
            return  # already minimized -- nothing to do
        if self._circle_pop_origin() is None:
            self.minimize_window()
            return
        # Remember exactly where/how big this window was *before* the
        # collapse animation shrinks it down -- that's what "restore"
        # needs to grow back out to, not whatever tiny size it ends up
        # animated to right before being withdrawn.
        self._pre_minimize_geom = (self.winfo_x(), self.winfo_y(),
                                    self.winfo_width(), self.winfo_height())

        def _collapse_done():
            self.withdraw()
            self._show_pill()

        self._play_close_animation(_collapse_done)

    def _show_pill(self):
        """Builds and shows the small pill-shaped MinimizedPill window
        just under Friday's circle, once this window has already been
        shrunk/withdrawn by minimize_to_pill(). No-ops if the circle's
        spot isn't available any more by the time this runs (extremely
        unlikely -- the same check already passed moments earlier in
        minimize_to_pill())."""
        origin = self._circle_pop_origin()
        if origin is None:
            self.deiconify()  # nothing to tuck this under -- don't strand it hidden
            return
        cx, cy, size = origin[0] + origin[2] / 2, origin[1] + origin[2], origin[2]
        slot_index = 0
        if self._agent_host is not None:
            try:
                slot_index = self._agent_host.get_pill_slot("ide")
            except Exception:  # noqa: BLE001
                slot_index = 0
        offset = slot_index * MinimizedPill.STACK_STEP
        self._pill = MinimizedPill(
            self, label=APP_NAME, agent_host=self._agent_host,
            circle_bottom=(cx, cy + offset), on_restore=self.restore_from_pill)
        # Apply whatever status was already active (set while this
        # window was maximized, or carried over from before the previous
        # minimize) rather than letting a freshly-built pill start out
        # looking like nothing is going on.
        self._pill.set_status(self._panel_status)

    def set_panel_status(self, status):
        """Records this IDE's current status ("normal"/"waiting"/"done"/
        "error" -- see MinimizedPill._STATUS_COLORS) and, if a pill is
        showing right now, recolors it live. Called via
        agent_tools.report_panel_status("ide", status) -- see there for
        who actually drives this (today: the IDE chat panel's own
        worker completions, per _ide_chat_ask in agent_overlay.py).
        Survives across minimize/restore cycles: the status itself is
        remembered here regardless of whether a pill happens to exist
        at the moment it's set (see _show_pill's own use of this).
        """
        self._panel_status = status
        pill = getattr(self, "_pill", None)
        if pill is not None:
            pill.set_status(status)

    def reposition_pill_to_slot(self, slot_index):
        """Live-repositions this IDE's already-shown pill to `slot_index`
        in the shared stack -- called (via agent_host.reposition_pill)
        when some other panel's pill above this one in the stack was
        just removed (restored/closed) and everything below it needs to
        shift up to close the resulting gap. No-ops if this IDE doesn't
        actually have a pill showing right now (e.g. it raced ahead and
        was itself just restored already)."""
        pill = getattr(self, "_pill", None)
        if pill is None:
            return
        origin = self._circle_pop_origin()
        if origin is None:
            return
        cx, cy = origin[0] + origin[2] / 2, origin[1] + origin[2]
        offset = slot_index * MinimizedPill.STACK_STEP
        pill.reposition((cx, cy + offset))

    def restore_from_pill(self):
        """Reverse of minimize_to_pill(): removes the pill and eases this
        window back out from Friday's circle to exactly the size/position
        it had right before it was minimized."""
        pill = getattr(self, "_pill", None)
        if pill is None:
            return
        self._pill = None
        try:
            pill.destroy()
        except tk.TclError:
            pass
        # Release this pill's slot in the shared IDE+app-panels stack and
        # shift any other still-minimized panel below it up to close the
        # gap, so the stack never ends up with a visible hole in the
        # middle of it.
        if self._agent_host is not None:
            try:
                reflow = self._agent_host.release_pill_slot("ide")
                for key, idx in reflow:
                    self._agent_host.reposition_pill(key, idx)
            except Exception:  # noqa: BLE001
                pass

        end_x, end_y, end_w, end_h = getattr(
            self, "_pre_minimize_geom",
            (self.winfo_x(), self.winfo_y(), self.winfo_width(), self.winfo_height()))
        origin = self._circle_pop_origin()
        self.deiconify()
        self.lift()
        try:
            self.focus_force()
        except tk.TclError:
            pass
        if origin is None or not self.winfo_exists():
            try:
                self.geometry(f"{end_w}x{end_h}+{end_x}+{end_y}")
                self._apply_opacity()
            except tk.TclError:
                pass
            return

        start_x, start_y, size = origin
        try:
            self.minsize(1, 1)
            self.geometry(f"{size}x{size}+{max(0, start_x)}+{max(0, start_y)}")
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            try:
                self.geometry(f"{end_w}x{end_h}+{end_x}+{end_y}")
                self._apply_opacity()
            except tk.TclError:
                pass
            return
        self._anim_active = True

        def _done():
            self._anim_active = False
            try:
                self.minsize(*self._real_minsize)
                self.attributes("-alpha", self.opacity)
            except tk.TclError:
                pass

        self._animate_geometry(
            (start_x, start_y, size, size), (end_x, end_y, end_w, end_h),
            duration_ms=300, on_done=_done, easing=ease_out_back,
            from_alpha=0.0, to_alpha=self.opacity)

    def _apply_opacity(self):
        if getattr(self, "_anim_active", False):
            return  # the open/close pop animation owns -alpha for now
        try:
            if abs(float(self.attributes("-alpha")) - self.opacity) > 0.005:
                self.attributes("-alpha", self.opacity)
        except (tk.TclError, ValueError):
            pass

    def fade(self, delta):
        self.opacity = max(0.45, min(1.0, self.opacity + delta))
        try:
            self.attributes("-alpha", self.opacity)
        except tk.TclError:
            pass
        self.status.opacity.configure(
            text=f"Opacity {round(self.opacity * 100)}%")

    def toggle_topmost(self):
        self._topmost = not getattr(self, "_topmost", False)
        try:
            self.attributes("-topmost", self._topmost)
        except tk.TclError:
            pass

    def _add_resize_grips(self):
        """Thin invisible edges that resize the frameless panel."""
        spec = {"right": ("e", "sb_h_double_arrow"),
                "bottom": ("s", "sb_v_double_arrow"),
                "corner": ("se", "bottom_right_corner")}
        # build into a local dict and publish it only once every grip
        # exists, so a <Configure> mid-build never sees a partial set
        built = {}
        for name, (mode, cur) in spec.items():
            g = tk.Frame(self, bg=C["border"], cursor=cur)
            g.bind("<Button-1>", lambda e, m=mode: self._rz_start(e, m))
            g.bind("<B1-Motion>", self._rz_move)
            built[name] = g
        self._grips = built
        self._place_grips()
        if getattr(self, "_grip_bind", None):
            try:
                self.unbind("<Configure>", self._grip_bind)
            except tk.TclError:
                pass
        self._grip_bind = self.bind("<Configure>",
                                    lambda e: self._place_grips(), add="+")

    def _place_grips(self):
        # a <Configure> can arrive mid-rebuild, when the old grips have been
        # destroyed and the new ones do not exist yet
        grips = getattr(self, "_grips", None)
        if not grips:
            return
        try:
            if (set(grips) != {"right", "bottom", "corner"}
                    or not all(g.winfo_exists() for g in grips.values())):
                return
        except tk.TclError:
            return
        t = 4
        self._grips["right"].place(relx=1.0, y=0, anchor="ne",
                                   width=t, relheight=1.0)
        self._grips["bottom"].place(x=0, rely=1.0, anchor="sw",
                                    height=t, relwidth=1.0)
        self._grips["corner"].place(relx=1.0, rely=1.0, anchor="se",
                                    width=12, height=12)
        for g in self._grips.values():
            g.lift()

    def _rz_start(self, e, mode):
        self._rz = (mode, e.x_root, e.y_root,
                    self.winfo_width(), self.winfo_height())

    def _rz_move(self, e):
        if not getattr(self, "_rz", None):
            return
        mode, x0, y0, w0, h0 = self._rz
        w = w0 + (e.x_root - x0) if "e" in mode else w0
        h = h0 + (e.y_root - y0) if "s" in mode else h0
        self.geometry(f"{max(900, w)}x{max(560, h)}")
        self._reround()

    # ---------------- body layout ----------------
    def _build_body(self):
        # The activity bar is a plain sibling of the body PanedWindow (not
        # a wrapper around it) so every widget inside the paned layout
        # (sidebar, editor, chat panel) keeps `self` (the IDEApp window
        # itself) as both its literal Tk master and its "app" reference,
        # exactly as before -- only the packing order changes, reserving
        # a fixed-width strip on the left before the paned area claims
        # the rest.
        self.activity_bar = ActivityBar(self)
        self.activity_bar.pack(side="left", fill="y")

        self.body = tk.PanedWindow(self, orient="horizontal", bd=0,
                                   sashwidth=max(1, band(1)),
                                   sashrelief="flat",
                                   bg=C["border_soft"], opaqueresize=True,
                                   showhandle=False)
        self.body.pack(side="left", fill="both", expand=True)

        self.sidebar = SideBar(self)
        self.sidebar_visible = True
        self.body.add(self.sidebar, minsize=180, width=264, stretch="never")

        self.vpanes = tk.PanedWindow(self.body, orient="vertical", bd=0,
                                     sashwidth=max(1, band(1)),
                                     sashrelief="flat",
                                     bg=C["border_soft"], opaqueresize=True,
                                     showhandle=False)
        self.body.add(self.vpanes, minsize=320, stretch="always")

        self.editor = EditorArea(self)
        self.vpanes.add(self.editor, minsize=200, stretch="always")

        self.panel = Panel(self)
        self.panel_visible = False

        self.chat_panel = None
        if self._agent_controlled:
            # A real, always-visible chat surface docked to the right of
            # the editor -- Friday's presence in the IDE is obvious the
            # moment Agent Mode turns on, instead of something you have
            # to already know to go looking for.
            self.chat_panel = ChatSidePanel(self)
            self.body.add(self.chat_panel, minsize=280, width=340,
                          stretch="never")
            if self._agent_host is not None:
                # Lets Friday post an unprompted "friday" bubble here --
                # not a reply to anything the user just typed -- for the
                # 2-minute unanswered-pause autonomy rule's follow-up
                # once it decides to proceed without a reply. See
                # ChatSidePanel.receive_proactive_message and
                # agent_tools.notify_ide_chat/_ide_chat_auto_continue.
                try:
                    self._agent_host.register_ide_chat_notify(
                        lambda t, o=None: self.after(
                            0, lambda: self.chat_panel.receive_proactive_message(t, o)))
                except Exception:  # noqa: BLE001
                    pass
                # Build Protocol status checklist (Task 65 / the IDE's
                # own "Permission" and status-tracking mechanism; see
                # development_skill.md's Build Protocol section and
                # agent_tools.ide_report_build_status). Same registration
                # shape as the notify handler just above.
                try:
                    self._agent_host.register_ide_build_status(
                        lambda phase, status, detail: self.after(
                            0, lambda: self.chat_panel.update_build_status(
                                phase, status, detail)))
                except Exception:  # noqa: BLE001
                    pass

    def _build_statusbar(self):
        self.status = StatusBar(self)
        self.status.pack(fill="x", side="bottom")

    # ---------------- shortcuts ----------------
    def _bind_shortcuts(self):
        b = self.bind
        b("<Control-n>", lambda e: self._sc(self.new_file))
        b("<Control-o>", lambda e: self._sc(self.open_file_dialog))
        b("<Control-s>", lambda e: self._sc(self.save_file))
        b("<Control-Alt-s>", lambda e: self._sc(self.save_all))
        b("<Control-S>", lambda e: self._sc(self.save_file_as))
        b("<Control-w>", lambda e: self._close_editor_sc())
        b("<Control-p>", lambda e: self._sc(lambda: self.quick_open("")))
        b("<Control-P>", lambda e: self._sc(lambda: self.quick_open(">")))
        b("<Control-g>", lambda e: self._sc(self.goto_line_dialog))
        b("<Control-f>", lambda e: self._sc(lambda: self.show_find(False)))
        b("<Control-h>", lambda e: self._sc(lambda: self.show_find(True)))
        b("<Control-b>", lambda e: self._sc(self.toggle_sidebar))
        b("<Control-E>", lambda e:
          self._sc(lambda: self.show_sidebar_mode("explorer")))
        b("<Control-F>", lambda e:
          self._sc(lambda: self.show_sidebar_mode("search")))
        b("<Control-j>", lambda e: self._sc(self.toggle_panel))
        b("<Control-grave>", lambda e: self._sc(self.toggle_panel))
        b("<Control-F5>", lambda e: self._sc(self.run_project))
        b("<F5>", lambda e: self._sc(self.run_file))
        b("<Control-B>", lambda e: self._sc(self.build_project))
        b("<Control-R>", lambda e: self._sc(self.show_tasks))
        b("<Control-period>", lambda e: self._sc(self.stop_task))
        b("<F2>", lambda e: self._sc(self.rename_current))
        b("<Shift-Alt-R>", lambda e: self._sc(self._explorer_action("reveal")))
        b("<Shift-Alt-F>", lambda e: self._sc(self._explorer_action("find")))
        b("<Shift-Alt-C>", lambda e: self._sc(self._explorer_action("path")))
        b("<Control-V>", lambda e: self._sc(self.open_in_browser))
        b("<Control-equal>", lambda e: self._sc(lambda: self.zoom(1)))
        b("<Control-plus>", lambda e: self._sc(lambda: self.zoom(1)))
        b("<Control-minus>", lambda e: self._sc(lambda: self.zoom(-1)))
        b("<Control-0>", lambda e: self._sc(self.reset_zoom))
        b("<Control-T>", lambda e: self._sc(self.cycle_theme))
        b("<Control-Shift-plus>", lambda e: self._sc(lambda: self.fade(0.04)))
        b("<Control-Shift-equal>", lambda e: self._sc(lambda: self.fade(0.04)))
        b("<Control-Shift-underscore>",
          lambda e: self._sc(lambda: self.fade(-0.04)))
        b("<Control-Shift-minus>", lambda e: self._sc(lambda: self.fade(-0.04)))
        b("<Alt-Up>", lambda e: self._move_line(-1) or "break")
        b("<Alt-Down>", lambda e: self._move_line(1) or "break")
        b("<Shift-Alt-Down>", lambda e: self._duplicate_line() or "break")
        b("<Escape>", lambda e: self._escape())
        self.editor.text.bind("<Control-a>", lambda e: self._select_all())

    def _sc(self, fn):
        if self.quickopen_open:
            return
        fn()
        return "break"

    def _escape(self):
        if self.completion_active:
            self.completion_hide()
        elif self.editor.findbar.winfo_ismapped():
            self.editor.hide_find()
        self.focus_editor()

    # ---------------- buffer management ----------------
    def current_buffer(self):
        if 0 <= self.current < len(self.buffers):
            return self.buffers[self.current]
        return None

    def _stash(self):
        buf = self.current_buffer()
        if buf and buf["kind"] == "file" and self.editor.text.winfo_ismapped():
            buf["content"] = self.editor.text.get("1.0", "end-1c")

    def new_file(self):
        self.untitled_n += 1
        self._add_buffer({"name": f"untitled-{self.untitled_n}",
                          "path": None, "kind": "file", "content": "",
                          "modified": False})

    def open_file_dialog(self):
        p = filedialog.askopenfilename(initialdir=self.root_dir)
        if p:
            self.open_file(p)

    def open_folder_dialog(self):
        d = filedialog.askdirectory(initialdir=self.root_dir)
        if d:
            self.set_root(d)

    # Prefix agent_tools.agent_mode_on() uses for the throwaway temp
    # folder it creates so Agent Mode always has somewhere real on disk
    # to write to, even when no folder was explicitly opened. The name
    # is meaningless to a human, so it's never shown as-is -- see
    # workspace_display_name().
    _PLACEHOLDER_WORKSPACE_PREFIX = "friday-empty-"

    def workspace_display_name(self):
        """Human-facing name for self.root_dir.

        Normally just the folder's real name. But if nobody has opened
        a real folder yet (Agent Mode fell back to its own auto-created
        scratch directory), showing that random temp-folder name in the
        title bar / Explorer would be confusing, so a friendly prompt is
        shown instead -- consistent no matter how it's capitalized by
        the caller.
        """
        name = os.path.basename(self.root_dir)
        if name.startswith(self._PLACEHOLDER_WORKSPACE_PREFIX):
            return "Open Folder or Create New Workspace"
        return name

    def _is_placeholder_workspace(self):
        """True while self.root_dir is one of agent_tools.py's own
        auto-created friday-empty-* scratch directories -- i.e. nobody has
        explicitly opened (or cloned) a real folder yet."""
        return os.path.basename(self.root_dir).startswith(
            self._PLACEHOLDER_WORKSPACE_PREFIX)

    def _placeholder_workspace_is_empty(self):
        """True while that placeholder workspace is still genuinely
        empty, which is when the Explorer shows the rich "no folder
        open" prompt instead of a (confusingly, meaninglessly named)
        real file tree."""
        if not self._is_placeholder_workspace():
            return False
        try:
            return not os.listdir(self.root_dir)
        except OSError:
            return False

    # ---------------- git status badges ----------------
    def _raw_git_status(self):
        """{abs_path: 'M'|'C'} for every changed file under root_dir, per
        `git status --porcelain`. Empty (and cheap) wherever root_dir
        isn't inside a git repo, or git isn't installed."""
        if not os.path.isdir(os.path.join(self.root_dir, ".git")):
            return {}
        try:
            out = subprocess.run(
                ["git", "status", "--porcelain=v1", "--untracked-files=all"],
                cwd=self.root_dir, capture_output=True, text=True, timeout=5)
        except Exception:  # noqa: BLE001
            return {}
        if out.returncode != 0:
            return {}
        status = {}
        for line in out.stdout.splitlines():
            if len(line) < 4:
                continue
            code, rel = line[:2], line[3:]
            if " -> " in rel:   # renames: "old -> new"
                rel = rel.split(" -> ", 1)[1]
            rel = rel.strip('"')
            try:
                abspath = os.path.normpath(os.path.join(self.root_dir, rel))
            except ValueError:
                continue
            # '??' untracked or staged-add -> created; anything else that's
            # an actual change to a tracked file -> modified.
            if code.strip() == "??" or "A" in code:
                status[abspath] = "C"
            else:
                status[abspath] = "M"
        return status

    def git_status_map(self):
        """_raw_git_status(), plus every ancestor folder up to root_dir
        tagged with the status of what it contains (M beats C when a
        folder has both kinds of changes inside it) -- so a collapsed
        folder still visibly flags that something changed underneath."""
        files = self._raw_git_status()
        if not files:
            return {}
        combined = dict(files)
        for path, code in files.items():
            d = os.path.dirname(path)
            while d and (d == self.root_dir or
                        d.startswith(self.root_dir + os.sep)):
                if combined.get(d) != "M":
                    combined[d] = "M" if code == "M" else combined.get(d, "C")
                if d == self.root_dir:
                    break
                d = os.path.dirname(d)
        return combined

    # ---------------- agent activity visualization ----------------
    # When Friday (not a human, via the UI) creates or writes a file/folder,
    # the Explorer and editor don't just silently update -- they visibly
    # "perform" the change: a highlighted status-bar chip says what's
    # happening, the new Explorer entry's name types itself out, and any
    # code being written types into the editor too, fast, instead of
    # appearing instantly. This is purely cosmetic -- the real file is
    # already written to disk, correctly and instantly, before any of
    # this runs; interrupting or skipping it (e.g. closing the IDE
    # mid-animation) never loses or corrupts anything.

    def _tree_node_for_path(self, path):
        """The Explorer tree item for an absolute path, or None if it
        isn't materialized right now (its parent folder may still be
        collapsed -- refresh_explorer() only rebuilds open folders)."""
        tree = self.sidebar.tree
        if tree is None:
            return None
        target = os.path.normpath(os.path.abspath(path))

        def walk(node):
            for k in tree.get_children(node):
                vals = tree.item(k, "values")
                if vals and os.path.normpath(vals[0]) == target:
                    return k
                found = walk(k)
                if found:
                    return found
            return None
        return walk("")

    def _highlight_tree_node(self, node_id):
        """Tints one Explorer row so it's obvious, at a glance, exactly
        which file/folder Friday is working on right now."""
        tree = self.sidebar.tree
        if tree is None:
            return
        tree.tag_configure("agent-active", background=C["sel"])
        old = self._agent_highlight_node
        if old and old != node_id:
            self._unhighlight_tree_node(old)
        try:
            tags = tuple(t for t in tree.item(node_id, "tags")
                         if t != "agent-active")
            tree.item(node_id, tags=tags + ("agent-active",))
            self._agent_highlight_node = node_id
        except tk.TclError:
            pass

    def _unhighlight_tree_node(self, node_id=None):
        tree = self.sidebar.tree
        node_id = node_id or self._agent_highlight_node
        if tree is not None and node_id:
            try:
                if tree.exists(node_id):
                    tags = tuple(t for t in tree.item(node_id, "tags")
                                 if t != "agent-active")
                    tree.item(node_id, tags=tags)
            except tk.TclError:
                pass
        if self._agent_highlight_node == node_id:
            self._agent_highlight_node = None

    def _typewriter_tree_label(self, node_id, full_label,
                               interval_ms=14, on_done=None):
        """Animate an Explorer item's name appearing character by
        character, fast -- used only for entries Friday just created."""
        tree = self.sidebar.tree
        jobs = self._type_jobs
        old = jobs.pop(node_id, None)
        if old:
            try:
                self.after_cancel(old)
            except Exception:  # noqa: BLE001
                pass

        def step(i=0):
            try:
                exists = tree is not None and tree.exists(node_id)
            except tk.TclError:
                exists = False
            if not exists:
                jobs.pop(node_id, None)
                if on_done:
                    on_done()
                return
            tree.item(node_id, text=full_label[:i])
            if i < len(full_label):
                jobs[node_id] = self.after(interval_ms, lambda: step(i + 1))
            else:
                jobs.pop(node_id, None)
                if on_done:
                    on_done()
        step(0)

    def _apply_content_now(self, buf, content):
        """Force `buf` (and, if it's the active tab, the live Text
        widget) to exactly `content` right now, synchronously, no
        animation. Shared by the typewriter's own natural finish and by
        _flush_agent_write()'s early-flush path so both land the file's
        true content the same way."""
        buf["content"] = content
        buf["modified"] = False
        if buf.get("path"):
            buf["mtime"] = self._mtime(buf["path"])
        if self.current_buffer() is buf:
            t = self.editor.text
            try:
                self.editor._loading = True
                t.configure(state="normal")
                t.delete("1.0", "end")
                t.insert("1.0", content)
                t.edit_modified(False)
            except tk.TclError:
                pass
            finally:
                self.editor._loading = False
            self.editor.highlight()
            self.editor.redraw_tabs()
            self._refresh_title()

    def _flush_agent_write(self, buf=None):
        """Make sure `buf` (default: the current buffer) reflects its
        real, final content right now, with no animation left pending --
        called before anything that reads the live Text widget to decide
        what to save/run (save_file(), which run_file() also goes
        through).

        This covers two distinct race windows against a Friday agent write,
        both real and both tested (see dev_tests/
        test_agent_activity_visualization.py): (1) the typewriter is
        already ticking -- cancel its timer and jump straight to the end;
        (2) WorkspaceFS already wrote the file to disk but the animation
        hasn't even been scheduled/started yet (it's marshalled onto this
        thread via .after(0, ...), which only runs on a later trip
        through the event loop) -- in that window there's no timer to
        cancel yet, so _pending_agent_writes (populated synchronously at
        the moment of the real disk write, before any such scheduling) is
        consulted instead. Either way, the real file on disk was already
        written completely and correctly the instant Friday asked for it;
        only the on-screen "typing" is still catching up, and it must
        never be mistaken for -- or allowed to overwrite -- the file's
        actual, true content.
        """
        buf = buf or self.current_buffer()
        if buf is None:
            return
        entry = self._write_anim_jobs.get(id(buf))
        if entry:
            job = entry.get("job")
            if job:
                try:
                    self.after_cancel(job)
                except Exception:  # noqa: BLE001
                    pass
            flush = entry.get("flush")
            if flush:
                flush()
        path = buf.get("path")
        norm = os.path.normpath(os.path.abspath(path)) if path else None
        if norm and norm in self._pending_agent_writes:
            content = self._pending_agent_writes.pop(norm)
            self._apply_content_now(buf, content)

    def _run_typewriter(self, buf, content, on_done=None):
        """Types `content` into the shared editor Text widget, fast, in
        small chunks (not literally one character at a time -- that
        would take forever for a real file) while `buf` is the active
        tab. If the user switches to a different tab mid-animation, the
        rest is "typed" invisibly -- buf["content"] still ends up
        exactly right, it just isn't drawn until they switch back."""
        if not any(b is buf for b in self.buffers):
            if on_done:
                on_done()
            return
        t = self.editor.text
        jobs = self._write_anim_jobs
        old = jobs.pop(id(buf), None)
        if old and old.get("job"):
            try:
                self.after_cancel(old["job"])
            except Exception:  # noqa: BLE001
                pass
        self.editor._loading = True
        if self.current_buffer() is buf:
            try:
                t.configure(state="normal")
                t.delete("1.0", "end")
            except tk.TclError:
                pass
        buf["content"] = ""
        total = max(1, len(content))
        chunk = max(1, total // 140)
        interval_ms = 10
        state = {"done": False}

        def finish():
            if state["done"]:
                return
            state["done"] = True
            jobs.pop(id(buf), None)
            # Land the exact final text regardless of how far the
            # animation had actually gotten (covers both a normal finish
            # and an early flush mid-way through).
            self._apply_content_now(buf, content)
            if buf.get("path"):
                self._pending_agent_writes.pop(
                    os.path.normpath(os.path.abspath(buf["path"])), None)
            if on_done:
                on_done()

        def step(pos=0):
            if not any(b is buf for b in self.buffers):
                jobs.pop(id(buf), None)
                if on_done:
                    on_done()
                return
            if self.current_buffer() is not buf:
                finish()
                return
            end = min(pos + chunk, total)
            try:
                t.insert("end", content[pos:end])
                t.see("end")
            except tk.TclError:
                finish()
                return
            if end < total:
                job = self.after(interval_ms, lambda: step(end))
                jobs[id(buf)] = {"job": job, "flush": finish}
            else:
                finish()

        jobs[id(buf)] = {"job": None, "flush": finish}
        step(0)

    def animate_agent_write(self, path, content, on_done=None):
        """Open `path` as a (visible) buffer and type `content` into it
        live, instead of the normal instant bulk-load -- so watching the
        IDE actually shows Friday writing the code."""
        path = os.path.abspath(path)
        idx = next((i for i, b in enumerate(self.buffers)
                    if b.get("path") == path), None)
        if idx is None:
            self._stash()
            self.buffers.append({"name": os.path.basename(path),
                                 "path": path, "kind": "file", "content": "",
                                 "modified": False,
                                 "mtime": self._mtime(path)})
            idx = len(self.buffers) - 1
        self.current = idx
        self._load_current()
        buf = self.buffers[idx]
        # _load_current() defers its own "just finished loading" bookkeeping
        # to the widget's idle queue -- queuing the typewriter start the
        # same way guarantees it runs strictly afterwards, so the two
        # never fight over self.editor._loading.
        self.editor.after_idle(
            lambda: self._run_typewriter(buf, content, on_done=on_done))

    def animate_agent_create(self, path, content="", is_folder=False):
        """Visual feedback for a file/folder Friday just created: a
        highlighted, typed-out name in the Explorer, then (for a file
        with content) the code typed into the editor too."""
        name = os.path.basename(path)
        self.status.set_agent_status(
            f"Creating {'folder ' if is_folder else ''}{name}…", "create")
        sb = self.sidebar
        before = set()
        if sb.tree is not None:
            def walk(n):
                for k in sb.tree.get_children(n):
                    vals = sb.tree.item(k, "values")
                    if vals:
                        before.add(os.path.normpath(vals[0]))
                    walk(k)
            walk("")
        try:
            self._index_workspace()
        except Exception:  # noqa: BLE001
            pass
        self.refresh_explorer()
        self.update_idletasks()
        node = self._tree_node_for_path(path)
        if node is None:
            self.after(1200, self.status.clear_agent_status)
            return
        self._highlight_tree_node(node)
        is_new = os.path.normpath(os.path.abspath(path)) not in before

        def settle():
            self.after(500, lambda: (self._unhighlight_tree_node(node),
                                     self.status.clear_agent_status()))

        def after_name():
            if content and not is_folder:
                self.animate_agent_write(
                    path, content,
                    on_done=lambda: self.after(
                        300, lambda: (self._unhighlight_tree_node(node),
                                      self.status.clear_agent_status())))
            else:
                settle()

        if is_new:
            full_label = sb.tree.item(node, "text")
            self._typewriter_tree_label(node, full_label, on_done=after_name)
        else:
            after_name()

    def animate_agent_write_file(self, path, content):
        """Visual feedback for an existing file Friday is overwriting/
        editing: highlights it in the Explorer and types the new content
        into the editor."""
        name = os.path.basename(path)
        self.status.set_agent_status(f"Writing {name}…", "write")
        try:
            self._index_workspace()
        except Exception:  # noqa: BLE001
            pass
        self.refresh_explorer()
        self.update_idletasks()
        node = self._tree_node_for_path(path)
        if node is not None:
            self._highlight_tree_node(node)

        def done():
            if node is not None:
                self.after(300, lambda: self._unhighlight_tree_node(node))
            self.status.clear_agent_status()
        self.animate_agent_write(path, content, on_done=done)

    def git_init_repository(self):
        """"Initialize Repository" in the Source Control view -- runs a
        real `git init` in the open workspace, visibly in the integrated
        terminal, then refreshes the Explorer/Source Control view so the
        new (empty) repo and its status immediately show up."""
        if not shutil.which("git"):
            self.panel_error("Git isn't installed, so a repository can't "
                             "be initialized here.")
            return
        try:
            self.run_terminal_command(
                f'git init "{self.root_dir}"', timeout=15)
        except Exception as exc:  # noqa: BLE001
            self.panel_error(f"git init failed: {exc}")
            return
        if not os.path.isdir(os.path.join(self.root_dir, ".git")):
            self.panel_error("git init did not complete successfully -- "
                             "check the Terminal panel for details.")
            return
        self.refresh_explorer()
        if self.sidebar.mode == "git":
            self.sidebar.show("git")

    def clone_repository_dialog(self):
        """Small modal to clone a Git repo and open it as the workspace.

        The clone itself runs through run_terminal_command() on a
        background thread -- visible in the integrated terminal exactly
        like any other command -- so the dialog (and the rest of the UI)
        stays responsive while it runs.
        """
        top = self._dialog("Clone Repository", 460, 250)
        parent = top.body

        tk.Label(parent, text="Repository URL", bg=C["sidebar"],
                 fg=C["fg_dim"], font=self.f_ui, anchor="w"
                 ).pack(fill="x", padx=14, pady=(14, 4))
        url_var = tk.StringVar()
        url_entry = tk.Entry(
            parent, textvariable=url_var, bg=C["input"], fg=C["fg"],
            insertbackground=C["fg"], relief="flat",
            highlightthickness=1, highlightbackground=C["border"],
            highlightcolor=C["accent"], font=self.f_ui)
        url_entry.pack(fill="x", padx=14, ipady=5)

        tk.Label(parent, text="You'll be asked where to clone it into; "
                 "it opens automatically once done.",
                 bg=C["sidebar"], fg=C["fg_faint"],
                 font=(self.f_ui[0], *ts(-1)), anchor="w", justify="left",
                 wraplength=420).pack(fill="x", padx=14, pady=(10, 2))

        status_var = tk.StringVar(value="")
        tk.Label(parent, textvariable=status_var, bg=C["sidebar"],
                 fg=C["term_err"], font=(self.f_ui[0], *ts(-1)),
                 anchor="w", justify="left", wraplength=420
                 ).pack(fill="x", padx=14, pady=(2, 2))

        row = tk.Frame(parent, bg=C["sidebar"])
        row.pack(fill="x", padx=14, pady=(10, 14), side="bottom")

        def do_clone():
            url = url_var.get().strip()
            if not url:
                status_var.set("Enter a repository URL first.")
                return
            dest_parent = filedialog.askdirectory(
                title="Choose where to clone into")
            if not dest_parent:
                return
            name = url.rstrip("/").rsplit("/", 1)[-1]
            if name.endswith(".git"):
                name = name[:-4]
            name = name or "repository"
            dest = os.path.join(dest_parent, name)
            if os.path.exists(dest):
                status_var.set(f"'{name}' already exists there.")
                return
            clone_btn.configure(state="disabled", text="Cloning…")
            cancel_btn.configure(state="disabled")
            status_var.set("Cloning — watch progress in the terminal panel…")

            def worker():
                self.run_terminal_command(
                    f'git clone "{url}" "{dest}"', timeout=600)
                ok = os.path.isdir(os.path.join(dest, ".git"))

                def finish():
                    try:
                        if not top.winfo_exists():
                            return
                    except tk.TclError:
                        return
                    if ok:
                        top.destroy()
                        self.set_root(dest)
                    else:
                        clone_btn.configure(state="normal", text="Clone")
                        cancel_btn.configure(state="normal")
                        status_var.set(
                            "Clone failed — see the terminal panel for "
                            "details.")
                self.after(0, finish)

            threading.Thread(target=worker, daemon=True,
                             name="FridayCloneRepo").start()

        clone_btn = self.flat_button(row, "Clone", do_clone)
        clone_btn.pack(side="right")
        cancel_btn = self.flat_button(row, "Cancel", top.destroy,
                                      secondary=True)
        cancel_btn.pack(side="right", padx=(0, 8))
        url_entry.bind("<Return>", lambda e: do_clone())
        top.focus_widget = url_entry
        top.activate()


    def set_root(self, d):
        self.root_dir = os.path.abspath(d)
        self.term_cwd = self.root_dir
        self.workspace_files = []
        self.sidebar.show("explorer")
        self._refresh_title()

    def open_file(self, path, line=None):
        path = os.path.abspath(path)
        for i, buf in enumerate(self.buffers):
            if buf.get("path") == path:
                self.switch_tab(i)
                if line:
                    self.goto_line(line)
                return
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if (ext in IMAGE_EXTS or ext == "pdf") and not os.path.isfile(path):
            # text files report this via the open() below; media routed by
            # extension would otherwise create an empty, confusing tab
            messagebox.showerror("Open File",
                                 f"File not found:\n{path}")
            return
        if ext in IMAGE_EXTS:
            self._add_buffer({"name": os.path.basename(path), "path": path,
                              "kind": "media", "media": "image",
                              "content": "", "modified": False,
                              "mtime": self._mtime(path)})
            return
        if ext == "pdf":
            return self._open_pdf(path)
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            content = raw.decode("utf-8", errors="replace")
        except OSError as ex:
            messagebox.showerror("Open File", str(ex))
            return
        if _looks_binary(raw):
            content = (f"⚠ Binary file — not shown as text\n\n"
                       f"    {os.path.basename(path)}\n"
                       f"    {_human_size(len(raw))}\n\n"
                       f"Editing it here would corrupt it, so the contents are "
                       f"withheld.")
        self._add_buffer({"name": os.path.basename(path), "path": path,
                          "kind": "file", "content": content,
                          "modified": False, "mtime": self._mtime(path)})
        if line:
            self.goto_line(line)

    def _crumb_text(self, buf):
        p = buf.get("path")
        if not p:
            return buf.get("name", "")
        try:
            rel = os.path.relpath(p, self.root_dir)
        except ValueError:
            rel = p
        return "  \u203a  ".join(rel.split(os.sep))

    def _open_pdf(self, path):
        """Render the PDF when a renderer exists; always offer the text."""
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError as ex:
            messagebox.showerror("Open File", str(ex))
            return
        name = os.path.basename(path)
        # Probe by actually rendering page 1: a tool can be installed and
        # still be unable to render PDFs (ImageMagick needs Ghostscript).
        # Trusting mere presence produced a blank viewer tab.
        import tempfile
        probe = tempfile.mkdtemp(prefix="idepdfprobe")
        try:
            rendered = pdf_render_page(path, 1, probe, 80)
        except Exception:  # noqa: BLE001
            rendered = None
        finally:
            shutil.rmtree(probe, ignore_errors=True)
        if rendered:
            self._add_buffer({"name": name, "path": path, "kind": "media",
                              "media": "pdf", "content": "",
                              "modified": False, "mtime": self._mtime(path)})
            return
        # no renderer: fall back to extracted text so the file is still usable
        header = [f"{name}", "=" * len(name), ""]
        header.append(pdf_summary(path)[0])
        if pdf_is_encrypted(raw):
            header.append("This PDF is encrypted; text may be unavailable.")
        header += ["", "No PDF renderer found (pdftoppm / mutool / gs /",
                   "magick), so the page images cannot be shown.",
                   "Extracted text follows.", "-" * 60, ""]
        text, found = pdf_extract_text(raw)
        if not found or not text.strip():
            text = ("(No extractable text - this PDF is probably scanned "
                    "images. Install poppler-utils, mupdf-tools or "
                    "Ghostscript to view the pages.)")
        self._add_buffer({"name": name, "path": path, "kind": "file",
                          "content": "\n".join(header) + text,
                          "modified": False, "readonly": True,
                          "mtime": self._mtime(path)})

    def _add_buffer(self, buf):
        self._stash()
        self.buffers.append(buf)
        self.current = len(self.buffers) - 1
        self._load_current()

    def switch_tab(self, i):
        if i == self.current or not (0 <= i < len(self.buffers)):
            return
        self._stash()
        self.current = i
        self._load_current()

    def close_tab(self, i, prompt=True):
        if not (0 <= i < len(self.buffers)):
            return
        buf = self.buffers[i]
        if buf.get("modified") and prompt:
            ans = messagebox.askyesnocancel(
                "Unsaved Changes",
                f"Do you want to save the changes to {buf['name']}?")
            if ans is None:
                return
            if ans:
                self.switch_tab(i)
                if not self.save_file():
                    return
        del self.buffers[i]
        if not self.buffers:
            self.current = -1
            self._load_current(force=True)
            return
        self.current = min(self.current, len(self.buffers) - 1)
        if i < self.current:
            self.current -= 1
        self._load_current(force=True)

    def close_current_tab(self):
        self.close_tab(self.current)

    def _close_editor_sc(self):
        if self.quickopen_open:
            return
        self.close_current_tab()
        return "break"

    def _load_current(self, force=False):
        buf = self.current_buffer()
        if not buf:
            self.editor.show_empty()
            self._refresh_title()
            self.status.pos.configure(text="")
            self.status.lang.configure(text="")
            self.status.enc.configure(text="")
            return
        self.editor.hide_empty()
        self.editor.redraw_tabs()
        self.editor.hide_find()
        self.completion_hide()
        if buf.get("kind") == "media":
            self.editor.hide_empty()
            self.editor.show_media(buf)
            self.editor.crumb.configure(text=self._crumb_text(buf))
            self._refresh_title()
            self.update_status()
            return
        self.editor.hide_media()
        if True:
            t = self.editor.text
            # every opened file renders at exactly EDITOR_FONT_SIZE
            t.configure(font=self.f_mono)
            self.editor._loading = True
            t.configure(state="normal")
            t.delete("1.0", "end")
            t.insert("1.0", buf.get("content", ""))
            t.edit_reset()
            t.edit_modified(False)
            t.mark_set("insert", "1.0")
            # <<Modified>> can fire on the idle loop *after* the load, which
            # would falsely flag the buffer as dirty -> clear it there.
            def _finish_load(b=buf):
                self.editor._loading = False
                t.edit_modified(False)
                if b.get("modified"):
                    b["modified"] = False
                    self.editor.redraw_tabs()
                    self.sidebar.refresh_open_editors()
                    self._refresh_title()
            self.editor.after_idle(_finish_load)
            self.editor._queue_gutter()
            self.editor.after_idle(self.editor.highlight)
            rel = (os.path.relpath(buf["path"], self.root_dir).replace(os.sep, " › ")
                   if buf.get("path") else buf["name"])
            self.editor.crumb.configure(text=rel)
            self.cmdcenter_set(buf["name"])
            self.focus_editor()
        self._refresh_title()
        self.update_status()
        self.sidebar.refresh_open_editors()

    def reload_current(self):
        buf = self.current_buffer()
        if buf and buf.get("path"):
            try:
                with open(buf["path"], encoding="utf-8",
                          errors="replace") as fh:
                    buf["content"] = fh.read()
                buf["modified"] = False
                self._load_current(force=True)
            except OSError:
                pass

    def mark_dirty(self):
        buf = self.current_buffer()
        if buf and buf["kind"] == "file" and not buf.get("modified"):
            buf["modified"] = True
            self.editor.redraw_tabs()
            self.sidebar.refresh_open_editors()
            self._refresh_title()

    def save_file(self):
        buf = self.current_buffer()
        # A Friday typewriter animation still mid-flight must never be
        # mistaken for the file's real content -- jump it straight to
        # its final text first, so an impatient Ctrl+S (or run_file(),
        # which calls this) can't ever save/run a half-typed truncation
        # of what was already written to disk correctly and instantly.
        self._flush_agent_write(buf)
        if not buf or buf["kind"] != "file":
            return False
        if buf.get("readonly"):
            messagebox.showinfo(
                "Read Only",
                f"{buf['name']} is shown as extracted text and cannot be "
                f"saved back to the original file.")
            return False
        if not buf.get("path"):
            return self.save_file_as()
        content = self.editor.text.get("1.0", "end-1c")
        try:
            with open(buf["path"], "w", encoding="utf-8") as fh:
                fh.write(content)
        except OSError as ex:
            messagebox.showerror("Save", str(ex))
            return False
        buf["content"] = content
        buf["modified"] = False
        buf["mtime"] = self._mtime(buf["path"])
        self.editor.redraw_tabs()
        self.sidebar.refresh_open_editors()
        self._refresh_title()
        return True

    def save_file_as(self):
        buf = self.current_buffer()
        if not buf or buf["kind"] != "file":
            return False
        p = filedialog.asksaveasfilename(initialdir=self.root_dir,
                                         initialfile=buf["name"])
        if not p:
            return False
        buf["path"] = p
        buf["name"] = os.path.basename(p)
        return self.save_file()

    def save_all(self):
        """Save every dirty buffer that has a path. Returns how many."""
        self._stash()
        saved, keep = 0, self.current
        for i, buf in enumerate(self.buffers):
            if buf.get("modified") and buf.get("path"):
                self.current = i
                if buf is not self.buffers[keep]:
                    try:
                        with open(buf["path"], "w", encoding="utf-8") as fh:
                            fh.write(buf.get("content", ""))
                        buf["modified"] = False
                        buf["mtime"] = self._mtime(buf["path"])
                        saved += 1
                    except OSError:
                        pass
        self.current = keep
        if self.save_file():          # the visible one, from the widget
            saved += 1
        self.editor.redraw_tabs()
        self.sidebar.refresh_open_editors()
        self._refresh_title()
        return saved

    def refresh_explorer(self):
        """Re-read the workspace folder into the tree, keeping what is open."""
        sb = self.sidebar
        if sb.mode != "explorer":
            return
        if sb.tree is None:
            # Either the tree has never been built yet, or the Explorer is
            # currently showing the "no folder open" prompt instead of a
            # tree -- a full show("explorer") re-evaluates which of those
            # is actually correct right now (e.g. Friday may have just
            # written the placeholder workspace's first file) and builds
            # whichever belongs.
            sb.show("explorer")
            return
        opened = set()
        def walk(node):
            for k in sb.tree.get_children(node):
                vals = sb.tree.item(k, "values")
                if vals and sb.tree.item(k, "open"):
                    opened.add(vals[0])
                walk(k)
        walk("")
        sb.show("explorer")
        def reopen(node):
            for k in sb.tree.get_children(node):
                vals = sb.tree.item(k, "values")
                if vals and vals[0] in opened and os.path.isdir(vals[0]):
                    sb.tree.item(k, open=True)
                    sb._fill_dir(k, vals[0])
                    reopen(k)
        reopen("")

    # ---------------- external change detection ----------------
    @staticmethod
    def _mtime(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return None

    def _start_watcher(self, interval=1500):
        """Poll open files so edits made outside the IDE (e.g. by an AI
        agent, git checkout or another editor) show up automatically."""
        self._watch_interval = interval
        self._watch_job = self.after(interval, self._watch_tick)

    def _watch_tick(self):
        try:
            if not self.winfo_exists():
                return
            self._check_external_changes()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._watch_job = self.after(self._watch_interval,
                                         self._watch_tick)
        except tk.TclError:
            pass

    # ---------------- Friday state glow (agent-controlled runs only) ------
    # The window's own outline (see highlightthickness/_glow_thickness in
    # __init__) is recolored to match Friday's live state. Friday and this
    # IDE share one process but each GUI toolkit gets its own dedicated
    # thread (Qt's main thread, and this IDE's own native Tk mainloop()
    # thread -- see agent_tools._tk_worker_loop/_TkThreadBridge), so
    # there's no polling: agent_overlay.py's CircleOverlay._enter_state
    # calls set_friday_status() every time Friday's own state changes,
    # always marshaled onto *this* thread first via
    # agent_tools._post_on_main() (see CircleOverlay._push_ide_status) --
    # this method itself can assume it's always running on the Tk thread
    # by the time it's actually called.
    _GLOW_IDLE = "#ffffff"  # matches every panel's white border when idle
    _GLOW_BUSY = "#3b82f6"
    _GLOW_OK = "#2ecc71"
    _GLOW_ERR = "#e74c3c"

    def set_friday_status(self, state, is_error=False):
        """Push Friday's current state straight into the window-border glow.
        `state` is one of "idle" / "listening" / "loading" / "responding"
        -- the same vocabulary CircleOverlay._enter_state already uses
        for its own ring, so one call here keeps both rings in sync."""
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if state == "responding" and is_error:
            color = self._GLOW_ERR
        elif state in ("listening", "loading"):
            color = self._GLOW_BUSY
        elif state == "responding":
            color = self._GLOW_OK
        else:
            color = self._GLOW_IDLE
        # Remembered (the raw state/is_error pair, exactly as given) so
        # the active-panel pulse (if running) knows whether it's
        # allowed to actually paint right now -- Friday's own live
        # status always wins over the passive "this is the active
        # panel" cue, same priority the plain static idle-white border
        # always implicitly had -- and so set_active_panel(False) can
        # restore the exact right static color once the pulse stops.
        self._friday_glow_state = state
        self._friday_glow_is_error = is_error
        if color == self._GLOW_IDLE and getattr(self, "_is_active_panel", False):
            return  # the active-glow ticker owns painting the border right now
        try:
            self.configure(highlightbackground=color, highlightcolor=color)
        except tk.TclError:
            pass

    def _paint_active_glow_color(self, hexcolor):
        """_ActiveGlowAnimator's set_color callback -- only actually
        paints the border while Friday's own live status is idle (see
        set_friday_status's matching comment); otherwise a no-op, since
        the busy/ok/error status color is already showing and takes
        priority. The ticker itself just keeps running regardless, so
        the pulse resumes immediately, with no extra wiring needed,
        the moment Friday's status goes back to idle."""
        if getattr(self, "_friday_glow_state", "idle") != "idle":
            return
        try:
            self.configure(highlightbackground=hexcolor, highlightcolor=hexcolor)
        except tk.TclError:
            pass

    def set_active_panel(self, active):
        """Tells this IDE window whether it's currently Friday's single
        active/maximized panel -- the one in the unified placement
        system's center/maximized slot -- so it can show (active) or
        stop showing (not active) the pulsing violet active-panel
        border. Called by agent_tools.py every time
        _maximized_panel_key changes. Safe to call repeatedly with the
        same value."""
        active = bool(active)
        if active == getattr(self, "_is_active_panel", False):
            return
        self._is_active_panel = active
        if active:
            self._active_glow.start()
        else:
            self._active_glow.stop()
            # Repaint immediately with whatever static color Friday's
            # own live status calls for right now (plain white if
            # idle), rather than leaving the last mid-pulse violet
            # shade stuck on screen until something else happens to
            # trigger a repaint.
            self.set_friday_status(getattr(self, "_friday_glow_state", "idle"),
                                    is_error=getattr(self, "_friday_glow_is_error", False))

    def destroy(self):
        """Cancel pending timers so nothing fires after the window dies,
        then tell Friday (if this IDE is one of its own windows) that it's
        gone -- the single, authoritative place that transition happens
        no matter how destroy() was reached (a close_window() from the
        agent_mode_off tool, Alt+F4/WM_DELETE_WINDOW, or Friday force-
        closing every window it owns on its own way out)."""
        for attr in ("_watch_job", "_geom_anim_job"):
            job = getattr(self, attr, None)
            if job:
                try:
                    self.after_cancel(job)
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, attr, None)
        active_glow = getattr(self, "_active_glow", None)
        if active_glow is not None:
            active_glow.stop()
        _cleanup_temp_dirs()
        self._drop_image_caches()
        super().destroy()
        if self._agent_host is not None:
            try:
                self._agent_host.on_ide_closed()
            except Exception:  # noqa: BLE001
                pass

    def _drop_image_caches(self):
        """Explicitly empties every per-widget PhotoImage cache (e.g.
        SideBar._icon()'s self._imgs) in this window's tree before the
        real teardown below.

        Why this matters specifically for Friday's agent-controlled runs
        (standalone use of this file doesn't need it -- the process
        just exits and the OS reclaims everything): when Friday runs this
        IDE in-process on its own dedicated thread (see agent_tools.py's
        agent_mode_on()), a widget tree this size is riddled with
        reference cycles (parent<->child back-references, bound methods
        stashed as menu commands, etc) that plain refcounting alone can
        never free -- only Python's cyclic collector can, and only
        *whenever* it next happens to run, which could be long after
        this window is gone (even during interpreter shutdown, on a
        totally different thread). A PhotoImage finalized that late
        doesn't raise a catchable Python exception -- Tcl considers
        itself no longer in a runnable state by then and panics with a
        hard, unrecoverable process abort. Clearing known image caches
        up front, here, while this window's Tcl interpreter is still
        fully alive and able to process the resulting "delete this
        image" calls, means there's nothing left to be swept up late by
        surprise.
        """
        seen = set()

        def _walk(widget):
            wid = id(widget)
            if wid in seen:
                return
            seen.add(wid)
            imgs = getattr(widget, "_imgs", None)
            if isinstance(imgs, dict):
                imgs.clear()
            try:
                children = widget.winfo_children()
            except Exception:  # noqa: BLE001
                children = []
            for child in children:
                _walk(child)

        try:
            _walk(self)
        except Exception:  # noqa: BLE001
            pass

    def _check_external_changes(self):
        reloaded = []
        for i, buf in enumerate(self.buffers):
            p = buf.get("path")
            if not p or buf["kind"] != "file" or buf.get("readonly"):
                continue
            m = self._mtime(p)
            if m is None or buf.get("mtime") is None:
                buf["mtime"] = m
                continue
            if m == buf["mtime"]:
                continue
            buf["mtime"] = m
            if buf.get("modified"):
                # do not clobber the user's unsaved edits
                buf["conflict"] = True
                continue
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            buf["content"] = text
            reloaded.append(i)
            if i == self.current:
                t = self.editor.text
                pos = t.index("insert")
                first = t.yview()[0]
                self.editor._loading = True
                t.delete("1.0", "end")
                t.insert("1.0", text)
                t.edit_modified(False)
                self.editor._loading = False
                try:
                    t.mark_set("insert", pos)
                    t.yview_moveto(first)
                except tk.TclError:
                    pass
                self.editor.highlight()
                self.editor._queue_gutter()
        if reloaded:
            self.status.pos.configure(text=self.status.pos.cget("text"))
            self.refresh_explorer()

    # ---------------- chrome updates ----------------
    def cmdcenter_set(self, text):
        self.cmdcenter.configure(state="normal")
        self.cmdcenter.delete(0, "end")
        self.cmdcenter.insert(0, text)
        self.cmdcenter.configure(state="readonly")

    def _refresh_title(self):
        buf = self.current_buffer()
        name = buf["name"] if buf else ""
        dot = "● " if buf and buf.get("modified") else ""
        folder = self.workspace_display_name()
        self.title(f"{dot}{name} — {folder} — {APP_NAME}" if name else
                   f"{folder} — {APP_NAME}")

    def update_status(self):
        buf0 = self.current_buffer()
        if buf0 and buf0.get("kind") == "media":
            mv = self.editor.media
            size = getattr(mv, "base_size", None)
            self.status.pos.configure(
                text=(f"{size[0]} x {size[1]} px" if size else "media"))
            self.status.lang.configure(
                text=("PDF" if buf0.get("media") == "pdf" else
                      (buf0["name"].rsplit(".", 1)[-1].upper()
                       if "." in buf0["name"] else "Image")))
            self.status.enc.configure(text="binary")
            return
        return self._update_status_text()

    def _update_status_text(self):
        try:
            i = self.editor.text.index("insert")
        except tk.TclError:
            return
        line, col = i.split(".")
        buf = self.current_buffer()
        self.status.update(buf["name"] if buf else "", line, int(col) + 1,
                           buf.get("modified") if buf else False)
        self.editor._mark_current_line()
        self.editor._queue_gutter()

    # ---------------- views ----------------
    def show_sidebar_mode(self, name):
        if self.sidebar_visible and self.sidebar.mode == name:
            self.toggle_sidebar()
            return
        if not self.sidebar_visible:
            self.toggle_sidebar()
        self.sidebar.show(name)

    def toggle_sidebar(self):
        w = band(264)
        if self.sidebar_visible:
            self.sidebar_visible = False
            animate_pane(self.body, self.sidebar, "width", 0, ms=140,
                         done=lambda: self._finish_hide_sidebar())
        else:
            self.body.add(self.sidebar, minsize=0, width=1,
                          stretch="never", before=self.vpanes)
            self.sidebar_visible = True
            animate_pane(self.body, self.sidebar, "width", w, ms=160,
                         done=lambda: self._settle_sidebar(w))

    def _finish_hide_sidebar(self):
        try:
            self.body.forget(self.sidebar)
        except Exception:  # noqa: BLE001
            pass

    def _settle_sidebar(self, w):
        try:
            self.body.paneconfigure(self.sidebar, minsize=band(180), width=w)
        except Exception:  # noqa: BLE001
            pass

    def toggle_panel(self):
        if self.panel_visible:
            self.vpanes.forget(self.panel)
            self.panel_visible = False
            self.focus_editor()
        else:
            self.vpanes.add(self.panel, minsize=80, height=200,
                            stretch="never")
            self.panel_visible = True
            self.panel.term.focus_set()
            if not getattr(self.panel, "_started", False):
                self.panel._started = True
                self.panel.start()

    def toggle_minimap(self):
        self.editor.toggle_minimap()

    def focus_editor(self):
        buf = self.current_buffer()
        if buf and buf["kind"] == "file":
            self.editor.text.focus_set()

    def quick_open(self, initial=""):
        if self.quickopen_open:
            return
        self._index_workspace()
        QuickOpen(self, initial)
        return "break"

    def _index_workspace(self):
        files = []
        for dirpath, dirs, fns in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in fns:
                files.append(os.path.join(dirpath, fn))
                if len(files) >= 3000:
                    break
        self.workspace_files = files

    def goto_line_dialog(self):
        self.quick_open(":")

    def goto_line(self, n):
        buf = self.current_buffer()
        if not buf or buf["kind"] != "file":
            return
        t = self.editor.text
        t.mark_set("insert", f"{n}.0")
        t.see(f"{n}.0")
        self.focus_editor()
        self.update_status()

    def show_find(self, replace=False):
        buf = self.current_buffer()
        if buf and buf["kind"] == "file":
            self.editor.show_find(replace)

    # ---------------- edit helpers ----------------
    def _undo(self):
        try:
            self.editor.text.edit_undo()
        except tk.TclError:
            pass
        self.editor._after_edit()

    def _redo(self):
        try:
            self.editor.text.edit_redo()
        except tk.TclError:
            pass
        self.editor._after_edit()

    def _select_all(self):
        self.editor.text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _duplicate_line(self):
        t = self.editor.text
        line = t.get("insert linestart", "insert lineend")
        t.insert("insert lineend", "\n" + line)
        self.editor._after_edit()

    def _move_line(self, d):
        t = self.editor.text
        n = int(t.index("insert").split(".")[0])
        tgt = n + d
        last = int(t.index("end-1c").split(".")[0])
        if tgt < 1 or tgt > last:
            return
        line = t.get(f"{n}.0", f"{n}.end")
        other = t.get(f"{tgt}.0", f"{tgt}.end")
        col = t.index("insert").split(".")[1]
        t._autoseparators = False  # type: ignore[attr-defined]
        t.delete(f"{n}.0", f"{n}.end")
        t.insert(f"{n}.0", other)
        t.delete(f"{tgt}.0", f"{tgt}.end")
        t.insert(f"{tgt}.0", line)
        t.mark_set("insert", f"{tgt}.{col}")
        self.editor._after_edit()

    def zoom(self, d):
        self.font_size = max(8, min(28, self.font_size + d))
        self.f_mono = (self.f_mono[0], self.font_size)
        self.editor.text.configure(font=self.f_mono)
        pct = round(self.font_size / EDITOR_FONT_SIZE * 100)
        self.status.zoom.configure(text=f"{pct}%")
        self.editor._queue_gutter()

    def reset_zoom(self):
        self.font_size = zoomed_pt()
        self.f_mono = (self.f_mono[0], self.font_size)
        self.editor.text.configure(font=self.f_mono)
        self.status.zoom.configure(
            text=f"{round(self.font_size / EDITOR_FONT_SIZE * 100)}%")
        self.editor._queue_gutter()

    # ---------------- run ----------------
    # ---------------- filesystem commands (explorer menu) ----------------
    def _prompt_text(self, title, label, initial="", select_stem=True):
        """Modal text prompt. Returns the string, or None if cancelled."""
        top = self._dialog(title, 470, 210)
        body = top.body
        tk.Label(body, text=label, bg=C["sidebar"], fg=C["fg_dim"],
                 font=self.f_ui, anchor="w").pack(fill="x", padx=16,
                                                  pady=(16, 6))
        var = tk.StringVar(value=initial)
        ent = tk.Entry(body, textvariable=var, bg=C["input"], fg=C["fg_bright"],
                       insertbackground=C["fg_bright"], relief="flat",
                       highlightthickness=1, highlightbackground=C["border_hi"],
                       highlightcolor=C["accent"], font=self.f_ui)
        ent.pack(fill="x", padx=16, ipady=6)
        top.focus_widget = ent
        out = {"v": None}
        err = tk.Label(body, text="", bg=C["sidebar"], fg=C["danger"],
                       font=(self.f_ui[0], max(8, UI_FONT_SIZE - 1)),
                       anchor="w")
        err.pack(fill="x", padx=16)

        def ok(_e=None):
            name = var.get().strip()
            if not name:
                err.configure(text="Please type a name.")
                return
            if any(ch in name for ch in '<>:"|?*'):
                err.configure(text='A name cannot contain < > : " | ? *')
                return
            out["v"] = name
            top.destroy()

        def cancel(_e=None):
            top.destroy()

        row = tk.Frame(body, bg=C["sidebar"])
        row.pack(fill="x", padx=16, pady=(10, 14))
        self.flat_button(row, "OK", ok).pack(side="right")
        self.flat_button(row, "Cancel", cancel,
                         secondary=True).pack(side="right", padx=6)
        for w in (ent, top, body):
            w.bind("<Return>", ok)
            w.bind("<KP_Enter>", ok)
            w.bind("<Escape>", cancel)
        top.activate()
        # Tk only replaces the selection on keypress when the insert cursor
        # lies inside it, so the cursor must sit at the end of the selection
        # rather than at the end of the text.
        if initial and select_stem:
            stem = os.path.splitext(initial)[0]
            n = len(stem) if stem else len(initial)
            ent.selection_range(0, n)
            ent.icursor(n)
        else:
            ent.selection_range(0, "end")
            ent.icursor("end")
        self.wait_window(top)
        try:
            self.focus_editor()
        except Exception:  # noqa: BLE001
            pass
        return out["v"] or None

    def _fs_error(self, exc):
        messagebox.showerror("File Operation Failed", str(exc))

    def _forget_paths(self, path):
        """A path vanished: close any buffer that lived under it."""
        path = os.path.abspath(path)
        for i in range(len(self.buffers) - 1, -1, -1):
            bp = self.buffers[i].get("path")
            if not bp:
                continue
            bp = os.path.abspath(bp)
            if bp == path or bp.startswith(path + os.sep):
                self.buffers[i]["modified"] = False
                self.close_tab(i, prompt=False)

    def _repath(self, old, new):
        """A path was renamed/moved: retarget any open buffer."""
        old, new = os.path.abspath(old), os.path.abspath(new)
        changed = False
        for buf in self.buffers:
            bp = buf.get("path")
            if not bp:
                continue
            bp = os.path.abspath(bp)
            if bp == old:
                buf["path"], buf["name"] = new, os.path.basename(new)
                changed = True
            elif bp.startswith(old + os.sep):
                buf["path"] = os.path.join(new, os.path.relpath(bp, old))
                buf["name"] = os.path.basename(buf["path"])
                changed = True
        if changed:
            self.editor.redraw_tabs()
            self._refresh_title()
            self.update_status()

    def _explorer_action(self, what):
        """Run a context-menu action against the explorer selection."""
        def go():
            p = (self.sidebar.selected_path() if self.sidebar.tree else None) \
                or self.root_dir
            if what == "reveal":
                self.reveal_in_file_manager(p)
            elif what == "find":
                self.find_in_folder(p if os.path.isdir(p)
                                    else os.path.dirname(p))
            elif what == "path":
                self.copy_path(p, False)
        return go

    def tab_menu(self, e, i):
        """Right-click on a tab."""
        if not (0 <= i < len(self.buffers)):
            return
        buf = self.buffers[i]
        m = tk.Menu(self, tearoff=0, bg=C["sidebar"], fg=C["fg"],
                    activebackground=C["list_sel"],
                    activeforeground=C["fg_bright"], bd=1, font=self.f_ui)
        has_path = bool(buf.get("path"))
        m.add_command(label="Close", command=lambda: self.close_tab(i))
        m.add_command(label="Close Others",
                      command=lambda: self.close_others(i))
        m.add_command(label="Close All", command=self.close_all_tabs)
        m.add_separator()
        m.add_command(label="Rename…", state="normal" if has_path else "disabled",
                      command=lambda: self.fs_rename(buf["path"]))
        m.add_command(label="Copy Path",
                      state="normal" if has_path else "disabled",
                      command=lambda: self.copy_path(buf["path"], False))
        m.add_command(label="Reveal in File Explorer",
                      state="normal" if has_path else "disabled",
                      command=lambda: self.reveal_in_file_manager(buf["path"]))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def close_others(self, keep):
        path = self.buffers[keep].get("path")
        name = self.buffers[keep].get("name")
        for i in range(len(self.buffers) - 1, -1, -1):
            b = self.buffers[i]
            if b.get("path") != path or b.get("name") != name:
                self.close_tab(i)

    def close_all_tabs(self):
        for i in range(len(self.buffers) - 1, -1, -1):
            self.close_tab(i)

    def rename_current(self):
        """Rename the file in the active tab (F2)."""
        buf = self.current_buffer()
        if not buf or not buf.get("path"):
            sel = self.sidebar.selected_path() if self.sidebar.tree else None
            if sel:
                return self.fs_rename(sel)
            return self.panel_error("Save the file before renaming it.")
        return self.fs_rename(buf["path"])

    def fs_new_file(self, base):
        name = self._prompt_text("New File", "File name", "", False)
        if not name:
            return
        try:
            p = self.fs.create_file(os.path.join(base, name))
            self.open_file(p)
        except Exception as ex:  # noqa: BLE001
            self._fs_error(ex)

    def fs_new_folder(self, base):
        name = self._prompt_text("New Folder", "Folder name", "", False)
        if not name:
            return
        try:
            self.fs.create_folder(os.path.join(base, name))
        except Exception as ex:  # noqa: BLE001
            self._fs_error(ex)

    def fs_rename(self, path):
        old = os.path.basename(path)
        name = self._prompt_text("Rename", f"New name for “{old}”", old)
        if not name or name == old:
            return
        try:
            self.fs.rename(path, name)
        except Exception as ex:  # noqa: BLE001
            self._fs_error(ex)

    def fs_delete(self, path):
        name = os.path.basename(path)
        kind = "folder and everything in it" if os.path.isdir(path) else "file"
        if not messagebox.askyesno(
                "Delete", f"Delete the {kind}?\n\n{name}\n\n"
                          f"This cannot be undone."):
            return
        try:
            self.fs.delete(path)
        except Exception as ex:  # noqa: BLE001
            self._fs_error(ex)

    def fs_duplicate(self, path):
        try:
            self.fs.copy(path, dst_dir=os.path.dirname(path))
        except Exception as ex:  # noqa: BLE001
            self._fs_error(ex)

    def fs_clip_set(self, path, op):
        self.fs_clip = (path, op)
        self.status.pos.configure(text=f"{op.title()}: {os.path.basename(path)}")

    def fs_paste(self, base):
        if not self.fs_clip:
            return
        src, op = self.fs_clip
        try:
            if op == "cut":
                self.fs.move(src, base)
                self.fs_clip = None
            else:
                self.fs.copy(src, dst_dir=base)
        except Exception as ex:  # noqa: BLE001
            self._fs_error(ex)

    def copy_path(self, path, relative):
        val = (os.path.relpath(path, self.root_dir) if relative
               else os.path.abspath(path))
        self.clipboard_clear()
        self.clipboard_append(val)
        self.status.pos.configure(text=f"Copied: {val}")

    def reveal_in_file_manager(self, path):
        path = os.path.abspath(path)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", path.replace("/", "\\")])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception as ex:  # noqa: BLE001
            self.panel_error(f"Could not open file manager: {ex}")

    def open_in_terminal(self, base):
        if not self.panel_visible:
            self.toggle_panel()
        self.panel._sel("TERMINAL")
        self.term_cwd = base if os.path.isdir(base) else os.path.dirname(base)
        self.panel.write(f"\n[cwd] {self.term_cwd}\n", "info")
        self.panel._prompt()

    def find_in_folder(self, base):
        self.show_sidebar_mode("search")
        self.sidebar.search_scope = base
        try:
            self.sidebar.s_query.focus_set()
        except Exception:  # noqa: BLE001
            pass

    # ---------------- build / run any project type ----------------
    def pdf_tmpdir(self):
        """One scratch directory for rendered PDF pages, owned by the app so
        that rebuilding the editor (theme switch) cannot orphan it."""
        d = getattr(self, "_pdf_tmpdir", None)
        if d and os.path.isdir(d):
            return d
        import tempfile
        d = tempfile.mkdtemp(prefix="idepdf")
        self._pdf_tmpdir = d
        _TEMP_DIRS.append(d)
        return d

    def _subst(self, cmd):
        return cmd.replace("{py}", sys.executable)

    def all_tasks(self):
        """Every task detected for this workspace, file task first."""
        tasks = []
        ft = detect_file_task(self._current_path(), sys.executable)
        if ft:
            tasks.append(ft)
        tasks.extend(detect_project_tasks(self.root_dir))
        return tasks

    def _current_path(self):
        buf = self.current_buffer()
        return buf.get("path") if buf else None

    def run_file(self):
        """F5 - run the file in the active tab, whatever language it is."""
        buf = self.current_buffer()
        if not buf or buf["kind"] != "file":
            return self.panel_error("Open a file first.")
        if not buf.get("path"):
            if not self.save_file_as():
                return None
        self.save_file()
        task = detect_file_task(buf["path"], sys.executable)
        if not task:
            ext = buf["name"].rsplit(".", 1)[-1] if "." in buf["name"] else "?"
            return self.panel_error(
                f"No run command known for .{ext} files. "
                f"Use Run > Tasks… to pick a project task.")
        return self.run_task(task)

    def run_project(self):
        """Ctrl+F5 - start the project (npm dev / cargo run / go run / ...)."""
        for t in detect_project_tasks(self.root_dir):
            if t["kind"] in ("run", "serve"):
                return self.run_task(t)
        return self.run_file()

    def build_project(self):
        for t in detect_project_tasks(self.root_dir):
            if t["kind"] == "build":
                return self.run_task(t)
        return self.panel_error("No build task detected in this workspace.")

    def run_task(self, task):
        """Execute a task, streaming output into the terminal panel."""
        if task["cmd"] == "__OPEN_BROWSER__":
            return self.open_in_browser()
        if self.task_proc is not None:
            self.stop_task()
        if not self.panel_visible:
            self.toggle_panel()
        p = self.panel
        p._sel("TERMINAL")
        cmd = self._subst(task["cmd"])
        p.write(f"\n[Run] {task['label']}\n", "info")
        p.write(f"$ {cmd}\n", "cwd")
        self.status.task.configure(text=f"\u25a0 {task['label']}")
        self._task_url_opened = False

        def worker():
            try:
                kw = {}
                if os.name == "posix":
                    kw["start_new_session"] = True
                else:
                    kw["creationflags"] = getattr(
                        subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                proc = subprocess.Popen(
                    cmd, shell=True, cwd=task.get("cwd") or self.root_dir,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                    env={**os.environ, "PYTHONUNBUFFERED": "1",
                         "FORCE_COLOR": "0", "TERM": "dumb"}, **kw)
                self.task_proc = proc
                for line in proc.stdout:
                    p.q.put((line, None))
                    if not self._task_url_opened:
                        url = find_url(line)
                        if url and task["kind"] in ("run", "serve"):
                            self._task_url_opened = True
                            self.after(0, lambda u=url: self._server_ready(u))
                rc = proc.wait()
                p.q.put((f"[Done] {task['label']} exited with code {rc}\n",
                         "err" if rc else "info"))
            except Exception as ex:  # noqa: BLE001
                p.q.put((f"{ex}\n", "err"))
            finally:
                self.task_proc = None
                self.after(0, lambda: self.status.task.configure(text=""))
                p.q.put(("\x00PROMPT", None))

        threading.Thread(target=worker, daemon=True).start()
        return task

    def _server_ready(self, url):
        self.server_url = url
        self.panel.write(f"[Server] {url}  (Run > Open in Browser)\n", "info")
        self.status.task.configure(text=f"\u25b6 {url}")
        if self.auto_open_browser:
            self.open_url(url)

    def open_url(self, url):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    def open_in_browser(self):
        """Open the current HTML file, or the running dev server."""
        if getattr(self, "server_url", None):
            return self.open_url(self.server_url)
        p = self._current_path()
        if p and p.lower().endswith((".html", ".htm", ".svg")):
            return self.open_url("file://" + os.path.abspath(p))
        return self.panel_error("No running server or HTML file to open.")

    def stop_task(self):
        """Terminate the running build/run process."""
        proc = self.task_proc
        if proc is None:
            return self.panel_error("Nothing is running.")
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
        except Exception:  # noqa: BLE001
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        self.panel.write("[Stopped]\n", "err")
        self.status.task.configure(text="")
        self.server_url = None
        return None

    def run_terminal_command(self, cmd, timeout=60.0):
        """Run a shell command in the IDE's own integrated terminal --
        visibly, exactly as if it had been typed there -- and block the
        calling thread until it finishes or `timeout` elapses, returning
        the captured output text. The subprocess itself always runs in
        its own fresh background thread (never the caller's), and all
        output is pushed through the terminal panel's existing
        thread-safe Queue (see Panel._run_cmd/_poll above). The only Tk
        widget touches here (revealing the panel, echoing the command)
        are marshaled onto the Tk thread via after(0, ...), the same
        pattern WorkspaceFS uses -- so this whole method is safe to call
        directly from Friday's own background worker thread, with no
        further marshaling needed by the caller."""
        panel = self.panel
        if panel.proc is not None:
            return ("A command is already running in the terminal -- "
                    "wait for it to finish or stop it first.")

        def echo():
            try:
                if not self.panel_visible:
                    self.toggle_panel()
                panel._sel("TERMINAL")
                panel.history.append(cmd)
                panel.hidx = len(panel.history)
                panel.write(cmd + "\n")
            except Exception:  # noqa: BLE001
                pass
        try:
            self.after(0, echo)
        except Exception:  # noqa: BLE001
            pass

        done = threading.Event()
        collected = []

        def worker():
            try:
                panel.proc = subprocess.Popen(
                    cmd, shell=True, cwd=self.term_cwd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, env={**os.environ, "TERM": "dumb"})
                for line in panel.proc.stdout:
                    collected.append(line)
                    panel.q.put((line, None))
                rc = panel.proc.wait()
                if rc:
                    msg = f"(exit code {rc})\n"
                    collected.append(msg)
                    panel.q.put((msg, "err"))
            except Exception as ex:  # noqa: BLE001
                msg = f"{ex}\n"
                collected.append(msg)
                panel.q.put((msg, "err"))
            finally:
                panel.proc = None
                panel.q.put(("\x00PROMPT", None))
                done.set()

        threading.Thread(target=worker, daemon=True,
                         name="FridayTerminalCmd").start()
        finished = done.wait(timeout)
        output = "".join(collected)
        if not finished:
            return (output + f"\n(still running after {timeout:.0f}s -- "
                    "output above is partial; it keeps streaming into the "
                    "terminal panel and can be stopped with Ctrl+C there)")
        return output or "(no output)"

    def get_terminal_output(self):
        """A plain snapshot of everything currently visible in the
        integrated terminal panel -- read-only, just a Tk Text widget
        read, so it's cheap. Lets Friday check back on output from a task
        started earlier (run_file/run_project/build_project) without
        having to keep its own call blocked the whole time."""
        return self.panel.term.get("1.0", "end-1c")

    def show_tasks(self):
        """A picker listing every detected build/run task."""
        tasks = self.all_tasks()
        top = self._dialog("Run Task", 620, 420)
        top = top  # keep the shell; widgets go in top.body
        parent = top.body
        tk.Label(parent, text=f"Tasks detected in "
                              f"{self.workspace_display_name()}",
                 bg=C["sidebar"], fg=C["fg_dim"], font=self.f_ui,
                 anchor="w").pack(fill="x", padx=14, pady=(12, 6))
        lb = tk.Listbox(parent, bg=C["editor"], fg=C["fg"], relief="flat",
                        highlightthickness=1, highlightbackground=C["border"],
                        selectbackground=C["list_sel"],
                        selectforeground=C["fg_bright"],
                        font=self.f_ui, activestyle="none")
        lb.pack(fill="both", expand=True, padx=14)
        icons = {"run": "\u25b6", "serve": "\u25b6", "build": "\u2699",
                 "test": "\u2713", "browser": "\u2197"}
        for t in tasks:
            lb.insert("end", f"  {icons.get(t['kind'], '\u25b6')}  "
                             f"{t['label']}   \u2014   {t['cmd']}")
        if tasks:
            lb.selection_set(0)

        def go(_e=None):
            sel = lb.curselection()
            if sel:
                top.destroy()
                self.run_task(tasks[sel[0]])
        lb.bind("<Double-1>", go)
        lb.bind("<Return>", go)
        row = tk.Frame(parent, bg=C["sidebar"])
        row.pack(fill="x", padx=14, pady=10)
        top.focus_widget = lb
        top.activate()
        self.flat_button(row, "Run", go).pack(side="right")
        self.flat_button(row, "Cancel", top.destroy,
                         secondary=True).pack(side="right", padx=6)
        if not tasks:
            lb.insert("end", "  No tasks detected in this workspace")

    def panel_error(self, msg):
        if not self.panel_visible:
            self.toggle_panel()
        self.panel.write(msg + "\n", "err")
        self.panel._prompt()

    # ---------------- autocomplete ----------------
    completion_active = False

    def autocomplete(self, trigger=False):
        t = self.editor.text
        buf = self.current_buffer()
        if not buf or buf["kind"] != "file":
            return
        prefix = t.get("insert wordstart", "insert")
        prev = t.get("insert-1c", "insert")
        if not trigger and prev != "." and len(prefix) < 2:
            if self.completion_active:
                self.completion_hide()
            return
        code = t.get("1.0", "end-1c")
        words = set(re.findall(r"[A-Za-z_]\w{2,}", code))
        words |= set(PY_KEYWORDS) | set(PY_BUILTINS)
        matches = sorted(w for w in words
                         if w.lower().startswith(prefix.lower())
                         and w != prefix)
        if prev == ".":
            matches = sorted(words)[:40]
        if not matches:
            self.completion_hide()
            return
        bbox = t.bbox("insert")
        if not bbox:
            return
        x = t.winfo_rootx() + bbox[0]
        y = t.winfo_rooty() + bbox[1] + bbox[3] + 2
        self.completion_show(matches[:30], prefix, x, y)

    def completion_show(self, items, prefix, x, y):
        self.completion_hide()
        top = tk.Toplevel(self)
        top.overrideredirect(True)
        top.configure(bg=C["border"])
        lb = tk.Listbox(top, height=min(8, len(items)), width=28,
                        bg=C["sidebar"], fg=C["fg"], relief="flat", bd=0,
                        highlightthickness=1, highlightbackground=C["accent"],
                        selectbackground=C["list_sel"],
                        selectforeground=C["fg_bright"],
                        font=self.f_ui, activestyle="none")
        lb.pack()
        for it in items:
            lb.insert("end", "  𝑎𝑏  " + it)
        lb.selection_set(0)
        top.geometry(f"+{x}+{y}")
        self.completion = (top, lb, items, prefix)
        self.completion_active = True

    def completion_key(self, e):
        top, lb, items, _ = self.completion
        if e.keysym == "Escape":
            self.completion_hide()
            return "break"
        sel = lb.curselection()
        i = (sel[0] if sel else 0)
        if e.keysym == "Down":
            i = min(i + 1, len(items) - 1)
        elif e.keysym == "Up":
            i = max(i - 1, 0)
        if e.keysym in ("Down", "Up"):
            lb.selection_clear(0, "end")
            lb.selection_set(i)
            lb.see(i)
            return "break"
        if e.keysym in ("Return", "Tab"):
            word = items[i]
            t = self.editor.text
            prefix = t.get("insert wordstart", "insert")
            t.delete(f"insert-{len(prefix)}c", "insert")
            t.insert("insert", word)
            self.completion_hide()
            self.editor._after_edit()
            return "break"

    def completion_hide(self):
        if self.completion:
            try:
                self.completion[0].destroy()
            except tk.TclError:
                pass
        self.completion = None
        self.completion_active = False

    # ---------------- help dialogs ----------------
    def show_shortcuts(self):
        top = self._dialog("Keyboard Shortcuts", 480, 420)
        rows = [("Ctrl+N", "New Text File"), ("Ctrl+O", "Open File…"),
                ("Ctrl+S", "Save"), ("Ctrl+P", "Quick Open"),
                ("Ctrl+Shift+P", "Command Palette"),
                ("Ctrl+G", "Go to Line…"), ("Ctrl+F / Ctrl+H", "Find / Replace"),
                ("Ctrl+B", "Toggle Side Bar"), ("Ctrl+`", "Toggle Terminal"),
                ("F5", "Run File (any language)"), ("Ctrl+Space", "Trigger Suggestion"),
                ("Ctrl+= / Ctrl+- / Ctrl+0", "Zoom In / Out / Reset (75%)"),
                ("Alt+↑ / Alt+↓", "Move Line"), ("Shift+Alt+↓", "Copy Line Down"),
                ("Ctrl+Shift+T", "Cycle Theme (grey/black/white)"),
                ("Ctrl+W", "Close Editor")]
        for k, v in rows:
            r = tk.Frame(top, bg=C["sidebar"])
            r.pack(fill="x", padx=18, pady=2)
            tk.Label(r, text=k, bg=C["input"], fg=C["fg"], width=22,
                     anchor="w", padx=6, font=self.f_ui).pack(side="left")
            tk.Label(r, text=v, bg=C["sidebar"], fg=C["fg"],
                     font=self.f_ui).pack(side="left", padx=10)

    def show_about(self):
        top = self._dialog("About", 420, 260)
        logo = tk.Canvas(top, width=64, height=64, bg=C["sidebar"],
                         highlightthickness=0)
        logo.pack(pady=(22, 6))
        logo.scale("all", 0, 0, 1, 1)
        draw_icon(logo, "logo")
        logo.scale("icon", 32, 32, 3.2, 3.2)
        tk.Label(top, text=APP_NAME, bg=C["sidebar"],
                 fg=C["fg_bright"],
                 font=(self.f_ui[0], 14, "bold")).pack()
        tk.Label(top, text="A lightweight Python/Tkinter code editor,\n"
                           "built to be driven by an AI agent.",
                 bg=C["sidebar"], fg=C["fg_dim"], font=self.f_ui,
                 justify="center").pack(pady=6)
        self.flat_button(top, "OK", top.destroy).pack(pady=10)

    def tooltip(self, widget, text):
        """Small hover label; keeps icon-only buttons discoverable."""
        state = {"win": None, "job": None}

        def show():
            state["job"] = None
            if state["win"] or not widget.winfo_exists():
                return
            tw = tk.Toplevel(self)
            tw.wm_overrideredirect(True)
            tk.Label(tw, text=text, bg=C["panel"], fg=C["fg"],
                     font=self.f_ui, bd=1, relief="solid",
                     padx=6, pady=3).pack()
            x = widget.winfo_rootx() + widget.winfo_width() // 2 - 60
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tw.wm_geometry(f"+{max(0, x)}+{y}")
            state["win"] = tw

        def enter(_e):
            state["job"] = widget.after(450, show)

        def leave(_e):
            if state["job"]:
                try:
                    widget.after_cancel(state["job"])
                except Exception:  # noqa: BLE001
                    pass
                state["job"] = None
            if state["win"]:
                try:
                    state["win"].destroy()
                except Exception:  # noqa: BLE001
                    pass
                state["win"] = None

        widget.bind("<Enter>", enter, add="+")
        widget.bind("<Leave>", leave, add="+")
        widget.bind("<Button-1>", leave, add="+")

    def _dialog(self, title, w, h, frameless=True):
        """Modal window that reliably takes keyboard focus.

        The main window is overrideredirect, and on Windows a decorated
        transient child of such a parent can be stacked behind it and never
        receive focus - so the dialog is drawn frameless, positioned over
        the app, raised, and only grabs input once it is actually mapped.
        """
        top = tk.Toplevel(self)
        top.withdraw()
        top.title(title)
        top.configure(bg=C["border"])
        if frameless:
            top.overrideredirect(True)
        top.transient(self)
        # centre on the app, clamped to the screen
        px, py = self.winfo_rootx(), self.winfo_rooty()
        pw, ph = self.winfo_width(), self.winfo_height()
        x = px + max(0, (pw - w) // 2)
        y = py + max(40, (ph - h) // 3)
        x = max(0, min(x, self.winfo_screenwidth() - w))
        y = max(0, min(y, self.winfo_screenheight() - h))
        top.geometry(f"{w}x{h}+{x}+{y}")

        shell = tk.Frame(top, bg=C["sidebar"])
        shell.pack(fill="both", expand=True, padx=1, pady=1)
        if frameless:
            bar = tk.Frame(shell, bg=C["tabbar"], height=30)
            bar.pack(fill="x")
            bar.pack_propagate(False)
            tk.Label(bar, text=title, bg=C["tabbar"], fg=C["fg"],
                     font=self.f_ui).pack(side="left", padx=12)
            x_btn = tk.Label(bar, text="\u2715", bg=C["tabbar"],
                             fg=C["fg_dim"], font=self.f_ui, padx=10,
                             cursor="hand2")
            x_btn.pack(side="right")
            x_btn.bind("<Button-1>", lambda e: top.destroy())
            # let the user drag it
            drag = {}

            def press(e):
                drag["x"], drag["y"] = e.x_root, e.y_root
                drag["gx"], drag["gy"] = top.winfo_x(), top.winfo_y()

            def move(e):
                if drag:
                    top.geometry(
                        f"+{drag['gx'] + e.x_root - drag['x']}"
                        f"+{drag['gy'] + e.y_root - drag['y']}")
            bar.bind("<Button-1>", press)
            bar.bind("<B1-Motion>", move)
        top.body = tk.Frame(shell, bg=C["sidebar"])
        top.body.pack(fill="both", expand=True)

        def activate():
            try:
                top.deiconify()
                top.lift()
                top.attributes("-topmost", True)
                top.update_idletasks()
                top.grab_set()
                top.focus_force()
                first = getattr(top, "focus_widget", None)
                if first is not None and first.winfo_exists():
                    first.focus_force()
                    first.focus_set()
            except tk.TclError:
                pass
        top.activate = activate
        top.bind("<Escape>", lambda e: top.destroy())
        return top

    # ---------------- demo content for screenshots ----------------
    def _plant_demo(self):
        base = os.path.expanduser("~/demo_workspace")
        os.makedirs(os.path.join(base, "src"), exist_ok=True)
        mainpy = os.path.join(base, "src", "main.py")
        if not os.path.exists(mainpy):
            with open(mainpy, "w", encoding="utf-8") as fh:
                fh.write(DEMO_MAIN)
            with open(os.path.join(base, "src", "utils.py"), "w") as fh:
                fh.write(DEMO_UTILS)
            with open(os.path.join(base, "README.md"), "w") as fh:
                fh.write("# demo_workspace\n\nA sample project.\n")
        self.set_root(base)
        self.open_file(mainpy)


DEMO_MAIN = '''#!/usr/bin/env python3
"""Demo module — shows off the syntax highlighter."""

import math
from dataclasses import dataclass

PI_DIGITS = 3.14159


@dataclass
class Vector:
    """A tiny 2-D vector."""
    x: float = 0.0
    y: float = 0.0

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def scale(self, factor: int) -> "Vector":
        # returns a new scaled vector
        return Vector(self.x * factor, self.y * factor)


def main() -> None:
    v = Vector(3, 4)
    w = v.scale(2)
    print(f"|v| = {v.length()}")        # 5.0
    print(f"pi ~ {PI_DIGITS:.4f}")
    items = [i * i for i in range(10) if i % 2 == 0]
    total = sum(items)
    assert total > 0, "math still works"
    return None


if __name__ == "__main__":
    main()
'''

DEMO_UTILS = '''"""Helpers for the demo project."""


def greet(name: str) -> str:
    return f"Hello, {name}!"
'''


def main():
    """Standalone entry point (`python -m ide.ide` / `python ide.py`) for
    developing or testing this IDE on its own, outside of Friday entirely.
    Friday itself never runs this function -- agent_tools.py constructs
    IDEApp directly, in-process, passing its own agent_host. The
    FRIDAY_AGENT_MODE env var here is purely a manual dev toggle to preview
    the agent-controlled chrome (inert window-control placeholder, chat
    panel, status glow, open/close pop animation) without actually
    going through Friday."""
    start = sys.argv[1] if len(sys.argv) > 1 else None
    agent_controlled = os.environ.get("FRIDAY_AGENT_MODE") == "1"
    app = IDEApp(start, agent_controlled=agent_controlled)
    app.mainloop()


if __name__ == "__main__":
    main()
