"""What a monster's rank does to it (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, our code or not established, in
`docs/models/monster-rank-spec.md`. `tests/test_monster_rank_model.py` holds
the checks, against `hs-game-sdk/curated/monster_rank_measurements.json`.

- A monster's rank is its `enemyRarity`, 1 to 4 (ForgePact calls them normal,
  champion, rare and ancient). The game builds the monster for its rank in
  `EnemyRaritySettings`, and the kill pays out through `DropItem` with the
  rank as its first argument.
- Next to the same monster at rank 1, a higher rank multiplies its health,
  damage and XP, and sets its protected drop values, by the measured rows in
  `RANK_TABLE` (AFK FARM, 2026-09-17 to 09-24, ordinary monsters only).
- Whether a boss built at rank 3 or 4 follows the same rows is not
  established: `HYPOTHESES["boss_follows_rank_table"]` stays `None` until a
  measured row about a boss says.

This module models the game only. ForgePact's Bosses control (ForgePact#44),
which writes rank 3 or 4 onto a rank-1 boss, is that mod's own code and lives
in the test as an input transform.

Every value is an exact `Fraction` or an int. The health and damage multipliers
are medians, so `scaled` gives the typical monster, not every one. Nothing here
draws a random number.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import monster_rank_model`.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, NamedTuple, Optional, Tuple, Union

Number = Union[Fraction, int]

#: The game's ranks (`enemyRarity`). Loot goblins drop at 5, but their own rank
#: stays 1-4, so 5 is a drop rank, not a monster rank, and is not modelled.
RANKS = (1, 2, 3, 4)


@dataclass(frozen=True)
class RankRow:
    """One rank's row: multipliers next to rank 1, and the protected drop values."""

    #: Health, next to the same monster at rank 1 (measured median).
    hp: Fraction
    #: Damage, next to rank 1 (measured median).
    damage: Fraction
    #: XP, next to rank 1 (measured; exact constants).
    xp: Fraction
    #: `dCommonChance` (measured, identical within a rank).
    common_chance: int
    #: `dCommonDropMult` (measured).
    common_drop_mult: int
    #: `dSatanicDropMult` (measured); the only value that falls with rank.
    satanic_drop_mult: Fraction
    #: `dSlots`, the lowest and highest value seen (measured).
    slots: Tuple[int, int]


#: MK1 and MK2 of the curated file (`docs/RUNTIME_DATA_MODELS.md` § 13.7).
RANK_TABLE = {
    1: RankRow(Fraction(1), Fraction(1), Fraction(1), 4, 11, Fraction(1), (1, 1)),
    2: RankRow(Fraction("1.84"), Fraction("1.27"), Fraction("2.75"), 20, 20, Fraction("0.925"), (1, 3)),
    3: RankRow(Fraction("2.98"), Fraction("1.53"), Fraction("4.25"), 36, 42, Fraction("0.475"), (2, 5)),
    4: RankRow(Fraction("4.23"), Fraction("1.90"), Fraction("6.25"), 50, 58, Fraction("0.285"), (4, 8)),
}

#: What is not yet known, kept beside the numbers so a caller cannot miss it.
#: `boss_follows_rank_table`: whether a boss built at rank 3 or 4 takes the
#: rows above. `None` is "not established"; a bool once a measured row about
#: a boss is in the curated file (ForgePact#44's Live procedure 1).
HYPOTHESES: Dict[str, Optional[bool]] = {
    "boss_follows_rank_table": None,
}


class Scaled(NamedTuple):
    hp: Fraction
    damage: Fraction
    xp: Fraction


def row(rank: int) -> RankRow:
    """The rank's row; anything but a whole rank 1-4 is refused."""
    if isinstance(rank, bool) or not isinstance(rank, int) or rank not in RANK_TABLE:
        raise ValueError(f"not a monster rank (1-4): {rank!r}")
    return RANK_TABLE[rank]


def scaled(rank: int, base_hp: Number, base_damage: Number, base_xp: Number) -> Scaled:
    """A rank-1 monster's health, damage and XP, taken to `rank`.

    Rank 1 returns the bases unchanged. For a boss the result is a prediction
    only while `HYPOTHESES["boss_follows_rank_table"]` is true.
    """
    rank_row = row(rank)
    bases = (Fraction(base_hp), Fraction(base_damage), Fraction(base_xp))
    if any(base < 0 for base in bases):
        raise ValueError("a base value cannot be negative")
    hp, damage, xp = bases
    return Scaled(hp * rank_row.hp, damage * rank_row.damage, xp * rank_row.xp)
