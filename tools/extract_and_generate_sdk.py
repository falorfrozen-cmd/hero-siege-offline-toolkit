"""Hero Siege Game SDK Generator and Asset Extractor.

Extracts all GameMaker objects, scripts, sprites, rooms, sounds, and strings
from data.win and Hero_Siege.exe, exports them to structured JSON, and generates
reusable Python, C++, and TypeScript bindings for use across all submodules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def sanitize_identifier(name: str) -> str:
    """Sanitize a name to make it a valid C++/Python/TS identifier."""
    # Replace non-alphanumeric chars with underscore
    clean = re.sub(r"[^0-9a-zA-Z_]", "_", name)
    if clean and clean[0].isdigit():
        clean = "_" + clean
    if not clean:
        clean = "_unnamed"
    return clean


class GameDataExtractor:
    def __init__(self, game_bin_dir: Path):
        self.game_bin = game_bin_dir.resolve()
        self.data_win_path = self.game_bin / "data.win"
        self.exe_path = self.game_bin / "Hero_Siege.exe"

        if not self.data_win_path.exists():
            raise FileNotFoundError(f"data.win not found at {self.data_win_path}")

        self.raw = self.data_win_path.read_bytes()
        if self.raw[:4] != b"FORM":
            raise ValueError("data.win is not a valid GameMaker IFF FORM file")

        self.chunks: Dict[str, Tuple[int, int]] = {}
        self._parse_chunks()
        self._strings: Dict[int, str] = {}

    def _parse_chunks(self) -> None:
        pos = 8
        while pos < len(self.raw):
            tag = self.raw[pos:pos + 4].decode("ascii", "replace")
            size = struct.unpack_from("<I", self.raw, pos + 4)[0]
            self.chunks[tag] = (pos + 8, size)
            pos += 8 + size

    def u32(self, p: int) -> int:
        return struct.unpack_from("<I", self.raw, p)[0]

    def i32(self, p: int) -> int:
        return struct.unpack_from("<i", self.raw, p)[0]

    def get_string(self, ptr: int) -> str:
        if ptr not in self._strings:
            n = self.u32(ptr - 4)
            self._strings[ptr] = self.raw[ptr:ptr + n].decode("utf-8", "replace")
        return self._strings[ptr]

    def ptr_list(self, base: int) -> List[int]:
        n = self.u32(base)
        return list(struct.unpack_from(f"<{n}I", self.raw, base + 4))

    def extract_all(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "metadata": {
                "game_bin": str(self.game_bin),
                "data_win_sha256": hashlib.sha256(self.raw).hexdigest(),
                "data_win_size": len(self.raw),
            },
            "objects": self.extract_objects(),
            "scripts": self.extract_scripts(),
            "sprites": self.extract_sprites(),
            "rooms": self.extract_rooms(),
            "sounds": self.extract_sounds(),
        }

        if self.exe_path.exists():
            with self.exe_path.open("rb") as f:
                data["metadata"]["exe_sha256"] = hashlib.file_digest(f, "sha256").hexdigest()
                data["metadata"]["exe_size"] = self.exe_path.stat().st_size

        return data

    # OBJT record layout, measured against this build's data.win (GEN8 bytecode
    # version 17; UILR/PSEM/PSYS/FEAT chunks present). This runtime inserts a
    # `managed` flag after `visible`, which shifts every following field by 4
    # bytes relative to the pre-2022.5 layout. Offsets are relative to a record
    # pointer from the OBJT pointer list:
    #
    #   +0   name                  string pointer
    #   +4   sprite_index          i32, -1 = no sprite
    #   +8   visible               bool32
    #   +12  managed               bool32  <- inserted by this runtime version
    #   +16  solid                 bool32
    #   +20  depth                 i32
    #   +24  persistent            bool32
    #   +28  parent_index          i32, OBJECT_NO_PARENT (-100) = no parent
    #   +32  mask_index            i32 sprite index, -1 = use sprite_index
    #   +36  uses_physics          bool32
    #   +40  is_sensor             bool32
    #   +44  collision_shape       i32
    #   +48  physics props         floats (density, restitution, ...)
    #   ...  physics shape vertices, then the 15 event-type lists
    #
    # Anchors that pin this layout (see tests/test_object_hierarchy.py):
    #   * +48/+52/+64/+72 hold the GameMaker physics defaults 0.5/0.1/0.1/0.2.
    #   * Reading the tail from +68 (vertex count) yields exactly 15 event lists
    #     with in-chunk, ascending pointers for all 6016 records, and no record
    #     overruns the next record's start.
    #   * +28 is always -100 or a valid object index; +32 resolves to sprites
    #     named "*_Mask_spr" / "Mask_Circle_*_spr".
    OBJ_OFF_SPRITE = 4
    OBJ_OFF_VISIBLE = 8
    OBJ_OFF_MANAGED = 12
    OBJ_OFF_SOLID = 16
    OBJ_OFF_DEPTH = 20
    OBJ_OFF_PERSISTENT = 24
    OBJ_OFF_PARENT = 28
    OBJ_OFF_MASK = 32

    #: Sentinel stored in an object's parent slot when it has no parent object.
    OBJECT_NO_PARENT = -100
    #: Sentinel stored in an object's mask slot when it collides with its sprite.
    OBJECT_NO_MASK = -1

    def extract_objects(self) -> List[Dict[str, Any]]:
        if "OBJT" not in self.chunks:
            return []
        objt_base, _ = self.chunks["OBJT"]
        obj_ptrs = self.ptr_list(objt_base)
        objects = []
        for idx, ptr in enumerate(obj_ptrs):
            objects.append({
                "index": idx,
                "name": self.get_string(self.u32(ptr)),
                "sprite_index": self.i32(ptr + self.OBJ_OFF_SPRITE),
                "parent_index": self.i32(ptr + self.OBJ_OFF_PARENT),
                "depth": self.i32(ptr + self.OBJ_OFF_DEPTH),
                "visible": bool(self.u32(ptr + self.OBJ_OFF_VISIBLE)),
                "managed": bool(self.u32(ptr + self.OBJ_OFF_MANAGED)),
                "solid": bool(self.u32(ptr + self.OBJ_OFF_SOLID)),
                "persistent": bool(self.u32(ptr + self.OBJ_OFF_PERSISTENT)),
                "mask_index": self.i32(ptr + self.OBJ_OFF_MASK),
            })
        return objects

    def extract_scripts(self) -> List[Dict[str, Any]]:
        if "SCPT" not in self.chunks:
            return []
        scpt_base, _ = self.chunks["SCPT"]
        scpt_ptrs = self.ptr_list(scpt_base)
        scripts = []
        for idx, ptr in enumerate(scpt_ptrs):
            name = self.get_string(self.u32(ptr))
            scripts.append({
                "index": idx,
                "name": name
            })
        return scripts

    def extract_sprites(self) -> List[Dict[str, Any]]:
        if "SPRT" not in self.chunks:
            return []
        sprt_base, _ = self.chunks["SPRT"]
        sprt_ptrs = self.ptr_list(sprt_base)
        sprites = []
        for idx, ptr in enumerate(sprt_ptrs):
            name = self.get_string(self.u32(ptr))
            sprites.append({
                "index": idx,
                "name": name
            })
        return sprites

    def extract_rooms(self) -> List[Dict[str, Any]]:
        if "ROOM" not in self.chunks:
            return []
        room_base, _ = self.chunks["ROOM"]
        room_ptrs = self.ptr_list(room_base)
        rooms = []
        for idx, ptr in enumerate(room_ptrs):
            name = self.get_string(self.u32(ptr))
            rooms.append({
                "index": idx,
                "name": name
            })
        return rooms

    def extract_sounds(self) -> List[Dict[str, Any]]:
        if "SOND" not in self.chunks:
            return []
        sond_base, _ = self.chunks["SOND"]
        sond_ptrs = self.ptr_list(sond_base)
        sounds = []
        for idx, ptr in enumerate(sond_ptrs):
            name = self.get_string(self.u32(ptr))
            sounds.append({
                "index": idx,
                "name": name
            })
        return sounds


# Hierarchy helpers appended verbatim to the generated hs_game_sdk/objects.py.
# They read the OBJECT_PARENT_INDEX / OBJECT_MASK_SPRITE_INDEX tables emitted
# just above them.
OBJECT_HIERARCHY_PY = '''

ObjectRef = Union[int, str, "GameObject"]

_CHILDREN: dict[int, tuple[int, ...]] = {}


def _resolve(obj: ObjectRef) -> int:
    """Normalize an object name, index or enum member to an object index."""
    if isinstance(obj, str):
        try:
            return OBJECT_NAME_TO_INDEX[obj]
        except KeyError:
            raise KeyError(f"Unknown object name: {obj!r}") from None
    return int(obj)


def _children_table() -> dict[int, tuple[int, ...]]:
    if not _CHILDREN:
        acc: dict[int, list[int]] = {}
        for child, parent in OBJECT_PARENT_INDEX.items():
            acc.setdefault(parent, []).append(child)
        _CHILDREN.update({p: tuple(sorted(c)) for p, c in acc.items()})
    return _CHILDREN


def get_parent_index(obj: ObjectRef) -> Optional[int]:
    """Direct parent object index, or None when `obj` is a root object."""
    return OBJECT_PARENT_INDEX.get(_resolve(obj))


def iter_ancestor_indices(obj: ObjectRef) -> Iterator[int]:
    """Yield parent, grandparent, ... up to the root. Cycle-safe."""
    seen: set[int] = set()
    current = OBJECT_PARENT_INDEX.get(_resolve(obj))
    while current is not None and current not in seen:
        seen.add(current)
        yield current
        current = OBJECT_PARENT_INDEX.get(current)


def get_ancestor_indices(obj: ObjectRef) -> tuple[int, ...]:
    """Parent chain from the direct parent up to the root."""
    return tuple(iter_ancestor_indices(obj))


def get_child_indices(obj: ObjectRef) -> tuple[int, ...]:
    """Direct children of an object, ascending by index."""
    return _children_table().get(_resolve(obj), ())


def iter_descendant_indices(obj: ObjectRef) -> Iterator[int]:
    """Yield every object below `obj` in the hierarchy. Cycle-safe."""
    table = _children_table()
    seen: set[int] = set()
    stack = list(table.get(_resolve(obj), ()))
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        yield current
        stack.extend(table.get(current, ()))


def get_descendant_indices(obj: ObjectRef) -> tuple[int, ...]:
    """Every object below `obj` in the hierarchy, ascending by index."""
    return tuple(sorted(iter_descendant_indices(obj)))


def is_descendant_of(obj: ObjectRef, ancestor: ObjectRef) -> bool:
    """True when `obj` inherits from `ancestor` at any depth.

    Mirrors the GML `object_is_ancestor(obj, ancestor)` relation, so a hook that
    wants "every enemy" can test membership instead of enumerating indices.
    """
    target = _resolve(ancestor)
    return any(a == target for a in iter_ancestor_indices(obj))


def get_mask_sprite_index(obj: ObjectRef) -> Optional[int]:
    """Explicit collision mask sprite index, or None when the object uses its own sprite."""
    return OBJECT_MASK_SPRITE_INDEX.get(_resolve(obj))
'''


def generate_python_bindings(data: Dict[str, Any], output_dir: Path) -> None:
    py_dir = output_dir / "python" / "hs_game_sdk"
    py_dir.mkdir(parents=True, exist_ok=True)

    # 1. __init__.py
    init_content = '''"""Hero Siege Game SDK.

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
'''
    (py_dir / "__init__.py").write_text(init_content, encoding="utf-8")

    # 2. objects.py
    lines = [
        '"""GameMaker GameObject enumeration, index maps and parent hierarchy."""',
        "from __future__ import annotations",
        "from enum import IntEnum",
        "from typing import Iterator, Optional, Union\n",
        "class GameObject(IntEnum):",
    ]
    name_map: Dict[str, int] = {}
    idx_map: Dict[int, str] = {}
    used_enum_names = set()

    for obj in data["objects"]:
        name = obj["name"]
        idx = obj["index"]
        enum_name = sanitize_identifier(name)
        if enum_name in used_enum_names:
            enum_name = f"{enum_name}_{idx}"
        used_enum_names.add(enum_name)
        lines.append(f"    {enum_name} = {idx}")
        name_map[name] = idx
        idx_map[idx] = name

    parent_map = {
        o["index"]: o["parent_index"]
        for o in data["objects"]
        if o["parent_index"] != GameDataExtractor.OBJECT_NO_PARENT
    }
    mask_map = {
        o["index"]: o["mask_index"]
        for o in data["objects"]
        if o["mask_index"] != GameDataExtractor.OBJECT_NO_MASK
    }

    lines.append("\n")
    lines.append("OBJECT_NAME_TO_INDEX: dict[str, int] = " + repr(name_map))
    lines.append("OBJECT_INDEX_TO_NAME: dict[int, str] = " + repr(idx_map))
    lines.append("")
    lines.append(f"NO_PARENT = {GameDataExtractor.OBJECT_NO_PARENT}")
    lines.append(f"NO_MASK = {GameDataExtractor.OBJECT_NO_MASK}")
    lines.append("")
    lines.append("#: Child object index -> parent object index. Root objects are absent.")
    lines.append("OBJECT_PARENT_INDEX: dict[int, int] = " + repr(parent_map))
    lines.append("#: Object index -> collision mask *sprite* index. Absent means the")
    lines.append("#: object collides using its own sprite_index.")
    lines.append("OBJECT_MASK_SPRITE_INDEX: dict[int, int] = " + repr(mask_map))
    lines.append(OBJECT_HIERARCHY_PY)
    (py_dir / "objects.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 3. scripts.py
    lines = [
        '"""GameMaker Script enumeration and index lookup tables."""',
        "from __future__ import annotations",
        "from enum import IntEnum\n",
        "class GameScript(IntEnum):",
    ]
    script_name_map: Dict[str, int] = {}
    script_idx_map: Dict[int, str] = {}
    used_script_enum_names = set()

    for sc in data["scripts"]:
        name = sc["name"]
        idx = sc["index"]
        enum_name = sanitize_identifier(name)
        if enum_name in used_script_enum_names:
            enum_name = f"{enum_name}_{idx}"
        used_script_enum_names.add(enum_name)
        lines.append(f"    {enum_name} = {idx}")
        script_name_map[name] = idx
        script_idx_map[idx] = name

    lines.append("\n")
    lines.append("SCRIPT_NAME_TO_INDEX: dict[str, int] = " + repr(script_name_map))
    lines.append("SCRIPT_INDEX_TO_NAME: dict[int, str] = " + repr(script_idx_map))
    (py_dir / "scripts.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 4. rooms.py
    lines = [
        '"""GameMaker Room enumeration and lookup tables."""',
        "from __future__ import annotations",
        "from enum import IntEnum\n",
        "class GameRoom(IntEnum):",
    ]
    room_name_map: Dict[str, int] = {}
    room_idx_map: Dict[int, str] = {}
    used_room_names = set()
    for rm in data["rooms"]:
        name = rm["name"]
        idx = rm["index"]
        enum_name = sanitize_identifier(name)
        if enum_name in used_room_names:
            enum_name = f"{enum_name}_{idx}"
        used_room_names.add(enum_name)
        lines.append(f"    {enum_name} = {idx}")
        room_name_map[name] = idx
        room_idx_map[idx] = name

    lines.append("\n")
    lines.append("ROOM_NAME_TO_INDEX: dict[str, int] = " + repr(room_name_map))
    lines.append("ROOM_INDEX_TO_NAME: dict[int, str] = " + repr(room_idx_map))
    (py_dir / "rooms.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 5. sprites.py
    lines = [
        '"""GameMaker Sprite enumeration and lookup tables."""',
        "from __future__ import annotations",
        "from enum import IntEnum\n",
        "class GameSprite(IntEnum):",
    ]
    spr_name_map: Dict[str, int] = {}
    spr_idx_map: Dict[int, str] = {}
    used_spr_names = set()
    for sp in data["sprites"]:
        name = sp["name"]
        idx = sp["index"]
        enum_name = sanitize_identifier(name)
        if enum_name in used_spr_names:
            enum_name = f"{enum_name}_{idx}"
        used_spr_names.add(enum_name)
        lines.append(f"    {enum_name} = {idx}")
        spr_name_map[name] = idx
        spr_idx_map[idx] = name

    lines.append("\n")
    lines.append("SPRITE_NAME_TO_INDEX: dict[str, int] = " + repr(spr_name_map))
    lines.append("SPRITE_INDEX_TO_NAME: dict[int, str] = " + repr(spr_idx_map))
    (py_dir / "sprites.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 6. sounds.py
    lines = [
        '"""GameMaker Sound enumeration and lookup tables."""',
        "from __future__ import annotations",
        "from enum import IntEnum\n",
        "class GameSound(IntEnum):",
    ]
    snd_name_map: Dict[str, int] = {}
    snd_idx_map: Dict[int, str] = {}
    used_snd_names = set()
    for snd in data["sounds"]:
        name = snd["name"]
        idx = snd["index"]
        enum_name = sanitize_identifier(name)
        if enum_name in used_snd_names:
            enum_name = f"{enum_name}_{idx}"
        used_snd_names.add(enum_name)
        lines.append(f"    {enum_name} = {idx}")
        snd_name_map[name] = idx
        snd_idx_map[idx] = name

    lines.append("\n")
    lines.append("SOUND_NAME_TO_INDEX: dict[str, int] = " + repr(snd_name_map))
    lines.append("SOUND_INDEX_TO_NAME: dict[int, str] = " + repr(snd_idx_map))
    (py_dir / "sounds.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 7. stats.py
    stats_content = '''"""Hero Siege Stat IDs, Proc Bundles, Buffs, and Roll Constants."""

from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum

BUFF_ANGELIC_CHANCE = 332

class StatId(IntEnum):
    STRENGTH = 0
    DEFENSE = 1
    SWIFTNESS = 2
    STAMINA = 3
    ENERGY = 4
    PHYSICAL_DAMAGE = 5
    FIRE_DAMAGE = 6
    ICE_DAMAGE = 7
    LIGHTNING_DAMAGE = 8
    POISON_DAMAGE = 9
    MAGIC_DAMAGE = 10
    WIND_DAMAGE = 11
    HOLY_DAMAGE = 12
    SHADOW_DAMAGE = 13
    CHAOS_DAMAGE = 14
    ATTACK_SPEED = 15
    CAST_RATE = 16
    CRITICAL_RATE = 17
    CRITICAL_DAMAGE = 18
    MOVEMENT_SPEED = 19
    MAGIC_FIND = 20
    EXTRA_GOLD = 21
    EXP_GAIN = 22
    ALL_STATS = 23
    MAX_HEALTH = 24
    MAX_MANA = 25
    HEALTH_REGEN = 26
    MANA_REGEN = 27
    MANA_PER_HIT = 28
    HEALTH_PER_HIT = 29
    LIFE_PER_KILL = 30
    MANA_PER_KILL = 31
    LIFE_LEECH = 32
    MANA_LEECH = 33
    COOLDOWN_REDUCTION = 34
    DODGE_CHANCE = 35
    BLOCK_CHANCE = 36
    DAMAGE_REDUCTION = 37
    DAMAGE_TO_BOSSES = 38
    DAMAGE_TO_ELITES = 39
    ARMOR_PENETRATION = 40
    MAGIC_PENETRATION = 41
    JEWELCRAFTING_LEVEL = 157

@dataclass(frozen=True)
class ProcBundle:
    trigger: str
    skill_id_key: int
    level_key: int
    chance_key: int

PROC_FAMILIES = {
    "when_striking": ProcBundle("When Striking", 116, 117, 118),
    "when_attacking": ProcBundle("When Attacking", 113, 114, 115),
    "after_kill": ProcBundle("After Kill", 122, 123, 124),
    "when_casting": ProcBundle("When Casting", 125, 126, 127),
    "when_struck": ProcBundle("When Struck", 185, 186, 187),
    "after_blocking": ProcBundle("After Blocking", 188, 189, 190),
}

DECODED_STAT_NAMES: dict[int, str] = {
    0: "Strength",
    1: "Defense",
    2: "Swiftness",
    3: "Stamina",
    4: "Energy",
    5: "Physical Damage",
    6: "Fire Damage",
    7: "Ice Damage",
    8: "Lightning Damage",
    9: "Poison Damage",
    10: "Magic Damage",
    11: "Wind Damage",
    12: "Holy Damage",
    13: "Shadow Damage",
    14: "Chaos Damage",
    15: "Attack Speed",
    16: "Cast Rate",
    17: "Critical Rate",
    18: "Critical Damage",
    19: "Movement Speed",
    20: "Magic Find",
    21: "Extra Gold",
    22: "Experience Gain",
    23: "All Attributes",
    24: "Max Health",
    25: "Max Mana",
    26: "Health Regen",
    27: "Mana Regen",
    28: "Mana Per Hit",
    29: "Health Per Hit",
    30: "Life Per Kill",
    31: "Mana Per Kill",
    32: "Life Leech",
    33: "Mana Leech",
    34: "Cooldown Reduction",
    35: "Dodge Chance",
    36: "Block Chance",
    37: "Damage Reduction",
    38: "Damage to Bosses",
    39: "Damage to Elites",
    40: "Armor Penetration",
    41: "Magic Penetration",
    157: "Jewelcrafting Level",
}
'''
    (py_dir / "stats.py").write_text(stats_content, encoding="utf-8")

    # 8. structs.py
    structs_content = '''"""Data structures for Hero Siege runtime items, players, and crafting."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class ItemDefinitionStruct:
    a: int = 0          # generation seed / serial
    b: int = 0          # base item ID in catalog
    c: int = 0          # isUnique (1 = unique repo, 0 = normal repo)
    j: int = 0          # subtype / weapon sub-class
    i: Optional[int] = None   # secondary seed (if applicable)
    s: Optional[int] = None   # socket generation seed
    r: int = 0          # corrupted flag
    p: int = 0          # star upgrade count
    extra: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ItemStatStruct:
    stats: Dict[int, float] = field(default_factory=dict)

    def get(self, stat_id: int, default: float = 0.0) -> float:
        return self.stats.get(stat_id, default)

    def set(self, stat_id: int, value: float) -> None:
        self.stats[stat_id] = value

@dataclass
class CraftData:
    item_type: Any
    item_id: Any
    result_chance: float = 100.0
    is_unique: bool = False
    amount: int = 1
    result_type: int = 0
    tier_requirement: Optional[int] = None
    rarity_requirement: Optional[int] = None
    craft_name: Optional[str] = None
    craft_desc: Optional[str] = None
    allow_multi_craft: bool = False
    keep_item: bool = False

@dataclass
class PlayerInstance:
    instance_id: int
    object_index: int
    x: float = 0.0
    y: float = 0.0
    buffs: Dict[int, float] = field(default_factory=dict)
'''
    (py_dir / "structs.py").write_text(structs_content, encoding="utf-8")

    # 9. setup.py and pyproject.toml for standard packaging
    pyproject = '''[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "hs-game-sdk"
version = "1.0.0"
description = "Hero Siege Game SDK - GameMaker symbols, object schemas, and runtime SDK"
readme = "README.md"
requires-python = ">=3.8"
dependencies = []

[tool.setuptools.packages.find]
where = ["."]
'''
    (output_dir / "python" / "pyproject.toml").write_text(pyproject, encoding="utf-8")

    setup_py = '''from setuptools import setup, find_packages

setup(
    name="hs-game-sdk",
    version="1.0.0",
    packages=find_packages(),
)
'''
    (output_dir / "python" / "setup.py").write_text(setup_py, encoding="utf-8")
    (output_dir / "python" / "README.md").write_text("# Hero Siege Game SDK (Python)\n\nImportable SDK for Hero Siege GameMaker symbols, objects, scripts, and stat models.\n", encoding="utf-8")


def _packed_int_table(values: List[int], per_line: int = 16) -> List[str]:
    """Format an int list as brace-initializer body lines."""
    out = []
    for start in range(0, len(values), per_line):
        chunk = values[start:start + per_line]
        out.append("    " + ", ".join(str(v) for v in chunk) + ",")
    return out


def _cpp_hierarchy_lines(data: Dict[str, Any]) -> List[str]:
    """Parent/mask tables plus lookup helpers for objects.hpp."""
    objects = data["objects"]
    count = len(objects)
    parents = [o["parent_index"] for o in objects]
    masks = [o["mask_index"] for o in objects]

    lines = [
        f"//: Sentinel stored in the parent slot of a root object.",
        f"inline constexpr int32_t kNoParent = {GameDataExtractor.OBJECT_NO_PARENT};",
        "//: Sentinel meaning \"collide using my own sprite\".",
        f"inline constexpr int32_t kNoMask = {GameDataExtractor.OBJECT_NO_MASK};",
        f"inline constexpr int32_t kObjectCount = {count};",
        "",
        "//: Parent object index per object index; kNoParent for root objects.",
        f"inline constexpr std::array<int32_t, {count}> kObjectParents = {{",
    ]
    lines.extend(_packed_int_table(parents))
    lines.extend([
        "};",
        "",
        "//: Collision mask *sprite* index per object index; kNoMask when the",
        "//: object collides using its own sprite.",
        f"inline constexpr std::array<int32_t, {count}> kObjectMasks = {{",
    ])
    lines.extend(_packed_int_table(masks))
    lines.extend([
        "};",
        "",
        "[[nodiscard]] inline constexpr bool IsValidObject(int32_t obj) {",
        "    return obj >= 0 && obj < kObjectCount;",
        "}",
        "",
        "//: Direct parent object index, or kNoParent for a root/unknown object.",
        "[[nodiscard]] inline constexpr int32_t GetParentObject(int32_t obj) {",
        "    return IsValidObject(obj) ? kObjectParents[static_cast<size_t>(obj)] : kNoParent;",
        "}",
        "",
        "[[nodiscard]] inline constexpr int32_t GetParentObject(GameObject obj) {",
        "    return GetParentObject(static_cast<int32_t>(obj));",
        "}",
        "",
        "//: Collision mask sprite index, or kNoMask when the object uses its own sprite.",
        "[[nodiscard]] inline constexpr int32_t GetMaskSpriteIndex(int32_t obj) {",
        "    return IsValidObject(obj) ? kObjectMasks[static_cast<size_t>(obj)] : kNoMask;",
        "}",
        "",
        "[[nodiscard]] inline constexpr int32_t GetMaskSpriteIndex(GameObject obj) {",
        "    return GetMaskSpriteIndex(static_cast<int32_t>(obj));",
        "}",
        "",
        "//: True when `obj` inherits from `ancestor` at any depth, mirroring the",
        "//: GML object_is_ancestor() relation. Bounded so a malformed table cannot",
        "//: spin forever.",
        "[[nodiscard]] inline constexpr bool IsDescendantOf(int32_t obj, int32_t ancestor) {",
        "    int32_t current = GetParentObject(obj);",
        "    for (int32_t hops = 0; current != kNoParent && hops < kObjectCount; ++hops) {",
        "        if (current == ancestor) {",
        "            return true;",
        "        }",
        "        current = GetParentObject(current);",
        "    }",
        "    return false;",
        "}",
        "",
        "[[nodiscard]] inline constexpr bool IsDescendantOf(GameObject obj, GameObject ancestor) {",
        "    return IsDescendantOf(static_cast<int32_t>(obj), static_cast<int32_t>(ancestor));",
        "}",
        "",
        "//: Direct children of `obj`, ascending by index.",
        "[[nodiscard]] inline std::vector<int32_t> GetChildObjects(int32_t obj) {",
        "    std::vector<int32_t> children;",
        "    for (int32_t i = 0; i < kObjectCount; ++i) {",
        "        if (kObjectParents[static_cast<size_t>(i)] == obj) {",
        "            children.push_back(i);",
        "        }",
        "    }",
        "    return children;",
        "}",
        "",
        "//: Every object below `obj` in the hierarchy, ascending by index.",
        "[[nodiscard]] inline std::vector<int32_t> GetDescendantObjects(int32_t obj) {",
        "    std::vector<int32_t> descendants;",
        "    for (int32_t i = 0; i < kObjectCount; ++i) {",
        "        if (IsDescendantOf(i, obj)) {",
        "            descendants.push_back(i);",
        "        }",
        "    }",
        "    return descendants;",
        "}",
    ])
    return lines


def generate_cpp_bindings(data: Dict[str, Any], output_dir: Path) -> None:
    inc_dir = output_dir / "cpp" / "include" / "hs_game_sdk"
    inc_dir.mkdir(parents=True, exist_ok=True)

    # 1. objects.hpp
    lines = [
        "#pragma once",
        "#include <array>",
        "#include <cstdint>",
        "#include <string_view>",
        "#include <string>",
        "#include <unordered_map>",
        "#include <vector>",
        "",
        "namespace HeroSiege::Objects {",
        "",
        "enum class GameObject : int32_t {",
    ]
    used_names = set()
    for obj in data["objects"]:
        name = obj["name"]
        idx = obj["index"]
        clean = sanitize_identifier(name)
        if clean in used_names:
            clean = f"{clean}_{idx}"
        used_names.add(clean)
        lines.append(f"    {clean} = {idx},")

    lines.extend([
        "};",
        "",
        "[[nodiscard]] inline std::string_view GetObjectName(GameObject obj) {",
        "    switch (obj) {",
    ])
    for obj in data["objects"]:
        name = obj["name"]
        idx = obj["index"]
        lines.append(f"        case GameObject({idx}): return \"{name}\";")
    lines.extend([
        "        default: return \"Unknown_Object\";",
        "    }",
        "}",
        "",
    ])
    lines.extend(_cpp_hierarchy_lines(data))
    lines.extend([
        "",
        "} // namespace HeroSiege::Objects",
    ])
    (inc_dir / "objects.hpp").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 2. scripts.hpp
    lines = [
        "#pragma once",
        "#include <cstdint>",
        "#include <string_view>",
        "",
        "namespace HeroSiege::Scripts {",
        "",
    ]
    used_script_names = set()
    for sc in data["scripts"]:
        name = sc["name"]
        idx = sc["index"]
        clean = sanitize_identifier(name)
        if clean in used_script_names:
            clean = f"{clean}_{idx}"
        used_script_names.add(clean)
        lines.append(f"inline constexpr std::string_view {clean} = \"{name}\";")
        lines.append(f"inline constexpr int32_t {clean}_Index = {idx};")

    lines.extend([
        "",
        "} // namespace HeroSiege::Scripts",
    ])
    (inc_dir / "scripts.hpp").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 3. rooms.hpp
    lines = [
        "#pragma once",
        "#include <cstdint>",
        "#include <string_view>",
        "",
        "namespace HeroSiege::Rooms {",
        "",
        "enum class GameRoom : int32_t {",
    ]
    used_room_names = set()
    for rm in data["rooms"]:
        name = rm["name"]
        idx = rm["index"]
        clean = sanitize_identifier(name)
        if clean in used_room_names:
            clean = f"{clean}_{idx}"
        used_room_names.add(clean)
        lines.append(f"    {clean} = {idx},")

    lines.extend([
        "};",
        "",
        "} // namespace HeroSiege::Rooms",
    ])
    (inc_dir / "rooms.hpp").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 4. yytk_helpers.hpp
    helpers = '''#pragma once
#include <string_view>
#include <vector>
#include <string>
#include "objects.hpp"
#include "scripts.hpp"

#ifdef __has_include
#if __has_include(<YYToolkit/YYTK_Shared.hpp>)
#include <YYToolkit/YYTK_Shared.hpp>
#define HS_SDK_HAS_YYTK 1
#endif
#endif

namespace HeroSiege::YYTK {

#ifdef HS_SDK_HAS_YYTK
using ::YYTK::RValue;
using ::YYTK::CInstance;
using ::YYTK::YYTKInterface;
using ::YYTK::CScript;
using ::YYTK::PFUNC_YYGMLScript;

inline RValue CallGameScript(YYTKInterface* yytk, std::string_view scriptName, const std::vector<RValue>& args = {}) {
    if (!yytk) return RValue();
    return yytk->CallGameScript(std::string(scriptName), args);
}

inline RValue GetInstanceVariable(YYTKInterface* yytk, const RValue& instance, std::string_view varName) {
    if (!yytk) return RValue();
    return yytk->CallBuiltin("variable_instance_get", { instance, RValue(std::string(varName)) });
}

inline void SetInstanceVariable(YYTKInterface* yytk, const RValue& instance, std::string_view varName, const RValue& value) {
    if (!yytk) return;
    yytk->CallBuiltin("variable_instance_set", { instance, RValue(std::string(varName)), value });
}

inline bool InstanceHasVariable(YYTKInterface* yytk, const RValue& instance, std::string_view varName) {
    if (!yytk) return false;
    return yytk->CallBuiltin("variable_instance_exists", { instance, RValue(std::string(varName)) }).ToBoolean();
}

inline RValue GetStructVariable(YYTKInterface* yytk, const RValue& structVal, std::string_view varName) {
    if (!yytk || structVal.m_Kind != ::YYTK::VALUE_OBJECT) return RValue();
    return yytk->CallBuiltin("variable_struct_get", { structVal, RValue(std::string(varName)) });
}

inline RValue GetStructVariable(YYTKInterface* yytk, const RValue& structVal, const char* varName) {
    if (!yytk || structVal.m_Kind != ::YYTK::VALUE_OBJECT || !varName) return RValue();
    return yytk->CallBuiltin("variable_struct_get", { structVal, RValue(std::string(varName)) });
}

inline RValue GetStructElement(YYTKInterface* yytk, const RValue& structVal, const RValue& keyVal) {
    if (!yytk || structVal.m_Kind != ::YYTK::VALUE_OBJECT) return RValue();
    return yytk->CallBuiltin("variable_struct_get", { structVal, keyVal });
}

inline void SetStructVariable(YYTKInterface* yytk, const RValue& structVal, std::string_view varName, const RValue& value) {
    if (!yytk || structVal.m_Kind != ::YYTK::VALUE_OBJECT) return;
    yytk->CallBuiltin("variable_struct_set", { structVal, RValue(std::string(varName)), value });
}

inline bool StructHasVariable(YYTKInterface* yytk, const RValue& structVal, std::string_view varName) {
    if (!yytk || structVal.m_Kind != ::YYTK::VALUE_OBJECT) return false;
    return yytk->CallBuiltin("variable_struct_exists", { structVal, RValue(std::string(varName)) }).ToBoolean();
}

inline RValue GetGlobalVariable(YYTKInterface* yytk, std::string_view varName) {
    if (!yytk) return RValue();
    return yytk->CallBuiltin("variable_global_get", { RValue(std::string(varName)) });
}

inline void SetGlobalVariable(YYTKInterface* yytk, std::string_view varName, const RValue& value) {
    if (!yytk) return;
    yytk->CallBuiltin("variable_global_set", { RValue(std::string(varName)), value });
}

inline bool GlobalHasVariable(YYTKInterface* yytk, std::string_view varName) {
    if (!yytk) return false;
    return yytk->CallBuiltin("variable_global_exists", { RValue(std::string(varName)) }).ToBoolean();
}

inline int GetArrayLength(YYTKInterface* yytk, const RValue& arrayVal) {
    if (!yytk || arrayVal.m_Kind != ::YYTK::VALUE_ARRAY) return 0;
    return static_cast<int>(yytk->CallBuiltin("array_length", { arrayVal }).ToDouble());
}

inline RValue GetArrayElement(YYTKInterface* yytk, const RValue& arrayVal, int index) {
    if (!yytk || arrayVal.m_Kind != ::YYTK::VALUE_ARRAY) return RValue();
    return yytk->CallBuiltin("array_get", { arrayVal, RValue(static_cast<double>(index)) });
}

#endif

} // namespace HeroSiege::YYTK
'''
    (inc_dir / "yytk_helpers.hpp").write_text(helpers, encoding="utf-8")

    # 5. hs_game_sdk.hpp
    main_header = '''#pragma once

#include "objects.hpp"
#include "scripts.hpp"
#include "rooms.hpp"
#include "yytk_helpers.hpp"
#include "hooks.hpp"
#include "player.hpp"
#include "satanic_zone.hpp"
#include "item_type.hpp"

namespace HeroSiege {
    inline constexpr int32_t BUFF_ANGELIC_CHANCE = 332;
    inline constexpr int32_t STAT_JEWELCRAFTING_LEVEL = 157;
}
'''
    (inc_dir / "hs_game_sdk.hpp").write_text(main_header, encoding="utf-8")


# Hierarchy helpers appended verbatim to the generated ts/src/objects.ts.
OBJECT_HIERARCHY_TS = '''
let childrenTable: Map<number, number[]> | null = null;

function childrenByParent(): Map<number, number[]> {
  if (childrenTable === null) {
    childrenTable = new Map<number, number[]>();
    for (const [child, parent] of Object.entries(OBJECT_PARENT_INDEX)) {
      const bucket = childrenTable.get(parent);
      if (bucket === undefined) {
        childrenTable.set(parent, [Number(child)]);
      } else {
        bucket.push(Number(child));
      }
    }
    for (const bucket of childrenTable.values()) {
      bucket.sort((a, b) => a - b);
    }
  }
  return childrenTable;
}

/** Direct parent object index, or undefined when `obj` is a root object. */
export function getParentObject(obj: number): number | undefined {
  return OBJECT_PARENT_INDEX[obj];
}

/** Parent chain from the direct parent up to the root. Cycle-safe. */
export function getAncestorObjects(obj: number): number[] {
  const chain: number[] = [];
  const seen = new Set<number>();
  let current = OBJECT_PARENT_INDEX[obj];
  while (current !== undefined && !seen.has(current)) {
    seen.add(current);
    chain.push(current);
    current = OBJECT_PARENT_INDEX[current];
  }
  return chain;
}

/** Direct children of an object, ascending by index. */
export function getChildObjects(obj: number): number[] {
  return childrenByParent().get(obj) ?? [];
}

/** Every object below `obj` in the hierarchy, ascending by index. Cycle-safe. */
export function getDescendantObjects(obj: number): number[] {
  const table = childrenByParent();
  const seen = new Set<number>();
  const stack = [...(table.get(obj) ?? [])];
  while (stack.length > 0) {
    const current = stack.pop() as number;
    if (seen.has(current)) {
      continue;
    }
    seen.add(current);
    stack.push(...(table.get(current) ?? []));
  }
  return [...seen].sort((a, b) => a - b);
}

/**
 * True when `obj` inherits from `ancestor` at any depth, mirroring the GML
 * object_is_ancestor() relation.
 */
export function isDescendantOf(obj: number, ancestor: number): boolean {
  return getAncestorObjects(obj).includes(ancestor);
}

/** Explicit collision mask sprite index, or undefined when the object uses its own sprite. */
export function getMaskSpriteIndex(obj: number): number | undefined {
  return OBJECT_MASK_SPRITE_INDEX[obj];
}
'''


def generate_ts_bindings(data: Dict[str, Any], output_dir: Path) -> None:
    ts_dir = output_dir / "ts" / "src"
    ts_dir.mkdir(parents=True, exist_ok=True)

    # 1. index.ts
    index_content = '''/**
 * Hero Siege Game SDK (TypeScript / ESM)
 */

export * from './objects';
export * from './scripts';
export * from './rooms';
export * from './stats';
export * from './satanic_zone';
export * from './item_type';
'''
    (ts_dir / "index.ts").write_text(index_content, encoding="utf-8")

    # 2. objects.ts
    lines = [
        "export enum GameObject {",
    ]
    used_names = set()
    for obj in data["objects"]:
        name = obj["name"]
        idx = obj["index"]
        clean = sanitize_identifier(name)
        if clean in used_names:
            clean = f"{clean}_{idx}"
        used_names.add(clean)
        lines.append(f"  {clean} = {idx},")
    lines.append("}\n")

    ts_parents = {
        o["index"]: o["parent_index"]
        for o in data["objects"]
        if o["parent_index"] != GameDataExtractor.OBJECT_NO_PARENT
    }
    ts_masks = {
        o["index"]: o["mask_index"]
        for o in data["objects"]
        if o["mask_index"] != GameDataExtractor.OBJECT_NO_MASK
    }
    lines.append(f"export const NO_PARENT = {GameDataExtractor.OBJECT_NO_PARENT};")
    lines.append(f"export const NO_MASK = {GameDataExtractor.OBJECT_NO_MASK};")
    lines.append("")
    lines.append("/** Child object index -> parent object index. Root objects are absent. */")
    lines.append(
        "export const OBJECT_PARENT_INDEX: Readonly<Record<number, number>> = "
        + json.dumps(ts_parents)
        + ";"
    )
    lines.append("/** Object index -> collision mask *sprite* index. Absent means the")
    lines.append(" *  object collides using its own sprite index. */")
    lines.append(
        "export const OBJECT_MASK_SPRITE_INDEX: Readonly<Record<number, number>> = "
        + json.dumps(ts_masks)
        + ";"
    )
    lines.append(OBJECT_HIERARCHY_TS)
    (ts_dir / "objects.ts").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 3. scripts.ts
    lines = [
        "export const GameScripts = {",
    ]
    used_script_names = set()
    for sc in data["scripts"]:
        name = sc["name"]
        idx = sc["index"]
        clean = sanitize_identifier(name)
        if clean in used_script_names:
            clean = f"{clean}_{idx}"
        used_script_names.add(clean)
        lines.append(f"  {clean}: '{name}',")
    lines.append("} as const;\n")
    (ts_dir / "scripts.ts").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 4. rooms.ts
    lines = [
        "export enum GameRoom {",
    ]
    used_room_names = set()
    for rm in data["rooms"]:
        name = rm["name"]
        idx = rm["index"]
        clean = sanitize_identifier(name)
        if clean in used_room_names:
            clean = f"{clean}_{idx}"
        used_room_names.add(clean)
        lines.append(f"  {clean} = {idx},")
    lines.append("}\n")
    (ts_dir / "rooms.ts").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 5. stats.ts
    stats_ts = '''export const BUFF_ANGELIC_CHANCE = 332;

export enum StatId {
  STRENGTH = 0,
  DEFENSE = 1,
  SWIFTNESS = 2,
  STAMINA = 3,
  ENERGY = 4,
  PHYSICAL_DAMAGE = 5,
  FIRE_DAMAGE = 6,
  ICE_DAMAGE = 7,
  LIGHTNING_DAMAGE = 8,
  POISON_DAMAGE = 9,
  MAGIC_DAMAGE = 10,
  WIND_DAMAGE = 11,
  HOLY_DAMAGE = 12,
  SHADOW_DAMAGE = 13,
  CHAOS_DAMAGE = 14,
  ATTACK_SPEED = 15,
  CAST_RATE = 16,
  CRITICAL_RATE = 17,
  CRITICAL_DAMAGE = 18,
  MOVEMENT_SPEED = 19,
  MAGIC_FIND = 20,
  EXTRA_GOLD = 21,
  EXP_GAIN = 22,
  ALL_STATS = 23,
  MAX_HEALTH = 24,
  MAX_MANA = 25,
  HEALTH_REGEN = 26,
  MANA_REGEN = 27,
  MANA_PER_HIT = 28,
  HEALTH_PER_HIT = 29,
  LIFE_PER_KILL = 30,
  MANA_PER_KILL = 31,
  LIFE_LEECH = 32,
  MANA_LEECH = 33,
  COOLDOWN_REDUCTION = 34,
  DODGE_CHANCE = 35,
  BLOCK_CHANCE = 36,
  DAMAGE_REDUCTION = 37,
  DAMAGE_TO_BOSSES = 38,
  DAMAGE_TO_ELITES = 39,
  ARMOR_PENETRATION = 40,
  MAGIC_PENETRATION = 41,
  JEWELCRAFTING_LEVEL = 157,
}
'''
    (ts_dir / "stats.ts").write_text(stats_ts, encoding="utf-8")

    # 6. package.json
    pkg_json = {
        "name": "@hero-siege/sdk",
        "version": "1.0.0",
        "description": "Hero Siege Game SDK TypeScript Bindings",
        "main": "dist/index.js",
        "types": "dist/index.d.ts",
        "type": "module"
    }
    (output_dir / "ts" / "package.json").write_text(json.dumps(pkg_json, indent=2) + "\n", encoding="utf-8")


def export_json_data(data: Dict[str, Any], output_dir: Path) -> None:
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    (data_dir / "manifest.json").write_text(json.dumps(data["metadata"], indent=2) + "\n", encoding="utf-8")
    (data_dir / "objects.json").write_text(json.dumps(data["objects"], indent=2) + "\n", encoding="utf-8")
    (data_dir / "scripts.json").write_text(json.dumps(data["scripts"], indent=2) + "\n", encoding="utf-8")
    (data_dir / "sprites.json").write_text(json.dumps(data["sprites"], indent=2) + "\n", encoding="utf-8")
    (data_dir / "rooms.json").write_text(json.dumps(data["rooms"], indent=2) + "\n", encoding="utf-8")
    (data_dir / "sounds.json").write_text(json.dumps(data["sounds"], indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract game symbols and build SDK bindings.")
    parser.add_argument(
        "--game-bin",
        type=Path,
        default=Path(r"C:\Program Files (x86)\Steam\steamapps\common\HeroSiege\bin"),
        help="Path to Hero Siege game bin directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "hs-game-sdk",
        help="Output directory for generated SDK and data",
    )
    args = parser.parse_args()

    print(f"Extracting game symbols from: {args.game_bin}")
    extractor = GameDataExtractor(args.game_bin)
    data = extractor.extract_all()

    print(f"Extracted:")
    print(f"  - Objects: {len(data['objects'])}")
    print(f"  - Scripts: {len(data['scripts'])}")
    print(f"  - Sprites: {len(data['sprites'])}")
    print(f"  - Rooms: {len(data['rooms'])}")
    print(f"  - Sounds: {len(data['sounds'])}")

    out_dir = args.output_dir
    print(f"Generating SDK at: {out_dir}")
    export_json_data(data, out_dir)
    generate_python_bindings(data, out_dir)
    generate_cpp_bindings(data, out_dir)
    generate_ts_bindings(data, out_dir)

    print("SDK successfully generated!")


if __name__ == "__main__":
    main()
