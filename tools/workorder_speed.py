#!/usr/bin/env python3
"""Where a /workorder session's wall time went: a re-runnable speed report.

`tools/workorder_audit.py` answers "did one session break a rule". This
answers "where did the time go", for one session or many, from paths it is
given, so the same figures can be compared across a baseline and a later
batch. It reuses the audit's parser and discovery (`parse_transcript`,
`discover_session`) and opens files for reading only.

Usage:
    py -3 tools/workorder_speed.py --transcript <driver .jsonl> [--transcript ...]
        [--project-dir <dir> ...] [--plan <plan.md>] [--until <UTC>] [--json]

- `--transcript` names one driver transcript. Its subagents are read from the
  sibling `<stem>/subagents/` directory and its launch records from
  `<stem>/workflows/wf_*.json`.
- `--project-dir` reads every `*.jsonl` in the directory that has at least
  one subagent with a record (the rule the 2026-09-27 study used).
- `--plan` adds a `plan` block: the plan's `owner:` items, and how many of
  them carry `default:` and `reversible:`.
- `--until` ignores every timestamped record after that UTC time, so a
  snapshot of a session that was still running can be reproduced once it has
  finished: pass the snapshot's time and the same paths.

Exit code: 0 when the report was produced, 2 on a usage error (an unreadable
path, or nothing to read).

What each figure means (every session entry and `aggregate` carry them; the
aggregate sums the minutes and divides the sums):

- `span_minutes`: first to last event of the driver or any subagent.
- `busy_minutes`: the span less every gap of 2 hours or more with no agent
  running (the owner away, a session left open).
- `serial_minutes`: the subagents' wall minutes added up.
- `concurrency`: serial / busy. Under 1 means agents ran less than the whole
  busy time; above 1 means they overlapped.
- `single_agent_share`, `parallel_share`: the share of busy time with exactly
  one agent running, and with two or more.
- `phases`: per phase (`plan`, `amend`, `replan`, `implement`, `verify`,
  `review`, `record`, `live`, `consult`, `other`) the `agents`, their
  `agent_minutes` and `sole_minutes` (time that phase's agent was the only
  one running). `waits` splits the time with no agent running by what ended
  the gap: `driver working`, `waiting human`, `waiting other session`,
  `waiting CI/PR review`, `bg task (non-agent)`, `idle (turn ended, no
  agent)`, `driver shell`, `driver tool:<name>`; `[>2h]` marks the gaps
  `busy_minutes` leaves out.
- `launches`: one per workflow run. An items launch adds its item windows:
  `max_concurrent`, `minutes_at_cap`, `queued_behind_cap`, `cap`,
  `gate_runs` and `finding_to_fix_minutes`.
- `items`: the most item windows running at once, and the item starts that
  waited on `maxParallel`, over all launches.
- `verifies`: `item` (an `item-verifier:`), `reach` (another verifier whose
  prompt carries `--changed-since`), `full` (the rest).
- `run_criteria`: shell calls naming `run_criteria`, how many the harness
  killed (595 s or longer, or stopped at its limit), the longest, and the
  longest `--item` call.
- `owner_blocks`: gaps of 120 s or more in the driver's records, with no
  subagent running at their midpoint, ended by a message the owner typed or
  an `AskUserQuestion` answer.
- `implementer_checks`: implementers, those that ran a check (a test run or
  `run_criteria`), and those whose check failed and who then edited
  (`caught`); `rate` is caught / ran_check.
- `routes`: amendment planners (and how many ran inside a workflow),
  replans, consultations.
- `lanes`: `workorder_audit.lane_summary` per session.
- `workorder_reads` (2026-10-03): per role (`agent_type`), its `agents` and,
  for what they read of the workorder's own files, a `<kind>_calls` and a
  `<kind>_kb` (result bytes / 1024) per kind. `plan` is a `Read` of a path
  ending `-plan.md`, or a shell call whose command names one; a command that
  runs `run_criteria.py`, `plan_lint.py`, `amend_check.py`, `live_checks.py`,
  `item_commit.py` or `workorder_brief.py`, or `git add`/`git commit`, is not
  a read of it. `context` is the same for `-context.md`. `brief` is a shell
  call that runs `workorder_brief.py`. `report` is a `Read` of a path ending
  `report.txt`, or a `cat`, `type` or `Get-Content` of one. The text format
  prints the implementer's and the verifier's rows: the pre-sliced brief and
  `run_criteria.py --digest` are meant to move them.

Story and the definitions' reasons: docs/agents/workorder-calibration.md
§ "Measuring where the pipeline spends its time (2026-09-27)".
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import workorder_audit as wa  # noqa: E402

AWAY_SECONDS = 2 * 3600       # a no-agent gap this long is the owner away, not busy time
GAP_SECONDS = 120             # a shorter gap between driver records is the driver working
KILLED_SECONDS = 595          # a run_criteria call this long hit the 10-minute Bash limit
QUEUE_WINDOW_SECONDS = 5      # a start this soon after another item's end took its slot
DEFAULT_CAP = 4               # the engine's DEFAULT_MAX_PARALLEL when a launch passes none
TOP_OWNER_BLOCKS = 5

PHASES = ("plan", "amend", "replan", "implement", "verify", "review", "record", "live", "consult", "other")
REPLAN_RE = re.compile(r"replan|rescope|split", re.I)
RECORD_HEADS = ("snapshot", "delta", "scribe", "refill", "amend-save", "amend-check", "amend-restore", "items")
ITEM_AGENT_RE = re.compile(r"^(item-implementer|fix-implementer|item-verifier):([^:]+):")
FINDING_FIX_RE = re.compile(r"^fix-implementer:fix-\d+:")
REVIEW_PASS_RE = re.compile(r":p\d+:r\d+$")
CHECK_CMD_RE = re.compile(r"run_criteria|unittest|pytest|npm test|npm run|node --test|run_tests_parallel")
ITEM_HEADING_RE = re.compile(r"^###\s+Item:\s*([A-Za-z0-9_-]+)")
ITEM_FIELD_RE = re.compile(r"^\s*(?:[-*]\s+)?\**(owner|default|reversible):\**\s*(.*)$", re.I)
NUMBERED_STEP_RE = re.compile(r"^\s*\d+\.\s")

PARALLEL = "parallel(>=2 agents)"
SINGLE = "single agent"


class UsageError(Exception):
    pass


def _minutes(seconds: float) -> float:
    return seconds / 60.0


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if t else None


def parse_until(text: str) -> datetime:
    try:
        t = wa.parse_ts(text)
    except ValueError:
        raise UsageError(f"--until is not an ISO time: {text!r}")
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

@dataclass
class Loaded:
    path: Path
    session: wa.Session
    subs: list        # subagents with at least one record, all of them
    raw: list         # (ts, record) of the driver transcript, sorted by time
    launch_files: dict  # workflow id -> the launch's wf_*.json, parsed


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load(path: Path, until: Optional[datetime]) -> Loaded:
    session = wa.discover_session(path.parent.parent, path.parent.name, path.stem, path, until=until)
    # A subagent that began after `until` is listed with no records: drop it
    # everywhere, the lane summary included.
    session.subagents = [a for a in session.subagents if a.ts_first]
    session.workflow_runs = {k: [a for a in v if a.ts_first] for k, v in session.workflow_runs.items()}
    session.workflow_runs = {k: v for k, v in session.workflow_runs.items() if v}
    # The harness can later copy a launch's agent transcript up into
    # `subagents/` under the same file name and without its meta file; the
    # launch's copy is the one with a label, so the other is not an agent.
    in_launch = {a.path.name for v in session.workflow_runs.values() for a in v}
    session.subagents = [a for a in session.subagents if a.path.name not in in_launch]
    raw = []
    for rec in wa.iter_jsonl(path):
        ts_raw = rec.get("timestamp")
        if not ts_raw:
            continue
        t = wa.parse_ts(ts_raw)
        if until is None or t <= until:
            raw.append((t, rec))
    raw.sort(key=lambda x: x[0])
    launch_files = {}
    wf_dir = path.parent / path.stem / "workflows"
    for wf_id in session.workflow_runs:
        data = _read_json(wf_dir / f"{wf_id}.json")
        if isinstance(data, dict):
            launch_files[wf_id] = data
    return Loaded(path=path, session=session, subs=wa.all_subagents(session), raw=raw, launch_files=launch_files)


def sessions_in(project_dir: Path, until: Optional[datetime]) -> list:
    """Every session in `project_dir` with at least one subagent that has a
    record at or before `until`."""
    out = []
    for p in sorted(project_dir.glob("*.jsonl")):
        if not (project_dir / p.stem / "subagents").is_dir():
            continue
        loaded = load(p, until)
        if loaded.subs:
            out.append(loaded)
    return out


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

def phase_of(agent: wa.AgentTranscript) -> str:
    t = agent.agent_type
    label = (agent.label or "").strip()
    if t == "planner":
        if wa.is_amendment(agent):
            return "amend"
        return "replan" if REPLAN_RE.search(label) else "plan"
    if t == "implementer":
        return "implement"
    if t == "verifier":
        return "verify"
    if t in wa.REVIEWER_TYPES:
        return "review"
    if t == "scribe":
        return "record"
    if t == "live-operator":
        return "live"
    if t == "consultant":
        return "consult"
    head = label.lower().split(":")[0].strip()
    if t == "workflow-subagent" and head.startswith(RECORD_HEADS):
        return "record"
    return "other"


def gap_kind(prev: dict, rec: dict, gap: float, callname: dict) -> str:
    """What a gap between two consecutive driver records was spent on, named
    by the record that ended it. The categories are the 2026-09-27 study's."""
    if gap < GAP_SECONDS:
        return "driver working"
    kind = "driver working"
    rec_type = rec.get("type")
    if rec_type == "queue-operation":
        c = rec.get("content")
        c = c if isinstance(c, str) else ""
        if c.startswith("<task-notification"):
            kind = "bg task (non-agent)" if "Agent" not in c[:600] else "driver working"
        elif c.startswith("<cross-session") or c.startswith("<agent-message"):
            kind = "waiting other session"
        elif c.startswith("<ci-monitor"):
            kind = "waiting CI/PR review"
        elif c.startswith("<"):
            kind = "idle (turn ended, no agent)" if prev.get("type") == "system" else "driver working"
        elif c:
            kind = "waiting human"
    elif rec_type == "user":
        c = (rec.get("message") or {}).get("content")
        if isinstance(c, list) and c and isinstance(c[0], dict) and c[0].get("type") == "tool_result":
            name = callname.get(c[0].get("tool_use_id"), "?")
            if name == "AskUserQuestion":
                kind = "waiting human"
            elif name in wa.SHELL_TOOLS:
                kind = "driver shell"
            else:
                kind = "driver tool:" + name
        else:
            kind = "waiting human"
    if gap >= AWAY_SECONDS and kind != "driver working":
        kind += " [>2h]"
    return kind


def _running_at(intervals: list, t: datetime) -> bool:
    return any(a <= t < b for a, b in intervals)


# --------------------------------------------------------------------------
# One session
# --------------------------------------------------------------------------

def timeline(ld: Loaded) -> dict:
    """Span, busy and serial time, the shares, per-phase minutes and the
    no-agent waits, following the study's method: cut the session at every
    event, and classify each piece by how many agents run at its midpoint."""
    d = ld.session.driver
    ivs = [(a.ts_first, a.ts_last, a) for a in ld.subs if a.ts_first and a.ts_last]
    drv_ts = [t for t in [d.ts_first, d.ts_last]
              + [c.ts_start for c in d.tool_calls] + [c.ts_end for c in d.tool_calls]
              + [u.ts for u in d.turns.values()] if t]
    human = [t for t, _ in d.human_messages]
    bounds = [t for t in [d.ts_first, d.ts_last] if t] + [x for i in ivs for x in i[:2]]
    t0, t1 = min(bounds), max(bounds)
    pts = sorted(set([t0, t1] + [x for i in ivs for x in i[:2]] + drv_ts + human))

    callname = {c.tool_use_id: c.name for c in d.tool_calls}
    gaps = []
    for (ta, ra), (tb, rb) in zip(ld.raw, ld.raw[1:]):
        g = (tb - ta).total_seconds()
        if g > 0:
            gaps.append((ta, tb, gap_kind(ra, rb, g, callname)))
    gap_starts = [g[0] for g in gaps]

    starts_at, ends_at = defaultdict(list), defaultdict(list)
    for i, (a, b, _) in enumerate(ivs):
        starts_at[a].append(i)
        ends_at[b].append(i)

    cat = defaultdict(float)
    sole = defaultdict(float)
    active: set = set()
    for a_, b_ in zip(pts, pts[1:]):
        active.update(starts_at.get(a_, ()))
        active.difference_update(ends_at.get(a_, ()))
        dur = (b_ - a_).total_seconds()
        if dur <= 0:
            continue
        if len(active) >= 2:
            cat[PARALLEL] += dur
        elif len(active) == 1:
            cat[SINGLE] += dur
            sole[phase_of(ivs[next(iter(active))][2])] += dur
        else:
            mid = a_ + (b_ - a_) / 2
            i = bisect.bisect_right(gap_starts, mid) - 1
            kind = gaps[i][2] if 0 <= i < len(gaps) and gaps[i][0] <= mid < gaps[i][1] else "driver working"
            cat[kind] += dur

    span = (t1 - t0).total_seconds()
    busy = sum(v for k, v in cat.items() if "[>2h]" not in k)
    serial = sum((b - a).total_seconds() for a, b, _ in ivs)

    phases = {p: {"agents": 0, "agent_minutes": 0.0, "sole_minutes": 0.0} for p in PHASES}
    for a, b, agent in ivs:
        p = phases[phase_of(agent)]
        p["agents"] += 1
        p["agent_minutes"] += _minutes((b - a).total_seconds())
    for p, secs in sole.items():
        phases[p]["sole_minutes"] += _minutes(secs)
    phases["waits"] = {k: _minutes(v) for k, v in sorted(cat.items(), key=lambda kv: -kv[1])
                       if k not in (PARALLEL, SINGLE)}

    agent_ranges = [(a, b) for a, b, _ in ivs]
    blocks = []
    for (ta, ra), (tb, rb) in zip(ld.raw, ld.raw[1:]):
        g = (tb - ta).total_seconds()
        if g < GAP_SECONDS or not gap_kind(ra, rb, g, callname).startswith("waiting human"):
            continue
        if _running_at(agent_ranges, ta + (tb - ta) / 2):
            continue
        blocks.append(g)

    return {
        "t0": t0, "t1": t1,
        "span": span, "busy": busy, "serial": serial,
        "single": cat[SINGLE], "parallel": cat[PARALLEL],
        "phases": phases,
        "owner_blocks": blocks,
    }


def item_windows(agents: list) -> list:
    """(start, end, key) per item of one launch: from the first start of its
    implementers (fixes are items to the scheduler too) to the last end of
    those or of its item verifier."""
    starts, ends = {}, {}
    for a in agents:
        m = ITEM_AGENT_RE.match(a.label or "")
        if not m or not a.ts_first:
            continue
        key = ("fix" if m.group(1) == "fix-implementer" else "item", m.group(2))
        if m.group(1) != "item-verifier":
            starts[key] = min(starts.get(key, a.ts_first), a.ts_first)
        ends[key] = max(ends.get(key, a.ts_last), a.ts_last)
    return sorted((starts[k], max(ends[k], starts[k]), k) for k in starts)


def window_stats(windows: list, cap: int) -> dict:
    events = sorted([(s, 1) for s, _, _ in windows] + [(e, -1) for _, e, _ in windows],
                    key=lambda x: (x[0], x[1]))
    running, peak, at_cap, prev = 0, 0, 0.0, None
    for t, step in events:
        if prev is not None and running >= cap:
            at_cap += (t - prev).total_seconds()
        running += step
        peak = max(peak, running)
        prev = t

    def running_before(t: datetime) -> int:
        return sum(1 for s, e, _ in windows if s < t <= e)

    queued = 0
    for s, _, key in windows:
        for s2, e2, key2 in windows:
            if key2 == key:
                continue
            if 0 <= (s - e2).total_seconds() <= QUEUE_WINDOW_SECONDS and running_before(e2) >= cap:
                queued += 1
                break
    return {"max_concurrent": peak, "minutes_at_cap": _minutes(at_cap), "queued_behind_cap": queued}


def launches(ld: Loaded) -> list:
    out = []
    for wf_id, agents in sorted(ld.session.workflow_runs.items()):
        meta = ld.launch_files.get(wf_id) or {}
        args = meta.get("args") if isinstance(meta.get("args"), dict) else {}
        start = min(a.ts_first for a in agents)
        end = max(a.ts_last for a in agents)
        entry = {
            "id": wf_id,
            "workflow": meta.get("workflowName"),
            "slug": args.get("slug"),
            "round": args.get("round"),
            "span_minutes": _minutes((end - start).total_seconds()),
            "agents": len(agents),
            "implementer_minutes": sum(a.wall_minutes for a in agents if a.agent_type == "implementer"),
        }
        windows = item_windows(agents)
        if windows or args.get("items"):
            cap = args.get("maxParallel")
            cap = cap if isinstance(cap, int) and cap >= 1 else DEFAULT_CAP
            entry.update({
                "items": len({k for _, _, k in windows if k[0] == "item"}),
                "cap": cap,
                **window_stats(windows, cap),
                "gate_runs": sum(1 for a in agents if a.agent_type == "verifier"
                                 and not (a.label or "").startswith("item-verifier:")),
                "finding_to_fix_minutes": finding_to_fix(agents),
            })
        out.append(entry)
    return out


def finding_to_fix(agents: list) -> list:
    passes = sorted(a.ts_last for a in agents
                    if a.agent_type in wa.REVIEWER_TYPES and REVIEW_PASS_RE.search(a.label or ""))
    out = []
    for a in sorted((a for a in agents if FINDING_FIX_RE.match(a.label or "")), key=lambda a: a.ts_first):
        i = bisect.bisect_right(passes, a.ts_first) - 1
        if i >= 0:
            out.append(_minutes((a.ts_first - passes[i]).total_seconds()))
    return out


def verifies(subs: list) -> dict:
    out = {"full": 0, "reach": 0, "item": 0}
    for a in subs:
        if a.agent_type != "verifier":
            continue
        if (a.label or "").startswith("item-verifier:"):
            out["item"] += 1
        elif "--changed-since" in (a.first_prompt or ""):
            out["reach"] += 1
        else:
            out["full"] += 1
    return out


def run_criteria(agents: list) -> dict:
    calls = killed = 0
    longest = item_longest = 0.0
    for a in agents:
        for c in a.tool_calls:
            if c.name not in wa.SHELL_TOOLS:
                continue
            cmd = c.tool_input.get("command") or ""
            if "run_criteria" not in cmd:
                continue
            calls += 1
            secs = c.duration_seconds or 0.0
            if secs >= KILLED_SECONDS or c.timed_out:
                killed += 1
            longest = max(longest, secs)
            if "--item" in cmd:
                item_longest = max(item_longest, secs)
    return {"calls": calls, "killed": killed, "max_seconds": longest, "item_max_seconds": item_longest}


def implementer_checks(subs: list) -> dict:
    implementers = ran = caught = 0
    for a in subs:
        if a.agent_type != "implementer":
            continue
        implementers += 1
        failed_at = None
        checked = got = False
        for i, c in enumerate(a.tool_calls):
            if c.name in wa.SHELL_TOOLS and CHECK_CMD_RE.search(c.tool_input.get("command") or ""):
                checked = True
                if failed_at is None and (c.is_error or c.failure_marker):
                    failed_at = i
            elif c.name in wa.EDIT_TOOLS and failed_at is not None and i > failed_at:
                got = True
        ran += checked
        caught += got
    return {"implementers": implementers, "ran_check": ran, "caught": caught,
            "rate": (caught / ran) if ran else None}


def routes(subs: list) -> dict:
    planners = [a for a in subs if a.agent_type == "planner"]
    amends = [a for a in planners if wa.is_amendment(a)]
    return {
        "amendments": len(amends),
        "amendments_in_workflow": sum(1 for a in amends if a.workflow_id),
        "replans": sum(1 for a in planners if not wa.is_amendment(a) and REPLAN_RE.search(a.label or "")),
        "consultations": sum(1 for a in subs if a.agent_type == "consultant"),
    }


PLAN_PATH_RE = re.compile(r"-plan\.md(?![\w.-])", re.I)
CONTEXT_PATH_RE = re.compile(r"-context\.md(?![\w.-])", re.I)
BRIEF_CMD_RE = re.compile(r"workorder_brief\.py\b")
# A tool that takes the plan as its argument and prints something else, and a
# git write that names it, are not reads of the plan.
NOT_A_READ_RE = re.compile(r"\b(?:run_criteria|plan_lint|amend_check|live_checks|item_commit|workorder_brief)\.py\b"
                           r"|\bgit\s+(?:-C\s+\S+\s+)?(?:add|commit)\b")
REPORT_SHELL_RE = re.compile(r"(?:^|[\s;&|(])(?:cat|type|Get-Content|gc)\s+[^|;&]*report\.txt\b", re.I)
READ_KINDS = ("plan", "context", "brief", "report")


def _empty_reads() -> dict:
    return {"agents": 0, **{f"{k}_{f}": 0.0 if f == "kb" else 0 for k in READ_KINDS for f in ("calls", "kb")}}


def read_kinds(call) -> list:
    """Which of the workorder's own files a tool call read: `plan`,
    `context`, `brief` (a `workorder_brief.py` run) or `report` (a criteria
    run's `report.txt`, read whole). A shell call naming both the plan and
    the context counts under both."""
    if call.name == "Read":
        path = str((call.tool_input or {}).get("file_path") or "").replace("\\", "/").lower()
        if path.endswith("-plan.md"):
            return ["plan"]
        if path.endswith("-context.md"):
            return ["context"]
        return ["report"] if path.endswith("report.txt") else []
    if call.name not in wa.SHELL_TOOLS:
        return []
    cmd = str((call.tool_input or {}).get("command") or "")
    if BRIEF_CMD_RE.search(cmd):
        return ["brief"]
    kinds = []
    if not NOT_A_READ_RE.search(cmd):
        kinds += ["plan"] if PLAN_PATH_RE.search(cmd) else []
        kinds += ["context"] if CONTEXT_PATH_RE.search(cmd) else []
    if REPORT_SHELL_RE.search(cmd):
        kinds.append("report")
    return kinds


def workorder_reads(subs: list) -> dict:
    """Per role (`agent_type`): its agents, and for each kind in
    `READ_KINDS` the calls that read it and their result KB."""
    out: dict = {}
    for a in subs:
        row = out.setdefault(a.agent_type, _empty_reads())
        row["agents"] += 1
        for c in a.tool_calls:
            for kind in read_kinds(c):
                row[f"{kind}_calls"] += 1
                row[f"{kind}_kb"] += c.result_bytes / 1024.0
    return dict(sorted(out.items()))


def owner_block_summary(blocks: list) -> dict:
    return {
        "count": len(blocks),
        "total_minutes": _minutes(sum(blocks)),
        "top": [_minutes(b) for b in sorted(blocks, reverse=True)[:TOP_OWNER_BLOCKS]],
        "over_2h_minutes": _minutes(sum(b for b in blocks if b >= AWAY_SECONDS)),
    }


def session_report(ld: Loaded) -> dict:
    tl = timeline(ld)
    runs = launches(ld)
    items_runs = [r for r in runs if "max_concurrent" in r]
    return {
        "path": str(ld.path),
        "session": ld.session.session_id,
        "first_event": _iso(tl["t0"]),
        "last_event": _iso(tl["t1"]),
        "_raw": tl,  # unrounded, for the aggregate; dropped before printing
        "span_minutes": _minutes(tl["span"]),
        "busy_minutes": _minutes(tl["busy"]),
        "serial_minutes": _minutes(tl["serial"]),
        "concurrency": tl["serial"] / tl["busy"] if tl["busy"] else 0.0,
        "single_agent_share": tl["single"] / tl["busy"] if tl["busy"] else 0.0,
        "parallel_share": tl["parallel"] / tl["busy"] if tl["busy"] else 0.0,
        "phases": tl["phases"],
        "launches": runs,
        "items": {"max_concurrent": max((r["max_concurrent"] for r in items_runs), default=0),
                  "queued_behind_cap": sum(r["queued_behind_cap"] for r in items_runs)},
        "verifies": verifies(ld.subs),
        "run_criteria": run_criteria(ld.subs + [ld.session.driver]),
        "owner_blocks": owner_block_summary(tl["owner_blocks"]),
        "implementer_checks": implementer_checks(ld.subs),
        "routes": routes(ld.subs),
        "lanes": wa.lane_summary(ld.session),
        "workorder_reads": workorder_reads(ld.subs),
    }


# --------------------------------------------------------------------------
# Aggregate and output
# --------------------------------------------------------------------------

def aggregate(entries: list) -> dict:
    span = sum(e["_raw"]["span"] for e in entries)
    busy = sum(e["_raw"]["busy"] for e in entries)
    serial = sum(e["_raw"]["serial"] for e in entries)
    single = sum(e["_raw"]["single"] for e in entries)
    parallel = sum(e["_raw"]["parallel"] for e in entries)
    phases = {p: {"agents": 0, "agent_minutes": 0.0, "sole_minutes": 0.0} for p in PHASES}
    waits = defaultdict(float)
    for e in entries:
        for p in PHASES:
            for k in phases[p]:
                phases[p][k] += e["phases"][p][k]
        for k, v in e["phases"]["waits"].items():
            waits[k] += v
    phases["waits"] = dict(sorted(waits.items(), key=lambda kv: -kv[1]))

    def total(block: str, key: str):
        return sum(e[block][key] for e in entries)

    ran = total("implementer_checks", "ran_check")
    caught = total("implementer_checks", "caught")
    reads: dict = {}
    for e in entries:
        for role, row in e["workorder_reads"].items():
            summed = reads.setdefault(role, _empty_reads())
            for k, v in row.items():
                summed[k] += v
    return {
        "sessions": len(entries),
        "span_minutes": _minutes(span),
        "busy_minutes": _minutes(busy),
        "serial_minutes": _minutes(serial),
        "concurrency": serial / busy if busy else 0.0,
        "single_agent_share": single / busy if busy else 0.0,
        "parallel_share": parallel / busy if busy else 0.0,
        "phases": phases,
        "launches": [dict(r, session=e["session"]) for e in entries for r in e["launches"]],
        "items": {"max_concurrent": max((e["items"]["max_concurrent"] for e in entries), default=0),
                  "queued_behind_cap": total("items", "queued_behind_cap")},
        "verifies": {k: total("verifies", k) for k in ("full", "reach", "item")},
        "run_criteria": {
            "calls": total("run_criteria", "calls"),
            "killed": total("run_criteria", "killed"),
            "max_seconds": max((e["run_criteria"]["max_seconds"] for e in entries), default=0.0),
            "item_max_seconds": max((e["run_criteria"]["item_max_seconds"] for e in entries), default=0.0),
        },
        "owner_blocks": {
            "count": total("owner_blocks", "count"),
            "total_minutes": total("owner_blocks", "total_minutes"),
            "top": sorted((t for e in entries for t in e["owner_blocks"]["top"]), reverse=True)[:TOP_OWNER_BLOCKS],
            "over_2h_minutes": total("owner_blocks", "over_2h_minutes"),
        },
        "implementer_checks": {"implementers": total("implementer_checks", "implementers"),
                               "ran_check": ran, "caught": caught, "rate": (caught / ran) if ran else None},
        "routes": {k: total("routes", k) for k in ("amendments", "amendments_in_workflow", "replans", "consultations")},
        "lanes": {e["session"]: e["lanes"] for e in entries if e["lanes"]},
        "workorder_reads": dict(sorted(reads.items())),
    }


def plan_block(path: Path) -> dict:
    """The plan's `### Item:` blocks with an `owner:` line, and how many of
    them also carry `default:` (non-empty) and `reversible:`."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UsageError(f"cannot read --plan {path}: {exc}")
    items, current, in_steps = [], None, False
    for line in text.splitlines():
        if line.startswith("## "):
            in_steps = line.strip().lower() == "## steps"
            current = None
            continue
        if not in_steps:
            continue
        m = ITEM_HEADING_RE.match(line)
        if m:
            current = {"id": m.group(1), "fields": {}, "open": True}
            items.append(current)
            continue
        if line.startswith("### "):
            current = None
            continue
        if current is None or not current["open"]:
            continue
        if NUMBERED_STEP_RE.match(line):
            current["open"] = False
            continue
        f = ITEM_FIELD_RE.match(line)
        if f:
            current["fields"].setdefault(f.group(1).lower(), f.group(2).strip())
    owned = [i for i in items if i["fields"].get("owner")]
    return {
        "path": str(path),
        "items": len(items),
        "owner_items": len(owned),
        "with_default": sum(1 for i in owned if i["fields"].get("default")),
        "with_reversible": sum(1 for i in owned if i["fields"].get("reversible")),
    }


def _rounded(obj):
    """Ratios and short times to 3 decimals, minutes of 10 or more to 1; the
    unrounded `_raw` timeline each session carries for the aggregate is dropped."""
    if isinstance(obj, float):
        return round(obj, 3 if abs(obj) < 10 else 1)
    if isinstance(obj, dict):
        return {k: _rounded(v) for k, v in obj.items() if k != "_raw"}
    if isinstance(obj, list):
        return [_rounded(v) for v in obj]
    return obj


def build(transcripts: list, project_dirs: list, until: Optional[datetime], plan: Optional[Path]) -> dict:
    loaded = []
    for t in transcripts:
        if not t.is_file():
            raise UsageError(f"no such transcript: {t}")
        ld = load(t, until)
        if ld.session.driver.ts_first or ld.subs:
            loaded.append(ld)
    for p in project_dirs:
        if not p.is_dir():
            raise UsageError(f"no such project directory: {p}")
        loaded.extend(sessions_in(p, until))
    if not loaded:
        raise UsageError("nothing to read: no session with records" + (" before --until" if until else ""))
    entries = [session_report(ld) for ld in loaded]
    report = {
        "generated_utc": _iso(datetime.now(timezone.utc)),
        "until": _iso(until),
        "sessions": entries,
        "aggregate": aggregate(entries),
    }
    if plan is not None:
        report["plan"] = plan_block(plan)
    return _rounded(report)


def format_text(report: dict) -> str:
    def line(name: str, r: dict) -> list:
        ph = r["phases"]
        out = [
            f"{name}",
            f"  span {r['span_minutes']} min, busy {r['busy_minutes']} min, agents {r['serial_minutes']} min, "
            f"concurrency {r['concurrency']}, one agent {r['single_agent_share']}, two or more {r['parallel_share']}",
            "  phases (agents / agent min / sole min): " + ", ".join(
                f"{p} {ph[p]['agents']}/{ph[p]['agent_minutes']}/{ph[p]['sole_minutes']}"
                for p in PHASES if ph[p]["agents"]),
            f"  items: most at once {r['items']['max_concurrent']}, starts queued behind the cap "
            f"{r['items']['queued_behind_cap']}; verifies {r['verifies']}",
            f"  run_criteria: {r['run_criteria']}",
            f"  owner blocks: {r['owner_blocks']}",
            f"  implementer checks: {r['implementer_checks']}; routes: {r['routes']}",
            "  workorder reads (calls/KB): " + ("; ".join(
                f"{role} ({row['agents']} agents): "
                + ", ".join(f"{k} {row[f'{k}_calls']}/{row[f'{k}_kb']}" for k in READ_KINDS)
                for role in ("implementer", "verifier") for row in [r["workorder_reads"].get(role)] if row)
                or "no implementer or verifier"),
        ]
        return out
    lines = [f"workorder speed report, until {report['until'] or 'the end'}"]
    for s in report["sessions"]:
        lines += line(f"session {s['session']} ({s['first_event']} .. {s['last_event']})", s)
    lines += line(f"aggregate over {report['aggregate']['sessions']} session(s)", report["aggregate"])
    if "plan" in report:
        lines.append(f"plan: {report['plan']}")
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Where a /workorder session's wall time went")
    ap.add_argument("--transcript", action="append", default=[], type=Path,
                    help="a driver transcript (.jsonl); may be repeated")
    ap.add_argument("--project-dir", action="append", default=[], type=Path,
                    help="read every session in this directory that has a subagent; may be repeated")
    ap.add_argument("--plan", type=Path, help="add the plan's owner-item counts")
    ap.add_argument("--until", help="ignore every record after this UTC time (ISO 8601)")
    ap.add_argument("--json", action="store_true", help="emit one JSON object")
    args = ap.parse_args(argv)
    try:
        if not args.transcript and not args.project_dir:
            raise UsageError("give at least one --transcript or --project-dir")
        until = parse_until(args.until) if args.until else None
        report = build(args.transcript, args.project_dir, until, args.plan)
    except UsageError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        json.dump(report, sys.stdout, indent=1)
        sys.stdout.write("\n")
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
