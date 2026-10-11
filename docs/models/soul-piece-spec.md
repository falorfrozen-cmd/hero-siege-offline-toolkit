# Where a boss soul piece drops, how often, and what using one does: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/soul_piece_model.py`](../../hs-game-sdk/python/hs_game_sdk/soul_piece_model.py)
(`soul_piece_model`), tested by
[`tests/test_soul_piece_model.py`](../../tests/test_soul_piece_model.py)
against [`hs-game-sdk/curated/boss_soul_pieces.json`](../../hs-game-sdk/curated/boss_soul_pieces.json)
and [`hs-game-sdk/curated/room_acts.json`](../../hs-game-sdk/curated/room_acts.json).
It was written for ForgePact#197, whose **Boss soul pieces** switch lets an
ordinary monster in a zone of an act drop a Piece of that act's boss's Soul.
Right-clicking a piece in the backpack and confirming opens a portal beside the
player to that act's boss room, where the room brings out its boss. The spec
answers three questions: what the game decides (which act a room belongs to,
which items stack, when the game rolls a gem, and when a backpack use leaves the
item gone), and exactly what the mod adds on top (which rooms and sources count,
the piece's chance on the gem's roll, and where its portal leads).

Every claim carries one of four labels, and a source:

- **Static reading**: read from the compiled game or from `hs-game-sdk`'s
  extracted tables, and written here in our own words. No script text is quoted
  or transcribed (`AGENTS.md` § "Legal").
- **Measured**: observed in a running game. ForgePact#197's sessions are
  named by their capture; Live procedure 1's is
  `forgepact-197-boss-soul-pieces-live-1` (2026-10-11, slot 14).
- **Our code**: what ForgePact does. The model leaves it out, and the test
  expresses it as an input transform.
- **Not established**: carried by the model as an open hypothesis, or left out.

The game facts behind this spec are in
[`docs/RUNTIME_DATA_MODELS.md`](../RUNTIME_DATA_MODELS.md) § 21 (acts, act
bosses, key items and stacking, the backpack's use path, portals and travel)
and § 18.4 (how a gem drops).

## Static reading

Read on 2026-10-11 through the `ghidra` MCP on build `498d588550d8`, plus local
byte scans of the game's executable and `data.win` whose positive controls were
`PickupLoot`'s known callers and a known object event row.

- **The act of a room.** `RoomActIndex(room)` (`gml_Script_RoomActIndex`) is a
  switch over 175 room constants into nine cases. Its answer starts undefined
  and only a matching case sets it, so a room outside the 175 has no act. Two
  direct callers (byte scan) pick an act's texture pages from the answer, so the
  game itself relies on it. The table, room by room with its SDK index, is
  `room_acts.json`; rows per act, 1 to 9: 21, 24, 16, 15, 14, 20, 17, 19 and 29.
  A room's name does not always give its act (`Act_08_Orres_Lair_rm` is act 4).
  `Act_01_Boss`, `Act_03_Boss`, `Act_04_Boss`, `Act_05_Boss` and `Act_07_Boss`
  are not in the switch; `Act_02_Boss`, `Act_06_Boss`, `Act_08_Boss` and
  `Act_09_Boss` are. What the answer is, is measured (below).
- **The act bosses and their rooms.** No act boss room places a descendant of
  `Enemy_Child_Boss_obj` in its room list; each places a `Pentagram_Boss_obj`.
  The pentagram's alarm creates the room's boss at the pentagram on the game
  layer, choosing by room; the objects it can create include `Gurag_obj`,
  `Reaper_obj`, `Anubis_obj`, `Damien_obj`, `Karp_King_obj`, `Satan_obj`,
  `Mevius_obj` and the Odin cutscene, and `Cthulhu_obj` was not seen among
  them. Which room maps to which object was not read. A boss's death runs
  `LoadBossDeath`, which needs the room's `Pentagram_Boss_obj`. Which boss
  belongs to which act is read from each boss room's decor: `Gurag_obj` (act 1,
  `Act_01_Boss`), `Reaper_obj` (2), `Anubis_obj` (3), `Satan_obj` (6),
  `Odin_Phase_1_obj` (8) and `Cthulhu_obj` (9). Acts 4 (`Damien_obj`) and 5
  (`Karp_King_obj`) are an inference: their decor names no boss, and those two
  are what remains of the Key of Terror's six bosses. Act 7's boss,
  `Mevius_obj`, is the owner's decision (2026-10-11), not a reading. All nine
  descend from `Enemy_Child_Boss_obj` through `Enemy_Parent_obj` in
  `hs-game-sdk`'s parent table, and each act's boss room is `Act_0N_Boss`
  (`boss_soul_pieces.json` `acts`, with the SDK's room index).
- **Pickup and stacking.** `PickupLoot`'s general path ends in
  `AddToInventory`, which tries a stack before placing an item as a new one:
  `InventoryGridAddToStack` for a class with a tab of its own (the Key,
  Material and Socket tabs), `GridAddToStack` for the bag. Both walk their grid
  and merge the item into one whose class matches and whose definition's `b`
  and `c` match, comparing those three fields themselves; neither calls
  `ItemsAreStackable`, and the seed `a` is never compared. The bag's attempt
  first accepts only classes 12, 13, 14 and 15, as `IsItemTypeStackable`
  answers, so a class-11 consumable never stacks there. `c` is the repository
  flag (0 normal, 1 unique), so changing it loads a different item.
- **The backpack's use.** `UiAInventoryConsumeItemConfirm` answers a "use this
  item?" prompt: it asks `PotionUse` with the item, and only when that answers
  true does it clear the item's cells one by one (`InvGridClearItemNode`).
  `CanUsePotion` runs at the right-click, before the prompt, and reads the
  item and the current room. `PotionUse`'s own body was not read.
- **Portals and travel.** A portal keeps its state in the protected store:
  `Portal_Parent_obj`'s Create keeps record keys in `portalZone`,
  `portalActive`, `isEligible`, `portalUsable` and `pSpwd`. `Portal_obj` (a
  child of it, SDK object 3593) writes a room into its `portalZone` record; its
  inherited collision with the player waits for an interact press, and its
  alarm reads the room back and calls `NetworkRoomGoto` with it. Offline,
  `NetworkRoomGoto` ends in `RoomGoto`, which sets the room's layers up once
  and then calls the `room_goto` builtin.
- **The gem roll.** `LoadDrops` asks, per drop type, an outer gate for the
  dying source: the monster's own `chances[6]` (45 on the sampled monster)
  against a die whose ceiling lives in `gDataProtected`. Only when it passes
  does it reach `DropGems` (drop type 6). `DropGems` reads the repository
  entries of category 15 (socketables), each one's `GetDropRate` answer and a
  `gDataProtected` member, floors a value and rolls.
- **`GetDropRate`** (a method of the item base definition, in the SDK as
  `gml_Script_GetDropRate_anon_55737_s_ItemBaseDefinition_DefineStructs`, a
  closure name that moves with every patch) answers the entry's
  `droprate.base`, replaced by a per-place field where the entry carries one and
  the room matches: boss dungeons, Chaos Tower, Niflheim, rifts, Ruby, Sheep,
  specials and ubers.
- **The Gem of Incarnation** is repository entry
  `socketable_gem_of_incarnation`, class 15, `b` 136. The only PAS-named item
  is `consumable_edible_pas_logo`, a consumable.

## Measured

All by Live procedure 1 (`forgepact-197-boss-soul-pieces-live-1`, 2026-10-11),
in our words; the capture holds the lines.

- **`RoomActIndex` answers the act itself**: 1 in `Town_01_rm` and in
  `Act_01_01`, 2 in `Act_02_01`. An earlier reading took the answer for the act
  less one; this corrected it, and those three rows of `room_acts.json` are
  `measured`.
- **The Gem of Incarnation's `droprate.base` is 9,000**, read by repository
  name, not the 10,000 its info key carries in the local drop records. A built
  gem's `itemSprite` read undefined.
- **A key-base piece merges into the real key.** Pieces built on a key
  definition, marked by their seeds, merged on pickup into the owner's own key
  stack of that definition (its count rose by two each time, its own seed
  kept), and the merge survived a reload. A both-route detour on
  `ItemsAreStackable` counted no call while they merged.
- **The Edible PAS Logo's use.** The owner's own logo is class 11, `b` 12. Its
  right-click and confirm reached `CanUsePotion`, `PotionUse` (answering
  true), `InvGridClearItemNode` and then `UiAInventoryConsumeItemConfirm`, each
  carrying the item, and the logo was used up. A potion drink reaches
  `PotionUse` with no item.
- **`DropGems`' `self` is the dying monster**: 29 rolls in `Act_02_01`, self
  `Chilling_Marksman_Passive_obj` or `Frost_Goblin_Passive_obj`, both
  descendants of `Enemy_Parent_obj`.
- **A boss outside its room crashes on death.** A `Reaper_obj` created in
  `Act_02_01` and brought to zero health crashed the game when its death found
  no `Pentagram_Boss_obj`; a Karp King made the same way in `Act_01_01` died
  cleanly (why they differ is not established).

## Not established

Each of these is an open question. Where it decides a number or a rule the
model uses, it is carried in the model's `HYPOTHESES`, `None` until the curated
file's matching `open_questions` entry is `measured`; the measured ones above
(`gem_roll_self_is_the_source`, `potion_use_true_clears_the_item`) are `True`.
Most are ForgePact#197's Live procedure 3 checks, named in the curated file.

- **`gem_one_in_its_rate`**: whether `DropGems` gives each socketable exactly 1
  in its `GetDropRate` answer, or picks one by weight among them. The model
  assumes 1 in the rate. Not measured live: a gem is too rare for one session.
- **`room_outside_the_switch_is_undefined`**: that a room outside the switch
  answers undefined is a reading (`portal-travel` reads it in `Act_01_Boss`).
- **`class_11_never_stacks`**: that a class-11 piece takes its own bag cell,
  apart from a real Edible PAS Logo and from other pieces (`piece-apart`).
- **The base's name**: that category 11's entry 12 is named
  `consumable_edible_pas_logo` (`base-consumable`).
- **The use and the portal**: whether a piece's right-click reaches
  `PotionUse` carrying the piece (`use-reaches-game`); whether a `Portal_obj`
  whose `portalZone` record holds a boss room takes the player there through
  the game's own travel (`portal-travel`); whether the room's pentagram brings
  out the boss (`boss-arrives`) and the boss dies there without a crash
  (`boss-dies-2`); whether a zone where a portal was opened loads again on
  revisit (`portal-revisit`). Whether `CanUsePotion` refuses the logo in town
  or any room, and whether a kill through a piece's portal counts toward the
  act's quest or completion.
- **Magic find.** No magic-find stat name appears in `DropGems`' or
  `GetDropRate`'s body. That is "not observed", not a negative.
- **Per-place overrides on the gem.** Whether the Gem of Incarnation carries a
  per-place field (rifts, ubers, boss dungeons) was not read; where it does, the
  game's chance there differs from `droprate.base`.

## Our code

**ForgePact's Boss soul pieces** (`soulpiece 1|0|on|off|status|force on|force
off`, config key `mod_boss_soul_pieces`, off by default, ForgePact#197,
`ForgePact/plugin/include/ForgePact/SoulPieceMod.hpp`). Write `G` for the Gem of
Incarnation's `droprate.base`, read at run time from its repository entry by
name (category 15, `socketable_gem_of_incarnation`), never by index.

- **Where it rolls.** Inside the game's own gem roll, as one more consumer of
  ForgePact's shared `DropGems` detour, after the original returns. A `DropGems`
  call means `LoadDrops`' type 6 gate already passed for the dying source, so
  the monster's own gem chance, the gate's die and every extra kill from density
  or spawner levers reach the piece exactly as they reach the gem. The piece adds
  no gate, no magic-find term and no slider.
- **The chance per `DropGems` call** is 1 in `D`, `D = max(1, floor(G × 4 / 5))`:
  five quarters of the gem's chance on the same roll (the owner, 2026-10-11:
  "a little more common than gem of incarnation"). With the measured `G` =
  9,000, `D` = 7,200. `G` unknown, zero or negative gives `D` = 0 and no piece
  (`no-rate`), unless forced.
- **Which rooms drop.** A room whose `RoomActIndex` answer is an act, except a
  town (name starting `Town_`, verdict `town`) and a boss room (name containing
  `_Boss`, or starting `Uber_` or `Dev_`, verdict `boss-room`). A room outside
  the act table gives `no-act`.
- **Which sources.** A source that does not descend from `Enemy_Parent_obj`
  gives `not-monster`; one that descends from `Enemy_Child_Boss_obj` gives
  `boss-kill`.
- **Drop verdict order**: `off`, `no-act`, `town`, `boss-room`, `not-monster`,
  `boss-kill`, `unnamed` (an act without a boss; no shipped act), `no-rate`,
  then `hit` (forced, or the roll below `1/D`) or `miss`. `soulpiece force on`
  replaces only the last three with `hit`.
- **The piece** is the game's own Edible PAS Logo: class 11, `b` the
  category-11 entry named `consumable_edible_pas_logo` (resolved by name at run
  time), `c` 0, `j` 0, with its seed `a` set to 777100 + act. 777001 to 777003
  are other ForgePact items' seeds. Class 11 never stacks in the bag, so each
  piece takes its own cell; with ForgePact gone a piece is an Edible PAS Logo,
  so a save holding pieces loads.
- **The use.** A detour on `PotionUse`: for an item that is a piece, the
  original is never called. Verdicts, in order: `off`, `not-piece`, `no-act`
  (the player's room has no act), `boss-room` (the drop's name rule),
  `unnamed`, then `portal`. Towns are allowed. On `portal` a `Portal_obj` is
  made 96 px to the player's right (to the left past the room's width), its
  `portalZone` record is set to the act's boss room (`Act_0N_Boss`, by SDK room
  name) and read back, and `PotionUse` answers true, so the game clears the
  piece's cell itself. Every other verdict, or a portal that did not open,
  answers false and the piece stays. The game's own travel and the room's
  pentagram do the rest; nothing of ours creates, moves or kills a boss.

The test file expresses this as input transforms (`piece_denominator`,
`piece_chance`, `room_refusal`, `decide_drop`, `decide_use`, `portal_target`,
`portal_x`, the seed helpers), and `ParityTests` pins the constants, the base,
the act table with its boss rooms, the portal offset, the room rules and the
verdict words to the header, so a change on either side fails there.

## The model

A pure function of whole numbers, booleans and exact fractions
([`soul_piece_model.py`](../../hs-game-sdk/python/hs_game_sdk/soul_piece_model.py)):

- `act_of_room(room_act_index)`: the act, `RoomActIndex`'s answer itself, 1 to
  9; `None` when the answer is undefined. Any other answer is refused.
- `stacks(held, picked)`: whether the game merges a picked-up `Item` (class,
  `b`, `c`, seed) into a held one: both of class 12 to 15, the same class, the
  same `b` and `c`; the seed is not an input to the answer.
- `gem_chance(gem_rate)`: the gem's chance on one `DropGems` call, `1/G` under
  `gem_one_in_its_rate`; `None` for a rate that is unknown, zero or negative.
- `expected_drops(rolls, chance)`: `rolls × chance`, linear in the rolls, 0 for
  an unknown chance.
- `item_used_up(potion_use_answer)`: a confirmed backpack use leaves the item
  gone only when `PotionUse` answered true.
- `HYPOTHESES`: the questions above, `None` until measured.

With the transforms of "Our code", the test checks the baseline and the target.
Baseline: the measured merge of a key-base piece into the real key (the seed
cannot keep it apart), the act as `RoomActIndex`'s answer, and no piece and no
portal with the mod off. Target: a consumable piece never stacks with a real
logo or another piece; for `G` in 9,000, 10,000 and 11,000 the piece's chance
over the gem's is exactly 5/4 (every multiple of 5), and otherwise above 5/4 by
less than `5/(4D)`; over `N` gem rolls the expected pieces are `N/D`, so more
rolls (more monsters from density, a higher gem chance) give proportionally more
pieces; an unknown rate, a boss, a town, a boss room or a source that is not a
monster gives no piece; and a use opens a portal to its act's boss room in
towns and zones, never from a boss room or a room with no act.

## What the model cannot catch

- **Whether `DropGems` gives the gem exactly 1 in its rate** (it may pick by
  weight), so whether the piece's 5/4 to the gem holds in play. A gem is too
  rare to count in one session.
- **Magic find** and any per-place override of the gem's rate: the piece takes
  `G` from `droprate.base`, so where the game uses another value the ratio
  differs.
- **Whether the detours attach**, whether `RoomActIndex` answers by name at run
  time, whether a piece's right-click reaches `PotionUse`, whether the portal
  shows, can be entered and leads to its room through `NetworkRoomGoto`, and
  whether the room's boss arrives and dies cleanly: those are Live procedure
  3's and Live procedure 2's checks.
- **What the Edible PAS Logo's own effect is**, and so what using a piece does
  with ForgePact removed, and how the drop rate feels over a season of play.
