"""Checks for `hs_game_sdk.skill_sliders_model` (ForgePact#160, hub #408).

The model is written from `docs/models/skill-sliders-spec.md` and covers the
game only. ForgePact's `projprobe` levers are research-build code, so they live
here as input transforms (`projprobe_*`); the next workorder's sliders are
pinned against the same transforms. `LeverParityTests` pins them to
ForgePact's source when ForgePact is checked out.

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
        self.assertEqual(model.projectile_delta_speed(8), 8)
        self.assertEqual(model.projectile_delta_speed(8, room_spd=2), 8)

    def test_percent_multiplies_then_flat_adds_times_room_speed(self):
        self.assertEqual(model.projectile_delta_speed(8, percent_element=Fraction(1, 2)), 12)
        self.assertEqual(model.projectile_delta_speed(8, flat_element=2, room_spd=Fraction(1, 2)), 9)
        self.assertEqual(model.projectile_delta_speed(8, percent_element=Fraction(1, 2), flat_element=2), 14)

    def test_a_projectile_with_no_delta_speed_is_not_changed(self):
        self.assertEqual(model.projectile_delta_speed(0, percent_element=1, flat_element=5), 0)
        self.assertEqual(model.projectile_delta_speed(-2, percent_element=1, flat_element=5), -2)

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
        settled = model.projectile_delta_speed(8, percent_element=Fraction(1, 2))
        self.assertEqual(projprobe_speed(settled, 2), 24)

    def test_speed_stat_form_scales_the_stat_before_it_is_stored(self):
        # The stat form doubles stat 75 while LoadAllModifiers reads it, so it
        # doubles the percent element, not the whole speed.
        _, percent = model.stored_speed_elements(0, projprobe_speed(50, 2), 1, Fraction(1, 100))
        self.assertEqual(model.projectile_delta_speed(8, percent_element=percent), 16)
        _, native = model.stored_speed_elements(0, 50, 1, Fraction(1, 100))
        self.assertEqual(model.projectile_delta_speed(8, percent_element=native), 12)

    def test_speed_is_never_slowed_and_capped(self):
        self.assertEqual(projprobe_speed(8, Fraction(1, 2)), 8)
        self.assertEqual(projprobe_speed(8, 10), 8 * PROJPROBE_SPEED_MAX)

    def test_every_lever_at_its_off_value_is_the_baseline(self):
        self.assertEqual(projprobe_amount(5, 0), 5)
        self.assertEqual(projprobe_aoe(40, 0), 40)
        self.assertEqual(projprobe_speed(8, 1), 8)


class MeasuredTests(unittest.TestCase):
    """The model against ForgePact#160 Live 1; rows not `measured` are skipped."""

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
                self.assertEqual(function(**args), Fraction(str(call["observed"])), row["what"])
                checked += 1
        if not checked:
            self.skipTest("no measured row yet (ForgePact#160 Live 1 has not run)")


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
                     "so there is no projprobe source to compare the test transforms with")
class LeverParityTests(unittest.TestCase):
    """The `projprobe_*` transforms above are ForgePact's `projprobe`; pin them to its source."""

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

    def test_a_lever_adds_or_multiplies_after_the_game(self):
        self.assertIn("boosted = native * mul + add;", self.source)
        self.assertIn("ProjProbeAdd(t, r, (double)g_PpAmount)", self.source)
        self.assertIn("ProjProbeAdd(t, r, g_PpAoe)", self.source)
        self.assertIn("ProjProbeAdjust(r, 0.0, g_PpSpeedMult, native, boosted)", self.source)
        self.assertIn('ProjProbeScaleVar(inst, "deltaSpeed", mult, note, delta)', self.source)


if __name__ == "__main__":
    unittest.main()
