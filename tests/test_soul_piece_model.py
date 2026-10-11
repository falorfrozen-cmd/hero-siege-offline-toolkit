"""Checks for `hs_game_sdk.soul_piece_model` (ForgePact#197, boss soul pieces).

The model is written from `docs/models/soul-piece-spec.md` and covers the game
only: `RoomActIndex` gives a room its act, and `DropGems` rolls the Gem of
Incarnation against its rate once per dying source whose drop type 6 gate
passed. ForgePact's boss soul pieces are our code, so they live here as input
transforms (`piece_denominator`, `decide_drop`, `decide_use`, `veto_stack` and
the seed helpers): a piece rolls inside that same gem roll at five quarters of
the gem's chance, in an act's ordinary rooms, from an ordinary monster.
`ParityTests` pins those transforms' constants, the act table, the room rules
and the verdict words to `SoulPieceMod.hpp` through the curated file, when
ForgePact carries the mod.

Baseline: what the game does with the mod off. Target: what the mod must turn
it into. That is the order `AGENTS.md` § "Mod Development Workflow" asks for.
`CuratedTests` checks `hs-game-sdk/curated/room_acts.json` and
`hs-game-sdk/curated/boss_soul_pieces.json` against the SDK's own tables.

Run from the hub root: `py -3 -m unittest tests.test_soul_piece_model -v`.
"""
import ast
import json
import math
import re
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
CURATED = ROOT / "hs-game-sdk" / "curated" / "boss_soul_pieces.json"
ROOM_ACTS = ROOT / "hs-game-sdk" / "curated" / "room_acts.json"
MODEL_FILE = SDK_PY / "hs_game_sdk" / "soul_piece_model.py"
SPEC_DOC = ROOT / "docs" / "models" / "soul-piece-spec.md"
RUNTIME_DOC = ROOT / "docs" / "RUNTIME_DATA_MODELS.md"
HOOKS_DIR = ROOT / ".claude" / "hooks"
FORGEPACT_HEADER = ROOT / "ForgePact" / "plugin" / "include" / "ForgePact" / "SoulPieceMod.hpp"

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import soul_piece_model as model  # noqa: E402
from hs_game_sdk.objects import OBJECT_NAME_TO_INDEX, is_descendant_of  # noqa: E402
from hs_game_sdk.rooms import ROOM_NAME_TO_INDEX  # noqa: E402
from hs_game_sdk.scripts import GameScript  # noqa: E402

DATA = json.loads(CURATED.read_text(encoding="utf-8"))
ROOMS = json.loads(ROOM_ACTS.read_text(encoding="utf-8"))

# ---- ForgePact's boss soul pieces, as input transforms (our code, not the game's) ----

RATIO_NUMERATOR = 4
RATIO_DENOMINATOR = 5
SEED_BASE = 777100
ACT_COUNT = 9
DROP_VERDICTS = ("off", "no-act", "town", "boss-room", "not-monster", "boss-kill",
                 "unnamed", "no-rate", "hit", "miss")
USE_VERDICTS = ("off", "town", "not-piece", "unnamed", "summon")
#: act -> (boss object, named); every shipped act is named.
ACTS = {row["act"]: (row["boss_object"], row["named"]) for row in DATA["acts"]}


def piece_denominator(gem_rate):
    """D = max(1, floor(G x 4 / 5)); 0 (no piece) when G is unknown, zero or negative."""
    if gem_rate is None or gem_rate <= 0:
        return 0
    return max(1, math.floor(Fraction(gem_rate) * RATIO_NUMERATOR / RATIO_DENOMINATOR))


def piece_chance(gem_rate):
    """The piece's chance on one `DropGems` call: 1 in D, 0 without a rate."""
    d = piece_denominator(gem_rate)
    return Fraction(1, d) if d else Fraction(0)


def is_town(room):
    return room.startswith("Town_")


def is_boss_room(room):
    return "_Boss" in room or room.startswith("Uber_") or room.startswith("Dev_")


def room_refusal(room, act):
    """The word that refuses a room for drops, `None` when it is eligible."""
    if not 1 <= act <= ACT_COUNT:
        return "no-act"
    if is_town(room):
        return "town"
    if is_boss_room(room):
        return "boss-room"
    return None


def decide_drop(mod_on, forced, room, act, monster, boss, gem_rate, roll):
    """One `DropGems` call for a dying source; `roll` is uniform in [0, 1)."""
    if not mod_on:
        return "off"
    refusal = room_refusal(room, act)
    if refusal:
        return refusal
    if not monster:
        return "not-monster"
    if boss:
        return "boss-kill"
    if not ACTS.get(act, (None, False))[1]:
        return "unnamed"
    if forced:
        return "hit"
    d = piece_denominator(gem_rate)
    if not d:
        return "no-rate"
    return "hit" if Fraction(roll) < Fraction(1, d) else "miss"


def seed_of_act(act):
    return SEED_BASE + act if 1 <= act <= ACT_COUNT else 0


def act_of_seed(seed):
    act = seed - SEED_BASE
    return act if 1 <= act <= ACT_COUNT else 0


def decide_use(mod_on, room, piece_act):
    """A right-click on an item in the backpack; allowed in any room but a town."""
    if not mod_on:
        return "off"
    if is_town(room):
        return "town"
    if not 1 <= piece_act <= ACT_COUNT:
        return "not-piece"
    if not ACTS.get(piece_act, (None, False))[1]:
        return "unnamed"
    return "summon"


def veto_stack(mod_on, seed_a, seed_b):
    """Consulted only after the game said the two stack: veto while on when
    exactly one is a piece or the pieces' acts differ."""
    return bool(mod_on) and act_of_seed(seed_a) != act_of_seed(seed_b)


def _roll(value):
    """A case's roll as an exact fraction of its written decimal."""
    return Fraction(str(value))


def _cases(kind):
    return [c for c in DATA["cases"] if c["kind"] == kind]


def _drop(case, **override):
    c = dict(case, **override)
    return decide_drop(c["mod_on"], c["forced"], c["room"], c["act"], c["monster"], c["boss"],
                       c["gem_rate"], _roll(c["roll"]))


def _table_rooms():
    return {row["room"]: row["act"] for row in ROOMS["rooms"]}


class BaselineTests(unittest.TestCase):
    """The game with the mod off: acts, the gem roll, and no piece at all."""

    def test_mod_off_never_drops(self):
        for room, act in _table_rooms().items():
            for forced in (False, True):
                for roll in (Fraction(0), Fraction(1, 10 ** 6), Fraction(1, 2)):
                    with self.subTest(room=room, forced=forced, roll=roll):
                        self.assertEqual(decide_drop(False, forced, room, act, True, False, 10000, roll), "off")
        for case in _cases("drop"):
            with self.subTest(case=case["id"]):
                self.assertEqual(_drop(case, mod_on=False), "off")

    def test_mod_off_never_summons_or_vetoes(self):
        for act in range(1, ACT_COUNT + 1):
            with self.subTest(act=act):
                self.assertEqual(decide_use(False, "Act_01_01", act), "off")
                self.assertFalse(veto_stack(False, seed_of_act(act), seed_of_act(act % ACT_COUNT + 1)))

    def test_room_act_index_answers_the_act_minus_one(self):
        self.assertEqual([model.act_of_room(i) for i in range(9)], list(range(1, 10)))
        self.assertIsNone(model.act_of_room(None))
        for bad in (-1, 9, True):
            with self.subTest(bad=bad):
                with self.assertRaises((ValueError, TypeError)):
                    model.act_of_room(bad)

    def test_the_gem_is_one_in_its_rate(self):
        for rate in (9000, 10000, 11000):
            with self.subTest(rate=rate):
                self.assertEqual(model.gem_chance(rate), Fraction(1, rate))
        for unknown in (None, 0, -5):
            with self.subTest(unknown=unknown):
                self.assertIsNone(model.gem_chance(unknown))
        with self.assertRaises(TypeError):
            model.gem_chance(10000.0)

    def test_expected_gems_are_linear_in_the_rolls(self):
        chance = model.gem_chance(10000)
        self.assertEqual(model.expected_drops(0, chance), 0)
        self.assertEqual(model.expected_drops(10000, chance), 1)
        self.assertEqual(model.expected_drops(30000, chance), 3 * model.expected_drops(10000, chance))
        self.assertEqual(model.expected_drops(50, None), 0)
        with self.assertRaises(ValueError):
            model.expected_drops(-1, chance)

    def test_every_hypothesis_is_none_until_measured(self):
        answered = {q["hypothesis"] for q in DATA["open_questions"] if q["status"] == "measured"}
        for key, value in model.HYPOTHESES.items():
            with self.subTest(key=key):
                if key not in answered:
                    self.assertIsNone(value)
        self.assertEqual({q["hypothesis"] for q in DATA["open_questions"]}, set(model.HYPOTHESES))


class TargetTests(unittest.TestCase):
    """What the mod turns it into: a piece rolled inside the gem roll."""

    def test_piece_is_a_quarter_more_common_than_the_gem(self):
        for rate in (9000, 10000, 11000, 9001, 10003, 2, 7):
            with self.subTest(rate=rate):
                gem = model.gem_chance(rate)
                piece = piece_chance(rate)
                self.assertGreater(piece, gem)
                d = piece_denominator(rate)
                if rate % RATIO_DENOMINATOR == 0:
                    self.assertEqual(piece / gem, Fraction(RATIO_DENOMINATOR, RATIO_NUMERATOR))
                elif rate >= RATIO_DENOMINATOR:
                    # floor() only rounds D down: the ratio overshoots 5/4 by under 5/(4D),
                    # and the piece's chance stays within 1/G of five quarters of the gem's.
                    over = piece / gem - Fraction(RATIO_DENOMINATOR, RATIO_NUMERATOR)
                    self.assertGreaterEqual(over, 0)
                    self.assertLess(over, Fraction(RATIO_DENOMINATOR, RATIO_NUMERATOR * d))
                    self.assertLess(abs(piece - gem * Fraction(5, 4)), gem)
        self.assertEqual(piece_denominator(DATA["gem"]["expected_rate"]), 8000)
        self.assertEqual(piece_denominator(1), 1)

    def test_more_gem_rolls_give_more_pieces(self):
        chance = piece_chance(10000)
        expected = [model.expected_drops(n, chance) for n in (0, 8000, 16000, 80000)]
        self.assertEqual(expected, [0, 1, 2, 10])
        # A lever that lowers the gem's rate lowers D with it: more pieces per roll.
        self.assertGreater(piece_chance(5000), piece_chance(10000))
        # The share of pieces to gems is the same whatever the number of rolls.
        for n in (1000, 123457):
            with self.subTest(rolls=n):
                self.assertEqual(model.expected_drops(n, chance) / model.expected_drops(n, model.gem_chance(10000)),
                                 Fraction(5, 4))

    def test_boss_kill_town_and_boss_room_never_drop(self):
        for room, act in _table_rooms().items():
            for forced in (False, True):
                with self.subTest(room=room, forced=forced):
                    verdict = decide_drop(True, forced, room, act, True, False, 10000, Fraction(0))
                    if is_town(room):
                        self.assertEqual(verdict, "town")
                    elif is_boss_room(room):
                        self.assertEqual(verdict, "boss-room")
                    else:
                        self.assertEqual(verdict, "hit")
                        self.assertEqual(decide_drop(True, forced, room, act, True, True, 10000, Fraction(0)),
                                         "boss-kill")
        for room in (r["room"] for r in ROOMS["not_in_table"]):
            with self.subTest(room=room):
                self.assertEqual(decide_drop(True, True, room, 0, True, False, 10000, Fraction(0)), "no-act")

    def test_non_monster_source_never_drops(self):
        for forced in (False, True):
            for boss in (False, True):
                with self.subTest(forced=forced, boss=boss):
                    self.assertEqual(decide_drop(True, forced, "Act_01_01", 1, False, boss, 10000, Fraction(0)),
                                     "not-monster")

    def test_unknown_gem_rate_never_drops(self):
        for rate in (None, 0, -1, Fraction(-1, 2)):
            for roll in (Fraction(0), Fraction(1, 10 ** 9)):
                with self.subTest(rate=rate, roll=roll):
                    self.assertEqual(piece_denominator(rate), 0)
                    self.assertEqual(decide_drop(True, False, "Act_02_01", 2, True, False, rate, roll), "no-rate")
        # Forcing replaces the chance, never the rules before it.
        self.assertEqual(decide_drop(True, True, "Act_02_01", 2, True, False, None, Fraction(0)), "hit")

    def test_force_overrides_only_the_chance(self):
        self.assertEqual(DATA["force_overrides"], ["no-rate", "hit", "miss"])
        for case in _cases("drop"):
            plain = _drop(case, forced=False)
            forced = _drop(case, forced=True)
            with self.subTest(case=case["id"]):
                if plain in DATA["force_overrides"]:
                    self.assertEqual(forced, "hit")
                else:
                    self.assertEqual(forced, plain)

    def test_the_roll_hits_below_one_in_d_only(self):
        d = piece_denominator(10000)
        self.assertEqual(decide_drop(True, False, "Act_01_01", 1, True, False, 10000, Fraction(1, d) - Fraction(1, 10 ** 12)), "hit")
        self.assertEqual(decide_drop(True, False, "Act_01_01", 1, True, False, 10000, Fraction(1, d)), "miss")

    def test_every_act_drops_and_summons_in_its_ordinary_rooms(self):
        rooms = _table_rooms()
        for act in range(1, ACT_COUNT + 1):
            eligible = [r for r, a in rooms.items() if a == act and room_refusal(r, a) is None]
            with self.subTest(act=act):
                self.assertTrue(eligible)
                self.assertEqual(decide_use(True, eligible[0], act), "summon")

    def test_use_is_refused_only_in_town_and_when_off(self):
        for room in ("Act_01_01", "Act_01_Boss", "Act_02_Boss_Dungeon_01", "Uber_Inoya_rm"):
            with self.subTest(room=room):
                self.assertEqual(decide_use(True, room, 1), "summon")
        self.assertEqual(decide_use(True, "Town_01_rm", 1), "town")
        self.assertEqual(decide_use(True, "Act_01_01", 0), "not-piece")

    def test_seeds_round_trip_and_stay_clear_of_other_items(self):
        for act in range(1, ACT_COUNT + 1):
            with self.subTest(act=act):
                self.assertEqual(act_of_seed(seed_of_act(act)), act)
        for seed in (SEED_BASE, SEED_BASE + ACT_COUNT + 1, *DATA["reserved_seeds"]):
            with self.subTest(seed=seed):
                self.assertEqual(act_of_seed(seed), 0)
        self.assertEqual(seed_of_act(0), 0)
        self.assertEqual(seed_of_act(ACT_COUNT + 1), 0)

    def test_stack_veto_keeps_acts_and_keys_apart_only_while_on(self):
        for act in range(1, ACT_COUNT + 1):
            with self.subTest(act=act):
                self.assertFalse(veto_stack(True, seed_of_act(act), seed_of_act(act)))
                self.assertTrue(veto_stack(True, seed_of_act(act), 4242))
                self.assertTrue(veto_stack(True, 4242, seed_of_act(act)))
        self.assertFalse(veto_stack(True, 4242, 4343))

    def test_the_shared_cases(self):
        for case in DATA["cases"]:
            with self.subTest(case=case["id"]):
                if case["kind"] == "drop":
                    self.assertEqual(_drop(case), case["verdict"])
                elif case["kind"] == "use":
                    self.assertEqual(decide_use(case["mod_on"], case["room"], act_of_seed(case["seed"])),
                                     case["verdict"])
                    if "boss_object" in case:
                        self.assertEqual(ACTS[act_of_seed(case["seed"])][0], case["boss_object"])
                else:
                    self.assertEqual(case["kind"], "stack")
                    self.assertEqual(veto_stack(case["mod_on"], case["seed_a"], case["seed_b"]), case["veto"])
        verdicts = {c["verdict"] for c in DATA["cases"] if c["kind"] == "drop"}
        # Every drop verdict but `unnamed` (unreachable with the shipped table) has a case.
        self.assertEqual(set(DROP_VERDICTS) - verdicts, {"unnamed"})
        self.assertEqual(set(USE_VERDICTS) - {c["verdict"] for c in _cases("use")}, {"unnamed"})


class CuratedTests(unittest.TestCase):
    """The two curated files agree with the SDK's tables and with each other."""

    def test_schema_note_comes_first(self):
        for path in (CURATED, ROOM_ACTS):
            with self.subTest(path=path.name):
                self.assertEqual(next(iter(json.loads(path.read_text(encoding="utf-8")))), "$schema_note")

    def test_room_acts_match_the_sdk_rooms(self):
        rows = ROOMS["rooms"]
        self.assertEqual(len(rows), 175)
        self.assertEqual(len({r["room"] for r in rows}), 175)
        for row in rows:
            with self.subTest(room=row["room"]):
                self.assertEqual(ROOM_NAME_TO_INDEX.get(row["room"]), row["index"])
                self.assertIn(row["act"], range(1, ACT_COUNT + 1))
                self.assertEqual(row["status"], "static_reading")
        # § 21.1's rows per act, 1 to 9.
        per_act = [sum(1 for r in rows if r["act"] == act) for act in range(1, ACT_COUNT + 1)]
        self.assertEqual(per_act, [21, 24, 16, 15, 14, 20, 17, 19, 29])
        # A room's name does not always give its act.
        self.assertEqual(_table_rooms()["Act_08_Orres_Lair_rm"], 4)
        self.assertNotIn("Town_08_rm", _table_rooms())
        self.assertNotIn("Unstable_Rift_08_04", ROOM_NAME_TO_INDEX)
        for row in ROOMS["not_in_table"]:
            with self.subTest(not_in_table=row["room"]):
                self.assertEqual(ROOM_NAME_TO_INDEX.get(row["room"]), row["index"])
                self.assertNotIn(row["room"], _table_rooms())
        self.assertTrue(hasattr(GameScript, ROOMS["script"]))

    def test_bosses_descend_from_the_boss_parent(self):
        boss_parent = OBJECT_NAME_TO_INDEX[DATA["boss_parent"]]
        monster_parent = OBJECT_NAME_TO_INDEX[DATA["monster_parent"]]
        self.assertEqual([row["act"] for row in DATA["acts"]], list(range(1, ACT_COUNT + 1)))
        for row in DATA["acts"]:
            with self.subTest(act=row["act"], boss=row["boss_object"]):
                index = OBJECT_NAME_TO_INDEX.get(row["boss_object"])
                self.assertEqual(index, row["object_index"])
                self.assertTrue(is_descendant_of(index, boss_parent))
                self.assertTrue(is_descendant_of(index, monster_parent))
                self.assertTrue(row["named"])
                self.assertTrue(row["piece_name"].startswith("Piece of "))
                self.assertEqual(row["seed"], DATA["seed_base"] + row["act"])
        self.assertEqual(DATA["acts"][6]["boss_object"], "Mevius_obj")

    def test_each_act_says_what_its_boss_rests_on(self):
        statuses = {row["act"]: row["status"] for row in DATA["acts"]}
        self.assertEqual(statuses[7], "owner_named")
        self.assertEqual({statuses[a] for a in (4, 5)}, {"inference"})
        for act in (1, 2, 3, 6, 8, 9):
            with self.subTest(act=act):
                self.assertIn(statuses[act], ("static_reading", "measured"))
        runtime = RUNTIME_DOC.read_text(encoding="utf-8")
        for row in DATA["acts"]:
            path, _, section = row["source"].partition(" § ")
            with self.subTest(act=row["act"]):
                self.assertTrue((ROOT / path).is_file())
                self.assertIn(section, runtime)

    def test_the_gem_rate_is_marked_unverified_with_its_source(self):
        gem = DATA["gem"]
        self.assertEqual(gem["repository_name"], "socketable_gem_of_incarnation")
        self.assertEqual((gem["category"], gem["item_type"], gem["b"]), (15, 15, 136))
        self.assertEqual(gem["expected_rate"], 10000)
        if not model.HYPOTHESES["gem_rate_is_10000"]:
            self.assertEqual(gem["rate_status"], "unverified")
        path, _, section = gem["rate_source"].partition(" § ")
        self.assertIn(section, (ROOT / path).read_text(encoding="utf-8"))
        self.assertEqual((DATA["ratio"]["numerator"], DATA["ratio"]["denominator"]),
                         (RATIO_NUMERATOR, RATIO_DENOMINATOR))

    def test_the_rules_and_words_are_the_transforms(self):
        self.assertEqual(tuple(DATA["drop_verdicts"]), DROP_VERDICTS)
        self.assertEqual(tuple(DATA["use_verdicts"]), USE_VERDICTS)
        self.assertEqual(DATA["seed_base"], SEED_BASE)
        rules = DATA["room_rules"]
        self.assertEqual(rules["town_prefixes"], {"Town_": "town"})
        self.assertEqual(rules["boss_room_prefixes"], {"Uber_": "boss-room", "Dev_": "boss-room"})
        self.assertEqual(rules["boss_room_substrings"], {"_Boss": "boss-room"})
        self.assertEqual(rules["no_act"], "no-act")

    def test_the_game_scripts_are_the_sdks(self):
        for name in ("gml_Script_RoomActIndex", "gml_Script_DropGems", "gml_Script_LoadDrops",
                     "gml_Script_ItemsAreStackable", "gml_Script_GetNormalRepoStruct",
                     "gml_Script_UiAInventoryConsumeItemConfirm", "gml_Script_PotionUse",
                     "gml_Script_GetDropRate_anon_55737_s_ItemBaseDefinition_DefineStructs"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(GameScript, name))


class NoDecompilerOutputTests(unittest.TestCase):
    """The spec, the model and the curated files were written clean-room."""

    FILES = (SPEC_DOC, MODEL_FILE, CURATED, ROOM_ACTS, Path(__file__).resolve())

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
        self.assertFalse(self._matches("a piece rolls inside the gem roll"))

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
        positions = [spec.find("\n## " + heading + "\n") for heading in
                     ("Static reading", "Measured", "Not established", "Our code",
                      "The model", "What the model cannot catch")]
        self.assertTrue(min(positions) >= 0 and positions == sorted(positions), positions)
        for name in ("RoomActIndex", "DropGems", "GetDropRate", "LoadDrops",
                     "socketable_gem_of_incarnation", "Enemy_Child_Boss_obj", "Enemy_Parent_obj",
                     "Mevius_obj", "soul_piece_model", "boss_soul_pieces.json", "room_acts.json",
                     "max(1, floor(G × 4 / 5))", *model.HYPOTHESES):
            with self.subTest(name=name):
                self.assertIn(name, spec)

    def test_the_model_stays_small_and_stdlib_only(self):
        source = MODEL_FILE.read_text(encoding="utf-8")
        self.assertLess(len(source.splitlines()), 120)
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, {"__future__", "fractions", "typing"})


@unittest.skipUnless(FORGEPACT_HEADER.is_file(),
                     "ForgePact does not carry SoulPieceMod.hpp (hub CI checks out without "
                     "submodules, or the mod has not landed), so there is no source to compare "
                     "the curated file and the test transforms with")
class ParityTests(unittest.TestCase):
    """The curated file and the transforms above are SoulPieceMod.hpp's; pin them to it."""

    @classmethod
    def setUpClass(cls):
        header = FORGEPACT_HEADER.read_text(encoding="utf-8", errors="replace")
        cls.code = re.sub(r"//[^\n]*", "", header)

    def _constant(self, name):
        found = re.search(r"\b%s(?:\[\])?\s*=\s*([^;]+);" % re.escape(name), self.code)
        self.assertIsNotNone(found, name)
        return found.group(1).strip()

    def _words(self, name):
        found = re.search(r"\b%s\[\]\s*=\s*\{(.*?)\};" % re.escape(name), self.code, re.S)
        self.assertIsNotNone(found, name)
        return re.findall(r'"([^"]*)"', found.group(1))

    def test_header_matches_the_curated_file(self):
        self.assertEqual(int(self._constant("kActCount")), ACT_COUNT)
        self.assertEqual(int(self._constant("kSeedBase")), DATA["seed_base"])
        self.assertEqual(int(self._constant("kRatioNumerator")), DATA["ratio"]["numerator"])
        self.assertEqual(int(self._constant("kRatioDenominator")), DATA["ratio"]["denominator"])
        self.assertEqual(int(self._constant("kExpectedGemRate")), DATA["gem"]["expected_rate"])
        self.assertEqual(int(self._constant("kGemCategory")), DATA["gem"]["category"])
        self.assertEqual(self._constant("kGemRepoName"), '"%s"' % DATA["gem"]["repository_name"])
        self.assertEqual(int(self._constant("kKeyCategory")), DATA["key_category"])
        self.assertEqual(float(self._constant("kSpawnOffsetPx")), DATA["spawn_offset_px"])
        self.assertEqual(self._constant("kMechanicTag"), '"%s"' % DATA["mechanic_tag"])

    def test_the_act_table_is_the_header_s(self):
        table = re.search(r"kActs\[kActCount\]\s*=\s*\{(.*?)\n\};", self.code, re.S)
        self.assertIsNotNone(table)
        rows = re.findall(r'\{\s*(\d+)\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*(true|false)\s*\}', table.group(1))
        self.assertEqual(
            [(int(a), boss, name, named == "true") for a, boss, name, named in rows],
            [(r["act"], r["boss_object"], r["piece_name"], r["named"]) for r in DATA["acts"]])

    def test_the_verdict_words_are_the_header_s(self):
        self.assertEqual(self._words("kDropVerdictWords"), DATA["drop_verdicts"])
        self.assertEqual(self._words("kUseVerdictWords"), DATA["use_verdicts"])

    def test_the_room_rules_are_the_header_s(self):
        town = re.search(r"IsTownRoom\([^)]*\)\s*\{(.*?)\}", self.code, re.S).group(1)
        self.assertEqual(re.findall(r'starts_with\("([^"]+)"\)', town), list(DATA["room_rules"]["town_prefixes"]))
        boss = re.search(r"IsBossRoom\([^)]*\)\s*\{(.*?)\n\}", self.code, re.S).group(1)
        self.assertEqual(re.findall(r'find\("([^"]+)"\)', boss), list(DATA["room_rules"]["boss_room_substrings"]))
        self.assertEqual(re.findall(r'starts_with\("([^"]+)"\)', boss), list(DATA["room_rules"]["boss_room_prefixes"]))

    def test_the_denominator_floors_four_fifths_of_the_gem_rate(self):
        body = re.search(r"PieceDenominator\(double gemRate\)\s*\{(.*?)\n\}", self.code, re.S).group(1)
        self.assertRegex(body, r"if\s*\(\s*!\(\s*gemRate\s*>\s*0\.0\s*\)\s*\)\s*return 0;")
        self.assertRegex(body, r"std::floor\(\s*gemRate\s*\*[^;]*kRatioNumerator[^;]*/[^;]*kRatioDenominator")
        self.assertRegex(body, r"d\s*<\s*1\.0\s*\?\s*1")
