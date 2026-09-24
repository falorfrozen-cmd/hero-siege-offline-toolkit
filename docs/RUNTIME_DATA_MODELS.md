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
  "o": 10,            // Relic: upgrade level (1 to 10). Stackable item: stack count
  "level": 10,        // Explicit level property (relics: used interchangeably with 'o')
  "relicLevel": 10,   // Alternate relic level property in UI tooltips
  "itemStatStruct": { // Dynamic roll values, flat stats & proc bundles
    "1": 250,         // Stat ID 1 = Strength
    "116": 167,       // Stat ID 116 = Skill ID for "Chance When Striking"
    "117": 25,        // Stat ID 117 = Skill Level for proc
    "118": 15         // Stat ID 118 = Proc Chance %
  }
}
```

**`o` means two things, depending on the item.** On a relic it is the upgrade
level. On a stackable item, such as a socketable or a crafting material, it is the
stack count. That was measured live on 2026-09-23 for ForgePact issue #14
(`ForgePact/docs/crafting-materials-research.md`, `### Phase 1b results`).
Every observed move of Ol (Socketable tab, both ways) and Unstable Dust (bag to
Materials tab) between the stash's special tabs and the bag handed the game's own
routines an item whose `o` was the stack, or the part of the stack being moved;
the Materials-to-bag leg was not observed. It is also the `data.o` that `tools/stash_tab_counts.py` sums from
`stash.hss`, where a missing `o` counts as one. So identify the item first
(rarity tier 16 is a relic) and only then read `o` as one or the other; `o`
alone does not say which it is.

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

---

## 5. Stash Special Tabs & the Crafting Route

Source: ForgePact issue #14 (`ForgePact/docs/crafting-materials-research.md`,
"RD" below). Facts come from one or two launches per research session (RD
`### Phase 1f results` ran two, launches A and B), on representative cases
(one Materials-tab entry the bag stacks, one Socketable stack of 10), on the
Season 10 build of 2026-09-22..24. **M** marks a fact measured live; **R**
marks a static Ghidra reading, paraphrased in RD's own words per `AGENTS.md`
§ "Legal: Decompiled Output Never Reaches Any Origin" - never the decompiled
text itself.

### The stash map

The stash map lives on `Controller_obj` (`HeroSiege::Objects::GameObject`,
index `984`) as `stashInventoryMap`. M: a content search matched
`stashInventoryMap (reference)` against the map's own text, and `GetItemMap(9)`
returned the same map by name with self `Console_Save_obj` (RD `### Phase 1i
results`). R, a static reading, not measured: `GetItemMap` answers owner `0`
with `New_Inventory_Data_obj.localItemMap` and owner `9` with a `ds_map`
variable of `Controller_obj` (RD `### Phase 1h instrument`). The map's
`ds_map` index is per launch, so compare it as an index only, never as an
identity (RD `### Phase 1e results`, `### Phase 1f results`, `### Phase 1i
results`).

The first `GetItemMap(9)` call of a launch comes at the stash's first open
(RD `### Phase 1d results`, `### Phase 1e results`); by name before any open
it still returns the whole map, counts equal to the save file (RD `### Phase
1f results`). The game edits the map in place, following a hand move and
dropping the entry on a whole-stack move; a by-name `GridRemoveItem` alone
leaves the map entry behind (RD `### Phase 1e results`). Map keys read as
`0-0-<n>-<class>`; values are item structs.

### Where the special tabs' cells live

M: `stashMaterialTab` is a two-level array, and `stashSocketItemSlot` is an
array of rows, each a 1x1 cell array (RD `### Phase 1i results`); R: the
two-level array's axis order, `[x][y]`, is from the static reading below, not
itself probed live. A cell keeps its item's fingerprint in `nodeFingerprint`,
the same key the stash map uses (M, RD `### Phase 1i results`).

R, a static reading, not measured: these container names are not present in
`Hero_Siege.exe`; the runtime fills the slots the code reads them through
from `data.win` at run time, and no extractor currently produces them or
ties them to `Controller_obj`, so they were found live, by content search
(RD `### Phase 1h instrument`); a cell holds either an item struct or
GameMaker's own "no value" sentinel; `SaveStash` and `GridRemoveItem` both
read a cell's `nodeFingerprint`; the ordinary (non-special) tabs form one
`[tab][x][y]` array whose variable name has not been found (RD `### Phase
1h instrument`).

### The item

M: `GetItemFromFingerprint(<fingerprint>, 9)` with the stash closed, self
`Console_Save_obj`, returns the item struct (`itemType=real:14` for the
Materials case) (RD `### Phase 1i results`). `itemDefinitionStruct.b` is the
base item id (Unstable Dust `50`, Greater Unstable Dust `51`); § 2's `o` field
is the stack count on this item, as on any stackable item - see § 2, not
restated here. `hs-game-sdk`'s `ItemType.SOCKETABLE` = 15 names the
Socketable case's class; that value is cited, not itself measured here (RD
`### Phase 1e results`, `### Phase 1i results`).

### `SaveStash` and the save invariant

M: one `SaveStash` call at each stash close, self `Console_Save_obj`, no
argument (RD `### Phase 1e results`, `### Phase 1f results`). M: each by-name
`SaveStash` in Live 1i made one `CreateItemSaveStruct` call per kept-map
entry (1627/1626/1625; RD `### Phase 1i results`); the save-control window
counted 1993, not reconciled.

R, a static reading: for each anchor cell, `SaveStash` looks the fingerprint
up in map `9` and passes the result to `CreateItemSaveStruct` without
checking whether the lookup came back with GameMaker's own "no value"
sentinel (RD `### Phase 1h instrument`).

**Invariant, measured twice, in two launches:** after a take that removed the
map entry but left the stash cell in place, the game's own save at the next
stash close ended the game (RD `### Phase 1h results`). A complete by-name
take (map step and `GridRemoveItem` on the cell, in the same take) avoided
the fault: each by-name `SaveStash` after it returned with one
`CreateItemSaveStruct` call fewer, and the owner's own stash close afterward
kept the game running and wrote a file without the taken items - measured in
one launch (RD `### Phase 1i results`). A by-name `SaveStash` (self
`Console_Save_obj`, no argument, stash closed) returned but wrote no file in
that same launch, making 1627 `CreateItemSaveStruct` calls; a separate
save-control window - the owner's stash open, hand move and close, run
before any by-name call - counted 1993, a different window in scope, so the
gap between the two is not reconciled and may be the open and the move
rather than the by-name save itself - a gap RD tracks as its own open lead,
not restated here.

### The take calls

M, with the call shapes as supplied (RD `### Phase 1i results`):

- Stacked case: `InventoryGridCanAddToStack` → `InventoryGridAddToStack`
  (`success=true`) → `RemoveItemFromMap` on map `9` → `GridRemoveItem` on
  `Controller_obj.stashMaterialTab` (`true`).
- No-stack case: `InventoryGridCanAddToStack` returns undefined, then
  `GetItemPreferredGrid(1, item)` returns a struct with a `gridBits` member
  and a grid array, `GridAddItem` places the item in that grid
  (`success=true`), `ChangeItemOwner` reassigns it to the bag, then
  `GridRemoveItem` clears `Controller_obj.stashSocketItemSlot`'s cell
  (`true`).

`inventorySocketGrid` (on `New_Inventory_Data_obj`) holds the bag's
Socketable tab; that it is the same array `GetItemPreferredGrid` returns is a
match on shape only, not established as identity (RD `### Phase 1i
results`). R, a static reading: `GridAddItem`'s last two arguments are
optional and it touches no map; `GridRemoveItem` sets every matching cell to
undefined and returns `true` if it matched any (RD `### Phase 1h instrument`,
`### Phase 1i instrument`).

### The recipe amount and the craft route

R, a static reading: a recipe's input amounts are stored encrypted and
decoded by `PilipaliDecrypt`, then compared against a `CountInventoryItem`
count (RD `### Phase 1h instrument`). M: at the craft press, inside
`CraftFindRecipeItems`, `PilipaliDecrypt` returned the recipe's amount (5),
matching the owner's own figure, beside `CountInventoryItem`'s stock count
(155) (RD `### Phase 1i results`). `CraftFindRecipeItems` runs once at the
press and returns before `DoCraftResult` starts; `DoCraftResult` encloses the
consume and the production of a one-unit craft in a single call (RD
`### Phase 1g results`). A multi-unit craft was not observed.

### SDK names and the curated entry

`SaveStashFunc` and `LoadStashFunc` are present in every `hs-game-sdk`
binding (bare names, not `gml_Script_`-prefixed) - see RD `### Phase 1h rows`
for the indices; neither is a call target here. The container names above
(`stashInventoryMap`, `stashMaterialTab`, `stashSocketItemSlot`,
`nodeFingerprint`) are not present in `Hero_Siege.exe`; the runtime fills
them from `data.win`, and no extractor currently produces them or ties them
to `Controller_obj`, so they are recorded as hand-verified data in
`hs-game-sdk/curated/stash_containers.json`, checked against this section and
the SDK by `tests/test_curated_stash_containers.py`.
