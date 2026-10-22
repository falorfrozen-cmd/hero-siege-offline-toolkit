# The Mark 1 automation's proc interval and mana cost: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/mark1_automation_model.py`](../../hs-game-sdk/python/hs_game_sdk/mark1_automation_model.py),
tested by [`tests/test_mark1_automation_model.py`](../../tests/test_mark1_automation_model.py),
with the shared cases in
[`hs-game-sdk/curated/mark1_automation_cases.json`](../../hs-game-sdk/curated/mark1_automation_cases.json).
It was written for ForgePact#166 (the Mark 1 set). With all four pieces worn
and the set bonus on, the automation can fire the Q, E, R and Y skills the
way the game fires an item proc: straight into the skill, with no cast time
and outside the input gate. The owner asked for two things on that route
(2026-10-22): each skill fires at an interval computed from its cooldown and
the player's cast speed, and a mana cost makes up for procs that cost no
mana. This spec answers how long the interval is, and what the cost does to
a character's mana. The reasoning and the live sessions are in the research
doc, [`ForgePact/docs/mark1-set-research.md`](../../ForgePact/docs/mark1-set-research.md).

Every claim carries one of four labels, and a source:

- **Static reading**: read from the compiled game locally and written here in our
  own words. No script text is quoted or transcribed (`AGENTS.md` § "Legal").
  The readings are of the Sep-17 build (`Hero_Siege.exe`), done on 2026-10-22.
- **Measured**: observed in a running game.
- **Assumption**: a number the model needs that nobody has read or measured yet.
  It is a named constant, so a measurement replaces it in one place.
- **Not established**: carried by the model as a parameter, or left out.

The shared game facts live in
[`docs/RUNTIME_DATA_MODELS.md`](../RUNTIME_DATA_MODELS.md):
§ 7.5 (Skill Haste) and § 7.10 (the skill bar's buttons, mana and the cast's
speed).

## Static reading

- **The stat dispatcher's ids.** `ReturnSpecificStat` sends id **37** to
  `StatMaxMana`, **42** to `StatManaReplenish`, **46** to `StatManaPerKill`,
  **103** to `StatSpellHaste` and **106** to `StatFasterCastRate`.
- **Skill Haste shortens a cooldown** by dividing it by `1 + haste / 200`
  (RDM § 7.5; the formula is the hub's `skill_stat_model`, and the cap is
  measured, below). `GetTalentCooldown`, which sets a cooldown's starting
  time, reads no Skill Haste itself: the haste is applied while the cooldown
  runs down.
- **The cast's speed.** `TalentUseSetSpeed` (read in part) takes the Faster
  Cast Rate answer (id 106) as a fraction of 100, adds the talent's own
  sub-talent cast-speed bonuses, and divides a per-talent base time by one
  plus that sum. So the cast time has the shape `base / (1 + fcr / 100)`.
  The stat's own description in the item semantics file says Faster Cast
  Rate is always counted from one cast a second (item keys 196 and 197),
  which is where the provisional base of 1 s comes from.
- **When a key cast's cooldown starts.** The same script reads the talent's
  cooldown first and, when it is above a small threshold, starts the
  cooldown at the beginning of the wind-up. So holding the key repeats a
  cooldown skill at about the longer of its cooldown and its cast time, not
  their sum. The owner's rule (the sum) paces a proc a little slower than a
  held key.
- **Where mana lives.** `PlayerManaUpdate` keeps the player's mana in the
  game's protected store and compares the value it finds with the last of
  its 100 recorded samples (`manaArray`); on a mismatch it takes a call
  stack and can report it. So a mana value changed outside the game's own
  update is plausibly detected, and the cost never writes mana. It changes
  only what the stat dispatcher answers.
- **The replenish.** `StatManaReplenish` (read in part) builds the
  replenish from Energy (id 20, 0.175 a point) and from ids 43, 37, 44 and
  309, multiplying id 43's answer by maximum mana when it is above zero, and
  adds the player's buffs. So the base replenish follows Energy, and maximum
  mana enters only through id 43's part.
- **Energy** gives 4 maximum mana a point (item keys 38 and 39).

## Measured

- **No cooldown.** A talent whose `abilityCooldown` reads 0.25 s has no
  cooldown (RDM § 7.1). The model treats anything at or below 0.25 s as 0.
- **The Skill Haste cap.** The game counts at most 200 Skill Haste, so a
  cooldown takes at least half its base time (ForgePact#114 Live 1, RDM
  § 7.5, `skill_stat_measurements.json`).
- Nothing about the proc interval or the mana cost has been measured yet.
  Live 1 of the Mark 1 playtest measures the key-hold interval at two Faster
  Cast Rates, Healing Zone's interval, the replenish answer's unit and
  whether a replenish below zero drains (the research doc's Live procedure
  1: `cast-interval`, `cast-interval-fcr`, `proc-cd`, `regen-units`,
  `drain-applies`).

## Assumption

- **The base cast time is 1.0 s** for every skill (`BASE_CAST_SECONDS`).
  Live 1's decision sets it (`cast-base:`).
- **One unit of the replenish answer is one mana a second**
  (`REPLENISH_UNIT`, Live 1 `regen-units`).
- **The reference character**: 1500 maximum mana and a base replenish of
  2.0% of maximum mana a second with no investment. Energy gives 0.175
  replenish for 4 mana, which is 4.4% of the mana it gives a second; if
  about half the pool comes from Energy, that is about 2%.
- **The reference investments**: +100% Replenish Mana (+2.0% a second, if it
  scales the base replenish), +20 Mana per second (+1.33%), and +10 Mana
  After each Kill at one kill a second (+0.67%).
- **The proposed numbers are the owner's call**: a drain of 1.0% of maximum
  mana a second per automated skill (half the assumed baseline replenish),
  and, for the alternative, a 20% cut of maximum mana per automated skill.

## Not established

- **The per-talent base cast time**, and each talent's sub-talent cast-speed
  bonus. The model takes the base as a parameter.
- **Whether `GetTalentCooldown`'s base differs from `abilityCooldown`** for
  some talents (sub talents). Live 1's `proc-cd` checks it on Healing Zone.
- **Whether Replenish Mana % scales the base replenish.** The model assumes
  it does.
- **What id 43 is.** Plausibly a share of the pool; not read.
- **Whether a replenish below zero lowers mana or stops at zero**
  (Live 1 `drain-applies`). The model gives the answer the consumer returns
  and the net a second as if it lowers mana.
- **Current mana.** It is in the protected store and not read, so the model
  starts from a full pool and nothing pauses the automation at zero mana.

## The model

A pure function of numbers, with exact fractions
([`mark1_automation_model.py`](../../hs-game-sdk/python/hs_game_sdk/mark1_automation_model.py)):

- `cooldown_seconds(ability_cooldown, haste)`: 0 when the cooldown is at most
  0.25 s, otherwise the cooldown times `skill_stat_model.cooldown_fraction(haste)`.
- `cast_seconds(fcr, base_cast_seconds=1)`: `base / (1 + fcr / 100)`, the
  divisor never below 0.1 (our code: a Faster Cast Rate of -100 or less never
  divides by zero or goes negative).
- `interval_ms(ability_cooldown, haste, fcr, base_cast_seconds=1)`: the two
  added, in milliseconds. Before the plugin has read either stat it uses 0
  for both, which is the longest interval.
- `drain_per_second(proc_columns, percent, max_mana, unit=1)`: how much the
  drain takes off the replenish answer, `columns × percent / 100 × max × unit`.
- `replenish_answer(original, proc_columns, max_mana, percent=1, unit=1)`:
  the answer the set's consumer gives for id 42, the original less the drain
  and never below minus the maximum. No proc column leaves the original.
- `cut_max_mana(proc_columns, cut_pct, max_mana)`: the alternative's answer
  for id 37, the maximum less `cut_pct` % per automated skill, never below 0.
- `regen_per_second(...)`, `net_mana_per_second(max_mana, base_regen_pct,
  replenish_pct, mana_per_second, mana_per_kill, kills_per_second, drain)`,
  `is_sustained(net)` and `seconds_to_empty(max_mana, net)`: what the drain
  leaves a character with, from a full pool.

Only proc columns pay: a toggle keeps the press and pays its own mana, and
on the press route the game's own casts pay the game's own mana.

What the proposed numbers give the reference character
(`tests/test_mark1_automation_model.py` checks every row):

| drain per skill | skills | at baseline (2%) | one investment | two investments |
|---|---|---|---|---|
| 1.0% | 1 or 2 | sustained | sustained | sustained |
| 1.0% | 4 | empty in 50 s | Replenish +100% exactly carries it; per second alone 150 s, per kill alone 75 s | sustained |
| 1.25% | 4 | empty in 33 s | 43 to 100 s | Replenish + per second sustains; the others 100 to 300 s |
| 0.75% | 4 | empty in 100 s | sustained, except per kill alone (300 s) | sustained |

The rule behind the proposal: the drain per skill is half the baseline
replenish, so two automated skills cost what the character regenerates and
four cost twice that. One or two sustain themselves, four empty a full pool
in about 50 s, one weaker investment does not carry four, a strong
Replenish roll exactly does, and any two of the three do.

The alternative, at four skills, leaves 300 of 1500 maximum mana. The procs
stay free, so nothing has to be sustained, and the price falls only on the
player's own casts.

The cases file holds the interval (no cooldown, Healing Zone's 14 s at
haste 0, 100 and 300, Faster Cast Rate -50, 0, 100 and the floor), the drain
(0 to 4 skills at 1% of 1500, and an overridden percent on a pool of 100000
where the floor at minus the maximum decides the answer) and the cut (0 to 4
skills). ForgePact's C++ cores are tested against the same file.

## What the model cannot catch

- **Whether a proc fires at all**, or whether the game treats it as an item
  proc. Only a live counter shows that.
- **The game's own frame timing.** The plugin checks due times once a frame,
  so a proc lands up to a frame after the model's interval.
- **How the drain feels in play**, and whether the game's mana update
  accepts a replenish below zero.
- **Stat reads.** The plugin reads haste, Faster Cast Rate and maximum mana
  at most once a second, so a change of gear reaches the interval up to a
  second late.
