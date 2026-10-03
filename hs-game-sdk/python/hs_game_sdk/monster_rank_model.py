"""What a monster's rank does to it (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, our code or not established, in
`docs/models/monster-rank-spec.md`. `tests/test_monster_rank_model.py` holds
the checks, against `hs-game-sdk/curated/monster_rank_measurements.json`.

- A monster's rank is its `enemyRarity`, 1 to 4: Common, Champion, Ancient and
  Legion, inferred from the save's kill counters and backed by a player's
  on-screen report since ForgePact#159. ForgePact's Monster Rarity rows use
  those names since #159; its code, commands and Bosses select still call
  rank 3 rare and rank 4 ancient. The game builds the monster for its rank in
  `EnemyRaritySettings`, and an ordinary monster's kill pays out through
  `DropItem` with the rank as its first argument. In ForgePact#44's Live
  procedure 1b (2026-10-02) a boss's did too, measured: 1 at an unraised Karp
  King's death, 4 at one raised to rank 4 with a ForgePact affix top-up the
  session's control did not share, so whether a boss's drop rank is the rank
  written is not established
  (`HYPOTHESES["boss_drop_rank_reaches_dropitem"]`).
- Next to the same monster at rank 1, a higher rank multiplies its health,
  damage and XP, and sets its protected drop values, by the measured rows in
  `RANK_TABLE` (AFK FARM, 2026-09-17 to 09-24, ordinary monsters only).
- Whether a boss built at rank 3 or 4 follows the same rows is asked once per
  dimension in `HYPOTHESES`, so a session that measured one dimension cannot
  answer the others. On one Karp King raised to rank 4, Live procedure 1b
  measured XP at x6.2505 against the row's x6.25 and damage at x2.0968
  against x1.90; whether a boss's XP or damage follows the row is not
  established (one spawn, its affixes unmatched by the control). Health
  stays open: two sessions read x5.65 and x4.73 on the same boss, each with
  a different ForgePact affix top-up built into it and no health control.

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
from typing import Dict, FrozenSet, NamedTuple, Optional, Tuple, Union

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

#: Whether a boss built at rank 3 or 4 takes the rows above, one entry per
#: dimension, kept beside the numbers so a caller cannot miss what is open.
#: `None` is "not established"; a bool only once that dimension's own live
#: check was measured on a boss with nothing else changed, or with what else
#: changed matched by an identity control on an ordinary monster in the same
#: session, raised with the same affix top-up at the same rank (compared, not
#: assumed) (a measured row in the curated file naming the dimension and a boss
#: object, with its ratio to the boss's rank-1 self). A row within the
#: control's tolerance of the table's ratio (damage 10%, XP 2%, health 5%)
#: follows it; one outside does not.
HYPOTHESES: Dict[str, Optional[bool]] = {
    # None: Live 1 (2026-10-02, `ancient-hp` pass) read Karp_King_obj at rank 4
    # with x5.65 its rank-1 health (44,625,000 -> 252,242,812) against MK1's
    # x4.23 (MK6, MK7), and Live 1b x4.73 (44,625,000 -> 210,992,578; MK19,
    # MK20). Not established: each boss got a different ForgePact 3-affix
    # top-up (16, 17, 25; then 12, 20, 31), built into the same health, and no
    # session had a health control (Live 1b's ordinary monster read x5.69 at
    # rank 3 and x5.31 at rank 4, MK17). So these are the feature's effect,
    # not the game's rank scaling for a boss alone.
    "boss_hp_follows_rank_table": None,
    # None: Live 1b (`ancient-damage` pass) read the record the protected-store
    # key held in `damage` names (not the variable's value, which is the key),
    # a read proven by the identity control (MK15, x1.40 / x2.00 on an
    # ordinary monster), at
    # x2.0968 its rank-1 value (217 -> 455; MK21), 10.4% above MK1's x1.90,
    # 0.4% outside the control's 10%. Not established: the control itself
    # read 8.4% below the table at rank 3 and 5.5% above it at rank 4, the
    # boss's ForgePact affix top-up (12, 20, 31) differed from the control's
    # rank-4 one (5, 12, 18), and it is one spawn. So whether a boss's damage
    # follows the row stays open.
    "boss_damage_follows_rank_table": None,
    # None: Live 1b (`ancient-xp` pass) read the record the protected-store
    # key held in `killExperience` names (not the variable's value, which is
    # the key), a read proven by the identity control (MK16), at x6.2505 its
    # rank-1 value (4,950 -> 30,940; MK22) against MK1's exact x6.25. Measured
    # on one boss, but not established: that Karp King spawn's ForgePact
    # affix top-up (12, 20, 31) was not the control's rank-4 one (5, 12, 18),
    # so the control does not stand in for it. Rank 4 only, one spawn; the
    # rank-3 row (x4.25) was not measured on a boss.
    "boss_xp_follows_rank_table": None,
    # None: Live 1b (`ancient-drop-rank` pass): `DropItem`'s first argument
    # was 1 at the unraised Karp King's death and 4 at the raised one's, with
    # the instrument's control on an ordinary monster passing (MK18, MK23).
    # Measured on one boss, but not established: the same spawn as MK22, with
    # the same unmatched affix top-up.
    "boss_drop_rank_reaches_dropitem": None,
}

#: The object every boss descends from; `boss_family()` lists them.
BOSS_PARENT = "Enemy_Child_Boss_obj"


def boss_family() -> FrozenSet[str]:
    """The object names that descend from `BOSS_PARENT`, from `hs-game-sdk`'s
    parent table: the objects a boss row in the curated file may name."""
    from . import objects  # imported here so the model stays light to import

    root = objects.GameObject[BOSS_PARENT]
    return frozenset(objects.GameObject(index).name
                     for index in objects.get_descendant_indices(root))


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

    Rank 1 returns the bases unchanged. For a boss each result is a prediction
    only while its own `HYPOTHESES["boss_<hp|damage|xp>_follows_rank_table"]`
    is true, and none is yet: XP (one read at x6.2505 against the row's
    x6.25) and damage (one read at x2.0968 against x1.90), each with affixes
    the control did not share, and health are open (`None`).
    """
    rank_row = row(rank)
    bases = (Fraction(base_hp), Fraction(base_damage), Fraction(base_xp))
    if any(base < 0 for base in bases):
        raise ValueError("a base value cannot be negative")
    hp, damage, xp = bases
    return Scaled(hp * rank_row.hp, damage * rank_row.damage, xp * rank_row.xp)
