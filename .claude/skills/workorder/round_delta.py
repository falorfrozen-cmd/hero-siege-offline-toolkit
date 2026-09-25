#!/usr/bin/env python3
"""Delta-scoped reviewers' instrument (SPEC.md § "Delta-scoped reviewers").

`snapshot` records a content hash for every changed or untracked path in the
hub, plus the same inside every initialized submodule listed in
`.gitmodules`, plus each of those repos' own HEAD sha, so a later `delta`
call can name exactly the paths a round touched -- including ones the round
committed rather than left dirty. The driver takes a snapshot right before
spawning or resuming the implementer for a round, then diffs against it once
the round returns, and hands a re-run reviewer only that delta instead of the
whole cumulative diff.

The property this exists to give: a file that was already dirty *before* the
round started, and that the round never touched, must not appear in the
round's delta merely because it is not clean. That is why state is a content
hash keyed by path rather than "is this path dirty" -- an unchanged dirty file
hashes the same in both snapshots and drops out of the diff, the same as a
file the round touched and then reverted byte-for-byte.

A second property, added after the first shipped blind to it: a file that was
clean at snapshot time, then edited *and committed* during the round, is
clean again by the time `delta` runs -- `git status` alone cannot see it. So
`delta` also compares each repo's recorded HEAD against its current one and,
when they differ, walks `git diff --name-only` between them (or the whole
tree, when the recorded HEAD was unborn) to recover exactly those paths. See
"Snapshot format v2" below.

Usage:

    round_delta.py snapshot <slug> <round> [--root PATH]
    round_delta.py delta    <slug> <round> [--root PATH]
    round_delta.py heads    <slug> <round> [--root PATH]
    round_delta.py stop     <slug> <round> --lane NAME --verdict PLAN-DEFECT|ADVICE-NEEDED [--root PATH]
    round_delta.py stopped  <slug> <round> [--root PATH]
    round_delta.py size     <slug> <round> [--root PATH]

`--root` defaults to `git rev-parse --show-toplevel`; tests pass a throwaway
repo instead. Snapshots live at
`<root>/.claude/workorders/.rounds/<slug>/round-<round>.json`.

`stop` and `stopped` are the lanes' cooperative stop (issue #176; SKILL.md
Step 2). The workflow cannot cancel a running agent, so a lane about to
return `PLAN-DEFECT` or `ADVICE-NEEDED` runs `stop`, which writes
`round-<round>.stop` beside the snapshot holding `<lane>\\t<verdict>\\n`; every
lane runs `stopped` before each step, which exits 4 and prints that line when
the marker exists and exits 0 silently when it does not. `snapshot` deletes
its round's marker first, because a round is relaunched under the same number
after a replan. The marker lives under `.rounds/`, which `delta` never
reports.

`heads` prints that snapshot's recorded heads, one `<key>\t<sha>` line per
repo -- `.` for the hub, the submodule dir otherwise, an unborn head printing
an empty sha -- so the driver can build reviewers' read commands (base heads
for a `never`-run reviewer, this round's heads for a re-run one) without
re-deriving them. It only checks the snapshot's own shape: it exits 3 for
exactly the reasons `delta` refuses to trust a snapshot at all (missing /
unreadable / not version 2 / malformed), never for the live-repo checks
`delta` layers on top (a recorded head git can no longer diff from, a repo
that came or went) -- those don't apply to a plain read of what was recorded.

`size` is the patch route's post-check (SKILL.md Step 4, "The patch
route"). It takes the same delta `delta` prints and says how big it is: one
`<added>\\t<deleted>\\t<new|existing>\\t<path>` line per path, then
`lines_changed: <N>` and `new_files: <K>`. Lines are counted against the
repo's *recorded* head (`git diff --numstat <head> -- <path>`, working tree
included), so a file that was already dirty before the round also counts its
earlier changes: the figure can only come out too large, never too small,
which fails into "count this round against the cap" rather than past it. A
path absent from the recorded head is `new` and counts every line it now has;
a binary file counts as 10**6 lines. It exits 3 exactly when `delta` would.

Snapshot format v2 (JSON):

    {"version": 2,
     "heads": {"": "<hub HEAD sha, or '' when unborn>",
               "<submodule dir>": "<its HEAD sha>", ...},
     "files": {"<path>": "<sha1 of working bytes> | deleted", ...}}

`heads` has the hub under the key `""` and one key per initialized submodule
(the same set `_submodule_dirs` yields). `files` is what the v1 snapshot was
in full: a content hash per changed/untracked path.

Exit codes: 0 on success (state, delta, size or heads printed; marker written; no
lane stopped); 4 from `stopped` when a lane has stopped; 2 on a usage error
(bad slug/round, missing command, a lane name outside `[a-z0-9-]+` or a
verdict other than the two above); 3 when the snapshot cannot be trusted at
all -- missing, unreadable, a pre-commit-tracking v1 snapshot, or malformed
(both `delta` and `heads`), plus, for `delta` only, a repo present now with no
recorded head or a recorded head git can no longer diff from. The driver then
treats everything as changed, which is the safe default this instrument's
blindness must fail into.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

STATUS_ARGS = ["status", "--porcelain", "-z", "-uall"]
LANE_NAME_RE = re.compile(r"[a-z0-9-]+")
STOP_VERDICTS = ("PLAN-DEFECT", "ADVICE-NEEDED")


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


def _repo_head(repo_root):
    """This repo's HEAD sha, or `''` for an unborn HEAD (no commits yet).

    Uses a raw `subprocess.run` rather than `_run_git` -- `rev-parse HEAD` on
    an unborn branch exits non-zero, which is an expected outcome here, not
    the "git command failed" case `main`'s `CalledProcessError` handler
    reports.
    """
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_root), capture_output=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", "surrogateescape").strip()


def compute_heads(root):
    """`{"": hub HEAD, "<submodule dir>": its HEAD, ...}`."""
    heads = {"": _repo_head(root)}
    for sub_dir in _submodule_dirs(root):
        heads[sub_dir] = _repo_head(root / sub_dir)
    return heads


def _committed_paths(repo_root, recorded_head):
    """Paths whose content differs between `recorded_head` and this repo's
    current HEAD, or `None` if git cannot answer that (the recorded head's
    object is gone).

    `recorded_head == ""` means the repo was unborn at snapshot time -- there
    is nothing to diff against, so every path in the current HEAD's tree is
    "committed" relative to that empty starting point.
    """
    if recorded_head == "":
        args = ["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"]
    else:
        args = ["git", "diff", "--name-only", "-z", "--no-renames",
                 recorded_head, "HEAD"]
    result = subprocess.run(args, cwd=str(repo_root), capture_output=True)
    if result.returncode != 0:
        return None
    raw = result.stdout.decode("utf-8", "surrogateescape")
    tokens = raw.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    return tokens


def _snapshot_path(root, slug, round_):
    return root / ".claude" / "workorders" / ".rounds" / slug / f"round-{round_}.json"


def _stop_path(root, slug, round_):
    return root / ".claude" / "workorders" / ".rounds" / slug / f"round-{round_}.stop"


def cmd_stop(root, slug, round_, lane, verdict):
    path = _stop_path(root, slug, round_)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"{lane}\t{verdict}\n")
    return 0


def cmd_stopped(root, slug, round_):
    path = _stop_path(root, slug, round_)
    try:
        line = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return 0
    print(line)
    return 4


def cmd_snapshot(root, slug, round_):
    # A replan relaunches the round under the same number; the previous
    # launch's stop marker must not stop this launch's lanes.
    _stop_path(root, slug, round_).unlink(missing_ok=True)
    snapshot = {
        "version": 2,
        "heads": compute_heads(root),
        "files": compute_state(root),
    }
    path = _snapshot_path(root, slug, round_)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(snapshot, fh, indent=2, sort_keys=True)
        fh.write("\n")
    name = path.relative_to(root).as_posix()
    print(name)
    return 0


def _load_snapshot(path):
    """Read and validate a v2 snapshot at `path`.

    Returns `(snapshot, None)` on success, or `(None, message)` -- a
    stderr-ready reason -- on failure. Shared between `delta` and `heads`:
    both refuse for exactly these reasons (missing/unreadable, not JSON, not
    an object, not version 2, or a malformed v2 shape); the extra live-repo
    checks in `cmd_delta` below are its own, since `heads` never touches the
    working tree at all.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"snapshot missing or unreadable: {path} ({exc})"
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"snapshot missing or unreadable: {path} ({exc})"
    if not isinstance(snapshot, dict):
        return None, f"snapshot missing or unreadable: {path} (not an object)"
    if snapshot.get("version") != 2:
        return None, (f"snapshot is not version 2 (a v1 flat snapshot "
                       f"predates commit tracking): {path}")
    heads = snapshot.get("heads")
    files = snapshot.get("files")
    if not isinstance(heads, dict) or not isinstance(files, dict):
        return None, f"snapshot missing or unreadable: {path} (malformed v2 snapshot)"
    return snapshot, None


def cmd_heads(root, slug, round_):
    path = _snapshot_path(root, slug, round_)
    snapshot, error = _load_snapshot(path)
    if error:
        print(f"round_delta: {error}", file=sys.stderr)
        return 3
    heads = snapshot["heads"]
    for key in sorted(heads, key=lambda k: (k != "", k)):
        printed_key = "." if key == "" else key
        print(f"{printed_key}\t{heads[key]}")
    return 0


def _delta(root, slug, round_):
    """`(changed paths, snapshot heads, None)`, or `(None, None, message)` when
    the snapshot cannot be trusted -- the shared body of `delta` and `size`."""
    path = _snapshot_path(root, slug, round_)
    snapshot, error = _load_snapshot(path)
    if error:
        return None, None, error
    before_heads = snapshot["heads"]
    before_files = snapshot["files"]

    sub_dirs = set(_submodule_dirs(root))
    committed = set()
    current_heads = compute_heads(root)
    # The symmetric case of "no recorded head" below: a repo the snapshot knew
    # that is gone now (a submodule deinitialized mid-round) cannot be diffed,
    # so its changes would silently drop out. Fail into "run everything".
    for key in before_heads:
        if key not in current_heads:
            return None, None, (f"{key or '<hub>'} was recorded in the snapshot but is "
                                f"not an initialized repo now: {path}")
    for key, current_head in current_heads.items():
        if key not in before_heads:
            where = key or "<hub>"
            return None, None, f"{where} has no recorded head in snapshot: {path}"
        recorded_head = before_heads[key]
        if current_head == recorded_head:
            continue
        repo_root = root if key == "" else root / key
        paths = _committed_paths(repo_root, recorded_head)
        if paths is None:
            where = key or "<hub>"
            return None, None, (f"git cannot diff {where} from its recorded "
                                f"head {recorded_head!r}: {path}")
        if key == "":
            for p in paths:
                if p in sub_dirs or p.startswith(_ROUNDS_PREFIX):
                    continue
                committed.add(p)
        else:
            for p in paths:
                committed.add(f"{key}/{p}")

    after = compute_state(root)
    candidates = before_files.keys() | after.keys() | committed
    changed = []
    for p in sorted(candidates):
        was = before_files.get(p)
        if was is None:
            if p in after or p in committed:
                changed.append(p)
            continue
        current = after[p] if p in after else _hash_path(root / p)
        if current != was:
            changed.append(p)
    return changed, before_heads, None


def cmd_delta(root, slug, round_):
    changed, _, error = _delta(root, slug, round_)
    if error:
        print(f"round_delta: {error}", file=sys.stderr)
        return 3
    for p in changed:
        print(p)
    return 0


BINARY_LINES = 10 ** 6


def _path_size(root, sub_dirs, heads, p):
    """`(added, deleted, is_new)` for one delta path, against its repo's
    recorded head."""
    owner = next((d for d in sub_dirs if p.startswith(f"{d}/")), None)
    repo_root = root / owner if owner else root
    rel = p[len(owner) + 1:] if owner else p
    head = heads.get(owner or "", "")
    in_head = bool(head) and subprocess.run(
        ["git", "cat-file", "-e", f"{head}:{rel}"], cwd=str(repo_root), capture_output=True,
    ).returncode == 0
    if not in_head:
        try:
            data = (repo_root / rel).read_bytes()
        except OSError:
            return 0, 0, False  # never committed and gone again: nothing left to count
        if b"\0" in data:
            return BINARY_LINES, 0, True
        return len(data.splitlines()), 0, True
    result = _run_git(["diff", "--numstat", "--no-renames", head, "--", rel], cwd=repo_root)
    added = deleted = 0
    for line in result.stdout.decode("utf-8", "surrogateescape").splitlines():
        a, _, rest = line.partition("\t")
        d = rest.partition("\t")[0]
        if a == "-" or d == "-":
            return BINARY_LINES, 0, False
        added += int(a)
        deleted += int(d)
    return added, deleted, False


def cmd_size(root, slug, round_):
    changed, heads, error = _delta(root, slug, round_)
    if error:
        print(f"round_delta: {error}", file=sys.stderr)
        return 3
    sub_dirs = sorted(_submodule_dirs(root), key=len, reverse=True)
    total = new_files = 0
    for p in changed:
        added, deleted, is_new = _path_size(root, sub_dirs, heads, p)
        total += added + deleted
        new_files += is_new
        print(f"{added}\t{deleted}\t{'new' if is_new else 'existing'}\t{p}")
    print(f"lines_changed: {total}")
    print(f"new_files: {new_files}")
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
    for name in ("snapshot", "delta", "heads", "stop", "stopped", "size"):
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.add_argument("round")
        p.add_argument("--root", default=None)
        if name == "stop":
            p.add_argument("--lane", required=True)
            p.add_argument("--verdict", required=True)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_slug(parser, args.slug)
    _validate_round(parser, args.round)
    if args.command == "stop":
        if not LANE_NAME_RE.fullmatch(args.lane):
            parser.error(f"invalid lane (want [a-z0-9-]+): {args.lane!r}")
        if args.verdict not in STOP_VERDICTS:
            parser.error(f"invalid verdict (want {' or '.join(STOP_VERDICTS)}): {args.verdict!r}")

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
        if args.command == "heads":
            return cmd_heads(root, args.slug, args.round)
        if args.command == "stop":
            return cmd_stop(root, args.slug, args.round, args.lane, args.verdict)
        if args.command == "stopped":
            return cmd_stopped(root, args.slug, args.round)
        if args.command == "size":
            return cmd_size(root, args.slug, args.round)
        return cmd_delta(root, args.slug, args.round)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "surrogateescape") if exc.stderr else ""
        print(f"round_delta: git command failed: {' '.join(exc.cmd)}: {stderr.strip()}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
