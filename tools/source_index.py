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
"""
import argparse
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
