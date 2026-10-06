# When a key dungeon's end chest opens: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/dungeon_chest_model.py`](../../hs-game-sdk/python/hs_game_sdk/dungeon_chest_model.py)
(`dungeon_chest_model`), tested by
[`tests/test_dungeon_chest_model.py`](../../tests/test_dungeon_chest_model.py)
against [`hs-game-sdk/curated/dungeon_chest_measurements.json`](../../hs-game-sdk/curated/dungeon_chest_measurements.json).
It was written for ForgePact#31, whose **Dungeon chest opens early** control lets
a key dungeon's end chest (`Dungeon_Chest_obj`) open once a chosen share of
**all** the dungeon's monsters is dead, instead of all of them. It answers two
questions: what this toolkit knows about the game's own rule for the chest, and
exactly what the mod counts.

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
  nor ruled out by the reading, and variable names are not visible either (they
  are read through slot ids). Live procedure 1 answered what the reading could
  not: the chest polls a builtin (DC10), and no unlock variable was seen to
  change (DC9).
- **DC5, the neighbours.** `Dungeon_Boss_Blocker_obj` (1365) has Create, Step and
  Draw; its Step calls `quest_exists` and `GPV`. `Spawn_Dungeon_obj` (4667) has
  Create, Step, Alarm 0 and Draw, and its Alarm 0 calls `sc_rift`,
  `StringStartsWith`, `GPV` and creates an instance: it is the world-side
  entrance spawner of the special-content family, not a monster spawner.
  `Dungeon_Spawner_1_obj` to `Dungeon_Spawner_4_obj` have only a small Create.
  The monsters inside a dungeon come from the creator family instead (DC8).
- **The creators** (no curated entry: the reading decides no number). Read on
  2026-10-03 for ForgePact#31's second plan. `Enemy_Creator_obj` owns Create,
  Alarm 0, Alarm 1, Alarm 2 and CleanUp events, plus the timer callback that
  ForgePact's creator trace already hooks. The callback does the distance test
  and, when the player is near enough, stops its own timer and arms an alarm;
  it reads nothing that names a count. The pack is built in the alarm events,
  which call monster-affix, network, wormhole, satanic-zone and stat scripts
  by name; one of them is a native body the decompiler does not finish. Every
  per-instance variable is reached through a slot number and every builtin
  through the runtime's table, so **which variable or roll decides how many
  monsters a creator makes is not nameable statically**. Only where it happens
  is: at the creator's birth of its pack, after the distance test. A creator
  stays alive after it has spawned (`docs/RUNTIME_DATA_MODELS.md` § 11.2, and
  DC8 measured it).

## Measured

- **DC6, the kill path** (`docs/RUNTIME_DATA_MODELS.md` § 13.5, from Headhunter's
  verification in `ForgePact/docs/headhunter-dispatch-verification.md`):
  `EnemyDestroyKillProc` runs with the dying enemy as `self`, and again with the
  player as `self`; `Enemy_Death_Effect_obj` is not made on every kill (50 for 307
  kill-proc calls); `Enemy_Parent_obj` (1429) is the monster family. That is why
  the mod counts a kill at the enemy-`self` call, once per instance id, and not
  by death effects.
- **The vanilla rule as players see it**: the chest stays shut until every
  monster in the dungeon is dead (ForgePact#31's report).

The entries below are ForgePact#31's Live procedure 1 (2026-10-03, research DLL
`256d3ba4…`, save slot 14, one Pumpkin Cellar run, room `Pumpkin_Cellar_01_rm`).
The capture is the local `.claude/workorders/forgepact-issue-31-dungeon-chest-live-1.md`;
the tracked copy is `ForgePact/docs/dungeon-chest-research.md` § "Live procedure
1" › "Results".

- **DC7, monsters stream in; they are not all alive at entry.** The first
  per-second line in the dungeon read `alive=5`, the next one `alive=44` (the
  owner: the 44 are the packs near the entrance), and `alive=` then rose and fell
  as the player moved, peaking at 210 with 260 kills made, before reaching 0 at
  the clear. So kills plus monsters alive now is not the dungeon's population,
  and a share measured against it is far too early (at entry it is 44 of 600).
  `HYPOTHESES["all_monsters_alive_at_entry"]` is `False`.
- **DC8, every creator exists at entry and stays.** `creators=122` on the first
  tick and on every line until the clear: the dungeon's monsters come from
  creator-family spawners inside it, and those spawners persist after they have
  spawned. `HYPOTHESES["no_creators_in_dungeon"]` is `False`.
- **DC9, no unlock variable was seen.** At the last kill the only chest variable
  that changed was `nearest` (from -4 to an instance reference), on the tick after
  `alive=0 kills=600`; on the open only the sprite (closed to open),
  `image_index` and `image_speed`. No player-variable read or write showed up in
  the whole session. Read: once no enemy exists, the chest looks for the nearest
  player and opens on approach; no unlock flag is written anywhere the probe
  watched. `HYPOTHESES["unlock_is_a_variable"]` is `False`.
- **DC10, the chest polls `instance_exists(Enemy_Parent_obj)` itself.** With the
  chest as `self`, `instance_exists` with `Enemy_Parent_obj` as its argument was
  called 3402 times by the time the dungeon had been entered and 41519 times by
  the end, about once a frame. The chest also asked about `Player_obj` (1897),
  `Loot_Ground_obj` (12) and `objZoneGenV2` (12); `instance_find` and
  `instance_place` were not called with the chest as `self` (their detours saw
  the game's calls). Whether the chest calls `instance_number` is **not
  observed**: that detour attributed no call to any game `self` in the session
  (`gameCalls=0`), so its zero chest row could not have shown one.
  `HYPOTHESES["unlock_is_a_builtin_poll"]` is `True`, and this poll is
  what ForgePact answers to open the chest early.
- **DC11, the dungeon's total was 600, all counted.** The run cleared at
  `kills=600 alive=0`. The kill hook counted one per kill with no kill whose
  `self` was not an enemy (`killHook=ok killNotEnemySelf=0`). That is about 4.9
  monsters per creator over all 122, or (600 − 44) ÷ 122 ≈ 4.6 per creator if
  every creator was still to spawn once the 44 were alive. The kill tally does
  not match the fall in `alive=` over a window, because spawns arrive in it
  (the `kill-hook-fires` check's literal wording failed for that reason only).
- **DC13, the chat line.** `ChatAddServerMessage`, called by name with the local
  player as `self` and one string, put a red line `SERVER: <text>` bottom-left.
  Inside, the game called `ChatAddMessage` (sender `SERVER`, the text, numbers, a
  `[hh:mm]` time and undefined values) and `IngameChatFeedAddLatest`. Offline,
  the player cannot type in chat. This is the countdown's chat form, not the
  chest, so the model does not carry it.

The entries below are ForgePact#31's Live procedure 1b (2026-10-03, research DLL
`316a68ed…`, save slot 14, two Pumpkin Cellar runs in one launch: run A a census
with the mod off, run B the mod at 50 % of an override total of 600). The
capture is the local `.claude/workorders/forgepact-issue-31-dungeon-chest-b-live-1b.md`;
the tracked copy is `ForgePact/docs/dungeon-chest-research.md` § "Live procedure
1b" › "Results".

- **DC14, no creator variable sums to the total (`creator-sum`).** At the
  chest's first sight run A read `alive0=5`, 122 creators, 5 of which had
  already spawned, and 20 variable names on the sampled creators. No numeric
  name present on the creators summed near the 619 kills to clear, over every
  creator or as `alive0` plus the creators still to spawn: the nearest were `img`
  (112.67, or 91 over the pending ones), `isWormhole` and `spawnPack` (about 20
  million each). The names that sound like a pack size read as one large real
  per creator, rising from creator to creator (about 163047 upward), not as a
  count. So the total is not readable as a sum, and
  `HYPOTHESES["planned_total_source"]` is `'estimate'` (with DC16).
- **DC15, no creator variable matches its births (`creator-match`).** Every
  candidate row read `match=0/122` and `matchPending=0/117` at the clear.
- **DC16, whether a creator has spawned is readable (`creator-state`).** All 8
  sampled creators read `alarm[0]=5`, `enemyCreatorTimer` undefined and
  `enemyArray` undefined at first sight. About 10 s later, after they had armed,
  `alarm[0]` was -1 and `enemyCreatorTimer` a real (214 to 221); at the clear,
  after they had spawned, `enemyArray` was an array. So "still to spawn" is
  `enemyArray` not being an array. `enemyCreatorTimer` alone cannot say it:
  it is undefined both before a creator arms and after it spawns.
- **DC17, kills and births differ by 25 (`kills-equal-births`).** Run A cleared
  at `kills=619 alive=0` with 644 births by creators (`births0=5`, so 639 after
  the census): `alive0` plus the births since is 644, 25 more than the kills.
  Some monsters a creator makes are never killed by the player and never block
  the chest, so a total for the chest is counted in kills, not births.
- **DC18, answering the poll opens the chest (`unlock-works`).** In run B the
  threshold latched at `unlocked early at 304/600 alive=214`; the detour then
  answered the chest's poll `false` 390 times (`answered=390`), and the chest's
  sprite went from closed to open at `kills=325 alive=193`: it opened with 193
  monsters alive. Whether it dropped loot was not checked by the operator (the
  owner opened it). The countdown showed above the head (`Chest: 9 kills to go`)
  and as chat lines; the owner saw the head label flicker ("the text above
  character felt jerky and was blinking very fast as it was updating every
  frame"), which is ForgePact's draw, not the game.

## Not established

Each of these is an open question, carried in the model's `HYPOTHESES` where it
decides a number.

- **DC12, does a boss dungeon follow the same rule?** (`boss-dungeon`, the
  outlier). Not observed: Live 1 and Live 1b saw `blockers=0` on every line,
  and only Cellar Keys were at hand. `HYPOTHESES["boss_dungeon_same_rule"]`
  stays `None`.
- **Whether the measured mean holds for other dungeons.** The mean per creator
  still to spawn (DC19 below) is one Pumpkin Cellar run; other key dungeons
  were not observed live.
- **What the 5 monsters alive at run A's first sight were.** The 5 creators with
  a birth before the census and the 5 alive match; whether those were their
  packs or idle monsters that come with a spawner is not established. If they
  were idle ones, all 122 creators were still to spawn.
- **Whether `enemyArray` marks every creator type: partly answered.** Here
  only the 8 sampled `Enemy_Creator_obj` instances were read before and
  after. Map reveal's issue #181 sessions (2026-10-06) then sampled five
  creator kinds: the plain and ambush creators carry `enemyArray`; the
  ancient, miniboss and colossal chest creators do not, and an ancient
  creator still did not after creates were attributed to it at a warp where
  the owner saw monsters appear (normal packs were born there too)
  (`docs/RUNTIME_DATA_MODELS.md` § 11.2). Champion and legion creators were
  not sampled. An inference, not measured: if the estimate counts a creator
  without `enemyArray` as still to spawn, a dungeon holding ancient, miniboss
  or colossal chest creators would be over-counted for the whole run.

## Our code

**ForgePact's Dungeon chest opens early** (`dungeonchest <pct>|off|status`, config
keys `mod_dungeon_chest` and `dungeon_chest_pct`, ForgePact#31,
`ForgePact/plugin/include/ForgePact/DungeonChestMod.hpp`). Write `k` for the
kills counted in this dungeon, `a` for the monsters alive now, `T` for the
dungeon's planned total, and `p` for the percentage.

- **Mode.** Off, or a whole number `p` from 50 to 95 inclusive. Any other value
  (49, 96, a fraction, text) is refused and the mode stays what it was. The
  panel's slider moves in steps of 5, but a typed value may be any whole number in
  the range. Off is the default; the command treats `0` as off, as every
  ForgePact toggle does.
- **Kills.** One per enemy instance id, at `EnemyDestroyKillProc`'s enemy-`self`
  call (DC6), counted only after the chest has been seen in this dungeon.
- **The planned total `T`** is every monster the dungeon will hold, spawned yet
  or not, **fixed once at the chest's first sight** from the creator family
  (the seven creator objects ForgePact's density code already knows, density
  copies included). Live 1b decided its form (`total-route: estimate`, DC14 and
  DC16): T is the monsters alive at first sight plus (creators still to spawn,
  those whose `enemyArray` is not an array, × a measured mean per creator),
  rounded up. A creator whose state cannot be read is counted on the status
  line (`unreadable=`), and a failed census (no creator family, no creators,
  or any creator unreadable; owner, 2026-10-04) gives no T: counted as
  spawned, an unread creator would shrink T below the share the player set.
  T does not move with the alive count, so `Chest: 50 kills to go` means 50
  real kills. (Had a per-creator count been readable, T would have been the
  `variable` form, the sum of those counts; DC14 found none.)
- **DC19, the mean** is 614 ÷ 117 ≈ 5.25 monsters per creator still to spawn,
  from run A of Live 1b: (619 kills to clear − 5 alive at first sight) ÷ (122
  creators − 5 that had spawned by then). It is taken over kills, never births
  (DC17). The header holds it as two named constants, `kEstimateKills = 614`
  and `kEstimatePendingCreators = 117`, so T for run A's first sight is exactly
  619. If the 5 first-sight monsters were idle ones (all 122 still to spawn), the
  same formula gives 646 for that run; an over-count only raises the threshold,
  and the game's rule still opens the chest at `a = 0`. Live 1's (600 − 44) ÷ 122
  ≈ 4.6 is a second point, from a census taken later; it is not the constant.
- **T unknown.** With no total source, or a source that answers 0 (the
  build's does for a failed census: no creator family, no creators, or any
  creator unreadable), the share is refused: no threshold, nothing shown, the
  status reports `total=unavailable`, and the chest follows the game's rule.
- **The clamp.** Each evaluation uses `max(T, k + a)` as T, so the total is
  never below the monsters already seen (kills counted plus alive now). The
  threshold is never above T, and the game's own rule still opens the chest at
  `a = 0`: the mod never opens the chest later than the game would.
- **Progress** is `k / T`.
- **Threshold** `t = ceil(p / 100 × T)`, computed in whole numbers as
  `ceil(p × T / 100)`, with T clamped as above. The threshold is reached when
  `k ≥ t`, and once reached it stays reached (latched) for that dungeon.
- **Rounding** is upward, so the chest never opens before `p` % of the planned
  total is dead. Because `p ≤ 95 < 100`, `t ≤ T`, though rounding can ask for
  all of them (95 % of 7 monsters is 6.65, so `t = 7`).
- **Switched on mid-dungeon.** T is taken from the census at that moment, plus
  the kills this dungeon's tally already holds. Kills made before the kill hook
  was installed are not counted, so the share then applies to what was left at
  the switch. A room change resets the tally.
- **Countdown** `n = max(0, t − k)`. It is shown only when `0 < n ≤ 50` and the
  threshold has not latched, as `Chest: <n> kills to go`. With T fixed, it only
  counts down. Its forms (a line above the player's head, chat lines, both or
  none) are the header's; the panel offers head, chat and both, head by
  default (the owner, 2026-10-04: `countdown-form: choice`). The head label's
  text changes only when `n` does.
- **Off** is the game's own rule: never early, no countdown, nothing written.

The test file expresses this as input transforms (`set_mode`, `known_total`,
`clamped`, `threshold`, `reached`, `countdown`, `shown`), and `LeverParityTests`
pins them to the header and to `ForgePact/src/forgepact.py`, so a change on
either side fails there.

## The model

A pure function of whole numbers and exact fractions
([`dungeon_chest_model.py`](../../hs-game-sdk/python/hs_game_sdk/dungeon_chest_model.py)):

- `chest_openable(alive)`: the game's rule, true only when no monster is alive
  (the chest's own `instance_exists` poll, DC10).
- `kills_to_vanilla(alive)`: the kills left before the game opens the chest
  itself, which is `alive`.
- `planned_total(alive_at_first_sight, planned_per_creator)`: the monsters alive
  at first sight plus the sum of the given per-creator counts (pass 0 alive for
  the plain sum over every creator).
- `estimated_total(alive_at_first_sight, pending_creators, mean_per_creator)`:
  the `estimate` form, rounded up to a whole monster.
- `progress(kills, total)`: `kills / total` as a `Fraction`; a total of 0 is
  refused, since it means the total is unknown.
- `HYPOTHESES`: the questions above, with Live 1's four answers and Live 1b's
  `planned_total_source` (`'estimate'`) filled in.

Every function refuses a negative or non-integer count. Nothing draws a random
number.

## What the model cannot catch

- **Whether the kill hook attaches** and sees every kill in a dungeon, and
  whether answering the chest's poll opens it (DC18). Only a live `dungeonchest
  status` line and a live session show that.
- **Whether the estimate fits a dungeon**: the model multiplies the counts it is
  given; whether `enemyArray` marks a creator still to spawn, and whether the
  mean holds outside Pumpkin Cellar, is what Live procedure 2's `on-total` and
  later sessions measure.
- **How early feels in play**, and whether the countdown is readable.
