# How Skill Haste and All Skills reach a skill: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/skill_stat_model.py`](../../hs-game-sdk/python/hs_game_sdk/skill_stat_model.py),
tested by [`tests/test_skill_stat_model.py`](../../tests/test_skill_stat_model.py).
It was written for ForgePact#114 (hub #337), which ports Stat Forge's **Skill
Haste** and **All Skills** boosts into ForgePact's `statadd`. It answers two
questions a slider needs answered before it ships: how fast a cooldown runs out
for a given Skill Haste, and which skills an All Skills bonus raises.

Every claim carries one of four labels, and a source:

- **Static reading**: read from the compiled game locally and written here in our
  own words. No script text is quoted or transcribed (`AGENTS.md` § "Legal").
  Unless a claim says otherwise, the reading is of the Sep-17 build
  (`Hero_Siege.exe`, 281,751,552 bytes), done on 2026-09-30.
- **Measured**: observed in a running game.
- **Our code**: what ForgePact does. The model leaves it out, and the test expresses
  it as an input transform.
- **Not established**: carried by the model as a parameter, or left out.

## Static reading

- **`ReturnSpecificStat` is the game's stat dispatcher.** Its second argument is a
  stat id, and a switch sends each id to one `Stat*` script. The switch's case
  table is filled in by the function itself the first time it runs; it was read
  from that setup code.
  - Stat id **103** goes to `StatSpellHaste`, id **2** to `StatAllSkills` and id
    **106** to `StatFasterCastRate`. Ids 36 and 37 go to `StatMaxLife` and
    `StatMaxMana`.
  - `StatSpellHaste` and `StatAllSkills` each have exactly one direct caller,
    `ReturnSpecificStat`. So a hook on either script sees every read of that stat
    that goes through the dispatcher.
- **Skill Haste sets how fast a skill's cooldown runs out.**
  - `Controller_obj`'s Step event walks the active cooldowns. For each one it lowers
    the time left by `(1 + rate) × deltaSpd` every step. `deltaSpd` is a global
    game-speed factor.
  - For a skill's cooldown, `rate` is Skill Haste (stat 103, element 0 of
    `StatSpellHaste`'s result) × 0.005.
  - The same loop has a second branch, taken for entries of another kind. There
    `rate` is stat 105 × 0.01. Stat 105 has no case in the dispatcher's table.
  - One cooldown id, 75, always takes `rate` 0.
  - So a cooldown lasts its base time divided by `1 + haste / 200`. 100 Skill Haste
    makes a cooldown take 2/3 of its base time, and 200 makes it take half.
  - Nothing in this step caps Skill Haste or sets a floor on the rate. The cap of
    200 that Live 1 measured (see Measured) is applied somewhere else, after
    `StatSpellHaste` returns: `ReturnSpecificStat` works with elements 0 to 3 of
    an array result on its way out, which was not fully read.
  - The step reads Skill Haste once per active skill cooldown per step.
- **The talent tooltip reads Skill Haste too.** It is the only other direct use of
  stat 103 found. It scales the value by 0.01 and then by 0.5, which is the same
  0.005 per point.
- **`ReturnTalentLevel` adds All Skills only to a talent with points, but nothing
  calls it directly.**
  - Its body reads a talent's allocated level first. Only when its third argument
    is true, and the allocated level is above 0, does it add the bonuses it reads
    through `ReturnSpecificStat`. All Skills (stat 2) is one of them.
  - It has no clamp: no `min`, and no constant like 20. Stat Forge's reading of the
    7.0.5.0 build found the same.
  - A direct-call scan of the Sep-17 build finds no caller of `ReturnTalentLevel`
    at all. Many scripts pass stat id 2 to `ReturnSpecificStat` themselves (the
    cast and class-talent scripts among them), so the level a cast uses is built
    elsewhere. Live 1 measured that it does include All Skills (see Measured);
    whether it too leaves a talent with no points at 0 is not established.
  - Allocating points is what puts a skill on the bar at all; All Skills allocates
    none, so it cannot unlock a skill.
- **Both scripts return an array whose element 0 is the total.** `StatSpellHaste`
  and `StatAllSkills` build the array fresh on every call.

## Catalog reading

From the item editor's item catalog (`hero-siege-item-editor/hs_full_catalog.json`),
the range the game's own items give:

- **"Skill Haste Increased by"** reaches 150 on one item (Divine Crackpipe) and
  20–50 on ordinary uniques (for example Gabriel's Dauntless Vision, 30–50).
- **"All Talents"**, which the game shows as "to All Skills", reaches 70 on
  Divine Crackpipe and 25 on a developer charm. Ordinary items give at most 15
  (Tayrel's Chestplate, 7–15).

## Measured

- **Stat Forge, 7.0.5.0, 2026-08-29.** Skill Haste came back as `12 + 100 = 112`
  over 631 live calls, with Stat Forge adding to element 0 of `StatSpellHaste`'s
  array (`hs-stat-forge/STATFORGE_S10_REAL_STAT_HOOK_NOTES.md`). Its additive All
  Skills mode (v2.5.0) was never verified live.
- **ForgePact#114 Live 1, 2026-09-30**
  ([`skill_stat_measurements.json`](../../hs-game-sdk/curated/skill_stat_measurements.json),
  S1 and S2, checked by `MeasuredTests`).
  - **Setup.** The #114 research build on Suh, a level-100 Samurai with 40 Skill
    Haste from gear, in town. Blade Barrier (talent 137, `abilityCooldown` 8 s,
    level 1) was cast from code, by `TalentUse` with self `Player_obj`.
  - **Method.** The cooldown was counted as the reads of Skill Haste that
    ForgePact's hook saw while it ran, the hook installed as a pass-through first
    so the no-bonus runs count too.
  - **Reads.** One per step, 60 a second, while the cooldown ran, and none while
    nothing did.
  - **Bonus 0.** 392 and 397 steps. The hook's first-call line of the next run
    read the character's own total, 40.
  - **Bonuses.** +100: 280 steps; +120: 265; +160 (total 200): 238; +200 (total
    240) and +300 (total 340): 238 each. The hook returned 140 and 340 on its
    first calls, so the game received those totals and counted 200.
  - So `base / (1 + min(total, 200) / 200)`, within 2.5%, with a base of about 473
    steps.
  - **Calling `ReturnTalentLevel` by name** with only a talent id raised the runner
    error "I32 argument is undefined" 17 times (`skillprobe state`); the game
    carried on.
- **ForgePact#114 Live 1, session 2, 2026-10-01** (A1 in the same file).
  - **Method.** For Honor (talent 142, one point allocated) was cast from code with
    `statadd allskills` at 0 and then at +19, and the buff it adds (buff type 42)
    was read, its `buffValue`.
  - **The stat.** The hook's first-call line read the character's own All Skills
    total, 28, and returned 47.
  - **The level.** The buff was [137.8, 72.5, 0] at 0 and [228, 120, 0] at +19.
    Both are the level times [4.75, 2.5], at level 29 (1 point + 28) and 48
    (29 + 19). So All Skills joins the level a cast uses, and the +19 reached it.
  - **No cheat report.** `ReportClient` was never called, on `skillprobe`'s row with
    its controls climbing.
  - **The save.** After a clean close it differed from the copy taken before the
    session only in `playtime` and the class's time (`shop.ini`
    `class_time8`).

## Our code

**ForgePact's `statadd`**, from ForgePact#114:

- `statadd skillhaste N` adds N to element 0 of `StatSpellHaste`'s result, on a
  copy, after the game's own calculation. So gear and buffs keep stacking under it.
  The panel's slider stops at 200, the measured cap, which a character with no
  Skill Haste of their own reaches at its top.
- `statadd allskills N` does the same for `StatAllSkills`. N is rounded to whole
  levels and capped at 100.
- Both need the native detour: a table-only install is refused.

The test file expresses both as transforms of the stat total, and
`LeverParityTests` pins them to ForgePact's source.

## Not established

- **What the second cooldown branch covers.** It is plausibly flask cooldowns with
  the Flask Skill Haste item stat, but no live run has shown that. The model
  covers skill cooldowns only.
- **`deltaSpd`'s value** in a given frame. The model counts in steps of 1 and takes
  `deltaSpd` as a parameter.
- **Which script builds the level a cast uses.** Live 1 measured that it includes
  All Skills; the script was not identified.
- **Where the Skill Haste cap is applied**, and whether its value comes from the
  stat array (Movement Speed's array, `[305.1, 0, 0, 600]`, suggests element 3 is
  a limit).
- **Talent levels far above the game's own range.** Tables indexed by level, summon
  counts and tooltips have not been checked above +70. That is why `statadd` stops
  All Skills at 100.
- **Indirect calls.** A script can also be called by index, for example with
  `script_execute`, and a direct-call scan cannot see that.

## The model

A pure function of numbers, with exact fractions
([`skill_stat_model.py`](../../hs-game-sdk/python/hs_game_sdk/skill_stat_model.py)):

- `effective_haste(haste)` = min(haste, 200), the measured cap.
- `recovery_rate(haste)` = 1 + `effective_haste(haste)` / 200: how much cooldown time
  one step removes, with `deltaSpd` 1.
- `cooldown_fraction(haste)` = 1 / `recovery_rate(haste)`: the part of its base time
  a cooldown takes, never below 1/2.
- `cooldown_steps(base_steps, haste, delta_spd=1)`: the steps a cooldown of
  `base_steps` takes to reach 0 or less.
- `talent_level(points, all_skills, other_bonus=0, include_bonuses=True)`: the
  allocated level, plus the bonuses only when they are asked for and the talent
  has points.

## What the model cannot catch

- **Whether a hook attaches.** Both scripts are only ever called directly
  (`call rel32`), so only the native detour runs. Only a live first-call line
  shows that it fired.
- **How often the game reads a stat.** The model takes a haste value per step as
  given; the call rate is a runtime question.
- **Frame timing, `deltaSpd`, and how a boost feels in play.**
