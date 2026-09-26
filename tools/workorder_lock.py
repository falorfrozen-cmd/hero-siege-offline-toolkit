#!/usr/bin/env python3
"""Named locks shared by every process in one checkout, for the parts of a
streamed `/workorder` that must not run twice at once even though the agents
running them do.

Items run as parallel implementers in one checkout (`workorder-rounds.js`,
items mode). Most of what they do is independent, but three things are not:

  * a commit -- `.git/index.lock` fails the second `git commit` at once
    instead of waiting (`tools/item_commit.py` takes `commit`);
  * a build -- two builds in one tree race on their artifacts
    (`tools/run_criteria.py --jobs` takes `build` around a build criterion);
  * a browser suite beyond the cap -- `run_criteria.py --jobs` takes one of
    `browser-0..browser-<n-1>`, so two items' checks together still run at
    most n suites.

A lock is an OS byte-range lock on a file under `git rev-parse --git-path
workorder-locks` (per checkout, so two worktrees never wait on each other).
The OS drops it when the holding process exits, however it exits, so a
crashed agent never leaves a lock behind for someone to clean up.

Usage:
    py -3 tools/workorder_lock.py <name> [--timeout SECONDS] -- <command ...>

runs the command under the lock and exits with its exit code; 75 when the
lock was not free within the timeout (default 1800).
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

LOCK_TIMEOUT_EXIT = 75


def lock_dir(cwd: str | Path | None = None) -> Path:
    """`<git-dir>/workorder-locks` for the checkout `cwd` is in; a temp
    directory beside nothing when `cwd` is not in a repository."""
    result = subprocess.run(["git", "rev-parse", "--git-path", "workorder-locks"], cwd=str(cwd or "."),
                            capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        path = Path(result.stdout.strip())
        if not path.is_absolute():
            path = Path(cwd or ".").resolve() / path
    else:
        import tempfile
        path = Path(tempfile.gettempdir()) / "workorder-locks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _try(handle) -> bool:
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _release(handle) -> None:
    with contextlib.suppress(OSError):
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()


@contextlib.contextmanager
def held(names, directory: Path, timeout: float = 1800.0, poll: float = 0.25):
    """Hold the first free lock among `names` (one name is a mutex; several
    are the slots of a semaphore) and yield its name, or yield None when none
    came free within `timeout`."""
    names = [names] if isinstance(names, str) else list(names)
    deadline = time.monotonic() + timeout
    got = None
    while got is None:
        for name in names:
            handle = open(directory / f"{name}.lock", "a+b")
            if _try(handle):
                got = (name, handle)
                break
            handle.close()
        if got is None:
            if time.monotonic() >= deadline:
                yield None
                return
            time.sleep(poll)
    try:
        yield got[0]
    finally:
        _release(got[1])


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--" not in args or args.index("--") == 0 or args.index("--") == len(args) - 1:
        print(__doc__.strip().split("\n\n")[-2], file=sys.stderr)
        return 2
    cut = args.index("--")
    head, command = args[:cut], args[cut + 1:]
    timeout = 1800.0
    if "--timeout" in head:
        i = head.index("--timeout")
        timeout = float(head.pop(i + 1))
        head.pop(i)
    if len(head) != 1:
        print("workorder_lock: give exactly one lock name", file=sys.stderr)
        return 2
    with held(head[0], lock_dir(), timeout) as name:
        if name is None:
            print(f"workorder_lock: {head[0]} not free after {timeout:.0f}s", file=sys.stderr)
            return LOCK_TIMEOUT_EXIT
        return subprocess.run(command).returncode


if __name__ == "__main__":
    sys.exit(main())
