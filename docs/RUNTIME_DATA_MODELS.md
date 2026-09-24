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
