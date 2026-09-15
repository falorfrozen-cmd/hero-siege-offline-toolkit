#!/usr/bin/env python3
"""PostToolUse: the mechanical half of the decompiled-output rule.

`AGENTS.md` § "Legal: Decompiled Output Never Reaches Any Origin" states the
hard rule: never commit, paste or embed decompiled or disassembled Hero Siege
source into any tracked file -- production code, `docs/` notes, commit messages
and comments alike. The constraint is about *output*, not technique; reading a
script body in Ghidra or UndertaleModTool locally is a legitimate research step.

`.gitignore` already excludes decompiler *artifact paths* (`*.i64`, `*.gpr`,
`ghidra_projects/`, `UndertaleModTool_Export/`). That is a backstop against
committing a project file. It does nothing about the likelier accident: listing
text pasted into a tracked `.md` or `.cpp` while writing up a finding.

This hook covers the half a grep can do -- text that is unmistakably a
decompiler or VM listing. Whether a prose paraphrase has crossed from
describing behaviour into reproducing expression is a judgement call and
belongs to the `decompile-output-guard` agent.

Why this rule gets a hook at all when the others describe shipped crashes: the
cost is not a bug. `ForgePact/CREDITS.md` claims AGPL-3.0 original work, and
that claim holds only while no game source text has reached any remote in this
toolkit -- every submodule's own origin included. A mistake here is not
something a later release fixes.

## Submodules

The hub's `git status` reports a dirty submodule as a single changed pointer,
never as the files inside it. `ForgePact/docs/` is exactly where research notes
land, so scanning only the hub would miss the highest-risk directory in the
repository. Each dirty submodule is therefore scanned in its own right.

## What this deliberately does not catch

Written down rather than left implied, per AGENTS.md's rule about recording a
negative as "not observed" rather than "does not happen":

  - **Paraphrase that follows the original statement for statement.** No
    pattern distinguishes that from an honest description. That is the agent's
    job, and it is the failure mode most likely to actually occur.
  - **A listing reformatted** as a markdown list or prose, stripped of the
    syntax below.
  - **Commit messages.** The rule covers them; this hook sees the working tree.
  - **A submodule the hub's status does not report as dirty** -- a `.gitmodules`
    entry with `ignore = all` would be invisible here.
  - **Its own machinery.** `.claude/` and `tests/test_claude_hooks.py` are
    skipped, because the patterns below and the fixtures that exercise them are
    themselves written in those files. Excluding them is what keeps the hook
    from flagging its own definition on every edit; it is not a claim that
    listings would be acceptable there.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SKIP_HINT, changed_paths, repo_root, skip_requested  # noqa: E402

# Text we might plausibly paste a listing into. A binary or an asset cannot
# carry this accident, and reading every changed `.png` would cost real time.
WATCHED_SUFFIXES = (
    ".md", ".txt", ".rst",
    ".cpp", ".hpp", ".h", ".c", ".cc",
    ".py", ".rs", ".ts", ".tsx", ".js", ".mjs", ".svelte",
    ".toml", ".json", ".yml", ".yaml",
)

# Paths holding this hook's own patterns and fixtures. See the module docstring.
EXCLUDED_PREFIXES = (".claude/", "tests/test_claude_hooks.py")

# Each pattern is a shape that only a decompiler, disassembler or GameMaker VM
# listing produces. Deliberately absent: `gml_Script_*` and asset indices.
# AGENTS.md names those as interoperability facts that are *fine* to commit --
# they are the whole point of `hs-game-sdk` -- so matching them would flag the
# SDK's own tables and train everyone to set HSTK_SKIP_HOOKS.
SIGNATURES = (
    (
        re.compile(r"\b(?:FUN|DAT|LAB|PTR|UNK)_[0-9a-f]{6,}\b"),
        "a Ghidra auto-generated symbol",
    ),
    (
        re.compile(r"\b(?:sub|loc|unk|byte|word|dword|qword)_[0-9A-F]{6,}\b"),
        "an IDA auto-generated symbol",
    ),
    (
        re.compile(r"\bundefined[1248]?\s+\w+\s*[;=(]"),
        "a Ghidra decompiler type declaration",
    ),
    (
        re.compile(r"@@(?:This|Other|Global|NULL)@@"),
        "a GameMaker VM pseudo-variable, which only appears in decompiler output",
    ),
    (
        re.compile(r"\bargument(?:1[0-5]|[0-9])\b"),
        "a GML positional argument, which only appears in game script source",
    ),
    (
        re.compile(r"^\s*(?:push(?:glb|loc|var|bltn|i|e)|pop(?:glb|loc|var)|"
                   r"conv\.[a-z]\.[a-z]|cmp\.[a-z]\.[a-z])\b", re.MULTILINE),
        "a GameMaker bytecode mnemonic",
    ),
    (
        re.compile(r"^\s*```\s*gml\b", re.MULTILINE | re.IGNORECASE),
        "a fenced block tagged as GML source",
    ),
)


def submodule_dirs(root: Path) -> list[str]:
    """Submodule paths from `.gitmodules`, in declaration order."""
    try:
        text = (root / ".gitmodules").read_bytes().decode("utf-8", "replace")
    except OSError:
        return []
    return re.findall(r"^\s*path\s*=\s*(.+?)\s*$", text, re.MULTILINE)


def dirty_submodules(root: Path) -> list[str]:
    """Submodules whose own working tree differs from their HEAD.

    The hub reports these as one changed pointer, so this is the only way to
    reach the files inside them -- and `ForgePact/docs/` is where the risk is.
    """
    changed = set(changed_paths(root, "."))
    found = []
    for rel in submodule_dirs(root):
        if rel in changed and (root / rel / ".git").exists():
            found.append(rel)
    return found


def inspect(display: str, source: str) -> list[str]:
    problems = []
    for pattern, what in SIGNATURES:
        match = pattern.search(source)
        if not match:
            continue
        lineno = source.count("\n", 0, match.start()) + 1
        excerpt = match.group(0).strip()
        if len(excerpt) > 60:
            excerpt = excerpt[:57] + "..."
        problems.append(
            f"{display}:{lineno}  contains {what}:\n"
            f"    {excerpt!r}"
        )
    return problems


def scan(tree: Path, prefix: str, skip_excluded: bool) -> list[str]:
    """Every changed watched file under one git working tree."""
    problems = []
    for rel in changed_paths(tree, "."):
        if skip_excluded and rel.startswith(EXCLUDED_PREFIXES):
            continue
        if not rel.endswith(WATCHED_SUFFIXES):
            continue
        try:
            source = (tree / rel).read_bytes().decode("utf-8", "replace")
        except OSError:
            # Deleted between the tool call and this hook, or unreadable.
            continue
        problems.extend(inspect(prefix + rel, source))
    return problems


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

    problems = scan(root, "", skip_excluded=True)
    for rel in dirty_submodules(root):
        problems.extend(scan(root / rel, f"{rel}/", skip_excluded=False))

    if not problems:
        return 0

    print(
        "\n\n".join(
            [
                "Decompiled or disassembled game source may be reaching a "
                "tracked file\n"
                "(AGENTS.md, 'Legal: Decompiled Output Never Reaches Any "
                "Origin'):",
                *problems,
                "Reading a script body locally is fine. Committing it is not, "
                "in any repository\n"
                "here -- every submodule's own origin included. Write up what "
                "you learned in\n"
                "your own words instead: names, indices, measured behaviour "
                "and offsets are\n"
                "interoperability facts and stay welcome.",
                SKIP_HINT,
            ]
        ),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
