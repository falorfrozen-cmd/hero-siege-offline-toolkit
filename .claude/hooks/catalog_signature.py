#!/usr/bin/env python3
"""PostToolUse guard: a touched catalog must still verify against its signature.

`catalog/catalog.json` is a signed artifact. The minisign signature covers the
exact bytes, so any line-ending conversion invalidates it -- see the comment in
`.gitattributes`, which exists because a CRLF rewrite once produced fourteen
signature failures that named everything except the cause.

The reason that failure was expensive is that it is *invisible locally*: a file
a tool writes and commits is never re-checked-out, so it keeps whatever endings
it was written with and nothing complains until CI verifies it. This hook moves
that check onto the machine that made the change.

Silent when the catalog is untouched, so it costs nothing on unrelated edits.
"""

import json
import subprocess
import sys
from pathlib import Path

CATALOG = "catalog/catalog.json"
PUBLIC_KEY = "catalog/catalog-signing.pub"


def repo_root() -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(out.stdout.strip())


def catalog_touched(root: Path) -> bool:
    """True when anything under catalog/ differs from HEAD or is untracked."""
    out = subprocess.run(
        ["git", "status", "--porcelain", "--", "catalog/"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return bool(out.stdout.strip())


def main() -> int:
    # The payload is read so a malformed stdin cannot wedge the hook, but this
    # check keys off the working tree rather than off which tool ran: a catalog
    # can be rewritten by Edit, by a build script under Bash, or by a rebuild
    # this session never saw the path of.
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        pass

    root = repo_root()
    if root is None:
        return 0

    catalog = root / CATALOG
    if not catalog.exists() or not catalog_touched(root):
        return 0

    # Read as bytes throughout. Text mode on Windows is how the endings got
    # flipped in the first place.
    data = catalog.read_bytes()
    crlf = data.count(b"\r\n")

    verify = subprocess.run(
        [
            sys.executable,
            "tools/minisign.py",
            "verify",
            CATALOG,
            "--public-key",
            PUBLIC_KEY,
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if verify.returncode == 0:
        return 0

    lines = [
        "catalog/catalog.json no longer verifies against its signature.",
        "",
        verify.stdout.strip() or verify.stderr.strip(),
        "",
    ]
    if crlf:
        lines += [
            f"The file contains {crlf} CRLF line endings. The signed form is LF.",
            "Something rewrote it in text mode -- Python's open(path, 'w') on",
            "Windows does this. Rewrite it with binary I/O, or rebuild and",
            "re-sign:  py -3 tools/build_catalog.py --sign --key <key outside the repo>",
        ]
    else:
        lines += [
            "Line endings look correct, so this is a content change without a",
            "matching signature. Either re-sign the rebuilt catalog, or check",
            "whether this worktree is carrying a stale copy -- a BAD SIGNATURE",
            "here is more often a stale file than a signing problem.",
            "",
            "Rebuild and re-sign:",
            "  py -3 tools/build_catalog.py --sign --key <key outside the repo>",
        ]
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
