# Runtime Data Models & Memory Cheat-Sheet (Season 10)

This document details reverse-engineered runtime memory structures, instance variables, container layouts, equipment slot indices, and manager tables for Hero Siege Season 10.

---

## 1. `Player_obj` Instance Variables & Slot Indices

The primary player entity in GameMaker is an instance of `GameObject::Player_obj` (object index `1440`).

### Equipment Slots Layout (`equippedItems` array)
The `equippedItems` array (or `inventory` equipped region) organizes items by numeric slot index:

| Slot Index | Equipment Type | Description |
|---|---|---|
| `0` | Helm | Head armor piece |
| `1` | Chestplate | Body armor piece |
| `2` | Boots | Footwear |
| `3` | Gloves | Hand armor |
| `4` | Belt | Waist gear |
| `5` | Amulet | Primary neck accessory |
| `6` | Ring 1 | Left finger ring |
| `7` | Ring 2 | Right finger ring |
| `8` | Main Hand | Primary weapon |
| `9` | Off Hand | Shield, quiver, or secondary weapon |
| `10` – `14` | Relics (`0`–`4`) | 5 active relic slots |
| `15` – `18` | Charms | Inventory charm slots |

### Player Runtime Stat Variables
* `synergy_stat_map`: GameMaker struct containing dynamic stat multipliers and calculated synergy bonuses.
* `talentStructMap`: Struct containing skill/talent allocation maps keyed by skill ID.
* `cur_stats`: Active combat statistics (Life, Mana, Physical Damage, Elemental Resistances).
* `p_gold` / `p_rubies`: Player currency counters.
* `inventory`: Primary inventory array containing serialized item structs or nested bag structs.
* `inventory_relic_tab` / `bags`: Extended bag containers.

### How the local player arrives: `VALUE_REF`, not `VALUE_OBJECT`

**The player handle this runner hands back is an instance reference — `VALUE_REF`,
kind 15 — not a struct.** `instance_find(Player_obj)` returns one (measured
2026-09-10), and `gml_Script_GetMyPlayer` does not resolve here at all, so the
reference is the normal case rather than the exotic one.

Every instance accessor takes it straight through — `variable_instance_get`,
`variable_instance_set`, `variable_instance_exists` — so code that reads player
variables needs no conversion. What it must not do is gate on
`m_Kind == VALUE_OBJECT` before starting: that check silently disables the whole
feature rather than failing loudly, and has now done so three times
(`orbpickup`, the relic filter's arming step, and the maxed-relic scan itself).
Use `HeroSiege::Player::IsInstanceHandle` (`player.hpp`), which accepts both
kinds, or accept both explicitly.

Note the contrast with the next section: *items* really are structs
(`VALUE_OBJECT`), and struct accessors do require that kind. The rule is
per-surface — an instance handle and an item struct are not interchangeable.

---

## 2. Item Definition & Runtime Struct (`itemDefinitionStruct`)

Items in Hero Siege exist in memory as GameMaker Structs (`VALUE_OBJECT`) with the following standardized properties:

```json
{
  "a": 104,           // Sprite index or base asset ID
  "b": 42,            // Item type ID / Relic ID / Base item category
  "c": 16,            // Item Rarity Tier (16 = Relic, 10 = Angelic, 8 = Satanic, 6 = Heroic)
  "j": 1,             // Item subtype / Class alignment
  "i": 100,           // Item quality / Item power level
  "s": 0,             // Sockets count / Socket metadata
  "p": 5,             // Star quality level (0 to 5)
  "o": 10,            // Relic upgrade level (1 to 10)
  "level": 10,        // Explicit level property (used interchangeably with 'o')
  "relicLevel": 10,   // Alternate relic level property in UI tooltips
  "itemStatStruct": { // Dynamic roll values, flat stats & proc bundles
    "1": 250,         // Stat ID 1 = Strength
    "116": 167,       // Stat ID 116 = Skill ID for "Chance When Striking"
    "117": 25,        // Stat ID 117 = Skill Level for proc
    "118": 15         // Stat ID 118 = Proc Chance %
  }
}
```

---

## 3. `Loot_Manager_obj` Drop Tables & Mechanics

Drop calculations in Season 10 run through `Loot_Manager_obj` (object index `2184`) and dedicated drop scripts:

### Two-Stage Drop Architecture
1. **Outer Gate (`LoadDrops`)**:
   - Evaluates whether a drop category (e.g. Dungeon Keys `12`, Relics `16`, Angelics `10`) is eligible to drop in the current room/difficulty.
   - Example: Angelic drops require Buff `332` (`buff_angelic_chance`).
2. **Inner Roll (`gml_Script_cpr_irandom` against `droprate.base`)**:
   - Iterates through the item repository table for the category.
   - Evaluates `cpr_irandom(droprate.base) < threshold`.
   - Modifying `droprate.base` to an extreme value (e.g., `1e18`) effectively excludes an item from the drop pool without corrupting repository indices.

---

## 4. Hooking Best Practices with `hs-game-sdk`

### Declarative Script Hooking (C++)
```cpp
#include <hs_game_sdk/hs_game_sdk.hpp>

static PFUNC_YYGMLScript g_Orig_DropRelic = nullptr;

static RValue& Hook_DropRelic(CInstance* S, CInstance* O, RValue& R, int argc, RValue** A) {
    // 1. Inspect player state
    RValue player;
    if (HeroSiege::Player::ResolveLocalPlayer(g_Yytk, player)) {
        auto maxedRelics = HeroSiege::Player::GetMaxedRelicIds(g_Yytk, player);
        // Exclude maxed relics from drop chances...
    }
    // 2. Call trampoline
    return g_Orig_DropRelic ? g_Orig_DropRelic(S, O, R, argc, A) : R;
}

void RegisterHooks(YYTKInterface* yytk, Aurie::AurieModule* self) {
    // selfModule + hookId are what let the installer add an inline detour on top
    // of the script-table swap. Without both it falls back to table-only, and
    // the calls compiled GML makes directly into the function bypass the hook -
    // so check the result instead of assuming success.
    HeroSiege::Hooks::ScriptHookOptions options;
    options.selfModule = self;
    options.hookId = "example_drop_relic";

    const auto result = HS_INSTALL_SCRIPT_HOOK(
        yytk, HeroSiege::Scripts::gml_Script_DropRelic, Hook_DropRelic, g_Orig_DropRelic, options);
    if (!result.IsNative()) {
        // Log it: result.note says why, e.g. "table entry is not executable code
        // inside the game module".
    }
}
```

`g_Orig_DropRelic` must be **static and zero-initialised**: the installer uses
`*outOriginalFunc == nullptr` to tell a first install from a repeat one, which is
what makes installing the same hook from two call sites safe. On a repeat it
returns `AlreadyInstalled` and leaves the saved original alone, so forwarding
through it can never re-enter the hook. See
[`docs/submodules/hs-game-sdk/instructions.md`](submodules/hs-game-sdk/instructions.md)
for the full semantics.
