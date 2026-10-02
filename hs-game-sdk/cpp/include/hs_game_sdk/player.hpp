#pragma once
#include <algorithm>
#include <cmath>
#include <utility>
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

// ---------------------------------------------------------------------------
// A relic lying on the ground (ForgePact#124).
//
// A dropped item is a Loot_Ground_obj instance. The ground item's constructor
// stores a fresh item instance in the ground instance's kGroundItemInstanceField
// variable, and that item instance carries the item class
// (kItemInstanceTypeField) and the definition (kItemInstanceDefinitionField,
// `b` the id) - the same two names an item instance carries anywhere else.
// Both readers seen (the companion's Step and the ground item's own
// Create-defined function) take the class through it; whether the ground
// instance also carries a top-level copy is not established, so it is never
// read. Static reading (2026-10-02), confirmed live by ForgePact#124's Live 1
// (2026-10-02, `petrelic census` ok=42): the itemInstance -> itemType /
// itemDefinitionStruct.b read held for every relic on screen.
//
// C++ only: a ground instance exists only in the running game's memory, and
// the Python binding reads saves.
// ---------------------------------------------------------------------------

/// Variable of a Loot_Ground_obj instance holding its item instance.
inline constexpr std::string_view kGroundItemInstanceField = "itemInstance";

/// Where a ReadGroundRelic call stopped. Every stage but Ok is a refusal.
enum class GroundRelicStage {
    NotRun,        ///< never read: the struct has not been through a call
    NoHandle,      ///< no interface, the value is not an instance handle, or reading it threw
    NoItemInstance, ///< no kGroundItemInstanceField, or one that holds no struct or reference
    NoClass,       ///< an item instance with no numeric kItemInstanceTypeField
    NotRelic,      ///< the class is read and is not kRelicItemClass
    NoDefinition,  ///< a relic class, but no definition struct
    NoId,          ///< the definition holds no id in 0 .. kRelicIdLimit - 1
    Ok,            ///< a relic, its id in relicId
};

/// The stage's name for a log line: `not-run`, `no-handle`, `no-item-instance`,
/// `no-class`, `not-relic`, `no-definition`, `no-id`, `ok`.
inline const char* GroundRelicStageName(GroundRelicStage stage) {
    switch (stage) {
    case GroundRelicStage::NotRun: return "not-run";
    case GroundRelicStage::NoHandle: return "no-handle";
    case GroundRelicStage::NoItemInstance: return "no-item-instance";
    case GroundRelicStage::NoClass: return "no-class";
    case GroundRelicStage::NotRelic: return "not-relic";
    case GroundRelicStage::NoDefinition: return "no-definition";
    case GroundRelicStage::NoId: return "no-id";
    case GroundRelicStage::Ok: return "ok";
    }
    return "unknown";
}

/// What one ReadGroundRelic call read. `itemClass` and `relicId` are -1 until
/// read; `relicId` is set only on Ok.
struct GroundRelicRead {
    GroundRelicStage stage = GroundRelicStage::NotRun;
    int itemClass = -1;
    int relicId = -1;
};

/**
 * Is this ground item a relic, and which one?
 *
 * Positive identification only: the class of the ground instance's item
 * instance (kGroundItemInstanceField) must read kRelicItemClass, and the id
 * comes from that item instance's definition's kRelicIdFields. An id-shaped or
 * level-shaped field - `relicLevel` included - is never evidence on its own,
 * and neither is a definition without a class: a relic's definition carries
 * `c` 0 and no class (#93), so the item instance is the only place the class
 * lives.
 *
 * Both kinds are accepted at every level (IsInstanceHandle): the ground
 * instance is read through `variable_instance_*`, which takes a reference
 * straight through, and the item instance and its definition through
 * `variable_struct_*` as a VALUE_OBJECT or `variable_instance_*` as a
 * VALUE_REF, the same split as the relic-tab profile read below. The kind
 * never decides whether the read runs.
 *
 * Returns true only on GroundRelicStage::Ok. `out` is reset first, so a
 * refusal never leaves an earlier read's id behind.
 */
inline bool ReadGroundRelic(YYTKInterface* yytk, const RValue& instance, GroundRelicRead& out) {
    out = GroundRelicRead{};
    const auto stop = [&out](GroundRelicStage stage) {
        out.stage = stage;
        return stage == GroundRelicStage::Ok;
    };
    const auto isNumber = [](const RValue& value) {
        return value.m_Kind == ::YYTK::VALUE_REAL || value.m_Kind == ::YYTK::VALUE_INT32
            || value.m_Kind == ::YYTK::VALUE_INT64;
    };
    // A field of a struct-like value: `variable_struct_*` for a VALUE_OBJECT,
    // `variable_instance_*` for the VALUE_REF this runner can hand back
    // instead. Anything else holds nothing.
    const auto field = [yytk](const RValue& owner, std::string_view name, RValue& value) {
        if (owner.m_Kind == ::YYTK::VALUE_OBJECT) {
            if (!YYTK::StructHasVariable(yytk, owner, name)) return false;
            value = YYTK::GetStructVariable(yytk, owner, name);
            return true;
        }
        if (owner.m_Kind == ::YYTK::VALUE_REF) {
            if (!YYTK::InstanceHasVariable(yytk, owner, name)) return false;
            value = YYTK::GetInstanceVariable(yytk, owner, name);
            return true;
        }
        return false;
    };
    if (!yytk || !IsInstanceHandle(instance)) return stop(GroundRelicStage::NoHandle);
    try {
        // The class is taken from the item instance only. A class-shaped
        // variable on the ground instance itself is never read: no reader
        // seen takes one from there, so a ground instance without an item
        // instance is refused here, whatever else it carries.
        if (!YYTK::InstanceHasVariable(yytk, instance, kGroundItemInstanceField)) {
            return stop(GroundRelicStage::NoItemInstance);
        }
        const RValue item = YYTK::GetInstanceVariable(yytk, instance, kGroundItemInstanceField);
        if (!IsInstanceHandle(item) || (item.m_Kind == ::YYTK::VALUE_OBJECT && !item.m_Object)) {
            return stop(GroundRelicStage::NoItemInstance);
        }
        RValue itemClass;
        if (!field(item, kItemInstanceTypeField, itemClass)) return stop(GroundRelicStage::NoClass);
        if (!isNumber(itemClass) || !std::isfinite(itemClass.ToDouble())) return stop(GroundRelicStage::NoClass);
        out.itemClass = static_cast<int>(itemClass.ToDouble());
        if (out.itemClass != kRelicItemClass) return stop(GroundRelicStage::NotRelic);

        RValue definition;
        if (!field(item, kItemInstanceDefinitionField, definition) || !IsInstanceHandle(definition)
            || (definition.m_Kind == ::YYTK::VALUE_OBJECT && !definition.m_Object)) {
            return stop(GroundRelicStage::NoDefinition);
        }

        for (const std::string_view idField : kRelicIdFields) {
            RValue id;
            if (!field(definition, idField, id)) continue;
            if (!isNumber(id)) break;
            const double value = id.ToDouble();
            if (!std::isfinite(value) || std::floor(value) != value
                || value < 0 || value >= kRelicIdLimit) break;
            out.relicId = static_cast<int>(value);
            return stop(GroundRelicStage::Ok);
        }
        return stop(GroundRelicStage::NoId);
    } catch (...) {
        out.itemClass = -1;
        return stop(GroundRelicStage::NoHandle);
    }
}

/// One line naming what a ground read did, for a log: e.g. `stage=ok class=16
/// id=42`, or `stage=not-relic class=4 id=-1`.
inline std::string FormatGroundRelicRead(const GroundRelicRead& r) {
    return std::string("stage=") + GroundRelicStageName(r.stage)
        + " class=" + std::to_string(r.itemClass)
        + " id=" + std::to_string(r.relicId);
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

/// A filled equipped slot that is not a relic slot, resolved as the scan's
/// same-session positive control: the helmet slot, which ForgePact's Miner's
/// Helmet has read through the same route live (2026-09-23).
inline constexpr int kEquippedControlSlot = 0;

/**
 * What one ScanEquippedRelicSlots call did, stage by stage.
 *
 * The route has many ways to read nothing - an `mplr` out of range, a slots
 * array that is too short, a resolver the runner refuses, an item whose class
 * is not a relic - and a set of maxed ids reduces all of them to the same
 * empty answer. This report keeps them apart, so a live read of "found 0" says
 * which stage it stopped at. REPORTED 2026-09-27 by the instrument-blindness
 * review of #93, before the route's first live measurement.
 *
 * C++ only: the Python binding reads saves, where equipped items are item
 * structs keyed by fingerprint and no resolver is called.
 */
struct EquippedSlotScanReport {
    /// A single scanned relic slot's relic.
    struct SlotRelic {
        int slot;
        int id;
        int level;
    };

    /// The stage that ended the scan early (`yytk`, `mplr`, `equippedItems`,
    /// `slots`, `slots-short`, `global`, `owner`, `exception`), or nullptr when
    /// every relic slot was read. `not-run` until the scan starts, so a report
    /// the scan never reached (an unusable player handle, an exception in an
    /// earlier container) cannot read as a complete one.
    const char* stopped = "not-run";
    /// `global.mplr` as read, -1 when it is not a whole number in range.
    int mplr = -1;
    /// RValue kind of `global.mplr` and `global.equippedItems`, -1 unread.
    int mplrKind = -1;
    int equippedItemsKind = -1;
    /// Length of `equippedItems[mplr][0]`, -1 unread.
    int slotsLength = -1;
    /// Relic slots present in that array, and those holding a fingerprint.
    int slotsInRange = 0;
    int strings = 0;
    /// Whether GetOnlinePlayerItemOwner returned success.
    bool ownerResolved = false;
    /// GetItemFromFingerprint calls the runner refused, and those it ran.
    int resolverRefused = 0;
    int itemsResolved = 0;
    /// Of the calls it ran: results that were not a struct, structs without a
    /// numeric `itemType`, and structs by class (relic, anything else).
    int nonStructResults = 0;
    int noClassResults = 0;
    int relicInstances = 0;
    int otherClassInstances = 0;
    /// Every relic the relic slots yielded, in slot order, at any level.
    std::vector<SlotRelic> relics;

    /// The positive control on kEquippedControlSlot: `not-run`, `no-slot`,
    /// `empty`, `global`, `owner`, `refused`, `non-struct`, `no-class` or
    /// `resolved`. `controlItemType` is its class when `resolved`, else -1.
    const char* controlStatus = "not-run";
    int controlItemType = -1;
};

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
 * that it reaches the relic slots 10-14 was measured live on 2026-09-27: all
 * five resolved to relic instances whose ids and levels matched the save.
 *
 * Nothing is guessed: an `mplr` that is not a whole number in
 * 0..kMaxLocalPlayerIndex reads nothing, and a slot that is not a non-empty
 * string, or whose fingerprint does not resolve to a struct, is skipped. Only
 * strings ever reach the game's resolver.
 *
 * With `report`, every stage is counted there (EquippedSlotScanReport), and
 * kEquippedControlSlot is also resolved, once, as a positive control for the
 * resolver in the same session; its item is never scanned for relics. Without
 * one, the scan makes no call beyond the relic slots'.
 */
inline void ScanEquippedRelicSlots(
    YYTKInterface* yytk,
    std::unordered_map<int, int>& outRelicLevels,
    EquippedSlotScanReport* report = nullptr
) {
    const auto stop = [report](const char* stage) {
        if (report) report->stopped = stage;
    };
    if (!yytk) return stop("yytk");
    stop(nullptr);
    try {
        const RValue mplr = YYTK::GetGlobalVariable(yytk, "mplr");
        if (report) report->mplrKind = static_cast<int>(mplr.m_Kind);
        if (mplr.m_Kind != ::YYTK::VALUE_REAL && mplr.m_Kind != ::YYTK::VALUE_INT32
            && mplr.m_Kind != ::YYTK::VALUE_INT64) return stop("mplr");
        const double index = mplr.ToDouble();
        if (!std::isfinite(index) || std::floor(index) != index
            || index < 0 || index > kMaxLocalPlayerIndex) return stop("mplr");
        if (report) report->mplr = static_cast<int>(index);

        RValue ownerRows, slots;
        const RValue all = YYTK::GetGlobalVariable(yytk, "equippedItems");
        if (report) report->equippedItemsKind = static_cast<int>(all.m_Kind);
        if (!Detail::ArrayAt(yytk, all, static_cast<int>(index), ownerRows)
            || !Detail::ArrayAt(yytk, ownerRows, 0, slots)) return stop("equippedItems");
        if (slots.m_Kind != ::YYTK::VALUE_ARRAY) return stop("slots");
        if (report) report->slotsLength = YYTK::GetArrayLength(yytk, slots);

        CInstance* global = nullptr;
        bool haveOwner = false;
        RValue owner;
        // The owner is resolved once, and only when a slot needs it. Returns
        // the stage that failed, or nullptr.
        const auto resolveOwner = [&]() -> const char* {
            if (haveOwner) return nullptr;
            yytk->GetGlobalInstance(&global);
            if (!global) return "global";
            if (!::Aurie::AurieSuccess(yytk->CallGameScriptEx(
                    owner, HeroSiege::Scripts::gml_Script_GetOnlinePlayerItemOwner,
                    global, global, { RValue(index) }))) return "owner";
            haveOwner = true;
            if (report) report->ownerResolved = true;
            return nullptr;
        };

        for (int slot = kFirstRelicSlot; slot <= kLastRelicSlot; ++slot) {
            RValue fingerprint;
            if (!Detail::ArrayAt(yytk, slots, slot, fingerprint)) {
                stop("slots-short");
                break;
            }
            if (report) ++report->slotsInRange;
            if (fingerprint.m_Kind != ::YYTK::VALUE_STRING || fingerprint.ToString().empty()) continue;
            if (report) ++report->strings;

            if (const char* failed = resolveOwner()) return stop(failed);

            RValue item;
            if (!::Aurie::AurieSuccess(yytk->CallGameScriptEx(
                    item, HeroSiege::Scripts::gml_Script_GetItemFromFingerprint,
                    global, global, { fingerprint, owner }))) {
                if (report) ++report->resolverRefused;
                continue;
            }
            if (report) ++report->itemsResolved;
            if (item.m_Kind != ::YYTK::VALUE_OBJECT || !item.m_Object) {
                if (report) ++report->nonStructResults;
                continue;
            }

            if (!report) {
                ScanContainerForRelics(yytk, item, outRelicLevels, ContainerKind::General, 0);
                continue;
            }

            // Counted by class, then scanned on its own so each relic found is
            // attributed to its slot before it joins the owned map.
            int itemClass = -1;
            if (YYTK::StructHasVariable(yytk, item, kItemInstanceTypeField)) {
                const RValue cls = YYTK::GetStructVariable(yytk, item, kItemInstanceTypeField);
                if (cls.m_Kind == ::YYTK::VALUE_REAL || cls.m_Kind == ::YYTK::VALUE_INT32
                    || cls.m_Kind == ::YYTK::VALUE_INT64) {
                    itemClass = static_cast<int>(cls.ToDouble());
                }
            }
            if (itemClass < 0) ++report->noClassResults;
            else if (itemClass == kRelicItemClass) ++report->relicInstances;
            else ++report->otherClassInstances;

            std::unordered_map<int, int> slotRelics;
            ScanContainerForRelics(yytk, item, slotRelics, ContainerKind::General, 0);
            for (const auto& [id, level] : slotRelics) {
                report->relics.push_back({ slot, id, level });
                const auto found = outRelicLevels.find(id);
                if (found == outRelicLevels.end() || level > found->second) outRelicLevels[id] = level;
            }
        }

        if (!report) return;

        // The positive control: one filled non-relic slot through the same
        // resolver, so "the resolver answers" is shown beside the relic slots.
        RValue control;
        if (!Detail::ArrayAt(yytk, slots, kEquippedControlSlot, control)) {
            report->controlStatus = "no-slot";
        } else if (control.m_Kind != ::YYTK::VALUE_STRING || control.ToString().empty()) {
            report->controlStatus = "empty";
        } else if (const char* failed = resolveOwner()) {
            report->controlStatus = failed;
        } else {
            RValue item;
            if (!::Aurie::AurieSuccess(yytk->CallGameScriptEx(
                    item, HeroSiege::Scripts::gml_Script_GetItemFromFingerprint,
                    global, global, { control, owner }))) {
                report->controlStatus = "refused";
            } else if (item.m_Kind != ::YYTK::VALUE_OBJECT || !item.m_Object) {
                report->controlStatus = "non-struct";
            } else {
                report->controlStatus = "no-class";
                if (YYTK::StructHasVariable(yytk, item, kItemInstanceTypeField)) {
                    const RValue cls = YYTK::GetStructVariable(yytk, item, kItemInstanceTypeField);
                    if (cls.m_Kind == ::YYTK::VALUE_REAL || cls.m_Kind == ::YYTK::VALUE_INT32
                        || cls.m_Kind == ::YYTK::VALUE_INT64) {
                        report->controlStatus = "resolved";
                        report->controlItemType = static_cast<int>(cls.ToDouble());
                    }
                }
            }
        }
    } catch (...) {
        stop("exception");
    }
}

/**
 * One line naming what an equipped-slot scan did, for a log: e.g.
 * `mplr=0 slots=15 inrange=5 strings=3 owner=ok resolved=3 refused=0
 * nonstruct=0 noclass=0 relic=2 otherclass=1 relics=10:135@10,11:15@8
 * control=resolved itemType=4 stopped=none`. A relic is `slot:id@level`.
 */
inline std::string FormatEquippedSlotScanReport(const EquippedSlotScanReport& r) {
    std::string out;
    out += "mplr=" + std::to_string(r.mplr);
    if (r.mplr < 0) out += "(kind " + std::to_string(r.mplrKind) + ")";
    out += " slots=" + std::to_string(r.slotsLength);
    if (r.slotsLength < 0) out += "(equippedItems kind " + std::to_string(r.equippedItemsKind) + ")";
    out += " inrange=" + std::to_string(r.slotsInRange);
    out += " strings=" + std::to_string(r.strings);
    out += std::string(" owner=") + (r.ownerResolved ? "ok" : "no");
    out += " resolved=" + std::to_string(r.itemsResolved);
    out += " refused=" + std::to_string(r.resolverRefused);
    out += " nonstruct=" + std::to_string(r.nonStructResults);
    out += " noclass=" + std::to_string(r.noClassResults);
    out += " relic=" + std::to_string(r.relicInstances);
    out += " otherclass=" + std::to_string(r.otherClassInstances);
    out += " relics=";
    if (r.relics.empty()) out += "none";
    for (std::size_t i = 0; i < r.relics.size(); ++i) {
        if (i) out += ",";
        out += std::to_string(r.relics[i].slot) + ":" + std::to_string(r.relics[i].id)
             + "@" + std::to_string(r.relics[i].level);
    }
    out += std::string(" control=") + (r.controlStatus ? r.controlStatus : "not-run");
    out += " itemType=" + std::to_string(r.controlItemType);
    out += std::string(" stopped=") + (r.stopped ? r.stopped : "none");
    return out;
}

// ---------------------------------------------------------------------------
// The relic tab (ForgePact#125).
//
// Relics the character owns but does not wear sit in the backpack's relic tab,
// which has one cell per relic id: `Controller_obj.inventoryData[key - 1]
// .inventoryRelicGrid[relicId][0][0]` holds a grid node whose `nodeFingerprint`
// is the owned copy's fingerprint (an empty cell holds undefined).
// `key` is kOnlineProfileKey when `global.onl` is 1, and the player row
// (`global.mplr`) otherwise. The game's own PickupRelic and
// RelicCheckAchievement use that rule and hand the key to GetProfileInventoryData,
// which reads index `key - 1`; the latter walks ids 0..155 the same way (static
// reading of the Sep-17 build, 2026-09-30; docs/models/relic-pick-spec.md).
// Measured live 2026-09-30 (#125, Live 1): offline, `mplr` is 1 and
// `inventoryData` holds one element, a reference to the New_Inventory_Data_obj
// instance carrying `inventoryRelicGrid`: 156 cells, each `[[node]]` or
// `[[undefined]]`, a node being `{nodeStartX, nodeStartY, nodeLocked,
// nodeIsPermanent, nodeFingerprint}`.
// PickupRelic refuses a pickup when that copy's `o` has reached 10, so a relic
// maxed here is as unobtainable as a maxed equipped one.
//
// The route reads variables only. It never calls GetProfileInventoryData,
// which returns the same `inventoryData[key]`: called without the game's own
// context it has crashed the game (docs/RUNTIME_DATA_MODELS.md).
// ---------------------------------------------------------------------------

/// Controller_obj's variable holding the profiles' inventory data, indexed by key.
inline constexpr std::string_view kRelicTabHolderField = "inventoryData";
/// The profile's relic grid: `[relicId][0][0]` is a grid node, or undefined.
inline constexpr std::string_view kRelicTabGridField = "inventoryRelicGrid";
/// A grid node's field holding the owned copy's fingerprint.
inline constexpr std::string_view kGridNodeFingerprintField = "nodeFingerprint";
/// `global.onl`: 1 while the game runs online, when the profile key is kOnlineProfileKey.
inline constexpr std::string_view kOnlineFlagGlobal = "onl";
inline constexpr int kOnlineProfileKey = 1;

/**
 * What one ScanRelicTab call did, stage by stage, so a live read of "no maxed
 * relics" says whether the grid was read at all, the way
 * EquippedSlotScanReport does for the equipped slots.
 *
 * C++ only: the Python binding reads saves, where the relic tab is the
 * `inventory_relic_tab` object of `inventory_order_<slot>.hss` and no
 * resolver is called.
 */
struct RelicTabScanReport {
    /// The stage that ended the scan early (`yytk`, `mplr`, `key`, `controller`,
    /// `inventoryData`, `profile`, `grid`, `global`, `owner`, `exception`), or
    /// nullptr when the whole grid was read. `not-run` until the scan starts,
    /// so a report the scan never reached cannot read as a complete one.
    const char* stopped = "not-run";
    /// The profile key used (the game's: 1 online, the player row offline) and
    /// the `inventoryData` index it reads (`key - 1`), -1 unread; and whether
    /// `global.onl` read 1.
    int key = -1;
    int profile = -1;
    bool online = false;
    /// Length of the relic grid, -1 unread; cells read within kRelicIdLimit,
    /// those holding a grid node, and nodes carrying a fingerprint string.
    int gridLength = -1;
    int cells = 0;
    int nodes = 0;
    int strings = 0;
    /// Whether GetOnlinePlayerItemOwner returned success.
    bool ownerResolved = false;
    /// GetItemFromFingerprint calls the runner refused, and those it ran; of
    /// those it ran, results that were not a struct, and structs by class.
    int resolverRefused = 0;
    int itemsResolved = 0;
    int nonStructResults = 0;
    int noClassResults = 0;
    int relicInstances = 0;
    int otherClassInstances = 0;
    /// `id:level` of every relic the grid yielded at kMaxedRelicLevel or above,
    /// in id order.
    std::vector<std::pair<int, int>> maxed;
};

/**
 * Adds the relics in the relic tab (ForgePact#125).
 *
 * Nothing is guessed:
 * - an `mplr` that is not a whole number in 0..kMaxLocalPlayerIndex reads
 *   nothing;
 * - Controller_obj is found by name, through the runner's own
 *   `asset_get_index` and `instance_find`;
 * - a cell that is not a grid node with a non-empty `nodeFingerprint` string
 *   is skipped;
 * - only strings ever reach the game's resolver.
 *
 * The owner and the resolver are the equipped-slot route's
 * (`GetOnlinePlayerItemOwner(mplr)`, then `GetItemFromFingerprint(fingerprint,
 * owner)`, with the global instance as self and other), and the item is
 * identified by its class in ScanContainerForRelics, as there.
 */
inline void ScanRelicTab(
    YYTKInterface* yytk,
    std::unordered_map<int, int>& outRelicLevels,
    RelicTabScanReport* report = nullptr
) {
    const auto stop = [report](const char* stage) {
        if (report) report->stopped = stage;
    };
    if (!yytk) return stop("yytk");
    stop(nullptr);
    try {
        const RValue mplr = YYTK::GetGlobalVariable(yytk, "mplr");
        if (mplr.m_Kind != ::YYTK::VALUE_REAL && mplr.m_Kind != ::YYTK::VALUE_INT32
            && mplr.m_Kind != ::YYTK::VALUE_INT64) return stop("mplr");
        const double row = mplr.ToDouble();
        if (!std::isfinite(row) || std::floor(row) != row
            || row < 0 || row > kMaxLocalPlayerIndex) return stop("mplr");

        const RValue onl = YYTK::GetGlobalVariable(yytk, kOnlineFlagGlobal);
        const bool online = (onl.m_Kind == ::YYTK::VALUE_REAL || onl.m_Kind == ::YYTK::VALUE_INT32
                             || onl.m_Kind == ::YYTK::VALUE_INT64 || onl.m_Kind == ::YYTK::VALUE_BOOL)
                            && onl.ToDouble() == 1.0;
        const int key = online ? kOnlineProfileKey : static_cast<int>(row);
        // GetProfileInventoryData reads `inventoryData[key - 1]`.
        const int profileIndex = key - 1;
        if (report) {
            report->online = online;
            report->key = key;
            report->profile = profileIndex;
        }
        if (profileIndex < 0) return stop("key");

        const RValue objectIndex = yytk->CallBuiltin("asset_get_index", {
            RValue(std::string(HeroSiege::Objects::GetObjectName(HeroSiege::Objects::GameObject::Controller_obj))) });
        if ((objectIndex.m_Kind != ::YYTK::VALUE_REAL && objectIndex.m_Kind != ::YYTK::VALUE_INT32
             && objectIndex.m_Kind != ::YYTK::VALUE_INT64 && objectIndex.m_Kind != ::YYTK::VALUE_REF)
            || objectIndex.ToDouble() < 0) return stop("controller");
        const RValue controller = yytk->CallBuiltin("instance_find", { objectIndex, RValue(0.0) });
        if (!IsInstanceHandle(controller)) return stop("controller");

        if (!YYTK::InstanceHasVariable(yytk, controller, kRelicTabHolderField)) return stop("inventoryData");
        const RValue profiles = YYTK::GetInstanceVariable(yytk, controller, kRelicTabHolderField);
        RValue profile;
        if (!Detail::ArrayAt(yytk, profiles, profileIndex, profile)) return stop("inventoryData");

        RValue grid;
        if (profile.m_Kind == ::YYTK::VALUE_OBJECT
            && YYTK::StructHasVariable(yytk, profile, kRelicTabGridField)) {
            grid = YYTK::GetStructVariable(yytk, profile, kRelicTabGridField);
        } else if (profile.m_Kind == ::YYTK::VALUE_REF
                   && YYTK::InstanceHasVariable(yytk, profile, kRelicTabGridField)) {
            grid = YYTK::GetInstanceVariable(yytk, profile, kRelicTabGridField);
        } else {
            return stop("profile");
        }
        if (grid.m_Kind != ::YYTK::VALUE_ARRAY) return stop("grid");
        const int length = YYTK::GetArrayLength(yytk, grid);
        if (report) report->gridLength = length;
        const int limit = length < kRelicIdLimit ? length : kRelicIdLimit;

        CInstance* global = nullptr;
        bool haveOwner = false;
        RValue owner;
        const auto resolveOwner = [&]() -> const char* {
            if (haveOwner) return nullptr;
            yytk->GetGlobalInstance(&global);
            if (!global) return "global";
            if (!::Aurie::AurieSuccess(yytk->CallGameScriptEx(
                    owner, HeroSiege::Scripts::gml_Script_GetOnlinePlayerItemOwner,
                    global, global, { RValue(row) }))) return "owner";
            haveOwner = true;
            if (report) report->ownerResolved = true;
            return nullptr;
        };

        for (int relicId = 0; relicId < limit; ++relicId) {
            RValue column, first, fingerprint;
            if (!Detail::ArrayAt(yytk, grid, relicId, column)) continue;
            if (report) ++report->cells;
            RValue node;
            if (!Detail::ArrayAt(yytk, column, 0, first) || !Detail::ArrayAt(yytk, first, 0, node)) continue;
            if (node.m_Kind != ::YYTK::VALUE_OBJECT || !node.m_Object) continue;
            if (report) ++report->nodes;
            if (!YYTK::StructHasVariable(yytk, node, kGridNodeFingerprintField)) continue;
            fingerprint = YYTK::GetStructVariable(yytk, node, kGridNodeFingerprintField);
            if (fingerprint.m_Kind != ::YYTK::VALUE_STRING || fingerprint.ToString().empty()) continue;
            if (report) ++report->strings;

            if (const char* failed = resolveOwner()) return stop(failed);

            RValue item;
            if (!::Aurie::AurieSuccess(yytk->CallGameScriptEx(
                    item, HeroSiege::Scripts::gml_Script_GetItemFromFingerprint,
                    global, global, { fingerprint, owner }))) {
                if (report) ++report->resolverRefused;
                continue;
            }
            if (report) ++report->itemsResolved;
            if (item.m_Kind != ::YYTK::VALUE_OBJECT || !item.m_Object) {
                if (report) ++report->nonStructResults;
                continue;
            }

            if (report) {
                int itemClass = -1;
                if (YYTK::StructHasVariable(yytk, item, kItemInstanceTypeField)) {
                    const RValue cls = YYTK::GetStructVariable(yytk, item, kItemInstanceTypeField);
                    if (cls.m_Kind == ::YYTK::VALUE_REAL || cls.m_Kind == ::YYTK::VALUE_INT32
                        || cls.m_Kind == ::YYTK::VALUE_INT64) {
                        itemClass = static_cast<int>(cls.ToDouble());
                    }
                }
                if (itemClass < 0) ++report->noClassResults;
                else if (itemClass == kRelicItemClass) ++report->relicInstances;
                else ++report->otherClassInstances;
            }

            std::unordered_map<int, int> cellRelics;
            ScanContainerForRelics(yytk, item, cellRelics, ContainerKind::General, 0);
            for (const auto& [id, level] : cellRelics) {
                if (report && level >= kMaxedRelicLevel) report->maxed.push_back({ id, level });
                const auto found = outRelicLevels.find(id);
                if (found == outRelicLevels.end() || level > found->second) outRelicLevels[id] = level;
            }
        }
        if (report) std::sort(report->maxed.begin(), report->maxed.end());
    } catch (...) {
        stop("exception");
    }
}

/**
 * One line naming what a relic-tab scan did, for a log: e.g. `key=1 profile=0
 * online=no grid=156 cells=156 nodes=14 strings=14 owner=ok resolved=14
 * refused=0 nonstruct=0 noclass=0 relic=14 otherclass=0 maxed=40@10
 * stopped=none`.
 */
inline std::string FormatRelicTabScanReport(const RelicTabScanReport& r) {
    std::string out;
    out += "key=" + std::to_string(r.key);
    out += " profile=" + std::to_string(r.profile);
    out += std::string(" online=") + (r.online ? "yes" : "no");
    out += " grid=" + std::to_string(r.gridLength);
    out += " cells=" + std::to_string(r.cells);
    out += " nodes=" + std::to_string(r.nodes);
    out += " strings=" + std::to_string(r.strings);
    out += std::string(" owner=") + (r.ownerResolved ? "ok" : "no");
    out += " resolved=" + std::to_string(r.itemsResolved);
    out += " refused=" + std::to_string(r.resolverRefused);
    out += " nonstruct=" + std::to_string(r.nonStructResults);
    out += " noclass=" + std::to_string(r.noClassResults);
    out += " relic=" + std::to_string(r.relicInstances);
    out += " otherclass=" + std::to_string(r.otherClassInstances);
    out += " maxed=";
    if (r.maxed.empty()) out += "none";
    for (std::size_t i = 0; i < r.maxed.size(); ++i) {
        if (i) out += ",";
        out += std::to_string(r.maxed[i].first) + "@" + std::to_string(r.maxed[i].second);
    }
    out += std::string(" stopped=") + (r.stopped ? r.stopped : "none");
    return out;
}

/// `id:level` for every relic in `relicLevels`, ascending by id, comma
/// separated; `none` when empty. For logging the whole owned map.
inline std::string FormatRelicLevels(const std::unordered_map<int, int>& relicLevels) {
    std::vector<std::pair<int, int>> sorted(relicLevels.begin(), relicLevels.end());
    std::sort(sorted.begin(), sorted.end());
    if (sorted.empty()) return "none";
    std::string out;
    for (std::size_t i = 0; i < sorted.size(); ++i) {
        if (i) out += ",";
        out += std::to_string(sorted[i].first) + ":" + std::to_string(sorted[i].second);
    }
    return out;
}

/**
 * Returns a map of every owned relic id and its highest recorded level, across
 * the equipped relic slots, the relic tab and the player containers below.
 *
 * `equippedReport`, when given, receives what the equipped-slot read did
 * (ScanEquippedRelicSlots), and `tabReport` what the relic-tab read did
 * (ScanRelicTab). When the player handle is unusable, or an earlier container
 * throws, the scan never reaches them and each report keeps
 * `stopped == "not-run"`.
 */
inline std::unordered_map<int, int> GetOwnedRelicLevels(
    YYTKInterface* yytk,
    const RValue& player,
    EquippedSlotScanReport* equippedReport = nullptr,
    RelicTabScanReport* tabReport = nullptr
) {
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
        ScanEquippedRelicSlots(yytk, relicMap, equippedReport);

        // 4. The relic tab: the relics owned but not worn (ForgePact#125).
        ScanRelicTab(yytk, relicMap, tabReport);
    } catch (...) {}

    return relicMap;
}

/**
 * The relic IDs in `relicLevels` at maximum level (>= kMaxedRelicLevel), for a
 * caller that already holds the owned map (to log it whole beside the set).
 */
inline std::unordered_set<int> MaxedRelicIdsOf(const std::unordered_map<int, int>& relicLevels) {
    std::unordered_set<int> maxed;
    for (const auto& [id, lvl] : relicLevels) {
        if (lvl >= kMaxedRelicLevel) {
            maxed.insert(id);
        }
    }
    return maxed;
}

/**
 * Returns set of relic IDs that are at maximum level (>= kMaxedRelicLevel).
 * `equippedReport` and `tabReport` as in GetOwnedRelicLevels.
 */
inline std::unordered_set<int> GetMaxedRelicIds(
    YYTKInterface* yytk,
    const RValue& player,
    EquippedSlotScanReport* equippedReport = nullptr,
    RelicTabScanReport* tabReport = nullptr
) {
    return MaxedRelicIdsOf(GetOwnedRelicLevels(yytk, player, equippedReport, tabReport));
}

#endif

} // namespace HeroSiege::Player
