#!/usr/bin/env python3
"""PostToolUse: the mechanical half of the Tauri command rules.

`hub/instructions.md` states the rule after the third hang shipped:

  - a *synchronous* fn that touches disk or the network takes
    `#[tauri::command(async)]`, so it does not run on the WebView2 UI thread;
  - an *async* API takes plain `#[tauri::command]` on an `async fn` and
    `.await`;
  - never `tauri::async_runtime::block_on` inside a command running on that
    runtime. It panics, and the frontend's IPC promise is never resolved, so
    the window sits on "Checking..." forever.

Only the last two are checkable by grep; whether a synchronous command touches
disk is a judgement call and belongs to the `tauri-command-reviewer` agent.
A hang is the worst possible symptom to leave to review, though, because the
app looks alive -- so the part that *can* be caught mechanically is caught here.

`startup_check` keeps its `block_on` legitimately: it is a plain fn on its own
OS thread, not a command, so it never matches.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

WATCHED_DIR = "hub/src-tauri/src"
ATTRIBUTE = re.compile(r"^#\[tauri::command(?P<args>\([^)]*\))?\]")
SIGNATURE = re.compile(r"^\s*(?:pub\s+)?(?P<async>async\s+)?fn\s+(?P<name>\w+)")


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


def commands(lines: list[str]):
    """Yield (name, lineno, is_async_fn, attr_args, body) for each command.

    The attribute must open the line, which is what keeps the several prose
    mentions of `#[tauri::command(async)]` in this file's doc comments from
    being read as code. Bodies end at a `}` in column zero -- rustfmt puts one
    there for every top-level item, and nowhere else.
    """
    for index, line in enumerate(lines):
        attr = ATTRIBUTE.match(line.strip()) if line.startswith("#[") else None
        if not attr:
            continue
        for offset in range(index + 1, min(index + 12, len(lines))):
            signature = SIGNATURE.match(lines[offset])
            if not signature:
                continue
            body = []
            for candidate in lines[offset:]:
                body.append(candidate)
                if candidate.rstrip("\r\n") == "}" and len(body) > 1:
                    break
            yield (
                signature.group("name"),
                offset + 1,
                bool(signature.group("async")),
                attr.group("args") or "",
                "".join(body),
            )
            break


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    path = (payload.get("tool_input") or {}).get("file_path")
    if not isinstance(path, str):
        return 0

    root = repo_root()
    if root is None:
        return 0

    try:
        rel = Path(path).resolve().relative_to(root).as_posix()
    except ValueError:
        return 0
    if not rel.startswith(f"{WATCHED_DIR}/") or not rel.endswith(".rs"):
        return 0

    source = (root / rel).read_bytes().decode("utf-8", "replace")
    lines = source.splitlines(keepends=True)

    problems = []
    for name, lineno, is_async, args, body in commands(lines):
        if "block_on" in body:
            problems.append(
                f"{rel}:{lineno}  `{name}` calls block_on inside a command.\n"
                f"    It runs on the async runtime, so this panics and the "
                f"frontend's\n"
                f"    IPC promise is never resolved -- the window hangs rather "
                f"than errors.\n"
                f"    Make it `#[tauri::command] async fn` and `.await` the "
                f"call instead."
            )
        if is_async and "async" in args:
            problems.append(
                f"{rel}:{lineno}  `{name}` is an `async fn` carrying "
                f"`#[tauri::command(async)]`.\n"
                f"    The `(async)` form is for *synchronous* fns that must "
                f"leave the UI\n"
                f"    thread. An `async fn` takes plain `#[tauri::command]`."
            )

    if not problems:
        return 0

    print(
        "\n\n".join(
            ["Tauri command rules violated (hub/instructions.md, 'Adding a command'):", *problems]
        ),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
