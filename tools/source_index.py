#!/usr/bin/env python3
"""source_index.py -- go to the range, don't grep around.

Generic, stdlib-only, read-only index for a single large C/C++ source file.
Built against the banner style used in ForgePact/plugin/ModuleMain.cpp:

    // ===== Section title ==============================================
    // --- Sub-section title ----------------------------------------------

and research-only spans guarded by a build macro:

    #ifndef FORGEPACT_RELEASE
    ...
    #endif

The point is to answer "where is X" and "what's near line N" with one call
that prints only identifiers and banner titles, so the *next* call can be a
`Read` with `offset`/`limit` instead of a chain of exploratory greps.

Usage:
    py -3 tools/source_index.py <file> [--regions] [--functions]
                                        [--find NAME] [--at LINE]
                                        [--guard MACRO] [--json]

Modes (pick at most one; default is --regions):
    --regions   One line per banner-delimited region:
                    start-end  KB  [R]  title
                [R] marks a region that lies inside an `#ifndef <guard>`
                span (or the `#else` branch of an `#ifdef <guard>` span),
                for any nesting depth. `--guard` overrides the macro name
                (default: FORGEPACT_RELEASE).
    --functions File-scope (brace-depth-0) function definitions, one line
                per function: start-end  name
    --find NAME Every region title and function name containing NAME
                (case-insensitive substring), with ranges.
    --at LINE   The region and the function that contain LINE, if any.

What --functions misses (brace-matching heuristic, not a parser):
    - Templates (`template<typename T> ...`) and anything else where the
      return-type/qualifier tokens contain characters outside
      `[A-Za-z0-9_:\\s*&]` (so `<...>`, default-argument expressions, etc.
      break the signature match).
    - A function whose entire body sits on the signature line
      (`void Foo() { return; }`) -- only the signature-then-brace-on-its-
      own-content form is recognised.
    - Anything not at file scope: a method defined inside a class/struct
      body, or a function nested inside a namespace block, sits at brace
      depth >= 1 and is skipped (a `Class::Method(...)` defined *outside*
      any brace, the common style in ModuleMain.cpp, is still found).
    - Function pointers, lambdas, and macro-expanded function definitions.
    - Comments and string/char literals are stripped before scanning, but
      the stripper is line-oriented and does not special-case raw strings
      or line-continuation (`\\`-newline) inside a literal.

Symbol index (`index_code`, no command-line mode of its own): what
`.claude/skills/workorder/section.py` uses to print one function, class or
method of a code file by name. It covers `.cpp .cc .c .hpp .h` (the comment
stripper and guard logic above, plus a scope walk that descends into
`namespace` and `extern "C"` blocks and class bodies, which `--functions`
does not), `.py` (`ast`, decorators included in the span) and `.js .mjs .ts`
(a lexer that blanks strings, template literals with nested `${}`, comments
and regex literals before brackets are counted). Measured 2026-10-03:
`--functions` found 0 of `hs-game-sdk`'s `player.hpp` functions, all inside
`namespace HeroSiege::Player`. It is still a heuristic, not a parser: a C++
signature it cannot read (a macro-built definition, a lambda) is skipped, and
a JS definition ends where the bracket depth returns to its own and the next
line at its indentation or less begins.
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

DEFAULT_GUARD = "FORGEPACT_RELEASE"

# A banner comment line: two or more '=' or '-' characters, a title with at
# least one alphanumeric character, then optionally more '='/'-' characters.
# A pure separator line (all '='/'-' and whitespace, no title) is not a
# region boundary by itself.
_BANNER_RE = re.compile(r'^//\s*[=\-]{2,}\s*(?P<title>.*?)\s*[=\-]*\s*$')

_IFNDEF_RE = re.compile(r'^\s*#\s*ifndef\s+(\w+)')
_IFDEF_RE = re.compile(r'^\s*#\s*ifdef\s+(\w+)')
_IF_RE = re.compile(r'^\s*#\s*if\b')
_ELSE_RE = re.compile(r'^\s*#\s*else\b')
_ELIF_RE = re.compile(r'^\s*#\s*elif\b')
_ENDIF_RE = re.compile(r'^\s*#\s*endif\b')

# Signature-before-a-brace, at brace depth 0: one or more
# "identifier(::identifier)* + qualifier-whitespace" tokens (return type,
# storage class, `ForgePact::` qualifiers, `*`/`&`), then the function name
# (itself possibly `::`-qualified), then a parenthesised parameter list,
# then only trailing keywords (`const`, `noexcept`, `override`) to end of
# line.
_FUNC_SIG_RE = re.compile(
    r'^(?:[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*[\s\*&]+)+'
    r'(?P<name>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)'
    r'\s*\((?P<params>[^()]*)\)'
    r'\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?$'
)

_NOT_FUNCTIONS = {
    "if", "for", "while", "switch", "catch", "return", "sizeof", "defined",
    "static_assert", "else", "do", "namespace", "struct", "class", "union",
    "enum", "typedef", "using",
}


def read_lines(path):
    """Read a source file as a list of lines (no line-ending characters),
    tolerating encoding errors (game/tooling source is not always strict
    UTF-8)."""
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        text = f.read()
    return text.splitlines()


def strip_comments_and_literals(lines):
    """Return a same-shaped list of lines with `//`/`/* */` comment text and
    string/char literal contents blanked to spaces (length preserved), so
    brace-depth scanning does not trip on a brace inside a comment or a
    literal such as `"{"`. A block comment may span lines; banner comment
    lines end up blank, which is intentional -- they are found separately
    by `find_banners` against the *original* lines."""
    out = []
    in_block_comment = False
    for line in lines:
        result = []
        i = 0
        n = len(line)
        in_string = False
        in_char = False
        while i < n:
            c = line[i]
            if in_block_comment:
                if c == "*" and i + 1 < n and line[i + 1] == "/":
                    result.append("  ")
                    i += 2
                    in_block_comment = False
                    continue
                result.append(" ")
                i += 1
                continue
            if in_string:
                if c == "\\" and i + 1 < n:
                    result.append("  ")
                    i += 2
                    continue
                if c == '"':
                    in_string = False
                result.append(" ")
                i += 1
                continue
            if in_char:
                if c == "\\" and i + 1 < n:
                    result.append("  ")
                    i += 2
                    continue
                if c == "'":
                    in_char = False
                result.append(" ")
                i += 1
                continue
            if c == "/" and i + 1 < n and line[i + 1] == "/":
                result.append(" " * (n - i))
                i = n
                break
            if c == "/" and i + 1 < n and line[i + 1] == "*":
                result.append("  ")
                i += 2
                in_block_comment = True
                continue
            if c == '"':
                in_string = True
                result.append(" ")
                i += 1
                continue
            if c == "'":
                in_char = True
                result.append(" ")
                i += 1
                continue
            result.append(c)
            i += 1
        out.append("".join(result))
    return out


def compute_guarded_lines(clean_lines, guard):
    """Return the set of 1-based line numbers that lie inside an
    `#ifndef <guard>` span, or the `#else` branch of an `#ifdef <guard>`
    span, at any nesting depth. Unrelated `#if`/`#ifdef`/`#ifndef` blocks
    are tracked only so `#else`/`#endif` matching stays correct for the
    guard's own nesting; they do not themselves toggle guardedness. An
    `#elif` on a guard-related conditional is treated conservatively as
    "not guarded from here on" (this tool does not evaluate expressions)."""
    guarded = set()
    stack = []  # bool per open conditional: is the *current* branch guarded
    kinds = []  # 'ifndef-guard' | 'ifdef-guard' | 'other', parallel to stack
    for lineno, raw in enumerate(clean_lines, start=1):
        m_ifndef = _IFNDEF_RE.match(raw)
        m_ifdef = _IFDEF_RE.match(raw)
        if m_ifndef and m_ifndef.group(1) == guard:
            kinds.append("ifndef-guard")
            stack.append(True)
        elif m_ifdef and m_ifdef.group(1) == guard:
            kinds.append("ifdef-guard")
            stack.append(False)
        elif m_ifdef or m_ifndef or _IF_RE.match(raw):
            kinds.append("other")
            stack.append(False)
        elif _ELSE_RE.match(raw):
            if kinds:
                if kinds[-1] == "ifndef-guard":
                    stack[-1] = False
                elif kinds[-1] == "ifdef-guard":
                    stack[-1] = True
        elif _ELIF_RE.match(raw):
            if kinds and kinds[-1] in ("ifndef-guard", "ifdef-guard"):
                stack[-1] = False
                kinds[-1] = "other"
        elif _ENDIF_RE.match(raw):
            if kinds:
                kinds.pop()
                stack.pop()
        if any(stack):
            guarded.add(lineno)
    return guarded


def find_banners(lines):
    """Return `[(lineno, title), ...]` for banner comment lines, skipping
    pure separator lines that carry no title text."""
    banners = []
    for lineno, raw in enumerate(lines, start=1):
        m = _BANNER_RE.match(raw)
        if not m:
            continue
        title = m.group("title").strip()
        if not title or not re.search(r"[A-Za-z0-9]", title):
            continue
        banners.append((lineno, title))
    return banners


def build_regions(lines, guarded_lines):
    """Split the file into regions at each banner line. A region runs from
    its banner line to the line before the next banner (or EOF). `guarded`
    is true when at least half of the region's lines are guarded lines."""
    banners = find_banners(lines)
    n = len(lines)
    regions = []
    for i, (start, title) in enumerate(banners):
        end = (banners[i + 1][0] - 1) if i + 1 < len(banners) else n
        end = max(end, start)
        size_bytes = sum(len(l) + 1 for l in lines[start - 1:end])
        span_len = end - start + 1
        guarded_count = sum(1 for ln in range(start, end + 1) if ln in guarded_lines)
        regions.append({
            "start": start,
            "end": end,
            "title": title,
            "kb": size_bytes / 1024.0,
            "guarded": guarded_count * 2 >= span_len,
        })
    return regions


def find_functions(clean_lines):
    """Return `[(name, start_line, end_line), ...]` for file-scope (brace
    depth 0) function definitions. See the module docstring for what this
    heuristic misses."""
    functions = []
    depth = 0
    buf = []
    buf_start = None
    open_stack = []  # per open '{': {'is_func', 'name', 'start'}

    for lineno, raw in enumerate(clean_lines, start=1):
        stripped = raw.strip()
        if depth == 0:
            if stripped.startswith("#"):
                buf = []
                buf_start = None
            elif stripped:
                if buf_start is None:
                    buf_start = lineno
                buf.append(stripped)

        for ch in raw:
            if ch == "{":
                if depth == 0:
                    sig = re.sub(r"\s+", " ", " ".join(buf)).strip()
                    sig = sig[:-1].strip() if sig.endswith("{") else sig
                    m = _FUNC_SIG_RE.match(sig)
                    is_func = bool(m) and m.group("name") not in _NOT_FUNCTIONS
                    open_stack.append({
                        "is_func": is_func,
                        "name": m.group("name") if is_func else None,
                        "start": buf_start if buf_start is not None else lineno,
                    })
                    buf = []
                    buf_start = None
                else:
                    open_stack.append({"is_func": False, "name": None, "start": None})
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    frame = open_stack.pop() if open_stack else None
                    if frame and frame["is_func"] and depth == 0:
                        functions.append((frame["name"], frame["start"], lineno))

        if depth == 0 and stripped.endswith(";"):
            buf = []
            buf_start = None

    return functions


# ---------------------------------------------------------------------------
# Symbol index: C/C++, Python and JS/TS definitions, for section.py's code mode.
# A symbol is a dict: name (bare), qual (class-qualified, what the toc shows),
# full (namespaces too), kind, start, end (1-based, inclusive), and toc (False
# for a JS definition nested inside a function: found by lookup, not listed).
# ---------------------------------------------------------------------------

SYMBOL_SUFFIXES = (".cpp", ".cc", ".c", ".hpp", ".h", ".py", ".js", ".mjs", ".ts")
_CPP_SUFFIXES = (".cpp", ".cc", ".c", ".hpp", ".h")
_JS_SUFFIXES = (".js", ".mjs", ".ts")


def _symbol(name, qual, full, kind, start, end=None, toc=True):
    return {"name": name, "qual": qual, "full": full, "kind": kind, "start": start, "end": end, "toc": toc}


def index_code(text, suffix, guard=DEFAULT_GUARD):
    """(lines, symbols, regions) for a code file's text. `symbols` is in file
    order; `regions` is `build_regions`' banner list (guard-marked for C/C++).
    Raises SyntaxError for a Python file `ast` cannot parse, ValueError for a
    suffix outside SYMBOL_SUFFIXES."""
    suffix = suffix.lower()
    # Not splitlines(): that also breaks on form feeds and U+2028, which
    # `ast` and an editor's line numbers do not.
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    guarded = set()
    if suffix in _CPP_SUFFIXES:
        clean = strip_comments_and_literals(lines)
        symbols = _cpp_symbols(clean)
        guarded = compute_guarded_lines(clean, guard)
    elif suffix == ".py":
        symbols = _py_symbols("\n".join(lines))
    elif suffix in _JS_SUFFIXES:
        symbols = _js_symbols(_js_clean("\n".join(lines)).split("\n"))
    else:
        raise ValueError(f"no symbol index for {suffix!r}")
    for s in symbols:
        if s["end"] is None:  # an unbalanced brace: run to the end of the file
            s["end"] = len(lines)
    symbols.sort(key=lambda s: (s["start"], -s["end"]))
    return lines, symbols, build_regions(lines, guarded)


# --- C/C++ ------------------------------------------------------------------

_CPP_STRUCTURE_RE = re.compile(r"[{};]")
_CPP_ACCESS_RE = re.compile(r"^\s*(?:public|private|protected)\s*:(?!:)")
_CPP_NAMESPACE_RE = re.compile(r"^(?:inline\s+)?namespace\b\s*(?P<name>[A-Za-z_]\w*(?:\s*::\s*(?:inline\s+)?[A-Za-z_]\w*)*)?\s*$")
_CPP_LINKAGE_RE = re.compile(r"^extern\s*$")  # `extern "C" {`, its literal blanked
_CPP_CLASS_RE = re.compile(
    r"^(?:typedef\s+)?(?P<kind>struct|class|union|enum(?:\s+(?:class|struct))?)\s+"
    r"(?:(?:alignas\s*\([^()]*\)|__declspec\s*\([^()]*\)|\[\[[^\]]*\]\])\s*)*"
    r"(?P<name>[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*)\s*(?:<[^{}]*>\s*)?"
    r"(?:final\s*)?(?::(?!:)[^{}]*)?$"
)
# What may follow a definition's parameter list: qualifiers, a trailing return
# type, and a constructor's initialiser list, which must be complete -- it
# ends in `)` or `}` -- so the `{` of a brace-initialised member is not taken
# for the body.
_CPP_TRAILING_RE = re.compile(
    r"^\s*(?:(?:const|volatile|noexcept\s*\([^()]*\)|noexcept|override|final|mutable|constexpr|&&|&"
    r"|throw\s*\([^()]*\)|__\w+(?:\s*\([^()]*\))?)\s*)*"
    r"(?:->\s*(?:[^{}=;:]|::)+?\s*)?(?::(?!:).*[)}])?\s*$"
)
_CPP_OPERATOR_RE = re.compile(
    r"\boperator\s*(?:\(\s*\)|\[\s*\]|new\b(?:\s*\[\s*\])?|delete\b(?:\s*\[\s*\])?|[^\s\w(]+|[A-Za-z_][\w\s:*&<>]*?)\s*\("
)
_CPP_NAME_RE = re.compile(
    r"(?P<q>(?:[A-Za-z_]\w*(?:\s*<[^()]*?>)?\s*::\s*)*)(?P<n>~?\s*[A-Za-z_]\w*|operator\b.*)$"
)
_CPP_ATTRIBUTES_RE = re.compile(r"\[\[[^\]]*\]\]|__declspec\s*\([^()]*\)|__attribute__\s*\(\([^()]*\)\)|alignas\s*\([^()]*\)")
_CPP_NOT_IN_HEAD = re.compile(r"[=();{}]|\b(?:return|else|new|delete|throw|case|goto)\b|(?:\.|->)\s*$")


def _strip_template_prefix(s):
    """`s` without leading `template<...>` clauses (nested angle brackets)."""
    while True:
        m = re.match(r"template\s*<", s)
        if not m:
            return s
        depth, i = 1, m.end()
        while i < len(s) and depth:
            depth += {"<": 1, ">": -1}.get(s[i], 0)
            i += 1
        if depth:
            return s
        s = s[i:].lstrip()


def _cpp_function(s):
    """(qualifier list, bare name) when `s` -- a signature up to its body's
    `{` -- reads as a function definition, else None."""
    m = _CPP_OPERATOR_RE.search(s) if "operator" in s else None
    if m:
        p = m.end() - 1
    else:
        p, angle = -1, 0
        for i, ch in enumerate(s):
            if ch == "<":
                angle += 1
            elif ch == ">" and angle:
                angle -= 1
            elif ch == "(" and not angle:
                p = i
                break
        if p < 0:
            return None
    prefix = s[:p].rstrip()
    m = _CPP_NAME_RE.search(prefix)
    if not m:
        return None
    if _CPP_NOT_IN_HEAD.search(prefix[:m.start()]):
        return None
    depth, q = 0, None
    for i in range(p, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if not depth:
                q = i
                break
    if q is None or not _CPP_TRAILING_RE.match(s[q + 1:]):
        return None
    name = re.sub(r"\s+", "", m.group("n")) if not m.group("n").startswith("operator") else m.group("n").strip()
    if name in _NOT_FUNCTIONS:
        return None
    quals = re.sub(r"<[^<>]*>", "", re.sub(r"\s+", "", m.group("q"))).strip(":")
    return [p for p in quals.split("::") if p], name


def _cpp_classify(buf):
    """The frame for a `{` met at namespace, class or file scope, from the
    text since the last `;`, `{` or `}` there. The signature is tried from
    each buffered line onward, earliest first, so a macro line with no `;`
    above a definition does not hide it."""
    pieces = buf[-24:]
    for k in range(len(pieces)):
        sig = re.sub(r"\s+", " ", " ".join(t for _, t in pieces[k:])).strip()
        s = _strip_template_prefix(_CPP_ATTRIBUTES_RE.sub(" ", sig).strip())
        start = pieces[k][0]
        m = _CPP_NAMESPACE_RE.match(s)
        if m:
            names = re.sub(r"\binline\b|\s+", "", m.group("name") or "")
            return {"kind": "namespace", "parts": [p for p in names.split("::") if p], "start": start}
        if _CPP_LINKAGE_RE.match(s):
            return {"kind": "namespace", "parts": [], "start": start}
        m = _CPP_CLASS_RE.match(s)
        if m:
            kind = "enum" if m.group("kind").startswith("enum") else m.group("kind")
            return {"kind": kind, "parts": re.sub(r"\s+", "", m.group("name")).split("::"), "start": start}
        f = _cpp_function(s)
        if f:
            return {"kind": "function", "parts": f[0] + [f[1]], "start": start}
    return {"kind": "other", "start": pieces[0][0] if pieces else None}


def _cpp_symbols(clean):
    """Definitions in comment- and literal-stripped C/C++ lines: functions at
    file or namespace scope (any depth), out-of-line `Class::Method`s, and
    struct/class/union/enum definitions with the methods defined in their
    bodies. `#` lines (and their `\\` continuations) are skipped."""
    symbols = []
    stack = []  # one frame per open '{'; None for a brace inside a body
    buf = []    # [line, text] pieces at the current scope since its last ; { }
    in_pp = False

    def at_scope():
        return not stack or (stack[-1] is not None and stack[-1]["kind"] in ("namespace", "class", "struct", "union"))

    def add(lineno, text):
        if not buf:
            text = _CPP_ACCESS_RE.sub("", text)
        if not text.strip():
            return
        if buf and buf[-1][0] == lineno:
            buf[-1][1] += text
        else:
            buf.append([lineno, text])

    for lineno, raw in enumerate(clean, start=1):
        if in_pp or raw.lstrip().startswith("#"):
            in_pp = raw.rstrip().endswith("\\")
            if at_scope():
                buf = []
            continue
        pos = 0
        for m in _CPP_STRUCTURE_RE.finditer(raw):
            ch, i = m.group(), m.start()
            if at_scope():
                add(lineno, raw[pos:i])
            pos = i + 1
            if ch == ";":
                if at_scope():
                    buf = []
            elif ch == "{":
                if not at_scope():
                    stack.append(None)
                    continue
                frame = _cpp_classify(buf)
                if frame["kind"] == "other":
                    # An initialiser, a brace-initialised member, a default
                    # argument: the statement goes on after it closes.
                    stack.append(frame)
                    continue
                buf = []
                classes = [f["parts"] for f in stack if f and f["kind"] in ("class", "struct", "union")]
                namespaces = [f["parts"] for f in stack if f and f["kind"] == "namespace"]
                chain = [p for parts in classes for p in parts]
                ns = [p for parts in namespaces for p in parts]
                parts = frame["parts"]
                if frame["kind"] == "namespace":
                    stack.append(frame)
                    continue
                if frame["kind"] == "function":
                    kind = "method" if classes and stack[-1]["kind"] != "namespace" else "function"
                else:
                    kind = frame["kind"]
                qual = "::".join(chain + parts)
                sym = _symbol(parts[-1], qual, "::".join(ns + chain + parts), kind, frame["start"] or lineno)
                symbols.append(sym)
                frame["sym"] = sym
                if frame["kind"] == "enum":
                    frame["kind"] = "enum-body"  # not a scope: nothing inside is a definition
                stack.append(frame)
            else:  # "}"
                if not stack:
                    continue
                frame = stack.pop()
                if frame and frame.get("sym"):
                    frame["sym"]["end"] = lineno
                if at_scope():
                    if frame and frame["kind"] == "other":
                        add(lineno, "{}")
                    else:
                        buf = []
        if at_scope():
            add(lineno, raw[pos:])
    return symbols


# --- Python -----------------------------------------------------------------

def _py_symbols(source):
    """Top-level `def`, `async def` and `class`, and the definitions one level
    down in a class body (`Class.method`). A span starts at its first
    decorator and ends at `ast`'s `end_lineno`."""
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    def make(node, qual):
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        kind = {ast.ClassDef: "class", ast.AsyncFunctionDef: "async def"}.get(type(node), "def")
        return _symbol(node.name, qual, qual, kind, start, node.end_lineno)

    symbols = []
    for node in ast.parse(source).body:
        if isinstance(node, defs):
            symbols.append(make(node, node.name))
            if isinstance(node, ast.ClassDef):
                symbols.extend(make(child, f"{node.name}.{child.name}") for child in node.body
                               if isinstance(child, defs))
    return symbols


# --- JS / TS ----------------------------------------------------------------

# After one of these (or at the start), a `/` opens a regex literal; after an
# operand -- a name, a number, `)` or `]` -- it divides.
_JS_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^}")
_JS_REGEX_KEYWORDS = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw",
                      "case", "do", "else", "yield", "await"}


def _js_blank(s):
    return re.sub(r"[^\n]", " ", s)


def _js_regex_end(text, i):
    """The index just past a regex literal starting at `text[i] == '/'`
    (flags included), or None when the line ends first: then it was a
    division."""
    j, n, in_class = i + 1, len(text), False
    while j < n:
        ch = text[j]
        if ch == "\n":
            return None
        if ch == "\\":
            j += 2
            continue
        if in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
        elif ch == "/":
            j += 1
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            return j
        j += 1
    return None


def _js_clean(text):
    """`text` with comments, strings, regex literals and whole template
    literals (their `${}` expressions included) blanked to spaces, newlines
    kept, so brackets can be counted and lines keep their numbers."""
    out = []
    i, n = 0, len(text)
    stack = []   # "T" for an open template, [depth] for an open ${ } in one
    last = ""    # the last code token: a word or one punctuation character
    while i < n:
        c = text[i]
        if stack and stack[-1] == "T":
            if c == "\\":
                out.append(_js_blank(text[i:i + 2]))
                i += 2
            elif c == "`":
                stack.pop()
                out.append(" ")
                i, last = i + 1, ")"
            elif c == "$" and text.startswith("{", i + 1):
                stack.append([0])
                out.append("  ")
                i, last = i + 2, "{"
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1
            continue
        hide = bool(stack)  # code inside a template's ${}: still the template's text
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(_js_blank(text[i:j]))
            i = j
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n) if j < n and text[j] == c else min(j, n)
            out.append(_js_blank(text[i:j]))
            i, last = j, ")"
            continue
        if c == "`":
            stack.append("T")
            out.append(" ")
            i += 1
            continue
        if c == "/" and (last == "" or last in _JS_REGEX_AFTER or last in _JS_REGEX_KEYWORDS):
            j = _js_regex_end(text, i)
            if j is not None:
                out.append(_js_blank(text[i:j]))
                i, last = j, ")"
                continue
        if stack and c == "{":
            stack[-1][0] += 1
        elif stack and c == "}":
            if stack[-1][0] == 0:
                stack.pop()  # the ${ } closes: back into the template
                out.append(" ")
                i += 1
                continue
            stack[-1][0] -= 1
        if c.isalnum() or c in "_$":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            word = text[i:j]
            out.append(" " * len(word) if hide else word)
            i, last = j, word
            continue
        if not c.isspace():
            last = c
        out.append((" " if c != "\n" else c) if hide else c)
        i += 1
    return "".join(out)


_JS_NAME = r"[A-Za-z_$][\w$]*"
_JS_TOP = [
    (re.compile(rf"^(?:export\s+)?(?:default\s+)?(?P<async>async\s+)?function\b\s*\*?\s*(?P<name>{_JS_NAME})"), "function"),
    (re.compile(rf"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(?P<name>{_JS_NAME})"), "class"),
    (re.compile(rf"^(?:export\s+)?(?:declare\s+)?interface\s+(?P<name>{_JS_NAME})"), "interface"),
    (re.compile(rf"^(?:export\s+)?(?:declare\s+)?(?:const\s+)?enum\s+(?P<name>{_JS_NAME})"), "enum"),
    (re.compile(rf"^(?:export\s+)?(?:declare\s+)?type\s+(?P<name>{_JS_NAME})\s*(?:<[^=]*>)?\s*="), "type"),
    (re.compile(rf"^(?:export\s+)?(?:declare\s+)?(?P<decl>const|let|var)\s+(?P<name>{_JS_NAME})\s*(?::[^=]*)?=(?!=)"), "decl"),
]
_JS_FUNCTION_VALUE = rf"=\s*(?:async\b\s*)?(?:function\b|\([^()]*\)\s*(?::[^=]*)?=>|\($|{_JS_NAME}\s*=>)"
_JS_NESTED = [
    (re.compile(rf"^(?P<async>async\s+)?function\b\s*\*?\s*(?P<name>{_JS_NAME})"), "function"),
    (re.compile(rf"^class\s+(?P<name>{_JS_NAME})"), "class"),
    (re.compile(rf"^(?P<decl>const|let|var)\s+(?P<name>{_JS_NAME})\s*(?::[^=]*)?{_JS_FUNCTION_VALUE}"), "decl"),
]
_JS_MODIFIERS = r"(?:(?:public|private|protected|static|readonly|abstract|override|declare|async)\s+)*"
_JS_MEMBER = [
    re.compile(rf"^{_JS_MODIFIERS}(?:(?:get|set)\s+(?=[#\w$]))?\*?\s*(?P<name>#?{_JS_NAME})\s*(?:<[^()]*>)?\s*\("),
    re.compile(rf"^{_JS_MODIFIERS}(?P<name>#?{_JS_NAME})\s*(?::[^=]*)?{_JS_FUNCTION_VALUE}"),
]
_JS_NOT_MEMBERS = {"if", "for", "while", "switch", "catch", "return", "super", "function", "new", "typeof", "await"}


def _js_match(patterns, stripped):
    for rx, kind in patterns:
        m = rx.match(stripped)
        if m:
            if kind == "function" and m.group("async"):
                kind = "async function"
            elif kind == "decl":
                kind = m.group("decl")
            return m.group("name"), kind
    return None


def _js_symbols(clean):
    """Definitions in `_js_clean`ed lines: top-level functions, classes,
    interfaces, enums, types and `const|let|var` bindings, class methods
    (`Class.method`), and -- lookup only -- named functions nested in a
    function body. A definition ends at the last line before the first one
    where the bracket depth is back to its own and the indentation is its own
    or less (a line opening with `.` continues a chain)."""
    n = len(clean)
    depth_at = [0] * (n + 2)
    indent_at = [0] * (n + 2)
    found = []    # (line, name, qual, kind, toc)
    stack = []    # per open '{': {"cls": name or None, "paren": int, "toc": bool}
    paren = 0     # open ( and [, file-wide
    pending = None
    for lineno, line in enumerate(clean, start=1):
        depth_at[lineno] = len(stack) + paren
        stripped = line.strip()
        indent_at[lineno] = len(line) - len(line.lstrip())
        if stripped:
            hit, toc, owner = None, True, None
            if not stack and not paren:
                hit = _js_match(_JS_TOP, stripped)
            elif stack and stack[-1]["cls"] and paren == stack[-1]["paren"]:
                owner, toc = stack[-1]["cls"], stack[-1]["toc"]
                for rx in _JS_MEMBER:
                    m = rx.match(stripped)
                    if m and m.group("name") not in _JS_NOT_MEMBERS:
                        hit = (m.group("name"), "method")
                        break
            elif stack:
                hit, toc = _js_match(_JS_NESTED, stripped), False
            if hit:
                name, kind = hit
                found.append((lineno, name, f"{owner}.{name}" if owner else name, kind, toc))
                if kind == "class":
                    pending = (name, paren, toc)
        for m in re.finditer(r"[()\[\]{}]", line):
            ch = m.group()
            if ch in "([":
                paren += 1
            elif ch in ")]":
                paren = max(0, paren - 1)
            elif ch == "{":
                cls = None
                if pending and pending[1] == paren:
                    cls, toc_cls = pending[0], pending[2]
                    pending = None
                stack.append({"cls": cls, "paren": paren, "toc": cls is not None and toc_cls})
            elif stack:
                stack.pop()

    symbols = []
    for start, name, qual, kind, toc in found:
        own_depth, own_indent, end, first = depth_at[start], indent_at[start], start, True
        for j in range(start + 1, n + 1):
            stripped = clean[j - 1].strip()
            if not stripped:
                continue
            if (depth_at[j] <= own_depth and indent_at[j] <= own_indent and stripped[0] != "."
                    and not (first and stripped[0] == "{")):
                break
            first, end = False, j
        symbols.append(_symbol(name, qual, qual, kind, start, end, toc))
    return symbols


def _region_at(regions, line):
    for r in regions:
        if r["start"] <= line <= r["end"]:
            return r
    return None


def _function_at(functions, line):
    for name, start, end in functions:
        if start <= line <= end:
            return {"name": name, "start": start, "end": end}
    return None


def _matches(name, needle):
    return needle.lower() in name.lower()


def do_find(regions, functions, needle):
    region_hits = [r for r in regions if _matches(r["title"], needle)]
    func_hits = [
        {"name": n, "start": s, "end": e}
        for (n, s, e) in functions
        if _matches(n, needle)
    ]
    return region_hits, func_hits


def _fmt_region_line(r):
    flag = "[R]" if r["guarded"] else "   "
    return f"{r['start']}-{r['end']}  {r['kb']:.1f}KB  {flag}  {r['title']}"


def _fmt_func_line(name, start, end):
    return f"{start}-{end}  {name}"


def emit_regions(regions, as_json):
    if as_json:
        print(json.dumps({"regions": regions}, indent=2))
        return
    for r in regions:
        print(_fmt_region_line(r))


def emit_functions(functions, as_json):
    if as_json:
        payload = [{"name": n, "start": s, "end": e} for (n, s, e) in functions]
        print(json.dumps({"functions": payload}, indent=2))
        return
    for name, start, end in functions:
        print(_fmt_func_line(name, start, end))


def emit_find(region_hits, func_hits, as_json):
    if as_json:
        print(json.dumps({"regions": region_hits, "functions": func_hits}, indent=2))
        return
    for r in region_hits:
        print(f"region  {_fmt_region_line(r)}")
    for f in func_hits:
        print(f"func    {_fmt_func_line(f['name'], f['start'], f['end'])}")


def emit_at(region, function, as_json):
    if as_json:
        print(json.dumps({"region": region, "function": function}, indent=2))
        return
    print(f"region:   {_fmt_region_line(region) if region else '(none)'}")
    if function:
        print(f"function: {_fmt_func_line(function['name'], function['start'], function['end'])}")
    else:
        print("function: (none)")


def build_parser():
    p = argparse.ArgumentParser(
        prog="source_index.py",
        description="Banner/function index for a large C/C++ source file "
                     "-- go to the range, don't grep around.",
    )
    p.add_argument("file", help="source file to index")
    p.add_argument("--regions", action="store_true", help="list banner-delimited regions (default)")
    p.add_argument("--functions", action="store_true", help="list file-scope function definitions")
    p.add_argument("--find", metavar="NAME", help="find regions/functions whose name contains NAME")
    p.add_argument("--at", metavar="LINE", type=int, help="report the region/function containing LINE")
    p.add_argument("--guard", default=DEFAULT_GUARD, metavar="MACRO",
                    help=f"research-only guard macro name (default: {DEFAULT_GUARD})")
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    modes = [args.regions, args.functions, bool(args.find), args.at is not None]
    if sum(1 for m in modes if m) > 1:
        print("error: pass only one of --regions/--functions/--find/--at", file=sys.stderr)
        return 2

    path = Path(args.file)
    if not path.is_file():
        print(f"error: no such file: {args.file}", file=sys.stderr)
        return 2

    lines = read_lines(path)
    clean_lines = strip_comments_and_literals(lines)
    guarded_lines = compute_guarded_lines(clean_lines, args.guard)
    regions = build_regions(lines, guarded_lines)
    functions = find_functions(clean_lines)

    if args.find:
        region_hits, func_hits = do_find(regions, functions, args.find)
        emit_find(region_hits, func_hits, args.json)
    elif args.functions:
        emit_functions(functions, args.json)
    elif args.at is not None:
        region = _region_at(regions, args.at)
        function = _function_at(functions, args.at)
        emit_at(region, function, args.json)
    else:
        emit_regions(regions, args.json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
