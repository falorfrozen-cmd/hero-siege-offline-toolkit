"""The walk's step against the movement speed stat (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, our code or not established, in
`docs/models/movement-speed-spec.md`. `tests/test_movement_speed_model.py`
holds the checks, and `curated/movement_speed_measurements.json` the points
they replay.

- The player's walk moves a modal step per frame that is affine in the answer
  the stat dispatcher gives for id 64 (movement speed): proportional to the
  answer plus STEP_OFFSET, about 200 (measured, ForgePact#166 Mod live 1).
  No cap was reached up to an answer of 226.5, and negative answers slow the
  walk further.
- The step also tracks the frame clock, so its scale (px per point of
  answer-plus-offset) belongs to one window at one frame time and is a
  parameter here, never a constant. Ratios of two answers are not.

This module models the game only. Mark 1's speed lever, which answers the
local player's id-64 calls with a halved value, is ForgePact's own code and
lives in the test as an input transform.

Every value is an exact `Fraction` or an int. Nothing here draws a random
number.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import movement_speed_model`.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Optional, Union

#: `ReturnSpecificStat`'s stat id for `StatMovementSpeed` (static reading,
#: RDM § 19.10).
MOVEMENT_SPEED_STAT_ID = 64
#: The answer is added to this before the walk scales by it: the step is
#: proportional to answer + 200 (measured, Mod live 1's `speed-sweep`; the
#: least-squares fit over the seven points is 200.0). Read for this game
#: build only; where in the Step event it is applied was not read. This is
#: the k of the plan's stat-model route.
STEP_OFFSET = 200
#: The answer above which the step stops growing: None, since no cap was
#: reached up to an answer of 226.5 (measured). This is the C of the plan's
#: stat-model route, None when it was not reached.
STEP_CAP: Optional[Fraction] = None
#: The answers the sweep measured the step at (measured, inclusive). Outside
#: this range the model extrapolates the same line.
MEASURED_ANSWERS = (Fraction(-151, 2), Fraction(453, 2))

#: Which lever the Phase 2 decision picked for Mark 1's half speed, and why
#: (ForgePact docs/mark1-set-research.md § Phase 2 decision).
SPEED_ROUTE = "stat-model"
SPEED_ROUTE_REASON = (
    "One affine shape fits every swept point within 0.02% and the "
    "interpolated answer gave a ratio of 0.500 (speed-sweep, speed-half), so "
    "the walk can be halved through the id-64 answer alone; no movement "
    "builtin moves the walk (speed-builtin) and halving hSpeedFactor and "
    "vSpeedFactor changed nothing (speed-factor), so neither other route "
    "qualifies. Because the step is affine, not proportional, halving the "
    "answer gives 0.785, not 0.5: the lever answers (x - STEP_OFFSET) / 2."
)

Number = Union[Fraction, int, float, str]


def _frac(value: Number) -> Fraction:
    return Fraction(value)


def effective_answer(answer: Number, cap: Optional[Number] = STEP_CAP) -> Fraction:
    """The answer the walk counts: the dispatcher's answer, stopped at `cap`
    when there is one (none was measured)."""
    value = _frac(answer)
    if cap is not None:
        value = min(value, _frac(cap))
    return value


def step_weight(answer: Number, offset: Number = STEP_OFFSET,
                cap: Optional[Number] = STEP_CAP) -> Fraction:
    """What the step is proportional to: effective_answer(answer) + offset.

    A weight of 0 or less is outside anything measured (the lowest measured
    answer, -75.5, still walked forward), so it raises rather than guess.
    """
    weight = effective_answer(answer, cap) + _frac(offset)
    if weight <= 0:
        raise ValueError("an answer at or below -offset is not established")
    return weight


def modal_step(answer: Number, step_per_point: Number, offset: Number = STEP_OFFSET,
               cap: Optional[Number] = STEP_CAP) -> Fraction:
    """The walk's modal step in px per frame for one window.

    `step_per_point` is that window's scale, which moves with the frame time;
    `step_per_point_from` derives it from a window whose answer is known.
    """
    return step_weight(answer, offset, cap) * _frac(step_per_point)


def step_per_point_from(reference_step: Number, reference_answer: Number,
                        offset: Number = STEP_OFFSET,
                        cap: Optional[Number] = STEP_CAP) -> Fraction:
    """The scale of a window from its modal step and the answer it walked at."""
    return _frac(reference_step) / step_weight(reference_answer, offset, cap)


def step_ratio(answer: Number, reference_answer: Number, offset: Number = STEP_OFFSET,
               cap: Optional[Number] = STEP_CAP) -> Fraction:
    """The modal step at `answer` over the modal step at `reference_answer`,
    both at the same frame time. Independent of the window's scale."""
    return step_weight(answer, offset, cap) / step_weight(reference_answer, offset, cap)


def scaled_answer_ratio(multiplier: Number, answer: Number,
                        offset: Number = STEP_OFFSET,
                        cap: Optional[Number] = STEP_CAP) -> Fraction:
    """The step ratio when the dispatcher's answer is multiplied by
    `multiplier`, the lever Mod live 1's `speed-sweep` applied."""
    return step_ratio(_frac(answer) * _frac(multiplier), answer, offset, cap)


def answer_for_ratio(answer: Number, ratio: Number, offset: Number = STEP_OFFSET,
                     cap: Optional[Number] = STEP_CAP) -> Fraction:
    """The answer that makes the step `ratio` times what `answer` gives:
    ratio * (effective_answer + offset) - offset. The result sits below any
    cap when ratio is at most 1, so it is not capped again."""
    return _frac(ratio) * step_weight(answer, offset, cap) - _frac(offset)
