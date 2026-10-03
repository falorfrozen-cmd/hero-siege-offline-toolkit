"""When a key dungeon's end chest opens (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, our code or not established, in
`docs/models/dungeon-chest-spec.md`. `tests/test_dungeon_chest_model.py` holds
the checks, against `hs-game-sdk/curated/dungeon_chest_measurements.json`.

- The game's rule (ForgePact#31, measured in its Live procedure 1):
  `Dungeon_Chest_obj` polls `instance_exists(Enemy_Parent_obj)` itself and
  stays shut while any monster of the dungeon is alive.
- The dungeon's planned total: every monster it will hold, spawned yet or not.
  Monsters stream in from creator-family spawners that all exist at entry, so
  the total is a sum over those creators taken at the chest's first sight.
  Which per-creator number that sum reads is not established (`HYPOTHESES`).

This module models the game only. ForgePact's percentage (ForgePact#31's
`dungeonchest <pct>`), its clamp, threshold and countdown are that mod's own
code and live in the test as input transforms.

Every value is an int or an exact `Fraction`. Nothing here draws a random
number.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import dungeon_chest_model`.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Dict, Iterable, Union

#: The alive count at which the game opens the chest itself.
VANILLA_UNLOCK_ALIVE = 0

#: ForgePact#31's open questions. Each stays `None` (not established) until a
#: `measured` entry of the curated file decides it; Live 1 decided four.
HYPOTHESES: Dict[str, Union[bool, str, None]] = {
    # Every monster exists when the chest is first seen (`alive-count`): no,
    # 5 then 44 alive at entry, 600 killed by the clear (DC7).
    "all_monsters_alive_at_entry": False,
    # No creator inside a dungeon (`creators-in-dungeon`): no, 122 (DC8).
    "no_creators_in_dungeon": False,
    # A chest or blocker variable flips at the last kill (`unlock-signal`): no
    # unlock flag, only `nearest` changed (DC9).
    "unlock_is_a_variable": False,
    # The chest polls a builtin about monsters (`builtin-poll`): yes,
    # instance_exists(Enemy_Parent_obj) (DC10).
    "unlock_is_a_builtin_poll": True,
    # Where the planned total comes from (`creator-sum`, `creator-state`):
    # 'variable' (a per-creator count read by name) or 'estimate' (pending
    # creators x a measured mean), set by ForgePact#31's Live 1b (DC14).
    "planned_total_source": None,
    # A boss dungeon follows the same rule (`boss-dungeon`, DC12).
    "boss_dungeon_same_rule": None,
}


def _count(name: str, value: int) -> int:
    """A monster count: a whole number, zero or more. `bool` is refused."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")
    return value


def chest_openable(alive: int) -> bool:
    """The game's rule: the chest opens only once no monster is alive."""
    return _count("alive", alive) == VANILLA_UNLOCK_ALIVE


def kills_to_vanilla(alive: int) -> int:
    """Kills left before the game opens the chest itself: every living monster."""
    return _count("alive", alive) - VANILLA_UNLOCK_ALIVE


def planned_total(alive_at_first_sight: int, planned_per_creator: Iterable[int]) -> int:
    """Monsters alive at the chest's first sight plus each creator's planned
    count. Pass 0 alive for the plain sum over every creator."""
    total = _count("alive_at_first_sight", alive_at_first_sight)
    for planned in planned_per_creator:
        total += _count("planned_per_creator", planned)
    return total


def estimated_total(alive_at_first_sight: int, pending_creators: int,
                    mean_per_creator: Union[int, Fraction]) -> int:
    """The `estimate` form: alive at first sight plus pending creators times a
    measured mean, rounded up to a whole monster."""
    if isinstance(mean_per_creator, bool) or not isinstance(mean_per_creator, (int, Fraction)):
        raise TypeError(f"mean_per_creator must be an int or Fraction, got {type(mean_per_creator).__name__}")
    if mean_per_creator < 0:
        raise ValueError(f"mean_per_creator must be >= 0, got {mean_per_creator}")
    pending = _count("pending_creators", pending_creators) * Fraction(mean_per_creator)
    return _count("alive_at_first_sight", alive_at_first_sight) - (-pending.numerator // pending.denominator)


def progress(kills: int, total: int) -> Fraction:
    """The share of the planned total that is dead. A total of 0 means the
    total is unknown, and is refused."""
    if _count("total", total) == 0:
        raise ValueError("total must be > 0 (0 means the planned total is unknown)")
    return Fraction(_count("kills", kills), total)
