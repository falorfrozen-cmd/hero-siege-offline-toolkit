#!/usr/bin/env python3
"""Read the `## Checks` block of a `/workorder` live capture
(`.claude/workorders/<slug>-live-<n>.md`, written by `live-operator`) and say
whether it carries one verdict for every check the procedure named.

Why this exists: a workorder's session criterion used to be a `grep -c` over
the capture with the verdict anchored at the end of the line
(`| \\(pass\\|fail\\|not-observed\\)$`). The operator wrote
`| not-observed (explanation)` twice, and once renamed checks
(`take-material (dropped)`), so three rounds and one split workorder in
forgepact-issue-14 were spent on the capture's punctuation, not the game,
and each time the implementer "fixed" it by editing the operator's evidence.

A check line is

    - <name> | expected: ... | observed: ... | <verdict> [note]

The name is everything before the first ` | `. The verdict is the first word
after the last `|`: `pass`, `fail`, `not-observed` or `not-run`
(`not observed` and `not run` are read the same way). `not-run` means the
instrument could not run the check, usually with its reason in parentheses:
`not-run (instrument: budget spent before slot 0,6)`. Anything after that
word is a note, printed and never dropped. A leading `crash` (the game ended
during the check: `crash (fail) - ...`) is read as `fail`, and the whole tail,
the word included, is kept as the note; the operator's own form is
`fail (crash - <the ERROR line>)`, verdict word first. A `fail`, `not-observed` or
`not-run` is a finding, not an error here; `--require-pass` names the
session-validity checks (dll-hash, marker, control) whose failure means
nothing was measured, and any verdict but `pass` fails those.

The list is the required form. A markdown table is read only as a fallback,
because in forgepact-issue-36 Live 1 (2026-09-28) the operator wrote one
instead, under `## Checks summary`, and a capture is evidence that nobody but
`live-operator` edits (`tools/workorder_audit.py` R20):

    ## Checks summary

    | Check | Result |
    |---|---|
    | dll-hash | pass — e1c5eb99..., matches dispatch |
    | helmet-rolls3 | not-run (no helmet) |

It is read under a `## Checks summary` heading, or under `## Checks` when that
heading carries no `- ` lines. The name is the first cell, stripped (and
unquoted from backticks, as in the list form); the verdict is the first word
of the last cell, by exactly the list form's rules, the rest of that cell its
note. The header row (the one above the `|---|` separator) and the separator
are skipped. Missing, duplicated, renamed and unreadable checks, and
`--require-pass`, behave as for the list. A capture that has both a `## Checks`
list and a table is read from the list alone; a table under any other heading
is not read.

Usage:
    py -3 tools/live_checks.py <capture> [--expect a,b,c] [--require-pass a,b]

Prints one `<name> <verdict>` line per check, then a summary line.
Exit code: 0 every expected check present once with a verdict (and every
--require-pass check `pass`); 1 otherwise, naming what is missing, renamed,
duplicated, unreadable or not passed; 2 usage error, no file, or neither a
`## Checks` heading nor a checks table under `## Checks summary`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERDICTS = ("pass", "fail", "not-observed", "not-run")
# A leading `crash` is a `fail`: forgepact-68-move-all Live 1f's operator wrote
# `crash (fail) ...` when a click ended the game, and the capture is never edited.
CRASH_RE = re.compile(r"[*_`]*crash\b(?![-'])", re.IGNORECASE)
CHECKS_HEADING_RE = re.compile(r"^##\s+Checks\s*$")
# The fallback table may sit under `## Checks` or `## Checks summary`.
TABLE_HEADING_RE = re.compile(r"^##\s+Checks(?:\s+[Ss]ummary)?\s*$")
NEXT_H2_RE = re.compile(r"^##\s")
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
SEPARATOR_CELL_RE = re.compile(r"^\s*:?-+:?\s*$")


def _split_names(value: str | None) -> list:
    if not value:
        return []
    return [n.strip().strip("`") for n in value.split(",") if n.strip()]


def check_lines(text: str) -> list | None:
    """The `- ` lines under the capture's `## Checks` heading, or None if it
    has no such heading."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if CHECKS_HEADING_RE.match(line):
            out = []
            for body in lines[i + 1:]:
                if NEXT_H2_RE.match(body):
                    break
                if body.startswith("- "):
                    out.append(body)
            return out
    return None


def _cells(row: str) -> list:
    """The cells of one markdown table row, outer pipes dropped."""
    body = row.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return CELL_SPLIT_RE.split(body)


def _is_separator(row: str) -> bool:
    return all(SEPARATOR_CELL_RE.match(c) for c in _cells(row))


def table_rows(text: str) -> list | None:
    """The data rows of the first checks table under a `## Checks` or
    `## Checks summary` heading (header and `|---|` rows skipped), or None if
    no such heading carries a table."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not TABLE_HEADING_RE.match(line):
            continue
        section = []
        for body in lines[i + 1:]:
            if NEXT_H2_RE.match(body):
                break
            section.append(body)
        out = []
        for j, body in enumerate(section):
            if not body.lstrip().startswith("|"):
                continue
            if _is_separator(body):
                continue
            nxt = section[j + 1] if j + 1 < len(section) else ""
            if nxt.lstrip().startswith("|") and _is_separator(nxt):
                continue  # the header row
            out.append(body)
        if out:
            return out
    return None


def _verdict(tail: str) -> tuple:
    """(verdict or None, note) for the text after a check's last `|`."""
    if CRASH_RE.match(tail):
        return "fail", tail
    m = re.match(r"[*_`]*(not[ -]observed|not[ -]run|pass|fail)\b[*_`.,;:]*\s*(.*)$", tail, re.IGNORECASE)
    if not m:
        return None, tail
    return m.group(1).lower().replace(" ", "-"), m.group(2).strip()


def parse_line(line: str) -> tuple:
    """(name, verdict or None, note) for one check line."""
    body = line[2:]
    name = body.split(" | ", 1)[0].strip().strip("`")
    if "|" not in body:
        return name, None, ""
    return (name,) + _verdict(body.rsplit("|", 1)[1].strip())


def parse_row(row: str) -> tuple:
    """(name, verdict or None, note) for one checks-table row: the name is the
    first cell, the verdict the first word of the last."""
    cells = _cells(row)
    name = cells[0].strip().strip("`")
    if len(cells) < 2:
        return name, None, ""
    return (name,) + _verdict(cells[-1].strip())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("capture", help="the <slug>-live-<n>.md file")
    ap.add_argument("--expect", help="comma-separated check names the procedure lists, verbatim")
    ap.add_argument("--require-pass", help="comma-separated checks that must read pass")
    args = ap.parse_args(argv)

    path = Path(args.capture)
    if not path.is_file():
        print(f"live_checks: no such file: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = check_lines(text)
    parse, where = parse_line, "after the last '|'"
    if not lines:
        # The list wins whenever it has a line; the table is only a fallback.
        rows = table_rows(text)
        if rows:
            lines, parse, where = rows, parse_row, "in the last cell"
    if lines is None:
        print(f"live_checks: {path} has no '## Checks' heading and no checks table "
              f"under '## Checks summary'", file=sys.stderr)
        return 2

    problems = []
    seen: dict = {}
    for line in lines:
        name, verdict, note = parse(line)
        print(f"{name} {verdict or 'UNREADABLE'}" + (f"  {note}" if note else ""))
        if verdict is None:
            problems.append(f"no pass/fail/not-observed/not-run {where}: {line}")
        if name in seen:
            problems.append(f"check listed twice: {name}")
        seen[name] = verdict

    expect = _split_names(args.expect)
    if expect:
        for name in expect:
            if name not in seen:
                problems.append(f"missing check: {name}")
        for name in seen:
            if name not in expect:
                problems.append(f"check the procedure does not name (renamed?): {name}")
    for name in _split_names(args.require_pass):
        if seen.get(name) != "pass":
            why = " (the instrument did not run it)" if seen.get(name) == "not-run" else ""
            problems.append(f"{name} must be pass, read {seen.get(name) or 'nothing'}{why}")

    counts = {v: sum(1 for x in seen.values() if x == v) for v in VERDICTS}
    print(f"checks: {len(lines)} (pass {counts['pass']}, fail {counts['fail']}, "
          f"not-observed {counts['not-observed']}, not-run {counts['not-run']})")
    for p in problems:
        print(f"PROBLEM: {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
