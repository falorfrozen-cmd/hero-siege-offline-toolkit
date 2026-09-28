"""Player instance structures, equipment slot definitions, and container scanning helpers."""

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Set, Any
from .item_type import ItemType
from .structs import ItemDefinitionStruct


class EquipmentSlot(IntEnum):
    HELM = 0
    CHESTPLATE = 1
    BOOTS = 2
    GLOVES = 3
    BELT = 4
    AMULET = 5
    RING_1 = 6
    RING_2 = 7
    MAIN_HAND = 8
    OFF_HAND = 9
    RELIC_0 = 10
    RELIC_1 = 11
    RELIC_2 = 12
    RELIC_3 = 13
    RELIC_4 = 14
    CHARM_0 = 15
    CHARM_1 = 16
    CHARM_2 = 17
    CHARM_3 = 18


@dataclass
class PlayerEquipment:
    helm: Optional[ItemDefinitionStruct] = None
    chestplate: Optional[ItemDefinitionStruct] = None
    boots: Optional[ItemDefinitionStruct] = None
    gloves: Optional[ItemDefinitionStruct] = None
    belt: Optional[ItemDefinitionStruct] = None
    amulet: Optional[ItemDefinitionStruct] = None
    ring1: Optional[ItemDefinitionStruct] = None
    ring2: Optional[ItemDefinitionStruct] = None
    main_hand: Optional[ItemDefinitionStruct] = None
    off_hand: Optional[ItemDefinitionStruct] = None
    relics: List[ItemDefinitionStruct] = field(default_factory=list)
    charms: List[ItemDefinitionStruct] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The relic-identification contract.
#
# These mirror the constants in hs_game_sdk/cpp/include/hs_game_sdk/player.hpp
# field for field, because both scanners must accept exactly the same item
# layouts and container kinds. REPORTED 2026-09-12 by origin's second review of
# PR #3: C++ recognised `cls` and read numeric arrays out of `relic_levels`
# while Python did neither, so the two disagreed about which relics a player
# owns. tests/test_cpp_sdk.py asserts these tuples still match what the C++
# header declares, so a future edit to one side fails a test instead of
# silently diverging.
# ---------------------------------------------------------------------------

#: Rarity tier that identifies an item as a relic (docs/RUNTIME_DATA_MODELS.md).
RELIC_RARITY_TIER = 16
#: Season 10 relic ids run 0..155; exclusive upper bound for a plausible id.
RELIC_ID_LIMIT = 160
#: A relic at this level or above is maxed.
MAXED_RELIC_LEVEL = 10
#: Recursion budget, shared with the C++ scanner.
MAX_SCAN_DEPTH = 5
#: Longest array read from a single container, to bound a pathological table.
MAX_SCANNED_ARRAY_LENGTH = 512

#: Fields holding the item/relic id.
RELIC_ID_FIELDS = ("b", "relicId")
#: Fields whose value being RELIC_RARITY_TIER identifies a relic.
RELIC_TIER_FIELDS = ("c", "cls", "itemType")
#: Fields holding a relic's upgrade level. The highest present value wins.
RELIC_LEVEL_FIELDS = ("o", "level", "relicLevel")
#: Relic-specific field whose mere presence identifies a relic.
RELIC_ONLY_FIELD = "relicLevel"
#: Item class (ItemType) of a relic. A relic's definition carries no class and
#: `c` 0 (read from a character save, 2026-09-27; #93), so on the game's own
#: items the class is on the item instance, or in the save key's last number.
RELIC_ITEM_CLASS = int(ItemType.RELIC)
#: Field of an item instance holding its class; a dict carrying it (with a
#: definition) is an item instance.
ITEM_INSTANCE_TYPE_FIELD = "itemType"
#: Field of an item instance holding its definition (`b` id, `o` level, ...).
ITEM_INSTANCE_DEFINITION_FIELD = "itemDefinitionStruct"
#: Containers holding item structs only; a bare number here means nothing.
#: `equipped_items` is the save file's name for the equipped items.
GENERAL_CONTAINER_FIELDS = ("equippedItems", "equipped_items", "inventory", "bags")
#: Containers where a numeric array really is `relic id -> level`.
RELIC_CONTAINER_FIELDS = (
    "inventory_relic_tab", "pRelics", "relic_array", "relic_inventory",
    "relic_levels", "relic_tab", "relicPage", "relics", "relics_collected",
)

# A save's item key, `<x>-<y>-<stamp>-<class>` (for example
# `0-0-209562107245-16`): its trailing number is the item's class. Python-only,
# because only Python reads saves; C++ resolves equipped items in memory.
_ITEM_KEY = re.compile(r"\d+-\d+-\d+-(\d+)")


def _as_int(value: Any) -> Optional[int]:
    """Numeric value as an int, or None when it is not a number at all."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _record(out_levels: Dict[int, int], relic_id: int, level: int) -> None:
    if level <= 0:
        level = 1
    if relic_id not in out_levels or level > out_levels[relic_id]:
        out_levels[relic_id] = level


def _scan_item(item: Dict[str, Any], out_levels: Dict[int, int], identified: bool = False) -> None:
    """Records `item` only on positive relic identification.

    A level-shaped field is not evidence: `p` is a star upgrade count and stacks
    carry `amount`/`count`/`qty`, so identity comes from the rarity tier, the
    relic-specific level field or, with `identified`, the class of the item
    instance or save key that holds this definition; the level only from
    RELIC_LEVEL_FIELDS.
    """
    relic_id = None
    for id_field in RELIC_ID_FIELDS:
        if id_field in item:
            relic_id = _as_int(item[id_field])
            break
    if relic_id is None or not 0 <= relic_id < RELIC_ID_LIMIT:
        return

    is_relic = identified or any(_as_int(item.get(f)) == RELIC_RARITY_TIER for f in RELIC_TIER_FIELDS)
    if RELIC_ONLY_FIELD in item:
        is_relic = True
    if not is_relic:
        return

    level = 0
    for level_field in RELIC_LEVEL_FIELDS:
        if level_field in item:
            value = _as_int(item[level_field])
            if value is not None and value > level:
                level = value

    _record(out_levels, relic_id, level)


def _scan_classified(container: Dict[Any, Any], out_levels: Dict[int, int]) -> None:
    """The two shapes where an item's class sits outside its definition (#93).

    An item instance (`itemType` beside `itemDefinitionStruct`, the in-memory
    shape C++ reads too) and a save entry keyed `x-y-<stamp>-<class>` wrapping
    `{"data": definition}`. Class RELIC_ITEM_CLASS identifies the definition as
    a relic; any other class adds nothing.
    """
    definition = container.get(ITEM_INSTANCE_DEFINITION_FIELD)
    if ITEM_INSTANCE_TYPE_FIELD in container and isinstance(definition, dict):
        if _as_int(container[ITEM_INSTANCE_TYPE_FIELD]) == RELIC_ITEM_CLASS:
            _scan_item(definition, out_levels, identified=True)

    for key, value in container.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        match = _ITEM_KEY.fullmatch(key)
        data = value.get("data")
        if match and int(match.group(1)) == RELIC_ITEM_CLASS and isinstance(data, dict):
            _scan_item(data, out_levels, identified=True)


def scan_relic_levels(
    container: Any,
    out_levels: Any = None,
    depth: int = 0,
    relic_container: bool = False,
) -> Dict[int, int]:
    """Extracts `relic id -> highest level` from raw dict/JSON player containers.

    `relic_container` marks the subtree as a dedicated relic container, where a
    bare number is a relic level indexed by relic id. It is set automatically
    when descending into a key named in RELIC_CONTAINER_FIELDS; callers scanning
    a known relic table directly can pass it themselves. Numbers in a general
    container are always ignored.
    """
    if out_levels is None:
        out_levels = {}
    if depth > MAX_SCAN_DEPTH:
        return out_levels

    if isinstance(container, dict):
        _scan_item(container, out_levels)
        _scan_classified(container, out_levels)
        for key, value in container.items():
            scan_relic_levels(
                value,
                out_levels,
                depth + 1,
                relic_container or key in RELIC_CONTAINER_FIELDS,
            )
    elif isinstance(container, (list, tuple)):
        for index, element in enumerate(container[:MAX_SCANNED_ARRAY_LENGTH]):
            number = _as_int(element)
            if number is not None:
                # `relic id -> level` only inside a recognised relic container.
                if relic_container and 0 <= index < RELIC_ID_LIMIT and number > 0:
                    _record(out_levels, index, number)
            else:
                scan_relic_levels(element, out_levels, depth + 1, relic_container)

    return out_levels


def maxed_relic_ids(container: Any) -> Set[int]:
    """Relic ids at MAXED_RELIC_LEVEL or above, the Python twin of
    HeroSiege::Player::GetMaxedRelicIds."""
    return {
        relic_id
        for relic_id, level in scan_relic_levels(container).items()
        if level >= MAXED_RELIC_LEVEL
    }
