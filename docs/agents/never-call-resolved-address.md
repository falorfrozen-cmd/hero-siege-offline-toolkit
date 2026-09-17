Story and evidence behind `AGENTS.md` § ["Never Call an Address You Resolved by Hand"](../../AGENTS.md#never-call-an-address-you-resolved-by-hand).

## Two shipped incidents

This toolkit has now hit that defect twice:

- **`relicgate`** used a fixed RVA inside `DropItem`. On the current build that
  address is not inside `DropItem` at all. The feature had been silently dead
  for an unknown number of releases; it is now a no-op that says so
  (`SetRelicGate`).
- **Pet Quest Collector** shipped `PetQuestCollectOne` calling
  `GetModuleHandleA(nullptr) + 0xB489070` - the runtime's call-a-method-value
  dispatcher, measured live and correct for exactly that build - validating
  neither the module, nor the bytes, nor the build. It survived one release
  before review caught it. Removing it took three attempts, and the second one
  (reading the callable off the value's own `CScriptRef`) failed for the same
  underlying reason as the first, which is why the struct bullet below exists.
  What works is `script_execute` through `CallBuiltinEx` - name-resolved,
  layout-free, confirmed live by the quest counter advancing.

## The full resolution ladder, with the reasoning behind each rung

So, before a pointer is called or dereferenced in code that reaches a player:

- **Resolve by name.** `GetNamedRoutinePointer` / `HookOneScript` /
  `HookBuiltin` for scripts and builtins, `asset_get_index` for assets,
  `CallBuiltin` for anything the runtime exposes. This is the default and it
  covers nearly everything.
- **Otherwise let the runtime do the work, still by name.** `CallBuiltinEx`
  supplies `self` and `other` to any builtin, so the runtime's own dispatcher
  can be handed a value whose internals you never inspect. This is how the Pet
  Quest Collector ends up invoking an anonymous method value
  (`script_execute`, `self` = the item, `other` = `Loot_Manager_obj`): no
  address, and no struct layout either.
- **Only then resolve off a runtime struct YYToolkit defines** - `CScriptRef`,
  `CScript`, `CInstance`, `RValue` - and treat that as an assumption to be
  measured, not a fact. **A struct layout is the quiet version of a hardcoded
  address.** Both are "a layout someone wrote down"; the address fails loudly
  and the field silently returns a plausible zero. This is not hypothetical:
  the fix for the Pet Quest Collector's hardcoded address was *itself* a
  `CScriptRef` read, and it shipped broken, because on this game's runner
  `m_Questpickup` is not a `CScriptRef` at all (`m_ObjectKind = 0`, both
  callable fields zero, `method_get_index` returns nothing - while a sibling
  variable on the same instance resolves fine). If you do read a struct,
  **find a positive control on the same target first**: something the plugin
  already proves works on this runtime, whose value you can compare against.
- **A measured address is a research finding, not an implementation.** Keep it
  in `docs/` and behind `#ifndef FORGEPACT_RELEASE`, where a wrong value costs
  a session. `citrace collect`'s `native` path is the pattern: the old shape
  stays runnable as an A/B check against the shipped one, and nothing else
  uses it.
- **If an address genuinely cannot be avoided, validate it and refuse.**
  Confirm the target is committed, executable, and inside the intended
  module's image (`AddrIsExecutableInModule` - `VirtualQuery`,
  `AllocationBase`, `PAGE_EXECUTE*`) before calling, and on failure disable
  the feature with a message the way `SetRelicGate` does. Never fall through
  to the call. Count the refusal so it surfaces in a `stat` command instead
  of as silence.

## The corollary: record what was supplied, not just the verdict

A corollary, learned from the same investigation: when a call shape is
rejected, record *what was supplied* alongside the result. Nine name-resolved
invoke shapes were written off as "measured negative" before a later round
established that the callee wanted one argument and a specific `self`, neither
of which those nine had passed - the notes say so themselves
(`ForgePact/docs/pet-quest-collector-c-research.md`, "This explains every C0.2
access violation"). **One of those nine is now the shipped mechanism.** Three
rounds went into inventing call machinery while the working answer sat in a
table of already-implemented paths, mislabelled. That is the "not observed" vs
"does not happen" distinction from the section above, applied to call
signatures - and the cost of getting it wrong is not one wasted session, it is
every session that trusts the label afterwards.
