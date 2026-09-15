#!/usr/bin/env python3
"""PostToolUse: run the hub's frontend tests when a hub frontend module changes.

`hub/scripts/test.mjs` makes the case for this itself: the frontend tests are
"a second of Node against a twelve-minute Windows build, and the bugs they cover
are the ones nothing else can reach". That ratio is what makes them worth
running automatically and `cargo test` not -- nothing here ever invokes cargo.

Scope is deliberately narrow. Only top-level `hub/src/*.js` edits trigger it,
matching what `test.mjs` itself discovers: those modules are kept free of Svelte
runes so the plain Node runner can import them. Editing a `.svelte` file does
not trigger a run, because no frontend test can import one.
"""

import json
import subprocess
import sys
from pathlib import PurePosixPath, Path

WATCHED_DIR = "hub/src"


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


def edited_path(payload: dict) -> str | None:
    path = (payload.get("tool_input") or {}).get("file_path")
    return path if isinstance(path, str) else None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    path = edited_path(payload)
    if not path:
        return 0

    root = repo_root()
    if root is None:
        return 0

    try:
        rel = PurePosixPath(Path(path).resolve().relative_to(root).as_posix())
    except ValueError:
        return 0

    # Top-level hub/src/*.js only, and never the test files' own edits looping
    # back on themselves any differently -- a changed test should still run.
    if rel.parent != PurePosixPath(WATCHED_DIR) or rel.suffix != ".js":
        return 0

    src = root / WATCHED_DIR
    tests = sorted(p.name for p in src.iterdir() if p.name.endswith(".test.js"))
    if not tests:
        return 0

    run = subprocess.run(
        ["node", "--test", *(f"{WATCHED_DIR}/{name}" for name in tests)],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if run.returncode == 0:
        return 0

    print(
        "\n".join(
            [
                f"The hub's frontend tests fail after editing {rel}.",
                "",
                (run.stdout or "").strip()[-4000:],
                (run.stderr or "").strip()[-2000:],
            ]
        ),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
