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

Usage:
    py -3 tools/run_criteria.py <slug>-plan.md [--out DIR] [--start K]
                                [--timeout SECONDS] [--shell PATH] [--list]

`--start K` resumes at criterion K after a call that hit the Bash tool's
ceiling; `--list` prints what would run and runs nothing. `--timeout` is per
command (default 900). Exit code: 0 when it ran (whatever the commands
exited with), 2 on a usage error, no plan, or no bash.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

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
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    plan = Path(args.plan)
    if not plan.is_file():
        print(f"run_criteria: no such file: {plan}", file=sys.stderr)
        return 2
    text = plan.read_text(encoding="utf-8", errors="replace")
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
