# What one mining dig pays: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/mining_reward_model.py`](../../hs-game-sdk/python/hs_game_sdk/mining_reward_model.py).
The model is checked against the numbers in
[`hs-game-sdk/curated/mining_reward_measurements.json`](../../hs-game-sdk/curated/mining_reward_measurements.json)
by [`tests/test_mining_reward_model.py`](../../tests/test_mining_reward_model.py). It
was built for ForgePact issue #36 (Mining Ore Extra Rolls). The workflow it follows
is [`docs/agents/static-model-workflow.md`](../agents/static-model-workflow.md), and
its first example is [`drop-roll-spec.md`](drop-roll-spec.md).

Every claim below carries one of three labels, and a source:

- **Static reading**: read from the compiled game locally and written here in our
  own words. No script text is quoted or transcribed (`AGENTS.md` § "Legal").
- **Measured**: observed in a running game.
- **Our code**: what ForgePact's own code does. The model leaves this out; the test
  expresses it as input transforms.

A claim that is none of these is under "Not established", and the model carries it
as a parameter or leaves it out.

Measured entries are cited by their fixture id (MR1–MR3). All three were recorded
on 2026-09-23, after `HookOneScript` gained its native detour, so the hooks that
logged them saw the direct calls the dig makes.

## Static reading

Source for every item in this section, unless another is named: the local reading
of issue #36's planning pass (2026-09-28), kept on the researcher's machine. The
names and object indices are all bound in `hs-game-sdk`.

- **One script is the whole dig.** `gml_Script_MiningNodeStepMain` handles
  activation, the level check, the reward, the experience, the quests and the
  node's depletion, in that order. Every script named below is a direct call from
  it, so a native `HookOneScript` detour sees each one (`AGENTS.md` § "Prove the
  Instrument").
- **The ore comes from a list the node already holds.** The node carries an array
  whose entries each name one of six ore kinds. At dig time the step counts the
  entries of each kind and then drops each kind that has at least one entry, once.
  There is no draw at dig time for which ore, or for how much of it.
- **Six drop sites, one per kind.** Each kind is dropped by its own
  `gml_Script_LootGroundCreate` call at the node's position, with item type 14
  (Material) and a params struct made by `gml_Script_CreateDefaultParams` with the
  kind's base: 27, 28, 29, 30, 31 or 32 for Copper, Iron, Gold, Ruby, Jade and
  Tarethium ([`RUNTIME_DATA_MODELS.md` §12](../RUNTIME_DATA_MODELS.md#12-mining)
  records the same bases). The kind's count goes on the struct as the stack
  quantity `o`, and only when the count is above one: a single entry leaves `o`
  absent, which the game reads as one.
- **The list is filled when the node is created.** `Mining_Node_obj`'s Create
  event (object 2775) builds the list from choices gated by the runtime's
  `irandom` and by two stat queries (ids 692 and 703) of the same shape as the
  bonus rolls below. `Asgard_Special_Node_obj`'s Create event (object 299) fills
  its list with fixed counts. So the composition is decided once per node, before
  anyone digs it, and a second pass over the same list at dig time yields the same
  kinds and counts again.
- **Bonus finds are drawn at dig time, gated by player stats.** After the ore the
  step makes several independent rolls. Each asks `gml_Script_ReturnSpecificStat`
  for one stat (the query ids seen are 693 to 700) and pays a bonus only when that
  stat is above zero and a whole-number `irandom` draw comes out below it. The
  runtime's `irandom(n)` draws from 0 to n inclusive, so a cap n gives n + 1
  outcomes. The cap is the literal 99 at one site; at the others it is computed.
- **What the bonuses are.** A type-15 item at base 109, 110 or 111 (the base
  itself is an inclusive draw over three values); one to three `Goblin_Ore_obj`
  (object 1903) placed through `gml_Script_CreateInFreePos`; type-14 materials at
  computed bases (three sites); two further type-15 sites and one type-13 site.
  These are the "special mats" issue #36 asks for. A character whose eight queried
  stats are all zero never passes one of these rolls, however often the dig runs.
- **The side effects follow the reward.** The step calls `gml_Script_MiningAdd`
  (the mining skill's own experience) and `gml_Script_ExperienceUpdate` on two
  branches, together with the floating text `gml_Script_CombatText` and
  `gml_Script_GuildExperienceAdd`; up to four pairs of `gml_Script_quest_exists`
  and `gml_Script_update_quest`; `gml_Script_PlaySound3D`; a `Mining_Effect_obj`
  (object 2773) hit effect; and `gml_Script_NetworkSendClient`, which does nothing
  offline. Then the node's `hp` goes from 1 to 0.

## Measured

- **One stack per kind, and the quantity multiplier scales it in place.** With
  ForgePact's Mining Ore Multiplier at x10 and the Miner's Helmet off, the adapter
  logged `first reward dispatched 6 -> 60`: one ore stack of 6 was sent as one
  stack of 60, and the owner confirmed the amounts in play (MR1, 2026-09-23).
  Source: [`ForgePact/docs/mining-ore-research.md`, "Live verification (2026-09-23)"](../../ForgePact/docs/mining-ore-research.md#live-verification-2026-09-23).
- **The helmet's x4 replaces the multiplier, per stack.** With the helmet worn,
  two digs logged `10 -> 40` and `13 -> 52` (MR2, 2026-09-23). Same source.
- **A dig completes in one step and leaves the node at `hp` 0.** Each reward was
  logged with the node's state `miningActive=true miningPlayer=-4 stop=0 range=48
  rangeMax=48 dir=1 hp=1`, and the node read `hp=0` right after. The probe never
  caught an intermediate slider position, because a dig completes in the step of
  the key press (MR3, 2026-09-23). Source:
  [`ForgePact/docs/miner-helmet-prototype.md`, "Ownership fix (2026-09-23)"](../../ForgePact/docs/miner-helmet-prototype.md#ownership-fix-2026-09-23).
- **Not measured:** mining experience, bonus finds and non-ore rewards under any
  lever. The records above say nothing about them.

## Not established

- **The list variable's name and its entry strings.** The slot is written only in
  the node's own Create event, which no name can hook. The model takes a list of
  ore kinds by the names above, not the game's own entries.
- **The caps and bases of the computed bonus sites.** Only one cap was read to a
  literal (99). The model carries the cap as a parameter whose default, 99, is a
  hypothesis for every site but that one.
- **What raises stats 692 to 703.** `hs_game_sdk.stats` does not name them, and
  which gear or talents feed them was not read. So whether a given character can
  see a bonus find at all is open.
- **Whether the completion pays again in the same frame.** ForgePact's extra rolls
  restore `hp` to 1 and set `miningQue` before re-running the step. Whether the
  step reads some other flag the first run set (`stop`, `range`, `miningActive`, a
  sprite index) and so pays nothing the second time, and whether ten runs in one
  frame are harmless, is Live procedure 1's question for issue #36. The model
  assumes a re-run pays exactly like the first; the test marks that as an input.
- **The order in which the six kinds are placed.** The model lists stacks in kind
  order, Copper to Tarethium, as a convention; no claim about the game's order.

## Our code

ForgePact's Mining Ore Extra Rolls (`drops.mining_ore_rolls`, command
`miningrolls N`) and the existing levers it combines with. Source:
`ForgePact/plugin/include/ForgePact/MiningOreMod.hpp` and `ForgePact/src/forgepact.py`,
pinned by the test's `RollsLeverParityTests` where ForgePact is checked out.

- **Rolls N re-runs the whole completion.** After the game's own dig returns, the
  plugin runs the same completion N − 1 more times on the same node in the same
  step, so the node's list pays N times and every bonus roll is drawn N times.
- **Each run is scaled as today.** Inside every run the quantity multiplier M
  scales each stack, or, when the Miner's Helmet applies, x4 replaces M. Rolls and
  multiplier multiply: N runs, each stack x M.
- **Experience, quests and floating text happen once.** The plugin passes
  `MiningAdd`, `ExperienceUpdate`, `update_quest` and `CombatText` through during
  the original run and skips them during the extra runs. Ore, bonus finds, sound
  and the hit effect happen once per run. The helmet's own dispatch (the pulse,
  Vein Resonance) runs for the original dig only.
- **No re-run without a first ore reward.** A dig that paid no ore starts no extra
  run; an extra run that pays no ore ends the loop. After the loop the node's `hp`
  is 0 whatever happened, so a node is never left diggable twice.
- **The cap is 10, refused in the plugin.** `kMaxRolls = 10`; the command parser
  refuses 0, anything above 10 and anything that is not one whole number, and the
  panel clamps its slider to 1–10. The default is 1, which installs nothing.

## The model

A pure function of the game's arithmetic, deterministic and analytic
([`mining_reward_model.py`](../../hs-game-sdk/python/hs_game_sdk/mining_reward_model.py)):

- `dig_stacks(kinds)` counts a node's list per kind and returns one params-shaped
  stack per kind present, `{"b": base}` at a count of one and `{"b": base, "o":
  count}` above it. `stack_quantity` reads a stack's quantity, absent `o` as one.
- `bonus_roll_probability(stat, cap)` is 0 when the stat is ≤ 0. Otherwise it is
  `min(cap + 1, ceil(stat)) / (cap + 1)`: the draw has `cap + 1` whole outcomes and
  hits on those below the stat.
- `expected_bonus_hits` and `probability_of_no_bonus` give the expectation and the
  miss probability over several independent rolls.

The levers above stay out of the SDK: the test defines the rolls, the multiplier
and the helmet as transforms of the model's output.

## What the model cannot catch

The model is a pure function of numbers. Everything below still needs code review
or a live run, and a green model test says nothing about any of it:

- **Whether the re-run pays at all** (see "Not established"). The model assumes it
  does; Live procedure 1 measures it.
- **Whether a hook attaches, and whether the silenced side effects are really
  silenced.** A table-only install cannot see this build's direct calls; only the
  plugin's harness and a live positive control show the detours run.
- **Frame timing, value kinds, stale addresses, the game's RNG sequence.** As in
  [`drop-roll-spec.md`](drop-roll-spec.md#what-the-model-cannot-catch).
- **Which stats a character has.** The bonus probability takes the stat as given.
