#!/usr/bin/env python3
"""Shared plumbing for the PostToolUse hooks.

All three hooks key off the **working tree**, not off the tool payload. That
choice is the whole reason this module exists, and it is worth stating once:

A payload-shaped hook only sees `Edit` and `Write`, and only sees them when it
can resolve `tool_input.file_path` against the repository root. Both halves of
that leak. A `sed -i` or a heredoc under `Bash` rewrites a file without ever
producing a `file_path`, and a path the hook cannot resolve returns "not my
file" -- which is indistinguishable from "nothing wrong". During development
exactly that happened: all three hooks exited 0 against a harness feeding them
POSIX-style paths Windows Python could not resolve, and looked installed and
healthy while guarding nothing.

Asking git what changed costs one subprocess (~40ms) and has neither hole.
"""

import os
import subprocess
from pathlib import Path


def repo_root() -> Path | None:
    """The top of the working tree, or None if git cannot say."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    root = out.stdout.strip()
    if not root:
        return None
    # Resolve both sides of any later comparison the same way: a checkout
    # reached through a junction or symlink otherwise never matches a resolved
    # payload path.
    try:
        return Path(root).resolve()
    except OSError:
        return Path(root)


def changed_paths(root: Path, pathspec: str) -> list[str]:
    """Repo-relative paths under `pathspec` that differ from HEAD.

    Includes untracked files, which is deliberate -- a brand new `.rs` file is
    exactly as capable of carrying a violation as an edited one.

    `-uall` is load-bearing, not tidiness. By default git *collapses* an
    untracked directory to a single entry (`?? docs/`) and never names the
    files inside it, so every hook built on this helper was blind to anything
    in a newly created folder -- it saw a directory it had no suffix rule for
    and moved on. That is the same "returns 'not my file', which is
    indistinguishable from 'nothing wrong'" hole this module exists to close,
    reached by a different route. It was found by `decompiled_output.py`'s
    tests, where a listing written to a fresh `docs/` went unflagged; the fix
    belongs here rather than in that hook, because all four share the blindness.

    Uses `-z` so paths containing spaces, quotes or non-ASCII arrive verbatim
    instead of in git's quoted form.
    """
    out = subprocess.run(
        ["git", "status", "--porcelain", "-z", "-uall", "--", pathspec],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if out.returncode != 0:
        return []

    fields = out.stdout.decode("utf-8", "replace").split("\0")
    paths: list[str] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        # A rename entry is followed by its source path in the next field.
        if "R" in status or "C" in status:
            index += 1
        if path:
            paths.append(path)
    return paths


def skip_requested() -> bool:
    """True when the operator has deliberately switched the hooks off.

    There are legitimate states these hooks would otherwise wedge. The catalog
    is the clear one: `catalog/catalog.json` can be rebuilt *unsigned* on a
    machine without `$HUB_MINISIGN_SECRET_KEY`, so a human who has the key can
    sign it later -- `.claude/skills/catalog-rebuild/SKILL.md` describes exactly
    that workflow. Without an escape hatch the signature hook would then fail
    every subsequent tool call in the repository, including the ones needed to
    finish or undo the work.

    A blocking hook with no way out is worse than no hook, so every blocking
    message names this variable.
    """
    return os.environ.get("HSTK_SKIP_HOOKS", "").strip() not in ("", "0", "false")


SKIP_HINT = (
    "If this state is deliberate, set HSTK_SKIP_HOOKS=1 for the session to "
    "silence the toolkit's PostToolUse hooks."
)
