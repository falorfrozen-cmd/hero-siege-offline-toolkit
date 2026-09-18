/**
 * Item class: the value an item instance carries in its `itemType` field.
 *
 * Hand-written, not extracted - tools/extract_and_generate_sdk.py does not write
 * this file. The Python (`ItemType` in item_type.py) and C++
 * (`HeroSiege::Items::ItemType` / `kItemTypes` in item_type.hpp) bindings declare
 * the same members, and tests/test_item_type_parity.py fails if any of them
 * drifts by a name or a value.
 *
 * Source: HSCraftSim/RESEARCH.md section 2, the "Item types (= catalog cls)"
 * list, with 11..15 cross-checked there against Item Editor catalog rows. The
 * integers 9 and 17 appear in no source and are deliberately absent.
 *
 * This describes the item *instance's* `itemType` field. It does not describe
 * the definition struct's `c` field; do not match it against `c`.
 */
export enum ItemType {
  Helmet = 0,
  Body = 1,
  Boots = 2,
  Weapon = 3,
  Gloves = 4,
  Amulet = 5,
  Shield = 6,
  Ring = 7,
  Belt = 8,
  Charm = 10,
  Consumable = 11,
  Key = 12,
  Tarot = 13,
  Material = 14,
  Socketable = 15, // runes, gems and jewels
  Relic = 16,
  Potion = 18,
  Other = 19,
}

/** Every ItemType member once, in value order, with its name. */
export const ITEM_TYPES: ReadonlyArray<{ readonly name: string; readonly value: ItemType }> = [
  { name: 'Helmet', value: ItemType.Helmet },
  { name: 'Body', value: ItemType.Body },
  { name: 'Boots', value: ItemType.Boots },
  { name: 'Weapon', value: ItemType.Weapon },
  { name: 'Gloves', value: ItemType.Gloves },
  { name: 'Amulet', value: ItemType.Amulet },
  { name: 'Shield', value: ItemType.Shield },
  { name: 'Ring', value: ItemType.Ring },
  { name: 'Belt', value: ItemType.Belt },
  { name: 'Charm', value: ItemType.Charm },
  { name: 'Consumable', value: ItemType.Consumable },
  { name: 'Key', value: ItemType.Key },
  { name: 'Tarot', value: ItemType.Tarot },
  { name: 'Material', value: ItemType.Material },
  { name: 'Socketable', value: ItemType.Socketable },
  { name: 'Relic', value: ItemType.Relic },
  { name: 'Potion', value: ItemType.Potion },
  { name: 'Other', value: ItemType.Other },
];
