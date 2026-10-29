#!/usr/bin/env python3
"""Map Hero Siege's renumbered closures from one game build to the next.

A game update renumbers the anonymous closures (`anon@N`, `___struct___N`) in
the compiled-code table, so every closure name a mod hooks or a doc cites can
name nothing, or a different function, in the new build. This tool reads that
table straight out of each build's executable, pairs each referenced closure
with its counterpart in the new build, and states the evidence for each pair:

    name-unique                 the closure's name with its numbers blanked
                                occurs once in each build
    fingerprint-unique          siblings share the blanked name, and the
                                closure's code fingerprint matches its rank
                                partner by at least MARGIN more than any
                                other sibling
    rank-order-fingerprint-tie  siblings whose fingerprints tie: the pair
                                rests on rank order alone (the fallback)
    rank-order-no-fingerprint   no extent could be found for the function

Rank order is the numeric order of a group's anon/struct numbers; the rank
partner of the i-th closure of a group in the old build is the i-th of the
same group in the new one. A sibling that outscores the rank partner by more
than MARGIN is a conflict, and a group whose member count changed is refused:
on either, `map` writes nothing and exits 1.

The table is YYToolkit's `YYGMLFuncs`: 24-byte rows of name pointer, function
pointer and variables pointer, initialised data in the exe's `.data`. A row
counts when its name pointer reaches a `gml_` string and its function lies in
`.text`. A function's fingerprint covers its `.pdata` extent (a leaf function
without an entry runs to the next known function start) and holds its direct
`E8 rel32` calls into table functions, by callee name with the closure numbers
blanked; the printable strings it loads with a RIP-relative `lea`, digit runs
blanked; and its size. Fingerprint content stays in memory: the map and this
tool's output carry names, evidence classes and numbers only (AGENTS.md §
"Legal").

Subcommands:

    table <exe> [--name <full name>]
        prints rows=<n> (and rva=0x<hex> for --name; exit 1 if absent)
    map --old-exe A --new-exe B --scan <path>... [--exclude <glob>...] --out <json>
        one row per old-build closure a scanned file spells whose rank
        partner is not itself
    verify <json> --old-exe A --new-exe B
        recomputes every row; exit 0 only for conflicts=0, mismatches=0 and
        both sha256 values matching the header
    rewrite <json> <path>... [--exclude <glob>...]
        replaces each row's full name, short name and identifier in one
        simultaneous pass, at token boundaries, every other byte untouched
    check <json> <path>... [--exclude <glob>...]
        prints path:line: spelling for each old spelling the new build lacks,
        then stale=<n>; exit 1 if n > 0

Scanning reads the git-tracked text files of each path (`git -C <path>
ls-files`, so a submodule is listed by its own repository) and skips gitlinks
and any `closure_renames_*.json` map. `map` and `rewrite` also skip the SDK's
generated script bindings (GENERATED_BINDINGS): they are regenerated from the
new build by `tools/extract_and_generate_sdk.py`, spell every new-build name,
and a rename pass over them would corrupt a surviving name.

Standard library only. Run from the hub root with `py -3`.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from array import array
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_and_generate_sdk import sanitize_identifier  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

MARGIN = 0.05
CALL_WEIGHT = 0.8
SIZE_WEIGHT = 0.2

EVIDENCE_CLASSES = (
    "name-unique",
    "fingerprint-unique",
    "rank-order-fingerprint-tie",
    "rank-order-no-fingerprint",
)
ROW_KEYS = (
    "old", "new", "old_identifier", "new_identifier", "evidence",
    "group_size", "score", "margin", "name_survives",
)

SCRIPT_PREFIX = "gml_Script_"
GENERATED_BINDINGS = (
    "hs-game-sdk/cpp/include/hs_game_sdk/scripts.hpp",
    "hs-game-sdk/python/hs_game_sdk/scripts.py",
    "hs-game-sdk/ts/src/scripts.ts",
)
MAP_FILE_GLOB = "closure_renames_*.json"

_NUMBERED = re.compile(r"(anon@|___struct___)(\d+)")
_TOKEN = re.compile(rb"[A-Za-z0-9_@]+")
_LEA = re.compile(rb"(?=[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d])")
_DIGITS = re.compile(rb"\d+")


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

def is_closure(name: str) -> bool:
    return name.startswith(SCRIPT_PREFIX) and ("anon@" in name or "___struct___" in name)


def group_key(name: str) -> str:
    """The name with only its anon/struct numbers blanked."""
    return _NUMBERED.sub(lambda m: m.group(1) + "#", name)


def rank_key(name: str) -> Tuple[int, ...]:
    return tuple(int(m.group(2)) for m in _NUMBERED.finditer(name))


def short_name(name: str) -> str:
    return name[len(SCRIPT_PREFIX):] if name.startswith(SCRIPT_PREFIX) else name


def spellings(name: str) -> Tuple[str, str, str]:
    """The full name, the short name and the SDK identifier."""
    return name, short_name(name), sanitize_identifier(name)


# --------------------------------------------------------------------------
# PE image
# --------------------------------------------------------------------------

@dataclass
class Section:
    name: str
    va: int
    vsize: int
    rsize: int
    rptr: int

    def contains(self, rva: int) -> bool:
        return self.va <= rva < self.va + self.vsize


class PeImage:
    """The few parts of a PE32+ image this tool reads."""

    def __init__(self, data: bytes):
        self.data = data
        if data[:2] != b"MZ":
            raise ValueError("not a PE file (no MZ header)")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("not a PE file (no PE signature)")
        nsec, = struct.unpack_from("<H", data, pe + 6)
        opt_size, = struct.unpack_from("<H", data, pe + 20)
        opt = pe + 24
        if struct.unpack_from("<H", data, opt)[0] != 0x20B:
            raise ValueError("not a PE32+ image")
        self.image_base = struct.unpack_from("<Q", data, opt + 24)[0]
        ndirs = struct.unpack_from("<I", data, opt + 108)[0]
        self.dirs = [struct.unpack_from("<II", data, opt + 112 + 8 * i)
                     for i in range(min(ndirs, 16))]
        self.sections: List[Section] = []
        sh = opt + opt_size
        for i in range(nsec):
            o = sh + 40 * i
            name = data[o:o + 8].rstrip(b"\0").decode("ascii", "replace")
            vsize, va, rsize, rptr = struct.unpack_from("<IIII", data, o + 8)
            self.sections.append(Section(name, va, vsize or rsize, rsize, rptr))

    def section(self, name: str) -> Section:
        for s in self.sections:
            if s.name == name:
                return s
        raise ValueError(f"no {name} section")

    def section_at(self, rva: int) -> Optional[Section]:
        for s in self.sections:
            if s.contains(rva):
                return s
        return None

    def offset(self, rva: int) -> Optional[int]:
        s = self.section_at(rva)
        if s is None or rva - s.va >= s.rsize:
            return None
        return s.rptr + rva - s.va

    def cstring(self, rva: int, limit: int = 1024) -> Optional[bytes]:
        off = self.offset(rva)
        if off is None:
            return None
        end = self.data.find(b"\0", off, off + limit)
        return None if end < 0 else self.data[off:end]

    def pdata(self) -> Dict[int, int]:
        """Function begin RVA -> end RVA from the exception directory."""
        if len(self.dirs) <= 3:
            return {}
        rva, size = self.dirs[3]
        off = self.offset(rva) if size else None
        out: Dict[int, int] = {}
        if off is None:
            return out
        for begin, end, _unwind in struct.iter_unpack("<III", self.data[off:off + size - size % 12]):
            if begin and end > begin:
                out.setdefault(begin, end)
        return out

    def file_version(self) -> str:
        """FileVersion from the VS_FIXEDFILEINFO block, or '' when absent."""
        sig = b"\xbd\x04\xef\xfe"
        try:
            rs = self.section(".rsrc")
            lo, hi = rs.rptr, rs.rptr + rs.rsize
        except ValueError:
            lo, hi = 0, len(self.data)
        at = self.data.find(sig, lo, hi)
        if at < 0:
            return ""
        ms, ls = struct.unpack_from("<II", self.data, at + 8)
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


# --------------------------------------------------------------------------
# Fingerprints
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Fingerprint:
    calls: Tuple[Tuple[str, int], ...]
    strings: Tuple[Tuple[bytes, int], ...]
    size: int

    def bag(self) -> Counter:
        bag: Counter = Counter()
        for k, n in self.calls:
            bag[("c", k)] += n
        for k, n in self.strings:
            bag[("s", k)] += n
        return bag


def similarity(a: Fingerprint, b: Fingerprint) -> float:
    """0.8 x weighted Jaccard of the call and string multisets + 0.2 x size ratio."""
    ba, bb = a.bag(), b.bag()
    keys = set(ba) | set(bb)
    union = sum(max(ba[k], bb[k]) for k in keys)
    inter = sum(min(ba[k], bb[k]) for k in keys)
    jac = inter / union if union else 1.0
    big = max(a.size, b.size)
    ratio = min(a.size, b.size) / big if big else 1.0
    return round(CALL_WEIGHT * jac + SIZE_WEIGHT * ratio, 6)


# --------------------------------------------------------------------------
# Builds
# --------------------------------------------------------------------------

class BuildBase:
    """A build's closure table: names, groups and fingerprints."""

    names: List[str]

    def _index(self) -> None:
        self.name_set = set(self.names)
        groups: Dict[str, List[str]] = {}
        for n in self.names:
            if is_closure(n):
                groups.setdefault(group_key(n), []).append(n)
        for members in groups.values():
            members.sort(key=lambda n: (rank_key(n), n))
        self.groups = groups

    def group(self, key: str) -> List[str]:
        return self.groups.get(key, [])

    def fingerprint(self, name: str) -> Optional[Fingerprint]:
        raise NotImplementedError


class ExeBuild(BuildBase):
    """The compiled-code table and fingerprints of one Hero_Siege.exe."""

    def __init__(self, path: Path):
        self.path = Path(path)
        raw = self.path.read_bytes()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self.pe = PeImage(raw)
        self.file_version = self.pe.file_version()
        self.rows = read_table(self.pe)
        self.names = [n for n, _ in self.rows]
        self.rva = {}
        for n, r in self.rows:
            self.rva.setdefault(n, r)
        self._index()
        text = self.pe.section(".text")
        self._text = (text.va, text.va + text.vsize)
        self._pdata = self.pe.pdata()
        self._starts = sorted(set(self._pdata) | {r for _, r in self.rows})
        self._callee: Dict[int, str] = {}
        for n, r in self.rows:
            self._callee.setdefault(r, group_key(n))
        self._fp: Dict[str, Optional[Fingerprint]] = {}

    def extent(self, rva: int) -> Optional[Tuple[int, int]]:
        end = self._pdata.get(rva)
        if end:
            return rva, end
        i = bisect_right(self._starts, rva)
        nxt = self._starts[i] if i < len(self._starts) else self._text[1]
        return (rva, nxt) if nxt > rva else None

    def fingerprint(self, name: str) -> Optional[Fingerprint]:
        if name not in self._fp:
            rva = self.rva.get(name)
            self._fp[name] = None if rva is None else fingerprint_at(self.pe, rva, self.extent(rva), self._callee)
        return self._fp[name]


def read_table(pe: PeImage) -> List[Tuple[str, int]]:
    """The compiled-code table's rows as (name, function RVA), in table order.

    Returns the longest contiguous run of 24-byte rows whose name pointer
    reaches a `gml_` string and whose function pointer lies in `.text`.
    """
    data = pe.section(".data")
    text = pe.section(".text")
    raw = pe.data[data.rptr:data.rptr + data.rsize]
    qwords = array("Q")
    qwords.frombytes(raw[:len(raw) // 8 * 8])
    if sys.byteorder != "little":
        qwords.byteswap()
    base = pe.image_base
    tlo, thi = base + text.va, base + text.va + text.vsize
    names: Dict[int, Optional[str]] = {}

    def name_at(va: int) -> Optional[str]:
        if va in names:
            return names[va]
        out = None
        if base <= va < base + 0x1_0000_0000:
            s = pe.cstring(va - base)
            if s and s.startswith(b"gml_"):
                try:
                    out = s.decode("ascii")
                except UnicodeDecodeError:
                    out = None
        names[va] = out
        return out

    hits: List[Tuple[int, str, int]] = []
    for k in range(1, len(qwords)):
        q = qwords[k]
        if tlo <= q < thi:
            n = name_at(qwords[k - 1])
            if n:
                hits.append((k - 1, n, q - base))
    best: List[Tuple[str, int]] = []
    run: List[Tuple[str, int]] = []
    prev = None
    for k, n, rva in hits:
        if prev is not None and k == prev + 3:
            run.append((n, rva))
        else:
            run = [(n, rva)]
        prev = k
        if len(run) > len(best):
            best = run
    return list(best)


def fingerprint_at(pe: PeImage, rva: int, extent: Optional[Tuple[int, int]],
                   callee: Dict[int, str]) -> Optional[Fingerprint]:
    if extent is None:
        return None
    lo, hi = extent
    off = pe.offset(lo)
    if off is None:
        return None
    code = pe.data[off:off + (hi - lo)]
    calls: Counter = Counter()
    for m in re.finditer(rb"\xe8", code):
        i = m.start()
        if i + 5 > len(code):
            break
        target = lo + i + 5 + struct.unpack_from("<i", code, i + 1)[0]
        name = callee.get(target)
        if name is not None:
            calls[name] += 1
    strings: Counter = Counter()
    for m in _LEA.finditer(code):
        i = m.start()
        if i + 7 > len(code):
            break
        target = lo + i + 7 + struct.unpack_from("<i", code, i + 3)[0]
        sec = pe.section_at(target)
        if sec is None or sec.name != ".rdata":
            continue
        s = pe.cstring(target, 512)
        if s and len(s) >= 2 and all(0x20 <= c < 0x7F or c in (9, 10, 13) for c in s):
            strings[_DIGITS.sub(b"#", s)] += 1
    return Fingerprint(tuple(sorted(calls.items())), tuple(sorted(strings.items())), hi - lo)


# --------------------------------------------------------------------------
# Mapping
# --------------------------------------------------------------------------

@dataclass
class MapResult:
    rows: List[dict] = field(default_factory=list)
    self_mapped: Counter = field(default_factory=Counter)
    conflicts: List[dict] = field(default_factory=list)
    size_changes: List[Tuple[str, int, int]] = field(default_factory=list)

    @property
    def refused(self) -> bool:
        return bool(self.conflicts or self.size_changes)

    def counts(self) -> Dict[str, object]:
        by_class = Counter(r["evidence"] for r in self.rows)
        return {
            "rows": len(self.rows),
            "conflicts": len(self.conflicts),
            "size_changes": len(self.size_changes),
            "self_mapped": sum(self.self_mapped.values()),
            "by_evidence": {c: by_class.get(c, 0) for c in EVIDENCE_CLASSES},
            "self_mapped_by_evidence": {c: self.self_mapped.get(c, 0) for c in EVIDENCE_CLASSES},
        }


def pair_evidence(old: BuildBase, new: BuildBase, name: str, members_old: List[str],
                  members_new: List[str]) -> Tuple[str, Optional[float], Optional[float], Optional[str]]:
    """(evidence, score, margin, conflicting sibling) for one old closure."""
    i = members_old.index(name)
    partner = members_new[i]
    fo = old.fingerprint(name)
    fp = new.fingerprint(partner)
    score = similarity(fo, fp) if fo is not None and fp is not None else None
    if len(members_old) == 1:
        return "name-unique", score, None, None
    if score is None:
        return "rank-order-no-fingerprint", None, None, None
    best_other, best_name = None, None
    for sib in members_new:
        if sib == partner:
            continue
        fs = new.fingerprint(sib)
        if fs is None:
            continue
        s = similarity(fo, fs)
        if best_other is None or s > best_other:
            best_other, best_name = s, sib
    if best_other is None:
        return "fingerprint-unique", score, None, None
    margin = round(score - best_other, 6)
    if -margin > MARGIN + 1e-9:
        return "conflict", score, margin, best_name
    if margin >= MARGIN - 1e-9:
        return "fingerprint-unique", score, margin, None
    return "rank-order-fingerprint-tie", score, margin, None


def compute_map(old: BuildBase, new: BuildBase, referenced: Iterable[str]) -> MapResult:
    result = MapResult()
    by_group: Dict[str, List[str]] = {}
    for n in sorted(set(referenced)):
        if is_closure(n) and n in old.name_set:
            by_group.setdefault(group_key(n), []).append(n)
    for key in sorted(by_group):
        mo, mn = old.group(key), new.group(key)
        if len(mo) != len(mn):
            result.size_changes.append((key, len(mo), len(mn)))
            continue
        for name in by_group[key]:
            partner = mn[mo.index(name)]
            evidence, score, margin, rival = pair_evidence(old, new, name, mo, mn)
            if evidence == "conflict":
                result.conflicts.append({"old": name, "rank_partner": partner, "rival": rival,
                                         "score": score, "margin": margin})
                continue
            if partner == name:
                result.self_mapped[evidence] += 1
                continue
            result.rows.append({
                "old": name,
                "new": partner,
                "old_identifier": sanitize_identifier(name),
                "new_identifier": sanitize_identifier(partner),
                "evidence": evidence,
                "group_size": len(mo),
                "score": None if score is None else round(score, 4),
                "margin": None if margin is None else round(margin, 4),
                "name_survives": name in new.name_set,
            })
    result.rows.sort(key=lambda r: r["old"])
    return result


# --------------------------------------------------------------------------
# Scanning tracked files
# --------------------------------------------------------------------------

def _display(path: Path) -> str:
    try:
        return Path(os.path.relpath(path, Path.cwd())).as_posix()
    except ValueError:
        return path.as_posix()


def _excluded(rel: str, shown: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(rel, p) or fnmatch.fnmatchcase(shown, p) for p in patterns)


def tracked_files(roots: Sequence[str], excludes: Sequence[str] = (),
                  skip_generated: bool = False) -> List[Path]:
    """Git-tracked text files under each root, gitlinks and maps skipped."""
    generated = {(ROOT / g).resolve() for g in GENERATED_BINDINGS} if skip_generated else set()
    out: List[Path] = []
    seen = set()
    for root in roots:
        base = Path(root)
        listing = subprocess.run(["git", "-C", str(base), "ls-files", "-s", "-z"],
                                 capture_output=True, check=True).stdout
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            meta, _, rel_b = entry.partition(b"\t")
            if meta.startswith(b"160000"):
                continue
            rel = rel_b.decode("utf-8")
            path = (base / rel)
            full = path.resolve()
            if full in seen or full in generated:
                continue
            if fnmatch.fnmatchcase(path.name, MAP_FILE_GLOB):
                continue
            if _excluded(rel, _display(path), excludes):
                continue
            if not path.is_file():
                continue
            seen.add(full)
            out.append(path)
    return out


def read_text(path: Path) -> Optional[bytes]:
    data = path.read_bytes()
    return None if b"\0" in data[:8192] else data


def spelling_index(names: Iterable[str]) -> Dict[bytes, str]:
    """Every spelling of each name -> the full name; an ambiguous spelling is dropped."""
    index: Dict[bytes, str] = {}
    clash = set()
    for n in names:
        for s in set(spellings(n)):
            b = s.encode("ascii")
            if b in index and index[b] != n:
                clash.add(b)
            index[b] = n
    for b in clash:
        del index[b]
    return index


def referenced_closures(files: Iterable[Path], old: BuildBase) -> Dict[str, List[str]]:
    """Old-build closures each scanned file spells, in any of the three forms."""
    index = spelling_index(n for n in old.names if is_closure(n))
    found: Dict[str, List[str]] = {}
    for path in files:
        data = read_text(path)
        if data is None:
            continue
        for m in _TOKEN.finditer(data):
            name = index.get(m.group())
            if name is not None:
                found.setdefault(name, []).append(_display(path))
    return found


def replacement_table(rows: Sequence[dict]) -> Dict[bytes, bytes]:
    table: Dict[bytes, bytes] = {}
    for r in rows:
        for o, n in zip(spellings(r["old"]), spellings(r["new"])):
            ob = o.encode("ascii")
            if ob in table and table[ob] != n.encode("ascii"):
                raise ValueError(f"two rows rewrite the same spelling: {o}")
            table[ob] = n.encode("ascii")
    return table


def rewrite_bytes(data: bytes, table: Dict[bytes, bytes]) -> Tuple[bytes, int]:
    """One simultaneous pass: each whole token is replaced at most once."""
    count = 0

    def sub(m: "re.Match[bytes]") -> bytes:
        nonlocal count
        new = table.get(m.group())
        if new is None:
            return m.group()
        count += 1
        return new

    return _TOKEN.sub(sub, data), count


def stale_spellings(data: bytes, rows: Sequence[dict]) -> List[Tuple[int, str]]:
    """(line, spelling) for each old spelling the new build no longer has."""
    stale = {}
    for r in rows:
        if r["name_survives"]:
            continue
        for s in spellings(r["old"]):
            stale[s.encode("ascii")] = s
    out = []
    for m in _TOKEN.finditer(data):
        s = stale.get(m.group())
        if s is not None:
            out.append((data.count(b"\n", 0, m.start()) + 1, s))
    return out


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def build_header(b: ExeBuild) -> dict:
    return {"file_version": b.file_version, "sha256": b.sha256, "table_rows": len(b.rows)}


def print_counts(result: MapResult) -> None:
    c = result.counts()
    print(f"rows={c['rows']} conflicts={c['conflicts']}")
    print(f"size_changes={c['size_changes']} self_mapped={c['self_mapped']}")
    for cls in EVIDENCE_CLASSES:
        print(f"  {cls}={c['by_evidence'][cls]} (self-mapped {c['self_mapped_by_evidence'][cls]})")
    for key, a, b in result.size_changes:
        print(f"SIZE CHANGE {key}: {a} -> {b}")
    for cf in result.conflicts:
        print(f"CONFLICT {cf['old']}: rank partner {cf['rank_partner']} outscored by "
              f"{cf['rival']} (margin {cf['margin']})")


def cmd_table(args: argparse.Namespace) -> int:
    b = ExeBuild(Path(args.exe))
    print(f"rows={len(b.rows)}")
    print(f"file_version={b.file_version}")
    print(f"sha256={b.sha256}")
    if args.name:
        rva = b.rva.get(args.name)
        if rva is None:
            print(f"absent: {args.name}")
            return 1
        print(f"rva=0x{rva:x}")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    old, new = ExeBuild(Path(args.old_exe)), ExeBuild(Path(args.new_exe))
    files = tracked_files(args.scan, args.exclude, skip_generated=True)
    referenced = referenced_closures(files, old)
    result = compute_map(old, new, referenced)
    print(f"files={len(files)} referenced={len(referenced)}")
    print_counts(result)
    if result.refused:
        print("refused: nothing written")
        return 1
    doc = {
        "about": ("Hero Siege closure renames between two builds, from tools/closure_port_map.py. "
                  "Each row pairs an old-build closure some tracked file spelled with its rank "
                  "partner in the new build, and the evidence for the pair. Old spellings are kept "
                  "here on purpose; this file is the record of them."),
        "old_build": build_header(old),
        "new_build": build_header(new),
        "margin": MARGIN,
        "counts": result.counts(),
        "rows": result.rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {_display(out)}")
    return 0


def load_map(path: str) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    for r in doc["rows"]:
        if set(r) != set(ROW_KEYS) or r["evidence"] not in EVIDENCE_CLASSES:
            raise ValueError(f"malformed row: {r.get('old')}")
    return doc


def cmd_verify(args: argparse.Namespace) -> int:
    doc = load_map(args.json)
    old, new = ExeBuild(Path(args.old_exe)), ExeBuild(Path(args.new_exe))
    sha_ok = (old.sha256 == doc["old_build"]["sha256"] and new.sha256 == doc["new_build"]["sha256"])
    result = compute_map(old, new, [r["old"] for r in doc["rows"]])
    fresh = {r["old"]: r for r in result.rows}
    mismatches = 0
    for r in doc["rows"]:
        f = fresh.get(r["old"])
        same = f is not None and all(
            (abs((f[k] or 0) - (r[k] or 0)) <= 1e-4 and (f[k] is None) == (r[k] is None))
            if k in ("score", "margin") else f[k] == r[k]
            for k in ROW_KEYS)
        if not same:
            mismatches += 1
            print(f"MISMATCH {r['old']}: map {r['new']} {r['evidence']}; "
                  f"recomputed {f['new'] + ' ' + f['evidence'] if f else 'no row'}")
    for key, a, b in result.size_changes:
        print(f"SIZE CHANGE {key}: {a} -> {b}")
    print(f"sha256={'match' if sha_ok else 'MISMATCH'}")
    print(f"rows={len(doc['rows'])} conflicts={len(result.conflicts)} mismatches={mismatches}")
    print(f"conflicts={len(result.conflicts)}")
    print(f"mismatches={mismatches}")
    return 0 if sha_ok and not result.conflicts and not mismatches and not result.size_changes else 1


def cmd_rewrite(args: argparse.Namespace) -> int:
    doc = load_map(args.json)
    table = replacement_table(doc["rows"])
    total = changed = 0
    for path in tracked_files(args.paths, args.exclude, skip_generated=True):
        data = read_text(path)
        if data is None:
            continue
        new, n = rewrite_bytes(data, table)
        if n:
            path.write_bytes(new)
            changed += 1
            total += n
            print(f"{_display(path)}: {n}")
    print(f"files={changed} replacements={total}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    doc = load_map(args.json)
    stale = 0
    for path in tracked_files(args.paths, args.exclude):
        data = read_text(path)
        if data is None:
            continue
        for line, s in stale_spellings(data, doc["rows"]):
            stale += 1
            print(f"{_display(path)}:{line}: {s}")
    print(f"stale={stale}")
    return 1 if stale else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("table", help="read an exe's compiled-code table")
    p.add_argument("exe")
    p.add_argument("--name")
    p.set_defaults(fn=cmd_table)
    p = sub.add_parser("map", help="map referenced closures from one build to the next")
    p.add_argument("--old-exe", required=True)
    p.add_argument("--new-exe", required=True)
    p.add_argument("--scan", action="append", required=True)
    p.add_argument("--exclude", action="append", default=[])
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_map)
    p = sub.add_parser("verify", help="recompute a map's rows")
    p.add_argument("json")
    p.add_argument("--old-exe", required=True)
    p.add_argument("--new-exe", required=True)
    p.set_defaults(fn=cmd_verify)
    for name, fn, text in (("rewrite", cmd_rewrite, "replace old spellings with new ones"),
                           ("check", cmd_check, "list old spellings the new build lacks")):
        p = sub.add_parser(name, help=text)
        p.add_argument("json")
        p.add_argument("paths", nargs="+")
        p.add_argument("--exclude", action="append", default=[])
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
