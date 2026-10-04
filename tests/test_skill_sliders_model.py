"""Checks for `hs_game_sdk.skill_sliders_model` (ForgePact#160, hub #408).

The model is written from `docs/models/skill-sliders-spec.md` and covers the
game only. ForgePact's levers are its own code, so they live here as input
transforms: the research build's `projprobe` (`projprobe_*`) and the shipped
`skillslider` sliders (`slider_*`). `LeverParityTests` pins both to ForgePact's
source when ForgePact is checked out.

Baseline: what the game does with no mod. Target: what each lever must turn it
into. That is the order `AGENTS.md` § "Mod Development Workflow" asks for.
"""
import json
import math
import re
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
SPEC_DOC = ROOT / "docs" / "models" / "skill-sliders-spec.md"
FIXTURE = ROOT / "hs-game-sdk" / "curated" / "skill_sliders_measurements.json"
FORGEPACT_MAIN = ROOT / "ForgePact" / "plugin" / "ModuleMain.cpp"
SLIDERS_HEADER = ROOT / "ForgePact" / "plugin" / "include" / "ForgePact" / "SkillSlidersMod.hpp"

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import skill_sliders_model as model  # noqa: E402

# ---- ForgePact's research levers, as input transforms (our code, not the game's) ----

#: `projprobe amount` stops at 10, `projprobe aoe` at 300, `projprobe speed` at x4.
PROJPROBE_AMOUNT_MAX = 10
PROJPROBE_AOE_MAX = 300
PROJPROBE_SPEED_MAX = 4


def projprobe_amount(helper_return, k):
    """`projprobe amount <k>`: k, rounded and clamped to 0..10, is added to the
    return of either extra-projectile helper, after the game's own calculation."""
    # std::lround on a value already clamped to 0..10: halves round up.
    k = math.floor(max(Fraction(0), min(Fraction(PROJPROBE_AMOUNT_MAX), Fraction(k))) + Fraction(1, 2))
    return Fraction(helper_return) + k


def projprobe_aoe(stat554_total, bonus):
    """`projprobe aoe <bonus>`: bonus, clamped to 0..300, is added to element 0
    of `StatAOESkillSize`'s result, which is what the dispatcher returns for 554."""
    bonus = max(Fraction(0), min(Fraction(PROJPROBE_AOE_MAX), Fraction(bonus)))
    return Fraction(stat554_total) + bonus


def projprobe_speed(value, mult):
    """`projprobe speed <mult>` (the projectile's `deltaSpeed` after
    `LoadProjectileSettings`) and `projprobe speed stat <id> <mult>` (the stat
    the dispatcher returns inside the speed scope) both multiply, clamped to 1..4."""
    mult = max(Fraction(1), min(Fraction(PROJPROBE_SPEED_MAX), Fraction(mult)))
    return Fraction(value) * mult


#: `projprobe speed stat <id> add <bonus>` stops at 100.
PROJPROBE_SPEED_ADD_MAX = 100


def projprobe_speed_add(value, bonus):
    """`projprobe speed stat <id> add <bonus>`: bonus, clamped to 0..100, is
    added to what the dispatcher returns for the stat inside the speed scope,
    so a stat a character does not carry (0) can still be raised."""
    bonus = max(Fraction(0), min(Fraction(PROJPROBE_SPEED_ADD_MAX), Fraction(bonus)))
    return Fraction(value) + bonus


# ---- ForgePact's shipped sliders (`skillslider`, SkillSlidersMod.hpp), as input transforms ----

#: `skillslider projamount` stops at 5, `aoesize` at 100, `projspeed` at 100.
SLIDER_AMOUNT_MAX = 5
SLIDER_AOE_MAX = 100
SLIDER_SPEED_MAX = 100


def _slider_value(value, ceiling, whole=False):
    """`SkillSlidersMod::Clamp`: not finite or negative is 0; Projectile Amount
    is rounded half up; each is capped at its ceiling."""
    value = Fraction(value)
    if value < 0:
        value = Fraction(0)
    if whole:
        value = Fraction(math.floor(value + Fraction(1, 2)))
    return min(value, Fraction(ceiling))


def slider_amount(helper_return, k, in_scope=True):
    """`skillslider projamount <k>`: for the player's own cast (or its double
    cast), k is added to what either extra-projectile helper returned, after
    the game's own calculation. Any other caller gets the helper's return."""
    return Fraction(helper_return) + (_slider_value(k, SLIDER_AMOUNT_MAX, whole=True) if in_scope else 0)


def slider_aoe(stat554_total, b, in_scope=True):
    """`skillslider aoesize <b>`: for a cast in scope, b is added to element 0
    of `StatAOESkillSize`'s result, the skill AoE stat 554."""
    return Fraction(stat554_total) + (_slider_value(b, SLIDER_AOE_MAX) if in_scope else 0)


def slider_speed(stat75, n, in_scope=True):
    """`skillslider projspeed <n>`: n is added to stat 75 as `ReturnSpecificStat`
    returns it inside the player's own `LoadAllModifiers`, so it reaches the
    stored percent element. Outside that scope stat 75 is the game's."""
    return Fraction(stat75) + (_slider_value(n, SLIDER_SPEED_MAX) if in_scope else 0)


class BaselineTests(unittest.TestCase):
    """The game with no mod: the spec's static reading, as numbers."""

    def test_the_stat_ids_and_elements(self):
        self.assertEqual(model.AOE_SKILL_SIZE_STAT_ID, 554)
        self.assertEqual((model.SPELL_PROJECTILES_PERCENT_STAT_ID, model.SPELL_PROJECTILES_FLAT_STAT_ID), (394, 311))
        self.assertEqual((model.RANGED_PROJECTILES_FLAT_STAT_ID, model.RANGED_ONE_MORE_CHANCE_STAT_ID,
                          model.RANGED_BONUS_CHANCE_STAT_ID, model.RANGED_BONUS_STAT_ID), (239, 240, 451, 452))
        self.assertEqual((model.PROJECTILE_SPEED_FLAT_STAT_ID, model.PROJECTILE_SPEED_PERCENT_STAT_ID), (74, 75))
        self.assertEqual((model.SPEED_FLAT_ELEMENT, model.SPEED_PERCENT_ELEMENT, model.AOE_SCALE_ELEMENT),
                         (1084, 1085, 1086))
        self.assertEqual(model.PER_POINT, Fraction(1, 100))

    def test_no_stats_leaves_a_spell_skills_base(self):
        self.assertEqual(model.spell_projectile_total(3), 3)
        # A non-whole base is only floored when the percent stat applies.
        self.assertEqual(model.spell_projectile_total(Fraction(5, 2)), Fraction(5, 2))

    def test_the_percent_stat_raises_the_base_and_floors_it(self):
        self.assertEqual(model.spell_projectile_total(3, more_percent=50), 4)    # 4.5 -> 4
        self.assertEqual(model.spell_projectile_total(3, more_percent=100), 6)
        self.assertEqual(model.spell_projectile_total(1, more_percent=99), 1)    # 1.99 -> 1

    def test_the_flat_stat_is_added_after_the_floor(self):
        self.assertEqual(model.spell_projectile_total(3, more_percent=50, extra=2), 6)
        self.assertEqual(model.spell_projectile_total(3, extra=1), 4)

    def test_a_negative_percent_is_ignored(self):
        self.assertEqual(model.spell_projectile_total(3, more_percent=-50), 3)

    def test_the_ranged_helper_returns_the_extra_only(self):
        self.assertEqual(model.ranged_extra_projectiles(0), 0)
        self.assertEqual(model.ranged_extra_projectiles(2), 2)
        self.assertEqual(model.ranged_projectile_total(1, model.ranged_extra_projectiles(2)), 3)

    def test_the_ranged_rolls_count_only_when_they_succeed(self):
        self.assertEqual(model.ranged_extra_projectiles(1, bonus=3), 1)
        self.assertEqual(model.ranged_extra_projectiles(1, bonus=3, bonus_rolled=True), 4)
        self.assertEqual(model.ranged_extra_projectiles(1, one_more_rolled=True), 2)
        self.assertEqual(model.ranged_extra_projectiles(1, bonus=3, bonus_rolled=True, one_more_rolled=True), 5)

    def test_aoe_is_a_hundredth_per_point_times_the_factor(self):
        self.assertEqual(model.aoe_scale_bonus(0), 0)
        self.assertEqual(model.aoe_scale_bonus(100), 1)
        self.assertEqual(model.aoe_scale_bonus(50, factor=2), 1)
        self.assertEqual(model.aoe_scale_bonus(10, also=(20, 30)), Fraction(6, 10))

    def test_aoe_is_added_to_the_scale_only_when_above_zero(self):
        self.assertEqual(model.projectile_scale(1, 0), 1)
        self.assertEqual(model.projectile_scale(1, Fraction(-1, 2)), 1)
        self.assertEqual(model.projectile_scale(1, model.aoe_scale_bonus(100)), 2)
        self.assertEqual(model.projectile_scale(Fraction(3, 2), model.aoe_scale_bonus(25)), Fraction(7, 4))

    def test_no_speed_stats_leaves_delta_speed(self):
        for order in model.SPEED_ORDERS:
            with self.subTest(order=order):
                self.assertEqual(model.projectile_delta_speed(8, order=order), 8)
                self.assertEqual(model.projectile_delta_speed(8, room_spd=2, order=order), 8)

    def test_percent_multiplies_and_flat_adds_times_room_speed(self):
        for order in model.SPEED_ORDERS:
            with self.subTest(order=order):
                self.assertEqual(model.projectile_delta_speed(8, percent_element=Fraction(1, 2), order=order), 12)
                self.assertEqual(model.projectile_delta_speed(8, flat_element=2, room_spd=Fraction(1, 2), order=order), 9)

    def test_speed_elements_apply_only_while_delta_speed_is_above_zero(self):
        # Static reading (spec, RUNTIME_DATA_MODELS 7.6): both elements act only
        # while deltaSpeed is above 0, so a still object keeps 0. The positive
        # control beside it is the same call on a moving object.
        both = dict(percent_element=Fraction(1, 2), flat_element=2, room_spd=Fraction(5, 12))
        for order in model.SPEED_ORDERS:
            with self.subTest(order=order):
                self.assertEqual(model.projectile_delta_speed(0, order=order, **both), 0)
                self.assertEqual(model.projectile_delta_speed(0, flat_element=2, room_spd=1, order=order), 0)
                self.assertGreater(model.projectile_delta_speed(Fraction(35, 12), order=order, **both),
                                   Fraction(35, 12))

    def test_the_order_matters_only_when_both_apply_and_is_a_parameter(self):
        # The order was not measured (the sessions raised one stat at a time), so it has no default.
        both = dict(percent_element=Fraction(1, 2), flat_element=2)
        self.assertEqual(model.projectile_delta_speed(8, order="multiply_first", **both), 14)
        self.assertEqual(model.projectile_delta_speed(8, order="add_first", **both), 15)
        with self.assertRaises(TypeError):
            model.projectile_delta_speed(8, **both)
        with self.assertRaises(ValueError):
            model.projectile_delta_speed(8, order="sideways", **both)

    def test_the_ranged_extra_is_a_sum_of_its_parts(self):
        # Each part counts on its own; none depends on another.
        for bonus_rolled in (False, True):
            for one_more_rolled in (False, True):
                with self.subTest(bonus_rolled=bonus_rolled, one_more_rolled=one_more_rolled):
                    self.assertEqual(model.ranged_extra_projectiles(2, bonus=3, bonus_rolled=bonus_rolled,
                                                                    one_more_rolled=one_more_rolled),
                                     2 + (3 if bonus_rolled else 0) + (1 if one_more_rolled else 0))

    def test_the_stored_speed_scale_is_a_parameter(self):
        self.assertEqual(model.stored_speed_elements(3, 50, 1, Fraction(1, 100)), (3, Fraction(1, 2)))
        with self.assertRaises(TypeError):
            model.stored_speed_elements(3, 50)   # no default: the scale was not read


class TargetTests(unittest.TestCase):
    """What each research lever must turn the baseline into."""

    def test_amount_adds_k_projectiles_to_either_helper(self):
        spell = model.spell_projectile_total(3, more_percent=50)
        self.assertEqual(projprobe_amount(spell, 2), spell + 2)
        ranged = model.ranged_extra_projectiles(1)
        self.assertEqual(model.ranged_projectile_total(1, projprobe_amount(ranged, 2)), 4)

    def test_amount_adds_after_the_floor_not_before(self):
        # +1 after the game's floor of 3 x 1.5 is 5; the same +1 on the base
        # before it would have been floor(4 x 1.5) = 6.
        self.assertEqual(projprobe_amount(model.spell_projectile_total(3, more_percent=50), 1), 5)
        self.assertEqual(model.spell_projectile_total(4, more_percent=50), 6)

    def test_amount_is_whole_and_capped(self):
        self.assertEqual(projprobe_amount(3, Fraction(26, 10)), 6)
        self.assertEqual(projprobe_amount(3, Fraction(5, 2)), 6)
        self.assertEqual(projprobe_amount(3, 50), 3 + PROJPROBE_AMOUNT_MAX)
        self.assertEqual(projprobe_amount(3, -2), 3)

    def test_aoe_bonus_reaches_the_scale_additively(self):
        native = 40
        boosted = projprobe_aoe(native, 100)
        self.assertEqual(boosted, 140)
        before = model.projectile_scale(1, model.aoe_scale_bonus(native))
        after = model.projectile_scale(1, model.aoe_scale_bonus(boosted))
        self.assertEqual(after - before, 1)

    def test_aoe_bonus_is_capped(self):
        self.assertEqual(projprobe_aoe(0, 1000), PROJPROBE_AOE_MAX)
        self.assertEqual(projprobe_aoe(10, -5), 10)

    def test_speed_instance_form_scales_the_settled_delta_speed(self):
        for order in model.SPEED_ORDERS:
            with self.subTest(order=order):
                settled = model.projectile_delta_speed(8, percent_element=Fraction(1, 2), order=order)
                self.assertEqual(projprobe_speed(settled, 2), 24)

    def test_speed_stat_form_scales_the_stat_before_it_is_stored(self):
        # The stat form doubles stat 75 while LoadAllModifiers reads it, so it
        # doubles the percent element, not the whole speed.
        for order in model.SPEED_ORDERS:
            with self.subTest(order=order):
                _, percent = model.stored_speed_elements(0, projprobe_speed(50, 2), 1, Fraction(1, 100))
                self.assertEqual(model.projectile_delta_speed(8, percent_element=percent, order=order), 16)
                _, native = model.stored_speed_elements(0, 50, 1, Fraction(1, 100))
                self.assertEqual(model.projectile_delta_speed(8, percent_element=native, order=order), 12)

    def test_speed_stat_form_multiplier_cannot_raise_a_zero_stat_but_add_can(self):
        # A character with no projectile-speed gear reads 0 for stat 75. The
        # multiplier leaves it 0 (negative control); the additive form moves it.
        _, multiplied = model.stored_speed_elements(0, projprobe_speed(0, 2), 1, Fraction(1, 100))
        self.assertEqual(model.projectile_delta_speed(8, percent_element=multiplied, order="multiply_first"), 8)
        _, added = model.stored_speed_elements(0, projprobe_speed_add(0, 50), 1, Fraction(1, 100))
        self.assertEqual(model.projectile_delta_speed(8, percent_element=added, order="multiply_first"), 12)

    def test_speed_is_never_slowed_and_capped(self):
        self.assertEqual(projprobe_speed(8, Fraction(1, 2)), 8)
        self.assertEqual(projprobe_speed(8, 10), 8 * PROJPROBE_SPEED_MAX)
        self.assertEqual(projprobe_speed_add(0, -5), 0)
        self.assertEqual(projprobe_speed_add(0, 1000), PROJPROBE_SPEED_ADD_MAX)

    def test_every_lever_at_its_off_value_is_the_baseline(self):
        self.assertEqual(projprobe_amount(5, 0), 5)
        self.assertEqual(projprobe_aoe(40, 0), 40)
        self.assertEqual(projprobe_speed(8, 1), 8)
        self.assertEqual(projprobe_speed_add(8, 0), 8)


class SliderBaselineTests(unittest.TestCase):
    """The shipped sliders off, or met by a caller out of scope: the game's own value."""

    def test_every_slider_at_zero_is_the_baseline(self):
        spell = model.spell_projectile_total(3, more_percent=50)
        self.assertEqual(slider_amount(spell, 0), spell)
        self.assertEqual(slider_amount(model.ranged_extra_projectiles(1), 0), 1)
        self.assertEqual(slider_aoe(40, 0), 40)
        self.assertEqual(slider_speed(50, 0), 50)

    def test_a_caller_out_of_scope_gets_the_game_value(self):
        # The mercenary, enemies and basic attacks: whatever the slider is set to.
        for value in (1, 5, 100):
            with self.subTest(value=value):
                self.assertEqual(slider_amount(4, value, in_scope=False), 4)
                self.assertEqual(slider_aoe(40, value, in_scope=False), 40)
                self.assertEqual(slider_speed(50, value, in_scope=False), 50)
                self.assertEqual(slider_speed(0, value, in_scope=False), 0)

    def test_speed_off_leaves_delta_speed(self):
        _, percent = model.stored_speed_elements(0, slider_speed(0, 0), 1, Fraction(1, 100))
        for order in model.SPEED_ORDERS:
            with self.subTest(order=order):
                self.assertEqual(model.projectile_delta_speed(Fraction(35, 12), percent_element=percent,
                                                              order=order), Fraction(35, 12))


class SliderTargetTests(unittest.TestCase):
    """What each shipped slider must turn the baseline into, for the player's own cast."""

    def test_amount_adds_k_projectiles_to_either_helper(self):
        spell = model.spell_projectile_total(3, more_percent=50)
        self.assertEqual(slider_amount(spell, 2), spell + 2)
        ranged = model.ranged_extra_projectiles(1)
        self.assertEqual(model.ranged_projectile_total(1, slider_amount(ranged, 2)), 4)

    def test_amount_adds_after_the_floor_not_before(self):
        # +1 after the game's floor of 3 x 1.5 is 5; on the base it would be 6.
        self.assertEqual(slider_amount(model.spell_projectile_total(3, more_percent=50), 1), 5)
        self.assertEqual(model.spell_projectile_total(4, more_percent=50), 6)

    def test_amount_is_whole_and_capped(self):
        self.assertEqual(slider_amount(3, Fraction(26, 10)), 6)
        self.assertEqual(slider_amount(3, Fraction(5, 2)), 6)      # halves round up
        self.assertEqual(slider_amount(3, Fraction(12, 5)), 5)
        self.assertEqual(slider_amount(3, 50), 3 + SLIDER_AMOUNT_MAX)
        self.assertEqual(slider_amount(3, -2), 3)

    def test_aoe_bonus_reaches_the_scale_additively(self):
        native = 40
        boosted = slider_aoe(native, 50)
        self.assertEqual(boosted, 90)
        before = model.projectile_scale(1, model.aoe_scale_bonus(native))
        after = model.projectile_scale(1, model.aoe_scale_bonus(boosted))
        self.assertEqual(after - before, Fraction(50, 100))

    def test_aoe_raises_a_character_with_no_aoe_stat(self):
        # Added after the game, so a 0 (no AoE gear) still moves: +b/100 on the scale.
        self.assertEqual(model.projectile_scale(1, model.aoe_scale_bonus(slider_aoe(0, 100))), 2)

    def test_aoe_is_capped(self):
        self.assertEqual(slider_aoe(0, 1000), SLIDER_AOE_MAX)
        self.assertEqual(slider_aoe(10, -5), 10)

    def test_speed_adds_to_stat_75_before_it_is_stored(self):
        # Live 2: +50 on stat 75 took a 35/12 deltaSpeed to 4.375 = 35/8.
        _, percent = model.stored_speed_elements(0, slider_speed(0, 50), 1, Fraction(1, 100))
        for order in model.SPEED_ORDERS:
            with self.subTest(order=order):
                self.assertEqual(model.projectile_delta_speed(Fraction(35, 12), percent_element=percent,
                                                              order=order), Fraction(35, 8))

    def test_speed_stacks_on_the_characters_own_stat(self):
        _, percent = model.stored_speed_elements(0, slider_speed(50, 50), 1, Fraction(1, 100))
        self.assertEqual(model.projectile_delta_speed(8, percent_element=percent, order="multiply_first"), 16)

    def test_speed_is_never_slowed_and_capped(self):
        self.assertEqual(slider_speed(0, -5), 0)
        self.assertEqual(slider_speed(0, 1000), SLIDER_SPEED_MAX)
        self.assertEqual(slider_speed(20, 1000), 20 + SLIDER_SPEED_MAX)


#: The levers (research and shipped) a measured row may apply to the model's result.
LEVERS = {"projprobe_amount": projprobe_amount, "projprobe_aoe": projprobe_aoe,
          "projprobe_speed": projprobe_speed, "projprobe_speed_add": projprobe_speed_add,
          "slider_amount": slider_amount, "slider_aoe": slider_aoe, "slider_speed": slider_speed}


class MeasuredTests(unittest.TestCase):
    """The model against ForgePact#160's live sessions; rows not `measured` are skipped."""

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.rows = cls.data["measurements"]

    def test_the_fixture_has_its_shape(self):
        self.assertIn("$schema_note", self.data)
        self.assertIsInstance(self.rows, list)
        ids = [row["id"] for row in self.rows]
        self.assertEqual(len(ids), len(set(ids)), "duplicate row ids")

    def _measured(self):
        for row in self.rows:
            if row.get("status") == "measured":
                yield row

    def test_every_measured_row_names_a_real_section_and_script(self):
        from hs_game_sdk.scripts import GameScript
        for row in self._measured():
            with self.subTest(row=row["id"]):
                self.assertIn(row["kind"], ("baseline", "target"))
                for source in row["source"]:
                    path = ROOT / source["path"]
                    self.assertTrue(path.is_file(), source["path"])
                    self.assertIn(source["section"], path.read_text(encoding="utf-8"))
                for script in row["scripts"]:
                    self.assertIn(script, GameScript.__members__)

    def test_every_measured_row_agrees_with_the_model(self):
        checked = 0
        for row in self._measured():
            call = row.get("model")
            if not call:
                continue
            with self.subTest(row=row["id"]):
                function = getattr(model, call["function"])
                args = {key: Fraction(str(value)) if isinstance(value, (int, float)) else value
                        for key, value in call["args"].items()}
                result = function(**args)
                lever = call.get("lever")
                if lever:
                    # Our code, not the game's: the lever acts on the game's result.
                    result = LEVERS[lever["transform"]](result, Fraction(str(lever["value"])))
                miss = abs(result - Fraction(str(call["observed"])))
                self.assertLessEqual(miss, Fraction(str(call.get("tolerance", 0))), row["what"])
                checked += 1
        if not checked:
            self.skipTest("no measured row with a model call")

    def test_the_tolerance_is_a_printing_allowance_not_a_fit(self):
        # Negative control: a tolerance only covers the capture's six printed
        # decimals, so a row whose model is off by a real amount still fails.
        for row in self._measured():
            call = row.get("model") or {}
            with self.subTest(row=row["id"]):
                self.assertLessEqual(Fraction(str(call.get("tolerance", 0))), Fraction(1, 10 ** 6))
        self.assertGreater(abs(model.projectile_delta_speed(Fraction(35, 12), percent_element=Fraction(1, 100),
                                                            order="multiply_first") - Fraction("2.93125")),
                           Fraction(1, 10 ** 6))

    def test_the_measured_rows_cover_each_lever(self):
        functions = {row["model"]["function"] for row in self._measured() if row.get("model")}
        for name in ("spell_projectile_total", "aoe_scale_bonus", "projectile_scale", "projectile_delta_speed"):
            self.assertIn(name, functions)


class NoDecompilerOutputTests(unittest.TestCase):
    """The spec and the model were written clean-room; nothing they ship may carry listing text."""

    FILES = (SPEC_DOC, SDK_PY / "hs_game_sdk" / "skill_sliders_model.py", Path(__file__).resolve())

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
        self.assertFalse(self._matches("the scale is raised by the element when it is above 0"))

    def test_no_signature_in_the_skill_sliders_files(self):
        for path in self.FILES:
            with self.subTest(path=path.name):
                self.assertEqual(self._matches(path.read_text(encoding="utf-8")), [])


class SpecTests(unittest.TestCase):
    def test_the_spec_labels_its_claims_and_names_the_model(self):
        spec = SPEC_DOC.read_text(encoding="utf-8")
        for heading in ("## Static reading", "## Measured", "## Our code", "## Not established",
                        "## The model", "## What the model cannot catch"):
            self.assertIn("\n" + heading + "\n", spec)
        self.assertIn("skill_sliders_model.py", spec)
        for name in ("ReturnSpecificStat", "StatAOESkillSize", "ReturnExtraSpellProjectiles",
                     "ReturnExtraProjectilesRanged", "LoadProjectileSettings", "LoadAllModifiers",
                     "deltaSpeed", "1086"):
            self.assertIn(name, spec)

    def test_every_function_the_spec_names_exists(self):
        spec = SPEC_DOC.read_text(encoding="utf-8")
        section = spec[spec.index("\n## The model\n"):spec.index("\n## What the model cannot catch\n")]
        names = re.findall(r"^- `([a-z_0-9]+)\(", section, re.MULTILINE)
        self.assertGreaterEqual(len(names), 7)
        for name in names:
            self.assertTrue(callable(getattr(model, name, None)), name)


@unittest.skipUnless(FORGEPACT_MAIN.is_file(),
                     "ForgePact is not checked out (hub CI checks out without submodules), "
                     "so there is no projprobe or skillslider source to compare the test transforms with")
class LeverParityTests(unittest.TestCase):
    """The `projprobe_*` and `slider_*` transforms above are ForgePact's
    `projprobe` and `skillslider`; pin them to its source."""

    @classmethod
    def setUpClass(cls):
        cls.source = FORGEPACT_MAIN.read_text(encoding="utf-8", errors="replace")

    def test_the_clamps(self):
        self.assertRegex(self.source, r"ProjProbeClampAmount\(double k\)\s*\{\s*return \(int\)std::lround\("
                                      rf"std::clamp\(k, 0\.0, {PROJPROBE_AMOUNT_MAX}\.0\)\);")
        self.assertRegex(self.source, rf"ProjProbeClampAoe\(double bonus\)\s*\{{\s*return std::clamp\("
                                      rf"bonus, 0\.0, {PROJPROBE_AOE_MAX}\.0\);")
        self.assertRegex(self.source, rf"ProjProbeClampSpeed\(double mult\)\s*\{{\s*return std::clamp\("
                                      rf"mult, 1\.0, {PROJPROBE_SPEED_MAX}\.0\);")
        self.assertRegex(self.source, rf"ProjProbeClampSpeedAdd\(double bonus\)\s*\{{\s*return std::clamp\("
                                      rf"bonus, 0\.0, {PROJPROBE_SPEED_ADD_MAX}\.0\);")

    def test_a_lever_adds_or_multiplies_after_the_game(self):
        self.assertIn("boosted = native * mul + add;", self.source)
        self.assertIn("ProjProbeAdd(t, r, (double)g_PpAmount)", self.source)
        self.assertIn("ProjProbeAdd(t, r, g_PpAoe)", self.source)
        self.assertIn("ProjProbeAdjust(r, 0.0, g_PpSpeedMult, native, boosted)", self.source)
        self.assertIn("ProjProbeAdjust(r, g_PpSpeedAdd, 1.0, native, boosted)", self.source)
        self.assertIn('ProjProbeScaleVar(inst, "deltaSpeed", mult, note, delta)', self.source)

    # ---- the shipped sliders: the `slider_*` transforms against SkillSlidersMod.hpp ----

    def _sliders(self):
        if not SLIDERS_HEADER.is_file():
            self.skipTest("SkillSlidersMod.hpp is not in this ForgePact checkout")
        return SLIDERS_HEADER.read_text(encoding="utf-8", errors="replace")

    def test_the_slider_ceilings_and_stat(self):
        source = self._sliders()
        self.assertRegex(source, rf"kProjAmountMax = {SLIDER_AMOUNT_MAX}\.0;")
        self.assertRegex(source, rf"kAoeSizeMax = {SLIDER_AOE_MAX}\.0;")
        self.assertRegex(source, rf"kProjSpeedMax = {SLIDER_SPEED_MAX}\.0;")
        self.assertRegex(source, rf"kProjectileSpeedStatId = {model.PROJECTILE_SPEED_PERCENT_STAT_ID}\.0;")

    def test_the_slider_clamp(self):
        # _slider_value: negative (or not finite) is 0, the whole lever rounds half up, then the cap.
        source = self._sliders()
        self.assertIn("if (!std::isfinite(v) || v < 0.0) v = 0.0;", source)
        self.assertIn("if (info.whole) v = std::floor(v + 0.5);", source)
        self.assertIn("if (v > info.max) v = info.max;", source)
        self.assertRegex(source, r'\{ "projamount", \{ kSpell, kRanged \}, 2, kProjAmountMax, true \}')
        self.assertRegex(source, r'\{ "aoesize", \{ kAoe, kAoe \}, 1, kAoeSizeMax, false \}')
        self.assertRegex(source, r'\{ "projspeed", \{ kLoadMods, kSpecificStat \}, 2, kProjSpeedMax, false \}')

    def test_a_slider_adds_after_the_game_and_only_in_scope(self):
        source = self._sliders()
        # The original runs first; the value is added to what it returned.
        self.assertEqual(source.count("RValue& r = orig ? orig(S, O, R, argc, A) : R;"), 2)
        self.assertIn("r = RValue(native + value);", source)
        self.assertIn("RValue(0.0), RValue(native + value) });", source)
        # Amount and AoE: in scope by the call's own self; speed: stat 75 inside the player's scope.
        self.assertIn("if (InScope(state, S)) Boost(r, value, state, script);", source)
        self.assertIn("if (!t_SpeedScope) return r;", source)
        self.assertIn("id != kProjectileSpeedStatId) return r;", source)
        self.assertIn("inScope = mod.InScope(state, S);", source)


if __name__ == "__main__":
    unittest.main()
