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

A capture may hold more than one `## Checks` list: when a session is run again,
`live-operator` appends the second attempt, with its own `## Checks`, below the
first, because the first attempt's evidence is never edited (R20 again). So
`--block` picks which `## Checks` heading's list is read: a 1-based number, or
`last`. It defaults to `1`, the first block, which is what every call read
before the option existed. A number past the last block is a usage error that
names how many blocks the capture has. Read without `--block`, a capture with
one `## Checks` block or none keeps the old fallback: the first checks table.
Otherwise a block that has no `- ` lines is read from the table under its own
heading, or under a `## Checks summary` between it and the next `## Checks`,
never from a table before it (another attempt's), and a block with neither is a
usage error.
`--block` counts `## Checks` headings only, so asking for a block other than 1
when a `## Checks summary` section follows that block (it could be a later
attempt) is a usage error rather than a guess, and a capture with more than one
checks section read without `--block` says on stderr that it read the first.

Usage:
    py -3 tools/live_checks.py <capture> [--expect a,b,c] [--require-pass a,b]
                               [--block N|last]

Prints one `<name> <verdict>` line per check, then a summary line.
Exit code: 0 every expected check present once with a verdict (and every
--require-pass check `pass`); 1 otherwise, naming what is missing, renamed,
duplicated, unreadable or not passed; 2 usage error, no file, a `--block` past
the capture's last `## Checks` block, a chosen block of several with neither a
list nor a table, or neither a `## Checks` heading nor a checks table under
`## Checks summary`.
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
SUMMARY_HEADING_RE = re.compile(r"^##\s+Checks\s+[Ss]ummary\s*$", re.MULTILINE)
NEXT_H2_RE = re.compile(r"^##\s")
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
SEPARATOR_CELL_RE = re.compile(r"^\s*:?-+:?\s*$")


def _split_names(value: str | None) -> list:
    if not value:
        return []
    return [n.strip().strip("`") for n in value.split(",") if n.strip()]


def check_blocks(text: str) -> list:
    """The `- ` lines under each of the capture's `## Checks` headings, one
    list per heading, in the order they appear."""
    lines = text.splitlines()
    blocks = []
    for i, line in enumerate(lines):
        if CHECKS_HEADING_RE.match(line):
            out = []
            for body in lines[i + 1:]:
                if NEXT_H2_RE.match(body):
                    break
                if body.startswith("- "):
                    out.append(body)
            blocks.append(out)
    return blocks


def check_lines(text: str, block=1) -> list | None:
    """The `- ` lines under the capture's `block`-th `## Checks` heading
    (1-based, or "last"), or None if it has no such heading."""
    blocks = check_blocks(text)
    if not blocks:
        return None
    if block == "last":
        return blocks[-1]
    if not 1 <= block <= len(blocks):
        return None
    return blocks[block - 1]


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


def _section(lines: list, i: int) -> list:
    """The lines under the heading at `i`, up to the next `## ` heading."""
    out = []
    for body in lines[i + 1:]:
        if NEXT_H2_RE.match(body):
            break
        out.append(body)
    return out


def _table_in(section: list) -> list:
    """The data rows of the table in one section (header and `|---|` rows
    skipped)."""
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
    return out


def table_rows(text: str) -> list | None:
    """The data rows of the first checks table under a `## Checks` or
    `## Checks summary` heading (header and `|---|` rows skipped), or None if
    no such heading carries a table."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if TABLE_HEADING_RE.match(line):
            out = _table_in(_section(lines, i))
            if out:
                return out
    return None


def block_table_rows(text: str, block) -> list:
    """The data rows of the table under the capture's `block`-th `## Checks`
    heading itself (1-based, or "last"), or else under a `## Checks summary`
    after it and before the next `## Checks` (the same attempt's table); empty
    if neither has one. A table before the block is another attempt's."""
    lines = text.splitlines()
    heads = [i for i, line in enumerate(lines) if CHECKS_HEADING_RE.match(line)]
    if not heads:
        return []
    k = len(heads) - 1 if block == "last" else block - 1
    end = heads[k + 1] if k + 1 < len(heads) else len(lines)
    rows = _table_in(_section(lines, heads[k]))
    for i in range(heads[k] + 1, end):
        if rows:
            break
        if SUMMARY_HEADING_RE.match(lines[i]):
            rows = _table_in(_section(lines, i))
    return rows


def summary_after(text: str, block) -> bool:
    """Whether a `## Checks summary` heading follows the `block`-th `## Checks`
    heading (1-based, or "last"), where it could be a later attempt that
    `--block` does not count. With no `## Checks` heading, whether there is
    more than one summary. A block past the last is not this question."""
    lines = text.splitlines()
    heads = [i for i, line in enumerate(lines) if CHECKS_HEADING_RE.match(line)]
    sums = [i for i, line in enumerate(lines) if SUMMARY_HEADING_RE.match(line)]
    if not heads:
        return len(sums) > 1
    if block != "last" and block > len(heads):
        return False
    chosen = heads[-1] if block == "last" else heads[block - 1]
    return any(i > chosen for i in sums)


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
    ap.add_argument("--block",
                    help="which '## Checks' block to read: a 1-based number or 'last' (default 1)")
    args = ap.parse_args(argv)

    block = (args.block or "1").strip().lower()
    if block != "last":
        if not (block.isascii() and block.isdigit()) or int(block) < 1:
            print(f"live_checks: --block takes a 1-based number or 'last', not {args.block!r}",
                  file=sys.stderr)
            return 2
        block = int(block)

    path = Path(args.capture)
    if not path.is_file():
        print(f"live_checks: no such file: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    count = len(check_blocks(text))
    summaries = len(SUMMARY_HEADING_RE.findall(text))
    sections = count + summaries
    if (block == "last" or block > 1) and summary_after(text, block):
        print(f"live_checks: {path} has a '## Checks summary' section after the block "
              f"asked for; --block counts only '## Checks' headings and cannot tell whether "
              f"it is a later attempt, so it cannot tell which attempt {block!r} means",
              file=sys.stderr)
        return 2
    if sections > 1 and args.block is None:
        hint = (" (pass --block last for an appended attempt)"
                if count > 1 and not summary_after(text, "last") else "")
        print(f"live_checks: note: {path} has {sections} checks sections; reading the "
              f"first{hint}", file=sys.stderr)
    # With no `## Checks` heading at all, block 1 and `last` keep the table
    # fallback below; asking for any later block is still past the end.
    if block != "last" and block > count and (count or block > 1):
        print(f"live_checks: --block {block} is past the last block: {path} has "
              f"{count} '## Checks' block{'' if count == 1 else 's'}", file=sys.stderr)
        return 2
    lines = check_lines(text, block)
    parse, where = parse_line, "after the last '|'"
    if not lines:
        # The list wins whenever it has a line; the table is only a fallback.
        # With more than one `## Checks` block, the table must sit under the
        # chosen block's own heading: the first table in the capture would be
        # another attempt's verdicts.
        # Only the default read of a capture with at most one `## Checks`
        # keeps the first-table fallback; a chosen block reads its own.
        legacy = count == 0 or (count == 1 and args.block is None)
        rows = table_rows(text) if legacy else block_table_rows(text, block)
        if rows:
            lines, parse, where = rows, parse_row, "in the last cell"
        elif not legacy:
            print(f"live_checks: '## Checks' block {block} of {path} has no checks "
                  f"list and no checks table", file=sys.stderr)
            return 2
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
