#!/usr/bin/env python3
"""crash_dump_stack.py -- which module raised the crash a WER dump recorded.

When `hs_stop_game` closes Hero Siege and the process exits `0xC0000409`, the
exit code says only that something fast-failed. No log names the module: the
game's own logs and ForgePact's stop before process teardown, which is where
the abort happens. Windows Error Reporting keeps a minidump of each crash in
`%LOCALAPPDATA%\\CrashDumps\\Hero_Siege.exe.<pid>.dmp` (the newest ten), and the
dump's stored exception context does name it. This tool reads one dump through
the Windows debugger's console front end, `cdb.exe`, and prints:

    dump: <path> pid=<n|?> code=0x<8 hex> subcode=<n|none> raised-in=<module>

then one line per frame of the faulting thread's stack, as `<module>+0x<offset
in that module>` with cdb's own export-relative name beside it. `raised-in` is
the topmost frame whose module is not one of the runtime's own (ucrtbase,
ntdll, kernel32, kernelbase, vcruntime140*, msvcp140*): for the tracker
producer's exit-time abort that is `HSOfflineTrackerProducer`.

Which dump (exactly one):
    --dump <path>      that file
    --pid <n>          %LOCALAPPDATA%\\CrashDumps\\<exe-name>.<n>.dmp
    --latest           the newest <exe-name>.*.dmp there
`--exe-name` (default Hero_Siege.exe) changes the prefix. `--wait <s>` polls,
with `--pid` (or `--dump`), until the file exists and its size has stopped
changing, since WER writes the dump a moment after the process is gone; a dump
still growing when the wait runs out is refused, never read half-written.

`raised-in` is judged over every frame cdb listed; `--frames` limits only what
is printed. When `.ecxr` fails, or frame 0's module is not the exception
address's module, `kn` walked some other stack than the exception's: the header
then ends `context=unverified`, a `context:` line says why, frame 0 is not
attributed to the exception address, and `--expect-module` never matches.

cdb is found at `--cdb`, then `CDB_PATH`, then
`%ProgramFiles(x86)%\\Windows Kits\\10\\Debuggers\\x64\\cdb.exe`, then `PATH`.
Its symbol path is an empty directory under the system temp directory and the
`_NT_SYMBOL_PATH` variables are dropped, so it never asks a symbol server (and
never touches the network); frames are named from each DLL's exports only.

Exit codes: 0 parsed (and `--expect-module` matched), 1 `--expect-module` did
not match (or the context was unverified), 2 usage error (argparse's own),
3 no dump, 4 cdb ran and no exception record was parsed, 5 no cdb (the message
lists every place looked), 6 the dump was still growing when `--wait` ran out.

It writes only its temp symbol directory. It never moves, deletes or opens a
process, and never edits a dump. The frames it prints name our DLLs, third-party
DLLs and the game's own image with offsets; a game offset (`Hero_Siege+0x...`)
is a research reading for this machine and never goes into a tracked file
(AGENTS.md, "Legal").

Usage:
    py -3 tools/crash_dump_stack.py --latest
    py -3 tools/crash_dump_stack.py --pid 20580 --wait 30 --expect-module HSOfflineTrackerProducer
    py -3 tools/crash_dump_stack.py --dump <path.dmp> --frames 20
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_EXE = "Hero_Siege.exe"
DEFAULT_FRAMES = 12
CDB_TIMEOUT_S = 180
SYMBOL_DIR_NAME = "hs_crash_dump_stack_symbols"

# Modules that only carry a fault raised elsewhere: the C runtime's abort and
# terminate, the loader's teardown, the exit call. The module that raised the
# crash is the first frame outside these.
RUNTIME_MODULES = ("ucrtbase", "ucrtbased", "ntdll", "kernel32", "kernelbase")
RUNTIME_PREFIXES = ("vcruntime140", "msvcp140")

EXIT_OK = 0
EXIT_MODULE_MISMATCH = 1
# 2 is left to argparse, which exits 2 on a usage error (two of --dump/--pid/
# --latest, or none), so a caller can tell a typo from a missing debugger.
EXIT_NO_DUMP = 3
EXIT_NOT_PARSED = 4
EXIT_NO_CDB = 5
EXIT_DUMP_GROWING = 6

# What `_wait_stable` saw when it stopped.
DUMP_STABLE = "stable"
DUMP_MISSING = "missing"
DUMP_GROWING = "growing"

MARK_EXR = "CDS_EXR_BEGIN"
MARK_STACK = "CDS_STACK_BEGIN"
MARK_LM = "CDS_LM_BEGIN"
MARK_END = "CDS_END"

_HEX = r"[0-9a-fA-F`]+"
RE_PROCESS = re.compile(r"^\(([0-9a-fA-F]+)\.[0-9a-fA-F]+\):")
RE_CODE = re.compile(r"^\s*ExceptionCode:\s*([0-9a-fA-F]+)")
RE_ADDRESS = re.compile(r"^\s*ExceptionAddress:\s*(" + _HEX + r")")
RE_SUBCODE = re.compile(r"^\s*Subcode:\s*0x([0-9a-fA-F]+)(?:\s+(\S+))?")
RE_FRAME = re.compile(r"^\s*([0-9a-fA-F]{2,})\s+(" + _HEX + r")\s+(" + _HEX + r")\s+(\S.*?)\s*$")
RE_MODULE = re.compile(r"^\s*(" + _HEX + r")\s+(" + _HEX + r")\s+(\S+)")
# cdb's refusals of `.ecxr` when the dump holds no usable exception context;
# `kn` then walks the current thread instead of the exception's stack.
RE_ECXR_FAILED = re.compile(
    r"unable to get exception context|doesn't have an exception context|no exception context",
    re.IGNORECASE)


class DumpStackError(Exception):
    """A refusal: the message the tool prints and the code it exits with."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Frame:
    index: int
    address: int | None
    call_site: str
    module: str | None
    offset: int | None

    def render(self) -> str:
        if self.module is None:
            where = "<no module>" if self.address is None else f"<no module> 0x{self.address:x}"
        elif self.offset is None:
            where = self.module
        else:
            where = f"{self.module}+0x{self.offset:x}"
        same = self.call_site == where or (self.address is not None and self.call_site == f"0x{self.address:x}")
        site = "" if same else f"  ({self.call_site})"
        return f"  #{self.index:02x} {where}{site}"


@dataclass
class Report:
    pid: int | None = None
    code: int | None = None
    subcode: int | None = None
    subcode_name: str | None = None
    exception_address: int | None = None
    frames: list[Frame] = field(default_factory=list)
    # Why the stack cannot be trusted to be the exception's, or None when it
    # can: `.ecxr` failed, or frame 0 sits in another module than the
    # exception address.
    context_problem: str | None = None

    @property
    def raised_in(self) -> str | None:
        """Over every parsed frame, not only the ones printed."""
        for frame in self.frames:
            if frame.module and not is_runtime_module(frame.module):
                return frame.module
        return None


def is_runtime_module(name: str) -> bool:
    low = normalize_module(name)
    return low in RUNTIME_MODULES or low.startswith(RUNTIME_PREFIXES)


def normalize_module(name: str) -> str:
    low = name.strip().lower()
    for suffix in (".dll", ".exe"):
        if low.endswith(suffix):
            return low[: -len(suffix)]
    return low


def _int(text: str) -> int:
    return int(text.replace("`", ""), 16)


def _section(transcript: str, begin: str, end: str) -> list[str]:
    lines = transcript.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped == begin:
            inside = True
            continue
        if inside and stripped in (MARK_EXR, MARK_STACK, MARK_LM, MARK_END):
            break
        if inside:
            out.append(line)
    return out


def parse_modules(lines: list[str]) -> list[tuple[int, int, str]]:
    modules = []
    for line in lines:
        if line.strip().lower().startswith("unloaded modules"):
            break
        m = RE_MODULE.match(line)
        if not m:
            continue
        try:
            modules.append((_int(m.group(1)), _int(m.group(2)), m.group(3)))
        except ValueError:
            continue
    return modules


def _module_of(address: int | None, call_site: str, modules: list[tuple[int, int, str]]):
    if address is not None:
        for start, end, name in modules:
            if start <= address < end:
                return name, address - start
    # cdb names the module itself (`mod!sym+0x..`, `mod+0x..`) even where the
    # module list has no entry for it; a bare `0x..` is a frame with no module.
    m = re.match(r"^([A-Za-z_][\w.\-]*?)(?:!|\+0x|$)", call_site)
    if m and not call_site.startswith("0x"):
        return m.group(1), None
    return None, None


def _context_problem(stack_lines: list[str], rows: list[tuple[int, int, str]],
                     exception_address: int | None,
                     modules: list[tuple[int, int, str]]) -> str | None:
    for line in stack_lines:
        if RE_FRAME.match(line):
            break
        if RE_ECXR_FAILED.search(line):
            return f".ecxr failed ({line.strip()})"
    if not rows or exception_address is None:
        return None
    named, _ = _module_of(None, rows[0][2], [])
    at, _ = _module_of(exception_address, "", modules)
    if named and at and normalize_module(named) != normalize_module(at):
        return (f"frame 0 is in {named} ({rows[0][2]}) but the exception address "
                f"0x{exception_address:x} is in {at}")
    return None


def parse_transcript(transcript: str) -> Report:
    """Every frame cdb listed; callers cut what they print, never what
    `raised_in` is judged over."""
    report = Report()
    for line in transcript.splitlines():
        m = RE_PROCESS.match(line.strip())
        if m:
            report.pid = int(m.group(1), 16)
            break

    for line in _section(transcript, MARK_EXR, MARK_STACK):
        if (m := RE_CODE.match(line)) and report.code is None:
            report.code = int(m.group(1), 16)
        elif (m := RE_ADDRESS.match(line)) and report.exception_address is None:
            report.exception_address = _int(m.group(1))
        elif (m := RE_SUBCODE.match(line)) and report.subcode is None:
            report.subcode = int(m.group(1), 16)
            report.subcode_name = m.group(2)

    modules = parse_modules(_section(transcript, MARK_LM, MARK_END))

    stack_lines = _section(transcript, MARK_STACK, MARK_LM)
    rows = []
    for line in stack_lines:
        m = RE_FRAME.match(line)
        if m:
            rows.append((int(m.group(1), 16), _int(m.group(3)), m.group(4)))

    report.context_problem = _context_problem(stack_lines, rows, report.exception_address, modules)

    # A row's RetAddr is where the frame below it returns to, so it is the
    # address the next row's frame is executing at; frame 0 is at the
    # exception address -- unless the stack is not the exception's, when
    # frame 0 is named from its call site alone.
    previous_return = None if report.context_problem else report.exception_address
    for index, return_address, call_site in rows:
        module, offset = _module_of(previous_return, call_site, modules)
        report.frames.append(Frame(index, previous_return, call_site, module, offset))
        previous_return = return_address
    return report


def find_cdb(explicit: str | None) -> tuple[Path | None, list[str]]:
    """The cdb to run, and every place looked, in order."""
    looked: list[str] = []
    candidates: list[tuple[str, str]] = []
    if explicit:
        candidates.append(("--cdb", explicit))
    env_path = os.environ.get("CDB_PATH")
    if env_path:
        candidates.append(("CDB_PATH", env_path))
    else:
        looked.append("CDB_PATH (not set)")
    program_files = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    candidates.append(("Windows Kits", str(Path(program_files) / "Windows Kits" / "10" / "Debuggers" / "x64" / "cdb.exe")))
    for label, candidate in candidates:
        looked.append(f"{label}: {candidate}")
        if Path(candidate).is_file():
            return Path(candidate), looked
    on_path = shutil.which("cdb") or shutil.which("cdb.exe")
    looked.append(f"PATH: {on_path or 'cdb not found'}")
    if on_path:
        return Path(on_path), looked
    return None, looked


def crash_dumps_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "CrashDumps"


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size if path.is_file() else None
    except FileNotFoundError:
        return None


def _wait_stable(path: Path, wait_s: float, poll_s: float = 0.5) -> tuple[str, int | None]:
    """Until the file exists and its size has held still for one poll.

    Returns `(DUMP_STABLE, size)`, `(DUMP_MISSING, None)` when it never
    appeared within `wait_s`, or `(DUMP_GROWING, size)` when it exists but its
    size had not held still by then (WER still writing it). A file first seen
    at the deadline gets one more poll, so it is compared at least once."""
    deadline = time.monotonic() + max(0.0, wait_s)
    last_size: int | None = None
    while True:
        size = _size(path)
        first_sighting = size is not None and last_size is None
        if size is not None:
            if size == last_size and size > 0:
                return DUMP_STABLE, size
            last_size = size
        elif wait_s <= 0:
            return DUMP_MISSING, None
        if time.monotonic() >= deadline and not first_sighting:
            return (DUMP_MISSING, None) if size is None else (DUMP_GROWING, size)
        time.sleep(poll_s)


def _newest(paths) -> Path | None:
    """The newest of `paths` by mtime, skipping any that vanished between the
    glob and the stat (WER rotates the oldest dump out as it writes a new one)."""
    dated = []
    for p in paths:
        try:
            dated.append((p.stat().st_mtime, p))
        except FileNotFoundError:
            continue
    return max(dated, key=lambda pair: pair[0])[1] if dated else None


def resolve_dump(args: argparse.Namespace) -> Path:
    folder = crash_dumps_dir()
    if args.dump:
        path = Path(args.dump)
        where = str(path)
    elif args.pid is not None:
        path = folder / f"{args.exe_name}.{args.pid}.dmp"
        where = str(path)
    else:
        newest = _newest(folder.glob(f"{args.exe_name}.*.dmp")) if folder.is_dir() else None
        if newest is None:
            raise DumpStackError(EXIT_NO_DUMP, f"no {args.exe_name}.*.dmp in {folder}")
        return newest
    if args.wait > 0:
        state, size = _wait_stable(path, args.wait)
        if state == DUMP_MISSING:
            raise DumpStackError(EXIT_NO_DUMP, f"no dump at {where} after waiting {args.wait:g}s")
        if state == DUMP_GROWING:
            raise DumpStackError(EXIT_DUMP_GROWING,
                                 f"dump at {where} still growing after {args.wait:g}s ({size} bytes at the last poll); "
                                 "not read half-written, run again with a longer --wait")
    if not path.is_file():
        raise DumpStackError(EXIT_NO_DUMP, f"no dump at {where}")
    return path


def symbol_dir() -> Path:
    """An empty local directory: no symbol server, so no network."""
    path = Path(tempfile.gettempdir()) / SYMBOL_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def cdb_command(cdb: Path, dump: Path, symbols: Path, frames: int) -> list[str]:
    script = "; ".join((
        f".echo {MARK_EXR}", ".exr -1",
        f".echo {MARK_STACK}", ".ecxr", f"kn {max(frames + 4, 16)}",
        f".echo {MARK_LM}", "lm",
        f".echo {MARK_END}", "q",
    ))
    # -sins: ignore _NT_SYMBOL_PATH and friends; -y: only the empty local dir.
    return [str(cdb), "-z", str(dump), "-y", str(symbols), "-sins", "-c", script]


def cdb_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        if key.upper() in ("_NT_SYMBOL_PATH", "_NT_ALT_SYMBOL_PATH", "_NT_SOURCE_PATH", "_NT_EXECUTABLE_IMAGE_PATH"):
            del env[key]
    return env


def run_cdb(command: list[str], env: dict[str, str], timeout: float) -> str:
    """Run cdb and return its transcript (tests replace this)."""
    proc = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=timeout, stdin=subprocess.DEVNULL,
    )
    return (proc.stdout or "") + (proc.stderr or "")


def _pid_from_name(path: Path) -> int | None:
    m = re.search(r"\.(\d+)\.dmp$", path.name, re.IGNORECASE)
    return int(m.group(1)) if m else None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Name the module that raised the crash a WER minidump recorded (reads it through cdb.exe).")
    which = p.add_mutually_exclusive_group(required=True)
    which.add_argument("--dump", help="the .dmp file to read")
    which.add_argument("--pid", type=int, help=r"read %%LOCALAPPDATA%%\CrashDumps\<exe-name>.<pid>.dmp")
    which.add_argument("--latest", action="store_true", help="read the newest <exe-name>.*.dmp")
    p.add_argument("--exe-name", default=DEFAULT_EXE, help=f"dump file prefix (default {DEFAULT_EXE})")
    p.add_argument("--wait", type=float, default=0.0,
                   help="seconds to poll, with --pid or --dump, until the file exists and stops growing "
                        "(default 0); still growing at the end exits 6")
    p.add_argument("--frames", type=int, default=DEFAULT_FRAMES, help=f"frames to print (default {DEFAULT_FRAMES}); raised-in is judged over every frame cdb lists")
    p.add_argument("--expect-module", help="exit 1 unless raised-in is this module (case-insensitive, .dll optional)")
    p.add_argument("--cdb", help="path to cdb.exe")
    p.add_argument("--timeout", type=float, default=CDB_TIMEOUT_S, help=f"cdb timeout in seconds (default {CDB_TIMEOUT_S})")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _main(args)
    except DumpStackError as exc:
        print(f"crash_dump_stack: {exc}", file=sys.stderr)
        return exc.code


def _main(args: argparse.Namespace) -> int:
    cdb, looked = find_cdb(args.cdb)
    if cdb is None:
        raise DumpStackError(EXIT_NO_CDB, "cdb.exe not found (install the Windows SDK's Debugging Tools); looked at:\n  "
                             + "\n  ".join(looked))
    dump = resolve_dump(args)
    frames = max(1, args.frames)
    command = cdb_command(cdb, dump, symbol_dir(), frames)
    try:
        transcript = run_cdb(command, cdb_env(), args.timeout)
    except subprocess.TimeoutExpired:
        raise DumpStackError(EXIT_NOT_PARSED, f"cdb did not finish within {args.timeout:g}s on {dump}")
    except OSError as exc:
        raise DumpStackError(EXIT_NO_CDB, f"cdb at {cdb} could not be started: {exc}")

    report = parse_transcript(transcript)
    if report.code is None:
        tail = "\n".join(transcript.strip().splitlines()[-15:])
        raise DumpStackError(EXIT_NOT_PARSED, f"cdb ran on {dump} and printed no exception record; its last lines:\n{tail}")

    pid = report.pid if report.pid is not None else _pid_from_name(dump)
    subcode = "none" if report.subcode is None else str(report.subcode)
    raised = report.raised_in or "none"
    unverified = " context=unverified" if report.context_problem else ""
    print(f"dump: {dump} pid={pid if pid is not None else '?'} code=0x{report.code:08x} "
          f"subcode={subcode} raised-in={raised}{unverified}")
    if report.context_problem:
        print(f"  context: {report.context_problem}; the frames below are the stack cdb walked, "
              "which may not be the exception's")
    for frame in report.frames[:frames]:
        print(frame.render())

    if args.expect_module:
        if report.context_problem:
            print(f"crash_dump_stack: expected raised-in={args.expect_module}, but the stack is not verified "
                  f"to be the exception's ({report.context_problem})", file=sys.stderr)
            return EXIT_MODULE_MISMATCH
        if report.raised_in is None or normalize_module(report.raised_in) != normalize_module(args.expect_module):
            print(f"crash_dump_stack: expected raised-in={args.expect_module}, got {raised}", file=sys.stderr)
            return EXIT_MODULE_MISMATCH
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
