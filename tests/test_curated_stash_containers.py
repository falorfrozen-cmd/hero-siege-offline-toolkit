"""Cross-checks for the hand-verified stash/crafting container names.

``hs-game-sdk/curated/stash_containers.json`` names the ``Controller_obj``
variables ForgePact issue #14 found live, by content search. They are not
present in Hero_Siege.exe (a static reading); the runtime fills the slots
the code reads them through from data.win at run time, and no extractor
currently produces them or ties them to Controller_obj (see
docs/RUNTIME_DATA_MODELS.md section '## 17. Stash Special Tabs & the Crafting
Route' and ForgePact/docs/crafting-materials-research.md). This test is what
stops the curated file, the SDK and the doc drifting apart.
"""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = ROOT / "hs-game-sdk"
SDK_PY_PATH = SDK_ROOT / "python"
if str(SDK_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PY_PATH))

from hs_game_sdk import GameObject, ItemType  # noqa: E402
from hs_game_sdk.scripts import SCRIPT_NAME_TO_INDEX  # noqa: E402

CURATED_FILE = SDK_ROOT / "curated" / "stash_containers.json"
RUNTIME_DOC = ROOT / "docs" / "RUNTIME_DATA_MODELS.md"

ITEM_CLASS_MEMBERS = {
    "materials": "MATERIAL",
    "socketable": "SOCKETABLE",
}


def _bare_script_name(script_name: str) -> str:
    prefix = "gml_Script_"
    if script_name and script_name.startswith(prefix):
        return script_name[len(prefix):]
    return script_name


def _runtime_doc_section_5(doc_text: str) -> str:
    heading = "\n## 17. Stash Special Tabs & the Crafting Route"
    start = doc_text.find(heading)
    if start == -1:
        return ""
    end = doc_text.find("\n## ", start + 1)
    return doc_text[start:end if end != -1 else None]


def validate(data: dict, doc_text: str) -> list:
    """Return a list of problem strings; an empty list means the file is consistent."""
    problems = []
    section = _runtime_doc_section_5(doc_text)

    def require(path, value):
        if value is None:
            problems.append(f"missing required key: {path}")
            return False
        return True

    controller = data.get("controller_object", {})
    name = controller.get("name")
    index = controller.get("index")
    if not require("controller_object.name", name) or not require("controller_object.index", index):
        pass
    elif name not in GameObject.__members__:
        problems.append(f"controller_object.name {name!r} is not a GameObject member")
    elif GameObject[name].value != index:
        problems.append(
            f"controller_object.index {index!r} does not match "
            f"GameObject[{name!r}].value ({GameObject[name].value!r})"
        )

    stash_map = data.get("stash_map", {})
    getter = stash_map.get("getter")
    if require("stash_map.getter", getter) and getter not in SCRIPT_NAME_TO_INDEX:
        problems.append(f"stash_map.getter {getter!r} is not in SCRIPT_NAME_TO_INDEX")
    variable = stash_map.get("variable")
    if require("stash_map.variable", variable) and variable not in section:
        problems.append(f"stash_map.variable {variable!r} is absent from RUNTIME_DATA_MODELS.md section 5")
    require("stash_map.owner", stash_map.get("owner"))

    special_tabs = data.get("special_tabs", {})
    for tab, item_type_name in ITEM_CLASS_MEMBERS.items():
        tab_data = special_tabs.get(tab, {})
        tab_variable = tab_data.get("variable")
        if require(f"special_tabs.{tab}.variable", tab_variable) and tab_variable not in section:
            problems.append(
                f"special_tabs.{tab}.variable {tab_variable!r} is absent from "
                "RUNTIME_DATA_MODELS.md section 5"
            )
        item_class = tab_data.get("item_class")
        if require(f"special_tabs.{tab}.item_class", item_class):
            expected = getattr(ItemType, item_type_name).value
            if item_class != expected:
                problems.append(
                    f"special_tabs.{tab}.item_class {item_class!r} does not match "
                    f"ItemType.{item_type_name} ({expected!r})"
                )

    fingerprint_member = data.get("cell", {}).get("fingerprint_member")
    if require("cell.fingerprint_member", fingerprint_member) and fingerprint_member not in section:
        problems.append(
            f"cell.fingerprint_member {fingerprint_member!r} is absent from "
            "RUNTIME_DATA_MODELS.md section 5"
        )

    save = data.get("save", {})
    save_script = save.get("script")
    if require("save.script", save_script):
        if save_script not in SCRIPT_NAME_TO_INDEX:
            problems.append(f"save.script {save_script!r} is not in SCRIPT_NAME_TO_INDEX")
        bare_script = _bare_script_name(save_script)
        if bare_script not in section:
            problems.append(
                f"save.script {save_script!r} (bare name {bare_script!r}) is absent from "
                "RUNTIME_DATA_MODELS.md section 5"
            )
    save_self_object = save.get("self_object")
    if require("save.self_object", save_self_object) and save_self_object not in GameObject.__members__:
        problems.append(f"save.self_object {save_self_object!r} is not a GameObject member")
    require("save.stash_kind", save.get("stash_kind"))

    crafting_cube = data.get("crafting_cube", {})
    cc_object = crafting_cube.get("object")
    cc_index = crafting_cube.get("index")
    if not require("crafting_cube.object", cc_object) or not require("crafting_cube.index", cc_index):
        pass
    elif cc_object not in GameObject.__members__:
        problems.append(f"crafting_cube.object {cc_object!r} is not a GameObject member")
    elif GameObject[cc_object].value != cc_index:
        problems.append(
            f"crafting_cube.index {cc_index!r} does not match "
            f"GameObject[{cc_object!r}].value ({GameObject[cc_object].value!r})"
        )
    cc_variable = crafting_cube.get("variable")
    if require("crafting_cube.variable", cc_variable) and cc_variable not in section:
        problems.append(
            f"crafting_cube.variable {cc_variable!r} is absent from "
            "RUNTIME_DATA_MODELS.md section 5"
        )
    require("crafting_cube.item_map_owner", crafting_cube.get("item_map_owner"))
    require("crafting_cube.note", crafting_cube.get("note"))

    for source in data.get("sources", []):
        source_file = source.get("file")
        section_heading = source.get("section")
        if not source_file or not section_heading:
            problems.append(f"sources entry missing file or section: {source!r}")
            continue
        source_path = ROOT / source_file
        if not source_path.exists():
            # A checkout without submodules has no ForgePact/ - skip, not a problem.
            continue
        source_text = source_path.read_text(encoding="utf-8")
        if section_heading not in source_text:
            problems.append(
                f"sources entry {source_file!r} lacks its heading {section_heading!r}"
            )

    return problems


class TestCuratedStashContainers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(CURATED_FILE.read_text(encoding="utf-8"))
        cls.doc_text = RUNTIME_DOC.read_text(encoding="utf-8")

    def test_curated_file_matches_the_sdk_and_the_doc(self):
        self.assertEqual(validate(self.data, self.doc_text), [])

    def test_validator_rejects_a_wrong_fixture(self):
        bad = copy.deepcopy(self.data)
        bad["controller_object"]["index"] = 985
        bad["stash_map"]["getter"] = "gml_Script_NoSuchScript"
        bad["stash_map"]["variable"] = "stashNoSuchVar"
        bad["save"]["script"] = "gml_Script_NoSuchSave"
        bad["crafting_cube"]["variable"] = "noSuchGrid"
        bad["crafting_cube"]["index"] = 3068

        problems = validate(bad, self.doc_text)

        self.assertTrue(any("985" in p for p in problems), problems)
        self.assertTrue(any("gml_Script_NoSuchScript" in p for p in problems), problems)
        self.assertTrue(any("stashNoSuchVar" in p for p in problems), problems)
        self.assertTrue(any("gml_Script_NoSuchSave" in p for p in problems), problems)
        self.assertTrue(any("noSuchGrid" in p for p in problems), problems)
        self.assertTrue(any("3068" in p for p in problems), problems)

    def test_validator_reports_a_missing_object_as_a_problem(self):
        missing = copy.deepcopy(self.data)
        del missing["save"]
        del missing["crafting_cube"]

        problems = validate(missing, self.doc_text)

        self.assertTrue(any("save" in p for p in problems), problems)
        self.assertTrue(any("crafting_cube" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
