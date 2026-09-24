"""A model of Hero Siege's two-stage drop roll (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured or not established, in
`docs/models/drop-roll-spec.md`. The measurements this model is checked
against are `hs-game-sdk/curated/drop_roll_measurements.json`, and
`tests/test_drop_roll_model.py` holds the checks.

Two stages decide whether a monster drops something from a family:

1. **The gate** (`gml_Script_LoadDrops`). For each drop type a monster lists,
   the game draws a whole number from its own die and runs that type's
   `Drop*` script only when the draw is below the monster's chance for the
   type. Because the draw is whole, any chance in (0, 1] behaves like 1.
2. **The inner roll** (`droprate.base`). The `Drop*` script picks an item and
   rolls against its "1 in N" base, after an adjustment the model carries as
   one unknown scale `s`. `DropRelic` has no such roll: it does not read the
   base at all.

This module models the game only. ForgePact's levers (`droprate group`,
`dungeonkey`, the relic pre-roll) are that mod's own code and live in the
test as input transforms, so this file never has to follow a ForgePact change.

Everything here is a deterministic, analytic probability: nothing draws a
random number, and nothing tries to reproduce the game's own random sequence.
The unknowns are explicit parameters, and their defaults are hypotheses,
listed in `HYPOTHESES`.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import drop_roll_model`.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

# HYPOTHESIS: the number of outcomes of the gate's die. Its range comes from a
# value the game fills at runtime, so no static reading gives it; native
# chances run from 1 to 100 and 100 is used as a certain drop, which suggests
# 100 outcomes. Whether the top value is included is not established either.
DEFAULT_DIE_OUTCOMES = 100

# HYPOTHESIS: the whole adjustment the dungeon-key script applies to a key's
# base before its inner roll (the chances slot-13 factor, a luck term and
# further optional arguments). Neither its direction nor its form is
# established; M3 to M5 bound it only loosely.
DEFAULT_INNER_SCALE = 1.0

HYPOTHESES = {
    "DEFAULT_DIE_OUTCOMES": (
        "Hypothesis, not established: the gate die has 100 outcomes. The value is "
        "filled at runtime; native chances of 1..100, with 100 used as certain, "
        "suggest it. One trace of the die's range would pin it."),
    "DEFAULT_INNER_SCALE": (
        "Hypothesis, not established: the dungeon-key inner roll hits with "
        "probability s / base with s = 1. The slot-13 factor (natively 0.7) and a "
        "luck term enter s, in a direction not yet read."),
}


def gate_probability(chance: float, die_outcomes: int = DEFAULT_DIE_OUTCOMES) -> float:
    """Probability that the `LoadDrops` gate runs a type's `Drop*` script.

    The game draws a whole number in [0, die_outcomes) and passes when the draw
    is below `chance`. A chance of 0 or less never passes; any positive chance
    passes on ceil(chance) of the outcomes, so 0.5 and 0.01 both mean "only
    on a draw of zero".
    """
    if isinstance(die_outcomes, bool) or not isinstance(die_outcomes, int) or die_outcomes < 1:
        raise ValueError(f"die_outcomes must be a positive whole number, got {die_outcomes!r}")
    if not chance > 0:          # also rejects NaN
        return 0.0
    if math.isinf(chance):
        return 1.0
    return min(1.0, math.ceil(chance) / die_outcomes)


def inner_probability(base: float, inner_scale: float = DEFAULT_INNER_SCALE) -> float:
    """Probability that an item's own "1 in `base`" roll hits, after the gate.

    `inner_scale` is the unknown adjustment `s`; the hit probability is
    min(1, s / base).
    """
    if not base > 0:
        raise ValueError(f"base must be positive, got {base!r}")
    if not inner_scale >= 0:
        raise ValueError(f"inner_scale must be zero or more, got {inner_scale!r}")
    return min(1.0, inner_scale / base)


def dungeon_key_call_probability(key_bases: Sequence[float],
                                 inner_scale: float = DEFAULT_INNER_SCALE) -> float:
    """Probability that one `DropDungeonKeys` call places a key.

    The script picks one key uniformly from the pool `GetDungeonKeys` returns,
    then rolls that key's own base, so the chance of a key is the mean of the
    keys' inner probabilities.
    """
    bases = list(key_bases)
    if not bases:
        raise ValueError("key_bases must name at least one key")
    return sum(inner_probability(b, inner_scale) for b in bases) / len(bases)


def dungeon_key_probability(chance: float, key_bases: Sequence[float], *,
                            die_outcomes: int = DEFAULT_DIE_OUTCOMES,
                            inner_scale: float = DEFAULT_INNER_SCALE) -> float:
    """Probability that one type-12 `LoadDrops` call ends with a key on the
    ground: the gate, then one `DropDungeonKeys` call."""
    return (gate_probability(chance, die_outcomes)
            * dungeon_key_call_probability(key_bases, inner_scale))


def relic_roll_probability(chance: float, *,
                           die_outcomes: int = DEFAULT_DIE_OUTCOMES) -> float:
    """Probability that `DropRelic` runs for one relic-type `LoadDrops` call.

    `DropRelic` does not read `droprate.base` (measured, M7), so there is no
    base-driven inner roll and this function deliberately takes no base: the
    gate is the whole of what a base-side lever could move. What `DropRelic`
    does after it runs (which relic, and any filtering) is not modelled.
    """
    return gate_probability(chance, die_outcomes)


def expected_hits(probability: float, trials: int) -> float:
    """Expected number of hits in `trials` independent rolls."""
    return probability * trials


def probability_of_no_hit(probability: float, trials: int) -> float:
    """Probability that `trials` independent rolls all miss."""
    return (1.0 - probability) ** trials


def binomial_band(trials: int, probability: float, sigmas: float = 3.0) -> tuple:
    """(low, high) count band: the binomial mean plus or minus `sigmas`
    standard deviations. A certain or impossible roll has zero width."""
    mean = trials * probability
    spread = sigmas * math.sqrt(trials * probability * (1.0 - probability))
    return (mean - spread, mean + spread)


def observation_within(passes: int, trials: int, low_probability: float,
                       high_probability: float, sigmas: float = 3.0) -> bool:
    """Whether `passes` in `trials` is consistent with some probability in
    [low_probability, high_probability], within `sigmas` of the binomial."""
    low, _ = binomial_band(trials, low_probability, sigmas)
    _, high = binomial_band(trials, high_probability, sigmas)
    return low <= passes <= high


def consistent_die_outcomes(passes: int, trials: int, chance_low: float,
                            chance_high: float, candidates: Iterable[int],
                            sigmas: float = 3.0) -> tuple:
    """Every candidate die-outcome count under which `passes` in `trials` is
    consistent with a monster whose chance lies in [chance_low, chance_high]."""
    return tuple(
        n for n in candidates
        if observation_within(passes, trials, gate_probability(chance_low, n),
                              gate_probability(chance_high, n), sigmas))
