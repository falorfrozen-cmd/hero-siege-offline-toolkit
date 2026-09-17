Story and evidence behind `AGENTS.md` § ["Prove the Instrument Before Trusting a Negative Result"](../../AGENTS.md#prove-the-instrument-before-trusting-a-negative-result).

## The false negative that started this rule

The batching advice above is necessary but was not sufficient, and the reason
is worth its own rule. The same Pet Quest Collector research went on to spend
several more sessions on a *false negative*: 34 hooked call sites reporting
**0 calls** across multiple confirmed, observed collects. The conclusion drawn
- "the game does not call any of these" - was wrong. `HookOneScript` installs
by swapping a pointer inside the script-table entry, and this game's compiled
GML calls another script with a direct `call rel32` bound at compile time,
which never reads that table. **Every one of those zeros measured the
instrument, not the game** (`ForgePact/docs/pet-quest-collector-c-research.md`,
"The hooks were blind"). Two whole mechanisms were abandoned on that evidence.

## The same blindness, found as a shipping bug (ForgePact PR #2)

**The same blindness is a shipping bug, not only a research one.** A
table-only hook prints "HOOK INSTALLED" and then silently changes nothing on
the paths compiled GML actually uses - a feature that reports armed and does
nothing. Origin's review of ForgePact PR #2 found direct native callers for
`StatMovementSpeed`, `StatAttackSpeed`, `DropRelic`, `DropMonsterGold` and
`DropGold`, so stat scaling, drop multipliers and the max-level relic filter
were all in that state. `ForgePact`'s `HookOneScript` therefore installs
**both** - the table swap and an inline detour at the function's own address -
and hands the hook body the trampoline. `HookOneScriptTable` still exists for
exactly one purpose: `citrace nativetrace` needs a deliberately table-only
hook to compare against, and that comparison is what proved the problem.

## The same fix, needed again in the shared SDK (hub PR #3)

**And the rule applies to every installer, including a shared one.** Origin's
review of hub PR #3 found `hs-game-sdk`'s own `HeroSiege::Hooks::InstallScriptHook`
- the API other submodules are told to adopt - still table-only, and worse,
overwriting the saved original with the hook itself on a second install, so a
hook body forwarding through that pointer would recurse into itself. The shared
installer now does what ForgePact's does: both routes, trampoline as the
original, detour attempted only on the first install, and a result that *says*
`TableOnly` with a reason rather than reporting plain success.
`InstallScriptHookTableOnly` is the deliberately-limited variant, named so the
limitation is visible at the call site. A correction landing in one submodule is
not done until the shared SDK that other submodules copy has it too.
