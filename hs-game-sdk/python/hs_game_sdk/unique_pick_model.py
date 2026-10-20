"""Which unique a unique roll yields (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, our code or not established, in
`docs/models/unique-pick-spec.md`. `tests/test_unique_pick_model.py` holds the
checks, against `hs-game-sdk/curated/unique_pick_measurements.json`. It
complements `drop_roll_model`, which answers *whether* a roll runs; this module
answers *which* unique comes out once one does.

Three rolls draw from `Controller_obj.lootListUnique`, an array of six lists of
`(type, sub-type, base)` triples (static reading, with the layout measured):
- The Angelic roll (`DropItemAngelicChance`) reads list 5 and draws again until
  it keeps a droppable entry: rarity 7 or 10, and not flagged hidden. So an
  entry listed r times among T droppable entries comes out r / T of the time.
- The ordinary unique roll (`DropUniqueItems`) reads one of lists 0..4 and
  makes one draw. It keeps an entry whose rarity is below 7 and that is not
  flagged hidden; anything else drops nothing, with no second draw. So one call
  drops an entry listed r times in a list of L entries with chance r / L, and
  drops anything with chance D / L, D the entries it keeps. A kill reaches it
  through drop type 45; with p entries added to the list for one call, an
  item with c of them comes out c / (L + p) of the time (`kill_share`).
- The Heroic roll (`DropItemHeroic`) reads the list its index argument names,
  5 when that is undefined, and draws again until it keeps an entry: not
  flagged hidden, and of any rarity but 7 and 10. So an entry listed r times
  among the T_H entries it keeps comes out r / T_H of the time.

This module models the game only. ForgePact's levers for ForgePact#74,
ForgePact#158 and ForgePact#166 (the stand-in entries pushed for the length
of a roll, and the coin that hands a stand-in hit to the mod's item) are that
mod's own code and live in the test as input transforms.

Every probability is an exact `Fraction`. Nothing here draws a random number or
tries to reproduce the game's own random sequence. What is not established is
a parameter: T, T_H and D are inputs, and `index_can_reach_length` carries
the open question of whether the ordinary roll's random index can equal the
list's length. The binomial helpers a count is compared with are `drop_roll_model`'s,
imported here and not copied.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import unique_pick_model`.
"""

from __future__ import annotations

from fractions import Fraction
from typing import FrozenSet, Tuple

from .drop_roll_model import binomial_band, observation_within  # noqa: F401  (re-exported)

#: The element of `lootListUnique` the Angelic roll reads (static reading).
ANGELIC_LIST_INDEX = 5
#: The elements the ordinary unique roll chooses between (static reading).
UNIQUE_SUB_LISTS: Tuple[int, ...] = (0, 1, 2, 3, 4)
#: The definition rarities the Angelic roll keeps: 7 Angelic, 10 Unholy
#: (static reading).
ANGELIC_RARITIES: FrozenSet[int] = frozenset({7, 10})
#: The ordinary unique roll keeps an entry whose rarity is below this
#: (static reading).
ORDINARY_RARITY_BELOW = 7
#: The element of `lootListUnique` the Heroic roll reads when its index
#: argument is undefined (static reading).
HEROIC_DEFAULT_LIST_INDEX = 5
#: The definition rarities the Heroic roll refuses and draws again on: 7
#: Angelic, 10 Unholy (static reading).
HEROIC_REFUSED_RARITIES: FrozenSet[int] = frozenset({7, 10})


def angelic_keeps(rarity: int, hidden: bool) -> bool:
    """Whether the Angelic roll keeps an entry once picked: its rarity is 7 or
    10 and its base is not flagged hidden."""
    return not hidden and rarity in ANGELIC_RARITIES


def ordinary_keeps(rarity: int, hidden: bool) -> bool:
    """Whether the ordinary unique roll keeps the entry its one draw read: its
    rarity is below 7 and it is not flagged hidden."""
    return not hidden and rarity < ORDINARY_RARITY_BELOW


def heroic_keeps(rarity: int, hidden: bool) -> bool:
    """Whether the Heroic roll keeps an entry once picked: its rarity is
    neither 7 nor 10 and its base is not flagged hidden."""
    return not hidden and rarity not in HEROIC_REFUSED_RARITIES


def _check_count(name: str, value: int, low: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be a whole number")
    if value < low:
        raise ValueError(f"{name} must be {low} or more")


def angelic_share(copies: int, droppable: int) -> Fraction:
    """An entry's share of the Angelic roll's drops: r / T.

    `copies` (r) is how many times the entry is listed, counted only when the
    roll keeps it; `droppable` (T) is the droppable entries on the list,
    counted with repeats, those r included. The roll draws again until it keeps
    one, so a roll with no droppable entry never ends: that refuses.
    """
    _check_count("copies", copies)
    _check_count("droppable", droppable, 1)
    if copies > droppable:
        raise ValueError("an entry cannot be listed more often than the droppable entries it is counted in")
    return Fraction(copies, droppable)


def heroic_share(copies: int, droppable: int) -> Fraction:
    """An entry's share of the Heroic roll's drops: r / T_H.

    `copies` (r) is how many times the entry is listed, counted only when the
    roll keeps it; `droppable` (T_H) is the entries the roll keeps on the list
    it reads, counted with repeats, those r included. Like the Angelic roll it
    draws again until it keeps one, so a list with nothing it keeps refuses.
    """
    _check_count("copies", copies)
    _check_count("droppable", droppable, 1)
    if copies > droppable:
        raise ValueError("an entry cannot be listed more often than the kept entries it is counted in")
    return Fraction(copies, droppable)


def _ordinary_draws(length: int, index_can_reach_length: bool) -> int:
    _check_count("length", length, 1)
    return length + 1 if index_can_reach_length else length


def ordinary_pick_chance(copies: int, length: int, *, index_can_reach_length: bool = False) -> Fraction:
    """The chance that one ordinary unique-roll call, on a list already chosen,
    drops a given droppable entry: r / L.

    `copies` (r) is how many times the entry is listed on that list, and
    `length` (L) the list's length. With `index_can_reach_length` the draw may
    also read one index past the end, which drops nothing, so the chance is
    r / (L + 1). Which list a call reads is not modelled here.
    """
    _check_count("copies", copies)
    draws = _ordinary_draws(length, index_can_reach_length)
    if copies > length:
        raise ValueError("an entry cannot be listed more often than the list is long")
    return Fraction(copies, draws)


def ordinary_drop_chance(droppable: int, length: int, *, index_can_reach_length: bool = False) -> Fraction:
    """The chance that one ordinary unique-roll call, on a list already chosen,
    drops anything: D / L, D the entries of the list the roll keeps.

    With `index_can_reach_length`, D / (L + 1), as for `ordinary_pick_chance`.
    """
    _check_count("droppable", droppable)
    draws = _ordinary_draws(length, index_can_reach_length)
    if droppable > length:
        raise ValueError("a list cannot keep more entries than it holds")
    return Fraction(droppable, draws)


def kill_share(copies: int, length: int, pushed: int, *, index_can_reach_length: bool = False) -> Fraction:
    """An item's share of one ordinary unique-roll call on a list already
    chosen, while extra entries sit on that list: c / (L + p).

    `copies` (c) is how many of the entries on the list are the item's,
    `length` (L) the list's own length, and `pushed` (p) every entry added to
    it for that call, those c included. The roll's one draw reads the
    lengthened list, so the item comes out with c / (L + p), each entry the
    game listed once with 1 / (L + p), and a draw of an entry the roll refuses
    still drops nothing. With `index_can_reach_length`, c / (L + p + 1), as
    for `ordinary_pick_chance`. Which list a call reads, and how often a kill
    runs the roll, are not modelled here.
    """
    _check_count("copies", copies)
    _check_count("length", length)
    _check_count("pushed", pushed)
    if copies > pushed:
        raise ValueError("an item cannot have more entries on the list than were pushed onto it")
    draws = _ordinary_draws(length + pushed, index_can_reach_length)
    return Fraction(copies, draws)
