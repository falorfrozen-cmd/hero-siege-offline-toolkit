# `ghidra` MCP server: Hero Siege's Ghidra project over MCP

The `ghidra` entry in [`.mcp.json`](../../.mcp.json) gives an agent the local
Ghidra project as tools: decompile a function, search functions and strings,
list callers, callees and xrefs, read bytes, disassemble. Before it existed,
each such question cost a headless `analyzeHeadless` run of
`ForgePact/tools/ghidra/DecompileTo.java`. Now it is one tool call. On
2026-10-06, `search_functions` found `SaveStash`'s eight symbols in 0.9 s, and a
cold decompile of it took 23 s.

It serves [bethington/ghidra-mcp](https://github.com/bethington/ghidra-mcp)
v6.0.0 (Apache-2.0), pinned by version and by the release's sha256 digests in
[`tools/ghidra_mcp.py`](../../tools/ghidra_mcp.py), on Ghidra 12.1.4 with
JDK 21. The release is built against 12.1.3. It was verified on 12.1.4 at the
time it was added.

## How it runs

There are two processes:

| Part | What it is | Lifetime |
|---|---|---|
| headless server | `GhidraMCPHeadlessServer` from the release jar, on Ghidra's own jars; opens the project and answers REST on `127.0.0.1:8089` | **shared**: the first session that needs it starts it detached, and it keeps running after that session ends |
| bridge | the release's `bridge-mcp-ghidra`, the stdio MCP server the agent talks to | one per agent session |

`py -3 -m tools.ghidra_mcp` (what `.mcp.json` runs) checks `/health`. If no
GhidraMCP 6.0.0 server answers, it starts one and waits for it, which takes
about 9 s cold. It then loads `/Hero_Siege.exe` if no program is loaded, and
hands stdio to the bridge.

The server is shared because a Ghidra project takes one lock. A server per
session would let the first session in `.claude/worktrees/` lock out every
other one. Sessions that start together (Claude Code and Codex, two worktrees) take
`server.lock` in turn: the first launches, and the rest re-check `/health`
once they hold the lock and find the server already up. A launch that is
not healthy by its deadline is killed, so it never holds the project behind a
failed start. The launcher adopts a running server only if it reports
`6.0.0-headless` and the process holding the port runs that server on this
project copy. Anything else is refused rather than used, and no second server
is started beside it. That includes the GUI plugin, another version, and a
headless server on the original research project or on another checkout's
copy (PR #449 review).

## The project it opens is a copy

The server opens `%USERPROFILE%\ghidra_projects\mcp\HeroSiege.gpr`, a copy of
the research project `%USERPROFILE%\ghidra_projects\HeroSiege.gpr`. It never
opens the research project itself, for two reasons:

- the project lock would make `DecompileTo.java` runs and the GUI fail while a
  server is up;
- the tool surface includes writes (renames, comments, types), and those land
  in the copy only.

When `ImportSymbols.java` re-names the source project after a new
`citrace symdump`, refresh the copy:

```bash
py -3 -m tools.ghidra_mcp stop
py -3 -m tools.ghidra_mcp setup --refresh-project
```

## Why this server and not pyghidra-mcp

[pyghidra-mcp](https://pypi.org/project/pyghidra-mcp/) 0.2.7 was tried first.
It is a single process and simpler to wire, but it refuses every call
(`"Analysis incomplete for binary 'Hero_Siege.exe'"`) on a program Ghidra does
not mark as auto-analyzed. Our project is imported with `-noanalysis` on
purpose: it has 307,150 functions, and a full pass takes hours (see
`ImportSymbols.java`'s header). It would also decompile every function into a
vector index the first time a session opened the project. GhidraMCP decompiles
on demand, as `DecompileTo.java` does, and needs no analysis pass.

## Setup on a new machine

Downloads need the owner's go-ahead. With Ghidra and a JDK 21 installed and
the research project in place (AGENTS.md § "Check for a Named Ghidra Project
Before Researching a Game Mechanism", which puts this server ahead of the
headless route):

```bash
py -3 -m tools.ghidra_mcp setup    # fetch + sha256-check the release, make the bridge venv, copy the project
py -3 -m tools.ghidra_mcp status   # resolved paths, what is missing, server health
```

Everything goes outside any git checkout, and the tool refuses otherwise:

| What | Default | Override |
|---|---|---|
| Ghidra install | newest `%USERPROFILE%\tools\ghidra_*_PUBLIC` | `GHIDRA_INSTALL_DIR` |
| jar, bridge venv, `server.log`, `server.lock` | `%USERPROFILE%\tools\ghidra-mcp-6.0.0` | `HS_GHIDRA_MCP_HOME` |
| research project (copied from) | `%USERPROFILE%\ghidra_projects\HeroSiege.gpr` | `HS_GHIDRA_SOURCE_PROJECT` |
| project copy (served) | `%USERPROFILE%\ghidra_projects\mcp\HeroSiege.gpr` | `HS_GHIDRA_MCP_PROJECT` |
| program | `/Hero_Siege.exe` | `HS_GHIDRA_MCP_PROGRAM` |
| port | `8089` | `HS_GHIDRA_MCP_PORT` |

`start` and `stop` manage the server by hand. `stop` finds the process
listening on the port and kills it only if it runs GhidraMCP's server class on
this project copy. Otherwise it reports what holds the port and kills nothing.
There is no pid file. The PR #449 review showed one goes stale after a crash or
reboot, or is never written when a launcher dies mid-start.

## What it refuses, and what stays local

- **Loopback only.** The server is started with `--bind 127.0.0.1`, and an
  inherited `GHIDRA_MCP_BIND_ADDRESS` is removed.
- **No script execution.** `GHIDRA_MCP_ALLOW_SCRIPTS` is removed from the
  server's environment, so `run_script_inline` and `run_ghidra_script` stay
  off.
- **File endpoints are confined** to the project copy's directory
  (`GHIDRA_MCP_FILE_ROOT`).
- **Decompiled output stays local.** A decompile reaching the agent is a
  local research step. It reaching a tracked file, a commit message, an issue
  or a PR is not (AGENTS.md § "Legal"). Paraphrase what the body does.
  `decompile-output-guard` and `.claude/hooks/decompiled_output.py` still check every
  change.
- **The decompile index does not see MCP decompiles.** `tools/decomp_index.py`
  indexes files a headless run wrote. A tool call writes no file, so there is
  nothing to `scan`, and re-asking the server is cheap. Keep using the index
  for headless output and for its `slot-name` / `find-name` naming of unnamed
  globals.

## Which agents reach it, and with what

The `/workorder` phase agents that research or decide (`planner` and its
effort variants, `implementer`, `implementer-medium`, `consultant`,
`consultant-max`) list the server's read tools, the set `AGENT_READ_TOOLS`
names, in their `tools:` lines, as `mcp__ghidra__<tool>`: search, list, decompile, xrefs, callers, callees, call
graph, function info and status. The verifier, the scribe, `live-operator`
and the reviewers get none.

- **The read set's source is `AGENT_READ_TOOLS` in
  [`tools/ghidra_mcp.py`](../../tools/ghidra_mcp.py).** The bridge names a
  tool after its REST path (`/server/status` becomes `server_status`).
- **What is left out, by rule:** every `POST` endpoint, read-looking ones
  included, because the server marks state-changing endpoints `POST`; every
  write and project or session change (`rename_*`, `set_*`, `create_*`,
  `delete_*`, `load_*`, `run_script*` and the rest); every `debugger_*` and
  `emulate_*` tool; `force_decompile`, which only matters after a rename;
  `list_functions` and `list_functions_enhanced`, which flood the context on
  307,150 functions (`list_methods` and `search_functions` page); and the
  tool-discovery helpers other than `check_tools`. Reads outside those
  categories, such as `read_memory`, are added to the set and the test together.
- **The test:** `py -3 -m unittest tests.test_ghidra_agent_tools` pins each
  of those agents' `mcp__ghidra__*` names to `AGENT_READ_TOOLS` and fails any
  write or debugger tool on any agent.
- **The list does not seal the server off.** Each of these agents has `Bash`,
  and the REST port answers `curl` on `127.0.0.1:8089`, so the prompts forbid
  that route as well. A write would land only in the project copy.
- **Codex gets no allowlist.** `tools/sync_agent_tooling.py` does not
  translate `tools:`, so a Codex agent sees every tool of every server, and
  the ban in the agent's prompt is the only restriction (`.claude/README.md`
  § "Codex").
- **Headless is the fallback**, for what these reads cannot do:
  `ImportSymbols.java` for a fresh import and symbol naming; `DecompileTo.java`
  (with `DecompileToLong.java` / `DecompileToHuge.java` for long timeouts)
  for bulk dumps that `tools/decomp_index.py scan` indexes; `FindCallers.java`,
  `FindWrites.java`, `FindPointers.java`, `FindRvaTable.java`,
  `ListCallsIn.java` and `DecompileAround.java` for byte-level scans; and
  `FindSlotNames.java` for the slot-name table. They run under
  `analyzeHeadless` against the research project, which this server never
  locks.

## Sharp edges

- **The bridge registers about 244 tools.** Claude Code defers MCP tools behind
  tool search, so they cost little context. Codex loads them all.
- **Codex's default MCP startup timeout is 10 s**, close to the server's cold
  start. If the `ghidra` server times out under Codex, run
  `py -3 -m tools.ghidra_mcp start` once first, and every later launch then
  finds the server warm.
- **Decompile by address.** `decompile_function` takes `address`, not a name.
  Get the address from `search_functions` (`name_pattern`) first.
- **An empty callers or xrefs answer is "not observed", not a negative.**
  `get_function_callers` and the xrefs tools read Ghidra's reference table,
  which a `-noanalysis` import is inferred to leave mostly empty. On 2026-10-07
  `search_functions` found `SaveStash`, `get_function_callers` answered "No
  callers found", and `get_function_xrefs` returned one `DATA` reference.
  That one probe is the whole basis for "mostly empty": it is inferred, not
  measured across the project. Whether `SaveStash` has direct callers was not
  checked in that run, but this build's compiled GML calls scripts by direct
  `call rel32`, which only a byte scan sees. `FindCallers.java` scans `.text`
  for `E8`/`E9` sites aimed at the target, and a zero from it does not close
  the question either: it sees only those direct sites, needs a
  positive control in the same project (a script it finds callers for), and
  is blind to calls through the script table, a global pointer or a method value.
- **The `debugger_*` and `emulate_*` tools** are part of the release's surface.
  They are not used or verified here. Attaching to a running game is
  `hs-drive`'s territory and subject to its lease.
- **Opening programs uses `load_program_from_project`**, not `open_program`,
  which is GUI-only. The launcher already loads the one program.

## Tests

`py -3 -m unittest tests.test_ghidra_mcp -v` pins the launcher's contract on
fixtures: the git-tree refusal, the loopback bind, the stripped environment,
the argfile classpath, the version check on the port, and the `.mcp.json` and
Codex wiring. It never starts Java or opens the real project.

`py -3 -m unittest tests.test_ghidra_agent_tools -v` pins which agents carry
which `mcp__ghidra__*` tools against `AGENT_READ_TOOLS`, and fails any write
or debugger tool on an agent (§ "Which agents reach it, and with what").
