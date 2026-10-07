"""Build the hub's modified AurieCore.dll: one pinned upstream commit plus the
patch series in `third_party/aurie/`, and nothing else.

    py -3 tools/build_aurie.py all --allow-network
    py -3 tools/build_aurie.py all --upstream C:\\src\\Aurie
    py -3 tools/build_aurie.py verify-dll --dll some\\other\\AurieCore.dll
    py -3 tools/build_aurie.py overlay --overlay build/aurie-overlay Aurie/source/AurieMain.cpp
    py -3 tools/build_aurie.py make-patch --overlay build/aurie-overlay --name 0001-<slug>.patch --message <file>

This file is only an entry point. Every step -- the export of the commit object
and its blob check, the whole-series apply check, the build with `/Brepro`
through a props file and a stripped `CL`/`LINK`, the host tests, the marker
check against pristine upstream, BUILD-INFO, the source zip and the authoring
path -- is `tools/build_yytoolkit.py`, run with its `AURIE` profile. Read that
file's docstring for what each step does and refuses; the subcommands and exit
codes are the same.

What the profile sets: the pin directory `third_party/aurie`, the project
`Aurie/AurieCore.vcxproj`, `AurieCore.dll`, `AurieCore-BUILD-INFO.json` (whose
`tool` is this file), host tests `Aurie/hs-tests/*.cpp`,
`aurie-source-<id>.zip` with every entry under `third_party/aurie/`, the work
directory `%LOCALAPPDATA%\\hstk\\au` (or `%SystemDrive%\\hstk\\au` when that is
too long) with its own marker, `/d1trimfile` in the props file, and the
authoring scope: under `Aurie/`, never `Aurie/source/framework/shared.hpp`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_yytoolkit as core  # noqa: E402
from build_yytoolkit import *  # noqa: E402,F401,F403  (the steps, errors and helpers)

PRODUCT = core.AURIE
DEFAULT_PIN_DIR = PRODUCT.pin_dir


def Context(**kwargs) -> "core.Context":
    """`build_yytoolkit.Context`, with the Aurie profile unless told otherwise."""
    kwargs.setdefault("product", PRODUCT)
    return core.Context(**kwargs)


def default_work_dir(environ: Mapping[str, str]) -> Path:
    return core.default_work_dir(environ, PRODUCT)


def build_source_zip(pin_dir: Path, dest_dir: Path):
    return core.build_source_zip(pin_dir, dest_dir, PRODUCT)


def build_parser():
    return core.build_parser(PRODUCT)


def main(argv: Optional[Sequence[str]] = None, **kwargs) -> int:
    kwargs.setdefault("product", PRODUCT)
    return core.main(argv, **kwargs)


if __name__ == "__main__":
    raise SystemExit(main())
