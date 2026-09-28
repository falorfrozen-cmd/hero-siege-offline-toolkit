"""Hero Siege Game SDK.

Auto-generated bindings and models for Hero Siege GameMaker objects,
scripts, assets, and runtime structures.

The generated tables (objects, scripts, rooms, sprites, sounds) are imported
the first time one of their names is used, by ``__getattr__`` below (PEP 562),
so ``import hs_game_sdk`` builds none of their enums. Every name is still
importable from this package, or from its own module, exactly as before.
"""

import importlib as _importlib
from typing import TYPE_CHECKING

from .stats import (
    StatId,
    ProcBundle,
    PROC_FAMILIES,
    DECODED_STAT_NAMES,
    BUFF_ANGELIC_CHANCE,
)
from .satanic_zone import (
    SatanicMod,
    SATANIC_BUFFS,
    SATANIC_DEBUFFS,
    SATANIC_ZONE_VAR,
    SATANIC_ZONE_BUFF_VAR,
    SATANIC_ZONE_DEBUFF_VAR,
)
from .structs import (
    ItemDefinitionStruct,
    ItemStatStruct,
    CraftData,
    PlayerInstance,
)
from .player import (
    EquipmentSlot,
    PlayerEquipment,
    scan_relic_levels,
    maxed_relic_ids,
    RELIC_RARITY_TIER,
    RELIC_ID_LIMIT,
    MAXED_RELIC_LEVEL,
    MAX_SCAN_DEPTH,
    MAX_SCANNED_ARRAY_LENGTH,
    RELIC_ID_FIELDS,
    RELIC_TIER_FIELDS,
    RELIC_LEVEL_FIELDS,
    RELIC_ONLY_FIELD,
    GENERAL_CONTAINER_FIELDS,
    RELIC_CONTAINER_FIELDS,
)
from .item_type import ItemType
from .mod_registry import ModDefinition, ModRegistry, GLOBAL_MOD_REGISTRY

if TYPE_CHECKING:
    # Never executed. Type checkers and editors read these imports, and so
    # does PyInstaller, which bundles only the modules it sees imported: a
    # frozen app (ForgePact.exe) built without them would lack the tables.
    from .objects import (
        GameObject,
        OBJECT_INDEX_TO_NAME,
        OBJECT_NAME_TO_INDEX,
        OBJECT_PARENT_INDEX,
        OBJECT_MASK_SPRITE_INDEX,
        NO_PARENT,
        NO_MASK,
        get_parent_index,
        get_ancestor_indices,
        get_child_indices,
        get_descendant_indices,
        is_descendant_of,
        get_mask_sprite_index,
    )
    from .scripts import GameScript, SCRIPT_INDEX_TO_NAME, SCRIPT_NAME_TO_INDEX
    from .rooms import GameRoom, ROOM_INDEX_TO_NAME, ROOM_NAME_TO_INDEX
    from .sprites import GameSprite, SPRITE_INDEX_TO_NAME, SPRITE_NAME_TO_INDEX
    from .sounds import GameSound, SOUND_INDEX_TO_NAME, SOUND_NAME_TO_INDEX

# Each table module and the names this package re-exports from it: the
# imports above, as data. tests/test_sdk_lazy_import.py keeps the two equal.
_LAZY_MODULES = {
    "objects": (
        "GameObject",
        "OBJECT_INDEX_TO_NAME",
        "OBJECT_NAME_TO_INDEX",
        "OBJECT_PARENT_INDEX",
        "OBJECT_MASK_SPRITE_INDEX",
        "NO_PARENT",
        "NO_MASK",
        "get_parent_index",
        "get_ancestor_indices",
        "get_child_indices",
        "get_descendant_indices",
        "is_descendant_of",
        "get_mask_sprite_index",
    ),
    "scripts": ("GameScript", "SCRIPT_INDEX_TO_NAME", "SCRIPT_NAME_TO_INDEX"),
    "rooms": ("GameRoom", "ROOM_INDEX_TO_NAME", "ROOM_NAME_TO_INDEX"),
    "sprites": ("GameSprite", "SPRITE_INDEX_TO_NAME", "SPRITE_NAME_TO_INDEX"),
    "sounds": ("GameSound", "SOUND_INDEX_TO_NAME", "SOUND_NAME_TO_INDEX"),
}
_LAZY_NAMES = {name: module for module, names in _LAZY_MODULES.items() for name in names}


def __getattr__(name):
    """Import the table module that defines `name`, then keep its names here."""
    module_name = name if name in _LAZY_MODULES else _LAZY_NAMES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = _importlib.import_module(f"{__name__}.{module_name}")
    for attr in _LAZY_MODULES[module_name]:
        globals()[attr] = getattr(module, attr)
    return module if name == module_name else globals()[name]


def __dir__():
    return sorted(set(globals()) | set(_LAZY_MODULES) | set(_LAZY_NAMES))


__version__ = "1.1.0"
__all__ = [
    "GameObject",
    "OBJECT_INDEX_TO_NAME",
    "OBJECT_NAME_TO_INDEX",
    "OBJECT_PARENT_INDEX",
    "OBJECT_MASK_SPRITE_INDEX",
    "NO_PARENT",
    "NO_MASK",
    "get_parent_index",
    "get_ancestor_indices",
    "get_child_indices",
    "get_descendant_indices",
    "is_descendant_of",
    "get_mask_sprite_index",
    "GameScript",
    "SCRIPT_INDEX_TO_NAME",
    "SCRIPT_NAME_TO_INDEX",
    "GameRoom",
    "ROOM_INDEX_TO_NAME",
    "ROOM_NAME_TO_INDEX",
    "GameSprite",
    "SPRITE_INDEX_TO_NAME",
    "SPRITE_NAME_TO_INDEX",
    "GameSound",
    "SOUND_INDEX_TO_NAME",
    "SOUND_NAME_TO_INDEX",
    "StatId",
    "ProcBundle",
    "PROC_FAMILIES",
    "DECODED_STAT_NAMES",
    "BUFF_ANGELIC_CHANCE",
    "ItemDefinitionStruct",
    "ItemStatStruct",
    "CraftData",
    "PlayerInstance",
    "EquipmentSlot",
    "PlayerEquipment",
    "scan_relic_levels",
    "maxed_relic_ids",
    "RELIC_RARITY_TIER",
    "RELIC_ID_LIMIT",
    "MAXED_RELIC_LEVEL",
    "MAX_SCAN_DEPTH",
    "MAX_SCANNED_ARRAY_LENGTH",
    "RELIC_ID_FIELDS",
    "RELIC_TIER_FIELDS",
    "RELIC_LEVEL_FIELDS",
    "RELIC_ONLY_FIELD",
    "GENERAL_CONTAINER_FIELDS",
    "RELIC_CONTAINER_FIELDS",
    "ItemType",
    "ModDefinition",
    "ModRegistry",
    "GLOBAL_MOD_REGISTRY",
]
