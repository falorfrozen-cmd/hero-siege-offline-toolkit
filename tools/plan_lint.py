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

And one measured in the ForgePact UI redesign (2026-09-24..26):

  pinned-sha       a bare commit hash (7-40 lowercase hex characters, at
                   least one digit and one letter, standing alone) in a
                   backticked span. A plan written against `HEAD`,
                   `origin/main` or the branch pins a head that moves: the
                   next commit, merge or amendment makes the criterion
                   compare against the wrong tree. Name a per-workorder tag
                   (`git tag <slug>-base`) or a merge-base expression
                   (`$(git merge-base HEAD origin/main)`) instead. A
                   64-character digest, a `0x` literal, a `#rrggbb` colour
                   and a hex run inside a longer word or a `-`-joined name
                   are not flagged.

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

And the items a streamed plan declares under `## Steps` (2026-09-26): a
`### Item: <id>` heading (optionally `— <title>`), then a `files:` line the
item alone may edit, a `checks:` line or bullet list of the targeted checks
its change can reach, and optionally `after:` (items that must be done
first), `shares:` (items whose files overlap this one's on purpose, run one
after the other) and `owner:` (the question the item waits on). Items run as
parallel implementers, so file sets that meet must say so:

  item-overlap     two items' file sets overlap (same rule as lanes) and
                   neither names the other in `after:` or `shares:`.
  item-no-files    an item with no `files:` line, or an empty one.
  item-no-checks   an item with no backticked check.
  item-dup-id      two items with the same id.
  item-bad-id      an id outside `[a-z0-9-]+`.
  item-unknown-ref `after:`/`shares:` naming an item the plan lacks.
  item-cycle       `after:` edges that loop.
  items-and-lanes  one plan declaring both, which the engine cannot run.

Each check is linted like a criterion (prose, bare-python, ...).

Usage:
    py -3 tools/plan_lint.py <slug>-plan.md [...]
    py -3 tools/plan_lint.py <slug>-plan.md --lanes-json
    py -3 tools/plan_lint.py <slug>-plan.md --items-json [--known a,b --wait SECONDS]

Prints `<plan>: criterion <k>: <rule>: <excerpt>` per criterion finding,
`<plan>: lane <name>: <rule>: <excerpt>` per lane finding and `<plan>: item
<id>: <rule>: <excerpt>` per item finding; all count in the `finding(s)`
line. `--lanes-json` (one plan) then prints, only when the lint is clean, one
JSON line `{"lanes": [{"name": ..., "files": [...]}, ...], "join":
true|false}` -- the lane table the driver passes to the workflow, so it can
never launch lanes a lint rejected. `--items-json` likewise prints `{"items":
[{"id", "title", "files", "checks", "after", "shares", "owner"}, ...],
"complete": true|false}`, `complete` false while `## State` says `planning:
streaming`. With `--known` it prints only the items not in that list, and
with `--wait` it first polls the plan (every 5 s, at most SECONDS) until an
unknown item appears or planning is complete -- what the round engine's
refill agent runs while the planner is still releasing items.
Exit code: 0 clean, 1 a finding, 2 no file or no `## Acceptance criteria`.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
import time
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
# A hex run standing alone: not inside a longer word, a `0x`/`#` literal or a
# `-`-joined name (a worktree or UUID segment), and at most 40 characters, so
# a sha256 digest never matches. Git prints hashes lowercase.
HEX_RUN_RE = re.compile(r"(?<![0-9A-Za-z_#-])[0-9a-f]{7,40}(?![0-9A-Za-z_-])")

STEPS_HEADING_RE = re.compile(r"^##\s+Steps\s*$")
H3_RE = re.compile(r"^###\s")
LANE_HEADING_RE = re.compile(r"^###\s+Lane:\s*(.*?)\s*$")
JOIN_HEADING_RE = re.compile(r"^###\s+Join\b")
FILES_LINE_RE = re.compile(r"^\s*(?:[-*]\s+)?\**files:\**\s*(.*)$")
# A step starts a numbered or bulleted item; the `files:` list ends there.
STEP_START_RE = re.compile(r"^\s*(?:\d+\.|[-*])\s")
LANE_NAME_RE = re.compile(r"[a-z0-9-]+")
GLOB_CHARS = "*?["
ITEM_HEADING_RE = re.compile(r"^###\s+Item:\s*`?([^`\s—–]*)`?\s*(?:[—–-]+\s*(.*?))?\s*$")
ITEM_FIELD_RE = re.compile(r"^\s*(?:[-*]\s+)?\**(files|checks|after|shares|owner):\**\s*(.*)$", re.I)
NUMBERED_STEP_RE = re.compile(r"^\s*\d+\.\s")
BULLET_RE = re.compile(r"^\s*[-*]\s+")
STATE_HEADING_RE = re.compile(r"^##\s+State\s*$")


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
        if any(_looks_like_sha(h) for h in HEX_RUN_RE.findall(span)):
            found.append(("pinned-sha", span))
    return found


def _looks_like_sha(run: str) -> bool:
    """A hex run with a digit and a letter: `deadbeef` and `20260926` are
    words and dates far more often than hashes."""
    return any(c.isdigit() for c in run) and any(c.isalpha() for c in run)


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
        # A directory literal (`docs/`) against a glob beneath it, or above
        # it: fnmatch's `*` crosses `/`, so `*.md` reaches `docs/readme.md`.
        p = _literal_prefix(glob)
        return literal.endswith("/") and (p.startswith(literal) or literal.startswith(p))
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


def _ticked(text: str) -> list:
    return [(a or b).strip().replace("\\", "/").removeprefix("./")
            for a, b in BACKTICK_RE.findall(text) if (a or b).strip()]


def _item_fields(body: list) -> dict:
    """An item's fields, read before its first numbered step. `checks:` takes
    its own line and any bullet lines under it, one check per bullet (or the
    whole inline text as one check); `files:` continues onto lines that carry
    a backtick, as a lane's does."""
    fields = {"files": None, "checks": [], "after": [], "shares": [], "owner": None}
    current = None
    for line in body:
        if NUMBERED_STEP_RE.match(line):
            break
        m = ITEM_FIELD_RE.match(line)
        if m:
            key, value = m.group(1).lower(), m.group(2).strip()
            current = key
            if key == "files":
                fields["files"] = _ticked(value)
            elif key == "checks" and value:
                fields["checks"].append(value)
            elif key in ("after", "shares"):
                fields[key] = _ticked(value) or [v.strip() for v in re.split(r"[,\s]+", value) if v.strip()]
            elif key == "owner":
                fields["owner"] = value or None
            continue
        if not line.strip():
            # A blank line between `checks:` and its first bullet is allowed.
            if not (current == "checks" and not fields["checks"]):
                current = None
            continue
        if current == "checks" and BULLET_RE.match(line):
            fields["checks"].append(BULLET_RE.sub("", line, count=1).strip())
        elif current == "checks" and fields["checks"] and line.startswith((" ", "\t")):
            fields["checks"][-1] += "\n" + line.strip()
        elif current == "files" and "`" in line:
            fields["files"] = (fields["files"] or []) + _ticked(line)
        else:
            current = None
    fields["checks"] = [c for c in fields["checks"] if c.strip()]
    return fields


def items(text: str) -> list:
    """Each `### Item: <id>` under `## Steps` as a dict of `id`, `title`,
    `files` (None when the item has no `files:` line), `checks` (the check
    texts, backticks kept), `after`, `shares` and `owner`, in plan order. A
    plan with no `### Item:` heading has no items and runs as it always has."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if STEPS_HEADING_RE.match(line)), None)
    if start is None:
        return []
    found, current = [], None
    for line in lines[start + 1:]:
        if NEXT_H2_RE.match(line):
            break
        if H3_RE.match(line):
            m = ITEM_HEADING_RE.match(line)
            current = {"id": m.group(1).strip("`* "), "title": (m.group(2) or "").strip(), "body": []} if m else None
            if current is not None:
                found.append(current)
            continue
        if current is not None:
            current["body"].append(line)
    return [{"id": it["id"], "title": it["title"], **_item_fields(it["body"])} for it in found]


def planning_complete(text: str) -> bool:
    """False only while `## State` carries `planning: streaming` -- the
    planner is still releasing items. Any other value, or no such line, is a
    finished plan."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if STATE_HEADING_RE.match(line):
            for body in lines[i + 1:]:
                if NEXT_H2_RE.match(body):
                    break
                m = re.match(r"^\s*planning:\s*(\S+)", body, re.I)
                if m:
                    return m.group(1).strip("`").lower() != "streaming"
    return True


def lint_items(declared: list, has_lanes: bool) -> list:
    """`(item, rule, excerpt)` per item finding. Overlap is checked over
    every pair, and allowed only where one item names the other in `after:`
    or `shares:` -- the engine then runs them one after the other."""
    out, seen = [], set()
    ids = {it["id"] for it in declared}
    if declared and has_lanes:
        out.append((declared[0]["id"], "items-and-lanes", "a plan declares `### Item:` or `### Lane:`, not both"))
    for it in declared:
        iid = it["id"]
        if not LANE_NAME_RE.fullmatch(iid):
            out.append((iid, "item-bad-id", f"`### Item: {iid}` (want [a-z0-9-]+)"))
        if iid in seen:
            out.append((iid, "item-dup-id", f"`### Item: {iid}` is declared twice"))
        seen.add(iid)
        if not it["files"]:
            out.append((iid, "item-no-files", "no `files:` line of backticked paths before the item's first step"))
        if not any(BACKTICK_RE.search(c) for c in it["checks"]):
            out.append((iid, "item-no-checks", "no `checks:` with a backticked command before the item's first step"))
        for ref in it["after"] + it["shares"]:
            if ref not in ids:
                out.append((iid, "item-unknown-ref", f"`{ref}` names no `### Item:` in this plan"))
        for k, check in enumerate(it["checks"], 1):
            for rule, excerpt in lint_criterion(check):
                if rule != "prose":
                    out.append((iid, rule, f"check {k}: {excerpt[:150]}"))
    after = {it["id"]: [r for r in it["after"] if r in ids] for it in declared}
    state: dict = {}

    def cyclic(node) -> bool:
        if state.get(node) == 1:
            return True
        if state.get(node) == 2:
            return False
        state[node] = 1
        hit = any(cyclic(nxt) for nxt in after.get(node, []))
        state[node] = 2
        return hit
    for it in declared:
        if it["id"] not in state and cyclic(it["id"]):
            out.append((it["id"], "item-cycle", "`after:` edges loop back to this item"))
    for i, one in enumerate(declared):
        for other in declared[i + 1:]:
            linked = other["id"] in one["after"] + one["shares"] or one["id"] in other["after"] + other["shares"]
            if linked:
                continue
            for a in one["files"] or []:
                hit = next((b for b in other["files"] or [] if _overlap(a, b)), None)
                if hit:
                    out.append((one["id"], "item-overlap",
                                f"`{a}` overlaps item {other['id']} `{hit}` -- declare `shares:` or `after:`"))
                    break
    return out


def lint(path: Path) -> tuple:
    text = path.read_text(encoding="utf-8", errors="replace")
    items_ = criteria(text)
    if items_ is None:
        return None, []
    out = []
    for k, item in enumerate(items_, 1):
        for rule, excerpt in lint_criterion(item):
            out.append((f"criterion {k}", rule, excerpt if len(excerpt) <= 160 else excerpt[:157] + "..."))
    declared_lanes, join = lanes(text)
    for name, rule, excerpt in lint_lanes(declared_lanes, join):
        out.append((f"lane {name}", rule, excerpt))
    for iid, rule, excerpt in lint_items(items(text), bool(declared_lanes)):
        out.append((f"item {iid}", rule, excerpt))
    return len(items_), out


def _items_json(text: str, known: set) -> str:
    return json.dumps({"items": [it for it in items(text) if it["id"] not in known],
                       "complete": planning_complete(text)})


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    want_json = "--lanes-json" in args
    want_items = "--items-json" in args
    known, wait = set(), 0
    for flag in ("--known", "--wait"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                print(f"plan_lint: {flag} needs a value", file=sys.stderr)
                return 2
            value = args.pop(i + 1)
            args.pop(i)
            if flag == "--known":
                known = {v.strip() for v in value.split(",") if v.strip()}
            else:
                try:
                    wait = max(0, int(value))
                except ValueError:
                    print("plan_lint: --wait takes whole seconds", file=sys.stderr)
                    return 2
    paths = [Path(p) for p in args if p not in ("--lanes-json", "--items-json")]
    if not paths or ((want_json or want_items) and len(paths) != 1) or (want_json and want_items):
        print(__doc__.strip().split("\n\n")[-2], file=sys.stderr)
        return 2
    if want_items and wait and paths[0].is_file():
        # Poll until the planner releases an item this caller does not have,
        # or says it is done; a lint finding is reported by the pass below.
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            text = paths[0].read_text(encoding="utf-8", errors="replace")
            if planning_complete(text) or any(it["id"] not in known for it in items(text)):
                break
            time.sleep(min(5, max(0.0, deadline - time.monotonic())))
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
    if want_items and rc == 0:
        print(_items_json(paths[0].read_text(encoding="utf-8", errors="replace"), known))
    return rc


if __name__ == "__main__":
    sys.exit(main())
