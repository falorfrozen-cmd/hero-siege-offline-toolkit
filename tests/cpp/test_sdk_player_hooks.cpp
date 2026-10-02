// Behavioural tests for the two hs-game-sdk C++ helpers that cannot be checked
// from Python: the relic scanner in player.hpp and the script-hook installer in
// hooks.hpp.
//
// Both are exercised through the UNCHANGED production headers. The YYToolkit
// and Aurie surfaces come from tests/cpp/stubs, so the SDK's own
// __has_include detection fires and the real code paths run against controlled
// responses - no Aurie runtime, no DLL in the game, no live game required.
//
// Driven by tests/test_cpp_sdk.py, which compiles and runs this and compares
// the relic results against the Python SDK's scan_relic_levels().

#include <cstdio>
#include <functional>
#include <map>
#include <string>
#include <vector>

#include <hs_game_sdk/player.hpp>
#include <hs_game_sdk/hooks.hpp>
#include <hs_game_sdk/item_type.hpp>

using YYTK::CInstance;
using YYTK::FakeStruct;
using YYTK::PFUNC_YYGMLScript;
using YYTK::RValue;

static int g_failures = 0;

#define CHECK(cond)                                                              \
    do {                                                                         \
        if (!(cond)) {                                                           \
            std::printf("FAIL line %d: %s\n", __LINE__, #cond);                   \
            ++g_failures;                                                        \
        }                                                                        \
    } while (0)

#define CHECK_EQ(actual, expected)                                               \
    do {                                                                         \
        const auto a_ = (actual);                                                \
        const auto e_ = (expected);                                              \
        if (!(a_ == e_)) {                                                        \
            std::printf("FAIL line %d: %s == %s (got %lld, want %lld)\n",         \
                        __LINE__, #actual, #expected,                            \
                        static_cast<long long>(a_), static_cast<long long>(e_));  \
            ++g_failures;                                                        \
        }                                                                        \
    } while (0)

// ---------------------------------------------------------------------------
// A YYTKInterface that answers from tables the test fills in.
// ---------------------------------------------------------------------------

class ControlledYYTK : public YYTK::YYTKInterface {
public:
    FakeStruct instanceFields;
    std::map<std::string, RValue> globals;
    std::map<std::string, PVOID> routines;

    RValue CallBuiltin(std::string_view name, std::vector<RValue> args) override {
        const std::string key = args.size() >= 2 ? args[1].m_String : std::string();

        if (name == "variable_instance_exists") {
            return RValue(instanceFields.count(key) > 0);
        }
        if (name == "variable_instance_get") {
            auto it = instanceFields.find(key);
            return it == instanceFields.end() ? RValue() : it->second;
        }
        if (name == "variable_struct_exists") {
            const FakeStruct* fields = StructOf(args.empty() ? RValue() : args[0]);
            return RValue(fields != nullptr && fields->count(key) > 0);
        }
        if (name == "variable_struct_get") {
            const FakeStruct* fields = StructOf(args.empty() ? RValue() : args[0]);
            if (!fields) return RValue();
            auto it = fields->find(key);
            return it == fields->end() ? RValue() : it->second;
        }
        if (name == "variable_global_exists") {
            const std::string g = args.empty() ? std::string() : args[0].m_String;
            return RValue(globals.count(g) > 0);
        }
        if (name == "variable_global_get") {
            const std::string g = args.empty() ? std::string() : args[0].m_String;
            auto it = globals.find(g);
            return it == globals.end() ? RValue() : it->second;
        }
        if (name == "array_length") {
            if (args.empty() || !args[0].m_Elements) return RValue(0);
            return RValue(static_cast<double>(args[0].m_Elements->size()));
        }
        if (name == "array_get") {
            if (args.size() < 2 || !args[0].m_Elements) return RValue();
            const int index = static_cast<int>(args[1].ToDouble());
            if (index < 0 || index >= static_cast<int>(args[0].m_Elements->size())) return RValue();
            return (*args[0].m_Elements)[static_cast<size_t>(index)];
        }
        // An asset the map does not name is -1, as the runner answers for an
        // unknown name; an object with no instance listed has none (`noone`).
        if (name == "asset_get_index") {
            const std::string asset = args.empty() ? std::string() : args[0].m_String;
            auto it = assets.find(asset);
            return RValue(it == assets.end() ? -1.0 : it->second);
        }
        if (name == "instance_find") {
            const double object = args.empty() ? -1.0 : args[0].ToDouble();
            auto it = firstInstances.find(object);
            return it == firstInstances.end() ? RValue(-4.0) : it->second;
        }
        return RValue();
    }

    /// Asset name -> index (`asset_get_index`), and an object's first instance
    /// (`instance_find(object, 0)`).
    std::map<std::string, double> assets;
    std::map<double, RValue> firstInstances;

    RValue CallGameScript(std::string, const std::vector<RValue>&) override { return RValue(); }

    // Game scripts called by name with an explicit self/other. A script the
    // map does not name is not found, the way an unresolvable name is; a
    // script it does name answers whatever the fixture returns: a struct, a
    // number or undefined.
    using GameScriptFn = std::function<RValue(const std::vector<RValue>&)>;
    std::map<std::string, GameScriptFn> gameScripts;
    struct ScriptCall {
        std::string name;
        std::vector<RValue> args;
        bool selfAndOtherAreGlobal = false;
    };
    std::vector<ScriptCall> scriptCalls;

    ::Aurie::AurieStatus CallGameScriptEx(RValue& result, std::string_view scriptName,
                                          CInstance* self, CInstance* other,
                                          const std::vector<RValue>& args) override {
        const std::string name(scriptName);
        scriptCalls.push_back({ name, args, self == GlobalInstance() && other == GlobalInstance() });
        auto it = gameScripts.find(name);
        if (it == gameScripts.end()) return ::Aurie::AURIE_OBJECT_NOT_FOUND;
        result = it->second(args);
        return ::Aurie::AURIE_SUCCESS;
    }

    size_t CallsTo(std::string_view name) const {
        size_t n = 0;
        for (const auto& call : scriptCalls) n += call.name == name ? 1 : 0;
        return n;
    }

    ::Aurie::AurieStatus GetGlobalInstance(CInstance** outInstance) override {
        if (outInstance) *outInstance = GlobalInstance();
        return ::Aurie::AURIE_SUCCESS;
    }

    ::Aurie::AurieStatus GetNamedRoutinePointer(const char* name, PVOID* outPointer) override {
        auto it = routines.find(name ? name : "");
        if (it == routines.end()) return ::Aurie::AURIE_OBJECT_NOT_FOUND;
        if (outPointer) *outPointer = it->second;
        return ::Aurie::AURIE_SUCCESS;
    }

private:
    static CInstance* GlobalInstance() {
        static CInstance instance;
        return &instance;
    }

    static const FakeStruct* StructOf(const RValue& value) {
        return value.m_Struct ? value.m_Struct.get() : nullptr;
    }
};

static RValue FakePlayer() {
    RValue player;
    player.m_Kind = YYTK::VALUE_OBJECT;
    static int marker = 0;
    player.m_Object = &marker;
    return player;
}

// The local player as THIS runner actually hands it over: an instance
// reference, not a struct. ForgePact resolves the player with
// instance_find(Player_obj), which returns VALUE_REF (kind 15) - measured
// 2026-09-10 and documented in ModuleMain.cpp's HhResolveLocalPlayer. Every
// instance accessor the scanner uses (variable_instance_exists /
// variable_instance_get) takes a reference happily, so a scan handed one must
// return the same relics as a scan handed a struct.
static RValue FakePlayerRef() {
    RValue player;
    player.m_Kind = YYTK::VALUE_REF;
    player.m_Real = 100001.0;  // an instance id, the way a real reference carries one
    return player;
}

// ---------------------------------------------------------------------------
// Relic fixtures. The ordinary item is the negative example the review used,
// and the same one test_expanded_sdk.py already relies on.
// ---------------------------------------------------------------------------

static RValue OrdinaryItemWithLevel() {
    return RValue::Struct({ { "b", RValue(15) }, { "c", RValue(8) }, { "level", RValue(100) } });
}

static RValue RealMaxedRelic() {
    return RValue::Struct({ { "b", RValue(42) }, { "c", RValue(16) }, { "o", RValue(10) } });
}

static RValue StarUpgradedOrdinaryItem() {
    // `p` is a star upgrade count, not a relic level.
    return RValue::Struct({ { "b", RValue(7) }, { "c", RValue(6) }, { "p", RValue(12) } });
}

static RValue StackedLowLevelRelic() {
    // A real relic at level 3 that also carries a stack count of 99. The count
    // must not be read as a level, or it would look maxed.
    return RValue::Struct({
        { "b", RValue(50) }, { "c", RValue(16) }, { "o", RValue(3) }, { "count", RValue(99) },
    });
}

static void TestRelicIdentification() {
    using namespace HeroSiege::Player;

    // 1. The reported case: an ordinary item with a large level field, alone.
    {
        ControlledYYTK yytk;
        yytk.instanceFields["equippedItems"] = RValue::Array({ OrdinaryItemWithLevel() });
        const auto maxed = GetMaxedRelicIds(&yytk, FakePlayer());
        std::printf("C++: ordinary_item_id_15_flagged_maxed_relic=%d\n", maxed.count(15) ? 1 : 0);
        CHECK(maxed.count(15) == 0);
        CHECK(maxed.empty());
    }

    // 2. A real relic is still found.
    {
        ControlledYYTK yytk;
        yytk.instanceFields["equippedItems"] = RValue::Array({ RealMaxedRelic() });
        const auto maxed = GetMaxedRelicIds(&yytk, FakePlayer());
        std::printf("C++: real_relic_id_42_flagged_maxed_relic=%d\n", maxed.count(42) ? 1 : 0);
        CHECK(maxed.count(42) == 1);
        CHECK_EQ(maxed.size(), static_cast<size_t>(1));
    }

    // 3. Both together: only the relic.
    {
        ControlledYYTK yytk;
        yytk.instanceFields["equippedItems"] =
            RValue::Array({ OrdinaryItemWithLevel(), RealMaxedRelic() });
        const auto owned = GetOwnedRelicLevels(&yytk, FakePlayer());
        CHECK_EQ(owned.size(), static_cast<size_t>(1));
        CHECK(owned.count(42) == 1);
        CHECK(owned.count(15) == 0);
        if (owned.count(42)) CHECK_EQ(owned.at(42), 10);

        // Machine-readable for the Python parity check.
        for (const auto& [id, level] : owned) {
            std::printf("PARITY_OWNED %d=%d\n", id, level);
        }
    }

    // 4. A star upgrade count is not a relic level.
    {
        ControlledYYTK yytk;
        yytk.instanceFields["equippedItems"] = RValue::Array({ StarUpgradedOrdinaryItem() });
        CHECK(GetOwnedRelicLevels(&yytk, FakePlayer()).empty());
    }

    // 5. A stack count on a real relic does not inflate its level.
    {
        ControlledYYTK yytk;
        yytk.instanceFields["equippedItems"] = RValue::Array({ StackedLowLevelRelic() });
        const auto owned = GetOwnedRelicLevels(&yytk, FakePlayer());
        CHECK(owned.count(50) == 1);
        if (owned.count(50)) CHECK_EQ(owned.at(50), 3);
        CHECK(GetMaxedRelicIds(&yytk, FakePlayer()).empty());
    }

    // 6. Numbers in a general container are not relic levels.
    {
        ControlledYYTK yytk;
        yytk.instanceFields["inventory"] = RValue::Array({ RValue(10), RValue(10), RValue(10) });
        const auto owned = GetOwnedRelicLevels(&yytk, FakePlayer());
        std::printf("C++: numbers_in_general_container_invented_relics=%d\n",
                    static_cast<int>(owned.size()));
        CHECK(owned.empty());
    }

    // 7. In a dedicated relic table, the same numbers ARE id -> level.
    {
        ControlledYYTK yytk;
        yytk.instanceFields["relic_levels"] = RValue::Array({ RValue(4), RValue(10), RValue(0) });
        const auto owned = GetOwnedRelicLevels(&yytk, FakePlayer());
        CHECK_EQ(owned.size(), static_cast<size_t>(2));
        if (owned.count(0)) CHECK_EQ(owned.at(0), 4);
        if (owned.count(1)) CHECK_EQ(owned.at(1), 10);
        CHECK(owned.count(2) == 0);
        const auto maxed = GetMaxedRelicIds(&yytk, FakePlayer());
        CHECK(maxed.count(1) == 1);
        CHECK(maxed.count(0) == 0);
    }

    // 8. A slot wrapper around an inner `data` struct still resolves.
    {
        ControlledYYTK yytk;
        yytk.instanceFields["equippedItems"] =
            RValue::Array({ RValue::Struct({ { "data", RealMaxedRelic() } }) });
        CHECK(GetMaxedRelicIds(&yytk, FakePlayer()).count(42) == 1);
    }

    // 9. An id outside the plausible relic range is rejected even with tier 16.
    {
        ControlledYYTK yytk;
        yytk.instanceFields["equippedItems"] = RValue::Array({
            RValue::Struct({ { "b", RValue(500) }, { "c", RValue(16) }, { "o", RValue(10) } }),
        });
        CHECK(GetOwnedRelicLevels(&yytk, FakePlayer()).empty());
    }

    // 10. The highest of several level fields wins, not the first found.
    {
        ControlledYYTK yytk;
        yytk.instanceFields["equippedItems"] = RValue::Array({
            RValue::Struct({
                { "b", RValue(42) }, { "c", RValue(16) },
                { "o", RValue(3) }, { "level", RValue(10) },
            }),
        });
        const auto owned = GetOwnedRelicLevels(&yytk, FakePlayer());
        CHECK(owned.count(42) == 1);
        if (owned.count(42)) CHECK_EQ(owned.at(42), 10);
    }

    // 11. The player arrives as an instance REFERENCE, which is what this
    //     runner hands back. A reference must scan exactly like a struct.
    //
    //     REPORTED 2026-09-14: "Remove owned relics from drop pool" did
    //     nothing in game. The panel sent `relicfilter 1`, the plugin armed
    //     it and logged "relicfilter: hook installed -> ON", and then every
    //     drop came through unfiltered, because the scan below was handed the
    //     VALUE_REF player and returned an empty map before reading anything.
    {
        ControlledYYTK yytk;
        yytk.instanceFields["equippedItems"] = RValue::Array({ RealMaxedRelic() });
        const auto owned = GetOwnedRelicLevels(&yytk, FakePlayerRef());
        const auto maxed = GetMaxedRelicIds(&yytk, FakePlayerRef());
        std::printf("C++: relic_scan_through_instance_reference=%d\n",
                    maxed.count(42) ? 1 : 0);
        CHECK(owned.count(42) == 1);
        if (owned.count(42)) CHECK_EQ(owned.at(42), 10);
        CHECK(maxed.count(42) == 1);

        // ... and the same fixture through a struct player, so the two kinds
        // are asserted to agree rather than merely both being non-empty.
        CHECK(owned == GetOwnedRelicLevels(&yytk, FakePlayer()));
    }

    // 12. A reference is not a blank cheque: an undefined player still scans
    //     nothing, so "accept VALUE_REF" cannot become "accept anything".
    {
        ControlledYYTK yytk;
        yytk.instanceFields["equippedItems"] = RValue::Array({ RealMaxedRelic() });
        CHECK(GetOwnedRelicLevels(&yytk, RValue()).empty());
    }
}

// ---------------------------------------------------------------------------
// #93: the equipped relic slots. A relic's definition carries `c: 0` and no
// class field (read from a character save 2026-09-27), so the class is only on
// the item INSTANCE (`itemType`, beside `itemDefinitionStruct`). The game keeps
// the equipped items as fingerprint strings in
// global.equippedItems[mplr][0][slot] and resolves one with
// GetItemFromFingerprint(fingerprint, GetOnlinePlayerItemOwner(mplr)) - the
// route ForgePact's Miner's Helmet reads slot 0 through, live.
// ---------------------------------------------------------------------------

static RValue RelicInstance(int id, int level, int slot) {
    return RValue::Struct({
        { "itemType", RValue(16) },
        { "itemDefinitionStruct", RValue::Struct({
            { "b", RValue(id) }, { "c", RValue(0) }, { "o", RValue(level) }, { "g", RValue(slot) },
        }) },
    });
}

static RValue OrdinaryGloveInstance() {
    // An equipped unique glove: class 4, repository flag `c` 1.
    return RValue::Struct({
        { "itemType", RValue(4) },
        { "itemDefinitionStruct", RValue::Struct({
            { "b", RValue(18) }, { "c", RValue(1) }, { "g", RValue(4) },
        }) },
    });
}

static RValue MaterialStackInstance() {
    // A material stack (class 14) whose `o` would read as maxed if the class
    // were not checked.
    return RValue::Struct({
        { "itemType", RValue(14) },
        { "itemDefinitionStruct", RValue::Struct({ { "b", RValue(51) }, { "o", RValue(99) } }) },
    });
}

static const char* kFpRelic135 = "0-0-209562107245-16";
static const char* kFpRelic109 = "0-0-209562107300-16";
static const char* kFpRelic15 = "0-0-210021549852-16";
static const char* kFpUnresolved = "0-0-210021549999-16";
static const char* kFpOrdinary = "0-0-210025648571-7";

// global.equippedItems as the game lays it out: one row per online player,
// whose [0] array holds the local character's slots. Slot 8 holds an ordinary
// weapon, 10-12 three relics (two maxed), 13 a fingerprint the resolver does
// not know, 14 a number where a string belongs. `mplr` picks the row the
// character sits on; the rows before it are empty.
static void FillEquippedSlots(ControlledYYTK& yytk, int mplr = 0) {
    std::vector<RValue> slots(15);
    slots[8] = RValue(std::string(kFpOrdinary));
    slots[10] = RValue(std::string(kFpRelic135));
    slots[11] = RValue(std::string(kFpRelic109));
    slots[12] = RValue(std::string(kFpRelic15));
    slots[13] = RValue(std::string(kFpUnresolved));
    slots[14] = RValue(7);
    std::vector<RValue> rows(static_cast<size_t>(mplr) + 1, RValue::Array({}));
    rows[static_cast<size_t>(mplr)] = RValue::Array({ RValue::Array(std::move(slots)) });
    yytk.globals["mplr"] = RValue(mplr);
    yytk.globals["equippedItems"] = RValue::Array(std::move(rows));

    yytk.gameScripts[std::string(HeroSiege::Scripts::gml_Script_GetOnlinePlayerItemOwner)] =
        [](const std::vector<RValue>&) { return RValue(0); };
    yytk.gameScripts[std::string(HeroSiege::Scripts::gml_Script_GetItemFromFingerprint)] =
        [](const std::vector<RValue>& args) {
            const std::string fp = args.empty() ? std::string() : args[0].m_String;
            if (fp == kFpRelic135) return RelicInstance(135, 10, 11);
            if (fp == kFpRelic109) return RelicInstance(109, 10, 14);
            if (fp == kFpRelic15) return RelicInstance(15, 8, 10);
            if (fp == kFpOrdinary) return OrdinaryGloveInstance();
            return RValue();  // VALUE_UNDEFINED: resolves to nothing
        };
}

static void TestEquippedSlots() {
    using namespace HeroSiege::Player;
    const std::string resolver(HeroSiege::Scripts::gml_Script_GetItemFromFingerprint);

    // 1. The relic slots resolve, through both player kinds, to exactly the
    //    two maxed relics; the level-8 relic is owned but not maxed.
    for (const RValue& player : { FakePlayerRef(), FakePlayer() }) {
        ControlledYYTK yytk;
        FillEquippedSlots(yytk);
        const auto owned = GetOwnedRelicLevels(&yytk, player);
        const auto maxed = GetMaxedRelicIds(&yytk, player);
        CHECK_EQ(owned.size(), static_cast<size_t>(3));
        if (owned.count(15)) CHECK_EQ(owned.at(15), 8);
        CHECK_EQ(maxed.size(), static_cast<size_t>(2));
        CHECK(maxed.count(135) == 1);
        CHECK(maxed.count(109) == 1);

        // Only the four string fingerprints in slots 10-14 reached the
        // resolver: never slot 8, never the number in slot 14, and always
        // with the owner and the global instance as self and other.
        for (const auto& call : yytk.scriptCalls) {
            CHECK(call.selfAndOtherAreGlobal);
            if (call.name != resolver) continue;
            CHECK(call.args.size() == 2);
            if (call.args.size() != 2) continue;
            CHECK(call.args[0].m_Kind == YYTK::VALUE_STRING);
            CHECK(call.args[0].m_String != kFpOrdinary);
            CHECK_EQ(call.args[1].ToDouble(), 0.0);
        }
        // Slots 10-13 once for the owned scan and once for the maxed scan.
        CHECK_EQ(yytk.CallsTo(resolver), static_cast<size_t>(8));
        if (player.m_Kind == YYTK::VALUE_REF) {
            std::printf("C++: equipped_slot_maxed_relics=%d\n", static_cast<int>(maxed.size()));
        }
    }

    // 2. Negative control: the fingerprint that resolves to nothing adds no
    //    relic, on its own.
    {
        ControlledYYTK yytk;
        FillEquippedSlots(yytk);
        std::vector<RValue> slots(15);
        slots[13] = RValue(std::string(kFpUnresolved));
        yytk.globals["equippedItems"] = RValue::Array({ RValue::Array({ RValue::Array(std::move(slots)) }) });
        CHECK(GetOwnedRelicLevels(&yytk, FakePlayerRef()).empty());
        CHECK_EQ(yytk.CallsTo(resolver), static_cast<size_t>(1));
    }

    // 3. An unreadable or out-of-range `mplr` reads no slot at all.
    for (const RValue& mplr : { RValue(), RValue(5), RValue(0.5), RValue(std::string("0")) }) {
        ControlledYYTK yytk;
        FillEquippedSlots(yytk);
        yytk.globals["mplr"] = mplr;
        CHECK(GetOwnedRelicLevels(&yytk, FakePlayerRef()).empty());
        CHECK(yytk.scriptCalls.empty());
    }

    // 4. The equipped relics join, not replace, what the player's own
    //    containers hold; the highest level still wins.
    {
        ControlledYYTK yytk;
        FillEquippedSlots(yytk);
        yytk.instanceFields["relic_levels"] = RValue::Array({ RValue(0), RValue(3) });
        yytk.instanceFields["inventory"] = RValue::Array({ RelicInstance(15, 10, 0) });
        const auto owned = GetOwnedRelicLevels(&yytk, FakePlayerRef());
        CHECK_EQ(owned.size(), static_cast<size_t>(4));
        if (owned.count(1)) CHECK_EQ(owned.at(1), 3);
        if (owned.count(15)) CHECK_EQ(owned.at(15), 10);
    }
}

// ---------------------------------------------------------------------------
// ForgePact#125: the relic tab. Relics owned but not worn sit in
// Controller_obj.inventoryData[key - 1].inventoryRelicGrid[relicId][0][0] as
// a grid node carrying the owned copy's `nodeFingerprint`; key is 1 online and
// the player row (mplr) offline. Measured live 2026-09-30 (Live 1): offline
// mplr is 1, inventoryData holds one instance reference, and a cell is
// `[[node]]` or `[[undefined]]`. The fixture below lays that out, with the
// negative cases beside the real ones.
// ---------------------------------------------------------------------------

static const char* kFpTab40 = "0-0-211821263155-16";
static const char* kFpTab7 = "0-0-210869177253-16";
static const char* kFpTabUnresolved = "0-0-210869177999-16";
static const char* kFpTabOnline = "0-0-210869184312-16";
static constexpr double kControllerObject = 984.0;

static RValue TabCell(const char* fingerprint) {
    const RValue node = RValue::Struct({
        { "nodeStartX", RValue(0) }, { "nodeStartY", RValue(0) }, { "nodeLocked", RValue(false) },
        { "nodeIsPermanent", RValue(0) }, { "nodeFingerprint", RValue(std::string(fingerprint)) },
    });
    return RValue::Array({ RValue::Array({ node }) });
}

// One profile's relic grid, 45 cells long: 40 holds a relic at 10/10, 7 one
// with no `o` at all (level 1, as the save stores it), 12 a fingerprint the
// resolver does not know, 20 a number, 25 a bare fingerprint string (not the
// measured node shape, so never read) and 30 nothing. `secondProfile` puts
// one relic, 42 at 10/10, in that profile instead.
static RValue RelicGrid(bool secondProfile) {
    std::vector<RValue> cells(45, RValue::Array({ RValue::Array({ RValue() }) }));
    if (secondProfile) {
        cells[42] = TabCell(kFpTabOnline);
    } else {
        cells[40] = TabCell(kFpTab40);
        cells[7] = TabCell(kFpTab7);
        cells[12] = TabCell(kFpTabUnresolved);
        cells[20] = RValue::Array({ RValue::Array({ RValue(-4) }) });
        cells[25] = RValue::Array({ RValue::Array({ RValue(std::string(kFpTab40)) }) });
        cells[30] = RValue();
    }
    return RValue::Array(std::move(cells));
}

// inventoryData[0] is the profile the game reads for key 1 (offline mplr 1,
// or online), inventoryData[1] the one for key 2.
static void FillRelicTab(ControlledYYTK& yytk) {
    yytk.globals["mplr"] = RValue(1);
    yytk.globals["onl"] = RValue(0);
    yytk.assets["Controller_obj"] = kControllerObject;
    RValue controller;
    controller.m_Kind = YYTK::VALUE_REF;
    controller.m_Real = 100002.0;
    yytk.firstInstances[kControllerObject] = controller;
    yytk.instanceFields["inventoryData"] = RValue::Array({
        RValue::Struct({ { "inventoryRelicGrid", RelicGrid(false) } }),
        RValue::Struct({ { "inventoryRelicGrid", RelicGrid(true) } }),
    });

    yytk.gameScripts[std::string(HeroSiege::Scripts::gml_Script_GetOnlinePlayerItemOwner)] =
        [](const std::vector<RValue>&) { return RValue(0); };
    yytk.gameScripts[std::string(HeroSiege::Scripts::gml_Script_GetItemFromFingerprint)] =
        [](const std::vector<RValue>& args) {
            const std::string fp = args.empty() ? std::string() : args[0].m_String;
            if (fp == kFpTab40) return RelicInstance(40, 10, 0);
            if (fp == kFpTabOnline) return RelicInstance(42, 10, 0);
            if (fp == kFpTab7) {
                return RValue::Struct({
                    { "itemType", RValue(16) },
                    { "itemDefinitionStruct", RValue::Struct({ { "b", RValue(7) }, { "c", RValue(0) } }) },
                });
            }
            return RValue();  // VALUE_UNDEFINED: resolves to nothing
        };
}

static void TestRelicTab() {
    using namespace HeroSiege::Player;
    const std::string resolver(HeroSiege::Scripts::gml_Script_GetItemFromFingerprint);

    // 1. Offline, mplr 1: key 1 reads inventoryData[0]. 40 is maxed, 7 is
    //    owned at level 1, and only the three nodes' fingerprints reached the
    //    resolver; the bare string in cell 25 is not a node and is never read.
    {
        ControlledYYTK yytk;
        FillRelicTab(yytk);
        RelicTabScanReport report;
        const auto owned = GetOwnedRelicLevels(&yytk, FakePlayerRef(), nullptr, &report);
        CHECK_EQ(owned.size(), static_cast<size_t>(2));
        if (owned.count(40)) CHECK_EQ(owned.at(40), 10);
        if (owned.count(7)) CHECK_EQ(owned.at(7), 1);
        CHECK(report.stopped == nullptr);
        CHECK_EQ(report.key, 1);
        CHECK_EQ(report.profile, 0);
        CHECK(!report.online);
        CHECK_EQ(report.gridLength, 45);
        CHECK_EQ(report.cells, 45);          // every entry within the limit, arrays or not
        CHECK_EQ(report.nodes, 3);
        CHECK_EQ(report.strings, 3);
        CHECK(report.ownerResolved);
        CHECK_EQ(report.itemsResolved, 3);
        CHECK_EQ(report.nonStructResults, 1);
        CHECK_EQ(report.relicInstances, 2);
        CHECK_EQ(report.maxed.size(), static_cast<size_t>(1));
        CHECK_EQ(yytk.CallsTo(resolver), static_cast<size_t>(3));
        for (const auto& call : yytk.scriptCalls) {
            CHECK(call.selfAndOtherAreGlobal);
            if (call.name != resolver) continue;
            CHECK(call.args.size() == 2);
            if (call.args.size() == 2) CHECK(call.args[0].m_Kind == YYTK::VALUE_STRING);
        }
        CHECK(FormatRelicTabScanReport(report) ==
              "key=1 profile=0 online=no grid=45 cells=45 nodes=3 strings=3 owner=ok resolved=3 refused=0 "
              "nonstruct=1 noclass=0 relic=2 otherclass=0 maxed=40@10 stopped=none");
        const auto maxed = GetMaxedRelicIds(&yytk, FakePlayerRef());
        std::printf("C++: relic_tab_maxed_relics=%d id40=%d\n", static_cast<int>(maxed.size()),
                    maxed.count(40) ? 1 : 0);
    }

    // 2. The key: offline it is the player row, so mplr 2 reads
    //    inventoryData[1]; online it is 1 whatever mplr says, so the same
    //    world reads inventoryData[0]; and a row of 0 has no profile at all.
    {
        ControlledYYTK yytk;
        FillRelicTab(yytk);
        yytk.globals["mplr"] = RValue(2);
        RelicTabScanReport report;
        const auto maxed = GetMaxedRelicIds(&yytk, FakePlayerRef(), nullptr, &report);
        CHECK_EQ(report.key, 2);
        CHECK_EQ(report.profile, 1);
        CHECK_EQ(maxed.size(), static_cast<size_t>(1));
        CHECK(maxed.count(42) == 1);
    }
    {
        ControlledYYTK yytk;
        FillRelicTab(yytk);
        yytk.globals["mplr"] = RValue(2);
        yytk.globals["onl"] = RValue(1);
        RelicTabScanReport report;
        const auto maxed = GetMaxedRelicIds(&yytk, FakePlayerRef(), nullptr, &report);
        CHECK_EQ(report.key, 1);
        CHECK_EQ(report.profile, 0);
        CHECK(report.online);
        CHECK(maxed.count(40) == 1);
        CHECK(maxed.count(42) == 0);
    }
    {
        ControlledYYTK yytk;
        FillRelicTab(yytk);
        yytk.globals["mplr"] = RValue(0);
        RelicTabScanReport report;
        CHECK(GetOwnedRelicLevels(&yytk, FakePlayerRef(), nullptr, &report).empty());
        CHECK(report.stopped != nullptr && std::string(report.stopped) == "key");
        CHECK(yytk.scriptCalls.empty());
    }

    // 3. No Controller_obj: the scan stops there and calls nothing.
    {
        ControlledYYTK yytk;
        FillRelicTab(yytk);
        yytk.firstInstances.clear();
        RelicTabScanReport report;
        CHECK(GetOwnedRelicLevels(&yytk, FakePlayerRef(), nullptr, &report).empty());
        CHECK(report.stopped != nullptr && std::string(report.stopped) == "controller");
        CHECK(yytk.scriptCalls.empty());
    }

    // 4. A key past the profiles, and a profile without a grid, stop at their
    //    own stages.
    {
        ControlledYYTK yytk;
        FillRelicTab(yytk);
        yytk.globals["mplr"] = RValue(4);
        RelicTabScanReport report;
        CHECK(GetOwnedRelicLevels(&yytk, FakePlayerRef(), nullptr, &report).empty());
        CHECK(report.stopped != nullptr && std::string(report.stopped) == "inventoryData");
    }
    {
        ControlledYYTK yytk;
        FillRelicTab(yytk);
        yytk.instanceFields["inventoryData"] = RValue::Array({ RValue::Struct({ { "other", RValue(1) } }) });
        RelicTabScanReport report;
        CHECK(GetOwnedRelicLevels(&yytk, FakePlayerRef(), nullptr, &report).empty());
        CHECK(report.stopped != nullptr && std::string(report.stopped) == "profile");
    }

    // 5. The owner script is refused: the stage is named, no item is resolved.
    {
        ControlledYYTK yytk;
        FillRelicTab(yytk);
        yytk.gameScripts.erase(std::string(HeroSiege::Scripts::gml_Script_GetOnlinePlayerItemOwner));
        RelicTabScanReport report;
        CHECK(GetOwnedRelicLevels(&yytk, FakePlayerRef(), nullptr, &report).empty());
        CHECK(report.stopped != nullptr && std::string(report.stopped) == "owner");
        CHECK_EQ(yytk.CallsTo(resolver), static_cast<size_t>(0));
    }

    // 6. The relic tab joins the equipped slots: two maxed relics worn, one in
    //    the tab, both read for the offline character on row 1.
    {
        ControlledYYTK yytk;
        FillEquippedSlots(yytk, 1);
        const auto equippedFingerprints = yytk.gameScripts[resolver];
        FillRelicTab(yytk);
        const auto tabFingerprints = yytk.gameScripts[resolver];
        yytk.gameScripts[resolver] = [equippedFingerprints, tabFingerprints](const std::vector<RValue>& args) {
            RValue item = tabFingerprints(args);
            return item.m_Kind == YYTK::VALUE_UNDEFINED ? equippedFingerprints(args) : item;
        };
        const auto maxed = GetMaxedRelicIds(&yytk, FakePlayerRef());
        CHECK_EQ(maxed.size(), static_cast<size_t>(3));
        CHECK(maxed.count(135) == 1);
        CHECK(maxed.count(109) == 1);
        CHECK(maxed.count(40) == 1);
    }
}

// ---------------------------------------------------------------------------
// ForgePact#124: a relic lying on the ground. A dropped item is a
// Loot_Ground_obj instance whose own variables carry the item class
// (`itemType`) and the definition (`itemDefinitionStruct`, `b` the id) - a
// static reading of the ground item's Create, not yet confirmed live. The
// fields are filled as the instance's variables, and the instance handed over
// both as a struct-shaped instance and as the reference this runner produces.
// ---------------------------------------------------------------------------

static void FillGroundItem(ControlledYYTK& yytk, const RValue& item) {
    for (const auto& [name, value] : *item.m_Struct) yytk.instanceFields[name] = value;
}

static void TestGroundRelic() {
    using namespace HeroSiege::Player;

    // 1. A relic instance handed over as VALUE_OBJECT reads as relic 42.
    {
        ControlledYYTK yytk;
        FillGroundItem(yytk, RelicInstance(42, 1, 0));
        GroundRelicRead read;
        const bool ok = ReadGroundRelic(&yytk, FakePlayer(), read);
        std::printf("C++: ground_relic_object read=%d id=%d stage=%s\n", ok ? 1 : 0, read.relicId,
                    GroundRelicStageName(read.stage));
        CHECK(ok);
        CHECK(read.stage == GroundRelicStage::Ok);
        CHECK_EQ(read.relicId, 42);
        CHECK_EQ(read.itemClass, kRelicItemClass);
        CHECK(FormatGroundRelicRead(read) == "stage=ok class=16 id=42");
    }

    // 2. The same instance as the VALUE_REF this runner hands back reads the
    //    same. A struct-only accessor would read nothing off a reference.
    {
        ControlledYYTK yytk;
        FillGroundItem(yytk, RelicInstance(42, 1, 0));
        GroundRelicRead read;
        const bool ok = ReadGroundRelic(&yytk, FakePlayerRef(), read);
        std::printf("C++: ground_relic_reference read=%d id=%d stage=%s\n", ok ? 1 : 0, read.relicId,
                    GroundRelicStageName(read.stage));
        CHECK(ok);
        CHECK(read.stage == GroundRelicStage::Ok);
        CHECK_EQ(read.relicId, 42);
    }

    // 3. Refusals, each naming the stage it stopped at. A refusal also clears
    //    what an earlier read left in the same struct.
    const auto refuse = [](const RValue& instance, const RValue* item) {
        ControlledYYTK yytk;
        if (item) FillGroundItem(yytk, *item);
        GroundRelicRead read;
        read.relicId = 99;
        read.stage = GroundRelicStage::Ok;
        const bool ok = ReadGroundRelic(&yytk, instance, read);
        CHECK(!ok);
        CHECK_EQ(read.relicId, -1);
        return read;
    };

    // An ordinary unique glove (class 4) and a material stack (class 14) whose
    // `o` would read as maxed: the class says not a relic.
    const RValue glove = OrdinaryGloveInstance();
    const RValue material = MaterialStackInstance();
    const GroundRelicRead ordinary = refuse(FakePlayerRef(), &glove);
    const GroundRelicRead stack = refuse(FakePlayerRef(), &material);
    CHECK(ordinary.stage == GroundRelicStage::NotRelic);
    CHECK_EQ(ordinary.itemClass, 4);
    CHECK(stack.stage == GroundRelicStage::NotRelic);

    // A definition but no class field. Id-shaped and level-shaped fields -
    // the relic-only `relicLevel` included - are never evidence on their own.
    const RValue classless = RValue::Struct({
        { "b", RValue(42) }, { "relicLevel", RValue(3) },
        { "itemDefinitionStruct", RValue::Struct({ { "b", RValue(42) }, { "c", RValue(16) }, { "o", RValue(3) } }) },
    });
    const GroundRelicRead noClass = refuse(FakePlayerRef(), &classless);
    CHECK(noClass.stage == GroundRelicStage::NoClass);

    // A class that is not a number is no class either.
    const RValue stringClass = RValue::Struct({
        { "itemType", RValue(std::string("16")) },
        { "itemDefinitionStruct", RValue::Struct({ { "b", RValue(42) } }) },
    });
    CHECK(refuse(FakePlayerRef(), &stringClass).stage == GroundRelicStage::NoClass);

    // A relic class with no definition, a definition that is not a struct, a
    // definition with no id, and an id outside the relic range.
    const RValue noDefinition = RValue::Struct({ { "itemType", RValue(16) } });
    const RValue numberDefinition = RValue::Struct({ { "itemType", RValue(16) }, { "itemDefinitionStruct", RValue(42) } });
    const RValue noId = RValue::Struct({
        { "itemType", RValue(16) }, { "itemDefinitionStruct", RValue::Struct({ { "o", RValue(1) } }) },
    });
    const RValue idOutOfRange = RelicInstance(kRelicIdLimit, 1, 0);
    CHECK(refuse(FakePlayerRef(), &noDefinition).stage == GroundRelicStage::NoDefinition);
    CHECK(refuse(FakePlayerRef(), &numberDefinition).stage == GroundRelicStage::NoDefinition);
    CHECK(refuse(FakePlayerRef(), &noId).stage == GroundRelicStage::NoId);
    CHECK(refuse(FakePlayerRef(), &idOutOfRange).stage == GroundRelicStage::NoId);

    // Negative control for accepting a reference: an undefined value is not an
    // instance, even with relic fields on offer.
    const RValue relic = RelicInstance(42, 1, 0);
    const GroundRelicRead undefined = refuse(RValue(), &relic);
    CHECK(undefined.stage == GroundRelicStage::NoHandle);
    CHECK(refuse(RValue(42), &relic).stage == GroundRelicStage::NoHandle);

    std::printf("C++: ground_relic_refused ordinary=%s material=%s classless=%s undefined=%s\n",
                GroundRelicStageName(ordinary.stage), GroundRelicStageName(stack.stage),
                GroundRelicStageName(noClass.stage), GroundRelicStageName(undefined.stage));

    // No interface at all reads nothing.
    {
        GroundRelicRead read;
        CHECK(!ReadGroundRelic(nullptr, FakePlayerRef(), read));
        CHECK(read.stage == GroundRelicStage::NoHandle);
    }
}

// ---------------------------------------------------------------------------
// The three cases from origin's second review, printed for the Python side of
// tests/test_cpp_sdk.py to compare against scan_relic_levels() directly.
// ---------------------------------------------------------------------------

static void PrintOwned(const char* label, ControlledYYTK& yytk) {
    const auto owned = HeroSiege::Player::GetOwnedRelicLevels(&yytk, FakePlayer());
    std::printf("CASE %s", label);
    // Deterministic order: the map is unordered.
    for (int id = 0; id < HeroSiege::Player::kRelicIdLimit; ++id) {
        auto it = owned.find(id);
        if (it != owned.end()) std::printf(" %d=%d", it->first, it->second);
    }
    std::printf("\n");
}

static void TestCrossLanguageCases() {
    {
        ControlledYYTK yytk;
        yytk.instanceFields["relic_levels"] = RValue::Array({ RValue(0), RValue(0), RValue(10) });
        PrintOwned("relic_levels_numeric", yytk);
    }
    {
        ControlledYYTK yytk;
        yytk.instanceFields["inventory"] = RValue::Array({
            RValue::Struct({ { "b", RValue(42) }, { "cls", RValue(16) }, { "o", RValue(10) } }),
        });
        PrintOwned("inventory_cls_item", yytk);
    }
    {
        ControlledYYTK yytk;
        yytk.instanceFields["inventory"] = RValue::Array({ RValue(0), RValue(0), RValue(10) });
        PrintOwned("inventory_numeric_negative_control", yytk);
    }
    // #93: the item instance shape the game really produces, and its two
    // negative controls. Same fixtures as tests/test_relic_identification.py.
    {
        // Prints "CASE equipped_slot_relic_instance 109=10".
        ControlledYYTK yytk;
        yytk.instanceFields["equippedItems"] = RValue::Array({ RelicInstance(109, 10, 14) });
        PrintOwned("equipped_slot_relic_instance", yytk);
    }
    {
        // Prints "CASE equipped_ordinary_instance_negative_control" with no relic.
        ControlledYYTK yytk;
        yytk.instanceFields["equippedItems"] = RValue::Array({ OrdinaryGloveInstance() });
        PrintOwned("equipped_ordinary_instance_negative_control", yytk);
    }
    {
        // Prints "CASE material_stack_instance_negative_control" with no relic.
        ControlledYYTK yytk;
        yytk.instanceFields["inventory"] = RValue::Array({ MaterialStackInstance() });
        PrintOwned("material_stack_instance_negative_control", yytk);
    }
}

// ---------------------------------------------------------------------------
// The identification contract, printed so tests/test_cpp_sdk.py can assert the
// Python SDK declares exactly the same fields, limits and container names.
// ---------------------------------------------------------------------------

template <size_t N>
static void PrintFields(const char* label, const std::string_view (&fields)[N]) {
    std::printf("CONTRACT %s", label);
    for (const std::string_view field : fields) {
        std::printf(" %.*s", static_cast<int>(field.size()), field.data());
    }
    std::printf("\n");
}

static void PrintContract() {
    using namespace HeroSiege::Player;
    PrintFields("id_fields", kRelicIdFields);
    PrintFields("tier_fields", kRelicTierFields);
    PrintFields("level_fields", kRelicLevelFields);
    PrintFields("general_containers", kGeneralContainerFields);
    PrintFields("relic_containers", kRelicContainerFields);
    std::printf("CONTRACT relic_only_field %.*s\n",
                static_cast<int>(kRelicOnlyField.size()), kRelicOnlyField.data());
    std::printf("CONTRACT rarity_tier %d\n", kRelicRarityTier);
    std::printf("CONTRACT id_limit %d\n", kRelicIdLimit);
    std::printf("CONTRACT maxed_level %d\n", kMaxedRelicLevel);
    std::printf("CONTRACT max_scan_depth %d\n", kMaxScanDepth);
    std::printf("CONTRACT max_array_length %d\n", kMaxScannedArrayLength);
    std::printf("CONTRACT relic_item_class %d\n", kRelicItemClass);
    std::printf("CONTRACT instance_type_field %.*s\n",
                static_cast<int>(kItemInstanceTypeField.size()), kItemInstanceTypeField.data());
    std::printf("CONTRACT instance_definition_field %.*s\n",
                static_cast<int>(kItemInstanceDefinitionField.size()), kItemInstanceDefinitionField.data());
    std::printf("CONTRACT relic_slots");
    for (int slot = kFirstRelicSlot; slot <= kLastRelicSlot; ++slot) std::printf(" %d", slot);
    std::printf("\n");
}

// ---------------------------------------------------------------------------
// The item class, printed one member per line so tests/test_cpp_sdk.py can
// assert the compiled kItemTypes equals the Python ItemType member for member.
// ---------------------------------------------------------------------------

static void PrintItemTypes() {
    using namespace HeroSiege::Items;
    for (const auto& [name, value] : kItemTypes) {
        std::printf("ITEM_TYPE %.*s %d\n", static_cast<int>(name.size()), name.data(),
                    static_cast<int>(value));
    }
}

// ---------------------------------------------------------------------------
// Hook installer.
// ---------------------------------------------------------------------------

static RValue& OriginalScript(CInstance*, CInstance*, RValue& result, int, RValue**) {
    result = RValue(3.0);
    return result;
}

static RValue& HookScript(CInstance*, CInstance*, RValue& result, int, RValue**) {
    result = RValue(13.0);
    return result;
}

static RValue& TrampolineScript(CInstance*, CInstance*, RValue& result, int, RValue**) {
    result = RValue(7.0);
    return result;
}

static int g_detourCalls = 0;
static void* g_detourTarget = nullptr;
static void* g_detourDest = nullptr;

static bool DetourSucceeds(void*, const char*, void* target, void* detour, void** outTrampoline) {
    ++g_detourCalls;
    g_detourTarget = target;
    g_detourDest = detour;
    *outTrampoline = reinterpret_cast<void*>(&TrampolineScript);
    return true;
}

static bool DetourFails(void*, const char*, void*, void*, void**) {
    ++g_detourCalls;
    return false;
}

namespace {

struct ScriptTable {
    YYTK::CScriptFunctions functions{};
    YYTK::CScript script{};

    explicit ScriptTable(PFUNC_YYGMLScript entry) {
        functions.m_ScriptFunction = entry;
        script.m_Functions = &functions;
    }
};

} // namespace

static void TestHookInstaller() {
    using namespace HeroSiege::Hooks;

    Aurie::AurieModule selfModule;
    void* thisModule = static_cast<void*>(GetModuleHandleA(nullptr));

    // 1. First install: native interception, original becomes the trampoline,
    //    table entry becomes the hook.
    {
        ScriptTable table(&OriginalScript);
        ControlledYYTK yytk;
        yytk.routines["gml_Script_DropRelic"] = &table.script;

        g_detourCalls = 0;
        PFUNC_YYGMLScript original = nullptr;
        ScriptHookOptions options;
        options.selfModule = &selfModule;
        options.hookId = "test_drop_relic";
        options.gameModuleBase = thisModule;
        options.detour = &DetourSucceeds;

        const auto result = InstallScriptHook(&yytk, "gml_Script_DropRelic", &HookScript, &original, options);

        std::printf("C++: first_install=%d kind_native=%d original_is_trampoline=%d table_is_hook=%d\n",
                    result.Installed() ? 1 : 0,
                    result.IsNative() ? 1 : 0,
                    original == &TrampolineScript ? 1 : 0,
                    table.functions.m_ScriptFunction == &HookScript ? 1 : 0);

        CHECK(result.Installed());
        CHECK(result.IsNative());
        CHECK_EQ(g_detourCalls, 1);
        CHECK(g_detourTarget == reinterpret_cast<void*>(&OriginalScript));
        CHECK(g_detourDest == reinterpret_cast<void*>(&HookScript));
        CHECK(original == &TrampolineScript);
        CHECK(table.functions.m_ScriptFunction == &HookScript);

        // 2. Repeat install must not capture our own hook as "the original".
        const auto repeat = InstallScriptHook(&yytk, "gml_Script_DropRelic", &HookScript, &original, options);

        std::printf("C++: repeat_install=%d original_points_to_hook=%d original_still_trampoline=%d\n",
                    repeat.Installed() ? 1 : 0,
                    original == &HookScript ? 1 : 0,
                    original == &TrampolineScript ? 1 : 0);

        CHECK(repeat.Installed());
        CHECK(repeat.kind == ScriptHookKind::AlreadyInstalled);
        CHECK(original != &HookScript);
        CHECK(original == &TrampolineScript);
        CHECK_EQ(g_detourCalls, 1);  // no second detour attempt
    }

    // 3. A failed detour falls back to table-only, and the original is still
    //    the game's function - never the hook.
    {
        ScriptTable table(&OriginalScript);
        ControlledYYTK yytk;
        yytk.routines["gml_Script_DropGold"] = &table.script;

        g_detourCalls = 0;
        PFUNC_YYGMLScript original = nullptr;
        ScriptHookOptions options;
        options.selfModule = &selfModule;
        options.hookId = "test_drop_gold";
        options.gameModuleBase = thisModule;
        options.detour = &DetourFails;

        const auto result = InstallScriptHook(&yytk, "gml_Script_DropGold", &HookScript, &original, options);

        CHECK(result.Installed());
        CHECK(result.kind == ScriptHookKind::TableOnly);
        CHECK(std::string(result.note).find("native detour") != std::string::npos);
        CHECK(original == &OriginalScript);
        CHECK(table.functions.m_ScriptFunction == &HookScript);

        // Repeat after a table-only install is still safe.
        const auto repeat = InstallScriptHook(&yytk, "gml_Script_DropGold", &HookScript, &original, options);
        CHECK(repeat.kind == ScriptHookKind::AlreadyInstalled);
        CHECK(original == &OriginalScript);
        CHECK(original != &HookScript);
    }

    // 4. The module guard: a table entry that is not executable code inside the
    //    given module is not ours to patch, and no detour is attempted.
    {
        auto* heapAddress = new int(0);
        ScriptTable table(reinterpret_cast<PFUNC_YYGMLScript>(heapAddress));
        ControlledYYTK yytk;
        yytk.routines["gml_Script_Foreign"] = &table.script;

        g_detourCalls = 0;
        PFUNC_YYGMLScript original = nullptr;
        ScriptHookOptions options;
        options.selfModule = &selfModule;
        options.hookId = "test_foreign";
        options.gameModuleBase = thisModule;
        options.detour = &DetourSucceeds;

        const auto result = InstallScriptHook(&yytk, "gml_Script_Foreign", &HookScript, &original, options);

        CHECK(result.kind == ScriptHookKind::TableOnly);
        CHECK(std::string(result.note).find("game module") != std::string::npos);
        CHECK_EQ(g_detourCalls, 0);
        CHECK(original == reinterpret_cast<PFUNC_YYGMLScript>(heapAddress));
        delete heapAddress;
    }

    // 5. Missing id or module: table-only, said plainly.
    {
        ScriptTable table(&OriginalScript);
        ControlledYYTK yytk;
        yytk.routines["gml_Script_NoId"] = &table.script;

        PFUNC_YYGMLScript original = nullptr;
        ScriptHookOptions options;
        options.selfModule = &selfModule;
        options.gameModuleBase = thisModule;
        options.detour = &DetourSucceeds;  // never reached: no hookId

        const auto result = InstallScriptHook(&yytk, "gml_Script_NoId", &HookScript, &original, options);
        CHECK(result.kind == ScriptHookKind::TableOnly);
        CHECK(std::string(result.note).find("hook id") != std::string::npos);
        CHECK(original == &OriginalScript);
    }

    // 6. A missing script fails rather than half-installing.
    {
        ControlledYYTK yytk;
        PFUNC_YYGMLScript original = nullptr;
        const auto result = InstallScriptHook(&yytk, "gml_Script_Absent", &HookScript, &original);
        CHECK(!result.Installed());
        CHECK(result.kind == ScriptHookKind::Failed);
        CHECK(original == nullptr);
    }

    // 7. The explicitly-named table-only helper still preserves the original
    //    across repeat installs.
    {
        ScriptTable table(&OriginalScript);
        ControlledYYTK yytk;
        yytk.routines["gml_Script_Research"] = &table.script;

        PFUNC_YYGMLScript original = nullptr;
        const auto first = InstallScriptHookTableOnly(&yytk, "gml_Script_Research", &HookScript, &original);
        CHECK(first.kind == ScriptHookKind::TableOnly);
        CHECK(original == &OriginalScript);

        const auto second = InstallScriptHookTableOnly(&yytk, "gml_Script_Research", &HookScript, &original);
        CHECK(second.kind == ScriptHookKind::TableOnly);
        CHECK(original == &OriginalScript);
        CHECK(original != &HookScript);
    }
}

int main() {
    TestRelicIdentification();
    TestEquippedSlots();
    TestRelicTab();
    TestGroundRelic();
    TestCrossLanguageCases();
    PrintContract();
    PrintItemTypes();
    TestHookInstaller();

    if (g_failures == 0) {
        std::printf("ALL C++ SDK CHECKS PASSED\n");
        return 0;
    }
    std::printf("%d C++ SDK CHECK(S) FAILED\n", g_failures);
    return 1;
}
