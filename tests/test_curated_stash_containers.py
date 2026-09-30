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

# The bag-to-stash move's routines (ForgePact #68); the first three are the
# ones every move needs, the next two the ones around them, and the last the
# Socketable tab's merge (Live 1f and 1g).
MOVE_STEPS = ("grid", "stack", "source_clear", "validate", "owner_step", "socket_merge")

# The UI node routines the in-game Move all button uses (ForgePact #68).
UI_NODE_STEPS = ("create", "remove", "set_activation", "move")


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

    # ForgePact #68: the bag-to-stash move. Every routine an SDK script at its
    # SDK index, every self an SDK object, every routine named in section 17.
    move = data.get("bag_to_stash_move")
    if require("bag_to_stash_move", move):
        node = move.get("grid_node_object", {})
        node_name, node_index = node.get("name"), node.get("index")
        if require("bag_to_stash_move.grid_node_object.name", node_name) and \
                require("bag_to_stash_move.grid_node_object.index", node_index):
            if node_name not in GameObject.__members__:
                problems.append(f"bag_to_stash_move.grid_node_object.name {node_name!r} is not a GameObject member")
            elif GameObject[node_name].value != node_index:
                problems.append(
                    f"bag_to_stash_move.grid_node_object.index {node_index!r} does not match "
                    f"GameObject[{node_name!r}].value ({GameObject[node_name].value!r})"
                )
        for step in MOVE_STEPS:
            entry = move.get(step)
            if not require(f"bag_to_stash_move.{step}", entry):
                continue
            script = entry.get("script")
            if require(f"bag_to_stash_move.{step}.script", script):
                if script not in SCRIPT_NAME_TO_INDEX:
                    problems.append(f"bag_to_stash_move.{step}.script {script!r} is not in SCRIPT_NAME_TO_INDEX")
                elif SCRIPT_NAME_TO_INDEX[script] != entry.get("index"):
                    problems.append(
                        f"bag_to_stash_move.{step}.index {entry.get('index')!r} does not match "
                        f"SCRIPT_NAME_TO_INDEX[{script!r}] ({SCRIPT_NAME_TO_INDEX[script]!r})"
                    )
                if _bare_script_name(script) not in section:
                    problems.append(
                        f"bag_to_stash_move.{step}.script {script!r} is absent from "
                        "RUNTIME_DATA_MODELS.md section 17"
                    )
            self_object = entry.get("self_object")
            if require(f"bag_to_stash_move.{step}.self_object", self_object) and \
                    self_object not in GameObject.__members__:
                problems.append(f"bag_to_stash_move.{step}.self_object {self_object!r} is not a GameObject member")
            require(f"bag_to_stash_move.{step}.arguments", entry.get("arguments"))
        owners = move.get("map_owner_by_tab", {})
        for kind in ("personal", "shared"):
            require(f"bag_to_stash_move.map_owner_by_tab.{kind}", owners.get(kind))
        socket = move.get("socket_merge") or {}
        container = socket.get("container")
        if require("bag_to_stash_move.socket_merge.container", container) and "StashSocketGrid" not in container:
            problems.append("bag_to_stash_move.socket_merge.container does not name the StashSocketGrid nodes")
        # ForgePact #131: the merge's cap, a static reading (R) until a live
        # session measures it (M); both numbers stated in section 17 too.
        cap = move.get("stack_cap")
        if require("bag_to_stash_move.stack_cap", cap):
            for key, want in (("default_cap", 999), ("flag_8_cap", 999999)):
                value = cap.get(key)
                if require(f"bag_to_stash_move.stack_cap.{key}", value) and value != want:
                    problems.append(f"bag_to_stash_move.stack_cap.{key} {value!r} is not {want}")
                elif value is not None and str(value) not in section:
                    problems.append(f"bag_to_stash_move.stack_cap.{key} {value!r} is absent from RUNTIME_DATA_MODELS.md section 17")
            require("bag_to_stash_move.stack_cap.rule", cap.get("rule"))
            measured = cap.get("measured")
            if require("bag_to_stash_move.stack_cap.measured", measured) and measured not in ("R", "M"):
                problems.append(f"bag_to_stash_move.stack_cap.measured {measured!r} is neither R nor M")

    # ForgePact #68's button: the UI node API. Every script an SDK script at
    # its SDK index and named in section 17, every object an SDK object at its
    # index.
    ui = data.get("ui_node_api")
    if require("ui_node_api", ui):
        for key in ("node_object", "owner_object", "mercenary_button"):
            obj = ui.get(key) or {}
            name, index = obj.get("name"), obj.get("index")
            if require(f"ui_node_api.{key}.name", name) and require(f"ui_node_api.{key}.index", index):
                if name not in GameObject.__members__:
                    problems.append(f"ui_node_api.{key}.name {name!r} is not a GameObject member")
                elif GameObject[name].value != index:
                    problems.append(
                        f"ui_node_api.{key}.index {index!r} does not match GameObject[{name!r}].value "
                        f"({GameObject[name].value!r})"
                    )
        sort_node = ui.get("sort_node") or {}
        callstack = sort_node.get("uiNodeCallstack")
        if require("ui_node_api.sort_node.uiNodeCallstack", callstack) and callstack not in section:
            problems.append(f"ui_node_api.sort_node.uiNodeCallstack {callstack!r} is absent from RUNTIME_DATA_MODELS.md section 17")
        # ForgePact #131: where a node's x, y put it - the button's origin is
        # its bbox centre, Sort's its top-left.
        origin = ui.get("node_origin")
        if require("ui_node_api.node_origin", origin) and not ("centre" in origin and "top-left" in origin):
            problems.append("ui_node_api.node_origin does not say which origin is the bbox centre and which the top-left")
        # ForgePact #131, Live 5 and 6: the Mercenary button the Move all
        # button takes the place of, and the members that carry a node's label
        # place and look. Each named in section 17 and labelled R or M.
        merc = ui.get("mercenary_button") or {}
        merc_callstack = merc.get("uiNodeCallstack")
        if require("ui_node_api.mercenary_button.uiNodeCallstack", merc_callstack) and merc_callstack not in section:
            problems.append(
                f"ui_node_api.mercenary_button.uiNodeCallstack {merc_callstack!r} is absent from RUNTIME_DATA_MODELS.md section 17"
            )
        require("ui_node_api.mercenary_button.box_relation", merc.get("box_relation"))
        label = ui.get("label_members")
        if require("ui_node_api.label_members", label):
            members = label.get("members")
            if require("ui_node_api.label_members.members", members):
                for member in members:
                    if member not in section:
                        problems.append(f"ui_node_api.label_members member {member!r} is absent from RUNTIME_DATA_MODELS.md section 17")
        for key in ("mercenary_button", "label_members"):
            measured = (ui.get(key) or {}).get("measured")
            if require(f"ui_node_api.{key}.measured", measured) and measured not in ("R", "M"):
                problems.append(f"ui_node_api.{key}.measured {measured!r} is neither R nor M")
        for step in UI_NODE_STEPS:
            entry = ui.get(step)
            if not require(f"ui_node_api.{step}", entry):
                continue
            script = entry.get("script")
            if require(f"ui_node_api.{step}.script", script):
                if script not in SCRIPT_NAME_TO_INDEX:
                    problems.append(f"ui_node_api.{step}.script {script!r} is not in SCRIPT_NAME_TO_INDEX")
                elif SCRIPT_NAME_TO_INDEX[script] != entry.get("index"):
                    problems.append(
                        f"ui_node_api.{step}.index {entry.get('index')!r} does not match "
                        f"SCRIPT_NAME_TO_INDEX[{script!r}] ({SCRIPT_NAME_TO_INDEX[script]!r})"
                    )
                if _bare_script_name(script) not in section:
                    problems.append(f"ui_node_api.{step}.script {script!r} is absent from RUNTIME_DATA_MODELS.md section 17")
            self_object = entry.get("self_object")
            if require(f"ui_node_api.{step}.self_object", self_object) and self_object not in GameObject.__members__:
                problems.append(f"ui_node_api.{step}.self_object {self_object!r} is not a GameObject member")
            require(f"ui_node_api.{step}.arguments", entry.get("arguments"))

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
        bad["bag_to_stash_move"]["grid"]["index"] = 1971
        bad["bag_to_stash_move"]["stack"]["script"] = "gml_Script_NoSuchStack"
        bad["bag_to_stash_move"]["source_clear"]["self_object"] = "No_Such_obj"
        del bad["bag_to_stash_move"]["map_owner_by_tab"]["shared"]
        bad["bag_to_stash_move"]["socket_merge"]["index"] = 113
        bad["bag_to_stash_move"]["socket_merge"]["container"] = "Controller_obj.stashSocketItemSlot"
        bad["ui_node_api"]["create"]["script"] = "gml_Script_NoSuchCreateNode"
        bad["ui_node_api"]["remove"]["index"] = 4462
        bad["ui_node_api"]["node_object"]["index"] = 5010
        bad["ui_node_api"]["move"]["self_object"] = "No_Such_Window_obj"
        bad["ui_node_api"]["sort_node"]["uiNodeCallstack"] = "NoSuchSort"
        bad["bag_to_stash_move"]["stack_cap"]["default_cap"] = 1000
        bad["bag_to_stash_move"]["stack_cap"]["measured"] = "guessed"
        bad["ui_node_api"]["node_origin"] = "the node's x, y"
        bad["ui_node_api"]["mercenary_button"]["index"] = 5005
        bad["ui_node_api"]["mercenary_button"]["uiNodeCallstack"] = "NoSuchMercenary"
        bad["ui_node_api"]["label_members"]["members"].append("noSuchLabelMember")
        bad["ui_node_api"]["label_members"]["measured"] = "assumed"

        problems = validate(bad, self.doc_text)

        self.assertTrue(any("985" in p for p in problems), problems)
        self.assertTrue(any("gml_Script_NoSuchScript" in p for p in problems), problems)
        self.assertTrue(any("stashNoSuchVar" in p for p in problems), problems)
        self.assertTrue(any("gml_Script_NoSuchSave" in p for p in problems), problems)
        self.assertTrue(any("noSuchGrid" in p for p in problems), problems)
        self.assertTrue(any("3068" in p for p in problems), problems)
        self.assertTrue(any("1971" in p for p in problems), problems)
        self.assertTrue(any("gml_Script_NoSuchStack" in p for p in problems), problems)
        self.assertTrue(any("No_Such_obj" in p for p in problems), problems)
        self.assertTrue(any("map_owner_by_tab.shared" in p for p in problems), problems)
        self.assertTrue(any("socket_merge.index 113" in p for p in problems), problems)
        self.assertTrue(any("socket_merge.container" in p for p in problems), problems)
        self.assertTrue(any("gml_Script_NoSuchCreateNode" in p for p in problems), problems)
        self.assertTrue(any("remove.index 4462" in p for p in problems), problems)
        self.assertTrue(any("node_object.index 5010" in p for p in problems), problems)
        self.assertTrue(any("No_Such_Window_obj" in p for p in problems), problems)
        self.assertTrue(any("NoSuchSort" in p for p in problems), problems)
        self.assertTrue(any("stack_cap.default_cap 1000" in p for p in problems), problems)
        self.assertTrue(any("stack_cap.measured 'guessed'" in p for p in problems), problems)
        self.assertTrue(any("ui_node_api.node_origin" in p for p in problems), problems)
        self.assertTrue(any("mercenary_button.index 5005" in p for p in problems), problems)
        self.assertTrue(any("NoSuchMercenary" in p for p in problems), problems)
        self.assertTrue(any("noSuchLabelMember" in p for p in problems), problems)
        self.assertTrue(any("label_members.measured 'assumed'" in p for p in problems), problems)

    def test_validator_reports_a_missing_object_as_a_problem(self):
        missing = copy.deepcopy(self.data)
        del missing["save"]
        del missing["crafting_cube"]
        del missing["ui_node_api"]
        del missing["bag_to_stash_move"]["socket_merge"]
        del missing["bag_to_stash_move"]["stack_cap"]

        problems = validate(missing, self.doc_text)

        self.assertTrue(any("save" in p for p in problems), problems)
        self.assertTrue(any("crafting_cube" in p for p in problems), problems)
        self.assertTrue(any("ui_node_api" in p for p in problems), problems)
        self.assertTrue(any("bag_to_stash_move.socket_merge" in p for p in problems), problems)
        self.assertTrue(any("bag_to_stash_move.stack_cap" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
