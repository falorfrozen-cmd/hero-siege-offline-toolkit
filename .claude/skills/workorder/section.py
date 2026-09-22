#!/usr/bin/env python3
"""Print one section of a workorder file, named by its heading.

    py -3 .claude/skills/workorder/section.py <file> '<heading>' [--log]

`<heading>` is the heading's text, with or without its leading `#`s:
`'Syntax-only compile check'` and `'### Syntax-only compile check'` name the
same section. Without `#`s any level matches; with them the level must match
too. **Single-quote it**: inside double quotes Bash runs a backticked word as
a command and PowerShell eats the backtick, and workorder headings are full of
backticks.

A citation is matched the way planners actually write them, strictest first,
and a looser tier is used only when it names exactly one heading:

1. the heading's text, exactly;
2. the same with backticks ignored on both sides (what survives a shell);
3. a prefix of it -- `ctx: "Code and test sites"` for a heading that goes on
   `(line numbers at b56e626; ...)`.

The section runs from its heading to the next heading of the same or a higher
level, so a `##` section brings its `###` subsections along and a `###`
section stops at its sibling. Headings inside a fenced code block are text,
not structure -- a context file routinely quotes markdown. Fences follow
CommonMark: a fence closes only on the same character, a run at least as long
as the one that opened it, and nothing after it.

`## Log` and everything under it is refused unless `--log` is given, and is
left out of the heading list. The Log is the implementer's reasoning; the
verifier, this tool's main caller, exists to not have seen it. An implementer
or a driver reading a round's entry passes `--log`.

Why this exists: a criterion may cite one `###` subsection of the context
file, and the verifier is meant to open that subsection and nothing else.
`verifier.md` gave a `sed` range for the plan's `## ` sections and nothing for
a cited `###`; measured 2026-09-18, a verifier spent eight calls hunting for
the section and then read the whole context file, Log included. One command
that either prints the section or says why not.

It reads any markdown file, not only workorders -- module guides included:

    py -3 .claude/skills/workorder/section.py <file> --toc
    py -3 .claude/skills/workorder/section.py <file> '<heading>' --grep '<regex>'

`--toc` lists every heading with its line and the KB its section spans, so
the too-big-to-read sections are visible before any is read. `--grep` prints
only the list items and paragraphs of the section that match (case
insensitive), each headed by its file line; an item over 4,000 characters is
printed as a window around each match. Why: agents did read ForgePact's guide
"by section" with small `offset`/`limit` windows and still pulled 68-124KB,
because 23 of its lines hold 128KB (measured 2026-09-22) -- a 20-line window
returned 45.6KB.

Exit codes: 0 printed; 2 usage, or the file cannot be read; 3 no such
heading (the file's headings are listed on stderr); 4 the heading is
ambiguous (each match is listed on stderr -- add its `#`s, or fix the plan);
5 a code fence is never closed, so sections cannot be told apart (the old
behaviour was to print to the end of the file, Log and all, with exit 0);
6 the heading is in the Log and `--log` was not given; 7 `--grep` matched
nothing in the section.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
LOG_HEADING = "Log"


def headings(lines: list) -> tuple:
    """((line index, level, text) for every heading outside a code fence,
    the 1-based line of a fence still open at the end of the file or None)."""
    found = []
    fence = None
    opened_at = None
    for i, line in enumerate(lines):
        m = FENCE.match(line)
        if m and fence is None and m.group(1)[0] == "`" and "`" in m.group(2):
            # CommonMark: a backtick fence's info string holds no backtick, so
            # a line opening with ```cmd``` is inline code in prose, not a fence.
            m = None
        if m:
            run, rest = m.group(1), m.group(2)
            if fence is None:
                fence, opened_at = run, i + 1
            elif run[0] == fence[0] and len(run) >= len(fence) and not rest.strip():
                fence, opened_at = None, None
            continue
        if fence is not None:
            continue
        h = HEADING.match(line)
        if h:
            found.append((i, len(h.group(1)), h.group(2)))
    return found, opened_at


def parse_request(raw: str) -> tuple:
    """(level or None, text) from what the caller typed. A citation is often
    pasted with its section sign or quotes -- `§ "Name"` -- so shed those."""
    text = raw.strip().lstrip("§").strip().strip("\"'").strip()
    m = HEADING.match(text)
    if m:
        return len(m.group(1)), m.group(2)
    return None, text


def in_log(found: list, index: int) -> bool:
    """Is found[index] the `## Log` heading, or a heading beneath it?"""
    for _, level, text in reversed(found[: index + 1]):
        if level <= 2:
            return level == 2 and text == LOG_HEADING
    return False


def match(found: list, level, wanted: str) -> list:
    """Indexes into `found`, from the strictest tier that matches at all."""
    bare = lambda s: s.replace("`", "").strip()
    candidates = [i for i, h in enumerate(found) if level is None or h[1] == level]
    tiers = (
        lambda t: t == wanted,
        lambda t: bare(t) == bare(wanted),
        lambda t: bool(bare(wanted)) and bare(t).startswith(bare(wanted)),
    )
    for tier in tiers:
        hits = [i for i in candidates if tier(found[i][2])]
        if hits:
            return hits
    return []


def extract(text: str, request: str, allow_log: bool = False) -> tuple:
    """(exit code, stdout text, stderr text)."""
    # Not splitlines(): that also breaks on form feeds and U+2028, and this
    # worktree writes CRLF and LF into the same file.
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    found, open_fence = headings(lines)
    if open_fence is not None:
        return 5, "", f"code fence opened at line {open_fence} is never closed; sections cannot be told apart\n"
    visible = [i for i in range(len(found)) if allow_log or not in_log(found, i)]
    level, wanted = parse_request(request)
    hits = match(found, level, wanted)
    if hits and not allow_log and all(in_log(found, i) for i in hits):
        return 6, "", f"{request!r} is in '## Log', the implementer's reasoning; pass --log only if that is yours to read\n"
    hits = [i for i in hits if i in visible]
    if not hits:
        listing = "\n".join(f"  {'#' * found[i][1]} {found[i][2]}" for i in visible)
        return 3, "", f"no heading {request!r}; this file has:\n{listing}\n"
    if len(hits) > 1:
        listing = "\n".join(f"  line {found[i][0] + 1}: {'#' * found[i][1]} {found[i][2]}" for i in hits)
        return 4, "", f"heading {request!r} is ambiguous:\n{listing}\n"
    start, lv, _ = found[hits[0]]
    end = next((i for i, other, _ in found if i > start and other <= lv), len(lines))
    body = lines[start:end]
    if not allow_log:
        # A level-1 section spans the whole file, Log included: cut it out.
        for log_line, log_lv, log_text in found:
            if log_lv == 2 and log_text == LOG_HEADING and start < log_line < end:
                log_end = next((i for i, other, _ in found if i > log_line and other <= 2), len(lines))
                body = lines[start:log_line] + ["(## Log omitted; --log prints it)"] + lines[min(log_end, end):end]
                break
    return 0, "\n".join(body).rstrip("\n") + "\n", ""


def _section_start(text: str, request: str, allow_log: bool) -> int:
    """1-based file line of the heading `extract` printed (it succeeded, so
    exactly one visible heading matches)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    found, _ = headings(lines)
    level, wanted = parse_request(request)
    hits = [i for i in match(found, level, wanted) if allow_log or not in_log(found, i)]
    return found[hits[0]][0] + 1


def toc(text: str, allow_log: bool = False) -> tuple:
    """(exit code, stdout, stderr): every heading with its line and the KB its
    own section spans, so a caller can see which sections are too big to read
    whole before reading any of them."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    found, open_fence = headings(lines)
    if open_fence is not None:
        return 5, "", f"code fence opened at line {open_fence} is never closed; sections cannot be told apart\n"
    out = []
    for k, (start, lv, name) in enumerate(found):
        if not allow_log and in_log(found, k):
            continue
        end = next((i for i, other, _ in found if i > start and other <= lv), len(lines))
        kb = sum(len(l.encode("utf-8")) + 1 for l in lines[start:end]) / 1024.0
        out.append(f"{start + 1:>6}  {kb:7.1f}KB  {'#' * lv} {name}")
    return 0, "\n".join(out) + "\n", ""


ITEM_START = re.compile(r"^ {0,3}(?:[-*+]|\d+[.)])[ \t]|^\S")
# A matching item longer than this is printed as windows around each match:
# ForgePact's guide carries single list items of 3-23KB (measured 2026-09-22:
# 23 lines holding 128KB of a 334KB file), so "read every match" printed
# whole would be the whole-guide read R3 exists to stop.
LONG_ITEM_CHARS = 4000
WINDOW_CHARS = 500


def grep_section(body: str, pattern: str, first_line: int) -> str:
    """The list items / paragraphs of `body` that match `pattern`
    (case-insensitive), each headed by its 1-based file line. An item longer
    than LONG_ITEM_CHARS prints only a window around each match."""
    rx = re.compile(pattern, re.IGNORECASE)
    lines = body.split("\n")
    items, cur = [], None
    for i, line in enumerate(lines):
        if not line.strip():
            cur = None
            continue
        if cur is None or ITEM_START.match(line):
            cur = [i, []]
            items.append(cur)
        cur[1].append(line)
    out = []
    for i, chunk in items:
        text = "\n".join(chunk)
        hits = list(rx.finditer(text))
        if not hits:
            continue
        where = f"-- line {first_line + i}"
        if len(text) <= LONG_ITEM_CHARS:
            out.append(f"{where}\n{text}")
            continue
        spans = []
        for m in hits:
            lo, hi = max(0, m.start() - WINDOW_CHARS), min(len(text), m.end() + WINDOW_CHARS)
            if spans and lo <= spans[-1][1]:
                spans[-1][1] = hi
            else:
                spans.append([lo, hi])
        parts = [("… " if lo else "") + text[lo:hi] + (" …" if hi < len(text) else "") for lo, hi in spans]
        out.append(f"{where} ({len(text):,} chars; {len(hits)} match(es) shown in context -- "
                   f"`Read` offset {first_line + i} limit 1 for the whole item)\n" + "\n[…]\n".join(parts))
    return "\n\n".join(out) + ("\n" if out else "")


def _option(argv: list, name: str) -> tuple:
    """(value or None, argv without `name value`)."""
    if name not in argv:
        return None, argv
    k = argv.index(name)
    if k + 1 >= len(argv):
        return "", argv[:k]
    return argv[k + 1], argv[:k] + argv[k + 2:]


def main(argv: list) -> int:
    allow_log = "--log" in argv
    want_toc = "--toc" in argv
    argv = [a for a in argv if a not in ("--log", "--toc")]
    pattern, argv = _option(argv, "--grep")
    usage = ("usage: section.py <file> '<heading>' [--log] [--grep <regex>]\n"
             "       section.py <file> --toc [--log]\n")
    if pattern == "" or len(argv) != (1 if want_toc else 2):
        sys.stderr.write(usage)
        return 2
    try:
        # utf-8-sig: a BOM would otherwise glue itself to the first heading.
        text = Path(argv[0]).read_bytes().decode("utf-8-sig", errors="replace")
    except OSError as exc:
        sys.stderr.write(f"cannot read {argv[0]}: {exc}\n")
        return 2
    if want_toc:
        code, out, err = toc(text, allow_log)
    else:
        code, out, err = extract(text, argv[1], allow_log)
        if code == 0 and pattern is not None:
            try:
                first = _section_start(text, argv[1], allow_log)
                out = grep_section(out, pattern, first)
            except re.error as exc:
                out, err, code = "", f"bad --grep pattern {pattern!r}: {exc}\n", 2
            else:
                if not out:
                    code, err = 7, f"nothing under {argv[1]!r} matches {pattern!r}\n"
    # Bytes, not text: this console's code page cannot encode the arrows and
    # section signs a workorder is full of, and a print() would raise on them.
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stderr.buffer.write(err.encode("utf-8"))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
