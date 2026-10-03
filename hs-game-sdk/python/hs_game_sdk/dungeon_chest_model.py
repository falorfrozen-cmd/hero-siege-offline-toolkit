"""When a key dungeon's end chest opens (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, our code or not established, in
`docs/models/dungeon-chest-spec.md`. `tests/test_dungeon_chest_model.py` holds
the checks, against `hs-game-sdk/curated/dungeon_chest_measurements.json`.

- The game's rule, as players see it (ForgePact#31): `Dungeon_Chest_obj` stays
  shut until no monster in the dungeon is alive. How the chest learns that (a
  builtin poll hidden from the static reading, or a variable another event
  writes) is not established, and is asked in `HYPOTHESES`.
- The quantities ForgePact's early-open mod is built on: the monsters it can
  see (kills since the chest was first seen plus monsters alive now) and the
  share of them that is dead.

This module models the game only. ForgePact's percentage (ForgePact#31's
`dungeonchest <pct>`), its threshold and its countdown are that mod's own
code and live in the test as input transforms.

Every value is an int or an exact `Fraction`. Nothing here draws a random
number.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import dungeon_chest_model`.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Dict, Optional

#: The alive count at which the game opens the chest itself.
VANILLA_UNLOCK_ALIVE = 0

#: Open questions ForgePact#31's Live procedure 1 answers. Each stays `None`
#: (not established) until a `measured` entry of the curated file decides it.
HYPOTHESES: Dict[str, Optional[bool]] = {
    # Every monster of the dungeon exists when the chest is first seen
    # (`alive-count`), so kills + alive is the whole population.
    "all_monsters_alive_at_entry": None,
    # No `Enemy_Creator_obj` inside a dungeon adds monsters after entry
    # (`creators-in-dungeon`).
    "no_creators_in_dungeon": None,
    # A chest or boss-blocker variable flips at the last kill (`unlock-signal`).
    "unlock_is_a_variable": None,
    # The chest's Step polls a builtin about monsters (`builtin-poll`).
    "unlock_is_a_builtin_poll": None,
    # The enemy-`self` kill hook's tally equals the fall in the alive count
    # (`kill-hook-fires`).
    "kill_tally_matches_alive_drop": None,
    # A boss dungeon follows the same rule (`boss-dungeon`).
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


def population(kills: int, alive: int) -> int:
    """The monsters the mod can see: kills since the chest was first seen,
    plus monsters alive now."""
    return _count("kills", kills) + _count("alive", alive)


def progress(kills: int, alive: int) -> Fraction:
    """The share of the seen population that is dead; 1 for an empty dungeon."""
    total = population(kills, alive)
    if total == 0:
        return Fraction(1)
    return Fraction(kills, total)
