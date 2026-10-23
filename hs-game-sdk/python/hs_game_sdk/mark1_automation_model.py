"""The Mark 1 automation's proc interval and its mana cost (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, assumption or not established, in
`docs/models/mark1-automation-spec.md`. `tests/test_mark1_automation_model.py`
holds the checks, and `hs-game-sdk/curated/mark1_automation_cases.json` the
cases ForgePact's C++ cores (`Mark1Priority.hpp`, `Mark1Cost.hpp`) are held
to as well.

- The proc route fires each automated skill at its own interval: its cooldown
  at the player's Skill Haste plus its cast time at the player's Faster Cast
  Rate. A skill with no cooldown fires at its cast time.
- The free procs carry a mana cost. The shipped one is a drain: the game's own
  mana replenish answer, lowered by a share of maximum mana per automated
  skill per second, divided by the measured replenish unit. The documented
  alternative cuts maximum mana by a share per automated skill.

The Skill Haste arithmetic is `skill_stat_model`'s, reused rather than
restated. Every value is an exact `Fraction` or an int. Nothing here draws a
random number.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import mark1_automation_model`.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Optional, Union

from hs_game_sdk import skill_stat_model

Number = Union[Fraction, int]

#: `ReturnSpecificStat`'s stat id for `StatMaxMana` (static reading).
MAX_MANA_STAT_ID = 37
#: `ReturnSpecificStat`'s stat id for `StatManaReplenish` (static reading).
MANA_REPLENISH_STAT_ID = 42
#: `ReturnSpecificStat`'s stat id for `StatManaPerKill` (static reading).
MANA_PER_KILL_STAT_ID = 46
#: Skill Haste and Faster Cast Rate, as `skill_stat_model` names them.
SKILL_HASTE_STAT_ID = skill_stat_model.SKILL_HASTE_STAT_ID
FASTER_CAST_RATE_STAT_ID = skill_stat_model.FASTER_CAST_RATE_STAT_ID

# ---- The interval ----

#: A talent whose `abilityCooldown` is at most this many seconds has no
#: cooldown (measured, RDM § 7.1: 0.25 means "no cooldown").
NO_COOLDOWN_SECONDS = Fraction(1, 4)
#: The cast time at 0 Faster Cast Rate, in seconds. Provisional: the stat's own
#: description says Faster Cast Rate is always counted from one cast a second
#: (static reading of the semantics file); the game's base is per talent and
#: not established. Live 1 measures it (`cast-base:`).
BASE_CAST_SECONDS = Fraction(1)
#: The cast-speed divisor, 1 + fcr / 100, is never taken below this (our
#: code: keeps a large negative Faster Cast Rate from dividing by zero).
CAST_DIVISOR_FLOOR = Fraction(1, 10)

# ---- The mana cost ----

#: Proposed drain per automated (proc) skill, in % of maximum mana per second:
#: half the assumed baseline replenish (the owner's call, proposal).
DRAIN_PCT_PER_SECOND = Fraction(1)
#: The alternative: maximum mana cut per automated skill, in % (the owner's
#: number, proposal).
MAX_MANA_CUT_PCT = 20
#: How many mana per second one unit of the replenish answer (id 42) is.
#: Measured: 0.745 per drained unit, in process, Stats live 3's S7 minus S8
#: (35.05 mana a second over 47.04 drained units; S7 alone read 0.874 a unit of
#: the answer). The drain divides by it, so each automated skill takes about
#: DRAIN_PCT_PER_SECOND % of maximum mana a second (the owner's choice,
#: 2026-10-23). Stats live 5 then measured that rate: 1.117% a second per
#: skill at about 144 frames a second and 0.956% at 60. ForgePact's
#: `kMark1ReplenishUnit` is the same.
REPLENISH_UNIT = Fraction(745, 1000)

# ---- Assumptions the reference table is built on (Live 1 `regen-units`) ----

#: Maximum mana of the reference character. Assumption.
ASSUMED_MAX_MANA = 1500
#: Replenish with no investment, in % of maximum mana per second. Assumption:
#: Energy gives 4 mana and 0.175 replenish a point (static reading), and about
#: half the pool is taken to come from Energy.
ASSUMED_BASE_REPLENISH_PCT = Fraction(2)
#: Reference investment: +100% Replenish Mana (item key 63). Assumption that it
#: scales the base replenish; not established.
REFERENCE_REPLENISH_PCT = 100
#: Reference investment: +20 Mana per second (item key 65). Assumption.
REFERENCE_MANA_PER_SECOND = 20
#: Reference investment: +10 Mana After each Kill (item key 66) at one kill a
#: second. Assumption.
REFERENCE_MANA_PER_KILL = 10
REFERENCE_KILLS_PER_SECOND = 1


def _non_negative_columns(columns: int) -> int:
    if columns < 0:
        raise ValueError("a negative count of automated skills means nothing")
    return columns


def cooldown_seconds(ability_cooldown: Number, haste: Number) -> Fraction:
    """A talent's cooldown at a Skill Haste total: 0 when `ability_cooldown` is
    at most NO_COOLDOWN_SECONDS, otherwise the cooldown times
    `skill_stat_model.cooldown_fraction(haste)` (haste counted up to 200)."""
    cooldown = Fraction(ability_cooldown)
    if cooldown <= NO_COOLDOWN_SECONDS:
        return Fraction(0)
    return cooldown * skill_stat_model.cooldown_fraction(haste)


def cast_seconds(fcr: Number, base_cast_seconds: Number = BASE_CAST_SECONDS) -> Fraction:
    """The cast time at a Faster Cast Rate total: base / (1 + fcr / 100), the
    divisor never below CAST_DIVISOR_FLOOR."""
    base = Fraction(base_cast_seconds)
    if base < 0:
        raise ValueError("a cast cannot take negative time")
    divisor = max(1 + Fraction(fcr) / 100, CAST_DIVISOR_FLOOR)
    return base / divisor


def interval_ms(ability_cooldown: Number, haste: Number, fcr: Number,
                base_cast_seconds: Number = BASE_CAST_SECONDS) -> Fraction:
    """Milliseconds between two procs of one skill: its cooldown plus its cast
    time (the owner's rule). A skill with no cooldown fires each cast time."""
    return 1000 * (cooldown_seconds(ability_cooldown, haste)
                   + cast_seconds(fcr, base_cast_seconds))


def drain_per_second(proc_columns: int, percent: Number, max_mana: Number,
                     unit: Number = REPLENISH_UNIT) -> Fraction:
    """How much the drain takes off the replenish answer, in units of that
    answer: `proc_columns` automated skills, each `percent` % of `max_mana` a
    second, divided by `unit` (the mana a second one unit is). Pass `unit=1`
    for the drain in mana a second, which is the same whatever the unit."""
    columns = _non_negative_columns(proc_columns)
    if Fraction(max_mana) < 0:
        raise ValueError("maximum mana cannot be negative")
    if Fraction(unit) <= 0:
        raise ValueError("a replenish unit must be a positive number of mana a second")
    return columns * Fraction(percent) / 100 * Fraction(max_mana) / Fraction(unit)


def replenish_answer(original: Number, proc_columns: int, max_mana: Number,
                     percent: Number = DRAIN_PCT_PER_SECOND,
                     unit: Number = REPLENISH_UNIT) -> Fraction:
    """The answer the set's consumer gives for id 42: the game's own answer
    minus the drain (divided by `unit`), never below minus `max_mana`. With no
    proc column the original is left alone."""
    if _non_negative_columns(proc_columns) == 0:
        return Fraction(original)
    lowered = Fraction(original) - drain_per_second(proc_columns, percent, max_mana, unit)
    return max(lowered, -Fraction(max_mana))


def cut_max_mana(proc_columns: int, cut_pct: Number, max_mana: Number) -> Fraction:
    """The alternative's answer for id 37: `max_mana` less `cut_pct` % per
    automated skill, never below 0. With no proc column it is left alone."""
    columns = _non_negative_columns(proc_columns)
    if columns == 0:
        return Fraction(max_mana)
    return max(Fraction(max_mana) * (1 - Fraction(cut_pct) / 100 * columns), Fraction(0))


def regen_per_second(max_mana: Number, base_regen_pct: Number, replenish_pct: Number = 0,
                     mana_per_second: Number = 0, mana_per_kill: Number = 0,
                     kills_per_second: Number = 0) -> Fraction:
    """Mana a character gains a second with no drain: the base replenish (in %
    of `max_mana` a second) raised by `replenish_pct` % (assumption: Replenish
    Mana scales the base), plus flat mana per second, plus mana per kill at
    `kills_per_second`."""
    base = Fraction(base_regen_pct) / 100 * Fraction(max_mana)
    return (base * (1 + Fraction(replenish_pct) / 100) + Fraction(mana_per_second)
            + Fraction(mana_per_kill) * Fraction(kills_per_second))


def net_mana_per_second(max_mana: Number, base_regen_pct: Number, replenish_pct: Number,
                        mana_per_second: Number, mana_per_kill: Number,
                        kills_per_second: Number, drain: Number) -> Fraction:
    """`regen_per_second(...)` less `drain` (mana per second, as
    `drain_per_second` gives it)."""
    return regen_per_second(max_mana, base_regen_pct, replenish_pct, mana_per_second,
                            mana_per_kill, kills_per_second) - Fraction(drain)


def is_sustained(net: Number) -> bool:
    """Whether a full pool stays full: the net is 0 or more."""
    return Fraction(net) >= 0


def seconds_to_empty(max_mana: Number, net: Number) -> Optional[Fraction]:
    """Seconds a full pool of `max_mana` lasts at `net` mana a second, or None
    when it is sustained (never empties)."""
    if is_sustained(net):
        return None
    return Fraction(max_mana) / -Fraction(net)
