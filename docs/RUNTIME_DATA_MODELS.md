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
| the `room` builtin | a room `VALUE_REF`, not a number; `variable_global_exists("room")` is false |
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
  Stand, 45 Agility. Whether they survive a game build is not known.

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

[toggle skills, Toggle skill table](../ForgePact/docs/toggle-skills-research.md#toggle-skill-table),
[Duration sweep](../ForgePact/docs/toggle-skills-research.md#duration-sweep-session-8-every-classs-timed-skill)

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
- `Hud_In_Combat_spr` is the HUD's in-combat icon. Read from the string table.

[toggle skills, Session 1](../ForgePact/docs/toggle-skills-research.md#session-1-1),
[Session 3](../ForgePact/docs/toggle-skills-research.md#session-3-1),
[Sprite look probe](../ForgePact/docs/toggle-skills-research.md#sprite-look-probe)

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

---

## 12. Mining

- `Mining_Node_obj` variables: `miningActive`, `miningPlayer`, `stop`,
  `range`/`rangeMax` (48/48), `dir`, `miningQue`, `hp` (1, then 0 on reward),
  `miningActivateDistance` (16 px) and a protected `miningReq` (the level
  requirement). **Measured.**
- A dig finishes inside the Step of the key press: level check, then the reward at
  once. Setting `miningQue` sends the node through that same completion on its
  next Step (hit effect, ore, XP, quests, depletion, network message) if the player
  is within `miningActivateDistance`. **Measured.**
- `miningPlayer` starts as `noone` (-4) and is still `noone` when a keyboard dig
  pays out; ground loot this client creates is credited to the local player.
  `GetMiningLevel()` returns the character's mining level. **Measured** and
  **static reading.**
- **The ore reward:** `MiningNodeStepMain` calls `LootGroundCreate` directly.
  Argument 2 (zero-based) is the item type (Material, 14); argument 3 is a params
  struct whose `b` is the base definition and optional `o` the stack quantity
  (absent = 1). Material bases 27–32 are Copper, Iron, Gold, Ruby, Jade and
  Tarethium. Changing `o` on a shallow `variable_clone` scales the pickup.
  **Static reading**, **measured 2026-09-23.**
- `material_mining_*` items have `droprate.base` 50,000,000, so no drop type
  produces them: ore comes only from mining (§13.2). **Measured.**

[miner's helmet, Runtime](../ForgePact/docs/miner-helmet-prototype.md#runtime),
[Ownership fix](../ForgePact/docs/miner-helmet-prototype.md#ownership-fix-2026-09-23),
[mining ore, Observed interface](../ForgePact/docs/mining-ore-research.md#observed-interface),
[Live verification](../ForgePact/docs/mining-ore-research.md#live-verification-2026-09-23)

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
**Measured 2026-08-28** (ForgePact `c0a6a6b`). Whether it reads the base at all,
for example as a weight in the pick between relics, is **not established**: every
relic had the same value, and a uniform divide leaves a weighted pick unchanged.
Changing one relic's base would settle it.
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
  observed. The chance read 1195 or 1526 even with 3000 supplied by the buff, so
  its composition is not established. One roll reads about 8 unique definitions
  through `GetUniqueRepoStruct`. **Measured 2026-09-23.**
- Unique definition records have the shape `{w, j, b, a, c}` (`c` = 1 marks the
  unique repository, `j` the weapon subtype); there is no Angelic flag, and base
  items with flag 40 set are skipped. **Headhunter and Tyrant's Crown have no
  unique-repository entry, so the game's own roll never drops them.** **Static
  reading.**
- `droprate.base` of some uniques: Marcher's of Hatred 4,266,000; Annihilator
  4,158,450; Tayrel's Chestplate 25,000,000; Lucifer's Crown 111,111,111.
  **Measured.**
- `Loot_Manager_obj` has no `lootListUnique` instance variable, although the
  instance exists. **Measured.**
- `DropItem` also runs for breakable props, and ordinary drops call
  `LootGroundCreate` (and `CreateDefaultParams`) directly from inside it.
  **Measured.**

[angelic roll, Results](../ForgePact/docs/angelic-roll-hook-research.md#results),
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

[AFK FARM design, 0.8](../HS-AFK-Expedition/docs/DESIGN.md#08-the-camp-traits-and-three-more-worker-types)

### 13.7 Monster ranks: names, health, damage, XP and drop values

From AFK FARM's 6,471 recorded packets and 214 capture sessions, 2026-09-17 to 09-24. Two game builds, pe6aaa6779 and pe6a9ed3ee.

- **Rank values.** An ordinary monster's `enemyRarity` is 1-4, and `DropItem`'s first argument is the same number. In every packet `killStatistic` equals the rank. **Measured.**
  - Loot goblins drop at 5, while their own `enemyRarity` stays 1, 3 or 4.
  - Every special-content monster seen dropped at 4.
- **Names (inferred).** The save's kill counters are Total, Common, Champion, Ancient, Legion and Fallen. On the save with the most kills, Common, Champion, Ancient and Legion add up exactly to the total, and their proportions fit only rank 1 Common, 2 Champion, 3 Ancient, 4 Legion. **Inferred; not yet checked on screen.** ForgePact's labels (normal, champion, rare, ancient) are one step off from this.
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

  No stock routine offers keys, fragments, materials, socketables or relics, and no gamble routine was found in Season 10.
- **Selling to a vendor pays** the item's info value 9 × the stack, rounded up. Materials are worth a token 10, runes and gems 125-381, most keys 15-5,000. **Static reading.**
- **Gold** is account-wide, with separate pools for softcore, hardcore and Blood Pact (`hs2saves\shop.ini`, `[gold]`). The offline cap is 500,000,000.
  - `PickUpGoldCheck(GetCounterHash(), amount, …)` is the only call that changes the balance, both credits and debits. `GoldLogAdd` only writes the UI log.
  - AFK FARM's `worker pay` and `worker credit` (0.9) use `PickUpGoldCheck` with a fresh hash, one receipt per request. **Measured** 2026-09-25: a `worker credit` of 5,000 raised the balance by exactly 5,000.
- **`LootGroundCreate(x, y, itemType, def, …)`** makes a floor item whose Create event builds it (`CreateItemNew`). `def` carries `b` (base), `j`, `c` (0 normal, 1 unique repository) and optional `o` (stack) and `a` (seed). Rarity is not an argument. **Measured** for types 14 and 15 through AFK FARM's workers. Type 12 was **measured** on 2026-09-25: a town delivery made Basic Keys (12:0) and Cellar Keys (12:10) with the right `b` and `o`. Type 13 was **measured** the same day: a town delivery made a Battle Fragment (13:0) with the right `b` and `o`, and the game gave it a new seed (`a`).

[AFK FARM design, 0.9](../HS-AFK-Expedition/docs/DESIGN.md#09-the-town-defense-trade-merchants)

---

## 14. Satanic Zone and Special Content

### 14.1 Satanic Zone modifiers

- The game does not call `LoadSatanicZone` in normal play (0 calls across zone
  load, walking and waypoints); called with no arguments it returns false.
- `Controller_obj.satanicZone` is a room-reference number. The buff and debuff
  arrays hold unique ids in 1–25 / 1–26 and re-roll on their own every few tens of
  seconds to minutes, not in step with room changes; overwriting them in place is
  picked up without a room change.
- With no arguments `GetSatanicZoneOffline` returns undefined,
  `ReturnSatanicZoneBuffs`/`Debuffs` return real 0 and `LoadRandomSatanicStat`
  throws.

**Measured 2026-09-10.** The buff and debuff names are in
[`hs-game-sdk/curated/satanic_zone.json`](../hs-game-sdk/curated/satanic_zone.json).
[satanic zone, Findings](../ForgePact/docs/satanic-zone-mods-research.md#findings-2026-09-10-live-session),
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
- `sCP(object ref, x, y)` creates the object on `gameLayer` and records it in
  `pSpwd`; Battlefield, Rift and Shadow Realm go through it. **Static reading.**
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
| `DropItemAngelic` when the zone has no candidates | infinite loop, game freezes | §13.4 ([angelic drop](../ForgePact/docs/angelic-drop-research.md#oyunun-kendi-mekanizması-statik-okuma-canlı-ölçülen-yalnızca-buff-yokken-zarın-hiç-atılmaması)) |
| Writing `dropTable` on piles, destructibles, `Cursed_Orb_obj` | GML error (static reading) | §13.1 |
| `DropDungeonKeys` with argument 5 undefined | GML error (static reading) | §13.3 |
| Overriding `eSt` at Room Start, or zeroing `ReturnSpecificStat`'s return | crash | §14.2 ([S10](../ForgePact/docs/S10-special-content-notes.md#simdiye-kadar-denenen-ve-coken-yollarin-tam-listesi)) |
| Calling `sCP` directly | crash | [S10](../ForgePact/docs/S10-special-content-notes.md#scpyi-dogrudan-cagirmak-cokertiyor) |
| Duplicating `Spawn_*` instances | crash (their zone-state keys collide) | [S10](../ForgePact/docs/S10-special-content-notes.md#simdiye-kadar-denenen-ve-coken-yollarin-tam-listesi) |
| Duplicating reward-portal objects | infinite loading | [S10](../ForgePact/docs/S10-special-content-notes.md#portal-cogaltmasi--sonsuz-loading--2026-08-25-2155-geri-alindi) |
| Hooking the game's internal integer-die helper | crash | [S10](../ForgePact/docs/S10-special-content-notes.md#simdiye-kadar-denenen-ve-coken-yollarin-tam-listesi) |
| Filling the protected-variable store (262,144 records) | fault while a creator builds a monster | §5.8 |
| Special content at 20× | dies at about 13.4k instances | §5.8 |
| A creator acted on before `enemyCreatorTimer` is real | no crash — the pack never spawns | §11.2 |
| Removing a stash item's map entry (`RemoveItemFromMap` on map 9) but leaving its cell in the tab | the game ends at its next stash save — measured twice, in two launches; `GridRemoveItem` on the cell in the same take avoids it | §17 |

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

**Measured.**
[Item Truth, step 2](../hero-siege-item-editor/GAME_TRUTH_DESIGN.md#step-2--the-game-checks-any-item-on-request-item-editor-2160-forgepact-145)

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
- **The game keeps every item it evaluates this way in memory** until it closes:
  about 95 KB each; a session that evaluated about 200,000 crashed in
  `ucrtbase.dll` (0xc0000409). **Measured.** Why is not established.

[Item Editor, game truth step 4](../hero-siege-item-editor/GAME_TRUTH_DESIGN.md#step-4--seeds-the-game-built-item-editor-2163)

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
the SDK by `tests/test_curated_stash_containers.py`.

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

### 18.6 No automatic pickup

- No automatic pickup was found. `Loot_Manager_obj`'s Step picks up only the
  targeted item (`playerLootTarget`) after an input: a key, a click or the
  gamepad (§10.2). `Loot_Ground_obj` has no Step, and its `Alarm 9` only sets
  visibility from the filter and the screen. No code in the exe or `data.win`
  refers to the translation key `auto_pickup`. **Static reading.**

["Auto loot"](../ForgePact/docs/incarnation-gems-research.md#auto-loot---static-reading)
