"""Checks for `hs_game_sdk.number_compress_model` (ForgePact#230, hub #539).

The model is written from `docs/models/number-compress-spec.md` and covers the
game only: which numbers `SteamCompressNumber` ends the process on, and the
text it writes for the rest. ForgePact's cap (`numguard`) is its own code, so
it lives here as an input transform (`numguard_cap`). `LeverParityTests` pins
the transform and the model's limits to `NumberGuard.hpp` when ForgePact is
checked out. `MeasurementTests` checks the model against Live 2's values
(`hs-game-sdk/curated/number_compress_measurements.json`).

Baseline: what the game does with no mod. Target: what the cap must turn it
into. That is the order `AGENTS.md` § "Mod Development Workflow" asks for.
"""
import json
import math
import random
import re
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
SPEC_DOC = ROOT / "docs" / "models" / "number-compress-spec.md"
GUARD_HEADER = ROOT / "ForgePact" / "plugin" / "include" / "ForgePact" / "NumberGuard.hpp"
MEASUREMENTS = ROOT / "hs-game-sdk" / "curated" / "number_compress_measurements.json"

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import number_compress_model as model  # noqa: E402

# ---- ForgePact's cap, as an input transform (our code, not the game's) ----

#: `kNumGuardLargestSafe`: q = 999,990, shown "99999B", terminator inside the buffer.
LARGEST_SAFE = 99999000000000.0
#: `kNumGuardSmallestSafe`: shown "-999999", 7 characters and the terminator.
SMALLEST_SAFE = -999999.0
#: What NaN becomes (shown "0").
NAN_REPLACEMENT = 0.0


def numguard_cap(x):
    """`numguard` while armed: a number the shortener would fail on is replaced
    before the game's own call goes ahead; every other number is left alone."""
    if math.isnan(x):
        return NAN_REPLACEMENT
    if x >= model.POSITIVE_LIMIT:
        return LARGEST_SAFE
    if x <= model.NEGATIVE_LIMIT:
        return SMALLEST_SAFE
    return x


def bits(x):
    return struct.pack("<d", x)


# The spec's baseline values (§ "The model").
PASSING = (0.0, 1.0, 9999.0, 10000.0, 123456.0, 999999.0, 1e9,
           99_999_000_000_000.0, 99_999_999_999_999.98)
FAILING = (1e14, 1e15, 1e18, 1e300, math.inf, math.nan, -1e6, -1e12, -math.inf)


def _sweep():
    """Values on both sides of every boundary, plus a fixed random spread."""
    values = list(PASSING) + list(FAILING)
    values += [-0.0, -0.5, -1.0, -1234.7, -999999.9, 0.5, 9999.9, 12345.0, 10050.0,
               2.15e17, 2.2e17, 1e13, 5e13, math.nextafter(1e13, 0.0)]
    for edge in (model.POSITIVE_LIMIT, model.NEGATIVE_LIMIT, 10_000.0, 1e6, 1e9, -1.0):
        below = above = edge
        for _ in range(4):
            below = math.nextafter(below, -math.inf)
            above = math.nextafter(above, math.inf)
            values += [below, above]
        values.append(edge)
    rng = random.Random(230)
    for _ in range(4000):
        magnitude = 10.0 ** rng.uniform(-3.0, 20.0)
        values.append(magnitude if rng.random() < 0.7 else -magnitude)
    return values


SWEEP = _sweep()


class BaselineTests(unittest.TestCase):
    """The game alone: what the shortener does with no mod in the way."""

    def test_the_limits_are_the_specs(self):
        self.assertEqual(model.POSITIVE_LIMIT, 1e14)
        self.assertEqual(model.NEGATIVE_LIMIT, -1e6)

    def test_ordinary_values_format(self):
        for x in PASSING:
            with self.subTest(x=x):
                self.assertFalse(model.fails(x))
                self.assertIsNotNone(model.text(x))

    def test_the_failing_values_fail(self):
        for x in FAILING:
            with self.subTest(x=x):
                self.assertTrue(model.fails(x))
                self.assertIsNone(model.text(x))
                self.assertFalse(model.fits_with_terminator(x))

    def test_both_limits_exactly(self):
        self.assertTrue(model.fails(model.POSITIVE_LIMIT))
        self.assertFalse(model.fails(math.nextafter(model.POSITIVE_LIMIT, 0.0)))
        self.assertTrue(model.fails(model.NEGATIVE_LIMIT))
        self.assertFalse(model.fails(math.nextafter(model.NEGATIVE_LIMIT, 0.0)))
        self.assertFalse(model.fails(-999_999.9))

    def test_the_positive_limit_is_where_q_reaches_seven_digits(self):
        # The spec's arithmetic: in doubles, "q has 7 or more digits" and
        # "x >= 1e14" pick the same positive values.
        below = math.nextafter(model.POSITIVE_LIMIT, 0.0)
        self.assertEqual(model.band(below), (999_999, "B"))
        self.assertGreaterEqual(math.trunc(model.POSITIVE_LIMIT / 1e8), 1_000_000)

    def test_the_texts_the_spec_names(self):
        cases = {
            0.0: "0", -0.0: "0", 1.0: "1", 9999.0: "9999", 9999.9: "9999",
            -1234.7: "-1234", -0.5: "-0", -999_999.9: "-999999",
            10000.0: "10K", 10050.0: "10K", 12345.0: "12,3K", 123456.0: "123,4K",
            999999.0: "999,9K", 1e6: "1M", 1e9: "1B",
            99_999_000_000_000.0: "99999B", 99_999_999_999_999.98: "99999,9B",
        }
        for x, shown in cases.items():
            with self.subTest(x=x):
                self.assertEqual(model.text(x), shown)

    def test_which_passing_values_fit_their_terminator(self):
        # 99,999,999,999,999.98 passes with an 8-character text; the others fit.
        for x in PASSING:
            with self.subTest(x=x):
                self.assertEqual(model.fits_with_terminator(x), x != 99_999_999_999_999.98)

    def test_only_the_b_band_six_digit_texts_overrun(self):
        for x in SWEEP:
            if model.fails(x):
                continue
            with self.subTest(x=x):
                shown = model.text(x)
                self.assertLessEqual(len(shown), model.BUFFER_BYTES)
                q_and_suffix = model.band(x)
                overrun = (q_and_suffix is not None and q_and_suffix[1] == "B"
                           and q_and_suffix[0] >= 100_000 and q_and_suffix[0] % 10 != 0)
                self.assertEqual(model.fits_with_terminator(x), not overrun)
                if overrun:
                    self.assertTrue(1e13 <= x < 1e14)

    def test_a_negative_text_never_fills_the_buffer(self):
        for x in SWEEP:
            if x < 0 and not model.fails(x):
                self.assertTrue(model.fits_with_terminator(x), x)


class TargetTests(unittest.TestCase):
    """ForgePact's cap in front of the game: nothing the shortener sees fails."""

    def test_every_failing_value_maps_to_one_that_passes_and_fits(self):
        for x in SWEEP:
            if not model.fails(x):
                continue
            with self.subTest(x=x):
                capped = numguard_cap(x)
                self.assertFalse(model.fails(capped))
                self.assertTrue(model.fits_with_terminator(capped))

    def test_every_passing_value_comes_through_bit_for_bit(self):
        for x in SWEEP:
            if model.fails(x):
                continue
            with self.subTest(x=x):
                self.assertEqual(bits(numguard_cap(x)), bits(x))

    def test_the_eight_character_texts_are_left_alone(self):
        x = 99_999_999_999_999.98
        self.assertFalse(model.fits_with_terminator(x))
        self.assertEqual(bits(numguard_cap(x)), bits(x))

    def test_what_a_capped_number_shows(self):
        self.assertEqual(model.text(numguard_cap(1e18)), "99999B")
        self.assertEqual(model.text(numguard_cap(math.inf)), "99999B")
        self.assertEqual(model.text(numguard_cap(-1e12)), "-999999")
        self.assertEqual(model.text(numguard_cap(-math.inf)), "-999999")
        self.assertEqual(model.text(numguard_cap(math.nan)), "0")

    def test_the_safe_values_sit_next_to_the_limits(self):
        # The largest safe value is the top of the shown range that fits: the
        # next q (999,991) would be an 8-character text.
        self.assertEqual(model.band(LARGEST_SAFE), (999_990, "B"))
        self.assertFalse(model.fits_with_terminator(LARGEST_SAFE + 1e8))
        self.assertTrue(model.fails(SMALLEST_SAFE - 1.0))


#: A text the shortener draws: whole digits, an optional ",<digit>", a band suffix.
_SHOWN = re.compile(r"^(\d+)(?:,(\d))?([KMB])$")
#: What one unit of q is worth in each band (the spec's divisors).
_Q_UNIT = {"K": 100.0, "M": 1e5, "B": 1e8}


def value_shown_as(shown):
    """A number whose text, by the spec's band rules, would be `shown`; None when
    `shown` is not shaped like a shortened text."""
    match = _SHOWN.match(shown)
    if match is None:
        return float(shown) if re.fullmatch(r"-?\d+", shown) else None
    whole, decimal, suffix = match.groups()
    q = int(whole) * 10 + int(decimal or 0)
    return q * _Q_UNIT[suffix]


class MeasurementTests(unittest.TestCase):
    """Live 2 (capture `forgepact-230-damage-crash-live-2`): the values the game
    met, from `hs-game-sdk/curated/number_compress_measurements.json`."""

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(MEASUREMENTS.read_text(encoding="utf-8"))
        cls.a = cls.data["launch_a"]
        cls.b = cls.data["launch_b"]

    def test_the_file_is_this_capture(self):
        self.assertEqual(self.data["capture"], "forgepact-230-damage-crash-live-2")
        self.assertEqual(self.data["status"], "measured")

    def test_the_model_fails_the_value_the_game_ended_on(self):
        crash = float(self.a["last_before_crash"])
        self.assertEqual(crash, float(self.a["traced"][-1]))
        self.assertTrue(model.fails(crash))
        self.assertIsNone(model.text(crash))

    def test_the_model_passes_the_largest_value_that_passed(self):
        largest = float(self.a["largest_traced_that_passed"])
        self.assertEqual(largest, max(float(v) for v in self.a["traced"][:-1]))
        self.assertFalse(model.fails(largest))
        for value in self.a["traced"][:-1]:
            with self.subTest(value=value):
                self.assertFalse(model.fails(float(value)))

    def test_the_measured_bracket_holds_the_modelled_limit(self):
        self.assertLess(float(self.a["largest_traced_that_passed"]), model.POSITIVE_LIMIT)
        self.assertGreaterEqual(float(self.a["last_before_crash"]), model.POSITIVE_LIMIT)

    def test_the_capped_value_is_the_bracket_s_lower_edge(self):
        # Launch B handed the capped value itself to the shortener `clamped`
        # times and the game lived: a measured pass at 9.9999e13, which
        # narrows the limit to (capped value, last value before the crash].
        capped = float(self.b["capped_to"])
        self.assertGreater(self.b["clamped"], 0)
        self.assertEqual(self.b["exit_code"], "0x00000000")
        self.assertFalse(model.fails(capped))
        self.assertGreater(capped, float(self.a["largest_traced_that_passed"]))
        self.assertLess(capped, model.POSITIVE_LIMIT)
        self.assertLessEqual(model.POSITIVE_LIMIT, float(self.a["last_before_crash"]))

    def test_the_dump_is_the_range_check_fast_fail_in_the_extension(self):
        dump = self.a["dump"]
        self.assertEqual(self.a["exit_code"].lower(), dump["code"])
        self.assertEqual(dump["code"], "0xc0000409")
        self.assertEqual(dump["fast_fail_subcode"], 8)
        self.assertEqual(dump["raised_in"] + ".dll", self.data["build"]["extension"])
        self.assertEqual(dump["export_on_stack"], "SteamCompressNumber")

    def test_the_route_ran_one_for_one(self):
        hits = self.data["route"]["hits"]
        self.assertGreater(hits["num_compressSteam"], 0)
        self.assertEqual(hits["num_compressSteam"], hits["SteamCompressNumber"])
        # A zero only counts beside a control that logged in the same window.
        self.assertEqual(hits["num_compressGML"], 0)
        self.assertGreater(hits["control_CheckTalentUse"], 0)

    def test_the_shown_texts_are_texts_the_model_writes(self):
        for shown in self.a["shown_texts"] + [self.b["shown_capped"]]:
            with self.subTest(shown=shown):
                value = value_shown_as(shown)
                self.assertIsNotNone(value)
                self.assertEqual(model.text(value), shown)

    def test_the_text_check_can_fail(self):
        # Negative control: texts the shortener never draws.
        for shown in ("1.2B", "1,0K", "1234567B", "12,34M"):
            with self.subTest(shown=shown):
                value = value_shown_as(shown)
                self.assertTrue(value is None or model.text(value) != shown)

    def test_the_cap_maps_what_launch_b_saw(self):
        first = float(self.b["first_capped"])
        self.assertEqual(numguard_cap(first), float(self.b["capped_to"]))
        self.assertEqual(float(self.b["capped_to"]), LARGEST_SAFE)
        self.assertEqual(model.text(numguard_cap(first)), self.b["shown_capped"])
        for value in self.b["traced"] + [self.b["largest_seen"]]:
            with self.subTest(value=value):
                value = float(value)
                self.assertEqual(model.fails(value), value >= model.POSITIVE_LIMIT)
                self.assertFalse(model.fails(numguard_cap(value)))
        self.assertGreater(self.b["clamped"], 0)
        self.assertEqual(self.b["exit_code"], "0x00000000")


class NoDecompilerOutputTests(unittest.TestCase):
    """The spec and the model were written clean-room; nothing they ship may carry listing text."""

    FILES = (SPEC_DOC, SDK_PY / "hs_game_sdk" / "number_compress_model.py", MEASUREMENTS,
             Path(__file__).resolve())

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
        self.assertFalse(self._matches("the quotient is truncated when it is above 0"))

    def test_no_signature_in_the_number_compress_files(self):
        for path in self.FILES:
            with self.subTest(path=path.name):
                self.assertEqual(self._matches(path.read_text(encoding="utf-8")), [])


class SpecTests(unittest.TestCase):
    def test_the_spec_labels_its_claims_and_names_the_model(self):
        spec = SPEC_DOC.read_text(encoding="utf-8")
        for heading in ("## Static reading", "## Measurements", "## Our code", "## Not established",
                        "## The model", "## What the model cannot catch"):
            self.assertIn("\n" + heading + "\n", spec)
        for name in ("number_compress_model.py", "num_compressSteam", "SteamCompressNumber",
                     "PAS_Steam_GMS_x64.dll", "kNumGuardPositiveLimit", "kNumGuardNegativeLimit",
                     "kNumGuardLargestSafe", "kNumGuardSmallestSafe"):
            self.assertIn(name, spec)

    def test_every_function_the_spec_names_exists(self):
        spec = SPEC_DOC.read_text(encoding="utf-8")
        section = spec[spec.index("\n## The model\n"):spec.index("\n## What the model cannot catch\n")]
        names = re.findall(r"^- `([a-z_0-9]+)\(", section, re.MULTILINE)
        self.assertGreaterEqual(len(names), 2)
        for name in names:
            self.assertTrue(callable(getattr(model, name, None)), name)


def _header_constant(source, name):
    match = re.search(rf"\b{name}\s*(?:=|\{{)\s*([-+0-9.eE']+)", source)
    if match is None:
        return None
    return float(match.group(1).replace("'", ""))


@unittest.skipUnless(GUARD_HEADER.is_file(),
                     "ForgePact is not checked out (hub CI checks out without submodules), "
                     "or its checkout has no NumberGuard.hpp to compare the limits and the cap with")
class LeverParityTests(unittest.TestCase):
    """The model's limits are the game's and `numguard_cap` is ForgePact's
    `numguard`; pin both to `NumberGuard.hpp`."""

    @classmethod
    def setUpClass(cls):
        cls.source = GUARD_HEADER.read_text(encoding="utf-8", errors="replace")

    def test_the_four_constants(self):
        for name, expected in (("kNumGuardPositiveLimit", model.POSITIVE_LIMIT),
                               ("kNumGuardNegativeLimit", model.NEGATIVE_LIMIT),
                               ("kNumGuardLargestSafe", LARGEST_SAFE),
                               ("kNumGuardSmallestSafe", SMALLEST_SAFE)):
            with self.subTest(name=name):
                self.assertEqual(_header_constant(self.source, name), expected)


if __name__ == "__main__":
    unittest.main()
