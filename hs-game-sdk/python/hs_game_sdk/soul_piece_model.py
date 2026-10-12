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
- The stack rule (static reading): the pickup's stack attempts refuse an
  incoming item outside classes 12 to 15 before comparing anything, then merge
  it into one whose class matches and whose definition's `b` and `c` are the
  same value to the runtime (two reals within the math epsilon), while the two
  counts summed stay at most 999. The seed `a` is never compared. Live
  procedure 1 measured a class-12 item merging into a real key of the same
  definition, and Live procedure 3 five class-11 items staying apart.
- The numbers a definition carries (static reading): `b` and `c` may be reals.
  The repository lookup truncates `b` toward zero, a `c` above 0.5 picks the
  unique repository, the save writes a real with two decimals
  (`HYPOTHESES['string_keeps_two_decimals']`), crafting counts an item by class
  and `b` (not `c`), and the inventory find matches `b` and `c`.
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
its transfer, its verdicts and the key piece's `b` of the key base's index plus
act/10) are that mod's own code and live in the test as input transforms,
pinned to `SoulPieceMod.hpp`.

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

#: The item classes the stack attempt accepts (static reading).
STACKABLE_CLASSES = frozenset({12, 13, 14, 15})

#: The most one stack holds: a merge goes ahead only while the summed count
#: stays at most this (static reading of `InventoryGridAddToStack`).
BAG_STACK_CAP = 999

#: How far apart two reals may be and still compare equal: GameMaker's default
#: math epsilon. Whether the game sets another is not established.
EPSILON = Fraction(1, 100000)

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
    # The save's `string()` keeps a real's two decimals and writes a whole number
    # whole (the runtime's documented behaviour, not read in this game; the
    # follow-up's Live procedure 1 `reload-frac-kept` measures it).
    "string_keeps_two_decimals": None,
    # A consumable's count `o` comes back from a save and reload as it was
    # (`saved_number` keeps a whole number; the follow-up's Live procedure 2
    # `reload-stack-kept` measures it on a piece stack).
    "saved_count_is_kept": None,
}

Number = Union[int, Fraction]


class Item(NamedTuple):
    """The fields the stack rule reads: class (`itemType`), the definition's
    `b` and `c` (whole or real), the seed `a`, which it never compares, and
    the count `o`, which the cap reads."""

    item_type: int
    b: Number
    c: Number
    a: int = 0
    o: int = 1


def _whole(name: str, value: int) -> int:
    """A whole number. `bool` is refused."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    return value


def _number(name: str, value: Number) -> Number:
    """A whole number or an exact fraction (a real). `bool` and `float` are refused."""
    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise TypeError(f"{name} must be an int or Fraction, got {type(value).__name__}")
    return value


def same_value(x: Number, y: Number) -> bool:
    """The runtime's general value compare on two numbers: equal when they
    differ by no more than `EPSILON`, so 2.1 and 2 differ and 2.1 and 2.1 match."""
    return abs(_number("x", x) - _number("y", y)) <= EPSILON


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
    """Whether the game merges `picked` into `held` on pickup. A `picked` class
    outside 12 to 15 is refused before anything else is read; then the same
    class, `b` and `c` the same value to the runtime (`same_value`), and the
    two counts summed at most `BAG_STACK_CAP`. The seed is not compared. The
    item-info flag `IsStackable` also asks is left out (it can only refuse)."""
    if _whole("item_type", picked.item_type) not in STACKABLE_CLASSES:
        return False
    for item in (held, picked):
        _whole("item_type", item.item_type)
        _number("b", item.b)
        _number("c", item.c)
        _whole("o", item.o)
    if held.item_type != picked.item_type:
        return False
    if not (same_value(held.b, picked.b) and same_value(held.c, picked.c)):
        return False
    return held.o + picked.o <= BAG_STACK_CAP


def repository_index(b: Number) -> int:
    """The repository entry a definition's `b` loads: the runtime's real-to-int
    conversion truncates toward zero, so 2.1 and 2.9 load entry 2."""
    return int(_number("b", b))


def uses_unique_repository(c: Number) -> bool:
    """Whether the item constructor takes the unique repository: when `c` is
    truthy, which for a real means above 0.5."""
    return _number("c", c) > Fraction(1, 2)


def saved_number(value: Number) -> Number:
    """What a definition's number reads after a save and reload, under
    `HYPOTHESES['string_keeps_two_decimals']`: a whole number whole (so a
    count `o` comes back as it was, `saved_count_is_kept`), a real rounded to
    two decimals (a tie rounds away from zero here; the game's is not known)."""
    hundredths = abs(_number("value", value)) * 100
    rounded = Fraction(int(hundredths + Fraction(1, 2)), 100) * (-1 if value < 0 else 1)
    return int(rounded) if rounded.denominator == 1 else rounded


def counted_by_crafting(item: Item, item_type: int, b: Number) -> bool:
    """Whether `CountInventoryItem` counts `item` for a recipe asking `item_type`
    and `b`: it compares the class and `b`, never `c`. The item-info value it
    also compares is left out, which can only make the model count more."""
    return _whole("item_type", item.item_type) == _whole("item_type", item_type) and same_value(item.b, b)


def find_matches(item: Item, b: Number, c: Number) -> bool:
    """Whether `FindInventoryItem` takes `item` for a definition `b`, `c`."""
    return same_value(item.b, b) and same_value(item.c, c)


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
