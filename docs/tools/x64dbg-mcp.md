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
| `mcp__x64dbg__status` | session state (`none`, `attaching`, `attach-unconfirmed`, `running`, `detaching`, `ended`, `detach-unconfirmed`), the target pid, whether the keeper and headless are alive, whether the plugin answers on loopback, and the hs-drive lease state |
| `mcp__x64dbg__logpoint` | adds one non-breaking hardware logging breakpoint: an `address` (an x64dbg expression such as `Hero_Siege.exe+427460`), a `log` format string (`{` `}` allowed, `"` refused), an optional log condition, an optional name, and an optional `expect_bytes`: the function's first bytes as Ghidra's copy has them, in hex. It first reads the code at the address and returns its first bytes; with `expect_bytes` a mismatch is refused before anything is paused or set. Then it pauses the debuggee, sets the hardware breakpoint (`bph`), its log text and optional log condition, sets its break condition to `0` so it never breaks, reads `bplist` back from the session log, sends `run`, and after the settle time asks again whether the game is running. It reports ok only when the read-back lists the resolved address as an enabled hardware breakpoint, every `Set*` step printed nothing, and the game is still running. On any failure after the pause it clears that breakpoint and still sends `run`: it never leaves the game paused |
| `mcp__x64dbg__command` | one allowlisted x64dbg command, sent on headless's stdin (not through the plugin, § "Breakpoint rules"): delete, enable or disable a hardware breakpoint, name it, set its log condition, reset its hit count, or `bplist`. It returns the log lines that followed. Everything else is refused, naming the allowlist: in particular a new hardware breakpoint (use `logpoint`), every software or memory breakpoint, setting a breakpoint command, `StopDebug`, `detach`, `exit`, memory writes, and any command with a `;` outside a double-quoted string. Reading a hit count is not on the list: x64dbg's `GetHardwareBreakpointHitCount` sets `$result` and, as far as is known, prints nothing, so it would answer ok with no number |
| `mcp__x64dbg__bplist` | sends `bplist` and returns the log lines it produced |
| `mcp__x64dbg__log` | the session log's lines after a given line number (by default the last 200), with the total line count, so logging-breakpoint hits can be paged |
| `mcp__x64dbg__modules` | the loaded modules from the memory map; gives `Hero_Siege.exe`'s base |
| `mcp__x64dbg__disasm` | disassembly at an address, for checking that an address maps to the function Ghidra names (it stays local; § "What stays local") |
| `mcp__x64dbg__detach` | the teardown in § "Attach, the keeper, and teardown", through the keeper |

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
  whose three columns are decimal with no leading zero and whose end equals
  base plus size. A row in any other format (a later plugin build, a hex
  rendering) gives no base: `resolve`, and so `logpoint` and `disasm`, refuse
  with `module_row_unreadable`, quoting the row, rather than guess between
  hex and decimal and misresolve. A module with no row at all is
  `no_such_module`. The other plugin outputs the tool parses (the
  `ReadDismAtAddress` listing) are hex, as before.
- **Two guards keep a logpoint from pausing the game.** x64dbg prints nothing
  when a `Set*` step succeeds. At the pinned commit the plugin never hands back
  a blank reply: when x64dbg printed nothing it answers `Result: Command
  executed successfully (no output captured)`, and `Result: Command execution
  failed (no output captured)` when the command could not be queued to
  x64dbg's command thread (a command x64dbg ran and rejected arrives as
  `Result: <its text>` instead). So the first is a `Set*` step's success, and
  any other output fails the logpoint, and its breakpoint is cleared. That
  output can be a rejected never-break condition, and the second form fails
  every command. Then the game's own answers are checked. The plugin's `run`
  reports RUNNING only when x64dbg still says the game runs about 250 ms after
  the run command, so the first `run` after arming that reports anything else
  (PAUSED) is direct evidence that the breakpoint broke on a hit: `logpoint`
  clears it, resumes the game and fails with stage `running`, quoting that
  answer. After a first `run` that reported RUNNING, it waits the settle time
  and sends `run` again, with the same result on a pause. The plugin offers no
  way to ask whether the game is running without resuming it, so each check
  sees only a breakpoint hit within about 250 ms after either plugin `run`
  (the plugin's own re-check delay). For a rarely called function, a pause
  that comes later shows as the game freezing: `detach` ends it.
- **Keep the control armed while a candidate's zero is read.** Clear
  candidates to free a debug register, never the control: a zero with no
  control logging in the same window measured nothing.
- **Counting hits.** Count from the log, not from x64dbg's hit counter, which
  `command` cannot read. Put a counter field in the `log` string, such as
  `hit #{d:$breakpointcounter} rcx={rcx}`, or count the lines in `log`. The
  `$breakpointcounter` field comes from x64dbg's documentation and is **not
  yet measured live**.
- **Hit counts across a plugin call are not established.** The plugin
  captures a command's output by redirecting x64dbg's whole log to a temp file
  for the length of the call. `headless.exe` implements that redirect, and
  whether it still writes the log to the session log meanwhile or diverts it
  is not established. If it diverts, hits inside those windows never reach
  the session log and `log` undercounts "how often". `command` and `bplist` go
  on headless's stdin, so no redirect is involved. Every `logpoint` still
  pauses and resumes through the plugin, and the game runs inside two of its
  windows: the moment before its pause takes effect, and about a quarter
  second after each `run`. **First-session check:** give the control a counter
  field (`#{d:$breakpointcounter}`, above), let it log steadily (about 85
  hits/s in town for `CheckTalentUse`), then add one more `logpoint`. In `log`,
  the control's counter should run on with no jump across that call. A jump
  means the skipped hits went to the redirect file. Look as well for a
  `[headless] failed to redirect log` line. Record what you saw. Until that
  check has run, a count that spans a `logpoint` call is a lower bound.
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
running is a refusal); x64dbg and the plugin are installed; and no session is
already live. It then starts the detached keeper and returns once the keeper
reports `running`, `attach-unconfirmed` (exit 1, below), or failed.

- **x64dbg pauses the process on attach** until it is told to `run`. In the
  probe that was a 10.65 s freeze. In the first live session (2026-10-10,
  `tooling-484-x64dbg-mcp` live 1) `attach` took 8.53 s wall clock, and
  ForgePact's incident monitor recorded one freeze episode across it, with a
  worst frame of 4201 ms. A `run` sent before the attach completes
  fails and leaves the game paused once it does. So the keeper sends the
  attach on headless's stdin, waits until the plugin answers a debug-only call
  without "No active debugging session", then sends `run`, and records
  whether readiness was observed.
- **An attach the keeper never saw complete is `attach-unconfirmed`**, not
  `running`. If the plugin has not answered within the ready timeout (60 s),
  the keeper sends `run` on stdin, which resumes the game if the attach did
  complete. A later attach would still pause the game, so the keeper goes on
  asking, and once the plugin answers it resumes the game and only then calls
  the session `running`. Until then every tool but `detach` refuses the
  session, `attach` exits 1 and says the game may be paused, and the thing to
  do is `detach`.
- **An attach whose resume was never confirmed is `attach-unconfirmed` too.**
  The keeper resumes the game with the plugin's `run` until it reports RUNNING
  twice, a settle apart. If no `run` ever does, the attach completed but the
  game was never seen running, so it may be paused: the keeper sends `run` on
  stdin as a last try and records `attach-unconfirmed` with `ready: false`,
  never `running`. It then keeps retrying the resume, each retry kept short
  (10 s) so a `detach` request is still served within the detach tool's wait,
  and calls the session `running` only once a resume is confirmed.
- **The keeper is the only holder of headless's stdin** for the session's
  whole life. What headless does on stdin EOF, and whether it ends the
  debuggee by exiting while attached, is not established. So the keeper is
  detached (its own process group, no console), an operator's shell ending
  cannot close the pipe, no Ctrl event reaches headless, and **nothing ever
  kills headless while it is attached**. Headless's output goes to the session
  log, and the state to a JSON file beside it.
- **Teardown** (the `detach` tool or the CLI): clear the hardware breakpoints,
  `detach`, confirm that a debug-only call reports no session, then `exit`.
  Only after a confirmed detach may the keeper end a headless that has not
  exited. An unconfirmed detach leaves headless alone, sets the state to
  `detach-unconfirmed`, and fails loudly: the game stays running and the lease
  stays held, and whoever is running the session says so.
- **Order in a live session: `detach` before `hs_stop_game`.** Stopping the
  game under an attached debugger is the case nobody has measured.

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
- Turning off x64dbg's attach breakpoint through its ini file: the key is not
  established, so the keeper's wait-then-`run` stays the answer.
- The first real `setup` and the first live debugger session, both of which
  need the owner's go-ahead. Until then the build command line, the readiness
  check after attach, the `bplist` read-back format and headless's exit
  behaviour are tested only against fakes.
- Upstream pull requests for the two plugin edits.

## Tests

`py -3 -m unittest tests.test_x64dbg_mcp -v` pins the launcher on fixtures,
each acceptance with a negative control beside it: the git-tree refusal, the
loopback bind and loopback-only client, the two edits (applied, already
applied, CRLF and LF, refused), the build command line and install, the lease
and attach refusals, the keeper's attach-then-`run`, its `attach-unconfirmed`
state and late resume, and teardown order, `logpoint`'s read-back (a row
listed but disabled fails), its `Set*` output check, its re-check that the
game kept running, its `expect_bytes` refusal and always-`run` failure path,
the `command` allowlist and its stdin route, the CLI `tool` route (the reply
as JSON, exit by `ok`, exit 2 for a name outside the eight or arguments it
cannot take), and the `.mcp.json` and Codex wiring.

The stand-in plugin prints the module table as the pinned plugin does,
decimal behind `0x`; for nine rounds it printed padded hex, which is how a
wrong live resolve passed every test. A regression test feeds live 1's
`hero_siege.exe` row verbatim and resolves `Hero_Siege.exe+427460` to
`0x7FF613D47460` through the stand-in, and its negative control serves the
hex table and expects `module_row_unreadable`, not a base. Two stand-in modes
cover the game's answers: `paused_runs` answers PAUSED to chosen plugin `run`
calls after arming (the first, for `logpoint`'s first-run check; the second,
for its re-check), and `never_running` never reports RUNNING, for the
keeper's unconfirmed resume. A guard fails any URL fetch that is not
`127.0.0.1` and any subprocess the test did not expect, and a test proves the
guard trips: no network, no download, no clone, no MSBuild, no real x64dbg,
game or lease. The stdio round trip needs the `mcp` package and skips without
it, naming the reason. Nothing else skips: the one platform-specific test, how
the keeper is detached, checks the Windows creation flags on Windows and
`start_new_session` elsewhere.

`py -3 -m unittest tests.test_x64dbg_agent_tools -v` pins `live-operator`'s
`tools:` line to exactly `mcp__x64dbg__` plus each name in
`LIVE_OPERATOR_TOOLS`, fails any `mcp__x64dbg__*` tool on any other agent, and
fails any name in the set that is one of the plugin's stopping, writing,
dumping, stepping or software-breakpoint tools.
