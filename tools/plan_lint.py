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

Usage:
    py -3 tools/plan_lint.py <slug>-plan.md [...]

Prints `<plan>: criterion <k>: <rule>: <excerpt>` per finding.
Exit code: 0 clean, 1 a finding, 2 no file or no `## Acceptance criteria`.
"""

from __future__ import annotations

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


def lint(path: Path) -> tuple:
    items = criteria(path.read_text(encoding="utf-8", errors="replace"))
    if items is None:
        return None, []
    out = []
    for k, item in enumerate(items, 1):
        for rule, excerpt in lint_criterion(item):
            out.append((k, rule, excerpt if len(excerpt) <= 160 else excerpt[:157] + "..."))
    return len(items), out


def main(argv=None) -> int:
    paths = [Path(p) for p in (sys.argv[1:] if argv is None else argv)]
    if not paths:
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
        for k, rule, excerpt in findings:
            print(f"{path}: criterion {k}: {rule}: {excerpt}")
        print(f"{path}: {n} criteria, {len(findings)} finding(s)")
        if findings:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
