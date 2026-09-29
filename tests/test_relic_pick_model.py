"""Checks for `hs_game_sdk.relic_pick_model` (ForgePact#125, hub #324).

The model is written from `docs/models/relic-pick-spec.md` and covers the game
only. ForgePact's lever for #125 is our code, so it lives here as an input
transform (`forgepact_quest`). `LeverParityTests` pins that transform to
ForgePact's source when ForgePact is checked out.

Baseline: what the game does with no mod. Target: what the lever must turn it
into. That is the order `AGENTS.md` § "Mod Development Workflow" asks for.
"""
import re
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
SPEC_DOC = ROOT / "docs" / "models" / "relic-pick-spec.md"
FORGEPACT = ROOT / "ForgePact"
FORGEPACT_PLUGIN = FORGEPACT / "plugin" / "ModuleMain.cpp"
FORGEPACT_RELIC_FILTER = FORGEPACT / "plugin" / "include" / "ForgePact" / "RelicFilterMod.hpp"

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import relic_pick_model as model  # noqa: E402

DROPPABLE = tuple(range(model.QUEST_RELIC_FIRST))    # 0..140
QUEST = tuple(range(model.QUEST_RELIC_FIRST, model.RELIC_ID_COUNT))
# `irandom(100) < 3`, if zrm were 100: an illustration, not a measurement.
SOME_COPY_CHANCE = model.copy_chance(3, 100)


# ---- ForgePact's lever, as an input transform (our code, not the game's) ----

def forgepact_quest(quest, maxed):
    """ForgePact#125: `GetRelicQuest` also answers true for a relic the player
    owns at 10/10, so the game's own loop draws again. It stands down, and
    answers as the game does, when no relic id would be left, because the loop
    would then never end."""
    quest, maxed = frozenset(quest), frozenset(maxed)
    left = [i for i in range(model.RELIC_ID_COUNT) if i not in quest and i not in maxed]
    return quest | maxed if left else quest


class BaselineTests(unittest.TestCase):
    """The game with no mod: the spec's static reading, as numbers."""

    def test_the_pick_is_uniform_over_the_141_relics_that_are_not_quest_relics(self):
        dist = model.pick_distribution()
        self.assertEqual(sorted(dist), list(DROPPABLE))
        self.assertEqual(set(dist.values()), {Fraction(1, 141)})

    def test_quest_relics_never_come_out_of_the_pick(self):
        self.assertEqual(model.quest_relic_ids(), frozenset(QUEST))
        dist = model.pick_distribution(equipped=[(31, 6)], copy_chance=SOME_COPY_CHANCE)
        self.assertFalse(set(dist) & set(QUEST))

    def test_the_distribution_sums_to_one(self):
        for equipped in ((), [(31, 6), (15, 5), None, (135, 3), (16, 6)], [(140, 10)] * 5):
            with self.subTest(equipped=equipped):
                dist = model.pick_distribution(equipped=equipped, copy_chance=SOME_COPY_CHANCE)
                self.assertEqual(sum(dist.values()), 1)

    def test_an_equipped_relic_below_ten_gets_a_copy_share(self):
        dist = model.pick_distribution(equipped=[(31, 6)], copy_chance=SOME_COPY_CHANCE)
        share = SOME_COPY_CHANCE / 5
        self.assertEqual(dist[31], (1 - share) * Fraction(1, 141) + share)
        self.assertEqual(dist[30], (1 - share) * Fraction(1, 141))

    def test_the_game_never_copies_an_equipped_relic_at_ten(self):
        # The copy step's own `o < 10`: a 10/10 relic reads as an empty slot.
        maxed_equipped = model.pick_distribution(equipped=[(140, 10)], copy_chance=SOME_COPY_CHANCE)
        nothing_equipped = model.pick_distribution()
        self.assertEqual(maxed_equipped, nothing_equipped)

    def test_the_issue_125_relic_still_drops_at_its_uniform_rate(self):
        # Relic 140, equipped at 10/10: with no working lever it comes out of
        # the uniform pick like any other relic, 1 in 141 relic drops.
        dist = model.pick_distribution(equipped=[(140, 10), (31, 8), (68, 8), (92, 5)],
                                       copy_chance=SOME_COPY_CHANCE)
        copies = 3 * SOME_COPY_CHANCE / 5
        self.assertEqual(dist[140], (1 - copies) * Fraction(1, 141))

    def test_the_satanic_kill_routine_has_no_copy_step(self):
        self.assertEqual(model.COPY_BOUNDS["EnemyKillSatanicZoneRelic"], ())
        self.assertEqual(model.pick_distribution(equipped=[(31, 6)], copy_chance=0),
                         model.pick_distribution())

    def test_copy_bounds_per_routine(self):
        self.assertEqual(model.COPY_BOUNDS["DropRelic"], (3, 6, 10))
        self.assertEqual(model.COPY_BOUNDS["EnemyKillSatanicZoneRelicFeast"], (3, 5, 8))

    def test_copy_chance_is_the_share_of_draws_below_the_bound(self):
        self.assertEqual(model.copy_chance(3, 100), Fraction(3, 101))
        self.assertEqual(model.copy_chance(10, 100), Fraction(10, 101))
        self.assertEqual(model.copy_chance(10, 4), 1)          # every draw is below the bound
        self.assertEqual(model.copy_chance(0, 100), 0)

    def test_an_empty_pool_is_the_endless_loop(self):
        with self.assertRaises(ValueError):
            model.pick_pool(range(model.RELIC_ID_COUNT))

    def test_bad_inputs_are_refused(self):
        with self.assertRaises(ValueError):
            model.pick_distribution(equipped=[None] * 6)
        with self.assertRaises(ValueError):
            model.pick_distribution(copy_chance=2)
        with self.assertRaises(ValueError):
            model.copy_chance(3, -1)


class TargetTests(unittest.TestCase):
    """What the #125 lever must produce, through the game's own pick."""

    def test_a_maxed_relic_never_comes_out(self):
        quest = forgepact_quest(model.quest_relic_ids(), {140, 7})
        dist = model.pick_distribution(quest, equipped=[(140, 10)], copy_chance=SOME_COPY_CHANCE)
        self.assertNotIn(140, dist)
        self.assertNotIn(7, dist)

    def test_every_other_relic_stays_equally_likely(self):
        dist = model.pick_distribution(forgepact_quest(model.quest_relic_ids(), {140, 7}))
        self.assertEqual(len(dist), 139)
        self.assertEqual(set(dist.values()), {Fraction(1, 139)})

    def test_a_maxed_relic_in_the_relic_tab_is_held_back_and_an_equipped_one_below_ten_is_still_copied(self):
        quest = forgepact_quest(model.quest_relic_ids(), {40})
        dist = model.pick_distribution(quest, equipped=[(31, 6)], copy_chance=SOME_COPY_CHANCE)
        self.assertNotIn(40, dist)
        share = SOME_COPY_CHANCE / 5
        self.assertEqual(dist[31], (1 - share) * Fraction(1, 140) + share)

    def test_quest_relics_stay_out(self):
        dist = model.pick_distribution(forgepact_quest(model.quest_relic_ids(), {1, 2, 3}))
        self.assertFalse(set(dist) & set(QUEST))

    def test_the_last_relic_left_takes_every_pick(self):
        maxed = set(DROPPABLE) - {7}
        self.assertEqual(model.pick_distribution(forgepact_quest(model.quest_relic_ids(), maxed)),
                         {7: Fraction(1)})

    def test_the_lever_stands_down_when_every_droppable_relic_is_maxed(self):
        quest = forgepact_quest(model.quest_relic_ids(), set(DROPPABLE))
        self.assertEqual(quest, model.quest_relic_ids())
        self.assertEqual(model.pick_distribution(quest), model.pick_distribution())

    def test_the_lever_off_is_the_baseline(self):
        self.assertEqual(model.pick_distribution(forgepact_quest(model.quest_relic_ids(), set())),
                         model.pick_distribution())


class NoDecompilerOutputTests(unittest.TestCase):
    """The spec and the model were written clean-room; nothing they ship may carry listing text."""

    FILES = (SPEC_DOC, SDK_PY / "hs_game_sdk" / "relic_pick_model.py", Path(__file__).resolve())

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
        from decompiled_output import SIGNATURES
        cls.signatures = SIGNATURES

    def _matches(self, text):
        return [what for pattern, what in self.signatures
                for line in text.splitlines() if pattern.search(line)]

    def test_the_instrument_can_fire(self):
        # Positive control, built at runtime so this file carries no sample.
        positional = "x = " + "argu" + "ment" + str(4) + ";"
        self.assertTrue(self._matches(positional))
        self.assertFalse(self._matches("the pick draws again while the quest check answers true"))

    def test_no_signature_in_the_relic_model_files(self):
        for path in self.FILES:
            with self.subTest(path=path.name):
                self.assertEqual(self._matches(path.read_text(encoding="utf-8")), [])


class SpecTests(unittest.TestCase):
    def test_the_spec_labels_its_claims_and_names_the_model(self):
        spec = SPEC_DOC.read_text(encoding="utf-8")
        for heading in ("## Static reading", "## Measured", "## Our code", "## Not established",
                        "## The model", "## What the model cannot catch"):
            self.assertIn("\n" + heading + "\n", spec)
        self.assertIn("relic_pick_model.py", spec)
        self.assertIn("GetRelicQuest", spec)
        self.assertIn("inventoryRelicGrid", spec)


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


@unittest.skipUnless(FORGEPACT_PLUGIN.is_file() and FORGEPACT_RELIC_FILTER.is_file(),
                     "ForgePact is not checked out (hub CI checks out without submodules), "
                     "so there is no lever source to compare the test transform with")
class LeverParityTests(unittest.TestCase):
    """`forgepact_quest` above is ForgePact's lever; pin it to ForgePact's source."""

    @classmethod
    def setUpClass(cls):
        cls.plugin = FORGEPACT_PLUGIN.read_text(encoding="utf-8", errors="replace")
        cls.header = FORGEPACT_RELIC_FILTER.read_text(encoding="utf-8", errors="replace")

    def test_the_answer_is_the_games_or_true_for_a_maxed_relic_while_one_is_left(self):
        answer = _function_body(self.header, "static bool QuestAnswer(")
        self.assertRegex(answer, r"if\s*\(\s*gameAnswer\s*\)\s*return\s+true\s*;")
        self.assertRegex(answer, r"return\s+relicLeft\s*&&\s*maxed\.count\(\s*id\s*\)\s*!=\s*0\s*;")

    def test_a_relic_is_left_only_if_one_is_neither_quest_nor_maxed(self):
        left = _function_body(self.header, "static bool AnyRelicLeft(")
        self.assertRegex(left, r"for\s*\(\s*int\s+id\s*=\s*0\s*;\s*id\s*<\s*kRelicPickIdCount\s*;")
        self.assertIn("isQuest(id)", left)
        self.assertIn("maxed.count(id)", left)
        self.assertRegex(self.header, rf"kRelicPickIdCount\s*=\s*{model.RELIC_ID_COUNT}\s*;")

    def test_the_hook_asks_the_game_first_and_steps_aside_for_afk_farm_rewards(self):
        hook = _function_body(self.plugin, "static RValue& Hook_GetRelicQuest(")
        self.assertIn("HeroSiege::RewardScope::Active()", hook)
        self.assertIn("g_Orig_GetRelicQuest(", hook)
        self.assertIn("QuestAnswer(", hook)
