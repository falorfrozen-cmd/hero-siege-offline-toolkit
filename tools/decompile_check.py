#!/usr/bin/env python3
"""The per-round half of `decompile-output-guard`, as a command.

    py -3 tools/decompile_check.py <slug> <round> [--base KEY=SHA ...] [--root PATH]
    py -3 tools/decompile_check.py --paths P [P ...] [--base KEY=SHA ...] [--root PATH]

`AGENTS.md` § "Legal: Decompiled Output Never Reaches Any Origin": decompiled
or disassembled Hero Siege source never lands in a tracked file. The
PostToolUse hook `.claude/hooks/decompiled_output.py` catches the shapes only
a decompiler or VM listing produces, in lines a change adds to the working
tree against `HEAD`. A workorder implementer commits as it goes, so by the
end of a round `HEAD` already holds what it added and the hook's view of the
round is empty. This tool runs the hook's own signatures (`SIGNATURES`,
`inspect`, `WATCHED_SUFFIXES`, `EXCLUDED_PREFIXES`, imported, never copied)
over the lines added since a recorded base instead:

* `<slug> <round>`: the paths `round_delta.py delta` reports for that round,
  against the heads its snapshot recorded;
* `--base KEY=SHA` (`.` for the hub, a submodule directory otherwise): the
  lines added since that commit instead, and every path changed since it as
  well, so a hit an earlier round left in the tree stays visible;
* `--paths`: just those paths, against `--base` or `HEAD`.

Measured over 240 rounds, the LLM guard found a BLOCKING item in 3 (the
2026-10-11 /workorder audit, F03), so `workorder-rounds.js` asks the
implementer to run this as its last step and turns a hit into a BLOCKING
finding; the LLM guard still reads prose at the final gate, where a
paraphrase that follows the original statement for statement -- which no
pattern can see -- would land.

Prints one line per hit, `<path>:<line>  adds <what>: <excerpt>`, then a
summary. Exit 0 clean, 1 at least one hit, 2 usage, 3 the round's snapshot
cannot be trusted and no `--base` was given (as `round_delta.py` exits 3).
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
SKILL = REPO / ".claude" / "skills" / "workorder"
HOOKS = REPO / ".claude" / "hooks"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The hook inserts its own directory on sys.path for `_common`; loading it by
# path keeps this tool from depending on the caller's working directory.
hook = _load("decompiled_output", HOOKS / "decompiled_output.py")
round_delta = _load("round_delta", SKILL / "round_delta.py")


def _git(args: list, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True)


def _lines(text: str) -> list:
    return [line for line in text.split("\n") if line]


def _owner(path: str, sub_dirs: list) -> str:
    return next((d for d in sub_dirs if path == d or path.startswith(d + "/")), "")


def changed_since(root: Path, key: str, base: str) -> list:
    """Paths (hub-relative) changed in repo `key` since `base`, working tree and
    untracked files included."""
    repo = root if key == "" else root / key
    out = _git(["diff", "--name-only", "--no-renames", base], repo)
    paths = _lines(out.stdout.decode("utf-8", "replace")) if out.returncode == 0 else []
    untracked = _git(["ls-files", "--others", "--exclude-standard"], repo)
    paths += _lines(untracked.stdout.decode("utf-8", "replace")) if untracked.returncode == 0 else []
    return [p if key == "" else f"{key}/{p}" for p in paths]


def added_lines(repo: Path, rel: str, base: str) -> list:
    """(line number, text) for each line `rel` gained since `base`; a file
    `base` does not hold is new in its entirety."""
    known = bool(base) and _git(["cat-file", "-e", f"{base}:{rel}"], repo).returncode == 0
    if not known:
        text = hook.read_text(repo / rel)
        return [] if text is None else list(enumerate(text.splitlines(), start=1))
    out = _git(["diff", base, "--unified=0", "--no-color", "--", rel], repo)
    if out.returncode != 0:
        return []
    lines, lineno = [], 0
    for raw in out.stdout.decode("utf-8", "replace").splitlines():
        hunk = hook.HUNK.match(raw)
        if hunk:
            lineno = int(hunk.group(1))
            continue
        if raw.startswith("+++"):
            continue
        if raw.startswith("+"):
            lines.append((lineno, raw[1:]))
            lineno += 1
    return lines


def watched(path: str, owner: str) -> bool:
    if not path.endswith(hook.WATCHED_SUFFIXES):
        return False
    # The hook skips its own machinery in the hub only; a submodule has none.
    return bool(owner) or not path.startswith(hook.EXCLUDED_PREFIXES)


def check(root: Path, paths: list, bases: dict, round_heads: dict) -> list:
    """One hit line per signature per file, as the hook's `inspect` reports
    them, flattened to one line each."""
    sub_dirs = sorted(round_delta._submodule_dirs(root), key=len, reverse=True)
    hits = []
    for path in sorted(set(paths)):
        owner = _owner(path, sub_dirs)
        if not watched(path, owner):
            continue
        repo = root / owner if owner else root
        rel = path[len(owner) + 1:] if owner else path
        base = bases.get(owner, round_heads.get(owner, "HEAD"))
        for problem in hook.inspect(path, added_lines(repo, rel, base)):
            where, _, rest = problem.partition("  adds ")
            what, _, excerpt = rest.partition(":\n")
            hits.append(f"{where}  adds {what}: {excerpt.strip()}")
    return hits


def _bases(raw: list) -> dict:
    out = {}
    for item in raw or []:
        key, sep, sha = item.partition("=")
        if not sep or not sha:
            raise ValueError(f"--base takes KEY=SHA (`.` for the hub), not {item!r}")
        out["" if key in (".", "") else key.replace("\\", "/").strip("/")] = sha
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="decompile_check.py", description=__doc__.split("\n\n")[0])
    p.add_argument("slug", nargs="?")
    p.add_argument("round", nargs="?")
    p.add_argument("--paths", nargs="+")
    p.add_argument("--base", action="append")
    p.add_argument("--root")
    a = p.parse_args(argv)
    if (a.paths is None) == (a.slug is None) or (a.slug is not None and a.round is None):
        print("decompile_check: name either <slug> <round> or --paths", file=sys.stderr)
        return 2
    try:
        bases = _bases(a.base)
        root = round_delta.resolve_root(a.root)
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"decompile_check: {exc}", file=sys.stderr)
        return 2
    round_heads: dict = {}
    if a.paths is not None:
        paths = [x.replace("\\", "/").removeprefix("./") for x in a.paths]
    else:
        if not a.round.isdigit():
            print(f"decompile_check: round must be a number, not {a.round!r}", file=sys.stderr)
            return 2
        changed, heads, error = round_delta._delta(root, a.slug, a.round)
        if error and not bases:
            print(f"decompile_check: {error}", file=sys.stderr)
            return 3
        paths, round_heads = list(changed or []), dict(heads or {})
        for key, base in bases.items():
            paths += changed_since(root, key, base)
    hits = check(root, paths, bases, round_heads)
    for hit in hits:
        print(hit)
    print(f"decompile_check: {len(hits)} hit(s) in {len(set(paths))} path(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
