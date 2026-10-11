# Where a boss soul piece drops, and how often: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/soul_piece_model.py`](../../hs-game-sdk/python/hs_game_sdk/soul_piece_model.py)
(`soul_piece_model`), tested by
[`tests/test_soul_piece_model.py`](../../tests/test_soul_piece_model.py)
against [`hs-game-sdk/curated/boss_soul_pieces.json`](../../hs-game-sdk/curated/boss_soul_pieces.json)
and [`hs-game-sdk/curated/room_acts.json`](../../hs-game-sdk/curated/room_acts.json).
It was written for ForgePact#197, whose **Boss soul pieces** switch lets an
ordinary monster in a zone of an act drop a Piece of that act's boss's Soul,
which summons the boss when the player right-clicks it in the backpack. It
answers two questions: what the game decides (which act a room belongs to, which
boss stands for an act, and when the game rolls a gem), and exactly what the mod
adds on top (which rooms and sources count, and the piece's chance on the gem's
roll).

Every claim carries one of four labels, and a source:

- **Static reading**: read from the compiled game or from `hs-game-sdk`'s
  extracted tables, and written here in our own words. No script text is quoted
  or transcribed (`AGENTS.md` § "Legal").
- **Measured**: observed in a running game.
- **Our code**: what ForgePact does. The model leaves it out, and the test
  expresses it as an input transform.
- **Not established**: carried by the model as an open hypothesis, or left out.

The game facts behind this spec are in
[`docs/RUNTIME_DATA_MODELS.md`](../RUNTIME_DATA_MODELS.md) § 21 (acts, act
bosses, key items, the backpack's use path) and § 18.4 (how a gem drops).

## Static reading

Read on 2026-10-11 through the `ghidra` MCP on build `498d588550d8`, plus local
byte scans of the game's executable and `data.win` whose positive controls were
`PickupLoot`'s known callers and a known object event row.

- **The act of a room.** `RoomActIndex(room)` (`gml_Script_RoomActIndex`) is a
  switch over 175 room constants into nine cases; the case number is the act
  minus one. Its answer starts undefined and only a matching case sets it, so a
  room outside the 175 has no act. Two direct callers (byte scan) pick an act's
  texture pages from the answer, so the game itself relies on it. The table,
  room by room with its SDK index, is `room_acts.json`; rows per act, 1 to 9:
  21, 24, 16, 15, 14, 20, 17, 19 and 29. A room's name does not always give its
  act (`Act_08_Orres_Lair_rm` is act 4). `Act_01_Boss`, `Act_03_Boss`,
  `Act_04_Boss`, `Act_05_Boss` and `Act_07_Boss` are not in the switch;
  `Act_02_Boss`, `Act_06_Boss`, `Act_08_Boss` and `Act_09_Boss` are.
- **The act bosses.** No act boss room places a descendant of
  `Enemy_Child_Boss_obj` in its room list; each places a `Pentagram_Boss_obj`,
  and the boss arrives at run time from a source not established. Which boss
  belongs to which act is read from each boss room's decor: `Gurag_obj` (act 1),
  `Reaper_obj` (2), `Anubis_obj` (3), `Satan_obj` (6), `Odin_Phase_1_obj` (8)
  and `Cthulhu_obj` (9). Acts 4 (`Damien_obj`) and 5 (`Karp_King_obj`) are an
  inference: their decor names no boss, and those two are what remains of the
  Key of Terror's six bosses. Act 7's boss, `Mevius_obj`, is the owner's
  decision (2026-10-11), not a reading. All nine descend from
  `Enemy_Child_Boss_obj` through `Enemy_Parent_obj` in `hs-game-sdk`'s parent
  table (`boss_soul_pieces.json` `acts`).
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
  `socketable_gem_of_incarnation`, class 15, `b` 136.
- **Stacking.** `ItemsAreStackable` compares the two items' `itemType` and
  their definitions' `b` and `c`; it never compares the seed `a`. So two items
  of one key definition stack whatever their seeds, as far as this predicate
  goes.

## Measured

- **The gem's info rate.** Every Gem of Incarnation in the local drop records
  carried info key `"31"` = 10,000 (`docs/RUNTIME_DATA_MODELS.md` § 18.4), and
  the measured gem bases are 9,000 and 11,000 (§ 13.2). So 10,000 is the
  plausible `droprate.base`; it is **not** a reading of `droprate.base` itself
  (`gem_rate_is_10000` below).
- **A boss spawned in a zone** by name lives, fights and dies there with its
  drops, and one spawned in town removes itself (§ 13.1; Karp King and four
  uber bosses in `Act_01_01`). Whether the nine act bosses do the same outside
  their pentagram is ForgePact#197's Live procedure 1 question.
- Nothing about the soul piece itself is measured yet. ForgePact#197's Live
  procedures 1 and 2 fill `boss_soul_pieces.json`'s `open_questions` and turn
  acts 1 and 2's status to `measured`.

## Not established

Each of these is an open question, carried in the model's `HYPOTHESES` where it
decides a number. Each stays `None` until the curated file's matching
`open_questions` entry is `measured`.

- **`gem_one_in_its_rate`**: whether `DropGems` gives each socketable exactly 1
  in its `GetDropRate` answer, or picks one by weight among them. The model
  assumes 1 in the rate. Not measured live: a gem is too rare for one session.
- **`gem_rate_is_10000`**: whether the Gem of Incarnation's `droprate.base` is
  the 10,000 its info key shows (Live procedure 1's `gem-rate`).
- **`gem_roll_self_is_the_source`**: whether `DropGems`' `self` is the dying
  instance, as scripts called from its Destroy event inherit it (Live procedure
  1's `gems-self`). Chests, destructibles and goblin piles reach `DropItem` too.
- **Magic find.** No magic-find stat name appears in `DropGems`' or
  `GetDropRate`'s body. That is "not observed", not a negative.
- **Per-place overrides on the gem.** Whether the Gem of Incarnation carries a
  per-place field (rifts, ubers, boss dungeons) was not read; where it does, the
  game's chance there differs from `droprate.base`.
- **Where an act boss comes from** in its own room, and whether a summoned boss
  counts toward its act's quest or completion.

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
  "a little more common than gem of incarnation"). With `G` = 10,000, `D` =
  8,000. `G` unknown, zero or negative gives `D` = 0 and no piece (`no-rate`),
  unless forced.
- **Which rooms.** A room whose `RoomActIndex` answer gives an act, except a
  town (name starting `Town_`, verdict `town`) and a boss room (name containing
  `_Boss`, or starting `Uber_` or `Dev_`, verdict `boss-room`). A room outside
  the act table gives `no-act`. That includes rifts, side dungeons and the act's
  key dungeons (Pumpkin Cellar in act 1).
- **Which sources.** A source that does not descend from `Enemy_Parent_obj`
  gives `not-monster`; one that descends from `Enemy_Child_Boss_obj` gives
  `boss-kill`.
- **Verdict order**: `off`, `no-act`, `town`, `boss-room`, `not-monster`,
  `boss-kill`, `unnamed` (an act without a boss; no shipped act), `no-rate`,
  then `hit` (forced, or the roll below `1/D`) or `miss`. `soulpiece force on`
  replaces only the last three with `hit`.
- **The piece** is one of the game's own key definitions (class 12, a base key
  found by repository name, `c` 0, `j` 0) whose seed `a` is 777100 + act, so a
  save holding pieces loads without ForgePact. 777001 to 777003 are other
  ForgePact items' seeds.
- **The use.** A right-click on a piece in the backpack, in any room but a town:
  `off`, `town`, `not-piece`, `unnamed`, `summon`. `summon` creates that act's
  boss 600 px to the player's side.
- **The stack veto** (only on the one-base item route): consulted after the game
  answered that two items stack, it turns that answer into "no" while the mod is
  on when exactly one item is a piece, or the two pieces' acts differ.

The test file expresses this as input transforms (`piece_denominator`,
`piece_chance`, `room_refusal`, `decide_drop`, `decide_use`, `veto_stack`, the
seed helpers), and `ParityTests` pins the constants, the act table, the room
rules and the verdict words to the header, so a change on either side fails
there.

## The model

A pure function of whole numbers and exact fractions
([`soul_piece_model.py`](../../hs-game-sdk/python/hs_game_sdk/soul_piece_model.py)):

- `act_of_room(room_act_index)`: the act, `RoomActIndex`'s answer plus one,
  `None` when the answer is undefined. An answer outside 0 to 8 is refused.
- `gem_chance(gem_rate)`: the gem's chance on one `DropGems` call, `1/G` under
  `gem_one_in_its_rate`; `None` for a rate that is unknown, zero or negative.
- `expected_drops(rolls, chance)`: `rolls × chance`, linear in the rolls, 0 for
  an unknown chance.
- `HYPOTHESES`: the three questions above, each `None`.

With the transforms of "Our code", the test checks the targets the mod is built
to: for `G` in 9,000, 10,000 and 11,000 the piece's chance over the gem's is
exactly 5/4 (every multiple of 5), and otherwise above 5/4 by less than
`5/(4D)`; over `N` gem rolls the expected pieces are `N/D`, so more rolls (more
monsters from density, a higher gem chance) give proportionally more pieces; and
an unknown rate, a boss, a town, a boss room or a source that is not a monster
gives no piece.

## What the model cannot catch

- **Whether `DropGems` gives the gem exactly 1 in its rate** (it may pick by
  weight), so whether the piece's 5/4 to the gem holds in play. A gem is too
  rare to count in one session; Live procedure 1 checks only that the roll
  fires and with what `self`.
- **Magic find** and any per-place override of the gem's rate: the piece takes
  `G` from `droprate.base`, so where the game uses another value the ratio
  differs.
- **Whether the detours attach**, whether `RoomActIndex` answers by name at run
  time, whether a right-click on a key reaches the game's consume path, and
  whether the summoned boss lives and dies: the hooks, the use route and the
  spawn route are Live procedure 1's checks.
- **Which key definition a piece wears**, whether it lands in the Key tab, and
  how the drop rate feels over a season of play.
