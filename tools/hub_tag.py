"""Check the tag a hub release is being cut as, before anything acts on it.

Run it:

    py -3 tools/hub_tag.py --tag hub-v1.0.2
    py -3 tools/hub_tag.py --tag 1.0.2 --tree 1.0.1 --existing $(git tag --list 'hub-v*')

It prints three `key=value` lines for `$GITHUB_OUTPUT` and nothing else:

    version=1.0.2
    tag=hub-v1.0.2
    bump=true

`bump=true` means the tree still says something else and has to be rewritten
with `cut_release.py` before the tag is created -- the tag has to point at a
commit whose six version fields already agree with it, because that is what
`hub-release.yml` checks before it builds.

Anything wrong exits non-zero having printed nothing, so the workflow stops
before it has bumped, committed or tagged.

`hub-tag.yml` takes this tag from a box on the Actions tab, which makes it the
one place in the release path where a typed string reaches CI directly. Three
refusals earn their place.

A tag that already exists. Tagging into one that has a release gives that tag
two release objects, and `releases/latest/download/latest.json` then resolves to
whichever of the two GitHub calls latest -- which is what hub-v0.1.1 did to
every installed hub's update check.

A version below one already tagged. `releases/latest` would point at it, and
every hub asking what the newest version is would be handed something older than
what it is running. Releasing an older line deliberately means pushing that tag
by hand; `hub-release.yml` still builds it.

Anything that is not three plain numbers. The string ends up in a shell and in
`git tag`, so this is not politeness about formatting.

The tag list is compared numerically, never sorted as text. This repository's
tags are ragged -- `0.1.x` and `1.0.x` both exist -- and `hub-v0.1.4` sorts after
`hub-v1.0.0` in any lexical order.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, List, NamedTuple, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cut_release

ROOT = Path(__file__).resolve().parent.parent

PREFIX = "hub-v"

#: Deliberately the same shape `cut_release.py` will accept, anchored at both
#: ends. Nothing with a suffix, a prefix, a space or a shell character in it
#: gets past here.
#:
#: Each component is `0` or a number that does not start with one. `\d+` alone
#: accepts `01.0.2`, which is three numbers, passes the six-field check, and is
#: then rejected by Cargo -- `invalid leading zero in major version number` --
#: after the tree has been rewritten, `main` has the commit and the tag is
#: pushed. `cut_release.VERSION` is the same pattern, so the gate and the
#: bumper cannot disagree about what is writable.
SHAPE = cut_release.VERSION


class Plan(NamedTuple):
    version: str
    tag: str
    #: Whether the tree has to be rewritten before this can be tagged.
    bump: bool


def tag_names(refs: Iterable[str]) -> set:
    """Tag names out of whatever git printed.

    `git ls-remote --tags` gives `refs/tags/hub-v1.0.0` and a peeled
    `refs/tags/hub-v1.0.0^{}` for every annotated tag; `git tag --list` gives
    the bare name. Both arrive here.
    """
    names = set()
    for ref in refs:
        name = ref.strip()
        if not name:
            continue
        name = name.rsplit("refs/tags/", 1)[-1]
        if name.endswith("^{}"):
            name = name[: -len("^{}")]
        names.add(name)
    return names


def as_numbers(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


def plan(raw: str, refs: Iterable[str], tree: str) -> Plan:
    version = raw.strip()
    if version.startswith(PREFIX):
        version = version[len(PREFIX) :]

    if not SHAPE.match(version):
        hint = ""
        # `[0-9]` here for the same reason as in the pattern itself: with `\d`
        # this would match `1.0.2` + U+0663 and advise dropping a leading zero
        # that is not there.
        if re.match(r"^[0-9]+\.[0-9]+\.[0-9]+$", version):
            # It is three numbers, so saying "give three numbers" would send
            # whoever typed it looking in the wrong place.
            hint = " Drop the leading zero: Cargo refuses to build 01.0.2."
        raise SystemExit(
            f"{raw.strip()!r} is not a version this can tag. "
            f"Give three numbers, as 1.2.3 or {PREFIX}1.2.3.{hint}"
        )

    tag = PREFIX + version
    taken = tag_names(refs)
    if tag in taken:
        raise SystemExit(
            f"{tag} already exists. Tagging it again would give it a second "
            f"release, and the updater endpoint would resolve to whichever one "
            f"GitHub calls latest. Pick a higher version, or delete that tag "
            f"and its release first."
        )

    released = [
        name for name in taken if name.startswith(PREFIX) and SHAPE.match(name[len(PREFIX) :])
    ]
    if released:
        highest = max(released, key=lambda name: as_numbers(name[len(PREFIX) :]))
        if as_numbers(version) < as_numbers(highest[len(PREFIX) :]):
            raise SystemExit(
                f"{tag} is behind {highest}, which is already tagged. Publishing "
                f"it would point releases/latest at an older version than the one "
                f"players are running. To release an older line on purpose, push "
                f"the tag by hand."
            )

    return Plan(version, tag, bump=tree != version)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="check the tag a hub release is being cut as",
    )
    parser.add_argument("--tag", required=True, help="the tag to cut, as typed")
    parser.add_argument(
        "--tree",
        default=None,
        help="the version the tree holds (default: read it with cut_release.py)",
    )
    parser.add_argument(
        "--existing",
        nargs="*",
        default=[],
        help="tags that already exist, as names or refs",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    tree = args.tree or cut_release.current(args.root)
    chosen = plan(args.tag, args.existing, tree)

    # Three bare lines: this is appended straight to `$GITHUB_OUTPUT`, and
    # `bump` is compared as a string because that is the only shape a step's
    # `if:` can test. Nothing is printed on the refusal path, so a workflow
    # that ignored the exit code would still have no version to act on.
    print(f"version={chosen.version}")
    print(f"tag={chosen.tag}")
    print(f"bump={'true' if chosen.bump else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
