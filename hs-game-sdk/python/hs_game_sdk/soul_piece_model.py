"""The act of a room, the bag's stack rule, the gem roll a boss soul piece
rides and the backpack's use (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, our code or not established, in
`docs/models/soul-piece-spec.md`. `tests/test_soul_piece_model.py` holds the
checks, against `hs-game-sdk/curated/boss_soul_pieces.json` and
`hs-game-sdk/curated/room_acts.json`.

- The act of a room (measured): `RoomActIndex(room)` answers the act itself,
  1 to 9, for the 175 rooms of its switch (Live procedure 1 read 1 in
  `Town_01_rm` and `Act_01_01`, 2 in `Act_02_01`; Live procedures 3 and 2
  read 2 in `Town_02_rm`, `Act_02_Boss` and `Act_02_02`), and `false` for a
  room outside it (Live procedure 3 read `bool:false` in `Act_01_Boss` and
  `Act_01_Pregame`; the static reading had said undefined).
- The stack rule (static reading): the pickup's stack attempts merge an item
  into one whose class, `b` and `c` match, and the bag's attempt takes only
  classes 12 to 15. The seed `a` is never compared. Live procedure 1 measured a
  class-12 item merging into a real key of the same definition, and Live
  procedure 3 five class-11 items (pieces and a plain logo) staying apart.
- The gem roll (static reading): `DropGems` runs once per dying source whose
  `LoadDrops` drop type 6 gate passed, and rolls the socketables of repository
  category 15 against their `GetDropRate` answer. Whether that gives the Gem
  of Incarnation exactly 1 in its rate is not established
  (`HYPOTHESES['gem_one_in_its_rate']`); the model assumes it, and says so.
- The use (measured for the Edible PAS Logo): a confirmed right-click asks
  `PotionUse` with the item, and the game clears the item's cells only when
  that answers true.

This module models the game only. ForgePact's boss soul pieces (ForgePact#197:
the piece's denominator, five quarters of the gem's chance, its room rules,
its transfer and its verdicts) are that mod's own code and live in the test as
input transforms, pinned to `SoulPieceMod.hpp`.

Every value is an int, a bool or an exact `Fraction`. Nothing here draws a
random number.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import soul_piece_model`.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Dict, NamedTuple, Optional, Union

#: How many acts `RoomActIndex` answers for (1..9).
ACT_COUNT = 9

#: The item classes the bag's stack attempt accepts (static reading).
STACKABLE_CLASSES = frozenset({12, 13, 14, 15})

#: ForgePact#197's open questions about the game. Each stays `None` (not
#: established) until a live check of the curated file's `open_questions`
#: answers it; a measured answer is written here with its check.
HYPOTHESES: Dict[str, Optional[bool]] = {
    # `DropGems` gives each socketable exactly 1 in its `GetDropRate` answer,
    # rather than picking one by weight (not read; a gem is too rare to measure
    # in one session).
    "gem_one_in_its_rate": None,
    # `DropGems`' self is the dying monster (Live procedure 1: 29 rolls, self a
    # descendant of `Enemy_Parent_obj` every time).
    "gem_roll_self_is_the_source": True,
    # A room outside the switch answers undefined: no, it answers `false`
    # (Live procedure 3 read `bool:false` in `Act_01_Boss` and `Act_01_Pregame`).
    "room_outside_the_switch_is_undefined": False,
    # A class-11 item never stacks in the bag (Live procedure 3's `piece-apart`:
    # five class-11 items picked up, each in its own cell).
    "class_11_never_stacks": True,
    # `PotionUse` answering true makes the game clear the item's cells (Live
    # procedure 1's `use-control`, the Edible PAS Logo).
    "potion_use_true_clears_the_item": True,
}

Number = Union[int, Fraction]


class Item(NamedTuple):
    """The fields the stack rule reads: class (`itemType`), the definition's
    `b` and `c`, and the seed `a`, which it never compares."""

    item_type: int
    b: int
    c: int
    a: int = 0


def _whole(name: str, value: int) -> int:
    """A whole number. `bool` is refused."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    return value


def act_of_room(room_act_index: Union[int, bool, None]) -> Optional[int]:
    """The act (1..9): `RoomActIndex`'s answer itself, `None` (no act) for a
    room outside its switch, which answers `false` (measured, Live procedure 3)
    or undefined (`None`, the static reading). `True` and an answer outside
    1..9 are refused."""
    if room_act_index is None or room_act_index is False:
        return None
    answer = _whole("room_act_index", room_act_index)
    if not 1 <= answer <= ACT_COUNT:
        raise ValueError(f"RoomActIndex answers 1..{ACT_COUNT} or undefined, got {answer}")
    return answer


def stacks(held: Item, picked: Item) -> bool:
    """Whether the game merges `picked` into `held` on pickup: both of a class
    the bag stacks (12 to 15), the same class, and the same `b` and `c`."""
    fields = (held.item_type, held.b, held.c, picked.item_type, picked.b, picked.c)
    for value in fields:
        _whole("item field", value)
    if held.item_type not in STACKABLE_CLASSES:
        return False
    return (held.item_type, held.b, held.c) == (picked.item_type, picked.b, picked.c)


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


def item_used_up(potion_use_answer: bool) -> bool:
    """Whether a confirmed backpack use leaves the item gone: only when
    `PotionUse` answered true does the game clear the item's cells."""
    if not isinstance(potion_use_answer, bool):
        raise TypeError(f"PotionUse's answer must be a bool, got {type(potion_use_answer).__name__}")
    return potion_use_answer
