Story and evidence behind `AGENTS.md` § ["Limit Rebuilds & Reruns During Development"](../../AGENTS.md#limit-rebuilds--reruns-during-development).

## Pet Quest Collector's Phase 0 research (2026-09-10)

**This was not respected closely enough during Pet Quest Collector's Phase 0
research (2026-09-10)**: candidate interaction hooks were added and tested
one small batch at a time - a named script, then five more named scripts,
then seven anonymous closures on one object, then two builtins, then nine
more anonymous closures on a second object - each round costing its own
rebuild, DLL swap, full game relaunch, and a live collect from the tester.
Several of those rounds could have been one round: `hs-game-sdk`'s static
name/hierarchy search (`grep` over `scripts.hpp`/`objects.hpp`, or the
Python/C++ bindings) can enumerate *every* plausibly-relevant script or
object *before* touching the game at all, and costs nothing to run
repeatedly. When a live research session's goal is "find which of several
unknown candidates does X" (not "verify one already-suspected mechanism"):
- Exhaust the static search first: every name matching the concept (by
  substring, by shared object/parent, by shared event) across
  `scripts.hpp`/`objects.hpp`, not just the one name the plan or a prior
  guess assumed. Read `hs-game-sdk`'s existing research docs
  (`ForgePact/docs/*-research.md`) for the technique already proven there -
  e.g. "every script-table entry inside `<object>`'s own Create event" found
  every anonymous closure GameMaker split out of that object, cheaply, with
  no live session.
- Hook every candidate that search turns up in the *same* build, gated
  together behind one research command, before asking for a single relaunch.
  A hook that turns out irrelevant costs one `HookOneScript`/`HookBuiltin`
  call and a few log lines - far cheaper than a round trip that could have
  included it.
- Only fall back to a narrower, more expensive technique (e.g. hooking hot
  builtins instead of named scripts) after the broad static-search round has
  been exhausted and come back empty, and even then, hook every plausible
  builtin candidate at once rather than one per relaunch.
