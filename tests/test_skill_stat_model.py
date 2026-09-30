"""Checks for `hs_game_sdk.skill_stat_model` (ForgePact#114, hub #337).

The model is written from `docs/models/skill-stat-spec.md` and covers the game
only. ForgePact's `statadd` boosts are our code, so they live here as input
transforms (`forgepact_statadd`). `LeverParityTests` pins those transforms to
ForgePact's source when ForgePact is checked out.

Baseline: what the game does with no mod. Target: what the boosts must turn it
into. That is the order `AGENTS.md` § "Mod Development Workflow" asks for.
"""
import math
import re
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
SPEC_DOC = ROOT / "docs" / "models" / "skill-stat-spec.md"
FORGEPACT = ROOT / "ForgePact"
FORGEPACT_STATS = FORGEPACT / "plugin" / "include" / "ForgePact" / "StatsManager.hpp"
FORGEPACT_PANEL = FORGEPACT / "src" / "forgepact.py"

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import skill_stat_model as model  # noqa: E402

#: Stat Forge measured a native Skill Haste of 12 on 7.0.5.0 (2026-08-29).
NATIVE_HASTE = 12
#: The largest Skill Haste one item of the game's own gives (Divine Crackpipe).
LARGEST_ITEM_HASTE = 150

# ---- ForgePact's boosts, as input transforms (our code, not the game's) ----

#: `statadd allskills` stops here (ForgePact's kAllSkillsMax).
FORGEPACT_ALL_SKILLS_MAX = 100
#: The panel's Skill Haste ceiling: the cap, reachable from no haste at all.
FORGEPACT_SKILL_HASTE_MAX = 200


def forgepact_statadd(native_total, bonus, whole=False, cap=None):
    """ForgePact#114: `statadd` adds its bonus to element 0 of the stat's result,
    after the game's own calculation, so gear and buffs still count under it. A
    negative bonus is 0; All Skills is rounded to whole levels and capped."""
    bonus = max(Fraction(bonus), Fraction(0))
    if whole:
        bonus = Fraction(math.floor(bonus + Fraction(1, 2)))
    if cap is not None:
        bonus = min(bonus, Fraction(cap))
    return Fraction(native_total) + bonus


def forgepact_all_skills(native_total, bonus):
    return forgepact_statadd(native_total, bonus, whole=True, cap=FORGEPACT_ALL_SKILLS_MAX)


class BaselineTests(unittest.TestCase):
    """The game with no mod: the spec's static reading, as numbers."""

    def test_no_haste_recovers_one_unit_a_step(self):
        self.assertEqual(model.recovery_rate(0), 1)
        self.assertEqual(model.cooldown_fraction(0), 1)
        self.assertEqual(model.cooldown_steps(2400, 0), 2400)

    def test_half_a_percent_per_point(self):
        self.assertEqual(model.SKILL_HASTE_PER_POINT, Fraction(1, 200))
        self.assertEqual(model.recovery_rate(NATIVE_HASTE), Fraction(53, 50))
        self.assertEqual(model.cooldown_fraction(NATIVE_HASTE), Fraction(50, 53))

    def test_the_largest_item_takes_a_cooldown_to_four_sevenths(self):
        self.assertEqual(model.cooldown_fraction(LARGEST_ITEM_HASTE), Fraction(4, 7))

    def test_the_game_counts_at_most_200(self):
        self.assertEqual(model.SKILL_HASTE_CAP, 200)
        self.assertEqual(model.effective_haste(340), 200)
        self.assertEqual(model.effective_haste(160), 160)
        self.assertEqual(model.recovery_rate(500), 2)
        self.assertEqual(model.cooldown_fraction(1000), Fraction(1, 2))

    def test_delta_speed_scales_every_step(self):
        self.assertEqual(model.cooldown_steps(2400, 0, delta_spd=2), 1200)
        self.assertEqual(model.cooldown_steps(2400, 200, delta_spd=Fraction(1, 2)), 2400)

    def test_a_cooldown_that_is_already_over_takes_no_step(self):
        self.assertEqual(model.cooldown_steps(0, 50), 0)
        self.assertEqual(model.cooldown_steps(-3, 50), 0)

    def test_a_partial_last_step_still_counts(self):
        self.assertEqual(model.cooldown_steps(10, 100), 7)   # 10 / 1.5 = 6.67

    def test_all_skills_counts_only_on_a_talent_with_points(self):
        self.assertEqual(model.talent_level(1), 1)
        self.assertEqual(model.talent_level(3, all_skills=2), 5)
        self.assertEqual(model.talent_level(0, all_skills=5), 0)

    def test_bonuses_count_only_when_the_caller_asks_for_them(self):
        self.assertEqual(model.talent_level(3, all_skills=2, include_bonuses=False), 3)
        self.assertEqual(model.talent_level(3, all_skills=2, other_bonus=1), 6)

    def test_there_is_no_clamp_at_twenty(self):
        self.assertEqual(model.talent_level(20, all_skills=15), 35)

    def test_the_stat_ids(self):
        self.assertEqual((model.SKILL_HASTE_STAT_ID, model.ALL_SKILLS_STAT_ID,
                          model.FASTER_CAST_RATE_STAT_ID), (103, 2, 106))

    def test_nonsense_is_refused(self):
        with self.assertRaises(ValueError):
            model.cooldown_fraction(-200)
        with self.assertRaises(ValueError):
            model.cooldown_steps(10, 0, delta_spd=0)
        with self.assertRaises(ValueError):
            model.talent_level(-1)


class TargetTests(unittest.TestCase):
    """What ForgePact's `statadd` must turn the baseline into."""

    def test_stat_forges_measured_total_is_what_the_cooldown_sees(self):
        haste = forgepact_statadd(NATIVE_HASTE, 100)
        self.assertEqual(haste, 112)
        self.assertEqual(model.cooldown_fraction(haste), Fraction(25, 39))

    def test_a_boost_shortens_every_cooldown_by_the_same_factor(self):
        for base in (600, 2400, 5760):
            with self.subTest(base=base):
                before = model.cooldown_steps(base, NATIVE_HASTE)
                after = model.cooldown_steps(base, forgepact_statadd(NATIVE_HASTE, 100))
                self.assertAlmostEqual(after / before, float(Fraction(106, 156)), delta=2 / before)

    def test_a_boost_past_the_cap_changes_nothing(self):
        at_cap = model.cooldown_steps(2400, forgepact_statadd(NATIVE_HASTE, 200 - NATIVE_HASTE))
        for bonus in (200, 300, 500):
            with self.subTest(bonus=bonus):
                self.assertEqual(model.cooldown_steps(2400, forgepact_statadd(NATIVE_HASTE, bonus)), at_cap)

    def test_the_slider_ceiling_is_the_cap(self):
        # From no Skill Haste at all, the panel's ceiling reaches the cap:
        # a cooldown takes half its time.
        self.assertEqual(model.cooldown_fraction(forgepact_statadd(0, FORGEPACT_SKILL_HASTE_MAX)), Fraction(1, 2))
        self.assertGreater(model.cooldown_steps(2400, forgepact_statadd(0, FORGEPACT_SKILL_HASTE_MAX)), 0)

    def test_all_skills_19_takes_a_one_point_talent_to_20(self):
        # Stat Forge's default: one point in every skill plus 19 shows 20,
        # and a +2 All Skills item on top makes it 22.
        self.assertEqual(model.talent_level(1, forgepact_all_skills(0, 19)), 20)
        self.assertEqual(model.talent_level(1, forgepact_all_skills(2, 19)), 22)

    def test_all_skills_never_unlocks_a_talent(self):
        self.assertEqual(model.talent_level(0, forgepact_all_skills(0, 100)), 0)

    def test_all_skills_is_whole_and_capped(self):
        self.assertEqual(forgepact_all_skills(0, Fraction(196, 10)), 20)
        self.assertEqual(forgepact_all_skills(0, Fraction(194, 10)), 19)
        self.assertEqual(forgepact_all_skills(0, 250), 100)
        self.assertEqual(forgepact_all_skills(3, -5), 3)

    def test_a_zero_bonus_is_the_baseline(self):
        self.assertEqual(forgepact_statadd(NATIVE_HASTE, 0), NATIVE_HASTE)
        self.assertEqual(model.talent_level(4, forgepact_all_skills(2, 0)), model.talent_level(4, 2))


FIXTURE = ROOT / "hs-game-sdk" / "curated" / "skill_stat_measurements.json"


class MeasuredTests(unittest.TestCase):
    """The model against ForgePact#114 Live 1 (2026-09-30)."""

    #: A step count is read off a live counter, and the frame rate wobbles
    #: (58-60 fps while measuring), so a prediction is held to 2.5%.
    TOLERANCE = 0.025

    @classmethod
    def setUpClass(cls):
        import json
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.entries = {entry["id"]: entry for entry in data["measurements"]}
        s1 = cls.entries["S1"]["values"]
        # The base, in steps, from the baseline runs: reads x recovery rate.
        cls.native = s1["native_haste"]
        cls.base = sum(s1["reads"]) / len(s1["reads"]) * float(model.recovery_rate(cls.native))

    def test_every_source_names_a_real_section_and_script(self):
        from hs_game_sdk.scripts import GameScript
        for entry in self.entries.values():
            for source in entry["source"]:
                path = ROOT / source["path"]
                self.assertTrue(path.is_file(), f"{entry['id']}: {source['path']}")
                self.assertIn(source["section"], path.read_text(encoding="utf-8"), entry["id"])
            for script in entry["scripts"]:
                self.assertIn(script, GameScript.__members__, f"{entry['id']}: {script}")

    def test_s1_the_base_is_about_eight_seconds_of_steps(self):
        # abilityCooldown 8 s at 60 steps/s is 480; the cast itself takes a little.
        self.assertTrue(440 <= self.base <= 480, self.base)
        self.assertEqual(self.entries["S1"]["values"]["idle_reads"], 0)

    def test_s2_each_boosted_run_matches_the_capped_formula(self):
        for run in self.entries["S2"]["values"]["runs"]:
            with self.subTest(total=run["total"]):
                self.assertEqual(run["total"], self.native + run["bonus"])
                predicted = self.base / float(model.recovery_rate(run["total"]))
                self.assertLess(abs(run["reads"] - predicted) / predicted, self.TOLERANCE,
                                (run, predicted))

    def test_s2_past_200_the_uncapped_formula_is_wrong(self):
        for run in self.entries["S2"]["values"]["runs"]:
            if run["total"] <= model.SKILL_HASTE_CAP:
                continue
            with self.subTest(total=run["total"]):
                uncapped = self.base / (1 + run["total"] / 200)
                self.assertGreater(abs(run["reads"] - uncapped) / uncapped, 0.08, (run, uncapped))


class NoDecompilerOutputTests(unittest.TestCase):
    """The spec and the model were written clean-room; nothing they ship may carry listing text."""

    FILES = (SPEC_DOC, SDK_PY / "hs_game_sdk" / "skill_stat_model.py", Path(__file__).resolve())

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
        self.assertFalse(self._matches("each step lowers the time left by the recovery rate"))

    def test_no_signature_in_the_skill_stat_files(self):
        for path in self.FILES:
            with self.subTest(path=path.name):
                self.assertEqual(self._matches(path.read_text(encoding="utf-8")), [])


class SpecTests(unittest.TestCase):
    def test_the_spec_labels_its_claims_and_names_the_model(self):
        spec = SPEC_DOC.read_text(encoding="utf-8")
        for heading in ("## Static reading", "## Measured", "## Our code", "## Not established",
                        "## The model", "## What the model cannot catch"):
            self.assertIn("\n" + heading + "\n", spec)
        self.assertIn("skill_stat_model.py", spec)
        for name in ("ReturnSpecificStat", "StatSpellHaste", "StatAllSkills", "ReturnTalentLevel", "0.005"):
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


@unittest.skipUnless(FORGEPACT_STATS.is_file() and FORGEPACT_PANEL.is_file(),
                     "ForgePact is not checked out (hub CI checks out without submodules), "
                     "so there is no statadd source to compare the test transforms with")
class LeverParityTests(unittest.TestCase):
    """`forgepact_statadd` above is ForgePact's `statadd`; pin it to ForgePact's source."""

    @classmethod
    def setUpClass(cls):
        cls.header = FORGEPACT_STATS.read_text(encoding="utf-8", errors="replace")
        cls.panel = FORGEPACT_PANEL.read_text(encoding="utf-8", errors="replace")

    def test_only_element_zero_gets_the_bonus(self):
        add = _function_body(self.header, "static RValue Add(")
        self.assertRegex(add, r"if\s*\(\s*i\s*==\s*0\s*\)")
        self.assertRegex(add, r"e\s*=\s*RValue\(\s*native\s*\+\s*ek\s*\)")

    def test_the_clamp_is_zero_floor_whole_levels_and_the_cap(self):
        clamp = _function_body(self.header, "static double ClampAddBonus(")
        self.assertRegex(clamp, r"v\s*<\s*0\.0\)\s*v\s*=\s*0\.0\s*;")
        self.assertIn("if (e.whole) v = std::floor(v + 0.5);", clamp)
        self.assertIn("if (e.cap > 0.0 && v > e.cap) v = e.cap;", clamp)
        cap = re.search(r"static constexpr double kAllSkillsMax = ([0-9.]+);", self.header)
        self.assertEqual(float(cap.group(1)), FORGEPACT_ALL_SKILLS_MAX)

    def test_all_skills_alone_is_whole_and_capped(self):
        self.assertRegex(self.header, r'\{ "allskills",\s+"StatAllSkills",[^}]*kAllSkillsMax, true \}')
        self.assertRegex(self.header, r'\{ "skillhaste",\s+"StatSpellHaste",[^}]*0\.0, false \}')

    def test_the_panel_ceilings(self):
        self.assertIn(f'("skillhaste", "Skill Haste", {FORGEPACT_SKILL_HASTE_MAX}, 5, "add"),', self.panel)
        self.assertEqual(FORGEPACT_SKILL_HASTE_MAX, model.SKILL_HASTE_CAP)
        self.assertIn(f'("allskills", "All Skills", {FORGEPACT_ALL_SKILLS_MAX}, 1, "add"),', self.panel)


if __name__ == "__main__":
    unittest.main()
