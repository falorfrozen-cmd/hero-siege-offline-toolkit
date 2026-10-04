# Projectile amount, projectile speed and AoE size: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/skill_sliders_model.py`](../../hs-game-sdk/python/hs_game_sdk/skill_sliders_model.py),
tested by [`tests/test_skill_sliders_model.py`](../../tests/test_skill_sliders_model.py).
It was written for ForgePact#160 (hub #408), the research phase of three player
sliders: how many projectiles a skill fires, how fast they fly, and how large an
area skill is. It answers, for each, what the game does with the stat before a
hook changes anything, so the next workorder's sliders start from numbers rather
than a guess. The research behind it, with the candidate table and the live
procedure, is ForgePact's
[`docs/skill-sliders-research.md`](../../ForgePact/docs/skill-sliders-research.md);
this spec was written from that document's `## Static reading` only.

Every claim carries one of four labels, and a source:

- **Static reading**: read from the compiled game locally and written here in our
  own words. No script text is quoted or transcribed (`AGENTS.md` § "Legal").
  Unless a claim says otherwise, the reading is of the Sep-17 build
  (`Hero_Siege.exe`, 281,751,552 bytes), done on 2026-10-04.
- **Measured**: observed in a running game.
- **Our code**: what ForgePact does. The model leaves it out, and the test expresses
  it as an input transform.
- **Not established**: carried by the model as a parameter, or left out.

## Static reading

- **`ReturnSpecificStat` is the game's stat dispatcher**, a switch on its second
  argument, the stat id. Its case table has 186 cases; 77 of them call no `Stat*`
  script.
  - Id **554** goes to `StatAOESkillSize`, id **191** to `StatExplosionAOE` and id
    **196** to `StatAttackRangeMelee`, and each of those three has the dispatcher as
    its only direct caller found. So a hook on `StatAOESkillSize` sees every read of
    stat 554 that goes through the dispatcher.
  - The projectile-amount ids have no `Stat*` script: id **394** has a case with no
    `Stat*` callee, and ids 311, 239, 240, 451 and 452 have no case.
  - The projectile-speed ids **74** and **75** have no case; their value comes from
    the dispatcher's default handling, which was not read in full.
- **AoE size.**
  - `StatAOESkillSize` returns a four-element array whose element 0 is the total:
    a sum of several of the player's buff values, plus stat **560**, plus, on one
    branch, stat **559**. No cap was found in it.
  - `LoadAOEModifiers` reads stat 554, scales it by 0.01 and by its sixth argument,
    and adds the result to element **1086** of the modifier array it fills. When its
    fourth argument is true it does the same for stats **552** and **553**. The same
    reads, and fourteen writes to element 1086, also sit inside `LoadAllModifiers`.
  - `LoadProjectileSettings`, when the calling instance's `projEffect[1086]` is above
    0, adds that value to both `image_xscale` and `image_yscale`. So AoE size
    reaches a projectile as an **additive** change of its scale: 100 points of stat
    554, with a factor of 1, add 1.0.
- **Projectile amount.**
  - `ReturnExtraSpellProjectiles(player, x, base)` returns the **adjusted total**.
    Stat **394** raises `base` by a percent, with the result floored, and stat
    **311** is added on top. The percent's 0.01 is a named global whose value was
    inferred from its use.
  - `ReturnExtraProjectilesRanged(player, x)` returns the **extra count only**: a
    flat stat (**239**) plus up to two chance-based bonuses, one worth stat **452**
    with its chance from stat **451** (for some skills only), and one worth a single
    projectile with its chance from stat **240**. The caller adds the result to its
    own base.
  - Both are called from the `Talents<Class>` scripts (44 and 19 direct sites
    found), so one native detour on each reaches every skill that asks it.
- **Projectile speed.**
  - `LoadAllModifiers` writes element **1085** of the modifier array right after the
    dispatcher returns stat **75**, and element **1084** right after stat **74**.
    Whether it stores the stat as read or scaled was not read.
  - `LoadProjectileSettings` changes the projectile's `deltaSpeed`, not the `speed`
    built-in. Stat 75 (element 1085) acts on it as a percent multiplier and stat 74
    (element 1084) as a flat addition scaled by `roomSpd`, a global speed factor.
    So stat 75 is the multiplicative form and stat 74 the flat form. The order in
    which the two combine is not a reading here.
  - `TalentUseSetSpeed` is cast speed (stats 68, 69 and 106), not projectile speed.
- **Skill objects that are not projectiles** (read after the first live session).
  - A White Mage talent creates its own objects, parented under
    `Player_Damage_Parent_obj` or `Player_Ability_Parent_obj`, and does not reach
    `LoadProjectileSettings`, which belongs to `Projectile_Player_obj` (the class
    basic attack's object).
  - An event of each of those two parents applies the same arithmetic to its own
    instance: element 1085 scales `deltaSpeed` and element 1084 adds to it, both
    only while `deltaSpeed` is above 0; element 1086, when above 0, is added to
    `maxScale` if that is non-zero, and otherwise to both `image_xscale` and
    `image_yscale`. So `projectile_scale` below describes these objects too, when
    their `maxScale` is 0.
  - The modifier list reaches such an object through `SetAllModifiersNew`, which
    the talent script calls after creating it. The Healing Zone's branch makes no
    such call, and the zone clamps its own drawn scale to 1.5, so AoE size does
    not reach it.

## Measured

ForgePact#160's three live sessions (2026-10-04, Sorak, a White Mage, research
build sha256 `e9064f6a…5603c3`); the research doc's `## Live 1` has every check.
The rows are in
[`hs-game-sdk/curated/skill_sliders_measurements.json`](../../hs-game-sdk/curated/skill_sliders_measurements.json),
and `MeasuredTests` checks each against the model.

- **Projectile amount** (Shadow Bolt): `ReturnExtraSpellProjectiles` called with a
  base of 1 returned 1 and one bolt appeared, three times; with 2 added to its
  return, 3 bolts appeared, twice. The helper's total is the bolt count.
- **AoE size** (Soul Spurn): stat 554 read 0 and the object's `projEffect[1086]` 0,
  with both image scales 7.5; with 50 added to stat 554, element 1086 read 0.5 and
  both scales 8.0. So the net factor on this path is 1 on 0.01 per point, and the
  element is added to the scale. Mana Orb showed the same (1.15 to 1.65), though
  its check was left inconclusive. The Healing Zone, with stat 554 at 50, read
  element 1086 0 and scale 1.5.
- **Projectile speed** (Shadow Bolt, `deltaSpeed` 2.916667 at baseline, which the
  rows read as 35/12): stats 74 and 75 read 0 on this character. Stat 75 raised
  to 0.5 and to 50 gave ×1.005 and ×1.5, so element 1085 is the stat times 0.01.
  Stat 74 raised to 0.5 and to 50 added 0.208333 and 20.833333, so each point adds
  5/12 (0.416667) to `deltaSpeed`, an absolute amount and not a fraction of it,
  linearly; how that splits between a stored scale and
  `roomSpd` was not separated. On every read the `speed` built-in equalled
  `deltaSpeed` times the object's `deltaTimer`.

## Our code

No lever ships in this phase. The research build's `projprobe` carries three
research-only levers, and the test expresses each as an input transform that the
next workorder's sliders will pin: `projprobe amount <k>` adds `k` to the return of
both extra-projectile helpers; `projprobe aoe <bonus>` adds `bonus` to element 0 of
`StatAOESkillSize`'s result (so to stat 554); and `projprobe speed <mult>` multiplies
the projectile's own `deltaSpeed` (and its `speed`) after `LoadProjectileSettings`
returns, while `projprobe speed stat <id> <mult>` multiplies what the dispatcher
returns for stat `<id>` while `LoadAllModifiers` or `LoadProjectileSettings` is on
the stack, and `projprobe speed stat <id> add <bonus>` (0..100) adds to it instead.
The additive form exists because a character with no projectile-speed gear reads 0
for stats 74 and 75 (measured on Sorak), and a multiplier cannot move a 0;
`projprobe` counts such a call as a no-op, not as applied. The live sessions used
the additive form.

## Not established

- **What the dispatcher returns for stats 74 and 75** when a character carries
  them (they have no case; 0 was read with none), and which branch rounds a
  result down on the way out.
- **Which of 74 and 75 is the tooltip's "Projectile Speed"** line. The model takes
  the two storage scales as parameters with no default; the rows pass 1 for stat
  74 with the measured 5/12 as `room_spd`, and 0.01 for stat 75.
- **How stat 74's 5/12 per point splits** between the scale `LoadAllModifiers`
  stores it with and `roomSpd`, and whether it holds in other rooms.
- **The factor callers pass as `LoadAOEModifiers`' sixth argument**, whether stats
  552 and 553 apply to a given skill, and how `LoadAllModifiers` scales stat 554 in
  general (the net 0.01 per point is measured on two White Mage skills). The model
  takes the factor as a parameter.
- **What stats 559 and 560 are**, which skills `LoadAllModifiers` reads stat 554
  for, and what element 1086 does on an object whose `maxScale` is non-zero.
- **How a class other than the White Mage uses the projectile count** (loop count,
  spread width or cap). `ReturnExtraProjectilesRanged` was not observed live.
- **The scale of the chances** in `ReturnExtraProjectilesRanged`, and which skills
  qualify for the 451/452 bonus. The model takes each bonus's outcome as a boolean.
- **The order in which stats 74 and 75 combine on `deltaSpeed`** (they were not
  raised together), and what either does below 0. The model takes the order as a
  parameter with no default.
- **The instance form on a `Projectile_Player_obj`**: no basic attack was seen.
- **How a lever keeps to the player's own casts**: the mercenary, a base-6 helper
  call that rides along with casts, and the double-cast proc reach these routes
  (measured); summons and NPCs whose Create closures call `LoadAllModifiers` were
  not observed.

## The model

A pure function of numbers, with exact fractions
([`skill_sliders_model.py`](../../hs-game-sdk/python/hs_game_sdk/skill_sliders_model.py)):

- `spell_projectile_total(base, more_percent=0, extra=0)`: what
  `ReturnExtraSpellProjectiles` returns. `base`, floored after the stat-394 percent
  when that is above 0, plus stat 311.
- `ranged_extra_projectiles(flat, bonus=0, bonus_rolled=False, one_more_rolled=False)`:
  what `ReturnExtraProjectilesRanged` returns, as one sum: stat 239, stat 452 if its
  chance came up, and one if stat 240's chance came up. The outcomes are inputs;
  nothing here draws a random number.
- `ranged_projectile_total(base, extra)`: the caller's base plus that extra.
- `aoe_scale_bonus(stat554, factor=1, also=())`: what one `LoadAOEModifiers` pass
  adds to element 1086 (each stat × 0.01 × `factor`).
- `projectile_scale(base_scale, element_1086)`: the scale `LoadProjectileSettings`
  leaves, or a skill object's parent event when its `maxScale` is 0, the element
  added only when it is above 0.
- `stored_speed_elements(stat74, stat75, flat_scale, percent_scale)`: elements 1084
  and 1085, each stat times a scale that is not established.
- `projectile_delta_speed(delta_speed, percent_element=0, flat_element=0, room_spd=1, *, order)`:
  the `deltaSpeed` `LoadProjectileSettings` leaves, the percent as a multiplier of
  `1 + percent_element` and the flat part as `flat_element × room_spd`, combined in
  the `order` given (`"multiply_first"` or `"add_first"`), since the order was not
  measured.

## What the model cannot catch

- **Whether a hook attaches.** Every script above is called directly
  (`call rel32`), so only a native detour runs; only a live first-call line shows
  that it fired.
- **Whether a skill reaches these scripts at all.** Some skills may build their
  count, scale or speed without the helpers; the model only says what the helpers
  do when asked.
- **How a count, a scale or a `deltaSpeed` looks in play**: spread, collision masks,
  frame timing and `roomSpd` in a given frame.
