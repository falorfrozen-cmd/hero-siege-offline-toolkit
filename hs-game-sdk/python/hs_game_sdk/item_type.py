"""Item class: the value an item instance carries in its ``itemType`` field.

Hand-written, not extracted - ``tools/extract_and_generate_sdk.py`` does not write
this file. The C++ (``HeroSiege::Items::ItemType`` / ``kItemTypes`` in
``item_type.hpp``) and TypeScript (``ItemType`` / ``ITEM_TYPES`` in
``item_type.ts``) bindings declare the same members, and
``tests/test_item_type_parity.py`` fails if any of them drifts by a name or a value.

Source: ``HSCraftSim/RESEARCH.md`` section 2, the "Item types (= catalog ``cls``)"
list, with 11..15 cross-checked there against Item Editor catalog rows. ``RELIC``
agrees with ``RELIC_RARITY_TIER`` in ``player.py``. The integers 9 and 17 appear in
no source and are deliberately absent.

This describes the item *instance's* ``itemType`` field. It does not describe the
definition struct's ``c`` field; do not match it against ``c``.
"""

from enum import IntEnum


class ItemType(IntEnum):
    HELMET = 0
    BODY = 1
    BOOTS = 2
    WEAPON = 3
    GLOVES = 4
    AMULET = 5
    SHIELD = 6
    RING = 7
    BELT = 8
    CHARM = 10
    CONSUMABLE = 11
    KEY = 12
    TAROT = 13
    MATERIAL = 14
    SOCKETABLE = 15  # runes, gems and jewels
    RELIC = 16
    POTION = 18
    OTHER = 19
