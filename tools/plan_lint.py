#!/usr/bin/env python3
"""Static checks on a `/workorder` plan's `## Acceptance criteria`, for the
defects that have cost a round to discover. It reads the plan and runs
nothing: executing a criterion is the planner's pre-flight and the
verifier's job, never the driver's.

Each rule is a defect measured in forgepact-issue-14 (2026-09-22..24):

  prose            a criterion with no backticked command or path. The
                   verifier cannot run a description (planner.md, "What a
                   usable acceptance criterion looks like").
  unanchored-slice `.index('## Heading')` / `.find("### X")` with no leading
                   `\\n`, so the slice starts at the first *mention* of the
                   heading, not the heading line (phase1c, PLAN-DEFECT 2).
  capture-grep     a `grep` over a `-live-<n>.md` capture that pins a
                   verdict with `pass\\|fail`. The operator's note after the
                   verdict broke three rounds; use `py -3
                   tools/live_checks.py <capture> --expect ...` instead.
  bare-python      a command that starts `python` or `python3`. This
                   repository's commands are `py -3`, and a verifier that
                   ran `python` got a false verdict (phase1j-record r0).

It also checks the lanes a plan declares under `## Steps` (issue #176): a
`### Lane: <name>` heading, then a `files:` line of backticked paths (globs
allowed) that lane alone may edit, and one `### Join` the serial join
implementer carries out after every lane returned. Lanes run concurrently in
one checkout, so their file sets must not meet:

  lane-overlap     two lanes, any pair of them, share a literal path; a
                   literal in one matches a glob in the other; two globs are
                   identical; or one glob's literal prefix is a prefix of the
                   other's (`docs/**` beside `docs/agents/*.md`). A literal
                   ending in `/` is a directory and covers what is under it.
  lane-no-files    a lane with no `files:` line, or an empty one.
  lane-no-join     one or more lanes and no `### Join`.
  lane-dup-name    two lanes with the same name.
  lane-bad-name    a name outside `[a-z0-9-]+`, or `join` (the join
                   implementer's label is `implementer:join:r<n>`).

Usage:
    py -3 tools/plan_lint.py <slug>-plan.md [...]
    py -3 tools/plan_lint.py <slug>-plan.md --lanes-json

Prints `<plan>: criterion <k>: <rule>: <excerpt>` per criterion finding and
`<plan>: lane <name>: <rule>: <excerpt>` per lane finding; both count in the
`finding(s)` line. `--lanes-json` (one plan) then prints, only when the lint
is clean, one JSON line `{"lanes": [{"name": ..., "files": [...]}, ...],
"join": true|false}` -- the lane table the driver passes to the workflow, so
it can never launch lanes a lint rejected.
Exit code: 0 clean, 1 a finding, 2 no file or no `## Acceptance criteria`.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path

CRITERIA_HEADING_RE = re.compile(r"^##\s+Acceptance criteria\s*$")
NEXT_H2_RE = re.compile(r"^##\s")
ITEM_RE = re.compile(r"^\s*-\s+\[[ xX]\]\s*")
BACKTICK_RE = re.compile(r"``(.+?)``|`([^`]+)`")
UNANCHORED_SLICE_RE = re.compile(r"\.(?:r?index|r?find)\(\s*['\"]#{1,6} ")
# `' '.join(t.split())` collapses newlines on purpose, so there is no
# newline to anchor on and the rule does not apply.
COLLAPSED_TEXT_RE = re.compile(r"\.join\(.*\.split\(\)\)")
CAPTURE_GREP_RE = re.compile(r"\bgrep\b[^`]*pass\\?\|")
BARE_PYTHON_RE = re.compile(r"(?:^|[\s;&|(])python3?(?:\.exe)?\s")

STEPS_HEADING_RE = re.compile(r"^##\s+Steps\s*$")
H3_RE = re.compile(r"^###\s")
LANE_HEADING_RE = re.compile(r"^###\s+Lane:\s*(.*?)\s*$")
JOIN_HEADING_RE = re.compile(r"^###\s+Join\b")
FILES_LINE_RE = re.compile(r"^\s*(?:[-*]\s+)?\**files:\**\s*(.*)$")
# A step starts a numbered or bulleted item; the `files:` list ends there.
STEP_START_RE = re.compile(r"^\s*(?:\d+\.|[-*])\s")
LANE_NAME_RE = re.compile(r"[a-z0-9-]+")
GLOB_CHARS = "*?["


def criteria(text: str) -> list | None:
    """Each checkbox item under `## Acceptance criteria`, continuation lines
    joined; None when the plan has no such heading."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not CRITERIA_HEADING_RE.match(line):
            continue
        items: list = []
        for body in lines[i + 1:]:
            if NEXT_H2_RE.match(body):
                break
            if ITEM_RE.match(body):
                items.append(ITEM_RE.sub("", body, count=1))
            elif items and body.strip():
                items[-1] += " " + body.strip()
        return items
    return None


def lint_criterion(text: str) -> list:
    spans = [a or b for a, b in BACKTICK_RE.findall(text)]
    if not spans:
        return [("prose", text)]
    found = []
    for span in spans:
        if UNANCHORED_SLICE_RE.search(span) and not COLLAPSED_TEXT_RE.search(span):
            found.append(("unanchored-slice", span))
        if "-live-" in span and CAPTURE_GREP_RE.search(span):
            found.append(("capture-grep", span))
        if BARE_PYTHON_RE.search(" " + span):
            found.append(("bare-python", span))
    return found


def _lane_files(body: list) -> list | None:
    """The backticked paths on a lane's `files:` line (and any continuation
    lines), read before the lane's first step; None when there is no such
    line."""
    for i, line in enumerate(body):
        m = FILES_LINE_RE.match(line)
        if m:
            text = m.group(1)
            for more in body[i + 1:]:
                if not more.strip() or STEP_START_RE.match(more) or "`" not in more:
                    break
                text += " " + more.strip()
            return [(a or b).strip().replace("\\", "/").removeprefix("./")
                    for a, b in BACKTICK_RE.findall(text) if (a or b).strip()]
        if STEP_START_RE.match(line):
            return None
    return None


def lanes(text: str) -> tuple:
    """(lanes, join): each `### Lane: <name>` under `## Steps` as
    `{"name", "files"}` (`files` None when the lane has no `files:` line), and
    whether `## Steps` holds a `### Join`. A plan with no `### Lane:` heading
    has no lanes; nothing here assumes how many it has."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if STEPS_HEADING_RE.match(line)), None)
    if start is None:
        return [], False
    found, join, current = [], False, None
    for line in lines[start + 1:]:
        if NEXT_H2_RE.match(line):
            break
        if H3_RE.match(line):
            m = LANE_HEADING_RE.match(line)
            current = {"name": m.group(1).strip("`* "), "body": []} if m else None
            if current is not None:
                found.append(current)
            join = join or bool(JOIN_HEADING_RE.match(line))
            continue
        if current is not None:
            current["body"].append(line)
    return [{"name": lane["name"], "files": _lane_files(lane["body"])} for lane in found], join


def _is_glob(path: str) -> bool:
    return any(c in path for c in GLOB_CHARS)


def _literal_prefix(glob: str) -> str:
    cut = min((glob.index(c) for c in GLOB_CHARS if c in glob), default=len(glob))
    return glob[:cut]


def _overlap(a: str, b: str) -> bool:
    """Whether two declared paths can name the same file. Conservative on
    purpose: a planner narrows the globs rather than the check trusting them."""
    if a == b:
        return True
    ga, gb = _is_glob(a), _is_glob(b)
    if ga and gb:
        pa, pb = _literal_prefix(a), _literal_prefix(b)
        return pa.startswith(pb) or pb.startswith(pa)
    if ga or gb:
        glob, literal = (a, b) if ga else (b, a)
        if fnmatch.fnmatchcase(literal, glob):
            return True
        # A directory literal (`docs/`) against a glob beneath it.
        return literal.endswith("/") and _literal_prefix(glob).startswith(literal)
    return (a.endswith("/") and b.startswith(a)) or (b.endswith("/") and a.startswith(b))


def lint_lanes(declared: list, join: bool) -> list:
    """`(lane, rule, excerpt)` per lane finding, overlap checked over every
    pair of lanes, not only adjacent ones."""
    out, seen = [], set()
    for lane in declared:
        name = lane["name"]
        if not LANE_NAME_RE.fullmatch(name) or name == "join":
            out.append((name, "lane-bad-name", f"`### Lane: {name}` (want [a-z0-9-]+, not `join`)"))
        if name in seen:
            out.append((name, "lane-dup-name", f"`### Lane: {name}` is declared twice"))
        seen.add(name)
        if not lane["files"]:
            out.append((name, "lane-no-files", "no `files:` line of backticked paths before the lane's first step"))
    if declared and not join:
        out.append((declared[0]["name"], "lane-no-join",
                    f"{len(declared)} lane(s) and no `### Join` under `## Steps`"))
    for i, one in enumerate(declared):
        for other in declared[i + 1:]:
            for a in one["files"] or []:
                for b in other["files"] or []:
                    if _overlap(a, b):
                        out.append((one["name"], "lane-overlap", f"`{a}` overlaps lane {other['name']} `{b}`"))
    return out


def lint(path: Path) -> tuple:
    text = path.read_text(encoding="utf-8", errors="replace")
    items = criteria(text)
    if items is None:
        return None, []
    out = []
    for k, item in enumerate(items, 1):
        for rule, excerpt in lint_criterion(item):
            out.append((f"criterion {k}", rule, excerpt if len(excerpt) <= 160 else excerpt[:157] + "..."))
    for name, rule, excerpt in lint_lanes(*lanes(text)):
        out.append((f"lane {name}", rule, excerpt))
    return len(items), out


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    want_json = "--lanes-json" in args
    paths = [Path(p) for p in args if p != "--lanes-json"]
    if not paths or (want_json and len(paths) != 1):
        print(__doc__.strip().split("\n\n")[-2], file=sys.stderr)
        return 2
    rc = 0
    for path in paths:
        if not path.is_file():
            print(f"plan_lint: no such file: {path}", file=sys.stderr)
            return 2
        n, findings = lint(path)
        if n is None:
            print(f"plan_lint: {path} has no '## Acceptance criteria' heading", file=sys.stderr)
            return 2
        for where, rule, excerpt in findings:
            print(f"{path}: {where}: {rule}: {excerpt}")
        print(f"{path}: {n} criteria, {len(findings)} finding(s)")
        if findings:
            rc = 1
    if want_json and rc == 0:
        declared, join = lanes(paths[0].read_text(encoding="utf-8", errors="replace"))
        print(json.dumps({"lanes": [{"name": lane["name"], "files": lane["files"]} for lane in declared],
                          "join": join}))
    return rc


if __name__ == "__main__":
    sys.exit(main())
