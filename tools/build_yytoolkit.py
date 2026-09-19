"""Build the hub's modified YYToolkit.dll: one pinned upstream commit plus the
patch series in `third_party/yytoolkit/`, and nothing else.

Run it:

    py -3 tools/build_yytoolkit.py all --upstream C:\\src\\YYToolkit
    py -3 tools/build_yytoolkit.py materialise --upstream C:\\src\\YYToolkit
    py -3 tools/build_yytoolkit.py apply
    py -3 tools/build_yytoolkit.py build
    py -3 tools/build_yytoolkit.py hosttests
    py -3 tools/build_yytoolkit.py verify-dll
    py -3 tools/build_yytoolkit.py verify-dll --dll some\\other\\YYToolkit.dll

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

`build` runs upstream's own `YYToolkit.vcxproj`, Release|x64, unedited. `/Brepro`
and `/PDBALTPATH` arrive through a props file this tool writes into the work
directory and hands to MSBuild as `ForceImportAfterCppTargets`, which makes two
builds on one toolchain byte-identical. `CL`, `_CL_`, `LINK` and `_LINK_` are
removed from the environment first: they add compiler and linker flags that no
project file and no log shows.

`hosttests` compiles and runs every `YYToolkit/hs-tests/*.cpp` in the patched
tree with `cl`. A tree with no host tests fails unless `--allow-no-hosttests`
says that is expected -- zero tests passing is not a result.

`verify-dll` is the check that would have caught the original failure. Every
literal a patch declares on a `Log-markers:` header line has to occur in the DLL
as ASCII, and must NOT occur in unpatched upstream, where it would prove
nothing. Only then does it write `YYToolkit-BUILD-INFO.json`, the `.sha256` and
`yytoolkit-source-<id>.zip` beside the DLL. `live_gameplay_verified` is always
written as false: this tool cannot know, and launching the game is a person's
row in the README table. With `--dll` it checks the markers of any file,
read-only, and writes nothing -- point it at a binary of unknown origin to see
which documented changes it lacks.

    Log-markers: none
    Log-markers: "first literal", "second, with a comma"

The work directory has to be short and outside the repository. Upstream's
longest path is 92 characters below it and this worktree's own prefix is 97, so
MAX_PATH is a real limit here, and an over-long `--work-dir` is refused rather
than warned about. A directory that is not empty and was not created by this
tool is refused as well, because every step deletes what it is about to rebuild.

What it never does: launch the game, read or write the game directory, copy the
DLL out of the work directory, or use the network -- unless `--upstream` is
omitted AND `--allow-network` is passed, which fetches the one pinned commit.

Exit codes: 0 done; 1 a step ran and failed (patch does not apply, MSBuild or a
host test failed, a marker is missing); 2 refused before doing anything (work
directory, pin, series, missing `--upstream`); 3 the toolchain is not there.
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
DEFAULT_PIN_DIR = ROOT / "third_party" / "yytoolkit"

#: Longest `--work-dir` accepted, as an absolute path. 40 + the 92 characters
#: upstream needs below it leaves MSBuild's tlog names and cl/link temp files
#: well inside MAX_PATH (260).
MAX_WORK_DIR_LEN = 40

#: Dropped into the work directory when this tool creates it. Every step deletes
#: directories called `src`, `o`, `i`... inside it, so it will only do that in a
#: directory it made (or an empty one).
WORK_MARKER = ".hstk-yytoolkit-work"

#: These silently add flags to every cl.exe / link.exe invocation.
STRIPPED_ENV = ("CL", "_CL_", "LINK", "_LINK_")

#: autocrlf off: upstream blobs are LF and the patches are LF, while this
#: machine's default would export CRLF. longpaths on: git resolves a junction to
#: its real, possibly long, path.
GIT_FLAGS = ("-c", "core.autocrlf=false", "-c", "core.longpaths=true")

DLL_NAME = "YYToolkit.dll"
BUILD_INFO_NAME = "YYToolkit-BUILD-INFO.json"
PROJECT = ("YYToolkit", "YYToolkit.vcxproj")
HOST_TESTS = ("YYToolkit", "hs-tests")
ZIP_PREFIX = "third_party/yytoolkit/"

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
  Written by tools/build_yytoolkit.py; passed as
  /p:ForceImportAfterCppTargets=<this file>. Upstream's YYToolkit.vcxproj is
  not edited.

  /Brepro              : cl + link stop stamping wall-clock time; the PE
                         TimeDateStamp and the PDB GUID become content hashes.
  /PDBALTPATH:%_PDB%   : the DLL records "YYToolkit.pdb", not the absolute
                         build directory.
-->
<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalOptions>%(AdditionalOptions) /Brepro</AdditionalOptions>
    </ClCompile>
    <Link>
      <AdditionalOptions>%(AdditionalOptions) /Brepro /PDBALTPATH:%25_PDB%25</AdditionalOptions>
    </Link>
  </ItemDefinitionGroup>
</Project>
"""
CONFIGURATION = "Release|x64 + repro.props (/Brepro, /PDBALTPATH:%_PDB%)"

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


def load_series(pin_dir: Path) -> List[Patch]:
    """The patches, in the order `patches/series` lists them."""
    patch_dir = Path(pin_dir) / "patches"
    series = patch_dir / "series"
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
    if not patches:
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


def default_work_dir(environ: Mapping[str, str]) -> Path:
    if os.name == "nt":
        local = env_get(environ, "LOCALAPPDATA")
        if local:
            candidate = Path(local) / "hstk" / "yk"
            if len(str(candidate)) <= MAX_WORK_DIR_LEN:
                return candidate
        # A long profile name makes even %LOCALAPPDATA% too long.
        drive = env_get(environ, "SystemDrive") or "C:"
        return Path(drive + "\\") / "hstk" / "yk"
    cache = env_get(environ, "XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "hstk" / "yk"


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
    pin_dir: Path = DEFAULT_PIN_DIR
    work_dir: Optional[Path] = None
    runner: Runner = run_process
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    #: The CLI never changes this. It exists because the system temp directory
    #: the unit tests must use is itself longer than the limit on Windows.
    max_work_dir_len: int = MAX_WORK_DIR_LEN
    log: Callable[[str], None] = say
    _prepared: bool = False

    def __post_init__(self) -> None:
        self.pin_dir = Path(os.path.abspath(str(self.pin_dir)))
        chosen = self.work_dir if self.work_dir is not None else default_work_dir(self.environ)
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
                f"{self.max_work_dir_len}. Upstream needs 92 more below it and MAX_PATH "
                f"is 260 - use a short path such as C:\\hstk\\yk."
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
            if entries and WORK_MARKER not in entries:
                raise Refused(
                    f"--work-dir {work} is not empty and was not created by this tool. "
                    f"Every step deletes what it rebuilds, so it only works in its own directory."
                )
        work.mkdir(parents=True, exist_ok=True)
        marker = work / WORK_MARKER
        if not marker.exists():
            marker.write_text("created by tools/build_yytoolkit.py; safe to delete whole\n",
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
            timeout: Optional[int] = None, capture: bool = True):
        try:
            return self.runner(list(argv), cwd=str(cwd) if cwd else None, env=self.env(),
                               timeout=timeout, capture=capture)
        except FileNotFoundError as error:
            raise ToolchainMissing(f"cannot start {argv[0]}: {error}") from error
        except subprocess.TimeoutExpired as error:
            raise Failed(f"{argv[0]} did not finish within {timeout} s") from error

    def git(self, *args: str, check: bool = True, timeout: int = GIT_TIMEOUT):
        result = self.run(["git", *GIT_FLAGS, *args], timeout=timeout)
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
    ctx.reset("up", "src", "chk", "p", "o", "i", "t", "log",
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
    project_dir = ctx.path("src", PROJECT[0])
    return [
        toolchain.msbuild, str(project_dir / PROJECT[1]),
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
    project = ctx.path("src", *PROJECT)
    if not project.is_file():
        raise Refused(f"{project} is missing from the patched tree")
    toolchain = toolchain or locate_toolchain(ctx, vs_version_range)

    # Fresh every time: with /LTCG:incremental a stale .iobj is a correctness
    # hazard, not a speed-up.
    ctx.reset("o", "i", "log", BUILT)
    for name in ("o", "i", "log"):
        ctx.path(name).mkdir()
    ctx.path("repro.props").write_bytes(REPRO_PROPS.encode("utf-8"))

    argv = msbuild_command(ctx, toolchain)
    ctx.log("build: " + " ".join(argv))
    started = time.monotonic()
    result = ctx.run(argv, cwd=project.parent, timeout=BUILD_TIMEOUT, capture=False)
    seconds = round(time.monotonic() - started, 1)
    if result.returncode != 0:
        raise Failed(f"MSBuild exited {result.returncode}; see {ctx.path('log', 'msbuild.log')}")
    dll = ctx.path("o", DLL_NAME)
    if not dll.is_file():
        raise Failed(f"MSBuild succeeded but {dll} is missing")

    data = dll.read_bytes()
    version = ctx.run([toolchain.msbuild, "-nologo", "-version"], timeout=GIT_TIMEOUT)
    version_lines = [l.strip() for l in (version.stdout or "").splitlines() if l.strip()]
    state_file = ctx.path("i", "YYToolkit.tlog", "YYToolkit.lastbuildstate")
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
        "configuration": CONFIGURATION,
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
    test_dir = ctx.path("src", *HOST_TESTS)
    sources = sorted(test_dir.glob("*.cpp")) if test_dir.is_dir() else []
    ctx.reset("t", HOSTTESTS)
    record = {"series": series_record(pin, patches), "ran": 0, "passed": 0, "files": []}
    if not sources:
        if not allow_none:
            raise Failed(
                f"no host tests: {'/'.join(HOST_TESTS)}/*.cpp matches nothing in the patched "
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
    project_dir = ctx.path("src", PROJECT[0])
    includes = [d for d in (project_dir / "include", project_dir / "source", test_dir)
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


def build_source_zip(pin_dir: Path, dest_dir: Path) -> Tuple[Path, str]:
    """A deterministic zip of `third_party/yytoolkit`, named by its content."""
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
    dest = Path(dest_dir) / f"yytoolkit-source-{source_id[:12]}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as bundle:
        for rel, data in contents:
            entry = zipfile.ZipInfo(ZIP_PREFIX + rel, date_time=(1980, 1, 1, 0, 0, 0))
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
    out = ctx.path("o")
    # A failed verification must not leave an older success lying beside the DLL.
    if out.is_dir():
        for stale in list(out.glob("yytoolkit-source-*.zip")) + [out / BUILD_INFO_NAME,
                                                                  out / (DLL_NAME + ".sha256")]:
            if stale.is_file():
                stale.unlink()
    require_applied(ctx, pin, patches)
    built = read_json(ctx.path(BUILT))
    if not isinstance(built, dict):
        raise Refused(f"{ctx.work_dir} holds no build; run `build` first")
    if built.get("series") != series_record(pin, patches):
        raise Refused("the DLL in the work directory was built from a different series; "
                      "run `build` again")
    path = out / DLL_NAME
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
    archive, source_id = build_source_zip(ctx.pin_dir, out)
    info = {
        "schema": 1,
        "tool": "tools/build_yytoolkit.py",
        "upstream": {"repo": pin.repo, "tag": pin.tag, "commit": pin.commit, "tree": pin.tree},
        "hub": {"commit": hub_commit, "patch_directory_dirty": hub_dirty},
        "patches": [{"name": p.name, "sha256": p.sha256, "log_markers": list(p.markers)}
                    for p in patches],
        "toolchain": built.get("toolchain"),
        "configuration": built.get("configuration"),
        "warnings": built.get("warnings"),
        "dll": {"name": DLL_NAME, "size": len(data), "sha256": sha256},
        "markers_verified": verified,
        "host_tests": None if tests is None else
        {"ran": tests.get("ran"), "passed": tests.get("passed"), "files": tests.get("files")},
        "source": {"name": archive.name, "id": source_id,
                   "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()},
        # Never set by this tool. A person launches the game and fills the
        # README's verification row; a build cannot know.
        "live_gameplay_verified": False,
    }
    write_json(out / BUILD_INFO_NAME, info)
    (out / (DLL_NAME + ".sha256")).write_bytes(f"{sha256}  {DLL_NAME}\n".encode("ascii"))
    ctx.log(f"verify-dll: {path}")
    ctx.log(f"verify-dll: size   {len(data)}")
    ctx.log(f"verify-dll: sha256 {sha256}")
    ctx.log(f"verify-dll: {len(verified)} marker(s) present in the DLL and absent from "
            f"unpatched upstream")
    ctx.log(f"verify-dll: wrote {BUILD_INFO_NAME}, {DLL_NAME}.sha256 and {archive.name} "
            f"in {out}")
    ctx.log("verify-dll: live_gameplay_verified is false - this binary has never been "
            "launched against the game")
    return info


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--work-dir", type=Path, default=None,
                        help=f"short directory OUTSIDE the repository, at most "
                             f"{MAX_WORK_DIR_LEN} characters (default: %%LOCALAPPDATA%%\\hstk\\yk)")
    common.add_argument("--pin-dir", type=Path, default=DEFAULT_PIN_DIR,
                        help="directory holding upstream.json and patches/ "
                             "(default: third_party/yytoolkit)")
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
                       help="do not fail when the patched tree has no YYToolkit/hs-tests/*.cpp")
    expect = argparse.ArgumentParser(add_help=False)
    expect.add_argument("--expected-sha256", default=None,
                        help="fail unless the DLL hashes to this")

    parser = argparse.ArgumentParser(
        description="build the modified YYToolkit.dll from the pinned upstream commit "
                    "and third_party/yytoolkit/patches/series")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    commands.add_parser("materialise", aliases=["materialize"], parents=[common, source],
                        help="export the pinned commit into the work directory and verify it")
    commands.add_parser("apply", parents=[common],
                        help="check the whole series on a scratch copy, then apply it in order")
    commands.add_parser("build", parents=[common, studio],
                        help="MSBuild Release|x64 with /Brepro injected through a props file")
    commands.add_parser("hosttests", parents=[common, studio, tests],
                        help="compile and run every YYToolkit/hs-tests/*.cpp")
    verify = commands.add_parser("verify-dll", parents=[common, expect],
                                 help="size, sha256, log markers; writes BUILD-INFO and the source zip")
    verify.add_argument("--dll", type=Path, default=None,
                        help="check the markers of this file instead, read-only; writes nothing")
    commands.add_parser("all", parents=[common, source, studio, tests, expect],
                        help="materialise, apply, build, hosttests, verify-dll")
    return parser


def main(argv: Optional[Sequence[str]] = None, *, runner: Runner = run_process,
         environ: Optional[Mapping[str, str]] = None,
         toolchain: Optional[Toolchain] = None) -> int:
    args = build_parser().parse_args(argv)
    ctx = Context(pin_dir=args.pin_dir, work_dir=args.work_dir, runner=runner,
                  environ=os.environ if environ is None else environ)
    command = "materialise" if args.command == "materialize" else args.command
    try:
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
        print(f"build_yytoolkit: {type(error).__name__.upper()}: {error}", file=sys.stderr)
        return error.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
