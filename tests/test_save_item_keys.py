"""tools/save_item_keys.py: where each item key is saved, for ForgePact #68.

The tool decodes `.hss` files with hero-siege-item-editor's own codec and lists
every item key (`0-0-<n>-<class>`) under the container that holds it. ForgePact's
"Move all" sessions read it after the game has exited to show that a moved key
is saved under a stash container, under no bag container, and only once, so a
tool that missed a container would pass a duplicate or a lost item.

Every case runs on synthetic documents encoded with the editor's own encoder
into a temp directory; nothing here can reach the real saves. The three layouts
are the ones the saves use: the shared stash and the bag file are one JSON
object each, and a character file is `key="value"` lines whose `inventory`
value is base64 of a JSON object holding the personal stash. The baseline is
the negative control - a key that appears only as a string value, and object
keys that are not item keys, are never listed - and the target is every key
under its container, the personal stash included. The last two cases pin that
the tool never writes.
"""
import base64
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
    from tools import save_item_keys  # noqa: E402

STASH = {
    "stash_tab_1": {
        "0-0-111111-3": {"data": {"b": 5}, "pos": [0, 0]},
        "0-0-222222-10": {"data": {"b": 6}, "pos": [1, 0]},
    },
    "material_tab": {"0-0-333333-14": {"data": {"b": 71, "o": 15}, "pos": [0, 0]}},
    "unique_items": {},
    # Not an item container: a reference held as a string value is never listed.
    "stash_tab_data": {"NS": [{"tab": 1.0, "name": "one", "last": "0-0-999999-7"}]},
    "stash_reset": 0,
}
BAG = {
    "inventory_tab_0": {"0-0-444444-7": {"data": {"b": 29}, "pos": [4, 0]}},
    "inventory_material_tab": {"0-0-555555-14": {"data": {"b": 72, "o": 934}, "pos": [0, 0]}},
    "inventory_tab_1": {},
}
CHARACTER_INVENTORY = {
    "personal_stash": {"0-0-666666-3": {"data": {"b": 1}, "pos": [14, 14]}},
    "equipped_items": {"0-0-777777-7": {"data": {"b": 49, "g": 5}}},
    "potions": {},
}


def character_text(inventory: dict) -> str:
    encoded = base64.b64encode(json.dumps(inventory).encode("utf-8")).decode("ascii")
    return ('[0]\r\nlevel="100.000000"\r\nname="Sorak"\r\n'
            f'inventory="{encoded}"\r\nloot_filter_new="bm90IGpzb24="\r\n')


@unittest.skipUnless(EDITOR_PRESENT, "hero-siege-item-editor is not initialized in this checkout "
                                     "(py -3 .claude/skills/workorder/ensure_submodule.py hero-siege-item-editor)")
class SaveItemKeysTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        editor = save_item_keys.load_editor()
        self.stash = self.dir / "stash.hss"
        self.bag = self.dir / "inventory_order_13.hss"
        self.char = self.dir / "herosiege13.hss"
        self.stash.write_text(editor.encode_hss(json.dumps(STASH)), encoding="ascii")
        self.bag.write_text(editor.encode_hss(json.dumps(BAG)), encoding="ascii")
        self.char.write_text(editor.encode_hss(character_text(CHARACTER_INVENTORY)), encoding="ascii")

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = save_item_keys.main([str(a) for a in args])
        return code, out.getvalue(), err.getvalue()

    def keys(self, *paths):
        code, out, err = self.run_tool(*paths, "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)["files"]

    # ---- baseline: what must never be listed ------------------------------

    def test_baseline_string_values_and_plain_keys_are_not_item_keys(self):
        files = self.keys(self.stash)
        containers = files[str(self.stash)]
        listed = [k for keys in containers.values() for k in keys]
        # The reference in stash_tab_data is a value, not an entry.
        self.assertNotIn("0-0-999999-7", listed)
        # Negative control on the fixture itself: the string really is there.
        self.assertIn("0-0-999999-7", json.dumps(STASH))
        self.assertNotIn("stash_tab_data.NS.0", containers)
        # Object keys that are not item keys (containers, members) are never listed.
        self.assertFalse([k for k in listed if not k.startswith("0-0-")], listed)

    def test_baseline_character_fields_that_are_not_base64_json_are_skipped(self):
        containers = self.keys(self.char)[str(self.char)]
        self.assertFalse([c for c in containers if c.startswith(("level", "name", "loot_filter_new"))], containers)

    # ---- target: every key under the container that holds it -------------

    def test_target_stash_keys_are_grouped_by_tab(self):
        containers = self.keys(self.stash)[str(self.stash)]
        self.assertEqual(containers["stash_tab_1"], ["0-0-111111-3", "0-0-222222-10"])
        self.assertEqual(containers["material_tab"], ["0-0-333333-14"])
        self.assertEqual(sorted(containers), ["material_tab", "stash_tab_1"])

    def test_target_bag_file_lists_the_bag_tabs(self):
        containers = self.keys(self.bag)[str(self.bag)]
        self.assertEqual(containers["inventory_tab_0"], ["0-0-444444-7"])
        self.assertEqual(containers["inventory_material_tab"], ["0-0-555555-14"])

    def test_target_character_file_lists_the_personal_stash_and_equipped_items(self):
        containers = self.keys(self.char)[str(self.char)]
        self.assertEqual(containers["inventory.personal_stash"], ["0-0-666666-3"])
        self.assertEqual(containers["inventory.equipped_items"], ["0-0-777777-7"])

    def test_target_key_filter_names_every_place_a_key_is_saved(self):
        code, out, err = self.run_tool(self.stash, self.bag, self.char,
                                       "--key", "0-0-444444-7", "--key", "0-0-666666-3", "--key", "0-0-888888-6")
        self.assertEqual(code, 0, err)
        self.assertIn("key 0-0-444444-7: inventory_order_13.hss:inventory_tab_0", out)
        self.assertIn("key 0-0-666666-3: herosiege13.hss:inventory.personal_stash", out)
        self.assertIn("key 0-0-888888-6: not in any file read", out)
        # A key saved twice is named twice, which is what a duplicate check reads.
        dup = dict(BAG, inventory_tab_1={"0-0-111111-3": {"data": {"b": 5}, "pos": [0, 0]}})
        self.bag.write_text(save_item_keys.load_editor().encode_hss(json.dumps(dup)), encoding="ascii")
        code, out, err = self.run_tool(self.stash, self.bag, "--key", "0-0-111111-3", "--json")
        self.assertEqual(code, 0, err)
        places = json.loads(out)["keys"]["0-0-111111-3"]
        self.assertEqual(sorted(p["container"] for p in places), ["inventory_tab_1", "stash_tab_1"])

    def test_target_text_output_names_each_container_and_its_count(self):
        code, out, err = self.run_tool(self.stash)
        self.assertEqual(code, 0, err)
        self.assertIn("stash_tab_1: keys=2", out)
        self.assertIn("  0-0-222222-10", out)

    # ---- it never writes ---------------------------------------------------

    def test_corrupt_or_missing_file_exits_nonzero_and_writes_nothing(self):
        self.stash.write_bytes(b"this is not an hss document")
        before = (self.stash.read_bytes(), sorted(p.name for p in self.dir.iterdir()))
        code, out, err = self.run_tool(self.stash)
        self.assertNotEqual(code, 0)
        message = (out + err).strip().splitlines()
        self.assertEqual(len(message), 1, out + err)
        self.assertIn("stash.hss", message[0])
        self.assertEqual((self.stash.read_bytes(), sorted(p.name for p in self.dir.iterdir())), before)
        code, out, err = self.run_tool(self.dir / "absent.hss")
        self.assertNotEqual(code, 0)
        self.assertEqual(len((out + err).strip().splitlines()), 1, out + err)
        self.assertFalse((self.dir / "absent.hss").exists())
        code, out, err = self.run_tool(self.bag, "--key", "not-a-key")
        self.assertNotEqual(code, 0)
        self.assertEqual(len((out + err).strip().splitlines()), 1, out + err)

    def test_tool_never_opens_a_save_for_writing(self):
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
        files = (self.stash, self.bag, self.char)
        before = [(p.read_bytes(), os.stat(p).st_mtime_ns) for p in files]
        with patch("builtins.open", recording(real_open)), patch("io.open", recording(real_io_open)), \
                patch.object(Path, "write_text", side_effect=AssertionError("write_text")), \
                patch.object(Path, "write_bytes", side_effect=AssertionError("write_bytes")):
            code, _, err = self.run_tool(*files, "--json")
        self.assertEqual(code, 0, err)
        opened = [m for f, m in modes if Path(f).suffix == ".hss"]
        self.assertTrue(opened, "the recorder saw no open of a save - it did not watch the read")
        self.assertFalse([m for m in opened if write_like(m)], opened)
        self.assertEqual([(p.read_bytes(), os.stat(p).st_mtime_ns) for p in files], before)


if __name__ == "__main__":
    unittest.main()
