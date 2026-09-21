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
| `implementer` | sonnet | executes the steps; returns `PLAN-DEFECT` with evidence rather than improvising around a plan that turns out to be wrong |
| `verifier` | haiku | runs the acceptance criteria and reports what they actually printed; read-only, and judges nothing it cannot execute |
| `consultant` | opus | answers **one** narrow question from a phase that hit a decision above its tier, then stops; never implements, plans or reviews |
| `scribe` | haiku | pastes a precomputed round Log entry and replacement State lines into the workorder's own `-plan.md`/`-context.md`, with `Read`/`Edit` only; spawned only by `workorder-rounds.js`, and records the round's findings rather than acting on them |

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
hardest rows), then re-enters the phase with the answer appended to the
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
others have 1M. It is comfortable for acceptance criteria plus the one context
section a criterion cites, which is all the verifier opens, and that is part of
why the verifier's job is scoped
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
and **3 implement→verify rounds**, then it stops and asks a human.

A workorder is two files: `.claude/workorders/<slug>-plan.md` (frontmatter,
`## State`, `## Goal`, `## Out of scope`, `## Acceptance criteria`,
`## Steps` — what everyone who touches the workorder reads) and
`<slug>-context.md` (`## Context the implementer needs` by stable `###`
subsection, `## Needs human judgement`, `## Log` — read by section, only when
a step or a reviewer is pointed at it). `## State` carries `round:`, `phase:`,
`gates:` (the tokens a conditional criterion or step names, instead of
"while the Log lacks X"), `round base:` (the `round_delta.py` snapshot for
this round), `agents:` (each phase's agent id, for the resume mechanism
above), `reviewers:`, `open defects:` and `decisions in force:`. The nine plans written before this
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
passes `--log`. That same run's verifier had no context path in its dispatch
and no command for a `###` heading; it spent eight calls looking and then read
the whole file (audit R2, which now also catches a `cat`/`sed`/`Get-Content`
of a context file, since `Read` is not the only way in). The workflow now
passes the path and the command — the plan's own path for a legacy single-file
plan.

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

It runs as the restricted `scribe` agent type (`.claude/agents/scribe.md`,
`Read`/`Edit` only), not the unrestricted `workflow-subagent` every other
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
                   submodules: ['<dir>', ...], researchHeadings, baseHeads, priorFindings } })
```

`reviewers` is a map, one entry per applicable round-0 reviewer, valued
`'never'`. `submodules` names the dirs whose own diff the reviewers must
read, relative to `repoRoot`. `researchHeadings` names the context file's
`###` heading(s) `instrument-blindness-reviewer` should read. `baseHeads` is
`{ '.': sha, '<submodule>': sha, ... }`, copied from `## State` ›
`round base:`. `priorFindings` is `{ '<reviewer>': [{ where, problem }] }` for
a reviewer entering as `blocking`, copied by the driver on a fresh launch from
the most recent `### Round <n>` Log entry that carries a `BLOCKING (k)` list;
between rounds of one launch the script carries it itself. A
re-run reviewer that was blocking is handed its own finding and asked whether
the delta resolves it, every re-run is told earlier rounds reviewed the rest,
and every reviewer is told the Out-of-scope list is not a checklist — a
`docs-sync-reviewer` given none of the three ran 40 turns twice, once policing
scope the verifier already checks and once re-deriving a one-file delta's
history. `repoRoot` is still accepted and nothing passes it; see "A workorder
cannot be run against another checkout" above.

It returns to the driver on anything needing judgement — `PASS`,
`PASS-PENDING-HUMAN`, `PLAN-DEFECT`, `ADVICE-NEEDED`, `AGENT-FAILED` or `CAP`
— so replans, consultations, human questions and the step-5 report stay with
the driver either way, and one launch may cover several rounds (a
`PLAN-DEFECT` hand-back means relaunching after the replan). What it still
trades away: every re-entry inside the script is a fresh spawn, never the
`SendMessage` resume above, because the script has no agent id to send to —
measured, on this one real run, as no worse than a resumed implementer (a
resumed round-1 implementer cost 14.6M tokens at 304K context per turn;
losing the resume cost nothing). `.claude/workflows/workorder-rounds.test.mjs`
(`node --test`, 36 cases, each with its own control) dry-runs the routing
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
py -3 tools/workorder_audit.py [--latest | --session <id-prefix>]
    [--projects-dir DIR] [--project NAME] [--json]
```

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
and KB of `Read` results by kind (plan, context file, `instructions.md`,
source). It prints one table, then sixteen rules as `PASS`/`FAIL` with
evidence (the agent, the time, the command or path), then each role's numbers
against the pre-update averages as a percentage; `--json` emits the same as
one object.

| Rule | Checks |
|---|---|
| R1 reviewer-reads-workorder | a reviewer `Read`/grep of a `-plan.md` (`instrument-blindness-reviewer` may read a `-context.md`) |
| R2 verifier-scope | a verifier whole-file `Read` of a `-context.md` or of an oversized plan, or a shell read (`cat`, `sed`, `head`, `Get-Content`, … as a command, not as part of a slug) of a `-context.md`, or `section.py` run with `--log` — `section.py` without it and a heading `grep` are the sanctioned routes; the reader list is a heuristic drawn from real transcripts, not a fence |
| R3 guide-whole | an agent whose `instructions.md` `Read` results exceed a KB budget |
| R4 batching | an implementer's share of small-sequential-shell-call runs over budget |
| R5 blocking-call | a tool call over the time budget — except `Agent`/`Task`, which dispatch a subagent and are meant to block for minutes |
| R6 planner-rewrite | a planner `Write` to a plan/context path already written earlier in the session |
| R7 / R8 / R9 reviewer- / implementer- / verifier-budget | turns, tokens, or (implementer only) context-per-turn over that role's budget |
| R10 driver-discipline | a driver shell command that builds or tests, a driver `Edit`/`Write` outside `.claude/workorders/`, or too many driver turns in one round — judged only while it is driving: one window per `/workorder` invocation, from the invocation to the first message the user types after that invocation's last pipeline agent finished (a phase agent, a reviewer, anything in a workflow run — an ad-hoc agent asked for later does not hold it open; harness-written `user` records are not the user), or to the next invocation, so a build the user asks for afterwards, or between two workorders, is not the driver's violation |
| R11 replans | two or more planner runs in one session |
| R12 plan-size | a plan or context file whose planner-authored part is over its KB budget, from the `Read` calls that touched it — `## Log` is not counted, being what the scribe, implementer and driver append while the rounds run |
| R13 round-budget | a round's total subagent tokens over budget |
| R14 reviewer-reruns-suite | a reviewer running test suites or builds more than twice (the two reviewers told to build and test are exempt) |
| R15 edit-guard-workaround | a subagent whose `Edit`/`Write` was refused by the harness's worktree guard ("is in the base repo checkout") and which then made more than five further tool calls (its own return not counted) instead of returning `PLAN-DEFECT` — unless an edit of the same repo-relative path then landed inside a worktree, which is a mistyped path corrected, not a workaround (a same-named scratch copy is the workaround) |
| R16 scribe-scope | a scribe (`agentType: "scribe"`, or the `scribe` role a workflow label like `scribe:r1` parses to) whose `Edit`/`Write` landed outside its own `.claude/workorders/`, judged against the transcript's own `cwd` rather than a bare substring test; which ran `git add`/`git commit` in any shell command; which wrote a file through a shell command instead (a redirect or heredoc, `tee`, a PowerShell content cmdlet, `cp`/`mv`/`rm`/`sed -i`, a Python file write) whatever the target path; or, for the restricted `scribe` agent type, ran any shell command at all |

Every budget is a named module-level constant in the tool itself
(`IMPLEMENTER_MAX_TURNS`, `VERIFIER_MAX_TOKENS`, `BATCHABLE_SHARE_MAX`, and so
on), each with a comment naming the measurement it was set from — read those
constants for the current number rather than one copied here, since
re-measuring is exactly what this tool exists to make cheap. Exit code is 0
when every rule passes, 1 when any rule fails, 2 on a usage error.

Tests (`tests/test_workorder_audit.py`) build synthetic transcripts in a temp
directory; every rule has both a failing fixture and a passing control, plus
coverage for message-id dedupe, workflow-subdirectory discovery, and the exit
codes.

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

`implementer.md` is the rule that sends the implementer here: for a source
file over 2,000 lines, run `source_index.py --find <name>` first and `Read`
only the range it prints, instead of an exploratory grep chain. Measured
against the file it was built for (`ForgePact/plugin/ModuleMain.cpp`, 997KB /
18,144 lines): `--regions` prints 94 regions in about 6KB.

Tests (`tests/test_source_index.py`) cover a synthetic fixture (banners,
nested guard spans, a function inside and outside a guard, `--find`, `--at`)
plus a smoke test against the real `ModuleMain.cpp`, skipped when the file is
absent — as it is in a worktree with the ForgePact submodule uninitialized.

## MCP servers — `../.mcp.json`

| Server | For |
|---|---|
| `tauri-hub` | driving a running debug hub through its bridge on `127.0.0.1:9223` |
| `hs-drive` | reporting whether Hero Siege is running, backing up / restoring `hs2saves\`, and driving the modded game (launch, `bp_ipc` command + reply, screenshot, keyboard/mouse injection, graceful close) — a local stdio server in `tools/hs_drive_mcp/` |
| `context7` | live library documentation; `AGENTS.md` § "YYToolkit Integration" already assumes it |
| `github` | releases, dispatches and pointer PRs across the eleven repositories |

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
[`docs/tools/hs-drive-mcp.md`](../docs/tools/hs-drive-mcp.md) has the tool
surface, the refusal vocabulary and the sharp edges, including why the server's
process must keep the real `LOCALAPPDATA`.

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

Fifteen suites cover this page's tooling. Fourteen are Python and run
automatically under the first command below; the workflow script's own routing is
JavaScript and runs separately, under Node:

```bash
py -3 -m unittest discover -s tests
py -3 -m unittest tests.test_claude_hooks -v      # the hooks actually block
py -3 -m unittest tests.test_claude_agents -v     # the definitions are well-formed
py -3 -m unittest tests.test_claude_workorder -v  # round_delta.py + ensure_submodule.py, one round/submodule at a time
py -3 -m unittest tests.test_claude_workorder_section -v  # section.py, plus the sentences in agents/ and SKILL.md that carry the same lesson
py -3 -m unittest tests.test_workorder_audit -v   # workorder_audit.py's rules, each with a failing fixture and a passing control
py -3 -m unittest tests.test_source_index -v      # source_index.py against a synthetic fixture, plus a real-ModuleMain.cpp smoke test
py -3 -m unittest tests.test_hs_drive_mcp_server -v            # the hs-drive tool surface, over a real stdio session
py -3 -m unittest tests.test_hs_drive_mcp_engine_bridge -v     # ENGINE_SYMBOLS still resolve, and importing the engine starts nothing
py -3 -m unittest tests.test_hs_drive_mcp_saves -v             # the fail-closed save backup/restore contract
py -3 -m unittest tests.test_hs_drive_mcp_launch -v            # launch through ForgePact's engine, readiness, WM_CLOSE vs TerminateProcess
py -3 -m unittest tests.test_hs_drive_mcp_ipc -v               # the bp_ipc command channel, against a fake consumer
py -3 -m unittest tests.test_hs_drive_mcp_screenshot -v        # window resolution, both capture methods, the flat-image warning
py -3 -m unittest tests.test_hs_drive_mcp_input -v             # what hs_input actually injects, and the foreground it refuses without
py -3 -m unittest tests.test_hs_drive_mcp_charselect -v        # hs_select_character's click sequence, its proof and every refusal
py -3 -m unittest tests.test_hs_drive_mcp_release_boundary -v  # no release input mentions hs-drive
node --test .claude/workflows/workorder-rounds.test.mjs   # workflow mode's routing
```

Those seven stay green on CI's `ubuntu-latest` runner, where neither Windows,
the SDK, nor any submodule is present — but only the parts that need one skip.
The engine-bridge, launch and screenshot suites skip wholesale (launching a
process, enumerating windows and grabbing the screen are Windows-only); the
server suite skips its stdio and `hs_status` classes but still runs
`SelfCheckSummaryTests`, which drives `run_checks` over a stub registry and so
needs nothing; the release-boundary suite skips only its submodule check; and
the saves and IPC suites run in full, against fixtures — the IPC one because
its gate is injected and its whole channel is two files in a temporary
directory, which is deliberate: it covers the rules most likely to be broken by
an edit somewhere else. Each skip names its reason.

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
