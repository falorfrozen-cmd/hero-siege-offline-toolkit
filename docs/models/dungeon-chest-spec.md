# When a key dungeon's end chest opens: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/dungeon_chest_model.py`](../../hs-game-sdk/python/hs_game_sdk/dungeon_chest_model.py)
(`dungeon_chest_model`), tested by
[`tests/test_dungeon_chest_model.py`](../../tests/test_dungeon_chest_model.py)
against [`hs-game-sdk/curated/dungeon_chest_measurements.json`](../../hs-game-sdk/curated/dungeon_chest_measurements.json).
It was written for ForgePact#31, whose **Dungeon chest opens early** control lets
a key dungeon's end chest (`Dungeon_Chest_obj`) open once a chosen share of the
dungeon's monsters is dead, instead of all of them. It answers two questions
before that mod's unlock code is written: what this toolkit knows about the
game's own rule for the chest, and exactly what the mod counts.

Every claim carries one of four labels, and a source:

- **Static reading**: read from the compiled game or from `hs-game-sdk`'s extracted
  tables, and written here in our own words. No script text is quoted or
  transcribed (`AGENTS.md` § "Legal").
- **Measured**: observed in a running game.
- **Our code**: what ForgePact does. The model leaves it out, and the test expresses
  it as an input transform.
- **Not established**: carried by the model as an open hypothesis, or left out.

Each claim names its curated entry (DC1, DC2, ...) where it has one.

## Static reading

Read on 2026-10-03 in a local Ghidra project of the current game build. The
object events were found through the exe's `YYGMLFuncs` rows (name, function,
variables), the same table ForgePact's frame profiler walks, so an object's events
can be read statically even though `symbols.csv` lists only scripts. Only the
names of what each event calls are recorded here.

- **DC1, the chest's events.** `Dungeon_Chest_obj` (SDK object index 1366) owns
  five events: Create, Step, Draw, Alarm 0 and Other 7 (animation end).
- **DC2, the Step calls no named script that counts.** The chest's Step calls,
  by name, `GetKeyDungeonRoom`, `GetKeyDungeon`, `NetworkSendClientEffect`, `GPV`
  (read a player variable), `IsDefined` and `PlaySound3D`. None of those named
  scripts counts or lists enemies; a builtin the Step reaches through the
  function table is not visible to the reading (DC4).
- **DC3, the open is the animation end.** Other 7 is where the chest pays out:
  it calls `CreateInFreePos`, creates an instance through the `instance_create`
  builtin, and calls `SPV`, `ReturnSpecificStat`, `quest_exists`, `QuestComplete`
  and `CommunityQuestAddProgress`. Alarm 0 calls `ReturnSpecificStat` and `GPV`;
  Create calls `CheckTown`, `UpdateDepth` and `ReportClient`. The mod leaves all of
  this alone: what the chest drops and the quest progress it makes are out of
  ForgePact#31's scope.
- **DC4, the unlock condition is not visible statically.** No body in this build
  calls a builtin directly (in 150 functions read, only `is_handle` appeared as a
  direct call); builtins go through the runtime's function table. So a poll such
  as `instance_number` or `instance_exists` made by the chest is neither proven
  nor ruled out by the reading. Variable names are not visible either: they are
  read through slot ids, and no store to the slot globals was found. What
  decides the chest's unlock is therefore not established. Candidates include a
  builtin poll hidden from the reading, a chest or blocker variable (built-in or
  not) that another event writes, and the player variable the Step reads
  through `GPV`. Only a live census can tell which.
- **DC5, the neighbours.** `Dungeon_Boss_Blocker_obj` (1365) has Create, Step and
  Draw; its Step calls `quest_exists` and `GPV`. `Spawn_Dungeon_obj` (4667) has
  Create, Step, Alarm 0 and Draw, and its Alarm 0 calls `sc_rift`,
  `StringStartsWith`, `GPV` and creates an instance: it is the world-side
  entrance spawner of the special-content family, not a monster spawner.
  `Dungeon_Spawner_1_obj` to `Dungeon_Spawner_4_obj` have only a small Create.

## Measured

- **DC6, the kill path** (`docs/RUNTIME_DATA_MODELS.md` § 13.5, from Headhunter's
  verification in `ForgePact/docs/headhunter-dispatch-verification.md`):
  `EnemyDestroyKillProc` runs with the dying enemy as `self`, and again with the
  player as `self`; `Enemy_Death_Effect_obj` is not made on every kill (50 for 307
  kill-proc calls); `Enemy_Parent_obj` (1429) is the monster family. That is why
  the mod counts a kill at the enemy-`self` call, once per instance id, and not
  by death effects.
- **The vanilla rule as players see it**: the chest stays shut until every
  monster in the dungeon is dead (ForgePact#31's report). This is the rule the
  model carries as the game's. How the chest learns it is DC4's open question.

Nothing else about the chest has been measured yet. ForgePact#31's Live procedure
1 is the session that measures it; its results go into DC7-DC10 below and into
the curated file, which holds those four as `pending` placeholders until then.

## Not established

Each of these is a question Live procedure 1 answers, and an entry in the model's
`HYPOTHESES`, `None` until a measured curated entry decides it:

- **DC7, are all of a dungeon's monsters alive at entry?** (`alive-count`) The
  mod's denominator is kills since the chest was first seen plus monsters alive
  now; that is the dungeon's whole population only if nothing spawns later.
  `HYPOTHESES["all_monsters_alive_at_entry"]`.
- **DC8, are there creators inside a dungeon?** (`creators-in-dungeon`) An
  `Enemy_Creator_obj` inside the dungeon would add monsters after entry, which the
  denominator only sees once they exist (a Known Limitation, not solved here).
  `HYPOTHESES["no_creators_in_dungeon"]`.
- **DC9, which variable flips when the last monster dies?** (`unlock-signal`) On
  the chest or the boss blocker. `HYPOTHESES["unlock_is_a_variable"]`.
- **DC10, does the chest's Step poll a builtin about monsters, and which?**
  (`builtin-poll`) `HYPOTHESES["unlock_is_a_builtin_poll"]`.
- **Does the kill hook's tally match the fall in the alive count?**
  (`kill-hook-fires`) If it does not, kills are under- or over-counted and the
  threshold moves. `HYPOTHESES["kill_tally_matches_alive_drop"]`.
- **Does a boss dungeon follow the same rule?** (`boss-dungeon`, the outlier).
  `HYPOTHESES["boss_dungeon_same_rule"]`.
- **Which chat script and call shape put a line in the feed** (`chat-hook-fires`,
  `chat-shape`). This is about the countdown's chat form, not the chest, so the
  model does not carry it.

## Our code

**ForgePact's Dungeon chest opens early** (`dungeonchest <pct>|off|status`, config
keys `mod_dungeon_chest` and `dungeon_chest_pct`, ForgePact#31,
`ForgePact/plugin/include/ForgePact/DungeonChestMod.hpp`). Write `k` for the
kills counted since the chest was first seen in this dungeon, `a` for the
monsters alive now, and `p` for the percentage.

- **Mode.** Off, or a whole number `p` from 50 to 95 inclusive. Any other value
  (49, 96, a fraction, text) is refused and the mode stays what it was. The
  panel's slider moves in steps of 5, but a typed value may be any whole number in
  the range. Off is the default; the command treats `0` as off, as every
  ForgePact toggle does.
- **Kills.** One per enemy instance id, at `EnemyDestroyKillProc`'s enemy-`self`
  call (DC6), counted only after the chest has been seen in this dungeon.
- **Progress** is `k / (k + a)`, re-evaluated once a second. With `k + a = 0` it
  is 1.
- **Threshold** `t = ceil(p / 100 × (k + a))`, computed in whole numbers as
  `ceil(p × (k + a) / 100)`. The threshold is reached when `k ≥ t`, and once
  reached it stays reached (latched) for that dungeon.
- **Rounding** is upward, so the chest never opens before `p` % of the counted
  monsters are dead. Because `p ≤ 95 < 100`, `t ≤ k + a`: the mod never opens the
  chest later than the game would, though rounding can make it open at the same
  kill (95 % of 7 monsters is 6.65, so `t = 7`, all of them).
- **Countdown** `n = max(0, t − k)`. It is shown only when `0 < n ≤ 50` and the
  threshold has not latched, as `Chest: <n> kills to go`. Its forms (a line above
  the player's head, chat lines, both or none) are the header's; which one ships
  is decided after Live procedure 2.
- **Zero-monster dungeon.** `k + a = 0` gives `t = 0`: the threshold is reached at
  once and no countdown is shown.
- **Off** is the game's own rule: never early, no countdown, nothing written.

The test file expresses this as input transforms (`set_mode`, `threshold`,
`reached`, `countdown`, `shown`), and `LeverParityTests` pins them to the header
and to `ForgePact/src/forgepact.py`, so a change on either side fails there.

## The model

A pure function of whole numbers and exact fractions
([`dungeon_chest_model.py`](../../hs-game-sdk/python/hs_game_sdk/dungeon_chest_model.py)):

- `chest_openable(alive)`: the game's rule, true only when no monster is alive.
- `population(kills, alive)`: `kills + alive`, the monsters the mod can see.
- `progress(kills, alive)`: `kills / (kills + alive)` as a `Fraction`, 1 for an
  empty dungeon.
- `kills_to_vanilla(alive)`: the kills left before the game opens the chest
  itself, which is `alive`.
- `HYPOTHESES`: the six open questions above, all `None`.

Every function refuses a negative or non-integer count. Nothing draws a random
number.

## What the model cannot catch

- **Whether the kill hook attaches** and sees every kill in a dungeon, and
  whether the chest's own unlock reacts to what the mod writes. Only a live
  `dungeonchest status` line and Live procedure 1's probe show that.
- **Monsters spawned after entry**, if a dungeon has creators (DC8).
- **How early feels in play**, and whether the countdown is readable.
