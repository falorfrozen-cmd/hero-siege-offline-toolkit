#!/usr/bin/env python3
"""Whether a plan change was an amendment or a replan (`/workorder` SKILL.md
Step 2, "Amend, or replan").

A `PLAN-DEFECT` whose evidence names the wrong criterion or step and states
the correction is sent back to the planner as an amendment: it applies that
correction and nothing else, is not counted as a replan, and does not move
the next replan up a tier. Whether it really was one is decided here, from
the files, never from what the planner says it did:

  * `## Goal`, `## Out of scope` and `## Needs human judgement` are unchanged
    -- the work being asked for is the same work;
  * no `##` section appeared or disappeared;
  * at most MAX_LINES lines changed across the other sections. `## State`
    (the driver's) and `## Log` (append-only history) are not compared.

Anything else counts as a replan, with the same tier escalation and cap as
one the driver asked for.

Usage:
    py -3 tools/amend_check.py save  <slug>-plan.md [<slug>-context.md]
    py -3 tools/amend_check.py check <slug>-plan.md [<slug>-context.md]

`save`, run before the planner is sent the amendment, copies each file to
`<plan dir>/.rounds/<slug>/amend-base-<plan|context>.md` (ignored with the
rest of `.claude/workorders/`). `check`, run after it returns, compares each
file against its copy and prints one `<file>: ## <heading>: +<a> -<d>` line
per changed section, then `lines_changed: <N>` and one verdict line:
`AMENDMENT` or `REPLAN: <reasons>`.

Exit code: 0 an amendment, 1 a replan, 2 a usage error or no saved copy.
"""

import difflib
import re
import shutil
import sys
from pathlib import Path

MAX_LINES = 20
FROZEN = ("goal", "out of scope", "needs human judgement")
IGNORED = ("state", "log")
HEADING = re.compile(r"^##\s+(.+?)\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


def sections(text: str) -> dict:
    """`{heading (lowercased): [lines]}` for each `## ` section; text before
    the first one (frontmatter, title) is not a section and is left out. A
    `## ` line inside a fenced block is content, not a heading."""
    out: dict = {}
    current = None
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
        m = None if fenced else HEADING.match(line)
        if m:
            current = m.group(1).lower()
            out.setdefault(current, [])
            continue
        if current is not None:
            out[current].append(line.rstrip())
    return out


def compare(before: str, after: str) -> tuple:
    """`(changed, reasons)`: `changed` is `[(heading, added, deleted)]` for
    each compared section that differs; `reasons` lists what makes the change
    a replan (a frozen section changed, or a section came or went)."""
    old, new = sections(before), sections(after)
    reasons, changed = [], []
    for heading in sorted(old.keys() - new.keys()):
        reasons.append(f"## {heading} removed")
    for heading in sorted(new.keys() - old.keys()):
        reasons.append(f"## {heading} added")
    for heading in sorted(old.keys() & new.keys()):
        if heading in IGNORED or old[heading] == new[heading]:
            continue
        added = deleted = 0
        for line in difflib.unified_diff(old[heading], new[heading], lineterm="", n=0):
            if line.startswith(("+++", "---", "@@")):
                continue
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                deleted += 1
        changed.append((heading, added, deleted))
        if heading in FROZEN:
            reasons.append(f"## {heading} changed")
    return changed, reasons


def _slug(plan: Path) -> str:
    stem = plan.stem
    return stem[: -len("-plan")] if stem.endswith("-plan") else stem


def _base(plan: Path, kind: str) -> Path:
    return plan.parent / ".rounds" / _slug(plan) / f"amend-base-{kind}.md"


def _files(plan: Path, context) -> list:
    out = [("plan", plan)]
    if context is not None and context.resolve() != plan.resolve():
        out.append(("context", context))
    return out


def cmd_save(plan: Path, context) -> int:
    for kind, path in _files(plan, context):
        if not path.is_file():
            print(f"amend_check: no such file: {path}", file=sys.stderr)
            return 2
        target = _base(plan, kind)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        print(f"saved {path} -> {target}")
    return 0


def cmd_check(plan: Path, context) -> int:
    total, reasons = 0, []
    for kind, path in _files(plan, context):
        base = _base(plan, kind)
        if not base.is_file() or not path.is_file():
            print(f"amend_check: missing {path if not path.is_file() else base} "
                  f"(run `save` before the amendment)", file=sys.stderr)
            return 2
        changed, why = compare(base.read_text(encoding="utf-8", errors="replace"),
                               path.read_text(encoding="utf-8", errors="replace"))
        for heading, added, deleted in changed:
            print(f"{path.name}: ## {heading}: +{added} -{deleted}")
            total += added + deleted
        reasons.extend(f"{path.name}: {r}" for r in why)
    print(f"lines_changed: {total}")
    if total > MAX_LINES:
        reasons.append(f"{total} lines changed (limit {MAX_LINES})")
    if reasons:
        print("REPLAN: " + "; ".join(reasons))
        return 1
    print("AMENDMENT")
    return 0


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in (2, 3) or args[0] not in ("save", "check"):
        print(__doc__.strip().split("\n\n")[-3], file=sys.stderr)
        return 2
    plan = Path(args[1])
    context = Path(args[2]) if len(args) == 3 else None
    return cmd_save(plan, context) if args[0] == "save" else cmd_check(plan, context)


if __name__ == "__main__":
    sys.exit(main())
