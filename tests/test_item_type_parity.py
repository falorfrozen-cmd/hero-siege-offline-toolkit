"""Cross-binding parity for the item-class ``ItemType`` enum.

The value an item instance carries in its ``itemType`` field is declared once
per binding - ``hs_game_sdk.ItemType`` (Python), ``HeroSiege::Items::ItemType``
plus the enumerable ``kItemTypes`` (C++), and ``ItemType`` plus ``ITEM_TYPES``
(TypeScript). Nothing generates one from another, so this test is what stops
them drifting apart by a name or a value.

The C++ and TypeScript sources are parsed as text, which runs in every clean
checkout with no compiler and no node. Two further routes prove the parsed text
is what each language actually sees: the TypeScript file is executed under node
here, and the C++ header is compiled and printed by the harness that
``tests/test_cpp_sdk.py`` drives.

Values and names come from HSCraftSim/RESEARCH.md section 2 (see
docs/submodules/hs-game-sdk/instructions.md for the source of each member).
"""

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = ROOT / "hs-game-sdk"
SDK_PY_PATH = SDK_ROOT / "python"
if str(SDK_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PY_PATH))

from hs_game_sdk import RELIC_RARITY_TIER, ItemType  # noqa: E402

CPP_HEADER = SDK_ROOT / "cpp" / "include" / "hs_game_sdk" / "item_type.hpp"
TS_SOURCE = SDK_ROOT / "ts" / "src" / "item_type.ts"
GENERATOR = ROOT / "tools" / "extract_and_generate_sdk.py"
GUIDE = ROOT / "docs" / "submodules" / "hs-game-sdk" / "instructions.md"

# The pinned table. A change here is a change to the SDK's contract, not a
# refactor: every binding has to follow it.
EXPECTED = {
    "HELMET": 0,
    "BODY": 1,
    "BOOTS": 2,
    "WEAPON": 3,
    "GLOVES": 4,
    "AMULET": 5,
    "SHIELD": 6,
    "RING": 7,
    "BELT": 8,
    "CHARM": 10,
    "CONSUMABLE": 11,
    "KEY": 12,
    "TAROT": 13,
    "MATERIAL": 14,
    "SOCKETABLE": 15,
    "RELIC": 16,
    "POTION": 18,
    "OTHER": 19,
}

# No source names these integers; an entry for either would be invented.
UNEVIDENCED_VALUES = (9, 17)


def _normalise(pairs) -> dict:
    """Map every binding's naming style onto the Python one (all names are one word)."""
    return {name.replace("_", "").upper(): int(value) for name, value in pairs}


def _python_pairs() -> dict:
    return {member.name: member.value for member in ItemType}


def _block(text: str, pattern: str, what: str) -> str:
    match = re.search(pattern, text, re.DOTALL)
    if match is None:
        raise AssertionError(f"could not find {what}")
    return match.group(1)


def _cpp_enum_pairs(text: str) -> list:
    body = _block(
        text, r"enum\s+class\s+ItemType\s*:\s*(?:std::)?int32_t\s*\{(.*?)\}\s*;", "C++ enum ItemType"
    )
    return re.findall(r"\b([A-Za-z_]\w*)\s*=\s*(-?\d+)\s*,?", body)


def _cpp_table_pairs(text: str) -> list:
    body = _block(text, r"\bkItemTypes\b[^=]*=\s*\{(.*?)\}\s*;", "C++ kItemTypes")
    return re.findall(r"\{\s*\"(\w+)\"\s*,\s*ItemType::(\w+)\s*\}\s*,?", body)


def _ts_enum_pairs(text: str) -> list:
    body = _block(text, r"export\s+enum\s+ItemType\s*\{(.*?)\}", "TS enum ItemType")
    return re.findall(r"\b([A-Za-z_]\w*)\s*=\s*(-?\d+)\s*,?", body)


def _ts_table_pairs(text: str) -> list:
    body = _block(text, r"export\s+const\s+ITEM_TYPES\b[^=]*=\s*\[(.*?)\]", "TS ITEM_TYPES")
    return re.findall(
        r"\{\s*name\s*:\s*['\"](\w+)['\"]\s*,\s*value\s*:\s*ItemType\.(\w+)\s*\}\s*,?", body
    )


def _template(source: str, variable: str) -> str:
    return _block(source, rf"\b{variable}\s*=\s*'''(.*?)'''", f"template {variable}")


class TestItemTypePython(unittest.TestCase):
    def test_python_members_match_the_pinned_table(self):
        self.assertEqual(_python_pairs(), EXPECTED)

    def test_material_is_fourteen(self):
        """The value ForgePact's prospect-to-bag work needs."""
        self.assertEqual(ItemType.MATERIAL, 14)

    def test_relic_matches_the_relic_contract(self):
        self.assertEqual(ItemType.RELIC, RELIC_RARITY_TIER)


class TestItemTypeCpp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = CPP_HEADER.read_text(encoding="utf-8")

    def test_enum_matches_python(self):
        pairs = _cpp_enum_pairs(self.text)
        self.assertEqual(len(pairs), len(EXPECTED), pairs)
        self.assertEqual(_normalise(pairs), _python_pairs())

    def test_enumerable_table_matches_python(self):
        pairs = _cpp_table_pairs(self.text)
        self.assertEqual(len(pairs), len(EXPECTED), pairs)
        for label, member in pairs:
            with self.subTest(entry=label):
                self.assertEqual(label, member, "kItemTypes label names a different member")
        enum_values = dict(_cpp_enum_pairs(self.text))
        table = _normalise((label, enum_values[member]) for label, member in pairs)
        self.assertEqual(table, _python_pairs())


class TestItemTypeTypeScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = TS_SOURCE.read_text(encoding="utf-8")

    def test_enum_matches_python(self):
        pairs = _ts_enum_pairs(self.text)
        self.assertEqual(len(pairs), len(EXPECTED), pairs)
        self.assertEqual(_normalise(pairs), _python_pairs())

    def test_enumerable_table_matches_python(self):
        pairs = _ts_table_pairs(self.text)
        self.assertEqual(len(pairs), len(EXPECTED), pairs)
        for label, member in pairs:
            with self.subTest(entry=label):
                self.assertEqual(label, member, "ITEM_TYPES name names a different member")
        enum_values = dict(_ts_enum_pairs(self.text))
        table = _normalise((label, enum_values[member]) for label, member in pairs)
        self.assertEqual(table, _python_pairs())

    def test_executed_enum_matches_python(self):
        """What node actually evaluates, not just what the regex reads."""
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not on PATH")
        # --experimental-transform-types (TS enums) arrived in Node 22.7; an older node rejects
        # the flag, which says nothing about item_type.ts, so that is a skip, not a failure.
        version = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        match = re.match(r"v(\d+)\.(\d+)", version)
        if match is None or (int(match.group(1)), int(match.group(2))) < (22, 7):
            self.skipTest(f"node {version or '?'} predates --experimental-transform-types (22.7)")
        script = (
            f"import({json.dumps(TS_SOURCE.as_uri())}).then(m => console.log(JSON.stringify("
            "{enum: Object.entries(m.ItemType).filter(([k]) => isNaN(Number(k))),"
            " table: m.ITEM_TYPES.map(e => [e.name, e.value])})))"
        )
        result = subprocess.run(
            [node, "--experimental-transform-types", "--no-warnings", "-e", script],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads(result.stdout)
        self.assertEqual(len(loaded["enum"]), len(EXPECTED), loaded)
        self.assertEqual(_normalise(loaded["enum"]), _python_pairs())
        self.assertEqual(len(loaded["table"]), len(EXPECTED), loaded)
        self.assertEqual(_normalise(loaded["table"]), _python_pairs())


class TestNoUnevidencedMembers(unittest.TestCase):
    def test_no_binding_declares_nine_or_seventeen(self):
        bindings = {
            "python": _python_pairs().values(),
            "cpp": [int(v) for _, v in _cpp_enum_pairs(CPP_HEADER.read_text(encoding="utf-8"))],
            "ts": [int(v) for _, v in _ts_enum_pairs(TS_SOURCE.read_text(encoding="utf-8"))],
        }
        for binding, values in bindings.items():
            for value in UNEVIDENCED_VALUES:
                with self.subTest(binding=binding, value=value):
                    self.assertNotIn(value, list(values))


class TestGuideRecordsTheMeasuredRow(unittest.TestCase):
    """docs/submodules/hs-game-sdk/instructions.md's ItemType value table must say
    only what has actually been read from a live item instance - not more, and,
    once a row is measured, not less either.

    Every table row in the guide opens with a bare integer cell (`| 14 |`); the
    ItemType value table is the only table in the file shaped that way, so a
    per-line scan for that prefix is enough without extracting the section first.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = GUIDE.read_text(encoding="utf-8")

    def test_only_row_fourteen_is_measured_in_game(self):
        measured = set()
        for line in self.text.splitlines():
            match = re.match(r"^\| (\d+) \|", line)
            if match and "measured in-game" in line:
                measured.add(int(match.group(1)))
        self.assertEqual(measured, {14})

    def test_the_blanket_unmeasured_claim_is_gone(self):
        self.assertNotIn(
            "No row has been read from a live item instance on this runner yet",
            self.text,
        )


class TestAggregatesMatchGeneratorTemplates(unittest.TestCase):
    """The aggregate files are generated; an edit to one without its template is reverted
    by the next extraction, so both have to carry `item_type`."""

    @classmethod
    def setUpClass(cls):
        cls.generator = GENERATOR.read_text(encoding="utf-8").replace("\r\n", "\n")

    def _check(self, variable: str, path: Path, wiring: str):
        template = _template(self.generator, variable)
        committed = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertEqual(committed, template, f"{path.name} differs from template {variable}")
        self.assertIn(wiring, template)

    def test_python_init(self):
        self._check("init_content", SDK_PY_PATH / "hs_game_sdk" / "__init__.py",
                    "from .item_type import ItemType")
        self.assertIn('"ItemType"', _template(self.generator, "init_content"))

    def test_cpp_aggregate_header(self):
        self._check("main_header", SDK_ROOT / "cpp" / "include" / "hs_game_sdk" / "hs_game_sdk.hpp",
                    '#include "item_type.hpp"')

    def test_ts_index(self):
        self._check("index_content", SDK_ROOT / "ts" / "src" / "index.ts",
                    "export * from './item_type';")


if __name__ == "__main__":
    unittest.main()
