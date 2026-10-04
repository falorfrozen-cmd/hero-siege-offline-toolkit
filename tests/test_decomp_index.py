"""tools/decomp_index.py: the local index of decompiled scripts, and slot names.

The index answers "has this script already been decompiled for this game build,
and where is the file?" before anyone opens Ghidra. Every case here runs on
temp-directory fixtures: synthetic `.c` files carrying only our own header line
and a sentinel body, and a minimal PE32+ executable the test builds itself, with
an image base far below the game's. Nothing here reads the real decompile store,
the real index or the game executable.

The baseline is the empty store: `has` on a missing or empty index exits 1. The
targets are recording (`scan`), looking up by name, variant and build (`has`),
refusing to write inside a git tree, and the variable-slot technique: the
pointer 8 bytes before a global's slot names it (`slot-name`, `find-name`,
`annotate`). Each target keeps a negative control beside it: an unknown name,
another build, an unresolvable slot, a string that only ends with the name.

Any decompiler-shaped token a fixture needs is assembled at runtime, so this
file carries no sample of decompiler output.
"""
import contextlib
import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import decomp_index  # noqa: E402

BUILD_A = "a" * 64
BUILD_B = "b" * 64

IMAGE_BASE = 0x400000
SECTION_VA = 0x1000
SECTION_RAW = 0x200
SECTION_SIZE = 0x1000


def header(label, address, size=1):
    return "// %s @ %x size=%d\n" % (label, address, size)


def build_pe(path):
    """A minimal PE32+ with one data section holding a variable-slot table.

    Layout inside the section (offsets from its start):
      0x010  "projEffect\\0"              a real string start (preceded by NUL)
      0x020  "maxScale\\0"
      0x030  "notprojEffect\\0"           ends with the name, not a string start
      0x050  "\\x01\\x02\\0"              not an identifier
      0x100  ptr -> 0x010, slot           slot(projEffect) = VA 0x108
      0x110  ptr -> 0x020, slot           slot(maxScale)   = VA 0x118
      0x120  ptr -> 0x033, slot           a pointer to the decoy's inner text
      0x130  ptr -> outside every section, slot at VA 0x138
      0x140  ptr -> 0x050, slot at VA 0x148
    Returns the slot addresses by role.
    """
    def va(off):
        return IMAGE_BASE + SECTION_VA + off

    section = bytearray(SECTION_SIZE)
    section[0x10:0x10 + 11] = b"projEffect\0"
    section[0x20:0x20 + 9] = b"maxScale\0"
    section[0x30:0x30 + 14] = b"notprojEffect\0"
    section[0x50:0x53] = b"\x01\x02\0"
    struct.pack_into("<Q", section, 0x100, va(0x10))
    struct.pack_into("<Q", section, 0x110, va(0x20))
    struct.pack_into("<Q", section, 0x120, va(0x33))
    struct.pack_into("<Q", section, 0x130, 0x999999)
    struct.pack_into("<Q", section, 0x140, va(0x50))

    pe_off = 0x40
    opt_size = 0xF0
    dos = bytearray(pe_off)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, pe_off)
    coff = b"PE\0\0" + struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, opt_size, 0x22)
    opt = bytearray(opt_size)
    struct.pack_into("<H", opt, 0, 0x20B)
    struct.pack_into("<Q", opt, 24, IMAGE_BASE)
    sect = b".data\0\0\0" + struct.pack("<IIIIIIHHI", SECTION_SIZE, SECTION_VA, SECTION_SIZE,
                                         SECTION_RAW, 0, 0, 0, 0, 0xC0000040)
    head = bytes(dos) + coff + bytes(opt) + sect
    image = head + b"\0" * (SECTION_RAW - len(head)) + bytes(section)
    Path(path).write_bytes(image)
    return {
        "projEffect": va(0x108),
        "maxScale": va(0x118),
        "outside": va(0x138),
        "not_identifier": va(0x148),
        "nowhere": 0x123456,
    }


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = decomp_index.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


class _TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.store = self.tmp / "store"
        self.store.mkdir()
        self.index = self.tmp / "idx" / "decomp-index.jsonl"
        # Neither the real index nor the real executable may be reached by default.
        env = {"HS_DECOMP_INDEX": str(self.index), "HS_DECOMP_EXE": str(self.tmp / "no-such.exe")}
        self._env = patch.dict(os.environ, env)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def write_c(self, rel, label, address, body="int x;\n"):
        path = self.store / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        text = (header(label, address) if label is not None else "") + body
        path.write_text(text, encoding="utf-8")
        return path

    def records(self):
        lines = self.index.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]


class IndexTests(_TempCase):
    def test_scan_then_has_finds_a_script_for_its_build(self):
        self.write_c("LoadThing.c", "LoadThing", 0x401000)
        self.write_c("sub/Other.c", "Other", 0x402000)
        code, out, _ = run("scan", self.store, "--build", BUILD_A)
        self.assertEqual(code, 0, out)
        self.assertIn("added=2", out)

        code, out, _ = run("has", "LoadThing", "--build", BUILD_A)
        self.assertEqual(code, 0, out)
        self.assertIn("LoadThing", out)
        self.assertIn(str(self.store / "LoadThing.c"), out)
        self.assertNotIn("Other", out)

        # The prefixed script name normalises to the bare label.
        code, out, _ = run("has", "gml_Script_LoadThing", "--build", BUILD_A)
        self.assertEqual(code, 0, out)
        # An address query matches the header's address.
        code, out, _ = run("has", "0x402000", "--build", BUILD_A)
        self.assertEqual(code, 0, out)
        self.assertIn("Other", out)
        # A substring needs --contains.
        self.assertEqual(run("has", "Thing", "--build", BUILD_A)[0], 1)
        self.assertEqual(run("has", "Thing", "--contains", "--build", BUILD_A)[0], 0)

    def test_has_reports_another_build_and_exits_1(self):
        self.write_c("LoadThing.c", "LoadThing", 0x401000)
        self.assertEqual(run("scan", self.store, "--build", BUILD_A)[0], 0)
        code, out, _ = run("has", "LoadThing", "--build", BUILD_B)
        self.assertEqual(code, 1, out)
        self.assertIn("other build", out)
        self.assertIn("LoadThing", out)
        self.assertIn(BUILD_A[:12], out)

    def test_has_unknown_name_exits_1(self):
        # Baseline: no index at all, then an empty one.
        code, out, err = run("has", "LoadThing", "--build", BUILD_A)
        self.assertEqual(code, 1, out + err)
        self.assertIn("scan", out + err)
        self.index.parent.mkdir(parents=True)
        self.index.write_text("", encoding="utf-8")
        self.assertEqual(run("has", "LoadThing", "--build", BUILD_A)[0], 1)

        # A populated index without the name.
        self.write_c("LoadThing.c", "LoadThing", 0x401000)
        self.assertEqual(run("scan", self.store, "--build", BUILD_A)[0], 0)
        code, out, _ = run("has", "NoSuchScript", "--build", BUILD_A)
        self.assertEqual(code, 1, out)
        self.assertNotIn("LoadThing", out)

    def test_variant_suffixes_index_under_one_name(self):
        for rel in ("Foo.c", "Foo.s.c", "Foo.s.n.c", "Foo.s.r.c", "Foo.a.c", "Foo.n.c"):
            self.write_c(rel, "Foo", 0x401000)
        # Without a header the file name names it, suffixes stripped the same way.
        self.write_c("Bar.s.c", None, 0)
        self.assertEqual(run("scan", self.store, "--build", BUILD_A)[0], 0)
        recs = self.records()
        foo = sorted(r["variant"] for r in recs if r["name"] == "Foo")
        self.assertEqual(foo, ["", "a", "n", "s", "s.n", "s.r"])
        bar = [r for r in recs if r["name"] == "Bar"]
        self.assertEqual([r["variant"] for r in bar], ["s"])
        code, out, _ = run("has", "Foo", "--build", BUILD_A)
        self.assertEqual(code, 0)
        self.assertEqual(len([l for l in out.splitlines() if "Foo" in l]), 6)

    def test_header_label_wins_over_file_name(self):
        self.write_c("renamed_copy.s.c", "RealName", 0x401000)
        # A label with spaces is not a name: the file name gives it instead.
        self.write_c("around_fn.c", "function containing 401010", 0x401000)
        self.assertEqual(run("scan", self.store, "--build", BUILD_A)[0], 0)
        by_path = {Path(r["path"]).name: r for r in self.records()}
        self.assertEqual(by_path["renamed_copy.s.c"]["name"], "RealName")
        self.assertEqual(by_path["renamed_copy.s.c"]["variant"], "s")
        self.assertEqual(by_path["renamed_copy.s.c"]["address"], "0x401000")
        self.assertEqual(by_path["around_fn.c"]["name"], "around_fn")
        self.assertEqual(run("has", "RealName", "--build", BUILD_A)[0], 0)
        self.assertEqual(run("has", "renamed_copy", "--build", BUILD_A)[0], 1)

    def test_index_holds_no_body_text(self):
        sentinel = "SENTINEL_BODY_TEXT_7f3a"
        self.write_c("LoadThing.c", "LoadThing", 0x401000, body="int %s = 1;\n" % sentinel)
        self.assertEqual(run("scan", self.store, "--build", BUILD_A, "--note", "fixture")[0], 0)
        text = self.index.read_text(encoding="utf-8")
        self.assertNotIn(sentinel, text)
        rec = self.records()[0]
        self.assertEqual(set(rec), {"name", "variant", "address", "build", "path", "bytes",
                                    "mtime", "recorded", "note"})
        self.assertEqual(rec["note"], "fixture")
        self.assertEqual(rec["build"], BUILD_A)
        # Positive control: the sentinel really is in the file that was scanned.
        self.assertIn(sentinel, (self.store / "LoadThing.c").read_text(encoding="utf-8"))

    def test_refuses_index_inside_a_git_tree(self):
        self.write_c("LoadThing.c", "LoadThing", 0x401000)
        for kind in ("dir", "file"):
            repo = self.tmp / ("repo-" + kind)
            repo.mkdir()
            if kind == "dir":
                (repo / ".git").mkdir()
            else:
                (repo / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
            inside = repo / "sub" / "decomp-index.jsonl"
            code, out, err = run("scan", self.store, "--build", BUILD_A, "--index", inside)
            self.assertEqual(code, 2, out + err)
            self.assertIn("Legal", out + err)
            self.assertFalse(inside.exists())
            self.assertFalse(inside.parent.exists())
        # Control: the same scan outside a git tree writes the index.
        self.assertEqual(run("scan", self.store, "--build", BUILD_A)[0], 0)
        self.assertTrue(self.index.is_file())

    def test_scan_is_idempotent(self):
        path = self.write_c("LoadThing.c", "LoadThing", 0x401000)
        self.write_c("Other.c", "Other", 0x402000)
        self.assertEqual(run("scan", self.store, "--build", BUILD_A)[0], 0)
        first = self.records()
        code, out, _ = run("scan", self.store, "--build", BUILD_A)
        self.assertEqual(code, 0)
        self.assertIn("added=0", out)
        self.assertIn("updated=0", out)
        self.assertIn("unchanged=2", out)
        self.assertEqual(self.records(), first)

        st = path.stat()
        os.utime(path, (st.st_atime, st.st_mtime - 86400))
        code, out, _ = run("scan", self.store, "--build", BUILD_A)
        self.assertIn("added=0", out)
        self.assertIn("updated=1", out)
        self.assertEqual(len(self.records()), 2)

        # The same file under another build is its own record.
        code, out, _ = run("scan", self.store, "--build", BUILD_B)
        self.assertIn("added=2", out)
        self.assertEqual(len(self.records()), 4)

    def test_build_hash_is_the_exe_sha256(self):
        exe = self.tmp / "game.exe"
        exe.write_bytes(os.urandom(3 * 1024 * 1024 + 17))
        want = hashlib.sha256(exe.read_bytes()).hexdigest()
        code, out, _ = run("build-hash", "--exe", exe)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), want)
        # The environment override is the same answer, and scan records it.
        with patch.dict(os.environ, {"HS_DECOMP_EXE": str(exe)}):
            self.assertEqual(run("build-hash")[1].strip(), want)
            self.write_c("LoadThing.c", "LoadThing", 0x401000)
            self.assertEqual(run("scan", self.store)[0], 0)
            self.assertEqual(self.records()[0]["build"], want)
            self.assertEqual(run("has", "LoadThing")[0], 0)
        # No build at all is a usage error naming both options.
        code, out, err = run("build-hash")
        self.assertEqual(code, 2)
        code, out, err = run("scan", self.store)
        self.assertEqual(code, 2)
        self.assertIn("--build", out + err)
        self.assertIn("--exe", out + err)


class SlotNameTests(_TempCase):
    def setUp(self):
        super().setUp()
        self.exe = self.tmp / "synthetic.exe"
        self.slots = build_pe(self.exe)

    def test_slot_name_reads_the_pointer_8_bytes_before(self):
        code, out, _ = run("slot-name", "--exe", self.exe,
                           hex(self.slots["projEffect"]), hex(self.slots["maxScale"]))
        self.assertEqual(code, 0, out)
        self.assertEqual(out.splitlines(), [
            "%s projEffect" % hex(self.slots["projEffect"]),
            "%s maxScale" % hex(self.slots["maxScale"]),
        ])
        # The environment override reaches the same file.
        with patch.dict(os.environ, {"HS_DECOMP_EXE": str(self.exe)}):
            self.assertIn("projEffect", run("slot-name", hex(self.slots["projEffect"]))[1])

    def test_slot_name_unresolved_is_not_guessed(self):
        for role in ("outside", "not_identifier", "nowhere"):
            code, out, _ = run("slot-name", "--exe", self.exe, hex(self.slots[role]))
            self.assertEqual(code, 1, role)
            self.assertEqual(out.strip(), "%s ?" % hex(self.slots[role]), role)
        # Not a PE32+ file is refused, not read.
        junk = self.tmp / "junk.bin"
        junk.write_bytes(b"\0" * 512)
        self.assertEqual(run("slot-name", "--exe", junk, "0x401108")[0], 2)

    def test_find_name_lists_the_slot_after_the_entry(self):
        code, out, _ = run("find-name", "--exe", self.exe, "projEffect", "maxScale")
        self.assertEqual(code, 0, out)
        lines = out.splitlines()
        self.assertIn("projEffect %s" % hex(self.slots["projEffect"]), lines)
        self.assertIn("maxScale %s" % hex(self.slots["maxScale"]), lines)
        # The pointer into "notprojEffect" is not a pointer to the name.
        self.assertEqual(len([l for l in lines if l.startswith("projEffect ")]), 1)
        code, out, _ = run("find-name", "--exe", self.exe, "NoSuchGlobal")
        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "NoSuchGlobal ?")

    def test_annotate_renames_only_resolvable_globals(self):
        data = "DAT" + "_"
        resolvable = data + "%08x" % self.slots["projEffect"]
        deref = "_" + data + "%08x" % self.slots["maxScale"]
        wide = "uRam" + "%016x" % self.slots["projEffect"]
        unresolved = data + "%08x" % self.slots["outside"]
        text = ("a = %s;\nb = *%s;\nc = %s;\nd = %s;\ne = local_10;\n"
                % (resolvable, deref, wide, unresolved))
        src = self.tmp / "in.c"
        dst = self.tmp / "out" / "annotated.c"
        src.write_text(text, encoding="latin-1")
        code, out, err = run("annotate", "--exe", self.exe, src, dst)
        self.assertEqual(code, 0, out + err)
        got = dst.read_text(encoding="latin-1")
        self.assertEqual(got, "a = V_projEffect;\nb = *V_maxScale;\nc = V_projEffect;\n"
                              "d = %s;\ne = local_10;\n" % unresolved)

    def test_annotate_refuses_output_inside_a_git_tree(self):
        src = self.tmp / "in.c"
        src.write_text("a = %s;\n" % ("DAT" + "_" + "%08x" % self.slots["projEffect"]),
                       encoding="latin-1")
        repo = self.tmp / "repo"
        (repo / ".git").mkdir(parents=True)
        dst = repo / "docs" / "annotated.c"
        code, out, err = run("annotate", "--exe", self.exe, src, dst)
        self.assertEqual(code, 2, out + err)
        self.assertIn("Legal", out + err)
        self.assertFalse(dst.exists())
        # Control: the same call outside a git tree writes.
        ok = self.tmp / "annotated.c"
        self.assertEqual(run("annotate", "--exe", self.exe, src, ok)[0], 0)
        self.assertTrue(ok.is_file())


if __name__ == "__main__":
    unittest.main()
