# Where a boss soul piece drops, how often, and what using one does: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/soul_piece_model.py`](../../hs-game-sdk/python/hs_game_sdk/soul_piece_model.py)
(`soul_piece_model`), tested by
[`tests/test_soul_piece_model.py`](../../tests/test_soul_piece_model.py)
against [`hs-game-sdk/curated/boss_soul_pieces.json`](../../hs-game-sdk/curated/boss_soul_pieces.json)
and [`hs-game-sdk/curated/room_acts.json`](../../hs-game-sdk/curated/room_acts.json).
It was written for ForgePact#197, whose **Boss soul pieces** switch lets an
ordinary monster in a zone of an act drop a Piece of that act's boss's Soul.
Right-clicking a piece in the backpack and confirming moves the player straight
into that act's boss room through the game's own `NetworkRoomGoto`, after
dropping the room's saved zone state with `ZoneStateResetSingle` so the boss
comes out again; no portal is opened. The spec answers three questions: what
the game decides (which act a room belongs to, which items stack, when the game
rolls a gem, and when a backpack use leaves the item gone), and exactly what the
mod adds on top (which rooms and sources count, the piece's chance on the gem's
roll, and which room its use takes the player to).

The follow-up (2026-10-12, the owner: the Gem of Incarnation's icon on pieces,
pieces stacking per act, pieces in the Key tab and never merged into a real
key) adds the game's number rules a key piece rests on: how a stack compares
two reals, how the repository lookup and the save treat a `b` with a fraction,
and who else compares `b`. Its research session is Live procedure 1 of the
follow-up, capture `forgepact-197-piece-icon-stack-live-1`, not yet run; until
it is, everything this spec says about a key piece is a static reading or our
code.

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
bosses, key items and stacking, the backpack's use path, portals and travel,
zone state) and § 18.4 (how a gem drops).

## Static reading

Read on 2026-10-11 through the `ghidra` MCP on build `498d588550d8`, plus local
byte scans of the game's executable and `data.win` whose positive controls were
`PickupLoot`'s known callers and a known object event row. The follow-up's
readings (the stack route, the compare, the repository lookup, the save and
who else compares `b`) were made on 2026-10-12, on the same build, through the
`ghidra` MCP and a local call-site scan with a positive control; they are also
in `RUNTIME_DATA_MODELS.md` § 21.3.

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
- **Pickup and stacking** (corrected by the follow-up's reading, 2026-10-12;
  the first reading had the two stack scripts the other way round).
  `PickupLoot`'s general path ends in `AddToInventory`, which tries a stack
  before placing an item as a new one. Offline it asks
  `GetItemPreferredGrid`, which answers a grid of the item's own kind for keys,
  materials, socketables, tarot cards and the vault class (the Key tab's
  `inventoryKeyGrid` and its siblings, chosen by class) and none for a
  consumable. With a preferred grid it tries `GridAddToStack` on that grid
  first, and `InventoryGridAddToStack` only when that takes nothing; with
  none, `InventoryGridAddToStack` alone. A byte scan for direct call sites
  (positive control: the known `InvGridClearItemNode` call in
  `UiAInventoryConsumeItemConfirm`) found one `GridAddToStack` site and two
  `InventoryGridAddToStack` sites in `AddToInventory`. This fits both of Live
  procedure 3's measurements: a consumable's pickup reached
  `InventoryGridAddToStack`, and the key merge reached `AddToInventory` alone,
  because `GridAddToStack`, not watched then, took it.
- **What a stack compares.** The stack scripts merge the item into one whose
  class matches and whose definition's `b` and `c` match, comparing those
  fields themselves; neither calls `ItemsAreStackable`, and the seed `a` is
  never compared. `GridAddToStack` first accepts only classes 12, 13, 14 and
  15, as `IsItemTypeStackable` answers. It compares `itemType`, then the two
  definitions' `b`, then their `c`, each through the runtime's general value
  compare, which takes two reals as equal when they differ by no more than the
  math epsilon (GameMaker's default is 0.00001). So a `b` of 2.1 differs from
  2 and matches another 2.1, and a double's own rounding error is far inside
  the epsilon. `c` is the repository flag (0 normal, 1 unique), so a whole
  change of it loads a different item.
- **The bag's stack attempt refuses a consumable first** (read 2026-10-12,
  after Live procedure 1, through the `ghidra` MCP and local annotated
  decompiles on the same build; also in `RUNTIME_DATA_MODELS.md` § 21.3).
  1. *The class rule.* `IsItemTypeStackable` answers true for classes 12, 13,
     14 and 15 and for nothing else. `IsStackable` first asks the item's
     `GetItemInfo` method for one value (which info key was not resolved) and
     answers false when that value is truthy; otherwise it applies the same
     four-class rule. So the flag can only refuse an item the class rule
     would take.
  2. *`InventoryGridAddToStack` asks the rule before anything else.* The item
     being picked up is its second argument. It applies the `IsStackable` rule
     to that item itself, at the start, and when the rule fails it gives up
     there, before it reads a grid or compares any field. A class-11 piece is
     therefore refused whatever its `b`, `c`, seed or count, which fits Live
     procedure 3's measured `class_11_never_stacks` (below). For a class
     that passes, it picks its grid by class (15 the socket grid, 12 the Key
     grid, 13 and 14 the material grid); a later walk reads the bag's
     `inventoryTab` under a condition that was not read.
  3. *The cap.* A merge goes ahead only while the two counts summed stay at
     most 999.
  4. *The result.* Every path, the early refusal included, ends by building
     the game's `s_ItemOperation` struct (`gml_Script_s_ItemOperation`) and
     returning it, and `AddToInventory` reads that result's `success` at each
     of its stack attempts. A successful result's fields were measured on the
     prospecting grid (`RUNTIME_DATA_MODELS.md` § 9.7: `tabNumber`, `x`, `y`,
     `tabType`, `success`); whether `AddToInventory` reads any field but
     `success` was not read.

  So no consumable class or base stacks through the game's own stack code,
  and no value in a piece's own definition can change that: each class that
  does stack goes to its own tab (Key, material or socket), not the bag.
- **The repository lookup truncates.** `GetNormalRepoStruct` turns its index
  argument into an integer through the runtime's real-to-int conversion,
  which truncates toward zero: a `b` of 2.1, or 2.9, looks up entry 2. The item
  constructor takes `GetUniqueRepoStruct` when the definition's `c` is truthy,
  which for a real means above 0.5, and `GetNormalRepoStruct` otherwise.
- **The save writes reals as text.** `CreateItemSaveStruct` copies the item's
  definition and `json_ordered_by_key` writes it, sending every real and
  int64 through the `string` builtin. That GameMaker's `string()` of a real
  keeps two decimals and writes a whole number whole is the runtime's
  documented behaviour, not read in this game
  (`string_keeps_two_decimals`). So a `b` carrying tenths would survive a save,
  and a finer fraction would not.
- **Who else compares `b`.** `CountInventoryItem` (its direct callers are only
  the crafting scripts `GetCraftItemsAvailable` and `CraftFindRecipeItems`)
  compares the class, an item-info value and the definition's `b`, not `c`.
  `FindInventoryItem` (called from `PlayerMouseAction` and two unnamed sites)
  compares `b` and `c`. Both use the same epsilon compare.
- **The display sprite.** Item info key `"11"` is the sprite an item is drawn
  with: ForgePact #158's Live 1 (2026-10-12, on its own branch) **measured** a
  charm given another charm's sprite there drawn with it in the bag and on the
  ground, a sprite added at run time drawn in the bag and as the game's error
  sprite on the ground (the ground item looks up `Pickup_` followed by the
  sprite's name, #158's static reading), no icon in the tooltip, and the value
  not saved. `hs-game-sdk`'s sprite table holds both `Gem_Incarnation_spr` and
  `Pickup_Gem_Incarnation_spr`, so the gem's sprite has a ground companion
  (static reading of the SDK's tables). That a built Gem of Incarnation carries
  `Gem_Incarnation_spr` under `"11"` is unverified.
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
- **Zone state** (Amendment 2, 2026-10-11). A room's contents outlive the
  player's leaving it in the game's global `zoneStates` map, keyed by room,
  which `ZoneStateSaveController` fills as the player leaves; no exclusion it
  applies names an act boss room. `ZoneStateResetSingle(room)` deletes that
  room's entry, writing no quest, act or save-file value, and
  `ZoneStateExists(room)` answers whether the room has a visited entry. The
  pentagram sets its `bossSpawned` afresh on every creation and reads no
  boss-killed flag in its own events; whether the boss object or the room's
  creation code reads one was not read, nor what a revisit restores for a boss
  room (`RUNTIME_DATA_MODELS.md` § 21.6). That the boss comes out again once
  the entry is dropped is measured (below), not read.
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

By Live procedure 3 (`forgepact-197-boss-soul-pieces-live-3`, 2026-10-11, a
research build with the x64dbg debugger attached), in our words
(`RUNTIME_DATA_MODELS.md` § 21.5, § 21.6):

- **A portal does not reach the boss room; the game's travel does.** A
  `Portal_obj` created at run time with a boss room written into its
  `portalZone` record took the player, through its alarm and `NetworkRoomGoto`,
  to `Act_01_Pregame` both times (both opened in `Town_01_rm`, one for
  `Act_01_Boss` and one for `Act_02_Boss`; one opened in `Act_01_01` read back
  `Act_01_02` and was not entered; why the record lost the boss room is not
  established). `NetworkRoomGoto` called directly with `Act_01_Boss` or
  `Act_02_Boss`, the player as `self`, reached that room, whose pentagram
  brought out Gurag or the Reaper, who died there without a crash (the Reaper
  included, Live procedure 1's crash case). The owner chose the direct transfer
  (2026-10-11), so the shipped use opens no portal.
- **The base and the bag.** Category 11's entry named
  `consumable_edible_pas_logo` is index 12. Five class-11 items on it (three
  seeded 777101, one 777102, one plain) picked up into five bag items with
  count 1 each (`class_11_never_stacks`), each pickup reaching `AddToInventory`
  and then `InventoryGridAddToStack`, never `GridAddToStack`, under the
  debugger. A save holding a piece loaded after a relaunch with ForgePact's
  dress off, the piece reading as an Edible PAS Logo with its seed kept.
- **A piece's use.** Its right-click and confirm reached `CanUsePotion` and
  `PotionUse` carrying the piece, and a true `PotionUse` answer that did not
  run the logo's own use made the game clear its cell; the logo's own effect
  (a portal to Sheeponia) did not show.
- **`RoomActIndex` outside its switch** answered the boolean `false`, not
  undefined, in `Act_01_Boss` and `Act_01_Pregame`
  (`room_outside_the_switch_is_undefined`: the room has no act either way, but
  the answer is not undefined); 2 in `Town_02_rm` and `Act_02_Boss`.

By Live procedure 2 (`forgepact-197-boss-soul-pieces-live-2`, attempt 2, its
second check block, 2026-10-12, the player build) and Live procedure 4
(`forgepact-197-boss-soul-pieces-live-4`, 2026-10-12, the same build with the
debugger), in our words (`RUNTIME_DATA_MODELS.md` § 21.5, § 21.6):

- **Our drop, forced, gives named pieces in Acts 1 and 2**: with `force on`
  every eligible gem roll dropped a piece (`drops=` 0 to 42 in `Act_01_01`, 42
  to 49 in `Act_02_01`), each a Piece of Gurag's or of the Grim Reaper's Soul;
  with the switch off, kills dropped none. The unforced rate is our code's
  arithmetic on the measured `G`, not measured (a gem is too rare).
- **`RoomActIndex` answered 2 in `Act_02_02`** (Live procedure 2 attempt 2,
  through the status line's `act=2`), the act `room_acts.json` gives it.
- **Our transfer moves the player into the boss room**: a confirmed piece in
  `Act_01_01`, `Town_01_rm` or `Town_02_rm` put the player in `Act_01_Boss` or
  `Act_02_Boss` within seconds, with no portal, and used one piece; with the
  switch off the use was refused and the piece kept.
- **The zone-state reset brings the boss back.** `ZoneStateExists` answered
  true for an ordinary zone and a town just left, false for a boss room on its
  first entry of a launch, and true for `Act_01_Boss` after Gurag was killed
  there and the room left. The next piece's transfer asked `ZoneStateExists`
  (true), called `ZoneStateResetSingle`, asked again (false), and Gurag came
  out of the pentagram again. The debugger saw the transfer reach both scripts
  (Live procedure 4), and the game's own travel call `ZoneStateExists` but not
  `ZoneStateResetSingle`.

## Not established

Each of these is an open question. Where it decides a number or a rule the
model uses, it is carried in the model's `HYPOTHESES`, `None` until the curated
file's matching `open_questions` entry is `measured`; the measured ones above
(`gem_roll_self_is_the_source`, `potion_use_true_clears_the_item`) are `True`.
`class_11_never_stacks` and `room_outside_the_switch_is_undefined` are also
measured above (Live procedure 3, capture
`forgepact-197-boss-soul-pieces-live-3`: true, and false, since the answer
outside the switch is `false`, not undefined); their curated entries read
`measured` with that capture and answer, and the model carries them as `True`
and `False`, its `act_of_room` reading a `false` answer as no act.

- **`gem_one_in_its_rate`**: whether `DropGems` gives each socketable exactly 1
  in its `GetDropRate` answer, or picks one by weight among them. The model
  assumes 1 in the rate. Not measured live: a gem is too rare for one session.
- **The boss room's state**: what a revisit restores for a boss room without
  the reset (that the boss stays away after a kill is the owner's account; no
  session re-entered that way), whether `zoneStates` survives a relaunch, and
  what else the dropped entry held (loot on the floor, the portal a kill
  leaves).
- **The use**: whether `CanUsePotion` refuses the logo in some room other than
  the towns and `Act_01_01` where it was seen to accept, and whether a kill
  reached through a piece counts toward the act's quest or completion again
  (no quest or act message showed in any session).
- **Magic find.** No magic-find stat name appears in `DropGems`' or
  `GetDropRate`'s body. That is "not observed", not a negative.
- **Per-place overrides on the gem.** Whether the Gem of Incarnation carries a
  per-place field (rifts, ubers, boss dungeons) was not read; where it does, the
  game's chance there differs from `droprate.base`.

The follow-up's open questions (its Live procedure 1, capture
`forgepact-197-piece-icon-stack-live-1`, answers the first four):

- **`string_keeps_two_decimals`**: the exact rounding of the save's `string()`.
  The model assumes two decimals, a whole number written whole, and a tie
  rounded away from zero; `reload-frac-kept` and `tools/save_item_keys.py
  --defs` measure what a key piece's `b` reads after a reload.
- **The Key tab's right-click**: whether right-clicking a key in the Key tab
  reaches `CanUsePotion` and the use prompt at all (`keyuse-prompt`). The bag's
  right-click sits in `ProcessInventoryGridInput`; whether the Key tab's grid
  takes the same path, and whether `CanUsePotion` answers true for a key, were
  not read.
- **The confirm on a stack**: whether the confirm, after `PotionUse` answers
  true, takes one item from a stack of N or clears all N (`stackuse-all`). Every
  use measured so far was of a single item.
- **The icon on the ground**: whether a key piece dressed with
  `Gem_Incarnation_spr` lies on the ground as `Pickup_Gem_Incarnation_spr`
  (`icon-ground`), and whether a built gem carries that sprite (`gem-sprite`).
- **The epsilon's value**: GameMaker's default math epsilon is 0.00001; whether
  the game sets another was not read. Anything up to 0.05 keeps the 0.1 between
  two acts apart.
- **`InventoryGridAddToStack`'s compare**: how it compares `b` for a class that
  passes its class rule (it is the fallback `AddToInventory` tries when
  `GridAddToStack` takes nothing) was not read. Why it refuses a class-11 item
  is now read (above: the class rule comes first).
- **Door and NPC key checks**: which code a door or an NPC uses to find the key
  it wants (Heimdall's Bifröst Key and the rest) was not read, so whether one
  of them would take a key piece for its key is not established.
- **The tooltip**: whether it draws any icon for a key; #158 saw none for a
  charm. The tooltip names the piece either way (`icon-tooltip`).

The bag stack's open questions (the owner kept pieces in the bag after Live
procedure 1; the follow-up's Live procedure 2, capture
`forgepact-197-piece-icon-stack-live-2`, answers them):

- **A merged pickup**: whether `AddToInventory`, handed a result whose
  `success` ForgePact's merge branch set, finishes the pickup as for a stack
  the game made itself, with the piece gone from the ground and no second copy
  in the bag (`merge-no-duplicate`).
- **The bag's count**: whether the bag draws the count of a class-11 item whose
  `o` is above 1 on its cell (`stack-draw`). No consumable has stacked before.
- **The confirm on a bag stack**: whether `UiAInventoryConsumeItemConfirm`,
  after `PotionUse` answers true for a bag item whose `o` is above 1, takes one
  from it or clears the whole cell (`stackuse-all`).
- **`saved_count_is_kept`**: whether a class-11 item's count `o` comes back
  from a save and a relaunch as written (`reload-stack-kept`, read with
  `tools/save_item_keys.py --defs`). The model assumes it, since the save
  writes a whole number whole.
- **The bag file during play**: whether the bag's save file is rewritten over
  a session holding a piece stack (`save-written`); Live procedure 1's was not
  rewritten at its stop, for a reason not established.

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
  five quarters of the gem's chance on the same roll only if `DropGems` gives
  the gem exactly 1 in `G` (`gem_one_in_its_rate`, pending; the owner,
  2026-10-11: "a little more common than gem of incarnation"). With the measured `G` =
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
- **The key piece** (the follow-up, 2026-10-12; the mod's lever). A piece is
  built on a key: class 12, `b` = the key base's index + act/10, `c` 0, its
  seed `a` 777100 + act. The key base is the category-12 entry named
  `keys_bifrost_key` (resolved by name at run time; #197's Live procedure 3
  read index 2, so `b` runs from 2.1 for Act 1 to 2.9 for Act 9), our default
  until the owner names another key. Nothing of ours touches the pickup or the
  stack: the game's own compare (above) stacks pieces of one act, keeps other
  acts (0.1 apart) and the real key (a whole `b`) apart, and the repository
  lookup's truncation loads a piece as the key base, with or without
  ForgePact. Crafting's count and the inventory find compare `b`, so neither
  takes a piece for the key. ForgePact recognises a key piece by what it is:
  the key base's class, `c` 0, a `b` that truncates to the base's index, is not
  whole, and sits at its seed's act's tenth, each within 0.01, wide enough for
  what a two-decimal save returns. The candidate marked by `c` alone (`c` =
  act/20, 0.05 to 0.45, still the normal repository) is research only:
  crafting's count ignores `c`, so it would count such a piece as the key.
- **The icon.** ForgePact's dress writes `Gem_Incarnation_spr`, resolved by
  name, under item info key `"11"` on every piece, so the Key tab draws the gem
  and the ground item looks up `Pickup_Gem_Incarnation_spr`. It is not saved:
  without ForgePact a piece shows its base's icon.
- **The legacy bag piece**: the first builds made a piece of the game's own
  Edible PAS Logo, class 11, `b` the category-11 entry named
  `consumable_edible_pas_logo` (resolved by name at run time), `c` 0, `j` 0,
  with its seed `a` set to 777100 + act. Pieces already in a bag stay so and
  are still recognised. 777001 to 777003 are other ForgePact items' seeds.
  Class 11 never stacks through the game's own code, so each such piece takes
  its own cell unless the merge below joins it; with ForgePact gone it is an
  Edible PAS Logo, so a save holding one loads.
- **The bag merge** (the owner, after Live procedure 1: pieces stay bag
  consumables and pieces of one act stack in the bag; the mod's lever, outside
  the model). One detour on `InventoryGridAddToStack`, installed on both
  routes, always runs the game's own call first with the call's own arguments
  and keeps its result. Only when the merge is armed, that result's `success`
  is not true, the incoming item is a legacy bag piece (the class-11 rule above)
  and `DecideMerge` names the first bag piece of the same act whose count plus
  the incoming count stays within the game's cap of 999 (`kBagStackCap`), does
  it change anything: that piece's `o` rises by the incoming count, its hash is
  refreshed as the dress refreshes it, and the game's own result gets `success`
  true with the target's tab and cell. A real item is never a target and never
  merged, and a key-shape piece is not a bag piece. Any other call, a failed
  read included, returns the game's result untouched. Its verdicts, in order:
  `off`, `not-piece`, `no-target`, `cap`, `merge`. The model leaves this out:
  `stacks` stays the game's rule, under which a class-11 piece never merges.
- **The use.** A detour on `PotionUse`: for an item that is a piece, the
  original is never called. Verdicts, in order: `off`, `not-piece`, `no-act`
  (the player's room has no act), `boss-room` (the drop's name rule: a `_Boss`,
  `Uber_` or `Dev_` room), `unnamed`, then `transfer`. Towns are allowed. On
  `transfer` the detour checks that there is a player and that the act's boss
  room (`Act_0N_Boss`, by SDK room name through `asset_get_index`) resolves,
  records the transfer and answers `PotionUse` true, so the game clears the
  piece's cell itself. On the next frame tick it asks
  `ZoneStateExists(Act_0N_Boss)` (counted `fresh` when true), calls
  `ZoneStateResetSingle(Act_0N_Boss)` whatever it answered, dropping the
  room's saved zone state so the boss comes out again, asks `ZoneStateExists`
  again (counted `cleared` when the first was true and this is false), then
  calls `NetworkRoomGoto(Act_0N_Boss)` with the player as `self`, all by SDK
  script constant (measured: Live procedure 2's `on-reentry-reset` and
  `on-reentry-boss`, Live procedure 4's debugger hits). Every other verdict answers false and
  the piece stays. No portal is opened. The room's pentagram does the rest;
  nothing of ours creates, moves or kills a boss.

How a use takes one piece from a Key-tab stack, and whether the Key tab's
right-click reaches the use at all, wait on the follow-up's Live procedure 1.

The test file expresses this as input transforms (`piece_denominator`,
`piece_chance`, `room_refusal`, `decide_drop`, `decide_use`, `transfer_target`,
the seed helpers, `key_piece_b`, `key_piece_item` and `key_piece_act`), and
`ParityTests` pins the constants, the base, the key base, the icon, the act
table with its boss rooms, the room rules, the verdict words and the stack cap
(`kBagStackCap` against the curated `bag_stack` and the model's
`BAG_STACK_CAP`) to the header, so a change on either side fails there.

## The model

A pure function of whole numbers, booleans and exact fractions
([`soul_piece_model.py`](../../hs-game-sdk/python/hs_game_sdk/soul_piece_model.py)):

- `act_of_room(room_act_index)`: the act, `RoomActIndex`'s answer itself, 1 to
  9; `None` when the answer is `false` (measured outside the switch) or
  undefined. Any other answer is refused.
- `same_value(x, y)`: the runtime's value compare on two numbers, equal
  within `EPSILON` (1/100000).
- `stacks(held, picked)`: whether the game merges a picked-up `Item` (class,
  `b`, `c`, seed, count `o`; `b` and `c` whole or real) into a held one. A
  picked class outside 12 to 15 is refused before any other field is read;
  then the same class, `b` and `c` the same value by `same_value`, and the two
  counts summed at most `BAG_STACK_CAP` (999). The seed is not an input to the
  answer, and the item-info flag `IsStackable` also asks is left out (it can
  only refuse).
- `repository_index(b)`: the entry a definition loads, `b` truncated toward
  zero. `uses_unique_repository(c)`: `c` above 0.5.
- `saved_number(value)`: a definition's number after a save and reload, under
  `string_keeps_two_decimals`: whole stays whole, a real is rounded to two
  decimals. A count is whole, so a stack's `o` comes back as it was
  (`saved_count_is_kept`).
- `counted_by_crafting(item, item_type, b)`: crafting's count, class and `b`
  (the item-info value it also compares is left out, which can only count
  more). `find_matches(item, b, c)`: the inventory find, `b` and `c`.
- `gem_chance(gem_rate)`: the gem's chance on one `DropGems` call, `1/G` under
  `gem_one_in_its_rate`; `None` for a rate that is unknown, zero or negative.
- `expected_drops(rolls, chance)`: `rolls × chance`, linear in the rolls, 0 for
  an unknown chance.
- `item_used_up(potion_use_answer)`: a confirmed backpack use leaves the item
  gone only when `PotionUse` answered true.
- `HYPOTHESES`: the questions above, `None` until measured, then the measured
  answer.

With the transforms of "Our code", the test checks the baseline and the target.
Baseline: the measured merge of a key-base piece into the real key (the seed
cannot keep it apart), the act as `RoomActIndex`'s answer, and no piece and no
transfer with the mod off. Target: a consumable piece never stacks with a real
logo or another piece; for `G` in 9,000, 10,000 and 11,000 the piece's chance
over the gem's is exactly 5/4 (every multiple of 5), and otherwise above 5/4 by
less than `5/(4D)`; over `N` gem rolls the expected pieces are `N/D`, so more
rolls (more monsters from density, a higher gem chance) give proportionally more
pieces; an unknown rate, a boss, a town, a boss room or a source that is not a
monster gives no piece; and a use moves the player to its act's boss room in
towns and zones, never from a boss room or a room with no act.

For the key piece, the baseline adds the game's number rules on their own: the
compare within the epsilon, the repository index truncating `b`, a truthy `c`
(above 0.5) picking the unique repository, and the save keeping two decimals
(a finer step comes back whole). The target: a key piece stays apart from the
real key (a whole-`b` piece, the positive control, merges), pieces of one act
stack and other acts stay apart, a saved piece still stacks with a fresh one
and stays apart from the real key, crafting's count and the inventory find
never take a piece for the key, and a piece loads as the key base before and
after a save.

For the bag stack, the baseline is the game's rule on its own: only classes 12
to 15 stack, an incoming class-11 item is refused before any other field is
read (an unreadable field on it is never reached, while the same field on a
class that passes is), and a stack holds at most 999 (998 + 1 merges, 999 + 1
does not). The target: a consumable piece never stacks by the game's rule,
whatever its count, so every bag stack is the merge's doing; and a saved piece
stack comes back with its count, still its act's piece.

## What the model cannot catch

- **Whether `DropGems` gives the gem exactly 1 in its rate** (it may pick by
  weight), so whether the piece's 5/4 to the gem holds in play. A gem is too
  rare to count in one session.
- **Magic find** and any per-place override of the gem's rate: the piece takes
  `G` from `droprate.base`, so where the game uses another value the ratio
  differs.
- **Whether the detours attach**, whether `RoomActIndex` answers by name at run
  time, whether a piece's right-click reaches `PotionUse`, whether the
  transfer reaches the boss room from a confirmed use, and whether the room's
  boss arrives and dies cleanly: Gurag twice, the second time after he was
  killed and his room's zone state dropped, and the Grim Reaper. Live
  procedure 2 measured those on the player build (`on-transfer`, `on-boss`,
  `on-boss-dies`, `on-reentry-reset`, `on-reentry-boss`, `on-use-town`,
  `on-boss-2`, all passed, 2026-10-12), for acts 1 and 2 only; the model says
  nothing about acts 3 to 9's rooms.
- **What the Edible PAS Logo's own effect is** (Live procedure 3 saw it open a
  portal to Sheeponia), and so what using a legacy piece does with ForgePact
  removed, and how the drop rate feels over a season of play.
- **Anything about the key piece the numbers do not decide**: whether the save
  really keeps two decimals, whether `InventoryGridAddToStack` compares like
  `GridAddToStack`, which icon the Key tab, the ground and the tooltip draw,
  whether the Key tab's right-click reaches the use, what the confirm does to a
  stack, and whether a door or an NPC takes a piece for its key. The follow-up's
  Live procedure 1 measures the first five; the last is not read.
