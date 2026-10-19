"""Checks for `hs_game_sdk.movement_speed_model` (ForgePact#166, hub #518).

The model is written from `docs/models/movement-speed-spec.md` and covers the
game only. Mark 1's half speed is our code, so it lives here as an input
transform (`mark1_stat_model_answer`), the `speed-route: stat-model` lever the
research doc's Phase 2 decision picked.

Baseline: what the game does with no mod. Target: what the lever must turn it
into. Measured: every swept point of Mod live 1, replayed within 3%. That is
the order `AGENTS.md` § "Mod Development Workflow" asks for. LeverParity: the
plugin's constants (ForgePact's `Mark1Movement.hpp`) are the model's.
"""
import json
import re
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
SPEC_DOC = ROOT / "docs" / "models" / "movement-speed-spec.md"
FIXTURE = ROOT / "hs-game-sdk" / "curated" / "movement_speed_measurements.json"
RESEARCH_DOC = ROOT / "ForgePact" / "docs" / "mark1-set-research.md"
PLUGIN_HEADER = ROOT / "ForgePact" / "plugin" / "include" / "ForgePact" / "Mark1Movement.hpp"

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import movement_speed_model as model  # noqa: E402

#: Sorak's id-64 answer, every frame of Mod live 1's `stat-trace`.
SORAK_ANSWER = 151
#: How far a replayed point may sit from the model (the plan's tolerance).
TOLERANCE = Fraction(3, 100)


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---- Mark 1's lever, as an input transform (our code, not the game's) ----

def mark1_stat_model_answer(answer, offset=model.STEP_OFFSET, cap=model.STEP_CAP):
    """`speed-route: stat-model`: while the set's bonus is active, the local
    player's id-64 calls are answered (min(x, C) - k) / 2, with k the model's
    offset and C its cap (none measured)."""
    x = Fraction(answer)
    if cap is not None:
        x = min(x, Fraction(cap))
    return (x - Fraction(offset)) / 2


def no_lever(answer):
    return Fraction(answer)


class BaselineTests(unittest.TestCase):
    """The game with no mod: the measured shape, as numbers."""

    def test_no_lever_leaves_the_step_alone(self):
        for answer in (SORAK_ANSWER, 0, -75.5, 226.5, 1000):
            self.assertEqual(model.step_ratio(no_lever(answer), answer), 1)
            self.assertEqual(model.scaled_answer_ratio(1, answer), 1)

    def test_the_step_is_affine_not_proportional(self):
        self.assertEqual(model.MOVEMENT_SPEED_STAT_ID, 64)
        self.assertEqual(model.STEP_OFFSET, 200)
        self.assertEqual(model.step_weight(SORAK_ANSWER), 351)
        # An answer of 0 still walks, at 200 / 351 of Sorak's step.
        self.assertEqual(model.step_ratio(0, SORAK_ANSWER), Fraction(200, 351))
        # Halving the answer is not halving the walk.
        self.assertEqual(model.scaled_answer_ratio(Fraction(1, 2), SORAK_ANSWER),
                         Fraction(551, 702))
        self.assertNotEqual(model.scaled_answer_ratio(Fraction(1, 2), SORAK_ANSWER),
                            Fraction(1, 2))

    def test_no_cap_was_reached(self):
        self.assertIsNone(model.STEP_CAP)
        self.assertGreater(model.step_ratio(1000, SORAK_ANSWER),
                           model.step_ratio(226.5, SORAK_ANSWER))
        self.assertEqual(model.effective_answer(1000), 1000)

    def test_a_cap_when_given_stops_the_answer(self):
        self.assertEqual(model.effective_answer(300, cap=250), 250)
        self.assertEqual(model.step_ratio(300, 250, cap=250), 1)

    def test_the_scale_belongs_to_one_window(self):
        unit = model.step_per_point_from(Fraction("2.989"), SORAK_ANSWER)
        self.assertEqual(model.modal_step(SORAK_ANSWER, unit), Fraction("2.989"))
        self.assertEqual(model.modal_step(0, unit), Fraction("2.989") * 200 / 351)

    def test_an_answer_at_or_below_minus_the_offset_is_not_established(self):
        with self.assertRaises(ValueError):
            model.step_weight(-200)
        with self.assertRaises(ValueError):
            model.step_ratio(-250, SORAK_ANSWER)

    def test_the_measured_range(self):
        low, high = model.MEASURED_ANSWERS
        self.assertEqual(low, Fraction(SORAK_ANSWER) * Fraction(-1, 2))
        self.assertEqual(high, Fraction(SORAK_ANSWER) * Fraction(3, 2))


class TargetTests(unittest.TestCase):
    """What Mark 1's half speed must turn the walk into: exactly half."""

    def answers_across_the_sweep(self):
        low, high = model.MEASURED_ANSWERS
        steps = 12
        answers = [low + (high - low) * i / steps for i in range(steps + 1)]
        return answers + [Fraction(SORAK_ANSWER)]

    def test_the_stat_model_answer_halves_the_walk_across_the_sweep(self):
        for answer in self.answers_across_the_sweep():
            with self.subTest(answer=answer):
                halved = mark1_stat_model_answer(answer)
                self.assertEqual(model.step_ratio(halved, answer), Fraction(1, 2))

    def test_sorak_is_answered_minus_24_point_5(self):
        self.assertEqual(mark1_stat_model_answer(SORAK_ANSWER), Fraction(-49, 2))
        self.assertEqual(model.step_ratio(Fraction(-49, 2), SORAK_ANSWER), Fraction(1, 2))

    def test_the_lever_agrees_with_the_models_inverse(self):
        for answer in self.answers_across_the_sweep():
            self.assertEqual(mark1_stat_model_answer(answer),
                             model.answer_for_ratio(answer, Fraction(1, 2)))

    def test_halving_the_answer_instead_misses_the_target(self):
        # The proportional reading of "half speed" is the lever that was
        # measured at 0.785; the affine model is why the route subtracts k.
        for answer in self.answers_across_the_sweep():
            if answer <= 0:
                continue
            with self.subTest(answer=answer):
                self.assertGreater(model.step_ratio(answer / 2, answer), Fraction(1, 2))

    def test_the_halved_answer_stays_inside_the_measured_line(self):
        # Every halved answer for a swept answer is above -offset, so the
        # model never has to guess what a weight of 0 or less does.
        for answer in self.answers_across_the_sweep():
            self.assertGreater(model.step_weight(mark1_stat_model_answer(answer)), 0)

    def test_the_route_is_recorded_with_its_reason(self):
        self.assertEqual(model.SPEED_ROUTE, "stat-model")
        for word in ("speed-sweep", "speed-half", "speed-builtin", "speed-factor"):
            self.assertIn(word, model.SPEED_ROUTE_REASON)

    @unittest.skipUnless(RESEARCH_DOC.exists(), "ForgePact is not checked out")
    def test_the_route_matches_the_phase_2_decision(self):
        text = RESEARCH_DOC.read_text(encoding="utf-8")
        found = re.search(r"^speed-route: (\S+)\s*$", text, re.MULTILINE)
        self.assertIsNotNone(found, "the research doc has no speed-route: line")
        self.assertEqual(found.group(1), model.SPEED_ROUTE)
        shape = re.search(r"^speed-shape: (\S+)\s*$", text, re.MULTILINE)
        self.assertIsNotNone(shape)
        self.assertEqual(shape.group(1), "affine")


class MeasuredTests(unittest.TestCase):
    """Every recorded point, replayed against the model."""

    @classmethod
    def setUpClass(cls):
        cls.data = load_fixture()
        cls.rows = {row["id"]: row for row in cls.data["measurements"]}
        cls.control = cls.data["control"]

    def test_every_row_is_well_formed(self):
        for row in self.data["measurements"]:
            with self.subTest(row=row["id"]):
                for key in ("id", "kind", "status", "date", "source", "what", "values", "model"):
                    self.assertIn(key, row)
                self.assertEqual(row["status"], "measured")

    def test_the_control_answer_is_the_traced_answer(self):
        trace = self.rows["MS2"]["values"]
        self.assertEqual(trace["answer_min"], trace["answer_max"])
        self.assertEqual(trace["answer_min"], self.control["answer"])
        self.assertEqual(self.control["answer"], SORAK_ANSWER)

    def test_the_control_walks_agree(self):
        steps = [Fraction(s) for s in self.rows["MS1"]["values"]["modal_steps"]]
        self.assertEqual(steps[0], steps[1])
        self.assertEqual(steps[0], Fraction(self.control["modal_step"]))

    def sweep_rows(self):
        return [row for row in self.data["measurements"]
                if "multiplier" in row["values"] and row["date"] == "2026-10-19"]

    def test_every_window_ran_at_the_controls_frame_time(self):
        ms = Fraction(self.control["ms"])
        for row in self.sweep_rows():
            with self.subTest(row=row["id"]):
                self.assertLessEqual(abs(Fraction(row["values"]["ms"]) - ms), ms / 10)

    def test_every_swept_point_within_3_percent(self):
        reference = Fraction(self.control["modal_step"])
        answer = self.control["answer"]
        rows = self.sweep_rows()
        self.assertEqual(len(rows), 7)
        for row in rows:
            values = row["values"]
            with self.subTest(row=row["id"], multiplier=values["multiplier"]):
                measured = Fraction(values["modal_step"]) / reference
                predicted = model.scaled_answer_ratio(Fraction(values["multiplier"]), answer)
                self.assertLessEqual(abs(measured - predicted), TOLERANCE * predicted)
                # The recorded three-decimal ratio agrees with its own step.
                self.assertLessEqual(abs(measured - Fraction(values["ratio"])), Fraction(1, 1000))

    def test_every_swept_step_within_3_percent_from_the_windows_scale(self):
        unit = model.step_per_point_from(Fraction(self.control["modal_step"]),
                                         self.control["answer"])
        for row in self.sweep_rows():
            values = row["values"]
            answer = Fraction(values["multiplier"]) * self.control["answer"]
            predicted = model.modal_step(answer, unit)
            with self.subTest(row=row["id"]):
                self.assertLessEqual(abs(Fraction(values["modal_step"]) - predicted),
                                     TOLERANCE * predicted)

    def test_phase_1s_point_replays_at_its_own_frame_time(self):
        values = self.rows["MS10"]["values"]
        measured = Fraction(values["modal_step"]) / Fraction(values["reference_step"])
        predicted = model.scaled_answer_ratio(Fraction(values["multiplier"]),
                                              values["answer_assumed"])
        self.assertLessEqual(abs(measured - predicted), TOLERANCE * predicted)

    def test_the_half_point_is_half(self):
        values = self.rows["MS9"]["values"]
        measured = Fraction(values["modal_step"]) / Fraction(self.control["modal_step"])
        self.assertLessEqual(abs(measured - Fraction(1, 2)), TOLERANCE / 2)
        lever_answer = Fraction(values["multiplier"]) * SORAK_ANSWER
        self.assertLessEqual(abs(lever_answer - mark1_stat_model_answer(SORAK_ANSWER)), 1)

    def test_a_least_squares_fit_gives_the_models_offset(self):
        # Fit modal_step = a * answer + b over the control and every swept
        # point; the offset is b / a. The model's 200 must be that fit.
        answer0 = Fraction(self.control["answer"])
        points = [(answer0, Fraction(self.control["modal_step"]))]
        for row in self.sweep_rows():
            values = row["values"]
            points.append((Fraction(values["multiplier"]) * answer0,
                           Fraction(values["modal_step"])))
        n = len(points)
        mean_x = sum(x for x, _ in points) / n
        mean_y = sum(y for _, y in points) / n
        slope = (sum((x - mean_x) * (y - mean_y) for x, y in points)
                 / sum((x - mean_x) ** 2 for x, _ in points))
        offset = (mean_y - slope * mean_x) / slope
        self.assertLessEqual(abs(offset - model.STEP_OFFSET), 1)

    def test_the_step_tracks_the_frame_clock(self):
        values = self.rows["MS11"]["values"]
        slow, fast = (Fraction(s) for s in values["steps"])
        slow_ms, fast_ms = (Fraction(m) for m in values["ms"])
        self.assertGreater(slow, fast)
        self.assertGreater(slow_ms, fast_ms)
        # Each window gets its own scale; their ratio follows the frame time
        # only roughly (the law is not established), within 5% here.
        ratio = (model.step_per_point_from(slow, SORAK_ANSWER)
                 / model.step_per_point_from(fast, SORAK_ANSWER))
        self.assertLessEqual(abs(ratio - slow_ms / fast_ms), Fraction(5, 100) * ratio)


@unittest.skipUnless(PLUGIN_HEADER.exists(), "ForgePact is not checked out")
class LeverParity(unittest.TestCase):
    """The plugin's lever (ForgePact's Mark1Movement.hpp) uses the model's
    constants, so the half walk the tests above prove is the one that ships."""

    @classmethod
    def setUpClass(cls):
        cls.header = PLUGIN_HEADER.read_text(encoding="utf-8")

    def constant(self, kind, name):
        found = re.search(r"inline constexpr " + kind + r" " + name + r" = ([^;]+);", self.header)
        self.assertIsNotNone(found, name + " is not in Mark1Movement.hpp")
        return found.group(1).strip()

    def number(self, name):
        return Fraction(self.constant("double", name))

    def test_the_offset_is_the_models(self):
        self.assertEqual(self.number("kStepOffset"), Fraction(model.STEP_OFFSET))

    def test_the_cap_is_the_models(self):
        capped = self.constant("bool", "kStepCapped")
        if model.STEP_CAP is None:
            self.assertEqual(capped, "false")
        else:
            self.assertEqual(capped, "true")
            self.assertEqual(self.number("kStepCap"), Fraction(model.STEP_CAP))

    def test_the_stat_id_is_the_models(self):
        self.assertEqual(self.number("kMovementSpeedStatId"), model.MOVEMENT_SPEED_STAT_ID)

    def test_the_ratio_is_half(self):
        self.assertEqual(self.number("kWalkRatio"), Fraction(1, 2))

    def test_the_route_is_the_models(self):
        self.assertEqual(self.constant("std::string_view", "kSpeedRoute"), '"' + model.SPEED_ROUTE + '"')

    def test_the_plugins_formula_is_the_models_inverse(self):
        # The header's formula, evaluated here with its own constants, gives
        # the answer the model says halves the step at every swept answer.
        self.assertIn("return kWalkRatio * (counted + kStepOffset) - kStepOffset;", self.header)
        ratio, offset = self.number("kWalkRatio"), self.number("kStepOffset")
        low, high = model.MEASURED_ANSWERS
        for answer in [low + (high - low) * i / 12 for i in range(13)] + [Fraction(SORAK_ANSWER)]:
            with self.subTest(answer=answer):
                plugin = ratio * (answer + offset) - offset
                self.assertEqual(plugin, model.answer_for_ratio(answer, Fraction(1, 2)))
                self.assertEqual(plugin, mark1_stat_model_answer(answer))


class SpecTests(unittest.TestCase):
    """The spec carries the headings every model spec carries, and its numbers
    agree with the model's."""

    def test_spec_headings(self):
        text = SPEC_DOC.read_text(encoding="utf-8").replace("\r\n", "\n")
        for heading in ("## Static reading", "## Measured", "## Our code",
                        "## Not established", "## The model",
                        "## What the model cannot catch"):
            self.assertIn("\n" + heading + "\n", text)

    def test_spec_names_the_models_constants(self):
        text = SPEC_DOC.read_text(encoding="utf-8")
        self.assertIn("STEP_OFFSET", text)
        self.assertIn("200", text)
        self.assertIn("stat-model", text)


if __name__ == "__main__":
    unittest.main()
