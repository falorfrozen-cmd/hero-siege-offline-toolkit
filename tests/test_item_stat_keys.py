"""Pin ``hs-game-sdk/curated/item_stat_keys.json``.

The file holds two numberings the Mark 1 set (ForgePact #166) uses side by
side: item stat keys (what an item's stats map holds and the Custom Forge
writes, measured in Item Truth's captures against hero-siege-item-editor's
semantics file) and the stat dispatcher's ids (gml_Script_ReturnSpecificStat's
argument, a static reading of its case map), plus how the tooltip draws a set
bonus line. ForgePact's Mark1Rolls.hpp is checked against it by
ForgePact/tests/test_mark1_rolls_behavior.py; this test stops the file itself
drifting: every key with its name and kind, every dispatcher id with a getter
the SDK knows, the set lines with format and style, and each part's status.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = ROOT / "hs-game-sdk"
SDK_PY_PATH = SDK_ROOT / "python"
if str(SDK_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PY_PATH))

from hs_game_sdk.scripts import SCRIPT_NAME_TO_INDEX  # noqa: E402

CURATED_FILE = SDK_ROOT / "curated" / "item_stat_keys.json"
SEMANTICS_NAME = "hs_stat_semantics_s10.json"

# Item stat key -> (name, kind), as the semantics file names them and the game drew them.
KEYS = {
    "154": ("Defense", "flat"),
    "29": ("Enhanced Defense", "percent"),
    "48": ("to Vitality", "flat"),
    "173": ("to All Resistances", "percent"),
    "201": ("to All Skills", "flat"),
    "170": ("Faster Hit Recovery", "percent"),
    "52": ("to Life", "flat"),
    "59": ("Life After each Kill", "flat"),
    "51": ("to All Attributes", "flat"),
    "55": ("Replenish Life", "percent"),
    "159": ("Physical Damage Taken Reduced by", "percent"),
    "20": ("Sockets", "flat"),
    "25": ("Increased Movement Speed", "percent"),
    "294": ("Skill Movement Diminish decreased by", "percent"),
}

# Dispatcher id -> getter (the case map, static reading).
DISPATCHER_IDS = {
    "2": "StatAllSkills",
    "21": "StatArmor",
    "22": "StatVitality",
    "36": "StatMaxLife",
    "37": "StatMaxMana",
    "38": "StatLifeReplenish",
    "42": "StatManaReplenish",
    "45": "StatLifePerKill",
    "46": "StatManaPerKill",
    "64": "StatMovementSpeed",
    "92": "StatDefense",
    "97": "StatPhysicalDamageReduction",
    "103": "StatSpellHaste",
    "106": "StatFasterCastRate",
    "147": "ManaPerHit",
    "161": "StatAllResistances",
    "162": "StatFireResist",
    "163": "StatColdResist",
    "164": "StatPoisonResist",
    "165": "StatLightningResist",
    "167": "StatArcaneResist",
    "340": "StatManaCost",
}

# Set bonus lines as the game draws them: label -> (format, style).
SET_LINES = {
    "Defense": (6, 8),
    "to All Resistances": (5, 8),
    "Replenish Life": (5, 9),
    "to All Skills": (6, 8),
    "to Life": (6, 8),
    "Physical Damage Taken Reduced by": (5, 9),
    "Movement Speed": (5, 8),
}


def _semantics_file():
    """The item editor's semantics file: this checkout's submodule, or the main
    checkout's when this is a worktree under ``.claude/worktrees/``."""
    candidates = [ROOT / "hero-siege-item-editor" / SEMANTICS_NAME]
    if ROOT.parent.name == "worktrees" and ROOT.parent.parent.name == ".claude":
        candidates.append(ROOT.parents[2] / "hero-siege-item-editor" / SEMANTICS_NAME)
    for path in candidates:
        if path.is_file():
            return path
    return None


class ItemStatKeysTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(CURATED_FILE.read_text(encoding="utf-8"))

    def test_top_level_shape(self):
        for field in ("status", "source", "keys", "dispatcher_ids", "set_lines", "numbering_note"):
            self.assertIn(field, self.data)
        self.assertEqual(self.data["status"], "measured")
        source = self.data["source"]
        self.assertIn("hs_stat_semantics_s10.json", source["semantics"])
        self.assertIn("schemaVersion 1", source["semantics"])
        self.assertIn("2026-09-02", source["semantics"])
        self.assertIn("pe-6aaa6779-0cad4fc8", source["item_truth"])

    def test_statid_is_named_as_a_different_numbering(self):
        note = self.data["numbering_note"]
        self.assertIn("hs_game_sdk.stats.StatId", note)
        self.assertIn("#546", note)

    def test_every_key_with_its_name_and_kind(self):
        keys = self.data["keys"]
        self.assertEqual(set(keys), set(KEYS))
        for key, (name, kind) in KEYS.items():
            with self.subTest(key=key):
                self.assertEqual(keys[key]["name"], name)
                self.assertEqual(keys[key]["kind"], kind)
                self.assertIn(keys[key]["kind"], ("percent", "flat"))
                self.assertEqual(keys[key]["status"], "measured")

    def test_drawn_keys_carry_their_own_name_as_label(self):
        for key, entry in self.data["keys"].items():
            drawn = entry.get("drawn")
            if isinstance(drawn, dict):
                with self.subTest(key=key):
                    self.assertEqual(drawn["label"], entry["name"])
                    # An item's own lines: format 2 (percent) or 3 (flat), matching the kind.
                    self.assertEqual(drawn["format"], 2 if entry["kind"] == "percent" else 3)
                    self.assertIn(drawn["style"], (8, 9))

    def test_dispatcher_ids_with_getters_the_sdk_knows(self):
        ids = self.data["dispatcher_ids"]
        self.assertEqual(set(ids), set(DISPATCHER_IDS))
        for ident, getter in DISPATCHER_IDS.items():
            with self.subTest(id=ident):
                self.assertEqual(ids[ident]["getter"], getter)
                self.assertEqual(ids[ident]["status"], "static_reading")
                self.assertIn("gml_Script_" + getter, SCRIPT_NAME_TO_INDEX)
        self.assertIn("gml_Script_ReturnSpecificStat", SCRIPT_NAME_TO_INDEX)

    def test_set_lines_with_format_and_style(self):
        lines = self.data["set_lines"]
        self.assertEqual([l["label"] for l in lines], list(SET_LINES))
        formats = self.data["set_line"]["formats"]
        styles = self.data["set_line"]["styles"]
        for line in lines:
            with self.subTest(label=line["label"]):
                self.assertEqual((line["format"], line["style"]), SET_LINES[line["label"]])
                self.assertIn(str(line["format"]), formats)
                self.assertIn(str(line["style"]), styles)
                self.assertEqual(line["status"], "measured")
        self.assertEqual(self.data["set_line"]["script"], "gml_Script_DrawInventoryStatsNew")
        self.assertIn(self.data["set_line"]["script"], SCRIPT_NAME_TO_INDEX)
        self.assertEqual(self.data["set_line"]["status"], "measured")

    def test_keys_agree_with_the_semantics_file_when_present(self):
        path = _semantics_file()
        if path is None:
            self.skipTest(f"{SEMANTICS_NAME} not found in this checkout or the main one")
        semantics = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(semantics.get("schemaVersion"), 1)
        stats = semantics["stats"]
        for key, (name, kind) in KEYS.items():
            with self.subTest(key=key):
                self.assertEqual(stats[key]["name"], name)
                self.assertEqual(stats[key]["valueKind"], kind)


if __name__ == "__main__":
    unittest.main()
