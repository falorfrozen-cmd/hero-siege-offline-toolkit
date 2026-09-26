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
word is a note, printed and never dropped. A `fail`, `not-observed` or
`not-run` is a finding, not an error here; `--require-pass` names the
session-validity checks (dll-hash, marker, control) whose failure means
nothing was measured, and any verdict but `pass` fails those.

Usage:
    py -3 tools/live_checks.py <capture> [--expect a,b,c] [--require-pass a,b]

Prints one `<name> <verdict>` line per check, then a summary line.
Exit code: 0 every expected check present once with a verdict (and every
--require-pass check `pass`); 1 otherwise, naming what is missing, renamed,
duplicated, unreadable or not passed; 2 usage error, no file, or no
`## Checks` heading.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERDICTS = ("pass", "fail", "not-observed", "not-run")
CHECKS_HEADING_RE = re.compile(r"^##\s+Checks\s*$")
NEXT_H2_RE = re.compile(r"^##\s")


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


def parse_line(line: str) -> tuple:
    """(name, verdict or None, note) for one check line."""
    body = line[2:]
    name = body.split(" | ", 1)[0].strip().strip("`")
    if "|" not in body:
        return name, None, ""
    tail = body.rsplit("|", 1)[1].strip()
    m = re.match(r"[*_`]*(not[ -]observed|not[ -]run|pass|fail)\b[*_`.,;:]*\s*(.*)$", tail, re.IGNORECASE)
    if not m:
        return name, None, tail
    return name, m.group(1).lower().replace(" ", "-"), m.group(2).strip()


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
    lines = check_lines(path.read_text(encoding="utf-8", errors="replace"))
    if lines is None:
        print(f"live_checks: {path} has no '## Checks' heading", file=sys.stderr)
        return 2

    problems = []
    seen: dict = {}
    for line in lines:
        name, verdict, note = parse_line(line)
        print(f"{name} {verdict or 'UNREADABLE'}" + (f"  {note}" if note else ""))
        if verdict is None:
            problems.append(f"no pass/fail/not-observed/not-run after the last '|': {line}")
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
