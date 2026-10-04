"""Projectile amount, projectile speed and AoE size (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, our code or not established, in
`docs/models/skill-sliders-spec.md`. `tests/test_skill_sliders_model.py` holds
the checks.

- Projectile amount: `ReturnExtraSpellProjectiles` returns a skill's adjusted
  total (its base, raised by a percent stat and floored, plus a flat stat), and
  `ReturnExtraProjectilesRanged` returns only an extra count that its caller
  adds to its own base.
- AoE size: stat 554 times 0.01 times the caller's factor is added to element
  1086 of the modifier array, and `LoadProjectileSettings` adds that element to
  the projectile's scale.
- Projectile speed: stats 74 (flat) and 75 (percent) are stored in elements
  1084 and 1085; on the projectile's `deltaSpeed`, 75 acts as a percent
  multiplier and 74 as a flat addition scaled by `roomSpd`.

What the static reading leaves open (the scale `LoadAllModifiers` applies to
stats 74 and 75, the order they combine in, the factor callers pass for AoE,
whether a chance-based bonus came up) is an explicit parameter here, never a
guessed constant.

This module models the game only. ForgePact's research levers (`projprobe`,
ForgePact#160) are that mod's own code and live in the test as input
transforms.

Every value is an exact `Fraction` or an int. Nothing here draws a random
number.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import skill_sliders_model`.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Iterable, Tuple, Union

#: `ReturnSpecificStat`'s stat id for `StatAOESkillSize` (static reading).
AOE_SKILL_SIZE_STAT_ID = 554
#: The two stats `LoadAOEModifiers` adds the same way when its fourth argument
#: is true (static reading).
AOE_EXTRA_STAT_IDS = (552, 553)
#: The percent stat `ReturnExtraSpellProjectiles` raises its base by (static reading).
SPELL_PROJECTILES_PERCENT_STAT_ID = 394
#: The flat stat `ReturnExtraSpellProjectiles` adds (static reading).
SPELL_PROJECTILES_FLAT_STAT_ID = 311
#: `ReturnExtraProjectilesRanged`'s starting stat (static reading).
RANGED_PROJECTILES_FLAT_STAT_ID = 239
#: The chance stat of its one-more roll (static reading).
RANGED_ONE_MORE_CHANCE_STAT_ID = 240
#: The chance and bonus stats of its looked-up roll (static reading).
RANGED_BONUS_CHANCE_STAT_ID = 451
RANGED_BONUS_STAT_ID = 452
#: The projectile-speed stats: 74 the flat form, 75 the percent form (static
#: reading, by where they are stored; that they are the tooltip's "Projectile
#: Speed" is not established).
PROJECTILE_SPEED_FLAT_STAT_ID = 74
PROJECTILE_SPEED_PERCENT_STAT_ID = 75
#: Modifier-array elements (static reading).
SPEED_FLAT_ELEMENT = 1084
SPEED_PERCENT_ELEMENT = 1085
AOE_SCALE_ELEMENT = 1086
#: One point of a percent stat, as both helpers and `LoadAOEModifiers` use it:
#: 0.01 (static reading; a named global whose value was inferred from its use).
PER_POINT = Fraction(1, 100)
#: The two orders in which the speed stats could combine on `deltaSpeed`; which
#: one the game uses is not established until measured.
SPEED_ORDERS = ("multiply_first", "add_first")

Number = Union[Fraction, int]


def spell_projectile_total(base: Number, more_percent: Number = 0, extra: Number = 0) -> Fraction:
    """What `ReturnExtraSpellProjectiles(player, x, base)` returns: the adjusted total.

    When `more_percent` (stat 394) is above 0, `base` becomes
    `floor(base * (1 + more_percent * 0.01))`; otherwise it is kept as given.
    `extra` (stat 311) is then added.
    """
    total = Fraction(base)
    if Fraction(more_percent) > 0:
        total = Fraction(math.floor(total * (1 + Fraction(more_percent) * PER_POINT)))
    return total + Fraction(extra)


def ranged_extra_projectiles(flat: Number, bonus: Number = 0, bonus_rolled: bool = False,
                             one_more_rolled: bool = False) -> Fraction:
    """What `ReturnExtraProjectilesRanged(player, x)` returns: the extra count only.

    A sum of three parts: the flat stat 239, the chance-based bonus worth stat
    452 (its chance from stat 451, for some skills only) and the chance-based
    single extra (its chance from stat 240). Whether each chance came up is an
    input, because the chances' scale and which skills qualify are not
    established.
    """
    return (Fraction(flat)
            + (Fraction(bonus) if bonus_rolled else 0)
            + (1 if one_more_rolled else 0))


def ranged_projectile_total(base: Number, extra: Number) -> Fraction:
    """The caller's own base plus `ReturnExtraProjectilesRanged`'s extra."""
    return Fraction(base) + Fraction(extra)


def aoe_scale_bonus(stat554: Number, factor: Number = 1, also: Iterable[Number] = ()) -> Fraction:
    """What one `LoadAOEModifiers` pass adds to element 1086.

    Each stat (554, and `also` - stats 552 and 553 when the caller's fourth
    argument is true) times 0.01 times `factor`, the caller's sixth argument,
    whose usual value is not established.
    """
    total = Fraction(stat554)
    for value in also:
        total += Fraction(value)
    return total * PER_POINT * Fraction(factor)


def projectile_scale(base_scale: Number, element_1086: Number) -> Fraction:
    """The scale (`image_xscale`, and the same for `image_yscale`) that
    `LoadProjectileSettings` leaves: the element is added only when it is above 0."""
    element = Fraction(element_1086)
    return Fraction(base_scale) + (element if element > 0 else 0)


def stored_speed_elements(stat74: Number, stat75: Number, flat_scale: Number,
                          percent_scale: Number) -> Tuple[Fraction, Fraction]:
    """Elements 1084 and 1085 as `LoadAllModifiers` stores them.

    Whether it stores the stats as read or scales them first was not read, so
    both scales are required parameters (pass 1 for "as read").
    """
    return Fraction(stat74) * Fraction(flat_scale), Fraction(stat75) * Fraction(percent_scale)


def projectile_delta_speed(delta_speed: Number, percent_element: Number = 0,
                           flat_element: Number = 0, room_spd: Number = 1, *, order: str) -> Fraction:
    """The `deltaSpeed` `LoadProjectileSettings` leaves on a projectile.

    The percent element acts as a multiplier of `1 + percent_element` and the
    flat element as an addition of `flat_element * room_spd`, `room_spd` being
    the game's global speed factor. Which of the two applies first is for
    ForgePact#160's Live 1 to measure, so `order` (one of `SPEED_ORDERS`) has no
    default. What either does at 0 or below is not established; the model only
    claims non-negative elements.
    """
    if order not in SPEED_ORDERS:
        raise ValueError("order must be one of %r, not %r" % (SPEED_ORDERS, order))
    multiplier = 1 + Fraction(percent_element)
    addition = Fraction(flat_element) * Fraction(room_spd)
    if order == "add_first":
        return (Fraction(delta_speed) + addition) * multiplier
    return Fraction(delta_speed) * multiplier + addition
