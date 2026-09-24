"""tools/stash_tab_counts.py: the closed-stash count cross-check for ForgePact #14.

The tool decodes `hs2saves\\stash.hss` with hero-siege-item-editor's own codec
and sums the shared stash's two special tabs (Socketable = `socket_tab*`,
Materials = `material_tab*`) per (item class, base id). ForgePact's research
build compares its in-game `craftprobe node` sums against it, so a wrong sum
here would pass a wrong reader.

Every case runs on a fixture document encoded with the editor's own encoder
into a temp directory; nothing here can reach the real saves. The baseline is
the negative control - an ordinary `stash_tab_1` stack of the same class and
base must not be counted - and the target is the per-(class, b) sum, with a
missing `o` counting as one stack. The last two cases pin that the tool never
writes: a corrupt file exits non-zero and is left byte-identical, and every
open of the save is read-only, checked by a recorder that is first shown to
catch a write-mode open.
"""
import builtins
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "hero-siege-item-editor"
sys.path.insert(0, str(ROOT))

EDITOR_PRESENT = (EDITOR / "hs_item_editor_gui.py").is_file() and (EDITOR / "hss_recovery.py").is_file()

if EDITOR_PRESENT:
    from tools import stash_tab_counts  # noqa: E402

FIXTURE = {
    # An ordinary grid tab: the same class and base as the socket stacks, never counted.
    "stash_tab_1": {"0-0-111111-15": {"data": {"b": 2, "o": 50}, "pos": [0, 0]}},
    # The Socketable tab: two stacks of one (class 15, b 2) - 200 + 14.
    "socket_tab": {
        "0-0-222222-15": {"data": {"b": 2, "o": 200}, "pos": [0, 0]},
        "0-0-333333-15": {"data": {"b": 2, "o": 14}, "pos": [1, 0]},
    },
    # The Materials tab: one entry without `o` - a single item.
    "material_tab": {"0-0-444444-14": {"data": {"b": 7}, "pos": [0, 0]}},
    "unique_items": {"0-0-555555-3": {"data": {"b": 9, "c": 1}, "pos": [0, 0]}},
    "stash_tab_data": {"NS": [{"tab": -2.0, "name": "Socketable"}, {"tab": -4.0, "name": "Materials"}]},
}


@unittest.skipUnless(EDITOR_PRESENT, "hero-siege-item-editor is not initialized in this checkout "
                                     "(py -3 .claude/skills/workorder/ensure_submodule.py hero-siege-item-editor)")
class StashTabCountsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.stash = self.dir / "stash.hss"
        editor = stash_tab_counts.load_editor()
        self.stash.write_text(editor.encode_hss(json.dumps(FIXTURE)), encoding="ascii")

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = stash_tab_counts.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def counts(self):
        code, out, err = self.run_tool("--path", str(self.stash), "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def stack(self, report, tab, cls, base):
        for row in report["tabs"][tab]["stacks"]:
            if row["class"] == cls and row["b"] == base:
                return row
        self.fail(f"{tab} has no (class {cls}, b {base}) row: {report['tabs'][tab]}")

    # ---- baseline: what must never be counted -----------------------------

    def test_baseline_ordinary_tab_items_are_not_counted(self):
        report = self.counts()
        self.assertEqual(sorted(report["tabs"]), ["material_tab", "socket_tab"])
        # The stash_tab_1 stack of the same (15, 2) would make this 264.
        self.assertEqual(self.stack(report, "socket_tab", 15, 2)["stack"], 214)
        # Negative control on the fixture itself: the ordinary tab really does
        # hold a (15, 2) stack, so the 214 above is the filter working.
        self.assertIn("0-0-111111-15", FIXTURE["stash_tab_1"])

    # ---- target: the special tabs, summed per (class, b) ------------------

    def test_target_special_tab_stacks_are_summed_per_class_and_base(self):
        report = self.counts()
        socket = report["tabs"]["socket_tab"]
        self.assertEqual(socket["entries"], 2)
        row = self.stack(report, "socket_tab", 15, 2)
        self.assertEqual((row["stack"], row["entries"]), (214, 2))
        code, text, _ = self.run_tool("--path", str(self.stash))
        self.assertEqual(code, 0)
        lines = text.splitlines()
        self.assertTrue(any(l.startswith("socket_tab:") for l in lines), text)
        self.assertTrue(any(l.startswith("material_tab:") for l in lines), text)
        self.assertIn("class=15 b=2 stack=214 entries=2", text)

    def test_target_missing_o_counts_as_one(self):
        report = self.counts()
        row = self.stack(report, "material_tab", 14, 7)
        self.assertEqual((row["stack"], row["entries"]), (1, 1))

    # ---- it never writes ---------------------------------------------------

    def test_corrupt_document_exits_nonzero_and_writes_nothing(self):
        self.stash.write_bytes(b"this is not an hss document")
        before = (self.stash.read_bytes(), sorted(p.name for p in self.dir.iterdir()))
        code, out, err = self.run_tool("--path", str(self.stash))
        self.assertNotEqual(code, 0)
        message = (out + err).strip().splitlines()
        self.assertEqual(len(message), 1, out + err)
        self.assertIn("stash.hss", message[0])
        self.assertEqual((self.stash.read_bytes(), sorted(p.name for p in self.dir.iterdir())), before)
        # A missing file is the same one-line refusal.
        code, out, err = self.run_tool("--path", str(self.dir / "absent.hss"))
        self.assertNotEqual(code, 0)
        self.assertEqual(len((out + err).strip().splitlines()), 1, out + err)
        self.assertFalse((self.dir / "absent.hss").exists())

    def test_tool_never_opens_the_save_for_writing(self):
        modes = []
        real_open, real_io_open = builtins.open, io.open

        def recording(opener):
            def wrapper(file, mode="r", *args, **kwargs):
                modes.append((str(file), mode))
                return opener(file, mode, *args, **kwargs)
            return wrapper

        def write_like(mode):
            return any(flag in mode for flag in "wax+")

        # Positive control: the recorder catches a write-mode open through the
        # same patch, so a clean result below is the tool, not a blind recorder.
        probe = self.dir / "probe.txt"
        with patch("builtins.open", recording(real_open)), patch("io.open", recording(real_io_open)):
            with open(probe, "w") as handle:
                handle.write("x")
        self.assertTrue(any(write_like(m) for f, m in modes if f == str(probe)), modes)

        modes.clear()
        before = (self.stash.read_bytes(), os.stat(self.stash).st_mtime_ns)
        with patch("builtins.open", recording(real_open)), patch("io.open", recording(real_io_open)), \
                patch.object(Path, "write_text", side_effect=AssertionError("write_text")), \
                patch.object(Path, "write_bytes", side_effect=AssertionError("write_bytes")):
            code, _, err = self.run_tool("--path", str(self.stash), "--json")
        self.assertEqual(code, 0, err)
        opened = [m for f, m in modes if Path(f).name == "stash.hss"]
        self.assertTrue(opened, "the recorder saw no open of the save - it did not watch the read")
        self.assertFalse([m for m in opened if write_like(m)], opened)
        self.assertEqual((self.stash.read_bytes(), os.stat(self.stash).st_mtime_ns), before)


if __name__ == "__main__":
    unittest.main()
