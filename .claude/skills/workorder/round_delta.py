#!/usr/bin/env python3
"""Delta-scoped reviewers' instrument (SPEC.md § "Delta-scoped reviewers").

`snapshot` records a content hash for every changed or untracked path in the
hub, plus the same inside every initialized submodule listed in
`.gitmodules`, so a later `delta` call can name exactly the paths a round
touched. The driver takes a snapshot right before spawning or resuming the
implementer for a round, then diffs against it once the round returns, and
hands a re-run reviewer only that delta instead of the whole cumulative diff.

The property this exists to give: a file that was already dirty *before* the
round started, and that the round never touched, must not appear in the
round's delta merely because it is not clean. That is why state is a content
hash keyed by path rather than "is this path dirty" -- an unchanged dirty file
hashes the same in both snapshots and drops out of the diff, the same as a
file the round touched and then reverted byte-for-byte.

Usage:

    round_delta.py snapshot <slug> <round> [--root PATH]
    round_delta.py delta    <slug> <round> [--root PATH]

`--root` defaults to `git rev-parse --show-toplevel`; tests pass a throwaway
repo instead. Snapshots live at
`<root>/.claude/workorders/.rounds/<slug>/round-<round>.json`.

Exit codes: 0 on success (state or delta printed); 2 on a usage error (bad
slug/round, missing command); 3 when `delta` cannot find or read its
snapshot -- the driver then treats everything as changed, which is the safe
default this instrument's blindness must fail into.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

STATUS_ARGS = ["status", "--porcelain", "-z", "-uall"]


def _run_git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, check=True
    )


def resolve_root(root_arg):
    """`--root` if given, else `git rev-parse --show-toplevel`."""
    if root_arg:
        return Path(root_arg).resolve()
    result = _run_git(["rev-parse", "--show-toplevel"], cwd=Path.cwd())
    return Path(result.stdout.decode("utf-8", "surrogateescape").strip()).resolve()


def _status_paths(cwd, ignore_submodules):
    """Paths `git status --porcelain -z -uall` reports, relative to `cwd`.

    A rename/copy entry is two NUL-separated tokens (new path, then the
    original path) rather than one; both are returned so the old path's
    disappearance from disk is picked up as a 'deleted' value below, without
    needing to special-case rename status codes.
    """
    args = list(STATUS_ARGS)
    if ignore_submodules:
        args.append("--ignore-submodules=all")
    result = _run_git(args, cwd=cwd)
    raw = result.stdout.decode("utf-8", "surrogateescape")
    tokens = raw.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()

    paths = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if len(token) < 4:
            i += 1
            continue
        status, path = token[:2], token[3:]
        paths.append(path)
        if "R" in status or "C" in status:
            i += 1
            if i < len(tokens):
                paths.append(tokens[i])
        i += 1
    return paths


def _submodule_dirs(root):
    """Paths from `.gitmodules`, forward-slashed, that have a `.git` entry.

    Reads `.gitmodules` through `git config` rather than parsing it by hand --
    the file is git's own config format (quoted section names, tab-indented
    values), and `git config --get-regexp` already handles that correctly.
    """
    gitmodules = root / ".gitmodules"
    if not gitmodules.exists():
        return []
    result = subprocess.run(
        ["git", "config", "--file", str(gitmodules), "--get-regexp",
         r"^submodule\..*\.path$"],
        cwd=str(root), capture_output=True,
    )
    if result.returncode != 0:
        return []
    dirs = []
    text = result.stdout.decode("utf-8", "surrogateescape")
    for line in text.splitlines():
        _, _, value = line.partition(" ")
        value = value.strip().replace("\\", "/")
        if value and (root / value / ".git").exists():
            dirs.append(value)
    return dirs


def _hash_path(path):
    """sha1 of the file's raw bytes, or the 'deleted' marker.

    Reads bytes, never text -- a CRLF/LF rewrite of a tracked file must
    change this hash, not be silently normalized away (this worktree is
    CRLF, and a text-mode rewrite flips a whole file to LF).
    """
    try:
        data = path.read_bytes()
    except OSError:
        return "deleted"
    return hashlib.sha1(data).hexdigest()


# This script's own bookkeeping. Excluded unconditionally -- not merely
# relying on `.gitignore` carrying it -- so a snapshot's own file never shows
# up as "changed" in the very state it is recording (it would otherwise: the
# first snapshot in a fresh worktree is itself a new untracked path, and every
# later round would see it too, alongside whatever the round actually did).
_ROUNDS_PREFIX = ".claude/workorders/.rounds/"


def compute_state(root):
    """`{path: hash}` for every changed/untracked path in the hub and in
    every initialized submodule, submodule paths prefixed `<dir>/...`."""
    state = {}
    for rel in _status_paths(root, ignore_submodules=True):
        if rel.startswith(_ROUNDS_PREFIX):
            continue
        state[rel] = _hash_path(root / rel)
    for sub_dir in _submodule_dirs(root):
        sub_root = root / sub_dir
        for rel in _status_paths(sub_root, ignore_submodules=False):
            key = f"{sub_dir}/{rel}"
            if key.startswith(_ROUNDS_PREFIX):
                continue
            state[key] = _hash_path(sub_root / rel)
    return state


def _snapshot_path(root, slug, round_):
    return root / ".claude" / "workorders" / ".rounds" / slug / f"round-{round_}.json"


def cmd_snapshot(root, slug, round_):
    state = compute_state(root)
    path = _snapshot_path(root, slug, round_)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")
    name = path.relative_to(root).as_posix()
    print(name)
    return 0


def cmd_delta(root, slug, round_):
    path = _snapshot_path(root, slug, round_)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"round_delta: snapshot missing or unreadable: {path} ({exc})",
              file=sys.stderr)
        return 3
    try:
        before = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"round_delta: snapshot missing or unreadable: {path} ({exc})",
              file=sys.stderr)
        return 3
    if not isinstance(before, dict):
        print(f"round_delta: snapshot missing or unreadable: {path} (not an object)",
              file=sys.stderr)
        return 3

    after = compute_state(root)
    changed = sorted(
        p for p in (before.keys() | after.keys()) if before.get(p) != after.get(p)
    )
    for p in changed:
        print(p)
    return 0


def _validate_slug(parser, value):
    if not value or "/" in value or "\\" in value or value in (".", ".."):
        parser.error(f"invalid slug (no path separators): {value!r}")


def _validate_round(parser, value):
    if not value or "/" in value or "\\" in value or not value.isdigit():
        parser.error(f"invalid round (digits only, no path separators): {value!r}")


def build_parser():
    parser = argparse.ArgumentParser(prog="round_delta.py")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("snapshot", "delta"):
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.add_argument("round")
        p.add_argument("--root", default=None)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_slug(parser, args.slug)
    _validate_round(parser, args.round)

    try:
        root = resolve_root(args.root)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "surrogateescape") if exc.stderr else ""
        print(f"round_delta: could not resolve repo root: {stderr.strip()}",
              file=sys.stderr)
        return 1

    try:
        if args.command == "snapshot":
            return cmd_snapshot(root, args.slug, args.round)
        return cmd_delta(root, args.slug, args.round)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "surrogateescape") if exc.stderr else ""
        print(f"round_delta: git command failed: {' '.join(exc.cmd)}: {stderr.strip()}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
