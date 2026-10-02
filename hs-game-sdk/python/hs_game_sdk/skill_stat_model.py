"""How Skill Haste and All Skills reach a skill (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, our code or not established, in
`docs/models/skill-stat-spec.md`. `tests/test_skill_stat_model.py` holds the
checks.

- Skill Haste sets how fast a skill's cooldown runs out: each step the game
  lowers the time left by `(1 + haste * 0.005) * deltaSpd`, so a cooldown
  lasts its base time divided by `1 + haste / 200`. The game counts at most
  200 Skill Haste, so a cooldown never takes less than half its base time.
- All Skills raises the level of a talent that has at least one allocated
  point, and only when the level is read with its bonuses.

This module models the game only. ForgePact's `statadd` boosts
(ForgePact#114), which add to the stat totals before the game uses them, are
that mod's own code and live in the test as input transforms.

Every value is an exact `Fraction` or an int. Nothing here draws a random
number.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import skill_stat_model`.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Union

#: `ReturnSpecificStat`'s stat id for `StatSpellHaste` (static reading).
SKILL_HASTE_STAT_ID = 103
#: `ReturnSpecificStat`'s stat id for `StatAllSkills` (static reading).
ALL_SKILLS_STAT_ID = 2
#: `ReturnSpecificStat`'s stat id for `StatFasterCastRate` (static reading).
FASTER_CAST_RATE_STAT_ID = 106
#: How much one point of Skill Haste adds to a skill cooldown's recovery per
#: step: 0.005 (static reading of `Controller_obj`'s Step event).
SKILL_HASTE_PER_POINT = Fraction(1, 200)
#: The one cooldown id the recovery step gives no haste (static reading).
NO_HASTE_COOLDOWN_ID = 75
#: The most Skill Haste the game counts (measured, ForgePact#114 Live 1):
#: totals of 240 and 340 ended a cooldown in as many steps as 200 did. Where
#: the game applies it is not established.
SKILL_HASTE_CAP = 200

Number = Union[Fraction, int]


def effective_haste(haste: Number) -> Fraction:
    """The Skill Haste the cooldown step counts: the total, stopped at SKILL_HASTE_CAP."""
    return min(Fraction(haste), Fraction(SKILL_HASTE_CAP))


def recovery_rate(haste: Number) -> Fraction:
    """How much cooldown time one step removes, with `deltaSpd` 1: 1 + haste / 200,
    with haste stopped at SKILL_HASTE_CAP (so at most 2).

    Negative totals are the game's business and pass through unchanged.
    """
    return 1 + effective_haste(haste) * SKILL_HASTE_PER_POINT


def cooldown_fraction(haste: Number) -> Fraction:
    """The part of its base time a skill cooldown takes: 1 / recovery_rate(haste),
    never below 1/2."""
    rate = recovery_rate(haste)
    if rate <= 0:
        raise ValueError("a recovery rate of 0 or less never ends the cooldown")
    return 1 / rate


def cooldown_steps(base_steps: Number, haste: Number, delta_spd: Number = 1) -> int:
    """Steps until a cooldown of `base_steps` reaches 0 or less.

    Each step lowers the time left by `recovery_rate(haste) * delta_spd`. A
    cooldown of 0 or less takes no step.
    """
    tick = recovery_rate(haste) * Fraction(delta_spd)
    if tick <= 0:
        raise ValueError("a step of 0 or less never ends the cooldown")
    remaining = Fraction(base_steps)
    if remaining <= 0:
        return 0
    return math.ceil(remaining / tick)


def talent_level(points: int, all_skills: Number = 0, other_bonus: Number = 0,
                 include_bonuses: bool = True) -> Fraction:
    """A talent's level as `ReturnTalentLevel` builds it.

    `points` is the allocated level. The bonuses (`all_skills` and any
    `other_bonus`, such as a class or element bonus) are added only when the
    caller asks for them and the talent has at least one point, so a bonus
    never unlocks a talent. There is no clamp.
    """
    if points < 0:
        raise ValueError("allocated points cannot be negative")
    level = Fraction(points)
    if include_bonuses and points > 0:
        level += Fraction(all_skills) + Fraction(other_bonus)
    return level
