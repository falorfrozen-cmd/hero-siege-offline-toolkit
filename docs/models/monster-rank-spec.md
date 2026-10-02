# What a monster's rank does to it, and what a boss's might: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/monster_rank_model.py`](../../hs-game-sdk/python/hs_game_sdk/monster_rank_model.py),
tested by [`tests/test_monster_rank_model.py`](../../tests/test_monster_rank_model.py)
against [`hs-game-sdk/curated/monster_rank_measurements.json`](../../hs-game-sdk/curated/monster_rank_measurements.json).
It was written for ForgePact#44 (hub #379), whose **Bosses** control makes every
boss the game spawns roll as Rare (rank 3, "uber boss") or Ancient (rank 4, "uber
uber boss"). It answers one question before that control's text is written: what
does a rank do to a monster, and what is still unknown about what it does to a
boss.

Every claim carries one of four labels, and a source:

- **Static reading**: read from the compiled game or from `hs-game-sdk`'s extracted
  tables, and written here in our own words. No script text is quoted or
  transcribed (`AGENTS.md` § "Legal").
- **Measured**: observed in a running game.
- **Our code**: what ForgePact does. The model leaves it out, and the test expresses
  it as an input transform.
- **Not established**: carried by the model as an open hypothesis, or left out.

The rank numbers are the game's `enemyRarity`: 1, 2, 3 and 4. ForgePact's labels for
them are normal, champion, rare and ancient. The save's kill counters suggest the
game's own names are one step off (Common, Champion, Ancient, Legion); that is
inferred, not checked on screen (`docs/RUNTIME_DATA_MODELS.md` § 13.7).

## Static reading

- **`EnemyRaritySettings(typeId)` is where a rank becomes a monster.** It is called
  from `Enemy_Parent_obj`'s Alarm 4 with the enemy as `self`, for every enemy,
  boss or not. The call comes after the spawner has decided `enemyRarity` and filled
  the affix list, and before the stats, the affix effects and the health bar are
  built. Sources: ForgePact README § "Tyrant's Crown" and the hook's comment in
  `ForgePact/plugin/ModuleMain.cpp`; the order was live-traced on 2026-09-05 (entry
  and exit state identical, the health bar not yet made), so this item is measured
  as well as read. Its body was not read in full: which values it scales, and by
  how much, is not established from the reading (see Not established).
- **An ordinary monster's kill pays out through `DropItem` with the rank as its
  first argument.** `Enemy_Parent_obj`'s Destroy event calls `DropItem` only when
  the monster's protected HP is 0 or less (`docs/RUNTIME_DATA_MODELS.md` § 13.1).
  Drops read `enemyRarity` off the dying enemy (§ 13.5), and `DropItem`'s first
  argument is the same number (§ 13.7, measured on ordinary monsters). For a
  boss it was measured on one Karp King in Live procedure 1b (1 unraised, 4
  raised; MK23, below), after Live procedure 1 had no anchor (MK12).
- **Which objects are bosses.** `hs-game-sdk`'s object parent table gives
  `Enemy_Child_Boss_obj` (index 1407) 41 descendants, among them `Karp_King_obj`
  (2368), `Damien_obj` (1115), `Uber_Damien_obj` (4945), `Uber_Anubis_obj` (4938)
  and `Uber_Luna_obj` (4952). The chain is
  `<boss> -> Enemy_Child_Boss_obj -> Enemy_Parent_obj -> Avoidable_Parent_obj`.
  `Enemy_Parent_obj`'s direct children are only `Demon_Lightning_obj`,
  `Enemy_Child_Basic_obj`, `Enemy_Child_Boss_obj` and
  `Enemy_Child_Destructible_obj`, so descending from `Enemy_Child_Boss_obj` is the
  whole boss signal. `Ghost_Pirate_King_Boss_obj` is a prop, not an enemy, and is
  not one of them. `MonsterRankFamilyTests` checks the count against the SDK.

## Measured

- **AFK FARM, 2026-09-17 to 09-24**: 6,471 recorded packets over 214 capture
  sessions, two game builds (`docs/RUNTIME_DATA_MODELS.md` § 13.7; MK1-MK4 in the
  curated file). These are ordinary monsters; no boss row is among them.
  - **MK1, rank multipliers** next to the same monster object at rank 1 in the same
    room (medians over 41-48 pairs). Health ×1.84, ×2.98, ×4.23; damage ×1.27,
    ×1.53, ×1.90; XP ×2.75, ×4.25, ×6.25, for ranks 2, 3 and 4. The XP multipliers
    are exact; the health and damage ones are medians.
  - **MK2, protected drop values by rank**, identical within a rank:
    `dCommonChance` 4 / 20 / 36 / 50, `dCommonDropMult` 11 / 20 / 42 / 58,
    `dSatanicDropMult` 1 / 0.925 / 0.475 / 0.285, `dSlots` 1 / 1-3 / 2-5 / 4-8,
    for ranks 1 to 4.
  - **MK3, the monster's drop table rises with rank**: runes (drop type 4)
    12 / 22 / 34 / 100 and dungeon keys (type 12) 5 / 40 / 75 / 100 for ranks 1-4.
  - **MK4, kill mix**: without ForgePact's rarity sliders, 70.1 / 16.9 / 10.4 /
    0.1 % of 2,994 kills at ranks 1-4; with them on, 35.1 / 18.9 / 32.1 / 13.8 % of
    21,122 kills.
- **MK5, a player's report, not a measurement of ours** (ForgePact v1.4.1,
  recorded 2026-09-18 in `ForgePact/tests/test_rarity_boss_exclusion_contract.py`'s
  docstring): with the sliders at 20 % rare and 20 % ancient, an Anubis boss went
  from about 500k to about 4.5M HP. That is about ×9, above every health multiplier
  in MK1, and its base, its rank and how it was read are unknown. It is why the
  sliders leave bosses alone, and it is not evidence either way about the rank
  table.
- **ForgePact#44's Live procedure 1, 2026-10-02** (MK6-MK14; Nightmare, Outskirts
  of Inoya, zone level 170; each boss spawned by `instance_create_depth` with the
  Bosses control set, read with the research build's `bossprobe`, killed by
  writing its protected health to 0; the session's record is
  `ForgePact/docs/boss-rarity-research.md` § "Live procedure 1"):
  - **MK6, a boss's health at rank 1**: `Karp_King_obj` 44,625,000, the same on two
    spawns, read through the protected-store getter the probe's own control proved.
  - **MK7, a boss's health at rank 4**: the same boss raised to rank 4 by the
    Bosses control had 252,242,812, ×5.65 its rank-1 health (5.6525). MK1's rank-4
    row is ×4.23, so this boss rose 1.34 times as far as the ordinary monsters'
    median, but the sample is confounded (the Bosses control also wrote a
    3-affix top-up on this boss: 16 Multishot, 17 Treasure Gobbler, 25
    Pyromaniac), so it decides nothing:
    `HYPOTHESES["boss_hp_follows_rank_table"]` stays `None`. One boss, one kill,
    one zone. It fits MK5 (a report above every health row) without confirming it.
  - **MK8, the rank written held through the setup**: at the exit of
    `EnemyRaritySettings` the rank the control wrote at its entry was still 3 or 4
    on `Karp_King_obj`, `Damien_obj`, `Uber_Damien_obj` and `Uber_Anubis_obj`. This
    is a readback of our own write, not something the game built.
  - **MK9, three more rank-4 bosses' health, no rank-1 base**: `Damien_obj`
    159,906,250, `Uber_Damien_obj` 1,306,210,937, `Uber_Anubis_obj` 4,451,343,750.
  - **MK14, the drop rank instrument's control**: an ordinary
    `Skeleton_Mage_Fire_obj` the sliders raised to rank 4 died with `DropItem`'s
    first argument 4, as MK2 says.
- **ForgePact#44's Live procedure 1b, 2026-10-02** (MK15-MK24; the same zone,
  spawn route, probe and kill route; the session's record is
  `ForgePact/docs/boss-rarity-research.md` § "Live procedure 1b"):
  - **MK15-MK16, the identity control.** An ordinary `Skeleton_Mage_Fire_obj`
    raised by the sliders (which write the rank and the same affix top-up as the
    Bosses control) to rank 3 and 4, read on the probe's own path: `damage`
    ×1.4008 and ×2.0039 (within 10% of MK1's ×1.53 and ×1.90), `killExperience`
    ×4.2670 and ×6.2760 (within 2% of ×4.25 and ×6.25; `experience` the same). So
    these two variables hold a monster's damage and XP, which is what lets a
    boss's reads of them count. **MK17**: the same spawns' health is not a
    control (×5.69 at rank 3, ×5.31 at rank 4, one spawn each). **MK18**: the
    drop rank control passed again (first argument 4 at rank 4).
  - **MK19, the rank-1 Karp King** on three spawns: health 44,625,000, `damage`
    217, `killExperience` 4,950, and a `DropItem` first argument of 1 at its
    traced death, the anchor.
  - **MK21, a boss's damage at rank 4**: ×2.0968 (217 -> 455). MK1's rank-4 row is
    ×1.90; this is 10.4% above it, outside the control's 10%, so
    `HYPOTHESES["boss_damage_follows_rank_table"]` is `False`.
  - **MK22, a boss's XP at rank 4**: ×6.2505 (4,950 -> 30,940), the table's exact
    ×6.25: `boss_xp_follows_rank_table` is `True`.
  - **MK23, a boss's drop rank at rank 4**: `DropItem`'s first argument 1 at the
    unraised boss's death, 4 at the raised one's: `boss_drop_rank_reaches_dropitem`
    is `True`.
  - **MK20, a boss's health at rank 4**: ×4.7281 (44,625,000 -> 210,992,578), with
    a different 3-affix top-up (12 Fire Enchanted, 20 Punisher, 31 Antimagus) built
    into it and no health control; confounded like MK7, so health stays open.
  - **MK24, drops per kill**: 10 lines at the rank-1 traced kill, 12 at the rank-4
    one, one kill each: recorded, not a verdict.

## Not established

- **Whether a boss follows the rank table in health.** Two sessions read one Karp
  King raised to rank 4 at ×5.65 (MK7) and ×4.73 (MK20), each with a different
  affix top-up built into the same health and no health control, so
  `HYPOTHESES["boss_hp_follows_rank_table"]` stays `None`.
- **Why a boss's damage rose past the table's row.** MK21's ×2.0968 is one boss,
  one spawn, with affixes other than the control's; whether the extra is the
  boss's own scaling, an affix's or one sample's spread is not established.
- **A boss at rank 3, and every boss but the Karp King,** for damage, XP and the
  drop rank: not measured. Nor MK2's protected drop values on a boss (the probe's
  unproven reads of `dCommonChance` and `dCommonDropMult` stayed 58 and 70 at
  rank 1 and rank 4; no check covered them), nor whether a raised boss drops more
  (MK13, MK24). The panel text, the README and the release notes claim only what
  was measured.
- **What `forceRarity` does.** Enemies carry a `forceRarity` variable beside
  `enemyRarity` (ForgePact's research probes read and write it); what in the game
  reads it, and when, is not known.
- **Which bosses the game itself spawns above rank 1**, if any. None is recorded
  here either way.
- **`EnemyRaritySettings`' own arithmetic.** The rank table is measured on the
  results, not read from the script, so a monster family that scales differently
  would not show in it.

## Our code

**ForgePact's Bosses control** (`bossrarity off|rare|ancient`, config key
`boss_rarity`, ForgePact#44, `ForgePact/plugin/include/ForgePact/BossRarityMod.hpp`):

- At the entry of the shared `EnemyRaritySettings` hook it writes `enemyRarity` 3
  (rare) or 4 (ancient) before the game's own setup runs.
- Only on a boss (an instance whose object descends from `Enemy_Child_Boss_obj`),
  only at rank 1, and never on a boss another monster created (a phase, a clone).
  A boss the game already made champion, rare or ancient keeps its rank; ordinary
  monsters are never touched by it.
- It tops the boss's affixes up to the tier's count (2 for rare, 3 for ancient)
  from the pool the Monster Rarity sliders use.
- Off by default; the sliders keep leaving bosses alone.

The test file expresses the rank change as `force_boss_rank(mode, ...)`, and
`LeverParityTests` pins it to the header's tier numbers and decision and to
`ForgePact/src/forgepact.py`'s `BOSS_RARITY_VALUES`.

## The model

A pure function of numbers, with exact fractions
([`monster_rank_model.py`](../../hs-game-sdk/python/hs_game_sdk/monster_rank_model.py)):

- `RANK_TABLE[rank]` for ranks 1-4: the health, damage and XP multipliers next to
  rank 1 (MK1), and `dCommonChance`, `dCommonDropMult`, `dSatanicDropMult` and the
  `dSlots` range (MK2). `row(rank)` returns one row and refuses anything but a
  whole rank 1-4.
- `scaled(rank, base_hp, base_damage, base_xp)`: a rank-1 monster's health, damage
  and XP taken to `rank`. Rank 1 returns the bases unchanged.
- `HYPOTHESES`: four entries, one per dimension a boss might or might not share
  with the rank table: `boss_hp_follows_rank_table`,
  `boss_damage_follows_rank_table`, `boss_xp_follows_rank_table` and
  `boss_drop_rank_reaches_dropitem`. Health is `None`, not established (MK7 and
  MK20 are confounded by the Bosses control's 3-affix top-up); damage is `False`
  (MK21), XP `True` (MK22) and the drop rank `True` (MK23). Each becomes a bool
  only from a measured row naming that dimension and a boss object, with its ratio
  to the boss's rank-1 self, and either nothing else changed on the boss or the
  row names the identity control that matched the top-up (`controlled_by`);
  within the control's tolerance of the table's ratio (damage 10%, XP 2%, health
  5%) follows it.
- `BOSS_PARENT` and `boss_family()`: `Enemy_Child_Boss_obj` and the names of its
  descendants in `hs-game-sdk`'s parent table, the objects a boss row may name.

Nothing draws a random number, so the kill mix (MK4) and the drop table (MK3) are
recorded but not modelled.

## What the model cannot catch

- **Whether the hook attaches,** and whether the write reaches the game's setup
  before it runs. Only a live `bossrarity status` line and a probe of the boss show
  that.
- **A boss's own scripted setup** after the rank is applied, if it has one.
- **How a boss feels in play**: its look, its affixes in action, its phases.
