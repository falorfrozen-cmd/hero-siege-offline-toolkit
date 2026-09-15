#!/usr/bin/env python3
"""PostToolUse: run the hub's frontend tests when a hub frontend module changes.

`hub/scripts/test.mjs` makes the case for this itself: the frontend tests are
"a second of Node against a twelve-minute Windows build, and the bugs they cover
are the ones nothing else can reach". That ratio is what makes them worth
running automatically and `cargo test` not -- nothing here ever invokes cargo.

Scope is deliberately narrow: top-level `hub/src/*.js`, matching what
`test.mjs` itself discovers. Editing a `.svelte` file does not trigger a run,
because no frontend test can import one. Note that several watched modules are
named `*.svelte.js` (`library.svelte.js`, `skin.svelte.js`,
`hub-update.svelte.js`) -- those *are* plain `.js` and do trigger a run; only
the rune-free ones carry tests, but running the suite for any of them costs
about a fifth of a second.
"""

import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SKIP_HINT, changed_paths, repo_root, skip_requested  # noqa: E402

WATCHED_DIR = "hub/src"


def main() -> int:
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        pass

    if skip_requested():
        return 0

    root = repo_root()
    if root is None:
        return 0

    touched = [
        rel
        for rel in changed_paths(root, WATCHED_DIR)
        if PurePosixPath(rel).parent == PurePosixPath(WATCHED_DIR)
        and rel.endswith(".js")
    ]
    if not touched:
        return 0

    src = root / WATCHED_DIR
    try:
        tests = sorted(p.name for p in src.iterdir() if p.name.endswith(".test.js"))
    except OSError:
        return 0
    if not tests:
        return 0

    try:
        run = subprocess.run(
            ["node", "--test", *(f"{WATCHED_DIR}/{name}" for name in tests)],
            cwd=root,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        # node absent from PATH, or a .cmd shim that cannot be exec'd directly
        # (nvm/fnm on Windows). Not a test failure; do not block on it.
        print(f"hub frontend tests skipped: could not run node ({error})", file=sys.stderr)
        return 0

    if run.returncode == 0:
        return 0

    print(
        "\n".join(
            [
                "The hub's frontend tests fail. Changed: " + ", ".join(sorted(touched)),
                "",
                (run.stdout or "").strip()[-4000:],
                (run.stderr or "").strip()[-2000:],
                "",
                SKIP_HINT,
            ]
        ),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
