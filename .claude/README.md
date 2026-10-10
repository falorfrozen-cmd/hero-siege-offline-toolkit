# `.claude/` — the automated half of `AGENTS.md`

`AGENTS.md` holds this repository's rules in prose. This directory holds the
subset that a machine can enforce or execute, so they stop depending on whether
an agent happened to read the right section of a long file first. `AGENTS.md`
itself states each rule plus one sentence of why; the dated incident or review
finding that made a rule worth writing lives in `docs/agents/<section>.md`,
linked from the rule, so it stops being loaded into every subagent's context
on every turn.

Everything here is committed on purpose. Only `settings.local.json`
(per-machine overrides) is gitignored.

## Hooks — `settings.json` + `hooks/`

`settings.json` fires one `PostToolUse` command per call,
`.claude/hooks/post_tool_use.py`, which runs the four checks below in-process
against one shared `git status` (`_common.TreeState`, its explicit injection
point) instead of launching a separate `py -3`, and its own `git status`, per
check. Each check keeps its own `check(payload, tree) -> (rc, message)`
body and its own standalone `main()`, so `py -3
.claude/hooks/decompiled_output.py` still behaves exactly as it did before the
dispatcher existed; `tests/test_claude_hooks.py`'s `TestDispatcherEquivalence`
proves the two paths agree. A crash in one check is caught and reported as its
own non-blocking line rather than masking, or blocking for, the others. Every
check exits 0 silently when nothing is wrong and 2 with an explanation when
something is. They all run through `py -3`; on a non-Windows machine change
that to `python3` in `settings.json`.

| Check | Fires when | Catches |
|---|---|---|
| `catalog_signature.py` | `catalog/` differs from HEAD | `catalog/catalog.json` no longer verifying against its minisign signature, with CRLF called out by name when that is the cause |
| `tauri_command_guard.py` | a `.rs` under `hub/src-tauri/src/` differs from HEAD | `block_on` inside a `#[tauri::command]`, and `#[tauri::command(async)]` on an `async fn` |
| `hub_frontend_tests.py` | a top-level `hub/src/*.js` differs from HEAD | the hub's frontend tests failing |
| `decompiled_output.py` | any changed text file, in the hub **or in a dirty submodule** | Ghidra/IDA symbols, GameMaker VM pseudo-variables, GML positional arguments and bytecode mnemonics reaching a tracked file |

**Adding a check now:** give it a `check(payload, tree: TreeState) -> (rc,
message)` function, add its module name to `post_tool_use.py`'s
`TREE_CHECKS` tuple, keep a standalone `main()` for its own CLI, and add a
positive/negative pair to both the check's own test class and
`TestDispatcherEquivalence` in `tests/test_claude_hooks.py`.

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

## Agents — `agents/`

There are two kinds here, and the distinction is the whole design.

**Phase agents run in sequence**, each at its own model tier, and each hands the
next one a document rather than a conversation. They are driven by
`/workorder`, never spawned by hand.

| Agent | Model | Does |
|---|---|---|
| `planner` | opus | researches the change and writes `.claude/workorders/<slug>-plan.md`, whose acceptance criteria are commands and files, never prose |
| `implementer` | opus | executes the steps; returns `PLAN-DEFECT` with evidence rather than improvising around a plan that turns out to be wrong |
| `verifier` | haiku (medium) | runs the acceptance criteria (first through `tools/run_criteria.py --jobs auto`, which runs every command-shaped criterion in one call, independent ones at once; after a fix, only the criteria the fix reaches plus the failed ones), or one item's `checks:` in a streamed plan, and reports what they actually printed; read-only, and judges nothing it cannot execute |
| `consultant` | opus | answers **one** narrow question from a phase that hit a decision above its tier, then stops; never implements, plans or reviews |
| `live-operator` | opus | runs a workorder's written `### Live procedure <n>` against the real game through `hs-drive` — its own save backup, the positive control first, raw output to `<slug>-live-<n>.md` — and hands every in-game action a person must take back to the driver; never installs a build, never judges the mechanism |
| `scribe` | haiku (low) | pastes a precomputed round Log entry and replacement State lines into the workorder's own `-plan.md`/`-context.md`, with `Read`/`Grep`/`Edit` only (no shell); spawned only by `workorder-rounds.js`, and records the round's findings rather than acting on them |

Why these tiers: planning carries the most judgement that is written down
nowhere, so it gets the strongest model. Implementation is *not* the easy part —
a plan never fully survives contact, and a weak model follows a wrong plan off
the cliff instead of stopping — so it gets a capable one: `opus` since
2026-09-22, when Opus 5.5 made that tier cost about what Sonnet 5 does for
this cache-read-dominated work and the Sonnet tail was what hit the round caps
(`skills/workorder/SKILL.md` § "Model tiers" has the prices and the
measurement). Verification against mechanical criteria is genuinely cheap, so
it gets the cheapest. The domain reviewers and `live-operator` run opus at
`medium` effort since 2026-10-06 (#436), and the session that drives
`/workorder` should run opus/medium too (§ "Model tiers" says why). Every agent that can take one also pins `effort:`, for
the same reason it pins `model:` — left out, it silently follows the session.
Where `/workorder` runs one agent at more than one effort, the agent lists
the extra levels in `effort-variants:` and `tools/sync_agent_tooling.py`
generates `<agent>-<level>.md` for each (`planner-xhigh`, `implementer-medium`
and so on): the `Agent` tool takes a model per call but no effort, so the
agent's name is how a spawn picks one. Never edit a variant; edit its
source and re-run the sync. The verifier
never sees the implementer's reasoning, because sharing that context would mean
sharing its blind spots.

The `planner` (and its variants), `implementer`, `implementer-medium`,
`consultant` and `consultant-max` reach the `ghidra` MCP server's read tools,
named `mcp__ghidra__<tool>` in their `tools:` lines: search, list, decompile,
xrefs, callers, callees, call graph and function info. The read set is
`AGENT_READ_TOOLS` in `tools/ghidra_mcp.py`, and
`tests/test_ghidra_agent_tools.py` pins those lines to it and fails any write
or debugger tool on them. Every other agent (verifier, scribe, `live-operator`,
the reviewers) gets none. Their prompts put the MCP first for a game-mechanism
question, treat an empty callers or xrefs answer as "not observed", and do not
let a `FindCallers.java` zero close the question either: it counts only direct
E8/E9 call sites, needs a positive control in the same project, and is blind to
calls through the script table, a global pointer or a method value. They keep headless `analyzeHeadless` with
`ForgePact/tools/ghidra/*.java` as the fallback (AGENTS.md § "Check for a Named
Ghidra Project Before Researching a Game Mechanism").

`live-operator` alone carries the `x64dbg` MCP server's tools, all eight,
named `mcp__x64dbg__<tool>` on its `tools:` line: `status`, `logpoint`,
`command`, `bplist`, `log`, `modules`, `disasm` and `detach`. The set is
`LIVE_OPERATOR_TOOLS` in `tools/x64dbg_mcp.py`, and
`tests/test_x64dbg_agent_tools.py` pins the line to it and fails any
`mcp__x64dbg__*` tool on another agent. Its prompt uses them only when a live
procedure names debugger steps: attach under the lease it already holds, a
debugger positive control first, hardware logging breakpoints only, verified
with `bplist`, and `detach` before `hs_stop_game`
([`docs/tools/x64dbg-mcp.md`](../docs/tools/x64dbg-mcp.md)).

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
question; the driver spawns `consultant` (opus, read-only, `consultant-max`
for the hardest rows), then re-enters the phase with the answer appended to the
workorder's `## Log`. Same-phase, same-tier re-entry is a `SendMessage` to
that phase's own agent id (recorded in `## State` › `agents:` when it was
spawned) — the send is what actually keeps its context and progress, not a
claim the driver makes about it. A fresh spawn happens only when that is not
possible (the id does not resolve, or the agent has already been resumed
twice), and carries a `PROGRESS SO FAR` block instead. Either way, one hard
decision costs one short answer rather than re-running the whole phase at a
higher tier. An agent cannot spawn another agent, so this is a
return-and-redispatch through the driver rather than a call.

The guardrail is one required field: **`WHAT I WOULD DO WITHOUT HELP`**. The
consultant confirms or corrects a position, which is fast and precise, instead
of solving from nothing — which is just the expensive model doing the phase's
job one question at a time. A question without it is sent back. Cap is two per
round; a third means triage was wrong and the *phase* escalates instead, which
makes the frequency itself the signal rather than an open tab.

**Escalation, on repeated failure.** The planner moves to `planner-max`
(opus at `max` effort) on a second `PLAN-DEFECT` and stops on a third. This is
the backstop for what the first two missed, not the router. It works because
planning is the cheapest phase by token volume — a plan is a few thousand
output tokens against an implementation's hundred thousand — so one
maximum-effort replan costs less than the implement round it saves. Until
2026-10-05 the escalation, the hard triage rows and the hard-row consultant
went to `fable`; the owner's license dropped it that day, and each became an
`opus` effort variant one or two levels up.

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

Note one limit behind the tiers: Haiku 5.5 has a 1M context, as the others
do, but bills any turn whose prompt is over 100K tokens at 5x (Haiku 4.5 had a
hard 200K context). Acceptance criteria plus the one context section a
criterion cites, which is all the verifier opens, stay well under it (p90 64K
over 87 sessions), and that is part of why the verifier's job is scoped to
what it can execute rather than to reviewing the change.

**Domain reviewers run in parallel**, are read-only, and each covers one bug
class that has recurred here. Wall-clock is one agent; only tokens add up.

| Agent | Model | Reviews |
|---|---|---|
| `sdk-contract-reviewer` | opus | `hs-game-sdk/`, `tests/cpp/`, and anything reading runtime values: identity-by-positive-signal, instance-handle kind gates, cross-binding parity and test-stub fidelity |
| `tauri-command-reviewer` | opus | `hub/src-tauri/src/`: command threading annotations, `announce()` after state changes, independent failure paths, and the debug-only MCP bridge gate |
| `decompile-output-guard` | opus | whether a change carries the game's own expression rather than facts about it — the judgement half of `decompiled_output.py` |
| `docs-sync-reviewer` | opus | which `instructions.md`, README, index entry, ADR or `release-notes-vX.Y.Z.md` the change just made wrong |
| `instrument-blindness-reviewer` | opus | table-only hook installs, hand-resolved addresses, struct-layout assumptions, and negatives recorded without a positive control |

**Delta-scoped from round 1 on.** No reviewer is given the workorder path —
each dispatch pastes `## Goal`, `## Out of scope`, the diff commands, and the
paths this round touched, found with
`.claude/skills/workorder/round_delta.py` (`snapshot <slug> <round>` before
the round, `delta <slug> <round>` after; the snapshot also records each
repo's HEAD, so work the implementer commits mid-round lands in the delta too,
not only what it leaves dirty; exit 3 means the snapshot is missing,
unreadable, or a recorded head can no longer be trusted, and everything is
treated as changed). Round 0 runs every
applicable reviewer against the whole change. Round ≥ 1 runs `verifier`
always, plus every reviewer that was `BLOCKING` last round or whose own
trigger paths (stated in that reviewer's file) appear in the delta; a
reviewer skipped this way is recorded as `clean@round<n>, not re-run`.
`decompile-output-guard` is the one exception to being skippable — a legal
finding is always blocking, so it re-reads every added line every round
regardless of the delta.

The diff commands a reviewer actually gets differ by mode. In workflow mode
(the default — "Skills" below), they are per-repo and read from
`round_delta.py heads`'s recorded base commits rather than `HEAD`, because a
`HEAD`-relative diff after the round's own commits is empty; the driver-mode
fallback still reads `git status --porcelain -uall` / `git diff HEAD` per
repo, as `skills/workorder/SKILL.md` § "Step 3 — verify" states.

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

## Skills — `skills/`, mirrored from `../.agents/skills/`

Every skill except `workorder` is written in `.agents/skills/`, the location
Codex and most other agents scan, and `.claude/skills/<name>/` is a
byte-for-byte copy made by `tools/sync_agent_tooling.py`, because Claude Code
scans only `.claude/skills/`. Edit the `.agents/skills/` copy and re-run the
sync; `tests/test_agent_tooling_sync.py` fails on a mirror that differs or a
skill added under `.claude/skills/` alone. `workorder` stays Claude-only (see
§ "Codex" below). A user-only skill also gets a generated
`agents/openai.yaml` with `allow_implicit_invocation: false`, Codex's
equivalent of `disable-model-invocation: true`.

| Skill | Invocation | Purpose |
|---|---|---|
| `catalog-rebuild` | user-only (`/catalog-rebuild`) | rebuild → sign → verify → test, with the signing-key and CRLF rules attached |
| `workorder` | user-only (`/workorder`) | drives plan → implement → verify across the phase agents, routing defects back to the phase that caused them |
| `submodule-context` | Claude-only | loads the right `docs/submodules/<name>/instructions.md` before work starts |

The remaining eleven directories are vendored, unmodified, from
[`emilkowalski/skill`](https://github.com/emilkowalski/skill) (MIT) so every
contributor's agent works from the same frontend and motion guidance —
`.agents/skills/THIRD_PARTY.md` has the pinned commit and how to update them.
Claude Code and Codex both discover them on their own.

| Skill | Invocation | Use for |
|---|---|---|
| `animate` | either | building a web animation |
| `review-animations`, `prototype`, `pick-ui-library` | user-only | critiquing motion code, several UI variants, choosing a frontend library |
| `improve-animations`, `find-animation-opportunities` | either | read-only motion audits of a codebase or UI |
| `emil-design-eng`, `apple-design`, `mobile-native` | either | UI polish, gesture/spring design, mobile web feel |
| `animation-vocabulary`, `ask-sonner` | either | naming a motion effect, the Sonner toast library |

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
and **3 implement→verify rounds**, then it stops and asks a human.

A workorder is two files: `.claude/workorders/<slug>-plan.md` (frontmatter,
`## State`, `## Goal`, `## Out of scope`, `## Acceptance criteria`,
`## Steps` — what everyone who touches the workorder reads) and
`<slug>-context.md` (`## Context the implementer needs` by stable `###`
subsection, `## Needs human judgement`, `## Log` — read by section, only when
a step or a reviewer is pointed at it). `## State` carries `round:`, `phase:`,
`gates:` (the tokens a conditional criterion or step names, instead of
"while the Log lacks X"), `gates pending:` and `route tokens:`, `round base:` (the `round_delta.py` snapshot for
this round), `agents:` (each phase's agent id, for the resume mechanism
above), `reviewers:`, `open defects:`, `patch rounds:` (the patch rounds
that held, which the round cap does not count), `decisions in force:` and,
on a plan that researches a game mechanism, `ghidra mcp:` (whether the
`ghidra` MCP answered the research: `used — <what it answered>`,
`unavailable — <what status printed>; offered setup` or `skipped —
<reason>`, which `tools/plan_lint.py` checks as `ghidra-unchecked` and
`ghidra-bad-value`). `gates:`
lists only the gates that are set, or `none`. Every gate a criterion may
later need sits on `gates pending:`, and the possible research outcomes sit
on `route tokens:`. A gate counts as set only when `gates:` literally carries
its token. A `gates:` value holding `|` or "or" alternatives, or a `<placeholder>`, is a
template and sets nothing. On 2026-09-24 a planner wrote `gates:` as a
template of every gate and every possible value. The verifier read it as all
set and failed the live-session criteria three rounds running, and the launch
went to `CAP` with no real defect open after round 0. The verifier now
reports a criterion whose gate is not set as `UNATTEMPTED (gate <x> not set)`.
`workorder-rounds.js` reads `gates:` itself and routes a round as
`PASS-PENDING-HUMAN` when every failure it has is gated on a gate that is not
set and no reviewer found anything BLOCKING. `tools/workorder_audit.py` R19
flags whoever wrote the template line. The nine plans written before this
split stay valid — same sections, single-file — located with
`grep -n '^## \|^### '` rather than assumed; nothing routes on which shape it
finds. Both files, and the `.claude/workorders/.rounds/` round snapshots, are
gitignored at any depth, for the reason `AGENTS.md` § "Documentation &
Instructions Maintenance" gives: they are working notes for the run, and what
is still true once the work lands belongs in `docs/` instead.

Three rules exist because the first real run — the panel-and-launcher
performance pass — hit the cap with seven items open and had to be finished by
hand, outside the phase separation:

- **Only `BLOCKING` findings spend a round.** Every reviewer returns `blocking`
  findings, `non_blocking` findings, and a separate `plan_defect` flag for the
  round — set only when no implementation of the plan as written could satisfy
  its Goal; a missing assert, pin, or sentence the plan didn't forbid is a
  `BLOCKING` finding for the implementer, not a defect in the plan, so an
  implementer's own oversight cannot route back to the planner as a costly
  replan. That run reached its cap on a round whose instrument reviewer opened
  with *"nothing here blocks shipping"* and then listed eight improvements —
  polish consumed the last round and stopped eight findings that were already
  green. Non-blocking findings ride along as context and surface in the final
  report.
- **A fix that is already known does not buy a full round.** When every
  BLOCKING finding of a round carries its reviewer's exact `fix`, and nothing
  else failed, the next round is a *patch round*. A `patch-implementer`
  applies the fixes, the verifier re-verifies by reach when the last verify
  allows it (every criterion otherwise), and only the finding
  reviewers and `decompile-output-guard` re-run. If `round_delta.py size`
  then shows at most 20 changed lines, no new file and no instrument path or
  release note, the round is not counted against the cap. The same idea
  covers plans: a `PLAN-DEFECT` that states its own correction goes to an
  `amendment:` planner, and `tools/amend_check.py` decides from the files
  whether it stayed an amendment (Goal, scope and human questions untouched,
  at most 20 lines) or counts as a replan. `skills/workorder/SKILL.md` Steps 2
  and 4 have the rules, and `docs/agents/workorder-calibration.md` the
  measurement behind them.
- **At the cap, split rather than raise.** The recovery is a new workorder
  carrying only the still-open findings, with its own fresh three rounds. The
  cap means the pipeline lost the thread, and that does not become untrue
  because the plan is large; raising it buys more of what was not working.
- **Triage warns on size.** The caps are per *workorder*, so an oversized plan
  puts unrelated work on one shared budget. Above 30 criteria, 3 independent
  findings, or one submodule, the driver says so before spawning. That run was
  116 criteria, 9 findings, 2 submodules, 1,524 lines — no individual finding
  was too hard, there were simply too many sharing one budget.

**Each worktree gets its own submodule checkout.** Step 1 (and `resume`) run
`py -3 .claude/skills/workorder/ensure_submodule.py <module>` before planning
starts, whenever the workorder's module is a submodule not yet initialized in
this checkout. Without it, a linked worktree that never initializes the
submodule silently falls back to reading and writing the MAIN checkout's copy
— which is what happened to `prospect-idcheck-pin-hardening`'s ForgePact work
on 2026-09-17, and is exactly why two worktrees could not work the same
submodule at the same time. The script gives this checkout its own gitdir
(`git submodule update --init --reference <main>/<module> --dissociate`,
proven cheap here: the module's own object store measured 14MB), then prints
the module's new HEAD and git dir, and — only when a main-checkout copy exists
to reference — the exact command to bring unpushed work across:
`git -C <module> fetch "<main>/<module>" <branch>`. It never touches the main
checkout and never creates or switches branches; it only checks out the
commit the gitlink already names, and a second run is a no-op
(`already initialized: <module> @ <sha>`). From there, all work on that
module — reading, editing, building, committing, the work branch — stays in
this checkout's own copy, never another checkout's. Removing a worktree that
has initialized a submodule this way needs `git worktree remove --force`
("working trees containing submodules cannot be moved or removed").

**A workorder cannot be run against another checkout, and the driver stops
rather than trying** (`SKILL.md` Step 0.25). A session opened in a worktree
has every `Edit` and `Write` outside that worktree refused by the harness — a
guard on the user's main working copy. `forgepact-closure-names-current-game`
(2026-09-18) was planned against the main checkout on request, because the
unpushed branch and five deliberately uncommitted guide lines lived there; its
implementer met the refusal, and instead of returning `PLAN-DEFECT` routed
every edit through scratch byte-patch scripts: 57 of 142 turns, 9.4M of 22.6M
tokens, a 31M-token round against a 15M budget. The driver now names the two
ways forward instead — open the session in that checkout, or bring the work
here — `planner.md` refuses to write such a plan (`status: BLOCKED`),
`implementer.md` makes the refusal a `PLAN-DEFECT`, and the audit's R15 fails
any run that carried on after it. The script's `repoRoot` argument only ever
re-pointed the git commands agents are handed, never where `Edit` lands, which
is why it looked like an escape hatch and was not one.

**`.claude/skills/workorder/section.py <file> '<heading>'` prints one section
of a workorder file** — heading to the next heading of the same or a higher
level, fenced code ignored by CommonMark's rule, CRLF and LF alike. The
heading is single-quoted because headings carry backticks, which Bash runs as
a command inside double quotes. A citation matches the way planners write
them, strictest first and a looser tier only when it names one heading: the
exact text, then the text with backticks ignored, then a prefix (`ctx: "Code
and test sites"` for a heading that goes on in parentheses — and the way to
cite a heading with an apostrophe, which would end the single quotes: stop
before it). Exit 3 lists the
file's headings, 4 names an ambiguous one, 5 refuses a file with an unclosed
fence rather than printing to its end, and 6 refuses `## Log` and everything
under it unless `--log` is passed — the Log is also left out of the listing
and cut from a level-1 section. It is how the verifier follows a criterion's
citation into the context file without reading the rest, whose `## Log` is the
implementer's reasoning; an implementer or the driver reading a round's entry
passes `--log`. It reads any markdown file, module guides included: `--toc`
lists every heading with its line and section size, and `--grep '<regex>'`
prints only the list items and paragraphs of a section that match, windowing
an item over 4,000 characters around each match — ForgePact's guide is 334KB
and 23 of its lines hold 128KB, so even a 20-line `Read` window returned 45KB
and R3 failed in 8 of 22 sessions for agents that *were* reading by section. That same run's verifier had no context path in its dispatch
and no command for a `###` heading; it spent eight calls looking and then read
the whole file (audit R2, which now also catches a `cat`/`sed`/`Get-Content`
of a context file, since `Read` is not the only way in). The workflow now
passes the path and the command — the plan's own path for a legacy single-file
plan.

**`tools/workorder_brief.py <plan> <selector>` prints one implementer's slice
of a workorder in one call**, built on `section.py`'s heading matching,
`plan_lint.py`'s lane and item parsers and `run_criteria.py`'s criterion
numbering. The selector is `--round N`, `--lane NAME`, `--join`, `--item ID`,
`--paths P[,P...]` or `--criteria K[,K...]` (the last also adds criteria next
to another selector), and `--context`, `--base REF`/`DIR=REF`,
`--since-round K` and `--amended` add to it. Every brief prints a header with
its size against the plan's and context's, `## Goal`, `## Out of scope`,
`## State`, the preconditions above the first lane, item or join, the
selection, each Context subsection the printed steps and criteria cite by
`ctx:` (an unresolved citation prints `ctx not found: "<cite>"`),
`### Decisions`, the `git diff` commands for the selection's files when a
base is given (it prints them and never runs git), and a footer listing the
Context headings it left out with the full files named as the fallback.
Nothing else from `## Log` is printed, except the previous round's entry for
`--round N` past 0 and the newest amendment with `--amended`. Exit 0
printed, 2 a usage error or unreadable plan, 3 a lane, item or criterion
that does not exist, 5 an unclosed fence. Every implementer prompt
`workorder-rounds.js` writes names its brief command first, with the plan
and context paths kept as the fallback, and SKILL.md's Step 2 spawn does the
same. `workorder-rounds.js` runs in the Workflow tool, which cannot read a
file, so the prompt names a command rather than carrying the slice. Tests:
`tests/test_workorder_brief.py`.

**It also provisions each module's local-only build prerequisites**, on both
the fresh-init path and an already-initialized one.
`.claude/skills/workorder/local_prereqs.json` lists, per module, paths a
`.gitignore`d build step needs that no `git submodule update` can produce
because they were never committed anywhere — for ForgePact,
`plugin_build/include/` (the YYToolkit/Aurie/FunctionWrapper headers plus
`YYTK_Shared_Types.cpp`) and the four DLLs/EXE under `modfiles_shipped/`.
Proven on the real repo: a freshly-initialized linked worktree's own
`plugin_build\build.bat dev` failed until `plugin_build/include/` was copied
across by hand, then passed in 25s and produced a byte-size-identical DLL.
The script copies each listed path from the main checkout's copy of the
module when it exists there and is missing here — checked again on every run,
not only a fresh init, since the manifest or the main checkout can gain an
entry after this worktree's module was already set up — never overwriting a
path that already exists here, never copying anything the manifest doesn't
list, and rejecting (not copying) an entry that is absolute or contains `..`.
A run in the main checkout itself provisions nothing, since that IS where the
files already live.

It has three modes: `/workorder <task>` runs everything, `/workorder plan
<task>` stops after the plan, and `/workorder resume <slug>` picks up at
implementation — in a **different session**, which is the point. Splitting there
buys two things the in-pipeline phase boundaries do not: a human checkpoint
where a plan can be argued with before any code exists, and a real test of
whether the plan is self-sufficient, since a fresh session has none of the
conversation that produced it. Context isolation is *not* one of the benefits —
planner and implementer are already separate subagents with separate contexts
either way.

**Workflow mode is the default way steps 2–4 run.** `/workorder <task>` (after
the plan is approved) and `/workorder resume <slug>` call
`.claude/workflows/workorder-rounds.js` instead of driver turns — the user's
own `/workorder` invocation is the opt-in the Workflow tool requires, so the
skill does not ask again. **Driver mode — steps 2–4 as the driver's own turns,
above — is the documented fallback**, used when the Workflow tool is
unavailable, the launch fails, or the user says "driver mode" or "no
workflow". This replaces "opt-in and unproven": it carried
`prospect-idcheck-pin-hardening` through three rounds to `PASS` on
2026-09-17 (fresh sonnet implementer 73–88 turns / 9–10.6M tokens per round,
verifier 2–3M, nine haiku utility agents 1.8M total —
`skills/workorder/SKILL.md` § "Driver discipline" has the matching cost for
the same work done by hand).

Per round the script snapshots (`round_delta.py snapshot`), reads back that
snapshot's recorded per-repo base commits (`round_delta.py heads`), spawns a
fresh implementer at the triaged tier, then runs `verifier` plus the
delta-scoped reviewers above in parallel — each pointed at a `git -C <repo>
diff <sha>` built from those heads rather than `git diff HEAD`, since
implementers commit mid-round and a `HEAD`-relative diff taken afterward is
empty (measured 2026-09-17: every reviewer had to rediscover the round's own
commits by hand, at 23–59 turns instead of the usual 6–17). A reviewer that
has never run reads the whole change from `args.baseHeads` (the workorder's
own starting heads, copied from `## State` › `round base:`) when given, else
the round's own first snapshot; a re-run reviewer reads only the round's
delta paths, split per repo from that round's own heads. If heads could not
be obtained at all, the script falls back to the old `HEAD`-relative commands
and says so loudly in the dispatch, rather than reading nothing silently.
`round_delta.py heads <slug> <round>` prints `<key>\t<sha>` per repo (`.` for
the hub, the submodule dir otherwise; an empty sha for an unborn head),
refusing (exit 3) for exactly the reasons `delta` refuses a snapshot outright
— missing, unreadable, not version 2 — and nothing else, since `heads` never
touches the working tree the way `delta`'s own live-repo checks do. The delta
agent's own content greps now run from the repository root explicitly and
report `files_checked`/`files_missing`, so a path missing because the greps
ran in the wrong directory (previously invisible) is distinguishable from one
deleted this round.

A haiku scribe still records each round, but composes nothing: the exact
markdown — the `### Round <n>` Log entry, `BLOCKING (<k>)`/`NON-BLOCKING (<k>)`
lists with the counts in the headings themselves, and the replacement
`## State` lines — is built in the script, and the scribe's only job is to
paste it verbatim. This is the fix for a measured relabel: a scribe once
turned a round's own `1 BLOCKING` + `5 NON-BLOCKING` verdict into six
`BLOCKING` findings, caught only because the driver happened to read it by
hand; counts baked into the headings make that kind of relabel visible on
sight instead.

The State the scribe pastes is the *whole* block, not just the lines the round
computed. The script merges this round's `round:`/`phase:`/`reviewers:`/`open
defects:` (and, once a patch round has held, `patch rounds:`) into the `## State` the driver passed as `args.state` (or the one the
previous Record pass left), so `gates:`, `round base:`, `agents:`,
`decisions in force:` and anything else are pasted back verbatim; without
`args.state` the scribe is told to edit one line per `Edit`. On 2026-09-23 a
scribe handed only the four computed lines replaced the whole block with them
in several workorders, and the next verifier, reading no `gates:`, reported
gated criteria pending instead of running them. The scribe now also returns
the State lines it read before and after its edits, and a line that was there
before, is not one the round replaces, and is gone after ends the launch as
`STATE-LOST` — carrying `lost`, the full `state` it should read, and `then`,
the outcome the round would otherwise have returned — before any verifier
reads the damaged block. `tools/workorder_audit.py` R18 checks the same thing
from the transcript. A scribe that wrote nothing (`written: false`, or no
result) is not compared at all: the launch ends as `SCRIBE-FAILED`, carrying
the `log` block and `state` it should have written and `then`. The scribe is
handed absolute paths, joined under the driver's `checkoutRoot` (`git
rev-parse --show-toplevel`): on 2026-09-24 a scribe given relative ones in a
worktree resolved them against the main checkout, wrote nothing, and its "N/A"
report came back as a false `STATE-LOST`. Both blocks sit between marker
lines (`<<<LOG-BLOCK-BEGIN>>>` …, `<<<STATE-LINES-BEGIN>>>` …), the Log append
is one `Edit` anchored on the file's last line with the block after it, and
the scribe returns the file's last lines afterwards (`log_tail`): a block
that is not the last thing there ends the launch as `LOG-DAMAGED`, carrying
`log`, the `anchor` the scribe used, and `then`. On 2026-10-03 a scribe given
unfenced blocks pasted its own State instruction into the Log and wrote the
block before its anchor, moving the previous entry's last line to the end.

It runs as the restricted `scribe` agent type (`.claude/agents/scribe.md`,
`Read`/`Grep`/`Edit` only), not the unrestricted `workflow-subagent` every other
Record-phase agent here still is. On 2026-09-19 an unrestricted scribe read
the harness's relayed user message next to a round's findings and acted on
it instead of only recording it — resolving the prompt's relative paths
against the user's home directory, editing ForgePact source and docs, and
running `git add`/`git commit` on both ForgePact and the hub's ForgePact
pointer, with no build, test or review. A second, later run repeated the
incident on a route the git check alone never sees: a scribe whose `Write`
was refused overwrote the same file anyway with a Bash heredoc.
`tools/workorder_audit.py` R16 fails a run whose scribe edited outside
`.claude/workorders/`, touched git, wrote a file through a shell command
(a redirect or heredoc, `tee`, a PowerShell content cmdlet, a Python file
write), or — for the restricted `scribe` agent type specifically — ran any
shell command at all, since its `tools:` line carries no shell to run one
with.

```
Workflow({ scriptPath: ".claude/workflows/workorder-rounds.js",
           args: { slug, planPath, contextPath, goalExcerpt, implementerModel, round,
                   reviewers: { '<name>': 'never' | 'clean' | 'blocking', ... },
                   submodules: ['<dir>', ...], researchHeadings, baseHeads, priorFindings, state,
                   lanes, join, items: [{ id, files, checks, after, shares, owner, default, reversible, build_reads }, ...],
                   streaming, answered, reviewScopes,
                   maxParallel /* DEFAULT_MAX_PARALLEL, 4; 1-16 */, maxAgents, tokenCeiling, itemAttempts, reviewPassCap } })
```

`reviewers` is a map, one entry per applicable round-0 reviewer, valued
`'never'`. `submodules` names the dirs whose own diff the reviewers must
read, relative to `repoRoot`. `researchHeadings` names the context file's
`###` heading(s) `instrument-blindness-reviewer` should read. `baseHeads` is
`{ '.': sha, '<submodule>': sha, ... }`, copied from `## State` ›
`round base:`. `priorFindings` is `{ '<reviewer>': [{ where, problem }] }` for
a reviewer entering as `blocking`, copied by the driver on a fresh launch from
the most recent `### Round <n>` Log entry that carries a `BLOCKING (k)` list;
between rounds of one launch the script carries it itself. `state` is the
plan's `## State` section as `section.py <plan> 'State'` prints it, which the
Record pass merges each round's lines into (see the scribe above). A
re-run reviewer that was blocking is handed its own finding and asked whether
the delta resolves it, every re-run is told earlier rounds reviewed the rest,
and every reviewer is told the Out-of-scope list is not a checklist — a
`docs-sync-reviewer` given none of the three ran 40 turns twice, once policing
scope the verifier already checks and once re-deriving a one-file delta's
history. `repoRoot` is still accepted and nothing passes it; see "A workorder
cannot be run against another checkout" above.

**Lanes** (issue #176) are step groups a plan declares as `### Lane: <name>`
headings with a `files:` line, plus one `### Join`. `lanes` (`[{ name, files }]`)
and `join` are pasted from `py -3 tools/plan_lint.py <plan> --lanes-json`, and
only for the first implementation of the plan's steps: round 0, or the
relaunch after a replan. On the round a launch starts at, the script runs one
implementer per lane (`implementer:<name>:r<n>`) through one `parallel()`
barrier, however many lanes there are. Each lane stays inside its file set,
runs no git write and no full build or suite, and checks the cooperative stop
marker (`round_delta.py stopped`) before each step. A lane about to return
`PLAN-DEFECT` or `ADVICE-NEEDED` writes the marker first (`round_delta.py
stop`), and the others return `STOPPED`. When every lane returns `IMPL-DONE`,
the join (`implementer:join:r<n>`) is handed every lane's report, commits each
lane's file set as its own commit by pathspec, does the `### Join` steps, and
its result goes down the same delta and verify path as a single implementer's.
Otherwise the join is skipped, the Log records every lane's verdict and
progress, and the launch returns `PLAN-DEFECT` if any lane returned it, else
`ADVICE-NEEDED`. Later rounds of the launch run one implementer that owns every
file set. Lanes that could not have come from `--lanes-json` are `BAD-ARGS`.
Absent or empty `lanes` dispatches exactly the prompt a plan without lanes
always got.

**Items** (2026-09-26) replace rounds with a streamed pipeline for a plan
whose `## Steps` declares `### Item: <id>` groups. `items` is pasted from
`plan_lint.py <plan> --items-json`. Each item gets its own implementer
(`item-implementer:<id>:a<k>:r<n>`) the moment no running item holds its
files; items sharing a file queue in plan order. The implementer commits
only its own paths through `tools/item_commit.py`, then an independent
`item-verifier:<id>:a<k>:r<n>` runs its `checks:`. A failure sends it back
with the evidence, up to three attempts. Reviewers (`<name>:p<k>:r<n>`) read
committed ranges pinned to the `HEAD` they start from, re-run as new commits
match their trigger, and each finished reviewer's `BLOCKING` findings become
a `fix-implementer:fix-<k>:r<n>` on the files they name. An item that stops
parks alone, holding only what depends on it. When nothing is left, the
acceptance criteria run once (`verifier:r<n>`), and a failure there becomes
one fix that runs alone before the gate runs again. It returns `PARKED`,
`CEILING` or the round outcomes, with every item's status. Which item may
start is a set of pure functions between the script's `@scheduler` markers,
which the test file cuts out and tests directly. `maxParallel` defaults to
`DEFAULT_MAX_PARALLEL` (4) and anything but a whole number from 1 to 16 is
`BAD-ARGS`: in the first real plan of items no start waited on the cap. An
unanswered owner item with `reversible: true` and a default runs on that
default and is listed under `defaulted` with its commits and how to undo it;
every result that waits on a person lists under `unblocked` the parked work
that does not wait on them.

**Amendments run inside the launch** (2026-09-27). An item implementer's, a
fixer's or a rounds implementer's `PLAN-DEFECT` whose `CORRECTION:` is not
`none` goes through `amend-save:<id>:r<n>` (`tools/amend_check.py save`), a
fresh planner labelled `amendment: <slug> <id>:r<n>`, and
`amend-check:<id>:r<n>`. Only exit 0 with `AMENDMENT` re-runs the work, one
amendment at a time; anything else goes back to the driver as a replan with
its reason, after `amend-restore:<id>:r<n>` (`tools/amend_check.py restore`)
has put the plan and context back as saved. No item starts while an
amendment is queued or running. A lane's and a reviewer's plan defect stay
the driver's.
The whole-tree verifiers (the rounds verifier, the reach re-verify and the
items gate) start `run_criteria.py` in the background and poll it with
`--status <out> --wait 220`; one item's checks stay in the foreground.

It returns to the driver on anything needing judgement — `PASS`,
`PASS-PENDING-HUMAN`, `PLAN-DEFECT`, `ADVICE-NEEDED`, `AGENT-FAILED`,
`STATE-LOST`, `SCRIBE-FAILED`, `LOG-DAMAGED` or `CAP` — so replans, consultations, human questions and the step-5 report stay with
the driver either way (only a confirmed amendment runs inside), and one launch may cover several rounds (a
`PLAN-DEFECT` hand-back means relaunching after the replan). A laned round
that ends before its join also returns `lanes`, each lane's `name`,
`verdict` and `progress_so_far`. What it still
trades away: every re-entry inside the script is a fresh spawn, never the
`SendMessage` resume above, because the script has no agent id to send to —
measured, on this one real run, as no worse than a resumed implementer (a
resumed round-1 implementer cost 14.6M tokens at 304K context per turn;
losing the resume cost nothing). `.claude/workflows/workorder-rounds.test.mjs`
(`node --test`, 126 cases, each with its own control) dry-runs the routing
above against stub agents.

That makes the split a forcing function rather than just a workflow: a plan that
cannot survive a fresh session was never a plan, it was a conversation someone
was still holding in their head. `resume` checks for exactly that before
spawning anything, and routes `PLAN-DEFECT` if a step says "as discussed" or
leans on a decision that was never written down.

Because the skill cannot invoke itself (`disable-model-invocation: true` — three
agent spawns is the wrong answer to a typo), `AGENTS.md` § "Offer `/workorder`
When the Work Has Shape" carries the trigger list that makes Claude *suggest*
it. Suggest, wait, and drop it if the answer is no.

**Step 5 audits the run's own cost.** The report step runs `py -3
tools/workorder_audit.py --latest` and prints every `FAIL` line verbatim
beside the round summary — a workorder that passes its acceptance criteria and
still breaks a cost/behavior rule says so, instead of merging on the strength
of the criteria alone.

### `tools/workorder_audit.py` — did this run actually save time and tokens

Before this tool existed, "did a `/workorder` run save time and tokens, and
did it break a rule" was answered by one-off transcript scripts run by hand,
once per question. This makes that judgement runnable and repeatable, against
the same rules this page states above (batching, per-role budgets, plan/context
scope, driver discipline, replans, round budgets):

```
py -3 tools/workorder_audit.py [--latest | --session <id-prefix> | --calibrate <list>]
    [--projects-dir DIR] [--project NAME] [--json]
```

`--session` looks in every checkout of the repository — the main checkout's
project directory and each `.claude/worktrees/<name>` one — when the prefix is
not under the current one, since every `/workorder` session runs in a worktree
of its own. `--calibrate <file>` takes a list of session prefixes (one per
line) and prints, over all of them, each role's turns, tokens, context per
turn and list-price cost as p50/p75/p90/max — per role and per role *and
model* — plus round-0 and later-round totals, driver turns per round, and how
many sessions each rule fails at the constants as they stand. The budgets are
set from that output (story: [docs/agents/workorder-calibration.md](../docs/agents/workorder-calibration.md)).

It streams — never loads whole — a session's transcripts: the driver's own
`~/.claude/projects/<project>/<session>.jsonl`, ad-hoc subagents at
`<session>/subagents/agent-*.jsonl`, and workflow-mode round agents at
`<session>/subagents/workflows/wf_*/agent-*.jsonl`, each paired with a
sibling `.meta.json` carrying `agentType` and a label (a workflow label reads
like `implementer:r1`). `--project` defaults to the mangled name Claude Code
derives from the current working directory (every non-alphanumeric character
becomes `-`); `--projects-dir`/`--project` exist so tests never touch the real
`~/.claude/projects`.

Per agent it reports turns (deduped by `message.id`), tokens (input +
cache-creation + cache-read, summed over assistant turns), output tokens,
context per turn, peak context, wall minutes, the longest single tool call,
the model the transcript actually ran on (what a tier alias resolved to that
day), its list-price cost (`MODEL_PRICES`), and KB of `Read` results by kind
(plan, context file, `instructions.md`, source). The table's `lane` column
names a lane implementer's lane (`implementer:<lane>:r<n>`, `join` for the
join). For every round that ran two or more implementers, a lane summary
follows the table: each lane's wall minutes and cost, the round's span
(earliest lane start to latest lane end) against the lanes' serial sum, and
the join's wall minutes; `--json` carries it under `lanes`, which is what
`docs/agents/workorder-calibration.md` § "Lanes" measures. It prints one table and the
session's total cost, then twenty-five rules as `PASS`/`FAIL` with
evidence (the agent, the time, the command or path), then each role's numbers
against the pre-update averages as a percentage; `--json` emits the same as
one object.

| Rule | Checks |
|---|---|
| R1 reviewer-reads-workorder | a reviewer `Read`/grep of a `-plan.md` (`instrument-blindness-reviewer` may read a `-context.md`) |
| R2 verifier-scope | a verifier whole-file `Read` of a `-context.md` or of an oversized plan, or a shell read (`cat`, `sed`, `head`, `Get-Content`, … as a command, not as part of a slug) of a `-context.md`, or `section.py` run with `--log` — `section.py` without it and a heading `grep` are the sanctioned routes; the reader list is a heuristic drawn from real transcripts, not a fence |
| R3 guide-whole | an agent whose `instructions.md` `Read` results exceed a KB budget |
| R4 batching | an implementer's share of small-sequential-shell-call runs over budget |
| R5 blocking-call | a tool call over the time budget — except `Agent`/`Task`, which dispatch a subagent and are meant to block for minutes, and `AskUserQuestion`, which waits for a person |
| R6 planner-rewrite | a planner `Write` to a plan/context path already written earlier in the session |
| R7 / R8 / R9 reviewer- / implementer- / verifier-budget | turns, tokens, or (implementer only) context-per-turn over that role's budget — each reviewer type has its own (`REVIEWER_BUDGETS`) |
| R10 driver-discipline | a driver shell command that builds or tests, a driver `Edit`/`Write` outside `.claude/workorders/`, or too many driver turns in one round — judged only while it is driving: one window per `/workorder` invocation, from the invocation to the first message the user types after that invocation's last pipeline agent finished (a phase agent, a reviewer, anything in a workflow run — an ad-hoc agent asked for later does not hold it open; harness-written `user` records are not the user), or to the next invocation, so a build the user asks for afterwards, or between two workorders, is not the driver's violation |
| R11 replans | two or more planner runs in one session, not counting an `amendment:` planner whose `tools/amend_check.py check` passed |
| R12 plan-size | a plan or context file whose planner-authored part is over its KB budget, from the `Read` calls that touched it — `## Log` is not counted, being what the scribe, implementer and driver append while the rounds run |
| R13 round-budget | one round's total subagent tokens over budget — a round is one workflow launch's round `n`, never every launch's round `n` added together, and round 0 (the whole change) has a larger budget than a later round (a defect); a round that ran k > 1 implementers (a laned round's lanes and join) gets k times its budget, since R8 already holds each implementer to its own |
| R14 reviewer-reruns-suite | a reviewer running test suites or builds more than twice (the two reviewers told to build and test are exempt) |
| R15 edit-guard-workaround | a subagent whose `Edit`/`Write` was refused by the harness's worktree guard ("is in the base repo checkout") and which then made more than five further tool calls (its own return not counted) instead of returning `PLAN-DEFECT` — unless an edit of the same repo-relative path then landed inside a worktree, which is a mistyped path corrected, not a workaround (a same-named scratch copy is the workaround) |
| R16 scribe-scope | a scribe (`agentType: "scribe"`, or the `scribe` role a workflow label like `scribe:r1` parses to) whose `Edit`/`Write` landed outside its own `.claude/workorders/`, judged against the transcript's own `cwd` rather than a bare substring test; which ran `git add`/`git commit` in any shell command; which wrote a file through a shell command instead (a redirect or heredoc, `tee`, a PowerShell content cmdlet, `cp`/`mv`/`rm`/`sed -i`, a Python file write) whatever the target path; or, for the restricted `scribe` agent type, ran any shell command at all |
| R17 live-operator-scope | a `live-operator` that wrote anything but its own `.claude/workorders/<slug>-live-<n>.md`, installed a build (a `.dll` copied or moved, or `installmod`), ran a writing git command, restored a backup it did not take itself (restoring its own at teardown is required), force-stopped the game, or took over another holder's game lease (`hs_lease_acquire` with `force`) |
| R18 scribe-state-preserved | a scribe `Edit` to a `-plan.md` whose `old_string` carries a `key:` State entry (`gates:`, `round base:`, `agents:`, … — a hand-written `round: 0        phase: plan` counts as two) that its `new_string` no longer has |
| R19 gates-template | any agent's `Write`/`Edit` to a `-plan.md` whose `gates:` line holds `\|` or "or" alternatives (an "or" inside a backticked token does not count) or a `<placeholder>`, outside parentheses: a template of every possible gate, which sets none. Possible gates go on `gates pending:`, and outcome tokens go on `route tokens:` |
| R20 live-capture-author | any agent but `live-operator` (the driver included) whose `Edit`/`Write` landed on a `.claude/workorders/<slug>-live-<n>.md` capture. A capture a criterion cannot read is reported, never repaired |
| R21 verifier-interpreter | a verifier shell command that runs `python` or `python3` in command position (a `grep python` does not count) — this repository's commands are `py -3`, and the verifier runs a criterion exactly as written |
| R22 verifier-suite-once | a verifier that runs the same `unittest discover` suite (same `cd` directory, same arguments) more than once, counting ForgePact's `tools/run_tests_parallel.py` as the same suite as its serial `discover -s tests` — after a timeout, or to read another slice of the output |
| R23 lane-git-mutation | a lane implementer (`implementer:<lane>:r<n>`, any lane but `join`) that ran a git command outside the read-only allow-list R16 uses (a `git config` that only reads, such as `git config core.autocrlf` or `--get`, is on it). Lanes share one checkout and `.git/index.lock` fails instead of waiting, so only the join commits; the join and a laneless implementer are exempt |
| R24 cheap-routes | an `amendment:` planner with no `tools/amend_check.py save` before it or no `check` after it, made by the driver or, for a planner a workflow launch spawned (`amendment: <slug> <id>:r<n>`), by another agent of that same launch (`amend-save:`/`amend-check:`), never the planner itself; a second amendment with no implementer between it and the first (inside a launch, of the same item); or two `patch-implementer` rounds back to back in one workflow launch. Both routes skip work, so each runs only where something other than the agent taking it has checked that it applies. R11 accepts the same in-launch `check` |
| R25 owner-scope | a `tools/amend_check.py check` that printed `SCOPE:` (a plan change following a new owner decision, exempt from the replan cap and the tier ladder) with no message typed by the user since the previous `check`, or since the first planner started. The driver writes the decision line, so the audit checks the owner actually said something |
| R26 reread-after-write | an implementer or planner that reads a file it had already written (`Edit`/`Write`) whole more than twice — a `Read` with no `offset` or `limit`, or a bare `cat`/`type`/`Get-Content` of it — with no shell command naming the file in between (which may have rewritten it). After a write, read `git diff -- <file>`, a grep or the range instead (the owner, 2026-10-02) |
| R27 amendment-tier | an `amendment:` planner whose transcript's model (the majority model of its assistant records) is a `fable` model, or that ran as an escalated effort variant (`planner-xhigh`, `planner-max`; amendments spawn as `planner-medium`). An amendment applies one stated correction and always runs on opus, whatever tier the workorder's replans escalated to; the one fable amendment measured (forgepact-74, 2026-10-02) came from a driver carrying `planner-tier=fable` over. The evidence names the label and the model |

Every budget is a named module-level constant in the tool itself
(`IMPLEMENTER_MAX_TURNS`, `VERIFIER_MAX_TOKENS`, `BATCHABLE_SHARE_MAX`, and so
on), each with a comment naming the measurement it was set from — read those
constants for the current number rather than one copied here, since
re-measuring is exactly what this tool exists to make cheap. Since
2026-09-22 each sits at about the 90th percentile of what its role did over a
named set of real runs, so a `FAIL` means "this run is in the slowest tenth";
re-run `--calibrate` on newer sessions and move a constant when its
percentile has moved. Exit code is 0
when every rule passes, 1 when any rule fails, 2 on a usage error.

Tests (`tests/test_workorder_audit.py`) build synthetic transcripts in a temp
directory; every rule has both a failing fixture and a passing control, plus
coverage for message-id dedupe, workflow-subdirectory discovery, and the exit
codes. `parse_transcript` and `discover_session` take an optional cutoff
that skips every record after it; left out, the audit's output is unchanged.

### `tools/workorder_speed.py` — where the wall time went

The audit answers "did one session break a rule". This answers "where did
the time go", for one session or many, so a baseline and a later batch can
be compared with the same figures. It imports the audit's parser and
discovery, re-parses nothing itself, and opens files for reading only:

```
py -3 tools/workorder_speed.py [--transcript <driver .jsonl> ...] [--project-dir <dir> ...]
    [--plan <plan.md>] [--until <UTC>] [--json]
```

`--transcript` reads one driver transcript, its subagents and its launch
records (`<stem>/workflows/wf_*.json`); `--project-dir` reads every session
in a directory that has a subagent. `--until` ignores every record after a
UTC time, so a snapshot of a session that was still running can be
reproduced once it has finished. `--plan` adds how many `owner:` items the
plan has and how many carry `default:` and `reversible:`. Each session and
the aggregate carry the span, busy and serial minutes, concurrency, the
shares of busy time with one agent and with two or more, minutes per phase,
each launch's item windows (`max_concurrent`, `minutes_at_cap`,
`queued_behind_cap`, `finding_to_fix_minutes`), verifies by kind, the
`run_criteria` calls the Bash limit killed, owner waits, the implementers'
check catch rate, routes (amendments, in-launch amendments, replans,
consultations), the audit's lane summary, and `workorder_reads`. That last
one is keyed by role and counts how each role read the workorder's own
files: `agents`, `plan_calls`/`plan_kb` (a `Read` of a `-plan.md`, or a
shell command naming one, except a command that runs `run_criteria.py`,
`plan_lint.py`, `amend_check.py`, `live_checks.py`, `item_commit.py` or
`workorder_brief.py`, or `git add`/`git commit`), `context_calls`/
`context_kb` (the same for `-context.md`), `brief_calls`/`brief_kb` (shell
calls of `workorder_brief.py`) and `report_calls`/`report_kb` (a `Read`,
`cat`, `type` or `Get-Content` of a `report.txt`); the text format prints
the implementer's and the verifier's rows. It is what shows whether the
brief and the digest moved reading off the whole files
(`docs/agents/workorder-calibration.md`, 2026-10-03). The module docstring
defines each figure. Exit 0 when the report was produced, 2 on a usage error.
`docs/agents/workorder-calibration.md` § "Measuring where the pipeline spends
its time" holds the 2026-09-27 baseline and the exact commands to re-run it.
Tests: `tests/test_workorder_speed.py`, synthetic sessions only, each measure
with a counting case and a control.

### `tools/live_checks.py` and `tools/plan_lint.py` — criteria that read, not guess

Both read a file and run nothing. `live_checks.py <capture> --expect <names>
[--require-pass <names>]` reads a live capture's `## Checks` block: the
verdict is the first word after a line's last `|`, anything after it a note.
It exits 1 on a missing, renamed, duplicated or unreadable check, or a
`--require-pass` check (`dll-hash`, `marker`, `control`, a shipped feature's
acceptance checks) that did not pass; a research check's `fail`,
`not-observed` or `not-run (instrument: …)` is a finding and exits 0. A
capture with no list but a `| Check | Result |` table under `## Checks
summary` (forgepact-issue-36 Live 1 wrote one, and a capture is never edited)
is read from the table by the same rules; the list wins when both exist. It replaces the
`| (pass|fail|not-observed)$` greps that cost forgepact-issue-14 three rounds
and a split workorder on the operator's punctuation. `plan_lint.py <plan>`
checks `## Acceptance criteria` for four defects that each cost a round there
(forgepact-issue-14):
a prose criterion, a heading slice not anchored on `\n`, a grep over a live
capture, and `python` where the repository runs `py -3`. A fifth,
`pinned-sha`, came from the ForgePact UI redesign: a bare commit hash in a
backticked span, where a per-workorder tag or a merge-base expression belongs
because the head it was copied from moves. Three more came from the
redesign's review (2026-09-27): `eof-slice`, an `.index` of "the next
heading" that raises once its section is the file's last; `merge-walk`, a
`git log`/`rev-list` range without `--first-parent` in a plan that merges
main (a criterion that means every parent writes `(all-parents)`); and
`plan-draft`, a plan still `status: DRAFT` because it waits on another
workorder's result, named with its status from its `depends on:` line. The
planner runs it
before `PLAN-READY`; the driver runs it again before spawning an implementer.
It also reads a plan's lanes (`### Lane: <name>` headings under `## Steps`,
each with a `files:` line, plus one `### Join`) and reports five lane
findings, each exiting 1: `lane-overlap` (two lanes share a literal path, a
literal matches another lane's glob, two globs are identical, or one glob's
fixed prefix is a prefix of another's, checked over every pair of lanes),
`lane-no-files`, `lane-no-join`, `lane-dup-name` and `lane-bad-name`.
`plan_lint.py <plan> --lanes-json` prints, only when the lint is clean, one
JSON line `{"lanes": [{"name", "files"}, ...], "join": true|false}`, which
the driver pastes into the workflow's `lanes`/`join` args, so lanes the lint
rejected cannot be launched. A plan without lanes prints `{"lanes": [],
"join": false}`.
Two plan-level findings, each exiting 1, hold a plan to AGENTS.md § "Check
for a Named Ghidra Project": a plan that researches a game mechanism records
its Ghidra MCP check on one `## State` line, `ghidra mcp: used — <what it
answered>`, `ghidra mcp: unavailable — <what status printed>; offered setup`
or `ghidra mcp: skipped — <reason>`. A plan counts as mechanism research when
it or its `-context.md` has a `### Live procedure` heading, a backticked
`route tokens:` State value, the text `analyzeHeadless`, `DecompileTo`,
`decomp_index.py has` or `mcp__ghidra__`, or a
`ForgePact/docs/<name>-research.md` path. `ghidra-unchecked` fires when such a
plan has no `ghidra mcp:` line, and its excerpt names the trigger;
`ghidra-bad-value` fires, trigger or not, on a value other than those three
words, or `skipped` with no reason. The trigger is broad on purpose: a plan
that only mentions these tools clears it with one `skipped — <reason>` line.
`run_criteria.py <plan>` is the verifier's first call. It runs every
command-shaped criterion (a backticked span starting with `py`, `git`, `grep`,
`node`, `cd` and the like) exactly as written, in bash from the checkout
root, once per distinct command. It skips a criterion whose gate `gates:`
does not carry, and carries a criterion's opening `cd <dir>;` to its later
spans. It prints each exit code with the output's tail, keeps full logs as
`cmd-<n>.log`, and judges nothing. With `--jobs N|auto` it runs independent
commands at the same time by resource class (builds first and alone; at most
one whole suite and `--browser-jobs` browser suites, default 2; file checks
and targeted tests up to N; a timing benchmark and any unrecognised command
as a barrier at its place in the plan), declared per criterion as `(class
<c>)` and `(after <k>)` or recognised from the command, and still prints in
plan order with the serial run's log numbers. `--item <id>` runs one item's
`checks:` instead of the acceptance criteria. Without `--jobs` it runs
serially, as it always has. Each command's timeout is `--timeout` when
given, else 1800 s for a `suite` or `exclusive` command and 900 s for the
rest. `--changed-since <ref>` (plus `DIR=<ref>` per
submodule, or `--changed-from <file>`) and `--failed <k,...>` run only the
criteria a fix can reach: each whose `(reads `<glob>`)` a changed path
matches, the failed ones, and any criterion with no map. It prints what it
selected and skipped and why, and falls back to every criterion when the
delta is unknown or a shared contract changed (SKILL.md Step 4, "Re-verify
what the fix reaches"). `plan_lint.py` warns, without failing, `no-reads` on
a criterion with no map and `reads-nothing` on a glob that matches no tracked
file.
Every run that is not `--list` keeps `<out>/status.json` current (started and
updated times, `finished`, and each criterion's state with each command's
exit code and seconds, replaced whole through a temporary file) and writes
what it prints to `<out>/report.txt`. `run_criteria.py --status <out> [--wait
S]` reads it and exits 0 when the run finished, 3 while it runs, 4 when it is
stale (not finished and not updated for 1,900 s) and 2 without a status
file or for a run that refused before running anything. A new run clears an
earlier run's `status.json` and `report.txt` from its `--out` before it can
refuse, so a poll never reads the earlier one as this one; `--wait` polls for at most S ≤ 220 seconds, so a poll stays under audit
R5. That is how the whole-tree verifiers run in the background: start the
run with `run_in_background` and `--out`, poll `--status`, then judge from
`run_criteria.py --digest <out>`.
`run_criteria.py --digest <out>` needs no plan: the run records in its out
directory what the digest needs, each criterion's full text included. It
exits as `--status` would for the same run (0 finished, 3 running with the
status lines printed, 4 stale, 2 for no status file, a refused run or a usage
error). On a finished run it prints a header (criteria, how many shown in
full, `report.txt`'s KB), the scope block when the run was scoped, and per
criterion either one line or the whole block exactly as `report.txt` has
it. One line is for a SKIPPED or NOT SELECTED criterion, and for an
exit-only criterion (its prose says nothing but `exits <n>` once the
backticked spans and the `(reads ...)`, `(final)`, `(gate ...)`, `(class
...)`, `(after ...)` and `(all-parents)` declarations are removed) whose
every command exited as expected. It judges nothing, and `report.txt` keeps
its bytes. Verifiers read `report.txt` whole after 2026-10-02, 100-217 KB a
run, which is why it exists.
Owner questions carry a default: an item's `owner:` line needs `default:`
and `reversible: yes|no` beside it, and so does each entry of `## Needs
human judgement`, read in the plan and in its sibling `<slug>-context.md`.
`plan_lint.py` reports `owner-no-default`, `owner-no-reversible`,
`owner-reversible-no-default` (`reversible: yes` with no default, or
`none`) and `owner-legal-default` (a legal or decompile-output question
marked reversible or given a default), each exiting 1, and `--items-json`
carries each item's `default` and `reversible`.
`plan_lint.py` also reads a plan's items (`### Item: <id>` under `## Steps`,
each with `files:`, `checks:` and optional `after:`/`shares:`/`owner:`) and
reports `item-overlap` (an overlap neither item declares), `item-no-files`,
`item-no-checks`, `item-dup-id`, `item-bad-id`, `item-unknown-ref`,
`item-cycle` and `items-and-lanes`. `--items-json` prints the item table and
whether planning is complete, and `--known a,b --wait S` waits for the next
item a streaming planner releases. `item_commit.py --message <m> -- <paths>`
commits one item's paths, per repository, under the checkout's commit lock;
`workorder_lock.py <name> -- <cmd>` is that lock (an OS file lock the system
drops when its holder exits) for anything else that must not run twice at
once. `amend_check.py save|check|restore <plan> [<context>]` decides whether a plan
change was an amendment, the owner's own scope, or a replan (SKILL.md
Step 2 and Step 4, "Owner scope is not a failure"). It prints `SCOPE:` when a
change that would otherwise be a replan follows an `owner, <date>:` decision
line the context gained since `save`. That exempts the change from the
replan cap and the tier ladder, and audit R25 checks the owner did say
something. A change small enough to be an amendment anyway prints
`AMENDMENT`. `restore` copies the saved files back, which the workflow
launch does after any amendment it did not confirm.
Tests: `tests/test_workorder_plan_tools.py`.

### `tools/source_index.py` — go to the range, don't grep around

Generic, stdlib-only, read-only index for one large C/C++ file, built against
the banner-comment and `#ifndef <guard>` research-span style
`ForgePact/plugin/ModuleMain.cpp` already uses:

```
py -3 tools/source_index.py <file> [--regions] [--functions]
                                    [--find NAME] [--at LINE]
                                    [--guard MACRO] [--json]
```

`--regions` (the default) prints one line per banner-delimited region —
`start-end  KB  [R]  title`; `[R]` marks a region that sits inside an
`#ifndef FORGEPACT_RELEASE` (or `--guard`-named) span, at any nesting depth.
`--functions` finds file-scope function definitions with a brace-matching
heuristic (its own docstring lists what it misses: templates, a body on the
signature line, anything not at brace depth 0). `--find NAME` returns every
region and function whose name contains `NAME`, with ranges, so the next call
is a `Read` with `offset`/`limit` instead of another grep chain. `--at LINE`
returns the region and function containing a line. It only ever prints
identifiers and banner titles from the file it is given, never the file's own
text.

Measured against the file it was built for (`ForgePact/plugin/ModuleMain.cpp`,
997KB / 18,144 lines then): `--regions` prints 94 regions in about 6KB.

**`section.py`'s code mode is built on it.** `section.py <file> --toc
[--grep REGEX]` and `section.py <file> '<symbol>' [--grep REGEX]` take a
`.cpp .cc .c .hpp .h .py .js .mjs .ts` file; every other file keeps the
markdown behaviour. `source_index.py` gained a symbol index behind it (its
existing modes print what they always did): C/C++ functions at file scope
and inside `namespace` blocks at any depth, out-of-line `Class::Method`
definitions, and `struct`/`class`/`enum` definitions with their inline
methods, read with the same comment stripping and guard spans; Python's
top-level `def`/`async def`/`class` and their methods through `ast`; and
JS/TS functions, classes, `export` forms, `const|let|var NAME =`
definitions and class methods, through a lexer that knows strings, template
literals with nested `${}`, comments and regex literals. `--toc` prints
`<start>-<end>  <KB>KB  <kind> <name>` per symbol in file order; past 20 KB
it prints the symbol count, the banner regions and a line saying to narrow
it with `--grep`. A symbol prints `-- <path> lines <start>-<end> (<kind>
<qualified name>)` and then its lines exactly as in the file, decorators
included. It matches the exact name, then the qualified name, then the name
case-insensitively; exit 3 lists up to 20 near names, 4 lists every match of
an ambiguous one, and with `--grep` it prints the body's matching lines with
two lines of context and exits 7 when none match. A 2.5 MB generated C++
file is indexed and looked up in under 10 seconds.

`implementer.md` and `planner.md` send their agents here: for a source file
over about 200 KB, `section.py <file> --toc --grep <regex>`, then
`section.py <file> '<symbol>'`, one call per symbol, never `grep -n`
followed by `sed -n`. In the 18 sessions after 2026-10-02 ModuleMain.cpp
took 422 implementer and 168 planner shell reads that way, two turns per
lookup (`docs/agents/workorder-calibration.md`, 2026-10-03).
`source_index.py --regions` stays the banner map. Tests:
`tests/test_section_code_mode.py`, one fixture per language with its
outliers, the size test and the toc cap.

Tests (`tests/test_source_index.py`) cover a synthetic fixture (banners,
nested guard spans, a function inside and outside a guard, `--find`, `--at`)
plus a smoke test against the real `ModuleMain.cpp`, skipped when the file is
absent — as it is in a worktree with the ForgePact submodule uninitialized.

## Plugins — `settings.json`

`settings.json` registers three marketplaces (`extraKnownMarketplaces`) and
enables one plugin from each (`enabledPlugins`). Claude Code offers to install
them when a contributor trusts the repository.

| Plugin | Source | For |
|---|---|---|
| `impeccable` | `pbakaus/impeccable` | frontend design: `/impeccable audit`, `critique`, `polish` and the rest, plus a design-detector hook |
| `taste-skill` | `Leonxlnx/taste-skill` | design-direction skills (minimalist, brutalist, redesign and more) |
| `claude-code-setup` | `anthropics/claude-plugins-official` | recommending Claude Code automations for this codebase |

`impeccable` ships its own hooks, which run alongside `post_tool_use.py` above
and do not replace it. A `PostToolUse` hook scans each edited UI file
(`.tsx .jsx .html .vue .svelte .astro .css .scss .sass .less .ts .js`), and a
`Stop` hook makes one deeper pass over the files touched in the session. Both
only report findings; neither blocks an edit. The first run downloads a signed
engine binary from the project's GitHub releases and checks its SHA-256.
Telemetry is one anonymous ping during a design-direction round and nothing
else. `DO_NOT_TRACK=1` turns it off, `IMPECCABLE_NO_UPDATE_CHECK=1` turns off
the update check, and `IMPECCABLE_HOOK_DISABLED=1` turns off the hook for one
contributor. `/impeccable hooks off` turns it off for everyone, because it writes
the shared `.impeccable/config.json`.

For Codex, which has no plugin marketplace for these, install the two design
plugins per user, never into this project, so their files do not land in
`.agents/skills/` or overwrite `.codex/hooks.json`:

```bash
npx impeccable install --providers=codex --scope=global
npx skills add https://github.com/Leonxlnx/taste-skill -g -a codex
```

impeccable's Codex design-detector hook is project-local by its own design, so
under Codex it does not run here; run `/impeccable audit` (Codex: `$impeccable
audit`) on the changed UI instead. `.impeccable/config.json` is shared by both.

## MCP servers — `../.mcp.json`

| Server | For |
|---|---|
| `tauri-hub` | driving a running debug hub through its bridge on `127.0.0.1:9223` |
| `hs-drive` | reporting whether Hero Siege is running, backing up / restoring `hs2saves\`, and driving the modded game (launch, `bp_ipc` command + reply, screenshot, keyboard/mouse injection, selecting a character from the title screen with `hs_select_character`, graceful close), under one machine-wide game lease (`hs_lease_acquire` / `hs_lease_status` / `hs_lease_release`) that stops a second session driving the same install — a local stdio server in `tools/hs_drive_mcp/` |
| `ghidra` | the local Ghidra project as tools (search functions, decompile by address, callers, callees, xrefs, strings), from [bethington/ghidra-mcp](https://github.com/bethington/ghidra-mcp) v6.0.0 pinned by sha256: one shared headless server on `127.0.0.1:8089` over a *copy* of the research project, plus a stdio bridge per session, started by `tools/ghidra_mcp.py` |
| `x64dbg` | a live debugger on the running game, for `live-operator` only: headless x64dbg with the [AgentSmithers/x64DbgMCPServer](https://github.com/AgentSmithers/x64DbgMCPServer) plugin, both pinned, attached under the hs-drive lease, and eight tools of our own (non-breaking hardware logging breakpoints, `bplist`, the session log, modules, disassembly, detach) served over stdio by `tools/x64dbg_mcp.py`, which forwards to the plugin on `127.0.0.1:50300` — see [`docs/tools/x64dbg-mcp.md`](../docs/tools/x64dbg-mcp.md) |
| `context7` | live library documentation; `AGENTS.md` § "YYToolkit Integration" already assumes it |
| `github` | releases, dispatches and pointer PRs across the eleven repositories |
| `figma` | reading Figma designs (layout, styles, images) into code — [`figma-developer-mcp`](https://github.com/GLips/Figma-Context-MCP) (MIT), run locally and pinned, authenticated by the `FIGMA_API_KEY` personal access token |
| `playwright` | driving a browser — the web submodules (`HSCraftSim`, `HS-Offline-Tracker`'s frontend) the way `tauri-hub` drives the hub; pinned to `@playwright/mcp@0.0.82`, run headless on Microsoft Edge (`--browser msedge --headless`) because Edge ships with Windows and the server's default, Chrome, is often not installed, and with `--isolated` (an in-memory profile per server) because concurrent sessions in `.claude/worktrees/` otherwise collide on one shared profile with "Browser is already in use" |

`tauri-hub` is pinned to `@hypothesi/tauri-mcp-server@0.13.0` to match
`tauri-plugin-mcp-bridge = "0.13"` in `hub/src-tauri/Cargo.toml`. Keep those two
in step: some tools (the desktop `manage_window` actions) return a version error
against an older plugin.

The bridge only exists in a **debug** build with the `mcp-bridge` feature — an
optional dependency registered under
`#[cfg(all(debug_assertions, feature = "mcp-bridge"))]`, because it can invoke
any command in the application. A bare `cargo run` or `tauri dev` does not start
it. Start the hub with `npm start` in `hub/` (which passes `--features mcp-bridge`) and wait for `:9223` before expecting
`tauri-hub` to connect. `AGENTS.md` § "Drive a Tauri App Yourself Instead of
Asking Someone to Click It" has the rest, including the window label (`hub`, not
the `main` every tool defaults to).

`hs-drive` is the one entry that is not an installed package: it starts
`py -3 -m tools.hs_drive_mcp` from this repository, so it needs
`py -3 -m pip install -r tools/hs_drive_mcp/requirements.txt` once, and it
assumes Claude Code starts a project-scoped stdio server with the project root
as its working directory. Its save tools refuse — with a named reason — unless
the game is provably not running, and nothing in it ever deletes a file.
The tools that drive or overwrite the game refuse `lease_held` while another
session holds its machine-wide lease; the `live-operator` takes it with
`hs_lease_acquire` before its first check and gives it back with
`hs_lease_release` after the stop, and the `/workorder` driver reads
`hs_lease_status` before asking to install anything.
[`docs/tools/hs-drive-mcp.md`](../docs/tools/hs-drive-mcp.md) has the tool
surface, the refusal vocabulary and the sharp edges, including why the server's
process must keep the real `LOCALAPPDATA`.

`ghidra` is the other local entry, `py -3 -m tools.ghidra_mcp`. It needs
Ghidra, a JDK 21 and the research project, plus `py -3 -m tools.ghidra_mcp
setup` once per machine, which downloads the pinned release (ask the owner
first). The first session to use it starts a shared headless server, and later
sessions, worktrees and Codex reuse it, because a Ghidra project allows one
lock. It binds to loopback, has script execution off, and serves a copy of the
project, so `DecompileTo.java` runs on the original keep working. What it
decompiles stays out of tracked files (AGENTS.md § "Legal"). Under Codex, whose
MCP startup timeout is 10 s, run `py -3 -m tools.ghidra_mcp start` first if
the server is cold.
[`docs/tools/ghidra-mcp.md`](../docs/tools/ghidra-mcp.md) explains why this
server and not pyghidra-mcp, and covers the overrides and the sharp edges.
Which agents may call which of its tools is in § "Agents" above.

`x64dbg` is the third local entry, `py -3 -m tools.x64dbg_mcp`, a stdio proxy
that is connected from session start and answers "not attached" until a
debugger session exists. It needs `py -3 -m tools.x64dbg_mcp setup` once per
machine, which downloads the pinned x64dbg snapshot, clones the plugin at its
pinned commit, applies our two edits (loopback bind, braces in log lines) and
builds it with MSBuild and a .NET 8 SDK (ask the owner first). Everything it
installs stays under `%USERPROFILE%\tools\`, outside any checkout. Attach and
teardown run through a detached keeper (`attach --game`, `detach`), under the
hs-drive lease, and the game is detached **before** `hs_stop_game`. It is not
an HTTP entry pointing at the plugin's own server, because that server exists
only after the attach and exposes the plugin's whole surface (`StopDebug`,
memory writes, stepping) to every session; our eight tools are the boundary in
code. What x64dbg disassembles stays in the live capture (AGENTS.md § "Legal").
[`docs/tools/x64dbg-mcp.md`](../docs/tools/x64dbg-mcp.md) has the pins, the
breakpoint rules and the license position.

`github` does **not** authenticate interactively. Claude Code tries OAuth
dynamic client registration, that endpoint does not support it, and the session
reports *"Incompatible auth server: does not support dynamic client
registration"*. Probing directly confirms what it wants: a POST with a bearer
token returns 200, without one 401. So `.mcp.json` sends
`Bearer ${GITHUB_MCP_PAT}`, expanded from the environment — no token in the
repository.

### Tokens: `tools/setup_agent_secrets.py`, once per machine

`github` and `figma` read a personal access token from an environment variable
(`GITHUB_MCP_PAT`, `FIGMA_API_KEY`), so no token is in the repository and both
Claude Code and Codex read the same one. On a new machine run:

```bash
py -3 tools/setup_agent_secrets.py
```

On Windows it asks, with input hidden, for each token not saved yet and saves
it as a persistent user variable in `HKCU\Environment`. A value set only in
the current shell does not count, because newly started programs will not see
it; Enter saves it. `--list` shows `set`, `SESSION` or `MISSING`, and `--force`
asks again. Pressing Enter at the GitHub prompt uses `gh auth token` instead.
On macOS and Linux it saves nothing and asks for nothing: it prints the
`export` line for each missing token, to add to your shell profile. Keeping the
tokens between machines is up to you; a test fails if a server in `.mcp.json`
reads a variable the script does not ask for.

`figma` is a local server rather than Figma's official one because
`mcp.figma.com` accepts only an OAuth login, per program and per machine,
never a token. It reads designs and cannot edit them; Claude sessions that
also have Figma's claude.ai connector can use that for writing.

**Claude Code and Codex must be restarted afterwards.** A process reads its environment at
launch, so the session that sets the variable is never the session that can use
it.

Three things worth knowing about that arrangement:

- **It is a copy, and copies go stale.** That is the `gh` CLI's own OAuth token.
  `gh auth refresh`, `gh auth logout` or a re-login rotates it, and this copy
  then 401s while `gh` itself keeps working — so the symptom is "the MCP server
  broke for no reason". Re-run `tools/setup_agent_secrets.py --force` to resync.
- **It is plaintext at rest**, in the user's registry environment, readable by
  anything running as that user. `gh` keeps its own copy in the OS keyring, so
  this is a deliberate downgrade accepted for convenience.
- **It is broadly scoped**: gist, read:org, repo and workflow across *every*
  repository the account can reach, not just this one. A fine-grained PAT
  restricted to the `falorfrozen-cmd` repos narrows the blast radius
  considerably and drops into the same variable.

Until a variable is set its entry simply fails to connect, which is harmless —
the `gh` CLI covers the same ground and keeps its token in the keyring.

## Codex — `../.codex/` and `../.agents/`

The same rules and tooling reach Codex. `AGENTS.md` is the rule file for both
agents (Claude Code reads it through `CLAUDE.md`'s import).

| Claude Code | Codex | How the two stay in step |
|---|---|---|
| `.claude/skills/` | `.agents/skills/` (the source) | `tools/sync_agent_tooling.py` mirrors it |
| `.claude/agents/*.md` (the source) | `.codex/agents/*.toml` | generated by the same tool |
| `.mcp.json` (the source) | `.codex/config.toml` `[mcp_servers.*]` | generated by the same tool |
| `settings.json` `PostToolUse` | `.codex/hooks.json` `PostToolUse` | both run `hooks/post_tool_use.py`; a test pins it |

Run `py -3 tools/sync_agent_tooling.py` after editing any source; `--check`
only reports. Codex loads `.codex/` only once you trust the project, and asks
you to approve `.codex/hooks.json` in `/hooks` (again whenever it changes).
Start Codex at the repository root: the hook command is a relative path.

The generated agents keep each Claude agent's instructions verbatim, with a
preamble translating tool names. A Claude agent without write tools becomes
`sandbox_mode = "read-only"`. Its `effort:` becomes `model_reasoning_effort`
(`max` becomes `xhigh`); a Haiku-tier agent that pins no `effort:` falls
back to `low` (`TIER_DEFAULT_EFFORT` in `tools/sync_agent_tooling.py`),
though every Haiku agent now pins one. Effort
variants get a Codex twin like any other agent, so `planner-max` and
`planner-xhigh` are the same there. The Claude
model tier is not translated: Codex has no fixed model per tier, so the agent
inherits the session's model, and the tier is recorded in a comment.

What does not carry over:

- **`/workorder` and `workorder-rounds`** drive Claude Code's `Agent` and
  `Workflow` tools and their scripts are called by `.claude/skills/workorder/`
  path, so they stay Claude-only. Under Codex, run the phases by hand with the
  generated `planner`, `implementer` and `verifier` agents.
- **The `ai-review` CI job** runs Claude Code in GitHub Actions whichever agent
  opened the pull request; the label works the same for both.
- **The `tools:` allowlist, and with it the `mcp__ghidra__*` read set.**
  `tools/sync_agent_tooling.py` reads an agent's `tools:` line only to decide
  `sandbox_mode`, so every Codex agent sees every server in
  `.codex/config.toml` with all its tools, the `ghidra` server's writes and
  `debugger_*` included. A server-wide `disabled_tools` would strip the
  owner's own Codex session too, so the restriction there is the ban written
  in the agent bodies, which reach `.codex/agents/*.toml` verbatim. The
  `x64dbg` server is narrower by construction: its stdio proxy serves only its
  eight tools, so under Codex every agent sees those eight, and the plugin's
  own surface stays out of reach.

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

Twenty-nine suites cover this page's tooling. Twenty-eight are Python and run
automatically under the first command below; the workflow script's own routing is
JavaScript and runs separately, under Node:

```bash
py -3 -m unittest discover -s tests
py -3 -m unittest tests.test_claude_hooks -v      # the hooks actually block
py -3 -m unittest tests.test_claude_agents -v     # the definitions are well-formed
py -3 -m unittest tests.test_agent_tooling_sync -v  # the Codex copies (.agents/, .codex/) match their sources
py -3 -m unittest tests.test_claude_workorder -v  # round_delta.py + ensure_submodule.py, one round/submodule at a time
py -3 -m unittest tests.test_claude_workorder_section -v  # section.py, plus the sentences in agents/ and SKILL.md that carry the same lesson
py -3 -m unittest tests.test_workorder_audit -v   # workorder_audit.py's rules, each with a failing fixture and a passing control
py -3 -m unittest tests.test_workorder_plan_tools -v  # live_checks.py, plan_lint.py, amend_check.py and run_criteria.py, on the capture, criterion and plan-diff shapes that cost rounds
py -3 -m unittest tests.test_workorder_plan_lint_owner -v  # plan_lint.py's owner-question rules, each with a failing fixture and a passing control
py -3 -m unittest tests.test_workorder_run_criteria_status -v  # run_criteria.py's status.json, report.txt, --status exit codes and --digest
py -3 -m unittest tests.test_workorder_speed -v   # workorder_speed.py's measures on synthetic sessions, each with a control
py -3 -m unittest tests.test_source_index -v      # source_index.py against a synthetic fixture, plus a real-ModuleMain.cpp smoke test
py -3 -m unittest tests.test_section_code_mode -v  # section.py's code mode: one fixture per language with its outliers, the 2.5 MB size test, the toc cap
py -3 -m unittest tests.test_workorder_brief -v   # workorder_brief.py's selectors, each with a control that it prints nothing it was not asked for
py -3 -m unittest tests.test_hs_drive_mcp_server -v            # the hs-drive tool surface, over a real stdio session
py -3 -m unittest tests.test_hs_drive_mcp_engine_bridge -v     # ENGINE_SYMBOLS still resolve, and importing the engine starts nothing
py -3 -m unittest tests.test_hs_drive_mcp_saves -v             # the fail-closed save backup/restore contract
py -3 -m unittest tests.test_hs_drive_mcp_launch -v            # launch through ForgePact's engine, readiness, WM_CLOSE vs TerminateProcess
py -3 -m unittest tests.test_hs_drive_mcp_ipc -v               # the bp_ipc command channel, against a fake consumer
py -3 -m unittest tests.test_hs_drive_mcp_screenshot -v        # window resolution, both capture methods, the flat-image warning
py -3 -m unittest tests.test_hs_drive_mcp_input -v             # what hs_input actually injects, and the foreground it refuses without
py -3 -m unittest tests.test_hs_drive_mcp_charselect -v        # hs_select_character's click sequence, its proof and every refusal
py -3 -m unittest tests.test_hs_drive_mcp_layout -v            # parsing ForgePact's menulayout listing, and the refusals it decides
py -3 -m unittest tests.test_hs_drive_mcp_lease -v             # the machine-wide game lease, across real processes
py -3 -m unittest tests.test_hs_drive_mcp_release_boundary -v  # no release input mentions hs-drive
py -3 -m unittest tests.test_ghidra_mcp -v                     # the ghidra launcher: git refusal, loopback, stripped env, version check
py -3 -m unittest tests.test_ghidra_agent_tools -v              # the phase agents' mcp__ghidra__* tools match AGENT_READ_TOOLS; no write or debugger tool
py -3 -m unittest tests.test_x64dbg_mcp -v                     # the x64dbg launcher: git refusal, loopback, the two edits, build argv, lease, keeper, teardown, allowlist
py -3 -m unittest tests.test_x64dbg_agent_tools -v              # live-operator alone carries mcp__x64dbg__*, exactly LIVE_OPERATOR_TOOLS
node --test .claude/workflows/workorder-rounds.test.mjs   # workflow mode's routing
```

The eleven `test_hs_drive_mcp_*` suites stay green on CI's `ubuntu-latest`
runner, where neither Windows, the SDK, nor any submodule is present — but only the parts that need one skip.
The engine-bridge, launch and screenshot suites skip wholesale (launching a
process, enumerating windows and grabbing the screen are Windows-only); the
server suite skips its stdio and `hs_status` classes but still runs
`SelfCheckSummaryTests`, which drives `run_checks` over a stub registry and so
needs nothing; the release-boundary suite skips only its submodule check; and
the lease suite skips only its two-stdio-server test; and the saves, IPC,
input, charselect and layout suites run in full, against fixtures and fakes (the input suite's Win32 calls all go through
one patched table, charselect patches `hs_input.inject` and `ipc.send`, and
layout is pure parsing) — the IPC one because
its gate is injected and its whole channel is two files in a temporary
directory, which is deliberate: it covers the rules most likely to be broken by
an edit somewhere else. Each skip names its reason.

The two `test_x64dbg_*` suites run on fixtures and fakes too: a stand-in
plugin on `127.0.0.1`, a fake headless, and a guard that fails any non-loopback
fetch or unexpected subprocess. On CI, which has neither `mcp` nor Windows,
only the stdio round trip skips, naming why; the one test that checks how the
keeper is detached asserts the Windows creation flags or the POSIX
`start_new_session`, whichever platform it runs on.

**`.claude/workflows/*.js` and `*.mjs` must stay LF.** `.gitattributes` forces
`text eol=lf` on both globs: the Workflow tool's permission handler refuses to
schedule a script containing any CR byte at all — "script contains control
characters that would be hidden in the approval dialog" — so a CRLF
`workorder-rounds.js` could never be launched, independent of whether its
content was otherwise correct, which is almost certainly why workflow mode had
never carried a workorder end to end before 2026-09-17. That is the opposite
of the rest of this repository, which is CRLF by convention; check with `file`
after editing either script rather than assuming the checkout's usual
`core.autocrlf` behavior carried over.

`test_claude_agents.py` enforces the two rules on this page that a machine can
check: every agent pins `model:` to a known tier alias, and no frontmatter
carries an unquoted ` #` that would silently truncate the value. Both are
invisible in a diff and neither had a check before. It self-tests its own
parser, for the same reason everything else here does.

`test_claude_workorder.py` drives `round_delta.py` and `ensure_submodule.py`
as the subprocesses the driver and the workflow script actually invoke, not by
importing their functions — the same discipline `test_claude_hooks.py` uses
for the hooks. Its submodule fixtures prove a linked worktree gets its own
gitdir and that a commit made there stays invisible to the main checkout's
copy until fetched across by hand, and that the prerequisites manifest copies
exactly what it lists — once, never overwriting an existing path, never
touching one the manifest doesn't name — and stays a no-op run from the main
checkout itself.

Every test there is a **pair**: a positive control proving the hook fires on a
real violation, and a negative control proving it stays quiet on a clean tree.
A suite with only the negative half passes against hooks that do nothing, which
is exactly the failure this project keeps rediscovering — see `AGENTS.md`
§ "Prove the Instrument Before Trusting a Negative Result". If you add a check,
add both halves.

The rig builds a throwaway git repository in the system temp directory rather
than the session scratchpad, where `git init` fails with `Filename too long`.
