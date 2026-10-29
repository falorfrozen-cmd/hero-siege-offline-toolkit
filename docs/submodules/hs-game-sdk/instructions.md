# HS Game SDK Module Development Instructions

## Module Overview & Metadata

`hs-game-sdk` is the centralized, multi-language SDK and metadata library providing GameMaker objects, scripts, assets, stat IDs, and runtime struct definitions extracted directly from `Hero_Siege.exe` and `data.win`.

It serves as the unified source of truth for:
* **C++ plugins** (`ForgePact/plugin`, `HS-Offline-Tracker/aurie-producer`, `hs-stat-forge`)
* **Python tools** (`hero-siege-item-editor`, `HSSaveEditor`, `HS-Offline-Launcher`)
* **TypeScript / Web interfaces** (`HSCraftSim`, `HS-Offline-Tracker/src`)

| Item | Value |
| --- | --- |
| **Directory** | `hs-game-sdk/` |
| **Languages** | Python 3.10+, C++20, TypeScript / JavaScript |
| **Output Formats** | Python package (`hs_game_sdk`), C++ headers (`include/hs_game_sdk/`), TypeScript package (`@hero-siege/sdk`), JSON dumps |
| **Supported Game Build** | Hero Siege Season 10 (Steam / Offline) |

---

## Architecture & Directory Map

```text
hs-game-sdk/
├── data/                       # Extracted JSON databases (ignored by git for clean distribution)
│   ├── manifest.json           # Binary metadata and hashes
│   ├── objects.json            # 6,016 GameMaker Object definitions, indexes, parent hierarchy
│   ├── scripts.json            # 6,254 GML Script names and asset indexes
│   ├── sprites.json            # 32,270 Sprite indexes and names
│   ├── rooms.json              # 306 Room indexes and names
│   └── sounds.json             # 2,718 Sound indexes and names
├── curated/                    # Hand-verified game knowledge (NOT gitignored - tracked)
│   ├── satanic_zone.json       # Satanic Zone buff/debuff ids/names/descriptions + Controller_obj var names
│   ├── drop_types.json         # LoadDrops drop types + GetNormalRepoStruct repository categories (data only)
│   ├── drop_roll_measurements.json # M1-M10: recorded drop-roll numbers drop_roll_model.py is tested against (data only)
│   ├── mining_reward_measurements.json # MR1-MR9: recorded mining-dig numbers mining_reward_model.py is tested against (data only)
│   ├── monster_rank_measurements.json # MK1-MK24: what a monster's rank does (§13.7), the boss report, and ForgePact #44's Live 1 and 1b on bosses, for monster_rank_model.py (data only)
│   ├── dungeon_chest_measurements.json # DC1-DC23: the dungeon chest's static reading, the kill path (§13.5), and ForgePact #31's Live 1, Live 1b, Live 2 and Live 3 measurements (the estimate's mean, the player build's census, latch and head label), for dungeon_chest_model.py (data only)
│   ├── skill_sliders_measurements.json # ForgePact #160's live values for skill_sliders_model.py (data only)
│   ├── number_compress_measurements.json # ForgePact #230's Live 2: the values traced into num_compressSteam, the one it ended on and the largest that passed, the multipliers, the dump's code and subcode, the display options, the cap's text, for number_compress_model.py (data only)
│   ├── room_acts.json          # RoomActIndex's act per room (its answer is the act): 175 rows (SDK room name, index, act), static reading, six rows measured (Live procedures 1, 2 and 3), for soul_piece_model.py's tests (data only; nothing ships it)
│   ├── boss_soul_pieces.json   # ForgePact #197: the key piece's base (`keys_bifrost_key`, class 12, `b` + act/10) and its icon (`Gem_Incarnation_spr` under info key "11", ground `Pickup_Gem_Incarnation_spr`), `bag_stack` (the game's `InventoryGridAddToStack`: classes 12 to 15 only, asked before any compare, a cap of 999, the `s_ItemOperation` result's `success`), the legacy piece's base (Edible PAS Logo), act bosses and boss rooms, piece seeds, the Gem of Incarnation's measured rate (9,000), the 4/5 ratio, the travel route (`NetworkRoomGoto` after `ZoneStateResetSingle`), room and use rules, verdict words, shared cases (key pieces and stack counts included) and the open questions of Live procedure 3 and the follow-up's Live procedures 1, 2 and 4, with their answers (Live procedure 4: the bag file is written at stash close, and a saved stack count comes back as written) (data only)
│   ├── loot_announcement_measurements.json # ForgePact #17: the rare-drop announcement chain, the rarity codes its closure branches on and the route ForgePact ships (§16.10; data only, no model)
│   ├── special_content.json    # global.eSt slot -> stat -> content map + Spawn_*_obj markers (data only)
│   ├── flight_charms_measurements.json # ForgePact #158 phase 1: walk callers, charm size keys, sprite key, the Heroic roll (RDM §19.6, §23), and the mod's Mod live 1-3 records (data only)
│   ├── unique_pick_measurements.json # UP1-UP22: #74's stand-in picks, the unique list's lengths, ForgePact's push and coin, the flight charms' Mod live 1 and 2 counts, the Heroic roll (UP14, UP21) and DropItem's draw (UP15-UP20), and the Mark 1 kill route by name (UP22), for unique_pick_model.py (data only)
│   ├── mark1_set_measurements.json # ForgePact #166: the Mark 1 set's Mod live 1-10 records (casts, walk, jump, the Heroic roll's pool, the DropUniqueItems route by name, the kill lever, DropItem's draw) and the 2026-10-22 playtest's Stats live 1-5 (`playtest2`; data only)
│   ├── mark1_automation_cases.json # ForgePact #166: the Mark 1 automation's shared cases (proc interval, drain, maximum-mana cut), computed by mark1_automation_model.py, which ForgePact's Mark1Priority.hpp and Mark1Cost.hpp are held to as well (data only)
│   ├── item_stat_keys.json     # ForgePact #166: item stat keys (an item's stats map) beside ReturnSpecificStat's dispatcher ids and their getters, and the tooltip's set-bonus lines; neither numbering is StatId's (data only, no generator)
│   ├── movement_speed_measurements.json # MS1-MS11: ForgePact #166's Mod live 1 sweep of the walk's modal step against the id-64 answer, its half point and phase 1's point, for movement_speed_model.py (data only)
│   ├── item_info.json          # Rarity codes, itemInfoStruct keys, affix slots, tooltip stat-line call (data only)
│   └── stash_containers.json   # Stash map/special-tab Controller_obj var names (ForgePact #14, data-only, no generator)
├── python/                     # Python SDK package
│   ├── hs_game_sdk/
│   │   ├── __init__.py         # Re-exports; the five tables below load on first use (see "Import cost")
│   │   ├── objects.py          # GameObject enum & index maps
│   │   ├── scripts.py          # GameScript enum & index maps
│   │   ├── rooms.py            # GameRoom enum & index maps
│   │   ├── sprites.py          # GameSprite enum & index maps
│   │   ├── sounds.py           # GameSound enum & index maps
│   │   ├── stats.py            # StatId enum, proc bundles (116/117/118), buff IDs (332)
│   │   ├── structs.py          # Dataclasses: ItemDefinitionStruct, ItemStatStruct, etc.
│   │   ├── player.py           # EquipmentSlot enums, PlayerEquipment, container scanners
│   │   ├── item_type.py        # ItemType IntEnum: the item instance's itemType class (hand-written)
│   │   ├── drop_roll_model.py  # Two-stage drop roll model, stdlib only, not exported from __init__ (hand-written)
│   │   ├── mining_reward_model.py # What one mining dig pays (ore stacks, bonus rolls), stdlib only, not exported (hand-written)
│   │   ├── monster_rank_model.py # What a monster's rank does to health, damage, XP and drop values, stdlib only, not exported (hand-written)
│   │   ├── dungeon_chest_model.py # When a key dungeon's end chest opens (no monster alive) and the kill tally's quantities, stdlib only, not exported (hand-written)
│   │   ├── skill_sliders_model.py # Projectile count, AoE scale and projectile deltaSpeed from their stats, stdlib only, not exported (hand-written)
│   │   ├── unique_pick_model.py # Which unique the Angelic roll, the ordinary unique roll, the Heroic roll and DropItem's own draw yield (one entry's share), stdlib only, not exported (hand-written)
│   │   ├── movement_speed_model.py # The walk's modal step against the movement speed stat (affine: answer + 200) and the answer that halves it, stdlib only, not exported (hand-written)
│   │   ├── mark1_automation_model.py # The Mark 1 automation's proc interval (cooldown at Skill Haste plus cast time at Faster Cast Rate) and its mana cost (the drain, the maximum-mana cut), stdlib only, not exported (hand-written)
│   │   ├── soul_piece_model.py # A room's act (RoomActIndex's answer), the pickup's stack rule (reals within the epsilon), the number rules a key piece rests on (repository truncation, unique `c`, the save's two decimals, crafting's count, the find), the gem roll a boss soul piece rides and the backpack's use, stdlib only, not exported (hand-written)
│   │   ├── number_compress_model.py # Which numbers the game's Steam number shortener (num_compressSteam -> SteamCompressNumber) ends the process on, and the text it writes for the rest, stdlib only, not exported (hand-written)
│   │   ├── mod_registry.py     # ModDefinition & ModRegistry for declarative mods
│   │   └── satanic_zone.py     # SATANIC_BUFFS/SATANIC_DEBUFFS tuples, generated from curated/satanic_zone.json
│   ├── pyproject.toml
│   └── setup.py
├── cpp/                        # C++ Header SDK for YYToolkit / Aurie Plugins
│   └── include/hs_game_sdk/
│       ├── objects.hpp         # enum class GameObject & GetObjectName()
│       ├── scripts.hpp         # constexpr string_view script names & indexes
│       ├── rooms.hpp           # enum class GameRoom
│       ├── stats.hpp           # Stat constants & proc families
│       ├── yytk_helpers.hpp    # Typed helper wrappers for YYTKInterface
│       ├── hooks.hpp           # InstallScriptHook: table swap + inline detour, repeat-safe
│       ├── player.hpp          # Player discovery; relic scanners and ReadGroundRelic (positive ID only)
│       ├── item_type.hpp       # HeroSiege::Items::ItemType + enumerable kItemTypes (hand-written, no YYToolkit)
│       ├── satanic_zone.hpp    # HeroSiege::SatanicZone::kBuffs/kDebuffs, generated from curated/satanic_zone.json
│       └── hs_game_sdk.hpp     # Main aggregate header
├── ts/                         # TypeScript / ESM SDK for web and UI modules
│   ├── src/
│   │   ├── objects.ts
│   │   ├── scripts.ts
│   │   ├── rooms.ts
│   │   ├── stats.ts
│   │   ├── player.ts
│   │   ├── item_type.ts        # ItemType enum + enumerable ITEM_TYPES (hand-written)
│   │   ├── satanic_zone.ts     # SATANIC_BUFFS/SATANIC_DEBUFFS, generated from curated/satanic_zone.json
│   │   └── index.ts
│   └── package.json
└── (Configured via repository root .gitignore & README.md)
```

**`data/` vs `curated/`:** `data/` is mechanically extracted straight from `Hero_Siege.exe`/`data.win`
by `tools/extract_and_generate_sdk.py` and is gitignored (see Safety section below) - it never leaves
a contributor's machine. `curated/` is hand-verified game knowledge that no extractor can derive (item
names/effect text that requires playing the game and cross-checking, not just walking a symbol table)
and IS tracked in git, generated into the same three language targets by a small sibling script,
`tools/generate_satanic_zone_sdk.py` (run it after editing a `curated/*.json` file; it is not part of
`extract_and_generate_sdk.py`'s pipeline since it has nothing to extract from a binary). `curated/`
is the pattern to extend for any future hand-verified, non-mechanically-extracted domain knowledge a
submodule needs to share - see `ForgePact/docs/satanic-zone-mods-research.md` for how `satanic_zone.json`
came to exist. Not every `curated/*.json` file is generated into bindings: `drop_types.json`,
`special_content.json` (2026-09-24) and `item_info.json` (2026-09-25: rarity codes, info keys,
affix slots and the tooltip's stat-line call, from the Item Editor's game-truth check) are data only,
read as JSON, with no `tools/generate_*_sdk.py` counterpart; each file's `$schema_note` says so, and
`docs/RUNTIME_DATA_MODELS.md` §13, §14 and §16 carry the prose and sources. `tests/test_sdk_all.py`
checks every script and object they name is bound.
`stash_containers.json` (ForgePact issue #14's stash and Crafting Cube container names, and
ForgePact #68's `bag_to_stash_move`: the routines, selfs and argument order of a move from the
bag into the stash, and the map owner per tab kind; see `docs/RUNTIME_DATA_MODELS.md` § 17) is data-only too, with no generator and no consumer yet, checked
against the SDK and that doc section by `tests/test_curated_stash_containers.py`.
`gamba_measurements.json` (2026-10-04 to 2026-10-06, ForgePact issue #134's gamba machine work,
G1-G22: G1-G3 the static reading of `Slot_Machine_01_obj`, its parents and its creation call, G4-G9
measured with the research build's `gambaprobe` in Lives 1 and 2, G10 the spin checks those two
sessions never reached, G11-G13 the phase-1c static readings of the `Alarm_9` guard, `sCP` and the
extension-function state route, G14-G17 Live 3's spin, payout, prize roll and spawn-route
measurements, G18-G19 Live 4's two natural explosions (research build, 2026-10-05/06) and the head
the game did not drop at them, G20-G21 Live 5's forced head through the player build's `gambapity`
and the outcomes it did not reach, and G22 Live 6's explosion count on two more natural machines)
is data only, in the shape of `jump_measurements.json`
(`measurements[]` with `id`, `kind`, `status`, `date`, `source`, `what`, `values`), with no generator, no model and no consumer yet; its
prose is `docs/RUNTIME_DATA_MODELS.md` § 20 and its argument ForgePact's
`docs/gamba-machine-research.md`.

**Models (`drop_roll_model.py`, 2026-09-24, issue #162):** a model is a hand-written, stdlib-only,
deterministic function of the game's mechanism, built from a written spec
(`docs/models/drop-roll-spec.md`) and checked against a curated fixture of recorded measurements
(`curated/drop_roll_measurements.json`) by `tests/test_drop_roll_model.py`. It models the game only;
a mod's levers are that mod's code and live in the test as input transforms. It is imported as
`from hs_game_sdk import drop_roll_model` and deliberately not exported from the generator-owned
`__init__.py`. There is no C++ or TypeScript counterpart, so no parity across bindings is claimed.
Why and how: `docs/agents/static-model-workflow.md`.

`mining_reward_model.py` (2026-09-28, ForgePact issue #36) is the second model, built the same
way: spec `docs/models/mining-reward-spec.md`, fixture `curated/mining_reward_measurements.json`
(MR1-MR9: MR1-MR3 from 2026-09-23, MR4-MR9 from issue #36's Live procedure 1 on 2026-09-28), checks `tests/test_mining_reward_model.py`. It gives the ore stacks one dig drops from a
node's list and the chance of a stat-gated bonus find; ForgePact's Mining Ore Multiplier, the Miner's
Helmet and Mining Ore Extra Rolls stay in the test as transforms, pinned to `MiningOreMod.hpp` and
`src/forgepact.py` by `RollsLeverParityTests`.

`monster_rank_model.py` (2026-10-02, ForgePact issue #44, hub #379) is built the same way: spec
`docs/models/monster-rank-spec.md`, fixture `curated/monster_rank_measurements.json` (MK1-MK24:
MK1-MK4 AFK FARM's § 13.7 rank table, MK5 the reported Anubis HP jump, `reported`, not measured,
and MK6-MK24 ForgePact #44's Live procedures 1 and 1b on bosses), checks
`tests/test_monster_rank_model.py`. It gives a rank's health, damage and XP multipliers and its
protected drop values. Whether a boss follows the same rows is carried one dimension at a time in
`monster_rank_model.HYPOTHESES`, each `None` (not established) until a measured row about a boss,
with nothing else changed or the change matched by an identity control, decides it:
`boss_hp_follows_rank_table` `None` (the boss's health carried a ForgePact affix top-up and had no
control), `boss_damage_follows_rank_table` `None` (one confounded spawn, 0.4% outside the
control's tolerance), `boss_xp_follows_rank_table` `None` (measured ×6.2505 against ×6.25 on one
Karp King, one spawn, whose affix top-up the control did not share; rank 3 not measured on a boss)
and `boss_drop_rank_reaches_dropitem` `None` (`DropItem`'s first argument 1 -> 4, measured on the
same spawn, the same unmatched top-up). The test compares a boss row's top-up with its control's
at the boss's rank, so an unmatched one keeps the row out by itself. The test fails when a
hypothesis and the fixture disagree. ForgePact's Bosses control stays in the test as `force_boss_rank`, pinned to
`BossRarityMod.hpp` and `src/forgepact.py` by `LeverParityTests`.

`dungeon_chest_model.py` (2026-10-03, ForgePact issue #31) is built the same way: spec
`docs/models/dungeon-chest-spec.md`, fixture `curated/dungeon_chest_measurements.json` (DC1-DC5
the static reading of `Dungeon_Chest_obj` and its neighbours, DC6 the measured kill path of
`docs/RUNTIME_DATA_MODELS.md` § 13.5, DC7-DC11 and DC13 measured in ForgePact #31's Live procedure 1,
DC12 not observed, DC14-DC19 its Live procedure 1b, DC20-DC21 its Live procedure 2 and DC22-DC23 its
Live procedure 3 on the player build, 2026-10-04), checks
`tests/test_dungeon_chest_model.py`. It models the game's rule (the chest opens once no monster is
alive) and ForgePact's progress: kills counted in the dungeon over its planned total, fixed at the
chest's first sight (`planned_total`, `estimated_total`, `progress`). What Live 1 settled (the chest
polls `instance_exists` itself; monsters stream from spawners present at load) and what is still
open (where the planned total comes from) are carried in `dungeon_chest_model.HYPOTHESES`, each
`None` until a measured entry decides it. ForgePact's Dungeon
chest opens early stays in the test as input transforms, pinned to `DungeonChestMod.hpp` and
`src/forgepact.py` by `LeverParityTests`.

`soul_piece_model.py` (2026-10-11, ForgePact issue #197, hub #489) is built the same way: spec
`docs/models/soul-piece-spec.md`, fixtures `curated/room_acts.json` (the act of each of the 175
rooms `RoomActIndex` knows, with its SDK room index, a static reading, six rows measured by
Live procedures 1, 2 and 3; `CuratedTests` checks every name and index against `GameRoom`) and
`curated/boss_soul_pieces.json` (the key piece's base, `keys_bifrost_key`, class 12 at index 2
measured, whose `b` a piece carries plus act/10, a static reading until the follow-up's Live
procedure 1; the piece's icon, `Gem_Incarnation_spr` under item info key `"11"` with its ground
companion `Pickup_Gem_Incarnation_spr`, both checked against `hs_game_sdk.sprites`; `bag_stack`,
the game's stack attempt a consumable's pickup reaches (`InventoryGridAddToStack`, classes 12 to
15 only, a cap of 999 pinned to `SoulPieceMod.hpp`'s `kBagStackCap`), a static reading until the
follow-up's Live procedure 2; the legacy
piece's base, the Edible PAS Logo, class 11 with `b` 12
measured; the nine act bosses, each checked to descend from `Enemy_Child_Boss_obj`, and their boss
rooms, each checked against `GameRoom`; the piece seeds; the Gem of Incarnation's rate of 9,000,
measured by Live procedure 1; the 4/5 ratio; the travel route (`NetworkRoomGoto` after `ZoneStateResetSingle`); the room and use rules; the verdict words;
shared cases; and the open questions of ForgePact #197's Live procedure 3 and the follow-up's Live
procedures 1, 2 and 4, with their answers), checks
`tests/test_soul_piece_model.py`. It models the game only: a room's act (`RoomActIndex`'s answer,
which is the act itself, measured; none outside its switch), the pickup's stack rule (an incoming
class outside 12 to 15 refused before any field is compared, then the same class, `b` and `c`
equal within the runtime's epsilon and at most 999 in a stack; the seed is never compared, so a
class-11 piece never stacks by the game's own code), the number rules a key piece rests on (the repository lookup
truncates `b`, a `c` above 0.5 picks the unique repository, the save keeps two decimals, crafting
counts by class and `b`, the inventory find matches `b` and `c`), the
gem's chance on one `DropGems` call (1 in its rate) and the backpack's use (the item is cleared only
when `PotionUse` answers true). Whether `DropGems` really gives 1 in the rate and whether the save
keeps two decimals are carried in `soul_piece_model.HYPOTHESES`, `None` until the curated file's
`open_questions` entry is measured; the roll's `self` being the dying monster, `PotionUse`'s true
answer clearing the item, a class-11 item never stacking and a saved count coming back as written
are measured `True` there, and a room outside the switch answering undefined is measured `False`
(the answer is the bool `false`). ForgePact's Boss soul pieces (the piece's 1 in `max(1, floor(G × 4 / 5))`, its room and
source rules, its use and the travel route (`NetworkRoomGoto` after `ZoneStateResetSingle`) to the act's boss room, and the key piece's shape and identity) stays
in the test as input transforms, pinned to `SoulPieceMod.hpp` through the curated file by
`ParityTests`.

`skill_sliders_model.py` (2026-10-04, ForgePact issue #160, hub #408) is built the same way: spec
`docs/models/skill-sliders-spec.md` (written from the static reading in ForgePact's
`docs/skill-sliders-research.md`), fixture `curated/skill_sliders_measurements.json` (#160's three
live sessions of 2026-10-04; `MeasuredTests` checks each `measured` row's `model` call, applying
the row's research `lever` to the result and allowing only its printed-precision `tolerance`, and
skips a row whose `status` is not `measured`), checks `tests/test_skill_sliders_model.py`. It gives
what the game's two extra-projectile helpers return, the AoE size a projectile's or skill object's
scale gains, and the `deltaSpeed` the projectile-speed stats leave. What is still open (how
`LoadAllModifiers` stores stats 74 and 75, the order they combine in on `deltaSpeed`, which the
required keyword-only `order` stands for, the AoE factor callers pass, the outcome of the chance
rolls) is a parameter, never a guessed constant. ForgePact's research levers (`projprobe amount`,
`aoe`, `speed`) stay in the test as transforms, pinned to `plugin/ModuleMain.cpp` by
`LeverParityTests`.

`unique_pick_model.py` (2026-10-13, ForgePact issue #158, hub #500) is built the same way: spec
`docs/models/unique-pick-spec.md` (written from `docs/RUNTIME_DATA_MODELS.md` § 13.4, § 13.12, § 23.4
and § 23.8), fixture `curated/unique_pick_measurements.json` (UP1-UP5 #74's `standinPicks=` counts from
its list-injection Lives 1 to 3 of 2026-10-02, with nothing pushed and with Headhunter at 200
copies; UP6 the measured lengths of `lootListUnique[0..5]`; UP7-UP8 ForgePact's push and coin, as
our-code contracts; UP9-UP13 the flight charms' Mod live 1 and 2 counts, replayed at the measured
T = 48; UP14 the Heroic roll `DropItemHeroic` called by name; UP15-UP20 `DropItem`'s own unique draw,
Mark 1's Mod live 7 and the draw push it takes under `move: go`; UP21 Mark 1's Mod live 4 on the
Heroic roll, replayed at the measured T_H = 203; UP22 Mark 1's Mod live 5 on the `DropUniqueItems`
route by name), checks `tests/test_unique_pick_model.py`. It gives an entry's share of the
Angelic roll's drops (r / T: the roll draws again until it keeps a droppable entry), and the
ordinary unique roll's chance of dropping a given entry or anything at all (r / L and D / L: one
draw, nothing on a miss). T, the droppable entries on the Angelic list, was measured as 48 by the flight charms' Mod live 2
`flightprobe pool` (RDM § 13.4); #74's replays, made before that, still accept one T in 40..60.
What is still open is a parameter, never a guessed constant: D, and whether the ordinary roll's index can reach the list's length
(`index_can_reach_length`). The binomial helpers are `drop_roll_model`'s, imported and not copied.
ForgePact's push (one stand-in per switched-on item per roll, onto list 5 for Headhunter, Tyrant's
Crown, Gabriel Wings and Witch's Broomstick, onto lists 0..4 for Pocket Elf) and its coin
c / (n + c) stay in the test as transforms, so each item takes c / (T + e) of the Angelic roll and
Pocket Elf c / (L_k + c) of the ordinary one, one entry's share at the player build's c = 1; they
are pinned to `plugin/ModuleMain.cpp` and `plugin/include/ForgePact/FlightCharms.hpp` by
`LeverParityTests`.

`movement_speed_model.py` (2026-10-19, ForgePact issue #166, hub #518) is built the same way: spec
`docs/models/movement-speed-spec.md` (written from ForgePact's `docs/mark1-set-research.md`
§ Mod live 1 results and its Phase 2 decision), fixture `curated/movement_speed_measurements.json`
(MS1-MS2 the unlevered walk and the id-64 answer, 151 every frame; MS3-MS8 the `speed-sweep`
windows at multipliers 1.5 to -0.5; MS9 `speed-half`; MS10 phase 1's Live 2 point at 13.4 ms a
frame; MS11 the step halving between two sessions, cause not established), checks `tests/test_movement_speed_model.py`. It gives the walk's
modal step as proportional to the dispatcher's id-64 answer plus `STEP_OFFSET` (200, measured;
no cap reached, `STEP_CAP` is `None`), the ratio between two answers in one window, and the
answer that makes the step a given fraction of another's. The window's scale (px per point)
differed between sessions, for a cause not established, and is a parameter, never a constant. The model records which speed lever
Mark 1 ships and why (`SPEED_ROUTE`, `"stat-model"`, and `SPEED_ROUTE_REASON`): the step is
affine, so halving the answer gives 0.785, and the lever answers (x - 200) / 2 instead. That
lever stays in the test as a transform; the `movement` item's `LeverParity` tests pin
`Mark1Movement.hpp`'s constants to the model's.

`mark1_automation_model.py` (2026-10-22, ForgePact issue #166, hub #518) is built the same way:
spec `docs/models/mark1-automation-spec.md` (written from ForgePact's `docs/mark1-set-research.md`
§ "The 2026-10-22 playtest: stats, cast priority and held input" and the hub's RDM § 7.5 and
§ 7.10), shared cases `curated/mark1_automation_cases.json`, checks
`tests/test_mark1_automation_model.py`. It gives the proc route's interval for each automated skill
(its cooldown at the player's Skill Haste, reusing `skill_stat_model`, plus its cast time at the
player's Faster Cast Rate, the cast time alone for a skill with no cooldown) and the mana cost: the
shipped drain, which lowers the game's own replenish answer by a share of maximum mana per automated
skill a second divided by `REPLENISH_UNIT` (0.745, measured in Stats live 3), and the documented
maximum-mana cut beside it. Stats live 5 measured the drain at 1.117% a second per skill at about
144 frames a second and 0.956% at 60; how much regeneration a character needs to sustain a number of
skills rests on an assumed baseline and is modelled, not measured. ForgePact's `Mark1Priority.hpp`
and `Mark1Cost.hpp` are held to the same cases by its `test_mark1_priority_behavior.py` and
`test_mark1_cost_behavior.py`.

`number_compress_model.py` (2026-10-20, ForgePact issue #230, hub #539) is built the same way: spec
`docs/models/number-compress-spec.md` (written from the static reading folded into
`docs/RUNTIME_DATA_MODELS.md`), curated fixture `curated/number_compress_measurements.json` (ForgePact
#230's Live 2, capture `forgepact-230-damage-crash-live-2`), checks `tests/test_number_compress_model.py`.
It gives which numbers the game's Steam number shortener (`num_compressSteam`, which calls
`SteamCompressNumber` in `PAS_Steam_GMS_x64.dll`) ends the process on, because its text does not
fit the export's 8-byte buffer, and for every other number the text it writes and whether that
text's terminator still fits. By the static reading NaN, a positive number of 1e14 or more and a
negative number of -1e6 or less fail. Live 2 measured the positive limit's lower edge, between
9.9999e13 (ForgePact's cap, which passed) and 1e15: the last value traced before the end was about
1.025e14, the first of its decade, so the value the game ended on lies in [1.025e14, 1e15) and is not
itself known; the exact 1e14 limit, NaN and the negative limit remain static readings. The cap's text
`99999B` is measured.
`BaselineTests` pins those limits and the texts the spec names; `TargetTests` checks that ForgePact's cap (`numguard`, kept in the test as the input
transform `numguard_cap`) turns every failing value into one that passes and fits and passes every
other value through bit for bit; `MeasurementTests` checks the model against the fixture (it passes
every traced value before the end and the cap's value, which sits below `POSITIVE_LIMIT`, which in
turn sits below 1e15, the measured bracket; it fails the last traced value, which rests on the static
reading; and it writes the texts the operator read); `SpecTests` checks the spec labels its claims and names only
functions the model has; `NoDecompilerOutputTests` keeps decompiled text out of the model's files.
`LeverParityTests` pins only the four constants (`kNumGuardPositiveLimit`,
`kNumGuardNegativeLimit`, `kNumGuardLargestSafe`, `kNumGuardSmallestSafe`) to
`plugin/include/ForgePact/NumberGuard.hpp`, skipping when ForgePact is not checked out; the guard's
comparison directions and its NaN handling are not pinned here, and ForgePact's own harness covers
them.

---

## Import cost: the tables load on first use (2026-09-28)

`hs_game_sdk/__init__.py` imports its six small modules (`stats`, `satanic_zone`, `structs`,
`player`, `item_type`, `mod_registry`) when the package is imported. It imports the five
generated tables (`objects`, `scripts`, `rooms`, `sprites`, `sounds`) only when one of their names
is first used, through a module `__getattr__` (PEP 562). So `import hs_game_sdk` builds none of the
table enums. `from hs_game_sdk import GameObject` builds `objects` only. ForgePact's import list, the
two Satanic pools since ForgePact PR #116, builds none (it built `objects` and `scripts` before).

Callers change nothing:
- Every name is still importable from the package or from its own module, and is the same object
  either way.
- `hs_game_sdk.sprites` still works after a plain `import hs_game_sdk`, and `dir()` lists every name.
- `from hs_game_sdk import *` still binds exactly `__all__`, so it builds every table.

The first use of a name does the import, so `hasattr(hs_game_sdk, "GameSprite")` builds the sprite
table too.

**Why.** The cost was never the file size or a cold bytecode cache: an `IntEnum`'s class body
builds every member at each import. On some CPython versions that takes time quadratic in the
member count:
- On 3.13 and 3.14, each new member runs `value not in enum_class._hashable_values_`, a scan of a
  list holding every value before it (3.14's `Lib/enum.py` has the same line).
- 3.10 is quadratic too, with a larger constant.
- 3.11 is linear. 3.12 was not measured.

`GameSprite` has 32,271 members:

| Python | Building an `IntEnum` of 32,271 members | `import hs_game_sdk` before this change |
| --- | --- | --- |
| 3.10 | 45.7 s | 46.0 s (`sprites` 43.2 s, `objects` and `scripts` 1.2 s each) |
| 3.11 | 0.24 s | 0.50 s (`sprites` 0.30 s) |
| 3.13 | 3.6-4.0 s | 3.6-4.0 s (`sprites` 3.2-3.5 s, `objects` and `scripts` 0.15 s each) |
| 3.14 | not run locally | not run locally; the CI-built ForgePact.exe (3.14) starts like the eager build, below |

**Measured, before and after (2026-09-28).** This machine has 20 logical cores and was carrying other
sessions' load, so the figures are medians of runs interleaved between the two SDK copies. Each
import row times only the import statement, in a fresh interpreter.

| Python 3.13, 7 runs | Before | After |
| --- | --- | --- |
| `import hs_game_sdk` | 4.04 s | 0.084 s |
| `import forgepact` (ForgePact `src/`, a77c33e) | 4.44 s | 0.56 s |
| `from hs_game_sdk import GameObject, GameScript, GameRoom` (HS-AFK-Expedition `tools/game_session.py`) | 3.88 s | 0.43 s |
| `from hs_game_sdk import GameSprite` (control: still builds the sprite table, now without the other four) | 4.17 s | 3.92 s |
| ForgePact `tests/panel_sandbox_server.py`, spawn to its `port=` line | 4.49 s | 0.76 s |

On 3.11 (3 runs) the same rows went from 0.59, 0.79, 0.55, 0.56 and 0.96 s to 0.088, 0.45, 0.20,
0.42 and 0.64 s. On 3.10 they went from 53.7, 55.4, 41.8, 43.4 and 38.8 s to 0.070, 2.5, 2.3, 34.5
and 2.5 s. That was one run, made while the hub suite was running, so read it as an order of
magnitude. On 3.10, `objects` and `scripts` alone still cost about 1.2 s each.

**The packaged ForgePact.exe pays it too.** Each run launched the exe with a throwaway
`USERPROFILE` and timed it until `/api/state` answered; the exe was then killed by pid. Medians of 7
interleaved runs:

| Build | Python | Launch to `/api/state` |
| --- | --- | --- |
| ForgePact a77c33e, `build_release.py`'s PyInstaller command (PyInstaller 6.20), SDK before this change | 3.13 | 5.35 s |
| The same, with this SDK | 3.13 | 1.36 s |
| CI-built 2.0.0 draft | 3.14 | 5.49 s |
| CI-built 1.4.7, as the hub installed it | 3.14 | 6.38 s |

Every run served 25 Satanic buffs, so each frozen `from hs_game_sdk import (...)` had succeeded.

**PyInstaller needs the static imports.** A frozen app bundles only the modules PyInstaller's
analysis sees imported. A module that `importlib.import_module` loads at run time is invisible to
that analysis. So `__init__.py` repeats the table imports as plain `from .objects import (...)`
statements inside `if TYPE_CHECKING:`. They never run, but PyInstaller's bytecode scan follows
them, as type checkers and editors do. The ForgePact.exe built above holds the same twelve
`hs_game_sdk` entries in its PYZ as the eager build, and PyInstaller warned about none.

A build with the block deleted showed what the block prevented, while ForgePact still imported
`GameObject` and `GameScript`. PyInstaller still built that exe, but its PYZ held none of the five
tables, and the running exe served no Satanic buffs: `forgepact.py`'s `except Exception` fell back
to empty pools, the 2026-09-14 failure in the ForgePact guide's Packaging Hazards, item 4. That
build's `warn-ForgePact.txt` listed `missing module named hs_game_sdk.GameObject` and
`hs_game_sdk.GameScript`, because PyInstaller took the two names for submodules.
`build_release.py`'s substring check for `missing module named hs_game_sdk` would therefore have
refused the package. That warning existed only because ForgePact imported table names with `from
hs_game_sdk import`. Since ForgePact PR #116 it imports only `SATANIC_BUFFS` and
`SATANIC_DEBUFFS`, which `__init__.py` binds when the package is imported, so a ForgePact.exe no
longer needs the block: built against an SDK copy without it, the exe's PYZ held seven
`hs_game_sdk` entries and no table, its warn file named no `hs_game_sdk` module, and it served 25
Satanic buffs. The block still decides whether any other frozen app that imports a table name gets
its tables; `tests/test_sdk_lazy_import.py` checks it in the SDK itself. A bundler that evaluates
`TYPE_CHECKING` as false and drops the block would need the package named explicitly; every frozen
app in this toolkit is built with PyInstaller.

**Editing it.** The loader is part of the generated `__init__.py`, so it lives in the `init_content`
template of `tools/extract_and_generate_sdk.py` (see "Never hand-edit a generated file" below).
The `TYPE_CHECKING` block and the loader's table, `_LAZY_MODULES`, list the same names. Change them
together, in the template; the test fails if they drift. A new generated table belongs in both.

**What still pays.** A caller that uses a table still builds it: `GameSprite` costs about 3.2-4 s on
3.13. ForgePact's panel no longer builds any: `forgepact.py` imported `GameObject`, `GameScript`
and seven more names without using any of them, and so built `objects` and `scripts` at every start.
ForgePact PR #116 narrowed the import to the two Satanic pools, and `import forgepact` then took
0.21 s instead of 0.56 s on 3.13 and 0.18 s instead of 2.36 s on 3.10 (ForgePact guide, Known
Limitations item 38).

---

## OBJT Record Layout & the Object Parent Hierarchy

`objects.json` is extracted by walking the `OBJT` chunk's pointer list. This build's
runtime inserts a `managed` flag right after `visible`, which pushes every later field
4 bytes further than the pre-2022.5 layout most references describe. Offsets relative
to an object's record pointer, as measured against `data.win`
(`2fc37b1b…`, GEN8 bytecode version 17, `UILR`/`PSEM`/`PSYS`/`FEAT` chunks present).
**Reverified against `07D864C91EFE…` on 2026-09-17** (hub `4539e68`,
`hs-game-sdk/data/manifest.json` records the full hash): the game had been
patched, the extractor ran with this layout unchanged, a second run produced no
diff, it still yields 6,016 object records, and the regenerated closure names
matched the method values read off live instances in ForgePact's prospect window
session (`anon@1065/2806/3657@gml_Object_UI_Prospect_obj_Create_0`). That is a
check of the extractor's output, not a field-by-field re-measurement of every
anchor below. The patch renumbered every closure (`anon@N`) and shifted sprite and
mask indices, so code that spells a closure name as a literal goes stale with each
game update (see the ForgePact guide's Maintenance Triggers):

| Offset | Field | Notes |
| --- | --- | --- |
| `+0` | name | string pointer |
| `+4` | `sprite_index` | `-1` = no sprite |
| `+8` | `visible` | bool32 |
| `+12` | `managed` | bool32 — **the inserted field**; `true` for all 6,016 objects |
| `+16` | `solid` | bool32 |
| `+20` | `depth` | i32 — `0` for every object in this build (depth is layer-driven) |
| `+24` | `persistent` | bool32 |
| `+28` | `parent_index` | i32 **object** index, `-100` = root object |
| `+32` | `mask_index` | i32 **sprite** index, `-1` = collide using `sprite_index` |
| `+36` | `uses_physics` | bool32, followed by the physics block and the 15 event lists |

Anchors that pin this layout, in case it has to be re-derived for a future game build:

* `+48`/`+52`/`+64`/`+72` hold the GameMaker physics defaults `0.5`, `0.1`, `0.1`, `0.2`.
* Parsing the tail from `+68` (physics vertex count) yields exactly 15 event lists whose
  pointers are in-chunk and ascending for all 6,016 records, and no record's parsed end
  overruns the next record's start.
* `+28` is never anything but `-100` or a valid object index, and grouping by it produces
  the families the names imply (`Collision_Prop_obj` 1,495 children, `Visual_Parent_obj` 960,
  `Player_Damage_Parent_obj` 582, …), with 840 roots and no cycles.
* `+32` reaches past the object table into the sprite table and resolves to the game's own
  mask sprites (`Abandoned_Mine_Entrance_obj` → `Abandoned_Mine_Mask_spr`).

`tests/test_object_hierarchy.py` asserts all of the above, including the three-level chain
`Quest_Act_01_Coffee_Beans_obj → Quest_Object_Parent_obj → Pickup_Parent_obj`. Before
2026-09-10 the extractor used the unshifted offsets, so `parent_index` carried the
`persistent` flag (`0`/`1` only) and `mask_index` carried the parent index; any consumer
written against a `data/objects.json` from before that date needs regenerating.

### Hierarchy lookups in the bindings

All three targets expose the parent/mask tables plus lookup helpers, so a hook can ask
"is this instance an enemy?" instead of enumerating indices (the GML `object_is_ancestor`
relation):

```python
from hs_game_sdk import get_parent_index, get_child_indices, is_descendant_of

is_descendant_of("Quest_Act_01_Coffee_Beans_obj", "Pickup_Parent_obj")  # True
len(get_child_indices("Collision_Prop_obj"))                            # 1495
```

```cpp
using namespace HeroSiege::Objects;
static_assert(IsDescendantOf(GameObject::Quest_Act_01_Coffee_Beans_obj,
                             GameObject::Pickup_Parent_obj));
std::vector<int32_t> props = GetChildObjects(static_cast<int32_t>(GameObject::Collision_Prop_obj));
```

```typescript
import { GameObject, isDescendantOf, getChildObjects } from '@hero-siege/sdk';
```

Python: `OBJECT_PARENT_INDEX`, `OBJECT_MASK_SPRITE_INDEX`, `NO_PARENT`, `NO_MASK`,
`get_parent_index`, `get_ancestor_indices`, `get_child_indices`, `get_descendant_indices`,
`is_descendant_of`, `get_mask_sprite_index`. C++: `kObjectParents`, `kObjectMasks`,
`kNoParent`, `kNoMask`, `GetParentObject`, `GetMaskSpriteIndex`, `IsDescendantOf`,
`GetChildObjects`, `GetDescendantObjects` (the first three are `constexpr`, so ancestry
checks can be `static_assert`ed). TypeScript mirrors the Python names in camelCase.

---

## Item class: `ItemType`

`ItemType` names the value an item **instance** carries in its `itemType` field — the
field ForgePact already reads off live item structs, and the one `s_ItemInstanceStruct`
carries alongside its definition, info and stat structs (`HSCraftSim/RESEARCH.md` § 2).
It does **not** describe the item *definition* struct's `c` field: HSCraftSim treats `c`
as a 0/1 unique flag, and `docs/RUNTIME_DATA_MODELS.md` labels it a rarity tier. Do not
match `ItemType` against `c`.

| Binding | Enum | Enumerable companion |
| --- | --- | --- |
| Python | `from hs_game_sdk import ItemType` (`IntEnum`, UPPER_SNAKE) | iterate the enum |
| C++ | `HeroSiege::Items::ItemType` (`enum class : int32_t`, PascalCase) in `<hs_game_sdk/item_type.hpp>` | `HeroSiege::Items::kItemTypes` — `(std::string_view name, ItemType)` pairs |
| TypeScript | `ItemType` (`export enum`, PascalCase) from `@hero-siege/sdk` | `ITEM_TYPES` — readonly `{ name, value }` array |

`item_type.hpp` is self-contained (standard headers only, no YYToolkit), so any plugin can
include it on its own; `hs_game_sdk.hpp` pulls it in too.

| Value | Python | C++ / TS | Source |
| --- | --- | --- | --- |
| 0 | `HELMET` | `Helmet` | R |
| 1 | `BODY` | `Body` | R |
| 2 | `BOOTS` | `Boots` | R |
| 3 | `WEAPON` | `Weapon` | R |
| 4 | `GLOVES` | `Gloves` | R |
| 5 | `AMULET` | `Amulet` | R |
| 6 | `SHIELD` | `Shield` | R (`RUNTIME_DATA_MODELS.md` gives 6 a different label on `c`) |
| 7 | `RING` | `Ring` | R |
| 8 | `BELT` | `Belt` | R (`RUNTIME_DATA_MODELS.md` gives 8 a different label on `c`) |
| 10 | `CHARM` | `Charm` | R (`RUNTIME_DATA_MODELS.md` gives 10 a different label on `c`) |
| 11 | `CONSUMABLE` | `Consumable` | R + V (catalog row `(11, 23)` Infernal Codex) |
| 12 | `KEY` | `Key` | R + V (`(12, 8)` Angelic Key) + D (repository category 12 = keys) |
| 13 | `TAROT` | `Tarot` | R + V (`(13, 24)` The Wheel of Fortune) |
| 14 | `MATERIAL` | `Material` | R + V (`(14, 69)` Infernal Codex Page) + M (measured in-game 2026-09-19) |
| 15 | `SOCKETABLE` | `Socketable` | R + V (`(15, 82)` Exan Jewel) — runes, gems and jewels |
| 16 | `RELIC` | `Relic` | R + S (`RELIC_RARITY_TIER` / `kRelicRarityTier`, matched against `itemType`) + D (repository category 16 = relics) |
| 18 | `POTION` | `Potion` | R |
| 19 | `OTHER` | `Other` | R |

Sources:
- **R** — `HSCraftSim/RESEARCH.md` § 2, the "Item types (= catalog `cls`)" list, which names
  all 18 values.
- **V** — the same paragraph's "Verified" list: `(itemType, itemId)` pairs cross-checked
  against Item Editor catalog rows `(cls, b)`. HSCraftSim's `data/README.md` documents the
  catalog's `cls` column as the crafting `itemType`.
- **S** — already in this SDK: the relic contract in `player.py` / `player.hpp` identifies a
  relic by tier 16 read from `itemType` among other fields. `tests/test_item_type_parity.py`
  asserts `ItemType.RELIC == RELIC_RARITY_TIER`; the relic contract itself is unchanged.
- **D** — `docs/RUNTIME_DATA_MODELS.md` § 13.2, the item repository categories that
  `GetNormalRepoStruct(category, 0, index)` answers (measured 2026-08-27; also in
  `curated/drop_types.json`). Until 2026-09-24 this row cited § 3's "Dungeon Keys `12`" /
  "Relics `16`" examples, which mixed drop types with repository categories.
- **M** — measured in-game, 2026-09-19: ForgePact research build `8c56ca7`'s
  `prospectprobe stackmove` route read `itemType` off a live item twice in the same
  session — the Prospect Cube grid cell's `nodeFingerprint` (a Mallet Fragment)
  resolved through the game's own `GetItemFromFingerprint(fp, 0)`, called by name,
  and the existing stack `InventoryGridCanAddToStack` returned for that same
  material — and both reported `itemType = 14`, matching
  `HeroSiege::Items::ItemType::Material`. One material type, this row only; see
  `ForgePact/docs/prospect-window-research.md` (Stage C, `M-identity`/`M-shapes`)
  and ForgePact issue #52.

The integers **9** and **17** appear in no source and have no member. Do not add one without
evidence. Row 14 is measured in-game (Source M above); **no other row has been read from a
live item instance on this runner yet**: every other Source above is the research note or a
catalog cross-check, not a runtime measurement. When a live read confirms another value, mark
its row "measured in-game" with the date the same way. The other values rest on the research
note above, so treat a live mismatch on one of them as a finding to record here, not a typo.

The three declarations are hand-written, not generated, and nothing derives one from another:
that is what makes `tests/test_item_type_parity.py` a real check rather than a tautology. It
parses `item_type.hpp` and `item_type.ts` as text (runs in any checkout), imports
`item_type.ts` under `node --experimental-transform-types` (skips without `node` ≥ 22.7), and checks
no binding declares 9 or 17. `tests/test_cpp_sdk.py`'s
`test_compiled_item_type_table_matches_python` compares the *compiled* `kItemTypes`, printed by
the harness as `ITEM_TYPE <Name> <value>` lines, against the Python enum. A `curated/*.json` +
generator was considered and not used: with one generated source, the parity test would compare
a file with itself, and for 18 stable constants the extra artifact costs more than the drift it
prevents — revisit if the table grows.

---

## Integration Workflow Across Submodules

### 1. Python Submodules (`hero-siege-item-editor`, `HSSaveEditor`, etc.)
Install in editable mode:
```powershell
py -3 -m pip install -e hs-game-sdk/python
```
Or import directly:
```python
from hs_game_sdk import GameObject, GameScript, StatId, PROC_FAMILIES, ItemDefinitionStruct, ItemType
```

### 2. C++ Submodules (`ForgePact/plugin`, `HS-Offline-Tracker/aurie-producer`)
Add `hs-game-sdk/cpp/include` to the include search path and include the aggregate header:
```cpp
#include <hs_game_sdk/hs_game_sdk.hpp>

using namespace HeroSiege;

void ExampleHook() {
    auto obj = Objects::GameObject::Enemy_Parent_obj;
    std::string_view script = Scripts::gml_Script_DropItem;
    auto material = Items::ItemType::Material;  // itemType 14
}
```

### 3. TypeScript Submodules (`HSCraftSim`, `HS-Offline-Tracker` UI)
Import from the module:
```typescript
import { GameObject, GameScripts, StatId, ItemType } from '@hero-siege/sdk';
```

---

## Setup, Extraction & Test Command Reference

| Command | Working Directory | Purpose | Verification Status |
| --- | --- | --- | --- |
| `py -3 tools/extract_and_generate_sdk.py --game-bin "<path-to-game-bin>"` | Workspace Root | Re-extract symbols from `data.win` and regenerate all SDK bindings | Verified 2026-10-29 on game 7.0.14.0 (hub `c08e265`, default game path; `data.win` sha256 `7d66e5b5f579…`, vanilla `Hero_Siege.exe` sha256 `2c248a580810…`; idempotent: re-run after that commit, it left `git status` clean under `hs-game-sdk/` outside `curated/`). `data/manifest.json`'s `exe_sha256` is whatever exe is installed, so after ForgePact's Install it is the Aurie-patched one (`b364843e3763…` that day), not the vanilla hash. Earlier: 2026-09-17 (hub `4539e68`, `data.win` `07D864C91EFE…`) |
| `py -3 tools/closure_port_map.py table <exe> [--name <full name>]` | Workspace Root | Read an exe's compiled-code table from the file (no game launch): prints `rows=`, `file_version=`, `sha256=`, and with `--name` that function's `rva=`; exits 1 when the name is absent | Verified 2026-10-29 (7.0.14.0: `rows=20980`; 7.0.13.0: 20,951) |
| `py -3 tools/closure_port_map.py map --old-exe <old> --new-exe <new> --scan . --scan ForgePact --exclude ".claude/**" --out <json>` | Workspace Root | Pair every closure the hub and ForgePact spell with its new-build name, each with its evidence class (see "Mapping renamed closures after a game patch" below). Refuses, writing nothing, on a conflict or a sibling group whose size changed | Verified 2026-10-29 (7.0.13.0 → 7.0.14.0: 185 rows, 0 conflicts; `hs-game-sdk/curated/closure_renames_7_0_14_0.json`) |
| `py -3 tools/closure_port_map.py verify <json> --old-exe <old> --new-exe <new>` | Workspace Root | Recompute every row of a committed map; exits 0 only with both exe hashes matching the header and 0 conflicts, 0 mismatches | Verified 2026-10-29 (`sha256=match`, `conflicts=0`, `mismatches=0`, about 1 s) |
| `py -3 tools/closure_port_map.py rewrite <json> <path>... [--exclude <glob>]` | Workspace Root | Replace each old spelling (full name, short name, C++/Python identifier) with the new one in the git-tracked text files under each path, all rows in one pass, every other byte (CRLF included) kept | Verified 2026-10-29 (hub: 7 files, 21 replacements) |
| `py -3 tools/closure_port_map.py check <json> <path>... [--exclude <glob>]` | Workspace Root | List every old spelling still present that the new build does not have, then `stale=<n>`; exits 1 when n > 0. Skips the map file itself | Verified 2026-10-29 (hub after its rewrite: `stale=3`, all three in `tests/test_closure_port_map.py`, whose old-exe controls name 7.0.13.0 closures; `stale=0` with that file excluded) |
| `py -3 tools/generate_satanic_zone_sdk.py` | Workspace Root | Regenerate `satanic_zone.py`/`.hpp`/`.ts` from `hs-game-sdk/curated/satanic_zone.json` (hand-edited, not extracted) | Verified 2026-09-10 |
| `py -3 -m unittest discover -s tests` | Workspace Root | Run the SDK test suite. Passes in a clean checkout; extraction- and compiler-dependent suites skip (see below) | Verified 2026-09-12 |
| `py -3 -m unittest tests.test_cpp_sdk -v` | Workspace Root | Compile and run the C++ relic/hook behavioural tests against the stubbed YYToolkit surface | Verified 2026-09-12 |
| `py -3 -m unittest tests.test_item_type_parity -v` | Workspace Root | Check the Python, C++ and TypeScript `ItemType` declarations match value for value, the aggregates match their generator templates, and this guide's value table claims "measured in-game" for row 14 only | Verified 2026-09-20 (14 tests OK, node v24) |
| `py -3 -m unittest tests.test_sdk_lazy_import -v` | Workspace Root | Check, in fresh interpreters, that `import hs_game_sdk` builds no table and ForgePact's import list (the two Satanic pools since ForgePact PR #116) builds none either; that every name the eager package bound is still bound, as the same object; and that the static imports PyInstaller reads name every table (stdlib `modulefinder`, with a negative control). See "Import cost" above | Verified 2026-09-28 (14 tests OK), and again with ForgePact's two-name list. Against the eager `__init__.py` from before this change (hub `a06a1a1`, before #286), the five import-cost tests fail (8 failures with subtests) and the other nine pass; the same with the two-name list. With the `TYPE_CHECKING` block deleted, the scanner test and the block-matches-loader test fail |
| `py -3 -m pip install -e hs-game-sdk/python` | Workspace Root | Install Python SDK in development mode | Verified |

### Which tests need a game install, and which do not

`py -3 -m unittest discover -s tests` passes from a clean checkout with no game
installed and no build tools. Anything that cannot run there **skips** rather than
fails, because `hs-game-sdk/data/` is gitignored extraction output that no
contributor can be assumed to have:

| Suite | Needs | Behaviour without it |
| --- | --- | --- |
| `test_sdk_python.py`, `test_expanded_sdk.py`, `test_relic_identification.py` | nothing | always runs |
| `test_sdk_all.py` → `TestSdkArtifacts` | nothing | always runs |
| `test_sdk_all.py` → `TestExtractedDataArtifacts` | `hs-game-sdk/data/` | skips |
| `test_object_hierarchy.py` → `TestObjectParentChain` | nothing (reads the tracked bindings) | always runs |
| `test_object_hierarchy.py` → `TestObjectsJsonMatchesBindings` | `hs-game-sdk/data/` | skips |
| `test_extractor_layout.py` | nothing (builds a synthetic `data.win`) | always runs |
| `test_drop_roll_model.py` | nothing (the model, its fixture and the pilot docs); `ForgePact/` checked out for `LeverParityTests` | always runs; only `LeverParityTests` skips, when `ForgePact/plugin/ModuleMain.cpp` is absent (hub CI checks out without submodules), and `FixtureShapeTests` then skips checking `ForgePact/...` source paths |
| `test_mining_reward_model.py` | nothing (the model, its fixture and its spec); `ForgePact/` checked out for `RollsLeverParityTests` | always runs; only `RollsLeverParityTests` skips, when `ForgePact/plugin/include/ForgePact/MiningOreMod.hpp` or `ForgePact/src/forgepact.py` is absent (hub CI checks out without submodules), and `FixtureShapeTests` then skips checking `ForgePact/...` source paths |
| `test_monster_rank_model.py` | nothing (the model, its fixture, its spec and the tracked object bindings); `ForgePact/` checked out for `LeverParityTests` | always runs; only `LeverParityTests` skips, when `ForgePact/plugin/include/ForgePact/BossRarityMod.hpp` or `ForgePact/src/forgepact.py` is absent (hub CI checks out without submodules), and `FixtureShapeTests` then skips checking `ForgePact/...` source paths |
| `test_dungeon_chest_model.py` | nothing (the model, its fixture and its spec); `ForgePact/` checked out for `LeverParityTests` | always runs; only `LeverParityTests` skips, when `ForgePact/plugin/include/ForgePact/DungeonChestMod.hpp` or `ForgePact/src/forgepact.py` is absent (hub CI checks out without submodules), and `FixtureShapeTests` then skips checking `ForgePact/...` source paths and local `.claude/workorders/` captures |
| `test_unique_pick_model.py` | nothing (the model, its fixture and its spec); `ForgePact/` checked out for `LeverParityTests` | always runs; only `LeverParityTests` skips, when `ForgePact/plugin/ModuleMain.cpp` or `ForgePact/plugin/include/ForgePact/FlightCharms.hpp` is absent (hub CI checks out without submodules), while `FixtureShapeTests` skips checking `ForgePact/...` source paths only when `ForgePact/docs` is absent, so a ForgePact checkout that predates the paths the fixture cites fails it rather than skipping |
| `test_soul_piece_model.py` | nothing (the model, its two curated files, its spec and the tracked room and object bindings); `ForgePact/` checked out for `ParityTests` | always runs; only `ParityTests` skips, when `ForgePact/plugin/include/ForgePact/SoulPieceMod.hpp` is absent (hub CI checks out without submodules) |
| `test_number_compress_model.py` | nothing (the model, its fixture and its spec); `ForgePact/` checked out for `LeverParityTests` | always runs; only `LeverParityTests` skips, when `ForgePact/plugin/include/ForgePact/NumberGuard.hpp` is absent (hub CI checks out without submodules) |
| `test_cpp_sdk.py` | Windows + MSVC or g++/clang++ | skips |
| `test_sdk_lazy_import.py` | nothing (starts fresh interpreters of the Python running the suite) | always runs |
| `test_item_type_parity.py` | nothing (parses the tracked bindings and this guide); `node` for the executed-TypeScript sub-test | always runs; only `test_executed_enum_matches_python` skips, when `node` is missing from `PATH` or older than 22.7 (no `--experimental-transform-types`); `TestGuideRecordsTheMeasuredRow` checks this guide's ItemType table names only row 14 as "measured in-game" |
| `test_curated_stash_containers.py` | nothing (reads the tracked `curated/stash_containers.json`, the SDK and `docs/RUNTIME_DATA_MODELS.md`) | always runs |
| `test_closure_port_map.py` | nothing (synthetic builds and the committed map); both game executables for `ExeTests` | always runs; only `ExeTests` skips, when the 7.0.13.0 or 7.0.14.0 exe copy is absent |

`test_extractor_layout.py` is how the OBJT offsets stay verifiable without the
game: it writes a tiny GameMaker IFF file by hand, with each field at its
documented offset and a distinct value, so a one-field shift fails immediately.

`test_cpp_sdk.py` compiles `tests/cpp/test_sdk_player_hooks.cpp` against the
**unchanged** production headers, with the YYToolkit and Aurie surfaces supplied
by `tests/cpp/stubs/`. Because the SDK detects YYToolkit with
`__has_include(<YYToolkit/YYTK_Shared.hpp>)`, putting the stubs on the include
path is enough to compile the real code paths and drive them with controlled
responses - no Aurie runtime, no DLL in the game, no live game.

### Mapping renamed closures after a game patch

A game patch renumbers anonymous closures (`anon@N`, `___struct___N`; see
`docs/RUNTIME_DATA_MODELS.md` § 5.3), so the regenerated bindings drop the old
spellings and every C++ constant, research table and doc that used one stops
resolving. `tools/closure_port_map.py` (stdlib only) pairs the old names with
the new ones from the two executables' compiled-code tables, without launching
the game. What to do, in order:

1. **Before Steam updates the game**, copy the current `Hero_Siege.exe` to a
   plain path outside the game folder (the 7.0.13.0 copy is
   `%USERPROFILE%\tools\hs-bin\Hero_Siege.exe`, an Aurie-patched one; the
   table reads the same from a patched or a vanilla exe). Once the update
   lands the old build is gone from the machine, and no map can be made
   without it.
2. After the update, copy the new exe to its own plain path as well (Install
   patches the installed one, and Ghidra's headless launcher cannot take a
   path containing `(x86)`), then regenerate the SDK with
   `extract_and_generate_sdk.py`.
3. `map --old-exe <old> --new-exe <new> --scan . --scan ForgePact --exclude
   ".claude/**" --out hs-game-sdk/curated/closure_renames_<new version>.json`.
   Commit the map; it is the one tracked file allowed to keep the old
   spellings.
4. `verify` the map against both exes, then `rewrite` each repository
   (`. --exclude ".claude/**"`, and `ForgePact`). Fix by hand what a token
   match cannot see: truncated labels, a bare `anon@N` a test asserts, prose
   that explains a number, and negative controls built on a deliberately wrong
   name (give those a number neither build has).
5. `check` both repositories until it prints `stale=0`, then build and run the
   suites. A name `check` cannot flag is one that still exists in the new
   build but now names a different closure (on 7.0.14.0, one of `SaveStash`'s
   `___struct___` closures); the map's `name_survives` column marks those, so
   `rewrite` handles them and `check` need not.

What each row's `evidence` means:

| Evidence | Meaning | How much to trust it |
| --- | --- | --- |
| `name-unique` | The closure is the only member of its group (same name with the closure numbers blanked) in both builds | As good as a name lookup |
| `fingerprint-unique` | Its code fingerprint (direct calls to other compiled functions, referenced strings, size) matched its rank partner better than any sibling by at least the margin (0.05) | Strong; still a static reading |
| `rank-order-fingerprint-tie` | Two or more siblings have identical fingerprints, so the pairing is the k-th closure of the old group to the k-th of the new one | Rank order only. Treat it as unverified until a live session or a decompile of both builds separates the siblings |
| `rank-order-no-fingerprint` | No fingerprint could be taken (a leaf function with no extent found) | Rank order only, as above |

`map` refuses rather than guessing: a sibling that outscores the rank partner
by more than the margin, or a group whose member count changed, exits 1 and
writes nothing. The 7.0.13.0 → 7.0.14.0 map had 0 of either; its counts are in
the map's header and in § 5.3.

---

## Runtime helper semantics

### `Player::GetOwnedRelicLevels` / `GetMaxedRelicIds` — relic identification

Both take the player as an **instance handle of either kind**: `VALUE_OBJECT` or
`VALUE_REF`, tested with `Player::IsInstanceHandle`. This runner produces
`VALUE_REF` (kind 15) for the local player, so the reference is the normal case —
see `docs/RUNTIME_DATA_MODELS.md` §1.

That was a real defect too (REPORTED 2026-09-14): the gate read
`player.m_Kind != VALUE_OBJECT -> return {}`, so the scan returned an empty map
for every player on this runner. An empty maxed set means "nothing to hold back",
which is indistinguishable downstream from "the player owns no maxed relics" —
so `ForgePact`'s relic filter armed, installed its hook, logged
`hook installed -> ON`, and filtered nothing, for every user, silently.

If a caller hands in something that is neither kind (an undefined value, a bare
instance id), the scan still returns empty rather than guessing: convert an id
with `GetInstanceObject` first.

An item counts as a relic only on **positive identification**: rarity tier 16 via
`c` / `cls` / `itemType`, the relic-specific `relicLevel` field, or the **item
class** of the instance or save entry that holds the definition (below). Level is
read only from `o`, `level` and `relicLevel`.

**The game's own relics carry none of the tier fields on their definition**
(#93, read from a character save 2026-09-27). A save's `[inventory]` JSON has an
`equipped_items` dict keyed `0-0-<stamp>-<class>`, whose trailing number is the
item class (`ItemType`, 16 = relic), each value `{"data": {...}}`: for a relic,
`g` is the equip slot (10-14), `o` the level, `b` the relic id, and `c` is **0**
(1 on unique gear; it is not a rarity tier). There is no `relicLevel`, `cls` or
`itemType` in the definition. In memory the class is `itemType` on the item
**instance**, beside its `itemDefinitionStruct`. So the scanners also recognise:

- **an item instance**: a struct/dict carrying `itemType` and
  `itemDefinitionStruct`; `itemType == 16` identifies it, and `b`/`o` are read
  from the definition, which is scanned with that identification carried (both
  bindings);
- **a save entry**: a dict key `x-y-<stamp>-<class>` whose class is 16, with id
  and level from its `data.b` / `data.o` (Python only, since only Python reads
  saves; the traversal difference below).

The `c == 16` rule is kept, so every earlier fixture and caller still behaves the
same, but it has **no measured match** on a game item: treat it as a
compatibility rule, not as how relics are found. An equipped unique glove
(`itemType` 4, `{b:18, c:1, g:4}`) and a material stack (`itemType` 14,
`{b:51, o:99}`) are the negative controls beside the relic instance in the shared
cases.

**The equipped relic slots are not on the player instance** (C++,
`Player::ScanEquippedRelicSlots`, called by `GetOwnedRelicLevels` after the
container passes). Measured live on 2026-09-27 (ForgePact #93, Live 1): the
player has no `equippedItems` variable at all (reading it answered "no such
variable"), and the game keeps the local character's equipped items only as
fingerprint strings in `global.equippedItems[global.mplr][0][slot]`, where
`global.mplr` read 1 for the offline character. The scan reads
slots 10-14 (`kFirstRelicSlot`..`kLastRelicSlot`), resolves each string with the
game's own scripts, by `HeroSiege::Scripts` name through `CallGameScriptEx` with
the global instance as self and other: `GetOnlinePlayerItemOwner(mplr)`, then
`GetItemFromFingerprint(fingerprint, owner)`, and scans the returned item instance.
Nothing is guessed: an `mplr` that is not a whole number in 0..4 reads nothing, a
slot that is not a non-empty string is never passed to the resolver, and a
fingerprint that resolves to anything but a struct is skipped. It is the route
ForgePact's Miner's Helmet reads slot 0 through, confirmed live 2026-09-23, and
the **relic** slots 10-14 were measured on 2026-09-27: all five held `…-16`
fingerprints, every one resolved to a relic instance, and the ids and levels
equalled the character save's `equipped_items`. ForgePact's relic filter logged
it at arm time:

```
relicfilter: scan found 3 maxed relics (ids 109,124,135)
relicfilter: equipped slots mplr=1 slots=18 inrange=5 strings=5 owner=ok resolved=5 refused=0 nonstruct=0 noclass=0 relic=5 otherclass=0 relics=10:15@8,11:135@10,12:124@10,13:140@9,14:109@10 control=resolved itemType=0 stopped=none
```

The second line is `FormatEquippedSlotScanReport` of the
`EquippedSlotScanReport` that `GetOwnedRelicLevels` and `GetMaxedRelicIds` fill
when a caller passes one: each stage counted, the helmet slot resolved once as a
positive control, and `stopped=` naming the stage that ended a short scan, so a
zero says which stage read nothing. `tests/cpp/test_sdk_player_hooks.cpp`'s
`TestEquippedSlots` drives it through a stub whose `CallGameScriptEx` answers per
script name with a struct, a number or undefined.

**The relic tab is read the same way** (C++, `Player::ScanRelicTab`, called by
`GetOwnedRelicLevels` after the equipped slots; ForgePact #125, hub #324). The
relics a character owns but does not wear sit in
`Controller_obj.inventoryData[key - 1].inventoryRelicGrid[relicId][0][0]`, one
grid node per owned relic id, whose `nodeFingerprint` is the fingerprint. `key` is
1 when `global.onl` is 1 and the player row (`global.mplr`) otherwise. That is the
rule the game's own `PickupRelic` and `RelicCheckAchievement` use, with
`GetProfileInventoryData` reading index `key - 1` (static reading of the Sep-17
build, 2026-09-30; hub `docs/models/relic-pick-spec.md`). Measured live the same
day (ForgePact #125, Live 1): offline, `mplr` is 1, `inventoryData` holds one
`New_Inventory_Data_obj` reference, and its 156-cell grid holds `[[node]]` or
`[[undefined]]`. The scan resolved all 100 of the character's tab relics and named
its two maxed ones:

```
relicfilter: relic tab key=1 profile=0 online=no grid=156 cells=156 nodes=100 strings=100 owner=ok resolved=100 refused=0 nonstruct=0 noclass=0 relic=100 otherclass=0 maxed=92@10,128@10 stopped=none
```
 `Controller_obj` is found by name
(`GetObjectName`, then the runner's `asset_get_index` and `instance_find(obj, 0)`),
the profile entry may be a struct or an instance reference, and each fingerprint
goes through the same owner and resolver as the equipped slots. The route reads
variables only and never calls `GetProfileInventoryData`, which has crashed the
game when called cold (RUNTIME_DATA_MODELS §9.4). `RelicTabScanReport` and
`FormatRelicTabScanReport` count each stage and name the one a short scan stopped
at, beside the maxed relics it found; pass one as
`GetOwnedRelicLevels`/`GetMaxedRelicIds`' fourth argument. Only a node with a
non-empty `nodeFingerprint` string reaches the resolver. C++ only, like the equipped-slot route: the Python binding reads the
same tab from a save (`inventory_relic_tab`, keyed `x-y-<stamp>-16`, `o` absent at
level 1), pinned by `tests/test_relic_identification.py` (`TestSaveRelicTab`).
`TestRelicTab` in `tests/cpp/test_sdk_player_hooks.cpp` drives the C++ route:
the offline and online keys and their `key - 1` index, a row of 0 with no profile,
a missing controller, a key past the profiles, a profile without a grid, a bare
string where a node belongs, a refused owner, and the tab joining the equipped
slots.

A level-shaped field is not evidence of relic-ness, and this was a real defect
(REPORTED 2026-09-12 against PR #3): the scanner accepted `isRelic || level > 0`,
so the ordinary item `{b:15, c:8, level:100}` was reported as maxed relic 15.
`ForgePact`'s `RelicFilterMod` calls `GetMaxedRelicIds` directly, so that false
positive could suppress an unrelated relic drop. `p` is a star upgrade count and
stacks carry `amount`/`count`/`qty`, so the old field list both invented relics
and inflated levels past the maxed threshold.

Container shape matters too, via `Player::ContainerKind`:

| Kind | Containers | A bare number means |
| --- | --- | --- |
| `General` | `equippedItems`, `equipped_items`, `inventory`, `bags` | nothing - item structs only |
| `RelicTable` | `relic_levels`, `relics`, `relic_tab`, `relic_array`, `pRelics`, `relic_inventory`, `relics_collected`, `inventory_relic_tab`, `relicPage` | `relic id -> level` |

#### The contract shared with the Python SDK

Both scanners must accept exactly the same layouts. REPORTED 2026-09-12 by
origin's second review of PR #3: C++ recognised `cls` and read numeric arrays out
of `relic_levels` while Python did neither, so on identical input
`{"relic_levels":[0,0,10]}` C++ said `{2:10}` and Python said `{}`. They now
declare one contract, as enumerable constants on both sides:

| Contract | Value | C++ | Python |
| --- | --- | --- | --- |
| Id fields | `b`, `relicId` | `kRelicIdFields` | `RELIC_ID_FIELDS` |
| Rarity-tier fields (`== 16` means relic) | `c`, `cls`, `itemType` | `kRelicTierFields` | `RELIC_TIER_FIELDS` |
| Level fields (highest present wins) | `o`, `level`, `relicLevel` | `kRelicLevelFields` | `RELIC_LEVEL_FIELDS` |
| Relic-only field (presence means relic) | `relicLevel` | `kRelicOnlyField` | `RELIC_ONLY_FIELD` |
| Relic item class (instance `itemType` or save-key class) | `16` | `kRelicItemClass` | `RELIC_ITEM_CLASS` |
| Item instance fields (class, definition) | `itemType`, `itemDefinitionStruct` | `kItemInstanceTypeField`, `kItemInstanceDefinitionField` | `ITEM_INSTANCE_TYPE_FIELD`, `ITEM_INSTANCE_DEFINITION_FIELD` |
| Equipped relic slots | `10 .. 14` | `kFirstRelicSlot`, `kLastRelicSlot` | `EquipmentSlot.RELIC_0` .. `RELIC_4` |
| General containers | see table above | `kGeneralContainerFields` | `GENERAL_CONTAINER_FIELDS` |
| Relic containers | see table above | `kRelicContainerFields` | `RELIC_CONTAINER_FIELDS` |
| Plausible id range | `0 .. 159` | `kRelicIdLimit` | `RELIC_ID_LIMIT` |
| Maxed at | `10` | `kMaxedRelicLevel` | `MAXED_RELIC_LEVEL` |
| Recursion budget | `5` | `kMaxScanDepth` | `MAX_SCAN_DEPTH` |
| Array read cap | `512` | `kMaxScannedArrayLength` | `MAX_SCANNED_ARRAY_LENGTH` |

They are enumerable rather than inline literals for one reason: the C++ harness
prints them and `tests/test_cpp_sdk.py` asserts the Python tuples match field for
field, so editing one side without the other fails a test instead of drifting
silently. The three reported cases are in that shared suite too, negative control
included.

**One difference is deliberate: how each side walks its input.** C++ reads named
variables off a live `CInstance` and can only follow what it looks up - the `data`
field and array elements - because YYToolkit gives it no way to enumerate a
struct's keys. Python walks every key of a decoded save-file tree. So
`{"inventory": {"bag1": [relic]}}` resolves in Python and has no C++ equivalent
to resolve. The contract above is about *which layouts are recognised*; the
traversal differs because the inputs do. There is no TypeScript scanner -
`ts/src/player.ts` only carries `EquipmentSlot` - so the contract covers exactly
these two implementations.

### `Player::ReadGroundRelic` — is this ground item a relic, and which one

```cpp
HeroSiege::Player::GroundRelicRead read;
if (HeroSiege::Player::ReadGroundRelic(yytk, groundInstance, read)) {
    // read.relicId is the relic's id, 0 .. kRelicIdLimit - 1
} else {
    Log("not a relic: " + HeroSiege::Player::FormatGroundRelicRead(read));  // stage=not-relic class=4 id=-1
}
```

Added for ForgePact#124 (the pet collecting relics). A dropped item is a `Loot_Ground_obj`
instance, and the read goes through the item instance it holds in `kGroundItemInstanceField`
(`itemInstance`): the class in that item's `kItemInstanceTypeField` (`itemType`) and the
definition in its `kItemInstanceDefinitionField` (`itemDefinitionStruct`), whose first present
`kRelicIdFields` entry (`b`) is the id. A class-shaped variable on the ground instance itself
is never read. It is
the same positive identification the owned-relic scan uses: the class must equal
`kRelicItemClass`, never a literal `16`, and an id-shaped or level-shaped field (`relicLevel`
included) is never evidence on its own. A definition with no class beside it is refused,
because a relic's definition carries `c` 0 and no class (#93).

It accepts both instance kinds through `IsInstanceHandle`, `VALUE_OBJECT` and the
`VALUE_REF` this runner produces, and reads them through `variable_instance_*`, which takes a
reference straight through. It returns true only when it reaches `Ok`. `GroundRelicRead` is
reset on every call, so a refusal never keeps an earlier read's id, and it names the stage
the read stopped at:

| Stage (`GroundRelicStageName`) | Meaning |
| --- | --- |
| `no-handle` | no interface, the value is not an instance handle, or the read threw |
| `no-item-instance` | no `itemInstance` on the ground instance, or one that holds no struct or reference |
| `no-class` | no numeric `itemType` on the item instance |
| `not-relic` | the class is read (`itemClass`) and is not `kRelicItemClass` |
| `no-definition` | a relic class, but no `itemDefinitionStruct` struct |
| `no-id` | the definition has no id, or one outside `0 .. kRelicIdLimit - 1` |
| `ok` | a relic; `relicId` is set |

`not-run` is the default of a `GroundRelicRead` no call has filled.

**C++ only.** A ground instance exists only in the running game's memory, and the Python
binding reads saves, so there is no Python twin and no parity claim beyond the shared
constants the read uses. **The variable names are measured** (ForgePact#124 Live 1,
2026-10-02, research build): `petrelic census` read 42 of 42 ground relics on screen
(`read stages: ok=42`) through `itemInstance`, its `itemType` (16) and its
`itemDefinitionStruct.b` (the relic id the research command had placed). They came first
from a static reading of the ground item's Create. Whether the ground instance also carries
a top-level `itemType` copy is still **not established**: the capture did not record the
census's `first relic vars:` dump, so the read never looks for one. Should a later game build
make the read refuse every ground item on screen, suspect the names before the item.
`tests/cpp/test_sdk_player_hooks.cpp` (`TestGroundRelic`, driven
by `tests/test_cpp_sdk.py`) pins a relic through both kinds, an ordinary glove and a
material stack refused as `not-relic`, a classless instance refused as `no-class`, and an
undefined value refused as `no-handle` as the negative control for accepting a reference.

### `Hooks::InstallScriptHook` — both call routes, and safe to install twice

```cpp
static PFUNC_YYGMLScript g_origDropRelic = nullptr;  // static, zero-initialised

HeroSiege::Hooks::ScriptHookOptions options;
options.selfModule = g_ArSelfModule;      // required for native interception
options.hookId = "forgepact_drop_relic";  // required, unique per detour
const auto result = HeroSiege::Hooks::InstallScriptHook(
    yytk, "gml_Script_DropRelic", &Hook_DropRelic, &g_origDropRelic, options);
if (!result.IsNative()) {
    Log(std::string("table-only: ") + result.note);  // surface it, do not ignore it
}
```

A script-table swap alone catches only calls the game routes through the table;
compiled GML also calls straight into the function's address. So the installer
does **both** - the table swap and an inline detour - and `*outOriginalFunc`
becomes the trampoline, reaching the real original from either route without
re-entering the hook. See the "Prove the Instrument" rule in
[`AGENTS.md`](../../../AGENTS.md).

Check `result.kind`:

| Kind | Meaning |
| --- | --- |
| `Native` | both routes covered |
| `TableOnly` | the detour could not be installed; `note` says why, and direct compiled-GML calls bypass the hook |
| `AlreadyInstalled` | a hook was already present; the recorded original was left alone |
| `Failed` | nothing was installed |

Repeat installation is safe, which matters because a shared chokepoint gets hooked
from more than one call site. The detour is attempted only on the first install
(`!*outOriginalFunc`) - the one moment the table still holds the game's own
function - and the table entry must be executable code inside the game module, or
it is not ours to patch. Pass a **static, zero-initialised** original pointer: it
is how the installer knows which install is the first.

**Every detour pays Aurie's freeze, and the freeze scales with the whole
machine's thread count.** Measured in ForgePact#151's Live 1 (2026-10-06, the
owner's machine, about 6000 threads system-wide, 76 in the game): one
`MmCreateHook` detour cost 66-73 ms, 2.1 times one timed system-wide thread
snapshot (32.8 ms median), and the detours were 97.5% of ForgePact's 1268 ms
start-up setup (18 detours); 20 hooks installed on demand in town held one frame
1.5 s. Why it costs that much is a static reading of Aurie v2.0.2, which the
ratio agrees with: `MmCreateHook` suspends the process's other threads, creates
the hook, and resumes them, and both the suspend and the resume start from a
`CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD)`, which lists every thread on the
system, not only the game's. So each install that detours pays for two
system-wide thread snapshots, and a frame that installs many hooks holds the
game for about 70 ms per hook on that machine. ForgePact's setup line and its `incident setup`
verb time each part of an install. That is upstream Aurie's cost. The hub's
patched `AurieCore.dll` ([`third_party/aurie/`](../../../third_party/aurie/README.md),
series `hs.1`, which ForgePact ships from 2.2.0) walks only the game's own
threads, and its Live 2 (2026-10-06, same machine and plugin, only the DLL
changed; capture `.claude/workorders/forgepact-151-aurie-freeze-live-1.md`)
measured a detour at 1.56 ms against a 37.9 ms system-wide snapshot median,
ForgePact's setup at 47.8 ms (18 detours, 28.1 ms of them), and the 20 on-demand
installs at 35.0 ms of detours with the worst frame 122 ms. A detour under
upstream's `AurieCore.dll` (what HS-Offline-Tracker shipped through 0.1.3) still pays the
system-wide walk. The reading, the measurements and the route as built are in
[`ForgePact/docs/setup-stall-research.md`](../../../ForgePact/docs/setup-stall-research.md)
(ForgePact#151).

`InstallScriptHookTableOnly` is a deliberately limited variant, named so the
limitation is visible at the call site. It exists for research - observing
table-routed calls without patching code - and still preserves the original
across repeat installs. It is not what a shipped gameplay hook should use.

---

### Never hand-edit a generated file

`tools/extract_and_generate_sdk.py` rewrites **every** file under `python/hs_game_sdk/`,
`cpp/include/hs_game_sdk/` and `ts/src/` on each run — including the ones with no extracted
content in them (`__init__.py`, `hs_game_sdk.hpp`, `yytk_helpers.hpp`, `index.ts`), which come
from string templates inside the generator. Editing those files in place works right up until
the next extraction silently reverts them. Change the template in the generator instead, then
re-run it; regeneration is idempotent, so a second run must produce no diff.

`satanic_zone.py`/`.hpp`/`.ts` are the exception: they belong to
`tools/generate_satanic_zone_sdk.py` and are regenerated from `curated/satanic_zone.json`.

"Every file" is broader than the code, though: `player.py`/`.hpp`/`.ts`, `hooks.hpp`,
`mod_registry.py`, `item_type.py`/`.hpp`/`.ts`, `drop_roll_model.py`, `mining_reward_model.py`,
`monster_rank_model.py`, `dungeon_chest_model.py`, `unique_pick_model.py`, `soul_piece_model.py` and `number_compress_model.py` are hand-written, and the generator neither writes nor deletes them. Edit those in place. The
models are not wired
into any aggregate on purpose (import it by its module name), and it has no C++ or TypeScript
counterpart. They still have to be wired into the aggregates
through the templates — `init_content`, `main_header` and `index_content` all include
`item_type` now, and `tests/test_item_type_parity.py` fails if a committed aggregate stops
matching its template.

`init_content` also carries the lazy loader (2026-09-28, "Import cost" above). Its `TYPE_CHECKING`
imports and its `_LAZY_MODULES` table both list the five tables and their names.
`tests/test_sdk_lazy_import.py` fails if the two disagree, or if a bytecode scanner stops finding a
table.

---

## Safety, Git & Intellectual Property Boundaries

* **No Game Binaries / Bytecode in Git**: Root `.gitignore` excludes `data.win`, `.exe`, `.dll`, audio groups, texture pages, and raw dump folders (`hs-game-sdk/data/`, `raw/`, `extracted/`). `hs-game-sdk/curated/` is the deliberate exception to this rule: it holds hand-verified data (not extracted bytecode/assets) and is meant to be shared, so it is tracked normally.
* **Interoperability Definitions**: Distributes typed symbol names, enum IDs, and data structures necessary for interoperability and modding.
* **Idempotent Regeneration**: Extraction tooling is deterministic and can be rerun against any updated game binary to regenerate SDK bindings.


## Independent reward cooperation (2026-09-22)

`cpp/include/hs_game_sdk/reward_scope.hpp` provides a process-local, thread-owned
RAII scope shared by AFK FARM and optional ForgePact. It exposes compatibility
and observed native drop denominators, never calls plugin symbols, and restores
scope depth on exception. Keep mapping version/layout identical in both builds.
`reward_stats.hpp` distinguishes runtime query IDs from item/UI stat IDs: native
`ReturnSpecificStat` Magic Find uses query 34 on the verified AFK build.

AFK's C++ rewards smoke checks defaults, bounds, nesting, thread isolation,
exception restoration and published bases. Native MF positive control requires
the query to reach StatMagicFind, not just return a plausible number.

## Native routine names (AFK FARM, 2026-09-23)

`cpp/include/hs_game_sdk/native_names.hpp` (namespace `HeroSiege::Hooks`) finds
the one function that references a GML routine's name string: it looks for the
NUL-terminated name in readable, non-executable sections, then for RIP-relative
`LEA` references to it inside caller-supplied function bounds. Ambiguous matches
and names inlined into another script's body are refused. It never calls or
patches a resolved address, and an offline PE probe runs the same search as the
live one. AFK FARM's plugin (`HS-AFK-Expedition/plugin`) includes it; ForgePact
does not.
