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

And three measured when the redesign was reviewed (2026-09-27):

  eof-slice        `.index('\n## ')` (or `### `) to find where a section
                   *ends*: the next heading, of any name. `index` raises
                   when the section is the last in the file, so the
                   criterion fails on a correct tree (restyle, ship). Use
                   `find` and treat -1 as the end of the text.
  merge-walk       `git log`/`git rev-list` over a `A..B` range without
                   `--first-parent`, in a plan that merges `origin/main`.
                   The walk then counts or greps main's merged-in commits
                   as the branch's own (main-merge R0, main-merge-2 R0).
                   A criterion that means every parent says so with
                   `(all-parents)`.
  plan-draft       `status: DRAFT` at the top of the plan: it waits on
                   another workorder's result (`depends on:` names the
                   slugs), so no round may start from it. Written before
                   its inputs existed, the redesign's restyle and ship plans
                   were replanned nine times before either ran a round.
                   Re-plan it against the finished dependencies, then set
                   `status: READY`.

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

And the reach map (2026-09-27), which lets a fix round re-run only the
criteria its change can reach (`run_criteria.py --changed-since`): each
criterion declares the files whose change can alter its result, as
`(reads `<glob>`, `<glob>`, ...)` on the criterion, paths from the checkout
root, submodule files under their directory (`ForgePact/panel/src/**`). These
are *warnings*: they are printed, counted on the summary line, and never
change the exit code, because a criterion without a map is not wrong -- it
runs on every fix round, which is what every plan did before the map existed.

  no-reads         a criterion that declares no `(reads ...)`. The warning
                   names the paths its commands mention, as a starting
                   point: a `cd <dir>` or `npm --prefix <dir>` reads
                   `<dir>/**`, `-m unittest tests.test_x` reads
                   `tests/test_x.py`, and a path-shaped word is itself. A
                   suite reads far more than the paths on its command line,
                   so check the inference before copying it.
  reads-nothing    a declared glob that names no file tracked in this
                   checkout (hub and initialized submodules), so no change
                   would ever select its criterion. Checked only when the
                   plan sits inside a git checkout, and never for a glob
                   under a submodule that is not initialized there, whose
                   files git cannot list. A file the plan creates is the
                   usual false alarm. The `no-reads` hint is filtered the
                   same way, which drops refs and repo slugs.

And the owner questions (workorder-speedup, 2026-09-27), so a question never
idles the pipeline: the engine proceeds on a reversible default and parks
only what an irreversible one gates. An item with `owner:` also carries
`default: <what to do unanswered>` and `reversible: yes|no` (its first word
counts: `yes. Revert the item's commit.`). So does each entry of `## Needs
human judgement`, read in the plan and in its sibling `<slug>-context.md`: a
`###` subsection, or, when the section has none, a top-level list item. A
default is "none" when it is empty or its first word is `none`; a wait on a
live capture or on data that does not exist yet is `reversible: no` with
`default: none`. An item without `owner:` needs neither line.

  owner-no-default the question has no `default:` line.
  owner-no-reversible
                   no `reversible:` line, or its first word is neither `yes`
                   nor `no`.
  owner-reversible-no-default
                   `reversible: yes` with a default that is none: nothing to
                   proceed on, so it would park anyway.
  owner-legal-default
                   the question's text (the whole entry, or an item's
                   `owner:` and `default:`) matches `decompil|disassembl|
                   legal|licen[cs]e|copyright|ghidra|\\bIDA\\b|
                   UndertaleModTool|dnSpy` (any case) and it is `reversible:
                   yes` or its default is not none. A legal or
                   decompile-output question is never defaultable (AGENTS.md,
                   "Legal: Decompiled Output Never Reaches Any Origin").

Usage:
    py -3 tools/plan_lint.py <slug>-plan.md [...]
    py -3 tools/plan_lint.py <slug>-plan.md --lanes-json
    py -3 tools/plan_lint.py <slug>-plan.md --items-json [--known a,b --wait SECONDS]

Prints `<plan>: criterion <k>: warning <rule>: <excerpt>` per reach warning,
`<plan>: criterion <k>: <rule>: <excerpt>` per criterion finding,
`<plan>: lane <name>: <rule>: <excerpt>` per lane finding and `<plan>: item
<id>: <rule>: <excerpt>` per item finding; the findings count in the
`finding(s)` line, and warnings, when there are any, in a `warning(s)` count
after it. `--lanes-json` (one plan) then prints, only when the lint is clean, one
JSON line `{"lanes": [{"name": ..., "files": [...]}, ...], "join":
true|false}` -- the lane table the driver passes to the workflow, so it can
never launch lanes a lint rejected. `--items-json` likewise prints `{"items":
[{"id", "title", "files", "checks", "after", "shares", "owner", "default",
"reversible", "build_reads"}, ...], "complete": true|false}` (`default` a string or null,
`reversible` true, false or null, `build_reads` what the item's `build`/`exclusive`
checks read, see `build_reads()`), `complete` false while `## State` says `planning:
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
import subprocess
import sys
import time
from pathlib import Path

CRITERIA_HEADING_RE = re.compile(r"^##\s+Acceptance criteria\s*$")
NEXT_H2_RE = re.compile(r"^##\s")
ITEM_RE = re.compile(r"^\s*-\s+\[[ xX]\]\s*")
BACKTICK_RE = re.compile(r"``(.+?)``|`([^`]+)`")
UNANCHORED_SLICE_RE = re.compile(r"\.(?:r?index|r?find)\(\s*['\"]#{1,6} ")
# `.index('\n## ')`: a search for whatever heading comes next, which is
# absent when the section is the file's last.
EOF_SLICE_RE = re.compile(r"\.r?index\(\s*(['\"])\\n#{1,6} ?\1")
GIT_WALK_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:log|rev-list)\b[^`]*?\S\.\.\.?\S")
PLAN_MERGES_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?merge\b(?!-)|\bmerges?\s+`?origin/main\b|\bmain moved\b", re.I)
STATUS_RE = re.compile(r"^\s*status:\s*`?([A-Za-z-]+)", re.I)
DEPENDS_RE = re.compile(r"^\s*depends on:\s*(.*)$", re.I)
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
ITEM_FIELD_RE = re.compile(r"^\s*(?:[-*]\s+)?\**(files|checks|after|shares|owner|default|reversible):\**\s*(.*)$",
                           re.I)
JUDGEMENT_HEADING_RE = re.compile(r"^##\s+Needs human judgement\s*$", re.I)
FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
# `default:` / `reversible:` inside a judgement entry, also as its own bullet.
OWNER_FIELD_RE = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+)?\**(default|reversible):\**\s*(.*)$", re.I)
TOP_ENTRY_RE = re.compile(r"^(?:[-*]|\d+\.)\s+")
LEGAL_RE = re.compile(r"decompil|disassembl|legal|licen[cs]e|copyright|ghidra|\bIDA\b|UndertaleModTool|dnSpy", re.I)
NUMBERED_STEP_RE = re.compile(r"^\s*\d+\.\s")
BULLET_RE = re.compile(r"^\s*[-*]\s+")
STATE_HEADING_RE = re.compile(r"^##\s+State\s*$")
# `(reads `a/**`, `b.py`)`: backticked globs, which may hold parentheses.
READS_DECL_RE = re.compile(r"\(reads\s+((?:`[^`]*`|[^()`])*)\)")
INFER_DIR_RE = re.compile(r"(?:\bcd\s+|--prefix[=\s]+)(\"[^\"]+\"|'[^']+'|[^\s;&|]+)")
INFER_MODULE_RE = re.compile(r"-m\s+(?:unittest|pytest)\s+(?:-\S+\s+)*([A-Za-z_][\w.]*)")
INFER_SPLIT_RE = re.compile(r"[\s;&|()<>=,'\"`{}\[\]]+")
INFER_PATH_RE = re.compile(r"(?=.*[A-Za-z])[\w.*?/-]+")
INFER_EXT_RE = re.compile(r"\.(?:py|md|mjs|cjs|js|ts|tsx|svelte|json|cpp|hpp|h|c|rs|toml|ya?ml|txt|css|html|"
                          r"ps1|bat|sh|csv)$")


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


def reads(text: str) -> list | None:
    """The globs a criterion's `(reads ...)` declares, forward-slashed; None
    when it declares none (an empty declaration is none, not "reads
    nothing": a criterion that read nothing could never fail)."""
    found = [g for m in READS_DECL_RE.finditer(text) for g in _ticked(m.group(1))]
    return found or None


def without_reads(text: str) -> str:
    """The criterion with its `(reads ...)` removed, so a declared path is
    never mistaken for a command or linted as one."""
    return READS_DECL_RE.sub("", text)


def reads_path(glob: str, path: str) -> bool:
    """Whether a changed `path` is one a `(reads ...)` glob covers. `*`
    crosses `/` (fnmatch), so `dir/*` and `dir/**` both cover everything
    under `dir/`; a literal covers itself and, as a directory, everything
    under it. A `**/` anywhere also matches no directory at all, as a
    globstar does: `**/x` covers a root-level `x`, and `dir/**/*.ts` covers
    `dir/a.ts` (fnmatch alone keeps the `/` after `**` and misses both)."""
    glob = glob.replace("\\", "/").removeprefix("./")
    path = path.replace("\\", "/").removeprefix("./")
    if glob.rstrip("/") in ("", "*", "**"):
        return True
    if _is_glob(glob):
        return any(fnmatch.fnmatchcase(path, g) for g in _globstar_forms(glob))
    glob = glob.rstrip("/")
    return path == glob or path.startswith(glob + "/")


def _globstar_forms(glob: str) -> set:
    """`glob` and every form of it with one or more of its `**/` removed."""
    forms, todo = {glob}, [glob]
    while todo:
        g = todo.pop()
        i = g.find("**/")
        while i >= 0:
            if i == 0 or g[i - 1] == "/":
                shorter = g[:i] + g[i + 3:]
                if shorter not in forms:
                    forms.add(shorter)
                    todo.append(shorter)
            i = g.find("**/", i + 1)
    return forms


def infer_reads(text: str) -> list:
    """Paths a criterion's spans mention, as a suggestion for its `(reads
    ...)`: never used to select anything, because a suite reads far more
    than its command line names."""
    out: list = []
    for a, b in BACKTICK_RE.findall(without_reads(text)):
        span = a or b
        dirs = [m.group(1) for m in INFER_DIR_RE.finditer(span)]
        out += [d.strip("\"'").rstrip("/") + "/**" for d in dirs]
        if dirs:
            continue
        out += [m.group(1).replace(".", "/") + ".py" for m in INFER_MODULE_RE.finditer(span)
                if m.group(1) != "discover"]
        for token in INFER_SPLIT_RE.split(span):
            token = token.removeprefix("./")
            if (token and not token.startswith(("-", "$", "http")) and INFER_PATH_RE.fullmatch(token)
                    and ("/" in token or INFER_EXT_RE.search(token)) and token.strip("./")):
                out.append(token)
    return list(dict.fromkeys(out))


def reach_warnings(text: str, tracked: tuple | None = None) -> list:
    """`(criterion k, rule, excerpt)` per reach-map warning. `tracked` is
    `tracked_files()`'s `(files, opaque)`: every file in the checkout, and
    the submodule directories whose files are unknown because they are not
    initialized here. None when unknown: then `reads-nothing` is not checked
    and the inferred paths are not filtered."""
    files, opaque = tracked if tracked is not None else (None, [])

    def known(glob: str) -> bool:
        return any(reads_path(o, glob.rstrip("*/")) for o in opaque) or any(reads_path(glob, f) for f in files)
    out = []
    for k, item in enumerate(criteria(text) or [], 1):
        declared = reads(item)
        if declared is None:
            # A ref (`origin/main`), a range or a repo slug looks like a path;
            # keeping only what names a tracked file drops them.
            inferred = [p for p in infer_reads(item) if files is None or known(p)]
            hint = ("inferred from its commands, check before copying: " + ", ".join(f"`{p}`" for p in inferred)
                    if inferred else "nothing to infer from; until it declares one it runs on every fix round")
            out.append((f"criterion {k}", "no-reads", f"declare (reads `<glob>`, ...); {hint}"))
            continue
        if files is not None:
            for glob in declared:
                if not known(glob):
                    out.append((f"criterion {k}", "reads-nothing",
                                f"`{glob}` names no tracked file here, so no change would select this criterion"))
    return out


def tracked_files(plan: Path) -> tuple | None:
    """`(files, opaque)` for the checkout the plan sits in: every tracked
    file, submodule files under their directory, and the submodule
    directories that are not initialized here, whose files git cannot list.
    None when the plan is not inside a git checkout."""
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(plan.resolve().parent),
                         capture_output=True, text=True)
    if top.returncode != 0:
        return None
    root = Path(top.stdout.strip())
    listed = subprocess.run(["git", "ls-files", "--recurse-submodules"], cwd=str(root),
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    staged = subprocess.run(["git", "ls-files", "-s"], cwd=str(root),
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if listed.returncode != 0 or staged.returncode != 0:
        return None
    gitlinks = [line.split("	", 1)[1] for line in staged.stdout.splitlines() if line.startswith("160000 ")]
    opaque = [d for d in gitlinks if not (root / d / ".git").exists()]
    return [p for p in listed.stdout.splitlines() if p], opaque


def lint_criterion(text: str, merges: bool = False) -> list:
    """`(rule, excerpt)` per finding. `merges` says the plan merges
    `origin/main`, which is when a walk without `--first-parent` goes wrong."""
    all_parents = "(all-parents)" in text
    text = without_reads(text)
    spans = [a or b for a, b in BACKTICK_RE.findall(text)]
    if not spans:
        return [("prose", text)]
    found = []
    for span in spans:
        if UNANCHORED_SLICE_RE.search(span) and not COLLAPSED_TEXT_RE.search(span):
            found.append(("unanchored-slice", span))
        if EOF_SLICE_RE.search(span):
            found.append(("eof-slice", span))
        if merges and not all_parents and GIT_WALK_RE.search(span) and "--first-parent" not in span:
            found.append(("merge-walk", span))
        if "-live-" in span and CAPTURE_GREP_RE.search(span):
            found.append(("capture-grep", span))
        if BARE_PYTHON_RE.search(" " + span):
            found.append(("bare-python", span))
        if any(_looks_like_sha(h) for h in HEX_RUN_RE.findall(span)):
            found.append(("pinned-sha", span))
    return found


def plan_merges(text: str) -> bool:
    """Whether the plan merges `origin/main` into its branch (a step, the
    'main moved' precondition, or a criterion that says so)."""
    return bool(PLAN_MERGES_RE.search(text))


def draft(text: str, plan_dir: Path | None = None) -> list:
    """`[(rule, excerpt)]` for a plan whose header (before the first `## `)
    says `status: DRAFT`, naming each `depends on:` slug with its own plan's
    status when that plan sits beside this one."""
    status, deps = None, []
    for line in text.splitlines():
        if NEXT_H2_RE.match(line):
            break
        m = STATUS_RE.match(line)
        if m and status is None:
            status = m.group(1).upper()
        d = DEPENDS_RE.match(line)
        if d:
            deps += _ticked(d.group(1)) or [v for v in re.split(r"[,\s]+", d.group(1)) if v]
    if status != "DRAFT":
        return []
    shown = []
    for slug in deps:
        other = plan_dir / f"{slug}-plan.md" if plan_dir is not None else None
        theirs = None
        if other is not None and other.is_file():
            for line in other.read_text(encoding="utf-8", errors="replace").splitlines():
                if NEXT_H2_RE.match(line):
                    break
                m = STATUS_RE.match(line)
                if m:
                    theirs = m.group(1).upper()
                    break
        shown.append(f"{slug} ({theirs or 'no plan beside this one'})")
    waits = ("waits on " + ", ".join(shown)) if shown else "names no `depends on:`"
    return [("plan-draft", f"status: DRAFT, {waits}; re-plan against the finished result, then set READY")]


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
    fields = {"files": None, "checks": [], "after": [], "shares": [], "owner": None, "default": None,
              "reversible": None}
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
            elif key == "default":
                fields["default"] = value
            elif key == "reversible":
                fields["reversible"] = _reversible(value)
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
        elif current == "default":
            fields["default"] = (fields["default"] + " " + line.strip()).strip()
        else:
            current = None
    fields["checks"] = [c for c in fields["checks"] if c.strip()]
    return fields


def items(text: str) -> list:
    """Each `### Item: <id>` under `## Steps` as a dict of `id`, `title`,
    `files` (None when the item has no `files:` line), `checks` (the check
    texts, backticks kept), `after`, `shares`, `owner`, `default` (the text,
    None without a `default:` line) and `reversible` (True, False, or None
    without a `yes`/`no` value), in plan order. A plan with no `### Item:`
    heading has no items and runs as it always has."""
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


def _reversible(value: str) -> bool | None:
    """`reversible:`'s answer from its first word (`yes. Revert ...`,
    `` `no` ``); None when that word is neither."""
    m = re.match(r"[`*_\s]*(yes|no)\b", value, re.I)
    return None if m is None else m.group(1).lower() == "yes"


def _no_default(value: str) -> bool:
    """Whether a `default:` value offers nothing to proceed on: empty, or its
    first word is `none` (`none (waits on the capture)`)."""
    return not value.strip("`*_ .") or re.match(r"[`*_\s]*none\b", value, re.I) is not None


def owner_findings(title: str, text: str, default: str | None, reversible: bool | None) -> list:
    """`(rule, excerpt)` per finding on one owner question: an `owner:` item
    or a `## Needs human judgement` entry. `text` is what the legal rule
    searches: the whole entry, or an item's question and default."""
    label = f'"{title[:60]}{"..." if len(title) > 60 else ""}"'
    out = []
    if default is None:
        out.append(("owner-no-default", f"{label} has no `default:` line"))
    if reversible is None:
        out.append(("owner-no-reversible", f"{label} has no `reversible: yes` or `reversible: no` line"))
    if reversible is True and default is not None and _no_default(default):
        out.append(("owner-reversible-no-default",
                    f"{label} is `reversible: yes` with no default to proceed on; give one, or mark it `no`"))
    if LEGAL_RE.search(text) and (reversible is True or (default is not None and not _no_default(default))):
        out.append(("owner-legal-default",
                    f"{label} is a legal or decompile-output question: it takes `reversible: no` and "
                    "`default: none`, never a default"))
    return out


def _unfenced(lines: list) -> list:
    """`(line, fenced)` per line: whether it sits inside a ``` or ~~~ fence
    (the fence lines themselves count as fenced)."""
    out, fence = [], False
    for line in lines:
        if FENCE_RE.match(line):
            out.append((line, True))
            fence = not fence
            continue
        out.append((line, fence))
    return out


def judgement_entries(text: str) -> list:
    """Each entry of `## Needs human judgement` as `{"title", "text",
    "default", "reversible"}`: a `###` subsection, or, when the section has
    none, a top-level (unindented) list item. A list line that is itself a
    `default:` or `reversible:` belongs to the entry before it, and an entry
    that only says `none` is no entry. Headings inside a fence are text."""
    lines = _unfenced(text.splitlines())
    start = next((i for i, (line, fenced) in enumerate(lines)
                  if not fenced and JUDGEMENT_HEADING_RE.match(line)), None)
    if start is None:
        return []
    body = []
    for line, fenced in lines[start + 1:]:
        if not fenced and NEXT_H2_RE.match(line):
            break
        body.append((line, fenced))
    groups: list = []
    if any(not fenced and H3_RE.match(line) for line, fenced in body):
        for line, fenced in body:
            if not fenced and H3_RE.match(line):
                groups.append([line])
            elif groups:
                groups[-1].append(line)
    else:
        current, blank = None, False
        for line, fenced in body:
            if not line.strip():
                blank = True
                if current is not None:
                    current.append(line)
                continue
            starts = not fenced and TOP_ENTRY_RE.match(line) and not OWNER_FIELD_RE.match(line)
            if starts:
                current = [line]
                groups.append(current)
            elif current is not None and blank and not line.startswith((" ", "\t")) \
                    and not OWNER_FIELD_RE.match(line):
                current = None  # prose after the list
            elif current is not None:
                current.append(line)
            blank = False
    out = []
    for group in groups:
        title = re.sub(r"^(?:###\s+|(?:[-*]|\d+\.)\s+)", "", group[0]).strip()
        if re.fullmatch(r"[`*_\s]*(?:none|n/a)[`*_.\s]*", title, re.I) and not "".join(group[1:]).strip():
            continue
        default, reversible, current = None, None, None
        for line in group[1:]:
            m = OWNER_FIELD_RE.match(line)
            if m:
                current = m.group(1).lower()
                if current == "default":
                    default = m.group(2).strip()
                else:
                    reversible = _reversible(m.group(2))
            elif current == "default" and line.strip():
                default = (default + " " + line.strip()).strip()
            else:
                current = None
        out.append({"title": title, "text": "\n".join(group), "default": default, "reversible": reversible})
    return out


def lint_owner(declared: list, text: str, context: str | None = None) -> list:
    """`(where, rule, excerpt)` per owner-question finding: each item with an
    `owner:`, each `## Needs human judgement` entry of the plan (`judgement
    <k>`) and of its sibling context file (`context judgement <k>`)."""
    out = []
    for it in declared:
        if it.get("owner"):
            for rule, excerpt in owner_findings(it["owner"], it["owner"] + "\n" + (it.get("default") or ""),
                                                it.get("default"), it.get("reversible")):
                out.append((f"item {it['id']}", rule, excerpt))
    for prefix, source in (("judgement", text), ("context judgement", context)):
        for k, entry in enumerate(judgement_entries(source or ""), 1):
            for rule, excerpt in owner_findings(entry["title"], entry["text"], entry["default"], entry["reversible"]):
                out.append((f"{prefix} {k}", rule, excerpt))
    return out


def sibling_context(plan: Path) -> Path | None:
    """`<slug>-context.md` beside `<slug>-plan.md`; None for any other name."""
    if not plan.name.endswith("-plan.md"):
        return None
    return plan.with_name(plan.name[: -len("-plan.md")] + "-context.md")


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
    out = [("plan", rule, excerpt) for rule, excerpt in draft(text, path.parent)]
    merges = plan_merges(text)
    for k, item in enumerate(items_, 1):
        for rule, excerpt in lint_criterion(item, merges):
            out.append((f"criterion {k}", rule, excerpt if len(excerpt) <= 160 else excerpt[:157] + "..."))
    declared_lanes, join = lanes(text)
    for name, rule, excerpt in lint_lanes(declared_lanes, join):
        out.append((f"lane {name}", rule, excerpt))
    declared_items = items(text)
    for iid, rule, excerpt in lint_items(declared_items, bool(declared_lanes)):
        out.append((f"item {iid}", rule, excerpt))
    context = sibling_context(path)
    context_text = context.read_text(encoding="utf-8", errors="replace") if context and context.is_file() else None
    out += lint_owner(declared_items, text, context_text)
    return len(items_), out


def build_reads(checks: list) -> list:
    """What an item's `build`/`exclusive` checks read (declared with `(class
    ...)`, or a command `run_criteria` recognises as one): the union of their
    `(reads ...)` globs, `["*"]` when one of them declares none (it then
    reads whatever changed, as `run_criteria.select` treats it), and `[]`
    when the item has no such check. The round engine re-runs a done item
    with a non-empty list when a later commit lands on a path it covers:
    a build that passed before a reviewer's fix still names the old tree
    (forgepact-124-pet-relics, 2026-10-02: three relaunches for a DLL that
    predated the last fix commit)."""
    import run_criteria  # imports this module; deferred so neither import loops
    out: list = []
    for check in checks:
        cmds = run_criteria.commands(check)
        declared = run_criteria.CLASS_DECL_RE.search(check)
        if declared:
            builds = declared.group(1) in ("build", "exclusive")
        else:
            # `classify` calls any command it does not recognise `exclusive`
            # too; only a recognised build or barrier counts here, or every
            # `grep`-and-`bash` check would re-run on every commit.
            bodies = [run_criteria.ANY_CD_RE.sub("", c.strip()) for c in cmds]
            builds = any(run_criteria.BUILD_RE.search(b) or run_criteria.EXCLUSIVE_RE.search(b) for b in bodies)
        if not cmds or not builds:
            continue
        globs = reads(check)
        if globs is None:
            return ["*"]
        out += [g for g in globs if g not in out]
    return out


def _items_json(text: str, known: set) -> str:
    return json.dumps({"items": [{**it, "build_reads": build_reads(it["checks"])}
                                 for it in items(text) if it["id"] not in known],
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
        warnings = reach_warnings(path.read_text(encoding="utf-8", errors="replace"), tracked_files(path))
        for where, rule, excerpt in warnings:
            print(f"{path}: {where}: warning {rule}: {excerpt}")
        for where, rule, excerpt in findings:
            print(f"{path}: {where}: {rule}: {excerpt}")
        print(f"{path}: {n} criteria, {len(findings)} finding(s)" +
              (f", {len(warnings)} warning(s)" if warnings else ""))
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
