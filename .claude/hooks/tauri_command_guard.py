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

## What this deliberately does not catch

Written down rather than left implied, per AGENTS.md's rule about recording a
negative as "not observed" rather than "does not happen":

  - **`block_on` reached indirectly.** Only a literal `block_on` inside the
    command body is seen. A helper the command calls is invisible here; that is
    the reviewer agent's job.
  - **`block_on` handed to another thread.** `thread::spawn(|| block_on(..))`
    inside a command is the pattern `hub/instructions.md` blesses for the
    startup worker, but it is flagged all the same. Treat that as a prompt to
    move the call out of the command rather than as a false alarm to suppress.
  - **A column-zero `}` inside a raw string** ends the body early, so a
    violation after it is missed. Rust source with that shape is rare and the
    alternative is a real parser.

Line comments are stripped before the `block_on` test, so a commented-out call
no longer trips it.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SKIP_HINT, TreeState, repo_root, skip_requested  # noqa: E402

WATCHED_DIR = "hub/src-tauri/src"

# Leading whitespace is allowed: inside a `mod` block rustfmt indents the
# attribute, and requiring column zero made every command in a module
# invisible. `#[command]` is the idiomatic short form after
# `use tauri::command;`.
ATTRIBUTE = re.compile(r"^\s*#\[\s*(?:tauri::)?command\b")
SIGNATURE = re.compile(r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?(?P<async>async\s+)?fn\s+(?P<name>\w+)")
LINE_COMMENT = re.compile(r"//.*$", re.MULTILINE)


def attribute_text(lines: list[str], start: int) -> tuple[str, int]:
    """The full attribute beginning at `start`, joined across wrapped lines.

    rustfmt splits any attribute wider than `max_width`, so
    `#[tauri::command(rename_all = "snake_case", async)]` can arrive as four
    lines. Matching only the first of them found no command at all and skipped
    both checks for that function.
    """
    text = ""
    for offset in range(start, min(start + 10, len(lines))):
        text += lines[offset].strip()
        if text.count("[") <= text.count("]"):
            return text, offset
    return text, start


def commands(lines: list[str]):
    """Yield (name, lineno, is_async_fn, attr_text, body) for each command.

    Bodies end at a `}` whose indentation matches the `fn`'s own -- rustfmt
    guarantees that for every item, including one nested in a `mod`.
    """
    index = 0
    while index < len(lines):
        if not ATTRIBUTE.match(lines[index]):
            index += 1
            continue
        attr, attr_end = attribute_text(lines, index)
        index = attr_end + 1
        for offset in range(index, min(index + 12, len(lines))):
            signature = SIGNATURE.match(lines[offset])
            if not signature:
                continue
            indent = lines[offset][: len(lines[offset]) - len(lines[offset].lstrip())]
            closer = indent + "}"
            body = []
            for candidate in lines[offset:]:
                body.append(candidate)
                if candidate.rstrip("\r\n") == closer and len(body) > 1:
                    break
            yield (
                signature.group("name"),
                offset + 1,
                bool(signature.group("async")),
                attr,
                "".join(body),
            )
            index = offset + 1
            break


def inspect(rel: str, source: str) -> list[str]:
    problems = []
    lines = source.splitlines(keepends=True)
    for name, lineno, is_async, attr, body in commands(lines):
        if "block_on" in LINE_COMMENT.sub("", body):
            problems.append(
                f"{rel}:{lineno}  `{name}` calls block_on inside a command.\n"
                f"    It runs on the async runtime, so this panics and the "
                f"frontend's\n"
                f"    IPC promise is never resolved -- the window hangs rather "
                f"than errors.\n"
                f"    Make it `#[tauri::command] async fn` and `.await` the "
                f"call instead."
            )
        if is_async and re.search(r"\basync\b", attr):
            problems.append(
                f"{rel}:{lineno}  `{name}` is an `async fn` carrying "
                f"`#[tauri::command(async)]`.\n"
                f"    The `(async)` form is for *synchronous* fns that must "
                f"leave the UI\n"
                f"    thread. An `async fn` takes plain `#[tauri::command]`."
            )
    return problems


def check(payload, tree: TreeState) -> tuple[int, str]:
    """(rc, message) for one call. `payload` is unused -- this check keys off
    the working tree, never off which tool ran -- and is accepted only so
    every check shares one call shape with the dispatcher."""
    root = tree.root
    problems = []
    for rel in tree.changed_paths(root, WATCHED_DIR):
        if not rel.endswith(".rs"):
            continue
        path = root / rel
        try:
            source = path.read_bytes().decode("utf-8", "replace")
        except OSError:
            # Deleted between the tool call and this hook, or unreadable.
            # Nothing to check, and nothing worth blocking over.
            continue
        problems.extend(inspect(rel, source))

    if not problems:
        return 0, ""

    return 2, "\n\n".join(
        [
            "Tauri command rules violated (hub/instructions.md, 'Adding a command'):",
            *problems,
            SKIP_HINT,
        ]
    )


def main() -> int:
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
