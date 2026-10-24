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
The `equippedItems` array (or `inventory` equipped region) organizes items by
numeric slot index. Only some rows are measured; the rest were written before
any measurement and stay **not measured**, and one of them (slot 3 as the
gloves) is contradicted for the character measured:

| Slot Index | Equipment Type | Status |
|---|---|---|
| `0` | Helm | **Measured**: the worn helmet (ForgePact #166, Mod live 2, 2026-10-19). |
| `1` | Body armour | **Measured**: the worn body armour (Mod live 2). |
| `2` | Boots | **Measured**: the worn boots (Mod live 2). |
| `3` | (the table said Gloves) | **Not measured.** The gloves are not here on the character measured: Mod live 2 found them at slot 4, and a read of slot 3 did not change when they came off or went back on. |
| `4` | Gloves (the table said Belt) | **Measured**: the worn gloves (Mod live 2), on save slot 14's Sorak; another character not read. |
| `5` – `8` | (the table said Amulet, Ring 1, Ring 2, Main Hand) | **Not measured.** |
| `9` | Off Hand | **Measured**: the off hand (ForgePact #93, 2026-09-27, below). |
| `10` – `14` | Relics (`0`–`4`) | **Measured**: the five equipped relics (#93, below). |
| `15` – `18` | (the table said Charms) | **Not measured.** 15-17 were empty on the character measured, and the measured array is 18 strings long (0-17), so it has no slot 18. |

The rows for slots 0, 1, 2 and 4 come from the Mark 1 set's worn read, which
looks for each of its four pieces among gear slots 0 to 9 of
`global.equippedItems[global.mplr][0]` and names the slot it found each in
(`worn=0/1/2/4`, helmet, body armour, boots, gloves; with the gloves off,
`worn=0/1/2/-`), in `Town_01_rm` on save slot 14, "Sorak" (White Mage):
[Mark 1 research, Mod live 2 results](../ForgePact/docs/mark1-set-research.md#mod-live-2-results).
The gloves at 4 match their item class (4 in `hs_game_sdk.ItemType`), and so
do the helmet, body armour and boots (classes 0, 1 and 2), but the off hand's
fingerprint at 9 ends in class 7 (below), so a slot is not its item class in
general. `hs_game_sdk.player.EquipmentSlot` still
carries this table's unmeasured `GLOVES = 3` and `BELT = 4`.

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

**A room with no `Player_obj` has no local player, for every reader.**
`GetMyPlayer` walks the `Player_obj` instances and answers `noone` (-4) when
none matches (**static reading**, the decompiler copy of this build through
the Ghidra MCP, 2026-10-13, in our own words). So wherever there is no
`Player_obj`, every read that goes through the local player answers "no
player": the player's `name`, `GPV` with the player as `self`, a scan of the
player's buffs. Measured cases: while the world map is open there is no
`Player_obj` and every player read answers "no player"
([satanic zone, Live 4](../ForgePact/docs/satanic-zone-mods-research.md#live-4-2026-10-04-what-loadsataniczone-really-answers-and-the-map-marker));
and `Player_obj` gets a new instance id on a room change (§ 19.5), so a
handle kept across one is stale. A room's setup spans frames
(`NetworkRoomSetupDone` asks `EnemyCreatorPending` before its "room is set
up" work, static reading), and in Live procedure 1 of
`forgepact-185-tracker-move` the tracker's one read of the name and the zone
on a room change's own tick answered neither (measured; that the player was
the missing piece is consistent with the record but was not measured). How
many ticks a new room runs without a player is not measured. Live procedure 2
of `forgepact-185-tracker-zone-fix` (2026-10-14) bounds it for one travel into
`Act_01_01`: the zone readers, polled every 15 ticks, failed twice, the last
time with `no-player`, then answered, so 15 to 30 ticks (§ 14.1). That is a
bound, not a duration. So a reader
that must answer once per room reads until it answers, not once on the room
change's tick.

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
| `asset_get_index(name)` | `VALUE_REF`, not a number; a kind check for a number rejects every object. Validate with `object_exists` / `sprite_exists` / `room_exists`, or convert with `real()` (**measured** 2026-09-17 on the pre-2026-09-18 build `pe6a9ed3ee`, HS-AFK-Expedition, [AFK §10.5](research/afk-expedition-adding-content.md)) |
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
  - Two more player dumps (2026-10-19/20, density 5 with Special Content at
    100×; 617 monsters and 5,996 instances a minute before the first) fault at
    the same place: `ac_dll_gm.dll!SetVariable+0xb4`, under the game's own
    `instance_create_layer`. The faulting registers put the write one 40-byte
    record before the table (page 0, slot -1), which is what handle -1 gives.
    **Measured** from the dumps.
    - **Static reading** of the exported functions' machine code:
      - The store is 512 pages of 512 records, 40 bytes each, and a handle is
        split into a page (handle / 512) and a slot (handle % 512).
      - `InitNewVariableFast` scans forward from a cursor and returns -1.0
        when it reaches the end.
      - `FreeVariable` moves the cursor back to a freed record below it, so a
        -1 means every record really is live.
    - **Measured live** on 2026-10-20
      ([population capacity, Live 1](../ForgePact/docs/population-capacity.md#live-1-2026-10-20-research-build-slot-14-lease-forgepact-232-pool-capacity-live-1)):
      the pool does refuse once it is full, since ForgePact's router (which
      spills only on -1) put 823,541 records into extra pools. It also refuses
      expensively: the frame thread stalled for seconds inside the scan loop
      of pools that were full, consistent with a refusal scanning from a
      rewound cursor to the end.
    - **Not observed:** a check on the game's side that refuses a -1 handle
      before `SetVariable` uses it. Both crashes show the -1 reaching it; no
      call site was searched with a positive control.

    What filled the store (live monsters or records that outlive them) is
    **not established**, because the minidumps do not include the store's
    memory. ForgePact's capacity router answers it from 2.4.0
    ([ForgePact#232](https://github.com/falorfrozen-cmd/ForgePact/issues/232)).
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

### 5.11 What a plugin's exception handlers see at a crash

**Measured** twice, both on 2026-10-19 with game 7.0.13.0: ForgePact #223
Live 1 (research DLL built at `a4db66c`) and Live 2 (research DLL built from
`38acede`'s plugin code). The captures are the hub workorder files
`forgepact-222-223-extra-rolls-crash-trap-live-1.md` and `-live-2.md`, kept
locally.

- Each crash was crashwatch's positive control, run in-mod `ipc`: an access
  violation (`0xC0000005`) raised on the game thread inside
  `BloodPactPlugin.dll` (Live 1 at `+0x1BC12A`, Live 2 at `+0x1BC53A`). Both
  processes ended with exit code `0xC0000005`.
- The plugin had installed two routes: a vectored handler registered first
  (it sees the exception at first chance), and a top-level
  unhandled-exception filter (`SetUnhandledExceptionFilter`). Before each
  crash, `incident stat` read the filter as installed and still top-level
  (`unhandled armed (top-level)`).
- In both sessions the vectored handler ran and recorded `route=first-chance`.
  The top-level filter was **not observed** to run in either: neither crash
  recorded a `route=unhandled` line. In Live 1 none of the work the filter
  started at that time (the dump, the log copies) happened either.
- Live 1's process was not a clean one. Headless x64dbg (`tools.x64dbg_mcp`)
  was attached to that same process (pid 29784) for most of the session, from
  shortly after its 12:11 UTC launch, and detached, confirmed, before the
  crash control at about 13:03:25 UTC. An attached debugger makes Windows
  skip the top-level filter, so on its own Live 1 left open whether the
  detach had left something behind with the same effect.
- Live 2 repeated the crash control on a process no debugger touched at any
  point (pid 23600, crash at about 14:18 UTC), and the result was the same:
  `first-chance` only, the top-level filter not observed to run. So the
  earlier debugger attach does not explain the result on its own.
- Why the filter does not run is **not established**. Another handler ending
  the process, a frame that catches the fault and terminates, or something
  else are all open; two crashes, each from the same in-plugin control, say
  nothing about which.

So this is not a measurement that the top-level filter never runs in Hero
Siege: both crashes are one kind of fault, raised in one place. It is a
measurement that, for that fault, the filter did not run, with and without a
debugger having been attached earlier. ForgePact's crash trap therefore does
not rely on the top-level filter: whatever has to be captured at a crash is
started from first chance, and in Live 2 that staging produced the report's
dump and log tails. The trap's design, its staging rules and both sessions'
results are in
[ForgePact/docs/incident-report.md](../ForgePact/docs/incident-report.md).

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
- **The key refuses Mana Orb beyond its cooldown.** Its talent reads
  `abilityCooldown` 6 and `abilityLength` 240. With Mark 1's automation
  pressing Q, 74 presses in 30 s landed no Mana Orb, and a hand-held Q for
  4 s while the automation left the gate alone cast none either, where the
  same windows landed Healing Zone at its cooldown and Shadow Bolt
  continuously; across the session a Q press landed only now and then (one
  in a 10 s window, one in a 4 s hold). § 7.7 measured a forced Mana Orb
  press casting once in more than 480 frames. Why the game refuses it is
  **not established**; plausibly while its orb lives (about 35 s with
  Chosen One, above). Whether a direct `TalentUseClass` call (§ 7.9) casts
  it while the key refuses it was not established: the session's direct
  calls of Mana Orb passed the player as a number, not a ref, and were
  counted as calls that returned, not as casts. **Measured 2026-10-22** (ForgePact's Mark 1 Stats live 1,
  `prio-order`, `lock-key`, `free-cadence`).
- **What Mana Orb and Healing Zone do besides their effect** (the owner's
  word, 2026-10-22, **not measured**): Mana Orb raises the player's mana
  regen, so with it on the bar the HUD mana can refill too fast to show a
  cost; Healing Zone has a constant life drain while it runs, which the
  owner gave as the cause of the low life seen in that session (as low as
  531 of 5651). Measured beside it: with the automation casting Healing
  Zone, the life replenish's dispatcher original (id 38) read 159 and 242
  where it had read 46 before (plausibly the zone's own replenish; not
  established).
  [Mark 1 Stats live 1 results](../ForgePact/docs/mark1-set-research.md#stats-live-1-results)

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
- **Added after the sliders shipped** (ForgePact 2.2.0's `skillslider`, two
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

### 7.7 The cast gate and its input

What ForgePact's Mark 1 research (#166, phase 1) read on 2026-10-13 about how
a key press on the skill bar becomes a cast, in the build Ghidra imported (the
one `py -3 tools/decomp_index.py build-hash` names). Sources: a local headless
decompile of `CheckTalentUse` (2026-09-25, this build) read with the decompile
index's slot names; a local scan of each script's compiled code for the
variable, builtin and script names it references, the direct calls it makes
and the constant ids it passes (its positive control: on
`PathFindControllerCreate` the scan listed exactly what the MCP decompile of
that function shows); and the ghidra MCP for the small functions. A byte scan
of direct call sites is blind to calls through the script table or a method
value, so a caller it did not find is not observed, not absent. Every bullet
is a **static reading** (2026-10-13) unless it says measured. The **measured**
parts come from the research's Live 1 session on 2026-10-13 (the
`mark1probe` instrument and x64dbg logpoints, save slot 14, White Mage, in
`Town_01_rm`, on the build above): see
[Mark 1 research, Live 1 results](../ForgePact/docs/mark1-set-research.md#live-1-results).

- **The gate runs inside the movement step.** The only direct call site of
  `gml_Script_CheckTalentUse` (539) found is in `gml_Script_PlayerMovement`
  (2774), which the player object's Step event calls. Its entry was measured
  at about 85 calls a second in town with `self` equal to `other` and three
  arguments ([x64dbg-mcp.md](tools/x64dbg-mcp.md), "Breakpoint rules").
  **Measured** in Live 1: the local player's calls come once a frame
  (consecutive frame numbers), and every call the probe saw was the local
  player's (local and total counts equal), so the 85 a second is one call per
  frame at the frame rate of that session, not several per frame.
- **None of its three arguments names a bar slot.** All three are optional.
  The first is the player instance (when it is undefined the gate takes a
  value from the game's protected global data). The second is the player
  number (default: the global `mplr`), and goes with the player into the
  talent-info and talent-requirement lookups. The third (default 1) is the
  index into `Input_Device_Manager_obj` (2259)'s `playerProfileSlot`, and is
  handed on unchanged as `TalentUse`'s third argument, which § 7.2 measured
  as 1 on a key cast. **Measured** in Live 1 (`ctu-args`): over 300 local
  calls, idle and with Q held down, the three arguments were always the
  player (as a `VALUE_REF`), 1 and 1. No argument names a slot.
- **The bar slots are a loop inside the gate**, over a counter from 0 to 11.
  For each value it looks the slot's talent id up (through a ds_map lookup
  and two further lookups keyed by the counter), then decides whether the
  slot is asking to cast.
- **The key state comes from the profile slot.** For each bar slot the gate
  reads `Input_Device_Manager_obj.playerProfileSlot[<third argument>]`, and
  from that entry the `inputState` array, at an index an unnamed helper
  derives from the slot counter (the derivation was not read), and compares
  it against one state value (which value means "pressed" was not read). It
  does this on 15 paths. § 10.4 measured `inputState` on `Profile_Manager_obj`
  (3673), 78 entries resting at 1. The profile slot's entry is plausibly a
  `Profile_Manager_obj` instance: it also carries the `inputSimMap` that
  object's Create event makes (next bullet). **Measured** in Live 1
  (`slot-keys`): the entry read was `playerProfileSlot` entry 1 of
  `Input_Device_Manager_obj` instance 0, and each bar key moved one
  `inputState` entry of it, the bar column the slot sits on: Q entry 3, E
  entry 4, R entry 5, Y entry 6 (entries 26 and 25 moved together with Q and
  E, for a reason not read). An entry rests at 1, reads 4 on the press frame,
  3 while the key is held and 2 on the release frame, then 1 again. The
  entries of the other bar columns were not measured.
- **Writing the press value inside the gate casts the slot (measured).** In
  Live 1 (`cast-input`), writing 4 into a slot's `inputState` entry just
  before each local `CheckTalentUse` call, and restoring it after, cast that
  slot's skill with no key pressed (Mana Orb on column 3). With the value
  forced on every call for more than 480 frames (about 5.6 s at the session's
  ~85 fps), Mana Orb was cast once (`cast-gate`). What refused the repeats
  (its cooldown, mana, the orb still being alive, or how the forced press is
  seen) was not read, and Mana Orb's cooldown was not read in that session:
  that the game's cooldown still applies to a forced press is **not
  established**, and neither is whether the forced cast still charged mana.
  An immediate key recast of Mana Orb has been measured to work (§ 7.3, the
  `effect=` count reading 2 right after a recast), so the window may well be
  longer than the cooldown; talent 253's cooldown is the next read. The same
  write on Soul Spurn's column switched the toggle on and off 13 times in 600
  frames (`toggle-flips`), and on an empty column it called no `TalentUse` at
  all (`empty-slot`).
- **The same write on Healing Zone and Soul Spurn (measured, 2026-10-19).**
  In the Mark 1 research's Mod live 1
  ([Mod live 1 results](../ForgePact/docs/mark1-set-research.md#mod-live-1-results);
  the same character and game build, a later research DLL, at about 144
  frames a second), writing
  4 into `inputState[4]` (E, column 4) for one gate call cast Healing Zone,
  once inside a walk and once standing, each counted by the probe's
  `TalentUse` row; the same write made soon after a key cast of it cast
  nothing (plausibly its cooldown, which was not read). One such write into
  `inputState[5]` (R) switched Soul Spurn on, its on-state object
  `White_Mage_Soul_Spurn_AOE_obj` appearing 19 frames later
  (`toggle-settle`). A second write switched it off 20 frames after the
  press, and it was on again 57 frames after it with no further write; what
  switched it back on was not read. Whether a forced cast costs mana is still
  **not established** (`cast-mana`, not-observed): no number or bool element
  of the player's `pSt` changed on a key cast or a forced one, and none
  changed in any `pSt` watch of that session (which reads only those kinds),
  so nothing shows mana is held there.
- **The same write on three columns at once, every gate call (measured,
  2026-10-19).** In the Mark 1 research's Mod live 2
  ([Mod live 2 results](../ForgePact/docs/mark1-set-research.md#mod-live-2-results);
  the same character and game build, the Mark 1 set's shipped automation on a
  research DLL, at about 144 frames a second), the press value was written
  into Q's, E's and R's `inputState` entries inside every local
  `CheckTalentUse` call, with Shadow Bolt on Q, Healing Zone on E and Heavenly
  Fire on R (both no-cooldown skills read `abilityCooldown` 0.25, Healing
  Zone 14). Over 1350 gate calls (one a frame) Shadow Bolt cast 20 times,
  Healing Zone once, and a cast of Heavenly Fire was **not observed** in any
  of them (`on-automation`), with no read, write or restore failing. Why it
  never cast is **not established**: Shadow Bolt's column may have been
  served first on every call, or Heavenly Fire may not be castable through
  the press write, in town, or within the mana Shadow Bolt's casts left (no
  mana value is known), and no session records a cast of Heavenly Fire, by
  key or forced, that would tell these apart. In which order the gate serves
  the asking slots, and whether it serves more than one a call, is likewise
  **not established** (the slot loop's order was not read). An empty column
  (Y) was skipped every call and never pressed.
- **The game's refusal holds a forced press (measured, 2026-10-19).** In the
  same session Healing Zone's column, pressed every gate call, cast once in
  1350 presses (`gate-kept`), and over 3600 frames with no key it was recast
  at intervals of 661, 910, 1071 and 501 frames, each rise of
  `White_Mage_Healing_Zone_obj`'s count marking one (`cooldown-recast`; the
  probe counted four casts against five rises in that window, not
  reconciled). Its `abilityCooldown` reads 14; 14 seconds would be 2016
  frames at that frame rate, longer than every interval, so the value's unit,
  and what makes the intervals differ, are **not established**.
- **Pressing one column a call casts every skill on the bar (measured,
  2026-10-20).** In the Mark 1 research's Mod live 3
  ([Mod live 3 results](../ForgePact/docs/mark1-set-research.md#mod-live-3-results);
  the same character, game build and frame rate, the set's turn rule on a
  research DLL), the press value was written into one column's `inputState`
  entry per local `CheckTalentUse` call, the column whose last landed cast
  was longest ago, on the same bar as above. Over 4590 gate calls with no key
  Shadow Bolt cast 31 times, Heavenly Fire 30 and Healing Zone 3
  (`on-automation`), and a key cast of each no-cooldown skill had counted
  first (`casts=239:1,245:1`). So Heavenly Fire casts by key on this
  character in town and through the press write, and the previous bullet's
  zero came from pressing several columns in one call; which of them the gate
  serves then is still **not established**. A landed cast is seen as a local
  `TalentUseSetSpeed` call during the gate's call (§ 7.8): the set's count of
  those per column matched the probe's `TalentUse` count per talent exactly,
  alone (4 of 4) and beside the others (31, 3 and 30), and every such call it
  saw was one of them (`turn-landed`).
- **One Healing Zone cast can leave two zone instances (measured,
  2026-10-20).** In the same session (`landed-control`), with Healing Zone
  alone on the bar and cast by the press write, a rise of
  `White_Mage_Healing_Zone_obj`'s instance count went from 0 to 2 at one cast
  in each of two windows while the probe's `TalentUse` row counted one, and
  in a 3600-frame window beside Shadow Bolt and Heavenly Fire four rises stood
  against three casts, the extra instance lasting 88 frames
  (`cooldown-recast`). So the instance count is at least the number of casts,
  not equal to it, which accounts for the five rises against four casts
  above. What the second instance is was not read. Alone on the bar, Healing
  Zone was recast 1575 frames apart in both windows; beside the other two,
  1064, 587 and 1627 frames apart, so its `abilityCooldown` unit is still
  **not established**.
- **The game has its own input simulation.** `gml_Script_InputSimulate`
  (1903) takes a profile slot index, a key and a value, and stores the value under
  the key in that profile slot entry's `inputSimMap` (a ds_map). That map is
  read by `Profile_Manager_obj`'s Begin Step event (eight references) and
  `Controller_obj`'s Begin Step event (four), both of which run before the
  Step event that reaches the gate. `InputCheck` and `InputPressed` read
  `playerProfileSlot` and `inputState` the same way the gate does. No direct
  caller of `InputSimulate` was found (not observed), what its keys are and
  how the Begin Step folds the map into `inputState` were not read. It is a
  candidate cast route that leaves the game's own gate in charge, and unlike
  posting a key to the window it does not depend on which key is bound.
- **The queue is a second way into the same slot.** `abilityQueue` and
  `mobileTalentPressed` are global arrays (both are created in
  `gml_GlobalScript_DefineGlobals`), indexed by the bar slot counter. When the
  slot's key state does not ask for a cast, the gate reads the slot's
  `abilityQueue` entry, and when that is not set either, its
  `mobileTalentPressed` entry; only when all three are unset does it move on
  to the next slot. Later it writes both entries of the slot back with 0, and
  one other path writes 1 into `abilityQueue`'s entry 0. So an entry is a
  0-or-1 flag per bar slot. `PlayerMovement` writes `abilityQueue` at five
  sites (values not read); nothing else found references it. `autoAim` is a
  global array read the same way, per slot. Whether setting a slot's
  `abilityQueue` entry makes the gate cast that slot is **not established**:
  Live 1 did not try it, because the input write cast first. **Measured** in
  Live 1 (`queue-observed`): over two key presses with one cast, none of the
  first four entries of `abilityQueue`, `mobileTalentPressed` or the player's
  `stackSkillList` changed from one frame to the next. The watch reads entries
  0-3 of each array only, once a frame at the frame's end, so an entry of a
  later slot, or one set and cleared inside one gate call, would not show;
  whether a key cast goes through the queue is therefore **not established**.
- **`stackSkillList` is a variable of the gate's own `self`**, read at five
  sites and taken for writing at two.
- **The cast itself.** Per slot that asks, the gate calls `GetTalentInfo`
  (1788) and `TalentRequirement` (3769), and then, at its one `TalentUse`
  (3829) site, calls it with the player, the slot's talent id, its own third
  argument and false (the arguments § 7.2 measured on a key cast). It also
  asks the stat dispatcher for id 199 (no case in the dispatcher's table as
  [skill sliders' reading](../ForgePact/docs/skill-sliders-research.md#returnspecificstat-the-dispatchers-case-table)
  lists it) and calls `PlayerManaUpdate` and `PlayerHpUpdate`.
- **An earlier negative does not cover this reader.** § 10.4 measured that
  writing `inputState` from the frame callback did nothing for the interact
  key, whose check reads the keyboard directly, and that write landed at
  `EVENT_FRAME`, after the frame's readers ran. A write inside the gate's own
  call, just before it reads, does cast (**measured**, Live 1, above).

[Mark 1 research, Static reading](../ForgePact/docs/mark1-set-research.md#static-reading)

### 7.8 What a cast does to movement

From the same reading as § 7.7 (2026-10-13, static unless marked). The
**measured** parts are from the same Live 1 session
([Mark 1 research, Live 1 results](../ForgePact/docs/mark1-set-research.md#live-1-results)).

- **`gml_Script_TalentUseSetSpeed` (3830)** has two direct callers found,
  `TalentUse` (3829) and `gml_Script_CA_playerTalentActive` (368), one site
  each. It asks the stat dispatcher for ids 68 and 69 (the two attack speeds)
  and 106 (faster cast rate), and calls `GetTalentCooldown`, `GetTalentInfo`,
  `ReturnSubTalentLevel`, `LoadSubTalentDamage`, `SetCooldown`,
  `RefreshMouseMove`, `GetPlayerDevice` and `IsMyPlayer`. Besides the cast
  speed it writes six entries of the player's `playerEffect` array (entries
  40, 46, 79, 182, 231 and 282; what each entry means is not read) and sets
  `image_speed` on an instance or object it names (which one is not read). It
  references no movement-speed name (`hSpeedFactor`, `vSpeedFactor`,
  `mobileSpeedFactor`, `moveSpeed`). So if a cast slows the caster, it is
  plausibly through a `playerEffect` entry or the movement step's own state,
  not a movement variable this script names. **Measured** in Live 1
  (`dbg-cast-speed`): an x64dbg logpoint on its entry logged 17 hits over the
  session's key casts, every one returning to the one direct call site in
  `TalentUse`; `CA_playerTalentActive` was not observed calling it.
- **A cast slows the walk briefly (measured).** In Live 1
  (`penalty-baseline`), Healing Zone cast one second into a three-second walk
  cut the walk's step from about 6.0 px a frame to about 3.9 px (about 0.65)
  for about 21 frames, after which it climbed back to 6.0 px; the walk
  covered 6.5% less than without the cast. The player members that changed
  after the cast (`playerSequenceTopPrev`, `playerSequenceBottomPrev`,
  `playerSequenceDirection`, `manaArrayPos`) did not settle back within 90
  frames, so none of them follows the penalty's course; the member that
  holds the penalty was not observed (`penalty-vars`).
- **The slowdown has a flat part and a ramp, and `playerEffect[199]` follows
  the ramp (measured, 2026-10-19).** In the Mark 1 research's Mod live 1
  ([Mod live 1 results](../ForgePact/docs/mark1-set-research.md#mod-live-1-results)),
  at 6.94 ms a frame, a Healing Zone cast one second into a walk dropped the
  step from 2.989 px to 1.943 px (0.650) for 57 frames, then a 16-frame ramp
  brought it back (`penalty-control`). Element-wise watches from the cast
  showed `playerEffect[199]` falling from 1 to 0.65 on the cast frame and
  climbing back to 1 frame for frame with the ramp, 57 to 73 frames after
  the cast (`penalty-watch`); so `playerEffect[199]` is the cast's speed
  factor during the ramp. Holding it at 1 during `PlayerMovement` removed the
  ramp and left the 57 flat frames at 0.650 (`penalty-lever`), so the flat
  part's 0.65 comes from somewhere that hold does not reach, which is **not
  established**. `playerEffect[204]` turned from true to false 56 frames
  after the cast, the frame before the ramp, a candidate for the flat part
  that was not held. The cast also turned `playerEffect[205]` from true to
  false and changed `playerEffect[196]` and `playerEffect[250]` 18 frames
  after it; `playerEffect[54]`, `[56]` and `[192]` count down by one a
  frame. The movement speed stat's answer did not move through the slowdown
  (151 on every frame, `penalty-stat`). The `pst` watch (number and bool
  entries only; how many of the 54 it covered was not recorded; no positive
  control within `pSt` in that session) saw no change at a frame boundary in
  the 90 frames after a cast, which is not observed, not a negative: the
  cached `pSt` values `PlayerMovement` reads remain an open candidate for
  the 57 flat frames (**not established**, see the `pSt` bullet in § 7). Of
  the player's builtin variables only `image_index` changed. The slowdown lasted more frames than Live 1's 21 at
  about half this frame rate; whether it is timed in frames or in time is
  **not established**. **Measured** too (`dbg-cast-active`): an x64dbg
  logpoint on `CA_playerTalentActive` logged no hit over a standing Healing
  Zone cast while the control logged, so it is not on a key cast's path (not
  observed).
- **Casts every 60 frames keep `playerEffect[199]` at 0.65 (measured,
  2026-10-19).** In the Mark 1 research's Mod live 2
  ([Mod live 2 results](../ForgePact/docs/mark1-set-research.md#mod-live-2-results)),
  with Shadow Bolt cast about every 60 frames by the set's automation and the
  half walk on, `playerEffect[199]` read 0.65 on every watched frame of three
  bonus-on walks, rising to 0.670833 for one frame at each Shadow Bolt cast;
  no frame read 1. So whether the cast's slowdown stacks on a halved walk or
  replaces it was **not observed** (`on-speed`, `on-penalty`,
  `penalty-stack`). One consistency observation, not a measurement: those
  windows' modal step, 0.775 px, is 0.325 of the same session's unlevered
  2.385 px, and 0.325 equals 0.5 × 0.65, what stacking would give; the
  frames behind it are all under the slowdown, so nothing compared them with
  an unslowed bonus-on step. The watch's 400-line reply cap ended each watch
  after about 126 of its 240 frames.
- **The cast's slowdown stacks on the half walk (measured, 2026-10-20).** In
  the Mark 1 research's Mod live 3
  ([Mod live 3 results](../ForgePact/docs/mark1-set-research.md#mod-live-3-results);
  the same character and build, 6.93 to 6.94 ms a frame), with Healing Zone
  alone on the bar and the set's half walk on, a walk's 86 watched frames at
  `playerEffect[199]` = 1 stepped 1.192 px; an automated Healing Zone cast
  then dropped `playerEffect[199]` to 0.65 and the step to 0.775 px, 0.650 of
  the pre-cast step, for 76 frames (one double step among them), and a
  16-frame ramp brought it back to 1.192 px (`on-penalty`, `penalty-stack`).
  So the slowdown multiplies the halved walk, and under a cast the set walks
  at 0.325 of the unlevered step, which the previous bullet's windows showed
  by arithmetic and this one measured. The flat part ran 76 frames against
  Mod live 1's 57 for a key cast without the set at the same frame time; why
  it ran longer is **not established**.
- **`manaArrayPos` is plausibly the mana graph's ring index, not mana.**
  **Static reading (2026-10-14, unannotated)**, through the ghidra MCP, of
  `gml_Script_PlayerManaUpdate`: its body came out with no variable names, but
  it reads an array at a few small constant indices and advances a position
  that wraps back to the start at 100, writing into a 100-entry history array.
  That shape fits Live 1's observation that `manaArrayPos` rose by one per
  update and never settled back after a cast: it is plausibly the write
  position of a 100-sample mana history (the kind a mana graph draws), so a
  change in it says a mana update ran, not how much mana the player holds.
  Where current mana is held is **not established** (plausibly an entry of
  `pSt`, the player's stat values, unread).
- **`PlayerMovement` (2774)** calls `TalentUseClass` (3833) once and
  `CheckTalentUse` once, reads its own `playerEffect` at 21 sites and takes it
  for writing at 19, and reads `pSt` (the player's stat values) at 32 sites.
  The player object's Step event calls `TalentUseClass` at five more sites.
  Which of these holds the caster still while a skill is cast is **not
  established**. **Measured** in Live 1: the player's `pSt` is an array of
  54 entries, not a struct or an instance, so a watch of named members reads
  nothing from it. **Not observed** in Mod live 1 (2026-10-19, above): the
  element-wise `pst` watch saw no change at a frame boundary in the 90 frames
  after a cast, nor in the 60 after a key cast or a forced one. That watch
  reads only number and bool entries (an array, struct or reference entry is
  left out without a word), how many of the 54 it covered was not recorded,
  and no `pSt` element changed in any watch of the session, so it had no
  positive control within `pSt`. The cached `pSt` values `PlayerMovement`
  reads therefore remain an open candidate for what holds the cast
  slowdown's 57 flat frames (**not established**).

[Mark 1 research, Static reading](../ForgePact/docs/mark1-set-research.md#static-reading)

### 7.9 Procs: how the game fires a skill without a cast

Written for ForgePact#166 (2026-10-22), when the owner asked whether Mark 1's
automation could fire a skill the way the game fires an item proc, with no
cast time. **Static reading** (2026-10-22, in our own words) except where
§ 7.2 measured it: one headless `FindCallers.java` byte scan of the direct
call sites of `TalentUseClass`, `TalentUse`, `TalentUseSetSpeed`,
`SetCooldown` and `GetTalentCooldown` (positive control: `CheckTalentUse`
called from `PlayerMovement`, found), a `ListCallsIn.java` listing of
`TalentUse`'s calls, and annotated decompiles of `EnemyDestroyKillProc` and
`SetCooldown`. The ghidra MCP timed out on `TalentUse` and `TalentUseClass`,
so their bodies were not read. Calls through the script table or a method
value are invisible to the scan: a caller missing below is **not observed**.

- **A key cast.** `CheckTalentUse` (the gate: the key, the requirement, and
  the mana update after it, § 7.7) calls `TalentUse`, whose direct callers
  are `CheckTalentUse`, `MercenaryAbilities`, `skillsBasic` (two sites) and
  one unnamed function. `TalentUse` calls `TalentUseSetSpeed` (the wind-up:
  cast and attack speed, the `playerEffect` writes and `image_speed`, § 7.10),
  `SetCooldown` at one site, `NetworkSendClientTalentUse`, `TalentUseClass`
  at one site, `ReturnSpecificStat` 27 times and `GetTalentInfo` 11 times.
  **Measured** (§ 7.2): the player's own `TalentUseClass` call comes about 19
  frames after `TalentUse`; that delay is the cast time.
  `TalentUseSetSpeed`'s direct callers are `TalentUse` and
  `CA_playerTalentActive`.
- **`TalentUseClass`'s direct callers**: `enemyCollisionDamageParent` (two
  sites), `enemyCollisionProjectile`, `EnemyDestroyKillProc`,
  `EnemyKillAfterShock`, `EnemyKillCelestialCreation`, `PlayerTakeDamage`,
  `ProjectileCollision00Skills` (two), `SummonAttackScript` (two),
  `skillsBasic` (two), `CA_playerTalentActive`, `PlayerMovement`,
  `TalentUse`, `TalentUseClass` itself (two, the chained sub-skills of
  § 7.2) and 15 sites in unnamed functions.
- **`SetCooldown`'s direct callers**: `TalentUse` (one site),
  `TalentUseSetSpeed` (two), `TalentUseClass` (one),
  `enemyCollisionDamageParent` (two), `enemyCollisionProjectile`,
  `EnemyDestroyKillProc`, `CA_playerTalentActive`, `TalentsNomad` (two),
  `TalentsViking` and `TalentsRelics`. `GetTalentCooldown`'s:
  `TalentUseSetSpeed`, `TalentsRelics`, `DrawMobileTalentIcon`, the Create
  events of `Player_Talent_Tooltip_obj` and `UI_Hud_Talent_obj`, and one
  unnamed function.
- **The proc paths' shape.** In the hit and kill paths
  (`enemyCollisionDamageParent`, both sites, `enemyCollisionProjectile` and
  `EnemyDestroyKillProc`) a `SetCooldown` site comes just before the
  `TalentUseClass` site, and none of these functions calls `TalentUse`.
  `PlayerTakeDamage` (the struck path) calls `TalentUseClass` and has no
  direct `SetCooldown` site of its own; how it paces its proc was not read.
  So the game fires an item proc straight into `TalentUseClass`, and paces
  it with its own `SetCooldown` entry where it paces it at all.
- **What that skips**: the gate, so its key read, its requirement check and
  its mana update; `TalentUse`, so the wind-up and the cast speed that
  `TalentUseSetSpeed` applies; and the cooldown `TalentUse` and
  `TalentUseSetSpeed` set.
- **The kill proc's call** (`EnemyDestroyKillProc`, annotated): it first
  calls `SetCooldown` with five arguments (its own first two arguments, a
  value halved, and two more), then `TalentUseClass` with ten (the same two,
  the target's x and y, a direction, and a random number from 1 to 65000).
  Which argument is the talent and which the level was not read.
- **`SetCooldown`** keeps its entries in two lists in the game's protected
  data, `cooldownList` and `cooldownProcList`, one branch each. Which
  argument picks the list was not read.
- **The one measured case** (§ 7.2): the double-cast proc is a
  `TalentUseClass` call with `self` = `Universal_Double_Cast_obj`, a4
  false and a6, a7 a world x and y, with no `TalentUse` before it.
- **Not established:**
  - `TalentUseClass`'s arguments besides a0 and a4 to a7 (§ 7.2 recorded
    those of the player's call; a1 to a3 and anything after a7 were not
    recorded);
  - what `TalentUseClass`'s own `SetCooldown` site sets, and when it runs;
  - which level a proc casts at: whether it is passed in or read from the
    player's talents.
- **Measured 2026-10-22** (ForgePact's Mark 1 Stats live 1, slot 14
  "Sorak", White Mage, in town; `tgprobe hook TalentUseClass` with
  `tgprobe verbose on`, `skillprobe call`, and `mark1probe hook`'s
  `TalentUse` row as the count of key casts):
  - **The player's own call** on a key cast of Shadow Bolt (239) and of
    Healing Zone (252): self and other `Player_obj`, argc 10, a0 the talent
    id (a real), a1 a ref (kind 15) to the player's own instance, a2 1, a3
    false, a4 true, a5 0, a6 and a7 -1 (a8 and a9 were not printed). Inside
    it the game makes a second `TalentUseClass` call with a0 243 (an
    integer), a4 false and a5 55; what talent 243 is was not read. The
    double-cast proc's call in the same session read self
    `Universal_Double_Cast_obj`, a0 239 (or 252), a1 the player's ref, a4
    false, a5 0 or 43, a6 109.17 and a7 3.15, which is not the player's
    position (912, 960); what a6 and a7 are there is not established.
  - **Two call shapes cast both talents with `TalentUse` unmoved**, through
    `skillprobe call TalentUseClass Player_obj 0 … confirm` with argc 8:
    shape A, the player's own arguments as logged (a4 true, a6 and a7 -1),
    and shape B, the same with a4 false and a6, a7 the player's x and y.
    Each raised the skill's `effect=` count from 0 to 1 (Shadow Bolt's
    bolt, Healing Zone's zone in the screenshot) with no throw, while the
    `TalentUse` row stayed at 0: no wind-up. Shape A also made the nested
    243 call (and for Healing Zone a double-cast proc); shape B made
    neither.
  - **A direct call sets no cooldown the key respects.** Control: Healing
    Zone pressed twice 0.5 s apart cast once. After a shape-B call of
    Healing Zone, its key pressed within 1 s cast it again.
  - **The skill's strength is the same.** `White_Mage_Healing_Zone_obj`
    read after a key cast and after a direct call had `heal` 17,
    `augmentLevel` 0, `deadly` 1, `skillId` 252, `isProc` false and
    `tick_frequency` 144 in both; only `deltaTimer`, `destroyTimer`,
    `inviewCheck`, `trail_x` and `trail_y` differed. So with a2 at 1 the
    direct call casts at the player's strength; whether a2 is the level is
    still not read.
  - **A direct call is made regardless of held input.** With the right
    button held 8 s (its skill casting 16 times), Mark 1's direct calls
    kept being made and returning (16 in the window); with Mana Orb's key
    held 5 s under the automation's lockout too (13), and the key cast
    none. Those calls passed the player in a1 as a number rather than a
    ref, so they were counted as calls that returned, not as casts.
  - **A held cooldown skill's repeat**: Healing Zone's key held 30 s cast 3
    times over 31.25 s (10.42 s each, crude: window over casts) at Skill
    Haste 56 and Faster Cast Rate 106, against a cooldown of 14 / 1.28 =
    10.94 s and a cast time of about 0.49 s; closer to the longer of the two
    than to their sum (§ 7.10).
  [Mark 1 Stats live 1 results](../ForgePact/docs/mark1-set-research.md#stats-live-1-results)

[Mark 1 research, the 2026-10-22 playtest](../ForgePact/docs/mark1-set-research.md#the-2026-10-22-playtest-stats-cast-priority-and-held-input),
[Playtest static reading](../ForgePact/docs/mark1-set-research.md#playtest-static-reading)

### 7.10 The skill bar's buttons, mana and the cast's speed

Written for the same playtest's second amendment (2026-10-22): a skill under
Mark 1's automation cannot be cast by hand, its bar icon is drawn grey, each
proc fires at an interval computed from the skill's cooldown and cast speed,
and a mana cost counters the free procs. **Static reading** (2026-10-22, in
our own words) except where earlier sections measured it: the ghidra MCP's
decompiles of `PlayerManaUpdate`, `StatMaxMana`, `StatManaPerKill`,
`ManaPerHit`, `GetTalentCooldown`, `DrawHudAbilityButtons` and the talent
HUD's methods; one headless slot-reference scan (`FindSlotRefSites.java`) of
`drawButton`, `manualDisable` and `manaCost`; and long headless decompiles of
`UI_Talent_Button_obj`'s Draw GUI event, `StatManaReplenish` and
`TalentUseSetSpeed`. `TalentUse` and `DrawHud` timed out.

- **The bar's buttons.** `DrawHudAbilityButtons` draws no icon itself: it
  calls the talent HUD's `m_SetupTalentButtons` method and creates UI nodes.
  The elements of `UI_Hud_Talent_obj.row0` (whose `navBbox*` members
  ForgePact's Mark 1 border already reads) are `UI_Talent_Button_obj`
  instances: the slot scan found `drawButton` written and read only by the
  talent HUD's setup method and that object's Create and Draw GUI events.
- **The button's Draw GUI blend.** That event draws the icon sprite
  (`sprite_index`, `image_index`, at `x`, `y`, `image_xscale`,
  `image_yscale` and `image_angle`) with a blend colour that starts white.
  The blend is set to a dark grey, 3158064 (RGB 48,48,48), when the button's
  own `enabled` reads false or when `TalentRequirement` refuses the talent.
  So the game's own "cannot use" look is the icon drawn with that dark-grey
  blend. Three more blends are set in branches whose conditions were not
  fully read (they read the player's `pSt` and the game's protected data):
  9474192 (RGB 144,144,144), 9250839 and 138 (in GameMaker's colour order,
  red in the low byte: RGB 23,40,141 and RGB 138,0,0). The event also draws
  a cooldown sweep (`draw_rectangle_cd`).
- **The key the gate reads per column** is `inputState` of the profile
  entry, column c at entry c (Q 3, E 4, R 5, Y 6, **measured**, § 7.7
  `slot-keys`): 3 held, 4 pressed, 1 resting.
- **Where mana lives.** `PlayerManaUpdate` (the gate calls it, § 7.7) reads
  the player's `pSt` entries 17, 18 and 23 and gets and sets their values
  through the game's protected store (an extension's `GetVariable` and
  `SetVariable`). It compares the value it finds with the last entry of its
  100-sample `manaArray` history (`manaArrayPos` is that history's write
  position, § 7.8) and, on a mismatch, takes `debug_get_callstack` and can
  call `ReportClient` or `show_message_async`. So a mana value changed
  outside the game's own update is plausibly detected.
- **The dispatcher ids around mana** (`ReturnSpecificStat`'s case map, § 7.5):
  37 `StatMaxMana`, 42 `StatManaReplenish`, 46 `StatManaPerKill`, 147
  `ManaPerHit`, 340 `StatManaCost`, 103 `StatSpellHaste` and 106
  `StatFasterCastRate`. The item keys that feed them
  (`hs_stat_semantics_s10.json`, labels measured in Item Truth's captures):
  60 `to Mana`, 61 `Mana Increased by`, 63 `Replenish Mana`, 64 `Mana
  stolen per Hit`, 65 `Mana per second`, 66 `Mana After each Kill`, 167 `of
  Damage Taken Recouped as Mana`, 200 `Mana Costs decreased by`, 385 `Mana
  Regeneration Increased by`, and 38 and 39, Energy (4 mana a point).
- **`StatManaReplenish`** (partly read) asks the dispatcher for Energy
  (id 20) and scales it by 0.175, asks ids 43, 37 (maximum mana), 44 and
  309, multiplies 43's answer by 37's when 43's is above zero and floors the
  product, and adds the player's buff values. So the base replenish follows
  Energy, and maximum mana enters only through id 43's part. `StatMaxMana`
  is id 37's getter; its total is element 0 of the array it returns, as for
  the other getters (§ 7.5).
- **`TalentUseSetSpeed`, the cast's speed** (partly read): it takes the
  Faster Cast Rate answer (id 106) times 0.01, adds the talent's own
  sub-talent cast-speed bonuses (`LoadSubTalentDamage` times 0.01, from a
  24-case table by talent), and divides a per-talent base (from
  `GetTalentInfo`'s entry 66) by one plus that sum; ids 68 and 69 (attack
  speed) go into the same speed on another branch. So a cast's time has the
  shape base / (1 + Faster Cast Rate / 100).
- **When a key cast's cooldown starts** (same body): `TalentUseSetSpeed`
  reads `GetTalentCooldown` first and, for a cooldown above a small
  threshold, calls `SetCooldown` with that cooldown times `game_get_speed`
  (steps), at the start of the wind-up. So a held key's repeat of a
  cooldown skill is plausibly the longer of its cooldown and its cast time,
  not their sum. A talent's `abilityCooldown` of 0.25 means it has no
  cooldown (§ 7.1, **measured**); Skill Haste divides a running cooldown by
  1 + haste / 200, the total stopped at 200 (§ 7.5, **measured**), and
  `GetTalentCooldown` reads no Skill Haste (§ 7.5).
- **Measured 2026-10-22** (ForgePact's Mark 1 Stats live 1, slot 14
  "Sorak", White Mage, in town, at 2560 × 1440):
  - **A draw inside a bar slot from `DrawHudBuffs` does not show.** Icons
    redrawn darker, or a dark box drawn over them, from the `DrawHudBuffs`
    hook changed no slot's look: the slot boxes' mean luminance read the
    same with the redraw on and 18 s after it went off for Q (44.9 against
    46.2) and R (54.4 against 54.4), and E's and Y's darker reads were the
    game's own (E's cooldown, Y cast continuously). A red outline drawn
    from the same hook around the slots shows. Plausibly the
    `UI_Talent_Button_obj` nodes draw their icons after `DrawHudBuffs`, over
    anything drawn inside a slot (an inference).
  - **A button's `enabled` false draws the game's dark look.** Writing
    `enabled` false on the four automated columns' buttons drew Q, E, R and
    Y dark in the game's own "cannot use" look; the skill's tooltip still
    showed on hover, and a left click still opened the bar editor.
  - **A left click on a bar icon opens the skill-bar editor** and casts
    nothing: the bar shows the empty slots Y, U, I, O, H, J and K to the
    right of R and a skill list above the bar. A left click on open ground
    closes it; Escape does not. To bind, the slot, then the skill in the
    list (the owner bound Shadow Bolt to Y this way). A right click on an
    icon shows only the skill's tooltip.
  - **Mana refills fast.** Sorak's mana rose from 983 to 2352, its
    maximum, within 10 s (at least 137 a second) with id 42's original at
    415, and five key casts of Shadow Bolt 2 s apart left the HUD at
    2352 / 2352 before and after: with Mana Orb on the bar (the owner: it
    raises mana regen) the HUD showed no key cast's cost. The unit of id
    42's answer is still not established.
  - **The HUD's maximum mana follows id 37's dispatcher answer.** With
    Mark 1 answering id 37 with 0.4 × its original (2352 to 940.8), the
    HUD read 941 / 940.80 within 3 s.
  - **How often the game reads mana** (debugger logpoints at each
    function's own address, with a positive control on `PlayerMovement`
    logging about 73 a second): `StatManaReplenish` none in a 10.26 s idle
    and 20 over five key casts in 14.7 s; `StatMaxMana` 11 in the idle and
    14 over the casts; `PlayerManaUpdate` none in the idle and 25 over the
    casts. Mana was not read during that idle and was plausibly at its
    maximum, so the idle zeros do not say whether the regen calls them
    while mana is below it; which code applies the regen is still not
    established.
  - **The held right button's input**: `inputState` entries 2, 27 and 40
    of the profile read 4 for one frame, then 3 for as long as it was held.
  - **A held key's repeat and the cast's speed**: Shadow Bolt's key held
    10 s cast 24 times at Faster Cast Rate 106 (about 62 gate frames
    between casts, 417 ms) and 30 times with 100 more Faster Cast Rate
    added (333 ms). Base = interval × (1 + FCR / 100) gives 0.858 s and
    0.973 s, 13.4% apart, with the second FCR read as 192 (the cached
    read, which drifted between 54 and 106 over the session); the shape
    base / (1 + FCR / 100) holds only that loosely.
  [Mark 1 Stats live 1 results](../ForgePact/docs/mark1-set-research.md#stats-live-1-results)
- **Static reading (2026-10-23): the player's mana regen tick.** From the
  ghidra MCP's decompiles of `playerUpdateTimerMana`, `PlayerRegenSet`,
  `SetRoomSpeed` and `stepMercenaryTimers`, a headless decompile of
  `PlayerUpdateTimers` and `Timer_obj`'s Step, local byte scans (positive
  controls: id 64's askers as § 7.8 lists them, and `CheckTalentUse` called
  from `PlayerMovement`) and a names-only trace of `Player_obj`'s Step; in
  our own words:
  - **The regen is `playerUpdateTimerMana`**, called once, directly, from
    `Player_obj`'s Step (the only direct caller found). `PlayerUpdateTimers`
    does not regenerate: its one `PlayerManaUpdate` call is the clamp that
    puts current mana back to the maximum. For the local player only, the
    tick reads two `pSt` entries as gates (their meaning not read),
    compares current mana (`pSt` 18) with the maximum (17) and, while mana
    is below it, asks the dispatcher for id 42, divides the answer by the
    tick's second argument, rounds the quotient up and adds the result
    through `PlayerManaUpdate`. Life works the same way in
    `playerUpdateTimerLife` with id 38. The tick loads 42 as a plain integer
    constant, which the earlier constant-id scan (address-loaded constants
    only) could not see; that scan's "only `stepMercenaryTimers` asks 42"
    was a scan blindness, not an absence.
  - **What the Step passes is not established.** Just before each tick
    call it reads a `pSt` entry, asks the dispatcher for id 44 (mana) or 41
    (life), neither of which has a case in the dispatcher's table, and reads
    `game_get_speed` twice; how those become the tick's timing and divisor
    was not read (a long decompile of the Step did not finish).
  - **The mercenary's version**, `stepMercenaryTimers`, counts a `pSt`
    timer down by the mercenary's own `deltaFrame` each step, adds the
    rounded-up answers to 38 and 42 when it runs out, and resets the timer
    from `game_get_speed`. The local slot scan (RIP-relative references
    only, the kind that missed id 42 above) and the names-only trace of
    `Player_obj`'s Step did not show a `deltaFrame` slot; whether the
    player's timing reads one is not established.
  - **The game's step rate.** `SetRoomSpeed` reads the video FPS option
    (protected data entry 76) and sets `game_set_speed` to 60, 120 or 144
    (options 0, 1, 2; 60 otherwise). GameMaker runs one step per drawn
    frame (engine behaviour, not read from this binary; consistent with
    Live 3's measured rate below), so the step rate is the frame rate,
    capped at that setting.
    `Timer_obj`'s Step keeps a real-time factor, the frame's `delta_time`
    over the target frame time, clamped to 0.9 .. 4.0 and stored in the
    protected data (entry 294); the player's tick and `PlayerUpdateTimers`
    were not seen to read it (not established: the Step itself was not
    read).
- **Measured, Stats live 3 (2026-10-23), from the in-process `vitals`
  lines' `frame=` and `dt=`:** the game ran about 143 frames a second (S7
  180 frames in 1258 ms, S8 180 in 1259 ms, S9 600 in 4173 ms), the 144
  setting. The "about 78" once inferred from the debugger control's 777
  `PlayerMovement` hits in 10 s is therefore not once a frame (or the
  logpoints slowed the game; not established which).
- **Inferred from those windows' measured gains:** each is a whole number
  of ticks of the answer over ten, rounded up: S7 (answer 140) gained
  154 = 11 × 14, S8 (answer 92.96) gained 110 = 11 × 10, S9 (answer −140)
  lost 518 = 37 × 14. The gains alone also fit a divisor of 20
  (154 = 22 × 7, 110 = 22 × 5, 518 = 74 × 7); the mod's own count of id 42
  asks it answered (`forced=`) excludes that: it rose 133 to 223 and 223 to
  323 over the two 10 s switch-off spends, about 9 asks a second, one per
  tick at about 8.8 ticks a second, not the 17.5 a divisor of 20 would
  need. So at the 144 setting the divisor is 10 and a tick came every 16.2
  to 16.4 frames, about 8.7 to 8.9 ticks a second.
- **The replenish readings side by side.** Read as mana a second per unit
  of the whole answer, S7 gives 0.874 (§ 16.13). Read on the drain side,
  S7 minus S8 gives 35.05 mana a second over 47.04 drained units, 0.745 a
  drained unit, the value ForgePact's `kMark1ReplenishUnit` adopts. The two
  disagree, and the inference is that the rounding up per tick, not the
  unit, explains the gap: the drain took 14 − 10 = 4 whole mana a tick
  where 4.70 was asked. At the shipped 0.745 (answer 140, maximum 2352, two
  proc columns, 63.14 drained) each tick would take 14 − 8 = 6 mana, about
  1.12% of maximum mana a second per skill (measured in Stats live 5,
  below). One mana a tick is about 0.19% of that maximum a second per
  column, so the drain moves in steps of that size.
  [Regen and the frame rate](../ForgePact/docs/mark1-set-research.md#regen-and-the-frame-rate-static-reading)
- **Measured, Stats live 5 (2026-10-23), in process (`vitals` windows,
  the replenish forced to 1 for the tick counts, every other regen source
  off the bar), on one character (maximum mana 2352, answer 140):**
  - **The tick's rate at each frame rate.** At about 143.7 frames a second
    (VSync off; the Video page's Framerate row drawn disabled and showing
    60 throughout, the game's own counter at 143 to 144): 219 ticks in
    25.007 s, 8.76 a second, a tick every 16.4 frames. At 59.9 frames a
    second (VSync on): 225 ticks in 30.008 s, 7.50 a second, a tick every
    8.0 frames. The tick rate fell to 0.856 of the higher rate while the
    frame rate fell to 0.417, so the tick is neither a fixed frame count
    (which predicts about 0.42) nor held at the same rate a second within
    10% (which predicts 0.9 to 1.1). Which `game_get_speed` value was in
    force at each rate was not read, since the setting row showed 60 in
    both. With the logpoints armed at the higher setting the game slowed
    to about 60.5 frames a second and ticked 7.66 a second, a tick every
    7.9 frames, close to the 60 FPS window (inferred: the tick follows the
    frame rate the game reaches, not only its setting).
  - **The per-tick amount is the answer over ten, rounded up, at both
    rates.** Every window's gain was a whole number of ticks of
    ceil(answer / 10): answer 140 gave 14 a tick (308 and 630 = 45 × 14),
    answer 76.86 (the drain on) gave 8 a tick (176 and 360 = 45 × 8); the
    divisor stayed 10 at 60 frames a second (VSync on; the setting row
    unchanged).
  - **What the logpoints counted.** The entries of `playerUpdateTimerMana`
    and `StatManaReplenish` were each hit once per tick, within 5% of each
    window's ticks (from its gain), and far fewer times than frames (0.12
    to 0.14 a frame), in both debugger windows, which both ran at about 60
    frames a second (57.1 and 60.5; the logpoints slowed the 144 setting),
    so the entries were not counted at 144. The tick script runs only when
    a tick is due, and `StatManaReplenish` (the replenish getter) is
    entered once a tick. Counted against each window's ticks from its
    gain; `dbg-tick` and `dbg-replenish` failed their rule in D1, whose
    ticks S3's rate overpredicted. Mana gained per hit read 13.3 to 14.8
    against 14 a tick.
  - **Mark 1's drain.** At the shipped unit 0.745 with two proc columns
    each tick took 14 − 8 = 6 mana: 1.117% of maximum mana a second per
    skill at about 144 frames a second (±0.005) and 0.956% at 60, both
    inside the owner's 0.95% to 1.15% band.
  [Stats live 5 results](../ForgePact/docs/mark1-set-research.md#stats-live-5-results)
- **Not established:**
  - how the player's tick is timed: Stats live 5 measured 8.76 ticks a
    second at about 144 frames a second and 7.50 at 60, which fits neither
    a fixed frame count nor a clock-held rate; the mechanism (the Step's
    argument and what it reads) was not read;
  - what the Video page's disabled Framerate row means, and which
    `game_get_speed` value the game runs with while it is disabled;
  - whether the tick's divisor depends on the FPS setting: Stats live 5
    read 10 at about 144 and at 60 frames a second, but the 60 was reached
    with VSync on while the Framerate row showed 60, disabled, in every
    window and `game_get_speed` was not read, so the setting itself may
    not have changed between them;
  - what the other three blends mean (plausibly mana, cooldown or stacks);
  - who else writes a button's `enabled`, and what else it changes besides
    the look (the tooltip and the left click were unchanged, measured
    above; navigation not read);
  - whether id 43's part is a share of the mana pool;
  - a talent's base cast time, and its sub-talent bonus;
  - whether `GetTalentCooldown`'s base differs from `abilityCooldown` (sub
    talents);
  - where current mana can be read from outside the protected store;
  - any path that casts a bar skill without the gate's key read (a gamepad,
    `abilityQueue`, `mobileTalentPressed`); a left click on the HUD icon
    is not one (it opens the bar editor, measured above).

[Mark 1 research, the 2026-10-22 playtest](../ForgePact/docs/mark1-set-research.md#the-2026-10-22-playtest-stats-cast-priority-and-held-input),
[Playtest static reading](../ForgePact/docs/mark1-set-research.md#playtest-static-reading)

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

**A node's place members, and the box it is highlighted by** (ForgePact #68 /
#131; the owner's report of 2026-10-08):

- **Three members hold an absolute GUI position. Measured** (Live 5 and 6,
  2026-09-30). On a `UI_Button_Small_obj`, `createX`, `navBboxX` and
  `navBboxY` are absolute GUI coordinates: on the bag's `InventorySort` they
  are its own box's top-left corner (2290, 1262 at 2560×1440); on a node made
  by `UiCreateNode` they are the corner of its box as first made (1988, 1238
  for ForgePact's Move All node under its original sprite), and they are not
  updated when the node's sprite or scale is changed afterwards.
  `navBboxWidth`/`navBboxHeight` hold the box's size (192×66 on Sort). So a
  copy of these members from one node onto another carries the first node's
  place, not its look. A node's `bbox_*` follow its drawn sprite instead.
  Detail: § "Moving an item from the bag into the stash" below.
- **`navBbox*` is the box the game hovers and highlights. Measured**
  (2026-10-08, two sessions; ForgePact `stash-move-research.md` § Live 8
  results and § Live 9 results). With ForgePact's Move All node carrying
  `createX`/`navBboxX`/`navBboxY` displaced onto its own box and
  `navBboxWidth`/`navBboxHeight` its own size, hovering InventorySort flips
  five of Sort's members (`image_index` 0 to 1, `inFocus`, `mouseHover` and
  `stopAnimation` false to true, `mouseHoverSound` true to false: the
  instrument's positive control), hovering the node's drawn box flips the
  same five on the node the same way, and the mouse over Sort flips none of
  the node's. Measured at 2560×1440 fullscreen (GUI 2560×1440) and at
  1920×1080 windowed (a 1920×1090 client, GUI 2560×1368 in town as on the
  main menu); fullscreen 1920×1080 and other GUI scales not observed.
  Not separated: `createX` and `navBboxX` were moved together, so which of
  the two the game takes the box's left edge from; and in both sessions the
  node sat level with Sort at Sort's size (displacement 0 in y, scale 1), so
  only the x displacement was exercised. Before those sessions it was a
  static reading,
  on this support: the name; on the hotbar a `row0` slot's
  `navBbox*` is the rectangle sitting on its button (§ 8.3); and the owner's
  report that ForgePact's Move All button, which then carried Sort's
  `navBboxX`/`navBboxY` while drawn one Sort width to Sort's left, lit only
  with the mouse to its right, over Sort, while a click on the drawn button
  still worked (ForgePact's own press poll tests the node's `bbox_*`). The
  game's GUI mouse helpers (`mouse_in_gui`, `mouse_in_check_gui`,
  `ui_cursor_in_gui`, bound by `MouseGuiFuncs`) each test a device-to-GUI
  point against a box they are handed, but every member read on that path
  goes through a variable slot this build leaves unnamed, so which member
  supplies the box was not settled by reading; the two sessions above
  measured it (`node-hover`, `node-hover-win`).
- **What a mod that copies a node's look should do with them**, as ForgePact
  does since 2026-10-08: write `createX`, `navBboxX` and `navBboxY` as the
  source node's value displaced by the target box's offset from the source's
  box, and `navBboxWidth`/`navBboxHeight` scaled by the target's size over
  the source's, so the source's own relation between those members and its
  box is kept rather than assumed.

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
- **The save files count from 0: card `slot` N loads `herosiege<N-1>.hss`**
  (and `inventory_order_<N-1>.hss`), so `hs_select_character` slot 14 is
  `herosiege13.hss`. **Measured** by hs-drive's rows M-L2 and M-L2b on
  2026-09-21 (slot 1 changed `herosiege0.hss`, slot 2 `herosiege1.hss`;
  `docs/tools/hs-drive-mcp.md`, Verification), and again by Live procedure 1
  of `forgepact-185-tracker-move` (2026-10-13): slot 14 loaded Sorak, file 13
  reads Sorak and file 14 another character, and after the session
  `herosiege13.hss` and `inventory_order_13.hss` had changed. A tool that
  takes a save file's number (ForgePact's `tools/tracker_replay.py --save`)
  takes N-1, not the card's slot.

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

**The pause menu's Exit (measured 2026-10-13, ForgePact #201, where the
sessions reached; the script behind it is a static reading).** An injected
Escape (hs-drive's `hs_exit_to_menu`, VK 27 through `SendInput`) opens the
pause menu in `Town_01_rm`. Its Exit is a `UI_Button_obj` whose text reads
"Save & Exit" and whose `uiNodeCallstack` is `"PauseSaveExit"`, listed by
`menulayout` at `win=1280,856` on a 2560x1440 fullscreen client. One click
there takes the game to `Chose_rm` (the character select) with no
confirmation in between; it does not end the game. Both the character file
`herosiege13.hss` and the bag file `inventory_order_13.hss` are rewritten by
it, within a second of each other. Measured twice, once per session (Live 1
cell C, Live 2 cell G), each on the first call (#201's Live procedure 1, capture
`forgepact-201-exit-c0000409-live-1`, and Live procedure 2, capture
`forgepact-201-exit-c0000409-live-2`, local to the hub's workorder folder).
**Static reading** (2026-10-13): `UiAIngameExit` is named beside
`UiAIngameRestart` among the pause menu's activations and is read as this
button's. It saves through `SaveLocalFile` (six call sites; which file kinds
they ask for was not read), calls `DisableEnemyStep`, and then goes to room
150, which `hs-game-sdk` names `Chose_rm`. That the click runs
`UiAIngameExit` was not measured; the room and the two rewritten files fit it.
[graceful stop research, Results](../ForgePact/docs/graceful-stop-exit-research.md#results)

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
  (count-only hooks on both, same session). `ChatAddMessage` called directly
  with another sender does show a line without the `SERVER:` prefix:
  **measured** in the dungeon chest's Live procedure 1b (shape 8; see
  this section's last bullet).
- **How `ChatAddMessage` builds a line** (ForgePact#228). **Static reading**
  (2026-10-23, local Ghidra project, our own words). Its fifteen parameters,
  in order: sender name, text, sender colour, text colour, message type,
  channel, account id, language, time stamp, character slot, DLC bitmap,
  platform, platform id, platform name, region. An omitted text colour
  defaults to 11974842 (#BAB8B6, the game's grey chat text). It builds one
  `s_ChatMessageData` (fields `name`, `msgNameColor` from the sender colour,
  `messageColor` from the text colour, `messageType`, `channelType`,
  `timestamp`, `language`, `commandList`, `msgItemData`, and more), adds it to
  every `UI_Chat_List_obj` list of its channel (except a message type 3 line
  while the player's `chatShowItemDropMessages` option is off), and adds it to
  the bottom-left in-game feed (`IngameChatFeedAddLatest`) only when the
  channel is -1 or the `enableGeneralChat` option is on.
- **How a chat line is drawn: two text colours, no inline markup**
  (ForgePact#228). **Static reading**, same session. The message's update
  pass turns emoji codes in the text (`chatEmojiMap`) into image commands,
  and a text that starts with an item link (item data encoded in the text)
  into `msgItemData`, whose `GetItemColor` then becomes the text colour and
  whose tooltip shows on hover. `DrawChatMessage` (an `s_ChatMessageData`
  method, SDK name
  `gml_Script_DrawChatMessage@anon@13887@s_ChatMessageData@DefineChatMessageData`,
  whose anon number moves per patch, § 5.3) draws, each with a black shadow:
  the time stamp in 8421504 (#808080), the sender in `msgNameColor`, platform
  badges, a separator in 7844807 (#C7B377), then the text one character at a
  time in `messageColor`, with emoji images between characters. When
  `msgNameColor` is exactly 6776816 (#F06767) the text is drawn in the
  default grey instead. Nothing in the text can change its colour, so a line
  carries exactly two text colours: one for the sender part, one for the
  text part. **Measured** 2026-10-23 (capture
  `forgepact-228-loot-colors-live-1`, ForgePact#228's Live 1, research
  build, slot 14 "Sorak", Town of Inoya; pixels sampled on full-resolution
  screenshots of the bottom-left feed): three `ChatAddMessage` lines, each
  with sender colour 11974842 and a different text colour, drew the sender
  part in (186,184,182), which is 11974842 (#BAB8B6) exactly, and the text
  part in exactly the text colour passed (details in this section's last
  bullet), so on the feed the sender and the text each carry their own
  colour. **Measured** 2026-10-23 again (capture
  `forgepact-228-loot-colors-live-2`, ForgePact#228's Live 2, same
  character and place): three lines with sender colour 18687 drew the
  sender in (255,72,0), which is 18687 (#FF4800) exactly, and on a message
  type 0 line the separator straight after the sender is a colon and a
  space, `: `, in (199,179,119), which is 7844807 (#C7B377) exactly, the
  colour the reading gives it; the feed read `[hh:mm] Sorak: found <item>`.
  The time stamp sampled (128,128,128), 8421504 (#808080), on that
  session's red control line and its Heroic line, which is the stamp colour
  the reading gives. That nothing inside the text can change its colour and
  the 6776816 rule stay a static reading (neither was exercised). **Not
  established**: that the bottom-left feed draws through `DrawChatMessage`
  (inference: the measured feed lines show a stamp, a sender, a separator
  and a text in exactly the colours the reading gives), and what a click
  on a sender name in the opened chat window does offline.
- **`ChatAddServerMessage(text, channel)` cannot carry a colour.** **Static
  reading** (ForgePact#228): it passes the sender (measured `"SERVER"`), red
  255 (#FF0000) as both the sender and the text colour, message type 1 and the
  channel (default 0). That is why its line is red throughout.
- **The online announcement's colours** (ForgePact#228). **Static reading**:
  the ground item's closure calls `NetworkSendChatMessageIngame` with 18687
  and a colour, and that sender passes 18687 (#FF4800, orange) as the sender
  colour, the colour as the text colour, and message type 3; the sender name
  comes from a protected-store read (which value is not established). The
  text colour per rarity: Heroic (`"27"` 9) `GetRarityColor(9)` = 9764608
  (#00FF94); Angelic (`"27"` 7, or tier `"32"` 6) a fixed 10681599
  (#FFFCA2, pale yellow; the rarity table's Angelic is 10092542, § 16.4);
  Unholy (`"27"` 10) a fixed 7224024 (#D83A6E), the same as
  `GetRarityColor(10)`; a Satanic item (`"27"` 6) of tier `"32"` 5 (SS) takes
  the Heroic branch with `GetRarityColor(6)` = 1447638 (#D61616). With type 3
  the text is `GetItemDropMessage`'s: a `[Softcore] ` or `[Hardcore] ` tag,
  the finder's name, the localized `just_found` phrase and the item's loot
  name in square brackets, all in that one text colour. So online colours the
  whole text, not only the item name. That 18687 draws the sender part
  orange (255,72,0) on the feed is **measured** (capture
  `forgepact-228-loot-colors-live-2`, ForgePact's own `ChatAddMessage` line,
  below); that the online path passes it, and these text colours, stays a
  static reading.
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
  announcements switch (`lootann`) shipped this route for Heroic, Angelic and
  Unholy items until ForgePact#228 made it the fallback of the coloured
  route below; in Live procedure 3 it announced placed items, held a
  Satanic one, held a bag drop, and announced one natural drop with Magic
  Find raised.
- **A coloured drop announcement: `ChatAddMessage` with its own sender and
  colours** (ForgePact#228). **Measured** (dungeon chest Live procedure 1b,
  shape 8): `ChatAddMessage` called by name with the local `Player_obj` as
  `self`, sender `"ForgePact"`, both colours 0, message type and channel int64
  0, two reals 0, a `[hh:mm]` stamp and six `undefined` showed
  `[00:49] ForgePact : ForgePact chat test 8`; the line's colour was not
  recorded. ForgePact#228 moves Loot announcements to this route
  (`chatcolour`) in the online announcement's layout: sender part the
  character's name in the online sender colour 18687 (#FF4800, orange),
  text part `found <item name>` in the online announcement's colour for its
  rarity (9764608, 10681599 or 7224024), with the red `SERVER:` line as its
  fallback. **Measured** 2026-10-23 in two sessions. The first build, an
  earlier layout with the grey `<character> found` as the sender (capture
  `forgepact-228-loot-colors-live-1`, ForgePact#228's Live 1; research
  build sha256 `e053249d…0d77151`, slot 14 "Sorak", Town of Inoya): with
  `self` the local `Player_obj`, sender `"Sorak found"`, sender colour
  11974842 as a real, the item name as the text and its rarity's colour as
  a real, type and channel int64 0, a placed Heroic, Angelic and Unholy
  item each showed `[hh:mm] Sorak found: <item name>` on the feed with no
  `SERVER:` prefix. Pixels on the full-resolution screenshot: the sender
  part (186,184,182) on all three lines; the item name (0,255,148) for
  Heroic (9764608, #00FF94), (255,252,162) for Angelic (10681599, #FFFCA2,
  pale yellow, plainly apart from the grey) and (216,58,110) for Unholy
  (7224024, #D83A6E), each exactly the colour passed. The same placed
  items' ground labels showed the same hue, darker (about 0.85 of the chat
  value per channel: (0,217,126), (216,217,130), (184,49,94)). A placed
  Satanic item and a Heroic item placed with the switch off showed no line.
  The layout that ships (capture `forgepact-228-loot-colors-live-2`,
  ForgePact#228's Live 2; research build sha256 `f87496ed…aaf14d28` at
  ForgePact `8bbeaa0`, same character and place): the same call with sender
  `"Sorak"`, sender colour 18687 as a real and the text `found <item name>`
  in its rarity's colour; a placed Heroic, Angelic and Unholy item each
  showed `[hh:mm] Sorak: found <item name>` with no `SERVER:` prefix (for
  example `[22:51] Sorak: found Cobra Heavy Belt`). Pixels: `Sorak`
  (255,72,0) = 18687 on all three lines, the separator `: ` (199,179,119) =
  7844807, and `found <item name>` exactly the colour passed, `found`
  included: (0,255,148), (255,252,162) and (216,58,110). `layout: online`.
  A placed Satanic item and a Heroic item placed with the switch off again
  showed no line. **Not observed live**: the fallback to the red line (no
  call refused in either session), natural drops on this route, the line
  with `enableGeneralChat` off, and co-op.

[dungeon chest, Chat route](../ForgePact/docs/dungeon-chest-research.md#chat-route),
[loot announcements, Static reading](../ForgePact/docs/loot-announcement-research.md#static-reading),
[loot announcements, Live procedure 3](../ForgePact/docs/loot-announcement-research.md#live-procedure-3),
[loot announcements, #228 Session results 2](../ForgePact/docs/loot-announcement-research.md#session-results-2)

### 8.7 Numbers on screen: the game's number formatters

Everything in this section is a **static reading** (ForgePact #230,
2026-10-20) of game build 7.0.13.0: `Hero_Siege.exe` sha256
`dab03f134327d9b682c67f1dc461822fb822a7e535009636624bb1454f498e2b`, and the
Steam extension `bin\PAS_Steam_GMS_x64.dll` (127,488 bytes) sha256
`c789ee5e5850e0d68c42a6d0b84876509eaea4f2ffab1ea9c35e71709c47b88f`, except
the paragraphs "Live 1" and "Live 2" and the claims marked measured, which
are measured. Live 1 did not reach the shortener; Live 2 (capture
`forgepact-230-damage-crash-live-2`, 2026-10-20) did. What it measured on
the positive side is one pass and one end: 9.9999e13 passed, and the game
ended after a value of at least 1.025e14 was handed in. The trace writes
only the first value of each decade, so the fatal value lies somewhere in
[1.025e14, 1e15) and is not itself known; the upper edge is not measured.
That the limit is exactly 1e14 is the static reading. It also recorded the crash's dump. The rest of the
positive band, the NaN and negative bands, the 32-bit overflow and the
8-character texts are still static readings. The shortener's arithmetic,
band by band, is written
up as a spec in [`docs/models/number-compress-spec.md`](models/number-compress-spec.md)
and modelled in `hs-game-sdk` from it.

**Three formatter scripts and a binder** (static reading):

- `num_compressFunc` binds the script file's two shorteners: it stores
  `num_compressGML` and `num_compressSteam` as global method values.
- `num_compressGML` (SDK index 2607) shortens in GML: below 10,000 it is the
  plain `string()` of the value, above that a suffix chosen by magnitude, and
  from 1e9 up it always divides by 1e9. It writes into no fixed buffer.
- `num_compressSteam` (SDK `gml_Script_num_compressSteam`, 2608) takes one
  argument and returns the text that the Steam extension's
  `SteamCompressNumber` export builds, called through the runtime's
  extension-call helper. The extension's id is referenced once in the exe's
  code, inside `num_compressSteam`. Neither shortener script, nor the two
  globals the binder stores them in, is called or read anywhere else in the
  exe's code (byte scan for direct calls and references), so whatever reaches
  `num_compressSteam` does so through a method value, and only an inline
  detour at the function's own address sees those calls (§ 5.1). Whether
  anything else in the game calls the extension function is not established.
- `RealFormat` (3250) inserts thousands separators, built from the runner's
  string builtins (`string`, `string_format`, `string_pos`, `string_insert`
  and others) and `floor`; 42 direct call sites. How it behaves for very large
  values (that is, how the runner's `string_format` does) is not established
  statically; Live 1 below measured the DPS meter's use of it.

**Every caller goes through the global `num_compress`** (static reading, a
byte scan of the exe for references to the global, since the Ghidra
project's caller and reference tables come back empty here, which is "not
observed"):

- `DefineGlobals` sets it up. The game code that reads it is
  `DrawEnemyHealthBars`, `DrawHudCoop`, `DrawHudMobile`, a closure of
  `Combat_Text_obj`, a closure of `DPS_Meter_obj`, and code belonging to
  `Player_Death_Sequence_obj`, `Player_Talent_Tooltip_obj`, `Quest_Text_obj`
  (`m_UpdateQuestRewards`), `UI_Button_Cost_obj` and `UI_Steam_Cloud_obj`.
  Code is attributed to the nearest preceding named symbol, and the symbol
  table names closures sparsely, so "code belonging to" an object is as
  precise as this reading gets.
- **Which script `num_compress` holds on the Steam PC build: `num_compressSteam`**
  (**measured**, Live 2, 2026-10-20, build 7.0.13.0). With the floating damage
  numbers drawn and compressed, debugger logging breakpoints in one 20 s
  window logged 748 calls into `num_compressSteam` and 748 into
  `SteamCompressNumber`, while `num_compressGML` logged none beside a control
  that logged 322 (a zero with the control logging; its first bytes were
  checked). No logpoint was set on `PS5_NumCompressGMLWrapper`. No write to
  the global was found outside `DefineGlobals` (static reading).

**Three display options decide whether a hit's floating number or the DPS
meter's total reaches it** (static reading). The other readers listed above
(`DrawEnemyHealthBars`, `DrawHudCoop`, `DrawHudMobile`, `Quest_Text_obj`,
`UI_Button_Cost_obj`, `Player_Talent_Tooltip_obj`,
`Player_Death_Sequence_obj`, `UI_Steam_Cloud_obj`) are not gated by these
options: none of them is among the code found to read any of the three, so
they can reach `num_compress` whatever the options say (static reading):

- `showDamage`: read by `enemyCollisionDamageParent`,
  `enemyCollisionProjectile`, `sc_hurt` and the `Combat_Text_obj` closure.
  The floating damage number for a hit on an enemy is created only while it
  is on.
- `combatTextCompress`: the `Combat_Text_obj` closure (which also reads
  `textValue`, `textText`, `textCritSize` and calls the builtin `string`)
  formats the number through `num_compress` only while it is on. What it
  draws with the option off is not established.
- `dpsMeterCompress`: the DPS meter's draw code (`DPS_Meter_obj`, 1357)
  formats through `num_compress` while it is on and through `RealFormat`
  otherwise. `UiADpsMeterCompress`, behind the meter's dropdown, flips it.
- `SaveLocalSettings` writes all three and `OptionsReset` resets them; the
  Gameplay options screen (`UI_Options_Gameplay_obj`) reads `showDamage` and
  `combatTextCompress`. On disk they are the keys `show_damage`,
  `combat_text_compress` and `dps_meter_compress` in the `[settings]`
  section of the save directory's `shop.ini`
  (`%LOCALAPPDATA%\Hero_Siege\hs2saves\shop.ini`; the key strings are in the
  exe, and the file was read on a player's machine). The game applies the
  file at start (**measured**, Live 2): with `show_damage` set to 1 in the file
  while the game was closed, the next launch drew floating damage numbers over
  the training dummies, which Live 1 with 0 never did, and with
  `combat_text_compress` 1 they were shortened (`970,4K`, `1,2M`, `394,6M`,
  `1296,2B`).

**`SteamCompressNumber`: one double in, a pointer to an 8-byte static text
out** (static reading of the DLL's export):

- It clears the 8-byte buffer first. Zero gives the constant text `0`.
- A negative value is never shortened: the whole part of its magnitude,
  converted to a 32-bit integer, is written after a minus sign.
- A positive value below 10,000 is written whole. From 10,000 to below 1e6
  it is truncated to hundreds (q = trunc(x / 100)) and shown as thousands
  with one decimal digit and `K`; below 1e9, q = trunc(x / 1e5) with `M`;
  from 1e9 up, and for NaN (which fails every comparison), q = trunc(x / 1e8)
  with `B`. The decimal digit follows a comma and is left out when it is 0
  (`12,3K`, `10K`). q is converted to a 32-bit integer.
- Every write into the buffer carries the compiler's range check. A failed
  check calls the C runtime's range-check failure, a fast fail with code 8
  (`FAST_FAIL_RANGE_CHECK_FAILURE`), and the process ends with exit code
  `0xC0000409`.
- **The failure bands.** The text does not fit, and the game ends, exactly
  when: the value is NaN; the value is positive and q has seven or more
  digits, that is x ≥ 1e14 (past about 2.1e17 the 32-bit conversion
  overflows to its minimum, a ten-digit negative, which fails the same way,
  and so does +inf); or the value is negative and the whole part of its
  magnitude has seven or more digits, that is x ≤ −1e6 (seven digits plus
  the sign; −inf overflows the same way). Every other value fits. What is
  **measured** of the positive edge (Live 2, below) is its passing side:
  99,999,000,000,000 (9.9999e13) passed 29,990 times. On the other side,
  the game ended after a value of at least 1.025e14 was handed in. The
  trace writes only the first value of each new decade, and about 1.025e14
  was the first of its decade, so later values in [1.025e14, 1e15) went in
  untraced and the fatal value is only known to lie in that range. That is
  not a measured upper edge; that the edge is exactly 1e14 is the static
  reading above. The band above
  that edge, the NaN and negative bands and the 32-bit overflow are not
  observed (no such value ran uncapped).
- **The terminator.** A shortened text is digits(q) + 2 characters with a
  nonzero decimal and digits(q) characters with a zero one; the cleared byte
  after it ends the string. For a six-digit q whose last digit is not 0
  (about 1e13 to 1e14) the text fills all 8 bytes and has no terminator
  inside the buffer; what the game then reads past it is not established.
  Whole-number texts that do not fail always end inside the buffer.

**Why no plugin handler sees it.** A fast fail ends the process from the
kernel without dispatching an exception inside it, so a plugin's vectored
handler, its top-level filter (§ 5.11) and any `ExitProcess`-time code never
run: the crash bundle names no faulting module and the trap records nothing,
which is what the two #230 reports of 2026-10-20 show (measured from their
bundles). Windows Error Reporting still writes a dump when the error mode
allows it, and the dump names the code, the subcode and the module that
raised it (**measured**, Live 2: the dump of the run that ended reads
`code=0xc0000409 subcode=8 raised-in=PAS_Steam_GMS_x64`, with
`SteamCompressNumber` on its stack); an attached debugger takes the fast fail
instead and no dump is written (not measured here; Live 2 detached its
debugger before the crash). The shortener fails for such a number with or
without a mod; whether
an unmodded character can put 1e14 on screen is not known.

**`CombatText` and the floating number** (static reading, extends § 12):
`CombatText` creates a `Combat_Text_obj` with `instance_create_layer` and
sets `textText`, `textValue`, `textColor`, `textSize`, `setDestroy` and an
alarm on it. None of `CombatText`'s 28 direct call sites falls in the
enemy-collision code, so whether a hit's number goes through `CombatText` or
creates the object itself is not established; the formatting happens in
`Combat_Text_obj` either way, through `num_compress` while
`combatTextCompress` is on (above). A DPS meter sums hits over time and over
projectiles, so its total would cross 1e14 well before a single hit does
(not measured). ForgePact's `stat` on `CalculateEndDamage` scales the final
per-hit damage (measured earlier), which is how its Modifiers reach these
numbers.

**Live 1** (measured, ForgePact #230, 2026-10-20, capture
`forgepact-230-damage-crash-live-1`; a research build, the Act 1 town with
training dummies, the Modifiers ramped from x11 to x1e12): the player's
`shop.ini` had `show_damage` 0 and `dps_meter_compress` 0
(`combat_text_compress` 1).

- No floating damage number was drawn at any multiplier.
- Debugger logging breakpoints on `num_compressSteam` and
  `SteamCompressNumber` logged no call all session, while a control
  breakpoint in the same session logged 792 hits and one on `RealFormat` 820
  in a 20 s window. ForgePact's own inline hook on `num_compressSteam` (its
  number guard, with a `CalculateEndDamage` trace as its control) counted no
  call either, while `CalculateEndDamage` returned up to about 1.63e18 per
  hit.
- The DPS meter drew full digits (the `RealFormat` route) up to about
  7.9e18 with the game alive, and both launches exited `0x00000000`.
- **What it means:** no call reached `num_compressSteam` or
  `SteamCompressNumber`. No logpoint was set on `num_compressGML` or
  `PS5_NumCompressGMLWrapper`, so whether any `num_compress` consumer ran,
  and which script the global holds, is not measured. The shortener's
  failure bands above are therefore **untested, not refuted**. The run is a
  measured positive only for the `RealFormat` route.

**Live 2** (measured, ForgePact #230, 2026-10-20, capture
`forgepact-230-damage-crash-live-2`; the same research build, character, town
and dummies as Live 1, the reporter's 63 ForgePact settings, with
`show_damage` 1 and `combat_text_compress` 1 in `shop.ini`, and in the second
launch `dps_meter_compress` 1 as well):

- **The damage text reaches the shortener.** Floating damage numbers were
  drawn over the dummies and shortened, and `num_compress` led to
  `num_compressSteam` and on to `SteamCompressNumber` one call for one (748
  and 748 in a 20 s window; `num_compressGML` 0 beside a logging control).
- **The crash, with ForgePact's cap forced off.** The Modifiers were ramped
  from the reporter's x11 (Total Damage, with Critical Strike Damage x11 and
  Critical Strike Chance x6) to Total Damage x100, x1e4 and x1e6, and the game
  ended in the x1e6 window with exit code `0xC0000409`. Its dump reads
  `code=0xc0000409 subcode=8 raised-in=PAS_Steam_GMS_x64`, with
  `SteamCompressNumber` on the stack. The values ForgePact's hook traced into
  `num_compressSteam` (one line per new decade) were, in order, 2,915,427
  up to 15,038,794,170,000 (about 1.5e13, the largest traced value that
  passed), then 102,480,421,310,000 (about 1.025e14), the last line before
  the end. That is the first value of its decade, not necessarily the value
  the game ended on: values later in the same decade write no line, so the
  fatal value was at least 1.025e14 and below 1e15. No negative value was
  traced. The second launch's capped value (below) passed at 9.9999e13, a
  measured pass just under the reading's 1e14. The fatal value is not
  measured, only placed in [1.025e14, 1e15) by the per-decade trace, so
  1e14 as the limit stays the static reading; measuring it needs a trace
  of every value at or above 1e13, a later session's work.
- **The cap holding.** In the second launch, with the cap automatic, the
  guard was not armed before any lever and armed with the reporter's
  settings. Ramped to Total Damage x1e12, the hook saw values up to about
  2.2e20; it capped 29,990 of them (the first at about 1.003e14) to
  99,999,000,000,000, every floating number read `99999B` in the last window,
  the game answered after every window and the launch exited `0x00000000`.
- **At the reporter's x11** the values handed in reached about 2.1e9 per
  call (Sorak, Act 1 town), far below 1e14. Whether the reporter's own crash
  (another character, an Act 5 dummy) reached this limit is not measured.
- **Not established:** the DPS meter read `0` with `dps_meter_compress` on,
  in the x1e12 window too, so whether its compressed total reaches the
  shortener was not observed; what the game shows for an 8-character text;
  the NaN and negative bands.

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

**When the game writes the bag file.** The character file and the bag file are
written by separate calls, so one can be rewritten while the other is not.

- `gml_Script_SaveLocalFile` takes a file kind first and a local player number
  second (the inventory window passes its own `uiLocalPlayer`). Kind 0 writes
  the character file `herosiege<N>.hss` through `SaveSlot`, kind 4 the stash
  through `SaveStash`, and kind 9 the bag file `inventory_order_<N>.hss`
  through `SaveInventoryOrderNew`; each is wrapped in `SaveStart` and
  `SaveCommit`, the shape § 17 measured for the stash. `SaveInventoryOrderFunc`
  also keeps the bag writer as a method value, which a scan for direct call
  sites cannot see. **Static reading** (2026-10-12).
- Kind 9 is asked for by the inventory window's Destroy event
  (`UI_Inventory_Parent_obj`; offline, kind 0 and then kind 9) and by
  `Controller_obj`'s Game End event (offline, kinds 0 and 9 for the first
  player, the same again for the second under a condition not read, then the
  game's `Sleep` for 2000). The stash window's Destroy (`UI_Stash_obj`) saves
  kinds 0 and 4, not the bag; `Player_obj`'s Room End saves kind 0,
  `Controller_obj`'s Room End kind 2, and `RoomGoto` saves nothing. A headless
  byte scan (positive control: `SaveLocalFile`'s own call to
  `SaveInventoryOrderNew`, found) lists 104 direct `SaveLocalFile` call sites
  in about 57 functions; the rest, `UiAIngameExit`'s six among them, were not
  read. **Static reading** (2026-10-12).
- The bag writer passes every bag item through `CreateItemSaveStruct`, which
  copies the item's definition (§ 21.3), so a definition's `o` reaches the file
  with it. **Static reading** (2026-10-12).
- Over the 132 pre-restore snapshots hs-drive kept from 2026-09-20 to
  2026-10-12 (file times compared with each session's own backup): of the 66
  stops before 2026-10-04 17:00 UTC that rewrote the character file, 31 also
  rewrote the bag file in the same second; of the 43 such stops since, none
  did. In 35 sessions the bag file changed minutes before the stop.
  **Measured** (read-only, 2026-10-12).
- In the piece icon and stack follow-up's Live procedure 2 (2026-10-12,
  capture `forgepact-197-piece-icon-stack-live-2`, local to the hub's workorder
  folder), the pre-restore snapshot's bag file was still the 2026-10-10 file
  and no slot file held a soul piece. The character file rewritten at the stop
  holds no bag (the `inventory_tab_*` keys live only in the bag file) and,
  decoded, differed from the session's backup only in `playtime` and the order
  of its keys. A debugger logpoint on `SaveInventoryOrderNew` read 0 hits, its
  control still logging, until the detach just before the stop; the capture
  records no close of the bag window after the stacks were built.
  **Measured.**
- The bag files of the #197 sessions hold class-11 soul pieces with `o` 1 and
  Key-tab stacks with their counts (`o` 964 and the like); a class-11 item with
  no `o` is saved without one. **Measured.**
- Closing the stash saves the bag. In the follow-up's Live procedure 4
  (2026-10-12, research build, capture
  `forgepact-197-piece-icon-stack-live-4`, x64dbg logpoints with a
  `CheckTalentUse` control logging in the same window), six pickups made no
  `SaveLocalFile`, `SaveInventoryOrderNew` or inventory-window Destroy call
  and left the bag file as it was. Opening the stash (`hs_stash_open`) wrote
  nothing either; closing it (`hs_stash_close`) hit the logpoint on
  `UI_Inventory_Parent_obj`'s Destroy event once, `SaveLocalFile` seven times
  and `SaveInventoryOrderNew` once, between the fifth and sixth
  `SaveLocalFile`, and `inventory_order_13.hss`, `herosiege13.hss` and
  `stash.hss` were rewritten within the same second. With the stash open,
  `menulayout UI_Inventory_Parent_obj` listed the `UI_Stash_obj` instance, so
  the stash window is one of that parent's children, which fits the parent's
  Destroy running at its close; which of the seven `SaveLocalFile` calls asked
  for which kind was not logged. **Measured.** The player build's Live
  procedure 3 (capture `forgepact-197-piece-icon-stack-live-3`) wrote the bag
  file the same way. So the static reading above (the inventory window's
  Destroy asks for kind 9) is measured where the window closing is the
  stash's; the bag window's own close was not measured, because neither the I
  key nor the B key opened it (the owner opens it with C).
- A stop after that save did not write the bag file. In the same session a
  piece picked up after the stash's close took a stack from 3 to 4 with no
  save; the graceful stop then rewrote `herosiege13.hss` but not
  `inventory_order_13.hss`, which still held 3 (`stop-bag-write`, hub issue
  #506). **Measured.** Nor did the stops of the follow-up's Live procedures 1
  and 2 write it.
- Per close, in ForgePact #201's two sessions (2026-10-13, slot 14, file
  times read with `stat` before and after; captures
  `forgepact-201-exit-c0000409-live-1` and `-live-2`). The in-world stop
  (`hs_stop_game`, `WM_CLOSE`) rewrote `herosiege13.hss` and left
  `inventory_order_13.hss` as it was, both with the HS-Offline-Tracker
  producer loaded (Live 1 cell B) and with it held aside and every mod off
  (Live 2 cell D), so the producer is not why a stop skips the bag. The pause
  menu's Save & Exit (§ 8.4) rewrote both files within a second, with the
  producer present (Live 1 cell C) and absent (Live 2 cell G), and the close
  from `Chose_rm` after it rewrote neither (Live 1 cell C). **Measured.** The
  mods-on in-world stop (Live 2 cell F) and the main-menu closes did not
  record file times.
- A consumable's count survives the bag save and a reload. Live procedure 4's
  bag file held two class-11 stacks at `o` 3 and 2 (read with
  `tools/save_item_keys.py --defs`), and after a relaunch the bag held both
  with the same counts; Live procedure 3's held `o` 1 and 2 and reloaded the
  same. **Measured.**

So a stop is not a save of the bag file, and a check that reads the bag file
after a stop has to make the game save the bag in play first: closing the
stash does (measured above), and so does saving to the main menu or the pause
menu's Save & Exit (measured, #201). What decides whether a stop writes the
bag file is **not established**; the tracker producer is ruled out (#201).

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
  2026-09-10.** (That is as instance variables; read as built-in variables,
  `mouse_x`/`mouse_y` answer in room coordinates, § 19.5, measured
  2026-10-10.)

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

### 11.2 Spawners: most packs are built when the player comes near, some at arrival

- Every `Enemy_Creator_*` spawner exists and is awake from zone generation (one
  zone: 271 `Enemy_Creator_obj`, 13 Ambush, 19 Ancient, 7 Legion, with 208 live
  enemies). The family is `Enemy_Creator_obj` plus `_Champion_`, `_Ancient_`,
  `_Legion_`, `_Miniboss_`, `_Ambush_` and `_Colossal_Chest_`. **Measured**; family
  from names.
- Each plain creator (`Enemy_Creator_obj`; the other kinds below) registers a
  periodic timer with the game's timer system and keeps its handle in
  **`enemyCreatorTimer`** (period about 116 frames). The check spawns
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
  is `enemyArray` not being an array within one visit; after leaving and
  returning, all 92 plain creators read undefined (per-kind bullet below);
  `enemyCreatorTimer` alone cannot tell it,
  being undefined both before a creator arms and after it spawns. 5 of the 122
  had spawned by first sight, and the rest made about 5.25 kills each (614 for
  117). **Measured 2026-10-03**; the other creator objects' `enemyArray` was
  not sampled then ([dungeon chest, Live procedure 1b](../ForgePact/docs/dungeon-chest-research.md#live-procedure-1b));
  of the five kinds sampled since, only the plain and ambush creators carry
  it (the per-kind bullet below).
- **The SDK script table lists a Create-event closure for the plain creator
  only, and the seven creator objects are unrelated to one another.** Of the
  seven, only `Enemy_Creator_obj` has a Create-event closure in the SDK script
  table, `anon@886@gml_Object_Enemy_Creator_obj_Create_0` (the `anon@N` part
  is patch-specific, §5.3); the Ambush, Ancient, Champion, Colossal Chest,
  Legion and Miniboss creators have none listed. That absence says nothing
  about whether the other six have Create events of their own; what they carry
  is the measured bullet below. All seven (objects 1409-1415) are each a
  root object in the SDK parent table, with no parent and no children, so
  `instance_number`/`instance_find` on one never counts another's instances.
  **Static reading** of the SDK tables, 2026-10-06 (falorfrozen-cmd/ForgePact#181).
- **Of the five creator kinds sampled, only the plain and ambush creators
  carried `enemyArray`, and only the plain creator carried
  `enemyCreatorTimer`.** Per kind sampled, read by name with
  `variable_instance_exists` on every creator of that kind in the zone:
  - `Enemy_Creator_obj` (control): `enemyCreatorTimer` a number on unspawned
    creators; `enemyArray` undefined before birth and an array after, as
    above. On a revisit (leaving the zone and returning, 2026-10-06) all 92
    plain creators read `enemyArray` undefined, including the 10 whose
    `enemyCreatorTimer` was undefined and whose `enemyArray` had read an
    array before the player left; so after a revisit `enemyArray` not being
    an array does not show a creator is still to spawn. Why is not
    established.
  - `Enemy_Creator_Ambush_obj` (9 in one zone): no `enemyCreatorTimer`
    (absent). `enemyArray` exists and reads undefined before birth; when the
    player was moved beside them, 6 of the 9 read an array.
  - `Enemy_Creator_Ancient_obj` (15 and 10, two zones),
    `Enemy_Creator_Miniboss_obj` (3 and 4) and
    `Enemy_Creator_Colossal_Chest_obj` (6, one zone): neither variable exists
    on any of them. No colossal chest creator had a create attributed to it.
    Miniboss creators did (`Hellspawn_Guardsman_obj` 4 in one zone and
    `Servant_of_Devil_obj` 3 in the other, from creators about 3000 px from
    the player) and still read both variables absent afterwards. Whether
    those creates were the pack's birth, and what a miniboss or colossal
    chest creator holds after birth, is **not established**.
  - Ancient creators after creates were attributed to them: warping the
    player beside an ancient creator's position twice in a Depths of Hell zone (zone level 514), the
    owner saw monsters appear at each warp, and creates were attributed to
    ancient creators (0 before, 3 after the first warp, 7 after a warp beside
    a miniboss creator in the same area, 10 after the second ancient warp:
    `Hell_Beast_Passive_obj` 3, `Skeleton_Mage_Fire_obj` 3,
    `Imp_Passive_obj` 2, `Undead_Priest_Passive_obj` 2). All 15 ancient
    creators still existed afterwards and still read both variables absent.
    So an ancient creator that has made creates still carries neither
    variable. Whether those creates were its pack's birth is not
    established: normal packs were born at both ancient warps too (normal
    `stateborn` 10 → 22 at the first, 48 → 57 across the second), so the
    owner's report of monsters appearing does not single out an ancient pack;
    7 of the 10 creates are `*_Passive_obj`; and 4 came at the miniboss warp.
    **Measured 2026-10-06** (issue #181, capture
    `forgepact-181-map-reveal-icons-live-3.md`). In the same session no
    create was attributed to a miniboss creator at a warp beside one,
    although named monsters showed nearby.
  - `Enemy_Creator_Champion_obj` and `Enemy_Creator_Legion_obj`: none in
    either zone sampled, **not established**.

  So in both zones sampled, no ancient, miniboss or colossal chest creator
  showed a numeric timer or an `enemyArray`, and "still to spawn" could not
  be read from either variable on those three; by the static reading in the
  next bullet, their pack state is held in the protected-store record their
  `spawnPack` variable names. For ancient creators that
  holds after creates were attributed to them too (above); for miniboss and
  colossal chest creators, whether either is set later (nearer the player, or at birth) is not
  observed. **Measured 2026-10-06** (issue #181, captures
  `forgepact-181-map-reveal-icons-live-1.md` and `-live-3.md`;
  [map reveal §11, Live 1 results](../ForgePact/docs/map-reveal-research.md#live-1-results)
  and [Live 3 results](../ForgePact/docs/map-reveal-research.md#live-3-results)).
- **Every creator keeps its pack state in a protected-store record named by
  its `spawnPack` variable.** All seven creator objects allocate a record in
  the game's protected value store in their Create event, keep its key in the
  instance variable `spawnPack`, and free it in CleanUp; their own events read
  and write the pack state as that record's value. So
  `variable_instance_get(creator, "spawnPack")` returns a key, not the state
  (the same trap as a monster's `damage`, §13.7), and the state is
  `PC_GetVariableGMLWrapper(key)`. Check the key before that call: a key
  outside 0..262143 must never reach the store's getter, since the store
  holds 262,144 records (§5.8) and a -1 key faulted the game. What moves the
  state, per kind:
  - `Enemy_Creator_Ancient_obj`: 1 after Create. While it is 1, each step
    tests the player's distance, and within about 1200 px (or always, for a
    wormhole creator) writes 2 and arms an alarm for the next frame; that
    alarm builds the pack from the zone's enemy pool, rolls its rarity and
    affixes, and writes 3. The creator stays. So an ancient pack exists at
    most one frame after the state leaves 1. *Measured (Live 4):* 1 on all
    10 at arrival, 3 on each born one (1 → 3 at a warp beside it), and the
    creator still exists; the state 2 between them was never read.
  - `Enemy_Creator_Miniboss_obj`: Create writes 1 and arms an alarm, due the
    next frame in most rooms and a few seconds later in seven named rooms
    (Ruby Gardens, Tomb of Amun Ra 02, the Fortune Teller room and four Act 9
    boss rooms). That alarm, while the state is 1, builds the miniboss and
    writes 2. It references named uniques (`Mancrusher_obj`, `Queen_Bee_obj`,
    `Black_Plague_obj` and others), but how it picks what it builds was not
    read, so these are not a set it is known to build from; Live 4 attributed
    a `Hellspawn_Guardsman_obj` to each creator (below). No miniboss event tests the player's distance,
    so a miniboss pack is built at zone arrival, not on approach. Create also
    asks `ZoneStateExists`; what that changes on a revisit was not read.
    *Measured (Live 4):* 2 on all 4 at arrival, read with the player at
    the zone's waypoint (2976,3648, the position `playerwarp` reported
    before the step-4 warp; no movement in between was recorded), about
    900-1460 px from the four creators, with one `Hellspawn_Guardsman_obj`
    attributed to each by our create hooks (in Steam Train). The creator
    still exists after its pack is killed (262691 read in full before the
    warp, 5 s after it, about 16 s after it and after the kill; 262694 in
    full 5 s after the warp and after the kill, and before the warp only
    its census row, spawnPack 2): its six protected values (state 2, zone state 1,
    self-destroy 0 and the rest) and its instance variables did not change,
    apart from `img`, which advanced steadily throughout; built-in variables
    such as its alarms were not read. So none of the values read marks the
    pack's death (not observed, not ruled out).
  - `Enemy_Creator_Legion_obj`: Create writes 1 and arms an alarm (about
    1.5 s in one branch), which builds the pack (named monsters such as
    `Hellspawn_Guardsman_obj`, `Undead_Raider_obj`, `Skinwalker_obj`) and
    writes 2. No distance test: built at arrival.
  - `Enemy_Creator_Champion_obj`: its step sets the state to 1 when unset,
    builds the pack while it is 1 and writes 2. No distance test: built in
    its first steps.
  - `Enemy_Creator_Colossal_Chest_obj`: its step builds its wave while the
    state is 1 and writes 2. The chest sets that 1: `ChestColossalSpawnEnemies`,
    run when the player opens a `Colossal_Chest_obj`, sets it on the nearby
    colossal chest creators whose state is unset. So a colossal chest pack is
    born when its chest is opened. *Measured (Live 4):* 0 on all 6 at
    arrival and until the chest was opened, 2 on all 6 afterwards, with one
    `Abomination_obj` attributed to each; the state 1 between was not read.
  - `Enemy_Creator_Ambush_obj`: while the state is unset, its step counts
    down a check timer and tests the player's distance; once near, it writes
    1, shows the ambush effect and arms the alarm that builds the pack (and
    fills `enemyArray`, measured above). *Measured (Live 4):* 0 (unset) on
    all 9 at arrival; no ambush birth was seen that session.
  - `Enemy_Creator_obj`: Create writes several protected values; about 0.4 s
    later an alarm reads the state before it registers the periodic timer
    (`enemyCreatorTimer`). Which value means born was not read statically.
    *Measured (Live 4):* 1 before its birth, 3 after: at arrival 50 read 1
    and the 12 already born read 3, and one creator watched through its
    birth went 1 → 3 as `enemyArray` became an array and
    `enemyCreatorTimer` went away. At every census that session the number
    of plain creators reading 3 equalled the number whose `enemyArray` was
    an array (12, 25, 30, 37); the per-creator match was read on the
    watched creator only.

  **On a revisit** (*measured, Live 4*): leaving a zone by waypoint and
  coming back gives every creator a new instance id (262xxx → 321xxx; no
  creator id seen on the first visit was listed again, for any kind), at
  the same position. The protected pack state comes back with the zone for
  every kind measured: normal 1 on 25 and 3 on 37, ancient 1 on 3 and 3 on
  7, colossal chest 2 on all 6, miniboss 2 on all 4. The plain creators
  kept their timer split (25 with a timer, 37 without), but none carried an
  `enemyArray` that was an array after the revisit, so on a revisit
  `enemyArray` no longer tells a born plain creator from an unborn one; the
  protected state and the timer's absence still do, by count (37 and 37).

  **Measured 2026-10-06** (issue #181, capture
  `forgepact-181-map-reveal-icons-live-4.md`, one zone, Steam Train, zone
  level 293; [map reveal §11, Live 4 results](../ForgePact/docs/map-reveal-research.md#live-4-results)):
  that the getter, given the key `spawnPack` holds, returns a state that
  moves with the pack's birth as above (a positive control on a known slot
  through the same getter answered in every census), and each *Measured (Live 4)* line and the
  revisit paragraph above. Everything else in this bullet is still the
  **static reading**, 2026-10-06 (falorfrozen-cmd/ForgePact#181, replan 2
  of the hub workorder `forgepact-181-map-reveal-icons`): where the record
  is allocated and freed, the alarms, the distance tests and the intermediate states, the miniboss room list and
  the unique names its alarm references, and the whole legion and champion lines, since that session
  had no legion or champion creator (not observed). Not read: what the
  zone state restores on a revisit beyond the values above, the plain
  creator's pack-building alarm (it exceeded the decompiler's time limit),
  and the miniboss alarm beyond its state test and its final write, which
  includes how it picks the unit it builds.
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
  **Measured** and **static reading.** On 2026-09-28 (Highland Mines Copper Veins) every node
  snapshot, before and after completions, read `miningPlayer` as an instance
  reference (`312664r`), not `noone`; whether that instance is the local player
  was not checked, and when the game sets it is not established.
- **Mining XP is an account value, and `GetMiningLevel()` returns it raw**, not
  a level derived from it. The game keeps it in the account file
  `%LOCALAPPDATA%\Hero_Siege\hs2saves\shop.ini`, section `[mining]`, keys
  `mining` and `mining_hc`, not in a character save. Both keys were edited to
  225 before a launch (HSSaveEditor writes the two together, so which one a
  softcore hero reads is not separated); in game `GetMiningLevel()` then read
  `225.0`, and each later dig moved that reading by exactly the "+n" of the
  dig's on-screen XP text (225 -> 232 with "mining +7", 232 -> 238 with
  "mining +6"). The game wrote the changed value back to `shop.ini` at its own
  save on exit. **Measured 2026-10-19** (ForgePact #223 Live 1 and Live 2, hero
  slot 14). The account's value before the sessions was 5000, which the owner
  reports as maxed; at 4000 one dig showed "mining +0" (Live 1), and why is not
  established.
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
  branch skips them is not established (MR8). On 2026-10-19, at mining XP 225,
  digs were observed calling both: the `MiningAdd` detour counted one call per
  dig, and for a dig with two completion re-runs the `CombatText` detour
  counted one call from the dig and one from each re-run, while an x64dbg
  logpoint on `CombatText` logged three hits inside `MiningNodeStepMain`'s
  window. **Measured 2026-10-19** (ForgePact #223 Live 1 and Live 2). So MR8's
  zeros do not hold for every dig; the condition that skips the calls is still
  not established.
  A completion re-run whose `MiningAdd`, `ExperienceUpdate` and
  `GuildExperienceAdd` calls are skipped adds no mining XP: on the same
  character a dig with no re-run gained 7 (one text, "mining +7") and the next
  dig, with two such re-runs, gained 6 (one text, "mining +6"), the detours
  reading 2 skipped calls of each script for the two re-runs. Of the silenced
  rewards, mining, character and guild XP were measured not to repeat per roll. **Measured 2026-10-19** (ForgePact #223 Live 2, x1 +7, x3 +6).
  **The dig reads one side effect's result: the `CombatText` instance.**
  `CombatText` creates one `Combat_Text_obj` (973) instance, sets its variables
  from its arguments and returns that instance. Of the step's six `CombatText`
  call sites, two (each after an `ExperienceUpdate` + `GuildExperienceAdd` pair,
  behind a further condition that is not established) keep the returned
  instance and at once set its `font`, `vspeed` and `hspeed`; the other four
  discard it. The results of `MiningAdd`, `ExperienceUpdate`,
  `GuildExperienceAdd` and `update_quest` are never read. **Static reading,
  2026-10-19**, on build `498d588550d8`; the installed build `dab03f13...` holds
  game code byte-identical to it (only the Aurie-appended section differs, by
  byte compare), so the reading holds there too. A detour that returns no value
  at those two sites leaves the step setting `font` on a non-instance, and the
  game raises its runtime error as a C++ exception: **inferred** from the
  2026-10-19 crash logs and reproduced in ForgePact's harness, **not measured**
  in the game. Why the 2026-09-28 session never saw `CombatText` from a dig
  (MR8 above) is consistent with that character being at the mining cap, but
  not established.
  [Extra rolls](../ForgePact/docs/mining-ore-research.md#extra-rolls).
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
- The only direct call of `DropUniqueItems` found is drop type 45's;
  indirect calls were not scanned. **Static reading** (2026-10-20, ForgePact
  #166). A kill's ordinary uniques come from `DropItem`'s own draw on
  `lootListUnique[LoadSatanicDropTier's answer]`, which runs without
  `LoadDrops` (§ 13.12). ForgePact's Mod live procedure 7 measured it
  (`unique-route: satanic-draw`): every natural unique of its Live 1 owner
  window was built in the draw's scope, and of Live 1b's and Live 1c's all
  but 4, which were built inside a nested `DropUniqueItems` roll. **Measured**
  (2026-10-20 and 2026-10-21;
  [Mod live 7 results](../ForgePact/docs/mark1-set-research.md#mod-live-7-results)).
- Drop type 45 on ordinary kills, with nothing forced: in ForgePact's Mod
  live 6 (2026-10-20, slot 14 "Sorak", Hell, from the Outskirts of Inoya,
  zone level 243), the owner's 8.7 minutes of play ran `LoadDrops` 45332
  times over 1831 distinct drop arrays, and type 45's chance was 0 on every
  one of them (`c45-nonzero=` 0, `c45-max=` 0), as on 51 more arrays from
  the operator's kills. The game made no type-45 call of its own
  (`game45=` 0), and `DropUniqueItems` was not entered while 4 natural
  uniques dropped (`vanilla-unique-path: other-path`, with its by-name
  control passing in the same session). With the research build's
  `killgate` lever forcing type 45's gate open once per kill, inside the
  game's own `LoadDrops` call, 57 kills ran `DropUniqueItems` through
  `LoadDrops`' direct call, 57 on a debugger logpoint and 57 on the detour
  alike. **Measured** (one session;
  [Mod live 6 results](../ForgePact/docs/mark1-set-research.md#mod-live-6-results)).
  Type 45 is not always 0: Mod live 8 counted 7 `DropUniqueItems` calls
  inside about 2900 outermost `DropItem` calls of the owner's play in The
  Devil's Breach at raised magic find (§ 13.12). What opened the gate there is not established.
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
What the lookup does with an index past its category's end is in § 21.3.
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
- The 44 key names of repository category 12 are listed in § 21.3.

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
- **The droppable entries.** Of `lootListUnique[5]`'s 380 entries, 48 pass
  the roll's two tests (rarity 7 or 10, not flagged hidden), counted with
  repeats; Water Melon `{10, 0, 47}` and Soul Collector `{10, 0, 91}` are
  each listed once. The same in `Town_01_rm` and `Act_01_01`. **Measured**
  (2026-10-13, ForgePact's flight charms Mod live 2, `flightprobe pool`,
  research DLL sha256 `dd87086c…`). So an entry listed once is 1 in 48 of the
  roll's drops, and each item pushed onto the Angelic list (Headhunter,
  Tyrant's Crown, Gabriel Wings, Witch's Broomstick) takes 1 in (48 + e),
  e being the entries pushed (hub `docs/models/unique-pick-spec.md`). At one
  pushed entry each for Gabriel Wings and Witch's Broomstick, 102 hits gave
  2 Broomsticks and no Wings, both within that share's band (`rate-angelic`);
  0 Wings fits a Wings push that did nothing just as well, so the Wings push
  at one copy is not observed (it is shown only at 200 copies, Mod live 1).
  [Mod live 2 results](../ForgePact/docs/flight-charms-research.md#mod-live-2-results)
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
  reading (2026-10-02, issue #74).** Potions (type 18) and the roll, which
  tests no item type, are § 13.13.
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
  (2026-10-02, issue #74).** Of the three rolls read on 2026-10-11
  (`DropUniqueItems`, this roll and `DropItemHeroic`), only `DropItemHeroic`
  keeps a Heroic (9) entry; the other readers listed here were not read for
  rarity (§ 23.4, **static reading**, 2026-10-11, ForgePact #158). Called with
  the player as `self`, `DropItemHeroic` placed seven Heroic and three Satanic
  uniques in ten calls (§ 23.4, **measured**, 2026-10-12).
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
  `b` the second (the unique's index), `c` from the third (1, the unique
  repository); it has no field `a` (**measured**, Live 2, below). `c` is not
  the third argument itself but a real derived from it: 1 when the runner's
  own truth test passes on that argument, else 0, and a missing or undefined
  third argument counts as 0. That truth test passes a real or a bool above
  0.5, an int32 or a reference above 0, an int64 above 0 and a pointer that
  is not null; undefined fails it, and a string or any other kind raises a
  runner error. So a caller may pass the class as a bool or as a number and
  get the same record, and a hook that reads the argument before the game
  does must apply the same test rather than read it as a number. Which kind
  the Angelic roll passes was not read; nothing on this path reads the
  argument after `CreateDefaultParams` has stored `c`. **Static reading**
  (2026-10-21, ForgePact #166, build 498d5885…). The built
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
- **The merchant sale** (**static reading**, 2026-10-23, build `498d588550d8`, ForgePact #196), in our own words:
  - **No script whose name mentions merchant, vendor, shop, sell, buyback, price or value sells an item** (a script under another name was not ruled out). Every SDK script whose name mentions merchant, vendor, shop, sell, buyback, price or value was checked, and each is something else: `CallbackMerchantSellPoolExit` and `CallbackMerchantSellPoolResetGold` handle an online API answer (they decrypt and hash it); `GetMerchantPrice` is a fixed table of 174 names to values, not an item's sale price; `GetItemBuyPrice` belongs to buying from the merchant (it sits beside a purchase's gold checks); the `UiAMarket*` scripts are the player market.
  - **The sale is one branch of a UI closure**: `UI_Inventory_Grid_obj`'s `m_MoveItemToGrid` (§ 9.8 lists it on the 2026-09-17 build; its `anon@N` name moves with every patch, § 5.3), taken when an item is moved into the merchant's grid. The closure takes the item from the drag state, not from an argument ([stash move research](../ForgePact/docs/stash-move-research.md), § Static reading), so a ground item cannot be handed to it.
  - **Its steps, in order:** check the item's hash (`ItemCheckHash`, reporting the client through `ReportClient` on a failure); take the dragged item's fingerprint (`itemDragFingerprint`) and append it to the merchant window's `sellPoolFingerprintList` (the buyback / sell pool) with `ds_list_add`; compute the price as `ceil` of the item's `GetItemInfo` answer for key 9 multiplied by a second value; credit it with `PickUpGoldCheck(GetCounterHash(), price, 1, undefined, undefined, undefined)`, six arguments; write the UI gold log with `GoldLogAdd(18, price)`, two arguments (§ 13.11); then make one more call, which looks like a sound and was not identified.
  - **A second branch** credits `PickUpGoldCheck(hash, price, undefined, undefined, undefined, undefined)` and writes no gold log. Its condition was not read, so when a sale takes it is **not established**.
  - **What this confirms of the bullet above.** `GetItemInfo(key, default)` answers the item's `itemInfoStruct[key]` (§ 23.2), so the first factor is `itemInfoStruct["9"]`; this reading confirms the key 9, the multiplication and the rounding up (`ceil`). That the second factor is the stack count (`itemDefinitionStruct.o`, absent counting as 1) is AFK FARM's earlier reading and was **not re-read** here.
  - **`GenerateItemPrice`** reads the item's definition and its rarity code (a base of 15, 30, 50, 225 or 450 by rarity, 5 otherwise) and writes item info through `SetItemInfo`. Which key it writes is **not established**; key 9 is the natural guess.
  - What this reading shows the sale changing: the gold balance (through `PickUpGoldCheck` only, as below), the UI gold log on the first branch, and the buyback list; how the sold item leaves the bag and what the unidentified last call does were not read, so this list is **not established** as complete. ForgePact's `autosell` (#196) mirrors the first branch's price, credit and log for a filter-hidden ground item by name and leaves the buyback list alone. Live 1 measured the price (below); Live 2 measured the by-name credit paying the player exactly (below). The buyback list staying clean and the sale's second branch are still **not observed live**.
  - **What the credit answers** (**static reading**, 2026-10-24, build `498d588550d8`, ForgePact #196, from the local decompile of `PickUpGoldCheck` #173 made): the script starts with its answer `undefined` and writes one in a single place, the hash-mismatch path, where it reports the client and answers `false`. Every other path returns with the answer still `undefined`, so a credit that passes the hash check answers `undefined`, never `true`; a caller that waits for `true` reads every good credit as refused. Both `GetCounterHash` and the check inside `PickUpGoldCheck` read the counter from the global protected store (`gDataProtected`), not from `self`, so the instance a caller passes as `self` does not decide the hash. An `undefined` third argument is replaced with 0, so the sale's two branches differ in that argument (1 against 0); what the argument means was not read, and neither was the rest of the body after the hash check (its online calls, the balance write). The gamba machine calls `GetGoldAmount` after its own `PickUpGoldCheck` debit (§ 20.4, measured as an order of calls); a balance read in the same frame, right after the call, already includes the credit (**measured**, ForgePact #196's Live 2, below). Live 2 also measured the answer: every credit the mod made answered `undefined` and paid, which agrees with this reading.
  - **The types the game will not buy** (**static reading**, same date and build): the translation key behind the line "Item cannot be sold" is `item_cannot_be_sold` (`bin\translationsAttributes.csv`), and its one use in the code is inside the tooltip script `DrawInventoryItemV2` (§ 16.6; found by a byte scan, since the imported project leaves that function unnamed). The tooltip takes the item's sale price from `GetItemInfo(9)`, sets it to 0 when the item's `itemType` is Key (12), Tarot (13), Material (14), Socketable (15) or Relic (16) (`HeroSiege::Items::ItemType::Key`, `Tarot`, `Material`, `Socketable`, `Relic`), and with a price of 0 draws "Item cannot be sold", under a condition on one of its arguments that was not identified (the merchant view is the natural reading). `itemType` sits on the item instance beside `itemDefinitionStruct` (§ 9.3). Whether the sale closure itself refuses the same five types is **not established** (it was not read; decompiling it times out). ForgePact's `autosell` follows the tooltip's rule and never sells these five types.
  - **Measured** (2026-10-24, capture `forgepact-196-autosell-filtered-live-1`, ForgePact #196's Live 1, player build): a hand sale of a ring to the town merchant raised the balance by exactly `ceil(info 9 × 1)`, 57, the price `autosell quote` gave it; `GetGoldAmount`, called by name from the plugin, answered the balance the HUD showed; a Topaz x4 (Socketable) and a Destiny Shard (Material) both showed "Item cannot be sold", and the merchant would not take the Topaz. Live 1's build, before the type rule above, still quoted those two at 692 and 1350. [Auto-sell research](../ForgePact/docs/auto-sell-research.md)
  - **Measured** (2026-10-24, capture `forgepact-196-autosell-filtered-live-2`, ForgePact #196's Live 2, research build sha256 `2bd6c8ab...`, slot 14, Hell, Fields of Battle at zone level 245, no debugger, the session's save restored after it):
    - **The by-name credit pays exactly.** `PickUpGoldCheck(GetCounterHash(), price, 1, ...)`, called by name from the plugin's frame callback with the local player as `self`, raised `GetGoldAmount` by exactly the price, read immediately before and after the call: 81 of 81 sales in about 117 s of kills (111 of 111 by the end of the session), none paid more or less, and none refused by the hash check (no `false` answer, no failed dispatch, no credit that left the balance unchanged). So the hash check accepts a caller whose `self` is the player, as the self-free reading above says, and the balance read in the same frame already includes the credit. The balance over the window rose 4,540 against 4,342 of sales; the other 198 is not attributed: coin pickups are the likely source but were not counted, and the session cannot rule out a per-sale effect after the second balance read (the gap was about 2.4 gold per sale in both windows).
    - **The credit's answer is `undefined`.** Every answer recorded in the session was `undefined`, as the static reading says; none was `true`.
    - **`itemType` reads off the item instance as the tooltip rule expects.** With the bag open in town, the mod read type 7 on a ring (priced 57, the price Live 1's hand sale paid), 15 on a Topaz and a Diamond (Socketable) and 14 on a material, and refused the last three as types the game does not sell. That the merchant refuses the five types is measured for the Socketable only (Live 1); a dropped item of the five types was **not observed live** (none fell in the session's kill windows).
    - **Not observed live:** the sale's second branch, the buyback list, a sellable stack (so the stack factor stays AFK FARM's reading), the offline gold cap, what the remaining balance rise over a kill window came from, and a Chaos Tower floor's drops (the character died on the first floor before the readings that would show them).
- **Gold** is account-wide, with separate pools for softcore, hardcore and Blood Pact (`hs2saves\shop.ini`, `[gold]`). The offline cap is 500,000,000.
  - `PickUpGoldCheck(GetCounterHash(), amount, …)` is the only call that changes the balance, both credits and debits. `GoldLogAdd` only writes the UI log.
  - AFK FARM's `worker pay` and `worker credit` (0.9) use `PickUpGoldCheck` with a fresh hash, one receipt per request. **Measured** 2026-09-25: a `worker credit` of 5,000 raised the balance by exactly 5,000.
  - **Static reading** (ForgePact #173, 2026-10-06): `PickUpGoldCheck` first compares its hash argument with the current counter hash (`GetCounterHash`); on a mismatch it reports the client (`ReportClient`, § 7.5) and returns false without touching the balance. A second `ReportClient` call site in it exists; its condition was not read. The bodies of `PickUpGoldCheck` and `ReportClient` themselves make no call that ends the game. Of their named callees, `GetCounterHash` and `ShowDebug` were read; `ApiRequest`, `ApiRequestRegion`, `GetGameStateReport`, `DecryptStringApi`, `GetCurrenciesSetLogParams` and `string_sha256` were not, so whether a pickup that fails the game's own check can end the game through them is not established. Not read: `PickUpGoldCheck`'s 58 unnamed callees, `DropGold` and `DropMonsterGold` again (not named in this build's project, so #77's reading above stands), and `Coin_obj`'s Create closures; where a coin hands its value to `PickUpGoldCheck` is not established. [Gold x100 crash research, #173](../ForgePact/docs/dropmult-gold-crash-research.md#static-reading)
- **A monster's gold drop is one coin** (ForgePact #77, 2026-09-27):
  - `DropMonsterGold` (six arguments) applies the profile's gold getters, rounds an amount down and calls `DropGold` **once**, directly, with nine arguments; it has no loop. `DropGold` creates **one** instance and sets its value with one call to that coin's `m_SetGoldValue` method, then sets its spread and log fields. **Static reading.**
  - The coin is a `Coin_obj`, and coins are not `Loot_Ground_obj` instances: with each call repeated a hundred times (below), a count of `Coin_obj` by name rose from 0 to 20,000 over two drops while `Loot_Ground_obj` stayed at 23. **Measured.**
  - `DropGold`'s arguments as logged on four x1 drops: argument 0 a 40-character hex string, the same on every call; 1 and 2 the drop position (equal to `DropMonsterGold`'s 0 and 1); 3 always 1; **4 the only one that varied per drop** (51, 59, 31, 29); 5-8 undefined. Index 4 is the amount's shape and the static reading's candidate. **Measured.**
  - Argument 4 held against the gold the game showed, on the player build with ForgePact's Gold multiplier at x100 (ForgePact #77's Live 2, 2026-09-27): the hook scaled the first coin's argument 4 from 44 to 4400, and the HUD gold rose from 188948 to 189019 at x1 (+71), then to 201889 at x100 (+12870, two stacks the screen showed as 5720 and 7150), with no freeze at the kill or the pickup. So scaling argument 4 scales the gold picked up: the credited stacks were about 1.3 x the scaled argument 4 on this character (5720 = 4400 x 1.3), so what the pickup credits is argument 4 times a further factor whose source (a gold-find stat at pickup?) is not established. **Measured**, monster gold only (see the next bullet for #173's repeat); whether the game caps or rounds a coin's value is not established.
  - The 1.3 x held over many coins (ForgePact #173's Live 1 and Live 2, 2026-10-07, same character, research and player builds, every coin's scaled argument 4 logged): the HUD gold rose by exactly 1.3 x the coins' summed scaled amounts in three play windows (45 coins at x10, zone level 243, +27,508 for 21,160; 3 coins at x10, +1,859 for 1,430, and 5 at x100, +29,900 for 23,000, zone level 514), and by 1.26 x and 1.28 x in two x100 windows, mostly at zone level 243 (the 39-coin window also spent about 40 s in `Act_05_02`, level not read) (39 coins, +234,260 for 185,900; 61 coins, +444,990 for 346,500) whose readings may have left coins on the ground. x100 coins (scaled amounts such as 3,100 and 5,900) were picked up with no freeze and no crash observed (Live 1, research build, whose stall watchdog reported a 6 s freeze elsewhere in the same session). In Live 1's x10 window the `Coin_obj` count rose with each drop and fell back to 0 within about 0.3-2 s as the coins were collected; the x100 windows' fall times were not read (the 61-coin window's reading was taken with one coin still on the ground), and the player build has no coin count. **Measured**, monster gold only; the factor's source is still not established. [Gold x100 crash research, #173](../ForgePact/docs/dropmult-gold-crash-research.md#results)
  - One `DropGold` per `DropMonsterGold` at x1 (4 and 4). A mod that repeats both calls a hundred times multiplies, because each repeated `DropMonsterGold` reaches the hooked `DropGold` again: two drops made 200 hooked `DropGold` calls, each running the original a hundred times, and 20,000 coins; the frame stalled 8.4 s at the drop and 6.5 s again at the pickup, and the game recovered once the coins were gone. Scale the one coin's amount instead. **Measured.**

  [dev2 bug batch, #77](../ForgePact/docs/dev2-bug-batch-research.md#77-dropmult-gold-100-froze-the-game)
- **`LootGroundCreate(x, y, itemType, def, …)`** makes a floor item whose Create event builds it (`CreateItemNew`). `def` carries `b` (base), `j`, `c` (0 normal, 1 unique repository) and optional `o` (stack) and `a` (seed). Rarity is not an argument. **Measured** for types 14 and 15 through AFK FARM's workers. Type 12 was **measured** on 2026-09-25: a town delivery made Basic Keys (12:0) and Cellar Keys (12:10) with the right `b` and `o`. Type 13 was **measured** the same day: a town delivery made a Battle Fragment (13:0) with the right `b` and `o`, and the game gave it a new seed (`a`).

AFK FARM design, 0.9 (a private repository)

### 13.11 Gold, XP and kill counters (HS Offline Tracker's routes)

Three scripts the game calls on a gold pickup's UI log, an experience gain
and a monster kill; one call per kill is measured, and whether every gold or
experience credit (vendor sales, quest rewards, a mod's `PickUpGoldCheck`
credit) passes through `GoldLogAdd`/`ExperienceUpdate` is not established.
HS-Offline-Tracker's producer DLL counts through them (its
`aurie-producer/README.md` § "Current counter contract", a reviewed code
profile bound to the build's fingerprint; only the kill count cites a live
run), and ForgePact's `tracker` sensor (ForgePact #185,
`ForgePact/docs/tracker-research.md`) counts through the same three, by name.
So a gold or experience total built on them is what these scripts saw, not
yet known to be every credit. In our own words, with labels:

- **`GoldLogAdd`** is the gold credit's UI-log writer (§ 13.10: it does not
  change the balance; `PickUpGoldCheck` does). It takes **two arguments**, and
  on the 2026-08-29 build the earned amount is **argument 1** (argument 0 on
  the older Season 10 build the Tracker reviewed first). **The Tracker's
  reviewed code profile (static reading)**; its producer validates the amount
  as a finite, positive whole number. A local reading of the current build's function agrees that it is a
  two-argument UI-log writer (**static reading**, 2026-10-13). ForgePact's
  sensor accepts 1 to 4 arguments and counts the last one that decodes as a
  positive whole number (the producer's adaptive rule), so the amount at
  index 1 is what it counts. The merchant sale's first branch calls it
  with argument 0 = 18 and the price at argument 1, and the second branch
  writes no gold log (**static reading**, 2026-10-23, ForgePact #196,
  § 13.10 "The merchant sale"). Whether a hook or the sensor above sees
  that call is not measured.
- **`ExperienceUpdate`** takes **two arguments**; **argument 0** is the
  experience credited. A call the game refuses returns an explicit boolean
  `false`, and that call is not a gain. **The Tracker's reviewed code profile
  (static reading)**, its reviewed rejection exit. It is reached by direct calls, so only a native
  detour sees it: mining's completion run calls it once per run (§ 12,
  measured 2026-09-28), and calling it directly from a mod reports a hash
  mismatch (§ 22), so the sensor only observes it.
- **`EnemyAddStatistics`** takes **one argument**, the kill's
  `killStatistic` id (a non-negative whole number, 0 included), which equals
  the monster's rank (§ 13.7). **One call per kill:** in a packaged live run
  the Tracker's candidate calls rose 96 to 152 (+56) while the same
  character's saved `statisticTotalMonsterKills` rose 45,516 to 45,572 (+56)
  over the same save interval. **Measured by the Tracker.**

**Measured on ForgePact's own instrument** (Live procedure 1 of the toolkit
workorder `forgepact-185-tracker-move`, capture
`forgepact-185-tracker-move-live-1`, 2026-10-13, this build, the owner's
play in `Act_01_01`):
- each script's debugger logpoint hits equal the sensor's matching `*-calls=`
  rise, beside a rising control logpoint: 17 `GoldLogAdd`, 588
  `ExperienceUpdate` and 588 `EnemyAddStatistics` calls;
- every hit logged 2, 2 and 1 arguments respectively, so each script's
  argument count is now measured. Gold's amount index stays the reviewed
  profile above, and whether every gold credit passes through `GoldLogAdd`
  stays not established;
- Sorak's save file 13 moved by exactly the sensor's sums, experience
  +501,483 and kills +588 (the operator's reads of file 13 in the capture's
  steps 1 and 12);
- the procedure's own `kills-vs-save` and `xp-vs-save` checks read file 14,
  another character's (the save files count from 0, § 8.2), and stay `fail`
  as written.

Live procedure 2 of the toolkit workorder `forgepact-185-tracker-zone-fix`
(capture `forgepact-185-tracker-zone-fix-live-2`, 2026-10-14, the same
character in `Act_01_01`, fought through `hs_input`) read file 13 itself,
before and after: experience 16,441,857 to 16,511,032 (+69,175) and kills
797,474 to 797,532 (+58), exactly the sensor's `xp-sum=69175` and
`kills-sum=58` (`kills-vs-save` and `xp-vs-save` `pass`, **measured**). Its
gold sum (201, from 3 `GoldLogAdd` calls) has no save counterpart in that
check.

### 13.12 The unique draw inside DropItem

Read on 2026-10-20 for ForgePact's Mark 1 drops (#166), after the drops
workorder's Live 3 saw four natural uniques drop from kills in Hell while
`DropUniqueItems` (§ 23.4, § 23.8) was never entered and drop type 45's
chance was never above 0 on any `LoadDrops` array
([Mark 1 research, Phase 4](../ForgePact/docs/mark1-set-research.md#phase-4-the-unique-draw-inside-dropitem)).
The means: the hub's ghidra MCP on build `498d5885…` for
`LoadSatanicDropTier` and `ReturnRandomSatanic`, and, because `DropItem` is
too large for the decompiler (a headless decompile timed out on it on
2026-10-02) and has no body in the MCP, a headless byte scan for direct calls
(`FindCallers.java`), its call list (`ListCallsIn.java`) and a local
disassembly listing. The byte scan's positive control, in the same run, was
`CreateDefaultParams` (2349) with 177 direct sites. Every reading below is
the order and shape of calls, paraphrased; no listing is reproduced here.
ForgePact's Mod live procedure 7 then measured the route, k, the reads per
build, argument 7, the lever's pushed entries reaching the draw and the
tier-5 check. It ran in three sessions (2026-10-20 and 2026-10-21, slot 14,
Hell, build `498d5885…`), recorded in
[Mod live 7 results](../ForgePact/docs/mark1-set-research.md#mod-live-7-results).
ForgePact's Mod live procedure 8 (2026-10-21, slot 14, Hell, the research
build that moves the Mark 1 drops and Pocket Elf onto this draw) measured
the class argument, the stand-ins pushed for a call being built, and
`DropUniqueItems` running inside a kill's `DropItem` call, recorded in
[Mod live 8 results](../ForgePact/docs/mark1-set-research.md#mod-live-8-results).
Each label below says which.

- `DropItem` (1364) has 19 direct call sites, all in unnamed object events,
  and every one passes 12 arguments. **Static reading** (2026-10-20,
  ForgePact #166).
- `DropItem` is the only direct caller of both `LoadCommonDropTier` (2172)
  and `LoadSatanicDropTier` (2173), each called once and each result kept in
  a local of its own. That scan ran on these two names alone, so its hit cap
  was not reached. `LoadSatanicDropTier` answers a whole number from 0 to 5:
  it sorts the monster's level into brackets (bounds at 200, 123, 100, 75,
  42, 24 and 15) and, inside each bracket, steps the answer by cumulative
  random cut-offs. ForgePact's `raredrop satanic` already lifts its first
  argument. **Static reading** (2026-10-20, ForgePact #166). **Measured**
  (Mod live 7) is how its answers spread in Hell (zone levels 243 to 245
  and the owner's own play): answers 0 to 5 counted 0, 405, 401, 410, 3449
  and 3432 over 8146 `DropItem` calls (Live 1c, magic find x10), and 0,
  179, 193, 169, 1530 and 1432 over 3544 calls (Live 1b). k = 0 never came
  up. In those two sessions there was about one answer per call; in Live 1
  the answers outnumbered the calls (867 against 497), and why is not
  established.
- `DropItem` draws a unique itself, apart from every named unique roll. It
  takes `Controller_obj.lootListUnique[k]`, with k the value
  `LoadSatanicDropTier` returned, reads its size, draws a random index, reads
  the entry there and needs it to be an array. It looks the entry's triple up
  with a direct `GetUniqueRepoStruct` (819) call and reads the definition's
  fields 28 (level-like), 40 and 41 (flags) and 27 (the rarity, § 13.4). A
  set field 40 or 41 sends it back to draw again, inside a loop whose counter
  starts at 500, so a call can draw up to about 500 times. **Static reading**
  (2026-10-20, ForgePact #166).
  **Measured** (Mod live 7): this draw is the route a kill's unique takes.
  - In Live 1's owner window (about 10 minutes) all 4 natural uniques were
    built inside a `DropItem` call and outside every nested roll. While
    that happened, `DropUniqueItems`, `ReturnRandomSatanic` and the builds
    outside `DropItem` each rose by 0. The two the owner named were among
    the four.
  - Live 1b built 9 that way and Live 1c 105, with 2 inside the nested
    `DropUniqueItems` roll in each session.
  - Each natural draw build's triple sat on list k (Live 1: 4 of 4; Live
    1b: 8 of 8; Live 1c: 103 of 103), and its tier, field 32, equalled k.
    So list k holds the tier-k uniques.
  - The lookups per build are mostly few. Over Live 1's and Live 1b's 12
    natural draw builds the reads since the last build had a median of 4,
    and over Live 1c's 103 a median of 3. The tail runs to 249.
  - Lookups per call: in Live 1c about 8.8 a call (71988 over 8146 calls).
    Operator kills in Live 1 made 7 a call (276 over 40 calls) and built no
    unique.
- The rarity then picks one of four branches: 6 (Satanic), 9 (Heroic), 7 or
  10 (Angelic or Unholy), and any other value. In the rarity-6 branch an
  entry whose field 32 (the tier) is 5 meets one more test, on protected
  value slot 75. Whether each branch keeps the entry or draws again was not
  read branch by branch. Whether the loop keeps the first entry it accepts,
  or weighs the accepted entries by a computed value and keeps the best, was
  not read either: a local that starts at 100,000,000 and is compared and
  lowered inside the loop hints at a weighing. **Static reading** (2026-10-20,
  ForgePact #166); the keep-or-weigh question is **not established**, and
  ForgePact's Mod live procedure 7 (`draw-reads`, `draw-mode`) is written to
  answer it. If the draw weighs entries, an entry added to list k is not
  picked on c / (L_k + c) of draws, and its own fields (field 28 first) may
  decide whether it is ever picked.
  **Measured** (Mod live 7) for the keep-or-weigh question: the rule's
  answer is `first-kept`. The natural draw builds' median of 4 reads met
  it, and so did Live 1b's below-SS lever, at 1 pick per 3 typed draw builds
  against the 0.13 the rule asks. The lever half rests on 3 builds, so it is
  a weak reading.
  **Measured** (Mod live 7, Live 1b and Live 1c) for the tier-5 test:
  - A pushed rarity-6, tier-5 stand-in is rarely built through the draw.
    Live 1c built 2 SS stand-ins among 105 draw builds at magic find x10,
    both at k 0 to 4 where no natural copy sits, and Live 1b built 0 among
    6 at x1. With s·c = 100 copies pushed on lists of about 221 entries, a
    draw that keeps the first entry it reads would build one on about 0.3
    of draws. Why SS stand-ins are rarely built is **not established**.
  - The probe's `picks=` (47 in Live 1c, 13 in Live 1b) is an instrument
    count, not the draw's picks. It counts any `CreateDefaultParams` call
    in the draw's scope whose sub and b match a pushed triple read since
    the read window was last cleared; it does not compare the class, and a
    normal build does not clear the window. The debugger logpoint on the
    draw's own `CreateDefaultParams` call hit 105 times, equal to the 105
    draw builds and including both stand-ins, so the other 45 counted calls
    ran at a different call site. They are not the draw picking a stand-in
    and sending it back.
  - Both reads of slot 75 were reached, more than once a call. Every logged
    hit carried 75.0, a real, as the logpoint's logged value. Whether that
    is the index argument or the value stored in slot 75 is **not
    established**, and the comparison after the read was not logged, so
    whether the tier-5 test rejects anything is **not established** either.
  - In 28 minutes at x10 no natural rarity-6, tier-5 unique was built
    through the draw.
  - Natural tier-5 builds through the draw did come at k = 5 with rarity 7
    (Angelic, 1) and rarity 9 (Heroic, 2), outside the `angelic=` and
    `heroic=` roll scopes. So list 5 holds those rarities too, and the draw
    builds them itself.
  - **Measured** (Mod live 8): pushed rarity-6, tier-5 stand-ins are built
    through the draw at a high push. With every Mark 1 piece class's SS
    stand-in and Pocket Elf's pushed 400 times a call onto each of the six
    lists, at magic find x10 and then x100, the draw built 9 of them among
    67 unique builds (8 pieces, 1 Pocket Elf; ForgePact's rewrite then made
    each the item). It does not say how often the tier-5 test passes at
    one copy.
- The build follows the draw. In the call list that `GetUniqueRepoStruct`
  call is followed by one `CreateDefaultParams` call and one call to the
  unnamed placement routine (§ 23.8 names `LootGroundCreate` for the ordinary
  roll) before any other build. That is the order of the calls, not a
  reading of the control flow between them. **Static reading** (2026-10-20,
  ForgePact #166). **Measured** (Mod live 7): a debugger logpoint on that
  `CreateDefaultParams` call counted one hit per unique the draw built (4
  of 4 in Live 1, 105 of 105 in Live 1c), and none when 10 uniques were
  placed by name through `DropUniqueItems`.
- A second draw of the same shape reads a ds_list passed as `DropItem`'s
  argument 7 (counting from 0), when that argument is present and passes a
  builtin test. Which builtin was not read, and whether a kill passes a list
  there was not read. It has its own `GetUniqueRepoStruct`,
  `CreateDefaultParams` and placement calls. **Static reading** (2026-10-20,
  ForgePact #166). **Measured** (Mod live 7): most kills pass a list there.
  `DropItem` was always called with 12 arguments, and argument 7 was a list
  on 392 of 497 calls (Live 1), 2682 of 3544 (Live 1b) and 6934 of 8146
  (Live 1c). In Live 1's owner window this draw's `GetUniqueRepoStruct`
  call was reached 49 times, but no unique was built through it: every
  draw-scope build went through the Satanic draw's own `CreateDefaultParams`
  call.
- What else `DropItem` builds: a normal item, through `GetNormalRepoStruct`,
  then `CreateDefaultParams`, then the placement. All three of `DropItem`'s
  `CreateDefaultParams` calls (the Satanic draw's build, the argument-7 list
  draw's build and this normal build) pass three arguments, and each passes
  its class, the third, as a bool rather than a number: the Satanic draw's
  build passes true on its unique path and false on one fallback build of a
  fixed sub and b, the argument-7 build passes a constant true, and the
  normal build a constant false. `CreateDefaultParams` turns that bool into
  the real 1 or 0 it stores as `c` (§ 13.4), so a read of the stored `c` sees
  a number while a read of the argument sees a bool; a number-only read of
  the argument therefore never sees a unique build here. **Static reading**
  (2026-10-21, ForgePact #166, build 498d5885…). **Measured** (Mod live 8):
  over 13457 `CreateDefaultParams` calls in the draw's scope, the third
  argument read as a bool or absent and never as a number. It read true on
  the 69 unique builds and false on 8482 normal ones, and 4906 more normal
  builds passed no third argument, or passed it unset; which call made
  them was not read. On all 13457 the argument's truth agreed with the `c`
  the game stored. ForgePact's first counter, which read only a number, saw
  none of the unique builds in 8342 calls. It calls `LoadDrops`
  (2171) once, and is that script's only direct caller (§ 13.1); drop type
  45 inside `LoadDrops` holds the only direct call of `DropUniqueItems`
  (1424). It calls `DropItemAngelicChance` (1368) once (§ 13.4). **Static
  reading** (2026-10-20, ForgePact #166).
- So a kill reaches `DropUniqueItems` directly only through drop type 45
  (calls through the script table or a method value were not scanned), and
  a kill's ordinary uniques can come from `DropItem`'s own draw without it.
  Live 3's
  four natural uniques with `DropUniqueItems` flat fit that. **Static
  reading** (2026-10-20, ForgePact #166). **Measured** (Mod live 7, route
  `satanic-draw`): an ordinary kill's unique comes from `DropItem`'s own draw
  on `lootListUnique[k]`, as the draw bullet above records. **Measured**
  (Mod live 8): kills do sometimes reach `DropUniqueItems`. In about 40
  minutes of the owner's play in The Devil's Breach (Hell, zone level 276)
  at magic find x10 and then x100, it ran 7 times inside a `DropItem`
  call, over about 2900 outermost `DropItem` calls. The drops workorder's Live 3 saw
  it never run in Act 1 on Hell. What opened type 45's gate there (the
  zone, its level or the magic find) is **not established**.
- Entries added to `lootListUnique[0..5]` during a `DropItem` call reach
  this draw. **Measured** (Mod live 7, Live 1b and Live 1c, ForgePact's
  research lever `mark1probe draws push`).
  - The draw read pushed entries: 1943 times over 971 calls with four
    below-SS stand-ins, 4538 over 2336 with four SS ones, and 14729 over
    8146 in Live 1c.
  - It picked them, and the below-SS gloves stand-in was built at k = 5,
    where no natural copy sits.
  - The lists' lengths were back to 50, 61, 79, 152, 221 and 380 after the
    lever was switched off.
  - **Measured** (Mod live 8): entries the Mark 1 drops and Pocket Elf push
    for each outermost `DropItem` call are built from kills. Every build
    typed on one of those stand-ins (9 of 67 typed builds, at 400 copies a
    call) was rewritten into its item and built, and the lists read 50, 61,
    79, 152, 221 and 380 again afterwards.
- `ReturnRandomSatanic` (3326) draws from `lootListUnique[argument 1]` until
  it finds an entry whose definition matches argument 0, is not hidden and,
  unless argument 2 is set, is neither Angelic nor Unholy, and it returns
  that definition. The byte scan found no direct call site, which is not
  observed: it may be called through the script table or a method value.
  **Static reading** (2026-10-20, ForgePact #166). Mod live 7 counted its
  calls through a count-only hook by name. The count stayed 0 in all three
  sessions, but no positive control for that hook exists, so this is **not
  observed**, never "not called".
- Not observed, never "none": the ghidra MCP's callers, callees and xrefs
  were empty for every function above (the project is a `-noanalysis`
  import), and the MCP shows neither a body nor a disassembly for `DropItem`.
  The decompile index held no earlier record of any of these scripts for
  this build. **Static reading** (2026-10-20, ForgePact #166).

### 13.13 Potions and the Angelic roll

Read on 2026-10-23 for ForgePact #229 (the Gold Inlaid Mysterious Potion,
the game's one Angelic potion, never dropped from the Loot tab's Angelic /
Unholy Drops slider). The means: the hub's ghidra MCP on
`DropItemAngelicChance`, `CreateDefaultParams`, `GetUniqueRepoStruct` and
`DefineItemUniqueConsumable`, plus a read-only byte scan for the slot of
`Controller_obj`'s `lootListUnique` variable. Every reading below is
paraphrased; no listing is reproduced here. Each label says which.
Measured since in ForgePact #229's Live 1 (2026-10-23, capture
`forgepact-229-gold-inlaid-potion-live-1`; research build, slot 14, Hell,
Outskirts of Inoya at zone level 243, one session, Liquor Holster
`{8, 0, 51}` the positive control for each read): the potions' definitions
as the game answers them, their counts in each `lootListUnique[k]`, and the
Gold Inlaid Mysterious Potion's built item, ground label, pickup, use and
save. The reads went through the research build's `angeliclist` and
`angelicprobe pool find|drop` (the guide's Known Limitations item 63).

- **The roll has no item-type rule.** `DropItemAngelicChance` takes an entry
  of `Controller_obj.lootListUnique[5]`, reads its definition and re-picks
  until the hidden flag (base-info field 40) is clear and the rarity
  (field 27) is 7 or 10 (§ 13.4, "The pick"). Nothing in it tests the
  entry's type; the type goes from the entry to the placement unchanged. So
  a potion entry (type 18) that passes those two tests reaches the
  placement call exactly like any other Angelic or Unholy entry; what the
  placement does with a type-18 entry was **not read**. **Static reading**
  (2026-10-23, ForgePact #229). That the potion's own entry passes both
  filters is **measured** (below); the game's own roll picking and placing
  it was **not observed** (offline that roll practically never fires,
  § 13.4, and Live 1 did not force it).
- **The placement's parameters carry no type.** `CreateDefaultParams` takes
  three values (the sub, with a fallback when it is absent, the base index
  and a unique flag) and returns `{j, b, c}`, with no type in it; the roll
  hands it the entry's sub and base, and the entry's type separately to the
  placement. **Static reading** (2026-10-23, ForgePact #229), consistent
  with #74 Live 2's measured `{"b":51.0,"j":0.0,"c":1.0}` for Liquor
  Holster `{8, 0, 51}` (§ 13.4).
- **The repository's potion entries.** `DefineItemUniqueConsumable` fills
  repository type 11 (consumables) only. **Static reading** (2026-10-23,
  ForgePact #229). The type-18 unique entries come from another loader,
  by name `DefineItemUniqueFlask`, whose MCP decompile timed out, so the
  loader itself was not read. The triples `{18, 0, 8}` (Gold Inlaid
  Mysterious Potion) and `{18, 0, 5}` (Elixir of Unworldly Cognition) come
  from ForgePact's `kAngelicBases` table, taken from the Item Editor's
  catalog. **Measured** (Live 1, 2026-10-23, capture
  `forgepact-229-gold-inlaid-potion-live-1`): `GetUniqueRepoStruct` answers
  both triples, read outside any roll. `{18, 0, 8}`: key (base info `"28"`)
  `consumable_gold_inlaid_mysterious_potion`, rarity (`"27"`) 7, hidden
  flag (`"40"`) absent, so the Angelic roll's two filters keep it and the
  ordinary unique roll's (rarity below 7, § 23.4) do not; `InitItemFromJson`
  builds it at rarity 7 too. `{18, 0, 5}`: key
  `consumable_elixir_of_unworldly_cognition`, rarity 9, hidden flag absent,
  so neither roll's filters keep it, and `InitItemFromJson` builds it at
  rarity 9 (Heroic, as HS Offline Tracker's table has it, not the Unholy
  `kAngelicBases` labels it). Both keys match the table's.
- **Where the lists are built.** The byte scan (positive controls: the two
  known readers, `DropItemAngelicChance` and `DropUniqueItems`, two sites
  each) found 59 references to `lootListUnique`'s slot in 17 functions:
  the two rolls, `DropItemHeroic`, `DropItemDebug`, `CreateShrineEffect`,
  `DoCraftResult`, the two merchant grids, `ReturnRandomSatanic`, the gamba
  machine's event and six unnamed functions. One unnamed function, placed
  just after `Controller_obj`'s Create-event closures (that it is the Create
  event is an inference, not a reading), creates the eleven lists (five
  `lootListNormal`, six `lootListUnique`) and fills them in a loop that reads
  unique definitions through `GetUniqueRepoStruct` and normal ones through
  `GetNormalRepoStruct`; another destroys all eleven and sets the variables
  to -1. **Static reading** (2026-10-23, ForgePact #229). The builder does
  not decompile (the MCP timed out at 300 s, a headless decompile at 1800 s
  with the decompiler near 16 GB of memory), and its membership rule sits
  inline in it, so **the rule that decides which entries go into which list
  is not established**. Do not decompile the builder whole again; read the
  lists instead.
- **The potions on the lists. Measured** (Live 1, 2026-10-23, capture
  `forgepact-229-gold-inlaid-potion-live-1`, each sub-list counted for
  entries equal to the whole triple): `{18, 0, 8}`, the Gold Inlaid
  Mysterious Potion, is on `lootListUnique[5]` once and on `[0]` to `[4]`
  not at all, the same pattern as the control Liquor Holster `{8, 0, 51}`
  (§ 13.4). So the list the game's Angelic roll draws from carries the
  potion, and its filters keep it: the game's roll can pick it like any
  other entry. `{18, 0, 5}`, the Elixir, is also on `[5]`
  once and nowhere else, but its rarity 9 fails the roll's filter, so the
  roll re-picks past it. The six sizes read 50, 61, 79, 152, 221 and 380,
  as #74 measured them. That the game's roll then places a type-18 entry as
  an item was **not observed**: Live 1 placed the potion through ForgePact's
  own spawn (next bullet), not through the game's roll. The 48 droppable
  entries § 13.4 counted on `[5]` now match ForgePact's 48 validated
  candidates with the potion among them; that the potion is the one extra
  entry over the old 47 is consistent with this, not checked entry by entry.
- **The potion as an item. Measured** (Live 1, 2026-10-23, capture
  `forgepact-229-gold-inlaid-potion-live-1`, one copy, the local player as
  `self`). Built by `InitItemFromJson` from `{18, 0, 8}` and placed by
  `LootGroundCreateFromItem` (ForgePact's `SpawnAngelicItem`), it became a
  ground item (the `Loot_Ground_obj` count rose by one) at rarity 7, its
  label reading "Gold Inlaid Mysterious Potion | SS" under the owner's loot
  filter. The built item's `itemInfoStruct["28"]` reads the display name
  ("Gold Inlaid Mysterious Potion"), not the repository key, so a line that
  prints it names the item. Hovering the label and pressing F picked it up
  ("[Gold Inlaid Mysterious Potion] Picked up") into the bag grid, not the
  potion slots. Its tooltip there: "Potion", 0 charges out of 1, a 45 s
  flask cooldown, a 15 s effect, Endless Wealth (Magic Find 275%, Gold
  Amount 26%), tier SS, level 1. With 0 charges it could not be drunk:
  neither a right-click in the bag nor its potion-slot key used it. Moved
  into a potion slot, it stayed there through Save & Exit and a reload of
  the character, and came back with 1 charge out of 1; the slot's key then
  drank it, giving a 15 s "Endless Wealth" buff (Magic Find +275%, extra
  gold from kills 26%), and it stayed in the slot as a recharging flask,
  not used up. The same key press drank every charged potion slot at once,
  both times (as seen; not explained). **Not observed:** a second copy, the
  game's own roll placing it, another difficulty or zone tier, co-op, and
  whether the item refills its charge over time rather than on reload.
- **ForgePact's own pool rejected potions before #229.** From the slider's
  first release (v1.3.14) ForgePact's `BuildAngelicPool` threw out every
  `kAngelicBases` row of type 18, with the reason `potion`, before its three
  real tests (the repository key, the hidden flag and the rarity the game
  builds), so neither type-18 row could ever enter ForgePact's own die.
  Nothing else in ForgePact filtered them. This was ForgePact's rule, not
  the game's: the roll above has none. A player's own loot filter can still
  hide a type-18 ground item (§ 18.5). With the rule removed, Live 1
  (2026-10-23, capture `forgepact-229-gold-inlaid-potion-live-1`)
  **measured** the potion validated (`-> ok`), the pool at 48 candidates
  and 10 rejected (nine for the hidden flag, the Elixir for its built
  rarity 9), and the slider at one in one kill dropping it twice in 24
  rolls (24 drops, 0 fails).

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

**How the game rolls the zone: static reading** (the decompiler copy of this
build through the Ghidra MCP, 2026-10-13, for ForgePact #185's tracker; in
our own words, not run):
- `GetSatanicZoneOffline` rolls only when `GetSatanicZoneEligible` says yes.
- `GetSatanicZoneEligible` answers through `IsDifficultyUnlocked`, for a
  value it reads, in one of three cases. Which value it reads was not read.
- When eligible, `GetSatanicZoneOffline` picks one room, by a random index,
  from a fixed list of 40: zones 01-05 of acts 1-8, `Act_01_01` to
  `Act_08_05`, with no act 9, no `_06` zone and no boss or sub-area room. So
  every rolled zone has the `Act_<a>_<z>` shape, which the tracker and HS
  Offline Tracker's producer name `Satanic_<1-8>_<1-5>`.
- `GPV` picks one of two implementations by a global mode value and hands
  each its caller's `self` and `other`. Whether either implementation reads
  `self` was not read, so ForgePact's readers keep the measured shape: the
  local player as `self`.
- **Not established:** what triggers a roll. Callers of
  `GetSatanicZoneOffline` and `GetSatanicZoneEligible` were not observed (a
  `-noanalysis` import leaves the reference table mostly empty, so that is
  not a negative). Live procedure 2 of the toolkit workorder
  `forgepact-185-tracker-zone-fix` puts debugger logpoints on both beside its room
  changes. How many ticks a newly generated act zone runs without a
  `Player_obj`, so without an answer from the zone's readers, is not
  established either (§ 1, "How the local player arrives").

**Measured on a room change and a pin** (Live procedure 2 of the toolkit
workorder `forgepact-185-tracker-zone-fix`, capture
`forgepact-185-tracker-zone-fix-live-2`, 2026-10-14, this build, Sorak, two
travels by `NetworkRoomGoto` called by name with the player as `self`):
- **The act zone's first ticks have no local player.** After the travel from
  `Town_01_rm` to `Act_01_01`, the tracker's zone readers failed twice before
  answering, the last time for want of a local player (`zone-why=no-player`,
  which keeps only the last failure's reason; `zone-unresolved=` 0 to 2).
  Read every 15 ticks, that bounds the player's arrival between 15 and 30
  ticks after the room change; it is a bound, not a measured duration
  (2,482 ms between the two records: an upper bound on when the readers
  answered, which depends on how long the ticks ran during the load, not on
  the poll period alone; at 2,482 ms for at most 30 ticks they ran far
  slower than 60 a second). Between the stat after the fighting and the one
  after the travel back to `Town_01_rm`, three more reads failed, the last
  for want of a local player (633 ms between the travel's records); all 3
  fell after the travel's room change: `name-unresolved=` rose with them,
  and the name is read only while it is owed after a room change. The player's `name` read empty as often
  (`name-unresolved=` in step) and answered with the zone.
- **These two travels did not roll the zone.** Debugger logpoints on
  `GetSatanicZoneOffline` and `GetSatanicZoneEligible` had no hit over about
  4.5 minutes that held both travels, beside a control that kept rising and
  a `NetworkRoomGoto` logpoint that hit once per travel; the store kept the
  pinned `Act_01_01` across both travels and after the pin was released. Not
  observed: a roll beside a `NetworkRoomGoto` travel called by name (n=2,
  the pin on for the first). The game's own travel routes (waypoint menu,
  portal, death, a new game) did not run, so whether one of them rolls is
  not established. What does trigger a roll stays
  **not established**, because no natural re-roll came in the session's
  337 s, so the logpoints had none to catch.
- **A pin with no room change re-points the store and leaves the arrays.**
  `SPV` of the key to `Act_01_01` from town (ForgePact's `satzone pin 1`)
  was read back within 3 s, with the buff and debuff arrays unchanged
  (`[3,21,10]` / `[19,17]`).

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

### 14.4 Chaos Pillars: the tooltip and what shows it

Everything below is a **static reading** of game build `pe-6aaa6779-0cad4fc8`,
made 2026-10-11 for ForgePact #7 and written in our own words, except where a
line says **measured** or **inferred**.

- **Two objects, one tooltip per pillar.** `Chaos_Pillar_obj` (861; parent
  chain `Quest_NPC_Parent_obj` → `Collision_Parent_obj` →
  `Avoidable_Parent_obj`; no children) and `Chaos_Pillar_Tooltip_obj` (862; no
  parent). **Static reading** for the hierarchy. A session counted 18 of each
  in one map: equal counts, **measured** 2026-08-26 on an older build
  ([S10, working recipe](../ForgePact/docs/S10-special-content-notes.md#-calisan-tarif---yytoolkit-2026-08-26)).
  Equal counts alone do not pair them. The one-to-one pairing is the Alarm 0
  reading below (one tooltip created per pillar and kept in that pillar's
  `chaosPillarTooltip`), a **static reading**. Live 1 (below) found all 17
  pillars of one zone each naming an existing tooltip in `chaosPillarTooltip`,
  which fits it.
- **Events.** The pillar has Create, Alarm 0, Step, Draw, Destroy, CleanUp and
  the two mouse events `Mouse_10` (mouse enter) and `Mouse_11` (mouse leave);
  the tooltip has only Create and Draw GUI (`Draw_64`). They are rows of the
  compiled-code table (`gml_Object_Chaos_Pillar_obj_Mouse_10`, …), not named
  scripts. **Static reading.**
- **Create** sets `chaosPillarTooltip` to noone (-4), sets `device`,
  `isHovered` and `isCoOp` to false, and arms alarm 0. **Static reading.**
- **Alarm 0 rolls the pillar and builds its tooltip.** It draws the pillar's
  affixes from `affixPool` (a ds_list) into `affixes`, works out `textHeight`,
  `rarityColor` and seventeen `tooltip*` display values (`tooltipPackSize`,
  `tooltipMF`, `tooltipXP`, `tooltipLootAmount`, `tooltipExtraGold`,
  `tooltipRelic` and the rest), then creates one `Chaos_Pillar_Tooltip_obj` at
  the pillar's own position on the UI layer named by the global `uiLayer`,
  stores it in `chaosPillarTooltip` and copies those values onto it. The mods
  therefore live on the pillar and are copied, once, onto its tooltip. It also
  sets `device` true when the player's input device reads as a gamepad
  (`GetPlayerDevice` answering 2), or, with `isCoOp`, when a protected global
  flag read as local co-op is set (which flag that is was not established).
  **Static reading.**
- **The hover gate is the tooltip's built-in `visible`.** Mouse enter sets it
  true and mouse leave sets it false, each only when `chaosPillarTooltip` is
  not noone. The tooltip's own code never writes it. Its starting value is an
  object property rather than code, inferred to be false because the box shows
  only on hover. **Static reading.** The mouse half is **measured** in Live 1
  (below): hovering a pillar turned its tooltip's `visible` to 1 and moving
  away turned it back to 0.
- **`activated` holds a key, not the state.** In Create the pillar asks the
  anti-cheat extension's `InitNewVariableFast` for a new record in the native
  protected-value store (§ 5.8), keeps the record's key in `activated`, and
  stores the starting value under that key through the extension's
  `SetVariable` (inferred to be false from the constant it passes). CleanUp
  frees the record with `FreeVariable`. The pillar keeps the same kind of key
  in `rarity`, `affix`, `activateTimer`, `magicFind01`..`06`,
  `lootAmount01`..`06`, `xZe` and `zrmb`. The game reads the state through the
  extension's `GetVariable(key)`: the pillar's interaction closure (the first
  of its four Create closures, its `m_TalkToNPC`) does nothing once the record
  is true, so a used pillar cannot be talked to again, and the Step takes its
  own branch on it (below). `DialogChaosPillar` reads the pillar's `rarity`
  record; at the lower rarities it calls the pillar's `m_Activate` (the third
  closure) at once, at the higher ones it first runs an inventory-item
  operation, a cost whose item was not established. `m_Activate` sets
  `speakCooldown` and sends a client effect carrying the pillar's x and y; the
  handler of that effect, which presumably sets the record true and starts the
  fight, was **not read**. **Static reading.** So
  `variable_instance_get(pillar, "activated")` returns a key, the same trap as
  a creator's `spawnPack` (§ 11.2) and a monster's `damage` (§ 13.7), and the
  state is the record, which ForgePact reads by calling the game's script
  `PC_GetVariableGMLWrapper(key)` by name after checking the key is a finite
  whole number in [0, 262144): the store holds 262,144 records and a -1 key
  faulted the game (§ 5.8). That route is **measured** on creators and
  monsters (§ 11.2, § 13.7); the extension's own `GetVariable` does not
  resolve from the plugin (§ 20.5). Reading a pillar's record through it, and
  the record turning true when a player activates the pillar, are now
  **measured** (Live 2, below); which code writes it stays **not
  established**.
- **Step.** When the pillar's protected `activated` record reads true, the
  Step takes its own branch (the tremble: `trembleTimer`, `angle`, `x2`) and
  leaves the tooltip alone. Otherwise, and only while `device` is true, it
  rewrites the tooltip's `visible` every step: true while the local player
  (in co-op, either player) is within 180 px (`distance_to_object`), false
  otherwise. With mouse input the Step never touches `visible`, so only the
  mouse events do. **Static reading**; the gamepad branch has not been
  measured.
- **The tooltip's Draw GUI** draws nothing unless its own `visible` is true.
  Then it maps its room x/y through view camera 0 into GUI space (offset from
  the view's origin, scaled by GUI size over view size, floored) and draws the
  box of mods there, so the box sits over its pillar wherever the camera is.
  **Static reading.**
- **Destroy** destroys the tooltip and sets `chaosPillarTooltip` to -1, not
  -4, so a reader must treat both as "no tooltip". **Static reading.**
- **Two negatives, "not observed".** A byte scan for code that uses the
  `chaosPillarTooltip` variable found its uses only inside the pillar's own
  Create, Alarm 0, Step, mouse enter, mouse leave and Destroy; a scan for code
  building a reference to object 862 found only Alarm 0's creation. As the
  second scan's positive control, the same scan run for the gamba machine
  (4644) found four sites. That four is this research's own count, not a
  figure § 20.2 states: § 20.2 names the machine's creation in
  `gml_Script_ClientCreateEffect` and notes that `Zone_State_Buffer_obj`'s
  Create closures also name it. A reference built another way, or a
  `variable_instance_*` access by string, would not show in either scan.
  `isHovered` is written in Create and read nowhere the scan sees. **Static
  reading**, not a measured negative.
- **Measured (Live 1, 2026-10-11)**, mouse play, the installed game, the
  first zone (`Act_01_01`) with ForgePact's Chaos Pillar rate at ×10, read
  through ForgePact's research probe and its event counter on
  `gml_Object_Chaos_Pillar_Tooltip_obj_Draw_64`:
  - 17 pillars, each with an existing tooltip, and `device` 0 on every one.
  - The raw `activated` variable read as a bool true or a number above 0.5 on
    all 17 untouched pillars (the probe printed only that, not the number).
    That fits a store key and does not fit "this pillar was used".
  - Hovering a pillar showed its box: the tooltip's `visible` read 1, the Draw
    GUI count rose (106, then 706 on the next read), and a screenshot showed
    the box of mods under the pillar's name.
  - Moving the cursor away hid it: `visible` read 0 and the count stayed flat
    (1311, then 1311). With the cursor parked away from every pillar the box
    was not drawn: `visible` 0, the count flat at 0, and no box in a
    screenshot. So while `visible` is false the tooltip's Draw GUI code does
    not run at all.
  - `Controller_obj`'s depth was -12998, and every tooltip's was -13001, on
    layer `Layer_UI_Parent_1`.
  - **Inferred** from those depths, not measured: GameMaker draws a lower
    depth later, so the tooltips' Draw GUI runs after `Controller_obj`'s,
    where ForgePact's HUD hook runs (§ 8.3), and a `visible` written from
    that hook is drawn the same frame.
- **Measured (Live 2, 2026-10-11)**, the same zone, rate and instruments,
  mouse play, 35 pillars:
  - **The raw `activated` is a key whose record reads false before any
    interaction.** On all 35 untouched pillars `activated` held a distinct
    whole number between 174773 and 175959, and the record behind it, read
    through `PC_GetVariableGMLWrapper` by name, answered 0. The same pillar's
    `rarity` and `activateTimer` keys sat two below and one above it. As the
    read's positive control, the `rarity` records answered 1, 2, 3, 5 and 6
    across the pillars, and one reading 3 was the pillar the game's own box
    named "Rare"; `activateTimer`'s record read 216 on every untouched
    pillar. The getter itself answered the same non-zero number as `GPV` for
    `gDataProtected[177]` that session.
  - **The player's activation turns the record true.** Clicking a pillar
    (rarity 1) opened the game's dialog ("Activate the pillar?", asking for no
    item at that rarity), and choosing its yes option made the record answer
    1 within 2 s, under the same key; every other pillar's stayed 0. In the
    same read the `activateTimer` record had fallen from 216 to about 122,
    `trembleTimer` from 14.4 to 7.2 and `speakCooldown` from 0 to about
    -0.29, while `rarity`, `questState`, `isDiscovered`, `image_index` and
    `sprite_index` were unchanged.
  - **The tooltip survived that read, then the pillar went.** Within 2 s of
    the activation the pillar's tooltip still existed (with `visible` 0); a
    few seconds later the pillar was gone from the room (35 pillars, then
    34), its place taken by the fight's pentagram. One activation was
    observed, so whether the game always removes an activated pillar this
    way is not established.
  - With `visible` written true from ForgePact's HUD hook and no hover, the
    box was drawn (the Draw GUI count rising, the box in a screenshot), so a
    write there is drawn. Whether it is drawn the same frame (the depth-order
    inference above) is still **not measured**: with mouse input nothing
    writes `visible` false between frames, so a write drawn one frame late
    would look the same.

ForgePact's **Always show Chaos Pillar mods** switch (`pillartips`, off by
default, mouse play only) is built on this reading: once a frame, from its HUD
hook, it sets `visible` on the tooltips of on-screen pillars whose protected
`activated` record reads false, the way mouse enter would, and clears it again
when they leave the screen or the switch goes off. What is live-measured: the
mouse hover gate, mouse leave's clear, the depths, and that the raw
`activated` variable is not the state (Live 1); the switch showing every
on-screen, untouched pillar's box without hover, hiding it off screen and on
activation, the record turning true when a player activates a pillar, and the
game's own hover back once the switch is off (Live 2). What is not: which
code writes the record, the draw order of `Controller_obj`'s Draw GUI and the
tooltips' within a frame (inferred from the depths), the game's hover on an activated pillar with the
switch on (the pillar was removed first), and gamepad play, where the Step
rewrites `visible` every step and which ForgePact does not support or test
(that branch stays a static reading).
The argument, the instrument and the live results are in
[the Chaos Pillar tips research](../ForgePact/docs/chaos-pillar-tips-research.md).

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
| A plugin DLL whose global `std::thread` is still joinable when the game exits | `std::terminate` while `ExitProcess` destroys that DLL's globals (the other threads are already gone): a WER report at close, `ucrtbase.dll` `0xc0000409`, fast-fail 7 (`abort`). HS-Offline-Tracker 0.1.2's producer (`36608aa0…`, the build ForgePact shipped through 2.2.x) does it, measured: 9 of the 10 dumps Windows kept on 2026-09-25/26 show it, the game's own exit path under it, and a plain `CloseMainWindow` at the main menu does it too. Tracker 0.1.1's and 0.1.3's producers keep the same global `std::thread` (static reading of their source, not measured). A game started from a tool running under Git Bash inherits error mode `0x3` (`SEM_NOGPFAULTERRORBOX`) and aborts without a dump or an event: read the exit code. In-world graceful stops too (ForgePact #201, measured from dumps and WER reports, 2026-10-13): all ten dumps Windows kept on 2026-10-12/13, nine of them `hs_stop_game` stops (most with a character in the world), raise fast fail 7 at `ucrtbase!abort` from `terminate`, called from `HSOfflineTrackerProducer.dll`'s exit-time destructor under `LdrShutdownProcess`; the two 2026-10-08 batch closes left WER reports with the same bucket and the producer loaded. Measured live (#201, 2026-10-13, captures `forgepact-201-exit-c0000409-live-1` and `-live-2`): with the producer loaded, an in-world close and a close after the pause menu's Save & Exit both read `0xC0000409` with a dump naming the producer, and so did a main-menu close; with it held aside, a main-menu close, an in-world close with every mod off, a close after Save & Exit and an in-world close with `lootann`, `stashmoveall` and `frameprof` on (its worker thread still running) all read `0x00000000` and left no dump. So the producer is the only module seen aborting a graceful close; a vanilla or ForgePact-free game was not run. **The avoidance, HS-Offline-Tracker 0.1.4's producer (Tracker PR #8):** the thread is kept out of every exit-time destructor instead of being joined first. It is held on the heap behind `ExitSafeThread`, a trivially destructible owner that frees it only after a successful join, and only a real `ModuleUnload` attempts that join (bounded at 2 s). Why no join can come first is a *static reading* of the Tracker's `aurie-producer/include/hsot_aurie/exit_safe_thread.h` and its account of Aurie, not measured: Aurie runs no unload routine when the process is ending, and a join under the loader lock would wait for a thread that cannot exit. A module that meets this abort needs the same shape, not a join added to its unload. Measured (ForgePact #185, capture `forgepact-185-tracker-mod-live-1`, 2026-10-13): with the 0.1.4 producer three graceful closes read `0x00000000` and left no dump, after an old-build control close in the same session aborted with a dump naming the producer. The cells, every Tracker producer's hash and which ForgePact release ships which build are in the #185 follow-on and ForgePact's pin table | [Item Truth memory research](../ForgePact/docs/item-truth-memory-research.md#the-crash-of-2026-09-26-013627), [graceful stop research](../ForgePact/docs/graceful-stop-exit-research.md#results), [#185 follow-on](../ForgePact/docs/graceful-stop-exit-research.md#follow-on-the-fixed-producer-pinned-forgepact-185) |
| `RoomGoto` into `Act_01_06` from code | crash | §22.7 |
| `PC_GetVariableGMLWrapper` on a far-out handle (id 999999) | crash | §22.8 |
| A gold amount mistaken for a handle (call not recorded) | crash in the anti-cheat module | §22.8 |
| `EnemyGiveExperience` with no argument | crash | §22.8 |
| A parsed struct held only in C++ `RValue`s across frames | freed by the runner's GC; the next frame crashes | §22.8, §5.9 |
| `WM_CLOSE` to YYToolkit's console window | the game ends with 0xC000013A, no normal save | §22.5 |
| A number of 100 trillion (1e14) or more, NaN, or a negative of a million or more handed to `num_compressSteam` (its `SteamCompressNumber` text does not fit 8 bytes) | the game ends with `0xC0000409`, fast fail 8 raised in `PAS_Steam_GMS_x64.dll`, which no in-process handler sees (**measured** for a positive value, ForgePact #230 Live 2, 2026-10-20, capture `forgepact-230-damage-crash-live-2`: 9.9999e13 passed (measured), and the game ended after a value of at least 1.025e14 was handed in; the trace logs only the first value of each decade, so the fatal value lies in [1.025e14, 1e15) and is not itself measured, and the 1e14 limit is the static reading; dump `code=0xc0000409 subcode=8 raised-in=PAS_Steam_GMS_x64`; NaN and the negative band a **static reading**) | §8.7 |
| A ground monster's path search while the hero is sealed in | about 20 s at 3 fps for a 20-monster wave; `pathFailed = true` avoids it | §22.7 |

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
| `"2"` / `"3"` | the footprint in grid cells, width / height; `GetItemSize` reads them (§ 23.2) |
| `"11"` | the display sprite (§ 21.7, § 23.5) |
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

**The game's rarity colour table** (ForgePact#228). **Static reading**
(2026-10-23, local Ghidra project, our own words): `GetRarityColor(code, a,
b)` answers one colour per code, as GameMaker's blue-green-red integer, and
white for any other code. `GetItemColor` gives an ordinary equipment item's
name `GetRarityColor` of its `"27"`; other item kinds have branches of their
own. Codes 4, 8 and 11 have colours but no item carrying them was observed.

| Code | Rarity | Colour |
|---|---|---|
| 1 | Common | 16777215 (#FFFFFF); 10982553 (#9994A7) when `a` is non-zero, what `a` means not established |
| 2 | Superior | 12745262 (#2E7AC2) |
| 3 | Rare | 698851 (#E3A90A) |
| 4 | not observed | 215270 (#E64803) |
| 5 | Mythic | 15406513 (#B115EB) |
| 6 | Satanic | 1447638 (#D61616) |
| 7 | Angelic | 10092542 (#FEFF99) |
| 8 | not observed | 1892620 (#0CE11C) |
| 9 | Heroic | 9764608 (#00FF94) |
| 10 | Unholy | 7224024 (#D83A6E) |
| 11 | not observed | 7844807 (#C7B377) |

The online drop announcement does not always use this table: its Angelic
text is a fixed 10681599 (#FFFCA2), not 10092542 (§ 8.6). Also in
[`hs-game-sdk/curated/loot_announcement_measurements.json`](../hs-game-sdk/curated/loot_announcement_measurements.json)
(`rarity_colours`).

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
  the information view, which adds each rolled line's range (` [45-75]`).
  It was taken to add skill descriptions too, but a gear item's skill-grant
  description shows with and without it (§ 16.12, measured).
  With the gameplay option `Show Item Information` on (Options ›
  Gameplay), both ALT states draw the information view: Zealot's Book of
  Prophecy read the same in both, its ranges (` [31-36]`, ` [7-12]`,
  ` [10-20]`) and its grant description shown in both. **Measured
  2026-10-22** (ForgePact's Mark 1 Stats live 1, `desc-view`). With the
  option off: not observed.
- **How a range is drawn** (**measured 2026-10-22**, from Mark 1 Stats live
  1's Item Truth journal, whose tooltip records carry each drawn text with
  its stat, colour and position): `DrawInventoryStatsNew` draws a rolled
  line's range as a third `draw_text` after the value and the label, the
  text ` [lo-hi]` in colour 8421504 (grey), left-aligned at the label's
  right edge, with the whole line (value, label, range) centred on the
  tooltip. Zealot's Book's line 203 drew `+11` at x 1816, its label at 1859
  and ` [7-12]` at 2214. The header draws `Defense: N`, then the item's own
  Defense (key 154) in white as ` [80]`, then a grey ` [lo-hi]`; a sockets
  row draws `Sockets (N)` and a grey ` [lo-hi]`. A fixed line draws no
  range (Pitfiend's Thorn, Wall of the Legion). An item placed by a mod
  over a set item's base (ForgePact's Mark 1 pieces) drew the base piece's
  header and sockets ranges, not its own, and no range on its own rolled
  lines.
- **Where a set item's or a unique's line ranges come from** was not read.
  Generated affixes carry theirs in `itemStatStruct` keys `"10"` to `"14"`
  as `[stat, min, max, tier]` (§ 16.3), but across every Item Truth journal
  on the owner's machine none of 141,676 rarity-6 records carries such an
  entry (**measured 2026-10-22**, replan 1 of ForgePact#166's playtest). So
  writing them onto a rarity-6 item makes a state the game never makes.
  [Mark 1 Stats live 1 results](../ForgePact/docs/mark1-set-research.md#stats-live-1-results)
- An unidentified item draws `Unidentified` and no stat lines.
- The tooltip prices a Key, Tarot, Material, Socketable or Relic at 0 and
  then shows "Item cannot be sold" (`item_cannot_be_sold`); the type rule
  and its labels are in § 13.10 "The types the game will not buy".
- All 344 direct call sites of `DrawInventoryStatsNew` in the build Ghidra
  imported (§ 19.7 names its hash) lie inside `DrawInventoryItemV2`, one after
  another. A fixed run of calls that long is the tooltip's list of known stat
  lines, not a loop over the item's own stats. **Static reading** (2026-10-13,
  byte scan of the imported executable; blind to calls through the script
  table or a method value).
- Before that run, one conditional branch jumps past all of it. The code
  just before it reads the tooltip surface fields (`inventorySurfaceData`,
  `inventorySurfaceWidth`, `usedThisFrame`) and the item's identity fields
  (`itemRegion`, `itemAccount`, `itemTimeStamp`, `itemType`,
  `itemDataHash`). So the tooltip most likely keeps a drawn surface per item:
  the stat calls run on a frame where that item's tooltip is not cached, and
  later frames draw the cached surface and may make no stat call at all.
  **Inference** from the slot names around the branch (2026-10-13), not a
  reading of its logic and not measured. If it holds, the unidentified
  item's missing lines are decided inside the run, not by a branch around it.
- Hovering an item, the first tooltip pass made the stat calls (ForgePact's
  stats hook counted 333) and every later pass of the same hover made none,
  for an item with stats (Gabriel Wings) and for one with none (Pocket Elf)
  alike. A debugger logpoint on a middle one of the 344 sites logged once
  per hover, while a control logpoint logged throughout, and stayed flat with
  the pointer on an empty cell; the first and the last site never logged.
  **Measured** (2026-10-13, ForgePact's flight charms Mod live 2, `tip-calls`,
  `dbg-stat-wings` and `dbg-stat-elf`). So the run is made once per hover,
  also for an item without stats, which agrees with the cache inference
  above; the branch's logic itself is still not read.
  [Mod live 2 results](../ForgePact/docs/flight-charms-research.md#mod-live-2-results)
- The call runs on every frame the tooltip shows, while the tooltip's text,
  the type line under the name included, is drawn on the first frame of a
  hover only. A hook on the call armed for one item counted hundreds of
  calls per hover and kept counting with the pointer resting on the item
  (about 24,600 over three minutes), while the hook's swap of the type line
  and its own rows counted 1 per hover; the swapped type line showed on
  every frame, so the cached copy holds it. **Measured** (2026-10-21,
  ForgePact's Mark 1 Mod live 9, `tip-rehover` and `tip-ground`). Counting
  each call by whether the game drew in it, one call per hover drew and the
  later ones drew nothing (49 such calls in a 1 s hover, 2,190 more over a
  5 s rest), and a debugger logpoint on a direct `DrawInventoryStatsNew`
  call inside the pass rose by the same 1 on each of three hovers (ground,
  bag, worn) and stayed flat over the rest while a control logpoint logged.
  **Measured** (2026-10-21, Mark 1 Mod live 10, `tip-ground`, `tip-cached`
  and `dbg-stat-site`). The same site also logged once for other items'
  tooltips between those hovers.
  [Mod live 9 results](../ForgePact/docs/mark1-set-research.md#mod-live-9-results),
  [Mod live 10 results](../ForgePact/docs/mark1-set-research.md#mod-live-10-results)

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
  function.) What `LootExplosion` does with those two calls, putting a Chaos
  Tower floor's held loot back on the ground, is in § 16.14.
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

### 16.12 A set piece's tooltip, and a skill grant's description

- **Measured** (Item Truth's tooltip captures on the owner's machine,
  `%LOCALAPPDATA%\Hero_Siege\itemtruth\journal\*.ndjson`, game build
  `pe-6aaa6779-0cad4fc8`, recorded 2026-09-27 to 2026-10-21; each capture
  holds one tooltip pass's `draw_text` calls with colour, x and y, and its
  `DrawInventoryStatsNew` calls): 230 tooltips of set pieces, whose type line
  reads `Satanic Set <type>`. `UI_Inventory_Tooltip_obj` drew those of items
  in the bag or worn, `UI_Pickup_Tooltip_obj` those of items on the ground.
  The set's part of the tooltip comes after the item's own stats and
  sockets, in this order:
  - a gap of two rows, then the set's bonus lines. They are stat lines like
    any other, through `DrawInventoryStatsNew` with format 5 (a percent) or
    6 (a flat number) and style 8 or 9 (§ 16.6). A line drawn active is
    7844807 (RGB 199,180,119, a pale gold), one drawn inactive 4210752
    (RGB 64,64,64, a dark grey);
  - a gap of two rows, then the set's name, centred, in 7844807;
  - one centred row per piece of the set, in the set's own order and the
    hovered piece among them: 65280 (green) when the player wears that
    piece, 4210752 when not. No count of worn pieces is drawn;
  - a gap of two rows, then the footer.
- **Measured**, how the colours split over those 230: in the 191 with no
  piece name green, every bonus line was 4210752. Of the 39 with at least one
  piece green, 19 drew one or more bonus lines in 7844807.
- **Measured**, the row pitch: every stat call in these captures reported a
  row height of 28 at the capture's scale, where § 16.6 measured 30 and
  ForgePact's forged rows draw at 30.
- **Measured**, a skill grant's line and the description under it (same
  captures): the Heroic Shield `Celestial's Authority` draws `+1` and `to
  Celestial Might` as stat 203's line (`DrawInventoryStatsNew`, format 3,
  style 8) in 18687 (RGB 255,72,0, an orange). Under it comes the talent's
  description, the `talent_desc_celestialMight` text, in 8421504
  (RGB 128,128,128, a grey), wrapped over two centred rows, and then a
  parameter row: its name (`Conversion `) in 7844807 and its value (`80%`) in
  white. All 200 captured tooltips with a stat-203 line drew the description
  under it. The item editor's own static analysis sends that description
  through `DrawSkillDescription`
  (`hero-siege-item-editor/hs_stat_semantics_s10.json`, its grant block).
- **Measured**, a gear item's grant description outside the ALT view
  (2026-10-21, ForgePact's Mark 1 Mod live 9, `desc-plain`): a worn Zealot's
  Book of Prophecy, line `+11 to Satan's Mark (White Mage)`, drew the skill's
  description under the line without ALT and with ALT held, the tooltip the
  same in both. Both of its screenshots show the rolled ranges, which § 16.6
  puts in the information view, so whether the plain view was among them is
  **not established** (§ 16.13).
  [Mod live 9 results](../ForgePact/docs/mark1-set-research.md#mod-live-9-results)
- **Measured**, the width an item's description or lore row wraps at
  (Item Truth's captures, 182 journals of the same build): the game draws
  those rows with `draw_text_ext` at a line separation of -1, and the width
  it passes is not one constant but follows the tooltip's box. 1,176
  captured tooltips carry such a row, at widths from 478 to 1160; 504 is
  the commonest (382 bag or worn tooltips and 437 ground ones), and 622
  belongs to a few wide boxes (Elixir of Death, Ghostly Potion, Celestial's
  Authority). Which instance variable holds a box's width was not read
  (§ 16.6 names `inventorySurfaceWidth` beside the cache branch, unread).
- **Static reading** (2026-10-21, the hub's ghidra MCP, in our own words):
  - `GetSetName` (`gml_Script_GetSetName`, a method that `GetSetNames`
    defines) turns a set index from 1 to 70 into that set's localized name,
    one of the `*_setname` keys of `translationsItem.csv`; any other index
    gets a fallback string.
  - `DefineSetPieceRequirements` fills `global.requiredPieces` at indices 1
    to 70 with 2, 3 or 4, one value per set. What reads the array was not
    read.
  - `gml_Script_s_SetItemInfo` builds the reference to one set piece out of
    three fields, `itemType`, `weaponType` and `itemId` (slot names taken
    from `tools/decomp_index.py slot-name`). So the game names a set's
    pieces as unique-repository triples, and an item built as a base item
    (as ForgePact's Mark 1 pieces are) is no such triple.
  - `GetSetInformation` sorts a set name into one of 70 cases.
  - `DrawInventoryItemV2Func` makes `DrawInventoryItemV2` (§ 16.6's tooltip
    pass) a method value, and the MCP's decompiler gives up on that method's
    body at its flow limit, so the pass itself was not read.
- **Not established:**
  - the rule that draws a bonus line active: per line, and at which count of
    worn pieces;
  - how the pass decides that an item belongs to a set (how an item names
    its set), and how it counts the worn pieces;
  - the 28 against 30 px row pitch: which one a live tooltip uses at the
    player's scale.

ForgePact's Mark 1 set draws its own set block in the pieces' tooltips from
these measurements. The pieces' description wraps at 478, the narrowest
width the game itself used in any captured tooltip, after Mod live 9 found a
row wrapped at 622 running past both edges of a piece's box. At 478 the
description took four rows, and every row of the block sat inside the box,
no letter cut and none over another row or the footer, in a ground, a bag
and a worn piece's tooltip, with the bonus line grey and gold. **Measured**
(2026-10-21, Mod live 10, `tip-layout`):
[Mark 1 research, Phase 5](../ForgePact/docs/mark1-set-research.md#phase-5-the-set-tooltip-and-the-pieces-art),
[Mod live 10 results](../ForgePact/docs/mark1-set-research.md#mod-live-10-results).

### 16.13 Set bonuses, item stat keys and the item description font

Written for ForgePact#166's second playtest (2026-10-22), when the Mark 1
pieces got rolled stats and the set a bonus at 2, 3 and 4 pieces. In our own
words; nothing here quotes the game's code.

- **Static reading** (2026-10-22; the owner's headless decompile of the set
  scripts, the hub's ghidra MCP, and one headless `FindCallers.java` byte
  scan whose positive control, `CheckTalentUse` called from
  `PlayerMovement`, was found):
  - **`GetSetInformation`** takes a set's name and a line number from 1 to 5
    and returns one bonus line per call: the set's class id (-1 for none),
    the value, the id the stat dispatcher `ReturnSpecificStat` takes, a draw
    style (8 or 9) and a format (5 a percent, 6 a flat number). A line the
    set does not use returns nothing, and no line carries a count of pieces.
    The owner's positive controls: Pit Fighter's and Zealot's five lines
    decode to exactly what Item Truth's tooltips of those sets show, and
    Zealot's line 1 is dispatcher id 64, movement speed, at 25%.
  - `DefineSetPieceRequirements`' one value per set (§ 16.12) equals the
    set's piece count for 59 of the 70 sets: plausibly the pieces for the
    full set, an inference. Line counts do not follow piece counts (Sheep
    King has five lines and three pieces), so "one line per extra piece" is
    ruled out for those sets.
  - **Who reads set lines** (byte scan, direct calls only):
    `GetSetInformation` is called from `LoadSpecificStat` (one site) and
    from two unnamed functions (five sites each; one of them also calls
    `DrawSkillDescription` 23 times, so it is plausibly the tooltip pass's
    body). `LoadSpecificStat` is called from `RunItemEquipped` (two),
    `GuildPerkActivate` (eight), `JewelcraftingAdd`, `MiningAdd`,
    `PickupRelic` and one unnamed function, and from no `Stat*` getter. So
    the game's stat aggregation reads set lines, on equip-time paths.
  - **The dispatcher ids a set bonus can answer, and their getters**
    (`ReturnSpecificStat`'s case map, the 2026-10-04 reading, § 7.5): 2
    `StatAllSkills`, 21 `StatArmor`, 22 `StatVitality`, 36 `StatMaxLife`, 38
    `StatLifeReplenish`, 45 `StatLifePerKill`, 64 `StatMovementSpeed`, 92
    `StatDefense`, 97 `StatPhysicalDamageReduction`, 161
    `StatAllResistances`, 162 `StatFireResist`, 163 `StatColdResist`, 164
    `StatPoisonResist`, 165 `StatLightningResist`, 167 `StatArcaneResist`.
    These are the dispatcher's ids: not item stat keys (the table below),
    and not `hs-game-sdk`'s `StatId`, whose numbering is neither (hub #546).
  - Each of `StatMaxLife`, `StatDefense`, `StatArmor`, `StatAllResistances`,
    `StatFireResist`, `StatLifeReplenish`, `StatPhysicalDamageReduction`,
    `StatAllSkills` and `StatLifePerKill` has exactly one direct caller,
    `ReturnSpecificStat`. So every direct-call consumer of those stats goes
    through the dispatcher, and an answer changed there reaches them. A call
    through the script table or a method value is invisible to the scan:
    such consumers are **not observed**, not excluded.
  - **`DrawSkillDescription`**, the script that draws a skill grant's
    description: it reads three font globals, `font_item_stats`,
    `font_item_stats_small` and `font_item_stats_smaller`, and `hud_res`. It
    sets the colour to grey 128,128,128 (8421504) at alpha 1 and the font to
    `font_item_stats_small`, or to `font_item_stats_smaller` when an
    optional argument asks for it, and hands the text to a rich-text object
    (`inventorySurfaceRichText`, through its `SetText`, `SetRichTextFont`,
    `CalculateRowWidths` and `Draw` methods). That the builtin it gives the
    font to is `draw_set_font` is inferred from the argument. Its body reads
    no key, input, view, compare or option value: any view rule would sit in
    its caller.
  - `DrawSkillDescription`'s only direct caller found is
    `DrawInventoryItemV2`, the tooltip pass (§ 16.6), at 23 sites. So the
    game draws a grant description only inside an item's tooltip pass.
    Whether that pass skips those calls outside the information view was
    not read: the pass's body is about 1.6 MB of code, past what the
    decompiler finishes.
  - **The `alwaysShowInfo` option.** The game keeps a gameplay option of
    that name. A scan of its slot's references found it used only by the
    startup name table, the gameplay options screen's Create event and the
    game's global function table, and not directly in `DrawInventoryItemV2`
    (**not observed**: how its value reaches the pass was not read). If it
    is on, a tooltip shown without ALT is the information view too.
  - **`SetCooldown`** keeps the active cooldowns in two lists in the game's
    protected data, `cooldownList` and `cooldownProcList`, one branch each
    (§ 7.9). Reading by name whether a talent is on cooldown is not
    established.
  - `GetSetInformation`'s cross-references through the MCP: one data
    reference. **Not observed**, not a negative: the import was made with
    `-noanalysis` (AGENTS.md, the Ghidra section).
- **Measured** (Item Truth's captures, 184 journals on the owner's machine,
  build `pe-6aaa6779-0cad4fc8`, 2026-09-27 to 2026-10-21; what a capture
  holds is in § 16.12):
  - **The item stat keys**, against `hero-siege-item-editor`'s
    `hs_stat_semantics_s10.json` (schema 1, generated 2026-09-02) and the
    labels the game drew:

    | key | name | drawn as (label, format, style) |
    |---|---|---|
    | 154 | Defense | the header `Defense: N`, no stat call |
    | 29 | Enhanced Defense | `Enhanced Defense`, 2, 8 |
    | 48 | to Vitality | `to Vitality`, 3, 8 |
    | 173 | to All Resistances | `to All Resistances`, 2, 8 |
    | 201 | to All Skills | `to All Skills`, 3, 8 (the class from key 21) |
    | 170 | Faster Hit Recovery | `Faster Hit Recovery`, 2, 8 |
    | 52 | to Life | `to Life`, 3, 8 |
    | 59 | Life After each Kill | `Life After each Kill`, 3, 8 |
    | 51 | to All Attributes | `to All Attributes`, 3, 8 |
    | 55 | Replenish Life | `Replenish Life`, 2, 9 |
    | 159 | Physical Damage Taken Reduced by | `Physical Damage Taken Reduced by`, 2, 9 |
    | 20 | Sockets | the `Sockets (N)` text row after the stat lines |
    | 25 | Increased Movement Speed | `Increased Movement Speed`, 2, 8 |
    | 294 | Skill Movement Diminish decreased by | `Skill Movement Diminish decreased by`, 2, 9 |

  - **Key 294**, translation key `stat_movement_diminish`: 72 captured
    tooltips drew it under that label, on items carrying 10 to 100. By its
    label it reduces the cast's movement slowdown (§ 7.8); it is not a
    movement-speed stat, and it does not express "-50% Movement Speed".
  - **A set line as the game draws it**: `DrawInventoryStatsNew` with the
    value as its argument 3 and the label as its argument 4, format 5 or 6,
    style 8 (value first, signed) or 9 (label first), row height 30.
    Captured: `Defense` 6/8 at 350, 475 and 500; `to All Resistances` 5/8;
    `Replenish Life` 5/9 at 25; `to All Skills` 6/8; `to Life` 6/8 at 235 to
    1250; `Physical Damage Taken Reduced by` 5/9 at 15, 20 and 30; `Movement
    Speed` 5/8 at 25 (Zealot's line 1). A negative value is drawn signed
    (`-125% to All Resistances`). The words a row reads: `+500 Defense`,
    `+35% to All Resistances`, `Replenish Life 25%`, `+5 to All Skills`,
    `+750 to Life`, `Physical Damage Taken Reduced by 20%`, `-50% Movement
    Speed`.
  - **The order of an item's stat lines in a pass** (a pass calls every
    stat line it knows in one fixed order, § 16.6): of the keys above, 29
    comes first, then 201, 48, 51, 52, 170, 59 and 173. At least 50 other
    drawn ids came after 173, so a format 2 or 3 call always follows the
    last of an item's own lines.
  - **After the sockets row**, in 614 passes of socketed items, only a set
    item's bonus calls (format 5 or 6) ever followed; a non-set item makes
    no stat call after its `Sockets (N)` row.
  - **The description font is smaller.** A skill grant's description
    (Celestial's Authority, 2026-09-28) was drawn glyph by glyph in 8421504,
    its rows 26 px apart at about 10 px a glyph, where the same pass's stat
    rows were 28 px apart at about 13.6 px a glyph.
  - **The natural seed bound**: 485,148 item records carry a definition `a`
    from 0 to 999,981,452, none at or above 1,000,000,000. 684 sit in
    777000 to 799999, ForgePact's own built-ins among them, and ForgePact's
    `angelicdrop` placements draw their seeds from 100,000,000 to
    999,999,999, also below that bound.
- **Static reading** (replan 1, 2026-10-22, the hub's ghidra MCP):
  `StatFireResist` itself calls `ReturnSpecificStat` at ten sites; which
  ids it asks for was not read.
- **Measured 2026-10-22** (ForgePact's Mark 1 Stats live 1, slot 14
  "Sorak", White Mage, in town; Mark 1's `ReturnSpecificStat` consumer
  records each id's last local call as original and answer, and debugger
  logpoints at the getters' own addresses counted their calls beside a
  positive control on `PlayerMovement`):
  - **An answer changed at the dispatcher reaches what the player sees.**
    Answering id 36 with its original plus 750 moved the HUD's maximum life
    between 4901 and 5651 as the answer was switched; id 2 read 28 to 33
    and id 161 266 to 301 under the same answers, and with the answers off
    every id read its original again. Taking a piece off, the HUD maximum
    had not moved 0.4 s later and had moved about 7 s later, after the
    game's next `StatMaxLife` read. This measures the dispatcher route the
    byte scan above found; the claim that every consumer goes through it
    stays scoped to the consumers seen.
  - **The getters are read periodically, not every frame.** `StatMaxLife`
    about once a second idle (10 in 10.26 s) and `StatAllResistances` about
    twice a second (20), both faster around an equip change (16 and 48 in
    the 15 s after wearing a piece). `StatFireResist` logged no call over
    about seven minutes in town while the control logged more than 25,000:
    **not observed**, plausibly asked only on events the town did not
    produce (a hit taken, the character sheet; not established).
  - **Ids not asked in town**: 92 (Defense), 97 (Physical Damage Taken
    Reduced), 162 to 165 (fire, cold, poison, lightning) and 21 had no
    local dispatcher call in the whole session, the set equipped and
    unequipped and the automation casting. Not observed, not "never asked".
  - **Id 38** (life replenish) was asked when the automation cast Healing
    Zone (its original 159 then 242, against 46 before), and not after a
    piece was worn with no skill cast.
  - **Id 167 (arcane resistance) follows id 161.** Its original read 339
    with Mark 1's 161 answer off and 374 with it on, 35 more, the size of
    that answer. So `StatArcaneResist` plausibly takes the all-resistance
    answer through the dispatcher (an inference from one id; 162 to 165
    were not asked).
  - **The description font is smaller in our tooltips too.** A description
    drawn through the game's `font_item_stats_small` had capitals about
    17 px high against the bonus lines' 22 px at 2560 × 1440, the same
    letter height and line pitch as Zealot's Book of Prophecy's grant
    description in the same session.
  [Mark 1 Stats live 1 results](../ForgePact/docs/mark1-set-research.md#stats-live-1-results)
- **Measured 2026-10-22, Stats live 2** (ForgePact's Mark 1, slot 14
  "Sorak", White Mage, in town and in Outskirts of Inoya; the same consumer
  records, `statask` asking the dispatcher itself with the local player as
  self, and debugger logpoints at `StatDefense` and
  `StatPhysicalDamageReduction` logging each call's self beside a
  `PlayerMovement` control):
  - **Id 162 (fire) did not move with Mark 1's 161 answer.** With the
    answer on (161 266 to 301), id 162 read 83 with the answer off and 83
    with it on (`statask`, the dispatcher asked with the local self); 164
    also read 83 (83 -> 83, in Outskirts, from a call made around the
    switch's change). Whether `StatFireResist` adds 161 is **not
    established**: 83 on two elements against 161 = 266 fits a cap clamping
    the value, which no read separated (no read below a cap, no negative 161
    answer). 163 and 165 were not asked. Id 167 (arcane), which read 339 and
    so is not at 83, followed 161 by +35 in Stats live 1 (above).
  - **Who asks for 92 and 97.** While the debugger was attached (the sheet
    windows in town and the Outskirts window), only our own `statask` asked 92 or 97 with the local player as self. Each opening of
    the talent screen (T) made two fresh instances ask, 92 twice and 97
    three times, and in Outskirts one instance asked 92 about every 344
    control hits and 97 in pairs; neither was the player. Measured; who those
    selves are is the static reading below, and whether an enemy's hit asks
    with the player as self is not observed (the session separated no hit
    from Soul Spurn's own life drain).
  - **The game asks for the maximum life with the local self** inside both
    windows, the sheet's and Outskirts': id 36's record read 4901 -> 5651
    with Mark 1's answer on (in town it is asked about once a second, Stats
    live 1). The talent screen itself
    showed Life 4901 while the HUD read 5651: the sheet's number does not
    come from a call with the player as self.
  - **Id 37's answer reaches the HUD's maximum mana**: answered 940.8, the
    HUD read `941 / 940.80`.
  - **Id 42's answer reaches the regen.** Forced to 0, mana held at 1428 for
    5 s after a spend (a 10 s key spend took 924 in the same window, the
    control). At its own value R = 257, mana rose 676 in 2.98 s (0.883 a
    second per unit, read from HUD crops); answered 128.581, about half, it
    rose 338 in 2.97 s, half as much.
  - **A skill fired through `TalentUseClass` from outside the input gate**
    charges no mana (0 spent over 10 s, against 1219 by the same skills'
    key presses) and skips the game's own pre-cast refusals: Mana Orb, whose
    key press the game refused in Stats live 1 for a reason beyond its
    cooldown (plausibly while its orb lives; not established), reached 7
    instances at once.
  - **Faster Cast Rate's id 106 moves on its own**: it read 55, 85 and 106 in
    one session with no change of gear, so a before-and-after read seconds
    apart does not isolate a change (`statadd castrate 100` read 55 -> 158).
  [Mark 1 Stats live 2 results](../ForgePact/docs/mark1-set-research.md#stats-live-2-results)
- **Static reading after Stats live 2** (2026-10-22, ForgePact's Mark 1
  replan 4: who else asks the dispatcher for Defense, id 92, and Physical
  Damage Taken Reduced, id 97). Sources: the hub's ghidra MCP (it decompiled
  `GetMyPlayer`; `StatDefense` and `StatPhysicalDamageReduction` timed out),
  and local byte scans of an import copy of `Hero_Siege.exe` (build
  `498d588550d8`) for direct `call rel32` sites into the dispatcher with a
  constant id, and for each script's direct callers. The scans and their
  outputs are local research material on the owner's machine, outside any
  repository (`%USERPROFILE%\tools\hs-decomp\issue166\` and
  `%USERPROFILE%\tools\hs-decomp\mark1-playtest2-replan2\`), and hold names
  and counts only. **Positive controls**, same scans: the constant-id scan
  listed id 64's askers exactly as § 7.8 lists them (the player's Step,
  `StatTotalDamage`, `StatAttackDamage`, `StatMagicSkillDamage`,
  `TalentsSamurai`, `Mercenary_obj`'s Alarm 5), and the caller scan found
  `CheckTalentUse` called from `PlayerMovement`. A call through the script
  table, a global or a method value, or with a computed id, is invisible to
  them: an asker they did not find is **not observed**, not absent.
  - **Who asks for 92 and 97 with a constant id** (static reading): 92 is
    asked by `StatMaxLife` (one site), by `StatDefense` itself, and by the
    collision events of `Player_obj` and of `Mercenary_obj` with
    `Enemy_Damage_Parent_Projectile_obj`. 97 is asked by `sc_hurt` (one
    site) and by `Mercenary_obj`'s collision events with
    `Enemy_Damage_Parent_obj` and with `Enemy_Damage_Parent_Projectile_obj`
    (two sites each).
  - **A hit on the player asks with the player as self** (static reading,
    then inference): `sc_hurt` is called directly from `Player_obj`'s two
    collision events with enemy damage and from `CA_playerHurt`, and
    `PlayerTakeDamage` from the same two events. A collision event runs on
    the instance it belongs to, and a called script keeps its caller's self
    (GameMaker's rule, not read in this build), so the player's own Defense
    and PDR are asked with the player as self when an enemy strikes it.
    **Measured in part** (Stats live 3, below): four hits on the player each
    ran `sc_hurt` with the player as self and then asked 97 with the player
    as self; no 92 ask with the player as self came with them (not
    observed; whether those hits were projectiles was not read).
  - **The mercenary asks for itself** (static reading): `Mercenary_obj`'s
    Alarm 5 asks 36, 37, 64, 2, 8 and more at 18 sites, and its melee
    collision asks 97 at two. That fits what Stats live 2 measured outside
    town, a non-player self asking 92 about once every 344 control hits (a
    periodic alarm) and 97 in pairs, while the character played (slot 14,
    Sorak) has a mercenary (§ 7.6). That this self is a `Mercenary_obj` is
    **measured** (Stats live 3, below).
  - **The talent screen asks with its own objects as self** (static reading
    and measured): the T screen is the character sheet (Player tab: Base
    Stats, Offensive, Defensive, Summoned, Statistics; it scrolls).
    `UI_Button_Talent_Player_obj`'s Alarm 0 calls the dispatcher at 15 sites
    with no constant id and its Draw GUI at 27 with constant damage ids;
    `UI_Talent_Screen_Attribute_obj`'s and `UI_Talent_Screen_Allocate_obj`'s
    Alarm 0 at about 30 each (127, 68, 69, 155, 32 and 33 as constants, the
    rest computed); `Player_Talent_Tooltip_obj`'s Create method at 34. No
    `UI_Mercenary_*` object calls the dispatcher directly (not observed).
    Stats live 2 measured two fresh instances asking 92 twice and 97 three
    times on each opening of the sheet, and the sheet showed Life 4901 while
    the HUD read 5651 with Mark 1's id-36 answer on: the sheet asks for the
    player's stats with a self that is not the player. Which object asks
    for Base Stats' Life is **measured** (Stats live 3, below):
    `UI_Talent_Screen_Attribute_obj`, for 36, 92 and 97 alike.
  - `Load_Player_Stats_obj`'s Step calls the dispatcher at 226 sites, all
    with constant damage ids (2, 3 to 10, 79, 194, 355, 361, 561 to 565),
    none of them 36, 92 or 97 (static reading).
  - **Argument 0, the stat's unit** (static reading): the dispatcher hands
    its first argument to `GetMyPlayer` (seen in id 102's case), and
    `GetMyPlayer` given an undefined argument takes a global value and walks
    the `Player_obj` instances for the one whose player number matches.
    `StatDefense`, `StatPhysicalDamageReduction` and `StatMaxLife` read
    `playerBuff` (63, 181 and 85 references) and test `instance_exists` (9,
    28 and 13). So the unit a stat is computed for may be argument 0 rather
    than self; **not established**. Measured in Stats live 3 (below):
    argument 0 read 1 on every non-player asker recorded, the player's sheet, the
    mercenary and summons alike, so it does not tell them apart.
  - **The HUD's numbers** (static reading): `DrawHud` draws text through
    `draw_text` (32 references) after reading values through the protected
    store (`gDataProtected`'s `GetVariable`, 45 references) and `pSt` (8).
    That its life and mana `current / max` texts are among them is
    **measured** (Stats live 3, below: the text it draws agreed with the
    dispatcher's 36 and 37).
  [Static reading after Stats live 2](../ForgePact/docs/mark1-set-research.md#static-reading-after-stats-live-2)
- **Measured 2026-10-23, Stats live 3** (ForgePact's Mark 1, slot 14
  "Sorak", White Mage, in town and in Outskirts of Inoya, Mana Orb and Soul
  Spurn off the bar; debugger logpoints at `StatDefense`,
  `StatPhysicalDamageReduction` and `sc_hurt` logging each call's self
  beside a `PlayerMovement` control; Mark 1's recorder naming each
  non-player asker's object and argument 0; life and mana read in process
  from the text `DrawHud` draws):
  - **When an enemy strikes the player**, `sc_hurt` runs with the player
    as self and the player's 97 is asked with the player as self, once per
    hit (four hits). The player's 92 was not asked with the player as self
    on those hits (not observed). Life read full before and after, so
    whether those calls dealt damage was not read.
  - **The other self outside town is the mercenary.** `Mercenary_obj`
    asked 92 and 97 (69 and 14 times, against the logpoints' 67 and 14 for
    that self); summons' and pets' passives (`Legion_Skeleton_Passive_obj`,
    `Legion_Skeleton_Archer_Passive_obj`, `Spider_Passive_obj`,
    `Zombie_Passive_obj`) asked 36 with the player's values; `Companion_obj`
    and `Mercenary_obj` asked 64. Argument 0 read 1 on every non-player
    asker recorded (the player's own calls' argument 0 was not recorded).
  - **The character sheet's askers.** On its Player tab
    `UI_Talent_Screen_Attribute_obj` asks 2, 21, 36, 37, 38, 42, 64, 92, 97,
    103, 106, 161 to 165 and 167, and `UI_Button_Talent_Player_obj` asks 2;
    the sheet's Base Stats Life and its Defensive tab's Defense and Physical
    damage reduction equal what the dispatcher answers those asks.
    `UI_Talent_Screen_Allocate_obj` and `Player_Talent_Tooltip_obj` were not
    seen asking. The sheet's own Mercenary tab asks for the mercenary's
    stats through the same `UI_Talent_Screen_Attribute_obj` (and id 2
    through `UI_Button_Talent_Player_obj` and `Load_Mana_Costs_obj`), so an
    answer keyed on that object reaches the mercenary's page too.
  - **The HUD's life and mana text** matches the dispatcher's 36 and 37
    maxima, and follows a spend (mana 3341 to 1937 over a 10 s key hold).
  - **The replenish unit**: with id 42 at its own 140, mana rose 122.417 a
    second, 0.874 a second per unit (read in process; Stats live 2's HUD
    crops read 0.883). With 42 answered 92.96 it rose 87.37 a second, within
    8% of that unit's prediction. Read on the drain side, the two windows'
    difference (S7 minus S8) is 0.745 a second per drained unit, the value
    ForgePact's `kMark1ReplenishUnit` adopts; the readings disagree, and
    § 7.10 infers that the regen tick's rounding up explains it.
  - **A replenish below zero drains.** With 42 forced to −140 from 1428 of
    2352, mana fell 518 in 4.2 s, −124.131 a second: the game's regen
    applies a negative replenish, it does not stop at zero.
  - **Faster Cast Rate's 106** read 54, 158 and 54 in one command file
    around `statadd castrate 100` and back to 0: +104, not +100.
  [Mark 1 Stats live 3 results](../ForgePact/docs/mark1-set-research.md#stats-live-3-results)
- **Measured 2026-10-23, Stats live 4** (ForgePact's Mark 1, the same
  character and instruments, Y left empty, all four pieces worn and the set's
  switch on, in Outskirts of Inoya with the mercenary still hired; it was
  not sent away: the agent session's permission classifier refused the
  click on "Discharge Mercenary", not the game):
  - **When an enemy strikes the player** (four hits), `sc_hurt` runs with
    the player as self and each hit is followed by an ask for the player's
    97 with the player as self, as in Stats live 3; this time with
    `bonusread` reading 97 21->41 in the same window.
  - **The player's 92 was asked with the player as self** once in the
    struck window (`bonusread` read 92 7056->7556 there), not next to any
    of the four hits (window-relative line 3035 against 6633 to 6749).
    Which code asked was not read: the static reading above lists
    `StatMaxLife` (one site) and the player's collision with an enemy
    projectile as constant-id askers, and cannot see a computed-id one;
    whether any hit was a projectile was not read.
  - The logpoints read each call's self, not the answer it got; life read
    full throughout, so whether the set's numbers changed the damage the
    hits dealt was not read.
  - **Another self asked 92 and 97 again**, the same self as
    `Mercenary_obj`'s 92 and 97 asks by count: from the recorder's reset
    on arrival in Outskirts, 31 `df` and 8 `pd` lines with that self
    against `Mercenary_obj`'s 31 asks of 92 and 8 of 97, all left as the
    game answered them.
  [Mark 1 Stats live 4 results](../ForgePact/docs/mark1-set-research.md#stats-live-4-results)
- **The talent screen's page** (ForgePact's Mark 1, Amendment 8,
  2026-10-23):
  - **Measured** (Stats live 3, `merc-page`): on the talent screen's
    Mercenary tab the rows ask the dispatcher with the same objects as on
    the Player tab (`UI_Talent_Screen_Attribute_obj`,
    `UI_Button_Talent_Player_obj`), argument 0 read 1 on both pages, and
    the originals were the mercenary's own (36 12527, 37 742, 92 5114, 97
    86, the numbers `Mercenary_obj`'s own asks read; 42 read 31, not the
    player's 140, and no `Mercenary_obj` 42 ask was recorded). So neither the asker's
    object nor argument 0 tells the sheet's two pages apart.
    [Mark 1 Stats live 3 results](../ForgePact/docs/mark1-set-research.md#stats-live-3-results)
  - **Static reading** (the hub's ghidra MCP decompiled
    `UiATalentsPlayer`, `UiATalentsMercenary` and `close_talents`; in our
    own words): the screen's top tabs are UI actions, and each page is its
    own screen object. The Player tab's action does nothing when a
    `UI_Talent_Screen_obj` already exists; otherwise it closes the talent
    screens and creates a `UI_Talent_Screen_obj`, passing on the old
    screen's local and online player. The Mercenary tab's action does the
    same with `UI_Mercenary_Talents_obj` and then sets up the mercenary's
    talent buttons on it. `close_talents` destroys every instance of
    `UI_Talent_Screen_obj`, `UI_Incarnation_Board_obj` and
    `UI_Mercenary_Talents_obj`. So the page on show is whichever screen
    object has an instance: the player's page is an instance of
    `UI_Talent_Screen_obj` and none of `UI_Mercenary_Talents_obj`. That T
    opens the screen as a `UI_Talent_Screen_obj` is inferred from Stats
    live 3 (T opened on the Player tab), not read. The Hero and Ether tabs
    (`UiATalentsIncarnation`, `UiATalentsEther`) were not read.
    `UiAMercenaryDischarge` (sending the mercenary away) has one data
    reference through the MCP: where its button sits is **not observed**.
  - Mark 1 answers a talent-screen asker only when, read at that call,
    `UI_Talent_Screen_obj` counts at least one instance and
    `UI_Mercenary_Talents_obj` none. That this keeps the Mercenary tab at
    the game's values is **measured** (Stats live 4, `merc-page`,
    `page-back`): on the Mercenary tab every talent-screen ask read answer =
    original on the mercenary's numbers (36 12527, 92 5114, 97 86, 42 31),
    and back on the Player tab 36 read 4901->5651 again. Live 4 measured
    that effect, not the mechanism: that the page on show is whichever
    screen object has an instance stays the static reading above.
  [Mark 1 static reading after Stats live 3](../ForgePact/docs/mark1-set-research.md#static-reading-after-stats-live-3),
  [Mark 1 Stats live 4 results](../ForgePact/docs/mark1-set-research.md#stats-live-4-results)
- **Not established:**
  - which line the game lights at 3 and at 4 pieces for its own sets (the
    one measured case: with 2 pieces counted, Zealot's Prophecy's first line
    is lit, 37 captures);
  - whether ids 162 to 165 take the all-resistance answer (id 161) (162
    and 164 sat at 83 with it on and off, possibly a cap), and what 167
    does differently (Stats live 1 and 2, above);
  - whether key 294 feeds the dispatcher's id 199, the cast slowdown the
    gate asks for (§ 7.7, § 7.8);
  - whether the game hides a grant description outside the information
    view, and so whether § 16.12's `desc-plain` saw a plain view at all
    (Stats live 1 found `Show Item Information` on, which makes both ALT
    states the information view, § 16.6).

ForgePact's Mark 1 set writes its pieces' stats under the item keys above
and gives its set bonus as dispatcher answers of the ids above:
[Mark 1 research, the 2026-10-22 playtest](../ForgePact/docs/mark1-set-research.md#the-2026-10-22-playtest-stats-cast-priority-and-held-input),
[Playtest static reading](../ForgePact/docs/mark1-set-research.md#playtest-static-reading).

### 16.14 The Chaos Tower's loot burst: a floor's drops wait for its end

Every claim in this section is a **Static reading** (2026-10-23, local Ghidra
project, the build the decompile index labels `498d588550d8`, our own words)
unless it says measured, inference or not established. **Measured** marks
what ForgePact #227's Live procedure 1 showed (2026-10-23, capture
`forgepact-227-chaos-tower-announce-live-1`, the research doc's Live
procedure 5; research build sha256 `a21409cb…9fa3`, slot 14 "Sorak", Outskirts
of Inoya at Hell, `Chaos_Tower_Floor_01_rm`), read through ForgePact's
`lootannprobe burst` and `lootann stat` and the owner's own watch of the
screen. That session ran one floor; a bag drop on a floor and the debugger's
`LootExplosion` and burst-window `LootGroundInit` logpoints were not run
(x64dbg paused the game on its own first-chance C++ exceptions during the
floor's fight and was detached), so those parts stay **not observed live**.

- **Measured: a floor collects its drops.** On the first floor
  `Controller_obj.lootExplosionList` read as a reference to an existing
  ds_list (`ds_exists` true) whose `ds_list_size` started at 0 and rose by one
  for each new ground item: by 4 for the floor's natural drops before any
  placement, by 1 in the very frame a placed Heroic item was put on the
  ground, and again for later kills. Each entry's `itemInstance` gave the
  item's identity key, and the natural drops' structs and the placed item's
  read with the list memory on had been built through `CreateItemNew` in
  that frame or the one before (`burst-fresh` rose with `burst-listed`).
  That the ground item leaves the floor at that moment was not watched and
  stays the inference below.
- **Static reading: what is collected.** `LootGroundInit`, which every new
  ground item passes through (§16.11), has a branch for the Chaos Tower. It
  applies when the room's name starts with the tower's prefix (the same test
  `IsChaosTower` makes) or when a protected value, `gDataProtected[12]`
  (§5.1), reads true; the meaning of that protected value is **not
  established**. Two rooms are excepted: `Chaos_Tower_Boss_1` (137) and
  `Chaos_Tower_xLobby` (148) keep their drops on the floor. And the branch
  applies only while the flag behind `Controller_obj.lootExplosionGiven`
  reads false.
- **Static reading: what is held.** In that branch the new ground item does
  not stay on the floor. The game builds an `s_LootExplosionData` struct with
  two fields, `itemInstance` (the item struct itself, a reference rather than
  a copy) and `isPlayerDrop`, and appends it to
  `Controller_obj.lootExplosionList`, a plain ds_list read directly. That the
  call after the append destroys the ground instance is **inference**: the
  same runtime routine destroys a dialog's instance elsewhere. One item-kind
  test can exempt an item from the branch; which kinds it exempts was not
  read and is **not established**. Nothing tests `isPlayerDrop` before the
  append, so an item the player drops from the bag on a tower floor is
  collected as well (a bag drop on a floor is **not observed live**: Live
  procedure 1 never got to drop one).
- **Static reading: protected keys.** `Controller_obj.lootExplosionGiven` and
  `Controller_obj.lootExplosionGold` each hold a protected-store key, not the
  value itself, the same pattern as the monster values of §13.7: reading the
  variable directly returns the key. **Measured:** `GPV` of
  `lootExplosionGiven` (the route `gatestats` uses) read `0` while the floor
  was collecting and `1` once the floor had ended. A direct read of either
  variable was not taken, and `lootExplosionGold` was not read.
- **Static reading: the burst.** `LootExplosion` first sets
  `lootExplosionGiven` true, drops the gold the floor held, and then, for each
  list entry, calls `LootGroundDrop` around a given point (a new
  `Loot_Ground_obj` whose `itemInstance` is set to the entry's item struct,
  with no `CreateItemNew` for that item) and then `LootGroundInit` on the new
  ground item with a second argument of `true`, and finally clears the list.
  `LootGroundDrop`'s own body also calls `LootGroundInit`; whether both calls
  run for one item is **not established**.
- **Measured: the burst lands the held items.** When the floor ended ("Floor
  Cleared"), the list read `size=0` and the given flag `1`, and both placed
  items were on the ground near the character. Each carried the same
  `itemTimeStamp` it had when it was listed, and no `CreateItemNew` had built
  it in that frame or the one before. The struct that landed is the listed
  one, not a copy (**measured**, Live procedure 1): ForgePact's `via=burst`
  needs the landed item's key, which it derives from the item struct's object
  pointer, to equal a key it kept when the entry was listed, and the list
  held that struct alive in between, so its pointer could not have been
  reused by another struct; B's `announce via=burst` and `burst-landed=12`
  are such matches. ForgePact's `LootGroundInit` detour saw each landed item twice:
  two `lootann decide:` lines per stamp, and 12 burst landings for the 6
  entries the reader kept. That fits both `LootGroundInit` calls running for
  one item, but which two calls they were is **not established**: the
  `LootExplosion` logpoint was not run, so that `LootExplosion` is the
  routine that ran stays the static reading above.
- **Static reading: who bursts it.** `LootExplosion` has two direct callers
  (found by a byte scan for call sites, with positive controls, since the MCP
  callers table was empty): the closure SDK-named
  `gml_Script_anon@1312@gml_Object_Spawn_Next_obj_Create_0`, which reads
  `chaosTowerFloorFinished`, `chaosTowerIsLastFloor`, `chaosTowerFloor`,
  `chaosTowerFloorList`, `nextFloorType` and `nextFloorNumber` (so the burst
  comes when a floor is finished), and `WormholeGiveReward`. Whether a
  Wormhole reward uses the same held list is **not established**. That the
  burst comes at a floor's end is **measured** (above); which caller ran is
  not.
- **Static reading: the reset.** `Controller_obj`'s closure `anon@16838`
  clears `lootExplosionList` and resets `lootExplosionGold`,
  `chaosTowerFloor`, `chaosTowerSpawnZone`, `chaosTowerStarted`,
  `chaosTowerBossState`, `lootExplosionGiven` (to false) and
  `chaosTowerRift`. That it is what `m_ChaosTowerReset` holds (§14.3) is
  **inference**, as is the S10 notes' earlier-build `anon@16294` being the
  same closure.
- **Static reading: not the cause.** `EnemyDestroyChaosTower` applies the
  tower's death effects and makes no item call. The tower's reward, near
  `Chaos_Tower_NPC_obj`'s code, gives an item through `DropItemHeroic` and a
  drop table; in which room is **not established**.
- **Measured (2026-10-23, capture `forgepact-227-chaos-tower-announce-live-1`):
  what ForgePact's creation guard does with it.** The guard (§16.11's last
  bullet) passes a ground item only when the game built its struct through
  `CreateItemNew` this frame or the last. A tower floor's drop is built
  through `CreateItemNew` when it first drops and is listed; the item that
  reaches the ground at the burst carries the same struct's stamp, minutes
  later, with no new `CreateItemNew`. A Heroic item placed with the fix's list
  memory off (the rule before #227) was decided `held-bag-drop` at the burst,
  and the owner saw no line for it; one placed with the memory on was decided
  `announce via=burst`, and the owner saw its red `SERVER: Sorak found
  <item>` line (the session's screenshot came a minute later, after the line
  had faded). The burst came at the end of a 42 s freeze the debugger caused.

[loot announcements, Chaos Tower (#227)](../ForgePact/docs/loot-announcement-research.md#chaos-tower-227)

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
  beyond the label (gamepad navigation, for example; that `navBbox*` is the
  hover and highlight box is measured since 2026-10-08, § 8.1), and whether the game
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
- How the rate reaches that roll (read 2026-10-11, build `498d588550d8`, for
  ForgePact #197, § 21). `DropGems` runs only after `LoadDrops`' outer gate
  passed for the dying source: the monster's `chances[6]` (45 on the sampled
  monster, `hs-game-sdk/curated/drop_types.json`) against a die whose ceiling
  lives in `gDataProtected`. Inside, it reads category 15's repository entries,
  `GetDropRate` and a `gDataProtected` member, floors a value and rolls.
  `GetDropRate`, a method of the item base definition
  (`gml_Script_GetDropRate_anon_55737_s_ItemBaseDefinition_DefineStructs`
  (1058), a closure name that moves with every patch, §5.3), answers
  `droprate.base`, replaced by a per-place field where the entry carries one and
  the room matches: boss dungeons, Chaos Tower, Niflheim, rifts, Ruby, Sheep,
  specials and ubers. **Static reading.** Whether `DropGems` gives each
  socketable exactly 1 in its rate or picks by weight is **not established**,
  and no magic-find stat name appears in either body (**not observed**, not a
  negative). The Gem of Incarnation (`socketable_gem_of_incarnation`, class 15,
  `b` 136) carried info key `"31"` = 10,000 on every one in the local drop
  records (`bp_ipc\itemdrops.jsonl`, **measured**); with measured gem bases of
  9,000 and 11,000 (§13.2), 10,000 looked like its `droprate.base`; the live
  read below says otherwise.
- The Gem of Incarnation's `droprate.base` read 9,000, not the 10,000 its info
  key `"31"` carries, and a built Gem of Incarnation's `itemSprite` read
  undefined. **Measured** (ForgePact #197's Live procedure 1, 2026-10-11,
  research build).
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
- Which test reads an item's own tier (`itemInfoStruct["32"]`, §16.3) is
  **not read**. `LootFilterAffixTierVisible` walks the affix slots "10".."14"
  and reads each slot's own affix tier, not the item's tier. The
  `m_LootFilter` closure itself (the middle of Create's three by role) did
  not decompile within 220 s. Its dispatcher sibling was read and only
  dispatches. What was read around it: the menu's per-type tier action
  (`UiALootFilterTypeTier`) walks five positions, 0 to 4, and sets or clears
  one bit per position in a per-type number, and `LootFilterBit(n, k)` answers
  bit k of n. So the filter keeps a five-position tier mask per item type,
  which fits the five tiers C to SS; that a position is the item's tier less
  one is an inference, not read. **Static reading** (2026-10-20, ForgePact
  #166, workorder `forgepact-166-mark1-set-drops`, item `tier`). Mark 1's
  pieces are written SS (5) by their dressing for this reason.
- An item written rarity 6, tier 5 shows past a filter that shows SS items:
  in ForgePact's Mod live 6 (2026-10-20, `filter-shown`, pass) a Mark 1 Boots
  placed at rarity 6, tier 5 showed its ground label `Mark 1 Boots | SS`
  under the owner's own filter, with no `lootshow`, and Mod live 5 read
  `Tier SS` in its tooltip (`tier-ss`). Its control, a vanilla tier-5 item
  with no affix lines (`filter-control`), was not observed in either
  session, because no by-name call placed one; a pass needs no control.
  That the tier mask's position is the item's tier less one stays an
  inference. **Measured**
  ([Mod live 6 results](../ForgePact/docs/mark1-set-research.md#mod-live-6-results),
  [Mod live 5 results](../ForgePact/docs/mark1-set-research.md#mod-live-5-results)).
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
  owner's account, 2026-10-03; 19.5 measured that the jump ends near the
  cursor, up to a maximum length.
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
  **Measured.** During that blocked walk, 6252 `place_meeting` calls naming
  an object outside the collision family ran unanswered, beside
  `InstancePlaceTallest`'s 1944 (jump research Live 1,
  [the "Walking stayed blocked" result](../ForgePact/docs/jump-scenery-research.md#live-1-results)).
  **Measured** for the count; which of them, if either, holds the walk is
  **not established**.

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
  lets it cross: 125 px, about 50 px short of the open-ground jump. **Measured.**
  That session did not record where the cursor was, so why the crossing jump
  ended shorter was not established there; 19.5 measured that a jump's length
  follows the cursor distance, which fits both lengths.
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
  walkable map's edge is **not observed**. What marks that edge in this room
  (invisible wall instances, on its south side) is measured in § 19.11.

[Mod live 1 results](../ForgePact/docs/jump-scenery-research.md#mod-live-1-results)

### 19.5 The v2.2.1 hotfix sessions

What the v2.2.1 hotfix's first live session (ForgePact #206) measured about
the game on 2026-10-09, on the shipped ForgePact 2.2.0 player plugin, slot 14
("Sorak"), in `Town_01_rm` and in `Act_01_01` (the Outskirts of Inoya).
Curated entries J16 to J21. The second live session (2026-10-10, the 2.2.1
player build, same character, `Town_01_rm` and `Act_01_01` again) added
curated J22 to J27. Positions are `menulayout Player_obj`'s `gui=`
reads, which are room coordinates; the operator converted a screen point to
the room as room = view origin + screen ÷ 2 (`menulayout`'s `view=`, a
1280 × 720 view under a 2560 × 1440 GUI).

- **A jump ends near the mouse cursor, not at a fixed length.** On open
  ground in town, from (912.0, 822.0) with the cursor at (912, 922), 100 px
  away, the player ended at (911.0, 910.8): 88.8 px, about 11 px short of the
  cursor. In `Act_01_01`, from (2031.8, 3966.0) with the cursor at (2131.5,
  3916.0), 111.5 px away, the player ended at (2129.8, 3909.7): 113.0 px,
  about 6.5 px from it. **Measured.** The second session repeated the town
  jump and ended at the same point, (911.0, 910.8) (J24). The length follows
  the cursor distance up to a maximum. **The maximum, measured**: from
  (912.0, 822.0) with the cursor at (912, 1122), 300 px away, the player
  moved 246.3 px to (911.2, 1068.3), 53.7 px short of the cursor (J25), so
  this character's longest jump is about **246 px**, from one jump. How it
  depends on Jump Power is **not measured** (Jump Power was not read).
  19.4's 175 px open-ground jump and 125 px crossing fit the same rule with
  the cursor at different distances; that session did not record its
  cursor, so for it this is a reading.
- **`mouse_x` / `mouse_y` read in room coordinates.** Read by name as
  built-in variables through ForgePact's `GetBuiltin`, they gave the room
  point the mouse had been moved to within 1.2 px on each axis (the reads are
  whole numbers), on four aims in two rooms (J22). **Measured.** For a cursor within the jump's maximum, the
  jump ends within about 11 px of that point (J23, J24); beyond it the jump
  stops at the maximum (J25, 53.7 px short). Whether the game itself takes the target from `mouse_x` / `mouse_y`
  or from an aim value of its own is **not established** (`skillsLeap` does
  not decompile in the unanalysed import). `device_mouse_x` was not read.
- **`Player_obj` gets a new instance id on a room change.** 261723 in
  `Town_01_rm`, 297089 in `Act_01_01` after walking from the Town of Inoya
  into the Outskirts of Inoya; again in the second session, 261723 in town
  and 306593 in `Act_01_01` after taking the town waypoint (J26).
  **Measured.** Anything keyed on the player's instance id is new in every
  room.
- **`Act_01_01`'s room size changes between visits.** `room_width` ×
  `room_height` read 18272 × 8704 on 2026-10-09 and 15296 × 12960 on
  2026-10-10 (J18, J26). **Measured.** A position in the Outskirts of Inoya
  does not carry over to another visit.
- **Outdoor scenery.** In `Act_01_01`, a jump beside a large tree with the
  cursor beyond it (at (1901.5, 3867.5), 163.3 px from the take-off) did not
  move the player (0 px), as 19.2's town prop; a jump beside a rock with the
  cursor beyond it went past the rock, from (1916.2, 4115.9) to (2059.9,
  3991.9), 189.8 px. Both with the mod off. **Measured.** So a rock does not
  necessarily stop a jump while a large tree does; the props were the owner's
  choice and are not identified by object. Whether the tree blocks through
  the five builtins of 19.2 was not reached in that session (the 2.2.0 mod
  refused the jump itself).
- **A large tree outdoors blocks through the five builtins of 19.2.** In the
  second session, beside another large tree in `Act_01_01` at (10640, 6965)
  with the cursor 199 px east past it, a jump with the mod off moved 0 px;
  with the 2.2.1 mod answering the player's blocked family queries "no
  collision" (1133 answers), the same jump moved 197.7 px toward the cursor
  and ended on open ground (J27). **Measured** for that tree; the tree is
  not identified by object.

[Hotfix live 1 results](../ForgePact/docs/jump-scenery-research.md#hotfix-live-1-results);
[Hotfix live 2 results](../ForgePact/docs/jump-scenery-research.md#hotfix-live-2-results)

### 19.6 Walking: what the movement step calls

What ForgePact's flight-charms research (#158, phase 1) read about the
player's walk on 2026-10-11, in the build Ghidra imported (the one
`py -3 tools/decomp_index.py build-hash` names), through the ghidra MCP and a
local scan for the names a function's code references. A name scan lists
candidate direct call sites; it is blind to calls through the script table or
a method value, so a call it did not find is not observed, not absent. Live 1
of that research measured the walk on 2026-10-12 (research DLL sha256
`ef6af41d4bd3ff478f3516a30dc46c4dd699caed8ab383ef5a5aeb7558ac323f`, slot 14
"Sorak", `Town_01_rm`, x64dbg logpoints and the `jumpprobe` hooks together);
each claim below says whether it is a static reading or measured.

- `gml_Script_PlayerMovement` (2774) does not decompile within the tool's
  limit: it is roughly 200 KB of compiled code. Read as the names its code
  references, it uses the builtins `place_meeting`, `position_meeting` and
  `collision_circle`, the path builtins, `point_distance`, `instance_nearest`
  and `object_is_ancestor`, and the variables `x`, `y`, `hSpeedFactor`,
  `vSpeedFactor`, `moving`, `mountId`, `inputState` and `pSt`. **Static
  reading** (2026-10-11).
- The name scan found no reference to `instance_place`, `tilemap_get_at_pixel`,
  the `mp_grid_*` builtins or `move_and_collide`, and it found no direct
  call from it to `CanMove` (467) or `InstancePlaceTallest` (599). **Static
  reading** (2026-10-11). The walk's own collision test is therefore most
  plausibly the three meeting builtins above, the ones answered for the jump
  in § 19.2; § 19.2 also measured that a walk stays blocked when only the
  family's queries are answered, so something other than the family's queries
  holds the walk. Candidates include a query naming an object outside the
  family, a query whose self is not the player, a builtin the jump probe does
  not hook (such as `instance_place_list` or `place_empty`), GameMaker's own
  solid-collision restore, a direct callee the scan did not resolve, or a
  script outside `PlayerMovement`. Live 1 found it outside `PlayerMovement`,
  in the player object's Step event (next bullet). **Measured** (2026-10-12).
- `InstancePlaceTallest` (599) gathers the instances at a place through
  `instance_place_list` into a list it reuses, and returns the one with the
  largest `height`, or `noone` when there is none. **Static reading**
  (2026-10-11). Its direct callers are `CanMove` (467), `playerJumpGravity`
  (2764) and six sites in `gml_Object_Player_obj_Step_0`, the player object's
  Step event: a function the symbol dump does not name, whose entry the
  runner's object-event registration table stores beside that name (the same
  table read names `ClassStepEvent`'s entry correctly). The 2026-10-11
  reading had put the six sites in `ClassStepEvent` (561), the nearest named
  script, which the Step event follows in the image; that was wrong. **Static
  reading** (2026-10-12, a byte scan of direct call sites and the
  registration table).
- During a walk, every player-self call to `InstancePlaceTallest` came from
  the player object's Step event, three of its six sites at a time, equally
  often (a different three at the ravine edge south of the town and at the
  church's stone wall): 315 calls in a 3 s blocked walk at the edge, 303 at
  the wall. Neither `CanMove` nor `PlayerMovement` called it. `CanMove` and
  `TilePlaceMeeting` were not observed to be called during any walk (no
  logpoint hit while the control logged, and no call through the hooked
  row either). **Measured** (2026-10-12).
- **Answering `InstancePlaceTallest` together with the player's builtin
  queries frees a walk; the builtins alone do not.** With the player's calls to it answered `noone` and the player's
  builtin queries answered too (`jumpprobe pass ... all scripts hold` or
  `any scripts hold`), the walk crossed both the ravine edge (about 700 px)
  and the church wall (about 690 px), and only the first of the three sites
  ran. With every hooked builtin query answered and the scripts left alone
  (`any hold`), all three sites still ran and the walk stayed held. Whether
  answering `InstancePlaceTallest` alone, with no builtin answered, frees the
  walk was not run. **Measured** (2026-10-12).
- A player left inside a prop by that lever (150 ms past the ravine edge,
  where `Collision_Parent_obj`'s family reads blocked by
  `Block_Dynamic_Sprite_obj`) stays stuck once the lever is off: 1 s walks
  in all four directions left the position unchanged, and the game did not
  push the player out. **Measured** (2026-10-12). The walk's blocked-walk
  queries also name objects outside the family (`place_meeting` named
  `Enemy_Parent_obj` most, then `Enemy_Child_Boss_obj` and
  `Enemy_Only_Passage_obj`), and `Wall_Parent_obj`, which the tally labelled
  a member of the family. **Measured** (2026-10-12). An earlier version of
  this line counted `Wall_Parent_obj` outside the family; the data file puts
  it inside (§ 19.8).
- `gml_Script_StatPhasing` (3390) is the getter behind item stat 26,
  "Movement Phasing" ("you walk through monsters", in the Item Editor's stat
  catalog), and the only caller found is `ReturnSpecificStat` (3344), the
  dispatcher Jump Power's getter is reached from too. The name search (fly,
  flight, wing, float, hover, phas) found no stat or flag for passing through
  terrain; that is a search negative, not an established absence. **Static
  reading** (2026-10-11); what
  stat 26 does on a character is not measured.
- `playerWings` (the cosmetic wings, drawn through `GetWingSprite` (1797) and
  `ReturnWingsInfo` (3467)) and `floating` (the interface's floating state,
  set through `UiSetFloating` (4472)) are not flight mechanisms. **Static
  reading** (2026-10-11).

[Static reading](../ForgePact/docs/flight-charms-research.md#static-reading),
[Live 1 results](../ForgePact/docs/flight-charms-research.md#live-1-results)

### 19.7 Draw order: the game layers sorted by y

What ForgePact's flight charms (#158, phase 2) read on 2026-10-12 about how an
instance's draw order follows its y, in the same build as § 19.6 (executable
sha256 `498d588550d80d0d100a4ce6958bcc044e6b79339920d3d8a931bca9a1b142c0`,
the one `py -3 tools/decomp_index.py build-hash` names), through the ghidra
MCP and existing local decompiles. Direct call sites come from a local byte
scan for calls to the function's entry, each mapped to its function by the
image's exception table; like the name scan in § 19.6, it is blind to calls
through the script table or a method value. The bullets that say
**measured** come from a later live session; the rest is not measured.

- `gml_Script_UpdateDepth` (4576) takes a y, the instance's own y when none
  is given, and a second argument that defaults to −1. It stores the y in the
  instance's `yDepthSet`. **Static reading** (2026-10-12).
- With the default second argument it sets the instance's `layer` to the
  layer `global.gameLayer` holds for the current room at that y, with the y
  clamped to 0..5500. Any other second argument takes a render-group route,
  which also ends by setting `layer`. **Static reading** (2026-10-12).
- It has 2746 direct call sites. Two of them are in the player object's Step
  event, the function that holds the six `InstancePlaceTallest` sites
  (§ 19.6). **Static reading** (2026-10-12, byte scan). Both of those calls
  run all the time in town: debugger logpoints on them rose by 3704 and 3703
  over a window in which a control logpoint on `CheckTalentUse` rose by 3707.
  **Measured** (2026-10-12, ForgePact's Mod live 1, `dbg-step-depth`,
  research DLL sha256
  `c15f85e1a79ccd7acfd3ad8d271605a4061182f6364a1d23c5c6096c1b2cd442`).
- So the game rewrites the player's draw layer from the player's y during the
  player's own Step, and a draw order a mod sets before that call would not
  last past it. **Inference** from the readings above; that the calls run is
  measured, that a draw order set before them is lost is not.
- Which end of the room's `global.gameLayer` layers draws in front:
  **measured** in ForgePact's Mod live 1 (2026-10-12, research DLL from
  ForgePact `26eecd2`, slot 14 "Sorak", `Town_01_rm`). The research probe read
  the last entry of the room's list at depth −5500 and entry 0 at depth 0, so
  the last entry, the one the largest y lands on, draws in front, as a lower
  depth draws on top in GameMaker. With flight off at (1180, 1650) the
  player's layer read depth −830.
- Both of `UpdateDepth`'s routes, the y route and the render-group route, end
  at an entry of `global.gameLayer` for the current room. **Static reading**
  (2026-10-13).

**Room layers in front of the game layers.** Replan 2 of the same work read
more on 2026-10-13, in the same build: object events through the ghidra MCP
(found by their name records, with slots named through `decomp_index`), and
room layers, room instances, object parents and events, and sprite sizes and
origins from the game's data file (`data.win`). Each bullet is labelled.

- `Town_01_rm` (room 235, 2800×2400) defines 21 layers. **Static reading
  from the data file** (2026-10-13). From the front:
  - `Effect_1`, an effect layer carrying `_filter_lut_colour`, at −10300;
    `Wind_Leaves`, an effect layer, hidden, at −10200;
    `Xmas_Event_Assets_1`, an asset layer, hidden, at −10100;
    `Invisible_walls`, 77 `Invisible_Wall_Not_Minimap_obj`, at −10000;
    `Windmill_Propels` at −9900; `Raven_Creators` at −9800;
  - `Tree_Leaves`, an instance layer at −9700 carrying the layer effect
    `_filter_underwater`, which is the canopies' sway;
  - behind them, `Flames` (0), `Christmas_Event` (1), `Halloween` (hidden, 2),
    `ZoneLight` (3), `Spawners` (4) and `Objects` (5, 430 instances: trees,
    bushes, hay, fences and rocks), then the tile layers from `Darkness` (6)
    to `Background_Tiles` (608).
- The room places 42 `Fall_Dead_Tree_Leaves_01_obj`, 34 on `Tree_Leaves` and
  8 on `Objects`. Their sprite, `Fall_Dead_Tree_Leaves_01_spr`, is 220×278
  with its origin at (115, 264). The canopy over Mod live 1's spot
  (1180, 1650) is the
  mirrored instance at (1158, 1869), covering x 1053..1273 and y 1605..1883.
  **Static reading from the data file** (2026-10-13).
- `Fall_Dead_Tree_Leaves_01_obj` is a child of `Visual_Parent_obj` and is
  invisible as an object. Its Create event runs its parent's Create and then
  moves the instance's `layer` to the room layer named `Tree_Leaves`; that
  name is a string the runner's start-up code fills in. `Visual_Parent_obj`'s
  own Create makes the instance visible, sets its `renderGroup` to 0, and
  sets sound and light fields. **Static reading** (2026-10-13).
- So every canopy of that object draws on the room's `Tree_Leaves` layer,
  whichever layer the room placed it on. **Inference** from the two readings
  above, and **measured** in ForgePact's Mod live 2 (2026-10-13, research DLL
  sha256 `dd87086cab7ba1b27d4742a68b063a85c593a7d97597412fd7f1714d08f2dc11`
  from ForgePact `7dfea36`, slot 14 "Sorak"): ForgePact's `zonecensus` found
  all 42 of `Town_01_rm`'s canopies on `Tree_Leaves` at −9700, the 8 the room
  places on `Objects` included, and all 187 of `Act_01_01`'s on its
  `Tree_Leaves` at −10000.
- At runtime a room holds far more layers than the data file defines: 5598 in
  `Town_01_rm` and 5620 in `Act_01_01`, most of them behind the game layers'
  front at −5500. In front of it are the runner's own `Layer_*` layers (the
  UI, the camera, the vignette, particles and the like, between −11001 and
  −14003) and the room's own; in town `Effect_1` read visible at −10300 and
  `Wind_Leaves` hidden at −10200, as the data file says, and two visible
  layers the data file's list for the room lacks, `FilterLayer1` at −10501
  and `Raven` at −10300, were there too, in both rooms. In `Act_01_01`,
  `Effect_1` read visible at −10100. **Measured** (2026-10-13, Mod live 2,
  `layers-town` and `layers-zone`).
- Fifteen more `*_Leaves_*` objects are `Visual_Parent_obj` children with a
  Create of their own, in the Abyss, Aztec, Boreal, Desert, Fallen Realm,
  Fuji, Miner Village, Mist and Valhalla sets. Their Creates were **not
  read**.
- `Zone_Light_obj`'s Create sets its `renderGroup` to 2 and places the
  instance through `UpdateDepth`'s render-group route. **Static reading**
  (2026-10-13). So its room layer (often `ZoneLight`, at −9800 or −9900)
  empties at runtime. **Inference**.
- Measured in the same Mod live 1: with the player's layer at −5500, the
  front entry of `global.gameLayer`, a canopy still covered him at
  (1180, 1650) (S9, two screenshots) and at (929.9, 2031.1) (S11). With
  flight on near the stash (S16) he was visible on open ground, so the game
  layer at −5500 is drawn. **Measured** (2026-10-12).
- So no layer of `global.gameLayer` draws in front of a room's `Tree_Leaves`
  layer. **Inference** from the measurements and the readings above.
- A room layer of ForgePact's own at −10001, in front of `Tree_Leaves` and
  `Invisible_walls` (at −9700 and −10000 in these two rooms; elsewhere
  `Tree_Leaves` can sit as far forward as −10100, see below) and behind
  `Effect_1`, draws the player over the canopy that hid him without it: at (1180, 1650) and
  (1158, 1720) in town and at a canopy in `Act_01_01` (screenshots). With the
  player there his colours looked like the scene around him (the operator's
  note, not judged). **Measured** (2026-10-13, Mod live 2, `flight-depth`
  and `flight-depth-zone`).
- Of the data file's 306 rooms with layers, 120 put a visible layer in front
  of −5500. `Tree_Leaves` sits between −9700 and −10100 in about 40 rooms.
  **Static reading from the data file** (2026-10-13).

**Colour-filter layers.** Read from the data file on 2026-10-13 (amendment 2
of the same replan). The script that read it is kept outside every
repository.

- A filter layer, in the data file, is a visible layer of the effect type
  (type 6) that lies in front of the game layers' front end at −5500,
  whatever its effect: a colour lookup, tint, contrast, colourise, vignette,
  or windblown particles. Full-screen filters sit mostly between −10000 and
  −10300. **Static reading from the data file** (2026-10-13).
- At runtime, a `_filter_lut_colour` filter layer reads as a visible layer
  that holds no element and for which the `layer_get_fx` builtin answers a
  struct. The builtin's name appears in this build's executable (byte
  search, 2026-10-13). That `layer_get_fx`, handed the layer's id as
  `layer_get_all` lists it, answers a struct for `Effect_1`
  (`_filter_lut_colour`) is **measured** (2026-10-13, ForgePact's Mod live
  2, `flight-depth` and `flight-depth-zone`): ForgePact's `flightprobe
  depth` named `Effect_1` as the filter, `filter=Effect_1@-10300` in
  `Town_01_rm` (the positive control) and `filter=Effect_1@-10100` in
  `Act_01_01`, each with an `fx=` struct count of 2 (the second
  struct-answering layer in each room was not named). For the other effect
  kinds (tint, contrast, colourise, vignette, particles) and in the 8 rooms
  below, where the rule changes the answer, it is **not established**. That
  reading, not the
  flight depth, is the evidence: in both rooms `Effect_1` lies in front of
  every drawn layer, so a filter read and no filter read give the same
  depth there. What the builtin answered for the layers that were not a
  struct is recorded, with the argument supplied, in the research doc only
  ([Mod live 2 results](../ForgePact/docs/flight-charms-research.md#mod-live-2-results));
  the argument is in
  [Drawing in front](../ForgePact/docs/flight-charms-research.md#drawing-in-front).
  An instance or asset layer that carries a layer effect but holds no element
  yet reads the same way until it fills: a zone's `Tree_Leaves` (with its
  `_filter_underwater`) before its canopies exist, or `Act_09_04`'s `Flame`.
- 101 of the 306 rooms have such a filter. In 8 of them a filter lies behind
  the room's frontmost visible drawn layer: `Act_01_Pregame`, `Act_09_01`,
  `Act_09_04`, `Act_09_05`, `Town_09_rm`, `Unstable_Rift_09_01`,
  `Unstable_Rift_09_04` and `Unstable_Rift_09_05`. In those rooms a layer the
  game draws sits in front of a tint. **Static reading from the data file**
  (2026-10-13).
- In `Act_09_05` and `Unstable_Rift_09_05`, a drawn layer, `Smoke` at −11200,
  sits between filters: `Sparks` at −11300 in front of it, `Effect_2` at
  −11100 and `Effect_1` at −11000 behind it. An instance drawn in front of
  every drawn layer behind the frontmost filter would sit at −11201, in front
  of both rear filters; only a place behind the rearmost filter, the one
  nearest the game layers, keeps it behind every filter of the room. **Static
  reading from the data file** (2026-10-13).

What ForgePact's flight charms do with these facts is in the module guide;
the research is in
[Why the canopy covered the flying player](../ForgePact/docs/flight-charms-research.md#why-the-canopy-covered-the-flying-player),
and the sessions' records in
[Mod live 1 results](../ForgePact/docs/flight-charms-research.md#mod-live-1-results)
and
[Mod live 2 results](../ForgePact/docs/flight-charms-research.md#mod-live-2-results).

[Phase 2 static reading](../ForgePact/docs/flight-charms-research.md#phase-2-static-reading)

### 19.8 The collision family in the game data

What the game's data file (`data.win`) says about `Collision_Parent_obj`'s
family, read from its object table (each object's name and parent) on
2026-10-12 for ForgePact's flight charms (#158, phase 2). This is the data
file's parent chain: not a decompile, and not measured unless a bullet says
so.

- `Collision_Parent_obj` (957) has 1824 objects in its family. Its direct
  children are `Angelic_Room_Platform_Mask_obj`, `Block_obj`,
  `Chaos_Tower_Collision_obj`, `Collision_Prop_obj`,
  `Cult_Dungeon_Bridge_Block_obj`, `Lever_Parent_obj`, `Lock_obj`,
  `Quest_NPC_Parent_obj`, `Rock_Pillar_obj`, `Valve_Platform_obj` and
  `Wall_Parent_obj`. Read from the data file (2026-10-12).
- `Wall_Parent_obj` (5701) is one of those children. Its descendants are
  `Wall_obj`, `Wall_Wooden_obj` and `Wall_Boss_obj`, the eight
  `Invisible_Wall_*` objects, `Gate_Parent_obj` (1881) and through it the zone
  gates, `Coffee_Club_obj` and `Puzzle_Pillar_obj`. So a zone gate is a wall,
  and walls are in the family. Read from the data file (2026-10-12).
- `Lock_obj` (2509) is a direct child of `Collision_Parent_obj` and has no
  descendants. Read from the data file (2026-10-12).
- `Block_Dynamic_Sprite_obj` (608), the object that blocked the ravine edge
  south of the town in Live 1 (§ 19.6), is a child of `Block_obj` (609), a
  direct child of `Collision_Parent_obj`. So it is in the family but is not a
  wall. Read from the data file (2026-10-12).
- Live 1's tally of a blocked walk labelled `Wall_Parent_obj` a member of the
  family (capture step S6). **Measured** (2026-10-12), and it agrees with the
  data file.
- In `Town_01_rm`, a step down from the ravine edge at (928.9, 1590.7) and a
  step right from the church's stone wall at (1035.7, 1253.7) each met the
  family but no `Wall_Parent_obj`: the blockers there are scenery, not walls.
  A step south of (929.9, 2031.1), where the data file puts the
  `Invisible_Wall_Not_Minimap_obj` columns, met a `Wall_Parent_obj`.
  **Measured** with ForgePact's `flightprobe free` (Mod live 1, 2026-10-12,
  S10; Mod live 2, 2026-10-13, `flight-excluded`).
  [Mod live 2 results](../ForgePact/docs/flight-charms-research.md#mod-live-2-results)

[Phase 2 static reading](../ForgePact/docs/flight-charms-research.md#phase-2-static-reading)

### 19.9 The monster family in the game data

What the game says about the objects a walk can meet besides the collision
family (§ 19.8), read on 2026-10-13 for ForgePact's flight charms (#158,
phase 2), after the owner asked for a flying player to walk through monsters.
Most of it comes from the data file's object table (each object's name and
parent) and room table (each room's placed instances). That is neither a
decompile nor a measurement; each bullet says which kind of reading it is.

- `Enemy_Parent_obj` (1429) is a child of `Avoidable_Parent_obj` and has 336
  descendants. Its four direct children are `Enemy_Child_Basic_obj`,
  `Enemy_Child_Boss_obj`, `Enemy_Child_Destructible_obj` and
  `Demon_Lightning_obj`. The six children of `Enemy_Child_Destructible_obj`
  are boss parts: `Akora_Wrapping_obj`, `Blackstone_Defender_obj`,
  `Damien_Mask_obj`, `Damiens_Chain_obj`, `Mevius_Chain_obj` and
  `Odin_Pillar_Enemy_obj`. So a destructible boss part counts as a monster
  under the "descends from `Enemy_Parent_obj`" test. Read from the data file
  (2026-10-13).
- `Player_obj` (3553), `Mercenary_obj` and `Summon_Parent_obj` are children of
  `Enemy_Aggroable_obj` (1401), which has no parent. Despite its name, that
  object is not in the monster family, and neither are the player, a
  mercenary or a summon. Read from the data file (2026-10-13).
- `Enemy_Only_Passage_obj` (1428) has no parent: it is neither a monster nor
  a member of `Collision_Parent_obj`'s family. The blocked walk's tally named
  it on `place_meeting` (§ 19.6). Read from the data file (2026-10-13); the
  tally is **measured** (2026-10-12).
- The training dummies, `Attack_Dummy_obj` (364) and `Attack_Dummy_Boss_obj`
  (363), descend from `Enemy_Child_Basic_obj`, so they are monsters under the
  same test. `Town_01_rm` places seven `Attack_Dummy_obj` and one
  `Attack_Dummy_Boss_obj` on its `Spawners` layer. The plain dummies stand at
  (1592, 688), (1664, 688), (1629, 654), (1592, 616), (1664, 616),
  (1816, 704) and (1736, 544), and the boss dummy at (1616, 416); the ones at
  (1816, 704) and (1736, 544) stand apart from the rest. Read from the data
  file (2026-10-13). That the dummies neither move nor attack is how the town
  is played, not a reading of their code. **Measured** (ForgePact's mod live
  3, 2026-10-13): `Attack_Dummy_obj` does not stop a vanilla player walk.
  With no flight charm worn, a 1.5 s walk north from 96 px south of the dummy
  at (1816, 704) ended at y 503, past it. The saved original `place_meeting`
  did name the dummy at its own spot (`by=Attack_Dummy_obj`), so a dummy is
  met by the query but does not hold the walk.
- `StatPhasing` (3390), the getter of item stat 26 "Movement Phasing" (walk
  through monsters), has exactly one direct call site in the imported
  executable, inside `ReturnSpecificStat` (3344), the stat dispatcher.
  **Static reading** (2026-10-13), from a local byte scan for calls to its
  entry, each mapped to its function through the image's exception table; it
  agrees with § 19.6's earlier caller search. **Measured** (ForgePact's mod
  live 3, 2026-10-13, a non-breaking debugger logpoint on its entry beside a
  `CheckTalentUse` control): `StatPhasing` runs on every step, once per
  `CheckTalentUse` hit, whether the player walks or stands still (419 against
  418 during one walk, 12693 against 12692 over a stretch standing in town).
  So something reads stat 26 every step, not only when the stats are rebuilt.
  What calls it each step, and whether the movement uses its answer to let a
  player through monsters, is **not established**: the decompile of
  `StatPhasing` and of the movement did not complete through the ghidra MCP,
  and no headless decompile was run. The same session measured
  `InstancePlaceTallest` entered during walks only (111 and 103 times in two
  1.5 s walks, none while standing).
- The walk's `place_meeting` names `Enemy_Parent_obj` more often than any
  other object outside the collision family: 3015 queries in the blocked-walk
  tally (§ 19.6). **Measured** (2026-10-12). During a jump, `position_meeting`
  also names it with the player as `self`
  ([jump research, Live 1 results](../ForgePact/docs/jump-scenery-research.md#live-1-results));
  **measured** for jumps, not for walks. That a monster standing
  in the path makes those queries answer "blocked", and that this answer is
  what holds the walk, is **not established**. ForgePact's mod live 3 walked
  the player into a training dummy, but a dummy does not hold a vanilla walk
  (above), so whether a live monster holds one, and through which row, is
  still not observed by any instrument. Under ForgePact's flight the monster
  pass-through, with monsters still damaging the flying player and his own
  hits still landing, is **owner-confirmed in play, 2026-10-13**: the
  owner's report after playing on the research build, not an instrumented
  measurement. The game facts above keep their own labels.

[Phase 2 static reading](../ForgePact/docs/flight-charms-research.md#phase-2-static-reading),
[Mod live 3 results](../ForgePact/docs/flight-charms-research.md#mod-live-3-results)

### 19.10 Walking speed and jump length

What ForgePact's Mark 1 research (#166, phase 1) read on 2026-10-13, by the
sources and with the caveats § 7.7 gives (a local scan of each script's
compiled code for the names it references, its direct calls and the constant
ids it passes, plus the ghidra MCP for the small functions). Every bullet is a
**static reading** (2026-10-13) unless it says measured. The large bodies
(`StatMovementSpeed`, `PlayerMovement`, `skillsLeap`, `playerJumpGravity`) did
not decompile within the tools' limits, so what is below is which names each
one touches and whether it reads or writes them, not the arithmetic. The
**measured** parts come from the research's Live 2 session on 2026-10-13
(the `mark1probe` rows, levers and `pos` sampler plus x64dbg logpoints, save
slot 14, in `Town_01_rm`, on the same build): see
[Mark 1 research, Live 2 results](../ForgePact/docs/mark1-set-research.md#live-2-results).
The parts marked **measured, 2026-10-19** come from the research's phase 2
session, Mod live 1 (the same character and game build, the probe extended
with eleven builtin rows, a per-call stat log and a modal step per window,
in `Town_01_rm` and the Outskirts of Inoya): see
[Mark 1 research, Mod live 1 results](../ForgePact/docs/mark1-set-research.md#mod-live-1-results).

- **The movement speed stat is read in the player's Step event.** The stat
  dispatcher sends id 64 to `gml_Script_StatMovementSpeed` (3389), whose only
  direct caller found is the dispatcher (3344). The scripts found asking the
  dispatcher for id 64 are the player object's Step event (once),
  `StatTotalDamage`, `StatAttackDamage`, `StatMagicSkillDamage`,
  `TalentsSamurai` and `Mercenary_obj`'s Alarm 5. No request for id 64 was
  found in `PlayerMovement` (not observed; the scan sees only constant ids at
  direct call sites); it asks for id 336, which has no case in the dispatcher's table
  ([skill sliders' reading](../ForgePact/docs/skill-sliders-research.md#returnspecificstat-the-dispatchers-case-table)).
  **Measured** in Live 2 (`dbg-stat-movement`): `StatMovementSpeed` runs once
  a frame, standing or walking, every call returning to the dispatcher's
  direct call site in `ReturnSpecificStat` (2008 logpoint hits, one return
  location), and nothing called it directly during a walk.
- **Halving movement speed at the dispatcher does not halve the walk
  (measured).** In Live 2 (`speed-stat`), multiplying id 64's result by 0.5
  on every dispatcher call for 240 frames cut the walk's step from 5.979 px a
  frame to 4.693 px: 0.785 of itself, not 0.5. The lever scaled the
  dispatcher's answer (`changed-dispatch=240`) and never the getter's
  (`changed-getter=0`, `skip=240`): every local `StatMovementSpeed` call
  inside the dispatcher returned something the probe could not read as a
  number, so the getter route never scaled, against the probe core's tested
  model, which scales such a nested call at the getter. Halving the
  dispatcher's id-64 answer gave 0.785 of the step. Whether the step is not
  proportional to it (base, cap, floor), whether the walk also reads
  movement speed by a route the dispatcher lever does not reach (e.g. the
  cached `pSt` values `PlayerMovement` reads), and why the getter's own
  result was not a number to the probe (`skip=240`) are **not established**;
  the last is an open instrument question for the choice of speed lever.
- **The walk's per-frame step comes in multiples of half its modal step
  (measured). The modal step is robust to occasional slow frames within one
  window, and compares across windows only at the same mean frame time.** In
  the same Live 2 (`forgepact-166-mark1-set-live-2.md`, T7 and its recheck),
  the per-frame steps of a 240-frame walk were not one value: unscaled, 138
  frames moved 5.979 px, 6 moved 2.989 and 4 moved 8.968; with the id-64
  answer halved, 128 frames moved 4.693 px, 13 moved 7.039 and 2 moved 2.346.
  Every step is 0.5, 1 or 1.5 times that walk's most common step. Plausibly a
  frame-time factor in steps of 0.5 multiplies the step (inferred from the
  quantization and T5; per-frame frame time was not recorded). A walk's total
  distance moves with the frame time, and a sustained change in frame time
  moves the modal step too: in T5 a per-frame logpoint took the frame from
  13.4 to 23.2 ms, and the walk's modal step went from 5.979 to 8.968 px (its
  steps were 8.968 and 11.958 px, 1.5 and 2 times the unscaled 5.979). So
  comparing modal steps across windows is valid only when their mean frame
  time (the probe's `ms=`) agrees within 10%, which is Live procedure 1's
  rule; a window run under different instrumentation load can show a 1.5x or
  2x frame-time artefact that is not a speed effect. The 0.785 above is a
  ratio of modal steps taken at comparable frame time (T4 and T7, neither with
  the per-frame logpoint).
  Live 2 left the shape open, and Mod live 1 settled it as affine (next
  bullet). What Live 2 could not tell apart: a step affine in
  the answer (a base plus a part proportional to the stat, such as a "+N%"
  stat over a base speed, which with these two points puts this character
  near +75%); a step capped at a maximum the unscaled answer already exceeds;
  or a walk that also reads a cached copy of the stat (`pSt`, plausibly
  refreshed by Alarm 8, below) the dispatcher lever does not reach, which
  would show as a lever whose effect drifts within a window (the 128 frames
  at one constant step argue against it but do not rule it out). The first
  two predict different levers, and one measured ratio cannot tell them
  apart.
- **The walk's step is affine in the movement speed stat (measured,
  2026-10-19).** In Mod live 1 (`speed-sweep`, `speed-half`), with id 64's
  answer multiplied at the dispatcher by 1.5, 0.75, 0.5, 0.25, 0 and -0.5
  for a walk each, the modal step went 1.215, 0.893, 0.785, 0.678, 0.570 and
  0.355 of the unlevered 2.989 px, every frame of each window at that one
  step. All six points lie on one line to within 0.02%: the step is
  proportional to the answer plus about 200 (fitted 200.0), so this
  character's 151 walks at 1.755 times the step an answer of 0 gives. No cap
  was reached up to an answer of 226.5, a negative answer slowed the walk
  further, and the same 0.785 at half the answer as Live 2 found came back at
  another frame rate. Answering about -24.5, (151 - 200) / 2, gave a ratio of
  0.500. The id-64 call came once a frame, 151 each time, outside every row
  the probe wraps (`PlayerMovement`, `CheckTalentUse` and the rest), as the
  static reading placed it in the player's Step event (`stat-trace`), and
  `StatMovementSpeed` was never called outside the dispatcher. Where in the
  Step event the answer is turned into the step is not read, so the constant
  200 is measured for this game build, not read.
- **The walk's step halved between two sessions (measured, 2026-10-19).**
  Mod live 1, at 6.94 ms a frame, measured a modal step of 2.989 px against
  Live 2's 5.979 px at 13.4 ms: a step ratio of 0.500 at a frame time ratio
  of 0.518. The step halved exactly while the frame time did not halve; a
  step proportional to frame time would have been about 3.10 px, 3.6% off
  the measured one. The cause (the frame clock, a target-rate setting or a
  per-frame constant) is **not established**, so nothing here supports
  scaling a step, or a frame-counted window, by measured frame time.
- **Gear changes the unlevered step (measured, 2026-10-19).** In the Mark 1
  research's Mod live 2
  ([Mod live 2 results](../ForgePact/docs/mark1-set-research.md#mod-live-2-results)),
  at the same 6.93 to 6.96 ms a frame as Mod live 1, Sorak wearing the four
  Mark 1 pieces in place of his own helmet, body armour, boots and gloves
  walked at a modal step of 2.385 px with every lever off (two control walks,
  2.385 both), against Mod live 1's 2.989 px in his own gear. So a walk
  control is valid only for the gear it was taken in.
- **The half walk measured with the set worn (measured, 2026-10-20).** In the
  Mark 1 research's Mod live 3
  ([Mod live 3 results](../ForgePact/docs/mark1-set-research.md#mod-live-3-results)),
  at 6.93 to 6.94 ms a frame, Sorak in the four pieces walked at 2.385 px with
  the switch off (two control walks, as in Mod live 2) and at 1.192 px with
  it on, on all 103 watched frames free of a cast's slowdown (`on-speed`):
  0.4998 of the control. So the set's answer of (x - 200) / 2 to the local
  movement speed calls halves the walk in this gear too, as `speed-half`
  found (0.500) in his own.
- **What `StatMovementSpeed` reads.** The player's `playerBuff` (about 380
  reads) through the `GetBuffValue` and `GetBuffStack` methods, `buffArray`,
  `debuffArray`, `buffMult` and `skpDb`; it asks the dispatcher for ids 106,
  531, 532 and 598 (106 is faster cast rate; the other three have no case),
  calls `ReturnSubTalentLevel` and `LoadSubTalentDamage`, and uses `floor`
  and `power`. **Whether it caps is not established**: this build compiles
  `min`, `max` and `clamp` inline (the scan finds no named builtin for them),
  so a cap would not show as a name.
- **The speed names the walk touches.** `PlayerMovement` (2774) reads
  `hSpeedFactor` and `vSpeedFactor` (five sites each, no write found),
  `mobileSpeedFactor` and `roomSpd`, and its stat values `pSt`. The player's
  Step event reads `move_dist`, `new_x`, `new_y`, `hSpeedFactor`,
  `vSpeedFactor`, and `mountSpeed` from another instance, writes `moveOverrideHor` and
  `moveOverrideVer`, and uses `mp_linear_step`. Which of these the step's
  final distance is computed from is **not established**. **Measured** in
  Live 2 (`walk-mover`): during a walk `PlayerMovement` runs once a frame, but
  none of its calls, nor any call of `CheckTalentUse`, `TalentUse`,
  `TalentUseSetSpeed`, `ReturnSpecificStat`, `StatMovementSpeed`,
  `skillsLeap`, `playerJumpGravity` or `StatJumpPower`, changes the player's
  position: the walk's displacement is applied somewhere outside all of them.
  **Measured, 2026-10-19** (Mod live 1, `speed-builtin`, `dbg-walk-movers`,
  `speed-factor`): eleven movement builtins hooked beside those rows
  (`place_meeting`, the `mp_linear_step`, `mp_potential_step`, `move_*` and
  `motion_*` families and `move_and_collide`) moved no walk either; the
  player called `place_meeting` 8270 times during one, and none of the
  others was called at all. x64dbg logpoints on `PlayerMoveSkill`,
  `PlayerMoveSkillFunc` and `CA_playerMove` logged no hit over a walk or a
  walk with a cast while the control logged. Holding `hSpeedFactor` or
  `vSpeedFactor` at half during `PlayerMovement` left the step unchanged,
  but the values the probe read from them were 163556 and 163557,
  consecutive whole numbers unlike a speed factor, so whether the walk
  scales with those members is **not established**.
- **Jump Power is read by the player's Alarm 8 event**, the only script found
  asking the dispatcher for id 66 (`gml_Script_StatJumpPower`, 3391). That
  event asks the dispatcher about 350 times, so it is plausibly the routine
  that refreshes the player's stat values; that fits § 19.1's measurement
  that `StatJumpPower` logged no call during a jump. `StatJumpPower` reads
  only `playerBuff`, through `GetBuffValue`. **Measured** again in Live 2
  (`dbg-stat-jump`, `jump-stat`): an x64dbg logpoint on its entry logged no
  hit over six jumps while the control logpoint kept logging, and a x3 on id
  66 at the dispatcher found no call to scale; the jumps' lengths did not
  change.
- **`gml_Script_skillsLeap` (3664)** has three direct callers found: the
  player object's Step event, `ClassStepEvent` (560) and `Mercenary_obj`'s
  Step event. It sets `x` and `y` at three sites each (on which instance is
  not read: the script also creates instances of many kinds and handles leap
  skills' damage), sets `direction` (four sites), `deltaSpeed` (two) and
  `max_range` (one), reads `height` and `jumpDirection`, and calls
  `gml_Script_PlayerMoveSkill` (2776, which reads `pSt` and sets `x` and
  `y`), `gml_Script_IsObtainablePlace` (2076, five sites, § 19.11),
  `InheritModifiers` and the collision builtins `collision_circle`,
  `collision_circle_list`, `instance_place`, `instance_position`,
  `place_meeting` and `position_meeting`, naming `Collision_Parent_obj`,
  `Wall_Parent_obj` and `Block_obj`. It asks the dispatcher for id 337 (no
  case) and for damage stat ids. It references no mouse coordinate, so the
  jump's target is plausibly decided before it runs (the Step event reads
  `mouse_x`, `mouse_y`, `xMouse` and `yMouse`).
- **`jumpDirection` is set up by the scenery.** The Create
  events of `Collision_Parent_obj`, `Collision_Prop_obj` and about thirty
  cliff objects reference it, so it is plausibly the direction a cliff lets a
  leap go down, read from the prop a leap meets. Whether the player also
  carries it was not read: `skillsLeap` reads it on an instance this reading
  did not identify.
- **`gml_Script_playerJumpGravity` (2764)** has one direct caller found, the
  player object's Step event. It reads `x` and `y` (no write site found),
  `height`, `pSt` and `playerEffect`, sets `stickHost`, references `unstuck`,
  `unstuckDir`, `myShadow`, `groundDepth` and `playerSkipCollisions`, and
  calls `InstancePlaceTallest` (599), `IsInWater` and `UpdateDepth`; it asks
  the dispatcher for id 337 too. So by this reading `skillsLeap` (or
  `PlayerMoveSkill` inside it) moves the player during a jump and
  `playerJumpGravity` handles the landing side. Both run every frame of a
  jump (§ 19.1, **measured**). **Measured** in Live 2 (`jump-mover`): the
  jump is moved by `skillsLeap` alone, 102 moving calls in a jump with the
  cursor about 100 px away (96.9 px covered) and no movement outside it;
  `playerJumpGravity` ran 101 times in the same jump and never moved the
  player.
- **Scaling `skillsLeap`'s displacement scales the jump (measured).** In
  Live 2 (`jump-move`), multiplying the position change of each local
  `skillsLeap` call by 3 tripled the jump: 290.7 px against 96.9 px with the
  cursor about 100 px away (3.00 times), and 738.8 px against an unscaled
  250.3 px with it about 300 px away (2.95 times), well past the jump's usual
  reach of about 246 px (§ 19.5). Whether the game's own landing checks still
  hold at the scaled landing point was not measured.
- **The shipped three-times jump (measured, 2026-10-19).** In the Mark 1
  research's Mod live 2
  ([Mod live 2 results](../ForgePact/docs/mark1-set-research.md#mod-live-2-results)),
  the Mark 1 set read the jump's maximum M as jumpscenery's cap, 250.3 px,
  and its scaled jumps landed 734.9 px (cursor 300 px away), 740.9 px (cursor
  110 px away) and 750.9 px (cursor 510 px away) from the take-off, 2.94 to
  3.00 times M, toward the cursor and not at it. With the switch off a jump
  with the cursor 101 px away covered 96.9 px, and one with the cursor 301 px
  away 250.3 px, as before. The landing's walkability is § 19.11.
- **The game has its own collision skip.** `playerSkipCollisions` is
  initialised in the player's Create event and read in its Step event, and is
  referenced through another scope by `playerJumpGravity`, the player's
  collision event with `Collision_Parent_obj`, `Krampus_obj` (2426) and
  `Prison_Catapult_Bottom_obj` (3629)'s Alarm 0, which also references
  `launchPlayer`, `forceMovePlayer`, `jump` and `zSpeed`. The player's
  collision event with `Collision_Parent_obj` references `x`, `y`,
  `xprevious`, `yprevious`, `speed` and `height`: the shape of an event that
  puts the player back where it was. Whether `playerSkipCollisions` gates
  that event, and who sets it when, is **not read**.

[Mark 1 research, Static reading](../ForgePact/docs/mark1-set-research.md#static-reading)

### 19.11 The walkable map and its edge

From the same reading as § 19.10 (2026-10-13). Static unless marked.

- **What tells a walkable point in town (measured, 2026-10-13).** In the
  Mark 1 research's Live 3 session
  ([Live 3 results](../ForgePact/docs/mark1-set-research.md#live-3-results)),
  the probe called, with the player as `self`, `place_meeting` against
  `Collision_Parent_obj` (957) at a point, `collision_line` from the player
  to it against `Wall_Parent_obj`, and `mp_grid_get_cell` on
  `global.pathGrid`, in `Town_01_rm`:
  - On open floor, the player's own position included, `place_meeting`
    answered a `real` 0, `collision_line` a `ref` -4 (`noone`) and the grid
    cell 0. Called this way, `place_meeting`'s answer is a number, 0 or 1,
    not a `bool` (§ 19.3 measured a `bool` inside the game's own calls).
  - Inside a prop, the Bounty Board (`Bounty_Board_obj`), only
    `place_meeting` met anything (`real` 1, `instance_place` on the family
    naming the board); the grid cell read free and the line clear.
  - The town's south edge is an invisible wall: `Invisible_Wall_Not_Minimap_obj`
    instances, which `place_meeting` meets as `Collision_Parent_obj` and
    `collision_line` returns as `Wall_Parent_obj`. Scanning toward it in
    16 px steps, `place_meeting` met it one step before the grid cell read -1
    and the line crossed it. Nothing on screen draws it. Water
    (`Block_Dynamic_Sprite_obj`) and fallen rocks and trees
    (`Fall_Rock_01_obj`, `Fall_Dead_Tree_02_obj`) blocked both the grid and
    `place_meeting`.
  - Past the room's bottom the grid cell read -1, but `place_meeting` met
    nothing once the points were past the invisible walls.
  - None of the four tile layers the probe read (`Darkness`, `Hay_Ground`,
    `Leaves_Ground` and `Water`) marks the edge. The probe keeps at most four
    tile layers, and `Town_01_rm` has more (its tile layers run from
    `Darkness` to `Background_Tiles`, § 19.7), so whether a later tile layer
    marks the edge was not read.

  So in a town a landing point is walkable when it lies inside the room and
  the player placed there meets nothing of `Collision_Parent_obj`; the
  research records `walkable-test: combined`. Live 2's control had failed
  (`walkable-control`, [Live 2 results](../ForgePact/docs/mark1-set-research.md#live-2-results))
  because that build's probe counted any number of 0 or more as a meeting,
  so `place_meeting`'s 0 printed as blocked; ForgePact 61243b2 corrected it.
  A generated zone was measured later (next bullet).

- **One edge of a generated zone (measured, 2026-10-19).** In the Mark 1
  research's Mod live 1
  ([Mod live 1 results](../ForgePact/docs/mark1-set-research.md#mod-live-1-results)),
  the same reads were taken in the Outskirts of Inoya (`Act_01_01`, reached
  through the town waypoint's map). At the arrival point and 32 px either
  side every field read free (`zone-control`). Scanning 96 px steps out in
  four directions (`zone-edge`), the floor upward ended at an
  `Invisible_Wall_obj`: in 16 px steps across it, `place_meeting` met the wall
  one step before the path grid cell read -1 and the wall line crossed it,
  and past the wall `place_meeting` met nothing again while the grid cell
  stayed -1 to the room's top edge, the cliff tile layer
  (`Autotile_Fall_Cliff_tileset`) reading non-zero from the wall on. So, as in town, the
  edge is an invisible wall that both readings see, and past it only the
  grid still says no; the research records `zone-edge: both`. Elsewhere the
  scans crossed cliff bands that only the grid and the wall line marked
  (with the cliff tiles set), floor that read free again beyond them, and
  scattered points both readings blocked, plausibly props; the `Void` tile
  layer read non-zero at two points both readings called free. The
  screenshot showed no void (the edge lay about 600 px above the player,
  plausibly just out of view). One edge of one
  zone was measured; whether every zone marks its edge this way, and how the
  zone generator's outside rectangles line up with it, are **not
  established**.

- **Landings read with these fields hold at a jump's end (measured,
  2026-10-19).** In the Mark 1 research's Mod live 2
  ([Mod live 2 results](../ForgePact/docs/mark1-set-research.md#mod-live-2-results)),
  the Mark 1 set's jump passed a landing only when the point and the points
  16 px either side of it were inside the room, met no `Collision_Parent_obj`
  and sat on a free path-grid cell, and each granted landing that was read
  again with the player standing on it read free on every field. A take-off
  at (912, 1560) aimed due south, whose three-times point lay past the
  town's south edge (the family blocked from y 2038), backed off to a point
  250.0 px south; a jump
  west across the Bounty Board covered 718.9 px and landed past it. At the
  town's south edge from (912, 1974) no candidate passed, and the jump went
  its vanilla 40.3 px; the refusal came from the reads' answers (no read
  failed, the family's rejections rose, and the grid answered free or
  blocked, never "no grid"). At the Outskirts' edge the zone had loaded in a
  different layout from Mod live 1's, and the edge was found again by the
  same signature (an `Invisible_Wall_obj` met by the family, then the grid
  alone blocked over the cliff tiles): a jump aimed past it was refused and
  stopped 125.1 px on, inside the wall. So one zone's edge sits in a
  different place from one load to the next, while its marking stays the
  same.
- **The view the cursor can reach (measured, 2026-10-19).** In the same
  session the view was 1280 × 720 room pixels centred on the player, in town
  at both points read: an on-screen cursor reaches at most about 645 px from
  the player horizontally and about 741 px at a corner, so with the jump's
  M of 250.3 px no on-screen cursor lies past 3M (751 px).

- **The path grid marks blockers, not the map's edge.**
  `gml_Script_PathFindControllerCreate` (2714) destroys any earlier
  `global.pathGrid`, sets `global.gridSize` to 16, creates an mp_grid of
  `room_width` / 16 by `room_height` / 16 cells, clears it, and adds every
  instance of `Collision_Parent_obj` (957) with precise masks, then those of
  `Player_Only_Passage_obj` (3554) and `Projectile_Only_Passage_obj` (3675)
  when any exist. It ends with `gml_Script_PathFindApplyStaticBlockers`
  (2718): when `global.pathStaticRoom` is the current room, every rectangle in
  `global.pathStaticRects` (four numbers each) is added too. Neither function
  marks a cell because it lies beyond the floor: a cell is blocked only where
  one of those instances or rectangles covers it. Read from the MCP decompile
  of both functions. § 22.7 measured the grid itself. **Measured in part
  (Live 3, above):** at the town's south edge the blocked cells are where
  the invisible wall instances stand, and a point past the room reads -1;
  but the cells under the Bounty Board, which `place_meeting` meets as a
  `Collision_Parent_obj` instance, read free, so not every instance of the
  family blocks a cell in that room. Why is not established.
- **In a generated zone the rectangles are the outside.** The rectangles come
  from `gml_Script_PathFindBuildStaticBlockers` (2717), whose one direct caller found
  is an anonymous function of `objZoneGenV2` (3259)'s Create event. It reads
  the generator's `outsideBlockList`, `zoneOuterScale` and `global.gridSize`
  and the room size, and writes `global.pathStaticRects` and
  `global.pathStaticRoom`. So in a generated zone the area outside the zone
  is plausibly blocked in the path grid through those rectangles. Name scan;
  the arithmetic was not read. In a room the generator did not build, no
  script was found that marks the outside; in `Town_01_rm` the edge measured
  is placed instances, the invisible walls above (Live 3).
- **The game's own "can something stand here" test.**
  `gml_Script_IsObtainablePlace` (2076) takes a point. When no
  `objZoneGenV2` (3259) exists it answers yes, for any point. Otherwise it
  answers no for a point outside the room, no when the generator's
  `heatGridL` is negative, and yes only when the point's 32 px cell and its
  four diagonal neighbours all hold something other than 30000. Read from the
  MCP decompile.
- **The heat grid is the generated zone's wall map.** `heatGridL` is written
  by `objZoneGenV2`'s Create event and by `gml_Script_ZoneGenMakeZoneWalls`
  (3601), so 30000 plausibly marks a wall or void cell of a generated zone.
  `IsObtainablePlace` has callers across the game: `skillsLeap` (five sites),
  `skillsBlink` (3660), the player's Step event, `PlayerUpdateTimers` (2794),
  `TalentsUniversal`, the enemy creators, `Quest_Manager_obj` and the platform
  objects. Whether `objZoneGenV2` exists in a town, and so whether the test
  says anything there, is **not established**.

[Mark 1 research, Static reading](../ForgePact/docs/mark1-set-research.md#static-reading)

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
  entry; `fnwalk` was built to walk the array for one but in Live 3 could not
  locate the table, so the by-name route stays blind - § 20.5,
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
- After the log, `Alarm_9` reads the machine's protected value `activated`
  through `GetVariable`; when it is false it sets `activated` and `isActive`
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

## 21. Acts, act bosses and boss soul pieces

What ForgePact's boss soul pieces work (ForgePact #197, hub #489) read about
acts, act bosses and key items on 2026-10-11: through the `ghidra` MCP on build
`498d588550d8`, and through local byte scans of `Hero_Siege.exe` and `data.win`
whose positive controls were `PickupLoot`'s known callers and a known object
event row. Each claim carries its label: **static reading** (a local reading
of the game, in our own words), **measured** (naming the live session that
measured it; all slot 14: ForgePact #197's Live procedure 1, 2026-10-11, and
Live procedure 3, 2026-10-11, with the x64dbg debugger, both on a research
build; Live procedure 2 (attempt 2, its capture's second check block) and
Live procedure 4, 2026-10-12, on the player build, the latter with the
debugger; captures `forgepact-197-boss-soul-pieces-live-<n>`, local to the
hub's workorder folder; and the piece icon and stack follow-up's Live
procedures 1, 2 and 4, 2026-10-12, on research builds with the debugger, and
its Live procedure 3, the same day, on the player build, captures
`forgepact-197-piece-icon-stack-live-1`, `-live-2`, `-live-4` and `-live-3`,
in the same folder) or **not established**. The mod's design, its live procedures
and their results are in ForgePact's
[`docs/boss-soul-pieces-research.md`](../ForgePact/docs/boss-soul-pieces-research.md).
The MCP's callers and xrefs answers were empty for every function read here,
which is "not observed", not "has no callers": compiled GML calls scripts by a
direct `call rel32` that the import's reference table does not hold.

### 21.1 The act of a room (`RoomActIndex`)

- `gml_Script_RoomActIndex` (3474) takes a room and answers its act itself, 1
  to 9: it answered 1 in `Town_01_rm` and in `Act_01_01` and 2 in `Act_02_01`.
  **Measured** (ForgePact #197's Live procedure 1, 2026-10-11). An earlier
  static reading took the answer for the act less one; that reading was wrong.
- It is a switch over 175 room constants into nine cases. Its result starts
  undefined and only a matching case sets it, so any room outside the 175
  answers undefined. **Static reading** (2026-10-11). **Measured** otherwise:
  in `Act_01_Boss` and `Act_01_Pregame`, two rooms outside the switch, it
  answered the boolean `false`, not undefined (Live procedure 3, 2026-10-11).
  A reader that takes only a whole number 1 to 9 as an act handles both.
- More rooms measured: 2 in `Town_02_rm` and in `Act_02_Boss` (Live procedure
  3), and the act the player build's `soulpiece status` took from the answer
  was 2 in `Act_02_02` and none in `Act_01_Boss` (Live procedure 2, 2026-10-12).
  All agree with the table.
- A byte scan for direct call sites found two callers,
  `gml_Script_FetchActTexPages` (1574) and the texture manager's `Other_4`
  event, so the game itself uses the answer to pick an act's texture pages.
  **Static reading** (byte scan, with `PickupLoot`'s callers as its positive
  control).
- Rows per act, 1 to 9: 21, 24, 16, 15, 14, 20, 17, 19 and 29. Besides the
  act's zones, the switch holds the act's town where it has one (no
  `Town_08_rm` row), boss dungeons, side dungeons and cellars, the act's
  `Unstable_Rift_*` rooms, `Uber_Inoya_rm` (act 1), `Multiplayer_Highscores_rm`
  (act 6) and five `Dev_5_Mika_Test_*_rm` rooms (act 9). A room's name does not
  always give its act: `Act_08_Orres_Lair_rm` is act 4. **Static reading.**
- Rooms not in the switch: `Act_01_Boss`, `Act_03_Boss`, `Act_04_Boss`,
  `Act_05_Boss` and `Act_07_Boss` (while `Act_02_Boss`, `Act_06_Boss`,
  `Act_08_Boss` and `Act_09_Boss` are in it), and the fourth act 8 rift: rifts
  `Unstable_Rift_08_01..03` and `_05` are rows, and `hs-game-sdk` has no room
  named `Unstable_Rift_08_04`. **Static reading** (the list). Such a room
  answers the boolean `false`: **measured** in `Act_01_Boss` and
  `Act_01_Pregame` (Live procedure 3, 2026-10-11), not read in the others.
- The full table, room by room with its `hs-game-sdk` room index, is
  `hs-game-sdk/curated/room_acts.json`. Room indices move between builds; a
  consumer that needs a room's act at run time asks `RoomActIndex` by name
  rather than shipping the table.

### 21.2 Act boss rooms and their bosses

- `Act_01_Boss` (room 12) to `Act_09_Boss` (room 109) place no instance of any
  descendant of `Enemy_Child_Boss_obj` (1407) in their room instance lists.
  Each places a `Pentagram_Boss_obj` (3409), beside a `Boss_Block_obj` (682),
  an `Enemy_Creator_obj` (1415) and an `Enemy_Creator_Ancient_obj` (1410).
  **Static reading** (`data.win` room lists, read locally).
- The pentagram's Step event names every act boss room and calls
  `gml_Script_PlayMusic` (2434), `gml_Script_ScreenShake` (450) and
  `gml_Script_NetworkSendBoss` (2557), and the last of these only sends a
  network message. So the act boss arrives at run time. **Static reading** (the
  pentagram's Create, Alarm_4 and Step events).
- The pentagram makes the boss. Its Create reads the player's distance and the
  instance variables `bossSpawned`, `bossesKilled`, `allPlayersIn` and
  `instantSpawn`; its Alarm_0 creates the room's boss with
  `instance_create_layer` on the game layer, at the pentagram, choosing the
  object by room. The objects it can create include `Gurag_obj`, `Reaper_obj`,
  `Anubis_obj`, `Damien_obj`, `Karp_King_obj`, `Satan_obj`, `Mevius_obj` and
  `Odin_Cutscene_obj`, besides other rooms' bosses; `Cthulhu_obj` is not among
  them (**not observed**). Which room maps to which object was not read, so the
  table below stays the decor's evidence. **Static reading** (Alarm_0,
  2026-10-11).
- `Boss_Block_obj`'s collision with the player tests for eight boss objects:
  Uber Anubis, the Architect, Phantom Leviathan, Cthulhu, Uber Reaper, Kaelith,
  Captain Grimtide and the Blood Maiden. **Static reading.**
- Which boss belongs to which act, read from the decor each act's boss room
  places (no room names its boss outright):

  | Act | Boss object | Decor in the act's boss room |
  |---|---|---|
  | 1 | `Gurag_obj` (2014) | `Gurag_Dungeon_*`, `Gurag_Board_obj` |
  | 2 | `Reaper_obj` (4013) | `Winter_Reaper_*`, `Reaper_Flames_*` |
  | 3 | `Anubis_obj` (241) | `Pyramid_*`, `Pyramid_Anubis_Statue_Dark_obj` |
  | 4 | `Damien_obj` (1115) (inferred) | `Nightmare_Demon_*` and satanic props |
  | 5 | `Karp_King_obj` (2368) (inferred) | `Sea_*`, `Fuji_*` |
  | 6 | `Satan_obj` (4266) | `Satan_Light_obj`, `Satan_Pentagram_Trail_obj` |
  | 7 | `Mevius_obj` (2705), named by the owner, 2026-10-11 | `Bad_Trip_*`, which names no boss |
  | 8 | `Odin_Phase_1_obj` (3276) | `Odin_Cutscene_obj`, `Odin_Pillar_*` |
  | 9 | `Cthulhu_obj` (1043) | `Cthulhu_*` |

  **Measured** for acts 1 and 2: their rooms' pentagrams brought out
  `Gurag_obj` and `Reaper_obj` (ForgePact #197's Live procedures 3 and 2).
  **Static reading (boss room decor naming the boss)** for acts 3, 6, 8
  and 9; acts 4 and 5 are an **inference** (their decor names no boss; Damien
  and Karp King are what remains of the Key of Terror's six once acts 1-3 and 6
  are placed, and the decor fits them); act 7's boss the decor does not name
  and the owner chose (2026-10-11). The SDK also names
  `Bad_Trip_Mevius_Painting_obj`, `Mevius_Boss_mus` and a room
  `Act_08_Mevius_Intro`; whether `Act_07_Boss` places a Mevius painting was not
  read. All nine named objects descend from `Enemy_Child_Boss_obj` through
  `Enemy_Parent_obj` (`hs-game-sdk`'s parent table, `Mevius_obj` checked
  2026-10-11 the same way as `Gurag_obj` and `Reaper_obj`). The Key
  of Terror's parts name six bosses (Gurag, Death, Damien, Anubis, Karp King
  and Satan), which agrees with acts 1 to 6 as a set and says nothing about
  their order. **Static search.**
- The game already has an item named "Gurag's Soul", one of the Key of
  Terror's parts, in repository category 13. **Static search.**
- Karp King and four uber bosses spawned in Act_01_01 were killed there with
  their drops. Setting a monster's HP to 0 kills it through its own death path,
  but Uber Endrixia, Uber Anubis and Uber Luna do not die that way, and a boss
  spawned in town removes itself (§ 13.1, measured; the spawn route is not
  named there).
- The act 2 boss created outside its own room crashed the game when killed;
  the Karp King did not. A `Reaper_obj` created with `instance_create_depth` in `Act_02_01` and killed
  by setting its `enemy_hp` record to 0 closed the game with an access
  violation: `Enemy_Child_Boss_obj`'s Destroy event ran
  `gml_Script_LoadBossDeath`, which found no `Pentagram_Boss_obj` in the room.
  A Karp King created and killed the same way in `Act_01_01` died without a
  crash; why the two differ is **not established**. **Measured** (ForgePact
  #197's Live procedure 1, 2026-10-11). Whether the other seven act bosses
  crash the same way outside it was not measured.
- In its own room an act boss comes out of the pentagram and dies safely, for
  acts 1 and 2. `Act_01_Boss`'s pentagram brought out `Gurag_obj` and
  `Act_02_Boss`'s `Reaper_obj`; the pentagram's Alarm_0 ran before Gurag
  appeared; each, set to HP 0 through its `enemy_hp` record, died with
  `gml_Script_LoadBossDeath` running and the game running on, the Reaper
  (Live procedure 1's crash case) included; right after each death a portal
  stood in the room (labelled "Danethorpe" and "Village of Mos'Arathim" on
  screen; that the kill made it was not established). **Measured**
  (Live procedure 3, 2026-10-11, debugger logpoints on the alarm and the death
  script). Gurag killed in an ordinary fight, the room then left by the town
  portal key, did not crash either (Live procedure 2, 2026-10-12). Acts 3 to 9
  were not visited.
- That an act boss killed in its own room counts toward its act's quest or
  completion, after arriving there by a route other than the game's own
  travel or after its room's state was dropped, is **not established**; no
  quest or act message showed in either session.

### 21.3 Key items: the repository, the Key tab and stacking

- `gml_Script_GetNormalRepoStruct` (818) reads the global `itemRepoNormal` by
  category and index (weapons by a sub-index as well), and raises the runtime's
  array-index error for an index past its category's end. **Static reading.**
  So a saved item whose `b` lies past its category's end cannot load unless
  something added that entry first: **inference, not measured**. This is why a
  mod item that must survive the mod's removal reuses an existing repository
  entry rather than adding one.
- Category 12 (keys) holds 44 entries (§ 13.2), and `data.win` names 44
  `keys_*` strings: `ancient`, `angelic`, `ankh_eternal_death`,
  `ankh_infernal_death`, `axe`, `aztec`, `battle`, `bifrost`, `boreal`,
  `cellar`, `chaos`, `cloud`, `copper`, `crystal`, `curacan`, `devils`,
  `frosted`, `garden`, `golden`, `hellflame_torch`, `hive`, `key`,
  `key_of_infernal_terror`, `key_of_terror`, `magma`, `mysterious`, `mystic`,
  `naga_scale`, `parasitic`, `pickaxe`, `ruby`, `rusted`, `shovel`,
  `smelly_cheese`, `storage`, `tablet_of_armada`, `tablet_of_leviathan`,
  `tablet_of_parasite`, `tomb`, `tower`, `treasure`, `valhalla`, `valor` and
  `warp` (each `keys_<word>`, most ending `_key`). **Static search.** Which
  index holds which name is **not established** statically; ForgePact's
  `droprate list 12` prints the runtime's order.
- `gml_Script_GetDungeonKeys` (1638) builds the 26-entry pool `DropDungeonKeys`
  picks from (§ 13.3) out of global constants whose values are not visible
  statically, so which 26 keys it holds is **not established**. **Static
  reading.**
- The bag's Key sub-tab (`InventoryTabKey`, § 17): the slot-name table holds
  `inventoryKeyGrid`, by analogy with `inventoryMaterialGrid` the Key tab's
  grid; the object that owns it is **not established**. It holds no
  `stashKeyTab`- or `stashKeyGrid`-like name, so keys live in the bag's Key
  sub-tab and a stash tab for keys was **not observed**. The table also holds
  `itemSprite`, whose meaning is **not established**. **Static search**
  (`tools/decomp_index.py find-name`). On a built Gem of Incarnation
  `itemSprite` read undefined (§ 18.4, **measured**).
- Stacking: `gml_Script_ItemsAreStackable` (1923) needs both items defined,
  consults the first item's `GetItemInfo` method (a closure, in `hs-game-sdk`
  as `gml_Script_GetItemInfo_anon_5277_s_ItemInstanceStruct_InventoryV2Funcs`
  (2035), a name that moves with every patch, §5.3), which can answer false
  for reasons not read, and then answers true only when the two items'
  `itemType` match and their `itemDefinitionStruct`'s `b` and `c` match. The
  seed `a` and the count `o` are not compared by this predicate. **Static
  reading.** A byte scan for its direct call sites found none (the same scan
  found `PickupLoot`'s four callers), so how the game reaches it is **not
  observed**.
- The pickup route. `PickupLoot`'s general path ends in
  `gml_Script_AddToInventory` (109, § 10.7). Offline, `AddToInventory` reads
  the item's class and info and asks `gml_Script_GetItemPreferredGrid` (1986),
  which answers a grid of the item's own kind for keys, materials,
  socketables, tarot cards and the vault class (it picks `inventoryKeyGrid` and
  its sibling grids by `itemType`) and none for a consumable. With a preferred
  grid, `AddToInventory` first tries `gml_Script_GridAddToStack` (1963) on that
  grid, and only if that takes nothing `gml_Script_InventoryGridAddToStack`
  (1962); with none, it tries `InventoryGridAddToStack` alone. Only when no
  stack takes the item is it placed as a new one (`InventoryGridAddItem`,
  `GridAddItem`). Online it goes through `OnlineAddToStack` instead. A byte
  scan for direct call sites, whose positive control found the known
  `InvGridClearItemNode` call in `UiAInventoryConsumeItemConfirm`, found one
  `GridAddToStack` site and two `InventoryGridAddToStack` sites in
  `AddToInventory`. **Static reading** (ForgePact #197's piece icon and stack
  follow-up, 2026-10-12). This corrects Replan 1's reading (2026-10-11), which
  had the two stack scripts the other way round: the tab classes through
  `InventoryGridAddToStack` and the bag through `GridAddToStack`. The corrected
  reading fits both of Live procedure 3's measurements below: a consumable's
  pickup reached `InventoryGridAddToStack`, and the key merge reached
  `AddToInventory` and not `InventoryGridAddToStack`, because `GridAddToStack`,
  not watched in that session, took the key. The follow-up's Live procedure 1
  (capture `forgepact-197-piece-icon-stack-live-1`) then watched it: a piece
  on `keys_bifrost_key` with a whole `b` merged into the owner's Bifröst Key
  stack (38 to 39) with a `GridAddToStack` logpoint logging the pickup and
  the `InventoryGridAddToStack` one not, the control logging in the same
  window. **Measured.** So that merge is `GridAddToStack`'s. Separately, § 9.7
  measured `InventoryGridCanAddToStack` then `InventoryGridAddToStack` for a
  material on the prospecting grid.
- What a stack compares. `InventoryGridAddToStack` and `GridAddToStack` walk
  their grid and merge into an item whose class (`itemType`) matches and whose
  definition's `b` and `c` match, comparing those fields themselves; neither
  calls `ItemsAreStackable`. The seed `a` is never compared. `GridAddToStack`
  first accepts only classes 12, 13, 14 and 15, the same classes
  `gml_Script_IsItemTypeStackable` answers true for. A class-11 consumable has
  no preferred grid and never reaches `GridAddToStack` (the pickup route
  above), only `InventoryGridAddToStack`. That it does not stack in the bag is
  measured (below). `c` is the repository flag (0 normal, 1 unique, § 2
  and § 13.10), so changing it loads a different item: no whole-number value
  of a field the merge compares can mark an item apart from the real one (a
  fraction in `b` can in `GridAddToStack`, by the reading that follows; how
  `InventoryGridAddToStack`, which `AddToInventory` tries when
  `GridAddToStack` takes nothing, compares `b` for the classes it accepts is
  **not established**). **Static reading** (Replan 1).
- Why `InventoryGridAddToStack` refuses a consumable. The class rule:
  `gml_Script_IsItemTypeStackable` (1921) answers true for classes 12, 13, 14
  and 15 only, and `gml_Script_IsStackable` (1922) first asks the item's
  `GetItemInfo` method for one value (which info key it asks for was not
  resolved), answers false when that value is truthy, and otherwise applies
  the same four-class rule. `InventoryGridAddToStack` takes the item as its
  second argument and applies the `IsStackable` rule itself, before anything
  else; when the rule fails it gives up at once, before it reads a grid or
  compares any field. So a class-11 item is refused whatever its `b`, `c`,
  seed or count. For a class that passes, it picks its grid by class (15 the
  socket grid, 12 the Key grid, 13 and 14 the material grid), and a later
  walk reads the bag's `inventoryTab` under a condition that was not read. A
  merge goes ahead only while the two counts summed stay at most 999. Every
  path, the early refusal included, ends by building the game's
  `gml_Script_s_ItemOperation` (1959) struct and returning it, and
  `AddToInventory` reads that result's `success` at each of its stack
  attempts. § 9.7 measured a successful result's fields on the prospecting
  grid (`tabNumber`, `x`, `y`, `tabType`, `success`); whether
  `AddToInventory` reads any field but `success` was not read. **Static
  reading** (2026-10-12, ForgePact #197's piece icon and stack follow-up).
  So no consumable base or class stacks through the game's own stack code:
  only classes 12 to 15 pass the rule, and each of those goes to its own tab
  (the Key, material or socket grid), not the bag, while no value in a
  class-11 item's own definition gets it past the rule.
- How the compare is made. `GridAddToStack` compares `itemType`, then the two
  definitions' `b`, then their `c`, each through the runtime's general value
  compare, which takes two reals as equal when they differ by no more than the
  math epsilon (GameMaker's default is 0.00001; whether the game sets another
  is **not established**). So a `b` of 2.1 differs from 2 and matches 2.1.
  **Static reading** (2026-10-12). How `InventoryGridAddToStack`, which
  `AddToInventory` tries when `GridAddToStack` takes nothing, compares `b` is
  **not established**. In session it held: key pieces with `b` 2.10 (seed
  777101) and 2.20 (777102) on the Bifröst Key's definition stayed apart from
  the real key (`b` 2) and from each other, and a second 2.10 piece joined the
  first through `GridAddToStack` (`o` 2); pieces with `b` 2 and `c` 0.05 did
  the same. **Measured** (the follow-up's Live procedure 1, `frac-apart-key`,
  `frac-stack`, `frac-apart-act`, `cfrac-stack`, `cfrac-apart`). Whether such
  a `b` or `c` survives a save was not observed: that session's stop did not
  save the bag (§ 9.5).
- The repository lookup truncates. `GetNormalRepoStruct` turns its index
  argument into an integer through the runtime's real-to-int conversion, which
  truncates toward zero, so a `b` of 2.1 looks up entry 2. The item
  constructor takes `gml_Script_GetUniqueRepoStruct` (819) when the
  definition's `c` is truthy (to the runtime, a real above 0.5) and
  `GetNormalRepoStruct` otherwise. **Static reading** (2026-10-12). The MCP's
  reference table holds no caller of `GetUniqueRepoStruct`, which is **not
  observed**, not "has none".
- How the save writes a definition. `gml_Script_CreateItemSaveStruct` (693)
  copies the item's definition, and `gml_Script_json_ordered_by_key` (691)
  writes it, sending every real and int64 value through the `string` builtin.
  **Static reading** (2026-10-12; variable slots named with
  `tools/decomp_index.py slot-name`). GameMaker's `string()` of a real keeps two
  decimals and prints a whole number whole; that is the runtime's documented
  behaviour, not read in this game. So a `b` carrying tenths would survive a
  save and reload, and one with a finer fraction would not: **inference, not
  measured**.
- The bag's save writer. `gml_Script_SaveInventoryOrderNew` (3507) writes the
  bag's tabs and the special tabs (key, material, socket, tarot, relic, vault
  and charms) through `json_stringify`. **Static reading** (2026-10-12). The
  game writes the bag file as § 9.5 says (the inventory window's Destroy and
  the Game End event), not at every stop. In the piece icon and stack
  follow-up's Live procedure 1 (2026-10-12, research build, capture
  `forgepact-197-piece-icon-stack-live-1`, local to the hub's workorder
  folder), the bag file `inventory_order_13.hss` was not rewritten at the
  graceful stop, while the Key tab held pieces with a fractional `b`; that
  stop ended in the game's fail-fast exit (`STATUS_STACK_BUFFER_OVERRUN`,
  C0000409). **Measured.** Neither Live procedure 1 nor Live procedure 2 made
  the game save the bag, so neither session's bag file holds what it built.
  Live procedure 4 (capture `forgepact-197-piece-icon-stack-live-4`) did, by
  closing the stash: the bag file then held two class-11 piece stacks with
  their counts (`o` 3 and 2) and a plain logo, and after a relaunch the bag
  held all three with the same counts. **Measured** (§ 9.5).
- Who else compares `b`. `gml_Script_CountInventoryItem` (1925), whose direct
  callers the byte scan found to be only the crafting scripts
  `GetCraftItemsAvailable` and `CraftFindRecipeItems`, compares `itemType`, an
  item-info value and the definition's `b`, not `c`.
  `gml_Script_FindInventoryItem` (1920), called from `PlayerMouseAction` and two
  unnamed sites, compares `b` and `c`. Both go through the same epsilon
  compare. **Static reading** (2026-10-12). Which code a door or an NPC uses to
  find the key it wants (Heimdall's Bifröst Key and the rest) was not read, so
  whether a key with a fractional `b` would open anything is **not
  established**.
- The merge, measured. Two items built on the Bifröst Key's definition
  (`keys_bifrost_key`) with seeds 777101 and 777102, and named "Piece of
  Gurag's Soul", joined the owner's own Bifröst Key stack on pickup (its count
  `o` went 39, 41, 43; the stack kept its own seed), and the merge survived a
  reload. **Measured** (ForgePact #197's Live procedure 1, 2026-10-11). So a
  seed cannot keep a key apart from the real key of its definition in the Key
  tab. A both-route detour on `ItemsAreStackable` counted no call through the
  merges (log and veto mode); no call to it was seen anywhere in the session,
  so the hook has no positive control and the zero is **not observed**, not a
  negative. With the static reading above (the two stack scripts compare
  inline and do not call it), the predicate was not seen on the pickup route
  that merged them; whether any other script on that route reaches it is **not
  established**.
- The pickup route and the stack rule under the debugger. Non-breaking
  logpoints on the scripts' first bytes, with a `CheckTalentUse` control
  logging in the same windows: replaying the key merge (a piece on
  `keys_bifrost_key`, the owner's Bifröst Key stack going from 38 to 39, the
  piece taken by the game's own pickup) hit `AddToInventory` once and neither
  `InventoryGridAddToStack` nor `ItemsAreStackable`, so which code merged the
  key was **not established** by measurement (the corrected pickup reading
  above attributes it to `GridAddToStack`, which was not watched). Five class-11 items on the Edible PAS Logo's
  definition (three seeded 777101, one 777102, one plain logo) picked up one
  by one each hit `AddToInventory` and then `InventoryGridAddToStack` with the
  same `self`, and never `GridAddToStack`: a consumable's stack attempt goes
  through `InventoryGridAddToStack`, as the corrected reading above has it
  for an item with no preferred grid. All five stayed separate bag items with count 1, so class 11 does not
  stack whatever the seed. **Measured** (ForgePact #197's Live procedure 3,
  2026-10-11; the player build's pieces again in Live procedure 2, 2026-10-12,
  three pieces in three cells over two bag tabs).
- A stack result written by a detour is taken as the game's own. In the
  follow-up's Live procedure 2 (capture
  `forgepact-197-piece-icon-stack-live-2`, research build, x64dbg logpoints
  on `AddToInventory`, `InventoryGridAddToStack` and `SaveInventoryOrderNew`
  with a `CheckTalentUse` control): with ForgePact's merge off, two class-11
  pieces of one act took two cells, each pickup hitting `AddToInventory` and
  `InventoryGridAddToStack` once. With it on, a both-route detour on
  `InventoryGridAddToStack` called the game first (its result a struct with
  `tabNumber`, `x`, `y`, `tabType` and `success`, `success` false), then
  raised a same-act bag piece's `o` from 1 to 2, refreshed its hash and wrote
  `success` true and that piece's tab and cell into the result; the game
  then finished the pickup as for a stack it made itself: the picked-up
  piece left the ground and took no cell, and the counts summed to the
  pieces picked up. The logpoint and the detour's own call count rose by the
  same three, so the detour saw every call the logpoint did. **Measured.**
  Whether `AddToInventory` reads any field of the result but `success` was
  not separated. The bag draws a class-11 item's count on its cell when `o`
  is above 1 (a small "2"); the tooltip names the item and shows no count.
  **Measured** (the same session, `stack-draw`, `stack-tooltip`). The player
  build stacked two pieces per act the same way (Live procedure 3,
  `on-bag-stack`, `on-apart-act`).
- Already in this reference: `LootGroundCreate` writes a fresh seed into `a`
  (§ 18.4); `InitItemFromJson` followed by `LootGroundCreateFromItem` keeps the
  definition it was handed (ForgePact #74's `sigdrop`; relics placed with the
  player as `self`, § 10.7); a bag drop reaches `LootGroundInit`, and the loot
  announcement's creation guard tells it from a fresh build (§ 16.11); `sCP` is
  the game's own spawner that stamps the spawned flag (§ 20.5); and the gem
  roll a soul piece rides, `DropGems` with `GetDropRate`'s per-place
  overrides (§ 18.4).

### 21.4 Using an item from the backpack

Read on 2026-10-11 through the same MCP and build, for the owner's choice that a
soul piece is used by right-clicking it in the backpack, the way a PAS token is;
the last two bullets are what ForgePact #197's Live procedures 1, 3 and 2
measured, and the parts of the right-click and confirm bullets labelled
measured are the piece icon and stack follow-up's.

- `gml_Script_UiAInventoryConsumeItemConfirm` (4087) is a UI action, the answer
  to the "use this item?" prompt, and takes three values: the item, a second
  value whose meaning was not read, and the cells the item occupies. It first
  asks `gml_Script_PotionUse` (2813) about the item, and only when that answers
  true does it look the item up, clear the item's cells one at a time with
  `gml_Script_InvGridClearItemNode` (1988), and close the prompt. So the item
  leaves the bag through the cells, after the use itself said yes. **Static
  reading.**
- `gml_Script_CanUsePotion` (2812) reads the item's definition, its info and
  stats, and the current room before it answers. Which of them decides what is
  **not established**. **Static reading.**
- `PotionUse`'s own body is **not established**: the MCP's decompile of it
  timed out, and a second attempt in Replan 1 exceeded the MCP's response
  buffer. That it is one large switch over consumables is an inference, so
  whether a consumable's effect is applied inside it is **not established**.
  `CanUsePotion` reads the item's stats 4 and 22 and the room; whether it
  refuses the Edible PAS Logo in town or in any room is **not established**.
  **Static reading** (Replan 1).
- No script is named for a right-click. The dispatch from the click is inline,
  as the drag's is (§ 17), and a right-click on a class 7 item equips it
  (**measured**, ForgePact's
  [`stash-move-research.md`](../ForgePact/docs/stash-move-research.md)).
  A right-click on a key in the Key tab reaches the equip script, not the
  use: in the follow-up's Live procedure 1 (capture
  `forgepact-197-piece-icon-stack-live-1`) right-clicking a key piece (class
  12, kept apart from the real key by its `b`) opened no prompt, and a
  `CanUsePotion` logpoint stayed at its count with the control logging,
  where the bag logo's right-click in the same session had hit it once; with
  ForgePact's probe detouring the use scripts, the right-clicks reached
  `InvGridEquipV2` twice and `CanUsePotion` and `PotionUse` not at all.
  **Measured.**
- The click's inline dispatch lives in the grid's input script,
  `gml_Script_ProcessInventoryGridInput` (3000). It is too large for the MCP to
  decompile; its calls, listed in address order with a local Ghidra script,
  hold the bag's right-click as `gml_Script_ValidateItem` (1128),
  `gml_Script_VaultUse` (4597), `CanUsePotion`, `gml_Script_MessagePrompt`
  (2393, the "use this item?" prompt), `PotionUse` and `InvGridClearItemNode`,
  then the equip scripts. A byte scan for direct call sites (with the
  `InvGridClearItemNode` call in `UiAInventoryConsumeItemConfirm` as its
  positive control) found `CanUsePotion` called from
  `ProcessInventoryGridInput` alone, and `PotionUse` from it twice and from
  `UiAInventoryConsumeItemConfirm`, `ControllerCheckInput`,
  `DrawMobilePotionIcon` and one unnamed site; the MCP's reference table holds
  no caller of `CanUsePotion` (**not observed**). `ValidateItem`, called
  throughout the input script, builds description strings (type and rarity
  names, the sprite's name, loot name data); no call that removes an item was
  seen in it. **Static reading** (ForgePact #197's piece icon and stack
  follow-up, 2026-10-12). The Key tab's right-click does not take the use
  path (measured, the bullet above); whether `CanUsePotion` would answer true
  for a key is **not established**, since it was never reached.
- The confirm and a stack. After `PotionUse` answers true,
  `UiAInventoryConsumeItemConfirm` compares an item-info value with 6 (what
  that value means was not read) and then clears the item's cells one by one.
  **Static reading** (2026-10-12). The confirm clears the whole stack: in the
  follow-up's Live procedure 2 (capture
  `forgepact-197-piece-icon-stack-live-2`), a bag item of class 11 with `o` 2
  right-clicked, its prompt confirmed and `PotionUse` answering true left no
  item in the bag. When `PotionUse` instead answered false after ForgePact
  lowered `o` by one, the prompt closed with no message, the stack stayed one
  smaller and could still be dragged to another cell, and its last piece,
  answered true, was cleared. **Measured** (`stackuse-all`, `stackuse-one`,
  `stackuse-after-false`, `stackuse-move`, `stackuse-last`); the player build
  took one piece from a stack of 2 the same way (Live procedure 3,
  `on-takes-one`). What the item-info value compared with 6 means is **not
  established**.
- `ConsumeToken` (631) and `gml_Script_ConsumeBPToken` (632) are Blood Pact
  token bookkeeping, not the use of an item. **Static reading**; their callers
  were not observed.
- The owner's "PAS token" is the Edible PAS Logo,
  `consumable_edible_pas_logo`: class 11, `b` 12, crafted in the session
  (sprites `Edible_Pas_Logo_spr` and `Pickup_Edible_Pas_Logo_spr`, craft key
  `craft_consumable_edible_pas_logo`, static search; `data.win` and the
  `translations*.csv` files hold no item named "PAS token"). Right-clicking it
  in the backpack and confirming reached these scripts, each call carrying the
  item: `CanUsePotion` (self `UI_Inventory_Grid_obj`, one argument, answering
  true), `PotionUse` (self `UI_Button_Small_obj`, three arguments, answering
  true), `InvGridClearItemNode` (self the bag grid, two arguments, the item
  through its fingerprint) and `UiAInventoryConsumeItemConfirm` (one array
  argument; that the array holds the three values the first bullet reads is
  **not established**), and the logo was used up. A potion drink reaches
  `PotionUseFlask` and `PotionUse` with self `Profile_Manager_obj` and no
  item. **Measured** (ForgePact #197's Live procedure 1, 2026-10-11).
- The logo's repository name is `consumable_edible_pas_logo`, category 11,
  index 12, and its own use opens a portal to Sheeponia (a
  `Portal_Sheeponia_obj` to `Sheep_rm`). A logo built with a reserved seed
  (777101, 777102) and another name goes through the same right-click and
  confirm: `CanUsePotion` and `PotionUse` were called carrying it, and when
  `PotionUse` answered true without running the logo's own use, the game
  cleared its cell (`InvGridClearItemNode`, then the confirm action) and no
  Sheeponia portal opened. `CanUsePotion` answered true for it in
  `Town_01_rm` and `Act_01_01`. **Measured** (Live procedure 3, 2026-10-11,
  research build). The player build's use went through the same way from
  `Act_01_01`, `Town_01_rm` and `Town_02_rm` (Live procedure 2, 2026-10-12).
  Whether
  `CanUsePotion` refuses the logo in some other room is **not established**.

### 21.5 Portals and travel between rooms

Read in Replan 1 of ForgePact #197 (2026-10-11, the same MCP and build), when
the design was a portal from a soul piece to its act's boss room. Live
procedure 3 (2026-10-11) measured that portal failing and the game's own
`NetworkRoomGoto` reaching the room, so the owner chose a direct transfer and
no portal ships; Live procedure 2 (2026-10-12) measured the shipped transfer.
The last three bullets are those measurements; the rest is static reading.

- A portal keeps its state in the protected store. `Portal_Parent_obj`'s Create
  allocates protected records and keeps their keys in the instance variables
  `isEligible`, `pSpwd`, `portalZone`, `portalUsable` and `portalActive`, so
  reading `portalZone` gives a key, and the room is that record's value (the
  way a monster's `enemy_hp` and `damage` hold keys, § 13.1 and § 13.7).
  `Portal_obj` (3593), a child of `Portal_Parent_obj`, writes a room into its
  `portalZone` record in its own Create (a room reference by default). The
  collision with the player it inherits checks the portal's active, eligible
  and entering state and the player's interact press, and sets an alarm;
  `Portal_obj`'s Alarm_0 reads the room from the `portalZone` record and calls
  `gml_Script_NetworkRoomGoto` with it. **Static reading.**
- The other portal objects `hs-game-sdk` names: `Portal_Town_obj`,
  `Portal_Dungeon_Exit_obj` and `Portal_Hell_obj` also descend from
  `Portal_Parent_obj`; `Portal_Uber_Boss_obj` takes its target from uber
  state, and `Portal_Waypoint_obj` (a `Slope_Parent_obj` child) opens the
  waypoint menu. `Portal_obj` is the general one, whose target is only a room.
  **Static reading** (and the SDK's parent table).
- The game's travel scripts. `NetworkRoomGoto(room)` checks whether the room
  is a town (`CheckTown`), sends network effects online, and offline ends in
  `gml_Script_RoomGoto(room)`. `RoomGoto` sets the room's layers up once
  (`SetupRoomLayers`, remembered in `roomSetupMap`) and then calls the
  `room_goto` builtin. **Static reading.** A raw `room_goto` to
  `Uber_Inoya_rm` closed the game (§ 13.1, **measured**); whether the setup
  `RoomGoto` adds would have prevented that is **not established**.
- A `portalZone` record of a `Portal_obj` created at run time, written with a
  boss room through `PC_SetVariableGMLWrapper`, read that room back at once
  (`after=12` for `Act_01_Boss`, `after=26` for `Act_02_Boss`). Read again
  before entry, the same key resolved to another room: `Act_01_Pregame` (13)
  for the portal opened in `Town_01_rm`, `Act_01_02` (3) for the one opened in
  `Act_01_01`, matching the labels on screen ("River of Inoya", "Fields of
  Battle"). Both portals opened in town and entered took the player through
  their Alarm_0 and `NetworkRoomGoto` to `Act_01_Pregame` (the second, for
  `Act_02_Boss`, was not read again before entry, but its label also read
  "River of Inoya"); the one opened in `Act_01_01` was not entered.
  `NetworkRoomGoto` called
  with `Act_01_Boss` or `Act_02_Boss` reached that room, whose pentagram then
  brought out Gurag or the Reaper, who died there without a crash; the zone a
  portal was opened in still loaded on a revisit, the portal with it.
  **Measured** (ForgePact #197's Live procedure 3, 2026-10-11, capture
  `forgepact-197-boss-soul-pieces-live-3`). What rewrites the record after
  creation, and whether a write that persists would route the portal to a boss
  room, is **not established**. The owner's reading (2026-10-12), not
  measured: the run-time `Portal_obj` is probably the kind of portal that is a
  door to the neighbouring zone, not one that honours a boss room.
- Which travel scripts run. Logpoints on the scripts' first bytes, with a
  control logging: entering a `Portal_obj` ran its Alarm_0 and then
  `NetworkRoomGoto` with the same `self`; the town portal key (V) and the
  waypoints ran `NetworkRoomGoto` and no `Portal_obj` Alarm_0. `RoomGoto` was
  not watched: on that research build its entry began with a jump where the
  game's copy has its first instruction (some hook's detour, which one is not
  established), so the byte check refused the breakpoint. **Measured** (Live
  procedure 3, 2026-10-11).
- The shipped transfer: `NetworkRoomGoto` with an act boss room's index
  (resolved from its name through `asset_get_index`) and the local player as
  `self`, called from ForgePact's frame callback on the tick after the piece's
  use, moved the player into `Act_01_Boss` (from `Act_01_01` and from
  `Town_01_rm`) and into `Act_02_Boss` (from `Town_02_rm`) within seconds, with
  no portal on screen, three times out of three. **Measured** (Live procedure
  2, 2026-10-12, player build; once more from `Act_01_01` in Live procedure 4).

### 21.6 Zone state and a boss room's return

Read in Amendment 2 of ForgePact #197 (2026-10-11, the same MCP and build, with
variable slots named by `tools/decomp_index.py slot-name`), for the owner's
choice that every soul piece brings a fresh boss fight, even after the boss was
killed.

- A room's contents outlive the player's leaving it through the game's zone
  state, a global map `zoneStates` keyed by room.
  `gml_Script_ZoneStateSaveController` (4636), run as the player leaves a room,
  stores the room in it with `gml_Script_ZoneStateSave` (4634) unless one of
  these holds: the controller's `skipZoneStateSave` flag is set (it clears the
  flag and saves nothing; `gml_Script_ZoneGenRestart` (3611) sets that flag
  before `room_restart`); the room's name starts with `Unstable_Rift_` or
  `Chaos_Tower_` (two prefixes found by a byte scan of the string table; which
  test reads which is not settled); the room is `The_Labyrinth_01_rm` (230) or
  `The_Labyrinth_02_rm` (231); or the controller's `zoneStateReset` flag is
  set. In the last three cases it calls `ZoneStateResetSingle` on the room
  instead and clears that flag. **Static reading** (Amendment 2, 2026-10-11).
  Further conditions on the save branch (a pass over the players' rooms, an
  `endAction` value) were not fully read, so that an act boss room, which none
  of the exclusions names, is saved on leaving is a reading, not a
  measurement.
- `gml_Script_ZoneStateResetSingle` (4632) takes a room index, the same value
  the controller passes, and, when `zoneStates` holds a state for it, frees
  that state and deletes the room's entry; its body writes no quest, act,
  waypoint or save-file value. `gml_Script_ZoneStateExists` (4621) answers the
  room entry's `zoneVisited` value, and false when there is no entry. **Static
  reading** (Amendment 2, 2026-10-11). The MCP's reference table holds no
  caller of `ZoneStateResetSingle`, which is **not observed**, not "has none"
  (the controller's call above is one). ForgePact's density code has a detour
  for it (`fp_density_window_single`), but the installer that holds it,
  `InstallDensityLifecycleHooks`, has no caller, and Live procedure 4
  (2026-10-12, player build) read the script's first bytes as the game's own.
- `Pentagram_Boss_obj`'s Create sets `bossSpawned` and `bossesKilled` afresh
  every time the pentagram is created, and its Create, Step and Alarm_0 read no
  quest, act-completion or boss-killed flag: Alarm_0 checks `bossSpawned` and
  whether the boss object exists, and one other event reads a protected value
  in `Niflhel_01_rm` (204) only. So, as far as the pentagram's own events go,
  nothing but its instance state decides whether the boss comes out; whether a
  revisit restores that state from the zone state, and whether the boss object
  or the room's creation code reads a kill flag, was not read. **Static
  reading** (Amendment 2, 2026-10-11).
- A revisited zone gets new instance ids at the same positions with its
  creators' protected state restored (§ 11.2, **measured**, ForgePact #181's
  Live 4), and Live procedure 3 measured the same for a zone's portals (§ 21.5).
- A boss room is saved on leaving, and after its entry was dropped the boss
  came out again; whether it would come out without the drop is not
  established (below). With the room value `asset_get_index` returns for a room's name (a
  reference) and the local player as `self`, `ZoneStateExists` answered true
  for `Act_01_01` and for the towns just after the player left them, false for
  `Act_01_Boss` and `Act_02_Boss` on the first entry of a launch, and true for
  `Act_01_Boss` after Gurag was killed there and the room left by the town
  portal key (V). The next entry from a soul piece asked `ZoneStateExists`
  (true), called `ZoneStateResetSingle`, asked again (false), and then
  travelled: Gurag came out of the pentagram again. **Measured** (ForgePact
  #197's Live procedure 2, 2026-10-12, player build, the mod's own
  `saved=`/`after=` answers and boss bars on screen). The same three calls,
  in that order, one argument each and one `self`, hit debugger logpoints on
  the scripts' entries for one transfer, while the game's own travel (town
  portal, waypoint) hit `ZoneStateExists` several times and
  `ZoneStateResetSingle` not at all (Live procedure 4, 2026-10-12). So the
  game calls `ZoneStateExists` itself, which the MCP's reference table had
  left unobserved.
- **Not established**: what `gml_Script_ZoneStateLoad` (4625) restores for a
  boss room (that a re-entry after a kill, without the reset, finds no boss is
  the owner's account; no session re-entered that way); whether `zoneStates` reaches the save file and survives a relaunch
  (the first entry of a launch read no entry, but no saved boss room was
  carried across a relaunch); what else a boss room's state holds (loot left
  on its floor, the portal a kill leaves), since nothing was left on the floor
  before a reset; and whether a boss killed again after its room's state was
  dropped credits its act's quest a second time.

### 21.7 An item's display sprite (`itemInfoStruct["11"]`)

Collected for ForgePact #197's piece icon and stack follow-up (2026-10-12).
The first measurements are ForgePact #158's (its Live procedure 1, 2026-10-12,
on that issue's own branch, not on #197's), the last three bullets the
follow-up's own; § 16.3's info-key table lists key `"11"`, and ForgePact
#158's own measurements of it are § 23.5.

- `itemInfoStruct["11"]` is the sprite an item is drawn with. A charm given a
  Grand charm's sprite under key `"11"` drew the Grand charm's icon both in
  the bag and lying on the ground. **Measured** (ForgePact #158's Live
  procedure 1).
- The ground item draws a sprite of its own, which it looks up by name as
  `Pickup_` followed by the item sprite's name. **Static reading** (ForgePact
  #158). A sprite added at run time with `sprite_add` under key `"11"` drew in
  the bag and the game's error sprite on the ground, which fits: no `Pickup_`
  sprite of that name exists. **Measured** (ForgePact #158's Live procedure 1).
- The tooltip drew no icon for any charm, whatever key `"11"` held.
  **Measured** (ForgePact #158's Live procedure 1). Whether the tooltip draws
  an icon for any other item class is **not established**.
- Key `"11"` is not saved: an item whose value was changed showed its base
  icon again after a reload. **Measured** (ForgePact #158's Live procedure 1).
- The Gem of Incarnation's two sprites: `hs-game-sdk`'s sprite table holds
  both `Gem_Incarnation_spr` (9644) and `Pickup_Gem_Incarnation_spr` (15659),
  so the gem's sprite has the ground companion the lookup above wants.
  **Static search** (`hs_game_sdk.sprites`; sprite indices move between
  builds, so a consumer resolves them by name through `asset_get_index`). A
  built Gem of Incarnation carries `Gem_Incarnation_spr` under key `"11"`
  (its `itemSprite` read undefined, § 18.4). **Measured** (the follow-up's
  Live procedure 1, capture `forgepact-197-piece-icon-stack-live-1`,
  `gem-sprite`).
- What a soul piece given that sprite under key `"11"` shows (the same
  session): the bag and the Key tab drew the gem's icon on it, a real key
  beside it its own; on the ground the piece kept its base's own pickup
  sprite (`Pickup_Bifrost_Key_spr` on a key base, `Pickup_Edible_Pas_Logo_spr`
  on the logo), never `Pickup_Gem_Incarnation_spr` and never the error
  sprite; neither the key's nor the consumable's tooltip drew an icon, and
  both named the piece. **Measured** (`icon-keytab`, `icon-legacy-bag`,
  `icon-ground`, `icon-tooltip`). Why the ground differs from #158's charm,
  whose ground item drew the sprite under key `"11"`, is **not
  established**.
- After a save and a reload, a piece stack showed its piece's name, lore
  line and the gem's icon even with ForgePact's research probe's dress and
  icon off and `soulpiece` never on (the follow-up's Live procedure 4,
  capture `forgepact-197-piece-icon-stack-live-4`, `reload-base`); the
  plugin had registered its pieces' Custom Forge entries (name, lore and
  sprite, matched by base and seed) at boot, as it does in every session, so
  whether key `"11"` and the name were saved with the item or put back by that
  registration was not separated. **Measured** for that load; what a piece
  shows with the plugin removed is **not established**.
- An armour piece (ForgePact #166's Mark 1 Body Armor, a class 1 item given
  a sprite added at run time under key `"11"`, and given a ground copy of
  its own by the plugin's `LootGroundInit` consumer): the bag drew the `"11"` sprite, the
  ground drew the plugin's ground copy, the **worn** body-armour slot drew
  the same `"11"` sprite as the bag, and the tooltip drew no item icon at
  all, only its text rows. Before the plugin set key `"11"`, the same piece
  showed its base item's own bag icon and ground sprite, never the error
  sprite. **Measured** (the Mark 1 research's Mod live 2, 2026-10-19,
  `art-default`, `art-load`, `art-ground`, `art-bag`, `art-equipped`,
  `art-tooltip`:
  [Mod live 2 results](../ForgePact/docs/mark1-set-research.md#mod-live-2-results)).
  So the worn slot reads key `"11"` as the bag does, and the tooltip draws no
  icon for armour either, as for charms; for a class other than charms,
  keys, consumables and armour it is still **not established**.

---

## 22. Adding our own content: art, drawing, input, spawning and blockers

Folded 2026-10-12 (hub #498) from HS-AFK-Expedition, which built a whole
in-game Stronghold: its own art in a repurposed room, a panel over the game's
UI, its own input, spawned monsters and gates. Only what AFK **measured** is
here. Its recipes, inferred claims, open questions and superseded attempts, each
with the AFK commit it comes from, are in
[docs/research/afk-expedition-adding-content.md](research/afk-expedition-adding-content.md);
"AFK §n" below points there. Measured 2026-09-17..10-07. The 2026-09-17 PHASE0 runs
behind §22.8 and its §15 rows were on the earlier build,
`exe-281798144-pe6a9ed3ee-111c3000`, from before the 2026-09-18 update; the
later runs that name a build name `exe-281751552-pe6aaa6779-111b8000`.
§22.9 has a second source, the owner's local Seraph prototype (measured
2026-09-23..24, no build named); AFK's builds above do not apply to it.

### 22.1 Our own art

- **`sprite_add(path, frames, false, false, 0, 0)` loads a PNG at runtime**, and
  the result draws in the world as a layer sprite. A multi-frame PNG is one row
  of equal frames. **Measured** (AFK §1.1). What kind of value `sprite_add`
  returns on this runner is **not established**.
- **The automatic bounding box counts every pixel above alpha 0.** Generated
  art carries a faint halo (alpha 1-8): one piece measured 527×998 visible but
  1152×1144 with the halo. `sprite_collision_mask(spr, false, 0, 0,0,0,0, 1, 16)`
  re-measures it at alpha tolerance 16, after which `sprite_get_bbox_*` give the
  visible part. **Measured** (AFK §1.2).
- **An atlas cell becomes its own sprite** by drawing it onto a surface
  (`draw_sprite_part`) and calling `sprite_create_from_surface`. This worked
  from a plugin's per-frame callback, outside any draw event. **Measured** (AFK
  §1.4).
- **`font_add(path, size, false, false, 32, 8230)` loads a TTF** that draws in
  the GUI. **Measured** (AFK §1.7). Its texture-memory cost was not measured.

### 22.2 Placing art in a room

- **Layer sprites** (`layer_create`, `layer_sprite_create` and the
  `layer_sprite_*` setters) draw art in a room without creating instances.
  Layer sprites given depth −y/2 sorted correctly with the hero and monsters.
  **Measured** (AFK §2.1, §2.2). That every game object uses −y/2 is not
  established.
- **Layers die with the room.** Leaving the room removes every layer and layer
  sprite created in it. **Measured** (AFK §2.5).
- **Two sprites on one layer have no set draw order.** A piece that must be in
  front needs its own layer. **Measured** for the fix (AFK §2.3).

### 22.3 Texture groups

- **The game streams 254 dynamic texture groups by region. A sprite whose group
  is not loaded draws nothing and raises no error**, although its layer element
  exists. `Guild_Master_NPC_spr` (`act_2_tex`) drew nothing in Town_01 until
  `sprite_prefetch`; `npc_tex` sprites (`Tristan_NPC_spr`) are loaded
  everywhere. **Measured** 2026-09-26 (AFK §3.1, §9.2).
- `texturegroup_get_names`, `texturegroup_get_sprites` and
  `texturegroup_get_status` (0 unloaded, 1 loading, 2 loaded, 3 fetched) work at
  runtime, as do `sprite_get_texture` with `texture_is_ready`. **Measured** (AFK
  §3.2).
- **Monsters spawned outside their own act drew once their sprites were
  prefetched**: `sprite_index`, the object's sprite, and every instance variable
  named `enemy_*`, `enemy_corpse` or `shadow_sprite`. **Measured** (AFK §3.4).
  That they do not draw without the prefetch is inferred from the NPC case
  above, not observed.

### 22.4 Drawing over the game's UI

- **YYToolkit's object-event callback (`EVENT_OBJECT_CALL`) returns
  `AURIE_UNAVAILABLE` on this YYC build.** An inline detour on a compiled event
  function resolved by its name (`gml_Object_<obj>_<event>`) works instead.
  **Measured** 2026-09-26 (AFK §4.1).
- **Town GUI event order:** `Loot_Manager_obj` Draw GUI Begin,
  `Controller_obj`, `UI_Inventory_Drag_obj`, `Menu_Controller_obj` Draw GUI,
  then `objColorBlindShader` Draw GUI End
  (`gml_Object_objColorBlindShader_Draw_75`) last. Drawing right after it puts
  a window above the inventory, a dragged item and menus. `Draw_64` is Draw GUI,
  `Draw_74` Draw GUI Begin and `Draw_75` Draw GUI End. **Measured** (AFK §4.2,
  §4.3).
- **GUI size equals the monitor resolution** (2560×1440 on the owner's PC).
  **Measured** 2026-09-30 (AFK §4.5).
- **The cursor.** The game hides the Windows cursor (`window_get_cursor()` is
  `cr_none` in play) and puts back any `window_set_cursor`. It draws `Cursor_spr`
  from `Menu_Controller_obj` in an earlier GUI step, scaled by
  `global.mouse_gui_scalar` (default 2); `Screen_Cursor_obj` has no instance in
  play. Anything drawn later covers the cursor unless `Cursor_spr` is drawn
  again on top. **Measured** (AFK §5.7).
- **`effect_create_depth` effects: not observed to display.** None of 56
  `ef_spark` effects created by `effect_create_depth` (2026-09-27, `Act_02_01`,
  monster depth − 1) was visible, and the calls raised no error. There was no
  positive control, so whether effects can display on this build, and why these
  did not, is not established (AFK §9.1).

### 22.5 Input and the game window

- **`EVENT_WNDPROC` with `Override(0)` keeps a message from the game.** A
  swallowed press or key never reaches `mouse_check_button` / `keyboard_check`,
  while unswallowed ones do, in town and in combat. Posted `WM_*` messages
  reach the game's input, also while it is minimized. **Measured** (AFK §5.1,
  §5.4).
- **Activating a menu node.** Calling the menu's `UiAMainMenuLocal`,
  `UiAChooseSaveSlot` and `UiACharacterPlay` scripts directly entered the hero
  but broke later mouse clicks on the inventory Extra tab and skill selection.
  Running `event_perform(7, 25)` on the `UI_Node_Parent_obj` instance whose
  `activationFunc` names the script, with that node as self and other, did not.
  **Measured** 2026-10-07 (AFK §5.8). See §8.1 for UI nodes.
- **The runner's window class is `YYGameMakerYY`.** `WM_CLOSE` to it exits with
  code 0; `WM_CLOSE` to YYToolkit's console window ends the game with
  0xC000013A and no normal save. **Measured** 2026-09-28 (AFK §5.11).

### 22.6 Spawning monsters

- **`instance_create_depth(x, y, depth, obj)` spawns a monster with the current
  room's stats.** `enemyRarity` and the affixes (`affixList` plus the
  `enemyAffix` flag array) set right after creation are applied when the stats
  are built. `aggroRange` is reset to 300 then, so it must be set a frame later.
  **Measured** (AFK §6.1-§6.3). AFK also sets `distance` a frame later; that the
  game resets `distance` was not observed.
- **A monster spawned in a town removes itself within a second.** Answering the
  room routines `CheckTown` false and `RoomIsZone` true, and answering
  `GetAct`, `GetMonsterLevel` and `ReturnEnemyStats` for a reference zone, only
  while the hero is in that room, makes an unused room behave like that zone,
  with the game's own stats, loot and XP. **Measured** (AFK §6.4, §6.7).
- **Monsters were moved and killed only within about one screen of the hero**,
  with deaths at 650 px and 8 of 12 at 750 and 850 px. Appending ids to
  `Controller_obj.monsterHandleArray` after `ActivateDeactivateProps` returns
  kept far monsters stepping. **Measured** (AFK §6.5, R2/R8). That the game
  steps only that array's members is inferred, and the result fits either
  rebuild routine: compare the static reading of the enemy loop in §11.3, which
  names `EnemyStepHandleNew` as what rebuilds that array.
- **Kill parity.** Health written to 0 runs the death, but `DropItem` ran only
  about half the time and no XP was given. `DropItem` with the player-kill
  arguments plus `EnemyGiveExperience(self = monster, other = player,
  killExperience)` matches a hero kill. **Measured** (AFK §6.11). AFK waits 60
  frames before hitting a spawned monster, on the assumption that its drop table
  is built shortly after creation; that the table is built late is **not
  established**.

### 22.7 Blockers, the path grid and rooms

- **`Invisible_Wall_obj`**, created with `image_xscale`/`image_yscale` set to
  size/32 and `addToMinimap = true`, is found by `collision_point` and drawn on
  the minimap. **Measured** 2026-10-07 (AFK §7.1). **Whether it stops the hero's
  own movement was not observed**: AFK never walked the hero into one (AFK
  §7.2). For what blocks the player, see §19.
- **The path grid.** `PathFindControllerCreate` (self and other = the hero)
  rebuilds `global.pathGrid`, an mp_grid of `global.gridSize` 16 px cells sized
  from the room, from the room's blockers. A monster's own cells count as taken,
  so a search must start from the next free cell. **Measured** (AFK §7.3, §7.4).
- **A sealed-in hero makes every outside ground monster's search flood the
  whole field**: a 20-monster wave froze the game for about 20 s at 3 fps.
  Setting the monster's `pathFailed = true` skips the search. **Measured**
  2026-09-29 (AFK §7.7).
- **The minimap** is refreshed with `MinimapRefresh` (self = hero) and the
  `objMinimap` dirty flags. Its discovery grid can be replaced by a 256×256 town
  grid after it reports ready. **Measured** (AFK §7.9).
- **`RoomGoto(room)` with `Controller_obj` as self and other travels.**
  `Dev_10_rm` is an unused 4000×4000 room that `room_set_width`/`height` widen
  before entry (9600×9600 measured). The game never saves the hero there.
  **Entering `Act_01_06` from code crashed the game.** **Measured** (AFK §8.1,
  §8.2, §10.1).

### 22.8 Crashes found on the way

Also listed in §15. **Measured** (AFK §10.2-§10.6), on the earlier build
`exe-281798144-pe6a9ed3ee-111c3000` (2026-09-17, PHASE0_NOTES), except one of
the protected-handle crashes, which recurred on 2026-09-24 in a run that names
no build:
- reading a protected handle far out of range (`PC_GetVariableGMLWrapper` on id
  999999) crashes the game; a gold amount mistaken for a handle crashed the
  anti-cheat module;
- `EnemyGiveExperience` with no argument crashes; `ExperienceUpdate` called
  directly reports a hash mismatch through `ReportClient`;
- a struct held only in C++ `RValue`s is freed by the runner's GC between frames
  (§5.9);
- `instance_destroy` on a monster skips its death and `DropItem`.

### 22.9 Replacing a draw and drawing above the actors (Seraph)

Folded 2026-10-12 from the owner's local Seraph prototype, which drew one
White Mage character as an original custom character. It was measured
2026-09-23..24; its notes name no game build. The recipes, labels and source
pointers are in
[docs/research/seraph-custom-sprites.md](research/seraph-custom-sprites.md)
("Seraph §n" below).

- **The player's body is one `draw_surface_ext` call.** `Player_obj`'s Draw
  composes the body into a 300×300 surface, `playerSequenceData.sequenceSurface`,
  with the ground point at its centre. It draws that surface once, at the
  anchor minus 150 × scale, with the jump and slope offsets applied. A
  name-resolved inline detour of `draw_surface_ext`, filtered to that one
  surface handle, replaced the body in 10,582 frames with 0 errors and
  followed a camera zoom. **Measured** (Seraph §1.1–1.3).
- **White Mage geometry.** The body is 46–47 px tall, and its **feet are
  16 px below the player's position**, measured from 40 read-backs of the
  body surface. Running speed is 205–217 px/s (211 on average) in all four
  directions, measured from the player's `x`/`y` change per frame.
  **Measured** (Seraph §2.6).
- **`buffer_get_surface` reads a surface's RGBA into memory.** Use
  `buffer_create(w*h*4, 0, 1)`, then `buffer_get_address`. **Measured**: it
  returned the body's opaque bounds (Seraph §2.5). That the surface is left
  unchanged is GameMaker's documented behaviour, inferred.
- **Baked sprites draw crisp.** Cells drawn onto a surface with
  `gpu_set_blendenable(false)` and `gpu_set_texfilter(false)`, then passed to
  `sprite_create_from_surface`, drew on the game's pixel grid. This extends
  §22.1's atlas-cell recipe. **Measured**. That alpha survives byte for byte
  is inferred.
- **A `DrawHud` pre-pass draws above every actor and under the HUD.** A
  detour of `gml_Script_DrawHud` (installed with `InstallScriptHook`) drew
  world art first and then called the original. World coordinates were
  mapped through `view_camera[0]`:
  `(wx - camera_get_view_x) * display_get_gui_width / camera_get_view_width`.
  One factor was used for both axes, which assumes the GUI and the view share
  an aspect ratio. **Measured**: the art was seen above the actors and below
  the HUD. All of Seraph's skill-effect drawing, in the body draw and in this
  pre-pass while a cast was active, averaged about 0.1 ms per draw call
  (Seraph §3.1).
- **A `Player_Damage_Parent_obj` the mod creates does damage when it is kept
  alive for two steps.** Seraph spawned one per contact, with the carrier's
  captured payload and an ellipse mask, kept it for exactly two steps and then
  removed it. **Measured**: 14 of 14 contacts lowered enemy health, read
  before and after through `gml_Script_PC_GetVariableGMLWrapper` (Seraph
  §2.8). Why one step is not enough is the package's reading of the game, not
  established live: the stats load into the object after that frame's
  collision pass. No recorded control shows a one-step object failing after
  the transport fix.

---

## 23. Charms

What ForgePact's flight-charms research (#158, phase 1) read about charms,
item size and the unique rolls on 2026-10-11, in the build Ghidra imported
(the one `py -3 tools/decomp_index.py build-hash` names), through the ghidra
MCP and a local scan for the names a function's code references. That
research's Live 1 measured part of it on 2026-10-12 (research DLL sha256
`ef6af41d4bd3ff478f3516a30dc46c4dd699caed8ab383ef5a5aeb7558ac323f`, slot 14
"Sorak", `Town_01_rm`), and each claim below says whether it is a static
reading or measured. The procedure, its checks and the Decision keys they
settle are in ForgePact's
[`docs/flight-charms-research.md`](../ForgePact/docs/flight-charms-research.md),
the measurements in its
[Live 1 results](../ForgePact/docs/flight-charms-research.md#live-1-results).
A caller list is the direct call sites the reading found. It is blind to calls
through the script table or a method value, so a caller it does not list is
not observed, not absent.

### 23.1 Equipped charms

- Offline, `gml_Script_GetPlayerCharmData` (493) answers, for player number
  p, `Controller_obj.inventoryData[p - 1].localCharmItemArray`: the same
  `inventoryData` entry the relic tab lives in (§ 2, where its key rule is
  measured). Online it answers `Client_obj.players[p].charmItemArray`.
  **Static reading** (2026-10-11).
- `gml_Script_UpdateCharmData` (491) rebuilds that array. It walks the
  entry's `inventoryCharmGrid` nodes and takes each distinct
  `nodeFingerprint` once, so a charm covering several cells is counted once.
  It resolves each fingerprint to its item through `GetOnlinePlayerItemOwner`
  (2031) and `GetItemFromFingerprint` (2046), as § 2 does for a relic, and
  pushes the item onto the array. Its direct callers are `RunItemEquipped`
  (3483) and a `Client_obj` closure. **Static reading** (2026-10-11).
- So the equipped charms are read from `localCharmItemArray`, not through a
  worn slot's fingerprint as the Miner's Helmet's equipped read is. **Static
  reading** (2026-10-11).
- Read live, `localCharmItemArray` lists the charms in the charm grid, each
  once, each with type `t` 10: twelve worn charms of sizes 1x1 to 1x5, then three
  charms dragged into the grid from the ground appeared in it, and charms
  moved from the grid to the bag left it. A charm in the bag is not in it.
  **Measured** (2026-10-12).
- **One charm per definition `b` above a rarity line, so one flight charm at
  a time.**
  - The game lists only one charm with flight at a time. **Owner-stated**
    (2026-10-12): "Only one charm with flight can be enabled at one point.
    This is how game works".
  - `UpdateCharmData` enters every ordinary charm, but when an item-info
    value it reads for the charm is 6 or more, it enters that charm only if
    no charm with the same definition `b` was entered before, keeping a map
    keyed by `b` for the purpose. **Static reading** (2026-10-13). That the
    value is the rarity (`"27"`, 6 being Satanic and above, § 16.4) is
    **inferred**, not read.
  - ForgePact's three flight charms all carry `b` 0, so they count as one;
    the one listed is the first the walk meets, and the walk's order is **not
    established**.
  - A game unique charm does carry `b` 0: the unique repository answers
    `{10, 0, 0}` with `charms_raiders_torch`, rarity 6 (Satanic), 1x2, not
    flagged hidden. **Measured** (2026-10-13, ForgePact's Mod live 2,
    `unique-b0`, through `charmprobe repo`). So by the reading above it would
    pair with the flight charms; that is an **inference**, and wearing the
    two together was not tried.
  - With Gabriel Wings and Witch's Broomstick both in the charm grid,
    `localCharmItemArray` listed the Wings only, while two normal Small
    Charms of Bastion were both listed. **Measured** (2026-10-12, ForgePact's
    Mod live 1, S14 and S17). Measured again on 2026-10-13 (Mod live 2,
    `broom-alone` and `one-flight`): the Broomstick worn alone was listed;
    with the Wings added beside it, only the Wings were. Both times the grid
    still drew the unlisted charm, and its tooltip showed.
  - So a worn charm the game does not list adds nothing, its stats included.
    **Inference** from the game reading this array, not measured.

[Mod live 1 results](../ForgePact/docs/flight-charms-research.md#mod-live-1-results),
[Mod live 2 results](../ForgePact/docs/flight-charms-research.md#mod-live-2-results)

### 23.2 Item size

- `gml_Script_GetItemSize` (1976) calls the item's own `GetItemInfo` method
  (2035, `GetItemInfo@anon@5277@s_ItemInstanceStruct@InventoryV2Funcs`)
  twice, each time with a constant key and one shared default, and returns
  the two answers as a pair: the item's footprint in grid cells. **Static
  reading** (2026-10-11).
- `GetItemInfo` takes a key and a default and answers that item's
  `itemInfoStruct[key]`, or the default when the key is undefined. So an
  item's footprint is read off the built item's `itemInfoStruct`, the struct
  the Custom Forge already writes (`"27"`, `"28"`, `"29"`, `"32"`; § 16.1).
  **Static reading** (2026-10-11).
- The footprint is held by the `itemInfoStruct` keys `"2"` (width in cells)
  and `"3"` (height), so `GetItemSize` answers those two. Inferred from twelve
  worn charms of six sizes and read back on a scratch struct (written 2x3
  read 2x3, written 4x1 read 4x1); normal Small, Large and Grand charms read
  1x1, 1x2 and 1x3. **Measured** (2026-10-12).
- Writing `"2"` and `"3"` as 2 and 2 on a charm's built struct before it is
  placed gives a ground item whose `GetItemSize` answers 2x2, and the bag
  gives it 2x2 cells. **Measured** (2026-10-12).
- `GetItemSize` has 38 direct callers across the grid scripts, among them
  `InventoryGridAddItem` (1964), `GridHasSpace` (1966),
  `InventoryGridHasSpace` (1967), `InventoryGridHasSpaceMulti` (1968),
  `GridAddItem` (1970), `InventorySortTab` (1983), `InvGridEquipV2` (1990),
  `InventorySwapItemsNew` (2047), `ProcessInventoryGridInput` (3000) and
  `CraftEditGrid` (757). Whether every reader of an item's size goes through
  it is **not established**. **Static reading** (2026-10-11). The bag
  honoured a written footprint. So did the charm grid (2x2 and 1x5 charms
  drawn on 2x2 and 1x5 cells) and the stash's Personal tab (a 1x5 charm
  dragged in took 1x5 cells). **Measured** (2026-10-12, ForgePact's Mod
  live 1, S14 and `stash-size`). The crafting grid was not tried.
- A save keeps only an item's compact definition (§ 16.1, measured), so a
  footprint written into a built item's `itemInfoStruct` is not saved and
  would have to be written each time the item is built. What a saved grid does
  when such a footprint appears or goes away was a **static reading**
  (2026-10-11) for the consequence; Live 1 measured both directions:
  - Gone: after a save and a reload of the character with no rule writing it
    again, the 2x2 charm came back 1x1 with its base icon, and nothing was
    lost, duplicated or overlapped. **Measured** (2026-10-12).
  - Appearing: a 1x1 charm whose right and lower neighbours were occupied was
    built 2x2 on the reload (the rule applied). The game did not crash and
    did not overlap the neighbours, but the charm was no longer at its cell
    or on the bag's Extra tabs 1 to 3. The Main tab and Extra tab 4 were not
    checked, so where it went is **not established**. **Measured**
    (2026-10-12).

### 23.3 Charm stats and the player stats

- `GetPlayerCharmData`'s direct callers are `GetItemStats` (1682) and five
  sites in `LoadSpecificStat` (2296), so the player's stat aggregation reads
  the equipped charms. **Static reading** (2026-10-11).
- A stat written on a charm's built struct counts toward the player's stats:
  a charm spawned with stat 25 (Increased Movement Speed) at 100 kept
  `25=100` after pickup and equip, and the character sheet's Movement Speed
  rose from 151% to 251% (the owner's reading; the owner notes a soft cap at
  228%). A 2 s walk covered the same distance before and after, with the
  inventory open both times; why is **not established**. After a save and
  reload the stat was gone from the charm, as § 16.1's compact save predicts.
  **Measured** (2026-10-12).
- The item stat ids a charm carries are the Item Editor's numbering: 25
  Increased Movement Speed (%), 159 Physical Damage Taken Reduced by (%), 160
  Magic Damage Taken Reduced by (%), and 162 a flat Damage Taken Reduced by,
  from all sources. `hs_game_sdk.stats.StatId` numbers stats another way (it
  gives 19 for movement speed), so it is not the item stat id. Not a static
  reading of the game: the Item Editor's stat catalog, not measured.

### 23.4 Which roll drops a unique of which rarity

- `gml_Script_DropUniqueItems` (1424), called from `LoadDrops` (2171), picks
  one entry of `Controller_obj.lootListUnique[k]`, with k from 0 to 4 taken
  from a protected zone value that has a random chance of stepping up. It
  keeps the entry only when the entry's rarity, field 27 of its
  `GetUniqueRepoStruct` (819) entry (§ 13.4), is below Angelic (7) and the
  entry is not flagged hidden, then calls
  `CreateDefaultParams` (2349) and the placement. **Static reading**
  (2026-10-11).
- `gml_Script_DropItemHeroic` (1374) takes a position and a list index that
  defaults to 5. It draws from `lootListUnique` at that index until an entry
  is unflagged and is neither Angelic (7) nor Unholy (10), so it can give a
  Heroic or a Satanic unique, then calls `CreateDefaultParams` and the
  placement. Its direct callers are `VaultUse` (4597) and a Chaos Tower NPC
  closure. **Static reading** (2026-10-11). Called by name with the local
  player as `self` (which `self` the game's own callers pass was not read
  then; see the 2026-10-20 bullets below), ten calls placed
  ten items: seven Heroic (9) and three Satanic (6), none Angelic or Unholy,
  and no charm. **Measured** (2026-10-12).
- Read again on 2026-10-20 for ForgePact's Mark 1 drops (#166), through the
  hub's ghidra MCP and, for the two callers the MCP could not decompile, a
  headless decompile on the same build (`498d5885…`). The bullets below
  extend the one above.
- `DropItemHeroic` (1374) takes three arguments: an x, a y and a sub-list
  index. When the x or the y is undefined it reads that coordinate from
  `self`; when the index is undefined it uses 5. **Static reading**
  (2026-10-20).
- It draws a random entry of `Controller_obj.lootListUnique` at that index
  and draws again whenever the entry is not an array. For a triple it looks
  the entry up in `GetUniqueRepoStruct` (819), one lookup per draw, and keeps
  it only when the definition's flag 40 is clear and its rarity (field 27,
  § 13.4) is neither 7 nor 10; otherwise it draws again, until it keeps one.
  So, unlike `DropUniqueItems` (§ 23.8), a call never comes up empty: an
  entry listed r times among the T_H entries of the sub-list that pass both
  tests comes out r / T_H of the time, whether or not the random index can
  reach the list's length. **Static reading** (2026-10-20).
- Once an entry is kept it calls `CreateDefaultParams` (2349) once, from the
  entry's sub-type and base and a constant, and then one unnamed placement
  routine with the position, the entry's own type and those parameters
  (§ 23.8 names `LootGroundCreate` for the ordinary roll). So the placed
  item's class is the entry's type, as in the Angelic roll, and an entry
  standing in for another item must share that item's class. **Static
  reading** (2026-10-20).
- Its direct callers, by a byte scan for direct calls (`FindCallers.java`;
  in the same run `CreateDefaultParams` showed 177 direct sites, the positive
  control): exactly two, one in `VaultUse` (4597) and one in an unnamed
  closure that reads `floor` and `towersCleared` around the call, the Chaos
  Tower NPC closure named above. A call through the script table is invisible
  to that scan. The ghidra MCP's callers, callees and disassembly for
  `DropItemHeroic` and `VaultUse` are empty: not observed, never "none".
  **Static reading** (2026-10-20).
- `VaultUse` runs when a vault item (repository category 19 "vault", seven
  entries, § 13.2) is used by its right-click in the bag, the inline dispatch
  of [§ 21.4](#214-using-an-item-from-the-backpack). Its body sorts the used
  vault into one of seven tiers, 0 to 6, from a value it asks `GetItemInfo`
  for (which value was not read; that the seven tiers are category 19's seven
  vaults is an inference). It sets the roll's sub-list index to 4 and moves
  it to 5 on a random check whose threshold rises with the tier (400, 800,
  1000, 1500 and 2500 for tiers 0 to 4, 6500 for tiers 5 and 6). A second
  random check, with thresholds 1, 5, 10, 30 and 50 for tiers 0 to 4 and 100
  for tiers 5 and 6, sends the use to an unnamed draw of the Angelic kind
  (next bullet) instead of `DropItemHeroic`; tier 5 then asks that draw for
  rarity 7 only and tier 6 for rarity 10 only. The random draws' bound, and so
  the chances themselves, were not read. When it does call `DropItemHeroic`
  it passes its own `self` and `other`, the x and y of an instance it resolved
  earlier in the body (which instance was not read), and that index. So a
  vault's Heroic roll reads sub-list 4 or 5, not always the default 5.
  **Static reading** (2026-10-20).
- The unnamed draw `VaultUse` sends the rest to lies just before
  `DropItemAngelicChance` (1368) in the executable. Its body takes the same
  three arguments with the same fallback to `self`'s position, draws from a
  unique list (which one was not read) until the kept entry's rarity is 7 or
  10 (only 7, or only 10, when its third argument says so), then calls
  `CreateDefaultParams` and the placement. That it is `DropItemAngelic`
  (1366), one of the drop scripts the 2026-09-24 import left unnamed, is an
  inference from its body and its place. **Static reading** (2026-10-20).
- The Chaos Tower closure calls `DropItemHeroic` in a loop, behind a random
  check, a number of times a script works out from `floor`, with all three
  arguments undefined, so the position is the closure's `self`'s and the
  sub-list is 5. **Static reading** (2026-10-20).
- So, as far as is read, the Heroic roll runs when a player uses a vault or
  that NPC, and not on a kill. **Static reading** (2026-10-20).
- Not a reading of the game, and not measured: the Item Editor's catalog
  (`hs_full_catalog.json`) lists 13, 15, 17 and 17 Heroic uniques of classes
  0, 1, 2 and 4. Which of them `lootListUnique[5]` (380 entries, § 13.4) or
  `[4]` holds is not established. ForgePact's `mark1probe pool` reads `[5]`
  ([Phase 3 static reading](../ForgePact/docs/mark1-set-research.md#phase-3-static-reading)).
- What the Heroic roll keeps on its lists, read by ForgePact's `mark1probe
  pool` in Mark 1's Mod live 4 (2026-10-20, slot 14, nothing pushed):
  `lootListUnique[5]` held 380 entries, of which the roll keeps **T_H = 203**
  (93 of rarity 6 and 110 of rarity 9, counted with repeats); 48 are rarity
  7 (31) or 10 (17), the T = 48 the Angelic roll keeps, and 129 are flagged
  hidden. `[4]` held 221, of which it keeps 218, all rarity 6, and 3 are
  hidden. Each of the classes 0, 1, 2 and 4 has kept triples on both lists
  (10 to 23 per class and list), and the stand-in Mark 1 chose for each is
  listed once. With one entry pushed per Mark 1 piece, 100
  by-name calls gave 2 pieces, inside the band for 4 / (203 + 4).
  **Measured**
  ([Mod live 4 results](../ForgePact/docs/mark1-set-research.md#mod-live-4-results)).
  Which list a vault's call reads stays a static reading (above), so the
  rate per vault is not measured.
- The ordinary roll's lists 0 to 4, read by `mark1probe pool kill` in Mark
  1's Mod live 5 (2026-10-20): lengths 50, 61, 79, 152 and 221 again (§ 13.4),
  and for each of the classes 0, 1, 2 and 4 a rarity-6 triple the roll keeps
  that is held the same number of times on every one of the five lists (0
  times each). 40 by-name `DropUniqueItems` calls at 200 copies of each piece's
  entry built 35 pieces, all rarity 6, tier 5. **Measured**
  ([Mod live 5 results](../ForgePact/docs/mark1-set-research.md#mod-live-5-results)).
- The Angelic roll keeps only rarity 7 or 10 (§ 13.4).
- So of these three rolls only `DropItemHeroic` can drop a Heroic (9) unique.
  **Static reading** (2026-10-11). This is about the rarity each roll keeps,
  not about which items a kill can give: ForgePact's Mark 1 pieces (#166)
  join the ordinary roll through a Satanic (6) stand-in entry of the piece's
  own class, which that roll keeps, and the rewrite before the item is built
  turns a hit on the stand-in into the piece (the kill route below, and
  [Phase 3 kill route static reading](../ForgePact/docs/mark1-set-research.md#phase-3-kill-route-static-reading)).
- Read again on 2026-10-20 for the Mark 1 pieces' kill route, after the
  owner decided they drop from ordinary kills anywhere, the way the game's
  own SS set items do (White Mage's Sacred set, Zealot's Prophecy), through
  the hub's ghidra MCP on the same build. The bullets below extend those
  above.
- A kill reaches the ordinary unique roll: `Enemy_Parent_obj`'s Destroy event
  calls `DropItem`, which calls `LoadDrops` (§ 13.1), and `LoadDrops` calls
  `DropUniqueItems` (first bullet). Drop type 45 is the type § 13.1 measured
  as "a unique item" by opening every gate on one monster (2026-08-27), so it
  is the gate in front of this roll on a kill. How often type 45's gate
  passes on a kill was not read and not measured. Chests, goblins,
  destructibles and piles reach `DropItem` too (§ 13.1, § 13.6), so they
  reach the same roll; that is an inference. **Static reading** (2026-10-20,
  the kill route), with type 45's meaning **measured**.
- That route holds the only direct call from a kill to `DropUniqueItems`
  (§ 13.12). In ForgePact's Mark 1 Mod live 6 (the drops workorder's Live 3,
  2026-10-20), four natural uniques dropped from kills with `DropUniqueItems`
  not entered and type 45's chance 0 on every `LoadDrops` array (§ 13.1;
  **measured**, one session). That `DropItem`'s own draw builds a kill's
  uniques was then measured by Mod live 7 (§ 13.1, § 13.12).
- `DropUniqueItems` (1424), decompiled again: it picks the sub-list k from 0
  to 4 by a zone value with random step-ups, draws one random index of
  `Controller_obj.lootListUnique[k]`, looks the entry up in
  `GetUniqueRepoStruct`, keeps it only when its rarity is below 7 and it is
  not flagged hidden, then calls `CreateDefaultParams` and the placement with
  the entry's own type. A refused draw places nothing; there is no second
  draw (§ 23.8). There is no branch for set items anywhere in it.
  **Static reading** (2026-10-20, the kill route), agreeing with the first
  bullet and § 23.8.
- The game's set items are ordinary uniques that the unique repository rates
  Satanic (6). In ForgePact's Mark 1 drops live 1 (2026-10-20, D4), a
  by-name call of `DropItemHeroic` placed "Sacred Pendant" from the unique
  repository (`c` 1) at `rarity=6`. In the same session (D5)
  `lootListUnique[4]` held 218 entries with flag 40 clear and a rarity
  neither 7 nor 10, every one rarity 6, and `[5]` held 93 rarity-6 entries
  among its 203 such entries. **Measured** (2026-10-20). The
  ordinary roll keeps every rarity below 7, so a set piece on lists 0 to 4
  can drop from it like any other Satanic unique; that is an inference from
  the reading above. Which sub-lists hold the Sacred or Zealot's Prophecy
  pieces is **not established**.
- `GetSetInformation` maps a set's name to one of 70 set indices. Other
  set scripts exist by name (`GetSetName`, `GetSetNames`,
  `DefineSetPieceRequirements`) and were not read, and how an item names the
  set it belongs to was not read. No drop script names a set (the ghidra
  MCP's function search over "Drop", "Set", "Unique" and "LootList"): not
  observed by name, never "there is none". **Static reading** (2026-10-20,
  the kill route).
- Not established: which sub-lists hold set pieces, how often a kill runs
  drop type 45, and the distribution of k. The MCP's callers and disassembly
  for `DropUniqueItems` are empty, as for `DropItemHeroic`: not observed.
  **Static reading** (2026-10-20, the kill route).
- Not readings of the game, and not measured: HS Offline Tracker's item table
  (`ForgePact/src/forgepact_tracker/item_table.py`) labels the Sacred and
  Zealot's Prophecy pieces "Set", most at grade 6 (SS), with odds of one in
  147,455 to 555,250, and the Item Editor's catalog likewise labels set
  items. Neither label says how the game drops them.
- The Item Editor's catalog (`hs_full_catalog.json`, not a reading of the
  game and not measured) lists normal charms as Small (`b` 0-19, 1x1), Large
  (20-39, 1x2) and Grand (40-59, 1x3), with no normal 2x2 or 1x5 charm. Its 2x2
  uniques include the Angelic melons (`b` 47-50) and Goburin's Head (Unholy,
  98); its only 1x5 is Soul Collector (Unholy, 91); its Heroic 1x1 charms are
  Torstein's Anvil (52), Wizard's Dice (82) and Gladiator's Dice (83). It lists
  Aimbot.exe `{10, 0, 76}` as Satanic, not Heroic.
- The game's own unique repository (`GetUniqueRepoStruct`, field 27) gives
  Aimbot.exe `{10, 0, 76}` rarity 6 (Satanic), Torstein's Anvil (52) 9
  (Heroic), the Water Melon (47) 7 (Angelic, 2x2), Soul Collector (91) 10
  (Unholy, 1x5) and Goburin's Head (98) 10 (Unholy, 2x2, and the only one of
  the five flagged). **Measured** (2026-10-12).

### 23.5 An item's display sprite

- The built item's `itemInfoStruct` key `"11"` holds the item's display
  sprite (each charm's own `Charms_*_spr`). A charm whose key `"11"` was given
  a Grand charm's sprite before it was placed drew the Grand icon on the
  ground and in the bag. Seven keys hold a sprite on every charm sampled, so
  the key was chosen by hand and proven by that control. **Measured**
  (2026-10-12).
- A sprite added at runtime with `sprite_add` (a PNG of our own) and written
  under key `"11"` draws in the bag; the ground item draws the game's error
  placeholder instead. The item tooltip draws no icon for any charm, the
  game's own included. **Measured** (2026-10-12). Why the ground cannot draw
  it is the static reading in § 23.7.
- A save does not keep it: after a reload, and after a full restart that
  never added the sprite, the charm drew its base icon and the game loaded
  normally. The stored value itself was not read (the charm was in the bag,
  which ForgePact's probe does not list). **Measured** (2026-10-12).
- The soul piece's measurements of the same key are § 21.7.

[Live 1 results](../ForgePact/docs/flight-charms-research.md#live-1-results)

### 23.6 Placing a rebuilt item in its grid

Read on 2026-10-12 for ForgePact's flight charms (#158, phase 2), in the same
build and by the same means as § 19.7: the ghidra MCP, existing local
decompiles, and a byte scan for direct call sites. Nothing here is measured
unless a bullet says so.

- `gml_Script_ParseItemToGrid` (1984) walks a saved grid's entries. For each
  one it reads the item's data and its saved position, rebuilds the item
  through `InitItemFromJson` (1883), enters it in a ds_map under its key, and
  then places it at the saved cell through `InventoryGridAddItemPos` (1969).
  **Static reading** (2026-10-12).
- `gml_Script_InventoryGridAddItemPos` (1969) checks the anchor cell first,
  then every cell of the item's footprint as `GetItemSize` answers it
  (§ 23.2). If any of those cells is taken or lies outside the grid, it
  answers false and writes nothing. Otherwise it writes one `s_InvNode` per
  covered cell and answers true. **Static reading** (2026-10-12).
- `ParseItemToGrid` does not look at that answer. So a rebuilt item whose
  footprint no longer fits at its saved cell is left off the grid, though it
  was already entered in the map. That is the reading behind Live 1's
  `dress-added: item-missing` (§ 23.2, "Appearing"). **Static reading**
  (2026-10-12); what the game later does with such an item is not
  established.
- Direct call sites: 31 for `InventoryGridAddItemPos` and 11 for
  `ParseItemToGrid`. **Static reading** (2026-10-12, byte scan).
- A character load places through that call: a debugger logpoint on
  `ParseItemToGrid`'s call to `InventoryGridAddItemPos` logged nothing
  before a save-and-reload and 1114 times during it, while a control
  logpoint kept logging. **Measured** (2026-10-12, ForgePact's Mod live 1,
  `dbg-parse-place`).
- The outcome the reading predicts was measured through ForgePact's size
  guard, which holds a flight charm's placement back until the load returns
  (`guard-kept`): a 2x2 charm saved 1x1 at a bag cell whose right and lower
  neighbours were taken was refused at full size and loaded at that cell at
  1x1, with both neighbours intact. **Measured** (2026-10-12, Mod live 1).
- The bag loads through `ParseItemToGrid` (above). The charm grid most
  likely does too: in both sessions the guard held back as many charms as
  the bag and the charm grid held between them (five, three in the bag and
  two worn, on 2026-10-12; three, two in the bag and one worn, on
  2026-10-13). **Inference** from those counts. Whether the stash and the
  other grids load the same way is not established.

[Mod live 1 results](../ForgePact/docs/flight-charms-research.md#mod-live-1-results),
[Mod live 2 results](../ForgePact/docs/flight-charms-research.md#mod-live-2-results)

### 23.7 How a ground item picks its sprite

Read on 2026-10-12 for ForgePact's flight charms (#158, phase 2), by the same
means as § 23.6, together with the game's data file (`data.win`), whose
sprite table gives each sprite's name and size.

- `gml_Script_LootGroundInit` (2353) is handed the new ground instance as
  argument 0 and the item as argument 1. That argument 0 is the new ground
  instance is **measured** (hidden loot's Live 3, all 1,473 calls, § 16.11);
  that argument 1 is the item stays a reading.
- It sets the new instance's `sprite_index`. It builds a sprite name from a
  constant prefix followed by the name (`sprite_get_name`) of the item's
  display sprite, its `itemInfoStruct` key `"11"` (§ 23.5), and looks that
  name up with `asset_get_index`. When `sprite_exists` accepts the result,
  that becomes `sprite_index`; otherwise `sprite_index` becomes the fixed
  sprite 8223, `Error_spr`. **Static reading** (2026-10-12).
- The prefix is `Pickup_`. The constant's own text did not render in the
  decompile, but the data file names a `Pickup_` ground sprite beside each
  charm icon, sized for the ground: `Pickup_Charms_Aimbot_Exe_spr` 13x13,
  `Pickup_Charms_Normal_Small_Charm_01_spr` 17x11 and
  `Pickup_Charms_Soul_Collector_spr` 34x17. Read from the data file
  (2026-10-12).
- A sprite added at runtime with `sprite_add` carries a name GameMaker
  generates, which has no `Pickup_` companion, so the lookup fails and the
  ground item draws `Error_spr`. That is the reading behind Live 1's
  `sprite-draw: partial` (§ 23.5: our sprite drawn in the bag, the error
  placeholder on the ground). **Static reading** (2026-10-12). The generated
  name reads `__newsprite<n>`: `sprite_get_name` on the ground sprites of
  ForgePact's four Mark 1 pieces, which ForgePact adds with `sprite_add` and
  sets after the game's call, read `__newsprite32286`, `__newsprite32288`,
  `__newsprite32290` and `__newsprite32292`, one per piece in the order they
  were made. **Measured** (2026-10-21, Mark 1 Mod live 10, `soulprobe
  ground`).
  [Mod live 10 results](../ForgePact/docs/mark1-set-research.md#mod-live-10-results)
- `gml_Script_LootGroundDraw` (2355) draws the ground item's `sprite_index`,
  after a glow drawn from its `img`. **Static reading** (2026-10-12).
- `LootGroundInit` has 10 direct call sites. **Static reading** (2026-10-12,
  byte scan).
- A normal Small Charm dropped on the ground got
  `Pickup_Charms_Normal_Small_Charm_01_spr` as its `sprite_index`, the
  `Pickup_` companion of its display sprite. And a flight charm whose ground
  instance ForgePact gave its own ground sprite after the game's call drew
  that sprite, with no `Error_spr`. **Measured** (2026-10-12, ForgePact's
  Mod live 1, `ground-control` and `ground-icon`). That the lookup goes by
  name stays the reading above.
  [Mod live 1 results](../ForgePact/docs/flight-charms-research.md#mod-live-1-results)
- A ground item lying on the town's waypoint shows only its name label,
  whatever its sprite. In Inoya, a Mark 1 piece on the
  waypoint showed its label and no sprite (Mark 1 Mod live 2, 2026-10-19,
  step V2a of its capture `forgepact-166-mark1-set-mod-live-2.md`, kept with
  the hub's workorder files and not tracked), and four pieces placed on it
  showed their four labels and no sprite of any kind while ForgePact had set
  its own sprite on all four (Mod live 9, 2026-10-21). The same four, placed
  138 px south of the waypoint and viewed from 128 px away, showed their
  sprites, and a debugger logpoint on `LootGroundDraw` counted 0 before they
  were placed, 745 hits about 5 s after the player moved beside them and
  2,099 when it was cleared (Mod live 10, 2026-10-21, `art-spawn` and
  `dbg-ground-draw`). **Measured**, for what the screen shows. **Why** the
  sprite is missing is **not established**: no debugger ran with a piece on
  the waypoint (the `LootGroundDraw` count above was taken off it, and the
  two waypoint observations are screenshots), so "drawn, then covered by the
  waypoint" cannot be told apart from "never drawn" (`LootGroundDraw` not
  running for an item there, or the draw skipped). Do not assume a ground
  draw or a draw hook fires for an item on the waypoint. So a ground check
  is made off the waypoint; a count of sprite writes cannot see this.
  [Mod live 9 results](../ForgePact/docs/mark1-set-research.md#mod-live-9-results),
  [Mod live 10 results](../ForgePact/docs/mark1-set-research.md#mod-live-10-results)

### 23.8 The ordinary unique roll makes one draw

Read on 2026-10-12 for ForgePact's flight charms (#158, phase 2), by the same
means as § 23.6. It extends § 23.4's reading of the same roll.

- `gml_Script_DropUniqueItems` (1424) is given a position. It takes
  `lootListUnique[k]` of the first `Controller_obj` (k as in § 23.4) and
  reads one random index of that sub-list. **Static reading** (2026-10-12).
- Only when the entry there is an array does it read the entry's three
  numbers (type, sub-type and base) and look them up in
  `GetUniqueRepoStruct` (819). It keeps the entry when the rarity is below 7
  (Angelic) and the entry is not flagged hidden. It then builds the drop's
  parameters with `CreateDefaultParams` (2349), from the sub-type, the base
  and a constant, and places the item at the position through
  `LootGroundCreate` (2351), with the entry's type. **Static reading**
  (2026-10-12).
- A pick that fails any of those tests drops nothing: there is no second draw
  and no die per entry. So one entry added to a sub-list of L entries is
  picked on 1 call in L + 1, whatever the other entries are, if the roll's
  random index cannot equal the list's length (**not established**; if it
  can, that index drops nothing and the share is 1 in L + 2; the model keeps
  it open as `index_can_reach_length`, `docs/models/unique-pick-spec.md`
  § Not established). **Static reading** (2026-10-12) for the mechanism; the
  share is arithmetic on it, not measured.
- The sub-lists `[0]` to `[4]` this roll reads hold 50, 61, 79, 152 and 221
  entries (**measured**, § 13.4, 2026-10-02), so an added entry is picked on
  between 1 call in 51 and 1 in 222, depending on k, on the same open
  assumption (1 in 52 to 1 in 223 if the index can equal the length).
- Measured with ForgePact's flight charms (Mod live 1, 2026-10-12, and Mod
  live 2, 2026-10-13), calling `DropUniqueItems` by name with the player as
  `self` in `Town_01_rm` (not how the game calls it; `unique-control` is the
  control). **Measured** for each of these:
  - With nothing added, ten calls placed ten Satanic (6) uniques, in each
    session.
  - The lengths were again 50, 61, 79, 152 and 221, in town and in
    `Act_01_01` (Mod live 2, `pool`).
  - With one entry added to each sub-list per call, 100 calls placed 97
    items, one of them the added entry's: within the band one entry's share
    gives, 1 in 222 to 1 in 51 (`rate-elf`). Three calls placed nothing.
  - With 200 copies added, 20 calls placed 19 items, 11 of them the added
    entry's, inside 200 / (L + 200) (Mod live 1, `drop-elf`).
  - These counts are too few to tell one entry's share from a share a few
    times larger or smaller, and k's distribution was not read.

[Mod live 1 results](../ForgePact/docs/flight-charms-research.md#mod-live-1-results),
[Mod live 2 results](../ForgePact/docs/flight-charms-research.md#mod-live-2-results)

[Phase 2 static reading](../ForgePact/docs/flight-charms-research.md#phase-2-static-reading)
