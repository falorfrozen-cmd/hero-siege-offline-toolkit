#pragma once
#include <cstdint>
#include <string_view>
#include <utility>

// ---------------------------------------------------------------------------
// Item class: the value an item instance carries in its `itemType` field.
//
// Hand-written, not extracted - tools/extract_and_generate_sdk.py does not
// write this file. Self-contained on purpose (standard headers only, no
// YYToolkit), so it can be included anywhere.
//
// Source: HSCraftSim/RESEARCH.md section 2, the "Item types (= catalog cls)"
// list, with 11..15 cross-checked there against Item Editor catalog rows.
// Relic agrees with Player::kRelicRarityTier. The integers 9 and 17 appear in
// no source and are deliberately absent.
//
// This describes the item *instance's* `itemType` field. It does not describe
// the definition struct's `c` field; do not match it against `c`.
//
// kItemTypes is deliberately enumerable, like the relic contract in
// player.hpp: tests/cpp/test_sdk_player_hooks.cpp prints it and
// tests/test_cpp_sdk.py asserts it equals the Python ItemType member for
// member; tests/test_item_type_parity.py checks the text of this header too.
// ---------------------------------------------------------------------------

namespace HeroSiege::Items {

enum class ItemType : int32_t {
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
    Socketable = 15,  // runes, gems and jewels
    Relic = 16,
    Potion = 18,
    Other = 19,
};

/// Every ItemType member once, in value order, with its name.
inline constexpr std::pair<std::string_view, ItemType> kItemTypes[] = {
    { "Helmet", ItemType::Helmet },
    { "Body", ItemType::Body },
    { "Boots", ItemType::Boots },
    { "Weapon", ItemType::Weapon },
    { "Gloves", ItemType::Gloves },
    { "Amulet", ItemType::Amulet },
    { "Shield", ItemType::Shield },
    { "Ring", ItemType::Ring },
    { "Belt", ItemType::Belt },
    { "Charm", ItemType::Charm },
    { "Consumable", ItemType::Consumable },
    { "Key", ItemType::Key },
    { "Tarot", ItemType::Tarot },
    { "Material", ItemType::Material },
    { "Socketable", ItemType::Socketable },
    { "Relic", ItemType::Relic },
    { "Potion", ItemType::Potion },
    { "Other", ItemType::Other },
};

} // namespace HeroSiege::Items
