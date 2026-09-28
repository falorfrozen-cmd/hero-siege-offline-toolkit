#!/usr/bin/env python3
"""Run a `/workorder` plan's command-shaped acceptance criteria in one call,
so the verifier judges from their output instead of spending a model turn on
each command.

Measured 2026-09-25 over 124 verifiers: a median verifier took 7.6 minutes
and 38 tool calls, and about a third of verifier wall time (346 of 1,042
minutes) went on the model's turns between commands rather than on the
commands themselves. The commands still run -- this does not cache, skip or
share a result with the implementer (docs/agents/workorder-calibration.md
explains why a shared result was rejected). It only runs them back to back,
in the verifier's own call, and prints what they printed.

It judges nothing. For each criterion it prints the commands it ran, each
one's exit code and elapsed time, and the tail of its output; the full output
of each command goes to `<out>/cmd-<n>.log`. Whether "prints `ok`" or "lists
at least one commit" holds is still the verifier's call, and so is every
criterion with no command in it (`criterion <k>: no command -- check by
reading`).

  * A command is a backticked span whose first word is a command (`py`,
    `git`, `grep`, `node`, `npm`, `cd`, a `.bat`/`.ps1`/`.sh` path, ...).
    Expected output (`ok`), paths and gate tokens are not commands.
    Multi-line spans (`py -3 -c "` scripts) keep their newlines.
  * Commands run exactly as written, in bash (Git Bash on Windows, as the
    verifier's own Bash tool does), from the checkout root the plan lives in.
    A command that runs twice in the plan runs once and is reported under
    both criteria.
  * A criterion carrying `(gate `<token>`)` whose token is not on the plan's
    `## State` `gates:` line is not run: `SKIPPED (gate <token> not set)`.
    A `gates:` value with `|`, `<placeholder>` or "or" alternatives is a
    template and sets nothing -- the same reading as `workorder-rounds.js`.

`--jobs N` (or `--jobs auto`, min(8, CPUs)) runs independent commands at the
same time. The report is unchanged: criteria print in plan order, each once
every command in it has finished, and `cmd-<n>.log` numbers follow plan
order, so the verifier reads exactly what a serial run prints. What may run
beside what is decided by each command's resource class:

  build      builds first, one at a time, before anything else starts: the
             suites read what they write (ForgePact's e2e suites all serve
             the one `panel/dist`, which a Vite build empties and rewrites).
             Also held under the checkout's `build` lock, so two items'
             checks never build at once (`tools/workorder_lock.py`).
  suite      a whole test suite that already uses every core
             (`run_tests_parallel.py`, `unittest discover`, a bare `pytest`):
             at most one at a time.
  browser    a browser suite (`e2e`, `playwright`): at most `--browser-jobs`
             (default 2) at once, across every process in the checkout.
             Measured 2026-09-26 on ForgePact's panel suites: each binds an
             OS-assigned port (re-bound off Chromium's restricted ports), its
             own temp config and its own browser profile, and none builds.
  test       a targeted test (`-m unittest tests.x`, `node --test`, `npm
             test`): up to `--jobs`.
  pure       a read of files or git (`grep`, `git log`, `py -3 -c`, ...): up
             to `--jobs`.
  exclusive  a barrier at its place in the plan: it runs alone, once
             everything before it is done, and nothing after it starts until
             it is done. A timing benchmark (`e2e:perf`, whose frame budgets a
             loaded machine fails), anything that drives the oracle replay (it
             runs `e2e:perf` inside), and any command no rule above
             recognises -- which may write what a later criterion reads.

A criterion can say what it is: `(class build)` (or `suite`, `browser`,
`test`, `pure`, `exclusive`) sets the class of every command in it, and
`(after 3)` or `(after 3, 5)` holds its commands until criteria 3 and 5 have
run. A command two criteria share runs once, with the stricter class.

`--item ID` runs one streamed-plan item's `checks:` (under `### Item: ID` in
`## Steps`, read by `tools/plan_lint.py`) instead of `## Acceptance
criteria`, numbered from 1 -- the targeted checks `workorder-rounds.js` has
the verifier run as an item finishes.

`--changed-since REF` (2026-09-27) runs only the criteria a change can
reach, for a fix round after a verify that passed every other criterion. The
owner, in the ForgePact UI redesign's ship workorder: "run relevant tests
only if possible". What changed is `git diff --name-only REF` (committed and
uncommitted) plus untracked files, in the hub and in every initialized
submodule, submodule paths under their directory. A submodule's base is the
commit the hub's REF records for it, unless `--changed-since DIR=REF` names
one (the round's own heads, from `round_delta.py heads`). `--changed-from
FILE` reads the changed paths from a file instead (`round_delta.py delta`'s
output; `-` is stdin). A criterion is selected when:

  * it failed last time: `--failed K[,K...]`, the plan numbers the previous
    verify reported as failed;
  * a changed path matches a glob its `(reads `<glob>`, ...)` declares
    (`tools/plan_lint.py` warns on a criterion without one);
  * it declares no `(reads ...)`: an unmapped criterion runs on every fix
    round, so an old plan verifies fully;
  * a selected criterion runs `(after K)` it: criterion K is selected too.

Every criterion runs, as without the flag, when the delta is unknown (a base
git cannot diff from, a submodule with no base, an unreadable
`--changed-from` file) or a changed path is a shared contract: a glob in
`SHARED_CONTRACT` below, or on the plan's `## State` `shared contract:` line.
Before anything runs it prints the scope: the changed paths, then each
criterion as `run` or `skip` with the reason; `scope: full -- <why>` when it
fell back. An unselected criterion prints `NOT SELECTED (<why>)` in the
report, where its commands would have been. The full set still runs at the
final gate before a push; this is for the fix rounds before it.

Every run that is not `--list`, serial or `--jobs`, keeps `<out>/status.json`
current and writes `<out>/report.txt` (2026-09-27), so a whole-tree run can
go to the background and outlive the Bash tool's 10-minute ceiling. The
status file is rewritten whole, through a temporary file and a replace, each
time a command starts or finishes: `started_utc`, `updated_utc`, `finished`,
and per criterion its number `k`, its state (`pending`, `running`, `done`,
`skipped` or `not-selected`) and each command's exit code and seconds. A run
that stopped on an exception is `finished` with its `error`. `report.txt` is
everything the run prints to stdout, byte for byte, written as it prints.

`--status DIR` reads that file, prints one line per criterion and a summary
line, and exits 0 when the run has finished, 3 while it is still running, 4
when it is stale (not finished, and `updated_utc` more than 1,900 s old:
longer than the longest per-command timeout, so the runner has died), and 2
when DIR has no status file or on a usage error. `--wait S` polls until the
run finishes, goes stale or S seconds pass, and waits for the file to appear
too; S may not exceed 220, so each poll stays under `workorder_audit.py`
R5's 240-second blocking-call limit. A `--timeout` over 1,800 s can make a
live run look stale. The verifier's procedure: start the whole-tree run with
`run_in_background: true` and `--out` in its own scratchpad, re-issue
`--status <out> --wait 220` (Bash timeout 300000) while it exits 3, then read
`<out>/report.txt`. Never read a status or out directory you did not start.

A run into an `--out` that already holds an earlier run's files first
removes that `report.txt` and replaces `status.json` with an unfinished one,
before anything can refuse the run (2026-09-28), so a poll never reads the
earlier run as this one. A run that then exits before it runs anything (a
usage error, a missing plan, no bash) leaves its status `refused` with the
last line it printed to stderr, and `--status` exits 2 on it.

Usage:
    py -3 tools/run_criteria.py <slug>-plan.md [--out DIR] [--start K]
                                [--timeout SECONDS] [--shell PATH] [--list]
                                [--jobs N|auto] [--browser-jobs N] [--item ID]
                                [--changed-since REF [--changed-since DIR=REF ...]
                                 | --changed-from FILE] [--failed K[,K...]]
    py -3 tools/run_criteria.py --status DIR [--wait S]

`--start K` resumes at criterion K after a call that hit the Bash tool's
ceiling; `--list` prints what would run and runs nothing (with `--jobs`, each
command's class too; with `--changed-since`, the scope). `--timeout` is per
command. Without it, a `suite` or `exclusive` command (a whole test suite, or
one the runner does not recognise) gets 1800 s and every other command 900 s:
ForgePact's Python suite ran 1,037-1,302 s in the UI redesign, past the old
flat 900 s, and its ship plan had to pass `--timeout 1800` by hand. Without
`--jobs` everything runs one command at a time
in plan order, as it always has. Exit code: 0 when it ran (whatever the
commands exited with), 2 on a usage error, no plan, no such item, or no bash;
`--status` exits as above.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_lint  # noqa: E402
import workorder_lock  # noqa: E402

CRITERIA_HEADING_RE = re.compile(r"^##\s+Acceptance criteria\s*$")
STATE_HEADING_RE = re.compile(r"^##\s+State\s*$")
NEXT_H2_RE = re.compile(r"^##\s")
ITEM_RE = re.compile(r"^\s*-\s+\[[ xX]\]\s*")
SPAN_RE = re.compile(r"``(.+?)``|`([^`]+)`", re.S)
GATE_RE = re.compile(r"\(gate\s+`([^`]+)`\)")
COMMAND_RE = re.compile(
    r"^(?:cd|py|python|python3|node|npm|npx|git|grep|rg|ls|cat|head|tail|wc|find|diff|"
    r"fc|fc\.exe|cargo|bash|sh|powershell|pwsh|cmd|cmd\.exe|timeout|curl)(?:\s|$)"
    r"|^[\w./\\:-]+\.(?:bat|cmd|ps1|sh)(?:\s|$)")
# `cd <dir>;` or `cd <dir> &&` opening a span: later spans of the same
# criterion ("`cd ForgePact; build.bat dev` exits 0 and `build.bat release`
# ...") are read in that directory, as the criterion's author meant.
CD_PREFIX_RE = re.compile(r"^cd\s+(\"[^\"]+\"|'[^']+'|\S+?)\s*(?:;|&&)")
TAIL_LINES = 20

CLASSES = ("build", "exclusive", "suite", "browser", "test", "pure")
# Strictest first: a command two criteria share takes the stricter class.
STRICTNESS = {c: i for i, c in enumerate(CLASSES)}
CLASS_DECL_RE = re.compile(r"\(class\s+`?(" + "|".join(CLASSES) + r")`?\)")
AFTER_DECL_RE = re.compile(r"\(after\s+([\d,\s]+)\)")
ANY_CD_RE = re.compile(r"^(?:cd\s+(?:\"[^\"]+\"|'[^']+'|\S+?)\s*(?:;|&&)\s*)+")
BUILD_RE = re.compile(r"\bbuild\.(?:bat|ps1|sh)\b|\bcargo\s+build\b|\btauri\s+build\b|\bcmake\s+--build\b|"
                      r"\bmsbuild\b|\bvite\s+build\b|\bnpm\s+(?:--prefix\s+\S+\s+)?run\s+build\b")
EXCLUSIVE_RE = re.compile(r"e2e:perf|perf\.e2e|oracle|\bbench(?:mark)?\b", re.I)
BROWSER_RE = re.compile(r"\be2e\b|e2e:|\.e2e\.|playwright", re.I)
SUITE_RE = re.compile(r"run_tests_parallel\.py|\bunittest\s+discover\b|(?:-m\s+)?\bpytest\s*(?:$|[;&|>])")
TEST_RE = re.compile(r"-m\s+unittest\b|-m\s+pytest\b|\bpytest\b|\bnode\s+--test\b|\bnpm\s+(?:--prefix\s+\S+\s+)?"
                     r"(?:run\s+)?test\b|\bvitest\b")
PURE_FIRST = {"grep", "rg", "ls", "cat", "head", "tail", "wc", "diff", "fc", "fc.exe", "find", "git", "test"}
PURE_SCRIPT_RE = re.compile(r"^(?:py(?:\s+-3)?|python3?)\s+(?:-c\b|\S*(?:plan_lint|live_checks|amend_check|"
                            r"section|round_delta)\.py\b)|^node\s+-e\b")
DEFAULT_BROWSER_JOBS = 2

# A change here can alter what every criterion reads without touching a path
# any criterion declares: the contract the C++/Python/TypeScript bindings
# agree on, the distributed YYToolkit, which submodules exist, and this
# selection itself. Any of them changed runs the full set.
SHARED_CONTRACT = ("hs-game-sdk/**", "third_party/yytoolkit/**", ".gitmodules",
                   "tools/run_criteria.py", "tools/plan_lint.py")
CONTRACT_LINE_RE = re.compile(r"^\s*shared contract:", re.I)
SCOPE_LIST = 20


def _section(lines: list, heading_re) -> list | None:
    for i, line in enumerate(lines):
        if heading_re.match(line):
            out = []
            for body in lines[i + 1:]:
                if NEXT_H2_RE.match(body):
                    break
                out.append(body)
            return out
    return None


def criteria(text: str) -> list | None:
    """Each checkbox item under `## Acceptance criteria`, with its
    continuation lines joined by newlines (a multi-line `py -3 -c` script
    must keep them); None when the plan has no such heading."""
    body = _section(text.splitlines(), CRITERIA_HEADING_RE)
    if body is None:
        return None
    items: list = []
    for line in body:
        if ITEM_RE.match(line):
            items.append(ITEM_RE.sub("", line, count=1))
        elif items and line.strip():
            items[-1] += "\n" + line
        elif items:
            items[-1] += "\n"
    return [item.strip() for item in items]


def commands(item: str) -> list:
    """The criterion's command spans, in order. A span after one that opened
    with `cd <dir>;` and that does not `cd` itself is prefixed with the same
    `cd <dir>; `."""
    out = []
    cd = None
    for a, b in SPAN_RE.findall(plan_lint.without_reads(item)):
        span = (a or b).strip()
        if not COMMAND_RE.match(span):
            continue
        m = CD_PREFIX_RE.match(span)
        if m:
            cd = m.group(1)
        elif cd is not None and not span.startswith("cd "):
            span = f"cd {cd}; {span}"
        out.append(span)
    return out


def _norm_gate(token: str) -> str:
    return " ".join(token.replace("`", "").split()).lower()


def gates_set(text: str) -> set | None:
    """The gate tokens `## State`'s `gates:` line sets; None when there is no
    such line (then nothing is skipped: an unknown gate set must not hide a
    criterion)."""
    body = _section(text.splitlines(), STATE_HEADING_RE)
    line = next((l for l in body or [] if re.match(r"^\s*gates:", l, re.I)), None)
    if line is None:
        return None
    value = re.sub(r"\([^)]*\)", "", line.split(":", 1)[1])
    if re.search(r"\||<[^>]*>", value) or re.search(r"\bor\b", re.sub(r"`[^`]*`", "", value), re.I):
        return set()
    value = re.split(r"\bnot yet\b", value, flags=re.I)[0]
    ticked = re.findall(r"`([^`]+)`", value)
    tokens = ticked if ticked else re.split(r"[;,]|\band\b", value, flags=re.I)
    return {_norm_gate(t) for t in tokens if _norm_gate(t) and _norm_gate(t) != "none"}


def contract_globs(text: str) -> list:
    """`SHARED_CONTRACT` plus the globs on the plan's `## State` `shared
    contract:` line."""
    body = _section(text.splitlines(), STATE_HEADING_RE) or []
    extra = [(a or b).strip() for line in body if CONTRACT_LINE_RE.match(line)
             for a, b in SPAN_RE.findall(line.split(":", 1)[1]) if (a or b).strip()]
    return list(SHARED_CONTRACT) + extra


def _hits(globs: list, changed: list) -> list:
    return [p for p in changed if any(plan_lint.reads_path(g, p) for g in globs)]


def _hit_text(globs: list, hits: list) -> str:
    glob = next(g for g in globs if plan_lint.reads_path(g, hits[0]))
    more = f" (+{len(hits) - 1} more)" if len(hits) > 1 else ""
    return f"reads `{glob}` <- {hits[0]}{more}"


def select(items: list, changed, failed=frozenset(), contract=SHARED_CONTRACT, unknown: str = "") -> tuple:
    """`(full, why, scope)`: which criteria a change can reach, as a pure
    function of the criteria texts, the changed paths and the criteria that
    failed last time. `scope` maps each criterion number to `(selected,
    reason)`. `changed` None means the delta is unknown (`unknown` says why):
    then, as when a changed path is a shared contract, every criterion is
    selected and `full` is True."""
    ks = range(1, len(items) + 1)
    if changed is None:
        why = f"delta unknown: {unknown or 'no changed paths'}"
    else:
        hit = _hits(list(contract), changed)
        why = f"shared contract changed: {_hit_text(list(contract), hit)}" if hit else ""
    if why:
        return True, why, {k: (True, why) for k in ks}
    scope = {}
    for k, item in zip(ks, items):
        declared = plan_lint.reads(item)
        hits = _hits(declared, changed) if declared else []
        if k in failed:
            scope[k] = (True, "failed last time (--failed)")
        elif declared is None:
            scope[k] = (True, "declares no (reads ...), so it runs whatever changed")
        elif hits:
            scope[k] = (True, _hit_text(declared, hits))
        else:
            scope[k] = (False, f"nothing it reads changed (reads {', '.join(f'`{g}`' for g in declared)})")
    # A selected criterion that runs after another needs what that one's
    # command writes (a build, most often), so the other runs too.
    grew = True
    while grew:
        grew = False
        for k, item in zip(ks, items):
            if not scope[k][0]:
                continue
            for m in AFTER_DECL_RE.finditer(item):
                for dep in (int(x) for x in re.findall(r"\d+", m.group(1))):
                    if dep in scope and not scope[dep][0]:
                        scope[dep] = (True, f"criterion {k} runs after it")
                        grew = True
    return False, "", scope


def _submodule_dirs(root: Path) -> list:
    """`.gitmodules` paths that are initialized checkouts, forward-slashed."""
    if not (root / ".gitmodules").is_file():
        return []
    result = subprocess.run(["git", "config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"],
                            cwd=str(root), capture_output=True, text=True)
    dirs = [line.partition(" ")[2].strip().replace("\\", "/") for line in result.stdout.splitlines()]
    return [d for d in dirs if d and (root / d / ".git").exists()]


def _git_lines(cwd: Path, *args) -> list | None:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    return result.stdout.splitlines() if result.returncode == 0 else None


def changed_paths(root: Path, since: dict) -> tuple:
    """`(paths, None)` changed since each repo's base, or `(None, why)`.
    `since` maps `.` to the hub's base and a submodule dir to its own; a
    submodule without one takes the commit the hub's base records for it.
    Working-tree and untracked changes count, so work left uncommitted is
    in scope too."""
    subs = _submodule_dirs(root)
    unknown = sorted(set(since) - {"."} - set(subs))
    if unknown:
        return None, f"not an initialized submodule: {', '.join(unknown)}"
    paths: set = set()
    for key in ["."] + subs:
        repo = root if key == "." else root / key
        base = since.get(key)
        if base is None:
            recorded = _git_lines(root, "rev-parse", f"{since['.']}:{key}")
            if not recorded:
                return None, f"no base for {key}: the hub's {since['.']} records no commit for it"
            base = recorded[0].strip()
        diff = _git_lines(repo, "diff", "--name-only", "--no-renames", base)
        untracked = _git_lines(repo, "ls-files", "--others", "--exclude-standard")
        if diff is None or untracked is None:
            return None, f"git cannot diff {'the hub' if key == '.' else key} from {base}"
        for p in diff + untracked:
            p = p.strip().replace("\\", "/")
            if not p or (key == "." and p in subs):
                continue  # the hub's own line for a submodule is its gitlink, not a file
            paths.add(p if key == "." else f"{key}/{p}")
    return sorted(paths), None


def _read_changed_from(source: str) -> tuple:
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"cannot read {source}: {exc}"
    return sorted({l.strip().replace("\\", "/").removeprefix("./") for l in text.splitlines() if l.strip()}), None


def print_scope(source: str, changed, full: bool, why: str, scope: dict, start: int) -> None:
    if full:
        print(f"scope: full -- {why}; running every criterion")
        return
    print(f"scope: changed {source}: {len(changed)} path(s)")
    for p in changed[:SCOPE_LIST]:
        print(f"  {p}")
    if len(changed) > SCOPE_LIST:
        print(f"  ... {len(changed) - SCOPE_LIST} more")
    shown = {k: v for k, v in scope.items() if k >= start}
    print(f"scope: running {sum(1 for s, _ in shown.values() if s)} of {len(shown)} criteria")
    for k, (selected, reason) in shown.items():
        print(f"  {'run ' if selected else 'skip'} criterion {k}: {reason}")


def find_bash(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    if os.name == "nt":
        # `bash` on PATH may be WSL's launcher in System32, which runs in a
        # different filesystem; the verifier's Bash tool is Git Bash.
        git = shutil.which("git")
        if git:
            root = Path(git).resolve().parent.parent
            for candidate in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
                if candidate.is_file():
                    return str(candidate)
        found = shutil.which("bash")
        if found and "system32" not in found.lower():
            return found
        return None
    return shutil.which("bash")


def checkout_root(plan: Path) -> Path:
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(plan.resolve().parent),
                            capture_output=True, text=True)
    return Path(result.stdout.strip()) if result.returncode == 0 else plan.resolve().parent


def classify(cmd: str) -> str:
    """A command's resource class when its criterion declares none. Anything
    no rule recognises is `exclusive`: running an unknown command alone is
    slow, running it beside a build it races with is wrong."""
    body = ANY_CD_RE.sub("", cmd.strip())
    if BUILD_RE.search(body):
        return "build"
    if EXCLUSIVE_RE.search(body):
        return "exclusive"
    if BROWSER_RE.search(body):
        return "browser"
    if SUITE_RE.search(body):
        return "suite"
    if TEST_RE.search(body):
        return "test"
    first = body.split(None, 1)[0] if body.split() else ""
    if first in PURE_FIRST or PURE_SCRIPT_RE.search(body):
        return "pure"
    return "exclusive"


def build_jobs(items: list, start: int, gates, scope: dict | None = None) -> tuple:
    """(rows, jobs): one row per criterion from `start` on -- its number, the
    first line, and either a skip reason or its commands as job ids -- and
    one job per distinct command, numbered in plan order (the serial run's
    `cmd-<n>.log` numbers), with its class and the jobs it must follow.
    `scope` is `select()`'s map; a criterion it did not select gets no job."""
    rows, jobs, by_cmd = [], [], {}
    job_of_criterion: dict = {}
    for k, item in enumerate(items, 1):
        if k < start:
            continue
        first = item.splitlines()[0] if item else ""
        row = {"k": k, "first": first, "more": len(first) > 150 or len(item.splitlines()) > 1,
               "skip": None, "jobs": []}
        rows.append(row)
        if scope is not None and not scope[k][0]:
            row["skip"] = f"NOT SELECTED ({scope[k][1]})"
            continue
        unset = [g for g in GATE_RE.findall(item) if gates is not None and _norm_gate(g) not in gates]
        if unset:
            row["skip"] = f"SKIPPED (gate {'; '.join(unset)} not set)"
            continue
        cmds = commands(item)
        if not cmds:
            row["skip"] = "no command -- check by reading"
            continue
        declared = CLASS_DECL_RE.search(item)
        after_ks = {int(x) for m in AFTER_DECL_RE.finditer(item) for x in re.findall(r"\d+", m.group(1))}
        for cmd in cmds:
            cls = declared.group(1) if declared else classify(cmd)
            if cmd in by_cmd:
                job = jobs[by_cmd[cmd]]
                if STRICTNESS[cls] < STRICTNESS[job["cls"]]:
                    job["cls"] = cls
            else:
                by_cmd[cmd] = len(jobs)
                job = {"id": len(jobs) + 1, "cmd": cmd, "cls": cls, "after_k": set(), "after": set()}
                jobs.append(job)
            job["after_k"] |= after_ks
            row["jobs"].append(job["id"])
        job_of_criterion[k] = list(row["jobs"])
    for job in jobs:
        for k in job.pop("after_k"):
            job["after"] |= {j for j in job_of_criterion.get(k, []) if j != job["id"]}
    return rows, jobs


def startable(jobs: list, done: set, running: set, jobs_cap: int, browser_cap: int) -> list:
    """The job ids to start now, in plan order -- a pure function of what is
    done and running, so the rules can be tested without running anything.

    Builds first and one at a time; nothing else while one is left. An
    exclusive job is a barrier at its place in the plan: it starts alone,
    once every job before it is done, and nothing after it starts until it
    is done -- an unrecognised command may write what a later criterion
    reads, as it would have in a serial run. Between barriers, at most one
    suite, `browser_cap` browser suites and `jobs_cap` jobs in all. A job
    waits for every job its `after` names. If nothing runs and the rules
    leave nothing to start, the first pending job whose `after` is done
    starts anyway, so a declared order the rules did not foresee (a build
    after a pure check) cannot deadlock."""
    by_id = {j["id"]: j for j in jobs}
    running_cls = [by_id[r]["cls"] for r in running]
    if "exclusive" in running_cls:
        return []
    pending = [j for j in jobs if j["id"] not in done and j["id"] not in running]
    ready = [j for j in pending if j["after"] <= done]
    builds_left = any(j["cls"] == "build" for j in jobs if j["id"] not in done)
    barrier = next((j for j in pending if j["cls"] == "exclusive"), None)
    out: list = []
    slots = jobs_cap - len(running)
    counts = {c: running_cls.count(c) for c in CLASSES}
    for j in ready:
        if slots <= 0:
            break
        cls = j["cls"]
        if cls == "build":
            if counts["build"]:
                continue
        elif builds_left or cls == "exclusive" or (barrier is not None and j["id"] > barrier["id"]):
            continue
        elif cls == "suite" and counts["suite"] >= 1:
            continue
        elif cls == "browser" and counts["browser"] >= browser_cap:
            continue
        out.append(j["id"])
        counts[cls] += 1
        slots -= 1
    if out or running:
        return out
    if (barrier is not None and not builds_left and barrier["after"] <= done
            and all(j["id"] in done for j in jobs if j["id"] < barrier["id"])):
        return [barrier["id"]]
    return [ready[0]["id"]] if ready else []


DEFAULT_TIMEOUT = 900
LONG_TIMEOUT = 1800
LONG_CLASSES = ("suite", "exclusive")


def timeout_for(cls: str, explicit: int | None) -> int:
    """A command's timeout: `--timeout` when given, else by its class."""
    if explicit is not None:
        return explicit
    return LONG_TIMEOUT if cls in LONG_CLASSES else DEFAULT_TIMEOUT


def _run_one(bash: str, cmd: str, root: Path, timeout: int) -> tuple:
    started = time.monotonic()
    try:
        proc = subprocess.run([bash, "-c", cmd], cwd=str(root), capture_output=True, timeout=timeout)
        code = proc.returncode
        output = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        code = "TIMEOUT"
        output = ((exc.stdout or b"") + (exc.stderr or b"")).decode("utf-8", "replace") + \
            f"\n[run_criteria: killed after {timeout}s]"
    return code, time.monotonic() - started, output


STATUS_FILE = "status.json"
REPORT_FILE = "report.txt"
# Not finished and not rewritten for longer than the longest per-command
# timeout (LONG_TIMEOUT): nothing the runner is doing can take that long
# between two writes, so the runner is gone.
STALE_AFTER = 1900
# Each `--status --wait` call has to return inside workorder_audit.py R5's
# 240-second blocking-call limit.
MAX_WAIT = 220
POLL_SECONDS = 1.0
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime(UTC_FORMAT)


def _replace_json(path: Path, doc: dict) -> None:
    """Write `doc` to `path` through a temporary file and a replace, so a
    reader in another process never sees half a file."""
    tmp = path.with_name(f"{STATUS_FILE}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    # On Windows a replace fails while a `--status` reader holds the file
    # open; it is open for milliseconds, so try again.
    for _ in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, path)


class _Starting:
    """A new run into an `--out` that may hold an earlier run's files. Before
    anything can refuse the run, the earlier `report.txt` goes and
    `status.json` becomes an unfinished status with no criteria, so a
    `--status` poll can never read the earlier run as this one. A run that
    exits before `Status` takes over is recorded as refused, with the last
    line it printed to stderr, so the poll stops instead of waiting for it
    to go stale."""

    def __init__(self, out: Path):
        self.path = out / STATUS_FILE
        self.handed_over = False
        self.last_error = ""
        now = _utc_now()
        self.doc = {"plan": None, "item": None, "started_utc": now, "updated_utc": now,
                    "finished": False, "error": None, "criteria": []}
        try:
            out.mkdir(parents=True, exist_ok=True)
            _replace_json(self.path, self.doc)
        except OSError:
            pass  # main's own mkdir, or Status, reports an unwritable out dir
        for _ in range(40):
            try:
                (out / REPORT_FILE).unlink()
                break
            except FileNotFoundError:
                break
            except OSError:
                time.sleep(0.05)

    def write(self, text: str) -> None:
        """`sys.stderr` hook: remember the last non-empty line printed."""
        lines = [line for line in text.splitlines() if line.strip()]
        if lines:
            self.last_error = lines[-1].strip()

    def end(self, error: str, code=None) -> None:
        if self.handed_over:
            return
        self.doc.update(updated_utc=_utc_now(), finished=True, error=error)
        if code is not None:
            self.doc.update(refused=True, exit=code)
        try:
            _replace_json(self.path, self.doc)
        except OSError:
            pass


class _StderrTap:
    """Everything printed to stderr goes through unchanged; `_Starting`
    sees it too, to name why a run refused."""

    def __init__(self, stream, starting: _Starting):
        self.stream = stream
        self.starting = starting

    def write(self, text: str) -> int:
        self.starting.write(text)
        return self.stream.write(text)

    def flush(self) -> None:
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


class Status:
    """`<out>/status.json`, rewritten whole on every change so a reader in
    another process never sees half a file. Worker threads call `running`
    once their lock is held, so every write takes `self.lock`."""

    def __init__(self, out: Path, plan: Path, item, rows: list, jobs: list, start: int):
        self.path = out / STATUS_FILE
        self.lock = threading.Lock()
        self.warned = False
        self.cmds = {j["id"]: {"n": j["id"], "cmd": j["cmd"], "class": j["cls"], "state": "pending",
                               "exit": None, "seconds": None, "started_utc": None} for j in jobs}
        self.criteria = [{"k": k, "state": "skipped", "note": f"before --start {start}", "jobs": []}
                         for k in range(1, start)]
        for row in rows:
            skip = row["skip"]
            state = None if not skip else "not-selected" if skip.startswith("NOT SELECTED") else "skipped"
            self.criteria.append({"k": row["k"], "state": state, "note": skip, "jobs": list(row["jobs"])})
        now = _utc_now()
        self.doc = {"plan": str(plan), "item": item, "started_utc": now, "updated_utc": now,
                    "finished": False, "error": None}
        self._write()

    def _criterion_state(self, c: dict) -> str:
        if c["state"]:
            return c["state"]
        states = [self.cmds[j]["state"] for j in c["jobs"]]
        if all(s == "done" for s in states):
            return "done"
        return "pending" if all(s == "pending" for s in states) else "running"

    def _write(self) -> None:
        self.doc["updated_utc"] = _utc_now()
        doc = dict(self.doc, criteria=[{"k": c["k"], "state": self._criterion_state(c), "note": c["note"],
                                        "commands": [dict(self.cmds[j]) for j in c["jobs"]]}
                                       for c in self.criteria])
        try:
            _replace_json(self.path, doc)
        except OSError as exc:
            if not self.warned:
                self.warned = True
                print(f"run_criteria: cannot write {self.path}: {exc}", file=sys.stderr)

    def _set(self, jid: int, **fields) -> None:
        with self.lock:
            self.cmds[jid].update(fields)
            self._write()

    def waiting(self, jid: int) -> None:
        """Started, but waiting for its `build` or browser lock."""
        self._set(jid, state="waiting", started_utc=_utc_now())

    def running(self, jid: int) -> None:
        self._set(jid, state="running", started_utc=_utc_now())

    def done(self, jid: int, result: tuple) -> None:
        code, secs, _ = result
        self._set(jid, state="done", exit=code, seconds=round(secs, 1))

    def finish(self, error: str | None = None) -> None:
        with self.lock:
            self.doc.update(finished=True, error=error)
            self._write()


class _Tee:
    """Everything the run prints goes to stdout unchanged and, as it is
    printed, to `<out>/report.txt`."""

    def __init__(self, stream, path: Path):
        self.stream = stream
        self.file = open(path, "w", encoding="utf-8", errors="replace", newline="")

    def write(self, text: str) -> int:
        self.stream.write(text)
        if not self.file.closed:
            self.file.write(text)
            self.file.flush()
        return len(text)

    def flush(self) -> None:
        self.stream.flush()
        if not self.file.closed:
            self.file.flush()

    def close(self) -> None:
        self.file.close()


def read_status(out: Path) -> tuple:
    """`(doc, None)` or `(None, why)`. A file being replaced this instant
    can refuse the open on Windows, so an unreadable one is retried."""
    path = out / STATUS_FILE
    why = "unreadable"
    for _ in range(20):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            datetime.strptime(doc["updated_utc"], UTC_FORMAT)
            return doc, None
        except FileNotFoundError:
            return None, f"no {STATUS_FILE} in {out}"
        except (OSError, ValueError, KeyError, TypeError) as exc:
            why = f"{path} is unreadable: {exc}"
            time.sleep(0.05)
    return None, why


def status_state(doc: dict, now: datetime | None = None) -> tuple:
    """`(state, exit code, age in seconds)`: finished 0, running 3, stale 4,
    and refused 2 for a run that exited before it ran anything."""
    now = now or datetime.now(timezone.utc)
    updated = datetime.strptime(doc["updated_utc"], UTC_FORMAT).replace(tzinfo=timezone.utc)
    age = max(0, int((now - updated).total_seconds()))
    if doc.get("refused"):
        return "refused", 2, age
    if doc.get("finished"):
        return "finished", 0, age
    if age > STALE_AFTER:
        return "stale", 4, age
    return "running", 3, age


def _status_line(c: dict) -> str:
    head = f"criterion {c['k']}: {c['state']}"
    if c["state"] in ("skipped", "not-selected"):
        return f"{head} -- {c.get('note')}"
    parts = []
    for cmd in c.get("commands", []):
        if cmd["state"] == "done":
            parts.append(f"cmd-{cmd['n']} exit {cmd['exit']} ({cmd['seconds']:.0f}s)")
        elif cmd["state"] in ("running", "waiting"):
            what = "waiting for its lock" if cmd["state"] == "waiting" else "running"
            parts.append(f"cmd-{cmd['n']} {what} since {cmd['started_utc']}")
        else:
            parts.append(f"cmd-{cmd['n']} pending")
    return f"{head} -- {'; '.join(parts)}" if parts else head


def show_status(out: Path, wait: float) -> int:
    """`--status`: poll until the run finishes, goes stale or `wait` runs
    out, then print one line per criterion and a summary."""
    deadline = time.monotonic() + wait
    while True:
        doc, why = read_status(out)
        state = status_state(doc)[0] if doc else None
        left = deadline - time.monotonic()
        if state in ("finished", "stale", "refused") or left <= 0:
            break
        time.sleep(min(POLL_SECONDS, left))
    if doc is None:
        print(f"status: none -- {why}")
        return 2
    state, code, age = status_state(doc)
    counts: dict = {}
    for c in doc.get("criteria", []):
        print(_status_line(c))
        counts[c["state"]] = counts.get(c["state"], 0) + 1
    tally = ", ".join(f"{counts[s]} {s}" for s in ("done", "running", "pending", "skipped", "not-selected")
                      if counts.get(s))
    report = out / REPORT_FILE
    if state == "stale":
        tail = (f"not finished and not updated for {age}s (over {STALE_AFTER}s): the runner has died; "
                f"run it again")
    elif state == "refused":
        tail = (f"the run exited {doc.get('exit')} before running anything: {doc.get('error')}; "
                f"nothing ran, so fix the command and start it again")
    elif state == "running":
        tail = f"updated {age}s ago; poll again with --status {out} --wait {MAX_WAIT}"
    elif doc.get("error"):
        tail = f"the runner stopped on an error: {doc['error']}; what it printed is in {report}"
    else:
        tail = f"read {report}"
    print(f"status: {state} -- {len(doc.get('criteria', []))} criteria ({tally or 'none'}); "
          f"started {doc.get('started_utc')}, updated {doc['updated_utc']}; {tail}")
    return code


def run_parallel(rows: list, jobs: list, bash: str, root: Path, out: Path, explicit_timeout: int | None,
                 jobs_cap: int, browser_cap: int, status: Status | None = None) -> None:
    """Run `jobs` under `startable`'s rules on worker threads and print each
    criterion, in plan order, once all of its commands are done."""
    by_id = {j["id"]: j for j in jobs}
    results: dict = {}
    done: set = set()
    running: set = set()
    finished: queue.Queue = queue.Queue()
    locks = workorder_lock.lock_dir(root)
    browser_slots = [f"browser-{i}" for i in range(browser_cap)]

    def run_now(job, timeout):
        if status is not None:
            status.running(job["id"])
        return _run_one(bash, job["cmd"], root, timeout)

    def worker(job):
        # Every path puts a result: a job that never reports would leave the
        # main loop waiting on `finished` forever.
        try:
            timeout = timeout_for(job["cls"], explicit_timeout)
            names = "build" if job["cls"] == "build" else browser_slots if job["cls"] == "browser" else None
            if names:
                with workorder_lock.held(names, locks, timeout=timeout) as got:
                    result = run_now(job, timeout) if got else \
                        ("LOCKED", 0.0, f"[run_criteria: the {job['cls']} lock was not free after {timeout}s]")
            else:
                result = run_now(job, timeout)
        except BaseException as exc:  # noqa: BLE001 -- reported as the job's result
            result = ("ERROR", 0.0, f"[run_criteria: {type(exc).__name__}: {exc}]")
        finished.put((job["id"], result))

    printed = 0
    reported: set = set()

    def flush():
        nonlocal printed
        while printed < len(rows) and all(j in done for j in rows[printed]["jobs"]):
            row = rows[printed]
            print(f"\ncriterion {row['k']}: {row['first'][:150]}{' ...' if row['more'] else ''}")
            if row["skip"]:
                print(f"  {row['skip']}")
            for jid in row["jobs"]:
                job = by_id[jid]
                code, secs, output = results[jid]
                shown = job["cmd"] if "\n" not in job["cmd"] else job["cmd"].splitlines()[0] + " ...(multi-line)"
                if jid in reported:
                    print(f"  `{shown}` -> exit {code} ({secs:.0f}s), same command as cmd-{jid}.log, run once")
                    continue
                reported.add(jid)
                print(f"  `{shown}` -> exit {code} ({secs:.0f}s), cmd-{jid}.log")
                if output.strip():
                    print(_tail(output))
            sys.stdout.flush()
            printed += 1

    flush()
    while len(done) < len(jobs):
        for jid in startable(jobs, done, running, jobs_cap, browser_cap):
            running.add(jid)
            if status is not None and by_id[jid]["cls"] in ("build", "browser"):
                status.waiting(jid)
            threading.Thread(target=worker, args=(by_id[jid],), daemon=True).start()
        if not running:
            # Only an `after` cycle leaves nothing runnable and nothing running.
            for job in jobs:
                if job["id"] not in done:
                    results[job["id"]] = ("NOT RUN", 0.0, "[run_criteria: its (after ...) order loops]")
                    done.add(job["id"])
                    if status is not None:
                        status.done(job["id"], results[job["id"]])
            break
        jid, result = finished.get()
        running.discard(jid)
        done.add(jid)
        results[jid] = result
        (out / f"cmd-{jid}.log").write_text(f"$ {by_id[jid]['cmd']}\n{result[2]}", encoding="utf-8")
        if status is not None:
            status.done(jid, result)
        flush()
    flush()


def _tail(text: str, n: int = TAIL_LINES) -> str:
    lines = text.rstrip("\n").splitlines()
    head = [f"    ... {len(lines) - n} earlier lines in the log"] if len(lines) > n else []
    return "\n".join(head + ["    " + l for l in lines[-n:]])


def _new_run_out(argv) -> Path | None:
    """The `--out` of a run that will write one, known before anything can
    refuse the run: None for `--status` and `--list`, which write nothing
    there, and when `--out` is not given (a fresh temporary dir then)."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--out", default=None)
    pre.add_argument("--status", default=None)
    pre.add_argument("--list", action="store_true")
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            known, _ = pre.parse_known_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return None
    if known.status is not None or known.list or not known.out:
        return None
    return Path(known.out)


def main(argv=None) -> int:
    out = _new_run_out(argv)
    if out is None:
        return _main(argv, None)
    starting = _Starting(out)
    try:
        with contextlib.redirect_stderr(_StderrTap(sys.stderr, starting)):
            code = _main(argv, starting)
    except BaseException as exc:
        starting.end(f"{type(exc).__name__}: {exc}")
        raise
    if code != 0:
        starting.end(starting.last_error or f"run_criteria exited {code}", code)
    return code


def _main(argv, starting) -> int:
    parser = argparse.ArgumentParser(prog="run_criteria.py")
    parser.add_argument("plan", nargs="?", default=None)
    parser.add_argument("--status", default=None)
    parser.add_argument("--wait", type=float, default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--shell", default=None)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--jobs", default=None)
    parser.add_argument("--browser-jobs", type=int, default=DEFAULT_BROWSER_JOBS)
    parser.add_argument("--item", default=None)
    parser.add_argument("--changed-since", action="append", default=[])
    parser.add_argument("--changed-from", default=None)
    parser.add_argument("--failed", default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    if args.wait is not None and args.status is None:
        print("run_criteria: --wait goes with --status DIR", file=sys.stderr)
        return 2
    if args.status is not None:
        if args.plan is not None:
            print("run_criteria: --status DIR reads a run; it takes no plan", file=sys.stderr)
            return 2
        wait = 0.0 if args.wait is None else args.wait
        if not 0 <= wait <= MAX_WAIT:
            print(f"run_criteria: --wait takes 0 to {MAX_WAIT} seconds, so each poll stays under the "
                  f"240-second blocking-call limit", file=sys.stderr)
            return 2
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        return show_status(Path(args.status), wait)
    if args.plan is None:
        print("run_criteria: give a plan, or --status DIR", file=sys.stderr)
        return 2
    since: dict = {}
    for value in args.changed_since:
        key, _, ref = value.rpartition("=") if "=" in value else (".", "", value)
        key = key.replace("\\", "/").strip("/") or "."
        if not ref or key in since:
            print(f"run_criteria: --changed-since {value}: want REF once, and DIR=REF once per submodule",
                  file=sys.stderr)
            return 2
        since[key] = ref
    scoped = bool(since) or args.changed_from is not None
    if since and "." not in since:
        print("run_criteria: --changed-since DIR=REF needs the hub's --changed-since REF too", file=sys.stderr)
        return 2
    if since and args.changed_from is not None:
        print("run_criteria: --changed-since and --changed-from are alternatives", file=sys.stderr)
        return 2
    if (args.failed is not None or scoped) and args.item is not None:
        print("run_criteria: --item runs an item's own checks; the reach selection is for the criteria",
              file=sys.stderr)
        return 2
    if args.failed is not None and not scoped:
        print("run_criteria: --failed needs --changed-since or --changed-from", file=sys.stderr)
        return 2
    failed: set = set()
    if args.failed is not None:
        parts = [p.strip() for p in args.failed.split(",") if p.strip()]
        if not all(p.isdigit() and int(p) >= 1 for p in parts):
            print("run_criteria: --failed takes criterion numbers, e.g. 3,7", file=sys.stderr)
            return 2
        failed = {int(p) for p in parts}
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    jobs_cap = None
    if args.jobs is not None:
        if args.jobs == "auto":
            jobs_cap = min(8, os.cpu_count() or 2)
        elif args.jobs.isdigit() and int(args.jobs) >= 1:
            jobs_cap = int(args.jobs)
        else:
            print("run_criteria: --jobs takes a whole number >= 1, or auto", file=sys.stderr)
            return 2
    if args.browser_jobs < 1:
        print("run_criteria: --browser-jobs takes a whole number >= 1", file=sys.stderr)
        return 2

    plan = Path(args.plan)
    if not plan.is_file():
        print(f"run_criteria: no such file: {plan}", file=sys.stderr)
        return 2
    text = plan.read_text(encoding="utf-8", errors="replace")
    if args.item is not None:
        found = next((it for it in plan_lint.items(text) if it["id"] == args.item), None)
        if found is None:
            print(f"run_criteria: {plan} has no '### Item: {args.item}' under '## Steps'", file=sys.stderr)
            return 2
        items = list(found["checks"])
    else:
        items = criteria(text)
    if items is None:
        print(f"run_criteria: {plan} has no '## Acceptance criteria' heading", file=sys.stderr)
        return 2
    bash = None if args.list else find_bash(args.shell)
    if not args.list and not bash:
        print("run_criteria: no bash found (pass --shell PATH)", file=sys.stderr)
        return 2
    if bash and not (Path(bash).is_file() or shutil.which(bash)):
        print(f"run_criteria: --shell {bash} does not exist", file=sys.stderr)
        return 2
    gates = gates_set(text)
    root = checkout_root(plan)
    if failed - set(range(1, len(items) + 1)):
        print(f"run_criteria: --failed names no criterion of {len(items)}: "
              f"{', '.join(str(k) for k in sorted(failed - set(range(1, len(items) + 1))))}", file=sys.stderr)
        return 2
    scope = None
    if scoped:
        if since:
            changed, why = changed_paths(root, since)
            source = "since " + ", ".join(ref if key == "." else f"{key}={ref}" for key, ref in since.items())
        else:
            changed, why = _read_changed_from(args.changed_from)
            source = f"per {args.changed_from}"
        full, full_why, scope = select(items, changed, failed, contract_globs(text), why or "")
    if args.list:
        # Runs nothing and writes nothing: no out dir, no status, no report.
        if scoped:
            print_scope(source, changed, full, full_why, scope, args.start)
        list_only(items, args.start, gates, scope, jobs_cap is not None)
        return 0

    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="run_criteria_"))
    out.mkdir(parents=True, exist_ok=True)
    rows, jobs = build_jobs(items, args.start, gates, scope)
    if starting is not None:
        starting.handed_over = True
    status = Status(out, plan, args.item, rows, jobs, args.start)
    tee = _Tee(sys.stdout, out / REPORT_FILE)
    error = None
    try:
        with contextlib.redirect_stdout(tee):
            print(f"checkout: {root}\nlogs: {out}\nshell: {bash}")
            if scoped:
                print_scope(source, changed, full, full_why, scope, args.start)
            if jobs_cap is not None:
                print(f"jobs: {jobs_cap} (browser suites at most {args.browser_jobs})")
                run_parallel(rows, jobs, bash, root, out, args.timeout, jobs_cap, args.browser_jobs, status)
            else:
                run_serial(items, args.start, gates, scope, bash, root, out, args.timeout, jobs, status)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        # The report is whole before the status says the run finished.
        tee.close()
        status.finish(error)
    return 0


def list_only(items: list, start: int, gates, scope: dict | None, with_classes: bool) -> None:
    """`--list`: what would run, and with `--jobs` each command's class."""
    if with_classes:
        rows, jobs = build_jobs(items, start, gates, scope)
        by_id = {j["id"]: j for j in jobs}
        for row in rows:
            print(f"\ncriterion {row['k']}: {row['first'][:150]}{' ...' if row['more'] else ''}")
            if row["skip"]:
                print(f"  {row['skip']}")
            for jid in row["jobs"]:
                job = by_id[jid]
                shown = job["cmd"] if "\n" not in job["cmd"] else job["cmd"].splitlines()[0] + " ...(multi-line)"
                after = f", after cmd {', '.join(str(a) for a in sorted(job['after']))}" if job["after"] else ""
                print(f"  would run: {shown} [class {job['cls']}{after}]")
        return
    for k, item in enumerate(items, 1):
        if k < start:
            continue
        cmds = commands(item)
        first = item.splitlines()[0]
        more = " ..." if len(first) > 150 or len(item.splitlines()) > 1 else ""
        print(f"\ncriterion {k}: {first[:150]}{more}")
        if scope is not None and not scope[k][0]:
            print(f"  NOT SELECTED ({scope[k][1]})")
            continue
        unset = [g for g in GATE_RE.findall(item) if gates is not None and _norm_gate(g) not in gates]
        if unset:
            print(f"  SKIPPED (gate {'; '.join(unset)} not set)")
            continue
        if not cmds:
            print("  no command -- check by reading")
            continue
        for cmd in cmds:
            shown = cmd if "\n" not in cmd else cmd.splitlines()[0] + " ...(multi-line)"
            print(f"  would run: {shown}")


def run_serial(items: list, start: int, gates, scope: dict | None, bash: str, root: Path, out: Path,
               explicit_timeout: int | None, jobs: list, status: Status) -> None:
    """Without `--jobs`: one command at a time, in plan order. `jobs` is
    `build_jobs`' list for the same selection, whose ids are the `cmd-<n>`
    numbers this assigns, so the status file can name each command."""
    job_of = {j["cmd"]: j["id"] for j in jobs}
    ran: dict = {}  # command -> (n, exit, seconds, output)
    for k, item in enumerate(items, 1):
        if k < start:
            continue
        cmds = commands(item)
        first = item.splitlines()[0]
        more = " ..." if len(first) > 150 or len(item.splitlines()) > 1 else ""
        print(f"\ncriterion {k}: {first[:150]}{more}")
        if scope is not None and not scope[k][0]:
            print(f"  NOT SELECTED ({scope[k][1]})")
            continue
        unset = [g for g in GATE_RE.findall(item) if gates is not None and _norm_gate(g) not in gates]
        if unset:
            print(f"  SKIPPED (gate {'; '.join(unset)} not set)")
            continue
        if not cmds:
            print("  no command -- check by reading")
            continue
        for cmd in cmds:
            shown = cmd if "\n" not in cmd else cmd.splitlines()[0] + " ...(multi-line)"
            if cmd in ran:
                n, code, secs, _ = ran[cmd]
                print(f"  `{shown}` -> exit {code} ({secs:.0f}s), same command as cmd-{n}.log, run once")
                continue
            n = len(ran) + 1
            declared = CLASS_DECL_RE.search(item)
            timeout = timeout_for(declared.group(1) if declared else classify(cmd), explicit_timeout)
            status.running(job_of[cmd])
            code, secs, output = _run_one(bash, cmd, root, timeout)
            (out / f"cmd-{n}.log").write_text(f"$ {cmd}\n{output}", encoding="utf-8")
            ran[cmd] = (n, code, secs, output)
            status.done(job_of[cmd], (code, secs, output))
            print(f"  `{shown}` -> exit {code} ({secs:.0f}s), cmd-{n}.log")
            if output.strip():
                print(_tail(output))
            sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
