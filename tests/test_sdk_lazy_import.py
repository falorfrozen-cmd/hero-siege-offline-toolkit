"""hs_game_sdk imports its five generated tables on first use.

``hs_game_sdk/__init__.py`` used to import every generated table eagerly.
Building an IntEnum takes time quadratic in its member count on CPython 3.10
and 3.13, and ``GameSprite`` has 32,271 members, so every ``import
hs_game_sdk`` paid 3.2 s on 3.13 (43 s on 3.10) for a table the caller never
used. ForgePact's panel, and every sandbox its browser tests start, paid it at
each start without touching a sprite. The package now imports a table the
first time one of its names is used (PEP 562 ``__getattr__``); see
docs/submodules/hs-game-sdk/instructions.md, "Import cost".

The tests pin the win in a fresh interpreter each, since a table another test
already imported would hide a regression. They also pin what the lazy import
has to keep: every name the eager package bound is still bound, and is the
same object as its module's; ``from hs_game_sdk import *`` binds exactly
``__all__``; the submodules are still attributes of the package; and the
static imports that PyInstaller reads still name every table, because a
frozen ForgePact.exe bundles only the modules its analysis sees imported.
"""

import ast
import importlib
import json
import modulefinder
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY_PATH = ROOT / "hs-game-sdk" / "python"
INIT_FILE = SDK_PY_PATH / "hs_game_sdk" / "__init__.py"
if str(SDK_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PY_PATH))

import hs_game_sdk  # noqa: E402

TABLES = ("objects", "scripts", "rooms", "sprites", "sounds")

# Every name hs_game_sdk/__init__.py bound before the tables became lazy (hub
# ef15a74), by the module that defines it, plus the three relic-identification
# names issue #93 added to player (RELIC_ITEM_CLASS and the two item-instance
# fields). The satanic_zone names were bound but never listed in __all__, and
# that stays as it was.
EXPORTS = {
    "objects": (
        "GameObject",
        "OBJECT_INDEX_TO_NAME",
        "OBJECT_NAME_TO_INDEX",
        "OBJECT_PARENT_INDEX",
        "OBJECT_MASK_SPRITE_INDEX",
        "NO_PARENT",
        "NO_MASK",
        "get_parent_index",
        "get_ancestor_indices",
        "get_child_indices",
        "get_descendant_indices",
        "is_descendant_of",
        "get_mask_sprite_index",
    ),
    "scripts": ("GameScript", "SCRIPT_INDEX_TO_NAME", "SCRIPT_NAME_TO_INDEX"),
    "rooms": ("GameRoom", "ROOM_INDEX_TO_NAME", "ROOM_NAME_TO_INDEX"),
    "sprites": ("GameSprite", "SPRITE_INDEX_TO_NAME", "SPRITE_NAME_TO_INDEX"),
    "sounds": ("GameSound", "SOUND_INDEX_TO_NAME", "SOUND_NAME_TO_INDEX"),
    "stats": ("StatId", "ProcBundle", "PROC_FAMILIES", "DECODED_STAT_NAMES", "BUFF_ANGELIC_CHANCE"),
    "satanic_zone": (
        "SatanicMod",
        "SATANIC_BUFFS",
        "SATANIC_DEBUFFS",
        "SATANIC_ZONE_VAR",
        "SATANIC_ZONE_BUFF_VAR",
        "SATANIC_ZONE_DEBUFF_VAR",
    ),
    "structs": ("ItemDefinitionStruct", "ItemStatStruct", "CraftData", "PlayerInstance"),
    "player": (
        "EquipmentSlot",
        "PlayerEquipment",
        "scan_relic_levels",
        "maxed_relic_ids",
        "RELIC_RARITY_TIER",
        "RELIC_ID_LIMIT",
        "MAXED_RELIC_LEVEL",
        "MAX_SCAN_DEPTH",
        "MAX_SCANNED_ARRAY_LENGTH",
        "RELIC_ID_FIELDS",
        "RELIC_TIER_FIELDS",
        "RELIC_LEVEL_FIELDS",
        "RELIC_ONLY_FIELD",
        "GENERAL_CONTAINER_FIELDS",
        "RELIC_CONTAINER_FIELDS",
        "RELIC_ITEM_CLASS",
        "ITEM_INSTANCE_TYPE_FIELD",
        "ITEM_INSTANCE_DEFINITION_FIELD",
    ),
    "item_type": ("ItemType",),
    "mod_registry": ("ModDefinition", "ModRegistry", "GLOBAL_MOD_REGISTRY"),
}

# ForgePact's src/forgepact.py import list (ForgePact a77c33e): the panel, and
# every sandbox its browser tests start, import exactly these.
FORGEPACT_NAMES = (
    "GameObject",
    "GameScript",
    "StatId",
    "PROC_FAMILIES",
    "EquipmentSlot",
    "PlayerEquipment",
    "scan_relic_levels",
    "ModDefinition",
    "GLOBAL_MOD_REGISTRY",
    "SATANIC_BUFFS",
    "SATANIC_DEBUFFS",
)

_PROBE = """
import json, sys
sys.path.insert(0, {sdk!r})
result = None
{statement}
loaded = sorted(m.split(".", 1)[1] for m in sys.modules if m.startswith("hs_game_sdk."))
print(json.dumps({{"loaded": loaded, "result": result}}))
"""


def _fresh(statement: str):
    """Run `statement` in a new interpreter: (submodules it imported, its `result`)."""
    code = _PROBE.format(sdk=str(SDK_PY_PATH), statement=statement)
    run = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True,
                         text=True, timeout=300)
    if run.returncode != 0:
        raise AssertionError(f"probe failed:\n{run.stderr}")
    answer = json.loads(run.stdout.strip().splitlines()[-1])
    return set(answer["loaded"]), answer["result"]


def _static_table_imports(init_source: str) -> dict:
    """The relative `from .x import ...` statements inside `if TYPE_CHECKING:`."""
    found = {}
    for node in ast.parse(init_source).body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            for stmt in node.body:
                if isinstance(stmt, ast.ImportFrom) and stmt.level == 1:
                    found[stmt.module] = tuple(alias.name for alias in stmt.names)
    return found


def _scanned_modules(package_dir: Path, statement: str) -> set:
    """What a bytecode-scanning bundler (modulefinder, like PyInstaller) finds."""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "probe.py"
        script.write_text(statement + "\n", encoding="utf-8")
        finder = modulefinder.ModuleFinder(path=[str(package_dir)])
        finder.run_script(str(script))
        return set(finder.modules)


class TestTablesLoadOnFirstUse(unittest.TestCase):
    def test_import_builds_no_table(self):
        loaded, listed = _fresh("import hs_game_sdk\nresult = sorted(dir(hs_game_sdk))")
        self.assertEqual(loaded & set(TABLES), set())
        self.assertEqual(loaded, set(EXPORTS) - set(TABLES))
        # dir() advertises the lazy names without importing their tables.
        for module in TABLES:
            with self.subTest(module=module):
                self.assertIn(module, listed)
                for name in EXPORTS[module]:
                    self.assertIn(name, listed)

    def test_forgepact_import_list_builds_objects_and_scripts_only(self):
        loaded, _ = _fresh(f"from hs_game_sdk import {', '.join(FORGEPACT_NAMES)}")
        self.assertEqual(loaded & set(TABLES), {"objects", "scripts"})

    def test_a_name_builds_only_its_own_table(self):
        # sprites is left out only because building it costs seconds; the
        # in-process tests below build it.
        for module in ("objects", "scripts", "rooms", "sounds"):
            with self.subTest(module=module):
                loaded, _ = _fresh(f"from hs_game_sdk import {EXPORTS[module][0]}")
                self.assertEqual(loaded & set(TABLES), {module})

    def test_submodule_attribute_imports_it(self):
        loaded, value = _fresh("import hs_game_sdk\nresult = int(hs_game_sdk.rooms.GameRoom.Act_01_01)")
        self.assertEqual(loaded & set(TABLES), {"rooms"})
        self.assertEqual(value, 1)


class TestSameNamesAsTheEagerPackage(unittest.TestCase):
    def test_every_name_is_its_modules_object(self):
        for module, names in EXPORTS.items():
            source = importlib.import_module(f"hs_game_sdk.{module}")
            for name in names:
                with self.subTest(name=name):
                    self.assertIs(getattr(hs_game_sdk, name), getattr(source, name))

    def test_from_import_binds_the_same_objects(self):
        names = [name for group in EXPORTS.values() for name in group]
        namespace = {}
        exec(f"from hs_game_sdk import {', '.join(names)}", namespace)
        for name in names:
            with self.subTest(name=name):
                self.assertIs(namespace[name], getattr(hs_game_sdk, name))

    def test_star_import_binds_exactly_all(self):
        namespace = {}
        exec("from hs_game_sdk import *", namespace)
        namespace.pop("__builtins__", None)
        self.assertEqual(set(namespace), set(hs_game_sdk.__all__))
        for name, value in namespace.items():
            with self.subTest(name=name):
                self.assertIs(value, getattr(hs_game_sdk, name))

    def test_all_is_unchanged(self):
        everything = {name for group in EXPORTS.values() for name in group}
        self.assertEqual(set(hs_game_sdk.__all__), everything - set(EXPORTS["satanic_zone"]))
        self.assertEqual(len(hs_game_sdk.__all__), len(set(hs_game_sdk.__all__)))

    def test_submodules_are_package_attributes(self):
        for module in EXPORTS:
            with self.subTest(module=module):
                self.assertIs(getattr(hs_game_sdk, module), sys.modules[f"hs_game_sdk.{module}"])

    def test_unknown_names_still_raise_attribute_error(self):
        with self.assertRaisesRegex(AttributeError, r"module 'hs_game_sdk' has no attribute 'NoSuchName'"):
            hs_game_sdk.NoSuchName  # noqa: B018
        self.assertFalse(hasattr(hs_game_sdk, "NoSuchName"))
        with self.assertRaises(ImportError):
            exec("from hs_game_sdk import NoSuchName", {})

    def test_a_module_the_package_never_imports_still_imports(self):
        namespace = {}
        exec("from hs_game_sdk import drop_roll_model", namespace)
        self.assertEqual(namespace["drop_roll_model"].__name__, "hs_game_sdk.drop_roll_model")


class TestBundlersSeeEveryTable(unittest.TestCase):
    def test_static_imports_match_the_loader(self):
        static = _static_table_imports(INIT_FILE.read_text(encoding="utf-8"))
        self.assertEqual(static, {module: EXPORTS[module] for module in TABLES})
        self.assertEqual(static, dict(hs_game_sdk._LAZY_MODULES))

    def test_bytecode_scanner_finds_every_submodule(self):
        found = _scanned_modules(SDK_PY_PATH, "import hs_game_sdk")
        for module in EXPORTS:
            with self.subTest(module=module):
                self.assertIn(f"hs_game_sdk.{module}", found)

    def test_scanner_misses_a_lazy_module_without_static_imports(self):
        """The negative control: the static imports are what the scanner sees."""
        loader = (
            "import importlib\n"
            "def __getattr__(name):\n"
            "    return getattr(importlib.import_module(__name__ + '.table'), name)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "lazypkg"
            package.mkdir()
            (package / "table.py").write_text("VALUE = 1\n", encoding="utf-8")
            (package / "__init__.py").write_text(loader, encoding="utf-8")
            self.assertNotIn("lazypkg.table", _scanned_modules(Path(tmp), "import lazypkg"))
            (package / "__init__.py").write_text(
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    from .table import VALUE\n" + loader, encoding="utf-8")
            self.assertIn("lazypkg.table", _scanned_modules(Path(tmp), "import lazypkg"))


if __name__ == "__main__":
    unittest.main()
