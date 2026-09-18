"""Hero Siege Game SDK.

Auto-generated bindings and models for Hero Siege GameMaker objects,
scripts, assets, and runtime structures.
"""

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
