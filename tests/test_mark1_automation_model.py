"""Checks for `hs_game_sdk.mark1_automation_model` (ForgePact#166, the Mark 1 set).

The model is written from `docs/models/mark1-automation-spec.md` and covers
the proc route's interval and the mana cost that offsets its free procs. Its
cases, `hs-game-sdk/curated/mark1_automation_cases.json`, are the ones
ForgePact's C++ cores (`Mark1Priority.hpp`, `Mark1Cost.hpp`) are tested
against as well.

Baseline: what happens with nothing automated, or a skill with no cooldown.
Target: what the owner's rule and the proposed cost must turn it into. That
is the order `AGENTS.md` § "Mod Development Workflow" asks for.
"""
import json
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
SPEC_DOC = ROOT / "docs" / "models" / "mark1-automation-spec.md"
CASES = ROOT / "hs-game-sdk" / "curated" / "mark1_automation_cases.json"

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import mark1_automation_model as model  # noqa: E402
from hs_game_sdk import skill_stat_model  # noqa: E402

#: Healing Zone's `abilityCooldown`, in seconds.
HEALING_ZONE_COOLDOWN = 14
#: A talent with no cooldown reads 0.25 (RDM § 7.1).
NO_COOLDOWN = Fraction(1, 4)

MAX = model.ASSUMED_MAX_MANA
BASE = model.ASSUMED_BASE_REPLENISH_PCT

#: The three reference investments, as keyword arguments of `net_mana_per_second`.
REPLENISH = {"replenish_pct": model.REFERENCE_REPLENISH_PCT}
PER_SECOND = {"mana_per_second": model.REFERENCE_MANA_PER_SECOND}
PER_KILL = {"mana_per_kill": model.REFERENCE_MANA_PER_KILL,
            "kills_per_second": model.REFERENCE_KILLS_PER_SECOND}


def net(columns, *investments, percent=model.DRAIN_PCT_PER_SECOND, base=BASE):
    """The reference character's net mana a second with `columns` automated skills."""
    kwargs = {"replenish_pct": 0, "mana_per_second": 0, "mana_per_kill": 0, "kills_per_second": 0}
    for investment in investments:
        kwargs.update(investment)
    # In mana a second: the drain at unit 1, which the measured unit leaves
    # the same once id 42's answer is divided by it.
    drain = model.drain_per_second(columns, percent, MAX, unit=1)
    return model.net_mana_per_second(MAX, base, drain=drain, **kwargs)


class IntervalTests(unittest.TestCase):
    """The proc route's interval: cooldown at Skill Haste plus cast time at Faster Cast Rate."""

    def test_interval_baseline_no_cooldown_is_cast_time(self):
        for cooldown in (0, NO_COOLDOWN):
            with self.subTest(cooldown=cooldown):
                self.assertEqual(model.cooldown_seconds(cooldown, 0), 0)
                self.assertEqual(model.interval_ms(cooldown, 0, 0), 1000)
                # Skill Haste has nothing to shorten.
                self.assertEqual(model.interval_ms(cooldown, 100, 0), 1000)
        self.assertEqual(model.interval_ms(NO_COOLDOWN, 0, -50), 2000)
        self.assertEqual(model.interval_ms(NO_COOLDOWN, 0, 100), 500)
        self.assertEqual(model.interval_ms(NO_COOLDOWN, 0, 0, base_cast_seconds=Fraction(3, 2)), 1500)

    def test_interval_target_cooldown_plus_cast_time_with_haste(self):
        self.assertEqual(model.interval_ms(HEALING_ZONE_COOLDOWN, 0, 0), 15000)
        # 100 Skill Haste: two thirds of 14 s, plus the 1 s cast.
        self.assertEqual(model.interval_ms(HEALING_ZONE_COOLDOWN, 100, 0), Fraction(31000, 3))
        self.assertEqual(model.interval_ms(HEALING_ZONE_COOLDOWN, 100, 100), Fraction(29500, 3))
        # The game counts at most 200 Skill Haste: half the cooldown.
        self.assertEqual(model.interval_ms(HEALING_ZONE_COOLDOWN, 300, 0), 8000)
        self.assertEqual(model.interval_ms(HEALING_ZONE_COOLDOWN, 0, -50), 16000)
        # Just above the floor is a cooldown.
        self.assertEqual(model.interval_ms(Fraction(3, 10), 0, 0), 1300)

    def test_interval_reuses_the_skill_stat_model(self):
        for haste in (0, 12, 100, 200, 340):
            with self.subTest(haste=haste):
                self.assertEqual(model.cooldown_seconds(HEALING_ZONE_COOLDOWN, haste),
                                 HEALING_ZONE_COOLDOWN * skill_stat_model.cooldown_fraction(haste))
        self.assertEqual((model.SKILL_HASTE_STAT_ID, model.FASTER_CAST_RATE_STAT_ID), (103, 106))
        self.assertEqual((model.MAX_MANA_STAT_ID, model.MANA_REPLENISH_STAT_ID,
                          model.MANA_PER_KILL_STAT_ID), (37, 42, 46))

    def test_interval_cast_divisor_is_floored(self):
        self.assertEqual(model.cast_seconds(-95), 10)
        self.assertEqual(model.cast_seconds(-100), 10)
        self.assertEqual(model.cast_seconds(-500), 10)
        self.assertEqual(model.cast_seconds(-90), 10)
        self.assertEqual(model.cast_seconds(-89), Fraction(100, 11))

    def test_interval_nonsense_is_refused(self):
        with self.assertRaises(ValueError):
            model.cast_seconds(0, base_cast_seconds=-1)
        with self.assertRaises(ValueError):
            model.cooldown_seconds(HEALING_ZONE_COOLDOWN, -200)


class DrainTests(unittest.TestCase):
    """The planned cost: the replenish answer lowered per automated skill."""

    def test_drain_baseline_nothing_automated_drains_nothing(self):
        self.assertEqual(model.drain_per_second(0, model.DRAIN_PCT_PER_SECOND, MAX), 0)
        for original in (30, 0, -7, Fraction(5, 2)):
            with self.subTest(original=original):
                self.assertEqual(model.replenish_answer(original, 0, MAX), original)
        self.assertEqual(model.cut_max_mana(0, model.MAX_MANA_CUT_PCT, MAX), MAX)
        self.assertTrue(model.is_sustained(net(0)))
        self.assertIsNone(model.seconds_to_empty(MAX, net(0)))

    def test_drain_baseline_unit_one_is_mana_a_second(self):
        # At unit 1 id 42's answer is mana a second: R - n x 1% x M.
        self.assertEqual([model.replenish_answer(30, n, MAX, 1, 1) for n in range(5)],
                         [30, 15, 0, -15, -30])
        self.assertEqual(model.replenish_answer(0, 4, 1000, 100, 1), -1000)

    def test_drain_target_scaled_by_the_measured_unit(self):
        # Stats live 3's `regen-units`: one unit of id 42's answer is 0.874
        # mana a second, so the answer divides by it.
        self.assertEqual(model.REPLENISH_UNIT, Fraction(874, 1000))
        unit = model.REPLENISH_UNIT
        for n in (1, 4):
            with self.subTest(columns=n):
                expected = 30 - n * Fraction(1, 100) * MAX / unit
                self.assertEqual(model.replenish_answer(30, n, MAX), expected)
                self.assertEqual(model.drain_per_second(n, model.DRAIN_PCT_PER_SECOND, MAX),
                                 n * Fraction(15) / unit)
                # In mana a second, a true 1% of the maximum per skill.
                self.assertEqual(model.drain_per_second(n, model.DRAIN_PCT_PER_SECOND, MAX) * unit, 15 * n)
        self.assertAlmostEqual(float(model.replenish_answer(30, 1, MAX)), 30 - 15 / 0.874, places=9)
        # Still clamped at minus the maximum.
        self.assertEqual(model.replenish_answer(0, 4, 1000, 100), -1000)
        self.assertEqual(model.replenish_answer(0, 4, MAX, percent=25), -MAX)

    def test_drain_negative_control_unit_divides_not_multiplies(self):
        unit = model.REPLENISH_UNIT
        shipped = model.drain_per_second(1, model.DRAIN_PCT_PER_SECOND, MAX)
        multiplied = model.drain_per_second(1, model.DRAIN_PCT_PER_SECOND, MAX, 1) * unit
        self.assertGreater(shipped, 15)
        self.assertNotEqual(shipped, multiplied)
        # The unit leaves zero columns, and the cut, exactly as before.
        self.assertEqual(model.drain_per_second(0, model.DRAIN_PCT_PER_SECOND, MAX), 0)
        self.assertEqual(model.replenish_answer(30, 0, MAX), 30)
        self.assertEqual([model.cut_max_mana(n, model.MAX_MANA_CUT_PCT, MAX) for n in range(5)],
                         [1500, 1200, 900, 600, 300])
        for bad in (0, -1):
            with self.subTest(unit=bad), self.assertRaises(ValueError):
                model.drain_per_second(1, 1, MAX, bad)

    def test_drain_target_one_sustainable_at_baseline(self):
        self.assertEqual(model.drain_per_second(1, model.DRAIN_PCT_PER_SECOND, MAX, unit=1), 15)
        self.assertEqual(net(1), 15)
        self.assertTrue(model.is_sustained(net(1)))
        # Two cost what the character regenerates.
        self.assertEqual(net(2), 0)
        self.assertTrue(model.is_sustained(net(2)))

    def test_drain_target_four_unsustainable_at_baseline(self):
        self.assertEqual(model.drain_per_second(4, model.DRAIN_PCT_PER_SECOND, MAX, unit=1), 60)
        self.assertEqual(net(4), -30)
        self.assertFalse(model.is_sustained(net(4)))
        self.assertEqual(model.seconds_to_empty(MAX, net(4)), 50)

    def test_drain_target_four_not_sustained_by_a_weaker_single_investment(self):
        self.assertEqual(model.seconds_to_empty(MAX, net(4, PER_SECOND)), 150)
        self.assertEqual(model.seconds_to_empty(MAX, net(4, PER_KILL)), 75)

    def test_drain_target_four_break_even_at_one_strong_replenish(self):
        self.assertEqual(net(4, REPLENISH), 0)
        self.assertTrue(model.is_sustained(net(4, REPLENISH)))

    def test_drain_target_four_sustainable_with_two_investments(self):
        pairs = {"replenish+per second": (REPLENISH, PER_SECOND),
                 "replenish+per kill": (REPLENISH, PER_KILL),
                 "per second+per kill": (PER_SECOND, PER_KILL)}
        for name, pair in pairs.items():
            with self.subTest(pair=name):
                self.assertTrue(model.is_sustained(net(4, *pair)), net(4, *pair))

    def test_drain_answer_never_below_minus_max_mana(self):
        self.assertEqual(model.replenish_answer(30, 4, MAX, unit=1), -30)
        self.assertEqual(model.replenish_answer(50, 4, 100000, percent=30), -100000)
        self.assertEqual(model.replenish_answer(0, 4, MAX, percent=25), -MAX)

    def test_drain_reference_table(self):
        # The spec's table, row by row, for the reference character.
        quarter = Fraction(5, 4)
        three_quarters = Fraction(3, 4)
        self.assertEqual(round(model.seconds_to_empty(MAX, net(4, percent=quarter))), 33)
        singles = [model.seconds_to_empty(MAX, net(4, one, percent=quarter))
                   for one in (REPLENISH, PER_SECOND, PER_KILL)]
        self.assertEqual((round(min(singles)), max(singles)), (43, 100))
        self.assertTrue(model.is_sustained(net(4, REPLENISH, PER_SECOND, percent=quarter)))
        self.assertEqual(model.seconds_to_empty(MAX, net(4, REPLENISH, PER_KILL, percent=quarter)), 300)
        self.assertEqual(model.seconds_to_empty(MAX, net(4, PER_SECOND, PER_KILL, percent=quarter)), 100)
        self.assertEqual(model.seconds_to_empty(MAX, net(4, percent=three_quarters)), 100)
        self.assertTrue(model.is_sustained(net(4, REPLENISH, percent=three_quarters)))
        self.assertTrue(model.is_sustained(net(4, PER_SECOND, percent=three_quarters)))
        self.assertEqual(model.seconds_to_empty(MAX, net(4, PER_KILL, percent=three_quarters)), 300)
        # Sensitivity: at a 1% baseline, four need all three investments.
        self.assertEqual(round(model.seconds_to_empty(MAX, net(4, base=1))), 33)
        self.assertFalse(model.is_sustained(net(4, REPLENISH, PER_SECOND, base=1)))
        self.assertTrue(model.is_sustained(net(4, REPLENISH, PER_SECOND, PER_KILL, base=1)))

    def test_drain_nonsense_is_refused(self):
        with self.assertRaises(ValueError):
            model.drain_per_second(-1, 1, MAX)
        with self.assertRaises(ValueError):
            model.drain_per_second(1, 1, -1)


class MaxManaTests(unittest.TestCase):
    """The documented alternative: maximum mana cut per automated skill."""

    def test_maxmana_target_four_leaves_twenty_percent(self):
        cut = model.MAX_MANA_CUT_PCT
        self.assertEqual(cut, 20)
        self.assertEqual([model.cut_max_mana(n, cut, MAX) for n in range(5)],
                         [1500, 1200, 900, 600, 300])
        self.assertEqual(model.cut_max_mana(4, cut, MAX) / MAX, Fraction(1, 5))

    def test_maxmana_never_below_zero(self):
        self.assertEqual(model.cut_max_mana(4, 30, MAX), 0)


def _close(actual, expected, tolerance):
    return abs(float(actual) - float(expected)) <= tolerance


class CasesTests(unittest.TestCase):
    """The shared cases the C++ cores are held to."""

    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(CASES.read_text(encoding="utf-8"))

    def test_cases_file_matches_the_model(self):
        cases = self.cases
        for key in ("status", "source", "interval", "drain", "maxmana"):
            self.assertIn(key, cases)
        for case in cases["interval"]:
            with self.subTest(interval=case["label"]):
                got = model.interval_ms(Fraction(str(case["ability_cooldown"])), case["haste"],
                                        case["fcr"], Fraction(str(case["base_cast_seconds"])))
                self.assertTrue(_close(got, case["expected_ms"], 0.001), (float(got), case))
        for case in cases["drain"]:
            with self.subTest(drain=case["label"]):
                drain = model.drain_per_second(case["columns"], case["percent"], case["max_mana"], case["unit"])
                answer = model.replenish_answer(case["original"], case["columns"], case["max_mana"],
                                                case["percent"], case["unit"])
                self.assertTrue(_close(drain, case["expected_drain"], 0.001), (float(drain), case))
                self.assertTrue(_close(answer, case["expected_answer"], 0.001), (float(answer), case))
        for case in cases["maxmana"]:
            with self.subTest(maxmana=case["label"]):
                got = model.cut_max_mana(case["columns"], case["cut_pct"], case["original"])
                self.assertTrue(_close(got, case["expected_answer"], 0.001), (float(got), case))

    def test_cases_cover_what_the_plan_asks_for(self):
        cases = self.cases
        interval = cases["interval"]
        self.assertTrue(any(Fraction(str(c["ability_cooldown"])) <= NO_COOLDOWN for c in interval))
        hz = {c["haste"] for c in interval if c["ability_cooldown"] == HEALING_ZONE_COOLDOWN}
        self.assertTrue({0, 100} <= hz, hz)
        self.assertTrue({-50, 0, 100} <= {c["fcr"] for c in interval})
        at_one = [c for c in cases["drain"] if c["percent"] == 1 and c["max_mana"] == MAX]
        self.assertEqual({c["columns"] for c in at_one}, {0, 1, 2, 3, 4})
        self.assertTrue(any(c["expected_answer"] == -c["max_mana"] for c in cases["drain"]))
        # The shipped unit, one column and four, so the C++ core is held to the
        # scaled numbers too.
        scaled = [c for c in cases["drain"] if Fraction(str(c["unit"])) == model.REPLENISH_UNIT
                  and c["percent"] == 1 and c["max_mana"] == MAX]
        self.assertTrue({1, 4} <= {c["columns"] for c in scaled}, scaled)
        self.assertEqual({c["columns"] for c in cases["maxmana"]}, {0, 1, 2, 3, 4})
        for key in ("interval", "drain", "maxmana"):
            for case in cases[key]:
                self.assertTrue(case.get("label"), (key, case))

    def test_cases_controls_disagree_with_a_wrong_model(self):
        # Negative control: the sum rule is what the cases pin, so the "longer
        # of the two" a held key plausibly gives would not pass them.
        hz = [c for c in self.cases["interval"]
              if c["ability_cooldown"] == HEALING_ZONE_COOLDOWN and c["haste"] == 0 and c["fcr"] == 0][0]
        longer = 1000 * max(model.cooldown_seconds(HEALING_ZONE_COOLDOWN, 0), model.cast_seconds(0))
        self.assertFalse(_close(longer, hz["expected_ms"], 1))


class NoDecompilerOutputTests(unittest.TestCase):
    """The spec, the model and the cases were written clean-room; nothing they ship may carry listing text."""

    FILES = (SPEC_DOC, SDK_PY / "hs_game_sdk" / "mark1_automation_model.py", CASES, Path(__file__).resolve())

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
        self.assertFalse(self._matches("each proc fires at its cooldown plus its cast time"))

    def test_no_signature_in_the_mark1_automation_files(self):
        for path in self.FILES:
            with self.subTest(path=path.name):
                self.assertEqual(self._matches(path.read_text(encoding="utf-8")), [])


class SpecTests(unittest.TestCase):
    def test_spec_labels_every_claim(self):
        spec = SPEC_DOC.read_text(encoding="utf-8")
        for heading in ("## Static reading", "## Measured", "## Assumption", "## Not established",
                        "## The model", "## What the model cannot catch"):
            self.assertIn("\n" + heading + "\n", spec)
        for label in ("Static reading", "Measured", "Assumption", "Not established"):
            self.assertIn(label, spec)
        self.assertIn("mark1_automation_model.py", spec)
        self.assertIn("mark1_automation_cases.json", spec)
        self.assertIn("mark1-set-research.md", spec)
        for section in ("§ 7.5", "§ 7.10"):
            self.assertIn(section, spec)
        for name in ("ReturnSpecificStat", "StatManaReplenish", "StatMaxMana", "PlayerManaUpdate",
                     "TalentUseSetSpeed", "abilityCooldown"):
            self.assertIn(name, spec)


if __name__ == "__main__":
    unittest.main()
