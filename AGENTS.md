# Agent Guidelines

## Submodule & Directory Development Instructions

When developing, modifying, testing, or investigating code within any submodule or specific directory (e.g., `HSCraftSim/`, `ForgePact/`, `HS-Offline-Tracker/`, etc.), always consult and follow the corresponding development instructions guide:
- Check the centralized index at [`docs/submodules/README.md`](docs/submodules/README.md) for available module guides.
- Check for submodule-specific development guides located at `docs/submodules/<submodule-name>/instructions.md` (or `<submodule-name>/instructions.md` if present within the directory).
- Adhere to the documented architecture, entry points, workflows, testing procedures, dependencies, and command conventions outlined in the relevant `instructions.md`.

## Some of These Rules Are Enforced, Not Just Written

[`.claude/`](.claude/README.md) carries the subset of this file that a machine
can check or run, so those rules stop depending on whether the right section was
read first. Four `PostToolUse` hooks (the catalog signature, the Tauri command
threading rules, the hub's frontend tests, and decompiled output reaching a
tracked file) and a `Stop` hook that reports processes this session started and
left running, five review agents (`sdk-contract-reviewer`,
`tauri-command-reviewer`, `decompile-output-guard`, `docs-sync-reviewer`,
`instrument-blindness-reviewer`), three phase agents that run a change through
plan → implement → verify at three different model tiers (`planner`,
`implementer`, `verifier`), a `consultant` a phase can put one hard decision to
without escalating the whole phase, and three skills (`/catalog-rebuild`,
`/workorder`
which drives those phases and routes defects back to the phase that caused them,
and a `submodule-context` skill that loads the guide named above). MCP servers
are in [`.mcp.json`](.mcp.json).

The phase split exists because the expensive failures in this file are not
planning failures — they are an implementer meeting something the plan did not
anticipate and writing something plausible instead of stopping. So the
`implementer` is required to return `PLAN-DEFECT` with evidence rather than
improvise, and the `verifier` runs the acceptance criteria and reports what they
actually printed rather than judging whether the code looks right. Both rules
are this file's "evidence before assertions" applied to a handover.

A phase that is merely *stuck* on one decision has a cheaper move than failing:
`ADVICE-NEEDED` puts that question to the `consultant` and resumes with the
answer, keeping its context and its progress. It must state what it would do
unaided, so the answer confirms or corrects a position rather than replacing the
thinking — a consultation that skips that field is a handoff wearing a question
mark, and the driver sends it back. Which problems start a tier higher is
decided up front from **observable properties of the task** (does it introduce
concurrency, must it establish an unknown mechanism, does it change how a hook
attaches), never from a model's self-reported confidence: a model that cannot
solve something is also badly calibrated about whether it can, which is the same
reason this file does not accept an unproven negative.

If a hook blocks an edit, it is quoting a rule from this file — read what it
printed rather than working around it. If you add a rule here that is
mechanically checkable, add the check too; `.claude/README.md` says how.

## Offer `/workorder` When the Work Has Shape, and Respect "Plan Only"

`/workorder` is user-invoked only. The skill sets `disable-model-invocation:
true`, because it spawns at least three agents, which is the wrong response to
a typo — so reaching for it through the `Skill` tool returns a refusal, not a
pipeline. You cannot start it; you can only **offer** it, in one line, before
starting, when the request matches any of these:

- the change spans several files, or touches a submodule;
- the user asks to **implement, execute or carry out a plan** — theirs, or one
  from an earlier session;
- it introduces concurrency, changes how a hook attaches, alters a contract the
  C++/Python/TypeScript bindings must agree on, or would ship a player-visible
  change;
- there are three or more distinct steps and a later one depends on an earlier
  one being right.

Offer, then wait. One line — *"This spans the SDK and two bindings; want me to
run it through `/workorder`, or just make the change?"* — and if the answer is
no, do the work directly and drop it. Do not re-offer within a session, and do
not ask about a one-line fix.

**"Plan it" means plan it, and nothing else.** When the request is for a plan,
a design, an approach, or an assessment of how something should be done, the
mode that fits is `/workorder plan <task>` — so name it and ask the user to run
it, the same way you offer the full pipeline. Do not try to invoke it yourself;
that is the refusal above, and it costs a round to discover.

Once it is running, **stop when the plan exists**. Report it, name the
`resume` command, write no code, and edit nothing. The user is splitting the
work across sessions on purpose: implementation starts from the file, not from
the conversation, and the plan not surviving that split is exactly the signal
they are trying to get. Starting the implementation because the plan looked
obviously right removes the review checkpoint they asked for, and it is the one
outcome that makes the split worthless.

## Legal: Decompiled Output Never Reaches Any Origin

This toolkit reverse-engineers Hero Siege's runtime (memory layout, hooked functions,
GameMaker object/script indices) to build offline tools. **The constraint is entirely
about output, not technique**: decompiling or disassembling the game locally — reading
a script body in Ghidra/IDA/UndertaleModTool/dnSpy to understand what a mechanism does —
is not restricted and is a legitimate research step when static name/hierarchy search
and live measurement (hooking, tracing, before/after diffing) run out, same as the rest
of this toolkit's reverse-engineering. What must never happen is for that output to
land in a repository that gets pushed to its origin (this includes every submodule's
own remote, not just this hub) — see the hard rule below.

**Hard rule: never commit, paste, or embed decompiled or disassembled Hero Siege
source (GML script bodies, decompiled bytecode, IDA/Ghidra/UndertaleModTool
listings or exports, disassembly dumps) into any tracked file.** This applies to
production code, `docs/` research notes, commit messages, and comments alike — write
up *what was learned*, in your own words, never the decompiled text itself.

What is fine to commit — because it documents *interoperability facts*, not the
game's copyrightable expression:
- Object/script/room/sprite/sound **names and their numeric indices** (e.g. the
  `hs-game-sdk` tables, or a hook installed by name via `HookOneScript`).
- **Measured runtime behavior**: what a function does when called, what it reads
  or writes, observed crashes and their signatures, before/after values.
- **Our own** C++/Python/TypeScript code that reacts to that behavior (hooks,
  panels, SDK bindings) — original work, not derived from the game's source text.
- Function/struct *offsets and calling conventions* needed to hook or read memory.

What must stay local and out of version control:
- Full or partial decompiled/disassembled script bodies, however they were
  produced (Ghidra, IDA, dnSpy, UndertaleModTool, manual transcription).
- Exported decompiler project files or listings (e.g. `.gpr`, `.i64`, `.idb`,
  UndertaleModTool `Export/` dumps) — kept on the researcher's machine only.
- Screenshots or copy-pasted excerpts of the game's own script source in issues,
  PRs, or docs.

If a research note needs to explain *why* something behaves a certain way,
paraphrase the mechanism ("the door script rolls the same die as case 11/31/40")
rather than quoting the script. `ForgePact/docs/*.md` is the existing example to
follow — behavior and our own hook code only, no game script text, and that
practice is what keeps the AGPL-3.0 "original work" claim in `ForgePact/CREDITS.md`
true. `.gitignore` also excludes common decompiler artifact paths as a mechanical
backstop; extend it rather than working around it if a new tool produces a new
artifact type.

## Mod Development Workflow: Test Before / After, Then Build to It

When developing a mod, hook, or any gameplay-affecting change (drop rates, stats,
spawns, combat, crafting, etc.), don't start by editing the hook and checking it
live in-game. Establish both ends of the behavior change as tests first, then
write the mod to close the gap:

1. **Baseline test** — capture how the game behaves *without* the mod (vanilla
   read, unmodified value, default probability/roll). This pins down the exact
   starting point so a regression in "no mod applied" behavior is caught too.
2. **Target test** — capture how it *should* behave once the mod is applied
   (the new value, rate, or code path the mod is meant to produce).
3. **Implement the mod** to turn the target test green without breaking the
   baseline test's assumptions about the unmodified path (e.g. a toggle/config
   that's off by default should still reproduce baseline behavior).

Place these alongside existing coverage — see `tests/` at the repo root for the
`hs-game-sdk` test style, or a submodule's own test directory per its
`instructions.md`. Where a real game process is required to observe the
behavior, prefer a fixture or mock built on `hs-game-sdk` structs over a live
game session for the baseline/target tests, and reserve actual in-game runs for
final verification.

## Limit Rebuilds & Reruns During Development

Full recompiles and relaunching the game for every change are slow and make the
edit-verify loop expensive. Before or alongside mod development:
- Look for an existing tool that lets you exercise the change without a full
  rebuild/relaunch (e.g. a standalone test harness, a script that replays
  captured game state, incremental/unity builds, hot-reloadable hook code).
- If nothing suitable exists for the submodule you're working in, build one
  (or extend `tools/`) and document it in that submodule's `instructions.md`
  so the shortcut is reusable rather than one-off.
- `tools/freeze_probe.ps1` is an example of this pattern applied to diagnostics
  (observe the running game from outside it instead of adding print-and-relaunch
  instrumentation); prefer the same "build a tool once, reuse it" approach for
  mod iteration.
- Reserve full rebuild + in-game relaunch cycles for final confirmation once
  the baseline/target tests above already pass against the faster loop.

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

## Drive a Tauri App Yourself Instead of Asking Someone to Click It

The same "build the fast loop first" rule applies to the Tauri submodules
(`hub`, `HS-Offline-Tracker`). A change to a window is not verified by the
frontend compiling, and the alternative to verifying it should not be asking a
human to click it and describe what happened.

`hub/src-tauri` carries `tauri-plugin-mcp-bridge`, **behind
`#[cfg(debug_assertions)]`**, listening on `127.0.0.1:9223`. A debug build can
therefore be clicked, screenshotted, queried and measured from a terminal. The
gate is not a detail: the bridge can invoke any command in the application, so
a release build must never start one. Copy that arrangement — including the
`cfg` and the loopback bind — into any other Tauri submodule that wants this,
rather than shipping a listener.

```bash
npm start                                                     # in hub/, wait for :9223
npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp driver-session start --port 9223
npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp webview-screenshot --window-id hub --file-path shot.png --format png
npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp webview-interact  --window-id hub --action click --selector "button[aria-label='Star ForgePact']"
```

Four things cost an afternoon to work out and none are visible from the code.
Each one makes the bridge *look* broken while it is working fine:

- **The hub's window label is `hub`, not `main`.** Every bridge tool defaults
  to `main` and fails with `Window 'main' not found`. Pass `--window-id hub`.
- **`npx @hypothesi/tauri-mcp-cli` does not run anything** — the package's
  binary is named `tauri-mcp`, so it must be
  `npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp <subcommand>`.
- **`--script` must be one line.** A multi-line script fails with
  `Script execution timeout` even when it would return instantly. Write the
  whole IIFE on a single line.
- **Long work needs two calls.** The transport gives up well before
  `--timeout` claims it will, so kick the work off, stash the result on
  `window`, and read it back in a second call.

The CLI is one of two front ends to the same bridge, and **it has no server
mode** — `@hypothesi/tauri-mcp-cli` is a terminal wrapper, so `tauri-mcp serve`
does not exist and looking for it wastes a round. The MCP server is a separate
package, `@hypothesi/tauri-mcp-server`, wired up as `tauri-hub` in
[`.mcp.json`](.mcp.json); prefer it, and keep its version pinned to the
`tauri-plugin-mcp-bridge` major in `hub/src-tauri/Cargo.toml`, because some
tools return a version error against an older plugin rather than working
partially.

Subcommands are spelled either way — `webview-screenshot` or
`webview_screenshot`. The ones worth knowing beyond the three above:
`webview-dom-snapshot` (an accessibility or structure tree, better than a
screenshot for asserting text), `webview-find-element` (geometry, attributes
and computed styles — use it instead of `webview-execute-js` for
`querySelector`/`getBoundingClientRect`/`getComputedStyle` reads),
`webview-wait-for`, `read-logs --source console`, `ipc-execute-command` and
`ipc-monitor` (Tauri IPC, not browser network), and `manage-window list` when
you need to confirm the label rather than assume it.

Prefer a **selector** over a coordinate (`--selector "button[aria-label='…']"`,
or `--strategy text`): a selector re-queries after the interface has re-laid
itself out, and a coordinate captured from an earlier screenshot does not. Then
assert against what the change actually wrote — `state.json`, the log — rather
than only against the screenshot, and record the result in that submodule's
verification table. This is the "prove the instrument" rule below applied to a
window instead of a hook.

## Clean Up the Processes You Started Before Ending a Reply

A session in this repository routinely starts real processes: `npm start` in
`hub/` for the section above (a Tauri debug build plus its MCP bridge), `cargo`,
`npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp driver-session start`, a
`run_in_background` shell, a `Monitor` task, a test or game launch. Left
running past the reply that started them, these are exactly how a machine's
memory fills up over a long day — one process at a time, none of them
individually alarming.

So: before ending a reply, stop what you started. Kill background shells
through the tool that owns them. A dev server leaves more than its own PID —
`npm start` in `hub/` leaves both `cargo` and the debug `hub.exe` behind it, so
kill the **tree**, not just the process you launched. The same goes for
watchers, a `tauri-mcp driver-session`, and test children. If the user asked
for something to keep running, leave it, and say so in the reply, naming the
PID. A background agent or shell of this session that is still working — not
finished, not abandoned — is also a valid reason to leave a process running:
say so and name the PID rather than treating a leftover report as an error.

How to find what a PID left behind, on Windows:

```powershell
Get-CimInstance Win32_Process | Where-Object ParentProcessId -eq <pid> | Select ProcessId,Name,CreationDate,CommandLine
Get-NetTCPConnection -LocalPort 9223 -State Listen | Select OwningProcess
```

then end it — `taskkill /PID <pid> /T /F`, written as `taskkill //PID <pid>
//T //F` under Git Bash so it is not read as a path. In auto mode `taskkill`
can be denied by the permission classifier (seen: "Interfere With Workloads");
if it is, do not retry around it -- tell the user what is still running and
name the PID.

Never kill a process you did not start: the MCP servers backing this session
(each is `npx` → `cmd.exe` → `node`, one full set per session), another
Claude session's processes, or the user's own game or hub. Never kill by image
name — `taskkill /IM node.exe` takes out every session's MCP servers along
with the one you meant. And check with a command that the process is actually
gone; do not assume a kill succeeded.

`.claude/hooks/leftover_processes.py` backs this up: a `Stop` hook reports
whatever it can attribute to this session's own tool calls and is still alive
when a reply ends, once per process. It never kills anything — reporting is
all it does. A quiet hook is "not observed", not proof that nothing leaked; it
can only see what its own ledger recorded, so the rule above is still yours to
follow, not something to wait for the hook to catch.

## Prove the Instrument Before Trusting a Negative Result

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

So, before a "0 calls" / "no effect" / "never fires" result is allowed to
close a line of investigation:
- **Run a positive control through the same instrument.** Point it at
  something you already know fires - in this case any hook that had ever
  logged a call - in the same build, in the same session. An instrument that
  cannot produce a non-zero anywhere has told you nothing about your target.
- **Know how your instrument attaches, and whether the code under test can
  reach it.** Script-table swaps only see calls routed through the table;
  address-patching hooks (`MmCreateHook`) see the call itself. Prefer the
  latter whenever a table-based hook reports zero, before concluding anything
  about the game.

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

The general rule: **put the interception in the installer, not in whichever
call sites a review happened to verify.** Fixing the five named functions
would have left every other gameplay hook, and every future one, blind.

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

## Check a Permission Where It Is Used, Not Where It Is Convenient

`EVENT_FRAME` (what `FrameCallback`/`OnFrame` run on) is dispatched from
`HkPresent` — the **end** of a frame. Object step events run **before** it. So
a flag that a step-time consumer reads cannot be validated at `EVENT_FRAME`:
whatever the consumer did this frame, it already did.

Map reveal's pack pass learned this the expensive way. Its "lie about
distance" permission was invalidated in `OnFrame` when the zone changed, which
looked correct and passed its tests, but the creators consuming that
permission ran earlier in the same frame — so the first call in a new zone
still got the previous zone's answer, which is exactly the call that leaves a
spawner inert. Two rounds of adding more identity tracking at `OnFrame` could
not have fixed it; only moving the check to the consumer did.

- **Validate at the point of use**, with the thing being acted on. The
  question "may I do this to *this* object" is usually answerable from the
  object itself (here: does this creator report a real `enemyCreatorTimer`),
  and that answer is correct regardless of when any cached state was last
  refreshed.
- **A sentinel that means "unknown" must never compare equal to a real
  value.** The same code stored `INT64_MIN` for an unreadable room and then
  compared against it, so "unreadable" silently matched "unreadable" and the
  guard passed. Prefer a read that fails as a unit over a magic value.
- **Frame-boundary work is for budgets and housekeeping** — counting a window
  down, throttling expensive polls — not for anything another system's
  correctness depends on within the same frame.
- **Write the negative down as "not observed", not "does not happen"**, until
  a control backs it. Research docs in this repo are read later as settled
  fact; a mislabeled negative costs more sessions than the one that produced
  it.

## Never Call an Address You Resolved by Hand

Reading a function's address in Ghidra is a legitimate research step (see the
legal section above). **Shipping that address as a constant is not.** A game
build's RVAs are not an interface: the next recompile moves every one of them,
and the constant then names whatever bytes happen to sit at that offset. A
*read* through a stale address returns garbage; a *call* through one transfers
control into arbitrary code on a player's machine.

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

`ForgePact/tests/test_release_hook_contract.py`'s
`test_player_binary_calls_no_hand_resolved_game_address` enforces this
mechanically: it strips the research blocks and fails if anything left can
reach a `*Rva*` constant or computes a call target from a module base plus a
literal. Extend that test rather than working around it.

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

Finally, make a refusal say why. `InvokeMethodValue` logs one line naming the
field that failed, and `petquest 0` reports which route actually ran plus a
`dispatched-but-item-remained` counter that separates "nothing ran" from "ran
and did nothing". Those two outputs turned a hypothesis that would have cost a
research session into two launches. A mod that fails silently is a mod nobody
can debug from a bug report.

## Don't Suspend the Game's Own Runtime

Every mod in this toolkit that works does one of two things: it **reads** game
state, or it **changes one value inside a call the game is already making** — a
`droprate.base` divided before the game's own die is rolled, a base speed scaled
for the duration of one `PathFindStartPath`, a marker object multiplied so the
game places and runs the mechanic itself. The game stays in charge of its own
loop throughout.

**Features that take the loop away from the game are not recommended**: pause,
time scaling or slow-motion, save-state/rewind, forced state restore, freezing
or wholesale deactivating instances — anything whose contract is "suspend the
world and give it back unchanged". They are a different risk class, and the
reasons are structural rather than a matter of implementation quality:

- **The failure mode inverts.** Ordinary mods fail by doing nothing (a dead
  `relicgate`, a collect that never fires). A suspension feature fails by
  leaving the player's session stuck, or by letting the game save while its own
  state is half-removed. When a design needs a panic hotkey, a watchdog and a
  fail-open path on every branch before it can ship, that machinery is the
  signal, not the mitigation.
- **The precise instruments are unavailable on this build.** YYToolkit's
  per-event hook (`EVENT_OBJECT_CALL`) is deliberately disabled in the
  YYToolkit this project ships — it crash-looped on Season 10 — and
  named-script hooks are structurally blind against this YYC build's direct
  calls (see the section above). What remains is blunt, whole-subtree
  instance deactivation, with the widest possible blast radius.
- **The claim cannot be verified.** "Everything stops" is a statement about
  every timer, DoT, cooldown and internal counter in the game, including the
  ones nobody has enumerated. Contract tests can pin the mod's own structure;
  they cannot establish that. A miss surfaces as a buff that quietly expired or
  a cooldown that quietly advanced — wrongness a player reports months later as
  "the mod broke my character".
- **It taxes every future game patch.** Anything that has to know the game's
  full object or UI surface (which windows count as a menu, which objects are
  actors) is upkeep on someone else's release schedule.

The worked example is `ForgePact/docs/menu-pause-plan.md` — a complete design
for "pause the world while a menu is open", researched to the point where the
mechanism was clear, and **not recommended for implementation** for exactly the
reasons above. Read its §0 before proposing anything in this class; if one is
built anyway, that is a deliberate decision to accept those risks, and it
belongs in the submodule's Known Limitations with the acceptance recorded.

Prefer the alternatives: read-only tooling outside the game, a change to one
value the game is about to use, or leaving the behaviour alone.

## Documentation & Instructions Maintenance

Upon completing any task or making changes to features, workflows, architecture, or dependencies:
- Update documentation, instructions (such as submodule `instructions.md` files), and `README.md` files when and where relevant to reflect the changes.
- Ensure any new guides, updated links, or modified commands remain accurate and in sync across project and submodule documentation.

**Record what was built, not what you meant to build.** `*-plan.md` is in this
repository's `.gitignore`. A plan is a working note: it is out of date the
moment the thing exists, and a repository carrying both leaves the next reader
two documents and no way to tell which describes the software they are running.
So when a plan's work lands, fold the reasoning that is still true into the
document that describes the result — `docs/hub/design.md`, a `docs/adr/` entry
for a decision that outlived its discussion, or the submodule's
`instructions.md` — and leave the plan on your own machine.

This is a rule about *this* repository. The research and plan documents under
`ForgePact/docs/` belong to that submodule, which keeps them deliberately: an
investigation that came back negative is a result, and re-running it is the
expensive mistake.

## YYToolkit Integration

When a prompt or task requires the use of `yytoolkit`, attempt to retrieve `yytoolkit` documentation and references from the `context7` MCP server if it is available.

## HS Game SDK Usage

When developing, modifying, testing, or reverse-engineering game logic, hooks, drops, and items across any submodules:
- Use `hs-game-sdk` (`hs-game-sdk/`) as the central source of truth for GameMaker object indices, script names, room indices, sprite indices, sound indices, stat IDs, proc bundles, and runtime item/stat structs.
- In **C++** plugins (`ForgePact/plugin`, `HS-Offline-Tracker/aurie-producer`, `hs-stat-forge`), `#include <hs_game_sdk/hs_game_sdk.hpp>` and use strongly-typed definitions from namespace `HeroSiege` (such as `HeroSiege::Objects::GameObject`, `HeroSiege::Scripts::gml_Script_*`, `HeroSiege::Stats::StatId`, and `HeroSiege::YYTK`).
- In **Python** submodules (`ForgePact/src`, `hero-siege-item-editor`, `HSSaveEditor`, `HS-Offline-Launcher`), import models and constants from `hs_game_sdk` (e.g. `from hs_game_sdk import GameObject, GameScript, StatId, PROC_FAMILIES, ItemDefinitionStruct, ItemStatStruct`).
- In **TypeScript / Web** submodules (`HSCraftSim`, `HS-Offline-Tracker/src`), import from `@hero-siege/sdk`.
- Avoid declaring raw string literals or magic numbers for game scripts, asset indices, object types, and stat keys when equivalent constants exist in `hs-game-sdk`.
- If game updates shift asset or script indices, regenerate the SDK bindings using `tools/extract_and_generate_sdk.py`.

**Identify a thing by what it is, not by a field it happens to carry.** Origin's
review of hub PR #3 found the C++ relic scanner accepting any item with a level
field, so the ordinary item `{b:15, c:8, level:100}` came back as maxed relic 15
- and `ForgePact`'s `RelicFilterMod` calls that scanner directly, so an unrelated
item could suppress a real relic drop. Level-shaped fields are everywhere in this
game's item structs (`p` is a star upgrade count, stacks carry
`amount`/`count`/`qty`), so "has a level" identifies nothing. Use the documented
positive signal instead - rarity tier 16, or the relic-specific `relicLevel` field
(`docs/RUNTIME_DATA_MODELS.md`) - and read the value only from the fields
documented to hold it. The same applies to shape: a bare number is only a
`relic id -> level` entry inside a container that is specifically a relic table,
never in a general inventory.

**Accept the kinds the runtime actually produces, and never let a kind check
decide whether the work happens at all.** `GetOwnedRelicLevels` opened with
`player.m_Kind != VALUE_OBJECT -> return {}`, but this runner resolves the local
player as `VALUE_REF` (kind 15, `docs/RUNTIME_DATA_MODELS.md` §1). So the scan
returned an empty map for every player, and because an empty maxed set means
"nothing to hold back", ForgePact's relic filter armed, hooked, logged
`hook installed -> ON`, and then let every relic through (reported 2026-09-14).
This is a **recurring bug class in this codebase, not a one-off**: `orbpickup`
logged `seen=176993 noplayer=176993`, the relic filter's own arming step never
fired, and upstream had already fixed the same class in the Headhunter
kill/steal path (`HhResolveInstance`, shipped in 1.3.16) — each found
separately, each costing a live session. That is why the kinds now live in a
named `IsInstanceHandle` predicate instead of one more inline comparison. Every accessor involved
(`variable_instance_exists`, `variable_instance_get`) takes a reference straight
through, so the kind was never load-bearing; it only decided whether anything
ran. A feature that reports itself ON while doing nothing is the expensive
shape of this bug: prefer a log line that names what it *did* ("holding back N")
over one that names what it *is*.

**A stub that cannot represent the failing input cannot catch the bug.** Nine
C++ SDK tests passed over that dead scanner because
`tests/cpp/stubs/YYToolkit/YYTK_Shared.hpp` did not define `VALUE_REF` at all
and `FakePlayer()` only ever built a `VALUE_OBJECT` - the test double had
quietly narrowed the world to the half that worked. When a stub stands in for a
runtime surface, its enums and shapes are part of the contract under test: give
it the values the real runtime returns, then assert the two paths agree on one
shared fixture rather than asserting each is separately non-empty. Keep a
negative control alongside (an undefined player still scans nothing), so
widening what is accepted cannot quietly become accepting anything.

**When two language bindings answer the same question, test them against the same
fixture - and make the contract itself comparable.** The Python scanner was
already correct while the C++ one was not, and nothing caught the divergence
because only Python had tests. Adding one shared fixture was still not enough:
origin's second review found the *opposite* gap on the same pair - C++ accepted
`cls` and read numeric arrays out of `relic_levels`, Python did neither - because
a single flat fixture cannot cover a contract. So the accepted fields, limits and
container names are now declared as **enumerable constants in both bindings**
(`kRelicTierFields` / `RELIC_TIER_FIELDS` and friends), the C++ test harness
prints them, and `tests/test_cpp_sdk.py` asserts the two lists match field for
field. Editing one side now fails a test rather than drifting.

Where the two genuinely cannot match - C++ reads named variables off a live
`CInstance` and cannot enumerate a struct's keys, Python walks a whole decoded
save tree - say so in the docs and scope the parity claim to what is actually
shared. Do not claim parity you have not tested.
