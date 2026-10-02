"""Checks for `hs_game_sdk.monster_rank_model` (ForgePact#44, hub #379).

The model is written from `docs/models/monster-rank-spec.md` and covers the game
only: what a monster's rank (`enemyRarity` 1-4) does to its health, damage, XP
and protected drop values. ForgePact's Bosses control (`bossrarity`) is our
code, so it lives here as an input transform (`force_boss_rank`).
`LeverParityTests` pins that transform to ForgePact's source when ForgePact is
checked out.

Baseline: what the game does with no mod. Target: what the Bosses control must
turn it into. That is the order `AGENTS.md` § "Mod Development Workflow" asks
for. Whether a boss built at rank 3 or 4 actually takes the rank table's rows is
not established; `HypothesisTests` keeps the model honest about that until a
measured row about a boss is in the curated file.

Each entry of `hs-game-sdk/curated/monster_rank_measurements.json` names the
test that reproduces it (`reproduced_by`) or says why none can
(`not_reproduced`).

Run from the hub root: `py -3 -m unittest tests.test_monster_rank_model -v`.
"""
import ast
import json
import re
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
FIXTURE = ROOT / "hs-game-sdk" / "curated" / "monster_rank_measurements.json"
MODEL_FILE = SDK_PY / "hs_game_sdk" / "monster_rank_model.py"
SPEC_DOC = ROOT / "docs" / "models" / "monster-rank-spec.md"
HOOKS_DIR = ROOT / ".claude" / "hooks"
FORGEPACT = ROOT / "ForgePact"
FORGEPACT_BOSS = FORGEPACT / "plugin" / "include" / "ForgePact" / "BossRarityMod.hpp"
FORGEPACT_PANEL = FORGEPACT / "src" / "forgepact.py"

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import monster_rank_model as model  # noqa: E402

#: A rank-1 boss, in round numbers: the model is linear, so any base will do.
BASE_HP, BASE_DAMAGE, BASE_XP = 100000, 500, 2000

# ---- ForgePact's Bosses control, as an input transform (our code, not the game's) ----

#: The panel's values for `boss_rarity` (ForgePact's `BOSS_RARITY_VALUES`).
FORGEPACT_BOSS_MODES = ("off", "rare", "ancient")
#: The rank each mode writes (ForgePact's `kRareTier` / `kAncientTier`).
FORGEPACT_BOSS_TIERS = {"rare": 3, "ancient": 4}
#: The affix count the top-up fills a raised boss to (`kRareAffixes` / `kAncientAffixes`).
FORGEPACT_BOSS_AFFIXES = {3: 2, 4: 3}


def force_boss_rank(mode, rank=1, is_boss=True, enemy_born=False):
    """ForgePact#44: at the entry of `EnemyRaritySettings`, a boss at rank 1 that
    no monster created is written to 3 (rare) or 4 (ancient). Everything else,
    and every instance while the mode is off, keeps its rank."""
    if mode not in FORGEPACT_BOSS_MODES:
        raise ValueError(f"not a Bosses mode: {mode!r}")
    if mode == "off" or not is_boss or enemy_born or rank != 1:
        return rank
    return FORGEPACT_BOSS_TIERS[mode]


class BaselineTests(unittest.TestCase):
    """The game with no mod: the spec's measured rank table, as numbers."""

    def test_baseline_rank_one_is_the_vanilla_monster(self):
        out = model.scaled(1, BASE_HP, BASE_DAMAGE, BASE_XP)
        self.assertEqual((out.hp, out.damage, out.xp), (BASE_HP, BASE_DAMAGE, BASE_XP))
        row = model.RANK_TABLE[1]
        self.assertEqual((row.hp, row.damage, row.xp), (1, 1, 1))

    def test_the_ranks_are_one_to_four(self):
        self.assertEqual(model.RANKS, (1, 2, 3, 4))
        self.assertEqual(tuple(sorted(model.RANK_TABLE)), model.RANKS)

    def test_every_value_rises_with_rank_but_the_satanic_multiplier(self):
        rows = [model.RANK_TABLE[rank] for rank in model.RANKS]
        for field in ("hp", "damage", "xp", "common_chance", "common_drop_mult"):
            with self.subTest(field=field):
                values = [getattr(row, field) for row in rows]
                self.assertEqual(values, sorted(set(values)), field)
        satanic = [row.satanic_drop_mult for row in rows]
        self.assertEqual(satanic, sorted(set(satanic), reverse=True))

    def test_values_are_exact(self):
        for rank in model.RANKS:
            row = model.RANK_TABLE[rank]
            for field in ("hp", "damage", "xp", "satanic_drop_mult"):
                with self.subTest(rank=rank, field=field):
                    self.assertIsInstance(getattr(row, field), Fraction)
        out = model.scaled(3, BASE_HP, BASE_DAMAGE, BASE_XP)
        self.assertEqual(out.hp, 298000)
        self.assertEqual(out.damage, Fraction(1530, 2))
        self.assertEqual(out.xp, 8500)

    def test_nonsense_is_refused(self):
        for rank in (0, 5, -1, 2.5, True):
            with self.subTest(rank=rank):
                with self.assertRaises(ValueError):
                    model.scaled(rank, BASE_HP, BASE_DAMAGE, BASE_XP)
        with self.assertRaises(ValueError):
            model.scaled(2, -1, BASE_DAMAGE, BASE_XP)


class TargetTests(unittest.TestCase):
    """What the Bosses control must turn the baseline into, if a boss follows the table."""

    def test_target_forced_rank_three_and_four_take_the_rank_rows(self):
        for mode, rank in (("rare", 3), ("ancient", 4)):
            with self.subTest(mode=mode):
                forced = force_boss_rank(mode)
                self.assertEqual(forced, rank)
                out = model.scaled(forced, BASE_HP, BASE_DAMAGE, BASE_XP)
                row = model.RANK_TABLE[rank]
                self.assertEqual(out.hp, BASE_HP * row.hp)
                self.assertEqual(out.damage, BASE_DAMAGE * row.damage)
                self.assertEqual(out.xp, BASE_XP * row.xp)
        self.assertEqual(model.scaled(force_boss_rank("ancient"), BASE_HP, BASE_DAMAGE, BASE_XP).hp,
                         423000)
        self.assertEqual(model.RANK_TABLE[force_boss_rank("ancient")].slots, (4, 8))

    def test_off_leaves_the_boss_at_the_baseline(self):
        self.assertEqual(force_boss_rank("off"), 1)
        self.assertEqual(model.scaled(force_boss_rank("off"), BASE_HP, BASE_DAMAGE, BASE_XP),
                         model.scaled(1, BASE_HP, BASE_DAMAGE, BASE_XP))

    def test_an_ordinary_monster_is_never_raised(self):
        for mode in FORGEPACT_BOSS_MODES:
            with self.subTest(mode=mode):
                self.assertEqual(force_boss_rank(mode, is_boss=False), 1)

    def test_an_enemy_born_boss_keeps_its_rank(self):
        self.assertEqual(force_boss_rank("ancient", enemy_born=True), 1)

    def test_a_boss_the_game_already_raised_keeps_its_rank(self):
        for rank in (2, 3, 4):
            with self.subTest(rank=rank):
                self.assertEqual(force_boss_rank("rare", rank=rank), rank)
                self.assertEqual(force_boss_rank("ancient", rank=rank), rank)

    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(ValueError):
            force_boss_rank("legion")


class MeasuredTests(unittest.TestCase):
    """The model against the curated rows (`monster_rank_measurements.json`)."""

    @classmethod
    def setUpClass(cls):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.entries = {entry["id"]: entry for entry in data["measurements"]}

    def test_mk1_the_rank_multipliers(self):
        values = self.entries["MK1"]["values"]
        for field in ("hp", "damage", "xp"):
            for rank, text in values[field].items():
                with self.subTest(field=field, rank=rank):
                    self.assertEqual(getattr(model.RANK_TABLE[int(rank)], field), Fraction(text))

    def test_mk2_the_drop_values_by_rank(self):
        values = self.entries["MK2"]["values"]
        for rank in model.RANKS:
            key = str(rank)
            row = model.RANK_TABLE[rank]
            with self.subTest(rank=rank):
                self.assertEqual(row.common_chance, values["common_chance"][key])
                self.assertEqual(row.common_drop_mult, values["common_drop_mult"][key])
                self.assertEqual(row.satanic_drop_mult, Fraction(values["satanic_drop_mult"][key]))
                self.assertEqual(row.slots, tuple(values["slots"][key]))

    def test_mk5_the_report_is_above_every_health_row(self):
        # The report is not evidence about the table, but the spec says its
        # ratio is above every row; keep that sentence true.
        values = self.entries["MK5"]["values"]
        ratio = Fraction(values["hp_after"], values["hp_before"])
        self.assertGreater(ratio, max(model.RANK_TABLE[rank].hp for rank in model.RANKS))
        self.assertEqual(self.entries["MK5"]["status"], "reported")


class HypothesisTests(unittest.TestCase):
    """What a forced rank does to a boss stays open until a session measures it."""

    def test_boss_rows_are_not_established_until_measured(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        boss_rows = [e["id"] for e in data["measurements"]
                     if e["status"] == "measured" and "boss" in e["what"].lower()]
        self.assertEqual(set(model.HYPOTHESES), {"boss_follows_rank_table"})
        answer = model.HYPOTHESES["boss_follows_rank_table"]
        if boss_rows:
            self.assertIsInstance(answer, bool, boss_rows)
        else:
            self.assertIsNone(answer, "set from no measured boss row")

    def test_a_report_does_not_count_as_a_measurement(self):
        # Negative control: the fixture does carry a row about a boss (MK5),
        # and it alone must not be enough to set the hypothesis.
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        reported = [e for e in data["measurements"] if "boss" in e["what"].lower()]
        self.assertTrue(any(e["status"] == "reported" for e in reported))


class MonsterRankFamilyTests(unittest.TestCase):
    """The spec's boss family, against `hs-game-sdk`'s object parent table."""

    def test_the_boss_family_is_the_sdks(self):
        from hs_game_sdk import objects
        GameObject = objects.GameObject
        bosses = objects.get_descendant_indices(GameObject.Enemy_Child_Boss_obj)
        self.assertEqual(int(GameObject.Enemy_Child_Boss_obj), 1407)
        self.assertEqual(len(bosses), 41)
        for name, index in (("Karp_King_obj", 2368), ("Damien_obj", 1115), ("Uber_Damien_obj", 4945),
                            ("Uber_Anubis_obj", 4938), ("Uber_Luna_obj", 4952)):
            with self.subTest(name=name):
                self.assertEqual(int(GameObject[name]), index)
                self.assertIn(index, bosses)
        self.assertEqual(
            [GameObject(i).name for i in objects.get_ancestor_indices(GameObject.Karp_King_obj)],
            ["Enemy_Child_Boss_obj", "Enemy_Parent_obj", "Avoidable_Parent_obj"])
        self.assertEqual(
            sorted(GameObject(i).name for i in objects.get_child_indices(GameObject.Enemy_Parent_obj)),
            ["Demon_Lightning_obj", "Enemy_Child_Basic_obj", "Enemy_Child_Boss_obj",
             "Enemy_Child_Destructible_obj"])
        # Negative control: a prop named like a boss is not one.
        self.assertFalse(objects.is_descendant_of(GameObject.Ghost_Pirate_King_Boss_obj,
                                                  GameObject.Enemy_Parent_obj))
        self.assertIn("41 descendants", SPEC_DOC.read_text(encoding="utf-8"))


class FixtureShapeTests(unittest.TestCase):
    REQUIRED = ("id", "kind", "status", "date", "source", "scripts", "what", "values", "model")

    @classmethod
    def setUpClass(cls):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.note = data["$schema_note"]
        cls.entries = data["measurements"]

    def test_every_entry_has_the_fields(self):
        ids = [e["id"] for e in self.entries]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({"MK1", "MK2", "MK3", "MK4", "MK5"} <= set(ids))
        self.assertIn("monster-rank-spec.md", self.note)
        for entry in self.entries:
            for field in self.REQUIRED:
                self.assertIn(field, entry, entry.get("id"))
            self.assertRegex(entry["id"], r"^MK\d+$")
            self.assertIn(entry["kind"], ("baseline", "target", "our_code"), entry["id"])
            self.assertIn(entry["status"],
                          ("measured", "reported", "not_observed", "qualitative", "approximate",
                           "our_code"), entry["id"])
            self.assertRegex(entry["date"], r"^\d{4}-\d{2}-\d{2}$", entry["id"])
            self.assertEqual(("reproduced_by" in entry) + ("not_reproduced" in entry), 1,
                             f"{entry['id']} needs exactly one of reproduced_by / not_reproduced")

    def test_every_named_test_exists_in_this_module(self):
        named = 0
        for entry in self.entries:
            if "reproduced_by" not in entry:
                continue
            dotted = entry["reproduced_by"]
            prefix = "tests.test_monster_rank_model."
            self.assertTrue(dotted.startswith(prefix), dotted)
            class_name, method = dotted[len(prefix):].split(".")
            cls = globals().get(class_name)
            self.assertIsNotNone(cls, dotted)
            self.assertTrue(method.startswith("test_"), dotted)
            self.assertTrue(callable(getattr(cls, method, None)), dotted)
            named += 1
        self.assertGreater(named, 0)

    def test_every_script_is_bound_in_the_sdk(self):
        from hs_game_sdk.scripts import GameScript
        for entry in self.entries:
            self.assertTrue(entry["scripts"], entry["id"])
            for name in entry["scripts"]:
                self.assertIn(name, GameScript.__members__, f"{entry['id']}: {name}")
        # Negative control: an unbound name is not in the table.
        self.assertNotIn("gml_Script_" + "NoSuchRankScript", GameScript.__members__)

    def test_source_paths_exist_where_they_can_be_checked(self):
        # Hub CI checks out without submodules, so a ForgePact path is only
        # checked where ForgePact is initialised.
        forgepact_present = (FORGEPACT / "src").is_dir()
        checked = 0
        for entry in self.entries:
            self.assertTrue(entry["source"], entry["id"])
            for source in entry["source"]:
                self.assertTrue(("path" in source) != ("commit" in source), (entry["id"], source))
                if "commit" in source:
                    self.assertRegex(source["commit"], r"^[0-9a-f]{7,40}$", entry["id"])
                    continue
                if source["path"].startswith("ForgePact/") and not forgepact_present:
                    continue
                path = ROOT / source["path"]
                self.assertTrue(path.is_file(), f"{entry['id']}: {source['path']}")
                if "section" in source:
                    self.assertIn(source["section"], path.read_text(encoding="utf-8"),
                                  f"{entry['id']}: {source['path']}")
                checked += 1
        self.assertGreater(checked, 0)


class NoDecompilerOutputTests(unittest.TestCase):
    """The spec and the model were written clean-room; nothing they ship may carry listing text."""

    FILES = (SPEC_DOC, MODEL_FILE, FIXTURE, Path(__file__).resolve())

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(HOOKS_DIR))
        from decompiled_output import SIGNATURES
        cls.signatures = SIGNATURES

    def _matches(self, text):
        return [what for pattern, what in self.signatures
                for line in text.splitlines() if pattern.search(line)]

    def test_the_instrument_can_fire(self):
        # Positive control, built at runtime so this file carries no sample.
        ghidra_like = "call " + "FUN" + "_" + "0041a2b3" + "();"
        positional = "x = " + "argu" + "ment" + str(2) + ";"
        self.assertTrue(self._matches(ghidra_like))
        self.assertTrue(self._matches(positional))
        self.assertFalse(self._matches("a rank-3 monster takes about three times the health"))

    def test_no_signature_in_the_new_files(self):
        for path in self.FILES:
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), path)
                self.assertEqual(self._matches(path.read_text(encoding="utf-8")), [], path)

    def test_no_local_decompiler_paths_in_the_new_files(self):
        forbidden = ("hs-" + "decomp", "ghidra" + "_projects")
        for path in self.FILES:
            text = path.read_text(encoding="utf-8")
            for word in forbidden:
                with self.subTest(path=path.name, word=word):
                    self.assertNotIn(word, text, path)
        # Positive control: the same check does see the words when they are there.
        self.assertIn(forbidden[1], "C:/Users/x/" + forbidden[1] + "/HeroSiege")


class SpecTests(unittest.TestCase):
    def test_the_spec_labels_its_claims_and_names_the_model(self):
        spec = SPEC_DOC.read_text(encoding="utf-8")
        for heading in ("Static reading", "Measured", "Not established", "Our code",
                        "The model", "What the model cannot catch"):
            self.assertRegex(spec, re.compile("^## " + heading + "$", re.M))
        for name in ("EnemyRaritySettings", "Enemy_Child_Boss_obj", "DropItem", "monster_rank_model",
                     "boss_follows_rank_table", "monster_rank_measurements.json"):
            self.assertIn(name, spec)


def _function_body(source, signature):
    """The brace-balanced body that follows `signature` in C++ source."""
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"unterminated: {signature}")


@unittest.skipUnless(FORGEPACT_BOSS.is_file() and FORGEPACT_PANEL.is_file(),
                     "ForgePact is not checked out (hub CI checks out without submodules), "
                     "so there is no Bosses source to compare the test transform with")
class LeverParityTests(unittest.TestCase):
    """`force_boss_rank` above is ForgePact's Bosses control; pin it to ForgePact's source."""

    @classmethod
    def setUpClass(cls):
        cls.header = FORGEPACT_BOSS.read_text(encoding="utf-8", errors="replace")
        cls.panel = FORGEPACT_PANEL.read_text(encoding="utf-8-sig", errors="replace")

    def _constant(self, name):
        found = re.search(r"inline constexpr int " + name + r" = (\d+);", self.header)
        self.assertIsNotNone(found, name)
        return int(found.group(1))

    def test_the_tiers_are_the_header_s(self):
        self.assertEqual(self._constant("kRareTier"), FORGEPACT_BOSS_TIERS["rare"])
        self.assertEqual(self._constant("kAncientTier"), FORGEPACT_BOSS_TIERS["ancient"])
        self.assertRegex(self.header, r"enum class Mode : int \{ Off = 0, Rare = 3, Ancient = 4 \};")
        self.assertEqual(self._constant("kRareAffixes"), FORGEPACT_BOSS_AFFIXES[3])
        self.assertEqual(self._constant("kAncientAffixes"), FORGEPACT_BOSS_AFFIXES[4])

    def test_the_decision_is_the_header_s(self):
        decide = _function_body(self.header, "inline int DecideTier(")
        self.assertIn("if (mode == Mode::Off || !isBoss || enemyBorn) return 0;", decide)
        self.assertIn("return enemyRarity == 1.0 ? TierFor(mode) : 0;", decide)

    def test_the_modes_are_the_panel_s(self):
        tree = ast.parse(self.panel)
        values = [ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "BOSS_RARITY_VALUES" for t in node.targets)]
        self.assertEqual(values, [FORGEPACT_BOSS_MODES])


if __name__ == "__main__":
    unittest.main()
