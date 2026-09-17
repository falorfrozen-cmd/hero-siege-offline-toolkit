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

It is not a hypothetical hazard. A `tauri dev` run in `hub/` rewrites
`hub/src-tauri/Cargo.toml` from CRLF to LF -- a text-mode rewrite by a tool
nobody suspects, to a file nobody edited. Harmless there; fatal to a signature.

Silent when the catalog is untouched, so it costs nothing on unrelated edits.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SKIP_HINT, TreeState, repo_root, skip_requested  # noqa: E402

CATALOG = "catalog/catalog.json"
PUBLIC_KEY = "catalog/catalog-signing.pub"


def check(payload, tree: TreeState) -> tuple[int, str]:
    """(rc, message) for one call. `tree` is a `_common.TreeState` already
    built for the working tree; `payload` is unused (this check keys off the
    working tree, never off which tool ran or what it touched -- see the
    module docstring), kept only so every check shares one call shape with
    the dispatcher. `main()` below is the standalone CLI; it builds its own
    `TreeState` and prints what this returns, so its stdin/exit/stderr
    contract is unchanged."""
    root = tree.root
    catalog = root / CATALOG
    if not catalog.exists() or not tree.changed_paths(root, "catalog/"):
        return 0, ""

    try:
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
    except OSError as error:
        return 2, (
            f"Could not run the catalog verifier: {error}\n"
            f"The catalog has changed and is therefore unchecked. This is a "
            f"problem with\nthe verifier, not necessarily with the catalog.\n\n"
            f"{SKIP_HINT}"
        )

    if verify.returncode == 0:
        return 0, ""

    output = f"{verify.stdout}\n{verify.stderr}".strip()

    # Distinguish "the signature is wrong" from "the verifier could not run".
    # Reporting a missing key or a traceback as a bad signature sends the
    # reader after a file that is fine, with remediation that cannot help.
    if "BAD SIGNATURE" not in output.upper():
        return 2, "\n".join(
            [
                "The catalog changed, but its signature could not be checked.",
                "",
                output or "(the verifier produced no output)",
                "",
                "This is a verifier problem, not a verdict on the catalog --",
                f"check that {PUBLIC_KEY} and {CATALOG}.minisig are both present",
                "and that tools/minisign.py imports cleanly.",
                "",
                SKIP_HINT,
            ]
        )

    # Read as bytes. Text mode on Windows is how the endings got flipped in the
    # first place.
    crlf = catalog.read_bytes().count(b"\r\n")

    lines = [
        "catalog/catalog.json no longer verifies against its signature.",
        "",
        output,
        "",
    ]
    if crlf:
        lines += [
            f"The file contains {crlf} CRLF line endings. The signed form is LF.",
            "Something rewrote it in text mode -- Python's open(path, 'w') on",
            "Windows does this, and so does the Tauri CLI to Cargo.toml.",
            "Rewrite it with binary I/O, or rebuild and re-sign:",
            "  py -3 tools/build_catalog.py --sign --key <key outside the repo>",
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
    lines += [
        "",
        "Rebuilding unsigned on a machine without the key is a legitimate state,",
        f"and this hook would otherwise block every later tool call. {SKIP_HINT}",
    ]
    return 2, "\n".join(lines)


def main() -> int:
    # The payload is read so a malformed stdin cannot wedge the hook, but this
    # check keys off the working tree rather than off which tool ran: a catalog
    # can be rewritten by Edit, by a build script under Bash, or by a rebuild
    # this session never saw the path of.
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = None

    if skip_requested():
        return 0

    root = repo_root()
    if root is None:
        return 0

    rc, message = check(payload, TreeState(root))
    if message:
        print(message, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
