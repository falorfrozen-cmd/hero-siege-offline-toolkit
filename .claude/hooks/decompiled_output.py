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

## Added lines only, and why that is not a loophole

The rule is about *introducing* game source, so this reads the lines a change
adds, never the whole file.

The first version matched whole file contents, and it was unusable. Five
matches already sit in committed files -- two in
`ForgePact/docs/pet-quest-collector-c-research.md`, two in
`ForgePact/docs/dungeon-key-research.md`, one in the vendored YYToolkit at
`HS-Offline-Tracker/aurie-loader/yytoolkit-modified/`. Some are legitimate
(`AGENTS.md` explicitly keeps measured addresses in `docs/` as research
findings), and one is third-party code that was never ours to police. With
whole-file matching, appending a single paragraph to any of those dirties the
tree and every subsequent tool call exits 2 until someone sets
`HSTK_SKIP_HOOKS=1` -- which is exactly the outcome this file's own notes say
it must avoid. A hook that fires on work it cannot help with does not protect
the rule; it trains people to turn the rule off.

An untracked file has no committed half, so all of it is "added" and all of it
is read.

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
  - **Anything already committed.** See above -- that is a deliberate trade,
    and it means this hook prevents new violations rather than auditing old
    ones. `decompile-output-guard` reviews what a change adds; auditing history
    is a separate job nobody has asked for.
  - **Commit messages.** The rule covers them; this hook sees the working tree.
  - **A submodule the hub's status does not report as dirty** -- a `.gitmodules`
    entry with `ignore = all` would be invisible here.
  - **Its own machinery.** `.claude/` and `tests/test_claude_hooks.py` are
    skipped, because the patterns below and the fixtures that exercise them are
    themselves written in those files. Excluding them is what keeps the hook
    from flagging its own definition on every edit; it is not a claim that
    listings would be acceptable there.

Re-vendoring a third-party dependency full of IDA symbols will trip this. That
is a legitimate `HSTK_SKIP_HOOKS=1` case and the blocking message names it.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SKIP_HINT, changed_entries, repo_root, skip_requested  # noqa: E402

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
                   r"conv\.[a-z]\.[a-z]|cmp\.[a-z]\.[a-z])\b"),
        "a GameMaker bytecode mnemonic",
    ),
    (
        re.compile(r"^\s*```\s*gml\b", re.IGNORECASE),
        "a fenced block tagged as GML source",
    ),
)

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


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
    changed = {path for _, path in changed_entries(root, ".")}
    return [
        rel
        for rel in submodule_dirs(root)
        if rel in changed and (root / rel / ".git").exists()
    ]


def read_text(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8", "replace")
    except OSError:
        # Deleted between the tool call and this hook, or unreadable.
        return None


def added_lines(tree: Path, status: str, rel: str) -> list[tuple[int, str]]:
    """(line number, text) for the lines this change adds to `rel`.

    An untracked file is new in its entirety. For anything git already knows
    about, only the `+` lines of `git diff HEAD` are this hook's business --
    see the module docstring for why whole-file matching was unusable.
    """
    if status.startswith("?"):
        source = read_text(tree / rel)
        if source is None:
            return []
        return list(enumerate(source.splitlines(), start=1))

    out = subprocess.run(
        ["git", "diff", "HEAD", "--unified=0", "--no-color", "--", rel],
        cwd=tree,
        capture_output=True,
        check=False,
    )
    if out.returncode != 0:
        return []

    lines: list[tuple[int, str]] = []
    lineno = 0
    for raw in out.stdout.decode("utf-8", "replace").splitlines():
        hunk = HUNK.match(raw)
        if hunk:
            lineno = int(hunk.group(1))
            continue
        if raw.startswith("+++"):
            continue
        if raw.startswith("+"):
            lines.append((lineno, raw[1:]))
            lineno += 1
    return lines


def inspect(display: str, lines: list[tuple[int, str]]) -> list[str]:
    """One finding per signature, reported at its first added occurrence."""
    problems = []
    for pattern, what in SIGNATURES:
        for lineno, text in lines:
            match = pattern.search(text)
            if not match:
                continue
            excerpt = match.group(0).strip()
            if len(excerpt) > 60:
                excerpt = excerpt[:57] + "..."
            problems.append(
                f"{display}:{lineno}  adds {what}:\n    {excerpt!r}"
            )
            break
    return problems


def scan(tree: Path, prefix: str, skip_excluded: bool) -> list[str]:
    """Every line added to a watched file under one git working tree."""
    problems = []
    for status, rel in changed_entries(tree, "."):
        if skip_excluded and rel.startswith(EXCLUDED_PREFIXES):
            continue
        if not rel.endswith(WATCHED_SUFFIXES):
            continue
        problems.extend(inspect(prefix + rel, added_lines(tree, status, rel)))
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
