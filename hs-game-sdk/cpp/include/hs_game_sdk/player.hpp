#pragma once
#include <cmath>
#include <vector>
#include <unordered_set>
#include <unordered_map>
#include <string>
#include <string_view>
#include "yytk_helpers.hpp"
#include "objects.hpp"
#include "scripts.hpp"
#include "item_type.hpp"

namespace HeroSiege::Player {

#ifdef HS_SDK_HAS_YYTK

using ::YYTK::YYTKInterface;
using ::YYTK::RValue;
using ::YYTK::CInstance;

/**
 * Resolves the primary local player CInstance or RValue.
 */
inline bool ResolveLocalPlayer(YYTKInterface* yytk, RValue& outPlayer) {
    if (!yytk) return false;
    try {
        CInstance* globalInst = nullptr;
        yytk->GetGlobalInstance(&globalInst);
        if (globalInst) {
            for (const char* varName : { "player", "local_player", "oPlayer", "player_obj" }) {
                if (YYTK::GlobalHasVariable(yytk, varName)) {
                    RValue cand = YYTK::GetGlobalVariable(yytk, varName);
                    if (cand.m_Kind == ::YYTK::VALUE_OBJECT && cand.m_Object) {
                        outPlayer = cand;
                        return true;
                    }
                }
            }
        }
    } catch (...) {}
    return false;
}

// ---------------------------------------------------------------------------
// The relic-identification contract.
//
// These constants are the shared contract between this header and
// scan_relic_levels() in the Python SDK, which must accept exactly the same
// item layouts and container kinds. REPORTED 2026-09-12 by origin's second
// review of PR #3: C++ recognised `cls` and read numeric arrays out of
// `relic_levels` while Python did neither, so the two bindings disagreed about
// which relics a player owns.
//
// They are deliberately enumerable rather than inline literals, so
// tests/cpp/test_sdk_player_hooks.cpp can print them and
// tests/test_cpp_sdk.py can assert the Python tuples match field for field. A
// future edit to one side now fails a test instead of silently diverging.
// ---------------------------------------------------------------------------

/// Rarity tier that identifies an item as a relic (docs/RUNTIME_DATA_MODELS.md).
inline constexpr int kRelicRarityTier = 16;
/// Season 10 relic ids run 0..155; this is the exclusive upper bound used to
/// reject ids that cannot be relics.
inline constexpr int kRelicIdLimit = 160;
/// A relic at this level or above is maxed.
inline constexpr int kMaxedRelicLevel = 10;
/// Recursion budget, shared with the Python scanner.
inline constexpr int kMaxScanDepth = 5;
/// Longest array read from a single container, to bound a pathological table.
inline constexpr int kMaxScannedArrayLength = 512;

/// Fields holding the item/relic id.
inline constexpr std::string_view kRelicIdFields[] = { "b", "relicId" };
/// Fields whose value being kRelicRarityTier identifies a relic.
inline constexpr std::string_view kRelicTierFields[] = { "c", "cls", "itemType" };
/// Fields holding a relic's upgrade level. The highest present value wins.
inline constexpr std::string_view kRelicLevelFields[] = { "o", "level", "relicLevel" };
/// Relic-specific field whose mere presence identifies a relic.
inline constexpr std::string_view kRelicOnlyField = "relicLevel";

/// Item class (ItemType) of a relic. A relic's definition struct carries no
/// class at all and `c` 0 (read from a character save, 2026-09-27; #93), so on
/// the game's own items the class is only on the item INSTANCE.
inline constexpr int kRelicItemClass = static_cast<int>(HeroSiege::Items::ItemType::Relic);
/// Field of an item instance holding its class. A struct carrying it is an
/// item instance: identified by the class, its id and level read from the
/// definition below.
inline constexpr std::string_view kItemInstanceTypeField = "itemType";
/// Field of an item instance holding its definition (`b` id, `o` level, ...).
inline constexpr std::string_view kItemInstanceDefinitionField = "itemDefinitionStruct";
/// The equipped relic slots of global.equippedItems[mplr][0], inclusive
/// (EquipmentSlot RELIC_0..RELIC_4 in the Python binding).
inline constexpr int kFirstRelicSlot = 10;
inline constexpr int kLastRelicSlot = 14;
/// global.mplr, the local player's row in global.equippedItems, runs 0..this.
inline constexpr int kMaxLocalPlayerIndex = 4;

/// Player variables scanned as general containers: item structs only.
/// `equipped_items` is the save file's name for the equipped items; C++ never
/// sees a save, but the list is shared with the Python scanner, which does.
inline constexpr std::string_view kGeneralContainerFields[] = {
    "equippedItems", "equipped_items", "inventory", "bags",
};
/// Player variables where a numeric array really is `relic id -> level`.
inline constexpr std::string_view kRelicContainerFields[] = {
    "inventory_relic_tab", "pRelics", "relic_array", "relic_inventory",
    "relic_levels", "relic_tab", "relicPage", "relics", "relics_collected",
};

/**
 * What a container is, which decides how a bare number inside it is read.
 *
 * A numeric array is only a relic-level table in a container that is
 * specifically about relics. In a general container - equipped items, bags -
 * numbers are anything at all, and reading them as `relic id -> level` invents
 * relics out of unrelated data.
 */
enum class ContainerKind {
    General,
    RelicTable,
};

/**
 * Populates outRelicLevels with relic ids (field `b`) and their highest level.
 *
 * An item counts as a relic only on POSITIVE identification: rarity tier 16 via
 * `c` / `cls` / `itemType`, or the relic-specific `relicLevel` field. A
 * level-shaped field is not evidence on its own.
 *
 * REPORTED 2026-09-12 by origin's review of PR #3, and reproduced: accepting
 * `isRelic || level > 0` classified the ordinary item `{b:15, c:8, level:100}`
 * as maxed relic 15. ForgePact's RelicFilterMod calls GetMaxedRelicIds
 * directly, so a false positive there suppresses an unrelated relic drop.
 * Two measured facts make "has a level" unusable as a relic test:
 *
 *   - Ordinary items carry level-shaped fields of their own. `p` is a star
 *     upgrade count and stacks carry `amount`/`count`/`qty`, so the old field
 *     list both invented relics and inflated levels past the maxed threshold.
 *     Only the three documented relic level fields are read now.
 *   - The previous `g` in 10..14 signal had no measured basis in
 *     docs/RUNTIME_DATA_MODELS.md, and could only add false positives, so it
 *     is gone. Equipped relics are identified by their item class instead
 *     (below), and ScanEquippedRelicSlots reaches them by slot position.
 *
 * This now matches scan_relic_levels() in the Python SDK, which is the
 * behaviour the review benchmarked against.
 *
 * An item INSTANCE - a struct carrying kItemInstanceTypeField - is how the game
 * holds a finished item, and the only place its class lives: its definition
 * has no class field and `c` 0 on a relic (#93, 2026-09-27). The instance is
 * identified by `itemType == kRelicItemClass`, and its definition is scanned
 * with that identification carried in `identified`, so `b`/`o` are read from
 * the definition. A definition is never identified by its own level.
 */
inline void ScanContainerForRelics(
    YYTKInterface* yytk,
    const RValue& container,
    std::unordered_map<int, int>& outRelicLevels,
    ContainerKind kind = ContainerKind::General,
    int depth = 0,
    bool identified = false
) {
    if (!yytk || depth > kMaxScanDepth) return;
    try {
        if (container.m_Kind == ::YYTK::VALUE_OBJECT && container.m_Object) {
            // 1. If this is a slot container wrapping an inner 'data' struct:
            if (YYTK::StructHasVariable(yytk, container, "data")) {
                RValue innerData = YYTK::GetStructVariable(yytk, container, "data");
                ScanContainerForRelics(yytk, innerData, outRelicLevels, kind, depth + 1);
            }

            // 1b. An item instance: its class identifies it, its definition
            //     holds the id and level.
            if (YYTK::StructHasVariable(yytk, container, kItemInstanceTypeField)
                && YYTK::StructHasVariable(yytk, container, kItemInstanceDefinitionField)) {
                const RValue itemClass = YYTK::GetStructVariable(yytk, container, kItemInstanceTypeField);
                const bool relicInstance =
                    (itemClass.m_Kind == ::YYTK::VALUE_REAL || itemClass.m_Kind == ::YYTK::VALUE_INT32
                     || itemClass.m_Kind == ::YYTK::VALUE_INT64)
                    && static_cast<int>(itemClass.ToDouble()) == kRelicItemClass;
                RValue definition = YYTK::GetStructVariable(yytk, container, kItemInstanceDefinitionField);
                ScanContainerForRelics(yytk, definition, outRelicLevels, kind, depth + 1, relicInstance);
            }

            // 2. Direct item inspection
            int b = -1;
            int level = 0;
            bool isRelic = identified;

            for (const std::string_view idField : kRelicIdFields) {
                if (YYTK::StructHasVariable(yytk, container, idField)) {
                    b = static_cast<int>(YYTK::GetStructVariable(yytk, container, idField).ToDouble());
                    break;
                }
            }

            // Positive identification: the rarity tier says relic, ...
            for (const std::string_view tierField : kRelicTierFields) {
                if (YYTK::StructHasVariable(yytk, container, tierField)) {
                    const int tier = static_cast<int>(YYTK::GetStructVariable(yytk, container, tierField).ToDouble());
                    if (tier == kRelicRarityTier) {
                        isRelic = true;
                        break;
                    }
                }
            }
            // ... or the item carries the relic-specific level field.
            if (YYTK::StructHasVariable(yytk, container, kRelicOnlyField)) {
                isRelic = true;
            }

            // Level comes only from the documented relic level fields, highest wins.
            for (const std::string_view lField : kRelicLevelFields) {
                if (YYTK::StructHasVariable(yytk, container, lField)) {
                    const int val = static_cast<int>(YYTK::GetStructVariable(yytk, container, lField).ToDouble());
                    if (val > level) level = val;
                }
            }

            if (isRelic && b >= 0 && b < kRelicIdLimit) {
                if (level <= 0) level = 1;
                if (outRelicLevels.find(b) == outRelicLevels.end() || level > outRelicLevels[b]) {
                    outRelicLevels[b] = level;
                }
            }
        } else if (container.m_Kind == ::YYTK::VALUE_ARRAY) {
            int len = YYTK::GetArrayLength(yytk, container);
            // Cap array length to avoid pathological tables
            if (len > kMaxScannedArrayLength) len = kMaxScannedArrayLength;
            for (int i = 0; i < len; ++i) {
                RValue child = YYTK::GetArrayElement(yytk, container, i);
                if (child.m_Kind == ::YYTK::VALUE_REAL || child.m_Kind == ::YYTK::VALUE_INT32 || child.m_Kind == ::YYTK::VALUE_INT64) {
                    // A bare number is a relic level indexed by relic id only in
                    // a container that is specifically a relic table.
                    if (kind == ContainerKind::RelicTable && i < kRelicIdLimit) {
                        const int numVal = static_cast<int>(child.ToDouble());
                        if (numVal > 0 && (outRelicLevels.find(i) == outRelicLevels.end() || numVal > outRelicLevels[i])) {
                            outRelicLevels[i] = numVal;
                        }
                    }
                } else if (child.m_Kind == ::YYTK::VALUE_OBJECT || child.m_Kind == ::YYTK::VALUE_ARRAY) {
                    ScanContainerForRelics(yytk, child, outRelicLevels, kind, depth + 1);
                }
            }
        }
    } catch (...) {}
}

/**
 * Is this RValue a usable handle to a live instance?
 *
 * Two kinds qualify. VALUE_OBJECT is the struct-shaped instance. VALUE_REF is
 * an instance reference, and it is what this runner actually produces for the
 * local player: `instance_find(Player_obj)` returns kind 15, measured
 * 2026-09-10 (ForgePact ModuleMain.cpp, HhResolveLocalPlayer).
 *
 * Both are accepted by every accessor used below - `variable_instance_exists`
 * and `variable_instance_get` take a reference straight through - so the kind
 * must not decide whether a scan runs at all.
 *
 * REPORTED 2026-09-14: "Remove owned relics from drop pool" armed, installed
 * its DropRelic hook, logged ON, and then filtered nothing for anyone. The
 * player handed to GetOwnedRelicLevels was a VALUE_REF, the old
 * `!= VALUE_OBJECT` gate returned an empty map before reading a container,
 * and an empty maxed set means the caller suppresses nothing. This is the
 * third time a VALUE_REF instance has silently disabled a feature in this
 * codebase (orbpickup and the relic filter's own arming step were the first
 * two), which is why it is a named predicate rather than an inline check.
 */
inline bool IsInstanceHandle(const RValue& value) {
    return value.m_Kind == ::YYTK::VALUE_OBJECT || value.m_Kind == ::YYTK::VALUE_REF;
}

namespace Detail {

/// `array[index]`, only when `array` is an array that long. An out-of-range
/// array_get is a runner error, so the length is checked first.
inline bool ArrayAt(YYTKInterface* yytk, const RValue& array, int index, RValue& out) {
    if (array.m_Kind != ::YYTK::VALUE_ARRAY || index < 0) return false;
    if (index >= YYTK::GetArrayLength(yytk, array)) return false;
    out = YYTK::GetArrayElement(yytk, array, index);
    return true;
}

} // namespace Detail

/**
 * Adds the relics worn in the equipped relic slots (#93).
 *
 * The game keeps the local character's equipped items as FINGERPRINT STRINGS in
 * `global.equippedItems[global.mplr][0][slot]`, not as item structs, so no
 * container the player instance exposes shows them. Each fingerprint is
 * resolved by the game's own scripts, called by name with the global instance
 * as self and other: `GetOnlinePlayerItemOwner(mplr)`, then
 * `GetItemFromFingerprint(fingerprint, owner)`, which returns the item instance
 * that ScanContainerForRelics identifies by its class. This is the route
 * ForgePact's Miner's Helmet reads slot 0 through, confirmed live 2026-09-23;
 * that it reaches the relic slots 10-14 is UNVERIFIED until measured live.
 *
 * Nothing is guessed: an `mplr` that is not a whole number in
 * 0..kMaxLocalPlayerIndex reads nothing, and a slot that is not a non-empty
 * string, or whose fingerprint does not resolve to a struct, is skipped. Only
 * strings ever reach the game's resolver.
 */
inline void ScanEquippedRelicSlots(YYTKInterface* yytk, std::unordered_map<int, int>& outRelicLevels) {
    if (!yytk) return;
    try {
        const RValue mplr = YYTK::GetGlobalVariable(yytk, "mplr");
        if (mplr.m_Kind != ::YYTK::VALUE_REAL && mplr.m_Kind != ::YYTK::VALUE_INT32
            && mplr.m_Kind != ::YYTK::VALUE_INT64) return;
        const double index = mplr.ToDouble();
        if (!std::isfinite(index) || std::floor(index) != index
            || index < 0 || index > kMaxLocalPlayerIndex) return;

        RValue ownerRows, slots;
        const RValue all = YYTK::GetGlobalVariable(yytk, "equippedItems");
        if (!Detail::ArrayAt(yytk, all, static_cast<int>(index), ownerRows)
            || !Detail::ArrayAt(yytk, ownerRows, 0, slots)) return;

        CInstance* global = nullptr;
        bool haveOwner = false;
        RValue owner;
        for (int slot = kFirstRelicSlot; slot <= kLastRelicSlot; ++slot) {
            RValue fingerprint;
            if (!Detail::ArrayAt(yytk, slots, slot, fingerprint)) break;
            if (fingerprint.m_Kind != ::YYTK::VALUE_STRING || fingerprint.ToString().empty()) continue;

            // The owner is resolved once, and only when a slot needs it.
            if (!haveOwner) {
                yytk->GetGlobalInstance(&global);
                if (!global) return;
                if (!::Aurie::AurieSuccess(yytk->CallGameScriptEx(
                        owner, HeroSiege::Scripts::gml_Script_GetOnlinePlayerItemOwner,
                        global, global, { RValue(index) }))) return;
                haveOwner = true;
            }

            RValue item;
            if (!::Aurie::AurieSuccess(yytk->CallGameScriptEx(
                    item, HeroSiege::Scripts::gml_Script_GetItemFromFingerprint,
                    global, global, { fingerprint, owner }))) continue;
            if (item.m_Kind != ::YYTK::VALUE_OBJECT || !item.m_Object) continue;
            ScanContainerForRelics(yytk, item, outRelicLevels, ContainerKind::General, 0);
        }
    } catch (...) {}
}

/**
 * Returns a map of all owned relic IDs and their highest recorded level across equipped slots & inventory.
 */
inline std::unordered_map<int, int> GetOwnedRelicLevels(YYTKInterface* yytk, const RValue& player) {
    std::unordered_map<int, int> relicMap;
    if (!yytk || !IsInstanceHandle(player)) return relicMap;

    try {
        // 1. General containers: item structs only, each positively identified.
        //    A bare number in here is not a relic level.
        for (const std::string_view varName : kGeneralContainerFields) {
            if (YYTK::InstanceHasVariable(yytk, player, varName)) {
                RValue val = YYTK::GetInstanceVariable(yytk, player, varName);
                ScanContainerForRelics(yytk, val, relicMap, ContainerKind::General, 0);
            }
        }

        // 2. Dedicated relic containers, where a numeric array really is
        //    `relic id -> level`.
        for (const std::string_view varName : kRelicContainerFields) {
            if (YYTK::InstanceHasVariable(yytk, player, varName)) {
                RValue val = YYTK::GetInstanceVariable(yytk, player, varName);
                ScanContainerForRelics(yytk, val, relicMap, ContainerKind::RelicTable, 0);
            }
        }

        // 3. The equipped relic slots, held by the game as fingerprints in a
        //    global rather than on the player instance.
        ScanEquippedRelicSlots(yytk, relicMap);
    } catch (...) {}

    return relicMap;
}

/**
 * Returns set of relic IDs that are at maximum level (>= kMaxedRelicLevel).
 */
inline std::unordered_set<int> GetMaxedRelicIds(YYTKInterface* yytk, const RValue& player) {
    std::unordered_set<int> maxed;
    auto relicMap = GetOwnedRelicLevels(yytk, player);
    for (const auto& [id, lvl] : relicMap) {
        if (lvl >= kMaxedRelicLevel) {
            maxed.insert(id);
        }
    }
    return maxed;
}

#endif

} // namespace HeroSiege::Player
