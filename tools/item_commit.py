#!/usr/bin/env python3
"""Commit one streamed-workorder item's files, and only them, while other
items' implementers are editing the same checkout.

Items (`workorder-rounds.js`, items mode) run as parallel implementers in one
checkout, so a plain `git add -A && git commit` would sweep up another item's
half-finished edits, and two commits at once would fail on
`.git/index.lock`. This commits under the checkout's `commit` lock
(`tools/workorder_lock.py`), by pathspec: for each repository the item's
paths belong to (a path under a submodule is committed in that submodule,
its prefix stripped), `git add -A -- <paths>`, then `git commit -- <the
paths that were staged>`, so nothing staged by anyone else rides along. A
path matching nothing is not an error; an item with nothing to commit prints
no `commit` line.

It prints, for the round engine to read back through the implementer:

    commit\t<repo>\t<sha>        one per repository committed ('.' is the hub)
    path\t<path>                 each committed path, hub-relative
    flags\t<instrument,sdk>      which reviewer-trigger patterns the committed
                                 files contain (the same greps as a round's
                                 delta agent), or `flags\t` for none

Usage:
    py -3 tools/item_commit.py --message "<msg>" [--root DIR] -- <path-or-glob> ...

Exit code: 0 committed or nothing to commit; 1 a git command failed (its
output is printed); 2 usage; 75 the commit lock was not free in 10 minutes.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workorder_lock  # noqa: E402

INSTRUMENT_RE = re.compile(r"Rva|GetModuleHandle|MmCreateHook|HookOneScript|InstallScriptHook")
SDK_RE = re.compile(r"CInstance|relicLevel|ItemStatStruct|ItemDefinitionStruct")


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    # index.lock may be held for a moment by a reader's `git status`; retry
    # briefly rather than fail the item.
    for attempt in range(20):
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        if proc.returncode == 0 or "index.lock" not in (proc.stderr or ""):
            break
        time.sleep(0.5)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({proc.returncode}):\n{proc.stdout}{proc.stderr}")
    return proc


def submodules(root: Path) -> list:
    proc = git(root, "config", "--file", ".gitmodules", "--get-regexp", r"submodule\..*\.path", check=False)
    return [line.split(" ", 1)[1].strip() for line in proc.stdout.splitlines() if " " in line]


def split_by_repo(paths: list, subs: list) -> dict:
    """{repo: [pathspec relative to that repo]}; '.' is the hub."""
    out: dict = {}
    for p in paths:
        p = p.replace("\\", "/").removeprefix("./")
        owner = next((s for s in subs if p == s or p.startswith(s + "/")), None)
        if owner and p != owner:
            out.setdefault(owner, []).append(p[len(owner) + 1:])
        else:
            out.setdefault(".", []).append(p)
    return out


def commit(root: Path, message: str, paths: list) -> list:
    """Commit each repository's share of `paths`; return printed lines."""
    lines, committed, flags = [], [], set()
    for repo_key, specs in split_by_repo(paths, submodules(root)).items():
        repo = root if repo_key == "." else root / repo_key
        if not (repo / ".git").exists():
            continue
        # `git add` refuses a pathspec that matches nothing; a declared file
        # the item never created is not an error, so keep only live specs.
        specs = [s for s in specs
                 if git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "--", s).stdout.strip()]
        if not specs:
            continue
        git(repo, "add", "-A", "--", *specs)
        staged = [n for n in git(repo, "diff", "--cached", "--name-only", "--", *specs).stdout.splitlines() if n]
        if not staged:
            continue
        git(repo, "commit", "-q", "-m", message, "--", *staged)
        sha = git(repo, "rev-parse", "HEAD").stdout.strip()
        lines.append(f"commit\t{repo_key}\t{sha}")
        for name in staged:
            hub_path = name if repo_key == "." else f"{repo_key}/{name}"
            committed.append(hub_path)
            f = repo / name
            if f.is_file():
                text = f.read_text(encoding="utf-8", errors="replace")
                if INSTRUMENT_RE.search(text):
                    flags.add("instrument")
                if SDK_RE.search(text):
                    flags.add("sdk")
    lines += [f"path\t{p}" for p in committed]
    lines.append("flags\t" + ",".join(sorted(flags)))
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="item_commit.py")
    parser.add_argument("--message", required=True)
    parser.add_argument("--root", default=None)
    parser.add_argument("paths", nargs="+")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    root = Path(args.root) if args.root else None
    if root is None:
        proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if proc.returncode != 0:
            print("item_commit: not in a git checkout", file=sys.stderr)
            return 2
        root = Path(proc.stdout.strip())
    with workorder_lock.held("commit", workorder_lock.lock_dir(root), timeout=600) as name:
        if name is None:
            print("item_commit: the commit lock was not free after 600s", file=sys.stderr)
            return workorder_lock.LOCK_TIMEOUT_EXIT
        try:
            lines = commit(root, args.message, args.paths)
        except RuntimeError as exc:
            print(str(exc))
            return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
