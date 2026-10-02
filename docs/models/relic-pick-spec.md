# Which relic a relic drop yields: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/relic_pick_model.py`](../../hs-game-sdk/python/hs_game_sdk/relic_pick_model.py),
tested by [`tests/test_relic_pick_model.py`](../../tests/test_relic_pick_model.py).
It was written for ForgePact#125 (hub #324): **Remove owned relics from drop pool**
announced that it was holding back a 10/10 relic, and that relic still dropped. It
complements [`drop-roll-spec.md`](drop-roll-spec.md), which covers *whether* a relic
drops (the gate). This spec covers *which* relic comes out once one does.

Every claim carries one of four labels, and a source:

- **Static reading**: read from the compiled game locally and written here in our
  own words. No script text is quoted or transcribed (`AGENTS.md` § "Legal").
  Unless a claim says otherwise, the reading is of the Sep-17 build
  (`Hero_Siege.exe`, 281,751,552 bytes), done on 2026-09-30.
- **Measured**: observed in a running game.
- **Our code**: what ForgePact does. The model leaves it out, and the test expresses
  it as an input transform.
- **Not established**: carried by the model as a parameter.

## Static reading

- **Three routines place a relic, and none of them reads a relic's `droprate.base`.**
  - `DropRelic` is reached from `LoadDrops`.
  - `EnemyKillSatanicZoneRelic` and `EnemyKillSatanicZoneRelicFeast` are both
    reached from `ProjectileKill00Universal`.
  - Each builds the item from the chosen id and places it with `LootGroundCreate`
    as item class 16.
  - The two Satanic kill routines never go through `DropRelic`, so a hook on
    `DropRelic` never sees their rolls.
- **The pick is uniform over every relic that is not a quest relic.** Each routine
  draws an id with `irandom(155)`, which gives 0..155. It draws again for as long
  as `GetRelicQuest(id)` answers true.
  - `GetRelicQuest` answers true for ids 141..155 and false for every other id.
    Its case table lives in zero-initialised data, so every listed id takes the
    "true" branch.
  - So ids 0..140 are equally likely, 1 in 141 each, and a quest relic never
    comes out of the pick.
- **`DropRelic` and the Feast routine can copy an equipped relic instead.**
  - Before the pick, both call `ReturnRandomPlayerRelic`. It chooses one of the
    five equipped relic slots at random (`global.equippedItems[mplr][0][10..14]`)
    and resolves the item there.
  - It returns that relic's id (`b`) only when its level (`o`) is below 10.
    Otherwise it returns -1, and an empty slot also gives -1.
  - After the pick, if the result is not -1 and a draw of `irandom(zrm)` is below
    a bound, the equipped relic replaces the picked id.
  - The bound is 3, 6 or 10 in `DropRelic`, and 3, 5 or 8 in the Feast routine,
    selected by a protected game value that takes the values 1, 2 or 3.
  - `EnemyKillSatanicZoneRelic` has no copy step.
  - So the game never duplicates an equipped relic that is already at 10/10.
- **Only these three routines call `GetRelicQuest`.** A direct-call scan of the
  code section found exactly three call sites, one in each routine, and no other
  code reference. Two call sites reach `ReturnRandomPlayerRelic`: one in
  `DropRelic` and one in the Feast routine.
- **Where the player's own relics live.**
  - Equipped relics are fingerprints in `global.equippedItems[mplr][0][10..14]`.
    This was also measured live on 2026-09-27 (#93).
  - The relic tab is `Controller_obj.inventoryData[key - 1].inventoryRelicGrid`,
    with one cell per relic id. `[relicId][0][0]` holds a grid node whose
    `nodeFingerprint` is the owned copy's fingerprint.
    - `key` is 1 when `global.onl` is 1, and otherwise the player row, which is
      `mplr` offline.
    - `PickupRelic` and `RelicCheckAchievement` both pass `key` to
      `GetProfileInventoryData`, which reads index `key - 1`. The latter walks
      ids 0..155.
    - The game resolves a fingerprint with `GetItemFromFingerprint`, passing the
      owner from `GetOnlinePlayerItemOwner`.
    - Live 1 measured this path (see Measured).
- **A 10/10 relic cannot be picked up.** `PickupRelic` finds the owned copy, first
  in the relic tab and then in the equipped slots, and raises its level only while
  `o` is below 10.

## Measured

- **Live 1, 2026-09-30** ([`relic_pick_measurements.json`](../../hs-game-sdk/curated/relic_pick_measurements.json),
  R1–R3).
  - **Setup.** ForgePact#125's research build ran on the character Suh:
    - 68, 140, 15 and 29 were worn at 10/10, and 109 at level 2;
    - 92 and 128 were at 10/10 in the relic tab.
  - **Method.**
    - Each relic was placed by a direct `DropRelic` call with the chance roll
      skipped.
    - The relic the game built was counted from `CreateItemNew`'s research
      log.
  - **Filter off (R1).** 150 relics built. 8 of them were maxed relics, which
    fits the uniform pick. None of them was a quest relic.
  - **Filter on (R2).** 150 relics built. None was maxed, and none was a quest
    relic. With the filter off, a run of 150 with no maxed relic has less than
    a 1% chance.
  - **One droppable id left (R3).** With every droppable id but 7 and 109
    treated as maxed, only 7 and 109 came out, ten times each.
  - **The relic tab's in-memory shape.**
    - `inventoryData` held one element, a `New_Inventory_Data_obj`
      reference, read at index 0 for the offline key 1.
    - Its `inventoryRelicGrid` had 156 cells. Each was `[[node]]` or
      `[[undefined]]`, and a node is `{nodeStartX, nodeStartY, nodeLocked,
      nodeIsPermanent, nodeFingerprint}`.
    - The SDK's scan resolved all 100 of the save's tab relics and named 92@10
      and 128@10.
- **Relics kept dropping with every relic base at 25,000,000** (drop-roll M7,
  2026-08-28). This agrees with the static reading that the pick never reads the
  base.
- **ForgePact 2.0.1's hold-back did not stop an equipped 10/10 relic.**
  - The hold-back wrote `droprate.base = 1e18` for each maxed relic around a
    `DropRelic` call.
  - A player's log showed `holding back 1 of 1`, and relic 140, equipped at
    10/10, still dropped (ForgePact#125, 2026-09-28).
- **A save's relic tab**: `inventory_order_<slot>.hss` has an
  `inventory_relic_tab` object.
  - It is keyed `x-y-<stamp>-16`, and each entry is `{data: {b, a, j, c}}`.
  - `o` is absent at level 1: slot 1 of the owner's saves holds 14 such entries
    and none has `o` (read 2026-09-30).

## Our code

**ForgePact's lever**, from ForgePact#125's fix:
- `GetRelicQuest` answers true for a relic the player owns at 10/10, whether
  equipped or in the relic tab. The game's own loop then draws again, so the maxed
  relic never comes out and the rest stay equally likely.
- It stands down when no relic in 0..140 would be left. Otherwise the loop has no
  way out.

The test file expresses this as a transform of the quest set, and
`LeverParityTests` pins it to ForgePact's source.

## Not established

- **`zrm` and the protected value that selects the copy bound.** The copy chance
  is therefore a parameter, `copy_chance` = P(`irandom(zrm)` < bound). If `zrm`
  were 100, it would be 3/101, 6/101 or 10/101.
- **Indirect calls.** A script can also be called by index, for example with
  `script_execute`, and the direct-call scan cannot see that. No such call has
  been observed.

## The model

A pure function of numbers, with exact fractions
([`relic_pick_model.py`](../../hs-game-sdk/python/hs_game_sdk/relic_pick_model.py)):

- `quest_relic_ids()` returns ids 141..155. `pick_pool(quest)` returns the ids
  that can come out of the pick. It raises when the pool is empty, because the
  game's loop would never end.
- `pick_distribution(quest, equipped, copy_chance)`:
  - The uniform pick over the pool, times the chance of no copy.
  - Plus `copy_chance / 5` for each equipped slot whose relic is below level 10.
  - `equipped` lists the five slots as `(id, level)` or `None`.
- `copy_chance(bound, zrm)` = min(bound, zrm + 1) / (zrm + 1).

## What the model cannot catch

- **Whether a hook attaches.**
  - `GetRelicQuest` is only ever called directly (`call rel32`), so a table-only
    hook never runs.
  - The lever needs the native detour, and only a live positive control shows
    that it fired.
- **What the scan sees.** The model takes the maxed set as given, and whether the
  plugin's scan reads the relic tab is a runtime question. The SDK's
  `RelicTabScanReport` answers it live.
- **The RNG sequence and the copy bound's inputs**, as in `drop-roll-spec.md`.
