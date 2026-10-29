"""Checks for `tools/closure_port_map.py`, the two-build closure rename map.

The fixtures are synthetic: `make_pe` writes a small PE32+ image with a
`.text`, `.rdata`, `.data`, `.pdata` and `.rsrc`, a compiled-code table of
24-byte rows in `.data`, and functions built from invented calls and strings.
No byte here comes from the game. Against it the tests pin the table reader,
the fingerprint (calls by blanked callee name, `lea`-loaded strings with digit
runs blanked, the size, a leaf function's extent), grouping and rank order,
each evidence class (a conflict and a changed group size refused), the
surviving-name collision, `rewrite`'s single pass and `check`.

`CommittedMapTests` reads the committed map against the regenerated SDK, and
`ExeTests` reads the two real executables, skipping when either is absent.

Run from the hub root: `py -3 -m unittest tests.test_closure_port_map -v`.
"""
import contextlib
import io
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import closure_port_map as cpm  # noqa: E402
from extract_and_generate_sdk import sanitize_identifier  # noqa: E402

MAP_JSON = ROOT / "hs-game-sdk" / "curated" / "closure_renames_7_0_14_0.json"
SCRIPTS_HPP = ROOT / "hs-game-sdk" / "cpp" / "include" / "hs_game_sdk" / "scripts.hpp"
OLD_EXE = Path("C:/Users/stann/tools/hs-bin/Hero_Siege.exe")
NEW_EXE = Path("C:/Users/stann/tools/hs-bin-7.0.14.0/Hero_Siege.exe")

BASE = 0x140000000
TEXT_RVA, RDATA_RVA, DATA_RVA, PDATA_RVA, RSRC_RVA = 0x1000, 0x20000, 0x30000, 0x40000, 0x50000


def _align(n, a):
    return (n + a - 1) // a * a


def make_pe(funcs, junk_rows=0, version=(7, 0, 99, 1)):
    """A PE32+ image whose compiled-code table lists `funcs`.

    `funcs` is a list of (name, ops, has_pdata); ops are ("call", name),
    ("lea", bytes string) or ("raw", bytes). Functions sit back to back in
    `.text`, each padded with int3 to 16 bytes. `junk_rows` rows whose names
    do not start with `gml_` sit before the table, outside the run.
    """
    def op_size(op):
        return {"call": 5, "lea": 7}.get(op[0]) or len(op[1])

    starts, pos = {}, TEXT_RVA
    for name, ops, _ in funcs:
        starts[name] = pos
        pos = _align(pos + sum(op_size(o) for o in ops), 16)
    text_end = pos
    rdata = bytearray()
    str_rva = {}

    def intern(s):
        if s not in str_rva:
            str_rva[s] = RDATA_RVA + len(rdata)
            rdata.extend(s + b"\0")
        return str_rva[s]

    for name, ops, _ in funcs:
        intern(name.encode())
        for op in ops:
            if op[0] == "lea":
                intern(op[1])
    junk_name = intern(b"not_a_table_name")
    text = bytearray(b"\xcc" * (text_end - TEXT_RVA))
    for name, ops, _ in funcs:
        at = starts[name]
        for op in ops:
            off = at - TEXT_RVA
            if op[0] == "call":
                text[off:off + 5] = b"\xe8" + struct.pack("<i", starts[op[1]] - (at + 5))
                at += 5
            elif op[0] == "lea":
                text[off:off + 7] = b"\x48\x8d\x0d" + struct.pack("<i", str_rva[op[1]] - (at + 7))
                at += 7
            else:
                text[off:off + len(op[1])] = op[1]
                at += len(op[1])
    data = bytearray(struct.pack("<QQQ", 0x1234, 0, 0))
    for _ in range(junk_rows):
        data += struct.pack("<QQQ", BASE + junk_name, BASE + TEXT_RVA, 0)
    for name, _, _ in funcs:
        data += struct.pack("<QQQ", BASE + str_rva[name.encode()], BASE + starts[name], 0)
    data += struct.pack("<QQQ", 0, 0, 0)
    pdata = bytearray()
    for name, ops, has_pdata in funcs:
        if has_pdata:
            end = starts[name] + sum(op_size(o) for o in ops)
            pdata += struct.pack("<III", starts[name], end, 0)
    ms, ls = (version[0] << 16) | version[1], (version[2] << 16) | version[3]
    rsrc = bytearray(16) + b"\xbd\x04\xef\xfe" + struct.pack("<III", 0x10000, ms, ls) + bytearray(16)

    sections = [(b".text", TEXT_RVA, bytes(text)), (b".rdata", RDATA_RVA, bytes(rdata)),
                (b".data", DATA_RVA, bytes(data)), (b".pdata", PDATA_RVA, bytes(pdata)),
                (b".rsrc", RSRC_RVA, bytes(rsrc))]
    pe_off, opt_size = 0x80, 240
    headers = _align(pe_off + 24 + opt_size + 40 * len(sections), 0x200)
    out = bytearray(headers)
    out[0:2] = b"MZ"
    struct.pack_into("<I", out, 0x3C, pe_off)
    out[pe_off:pe_off + 4] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", out, pe_off + 4, 0x8664, len(sections), 0, 0, 0, opt_size, 0x22)
    opt = pe_off + 24
    struct.pack_into("<H", out, opt, 0x20B)
    struct.pack_into("<Q", out, opt + 24, BASE)
    struct.pack_into("<I", out, opt + 108, 16)
    struct.pack_into("<II", out, opt + 112 + 8 * 3, PDATA_RVA, len(pdata))
    struct.pack_into("<II", out, opt + 112 + 8 * 2, RSRC_RVA, len(rsrc))
    sh = opt + opt_size
    for i, (sname, rva, body) in enumerate(sections):
        raw = _align(len(body), 0x200) or 0x200
        struct.pack_into("<8sIIII", out, sh + 40 * i, sname, max(len(body), 1), rva, raw, len(out))
        out += body + bytes(raw - len(body))
    return bytes(out)


S = "gml_Script_"
QP = "@gml_Object_Quest_obj_Create_0"


def base_funcs(numbers=(5, 12, 40), leaf=False):
    """Three siblings of one group plus two helpers and one name-unique closure."""
    funcs = [
        (S + "HelperA", [("raw", b"\x90\xc3")], True),
        (S + "HelperB", [("raw", b"\x90\x90\xc3")], True),
        (S + f"anon@{numbers[0]}" + QP, [("call", S + "HelperA"), ("lea", b"first 17 label"), ("raw", b"\xc3")], True),
        (S + f"anon@{numbers[1]}" + QP, [("call", S + "HelperB"), ("call", S + "HelperB"), ("lea", b"second"), ("raw", b"\x90" * 20 + b"\xc3")], not leaf),
        (S + f"anon@{numbers[2]}" + QP, [("lea", b"third 9"), ("lea", b"third 10"), ("raw", b"\x90" * 40 + b"\xc3")], True),
        (S + "Lonely@anon@77@s_Thing@Funcs", [("call", S + "HelperA"), ("raw", b"\xc3")], True),
        ("gml_Object_Quest_obj_Create_0", [("raw", b"\xc3")], True),
    ]
    return funcs


@contextlib.contextmanager
def captured():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


class FakeBuild(cpm.BuildBase):
    def __init__(self, fps):
        self.fps = dict(fps)
        self.names = list(self.fps)
        self._index()

    def fingerprint(self, name):
        return self.fps[name]


def fp(calls=(), strings=(), size=100):
    return cpm.Fingerprint(tuple(sorted(dict(calls).items())), tuple(sorted(dict(strings).items())), size)


class TempExes(unittest.TestCase):
    def write_exe(self, funcs, **kw):
        path = Path(self.tmp.name) / f"exe{len(list(Path(self.tmp.name).glob('exe*')))}.exe"
        path.write_bytes(make_pe(funcs, **kw))
        return path

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()


class TableAndFingerprintTests(TempExes):
    def test_table_reads_the_contiguous_run_and_its_rvas(self):
        build = cpm.ExeBuild(self.write_exe(base_funcs(), junk_rows=3))
        self.assertEqual(len(build.rows), 7)
        self.assertEqual(build.file_version, "7.0.99.1")
        self.assertEqual(build.rva[S + "HelperA"], TEXT_RVA)
        self.assertIn(S + "anon@40" + QP, build.name_set)
        self.assertNotIn("not_a_table_name", build.name_set)

    def test_table_command_prints_rows_and_rva_and_refuses_an_absent_name(self):
        exe = self.write_exe(base_funcs())
        with captured() as out:
            code = cpm.main(["table", str(exe), "--name", S + "HelperB"])
        self.assertEqual(code, 0)
        self.assertIn("rows=7", out.getvalue())
        self.assertRegex(out.getvalue(), r"rva=0x[0-9a-f]+\n")
        with captured():
            self.assertEqual(cpm.main(["table", str(exe), "--name", S + "Missing"]), 1)

    def test_fingerprint_blanks_callee_numbers_and_string_digits(self):
        build = cpm.ExeBuild(self.write_exe(base_funcs()))
        f = build.fingerprint(S + "anon@5" + QP)
        self.assertEqual(f.calls, ((S + "HelperA", 1),))
        self.assertEqual(f.strings, ((b"first # label", 1),))
        self.assertEqual(f.size, 5 + 7 + 1)
        third = build.fingerprint(S + "anon@40" + QP)
        self.assertEqual(third.strings, ((b"third #", 2),))
        lonely = build.fingerprint(S + "Lonely@anon@77@s_Thing@Funcs")
        self.assertEqual(lonely.calls, ((S + "HelperA", 1),))

    def test_calls_to_a_closure_are_named_with_its_number_blanked(self):
        funcs = base_funcs()
        funcs.append((S + "Caller", [("call", S + "anon@12" + QP), ("raw", b"\xc3")], True))
        build = cpm.ExeBuild(self.write_exe(funcs))
        self.assertEqual(build.fingerprint(S + "Caller").calls, ((S + "anon@#" + QP, 1),))

    def test_a_leaf_without_pdata_runs_to_the_next_known_start(self):
        build = cpm.ExeBuild(self.write_exe(base_funcs(leaf=True)))
        rva = build.rva[S + "anon@12" + QP]
        self.assertNotIn(rva, build._pdata)
        lo, hi = build.extent(rva)
        self.assertEqual(hi, build.rva[S + "anon@40" + QP])
        self.assertEqual(build.fingerprint(S + "anon@12" + QP).calls, ((S + "HelperB", 2),))


class GroupingTests(unittest.TestCase):
    def test_group_key_blanks_only_the_closure_numbers(self):
        self.assertEqual(cpm.group_key(S + "___struct___364@SaveStash@SaveStashFunc"),
                         S + "___struct___#@SaveStash@SaveStashFunc")
        self.assertEqual(cpm.group_key(S + "anon@126@gml_Object_Spawn_Abyss_obj_Create_0"),
                         S + "anon@#@gml_Object_Spawn_Abyss_obj_Create_0")
        self.assertEqual(cpm.group_key(S + "Thing2@anon@5"), S + "Thing2@anon@#")

    def test_rank_order_is_numeric_not_textual(self):
        build = FakeBuild({S + f"anon@{n}" + QP: fp(size=n) for n in (100, 9, 23)})
        self.assertEqual(build.group(S + "anon@#" + QP), [S + f"anon@{n}" + QP for n in (9, 23, 100)])

    def test_is_closure(self):
        self.assertTrue(cpm.is_closure(S + "anon@1@x"))
        self.assertTrue(cpm.is_closure(S + "___struct___3@x"))
        self.assertFalse(cpm.is_closure(S + "SaveStash"))
        self.assertFalse(cpm.is_closure("gml_Object_anon@1"))


def _names(numbers):
    return [S + f"anon@{n}" + QP for n in numbers]


class EvidenceTests(unittest.TestCase):
    def pair(self, old_fps, new_fps):
        return FakeBuild(old_fps), FakeBuild(new_fps)

    def distinct(self, numbers):
        return {n: fp(calls={f"C{i}": 1}, strings={f"s{i}".encode(): i + 1}, size=100 * (i + 1))
                for i, n in enumerate(_names(numbers))}

    def test_name_unique(self):
        old, new = self.pair({S + "Solo@anon@9@F": fp(size=10)}, {S + "Solo@anon@7@F": fp(size=10)})
        r = cpm.compute_map(old, new, [S + "Solo@anon@9@F"]).rows[0]
        self.assertEqual((r["new"], r["evidence"], r["group_size"], r["score"], r["margin"]),
                         (S + "Solo@anon@7@F", "name-unique", 1, 1.0, None))

    def test_fingerprint_unique(self):
        o = self.distinct((5, 12, 40))
        n = dict(zip(_names((4, 11, 39)), o.values()))
        res = cpm.compute_map(*self.pair(o, n), _names((12,)))
        r = res.rows[0]
        self.assertEqual((r["new"], r["evidence"], r["group_size"]), (_names((11,))[0], "fingerprint-unique", 3))
        self.assertGreaterEqual(r["margin"], cpm.MARGIN)

    def test_identical_siblings_fall_back_to_rank_order(self):
        same = fp(calls={"C": 2}, size=50)
        old, new = self.pair(dict.fromkeys(_names((5, 12)), same), dict.fromkeys(_names((6, 13)), same))
        r = cpm.compute_map(old, new, _names((12,))).rows[0]
        self.assertEqual((r["new"], r["evidence"], r["margin"]), (_names((13,))[0], "rank-order-fingerprint-tie", 0.0))

    def test_no_fingerprint(self):
        old, new = self.pair({_names((5,))[0]: None, _names((12,))[0]: fp()},
                             {_names((6,))[0]: fp(), _names((13,))[0]: fp()})
        r = cpm.compute_map(old, new, _names((5,))).rows[0]
        self.assertEqual((r["evidence"], r["score"], r["margin"]), ("rank-order-no-fingerprint", None, None))

    def test_a_sibling_outscoring_the_rank_partner_is_a_refused_conflict(self):
        o = self.distinct((5, 12))
        a, b = o.values()
        old, new = self.pair(o, dict(zip(_names((6, 13)), (b, a))))  # swapped
        res = cpm.compute_map(old, new, _names((5,)))
        self.assertTrue(res.refused)
        self.assertEqual(res.rows, [])
        self.assertEqual(res.conflicts[0]["rival"], _names((13,))[0])

    def test_a_conflict_among_self_mapped_closures_also_refuses(self):
        o = self.distinct((5, 12))
        a, b = o.values()
        old, new = self.pair(o, dict(zip(_names((5, 12)), (b, a))))
        res = cpm.compute_map(old, new, _names((5,)))
        self.assertTrue(res.refused)

    def test_self_mapped_closures_get_no_row(self):
        o = self.distinct((5, 12))
        res = cpm.compute_map(*self.pair(o, dict(o)), _names((5, 12)))
        self.assertEqual(res.rows, [])
        self.assertEqual(sum(res.self_mapped.values()), 2)
        self.assertFalse(res.refused)

    def test_a_group_whose_size_changed_is_refused(self):
        o = self.distinct((5, 12))
        n = self.distinct((5, 12, 40))
        res = cpm.compute_map(*self.pair(o, n), _names((5,)))
        self.assertTrue(res.refused)
        self.assertEqual(res.size_changes, [(S + "anon@#" + QP, 2, 3)])

    def test_the_surviving_name_collision(self):
        """Old 364 is new 365 and old 363 is new 364: 364's name survives as another closure."""
        g = S + "___struct___{}@SaveStash@SaveStashFunc"
        same = fp(calls={"C": 1})
        old, new = self.pair({g.format(363): same, g.format(364): same},
                             {g.format(364): same, g.format(365): same})
        res = cpm.compute_map(old, new, [g.format(364)])
        self.assertEqual(len(res.rows), 1)
        r = res.rows[0]
        self.assertEqual((r["old"], r["new"], r["name_survives"]), (g.format(364), g.format(365), True))
        self.assertEqual(set(r), set(cpm.ROW_KEYS))
        self.assertEqual(r["old_identifier"], sanitize_identifier(g.format(364)))


class GitTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, files):
        for rel, data in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        git = ["git", "-C", str(self.root), "-c", "core.autocrlf=false"]
        subprocess.run(git + ["init", "-q"], check=True)
        self.add_all()

    def add_all(self):
        subprocess.run(["git", "-C", str(self.root), "-c", "core.autocrlf=false", "add", "-A"], check=True)


ROWS = [
    {"old": S + "___struct___363@Stash@F", "new": S + "___struct___364@Stash@F", "name_survives": False},
    {"old": S + "___struct___364@Stash@F", "new": S + "___struct___365@Stash@F", "name_survives": True},
    {"old": S + "anon@126@gml_Object_Spawn_obj_Create_0", "new": S + "anon@119@gml_Object_Spawn_obj_Create_0",
     "name_survives": False},
]


class RewriteAndCheckTests(GitTree):
    def test_one_simultaneous_pass_does_not_chain(self):
        table = cpm.replacement_table(ROWS)
        out, n = cpm.rewrite_bytes(b"a ___struct___363@Stash@F b ___struct___364@Stash@F", table)
        self.assertEqual(out, b"a ___struct___364@Stash@F b ___struct___365@Stash@F")
        self.assertEqual(n, 2)

    def test_all_three_spellings_and_token_boundaries(self):
        table = cpm.replacement_table(ROWS)
        src = (b'"gml_Script_anon@126@gml_Object_Spawn_obj_Create_0"\r\n'
               b"Scripts::gml_Script_anon_126_gml_Object_Spawn_obj_Create_0;\r\n"
               b"`anon@126@gml_Object_Spawn_obj_Create_0`\r\n"
               b"gml_Script_anon_126_gml_Object_Spawn_obj_Create_0_Index\r\n"
               b"x@anon@126@gml_Object_Spawn_obj_Create_0\r\n")
        out, n = cpm.rewrite_bytes(src, table)
        self.assertEqual(n, 3)
        self.assertEqual(out, src.replace(b"126", b"119", 3))
        self.assertEqual(out.count(b"\r\n"), 5)
        self.assertIn(b"126_gml_Object_Spawn_obj_Create_0_Index", out)
        self.assertIn(b"x@anon@126", out)

    def write_map(self, rows):
        full = []
        for r in rows:
            full.append({**r, "old_identifier": sanitize_identifier(r["old"]),
                         "new_identifier": sanitize_identifier(r["new"]), "evidence": "name-unique",
                         "group_size": 1, "score": 1.0, "margin": None})
        path = self.root / "maps" / "closure_renames_test.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"old_build": {}, "new_build": {}, "counts": {}, "rows": full}),
                        encoding="utf-8")
        return path

    def test_rewrite_command_keeps_crlf_and_skips_the_map_and_excluded_paths(self):
        body = b"one\r\nuse anon@126@gml_Object_Spawn_obj_Create_0 here\r\n"
        self.commit({"docs/a.md": body, "skip/b.md": body, "bin.dat": b"\0anon@126@gml_Object_Spawn_obj_Create_0"})
        m = self.write_map(ROWS)
        self.add_all()
        with captured() as out:
            self.assertEqual(cpm.main(["rewrite", str(m), str(self.root), "--exclude", "skip/**"]), 0)
        self.assertEqual((self.root / "docs/a.md").read_bytes(), body.replace(b"126", b"119"))
        self.assertEqual((self.root / "skip/b.md").read_bytes(), body)
        self.assertIn(b"126", (self.root / "bin.dat").read_bytes())
        self.assertIn("anon@126", m.read_text(encoding="utf-8"))
        self.assertIn("files=1 replacements=1", out.getvalue())

    def test_check_flags_stale_spellings_but_not_surviving_ones(self):
        self.commit({"a.txt": b"ok\r\n___struct___364@Stash@F\r\ngml_Script_anon_126_gml_Object_Spawn_obj_Create_0\r\n",
                     "b.txt": b"___struct___365@Stash@F\n"})
        m = self.write_map(ROWS)
        self.add_all()
        with captured() as out:
            code = cpm.main(["check", str(m), str(self.root)])
        self.assertEqual(code, 1)
        self.assertRegex(out.getvalue(), r"a\.txt:3: gml_Script_anon_126_gml_Object_Spawn_obj_Create_0")
        self.assertIn("stale=1", out.getvalue())
        (self.root / "a.txt").write_bytes(b"ok\r\n")
        with captured() as out:
            self.assertEqual(cpm.main(["check", str(m), str(self.root)]), 0)
        self.assertIn("stale=0", out.getvalue())


class MapCommandTests(GitTree):
    def setUp(self):
        super().setUp()
        self.old = self.root / "old.exe"
        self.new = self.root / "new.exe"

    def test_map_writes_rows_and_verify_agrees(self):
        self.old.write_bytes(make_pe(base_funcs((5, 12, 40))))
        self.new.write_bytes(make_pe(base_funcs((4, 11, 39))))
        self.commit({"src/a.cpp": b"Scripts::gml_Script_anon_12_gml_Object_Quest_obj_Create_0;\r\n"
                                  b"\"Lonely@anon@77@s_Thing@Funcs\"\r\n"})
        out_json = self.root / "out" / "map.json"
        with captured() as out:
            code = cpm.main(["map", "--old-exe", str(self.old), "--new-exe", str(self.new),
                             "--scan", str(self.root), "--out", str(out_json)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("rows=1 conflicts=0", out.getvalue())
        doc = json.loads(out_json.read_text(encoding="utf-8"))
        # Lonely keeps its name in both builds: referenced and fingerprinted, but no row.
        self.assertEqual({r["old"]: (r["new"], r["evidence"]) for r in doc["rows"]},
                         {S + "anon@12" + QP: (S + "anon@11" + QP, "fingerprint-unique")})
        self.assertEqual(doc["counts"]["self_mapped"], 1)
        self.assertEqual(doc["old_build"]["table_rows"], 7)
        self.assertEqual(doc["new_build"]["file_version"], "7.0.99.1")
        for r in doc["rows"]:
            self.assertEqual(set(r), set(cpm.ROW_KEYS))
        with captured() as out:
            code = cpm.main(["verify", str(out_json), "--old-exe", str(self.old), "--new-exe", str(self.new)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("conflicts=0", out.getvalue())
        self.assertIn("mismatches=0", out.getvalue())

    def test_verify_fails_on_a_tampered_row_or_another_exe(self):
        self.old.write_bytes(make_pe(base_funcs((5, 12, 40))))
        self.new.write_bytes(make_pe(base_funcs((4, 11, 39))))
        self.commit({"a.txt": b"anon@12@gml_Object_Quest_obj_Create_0\n"})
        out_json = self.root / "map.json"
        with captured():
            self.assertEqual(cpm.main(["map", "--old-exe", str(self.old), "--new-exe", str(self.new),
                                       "--scan", str(self.root), "--out", str(out_json)]), 0)
        doc = json.loads(out_json.read_text(encoding="utf-8"))
        doc["rows"][0]["new"] = S + "anon@39" + QP
        out_json.write_text(json.dumps(doc), encoding="utf-8")
        with captured() as out:
            self.assertEqual(cpm.main(["verify", str(out_json), "--old-exe", str(self.old),
                                       "--new-exe", str(self.new)]), 1)
        self.assertIn("mismatches=1", out.getvalue())

    def test_map_refuses_a_changed_group_size_and_writes_nothing(self):
        self.old.write_bytes(make_pe(base_funcs((5, 12, 40))))
        funcs = base_funcs((4, 11, 39))
        funcs.append((S + "anon@50" + QP, [("raw", b"\xc3")], True))
        self.new.write_bytes(make_pe(funcs))
        self.commit({"a.txt": b"anon@12@gml_Object_Quest_obj_Create_0\n"})
        out_json = self.root / "map.json"
        with captured() as out:
            code = cpm.main(["map", "--old-exe", str(self.old), "--new-exe", str(self.new),
                             "--scan", str(self.root), "--out", str(out_json)])
        self.assertEqual(code, 1)
        self.assertIn("SIZE CHANGE", out.getvalue())
        self.assertFalse(out_json.exists())

    def test_map_refuses_a_conflict_and_writes_nothing(self):
        self.old.write_bytes(make_pe(base_funcs((5, 12, 40))))
        funcs = base_funcs((4, 11, 39))
        # Swap the bodies of the first two siblings: rank order now points at the wrong one.
        (n0, b0, p0), (n1, b1, p1) = funcs[2], funcs[3]
        funcs[2], funcs[3] = (n0, b1, p1), (n1, b0, p0)
        self.new.write_bytes(make_pe(funcs))
        self.commit({"a.txt": b"anon@12@gml_Object_Quest_obj_Create_0\n"})
        out_json = self.root / "map.json"
        with captured() as out:
            code = cpm.main(["map", "--old-exe", str(self.old), "--new-exe", str(self.new),
                             "--scan", str(self.root), "--out", str(out_json)])
        self.assertEqual(code, 1)
        self.assertIn("CONFLICT", out.getvalue())
        self.assertFalse(out_json.exists())


def sdk_constants():
    text = SCRIPTS_HPP.read_text(encoding="utf-8")
    pairs = re.findall(r'inline constexpr std::string_view (\w+) = "([^"]*)";', text)
    return {i for i, _ in pairs}, {v for _, v in pairs}


@unittest.skipUnless(MAP_JSON.exists(), "map not written yet")
class CommittedMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = cpm.load_map(str(MAP_JSON))
        cls.identifiers, cls.values = sdk_constants()

    def test_header(self):
        self.assertEqual(self.doc["old_build"]["file_version"], "7.0.13.0")
        self.assertEqual(self.doc["new_build"]["file_version"], "7.0.14.0")
        self.assertEqual(self.doc["old_build"]["table_rows"], 20951)
        self.assertEqual(self.doc["new_build"]["table_rows"], 20980)
        self.assertEqual(self.doc["counts"]["rows"], len(self.doc["rows"]))
        self.assertEqual(self.doc["counts"]["conflicts"], 0)

    def test_every_new_name_is_an_sdk_constant(self):
        missing = [r["new"] for r in self.doc["rows"]
                   if r["new"] not in self.values or r["new_identifier"] not in self.identifiers]
        self.assertEqual(missing, [])

    def test_every_old_identifier_is_gone_from_the_sdk_unless_its_name_survives(self):
        wrong = [r["old"] for r in self.doc["rows"]
                 if (r["old_identifier"] in self.identifiers) != r["name_survives"]]
        self.assertEqual(wrong, [])

    def test_identifiers_are_the_sanitized_names(self):
        for r in self.doc["rows"]:
            self.assertEqual(r["old_identifier"], sanitize_identifier(r["old"]))
            self.assertEqual(r["new_identifier"], sanitize_identifier(r["new"]))

    def test_rows_carry_no_fingerprint_content(self):
        for r in self.doc["rows"]:
            self.assertEqual(set(r), set(cpm.ROW_KEYS))
            for v in r.values():
                self.assertIsInstance(v, (str, int, float, bool, type(None)))


@unittest.skipUnless(OLD_EXE.exists() and NEW_EXE.exists(), "both game executables are needed")
class ExeTests(unittest.TestCase):
    def test_the_two_tables_and_the_ghidra_positive_controls(self):
        old = cpm.ExeBuild(OLD_EXE)
        self.assertEqual((len(old.rows), old.file_version), (20951, "7.0.13.0"))
        self.assertEqual(old.rva[S + "anon@1468@gml_Object_Quest_Object_Parent_obj_Create_0"], 0x98657A0)
        self.assertEqual(old.rva[S + "GenerateItemHash@anon@4791@s_ItemInstanceStruct@InventoryV2Funcs"], 0x3E5E210)
        self.assertEqual(len(old.name_set), len(old.rows))
        new = cpm.ExeBuild(NEW_EXE)
        self.assertEqual((len(new.rows), new.file_version), (20980, "7.0.14.0"))
        self.assertEqual(len(new.name_set), len(new.rows))


if __name__ == "__main__":
    unittest.main()
