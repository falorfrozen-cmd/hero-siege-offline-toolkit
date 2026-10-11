"""The act of a room and the gem roll a boss soul piece rides (hand-written,
stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, our code or not established, in
`docs/models/soul-piece-spec.md`. `tests/test_soul_piece_model.py` holds the
checks, against `hs-game-sdk/curated/boss_soul_pieces.json` and
`hs-game-sdk/curated/room_acts.json`.

- The act of a room (static reading): `RoomActIndex(room)` answers the act
  minus one, 0 to 8, for the 175 rooms of its switch, and undefined for every
  other room.
- The gem roll (static reading): `DropGems` runs once per dying source whose
  `LoadDrops` drop type 6 gate passed, and rolls the socketables of repository
  category 15 against their `GetDropRate` answer. Whether that gives the Gem
  of Incarnation exactly 1 in its rate is not established
  (`HYPOTHESES['gem_one_in_its_rate']`); the model assumes it, and says so.

This module models the game only. ForgePact's boss soul pieces (ForgePact#197:
the piece's denominator, five quarters of the gem's chance, its room rules and
its verdicts) are that mod's own code and live in the test as input
transforms, pinned to `SoulPieceMod.hpp`.

Every value is an int or an exact `Fraction`. Nothing here draws a random
number.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import soul_piece_model`.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Dict, Optional, Union

#: How many acts `RoomActIndex` answers for (its cases 0..8).
ACT_COUNT = 9

#: ForgePact#197's open questions about the game. Each stays `None` (not
#: established) until a live check of the curated file's `open_questions`
#: answers it.
HYPOTHESES: Dict[str, Optional[bool]] = {
    # `DropGems` gives each socketable exactly 1 in its `GetDropRate` answer,
    # rather than picking one by weight (not read; a gem is too rare to measure
    # in one session).
    "gem_one_in_its_rate": None,
    # The Gem of Incarnation's `droprate.base` is 10,000 (`gem-rate`, Live 1).
    "gem_rate_is_10000": None,
    # `DropGems`' self is the dying source (`gems-self`, Live 1).
    "gem_roll_self_is_the_source": None,
}

Number = Union[int, Fraction]


def _whole(name: str, value: int) -> int:
    """A whole number. `bool` is refused."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    return value


def act_of_room(room_act_index: Optional[int]) -> Optional[int]:
    """The act (1..9) from `RoomActIndex`'s answer, `None` (undefined) for a
    room outside its switch. An answer outside 0..8 is refused."""
    if room_act_index is None:
        return None
    answer = _whole("room_act_index", room_act_index)
    if not 0 <= answer < ACT_COUNT:
        raise ValueError(f"RoomActIndex answers 0..{ACT_COUNT - 1} or undefined, got {answer}")
    return answer + 1


def gem_chance(gem_rate: Optional[Number]) -> Optional[Fraction]:
    """The gem's chance on one `DropGems` call: 1 in its rate, under
    `HYPOTHESES['gem_one_in_its_rate']`. `None` when the rate is unknown, zero
    or negative (the game has no answer the model can give then)."""
    if gem_rate is None:
        return None
    if isinstance(gem_rate, bool) or not isinstance(gem_rate, (int, Fraction)):
        raise TypeError(f"gem_rate must be an int or Fraction, got {type(gem_rate).__name__}")
    if gem_rate <= 0:
        return None
    return 1 / Fraction(gem_rate)


def expected_drops(rolls: int, chance: Optional[Fraction]) -> Fraction:
    """The expected number of drops over `rolls` independent rolls of one
    chance: linear in the rolls. An unknown chance gives none."""
    if _whole("rolls", rolls) < 0:
        raise ValueError(f"rolls must be >= 0, got {rolls}")
    if chance is None:
        return Fraction(0)
    if not 0 <= chance <= 1:
        raise ValueError(f"chance must be in [0, 1], got {chance}")
    return rolls * Fraction(chance)
