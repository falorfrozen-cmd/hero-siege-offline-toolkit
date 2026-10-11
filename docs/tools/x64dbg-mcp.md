# `x64dbg` MCP server: a live debugger on the running game, for `live-operator`

The `x64dbg` entry in [`.mcp.json`](../../.mcp.json) lets a `live-operator`
session attach headless x64dbg to the running, modded game and answer "does
this function fire, with what arguments, how often" through **non-breaking
hardware logging breakpoints**. No research build, no relaunch: the game keeps
running, and each hit becomes one line in the session log. Before it existed,
the same question cost a ForgePact research build with a hook on the
candidate, an install and a relaunch, one round per guess.

It is research tooling for one agent. Nothing about it ships to a player, and
no address it finds may reach shipped code (§ "Addresses: research use only").

[`tools/x64dbg_mcp.py`](../../tools/x64dbg_mcp.py) (modelled on
[`tools/ghidra_mcp.py`](../../tools/ghidra_mcp.py), see
[ghidra-mcp.md](ghidra-mcp.md)) does four jobs: it sets up the pinned x64dbg
snapshot and the pinned plugin, attaches under the hs-drive game lease, tears
down by detaching before anything exits, and serves eight tools of its own over
stdio.

## How it runs

There are three processes:

| Part | What it is | Lifetime |
|---|---|---|
| stdio proxy | `py -3 -m tools.x64dbg_mcp` (what `.mcp.json` and `.codex/config.toml` run): the MCP server the agent talks to, serving our eight tools | one per agent session; connected from session start, whether or not a debugger is attached |
| keeper | a detached `py -3 -m tools.x64dbg_mcp keeper`, started by `attach` | one per debugger session; the only holder of headless's stdin |
| headless x64dbg | `release\x64\headless.exe` from the pinned snapshot, with the plugin loaded; the plugin serves MCP on `http://127.0.0.1:50300/` | started by the keeper, attached to the game, ended by the keeper only after a confirmed detach |

The proxy starts no process and never launches x64dbg. When no session is
attached, every tool that acts on the debuggee refuses with a named reason
instead of guessing. When one is, the proxy forwards to the plugin over
loopback HTTP (initialize, session id, `tools/list`, `tools/call`), and refuses
any host but `127.0.0.1`.

No tool asks x64dbg or the plugin to pause the game, and attaching does not
pause it either (there is no attach break, § "Attach, the keeper, and
teardown"). `logpoint` arms its hardware breakpoint on the running game,
through the keeper and headless's stdin. The game is held only at a
hardware breakpoint's own hit, for the moment a change takes, and resumed at
once (§ "Breakpoint rules"). The keeper resumes every pause x64dbg takes on
its own and reports each one. Whether the
game's threads actually run is checked from outside the debugger, with
`py -3 -m tools.thread_state <pid>` (§ "Checking the game from outside the
debugger").

### Why a stdio proxy, and not the plugin's own HTTP endpoint in `.mcp.json`

The plugin serves MCP itself, so `{"type": "http", "url":
"http://127.0.0.1:50300/"}` would have been the obvious entry. It was rejected
for three reasons:

1. **It is not there when the session starts.** The plugin's server exists only
   while headless x64dbg runs, which is after `attach`, mid-session. An agent
   session connects its MCP servers at start, and an HTTP entry that failed
   then leaves `live-operator` with no tools until someone reconnects it by
   hand. The stdio entry is always connected.
2. **The boundary has to hold under Codex too.** The plugin's whole surface
   includes `StopDebug` (which ends the debuggee, that is, kills the game),
   memory writes, module dumps, binary loading, software breakpoints, stepping
   and an arbitrary-command pass-through. Claude Code's `tools:` allowlist
   covers only subagents, and Codex has no allowlist at all. Our own eight
   tools are a boundary in code.
3. **The plugin reports false success** (issue #484). Its command tool says
   "executed successfully" once a command is *queued*, and its breakpoint-info
   tool reported zero breakpoints that existed. Our tools read back what x64dbg
   actually printed before they report ok.

Before forwarding, the proxy also checks that the plugin's `tools/list`
carries the plugin tool it is about to call and the argument name it will
pass, and refuses naming the mismatch otherwise. Those names were read from
the pinned commit in 2026-10; checking them at runtime keeps a changed plugin
from silently receiving the wrong call.

## Setup on a new machine

**Ask the owner first: `setup` downloads x64dbg, clones the plugin and builds
it.** It needs a .NET 8 SDK and Visual Studio Build Tools (MSBuild), and
installs neither: a missing one is a `missing <what> (<fix>)` line in
`status`.

```bash
py -3 -m tools.x64dbg_mcp status   # resolved paths, pins, what is missing, the installed bind address, session state, the lease
py -3 -m tools.x64dbg_mcp setup    # download + sha256-check, extract, clone + pin, apply our two edits, build, install
```

`status` always exits 0. A `mcp_config.json` that binds anything but
`127.0.0.1` is reported as a `missing` line, not a pass.

`setup` is idempotent: every step is skipped when it is already satisfied, so
an existing install passes through quickly. In order, it:

1. downloads the snapshot zip and checks its sha256;
2. extracts it, and confirms `commithash.txt` matches the pin (that is also
   how `status` identifies an install);
3. clones the plugin and checks out the pinned commit, detached. A working
   tree dirty with anything but our two edits is refused, naming the files;
4. applies our two edits (§ "The pins, and our two edits");
5. builds with MSBuild, found through `vswhere`, on `x64DbgMCPServer.sln` as
   `Release|x64`, with `/restore` and the `RGieseckeDllExport` target (the
   upstream build skips the native-export step, and without it no `.dp64` is
   produced). The environment points `MSBuildSDKsPath` at the .NET 8 SDK and
   sets `X96DBG_ROOT` to a path that does not exist, so the project's own
   post-build copy never fires;
6. installs exactly two files into
   `<x64dbg>\release\x64\plugins\x64DbgMCPServer\`: the built
   `x64DbgMCPServer.dp64`, and a `mcp_config.json` binding `127.0.0.1` and the
   port.

Everything goes outside any git checkout, and `setup` refuses a directory that
is inside one. The defaults follow the layout of the owner's first install:

| What | Default | Override |
|---|---|---|
| x64dbg snapshot (extracted) | `%USERPROFILE%\tools\x64dbg` | `HS_X64DBG_DIR` |
| snapshot download | `%USERPROFILE%\tools\x64dbg-dl` | `HS_X64DBG_DL_DIR` |
| plugin source (clone) | `%USERPROFILE%\tools\x64dbg-mcp-src` | `HS_X64DBG_MCP_SRC` |
| .NET SDK | `%USERPROFILE%\tools\dotnet-sdk`, then `dotnet --list-sdks` | `HS_X64DBG_DOTNET` |
| session state and log | `%USERPROFILE%\tools\x64dbg-mcp-session` | `HS_X64DBG_MCP_SESSION` |
| plugin port | `50300` | `HS_X64DBG_MCP_PORT` |

The plugin's host is always `127.0.0.1`; there is no override for it.

## The pins, and our two edits

- **x64dbg**: snapshot release `2026.05.27`, asset
  `snapshot_2026-05-27_12-11.zip`, checked against its sha256 in
  `tools/x64dbg_mcp.py`; the extracted tree's `commithash.txt` reads
  `9c8ca1cae0b6d56cc44f31fddcb10e3b02ffbb87`. Only `headless.exe` is used: in
  GUI mode the first-run Release Notes dialog blocked log capture while every
  tool still reported success.
- **The plugin**: [AgentSmithers/x64DbgMCPServer](https://github.com/AgentSmithers/x64DbgMCPServer)
  at commit `a8303d7` (`PLUGIN_COMMIT` in `tools/x64dbg_mcp.py` holds the full
  hash).

`setup` makes two edits to the plugin's source in the local clone, both made
by hand and used in the 2026-10-10 probe first:

1. **Loopback bind.** The plugin's default listen address is every interface
   (which also needs admin rights or a URL reservation). The edit makes its
   default, and its fallback when the configured address is blank,
   `127.0.0.1`.
2. **Braces in log lines.** The plugin's log writer passes every line through
   .NET's `string.Format`, even when there are no arguments, so any log line
   holding `{` or `}` throws "Input string was not in a correct format". That
   makes x64dbg's logging breakpoints unusable, since their format strings are
   brace expressions. The edit passes a line with no arguments through
   unchanged.

They are applied as in-code edits in `tools/x64dbg_mcp.py`, not as patch
files: each is a file, the short upstream fragment it anchors on, and its
replacement, applied only when the fragment occurs exactly the expected number
of times. An already-applied edit is detected and skipped, CRLF and LF are both
handled (the clone can hold LF where git expects CRLF), and anything else is
refused, naming the file. A unified diff would carry three lines of the
plugin's context per hunk, and the plugin has no license (next section).

### License position

The plugin's repository has **no LICENSE file**, so this repository carries
none of its source: no vendored file, no patch file with its context lines, no
excerpt in a doc. It carries only the URL, the commit, and our two edits as the
launcher applies them, anchored on fragments that are identifiers and a single
expression, not copied bodies. The clone, the build and the install stay on the
owner's machine. x64dbg itself is downloaded from its own release by `setup`
and never redistributed from here. Upstream pull requests for the two edits
are deferred.

## The eight tools

`LIVE_OPERATOR_TOOLS` in [`tools/x64dbg_mcp.py`](../../tools/x64dbg_mcp.py) is
the set, and each is named `mcp__x64dbg__<tool>` on an agent's `tools:` line:

| Tool | What it does |
|---|---|
| `mcp__x64dbg__status` | session state (`none`, `attaching`, `attach-unconfirmed`, `running`, `detaching`, `ended`, `detach-unconfirmed`, `game-not-released`), the target pid, whether the keeper and headless are alive, whether the plugin answers on loopback, and the hs-drive lease state. Beside those, the keeper's own record: `x64dbg_state` (x64dbg's settled state, read from its `[STATE]` lines), `breaks_resumed`, `last_break`, `break_storm` and `instrument` (§ "Attach, the keeper, and teardown"), and `paused_at_detach` and `game_released` once a teardown has set them. While a session is live it also carries `game`, a fresh outside check of the game (§ "Checking the game from outside the debugger") |
| `mcp__x64dbg__logpoint` | adds one non-breaking hardware logging breakpoint: an `address` (an x64dbg expression such as `Hero_Siege.exe+427460`), a `log` format string (`{` `}` allowed, `"` refused), an optional log condition, an optional name, and an optional `expect_bytes`: the function's first bytes as Ghidra's copy has them, in hex. It first reads the code at the address and returns its first bytes; with `expect_bytes` a mismatch is refused before anything is set. It refuses `break_storm` while the session has one, `not_running` unless x64dbg's settled state is `running`, and `already_armed` when `bplist` already lists the address. Then it arms through headless's stdin, with no plugin pause, in one keeper hold. With no hardware breakpoint armed yet (the control), it sends a breaking `bph <A>, x, 1` and holds the game at A's own first hit; there it takes the outside check (`hold_game`, which must read `frozen`, and which proves the instrument as its control hold), sets the never-break condition `SetHardwareBreakpointCondition <A>, 0`, the log text, the optional log condition and name, reads `bplist`, and sends `run`. A cold address that is not hit within the hold timeout (10 s) is armed never-break on the running game instead, with `held: null` and a `held_note`, and proves nothing. While another logpoint is logging (a candidate), the same lines go out as a held change at that logpoint's hit (§ "Breakpoint rules"). It fails at stage `set` (a failure line from x64dbg, no `Hardware breakpoint at <A> set!` line, no `bplist` row for A, or a row without the name given), `listed-but-disabled` (A's row starts `0:`), `running` (x64dbg broke on A again in the 1.5 s after the hold: its never-break condition did not take) or `game-not-running` (the outside check after arming reads anything but `running`). Every failure clears A with a hold of `bphc <A>` and returns `cleared` and `x64dbg_state`. Success returns `steps`, `bplist`, `held` (the break line the game was held at while the rest was set: A's own first hit for the control, the logging breakpoint's hit for a candidate, or null), `hold_game` (at a first hit), `x64dbg_state` and `game`, the outside check after the resume. It never calls the plugin's `PauseDebug`, `run` or `ExecuteDbgCommand` |
| `mcp__x64dbg__command` | one allowlisted x64dbg command, sent on headless's stdin (not through the plugin, § "Breakpoint rules"): delete, enable or disable a hardware breakpoint, name it, set its log condition, reset its hit count, or `bplist`. The verbs that change debug registers (`DeleteHardwareBreakpoint`/`bphc`/`bphwc`, `EnableHardwareBreakpoint`/`bphe`/`bphwe`, `DisableHardwareBreakpoint`/`bphd`/`bphwd`) go through a keeper hold, a held change while a logpoint is logging, and return its `lines`, `after` (with the `bplist` that followed), `held` and `x64dbg_state`. The others change only x64dbg's list and go straight to stdin, returning the log lines that followed. Everything else is refused, naming the allowlist: in particular a new hardware breakpoint (use `logpoint`), every software or memory breakpoint, setting a breakpoint command, `StopDebug`, `detach`, `exit`, memory writes, and any command with a `;` outside a double-quoted string. Reading a hit count is not on the list: x64dbg's `GetHardwareBreakpointHitCount` sets `$result` and, as far as is known, prints nothing, so it would answer ok with no number |
| `mcp__x64dbg__bplist` | sends `bplist` and returns the log lines it produced |
| `mcp__x64dbg__log` | the session log's lines after a given line number (by default the last 200), with the total line count, so logging-breakpoint hits can be paged |
| `mcp__x64dbg__modules` | the loaded modules from the memory map; gives `Hero_Siege.exe`'s base. `bases` holds only rows in the pinned plugin's format (decimal behind `0x`, § "Breakpoint rules"); a row in any other format is listed under `unreadable`, with a note, and an address in that module is refused with `module_row_unreadable` |
| `mcp__x64dbg__disasm` | disassembly at an address, for checking that an address maps to the function Ghidra names (it stays local; § "What stays local") |
| `mcp__x64dbg__detach` | the teardown in § "Attach, the keeper, and teardown", through the keeper: a held `bphc`, a confirmed `detach`, `exit`, then the outside check that every game thread runs again, reported as `game_released`. A detach that left game threads suspended is the state `game-not-released`, with `ok: false`, naming the threads and the recovery |

The `command` allowlist's exact spellings are in `tools/x64dbg_mcp.py`, which
is their source. Every tool that acts on the debuggee also refuses when no
live hs-drive lease is held.

**The same eight from a shell.** A session that has not loaded the
`mcp__x64dbg__*` tools (one started before the server entered `.mcp.json`, for
instance) calls them through the CLI instead:

```bash
py -3 -m tools.x64dbg_mcp tool status
py -3 -m tools.x64dbg_mcp tool log '{"after": 120, "limit": 5000}'
```

`tool <name> [<json object of arguments>]` calls the same `Tools` method that
`serve` registers, so the gates are the same (an attached session, a live
lease, the allowlist), under the same offline guard. It prints the tool's
reply as one JSON object and exits 0 when the reply's `ok` is true, 1 when it
is not. A name outside the eight, arguments that are not one JSON object, or
an argument the tool does not take (or a required one left out) exits 2,
naming the problem, before anything is called. Never import the module
through `py -3 -c` instead: that route is unsupported and skips the guard.

**A stale server refuses.** A stdio MCP server lives as long as the session
that started it and keeps the code it imported, so after `tools/x64dbg_mcp.py`
changes on disk it speaks an older protocol than the keeper and the guide. In
Live 3's rerun 3 (measured) the session's servers predated the arming commit:
they sent the breaking `bph` as a direct batch, and the keeper, on current
code, resumed the first hit as a stray pause, so the first-hit hold never ran.
So the module records `CODE_ID`, its own file's sha256 at import. While the
file on disk hashes differently, every tool but `status` refuses with reason
`stale_server`, and `status` reports `code_current` false (true otherwise).
The keeper checks the same id: `keeper_request` stamps each request with its
`code_id`, and the keeper refuses a hold or send from other code with
`stale_server` before anything reaches x64dbg; a `detach` request is served
whatever code sends it (`status` and `log` read files and never ask the
keeper). The remedy is to restart the MCP server, or to use the
CLI route above, which imports the file fresh on every call; the CLI
`py -3 -m tools.x64dbg_mcp detach` always gives the game back, so a stale
server never strands an attached game. A keeper that is itself the older one
refuses the fresh CLI too: detach and attach again.

**Left out on purpose:** breaking breakpoints, stepping, registers and call
stacks. Each one stops the game's loop (AGENTS.md § "Don't Suspend the Game's
Own Runtime"). A logging breakpoint can log the return address and the argument
registers without stopping anything.

## Breakpoint rules

These come from the 2026-10-10 probes recorded on issue #484.

- **Hardware breakpoints only (`bph`).** INT3 software breakpoints collide with
  ForgePact's inline detours. x64 has **four** debug registers, so at most
  four hardware breakpoints at once: the positive control and three
  candidates. More candidates are re-armed in the same session (clear one with
  `command`, add the next with `logpoint`), not in a new build.
- **Every debugger session starts with a positive control**: a `logpoint` on a
  function known to fire, with its hits read through `log`. A debugger session
  whose control logs nothing measured the instrument, not the game, and its
  negatives close nothing (AGENTS.md § "Prove the Instrument Before Trusting a
  Negative Result"). Measured on game 7.0.13.0: `CheckTalentUse` at
  `Hero_Siege.exe+427460` logged about 85 hits/s in town, with `self == other`
  and `argc=3`, read from RCX, RDX and R9D. A procedure names its own control;
  this one is an example for that build only.
- **Verify with `bplist`, never with `GetBreakpointInfo`.** The plugin's
  `GetBreakpointInfo` reported 0 breakpoints that `bplist` listed. A `bplist`
  row reads `<enabled>:<type>:<address>`, then `:"<name>"` when it has one.
  The first field is `1` for an enabled breakpoint and `0` for a disabled
  one, and the type is `HW` for a hardware breakpoint. A `0:HW:` row is listed
  and never logs, so `logpoint` accepts only `1:HW:`, and the `bplist` tool
  returns the disabled rows apart.
- **Check each candidate's bytes before trusting its zero.** A hardware execute
  breakpoint fires only where an instruction starts. An address that is stale
  (a Ghidra project from another build) or lands mid-instruction arms without
  complaint and never logs, and the positive control proves only its own
  address. So pass `expect_bytes`, the first bytes of the function in Ghidra's
  copy, to every candidate's `logpoint`. A candidate armed without it returns
  its bytes and a note, and its zero is not evidence until they are compared.
  A function ForgePact detours starts with the detour's jump in the live
  process, not with Ghidra's bytes, so expect a mismatch there.
- **The module table's numbers are decimal behind `0x`.** The pinned plugin's
  `GetAllModulesFromMemMap` prints each module's base, end and size as decimal
  digits after a literal `0x` (it asks for hex, but on the .NET Framework it
  targets, a pointer-sized integer ignores the format). Measured live on
  2026-10-10: the game's row read `0x140694867017728 0x140695154032640
  0x287014912`, which is base `0x7FF613920000`. So `modules` and every
  `<module>+<offset>` address read those columns as decimal, and only a row
  whose three columns are decimal with no leading zero, whose end equals
  base plus size, and whose base sits on a 64 KiB boundary, as every image
  Windows maps does. The last rule catches an unpadded hex rendering made only
  of the digits 0-9 with no carry from base to end (`0x180000000 0x180001000
  0x1000` reads as a decimal sum too, but 180000000 is not on a boundary). A
  row in any other format (a later plugin build, a hex rendering) gives no
  base: `resolve`, and so `logpoint` and `disasm`, refuse with
  `module_row_unreadable`, quoting the row, rather than guess between hex and
  decimal and misresolve, and `modules` lists the row under `unreadable`. A
  module with no row at all is `no_such_module`. The other plugin outputs the tool parses (the
  `ReadDismAtAddress` listing) are hex, as before.
- **No tool pauses the game, because x64dbg's pause cannot be detached from
  safely.** Before the no-pause rework that followed Live 2, `logpoint`
  paused the game through the plugin's `PauseDebug`, armed, and resumed
  through the plugin's `run`. Live 2 (2026-10-10) measured why that cannot
  stand. `PauseDebug` is asynchronous: it answered that the process "may still
  be settling", the tool's fail-path `run` answered RUNNING, and x64dbg then
  printed `paused!` and `[STATE] paused` after that `run`. The game ended
  paused while the tool reported it running. The static reading (x64dbg
  9c8ca1c, TitanEngine ec7a8b9) explains it: x64dbg's `pause` plants a
  non-single-shot software breakpoint at the current instruction of the
  thread that raised the last debug event and returns at once, so the game
  pauses only when some thread executes that instruction, seconds later or
  never, and a `run` sent meanwhile does nothing and cannot cancel it. Then
  the synchronized step: on Windows 10 and later, TitanEngine single-steps a
  thread past such a breakpoint (and past every hardware breakpoint hit) with
  every other thread suspended by `SuspendThread`, and resumes them when the
  step completes. A detach requested while that step is pending stops
  debugging without resuming them, and x64dbg's `detach` releases a paused
  event only after asking TitanEngine to detach, so detaching while paused
  at the pause breakpoint always takes that path. Live 2 measured the result:
  after a confirmed detach, 69 of 71 game threads sat in the Suspended wait,
  the game answered nothing, and only a force-stop ended it. So `logpoint`,
  `command` and the teardown never call `PauseDebug`, the plugin's `run` or
  `ExecuteDbgCommand`: they work through the keeper, which writes headless's
  stdin. Live 1 had measured the old route's cost too: each plugin command
  held the game about 3.4 s, and ForgePact's incident monitor episodes rose
  0, 2, 4, with a worst judged frame of 12032 ms.
- **A hardware breakpoint's hit is the only hold, the control hold among
  them.** Measured in Replan 3's probe, against a throwaway process and not
  the game: a breaking hardware execute breakpoint holds the target on its
  first hit about 10 to 15 ms after `bph`, synchronously, with every thread
  at suspend count 1, so the outside check reads `frozen`: every thread in
  the Suspended wait but the breaking thread that raised the hit, which
  waits in an Executive wait ("When the instrument is proven" in § "Attach,
  the keeper, and teardown"). `[STATE] paused` is the reliable sign of the hold; the
  descriptive `Hardware breakpoint (...)` line can come a beat later. And a
  detach while held at such a hit, with no clear and no `run` first, printed
  `Detached!` and `[STATE] stopped`, and left every thread running at
  suspend count 0: the opposite of Live 2. The static reading agrees: a
  hardware breakpoint that broke leaves no synchronized step pending once it
  is removed, and the detach clears the trap flag on every thread first. So
  the freeze risk belongs to the plugin's pause and its software breakpoint,
  which no tool path uses. The first such hold of a session is the **control
  hold**: the outside check taken there is the instrument's frozen reading
  (§ "Checking the game from outside the debugger"). A held thread still
  switches once per memory-map refresh: x64dbg reads every thread's context
  about once a second while it holds the game, and each context read
  schedules a held thread once without running its code (measured on a
  throwaway, 2026-10-11; who reads is a static reading of x64dbg's source).
  The outside check counts those switches as held (`touched`), within a
  bound a running game never meets.
- **The first hit as the hold.** Arming the first breakpoint of a session
  (the positive control) sends a breaking `bph <A>, x, 1` on the running
  game and waits up to the hold timeout (10 s) for a new `[STATE] paused`:
  A's own first hit, which comes within one frame for a function that runs
  every frame. Setting a hardware breakpoint on the running game works, and
  a `bph` with no condition yet breaks on its first hit (both measured in the
  issue #484 probe). Before the `bph` the keeper settles any pause already
  pending (resuming it as the watchdog would), so an earlier stray pause is
  not taken for the first hit; when x64dbg does not settle at running within
  the hold timeout, nothing is sent. The hit can also come exception-shaped
  (measured once, Live 3 rerun 3): x64dbg prints `[TODO] Not implemented
  GUI_SET_LAST_EXCEPTION (37)`, then `[STATE] paused`, before the batch's
  begin marker and before `set!`, then `First chance exception on <A>
  (80000004, EXCEPTION_SINGLE_STEP)!`, then "set!" after it; the keeper
  takes the pause as the hold all the same, names the first-chance line as
  its break line (`held`), and never counts the `[TODO]` notice as a break
  line or as `last_break`. Which of the two shapes appears when is not
  established. Held there, the keeper takes the outside check (the
  control hold), then sets the never-break condition, the log text, the log
  condition and the name, reads `bplist`, and sends `run`. Nothing else is
  armed, so nothing races the change. A hold that carries the breaking `bph`
  among its lines with nothing armed (an older client's shape) goes through
  the same first-hit hold. When A is not hit within the hold
  timeout (a cold address, not a control), the same lines go out on the
  running game, `held` is null with a `held_note`, and the instrument is not
  proven by it. After the hold, a 1.5 s verification window follows: a break
  line naming the address (its 16 hex digits or its name) and then `[STATE]
  paused` means the never-break condition did not take, and `logpoint`
  clears the breakpoint and fails at stage `running`. The outside check of
  the game comes last: anything but `running` is stage `game-not-running`.
- **A change while another breakpoint logs is a held change.** Static
  reading, not measured: TitanEngine's `SetHardwareBreakPoint` and
  `DeleteHardwareBreakPoint` each read DR7 once, from the thread of the last
  debug event, change their own bits and write the result to every thread,
  with no lock, and x64dbg's debug loop runs that delete and a re-arm around
  every logpoint hit. A change sent from the command thread while another
  hardware breakpoint is logging can therefore write stale DR7 bits: it can
  disarm a breakpoint that x64dbg and TitanEngine still list as enabled,
  which turns a candidate's zero into a false negative, or re-arm one x64dbg
  has deleted. So whenever `bplist` shows an enabled hardware breakpoint, a
  change to the debug registers is held: the keeper sets each armed one's
  break condition to 1 and waits up to 2 s for a new `[STATE] paused`, one
  that came after the conditions were set (a pause already there, such as
  one the watchdog has not resumed yet, does not count). The game is then
  held at a hit of a breakpoint that was logging, where nothing is mid-hit
  and the change cannot race the debug loop. The keeper sends the lines,
  restores each condition to 0, reads `bplist`, and sends `run` at once. The
  reply's `held` is the break line it paused at. When no armed breakpoint is
  hit within 2 s, the conditions go back to 0, the lines go out as a direct
  batch, and the reply has `held: null` and a `held_note` saying so. A live
  check that the control keeps logging across a candidate's arm measures this
  guard; until one has run, the guard is a reading. How long a held change holds the game
  is not yet measured; take `hs_command` `incident stat` right after each
  `logpoint` so a later slowdown window does not count it.
- **x64dbg pauses the game on its own, and the keeper resumes every one.**
  x64dbg's `[Events] TlsCallbacks=1`, its default and this headless install's
  `headless.ini` value, makes it set a single-shot breakpoint on each
  non-system module's TLS callbacks as the module loads; they fire on the
  next thread start or exit and pause the game (static reading). Measured in
  Live 2: six of them right after attach (discordhook64, steamclient64,
  tier0_s64, eossdk-win64-shipping, and auriecore twice), each an
  `INT3 breakpoint "TLS Callback <n> (<dll>)"` line and `[STATE] paused`. A
  DLL that loads mid-session gets one too. A hit on a breakpoint x64dbg no
  longer lists, such as a re-armed deleted one, or on a disabled one, prints
  `Breakpoint reached not in list!` and pauses (static reading). The keeper's
  watchdog resumes each such pause on stdin, counts it in `breaks_resumed`,
  keeps its break line and time in `last_break`, and sets `break_storm` at
  ten resumes within 10 s (§ "Attach, the keeper, and teardown"). x64dbg's
  settings stay as they are: the tool resumes these pauses rather than switch
  them off.
- **A stale breakpoint from x64dbg's database is cleared at attach.**
  Measured in Replan 3's probe: x64dbg saves a module's breakpoints in its
  database and restores them when it next attaches to the same image,
  printing `Set hardware breakpoint on <16 hex digits>!` for each before any
  command; a breakpoint left by one probe run came back on the next attach,
  and a fresh `bph` on it answered `Hardware breakpoint already set!`. A
  clean teardown (`bphc`, then a detach that saves the database) leaves
  nothing behind, but an aborted session can. So once x64dbg has settled at
  `running` after an attach, the keeper sends one `bphc` (and a `bplist`),
  recorded in the session as `attach_bphc`. Nothing legitimate is armed at
  that point, and nothing is logging, so the clear cannot race.
- **The plugin's `ExecuteDbgCommand` reply, for the record.** No tool path
  uses it now. At the pinned commit the plugin never hands back a blank
  reply: when x64dbg printed nothing it answers `Result: Command executed
  successfully (no output captured)`, and `Result: Command execution failed
  (no output captured)` when the command could not be queued to x64dbg's
  command thread. The reply is everything that reached x64dbg's log while
  the command ran, and that includes the plugin's own echo of the call: Live 1
  (2026-10-10) measured all five echo lines in one reply and only the last
  in another. `silent_reply_ok` and `plugin_echo` in `tools/x64dbg_mcp.py`
  keep that measured shape, with their tests.
- **Keep the control armed while a candidate's zero is read.** Clear
  candidates to free a debug register, never the control: a zero with no
  control logging in the same window measured nothing.
- **Counting hits.** Count from the log, not from x64dbg's hit counter, which
  `command` cannot read. Put a counter field in the `log` string, such as
  `hit #{d:$breakpointcounter} rcx={rcx}`, or count the lines in `log`. The
  `$breakpointcounter` field comes from x64dbg's documentation and is **not
  yet measured live**.
- **The session log has no gap.** Static reading: commands on headless's
  stdin and the plugin's `DbgCmdExec` go to the same x64dbg command thread,
  first in, first out, and headless prints every log message on stdout (the
  session log), unbuffered, writing it to a plugin's log-redirect file only
  in addition. So hits during a plugin call reach the session log, and no
  arming goes through the plugin any more anyway. A held change holds the
  game at one hit, so the control's counter (`#{d:$breakpointcounter}`,
  above) should run on across a `logpoint` with no jump. That is expected,
  not yet measured: no live session has yet checked that the counter runs on
  with no jump across a candidate's arm, or that the control still logs
  after it.
- **Health under load.** The game stayed healthy under about 50 s of logging:
  ForgePact's `ping` answered and no slowdown episode was seen. The game's
  exit `0xC0000409` on close matched the known `HSOfflineTrackerProducer.dll`
  abort. That the debugger caused it is "not observed", not "ruled out".

### Addresses: research use only

On game 7.0.13.0 the mapping

```
runtime address = Hero_Siege.exe base + (Ghidra address - 0x140000000)
```

held (Ghidra's image base is `0x140000000`; `modules` gives the runtime base).
That is how a function found in the Ghidra project becomes a `logpoint`
address. An address found this way is a **research finding** for `docs/`, and
it never reaches shipped code (AGENTS.md
§ "Never Call an Address You Resolved by Hand"). Shipped code resolves by
name.

## Attach, the keeper, and teardown

The game lease comes first. `live-operator` already holds hs-drive's
machine-wide lease (`hs_lease_acquire`) when it reaches a debugger step, and
`attach` refuses unless that lease is held by a live process.

```bash
py -3 -m tools.x64dbg_mcp attach --game    # the sole running Hero_Siege.exe
py -3 -m tools.x64dbg_mcp attach <pid>     # or a pid whose image is Hero_Siege.exe
py -3 -m tools.x64dbg_mcp detach           # exits 0 only on a confirmed detach
```

`attach` refuses, with a named reason, unless: the lease is held by a live
process; the target is `Hero_Siege.exe` (with `--game`, none or several
running is a refusal); x64dbg and the plugin are installed; no session is
already live; and the outside check reads the game `running` before anything
attaches (`game_not_running` otherwise, and `game_unreadable` when the check
reads `unreadable` or `unsupported`, since without it no detach can be shown
to release the game). That check is the session's baseline. `attach` then
starts the detached keeper and returns once the keeper reports `running`,
`attach-unconfirmed` (exit 1, below), or failed.

- **There is no attach break: x64dbg does not pause the game on attach.**
  Measured four times in Replan 3's probe against a throwaway process, and
  matching Live 3: after `attach` the only state lines are `[STATE]
  initialized` and `[STATE] running` (twice), then `Attached to process!`
  and the DLL loads, and never `[STATE] paused`. The static reading of this
  headless build and its TitanEngine (ec7a8b9) agrees: it attaches through
  `NtDebugActiveProcess` with the remote break-in compiled out, and the
  initial breakpoint of an attached process takes the "program generated"
  branch, which does not set the paused state. Live 3's 61 s
  `attach-unconfirmed` was the keeper of that time waiting for an attach
  break that never comes. The pauses Live 2 saw just after attach were
  x64dbg's TLS-callback breakpoints (§ "Breakpoint rules"). What the earlier
  sessions timed was attach **latency**, not an x64dbg hold: the probe of
  issue #484 saw 10.65 s, and in the first live session (2026-10-10,
  `tooling-484-x64dbg-mcp` live 1) `attach` took 8.53 s wall clock while
  ForgePact's incident monitor recorded one freeze episode with a worst
  frame of 4201 ms. That is symbol loading and the game hitching while the
  kernel's debug port attaches (measured by the incident monitor; the cause
  is a reading).
- **The attach sequence, with no attach break.** The keeper sends `attach`
  on headless's stdin, and from then on resumes every pause x64dbg takes on
  its own (a TLS-callback breakpoint, a late break), counted. It waits for
  three things: the plugin answering a debug-only call; x64dbg's state
  settled at `running` for 1 s with no new `[STATE]` line; and the outside
  check reading the game `running` (`ready_check`). Once x64dbg has settled,
  before that last check, it sends the one defensive `bphc` that drops a
  stale breakpoint restored from the database (§ "Breakpoint rules"). Then
  the session is `running`, with `ready: true`. **The instrument is not yet
  proven at this point**, because attach holds nothing, so there has been
  no frozen reading: the session's `instrument` field holds
  `before_attach` (the baseline), `control_hold: null`, `after_resume: null`
  and `proven: false`, with a `note` saying what is still missing. The
  frozen reading comes later, at the first logpoint's control hold.
- **When the instrument is proven.** `proven` turns true only for the
  sequence running before attach, `frozen` at the control hold with the held
  threads named, and `running` after its resume. At the control hold
  `suspended` and `stopped` must each list every thread the check before
  attach saw (less the baseline's), and `unreadable_counts` must be empty; a
  thread first seen at the hold is left out. There is one exemption, the
  breaking thread: the thread that raised the hardware-breakpoint hit waits
  for the debugger's reply in an Executive wait, not Waiting/Suspended, so
  `stopped` rightly leaves it out (measured on the Replan 3 probe's
  throwaway process, 2026-10-10, not yet on the game: suspend count 1, no
  context switch across the samples, wait reason Executive, while the six
  other threads read Waiting/Suspended). "No context switch" here, and for
  every thread in `suspended` and `stopped`, allows a debugger's context
  reads: 1 to `CONTEXT_READS` (2) switches with a suspend count of 1 or
  more in every sample (the check's `touched`). It is exempt only on that
  signature: it is the single thread missing from `stopped`, it is in
  `suspended`, it is in the check's `executive_waits`, and no other expected
  thread is in `executive_waits`. Two expected threads in an Executive wait,
  a missing thread with suspend count 0 or that switched, a missing thread
  not in an Executive wait, or a check that carries no `executive_waits`
  field is the same gap as any other. The exempted thread is recorded as
  `control_hold.breaking_tid`, and `instrument.note` names it; with no
  exemption `breaking_tid` is absent. x64dbg's own output names no thread
  on a hit line in the probe's log, so the signature is the only source of
  the tid. The keeper takes the control hold's check no sooner than
  `HOLD_SETTLE` (0.25 s) after it saw the pause: x64dbg reads the breaking
  thread's context at the pause (measured within 6 ms of `[STATE] paused`
  on a throwaway, 2026-10-11), and the settle puts those reads, and a
  memory-map refresh at the pause, behind the check's window, for at most
  0.25 s more hold. A `frozen` with empty lists
  could come from a check that read no thread at all. A check that does not
  read the held game as frozen, or does not name the held threads, saw
  nothing: `proven` stays false, `instrument` carries a `note` naming each
  missing piece, and its later `running` verdicts prove nothing (AGENTS.md
  § "Prove the Instrument Before Trusting a Negative Result"). A detach of a
  session whose instrument was never proven reports `game_released: null`
  with `ok: false` rather than a release, so a live procedure arms its
  control before it tears down.
- **An attach the keeper did not see through is `attach-unconfirmed`**, not
  `running`, with `ready: false` and an error naming which of the three was
  not seen within the ready timeout (60 s): the plugin never answered a
  debug-only call, x64dbg never settled at `running` for 1 s (with the number
  of pauses resumed meanwhile), or the outside check read the game as
  something other than `running`. The keeper keeps resuming every pause, and
  makes the session `running` once all three hold. Until then every tool but
  `detach` refuses the session, `attach` exits 1 and says the game may be
  paused, and the thing to do is `detach`.
- **The watchdog.** While the session is `running` or `attach-unconfirmed`,
  the keeper's loop reads x64dbg's settled state, and whenever it is
  `paused` sends `run` on stdin: one `run` per pause, and another for the
  same pause only when the first brought no new `[STATE]` line within 2 s.
  Each resume counts in `breaks_resumed` (a hold's own pause, at a first hit
  or in a held change, is the keeper's and does not count), and `last_break`
  keeps its break line and time. A break line is `paused!`,
  `INT3 breakpoint ...`, `Hardware breakpoint (...)` or
  `Breakpoint reached not in list!`, or failing those, the line just before
  the `[STATE] paused`. Ten resumes within 10 s set `break_storm: true`,
  which stays set until detach: `logpoint` then refuses with `break_storm`,
  and `detach` is still served. A hold and a teardown resume pauses the same
  way while they settle. This is what keeps the game from staying paused
  through any pause the tools did not ask for.
- **x64dbg's own state comes from its `[STATE]` lines, never from the
  plugin.** Headless prints `[STATE] <name>` on stdout (`initialized`,
  `paused`, `running` or `stopped`) for every debug-state change: once at
  once, and again within about 300 ms from a rate-limited task that always
  carries the latest state (static reading; Live 2's session log shows the
  pairs). A non-breaking logpoint hit prints none. So the last `[STATE]`
  line, once 0.4 s pass with no new one, is x64dbg's current state, and
  reading it changes nothing. That is `x64dbg_state`. The plugin's `run` and
  `PauseDebug` answers read `DbgIsRunning()`, which is false whenever
  x64dbg's run lock is held, and x64dbg takes that lock while it processes
  every breakpoint hit, a non-breaking logpoint's included (static reading).
  So during logging a plugin `run` can answer PAUSED while the game runs, and
  asking changes the state as well.
- **The keeper is the only holder of headless's stdin** for the session's
  whole life. What headless does on stdin EOF, and whether it ends the
  debuggee by exiting while attached, is not established. So the keeper is
  detached (its own process group, no console), an operator's shell ending
  cannot close the pipe, no Ctrl event reaches headless, and **nothing ever
  kills headless while it is attached**. Headless's output goes to the session
  log, and the state to a JSON file beside it.
- **Teardown** (the `detach` tool or the CLI), in order:
  1. a held `bphc` (held when a logpoint is logging), clearing every
     hardware breakpoint;
  2. a settle at `running`, resuming any pause, for 10 s at most. If x64dbg
     never settles, the state records `paused_at_detach: true` and the
     detach goes ahead: no tool path plants a pause breakpoint any more, and
     the outside check decides;
  3. `detach`, confirmed when the plugin reports no session and the log has
     `Detached!`;
  4. `exit`. Only after a confirmed detach may the keeper end a headless
     that has not exited;
  5. the outside check, leaving out the threads the baseline already found
     suspended or stopped. `running` ends the session `ended` with
     `detach_confirmed: true` and `game_released: true`, when the checks
     before attach, at the control hold and after its resume proved the
     instrument; when they did not, it ends `ended` with `game_released: null`, `ok: false` and a
     note that the instrument was not proven, and the CLI exits 1. `gone`
     ends it `ended` with `game_released: null` and a note. Anything else is
     `game-not-released`.

  An unconfirmed detach leaves headless alone, sets the state to
  `detach-unconfirmed`, and fails loudly: the game stays running and the lease
  stays held, and whoever is running the session says so.
- **`game-not-released`: the detach was confirmed, and the game's threads
  were not given back.** The reply has `ok: false`, `detach_confirmed: true`
  and `game_released: false` (`null` when the check read `unreadable`), and
  `game` holds the check. Its error names each suspended thread with its
  suspend count and each stopped thread. Only a force-stop releases them:
  these tools never resume a game thread (no `ResumeThread`, no x64dbg
  `resumeallthreads`). The driver runs `hs_stop_game` with `force=true`, then
  `hs_saves_restore` of this session's backup; `live-operator` returns
  `LIVE-ABORTED` with the lease still held and does neither. It is not a live
  state. The CLI `detach` exits 0 only for `ended` with `game_released` true,
  or for a game that was gone.
- **Order in a live session: `detach` before `hs_stop_game`.** Stopping the
  game under an attached debugger is the case nobody has measured.

## Checking the game from outside the debugger

`py -3 -m tools.thread_state <pid>` ([`tools/thread_state.py`](../../tools/thread_state.py))
reads one process's threads from the OS and touches nothing: it opens
threads with `THREAD_QUERY_LIMITED_INFORMATION` only, never suspends,
resumes or signals anything, and answers `unsupported` anywhere but Windows.
It is how the tools, and the live procedure independently of them, know
whether the game runs, without asking the debugger.

```bash
py -3 -m tools.thread_state <pid> [--samples N] [--interval S]
```

It prints one JSON object and exits 0 for `running`, 1 for any other
verdict, and 2 for a usage error. The fields:

| Field | Meaning |
|---|---|
| `verdict` | `running`, `frozen`, `threads-suspended`, `gone`, `unreadable` or `unsupported` |
| `threads` | the number of threads |
| `progress` | the summed context-switch increase from the first sample to the last, over the threads present in both |
| `suspended` | `[{"tid": n, "suspend_count": k}]`, each thread whose suspend count is 1 or more in every sample and whose own context switches did not advance across the window beyond a debugger's context reads (`touched`) |
| `stopped` | the tids in the Waiting/Suspended state with no context switch across the window beyond a debugger's context reads (`touched`) |
| `executive_waits` | the tids in the Waiting state with wait reason Executive (0), a suspend count of 1 or more in every sample and no context switch across the window beyond a debugger's context reads (`touched`): the breaking thread's signature at a hardware-breakpoint hold (measured on a throwaway process, 2026-10-10). Baseline threads are left out, and it plays no part in the verdict |
| `touched` | the tids with a readable suspend count of 1 or more in every sample whose own context switches across the window are 1 to `CONTEXT_READS` (2): held threads a debugger's context reads scheduled without running them. Baseline threads included; empty on a `gone`, `unreadable` or `unsupported` result |
| `unreadable_counts` | the tids whose suspend count could not be read in some sample (never read as 0) |
| `tids` | every thread present in every sample, so a caller can tell whether `suspended` and `stopped` cover the threads it expected |
| `samples`, `interval` | how it sampled (by default 3 samples, 0.4 s apart) |
| `detail` | one sentence naming the counts |

The verdict, in order: no such process is `gone`; not Windows is
`unsupported`; a failed sample is `unreadable`; no context switch on any
thread outside `touched` is `frozen` (with nothing touched, that is
`progress` 0); a non-empty `suspended` or `stopped` is
`threads-suspended`; a non-empty `unreadable_counts` is `unreadable`;
anything else is `running`. `progress` stays the raw sum, touched threads
included, and `detail` names the touched count. A thread with more than
`CONTEXT_READS` switches, or a suspend count of 0 or unread in any sample,
is never touched. A thread whose suspend count cannot be read is
listed in `unreadable_counts`, counted in `detail` and never read as 0, so
it never reads `running`. Threads in the baseline are left out of
`suspended`, `stopped` and `unreadable_counts`. Only a suspension
seen in every sample counts: x64dbg suspends every other thread for each
logpoint hit's step, so one sample during logging can catch everything
suspended. An idle process reads `frozen`; the game renders every frame, so
it never idles. The keeper passes the baseline's tids, so threads already
suspended before attach are not blamed on the detach.

How it reads them, measured on this machine (Windows 11 build 26300, x64) on
2026-10-10: `NtQuerySystemInformation(SystemProcessInformation)` gives each
thread's id, scheduling state, wait reason and context-switch count, and
`NtQueryInformationThread` with `ThreadSuspendCount` (35) its suspend count,
the same query x64dbg's own thread code uses. In a process entry the pid sits
at offset 0x50 and the thread array starts at 0x100; each thread entry is
0x50 bytes, with the owner pid at 40, the thread id at 48, context switches
at 64, state at 68 and wait reason at 72. State 5 is Waiting, and wait reason
5 is Suspended.

Measured on a throwaway child with three threads sleeping 2 ms in a loop,
before the tools used it:

- running: about 700 context switches in 0.5 s, no thread in
  Waiting/Suspended, every suspend count 0;
- one thread `SuspendThread`-ed: that thread in Waiting/Suspended with no
  context switch and suspend count 1, the others going on;
- held at a pending debug event (`DebugActiveProcess`, its first event not
  continued): no context switch at all, and every original thread in
  Waiting/Suspended with suspend count 2; the debugger's break-in thread was
  in an Executive wait with count 0;
- after `DebugActiveProcessStop`, with that event never continued: every
  thread running again, with suspend count 0. So leaving threads suspended
  after a detach was not observed on a child detached by
  `DebugActiveProcessStop` with the event never continued; x64dbg's
  TitanEngine detach path was not measured. Live 2's suspended threads came
  from the synchronized step's explicit `SuspendThread` calls.

A debugger's context reads at a hold, and why `touched` exists:

- **Measured on a throwaway child with no debugger** (2026-10-11, 26
  threads): every thread `SuspendThread`-ed reads `frozen`, progress 0. One
  `GetThreadContext` per thread between the first and second sample raised
  every thread's own switches by exactly 1 (progress 26), two reads by 2,
  with every sample still Waiting/Suspended at suspend count 1. Held at a
  pending debug event: +1 per read, count 2. So a context read schedules a
  held thread once, with its suspend count and its wait unchanged; that
  Windows runs the read on the target thread itself is our explanation, not
  measured.
- **Who reads, a static reading** of x64dbg 9c8ca1c: a background thread
  wakes x64dbg's memory map refresh every 2 s while a process is debugged,
  paused or not; the refresh then sleeps at least 1000 ms, and wake-ups
  during that sleep collapse into one run after it. Every pause also reads
  the active thread's context and wakes the refresh. The refresh reads each
  thread's instruction pointer, one context read per thread. The plugin's
  breakpoint callback only logs.
- **Measured on headless x64dbg** (the owner's install with its plugin,
  started as the keeper starts it, against a 70-thread throwaway, two runs):
  during a hold every thread took one context read per pass, the passes at
  least 1.004 s apart, the first 0.0 to 1.0 s after `[STATE] paused`. The
  breaking thread took x64dbg's at-pause reads within 6 ms of the
  `[STATE] paused` line. About 3 of 1,900 samples taken during holds caught
  one held thread outside its wait mid-read. Replaying the keeper's
  three-sample check at every start offset read the hold `frozen` about as
  often as `running`: a coin flip on timing. Counting the touched threads
  as held, it read held at 728 of 732, 431 of 432, 532 of 533 and 329 of 333
  offsets.
- **The negative controls, same runs**: before attach, attached and
  running, logging at about 100 hits a second, and after detach, every
  window read `running` and the allowance never held. While logging, threads
  read suspended at all three sample instants in thousands of
  thread-windows, and every one of them switched 499 or more times, so a
  bound of `CONTEXT_READS` (2) separates a read from a run.
- **The sample retake.** A sample that catches a thread outside a wait
  (state not Waiting) while its suspend count is 1 or more caught a held
  thread mid-read, so `check` takes it again `RETAKE_DELAY` (0.01 s) later,
  at most `RETAKES` (5) times, and the last one stands. It moves sample
  instants, never what counts as held.
- **Not established on the game.** Live 3 rerun 4 read the control hold
  `running` with progress 69 on 69 threads (every thread +1) and nothing
  listed: consistent with one memory-map refresh in the window, not
  profiled on the game. Rerun 2 read `frozen` at the same step.

The controls run in every session: before attach the game reads `running`
(`before_attach`); at the control hold, the first logpoint's first hit, it
reads `frozen` with `suspended` and `stopped` each naming every thread the
check before attach saw (less the baseline's, any thread new since left
out, and the one breaking thread in an Executive wait exempt from
`stopped`, recorded as `breaking_tid`) and `unreadable_counts` empty
(`control_hold`), and that reading may carry `touched`, naming the threads
x64dbg's memory-map refresh read during the hold; and after that hold is
released it reads `running` again (`after_resume`). All three sit in
`instrument` in `status`. Only that sequence makes a later `running` mean
anything: a `frozen` with empty lists could come from a check that read no
thread at all. Between attach and the first logpoint the session is
`running` with `proven: false`, because there is no attach break to take a
frozen reading at. Replan 3's probe measured the three readings on a
throwaway process; on the game they are first taken live. The live
procedure runs the CLI itself too, after attach, after each `logpoint` and
after `detach`.

## Which agents reach it

**`live-operator` alone** carries the `mcp__x64dbg__*` tools, all eight, on its
`tools:` line. No phase agent, reviewer, verifier or scribe carries any. Its
prompt says when to use them: only when a workorder's `### Live procedure`
names debugger steps, after the game's own positive control, under the lease
it already holds; a debugger positive control first, and `INSTRUMENT-BLIND` if
that logs nothing; breakpoints only through `logpoint`; `detach` before
`hs_stop_game`; never `StopDebug`, never killing headless, no software
breakpoints and no memory writes.

- **The CLI route, for an operator without the tools loaded.** When a
  session has not loaded the `mcp__x64dbg__*` tools (the first live session's
  driver had most likely started before the server entered `.mcp.json`;
  inferred, not measured), `live-operator` runs the same eight as
  `py -3 -m tools.x64dbg_mcp tool <name> '<json>'` (§ "The eight tools"),
  never by importing the module through `py -3 -c`. The CLI adds no
  capability: any agent with a shell could already run `attach` or import the
  module, and the boundary stays the eight tools and their gates. Other
  agents go through neither route. Like the plugin's own port below, that is
  a prompt rule, not something the tooling enforces.
- **Codex gets no allowlist** (`.claude/README.md` § "Codex"): a Codex session
  sees all eight tools. The eight are the whole surface the proxy serves, so
  the plugin's stopping, writing, dumping and stepping tools are out of reach
  under either agent.
- **The tools do not seal the plugin off.** While a session is live, the
  plugin's port answers any local HTTP client on `127.0.0.1:50300`, with its
  whole surface. Go through the eight tools, never around them, as the ghidra
  agents never go around their server to its REST port.

## What stays local

- **Disassembly is game code.** What `disasm` returns, and what x64dbg prints
  into the session log about the game's code, is disassembled game output. It
  stays in the gitignored live capture and is paraphrased in any tracked file
  (AGENTS.md § "Legal"). This doc deliberately carries no example listing.
- **The install, the clone, the build and the session log** live under
  `%USERPROFILE%\tools\` (or the overrides), outside every repository.
- **Addresses** stay research findings (§ "Addresses: research use only").

## Deliberately deferred

- Teaching `planner.md` (and the `/workorder` skill) to write debugger steps
  into a `### Live procedure`. This doc and `live-operator`'s prompt describe
  how such steps run; the planner waits for the first real use.
- Changing x64dbg's settings: its TLS-callback breakpoints (`[Events]
  TlsCallbacks`) stay on, and the keeper resumes those pauses instead.
- No live session has run on the first-hit route yet. Until one has, the
  first-hit hold and its control hold on the game, the held change, the
  watchdog on the game and the verified release are tested only against the
  fakes, a throwaway child process and Replan 3's throwaway probe.
- Upstream pull requests for the two plugin edits.

## Tests

`py -3 -m unittest tests.test_x64dbg_mcp -v` pins the launcher on fixtures,
each acceptance with a negative control beside it: the git-tree refusal, the
loopback bind and loopback-only client, the two edits (applied, already
applied, CRLF and LF, refused), the build command line and install, the lease
and attach refusals, the keeper's attach with no attach break
(`attach_no_break`: ready with the instrument unproven, and no `run` sent
before the first logpoint), the stale breakpoint cleared at attach, its
`attach-unconfirmed` state and late promotion, the watchdog (a late break,
the TLS storm, `break_storm`), the first-hit hold and the instrument's
control hold (`instrument_control`, with a cold address that holds nothing
and proves nothing beside it), held changes, a breakpoint that keeps
breaking after its first hit (`paused_first_run`), the verified release
(`game-not-released`) and teardown order, `logpoint`'s
read-back (a row listed but disabled fails) and its failure stages, the
`expect_bytes` refusal, the `command` allowlist and its stdin and hold
routes, the CLI `tool` route (the reply as JSON, exit by `ok`, exit 2 for a
name outside the eight or arguments it cannot take, by name or by type), and
the `.mcp.json` and Codex wiring. A `never_pauses` test checks that no tool
path sends `pause` on stdin or calls the plugin's `PauseDebug`, `run` or
`ExecuteDbgCommand`.

The stand-in plugin prints the module table as the pinned plugin does,
decimal behind `0x`; for nine rounds it printed padded hex, which is how a
wrong live resolve passed every test. A regression test feeds live 1's
`hero_siege.exe` row verbatim and resolves `Hero_Siege.exe+427460` to
`0x7FF613D47460` through the stand-in, and its negative control serves the
hex table and expects `module_row_unreadable`, not a base, with an unpadded,
all-digit hex row (refused by the 64 KiB rule) and `modules`' `unreadable`
list beside it. The stand-in still answers `ExecuteDbgCommand` as the pinned
plugin does, with its echo of the call ahead of what x64dbg printed, and a
regression test feeds live 1's `SetHardwareBreakpointLog` reply verbatim to
`silent_reply_ok`, beside negative controls; no tool calls it any more. Its
`PauseDebug` answers Live 2's "settling" text and makes the fake headless
break a few seconds later, the asynchronous pause, which the `never_pauses`
control shows only the watchdog resumes.

The fake headless, `tests/x64dbg_fake_headless.py`, prints what x64dbg
prints, as measured live, by Replan 3's probe, or as read: on `attach`,
`[STATE] initialized`, `[STATE] running` twice and `Attached to process!`,
and never `[STATE] paused`; the `log` markers, `bph`'s success line, nothing
for a `Set*` that succeeds, `bplist` rows, `Detached!`, hit lines for each
breakpoint a test marks hot, and a break on a hot breakpoint's hit while its
condition is not 0, so a breaking `bph`'s first hit holds it as the real one
does. Its modes stand in for each pause and failure: `tls_breaks` (the TLS
storm after attach), `late_break` (a pause landing late, as in Live 2),
`breaks` (a storm from now on), `break_after` (one break after a given
verb), `stale_db` (a breakpoint restored from the database on attach),
`condition_ignored`, `never_running`, `race` (a debug-register change that
is not held silences a hot logpoint, the lost DR7 update, so the
held-change test's control can fail), `leak_on_detach` (every game thread
but one stays suspended after `detach`), `fail_condition`, `listed_as`,
`false_success` and `exception_hold` (a breaking `bph` on a hot address hits
at once, reported in Live 3 rerun 3's exception shape: the
`GUI_SET_LAST_EXCEPTION` notice, the pause, the first-chance single-step line,
then `set!`). The `stale_server` tests patch `CODE_ID`: a `Tools` whose file
no longer hashes to it refuses every tool but `status`, and the keeper
refuses a hold or send stamped with another `code_id` and still detaches;
`breaking_bph_in_lines` sends the older client's shape, and `exception_hold`
pins the exception-shaped first hit, the settle before the `bph` and the
session log's reading of the `[TODO]` notice.

The outside check has a probe seam, `probe_cmd` in the session config: the
logic tests point it at a fake probe whose verdict follows a file the fake
headless writes (`frozen` at a break, the first-hit hold among them, with
its stand-in threads listed as suspended and stopped, `running` after a
`run`, `threads-suspended` after a leaking detach). Two modes are the
instrument's negative controls: `blind_probe` never reads `frozen`, and
`empty_lists` reads `frozen` at a break with no thread listed. Each must
leave `proven: false` after the control logpoint, with a `note` naming the
gap that `status` reports, and a detach with `game_released: null`,
`ok: false` and CLI exit 1. The `instrument_gaps` tests check each other
shortfall on hand-built checks: a thread left out of either list, an unread
suspend count, no `tids`. The `breaking_thread` tests replay the probe's
run2 readings at the first-hit hold (seven threads, tid 6320 in an Executive
wait): the replay is proven with `breaking_tid` 6320 named in the note, and
each negative control is not: 6320 at suspend count 0, a second expected
thread in an Executive wait, 6320 switching between samples, a missing
thread not in `executive_waits`, and a check with no `executive_waits`
field. The stand-in's `breaking_thread` N mode runs the same through the
keeper: with 1 the session is proven and records the breaking thread, with
2 it is not. `tests.test_thread_state`'s `executive` tests read the same
run2 samples through `classify`. The `real_os` tests use the real reader instead,
against a stand-in game the test starts (three threads sleeping 2 ms in a
loop) whose threads the fake headless really suspends at every break,
the first-hit hold included, and under `leak_on_detach`: the control hold
end to end (`proven: true`, with every stand-in thread in `suspended` and
`stopped` at the first-hit hold and `unreadable_counts` empty), a leaking
detach (`game-not-released`, CLI exit 1) and a clean one
(`game_released: true`, CLI exit 0). The stand-in's `context_reads` S mode,
with `real_os`, reads the context of each thread it suspended every S
seconds from the break while paused, as x64dbg's memory-map refresh does:
the `context_read` tests run the control hold with S 0.6 (one or two reads
in the check's window: `frozen`, `control_hold.touched` covering the
stand-in game's threads, progress above 0, proven) and, as the negative
control, with S 0.15 (four or more reads: not `frozen`, nothing touched,
not proven). The `control_settle` test reads the time of the break and of
each probe-seam call, which the stand-in leaves in its work directory, and
checks that the hold-time check came at least `HOLD_SETTLE` after the
break. The `real_os` tests run on Windows with a 64-bit Python only and
skip elsewhere, naming the reason.

A guard fails any URL fetch that is not `127.0.0.1` and any subprocess the
test did not expect, and a test proves the guard trips: no network, no
download, no clone, no MSBuild, no real x64dbg, game or lease. The stdio round
trip needs the `mcp` package and skips without it, naming the reason. Those,
and the `real_os` tests above off Windows or on a 32-bit Python (in both
test modules), are the only skips: the platform-specific test of how the
keeper is detached checks the Windows creation flags on Windows and
`start_new_session` elsewhere.

`py -3 -m unittest tests.test_thread_state -v` pins the outside check: the
`parse_layout` tests build a synthetic buffer at the measured offsets and
check that it parses to the right threads and skips another pid's entry; the
`classify_*` tests run the verdict rules over synthetic samples, with two
negative controls (`classify_transient`: one sample with a suspended thread,
or with every thread suspended while progress continues, reads `running`;
`classify_baseline`: a thread already suspended at the baseline is not
reported); `classify_unreadable_count` reads a switching thread whose count
could not be read as `unreadable`, listed in `unreadable_counts`, with the
readable samples as its `running` control; the `gone` and `cli` tests check
a missing pid, the JSON and the exit codes. The `touched` tests replay Live
3 rerun 4's shape (69 held threads, each +1, one in an Executive wait:
`frozen`, progress 69, all 69 touched, 68 stopped), +2 each (`frozen`), and
the negative controls: +3 each, the logging shape (suspended at every
sample but +500), idle threads switching at count 0, and a thread at count
0 or unread in one sample all read anything but `frozen` with that thread
not touched. The `retake` tests patch the sampler: a held thread caught
outside its wait is sampled again and lands in `stopped`, a running thread
at count 0 is not retaken, the retakes stop at `RETAKES`, and a pid gone
during a retake reads `gone`. Its `real_os` tests, Windows
only, start a throwaway child and read it `running`, then
`threads-suspended` with one thread suspended (that thread named, count 1),
`running` after the resume, `frozen` held at a pending debug event with
every worker in `suspended` and `stopped` and no count unread, and
`running` with nothing suspended after `DebugActiveProcessStop`; and, with
every thread suspended, one context read per thread between two samples
reads `frozen` with progress equal to the threads read, a reader every
0.6 s during `check` reads `frozen` with threads touched, and the resumed
child reads `running` with nothing touched.

`py -3 -m unittest tests.test_x64dbg_agent_tools -v` pins `live-operator`'s
`tools:` line to exactly `mcp__x64dbg__` plus each name in
`LIVE_OPERATOR_TOOLS`, fails any `mcp__x64dbg__*` tool on any other agent, and
fails any name in the set that is one of the plugin's stopping, writing,
dumping, stepping or software-breakpoint tools.
