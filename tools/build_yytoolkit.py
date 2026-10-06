"""Build the hub's modified YYToolkit.dll: one pinned upstream commit plus the
patch series in `third_party/yytoolkit/`, and nothing else. The same steps
build the modified AurieCore.dll from `third_party/aurie/`:

    product     pin directory           entry point
    YYToolkit   third_party/yytoolkit   tools/build_yytoolkit.py (this file)
    Aurie       third_party/aurie       tools/build_aurie.py

What differs between them -- the pin directory, the project file, the DLL's
name, the host-test directory, the default work directory, the names of what
`verify-dll` writes -- is a `Product` profile below, and nothing else is. A
copy of this file per product was rejected: a provenance fix to one copy would
miss the other. YYToolkit is the default, so this file's command line,
refusals, exit codes and outputs are what they were before Aurie was added.

Run it:

    py -3 tools/build_yytoolkit.py all --upstream C:\\src\\YYToolkit
    py -3 tools/build_yytoolkit.py materialise --upstream C:\\src\\YYToolkit
    py -3 tools/build_yytoolkit.py apply
    py -3 tools/build_yytoolkit.py build
    py -3 tools/build_yytoolkit.py hosttests
    py -3 tools/build_yytoolkit.py verify-dll
    py -3 tools/build_yytoolkit.py verify-dll --dll some\\other\\YYToolkit.dll
    py -3 tools/build_aurie.py all --allow-network

The DLL this project shipped was built from a tree nobody kept, and its strings
show changes that no document describes. Every step here exists so that cannot
happen again without something failing.

`materialise` exports the pinned commit OBJECT from `--upstream`, never that
clone's working tree, so another HEAD, local edits and stale build output there
are all irrelevant. The commit's tree id is checked against `upstream.json`
before anything is written, and every exported file is re-hashed against the
commit's blob ids afterwards, so "this is upstream at the pin" is measured and
not assumed. `--upstream` is only ever read. The pin lives in `upstream.json`
and nowhere else; this file holds no commit id.

`apply` proves the WHOLE series on a scratch copy before it touches the tree
that gets built. Each patch is checked on top of the ones before it -- handing
`git apply --check` several files validates each against the untouched tree and
wrongly rejects a patch stacked on an earlier one -- and the first one that does
not apply is named. Nothing is applied in that case.

`build` runs upstream's own project file (`YYToolkit.vcxproj`,
`AurieCore.vcxproj`), Release|x64, unedited. `/Brepro` and `/PDBALTPATH`
arrive through a props file this tool writes into the work directory and hands
to MSBuild as `ForceImportAfterCppTargets`, which makes two builds on one
toolchain byte-identical. For Aurie, whose project does not trim the build
directory out of `__FILE__` the way YYToolkit's series makes its project do,
the props file adds `/d1trimfile` too. `CL`, `_CL_`, `LINK` and `_LINK_` are
removed from the environment first: they add compiler and linker flags that no
project file and no log shows.

`hosttests` compiles and runs every `YYToolkit/hs-tests/*.cpp` (for Aurie,
`Aurie/hs-tests/*.cpp`) in the patched tree with `cl`. A tree with no host
tests fails unless `--allow-no-hosttests` says that is expected -- zero tests
passing is not a result.

`verify-dll` is the check that would have caught the original failure. Every
literal a patch declares on a `Log-markers:` header line has to occur in the DLL
as ASCII, and must NOT occur in unpatched upstream, where it would prove
nothing. Only then does it write `YYToolkit-BUILD-INFO.json`, the `.sha256` and
`yytoolkit-source-<id>.zip` beside the DLL (for Aurie `AurieCore-BUILD-INFO.json`
and `aurie-source-<id>.zip`). `live_gameplay_verified` is always
written as false: this tool cannot know, and launching the game is a person's
row in the README table. With `--dll` it checks the markers of any file,
read-only, and writes nothing -- point it at a binary of unknown origin to see
which documented changes it lacks.

    Log-markers: none
    Log-markers: "first literal", "second, with a comma"

The work directory has to be short and outside the repository. YYToolkit's
longest path is 92 characters below it (Aurie's 59) and this worktree's own
prefix is 97, so MAX_PATH is a real limit here, and an over-long `--work-dir` is
refused rather than warned about. A directory that is not empty and was not
created by this tool is refused as well, because every step deletes what it is
about to rebuild. The defaults are `%LOCALAPPDATA%\\hstk\\yk` and `...\\hstk\\au`.

Writing a patch needs no git of your own and no edit outside the checkout,
for a session that may only write inside it:

    py -3 tools/build_aurie.py materialise --allow-network
    py -3 tools/build_aurie.py overlay --overlay build/aurie-overlay Aurie/source/AurieMain.cpp
    (edit build/aurie-overlay/Aurie/source/AurieMain.cpp; create new files there too)
    py -3 tools/build_aurie.py make-patch --overlay build/aurie-overlay \\
        --name 0001-series-identity.patch --message <message file>
    py -3 tools/build_aurie.py make-patch --overlay build/aurie-overlay \\
        --message <message file> --regenerate-last

`overlay` copies named upstream files, as pristine upstream plus the series so
far leaves them, into the overlay at their upstream-relative paths; it will not
overwrite a copy already there without `--replace`. `make-patch` lays the
overlay over that tree and writes the difference as the next numbered patch,
appended to `patches/series`. With `--regenerate-last` the difference is taken
from the tree before the last patch and replaces it, so the overlay only needs
the files that change again. Both work from an empty series. The tool runs git
itself, in its work directory, against an empty git configuration. The patch
has the series' mail shape: a zero commit id, one fixed author and `Date:`,
`[PATCH n/m]` (the earlier patches' totals are renumbered to match), LF only.
The message file is the subject line, a blank line, and a body carrying `Why:`,
`Evidence:`, `Fails-safe:`, `Log-markers:` and `Upstream-status:`. Before
anything is written the whole new series is checked to apply.

`make-patch` refuses, writing nothing: an overlay inside the checkout that git
does not ignore (`build/` is ignored), or one sharing the work or the pin
directory; a `--name` that is not `NNNN-<slug>.patch` with the next number (or
the last one's, with `--regenerate-last`); a message without all five fields,
or whose `Log-markers:` does not parse; an overlay that changes nothing; a path
outside the product's directory (`YYToolkit/`, `Aurie/`) or one the product
marks plugin-facing (the shared headers plugins compile against); CR bytes or
binary content. Deleting a file is not supported: a file absent from the
overlay keeps whatever the tree has. The README rows, the NOTICE entry and a
`series_revision` bump stay the author's to write.

What it never does: launch the game, read or write the game directory, copy the
DLL out of the work directory, or use the network -- unless `--upstream` is
omitted AND `--allow-network` is passed, which fetches the one pinned commit.

Exit codes: 0 done; 1 a step ran and failed (patch does not apply, MSBuild or a
host test failed, a marker is missing); 2 refused before doing anything (work
directory, pin, series, missing `--upstream`, overlay, name or message); 3 the
toolchain is not there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent

#: Longest `--work-dir` accepted, as an absolute path. 40 + the 92 characters
#: YYToolkit's upstream needs below it leaves MSBuild's tlog names and cl/link
#: temp files well inside MAX_PATH (260). Aurie needs 59.
MAX_WORK_DIR_LEN = 40


@dataclass(frozen=True)
class Product:
    """Everything that differs between the upstreams this tool builds. Every
    step reads these and nothing else product-specific, so a fix to a step
    reaches both DLLs."""

    name: str
    #: Written into BUILD-INFO's `tool`, the work marker and the error prefix.
    tool: str
    pin_dir: Path
    #: (directory, project file) inside upstream's tree.
    project: Tuple[str, str]
    dll_name: str
    build_info_name: str
    #: MSBuild names `<ProjectName>.tlog/<ProjectName>.lastbuildstate` after this.
    project_name: str
    host_tests: Tuple[str, ...]
    #: Include directories for the host tests, relative to the project directory.
    host_test_includes: Tuple[str, ...]
    #: `<zip_stem>-<12 hex>.zip`, every entry under `zip_prefix`.
    zip_stem: str
    zip_prefix: str
    #: Last component of the default work directory.
    work_leaf: str
    #: Dropped into the work directory when this tool creates it. Every step
    #: deletes directories called `src`, `o`, `i`... inside it, so it will only
    #: do that in a directory it made (or an empty one).
    work_marker: str
    #: Upstream's longest path below the work directory, for the refusal text.
    longest_upstream_path: int
    #: Inject `/d1trimfile:<project dir>` through the props file, for a project
    #: whose own file does not strip the build directory from `__FILE__`.
    trim_project_dir: bool
    #: Every path a patch touches is under this directory of upstream's tree.
    source_root: str
    #: What plugins compile against. The authoring path refuses a patch that
    #: touches a path starting with one of these: plugins built against the
    #: unmodified pinned headers would silently change ABI.
    plugin_facing: Tuple[str, ...]

    @property
    def error_prefix(self) -> str:
        return Path(self.tool).stem


YYTOOLKIT = Product(
    name="YYToolkit",
    tool="tools/build_yytoolkit.py",
    pin_dir=ROOT / "third_party" / "yytoolkit",
    project=("YYToolkit", "YYToolkit.vcxproj"),
    dll_name="YYToolkit.dll",
    build_info_name="YYToolkit-BUILD-INFO.json",
    project_name="YYToolkit",
    host_tests=("YYToolkit", "hs-tests"),
    host_test_includes=("include", "source"),
    zip_stem="yytoolkit-source",
    zip_prefix="third_party/yytoolkit/",
    work_leaf="yk",
    work_marker=".hstk-yytoolkit-work",
    longest_upstream_path=92,
    # Patch 0006 of the series puts /d1trimfile:$(SolutionDir) in the project.
    trim_project_dir=False,
    source_root="YYToolkit/",
    plugin_facing=("YYToolkit/source/YYTK/Shared/", "ExamplePlugin/"),
)

AURIE = Product(
    name="Aurie",
    tool="tools/build_aurie.py",
    pin_dir=ROOT / "third_party" / "aurie",
    project=("Aurie", "AurieCore.vcxproj"),
    dll_name="AurieCore.dll",
    build_info_name="AurieCore-BUILD-INFO.json",
    project_name="AurieCore",
    host_tests=("Aurie", "hs-tests"),
    host_test_includes=("source", "source/include"),
    zip_stem="aurie-source",
    zip_prefix="third_party/aurie/",
    work_leaf="au",
    work_marker=".hstk-aurie-work",
    longest_upstream_path=59,
    # Upstream's AurieCore.vcxproj does not trim, and the default work
    # directory is under the user profile: a `__FILE__` would carry its path.
    trim_project_dir=True,
    # AuriePatcher/, AurieInstaller/ and TestModule/ are outside it.
    source_root="Aurie/",
    plugin_facing=("Aurie/source/framework/shared.hpp",),
)

PRODUCTS = {"yytoolkit": YYTOOLKIT, "aurie": AURIE}

#: Kept for callers that predate the profiles.
DEFAULT_PIN_DIR = YYTOOLKIT.pin_dir

#: These silently add flags to every cl.exe / link.exe invocation.
STRIPPED_ENV = ("CL", "_CL_", "LINK", "_LINK_")

#: autocrlf off: upstream blobs are LF and the patches are LF, while this
#: machine's default would export CRLF. longpaths on: git resolves a junction to
#: its real, possibly long, path.
GIT_FLAGS = ("-c", "core.autocrlf=false", "-c", "core.longpaths=true")

#: VS 2022 only by default: upstream's project pins PlatformToolset v143.
DEFAULT_VS_RANGE = "[17.0,18.0)"
VC_COMPONENT = "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"

#: A marker this short occurs in any binary, which would let a patch declare its
#: way past the check.
MIN_MARKER_LEN = 8

MATERIALISED, APPLIED, BUILT, HOSTTESTS = (
    "materialised.json", "applied.json", "build.json", "hosttests.json",
)

OBJECT_ID = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
PATCH_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.patch")
MARKER_LINE = re.compile(r"^Log-markers:[ \t]*(.*)$")
MARKER_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')

# Injected with /p:ForceImportAfterCppTargets, so it is evaluated after the
# upstream project's own ItemDefinitionGroup and appends to it. %25 is MSBuild's
# escape for a percent sign: the linker receives /PDBALTPATH:%_PDB%.
REPRO_PROPS = """\
<?xml version="1.0" encoding="utf-8"?>
<!--
  Written by {tool}; passed as
  /p:ForceImportAfterCppTargets=<this file>. Upstream's {project_file} is
  not edited.

  /Brepro              : cl + link stop stamping wall-clock time; the PE
                         TimeDateStamp and the PDB GUID become content hashes.
  /PDBALTPATH:%_PDB%   : the DLL records "{pdb}", not the absolute
                         build directory.{trim_comment}
-->
<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalOptions>%(AdditionalOptions) /Brepro{trim}</AdditionalOptions>
    </ClCompile>
    <Link>
      <AdditionalOptions>%(AdditionalOptions) /Brepro /PDBALTPATH:%25_PDB%25</AdditionalOptions>
    </Link>
  </ItemDefinitionGroup>
</Project>
"""
# $(ProjectDir) ends in a backslash; the second one keeps it from escaping the
# closing quote, as YYToolkit's own project does for $(SolutionDir).
TRIM_OPTION = ' /d1trimfile:"$(ProjectDir)\\"'
TRIM_COMMENT = """
  /d1trimfile:<project directory>
                       : __FILE__ is recorded relative to the project, not
                         under the work directory (a user-profile path)."""
CONFIGURATION = "Release|x64 + repro.props (/Brepro, /PDBALTPATH:%_PDB%)"
CONFIGURATION_TRIMMED = "Release|x64 + repro.props (/Brepro, /PDBALTPATH:%_PDB%, /d1trimfile)"


def repro_props(product: Product) -> str:
    return REPRO_PROPS.format(
        tool=product.tool, project_file=product.project[1],
        pdb=Path(product.dll_name).stem + ".pdb",
        trim_comment=TRIM_COMMENT if product.trim_project_dir else "",
        trim=TRIM_OPTION if product.trim_project_dir else "",
    )


def configuration(product: Product) -> str:
    return CONFIGURATION_TRIMMED if product.trim_project_dir else CONFIGURATION

GIT_TIMEOUT = 600
FETCH_TIMEOUT = 1800
BUILD_TIMEOUT = 3600
COMPILE_TIMEOUT = 900
TEST_TIMEOUT = 300


class ToolError(Exception):
    exit_code = 1


class Failed(ToolError):
    """A step ran and its result is bad."""

    exit_code = 1


class Refused(ToolError):
    """The inputs are unacceptable; nothing was done."""

    exit_code = 2


class ToolchainMissing(ToolError):
    exit_code = 3


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def say(line: str) -> None:
    # Flushed, or MSBuild's own output (which is not captured) overtakes it.
    print(line, flush=True)


def run_process(argv: Sequence[str], *, cwd: Optional[str] = None,
                env: Optional[Mapping[str, str]] = None, timeout: Optional[int] = None,
                capture: bool = True) -> "subprocess.CompletedProcess[str]":
    """The one place a process is started. Tests replace it."""
    return subprocess.run(
        list(argv), cwd=cwd, env=dict(env) if env is not None else None,
        timeout=timeout, capture_output=capture, text=True, encoding="utf-8",
        errors="replace", check=False,
    )


# --------------------------------------------------------------------------
# the pin and the series
# --------------------------------------------------------------------------

class Pin(NamedTuple):
    repo: str
    tag: str
    commit: str
    tree: str


class Patch(NamedTuple):
    name: str
    data: bytes
    sha256: str
    markers: Tuple[str, ...]


def load_pin(pin_dir: Path) -> Pin:
    path = Path(pin_dir) / "upstream.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise Refused(f"cannot read the upstream pin {path}: {error}") from error
    except ValueError as error:
        raise Refused(f"{path} is not valid JSON: {error}") from error
    if not isinstance(raw, dict):
        raise Refused(f"{path} must hold a JSON object")
    values = {}
    for key in Pin._fields:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise Refused(f"{path}: \"{key}\" is missing or empty")
        values[key] = value.strip()
    for key in ("commit", "tree"):
        if not OBJECT_ID.fullmatch(values[key]):
            raise Refused(
                f"{path}: \"{key}\" must be a full 40-character lowercase object id. "
                f"An abbreviation is not a pin."
            )
    return Pin(**values)


def parse_markers(name: str, data: bytes) -> Tuple[str, ...]:
    """The literals a patch's `Log-markers:` header lines declare.

    Only the header is read -- everything before the first `diff --git` -- so a
    hunk that happens to carry the words cannot declare anything.
    """
    if data.startswith(b"diff --git "):
        header = b""
    else:
        header = data.split(b"\ndiff --git ", 1)[0]
    declared = False
    markers: List[str] = []
    for line in header.decode("utf-8", "replace").splitlines():
        match = MARKER_LINE.match(line)
        if not match:
            continue
        declared = True
        value = match.group(1).strip()
        if value.lower() == "none":
            continue
        literals = MARKER_LITERAL.findall(value)
        if not literals or MARKER_LITERAL.sub("", value).strip(" ,\t"):
            raise Refused(
                f"{name}: a Log-markers line must be `none` or double-quoted "
                f"literals separated by commas, got: {value!r}"
            )
        for literal in literals:
            marker = re.sub(r"\\(.)", r"\1", literal)
            if len(marker) < MIN_MARKER_LEN:
                raise Refused(
                    f"{name}: Log-markers literal {marker!r} is shorter than "
                    f"{MIN_MARKER_LEN} characters; it would match any binary"
                )
            if not marker.isascii() or not marker.isprintable():
                raise Refused(f"{name}: Log-markers literal {marker!r} is not printable ASCII")
            if marker not in markers:
                markers.append(marker)
    if not declared:
        raise Refused(
            f"{name} has no `Log-markers:` header line. Declare the strings the "
            f"built DLL must contain, or `Log-markers: none`."
        )
    return tuple(markers)


def load_series(pin_dir: Path, *, allow_empty: bool = False) -> List[Patch]:
    """The patches, in the order `patches/series` lists them.

    Building needs at least one. The authoring path starts from none, so with
    `allow_empty` a series that lists nothing, or does not exist yet, is [].
    """
    patch_dir = Path(pin_dir) / "patches"
    series = patch_dir / "series"
    if allow_empty and not series.exists():
        return []
    try:
        raw = series.read_bytes()
    except OSError as error:
        raise Refused(f"cannot read {series}: {error}") from error
    if b"\r" in raw:
        raise Refused(f"{series} contains CR bytes; it must be LF (see .gitattributes)")
    patches: List[Patch] = []
    for line in raw.decode("utf-8", "replace").split("\n"):
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        # A bare file name and nothing else: the line ends up in a path.
        if not PATCH_NAME.fullmatch(name):
            raise Refused(f"{series}: {name!r} is not a plain <name>.patch file name")
        if any(existing.name == name for existing in patches):
            raise Refused(f"{series}: {name} is listed twice")
        try:
            data = (patch_dir / name).read_bytes()
        except OSError as error:
            raise Refused(f"{series} lists {name}, which cannot be read: {error}") from error
        if b"\r" in data:
            raise Refused(
                f"{name} contains CR bytes; patches must be LF or `git apply` "
                f"fails against the LF export (mark `*.patch -text` in .gitattributes)"
            )
        patches.append(Patch(name, data, hashlib.sha256(data).hexdigest(),
                             parse_markers(name, data)))
    if not patches and not allow_empty:
        raise Refused(f"{series} lists no patches")
    return patches


def series_record(pin: Pin, patches: Sequence[Patch]) -> dict:
    return {
        "upstream_commit": pin.commit,
        "patches": [{"name": p.name, "sha256": p.sha256} for p in patches],
    }


# --------------------------------------------------------------------------
# filesystem helpers
# --------------------------------------------------------------------------

def remove_tree(path: Path) -> None:
    """`rmtree` that also removes the read-only files git leaves behind."""
    target = str(path)
    if not os.path.lexists(target):
        return
    if os.path.islink(target) or not os.path.isdir(target):
        os.unlink(target)
        return

    def retry(function, failed, _error):
        os.chmod(failed, stat.S_IWRITE | stat.S_IREAD)
        function(failed)

    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=retry)
    else:
        shutil.rmtree(target, onerror=retry)


def write_json(path: Path, value) -> None:
    Path(path).write_bytes((json.dumps(value, indent=2) + "\n").encode("utf-8"))


def read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def env_get(environ: Mapping[str, str], name: str) -> Optional[str]:
    """Case-insensitive, as Windows is; a copied `os.environ` is not."""
    if name in environ:
        return environ[name]
    wanted = name.upper()
    for key, value in environ.items():
        if key.upper() == wanted:
            return value
    return None


def is_within(path: Path, parent: Path) -> bool:
    inner = os.path.normcase(str(path))
    outer = os.path.normcase(str(parent))
    try:
        return os.path.commonpath([inner, outer]) == outer
    except ValueError:  # different drives
        return False


def default_work_dir(environ: Mapping[str, str], product: Product = YYTOOLKIT) -> Path:
    leaf = product.work_leaf
    if os.name == "nt":
        local = env_get(environ, "LOCALAPPDATA")
        if local:
            candidate = Path(local) / "hstk" / leaf
            if len(str(candidate)) <= MAX_WORK_DIR_LEN:
                return candidate
        # A long profile name makes even %LOCALAPPDATA% too long.
        drive = env_get(environ, "SystemDrive") or "C:"
        return Path(drive + "\\") / "hstk" / leaf
    cache = env_get(environ, "XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "hstk" / leaf


def git_blob_id(data: bytes) -> str:
    digest = hashlib.sha1(b"blob %d\x00" % len(data), usedforsecurity=False)
    digest.update(data)
    return digest.hexdigest()


def verify_tree(root: Path, expected: Mapping[str, str], what: str) -> None:
    """Every file under `root` is exactly the blob `expected` names, and there
    are no others."""
    root = Path(root)
    actual = {
        p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
    } if root.is_dir() else set()
    missing = sorted(set(expected) - actual)
    extra = sorted(actual - set(expected))
    if missing:
        raise Failed(f"{what}: {missing[0]} is missing ({len(missing)} file(s) missing)")
    if extra:
        raise Failed(f"{what}: {extra[0]} is not part of the pinned commit "
                     f"({len(extra)} unexpected file(s))")
    for rel in sorted(expected):
        if git_blob_id((root / rel).read_bytes()) != expected[rel]:
            raise Failed(f"{what}: {rel} does not match the pinned commit's blob {expected[rel]}")


# --------------------------------------------------------------------------
# context
# --------------------------------------------------------------------------

@dataclass
class Context:
    #: None: the product's own pin directory.
    pin_dir: Optional[Path] = None
    work_dir: Optional[Path] = None
    runner: Runner = run_process
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    #: The CLI never changes this. It exists because the system temp directory
    #: the unit tests must use is itself longer than the limit on Windows.
    max_work_dir_len: int = MAX_WORK_DIR_LEN
    log: Callable[[str], None] = say
    product: Product = YYTOOLKIT
    _prepared: bool = False

    def __post_init__(self) -> None:
        pin_dir = self.pin_dir if self.pin_dir is not None else self.product.pin_dir
        self.pin_dir = Path(os.path.abspath(str(pin_dir)))
        chosen = self.work_dir if self.work_dir is not None else \
            default_work_dir(self.environ, self.product)
        self.work_dir = Path(os.path.abspath(str(chosen)))

    def path(self, *parts: str) -> Path:
        return self.work_dir.joinpath(*parts)

    def env(self) -> Dict[str, str]:
        env = {k: v for k, v in self.environ.items() if k.upper() not in STRIPPED_ENV}
        env["GIT_NO_LAZY_FETCH"] = "1"      # a partial clone must fail, not fetch
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["VSCMD_SKIP_SENDTELEMETRY"] = "1"
        env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
        return env

    def forbidden_roots(self) -> List[Path]:
        roots = [ROOT]
        # <hub>/third_party/yytoolkit -> <hub>
        if len(self.pin_dir.parents) >= 2:
            roots.append(self.pin_dir.parents[1])
        return roots

    def check_work_dir(self) -> None:
        """Refuse before anything is created."""
        work = self.work_dir
        if len(str(work)) > self.max_work_dir_len:
            raise Refused(
                f"--work-dir is {len(str(work))} characters ({work}); the limit is "
                f"{self.max_work_dir_len}. Upstream needs {self.product.longest_upstream_path} "
                f"more below it and MAX_PATH is 260 - use a short path such as "
                f"C:\\hstk\\{self.product.work_leaf}."
            )
        for root in self.forbidden_roots():
            for candidate in (work, Path(os.path.realpath(str(work)))):
                for outer in (root, Path(os.path.realpath(str(root)))):
                    if is_within(candidate, outer):
                        raise Refused(
                            f"--work-dir {work} is inside the repository {root}. Upstream's "
                            f"tree must never sit under a tracked directory; build outside it."
                        )

    def prepare(self) -> None:
        if self._prepared:
            return
        self.check_work_dir()
        work = self.work_dir
        if work.exists():
            if not work.is_dir():
                raise Refused(f"--work-dir {work} is not a directory")
            entries = os.listdir(work)
            if entries and self.product.work_marker not in entries:
                raise Refused(
                    f"--work-dir {work} is not empty and was not created by this tool. "
                    f"Every step deletes what it rebuilds, so it only works in its own directory."
                )
        work.mkdir(parents=True, exist_ok=True)
        marker = work / self.product.work_marker
        if not marker.exists():
            marker.write_text(f"created by {self.product.tool}; safe to delete whole\n",
                              encoding="utf-8")
        self._prepared = True

    def reset(self, *names: str) -> None:
        for name in names:
            try:
                remove_tree(self.path(name))
            except OSError as error:
                raise Failed(f"cannot delete {self.path(name)}: {error}. Is a previous "
                             f"build (MSBuild, mspdbsrv) still holding it?") from error

    def run(self, argv: Sequence[str], *, cwd: Optional[Path] = None,
            timeout: Optional[int] = None, capture: bool = True,
            env_extra: Optional[Mapping[str, str]] = None):
        env = self.env()
        env.update(env_extra or {})
        try:
            return self.runner(list(argv), cwd=str(cwd) if cwd else None, env=env,
                               timeout=timeout, capture=capture)
        except FileNotFoundError as error:
            raise ToolchainMissing(f"cannot start {argv[0]}: {error}") from error
        except subprocess.TimeoutExpired as error:
            raise Failed(f"{argv[0]} did not finish within {timeout} s") from error

    def git(self, *args: str, check: bool = True, timeout: int = GIT_TIMEOUT,
            env_extra: Optional[Mapping[str, str]] = None):
        result = self.run(["git", *GIT_FLAGS, *args], timeout=timeout, env_extra=env_extra)
        if check and result.returncode != 0:
            detail = (result.stderr or "").strip()
            raise Failed(f"git {' '.join(args)} exited {result.returncode}: {detail}")
        return result


def _tail(text: str, lines: int = 25) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


# --------------------------------------------------------------------------
# 1. materialise
# --------------------------------------------------------------------------

def _list_tree(ctx: Context, source: Path, commit: str) -> Dict[str, str]:
    listing = ctx.git("-C", str(source), "ls-tree", "-r", "-z", "--full-tree", commit).stdout
    files: Dict[str, str] = {}
    for entry in listing.split("\x00"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        _mode, kind, object_id = meta.split()
        if kind == "blob":          # a submodule entry ("commit") exports as nothing
            files[path] = object_id
    return files


def _fetch_upstream(ctx: Context, pin: Pin) -> Path:
    """The only code path that reaches the network."""
    if not pin.repo.startswith("https://"):
        raise Refused(f"upstream.json repo {pin.repo!r} is not an https:// URL")
    clone = ctx.path("clone.git")
    remove_tree(clone)
    ctx.git("init", "--bare", "-q", str(clone))
    ctx.log(f"materialise: NETWORK - fetching {pin.commit} from {pin.repo}")
    ctx.git("-C", str(clone), "fetch", "--depth=1", "--no-tags", pin.repo, pin.commit,
            timeout=FETCH_TIMEOUT)
    return clone


def materialise(ctx: Context, upstream: Optional[Path] = None, *,
                allow_network: bool = False) -> dict:
    pin = load_pin(ctx.pin_dir)
    ctx.check_work_dir()
    if upstream is None:
        if not allow_network:
            raise Refused(
                f"no --upstream given. Pass a local clone of {pin.repo} that contains "
                f"{pin.tag}, or add --allow-network to fetch that one commit."
            )
        ctx.prepare()
        source = _fetch_upstream(ctx, pin)
    else:
        source = Path(os.path.abspath(str(upstream)))
        if not source.is_dir():
            raise Refused(f"--upstream {source} is not a directory")
        if is_within(ctx.work_dir, source) or is_within(source, ctx.work_dir):
            raise Refused("--work-dir and --upstream must not contain one another; "
                          "--upstream is never written to")

    present = ctx.git("-C", str(source), "cat-file", "-e", pin.commit + "^{commit}", check=False)
    if present.returncode != 0:
        raise Refused(
            f"{source} does not contain upstream commit {pin.commit} ({pin.tag}). Fetch it "
            f"there yourself - this tool does not write into --upstream."
        )
    tree = ctx.git("-C", str(source), "rev-parse", "--verify", pin.commit + "^{tree}").stdout.strip()
    if tree != pin.tree:
        raise Refused(
            f"commit {pin.commit} in {source} has tree {tree}, but upstream.json pins tree "
            f"{pin.tree}. Refusing to build from a tree the pin does not describe."
        )
    expected = _list_tree(ctx, source, pin.commit)

    # Only now is anything written: a refused pin leaves no trace behind.
    ctx.prepare()
    # A new export invalidates everything built from the old one.
    ctx.reset("up", "src", "chk", "p", "o", "i", "t", "log", "a", "ap",
              MATERIALISED, APPLIED, BUILT, HOSTTESTS, "up.zip")
    archive = ctx.path("up.zip")
    # The commit object, not the checkout: no stale .obj/.iobj, no local edits.
    ctx.git("-C", str(source), "archive", "--format=zip", "-o", str(archive), pin.commit)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(ctx.path("up"))
    archive.unlink()
    try:
        verify_tree(ctx.path("up"), expected, "export")
    except Failed:
        ctx.reset("up")
        raise
    record = {"commit": pin.commit, "tree": pin.tree, "tag": pin.tag, "files": expected}
    write_json(ctx.path(MATERIALISED), record)
    ctx.log(f"materialise: {pin.tag} {pin.commit} (tree {pin.tree}) -> {ctx.path('up')}, "
            f"{len(expected)} file(s) match the commit's blobs")
    return record


# --------------------------------------------------------------------------
# 2. apply
# --------------------------------------------------------------------------

def _patched_copy(ctx: Context, dest: Path, staged: Sequence[Tuple[Patch, Path]],
                  *, check_first: bool) -> None:
    remove_tree(dest)
    shutil.copytree(ctx.path("up"), dest)
    # Its own repository root, so `git apply` inherits no config, attributes or
    # path prefix from whatever repository might enclose the work directory.
    ctx.git("-C", str(dest), "init", "-q")
    total = len(staged)
    for position, (patch, path) in enumerate(staged, 1):
        steps = (["--check"], []) if check_first else ([],)
        for extra in steps:
            result = ctx.git("-C", str(dest), "apply", *extra, "--whitespace=nowarn",
                             str(path), check=False)
            if result.returncode != 0:
                remove_tree(dest)
                raise Failed(
                    f"patch {patch.name} ({position} of {total} in series) does not apply on "
                    f"top of the {position - 1} before it; NOTHING was applied.\n"
                    f"{_tail(result.stderr)}"
                )


def require_materialised(ctx: Context, pin: Pin) -> dict:
    record = read_json(ctx.path(MATERIALISED))
    if not isinstance(record, dict) or not isinstance(record.get("files"), dict):
        raise Refused(f"{ctx.work_dir} holds no materialised upstream; run `materialise` first")
    if record.get("commit") != pin.commit or record.get("tree") != pin.tree:
        raise Refused("the work directory was materialised from a different pin than "
                      "upstream.json now names; run `materialise` again")
    return record


def apply_series(ctx: Context) -> List[Patch]:
    pin = load_pin(ctx.pin_dir)
    patches = load_series(ctx.pin_dir)
    ctx.prepare()
    record = require_materialised(ctx, pin)
    verify_tree(ctx.path("up"), record["files"],
                "the materialised upstream was modified (run `materialise` again)")

    # Whatever was built from an earlier series is stale from here on.
    ctx.reset("src", "chk", "p", "o", "i", "t", "log", APPLIED, BUILT, HOSTTESTS)
    # Apply the bytes that were hashed, from a short path.
    ctx.path("p").mkdir()
    staged = []
    for patch in patches:
        copy = ctx.path("p", patch.name)
        copy.write_bytes(patch.data)
        staged.append((patch, copy))

    _patched_copy(ctx, ctx.path("chk"), staged, check_first=True)
    ctx.reset("chk")
    _patched_copy(ctx, ctx.path("src"), staged, check_first=False)
    write_json(ctx.path(APPLIED), series_record(pin, patches))
    for patch in patches:
        ctx.log(f"apply: {patch.name}  sha256 {patch.sha256}")
    ctx.log(f"apply: {len(patches)} patch(es) applied in series order -> {ctx.path('src')}")
    return patches


def require_applied(ctx: Context, pin: Pin, patches: Sequence[Patch]) -> None:
    record = read_json(ctx.path(APPLIED))
    if record is None or not ctx.path("src").is_dir():
        raise Refused(f"{ctx.work_dir} holds no patched tree; run `apply` first")
    if record != series_record(pin, patches):
        raise Refused("the pin or the patch series changed since `apply` ran; the tree in "
                      "the work directory is not what the series describes. Run `apply` again.")


# --------------------------------------------------------------------------
# 3. build
# --------------------------------------------------------------------------

class Toolchain(NamedTuple):
    msbuild: str
    vcvars64: Optional[str]
    vs_version: Optional[str]


def locate_toolchain(ctx: Context, version_range: str = DEFAULT_VS_RANGE,
                     vswhere: Optional[Path] = None) -> Toolchain:
    if vswhere is None:
        if os.name != "nt":
            raise ToolchainMissing(
                "build and hosttests need Windows with Visual Studio 2022 Build Tools "
                "(C++ workload); materialise, apply and `verify-dll --dll` work anywhere"
            )
        base = env_get(ctx.environ, "ProgramFiles(x86)") or env_get(ctx.environ, "ProgramFiles")
        if not base:
            raise ToolchainMissing("neither ProgramFiles(x86) nor ProgramFiles is set")
        vswhere = Path(base) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not Path(vswhere).is_file():
        raise ToolchainMissing(f"{vswhere} not found; install Visual Studio 2022 Build Tools "
                               f"with the C++ workload")
    select = [str(vswhere), "-latest", "-products", "*", "-version", version_range,
              "-requires", VC_COMPONENT]

    def ask(*query: str) -> Optional[str]:
        lines = [l.strip() for l in (ctx.run(select + list(query)).stdout or "").splitlines()]
        lines = [l for l in lines if l]
        return lines[0] if lines else None

    msbuild = ask("-find", "MSBuild\\**\\Bin\\amd64\\MSBuild.exe")
    if not msbuild:
        raise ToolchainMissing(f"no Visual Studio {version_range} install with the x64 C++ "
                               f"tools ({VC_COMPONENT}) found")
    return Toolchain(msbuild, ask("-find", "VC\\Auxiliary\\Build\\vcvars64.bat"),
                     ask("-property", "installationVersion"))


def _batch_quote(path) -> str:
    text = str(path)
    if '"' in text or "%" in text or not text.isascii():
        raise Refused(f"{text!r} cannot be written into a batch file; use a plain ASCII path")
    return f'"{text}"'


def _write_batch(path: Path, lines: Sequence[str]) -> None:
    path.write_bytes(("\r\n".join(["@echo off", *lines]) + "\r\n").encode("ascii"))


def _cl_version(ctx: Context, toolchain: Toolchain) -> Optional[str]:
    if not toolchain.vcvars64:
        return None
    script = ctx.path("log", "clver.bat")
    _write_batch(script, [f"call {_batch_quote(toolchain.vcvars64)} >nul 2>&1", "cl 2>&1"])
    result = ctx.run(["cmd.exe", "/d", "/c", str(script)], cwd=ctx.path("log"),
                     timeout=COMPILE_TIMEOUT)
    for line in ((result.stdout or "") + "\n" + (result.stderr or "")).splitlines():
        if "Version" in line and "Compiler" in line:
            return line.strip()
    return None


def msbuild_command(ctx: Context, toolchain: Toolchain) -> List[str]:
    sep = os.sep
    project = ctx.product.project
    project_dir = ctx.path("src", project[0])
    return [
        toolchain.msbuild, str(project_dir / project[1]),
        "/t:Rebuild", "/m", "/nr:false", "/nologo",
        "/p:Configuration=Release", "/p:Platform=x64",
        f"/p:SolutionDir={project_dir}{sep}",       # what /d1trimfile strips from __FILE__
        f"/p:OutDir={ctx.path('o')}{sep}",
        f"/p:IntDir={ctx.path('i')}{sep}",
        f"/p:ForceImportAfterCppTargets={ctx.path('repro.props')}",
        f"/flp:logfile={ctx.path('log', 'msbuild.log')};verbosity=detailed;encoding=utf-8",
        f"/flp1:logfile={ctx.path('log', 'warnings.log')};warningsonly;encoding=utf-8",
        "/clp:Summary;Verbosity=minimal",
    ]


def build(ctx: Context, *, toolchain: Optional[Toolchain] = None,
          vs_version_range: str = DEFAULT_VS_RANGE) -> dict:
    pin = load_pin(ctx.pin_dir)
    patches = load_series(ctx.pin_dir)
    ctx.prepare()
    require_applied(ctx, pin, patches)
    product = ctx.product
    project = ctx.path("src", *product.project)
    if not project.is_file():
        raise Refused(f"{project} is missing from the patched tree")
    toolchain = toolchain or locate_toolchain(ctx, vs_version_range)

    # Fresh every time: with /LTCG:incremental a stale .iobj is a correctness
    # hazard, not a speed-up.
    ctx.reset("o", "i", "log", BUILT)
    for name in ("o", "i", "log"):
        ctx.path(name).mkdir()
    ctx.path("repro.props").write_bytes(repro_props(product).encode("utf-8"))

    argv = msbuild_command(ctx, toolchain)
    ctx.log("build: " + " ".join(argv))
    started = time.monotonic()
    result = ctx.run(argv, cwd=project.parent, timeout=BUILD_TIMEOUT, capture=False)
    seconds = round(time.monotonic() - started, 1)
    if result.returncode != 0:
        raise Failed(f"MSBuild exited {result.returncode}; see {ctx.path('log', 'msbuild.log')}")
    dll = ctx.path("o", product.dll_name)
    if not dll.is_file():
        raise Failed(f"MSBuild succeeded but {dll} is missing")

    data = dll.read_bytes()
    version = ctx.run([toolchain.msbuild, "-nologo", "-version"], timeout=GIT_TIMEOUT)
    version_lines = [l.strip() for l in (version.stdout or "").splitlines() if l.strip()]
    state_file = ctx.path("i", product.project_name + ".tlog",
                          product.project_name + ".lastbuildstate")
    try:
        build_state = state_file.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
    except (OSError, IndexError):
        build_state = None
    try:
        warnings = sum(1 for line in ctx.path("log", "warnings.log")
                       .read_text(encoding="utf-8", errors="replace").splitlines()
                       if ": warning " in line)
    except OSError:
        warnings = None
    record = {
        "series": series_record(pin, patches),
        "dll_sha256": hashlib.sha256(data).hexdigest(),
        "dll_size": len(data),
        "toolchain": {
            "visual_studio": toolchain.vs_version,
            "vs_version_range": vs_version_range,
            "msbuild": toolchain.msbuild,
            "msbuild_version": version_lines[-1] if version_lines else None,
            # PlatformToolSet / VCToolsVersion / TargetPlatformVersion, as MSBuild recorded them
            "build_state": build_state,
            "cl": _cl_version(ctx, toolchain),
        },
        "configuration": configuration(product),
        "warnings": warnings,
    }
    write_json(ctx.path(BUILT), record)
    ctx.log(f"build: {seconds} s, {warnings} warning(s)")
    ctx.log(f"build: toolchain {build_state}")
    ctx.log(f"build: {dll}  {len(data)} bytes  sha256 {record['dll_sha256']}")
    return record


# --------------------------------------------------------------------------
# 4. hosttests
# --------------------------------------------------------------------------

def hosttests(ctx: Context, *, toolchain: Optional[Toolchain] = None,
              vs_version_range: str = DEFAULT_VS_RANGE, allow_none: bool = False) -> dict:
    pin = load_pin(ctx.pin_dir)
    patches = load_series(ctx.pin_dir)
    ctx.prepare()
    require_applied(ctx, pin, patches)
    product = ctx.product
    test_dir = ctx.path("src", *product.host_tests)
    sources = sorted(test_dir.glob("*.cpp")) if test_dir.is_dir() else []
    ctx.reset("t", HOSTTESTS)
    record = {"series": series_record(pin, patches), "ran": 0, "passed": 0, "files": []}
    if not sources:
        if not allow_none:
            raise Failed(
                f"no host tests: {'/'.join(product.host_tests)}/*.cpp matches nothing in the patched "
                f"tree. Zero tests passing is not a result; pass --allow-no-hosttests if the "
                f"series really carries none."
            )
        ctx.log("hosttests: the patched tree carries no host tests; nothing ran")
        write_json(ctx.path(HOSTTESTS), record)
        return record

    toolchain = toolchain or locate_toolchain(ctx, vs_version_range)
    if not toolchain.vcvars64:
        raise ToolchainMissing("vcvars64.bat not found in the Visual Studio install")
    out = ctx.path("t")
    out.mkdir()
    project_dir = ctx.path("src", product.project[0])
    includes = [d for d in [project_dir.joinpath(*rel.split("/"))
                            for rel in product.host_test_includes] + [test_dir]
                if d.is_dir()]
    failures: List[str] = []
    for source in sources:
        stem = source.stem
        # A batch file rather than `cmd /c "<quoted line>"`, whose quote handling
        # drops the command when several quoted paths appear.
        script = out / f"{stem}.bat"
        command = " ".join(
            ["cl", "/nologo", "/std:c++latest", "/EHsc", "/permissive-", "/W3"]
            + [f"/I {_batch_quote(d)}" for d in includes]
            + [_batch_quote(source), f"/Fe:{_batch_quote(stem + '.exe')}"]
        )
        _write_batch(script, [
            f"call {_batch_quote(toolchain.vcvars64)} >nul 2>&1",
            "if errorlevel 1 exit /b 9",
            command,
            "exit /b %errorlevel%",
        ])
        record["ran"] += 1
        record["files"].append(source.name)
        compiled = ctx.run(["cmd.exe", "/d", "/c", str(script)], cwd=out, timeout=COMPILE_TIMEOUT)
        exe = out / f"{stem}.exe"
        if compiled.returncode != 0 or not exe.is_file():
            failures.append(f"{source.name}: did not compile (exit {compiled.returncode})\n"
                            f"{_tail(compiled.stdout)}\n{_tail(compiled.stderr)}".rstrip())
            continue
        ran = ctx.run([str(exe)], cwd=out, timeout=TEST_TIMEOUT)
        if ran.returncode != 0:
            failures.append(f"{source.name}: exited {ran.returncode}\n"
                            f"{_tail(ran.stdout)}\n{_tail(ran.stderr)}".rstrip())
            continue
        record["passed"] += 1
        ctx.log(f"hosttests: {source.name} passed")
    if failures:
        raise Failed(f"{len(failures)} of {record['ran']} host test(s) failed:\n"
                     + "\n".join(failures))
    write_json(ctx.path(HOSTTESTS), record)
    ctx.log(f"hosttests: {record['passed']} of {record['ran']} passed")
    return record


# --------------------------------------------------------------------------
# 5. verify-dll
# --------------------------------------------------------------------------

def check_markers(patches: Sequence[Patch], dll: bytes, pristine: Optional[Path]) -> List[dict]:
    """Every declared literal is in the DLL, and none is in unpatched upstream.

    Returns what was verified; raises `Failed` naming every marker and patch
    that was not.
    """
    problems: List[str] = []
    verified: List[dict] = []
    sources: List[Tuple[str, bytes]] = []
    if pristine is not None and pristine.is_dir():
        sources = [(p.relative_to(pristine).as_posix(), p.read_bytes())
                   for p in sorted(pristine.rglob("*")) if p.is_file()]
    for patch in patches:
        for marker in patch.markers:
            needle = marker.encode("ascii")
            if needle not in dll:
                wide = " (it IS present as UTF-16, which does not count)" \
                    if marker.encode("utf-16-le") in dll else ""
                problems.append(f"marker {marker!r} declared by {patch.name} is NOT in the DLL{wide}")
                continue
            origin = next((rel for rel, data in sources if needle in data), None)
            if origin is not None:
                problems.append(
                    f"marker {marker!r} declared by {patch.name} already occurs in unpatched "
                    f"upstream ({origin}); it cannot tell a patched build from an unpatched one"
                )
                continue
            verified.append({"patch": patch.name, "marker": marker})
    if problems:
        raise Failed(
            "the DLL does not match the documented patch series:\n  " + "\n  ".join(problems)
        )
    return verified


def build_source_zip(pin_dir: Path, dest_dir: Path,
                     product: Product = YYTOOLKIT) -> Tuple[Path, str]:
    """A deterministic zip of the pin directory (`third_party/<product>`),
    named by its content."""
    pin_dir = Path(pin_dir)
    files = sorted(
        (p.relative_to(pin_dir).as_posix(), p) for p in pin_dir.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    listing = hashlib.sha256()
    contents = []
    for rel, path in files:
        data = path.read_bytes()
        contents.append((rel, data))
        listing.update(f"{rel}\x00{hashlib.sha256(data).hexdigest()}\n".encode("utf-8"))
    source_id = listing.hexdigest()
    dest = Path(dest_dir) / f"{product.zip_stem}-{source_id[:12]}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as bundle:
        for rel, data in contents:
            entry = zipfile.ZipInfo(product.zip_prefix + rel, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o644 << 16
            bundle.writestr(entry, data)
    return dest, source_id


def _hub_commit(ctx: Context) -> Tuple[Optional[str], Optional[bool]]:
    head = ctx.git("-C", str(ctx.pin_dir), "rev-parse", "--verify", "HEAD", check=False)
    if head.returncode != 0 or not OBJECT_ID.fullmatch(head.stdout.strip()):
        return None, None
    status = ctx.git("-C", str(ctx.pin_dir), "status", "--porcelain", "--", ".", check=False)
    dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    return head.stdout.strip(), dirty


def _check_expected(sha256: str, expected: Optional[str]) -> None:
    if expected is None:
        return
    wanted = expected.strip().lower()
    if not SHA256.fullmatch(wanted):
        raise Refused("--expected-sha256 must be 64 hexadecimal characters")
    if sha256 != wanted:
        raise Failed(f"sha256 mismatch: the DLL is {sha256}, expected {wanted}. The hash is "
                     f"only stable on the toolchain it was recorded with.")


def verify_dll(ctx: Context, *, dll: Optional[Path] = None,
               expected_sha256: Optional[str] = None) -> dict:
    pin = load_pin(ctx.pin_dir)
    patches = load_series(ctx.pin_dir)
    materialised = read_json(ctx.path(MATERIALISED))
    pristine = ctx.path("up") if (isinstance(materialised, dict)
                                  and materialised.get("commit") == pin.commit) else None

    if dll is not None:
        # Any binary, read-only, nothing written: which documented changes does
        # it carry? Provenance cannot be vouched for, so no BUILD-INFO.
        path = Path(os.path.abspath(str(dll)))
        try:
            data = path.read_bytes()
        except OSError as error:
            raise Refused(f"cannot read --dll {path}: {error}") from error
        sha256 = hashlib.sha256(data).hexdigest()
        ctx.log(f"verify-dll: {path}  {len(data)} bytes  sha256 {sha256}")
        if pristine is None:
            ctx.log("verify-dll: no materialised upstream in the work directory; the "
                    "'marker is absent from unpatched upstream' control was skipped")
        verified = check_markers(patches, data, pristine)
        _check_expected(sha256, expected_sha256)
        ctx.log(f"verify-dll: {len(verified)} marker(s) present; markers only - no BUILD-INFO "
                f"is written for a DLL this tool did not just build")
        return {"dll": {"size": len(data), "sha256": sha256}, "markers_verified": verified}

    ctx.prepare()
    product = ctx.product
    dll_name, build_info_name = product.dll_name, product.build_info_name
    out = ctx.path("o")
    # A failed verification must not leave an older success lying beside the DLL.
    if out.is_dir():
        for stale in list(out.glob(product.zip_stem + "-*.zip")) + [out / build_info_name,
                                                                     out / (dll_name + ".sha256")]:
            if stale.is_file():
                stale.unlink()
    require_applied(ctx, pin, patches)
    built = read_json(ctx.path(BUILT))
    if not isinstance(built, dict):
        raise Refused(f"{ctx.work_dir} holds no build; run `build` first")
    if built.get("series") != series_record(pin, patches):
        raise Refused("the DLL in the work directory was built from a different series; "
                      "run `build` again")
    path = out / dll_name
    try:
        data = path.read_bytes()
    except OSError as error:
        raise Refused(f"cannot read {path}: {error}") from error
    sha256 = hashlib.sha256(data).hexdigest()
    if sha256 != built.get("dll_sha256"):
        raise Failed(f"{path} is not the file `build` produced (sha256 {sha256}, built "
                     f"{built.get('dll_sha256')}); run `build` again")
    if pristine is None:
        raise Refused("the work directory holds no materialised upstream for this pin")

    verified = check_markers(patches, data, pristine)
    _check_expected(sha256, expected_sha256)

    tests = read_json(ctx.path(HOSTTESTS))
    if not isinstance(tests, dict) or tests.get("series") != series_record(pin, patches):
        tests = None
    hub_commit, hub_dirty = _hub_commit(ctx)
    archive, source_id = build_source_zip(ctx.pin_dir, out, product)
    info = {
        "schema": 1,
        "tool": product.tool,
        "upstream": {"repo": pin.repo, "tag": pin.tag, "commit": pin.commit, "tree": pin.tree},
        "hub": {"commit": hub_commit, "patch_directory_dirty": hub_dirty},
        "patches": [{"name": p.name, "sha256": p.sha256, "log_markers": list(p.markers)}
                    for p in patches],
        "toolchain": built.get("toolchain"),
        "configuration": built.get("configuration"),
        "warnings": built.get("warnings"),
        "dll": {"name": dll_name, "size": len(data), "sha256": sha256},
        "markers_verified": verified,
        "host_tests": None if tests is None else
        {"ran": tests.get("ran"), "passed": tests.get("passed"), "files": tests.get("files")},
        "source": {"name": archive.name, "id": source_id,
                   "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()},
        # Never set by this tool. A person launches the game and fills the
        # README's verification row; a build cannot know.
        "live_gameplay_verified": False,
    }
    write_json(out / build_info_name, info)
    (out / (dll_name + ".sha256")).write_bytes(f"{sha256}  {dll_name}\n".encode("ascii"))
    ctx.log(f"verify-dll: {path}")
    ctx.log(f"verify-dll: size   {len(data)}")
    ctx.log(f"verify-dll: sha256 {sha256}")
    ctx.log(f"verify-dll: {len(verified)} marker(s) present in the DLL and absent from "
            f"unpatched upstream")
    ctx.log(f"verify-dll: wrote {build_info_name}, {dll_name}.sha256 and {archive.name} "
            f"in {out}")
    ctx.log("verify-dll: live_gameplay_verified is false - this binary has never been "
            "launched against the game")
    return info


# --------------------------------------------------------------------------
# 6. authoring: overlay and make-patch
# --------------------------------------------------------------------------

#: The series' mail shape. Every patch carries the same zero commit id, author
#: and date, so a regenerated patch differs from the old one only where its
#: content does.
MAIL_SEPARATOR = "From " + "0" * 40 + " Mon Sep 17 00:00:00 2001"
MAIL_FROM = "Hero Siege Offline Toolkit <noreply@example.invalid>"
MAIL_DATE = "Sat, 19 Sep 2026 12:00:00 +0000"
#: `git format-patch` folds the Subject header at this width.
SUBJECT_WIDTH = 78
SUBJECT_PREFIX = re.compile(r"^\[PATCH (\d+)/(\d+)\] ")
NUMBERED_NAME = re.compile(r"(\d{4})-[a-z0-9][a-z0-9._-]*\.patch")
MESSAGE_FIELDS = ("Why", "Evidence", "Fails-safe", "Log-markers", "Upstream-status")
MESSAGE_FIELD = re.compile(r"^(Why|Evidence|Fails-safe|Log-markers|Upstream-status):[ \t]*(.*)$")
#: Fixed, so neither this machine's diff settings nor git's defaults moving
#: shape a patch. No --binary: a binary hunk is refused, not written.
DIFF_FLAGS = (
    "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames", "--unified=3",
    "--src-prefix=a/", "--dst-prefix=b/", "--abbrev=7", "--diff-algorithm=myers",
)
#: Work-directory names the authoring path uses; `materialise` resets them.
AUTHOR_TREE, AUTHOR_PATCHES, AUTHOR_CHECK = "a", "ap", "ac"


def overlay_example(product: Product) -> str:
    return f"build/{product.name.lower()}-overlay"


def scope_problem(product: Product, rel: str) -> Optional[str]:
    """Why a patch may not touch `rel` (upstream-relative, `/`-separated), or None."""
    if not rel.startswith(product.source_root):
        return (f"{rel} is outside {product.source_root}; the series changes the DLL's "
                f"project and nothing else in upstream's repository")
    for prefix in product.plugin_facing:
        if rel == prefix or rel.startswith(prefix):
            return (f"{rel} is plugin-facing ({prefix}). Plugins compile against the "
                    f"UNMODIFIED pinned header, so a change here silently breaks the ABI of "
                    f"every plugin already built; keep new declarations in a DLL-private header")
    return None


def _upstream_rel(product: Product, raw: str) -> str:
    rel = str(raw).replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    parts = rel.split("/")
    if not rel or rel.startswith("/") or ":" in parts[0] or any(p in ("", ".", "..") for p in parts):
        raise Refused(f"{raw!r} is not a plain upstream-relative path such as "
                      f"{product.project[0]}/{product.project[1]}")
    problem = scope_problem(product, rel)
    if problem:
        raise Refused(problem)
    return rel


def check_overlay(ctx: Context, overlay: Path) -> Path:
    """An overlay lives outside the checkout, or inside it where git ignores it
    -- never where upstream's files could be committed. It may not share the
    work directory (every step deletes there) or the pin directory (the source
    zip packs that whole)."""
    overlay = Path(os.path.abspath(str(overlay)))
    work = ctx.work_dir
    if is_within(overlay, work) or is_within(work, overlay):
        raise Refused(f"--overlay {overlay} and the work directory {work} must not contain "
                      f"one another; the work directory is deleted step by step")
    if is_within(overlay, ctx.pin_dir) or is_within(ctx.pin_dir, overlay):
        raise Refused(f"--overlay {overlay} and the pin directory {ctx.pin_dir} must not "
                      f"contain one another; the source zip packs the pin directory whole")
    candidates = (overlay, Path(os.path.realpath(str(overlay))))
    for root in dict.fromkeys(ctx.forbidden_roots()):
        outers = (root, Path(os.path.realpath(str(root))))
        if not any(is_within(c, o) for c in candidates for o in outers):
            continue
        result = ctx.git("-C", str(root), "check-ignore", "-q", "--", str(overlay), check=False)
        if result.returncode == 1:
            raise Refused(
                f"--overlay {overlay} is inside the checkout {root} and git does not ignore "
                f"it, so upstream's files could be committed. Use an ignored directory such "
                f"as {overlay_example(ctx.product)}, or one outside the checkout.")
        if result.returncode != 0:
            raise Refused(f"--overlay {overlay} is inside {root}, and git cannot say whether "
                          f"it ignores it (exit {result.returncode}): "
                          f"{(result.stderr or '').strip()}")
    return overlay


def _author_env(ctx: Context) -> Dict[str, str]:
    """git with no user or system configuration, so a diff.noprefix, a rename
    setting or a template hook on this machine cannot shape a patch."""
    config = ctx.path("gitconfig")
    if not config.exists():
        config.write_bytes(b"")
    return {"GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_NOSYSTEM": "1"}


def _stage(ctx: Context, patches: Sequence[Patch]) -> List[Tuple[Patch, Path]]:
    ctx.reset(AUTHOR_PATCHES)
    ctx.path(AUTHOR_PATCHES).mkdir()
    staged = []
    for patch in patches:
        copy = ctx.path(AUTHOR_PATCHES, patch.name)
        copy.write_bytes(patch.data)
        staged.append((patch, copy))
    return staged


def _author_tree(ctx: Context, pin: Pin, patches: Sequence[Patch]) -> Path:
    """Pristine upstream plus `patches`, in its own repository under the work
    directory. The build tree (`src`) is not touched."""
    ctx.prepare()
    record = require_materialised(ctx, pin)
    verify_tree(ctx.path("up"), record["files"],
                "the materialised upstream was modified (run `materialise` again)")
    tree = ctx.path(AUTHOR_TREE)
    ctx.reset(AUTHOR_TREE)
    _patched_copy(ctx, tree, _stage(ctx, patches), check_first=False)
    return tree


def overlay_files(ctx: Context, overlay: Path, files: Sequence[str], *,
                  replace: bool = False) -> List[Path]:
    """Copy upstream files, as pristine upstream plus the whole series leaves
    them, into `overlay` at their upstream-relative paths, to be edited there."""
    pin = load_pin(ctx.pin_dir)
    patches = load_series(ctx.pin_dir, allow_empty=True)
    overlay = check_overlay(ctx, overlay)
    if not files:
        raise Refused("name at least one upstream file to copy into the overlay")
    rels = list(dict.fromkeys(_upstream_rel(ctx.product, f) for f in files))
    tree = _author_tree(ctx, pin, patches)
    for rel in rels:
        if not (tree / rel).is_file():
            raise Refused(f"{rel} is not a file in upstream plus the series. A new file is "
                          f"created in the overlay directly, at its upstream-relative path.")
        if (overlay / rel).exists() and not replace:
            raise Refused(f"{overlay / rel} already exists and may hold edits; delete it or "
                          f"pass --replace")
    written = []
    for rel in rels:
        dest = overlay / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tree / rel, dest)
        written.append(dest)
        ctx.log(f"overlay: {rel} -> {dest}")
    ctx.log(f"overlay: {len(written)} file(s) from upstream plus {len(patches)} patch(es); edit "
            f"them there, then run make-patch")
    return written


def fold_subject(subject: str) -> List[str]:
    """`Subject: <subject>`, folded the way `git format-patch` folds it."""
    lines: List[str] = []
    current = "Subject:"
    for word in subject.split():
        if current not in ("Subject:", "") and len(current) + 1 + len(word) > SUBJECT_WIDTH:
            lines.append(current)
            current = ""
        current += " " + word
    lines.append(current)
    return lines


def renumber_subject(data: bytes, total: int) -> bytes:
    """The patch with its `[PATCH n/m]` total set to `total`; otherwise unchanged."""
    text = data.decode("utf-8")
    head, sep, rest = text.partition("\n\n")
    lines = head.split("\n")
    start = next((i for i, line in enumerate(lines) if line.startswith("Subject: ")), None)
    if start is None:
        return data
    end = start + 1
    while end < len(lines) and lines[end].startswith(" "):
        end += 1
    subject = " ".join(line.strip() for line in lines[start:end])[len("Subject: "):]
    match = SUBJECT_PREFIX.match(subject)
    if not match or int(match.group(2)) == total:
        return data
    subject = f"[PATCH {match.group(1)}/{total}] " + subject[match.end():]
    lines[start:end] = fold_subject(subject)
    return ("\n".join(lines) + sep + rest).encode("utf-8")


def read_message(path: Path, name: str) -> Tuple[str, str]:
    """(subject, body) of a message file: the subject line, a blank line, then a
    body carrying the five fields, each once."""
    try:
        text = Path(path).read_bytes().decode("utf-8")
    except OSError as error:
        raise Refused(f"cannot read --message {path}: {error}") from error
    except UnicodeDecodeError as error:
        raise Refused(f"--message {path} is not UTF-8: {error}") from error
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    subject = lines[0].strip() if lines else ""
    if not subject or MESSAGE_FIELD.match(subject):
        raise Refused(f"--message {path}: the first line is the subject, then a blank line, "
                      f"then the body")
    if subject.startswith("[PATCH"):
        raise Refused(f"--message {path}: leave out the [PATCH n/m] prefix; the tool writes it")
    if len(lines) < 3 or lines[1]:
        raise Refused(f"--message {path}: the subject must be followed by a blank line and a body")
    body_lines = lines[2:]
    for line in body_lines:
        if line.startswith(("diff --git ", "Index: ")) or line == "---":
            raise Refused(f"--message {path}: the line {line!r} would end the message early "
                          f"for `git apply` and every reader of the series")
    # A field runs from its `Key:` line to the next blank line.
    fields: Dict[str, List[List[str]]] = {}
    current: Optional[List[str]] = None
    for line in body_lines:
        match = MESSAGE_FIELD.match(line)
        if match:
            current = [match.group(2)]
            fields.setdefault(match.group(1), []).append(current)
        elif not line.strip():
            current = None
        elif current is not None:
            current.append(line.strip())
    problems = []
    for key in MESSAGE_FIELDS:
        values = fields.get(key, [])
        if not values:
            problems.append(f"no `{key}:` field")
        elif len(values) > 1:
            problems.append(f"`{key}:` appears {len(values)} times")
        elif not " ".join(values[0]).strip():
            problems.append(f"`{key}:` is empty")
    if problems:
        raise Refused(f"--message {path}: {'; '.join(problems)}. Every patch message carries "
                      f"{', '.join(k + ':' for k in MESSAGE_FIELDS)}")
    body = "\n".join(body_lines)
    parse_markers(name, body.encode("utf-8"))       # refuses a grammar it cannot read
    return subject, body


def _diff_sections(diff: bytes) -> List[Tuple[str, bytes]]:
    """(upstream-relative path, bytes) of each file in a `git diff`. The path
    may contain spaces, so `a/X b/X` is split by length, not on " b/"."""
    sections = []
    for chunk in re.split(rb"(?m)^(?=diff --git )", diff):
        if chunk.startswith(b"diff --git "):
            rest = chunk.split(b"\n", 1)[0].decode("utf-8", "replace")[len("diff --git "):]
            size = (len(rest) - len("a/ b/")) // 2
            sections.append((rest[2:2 + size], chunk))
    return sections


def make_patch(ctx: Context, overlay: Path, message: Path, *, name: Optional[str] = None,
               regenerate_last: bool = False) -> Path:
    """Turn the overlay into the next numbered patch, or regenerate the last one.

    New: the overlay is laid over upstream plus the whole series and the
    difference is the next patch. --regenerate-last: the overlay is laid over
    upstream plus the whole series, and the difference from the tree BEFORE
    the last patch replaces it, so the overlay only needs the files that
    change again. Deleting a file is not supported: a file missing from the
    overlay keeps whatever the tree has.
    """
    product = ctx.product
    pin = load_pin(ctx.pin_dir)
    patches = load_series(ctx.pin_dir, allow_empty=True)
    patch_dir = Path(ctx.pin_dir) / "patches"
    overlay = check_overlay(ctx, overlay)

    if regenerate_last:
        if not patches:
            raise Refused("--regenerate-last: patches/series lists nothing to regenerate")
        last = patches[-1]
        number, base = len(patches), list(patches[:-1])
        name = name or last.name
    else:
        if not name:
            raise Refused(f"--name is required for a new patch: "
                          f"{len(patches) + 1:04d}-<slug>.patch")
        last, number, base = None, len(patches) + 1, list(patches)
    match = NUMBERED_NAME.fullmatch(name)
    if not match or int(match.group(1)) != number:
        raise Refused(
            f"--name {name!r} is out of sequence: patches/series lists {len(patches)}, so "
            f"{'the regenerated' if regenerate_last else 'the next'} patch is "
            f"{number:04d}-<slug>.patch (a lower-case slug of letters, digits, '.', '-', '_')")
    taken = {p.name for p in base}
    if name in taken or ((patch_dir / name).exists() and (last is None or name != last.name)):
        raise Refused(f"{patch_dir / name} already exists; a new change is a new number")
    subject, body = read_message(message, name)

    if not overlay.is_dir():
        raise Refused(f"--overlay {overlay} is not a directory; run `overlay` first")
    rels = sorted(p.relative_to(overlay).as_posix() for p in overlay.rglob("*") if p.is_file())
    if not rels:
        raise Refused(f"--overlay {overlay} holds no files; the patch would change nothing")
    problems = [problem for problem in (scope_problem(product, rel) for rel in rels) if problem]
    if problems:
        raise Refused("the overlay holds files no patch may touch:\n  " + "\n  ".join(problems))

    tree = _author_tree(ctx, pin, base)
    env = _author_env(ctx)
    ctx.git("-C", str(tree), "add", "-A", "-f", env_extra=env)
    before = ctx.git("-C", str(tree), "write-tree", env_extra=env).stdout.strip()
    if last is not None:
        copy = ctx.path(AUTHOR_PATCHES, last.name)
        copy.write_bytes(last.data)
        result = ctx.git("-C", str(tree), "apply", "--whitespace=nowarn", str(copy),
                         check=False, env_extra=env)
        if result.returncode != 0:
            raise Failed(f"{last.name} does not apply on top of the {len(base)} before it; "
                         f"run `apply` to see the series' state.\n{_tail(result.stderr)}")
    for rel in rels:
        dest = tree / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(overlay / rel, dest)
    ctx.git("-C", str(tree), "add", "-A", "-f", env_extra=env)
    after = ctx.git("-C", str(tree), "write-tree", env_extra=env).stdout.strip()
    output = ctx.path("author.diff")
    ctx.git("-C", str(tree), "diff", *DIFF_FLAGS, f"--output={output}", before, after,
            env_extra=env)
    diff = output.read_bytes()
    output.unlink()

    if not diff.strip():
        raise Refused(f"the overlay changes nothing against upstream plus "
                      f"{len(base) + (last is not None)} patch(es); there is no patch to write")
    sections = _diff_sections(diff)
    binary = [path for path, chunk in sections
              if b"\nBinary files " in chunk or b"\nGIT binary patch" in chunk]
    if binary:
        raise Refused("binary content: " + ", ".join(binary) + ". The series is reviewable "
                      "text only.")
    with_cr = [path for path, chunk in sections if b"\r" in chunk]
    if with_cr:
        raise Refused("CR bytes in the change to " + ", ".join(with_cr) + ". Patches are LF "
                      "only; save the overlay copy with LF line endings, as upstream has them.")
    deleted = [path for path, chunk in sections if b"\ndeleted file mode " in chunk]
    if deleted:
        raise Refused("a deletion: " + ", ".join(deleted) + ". Deleting a file is not supported.")

    header = [MAIL_SEPARATOR, "From: " + MAIL_FROM, "Date: " + MAIL_DATE]
    header += fold_subject(f"[PATCH {number}/{number}] {subject}")
    data = ("\n".join(header) + "\n\n" + body + "\n\n").encode("utf-8") + diff
    markers = parse_markers(name, data)
    host_tests = "/".join(product.host_tests) + "/"
    added = "\n".join(line for path, chunk in sections if not path.startswith(host_tests)
                      for line in chunk.decode("utf-8", "replace").split("\n")
                      if line.startswith("+") and not line.startswith("+++"))
    for marker in markers:
        if marker not in added:
            ctx.log(f"make-patch: WARNING - Log-markers literal {marker!r} is in no line this "
                    f"patch adds to the DLL's source; verify-dll will not find it")

    # The new series, checked whole on a scratch copy before anything is written.
    final = [Patch(p.name, renumber_subject(p.data, number), "", p.markers) for p in base]
    final.append(Patch(name, data, hashlib.sha256(data).hexdigest(), markers))
    ctx.reset(AUTHOR_CHECK)
    _patched_copy(ctx, ctx.path(AUTHOR_CHECK), _stage(ctx, final), check_first=True)
    ctx.reset(AUTHOR_CHECK)

    patch_dir.mkdir(parents=True, exist_ok=True)
    renumbered = []
    for old, new in zip(base, final):
        if new.data != old.data:
            (patch_dir / old.name).write_bytes(new.data)
            renumbered.append(old.name)
    if last is not None and name != last.name:
        (patch_dir / last.name).unlink()
    path = patch_dir / name
    path.write_bytes(data)
    series = patch_dir / "series"
    entries = series.read_text(encoding="utf-8").split("\n") if series.exists() \
        else ["# application order"]
    while entries and not entries[-1].strip():
        entries.pop()
    if last is not None:
        entries = [name if line.strip() == last.name else line for line in entries]
    else:
        entries.append(name)
    series.write_bytes(("\n".join(entries) + "\n").encode("utf-8"))

    for section_path, chunk in sections:
        lines = chunk.split(b"\n")
        plus = sum(1 for l in lines if l.startswith(b"+") and not l.startswith(b"+++ "))
        minus = sum(1 for l in lines if l.startswith(b"-") and not l.startswith(b"--- "))
        ctx.log(f"make-patch: {section_path}  +{plus} -{minus}")
    if renumbered:
        ctx.log(f"make-patch: [PATCH n/{number}] renumbered in {', '.join(renumbered)}")
    ctx.log(f"make-patch: {'regenerated' if last is not None else 'wrote'} {path}  "
            f"{len(data)} bytes  sha256 {hashlib.sha256(data).hexdigest()}")
    ctx.log(f"make-patch: patches/series lists {number}; the series applies whole. Its README "
            f"row and section, launch-gate row and NOTICE entry are yours to write.")
    return path


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------

def build_parser(product: Product = YYTOOLKIT) -> argparse.ArgumentParser:
    pin_rel = product.zip_prefix.rstrip("/")
    tests_rel = "/".join(product.host_tests)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--work-dir", type=Path, default=None,
                        help=f"short directory OUTSIDE the repository, at most "
                             f"{MAX_WORK_DIR_LEN} characters (default: "
                             f"%%LOCALAPPDATA%%\\hstk\\{product.work_leaf})")
    common.add_argument("--pin-dir", type=Path, default=product.pin_dir,
                        help=f"directory holding upstream.json and patches/ "
                             f"(default: {pin_rel})")
    source = argparse.ArgumentParser(add_help=False)
    source.add_argument("--upstream", type=Path, default=None,
                        help="local clone that contains the pinned commit; only ever read")
    source.add_argument("--allow-network", action="store_true",
                        help="with no --upstream: fetch the pinned commit from upstream.json's repo")
    studio = argparse.ArgumentParser(add_help=False)
    studio.add_argument("--vs-version-range", default=DEFAULT_VS_RANGE,
                        help=f"vswhere -version range (default: {DEFAULT_VS_RANGE}, VS 2022)")
    tests = argparse.ArgumentParser(add_help=False)
    tests.add_argument("--allow-no-hosttests", action="store_true",
                       help=f"do not fail when the patched tree has no {tests_rel}/*.cpp")
    expect = argparse.ArgumentParser(add_help=False)
    expect.add_argument("--expected-sha256", default=None,
                        help="fail unless the DLL hashes to this")
    overlay = argparse.ArgumentParser(add_help=False)
    overlay.add_argument("--overlay", type=Path, required=True,
                         help=f"directory of upstream-relative files to edit: outside the "
                              f"checkout, or ignored by git inside it "
                              f"(e.g. {overlay_example(product)})")

    parser = argparse.ArgumentParser(
        prog=Path(product.tool).name,
        description=f"build the modified {product.dll_name} from the pinned upstream commit "
                    f"and {pin_rel}/patches/series")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    commands.add_parser("materialise", aliases=["materialize"], parents=[common, source],
                        help="export the pinned commit into the work directory and verify it")
    commands.add_parser("apply", parents=[common],
                        help="check the whole series on a scratch copy, then apply it in order")
    commands.add_parser("build", parents=[common, studio],
                        help="MSBuild Release|x64 with /Brepro injected through a props file")
    commands.add_parser("hosttests", parents=[common, studio, tests],
                        help=f"compile and run every {tests_rel}/*.cpp")
    verify = commands.add_parser("verify-dll", parents=[common, expect],
                                 help="size, sha256, log markers; writes BUILD-INFO and the source zip")
    verify.add_argument("--dll", type=Path, default=None,
                        help="check the markers of this file instead, read-only; writes nothing")
    commands.add_parser("all", parents=[common, source, studio, tests, expect],
                        help="materialise, apply, build, hosttests, verify-dll")
    copy = commands.add_parser(
        "overlay", parents=[common, overlay],
        help="copy upstream files, as upstream plus the series leaves them, into --overlay")
    copy.add_argument("--replace", action="store_true",
                      help="overwrite a copy that is already in the overlay")
    copy.add_argument("files", nargs="+", metavar="PATH",
                      help=f"upstream-relative path, e.g. {product.project[0]}/{product.project[1]}")
    make = commands.add_parser(
        "make-patch", parents=[common, overlay],
        help="turn --overlay into the next numbered patch, or regenerate the last one")
    make.add_argument("--message", type=Path, required=True,
                      help="UTF-8 file: the subject line, a blank line, then a body with "
                           "Why:, Evidence:, Fails-safe:, Log-markers: and Upstream-status:")
    make.add_argument("--name", default=None,
                      help="NNNN-<slug>.patch, NNNN the next number (with --regenerate-last "
                           "the last patch's number; default: its current name)")
    make.add_argument("--regenerate-last", action="store_true",
                      help="replace the last patch instead of adding one")
    return parser


def main(argv: Optional[Sequence[str]] = None, *, runner: Runner = run_process,
         environ: Optional[Mapping[str, str]] = None,
         toolchain: Optional[Toolchain] = None, product: Product = YYTOOLKIT) -> int:
    args = build_parser(product).parse_args(argv)
    ctx = Context(pin_dir=args.pin_dir, work_dir=args.work_dir, runner=runner,
                  environ=os.environ if environ is None else environ, product=product)
    command = "materialise" if args.command == "materialize" else args.command
    try:
        if command == "overlay":
            overlay_files(ctx, args.overlay, args.files, replace=args.replace)
            return 0
        if command == "make-patch":
            make_patch(ctx, args.overlay, args.message, name=args.name,
                       regenerate_last=args.regenerate_last)
            return 0
        if command in ("materialise", "all"):
            materialise(ctx, args.upstream, allow_network=args.allow_network)
        if command in ("apply", "all"):
            apply_series(ctx)
        if command in ("build", "all"):
            build(ctx, toolchain=toolchain, vs_version_range=args.vs_version_range)
        if command in ("hosttests", "all"):
            hosttests(ctx, toolchain=toolchain, vs_version_range=args.vs_version_range,
                      allow_none=args.allow_no_hosttests)
        if command in ("verify-dll", "all"):
            verify_dll(ctx, dll=getattr(args, "dll", None),
                       expected_sha256=args.expected_sha256)
    except ToolError as error:
        print(f"{product.error_prefix}: {type(error).__name__.upper()}: {error}", file=sys.stderr)
        return error.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
