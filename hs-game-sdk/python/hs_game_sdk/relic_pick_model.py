"""Which relic a relic drop yields (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, our code or not established, in
`docs/models/relic-pick-spec.md`. `tests/test_relic_pick_model.py` holds the
checks. It complements `drop_roll_model`, which answers *whether* a relic
drops; this module answers *which* one comes out once it does.

Three routines place a relic: `DropRelic`, `EnemyKillSatanicZoneRelic` and
`EnemyKillSatanicZoneRelicFeast`.
- Each draws `irandom(155)` and draws again while `GetRelicQuest` answers
  true, so every relic that is not a quest relic is equally likely.
- `DropRelic` and the Feast routine may then put a copy of one of the five
  equipped relics in its place, but only a relic below level 10.

This module models the game only. ForgePact's lever for ForgePact#125
(`GetRelicQuest` also answering true for a relic the player owns at 10/10) is
that mod's own code and lives in the test as an input transform.

Every probability is an exact `Fraction`. Nothing here draws a random number
or tries to reproduce the game's own random sequence. The one unknown, the
copy step's chance, is an explicit parameter.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import relic_pick_model`.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Dict, FrozenSet, Iterable, Optional, Sequence, Tuple, Union

#: The pick draws `irandom(155)`: ids 0..155 (static reading).
RELIC_ID_COUNT = 156
#: `GetRelicQuest` answers true for ids QUEST_RELIC_FIRST..155 and for no
#: other id (static reading).
QUEST_RELIC_FIRST = 141
#: The equipped relic slots `ReturnRandomPlayerRelic` chooses between,
#: `global.equippedItems[mplr][0][10..14]` (static reading).
EQUIPPED_RELIC_SLOTS = 5
#: The copy step copies an equipped relic only while its level `o` is below
#: this, which is the level the game refuses a pickup at (static reading).
MAXED_RELIC_LEVEL = 10
#: The copy step's bound for each routine, one per value (1, 2, 3) of the
#: protected game value that selects it. An empty tuple means the routine has
#: no copy step (static reading).
COPY_BOUNDS: Dict[str, Tuple[int, ...]] = {
    "DropRelic": (3, 6, 10),
    "EnemyKillSatanicZoneRelicFeast": (3, 5, 8),
    "EnemyKillSatanicZoneRelic": (),
}

#: One equipped relic slot: `(relic id, level)`, or None when it is empty.
Slot = Optional[Tuple[int, int]]
Probability = Union[Fraction, int]


def quest_relic_ids() -> FrozenSet[int]:
    """The ids `GetRelicQuest` answers true for: the pick never yields them."""
    return frozenset(range(QUEST_RELIC_FIRST, RELIC_ID_COUNT))


def pick_pool(quest: Iterable[int]) -> Tuple[int, ...]:
    """The ids the draw-again loop can end on: 0..155 minus every id the quest
    check answers true for, in ascending order.

    Raises ValueError when no id is left. The game's loop then never ends, which
    is why a lever that adds ids to the quest answer has to stand down first.
    """
    excluded = frozenset(quest)
    pool = tuple(i for i in range(RELIC_ID_COUNT) if i not in excluded)
    if not pool:
        raise ValueError("no relic id is left for the pick: the game's draw-again loop never ends")
    return pool


def copy_chance(bound: int, zrm: int) -> Fraction:
    """P(`irandom(zrm)` < bound). `irandom(zrm)` is uniform over 0..zrm."""
    if zrm < 0:
        raise ValueError("zrm must be 0 or more")
    return Fraction(min(max(bound, 0), zrm + 1), zrm + 1)


def pick_distribution(
    quest: Optional[Iterable[int]] = None,
    equipped: Sequence[Slot] = (),
    copy_chance: Probability = 0,
) -> Dict[int, Fraction]:
    """relic id -> probability that one placed relic is that relic.

    `quest` is the set the quest check answers true for, the game's own by
    default. `equipped` holds up to five slots and is padded with empty ones.
    `copy_chance` is the probability that the copy step fires, given that the
    chosen slot held a relic it may copy. Use 0 for
    `EnemyKillSatanicZoneRelic`, which has no copy step.

    Only ids with a non-zero probability are keys, and the values sum to 1.
    """
    quest_set = quest_relic_ids() if quest is None else frozenset(quest)
    if len(equipped) > EQUIPPED_RELIC_SLOTS:
        raise ValueError(f"at most {EQUIPPED_RELIC_SLOTS} equipped relic slots")
    chance = Fraction(copy_chance)
    if not 0 <= chance <= 1:
        raise ValueError("copy_chance must be between 0 and 1")

    pool = pick_pool(quest_set)
    copies: Dict[int, Fraction] = {}
    for slot in equipped:
        if slot is None:
            continue
        relic_id, level = slot
        if level < MAXED_RELIC_LEVEL:
            copies[relic_id] = copies.get(relic_id, Fraction(0)) + chance / EQUIPPED_RELIC_SLOTS

    uniform = Fraction(1, len(pool))
    no_copy = 1 - sum(copies.values(), Fraction(0))
    distribution = {relic_id: no_copy * uniform for relic_id in pool}
    for relic_id, share in copies.items():
        distribution[relic_id] = distribution.get(relic_id, Fraction(0)) + share
    return {relic_id: p for relic_id, p in distribution.items() if p}
