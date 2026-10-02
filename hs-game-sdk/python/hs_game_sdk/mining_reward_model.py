"""A model of what one Hero Siege mining dig pays (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured or not established, in
`docs/models/mining-reward-spec.md`. The measurements this model is checked
against are `hs-game-sdk/curated/mining_reward_measurements.json`, and
`tests/test_mining_reward_model.py` holds the checks.

One dig (`gml_Script_MiningNodeStepMain`) pays in two parts:

1. **The node's ore list.** The node already holds a list of ore kinds, filled
   when it was created. The dig counts the entries per kind and drops each kind
   present once, through `gml_Script_LootGroundCreate` with item type 14 and a
   params struct whose base `b` names the kind (27 to 32) and whose `o` carries
   the count, written only when the count is above one. Nothing is drawn at dig
   time for which ore or how much.
2. **Stat-gated bonus finds.** Several independent rolls, each passing only when
   a stat from `gml_Script_ReturnSpecificStat` is above zero and an inclusive
   whole-number draw from 0 to a cap comes out below it.

This module models the game only. ForgePact's levers (Mining Ore Multiplier,
the Miner's Helmet's x4, Mining Ore Extra Rolls) are that mod's own code and
live in the test as transforms of this module's output, so this file never has
to follow a ForgePact change.

Everything here is deterministic: nothing draws a random number, and nothing
tries to reproduce the game's own random sequence. The unknowns are explicit
parameters, and their defaults are hypotheses, listed in `HYPOTHESES`.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import mining_reward_model`.
"""

from __future__ import annotations

import math
from typing import Iterable, List

from .item_type import ItemType

# The six ore kinds, in the order of their Material bases (static reading,
# matching `docs/RUNTIME_DATA_MODELS.md` section 12). The game's own list
# entries are not established; these names are the model's.
ORE_BASES = {
    "copper": 27,
    "iron": 28,
    "gold": 29,
    "ruby": 30,
    "jade": 31,
    "tarethium": 32,
}

# The item type every ore stack is dropped with (Material).
ORE_ITEM_TYPE = int(ItemType.MATERIAL)

# HYPOTHESIS: the cap of a bonus roll's draw. It is the literal 99 at one
# roll site; the other sites compute theirs, and those values were not read.
DEFAULT_BONUS_CAP = 99

HYPOTHESES = {
    "DEFAULT_BONUS_CAP": (
        "Hypothesis, not established for most sites: a bonus roll draws from 0 "
        "to 99 inclusive. 99 is a literal at one site only; the other sites' "
        "caps are computed and were not read."),
    "ORE_BASES": (
        "Static reading, but the names are the model's: the game's own list "
        "entries are not established, only the six bases they drop."),
}


def dig_stacks(kinds: Iterable[str]) -> List[dict]:
    """The ore stacks one dig drops from a node whose list holds `kinds`.

    One params-shaped dict per kind present, in base order: `{"b": base}` when
    the kind appears once (no `o`, which the game reads as one) and
    `{"b": base, "o": count}` when it appears more often. An empty list drops
    nothing.
    """
    counts = {}
    for kind in kinds:
        if kind not in ORE_BASES:
            raise ValueError(f"unknown ore kind {kind!r}; known: {sorted(ORE_BASES)}")
        counts[kind] = counts.get(kind, 0) + 1
    stacks = []
    for kind, base in sorted(ORE_BASES.items(), key=lambda item: item[1]):
        count = counts.get(kind, 0)
        if count == 1:
            stacks.append({"b": base})
        elif count > 1:
            stacks.append({"b": base, "o": count})
    return stacks


def stack_quantity(stack: dict) -> int:
    """A stack's quantity: its `o`, or one when `o` is absent."""
    return stack.get("o", 1)


def total_ore(stacks: Iterable[dict]) -> int:
    """The ore pieces a list of stacks carries, over every kind."""
    return sum(stack_quantity(s) for s in stacks)


def bonus_roll_probability(stat: float, cap: int = DEFAULT_BONUS_CAP) -> float:
    """Probability that one stat-gated bonus roll pays.

    The roll pays only when `stat` is above zero and a whole-number draw from
    0 to `cap` inclusive (`cap + 1` outcomes) is below `stat`, which happens on
    min(cap + 1, ceil(stat)) of the outcomes. A stat of 0 or less never pays.
    """
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
        raise ValueError(f"cap must be a whole number of zero or more, got {cap!r}")
    if not stat > 0:            # also rejects NaN
        return 0.0
    outcomes = cap + 1
    if math.isinf(stat):
        return 1.0
    return min(outcomes, math.ceil(stat)) / outcomes


def expected_bonus_hits(stat: float, rolls: int, cap: int = DEFAULT_BONUS_CAP) -> float:
    """Expected bonus finds from `rolls` independent draws of one roll site."""
    return bonus_roll_probability(stat, cap) * rolls


def probability_of_no_bonus(stat: float, rolls: int, cap: int = DEFAULT_BONUS_CAP) -> float:
    """Probability that `rolls` independent draws of one roll site all miss."""
    return (1.0 - bonus_roll_probability(stat, cap)) ** rolls
