# `.claude/` — the automated half of `AGENTS.md`

`AGENTS.md` holds this repository's rules in prose. This directory holds the
subset that a machine can enforce or execute, so they stop depending on whether
an agent happened to read the right section of a long file first.

Everything here is committed on purpose. Only `settings.local.json`
(per-machine overrides) is gitignored.

## Hooks — `settings.json` + `hooks/`

The four `PostToolUse` hooks below exit 0 silently when nothing is wrong, and
exit 2 with an explanation when something is. `leftover_processes.py` is
different in shape — it runs on `PreToolUse` and `PostToolUse` to keep a
ledger, and its blocking behavior lives at `Stop` — but the exit-0-quiet,
exit-2-explains contract is the same one. They all run through `py -3`; on a
non-Windows machine change that to `python3` in `settings.json`.

| Hook | Fires when | Catches |
|---|---|---|
| `catalog_signature.py` | `catalog/` differs from HEAD | `catalog/catalog.json` no longer verifying against its minisign signature, with CRLF called out by name when that is the cause |
| `tauri_command_guard.py` | a `.rs` under `hub/src-tauri/src/` differs from HEAD | `block_on` inside a `#[tauri::command]`, and `#[tauri::command(async)]` on an `async fn` |
| `hub_frontend_tests.py` | a top-level `hub/src/*.js` differs from HEAD | the hub's frontend tests failing |
| `decompiled_output.py` | any changed text file, in the hub **or in a dirty submodule** | Ghidra/IDA symbols, GameMaker VM pseudo-variables, GML positional arguments and bytecode mnemonics reaching a tracked file |
| `leftover_processes.py` | `PreToolUse`/`PostToolUse` on `Bash`/`PowerShell`/`Monitor`, and `Stop` | processes this session's tool calls started that are still alive when a reply ends |

**The first four key off the working tree, not the tool payload**, and that is the
single most important thing to preserve when editing them. A payload-shaped
hook only sees `Edit` and `Write`, and only when it can resolve
`tool_input.file_path` against the repository root. Both halves leak: a `sed -i`
or heredoc under `Bash` never produces a `file_path`, and a path the hook cannot
resolve returns "not my file" — which is indistinguishable from "nothing
wrong". That is not theoretical. During development all three exited 0 against
a harness feeding them POSIX-style paths Windows Python could not resolve, and
looked installed and healthy while guarding nothing. `git status --porcelain`
costs ~40 ms and has neither hole. `.claude/hooks/_common.py` holds the shared
parts.

**Escape hatch: `HSTK_SKIP_HOOKS=1`.** Every blocking message names it. There
are legitimate states these would otherwise wedge — most clearly a catalog
rebuilt *unsigned* on a machine without `$HUB_MINISIGN_SECRET_KEY`, which
`skills/catalog-rebuild/SKILL.md` explicitly contemplates. Because the trigger
is the working tree, that state would otherwise fail *every* later tool call,
including the ones needed to finish or undo the work. A blocking hook with no
way out is worse than no hook.

Why these four and not others: each one guards a failure that has already
shipped, and each is cheap. The catalog check is a signature verification; the
command guard is a parse; the frontend tests are, in `hub/scripts/test.mjs`'s
own words, "a second of Node against a twelve-minute Windows build". **Nothing
here ever invokes `cargo`** — that is the twelve-minute path and it belongs in
`npm run check`, not in a hook that fires on every edit.

`decompiled_output.py` is the exception to "already shipped", and deliberately
so: the failure it guards is not a bug a later release fixes.
`ForgePact/CREDITS.md` claims AGPL-3.0 original work, and that claim holds only
while no game source text has reached any remote here — every submodule's own
origin included. `.gitignore` already excludes decompiler *artifact paths*
(`*.i64`, `*.gpr`, `ghidra_projects/`); this covers the likelier accident, a
listing pasted into a tracked `.md` or `.cpp` while writing up a finding. It is
the only hook that scans inside submodules, because the hub's `git status`
reports a dirty submodule as one changed pointer and `ForgePact/docs/` is where
research notes land.

It deliberately does **not** match `gml_Script_*` names or asset indices.
`AGENTS.md` names those as interoperability facts that are fine to commit — they
are what `hs-game-sdk` is for — so matching them would flag the SDK's own tables
and teach everyone to set `HSTK_SKIP_HOOKS`.

The catalog hook keys off the working tree rather than off which tool ran,
because a catalog can be rewritten by `Edit`, by a build script under `Bash`, or
by a rebuild this session never saw the path of.

### `leftover_processes.py` — a per-call ledger, not a descendant walk

Unlike the other four, this hook keys off the **live process table**, not the
working tree, because what it is guarding against — a `cargo` build or a
detached `npm` script still running after the reply ends — never touches a
file. It runs three times per tool call and once per reply: `pre` snapshots
every live process before a `Bash`/`PowerShell`/`Monitor` call, `post`
snapshots again afterward and admits whatever that call can be blamed for into
a per-session ledger file, and `Stop` reports whichever ledger entries are
still alive and have not been reported before. A process is identified by
`(pid, creation time)`, never PID alone, because Windows reuses PIDs quickly.

Three simpler designs were rejected, and are worth recording so nobody
re-proposes them:

- **Walking every live descendant of the session's `claude.exe` at `Stop`.**
  This session's own MCP servers are exactly such descendants, and without
  command lines the only way to tell them apart from something like a
  `tauri-mcp driver-session` (which should be reported) is name matching on
  "mcp" — which the driver-session's own name defeats. It also cannot see a
  `Start-Process`-style detached child whose launcher has already exited,
  since no descendant walk from a living ancestor reaches it.
- **Attributing every orphan (dead parent) created since the session
  started.** Multiple sessions run at once on this machine, and timing alone
  cannot tell one session's orphan from another's — reporting a process a
  different session started is exactly what this hook must never do.
- **Reading another process's environment for a session marker.** That means
  `ReadProcessMemory` against a PEB layout this hook does not own, for a
  reporting tool that does not need it.

`stop_hook_active` is the loop guard: a hook that blocks Stop again while
`stop_hook_active` is true never lets the reply end. Every leftover is
reported at most once per ledger, in a `reported.json` next to it, so a dev
server the user asked to keep running does not re-block every later reply —
`AGENTS.md`'s "verify with a command" covers a process Claude claimed to kill
but did not.

Two environment variables, both documented in the hook's own docstring:
`HSTK_PROC_LEDGER_DIR` (default `%TEMP%/hstk-leftover-processes`, deliberately
never inside the repository, since `decompiled_output.py` scans every
untracked file and a ledger under the worktree would dirty `git status` on
every tool call) and `HSTK_PROC_SESSION_ROOT_PID` (overrides the nearest
`claude.exe` ancestor lookup; exists for tests).

**It never kills anything.** No `TerminateProcess`, no `kill`, no `taskkill`
run by the hook itself — it only prints what it found and suggests the command
a human or the reply should run.

**Known limitation, not observed to have happened yet:** if a whole parent
chain back to a ledger entry dies between two observations — `cargo` exits
while the `hub.exe` it started survives, with neither `post` nor `stop` having
run in between — the survivor cannot be attributed and will not be reported.
`AGENTS.md`'s "check with a command" is the backstop for exactly this gap.

Three more identity safeguards, each added after a live report misattributed
something and each proven by its own paired test in
`TestLeftoverProcessesAdmissionRules`:

- A PPID this hook cannot `OpenProcess` (a SYSTEM service, a protected
  process) is still counted as alive by consulting the raw, unfiltered
  Toolhelp32 PID list, not only the openable snapshot — otherwise an
  unopenable-but-live parent (`svchost.exe` under `dllhost.exe`/`audiodg.exe`)
  is indistinguishable from a dead one and its child looks like an orphan.
- Rule (c)'s "parent already has a ledger entry" check requires a *live*
  occupant of that PID to match the ledger entry's creation time exactly, not
  merely postdate it — `entry.creation <= proc.creation` is true for any later
  process once the ledger entry is dead, reused PID or not.
- `stop`'s liveness check trusts `GetExitCodeProcess` (`STILL_ACTIVE`) over
  Toolhelp32 membership alone, since a just-terminated PID can still appear in
  a snapshot for a brief window after it exits. Treat this one as a
  hypothesis-level safeguard rather than a confirmed fix: the flaky test that
  motivated it has also passed 20/20 in local runs *without* this gate, so the
  gate has not itself been shown to be what closes the flake.

### Live checks

**Live positive control — run this by hand in a real session; it cannot be a
checkbox, because it needs a live session to end a reply:**

1. In a Bash tool call, run
   `powershell -NoProfile -Command "Start-Process py -ArgumentList '-3','-c','\"import time; time.sleep(600)\"'"`,
   which is detached and orphaned. The inner `\"...\"` is required: Windows
   PowerShell 5.1's `Start-Process` joins `-ArgumentList` with spaces without
   quoting, so an unquoted code string reaches Python as `-c import`, which
   exits at once with `SyntaxError`. Confirm the sleeper is alive, then let
   the reply end. Expect one Stop block naming `py.exe` and its `python.exe`
   child.
2. Kill that process, then send a trivial message. Expect no report.
3. Confirm no MCP `node.exe` and no process belonging to a second, separately
   open session was listed.
4. If step 1 shows nothing, check stderr in transcript mode for
   `leftover_processes: no claude.exe ancestor; not tracking` before
   concluding there was no leak — that note means the session-root lookup
   failed inside the hook, which is a defect in the lookup, not evidence
   nothing leaked.

Record the result here, with the date, next to the runs below.

**Recorded result (2026-09-16, one session):** step 1 blocked exactly once,
naming `py.exe` and its `python.exe` child and nothing else -- no MCP
`node.exe`. After `taskkill /T` the next two replies ended with no report.
The first attempt measured nothing: it hit exactly the unquoted-`-ArgumentList`
failure step 1 above warns about, so the sleeper never lived and the hook's
silence proved nothing until the code string was quoted and the sleeper's
liveness confirmed first. **Still not observed:** step 3, a second
concurrently open session's processes staying out of the report — do not
treat cross-session attribution as field proven until that is recorded here
with its date.

**Recorded result (2026-09-16 13:28, second run, separate session):** step 1
blocked exactly once, naming only `py.exe` 658720 and its `python.exe` 658676
-- no MCP `node.exe`, and nothing from the "forgepact-ci-build" session, which
had its last activity at 13:31 and was running builds and an implementer
subagent around that time. The detached sleeper was attributed even though
`Start-Process` orphaned it. The sleeper was deliberately left alive, and the
next reply ended with no report, which confirms report-once. Step 2's
"killed, then silent" variant was not repeated in this run. This is a positive
cross-session observation but a weak one: it was not confirmed that the other
session started a process inside the sleeper's exact call window.

**Live negative control, 2026-09-16 10:51 and 11:00 (recorded, not yet
positive):** the hook went live in its own driver session as soon as
`settings.json` changed, ahead of any planned live check. The first Stop, with
several background agents running, blocked and reported 12 processes; 11 were
false positives -- the hook's own concurrent sibling `PostToolUse` hook chains
and their `conhost.exe`s, all dead by the time they were checked. A second
Stop reported 8 more: a still-running background verifier's own acceptance
run, correctly attributed but not actually left behind. Both runs are false
positives this hook must not repeat, not evidence the mechanism works; they
are the reason rules (a)-(c) now also exclude any chain running a
`.claude/hooks/*` script and any `conhost.exe` reached through the Stop-time
ledger extension, and why the report and `AGENTS.md`'s section both say a
background task of this session still working is a reason to leave a process,
not a leftover. The one plausible true positive that day, a `vctip.exe` from a
C++ build, could not be killed with `taskkill` under auto mode's workload
classifier -- see `AGENTS.md`'s section for what to do instead (tell the user,
name the PID).

## Agents — `agents/`

There are two kinds here, and the distinction is the whole design.

**Phase agents run in sequence**, each at its own model tier, and each hands the
next one a document rather than a conversation. They are driven by
`/workorder`, never spawned by hand.

| Agent | Model | Does |
|---|---|---|
| `planner` | opus | researches the change and writes `.claude/workorders/<slug>-plan.md`, whose acceptance criteria are commands and files, never prose |
| `implementer` | sonnet | executes the steps; returns `PLAN-DEFECT` with evidence rather than improvising around a plan that turns out to be wrong |
| `verifier` | haiku | runs the acceptance criteria and reports what they actually printed; read-only, and judges nothing it cannot execute |
| `consultant` | opus | answers **one** narrow question from a phase that hit a decision above its tier, then stops; never implements, plans or reviews |

Why these tiers: planning carries the most judgement that is written down
nowhere, so it gets the strongest model. Implementation is *not* the easy part —
a plan never fully survives contact, and a weak model follows a wrong plan off
the cliff instead of stopping — so it gets a capable one. Verification against
mechanical criteria is genuinely cheap, so it gets the cheapest. The verifier
never sees the implementer's reasoning, because sharing that context would mean
sharing its blind spots.

### Getting a harder model onto a harder problem

Three mechanisms, because they cover three different failures. A pipeline with
only the last one learns that a task was hard by failing at it twice.

**Triage, before anything is spawned.** `/workorder` matches the request against
a table of observable properties — does it introduce concurrency, does it have
to establish an unknown mechanism rather than verify a suspected one, does it
change how a hook attaches, does it change a contract three bindings must agree
on — and starts the planner and implementer a tier up when it matches. The
signals are deliberately *properties of the task*, never a model's own sense of
how confident it feels: a model that cannot solve something is also poorly
calibrated about whether it can, which makes self-reported confidence the least
reliable signal available. The driver states which row it matched, so the user
can correct it for free.

**Consultation, mid-phase.** A phase can return `ADVICE-NEEDED` with one narrow
question; the driver spawns `consultant` (opus, read-only, `fable` for the
hardest rows), then re-spawns the phase with the answer. The phase keeps its
context and its progress, so one hard decision costs one short answer instead of
re-running the whole phase at a higher tier. An agent cannot spawn another
agent, so this is a return-and-redispatch through the driver rather than a call.

The guardrail is one required field: **`WHAT I WOULD DO WITHOUT HELP`**. The
consultant confirms or corrects a position, which is fast and precise, instead
of solving from nothing — which is just the expensive model doing the phase's
job one question at a time. A question without it is sent back. Cap is two per
round; a third means triage was wrong and the *phase* escalates instead, which
makes the frequency itself the signal rather than an open tab.

**Escalation, on repeated failure.** The planner moves to `fable` on a second
`PLAN-DEFECT` and stops on a third. This is the backstop for what the first two
missed, not the router. It works because planning is the cheapest phase by token
volume — a plan is a few thousand output tokens against an implementation's
hundred thousand — so one Fable replan costs less than the implement round it
saves.

The reviewers never escalate and never consult: they run at high volume on every
change, where 2× is real money for no measured gain. Neither does the verifier,
and that one is a design choice rather than economy — it is scoped to what it
can execute, and a route to a judgement call would reopen the door that scoping
closes. An uncertain verifier reports `UNATTEMPTED` and lets a human decide.

**These are tier aliases, not pinned version IDs**, and deliberately. The tier
is the design decision; the version is not. Pinning `claude-opus-5` across eight
files would buy reproducibility this pipeline does not need — the acceptance
criteria are mechanical, so a model change that breaks something fails a *test*,
not a review — at the cost of a stale-ID sweep every generation, ending in a
retired model that breaks the agent outright. This is not the `*Rva*` case
`AGENTS.md` forbids: an alias is a documented moving pointer, where a hardcoded
address is a constant whose meaning moved underneath it.

**Every agent here sets `model:` explicitly — none inherits.** That is the
difference between a tier being a design decision and a tier being an accident
of whatever the operator last picked in `/model`. `sdk-contract-reviewer` and
`tauri-command-reviewer` originally omitted the field, which silently meant
"whatever the session is": running the session on Haiku would have quietly
dropped four rediscoveries' worth of review to the cheapest tier while still
printing a clean report, and running it on Fable would have doubled the cost of
every SDK-touching change without anyone choosing that. Neither is visible in a
diff, which is what makes it the same failure shape as the rest of this file —
something that reports itself working while doing something other than what it
says.

So: set `model:` on every new agent. `inherit` is a valid value when following
the session is genuinely the intent — but say why in the agent's **body**, not
as a YAML comment beside the value. A trailing ` # because …` makes the field
read as `inherit # because …`, which is neither a known tier nor quoted, and
fails both `test_every_pinned_model_is_a_known_tier` and
`test_no_unquoted_hash_in_any_definition`. That is the same ` #` trap described
further down, arriving through the field this page is about.

The one thing that cannot be pinned is the **`/workorder` driver itself** — a
skill runs in the main session, at the session's model. That is why its routing
is written as an explicit table of verdicts and destinations rather than as
judgement: the loop has to be followable at any tier, because the tier is not
ours to choose. If you run the session on Haiku, the phases still run at their
own pinned tiers; only the routing between them gets cheaper.

Note one hard limit behind the tiers: Haiku 4.5 has a 200K context where the
others have 1M. It is comfortable for acceptance criteria plus a diff, which is
all the verifier is given, and that is part of why the verifier's job is scoped
to what it can execute rather than to reviewing the change.

**Domain reviewers run in parallel**, are read-only, and each covers one bug
class that has recurred here. Wall-clock is one agent; only tokens add up.

| Agent | Model | Reviews |
|---|---|---|
| `sdk-contract-reviewer` | sonnet | `hs-game-sdk/`, `tests/cpp/`, and anything reading runtime values: identity-by-positive-signal, instance-handle kind gates, cross-binding parity and test-stub fidelity |
| `tauri-command-reviewer` | sonnet | `hub/src-tauri/src/`: command threading annotations, `announce()` after state changes, independent failure paths, and the debug-only MCP bridge gate |
| `decompile-output-guard` | sonnet | whether a change carries the game's own expression rather than facts about it — the judgement half of `decompiled_output.py` |
| `docs-sync-reviewer` | sonnet | which `instructions.md`, README, index entry, ADR or `release-notes-vX.Y.Z.md` the change just made wrong |
| `instrument-blindness-reviewer` | opus | table-only hook installs, hand-resolved addresses, struct-layout assumptions, and negatives recorded without a positive control |

`sdk-contract-reviewer` covers four separate rediscoveries of one defect;
`tauri-command-reviewer` covers three shipped hangs; `instrument-blindness-reviewer`
covers 34 hooks reporting zero calls against a game that was calling them. Each
agent's file records the incidents, because the reason these are hard to catch in
ordinary review is that the code reads as correct.

`docs-sync-reviewer` is the one whose bug class has not shipped as a crash. It
exists because of 2026-09-14 — the incident `CLAUDE.md` was written to prevent,
where two fixes went up for review with no documentation updates. That rule is
still enforced by nobody else.

Hooks and agents overlap deliberately, twice. On `hub/src-tauri/` the hook takes
the two violations that are a grep and the agent takes the judgement call ("does
this synchronous command touch disk or the network?"). On decompiled output the
hook takes text that is unmistakably a listing and the agent takes the question
no pattern answers: has a paraphrase crossed from describing behaviour into
reproducing expression?

## Skills — `skills/`

| Skill | Invocation | Purpose |
|---|---|---|
| `catalog-rebuild` | user-only (`/catalog-rebuild`) | rebuild → sign → verify → test, with the signing-key and CRLF rules attached |
| `workorder` | user-only (`/workorder`) | drives plan → implement → verify across the phase agents, routing defects back to the phase that caused them |
| `submodule-context` | Claude-only | loads the right `docs/submodules/<name>/instructions.md` before work starts |

`catalog-rebuild` is user-only because it has side effects and needs a signing
key that is deliberately not in this repository. `workorder` is user-only
because it spawns at least three agents and is the wrong tool for a one-line
fix — the cost should be a deliberate choice, not something that fires on a
typo. `submodule-context` is Claude-only because it is background knowledge, not
an action anyone invokes.

`workorder` owns the loop the phase agents cannot run themselves: an agent
returns a verdict to whoever spawned it, so the routing — `PLAN-DEFECT` back to
the planner, `IMPL-DEFECT` back to the implementer — lives in the driver. Two
caps keep that loop from burning tokens on a problem it has lost: **2 replans**
and **3 implement→verify rounds**, then it stops and asks a human. The
workorder file itself is `.claude/workorders/<slug>-plan.md`, gitignored by the
existing `*-plan.md` rule, which matches at any depth.

Three rules exist because the first real run — the panel-and-launcher
performance pass — hit the cap with seven items open and had to be finished by
hand, outside the phase separation:

- **Only `BLOCKING` findings spend a round.** Every reviewer labels each finding
  `BLOCKING` or `NON-BLOCKING`. That run reached its cap on a round whose
  instrument reviewer opened with *"nothing here blocks shipping"* and then
  listed eight improvements — polish consumed the last round and stopped eight
  findings that were already green. Non-blocking findings ride along as context
  and surface in the final report.
- **At the cap, split rather than raise.** The recovery is a new workorder
  carrying only the still-open findings, with its own fresh three rounds. The
  cap means the pipeline lost the thread, and that does not become untrue
  because the plan is large; raising it buys more of what was not working.
- **Triage warns on size.** The caps are per *workorder*, so an oversized plan
  puts unrelated work on one shared budget. Above 30 criteria, 3 independent
  findings, or one submodule, the driver says so before spawning. That run was
  116 criteria, 9 findings, 2 submodules, 1,524 lines — no individual finding
  was too hard, there were simply too many sharing one budget.

It has three modes: `/workorder <task>` runs everything, `/workorder plan
<task>` stops after the plan, and `/workorder resume <slug>` picks up at
implementation — in a **different session**, which is the point. Splitting there
buys two things the in-pipeline phase boundaries do not: a human checkpoint
where a plan can be argued with before any code exists, and a real test of
whether the plan is self-sufficient, since a fresh session has none of the
conversation that produced it. Context isolation is *not* one of the benefits —
planner and implementer are already separate subagents with separate contexts
either way.

That makes the split a forcing function rather than just a workflow: a plan that
cannot survive a fresh session was never a plan, it was a conversation someone
was still holding in their head. `resume` checks for exactly that before
spawning anything, and routes `PLAN-DEFECT` if a step says "as discussed" or
leans on a decision that was never written down.

Because the skill cannot invoke itself (`disable-model-invocation: true` — three
agent spawns is the wrong answer to a typo), `AGENTS.md` § "Offer `/workorder`
When the Work Has Shape" carries the trigger list that makes Claude *suggest*
it. Suggest, wait, and drop it if the answer is no.

## MCP servers — `../.mcp.json`

| Server | For |
|---|---|
| `tauri-hub` | driving a running debug hub through its bridge on `127.0.0.1:9223` |
| `context7` | live library documentation; `AGENTS.md` § "YYToolkit Integration" already assumes it |
| `github` | releases, dispatches and pointer PRs across the eleven repositories |

`tauri-hub` is pinned to `@hypothesi/tauri-mcp-server@0.13.0` to match
`tauri-plugin-mcp-bridge = "0.13"` in `hub/src-tauri/Cargo.toml`. Keep those two
in step: some tools (the desktop `manage_window` actions) return a version error
against an older plugin.

The bridge only exists in a **debug** build — it is registered under
`#[cfg(debug_assertions)]` because it can invoke any command in the application.
Start the hub with `npm start` in `hub/` and wait for `:9223` before expecting
`tauri-hub` to connect. `AGENTS.md` § "Drive a Tauri App Yourself Instead of
Asking Someone to Click It" has the rest, including the window label (`hub`, not
the `main` every tool defaults to).

`github` does **not** authenticate interactively. Claude Code tries OAuth
dynamic client registration, that endpoint does not support it, and the session
reports *"Incompatible auth server: does not support dynamic client
registration"*. Probing directly confirms what it wants: a POST with a bearer
token returns 200, without one 401. So `.mcp.json` sends
`Bearer ${GITHUB_MCP_PAT}`, expanded from the environment — no token in the
repository.

Set it once, piping so the value is never displayed:

```powershell
[Environment]::SetEnvironmentVariable('GITHUB_MCP_PAT', (gh auth token), 'User')
```

**Claude Code must be restarted afterwards.** A process reads its environment at
launch, so the session that sets the variable is never the session that can use
it.

Three things worth knowing about that arrangement:

- **It is a copy, and copies go stale.** That is the `gh` CLI's own OAuth token.
  `gh auth refresh`, `gh auth logout` or a re-login rotates it, and this copy
  then 401s while `gh` itself keeps working — so the symptom is "the MCP server
  broke for no reason". Re-run the command above to resync.
- **It is plaintext at rest**, in the user's registry environment, readable by
  anything running as that user. `gh` keeps its own copy in the OS keyring, so
  this is a deliberate downgrade accepted for convenience.
- **It is broadly scoped**: gist, read:org, repo and workflow across *every*
  repository the account can reach, not just this one. A fine-grained PAT
  restricted to the `falorfrozen-cmd` repos narrows the blast radius
  considerably and drops into the same variable.

Until the variable is set the entry simply fails to connect, which is harmless —
the `gh` CLI covers the same ground and keeps its token in the keyring.

## A trap worth knowing: `#` in frontmatter

An agent or skill `description:` is a **plain YAML scalar**, so a space followed
by `#` opens a comment and everything after it is silently dropped — no error,
no warning, and the file still loads. `tauri-command-reviewer` shipped with
`adds or edits a #[tauri::command]` in its description and lost the last 86
characters, which were the trigger conditions that make the agent get picked at
all. It is now written as a **double-quoted scalar**, which is the right fix:
the attribute stays readable in the trigger text, and the quoting stops YAML
treating the `#` as a comment. Do the same for any `description:` containing
attribute syntax, a shell flag, or a URL with a fragment — quote the value
rather than rewording around the character, and never put authoring notes in
`description:` itself, since that text is what gets matched against.

To check a file: strip the frontmatter and look for an unquoted ` #` in it.

## Changing any of this

Two suites cover this directory, and both run with the rest:

```bash
py -3 -m unittest discover -s tests
py -3 -m unittest tests.test_claude_hooks -v     # the hooks actually block
py -3 -m unittest tests.test_claude_agents -v    # the definitions are well-formed
```

`test_claude_agents.py` enforces the two rules on this page that a machine can
check: every agent pins `model:` to a known tier alias, and no frontmatter
carries an unquoted ` #` that would silently truncate the value. Both are
invisible in a diff and neither had a check before. It self-tests its own
parser, for the same reason everything else here does.

Every test there is a **pair**: a positive control proving the hook fires on a
real violation, and a negative control proving it stays quiet on a clean tree.
A suite with only the negative half passes against hooks that do nothing, which
is exactly the failure this project keeps rediscovering — see `AGENTS.md`
§ "Prove the Instrument Before Trusting a Negative Result". If you add a check,
add both halves.

The rig builds a throwaway git repository in the system temp directory rather
than the session scratchpad, where `git init` fails with `Filename too long`.
