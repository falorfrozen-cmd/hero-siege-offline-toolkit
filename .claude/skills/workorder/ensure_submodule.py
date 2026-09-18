#!/usr/bin/env python3
"""Give a worktree its OWN copy of a submodule (SPEC.md § "A worktree works
on its own submodule").

Without this, a linked worktree that never initializes a submodule falls
back to reading/writing the MAIN checkout's copy of it -- two worktrees
cannot then work on that submodule at the same time, and work done "in the
worktree" actually lands in the main checkout, invisible to anyone who only
looks at the worktree.

`git submodule update --init --reference <main copy> --dissociate` gives the
worktree its own gitdir (`.git/worktrees/<name>/modules/<module>`) sharing
objects with the main copy only at clone time -- a commit made afterwards in
one is invisible to the other until fetched across by hand. `--dissociate`
then drops the shared-object link so the worktree's copy has no lingering
dependency on the main checkout's object store (proven cheap on this repo:
the module's store measured 14MB).

Usage:

    ensure_submodule.py <module> [--root PATH]

`<module>` must be a path listed in `.gitmodules` (forward- or
back-slashed; compared after normalizing to forward slashes and stripping a
trailing slash), whether or not it is initialized anywhere yet. `--root`
defaults to `git rev-parse --show-toplevel`; tests pass a throwaway repo
instead.

Behavior:

- Already initialized at `<root>/<module>/.git` -> print
  `already initialized: <module> @ <sha>` and exit 0. Idempotent: a second
  run never re-runs `git submodule update`.
- Otherwise, find the MAIN checkout -- the first entry of
  `git worktree list --porcelain` -- and:
    - if `<root>` is a linked worktree (not the main checkout itself) AND
      `<main>/<module>/.git` exists, run
      `git submodule update --init --reference <main>/<module> --dissociate
      -- <module>`;
    - otherwise (this IS the main checkout, or the main checkout has no
      copy of the module either) run a plain
      `git submodule update --init -- <module>`.
  On success, print the module's new HEAD and its (now separate) git dir,
  and, only when a main-checkout copy existed to reference, the exact
  command to bring unpushed work across from it:
  `git -C <module> fetch "<main>/<module>" <branch>`.
- Never touches the main checkout's module, never creates or switches
  branches -- it only checks out the commit `.gitmodules`/the gitlink
  already names.
- In a linked worktree, also provisions this module's local-only build
  prerequisites (`.claude/skills/workorder/local_prereqs.json`) -- files a
  `.gitignore`'d build step needs but no `git submodule update` can produce,
  because they were never committed anywhere. Runs after a fresh init AND on
  the already-initialized path, copying only a listed path that exists in
  the main checkout's copy and is missing here; never overwrites, never
  copies anything unlisted. A run in the main checkout itself provisions
  nothing, since that IS where those files already live.

Exit codes: 0 on success (already-initialized or freshly initialized); 1 on
a git failure (stderr carries git's own message); 2 when `<module>` is not a
path `.gitmodules` declares.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

PREREQS_MANIFEST = Path(".claude") / "skills" / "workorder" / "local_prereqs.json"


def _run_git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, check=True
    )


def resolve_root(root_arg):
    """`--root` if given, else `git rev-parse --show-toplevel`."""
    if root_arg:
        return Path(root_arg).resolve()
    result = _run_git(["rev-parse", "--show-toplevel"], cwd=Path.cwd())
    return Path(result.stdout.decode("utf-8", "surrogateescape").strip()).resolve()


def _gitmodule_paths(root):
    """Every submodule path declared in `.gitmodules`, forward-slashed,
    whether or not it is initialized here -- unlike `round_delta.py`'s
    `_submodule_dirs`, which only yields already-initialized ones, this must
    also recognize the module `ensure_submodule.py` exists to initialize."""
    gitmodules = root / ".gitmodules"
    if not gitmodules.exists():
        return []
    result = subprocess.run(
        ["git", "config", "--file", str(gitmodules), "--get-regexp",
         r"^submodule\..*\.path$"],
        cwd=str(root), capture_output=True,
    )
    if result.returncode != 0:
        return []
    paths = []
    text = result.stdout.decode("utf-8", "surrogateescape")
    for line in text.splitlines():
        _, _, value = line.partition(" ")
        value = value.strip().replace("\\", "/")
        if value:
            paths.append(value)
    return paths


def _repo_head(repo_root):
    """This repo's HEAD sha, or `''` for an unborn HEAD."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_root), capture_output=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", "surrogateescape").strip()


def _git_dir(repo_root):
    """This repo's absolute git dir, or `''` if git cannot report one."""
    result = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=str(repo_root),
        capture_output=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", "surrogateescape").strip()


def _current_branch(repo_root):
    """This repo's checked-out branch name, or `''` on a detached HEAD (or
    if git cannot report one) -- callers fall back to the sha in that case."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(repo_root),
        capture_output=True,
    )
    if result.returncode != 0:
        return ""
    branch = result.stdout.decode("utf-8", "surrogateescape").strip()
    return "" if branch == "HEAD" else branch


def _main_worktree_root(root):
    """The main checkout's path -- the first `worktree` entry `git worktree
    list --porcelain` reports, from any checkout sharing that repo. Falls
    back to `root` itself if git cannot list worktrees at all."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=str(root),
        capture_output=True,
    )
    if result.returncode != 0:
        return root
    text = result.stdout.decode("utf-8", "surrogateescape")
    for line in text.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):]).resolve()
    return root


def _load_prereqs_manifest(root, module):
    """Prerequisite paths (relative to the module root) that
    `local_prereqs.json` lists for `module`. A missing manifest, an entry
    that fails to parse, or a manifest that just doesn't mention this module
    all mean "no prerequisites" rather than an error -- most modules have
    none, and the manifest is optional precisely so they don't need an empty
    entry. The manifest is a tracked file, so `root` (this checkout, worktree
    or not) always carries the same copy the main checkout does."""
    # The checkout's own copy first; failing that, the one beside this script
    # -- so running a newer script against a checkout that predates the
    # manifest still provisions, instead of reporting success having done
    # nothing (measured: exactly that happened in this script's first real run).
    manifest_path = root / PREREQS_MANIFEST
    if not manifest_path.exists():
        manifest_path = Path(__file__).resolve().parent / PREREQS_MANIFEST.name
    if not manifest_path.exists():
        return []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    entries = data.get(module) if isinstance(data, dict) else None
    return entries if isinstance(entries, list) else []


def _is_safe_prereq_entry(entry):
    """An entry must stay inside the module directory: reject anything
    absolute (POSIX `/...` or a Windows drive letter) or that walks out via a
    `..` segment, checked after normalizing back-slashes so a Windows-typed
    entry is not misread as one path segment."""
    if not isinstance(entry, str) or not entry:
        return False
    normalized = entry.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return False
    return ".." not in normalized.split("/")


def provision_local_prereqs(root, module_root, main_module_root, normalized):
    """Copy every prerequisite `local_prereqs.json` lists for `normalized`
    from the main checkout's copy of the module into this one, when it
    exists there and is missing here (SPEC.md § 5). These are local-only,
    git-ignored build inputs (`plugin_build/include`, the shipped mod DLLs) a
    linked worktree's own `git submodule update --init` cannot produce --
    they were never committed anywhere for it to check out. Never overwrites
    an existing path here, never copies anything the manifest does not list,
    and rejects an unsafe entry instead of copying it -- one bad entry never
    stops the rest from being provisioned."""
    entries = _load_prereqs_manifest(root, normalized)
    if not entries:
        # Say so: a silent no-op reads as "prerequisites handled".
        print(f"prerequisites: none listed for {normalized}")
    for entry in entries:
        if not _is_safe_prereq_entry(entry):
            print(f"ensure_submodule: rejected prerequisite (unsafe path): {entry}",
                  file=sys.stderr)
            continue
        dest = module_root / entry
        if dest.exists():
            continue
        src = main_module_root / entry
        if not src.exists():
            print(f"prerequisite not in main checkout: {entry}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
        print(f"copied prerequisite: {entry}")


def cmd_ensure(root, module):
    normalized = module.replace("\\", "/").rstrip("/")
    if normalized not in _gitmodule_paths(root):
        print(f"ensure_submodule: not a submodule in .gitmodules: {module!r}",
              file=sys.stderr)
        return 2

    module_root = root / normalized
    main_root = _main_worktree_root(root)
    is_linked_worktree = main_root.resolve() != root.resolve()
    main_module_root = main_root / normalized

    if (module_root / ".git").exists():
        sha = _repo_head(module_root)
        print(f"already initialized: {normalized} @ {sha}")
        # Re-checked on every run, not only a fresh init: the manifest can
        # gain an entry, or a prerequisite can appear in the main checkout,
        # after this worktree's module was already initialized.
        if is_linked_worktree:
            provision_local_prereqs(root, module_root, main_module_root, normalized)
        return 0

    reference_main = is_linked_worktree and (main_module_root / ".git").exists()

    if reference_main:
        git_args = ["submodule", "update", "--init",
                    "--reference", str(main_module_root), "--dissociate",
                    "--", normalized]
    else:
        git_args = ["submodule", "update", "--init", "--", normalized]

    result = subprocess.run(["git", *git_args], cwd=str(root), capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "surrogateescape").strip()
        print(f"ensure_submodule: git command failed: "
              f"git {' '.join(git_args)}: {stderr}", file=sys.stderr)
        return 1

    sha = _repo_head(module_root)
    git_dir = _git_dir(module_root)
    print(f"initialized: {normalized} @ {sha}")
    print(f"git dir: {git_dir}")
    if reference_main:
        branch = _current_branch(main_module_root) or _repo_head(main_module_root)
        print(f'bring unpushed work across: '
              f'git -C {normalized} fetch "{main_module_root}" {branch}')
    # A fresh init in the main checkout itself has no separate main copy to
    # provision from -- `is_linked_worktree` is false there, so this is the
    # "main checkout run copies nothing" case from the same predicate above.
    if is_linked_worktree:
        provision_local_prereqs(root, module_root, main_module_root, normalized)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="ensure_submodule.py")
    parser.add_argument("module")
    parser.add_argument("--root", default=None)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        root = resolve_root(args.root)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "surrogateescape") if exc.stderr else ""
        print(f"ensure_submodule: could not resolve repo root: {stderr.strip()}",
              file=sys.stderr)
        return 1

    return cmd_ensure(root, args.module)


if __name__ == "__main__":
    sys.exit(main())
