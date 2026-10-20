#!/usr/bin/env python3
"""Write a `/workorder` launch's State and Log from its saved run record.

    py -3 tools/workorder_record.py apply --run <wf_id | id | path/to/wf_<id>.json>
        [--project-dir DIR] [--slug SLUG]
    py -3 tools/workorder_record.py apply --latest --slug SLUG [--project-dir DIR]

`--latest` takes the newest saved run whose args name `SLUG`: what a
`/workorder resume` applies when the session before it ended without
applying its last launch (already applied, it changes nothing).

Why this exists: `workorder-rounds.js` runs in the Workflow tool, which can
neither read nor write a file. Until 2026-10-11 a haiku `scribe` agent pasted
each round's precomputed Log block and State into the workorder files and
reported them back, and 92 of 353 launches (26%) ended STATE-LOST,
LOG-DAMAGED or SCRIBE-FAILED on that bookkeeping rather than on the work (the
/workorder architecture audit, F01). The script now returns the same text in
its result, `record: {slug, planPath, contextPath, checkoutRoot, launch,
rounds: [{round, stateLines, logBlock}], state}`, and Claude Code saves that
result in the run record `~/.claude/projects/<encoded cwd>/<session>/
workflows/wf_<runId>.json` (top-level `runId`, `args`, `result`). The driver
runs this tool once after every launch, before anything else reads the files.

For each recorded round, in order:

1. its `stateLines` are merged by key into `<slug>-plan.md` `## State`: a key
   already there is replaced in place, a new key is added at the end, every
   other line stays as it is (the same merge the script uses, `stateEntries`
   and `mergeState`), plus `last run: <runId>`;
2. its `logBlock` is appended at the end of `## Log` in `<slug>-context.md`
   (the plan itself for a legacy single-file plan), after the marker
   `<!-- workorder-record run=<runId> round=<n> -->`.

A round whose marker is already in the Log is skipped whole, so applying the
same run twice changes nothing; the State merge is itself idempotent, so a
crash between the two writes is repaired by running the tool again. Every
write goes to a temporary file in the same directory and replaces the
original in one step, keeping the file's line endings.

Run records are looked up under `--project-dir` if given, else under this
checkout's project directory (`$CLAUDE_CONFIG_DIR` or `~/.claude`, then
`projects/<cwd with every non-alphanumeric character as '-'>`), else under
every project.

After writing, it prints what the launch came back with, so the driver routes
from the summary instead of parsing the run record: the outcome and its
detail, each item that is not done with its reason, open BLOCKING findings by
reviewer, what waits on a person, and -- when an agent failed on the
account's session limit -- that limit's reset time from the run's log. Week
one after #485 (#540) counted 334 inline Python scripts in 43 driver
sessions, 68 of them parsing run records by hand.

Exit codes: 0 applied (or already applied); 2 usage; 3 no run record, or none
carrying a `record` (a launch from before 2026-10-11, or one that failed
before returning); 4 the record names another workorder than `--slug`, its
own args or its plan file, or a workorder file cannot be read.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent / ".claude" / "skills" / "workorder"))
import section  # noqa: E402

MARK_RE = re.compile(r"^<!--\s*workorder-record\s+run=(\S+)\s+round=(\d+)\s*-->$")
STATE_KEY = re.compile(r"^([a-z][a-z0-9 _-]*?):(\s|$)", re.IGNORECASE)
TWO_KEYS = re.compile(r"\s{2,}(?=[a-z][a-z0-9 _-]*?:\s)", re.IGNORECASE)


class Fail(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


# -- State: the script's own merge, in Python ----------------------------------

def state_entries(text: str) -> list:
    """[(key, text)] the way `workorder-rounds.js` `stateEntries` splits State:
    one entry per key, a line carrying two keys split at the second, a line
    with no key continuing the entry before it."""
    out: list = []
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip() or line.startswith("#"):
            continue
        if not STATE_KEY.match(line):
            if out:
                out[-1] = (out[-1][0], out[-1][1] + "\n" + line)
            else:
                out.append(("", line))
            continue
        for seg in TWO_KEYS.split(line):
            out.append((STATE_KEY.match(seg).group(1).lower(), seg))
    return out


def merge_state(old: list, updates: list) -> list:
    """Old order kept; an updated key replaces its entry in place (a duplicate
    of it is dropped); a key the old block lacked goes at the end."""
    by_key = {k: (k, t) for k, t in updates}
    placed, out = set(), []
    for key, text in old:
        if key not in by_key:
            out.append((key, text))
        elif key not in placed:
            out.append(by_key[key])
            placed.add(key)
    out.extend(u for u in updates if u[0] not in placed)
    return out


# -- files -------------------------------------------------------------------

class Doc:
    def __init__(self, path: Path):
        try:
            raw = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise Fail(4, f"cannot read {path}: {exc}")
        self.path = path
        self.crlf = "\r\n" in raw
        self.text = raw.replace("\r\n", "\n")

    def write(self) -> None:
        data = self.text.replace("\n", "\r\n") if self.crlf else self.text
        fd, tmp = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(data)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _h2_span(lines: list, name: str):
    """(heading index, end index) of the `## <name>` section, fences honoured,
    or None."""
    found, _ = section.headings(lines)
    for i, (at, level, text) in enumerate(found):
        if level == 2 and text == name:
            end = next((other_at for other_at, other_level, _ in found[i + 1:] if other_level <= 2), len(lines))
            return at, end
    return None


def apply_state(doc: Doc, state_lines: str) -> None:
    lines = doc.text.split("\n")
    span = _h2_span(lines, "State")
    updates = state_entries(state_lines)
    if span is None:
        # No State yet: add one after the frontmatter block, before `## Goal`.
        block = ["## State", *[t for _, t in updates], ""]
        goal = _h2_span(lines, "Goal")
        at = goal[0] if goal else len(lines)
        doc.text = "\n".join(lines[:at] + block + lines[at:])
        return
    start, end = span
    merged = merge_state(state_entries("\n".join(lines[start + 1:end])), updates)
    tail = [""] if end < len(lines) else []
    doc.text = "\n".join(lines[:start + 1] + [t for _, t in merged] + tail + lines[end:])


def log_has(doc: Doc, run_id: str, round_: int) -> bool:
    for line in doc.text.split("\n"):
        m = MARK_RE.match(line.strip())
        if m and m.group(1) == run_id and int(m.group(2)) == round_:
            return True
    return False


def append_log(doc: Doc, run_id: str, round_: int, block: str) -> None:
    lines = doc.text.split("\n")
    span = _h2_span(lines, section.LOG_HEADING)
    entry = [f"<!-- workorder-record run={run_id} round={round_} -->"]
    entry += [line for line in str(block or "").replace("\r\n", "\n").strip("\n").split("\n")] if str(block or "").strip() else []
    if span is None:
        body = doc.text.rstrip("\n")
        doc.text = body + "\n\n## Log\n\n" + "\n".join(entry) + "\n"
        return
    start, end = span
    head, rest = lines[:end], lines[end:]
    while head and not head[-1].strip() and len(head) > start + 1:
        head.pop()
    out = head + [""] + entry
    out += ([""] + rest) if rest else [""]
    doc.text = "\n".join(out)


# -- the run record ----------------------------------------------------------

def encode_cwd(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _checkout_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / ".git").exists():
            return p
    return start


def _search_roots(project_dir: str | None) -> list:
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return [Path(project_dir)] if project_dir else [
        config / "projects" / encode_cwd(_checkout_root(Path.cwd().resolve())),
        config / "projects",
    ]


def find_latest(slug: str, project_dir: str | None) -> Path:
    """The newest saved run whose args name this workorder: what `resume`
    applies when the session before it ended without applying its last
    launch."""
    for root in _search_roots(project_dir):
        runs = sorted(root.glob("**/workflows/wf_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in runs:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            args = data.get("args") if isinstance(data, dict) else None
            if isinstance(args, dict) and args.get("slug") == slug:
                return path
    raise Fail(3, f"no saved run for workorder {slug!r} under {', '.join(str(r) for r in _search_roots(project_dir))}")


def find_run(run: str, project_dir: str | None) -> Path:
    candidate = Path(run)
    if candidate.suffix == ".json" and candidate.is_file():
        return candidate
    rid = run.removesuffix(".json")
    rid = rid if rid.startswith("wf_") else f"wf_{rid}"
    name = f"{rid}.json"
    roots = _search_roots(project_dir)
    for root in roots:
        hits = sorted(root.glob(f"**/workflows/{name}"), key=lambda p: p.stat().st_mtime, reverse=True)
        if hits:
            return hits[0]
    raise Fail(3, f"no run record {name} under {', '.join(str(r) for r in roots)}")


def load_record(path: Path) -> tuple:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Fail(3, f"cannot read the run record {path}: {exc}")
    result = data.get("result") if isinstance(data, dict) else None
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            result = None
    record = result.get("record") if isinstance(result, dict) else None
    if not isinstance(record, dict) or not isinstance(record.get("rounds"), list):
        outcome = result.get("outcome") if isinstance(result, dict) else None
        raise Fail(3, f"{path} carries no `record` (outcome {outcome or 'none'}): a launch from before "
                      "2026-10-11, or one that never returned; repair State and Log by hand from its `result`")
    run_id = str(data.get("runId") or path.stem)
    return run_id, record, data.get("args") if isinstance(data.get("args"), dict) else {}, result, data


# `[label] failed: You've hit your session limit · resets 1:40pm (Europe/Warsaw)`,
# as a run's `logs` record an agent the account's limit stopped.
SESSION_LIMIT_RE = re.compile(r"session limit\W+resets\s+([^\n\]]+?)\s*$", re.I | re.M)


def summary(result: dict, data: dict) -> list:
    """The lines a driver routes from, read off the launch's `result` and
    the run's `logs`; nothing here is judged, only reported."""
    out = [f"outcome: {result.get('outcome')}" + (f" -- {result['detail']}" if result.get("detail") else "")]
    items = [i for i in result.get("items") or [] if isinstance(i, dict)]
    if items:
        counts: dict = {}
        for i in items:
            counts[i.get("status")] = counts.get(i.get("status"), 0) + 1
        out.append("items: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
        for i in items:
            if i.get("status") != "done":
                why = i.get("reason") or "-"
                out.append(f"  {i.get('id')}: {i.get('status')} -- {why}" + (f"; replan: {i['replan']}" if i.get("replan") else ""))
    for u in result.get("unblocked") or []:
        out.append(f"unblocked: {u.get('id')} ({u.get('reason')} -> {u.get('route')})")
    blocking = [b for b in result.get("blocking") or [] if isinstance(b, dict)]
    if not blocking:
        blocking = [b for r in result.get("rounds") or [] if isinstance(r, dict) for b in (r.get("blocking") or [])][-50:]
    if blocking:
        by: dict = {}
        for b in blocking:
            by[b.get("reviewer") or "?"] = by.get(b.get("reviewer") or "?", 0) + 1
        out.append("blocking: " + ", ".join(f"{k} {v}" for k, v in by.items()))
    for h in result.get("pending_human") or []:
        out.append(f"pending human: {h}")
    logs = "\n".join(x if isinstance(x, str) else json.dumps(x) for x in data.get("logs") or [])
    resets = SESSION_LIMIT_RE.findall(logs)
    if resets:
        out.append(f"session limit: {len(resets)} agent(s) stopped on it, resets {resets[-1]}; "
                   "relaunch after the reset (nothing was charged)")
    return out


def resolve(p: str, checkout: str) -> Path:
    path = Path(p)
    if path.is_absolute():
        return path
    base = Path(checkout) if checkout and Path(checkout).is_dir() else _checkout_root(Path.cwd().resolve())
    return base / re.sub(r"^(\.[\\/])+", "", p)


def apply(args) -> int:
    if args.latest and not args.slug:
        raise Fail(2, "--latest needs --slug")
    path = find_latest(args.slug, args.project_dir) if args.latest else find_run(args.run, args.project_dir)
    run_id, record, run_args, result, data = load_record(path)
    slug = record.get("slug")
    for who, other in (("--slug", args.slug), ("the run's own args", run_args.get("slug"))):
        if other and other != slug:
            raise Fail(4, f"the record is for workorder {slug!r}, not {other!r} ({who}); nothing written")
    plan = resolve(record.get("planPath") or run_args.get("planPath") or "", record.get("checkoutRoot") or run_args.get("checkoutRoot") or "")
    context = resolve(record.get("contextPath") or run_args.get("contextPath") or str(plan), record.get("checkoutRoot") or run_args.get("checkoutRoot") or "")
    if not plan.name.startswith(f"{slug}-") and plan.name != f"{slug}.md":
        raise Fail(4, f"the record's plan {plan} is not workorder {slug!r}'s; nothing written")
    single = plan.resolve() == context.resolve()
    plan_doc = Doc(plan)
    ctx_doc = plan_doc if single else Doc(context)
    applied, skipped = [], []
    for entry in record["rounds"]:
        n = int(entry.get("round", 0))
        if log_has(ctx_doc, run_id, n):
            skipped.append(n)
            continue
        # State first: merging it again is harmless, so a crash between the
        # two writes leaves a run that the next apply completes.
        apply_state(plan_doc, f"{entry.get('stateLines') or ''}\nlast run: {run_id}")
        plan_doc.write()
        append_log(ctx_doc, run_id, n, entry.get("logBlock") or "")
        ctx_doc.write()
        applied.append(n)
    done = ", ".join(map(str, applied)) or "none"
    present = f"; already present: {', '.join(map(str, skipped))}" if skipped else ""
    where = str(plan) if single else f"{plan} + {context}"
    print(f"workorder_record: {slug} {run_id}: applied round(s) {done}{present} -> {where}")
    for line in summary(result, data):
        print(line)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="workorder_record.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("apply", help="write a launch's State and Log from its run record")
    which = a.add_mutually_exclusive_group(required=True)
    which.add_argument("--run", help="a run id (wf_<id> or <id>) or a path to its wf_<id>.json")
    which.add_argument("--latest", action="store_true", help="the newest saved run of --slug's workorder")
    a.add_argument("--project-dir", help="the ~/.claude/projects/<project> directory to search")
    a.add_argument("--slug", help="refuse unless the record is this workorder's")
    args = p.parse_args(argv)
    try:
        return apply(args)
    except Fail as exc:
        print(f"workorder_record: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
