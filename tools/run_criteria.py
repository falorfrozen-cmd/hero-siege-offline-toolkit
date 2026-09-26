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

Usage:
    py -3 tools/run_criteria.py <slug>-plan.md [--out DIR] [--start K]
                                [--timeout SECONDS] [--shell PATH] [--list]
                                [--jobs N|auto] [--browser-jobs N] [--item ID]

`--start K` resumes at criterion K after a call that hit the Bash tool's
ceiling; `--list` prints what would run and runs nothing (with `--jobs`, each
command's class too). `--timeout` is per command (default 900). Without
`--jobs` everything runs one command at a time in plan order, as it always
has. Exit code: 0 when it ran (whatever the commands exited with), 2 on a
usage error, no plan, no such item, or no bash.
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
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
    for a, b in SPAN_RE.findall(item):
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


def build_jobs(items: list, start: int, gates) -> tuple:
    """(rows, jobs): one row per criterion from `start` on -- its number, the
    first line, and either a skip reason or its commands as job ids -- and
    one job per distinct command, numbered in plan order (the serial run's
    `cmd-<n>.log` numbers), with its class and the jobs it must follow."""
    rows, jobs, by_cmd = [], [], {}
    job_of_criterion: dict = {}
    for k, item in enumerate(items, 1):
        if k < start:
            continue
        first = item.splitlines()[0] if item else ""
        row = {"k": k, "first": first, "more": len(first) > 150 or len(item.splitlines()) > 1,
               "skip": None, "jobs": []}
        rows.append(row)
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


def run_parallel(rows: list, jobs: list, bash: str, root: Path, out: Path, timeout: int,
                 jobs_cap: int, browser_cap: int) -> None:
    """Run `jobs` under `startable`'s rules on worker threads and print each
    criterion, in plan order, once all of its commands are done."""
    by_id = {j["id"]: j for j in jobs}
    results: dict = {}
    done: set = set()
    running: set = set()
    finished: queue.Queue = queue.Queue()
    locks = workorder_lock.lock_dir(root)
    browser_slots = [f"browser-{i}" for i in range(browser_cap)]

    def worker(job):
        names = "build" if job["cls"] == "build" else browser_slots if job["cls"] == "browser" else None
        if names:
            with workorder_lock.held(names, locks, timeout=timeout) as got:
                result = _run_one(bash, job["cmd"], root, timeout) if got else \
                    ("LOCKED", 0.0, f"[run_criteria: the {job['cls']} lock was not free after {timeout}s]")
        else:
            result = _run_one(bash, job["cmd"], root, timeout)
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
            threading.Thread(target=worker, args=(by_id[jid],), daemon=True).start()
        if not running:
            # Only an `after` cycle leaves nothing runnable and nothing running.
            for job in jobs:
                if job["id"] not in done:
                    results[job["id"]] = ("NOT RUN", 0.0, "[run_criteria: its (after ...) order loops]")
                    done.add(job["id"])
            break
        jid, result = finished.get()
        running.discard(jid)
        done.add(jid)
        results[jid] = result
        (out / f"cmd-{jid}.log").write_text(f"$ {by_id[jid]['cmd']}\n{result[2]}", encoding="utf-8")
        flush()
    flush()


def _tail(text: str, n: int = TAIL_LINES) -> str:
    lines = text.rstrip("\n").splitlines()
    head = [f"    ... {len(lines) - n} earlier lines in the log"] if len(lines) > n else []
    return "\n".join(head + ["    " + l for l in lines[-n:]])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_criteria.py")
    parser.add_argument("plan")
    parser.add_argument("--out", default=None)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--shell", default=None)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--jobs", default=None)
    parser.add_argument("--browser-jobs", type=int, default=DEFAULT_BROWSER_JOBS)
    parser.add_argument("--item", default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
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
    gates = gates_set(text)
    root = checkout_root(plan)
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="run_criteria_"))
    if not args.list:
        out.mkdir(parents=True, exist_ok=True)
        print(f"checkout: {root}\nlogs: {out}\nshell: {bash}")

    if jobs_cap is not None:
        rows, jobs = build_jobs(items, args.start, gates)
        if args.list:
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
            return 0
        print(f"jobs: {jobs_cap} (browser suites at most {args.browser_jobs})")
        run_parallel(rows, jobs, bash, root, out, args.timeout, jobs_cap, args.browser_jobs)
        return 0

    ran: dict = {}  # command -> (n, exit, seconds, output)
    for k, item in enumerate(items, 1):
        if k < args.start:
            continue
        cmds = commands(item)
        first = item.splitlines()[0]
        more = " ..." if len(first) > 150 or len(item.splitlines()) > 1 else ""
        print(f"\ncriterion {k}: {first[:150]}{more}")
        unset = [g for g in GATE_RE.findall(item) if gates is not None and _norm_gate(g) not in gates]
        if unset:
            print(f"  SKIPPED (gate {'; '.join(unset)} not set)")
            continue
        if not cmds:
            print("  no command -- check by reading")
            continue
        for cmd in cmds:
            shown = cmd if "\n" not in cmd else cmd.splitlines()[0] + " ...(multi-line)"
            if args.list:
                print(f"  would run: {shown}")
                continue
            if cmd in ran:
                n, code, secs, _ = ran[cmd]
                print(f"  `{shown}` -> exit {code} ({secs:.0f}s), same command as cmd-{n}.log, run once")
                continue
            n = len(ran) + 1
            started = time.monotonic()
            try:
                proc = subprocess.run([bash, "-c", cmd], cwd=str(root), capture_output=True,
                                      timeout=args.timeout)
                code = proc.returncode
                output = (proc.stdout + proc.stderr).decode("utf-8", "replace")
            except subprocess.TimeoutExpired as exc:
                code = "TIMEOUT"
                output = ((exc.stdout or b"") + (exc.stderr or b"")).decode("utf-8", "replace") + \
                    f"\n[run_criteria: killed after {args.timeout}s]"
            secs = time.monotonic() - started
            (out / f"cmd-{n}.log").write_text(f"$ {cmd}\n{output}", encoding="utf-8")
            ran[cmd] = (n, code, secs, output)
            print(f"  `{shown}` -> exit {code} ({secs:.0f}s), cmd-{n}.log")
            if output.strip():
                print(_tail(output))
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
