# Runtime Data Models & Memory Cheat-Sheet (Season 10)

This document details reverse-engineered runtime memory structures, instance variables, container layouts, equipment slot indices, and manager tables for Hero Siege Season 10.

It is the shared record of what the game does, for every module. A mod's research
doc is where a measurement is argued out; the fact it established belongs here
(`AGENTS.md` § "Fold What a Mod Learned About the Game Into the Shared References").
Sections 5 onward were backfilled on 2026-09-24 from ForgePact's research docs
at the hub's pinned commit; each entry links to the section it came from, which
holds the argument, the controls and the dead ends.

**How to read an entry.** *Measured* means observed on a running game (the date
is the session's). *Static reading* means read from the game's compiled code in a
local decompiler and paraphrased here — no game code is quoted anywhere in this
repository (`AGENTS.md` § Legal). Anything neither measured nor read is left in
its research doc. Object and script **indices** come from `hs-game-sdk`, never
from a research note, because indices move between builds; `anon@N` closure
names move too (§5.3). A thing that was looked for and not seen is written as
"not observed", not as "does not happen".

Links into `../ForgePact/` resolve in a checkout with the submodule initialised
(`git submodule update --init ForgePact`).

---

## 1. `Player_obj` Instance Variables & Slot Indices

The primary player entity in GameMaker is an instance of `GameObject::Player_obj` (object index `3553` in the current SDK; this line said `1440` until 2026-09-24).

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

The local character's equipped items are held in the global
`global.equippedItems[global.mplr][0][slot]`, as **fingerprint strings**, not as
item structs on the player instance; each resolves to an item through the game's
own scripts (§2, §6.1).

**Measured on 2026-09-27** (ForgePact #93, Live 1, the offline character "Sorak"):

- `global.equippedItems` is an array of six per-player entries. Only index 1 was
  populated, and `global.mplr` read `real:1.000000`: the offline local character
  is player **1**, not 0. Every other entry held empty strings.
- `global.equippedItems[1][0]` is the worn gear, 18 strings long (indices 0-17).
  Each filled slot is a fingerprint shaped like a save key, `0-0-<stamp>-<class>`,
  whose suffix is that item's class, not the slot (the off hand at index 9 ended
  in `-7`). Slots 10-14 held five `…-16` strings, the five equipped relics, and
  15-17 were empty on this character.
- `global.equippedItems[1][1]` is a second 18-string array, with seven
  fingerprints in slots 0-8. What it holds was not established.
- The player instance has **no** `equippedItems` variable: reading it answered
  "no such variable".
- All five relic fingerprints resolved through `GetOnlinePlayerItemOwner` and
  `GetItemFromFingerprint` to item instances of class 16, and their definitions'
  `b`/`o` equalled the save's `equipped_items` entries (below) slot for slot.

A character save keeps the same items in its `[inventory]` JSON's
`equipped_items` dict, keyed by those same `0-0-<stamp>-<class>` strings, each
value `{"data": {...}}` with the slot in `g` (§2, read 2026-09-27).
[dev2 bug batch, #93](../ForgePact/docs/dev2-bug-batch-research.md#93-the-relic-filter-did-not-see-equipped-relics)

### Player Runtime Stat Variables
* `synergy_stat_map`: GameMaker struct containing dynamic stat multipliers and calculated synergy bonuses.
* `talentStructMap`: Struct containing skill/talent allocation maps keyed by skill ID.
* `cur_stats`: Active combat statistics (Life, Mana, Physical Damage, Elemental Resistances).
* `p_gold` / `p_rubies`: Player currency counters.
* `inventory`: Primary inventory array containing serialized item structs or nested bag structs.
* `inventory_relic_tab` / `bags`: Extended bag containers. `inventory_relic_tab` is the name of the relic tab in a save file (`inventory_order_<slot>.hss`); in memory the relic tab is `Controller_obj.inventoryData[key - 1].inventoryRelicGrid` (§1, "The relic tab").

### How the local player arrives: `VALUE_REF`, not `VALUE_OBJECT`

**The player handle this runner hands back is an instance reference — `VALUE_REF`,
kind 15 — not a struct.** `instance_find(Player_obj)` returns one (measured
2026-09-10), and `gml_Script_GetMyPlayer` does not hand back a struct either
(2026-09-10), so the reference is the normal case rather than the exotic one.
`GetMyPlayer` does find the player once a character is loaded: with `orbpickup`
armed, its status read `none` at the main menu and on the save-slot screen and
`player via GetMyPlayer` on the first read after Play (measured 2026-09-21,
[character-select C-1.16](../ForgePact/docs/character-select-research.md#results)).
This paragraph said it "does not resolve here at all" until 2026-09-24.

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
  "c": 0,             // Repository flag: 0 normal, 1 unique (§13.10). Not a rarity and not the class: a relic's c is 0 (below); class = save key suffix / instance itemType (§16.3)
  "j": 1,             // Item subtype / Class alignment
  "i": 100,           // Item quality / Item power level
  "s": 0,             // Sockets count / Socket metadata
  "p": 5,             // Star quality level (0 to 5)
  "o": 10,            // Relic: upgrade level (1 to 10). Stackable item: stack count
  "level": 10,        // Explicit level property (relics: used interchangeably with 'o')
  "itemStatStruct": { // Dynamic roll values, flat stats & proc bundles
    "1": 250,         // Stat ID 1 = Strength
    "116": 167,       // Stat ID 116 = Skill ID for "Chance When Striking"
    "117": 25,        // Stat ID 117 = Skill Level for proc
    "118": 15         // Stat ID 118 = Proc Chance %
  }
}
```

**A game relic's definition carries none of the tier fields.** Read from a
character save on 2026-09-27 (ForgePact #93): a save's `[inventory]` JSON has an
`equipped_items` dict keyed `0-0-<stamp>-<class>`, whose trailing number is the
item class (`ItemType`, 16 = relic), and each value is `{"data": {...}}`. For a
relic, `g` is the equip slot (10-14), `o` the level, `b` the relic id, and `c` is
**0** (1 on unique gear, so `c` is not a rarity tier there). The definition has no
`relicLevel`, `cls` or `itemType`. In memory the class is `itemType` on the item
**instance**, beside its `itemDefinitionStruct`. So a relic is identified by:

- **the item instance**: a struct carrying `itemType` and `itemDefinitionStruct`,
  where `itemType == 16`; the id and level are then read from the definition's
  `b` and `o`;
- **the save entry**: a dict key `x-y-<stamp>-<class>` whose class is 16, with id
  and level from its `data.b` and `data.o`.

`hs-game-sdk`'s relic scanners still accept `c == 16` and `relicLevel`, which this
section's sample used to show as the relic markers, so earlier fixtures and
callers behave the same, but neither has a measured match on a game item: treat
them as a compatibility rule, not as how relics are found. An
equipped unique glove (`itemType` 4, definition `{b:18, c:1, g:4}`) and a
material stack (`itemType` 14, `{b:51, o:99}`) are the negative controls beside
the relic instance in the SDK's shared cases
([hs-game-sdk guide](submodules/hs-game-sdk/instructions.md)).

**The equipped relic slots are fingerprint strings, not item structs.** The local
character's equipped items live in the global
`global.equippedItems[global.mplr][0][slot]` (§6.1), one fingerprint string per
slot, and slots 10-14 are the relics. An item is reached by resolving the string
through the game's own scripts, `GetOnlinePlayerItemOwner(mplr)` then
`GetItemFromFingerprint(fingerprint, owner)`, which returns the item instance
above. That route was measured for the helmet slot on 2026-09-23, and for the
relic slots 10-14 on 2026-09-27: all five resolved to relic instances whose ids
and levels matched the save (§1, **measured**).

**The relic tab is a grid indexed by relic id.** The relics a character owns but
does not wear sit in `Controller_obj.inventoryData[key - 1].inventoryRelicGrid`,
where `[relicId][0][0]` holds a grid node, `{nodeStartX, nodeStartY, nodeLocked,
nodeIsPermanent, nodeFingerprint}`, or undefined. The node's `nodeFingerprint` is
the owned copy's fingerprint. `key` is 1 when `global.onl` is 1, and the player row
(`global.mplr`) otherwise. The game's own `PickupRelic` and `RelicCheckAchievement`
hand that key to `GetProfileInventoryData`, which reads index `key - 1`, and the
latter walks ids 0..155 (**static reading**, Sep-17 build, 2026-09-30; hub
`docs/models/relic-pick-spec.md`). **Measured** 2026-09-30 (ForgePact #125 Live 1,
offline, `mplr` 1): `inventoryData` held one element, a reference to a
`New_Inventory_Data_obj` instance. Its grid had 156 cells, each `[[node]]` or
`[[undefined]]`, and all 100 of the save's tab relics resolved through the owner and
resolver above, with the levels the save holds. Read the variables instead of
calling `GetProfileInventoryData` (§9.4). A save stores the same tab as `inventory_relic_tab` in
`inventory_order_<slot>.hss`: keyed `x-y-<stamp>-16`, each `{data: {b, a, j, c}}`,
with `o` absent at level 1 (the owner's slot 1, 14 entries, **read** 2026-09-30).
The SDK reads the in-memory grid as `Player::ScanRelicTab` (C++), for ForgePact #125.

**What 10/10 means** (owner, ForgePact #124/#125). A relic always drops at level 1.
Each pickup of the same relic raises the owned copy's level by one, up to 10, so a
10/10 relic is one picked up ten times. `PickupRelic` finds the owned copy (relic
tab first, then the equipped slots) and raises it only while `o` is below 10, so a
relic at 10/10 cannot be picked up again (**static reading**). A dropped relic's own
level therefore says nothing; the check is the owned copy's `o`.

**`o` means two things, depending on the item.** On a relic it is the upgrade
level. On a stackable item, such as a socketable or a crafting material, it is the
stack count. That was measured live on 2026-09-23 for ForgePact issue #14
(`ForgePact/docs/crafting-materials-research.md`, `### Phase 1b results`).
Every observed move of Ol (Socketable tab, both ways) and Unstable Dust (bag to
Materials tab) between the stash's special tabs and the bag handed the game's own
routines an item whose `o` was the stack, or the part of the stack being moved;
the Materials-to-bag leg was not observed. It is also the `data.o` that `tools/stash_tab_counts.py` sums from
`stash.hss`, where a missing `o` counts as one. So identify the item first
(item class 16 is a relic, as above) and only then read `o` as one or the other; `o`
alone does not say which it is.

What the game itself puts on a finished item (the rolled rarity, the name, the
generated affixes) and why `itemDataHash` cannot identify one were measured on
7,628 items in §16. The rarity a tooltip names is `itemInfoStruct["27"]`
(§16.4), not the definition's `c`: a Common belt carries `c` 0 and rarity 1.

---

## 3. `Loot_Manager_obj` Drop Tables & Mechanics

Drop calculations in Season 10 run through `Loot_Manager_obj` (object index `2514` in the current SDK; this line said `2184` until 2026-09-24) and dedicated drop scripts.

Two different numberings meet here, and this section mixed them until
2026-09-24: a **drop type** is an index into `LoadDrops`' `chances` array
(12 = dungeon key, 16 = Angelic Key), and a **repository category** is the first
argument of `GetNormalRepoStruct` (12 = keys, 16 = relics, 10 = charms). Angelic
is a rarity tier, not either of them. Both tables are in §13 and in
`hs-game-sdk/curated/drop_types.json`.

### Two-Stage Drop Architecture
1. **Outer Gate (`LoadDrops`)**:
   - Evaluates whether a drop type (e.g. dungeon keys, type `12`) is eligible to drop in the current room/difficulty (§13.1).
   - Example: Angelic item drops require Buff `332` (`buff_angelic_chance`); without it the Angelic roll was not observed in 984 kills (§13.4).
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

## 5. The Runtime Itself: YYC, Names, Value Kinds

### 5.1 Compiled GML calls scripts directly

- This is a YYC build. `data.win` has no CODE or VARI chunk: every script and
  object event is native x86-64 inside the exe, and instance-variable names are
  not in the STRG string pool (0 hits in 80,318 strings). **Measured.**
  [pet-quest research, Native decompilation](../ForgePact/docs/pet-quest-collector-research.md#native-decompilation-ghidra)
- One compiled script calls another, and an object event, through a native call
  fixed at compile time; the script table is never read on that path. A
  script-table swap therefore sees none of those calls: a native detour on
  `CheckPlayerInteraction` counted 3840 calls while the table hook counted 0.
  **Measured 2026-09-11.** The shipped gameplay scripts `StatMovementSpeed`,
  `StatAttackSpeed`, `DropRelic`, `DropMonsterGold` and `DropGold` (12 direct
  callers) are reached the same way (**static reading**, 2026-09-12). This is why
  `HookOneScript` installs an inline detour as well.
  [pet-quest C, The mechanism](../ForgePact/docs/pet-quest-collector-c-research.md#the-mechanism),
  [the hooks were blind — proven](../ForgePact/docs/pet-quest-collector-c-research.md#1-the-hooks-were-blind--proven-not-argued),
  [prove-the-instrument](agents/prove-the-instrument.md)
- A bound method value is called through a function pointer stored in the method
  object, not through the script table (**static reading**; the live trace never
  touched the table). [pet-quest C, The mechanism](../ForgePact/docs/pet-quest-collector-c-research.md#the-mechanism)
- The game's internal integer-die helper returns a double and does not go through
  the builtin table, so hooks on the `random`/`irandom` builtins do not see the
  special-content rolls (**static reading**). `cpr_irandom` is the game's die: it
  answers "what number", not "which item".
  [S10 §5](../ForgePact/docs/S10-special-content-notes.md#5-faydalı-bulgular-s10-20260824),
  [angelic roll, Found and set aside](../ForgePact/docs/angelic-roll-hook-research.md#found-and-set-aside)
- `gDataProtected` is a global that the game reads constants through (an
  anti-tamper indirection) — for example the ceiling of the drop dice in §13.1
  (member `0xAF`). It is a variable, not an asset, so it is not an SDK constant.
  **Static reading.** [S10 §5](../ForgePact/docs/S10-special-content-notes.md#5-faydalı-bulgular-s10-20260824)

### 5.2 What resolves by name

- **Object event bodies are not in the named-routine table.** All 22
  `gml_Object_<Obj>_<Event>_<N>` names tried returned status 14 (not found);
  scripts and the closures split out of Create events do resolve. **Measured.**
  [pet-quest research §1](../ForgePact/docs/pet-quest-collector-research.md#1-checkplayerinteraction--call-frequency-arguments-self-context),
  [toggle skills, Session 1](../ForgePact/docs/toggle-skills-research.md#session-1-1)
- **Runtime script numbers are the SDK index plus 100000** (`GetMouseTarget` is
  #102419 at runtime and 2419 in the SDK). `script_get_name` over 100000–110000
  resolved all 6,254 script names, including the runtime-only `anon@` closures.
  **Measured 2026-09-11.**
  [pet-quest C, citrace symdump](../ForgePact/docs/pet-quest-collector-c-research.md#citrace-symdump--a-symbol-table-for-a-stripped-280-mb-binary)
- The builtin dispatcher table holds 2867 builtins in 24-byte entries (name,
  function, int32 argc); internal names are wrapped in `@@` (`@@array_get@@`).
  A builtin is called with (result, self, other, argc, args). **Measured** (table
  read) and **static reading** (call shape). No quest-, interact-, pickup- or
  loot-named builtin exists.
  [pet-quest C, dispatchdump](../ForgePact/docs/pet-quest-collector-c-research.md#citrace-dispatchdump--read-the-whole-table)
- The runtime exposes `script_execute`, `method_call`, `method_get_index`,
  `method_get_self` and `script_get_name`. **Measured.**
  [pet-quest C, C0.1](../ForgePact/docs/pet-quest-collector-c-research.md#c01--resolve-the-six-m_quest-methods)

### 5.3 `anon@N` closure names change with every game patch

A Create-event closure is named after its character position in that event's
source (`anon@6013@gml_Object_UI_Pause_obj_Create_0`), so any patch to the event
renames every closure after the edit. Names recorded on an older build return
"not found" on a newer one (measured on the prospect window, 2026-09-17; the
special-content closures, 2026-09-18). Resolve a closure through the method
value an instance carries (`m_*`, below) rather than by its `anon@` name, and
treat any `anon@N` in this document as that build's name.
[prospect window, Scripts](../ForgePact/docs/prospect-window-research.md#scripts),
[S10, Not (2026-09-18)](../ForgePact/docs/S10-special-content-notes.md#not-2026-09-18-anon-numaralari-bu-derlemeye-2026-09-03-ait)

The `m_*` names are instance variables holding method values; they are not
assets, so `hs-game-sdk` does not list them and cannot generate them. The ones
research has used: `m_Questpickup`, `m_QuestInteract`, `m_QuestActive`,
`m_QuestActivate`, `m_QuestDestructible`, `m_QuestUseKey`,
`m_LootGroundDeActiveStep` (§10); `m_SetInventoryLocalPlayer`, `m_Resize`,
`m_UpdateInventoryGrid`, `m_RefreshNode`, `m_MoveItemToGrid`, `m_DropItem`,
`m_StartInvDragging`, `m_SetPosition`, `m_MouseInGrid`, `m_MouseInAnyGrid`,
`m_BuyItemConfirmed` (§9); `m_EnemyStep`, `m_runEnemyBuffs`, `m_CorpseStep`
(§11); `m_activateMechanic`, `m_BattlefieldPortalEnter`, `m_ChaosTowerReset`
(§14).

### 5.4 Value kinds on this runner

The player-handle rule in §1 is one case of a wider pattern. **Measured**, each on
this runner:

| Read | Kind returned |
|---|---|
| `instance_find(obj, n)`, an instance's `id` | `VALUE_REF` (kind 15), "ref instance N" |
| `object_index` on an instance | `VALUE_REF`, not a plain number |
| `object_index` on a struct `self` | undefined |
| the `room` builtin | a room `VALUE_REF`, not a number; `variable_global_exists("room")` is false, so `variable_global_get("room")` answers undefined and converting that to a number raises the runner error `REAL argument incorrect type undefined` (one per call, measured 2026-10-02, ForgePact#144). Read it with `GetBuiltin("room", ...)`, name it with `room_get_name`; `room_width`/`room_height` are built-ins too |
| an array, string, struct, undefined or null converted to a number (`RValue::ToDouble`) | no number: the runner raises its own error and the call then fails, and a C++ `catch` that swallows the failure does not take back the runner's report. An array raises `REAL argument incorrect type array` (**measured**, #74 Live 3's capture, 2026-10-02); undefined raises `REAL argument incorrect type undefined` (**measured**, ForgePact#144, the `room` row above). For a string, a struct and null it is a **source reading**, not a measurement: the reading (which is also all that identifies the two) is that `ToDouble` is the runner's own `REAL_RValue`, which raises for every kind it cannot turn into a number; their error text has not been captured. That ForgePact's research scan over `Controller_obj`'s array variables raised one error per array or string element it converted (18 per scan) is an arithmetic fit on Live 2's and Live 3's counts, and the string elements' share of it rests on the fit alone. Live 4 cannot settle that share: ForgePact's gate (§13.4) refuses strings before converting them, so it can show only that the total stops rising, not that a string conversion raises. Live 4 (2026-10-02, **measured**) showed that it does stop: with the 15 arrays and 3 strings refused before any conversion, two scans left the total at 1 where each had added 18 before, so the scan's conversions are measured as the cause of the rise, and the strings' share of it is still the fit. Refuse a kind that can never be a number before converting it (ForgePact's `SigNeverAHandle`, ForgePact#74) |
| a ds container | "ref ds_map" / "ref ds_list" |
| an item | `VALUE_OBJECT` struct (§2) |
| a bound `m_*` method value | `VALUE_OBJECT` with object kind 0, not a script ref (§10) |
| a marker such as `skillAstroHeated` | bool in one state, real 0 in another (§7) |

An instance or object-asset reference keeps a tag in its upper 32 bits (an
object asset uses `1 << 24`) and the id or index in the lower 32; S10 instance
ids fall around 250k–300k (**measured**). The runner builtin `@@GetInstance@@`
turns a ref, real or integer id into the live instance as `VALUE_OBJECT`.
YYToolkit 4.0.1's `GetInstanceObject` walks the room list forward from the *last*
active instance, so a forward walk visits one instance and stops (4341 were
active) — **measured** by read-only memory inspection.
[prospect window, Results](../ForgePact/docs/prospect-window-research.md#results),
[character select, Results](../ForgePact/docs/character-select-research.md#results),
[toggle skills, Track A design](../ForgePact/docs/toggle-skills-research.md#track-a-design-d-n1),
[S10, YYTK v4 error](../ForgePact/docs/S10-special-content-notes.md#yytk-v4un-s10da-urettigi-olumcul-hata-kayda-gecti),
[Headhunter, room traversal](../ForgePact/docs/headhunter-dispatch-verification.md#follow-up-second-test-incompatible-sdk-room-traversal)

### 5.5 Builtins, measured

- `game_get_speed` and `fps` both read **144**; everything in this document that
  counts frames counts 144 per second. `get_timer` advances in real time.
- `instance_number` and `instance_find` on a parent object cover every
  descendant's instances; `instance_number` counts only active instances.
- `event_perform` returns `true` even when the object has no such event. On quest
  items (mouse 0/4/10/11, key press 70, step 0, other 10–15) and on
  `UI_Button_obj` (mouse 0/4/5/10, user 10/11/12) it changed nothing.
- `keyboard_key_press`/`keyboard_key_release` return undefined and set both
  `keyboard_check` and `keyboard_check_direct`, without window focus; a posted
  window message sets only `keyboard_check`.
- `window_get_width`/`window_get_height` are the client size;
  `window_get_fullscreen` reads 1 in fullscreen.
- A zero-width `draw_rectangle` still fills a visible sliver.

[toggle skills, Duration sweep](../ForgePact/docs/toggle-skills-research.md#duration-sweep-session-8-every-classs-timed-skill),
[pet-quest C, C0.3](../ForgePact/docs/pet-quest-collector-c-research.md#c03--event_perform-on-the-items-own-events),
[character select, Results](../ForgePact/docs/character-select-research.md#results),
[menu layout, Instrument](../ForgePact/docs/menu-layout-research.md#instrument)

### 5.6 Frame order

- `Controller_obj`'s Step runs `ActivateDeactivateProps` (or
  `LocalActivateDeactivateProps`) and then `EnemyStepHandleNew` every frame;
  `Menu_Controller_obj`'s Step runs `timer_system_update`, which drives every
  per-instance timer the game registers (**static reading**, confirmed on the
  2026-09-17 build).
  [population performance §2.2](../ForgePact/docs/population-performance-analysis.md#22-who-gets-a-step)
- Object Step events run **before** YYToolkit's `EVENT_FRAME`, which is dispatched
  from Present at the end of the frame. Work done at `EVENT_FRAME` is always one
  step late for anything a Step event decides (**measured**, 2026-09-12).
  [map reveal, frame-boundary check](../ForgePact/docs/map-reveal-research.md#why-a-frame-boundary-check-cannot-work-here-2026-09-12-second-round),
  [check-a-permission](agents/check-a-permission.md)
- GML builtins may only be called on the game thread; calls from another thread
  crashed. **Measured.** [S10 §2](../ForgePact/docs/S10-special-content-notes.md#2-çözüm--s9un-asıl-tekniği-spawnatplayer)

### 5.7 Calling the game's scripts from outside

- Most game scripts called "cold" — global `self`, no arguments — fault inside
  game code, because they dereference `self` and their arguments unchecked. The
  process survives; `GetQuestProgress` returns -1, `GetMouseTarget` faults.
  Supply the `self`, `other` and arguments the game's own caller does
  (`CallBuiltinEx("script_execute", …)`). **Measured 2026-09-11.**
  [pet-quest C, cold calls](../ForgePact/docs/pet-quest-collector-c-research.md#why-the-games-scripts-cannot-be-called-cold-measured-2026-09-11)
- Calling `GetQuestProgress` with a `UI_Button_obj` as `self` at the main menu
  throws. **Measured.** [character select, Results](../ForgePact/docs/character-select-research.md#results)
- The game's own "Unable to find any instance for object index" error (raised
  through `timer_system_update` from `Menu_Controller_obj`'s Create) is caught by
  the runner and is not fatal, and appears with YYToolkit's own hook removed. With
  YYToolkit alone, about 140 caught game errors appear in two minutes, nearly all
  one message. **Measured.**
  [S10, the fatal error is not ours](../ForgePact/docs/S10-special-content-notes.md#yytoolkitin-olumcul-hatasi-bizden-degil),
  [yytoolkit-provenance](agents/yytoolkit-provenance.md)
- Installing a `DropRelic` script hook while character selection is still running
  stalls the runner; install after a character has loaded. **Measured.**
  [ForgePact guide, Known Limitations](submodules/ForgePact/instructions.md#known-limitations--gaps)

### 5.8 Capacity limits

- The native protected-variable store holds **262,144** live records. When it is
  full, allocation returns -1, and enemy construction passes that handle on and
  faults while a creator builds a monster (Hero Siege 7.0.13, density 2).
  **Measured** from the crash dump. Its reset does not rewind the allocation
  cursor. [population capacity, Failure addressed](../ForgePact/docs/population-capacity.md#failure-addressed)
- Special content at 10× plateaued at 12–13.6k active instances and lived; 20×
  died at about 13.4k; density 5 with special content crashed. On room entry the
  active count spikes to 20–30k for a single frame and settles at 8–11k, so a
  one-frame count is not a load measure. **Measured** (26.08.2026).
  [S10, crash behaviour](../ForgePact/docs/S10-special-content-notes.md#cokme-davranisi---olculen-degerler--26082026)
- Globals: 3553 through `variable_instance_get_names(-5)`, 3555 through the
  YYToolkit enumerator (2026-09-17). `cpr_seed`, `current_frames`, `deltaSpd`
  and `repeatGravity` change every frame. **Measured.**
  [toggle skills, Session 2](../ForgePact/docs/toggle-skills-research.md#session-2-1)

### 5.9 The garbage collector

Read with `gc_is_enabled`, `gc_get_target_frame_time` and `gc_get_stats` at the
main menu on 2026-09-26 (`pe-6aaa6779-0cad4fc8`). All **measured**.

- The collector is on, with the default 100 µs frame target, in five generations.
  The menu holds about 577,600 objects, 482,474 of them in the oldest.
- A struct that native code builds by calling a game script, and then lets go,
  is collected like any other: after 20,000 items built one after another
  through `InitItemFromJson` (§16.2) and one `gc_collect`, the object count was
  back where it started (+20 in the generation that held them).
- `gc_collect` collects at the end of the frame, not in the call: read in the
  same frame nothing had changed; one frame later it had walked the heap, taking
  12.7 ms with about 578,000 objects and 31.7 ms with about 692,000.
- Memory the collector frees stays with the process. When 100,000-114,000 held
  objects were released and collected, private bytes stayed at their high. Private bytes
  therefore show the most the game has held, and never fall back after a burst.
- About 45-126 s after launch, whether or not anything else runs, the game's
  private bytes fall once by 240-370 MB (for example 3.15 → 2.78 GB) and stay there; brief
  dips before it, up to 133 MB, come back. Measure a change against the level
  after that fall.

[Item Truth memory research](../ForgePact/docs/item-truth-memory-research.md#measurements)

### 5.10 A variable-slot global names itself

**Static reading**, 2026-10-04 (ForgePact #160), in our own words.

- The runtime keeps each variable-slot global in a 16-byte table entry inside
  the executable. The first 8 bytes are a pointer to the variable's name, a
  NUL-terminated ASCII string; the next 8 bytes are the slot itself. So the
  little-endian pointer 8 bytes before a slot names that slot.
- These names are found in the executable's own data this way, not in
  `data.win`'s string pool, which holds no instance-variable names on this
  build (§5.1).
- #160 named `projEffect`, `maxScale`, `image_xscale`, `image_yscale` and
  `loadSettings` this way, in decompiled bodies that left those slots
  unnamed.
- Slot locations move with every game build, so name them per build, with
  the `slot-name`, `find-name` and `annotate` subcommands of
  `tools/decomp_index.py`, and keep no slot location in a tracked file.

[Decompile index and slot-name helpers](tools/decomp-index.md),
[skill sliders research](../ForgePact/docs/skill-sliders-research.md)

---

## 6. Player and Global State

### 6.1 `Player_obj`

- About 116 instance variables, and **no `playerNumber`**; the player's number is
  on its `myHealthBar` instance (`playerNumber` = 1). **Measured.**
  [toggle skills, Session 3](../ForgePact/docs/toggle-skills-research.md#session-3-1)
- `wasInCombat` (bool): false in town, true in a fight, recomputed within about
  14 frames even while the pause menu is open. `combatRefresh` (bool) moves with
  combat. **Neither is the gate that greys out Restart** (§8.4): holding
  `wasInCombat` false unlocked nothing. **Measured 2026-09-22.**
  [restart research, Results](../ForgePact/docs/restart-always-available-research.md#results)
- Quest-cast state: `questCastInstance`, `questCastItem`, `questCastText`,
  `questCastTime`, `totalQuestCastTime` (144); also `interacting`, `mouseTarget`,
  `itemPickupCooldown`, `lootPickedThisFrame`. Ordinary quest pickups do not use
  the cast fields. **Measured.**
  [pet-quest C, C0.4](../ForgePact/docs/pet-quest-collector-c-research.md#c04--dumps-of-the-objects-never-inspected)
- `playerEffect[182]` went from 0 to int64 2 on the first Soul Spurn cast and
  stayed there; its meaning is unknown. **Measured.**
  [toggle skills, Session 2](../ForgePact/docs/toggle-skills-research.md#session-2-1)
- Equipped items per player: `global.equippedItems[mplr][0][0]` is the helmet
  slot's **fingerprint string** (§9.3), resolved to an item through
  `GetOnlinePlayerItemOwner` and then `GetItemFromFingerprint`. A worn and a
  removed helmet were both recognised on the next reward. **Static reading**,
  **measured 2026-09-23.** This is the global, per-player form of §1's slot table.
  The relic slots 10-14 resolve the same way, **measured 2026-09-27** (§1).
  [miner's helmet, Runtime](../ForgePact/docs/miner-helmet-prototype.md#runtime)

### 6.2 Buffs

| Where | What it holds (measured) |
|---|---|
| `global.playerBuff[1][0]` | a 420-slot array indexed by buff id; the local player's side. An empty slot reads -4 (or undefined); a live one holds a `VALUE_REF` to a `Draw_Player_Buff_obj`. `playerBuff[0][0]` read all -4. |
| `global.activeBuffList[1][0]` | a list of the active buff ids (int64) |
| `global.__timer_list[2].instance.buffNameText` | the buff name table, 419 entries, beside `buffSprite`, `buffDrawTime`, `buffHide`, `buffDebuff` |

`Draw_Player_Buff_obj` variables: `buffType` (int64, equal to its slot),
`destroyTimer` (frames left, falling by one per frame — held constant by a
toggle-type buff), `host` (the player's `id`), `buffStack`, `buffTimer` (the icon
clock, not monotonic), `buffPermanent`, `playerNumber`, `buffStackHash`.

`BuffAdd` takes the player as argument 1 and the duration in frames as argument 4.
A natural expiry does **not** call `BuffRemove` — the slot simply empties;
switching Holy Form off does call it.

| Buff id | Buff | Starting `destroyTimer` |
|---|---|---|
| 1 | Berserk | 720 per hit, stacking to 8; a new instance each time it reappears |
| 9 | Defensive Shout | 14400, re-added in full about 180 times over 89 frames |
| 21 | Master Mechanic (Marksman) | 1500 (25 s at 60 fps), `host` = the player's `id`; measured 2026-10-01 on a test copy, ForgePact #122 |
| 22 | Agility | 3600 |
| 86 | Martyr (White Mage passive during life drain) | about 445–563 |
| 104 | Counter | 1036.8; held constant with Give No Quarter |
| 107 | Last Stand | 3600 |
| 140 / 141 | Holy Form / Unholy Form | held constant (141 by analogy with 140) |
| 332 | angelic drop chance (§3, §13.4) | — |

[toggle skills, Buff-carried countdown](../ForgePact/docs/toggle-skills-research.md#buff-carried-countdown-session-12),
[toggle skills, Toggle skill table](../ForgePact/docs/toggle-skills-research.md#toggle-skill-table)

### 6.3 Other globals

- `GetMouseTarget`, `PlayerGetMouseTarget`, `GetQuestHoverDescription`,
  `GetMouseDisabledTarget`, `CanISeeTarget`, `PlayerMouseAction`,
  `GetPlayerMouseDisabled`, `KeyboardMouseInput` and `RefreshMouseMove` exist as
  **globals holding bound method values** that point at the scripts of the same
  names. `global.hoverTooltip` = 1. `global.questDataRepo` and
  `global.questDailyOffline` are ds_maps. **Measured.**
  [pet-quest C, C0.5](../ForgePact/docs/pet-quest-collector-c-research.md#c05--the-hover-target-globals-resolved-and-called)
- `global.mySkills[3]` held the bound skill 240 in one session. **Measured.**
  [toggle skills, Session 2](../ForgePact/docs/toggle-skills-research.md#session-2-1)
- `Controller_obj.questlogDescription` is an array of strings. **Measured.**

---

## 7. Talents and Skill Effects

### 7.1 Talent data

- `global.talentStructMap` is a ds_map from numeric talent id to the talent's
  static definition struct, 817 ids. Fields include `abilityId` (string),
  `abilityAura` (bool), `abilityDuration` (seconds), `abilityCooldown` (seconds;
  0.25 means "no cooldown"), `abilityLength` and `abilityTags` (int array). It
  carries **no toggle flag and no level**. **Measured.**
- `abilityDuration` × 144 is the effect object's starting `destroyTimer`
  (30 s → 4320); gear and talents scale it (Blade Barrier 6 s → 1296). Many timed
  effects have `abilityDuration` 0. **Measured.**
- `global.subTalentMap` is an array of 6; **index 1** holds the local player's
  sub-talent levels, shaped `t<talentId>` → `s<NN>` → level. An unallocated node
  reads 0 with its key present. A base-form talent (Bushido) has no `t<id>` node.
  **Measured.** The `s<NN>` matches the NN in the sub-talent translation key.
  Toggle-granting nodes: Purgatory s12, Crescent Moon s11, Unstable Contamination
  s13, Give No Quarter s13, Knifehoarder s13, Endless Blizzard s11, Astroheated
  Shower s11.
- The game ships `translationsTalent.csv` (`talent_name_<abilityId>` /
  `talent_desc_<abilityId>`, 721 each) and `translationsSubTalent.csv`
  (`sub<Class><Skill><NN>` / `subDesc<Class><Skill><NN>`, NN 01–14), pipe
  separated, in `bin/`. Read from the game's files.
- Per-talent bodies are not separate scripts; they live in the 26 `Talents<Class>`
  scripts (SDK names).
- Talent ids used by the research: 240 Soul Spurn, 243 its crow chain, 252
  Healing Zone, 358 Lunar Orbit, 283 Crematus, 301 Counter, 377 Submerged Knives,
  430 Maelstrom of Frost, 224 Meteor Storm, 134 Bushido, 364/365 Holy/Unholy
  Form, 137 Blade Barrier, 334 Blizzard, 6 Defensive Shout, 18 Berserk, 307 Last
  Stand, 45 Agility, 49 Beacon, 54 Master Mechanic. Whether they survive a game
  build is not known.

[toggle skills, Toggle skill table](../ForgePact/docs/toggle-skills-research.md#toggle-skill-table),
[After session 6](../ForgePact/docs/toggle-skills-research.md#after-session-6),
[After session 12](../ForgePact/docs/toggle-skills-research.md#after-session-12),
[Base-form toggles](../ForgePact/docs/toggle-skills-research.md#base-form-toggles-the-labelled-sweep-of-both-translation-files),
[Duration sweep](../ForgePact/docs/toggle-skills-research.md#duration-sweep-session-8-every-classs-timed-skill)

### 7.2 The cast pipeline (measured)

1. One key press makes one `TalentUse` call, `self` = `Player_obj`, arguments
   (player ref, talent id, 1, false, true). A held key repeats it every 57 frames.
2. About **19 frames** later `TalentUseClass` runs, `self` = `Player_obj`: a0 =
   talent id, a4 = true, a5 = 0, a6 = a7 = -1. Inside it run the class body
   (`TalentsWhiteMage` etc., no arguments) and `GetTalentCooldown(id, 1)`.
3. A player cast makes two `TalentUseClass` calls; a chained sub-skill (Soul
   Spurn's crows, talent 243) comes in the same frame with a4 = false.
4. A **double-cast proc** is a `TalentUseClass` call with `self` =
   `Universal_Double_Cast_obj`, a4 = false and a6/a7 = world x/y, 36–56 frames
   after the player's cast, with no `TalentUse` before it and a
   `NetworkSendClientTalentUse` beside it. It can switch a toggle back off.
5. Nothing in the call trace marks a cast as a toggle: routines, arguments and
   spawned objects are the same for a toggled and a plain cast. **A toggle is on
   exactly while its effect instance exists.**
6. A zone change ends every toggle measured. Purgatory's life drain can end its
   toggle at low life without any `TalentUse`.

`CheckTalentUse` runs once per frame. Self-buffs are added inside the class's
own `TalentUseClass` call (Counter, Last Stand, Agility, Holy Form); Defensive
Shout and Berserk add theirs outside it.
[toggle skills, Session 1](../ForgePact/docs/toggle-skills-research.md#session-1-1),
[Session 3](../ForgePact/docs/toggle-skills-research.md#session-3-1),
[Session 5 rerun](../ForgePact/docs/toggle-skills-research.md#session-5-rerun-2026-09-20-white-mage-only)

### 7.3 Effect objects

- `destroyTimer` on effect objects counts frames and the object goes away at or
  below 0 (it can linger a few frames there); -1 means constant — no timer, or a
  held toggle. Objects under `Skill_Controller_obj` (Blizzard, Crematus, Meteor
  Storm controllers) have no readable `destroyTimer`. **Measured.**
- `isMyClient` (bool) is readable on `Player_Damage_Parent_obj` children (Soul
  Spurn AOE, Maelstrom, meteors, Bushido, Blade Barrier) but not on
  `Skill_Controller_obj` children or on the `Player_Ability_Parent_obj` objects
  measured. **Measured.**
- Toggle carriers (**measured**):

| Skill | What exists while toggled |
|---|---|
| Soul Spurn | one `White_Mage_Soul_Spurn_AOE_obj`; `purgatory` 0.09 (0 on a plain cast), `destroyTimer` held at -1 after its first 144 |
| Lunar Orbit | `Exo_Lunar_Orbit_Crescent_Moon_obj` (only while toggled) |
| Crematus | the controller's `skillContamination` is 0.035 (0 plain) |
| Submerged Knives | `…_Knifehoarder_obj` (only while toggled) |
| Maelstrom of Frost | `Prophet_Maelstrom_obj` with `destroyTimer` -1 (4320 plain) |
| Meteor Storm | the controller's `skillAstroHeated` is bool true (real 0 plain) |
| Bushido | 7 `Samurai_Bushido_obj`, `destroyTimer` -1, no buff |
| Counter, Holy/Unholy Form | only the buff (§6.2) |

- Starting timers: Healing Zone 1152, Blade Barrier 1296 (an on-hit passive adds
  about 28.8, capped at the start value), Arrow Turret 1152, Progenies 2880,
  Pickup Truck 576, Dissipating Tornado 432. Relic companions (`Honey_Bee_obj`,
  `Minisect_obj`, `Karp_Head_obj`, `Zeppelin_obj`) sit under the ability parent at
  a constant -1. **Measured.**
- The Marksman's Beacon (`Marksman_Beacon_obj`, talent 49) is a timed effect:
  its own `destroyTimer` started at **516** (8.6 s at 60 fps) on each of two
  clean casts and fell about one per frame. `instance_number` stayed 1 in both
  cleared windows and a recast replaced the live beacon (the fresh timer back
  at 516), so it is single instance; ownership is unreadable (no `isMyClient`),
  and its parent is `Player_Ability_Parent_obj`, not the sentry parent. Its
  talent reads `abilityDuration=0`, `abilityCooldown=10` and tags `[15,18,10]`
  — the tag the turrets, totems and hydra share. **Measured 2026-10-01**, on a
  test copy of the class (ForgePact #122).
  [ForgePact #122](../ForgePact/docs/toggle-skills-research.md#issue-122-2026-10-01-the-marksmans-beacon)
- Mana Orb (talent 253) is a **timed effect, not a toggle**: its object is
  `White_Mage_Mana_Orb_obj`, and `skillstate`'s `effect=` reader
  (`instance_number` of that object, resolved by name through
  `kSkillTimerNames`) counted 0 → 1 on a Q press at slot 0,3, then read 0
  again with no further press (last seen at 1 at 12:12:53Z, at 0 by
  12:13:06Z - a 13 s gap between those two reads, not the effect's lifetime
  from the press, which happened earlier still, so the true lifetime ran
  longer than 13 s by an amount live 4 did not measure), and 2 right after an
  immediate recast; why the recast read 2 instead of 1 is not established.
  **M (live 4, 2026-09-26).**
- This is the same `effect=` reader's **positive control on the player
  build**: `hs_skill_cast(key=81, slot="0,3")` moved only 0,3's and 1,13's
  (both `manaOrb`) `effect=` count in a full-bar read, every other slot
  unchanged. Live 3's poll reads had already shown 0,3 at 1 after a Q
  press, without a no-press control. Live 4 is the first read with a
  negative control (`no-press`) and the tool's own confirmation.
  **M (live 4, 2026-09-26).**
- Mana Orb's object, `White_Mage_Mana_Orb_obj` (**static reading**, 2026-09-27):
  its Create runs the parent's Create, then sets `destroyTimer` to three seconds
  of `game_get_speed()` (432 at 144), the orbit fields and `chosenOne`,
  `haulingManaWell`, `compactingPower` and `arcaneBreakChance` to 0, and the
  pulse timer from the game speed. Its Step orbits `host` when `orbitRadius` is
  above 0, and with `chosenOne` truthy sets the orb's position to `host`'s every
  frame, so the orb follows the player; the pulse it spawns
  (`White_Mage_Mana_Pulse_obj`) copies `chosenOne` and the other upgrade fields.
  Step never writes `destroyTimer`; the inherited parent step counts it down. The
  Chosen One sub-talent is node s12 of talent 253 (§7.1).
- With Chosen One allocated (**measured 2026-09-27**, ForgePact #83 Live 1):
  `chosenOne` read `bool:true` and `orbitRadius` 0 while the orb existed.
  `destroyTimer` read 4151.71 within 2 s of the cast and 1599.87 about 18 s
  later, about 142 frames per second: it spans the cast. The duration sweep saw
  it start at **5040** (35 s), not the Create's 432, so something lengthens it
  after the Create; which script does was not read. The sweep read its owner
  field as unreadable. The skill-timer rule never selected talent 253 (17 rule
  rows, none Mana Orb); the likely reason, an `abilityDuration` of 0 (§7.1), was
  not read for it. Without Chosen One: not observed (the cast was not
  confirmed).
  [dev2 bug batch, #83](../ForgePact/docs/dev2-bug-batch-research.md#83-mana-orb-showed-no-countdown-with-chosen-one)

[toggle skills, Toggle skill table](../ForgePact/docs/toggle-skills-research.md#toggle-skill-table),
[Duration sweep](../ForgePact/docs/toggle-skills-research.md#duration-sweep-session-8-every-classs-timed-skill),
[skill actions, Results](../ForgePact/docs/skill-actions-research.md#results)

### 7.4 The talent screen: who handles a click, and what an allocation changes

- M: the talent screen's and the bar's buttons are handled by **named
  activation scripts** the game wires to each button (`UiSetActivationFunc`),
  not by the buttons' own Create closures. Each ran once per hand action with
  the clicked button as `self` (2026-09-25): a talent allocation runs
  `UiATalentScreenTalent` (self the talent's `UI_Button_Talent_Player_obj`,
  other `UI_Talent_Screen_obj`, one empty-array argument); a sub-node
  allocation runs `UiAActivateSkillSubPoint` (self the node's
  `UI_Button_Subtalent_obj`, other `UI_Sub_Talents_obj`); opening a talent's
  sub-panel runs `UiAActivateSkillSpecialization` (self its
  `UI_Button_Sub_Skill_obj`, other the screen); a bind from the expanded bar
  runs `UiATalentChange` (self the popup's `UI_Talent_Button_obj`, other
  `UI_Hud_Talent_obj`) after `UiAActiveTalentSelect`; "Reset Skills" runs
  `UiATalentScreenResetTalents` (self the `UI_Button_Small_obj`) and its
  confirm dialog (`UI_Character_Reset_obj`) runs `ClearPersistSkill` with
  `a0=1`. Undoing a level or a node (right-click) runs the Create closures
  `UI_Button_Talent_Player_obj anon@23904` and `UI_Button_Subtalent_obj
  anon@2428` (the latter then `ClearPersistSkill`).
- M: the talent screen opens through **`UiAOpenTalents`**, self = other =
  `Profile_Manager_obj`, two arguments `1, 1`; plain `UiCreate` does not fire.
  Called by name with that shape it opens the screen as the key T does. T
  closes it; an open sub-panel closes only by its own `UI_Button_Close_obj`
  or with the screen.
- M: by name, with the button instance as self and the screen (or sub-panel)
  as other and **no arguments**, `UiATalentScreenTalent` and
  `UiAActivateSkillSubPoint` reproduced the game's own allocation:
  `global.mySkills` gained the talent's id (`[236]` → `[236,239]`) and
  `global.subTalentMap[1].t<id>` gained a node at 1. That is what an
  allocation visibly changes; only a first level (0 → 1) was measured. The
  talent buttons, sub-skill buttons and sub-panels each carry the talent's
  `talentId`; the sub-panel's nodes carry no name, and the first node listed
  for Shadow Bolt (a `Big` sprite) changed nothing when activated.
- M: two replays did **not** reproduce: a bind by name (the popup's buttons are
  destroyed when it closes, so the logged instance no longer exists), and a
  reset by name (both the reset button's script and the dialog's
  `ClearPersistSkill` dispatched and changed nothing, while the owner's click
  emptied `global.mySkills`). Not observed working, which is not "cannot work".
- Not observed: a **points reader**. No numeric `Player_obj` member named like
  a point count exists, and a whole-scope diff of the player across an
  allocation changed only animation and mouse members; the profile object was
  not walked. `ReturnTalentLevel` by name (self `Player_obj`, the id as `a0`)
  threw. The talent screen shows "Points Left: N" to the eye.
- R (the static reading that set the route): the allocation handlers hash the
  talent state and report the client on a mismatch, so a raw write to it is
  never a substitute for the game's own handler.
- A by-name main allocation and its sub-node **survive a stop, a relaunch and
  a save reload**: `global.mySkills` still held the allocated id and
  `global.subTalentMap[1]` still showed the node after `hs_stop_game`,
  `hs_launch` and `hs_select_character`; the bar had filled the newly learned
  talent's slot by itself. **M (live 3 W6, 2026-09-26).**
- The owner's own "Reset Skills" click (through the talent screen, confirmed)
  emptied both `global.mySkills` and the drawn bar: W4's own `hs_skills_status`
  reply reported `learned=[236]` and `darkOath` gone from the bar, and the raw
  `skillstate` frames right after it (live 3, lines 14705 and 14732) read 0,0
  and 0,3 as `talent=0`, not only the learned list shrinking - a separate
  reading from the Dark Oath bullet below, which records a different action
  (a mouse switch-off) later, in live 4. **M (live 3, frames 14705/14732,
  2026-09-26).**
- Dark Oath (an aura, talent 242) has no key of its own on the HUD (§8.3), and
  no key switch for it was found: the only way found to switch it off is to
  click its bar icon and choose the same aura again from the expanded skills
  popup - a mouse action, not a keyboard key - which also empties that bar
  slot, so the aura's own effect count could not be read afterwards. Every
  read of 0,0's `effect=` count, before and after that action, showed 0,
  while the owner's report of the action implies the aura was on going in;
  `effect=0` on `darkOath` is therefore an inference from that report, not
  evidence the reader can tell an armed aura from an unarmed one. **R,
  reported by the owner (live 4, 2026-09-26), verbatim: "only way to turn off
  aura is to click it and select the same aura from expanded skills
  selection. i did it just now."**

[skill actions, Results](../ForgePact/docs/skill-actions-research.md#results),
[skill actions, Decision](../ForgePact/docs/skill-actions-research.md#decision)

### 7.5 Skill Haste and All Skills: the stats and where the game reads them

Written for ForgePact#114 (hub #337); the mechanism, labelled claim by claim,
is [`docs/models/skill-stat-spec.md`](models/skill-stat-spec.md).

- **`ReturnSpecificStat(player, statId, ...)` is the stat dispatcher.** A switch
  on the stat id sends it to one `Stat*` script; the function fills in its own
  case table on first run. Ids: **2** `StatAllSkills`, **36** `StatMaxLife`,
  **37** `StatMaxMana`, **103** `StatSpellHaste`, **106** `StatFasterCastRate`.
  `StatSpellHaste` and `StatAllSkills` each have exactly one direct caller,
  `ReturnSpecificStat`. **Static reading.**
- **Both return a fresh array; element 0 is the total.** Each builds its result
  with `@@NewGMLArray@@` on every call (**static reading**). On the way out,
  `ReturnSpecificStat` does more arithmetic with elements 0 to 3 of an array
  result (**static reading, not fully read**). Skill Haste's usable total stops
  at 200 somewhere after `StatSpellHaste` returns (**measured**, below).
- **Skill Haste runs cooldowns down faster.** `Controller_obj`'s Step event walks
  the active cooldowns and, each step, lowers one's time left by
  `(1 + rate) × deltaSpd`. For a skill cooldown `rate` = Skill Haste (stat 103) ×
  0.005; entries of another kind take stat 105 × 0.01 instead, and cooldown id
  75 takes 0. The talent tooltip, the only other constant-103 read found,
  scales by the same 0.005. **Static reading.** `GetTalentCooldown`, which sets
  a cooldown's base time, does not read Skill Haste.
- **Measured** (ForgePact#114 Live 1, 2026-09-30, Suh, a Samurai with 40 Skill
  Haste from gear, Blade Barrier's 8 s cooldown cast from code by `TalentUse`):
  - The step read Skill Haste once per step (60 reads a second) while the
    cooldown ran, and never while no cooldown ran.
  - The cooldown ran for 392 and 397 steps with no bonus, 280 with +100, 265
    with +120, and 238 with +160, +200 and +300. That is base / (1 + total/200)
    with the total stopped at 200: totals of 240 and 340 took exactly as long as
    200.
  - [`hs-game-sdk/curated/skill_stat_measurements.json`](../hs-game-sdk/curated/skill_stat_measurements.json)
    holds the counts, checked by `tests/test_skill_stat_model.py`.
- **`ReturnTalentLevel` has no direct caller in this build.** Its body adds the
  bonuses it reads through `ReturnSpecificStat`, All Skills among them, only when
  its third argument is true and the allocated level is above 0, with no clamp
  (**static reading**). Calling it by name with only a talent id raises the
  runner error "I32 argument is undefined" (**measured**, `skillprobe state`,
  2026-09-30; the game carried on). Which of the many scripts that pass stat id 2
  to `ReturnSpecificStat` turn it into a skill's level is **not established**.
- **All Skills joins the level a cast uses** (**measured**, ForgePact#114 Live 1,
  2026-10-01, Suh). For Honor (talent 142, one point) adds buff type 42, whose
  `buffValue` was [137.8, 72.5, 0] with the character's own All Skills total of
  28, and [228, 120, 0] with 19 more added through `StatAllSkills`: the level
  (29, then 48) times [4.75, 2.5]. `ReportClient` was not called, and the save
  kept every field but `playtime`.
- **`StatAllSkills` can call `ReportClient`.** It compares one of the values its
  caller passes in against twice a global constant and reports the client when
  it is larger, inside the script, on the game's own numbers. `ReportClient`
  builds a state report (sha256, base64) and sends it through the online API
  (`ApiRequestRegion`, `reportSendPendingMap`). `CheatDetection`, which calls
  `ReportClient` from `Client_obj`'s Step, checks hashes (gold, experience, the
  crafting trades, mercenary talents), game speed and items, and reads neither
  stat. **Static reading.**

### 7.6 Projectile count, projectile speed and AoE size: the stats and where the game reads them

Written for ForgePact#160 (hub #408). The research, with every live check, is
[`ForgePact/docs/skill-sliders-research.md`](../ForgePact/docs/skill-sliders-research.md);
the mechanism, labelled claim by claim, is
[`docs/models/skill-sliders-spec.md`](models/skill-sliders-spec.md), and the
measurements are
[`hs-game-sdk/curated/skill_sliders_measurements.json`](../hs-game-sdk/curated/skill_sliders_measurements.json).
Measured on 2026-10-04 on Sorak, a White Mage, in town and in Outskirts of Inoya
(`Act_01_01`).

- **The stat ids.** `ReturnSpecificStat` sends id **554** to `StatAOESkillSize`
  (a four-element array, element 0 the total, no cap found), **191** to
  `StatExplosionAOE` and **196** to `StatAttackRangeMelee`, each its only direct
  caller found. The projectile-amount ids (**394**, **311**, **239**, **240**,
  **451**, **452**) and the projectile-speed ids (**74**, **75**) have no `Stat*`
  script; 74 and 75 have no case at all. **Static reading.** Under
  `LoadAllModifiers` the game reads 74 and 75 (0 on a character without that
  gear), and 560/559 are read inside `StatAOESkillSize`, 394/311 inside
  `ReturnExtraSpellProjectiles` (**measured**, `projprobe ids`).
- **Projectile count.** `ReturnExtraSpellProjectiles(player, x, base)` returns the
  adjusted total (`base` raised by stat 394 as a percent and floored, plus stat
  311); `ReturnExtraProjectilesRanged(player, x)` returns an extra count only
  (stat 239 plus chance-based bonuses from 451/452 and 240), which its caller adds
  to its base. They have 44 and 19 direct call sites in the `Talents<Class>`
  scripts. **Static reading.** On Shadow Bolt the total is the number of
  `White_Mage_Shadow_Bolt_obj` created: base 1 gave one bolt, and 2 added to the
  return gave three (**measured**). `ReturnExtraProjectilesRanged` was not observed
  live.
- **The modifier array.** `LoadAllModifiers` fills a 1,100-element modifier array
  (`projEffect` on the object that receives it). Elements **1084** (stat 74),
  **1085** (stat 75) and **1086** (AoE size) carry the three values. A White Mage
  talent calls `LoadAllModifiers` once, then `SetAllModifiersNew` on each object it
  creates, which copies the list into that object's `projEffect`; the Healing Zone's
  branch makes no such call. **Static reading**; with stat 554 at 50,
  `projEffect[1086]` read 0.5 on the Soul Spurn object (**measured**) and on a
  Mana Orb object (a supporting read; its check was left not-run), and 0 on the
  Healing Zone (**measured**).
- **Who applies the elements.** `LoadProjectileSettings` does, for
  `Projectile_Player_obj` (the class basic attack's object; its one direct caller
  is that object's event, gated on an instance flag). White Mage skill objects are
  parented under `Player_Damage_Parent_obj` or `Player_Ability_Parent_obj`, and an
  event of each parent applies the same arithmetic to its own instance. **Static
  reading.** No White Mage skill cast was observed calling
  `LoadProjectileSettings` (seven skills; the same instrument counted it from the
  mercenary in the same session).
- **Projectile speed.** Element 1085 scales `deltaSpeed` as a percent and element
  1084 adds a flat amount times `roomSpd`, both only while `deltaSpeed` is above 0
  (**static reading**). On Shadow Bolt (`deltaSpeed` 2.916667) stat 75 at 0.5 and
  50 gave ×1.005 and ×1.5 (so `1 + stat75 / 100`), and stat 74 at 0.5 and 50 added 5/12 of a unit per
  point (+0.208333, +20.833333). The `speed` built-in read `deltaSpeed` × the
  object's `deltaTimer` on all six reads, so `deltaSpeed` is what moves it
  (**measured**). The order the two combine in, and which one the item tooltip's
  "Projectile Speed" is, were not observed.
- **AoE size.** Element 1086, when above 0, is added to `maxScale` when that is
  non-zero and otherwise to both `image_xscale` and `image_yscale` (**static
  reading**). Soul Spurn's object (`maxScale` 0) went from 7.5 to 8.0 on both
  scales with stat 554 at 50, and stat 554 reached the array at 0.01 per point
  (**measured**). The Healing Zone draws itself at a fixed 1.5 whatever its
  `maxScale` (3) and does not grow (**static reading and measured**).
- **Other callers of the same scripts** (**measured**): `Mercenary_obj` calls
  `LoadAllModifiers` about every 97 frames while it fights, beside
  `LoadProjectileSettings` calls with `self=Projectile_Player_obj`; the double-cast
  proc `Universal_Double_Cast_obj` calls `ReturnExtraSpellProjectiles`,
  `StatAOESkillSize` and `LoadAllModifiers` itself; and many casts carry a second
  `ReturnExtraSpellProjectiles` call with a base of 6. A hook on these scripts
  sees all of them.
- **Added after the sliders shipped** (ForgePact 2.3.0's `skillslider`, two
  live sessions on 2026-10-04 on the same character, research doc
  `## Implementation live 1`; all **measured** unless labelled):
  - **The top of each range.** Adding 5 to `ReturnExtraSpellProjectiles`'
    return left 6 bolts from one Shadow Bolt cast; adding 100 to stat 75 under
    the player's `LoadAllModifiers` doubled a bolt's `deltaSpeed` (2.916667 to
    5.833333); adding 100 to stat 554 took Soul Spurn from 7.5 to 8.5. Each is
    the same per-point rule as at +2 and +50, so it holds linearly to there.
  - **A Shadow Bolt object may take element 1086 too.** One bolt read
    `image_xscale` 1.75 with stat 554 raised by 100 and one read 0.75 with
    nothing added: a supporting read (one each, outside any check), not a
    measurement.
  - **The Healing Zone grows in, then holds 1.5.** With stat 554 raised by 50,
    a read about a second after the cast gave `image_xscale` 0.333333 and the
    same instance read 1.5 a second later; both casts settled at 1.5. Its cast
    does call `StatAOESkillSize` with `self=Player_obj`. Not read with stat 554
    raised by 100.
  - **The Shadow Bolt count varies with nothing changed.** `instance_number` of
    `White_Mage_Shadow_Bolt_obj` after a single cast, with no ForgePact lever
    ever set in that launch, read 1, 1, 1, 1, 2, 3, 2, 1 over eight casts. So a
    single cast sometimes leaves 2 or 3 bolts; what makes the extra ones (a
    double cast, an item proc) was not read. A count alone cannot tell a
    lever's effect from this.
  - **`Player_obj` calls `LoadAllModifiers` with no cast.** Across a waypoint
    trip to `Act_01_01` and 60 s idle there, the player's own
    `LoadAllModifiers` ran five more times with no skill cast. What triggers it
    was not read.
  - **Other callers seen in a fight.** In 60 s in `Act_01_01` beside enemies
    and the mercenary, `LoadAllModifiers` was called 7 times by something
    other than `Player_obj` or `Universal_Double_Cast_obj`, the last of them
    `Mercenary_obj`; the hooks on `ReturnExtraSpellProjectiles`,
    `ReturnExtraProjectilesRanged` and `StatAOESkillSize` counted no call from
    any other object in that window. The enemies died within seconds, so an enemy's
    call to these scripts was not observed.

---

## 8. HUD, Menus and UI Nodes

### 8.1 UI nodes in general

- UI windows are created when opened and destroyed when closed, along with their
  child nodes; every open gets new instance ids (pause menu, prospect window).
- A node is identified by its **`uiNodeCallstack`** string — `PauseRestart`,
  `ChooseHeroSlot`, `CharacterPlay`, `ProspectGrid` — not by sprite or position
  (two main-menu buttons share both). `masterUi` and `parent` link a node to its
  window. `UiCreateNode`'s argument 2 is the node's object.
- A mouse press registers only if the button is held across frames: about 120 ms
  works, a down and up in the same frame is ignored.
- GUI space is not window space: windowed at a 1920×1080 client the GUI is
  2560×1368; fullscreen 2560×1440 it is 2560×1440. Absolute GUI y changes between
  modes; a button's fraction of the client area does not.

All **measured** (2026-09-21/22).
[restart research, Results](../ForgePact/docs/restart-always-available-research.md#results),
[character select, Results](../ForgePact/docs/character-select-research.md#results),
[menu layout, Results](../ForgePact/docs/menu-layout-research.md#results)

### 8.2 Main menu and character select

- Flow: `Main_Menu_rm` → *Play local* → `Chose_rm` (save slots, then the character
  panel, same room) → *PLAY* → `Town_01_rm`.
- Clicking a save-slot card loads that character's save inside `Chose_rm`,
  without a room change, and holds the frame thread for roughly 2.5-3.5 s:
  3.53 s measured in Live 2 of the ForgePact incident report (2026-10-02),
  2.84 s the worst in its Live 3. **Measured.** The rooms ForgePact's incident
  monitor treats as menus, where a gap of 3 s or more (a freeze) is treated
  as a load and not reported (a shorter gap stays under its FPS-drop rules), are `Init_rm`,
  `Game_Start_rm`, `Login_rm`, `Login_Valhalla_rm`, `Main_Menu_rm`,
  `Main_Menu_Valhalla_rm`, `Char_Select_rm` and `Chose_rm` (names from
  `hs-game-sdk`'s `HeroSiege::Rooms::GameRoom`); see
  [ForgePact/docs/incident-report.md](../ForgePact/docs/incident-report.md)
  (D17).
- The main menu has 13 `UI_Button_obj` (told apart by `text`), one
  `Menu_Controller_obj`, one `Profile_Manager_obj`, plus
  `UI_Button_Close_obj`, `UI_Button_Menu_DLC_obj`, `UI_Button_Language_obj` and
  `UI_Container_obj`. `Menu_Controller_obj.menuNav` = -1 and
  `gamepadCursorManager` = -4; arrow keys and Enter do not navigate it.
- `Chose_rm`: 48 `Choose_Parent_obj` save-slot cards, `slot` 1–48 numbered row by
  row, 24 per page in an 8×3 grid (the other page's 24 sit hidden at the same
  positions). A card carries `slotClassName`, `uiNodeCallstack` =
  `"ChooseHeroSlot"` and `clickActivate` (true). Clicking a card **creates** a
  `UI_Character_obj` panel with a `UI_Button_obj` whose `uiNodeCallstack` is
  `"CharacterPlay"`.
- `Player_Parent_obj` does not exist (`asset_get_index` fails).
- Loading a character and leaving from town changed at most `shop.ini` in the save
  folder, which holds `herosiege<N>.hss`, `inventory_order_<N>.hss` and
  `shop.ini`.

All **measured** (2026-09-21).
[character select, Results](../ForgePact/docs/character-select-research.md#results),
[menu layout, Results](../ForgePact/docs/menu-layout-research.md#results)

**Unused and deleted character slots.** A slot that never held a character is
not empty on disk: it holds the game's blank character, a 581-byte encoded file
that decodes to an `[inventory]` section with an empty inventory and
`[0] version="8.000000"`, byte-identical in every unused slot. Deleting a
character from character select does not restore that file or remove anything:
the slot's `herosiege<N>.hss`, `ether<N>.hss`, `incarnation<N>.hss` and
`inventory_order_<N>.hss` are each rewritten as a single NUL byte, all four
within a few milliseconds. **Measured** (35 unused slots and four deletes in one
save folder, 2026-09-08). Static reading of the offline branch of
`UiACharacterDeleteConfirm`: it calls `SaveLocalFile` once per file type with a
clearing flag. **Observed**: two emptied slots in that folder later held new
characters while their `ether` and `incarnation` files were still the NUL byte
from the delete, so the game itself treats an emptied slot as free. A tool that
decodes `herosiege<N>.hss` has to read a NUL-only file as an empty slot, not as a
damaged save.
[HS Save Editor guide, Unused and Deleted Slots](submodules/HSSaveEditor/instructions.md#5-unused-and-deleted-slots)

### 8.3 In-game HUD

- Each frame, with `self` = `Controller_obj`: `DrawHud` →
  `DrawHudAbilityButtons` → `DrawHudBuffs`, once each. The hotbar button art is
  painted after all three return, so drawing inside an icon from those points is
  covered. **Measured.**
- There is one `UI_Hud_Talent_obj`. `row0` is the drawn bar: an array of structs
  with `talentId`, `drawButton`, `hidden`, `navBboxX/Y/Width/Height` (GUI
  coordinates, fractional) and `refreshInfoTimer`; `row1` repeats the talents
  hidden. A skill's index in `row0` differs per character and can move. Its
  `playerSlot` behaves as a map with `bind_skill` and `subTalentMap` keys.
  **Measured.**
- M (2026-09-25): on a White Mage, `row0` has 13 elements - 0,0 draws beside
  the mana orb, 0,2 to 0,5 in the bottom-left row, 0,6 is the slot beside the
  potions - and `row1` (16) lists the owned skills; an empty slot's `talentId`
  is 0. An element also carries `abilityCooldown`, `auraSkill`, `slotNumber`,
  a `timer` that jitters every frame on every slot, and **`keyBindKey`, which
  reads -1 on every slot**: the key a slot casts with is not stored on the
  slot. The HUD draws each slot's key letter through getters at draw time
  (`GetSpecificKeyBind`, `GetSpecificKBKeyBind`, `GetSpecificGPKeyBind`; the
  one that fired, `GetPlayerInputBindings`, returns the whole 78-entry
  bindings table and names no slot). A per-slot key read by name is **not
  observed** (an empty slot draws no key, so the getter for it never ran).
  Q is measured as 0,3's key (`manaOrb`). On the research build the Q
  press's armed `TalentUse` carried `a1=253` (`manaOrb`) (live 2 K2, IPC
  line 11593). On the player build live 3's `skillstate` read 0,3's
  `effect=` going from 0 to 1 after a Q press while 0,0 stayed 0, and live
  4's `hs_skill_cast(key=81, slot="0,3")` confirmed it (2026-09-26). Slot
  0,0 (`darkOath`, an aura) shows no key on the HUD. E and R sit on 0,4
  (`healingZone`) and 0,5 (`soulSpurn`), read by eye only, never
  name-resolved.
  `hud.playerSlot.bind_skill` read `undefined`, and `playerSlot` itself is a
  ds_map (`ref ds_map`). A newly learned skill appears in `row1` by itself.
- `Hud_In_Combat_spr` is the HUD's in-combat icon. Read from the string table.
- **The current font right after `DrawHudBuffs` returns is not the same from
  frame to frame.** In ForgePact #31's Live procedure 3 (2026-10-04, player
  standing still in Pumpkin Cellar), a label drawn from the `DrawHudBuffs`
  hook read the font left current with `draw_get_font` on every draw: it
  answered font index 7 at both status reads, and across about 45 s it found
  a different font from the previous draw 54 times, while the GUI layer's
  size did not change once. So a draw made from that point inherits
  whichever font was left current, and one that does not set its own font
  every frame changes size on some frames (Live procedure 2 caught a label
  at about 72 % size on 2 single frames in 272). **Measured.** Which code
  leaves the other font current is **not established**: by a reading of
  ForgePact's own code (not a measurement), its draws that run earlier in
  the frame are meant to restore the font they set, but Headhunter's head
  labels restore it inside the same `try` that sets it, and the other
  ForgePact draws (pack markers, the tip draw guard) were not isolated
  live, so the switch is not shown to be the game's. `draw_get_font` can
  also answer unset, so a reading counts only beside a font index.

[toggle skills, Session 1](../ForgePact/docs/toggle-skills-research.md#session-1-1),
[Session 3](../ForgePact/docs/toggle-skills-research.md#session-3-1),
[Sprite look probe](../ForgePact/docs/toggle-skills-research.md#sprite-look-probe),
[skill actions, Results](../ForgePact/docs/skill-actions-research.md#results),
[dungeon chest, Live procedure 3](../ForgePact/docs/dungeon-chest-research.md#live-procedure-3)

### 8.4 Pause menu and the Restart gate

- The pause menu **does not pause the world** (`wasInCombat` keeps updating).
  `UI_Pause_obj` exists only while the menu is open, and each open rebuilds it:
  10 `UiCreateNode` calls for `UI_Button_obj` and one run of its Create closure.
- The Restart button is a `UI_Button_obj` with `uiNodeCallstack` =
  `"PauseRestart"` and `buttonDrawFunc` = `UiDrawIngameRestart`. **Its own
  `manualDisable` (bool) decides whether a press is refused**: setting it false
  let Restart through in combat. Its `enabled` also flips in combat but does not
  gate. The game rewrites both every Step, before its click check, so a write
  made during Draw has no effect.
- A refused press never reaches `UiAIngameRestart` (self = the button, one array
  argument). `UiDrawIngameRestart` runs every frame while the menu is open, with
  one argument that is false in town and in combat alike. `UiSetFocus` (self =
  `UI_Pause_obj`, argument 0 the hovered button) runs at Step time while the mouse
  is over a button. Resume is `UiACloseButton`.
- Keyboard navigation does not reach the pause-menu buttons. Training dummies in
  `Town_01_rm` put the player in combat.

All **measured 2026-09-22.**
[restart research, Results](../ForgePact/docs/restart-always-available-research.md#results),
[Decision](../ForgePact/docs/restart-always-available-research.md#decision)

### 8.5 Structure worth knowing before designing a UI feature

From the SDK hierarchy and names (**static**): the game has no time-scale, delta
or pause script among its 6,254 scripts; `UI_Parent_obj` has 199 descendants,
mostly screens that block play; `Enemy_Aggroable_obj` is the parent of exactly
`Player_obj`, `Mercenary_obj` and `Summon_Parent_obj`; there are 16
`UiActivate*` menu openers.
[menu pause §2](../ForgePact/docs/menu-pause-plan.md#2-the-constraints-that-shape-everything),
[§3.1](../ForgePact/docs/menu-pause-plan.md#31-the-actors-are-reachable-through-a-handful-of-parents)

### 8.6 In-game chat

- **A mod can add a chat line with `ChatAddServerMessage`**, called by name
  (`asset_get_index` of the short name, then `script_execute` through
  `CallBuiltinEx`) with the local `Player_obj` instance as `self` and one string
  argument. It returns `undefined` and shows the text bottom left as a red line
  prefixed `SERVER: ` (`SERVER: ForgePact chat test 1`). **Measured 2026-10-03**,
  one call, screenshot.
- **Inside it, the game calls `ChatAddMessage` with 15 arguments**: the sender
  string `"SERVER"`, the text, two reals, two int64s, two reals, a `[hh:mm]`
  time string and six `undefined`; then `IngameChatFeedAddLatest` with the
  player as `self` and two arguments (a reference and a bool). **Measured**
  (count-only hooks on both, same session). Whether `ChatAddMessage` called
  directly with another sender shows a line without the `SERVER:` prefix is
  **not established**.
- **Offline, the player cannot type in chat**: the chat window opens and closes,
  but no line can be sent, so the call the game makes for a typed line was not
  observed. One `Ingame_Chat_obj` exists in a loaded game; `UI_Ingame_Chat_obj`
  and `Chat_obj` were 0. **Measured.**
- **The online drop-announcement chain.** Static reading (2026-10-04, local
  decompile, our own words): a ground item's own announcement closure (§16.10)
  reads the item's rarity and, on a branch per rarity, calls
  `NetworkSendChatMessageIngame` with five arguments: a runtime-filled global
  value (not established what it holds), the real 18687, the item, a colour
  and the int64 3. Static reading: with that last argument 3, the text is
  `GetItemDropMessage(item)`, a localized line naming the item (through
  `GetLootName` and `GetLocalized`); the sender adds it locally through
  `ChatAddMessage` (15 arguments) and, inside a block whose condition was not
  read, sends it with `PacketSend`. Static reading: `GetRareDropAnnouncement(a,
  b, c)` answers true for `a` 7 (Angelic) or 10 (Unholy), and for a few
  material (`b` 14) and socketable (`b` 15) ids; Heroic (9) is decided by the
  closure's own branch, not there. Static reading: before each send the
  closure also loops over `Chat_obj` (`ChatSendServerMessage`) and over
  `Menu_Controller_obj` (`ReportClient`). Offline, `Chat_obj` was counted at 0
  (measured above), so the `ChatSendServerMessage` loop would find nothing,
  but ForgePact#17's census counted one `Menu_Controller_obj` (measured
  2026-10-04), so the `ReportClient` loop would. Static reading: the
  receiving side is `CA_chatIngame` → `ChatAddIngameMessageFiltered` →
  `ChatAddMessage`.
- **Offline, the game's own announcement was not observed to run.**
  **Measured** 2026-10-04 (ForgePact#17 Live procedure 1, count-only hooks on
  the closure and the chain): a placed Heroic item and about 450 natural
  drops left the closure, `GetRareDropAnnouncement`,
  `NetworkSendChatMessageIngame`, `PacketSend`, `ChatSendServerMessage`,
  `ReportClient`, `ChatAddIngameMessageFiltered` and `CA_chatIngame` at 0,
  and no line appeared. "Not observed offline", not "cannot run offline".
  Called by name from a mod, `NetworkSendChatMessageIngame` (the ground item
  as `self`, first argument `undefined` or the player reference, the item
  struct as the item) and `GetItemDropMessage(item)` (the local `Player_obj`
  as `self`) refused, and no `PacketSend` counted. Whether the closure is
  bound on an offline ground item is not established (§16.10).
- **A drop announcement a mod can show offline: `ChatAddServerMessage` with its
  own text.** **Measured** 2026-10-04 (ForgePact#17 Live procedures 1 and
  3): `<character> found <item name>` (the name from the item's
  `itemInfoStruct["28"]`, the character's from the player's `name`) shows as
  a red `SERVER: Sorak found Headhunter` line, one per call. ForgePact's Loot
  announcements switch (`lootann`) ships this route for Heroic, Angelic and
  Unholy items; in Live procedure 3 it announced placed items, held a
  Satanic one, held a bag drop, and announced one natural drop with Magic
  Find raised.

[dungeon chest, Chat route](../ForgePact/docs/dungeon-chest-research.md#chat-route),
[loot announcements, Static reading](../ForgePact/docs/loot-announcement-research.md#static-reading),
[loot announcements, Live procedure 3](../ForgePact/docs/loot-announcement-research.md#live-procedure-3)

---

## 9. Inventory Grids, Fingerprints and Prospecting

### 9.1 Grid nodes

- `UI_Inventory_Parent_obj` has ten child windows: Angelic_Upgrade, Craft,
  Incarnation_Socket, Inventory, Inventory_Trade, Mailbox_Message_Send,
  Market_Add_Item, Merchant, Prospect and Stash (each `UI_*_obj`).
- Each grid is a `UI_Inventory_Grid_obj`, named by `uiNodeCallstack`: with the
  prospect window open there are six — `PotionGrid` ×2, `InventoryGrid` (15×6),
  `InventoryCharmGrid`, `InventoryVaultActiveGrid0` and `ProspectGrid` (9×6,
  `gridName` "Prospectron RX9000"; the window's `prospectGrid` points back at it).
- Node variables: `nodeGridWidth`, `nodeGridHeight`; **`nodeGrid`**, an array of
  rows of cells (row-major); `nodeWidth`/`nodeHeight` (92.8 — the cell size, and
  writable); `navBboxWidth`/`navBboxHeight`; `gridScale`; `gridBackground` (a
  fixed image).
- A cell is **undefined** when empty and, when filled, a struct of five members:
  `nodeStartX`, `nodeStartY`, `nodeLocked`, `nodeIsPermanent`,
  `nodeFingerprint`. It holds no item and no count. A 2×3 item fills six cells.

All **measured** (2026-09-17/18).
[prospect window, Results](../ForgePact/docs/prospect-window-research.md#results),
[Stage C results](../ForgePact/docs/prospect-window-research.md#stage-c-results)

### 9.2 The grid invariant, and its crash

A grid node's Draw and Step loop `nodeGridWidth` × `nodeGridHeight` over
`nodeGrid`, and nothing rebuilds `nodeGrid` from those two numbers — not
`m_RefreshNode`, `m_SetPosition`, `m_MouseInGrid`, `m_MouseInAnyGrid`, `m_Resize`,
`m_UpdateInventoryGrid` or `m_SetInventoryLocalPlayer`. **So the width must never
exceed a row's length.** Writing 9 → 18 on an open ProspectGrid crashed within one
frame (index out of bounds in the node's Draw event, then APPCRASH
c0000005); writing it just before `m_SetInventoryLocalPlayer` ran crashed in
Step 0 the same way. `nodeGrid` becomes an array inside
`m_SetInventoryLocalPlayer`; the node is created, still sizeless, by the 41st of
the open's 42 `UiCreateNode` calls. **Measured.**
[prospect window, Results](../ForgePact/docs/prospect-window-research.md#results)

### 9.3 Fingerprints and items

- `GetItemFromFingerprint(fingerprint, 0)`, called with `self` = `other` = a grid
  node, returns the item as a struct carrying **`itemType`** and
  `itemDefinitionStruct` (§2). The game calls it every frame.
- `itemType` 14 is Material (`ItemType::Material`); ore is 14 as well.
- A fingerprint names one item instance: three ores of one type had three.
  Suffixes seen are `-14` on materials, `-0` on inventory items and `-3` on one
  type-3 item; whether the suffix is the item type is not established.

**Measured.**
[prospect window, Stage C results](../ForgePact/docs/prospect-window-research.md#stage-c-results),
[Stage D results](../ForgePact/docs/prospect-window-research.md#stage-d-results)

### 9.4 Profile getters

| Getter | Returns | Notes |
|---|---|---|
| `GetProfileInventoryData` | a `VALUE_REF`, the same for every caller | needs the window as `self`: called otherwise it threw twice and then crashed `Controller_obj` Step (`array_get` index -1) |
| `GetInventoryArray` | an array of 18 strings | ~12,900 calls from `Player_obj` at load |
| `GetPlayerItemOwner` | int64 0 | |
| `GetPlayerProfileObj` | an instance ref | |

**Measured 2026-09-18.** [prospect window, Results](../ForgePact/docs/prospect-window-research.md#results)

### 9.5 Persistence

Items left in the prospect grid are **lost** across a written save and relaunch;
closing and reopening without a save keeps them; a crash loses unsaved inventory
moves. Saving to the main menu rewrites `herosiege<N>.hss` and
`inventory_order_<N>.hss`. **Measured.** The game also has
`ValidateInventory`, `DetectInventoryModifications` and
`DetectInventoryDuplicates`; their behaviour is not measured.
[prospect window, Results](../ForgePact/docs/prospect-window-research.md#results),
[Stage B results](../ForgePact/docs/prospect-window-research.md#stage-b-results)

### 9.6 Prospecting

- The Prospect button (`UI_Button_Small_obj`) stores its handler in
  `activationFunc`, a method value whose `method_get_index` is
  `UiAProspectButton`'s index, and its arguments in `activationArgs` (an array
  holding one empty struct).
- The game calls `UiAProspectButton` with `self` = the button, `other` = the
  window and one argument, the array. `script_execute` with that shape prospects,
  with any array; the grid changes during the call.
- One press prospects everything in the grid. Output lands as one single-cell
  stack per material type, filling column 0 rows 0–5 then column 1, unmerged.
  Materials are never used as input. An ore only has a *chance* of giving
  materials. One type-3 2×3 item could not be prospected.

**Measured** (2026-09-18/19).
[prospect window, Stage B results](../ForgePact/docs/prospect-window-research.md#stage-b-results),
[Stage D results](../ForgePact/docs/prospect-window-research.md#stage-d-results)

### 9.7 Moving items between grids

- A click-in and a drag-in both call `m_MoveItemToGrid` on the target node; so
  does rearranging inside a grid. Click: `self` = target, `other` = source, no
  arguments, the target cell already filled on entry. Drag: `self` = `other` =
  target, four arguments (undefined, 0, 0, 0), cells filled after it returns.
- **Stack a material onto an existing stack** — all with `self` = `other` = the
  ProspectGrid node: `InventoryGridCanAddToStack(1, undefined, item)` returns the
  existing stack (truthy); `InventoryGridAddToStack(1, item)` returns
  `{tabNumber, x, y, tabType, success}`; `InvGridClearItemNode(cell, undefined)`
  empties the source cell. The material merges into the materials tab (drawn by
  `UiDrawInventoryMaterialTab`, not a grid node).
- **First material of its type:** `InventoryGridCanAddToStack` returns
  undefined; `GetItemPreferredGrid(1, item)` returns `{gridBits, grid}` with a
  6×15 array; `GridAddItem(grid, item, 0, undefined)` places it in the main bag.
- Called by name through `script_execute` with those shapes, both paths move the
  material. A drag (`m_StartInvDragging`) depends on held-drag state and cannot be
  called by name.

**Measured** (2026-09-18/19).
[prospect window, Stage C results](../ForgePact/docs/prospect-window-research.md#stage-c-results),
[Stage D results](../ForgePact/docs/prospect-window-research.md#stage-d-results)

### 9.8 Closures on the 2026-09-17 build

`UI_Prospect_obj`: `anon@1065` = `m_SetInventoryLocalPlayer`, `anon@2806` =
`m_Resize`, `anon@3657` = `m_UpdateInventoryGrid`. `UI_Inventory_Grid_obj`:
`anon@36159` = `m_RefreshNode`, `anon@15345` = `m_MoveItemToGrid`, `anon@8881` =
`m_DropItem`, `anon@34555` = `m_StartInvDragging`. Measured by resolving the live
method values; see §5.3 before using a number.

---

## 10. Quest Items, Input and Loot Pickup

### 10.1 How a quest item is credited (the shipped Pet Quest Collector route)

- **The call:** `self` = the quest item, `other` = the live `Loot_Manager_obj`,
  invoking the item's own `m_Questpickup` method value with one real argument
  (`1` on real collects; the game's call site also allows undefined), through
  `CallBuiltinEx("script_execute", …)`. The quest counter advanced. **Measured
  2026-09-11.**
- `m_Questpickup` calls `update_quest(questIndex, questObjectiveNumber,
  questValue)` (e.g. int64 1002, 0, 1), which leads to `QuestSaveUpdate` — the
  credit and the save happen inside the call. **Measured** (signature), **static
  reading** (the save link).
- It **removes the item itself**: the item is neither deactivated
  (`instance_activate_object` did not bring it back) nor destroyed through the
  `instance_destroy` builtin. The bare call plays no pickup effect and writes no
  inventory-log entry. **Measured.**
- The `m_Quest*` values are `VALUE_OBJECT` with object kind 0, not script
  references: the script-ref fields read null and `method_get_index` returns
  nothing, while the sibling `s_lootDrawData` resolves. **Measured.**

[pet-quest C, The collect, measured](../ForgePact/docs/pet-quest-collector-c-research.md#2-the-collect-measured),
[Third pass](../ForgePact/docs/pet-quest-collector-c-research.md#third-pass-the-first-build-of-this-did-not-collect),
[Fourth pass](../ForgePact/docs/pet-quest-collector-c-research.md#fourth-pass-script_execute--confirmed),
[never-call-resolved-address](agents/never-call-resolved-address.md#two-shipped-incidents)

### 10.2 The game's own pickup path

- On an F press the measured order is `m_LootGroundDeActiveStep` (self = item,
  other = `Loot_Manager_obj`, no arguments) → `keyboard_check_pressed(70)` → 1 →
  `m_Questpickup` → `update_quest`. **Measured.**
- The caller is a `Loot_Manager_obj` body, not `PlayerMouseAction`. It selects the
  item through loot focus (`lootBoxInFocus`, `playerLootTarget`, `lootInstance`),
  not the player's `mouseTarget`, checks `canPickup` is true and `lootType == 0`,
  and consumes F through `ClearSpecificInput`. **Static reading**; that it is the
  caller is **measured**.
- `PlayerMouseAction` has a separate branch for `Quest_Object_Parent_obj`
  descendants: it dispatches on `lootType` — 0 `m_Questpickup`, 1
  `m_QuestInteract`, 2 `m_QuestActive`, 4 `m_QuestActivate`, 5
  `m_QuestDestructible` — each with the player's `id`, while
  `activateQuestObjectWithMouse` is true only for the duration of that call.
  **Static reading**; not taken on the brick path.
- The proximity path runs from the item's own Step: for `lootType` 1/2/4/5 it
  hands `CheckPlayerInteraction` the bound method and `distanceForPickup`.
  `lootType` 0 has no proximity path. `CheckPlayerInteraction` is a generic range
  check shared by NPCs, piles, shrines and stones; it reads no input and runs from
  every interactable's Step, about 2,100 times a second in town. **Static
  reading**; frequency **measured**.

[pet-quest C, The real caller](../ForgePact/docs/pet-quest-collector-c-research.md#4-the-real-caller-read-after-the-fact),
[The mechanism (§6)](../ForgePact/docs/pet-quest-collector-c-research.md#6-the-mechanism),
[A second, simpler path](../ForgePact/docs/pet-quest-collector-c-research.md#8-a-second-simpler-path-that-does-not-apply-to-bricks)

### 10.3 Quest item variables (`Quest_Object_Parent_obj` family)

Measured on a brick: `questIndex` (int64 1002), `questObjectType` 23,
`questValue` 1, `questObjectiveNumber` 0, `canPickup` true, `lootType` int64 0,
`distanceForPickup` 0, `itemActive` true, `isActive` 0, `lootName` "Brick",
`deleteTimer` (counting down from about 33, so bricks despawn), about 59 in all.
The parent's Create sets the `lootType`/`canPickup`/`distanceForPickup` defaults
(**static reading**, matched live). `Quest_Act_01_Body_Part_obj` has
`questIndex` 1021 and collecting one collects nearby duplicates;
`Quest_Toy_Bear_obj` stays collectible after its quest completes; quest items
collect instantly.
[pet-quest C, C0.4](../ForgePact/docs/pet-quest-collector-c-research.md#c04--dumps-of-the-objects-never-inspected),
[pet-quest research §1](../ForgePact/docs/pet-quest-collector-research.md#1-checkplayerinteraction--call-frequency-arguments-self-context)

Two facts for anything that picks quest items one after another (**static
reading**, ForgePact's dev2 bug batch, 2026-09-27):

- `m_Questpickup` reads the objective's progress and its maximum before it
  updates the quest, so an item whose objective has just filled can be
  "collected" and stay on the ground. With many items on screen that is the
  likely case, not the rare one.
- The `Quest_Object_Parent_obj` family also holds static quest props that are
  never collected. An enumeration of the family capped per tick (ForgePact's
  pet read at most 64) can therefore stop before it reaches collectable items
  with a high index.

A selector that picks the nearest item with no memory of a failed one can
re-pick the same item after either failure; ForgePact's Pet Quest Collector
therefore holds a failed target back and walks the family with a cursor. Not
measured. (The owner has since said the report that prompted this is about
the game's own companion loot pickup, §10.6, not a quest-item selector; that
it acts through §10.6's mechanism is a static reading, not measured.)
[dev2 bug batch, the Pet Quest Collector's section](../ForgePact/docs/dev2-bug-batch-research.md),
[pet loot stuck](../ForgePact/docs/pet-loot-stuck-research.md)

On the 2026-09-11 build the closures were `m_QuestUseKey` `anon@1400`,
`m_QuestActivate` `@1584`, `m_QuestDestructible` `@2113`, `m_Questpickup`
`@2786`, `m_QuestInteract` `@3858`, `m_QuestActive` `@4737`,
`m_LootGroundDeActiveStep` `@5164` (§5.3).

### 10.4 Input (`Profile_Manager_obj`)

- `Profile_Manager_obj` is the input and profile layer; the interact key F is read
  there with `keyboard_check_pressed(70)`. Its variables include `inputState` (78
  entries, one per bind, resting at 1), `inputToGP`/`inputToKB` (78-entry remap
  arrays), `pressedArray`/`mousePressedArray` (3 slots), `keyBinds`,
  `gamePadEnabled` and `mouse_x_prev`/`mouse_y_prev`. **Measured.**
- A real F press flips `inputState[30]` and `[60]` from 1 to 0; writing them does
  nothing. `mouse_x_prev`/`mouse_y_prev` track the cursor in screen space and are
  overwritten by the device within 1–2 frames; `mouse_x`/`mouse_y` have no runtime
  handle at all. Input cannot be simulated by writing these. **Measured
  2026-09-10.**

[pet-quest B4, Phase 0 checklist](../ForgePact/docs/pet-quest-collector-b4-research.md#phase-0-checklist-status-plan-5)

### 10.5 Other objects

- `Quest_Manager_obj` holds only online community-quest plumbing (6 variables).
- Writing `Companion_obj`'s x/y (11 px a frame) moves the pet visibly.

**Measured.** [pet-quest C, C0.4](../ForgePact/docs/pet-quest-collector-c-research.md#c04--dumps-of-the-objects-never-inspected)

### 10.6 The companion's own loot pickup (`Companion_obj`)

Every entry here is a **Static reading** of the current build's compiled
`Companion_obj`, `Loot_Ground_obj` and `Coin_obj` events (2026-09-27) unless
marked measured. Object events have no script-table entry, so none of it can
be hooked by name. ForgePact #94 (the pet stays on one ground item it cannot
pick up, with lots of loot around) is, by the owner's report, this companion
pickup; that the pinning rule below is its cause is a static reading, not yet
measured (Live 1 did not reproduce it; Live 2 measured the stale-target shape
below instead). Its mod is `petunstick`.

- **Variables** (Create): `lootList` (a ds_list), `lootTarget` (-4 = none, an
  instance id after; written as a real), `lootTimer` (0), `lootDistance`
  (1500 px), `playerRange` (128 px), `seekSpeed` / `baseSpeed` / `deltaSpeed`
  (0 at Create; Alarm 0 sets the speeds from character data, values not read),
  `move`, `deltaTimer`. Begin Step sets the built-in `speed` to
  `deltaSpeed * deltaTimer`, so the engine moves the pet by whatever
  `deltaSpeed` the Step left.
- **Scan radius and centre:** while `lootList` is empty and `lootTimer` has run
  out, the Step lists `Loot_Ground_obj` instances within `lootDistance` of the
  **player** (not the pet), nearest first, then adds **every** `Coin_obj` in
  the same circle, unfiltered, and sets `lootTimer` to half a second of frames.
- **Type filter:** a ground item joins the list only when its item type is a
  tarot card, a socketable (except the affix-rolled socketable bases), a
  crafting material, a key or one specific consumable, **and** `itemActive` is
  true, **and** `itemCompanionTimer` is 0 or less, **and**
  `lootFilterVisible` is true.
- **Retarget rule:** a new `lootTarget` (the list's first entry) is chosen
  **only** when the current one no longer exists. Nothing replaces a target
  that still exists.
- **A reused instance id keeps a stale target "alive"** (**Measured**,
  2026-10-02, ForgePact #138): `instance_exists(lootTarget)` is the only
  validity check there is, so when the game frees a destroyed instance's id
  and re-mints it for whatever is created next, `lootTarget` starts naming a
  stranger that passes the check and is never replaced. Measured live: the
  pet's target named `Abyss_Jungle_Dead_Aztec_Skeleton_01_obj` (object 15, a
  child of `Visual_Parent_obj`; `itemType=undefined`, `visible=0`), and the
  pet travelled to it and ground at it (52-88 px, `move=true`,
  `deltaSpeed=21.9`, the travel speed) while the player walked thousands of
  pixels away; both captures came within seconds of a zone change. The pet's
  list only ever holds `Loot_Ground_obj` and `Coin_obj` descendants, so an id
  naming neither is stale by construction and dropping it cannot lose an
  item; this is what `petunstick`'s on-sight rule acts on
  ([Live 2](../ForgePact/docs/pet-loot-stuck-research.md#live-2-results-2026-10-02)).
- **Arrival rule and pickup radius:** within twice `deltaSpeed` of a ground
  item the pet runs `PickupLoot` (item as `self`) on every ground item within
  **144 px of the pet** that passes the filter; an item whose pickup succeeds
  is destroyed, and every one is taken out of `lootList` whether it succeeded
  or not. A coin target is moved onto the pet, and the pet's collision event
  credits it. Arrival does **not** reset `deltaSpeed`, so the pet overshoots
  and turns back each frame while a target survives.
- **`itemCompanionTimer`** (on `Loot_Ground_obj` only; `Coin_obj` has none):
  positive at Create, counted down by Alarm 9 in the game's frame units
  (0.3 s of frames every 0.3 s); the scan skips an item while it is above 0.
  The player's own pickup (`Loot_Manager_obj`, `playerLootTarget`) does not
  read it.
- **Consequence:** a ground item whose `PickupLoot` returns false (the script
  returns false for a gone instance, an `ItemCheckHash` rejection, or, offline,
  `AddToInventory` failing on a full grid or stack) stays on the ground, passes
  the next scan and keeps `lootTarget` for as long as it lies there. Which of
  these failures a player meets is not established.
- **The loot block's gate:** an unnamed helper, most likely "the pet's player
  is the local one and exists"; not established.

[pet loot stuck, Static reading](../ForgePact/docs/pet-loot-stuck-research.md#static-reading),
[Live 2 results](../ForgePact/docs/pet-loot-stuck-research.md#live-2-results-2026-10-02),
[Not established](../ForgePact/docs/pet-loot-stuck-research.md#not-established)

### 10.7 Ground relics and the loot pickup

Every entry here is a **Static reading** of the Sep-17 build's compiled
scripts (2026-10-02, ForgePact #124), in our own words, unless marked
otherwise. ForgePact #124's Live 1 (2026-10-02, research build, offline,
relics placed by the research command `forcerelic`) checked the call shape
and the ground-relic read on the running game; what it confirmed is marked
**Measured** below, and the rest keeps its label. Variable names were
recovered from the binary's own name-slot table, which has matched every live
read it was checked against.

- **A dropped relic is a `Loot_Ground_obj`**, item class 16, placed by
  `LootGroundCreate` ([relic pick spec](models/relic-pick-spec.md)). It is not
  in the `Quest_Object_Parent_obj` family and carries no `m_Questpickup`, so
  the quest-item route (§10.1) does not apply to it. **Static reading.**
- **Where the class and the id live.** The ground item's constructor
  (registered by `LootGroundCreateFuncs`) stores a fresh item-instance struct
  in the instance's `itemInstance` variable. The class is
  `itemInstance.itemType`, the definition is
  `itemInstance.itemDefinitionStruct`, and that definition's `b` is the relic
  id. `itemActive`, `lootFilterVisible`, `itemCompanionTimer`, `isPlayerDrop`
  and `itemIsLocal` are variables of the ground instance itself. Both readers
  seen (the companion's Step and the ground item's own Create-defined
  function) take the class through `itemInstance`. Whether the instance also
  carries a top-level `itemType` copy is not established (`LootGroundInit`
  was not read). **Static reading.** **Measured** (#124 Live 1): on 42 ground
  relics read at once, `itemInstance` held a struct whose `itemType` was 16
  and whose `itemDefinitionStruct.b` was the relic id, and the instance
  carried `itemActive`. The other names here are still the reading.
- **`itemActive` comes on after placement.** A relic read straight after
  `LootGroundCreateFromItem` placed it showed `itemActive` 0 (two relics);
  every relic read after the next 45 s showed 1. When it turns on was not
  measured. **Measured.**
- **`isRelic`** is set true by that Create-defined function while the item is
  visible and its class is 16; whether every ground relic carries it, and
  from when, is not established, so it is not a positive signal for "this is a
  relic". **Static reading.**
- **`LootGroundRelicStep` is an animation step, not a pickup.** The same
  function calls it for a relic each update; it nudges two numeric members of
  the ground item by 0.005 per delta frame while flipping a direction flag:
  the relic's floating motion. The two member names did not resolve. There is
  no walk-over pickup for relics; §18.6 holds for them too. **Static
  reading.**
- **`PickupLoot` is the one pickup script for every ground item.** Its direct
  callers are `CA_playerItemPickupAccept` (network), the `Loot_Manager_obj`
  pickup closure (the player's own pickup, §10.2), `Companion_obj`'s Step
  (§10.6) and an event of an automated-player object that was not identified.
  `self` is the ground item; `other` is never read by the script, only passed
  on as `other` to what it calls. Every direct call site passes `argc` 5:
  1. the player index `global.mplr`;
  2. the item struct, the ground item's `itemInstance` (an undefined or zero
     `itemType` returns false at once);
  3. a flag: false sends the item down a path that reads its account, region
     and string fields first (an item from another account, by those names);
  4. a flag: true runs `ItemCheckHash` on the general path (a mismatch calls
     `ReportClient` and returns false);
  5. `isPlayerDrop` (defaults to false when undefined or missing; read on the
     class-13 branch only).

  The body switches on the class through a table of 16, 12, 13 and 14.
  **Class 16 calls `PickupRelic(args[0], args[1])` and returns its result**,
  with nothing after it: no hash check, no online branch, no
  `AddToInventory`. The general path ends in `AddToInventory`, whose result
  is the script's. Before the switch it sets `inventoryMapChanged` on the
  `Client_obj` instance when one exists. **Static reading.**
- **The two local call shapes.** Both run inside a `with` on the ground item,
  so `self` is the item. The companion passes `other` = the `Companion_obj`
  and the arguments `global.mplr`, `itemInstance`, `true`, `true` and
  `isPlayerDrop` through the game's protected-value read `GetVariable` (the
  "not set" sentinel turned into `undefined`). The player's pickup passes
  `other` = the `Loot_Manager_obj` and the same arguments except the third,
  which is the item's `itemIsLocal` through `GetVariable`. **Static
  reading.** **Measured** for the player's pickup (#124 Live 1, a click
  traced by a hook on both call routes): `self` = `Loot_Ground_obj`,
  `other` = `Loot_Manager_obj`, `argc` 5, arguments `real 1` (`global.mplr`
  offline), the item struct, `real 1`, `true`, `real 0`, returning `true`.
  A call with the companion's shape (`other` = the `Companion_obj`, third and
  fourth `true`, fifth `undefined`) made by ForgePact returned true 31 times
  out of 31, each raising the owned level. The game's companion never picks
  up a relic (its type filter takes classes 11 to 15), so a call of its own
  was not traced and its `other` stays the reading.
- **Neither `PickupLoot` nor `PickupRelic` destroys the ground instance.**
  Each caller does, after a true return: the companion destroys the item and
  then takes it out of `lootList` whatever the result; the player's pickup
  plays the pickup sound and effect, writes the inventory log line, drops the
  item from its on-screen label array and destroys it. **Static reading**;
  the destroy helper is unnamed in the binary and is read as the runtime's
  instance destroy (§10.6 records the companion's successful pickups removing
  the item). **Measured** (#124 Live 1): after each of 32 true returns of
  `PickupLoot` on a relic (one player pickup, 31 ForgePact calls) the ground
  instance still existed when the script returned.
- **`PickupRelic(mplr, itemStruct)`** finds the owned copy the way §2
  describes (the relic tab cell `inventoryRelicGrid[b][0][0]` first, then the
  five equipped slots), compares the owned relic's id with the dropped one's,
  reads the owned copy's `o`, and only while that is below 10 calls
  `RelicSetLevel(owned, o + 1)` and `RelicCheckAchievement`. Its outcomes
  (**Static reading**):
  - a relic the player does not own goes into a new relic tab entry
    (`GridAddItem`, `AddItemToMap`, `CreateItemSaveStruct`): true;
  - an owned copy below 10/10 is raised by one: true. **Measured** (#124
    Live 1): through `PickupLoot`'s class-16 branch, relic 1 went 7 -> 8 by
    the player's pickup, and relics 73, 106 and 131 went 9 -> 10 by
    ForgePact's companion-shaped call, one level per pickup;
  - an **equipped** copy at 10/10: nothing is raised and the script returns
    **false**, so the ground relic stays. This is the "a 10/10 relic cannot
    be picked up" the owner reports for #124;
  - a **relic tab** copy at 10/10: nothing is raised, but the script returns
    **true**, the same as a raise, so a caller destroys the ground relic for
    nothing. **Not established** on the running game: Live 1 never called
    the pickup on a maxed relic, so neither 10/10 branch was exercised, and
    a relic the player does not yet own was not available (all 141 owned).

  So a true return alone is not evidence that a level rose, and whether a
  relic can be picked up is decided by the owned copy's level (§2, "What
  10/10 means"), never the dropped relic's.
- **The SDK read.** `HeroSiege::Player::ReadGroundRelic(yytk, instance,
  GroundRelicRead&)` in `hs-game-sdk`'s `player.hpp` identifies a ground
  relic positively: the class from `itemInstance.itemType` must be
  `kRelicItemClass`, and the id comes from
  `itemInstance.itemDefinitionStruct.b`; anything else is refused with the
  stage it stopped at. It accepts both instance kinds (`IsInstanceHandle`:
  `VALUE_OBJECT` and `VALUE_REF`). C++ only: a ground instance exists only in
  the running game's memory, and the Python binding reads saves, so there is
  no Python twin and no parity claim
  ([hs-game-sdk guide](submodules/hs-game-sdk/instructions.md)). The variable
  names it reads were this section's static reading; #124's Live 1
  **measured** them, reading 42 of 42 ground relics on screen (`read stages:
  ok=42`), each with the id the research command had placed.
- **Placing a relic with `LootGroundCreateFromItem`, the player as `self`.**
  Static reading: it creates a `Loot_Ground_obj` through
  `CreateLootInFreePos`, sets its `itemInstance` to the item it is handed,
  runs `LootGroundInit` and returns the new instance (negative when none
  exists), with no create pool, no online branch and no zone gate; every
  earlier measurement (`sigdrop`, `angelicdrop`) had a dying enemy as `self`
  and an equipment item. **Measured** (#124 Live 1): with the player instance
  as `self` and `other`, it placed 49 of 49 relics, each built by
  `InitItemFromJson` from a relic tab entry's fields (`b`, `a`, `j`, `c`) and
  a key ending in `-16`, each read back as a class-16 relic with the
  requested id, and each could be picked up by hand or through `PickupLoot`.
  They lay at the player's position rather than spread out.
- **`DropRelic` and its force flag.** Static reading: it takes up to six
  arguments, x, y, two more, a fifth that when true skips the chance roll,
  and a sixth handed on to `LootGroundCreate`; without the fifth it compares
  a roll against the fourth and returns false when that fails (always, with
  no fourth), and it returns true only after its `LootGroundCreate` call. So a
  two-argument call builds nothing: ForgePact #124's first `forcerelic` made
  91 such calls and **measured** no relic on the ground. **Measured** (#124
  Live 1): five calls with `(x, y, 0, 0, true)`, the sixth left out and the
  player as `self` and `other`, each returned true and each put a relic on
  the ground (ground items 17 -> 22, five relics read with `itemActive` 1
  three seconds later). #125's six-argument call `(x, y, 0, 0, 1, 0)` had
  built relics and placed none; which difference matters is not established.
  `DropRelic` is not named in the local decompiler project, so its reading
  rests on the one unnamed caller of both `ReturnRandomPlayerRelic` and
  `GetRelicQuest` outside the Satanic kill routines.

ForgePact's Pet collects relics (`petrelic`) is built on this section: it
calls `PickupLoot` with the companion's shape, destroys the ground relic
itself only after a true return whose raise it sees in the owned level, and
never targets a relic the player owns at 10/10.
[pet relic collector, Static reading](../ForgePact/docs/pet-relic-collector-research.md#static-reading),
[Not established](../ForgePact/docs/pet-relic-collector-research.md#not-established),
[The mechanism](../ForgePact/docs/pet-relic-collector-research.md#the-mechanism),
[Live 1 results](../ForgePact/docs/pet-relic-collector-research.md#live-1-results-2026-10-02)

---

## 11. Minimap, Spawners and the Enemy Loop

### 11.1 Minimap and fog

- Mechanic, waypoint, chest, shrine and dungeon-entrance icons are hidden **only
  by the fog cell at their position**, in `objMinimap.minimapDiscoveredGrid` (a
  ds_grid); clearing the grid shows them all. `isDiscovered` (default false) and
  `discoveryRange` (500) exist on `Chaos_Pillar_obj` and `Mining_Node_obj` but do
  not gate the icon, and `Dungeon_Entrance_obj` has no `isDiscovered` at all.
- `objMinimap.minimapRevealed` is not a master flag: it is not recomputed and
  does not change when the fog is cleared.
- `minimapCellsX`/`minimapCellsY` are the fog grid's size; the grid is
  reallocated per zone (1119×561 and 1175×557 seen).
- Revealing a waypoint's icon does not unlock it: `waypointActive` stays false.
- `minimapShowMonsters` and `minimapShowEnvironment` are globals.

All **measured** (2026-09-10/11).
[map reveal §1](../ForgePact/docs/map-reveal-research.md#1-minimaprevealed-is-not-a-master-flag),
[§2](../ForgePact/docs/map-reveal-research.md#2-isdiscovered-does-not-gate-mechanic-icons--fog-does),
[§3](../ForgePact/docs/map-reveal-research.md#3-waypoint-icon-reveal-does-not-unlock-the-waypoint),
[§9](../ForgePact/docs/map-reveal-research.md#9-fog-robustness-minimapcellsxminimapcellsy-change-across-zones)

### 11.2 Spawners: packs do not exist until the player is near

- Every `Enemy_Creator_*` spawner exists and is awake from zone generation (one
  zone: 271 `Enemy_Creator_obj`, 13 Ambush, 19 Ancient, 7 Legion, with 208 live
  enemies). The family is `Enemy_Creator_obj` plus `_Champion_`, `_Ancient_`,
  `_Legion_`, `_Miniboss_`, `_Ambush_` and `_Colossal_Chest_`. **Measured**; family
  from names.
- Each creator registers a periodic timer with the game's timer system and keeps
  its handle in **`enemyCreatorTimer`** (period about 116 frames). The check spawns
  the pack when `distance_to_object(Player_obj)` is under **1050 px**, then
  destroys the timer — a creator spawns once. A pack's position and kind are known
  before birth; its rarity and affixes are rolled at birth, in the creator's
  `Alarm_2`. **Static reading**; period and radius **measured**.
- **A spawner's permanent failure mode, crash-free:** if the distance check sees 0
  before the creator has finished initialising, it takes the spawn branch early,
  once, and is inert forever. An uninitialised creator reads `enemyCreatorTimer`
  **undefined**; a ready one reads a real number. Validate against that, on the
  creator itself, at the point of use (§5.6). **Measured 2026-09-12.**
- A zone's minimap can exist before its creators; town has 0 creators and 8
  enemies. A spawned pack stays spawned, including across leaving and re-entering
  the zone. **Measured.**
- **A key dungeon spawns the same way, and all its creators exist at room
  entry and persist after spawning.** Pumpkin Cellar (`Pumpkin_Cellar_01_rm`)
  held 122 creators from the first tick to the last, while 600 kills were made
  to clear it; 5 enemies were alive on the first tick, 44 a second later (the
  packs near the entrance), and the alive count rose and fell as the player
  moved (peak 210). So a dungeon's creators can be counted at load. **Measured 2026-10-03**
  ([dungeon chest, Live procedure 1](../ForgePact/docs/dungeon-chest-research.md#results)).
- **No creator variable read by name was observed to hold its pack size, but
  whether a creator has spawned is readable.** In a second Pumpkin Cellar run
  every numeric variable on the 122 creators at the chest's first sight was
  summed against the 619 kills to clear and compared with each creator's
  births: none matched (the variables whose names suggest a pack size read as
  one large real per creator, rising from one creator to the next, not as
  counts). On 8 sampled `Enemy_Creator_obj`: at room entry `alarm[0]` was 5
  and both `enemyCreatorTimer` and `enemyArray` undefined; once armed,
  `alarm[0]` was -1 and `enemyCreatorTimer` a real; once spawned, `enemyArray`
  was an array and `enemyCreatorTimer` no longer listed. So "still to spawn"
  is `enemyArray` not being an array; `enemyCreatorTimer` alone cannot tell it,
  being undefined both before a creator arms and after it spawns. 5 of the 122
  had spawned by first sight, and the rest made about 5.25 kills each (614 for
  117). **Measured 2026-10-03**; the other creator objects' `enemyArray` was
  not sampled ([dungeon chest, Live procedure 1b](../ForgePact/docs/dungeon-chest-research.md#live-procedure-1b)).
- `EnemyCreatorPending` only reports whether a creator still has an alarm running.
  Creators make density copies through four-argument `instance_create_*` calls.
  **Static reading.**
- `objZoneGenV2` is the zone generator (its outer create calls measured at
  89–123 ms); `PopulatePresetData` is its first call.

[map reveal §10, The census](../ForgePact/docs/map-reveal-research.md#the-census-that-settled-it),
[The regression this nearly shipped with](../ForgePact/docs/map-reveal-research.md#the-regression-this-nearly-shipped-with-and-the-fix),
[population performance §2.1](../ForgePact/docs/population-performance-analysis.md#21-birth),
[population capacity, v4](../ForgePact/docs/population-capacity.md#local-v4-caller-reuse-and-generation-measurement),
[check-a-permission](agents/check-a-permission.md)

### 11.3 The enemy loop

- **The game never deactivates monsters**; it deactivates only props and their
  lights. Far monsters simply get no step. **Static reading**, consistent with
  the census.
- Every 30 frames (`updateEnemyTimer`; `updateEnemies` forces it)
  `EnemyStepHandleNew` walks every active `Enemy_Child_Basic_obj`, tests it
  against the player box (`playerBoxL/R/T/B`) and rebuilds
  `monsterHandleArray`/`monsterHandleArrayCount`. Monsters leaving the box get
  `wasActive`/`isMoving` cleared, their target dropped and their path ended. Each
  frame it makes one `m_EnemyStep` call per handle; AI, pathfinding and effect
  timers run only inside the box. **Static reading.**
- Every monster owns an `Enemy_Health_Bar_Parent_obj` (`myHealthBar`) whose Draw
  GUI is the only caller of `DrawEnemyHealthBars` (**measured** at 4.14 ms a
  frame); `objMinimap`'s Draw GUI runs `DrawMinimap` → `DrawMinimapDynamic`, which
  walks 17 object families including every enemy. Active buffs are one
  `Draw_Enemy_Buff_obj` each (`m_runEnemyBuffs`); corpses are `Corpse_obj`
  (`m_CorpseStep`). **Static reading.**
- A pack birth (the creator's `Alarm_2`) and each monster's Create event are large
  native bodies, one native call per pack, milliseconds each. **Static reading.**
- While a monster is deactivated the timer system pauses its timers and `with` on
  its id does nothing. **Measured.**
- Enemy variables: `distancePlayer` is a countdown (100000 idle), **not a
  distance**; `myGridCellX`/`Y` are `floor(x/16)`/`floor(y/16)` (-1 unset);
  `visible` reads 0 far away and is rewritten by the game within a second;
  `inviewCheck` is not the culling flag; `Enemy_Parent_obj` has 312 variables, none
  a minimap flag. **Measured.**
- **Rarity setup.** `EnemyRaritySettings(typeId)` runs from `Enemy_Parent_obj`'s
  Alarm 4 with the monster as `self`, after the spawner has set `enemyRarity`
  (1 common, 2 champion, 3 ancient, 4 legion; names per § 13.7) and filled `enemyAffix`/`affixList`,
  and before the stats, affix effects and health bar are built; a rarity or
  affix written at its entry is built by the game as if it had rolled that way.
  **Measured** 2026-09-05 on ordinary monsters (entry and exit state identical;
  ForgePact README § "Tyrant's Crown"). Bosses, the `Enemy_Child_Boss_obj`
  family, descend from `Enemy_Parent_obj` and so take the same alarm; that the
  rarity sliders raised an Anubis boss's health about ninefold (a player report
  against ForgePact 1.4.1) shows they reach this hook, and ForgePact traced it
  itself on 2026-10-02: `Karp_King_obj`, `Damien_obj`, `Uber_Damien_obj` and
  `Uber_Anubis_obj` each entered and left it (**Measured**; § 13.7, "Bosses at
  a forced rank"). The game's body of the script was not read: its call sites
  sit in a region the decompiler refuses, so whether a boss takes a branch of
  its own there is **not established**.
  [boss rarity, Static reading](../ForgePact/docs/boss-rarity-research.md#static-reading)
- ForgePact's rarity mods all write at that entry, through one shared hook.
  The Monster Rarity sliders and Tyrant's Crown raise ordinary monsters, and
  the sliders skip any instance whose object descends from
  `Enemy_Child_Boss_obj` (ancestry, `IsDescendantOf`, not a health threshold);
  the Bosses control (`bossrarity`, issue #44) raises only those, at rarity 1,
  to 3 or 4. Instances a monster creates are left alone by all three, because
  a re-raised split child splits again. **Our code**, not a game fact.

[population performance §2.2](../ForgePact/docs/population-performance-analysis.md#22-who-gets-a-step),
[§2.3](../ForgePact/docs/population-performance-analysis.md#23-what-runs-for-every-living-monster-every-frame),
[§2.5](../ForgePact/docs/population-performance-analysis.md#25-the-entry-hitch-is-a-different-problem),
[§5](../ForgePact/docs/population-performance-analysis.md#5-options),
[map reveal, dead ends](../ForgePact/docs/map-reveal-research.md#dead-ends-closed-on-the-way-so-they-are-not-re-tried)

### 11.4 Movement speed

`PathFindStartPath` is the single place an enemy's `moveSpeed` ×
`movementSpdMultiplier` becomes `moveSpeedCur` and reaches `path_start`; goblins
and online-client movement use other code. **Static reading.**
[ForgePact README, Enemy Movement Speed](../ForgePact/README.md#enemy-movement-speed)

### 11.5 Dungeon chest and its unlock

The end chest of a key dungeon is `Dungeon_Chest_obj` (1366). The game opens it
only once the dungeon's monsters are dead; the chest decides that itself, by
polling `instance_exists(Enemy_Parent_obj)` (measured, below).

- **Events.** `Dungeon_Chest_obj` has five: Create, Step, Draw, Alarm 0 and Other 7
  (animation end). They were read through the per-object event rows the runtime
  keeps (name, function, variable table: the table the frame profiler walks), so
  object events are readable statically although `symbols.csv` lists only
  scripts. **Static reading.**
- **Step** calls, by name, `GetKeyDungeonRoom`, `GetKeyDungeon`,
  `NetworkSendClientEffect`, `GPV`, `IsDefined` and `PlaySound3D`. It calls no
  script that counts or lists enemies. **Static reading.**
- **Animation end is the open**: `CreateInFreePos`, an `instance_create` by name,
  `SPV`, `ReturnSpecificStat`, `quest_exists`, `QuestComplete` and
  `CommunityQuestAddProgress`, so loot and quest completion both happen there.
  **Alarm 0** calls `ReturnSpecificStat` and `GPV`; **Create** calls `CheckTown`,
  `UpdateDepth` and `ReportClient`. **Static reading.**
- **What a static reading cannot show in this build.** Script bodies reach
  builtins through the runtime's function table, not by direct call (in 150
  bodies read, `is_handle` was the only direct one), so whether the chest's Step
  polls `instance_number`/`instance_exists` about monsters is **not
  established**. Instance variables are read and written through slot numbers,
  so which chest variable, if any, flips at the last kill is **not established**
  either. From the reading alone, what decides the unlock is **not
  established**; the live measurement below found the builtin poll.
  **Static reading.**
- **Neighbours.** `Dungeon_Boss_Blocker_obj` (1365) has Create, Step and Draw; its
  Step calls `quest_exists` and `GPV`. `Spawn_Dungeon_obj` (4667) has Create,
  Step, Alarm 0 and Draw; its Alarm 0 calls `sc_rift`, `StringStartsWith`, `GPV`
  and `instance_create`: it is the world-side entrance of the special-content
  family, not a monster spawner. `Dungeon_Spawner_1_obj`..`_4_obj` have only a
  small Create. **Static reading.**
- **Counting kills.** The kill path is § 13.5: `EnemyDestroyKillProc` runs with
  the dying enemy as `self` (and again with the player as `self`), monsters are
  the `Enemy_Parent_obj` (1429) family, and `Enemy_Death_Effect_obj` is not made
  on every kill, so it cannot count kills. **Measured.**
- **Measured in Live 1** (2026-10-03, Pumpkin Cellar, `Pumpkin_Cellar_01_rm`,
  which the runtime printed as a room reference by name rather than the SDK
  index 216; source: the research doc's
  [Live procedure 1 results](../ForgePact/docs/dungeon-chest-research.md#results)):
  - **The chest polls `instance_exists(Enemy_Parent_obj)` with itself as
    `self`**, about once a frame: 3402 calls with 44 monsters alive, 41519 by
    the end of the run. Its other `instance_exists` arguments were `Player_obj`
    (1897), `Loot_Ground_obj` and `objZoneGenV2` (12 each) and a few
    controllers. **Measured** (a `HookBuiltin` detour with a per-`self`
    positive control in the same session). It made no `instance_find` or
    `instance_place` call; **measured**, since those detours saw the game's
    own calls (`gameCalls` 631489 and 6422). Whether it calls
    `instance_number` is **not observed, and the instrument could not see
    it**: that detour attributed no call to any game `self` in the session
    (`gameCalls=0`), and the positive control was ForgePact's own
    `CallBuiltinEx` call, not the route compiled GML takes.
  - **At the last kill only `nearest` changed** on the chest, from `-4` to an
    instance reference, the tick after the alive count reached 0: read as the
    chest finding the nearest player once no monster exists. The open, on
    approach, changed only `sprite_index` (`Dungeon_Chest_Closed_spr` →
    `Dungeon_Chest_Open_spr`), `image_index` and `image_speed`. No store key
    read through `GPV` moved and no `SPV` ran. **Measured**; that no other
    unlock state exists is **not established** (only the user variables, seven
    built-ins, alarm 0 and the store keys were watched).
  - **The monsters stream in**: 5 alive on the first tick, 44 a second later,
    a peak of 210 at 260 kills, 0 at **600** kills; **122** creators on every
    tick (§ 11.2). The kill path (§ 13.5) counted one per kill with no
    non-enemy `self`. **Measured.**
  - **Blockers: 0** (`Dungeon_Boss_Blocker_obj`) in Pumpkin Cellar. Whether a
    dungeon with a blocker behaves the same is **not established** (not
    covered live).
- **Measured in Live 1b** (2026-10-03, two Pumpkin Cellar runs in one launch;
  source: the research doc's
  [Live procedure 1b results](../ForgePact/docs/dungeon-chest-research.md#live-procedure-1b)):
  - **Answering that one poll `false` opens the chest with monsters alive.**
    With the poll answered for the chest's own `self` only (390 calls answered
    after the latch at 304 kills), the chest's sprite went from closed to open
    at 325 kills with 193 monsters alive. **Measured**; whether it then drops
    loot as at a full clear was not checked.
  - **Kills to clear and births differ.** The second run cleared at 619 kills
    with 644 enemies created by creators (5 alive at the chest's first sight,
    639 born after it): 25 monsters a creator makes are never killed by the
    player and never keep the chest shut. A total for the chest is counted in
    kills. **Measured.**
  - **Blockers: 0** again; a dungeon with a blocker is still **not covered
    live**.
- **Measured in Live 2 and Live 3** (2026-10-04, ForgePact's player build,
  Pumpkin Cellar, one run each at a 50 % share; source: the research doc's
  [Live procedure 2](../ForgePact/docs/dungeon-chest-research.md#live-procedure-2)
  and [Live procedure 3](../ForgePact/docs/dungeon-chest-research.md#live-procedure-3)):
  - **The 122 creators were all still to spawn at the chest's first sight** in
    both runs, all readable, and ForgePact's estimate of the dungeon's total
    came out at **642** and **646**, the difference being the monsters alive
    at that moment (1 and 5 by the estimate's arithmetic). **Measured.**
  - **Answering the chest's poll at a share of the total opens it with many
    monsters alive**: 170 alive at the latch (333 kills of 642) and 163 after
    the open in Live 2; 128 alive at the latch (323 of 646, exactly the
    threshold) and 103 after the open in Live 3. The poll was answered
    thousands of times after the latch (9421 in Live 2 before the open).
    **Measured.**
  - **The kill path counts in the player build** once `Enemy_Parent_obj`'s
    index is resolved by name (§ 13.5): the first read after a few dozen kills
    showed 38, with no kill refused as a non-enemy. **Measured.**
  - **With no lever** the chest stayed shut with monsters alive and opened
    after the clear (Live 2, the owner's report). **Measured.**
  - **Blockers: 0**; a dungeon with a blocker is still **not covered live**.

[dungeon chest, Static reading](../ForgePact/docs/dungeon-chest-research.md#static-reading),
[Route](../ForgePact/docs/dungeon-chest-research.md#route),
[spec](models/dungeon-chest-spec.md)

---

## 12. Mining

- `Mining_Node_obj` variables: `miningActive`, `miningPlayer`, `stop`,
  `range`/`rangeMax` (48/48), `dir`, `miningQue`, `hp` (1, then 0 on reward),
  `miningActivateDistance` (16 px) and a protected `miningReq` (the level
  requirement). **Measured.** `range` is a pulse, not dig progress: with a
  character standing at the node and no dig completing it cycles 0 -> about
  45-48 -> 0 while `hp` stays 1, and `miningQue` reads false at every read from
  outside the step (consumed in the frame it is set). **Measured 2026-09-28.**
- A dig finishes inside the Step of the key press: level check, then the reward at
  once. Setting `miningQue` sends the node through that same completion on its
  next Step (hit effect, ore, XP, quests, depletion, network message) if the player
  is within `miningActivateDistance`. **Measured.** Setting `hp` back to 1 and
  `miningQue` to true right after a completion and calling `MiningNodeStepMain`
  again with the same arguments pays the completion again in the same Step: 13 of
  13 such re-runs paid ore and each left `hp=0 miningQue=false`; ten completions
  in one Step left the game responding. **Measured 2026-09-28** (ForgePact Mining
  Ore Extra Rolls, `hs-game-sdk/curated/mining_reward_measurements.json` MR4-MR6).
- `miningPlayer` starts as `noone` (-4) and is still `noone` when a keyboard dig
  pays out; ground loot this client creates is credited to the local player.
  `GetMiningLevel()` returns the character's mining level. **Measured** and
  **static reading.** On 2026-09-28 (Highland Mines Copper Veins) every node
  snapshot, before and after completions, read `miningPlayer` as an instance
  reference (`312664r`), not `noone`; whether that instance is the local player
  was not checked, and when the game sets it is not established.
- **The ore reward:** `MiningNodeStepMain` calls `LootGroundCreate` directly.
  Argument 2 (zero-based) is the item type (Material, 14); argument 3 is a params
  struct whose `b` is the base definition and optional `o` the stack quantity
  (absent = 1). Material bases 27–32 are Copper, Iron, Gold, Ruby, Jade and
  Tarethium. Changing `o` on a shallow `variable_clone` scales the pickup.
  **Static reading**, **measured 2026-09-23.**
- **The ore a node pays is decided when the node is created, not when it is dug.**
  Each node holds an array of ore-kind entries (the variable's name is not
  established). `Mining_Node_obj` (2775) fills it in its Create event from choices
  gated by the runtime's `irandom` and by two `ReturnSpecificStat` queries (ids 692
  and 703); `Asgard_Special_Node_obj` (299) fills it with fixed counts. At dig time
  `MiningNodeStepMain` only counts the entries per kind and makes one
  `LootGroundCreate` call per kind present, so at most six, writing `o` on the
  params only when a kind's count is above 1. There is no draw at dig time for
  which ore or how much. **Static reading** (2026-09-28), **measured 2026-09-28**
  for one-kind nodes: a Copper Vein made exactly one `LootGroundCreate` call per
  completion run (16 calls over the 16 runs counted), and a re-run of the completion paid the same
  kind again.
- **Bonus finds are drawn at dig time, gated by the digger's stats.** After the ore
  the step makes several independent rolls, each asking `ReturnSpecificStat` for
  one stat (query ids 693 to 700, in the five-argument query shape
  `hs_game_sdk/reward_stats.hpp` records for Magic Find) and paying only when the
  stat is above 0 and an `irandom(cap)` draw comes out below it. `irandom(n)` draws
  0..n inclusive; the cap is the literal 99 at one site and computed at the others
  (not established). What they pay: a type-15 item at base 109, 110 or 111 (itself
  an inclusive draw); one to three `Goblin_Ore_obj` (1903) placed through
  `CreateInFreePos`; type-14 materials at computed bases (three sites); two more
  type-15 sites and one type-13 site. A character whose queried stats are all 0
  never passes one. Which gear or talents raise ids 692-703 is not established.
  **Static reading** (2026-09-28). Measured data, 2026-09-28: on one character
  (hero Suh, digging Copper Veins in a zone-level-33 mine) all ten queries the node and the dig
  use, ids 692-700 and 703, read 0 through `ReturnSpecificStat`, and no bonus
  find was seen over 17 completion runs. That agrees with the reading but does
  not test it, so a bonus find is **not observed live** (MR9).
- **The dig's side effects are direct calls from the step.** `MiningAdd` (the
  mining skill's own XP); then, on each of two branches, `ExperienceUpdate` followed
  by `GuildExperienceAdd`, each called by the step itself (`GuildExperienceAdd` is
  not reached through `ExperienceUpdate`); `CombatText` floating text at several
  sites; up to four `quest_exists`/`update_quest` pairs; `PlaySound3D`; a
  `Mining_Effect_obj` (2773) hit effect; `NetworkSendClient` (nothing offline).
  Every one is a direct call, so only a native `HookOneScript` detour sees it.
  **Static reading** (2026-09-28). The node's `hp` then goes 1 -> 0 and the
  instance survives the frame at 0: **measured 2026-09-23.** Through native
  detours on 2026-09-28: `ExperienceUpdate` and `GuildExperienceAdd` are each
  called once per completion run (**static reading, measured 2026-09-28**, MR7).
  `MiningAdd`, `CombatText` and `update_quest` were **not observed** from a dig
  over four digs and 17 completion runs (`MiningAdd` 0 calls; `CombatText` 0
  calls across a whole dig while the same detour counted kill XP text;
  `update_quest` 0, probably no active quest), against the static reading; which
  branch skips them is not established (MR8).
- `material_mining_*` items have `droprate.base` 50,000,000, so no drop type
  produces them: ore comes only from mining (§13.2). **Measured.**

[miner's helmet, Runtime](../ForgePact/docs/miner-helmet-prototype.md#runtime),
[Ownership fix](../ForgePact/docs/miner-helmet-prototype.md#ownership-fix-2026-09-23),
[mining ore, Observed interface](../ForgePact/docs/mining-ore-research.md#observed-interface),
[Live verification](../ForgePact/docs/mining-ore-research.md#live-verification-2026-09-23),
[what one dig pays, the spec and its model](models/mining-reward-spec.md),
[extra rolls](../ForgePact/docs/mining-ore-research.md#extra-rolls)

---

## 13. Drops: Types, Categories, Keys and the Angelic Roll

The data tables in this section are also in
[`hs-game-sdk/curated/drop_types.json`](../hs-game-sdk/curated/drop_types.json).

### 13.1 Drop types (`LoadDrops`)

- `LoadDrops`' argument 2 is the drop type and argument 8 is **`chances`**, a
  70-slot array indexed by drop type, created zero-filled by `DropItem` and
  passed by reference, so writing into it in place works. A normal monster has
  only 9 non-zero slots. **Measured** (2026-08-27) and **static reading**.
- For each type the outer gate rolls an integer die whose ceiling is
  `gDataProtected` member `0xAF` and compares it with `chances[type]`; types 11
  (`DropKeys`), 12 (`DropDungeonKeys`), 31 (`DropBifrostKey`) and 40
  (`DropChaosKey`) are built identically. The ceiling's value is unread. **Static
  reading.**
- The die draws a whole number, so every chance in (0, 1] passes only on a draw
  of zero: 0.5 and 0.01 are the same gate. Scaling the relic gate chance by 0.05,
  and then by 0.001, did not reduce relics. A chance of 0 never passes (§13.3).
  **Measured 2026-08-28** (ForgePact `c0a6a6b`).
- With slot 12 set to the monster's own `chances[11]` (5–9), 95 of 1233 extra
  type-12 rolls passed (about 7.7%). **Measured 2026-08-27.** That pass rate fits
  a ceiling of about 100 outcomes and rules out 10 or 1000. This is an inference
  from the rate, not a reading of the value, and whether the top value is
  included is open. It also rests on the instrument: 1233 counts our own
  re-calls, but 95 is the counter of a table-only `DropDungeonKeys` hook, which
  read 95 rather than 0 and so saw that path, though only the rate's fit shows
  it saw every call on it. The mechanism in our own words, and a model checked against
  these numbers, is [`docs/models/drop-roll-spec.md`](models/drop-roll-spec.md).
- Types measured by opening every gate on one monster (vanilla chance on that
  monster where non-zero): 4 rune (14), 6 gem (45), 10 flask (3), 12 dungeon
  key, 15 Ninja Hook, 16 Angelic Key, 17 and 49 Satanic Dice, 18 Ruby Key, 25
  Battle Fragment, 26 Codex Page, 31 Bifröst Key (15), 33 `Flo`, 34 Scroll of Ra,
  35/36 Eternity/Infernal Codex, 37 the 18 orbs, 38 Colosseum Fragment, 39
  Satanic Crystal, 41 a Prime Evil part, 43 Dimensional Shard, 45 a unique item,
  46/51 Destiny Shard (51: 1), 47 Gypsy's Prophecy, 48/52 Prophet's Wisdom, 50
  Blacksmith's Mallet, 56/60 tarot cards, 59 Essence Vault, 61/63 Tarot Deck, 64
  Liquate. Type 2 threw for that monster. **Measured 2026-08-27.**
- A monster's `dropTable` is a list of `[type, chance]` pairs; its `Alarm_4` adds
  every listed type, so a duplicated type rolls twice. `Pile_Parent_obj`,
  `Destructible_Parent_obj`, `Destructible_NoCollision_Parent_obj`,
  `Cursed_Orb_obj` and `TalentsPirate` have no `dropTable`, and writing one there
  raises a GML error. **Static reading.**
- The `blood_pact_*` names are translation keys, not variables; pact values
  arrive from the server (`httpBloodPactJoin`/`httpBloodPactRefresh` hold the
  request handles). **Static reading.**
- Prime Evil parts: `DropBossParts`, `DropBossPartsNext` and `DropUberParts`
  each have one direct call site, all in `LoadDrops`. `LoadDrops` is called only
  from `DropItem`. Monsters reach `DropItem` from `Enemy_Parent_obj`'s Destroy
  event; chests, goblins, destructibles and piles reach it from their own
  events. **Static reading** (direct-call scan of the Sep-17 build).
- `DropBossParts` looks up the part's category-13 repository entry, reads its
  drop rate (`GetDropRate`) and player stat 736, then places the part with
  `LootGroundCreate`. **Static reading.**
- `DropUberParts` reads no drop rate and makes no Prime Evil part. It creates
  one of category 13's items 14-18, or one of their infernal versions, 49-53:
  - Soul of Anguish, Soul of Despair or Soul of Corruption;
  - Scroll of Ra or Colosseum Fragment.

  **Static reading.**
- `LoadDrops`' switch table:
  - sends drop type 43 to `DropUberParts`;
  - sends type 26 to `DropDimensionalShard`;
  - makes type 41 check `LoadDrops`' fourth argument first. It does nothing when
    that argument is false.

  **Static reading.** The §6 type map (2026-08-27) recorded a Dimensional Shard
  for type 43. The two disagree; not resolved.
- `Enemy_Parent_obj`'s Destroy calls `DropItem` only when the protected HP is 0
  or less. **Static reading.**
- A boss kill rolls its part several times. Karp King in Act_01_01 dropped:
  - 11 bellybuttons in 15 kills at the vanilla base of 27;
  - 36 in 12 kills at base 5.4;
  - 138 in 15 kills at base 1, up to 14 in one kill.

  **Measured 2026-09-26** (M11/M12 in `hs-game-sdk/curated/drop_roll_measurements.json`).
- Uber bosses spawned in Act_01_01 roll no Prime Evil part. With
  `droprate group primeevil` at x35 (base 1):
  - ten kills dropped no part and none of items 14-18 or 49-53: Uber Damien 3,
    Reaper 3, Uber Endrixia 2, Uber Anubis 2;
  - Karp King at the same spot dropped 12 parts before them and 8 after.

  **Measured 2026-09-26** (M13).
- Killing a monster from outside:
  - A boss spawned in a town removes itself within seconds and drops nothing.
  - `instance_destroy` on a live monster runs its Destroy event but drops
    nothing.
  - Setting its protected HP to 0 kills it through its own death path, drops
    included. The key is the monster's `enemy_hp`; the call is
    `PC_SetVariableGMLWrapper(key, 0)`.
  - Uber Endrixia, Uber Anubis and Uber Luna do not die that way.
  - For Endrixia and Anubis, HP 0 followed by `instance_destroy` works: the
    Destroy event runs with HP at 0, and the drop path follows.
  - `instance_destroy` on Uber Luna after HP 0 closed the game, with no crash
    dump. So did `room_goto` to `Uber_Inoya_rm`.
  - A boss that dies where loot cannot land drops nothing. One spawned past the
    room's edge left no `Loot_Ground_obj`.

  **Measured 2026-09-26.**

[prime evil parts](../ForgePact/docs/prime-evil-parts-research.md),
[blood pact §6](../ForgePact/docs/blood-pact-values-research.md#6-ölçüldü--damla-tipi-haritası-2026-08-27-akşam),
[blood pact §1](../ForgePact/docs/blood-pact-values-research.md#1-kapatılan-yanlış-yol-blood_pact_-isimleri),
[dungeon keys, LoadDrops](../ForgePact/docs/dungeon-key-research.md#kancalanacak-script-gml_script_loaddrops-adla-çözülür),
[dungeon keys §4](../ForgePact/docs/dungeon-key-research.md#4-önerilmeyen-yollar-ve-nedenleri)

### 13.2 Repository categories (`GetNormalRepoStruct(category, 0, index)`)

| Category | Holds | Entries |
|---|---|---|
| 0 | helmets | 15 |
| 1 | armors | 20 |
| 2 | boots | 15 |
| 4 | gloves | 20 |
| 5 | amulets | 25 |
| 6 | shields | 18 |
| 7 | rings | 30 |
| 8 | belts | 15 |
| 10 | charms | 60 |
| 11 | consumables | 27 |
| 12 | keys | 44 |
| 13 | collectibles | 65 |
| 14 | materials | 74 |
| 15 | socketables | 200 |
| 16 | relics | 156 |
| 18 | flasks | 16 |
| 19 | vault | 7 |

Categories 3, 9, 17 and 20–25 are empty (weapons come some other way).
These numbers coincide with `hs-game-sdk`'s `ItemType` (the value an item instance
carries in `itemType`) for 0–2, 4–8, 10–12 and 14–16; 13 is "collectibles" here and
`TAROT` there, and 3 (`WEAPON`) is empty here. That the two are the same field is
not measured beyond `itemType` 14 (§9.3).
`droprate.base` values by index: runes 350 → 334,800, orbs 11,000–14,400, gems
9,000/11,000, chipped/flawed/flawless stones 50/100/200, jewels 410, most dungeon
keys 1500. **Measured 2026-08-27.**
`DropRelic`'s drop is not a 1-in-`droprate.base` roll: all 156 relics carried
25,000,000 and relics still dropped constantly, so dividing every relic's base by
the same factor (the `droprate group relic` lever) changed nothing observable.
**Measured 2026-08-28** (ForgePact `c0a6a6b`). It does not read the base at all
(**static reading**, 2026-09-30): `DropRelic` and both Satanic kill relic routines
draw `irandom(155)` and draw again while `GetRelicQuest` answers true, which it does
for the quest relics 141..155 only, so every other relic is equally likely
whatever its base. `DropRelic` and the Feast routine may then copy one of the five
equipped relics below level 10 in place of the pick. The whole mechanism, with each
claim labelled, is hub `docs/models/relic-pick-spec.md`. **Measured** 2026-09-30
(ForgePact #125 Live 1, 320 relics built through `DropRelic`): no quest relic ever
came out. With six relics maxed, 8 of 150 relics were one of them without a filter
and 0 of 150 with `GetRelicQuest` answering true for them.
[blood pact §3](../ForgePact/docs/blood-pact-values-research.md#3-eşya-kategorisi-haritası-yeni)

### 13.3 Dungeon keys

- Type 12 always sits in the same drop-table block as 17 (Satanic Dice) and 18
  (Ruby Key), never beside 11; monsters that drop ordinary keys carried
  `chances[12]` = 0 in 200 of 200 calls. Tables with types 11/12 exist only in
  `LoadMonsterDropTables`, `EnemyRaritySettings` and `TalentsPirate`. **Measured**
  and **static reading**.
- After the gate, `DropDungeonKeys` picks one of 26 keys uniformly from
  `GetDungeonKeys`, reads that key's `GetNormalRepoStruct(12, …)` rate, scales it
  by `chances[13]` (0.7 natively), luck and argument 6, and places a hit with
  `LootGroundCreate`. It reads arguments 0, 1 and 3–7; an undefined argument 5
  makes the luck term fail. **Static reading.**

[dungeon keys, the whole chain](../ForgePact/docs/dungeon-key-research.md#zincirin-tamamı-açıldıktan-sonra-hepsi-oyunun-kendi-kodu),
[S10, dungeon keys solved](../ForgePact/docs/S10-special-content-notes.md#cozuldu---zindan-anahtarlari-dogal-olarak-dusuyor--27082026)

### 13.4 The Angelic roll

- Without buff 332 the Angelic roll was **not observed** in 984 kills (whether a
  positive control ran in that session is not recorded); the check is a single
  yes/no gate inside `DropItem` (**static reading**). Buff 332 stacks additively
  from Blood Pact and dungeon modifiers (**static reading**).
- With it, `DropItemAngelicChance` runs once per roll, always inside `DropItem`,
  with `self` = the dying monster and four arguments (two position reals, the
  chance, undefined). It returned undefined on all 374 misses; a hit was not
  observed in that session. The chance read 1195 or 1526 even with 3000 supplied
  by the buff, so its composition is not established. One roll reads about 8
  unique definitions through `GetUniqueRepoStruct`. **Measured 2026-09-23.**
- Hits were observed in Live 1 (#74), with the roll's chance argument raised by
  a research lever, not at the natural chance: 98 hits over 108 rolls, each
  detected as a `CreateDefaultParams` call while the roll ran (inline detour,
  `cdpCalls` above zero as its positive control), with the ground filling with
  the game's own Angelic and Unholy items (seen in screenshots, not counted
  against the hits). A hit at the natural chance has
  still not been observed. ForgePact's validated pool read 47 candidates and 11
  rejected once the two signature items were out of it. **Measured (Live 1,
  2026-10-02, research dll 4534c0ff…).**
- Unique definition records have the shape `{w, j, b, a, c}` (`c` = 1 marks the
  unique repository, `j` the weapon subtype); there is no Angelic flag, and base
  items with flag 40 set are skipped. **Headhunter and Tyrant's Crown have no
  unique-repository entry, so the game's own roll never picks them.** **Static
  reading.** How ForgePact #74 lets the roll pick them anyway is the bullet
  "How #74 uses the list" below (a stand-in entry for the length of the roll)
  and the guide's Known Limitations item 42.
- **The return value.** `DropItemAngelicChance` sets its result to undefined on
  entry and never assigns it again, so a hit returns undefined exactly like a
  miss: the return cannot tell the two apart. This is why the 374 measured
  misses were undefined. **Static reading (2026-10-02, issue #74).**
- **The arguments.** Position x and y fall back to the caller's own x and y when
  absent; the chance (argument 2) falls back to 0; argument 3 (undefined in
  every measured call) is never read by the roll and is handed on, unchanged, to
  the placement as its sixth argument. **Static reading (2026-10-02, issue
  #74)**, consistent with the four arguments measured.
- **The pick.** The roll takes a random entry from a list of unique
  identifiers; each entry is an array of three numbers (type, sub, b) that it
  looks up through `GetUniqueRepoStruct`. It throws the definition away and
  picks again when the base-info flag 40 (hidden or development item) is set, or
  when the definition's rarity field 27 is neither 7 (Angelic) nor 10 (Unholy),
  and it keeps re-picking until one passes. These are the same two filters
  ForgePact's `BuildAngelicPool` applies. Roughly one entry in eight passes,
  which accounts for the ~8 definition reads per roll measured above. **Static
  reading (2026-10-02, issue #74).**
- **Where the list lives.** The roll reads the list as a variable of an
  object-scoped reference whose constant encodes object index 984, which the
  SDK names `Controller_obj` (`HeroSiege::Objects::GameObject::Controller_obj`):
  in GameMaker terms, a variable of the first active `Controller_obj`
  instance. **Static reading (2026-10-02, issue #74, list injection).** The
  two earlier negatives were measured on other scopes: a `lootListUnique`
  instance variable on `Loot_Manager_obj` (`variable_instance_exists` false,
  2026-09-23) and, in #74's first live session (Session 2 of the research doc,
  2026-10-02, research dll 4534c0ff…), a `lootListUnique` global
  (`variable_global_exists` false) beside the same `Loot_Manager_obj`
  question. Each measured only that the name it asked for is absent from the
  scope it asked; neither asked `Controller_obj`, so neither is a measurement
  of the list and both say nothing about it.
- **The list's layout: `Controller_obj.lootListUnique[5]`, a `ds_list` of
  `[type, sub, b]` entries.** The runtime keeps, beside each variable slot and
  builtin-pointer global, a record of its name; read for the slot the roll
  loads, it names `lootListUnique`. (The four slot-name scripts of the first
  reading, `FindSlotNames`, `SlotRefs`, `FindPointers` and `FindRvaTable`,
  found 0 hits because they looked for stores and tables, not for that
  record.) The roll does not use `lootListUnique` itself as the list: its
  read carries the constant array index 5, so it takes the **sixth element**.
  On that element it calls `ds_list_size`, then `ds_list_find_value` at a
  random index drawn up to that size, then `is_array` on the value; only when
  `is_array` holds does it take the value's elements 0, 1 and 2 as the type,
  sub and b it hands to `GetUniqueRepoStruct`, otherwise it draws again. The
  three builtin names come from the same name records (`FindWrites` and
  `FindPointers` on their pointer globals: 0 hits each). So
  `Controller_obj.lootListUnique` is an array of length 6 (measured, Live 1)
  whose element 5 the Angelic roll uses as a `ds_list` (static reading). Live
  2 read element 5 as a `ref` value, like the ds containers of §5.4 (above).
  The entries of element 5 are arrays of three numbers. **Static reading
  (2026-10-02, issue #74, replan 2)**; the name and the outer length of 6 are
  confirmed by Live 1, and the layout, the kind and the sub-list's size by
  Live 2 (below). **Not established**: what the other five elements mean or
  are keyed by (Live 2 found them to be `ds_list`s of triples too; the roll
  reads only `[5]`; `lootListNormal`, outer length 5 on the same instance, is
  not read by this roll), and whether the random index can equal the size,
  an off-by-one the `is_array` re-draw would absorb. The curated record
  `hs-game-sdk/curated/angelic_list_measurements.json` holds this as
  `list_layout`, and its `list_variable` is `lootListUnique` since Live 2's
  reach check passed on it.
- **Measured (Live 1, list injection, 2026-10-02, research dll f7560e80…).**
  The first `Controller_obj` instance (one instance, read as `VALUE_REF`)
  answered `variable_instance_get_names` with 221 names in town and 222 after
  a zone change, among them `lootListUnique` with `array_length` 6 and
  `lootListNormal` with `array_length` 5, both before and after the zone
  change. The research build's shape check of that session expected a flat
  array of `[type, sub, b]` triples and refused both (`entry 0 is not three
  numbers`), as it refused every other array, so it accepted no list
  (`candidates=0`) and nothing was ever pushed. In the same session no
  `lootListUnique` global (`variable_global_exists` false) and none on
  `Loot_Manager_obj` (`variable_instance_exists` false) were found again:
  measured on other scopes than `Controller_obj`, the variable's own.
- **Measured (Live 2, list injection, 2026-10-02, research dll e30981d5…):
  the layout.** ForgePact's list dump read
  `Controller_obj.lootListUnique` as an array of 6 whose every element is a
  `ref` value that `ds_exists` accepts as a `ds_list`, every entry of each an
  array of three numbers: `[0]` 50 entries, `[1]` 61, `[2]` 79, `[3]` 152,
  `[4]` 221 and `[5]` 380 (`[5] kind=ref ds_list=yes:380 triples=380/380`,
  first entries `[0,0,1]`, `[0,0,15]`, `[0,0,29]`). Only `[5]` holds Liquor
  Holster's `{8, 0, 51}` (once), and the scan's only candidate was
  `lootListUnique[5]:380`. The six sizes were the same after a zone change
  and at the end of the session, after 36400 entries had been pushed and cut.
  `lootListNormal` dumped as five `ref` `ds_list`s of 70, 70, 73, 76 and 74
  triples. So the roll's sub-list is a `ref ds_list` of 380 entries on this
  build, stable within a session; who builds it is still not established.
- **Other readers of the list.** The same slot is loaded by `DropUniqueItems`,
  `DropItemHeroic`, `DropItemDebug`, `DropItem` itself, the traveling merchant
  and black market grids (`PopulateTravelingMerchantGrid`,
  `PopulateBlackMarketGrid`), `ReturnRandomSatanic`, `CreateShrineEffect`,
  `DoCraftResult` and several unnamed object events. An entry left in the list
  between rolls would be seen by all of them. Who builds the list, and whether
  it is rebuilt per zone or per load, is **not established**. **Static reading
  (2026-10-02, issue #74).**
- **The unique repository.** `GetUniqueRepoStruct(type, sub, b)` indexes a
  `global` three-level array `repo[type][sub][b]` (its slot name is also
  unresolved; type 3 takes a separate branch) with GameMaker's own bounds
  checks, so a list entry whose indices are out of range raises the runtime's
  array error rather than missing quietly. `sub` is 0 for the unique
  repository and `b` is the unique's own index: Liquor Holster is
  `{8, 0, 51}`, Lucifer's Crown `{0, 0, 85}` (ForgePact's validated pool table
  `kAngelicBases` holds exactly such triples). **Static reading (2026-10-02,
  issue #74)**, consistent with the pool's 47 validated entries measured in
  Live 1.
- **What a hit's placement reads.** `CreateDefaultParams(sub, b, 1.0)` builds
  its parameter struct from its three arguments, and reads no repository. The
  struct it returns is exactly `{j, b, c}`: `j` the first argument (the sub),
  `b` the second (the unique's index), `c` the third (1, the unique
  repository); it has no field `a` (**measured**, Live 2, below). The built
  item's `a` comes from `LootGroundCreate` itself: on both of its branches
  that build an item locally it stores a value of its own into the record's
  `a`, unconditionally and before the item instance exists, then hands the
  same struct (a second reference, not a copy) to the new item as its
  `itemDefinitionStruct`, sets the item's `itemType` from its own type
  argument, and calls `CreateItemNew` directly. `CreateItemNew` reads the
  item's `itemType` and the definition's `b`, `c` and `j` to look the item up
  (`c` choosing the unique or the normal repository) and the definition's
  `a` once, as the seed of the item's random rolls; it stores into none of
  those fields. An `a` written onto the struct when `CreateDefaultParams`
  returns is therefore overwritten, and one written at `CreateItemNew`'s
  entry is the one the item is built with. `LootGroundCreate`,
  `CreateLootInFreePos` and `LootGroundInit` read no repository. **Static
  reading (2026-10-02, issue #74; the chain read a second time for where the
  `a` is set)**; the record at `CreateItemNew`'s entry and what it keeps are
  **measured** (Live 3, below). Note that `type` reaches the
  placement from the list entry, not from the parameter struct, so rewriting
  the struct cannot change an item's type.
- **The forge selector.** The item the game builds carries the parameters as
  its `itemDefinitionStruct` (`{b, a, j, c}` for a roll-built item; `{w, j,
  b, a, c}` is the `sigdrop`/`InitItemFromJson` path's): `c` = 1 selects the unique
  repository and `b` the unique; `c` = 0 selects the normal repository, `b`
  the base item and `a` the seed or affix id. ForgePact's Custom Forge hook on
  `CreateItemNew` recognises an item by comparing every selector field, `t`
  against the item's `itemType` and `a`, `b`, `c`, `j` against its
  `itemDefinitionStruct`; its built-in entries are Headhunter
  `{t 8, a 777002, b 2, c 0, j 0}` and Tyrant's Crown
  `{t 0, a 777001, b 7, c 0, j 0}`. **Source reading** (ForgePact's own code);
  that an item built from those parameters is dressed as the signature item is
  **measured** (`sigdrop`, 30 of 30 and 17 of 17 on 2026-09-18; and through
  the game's own placement and `CreateItemNew`, Live 3, below). An item the
  Angelic roll builds carries `{b, a, j, c}` and no `w` (**measured**, Live 3,
  six vanilla hits); a `sigdrop` item, built through `InitItemFromJson`,
  carries `w` and `o` as well.
- **How #74 uses the list: a stand-in entry for the length of the roll.** While
  Headhunter's or Tyrant's Crown's panel switch is on, ForgePact pushes one
  entry per enabled item onto the list the roll draws from, the `ds_list` at
  `Controller_obj.lootListUnique[5]` (the layout above; never the outer
  array), with `ds_list_add` before the roll's first original call, and cuts
  them off its tail with `ds_list_delete` after its last, under a scope guard,
  so between rolls the list is exactly the game's own and none of the other
  readers above ever sees the entries. Each entry is a **stand-in**: a real
  Angelic unique of the same `type`, because the picker's filters and the
  rate need a real definition and the item's type comes from the entry
  (Headhunter's stand-in is Liquor Holster `{8, 0, 51}`; Tyrant's Crown's is a
  helmet chosen when the pool is built, named in the switch-on log line).
  Right after the push ForgePact reads the outer variable again by name off
  the `Controller_obj` instance (a fresh `variable_instance_get`, never the
  handle it pushed onto), takes the element at the same index, and counts the
  push as visible only when that element is the same `ds_list` id and the
  sub-list's size and tail hold what was pushed (the **held read-back**).
  When they do not (another id, not a list, or a short tail), it takes the
  entries off the id it pushed onto, logs one line, counts the roll in
  `anomalies=` and attributes nothing in it. A `ds_list` id is a handle into
  the runtime's own store, so the read-back cannot be fooled by a copy of the
  sub-list; it still cannot show that the roll reads that element. The
  removal checks the same tail: if the sub-list changed during the roll,
  nothing is removed, one anomaly line is logged and the roll is counted in
  `anomalies=`. ForgePact resolves the list by a name and an index
  (`kAngelicListVar`, `lootListUnique` since Live 2's reach check passed on
  it, and `kAngelicListIndex` 5), checks that the element is a live `ds_list` of
  at least 10 entries, each an array of three numbers, and prints it on the
  status lines as `list=<name>[<index>]:<size>` (for example
  `lootListUnique[5]:380`), or `none` / `missing`. The live-list check decides
  on the element as it was read, with no allow-list of handle kinds. It first
  refuses, before any conversion, an element of a kind that can never be a
  handle (array, string, struct, undefined or null) as `never a handle`,
  because converting one is, by source reading, the runner's own REAL
  conversion, which raises a runner error for an array and for undefined
  (measured) and, by that source reading alone, for a string, a struct and
  null, whose error text has not been captured (§5.4); a real, a ref and
  every other kind go on. Then a numeric conversion serves only to refuse a
  value that cannot be converted, is non-finite or is negative, and then
  `ds_exists` is asked of the value itself with 2 (`ds_type_list`). A value
  that cannot be converted is refused before `ds_exists` is asked; that is a
  failed conversion, not a kind rule. The
  refusal reads `Controller_obj.<name>[<i>] is not a ds_list (kind=<kind>,
  <step>)`, naming the kind it got (`real`, `int32`, `int64`, `bool`,
  `string`, `struct`, `array`, `ptr`, `undefined`, `null`, `ref`, else
  `kind<N>`) and the step that refused (`never a handle`, `id unreadable`, `id non-finite`,
  `id <value>`, `ds_exists threw` or `ds_exists false`); an element that
  cannot be read at all is `[<i>] array_get threw`.

  A hit is **typed** before anything is attributed to it. A third inline
  detour, on `GetUniqueRepoStruct`, records the `(type, sub, b)` of the latest
  definition read while the roll is in progress, cleared before each original
  call. When the roll calls `CreateDefaultParams`, the hit takes that record
  only if its sub and b equal the call's own first two arguments; otherwise
  the hit is **untyped**: it stays the game's own, is never rewritten, and is
  counted in `untyped=`. A typed hit is a candidate only when its whole triple
  `(type, sub, b)` is the stand-in's, so another unique that shares the
  stand-in's sub and b under a different type (Liquor Holster's `0/51` is also
  a type 10 unique's) is never taken for it. The picker cannot tell the added
  entry from the vanilla ones, so a candidate is the mod item's with
  probability 1 / (n + 1), `n` being how often the vanilla sub-list holds
  that same whole triple. The player build always pushes one entry per item; the
  research build's `angelicprobe inject copies <k>` pushes k, which makes the
  share m·k / (n + m·k) for m items sharing a stand-in. On the mod item's hit
  ForgePact rewrites, at `CreateItemNew`'s entry, the item's
  `itemDefinitionStruct` (a missing field is created) to the item's own `a`,
  `b`, `c` 0, `j` 0 and reads them back (a value that does not read back is a
  refusal: the record is put back, the game builds its stand-in, and the item
  stays off for the session), and the game's `CreateItemNew` builds it from
  that record, where the forge selector above recognises it (**measured**,
  Live 3, below: 48 of 48 Headhunters (46 with Headhunter alone on, 2 with
  both on) and 11 of 11 Tyrant's Crowns built by
  the game from a record written there). One hit is one item, in place of what
  the roll would have dropped. The switch is honoured only while all four
  hooks (`DropItemAngelicChance`, `CreateDefaultParams`,
  `GetUniqueRepoStruct` and `CreateItemNew`) are inline detours. **Design, #74 (2026-10-02, replan 1; the sub-list since
  replan 2)**, as the plugin implements it. Of the three questions only a live
  session answers, Live 1 answered **typing**, Live 2 **reach** (the roll's
  picker draws the entries the plugin pushes; the held read-back alone shows
  only that the sub-list holds them) and Live 3 the **build**: the game
  builds exactly one dressed item per hit that falls to a mod item (below).
  Live 2 could not ask that, because its rewrite, on the struct
  `CreateDefaultParams` returns, refused on every hit: the struct has no
  field `a` to rewrite. The rewrite has sat at `CreateItemNew`'s entry since.
- **Measured (Live 1, list injection, 2026-10-02, research dll f7560e80…):
  typing.** With the roll's chance raised by the research lever and both
  switches off, 59 rolls gave 57 hits (`cdpCalls=70`, `detect=detoured`, the
  detection's positive control). Every one was typed: `untyped=0`, and on
  each the built item's `itemType` equalled the type of the latest
  `GetUniqueRepoStruct` read inside the roll (`typeAgree=57`,
  `typeDisagree=0`; 85 and then 87 of 87 later in the session). Every hit line
  carried a `builtType` number and `lootDelta=1`: one `Loot_Ground_obj`
  instance per hit. So the latest definition read before
  `CreateDefaultParams` is the picked entry's, for the game's own entries; a
  hit on a pushed entry has not been seen. With nothing pushed, one of the 57
  hits carried a stand-in's sub and b (`standinPicks=1`), the baseline share
  1/57 that reach is measured against.
- **Measured (Live 2, list injection, 2026-10-02, research dll e30981d5…):
  typing, reach and the parameter struct.** Typing held again: 46 of 46
  vanilla hits typed (`untyped=0`, `typeAgree=46`, `typeDisagree=0`; 211
  agreements and no disagreement by the end). With both switches off,
  2 of 46 hits carried the stand-in's sub and b (`standinPicks=2`, p0 = 0.043). With Headhunter's
  switch forced on and the research build pushing 200 copies of Liquor
  Holster's entry onto `lootListUnique[5]` per roll (`injected=22800` over
  114 rolls, the held read-back never failing, `heldMiss=0`), 65 of the next
  80 hits fell on it (p1 = 0.81): **reach passes**, the roll draws what is
  pushed onto that sub-list. On each of those 65 hits the returned
  `CreateDefaultParams` struct read `{"b":51.0,"j":0.0,"c":1.0}`, no field
  `a`; the rewrite refused (`no field a`), wrote nothing, and the game placed
  its own Liquor Holster (`built=0`). That is a measurement of the struct and
  of the plugin's rewrite, not of whether the game would build the item from
  parameters that carry its `a`. The research build's replace mode (the
  stand-in removed and the item spawned in its place) worked on 42 of 42
  hits. The runner's YYError count rose from 1 to 37 in the first kill batch
  (`report#2` x30) and then held; its cause is not established.
- **Measured (Live 3, list injection, 2026-10-02, research dll e0749368…):
  where the id reaches the built item, and the build.** With the rewrite
  moved to `CreateItemNew`'s entry and both switches off, six vanilla hits
  printed the record there and the built definition: the record's fields are
  `b`, `a`, `j`, `c`, its `a` already a number (for example
  `{"b":9.0,"a":270500966.0,"j":6.0,"c":1.0}`, built as `itemType=3` with the
  same four values), so `LootGroundCreate`'s `a` is on the record by then and
  the built definition keeps every value. Typing held (47 of 47, `untyped=0`,
  `typeDisagree=0`; p0 = 2/47). With Headhunter forced and 200 copies pushed
  per roll, 46 of the next 62 hits fell on Liquor Holster's entry (p1 = 0.742,
  `heldMiss=0`), and on every one the record went from
  `{"b":51.0,"a":648002927.0,"j":0.0,"c":1.0}` (its own `a` each time) to
  `{"b":2.0,"a":777002.0,"j":0.0,"c":0.0}` and the game built
  `itemType=8` with exactly those values: `built=` and `belt=` +46,
  `refused=0`, `lootDelta=1` on every hit, the ground labelled
  `Headhunter`, and the owner, hovering one, read a Headhunter. With both
  forced, 11 of 15 hits built Tyrant's Crown (`picked 0/0/86`, stand-in Mask
  of the Celestial) and 2 Headhunter, `built=` growth equal to `ourHits=`
  growth. Switching both off left the next 22 hits vanilla and the list's six
  sizes as before. So a `c` 0 record written at `CreateItemNew`'s entry is
  built through the game's own placement and constructor as the signature
  item, one per hit, in place of the stand-in. The YYError count rose from 1
  to 19 between the read just before the layout dump and the end of the
  first kill batch, all of it before anything was pushed (`report#2` x15, message
  `REAL argument incorrect type array`), and then held; which step raises it
  is not established. An arithmetic fit on Live 2's and Live 3's counts puts
  it on the research scan's numeric conversion of 15 array and 3 string
  variables (18 per scan, §5.4); ForgePact's list check now refuses those
  kinds as `never a handle` before converting. Live 4 can show whether the
  count stops rising, not the strings' share of it, since strings are no
  longer converted. A hit at the natural chance was not observed (the
  research lever held the chance at 1e9).
- **Measured (Live 4, list injection, 2026-10-02, research dll 4b5994c3…,
  ForgePact `ed59983`): the research scan's runner errors.** With the list
  check refusing a kind that can never be a handle before converting it, in
  town with no kills, a lone `angelicprobe inject auto` (`list
  lootListUnique[5]:380`) and then `angelicprobe list` left the runner's
  YYError total at 1 with no new report, each read taken at least 35 s after
  the command. That one report was raised in the menus before any command
  (`Unable to find any instance for object index ...`). The scan refused the
  same 15 array and 3 string variables as `never a handle`, none as
  `id unreadable`, and still accepted the real list, a ref
  (`candidate lootListUnique array_length=6 at=5 ds_list_size=380`). On the
  earlier builds each scan had added 18. So the scan's numeric conversions of
  those elements are measured as the cause of Live 2's and Live 3's rise; how
  the 18 split between arrays and strings stays the arithmetic fit (§5.4),
  since Live 4 refused both kinds. A struct or a null element was not met.
- **The die.** The rate comes from a zero-argument method on a member of the
  picked definition, scaled by one global value read when the roll starts;
  neither is identified (`droprate.base` is the plausible reading). The roll
  draws a uniform integer up to that rate and hits when the draw is below the
  chance. With the measured chances of 1195-1526 against rates in the millions,
  that is about one hit in several thousand rolls, so a session should not
  expect a natural hit. **Static reading (2026-10-02, issue #74).**
- **A hit.** Only on a hit does the roll call `CreateDefaultParams` (sub, b and
  a constant), and then, by a direct call, the routine ForgePact hooks as
  `LootGroundCreate`, with the roll's position and the picked item's
  parameters. `CreateDefaultParams` is called nowhere else inside
  the roll, so **a `CreateDefaultParams` call while the roll is running marks a
  hit**. **Static reading (2026-10-02, issue #74)**, consistent with the
  measured count of zero `CreateDefaultParams` calls inside the roll over 374
  misses. A table-only hook on `LootGroundCreate` cannot see that direct call
  (§ 5.1); the `CreateDefaultParams` inline detour does, **measured** in
  session 1, which is why ForgePact #74 detects hits there.
- **The chance's composition** is computed by the caller, `DropItem`, and is
  **not established** (out of scope for #74).
- `droprate.base` of some uniques: Marcher's of Hatred 4,266,000; Annihilator
  4,158,450; Tayrel's Chestplate 25,000,000; Lucifer's Crown 111,111,111.
  **Measured.**
- A `lootListUnique` instance variable on `Loot_Manager_obj` was **not
  observed**: `variable_instance_exists` answered false on the instance found
  by name, with no positive control on that instance recorded (2026-09-23).
  The static reading of 2026-10-02 puts the list on `Controller_obj` (above),
  so this was measured on another scope than the list's.
- `DropItem` also runs for breakable props, and ordinary drops call
  `LootGroundCreate` (and `CreateDefaultParams`) directly from inside it.
  **Measured.**

[angelic roll, Results](../ForgePact/docs/angelic-roll-hook-research.md#results),
[Session 2 (#74) Results](../ForgePact/docs/angelic-roll-hook-research.md#results-1),
[Session 3 (#74, list injection)](../ForgePact/docs/angelic-roll-hook-research.md#session-3-list-injection-issue-74),
[Session 4 (#74, the list layout)](../ForgePact/docs/angelic-roll-hook-research.md#session-4-the-list-layout-issue-74),
[Session 5 (#74, the id on the built item)](../ForgePact/docs/angelic-roll-hook-research.md#session-5-the-id-on-the-built-item-issue-74),
[curated record](../hs-game-sdk/curated/angelic_list_measurements.json),
[Decision](../ForgePact/docs/angelic-roll-hook-research.md#decision),
[angelic drop, the game's own mechanism](../ForgePact/docs/angelic-drop-research.md#oyunun-kendi-mekanizması-statik-okuma-canlı-ölçülen-yalnızca-buff-yokken-zarın-hiç-atılmaması),
[ForgePact guide, Known Limitations](submodules/ForgePact/instructions.md#known-limitations--gaps)

### 13.5 The kill path

`EnemyDestroyKillProc` is called with the enemy as `self` and also with the player
as `self` (no drop from the second); the killer argument can be a projectile.
`Enemy_Death_Effect_obj` is not made on every kill (50 for 307 kill-proc calls).
Drops read `enemyRarity`, `x` and `y` off the dying enemy. **Measured.**
[Headhunter, typed instance ids](../ForgePact/docs/headhunter-dispatch-verification.md#follow-up-falors-first-test-typed-instance-ids)

### 13.6 World chests and loot goblins

- **World chests.** A world chest (`Chest_Drop_obj`) drops its loot through `DropItem`, like a kill.
  - The call's first argument is the chest's opening rarity: 2 is wooden, 3 golden, 4 crystal.
  - A golden chest takes a Basic Key (type 12, base 0); a crystal chest takes a Crystal Key (12:1).
  - **Measured** 2026-09-24 on the 23 chests AFK FARM recorded; each one's rarity matched its sprite.
- **Loot goblins.** There are five: `Goblin_Treasure_obj`, `Goblin_Rune_obj`, `Goblin_Ore_obj`, `Goblin_Orb_obj` and `Goblin_Shadow_obj`.
  - A dying goblin drops its items through `DropItem`, at rank 5 with the goblins' own magic find. **Static reading.**
  - That path is **measured** for treasure, rune and shadow goblins: 15 packets AFK FARM recorded on 2026-09-24. Orb and ore goblins were not observed.
  - A goblin's gold shower (`DropGold`) and the shadow goblin's Dimensional Shards (`LootGroundCreate`, type 13, base 1) are made outside `DropItem`, so a `DropItem` replay does not bring them. **Static reading.**

AFK FARM design, 0.8 (a private repository)

### 13.7 Monster ranks: names, health, damage, XP and drop values

From AFK FARM's 6,471 recorded packets and 214 capture sessions, 2026-09-17 to 09-24. Two game builds, pe6aaa6779 and pe6a9ed3ee.

- **Rank values.** An ordinary monster's `enemyRarity` is 1-4, and `DropItem`'s first argument is the same number. In every packet `killStatistic` equals the rank. **Measured.**
  - Loot goblins drop at 5, while their own `enemyRarity` stays 1, 3 or 4.
  - Every special-content monster seen dropped at 4.
- **Names (inferred).** The save's kill counters are Total, Common, Champion, Ancient, Legion and Fallen. On the save with the most kills, Common, Champion, Ancient and Legion add up exactly to the total, and their proportions fit only rank 1 Common, 2 Champion, 3 Ancient, 4 Legion. **Inferred from the kill counters**, and since ForgePact#159 also backed by a player's on-screen report (a monster raised to rank 3 shows as an Ancient, with a yellow name, and one raised to rank 4 as a Legion). That report is the player's, not a measurement of ours. ForgePact's World › Monster Rarity rows use these names since #159 (Ancient writes rank 3, Legion rank 4); its code, its commands (`rarity`, `bossrarity`), its config keys (`rarity_rare`, `rarity_ancient`) and its Bosses select still say rare for rank 3 and ancient for rank 4 (ForgePact#161 tracks the player-visible ones).
- **Rank multipliers**, next to rank 1. Medians over 41-48 pairs of the same monster object in the same room. **Measured.**

  | Rank | Health | Damage | XP |
  | --- | --- | --- | --- |
  | 2 | ×1.84 | ×1.27 | ×2.75 |
  | 3 | ×2.98 | ×1.53 | ×4.25 |
  | 4 | ×4.23 | ×1.90 | ×6.25 |

  The XP multipliers are exact constants.
- **Protected drop values by rank**: `dCommonChance` / `dCommonDropMult` / `dSatanicDropMult` / `dSlots`. They are identical within a rank. **Measured.**

  | Source | dCommonChance | dCommonDropMult | dSatanicDropMult | dSlots |
  | --- | --- | --- | --- | --- |
  | Rank 1 | 4 | 11 | 1 | 1 |
  | Rank 2 | 20 | 20 | 0.925 | 1-3 |
  | Rank 3 | 36 | 42 | 0.475 | 2-5 |
  | Rank 4 | 50 | 58 | 0.285 | 4-8 |
  | Goblins | 100 | mostly 42 | mostly 0.475 | 1-7 |
  | Abyss chest | 58 | 70 | 0.185 | 8 |

- **The monster's drop table also rises with rank.** For example, runes (drop type 4) are 12/22/34/100 and dungeon keys (type 12) 5/40/75/100 by rank 1-4. **Measured.**
- **Kill mix.** Without ForgePact's rarity sliders, over 2,994 kills: 70.1% rank 1, 16.9% rank 2, 10.4% rank 3, 0.1% rank 4. With the sliders on, over 21,122 kills: 35.1 / 18.9 / 32.1 / 13.8%. **Measured.**
- **What a packet carries** (see AFK FARM's `Packet.hpp`):
  - `monster_key`, which equals the snapshot's `nameKey` (for example `e_orc_warrior_3`; the suffix is `_1` for rank 1, `_2` for rank 2 and `_3` for ranks 3 and 4);
  - the display `name`, `affixList`, `isRanged`, the fire, cold and poison immunities and `moveSpeed`;
  - protected health, damage and XP.

  So AFK FARM's town builds a bestiary of real monsters from them.
- **A monster's damage and XP live behind protected-store keys. Measured 2026-10-02** (ForgePact#44's Live procedure 1b, an identity control on the research probe's read path): `damage`, `killExperience` and `experience` do not hold the values themselves. Like `enemy_hp`, each holds a protected-store key: 176880, 176863 and 176879 on the ordinary monsters and the rank-1 Karp King read, 176876, 176859 and 176875 on the rank-4 Karp King. The record a key names, read with `PC_GetVariableGMLWrapper(key)` (which agreed with `GPV` on `gDataProtected[177]` in the same session), holds the monster's damage and XP. An ordinary `Skeleton_Mage_Fire_obj` raised by ForgePact's Monster Rarity sliders to rank 3 and 4 read, through those keys, damage 257 / 360 / 515 (×1.40, ×2.00 against the table's ×1.53, ×1.90, within 10%) and XP on kill 221 / 943 / 1387 (×4.27, ×6.28 against the exact ×4.25, ×6.25, within 2%; the record behind `experience`, 96 / 410 / 603, moved the same way). So the records behind `damage` and `killExperience` hold a monster's damage and its XP on kill. Reading either variable directly (`variable_instance_get(inst, "damage")`) returns the key, a plausible-looking number that has nothing to do with damage. The same spawns' health was not a control: ×5.69 at rank 3 and ×5.31 at rank 4, one spawn each. MK15-MK17 in `hs-game-sdk/curated/monster_rank_measurements.json`.
- **Bosses at a forced rank.** A boss is an instance whose object descends from `Enemy_Child_Boss_obj`. None is in AFK FARM's packets; these rows are ForgePact's Bosses control (issue #44) writing the rank at the entry of `EnemyRaritySettings`, from Live procedure 1 and Live procedure 1b, 2026-10-02 (Nightmare, Outskirts of Inoya, zone level 170; one spawn and one kill per row; [boss rarity, Live procedure 1](../ForgePact/docs/boss-rarity-research.md#live-procedure-1) and [Live procedure 1b](../ForgePact/docs/boss-rarity-research.md#live-procedure-1b)). Health was read through the protected-store getter the probe's own control proved. In Live 1 damage and XP were read only through unproven keys, so they are **not observed** there; Live 1b counted the same key reads of `damage` and `killExperience` (the record each variable's key names, not the variable) because its identity control (above) proved them.

  | Boss | Session | Rank written | Health | Health ratio to its rank-1 self | Damage, XP | `DropItem` rank argument | Drops per kill (`itemdrops.jsonl` lines) |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | `Karp_King_obj` | Live 1 | none (rank 1) | 44,625,000 (two spawns) | 1 | not observed | no line at its traced death | 0 traced; 20 on an untraced kill |
  | `Karp_King_obj` | Live 1 | 4 | 252,242,812 | **×5.65** (5.6525) | not observed | no line at its traced death | 0 (traced) |
  | `Karp_King_obj` | Live 1 | 3 | not read | — | not observed | 3 (one line, no rank-1 anchor) | 20 (traced) |
  | `Damien_obj` | Live 1 | 4 | 159,906,250 | no rank-1 base | not observed | not traced | not counted |
  | `Uber_Damien_obj` | Live 1 | 4 | 1,306,210,937 | no rank-1 base | not observed | not traced | not counted |
  | `Uber_Anubis_obj` | Live 1 | 4 | 4,451,343,750 | no rank-1 base | not observed | not traced | not counted |
  | `Karp_King_obj` | Live 1b | none (rank 1) | 44,625,000 (three spawns) | 1 | read through the keys in `damage` and `killExperience`: 217, 4,950 | 1 | 10 (traced) |
  | `Karp_King_obj` | Live 1b | 4 | 210,992,578 | **×4.73** (4.7281) | read through the keys in `damage` and `killExperience`: 455 (**×2.10**, 2.0968); 30,940 (**×6.25**, 6.2505) | **4** | 12 (traced) |

  - **Health. Measured 2026-10-02:** one Karp King, raised to rank 4 by ForgePact with its 3-affix top-up, had ×5.65 its rank-1 health in Live 1 (affixes 16 Multishot, 17 Treasure Gobbler, 25 Pyromaniac) and ×4.73 in Live 1b (12 Fire Enchanted, 20 Punisher, 31 Antimagus), both above the ordinary monsters' rank-4 median of ×4.23. **Not established:** whether a boss scales on health differently from an ordinary monster. Each sample's topped-up affixes were built into the same health, the two sessions disagree, and neither had a health control (Live 1b's ordinary monster read ×5.31 at rank 4), so these are the feature's effect rather than the game's rank scaling for a boss alone. `hs_game_sdk.monster_rank_model` keeps this as the open hypothesis `boss_hp_follows_rank_table`; MK6, MK7, MK9, MK19 and MK20 in `hs-game-sdk/curated/monster_rank_measurements.json`.
  - **Damage and XP. Measured 2026-10-02** (Live procedure 1b, one Karp King raised to rank 4, the same spawn; each value is the record the variable's protected-store key names, not the variable): damage ×2.10 (217 -> 455, through `damage`'s key) and XP on kill ×6.25 (4,950 -> 30,940, through `killExperience`'s key; `experience`'s record 2,152 -> 13,452, ×6.25). XP took the table's exact rank-4 row; damage rose ×2.10 against the table's ×1.90; whether a boss's damage follows the row is not established: 0.4% outside the 10% the identity control was held to, while the control itself read 8.4% below the table at rank 3 and 5.5% above it at rank 4 (×2.00), and on one boss, one spawn, whose affixes differed from the control's. The same unmatched affixes leave XP open too: `monster_rank_model`: `boss_xp_follows_rank_table` `None` (measured ×6.2505 against ×6.25 on one boss, not established), `boss_damage_follows_rank_table` `None` (open) (MK21, MK22).
  - **The rank written holds through the setup. Measured 2026-10-02** (a readback of the hook's own write): each of the five raised bosses entered `EnemyRaritySettings` at `enemyRarity` 1 and still carried 3 or 4 at its exit. The Monster Rarity sliders at 100% ancient left a Karp King at 1.
  - **Drop rank. Measured 2026-10-02** (Live procedure 1b): the unraised Karp King died with `DropItem`'s first argument 1 and the one raised to rank 4 with 4, while the same session's ordinary control (a `Skeleton_Mage_Fire_obj` the sliders raised to 4) died with 4, as in Live 1 (MK14, MK18). On this one boss the drop rank was the rank written, but the spawn carried the same affix top-up the identity control did not share, so whether a raised boss's drop rank is the rank written is not established: `boss_drop_rank_reaches_dropitem` `None` (MK23). No `DropItemBoss` call was seen at either death. In Live 1 the rank-1 and rank-4 Karp Kings' traced deaths had printed no `DropItem` line and dropped nothing, so that session had no anchor.
  - **Drops per kill: not observed as an effect.** Live 1b's traced rank-1 kill added 10 lines, the rank-4 one 12; one kill each, with other monsters dying nearby, so not a count of extra drops (MK24). A boss's death sometimes entered none of the instrumented drop routines (no `DropItem`/`DropItemBoss` call, no gold, no gem or rune counter, no `itemdrops.jsonl` line; `DropBossParts` was not instrumented, so whether such a death ran any drop routine at all is not established): Live 1 saw it on two traced kills, Live 1b on an untraced one 1,200 px from the hero, and Live 1b also on an ordinary rank-3 monster killed the same way. What decides it is not established. The `DropBossGems` and `DropBossRunes` counters stayed 0 at every Live 1b kill, raised or not.
  - **The look. Not observed:** in Live 1b the raised Karp King's HUD name bar kept the ordinary style (after a control showed that writing `enemyRarity` after the setup did not restyle it within 2 s: one Karp King, one shot), and its body showed no change but a fire burst whose source could not be separated from its Fire Enchanted affix.

### 13.8 Monsters of special content (`specialType`)

A monster that special content spawned carries a non-zero `specialType` in its snapshot. It still drops through the ordinary `DropItem` at its own rank, so its packets replay like any other. Each value below is **measured** by association, from AFK FARM's recordings:
- **9 and 10:** died within two minutes before an Abyss chest opened (341 kills in Act 3-3). The Abyss chest itself drops through `DropItem` with arguments 4, 4 (`dSlots` 8).
- **4:** the Unholy Siege's (Summoning Portal) monsters in Act 6-5. They carry drop type 56 (tarot) at 100.
- **1:** most likely a Chaos Pillar's pack (1,100 kills in Acts 1 and 3, always drop type 54). **Unconfirmed.**
- **3:** unknown.

### 13.9 Elite affixes by runtime index

`affixList` holds runtime affix indexes. Slots from 40 up are flags (zones, states), not affixes. The names below are ForgePact's `kHhAffixNames`; "live" marks those ForgePact confirmed in a running game. The game ships affix names only (41 of them, `translationsEnemy.csv`), with no descriptions.
- 0 Champion, 1 Fractal, 2 Raging, 3 Enraged, 4 Haunted, 5 Vampiric, 6 Burst Shot, 7 Possessed, 8 Extra Fast, 9 Extra Strong: live.
- 10 Stoneskin, 11 Cold Enchanted, 12 Fire Enchanted, 13 Lightning Enchanted, 14 Magic Resistant, 15 Manaburn, 16 Multishot, 17 Treasure Gobbler, 18 Arcana's Curse, 19 Venomous, 20 Punisher, 21 Fallen Angel: live.
- 22-24 are three of Commander, Guardian of Hell, Bloating and Sharpshooter (unconfirmed).
- 25 Pyromaniac (live) and 26 Berserker (inferred). 27-29 are unconfirmed.
- 30 Thick Skin and 31 Antimagus: live.
- 32 Colossal, 33 Stealthy, 34 Time Lapsing and 35 Wasped.
- 36 Blazing (live), 37 Thunder Caller and 38 Meteoric (live).

**Fallen Angel** is the only kill source of Angelic Keys (12:8) on Hell, per the game's journal text. All 395 recorded packets with drop type 16 carried it. **Measured.**

### 13.10 Vendors, gold and stackable goods

- **Vendor stock** (**static reading**, at call-skeleton level):
  - the town merchant fills its grid from the zone's normal equipment list;
  - the Traveling Merchant fills it from the unique list;
  - Veras's Black Market fills it from uniques and exclusives.

  No stock routine offers keys, fragments, materials, socketables or relics. The gamble is not a vendor routine or a named script: it is the gamba machine object, `Slot_Machine_01_obj`, whose logic lives in its own events (§ 20).
- **Selling to a vendor pays** the item's info value 9 × the stack, rounded up. Materials are worth a token 10, runes and gems 125-381, most keys 15-5,000. **Static reading.**
- **Gold** is account-wide, with separate pools for softcore, hardcore and Blood Pact (`hs2saves\shop.ini`, `[gold]`). The offline cap is 500,000,000.
  - `PickUpGoldCheck(GetCounterHash(), amount, …)` is the only call that changes the balance, both credits and debits. `GoldLogAdd` only writes the UI log.
  - AFK FARM's `worker pay` and `worker credit` (0.9) use `PickUpGoldCheck` with a fresh hash, one receipt per request. **Measured** 2026-09-25: a `worker credit` of 5,000 raised the balance by exactly 5,000.
- **A monster's gold drop is one coin** (ForgePact #77, 2026-09-27):
  - `DropMonsterGold` (six arguments) applies the profile's gold getters, rounds an amount down and calls `DropGold` **once**, directly, with nine arguments; it has no loop. `DropGold` creates **one** instance and sets its value with one call to that coin's `m_SetGoldValue` method, then sets its spread and log fields. **Static reading.**
  - The coin is a `Coin_obj`, and coins are not `Loot_Ground_obj` instances: with each call repeated a hundred times (below), a count of `Coin_obj` by name rose from 0 to 20,000 over two drops while `Loot_Ground_obj` stayed at 23. **Measured.**
  - `DropGold`'s arguments as logged on four x1 drops: argument 0 a 40-character hex string, the same on every call; 1 and 2 the drop position (equal to `DropMonsterGold`'s 0 and 1); 3 always 1; **4 the only one that varied per drop** (51, 59, 31, 29); 5-8 undefined. Index 4 is the amount's shape and the static reading's candidate. **Measured.**
  - Argument 4 held against the gold the game showed, on the player build with ForgePact's Gold multiplier at x100 (ForgePact #77's Live 2, 2026-09-27): the hook scaled the first coin's argument 4 from 44 to 4400, and the HUD gold rose from 188948 to 189019 at x1 (+71), then to 201889 at x100 (+12870, two stacks the screen showed as 5720 and 7150), with no freeze at the kill or the pickup. So scaling argument 4 scales the gold picked up: the credited stacks were about 1.3 x the scaled argument 4 on this character (5720 = 4400 x 1.3), so what the pickup credits is argument 4 times a further factor whose source (a gold-find stat at pickup?) is not established. **Measured**, monster gold only, one session; whether the game caps or rounds a coin's value is not established.
  - One `DropGold` per `DropMonsterGold` at x1 (4 and 4). A mod that repeats both calls a hundred times multiplies, because each repeated `DropMonsterGold` reaches the hooked `DropGold` again: two drops made 200 hooked `DropGold` calls, each running the original a hundred times, and 20,000 coins; the frame stalled 8.4 s at the drop and 6.5 s again at the pickup, and the game recovered once the coins were gone. Scale the one coin's amount instead. **Measured.**

  [dev2 bug batch, #77](../ForgePact/docs/dev2-bug-batch-research.md#77-dropmult-gold-100-froze-the-game)
- **`LootGroundCreate(x, y, itemType, def, …)`** makes a floor item whose Create event builds it (`CreateItemNew`). `def` carries `b` (base), `j`, `c` (0 normal, 1 unique repository) and optional `o` (stack) and `a` (seed). Rarity is not an argument. **Measured** for types 14 and 15 through AFK FARM's workers. Type 12 was **measured** on 2026-09-25: a town delivery made Basic Keys (12:0) and Cellar Keys (12:10) with the right `b` and `o`. Type 13 was **measured** the same day: a town delivery made a Battle Fragment (13:0) with the right `b` and `o`, and the game gave it a new seed (`a`).

AFK FARM design, 0.9 (a private repository)

---

## 14. Satanic Zone and Special Content

### 14.1 Satanic Zone modifiers

- **`LoadSatanicZone` is called by the game about 150-160 times a second**, with
  one argument, the resolved zone's room index. The 2026-09-10 "0 calls" was an
  instrument artefact: that probe ran before `HookOneScript` installed its
  inline detour (2026-09-12), so it only saw table-routed calls. It answers
  "is the player in that act-zone room?": true for `Act_01_01`'s room while the
  player stands in it, false for the resolved room while the player is
  elsewhere, and false for an ineligible room even with the player in it (the
  town), so it is not a plain "player room == store" test. **Measured
  2026-10-03 and 2026-10-04.**
- **The zone is a writable protected value.** `Controller_obj.satanicZone` is a
  *key* (`162966.0`); `GPV(key)` is a room **asset index** (20 = `Act_02_04`,
  44 = `Act_04_03`, 235 = `Town_01_rm`; act zones run ~1-117, towns 235-243),
  and `SPV(key, <room>)` sets it, sticking until the next roll. It is a roll: it
  moved 20 -> 4 on its own within one session, and `GetSatanicZoneOffline(<n>)`
  re-rolled it (4 -> 28). **Measured 2026-10-03.**
- **The in-zone effect follows that state.** Entering `Act_01_01` with the store
  already naming its room added five `Draw_Player_Buff_obj` buffs to the player
  (the same slots read empty with the store elsewhere) and the player saw the
  zone's buffs and debuffs on the buff bar; releasing the store mid-zone did not
  remove objects already applied. **Measured 2026-10-04.** A relic drop in a
  satanic zone is still unwatched.
- **The world map's red marker is a separate layer.** `UI_Map_Zone_Button_obj`
  carries a per-node `isSatanic` flag with its own image/timer/scale fields, set
  when the game itself resolves a zone; the store, the game's own re-rolls and
  invoking every node's own `m_RefreshNode` left it unchanged. **Measured
  2026-10-04.**
- Forcing `LoadSatanicZone` to answer true on every call in town (a room it
  otherwise answers false for) changed nothing visible (player buffs, HUD and
  before/after screenshots identical). **Measured 2026-10-03.** The force's own
  effect in an eligible zone is still unwatched (the confirmed buffs above came
  from the store write, not the force); whether the effects are event/entry-
  driven rather than per-frame is **not established**, and the kill path
  (`ProjectileKill00Universal` -> the two satanic relic routines) is an
  untested candidate consumer.
- The buff and debuff arrays hold unique ids in 1–25 / 1–26 and re-roll on their
  own every few tens of seconds to minutes, not in step with room changes;
  overwriting them in place is picked up without a room change.
- With no arguments `GetSatanicZoneOffline` returns undefined,
  `ReturnSatanicZoneBuffs`/`Debuffs` return real 0 and `LoadRandomSatanicStat`
  throws.

**Measured 2026-09-10, 2026-10-03 and 2026-10-04.** The buff and debuff names are in
[`hs-game-sdk/curated/satanic_zone.json`](../hs-game-sdk/curated/satanic_zone.json).
[satanic zone, Findings](../ForgePact/docs/satanic-zone-mods-research.md#findings-2026-09-10-live-session),
[Live 3](../ForgePact/docs/satanic-zone-mods-research.md#live-3-2026-10-03-issue-155-the-re-probe-and-the-zone-value-is-writable),
[Live 4](../ForgePact/docs/satanic-zone-mods-research.md#live-4-2026-10-04-what-loadsataniczone-really-answers-and-the-map-marker),
[The mechanism that shipped](../ForgePact/docs/satanic-zone-mods-research.md#the-mechanism-that-shipped-poll-and-correct-not-a-routine-hook)

### 14.2 `global.eSt`: the special-content parameters

`global.eSt` has 11 slots, refilled at **every Room Start** (`Controller_obj`'s
Room Start event) from five-argument `ReturnSpecificStat` calls, so a single write
is undone by the next room. Measured values on one character:

| Slot | Stat | Content | Measured |
|---|---|---|---|
| 0 | 756 | shared gate for every mechanic | 35 |
| 1, 2, 3 | 675, 682, 676 | Chaos Pillars | 50, 3, 4 |
| 4, 5 | 705, 721 | Battlefield | 12, 25 |
| 6 | 666 | Chaos Tower | 15 |
| 7 | 813 | Cursed Orb | 0 |
| 8 | 770 | Rift | 14 |
| 9 | 723 | Shadow Realm | 18 |
| 10 | 823 | Summon Portal | 28 |

A mechanic runs only if `eSt[0] <= 0` **and** its own slot is `> 0` — the two
compare in opposite directions (Chaos Pillars uses another pattern; Abyss and the
Traveling Merchant read only slot 0). The values are real parameters, not
divisors: setting Battlefield's or Rift's slot to 1 stopped them. Forcing the
values every frame *after* Room Start is safe. **Measured**; the comparison
directions are a **static reading**. Also in
[`hs-game-sdk/curated/special_content.json`](../hs-game-sdk/curated/special_content.json).
[S10, eSt is filled by the game](../ForgePact/docs/S10-special-content-notes.md#esti-oyun-kendisi-dolduruyor),
[two gates in opposite directions](../ForgePact/docs/S10-special-content-notes.md#iki-kapi-ters-yonde),
[two disproved assumptions](../ForgePact/docs/S10-special-content-notes.md#yanlis-oldugu-kanitlanan-iki-varsayim)

### 14.3 Mechanic markers

- The game places one marker per map for each `Spawn_*_obj`, all children of
  `Spawn_Mechanic_Parent_obj` (Abyss, Battlefield, Rift, Cursed Orb, Summon Portal,
  Shadow Realm, Traveling Merchant, Chaos Pillars, Chaos Tower; later also
  `Spawn_Cabin_obj`). Each child's Create runs the parent's and then assigns its
  own closure to `m_activateMechanic`. **Measured** and **static reading**.
- Lifecycle (**static reading**, counts **measured**): the parent's Create sets
  `collisionRadius`, `discoverRange`, `discoverTimer` (≈30) and `activateTimer`;
  its Step drives discovery and sets `Alarm_0`; `Alarm_0` checks the room,
  `ZoneStateExists`, `isActive`, a position (up to 999 tries at least 128 units from
  the room edge) and `RunningHost()`, then fires the mechanic once. **If the zone
  state already exists, `Alarm_0` skips the mechanic — markers injected later do
  nothing.**
- Only `Spawn_Abyss_obj` sets `discoverable` true; measured on it: `discoverRange`
  1000, `discoverTimer` 30 (frozen out of range), `collisionRadius` 200,
  `activateTimer` -1 until discovered.
- `sCP(x, y, object)` creates the object on `gameLayer` and records it in
  `pSpwd`; Battlefield, Rift and Shadow Realm go through it. **Static
  reading** (2026-10-04). The S10 notes' `(object ref, x, y)` order was a
  reading not confirmed; this one follows the builtin's argument list, and
  Live 3's `spawn scp` answered `object=4644` with the default `(x, y,
  object)` order, so `(x, y, object)` is the right order. **Measured (Live
  3)** for the order.
- The reward portals (`Portal_Battlefield_obj`, `Rift_Portal_obj`,
  `Portal_Shadow_Realm_obj`) do their work in `Alarm_0` and stay dormant unless
  their spawner sets it; a `Portal_Battlefield_obj` carries 59 variables
  (`enemySpawnCount` 149, `fragmentAmount` 50, `m_BattlefieldPortalEnter`, …).
  **Measured.**
- Shadow Realm's gate needs `gDataProtected[68]` ≥ 2 and
  `Controller_obj.shadowRealmSpawned` == 0, with chance 13 + `eSt[9]`; Chaos Tower's
  needs `[68]` ≥ 1, `chaosTowerStarted` == 0 and `chaosTowerSpawnZone` == -1. Both
  roll against 9999 (`zrmb`); `m_ChaosTowerReset` resets their flags. **Static
  reading**, gates **measured** live (2026-09-03).
- `ReturnSpecificStat` is called about 140,000 times a session. **Measured.**

[S10, mechanic list](../ForgePact/docs/S10-special-content-notes.md#mekanik-listesi-9-adet-hepsi-spawn_mechanic_parent_obj-cocugu),
[lifecycle](../ForgePact/docs/S10-special-content-notes.md#yasam-dongusu-patch-gerektirmiyor---nesne-kendi-kendini-surer),
[marker path does not work](../ForgePact/docs/S10-special-content-notes.md#duzeltme---marker-yolu-calismiyor-2026-08-25-1940),
[Abyss solved](../ForgePact/docs/S10-special-content-notes.md#abyss-cozuldu---26082026),
[sCP](../ForgePact/docs/S10-special-content-notes.md#asil-cevap-gml_script_scp--2026-08-25-2010-statik),
[Shadow Realm and Chaos Tower gates](../ForgePact/docs/S10-special-content-notes.md#shadow-realm-ve-chaos-tower-kapilari)

---

## 15. Calls That Crash or Hang the Game

Collected from the sections above so they are found before they are repeated.
All **measured** unless marked.

| Doing this | Happens | Where |
|---|---|---|
| Widening `nodeGridWidth` past a grid row's length | index-out-of-bounds in the grid's Draw/Step within one frame, then APPCRASH c0000005 | §9.2 |
| `GetProfileInventoryData` without the window as `self` | throws, then crashes in `Controller_obj` Step | §9.4 |
| Most game scripts called cold (global `self`, no args) | access violation inside game code; process survives | §5.7 |
| A GML builtin called off the game thread | crash | §5.6 |
| Installing a `DropRelic` hook during character select | the runner stalls | §5.7 |
| `GetRelicQuest` answering true for every relic 0..155 | a relic pick's draw-again loop never ends (**static reading**) | §13.2 |
| `DropItemAngelic` when the zone has no candidates | infinite loop, game freezes | §13.4 ([angelic drop](../ForgePact/docs/angelic-drop-research.md#oyunun-kendi-mekanizması-statik-okuma-canlı-ölçülen-yalnızca-buff-yokken-zarın-hiç-atılmaması)) |
| Writing `dropTable` on piles, destructibles, `Cursed_Orb_obj` | GML error (static reading) | §13.1 |
| `DropDungeonKeys` with argument 5 undefined | GML error (static reading) | §13.3 |
| Overriding `eSt` at Room Start, or zeroing `ReturnSpecificStat`'s return | crash | §14.2 ([S10](../ForgePact/docs/S10-special-content-notes.md#simdiye-kadar-denenen-ve-coken-yollarin-tam-listesi)) |
| Calling `sCP` directly | crashed in S10 (2026-08-25) with the then-assumed `(object ref, x, y)` order and a suspect call format; called by name as `spawn scp` with `(x, y, object)` (§ 14.3) it does not crash (Live 3 created object 4644), but the machine it makes still dies of its own `Alarm_9` (§ 20.3), not a crash | [S10](../ForgePact/docs/S10-special-content-notes.md#scpyi-dogrudan-cagirmak-cokertiyor) |
| Duplicating `Spawn_*` instances | crash (their zone-state keys collide) | [S10](../ForgePact/docs/S10-special-content-notes.md#simdiye-kadar-denenen-ve-coken-yollarin-tam-listesi) |
| Duplicating reward-portal objects | infinite loading | [S10](../ForgePact/docs/S10-special-content-notes.md#portal-cogaltmasi--sonsuz-loading--2026-08-25-2155-geri-alindi) |
| Hooking the game's internal integer-die helper | crash | [S10](../ForgePact/docs/S10-special-content-notes.md#simdiye-kadar-denenen-ve-coken-yollarin-tam-listesi) |
| Filling the protected-variable store (262,144 records) | fault while a creator builds a monster | §5.8 |
| Special content at 20× | dies at about 13.4k instances | §5.8 |
| A creator acted on before `enemyCreatorTimer` is real | no crash — the pack never spawns | §11.2 |
| Removing a stash item's map entry (`RemoveItemFromMap` on map 9) but leaving its cell in the tab | the game ends at its next stash save — measured twice, in two launches; `GridRemoveItem` on the cell in the same take avoids it | §17 |
| A plugin DLL whose global `std::thread` is still joinable when the game exits | `std::terminate` while `ExitProcess` destroys that DLL's globals (the other threads are already gone): a WER report at close, `ucrtbase.dll` `0xc0000409`, fast-fail 7 (`abort`). HS-Offline-Tracker's producer does it; 9 of the 10 dumps Windows kept on 2026-09-25/26 show it, the game's own exit path under it, and a plain `CloseMainWindow` at the main menu does it too. A game started from a tool running under Git Bash inherits error mode `0x3` (`SEM_NOGPFAULTERRORBOX`) and aborts without a dump or an event: read the exit code | [Item Truth memory research](../ForgePact/docs/item-truth-memory-research.md#the-crash-of-2026-09-26-013627) |

---

## 16. Items as the Game Builds and Draws Them

What ForgePact's Item Truth capture measured on 2026-09-24, while the Item Editor
checked every item it owned (7,628, on characters, in the Shared Stash and in the
Infinite Vault) against the 2026-09-16 build, `pe-6aaa6779-0cad4fc8`. How the
capture works (hooks, budgets, files) is in
[ADR 0003](adr/0003-item-truth-lives-in-forgepact.md) and the two module guides.
The argument and the numbers are in the Item Editor's
[`GAME_TRUTH_DESIGN.md`](../hero-siege-item-editor/GAME_TRUTH_DESIGN.md).

### 16.1 Where an item is finished

- A save keeps an item's compact definition (§2) and nothing it rolled.
  `CreateItemNew` computes everything else each time it builds the item: the rarity,
  the magic prefix and suffix, up to five generated affixes, runeword and special
  tables, sockets and the display name. A rolled value therefore belongs to the
  build that rolled it.
- `CreateItemNew` can run inside another `CreateItemNew` call, and the inner item
  is part of the outer one. The **outermost return** is the finished item. Read
  there, the item's values match the stat lines the game drew for it: 41,920 of
  41,920 (§16.6).
- Before that point the item is not finished yet. A snapshot taken inside
  `CreateItemInit` / `GenerateItemRandomStats` lacked the socket count on 121 of
  386 compared items.

**Measured.**
[Item Truth, step 1](../hero-siege-item-editor/GAME_TRUTH_DESIGN.md#step-1--the-games-records-item-editor-2160-forgepact-145)

### 16.2 Building an item from its save data

- `InitItemFromJson(json, key)` is the game's loader for one saved item. It takes
  the `json_parse` result of the item's save `data` object and the item's key,
  with the global instance as `self`. It builds the item through `CreateItemNew`
  and returns the item struct (`VALUE_OBJECT`). ForgePact's Angelic pool
  (`BuildAngelicPool`, a ForgePact function) already built its probe items this
  way.
- On the game thread, 342 of 342 queued items were built this way in about 2 s at
  the main menu, including items of a character that had never been loaded. The
  structs were left to the collector, never placed in a grid or saved.
- **The collector does take them: a build keeps nothing.** At the main menu,
  20,000 items built this way moved private bytes by +6.7 MB (white bases) and
  +10.2 MB (white, unique, socketed and runeword items), and the level stayed
  flat afterwards (§5.9). The same 20,000 kept on purpose, in a global struct,
  grew private bytes by 106-117 MB and the collector's objects by 100,324-114,325
  (two runs): a kept item costs about 5.4-6.0 KB and 5.0-5.7 objects. One session
  built 197,704 items this way;
  its crash dump records a peak commit of 3.14 GB, the same as a fresh launch
  reaching the menu. A request builds about 430 items a second at ForgePact's
  budget (4 ms and 200 items per frame).

**Measured.**
[Item Truth, step 2](../hero-siege-item-editor/GAME_TRUTH_DESIGN.md#step-2--the-game-checks-any-item-on-request-item-editor-2160-forgepact-145),
[Item Truth memory research](../ForgePact/docs/item-truth-memory-research.md)

### 16.3 What a finished item carries

| Member | Holds |
|---|---|
| `itemTimeStamp` | the time stamp in the item's save key, `x-y-<itemTimeStamp>-<n>` |
| `itemType` | the item class (`ItemType`, `hs_game_sdk/item_type.hpp`) |
| `itemDataHash` | a hash of the item, which is not an identity (§16.5) |
| `itemDefinitionStruct` | the save definition (§2) |
| `itemStatStruct` | every stat the item has, by stat id |
| `itemInfoStruct` | what the tooltip's header shows |

| `itemInfoStruct` key | Holds |
|---|---|
| `"27"` | the rolled rarity (§16.4) |
| `"28"` | the display name |
| `"5"` / `"4"` | the magic prefix / suffix (`" of Recovery"`), empty when there is none |
| `"32"` | the tier letter: 1 C, 2 B, 3 A, 4 S, 5 SS |
| `"1"` | the level requirement |

- `itemStatStruct` keys `"10"`–`"14"` each hold one generated affix as
  `[stat id, minimum, maximum, affix tier]`. The rolled value itself sits under
  the stat id, like any other stat.
- Stat 447 is on hundreds of weapons, and a tooltip never draws it.

**Measured**, the info keys against 7,628 drawn tooltips. Also in
[`hs-game-sdk/curated/item_info.json`](../hs-game-sdk/curated/item_info.json).

### 16.4 Rarity codes

`itemInfoStruct["27"]`. The names are the game's own: the tooltip's type line
reads "Superior Ring", "Mythic Belt".

| Code | Rarity |
|---|---|
| 1 | Common |
| 2 | Superior |
| 3 | Rare |
| 5 | Mythic |
| 6 | Satanic |
| 7 | Angelic |
| 9 | Heroic |
| 10 | Unholy |

Codes 4 and 8 were not observed. **Measured** on 7,628 drawn tooltips. Also in
[`hs-game-sdk/curated/item_info.json`](../hs-game-sdk/curated/item_info.json).

### 16.5 `itemDataHash` is not an identity

The game gives some items a new `itemDataHash` each time it builds them, even
when the content is identical: potions, essence vaults, forged gear and a few
uniques, 51 of 7,628 owned items. Find an item by its `itemTimeStamp` and its
content, never by the hash alone. **Measured.**
[Item Truth, tying a drawing to its record](../hero-siege-item-editor/GAME_TRUTH_DESIGN.md#tying-a-drawing-to-its-record)

### 16.6 The inventory tooltip

- `DrawInventoryItemV2(x, y, scale, item, …)` draws an item's whole inventory
  tooltip, on every frame it is shown. The call can nest; the outer pass is the
  tooltip.
- Its text goes through the `draw_text*` builtins and the game's own
  `draw_text_outline(_ext)` and `DrawTooltipRichText` scripts. An outlined text is
  the same string drawn several times
  within 3 px, and the last draw is the visible one. Colours are GameMaker's
  `0xBBGGRR` integers.
- Stat lines come from `DrawInventoryStatsNew`. Its arguments are:
  0 `x`, 1 `y`, 2 `item`, 3 `stat`, 4 `label`, 5 `format`, 6 `style`,
  8 `per level`, 9 `negated`, 10 `colour`. Argument 7 is not established.
  - The pass calls it once for each stat line the tooltip knows, in draw order,
    whether or not the item has that stat. One pass made 335 calls on this build.
  - It draws a row only when the item has the stat. It returns the row height
    (30) or 0, and the caller adds that to its y cursor.
- How a line reads, checked on all 41,920 stat lines of the 7,628 drawn tooltips:
  - format 2 is a percent and 3 a flat number;
  - style 8 puts the value first and signs it (`+449% Enhanced Damage`,
    `-25% to All Enemy Resistances`);
  - style 9 puts the label first, unsigned (`Ailment damage increased by 35%`);
  - a per-level line is multiplied by the viewing character's level: a level-100
    character reads +300 for 3 per level;
  - a negated line is drawn below zero;
  - a whole number prints plain and anything else with two decimals
    (`+1.50 to Projectile Speed`);
  - a stat of 0 draws no line;
  - a skill grant is one line with its class (`+16 to Omnislash (Samurai)`): the
    skill is the stat id before it, the class the stat id after it;
  - `to All Skills` (201) and the element skill lines (222–227) take their class
    from stat 21;
  - relic skills are named from the game's `translations*.csv`
    (`talent_name_relicMeatHook` → `Meat Hook`).
- Every tooltip carries the key hint `ALT - Show Information`. Holding ALT draws
  the information view, which adds each rolled line's range (` [45-75]`) and
  skill descriptions.
- An unidentified item draws `Unidentified` and no stat lines.

**Measured 2026-09-24.** The stat call's arguments and return value were
live-traced on 2026-09-04 (ForgePact's forged tooltip rows).
[Item Truth, step 3](../hero-siege-item-editor/GAME_TRUTH_DESIGN.md#step-3--the-games-own-text-item-editor-2160-forgepact-145),
[how the rows are read](../hero-siege-item-editor/GAME_TRUTH_DESIGN.md#showing-it-item-editor)

### 16.7 Drawing a tooltip nobody sees

A tooltip can be drawn for other items from inside the game's own
`DrawInventoryItemV2` pass: the same instance, in its draw event. ForgePact does
it like this:
1. Save the draw colour, alpha, font, both alignments and the draw target.
2. Set a 16×16 surface as the target.
3. Call `DrawInventoryItemV2` for the other item struct.
4. Restore everything from step 1.

It drew 7,607 tooltips this way in about 2 minutes, at most 6 items and 3 ms per
frame. There were 0 failures, and nothing extra was seen on screen. **Measured.**
[Item Truth, drawing requests](../hero-siege-item-editor/GAME_TRUTH_DESIGN.md#drawing-requests-tooltips-of-items-the-player-never-hovers)

### 16.8 Which build is running

`pe-<link time stamp>-<.text size>`, both as 8 hex digits read from the PE headers
of `Hero_Siege.exe` (the file header's time stamp and the `.text` section's
virtual size), names a build.
- ForgePact chose these two fields because AuriePatcher does not touch them: it
  appends its `.aurie` section and rewrites the entry point and `SizeOfImage`.
  A patched and a clean exe of one build should therefore share the id. That is
  ForgePact's reasoning; it was not compared on a clean exe here.
- The two builds seen so far have different ids: `pe-6a91a8b3-0caf38b8`
  (2026-08-28) and `pe-6aaa6779-0cad4fc8` (2026-09-16).

**Measured**: the Item Editor computes the id from the exe on disk, and ForgePact
from the running process, and both gave the same id on 2026-09-24.

### 16.9 What a save definition decides: rarity, runewords, sockets

What the Item Editor's game-built seed table established on 2026-09-26 against
`pe-6aaa6779-0cad4fc8`: the game built about 135,000 items through
`InitItemFromJson` (§16.2) at the main menu, none placed or saved. The argument,
the controls and the table are in the Item Editor's
[`GAME_TRUTH_DESIGN.md`, step 4](../hero-siege-item-editor/GAME_TRUTH_DESIGN.md#step-4--seeds-the-game-built-item-editor-2163).

- **Rarity is rolled from `a`.** The same definition always builds the same
  rarity (info `"27"`, §16.4). Random seeds on white equipment bases came out
  Common 61%, Superior 31%, Rare 6%, Mythic 1%. The CPR stat model (the stat
  draws and the socket draw of the `a` chain) does not predict it: no single
  draw separated Common from the rest across bases. **Measured.**
- **Amulets and rings never came out Common** in about 16,000 builds. **Measured.**
- **A runeword forms only on a Common base.** Of recipe x base items built with
  the recipe's runes in `s1..sN`, 2,410 of 2,429 Common ones formed and 2 of
  1,286 others. Disaster and Celestus also did not form on 20 and 8 of the bases
  their targets name, even Common with the right socket count. **Measured.**
- **Socket count (stat 20).** **Measured**, with probes of each case and 4,849
  items built as the editor writes them:
  - a non-unique item (`c` 0) shows the larger of the definition's
    `zz.sockets` and the count its seed rolls; on a seed that rolls none,
    `zz.sockets` 1-6 gave exactly that count on every equipment class, gloves
    and belts included;
  - a unique (`c` 1) shows the count its seed rolls and never reads
    `zz.sockets`;
  - filled payloads `s1..s6` never add a socket: payloads beyond the count stay
    in the definition, unused (`s1..s5` on a seed that rolls 3 gave 3 sockets).
- **Most sockets a white base rolls**, over 332 seeds per base: helmets 3-4,
  body armours 4, boots 2-4, weapons 1-6, shields 2-5, gloves and belts none.
  **Measured.**
- **ForgePact's Custom Forge dresses every item whose type and `a`/`b`/`c`/`j`
  equal a forged item's**: two items that share a seed on one base are the same
  item to it. **Measured**: every white Great Helm built with the seed of the
  owner's forged Miner's Helmet came out as that Miner's Helmet.
- **The game keeps none of the items it evaluates this way** (§16.2), so the
  table is built in one game session. The WER report (`ucrtbase.dll`,
  `0xc0000409`) that ended a session of about 200,000 evaluations was the game
  exiting while HS-Offline-Tracker's producer aborted (§15), not memory.
  **Measured.**

[Item Editor, game truth step 4](../hero-siege-item-editor/GAME_TRUTH_DESIGN.md#step-4--seeds-the-game-built-item-editor-2163)

### 16.10 The rare-drop announcement closure on a ground item

- Static reading (2026-10-04, our own words): `Loot_Ground_obj`'s Create event
  binds three methods on each ground item; the one SDK-named
  `gml_Script_anon@1138@gml_Object_Loot_Ground_obj_Create_0` takes no
  arguments and is the drop announcement (§8.6). The other two are the
  loot-filter closure (`anon@6032`) and the step dispatcher (`anon@11081`).
- Static reading: it reads `self`'s item (`itemInstance`), then a struct
  inside it and one key of that struct, and compares the value with 7, 10, 9
  and 6 on separate branches, which are the rarity codes of §16.4; the key
  strings were not read, so that the key is `"27"` is an inference from the
  codes, not a reading.
- Static reading: a search for direct callers found none for it (while finding
  seven for the other targets of the same search), so it is reached as a
  method value; who invokes it, and whether anything does offline, is not
  established. Its name moves with every game patch (the `anon@N` position),
  so ForgePact spells it through the SDK constant.
- **Not observed (instrument-blind)**, 2026-10-04 (ForgePact#17's Live
  procedure 3, `lootannprobe methods`): the probe listed the ground item's
  method variables but its anon control did not resolve (`anon rows resolved:
  0 of 2`, every anon row `?#-1`), so the listing names no `anon@` method and
  whether the closure is bound and invokable on the ground item is not
  established. The `-1` is the probe's own reading of the index (whether
  `ToDouble()` on a reference yields the script number is open), not a settled
  `method_get_index` answer; `s_lootDrawData` resolving does not validate the
  anon rows (it resolved under the earlier broken probe too).
- **Measured** (2026-10-04, Live procedures 1 and 3 of the same feature,
  `lootannprobe methods` on a placed ground item offline): a `Loot_Ground_obj`
  instance carries four method-valued variables (each passed `is_method`):
  `m_AngelicMessage`, `m_LootFilter`, `m_LootGroundDeActiveStep` and
  `s_lootDrawData`. `s_lootDrawData` resolved to a named method of
  `Pickup_Parent_obj`'s Create event; the other three could not be named in
  either session. Not established: which function each of those three holds,
  and so whether `m_AngelicMessage`, the one named for an announcement, is the
  variable that holds `anon@1138`. It is the name a next attempt at the game's
  own path would start from.
- The chain, the rarity key and the codes the closure branches on are also in
  [`hs-game-sdk/curated/loot_announcement_measurements.json`](../hs-game-sdk/curated/loot_announcement_measurements.json),
  each entry with its own `status`: a static reading, an inference, or not
  established, until a live session measures it.

[loot announcements, Static reading](../ForgePact/docs/loot-announcement-research.md#static-reading),
[loot announcements, Live procedure 3](../ForgePact/docs/loot-announcement-research.md#live-procedure-3)

### 16.11 An item's time stamp, and what puts an item on the ground

- **Measured** (2026-10-04, the research build's `CreateItemNew` log in
  `bp_ipc\itemdrops.jsonl`, read while ForgePact #17's Live procedure 2 was
  analysed): an item the game makes for a natural drop carries a number in
  `itemTimeStamp`, rising from drop to drop and ending in a running counter
  (213292866000, 213292867001, 213292868002, ...). An item built from a save
  carries its save key's stamp as a 12-digit string. ForgePact's own
  placements (`sigdrop`, `angelicdrop`, `lootannprobe place`) carry the
  Unix-millisecond string of the key they hand `InitItemFromJson`. A
  temporary rebuild of a placed item, logged between that item's pickup and
  its bag drop (the log has no time to say which), carried `itemTimeStamp` 0;
  the last bullet of this section narrows it to the drop.
- **Measured** (2026-10-05, one log on one machine in one time zone): the
  number, without its last three digits, runs one hour behind the summer
  wall clock when counted as seconds from 2020-01-01 00:00. The log's newest
  stamp, 213313178109, is 2026-10-04 21:39:38 counted that way, and the file
  was last written at 22:39:39 local time (UTC+2). So on this machine it is
  seconds since 2020-01-01 00:00 at UTC+1, times 1000, plus the counter. Not
  established: whether the game takes local standard time or UTC plus a fixed
  hour (one time zone cannot tell them apart), and what the counter counts.
  Under that reading the three example values above fall at 15:01 UTC, the end
  of Live procedure 1's kills, not in Live procedure 2, which stayed in town
  and read no natural drop: the log read for Live procedure 2 still held the
  earlier launch's records.
- **Static reading** (2026-10-04, local Ghidra project, our own words):
  `LootGroundCreate` constructs the item and writes its `itemTimeStamp` from
  `LootTimestamp()`; the natural-drop `CreateItemNew` records already carry
  that stamp, so its `CreateItemNew(instance, undefined)` (§18.4) runs after
  the stamp is written. `LootGroundCreateFromItem` sets the new ground
  instance's `itemInstance` to the item it is given, a reference rather than
  a copy.
- **Static reading:** `LootGroundInit` reads `itemInstance.itemTimeStamp`
  and, behind a test against 0 whose exact form was not read, writes a fresh
  `LootTimestamp()` into it. So a stamp alone cannot tell a new item from an
  old one. `LootTimestamp` is also called from the merchant grids, crafting,
  prospecting and the runeword preview: the game mints a stamp wherever it
  makes an item.
- **Static reading:** `LootGroundDrop`'s direct callers are `LootExplosion`,
  `CreateItemDropInstance` and one unnamed function, with no inventory or UI
  function among them. `LootGroundInit`'s direct callers are
  `LootGroundDrop`, `LootGroundCreate`, `LootGroundCreateFromItem`,
  `LootExplosion`, `CA_playerItemDrop`, `CreateItemDropInstance` and sites in
  unnamed functions (one region also calls `RemoveItemFromMap`). (A byte
  scan for call sites; the "nearest symbol" of a site may be a preceding
  function.)
- **Static reading** (2026-10-04, our own words; recorded when ForgePact's
  creation guard was designed and not re-read since): `CA_playerItemDrop`,
  which puts a co-op peer's dropped item on this client's ground, builds that
  item anew here rather than receiving an existing struct. Not established:
  whether that build goes through `CreateItemNew`. Not measured: no co-op
  session has been run. ForgePact's Loot announcements would announce a peer's
  drop only if that build goes through `CreateItemNew`, and otherwise hold it
  as a bag drop (the module guide's Known Limitations).
- **Measured** (2026-10-04, ForgePact#17's Live procedure 2): a player's bag
  drop of an item
  ForgePact had placed reached `LootGroundInit` (the shared detour counted
  it), while a both-route detour on `LootGroundDrop` counted 0; that detour
  has never counted a call live. Which script the bag drop runs through is
  not established; that it is `LootGroundDrop` is not observed. The item
  that reached the ground still read the rarity the placement set, so it was
  not the temporary rebuild above (§18.5 corrects its older reading).
- **Measured** (2026-10-04, ForgePact#17's Live procedure 3, `bag-drop-silent`
  and `natural-fresh`): "the game built this item's struct through
  `CreateItemNew` this frame or the last" holds a bag drop and passes the
  game's own drops. The owner picked up a placed Heroic item and dropped it
  from the bag: `held-bag-drop` rose by one and no line appeared, while 215
  natural drops in the same session passed the guard (`natural-fresh`). It
  needs the `CreateItemNew` hook to be an inline detour (`LootGroundCreate`
  calls it directly). The same step measured where the game rebuilds: the
  count of keys noted from `CreateItemNew` (`created`) did not move at the
  pickup and rose by 2 at the bag drop, and the item on the ground was still
  held as not recently created. So a pickup builds nothing through
  `CreateItemNew`, a bag drop builds through it (two keys noted, which is one
  call's argument 0 and return or two calls; not told apart), and neither key
  was the struct that reached the ground. That the stamp-0 rebuild in the
  first bullet is that build is inference: this session did not read the log.
  One bag drop of one item was measured; a rebuild at the drop could still
  defeat the guard if it were given the existing struct or the ground
  received a copy, and which struct reaches the ground is not established.
  ForgePact's Loot announcements use it (the creation guard).

[loot announcements, Live procedure 2](../ForgePact/docs/loot-announcement-research.md#live-procedure-2),
[loot announcements, Live procedure 3](../ForgePact/docs/loot-announcement-research.md#live-procedure-3)

---

## 17. Stash Special Tabs & the Crafting Route

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

M: the bag's own grids read the same way: `inventoryMaterialGrid`
(`New_Inventory_Data_obj`) is row-major, `[row][column]` - `.0.7` held a
stack at column 7, row 0 (`nodeStartX=7`); `.7.0` was out of range (RD
`### Phase 1j results`). M: the Crafting Cube's own input grid is
`New_Inventory_Data_obj.craftGrid`, an array of 6 length-9 arrays, mirrored
at the Cube's own grid instance's `nodeGrid`. A hand-dropped item that was
already in the bag stays in map `0` there (`cube-holder`). A stash item
placed into the grid by name needs `ChangeItemOwner(9, 0, <fingerprint>)` as
well as `GridAddItem`, after which it left map `9` (`cube-place`); map `0`
was not read back after that call (RD `### Phase 1j results`, Live 1j).

### The item

M: `GetItemFromFingerprint(<fingerprint>, 9)` with the stash closed, self
`Console_Save_obj`, returns the item struct (`itemType=real:14` for the
Materials case) (RD `### Phase 1i results`). `itemDefinitionStruct.b` is the
base item id (Unstable Dust `50`, Greater Unstable Dust `51`); § 2's `o` field
is the stack count on this item, as on any stackable item - see § 2, not
restated here. `hs-game-sdk`'s `ItemType.SOCKETABLE` = 15 names the
Socketable case's class; that value is cited, not itself measured here (RD
`### Phase 1e results`, `### Phase 1i results`).

R: the item's methods are stored unbound on the struct the constructor
builds, so a name-resolved `script_execute` runs them with the caller's own
self, not the struct itself (RD `### Phase 1k results`, Live 1k). M:
`callm`'s `bind` re-binds a member to the struct it was read from through the
runtime's own `method` builtin before dispatch - `bind=yes`, and
`method_get_self` read `before=undefined` and `after=struct members=11`, so
the rebind was applied - but the one `script_execute` under the bound value
still threw and did not answer the item's count. This is a rejected shape
(`script_execute` of a bound value with an instance self), not a measurement
that a bound call cannot complete (RD `### Phase 1k results`, Live 1k,
`bind-control`).

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

M: the close's own save runs through `SaveLocalFile`, not `SaveStash`
directly - of the close's several `SaveLocalFile` calls, only the one with
self `Console_Save_obj`, `a0=4`, `a1=1` runs `SaveStart` (`stash.hss`,
`stash_kind` 4) with a true answer, then `SaveStash`, `SaveCommit`,
`SaveFileGMAsync`; the same shape, replayed by name with the stash closed,
ran the same chain and moved `stash.hss`'s write time again (RD `### Phase
1j results`, Live 1j). This is the reading that `SaveStash` alone only
serialises, into a buffer the game keeps, and `SaveLocalFile` is what
commits it to disk.

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

M, the rejected shape, recorded with what was supplied (RD `### Phase 1j
results`, Live 1j): four `callm` calls with self and other `Console_Save_obj`
- `SetItemDef` (key `"o"`) and `GenerateItemHash`, tried on both the stash
entry and the bag stack's own struct - each entered `script_execute` and
threw, with no state change. M: the game's own split instead runs those same
two methods with self `(not an instance: object/struct object_index=undefined)`
and other `UI_Split_Stack_obj` (RD `### Phase 1j results`, split-control), a
self `callm`'s instance-self form cannot supply. R, an inference from that
reading, not itself probed: that self is the item's own struct - the capture
shows only "not an instance", not that struct's identity. The inline `set`
route on `itemDefinitionStruct.o` was never tried, because the control showed
a method, not an inline write.

M: the inline route Live 1k used instead - `set itemDefinitionStruct.o <n>`
then `call ItemCheckHash(<item>)`, self `Console_Save_obj` - on a stash entry
and on a bag stack: `ItemCheckHash` answered `bool:false` both times; the bag
stack's `itemDataHash` changed from an earlier read, but the stash entry's
hash was read only after the edit, so its change is supplied by the reading,
not itself observed against an earlier value (RD `### Phase 1k
results`, Live 1k, `partial-stacked`). R: `ItemCheckHash` takes one argument
and re-runs the item's own hash method for comparison; a `false` on a
just-edited item is consistent with a stale-versus-new mismatch, not itself
probed (RD `### Phase 1k instrument`). R: `ItemCheckHash` itself calls no
reporting script (RD `## Ship design`). M: the json creation chain that makes
an item without the constructor - `CreateItemSaveStruct` -> `set o <n>` ->
`LootTimestamp` -> `InitItemFromJson(struct, "0-0-<S>-14")` -> `GetItemMap(0)`
-> `AddItemToMap(map, key, item)` -> `GetItemPreferredGrid` -> `GridAddItem` -
succeeded on the first argument order tried into both
`New_Inventory_Data_obj.inventoryMaterialGrid` (the bag) and
`New_Inventory_Data_obj.craftGrid` (the Crafting Cube's own input grid), with
no `ChangeItemOwner` needed in either case since the item was created
directly in map 0 (RD `### Phase 1k results`, Live 1k, `partial-nostack`,
`partial-cube`). R: the game's own merchant multi-buy (`UiAMerchantBuyMultiple`)
and its loaders (`InitItemFromJson`/`AddItemToMap`, the pattern
`ParseItemToGrid`, `ControllerLoadOnlineData` and the trade and market
handlers use) are the two routes that make an item without the constructor
(RD `### Phase 1k instrument`). M: the owner's drag of the Cube-created unit
into the bag's existing stack logged one call each of
`InventorySwapItemsNew`, `InventorySocketItem` and `RemoveItemFromMap`,
recorded as logged without interpreting them (RD `### Phase 1k results`,
Live 1k, `partial-cube`). Not observed: the game's own hash check on the
owner's drag of the edited bag stack, on that Cube merge, or on a save or a
reload - `ItemCheckHash` and `ReportClient` both logged zero calls during the
two armed drag windows, with no read taken of either row during the save or
the reload, and `ReportClient` never fired at all this session, so it has no
positive control here (RD `### Phase 1k results`, Live 1k, `hash-accept`,
`partial-cube`).

### The recipe amount and the craft route

R, a static reading: a recipe's input amounts are stored encrypted and
decoded by `PilipaliDecrypt`, then compared against a `CountInventoryItem`
count (RD `### Phase 1h instrument`). M: at the craft press, inside
`CraftFindRecipeItems`, `PilipaliDecrypt` returned the recipe's amount (5),
matching the owner's own figure, beside `CountInventoryItem`'s stock count
(155) (RD `### Phase 1i results`). `CraftFindRecipeItems` runs once at the
press and returns before `DoCraftResult` starts; `DoCraftResult` encloses the
consume and the production of a one-unit craft in a single call (RD
`### Phase 1g results`). M, Phase C (RD `## Phase C results`, ForgePact's
`craftmats` on): one press at the Crafting Cube's quantity 3, of a two-input
recipe whose inputs came only from the stash (Nut: 3 Sal and 1 Chipped
Sapphire per unit), moved 9 and 3 in one combined move line and produced 3
units, and the Cube's craftable maximum read 62 before and 59 after, with no
refusal or consume-mismatch line logged. How the quantity reaches the amount
the decode returns, and how many `DoCraftResult` calls a quantity 3 press
makes, are not measured.

R, a static reading of `CraftFindRecipeItems`, paraphrased (RD `## Ship
design`, "The needs"): each recipe input's amount is decoded by
`PilipaliDecrypt` before that input is counted, and an input that accepts
several base ids is counted one base at a time after its one decode,
stopping at the first base whose count reaches the amount.
`CountInventoryItem` decodes nothing and walks the bag's grids, not a map.
So the amount of a count made inside the call is the latest decode before
it, and of a run of counts after one decode the last is the one the game
used. ForgePact's `craftmats` pairs the needs it moves at the press this
way. M: the pairing held for a one-input recipe (the one decode and one
count measured above) and, in Phase C, for one two-input recipe (Nut) at
quantity 1 and at quantity 3: pairing this way, the mod moved exactly each
input's shortfall - 3 Sal and 1 Chipped Sapphire, then 9 and 3 - and the
game consumed them with no consume-mismatch line (RD `## Phase C results`).
Other multi-input recipes, including one whose input accepts several base
ids, were not exercised.

M, Phase C (RD `## Phase C results`, the player build on 2026-09-24; one
Socketable recipe, one Materials recipe and the two-input one, one press
each, the bag always with room and every stash stack left non-empty): a
recipe the bag alone could not cover (Ol: the bag's 1 of 3; Greater Unstable
Dust: none of 5) read available and crafted on one press, with the count
inside `CraftFindRecipeItems` supplied by the mod's hook. The by-name takes
ran inside `DoCraftResult`'s frame, before the game's own body: 2 Ol onto the
bag's existing stack (the inline route, the stack's `o` raised then
`ItemCheckHash`, `### The take calls`), and 5 Dust and the Nut's inputs as
new bag stacks made by the json creation chain, each stash stack lowered by
the same inline route. The game then consumed
the moved and the created units together with the bag's own - the bag held
none of the input afterwards - and produced one result per unit crafted.
The by-name stash save after each press (`SaveLocalFile(4, 1)`, the close's own route
above) moved `stash.hss`'s write time, and
the stash counts tool read the lowered stacks before any stash open, in the
stash window, after the game's own quit and reload, and with the game
stopped. The Cube's recipe list shows availability as computed when the Cube
opened: after `craftmats 0` a recipe the stash had made available still read
available while the window stayed open, and read unavailable at the next
Cube open (observed once, on to off). A press on a row whose shown
availability is stale was not observed, so what the game does on it, given
the press-time count inside `CraftFindRecipeItems` above, is not measured.
Not observed: the Cube's
`craftGrid` as a press-time destination, a take that empties a stash entry,
and the game's own hash check on the edited and created items beyond the
owner's drag and reload finding nothing marked.

M: a count injection inside the game's own availability check
(`GetCraftItemsAvailable`, the recipe row's Create closure, and any
craft-route row) moved a short recipe from unavailable to available and
back, `injected=2`, `outside-route=0`, `other-owner=0` - the mod's count
reaches the game's own display without any craft press (RD `### Phase 1j
results`, count-inject). M: the one `CountInventoryItem` call logged for
that recipe read `a0=1 a1=15 a2=1 a3=1` (owner, class, and base for a
Socketable identity); what `a0` and `a2` mean beyond that reading is not
measured (RD `### Phase 1j results`, cube-count).

### Jewel recipes in the Crafting Cube

**Static reading** (AFK FARM 0.8 research, paraphrased):
- **Tables.** The Cube's recipes are two globals: `global.craftComboList` holds the inputs and `global.craftComboResult` the results.
- **Jewelcrafting rows.** They have result types 37 to 41: 19 recipes, all with a 100% success chance.
- **Outputs and inputs.** They make type 15 (socketables) bases 78-81 (gems) and 82-96 (jewels) from type 14 bases 0-23. Result type 41 also takes the Enchanted Sigil (14:44).
- **Amounts** are stored encrypted like every recipe's and decoded by `PilipaliDecrypt` (above).
- **The in-game gate.** A hero may craft them only with the Jewelcrafting level (player stat 157) that the recipe's tier asks for, from 750 to 3750. That level rises only through prospecting (`JewelcraftingAdd`).

AFK FARM's plugin (0.8.0-camp) reads the two globals live with `afk worker recipes`. That read is **not yet measured** on a running game.

### SDK names and the curated entry

`SaveStashFunc` and `LoadStashFunc` are present in every `hs-game-sdk`
binding (bare names, not `gml_Script_`-prefixed) - see RD `### Phase 1h rows`
for the indices; neither is a call target here. The container names above
(`stashInventoryMap`, `stashMaterialTab`, `stashSocketItemSlot`,
`nodeFingerprint`) are not present in `Hero_Siege.exe`; the runtime fills
them from `data.win`, and no extractor currently produces them or ties them
to `Controller_obj`, so they are recorded as hand-verified data in
`hs-game-sdk/curated/stash_containers.json`, checked against this section and
the SDK by `tests/test_curated_stash_containers.py`. The same file's
`bag_to_stash_move` records the move below (§ "Moving an item from the bag
into the stash"): each routine by SDK name and index, its self and other, its
arguments in words, and the map owner per tab kind.

M: two more curated entries, added after Live 1j (RD `### Phase 1j
results`): `save` names the close's own save route (`SaveLocalFile`,
`hs-game-sdk` index 3518; self `Console_Save_obj`, index 980; `stash_kind`
4); `crafting_cube` names the Cube's input grid (`New_Inventory_Data_obj`,
index 3067; variable `craftGrid`; a stash item placed there by name needs
`ChangeItemOwner(9, 0)` as well as `GridAddItem`). Whether the game's own
count walks that grid is not measured, recorded as not observed on the
curated entry itself; the grid's persistence across a save is also not
measured, and the owner's design (2026-09-24) does not need it, since only
the craft's own items are placed there, at the press, and consumed at once.

Live 1k (RD `### Phase 1k results`) named no container the curated JSON
lacks: `inventoryMaterialGrid` (above) and `craftGrid` (`crafting_cube`,
just above) already covered every grid it placed an item into.

### The stash window, its tabs and the bag's sub-tabs (toolkit #147)

Source: the stash and bag research (`ForgePact/docs/stash-bag-layout-research.md`,
"SB" below), two research-build launches on 2026-09-25, slot 14 in
`Town_01_rm`, the interaction-check control climbing in both, plus a
player-build launch on 2026-09-26 ("live 3" below, the V0b and V3 readings);
representative cases only. **M** measured live; **R** a static reading, not
measured (one sentence, in the drag path bullet).

- **The tab numbers.** M (#14, RD `M-stash-open`, and the game's own tab
  table `global.defaultStashTabStruct`/`global.stashTabDataStruct` by name
  and index only): the personal tab is 0, the shared tabs 1 to 19,
  Socketable -2, Materials -4, Unique -5
  ([crafting-materials research](../ForgePact/docs/crafting-materials-research.md)).
  M (SB P0-3, P2-3): each `UI_Button_Stash_Tab_obj` carries that number as
  `tabNumber`, equal to the first element of its `activationArgs` (23 rows),
  and `tabType` 1 (the three special tabs) or 2; every row reads `visible=0`
  although drawn.
- **Two tab-state variables on `UI_Stash_obj`, not one.** M:
  `stashTabSelected` is the stash tab on show - 0 on Personal, -4 on
  Materials, -2 on Socketable (SB P0-3, P0-9, P2-3). `tabSelected` on the same
  instance is the bag's: a click on a bag page tab moved it alone from 0 to
  1, and the bag's Materials sub-tab click moved it from 1 to -4, while
  `stashTabSelected` read 0 throughout (SB P2-4). They also diverge the other
  way: the P2-3 dump read `stashTabSelected=-2` beside `tabSelected=0`. #14's
  one reading of both at -2 was one observation, not an invariant. So a
  stash tab is confirmed on `stashTabSelected` only, never on `tabSelected`.
- **The bag's sub-tabs.** M (SB P2-4): seven `UI_Button_Inventory_Tab_Small_obj`
  rows beside the open stash, told apart by `uiNodeCallstack` only
  (`InventoryTabVaultActive`, `InventoryTabVault`, `InventoryTabSocket`,
  `InventoryTabMaterial`, `InventoryTabKey`, `InventoryTabTarot`,
  `InventoryTabRelic`); `text` is empty on every row and none carries
  `tabNumber`. `UI_Stash_obj.invMaterialTab` and `.invSocketTab` hold the
  Material and Socket rows' instances. The page tabs are
  `UI_Button_Inventory_Tab_obj`, `tabNumber` 0 to 4 (Main, then four Extra).
  Their grid, M at two GUI scales, 2560x1368 (window 1920x1080, Town_01_rm)
  from two sessions, and 2560x1440 from Live 7 (below) - toolkit #147's
  stash-bag-layout live 2, attempt 1, with the stash open, for the tabs, and
  ForgePact #68's Live 1f and 1g for InventorySort: `uiNodeCallstack` `InventoryTab_1` to `InventoryTab_5` in
  `tabNumber` order, all `visible=1` and listed with the stash open; each
  bbox 182.4 wide (InventorySort's width), top 1136.2, bottom 1198.9, lefts
  1573.9, 1756.3, 1938.7, 2121.1 and 2303.5, so the row is contiguous (the
  pitch is the width). The row sits directly above InventorySort's
  (InventorySort 2303.5,1198.9,2485.9,1261.6: its top is the row's bottom),
  and InventorySort's left and right equal `InventoryTab_5`'s, so the slot
  left of Sort is under `InventoryTab_4`, whose column is 2121.1 to 2303.5:
  Sort's left minus one Sort width, up to Sort's left. Live 7 (ForgePact #131,
  2026-10-02, GUI and window 2560x1440) read the same relation there: each tab
  192 wide, top 1196, bottom 1262, lefts 1522, 1714, 1906, 2098 and 2290,
  InventorySort 2290,1262,2482,1328 (left and right `InventoryTab_5`'s, top the
  row's bottom), so `InventoryTab_4`'s column is 2098 to 2290; all five read
  `visible=1` with the bag open on its own; with the stash open the same five
  boxes were listed, `InventoryTab_4` and `InventoryTab_5` read `visible=1`,
  and the first three's visibility was not quoted. Not measured: the row at
  any other GUI scale.
- **`activeNode`.** M: `UI_Stash_obj.activeNode` holds an instance - the stash
  grid right after the open (SB P0-4), the clicked sub-tab's row after a real
  click on a bag sub-tab (SB P2-4). After a by-name
  `UiAInventoryMaterialTabClick` (argument list empty, where the game's own
  call passed one empty array) it still held the previous sub-tab's row: it
  was **not observed** to follow a by-name call. Live 3 (V3) read it again
  around the same by-name `UiAInventoryMaterialTabClick` and
  `UiAInventorySocketTabClick` calls: it stayed 262324 before and after both.
  `activeNode` was read only in that session, with no positive control run for
  it, so this is recorded as not observed to follow a by-name call, not as
  settled that it never does.
- **Who handles each click, as the game calls it.** M, each logged by a
  research-build detour on a real hand action (SB § Results):
  - the stash open on the interact key: `UiCreate`, self = other = the
    `Town_Stash_obj`, three arguments (the `UI_Stash_obj` object reference,
    1, 1), returning the new window (P0-3, P2-2);
  - a shared stash tab: `UiAStashTabClick`, self the `UI_Button_Stash_Tab_obj`,
    other the `UI_Stash_Tab_Bar_Container_obj`, one argument (its
    `activationArgs` array, `[<tabNumber>, <the button>]`) (P2-3). The
    Materials button's own handler is `UiAStashMaterialTabClick`; the
    Socketable button's is a closure the tab bar's Create made, held in the
    button's `activationFunc` (read hook-free);
  - a bag sub-tab: `UiAInventoryMaterialTabClick` (and
    `UiAInventorySocketTabClick` for Socket), self the sub-tab row, other the
    `UI_Stash_obj`, one empty-array argument (P2-4);
  - the stash's close row (`UI_Button_Close_obj`, `uiNodeCallstack`
    `InventoryClose`): `UiACloseButton`, self the row, other the
    `UI_Stash_obj`, one empty-array argument; `SaveStash` ran once on the
    close (P0-9, P2-7).
- **What reproduced by name.** M: `UiAStashMaterialTabClick` with self the
  Materials button, other the tab-bar container and two scalars (-4, the
  button) set `stashTabSelected` to -4; the Socketable closure, called as the
  method value with self = other = the button and (-2, the button), set -2;
  `UiAStashTabClick` with (0, the Personal button) set 0 (P2-3).
  `UiACloseButton` with no argument closed a reopened window, and `SaveStash`
  ran once more (P2-7). In live 2, `UiAInventoryMaterialTabClick` with no
  argument read `tabSelected=-4` after it, but nothing read `tabSelected`
  between the Socket click before it and the call, so that replay did not
  separate a switch from no change (SB P2-4). Live 3 (V3) then read
  `tabSelected` right before and after the shipped `bagtab` verb's call to the
  same by-name handlers, same shape (self the sub-tab row, other the
  `UI_Stash_obj`, no argument): `UiAInventoryMaterialTabClick` moved it from 0
  to -4, and `UiAInventorySocketTabClick` then moved it from -4 to -2, with a
  read before and after each call. The by-name bag-tab switch is measured as a
  switch. The by-name `UiCreate`
  open with the logged shape was dispatched once, and the game process died on
  the next command; causality is not established from one session, and it was
  not called again.
- **A grid node.** M (SB P2-5, on `New_Inventory_Data_obj.potionGrid.0.0`):
  a filled node is a struct of `nodeStartX`, `nodeStartY`, `nodeLocked`,
  `nodeIsPermanent` and `nodeFingerprint` and nothing else - no count
  (§ 9.1 reads the same on the prospect grids). The stash's personal grid
  array (`stashPersonalGrid`, 18 long) read `undefined` at `.0.0`: an empty
  cell or an indexing convention, not resolved.
- **The drag path.** M (SB P0-7): on a hand drag from the bag into the stash
  and a hand split of one unit into the bag, the only item writes logged
  were two `s_InvNode` calls - the constructor whose self is the node struct
  being built, with the destination grid as other and the cell's x, y and the
  item struct as arguments - and one `UiASplitStack` (self the dialog's
  button, other the `UI_Split_Stack_obj`). None of the twelve armed grid and
  map routines was observed on the drag or the split (not observed, with the
  control climbing); twelve rows are not every named grid routine. The
  destination cell was written by `s_InvNode`, which the research build
  could not replay by name: its self is a struct under construction, which
  `call`/`callm` cannot supply. That is a limit of the instrument, not of the
  game. R (static reading, not measured): the drag's own handling sits
  inline, likely in `ProcessInventoryGridInput`.
- **The warp.** M (SB P0-2, P2-2): the player's `x` and `y`, written by name,
  set to the town stash's own position with `y` 48 below it, landed 0 px from
  the target with no collision in both sessions, and the interact key F
  opened the stash from there.
- **`GetItemPreferredGrid`'s answer for one case.** M (SB live 3, V0b, one
  case): for a copy of a held non-stackable template (class 18) built by the
  game's own loader, ForgePact's reader `ApPreferredGrid` found no array
  `grid` member in what `GetItemPreferredGrid(1, item)` returned, or the call
  failed. The refusal did not record which, or the result's kind. ForgePact's
  verb then removed the unit from map 0 itself (`RemoveItemFromMap`) - not the
  game's loader, and not a rule for every step. For a stackable material
  (class 14), the same loader (`InitItemFromJson`) built the item and
  `GridAddItem` placed it without incident, confirmed by the verb's own
  re-read in the same session (V0), with no drag, save or reload. The
  template itself
  sits in the bag's `PotionGrid` (live 2 P2-1), so whether the game has
  another grid answer for such items (another first argument, or another
  result shape) is not established.

[stash and bag layout, Results](../ForgePact/docs/stash-bag-layout-research.md#results),
[stash and bag layout, Decision](../ForgePact/docs/stash-bag-layout-research.md#decision)

### Moving an item from the bag into the stash (ForgePact #68)

Source: the stash move research (`ForgePact/docs/stash-move-research.md`, "SM"
below): a static reading, then eight research-build sessions on 2026-09-28
(Live 1 to Live 1g), slot 14 in `Town_01_rm`, the interaction-check control
climbing in each; Live 1c and Live 1e had the owner's own Ctrl + left click as
the input, the others none (Live 1f's character pick was by hand). Representative cases: one or two items per tab
kind. **M** measured live; **R** a static reading, not measured.

- **The game's own quick move is Ctrl + left click.** M: with the stash open
  the bag window's hint strip reads `CTRL + LMB: Quick Move` (SM § Static
  reading 2), and the owner's Ctrl + left click moved an item from the bag
  into the tab on show in Live 1c and Live 1e. A plain click sent by
  `hs_input` reached `ProcessInventoryGridInput` once and never started a
  pick-up (Live 1b `click-control`), so no scripted gesture is measured.
- **The routines a quick move runs, in order.** M (Live 1c, Live 1e, each
  logged by a research-build detour on the hand move): `ValidateItem` (self
  and other the bag's grid node, the item), `StashAddToStack` (the same self
  and other, the shown tab's cell array, two numbers, the item, 1, a small
  number), then - when that answers false - `GridAddItem` (the same self,
  other and array, the item, 0, undefined), `s_InvNode` per covered cell,
  `ValidateItem` with self the stash's grid node and other the bag's, and on
  a stash-map destination `ChangeItemOwner` (self the stash grid, other the
  bag grid, 0, 9, the key as text). The two numbers are 0 and 13 into the
  personal page, 9 and 2 into a shared page, the Materials tab and the
  Socketable tab. When `StashAddToStack` answers true (a merge) the next call
  is `InvGridClearItemNode` on the bag cell. No `GetStashMaxTabs` and no other
  tab was logged on any bag-to-stash move.
- **The grid nodes.** M: the bag's grid node is the `UI_Inventory_Grid_obj`
  whose `uiNodeCallstack` is `InventoryGrid`, the stash's the one whose
  `uiNodeCallstack` is `StashGrid`; each rebinds to the view on show (the
  bag's to its Materials or Socket view after `bagtab`, the stash's to the
  tab after `stashtab`), keeping its instance id. Their `nodeGrid` is indexed
  `[y][x]`. Only the shown tab's array is readable this way.
- **By name, the same sequence moves the item.** M (Live 1d, into the
  personal page and shared page 1; Live 1e, a new identity into the Materials
  tab, with `Controller_obj.stashMaterialTab` as the array): the replayed
  sequence, `s_InvNode` left out, placed the item at `GridAddItem`'s answer
  (`tabNumber`, `x`, `y`, `tabType`, `success=true`), which held through a
  close, a reopen and the saved files. A by-name `GridAddItem` leaves the item
  in its bag cells too: `InvGridClearItemNode` (self and other the bag grid,
  the anchor cell's node, undefined) empties them, and it must run while the
  item is still on map 0, before the owner step.
- **Which map an item is in.** M: a personal-page item stays on map 0, with no
  owner step, and saves in the character's file under
  `inventory.personal_stash` (Live 1c, Live 1d). A shared-page item needs the
  owner step 0 to 9 after the placement; afterwards its key answers
  `undefined` on map 0 **and** on map 9 by `GetItemFromFingerprint`, as every
  shared-page key did, and it saves in `stash.hss` under `stash_tab_<n>` (Live
  1d). Which map holds a shared-page entry is not established. A Materials
  item answers on map 9 after the owner step and saves under `material_tab`;
  a Socketable item saves under `socket_tab` (Live 1e). R: the owner table
  has no personal-stash owner (0 the character ... 9 the stash, 10 and 11 the
  pact and guild stashes); an item carries an `inPersonalStash` member.
- **The owner step alone breaks the save invariant the other way.** M (Live
  1c step 8): `ChangeItemOwner` 0 to 9 on an item still in a bag cell left its
  key on no map while it sat in the bag; it was reversed before the close.
  Run it only after a placement the re-read confirmed.
- **`GridAddItem` places only into the array it is handed.** M: against the
  full shared page 2 (306 of 306), the owner's Ctrl + left click logged
  `StashAddToStack` false and `GridAddItem` `success=false` on that page's own
  array and nothing after; the item stayed in the bag and no other tab
  changed (Live 1c `hand-full`); the by-name call answered the same (Live 1d).
  Its answer's `tabNumber` read 0 on shared page 1 as well, so it does not
  name the tab.
- **Merges.** M: `StashAddToStack` answers true only when a stack of the
  item's identity is on the array and the stack then rose by the fifth
  argument's count: one unit (Live 1c, by name and by hand) and a whole stack
  of 15 (Live 1e, by name, `wholeStackMerge`); every hand merge logged 1. With
  no stack of that identity it answers false (Live 1, Live 1c). R: it takes
  only classes 12 to 15, merges through `InventoryStackUpdateAndRemove`, and
  answers false when the stack's hash check fails. Scope: every merge above
  was on the Materials tab (`Controller_obj.stashMaterialTab`, 9, 2) with the
  bag's Materials view on show, plus one by-hand orb on the Socketable tab. A
  merge on a stash page with that page's own two numbers (0 and 13 personal, 9
  and 2 shared) and the Materials tab fed from a bag page are not observed.
  Because it merges into any stack of the identity on the array that has
  room, a caller moving several items must re-read the array's stacks before
  each call: an earlier item of the same batch can have made or filled the
  stack a later one meets (ForgePact #68's round-2 review found a duplicated
  unit that way). **The cap** (M for 999, Live 3, 2026-09-30; R for 999999
  and the walk order; ForgePact #131): the routine
  takes a cap from its sixth argument - 999 when it is 0 or lacks flag 8,
  999999 when it carries flag 8 - and walks the array in order, merging into
  the first stack of the identity whose count plus the moved count stays at
  or below the cap; a stack that would pass it is passed over, and when none
  fits it answers false. So a merge takes the whole count or none, and never
  tops a stack up with part of an item. Live 3 measured the 999 cap through
  ForgePact's Move all on the Materials tab: beside a kind's one stack of
  875, a unit of 125 was placed as a new stack in a free cell and the 875
  left unchanged, and a unit of 129 then passed over the 875 and merged into
  the stack of 125 (254); no stack read above 999
  (`ForgePact/docs/stash-move-research.md` § Live 3 results). The measured
  merges pass 0 on the
  pages and the Materials tab (cap 999) and 8 on the Socketable tab (cap
  999999). The owner (2026-09-30): the Materials tab holds several stacks of
  one kind, 999 each, and the Socketable tab one stack per kind. Not read:
  whether the count added is the fifth argument or the item's own `o`, and the
  walk order beyond array order.
- **The Socketable tab.** Its container: M (Live 1e, 1f, 1g) one
  `UI_Inventory_Grid_obj` per item on the tab, each carrying `uiNodeCallstack`
  `StashSocketGrid` and a one-cell `nodeGrid` holding that item, whose key
  answers on map 9; the tab saves in `stash.hss` under `socket_tab`.
  `Controller_obj.stashSocketItemSlot` is not the container: it read no
  fingerprint while the tab held items (Live 1e). By hand, M (Live 1e): the
  game refuses jewels (base ids 109 and 110) and Incarnation Gems (136) for
  this tab after the first `ValidateItem` and before any placement routine,
  with nothing in the logged answers showing it; runes and gems were placed
  through the sequence above into a one-row array that was different for each
  item, and an orb merged. **By name, the merge**, M (Live 1f, Live 1g):
  `StashAddToStack` with self and other the bag's grid node (its Socket view
  on show), the `nodeGrid` of the `StashSocketGrid` node holding the item's
  identity, 9, 2, the item, its count (1) and 8, answered true, and that
  node's item's `o` rose by exactly the count (an orb, base id 118, 81 to 82
  in both sessions); `InvGridClearItemNode` (self and other the bag grid, the
  bag cell's node, undefined) then emptied the bag cell, and the merged unit's
  key reached no saved file after the stash's own close. A gem (base id 38)
  merged the same way and gained `o=2`, so it is stackable: no
  non-stackable answer was met on this tab, and Live 1e's missing `o` on it
  was a count of 1. A whole stack merges too, M (Live 3, 2026-09-30,
  ForgePact #131): a unit of 3 of the orb merged through ForgePact's Move
  all, and the node's `o` rose by exactly 3 (92 to 95). Placing a kind the tab does not hold yet was not
  replayed by name (no accepted kind absent from the tab could be obtained
  without a person).
- **The UI node API** (the in-game Move all button, ForgePact #68). M (Live
  1f, Live 1g) unless marked R. `UiCreateNode(x, y, object, activation,
  callstack name)` with self the window that will own the node (here
  `UI_Stash_obj`, as self and other): it made a `UI_Button_Small_obj` at that
  x and y, stored the name as the node's `uiNodeCallstack`, drew it with the
  object's own sprite, and answered the node (`visible` 0 in that frame, 1 the
  next); a `text` set on the node was drawn as its label. **The x and y are
  the node's origin, not its top-left** (M, Live 1f and 1g, the same numbers
  both times; ForgePact #131): for `UI_Button_Small_obj` (sprite
  `Menu_Button_Chat_spr`) the origin lies at its bbox centre - made at x
  2113.1, y 1198.9, its bbox read 2016.2, 1176.1, 2211.9, 1221.7 - while the
  bag's Sort node's origin is its bbox top-left (x 2303.5, y 1198.9, bbox
  2303.5, 1198.9, 2485.9, 1261.6), at a 2560x1440 GUI. The Sort node is a
  `UI_Button_Small_obj` too, drawn with `Inventory_Tab_Button_Solid_spr`, so
  the origin follows the sprite, not the object. Live 3 (2026-09-30) read
  the same relation at another GUI scale: the Move all node made at x
  2178.0, y 1295.0 read the bbox 2076.0, 1271.0, 2282.0, 1319.0, and Sort
  sat at x 2290.0, y 1262.0 with the bbox 2290.0, 1262.0, 2482.0, 1328.0.
  Its width, 195.7 in Live 1f and 1g, is
  not a whole sprite size, so a GUI scale is in play: read a node's extents
  about its origin from the node itself rather than from its sprite, and on a
  later frame, once it is visible and its box reads the same twice, not in the
  frame it was made (ForgePact's Move all button checks it that way).
  **A copied sprite and scale persist, and the bbox follows them** (M,
  Live 4, 2026-09-30, ForgePact #131): with `sprite_index`, `image_xscale` and
  `image_yscale` read off the Sort node by name and written onto a fresh
  `UiCreateNode` node, the node read Sort's sprite
  (`Inventory_Tab_Button_Solid_spr`) through `menulayout` and by name two
  ensure steps later and after a stash tab switch, its origin moved to its
  bbox top-left with the sprite, and its bbox read Sort's size (made at x
  2090, y 1262: bbox 2090.0, 1262.0, 2282.0, 1328.0, 192x66, beside Sort's
  2290.0, 1262.0, 2482.0, 1328.0). No read in that session found the object's own
  sprite put back on that member. **The drawn result was not Sort's
  button**, seen on a screenshot only: the node's `text` was no longer drawn
  inside its box (a clipped end of it showed at about the box's top-left
  corner, the node's new x, y), and the box did not read as Sort's to the
  owner. **Which members carry the label's place and look** (M, Live 5 and
  Live 6, 2026-09-30, ForgePact #131): such a node, already wearing Sort's
  sprite and scale, differed from InventorySort in exactly 13 writable
  members beyond its identity, place, text and activation - `textFont`,
  `dropShadow`, `createX`, `drawXOffset`, `drawYOffset`, `navBboxX`,
  `navBboxY`, `navBboxWidth`, `navBboxHeight`, `naviDown`, `naviDownPrev`,
  `naviRight`, `naviRightPrev` - and with those read off Sort by name and
  written onto the node as read, its label was drawn centred in its box like
  Sort's (Live 5 by a research copy; Live 6 on ForgePact's shipped path, on
  the first node and on one made after a close and reopen). `textFont` reads as an asset reference
  (`ref font __newfont2` on Sort), `dropShadow` and the four `navi*` members
  as bools, the rest as numbers. `createX`, `navBboxX` and `navBboxY` hold an
  absolute GUI position (on Sort, its own box's corner); written raw as Sort's
  onto a node 200 units to its left in Live 5 and 196 in Live 6, the label was
  still drawn inside the node's own box. **Copied label members persist:** they read back equal at
  once (Live 5), equal to Sort's again in a member diff seconds later, and on
  a reopened node's copy (Live 6). **Where the label sits:** measured, it is drawn
  centred in the box on both axes (the node's label box 2140,1286,2242,1303
  in its box 2094,1262,2286,1328 in Live 6; 2136,1286,2238,1303 in
  2090,1262,2282,1328 in Live 5; Sort's own label left edge 2338). Inferred,
  and not separated from plain centring: that left edge also sits within 2 of
  the node's x plus `drawXOffset` (Sort 2290 + 48 = 2338; the node 2094 + 48 =
  2142 against 2140 in Live 6, 2090 + 48 = 2138 against 2136 in Live 5), but a
  label centred in the box fits the same numbers to within 1, so they do not
  tell the two apart. Vertically the glyph top (1286) is 15 below the node's y
  plus `drawYOffset` (1262 + 9 = 1271 on Sort); the label tool reads drawn
  pixels, not the draw origin, so whether `drawYOffset` anchors the text, a
  font's own top spacing included, is not separated. Not read: which of the 13
  places the label on either axis (they were written together, in Live 5's
  trial and in the shipped copy), what the `navi*` and `navBbox*` members do
  beyond the label (gamepad navigation, for example), and whether the game
  rewrites any of them in longer play. **The Mercenary button** (M, Live 5
  and Live 6): with the bag open on its own (the `C` key) the game lists a
  `UI_Button_Open_Mercenary_obj` (SDK object 5004, `uiNodeCallstack`
  `InventoryMercenary`, `text` `Mercenary`, Sort's sprite) through
  `menulayout`, its bbox 2094, 1262, 2286, 1328 beside InventorySort's 2290,
  1262, 2482, 1328 at a 2560x1440 GUI: Sort's width and height, the same top,
  its left edge 196/192 of Sort's width left of Sort's left edge (its right
  edge 4 GUI units short of Sort's). With the stash open it is not listed
  (Live 5 alone: Live 6 ran no Mercenary query with the stash open), while
  InventorySort's box reads the same in both sessions; after the stash's close
  neither is listed (Live 5 alone). One GUI scale only.
  With the
  fourth
  argument undefined the node's `activationFunc` stays undefined (R: the
  function binds a callable value as a method of the new node and leaves
  anything else undefined, as `UiSetActivationFunc(node, f)` does). A node's
  click is dispatched as the node's user event 15 (in the object events
  `UI_Node_Parent_obj` defines), run from the owning window's Step, with self
  the node, other the window, and one argument, the node's `activationArgs`,
  handed to its `activationFunc`: M, a node bound to `UiSetFloatingToFalse`
  was called exactly so when clicked, and that script then raised "bool
  argument is unset" and ended the game (written for another object). R: when
  `activationFunc` is undefined the event does nothing - no sound, no call, no
  write; M (Live 1g): a click on such a node ended nothing, no dialog
  appeared, and no routine armed in that session logged a call with the
  node as self (UiSetFocus, the hover routine, aside); that nothing else
  runs is the R above, not measured. `UiRemoveNode(node)` with self the owning window removed
  it; the window's close destroyed a node still in its list, so a reopen finds
  none; a bag or stash tab switch kept it. R: `UiMoveNode(node, x, y)` sets
  both and runs the node's own position update; not called live. The bag's Sort button is the
  `UI_Button_Small_obj` whose `uiNodeCallstack` is `InventorySort` (text
  `Sort Tab`, `activationArgs` `[1]`, its activation `InventorySortTab`
  bound with the Sort node itself as self); the stash side's is `StashSort`.
  An end-of-frame `mouse_check_button_pressed(mb_left)` read sees a click
  made in that frame, and `device_mouse_x_to_gui`/`device_mouse_y_to_gui` put
  it inside the clicked node's `bbox` (Live 1f `sort-click-control`, Live 1g).
  Not read: where the game creates the Sort button, and the part of the
  window's Step that picks which node gets the click.
- **`GetItemPreferredGrid`** logged only on the reverse move (stash to bag),
  never on a move from the bag into the stash (M, Live 1e).

[stash move, Decision](../ForgePact/docs/stash-move-research.md#decision),
[stash move, Ship design](../ForgePact/docs/stash-move-research.md#ship-design)

## 18. Gems of Incarnation

What ForgePact's Gems of Incarnation mod established on 2026-09-25 against the
2026-09-16 build, `pe-6aaa6779-0cad4fc8`: the running game built 14,521 gems
through its own save loader (§16.2), and the drop, filter and pickup scripts were
read. The argument, the full tables and the live checks are in ForgePact's
[`docs/incarnation-gems-research.md`](../ForgePact/docs/incarnation-gems-research.md); how the mod uses them is in the
[module guide](submodules/ForgePact/instructions.md#gems-of-incarnation-146-simulated-drops-verified-2026-09-25).

### 18.1 The item

- Item key `socketable_gem_of_incarnation`: item type 15 (Socketable), base `b`
  136, `c` 0, `j` 0. A save keeps its seed `a`, `b`, `c`, `j` and the flags `n`,
  `o` and `w`, and nothing it rolled (§16.1). **Measured** (the owner's 21 gems).
- It goes only into the Incarnation tree's node sockets: a node holds an item
  fingerprint (`nodeItemFingerprint`), the tree gathers the socketed items in
  `incarnationSocketItemArray`, and `IncarnationStatGetter` adds their stats.
  **Static reading.**

[What a Gem of Incarnation is](../ForgePact/docs/incarnation-gems-research.md#what-a-gem-of-incarnation-is)

### 18.2 How the game rolls one

- The roll depends on the definition alone: the owner's 21 gems, rebuilt under
  new time stamps, came out identical to what the game had recorded for them,
  stats and names. **Measured.**
- The rarity (info `"27"`, §16.4) decides the affix count: Superior (2) 1-3,
  Rare (3) 3-4, Mythic (5) 4-5. With no `n`, 5,000 random seeds gave Superior
  91.1%, Rare 7.0% and Mythic 2.0%, and 1 to 5 affixes 66.8%, 24.0%, 7.2%, 1.9%
  and 0.1%. The level requirement (info `"1"`) is 52, 57, 62 and 67 for 1, 2, 3
  and 4+ affixes; the tier letter (info `"32"`) is always 4 (S). **Measured.**
- The affixes sit in stat slots `"10"`-`"14"` (§16.3). Each of the 37 affix stats
  has three affix tiers, 2, 3 and 4, with one range each: across all 14,521 gems
  and every `n`, no (stat, tier) pair showed a second range. Tier 4 is the best
  range. A value is rolled uniformly within its range. **Measured.**
- `n` moves the rarity odds, not the tiers (the tier-4 share stays 35-37%), and
  it is a table index, not a scale. On the same 2,000 seeds the Mythic share was
  2.0% for no `n`, 0 and 1; 3.0% for 2; 6.3% for 3; 11.3% for 4; 20.0% for 6.
  5 and 8 behave like no `n`. Real gear carries 0-4, mostly 3 and 4. What sets a
  drop's `n` was not read; the first `DropGems` drop measured in play carried
  none (§18.4). **Measured.**
- Building one gem through `InitItemFromJson` costs about 0.3 ms on the game
  thread: 47,147 builds took 14.4 s of build time at the main menu, in 4 ms
  slices. **Measured.**

[How the game rolls one](../ForgePact/docs/incarnation-gems-research.md#how-the-game-rolls-one---measured-on-14521-gems)

### 18.3 The affix pool

Every affix stat seen on the 14,521 gems, with its tier-4 range and the share of
Mythic gems carrying it (1,536 Mythic seeds: `n` 3, 4 and none, 512 each). The
names are the stats' tooltip names (the Item Editor's game-verified stat table).
**Measured.**

| Stat | Tooltip name | Tier 4 | Mythic gems |
|---|---|---|---|
| 28 | Enhanced Damage (%) | 12-35 | 17.3% |
| 29 | Enhanced Defense (%) | 25-75 | 16.6% |
| 52 | to Life | 10-50 | 15.8% |
| 53 | Life Increased by (%) | 3-10 | 12.4% |
| 57 | Life stolen per Hit (%) | 2-6 | 28.1% |
| 60 | to Mana | 10-50 | 16.5% |
| 61 | Mana Increased by (%) | 3-10 | 10.9% |
| 64 | Mana stolen per Hit (%) | 2-6 | 27.0% |
| 68 | Increased Attack Speed (%) | 3-12 | 28.6% |
| 74 | to Attack Rating | 15-50 | 17.0% |
| 75 | Increased Attack Rating (%) | 8-25 | 16.7% |
| 95 | Chance for a Deadly Blow (%) | 3-10 | 16.1% |
| 101 | Magic Skill Damage increased by (%) | 5-20 | 19.5% |
| 128 | to Physical Damage | 2-6 | 2.4% |
| 133 / 137 / 141 / 145 / 149 | to Fire / Cold / Arcane / Lightning / Poison Skill Damage | 18-24 | 2.7-3.4% each |
| 134 / 138 / 142 / 146 / 150 | Fire / Cold / Arcane / Lightning / Poison Skill Damage increased by (%) | 5-20 | 5.0-5.9% each |
| 173 | to All Resistances (%) | 2-5 | 11.7% |
| 175 / 177 / 179 / 181 / 183 | to Fire / Cold / Lightning / Arcane / Poison Resistance (%) | 6-15 | 3.1-3.6% each |
| 196 | Faster Cast Rate (%) | 2-5 | 24.8% |
| 201 | to All Skills | 1-1 | 0.7% |
| 284 | Increased Magic Find (%) | 3-10 | 25.7% |
| 448 / 450 | to Minimum / Maximum Weapon Damage | 6-12 | 16.7% / 25.5% |
| 462 + 463 | a skill grant: the skill (462, a skill id, 2-433) and its levels (463, 1-1) | - | 2.9% |

- A skill grant always takes two slots, 462 and 463. 462's "range" is a range of
  skill ids, not values.
- +All Skills is the rarest by far, yet it was on 3-4 of the 512 Mythic seeds at
  each of `n` 3, 4 and none. No movement stat is in the pool.

[The affix pool](../ForgePact/docs/incarnation-gems-research.md#the-affix-pool)

### 18.4 How a gem drops

- `DropGems` (drop type 6, §13.1) picks a socketable from repository category 15
  (§13.2) by drop rate and hands it to `LootGroundCreate`. **Static reading.**
- `LootGroundCreate(x, y, type, params, ...)` writes a fresh random seed into the
  params' `a`, creates the item instance and calls `CreateItemNew(instance,
  undefined)`. So a drop's seed is settled between that write and
  `CreateItemNew`'s first line. **Static reading.** A seed replaced at
  `CreateItemNew`'s entry, while `DropGems` runs, rolled as the replacement:
  simulated drops through the game's loader in that scope came out as the
  replacement seed's Mythic roll, 13 of 13. **Measured** (research build).
- On a real drop the definition is already on the item instance when
  `CreateItemNew` starts. In play, with every socketable a `DropGems` call made
  turned into a Gem of Incarnation at that point (a research-build test
  switch), 4 of 4 monster drops came out Mythic from the replacement seed, with
  every affix at its tier-4 top. The first carried no `n`. **Measured**
  (2026-09-25).
- Loading an item goes through `InitItemFromJson`, never `DropGems`, so an owned
  gem never takes a new seed. **Static reading.**
- A `DropGems` detour, like `DropRelic`'s, is installed once a player exists: a
  drop hook installed during character select stalls the runner (§15).
- A Gem of Incarnation that the game picked itself is not yet observed; it
  takes the same path.

[How it drops](../ForgePact/docs/incarnation-gems-research.md#how-it-drops---static-reading),
[Live checks](../ForgePact/docs/incarnation-gems-research.md#live-checks)

### 18.5 The loot filter never sees them

- The ground item's loot-filter closure (a `Loot_Ground_obj` Create closure; its
  `anon@N` name moves between builds, §5.3) runs its checks for equipment
  (types 0-8), charms (10), consumables (11), potions (18) and socketables with
  base 97-111 only: the Uncut Jewels, the only socketables with random affixes
  before Season 10. Every other socketable, base 136 included, skips the checks
  and stays visible. **Static reading;** not measured live.

[Why the loot filter never hides them](../ForgePact/docs/incarnation-gems-research.md#why-the-loot-filter-never-hides-them---static-reading)

What a hidden ground item still is (ForgePact #95 part 1, 2026-09-27, part 2,
workorder `forgepact-issue-95`, 2026-09-28, and part 2b, the mod's workorder
`forgepact-issue-95-mod`, 2026-09-28 and 2026-10-02):

- `Loot_Ground_obj`'s Create sets `lootFilterVisible`, `lootFilterHighlight`,
  `skipLootFilter`, `inviewCheck`, `itemCompanionTimer`, `visible` and alarm 4,
  and binds `m_LootFilter` and `m_LootGroundDeActiveStep`. Its Alarm 9 reads
  `lootFilterVisible`, sets `visible` from it, and re-arms itself for 0.3 s of
  game speed. So an item the filter hides stays a live instance that re-checks
  its visibility every 0.3 s. **Static reading.**
- `Loot_Ground_obj` (2513) owns five events: Create, Destroy, Alarm 9, Draw and
  Clean Up. It has no Step and no Alarm 4 event. Its parent is
  `Pickup_Parent_obj` (3421), which owns Create, Alarm 9 and Clean Up, and no
  Step. So the `alarm[4]` that Create sets counts down with no handler in the
  object or its parent, and nothing runs. **Static reading** (part 2).
- Create binds its three closures as methods and runs none of them. By role
  (the `anon@N` numbers move, §5.3): a rare-drop announcement, the loot-filter
  closure bound as `m_LootFilter` (reads `global.loot_filter_new`, calls
  `LootFilterAffixTierVisible` and `LootFilterAffixTierHighlight`), and a small
  dispatcher that calls `LootGroundRelicStep` or `LootGroundDeActiveStep`.
  **Static reading** (part 2).
- The filter verdict is computed in `LootGroundInit`, not in Create:
  `LootGroundCreateFromItem(x, y, item)` calls `CreateLootInFreePos`, then
  `LootGroundInit(instance, item)`, which reads the bound `m_LootFilter` off the
  instance and calls it behind a guard that was not read (`skipLootFilter` is
  the candidate). `LootGroundDrop` calls `LootGroundInit` too; that it is the
  player's bag drop was read from its name and its `RemoveItemFromMap` call
  only, and on 2026-10-04 a bag drop reached `LootGroundInit` while
  `LootGroundDrop`'s both-route detour counted 0 (§16.11: not observed, not
  "does not happen"). So when `LootGroundCreateFromItem` returns,
  `lootFilterVisible` already holds the game's verdict. **Static reading**
  (part 2); the bag drop reaching `LootGroundInit` is **measured** (§16.11).
- All three ground-drop entry points call `LootGroundInit`:
  `LootGroundCreateFromItem` once, after making the instance; `LootGroundDrop`
  at two sites; and `LootGroundCreate`, whose listing of callees names it once.
  No path through `LootGroundCreate`'s long body was traced, so whether every
  item it makes gets its verdict there is not established. **Static reading**
  (part 2b, workorder `forgepact-issue-95-mod`, 2026-09-28;
  [The mod](../ForgePact/docs/hidden-loot-research.md#the-mod)).
- Alarm 9 never re-runs the filter: it reads `lootFilterVisible`, calls
  `OnScreen`, sets `visible` from the two, re-arms itself and counts
  `itemCompanionTimer` down, with no method call. Items already on the ground
  are re-evaluated only from the loot filter's menu path (`LootFilterImport`
  references the `m_LootFilter` slot), which is how part 1 saw `hidden` fall
  to 0 with the filter off; how that pass walks the items, and so whether it
  reaches a deactivated one, was not read. **Static reading** (part 2).
- The Draw event tests one variable and calls `LootGroundDraw`. **Static
  reading** (part 2) of the event body only.
- A hidden item's Draw does not run: 2,736 hidden `Loot_Ground_obj` instances
  ran it 0 times in 10 s, and the same items, shown, ran it 1,477,440 times,
  the positive control. That matches GameMaker's documented rule for a
  `visible` false instance, whose draw pass still walks it (ForgePact's far
  sleep research). **Measured** (part 2, `forgepact-issue-95` Live 1).
- At a strict filter, 281 of 291 `Loot_Ground_obj` instances read
  `lootFilterVisible` false and `visible` false, and an earlier read gave 68 of
  68. With the filter turned off (the game has no "Show all loot" key), none
  read `lootFilterVisible` false, `ground` stayed 291, but 95 still read
  `visible` false: visibility also follows something besides the filter, which
  fits §18.6's reading that Alarm 9 consults the screen; which cause held those
  95 was not established. **Measured.**
- The frame cost of hidden items: part 1 did not observe it (the filter-off
  window read 7.08 ms average and 40.7 ms max; no clean strict-filter window was
  taken, the one read holding a 6.5 s stall from an unrelated gold pickup).
  Part 2 measured it for one arrangement of items: 2,736 copies of one
  equipment template, spawned by `lootspawn` at random offsets within ±600 x
  ±400 px of the player (so dense and near or on screen) and hidden by writing
  `lootFilterVisible` with `loothide`, because the game's own filter showed the
  template; in one zone, uncapped at about 140 fps asleep. Awake against the
  same items put to sleep with `instance_deactivate_object`, they added
  6.66 ms (pair 2) and 10.57 ms (pair 1, a mixed window) to the average frame
  interval, and frameprof's `working` rose 10 and 12 points, saturating at
  100%. That is **about 2.4-5.6 µs of frame time per hidden item per frame for
  that pile**. Whether the per-item cost holds for items spread across a zone
  or off screen, for items the game's filter hid, or at other counts (the
  linearity) was not measured, and three things say it may not: Alarm 9 calls
  `OnScreen`, so position takes a different path; the awake profile's heaviest
  event, `Loot_Manager_obj`'s Begin Step (42.7% of the frame), does per-item
  work that was neither read nor profiled asleep and may depend on proximity
  or density; and 9-19% of the spawn calls returned no instance, which would
  fit the pile running out of free positions (a cause not established, see
  below). **Measured** (part 2,
  `forgepact-issue-95` Live 1), under those conditions only. What the same
  items cost shown was not established: one unpaired capture read 1.21 ms
  more, taken while the check it annexes (`cost-visible-working`) failed and
  not reconciled with that capture's profile; see the research doc.
- A zone's end runs Clean Up, not Destroy, on each hidden ground item: 809 of
  809 Clean Up runs, 0 Destroy, and `instance_number(Loot_Ground_obj)` read 0
  after the exit. So a hidden item does not outlive its zone. **Measured**
  (part 2 Live 1, items awake; for items asleep, see the next bullets).
- A sleeping (deactivated) ground item is cleaned up at the zone's end the same
  way: with 1,495 `Loot_Ground_obj` instances asleep, leaving the zone ran
  Clean Up 1,495 times and Destroy 0, and none were left. **Measured** (part
  2b, workorder `forgepact-issue-95-mod`, Live 2, `zone-end-asleep`;
  [Live 2 results](../ForgePact/docs/hidden-loot-research.md#live-2-results-2026-09-28)).
- `instance_activate_object` brings back every ground item
  `instance_deactivate_object` put to sleep in the same zone (2,736 of 2,736,
  twice), and `instance_number` does not count them while asleep. **Measured**
  (part 2 Live 1). `instance_find` does not reach them either: with 1,495
  asleep and none awake, a walk with it found none (`lootcensus` read
  `ground=0 walked=0`), while every one was still there for its Clean Up at the
  zone's end. **Measured** (`forgepact-issue-95-mod` Live 2).
- A hook on `LootGroundInit` installed with both routes (`HookOneScript`'s
  table swap and inline detour) sees the game's own compiled drop calls: about
  60 s of killing monsters at a strict filter gave 531 calls, each carrying a
  live `Loot_Ground_obj`, 522 of them with a hidden verdict; 1,000
  `lootspawn` calls to `LootGroundCreateFromItem` added 971, the number that
  returned a live instance. Which route carried each call was not separated.
  **Measured** (part 2b, workorder `forgepact-issue-95-mod`, Live 2,
  `route-both` and `create-slept`;
  [Live 2 results](../ForgePact/docs/hidden-loot-research.md#live-2-results-2026-09-28)).
- `LootGroundInit`'s argument 0 is the new ground instance: in 473 of 473
  calls from the game's own monster drops, and 1,000 of 1,000 from
  `lootspawn`'s by-name `LootGroundCreateFromItem` calls, argument 0 named a
  live `Loot_Ground_obj` at the end of the frame, and argument 1 and `self`
  never did. Argument 0 never arrived as an object (`obj-a0=0` over all 1,473
  calls), so it was a number or a reference every time; the last call's kind
  was a reference (`VALUE_REF`), and the kind of each call was not recorded,
  so code reading it must accept both. Argument 1
  never arrived as an object (`VALUE_OBJECT`) in any of the 1,473 calls, and
  the last call's kind was none of a number, a reference, an object or
  undefined (which kind exactly was not recorded). `self` on a monster drop
  was a live instance with a numeric `id` every time. So the static reading
  `LootGroundInit(instance, item)` holds for argument 0; that argument 1 is
  the item's data stays a reading, and it is not an object-kind value on this
  build. **Measured** (part 2b, workorder `forgepact-issue-95-mod`, Live 3,
  2026-10-02, `candidate-slots` and `arg-kinds`;
  [Live 3 results](../ForgePact/docs/hidden-loot-research.md#which-argument-carries-the-item-candidate-slots-arg-kinds)).
- What `instance_exists` answers for an item struct inside `LootGroundInit`:
  **not observed**. Since argument 1 never arrived as an object, no item
  struct reached it (`obj-a1=0`). Inside the same call it answered false for
  an object that is not an instance, the runner's global instance passed as
  `self` by `lootspawn`, 1,000 times out of 1,000 (`dropped=1000`, `errors=0`),
  and YYToolkit's runner-error count did not move over those calls; it
  answered true for a monster's `self` 473 times of 473. **Measured**
  (`forgepact-issue-95-mod` Live 3, `struct-safe` and `spawn-inits`). That
  session's runner errors (`REAL argument incorrect type undefined`) came
  from a research-only ForgePact hook on `DropKeys` that reads the built-in
  `room` through `variable_global_get`, which answers undefined for it: our
  own code, not the game, and not the `LootGroundInit` hook (attributed from
  the research DLL's own function table, not separately measured;
  [`struct-safe`](../ForgePact/docs/hidden-loot-research.md#struct-safe-what-the-runner-errors-were)).
- A `lootFilterVisible` written true on a hidden item stays true: Alarm 9's
  refresh did not write it back (522 woken items, `hidden=0` 1 s and 2 s after
  the write), as the reading above that Alarm 9 never re-runs the filter
  predicts. With the built-in `visible` written true as well, 462 of the 522
  still read `visible` false at both readings while woken loot was drawn on
  screen; Alarm 9 sets `visible` from the verdict and `OnScreen`, which fits
  those being off screen, but which were off screen was not established.
  **Measured** (`forgepact-issue-95-mod` Live 2, `hold-shows`;
  [Live 2 results](../ForgePact/docs/hidden-loot-research.md#what-hold-shows-measured)).
- `LootGroundCreateFromItem(x, y, item)` returned no live instance for 86-90 of
  each 1,000 calls in one zone and 191 of 1,000 in another, and the ground count
  rose only by the instances it returned. **Measured**; the cause was not
  established.
- Whether hidden ground items reach the save, or come back after a reload:
  **not observed**. The save the game wrote at exit with 2,736 hidden items on
  the ground did not grow (the slot file shrank by 8 bytes), but the check's
  positive control failed, and the reload landed in town. A later finding would
  cover the save written at exit, not a save written mid-zone.

[dev2 bug batch, #95 part 1](../ForgePact/docs/dev2-bug-batch-research.md#95-part-1-what-a-hidden-ground-item-still-costs);
[#95 part 2, static reading and cost model](../ForgePact/docs/hidden-loot-research.md#static-reading);
[#95 part 2, Live 1 results](../ForgePact/docs/hidden-loot-research.md#live-1-results-2026-09-28);
[#95 part 2b, Live 2 results](../ForgePact/docs/hidden-loot-research.md#live-2-results-2026-09-28);
[#95 part 2b, Live 3 results](../ForgePact/docs/hidden-loot-research.md#live-3-results-2026-10-02)

### 18.6 No automatic pickup

- No automatic pickup was found. `Loot_Manager_obj`'s Step picks up only the
  targeted item (`playerLootTarget`) after an input: a key, a click or the
  gamepad (§10.2). `Loot_Ground_obj` has no Step, and its `Alarm 9` sets
  visibility from the filter and the screen (a later reading, §10.6, found it
  also counts down the item's `itemCompanionTimer`). No code in the exe or
  `data.win` refers to the translation key `auto_pickup`. The one pickup that
  runs without the player's input is the pet's own (`Companion_obj`, §10.6),
  which takes only some item types. **Static reading.**
- Relics included: `LootGroundRelicStep` is the relic's floating animation,
  not a pickup, and the pet's type filter leaves the relic class out; how a
  relic is picked up, and what a 10/10 one does, is §10.7. **Static
  reading.**

["Auto loot"](../ForgePact/docs/incarnation-gems-research.md#auto-loot---static-reading)

## 19. Player jump and collision

What ForgePact's jump-through-scenery research (#16, phase 1) measured on
2026-10-03 with its `jumpprobe` instrument, on save slot 14 ("Sorak", level
100) in `Town_01_rm`. The argument, the controls and the full check table are
in ForgePact's [`docs/jump-scenery-research.md`](../ForgePact/docs/jump-scenery-research.md);
the numbers are also in `hs-game-sdk/curated/jump_measurements.json`.

### 19.1 The universal jump

- The jump key (Space by default) jumps **towards the mouse cursor**. The
  owner's account, 2026-10-03.
- The local jump runs through `gml_Script_skillsLeap` (3664) and
  `gml_Script_playerJumpGravity` (2764): each is called once per frame, with
  the player as `self`, for the jump's whole length, whether the player moves
  or not. `skillsLeap` takes one argument close to 1. `gml_Script_CA_playerJump`
  (348) and `gml_Script_PlayerForceJump` (2770) are **not** called by the local
  jump, and `gml_Script_StatJumpPower` (3391) logged no call during one.
  **Measured.**
- The jump lasts 104 frames. On open ground it moved this character about
  175 px (19.4, curated J11); the jump that crossed a prop under phase 1's
  `all hold` lever (curated J2) went 117 px, about 1.1 px per frame. The
  character's Jump Power was not read, so neither is the base jump.
  **Measured.**
- No instance variable whose name contains `jump`, `air`, `grav`, `land`,
  `fall`, `height`, `zpos`, `hover` or `fly` changes during a jump: the only
  matches on `Player_obj` are `bufferJump` and `slopeHeight`, and both stayed
  0. **Measured.** Where the jump's state lives is not established.

[Live 1 results](../ForgePact/docs/jump-scenery-research.md#live-1-results)

### 19.2 What blocks it

- A jump at a scenery prop that blocks it does not move the player at all,
  not even to the prop's edge 22 to 40 px away, while `skillsLeap` and
  `playerJumpGravity` still run for the jump's 104 frames. **Measured.**
- During the jump the player's own builtin collision queries name the
  collision family by its parent: `position_meeting`, `place_meeting`,
  `instance_position` and `collision_line` pass `Collision_Parent_obj` (957)
  itself, and `collision_circle` passes `Wall_Parent_obj`. None passes
  `Collision_Prop_obj` (959) or a descendant. **Measured.**
- Answering those five builtins "nothing there" for the player (`noone` or
  `false`), without running them, lets the same jump cross the prop: 117 px
  over the jump's 104 frames. **Measured.** The `props` and `scripts` levers
  answered nothing, so they say nothing either way: no player query during
  the jump named `Collision_Prop_obj` or a descendant, so the `props` lever
  stayed at `passed=0` and every query counted `other-family=`; and the player
  made no call to `CanMove`, `InstancePlaceTallest` or `TilePlaceMeeting`
  during a jump (those rows are native detours, and `InstancePlaceTallest`'s
  1944 player-self calls during a walk are the positive control that they
  would have counted one). Whether `InstancePlaceTallest` holds a walk or
  refuses a landing inside a prop is **not established**
  ([Results](../ForgePact/docs/jump-scenery-research.md#results)). **Measured**
  for the counts, not for any effect.
- A jump aimed at a landing point inside a prop (a horse carriage) does not
  start even with those five builtins answered: the player stays within 4 px
  of the take-off point. What refuses it was not identified. **Measured.**
- Walking into a prop stays blocked with those five builtins answered.
  **Measured.**

[Live 1 results](../ForgePact/docs/jump-scenery-research.md#live-1-results);
[Decision](../ForgePact/docs/jump-scenery-research.md#decision)

### 19.3 The take-off check

Read from the arguments `jumpprobe` logged in Live 1's own `out.txt`
(2026-10-03), which the session capture had shortened.

- In the frame a jump takes off, before that frame's `skillsLeap` call
  returns, the game walks along the jump's direction with queries whose
  `self` is the player. The steps are about **4.0 px** apart. At each step it
  asks `collision_circle(cx, cy, 15, Wall_Parent_obj, true, true)` (radius
  **15**) and `instance_position` against `Collision_Parent_obj` (957) at two
  side points, about **14 px** to either side of the step, perpendicular to
  the direction. **Measured.**
- The first circle centre sits about 5-6 px below the player's origin,
  whichever way the jump goes (two take-offs heading south, one north).
  **Measured.**
- One blocked side point is enough: in Live 1 run J1 (curated J10) the
  right-hand point of the second step returned an instance, and that jump
  moved 0 px. **Measured.**
- Phase 1 could not tell whether the walk runs inside `skillsLeap`'s first
  call or just before it, in the same frame (the builtin rows were logged on
  return, before `skillsLeap`'s own line); the mod session settled it: inside
  the first call (19.4 / curated J12).
- The "no collision" answers the game accepts for these queries are real -4
  (`noone`) for `instance_position`, `collision_line` and `collision_circle`,
  and bool false for `position_meeting` and `place_meeting`; the game's own
  `noone` comes back as a ref to instance -4. **Measured** (Live 1 run J3,
  curated J5).

[Phase 2: the take-off check](../ForgePact/docs/jump-scenery-research.md#the-take-off-check)

### 19.4 Through the mod (phase 2 live session)

What ForgePact's Jump through scenery mod (`jumpscenery`, #16 phase 2)
measured about the game on 2026-10-03, on the player build, slot 14
("Sorak"), in `Town_01_rm`. Curated entries J11 to J15 in
`hs-game-sdk/curated/jump_measurements.json`. A bare Jn in section 19 is a
curated id in that file; the research doc's Live 1 run labels, also J1 to J5,
are not, and are written "Live 1 run Jn" here.

- A jump on open ground moved this character about **175 px** (from (912.0,
  822.0) to (921.9, 996.7)); the character's Jump Power was again not read.
  **Measured.**
- The take-off walk of 19.3 runs inside `skillsLeap`'s first call of the
  jump: on each of three jumps, at least two of the walk's `collision_circle`
  queries arrived after that frame's `skillsLeap` entry, and none before it.
  Together with 19.3's ordering (the walk's rows logged before `skillsLeap`
  returns), that places the walk between its entry and its return.
  **Measured.**
- A jump at the prop that blocks it does not move the player (0 px, twice),
  and answering the player's five builtins "no collision" during that jump
  lets it cross: 125 px, about 50 px short of the open-ground jump. Why the
  crossing jump ends shorter is **not established**. **Measured.**
- A jump aimed so that it would end inside a horse carriage did not move the
  player even with the five builtins' blocked player-self family queries
  answered (1152 answers in that jump), as in phase 1: something the mod does
  not answer refuses it (a script row, an unhooked builtin, or one of the five
  called with another self or a non-family object; not established), and the
  player did not end inside the prop. The mod's landing and room checks ran on
  that jump and let it through (`granted` +1, `refused-landing` 0), so the
  mod's landing check has not been observed to detect the carriage; the
  landing point they checked was not recorded, so whether it lay inside the
  carriage is **not established**. What
  refuses the jump is **not established**; the owner reads it as the game
  validating the landing zone itself. **Measured** for the position, not for a
  mechanism.
- `room_width` × `room_height` of `Town_01_rm` is **2800 × 2400**. The room
  rectangle is larger than the walkable map: `playerwarp` to (50, 1200) and
  (2705, 1200) held on a re-read (no snap back) and left the player out of
  bounds (the owner's report), within 100 px of a room edge; (95, 1200) held
  too and put the player in the dark margin at the west of the view, not
  judged standable. **Measured.** So a room
  edge is not a map edge, and what the game does with a jump at the
  walkable map's edge is **not observed**.

[Mod live 1 results](../ForgePact/docs/jump-scenery-research.md#mod-live-1-results)

---

## 20. Gamba machines

What ForgePact's Goburin's Head pity work (#134) established about the gamba
machine: in phase 1, on 2026-10-04, a static reading of the object's events
and three live sessions with its `gambaprobe` instrument (research build), on
save slot 14 ("Sorak"), mostly in the Town of Inoya, with Live 3 also in the
Fields of Battle; in phase 4, Live 4 (2026-10-05/06, research build), whose
explosion watch measured two natural machines' explosions; and in phases 5
and 6, Lives 5 and 6 (2026-10-06) on the player build's `gambapity`, which
measured three more natural explosions and the heads the mod placed at two of them
(§ 20.4). The argument, the controls and the check tables are in ForgePact's
[`docs/gamba-machine-research.md`](../ForgePact/docs/gamba-machine-research.md);
the measurements are also in `hs-game-sdk/curated/gamba_measurements.json`.
**No instrument-created machine has survived its first step** (§ 20.3); a spin
was first measured in Live 3, on a machine the game placed itself (§ 20.4).

### 20.1 The object

- `Slot_Machine_01_obj` (4644) is the gamba machine. Its parents are
  `Collision_Prop_obj` (959) -> `Collision_Parent_obj` (957) ->
  `Avoidable_Parent_obj` (433) (`hs-game-sdk` `kObjectParents`). **Static
  search.**
- Its events are `Create_0`, `Alarm_0`, `Alarm_9`, `Step_0`, `Draw_0`,
  `Draw_64` and `CleanUp_0`, plus one Create closure,
  `gml_Script_anon_1474_gml_Object_Slot_Machine_01_obj_Create_0` (5343; the
  name moves with every patch, §5.3). `Collision_Prop_obj` owns a `Create_0`
  and an `Alarm_11`; the two parents above it own a `Create_0` only. **Static
  reading.**
- The event names do not resolve through `GetNamedRoutinePointer` (no
  `gml_Object_*` name does: 22 of 22 raw event names returned not found,
  `pet-quest-collector-research.md`, 2026-09-10); they are reached by name in the
  compiled-code table, and detours placed there counted `Create_0`, `Alarm_9`
  and `CleanUp_0` on every spawned machine. **Measured.**
- The machine's logic is in these events, not in a named script: no script is
  named for gamba, gamble, slot, jackpot or casino. **Static search.**
- Goburin's Head, the unique charm at repository type 10 / sub 0 / base 98
  (key `charms_goburins_head`), is the prize ForgePact #134 is about; the
  executable stores "Gamba Machine" beside the charm keys as the item
  database's drop-source label. **Static search.** Its rarity code is 10:
  **Measured (Live 5 and Live 6)** on heads built through the loader route
  (§ 20.4). A head the game drops on its own has **not been observed**, so
  the rarity of a natural drop is the part still open.

### 20.2 Creation and state

- The game creates a machine from `gml_Script_ClientCreateEffect` (568), in
  the one case of its switch that carries the object index 4644: a single call
  of the game's own `gml_Script_instance_create` (4556) with x, y and the
  object. `instance_create` takes a layer from a global array and calls the
  `instance_create_layer` builtin on it. **Static reading.**
  `Zone_State_Buffer_obj` (6015)'s Create closures also name the object,
  presumably how machines persist between visits to a zone; those bodies were
  **not read**.
- `Create_0` has one exit and no early return. In order it updates the depth
  (`gml_Script_UpdateDepth`, 4576), arms its alarm 9 for the next step, runs
  the inherited `Collision_Prop_obj` Create (the depth again, alarm 11 two
  steps out), and then sets up the machine's state with about 80 calls by name
  to `gml_Script_InitPV` (119), `gml_Script_SPV` (121) and `gml_Script_GPV`
  (120). `CleanUp_0` frees it through `gml_Script_FPV` (122). **Static
  reading.** So the spin count, the gold spent and the threshold are values in
  the protected `GPV`/`SPV` store the dungeon chest and the satanic zone also
  use (§ 11, § 14), not instance variables, and
  `variable_instance_get_names` will not list them. Which keys hold them is
  **not established**.
- Those by-name calls are **not observed by** a `HookOneScript` detour on the
  scripts' own functions. Both the short name and the `gml_Script_` name of
  `InitPV`, `SPV`, `GPV` and `FPV` resolve through `GetNamedRoutineIndex` to
  the script itself (an index of 100000 or more, so `GetNamedRoutineIndex`
  prefers the script; this does not rule out a same-named functions-array
  entry, which `fnwalk` walks - § 20.5,
  `ForgePact/docs/gamba-machine-research.md` § Instrument), yet over four `Create_0` runs with a machine as `self` the four
  rows counted no call with the machine as `self`. **Measured** (2026-10-04).
  Read a zero on those rows as "not observed by the detour", never as "not
  called"; the dungeon chest's `store GPV calls=2` over a whole dungeon
  (`dungeon-chest-research.md`) has the same shape. How the call reaches the
  store without passing the detour is **not established**.
- `Draw_64` draws each machine's gold spent, so a per-machine gold-spent value
  exists, and the prompt offers a spin for 10,000 gold. **Static reading.**

[Live 2 results](../ForgePact/docs/gamba-machine-research.md#live-2-results)

### 20.3 A spawned machine removes itself

- A machine created from outside the game's own effect route runs `Create_0`
  inside the creating call and, in its first step, runs `Alarm_9`, which
  removes it: `CleanUp_0` runs nested inside `Alarm_9` (the stack walk taken
  at `CleanUp_0` shows, under the runner's frames, a frame in
  `gml_Object_Slot_Machine_01_obj_Alarm_9`). `Step_0` never runs for those seven,
  and nothing is left on screen. Seven machines, all the same: four by
  `instance_create_depth` at depth 0 (three in Live 1: two in town, one in a
  Hell zone; one as Live 2's control in town), then
  one each by the game's own `instance_create` script called by name with the
  player as `self`, by `instance_create_layer` on the player's `layer` value,
  and by `instance_create_depth` with the player as `self` and `other`. The
  route, the layer and the caller's identity varied; the outcome did not. The one exception is the `spawn scp` machine of Live 3 (below): it ran one `Step_0` (`step=1`) before its `Alarm_9` removed it.
  **Measured** (2026-10-04).
- No script or builtin row the instrument held (`instance_destroy`,
  `instance_change`, `layer_destroy_instances` and
  `instance_deactivate_object` among them) counted a call with the machine as
  `self` during that removal. Which runner routine `Alarm_9` removes the
  machine through is **not established**. **Measured.**
- `Alarm_9` logs "Slot Machine Spawned" through `DebugLogAddExt` first, on
  every path, and reports the spawn to clients; "out of thin air" is on a
  later branch. **Static reading.**
- `Alarm_9` reads the machine's protected value `activated` through
  `GetVariable` first; when it is false it sets `activated` and `isActive`
  true and `rollTimes01`..`rollTimes04` each to 8 plus a runtime routine
  called directly with the argument 8 (the shape of the runner's `irandom`
  core - a sign-adjusted argument, an integer result - **not verified**; if
  so, that one call bypasses the `irandom` builtin's table entry), all
  through `SetVariable` by name. **Static reading** (2026-10-04).
- `Alarm_9` then reads the protected value `pSpwd` (instance variable
  `pSpwd` is the key) through `GetVariable`; when it is false it reports
  "Slot Machine Spawned out of thin air" and destroys the machine through
  the runner's instance-destroy routine, called directly - not the
  `instance_destroy` builtin's table entry (Live 2's `instance_destroy` row
  counted no machine call, and the `CleanUp_0-caller` walk's runner frames
  lie inside that routine and its callee). Nothing else in `Alarm_9`
  destroys or deactivates. **Static reading** (2026-10-04).
- `Create_0` initialises `pSpwd` to false, so every machine ForgePact
  created so far died for one reason: `pSpwd` was still false at the first step.
  On the routes above it was never set true; on the `spawn scp` route
  `sCP` called `SetVariable(key, true)` but the stamp did not take effect
  (below). **Static reading** (2026-10-04), the `spawn scp` stamp outcome
  measured in Live 3 (next).
- The `spawn scp` route (§ 20.5) meets the guard on paper and still dies:
  Live 3's `gambaprobe spawn scp` created a machine (`object=4644`, the game's
  own `sCP` frame in its caller walk) that its own `Alarm_9` removed at its
  first step (`create=1 alarm9=1 step=1 cleanup=1`, `machines=0`), so `sCP`'s
  `SetVariable(key, true)` stamp did not take effect. The `spawn stamp` route
  was refused outright (`dispatch failed: GetVariable`), because the extension
  functions do not resolve by name (§ 20.5). A machine the game placed itself
  survived and spun (§ 20.4). **Measured (Live 3)**.

### 20.4 Spin, explosion and prize

- The spin, first measured on a machine the game placed itself (§ 20.3): each
  spin debits 10,000 gold through `PickUpGoldCheck` with the machine as `self`
  (`a1=-10000`, one call per spin), and `GetGoldAmount` with the machine as
  `self` reads the balance after each. Sixteen `PickUpGoldCheck` calls fired
  over the window, with no `instance_destroy` carrying a machine argument.
  **Measured (Live 3).**
- A payout between spins is a random roll, and the machine is not destroyed
  by it: the unique pick is the script `GetUniqueRepoStruct` with the machine
  as `self` (`argc=3`, arguments `1, 0, 72`), whose randomness goes through
  the `cpr_irandom` and `cpr_rand32` script rows (`scope=machine-event`); the
  `irandom` lever armed for the roll stayed `INERT`, which is not-observed on
  that row (the builtin rows are unproven against a compiled call), not proof
  the roll passes no builtin. Two different items were built through
  `CreateDefaultParams`: the unique pick's `(0,72,true)`, placed by
  `LootGroundCreate` with type `1.0` (a unique), and a separate
  `(0,11,undefined)`, placed with type `15.0` (a socketable built by
  `CreateItemNew`). Placement runs `LootGroundCreate` ->
  `CreateLootInFreePos` -> `instance_create_layer` (`Loot_Ground_obj`, plus
  `Coin_obj`, `Loot_Pillar_obj`, `Impact_Sound_obj`,
  `Visual_Effect_Simple_obj`); `machines=2` (the same two ids) before and
  after. **Measured (Live 3).**
- Live 3's sixteen-spin window produced two item builds with the machine as
  `self`, about four spins apart, each followed by more spins. Gold arrived
  separately, as `instance_create_layer` of `Coin_obj` with the machine as
  `self` (three times), never through `CreateDefaultParams`, and the HUD gold
  went back up afterwards. Over that session `CreateDefaultParams` ran 109
  times, 2 of them with the machine as `self`: monster drops pass through it
  too. **Measured (Live 3).** By the owner's report below, neither build was
  its explosion. How often the machine pays out is not established; the
  `rollTimes01`..`rollTimes04` counters stay only as § 20.3's static reading.
  `CreateDefaultParams` itself reads nothing from `self`: it returns
  `{j, b, c}` from its three arguments alone (§ 13.4). **Static reading.**
- The explosion is the machine's sprite changing from `Slot_Machine_01_spr`
  to `Slot_Machine_01_Destroyed_spr` (Python SDK sprite 26574); the instance
  stays: the change line is read off the live instance, and a screenshot
  after the explosion shows the wreck in place. (No `gone` line followed,
  but that line has no positive control: none was recorded even when the
  person left the first machine's zone.) With the machine as `self`, an
  `instance_create_layer` of `Visual_Effect_Simple_obj` comes 2 frames
  before the change, which itself comes about 190-200 frames after the
  machine's last `PickUpGoldCheck` debit. It is not a payout: inside an open
  window whose closed line read `build-dropped=0`, none of the eight build
  rows (`CreateDefaultParams`, `CreateItemNew`, `GetUniqueRepoStruct`,
  `LootGroundCreate`, `LootGroundCreateFromItem`, `CreateLootInFreePos`,
  `DropItem`, `DropUniqueItems`) ran for any `self`, and no `Loot_Ground_obj` was created, while the
  machine's `Coin_obj` creates in the same window showed that the window saw
  its creates; neither explosion (no head dropped in either) built an item.
  The two machines exploded after 12 debits (13 other machine-self calls,
  the person counted 13) and 9 debits (the person counted 8/9), so they did
  not share one spin count. Whether the exploding spin is debited is not
  established (machine 1's 13 against 12 suggests it is not, which would
  make machine 2's count 9-10), and neither is what decides the explosion. **Measured
  (Live 4, two natural machines, 2026-10-05/06; `explosion-route: none`).**
  So after Live 3's last spin, where the last machine-self call was the same
  `Visual_Effect_Simple_obj` create and the instance still existed
  (`machines=2`), that machine may have exploded; its probe did not read the
  sprite. A force that acts on a payout build acts on the wrong event.
- By the owner's report (2026-10-05), **not observed**: the explosion is
  the machine's last act, the machine cannot be used afterwards (not tried
  in Live 4), it comes after roughly 10-14 spins, and in the unmodded game it
  is the only time Goburin's Head drops. Neither Live 4 explosion dropped
  the head, so the route a natural head takes, and whether an explosion
  that drops one builds it through the build rows, are not observed.
- A Goburin's Head built from JSON and placed at a destroyed machine, with
  the player as `self`, lands as one ground item: ForgePact's `gambapity`
  read the machine's sprite change to `Slot_Machine_01_Destroyed_spr` once a
  frame and, 60 presented frames later, ran `json_parse` of the charm's
  `{w, a, j, b, c}` record (`j` 0, `b` 98, `c` 1), `InitItemFromJson` and
  `LootGroundCreateFromItem` at the machine's `x`/`y` (7920,3448) with the
  local player as `self`; `instance_exists` confirmed the returned instance
  on the first attempt, and the built item's rarity read 10. A scan of
  `Loot_Ground_obj` within 256 px of the machine then found exactly one
  charm (`itemType` 10, `j` 0, `b` 98), the drop's own `CreateItemNew`
  returned the charm, and a screenshot showed one `Goburin's Head` label by
  the wreck. The same machine took 12 `PickUpGoldCheck` debits for the
  person's count of 12 spins, the exploding spin included; with Live 4's
  machine 1 at 12 debits for 13, whether the exploding spin is debited
  stays not established (one sample each way). **Measured (Live 5, one
  natural machine, 2026-10-06, player build).** No natural head appeared, so
  how the game builds its own head is still not observed.
- Two more natural machines exploded in one session, after the person's
  counts of 13 and 9 spins (no debit was read: ForgePact's phase-6 build
  hooks no spin), and neither dropped a head of the game's own. At the
  first, the ground scan and the head-build window saw no charm and a
  screenshot showed none by the wreck. At the second, the same loader route
  with the player as `self` placed a charm at the machine (7584,4552), read
  back on the first attempt with rarity 10, and the ground scan after it
  found exactly that one (`heads=1`). Two machines stood in one zone (Deep
  Space, Pyramid Level 1) before the first spin. Across Live 4, 5 and 6,
  five natural machines exploded, at the person's counts of 13, 8/9, 12, 13
  and 9 spins, none with a head of the game's own; what decides the
  explosion is still not established. **Measured (Live 6, two natural
  machines, 2026-10-06, player build).**
- `Step_0` does not decompile on this build (the decompiler process died on
  it). A call-by-call listing of it, with callees named from the symbol dump,
  shows only these named script calls: 7 `CreateDefaultParams`, 3
  `GetUniqueRepoStruct`, 2 `LootBlocksUseKey`, 2 `GetGoldAmount`, 2
  `GoldOperationPending`, 2 `NetworkSendClientEffect` and 1
  `GetGoldCounterHash`. The builds sit in one stretch: three builds with no
  pick before them, three pick-then-build pairs and one trailing build. Each
  pick site loads the same small constants at the same distances before the
  call, consistent with all three picking the measured `(1, 0, 72)`, and no
  site was seen loading 10 or 98. **Static reading, not verified** (a small
  operand can be a stack offset); it cannot say which build, if any, is the
  explosion's.
- `Step_0` is the only event that calls `GetUniqueRepoStruct` (3 sites) and
  `CreateDefaultParams` (7) directly, the pair the Angelic roll uses (§ 13.4).
  No event calls `LootGroundCreate`, `LootGroundCreateFromItem`,
  `CreateLootInFreePos`, `DropItem`, `DropUniqueItems`, `cpr_irandom` or
  `cpr_rand32` directly, and none names them for lookup. Neither 10,000 nor
  750 appears as a literal in the `Create_0`, `Alarm_0` or closure bodies, so
  the price and the odds live in constant tables or the protected store.
  **Static reading.**
- `PickUpGoldCheck` is the only call that changes the gold balance (§ 13.10);
  the spin's gold debit is measured through it with the machine as `self`
  (above). **Measured (Live 3).**
- In about 15 seconds of combat with no mod on, `gml_Script_cpr_irandom` (707)
  was called 1,308 times and `gml_Script_cpr_rand32` (709) 1,386 times, while
  the `irandom`, `irandom_range`, `random`, `random_range` and `choose`
  builtin rows did not move (an `irandom` sent through `CallBuiltin` in the
  same session did register, so the rows see a `CallBuiltin`-routed call; they
  are unproven against a compiled call, so this is not-observed, not proof
  combat calls no builtin RNG). Combat's rolls go through the `cpr_*` scripts.
  **Measured (Live 2)**. The
  machine's prize roll passes the same `cpr_*` scripts (above); a builtin RNG
  row did not move, which is not-observed. **Measured (Live 3).**

[Live 2 results](../ForgePact/docs/gamba-machine-research.md#live-2-results)
[Live 3 results](../ForgePact/docs/gamba-machine-research.md#live-3-results)
[Live 5 results](../ForgePact/docs/gamba-machine-research.md#live-5-results)
[Live 6 results](../ForgePact/docs/gamba-machine-research.md#live-6-results)

### 20.5 The spawned flag and the game's spawner

- The spawned flag is a protected value, keyed by the ordinary instance
  variable `pSpwd`'s value; `Create_0` initialises the flag to false through
  `InitPV`, and `Alarm_9` destroys a machine whose flag is still false in its
  first step (§ 20.3). `sCP` is the game's own spawner that sets it true.
  **Static reading** (2026-10-04).
- `sCP(x, y, object)` (474) calls the `instance_create_layer` builtin with
  `(x, y, global.gameLayer[room][0], object)` - the layer the game's own
  `instance_create` script also picks - then reads the new instance's `pSpwd`
  key and calls `SetVariable(key, true)` by name with the caller as `self`,
  and returns the instance. No early return, no other check. **Static
  reading** (2026-10-04). The argument order `(x, y, object)` contradicts
  `S10-special-content-notes.md` ("object ref, x, y"), which § 14.3's bullet
  once copied (it now reads `sCP(x, y, object)`); Live 3's `spawn scp` answered `object=4644` with the default
  `(x, y, object)` order, confirming it. **Measured (Live 3)** for the order.
- The same `pSpwd` guard is shared game-wide: 60 compiled functions read that
  variable slot - chests, portals, shrines, globes, pickups, the zone state
  buffer's Create closure, `ZoneGenPopulatePresetObjects`, `CreateItemDrop`,
  `DropGold`, `LoadBossDeath`, and `ClientCreateEffect` once inside its
  machine case. So § 20.2's "a single call of the game's own
  `instance_create`" was incomplete: the effect case also stamps `pSpwd`,
  which is why the `game` spawn route (the call without the stamp) died.
  **Static reading** (2026-10-04).
- `Alarm_9` and `sCP` do not use the store scripts at all: they reach the
  machine's state through the extension functions `GetVariable`,
  `SetVariable` and `SetVariableToUndefined`, called by name with the builtin
  convention (a compiled `SetVariable` call branches on `is_undefined(value)`
  to `SetVariableToUndefined(key)`). **Static reading** (2026-10-04).
- The three extension functions do **not** resolve by name from the plugin:
  `GetVariable`, `SetVariable` and `SetVariableToUndefined` all read
  `(not found by name, st=4) missing` at `hook`, so the state route is blind
  (`state-route: blind`) and the `spawn stamp` route is refused (`dispatch
  failed: GetVariable`). **Measured (Live 3).**
- `fnwalk` could not locate the functions array by validation: `gambaprobe
  fnwalk: table not found (no aligned qword equal to camera_create's routine
  with eight valid entries)`, so the by-name route stays blind
  (`byname-route: blind`) and whether the array holds same-named entries for
  the store scripts is still open. **Measured (Live 3).**
