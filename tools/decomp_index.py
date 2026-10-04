#!/usr/bin/env python3
"""decomp_index.py -- which game scripts are already decompiled, and slot names.

Before opening Ghidra, ask whether a script has already been decompiled for the
game build in hand, and where the file is:

    py -3 tools/decomp_index.py has LoadProjectileSettings
    py -3 tools/decomp_index.py has --contains WhiteMage
    py -3 tools/decomp_index.py has 0x<address>

and after a headless run, record what it wrote:

    py -3 tools/decomp_index.py scan <outdir> [--note "..."]

The index and every decompile stay on the researcher's machine, outside any
repository: see AGENTS.md § "Legal: Decompiled Output Never Reaches Any Origin".
The index records only where a file is and what our own header line says about
it (name, variant, address, size, dates, the build), never a line of a
decompile's body, and the tool refuses (exit 2) to write the index, or an
annotated copy, anywhere that has a `.git` entry in itself or a parent.

The index is JSON Lines, one record per (file path, build), at
`%USERPROFILE%\\tools\\hs-decomp\\decomp-index.jsonl`, or `--index` / env
`HS_DECOMP_INDEX`. The build is the sha256 of the executable Ghidra imported:
`--build <sha|text>`, else the hash of `--exe`, env `HS_DECOMP_EXE`, or
`%USERPROFILE%\\tools\\hs-bin\\Hero_Siege.exe`.

`has` exits 0 when a record for the current build matches, 1 when none does
(matches for another build are still printed, labelled as such, so a stale
decompile reads as stale rather than missing), and 2 for a usage error or a
refusal.

The same tool names variable-slot globals that a decompiler leaves unnamed. The
runtime keeps each such global in a 16-byte table entry: 8 bytes pointing at the
variable's NUL-terminated name inside the executable, then the slot itself. So
the little-endian pointer 8 bytes before a slot names it (ForgePact #160):

    py -3 tools/decomp_index.py slot-name 0x<slot> ...   # slot -> name, or ?
    py -3 tools/decomp_index.py find-name projEffect ... # name -> slot(s), or ?
    py -3 tools/decomp_index.py annotate IN.c OUT.c      # rename resolvable globals

These read a PE32+ file only (the executable from `--exe`, `HS_DECOMP_EXE` or
the default above), never guess a name, and exit 1 when any address or name did
not resolve. No address of any build is written in this file.

Guide: docs/tools/decomp-index.md
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import struct
import sys
from pathlib import Path

ENV_INDEX = "HS_DECOMP_INDEX"
ENV_EXE = "HS_DECOMP_EXE"
LEGAL = 'AGENTS.md § "Legal: Decompiled Output Never Reaches Any Origin"'

# Our own header line, written by the local DecompileTo*.java scripts:
#   // <label> @ <hex address> size=<n>
HEADER = re.compile(r"^//\s+(.+?)\s+@\s+(?:0x)?([0-9A-Fa-f]+)\s+size=(\d+)")
LABEL = re.compile(r"^[A-Za-z0-9_.-]+$")
NOT_LABEL_CHAR = re.compile(r"[^A-Za-z0-9_.-]")
VARIANT_SUFFIX = re.compile(r"\.[A-Za-z]$")
SCRIPT_PREFIX = "gml_Script_"

IDENTIFIER = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{0,62}\x00")
# A decompiler's global data token: the data-symbol prefix (optionally with a
# leading underscore for a dereference) or the `uRam` form, then 8-16 hex digits.
_DATA_PREFIX = "D" + "AT_"
GLOBAL_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(?:_?" + _DATA_PREFIX + r"|uRam)([0-9A-Fa-f]{8,16})(?![0-9A-Za-z_])")


class Refusal(Exception):
    """A usage error or a refusal: exit 2 with the message."""


# -- paths, builds ----------------------------------------------------------

def default_index() -> Path:
    return Path.home() / "tools" / "hs-decomp" / "decomp-index.jsonl"


def default_exe() -> Path:
    return Path.home() / "tools" / "hs-bin" / "Hero_Siege.exe"


def index_path(args) -> Path:
    if getattr(args, "index", None):
        return Path(args.index)
    if os.environ.get(ENV_INDEX):
        return Path(os.environ[ENV_INDEX])
    return default_index()


def git_tree_of(path: Path) -> Path | None:
    """The nearest directory at or above `path` holding a `.git` entry, if any.

    A worktree's `.git` is a file, so any entry counts. No git process is run,
    which also catches a checkout other than this one.
    """
    p = Path(path).resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists():
            return d
    return None


def refuse_inside_git(path: Path, what: str) -> None:
    tree = git_tree_of(path)
    if tree is not None:
        raise Refusal(
            "refusing to write the %s at %s: %s is a git tree. Decompiled output and "
            "its index stay outside every repository, per %s." % (what, path, tree, LEGAL))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def exe_path(args) -> Path:
    """The executable: --exe, else HS_DECOMP_EXE, else the default; it must exist."""
    if getattr(args, "exe", None):
        p, src = Path(args.exe), "--exe"
    elif os.environ.get(ENV_EXE):
        p, src = Path(os.environ[ENV_EXE]), ENV_EXE
    else:
        p, src = default_exe(), "the default"
    if not p.is_file():
        raise Refusal("no executable at %s (%s). Pass --build <sha|text> or --exe <path>, "
                      "or set %s." % (p, src, ENV_EXE))
    return p


def current_build(args) -> str:
    if getattr(args, "build", None):
        return args.build
    return sha256_of(exe_path(args))


def short_build(build: str) -> str:
    return build[:12] if re.fullmatch(r"[0-9a-f]{64}", build) else build


# -- naming a decompile ------------------------------------------------------

def normalise(query: str) -> str:
    if query.startswith(SCRIPT_PREFIX):
        query = query[len(SCRIPT_PREFIX):]
    return NOT_LABEL_CHAR.sub("_", query)


def split_variant(stem: str) -> tuple[str, str]:
    """`Name.s.n` -> (`Name`, `s.n`): single-letter dotted suffixes are the variant."""
    parts = []
    while VARIANT_SUFFIX.search(stem) and len(stem) > 2:
        parts.insert(0, stem[-1])
        stem = stem[:-2]
    return stem, ".".join(parts)


def read_header(path: Path) -> tuple[str | None, str | None]:
    """(label, address) from the first line; only that line is ever read."""
    with open(path, "r", encoding="latin-1", newline="") as f:
        first = f.readline(4096)
    m = HEADER.match(first.strip())
    if not m:
        return None, None
    label = m.group(1)
    address = "0x%x" % int(m.group(2), 16)
    return (label if LABEL.match(label) else None), address


def describe(path: Path) -> dict | None:
    """A record's name fields for one `.c` file, or None when it cannot be named."""
    stem, variant = split_variant(path.name[:-2])
    label, address = read_header(path)
    name = label
    if name is None:
        name = stem if stem and LABEL.match(stem) else None
    if name is None:
        return None
    return {"name": name, "variant": variant, "address": address}


def iter_c_files(paths):
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            yield from sorted(q for q in p.rglob("*.c") if q.is_file())
        elif p.is_file() and p.suffix == ".c":
            yield p
        elif p.is_file():
            print("skipped (not a .c file): %s" % p)
        else:
            print("not found: %s" % p)


# -- the index --------------------------------------------------------------

def load_index(path: Path) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def write_index(path: Path, records: list[dict]) -> None:
    refuse_inside_git(path, "index")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    records = sorted(records, key=lambda r: (r["name"].lower(), r["path"].lower(), r["build"]))
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def cmd_scan(args) -> int:
    idx = index_path(args)
    refuse_inside_git(idx, "index")
    build = current_build(args)
    records = load_index(idx) if idx.is_file() else []
    by_key = {(r["path"], r["build"]): r for r in records}
    added = updated = unchanged = 0
    unnamed = []
    now = _dt.datetime.now().isoformat(timespec="seconds")
    for path in iter_c_files(args.paths):
        resolved = path.resolve()
        try:
            fields = describe(resolved)
            st = resolved.stat()
        except OSError as exc:
            unnamed.append("%s (%s)" % (resolved, exc))
            continue
        if fields is None:
            unnamed.append(str(resolved))
            continue
        mtime = _dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
        key = (str(resolved), build)
        old = by_key.get(key)
        note = args.note if args.note is not None else (old["note"] if old else "")
        rec = {
            "name": fields["name"],
            "variant": fields["variant"],
            "address": fields["address"],
            "build": build,
            "path": str(resolved),
            "bytes": st.st_size,
            "mtime": mtime,
            "recorded": now,
            "note": note,
        }
        if old is None:
            added += 1
        elif any(old.get(k) != rec[k] for k in ("name", "variant", "address", "bytes", "mtime", "note")):
            updated += 1
        else:
            unchanged += 1
            continue
        by_key[key] = rec
    if added or updated or not idx.is_file():
        write_index(idx, list(by_key.values()))
    print("scan: added=%d updated=%d unchanged=%d build=%s index=%s"
          % (added, updated, unchanged, short_build(build), idx))
    for p in unnamed:
        print("could not name: %s" % p)
    return 0


def _line(r: dict) -> str:
    return "  ".join([
        r["name"], r["variant"] or "-", short_build(r["build"]), r["mtime"][:10],
        r["path"], r.get("note") or "",
    ]).rstrip()


def cmd_has(args) -> int:
    idx = index_path(args)
    if not idx.is_file():
        print("no index at %s: record decompiles first with `py -3 tools/decomp_index.py "
              "scan <dir>`" % idx)
        return 1
    records = load_index(idx)
    build = current_build(args)
    q = args.query
    if re.fullmatch(r"0[xX][0-9A-Fa-f]+", q):
        want = int(q, 16)
        match = lambda r: r.get("address") is not None and int(r["address"], 16) == want  # noqa: E731
    elif args.contains:
        needle = normalise(q).lower()
        match = lambda r: needle in normalise(r["name"]).lower()  # noqa: E731
    else:
        needle = normalise(q)
        match = lambda r: normalise(r["name"]) == needle  # noqa: E731
    hits = [r for r in records if match(r)]
    mine = [r for r in hits if r["build"] == build]
    other = [r for r in hits if r["build"] != build]
    for r in sorted(mine, key=lambda r: (r["name"], r["path"])):
        print(_line(r))
    for r in sorted(other, key=lambda r: (r["name"], r["path"])):
        print("[other build] " + _line(r))
    if not mine:
        print("no record of %r for build %s%s" % (
            q, short_build(build), " (only for another build, above)" if other else ""))
        return 1
    return 0


def cmd_build_hash(args) -> int:
    print(sha256_of(exe_path(args)))
    return 0


# -- the slot-name technique --------------------------------------------------

class PE:
    """A PE32+ image read from disk: image base and file-backed sections."""

    def __init__(self, path: Path):
        self.data = Path(path).read_bytes()
        d = self.data
        if len(d) < 0x40 or d[:2] != b"MZ":
            raise Refusal("%s is not a PE32+ file (no MZ header)" % path)
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        if pe + 24 > len(d) or d[pe:pe + 4] != b"PE\0\0":
            raise Refusal("%s is not a PE32+ file (no PE signature)" % path)
        nsec, = struct.unpack_from("<H", d, pe + 6)
        opt_size, = struct.unpack_from("<H", d, pe + 20)
        opt = pe + 24
        if opt + 32 > len(d) or struct.unpack_from("<H", d, opt)[0] != 0x20B:
            raise Refusal("%s is not a PE32+ file (optional header is not PE32+)" % path)
        self.base, = struct.unpack_from("<Q", d, opt + 24)
        self.sections = []
        off = opt + opt_size
        for _ in range(nsec):
            if off + 40 > len(d):
                break
            _vsz, va, rsz, raw = struct.unpack_from("<IIII", d, off + 8)
            rsz = min(rsz, max(0, len(d) - raw))
            self.sections.append((self.base + va, raw, rsz))
            off += 40

    def to_offset(self, va: int, length: int = 1) -> int | None:
        for start, raw, rsz in self.sections:
            if start <= va and va + length <= start + rsz:
                return raw + (va - start)
        return None

    def to_va(self, offset: int) -> int | None:
        for start, raw, rsz in self.sections:
            if raw <= offset < raw + rsz:
                return start + (offset - raw)
        return None

    def identifier_at(self, va: int) -> str | None:
        fo = self.to_offset(va)
        if fo is None:
            return None
        # Only a string start names anything: a pointer into the middle of a
        # longer string would otherwise be named after its tail. find_slots
        # applies the same rule, so slot-name and find-name agree.
        if fo > 0 and self.data[fo - 1] != 0:
            return None
        m = IDENTIFIER.match(self.data, fo)
        return m.group(0)[:-1].decode("ascii") if m else None

    def slot_name(self, slot: int) -> str | None:
        fo = self.to_offset(slot - 8, 8)
        if fo is None:
            return None
        ptr, = struct.unpack_from("<Q", self.data, fo)
        return self.identifier_at(ptr)

    def find_slots(self, name: str) -> list[int]:
        needle = name.encode("ascii") + b"\0"
        slots = []
        d = self.data
        i = d.find(needle)
        while i >= 0:
            if i == 0 or d[i - 1] == 0:
                va = self.to_va(i)
                if va is not None:
                    pk = struct.pack("<Q", va)
                    j = d.find(pk)
                    while j >= 0:
                        pva = self.to_va(j)
                        if pva is not None:
                            slots.append(pva + 8)
                        j = d.find(pk, j + 1)
            i = d.find(needle, i + 1)
        return sorted(set(slots))


def _parse_address(text: str) -> int:
    try:
        return int(text[2:] if text.lower().startswith("0x") else text, 16)
    except ValueError:
        raise Refusal("not a hex address: %r" % text) from None


def cmd_slot_name(args) -> int:
    pe = PE(exe_path(args))
    missing = 0
    for a in args.addresses:
        slot = _parse_address(a)
        name = pe.slot_name(slot)
        missing += name is None
        print("0x%x %s" % (slot, name or "?"))
    return 1 if missing else 0


def cmd_find_name(args) -> int:
    pe = PE(exe_path(args))
    missing = 0
    for name in args.names:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", name):
            raise Refusal("not an identifier: %r" % name)
        slots = pe.find_slots(name)
        if not slots:
            missing += 1
            print("%s ?" % name)
        for s in slots:
            print("%s 0x%x" % (name, s))
    return 1 if missing else 0


def cmd_annotate(args) -> int:
    out = Path(args.out)
    refuse_inside_git(out, "annotated copy")
    pe = PE(exe_path(args))
    text = Path(args.input).read_text(encoding="latin-1")
    cache: dict[int, str | None] = {}
    renamed = kept = 0

    def sub(m):
        nonlocal renamed, kept
        slot = int(m.group(1), 16)
        if slot not in cache:
            cache[slot] = pe.slot_name(slot)
        name = cache[slot]
        if name is None:
            kept += 1
            return m.group(0)
        renamed += 1
        return "V_" + name

    result = GLOBAL_TOKEN.sub(sub, text)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="latin-1", newline="") as f:
        f.write(result)
    print("annotate: renamed=%d kept=%d -> %s" % (renamed, kept, out), file=sys.stderr)
    return 0


# -- command line -------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    idx = argparse.ArgumentParser(add_help=False)
    idx.add_argument("--index", help="index file (default: env %s, else %s)" % (ENV_INDEX, default_index()))
    build = argparse.ArgumentParser(add_help=False)
    build.add_argument("--build", help="build id: a sha256, or any text such as 'unknown'")
    exe = argparse.ArgumentParser(add_help=False)
    exe.add_argument("--exe", help="game executable (default: env %s, else %s)" % (ENV_EXE, default_exe()))

    p = argparse.ArgumentParser(prog="decomp_index.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", parents=[idx, build, exe], help="record .c decompiles under PATH...")
    s.add_argument("paths", nargs="+", metavar="PATH")
    s.add_argument("--note", help="note stored on every record this scan adds or updates")
    s.set_defaults(func=cmd_scan)

    h = sub.add_parser("has", parents=[idx, build, exe], help="is QUERY decompiled for this build?")
    h.add_argument("query", metavar="QUERY", help="script name, or 0x<address>")
    h.add_argument("--contains", action="store_true", help="substring match (case-insensitive)")
    h.set_defaults(func=cmd_has)

    b = sub.add_parser("build-hash", parents=[exe], help="print the executable's sha256")
    b.set_defaults(func=cmd_build_hash)

    sn = sub.add_parser("slot-name", parents=[exe], help="name variable-slot globals by address")
    sn.add_argument("addresses", nargs="+", metavar="ADDR")
    sn.set_defaults(func=cmd_slot_name)

    fn = sub.add_parser("find-name", parents=[exe], help="find the slot(s) of a global by name")
    fn.add_argument("names", nargs="+", metavar="NAME")
    fn.set_defaults(func=cmd_find_name)

    an = sub.add_parser("annotate", parents=[exe], help="rename resolvable globals in a decompile")
    an.add_argument("input", metavar="IN")
    an.add_argument("out", metavar="OUT")
    an.set_defaults(func=cmd_annotate)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        return args.func(args)
    except Refusal as exc:
        print("decomp_index: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
