"""Move the hub's version, in all six places at once.

Run it:

    py -3 tools/cut_release.py 0.1.2
    py -3 tools/cut_release.py --check
    py -3 tools/cut_release.py --check --expect 0.1.2

The version lives in six places across five files, and `hub-release.yml` used
to check only two of them against the tag. The two it skipped are the ones that
matter most when something goes wrong: `Cargo.toml` is what `CARGO_PKG_VERSION`
reports, which is the version About shows and the version every line of
`hub.log` is stamped with. A hub whose `Cargo.toml` and `tauri.conf.json`
disagree logs one number, compares against `latest.json` with another, and
hands whoever is debugging it two different answers to "what is installed".

So the same list is used to write the version and to check it, and `--check`
is what CI runs. One implementation, and no way for the checker and the setter
to drift apart.

This deliberately does not touch git. What to say in the commit message is a
judgement about why the release exists, and the 0.1.1 message -- which had to
explain a tag that pointed at a commit reachable from nothing -- is the reason
that is worth writing by hand.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, NamedTuple, Tuple

ROOT = Path(__file__).resolve().parent.parent

# Matches `\r\n` and `\n`, because the worktree is CRLF (`core.autocrlf=true`)
# and a pattern spanning two lines has to tolerate the `\r`.
NL = rb"\r?\n"
EOL = rb"(?=\r?\n)"


class Site(NamedTuple):
    """One place the version is written down."""

    path: str
    what: str
    #: Regex with the version between groups 1 and 2. Anchored on something
    #: unique -- the crate's own name, or a line-start at a known indent --
    #: because both lockfiles are full of other packages' versions and a loose
    #: `"version": "..."` would rewrite a dependency.
    pattern: bytes


def sites(version: bytes) -> List[Site]:
    v = re.escape(version)
    return [
        Site(
            "hub/package.json",
            "the npm manifest",
            rb'(?m)^(  "version": ")' + v + rb'(",)' + EOL,
        ),
        Site(
            "hub/package-lock.json",
            "the lockfile's own header",
            rb'(?m)^(  "name": "hero-siege-toolkit-hub",'
            + NL
            + rb'  "version": ")'
            + v
            + rb'(",)'
            + EOL,
        ),
        Site(
            "hub/package-lock.json",
            "the lockfile's root package entry",
            rb'(?m)^(      "name": "hero-siege-toolkit-hub",'
            + NL
            + rb'      "version": ")'
            + v
            + rb'(",)'
            + EOL,
        ),
        Site(
            "hub/src-tauri/Cargo.toml",
            "the crate manifest, which is what the binary reports",
            rb'(?m)^(version = ")' + v + rb'(")' + EOL,
        ),
        Site(
            "hub/src-tauri/Cargo.lock",
            "the crate lockfile",
            rb'(?m)^(name = "hero-siege-toolkit-hub"'
            + NL
            + rb'version = ")'
            + v
            + rb'(")'
            + EOL,
        ),
        Site(
            "hub/src-tauri/tauri.conf.json",
            "the Tauri config, which is what the updater compares",
            rb'(?m)^(  "version": ")' + v + rb'(",)' + EOL,
        ),
    ]


# Each component is `0` or a number that does not start with one. `\d+` alone
# accepts `01.0.2`, which every check here would pass and Cargo then refuses to
# build: `invalid leading zero in major version number`. `hub_tag.py` reuses
# this pattern, so the tag gate and the bumper cannot disagree about what is
# writable.
VERSION = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")


def current(root: Path) -> str:
    """The version according to `package.json`, which is the one CI reads first."""
    text = (root / "hub" / "package.json").read_bytes()
    found = re.search(rb'(?m)^  "version": "([^"]+)"', text)
    if not found:
        raise SystemExit("hub/package.json has no top-level version")
    return found.group(1).decode()


def check(root: Path, expect: str | None) -> Tuple[bool, List[str]]:
    """Does every site hold the same version, and is it the one expected?"""
    here = current(root)
    lines = []
    ok = True

    for site in sites(here.encode()):
        blob = (root / site.path).read_bytes()
        hits = len(re.findall(site.pattern, blob))
        if hits == 1:
            lines.append(f"  ok      {here}  {site.path} -- {site.what}")
        else:
            ok = False
            # Zero means it holds some other version; more than one means the
            # anchor stopped being unique and this script can no longer promise
            # it is rewriting the right line.
            lines.append(
                f"  MISSING {here}  {site.path} -- {site.what} ({hits} matches)"
            )

    if expect is not None and expect != here:
        ok = False
        lines.append(f"  MISMATCH the manifests say {here}, expected {expect}")

    return ok, lines


def cut(root: Path, new: str) -> List[str]:
    """Rewrite every site, in binary so the CRLF endings survive."""
    if not VERSION.match(new):
        raise SystemExit(f"{new!r} is not a three-part version like 1.2.3")

    here = current(root)
    if here == new:
        raise SystemExit(f"already at {new}")

    ok, lines = check(root, None)
    if not ok:
        # Refusing here rather than rewriting what does match: a half-bumped
        # tree is worse than an un-bumped one, because the workflow's check
        # would pass on the files it looks at and ship the mismatch.
        raise SystemExit(
            "the tree does not agree about its current version, so it cannot be "
            "bumped safely:\n" + "\n".join(lines)
        )

    done = []
    for site in sites(here.encode()):
        path = root / site.path
        blob = path.read_bytes()
        # Text mode would read CRLF as `\n` and write it back bare, flipping
        # the whole file to LF for a one-line change.
        blob, count = re.subn(site.pattern, rb"\g<1>" + new.encode() + rb"\g<2>", blob)
        if count != 1:
            raise SystemExit(f"{site.path}: expected one match, found {count}")
        path.write_bytes(blob)
        done.append(f"  {here} -> {new}  {site.path} -- {site.what}")

    return done


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="move the hub's version in all six places at once",
    )
    parser.add_argument("version", nargs="?", help="the new version, e.g. 0.1.2")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report the version at every site and fail if they disagree",
    )
    parser.add_argument(
        "--expect",
        default=None,
        help="with --check, also require the version to be this (CI passes the tag)",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    if args.check:
        ok, lines = check(args.root, args.expect)
        print(f"hub version: {current(args.root)}")
        print("\n".join(lines))
        if not ok:
            print("::error::the hub's version fields do not agree", file=sys.stderr)
            return 1
        return 0

    if not args.version:
        parser.error("give a version to cut, or --check")

    for line in cut(args.root, args.version):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
