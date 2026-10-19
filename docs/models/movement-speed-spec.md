# How the walk's step follows the movement speed stat: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/movement_speed_model.py`](../../hs-game-sdk/python/hs_game_sdk/movement_speed_model.py),
tested by [`tests/test_movement_speed_model.py`](../../tests/test_movement_speed_model.py)
against the points in
[`hs-game-sdk/curated/movement_speed_measurements.json`](../../hs-game-sdk/curated/movement_speed_measurements.json).
It was written for ForgePact#166 (hub #518), whose Mark 1 set halves the
wearer's walk. It answers one question that lever needs answered before it
ships: what the walk's step does when the movement speed stat's answer
changes, and so which answer halves it.

It is written from ForgePact's
[Mark 1 research, Mod live 1 results](../../ForgePact/docs/mark1-set-research.md#mod-live-1-results)
(the `speed-sweep`, `speed-half` and `stat-trace` checks) and that doc's Phase
2 decision; the shared facts are
[`docs/RUNTIME_DATA_MODELS.md` § 19.10](../RUNTIME_DATA_MODELS.md#1910-walking-speed-and-jump-length).

Every claim carries one of four labels, and a source:

- **Static reading**: read from the compiled game locally and written here in our
  own words. No script text is quoted or transcribed (`AGENTS.md` § "Legal").
- **Measured**: observed in a running game.
- **Our code**: what ForgePact does. The model leaves it out, and the test expresses
  it as an input transform.
- **Not established**: carried by the model as a parameter, or left out.

## Names used here

- **The answer**: what the stat dispatcher, `ReturnSpecificStat`, returns for
  stat id 64 (movement speed) on one call. Sorak, the White Mage on save slot
  14 that every session used, answers 151.
- **The modal step**: the most common distance the player moved per frame in
  one window of a walk, in pixels, as `mark1probe pos` reports it.
- **A ratio**: one window's modal step over the unlevered control's, the two
  windows at a mean frame time within 10% of each other.
- **A multiplier m**: what `mark1probe stat 64 <m>` multiplies every local
  dispatcher answer for id 64 by, for the window's frames.

## Static reading

- **Id 64 goes to `StatMovementSpeed`, and the walk reads it in the player's
  Step event.** The dispatcher sends id 64 to `StatMovementSpeed`, whose only
  direct caller found is the dispatcher. The player object's Step event asks
  for id 64 once; `PlayerMovement` was not found asking for it (RDM § 19.10,
  phase 1's reading of 2026-10-13).
- **Where the answer becomes a step was not read.** `StatMovementSpeed`, the
  Step event and `PlayerMovement` did not decompile within the tools' limits,
  so the arithmetic below is measured, not read.

## Measured

All from ForgePact#166's Mod live procedure 1, 2026-10-19, unless it says
otherwise: Sorak in `Town_01_rm`, walking right from the town waypoint with
D held, at 6.94 ms a frame.

- **The answer is 151 every frame** (`stat-trace`): 60 dispatcher calls for id
  64 in 60 frames, each answering 151, every one outside the twenty rows the
  probe wraps (`PlayerMovement` among them), and no call of `StatMovementSpeed`
  outside the dispatcher.
- **The unlevered walk's modal step is 2.989 px** (`walk-control`), in two
  walks at 6.94 and 6.95 ms a frame.
- **The sweep** (`speed-sweep`). With every dispatcher answer for id 64
  multiplied by m for a 240-frame window inside a walk, the windows gave:

  | m | answer | modal step (px) | ratio |
  |---|---|---|---|
  | 1.5 | 226.5 | 3.632 | 1.215 |
  | 1 | 151 | 2.989 | 1 |
  | 0.75 | 113.25 | 2.668 | 0.893 |
  | 0.5 | 75.5 | 2.346 | 0.785 |
  | 0.25 | 37.75 | 2.025 | 0.678 |
  | 0 | 0 | 1.703 | 0.570 |
  | -0.5 | -75.5 | 1.06 | 0.355 |

  The lever changed all 240 dispatcher answers in each window, and every
  window ran within 10% of the control's frame time (at most 6.96 ms).
- **The step is affine in the answer.** All seven points lie on one line to
  within 0.02%: the modal step is proportional to the answer plus about 200
  (a least-squares fit gives 200.0). An answer of 0 still walks, at 0.570 of
  Sorak's step; a negative answer slows the walk further and it still moves
  forward; no cap was reached up to 226.5.
- **Half speed is an answer of (151 - 200) / 2** (`speed-half`). The
  multiplier interpolated between the -0.5 and 0 windows, -0.162 (an answer
  of about -24.5), gave a modal step of 1.495 px, a ratio of 0.500.
- **Phase 1's point is the same line** (Live 2, 2026-10-13, at 13.4 ms a
  frame): halving the answer took the step from 5.979 px to 4.693 px, 0.785,
  the same ratio as the m = 0.5 window above. Phase 1 did not print the
  answer; the same character and save answered 151 in Mod live 1.
- **The step tracks the frame clock.** The unlevered step was 5.979 px at
  13.4 ms a frame and 2.989 px at 6.94 ms. Within one window the per-frame
  steps come in multiples of half the modal step (RDM § 19.10).

## Our code

**Mark 1's speed lever** (`speed-route: stat-model`, the research doc's Phase 2
decision; built by the workorder's `movement` item):

- While the set's bonus is active, every local id-64 call is answered
  (min(x, C) - k) / 2, where x is the game's own answer, k the model's
  `STEP_OFFSET` (200) and C its `STEP_CAP` (none, so x itself). For Sorak
  that is -24.5.
- `stat-trace` placed the id-64 call outside every row Mark 1 wraps, so the
  lever answers every local id-64 call, not only the walk's: the character
  sheet and the damage scripts that read id 64 see the halved value too.
- Why this route: the sweep fits one affine shape within 0.02% and the
  interpolated answer gave 0.500, while `speed-builtin` found no builtin that
  moves the walk and `speed-factor` found no effect from `hSpeedFactor` and
  `vSpeedFactor`. Because the shape is affine, halving the answer would give
  0.785, not 0.5; the lever subtracts k first. The model records this as
  `SPEED_ROUTE` and `SPEED_ROUTE_REASON`.

The test file expresses the lever as a transform of the answer
(`mark1_stat_model_answer`). The `movement` item's `LeverParity` tests pin the
plugin's constants to the model's.

## Not established

- **Where 200 comes from.** It is measured for this game build only; whether it
  is a base speed the stat is a percentage of, and where in the Step event it
  is applied, was not read.
- **A cap above 226.5.** None was reached; `STEP_CAP` is a parameter, `None`
  until one is measured.
- **Answers at or below -200.** The lowest measured answer is -75.5. The model
  refuses a weight of 0 or less rather than guess whether the walk stops or
  turns back.
- **The law between frame time and step.** Half the frame time gave exactly
  half the step, but the per-frame steps are quantized and the frame time
  ratio of the two sessions was 1.93, not 2. The model takes each window's
  scale (px per point of answer plus offset) as a parameter.
- **Whether the walk also reads a cached copy of the stat** (`pSt`), which the
  dispatcher lever would not reach. Every window held one step for its 240
  frames, which argues against it.
- **Other characters.** Only Sorak's 151 was measured; other answers are the
  same line extrapolated.

## The model

A pure function of numbers, with exact fractions
([`movement_speed_model.py`](../../hs-game-sdk/python/hs_game_sdk/movement_speed_model.py)):

- `STEP_OFFSET` = 200 (k) and `STEP_CAP` = None (C), the measured constants;
  `MEASURED_ANSWERS` = (-75.5, 226.5), the swept range.
- `effective_answer(answer, cap)`: the answer, stopped at the cap when there is
  one.
- `step_weight(answer)` = `effective_answer(answer)` + 200: what the step is
  proportional to. Raises when it is 0 or less.
- `modal_step(answer, step_per_point)`: the window's modal step, with the
  window's scale as a parameter; `step_per_point_from(step, answer)` derives the
  scale from a window whose answer is known.
- `step_ratio(answer, reference_answer)`: the step at one answer over the step
  at another, at the same frame time.
- `scaled_answer_ratio(m, answer)`: the ratio the sweep's lever gives.
- `answer_for_ratio(answer, r)` = r × (answer + 200) - 200: the answer that
  makes the step r times what `answer` gives. At r = 1/2 it is the
  stat-model route's (x - k) / 2.
- `SPEED_ROUTE` = `"stat-model"` and `SPEED_ROUTE_REASON`: which route the
  Phase 2 decision picked, and why.

## What the model cannot catch

- **Whether the lever attaches.** The model takes the answer the walk sees as
  given; only a live window with the lever's counter climbing shows that the
  detour answered the walk's call.
- **What else reads id 64.** The halved answer reaches the character sheet and
  the damage scripts too; the model says nothing about them.
- **The cast's slowdown.** A cast drops the walk to 0.650 of its step for a
  while (`penalty-control`), outside the stat; whether that stacks on the half
  speed is Mod live 2's question.
- **Frame timing, the quantized per-frame steps, and how half speed feels in
  play.**
