# The two-stage drop roll: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/drop_roll_model.py`](../../hs-game-sdk/python/hs_game_sdk/drop_roll_model.py).
The model is checked against the numbers in
[`hs-game-sdk/curated/drop_roll_measurements.json`](../../hs-game-sdk/curated/drop_roll_measurements.json)
by [`tests/test_drop_roll_model.py`](../../tests/test_drop_roll_model.py). It was
built for the pilot in issue #162. How the workflow is meant to be used, and what
the pilot showed, is in
[`docs/agents/static-model-workflow.md`](../agents/static-model-workflow.md).

Every claim below carries one of three labels, and a source:

- **Static reading**: read from the compiled game locally and written here in our
  own words. No script text is quoted or transcribed (`AGENTS.md` § "Legal").
- **Measured**: observed in a running game.
- **Our code**: what ForgePact's own code does. The model leaves this out; the test
  expresses it as input transforms.

A claim that is none of these is under "Not established", and the model carries it
as a parameter.

Measured entries are cited by their fixture id (M1–M10). All of them were recorded
before 2026-09-12, when `HookOneScript` was still table-only (ForgePact guide,
Known Limitations item 12). So they are rates per call *that the hook saw*, not a
census of every call the game made. The gate arithmetic needs only the per-call
rate, and for M2 the reason that rate holds is worth stating. Its denominator,
1233, counts our own re-calls of `LoadDrops`, so it is complete. Its numerator,
95, is the `c=N` counter of a table-only `DropDungeonKeys` hook, so it is
complete only if the type-12 branch reaches `DropDungeonKeys` through the table.
The counter read 95, not 0, so the hook did see that path. That it saw every
call on it rests on 95 agreeing with `chances[11]` of 5–9 at about 100 outcomes,
which is the same agreement the die-size inference below uses, so the two are
not independent. And no count here says how often the game reached a script by
some other route.

## Static reading

- **The outer gate is a whole-number die against a per-type chance.** For each drop
  type a monster lists, `gml_Script_LoadDrops` draws a whole number from its own
  die. It calls that type's `Drop*` script only when the draw is below the
  monster's chance for the type. The chances arrive as `LoadDrops`' argument 8, a
  70-slot array indexed by drop type. Source:
  [`ForgePact/docs/dungeon-key-research.md` §1](../../ForgePact/docs/dungeon-key-research.md#1-neden-düşmüyor--tek-cümle);
  [`RUNTIME_DATA_MODELS.md` §13.1](../RUNTIME_DATA_MODELS.md#131-drop-types-loaddrops).
- **Four key types share one gate shape and one die range.** Types 11
  (`DropKeys`), 12 (`DropDungeonKeys`), 31 (`DropBifrostKey`) and 40
  (`DropChaosKey`) are built the same way and read the die's range from the same
  place, a member of `gDataProtected` that the game fills at runtime. Source: the
  same two documents.
- **The die is the game's own generator.** The gate's draw goes through
  `gml_Script_cpr_irandom`, which draws from `gml_Script_cpr_rand32` rather than
  the runtime's builtin RNG. Source: the planning pass of 2026-09-24, kept local.
- **Dungeon keys: uniform pick, then the key's own base.** After its gate,
  `DropDungeonKeys` picks one key uniformly from the list `GetDungeonKeys`
  returns. It takes that key's rate from its repository record
  (`GetNormalRepoStruct`, category 12) and adjusts it by a factor read from
  chances slot 13 (0.7 natively, 1 when the slot is empty). A luck term and some
  optional arguments also enter. It reduces the result to a whole number, draws
  against it, and on a hit places the key with `LootGroundCreate`. Source:
  [dungeon-key-research, "Zincirin tamamı"](../../ForgePact/docs/dungeon-key-research.md#zincirin-tamamı-açıldıktan-sonra-hepsi-oyunun-kendi-kodu);
  the 2026-09-24 pass confirmed the uniform pick, the slot-13 factor and its
  default of 1.
- **An item's `droprate.base` is a "1 in N" value**: larger means rarer. Source:
  [`RUNTIME_DATA_MODELS.md` §3](../RUNTIME_DATA_MODELS.md) and ForgePact's README,
  "Drops are **not forced**".

## Measured

- **A chance of 0 never passes the gate.** Monsters that drop ordinary keys had
  `chances[12]` = 0 in 200 of 200 `LoadDrops` calls, and type 12 never appeared
  (M1, 2026-08-27).
- **An opened gate passes at about the monster's own key chance.** With
  ForgePact's `dungeonkey` hook copying `chances[11]` (5–9 on those monsters) into
  slot 12, 95 of 1233 extra type-12 rolls passed, about 7.7%. A forced gate would
  have passed all 1233 (M2, 2026-08-27).
- **The inner roll decides the rest.** At the keys' vanilla base of 1500, 95
  `DropDungeonKeys` calls gave no key. At base 50 the record says "~2", without
  saying whether that was observed or computed. At base 3 keys became visible
  (M3–M5, 2026-08-27).
- **The draw is a whole number, so chances in (0, 1] are all the same gate.**
  v1.2.1 scaled the relic gate chance by 0.05 and then by 0.001. Relics were not
  reduced: they were 30% and then 69% of dropped items (M6, 2026-08-28).
- **`DropRelic`'s drop is not a 1-in-`droprate.base` roll.** All 156 relics
  carried base 25,000,000, yet relics dropped constantly (M7, 2026-08-28). So
  dividing every relic's base by the same factor (the `droprate group relic`
  lever) changed nothing observable, and the relic family has a gate but no
  1-in-base inner roll. Whether the base is read some other way is not
  established (see below).
- **The relic share of dropped items under each pre-roll** (M8, 2026-08-28). This
  is recorded, but the model cannot reproduce it: see "What the model cannot catch".
- **Squaring the lever flooded drops.** 1.3.10–1.3.12 applied the slider to both
  the gate and the inner roll. Players reported it on 2026-09-07. 1.3.13 took the
  gate multiplier back to 1 for every family except relic (M9).

## Not established

- **The number of die outcomes, N.** The range is filled at runtime, so a static
  reading cannot give it. Native chances run from 1 to 100, and 100 is used as a
  certain drop, which suggests N = 100. Whether the top value is included is also
  open. The model's default is 100, marked as a hypothesis. M2 is consistent with
  100 and rules out 10 and 1000.
- **The inner adjustment, s.** This covers whether the slot-13 factor makes a key
  more or less likely, and the form of the luck term. The 2026-09-24 pass did not
  follow the code that far. The model carries the whole adjustment as one scale `s`
  (default 1, a hypothesis). The M3–M5 checks hold for `s` in {0.7, 1, 1/0.7}.
- **Whether `DropRelic` reads `droprate.base` at all**, for example as a weight
  in the pick between relics. M7 cannot tell: every relic carried the same value,
  and a weighted pick over equal weights looks exactly like a uniform one, as does
  one divided by the same factor throughout. No run changed a single relic's
  base, which is the control that would settle it. Only relic drops were
  observed, not the other direct callers of `DropRelic`
  ([RUNTIME_DATA_MODELS §5](../RUNTIME_DATA_MODELS.md)).
- **What `DropRelic` does after it runs**: which relic it picks, and any filter.
  This is not modelled.

One trace would pin both N and `s`: log the gate's draw range and the dungeon-key
inner bound on one monster that lists type 12 natively. It would also be the
positive control for any later measurement. It is described here, not planned.

## The model

A pure function of numbers, deterministic and analytic
([`drop_roll_model.py`](../../hs-game-sdk/python/hs_game_sdk/drop_roll_model.py)):

- `gate_probability(chance, N)` is 0 when the chance is ≤ 0. Otherwise it is
  `min(1, ceil(chance) / N)`, because a whole-number draw passes on `ceil(chance)`
  of the N outcomes.
- `inner_probability(base, s)` = `min(1, s / base)`.
- `dungeon_key_call_probability(key_bases, s)` is the mean of the keys' inner
  probabilities, because the pick is uniform. `dungeon_key_probability` multiplies
  that by the gate.
- `relic_roll_probability(chance, N)` is the gate alone. It takes no base on
  purpose, because the measured fact is that no 1-in-base roll follows the gate.
  That also makes a uniform divide of every relic's base a no-op in the model,
  which holds whether or not the base weights the pick between relics.
- Binomial helpers (`binomial_band`, `observation_within`,
  `consistent_die_outcomes`) let a test compare a recorded count with a
  predicted probability.

**ForgePact's levers are our code**, so they stay out of the SDK. The test file
defines them as transforms of the model's inputs:

- `droprate group <family> m` stores each item's vanilla base on first touch. It
  then writes `max(1, vanilla / m)`, or the vanilla value when `m ≤ 1`, so
  repeating the command never compounds. Source: ForgePact `ModuleMain.cpp`
  `VanilyaBase`, `DropGrupUygula`, and `DropRateCmd`'s `group` branch.
- `dungeonkey on` with `chance auto` runs after the vanilla type-11 `LoadDrops`
  call. For each opened type it skips a monster that already lists the type. For
  a type with a pre-roll scale (relic, type 41: 0.00025) it skips unless its own
  RNG draws below `min(1, scale × m²)`. It then sets the slot to
  `chances[11] × m_gate`, calls the original once more with that type, and resets
  the slot. `m_gate` is the slider for relic and 1 for every other family
  (`build_key_cmds` in ForgePact's `src/forgepact.py`). Source: `Hook_LoadDrops`,
  `g_DkTipOlcek`.

`LeverParityTests` pins those transforms to ForgePact's source when ForgePact is
checked out, so the test fails if either side moves.

## What the model cannot catch

The model is a pure function of numbers. Everything below still needs code review
or a live run, and a green model test says nothing about any of it:

- **Whether a hook attaches at all.** A table-only `HookOneScript` install cannot
  see this build's direct `call rel32` sites. The model assumes the lever's code
  runs. Only a positive control through the same instrument shows that it does
  (`AGENTS.md` § "Prove the Instrument").
- **Frame timing.** The model has no notion of when in a frame a value is written
  or read: step events run before `EVENT_FRAME`, and a check at the frame
  boundary comes too late (`AGENTS.md` § "Check a Permission").
- **Runtime value kinds.** This runner hands back the local player as `VALUE_REF`,
  not `VALUE_OBJECT`. A kind check that rejects one of them turns a feature off
  silently, and the model cannot see that.
- **Stale addresses and moving names.** A hand-resolved address breaks with each
  game build (`AGENTS.md` § "Never Call an Address You Resolved by Hand"), and so
  does an `anon@N` closure name. The model names scripts, not addresses. Whether
  a name still resolves is a runtime question.
- **The game's RNG sequence.** The model gives probabilities, never a draw order,
  so it cannot predict a particular kill's outcome. It also cannot notice a lever
  that disturbs the game's own sequence.
- **Zone rules for which families a monster lists.** The model takes the chances
  array as given. Which monsters list which type in which zone is data it does
  not have.
- **Player-feel tuning.** M8 is the example. The relic pre-roll was tuned by
  watching the share of dropped items, and that share depends on the mix of other
  drops and on kill counts, which were never recorded. The model reproduces only
  the identity `0.00025 × 2² = 0.0005 × 2 = 0.001` and the clamp at x100, not the
  percentages. Whether a setting "feels right" is still a live decision.
